"""Generic Idempotency-Key for every write under /v1 (Technical Document §10.1, API-2).

The HTTP layer (platform/http.py) calls ``begin`` before a POST/PUT/PATCH/DELETE that carries an ``Idempotency-Key`` and
``finish`` after the route ran:

- the key is reserved in ``idempotency_record`` (scope ``http:<user id>``, so keys are per user inside a tenant) in its own short
  transaction, so two concurrent requests with one key cannot both run: the second gets 409 REQUEST_IN_PROGRESS;
- the stored fingerprint is a hash of method, path, query and canonical body: the same key with anything different is
  422 IDEMPOTENCY_KEY_REUSED;
- a 2xx JSON response is stored (status, headers worth keeping, body) and replayed for 24 hours with
  ``Idempotent-Replayed: true``; the route does not run again;
- failures (4xx/5xx, exceptions) release the key: commands are atomic, so a corrected retry with the same key runs normally;
- routes that already honour the key through ``idempotent(...)`` (they store their own replay body) mark the request as
  handled; the generic reservation is then released after the route and only guards concurrency.

Records older than the TTL are ignored (and replaced); ``purge_expired`` deletes them (scheduled by the jobs framework).
"""
import hashlib
import json
import logging
import re
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

from app.pic.config import get_settings
from app.pic.db import tenant_tx
from app.pic.models import IdempotencyRecord
from app.pic.platform import clock
from app.pic.platform.errors import Problem

log = logging.getLogger("pic.idempotency")

# Set per request by the HTTP layer; Idempotent (platform/core.py) flags the request when a route does its own replay.
STATE: ContextVar[Optional[dict]] = ContextVar("pic_idempotency_state", default=None)

SKIP_PREFIXES = ("/v1/auth/",)  # sign-in and MFA answers hold tokens: never stored
KEY_PATTERN = re.compile(r"^[\x21-\x7e]{1,200}$")  # printable ASCII, no spaces
MAX_STORED_BYTES = 1_000_000
KEPT_HEADERS = ("content-type", "etag", "location", "content-language")
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


@dataclass
class Reservation:
    tenant_id: uuid.UUID
    scope: str
    key: str
    state: dict = field(default_factory=lambda: {"handled": False})


@dataclass
class Replay:
    status: int
    headers: dict
    body: str


def applies(method: str, path: str, key: Optional[str]) -> bool:
    return bool(key) and method in WRITE_METHODS and path.startswith("/v1/") and not path.startswith(SKIP_PREFIXES)


def fingerprint(method: str, path: str, query: str, content_type: str, body: bytes) -> str:
    canonical = body
    if "json" in (content_type or "").lower() and body:
        try:
            canonical = json.dumps(json.loads(body), sort_keys=True, separators=(",", ":")).encode()
        except ValueError:
            pass
    digest = hashlib.sha256()
    for part in (method.upper().encode(), path.encode(), query.encode(), canonical):
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.hexdigest()


def begin(principal, key: str, request_hash: str) -> tuple[Optional[Reservation], Optional[Replay]]:
    """Reserve the key, or return the stored response of an earlier identical request. Raises the 4xx problems above."""
    if not KEY_PATTERN.match(key):
        raise Problem(400, "IDEMPOTENCY_KEY_INVALID", "Idempotency-Key must be 1-200 printable ASCII characters without spaces (use a UUID)")
    settings = get_settings()
    scope = f"http:{principal.user_id}"
    ttl = timedelta(hours=settings.idempotency_ttl_hours)
    in_flight = timedelta(seconds=settings.idempotency_inflight_seconds)
    with tenant_tx(principal.tenant_id) as s:
        for _ in range(3):
            inserted = s.execute(
                insert(IdempotencyRecord)
                .values(tenant_id=principal.tenant_id, scope=scope, key=key, request_hash=request_hash)
                .on_conflict_do_nothing().returning(IdempotencyRecord.key)
            ).first()
            if inserted:
                return Reservation(principal.tenant_id, scope, key), None
            existing = s.get(IdempotencyRecord, (principal.tenant_id, scope, key))
            if existing is None:
                continue  # released between the insert and the read
            age = clock.now() - existing.created_at
            if age > ttl or (existing.response is None and age > in_flight):
                s.execute(delete(IdempotencyRecord).where(IdempotencyRecord.tenant_id == principal.tenant_id,
                                                          IdempotencyRecord.scope == scope, IdempotencyRecord.key == key))
                continue
            if existing.request_hash != request_hash:
                raise Problem(422, "IDEMPOTENCY_KEY_REUSED",
                              "This Idempotency-Key was already used with a different request (method, path, query or body)")
            if existing.response is None:
                raise Problem(409, "REQUEST_IN_PROGRESS", "A request with this Idempotency-Key is still being processed; retry shortly")
            stored = existing.response
            return None, Replay(existing.status_code or 200, stored.get("headers") or {}, stored.get("body") or "")
    raise Problem(409, "REQUEST_IN_PROGRESS", "The Idempotency-Key is being updated by another request; retry shortly")


def complete(reservation: Reservation, status: int, headers: dict, body: str) -> None:
    with tenant_tx(reservation.tenant_id) as s:
        record = s.get(IdempotencyRecord, (reservation.tenant_id, reservation.scope, reservation.key))
        if record is not None:
            record.status_code = status
            record.response = {"headers": headers, "body": body}


def release(reservation: Reservation) -> None:
    try:
        with tenant_tx(reservation.tenant_id) as s:
            s.execute(delete(IdempotencyRecord).where(
                IdempotencyRecord.tenant_id == reservation.tenant_id, IdempotencyRecord.scope == reservation.scope,
                IdempotencyRecord.key == reservation.key, IdempotencyRecord.response.is_(None)))
    except Exception:  # noqa: BLE001 - a stuck reservation expires after the in-flight timeout
        log.exception("could not release idempotency key")


def kept_headers(headers) -> dict:
    return {name: headers[name] for name in KEPT_HEADERS if name in headers}


def purge_expired(tenant_id: uuid.UUID) -> int:
    """Delete this tenant's records past the TTL (normally the scheduled job of engineer A's framework)."""
    cutoff = clock.now() - timedelta(hours=get_settings().idempotency_ttl_hours)
    with tenant_tx(tenant_id) as s:
        return s.execute(delete(IdempotencyRecord).where(IdempotencyRecord.created_at < cutoff)).rowcount or 0
