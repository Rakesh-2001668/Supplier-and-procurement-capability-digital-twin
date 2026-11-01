"""IT services template control (BP §23, pending workflow 40): software licence entitlements, usage records and the unused-licence
flag raised before the contract renewal alert (F4-10).

Rule ``LICENCE-UTILISATION``: ``minUtilisationPct`` (flag when the peak use over the look-back window is below it), ``lookbackDays``
and ``flagLeadDays`` (the review runs this many days before the renewal alert, which fires ``CONTRACT-APPROVAL.renewalNoticeDays``
before the contract ends)."""
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import Contract, LicenceEntitlement, LicenceUsage, Supplier, Task, Timer
from app.pic.platform import audit, clock, outbox, workflow
from app.pic.platform.errors import Problem, illegal_transition, not_found, rule_violation
from app.pic.platform.money import D, fmt_inr
from app.pic.platform.serialize import jsonable, row
from app.pic.services import ind_common
from app.pic.services.common import principal, supplier_ref

REVIEW_TIMER = "LICENCE_REVIEW"
MAX_IMPORT_ROWS = 5000


def _rule(session: Session):
    return ind_common.require_rule(session, "LICENCE-UTILISATION", "Licence utilisation")


def _review_due(session: Session, entitlement: LicenceEntitlement, rule) -> datetime:
    """Before the renewal alert: renewalNoticeDays + flagLeadDays before the term end (the alert itself is at 09:00 IST)."""
    notice = ind_common.rule_or_none(session, "CONTRACT-APPROVAL")
    days = int((notice.body.get("renewalNoticeDays") if notice else 0) or 0) + int(rule.body.get("flagLeadDays", 30))
    return clock.at_ist(entitlement.term_end - timedelta(days=days), 8)


def create_entitlement(session: Session, *, supplier: str, product: str, entitled_qty, unit_price_minor: int, term_start: date, term_end: date,
                       metric: str = "USER", contract: Optional[str] = None) -> LicenceEntitlement:
    p = principal(session)
    rule = _rule(session)
    supplier_row = supplier_ref(session, supplier)
    qty = D(entitled_qty)
    if qty <= 0 or unit_price_minor < 0:
        raise Problem(422, "INVALID_ENTITLEMENT", "The entitled quantity is positive and the price not negative", rule_ref=rule.ref)
    if term_end <= term_start:
        raise rule_violation("The term ends after it starts", rule.ref)
    contract_row = None
    if contract:
        from app.pic.services.common import by_ref
        contract_row = by_ref(session, Contract, contract)
        if contract_row.supplier_id != supplier_row.id:
            raise rule_violation(f"{contract_row.number} is not a contract with {supplier_row.code}", rule.ref)
    entitlement = LicenceEntitlement(
        tenant_id=current_tenant(session), number=ind_common.number(session, "LICENCE", "LIC-", 1001, 0), contract_id=contract_row.id if contract_row else None,
        supplier_id=supplier_row.id, product=product, metric=metric.upper(), entitled_qty=qty, unit_price_minor=unit_price_minor, term_start=term_start,
        term_end=term_end, status="ACTIVE", created_by=p.user_id)
    session.add(entitlement)
    session.flush()
    workflow.create_timer(session, REVIEW_TIMER, "LICENCE", entitlement.id, _review_due(session, entitlement, rule))
    audit.record(session, "LICENCE", entitlement.id, "CREATED", object_ref=entitlement.number, rule_set_version=rule.ref,
                 after={"supplier": supplier_row.code, "product": product, "metric": entitlement.metric, "entitledQty": jsonable(qty),
                        "unitPriceMinor": unit_price_minor, "termEnd": term_end.isoformat(), "contract": contract_row.number if contract_row else None})
    return entitlement


def import_usage(session: Session, records: list[dict], source: str = "IMPORT") -> dict:
    """Usage records from the licence portal or an SSO / device report: [{licence: LIC-1001, as_of: date, used_qty: n}]. A record for
    an (entitlement, date) that exists replaces it, so re-importing a report is safe. Utilisation and the flag are re-evaluated for
    every entitlement touched."""
    p = principal(session)
    rule = _rule(session)
    if not records:
        raise Problem(422, "VALIDATION_FAILED", "No usage records")
    if len(records) > MAX_IMPORT_ROWS:
        raise Problem(413, "TOO_MANY_ROWS", f"At most {MAX_IMPORT_ROWS} records per import")
    numbers = sorted({r["licence"] for r in records})
    found = {e.number: e for e in session.execute(select(LicenceEntitlement).where(LicenceEntitlement.number.in_(numbers))).scalars()}
    missing = [n for n in numbers if n not in found]
    if missing:
        raise Problem(404, "NOT_FOUND", f"Unknown licence entitlement(s): {', '.join(missing)}")
    imported = 0
    for record in records:
        entitlement = found[record["licence"]]
        used = D(record["used_qty"])
        if used < 0:
            raise Problem(422, "INVALID_USAGE", f"{entitlement.number}: used quantity cannot be negative", rule_ref=rule.ref)
        as_of = record["as_of"] if isinstance(record["as_of"], date) else date.fromisoformat(str(record["as_of"]))
        if as_of > clock.today():
            raise Problem(422, "INVALID_USAGE", f"{entitlement.number}: usage cannot be dated in the future ({as_of.isoformat()})", rule_ref=rule.ref)
        statement = pg_insert(LicenceUsage).values(id=uuid.uuid7(), tenant_id=current_tenant(session), entitlement_id=entitlement.id, as_of=as_of,
                                                   used_qty=used, source=source, created_at=clock.now(), created_by=p.user_id, row_version=1)
        session.execute(statement.on_conflict_do_update(index_elements=["tenant_id", "entitlement_id", "as_of"],
                                                        set_={"used_qty": used, "source": source, "updated_at": clock.now()}))
        imported += 1
    session.flush()
    results = [evaluate(session, e, rule) for e in found.values()]
    audit.record(session, "LICENCE_USAGE_IMPORT", uuid.uuid5(uuid.NAMESPACE_URL, f"usage:{current_tenant(session)}:{clock.now().isoformat()}"), "IMPORTED",
                 object_ref=f"{imported} records", after={"records": imported, "licences": numbers, "source": source}, rule_set_version=rule.ref)
    return {"imported": imported, "licences": results}


def evaluate(session: Session, entitlement: LicenceEntitlement, rule=None, *, raise_task: bool = True) -> dict:
    """Utilisation over the look-back window = peak use ÷ entitled quantity. Below ``minUtilisationPct`` the entitlement is flagged
    UNUSED with the unused quantity and the yearly saving of removing it, and a review task goes to the category manager (once
    per flag); a later import that brings utilisation back above the threshold clears the flag."""
    rule = rule or _rule(session)
    lookback = int(rule.body.get("lookbackDays", 90))
    since = clock.today() - timedelta(days=lookback)
    peak, last_on = session.execute(select(func.max(LicenceUsage.used_qty), func.max(LicenceUsage.as_of)).where(
        LicenceUsage.entitlement_id == entitlement.id, LicenceUsage.as_of >= since)).one()
    if peak is None:
        return licence_view(session, entitlement)
    peak = D(peak)
    utilisation = (peak / entitlement.entitled_qty * 100).quantize(Decimal("0.01"))
    unused = max(entitlement.entitled_qty - peak, Decimal(0))
    entitlement.peak_used_qty, entitlement.utilisation_pct, entitlement.unused_qty = peak, utilisation, unused
    entitlement.potential_saving_minor = int(unused * entitlement.unit_price_minor)
    entitlement.last_usage_on = last_on
    threshold = D(rule.body.get("minUtilisationPct", 80))
    flagged_before = entitlement.flag
    if utilisation < threshold and entitlement.status == "ACTIVE":
        if flagged_before != "UNUSED":
            entitlement.flag, entitlement.flagged_at = "UNUSED", clock.now()
            audit.record(session, "LICENCE", entitlement.id, "FLAGGED_UNUSED", object_ref=entitlement.number, rule_set_version=rule.ref,
                         after={"utilisationPct": str(utilisation), "thresholdPct": str(threshold), "unusedQty": jsonable(unused),
                                "potentialSavingMinor": entitlement.potential_saving_minor})
            outbox.emit(session, "licence.unused_flagged", "LICENCE", entitlement.id, entitlement.number,
                        {"utilisationPct": str(utilisation), "unusedQty": str(unused), "potentialSavingMinor": entitlement.potential_saving_minor,
                         "termEnd": entitlement.term_end.isoformat()})
            if raise_task:
                _open_review(session, entitlement, utilisation, unused, rule)
    elif flagged_before == "UNUSED":
        entitlement.flag, entitlement.flagged_at = None, None
        audit.record(session, "LICENCE", entitlement.id, "FLAG_CLEARED", object_ref=entitlement.number,
                     after={"utilisationPct": str(utilisation), "thresholdPct": str(threshold)}, rule_set_version=rule.ref)
    return licence_view(session, entitlement)


def _open_review(session: Session, entitlement: LicenceEntitlement, utilisation: Decimal, unused: Decimal, rule) -> None:
    supplier = session.get(Supplier, entitlement.supplier_id)
    ind_common.open_task(session, "LICENCE_RIGHTSIZE", "CATEGORY_MANAGER", object_type="LICENCE", object_id=entitlement.id, object_ref=entitlement.number,
                         rule_set_version=rule.ref, scope=None,
                         evidence={"supplier": supplier.code, "product": entitlement.product, "entitledQty": jsonable(entitlement.entitled_qty),
                                   "peakUsedQty": jsonable(entitlement.peak_used_qty), "utilisationPct": jsonable(utilisation), "unusedQty": jsonable(unused),
                                   "potentialSavingMinor": entitlement.potential_saving_minor, "termEnd": entitlement.term_end.isoformat(),
                                   "action": "Reduce the licence count at renewal, or reassign the unused licences"})


@workflow.on_timer(REVIEW_TIMER)
def _review(session: Session, timer: Timer) -> None:
    """Scheduled review ahead of the renewal alert: evaluate the usage on file and flag the entitlement if it is under-used."""
    entitlement = session.get(LicenceEntitlement, timer.object_id)
    if entitlement is None or entitlement.status != "ACTIVE":
        return
    evaluate(session, entitlement)
    audit.record(session, "LICENCE", entitlement.id, "RENEWAL_REVIEW", object_ref=entitlement.number, rule_set_version="LICENCE-UTILISATION",
                 after={"flag": entitlement.flag, "utilisationPct": jsonable(entitlement.utilisation_pct), "termEnd": entitlement.term_end.isoformat()})


@workflow.on_task("LICENCE_RIGHTSIZE")
def _rightsize_decided(session: Session, task: Task, outcome: str) -> None:
    entitlement = session.get(LicenceEntitlement, task.object_id)
    if entitlement is not None:
        audit.record(session, "LICENCE", entitlement.id, "RIGHTSIZE_" + outcome, object_ref=entitlement.number, reason=task.comment,
                     after={"unusedQty": jsonable(entitlement.unused_qty), "potentialSavingMinor": entitlement.potential_saving_minor})


def end_entitlement(session: Session, entitlement: LicenceEntitlement, reason: str) -> LicenceEntitlement:
    if not (reason or "").strip():
        raise Problem(422, "REASON_REQUIRED", "Give the reason")
    if entitlement.status != "ACTIVE":
        raise illegal_transition("Licence entitlement", entitlement.number, entitlement.status, "end")
    entitlement.status, entitlement.flag = "ENDED", None
    for timer in session.execute(select(Timer).where(Timer.object_id == entitlement.id, Timer.kind == REVIEW_TIMER, Timer.fired_at.is_(None))).scalars():
        timer.fired_at, timer.payload = clock.now(), {"cancelled": True}
    audit.record(session, "LICENCE", entitlement.id, "ENDED", object_ref=entitlement.number, reason=reason)
    return entitlement


def licence_view(session: Session, entitlement: LicenceEntitlement) -> dict:
    supplier = session.get(Supplier, entitlement.supplier_id)
    contract = session.get(Contract, entitlement.contract_id) if entitlement.contract_id else None
    return row(entitlement, extra={"version": entitlement.row_version, "supplier": supplier.code, "supplierName": supplier.legal_name, "contract": contract.number if contract else None,
                                   "daysToRenewal": (entitlement.term_end - clock.today()).days,
                                   "yearlyCostMinor": int(entitlement.entitled_qty * entitlement.unit_price_minor)})


def summary(session: Session) -> dict:
    """Portfolio view: entitlements with utilisation, flagged ones first, and the yearly saving the flags represent."""
    rows = session.execute(select(LicenceEntitlement).where(LicenceEntitlement.status == "ACTIVE")
                           .order_by(LicenceEntitlement.flag.asc().nulls_last(), LicenceEntitlement.term_end)).scalars().all()
    views = [licence_view(session, e) for e in rows]
    flagged = [v for v in views if v["flag"] == "UNUSED"]
    return {"licences": views, "flagged": len(flagged), "potentialSavingMinor": sum(v["potential_saving_minor"] or 0 for v in flagged),
            "yearlyCostMinor": sum(v["yearlyCostMinor"] for v in views)}
