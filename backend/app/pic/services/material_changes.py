"""M03 change request for an existing material (pending workflows 17 and 18).

A change request carries the before/after of the changed master fields, an impact analysis (open POs, contracts, catalogue items,
info records, planning, stock), and one parallel steward task per owning domain. Who owns which field is rule data
(``MATERIAL-FIELD-OWNERSHIP``, per material type): a field that is not listed for the type cannot be changed (refused); a field
outside the requester's own steward domains is routed to the owning domain's steward, or refused when the rule says so
(``outsideOwnership``). Requester and approver are kept apart by SOD-06 (the F9 steward rule); the approvals must come from different
people. On the last approval the master is updated under a row lock, the version is raised, the full snapshot is kept in
``material_version`` and the ERP master is updated exactly once through the integration queue (key ``MAT|<number>|<version>``).
"""
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    CatalogueItem, ContractLine, Contract, EventLine, Forecast, InfoRecord, Material, MaterialChangeRequest, MaterialVersion, PlannedOrder, PoLine,
    PrLine, PurchaseOrder, QuotaArrangement, Requisition, SourceList, SourcingEvent, Stock, Task,
)
from app.pic.platform import audit, clock, integration, outbox, rules, sod, workflow
from app.pic.platform.core import next_number
from app.pic.platform.errors import Problem, illegal_transition, not_found
from app.pic.platform.serialize import jsonable, row
from app.pic.services.common import principal

TASK_KIND = "MATERIAL_CHANGE"
RULE = "MATERIAL-FIELD-OWNERSHIP"
SOD_REQUEST, SOD_APPROVE = "MATERIAL_REQUEST", "MATERIAL_STEWARD_APPROVE"  # SOD-06: the requester of a material may not approve it
OPEN_PO_STATUSES = ("DRAFT", "IN_APPROVAL", "RELEASED", "TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED", "RECEIVED")
LIVE_CONTRACT_STATUSES = ("DRAFT", "IN_NEGOTIATION", "IN_APPROVAL", "OUT_FOR_SIGNATURE", "ACTIVE", "EXPIRING")
GST_SLABS = {Decimal(x) for x in ("0", "0.1", "0.25", "1.5", "3", "5", "6", "7.5", "12", "18", "28")}
MRP_TYPES = ("PD", "ND", "VB", "VM")
LOT_POLICIES = ("EXACT", "FIXED", "EOQ", "PERIOD", "MINMAX")

# field → (label, kind, default owning domain). The kinds drive validation and normalisation.
FIELDS: dict[str, tuple[str, str, str]] = {
    "description": ("Description", "text:200", "PURCHASING"),
    "material_group": ("Material group", "text:30", "PURCHASING"),
    "category": ("Category", "text:40", "PURCHASING"),
    "mpn": ("Manufacturer part number", "text:60", "PURCHASING"),
    "attributes": ("Attributes", "dict", "PURCHASING"),
    "base_uom": ("Base unit of measure", "text:5", "PLANT"),
    "valuation_class": ("Valuation class", "text:10", "FINANCE"),
    "hsn_code": ("HSN / SAC code", "hsn", "FINANCE"),
    "gst_rate": ("GST rate %", "gst", "FINANCE"),
    "standard_price_minor": ("Standard price (paise)", "int", "FINANCE"),
    "quality_managed": ("Quality inspection managed", "bool", "QUALITY"),
    "mrp_type": ("MRP type", "enum:" + ",".join(MRP_TYPES), "PLANT"),
    "lot_size_policy": ("Lot-size policy", "enum:" + ",".join(LOT_POLICIES), "PLANT"),
    "lot_size_qty": ("Fixed lot size", "qty", "PLANT"),
    "min_lot": ("Minimum lot", "qty", "PLANT"),
    "max_lot": ("Maximum lot", "qty", "PLANT"),
    "pack_size": ("Pack size", "qty", "PLANT"),
    "safety_stock": ("Safety stock", "qty", "PLANT"),
    "planned_delivery_days": ("Planned delivery days", "days", "PLANT"),
    "gr_processing_days": ("Goods-receipt processing days", "days", "PLANT"),
}

DEFAULT_RULE = {
    # fields every material type may change, with their owning domain
    "fields": {name: spec[2] for name, spec in FIELDS.items()},
    # per material type: fields that do not apply (refused) and extra domains that must also approve a field's change
    "byType": {
        "SERVICE": {"notApplicable": ["base_uom", "quality_managed", "mrp_type", "lot_size_policy", "lot_size_qty", "min_lot", "max_lot",
                                      "pack_size", "safety_stock", "planned_delivery_days", "gr_processing_days"],
                    "alsoApprove": {}},
        "NON_STOCK": {"notApplicable": ["mrp_type", "lot_size_policy", "lot_size_qty", "min_lot", "max_lot", "safety_stock"],
                      "alsoApprove": {}},
        "STOCK": {"notApplicable": [],
                  "alsoApprove": {"base_uom": ["QUALITY", "FINANCE"], "valuation_class": ["PLANT"], "hsn_code": ["PURCHASING"],
                                  "gst_rate": ["PURCHASING"], "quality_managed": ["PLANT"]}},
    },
    "outsideOwnership": "ROUTE",  # ROUTE (to the owning domain's steward) | REFUSE (only a steward of the owning domain may request)
    "distinctApprovers": True,
    "domains": ["PURCHASING", "QUALITY", "FINANCE", "PLANT"],
}
HSN_RE = re.compile(r"^[0-9]{4}(?:[0-9]{2}){0,2}$")


def ownership_rule(session: Session, category: Optional[str] = None):
    """The tenant's MATERIAL-FIELD-OWNERSHIP rule; tenants bootstrapped before it existed use the built-in default."""
    try:
        rule = rules.resolve(session, RULE, category=category)
        return rule.ref, {**DEFAULT_RULE, **rule.body}
    except Problem as exc:
        if exc.code != "RULE_SET_MISSING":
            raise
        return f"{RULE}@default", DEFAULT_RULE


def ownership_view(session: Session, material_type: str) -> dict:
    ref, body = ownership_rule(session)
    spec = (body.get("byType") or {}).get(material_type, {})
    refused = set(spec.get("notApplicable") or [])
    fields = [{"field": name, "label": FIELDS[name][0] if name in FIELDS else name, "kind": FIELDS[name][1] if name in FIELDS else "text",
               "domain": domain, "alsoApprove": (spec.get("alsoApprove") or {}).get(name, [])}
              for name, domain in body["fields"].items() if name not in refused and name in FIELDS]
    return {"ruleSet": ref, "materialType": material_type, "outsideOwnership": body["outsideOwnership"], "fields": fields,
            "domains": body["domains"]}


# ---------------------------------------------------------------- normalisation
def _norm(field: str, value: Any) -> Any:
    label, kind, _ = FIELDS[field]
    bad = lambda why: Problem(422, "INVALID_FIELD", f"{label}: {why}", rule_ref=RULE, field=field)  # noqa: E731
    if kind.startswith("text"):
        limit = int(kind.split(":")[1])
        text = str(value if value is not None else "").strip()
        if field in ("mpn",) and not text:
            return None
        if field == "valuation_class" and not text:
            return None
        if not text:
            raise bad("must not be empty")
        if len(text) > limit:
            raise bad(f"at most {limit} characters")
        return text.upper() if field in ("base_uom", "material_group", "category") else text
    if kind == "dict":
        if not isinstance(value, dict):
            raise bad("must be an object of attribute names and values")
        return {str(k): v for k, v in sorted(value.items())}
    if kind == "hsn":
        text = str(value or "").strip()
        if not text:
            return None
        if not HSN_RE.match(text):
            raise bad("HSN/SAC must be 4, 6 or 8 digits")
        return text
    if kind == "gst":
        try:
            rate = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise bad("must be a number")
        if rate not in GST_SLABS:
            raise bad("is not a GST rate slab (0, 0.25, 3, 5, 12, 18, 28 ...)")
        return rate
    if kind == "int":
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise bad("must be a whole number")
        if number < 0:
            raise bad("cannot be negative")
        return number
    if kind == "bool":
        if not isinstance(value, bool):
            raise bad("must be true or false")
        return value
    if kind.startswith("enum:"):
        allowed = kind.split(":")[1].split(",")
        text = str(value or "").strip().upper()
        if text not in allowed:
            raise bad(f"must be one of {', '.join(allowed)}")
        return text
    if kind in ("qty", "days"):
        if value is None or value == "":
            if kind == "days":
                raise bad("is required")
            return None
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise bad("must be a number")
        if not number.is_finite() or number < 0:
            raise bad("cannot be negative")
        return int(number) if kind == "days" else number
    raise bad("unsupported field")


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float, Decimal)) and isinstance(b, (int, float, Decimal)) and not isinstance(a, bool):
        return Decimal(str(a)) == Decimal(str(b))
    return a == b


def _current(material: Material, field: str) -> Any:
    return getattr(material, field)


def snapshot_of(material: Material) -> dict:
    return jsonable({name: getattr(material, name) for name in
                     ("number", "description", "type", "material_group", "category", "base_uom", "valuation_class", "hsn_code", "gst_rate",
                      "mpn", "attributes", "mrp_type", "lot_size_policy", "lot_size_qty", "min_lot", "max_lot", "pack_size", "safety_stock",
                      "planned_delivery_days", "gr_processing_days", "quality_managed", "standard_price_minor", "annual_demand",
                      "ordering_cost_minor", "holding_rate", "status")})


def record_version(session: Session, material: Material, *, change: Optional[MaterialChangeRequest] = None, fields: Optional[list] = None,
                   reason: Optional[str] = None) -> MaterialVersion:
    """Keep the material master as of its current version (called when a material is created and on every applied change)."""
    existing = session.execute(select(MaterialVersion).where(MaterialVersion.material_id == material.id,
                                                             MaterialVersion.version == material.version)).scalar_one_or_none()
    if existing is not None:
        return existing
    entry = MaterialVersion(tenant_id=material.tenant_id, material_id=material.id, version=material.version, snapshot=snapshot_of(material),
                            changed_fields=fields or [], change_request_id=change.id if change else None, reason=reason, valid_from=clock.now(),
                            created_by=principal(session).user_id if session.info.get("principal") else None)
    session.add(entry)
    session.flush()
    return entry


# ---------------------------------------------------------------- impact analysis
def impact(session: Session, material: Material, fields: list[str]) -> dict:
    """What the change touches. ``blockers`` stop the request (unit of measure with stock or open documents); ``warnings`` are for the stewards."""
    po_rows = session.execute(
        select(PurchaseOrder.number, PurchaseOrder.status, PoLine.line_no, PoLine.qty, PoLine.received_qty, PoLine.uom).join(
            PoLine, PoLine.po_id == PurchaseOrder.id).where(PoLine.material_id == material.id, PurchaseOrder.status.in_(OPEN_PO_STATUSES))
        .order_by(PurchaseOrder.number)).all()
    contract_rows = session.execute(
        select(Contract.number, Contract.status, ContractLine.line_no).join(ContractLine, ContractLine.contract_id == Contract.id).where(
            ContractLine.material_id == material.id, Contract.status.in_(LIVE_CONTRACT_STATUSES)).order_by(Contract.number)).all()
    catalogue = session.execute(select(CatalogueItem.supplier_part_no, CatalogueItem.price_minor).where(
        CatalogueItem.material_id == material.id, CatalogueItem.active.is_(True))).all()
    info = session.execute(select(InfoRecord.plant, InfoRecord.last_price_minor).where(InfoRecord.material_id == material.id)).all()
    planned = session.execute(select(PlannedOrder.number, PlannedOrder.qty).where(
        PlannedOrder.material_id == material.id, PlannedOrder.status.in_(("CREATED", "FIRMED")))).all()
    pr_lines = session.execute(
        select(Requisition.number, PrLine.line_no).join(PrLine, PrLine.requisition_id == Requisition.id).where(
            PrLine.material_id == material.id, Requisition.status.in_(("SUBMITTED", "IN_APPROVAL", "APPROVED", "PARTIALLY_ORDERED")),
            PrLine.sourcing_status.in_(("OPEN", "IN_SOURCING")))).all()
    events = session.execute(
        select(SourcingEvent.number).join(EventLine, EventLine.event_id == SourcingEvent.id).where(
            EventLine.material_id == material.id, SourcingEvent.status.not_in(("AWARDED", "CANCELLED")))).scalars().all()
    stock = session.execute(select(func.coalesce(func.sum(Stock.qty), 0)).where(Stock.material_id == material.id)).scalar() or Decimal(0)
    forecasts = session.execute(select(func.count()).select_from(Forecast).where(Forecast.material_id == material.id)).scalar()
    source_lists = session.execute(select(func.count()).select_from(SourceList).where(SourceList.material_id == material.id)).scalar()
    quotas = session.execute(select(func.count()).select_from(QuotaArrangement).where(QuotaArrangement.material_id == material.id)).scalar()
    result = {
        "openPurchaseOrders": {"count": len({r[0] for r in po_rows}), "lines": [
            {"po": r[0], "status": r[1], "line": r[2], "openQty": str(max(r[3] - (r[4] or 0), 0)), "uom": r[5]} for r in po_rows[:25]]},
        "contracts": {"count": len({r[0] for r in contract_rows}), "lines": [{"contract": r[0], "status": r[1], "line": r[2]} for r in contract_rows[:25]]},
        "catalogueItems": {"count": len(catalogue), "items": [{"supplierPartNo": r[0], "priceMinor": r[1]} for r in catalogue[:25]]},
        "infoRecords": {"count": len(info), "plants": sorted({r[0] for r in info})},
        "planning": {"openPlannedOrders": len(planned), "forecastPeriods": forecasts, "sourceLists": source_lists, "quotaArrangements": quotas,
                     "openRequisitionLines": len(pr_lines), "liveSourcingEvents": sorted(set(events))},
        "stockQty": str(stock),
    }
    blockers, warnings = [], []
    open_documents = result["openPurchaseOrders"]["count"] or result["contracts"]["count"] or result["catalogueItems"]["count"]
    if "base_uom" in fields and (stock != 0 or open_documents):
        blockers.append("The unit of measure cannot change while the material has stock, open purchase orders, live contracts or catalogue items "
                        "(quantities would be reinterpreted): create a new material and migrate.")
    if {"hsn_code", "gst_rate"} & set(fields) and result["openPurchaseOrders"]["count"]:
        warnings.append(f"{result['openPurchaseOrders']['count']} open purchase order(s) keep the HSN / GST rate they were released with; "
                        "the new values apply to new documents.")
    if {"standard_price_minor", "valuation_class"} & set(fields) and stock != 0:
        warnings.append("Stock is on hand: Finance revalues through the ERP (price-change document) after the update.")
    if {"mrp_type", "lot_size_policy", "lot_size_qty", "min_lot", "max_lot", "pack_size", "safety_stock", "planned_delivery_days"} & set(fields) and (
            result["planning"]["openPlannedOrders"] or result["planning"]["openRequisitionLines"]):
        warnings.append("Open planned orders / requisitions keep their quantities; the next MRP run applies the new planning parameters.")
    if {"material_group", "category", "description"} & set(fields) and result["catalogueItems"]["count"]:
        warnings.append("Catalogue items stay linked to this material; their supplier descriptions are unchanged.")
    if "category" in fields and (result["planning"]["liveSourcingEvents"] or result["contracts"]["count"]):
        warnings.append("A category change affects live sourcing events and contracts reported by category.")
    result["blockers"], result["warnings"] = blockers, warnings
    return result


# ---------------------------------------------------------------- classify and request
def classify(session: Session, material: Material, changes: dict, requester_domains: list[str]) -> dict:
    """Validate, normalise and route the requested changes. Returns the change list, the approving domains and the rule reference."""
    if not isinstance(changes, dict) or not changes:
        raise Problem(422, "NO_CHANGES", "Give the fields to change and their new values", rule_ref=RULE)
    ref, body = ownership_rule(session, material.category)
    spec = (body.get("byType") or {}).get(material.type, {})
    refused_fields = set(spec.get("notApplicable") or [])
    unknown = [f for f in changes if f not in FIELDS]
    if unknown:
        raise Problem(422, "FIELD_NOT_CHANGEABLE", f"{', '.join(sorted(unknown))} cannot be changed by a change request (identity, status and "
                      "type are fixed; create a new material instead)", rule_ref=ref, fields=sorted(unknown))
    not_for_type = [f for f in changes if f in refused_fields or f not in body["fields"]]
    if not_for_type:
        raise Problem(422, "FIELD_NOT_CHANGEABLE", f"{', '.join(sorted(not_for_type))} do not apply to {material.type} materials",
                      rule_ref=ref, fields=sorted(not_for_type))
    out, domains, outside = [], [], []
    for field, raw in changes.items():
        new = _norm(field, raw)
        old = _current(material, field)
        if _same(old, new):
            continue
        owner = body["fields"][field]
        approvers = [owner] + [d for d in (spec.get("alsoApprove") or {}).get(field, []) if d != owner]
        routed = owner not in requester_domains
        if routed:
            outside.append(field)
        for domain in approvers:
            if domain not in domains:
                domains.append(domain)
        out.append({"field": field, "label": FIELDS[field][0], "from": jsonable(old), "to": jsonable(new), "domain": owner,
                    "alsoApprove": approvers[1:], "routed": routed})
    if not out:
        raise Problem(422, "NO_CHANGES", "The requested values equal the current master data", rule_ref=ref)
    if outside and body["outsideOwnership"] == "REFUSE":
        raise Problem(403, "OUTSIDE_OWNERSHIP", f"{', '.join(outside)} belong to other steward domains "
                      f"({', '.join(sorted({c['domain'] for c in out if c['routed']}))}); only a steward of the owning domain may request them",
                      rule_ref=ref, fields=outside)
    ordered = [d for d in body["domains"] if d in domains] + [d for d in domains if d not in body["domains"]]
    return {"changes": out, "domains": ordered, "ruleSet": ref, "distinct": bool(body.get("distinctApprovers", True)), "outside": outside}


def preview(session: Session, material: Material, changes: dict) -> dict:
    p = principal(session)
    plan = classify(session, material, changes, list(p.attr("steward_domains") or []))
    return {"material": material.number, "version": material.version, **plan,
            "impact": impact(session, material, [c["field"] for c in plan["changes"]])}


def request_change(session: Session, material: Material, changes: dict, reason: str) -> MaterialChangeRequest:
    p = principal(session)
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for the change", rule_ref="MDM-CHANGE")
    if material.status != "ACTIVE":
        raise Problem(409, "MATERIAL_NOT_ACTIVE", f"{material.number} is {material.status}; only active materials can be changed", rule_ref="MDM-CHANGE")
    pending = session.execute(select(MaterialChangeRequest.number).where(
        MaterialChangeRequest.material_id == material.id, MaterialChangeRequest.status == "IN_APPROVAL")).scalar()
    if pending:
        raise Problem(409, "CHANGE_PENDING", f"{pending} for {material.number} is still in approval", rule_ref="MDM-CHANGE")
    plan = classify(session, material, changes, list(p.attr("steward_domains") or []))
    result = impact(session, material, [c["field"] for c in plan["changes"]])
    if result["blockers"]:
        raise Problem(422, "IMPACT_BLOCKED", " ".join(result["blockers"]), rule_ref="MDM-CHANGE", impact=result)
    record_version(session, material, reason="baseline before the first change request")
    request = MaterialChangeRequest(
        tenant_id=current_tenant(session), number=next_number(session, "MATERIAL_CHANGE"), material_id=material.id, status="IN_APPROVAL",
        material_type=material.type, changes=plan["changes"], domains=plan["domains"], impact=result, reason=reason, requested_by=p.user_id,
        from_version=material.version, approvals=[], rule_set_version=plan["ruleSet"], created_by=p.user_id)
    session.add(request)
    session.flush()
    sod.record(session, SOD_REQUEST, {"material_request_id": request.id})
    audit.record(session, "MATERIAL", material.id, "CHANGE_REQUESTED", object_ref=material.number,
                 before={c["field"]: c["from"] for c in plan["changes"]}, after={c["field"]: c["to"] for c in plan["changes"]},
                 reason=reason, rule_set_version=plan["ruleSet"])
    audit.record(session, "MATERIAL_CHANGE_REQUEST", request.id, "CREATED", object_ref=request.number,
                 after={"material": material.number, "domains": plan["domains"], "routed": plan["outside"], "warnings": result["warnings"]},
                 reason=reason, rule_set_version=plan["ruleSet"])
    tasks = workflow.start_approval(
        session, None, TASK_KIND, object_type="MATERIAL_CHANGE_REQUEST", object_id=request.id, object_ref=request.number,
        chain=["MDM_STEWARD"] * len(plan["domains"]), mode="PARALLEL", step_id=None, initiator_id=p.user_id,
        rule_set_version=plan["ruleSet"],
        evidence={"material": material.number, "changes": plan["changes"], "impact": {k: v for k, v in result.items() if k in ("warnings",)}})
    for task, domain in zip(tasks, plan["domains"]):
        task.candidate_scope = {"steward_domain": domain}
        task.name = f"Approve {domain.lower()} data change · {request.number}"
    outbox.emit(session, "material.change.requested", "MATERIAL_CHANGE_REQUEST", request.id, request.number,
                {"material": material.number, "domains": plan["domains"], "fields": [c["field"] for c in plan["changes"]]})
    return request


# ---------------------------------------------------------------- approval
@workflow.guard_task(TASK_KIND)
def _guard(session: Session, task: Task, decision: str) -> None:
    request = session.get(MaterialChangeRequest, task.object_id)
    if request is None:
        return
    if request.status != "IN_APPROVAL":
        raise illegal_transition("Material change request", request.number, request.status, "decide")
    if decision != "APPROVE":
        return
    sod.guard(session, SOD_APPROVE, {"material_request_id": request.id})
    p = principal(session)
    _, body = ownership_rule(session)
    if body.get("distinctApprovers", True):
        others = session.execute(select(Task).where(Task.group_key == task.group_key, Task.id != task.id)).scalars()
        if any(t.completed_by == p.user_id and t.decision == "APPROVE" for t in others):
            raise Problem(409, "SOD_CONFLICT", "The domain approvals of a material change must come from different people", rule_ref="SOD-06")


@workflow.on_task(TASK_KIND)
def _decided(session: Session, task: Task, outcome: str) -> None:
    request = session.get(MaterialChangeRequest, task.object_id)
    material = session.execute(select(Material).where(Material.id == request.material_id).with_for_update()).scalar_one()
    tasks = session.execute(select(Task).where(Task.group_key == task.group_key).order_by(Task.sequence)).scalars().all()
    request.approvals = [{"domain": (t.candidate_scope or {}).get("steward_domain"), "by": str(t.completed_by), "decision": t.decision,
                          "at": t.completed_at.isoformat() if t.completed_at else None, "comment": t.comment} for t in tasks if t.completed_by]
    if outcome != "APPROVED":
        request.status = "REJECTED"
        request.rejection_reason = task.comment
        audit.record(session, "MATERIAL_CHANGE_REQUEST", request.id, "REJECTED", object_ref=request.number, reason=task.comment,
                     after={"domain": (task.candidate_scope or {}).get("steward_domain")}, rule_set_version=request.rule_set_version)
        outbox.emit(session, "material.change.rejected", "MATERIAL_CHANGE_REQUEST", request.id, request.number,
                    {"material": material.number, "reason": task.comment})
        return
    sod.record(session, SOD_APPROVE, {"material_request_id": request.id})
    if material.version != request.from_version or material.status != "ACTIVE":
        request.status = "REJECTED"
        request.rejection_reason = (f"{material.number} changed (version {material.version}) after the request was made on version "
                                    f"{request.from_version}; raise a new request")
        audit.record(session, "MATERIAL_CHANGE_REQUEST", request.id, "STALE", object_ref=request.number, reason=request.rejection_reason)
        return
    _apply(session, request, material)


def _apply(session: Session, request: MaterialChangeRequest, material: Material) -> None:
    before = snapshot_of(material)
    for change in request.changes:
        field = change["field"]
        value = _norm(field, change["to"])
        setattr(material, field, value)
    material.version = request.from_version + 1
    material.erp_synced = False
    request.to_version = material.version
    request.status = "APPLIED"
    request.applied_at = clock.now()
    session.flush()
    fields = [c["field"] for c in request.changes]
    record_version(session, material, change=request, fields=fields, reason=request.reason)
    audit.record(session, "MATERIAL", material.id, "CHANGE_APPLIED", object_ref=material.number,
                 before={f: before.get(f) for f in fields}, after={f: snapshot_of(material).get(f) for f in fields},
                 reason=request.reason, rule_set_version=request.rule_set_version)
    audit.record(session, "MATERIAL_CHANGE_REQUEST", request.id, "APPLIED", object_ref=request.number,
                 after={"material": material.number, "version": material.version, "approvals": [a["domain"] for a in request.approvals]},
                 rule_set_version=request.rule_set_version)
    request.erp_key = f"MAT|{material.number}|{material.version}"
    message = integration.enqueue(
        session, target_system=integration.target_system(session), message_type="MATERIAL_MASTER", idempotency_key=request.erp_key,
        object_type="MATERIAL_CHANGE_REQUEST", object_id=request.id, object_ref=request.number,
        payload={"material": material.number, "description": material.description, "group": material.material_group, "uom": material.base_uom,
                 "valuationClass": material.valuation_class, "hsnCode": material.hsn_code, "gstRate": str(material.gst_rate),
                 "change": request.number, "version": material.version, "fields": fields})
    outbox.emit(session, "material.changed", "MATERIAL", material.id, material.number,
                {"material": material.number, "version": material.version, "fields": fields, "change": request.number,
                 "erpMessage": str(message.id)})
    integration.process(session, message)


def erp_posted(session: Session, message) -> None:
    """ERP callback for a change message (mdm._material_synced delegates here): the master is in sync again."""
    request = session.get(MaterialChangeRequest, message.object_id)
    if request is None:
        return
    material = session.get(Material, request.material_id)
    request.erp_document = message.erp_doc_no
    if material is not None and material.version == request.to_version:
        material.erp_synced = True
    audit.record(session, "MATERIAL_CHANGE_REQUEST", request.id, "SYNCED_TO_ERP", object_ref=request.number,
                 after={"erpDocument": message.erp_doc_no, "key": message.idempotency_key})


def decide(session: Session, request: MaterialChangeRequest, decision: str, comment: Optional[str]) -> MaterialChangeRequest:
    """Complete the caller's open steward task on the request (their domain)."""
    p = principal(session)
    tasks = [t for t in workflow.open_tasks_for(session, p) if t.object_id == request.id and t.kind == TASK_KIND]
    if not tasks:
        raise Problem(403, "NOT_YOUR_TASK", "You have no open steward task on this change request")
    workflow.complete(session, tasks[0].id, decision, comment)
    return request


def cancel(session: Session, request: MaterialChangeRequest, reason: str) -> MaterialChangeRequest:
    p = principal(session)
    if request.status != "IN_APPROVAL":
        raise illegal_transition("Material change request", request.number, request.status, "cancel")
    if p.user_id != request.requested_by and "TENANT_ADMIN" not in p.roles:
        raise Problem(403, "FORBIDDEN", "Only the requester can withdraw a change request", rule_ref="MDM-CHANGE")
    request.status = "CANCELLED"
    request.rejection_reason = (reason or "withdrawn by the requester").strip()
    for task in session.execute(select(Task).where(Task.object_id == request.id, Task.status == "OPEN")).scalars():
        task.status = "CANCELLED"
    audit.record(session, "MATERIAL_CHANGE_REQUEST", request.id, "CANCELLED", object_ref=request.number, reason=request.rejection_reason)
    return request


# ---------------------------------------------------------------- read
def by_number(session: Session, ref: str) -> MaterialChangeRequest:
    try:
        found = session.get(MaterialChangeRequest, uuid.UUID(str(ref)))
        if found is not None:
            return found
    except ValueError:
        pass
    found = session.execute(select(MaterialChangeRequest).where(MaterialChangeRequest.number == ref)).scalar_one_or_none()
    if found is None:
        raise not_found("Material change request", ref)
    return found


def view(session: Session, request: MaterialChangeRequest) -> dict:
    material = session.get(Material, request.material_id)
    tasks = session.execute(select(Task).where(Task.object_id == request.id, Task.kind == TASK_KIND).order_by(Task.sequence)).scalars().all()
    return row(request, extra={
        "material": material.number if material else None, "materialDescription": material.description if material else None,
        "tasks": [{"id": str(t.id), "domain": (t.candidate_scope or {}).get("steward_domain"), "status": t.status, "decision": t.decision,
                   "comment": t.comment, "completedAt": t.completed_at.isoformat() if t.completed_at else None} for t in tasks]})


def list_for(session: Session, material: Material) -> list[dict]:
    return [view(session, r) for r in session.execute(select(MaterialChangeRequest).where(
        MaterialChangeRequest.material_id == material.id).order_by(MaterialChangeRequest.created_at.desc())).scalars()]


def versions(session: Session, material: Material) -> list[dict]:
    return [row(v) for v in session.execute(select(MaterialVersion).where(MaterialVersion.material_id == material.id)
                                            .order_by(MaterialVersion.version.desc())).scalars()]
