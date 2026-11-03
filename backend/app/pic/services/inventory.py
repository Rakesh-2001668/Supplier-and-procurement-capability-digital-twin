"""Inventory documents (BP M09 stock, Technical Document sections 5.2, 6, 9.1): governed stock postings, physical inventory (cycle counts)
and stock reservations. Everything that changes stock goes through ``stock_ledger.post_movement``; the documents add the controls.

Stock posting   DRAFT -> SUBMITTED -> APPROVED -> POSTED (| REJECTED | CANCELLED)
                TRANSFER (311 within a plant, 301 between plants), BLOCK (344), UNBLOCK (343), SCRAP (551). Rule INVENTORY-POSTING: transfer, block
                and unblock under ``autoPostBelowMinor`` post when submitted; everything else (and every scrap) goes to the approval chain of its
                value band. Maker-checker: SOD-10 (whoever created or submitted a posting may not approve it). Release from quality stock is the
                usage decision of the inspection lot, never a stock posting.
Physical inv.   PLANNED -> COUNTING -> COUNTED -> PENDING_APPROVAL -> APPROVED -> POSTED (| CANCELLED)
                The book quantity of every line is frozen when the document is created; counters count blind; a count outside the tolerance of rule
                INVENTORY-COUNT must be recounted (by another person); the approver is never a counter (SOD-11); the difference posted is the count
                relative to the freeze (701 gain / 702 loss), so a receipt posted while counting is not wiped out.
Reservation     OPEN -> PARTIALLY_ISSUED -> ISSUED (| CANCELLED | EXPIRED)
                The open quantity is RESERVATION demand for MRP (demand_element); an issue posts 201 from unrestricted stock (first expiry first out
                unless a batch is given) and reduces both. Rule INVENTORY-RESERVATION: warn or refuse an unavailable quantity, grace after the need date.
Every state change is audited with before/after, reason and rule version; each document emits its events and, when posted, an ERP STOCK_POSTING.
"""
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.models import (
    CostObject, DemandElement, Material, PhysicalInventory, PhysicalInventoryLine, Plant, Stock, StockMovement, StockPosting, StockPostingLine,
    StockReservation, StorageLocation, Task,
)
from app.pic.platform import abac, audit, clock, integration, outbox, rules, sod, workflow
from app.pic.platform import inventory_defaults as ir
from app.pic.platform.core import StateMachine, next_number
from app.pic.platform.errors import Problem, illegal_transition, not_found, rule_violation
from app.pic.platform.money import D, line_amount
from app.pic.platform.serialize import jsonable
from app.pic.services import finance_controls, org_guard, stock_ledger
from app.pic.services.common import material_by_number, principal

POSTING_APPROVAL = "STOCK_POSTING_APPROVAL"
COUNT_APPROVAL = "PHYSICAL_INVENTORY_APPROVAL"
OPEN_COUNT = ("PLANNED", "COUNTING", "COUNTED", "PENDING_APPROVAL", "APPROVED")

POSTING_SM = StateMachine("STOCK_POSTING", {
    ("DRAFT", "submit"): "SUBMITTED",
    ("SUBMITTED", "approve"): "APPROVED",
    ("SUBMITTED", "reject"): "REJECTED",
    ("APPROVED", "post"): "POSTED",
    ("DRAFT", "cancel"): "CANCELLED",
    ("SUBMITTED", "cancel"): "CANCELLED",
    ("APPROVED", "cancel"): "CANCELLED",
})
COUNT_SM = StateMachine("PHYSICAL_INVENTORY", {
    ("PLANNED", "start"): "COUNTING",
    ("COUNTING", "complete"): "COUNTED",
    ("COUNTED", "reopen"): "COUNTING",
    ("COUNTED", "submit"): "PENDING_APPROVAL",
    ("PENDING_APPROVAL", "approve"): "APPROVED",
    ("PENDING_APPROVAL", "reject"): "COUNTING",
    ("PENDING_APPROVAL", "reopen"): "COUNTING",
    ("APPROVED", "post"): "POSTED",
    ("PLANNED", "cancel"): "CANCELLED", ("COUNTING", "cancel"): "CANCELLED", ("COUNTED", "cancel"): "CANCELLED",
    ("PENDING_APPROVAL", "cancel"): "CANCELLED", ("APPROVED", "cancel"): "CANCELLED",
})
RESERVATION_SM = StateMachine("STOCK_RESERVATION", {
    ("OPEN", "issue_part"): "PARTIALLY_ISSUED", ("OPEN", "issue"): "ISSUED",
    ("PARTIALLY_ISSUED", "issue_part"): "PARTIALLY_ISSUED", ("PARTIALLY_ISSUED", "issue"): "ISSUED",
    ("OPEN", "cancel"): "CANCELLED", ("PARTIALLY_ISSUED", "cancel"): "CANCELLED",
    ("OPEN", "expire"): "EXPIRED", ("PARTIALLY_ISSUED", "expire"): "EXPIRED",
})


# ---------------------------------------------------------------- shared helpers
def _need(value, what: str) -> str:
    text = (value or "").strip() if isinstance(value, str) else value
    if not text:
        raise Problem(422, "VALIDATION_FAILED", f"{what} is required", rule_ref="INVENTORY")
    return text


def _qty(value, what: str) -> Decimal:
    try:
        qty = D(value)
    except Exception:  # noqa: BLE001
        raise Problem(422, "INVALID_QUANTITY", f"{what}: {value!r} is not a number", rule_ref="INVENTORY")
    if not qty.is_finite() or qty <= 0:
        raise Problem(422, "INVALID_QUANTITY", f"{what}: the quantity must be positive (got {value})", rule_ref="INVENTORY")
    if qty.quantize(stock_ledger.QTY_PLACES) != qty:
        raise Problem(422, "INVALID_QUANTITY", f"{what}: at most three decimals (got {value})", rule_ref="INVENTORY")
    return qty


def _stock_material(session: Session, number: str) -> Material:
    material = material_by_number(session, number)
    if material.type != "STOCK":
        raise rule_violation(f"{material.number} is a {material.type.lower().replace('_', '-')} material: only stock materials have stock", "INVENTORY")
    return material


def _plant(session: Session, code: str) -> Plant:
    plant = session.execute(select(Plant).where(Plant.code == code)).scalar_one_or_none()
    if plant is None:
        raise Problem(422, "UNKNOWN_PLANT", f"Plant {code} does not exist", rule_ref="ADM-01")
    return plant


def _location(session: Session, plant: str, code: str, what: str = "storage location") -> None:
    if session.execute(select(StorageLocation.id).where(StorageLocation.plant == plant, StorageLocation.code == code)).first() is None:
        raise Problem(422, "UNKNOWN_STORAGE_LOCATION", f"{what.capitalize()} {code} does not exist at plant {plant}", rule_ref="ADM-01")


def _by_ref(session: Session, model, ref: str, label: str, lock: bool = False):
    try:
        query = select(model).where(model.id == uuid.UUID(str(ref)))
    except ValueError:
        query = select(model).where(model.number == ref)
    if lock:
        query = query.with_for_update()
    found = session.execute(query).scalar_one_or_none()
    if found is None:
        raise not_found(label, ref)
    return found


def posting_by_ref(session: Session, ref: str, lock: bool = False) -> StockPosting:
    return _by_ref(session, StockPosting, ref, "Stock posting", lock)


def count_by_ref(session: Session, ref: str, lock: bool = False) -> PhysicalInventory:
    return _by_ref(session, PhysicalInventory, ref, "Physical inventory", lock)


def reservation_by_ref(session: Session, ref: str, lock: bool = False) -> StockReservation:
    return _by_ref(session, StockReservation, ref, "Reservation", lock)


def _open_task(session: Session, kind: str, object_id) -> Optional[Task]:
    return session.execute(select(Task).where(Task.kind == kind, Task.object_id == object_id, Task.status == "OPEN")
                           .order_by(Task.sequence)).scalars().first()


def _cancel_tasks(session: Session, kind: str, object_id) -> int:
    n = 0
    for task in session.execute(select(Task).where(Task.kind == kind, Task.object_id == object_id, Task.status == "OPEN")).scalars():
        task.status = "CANCELLED"
        n += 1
    return n


def _cut_off(session: Session, company_code: str, what: str, *dates: date) -> None:
    for when in {clock.today(), *dates}:
        finance_controls.assert_open(session, company_code, when, what)


def _user_names(session: Session, ids) -> dict:
    from app.pic.models import AppUser
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    return {u.id: {"id": str(u.id), "name": u.full_name, "email": u.email}
            for u in session.execute(select(AppUser).where(AppUser.id.in_(wanted))).scalars()}


# ================================================================ 1 stock postings
def _line_spec(session: Session, posting_type: str, plant: str, company_code: str, rule: rules.Rule, data: dict, position: int) -> dict:
    """Validate one posting line and resolve its movement: from/to balance, movement type, the price at which it is valued."""
    what = f"line {position}"
    material = _stock_material(session, _need(data.get("material"), f"{what}: material"))
    qty = _qty(data.get("qty"), what)
    batch = (data.get("batch") or "").strip()
    sloc = _need(data.get("storage_location") or data.get("storageLocation"), f"{what}: storage location")
    _location(session, plant, sloc)
    stock_type = (data.get("stock_type") or data.get("stockType") or "").upper() or None
    to_plant, to_sloc, to_type = None, None, None
    if posting_type == "TRANSFER":
        from_type = stock_type or "UNRESTRICTED"
        if from_type not in ("UNRESTRICTED", "BLOCKED"):
            raise Problem(422, "INVALID_STOCK_TYPE", f"{what}: only unrestricted or blocked stock is transferred", rule_ref="INVENTORY")
        to_plant = (data.get("to_plant") or data.get("toPlant") or plant).strip()
        to_sloc = _need(data.get("to_storage_location") or data.get("toStorageLocation"), f"{what}: target storage location")
        to_type = from_type
        if to_plant != plant:
            if not rule.body.get("crossPlantTransfer", True):
                raise rule_violation("Plant-to-plant transfer is switched off in rule INVENTORY-POSTING", rule.ref)
            if _plant(session, to_plant).company_code != company_code:
                raise Problem(422, "INTERCOMPANY_TRANSFER", f"{what}: {to_plant} belongs to another company code; a transfer between companies is a stock "
                              "transport order, not a transfer posting", rule_ref=rule.ref)
        _location(session, to_plant, to_sloc, "target storage location")
        if (to_plant, to_sloc) == (plant, sloc):
            raise Problem(422, "VALIDATION_FAILED", f"{what}: the target is the same location", rule_ref=rule.ref)
        movement = "301" if to_plant != plant else "311"
    elif posting_type == "BLOCK":
        from_type, to_plant, to_sloc, to_type, movement = "UNRESTRICTED", plant, sloc, "BLOCKED", "344"
    elif posting_type == "UNBLOCK":
        from_type, to_plant, to_sloc, to_type, movement = "BLOCKED", plant, sloc, "UNRESTRICTED", "343"
    else:  # SCRAP
        from_type = stock_type or "UNRESTRICTED"
        if from_type not in ("UNRESTRICTED", "BLOCKED"):
            raise Problem(422, "INVALID_STOCK_TYPE", f"{what}: only unrestricted or blocked stock is scrapped", rule_ref="INVENTORY")
        movement = "551"
    price = material.standard_price_minor
    return {"material": material, "qty": qty, "batch": batch, "from_plant": plant, "from_storage_location": sloc, "from_stock_type": from_type,
            "to_plant": to_plant, "to_storage_location": to_sloc, "to_stock_type": to_type, "movement_type": movement,
            "unit_price_minor": price, "value_minor": line_amount(qty, int(price)) if price is not None else 0}


def _check_available(session: Session, line) -> None:
    """The balance a posting line takes from covers it (checked at creation, at submit and, under the row lock, at posting)."""
    material_id = line["material"].id if isinstance(line, dict) else line.material_id
    get = (lambda key: line[key]) if isinstance(line, dict) else (lambda key: getattr(line, key))
    available = stock_ledger.on_hand(session, material_id, get("from_plant"), get("from_storage_location"), get("from_stock_type"), get("batch"))
    if available < get("qty"):
        number = line["material"].number if isinstance(line, dict) else session.get(Material, material_id).number
        others = session.execute(select(Stock.batch, Stock.qty).where(
            Stock.material_id == material_id, Stock.plant == get("from_plant"), Stock.storage_location == get("from_storage_location"),
            Stock.stock_type == get("from_stock_type"), Stock.qty > 0)).all()
        hint = ""
        if not get("batch") and others:
            hint = f"; the stock is in batch(es) {', '.join(b or '(none)' for b, _ in others)}: name the batch"
        raise Problem(422, "INSUFFICIENT_STOCK", f"{number}: only {available} {get('from_stock_type').lower()} at {get('from_plant')}/"
                      f"{get('from_storage_location')}" + (f" batch {get('batch')}" if get("batch") else "") + f"; {get('qty')} needed{hint}",
                      rule_ref="STOCK", availableQty=jsonable(available), requiredQty=jsonable(get("qty")), material=number)


def create_posting(session: Session, *, posting_type: str, plant: str, lines: list[dict], reason_code: Optional[str] = None,
                   reason: Optional[str] = None, posting_date: Optional[date] = None, submit: bool = False) -> StockPosting:
    p = principal(session)
    posting_type = (posting_type or "").upper()
    if posting_type == "RELEASE_QUALITY":
        raise Problem(422, "USE_USAGE_DECISION", "Stock in quality inspection is released (or rejected) by the usage decision of its inspection lot "
                      "(POST /v1/inspection-lots/{lot}/usage-decision); a stock posting cannot bypass it", rule_ref="QM-UD")
    if posting_type not in ("TRANSFER", "BLOCK", "UNBLOCK", "SCRAP"):
        raise Problem(422, "INVALID_POSTING_TYPE", "type must be TRANSFER, BLOCK, UNBLOCK or SCRAP", rule_ref="INVENTORY-POSTING")
    plant_row = _plant(session, _need(plant, "plant"))
    company_code = plant_row.company_code
    abac.guard(session, "INVENTORY_POST", None, plant=plant_row.code, company_code=company_code)
    org_guard.ensure_active(session, "stock posting", company_code=company_code, plant=plant_row.code)
    rule = ir.rule(session, ir.POSTING_KEY, company_code=company_code, plant=plant_row.code)
    if not lines:
        raise Problem(422, "LINES_REQUIRED", "A stock posting lists at least one line", rule_ref=rule.ref)
    if len(lines) > int(rule.body["maxLines"]):
        raise Problem(422, "TOO_MANY_LINES", f"At most {rule.body['maxLines']} lines per stock posting (rule {rule.ref})", rule_ref=rule.ref)
    reason_code = (reason_code or "").strip().upper() or None
    reasons = rule.body.get("scrapReasons" if posting_type == "SCRAP" else "blockReasons") or {}
    if posting_type == "SCRAP" and not reason_code:
        raise Problem(422, "REASON_CODE_REQUIRED", f"A scrap needs a reason code ({', '.join(reasons)})", rule_ref=rule.ref)
    if posting_type in ("SCRAP", "BLOCK") and reason_code and reasons and reason_code not in reasons:
        raise Problem(422, "REASON_CODE_UNKNOWN", f"Reason code {reason_code} is not one of {', '.join(reasons)}", rule_ref=rule.ref)
    if posting_type in rule.body.get("reasonRequiredFor", []) and len((reason or "").strip()) < 3:
        raise Problem(422, "REASON_REQUIRED", f"A {posting_type.lower()} needs a reason", rule_ref=rule.ref)
    posting_date = posting_date or clock.today()
    if posting_date > clock.today():
        raise rule_violation(f"The posting date {posting_date.isoformat()} is in the future", rule.ref)
    specs = [_line_spec(session, posting_type, plant_row.code, company_code, rule, data, i) for i, data in enumerate(lines, start=1)]
    seen = set()
    for spec in specs:  # the same balance twice would be checked against its full quantity each time
        key = (spec["material"].id, spec["from_storage_location"], spec["from_stock_type"], spec["batch"])
        if key in seen:
            raise Problem(422, "DUPLICATE_LINE", f"{spec['material'].number} appears twice for the same location, stock type and batch; "
                          "combine the quantities", rule_ref=rule.ref)
        seen.add(key)
    for spec in specs:
        _check_available(session, spec)
        if spec["to_plant"] and spec["to_plant"] != plant_row.code:
            abac.guard(session, "INVENTORY_POST", None, plant=spec["to_plant"], company_code=company_code)
    posting = StockPosting(tenant_id=p.tenant_id, number=next_number(session, "STOCK_POSTING"), posting_type=posting_type, status="DRAFT",
                           company_code=company_code, plant=plant_row.code, posting_date=posting_date, reason_code=reason_code,
                           reason=(reason or "").strip() or None, total_value_minor=sum(s["value_minor"] for s in specs),
                           rule_set_version=rule.ref, created_by=p.user_id)
    session.add(posting)
    session.flush()
    for i, spec in enumerate(specs, start=1):
        session.add(StockPostingLine(tenant_id=p.tenant_id, posting_id=posting.id, line_no=i * 10, material_id=spec["material"].id, batch=spec["batch"],
                                     qty=spec["qty"], from_plant=spec["from_plant"], from_storage_location=spec["from_storage_location"],
                                     from_stock_type=spec["from_stock_type"], to_plant=spec["to_plant"], to_storage_location=spec["to_storage_location"],
                                     to_stock_type=spec["to_stock_type"], movement_type=spec["movement_type"],
                                     unit_price_minor=spec["unit_price_minor"], value_minor=spec["value_minor"], created_by=p.user_id))
    session.flush()
    sod.record(session, "INVENTORY_POST", {"posting_id": posting.id})  # the maker (SOD-10)
    audit.record(session, "STOCK_POSTING", posting.id, "CREATED", object_ref=posting.number, rule_set_version=rule.ref, reason=posting.reason,
                 after={"type": posting_type, "plant": plant_row.code, "lines": len(specs), "valueMinor": posting.total_value_minor,
                        "reasonCode": reason_code, "postingDate": posting_date.isoformat()})
    if submit:
        submit_posting(session, posting)
    return posting


def posting_lines(session: Session, posting: StockPosting) -> list[StockPostingLine]:
    return session.execute(select(StockPostingLine).where(StockPostingLine.posting_id == posting.id).order_by(StockPostingLine.line_no)).scalars().all()


def submit_posting(session: Session, posting: StockPosting) -> StockPosting:
    p = principal(session)
    if posting.status != "DRAFT":
        raise illegal_transition("Stock posting", posting.number, posting.status, "submit")
    abac.guard(session, "INVENTORY_POST", None, plant=posting.plant, company_code=posting.company_code)
    org_guard.ensure_active(session, "stock posting", company_code=posting.company_code, plant=posting.plant)
    rule = ir.rule(session, ir.POSTING_KEY, company_code=posting.company_code, plant=posting.plant)
    _cut_off(session, posting.company_code, f"stock posting {posting.number}", posting.posting_date)
    lines = posting_lines(session, posting)
    for line in lines:
        _check_available(session, line)
    total = sum(int(l.value_minor or 0) for l in lines)
    posting.total_value_minor = total
    posting.submitted_by, posting.submitted_at, posting.rule_set_version = p.user_id, clock.now(), rule.ref
    sod.record(session, "INVENTORY_POST", {"posting_id": posting.id})
    POSTING_SM.apply(session, posting, "submit", rule_set_version=rule.ref, extra_after={"valueMinor": total, "lines": len(lines)})
    outbox.emit(session, "stock_posting.submitted", "STOCK_POSTING", posting.id, posting.number,
                {"posting": posting.number, "type": posting.posting_type, "plant": posting.plant, "valueMinor": total, "lines": len(lines)})
    auto = (posting.posting_type in rule.body["autoPostTypes"] and posting.posting_type != "SCRAP" and total < int(rule.body["autoPostBelowMinor"]))
    if auto:
        posting.auto_posted = True
        POSTING_SM.apply(session, posting, "approve", rule_set_version=rule.ref,
                         extra_after={"auto": True, "reason": f"{posting.posting_type} of {total} is below the auto-post limit {rule.body['autoPostBelowMinor']}"})
        outbox.emit(session, "stock_posting.approved", "STOCK_POSTING", posting.id, posting.number,
                    {"posting": posting.number, "type": posting.posting_type, "approvedBy": "RULE", "auto": True})
        _execute_posting(session, posting, lines)
        return posting
    chain = ir.band_chain(rule.body, total)
    makers = [u for u in (posting.created_by, p.user_id) if u]
    workflow.start_approval(session, None, POSTING_APPROVAL, object_type="STOCK_POSTING", object_id=posting.id, object_ref=posting.number, chain=chain,
                            step_id=None, initiator_id=p.user_id, exclude=makers,
                            sla_business_days=int(rule.body["slaBusinessDays"]), rule_set_version=rule.ref,
                            evidence={"type": posting.posting_type, "plant": posting.plant, "totalValueMinor": total, "valueMinor": total,
                                      "reasonCode": posting.reason_code, "reason": posting.reason, "lines": len(lines), "chain": chain})
    return posting


def _posting_approval_guard(session: Session, task: Task, decision: str) -> None:
    """Task inbox path: the same SoD checks as the approve endpoint (SOD-10), evidence included."""
    if decision.upper() == "APPROVE":
        sod.guard(session, "INVENTORY_APPROVE", {"posting_id": task.object_id})
        sod.record(session, "INVENTORY_APPROVE", {"posting_id": task.object_id})


workflow.guard_task(POSTING_APPROVAL)(_posting_approval_guard)


@workflow.on_task(POSTING_APPROVAL)
def _posting_decided(session: Session, task: Task, outcome: str) -> None:
    posting = session.get(StockPosting, task.object_id)
    if posting is None or posting.status != "SUBMITTED":
        return
    if outcome == "APPROVED":
        posting.approved_by, posting.approved_at, posting.decision_comment = task.completed_by, clock.now(), task.comment
        POSTING_SM.apply(session, posting, "approve", reason=task.comment, rule_set_version=posting.rule_set_version,
                         extra_after={"approvedBy": str(task.completed_by)})
        outbox.emit(session, "stock_posting.approved", "STOCK_POSTING", posting.id, posting.number,
                    {"posting": posting.number, "type": posting.posting_type, "approvedBy": str(task.completed_by), "auto": False})
    else:
        posting.decision_comment = task.comment
        POSTING_SM.apply(session, posting, "reject", reason=task.comment or "not approved", rule_set_version=posting.rule_set_version)
        outbox.emit(session, "stock_posting.rejected", "STOCK_POSTING", posting.id, posting.number,
                    {"posting": posting.number, "type": posting.posting_type, "reason": task.comment or "not approved"})


def decide_posting(session: Session, posting: StockPosting, decision: str, comment: Optional[str]) -> StockPosting:
    """Approve or reject through the open approval task (the maker is refused by SOD-10 before the task is looked at)."""
    if posting.status != "SUBMITTED":
        raise illegal_transition("Stock posting", posting.number, posting.status, decision.lower())
    if decision == "APPROVE":
        sod.guard(session, "INVENTORY_APPROVE", {"posting_id": posting.id})
    elif len((comment or "").strip()) < 3:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for rejecting the stock posting", rule_ref="INVENTORY-POSTING")
    task = _open_task(session, POSTING_APPROVAL, posting.id)
    if task is None:
        raise Problem(409, "NO_OPEN_APPROVAL", f"{posting.number} has no open approval task", rule_ref="INVENTORY-POSTING")
    workflow.complete(session, task.id, decision, (comment or "").strip() or None)
    return posting


def cancel_posting(session: Session, posting: StockPosting, reason: str) -> StockPosting:
    p = principal(session)
    if len((reason or "").strip()) < 3:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for cancelling the stock posting", rule_ref="INVENTORY-POSTING")
    if not (posting.created_by == p.user_id or posting.submitted_by == p.user_id or "inventory:post" in p.scopes):
        raise Problem(403, "FORBIDDEN", "A stock posting is cancelled by the person who raised it or by a stock poster", rule_ref="RBAC")
    POSTING_SM.apply(session, posting, "cancel", reason=reason.strip(), rule_set_version=posting.rule_set_version)
    _cancel_tasks(session, POSTING_APPROVAL, posting.id)
    posting.decision_comment = reason.strip()
    return posting


def post_posting(session: Session, posting: StockPosting) -> StockPosting:
    if posting.status == "POSTED":
        return posting
    if posting.status != "APPROVED":
        raise illegal_transition("Stock posting", posting.number, posting.status, "post")
    abac.guard(session, "INVENTORY_POST", None, plant=posting.plant, company_code=posting.company_code)
    org_guard.ensure_active(session, "stock posting", company_code=posting.company_code, plant=posting.plant)
    _execute_posting(session, posting, posting_lines(session, posting))
    return posting


def _execute_posting(session: Session, posting: StockPosting, lines: list[StockPostingLine]) -> None:
    """Post the movements of an approved posting: period cut-off and stock are checked again now (the state may have changed since the
    submit), every movement is taken under its row lock, then the ERP is told."""
    p = principal(session)
    _cut_off(session, posting.company_code, f"stock posting {posting.number}", posting.posting_date)
    for line in lines:
        _check_available(session, line)
    reason = posting.reason_code
    movements = 0
    for line in lines:
        common = dict(material_id=line.material_id, batch=line.batch, ref_type="STOCK_POSTING", ref_id=posting.id, ref=posting.number,
                      movement=line.movement_type, posting_ref=posting.number, reason_code=reason)
        stock_ledger.post_movement(session, plant=line.from_plant, sloc=line.from_storage_location, stock_type=line.from_stock_type, qty=-line.qty, **common)
        movements += 1
        if line.to_stock_type:
            stock_ledger.post_movement(session, plant=line.to_plant, sloc=line.to_storage_location, stock_type=line.to_stock_type, qty=line.qty, **common)
            movements += 1
    posting.posted_by, posting.posted_at = p.user_id, clock.now()
    POSTING_SM.apply(session, posting, "post", rule_set_version=posting.rule_set_version,
                     extra_after={"movements": movements, "valueMinor": posting.total_value_minor, "autoPosted": posting.auto_posted})
    erp = stock_ledger.enqueue_erp(
        session, object_type="STOCK_POSTING", object_id=posting.id, ref=posting.number, company_code=posting.company_code, key=f"STP|{posting.number}",
        payload={"posting": posting.number, "type": posting.posting_type, "plant": posting.plant, "postingDate": posting.posting_date.isoformat(),
                 "grossMinor": posting.total_value_minor, "reasonCode": posting.reason_code, "reason": (posting.reason or "")[:200] or None,
                 "lines": [{"material": session.get(Material, l.material_id).number, "batch": l.batch, "qty": str(l.qty), "movement": l.movement_type,
                            "fromPlant": l.from_plant, "fromStorageLocation": l.from_storage_location, "fromStockType": l.from_stock_type,
                            "toPlant": l.to_plant, "toStorageLocation": l.to_storage_location, "toStockType": l.to_stock_type,
                            "valueMinor": l.value_minor} for l in lines]})
    outbox.emit(session, "stock_posting.posted", "STOCK_POSTING", posting.id, posting.number,
                {"posting": posting.number, "type": posting.posting_type, "plant": posting.plant, "valueMinor": posting.total_value_minor,
                 "movements": movements, "erpDocument": erp.get("erpDocument")})


@integration.on_posted(stock_ledger.MESSAGE_TYPE)
def _stock_message_posted(session: Session, message) -> None:
    """The ERP material document number of an inventory document comes back on the message."""
    model = {"STOCK_POSTING": StockPosting, "PHYSICAL_INVENTORY": PhysicalInventory}.get(message.object_type)
    document = session.get(model, message.object_id) if model is not None else None
    if document is not None:
        document.erp_doc_no = message.erp_doc_no


# ================================================================ 2 physical inventory
def abc_classes(session: Session, plant: str, cutoffs=(80, 95), months: int = 12) -> dict:
    """ABC class per material of a plant by the value issued over the last ``months`` (movements 201 / 201K at standard price, Pareto cut-offs
    in percent of the cumulative value); a material without issues is class C."""
    since = clock.now() - timedelta(days=30 * months)
    rows = session.execute(select(StockMovement.material_id, func.sum(-StockMovement.qty * func.coalesce(Material.standard_price_minor, 0)))
                           .join(Material, Material.id == StockMovement.material_id)
                           .where(StockMovement.plant == plant, StockMovement.movement_type.in_(("201", "201K")), StockMovement.created_at >= since)
                           .group_by(StockMovement.material_id)).all()
    ranked = sorted(((m, D(v)) for m, v in rows if v and v > 0), key=lambda r: r[1], reverse=True)
    total = sum((v for _, v in ranked), Decimal(0))
    out, running = {}, Decimal(0)
    for material_id, value in ranked:
        before = running * 100 / total if total else Decimal(100)
        out[material_id] = "A" if before < cutoffs[0] else "B" if before < cutoffs[1] else "C"
        running += value
    return out


def create_count(session: Session, *, plant: str, storage_location: str, material_group: Optional[str] = None, materials: Optional[list] = None,
                 abc: Optional[list] = None, description: Optional[str] = None, planned_date: Optional[date] = None) -> PhysicalInventory:
    p = principal(session)
    plant_row = _plant(session, _need(plant, "plant"))
    sloc = _need(storage_location, "storage location")
    _location(session, plant_row.code, sloc)
    abac.guard(session, "INVENTORY_COUNT", None, plant=plant_row.code, company_code=plant_row.company_code)
    org_guard.ensure_active(session, "physical inventory", company_code=plant_row.company_code, plant=plant_row.code, storage_location=sloc)
    rule = ir.rule(session, ir.COUNT_KEY, company_code=plant_row.company_code, plant=plant_row.code)
    query = (select(Stock, Material).join(Material, Material.id == Stock.material_id).where(
        Stock.plant == plant_row.code, Stock.storage_location == sloc, Stock.stock_type == "UNRESTRICTED", Stock.qty != 0))
    if material_group:
        query = query.where(Material.material_group == material_group)
    if materials:
        query = query.where(Material.number.in_([str(m) for m in materials]))
    rows = session.execute(query.order_by(Material.number, Stock.batch)).all()
    classes = {}
    if abc:
        wanted = {str(c).upper() for c in abc}
        if not wanted <= {"A", "B", "C"}:
            raise Problem(422, "VALIDATION_FAILED", "abc classes are A, B or C", rule_ref=rule.ref)
        classes = abc_classes(session, plant_row.code)
        rows = [r for r in rows if classes.get(r[1].id, "C") in wanted]
    if not rows:
        raise Problem(422, "NOTHING_TO_COUNT", f"No unrestricted stock at {plant_row.code}/{sloc} matches the selection", rule_ref=rule.ref)
    if len(rows) > int(rule.body["maxLines"]):
        raise Problem(422, "TOO_MANY_LINES", f"{len(rows)} lines; at most {rule.body['maxLines']} per count (rule {rule.ref}): narrow it by material group, "
                      "materials or ABC class", rule_ref=rule.ref)
    taken = session.execute(select(PhysicalInventory.number, PhysicalInventoryLine.material_id, PhysicalInventoryLine.batch).join(
        PhysicalInventoryLine, PhysicalInventoryLine.inventory_id == PhysicalInventory.id).where(
        PhysicalInventory.plant == plant_row.code, PhysicalInventory.storage_location == sloc, PhysicalInventory.status.in_(OPEN_COUNT))).all()
    busy = {(m, b): n for n, m, b in taken}
    clash = sorted({busy[(s.material_id, s.batch)] for s, _ in rows if (s.material_id, s.batch) in busy})
    if clash:
        raise Problem(409, "COUNT_IN_PROGRESS", f"{plant_row.code}/{sloc} is already being counted in {', '.join(clash)} for some of these materials; "
                      "finish or cancel that count first", rule_ref=rule.ref, counts=clash)
    inventory = PhysicalInventory(tenant_id=p.tenant_id, number=next_number(session, "PHYSICAL_INVENTORY"), status="PLANNED",
                                  company_code=plant_row.company_code, plant=plant_row.code, storage_location=sloc, material_group=material_group,
                                  scope={"materials": [str(m) for m in materials or []], "abc": sorted({str(c).upper() for c in abc or []}),
                                         "materialGroup": material_group}, description=(description or "").strip() or None,
                                  planned_date=planned_date, frozen_at=clock.now(), line_count=len(rows), rule_set_version=rule.ref, created_by=p.user_id)
    session.add(inventory)
    session.flush()
    for i, (stock, material) in enumerate(rows, start=1):
        session.add(PhysicalInventoryLine(tenant_id=p.tenant_id, inventory_id=inventory.id, line_no=i * 10, material_id=material.id, batch=stock.batch,
                                          stock_type="UNRESTRICTED", book_qty=stock.qty, unit_price_minor=material.standard_price_minor,
                                          count_status="PENDING", created_by=p.user_id))
    session.flush()
    audit.record(session, "PHYSICAL_INVENTORY", inventory.id, "CREATED", object_ref=inventory.number, rule_set_version=rule.ref,
                 after={"plant": plant_row.code, "storageLocation": sloc, "lines": len(rows), "frozenAt": inventory.frozen_at.isoformat(),
                        "scope": inventory.scope})
    return inventory


def count_lines(session: Session, inventory: PhysicalInventory) -> list[PhysicalInventoryLine]:
    return session.execute(select(PhysicalInventoryLine).where(PhysicalInventoryLine.inventory_id == inventory.id)
                           .order_by(PhysicalInventoryLine.line_no)).scalars().all()


def _within_tolerance(body: dict, book: Decimal, counted: Decimal, price: Optional[int]) -> bool:
    """A count is inside the tolerance when its difference is within the quantity percentage AND the value limit of rule INVENTORY-COUNT."""
    diff = abs(counted - book)
    if diff == 0:
        return True
    value = abs(line_amount(counted - book, int(price))) if price is not None else 0
    pct_ok = book != 0 and diff * 100 / book <= D(body["qtyTolerancePct"])
    value_ok = value <= int(body["valueToleranceMinor"])
    return pct_ok and value_ok


def enter_counts(session: Session, inventory: PhysicalInventory, entries: list[dict]) -> PhysicalInventory:
    """Count (or recount) lines. Entries: {"material", "batch"?, "qty", "note"?}. A line not on the freeze list is added as found stock."""
    p = principal(session)
    if inventory.status not in ("PLANNED", "COUNTING", "COUNTED"):
        raise illegal_transition("Physical inventory", inventory.number, inventory.status, "count")
    if not entries:
        raise Problem(422, "LINES_REQUIRED", "Send at least one count", rule_ref="INVENTORY-COUNT")
    abac.guard(session, "INVENTORY_COUNT", None, plant=inventory.plant, company_code=inventory.company_code)
    rule = ir.rule(session, ir.COUNT_KEY, company_code=inventory.company_code, plant=inventory.plant)
    lines = {(l.material_id, l.batch): l for l in count_lines(session, inventory)}
    now = clock.now()
    seen = set()
    results = []
    for position, entry in enumerate(entries, start=1):
        material = _stock_material(session, _need(entry.get("material"), f"count {position}: material"))
        batch = (entry.get("batch") or "").strip()
        if (material.id, batch) in seen:
            raise Problem(422, "DUPLICATE_LINE", f"{material.number} batch {batch or '(none)'} is counted twice in one request", rule_ref=rule.ref)
        seen.add((material.id, batch))
        counted = D(entry.get("qty"))
        if not counted.is_finite() or counted < 0 or counted.quantize(stock_ledger.QTY_PLACES) != counted:
            raise Problem(422, "INVALID_QUANTITY", f"count {position}: the counted quantity must be zero or more, with at most three decimals", rule_ref=rule.ref)
        line = lines.get((material.id, batch))
        if line is None:
            if len(lines) >= int(rule.body["maxLines"]):
                raise Problem(422, "TOO_MANY_LINES", f"At most {rule.body['maxLines']} lines per count", rule_ref=rule.ref)
            line = PhysicalInventoryLine(tenant_id=p.tenant_id, inventory_id=inventory.id, line_no=(max([l.line_no for l in lines.values()] or [0]) + 10),
                                         material_id=material.id, batch=batch, stock_type="UNRESTRICTED", book_qty=Decimal(0),
                                         unit_price_minor=material.standard_price_minor, unlisted=True, count_status="PENDING", created_by=p.user_id)
            session.add(line)
            lines[(material.id, batch)] = line
            inventory.line_count += 1
        note = (entry.get("note") or "").strip() or None
        if line.count_status == "RECOUNT_REQUIRED":
            if rule.body.get("recountDifferentCounter", True) and line.counted_by == p.user_id:
                raise Problem(403, "RECOUNT_SAME_COUNTER", f"{material.number}: the recount is made by someone other than the first counter",
                              rule_ref=rule.ref)
            line.recount_qty, line.recounted_by, line.recounted_at, line.count_status = counted, p.user_id, now, "RECOUNTED"
            line.final_qty = counted
        elif line.count_status == "RECOUNTED":
            if line.recounted_by != p.user_id:
                raise Problem(403, "FORBIDDEN", f"{material.number}: only the recounter corrects the recount", rule_ref=rule.ref)
            line.recount_qty, line.recounted_at, line.final_qty = counted, now, counted
        else:  # PENDING or COUNTED: the first count (a counter may correct it until the document is submitted)
            first = line.count_status == "PENDING"
            if not first and line.counted_by != p.user_id:
                raise Problem(403, "FORBIDDEN", f"{material.number}: only the counter corrects the count", rule_ref=rule.ref)
            ok = _within_tolerance(rule.body, D(line.book_qty), counted, line.unit_price_minor)
            line.counted_qty, line.counted_by, line.counted_at = counted, p.user_id, now
            if first:
                line.first_count_ok = ok
            line.count_status = "COUNTED" if ok else "RECOUNT_REQUIRED"
            line.final_qty = counted if ok else None
            line.recount_qty = line.recounted_by = line.recounted_at = None
        if note:
            line.note = note
        results.append(line)
    session.flush()
    sod.record(session, "INVENTORY_COUNT", {"count_id": inventory.id})  # SOD-11: whoever counted cannot approve
    _recompute_diffs(inventory, list(lines.values()))
    pending = [l for l in lines.values() if l.count_status in ("PENDING", "RECOUNT_REQUIRED")]
    if inventory.status == "PLANNED":
        COUNT_SM.apply(session, inventory, "start", rule_set_version=rule.ref, extra_after={"firstCountBy": p.actor})
    if not pending and inventory.status == "COUNTING":
        COUNT_SM.apply(session, inventory, "complete", rule_set_version=rule.ref, extra_after={"lines": len(lines)})
    elif pending and inventory.status == "COUNTED":
        COUNT_SM.apply(session, inventory, "reopen", rule_set_version=rule.ref, extra_after={"pendingLines": len(pending)})
    audit.record(session, "PHYSICAL_INVENTORY", inventory.id, "COUNTS_ENTERED", object_ref=inventory.number, rule_set_version=rule.ref,
                 after={"entries": len(entries), "recountRequired": sum(1 for l in lines.values() if l.count_status == "RECOUNT_REQUIRED"),
                        "pending": len(pending)})
    return inventory


def _recompute_diffs(inventory: PhysicalInventory, lines: list[PhysicalInventoryLine]) -> None:
    gain = loss = 0
    for l in lines:
        if l.final_qty is None:
            l.diff_qty = l.diff_value_minor = None
            continue
        l.diff_qty = D(l.final_qty) - D(l.book_qty)
        l.diff_value_minor = line_amount(l.diff_qty, int(l.unit_price_minor)) if l.unit_price_minor is not None else 0
        if l.diff_value_minor > 0:
            gain += l.diff_value_minor
        else:
            loss += -l.diff_value_minor
    inventory.gain_minor, inventory.loss_minor = gain, loss


def request_recount(session: Session, inventory: PhysicalInventory, *, materials: Optional[list] = None, reason: str) -> PhysicalInventory:
    """The controller orders a recount of some lines (all lines outside the tolerance when none are named): they wait for another counter."""
    if len((reason or "").strip()) < 3:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for the recount", rule_ref="INVENTORY-COUNT")
    if inventory.status not in ("COUNTING", "COUNTED", "PENDING_APPROVAL"):
        raise illegal_transition("Physical inventory", inventory.number, inventory.status, "recount")
    rule = ir.rule(session, ir.COUNT_KEY, company_code=inventory.company_code, plant=inventory.plant)
    wanted = {str(m) for m in materials or []}
    numbers = {m.id: m.number for m in session.execute(select(Material).where(Material.id.in_([l.material_id for l in count_lines(session, inventory)]))).scalars()}
    chosen = []
    for line in count_lines(session, inventory):
        if wanted:
            if numbers[line.material_id] in wanted and line.count_status != "PENDING":
                chosen.append(line)
        elif line.count_status == "RECOUNTED" or (line.final_qty is not None and line.diff_qty not in (None, 0)
                                                  and not _within_tolerance(rule.body, D(line.book_qty), D(line.final_qty), line.unit_price_minor)):
            chosen.append(line)
    if wanted and len(chosen) < len(wanted & set(numbers.values())):
        missing = sorted(wanted - {numbers[l.material_id] for l in chosen})
        raise Problem(422, "VALIDATION_FAILED", f"Not counted yet or not on the count: {', '.join(missing)}", rule_ref=rule.ref)
    if not chosen:
        raise Problem(422, "NOTHING_TO_RECOUNT", "No line is outside the tolerance; name the materials to recount", rule_ref=rule.ref)
    for line in chosen:
        line.count_status, line.final_qty, line.recount_qty, line.recounted_by, line.recounted_at = "RECOUNT_REQUIRED", None, None, None, None
        line.recount_reason = reason.strip()
    session.flush()
    _recompute_diffs(inventory, count_lines(session, inventory))
    if inventory.status == "PENDING_APPROVAL":
        _cancel_tasks(session, COUNT_APPROVAL, inventory.id)
        COUNT_SM.apply(session, inventory, "reopen", reason=reason.strip(), rule_set_version=rule.ref, extra_after={"recountLines": len(chosen)})
    elif inventory.status == "COUNTED":
        COUNT_SM.apply(session, inventory, "reopen", reason=reason.strip(), rule_set_version=rule.ref, extra_after={"recountLines": len(chosen)})
    else:
        audit.record(session, "PHYSICAL_INVENTORY", inventory.id, "RECOUNT_REQUESTED", object_ref=inventory.number, reason=reason.strip(),
                     rule_set_version=rule.ref, after={"lines": [numbers[l.material_id] for l in chosen]})
    return inventory


def submit_count(session: Session, inventory: PhysicalInventory) -> PhysicalInventory:
    p = principal(session)
    if inventory.status != "COUNTED":
        raise illegal_transition("Physical inventory", inventory.number, inventory.status, "submit")
    abac.guard(session, "INVENTORY_COUNT", None, plant=inventory.plant, company_code=inventory.company_code)
    rule = ir.rule(session, ir.COUNT_KEY, company_code=inventory.company_code, plant=inventory.plant)
    lines = count_lines(session, inventory)
    open_lines = [l for l in lines if l.final_qty is None]
    if open_lines:
        raise Problem(422, "COUNT_INCOMPLETE", f"{len(open_lines)} line(s) are not counted or still need a recount", rule_ref=rule.ref)
    _recompute_diffs(inventory, lines)
    counted = [l for l in lines if l.first_count_ok is not None]
    inventory.accuracy_pct = (Decimal(sum(1 for l in counted if l.first_count_ok)) * 100 / len(counted)).quantize(Decimal("0.01")) if counted else None
    inventory.submitted_by, inventory.submitted_at, inventory.rule_set_version = p.user_id, clock.now(), rule.ref
    total = inventory.total_value_minor
    chain = ir.band_chain(rule.body, total)
    counters = sorted({u for l in lines for u in (l.counted_by, l.recounted_by) if u}, key=str)
    COUNT_SM.apply(session, inventory, "submit", rule_set_version=rule.ref,
                   extra_after={"gainMinor": inventory.gain_minor, "lossMinor": inventory.loss_minor, "accuracyPct": inventory.accuracy_pct, "chain": chain})
    workflow.start_approval(session, None, COUNT_APPROVAL, object_type="PHYSICAL_INVENTORY", object_id=inventory.id, object_ref=inventory.number,
                            chain=chain, step_id=None, initiator_id=p.user_id, exclude=counters,
                            sla_business_days=int(rule.body["slaBusinessDays"]),
                            rule_set_version=rule.ref,
                            evidence={"plant": inventory.plant, "storageLocation": inventory.storage_location, "gainMinor": inventory.gain_minor,
                                      "lossMinor": inventory.loss_minor, "totalValueMinor": total, "valueMinor": total, "lines": len(lines),
                                      "differences": sum(1 for l in lines if l.diff_qty), "accuracyPct": str(inventory.accuracy_pct), "chain": chain})
    return inventory


def _count_approval_guard(session: Session, task: Task, decision: str) -> None:
    if decision.upper() == "APPROVE":
        sod.guard(session, "INVENTORY_COUNT_APPROVE", {"count_id": task.object_id})
        sod.record(session, "INVENTORY_COUNT_APPROVE", {"count_id": task.object_id})


workflow.guard_task(COUNT_APPROVAL)(_count_approval_guard)


@workflow.on_task(COUNT_APPROVAL)
def _count_decided(session: Session, task: Task, outcome: str) -> None:
    inventory = session.get(PhysicalInventory, task.object_id)
    if inventory is None or inventory.status != "PENDING_APPROVAL":
        return
    inventory.decision_comment = task.comment
    if outcome == "APPROVED":
        inventory.approved_by, inventory.approved_at = task.completed_by, clock.now()
        COUNT_SM.apply(session, inventory, "approve", reason=task.comment, rule_set_version=inventory.rule_set_version,
                       extra_after={"approvedBy": str(task.completed_by)})
    else:
        COUNT_SM.apply(session, inventory, "reject", reason=task.comment or "not approved", rule_set_version=inventory.rule_set_version)


def decide_count(session: Session, inventory: PhysicalInventory, decision: str, comment: Optional[str]) -> PhysicalInventory:
    if inventory.status != "PENDING_APPROVAL":
        raise illegal_transition("Physical inventory", inventory.number, inventory.status, decision.lower())
    if decision == "APPROVE":
        sod.guard(session, "INVENTORY_COUNT_APPROVE", {"count_id": inventory.id})
    elif len((comment or "").strip()) < 3:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for rejecting the count", rule_ref="INVENTORY-COUNT")
    task = _open_task(session, COUNT_APPROVAL, inventory.id)
    if task is None:
        raise Problem(409, "NO_OPEN_APPROVAL", f"{inventory.number} has no open approval task", rule_ref="INVENTORY-COUNT")
    workflow.complete(session, task.id, decision, (comment or "").strip() or None)
    return inventory


def cancel_count(session: Session, inventory: PhysicalInventory, reason: str) -> PhysicalInventory:
    if len((reason or "").strip()) < 3:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for cancelling the count", rule_ref="INVENTORY-COUNT")
    COUNT_SM.apply(session, inventory, "cancel", reason=reason.strip(), rule_set_version=inventory.rule_set_version)
    _cancel_tasks(session, COUNT_APPROVAL, inventory.id)
    inventory.decision_comment = reason.strip()
    return inventory


def post_count(session: Session, inventory: PhysicalInventory) -> PhysicalInventory:
    """Post the differences of an approved count: the delta between the count and the book quantity at the freeze (701 gain, 702 loss) on
    unrestricted stock, whatever has moved since. A loss larger than the stock now on hand is refused."""
    p = principal(session)
    if inventory.status == "POSTED":
        return inventory
    if inventory.status != "APPROVED":
        raise illegal_transition("Physical inventory", inventory.number, inventory.status, "post")
    abac.guard(session, "INVENTORY_POST", None, plant=inventory.plant, company_code=inventory.company_code)
    org_guard.ensure_active(session, "physical inventory", company_code=inventory.company_code, plant=inventory.plant, storage_location=inventory.storage_location)
    _cut_off(session, inventory.company_code, f"inventory differences of {inventory.number}")
    rule = ir.rule(session, ir.COUNT_KEY, company_code=inventory.company_code, plant=inventory.plant)
    lines = count_lines(session, inventory)
    posted, drift_lines = [], 0
    for line in lines:
        if line.final_qty is None:
            raise Problem(422, "COUNT_INCOMPLETE", "A line has no accepted count", rule_ref=rule.ref)
        current = stock_ledger.on_hand(session, line.material_id, inventory.plant, inventory.storage_location, "UNRESTRICTED", line.batch)
        line.drift_qty = current - D(line.book_qty)
        if line.drift_qty:
            drift_lines += 1
        delta = D(line.final_qty) - D(line.book_qty)
        line.posted_qty = delta
        if delta == 0:
            continue
        if current + delta < 0:
            material = session.get(Material, line.material_id)
            raise Problem(422, "NEGATIVE_STOCK", f"{material.number}: the loss of {-delta} counted against the freeze would leave {current + delta} "
                          f"(stock now {current}, book at the freeze {line.book_qty}); recount or cancel", rule_ref=rule.ref,
                          material=material.number, stockNow=jsonable(current), bookAtFreeze=jsonable(line.book_qty))
        stock_ledger.post_movement(session, material_id=line.material_id, plant=inventory.plant, sloc=inventory.storage_location,
                                   stock_type="UNRESTRICTED", batch=line.batch, qty=delta, movement="701" if delta > 0 else "702",
                                   ref_type="PHYSICAL_INVENTORY", ref_id=inventory.id, ref=inventory.number, posting_ref=inventory.number,
                                   reason_code=rule.body.get("differenceReasonCode", "COUNT_DIFF"))
        posted.append({"material": session.get(Material, line.material_id).number, "batch": line.batch, "qty": str(delta),
                       "movement": "701" if delta > 0 else "702", "valueMinor": line.diff_value_minor or 0})
    inventory.posted_by, inventory.posted_at = p.user_id, clock.now()
    COUNT_SM.apply(session, inventory, "post", rule_set_version=rule.ref,
                   extra_after={"differences": len(posted), "gainMinor": inventory.gain_minor, "lossMinor": inventory.loss_minor,
                                "linesWithMovementSinceFreeze": drift_lines})
    erp = {"status": "NOTHING_TO_POST", "erpDocument": None}
    if posted:
        erp = stock_ledger.enqueue_erp(session, object_type="PHYSICAL_INVENTORY", object_id=inventory.id, ref=inventory.number,
                                       company_code=inventory.company_code, key=f"PHI|{inventory.number}",
                                       payload={"inventory": inventory.number, "plant": inventory.plant, "storageLocation": inventory.storage_location,
                                                "grossMinor": inventory.gain_minor + inventory.loss_minor, "lines": posted})
    outbox.emit(session, "physical_inventory.posted", "PHYSICAL_INVENTORY", inventory.id, inventory.number,
                {"inventory": inventory.number, "plant": inventory.plant, "storageLocation": inventory.storage_location, "lines": len(lines),
                 "differences": len(posted), "gainMinor": inventory.gain_minor, "lossMinor": inventory.loss_minor,
                 "accuracyPct": str(inventory.accuracy_pct) if inventory.accuracy_pct is not None else None, "erpDocument": erp.get("erpDocument")})
    return inventory


# ================================================================ 3 reservations
def _cost_object(session: Session, spec: Optional[str], company_code: str, required: bool) -> tuple[Optional[str], Optional[str]]:
    if not spec:
        if required:
            raise Problem(422, "COST_OBJECT_REQUIRED", "Give the cost object the stock is for, e.g. COST_CENTER:6100", rule_ref="INVENTORY-RESERVATION")
        return None, None
    kind, _, code = spec.partition(":")
    if not code:
        raise Problem(422, "VALIDATION_FAILED", "cost object must look like COST_CENTER:6100", rule_ref="INVENTORY-RESERVATION")
    found = session.execute(select(CostObject).where(CostObject.type == kind.upper(), CostObject.code == code)).scalar_one_or_none()
    if found is None:
        raise Problem(422, "UNKNOWN_COST_OBJECT", f"Cost object {spec} does not exist", rule_ref="INVENTORY-RESERVATION")
    if not found.active:
        raise Problem(422, "ORG_RECORD_INACTIVE", f"Cost object {spec} is deactivated in the organisation master (ADM-01)", rule_ref="ADM-01")
    if found.company_code != company_code:
        raise Problem(422, "VALIDATION_FAILED", f"Cost object {spec} belongs to company code {found.company_code}, the plant to {company_code}",
                      rule_ref="INVENTORY-RESERVATION")
    return found.type, found.code


def availability(session: Session, material_id, plant: str, sloc: str, exclude_id=None) -> dict:
    on_hand = stock_ledger.on_hand(session, material_id, plant, sloc)
    reserved = stock_ledger.reserved_open(session, material_id, plant, sloc, exclude_id=exclude_id)
    free = on_hand - reserved
    return {"onHand": on_hand, "reservedByOthers": reserved, "available": free}


def _sync_demand(session: Session, res: StockReservation, live: bool) -> None:
    """The reservation's RESERVATION demand element for MRP: its open quantity while it lives, zero once it is closed. The row is kept (at
    zero, with a new ``changed_at``) so a net-change MRP run replans the material; the expiry job removes old zero rows."""
    element = session.get(DemandElement, res.demand_element_id) if res.demand_element_id else None
    open_qty = (D(res.qty) - D(res.issued_qty)) if live else Decimal(0)
    if element is None:
        element = DemandElement(tenant_id=res.tenant_id, material_id=res.material_id, plant=res.plant, type="RESERVATION", reference=res.number,
                                req_date=res.need_date, qty=open_qty, changed_at=clock.now(), created_by=res.created_by)
        session.add(element)
        session.flush()
        res.demand_element_id = element.id
    else:
        element.qty, element.req_date, element.changed_at = open_qty, res.need_date, clock.now()


def create_reservation(session: Session, *, material: str, plant: str, storage_location: str, qty, need_date: date, cost_object: Optional[str] = None,
                       purpose: Optional[str] = None) -> StockReservation:
    p = principal(session)
    plant_row = _plant(session, _need(plant, "plant"))
    sloc = _need(storage_location, "storage location")
    _location(session, plant_row.code, sloc)
    abac.guard(session, "INVENTORY_RESERVE", None, plant=plant_row.code, company_code=plant_row.company_code)
    org_guard.ensure_active(session, "reservation", company_code=plant_row.company_code, plant=plant_row.code, storage_location=sloc)
    rule = ir.rule(session, ir.RESERVATION_KEY, company_code=plant_row.company_code, plant=plant_row.code)
    mat = _stock_material(session, _need(material, "material"))
    quantity = _qty(qty, "reservation")
    if need_date < clock.today():
        raise rule_violation(f"The need date {need_date.isoformat()} is in the past", rule.ref)
    if need_date > clock.today() + timedelta(days=int(rule.body["maxOpenDays"])):
        raise rule_violation(f"The need date {need_date.isoformat()} is more than {rule.body['maxOpenDays']} days ahead", rule.ref)
    purpose = (purpose or "").strip() or None
    cost_type, cost_code = _cost_object(session, cost_object, plant_row.company_code, bool(rule.body["requireCostObject"]))
    avail = availability(session, mat.id, plant_row.code, sloc)
    short = max(quantity - avail["available"], Decimal(0))
    if short > 0 and rule.body["blockWhenUnavailable"]:
        raise Problem(422, "INSUFFICIENT_STOCK", f"{mat.number}: {avail['available']} available at {plant_row.code}/{sloc} after other reservations "
                      f"({avail['onHand']} on hand, {avail['reservedByOthers']} reserved); {quantity} reserved", rule_ref=rule.ref,
                      availableQty=jsonable(avail["available"]), requiredQty=jsonable(quantity))
    res = StockReservation(tenant_id=p.tenant_id, number=next_number(session, "STOCK_RESERVATION"), status="OPEN", company_code=plant_row.company_code,
                           material_id=mat.id, plant=plant_row.code, storage_location=sloc, qty=quantity, issued_qty=0, need_date=need_date,
                           cost_object_type=cost_type, cost_object_code=cost_code, purpose=purpose, requester_id=p.user_id,
                           availability={"onHand": jsonable(avail["onHand"]), "reservedByOthers": jsonable(avail["reservedByOthers"]),
                                         "available": jsonable(avail["available"]), "shortBy": jsonable(short), "checkedAt": clock.now().isoformat()}, rule_set_version=rule.ref, created_by=p.user_id)
    session.add(res)
    session.flush()
    _sync_demand(session, res, True)
    audit.record(session, "STOCK_RESERVATION", res.id, "CREATED", object_ref=res.number, rule_set_version=rule.ref, reason=purpose,
                 after={"material": mat.number, "plant": res.plant, "storageLocation": sloc, "qty": str(quantity), "needDate": need_date.isoformat(),
                        "costObject": cost_object, "shortBy": str(short)})
    outbox.emit(session, "stock_reservation.created", "STOCK_RESERVATION", res.id, res.number,
                {"reservation": res.number, "material": mat.number, "plant": res.plant, "qty": str(quantity), "needDate": need_date.isoformat(),
                 "shortBy": str(short)})
    return res


def issue_reservation(session: Session, res: StockReservation, *, qty=None, batch: Optional[str] = None) -> StockReservation:
    p = principal(session)
    if res.status not in stock_ledger.OPEN_RESERVATION:
        raise illegal_transition("Reservation", res.number, res.status, "issue")
    abac.guard(session, "INVENTORY_POST", None, plant=res.plant, company_code=res.company_code)
    org_guard.ensure_active(session, "goods issue", company_code=res.company_code, plant=res.plant, storage_location=res.storage_location)
    _cut_off(session, res.company_code, f"goods issue for {res.number}")
    rule = ir.rule(session, ir.RESERVATION_KEY, company_code=res.company_code, plant=res.plant)
    open_qty = D(res.qty) - D(res.issued_qty)
    quantity = _qty(qty, "issue") if qty is not None else open_qty
    if quantity > open_qty:
        raise Problem(422, "EXCEEDS_RESERVATION", f"{res.number}: {quantity} requested but only {open_qty} is still reserved", rule_ref=rule.ref,
                      openQty=jsonable(open_qty))
    cost_type, cost_code = _cost_object(session, f"{res.cost_object_type}:{res.cost_object_code}" if res.cost_object_code else None, res.company_code, False)
    if (batch or "").strip():
        allocation = [((batch or "").strip(), quantity)]
        have = stock_ledger.on_hand(session, res.material_id, res.plant, res.storage_location, "UNRESTRICTED", allocation[0][0])
        if have < quantity:
            raise Problem(422, "INSUFFICIENT_STOCK", f"Only {have} unrestricted in batch {allocation[0][0]} at {res.plant}/{res.storage_location}",
                          rule_ref="STOCK", availableQty=jsonable(have), requiredQty=jsonable(quantity))
    else:
        allocation = stock_ledger.fefo_allocation(session, res.material_id, res.plant, res.storage_location, quantity, lock=True)
    material = session.get(Material, res.material_id)
    issued_total = D(res.issued_qty) + quantity
    for lot, part in allocation:
        stock_ledger.post_movement(session, material_id=res.material_id, plant=res.plant, sloc=res.storage_location, stock_type="UNRESTRICTED", batch=lot,
                                   qty=-part, movement="201", ref_type="STOCK_RESERVATION", ref_id=res.id, ref=res.number, posting_ref=res.number,
                                   reason_code=None)
    res.issued_qty = issued_total
    done = issued_total >= D(res.qty)
    RESERVATION_SM.apply(session, res, "issue" if done else "issue_part", rule_set_version=rule.ref,
                         extra_after={"issuedQty": str(quantity), "totalIssuedQty": str(issued_total), "openQty": str(D(res.qty) - issued_total),
                                      "batches": [{"batch": b, "qty": str(q)} for b, q in allocation], "costObject": f"{cost_type}:{cost_code}" if cost_code else None})
    if done:
        res.closed_at, res.closed_reason = clock.now(), "ISSUED"
    _sync_demand(session, res, not done)
    value = line_amount(quantity, int(material.standard_price_minor)) if material.standard_price_minor is not None else 0
    erp = stock_ledger.enqueue_erp(session, object_type="STOCK_RESERVATION", object_id=res.id, ref=res.number, company_code=res.company_code,
                                   key=f"RSV|{res.number}|{jsonable(issued_total)}",
                                   payload={"reservation": res.number, "plant": res.plant, "storageLocation": res.storage_location,
                                            "costObject": f"{cost_type}:{cost_code}" if cost_code else None, "grossMinor": value,
                                            "lines": [{"material": material.number, "batch": b, "qty": str(q), "movement": "201"} for b, q in allocation]})
    outbox.emit(session, "stock_reservation.issued", "STOCK_RESERVATION", res.id, res.number,
                {"reservation": res.number, "material": material.number, "plant": res.plant, "issuedQty": str(quantity), "openQty": str(D(res.qty) - issued_total),
                 "valueMinor": value, "erpDocument": erp.get("erpDocument")})
    return res


def cancel_reservation(session: Session, res: StockReservation, reason: str, *, expired: bool = False) -> StockReservation:
    p = principal(session)
    if len((reason or "").strip()) < 3:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for cancelling the reservation", rule_ref="INVENTORY-RESERVATION")
    if not expired and not (res.requester_id == p.user_id or "inventory:post" in p.scopes):
        raise Problem(403, "FORBIDDEN", "A reservation is cancelled by its requester or by a stock poster", rule_ref="RBAC")
    open_qty = D(res.qty) - D(res.issued_qty)
    RESERVATION_SM.apply(session, res, "expire" if expired else "cancel", reason=reason.strip(), rule_set_version=res.rule_set_version,
                         extra_after={"openQtyReleased": str(open_qty)})
    res.closed_at, res.closed_reason = clock.now(), reason.strip()
    _sync_demand(session, res, False)
    outbox.emit(session, "stock_reservation.cancelled", "STOCK_RESERVATION", res.id, res.number,
                {"reservation": res.number, "material": session.get(Material, res.material_id).number, "plant": res.plant, "openQty": str(open_qty),
                 "reason": reason.strip(), "expired": expired})
    return res


def expire_due(session: Session, today: Optional[date] = None, dry_run: bool = False) -> dict:
    """Expire the open reservations whose need date plus the grace of rule INVENTORY-RESERVATION has passed, and delete the zero-quantity
    reservation demand a net-change run has had time to see (older than seven days)."""
    today = today or clock.today()
    expired, purged = [], 0
    for res in session.execute(select(StockReservation).where(StockReservation.status.in_(stock_ledger.OPEN_RESERVATION),
                                                              StockReservation.need_date < today).order_by(StockReservation.need_date)
                               .with_for_update(skip_locked=True)).scalars().all():
        grace = int(ir.rule(session, ir.RESERVATION_KEY, company_code=res.company_code, plant=res.plant).body["graceDays"])
        if res.need_date + timedelta(days=grace) >= today:
            continue
        if not dry_run:
            cancel_reservation(session, res, f"Expired: need date {res.need_date.isoformat()} plus {grace} day(s) grace has passed", expired=True)
        expired.append(res.number)
    if not dry_run:
        cutoff = clock.now() - timedelta(days=7)
        for element in session.execute(select(DemandElement).where(DemandElement.type == "RESERVATION", DemandElement.qty == 0,
                                                                   DemandElement.changed_at < cutoff)).scalars().all():
            if session.execute(select(StockReservation.id).where(StockReservation.demand_element_id == element.id,
                                                                 StockReservation.status.in_(stock_ledger.OPEN_RESERVATION))).first():
                continue
            for res in session.execute(select(StockReservation).where(StockReservation.demand_element_id == element.id)).scalars():
                res.demand_element_id = None
            session.delete(element)
            purged += 1
    return {"expired": expired, "demandPurged": purged}
