"""D8 manufacturing controls on the Axion tenant (July 2027): Kanban for C-parts, reorder-point planning, weekly MRP buckets.

The signature case (scheduling agreement SA-5520, the Trichy Forge / Kovai Diecast dual source) is not touched: this pack adds three new
C-part and consumable materials of its own, through the F9 material-master workflow, and plans only those materials:

  F9        washer M10 (Kanban), cable tie (reorder point) and gasket (weekly buckets) through the four data stewards
  Kanban    three cards of 5,000 washers each; two bins are emptied, each signal raises a replenishment requisition (origin MRP,
            reference the card number) that follows the normal approval route
  VB        cable tie: reorder point 400, maximum 2,000, nothing on hand -> the regenerative MRP run proposes an order up to the
            maximum, firmed and converted to a requisition by the MRP controller
  PW        gasket planned in weekly buckets: five demand elements over four weeks net to one planned order per week, needed on the
            Monday of the week (the first week is needed from the run date)

Self-billing (ERS) on scheduling agreements is covered by tests/pic/test_wave1_industry.py (a scheduling agreement of its own); the
signature case's SA-5520 deliveries keep their supplier invoices.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import DemandElement, KanbanCard, Material, PlannedOrder
from app.pic.platform import audit, clock
from app.pic.seed import axion
from app.pic.seed.axion import Scenario, at
from app.pic.seed.axion import SIGNATURE_KEY, SIGNATURE_VERSION  # noqa: E402
from app.pic.seed.datasets.purchase_types import material_via_f9, tenant_id_of

KEY = "axn-manufacturing-controls"
VERSION = "1"
TITLE = "D8 manufacturing controls: Kanban, reorder-point planning, weekly MRP buckets (AXN, July 2027)"
TENANTS = ('AXN',)
CREATES_TENANT = False
READY = True
REQUIRES = {SIGNATURE_KEY: SIGNATURE_VERSION}


def _july(day: int, hour: int = 10) -> datetime:
    return at(date(2027, 7, day), hour)


def apply(tenant_code: str, password: str) -> dict:
    from app.pic.services import ind_manufacturing, planning

    sc = Scenario(tenant_id_of(tenant_code), tenant_code, axion.DOMAIN)
    notes, counts = [], {}

    # ------------------------------------------------------------ F9 materials
    specs = [("washer", "Plain washer M10, zinc flake, DIN 125 (C-part, Kanban)", "VFS-W-M10-DIN125", 90),
             ("tie", "Cable tie 200 mm UV-stabilised black (C-part, reorder point)", "VFS-CT-200-UV", 120),
             ("gasket", "Flat gasket 80 x 60 x 2 mm NBR (weekly buckets)", "VFS-G-80X60-NBR", 1_850)]
    numbers = {}
    for index, (key, description, mpn, price) in enumerate(specs):
        numbers[key] = material_via_f9(sc, "buyer", _july(1, 9 + index), description=description, type="STOCK", material_group="FASTENERS",
                                       category="FASTENERS", base_uom="EA", hsn_code="73181500", mpn=mpn,
                                       attributes={"cClass": key != "gasket", "pack": "box of 100" if key != "gasket" else "each"})
    with sc.act("mrp.controller", _july(1, 14)) as s:
        for key, description, mpn, price in specs:
            material = s.execute(select(Material).where(Material.number == numbers[key])).scalar_one()
            before = {"mrpType": material.mrp_type, "standardPriceMinor": material.standard_price_minor}
            material.standard_price_minor, material.planned_delivery_days = price, 5
            audit.record(s, "MATERIAL", material.id, "MAINTAINED", object_ref=material.number, before=before,
                         after={"standardPriceMinor": price, "plannedDeliveryDays": 5}, reason="MRP controller: planning data for the C-part")
        ind_manufacturing.set_mrp_type(s, numbers["washer"], "KB")
        ind_manufacturing.set_mrp_type(s, numbers["tie"], "VB")
        ind_manufacturing.set_mrp_type(s, numbers["gasket"], "PW")
        ind_manufacturing.set_parameters(s, material=numbers["tie"], plant="P100", reorder_point=400, max_stock=2_000,
                                         note="Consumption about 250 a week; supplier lead time 5 days")
    notes.append(f"F9 {numbers['washer']} (Kanban), {numbers['tie']} (reorder point 400 / 2,000), {numbers['gasket']} (weekly buckets); MRP types KB, VB, PW")

    # ------------------------------------------------------------ Kanban: three cards, two empty bins
    with sc.act("mrp.controller", _july(5, 9)) as s:
        cards = [ind_manufacturing.create_card(s, material=numbers["washer"], plant="P100", bin_qty=5_000) for _ in range(3)]
        card_ids = [c.id for c in cards]
        card_numbers = [c.number for c in cards]
    requisitions = []
    for when, card_id in ((_july(8, 11), card_ids[0]), (_july(15, 11), card_ids[1])):
        with sc.act("mrp.controller", when) as s:
            card = ind_manufacturing.signal_empty(s, s.get(KanbanCard, card_id))
            requisitions.append(card.requisition_id)
        sc.approve_all(requisitions[-1], when.replace(hour=15), "Kanban replenishment of one bin")
    notes.append(f"Kanban cards {', '.join(card_numbers)}; bins 1 and 2 signalled empty -> {len(requisitions)} replenishment requisitions approved")

    # ------------------------------------------------------------ reorder point: regenerative run for the cable tie
    with sc.act("mrp.controller", _july(12, 9)) as s:
        run = planning.run(s, plant="P100", mode="REGENERATIVE", materials=[numbers["tie"]], run_date=date(2027, 7, 12))
        order = s.execute(select(PlannedOrder).where(PlannedOrder.mrp_run_id == run.id)).scalar_one()
        order_no, order_qty = order.number, int(order.qty)
        planning.firm(s, order)
        pr = planning.convert(s, order)
        tie_pr, tie_run = pr.number, run.number
        tie_pr_id = pr.id
    sc.approve_all(tie_pr_id, _july(12, 15), "Reorder-point replenishment of the cable tie")
    notes.append(f"Reorder point: {tie_run} proposed {order_no} for {order_qty} (up to the maximum 2,000) -> firmed -> {tie_pr}")

    # ------------------------------------------------------------ weekly buckets: gasket demand over four weeks
    demand = [(date(2027, 7, 14), 120), (date(2027, 7, 16), 80), (date(2027, 7, 21), 150), (date(2027, 7, 28), 90), (date(2027, 8, 4), 60)]
    with sc.act("mrp.controller", _july(13, 9)) as s:
        material = s.execute(select(Material).where(Material.number == numbers["gasket"])).scalar_one()
        for index, (day, qty) in enumerate(demand, start=1):
            s.add(DemandElement(tenant_id=sc.tenant_id, material_id=material.id, plant="P100", type="FORECAST", reference=f"GSK-FC-{index}", req_date=day,
                                qty=Decimal(qty), changed_at=_july(13, 9), created_by=s.info["principal"].user_id))
        audit.record(s, "MATERIAL", material.id, "DEMAND_LOADED", object_ref=material.number, after={"elements": len(demand)}, actor="migration")
    with sc.act("mrp.controller", _july(13, 11)) as s:
        run = planning.run(s, plant="P100", mode="REGENERATIVE", materials=[numbers["gasket"]], run_date=date(2027, 7, 13))
        orders = s.execute(select(PlannedOrder).where(PlannedOrder.mrp_run_id == run.id).order_by(PlannedOrder.need_date)).scalars().all()
        weekly = [(o.need_date.isoformat(), str(int(o.qty))) for o in orders]
        gasket_run = run.number
    notes.append(f"Weekly buckets: {gasket_run} nets 5 demand elements into {len(weekly)} planned orders needed " + ", ".join(f"{d} ({q})" for d, q in weekly))
    clock.set_pinned(None)
    counts.update({"materials": 3, "kanbanCards": 3, "kanbanRequisitions": len(requisitions), "reorderPointOrders": 1, "weeklyPlannedOrders": len(weekly)})
    return {"notes": notes, "counts": counts, "materials": numbers, "cards": card_numbers, "weekly": weekly, "reorderRun": tie_run}
