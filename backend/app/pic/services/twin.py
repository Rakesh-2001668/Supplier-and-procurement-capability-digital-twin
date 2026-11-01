"""Supplier Capability Digital Twin connector (Technical Document §12.3).

Reads capability, evidence level, free capacity, trust and late-delivery probability for a supplier and category from the Twin API,
caches the answer in ``twin_snapshot`` (source TWIN_API) and falls back to the snapshot already there (seeded demo data, or the
last good Twin answer) when the Twin is not configured, unreachable or answers something invalid. Scorecards are written back.

    PIC_TWIN_URL              base URL of the Twin API
    PIC_TWIN_TOKEN            bearer token (or PIC_TWIN_API_KEY, sent as X-API-Key)
    PIC_TWIN_TIMEOUT          seconds per call (default 10)
    PIC_TWIN_RETRIES          retries on connection errors, 429 and 5xx (default 2)
    PIC_TWIN_CACHE_SECONDS    how long a Twin answer is fresh (default 3600)

Assumed API (to be confirmed against the Twin's OpenAPI at onboarding):
    GET  {url}/suppliers/{supplierRef}/capability?category=CAT
         -> {"capability": {...}, "evidenceLevel": "E1".."E4", "freeCapacityPerMonth": n, "trustScore": 0..1,
             "lateDeliveryProbability": 0..1, "ppm": n?, "leadTimeDays": n?, "asOf": "YYYY-MM-DD"?}
    POST {url}/suppliers/{supplierRef}/scorecards   (header Idempotency-Key)
         <- {"period": "YYYY-MM", "otifPct": n, "ppm": n, "invoiceAccuracyPct": n, "receipts": n, "source": "PIC"}
``supplierRef`` is the twin reference stored on the supplier (``twin_ref``) or, without one, the PIC supplier code.
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import AuditEvent, Scorecard, Supplier, TwinSnapshot
from app.pic.platform import audit, clock
from app.pic.platform.errors import Problem

EVIDENCE = ("E1", "E2", "E3", "E4")


class TwinError(Exception):
    pass


def _env(key: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(key)
    return value.strip() if value and value.strip() else default


def configured() -> bool:
    return bool(_env("PIC_TWIN_URL"))


def _headers(extra: Optional[dict] = None) -> dict:
    headers = {"accept": "application/json", "user-agent": "AlphaHelion PIC twin connector"}
    if _env("PIC_TWIN_TOKEN"):
        headers["authorization"] = f"Bearer {_env('PIC_TWIN_TOKEN')}"
    if _env("PIC_TWIN_API_KEY"):
        headers["x-api-key"] = _env("PIC_TWIN_API_KEY")
    headers.update(extra or {})
    return headers


def _call(method: str, path: str, body: Optional[dict] = None, headers: Optional[dict] = None, sleep: Callable[[float], None] = time.sleep) -> dict:
    url = f"{_env('PIC_TWIN_URL').rstrip('/')}{path}"
    data = json.dumps(body).encode() if body is not None else None
    retries, timeout = int(_env("PIC_TWIN_RETRIES", "2")), float(_env("PIC_TWIN_TIMEOUT", "10"))
    delay, last = 0.5, "no attempt"
    for attempt in range(1, retries + 2):
        request = urllib.request.Request(url, data=data, method=method, headers=_headers({**({"content-type": "application/json"} if data else {}), **(headers or {})}))
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-configured URL
                text = response.read(2_000_000).decode("utf-8", "replace")
                payload = json.loads(text) if text.strip() else {}
                if not isinstance(payload, dict):
                    raise TwinError("the Twin answered with something other than a JSON object")
                return payload
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
            if exc.code not in (429, 500, 502, 503, 504):
                raise TwinError(f"{last} from {url.split('?')[0]}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = f"not reachable: {exc}"
        except ValueError:
            raise TwinError("the Twin answered with unreadable JSON")
        if attempt <= retries:
            sleep(delay)
            delay *= 2
    raise TwinError(f"{url.split('?')[0]} {last}")


def _number(value, low: float, high: float, name: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise TwinError(f"{name} is missing or not a number")
    if not d.is_finite() or not Decimal(str(low)) <= d <= Decimal(str(high)):
        raise TwinError(f"{name} {d} is outside {low}..{high}")
    return d


def parse_capability(data: dict) -> dict:
    """Validate a Twin capability answer; raise TwinError when it cannot be trusted."""
    level = str(data.get("evidenceLevel") or "").upper()
    if level not in EVIDENCE:
        raise TwinError(f"evidenceLevel {level!r} is not one of {', '.join(EVIDENCE)}")
    out = {"evidence_level": level,
           "free_capacity_per_month": _number(data.get("freeCapacityPerMonth"), 0, 1e12, "freeCapacityPerMonth"),
           "trust_score": _number(data.get("trustScore"), 0, 1, "trustScore").quantize(Decimal("0.001")),
           "late_delivery_prob": _number(data.get("lateDeliveryProbability"), 0, 1, "lateDeliveryProbability").quantize(Decimal("0.001")),
           "capability": data.get("capability") if isinstance(data.get("capability"), dict) else {}}
    out["ppm"] = _number(data["ppm"], 0, 1e7, "ppm").quantize(Decimal("0.1")) if data.get("ppm") is not None else None
    out["lead_time_days"] = int(_number(data["leadTimeDays"], 0, 3650, "leadTimeDays")) if data.get("leadTimeDays") is not None else None
    out["as_of"] = (clock.today() if not data.get("asOf") else __import__("datetime").date.fromisoformat(str(data["asOf"])[:10]))
    return out


def supplier_ref(supplier: Supplier) -> str:
    return supplier.twin_ref if supplier.twin_ref and not supplier.twin_ref.startswith("ERP-VENDOR-") else supplier.code


def view(snapshot: TwinSnapshot, **extra) -> dict:
    return {"supplier": str(snapshot.supplier_id), "category": snapshot.category, "evidenceLevel": snapshot.evidence_level,
            "freeCapacityPerMonth": str(snapshot.free_capacity_per_month), "trustScore": str(snapshot.trust_score),
            "lateDeliveryProbability": str(snapshot.late_delivery_prob), "ppm": str(snapshot.ppm) if snapshot.ppm is not None else None,
            "leadTimeDays": snapshot.lead_time_days, "capability": snapshot.capability, "asOf": snapshot.as_of.isoformat(), "source": snapshot.source,
            "modelVersion": snapshot.model_version, "syncedAt": snapshot.synced_at.isoformat() if snapshot.synced_at else None, **extra}


def snapshot(session: Session, supplier: Supplier, category: str, *, force: bool = False, sleep: Callable[[float], None] = time.sleep) -> dict:
    """The twin view of a supplier for a category: fresh cache, else a Twin call, else the stored snapshot (``fallback`` true)."""
    row = session.execute(select(TwinSnapshot).where(TwinSnapshot.supplier_id == supplier.id, TwinSnapshot.category == category)).scalar_one_or_none()
    ttl = timedelta(seconds=int(_env("PIC_TWIN_CACHE_SECONDS", "3600")))
    if row is not None and row.source == "TWIN_API" and row.synced_at and clock.now() - row.synced_at < ttl and not force:
        return view(row, cached=True, fallback=False)
    if not configured():
        if row is None:
            raise Problem(404, "TWIN_UNAVAILABLE", f"No twin data for {supplier.code}/{category} and PIC_TWIN_URL is not set")
        return view(row, cached=False, fallback=True, reason="PIC_TWIN_URL is not set: seeded snapshot")
    try:
        data = parse_capability(_call("GET", f"/suppliers/{urllib.parse.quote(supplier_ref(supplier), safe='')}/capability?category={urllib.parse.quote(category)}",
                                      sleep=sleep))
    except TwinError as exc:
        if row is None:
            raise Problem(502, "TWIN_UNAVAILABLE", f"The Twin could not be read for {supplier.code}/{category}: {exc}")
        audit.record(session, "SUPPLIER", supplier.id, "TWIN_FALLBACK", object_ref=supplier.code, reason=str(exc)[:300], after={"category": category})
        return view(row, cached=False, fallback=True, reason=str(exc)[:300])
    created = row is None
    if row is None:
        row = TwinSnapshot(tenant_id=current_tenant(session), supplier_id=supplier.id, category=category, capability={}, evidence_level=data["evidence_level"],
                           free_capacity_per_month=data["free_capacity_per_month"], trust_score=data["trust_score"],
                           late_delivery_prob=data["late_delivery_prob"], as_of=data["as_of"])
        session.add(row)
    before = None if created else {"trust": str(row.trust_score), "lateDeliveryProb": str(row.late_delivery_prob), "evidence": row.evidence_level}
    row.capability, row.evidence_level = data["capability"], data["evidence_level"]
    row.free_capacity_per_month, row.trust_score = data["free_capacity_per_month"], data["trust_score"]
    row.late_delivery_prob, row.ppm, row.lead_time_days = data["late_delivery_prob"], data["ppm"], data["lead_time_days"]
    row.as_of, row.source, row.synced_at, row.model_version = data["as_of"], "TWIN_API", clock.now(), "twin-api"
    session.flush()
    audit.record(session, "SUPPLIER", supplier.id, "TWIN_SYNCED", object_ref=supplier.code, before=before,
                 after={"category": category, "trust": str(row.trust_score), "lateDeliveryProb": str(row.late_delivery_prob), "evidence": row.evidence_level})
    return view(row, cached=False, fallback=False)


def refresh_all(session: Session, *, sleep: Callable[[float], None] = time.sleep) -> dict:
    """Refresh every supplier/category snapshot (job callable). Failures fall back per row and are counted."""
    done = fallback = failed = 0
    suppliers = {s.id: s for s in session.execute(select(Supplier)).scalars()}
    for snap in session.execute(select(TwinSnapshot)).scalars().all():
        supplier = suppliers.get(snap.supplier_id)
        if supplier is None:
            continue
        try:
            result = snapshot(session, supplier, snap.category, force=True, sleep=sleep)
            fallback += 1 if result.get("fallback") else 0
            done += 0 if result.get("fallback") else 1
        except Problem:
            failed += 1
    return {"refreshed": done, "fallback": fallback, "failed": failed}


def write_back_scorecard(session: Session, supplier: Supplier, period: str, *, sleep: Callable[[float], None] = time.sleep) -> dict:
    """Write one monthly scorecard back to the Twin (idempotent: the key hashes the figures; the same figures are sent once)."""
    card = session.execute(select(Scorecard).where(Scorecard.supplier_id == supplier.id, Scorecard.period == period)).scalar_one_or_none()
    if card is None:
        raise Problem(404, "SCORECARD_NOT_FOUND", f"No scorecard {period} for {supplier.code}")
    if not configured():
        raise Problem(409, "TWIN_NOT_CONFIGURED", "Set PIC_TWIN_URL to write scorecards back to the Supplier Capability Twin")
    body = {"period": period, "otifPct": float(card.otif_pct) if card.otif_pct is not None else None, "ppm": float(card.ppm) if card.ppm is not None else None,
            "invoiceAccuracyPct": float(card.invoice_accuracy_pct) if card.invoice_accuracy_pct is not None else None, "receipts": card.receipts, "source": "PIC"}
    key = f"scorecard:{supplier.code}:{period}:{hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]}"
    already = session.execute(select(AuditEvent.event_id).where(AuditEvent.object_id == supplier.id, AuditEvent.action == "TWIN_SCORECARD_WRITTEN",
                                                                AuditEvent.reason == key)).first()
    if already:
        return {"supplier": supplier.code, "period": period, "status": "ALREADY_SENT", "key": key}
    try:
        _call("POST", f"/suppliers/{urllib.parse.quote(supplier_ref(supplier), safe='')}/scorecards", body, {"idempotency-key": key}, sleep=sleep)
    except TwinError as exc:
        raise Problem(502, "TWIN_WRITE_FAILED", f"The Twin rejected the scorecard of {supplier.code} {period}: {exc}")
    audit.record(session, "SUPPLIER", supplier.id, "TWIN_SCORECARD_WRITTEN", object_ref=supplier.code, reason=key, after=body)
    return {"supplier": supplier.code, "period": period, "status": "SENT", "key": key}


def write_back_period(session: Session, period: str, *, sleep: Callable[[float], None] = time.sleep) -> dict:
    sent = skipped = failed = 0
    for supplier in session.execute(select(Supplier).where(Supplier.id.in_(select(Scorecard.supplier_id).where(Scorecard.period == period)))).scalars().all():
        try:
            result = write_back_scorecard(session, supplier, period, sleep=sleep)
            sent += 1 if result["status"] == "SENT" else 0
            skipped += 1 if result["status"] != "SENT" else 0
        except Problem:
            failed += 1
    return {"period": period, "sent": sent, "alreadySent": skipped, "failed": failed}


def status(session: Session) -> dict:
    rows = session.execute(select(TwinSnapshot)).scalars().all()
    by_source: dict = {}
    for r in rows:
        by_source[r.source] = by_source.get(r.source, 0) + 1
    return {"configured": configured(), "cacheSeconds": int(_env("PIC_TWIN_CACHE_SECONDS", "3600")), "snapshots": len(rows), "bySource": by_source,
            "mode": "twin-api" if configured() else "seeded-snapshots"}
