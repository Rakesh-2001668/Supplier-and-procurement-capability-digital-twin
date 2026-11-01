"""Logistics template controls (BP §23.1, pending workflow 41): detention, demurrage and accessorial charges with rate rules per
lane and carrier, proof-of-delivery evidence, service-entry approval and invoice matching; freight movements (distance and payload,
the denominator of cost per tonne-km); the index-value feed that contract index resets (fuel) read.

An accessorial claim is validated against the carrier's rate rule (free time, rate per hour / day / trip), needs an approved
proof-of-delivery service entry when ``FREIGHT-AUDIT.accessorialsNeedPod`` is set, and becomes a service entry (method UNIT_RATE)
on the accessorial line of the freight order. The service owner approves it like any service entry; the approved value is what the
carrier can invoice, so the standard SES invoice match and the freight audit (contracted rate × approved quantity) cover it."""
import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    AccessorialCharge, AccessorialRate, Contract, FreightMovement, IndexValue, PoLine, PurchaseOrder, ServiceEntry, SesLine, Supplier,
)
from app.pic.platform import audit, clock, outbox
from app.pic.platform.core import link
from app.pic.platform.errors import Problem, not_found, rule_violation
from app.pic.platform.money import D, fmt_inr, line_amount
from app.pic.platform.serialize import jsonable, row
from app.pic.services import ind_common
from app.pic.services.common import principal, supplier_ref

CHARGE_TYPES = ("DETENTION", "DEMURRAGE", "LOADING", "UNLOADING", "WAITING")
UNITS = ("HOUR", "DAY", "TRIP")
MAX_INDEX_ROWS = 2000


def _rule(session: Session, company_code: Optional[str] = None):
    return ind_common.require_rule(session, "FREIGHT-AUDIT", "Freight audit and accessorial charges", company_code=company_code)


# ---------------------------------------------------------------- rate rules
def add_rate(session: Session, *, charge_type: str, rate_minor: int, unit: str = "HOUR", free_units=0, supplier: Optional[str] = None,
             lane: Optional[str] = None, valid_from: Optional[date] = None, valid_to: Optional[date] = None) -> AccessorialRate:
    p = principal(session)
    _rule(session)
    charge_type, unit = charge_type.upper(), unit.upper()
    if charge_type not in CHARGE_TYPES or unit not in UNITS:
        raise Problem(422, "INVALID_RATE", f"charge_type is one of {', '.join(CHARGE_TYPES)}; unit one of {', '.join(UNITS)}")
    if rate_minor < 0 or D(free_units) < 0:
        raise Problem(422, "INVALID_RATE", "The rate and the free time are not negative")
    start = valid_from or clock.today()
    if valid_to is not None and valid_to < start:
        raise rule_violation("The rate cannot end before it starts", "FREIGHT-AUDIT")
    supplier_row = supplier_ref(session, supplier) if supplier else None
    rate = AccessorialRate(tenant_id=current_tenant(session), supplier_id=supplier_row.id if supplier_row else None, lane=lane, charge_type=charge_type,
                           unit=unit, free_units=D(free_units), rate_minor=rate_minor, valid_from=start, valid_to=valid_to, active=True,
                           created_by=p.user_id)
    session.add(rate)
    session.flush()
    audit.record(session, "ACCESSORIAL_RATE", rate.id, "CREATED", object_ref=f"{charge_type}/{lane or '*'}/{supplier_row.code if supplier_row else '*'}",
                 after={"unit": unit, "freeUnits": str(rate.free_units), "rateMinor": rate_minor, "validFrom": start.isoformat()}, rule_set_version="FREIGHT-AUDIT")
    return rate


def rate_for(session: Session, supplier_id: uuid.UUID, lane: Optional[str], charge_type: str, on: date) -> Optional[AccessorialRate]:
    """The most specific active rule valid on the date: carrier and lane, then carrier, then lane, then the tenant default."""
    candidates = session.execute(select(AccessorialRate).where(
        AccessorialRate.charge_type == charge_type, AccessorialRate.active.is_(True), AccessorialRate.valid_from <= on,
        (AccessorialRate.valid_to.is_(None)) | (AccessorialRate.valid_to >= on))).scalars().all()
    best, best_rank = None, (-1, date.min)
    for candidate in candidates:
        if candidate.supplier_id not in (None, supplier_id) or candidate.lane not in (None, lane):
            continue
        rank = ((candidate.supplier_id is not None) * 2 + (candidate.lane is not None), candidate.valid_from)
        if rank > best_rank:
            best, best_rank = candidate, rank
    return best


# ---------------------------------------------------------------- claims
def claim_charge(session: Session, po: PurchaseOrder, *, line: int, charge_type: str, units, occurred_on: date, lane: Optional[str] = None,
                 pod_ses: Optional[str] = None, note: Optional[str] = None) -> AccessorialCharge:
    """File a detention / demurrage / accessorial claim against an accessorial service line of a freight order (by the carrier on the
    portal or by the logistics team). Without the approved proof-of-delivery service entry (when the rule needs it), outside the rate
    rule's free time, or without value headroom on the order line the claim is recorded as BLOCKED / REJECTED with the reason and no
    service entry is raised."""
    from app.pic.services import receiving

    p = principal(session)
    rule = _rule(session, po.company_code)
    charge_type = charge_type.upper()
    if charge_type not in CHARGE_TYPES:
        raise Problem(422, "INVALID_CHARGE_TYPE", f"charge_type is one of {', '.join(CHARGE_TYPES)}", rule_ref=rule.ref)
    units = D(units)
    if units <= 0:
        raise Problem(422, "INVALID_QUANTITY", "The claimed units are positive", rule_ref=rule.ref)
    from app.pic.services.common import require_supplier_user
    require_supplier_user(session, po.supplier_id)
    po_line = session.execute(select(PoLine).where(PoLine.po_id == po.id, PoLine.line_no == line)).scalar_one_or_none()
    if po_line is None:
        raise not_found("PO line", f"{po.number}/{line}")
    if not po_line.ses_required:
        raise rule_violation(f"{po.number}/{line} is not a service line: accessorial charges are claimed on a service line", rule.ref)
    pod = None
    if pod_ses:
        # The POD is the service entry of the trip the charge arose on: an order of the same carrier (the accessorial allowance is often
        # a separate order from the trip it relates to).
        pod = session.execute(select(ServiceEntry).join(PurchaseOrder, PurchaseOrder.id == ServiceEntry.po_id).where(
            ServiceEntry.number == pod_ses, PurchaseOrder.supplier_id == po.supplier_id)).scalar_one_or_none()
        if pod is None:
            raise not_found("Proof-of-delivery service entry", f"{pod_ses} of carrier {session.get(Supplier, po.supplier_id).code}")
    number = ind_common.number(session, "ACCESSORIAL_CHARGE", "ACC-", 1001, 0)
    charge = AccessorialCharge(tenant_id=current_tenant(session), number=number, po_id=po.id, po_line_id=po_line.id, supplier_id=po.supplier_id, lane=lane,
                               charge_type=charge_type, occurred_on=occurred_on, units=units, pod_ses_id=pod.id if pod else None, status="CLAIMED",
                               created_by=p.user_id)
    session.add(charge)
    reason = None
    rate = rate_for(session, po.supplier_id, lane, charge_type, occurred_on)
    if rule.body.get("accessorialsNeedPod") and (pod is None or pod.status != "APPROVED"):
        reason = ("no approved proof of delivery: " + (f"{pod.number} is {pod.status.lower()}" if pod else "give the POD service entry")
                  + f" (rule {rule.ref}: accessorialsNeedPod)")
        charge.status = "BLOCKED"
    elif rate is None:
        reason = f"no {charge_type.lower()} rate rule for carrier / lane {lane or '-'} on {occurred_on.isoformat()}"
        charge.status = "BLOCKED"
    else:
        charge.free_units, charge.rate_minor = rate.free_units, rate.rate_minor
        charge.billable_units = max(units - rate.free_units, Decimal(0))
        charge.amount_minor = line_amount(charge.billable_units, rate.rate_minor)
        charge.rate_rule = {"rateId": str(rate.id), "unit": rate.unit, "freeUnits": str(rate.free_units), "rateMinor": rate.rate_minor,
                            "lane": rate.lane, "carrier": str(rate.supplier_id) if rate.supplier_id else None}
        if charge.billable_units == 0:
            charge.status, reason = "REJECTED", f"{units} {rate.unit.lower()}(s) are within the {rate.free_units} free {rate.unit.lower()}(s)"
    session.flush()
    if charge.status == "CLAIMED":
        try:
            with session.begin_nested():
                ses = receiving.create_ses(
                    session, po, method="UNIT_RATE", period_from=occurred_on, period_to=occurred_on,
                    lines=[{"line": line, "qty": str(charge.billable_units), "unit_rate": str(Decimal(charge.rate_minor) / 100),
                            "description": f"{charge_type.title()} {units} {rate.unit.lower()}(s), {rate.free_units} free – {charge.number}"
                                           + (f" – {note}" if note else "")}])
                receiving.submit_ses(session, ses)
                charge.ses_id = ses.id
        except Problem as exc:
            charge.status, reason = "BLOCKED", exc.detail
    charge.reason = reason
    link(session, "PURCHASE_ORDER", po.id, po.number, "ACCESSORIAL_CHARGE", charge.id, charge.number, "claimed_on")
    audit.record(session, "ACCESSORIAL_CHARGE", charge.id, "CLAIMED" if charge.status == "CLAIMED" else charge.status, object_ref=charge.number,
                 reason=reason, rule_set_version=rule.ref,
                 after={"po": po.number, "line": line, "type": charge_type, "units": str(units), "billableUnits": str(charge.billable_units),
                        "amountMinor": charge.amount_minor, "pod": pod.number if pod else None, "lane": lane, "serviceEntry": charge.ses_id and str(charge.ses_id)})
    outbox.emit(session, "accessorial.claimed", "ACCESSORIAL_CHARGE", charge.id, charge.number,
                {"po": po.number, "status": charge.status, "amountMinor": charge.amount_minor})
    return charge


def refresh_status(session: Session, charge: AccessorialCharge) -> AccessorialCharge:
    """CLAIMED follows its service entry: APPROVED once approved, REJECTED when the service owner rejects it."""
    if charge.status == "CLAIMED" and charge.ses_id:
        ses = session.get(ServiceEntry, charge.ses_id)
        if ses is not None and ses.status in ("APPROVED", "REJECTED", "REVOKED"):
            charge.status = "APPROVED" if ses.status == "APPROVED" else "REJECTED"
            if charge.status == "REJECTED":
                charge.reason = f"service entry {ses.number} was {ses.status.lower()}"
    return charge


@outbox.consumer("service_entry.approved", "accessorial-approved")
def _ses_approved(session: Session, event) -> None:
    for charge in session.execute(select(AccessorialCharge).where(AccessorialCharge.ses_id == event.object_id, AccessorialCharge.status == "CLAIMED")).scalars():
        refresh_status(session, charge)
        audit.record(session, "ACCESSORIAL_CHARGE", charge.id, "APPROVED", object_ref=charge.number, after={"amountMinor": charge.amount_minor},
                     rule_set_version="FREIGHT-AUDIT")


def accessorial_summary(session: Session, po_line: PoLine) -> dict:
    """The accessorial charges on a PO line, for the freight audit detail of an invoice line."""
    rows = session.execute(select(AccessorialCharge).where(AccessorialCharge.po_line_id == po_line.id).order_by(AccessorialCharge.number)).scalars().all()
    for charge in rows:
        refresh_status(session, charge)
    approved = [c for c in rows if c.status == "APPROVED"]
    return {"approvedMinor": sum(c.amount_minor for c in approved), "charges": [
        {"charge": c.number, "type": c.charge_type, "status": c.status, "amountMinor": c.amount_minor, "pod": c.pod_ses_id is not None} for c in rows]}


def charge_view(session: Session, charge: AccessorialCharge) -> dict:
    refresh_status(session, charge)
    po = session.get(PurchaseOrder, charge.po_id)
    line = session.get(PoLine, charge.po_line_id)
    pod = session.get(ServiceEntry, charge.pod_ses_id) if charge.pod_ses_id else None
    ses = session.get(ServiceEntry, charge.ses_id) if charge.ses_id else None
    supplier = session.get(Supplier, charge.supplier_id)
    return row(charge, extra={"po": po.number, "line": line.line_no, "carrier": supplier.code, "pod": pod.number if pod else None,
                              "serviceEntry": ses.number if ses else None, "serviceEntryStatus": ses.status if ses else None})


# ---------------------------------------------------------------- freight movements (cost per tonne-km)
def record_movement(session: Session, po: PurchaseOrder, *, line: int, reference: str, distance_km, payload_tonnes, moved_on: date,
                    lane: Optional[str] = None, ses: Optional[str] = None) -> FreightMovement:
    p = principal(session)
    _rule(session, po.company_code)
    km, tonnes = D(distance_km), D(payload_tonnes)
    if km <= 0 or tonnes <= 0:
        raise Problem(422, "INVALID_QUANTITY", "Distance and payload are positive")
    po_line = session.execute(select(PoLine).where(PoLine.po_id == po.id, PoLine.line_no == line)).scalar_one_or_none()
    if po_line is None:
        raise not_found("PO line", f"{po.number}/{line}")
    entry = None
    if ses:
        entry = session.execute(select(ServiceEntry).where(ServiceEntry.number == ses, ServiceEntry.po_id == po.id)).scalar_one_or_none()
        if entry is None:
            raise not_found("Service entry", ses)
    if session.execute(select(FreightMovement.id).where(FreightMovement.reference == reference)).first():
        raise Problem(409, "DUPLICATE_MOVEMENT", f"Consignment {reference} is already recorded")
    movement = FreightMovement(tenant_id=current_tenant(session), reference=reference, po_id=po.id, po_line_id=po_line.id, ses_id=entry.id if entry else None,
                               lane=lane, distance_km=km, payload_tonnes=tonnes, moved_on=moved_on, created_by=p.user_id)
    session.add(movement)
    session.flush()
    audit.record(session, "FREIGHT_MOVEMENT", movement.id, "RECORDED", object_ref=reference,
                 after={"po": po.number, "lane": lane, "distanceKm": str(km), "payloadTonnes": str(tonnes), "tonneKm": str(km * tonnes)})
    return movement


# ---------------------------------------------------------------- index feed (fuel and commodity indices)
def put_index_values(session: Session, index_code: str, values: list[dict], source: str = "IMPORT", source_ref: Optional[str] = None) -> dict:
    """Index values from a published source (import file or API): [{as_of, value, unit?}]. A value for a date that exists is replaced
    and audited (a revised publication); contract index resets read the latest value on or before their effective date."""
    p = principal(session)
    index_code = index_code.upper()
    if source not in ("IMPORT", "API", "MANUAL"):
        raise Problem(422, "INVALID_SOURCE", "source is IMPORT, API or MANUAL")
    if not values:
        raise Problem(422, "VALIDATION_FAILED", "No index values")
    if len(values) > MAX_INDEX_ROWS:
        raise Problem(413, "TOO_MANY_ROWS", f"At most {MAX_INDEX_ROWS} values per request")
    inserted = revised = 0
    for item in values:
        as_of = item["as_of"] if isinstance(item["as_of"], date) else date.fromisoformat(str(item["as_of"]))
        value = D(item["value"])
        if value <= 0:
            raise Problem(422, "INVALID_VALUE", f"{index_code} {as_of.isoformat()}: the index value must be positive")
        existing = session.execute(select(IndexValue).where(IndexValue.index_code == index_code, IndexValue.as_of == as_of)).scalar_one_or_none()
        if existing is None:
            session.add(IndexValue(tenant_id=current_tenant(session), index_code=index_code, as_of=as_of, value=value, unit=item.get("unit"), source=source,
                                   source_ref=source_ref, created_by=p.user_id))
            inserted += 1
        elif existing.value != value:
            audit.record(session, "INDEX_VALUE", existing.id, "REVISED", object_ref=f"{index_code}@{as_of.isoformat()}",
                         before={"value": str(existing.value)}, after={"value": str(value), "source": source})
            existing.value, existing.source, existing.source_ref = value, source, source_ref
            revised += 1
    session.flush()
    audit.record(session, "INDEX_FEED", uuid.uuid5(uuid.NAMESPACE_URL, f"index:{current_tenant(session)}:{index_code}"), "FED", object_ref=index_code,
                 after={"inserted": inserted, "revised": revised, "source": source, "sourceRef": source_ref})
    outbox.emit(session, "index.updated", "INDEX", uuid.uuid5(uuid.NAMESPACE_URL, f"index:{current_tenant(session)}:{index_code}"), index_code,
                {"index": index_code, "inserted": inserted, "revised": revised})
    return {"index": index_code, "inserted": inserted, "revised": revised}


def index_value_on(session: Session, index_code: str, on: Optional[date] = None) -> Optional[IndexValue]:
    on = on or clock.today()
    return session.execute(select(IndexValue).where(IndexValue.index_code == index_code.upper(), IndexValue.as_of <= on)
                           .order_by(IndexValue.as_of.desc()).limit(1)).scalar_one_or_none()


def reset_contract_from_feed(session: Session, contract: Contract, effective_from: Optional[date] = None) -> dict:
    """Index reset of an indexed contract (fuel clause) with the latest value on or before the effective date from the feed."""
    from app.pic.services import contract as contract_svc

    effective_from = effective_from or clock.today()
    if not contract.index_ref:
        raise rule_violation(f"{contract.number} carries no index clause", "CLM-INDEX")
    code = contract.index_ref["index"]
    value = index_value_on(session, code, effective_from)
    if value is None:
        raise Problem(409, "INDEX_VALUE_MISSING", f"No {code} value on or before {effective_from.isoformat()}: feed the index first", rule_ref="CLM-INDEX")
    result = contract_svc.index_reset(session, contract, value.value, effective_from)
    audit.record(session, "CONTRACT", contract.id, "INDEX_RESET_FROM_FEED", object_ref=contract.number,
                 after={"index": code, "asOf": value.as_of.isoformat(), "value": str(value.value), "source": value.source})
    return {**result, "index": code, "indexAsOf": value.as_of.isoformat(), "indexValue": str(value.value)}
