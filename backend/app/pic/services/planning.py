"""F1 MRP run → planned order → purchase requisition (M02, Technical Document §9.1)."""
import math
import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    Asn, AsnLine, DemandElement, DocumentLink, Material, MrpException, MrpRun, Plant, PlannedOrder, PlanningParameter, PoLine, PurchaseOrder, Stock,
)
from app.pic.platform import agents, audit, clock, outbox, workflow
from app.pic.platform.core import insert_rows, link, link_many, next_number, next_numbers
from app.pic.platform.errors import Problem, illegal_transition
from app.pic.services import source
from app.pic.services.common import principal

PROCESS = "pic.mrp-to-pr"
OPEN_PO_STATUSES = ("RELEASED", "TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED")

# MRP types (material.mrp_type, BP M02): PD plans in daily buckets (the default), PW weekly (Monday to Sunday), PM monthly
# (calendar month), VB reorder-point planning (order up to the maximum when stock plus receipts fall to the reorder point).
# ND (no planning) and KB (Kanban cards, services/ind_manufacturing.py) are not netted by the MRP run.
BUCKET_BY_TYPE = {"PD": "DAY", "PW": "WEEK", "PM": "MONTH"}
PLANNED_TYPES = ("PD", "PW", "PM", "VB")


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
def _assemble_supply(on_hand, po_rows, asn_rows, firmed: list) -> dict:
    """Receipts and totals from the open supply of one material and plant (rows as selected in ``_supply``)."""
    receipts: list[tuple[date, Decimal, str, str]] = []  # (date, qty, kind, ref)
    open_po = Decimal(0)
    for qty, shipped_qty, received_qty, need_date, line_no, po_number in po_rows:
        # Quantity not yet shipped (shipped quantities are counted as in-transit or received).
        remaining = max(qty - max(shipped_qty, received_qty), Decimal(0))
        if remaining > 0:
            receipts.append((need_date, remaining, "OPEN_PO", f"{po_number}/{line_no}"))
            open_po += remaining
    in_transit = Decimal(0)
    for qty, received_qty, expected_date, asn_number in asn_rows:
        remaining = qty - received_qty
        if remaining > 0:
            receipts.append((expected_date, remaining, "IN_TRANSIT", asn_number))
            in_transit += remaining
    firm_receipts = Decimal(0)
    for order in firmed:
        receipts.append((order.need_date, order.qty, "FIRM_PLANNED", order.number))
        firm_receipts += order.qty
    return {"on_hand": Decimal(on_hand), "open_po": open_po, "in_transit": in_transit, "firm_receipts": firm_receipts,
            "receipts": receipts, "firmed": firmed}


_PO_COLUMNS = (PoLine.qty, PoLine.shipped_qty, PoLine.received_qty, PoLine.need_date, PoLine.line_no, PurchaseOrder.number)
_ASN_COLUMNS = (AsnLine.qty, AsnLine.received_qty, Asn.expected_date, Asn.number)


# Stock that planning counts as supply on hand: own unrestricted stock plus supplier-owned consignment stock (available to withdraw;
# the liability arises only at withdrawal). Quality, blocked and subcontractor stock are not available. Product decision of 2 Nov 2026,
# a deliberate extension of TD 9.1 ("on_hand_unrestricted"): without it a consignment receipt is neither open order nor on-hand supply.
AVAILABLE_STOCK_TYPES = ("UNRESTRICTED", "CONSIGNMENT")


def _supply(session: Session, material: Material, plant: str) -> dict:
    on_hand = session.execute(select(func.coalesce(func.sum(Stock.qty), 0)).where(
        Stock.material_id == material.id, Stock.plant == plant, Stock.stock_type.in_(AVAILABLE_STOCK_TYPES))).scalar()
    po_rows = session.execute(select(*_PO_COLUMNS).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(
        PoLine.material_id == material.id, PoLine.plant == plant, PurchaseOrder.status.in_(OPEN_PO_STATUSES))).all()
    asn_rows = session.execute(select(*_ASN_COLUMNS).join(Asn, Asn.id == AsnLine.asn_id).join(PoLine, PoLine.id == AsnLine.po_line_id)
                               .where(PoLine.material_id == material.id, PoLine.plant == plant, Asn.status == "IN_TRANSIT")).all()
    firmed = session.execute(select(PlannedOrder).where(PlannedOrder.material_id == material.id, PlannedOrder.plant == plant,
                                                        PlannedOrder.status == "FIRMED")).scalars().all()
    return _assemble_supply(on_hand, po_rows, asn_rows, firmed)


def bucket_of(day: date, bucket: str) -> tuple[date, date]:
    """First and last day of the planning bucket holding ``day`` (DAY: the day itself)."""
    if bucket == "WEEK":
        start = day - timedelta(days=day.weekday())
        return start, start + timedelta(days=6)
    if bucket == "MONTH":
        start = day.replace(day=1)
        return start, (start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)) - timedelta(days=1)
    return day, day


def _calendar(session: Session, plant: str) -> tuple[list[int], list[date]]:
    row = session.execute(select(Plant).where(Plant.code == plant)).scalar_one()
    return list(row.working_days or [0, 1, 2, 3, 4, 5]), list(row.holidays or [])


class _Reads:
    """Demand, supply and calendar of one plant, one query per material (single-material callers)."""

    def __init__(self, session: Session, plant: str):
        self.session, self.plant = session, plant
        self._calendar = None
        self._releases: dict = {}

    def release_date(self, need_date: date, lead: int) -> date:
        """``lead`` working days before the need date on the plant calendar (memoised: the calendar is fixed for a run)."""
        key = (need_date, lead)
        found = self._releases.get(key)
        if found is None:
            working_days, holidays = self.calendar()
            found = self._releases[key] = clock.subtract_working_days(need_date, lead, working_days, holidays)
        return found

    def demand(self, material: Material) -> list:
        return self.session.execute(select(DemandElement.req_date, DemandElement.qty).where(
            DemandElement.material_id == material.id, DemandElement.plant == self.plant).order_by(DemandElement.req_date)).all()

    def supply(self, material: Material) -> dict:
        return _supply(self.session, material, self.plant)

    def calendar(self) -> tuple[list[int], list[date]]:
        if self._calendar is None:
            self._calendar = _calendar(self.session, self.plant)
        return self._calendar

    def parameters(self, material: Material) -> Optional[tuple[Decimal, Optional[Decimal]]]:
        """(reorder point, maximum stock) of a reorder-point material at this plant, None when not maintained."""
        row = self.session.execute(select(PlanningParameter.reorder_point, PlanningParameter.max_stock).where(
            PlanningParameter.material_id == material.id, PlanningParameter.plant == self.plant)).first()
        return None if row is None else (row[0], row[1])


class _BulkReads(_Reads):
    """The same reads for a whole run, loaded with one query per table (TD §15: 50,000 materials in < 10 minutes).

    ``material_ids`` limits the load to those materials; None loads the plant (callers pass None for large scopes, the
    rows of materials outside the run are simply never read). Row order per material is the database order of the
    per-material queries; netting only sums demand and receipts, firmed orders keep their database order.
    """

    def __init__(self, session: Session, plant: str, material_ids: Optional[list] = None):
        super().__init__(session, plant)
        self.scope = None if material_ids is None else set(material_ids)

        def scoped(query, column):
            if material_ids is None:
                yield from session.execute(query)
            else:
                for start in range(0, len(material_ids), source.IN_CHUNK):
                    yield from session.execute(query.where(column.in_(material_ids[start:start + source.IN_CHUNK])))

        self._demand = defaultdict(list)
        for material_id, req_date, qty in scoped(select(DemandElement.material_id, DemandElement.req_date, DemandElement.qty)
                                                 .where(DemandElement.plant == plant).order_by(DemandElement.req_date),
                                                 DemandElement.material_id):
            self._demand[material_id].append((req_date, qty))
        self._on_hand = {material_id: qty for material_id, qty in scoped(
            select(Stock.material_id, func.sum(Stock.qty)).where(Stock.plant == plant, Stock.stock_type.in_(AVAILABLE_STOCK_TYPES))
            .group_by(Stock.material_id), Stock.material_id)}
        self._po = defaultdict(list)
        for row in scoped(select(PoLine.material_id, *_PO_COLUMNS).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(
                PoLine.plant == plant, PurchaseOrder.status.in_(OPEN_PO_STATUSES)), PoLine.material_id):
            self._po[row[0]].append(tuple(row[1:]))
        self._asn = defaultdict(list)
        for row in scoped(select(PoLine.material_id, *_ASN_COLUMNS).join(Asn, Asn.id == AsnLine.asn_id)
                          .join(PoLine, PoLine.id == AsnLine.po_line_id).where(PoLine.plant == plant, Asn.status == "IN_TRANSIT"),
                          PoLine.material_id):
            self._asn[row[0]].append(tuple(row[1:]))
        self._firmed = defaultdict(list)
        for (order,) in scoped(select(PlannedOrder).where(PlannedOrder.plant == plant, PlannedOrder.status == "FIRMED"),
                               PlannedOrder.material_id):
            self._firmed[order.material_id].append(order)
        self._parameters = {material_id: (reorder_point, max_stock) for material_id, reorder_point, max_stock in scoped(
            select(PlanningParameter.material_id, PlanningParameter.reorder_point, PlanningParameter.max_stock)
            .where(PlanningParameter.plant == plant), PlanningParameter.material_id)}

    def _covers(self, material: Material) -> bool:
        return self.scope is None or material.id in self.scope

    def demand(self, material: Material) -> list:
        return self._demand.get(material.id, []) if self._covers(material) else super().demand(material)

    def parameters(self, material: Material) -> Optional[tuple[Decimal, Optional[Decimal]]]:
        return self._parameters.get(material.id) if self._covers(material) else super().parameters(material)

    def supply(self, material: Material) -> dict:
        if not self._covers(material):
            return super().supply(material)
        return _assemble_supply(self._on_hand.get(material.id, 0), self._po.get(material.id, ()), self._asn.get(material.id, ()),
                                self._firmed.get(material.id, []))


def _needed_on(on_hand: Decimal, gross_by_day: dict, receipt_by_day: dict, order: PlannedOrder, safety: Decimal,
               order_day: Optional[date] = None) -> Optional[date]:
    """First day (bucket) projected stock falls below safety stock when the firmed order's own receipt is left out (None: never)."""
    projected = on_hand
    order_day = order.need_date if order_day is None else order_day
    for day in sorted(set(gross_by_day) | set(receipt_by_day)):
        projected += receipt_by_day.get(day, Decimal(0)) - (order.qty if day == order_day else Decimal(0))
        projected -= gross_by_day.get(day, Decimal(0))
        if projected < safety:
            return day
    return None


def net_material(session: Session, material: Material, plant: str, run_date: date, reads: Optional[_Reads] = None) -> dict:
    """Bucket-by-bucket netting. Returns the planned receipts needed and exceptions, without writing."""
    reads = reads or _Reads(session, plant)
    demand = reads.demand(material)
    supply = reads.supply(material)
    if material.mrp_type == "VB":
        return _net_reorder_point(material, plant, run_date, reads, demand, supply)
    # Weekly / monthly MRP types net per bucket: demand and receipts of a bucket fall on its first day (daily: unchanged).
    bucket = BUCKET_BY_TYPE.get(material.mrp_type, "DAY")
    key = (lambda d: d) if bucket == "DAY" else (lambda d: bucket_of(d, bucket)[0])
    gross_by_day: dict[date, Decimal] = defaultdict(Decimal)
    for req_date, qty in demand:
        gross_by_day[key(req_date)] += qty
    receipt_by_day: dict[date, Decimal] = defaultdict(Decimal)
    for day, qty, _, _ in supply["receipts"]:
        receipt_by_day[key(day)] += qty
    reads.calendar()  # the plant must exist (scalar_one), as before
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
            if bucket != "DAY":  # the current bucket is needed from today, not from a Monday / 1st that has passed
                start, end = bucket_of(day, bucket)
                day = run_date if start < run_date <= end else start
            release = reads.release_date(day, lead)
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
            continue
        # Without this firmed receipt, when would projected stock first drop below safety stock?
        needed_on = _needed_on(supply["on_hand"], gross_by_day, receipt_by_day, order, safety, key(order.need_date))
        if needed_on is None:
            exceptions.append({"code": "CANCEL", "message": f"{order.number} ({order.qty} for {order.need_date}) is not needed: "
                               "demand is covered without it", "action": f"Cancel {order.number} or keep it as buffer",
                               "planned_order": order.number})
        elif needed_on > key(order.need_date):
            exceptions.append({"code": "RESCHEDULE_OUT", "message": f"{order.number} not needed until {needed_on} (firmed for {order.need_date})",
                               "action": f"Reschedule {order.number} out", "planned_order": order.number})
    gross_total = sum(gross_by_day.values(), Decimal(0))
    return {
        "material": material.number, "plant": plant, "gross": gross_total, "on_hand": supply["on_hand"],
        "open_po": supply["open_po"], "in_transit": supply["in_transit"], "firm_receipts": supply["firm_receipts"],
        "safety_stock": safety,
        "net": max(Decimal(0), gross_total - (supply["on_hand"] + supply["open_po"] + supply["in_transit"] + supply["firm_receipts"]) + safety),
        "proposals": proposals, "exceptions": exceptions,
    }


def _add_working_days(start: date, days: int, working_days, holidays) -> date:
    current, remaining = start, days
    while remaining > 0:
        current += timedelta(days=1)
        if clock.is_working_day(current, working_days, holidays):
            remaining -= 1
    return current


def _net_reorder_point(material: Material, plant: str, run_date: date, reads: _Reads, demand: list, supply: dict) -> dict:
    """Reorder-point planning (MRP type VB, BP M02-C1): when stock plus open receipts, less the requirements that fall due before
    a new order could arrive, is at or below the reorder point, order up to the maximum stock (reorder point plus safety stock when
    no maximum is maintained). No forecast netting: C-parts are replenished from consumption, not from a demand plan."""
    safety = material.safety_stock or Decimal(0)
    lead = material.planned_delivery_days + material.gr_processing_days
    working_days, holidays = reads.calendar()
    arrival = _add_working_days(run_date, lead, working_days, holidays)
    gross_total = sum((qty for _, qty in demand), Decimal(0))
    due = sum((qty for req_date, qty in demand if req_date <= arrival), Decimal(0))
    available = supply["on_hand"] + supply["open_po"] + supply["in_transit"] + supply["firm_receipts"]
    projected = available - due
    parameters = reads.parameters(material)
    proposals, exceptions = [], []
    if supply["on_hand"] < safety:
        exceptions.append({"code": "BELOW_SAFETY", "message": f"On-hand {supply['on_hand']} is below safety stock {safety}",
                           "action": "Expedite open supply or firm a planned order"})
    net = Decimal(0)
    if parameters is None:
        exceptions.append({"code": "NO_REORDER_PARAMS", "message": f"{material.number} is planned by reorder point but has no reorder point at plant {plant}",
                           "action": "Maintain the reorder point and maximum stock (planning parameters)"})
    elif projected <= parameters[0]:
        target = parameters[1] if parameters[1] is not None else parameters[0] + safety
        net = max(target - projected, Decimal(0))
        qty = lot_size(material, net, projected=projected)
        proposals.append({"need_date": arrival, "release_date": run_date, "qty": qty, "net": net})
    return {"material": material.number, "plant": plant, "gross": gross_total, "on_hand": supply["on_hand"], "open_po": supply["open_po"],
            "in_transit": supply["in_transit"], "firm_receipts": supply["firm_receipts"], "safety_stock": safety, "net": net,
            "proposals": proposals, "exceptions": exceptions}


# ---------------------------------------------------------------- run
BULK_SCOPE_LIMIT = 2000  # up to this many materials the run loads by material id, beyond it the whole plant
WRITE_BATCH = 2000  # planned orders per replacement UPDATE
LINK_ALL_LIMIT = 5000  # a run of up to this many planned orders writes one planned_by link row per order; a larger run writes the
#                        link when the order is firmed or converted (planned_order.mrp_run_id already ties every order to its run)


def _batches(rows: list) -> list:
    return [rows[start:start + WRITE_BATCH] for start in range(0, len(rows), WRITE_BATCH)]


def _replace_unfirmed(session: Session, plant: str, material_ids: set) -> None:
    """Unfirmed planned orders from earlier runs are replaced by this run (status DELETED, version bumped as the ORM does)."""
    ids = [order_id for order_id, material_id in session.execute(select(PlannedOrder.id, PlannedOrder.material_id).where(
        PlannedOrder.plant == plant, PlannedOrder.status == "CREATED")) if material_id in material_ids]
    now = clock.now()
    for part in _batches(ids):
        session.execute(update(PlannedOrder).where(PlannedOrder.id.in_(part))
                        .values(status="DELETED", row_version=PlannedOrder.row_version + 1, updated_at=now)
                        .execution_options(synchronize_session="fetch"))


def run(session: Session, *, plant: str, mode: str = "NET_CHANGE", materials: Optional[list[str]] = None,
        run_date: Optional[date] = None) -> MrpRun:
    p = principal(session)
    mode = mode.upper()
    if mode not in ("NET_CHANGE", "REGENERATIVE", "SIMULATION"):
        raise Problem(422, "INVALID_MODE", "mode must be NET_CHANGE, REGENERATIVE or SIMULATION")
    run_date = run_date or clock.today()
    tenant_id = current_tenant(session)
    mrp_run = MrpRun(tenant_id=tenant_id, number=next_number(session, "MRP_RUN"), mode=mode, plant=plant,
                     scope={"materials": materials} if materials else {}, run_date=run_date, status="RUNNING",
                     started_by=p.user_id, created_by=p.user_id)
    session.add(mrp_run)
    session.flush()
    instance = workflow.start(session, PROCESS, "MRP_RUN", mrp_run.id, mrp_run.number, {"mode": mode})
    workflow.step(session, instance, "F1-02", outcome=f"plant {plant}, {mode.lower().replace('_', '-')}")

    query = select(Material).where(Material.mrp_type.in_(PLANNED_TYPES), Material.status == "ACTIVE")
    if materials:
        query = query.where(Material.number.in_(materials))
    candidates = session.execute(query).scalars().all()
    if mode == "NET_CHANGE":
        last = session.execute(select(func.max(MrpRun.created_at)).where(MrpRun.plant == plant, MrpRun.id != mrp_run.id,
                                                                         MrpRun.mode.not_in(("SIMULATION", "ERP_IMPORT")))).scalar()
        if last is not None:
            changed = {row for row in session.execute(select(DemandElement.material_id).where(
                DemandElement.plant == plant, DemandElement.changed_at > last)).scalars()}
            candidates = [m for m in candidates if m.id in changed]
    workflow.step(session, instance, "F1-03", outcome=f"{len(candidates)} material(s) in scope")

    # Every read of the run is bulk-loaded once (demand, stock, open supply, firmed orders, sources of supply).
    scope = [m.id for m in candidates] if len(candidates) <= BULK_SCOPE_LIMIT else None
    reads = _BulkReads(session, plant, scope) if candidates else None
    lookup = source.Preloaded(session, plant, scope) if candidates and mode != "SIMULATION" else None

    results, orders, exceptions = [], [], []
    for material in candidates:
        result = net_material(session, material, plant, run_date, reads)
        results.append({k: (str(v) if isinstance(v, Decimal) else v) for k, v in result.items()
                        if k not in ("proposals", "exceptions")}
                       | {"proposals": [{k: str(v) for k, v in pr.items()} for pr in result["proposals"]],
                          "exceptions": result["exceptions"]})
        if mode == "SIMULATION":
            continue
        past_due = [e["code"] for e in result["exceptions"] if e["code"] == "PAST_DUE"]
        for proposal in result["proposals"]:
            determination = source.determine(session, material, plant, proposal["need_date"], proposal["qty"], lookup=lookup)
            orders.append({"id": uuid.uuid7(), "tenant_id": tenant_id, "mrp_run_id": mrp_run.id, "material_id": material.id,
                           "plant": plant, "storage_location": "0001", "qty": proposal["qty"], "need_date": proposal["need_date"],
                           "release_date": proposal["release_date"], "status": "CREATED", "source": determination.as_dict(),
                           "exception_codes": list(past_due), "created_by": p.user_id})
        value = int(Decimal(material.standard_price_minor or 0) * result["net"])
        for exc in result["exceptions"]:
            exceptions.append({"id": uuid.uuid7(), "tenant_id": tenant_id, "mrp_run_id": mrp_run.id, "material_id": material.id,
                               "code": exc["code"], "message": exc["message"], "value_at_risk_minor": value,
                               "recommended_action": exc["action"], "status": "OPEN", "created_by": p.user_id})

    if mode != "SIMULATION" and candidates:
        # Writes in bulk: one UPDATE per batch of replaced orders, one number-range update, array INSERTs.
        session.flush()
        _replace_unfirmed(session, plant, {m.id for m in candidates})
        for order, number in zip(orders, next_numbers(session, "PLANNED_ORDER", len(orders))):
            order["number"] = number
        insert_rows(session, PlannedOrder.__table__, orders)
        if len(orders) <= LINK_ALL_LIMIT:
            link_many(session, "MRP_RUN", mrp_run.id, mrp_run.number, [("PLANNED_ORDER", o["id"], o["number"]) for o in orders],
                      "planned_by")
        else:
            mrp_run.scope = {**(mrp_run.scope or {}), "lazyLinks": True}
        insert_rows(session, MrpException.__table__, exceptions)
    created, exception_count = len(orders), len(exceptions)

    if len(results) <= 20:
        step_outcome = "; ".join(
            f"{r['material']}: {r['gross']} − ({r['on_hand']} + {r['open_po']} + {r['in_transit']} + {r['firm_receipts']}) + {r['safety_stock']} = {r['net']}"
            for r in results) or "nothing to plan"
    else:
        sample = f"{results[0]['material']}..{results[-1]['material']}" if results else "none"
        total_net = sum((Decimal(r["net"]) for r in results), Decimal(0))
        step_outcome = f"{len(results):,} materials planned ({created:,} planned orders, {exception_count:,} exceptions, net: {total_net:,.3f} EA; sample: {sample})"
    workflow.step(session, instance, "F1-04", outcome=step_outcome)
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
        if exception_count and agents.permit(session, "MRP_EXCEPTION", object_type="MRP_RUN", object_id=mrp_run.id,
                                             object_ref=mrp_run.number, required_level="L2"):
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


def _ensure_run_link(session: Session, order: PlannedOrder) -> None:
    """Large runs do not write a planned_by link per order (50,000 materials: ~100 s of inserts); the link is written the first
    time the order is firmed or converted, so the lineage of every order that reaches a requisition is complete."""
    run = session.get(MrpRun, order.mrp_run_id)
    if run is None or not (run.scope or {}).get("lazyLinks"):
        return
    if session.execute(select(DocumentLink.id).where(
            DocumentLink.from_type == "MRP_RUN", DocumentLink.from_id == run.id, DocumentLink.to_type == "PLANNED_ORDER",
            DocumentLink.to_id == order.id, DocumentLink.link_type == "planned_by").limit(1)).first() is None:
        link(session, "MRP_RUN", run.id, run.number, "PLANNED_ORDER", order.id, order.number, "planned_by")


def firm(session: Session, order: PlannedOrder) -> PlannedOrder:
    if order.status != "CREATED":
        raise illegal_transition("Planned order", order.number, order.status, "firm")
    order.status = "FIRMED"
    _ensure_run_link(session, order)
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
    _ensure_run_link(session, order)
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


# ---------------------------------------------------------------- stock/requirements list (MRP-02)
def requirements_profile(session: Session, material: Material, plant: str, run_date: Optional[date] = None, horizon_days: int = 90) -> dict:
    """The stock/requirements list of one material and plant: the elements MRP nets (on-hand unrestricted stock, open purchase orders, ASNs in
    transit, firmed planned orders, demand incl. reservations) and the projected balance per planning bucket, from the same reads and bucket
    rules as ``net_material``. Nothing is written."""
    run_date = run_date or clock.today()
    reads = _Reads(session, plant)
    supply = reads.supply(material)
    bucket = BUCKET_BY_TYPE.get(material.mrp_type, "DAY")
    key = (lambda d: d) if bucket == "DAY" else (lambda d: bucket_of(d, bucket)[0])
    demand = session.execute(select(DemandElement.req_date, DemandElement.qty, DemandElement.type, DemandElement.reference).where(
        DemandElement.material_id == material.id, DemandElement.plant == plant, DemandElement.qty > 0).order_by(DemandElement.req_date)).all()
    safety = material.safety_stock or Decimal(0)
    gross: dict[date, Decimal] = defaultdict(Decimal)
    receipts: dict[date, Decimal] = defaultdict(Decimal)
    for req_date, qty, _, _ in demand:
        gross[key(max(req_date, run_date))] += qty   # overdue requirements fall due in the current bucket
    for day, qty, _, _ in supply["receipts"]:
        receipts[key(max(day, run_date))] += qty
    projected = supply["on_hand"]
    horizon = run_date + timedelta(days=horizon_days)
    buckets = []
    for day in sorted(set(gross) | set(receipts)):
        opening = projected
        projected = projected + receipts.get(day, Decimal(0)) - gross.get(day, Decimal(0))
        buckets.append({"from": day, "to": bucket_of(day, bucket)[1], "receipts": receipts.get(day, Decimal(0)), "requirements": gross.get(day, Decimal(0)),
                        "opening": opening, "projected": projected, "belowSafety": projected < safety, "shortage": projected < 0})
    return {"material": material.number, "plant": plant, "mrpType": material.mrp_type, "bucket": bucket, "asOf": run_date, "horizonTo": horizon,
            "onHand": supply["on_hand"], "openPo": supply["open_po"], "inTransit": supply["in_transit"], "firmPlannedReceipts": supply["firm_receipts"],
            "demand": sum((qty for _, qty, _, _ in demand), Decimal(0)), "safetyStock": safety,
            "available": supply["on_hand"] + supply["open_po"] + supply["in_transit"] + supply["firm_receipts"],
            "receipts": [{"date": d, "qty": q, "kind": k, "ref": r} for d, q, k, r in sorted(supply["receipts"], key=lambda x: x[0])],
            "requirements": [{"date": d, "qty": q, "type": t, "reference": r} for d, q, t, r in demand],
            "buckets": [b for b in buckets if b["from"] <= horizon], "parameters": reads.parameters(material)}
