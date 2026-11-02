"""Healthcare template controls (BP §23.1): clinical sign-off on awards (pending workflow 42), cold-chain tracking (43), par-level
planning with value-analysis (VAC) reports (44) and expiry write-offs (the expiry-write-off KPI).

Rules carried by the healthcare template: ``AWARD-APPROVAL.clinicalSignOff`` (an award is signed off by a clinical lead after the
value-based chain; the proposer and every earlier approver are excluded), ``COLD-CHAIN`` (allowed excursion minutes, who works the
excursion task) and ``PAR-LEVEL`` (reorder behaviour)."""
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    Asn, AsnLine, ColdChainReading, ColdChainSpec, GoodsReceipt, GrLine, InspectionLot, Material, ParLevel, PoLine, PrLine, PurchaseOrder,
    Requisition, Stock, StockMovement, Task,
)
from app.pic.platform import audit, clock, outbox, workflow
from app.pic.platform.core import link
from app.pic.platform.errors import Problem, illegal_transition, not_found, rule_violation
from app.pic.platform.money import D
from app.pic.platform.serialize import jsonable, row
from app.pic.services import ind_common
from app.pic.services.common import by_ref, material_by_number, principal

CLINICAL_ROLE = "CLINICAL_LEAD"
COLD_TASK = "COLD_CHAIN_EXCURSION"
QUARANTINE_MOVEMENT = {"UNRESTRICTED": "344", "CONSIGNMENT": "344K"}


# ---------------------------------------------------------------- 42 clinical sign-off on awards
def signoff_required(rule, category: Optional[str]) -> bool:
    """AWARD-APPROVAL.clinicalSignOff: every award, or only the categories listed in clinicalCategories."""
    body = rule.body or {}
    if not body.get("clinicalSignOff"):
        return False
    categories = body.get("clinicalCategories")
    return not categories or category in categories


def award_chain(rule, chain: list[str], category: Optional[str]) -> list[str]:
    """The value-based approval chain plus the clinical lead as the last approver when the rule asks for a clinical sign-off."""
    role = (rule.body or {}).get("clinicalRole", CLINICAL_ROLE)
    if signoff_required(rule, category) and role not in chain:
        return list(chain) + [role]
    return list(chain)


# ---------------------------------------------------------------- 43 cold chain
def set_spec(session: Session, *, material: str, min_c, max_c, max_excursion_minutes: Optional[int] = None, label: Optional[str] = None) -> ColdChainSpec:
    """Storage / transport temperature range of a material (e.g. 2-8 °C vaccines)."""
    p = principal(session)
    rule = ind_common.require_rule(session, "COLD-CHAIN", "Cold-chain tracking")
    mat = material_by_number(session, material)
    low, high = D(min_c), D(max_c)
    if high <= low:
        raise rule_violation("The maximum temperature is above the minimum", rule.ref)
    if max_excursion_minutes is not None and max_excursion_minutes < 0:
        raise Problem(422, "INVALID_MINUTES", "The allowed excursion is not negative")
    spec = session.execute(select(ColdChainSpec).where(ColdChainSpec.material_id == mat.id)).scalar_one_or_none()
    before = None
    if spec is None:
        spec = ColdChainSpec(tenant_id=current_tenant(session), material_id=mat.id, min_c=low, max_c=high, max_excursion_minutes=max_excursion_minutes,
                             label=label or f"{low:g}-{high:g} °C", created_by=p.user_id)
        session.add(spec)
    else:
        before = {"minC": str(spec.min_c), "maxC": str(spec.max_c)}
        spec.min_c, spec.max_c, spec.max_excursion_minutes, spec.label = low, high, max_excursion_minutes, label or f"{low:g}-{high:g} °C"
    session.flush()
    audit.record(session, "MATERIAL", mat.id, "COLD_CHAIN_SPEC_SET", object_ref=mat.number, before=before, rule_set_version=rule.ref,
                 after={"minC": str(low), "maxC": str(high), "maxExcursionMinutes": max_excursion_minutes})
    return spec


def _excursion_minutes(points: list[tuple[datetime, Decimal]], low: Decimal, high: Decimal) -> int:
    """Minutes outside [low, high]: every interval between two consecutive readings counts when either end is out of range
    (conservative: the logger does not say when inside the interval the temperature crossed the limit)."""
    total = 0
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if not (low <= v0 <= high) or not (low <= v1 <= high):
            total += int((t1 - t0).total_seconds() // 60)
    return total


def record_readings(session: Session, *, object_type: str, ref: str, material: str, logger_id: str, readings: list[dict],
                    batch: Optional[str] = None) -> ColdChainReading:
    """Temperature-logger readings for a material on an ASN (in transit) or a goods receipt. An excursion beyond the allowed minutes
    puts the received stock of that material (and batch) in blocked stock, opens a quality task, and — on an ASN — does the same when
    the goods are received."""
    p = principal(session)
    rule = ind_common.require_rule(session, "COLD-CHAIN", "Cold-chain tracking")
    object_type = object_type.upper()
    if object_type not in ("ASN", "GOODS_RECEIPT"):
        raise Problem(422, "INVALID_OBJECT", "object_type is ASN or GOODS_RECEIPT")
    document = by_ref(session, Asn if object_type == "ASN" else GoodsReceipt, ref)
    mat = material_by_number(session, material)
    spec = session.execute(select(ColdChainSpec).where(ColdChainSpec.material_id == mat.id)).scalar_one_or_none()
    if spec is None:
        raise rule_violation(f"{mat.number} has no cold-chain temperature range: set it first", rule.ref)
    if len(readings) < 2:
        raise Problem(422, "VALIDATION_FAILED", "A logger trace has at least two readings", rule_ref=rule.ref)
    points = []
    for item in readings:
        at = item["at"] if isinstance(item["at"], datetime) else datetime.fromisoformat(str(item["at"]))
        points.append((at if at.tzinfo else at.replace(tzinfo=clock.IST), D(item["temp_c"])))
    points.sort(key=lambda point: point[0])
    if session.execute(select(ColdChainReading.id).where(ColdChainReading.logger_id == logger_id, ColdChainReading.object_type == object_type,
                                                          ColdChainReading.object_id == document.id, ColdChainReading.material_id == mat.id)).first():
        raise Problem(409, "DUPLICATE_READING", f"Logger {logger_id} already reported for {document.number} and {mat.number}", rule_ref=rule.ref)
    allowed = spec.max_excursion_minutes if spec.max_excursion_minutes is not None else int(rule.body.get("maxExcursionMinutes", 30))
    minutes = _excursion_minutes(points, spec.min_c, spec.max_c)
    po_id = document.po_id
    reading = ColdChainReading(
        tenant_id=current_tenant(session), logger_id=logger_id, object_type=object_type, object_id=document.id, object_ref=document.number, material_id=mat.id,
        po_id=po_id, batch=batch, readings=[{"at": at.isoformat(), "tempC": str(v)} for at, v in points], min_seen_c=min(v for _, v in points),
        max_seen_c=max(v for _, v in points), excursion_minutes=minutes, status="EXCURSION" if minutes > allowed else "OK", quarantined_qty=0,
        spec={"minC": str(spec.min_c), "maxC": str(spec.max_c), "allowedMinutes": allowed, "quarantine": []}, created_by=p.user_id)
    session.add(reading)
    session.flush()
    audit.record(session, "COLD_CHAIN_READING", reading.id, "RECORDED", object_ref=f"{document.number}/{mat.number}", rule_set_version=rule.ref,
                 after={"logger": logger_id, "minSeen": str(reading.min_seen_c), "maxSeen": str(reading.max_seen_c), "range": f"{spec.min_c}..{spec.max_c}",
                        "excursionMinutes": minutes, "allowedMinutes": allowed, "status": reading.status})
    if reading.status == "EXCURSION":
        outbox.emit(session, "cold_chain.excursion", "COLD_CHAIN_READING", reading.id, document.number,
                    {"material": mat.number, "object": document.number, "minutes": minutes, "minSeen": str(reading.min_seen_c),
                     "maxSeen": str(reading.max_seen_c)})
        if object_type == "GOODS_RECEIPT":
            _quarantine(session, reading, document, rule)
        else:
            _open_task(session, reading, document, rule, exclude=[], note="excursion in transit: stock is quarantined when the goods are received")
    return reading


def _receipt_lines(session: Session, gr: GoodsReceipt, material_id: uuid.UUID, batch: Optional[str]) -> list[GrLine]:
    query = select(GrLine).where(GrLine.gr_id == gr.id, GrLine.material_id == material_id)
    if batch:
        query = query.where(GrLine.batch == batch)
    return list(session.execute(query).scalars())


def _quarantine(session: Session, reading: ColdChainReading, gr: GoodsReceipt, rule) -> None:
    """Move the unrestricted / consignment stock of the receipt lines to blocked stock; quality stock stays where it is (the open
    inspection lot is decided by the task). Opens the quality task."""
    from app.pic.services.receiving import _move

    quarantined = list(reading.spec.get("quarantine") or [])
    total = Decimal(0)
    for gr_line in _receipt_lines(session, gr, reading.material_id, reading.batch):
        if any(q["grLine"] == str(gr_line.id) for q in quarantined):
            continue
        po_line = session.get(PoLine, gr_line.po_line_id)
        if gr_line.stock_type in QUARANTINE_MOVEMENT:
            stock = session.execute(select(Stock).where(Stock.material_id == gr_line.material_id, Stock.plant == po_line.plant,
                                                        Stock.storage_location == gr_line.storage_location, Stock.stock_type == gr_line.stock_type,
                                                        Stock.batch == gr_line.batch)).scalar_one_or_none()
            qty = min(D(gr_line.qty), D(stock.qty) if stock else Decimal(0))
            if qty <= 0:
                continue
            movement = QUARANTINE_MOVEMENT[gr_line.stock_type]
            common = dict(material_id=gr_line.material_id, plant=po_line.plant, sloc=gr_line.storage_location, batch=gr_line.batch, movement=movement,
                          ref_type="COLD_CHAIN_READING", ref_id=reading.id, ref=gr.number)
            _move(session, stock_type=gr_line.stock_type, qty=-qty, **common)
            _move(session, stock_type="BLOCKED", qty=qty, **common)
            quarantined.append({"grLine": str(gr_line.id), "qty": str(qty), "from": gr_line.stock_type, "sloc": gr_line.storage_location,
                                "batch": gr_line.batch, "plant": po_line.plant})
            total += qty
        elif gr_line.stock_type == "QUALITY":
            quarantined.append({"grLine": str(gr_line.id), "qty": str(gr_line.qty), "from": "QUALITY", "sloc": gr_line.storage_location,
                                "batch": gr_line.batch, "plant": po_line.plant})
            total += D(gr_line.qty)
    reading.spec = {**reading.spec, "quarantine": quarantined}
    reading.quarantined_qty = D(reading.quarantined_qty) + total
    reading.status = "QUARANTINED"
    audit.record(session, "GOODS_RECEIPT", gr.id, "COLD_CHAIN_QUARANTINE", object_ref=gr.number, rule_set_version=rule.ref,
                 after={"material": session.get(Material, reading.material_id).number, "quarantinedQty": str(total), "lines": quarantined,
                        "excursionMinutes": reading.excursion_minutes})
    link(session, "GOODS_RECEIPT", gr.id, gr.number, "COLD_CHAIN_READING", reading.id, f"{gr.number}/{reading.logger_id}", "quarantined_by")
    if reading.task_id is None:
        _open_task(session, reading, gr, rule, exclude=[gr.posted_by], note=None)


def _open_task(session: Session, reading: ColdChainReading, document, rule, *, exclude: list, note: Optional[str]) -> None:
    mat = session.get(Material, reading.material_id)
    task = ind_common.open_task(
        session, COLD_TASK, rule.body.get("taskRole", "QUALITY_INSPECTOR"), object_type="COLD_CHAIN_READING", object_id=reading.id,
        object_ref=f"{document.number}/{mat.number}", exclude=exclude, rule_set_version=rule.ref, sla_business_days=1,
        evidence={"material": mat.number, "document": document.number, "documentType": reading.object_type, "logger": reading.logger_id,
                  "range": f"{reading.spec['minC']}..{reading.spec['maxC']} °C", "minSeen": str(reading.min_seen_c), "maxSeen": str(reading.max_seen_c),
                  "excursionMinutes": reading.excursion_minutes, "allowedMinutes": reading.spec["allowedMinutes"], "note": note,
                  "decision": "APPROVE releases the stock with a documented justification; REJECT writes it off and rejects the inspection lot"})
    reading.task_id = task.id


@workflow.on_task(COLD_TASK)
def _cold_decided(session: Session, task: Task, outcome: str) -> None:
    from app.pic.services import receiving
    from app.pic.services.receiving import _move

    reading = session.get(ColdChainReading, task.object_id)
    if reading is None:
        return
    mat = session.get(Material, reading.material_id)
    if outcome == "APPROVED":
        if not (task.comment or "").strip():
            raise Problem(422, "COMMENT_REQUIRED", "A release after a temperature excursion needs a documented justification")
        for item in reading.spec.get("quarantine") or []:
            if item["from"] in QUARANTINE_MOVEMENT:
                qty = D(item["qty"])
                movement = "343" if item["from"] == "UNRESTRICTED" else "344K"
                common = dict(material_id=reading.material_id, plant=item["plant"], sloc=item["sloc"], batch=item["batch"], movement=movement,
                              ref_type="COLD_CHAIN_READING", ref_id=reading.id, ref=reading.object_ref)
                _move(session, stock_type="BLOCKED", qty=-qty, **common)
                _move(session, stock_type=item["from"], qty=qty, **common)
        reading.status, reading.disposition_note = "RELEASED", task.comment
        audit.record(session, "COLD_CHAIN_READING", reading.id, "RELEASED", object_ref=reading.object_ref, reason=task.comment,
                     after={"material": mat.number, "quarantinedQty": str(reading.quarantined_qty)})
        return
    # REJECTED or RETURNED: write the blocked stock off; quality stock is rejected through its inspection lot.
    value = 0
    for item in reading.spec.get("quarantine") or []:
        qty = D(item["qty"])
        gr_line = session.get(GrLine, uuid.UUID(item["grLine"]))
        po_line = session.get(PoLine, gr_line.po_line_id)
        if item["from"] in QUARANTINE_MOVEMENT:
            _move(session, material_id=reading.material_id, plant=item["plant"], sloc=item["sloc"], stock_type="BLOCKED", batch=item["batch"], qty=-qty,
                  movement="551", ref_type="COLD_CHAIN_REJECT", ref_id=reading.id, ref=reading.object_ref)
            value += int(qty * (mat.standard_price_minor or po_line.unit_price_minor))
        else:
            lot = session.execute(select(InspectionLot).where(InspectionLot.gr_line_id == gr_line.id, InspectionLot.status == "OPEN")).scalar_one_or_none()
            if lot is not None:
                receiving.usage_decision(session, lot, accepted=Decimal(0), rejected=D(lot.qty), defect_code="COLDCHAIN",
                                         reason=f"Temperature excursion {reading.excursion_minutes} min outside {reading.spec['minC']}..{reading.spec['maxC']} °C")
                value += int(D(lot.qty) * (mat.standard_price_minor or po_line.unit_price_minor))
    reading.status, reading.disposition_note = "REJECTED", task.comment
    audit.record(session, "COLD_CHAIN_READING", reading.id, "REJECTED", object_ref=reading.object_ref, reason=task.comment,
                 after={"material": mat.number, "writtenOffValueMinor": value})
    outbox.emit(session, "cold_chain.rejected", "COLD_CHAIN_READING", reading.id, reading.object_ref, {"material": mat.number, "valueMinor": value})


def on_goods_receipt(session: Session, gr: GoodsReceipt) -> None:
    """Hook of goods-receipt posting: readings reported on the ASN of this receipt that showed an excursion quarantine the received
    goods of that material (the receiving clerk cannot release them: the quality task excludes the poster)."""
    if gr.asn_id is None:
        return
    rule = ind_common.rule_or_none(session, "COLD-CHAIN")
    if rule is None:
        return
    for reading in session.execute(select(ColdChainReading).where(ColdChainReading.object_type == "ASN", ColdChainReading.object_id == gr.asn_id,
                                                                  ColdChainReading.status.in_(("EXCURSION", "REJECTED")))).scalars():
        _quarantine(session, reading, gr, rule)


def reading_view(session: Session, reading: ColdChainReading) -> dict:
    mat = session.get(Material, reading.material_id)
    return row(reading, extra={"material": mat.number, "description": mat.description})


# ---------------------------------------------------------------- 44 par-level planning
def set_par_level(session: Session, *, plant: str, storage_location: str, material: str, par_qty, trigger_qty) -> ParLevel:
    p = principal(session)
    rule = ind_common.require_rule(session, "PAR-LEVEL", "Par-level planning")
    mat = material_by_number(session, material)
    par, trigger = D(par_qty), D(trigger_qty)
    if par <= 0 or trigger < 0 or trigger >= par:
        raise rule_violation("The par quantity is positive and the trigger is below it", rule.ref)
    level = session.execute(select(ParLevel).where(ParLevel.plant == plant, ParLevel.storage_location == storage_location,
                                                   ParLevel.material_id == mat.id)).scalar_one_or_none()
    before = None
    if level is None:
        level = ParLevel(tenant_id=current_tenant(session), plant=plant, storage_location=storage_location, material_id=mat.id, par_qty=par,
                         trigger_qty=trigger, active=True, created_by=p.user_id)
        session.add(level)
    else:
        before = {"parQty": str(level.par_qty), "triggerQty": str(level.trigger_qty)}
        level.par_qty, level.trigger_qty, level.active = par, trigger, True
    session.flush()
    audit.record(session, "PAR_LEVEL", level.id, "SET", object_ref=f"{plant}/{storage_location}/{mat.number}", before=before, rule_set_version=rule.ref,
                 after={"parQty": str(par), "triggerQty": str(trigger)})
    return level


def _on_hand(session: Session, level: ParLevel) -> Decimal:
    return D(session.execute(select(func.coalesce(func.sum(Stock.qty), 0)).where(
        Stock.material_id == level.material_id, Stock.plant == level.plant, Stock.storage_location == level.storage_location,
        Stock.stock_type.in_(("UNRESTRICTED", "CONSIGNMENT")))).scalar_one())


def _on_order(session: Session, level: ParLevel) -> Decimal:
    """Quantity already on its way: open order lines not yet received plus requisition lines not yet ordered."""
    ordered = D(session.execute(select(func.coalesce(func.sum(PoLine.qty - PoLine.received_qty), 0)).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(
        PoLine.material_id == level.material_id, PoLine.plant == level.plant, PoLine.storage_location == level.storage_location,
        PurchaseOrder.status.in_(("RELEASED", "TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED")), PoLine.qty > PoLine.received_qty)).scalar_one())
    requested = D(session.execute(select(func.coalesce(func.sum(PrLine.qty - PrLine.ordered_qty), 0)).join(Requisition, Requisition.id == PrLine.requisition_id).where(
        PrLine.material_id == level.material_id, PrLine.plant == level.plant, PrLine.storage_location == level.storage_location,
        Requisition.status.in_(("SUBMITTED", "IN_APPROVAL", "APPROVED", "PARTIALLY_ORDERED")), PrLine.qty > PrLine.ordered_qty)).scalar_one())
    return ordered + requested


def check_level(session: Session, level: ParLevel) -> Optional[Requisition]:
    """Replenish up to par when on hand plus on order is at or below the trigger. Returns the requisition raised, if any."""
    from app.pic.services import requisition

    rule = ind_common.require_rule(session, "PAR-LEVEL", "Par-level planning")
    if not level.active:
        return None
    on_hand, on_order = _on_hand(session, level), _on_order(session, level)
    if on_hand + on_order > level.trigger_qty:
        return None
    qty = level.par_qty - on_hand - on_order
    if qty <= 0:
        return None
    mat = session.get(Material, level.material_id)
    last_line = session.execute(select(PoLine, PurchaseOrder).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(
        PoLine.material_id == mat.id, PoLine.plant == level.plant, PoLine.purchase_type.in_(("STOCK", "CONSIGNMENT")))
        .order_by(PoLine.created_at.desc()).limit(1)).first()
    purchase_type = last_line[0].purchase_type if last_line else "STOCK"
    price = last_line[0].unit_price_minor if last_line else (mat.standard_price_minor or 0)
    need = clock.today() + timedelta(days=max(int(mat.planned_delivery_days or 0), 2))
    reference = f"PAR-{level.plant}-{level.storage_location}-{mat.number}"[:60]
    line = {"item_type": "MATERIAL", "purchase_type": purchase_type, "material": mat.number, "qty": str(qty), "price_est_minor": price, "need_date": need,
            "storage_location": level.storage_location}
    if last_line:
        line["preferred_supplier_id"] = last_line[1].supplier_id
    pr = requisition.create(session, origin="MANUAL", origin_ref=reference, purpose_code="PAR_REPLENISHMENT",
                            purpose_text=f"Par-level replenishment {level.plant}/{level.storage_location}: {qty} {mat.base_uom} {mat.number} to par {level.par_qty}",
                            plant=level.plant, lines=[line])
    level.last_replenished_at, level.open_requisition_id = clock.now(), pr.id
    link(session, "PAR_LEVEL", level.id, reference, "REQUISITION", pr.id, pr.number, "replenished_by")
    audit.record(session, "PAR_LEVEL", level.id, "REPLENISHMENT_REQUESTED", object_ref=reference, rule_set_version=rule.ref,
                 after={"requisition": pr.number, "qty": str(qty), "onHand": str(on_hand), "onOrder": str(on_order), "triggerQty": str(level.trigger_qty),
                        "parQty": str(level.par_qty), "purchaseType": purchase_type})
    requisition.submit(session, pr)
    return pr


def sweep(session: Session, plant: Optional[str] = None) -> dict:
    """Check every active par level (a nightly job, or after a count): the requisitions raised and the levels still in order."""
    query = select(ParLevel).where(ParLevel.active.is_(True))
    if plant:
        query = query.where(ParLevel.plant == plant)
    raised, checked = [], 0
    for level in session.execute(query.order_by(ParLevel.plant, ParLevel.storage_location)).scalars():
        checked += 1
        pr = check_level(session, level)
        if pr is not None:
            raised.append({"requisition": pr.number, "plant": level.plant, "storageLocation": level.storage_location,
                           "material": session.get(Material, level.material_id).number})
    return {"checked": checked, "requisitions": raised}


@outbox.consumer("consignment.withdrawn", "par-level-replenishment")
def _withdrawn(session: Session, event) -> None:
    """Replenishment on withdrawal: usage of a par-level material at its location checks that level straight away."""
    if ind_common.rule_or_none(session, "PAR-LEVEL") is None:
        return
    mat = session.execute(select(Material).where(Material.number == event.payload["material"])).scalar_one_or_none()
    if mat is None:
        return
    for level in session.execute(select(ParLevel).where(ParLevel.material_id == mat.id, ParLevel.plant == event.payload["plant"],
                                                        ParLevel.active.is_(True))).scalars():
        check_level(session, level)


def vac_report(session: Session, plant: Optional[str] = None, days: int = 90) -> dict:
    """Value-analysis committee report: per par-level item the usage over the period, days of supply on hand, stock-out risk,
    stock expiring within 90 days and the par level the usage would support (average daily usage × lead time + safety)."""
    since = clock.now() - timedelta(days=days)
    soon = clock.today() + timedelta(days=90)
    query = select(ParLevel, Material).join(Material, Material.id == ParLevel.material_id).where(ParLevel.active.is_(True))
    if plant:
        query = query.where(ParLevel.plant == plant)
    items, totals = [], {"valueOnHandMinor": 0, "expiringValueMinor": 0, "belowTrigger": 0}
    for level, mat in session.execute(query.order_by(ParLevel.plant, Material.number)).all():
        used = D(session.execute(select(func.coalesce(func.sum(-StockMovement.qty), 0)).where(
            StockMovement.material_id == mat.id, StockMovement.plant == level.plant, StockMovement.storage_location == level.storage_location,
            StockMovement.movement_type.in_(("201", "201K", "411K")), StockMovement.created_at >= since)).scalar_one())
        on_hand = _on_hand(session, level)
        daily = used / Decimal(days)
        expiring = D(session.execute(select(func.coalesce(func.sum(Stock.qty), 0)).where(
            Stock.material_id == mat.id, Stock.plant == level.plant, Stock.storage_location == level.storage_location, Stock.qty > 0,
            Stock.stock_type.in_(("UNRESTRICTED", "CONSIGNMENT")), Stock.batch.in_(
                select(GrLine.batch).join(GoodsReceipt, GoodsReceipt.id == GrLine.gr_id).where(
                    GrLine.material_id == mat.id, GrLine.expiry.isnot(None), GrLine.expiry <= soon, GrLine.batch != "", GoodsReceipt.status != "REVERSED")))).scalar_one())
        price = int(mat.standard_price_minor or 0)
        lead = int(mat.planned_delivery_days or 0) + int(mat.gr_processing_days or 0)
        suggested = (daily * Decimal(lead + 7)).quantize(Decimal("1"), rounding="ROUND_CEILING") if daily > 0 else None
        below = on_hand <= level.trigger_qty
        items.append({"plant": level.plant, "storageLocation": level.storage_location, "material": mat.number, "description": mat.description,
                      "uom": mat.base_uom, "parQty": jsonable(level.par_qty), "triggerQty": jsonable(level.trigger_qty), "onHand": jsonable(on_hand),
                      "usedQty": jsonable(used), "dailyUsage": str(daily.quantize(Decimal("0.001"))),
                      "daysOfSupply": str((on_hand / daily).quantize(Decimal("0.1"))) if daily > 0 else None, "belowTrigger": below,
                      "stockOutRisk": bool(daily > 0 and on_hand / daily < lead), "expiringQty": jsonable(expiring),
                      "expiringValueMinor": int(expiring * price), "suggestedPar": jsonable(suggested),
                      "parAdvice": ("INCREASE" if suggested is not None and suggested > level.par_qty else
                                    "DECREASE" if suggested is not None and suggested < level.par_qty * Decimal("0.6") else "KEEP")})
        totals["valueOnHandMinor"] += int(on_hand * price)
        totals["expiringValueMinor"] += int(expiring * price)
        totals["belowTrigger"] += 1 if below else 0
    return {"periodDays": days, "asOf": clock.today().isoformat(), "items": items, "totals": totals}


# ---------------------------------------------------------------- expiry write-off
def expired_stock(session: Session, as_of: Optional[date] = None) -> list[dict]:
    """Own stock (unrestricted) of batches whose expiry has passed; consignment stock is the supplier's, returned rather than written off."""
    as_of = as_of or clock.today()
    expired = (select(GrLine.material_id, GrLine.batch, func.min(GrLine.expiry).label("expiry")).join(GoodsReceipt, GoodsReceipt.id == GrLine.gr_id).where(
        GrLine.expiry.isnot(None), GrLine.expiry < as_of, GrLine.batch != "", GoodsReceipt.status != "REVERSED")
        .group_by(GrLine.material_id, GrLine.batch).subquery())
    rows = session.execute(select(Stock, Material, expired.c.expiry).join(Material, Material.id == Stock.material_id)
                           .join(expired, (expired.c.material_id == Stock.material_id) & (expired.c.batch == Stock.batch))
                           .where(Stock.qty > 0, Stock.stock_type == "UNRESTRICTED").order_by(Material.number, Stock.batch)).all()
    return [{"stock": stock, "material": mat, "expiry": expiry, "valueMinor": int(D(stock.qty) * (mat.standard_price_minor or 0))} for stock, mat, expiry in rows]


def write_off_expired(session: Session, reason: str, as_of: Optional[date] = None) -> dict:
    """Write expired own stock off (movement 551, reference EXPIRY_WRITE_OFF); the value feeds the expiry-write-off KPI."""
    from app.pic.services.receiving import _move

    if not (reason or "").strip():
        raise Problem(422, "REASON_REQUIRED", "Give the write-off reason (e.g. the monthly expiry sweep)")
    done, total = [], 0
    batch_id = uuid.uuid7()
    from app.pic.services.receiving import _guard_stock_change

    for item in expired_stock(session, as_of):
        stock, mat = item["stock"], item["material"]
        _guard_stock_change(session, stock.plant, f"expiry write-off of {mat.number} lot {stock.batch}")
        qty = D(stock.qty)
        _move(session, material_id=mat.id, plant=stock.plant, sloc=stock.storage_location, stock_type="UNRESTRICTED", batch=stock.batch, qty=-qty,
              movement="551", ref_type="EXPIRY_WRITE_OFF", ref_id=batch_id, ref=f"EXP-{(as_of or clock.today()).isoformat()}")
        audit.record(session, "MATERIAL", mat.id, "EXPIRY_WRITE_OFF", object_ref=mat.number, reason=reason,
                     after={"plant": stock.plant, "storageLocation": stock.storage_location, "batch": stock.batch, "qty": str(qty),
                            "expiry": item["expiry"].isoformat(), "valueMinor": item["valueMinor"]})
        done.append({"material": mat.number, "batch": stock.batch, "plant": stock.plant, "qty": str(qty), "expiry": item["expiry"].isoformat(),
                     "valueMinor": item["valueMinor"]})
        total += item["valueMinor"]
    if done:
        outbox.emit(session, "stock.expired_written_off", "EXPIRY_WRITE_OFF", batch_id, f"EXP-{(as_of or clock.today()).isoformat()}",
                    {"lines": len(done), "valueMinor": total})
    return {"writtenOff": done, "valueMinor": total}
