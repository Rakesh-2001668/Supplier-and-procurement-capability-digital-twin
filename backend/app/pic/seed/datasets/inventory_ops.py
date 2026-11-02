"""D13 Inventory operations for the demo tenants AXN and KAC: ILLUSTRATIVE SAMPLE (fictional quantities; the documents are real PIC documents).

For each tenant the pack leaves the inventory module in the state a plant would be in a week after go-live, using the real services (stock
ledger, governed stock postings, physical inventory, reservations) with the business clock pinned, so every document has its audit trail,
events, ERP material document and approval history:

  opening stock      balances posted through the ledger (movement 561). AXN gets six stores materials of its own (it has little stock);
                     KAC, loaded from SAP without stock, gets twenty of its materials at plant 1100, one of them in two batches
  transfer           a stock posting moving a part of one material to the second storage location: below the auto-post limit, so it posts at once
  blocked batch      a batch blocked for a quality doubt (auto-posted: below the limit)
  scrap              a scrap awaiting the inventory controller's approval (a scrap always needs one; the maker cannot approve it)
  physical inventory one count POSTED with a small loss inside the tolerance (counted by the stores clerk, approved by a controller who
                     did not count, posted as movement 702), and one still COUNTING (two lines counted, one waiting for its recount)
  reservations       three: open, partially issued (201), cancelled; their open quantity is RESERVATION demand for MRP

Idempotent: a tenant that already has a stock posting, physical inventory or reservation is left alone. To use a client's own stock, load it
with the ERP stock sync (POST /v1/erp/sync) or an opening-balance load and do not apply this pack.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import (
    CostObject, Material, PhysicalInventory, Plant, Stock, StockPosting, StockReservation, StorageLocation, Tenant,
)
from app.pic.platform import audit, clock
from app.pic.seed.axion import Scenario, at
from app.pic.seed.datasets import _tenant_kit as kit

KEY = "inventory-ops"
VERSION = "1"
TITLE = "D13 Inventory operations for AXN and KAC: opening stock, transfer, blocked batch, scrap, counts and reservations (ILLUSTRATIVE SAMPLE)"
TENANTS = ("AXN", "KAC")
CREATES_TENANT = False
READY = True

CONTROLLERS = [("inventory.controller", "Inventory controller", ["INVENTORY_CONTROLLER"]), ("inventory.controller2", "Inventory controller (second)", ["INVENTORY_CONTROLLER"])]
ROLE_USER = {"INVENTORY_CONTROLLER": ["inventory.controller", "inventory.controller2"]}

AXN_MATERIALS = [
    # number, description, material group, standard price (paise), opening quantity, batch-managed batches {batch: qty}
    ("AXN-INV-101", "Hex bolt M10 x 40 zinc flake", "FASTENERS", 850, 4000, None),
    ("AXN-INV-102", "Deep-groove ball bearing 6204-2RS", "MRO", 18_500, 600, None),
    ("AXN-INV-103", "Hydraulic oil ISO VG 46, 20 litre can", "MRO-LUBRICANTS", 345_000, 80, {"HYD-2705": 50, "HYD-2706": 30}),
    ("AXN-INV-104", "Structural adhesive cartridge 310 ml", "MRO-CHEMICALS", 62_000, 150, {"ADH-2704": 150}),
    ("AXN-INV-105", "Packaging foam insert for die-cast housing", "PACKAGING", 4_200, 2500, None),
    ("AXN-INV-106", "Cut-off wheel 125 mm", "TOOLING", 3_800, 900, None),
    ("AXN-INV-107", "Weld nut M8 flange", "FASTENERS", 620, 3000, None),
    ("AXN-INV-108", "Safety gloves, nitrile coated (pair)", "OFFICE-SAFETY", 5_500, 400, None),
    ("AXN-INV-109", "Coolant concentrate, 200 litre drum", "MRO-LUBRICANTS", 1_850_000, 24, None),
    ("AXN-INV-110", "Lithium grease cartridge 400 g", "MRO-LUBRICANTS", 21_000, 300, None),
    ("AXN-INV-111", "Thermal label roll 100 x 150 mm", "PACKAGING", 14_500, 500, None),
    ("AXN-INV-112", "Cable tie 200 mm, pack of 100", "MRO", 9_800, 700, None),
    ("AXN-INV-113", "Deburring brush, steel wire", "TOOLING", 17_500, 150, None),
]
SPECS = {
    "AXN": {"domain": "axion.example", "plant": "P100", "base": date(2027, 8, 9), "receiver": "receiver", "cost_object": "COST_CENTER:4100",
            "attributes": {"plants": ["P100", "P200"]}},
    "KAC": {"domain": "kaveri-auto.example", "plant": "1100", "base": date(2026, 11, 9), "receiver": "receiver.hosur", "cost_object": "COST_CENTER:1120",
            "attributes": {"plants": ["1100", "1200", "1300"]}},
}


def _units_under(price_minor: int, limit_minor: int, most: int) -> Decimal:
    """A quantity worth less than ``limit_minor`` (so the posting stays under the auto-post limit), at most ``most``."""
    return Decimal(max(1, min(most, (limit_minor - 1) // max(price_minor, 1))))


def _ensure_location(tenant_id, plant: str) -> None:
    with tenant_tx(tenant_id) as s:
        if s.execute(select(StorageLocation.id).where(StorageLocation.plant == plant, StorageLocation.code == "0002")).first() is None:
            s.add(StorageLocation(tenant_id=tenant_id, plant=plant, code="0002", name="Finished goods & quarantine"))


def _axion_materials(sc: Scenario, plant: str, when) -> list[tuple]:
    """AXN's own stores materials (direct master load, as the signature case loads its masters): [(number, price, qty, batches)]."""
    clock.set_pinned(when)
    out = []
    with tenant_tx(sc.tenant_id) as s:
        have = {m.number: m for m in s.execute(select(Material)).scalars()}
        for number, description, group, price, qty, batches in AXN_MATERIALS:
            if number not in have:
                s.add(Material(tenant_id=sc.tenant_id, number=number, description=description, type="STOCK", material_group=group, category=group,
                               base_uom="EA", valuation_class="3100", hsn_code="73181500", gst_rate=Decimal(18), mrp_type="ND", standard_price_minor=price,
                               attributes={"batchManaged": bool(batches), "source": "inventory-ops"}, status="ACTIVE", erp_synced=True))
            out.append((number, price, Decimal(qty), batches))
        audit.record(s, "MIGRATION", uuid.uuid5(uuid.NAMESPACE_URL, "axn-inventory-masters"), "INITIAL_LOAD", object_ref="inventory materials",
                     after={"materials": [m[0] for m in AXN_MATERIALS]}, actor="migration")
    return out


def _kac_materials(sc: Scenario, plant: str) -> list[tuple]:
    """Twenty of KAC's stock materials planned at the plant (loaded from SAP), ordered by number: [(number, price, qty, batches)]."""
    out = []
    with tenant_tx(sc.tenant_id) as s:
        rows = [m for m in s.execute(select(Material).where(Material.type == "STOCK", Material.status == "ACTIVE", Material.standard_price_minor.is_not(None))
                                     .order_by(Material.number)).scalars() if plant in ((m.attributes or {}).get("plants") or [])]
        for index, m in enumerate(rows[:20]):
            qty = Decimal(120 + 35 * index)
            out.append((m.number, int(m.standard_price_minor), qty, {"B-2609": qty // 2, "B-2610": qty - qty // 2} if index == 0 else None))
    return out


def _opening(sc: Scenario, plant: str, materials: list[tuple], when) -> int:
    """Opening balances through the ledger primitive (movement 561, reference OPENING_BALANCE), as the tenant administrator."""
    from app.pic.services import stock_ledger

    posted = 0
    with sc.act("admin", when) as s:
        ids = {m.number: m.id for m in s.execute(select(Material).where(Material.number.in_([m[0] for m in materials]))).scalars()}
        load_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{sc.tenant_code}-inventory-opening")
        for number, price, qty, batches in materials:
            for batch, part in (batches or {"": qty}).items():
                stock_ledger.post_movement(s, material_id=ids[number], plant=plant, sloc="0001", stock_type="UNRESTRICTED", batch=batch, qty=Decimal(part),
                                           movement="561", ref_type="OPENING_BALANCE", ref_id=load_id, ref=f"OPEN-{sc.tenant_code}-{number}"[:60],
                                           posting_ref=f"OPEN-{sc.tenant_code}", reason_code="OPENING")
                posted += 1
        audit.record(s, "MIGRATION", load_id, "INITIAL_LOAD", object_ref=f"{sc.tenant_code} opening stock", after={"balances": posted, "plant": plant,
                                                                                                                     "materials": len(materials)}, actor="migration")
    return posted


def apply(tenant_code: str, password: str) -> dict:
    from app.pic.services import inventory

    spec = SPECS.get(tenant_code)
    if spec is None:
        raise ValueError(f"{KEY} loads tenants {', '.join(SPECS)} only")
    plant, base, receiver = spec["plant"], spec["base"], spec["receiver"]
    tenant_id = _tenant_ids(tenant_code)[0]
    with tenant_tx(tenant_id) as s:
        if s.execute(select(Plant.id).where(Plant.code == plant)).first() is None:
            return {"notes": [f"Skipped: plant {plant} does not exist in tenant {tenant_code}"], "counts": {}}
        if (s.execute(select(StockPosting.id).limit(1)).first() or s.execute(select(PhysicalInventory.id).limit(1)).first()
                or s.execute(select(StockReservation.id).limit(1)).first()):
            return {"notes": [f"Skipped: tenant {tenant_code} already has inventory documents"], "counts": {}}
    sc = Scenario(tenant_id, tenant_code=tenant_code, domain=spec["domain"], role_user=ROLE_USER)
    kit.create_users(sc, [(local, name, roles, spec["attributes"]) for local, name, roles in CONTROLLERS], password)
    _ensure_location(tenant_id, plant)
    day = lambda n, hour=10: at(base + timedelta(days=n), hour)  # noqa: E731
    notes, counts = [], {}

    # ------------------------------------------------------------ opening stock
    if tenant_code == "AXN":
        materials = _axion_materials(sc, plant, day(0, 8))
    else:
        materials = _kac_materials(sc, plant)
    with tenant_tx(tenant_id) as s:
        has_stock = s.execute(select(Stock.id).where(Stock.plant == plant, Stock.qty > 0).limit(1)).first() is not None
    if not materials:
        return {"notes": [f"Skipped: tenant {tenant_code} has no stock materials at plant {plant}"], "counts": {}}
    balances = _opening(sc, plant, materials, day(0, 9))
    notes.append(f"Opening stock: {balances} balance(s) of {len(materials)} material(s) at {plant}/0001 posted through the ledger (561)"
                 + ("" if not has_stock else "; the plant already had other stock, which is left as it was"))
    counts.update({"materials": len(materials), "openingBalances": balances})

    plain = [m for m in materials if not m[3]]
    batch_material = next((m for m in materials if m[3]), materials[0])
    batch_name = sorted(batch_material[3])[0] if batch_material[3] else ""
    if len(plain) < 11:
        return {"notes": [f"Skipped after the opening stock: tenant {tenant_code} needs eleven stock materials without batches at {plant}"], "counts": counts}

    # ------------------------------------------------------------ a transfer to the second storage location (auto-posts)
    with sc.act(receiver, day(1, 10)) as s:
        qty = _units_under(plain[1][1], 2_000_000, 60)
        transfer = inventory.create_posting(s, posting_type="TRANSFER", plant=plant, submit=True,
                                            lines=[{"material": plain[1][0], "qty": qty, "storage_location": "0001", "to_storage_location": "0002"}])
        transfer_no, transfer_status = transfer.number, transfer.status
    notes.append(f"Transfer {transfer_no}: {qty} x {plain[1][0]} to storage location 0002, {transfer_status} at once (below the auto-post limit)")

    # ------------------------------------------------------------ a batch blocked for a quality doubt (auto-posts)
    with sc.act(receiver, day(2, 11)) as s:
        qty = _units_under(batch_material[1], 2_000_000, 12)
        block = inventory.create_posting(s, posting_type="BLOCK", plant=plant, reason_code="QUALITY_DOUBT", submit=True,
                                         reason=f"Supplier advised a possible out-of-spec lot; {batch_name or 'stock'} held until the certificate arrives",
                                         lines=[{"material": batch_material[0], "qty": qty, "batch": batch_name, "storage_location": "0001"}])
        block_no, block_status = block.number, block.status
    notes.append(f"Block {block_no}: {qty} x {batch_material[0]}" + (f" batch {batch_name}" if batch_name else "") + f" blocked, {block_status}")

    # ------------------------------------------------------------ a scrap awaiting approval
    with sc.act(receiver, day(3, 14)) as s:
        scrap = inventory.create_posting(s, posting_type="SCRAP", plant=plant, reason_code="DAMAGED", submit=True,
                                         reason="Crushed cartons found in the aisle after a forklift incident, photographed for the insurer",
                                         lines=[{"material": plain[2][0], "qty": _units_under(plain[2][1], 1_000_000, 8), "storage_location": "0001"}])
        scrap_no, scrap_status = scrap.number, scrap.status
    notes.append(f"Scrap {scrap_no} of {plain[2][0]} waits for the inventory controller ({scrap_status}); its maker cannot approve it (SOD-10)")

    # ------------------------------------------------------------ a physical inventory posted with a loss
    with sc.act("inventory.controller", day(4, 9)) as s:
        count = inventory.create_count(s, plant=plant, storage_location="0001", materials=[plain[3][0], plain[4][0]],
                                       description="Weekly cycle count of fast movers")
        count_id, count_no = count.id, count.number
        book = {l.material_id: l.book_qty for l in inventory.count_lines(s, count)}
    with sc.act(receiver, day(4, 14)) as s:
        count = s.get(PhysicalInventory, count_id)
        entries, short_done = [], False
        for line in inventory.count_lines(s, count):
            m = s.get(Material, line.material_id)
            short = Decimal(0)
            if not short_done and line.book_qty >= 100 and (m.standard_price_minor or 0) <= 400_000:
                short, short_done = Decimal(1), True      # one piece short on the first line, inside the count tolerance
            entries.append({"material": m.number, "batch": line.batch, "qty": line.book_qty - short})
        inventory.enter_counts(s, count, entries)
        assert count.status == "COUNTED", count.status
        inventory.submit_count(s, count)
    sc.approve_all(count_id, day(5, 10), "Difference explained: breakage at the line side")
    with sc.act("inventory.controller", day(5, 11)) as s:
        count = inventory.post_count(s, s.get(PhysicalInventory, count_id))
        loss = count.loss_minor
    notes.append(f"Physical inventory {count_no}: {len(entries)} lines counted, loss {loss / 100:,.2f} posted (702) after approval by a controller who did not count")

    # ------------------------------------------------------------ a physical inventory still being counted
    with sc.act("inventory.controller", day(6, 9)) as s:
        counting = inventory.create_count(s, plant=plant, storage_location="0001", materials=[plain[5][0], plain[6][0], plain[7][0]],
                                          description="Quarterly count, aisle 4")
        counting_id, counting_no = counting.id, counting.number
    with sc.act(receiver, day(6, 13)) as s:
        counting = s.get(PhysicalInventory, counting_id)
        lines = inventory.count_lines(s, counting)
        inventory.enter_counts(s, counting, [{"material": s.get(Material, lines[0].material_id).number, "batch": lines[0].batch, "qty": lines[0].book_qty},
                                             {"material": s.get(Material, lines[1].material_id).number, "batch": lines[1].batch,
                                              "qty": (lines[1].book_qty * Decimal("0.8")).quantize(Decimal("1"))}])   # a fifth short: recount required
        counting_status = counting.status
    notes.append(f"Physical inventory {counting_no} is {counting_status}: two of three lines counted, one needs a recount by another person")

    # ------------------------------------------------------------ reservations: open, partially issued, cancelled
    need = base + timedelta(days=21)
    with sc.act(receiver, day(7, 9)) as s:
        open_res = inventory.create_reservation(s, material=plain[8][0], plant=plant, storage_location="0001", qty=_units_under(plain[8][1], 5_000_000, 40),
                                                need_date=need, cost_object=spec["cost_object"], purpose="Maintenance shutdown kit")
        partial_qty = max(Decimal(10), plain[9][2] // 4)
        partial = inventory.create_reservation(s, material=plain[9][0], plant=plant, storage_location="0001", qty=partial_qty, need_date=need,
                                               cost_object=spec["cost_object"], purpose="Line 2 changeover")
        cancelled = inventory.create_reservation(s, material=plain[10][0], plant=plant, storage_location="0001", qty=max(Decimal(2), plain[10][2] // 10),
                                                 need_date=need, cost_object=spec["cost_object"], purpose="Trial run")
        numbers = (open_res.number, partial.number, cancelled.number)
        partial_id, cancelled_id = partial.id, cancelled.id
    with sc.act(receiver, day(8, 10)) as s:
        inventory.issue_reservation(s, s.get(StockReservation, partial_id), qty=(partial_qty * 2 // 5).quantize(Decimal(1)))
    with sc.act(receiver, day(8, 15)) as s:
        inventory.cancel_reservation(s, s.get(StockReservation, cancelled_id), "Trial run postponed to next quarter")
    notes.append(f"Reservations {numbers[0]} (open), {numbers[1]} (2/5 issued) and {numbers[2]} (cancelled) for cost object {spec['cost_object']}")
    clock.set_pinned(None)
    counts.update({"stockPostings": 3, "physicalInventories": 2, "reservations": 3})
    return {"notes": notes, "counts": counts, "documents": {"transfer": transfer_no, "block": block_no, "scrap": scrap_no, "countPosted": count_no,
                                                              "countOpen": counting_no, "reservations": list(numbers)}}


def _tenant_ids(code: str) -> list:
    from app.pic.db import system_tx
    with system_tx() as s:
        return list(s.execute(select(Tenant.id).where(Tenant.code == code)).scalars())
