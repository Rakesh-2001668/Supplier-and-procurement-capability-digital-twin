"""Financial-risk and news feeds (Technical Document §12.3) into supplier risk signals.

Provider adapter interface plus a generic REST/JSON adapter and signed webhook ingestion. The rules that turn a signal into a
mitigation, a hold or a score belong to ``risk.py``; this module only normalises provider events and calls ``risk.ingest``.

    FeedAdapter.fetch(since)  -> list[FeedEvent]            (pull)
    ingest_event(session, source, event) -> ledger row      (pull and webhook)

Generic REST/JSON adapter, per provider NAME (upper case) in ``PIC_RISKFEED_PROVIDERS`` (comma separated):

    PIC_RISKFEED_<NAME>_URL        endpoint returning the events; ``since`` is sent as ?since=<ISO date> when the provider supports it
    PIC_RISKFEED_<NAME>_API_KEY    sent as Authorization: Bearer and X-API-Key
    PIC_RISKFEED_<NAME>_MAP        JSON field map, defaults shown:
        {"items": "events", "id": "id", "supplier": "supplier", "gstin": "gstin", "pan": "pan", "name": "name", "category": "category",
         "severity": "severity", "title": "title", "detail": "detail",
         "categories": {"financial": "FINANCIAL", "news": "COMPLIANCE", ...}, "severities": {"critical": "Critical", "red": "High", ...}}
    PIC_RISKFEED_<NAME>_WEBHOOK_SECRET  HMAC-SHA256 key; the provider signs the raw body: header X-PIC-Signature: sha256=<hex>
    PIC_RISKFEED_<NAME>_TIMEOUT, _RETRIES

Events are matched to a supplier by PIC code, GSTIN or PAN (blind index, never stored in clear) or the normalised legal name; an event
that matches nothing is kept in the ledger as UNMATCHED for review. (source, event id) is unique, so a repeated delivery is a DUPLICATE.
"""
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import RiskFeedEvent, Supplier
from app.pic.platform import audit, clock, crypto
from app.pic.platform.errors import Problem
from app.pic.services import ml_core, risk

DEFAULT_MAP = {"items": "events", "id": "id", "supplier": "supplier", "gstin": "gstin", "pan": "pan", "name": "name", "category": "category",
               "severity": "severity", "title": "title", "detail": "detail"}
DEFAULT_CATEGORIES = {"financial": "FINANCIAL", "credit": "FINANCIAL", "insolvency": "FINANCIAL", "news": "COMPLIANCE", "adverse_media": "COMPLIANCE",
                      "sanctions": "COMPLIANCE", "compliance": "COMPLIANCE", "fraud": "FRAUD", "cyber": "CYBER", "quality": "QUALITY", "delivery": "DELIVERY",
                      "geographic": "GEOGRAPHIC"}
DEFAULT_SEVERITIES = {"critical": "Critical", "high": "High", "red": "High", "severe": "Critical", "medium": "Medium", "amber": "Medium", "moderate": "Medium",
                      "low": "Low", "green": "Low", "info": "Low"}


@dataclass
class FeedEvent:
    event_id: str
    category: str
    severity: str
    title: str
    supplier_code: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    name: Optional[str] = None
    detail: dict = field(default_factory=dict)


class FeedError(Exception):
    pass


class FeedAdapter:
    """Interface of a provider adapter: ``fetch`` returns normalised events published since a date (ISO string) or all."""
    name = ""

    def configured(self) -> bool:
        raise NotImplementedError

    def fetch(self, since: Optional[str] = None) -> list[FeedEvent]:
        raise NotImplementedError

    def webhook_secret(self) -> Optional[str]:
        return None

    def normalise(self, raw: dict) -> FeedEvent:
        raise NotImplementedError


def _env(name: str, key: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(f"PIC_RISKFEED_{name}_{key}")
    return value.strip() if value and value.strip() else default


def _path(data, path: str):
    for part in (path or "").split("."):
        if part == "":
            continue
        data = data.get(part) if isinstance(data, dict) else None
    return data


class RestJsonAdapter(FeedAdapter):
    def __init__(self, name: str):
        self.name = name.upper()

    @property
    def mapping(self) -> dict:
        raw = _env(self.name, "MAP")
        try:
            custom = json.loads(raw) if raw else {}
        except ValueError:
            raise FeedError(f"PIC_RISKFEED_{self.name}_MAP is not valid JSON")
        return {**DEFAULT_MAP, **custom}

    def configured(self) -> bool:
        return bool(_env(self.name, "URL"))

    def webhook_secret(self) -> Optional[str]:
        return _env(self.name, "WEBHOOK_SECRET")

    def normalise(self, raw: dict) -> FeedEvent:
        m = self.mapping
        categories = {**DEFAULT_CATEGORIES, **{k.lower(): v for k, v in (m.get("categories") or {}).items()}}
        severities = {**DEFAULT_SEVERITIES, **{k.lower(): v for k, v in (m.get("severities") or {}).items()}}
        event_id = _path(raw, m["id"])
        if event_id in (None, ""):
            raise FeedError("event has no id")
        category = categories.get(str(_path(raw, m["category"]) or "").lower())
        severity = severities.get(str(_path(raw, m["severity"]) or "").lower())
        if category not in risk.MITIGATIONS:
            raise FeedError(f"category {_path(raw, m['category'])!r} is not mapped to a PIC risk category")
        if severity not in risk.SEVERITY_ORDER:
            raise FeedError(f"severity {_path(raw, m['severity'])!r} is not mapped to Critical/High/Medium/Low")
        title = str(_path(raw, m["title"]) or "").strip()
        if not title:
            raise FeedError("event has no title")
        detail = _path(raw, m["detail"])
        return FeedEvent(event_id=str(event_id)[:120], category=category, severity=severity, title=title[:200],
                         supplier_code=_path(raw, m["supplier"]), gstin=_path(raw, m["gstin"]), pan=_path(raw, m["pan"]), name=_path(raw, m["name"]),
                         detail=detail if isinstance(detail, dict) else {"text": detail} if detail else {})

    def fetch(self, since: Optional[str] = None, sleep: Callable[[float], None] = time.sleep) -> list[FeedEvent]:
        url = _env(self.name, "URL")
        if not url:
            raise FeedError(f"PIC_RISKFEED_{self.name}_URL is not set")
        if since:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode({"since": since})
        headers = {"accept": "application/json", "user-agent": "AlphaHelion PIC risk feed"}
        key = _env(self.name, "API_KEY")
        if key:
            headers.update({"authorization": f"Bearer {key}", "x-api-key": key})
        retries, timeout = int(_env(self.name, "RETRIES", "2")), float(_env(self.name, "TIMEOUT", "15"))
        delay, last = 0.5, ""
        for attempt in range(1, retries + 2):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:  # noqa: S310 - operator URL
                    payload = json.loads(response.read(20_000_000).decode("utf-8", "replace"))
                break
            except urllib.error.HTTPError as exc:
                last = f"HTTP {exc.code}"
                if exc.code not in (429, 500, 502, 503, 504):
                    raise FeedError(f"{self.name}: {last}")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = f"not reachable: {exc}"
            except ValueError:
                raise FeedError(f"{self.name}: unreadable JSON")
            if attempt > retries:
                raise FeedError(f"{self.name}: {last}")
            sleep(delay)
            delay *= 2
        items = _path(payload, self.mapping["items"]) if isinstance(payload, dict) and self.mapping["items"] else payload
        if not isinstance(items, list):
            raise FeedError(f"{self.name}: no list of events at '{self.mapping['items']}'")
        events = []
        for raw in items:
            if isinstance(raw, dict):
                try:
                    events.append(self.normalise(raw))
                except FeedError as exc:
                    events.append(FeedEvent(event_id=str(_path(raw, self.mapping["id"]) or f"invalid-{len(events)}"), category="", severity="",
                                            title="", detail={"error": str(exc), "raw": raw}))
        return events


def adapters() -> dict[str, FeedAdapter]:
    names = [n.strip().upper() for n in os.environ.get("PIC_RISKFEED_PROVIDERS", "").split(",") if n.strip()]
    return {n: RestJsonAdapter(n) for n in names}


# ---------------------------------------------------------------- matching and ingestion
def match_supplier(session: Session, event: FeedEvent) -> Optional[Supplier]:
    tid = current_tenant(session)
    if event.supplier_code:
        found = session.execute(select(Supplier).where(Supplier.code == str(event.supplier_code))).scalar_one_or_none()
        if found is not None:
            return found
    if event.gstin:
        found = session.execute(select(Supplier).where(Supplier.gstin_hash == crypto.blind_index(tid, event.gstin.upper()))).scalars().first()
        if found is not None:
            return found
    if event.pan:
        found = session.execute(select(Supplier).where(Supplier.pan_hash == crypto.blind_index(tid, event.pan.upper()))).scalars().first()
        if found is not None:
            return found
    if event.name:
        wanted = ml_core.normalise_text(event.name)
        for s in session.execute(select(Supplier)).scalars():
            if ml_core.normalise_text(s.legal_name) == wanted:
                return s
    return None


def ingest_event(session: Session, source: str, event: FeedEvent) -> dict:
    """Idempotent ingestion of one normalised event; always leaves a ledger row."""
    source = source.upper()[:40]
    existing = session.execute(select(RiskFeedEvent).where(RiskFeedEvent.source == source, RiskFeedEvent.event_id == event.event_id)).scalar_one_or_none()
    if existing is not None:
        return {"eventId": event.event_id, "status": "DUPLICATE", "firstStatus": existing.status}
    ledger = RiskFeedEvent(tenant_id=current_tenant(session), source=source, event_id=event.event_id, category=event.category or None,
                           severity=event.severity or None, status="REJECTED", payload={"title": event.title, "detail": event.detail},
                           received_at=clock.now())
    session.add(ledger)
    if not event.category or not event.severity or not event.title:
        ledger.reason = (event.detail.get("error") if isinstance(event.detail, dict) else None) or "incomplete event"
        session.flush()
        return {"eventId": event.event_id, "status": "REJECTED", "reason": ledger.reason}
    supplier = match_supplier(session, event)
    if supplier is None:
        ledger.status, ledger.reason = "UNMATCHED", "no supplier matches the code, GSTIN, PAN or name"
        session.flush()
        return {"eventId": event.event_id, "status": "UNMATCHED"}
    ledger.supplier_code = supplier.code
    signal = risk.ingest(session, supplier, source=source, category=event.category, severity=event.severity, title=event.title,
                         detail={**event.detail, "feed": source, "eventId": event.event_id}, key=event.event_id)
    ledger.status = "INGESTED"
    session.flush()
    audit.record(session, "SUPPLIER", supplier.id, "RISK_FEED_EVENT", object_ref=supplier.code, after={"source": source, "event": event.event_id,
                                                                                                         "category": event.category, "severity": event.severity})
    return {"eventId": event.event_id, "status": "INGESTED", "supplier": supplier.code, "newSignal": signal is not None}


def pull(session: Session, name: str, since: Optional[str] = None) -> dict:
    """Pull one provider and ingest every event (job callable)."""
    adapter = adapters().get(name.upper())
    if adapter is None or not adapter.configured():
        raise Problem(409, "FEED_NOT_CONFIGURED", f"Risk feed {name} is not configured: add it to PIC_RISKFEED_PROVIDERS and set PIC_RISKFEED_{name.upper()}_URL")
    try:
        events = adapter.fetch(since)
    except FeedError as exc:
        raise Problem(502, "FEED_UNAVAILABLE", str(exc))
    counts: dict[str, int] = {}
    for event in events:
        result = ingest_event(session, adapter.name, event)
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    return {"source": adapter.name, "events": len(events), "byStatus": counts}


def verify_signature(secret: str, body: bytes, header: Optional[str]) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return bool(header) and hmac.compare_digest(expected, header.strip())


def ingest_webhook(session: Session, source: str, body: bytes) -> dict:
    """Webhook body: one event object, a list of events, or {"events": [...]} in the provider's own format (mapped by the adapter)."""
    adapter = adapters().get(source.upper())
    if adapter is None:
        raise Problem(404, "FEED_UNKNOWN", f"No risk feed {source}")
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        raise Problem(422, "INVALID_JSON", "The webhook body is not JSON")
    items = data if isinstance(data, list) else data.get("events") if isinstance(data, dict) and isinstance(data.get("events"), list) else [data]
    results = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        try:
            event = adapter.normalise(raw)
        except FeedError as exc:
            event = FeedEvent(event_id=str(_path(raw, adapter.mapping["id"]) or f"invalid-{hashlib.sha256(body).hexdigest()[:12]}"), category="", severity="",
                              title="", detail={"error": str(exc)})
        results.append(ingest_event(session, adapter.name, event))
    return {"source": adapter.name, "received": len(results), "results": results}


def status(session: Session) -> dict:
    rows = session.execute(select(RiskFeedEvent.source, RiskFeedEvent.status)).all()
    by: dict = {}
    for source, state in rows:
        by.setdefault(source, {})
        by[source][state] = by[source].get(state, 0) + 1
    return {"providers": [{"name": n, "configured": a.configured(), "webhookSecret": bool(a.webhook_secret()), "events": by.get(n, {})} for n, a in adapters().items()],
            "ledger": by}
