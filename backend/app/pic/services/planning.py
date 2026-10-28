"""F1 MRP run → planned order → purchase requisition (M02, Technical Document §9.1)."""
import math
import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    Asn, AsnLine, DemandElement, Material, MrpException, MrpRun, Plant, PlannedOrder, PoLine, PurchaseOrder, Stock,
)
from app.pic.platform import agents, audit, clock, outbox, workflow
from app.pic.platform.core import link, next_number
from app.pic.platform.errors import Problem, illegal_transition
from app.pic.services import source
from app.pic.services.common import principal

PROCESS = "pic.mrp-to-pr"
OPEN_PO_STATUSES = ("RELEASED", "TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED")


# ---------------------------------------------------------------- lot sizing
def lot_size(material: Material, net: Decimal, period_net: Optional[Decimal] = None, projected: Decimal = Decimal(0)) -> Decimal:
    policy = material.lot_size_policy
    if policy == "FIXED" and material.lot_size_qty:
        qty = (net / material.lot_size_qty).to_integral_value(ROUND_CEILING) * material.lot_size_qty
    elif policy == "EOQ" and material.annual_demand and material.ordering_cost_minor and material.holding_rate and material.standard_price_minor:
        holding = Decimal(material.standard_price_minor) * material.holding_rate
        eoq = Decimal(str(math.sqrt(float(2 * material.annual_demand * Decimal(material.ordering_cost_minor) / holding))))
        qty = max(net, eoq)
    elif policy == "PERIOD" and period_net is not None:
        qty = period_net
    elif policy == "MINMAX" and material.max_lot:
        qty = max(net, material.max_lot - projected)
    else:
        qty = net
    if material.min_lot and qty < material.min_lot:
        qty = material.min_lot
    if material.pack_size:
        qty = (qty / material.pack_size).to_integral_value(ROUND_CEILING) * material.pack_size
    return qty


# ---------------------------------------------------------------- supply and demand
def _supply(session: Session, material: Material, plant: str) -> dict:
    on_hand = session.execute(select(func.coalesce(func.sum(Stock.qty), 0)).where(
        Stock.material_id == material.id, Stock.plant == plant, Stock.stock_type == "UNRESTRICTED")).scalar()
    receipts: list[tuple[date, Decimal, str, str]] = []  # (date, qty, kind, ref)
    po_lines = session.execute(select(PoLine, PurchaseOrder).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(
        PoLine.material_id == material.id, PoLine.plant == plant, PurchaseOrder.status.in_(OPEN_PO_STATUSES))).all()
    open_po = Decimal(0)
    for line, po in po_lines:
        # Quantity not yet shipped (shipped quantities are counted as in-transit or received).
        remaining = max(line.qty - max(line.shipped_qty, line.received_qty), Decimal(0))
        if remaining > 0:
            receipts.append((line.need_date, remaining, "OPEN_PO", f"{po.number}/{line.line_no}"))
            open_po += remaining
    in_transit = Decimal(0)
    asn_lines = session.execute(select(AsnLine, Asn, PoLine).join(Asn, Asn.id == AsnLine.asn_id).join(PoLine, PoLine.id == AsnLine.po_line_id)
                                .where(PoLine.material_id == material.id, PoLine.plant == plant, Asn.status == "IN_TRANSIT")).all()
    for asn_line, asn, _ in asn_lines:
        remaining = asn_line.qty - asn_line.received_qty
        if remaining > 0:
            receipts.append((asn.expected_date, remaining, "IN_TRANSIT", asn.number))
            in_transit += remaining
    firmed = session.execute(select(PlannedOrder).where(PlannedOrder.material_id == material.id, PlannedOrder.plant == plant,
                                                        PlannedOrder.status == "FIRMED")).scalars().all()
    firm_receipts = Decimal(0)
    for order in firmed:
        receipts.append((order.need_date, order.qty, "FIRM_PLANNED", order.number))
        firm_receipts += order.qty
    return {"on_hand": Decimal(on_hand), "open_po": open_po, "in_transit": in_transit, "firm_receipts": firm_receipts,
            "receipts": receipts, "firmed": firmed}


def _calendar(session: Session, plant: str) -> tuple[list[int], list[date]]:
    row = session.execute(select(Plant).where(Plant.code == plant)).scalar_one()
    return list(row.working_days or [0, 1, 2, 3, 4, 5]), list(row.holidays or [])


def net_material(session: Session, material: Material, plant: str, run_date: date) -> dict:
    """Bucket-by-bucket netting. Returns the planned receipts needed and exceptions, without writing."""
    demand = session.execute(select(DemandElement).where(DemandElement.material_id == material.id,
                                                         DemandElement.plant == plant).order_by(DemandElement.req_date)).scalars().all()
    supply = _supply(session, material, plant)
    gross_by_day: dict[date, Decimal] = defaultdict(Decimal)
    for d in demand:
        gross_by_day[d.req_date] += d.qty
    receipt_by_day: dict[date, Decimal] = defaultdict(Decimal)
    for day, qty, _, _ in supply["receipts"]:
        receipt_by_day[day] += qty
    working_days, holidays = _calendar(session, plant)
    safety = material.safety_stock or Decimal(0)
    projected = supply["on_hand"]
    proposals, exceptions = [], []
    if projected < safety:
        exceptions.append({"code": "BELOW_SAFETY", "message": f"On-hand {projected} is below safety stock {safety}",
                           "action": "Expedite open supply or firm a planned order"})
    for day in sorted(set(gross_by_day) | set(receipt_by_day)):
        projected += receipt_by_day.get(day, Decimal(0))
        projected -= gross_by_day.get(day, Decimal(0))
        if projected < safety:
            net = safety - projected
            qty = lot_size(material, net, projected=projected)
            lead = material.planned_delivery_days + material.gr_processing_days
            release = clock.subtract_working_days(day, lead, working_days, holidays)
            proposals.append({"need_date": day, "release_date": release, "qty": qty, "net": net})
            if release < run_date:
                exceptions.append({"code": "PAST_DUE", "message": f"Release date {release} is before run date {run_date}",
                                   "action": "Expedite: source immediately or reschedule demand"})
            projected += qty
    # Firmed orders are never changed; differing dates raise reschedule messages.
    for order in supply["firmed"]:
        needs = [p["need_date"] for p in proposals]
        if needs and needs[0] < order.need_date:
            exceptions.append({"code": "RESCHEDULE_IN", "message": f"{order.number} needed on {needs[0]} (firmed for {order.need_date})",
                               "action": f"Reschedule {order.number} in", "planned_order": order.number})
    gross_total = sum(gross_by_day.values(), Decimal(0))
    return {
        "material": material.number, "plant": plant, "gross": gross_total, "on_hand": supply["on_hand"],
        "open_po": supply["open_po"], "in_transit": supply["in_transit"], "firm_receipts": supply["firm_receipts"],
        "safety_stock": safety,
        "net": max(Decimal(0), gross_total - (supply["on_hand"] + supply["open_po"] + supply["in_transit"] + supply["firm_receipts"]) + safety),
        "proposals": proposals, "exceptions": exceptions,
    }


# ---------------------------------------------------------------- run
def run(session: Session, *, plant: str, mode: str = "NET_CHANGE", materials: Optional[list[str]] = None,
        run_date: Optional[date] = None) -> MrpRun:
    p = principal(session)
    mode = mode.upper()
    if mode not in ("NET_CHANGE", "REGENERATIVE", "SIMULATION"):
        raise Problem(422, "INVALID_MODE", "mode must be NET_CHANGE, REGENERATIVE or SIMULATION")
    run_date = run_date or clock.today()
    mrp_run = MrpRun(tenant_id=current_tenant(session), number=next_number(session, "MRP_RUN"), mode=mode, plant=plant,
                     scope={"materials": materials} if materials else {}, run_date=run_date, status="RUNNING",
                     started_by=p.user_id, created_by=p.user_id)
    session.add(mrp_run)
    session.flush()
    instance = workflow.start(session, PROCESS, "MRP_RUN", mrp_run.id, mrp_run.number, {"mode": mode})
    workflow.step(session, instance, "F1-02", outcome=f"plant {plant}, {mode.lower().replace('_', '-')}")

    query = select(Material).where(Material.mrp_type == "PD", Material.status == "ACTIVE")
    if materials:
        query = query.where(Material.number.in_(materials))
    candidates = session.execute(query).scalars().all()
    if mode == "NET_CHANGE":
        last = session.execute(select(func.max(MrpRun.created_at)).where(MrpRun.plant == plant, MrpRun.id != mrp_run.id,
                                                                         MrpRun.mode != "SIMULATION")).scalar()
        if last is not None:
            changed = {row for row in session.execute(select(DemandElement.material_id).where(
                DemandElement.plant == plant, DemandElement.changed_at > last)).scalars()}
            candidates = [m for m in candidates if m.id in changed]
    workflow.step(session, instance, "F1-03", outcome=f"{len(candidates)} material(s) in scope")

    results, created, exception_count = [], 0, 0
    for material in candidates:
        result = net_material(session, material, plant, run_date)
        results.append({k: (str(v) if isinstance(v, Decimal) else v) for k, v in result.items()
                        if k not in ("proposals", "exceptions")}
                       | {"proposals": [{k: str(v) for k, v in pr.items()} for pr in result["proposals"]],
                          "exceptions": result["exceptions"]})
        if mode == "SIMULATION":
            continue
        # Unfirmed planned orders from earlier runs are replaced by this run.
        for old in session.execute(select(PlannedOrder).where(PlannedOrder.material_id == material.id,
                                                              PlannedOrder.plant == plant,
                                                              PlannedOrder.status == "CREATED")).scalars():
            old.status = "DELETED"
        for proposal in result["proposals"]:
            determination = source.determine(session, material, plant, proposal["need_date"], proposal["qty"])
            order = PlannedOrder(
                tenant_id=current_tenant(session), number=next_number(session, "PLANNED_ORDER"), mrp_run_id=mrp_run.id,
                material_id=material.id, plant=plant, storage_location="0001", qty=proposal["qty"],
                need_date=proposal["need_date"], release_date=proposal["release_date"], status="CREATED",
                source=determination.as_dict(),
                exception_codes=[e["code"] for e in result["exceptions"] if e["code"] == "PAST_DUE"], created_by=p.user_id,
            )
            session.add(order)
            session.flush()
            link(session, "MRP_RUN", mrp_run.id, mrp_run.number, "PLANNED_ORDER", order.id, order.number, "planned_by")
            created += 1
        for exc in result["exceptions"]:
            value = int(Decimal(material.standard_price_minor or 0) * result["net"])
            session.add(MrpException(tenant_id=current_tenant(session), mrp_run_id=mrp_run.id, material_id=material.id,
                                     code=exc["code"], message=exc["message"], value_at_risk_minor=value,
                                     recommended_action=exc["action"], status="OPEN", created_by=p.user_id))
            exception_count += 1

    workflow.step(session, instance, "F1-04", outcome="; ".join(
        f"{r['material']}: {r['gross']} − ({r['on_hand']} + {r['open_po']} + {r['in_transit']} + {r['firm_receipts']}) + {r['safety_stock']} = {r['net']}"
        for r in results) or "nothing to plan")
    mrp_run.results = results
    mrp_run.materials_planned = len(candidates)
    mrp_run.planned_orders_created = created
    mrp_run.exceptions_raised = exception_count
    mrp_run.completed_at = clock.now()
    if mode == "SIMULATION":
        mrp_run.status = "SIMULATED"
        workflow.end(session, instance, "F1-05", outcome="simulation: report only, no documents created")
    else:
        mrp_run.status = "COMPLETED"
        workflow.step(session, instance, "F1-05", outcome="live run")
        workflow.step(session, instance, "F1-06", outcome=f"{created} planned order(s), {exception_count} exception(s)")
        workflow.wait(session, instance, "F1-07", outcome="review exceptions, firm orders")
        if exception_count:
            agents.log_run(session, "MRP_EXCEPTION", object_type="MRP_RUN", object_id=mrp_run.id, object_ref=mrp_run.number,
                           inputs={"exceptions": exception_count}, evidence=[r["material"] for r in results],
                           output={"ranked": sorted((e["code"] for r in results for e in r["exceptions"]))},
                           confidence=0.8, action_taken="DRAFTED")
        outbox.emit(session, "mrp.run.completed", "MRP_RUN", mrp_run.id, mrp_run.number,
                    {"plant": plant, "mode": mode, "plannedOrders": created, "exceptions": exception_count})
    audit.record(session, "MRP_RUN", mrp_run.id, "COMPLETED", object_ref=mrp_run.number,
                 after={"mode": mode, "plannedOrders": created, "exceptions": exception_count})
    return mrp_run


# ---------------------------------------------------------------- firm and convert
def _run_instance(session: Session, order: PlannedOrder):
    return workflow.find(session, "MRP_RUN", order.mrp_run_id, PROCESS)


def firm(session: Session, order: PlannedOrder) -> PlannedOrder:
    if order.status != "CREATED":
        raise illegal_transition("Planned order", order.number, order.status, "firm")
    order.status = "FIRMED"
    audit.record(session, "PLANNED_ORDER", order.id, "FIRMED", object_ref=order.number, before={"status": "CREATED"},
                 after={"status": "FIRMED"})
    outbox.emit(session, "planned_order.firmed", "PLANNED_ORDER", order.id, order.number,
                {"qty": str(order.qty), "needDate": order.need_date.isoformat()})
    instance = _run_instance(session, order)
    if instance and instance.current_step == "F1-07":
        workflow.step(session, instance, "F1-07", outcome=f"{order.number} firmed")
    return order


def convert(session: Session, order: PlannedOrder, purpose_code: str = "MRP_REPLENISHMENT"):
    """Convert to a purchase requisition (origin MRP). It follows the same approval controls as manual PRs."""
    from app.pic.services import requisition  # local import: requisition imports planning for F1 callbacks

    if order.status not in ("CREATED", "FIRMED"):
        raise illegal_transition("Planned order", order.number, order.status, "convert")
    material = session.get(Material, order.material_id)
    determination = source.determine(session, material, order.plant, order.need_date, order.qty)
    price = next((a.unit_price_minor for a in determination.allocations if a.unit_price_minor), None) or material.standard_price_minor
    instance = _run_instance(session, order)
    if instance and instance.current_step == "F1-07" and order.status == "CREATED":
        workflow.step(session, instance, "F1-07", outcome=f"{order.number} reviewed")
    pr = requisition.create(session, origin="MRP", origin_ref=order.number, purpose_code=purpose_code,
                            purpose_text=f"MRP replenishment from {order.number}", plant=order.plant,
                            lines=[{"item_type": "MATERIAL", "purchase_type": "STOCK", "material": material.number,
                                    "qty": order.qty, "uom": material.base_uom, "price_est_minor": price,
                                    "need_date": order.need_date, "storage_location": order.storage_location,
                                    "planned_order_id": order.id, "source_determination": determination.as_dict()}])
    order.status = "CONVERTED"
    order.requisition_id = pr.id
    link(session, "PLANNED_ORDER", order.id, order.number, "REQUISITION", pr.id, pr.number, "converted_from", to_line=10)
    audit.record(session, "PLANNED_ORDER", order.id, "CONVERTED", object_ref=order.number, after={"requisition": pr.number,
                                                                                                   "source": determination.method})
    if instance:
        workflow.step(session, instance, "F1-08", outcome=f"{pr.number} created; source: {determination.method}")
    requisition.submit(session, pr)
    return pr


def on_requisition_approved(session: Session, pr) -> None:
    """F1-09/F1-10: the converted PR reaches the buyer workbench."""
    if pr.origin != "MRP":
        return
    order = session.execute(select(PlannedOrder).where(PlannedOrder.requisition_id == pr.id)).scalar_one_or_none()
    if order is None:
        return
    instance = _run_instance(session, order)
    if instance and instance.status == "RUNNING":
        workflow.step(session, instance, "F1-09", outcome=f"{pr.number} in buyer workbench")
        remaining = session.execute(select(func.count()).select_from(PlannedOrder).where(
            PlannedOrder.mrp_run_id == order.mrp_run_id, PlannedOrder.status.in_(("CREATED", "FIRMED")))).scalar()
        if remaining == 0:
            workflow.end(session, instance, "F1-10", outcome="all planned orders converted; PRs ready for sourcing / PO")
