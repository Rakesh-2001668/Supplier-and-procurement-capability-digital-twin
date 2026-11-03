"""D14 inventory go-live inputs for AXN and KAC (pack inventory_master): MOCK master data, KAC opening stock, controllers per plant, KAC rule values.

Idempotency (a second run changes nothing, no value that is set is overwritten), the formulas, the opening position of KAC (days of cover, deliberate
stock-outs, low, expiring, quality-hold, blocked and consignment lines, price and reorder data on every stocked material), the users and the
maker-checker rules per plant, the labelled rule versions, the committed data file, and the pack's place in the setup run. The master-data formulas and the
no-overwrite rule run on a tenant of their own (IMT1). Counts that depend on the consignment-as-supply decision are asserted as properties, not numbers."""
import csv
import hashlib
import json
import os
import subprocess
import sys
import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuditEvent, InfoRecord, Material, PlanningParameter, PoLine, PurchaseOrder, RuleSet, Stock, StockBatch, StockMovement, Supplier, SupplierCategoryStatus, Tenant,
)
from app.pic.platform import abac, auth, clock
from app.pic.platform import inventory_defaults as ir
from app.pic.platform import rules
from app.pic.platform.audit import verify_chain
from app.pic.platform.auth import Principal, scopes_for
from app.pic.platform.core import next_number
from app.pic.platform.errors import Problem
from app.pic.seed import datasets
from app.pic.seed.axion import Scenario, at
from app.pic.seed.datasets import _tenant_kit as kit
from app.pic.seed.datasets import inventory_master as pack
from app.pic.services import inventory, stock_ledger
from app.pic.tools import ai_eval
from app.pic.tools import inventory_mock as mock
from app.pic.tools import stock_opening_load as loader
from tests.pic.conftest import PASSWORD

IMT = os.environ.get("IMT_TEST_TENANT", "IMT1")
KEY_DATE = mock.KEY_DATE
DOMAINS = {"AXN": "axion.example", "KAC": "kaveri-auto.example"}
PLANTS = {"AXN": ["P100", "P200"], "KAC": ["1100", "1200", "1300"]}


@pytest.fixture(scope="module")
def packs(database):
    assert datasets.apply_pack("erp_client_kac", PASSWORD)[0]["status"] in ("LOADED", "ALREADY_LOADED")
    assert {r["status"] for r in datasets.apply_pack("inventory_ops", PASSWORD)} <= {"LOADED", "ALREADY_LOADED"}
    results = {r["tenant"]: r for r in datasets.apply_pack("inventory_master", PASSWORD)}
    assert set(results) == {"AXN", "KAC"} and {r["status"] for r in results.values()} <= {"LOADED", "ALREADY_LOADED"}, results
    with system_tx() as s:
        ids = {code: tid for code, tid in s.execute(select(Tenant.code, Tenant.id))}
    yield {"results": results, "ids": ids}
    clock.set_pinned(None)


def snapshot(tenant_id) -> dict:
    with tenant_tx(tenant_id) as s:
        return {name: s.execute(select(func.count()).select_from(model)).scalar_one()
                for name, model in (("audit", AuditEvent), ("stock", Stock), ("movements", StockMovement), ("planning", PlanningParameter), ("users", AppUser),
                                    ("rules", RuleSet), ("batches", StockBatch))}


def csv_rows():
    with open(mock.OUT_DIR / mock.FILE_NAME, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


# ================================================================ idempotency
def test_a_second_run_of_the_pack_and_of_every_step_changes_nothing(packs):
    assert {r["tenant"]: r["status"] for r in datasets.apply_pack("inventory_master", PASSWORD)} == {"AXN": "ALREADY_LOADED", "KAC": "ALREADY_LOADED"}
    for code in ("AXN", "KAC"):
        tid = packs["ids"][code]
        before = snapshot(tid)
        filled = pack.fill_master(tid, code, at(date(2026, 11, 20), 9))
        flags = pack.apply_flags(tid, code)
        users = pack.ensure_users(tid, code, PASSWORD)
        assert filled["materialsFilled"] == filled["safetyFilled"] == filled["priceFilled"] == filled["planningRowsAdded"] == filled["maxStockFilled"] == 0
        assert flags["flagged"] == 0 and users["created"] == 0
        if code == "KAC":
            opening = pack.load_opening_stock(code)
            assert opening["posted"] == 0 and opening["status"] == "NOTHING_TO_POST" and opening["alreadyLoaded"] == opening["toPost"] + opening["alreadyLoaded"]
            assert pack.publish_rules(tid, code)["published"] == []
        clock.set_pinned(None)
        assert snapshot(tid) == before, code


def test_the_pack_requires_inventory_ops_is_registered_after_it_and_neon_setup_still_starts():
    assert pack.REQUIRES == {"inventory-ops": "1"} and pack.READY and pack.TENANTS == ("AXN", "KAC")
    names = list(datasets.PACKS)
    assert names.index("inventory_ops") < names.index("inventory_master") < names.index("reference_data")
    assert datasets.load("inventory_master") is pack
    backend = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    result = subprocess.run([sys.executable, "-m", "app.pic.tools.neon_setup", "--help"], cwd=backend, capture_output=True, text=True, timeout=120,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert result.returncode == 0 and "--verify-only" in result.stdout and "--skip-datasets" in result.stdout, result.stderr[-500:]


def test_the_audit_chains_stay_valid_after_the_pack(packs):
    for code in ("AXN", "KAC"):
        with tenant_tx(packs["ids"][code]) as s:
            chain = verify_chain(s)
            assert chain["valid"], (code, chain)


# ================================================================ the formulas and the no-overwrite rule (tenant IMT1)
@pytest.fixture(scope="module")
def imt(database):
    sc = kit.setup_tenant(IMT, "Inventory Master Test Pvt Ltd", "MANUFACTURING", company=("1000", "Inventory Master Test Pvt Ltd", "29AAKCD4821M1Z7"),
                          plants=[("P100", "Plant one", "29"), ("P200", "Plant two", "29")], cost_objects=[("COST_CENTER", "6100", "Test cost centre")],
                          holidays=[], domain=f"{IMT.lower()}.example", role_user={})
    kit.create_users(sc, [("admin", "Admin", ["TENANT_ADMIN"], {}), ("buyer", "Buyer", ["BUYER"], {"plants": ["P100"]})], PASSWORD)
    when = at(date(2027, 1, 15), 9)
    ids = {}
    with tenant_tx(sc.tenant_id) as s:
        supplier = Supplier(tenant_id=sc.tenant_id, code="IMSUP", legal_name="Master Test Supplies", status="QUALIFIED", country="IN", state_code="29", payment_terms="N30")
        s.add(supplier)
        s.flush()
        s.add(SupplierCategoryStatus(tenant_id=sc.tenant_id, supplier_id=supplier.id, category="GENERAL", status="QUALIFIED", qualified_on=date(2026, 1, 1)))
        spec = {  # number: (price, safety, attributes, lead days)
            "FM-INFO": (None, 0, {"plants": ["P100"]}, 3), "FM-SET": (5_000, 40, {"plants": ["P100"]}, 3), "FM-HALF": (8_000, 0, {"plants": ["P100"]}, 3),
            "FM-NONE": (None, 0, {"plants": ["P100"]}, 0), "FM-PO": (None, 0, {"plants": ["P100"]}, 3), "FM-TWO": (3_000, 0, {"plants": ["P100", "P200"]}, 3),
        }
        for number, (price, safety, attrs, lead) in spec.items():
            m = Material(tenant_id=sc.tenant_id, number=number, description=f"Master test {number}", type="STOCK", material_group="GENERAL", category="GENERAL", base_uom="EA",
                         mrp_type="PD", lot_size_policy="EXACT", safety_stock=Decimal(safety), planned_delivery_days=lead, gr_processing_days=0, standard_price_minor=price,
                         status="ACTIVE", hsn_code="8708", gst_rate=Decimal(18), attributes=attrs)
            s.add(m)
            s.flush()
            ids[number] = m.id
        s.add(Material(tenant_id=sc.tenant_id, number="FM-SERVICE", description="A service", type="SERVICE", material_group="GENERAL", category="GENERAL", base_uom="EA",
                       safety_stock=Decimal(0), standard_price_minor=None, status="ACTIVE", hsn_code="9983", gst_rate=Decimal(18)))
        s.add(InfoRecord(tenant_id=sc.tenant_id, supplier_id=supplier.id, material_id=ids["FM-INFO"], plant="P100", last_price_minor=12_345, lead_time_days=5))
        s.add(InfoRecord(tenant_id=sc.tenant_id, supplier_id=supplier.id, material_id=ids["FM-PO"], plant="P100", last_price_minor=99, lead_time_days=5))
        s.add(PlanningParameter(tenant_id=sc.tenant_id, material_id=ids["FM-SET"], plant="P100", reorder_point=Decimal(77), max_stock=Decimal(90), note="set by the customer"))
        s.add(PlanningParameter(tenant_id=sc.tenant_id, material_id=ids["FM-HALF"], plant="P100", reorder_point=Decimal(10), max_stock=None, note="set by the customer"))
        clock.set_pinned(when)
        po = PurchaseOrder(tenant_id=sc.tenant_id, number=next_number(s, "PURCHASE_ORDER"), version=1, company_code="1000", purch_org="1000", plant="P100", supplier_id=supplier.id,
                           status="CONFIRMED", purpose_code="TEST", currency="INR", total_minor=0, payment_terms="N30", tolerance={"over_pct": 0, "under_pct": 0, "price_pct": 0},
                           rule_set_version="TEST")
        s.add(po)
        s.flush()
        for number, qty, price, line_no in (("FM-PO", 360, 20_000, 10), ("FM-TWO", 720, 3_000, 20)):
            s.add(PoLine(tenant_id=sc.tenant_id, po_id=po.id, line_no=line_no, item_type="MATERIAL", purchase_type="STOCK", description="Test line", material_group="GENERAL", uom="EA",
                         gst_rate=Decimal(18), hsn_code="8708", need_date=date(2027, 2, 1), plant="P100", storage_location="0001", gr_required=True, ir_required=True,
                         ses_required=False, ers=False, quality_managed=False, price_source="MANUAL", material_id=ids[number], qty=Decimal(qty), unit_price_minor=price,
                         net_minor=qty * price))
    clock.set_pinned(None)
    yield {"sc": sc, "ids": ids, "when": when}
    clock.set_pinned(None)


def material_state(imt, number):
    with tenant_tx(imt["sc"].tenant_id) as s:
        m = s.execute(select(Material).where(Material.number == number)).scalar_one()
        params = {p.plant: p for p in s.execute(select(PlanningParameter).where(PlanningParameter.material_id == m.id)).scalars()}
        return {"price": m.standard_price_minor, "safety": m.safety_stock, "attrs": dict(m.attributes or {}),
                "params": {k: (v.reorder_point, v.max_stock, v.note) for k, v in params.items()}}


def test_the_formulas_on_known_inputs():
    f = mock.Facts(number="X", uom="EA", category="MRO", group="MR-TOOL", std_minor=10_000, safety=Decimal(0), lead_days=9, lot_qty=Decimal(50), min_lot=None, pack_size=None, plants=["P1"])
    plan = mock.plan_material(f, {"P1": Decimal(300)})                       # 300 a month = 10 a day; MRO keeps 14 days
    assert plan.usage["P1"] == (Decimal(300), "HISTORY") and plan.safety == 140 and plan.safety_filled
    assert plan.reorder["P1"] == 10 * 9 + 140 == 230 and plan.maximum["P1"] == 230 + 50
    kept = mock.plan_material(mock.Facts(**{**f.__dict__, "safety": Decimal(25)}), {"P1": Decimal(300)})
    assert kept.safety == 25 and not kept.safety_filled and kept.reorder["P1"] == 90 + 25
    slow = mock.plan_material(mock.Facts(**{**f.__dict__, "lot_qty": None}), {})                 # nothing known: one INR 50,000 lot a month = 500 units of INR 100
    assert slow.usage["P1"] == (Decimal(500), "LOT") and slow.safety == 100 and slow.reorder["P1"] == 250 and slow.maximum["P1"] == 250 + 500        # safety 20 % of the lot
    held = mock.plan_material(f, {}, {"P1": Decimal(90)})                                       # 90 on hand = 60 a month
    assert held.usage["P1"] == (Decimal(60), "ON_HAND")
    assert mock.plan_material(f, {"P1": Decimal("0.2")}).usage["P1"][0] == 1                    # the floor of one unit a month
    assert mock.unit("a", 1) == mock.unit("a", 1) != mock.unit("a", 2) and 0 <= mock.unit("a", 1) < 1


def test_missing_values_are_filled_from_the_tenants_own_data_and_traced(imt):
    sc = imt["sc"]
    counts = pack.fill_master(sc.tenant_id, IMT, imt["when"])
    clock.set_pinned(None)
    assert counts["materialsChecked"] == 6 and counts["priceFilled"] == 2 and counts["priceNoSource"] == 1          # FM-INFO (info record) and FM-PO (order line); FM-NONE has no source
    info, po = material_state(imt, "FM-INFO"), material_state(imt, "FM-PO")
    assert info["price"] == 12_345 and po["price"] == 20_000                                  # the order line beats the info record
    # FM-PO bought 360 in 12 months = 30 a month = 1 a day: safety 7 days (GENERAL default), reorder = 1 x 3 + 7, max = reorder + 30 (no lot: a month of usage)
    assert po["safety"] == 7 and po["params"]["P100"][:2] == (Decimal(10), Decimal(40)) and "MOCK" in po["params"]["P100"][2]
    assert po["attrs"]["mockFilled"]["label"] == mock.TAG and set(po["attrs"]["mockFilled"]["fields"]) == {"safetyStock", "standardPriceMinor", "planningParameters"}
    two = material_state(imt, "FM-TWO")                                                       # one material at two plants: the PO plant has history, the other the lot fallback
    assert set(two["params"]) == {"P100", "P200"} and two["safety"] >= 1
    assert material_state(imt, "FM-NONE")["price"] is None and material_state(imt, "FM-NONE")["safety"] >= 1          # no price source: nothing is invented
    with tenant_tx(sc.tenant_id) as s:
        events = s.execute(select(AuditEvent).where(AuditEvent.action == "MASTER_DATA_FILLED")).scalars().all()
        assert len(events) == counts["materialsFilled"] == 5 and {e.object_ref for e in events} == {"FM-INFO", "FM-HALF", "FM-NONE", "FM-PO", "FM-TWO"}
        event = next(e for e in events if e.object_ref == "FM-PO")
        assert event.actor == pack.ACTOR and "MOCK" in event.reason and event.before["standardPriceMinor"] is None and event.after["standardPriceMinor"] == 20_000
        assert s.execute(select(func.count()).select_from(AuditEvent).where(AuditEvent.object_ref == "FM-SET", AuditEvent.action == "MASTER_DATA_FILLED")).scalar_one() == 0


def test_a_value_that_is_set_is_never_overwritten_and_a_second_run_changes_nothing(imt):
    sc = imt["sc"]
    set_state = material_state(imt, "FM-SET")
    assert set_state["price"] == 5_000 and set_state["safety"] == 40 and set_state["params"] == {"P100": (Decimal(77), Decimal(90), "set by the customer")}
    assert "mockFilled" not in set_state["attrs"]
    half = material_state(imt, "FM-HALF")                                                     # a reorder point without a maximum: only the maximum is filled
    assert half["params"]["P100"][0] == 10 and half["params"]["P100"][1] >= 10 and half["params"]["P100"][2] == "set by the customer" and half["price"] == 8_000
    before = snapshot(sc.tenant_id)
    again = pack.fill_master(sc.tenant_id, IMT, imt["when"])
    clock.set_pinned(None)
    assert again["materialsFilled"] == 0 and again["priceFilled"] == 0 and again["safetyFilled"] == 0 and again["planningRowsAdded"] == 0 and again["maxStockFilled"] == 0
    assert snapshot(sc.tenant_id) == before
    with tenant_tx(sc.tenant_id) as s:                                                         # a user's later change survives a re-run
        m = s.execute(select(Material).where(Material.number == "FM-INFO")).scalar_one()
        m.standard_price_minor, m.safety_stock = 777, Decimal(3)
    pack.fill_master(sc.tenant_id, IMT, imt["when"])
    clock.set_pinned(None)
    assert material_state(imt, "FM-INFO")["price"] == 777 and material_state(imt, "FM-INFO")["safety"] == 3


def test_service_materials_and_the_signature_materials_are_left_alone(packs):
    with tenant_tx(packs["ids"]["AXN"]) as s:
        for number in ("DC-330", "DC-331", "FK-M8-50"):
            m = s.execute(select(Material).where(Material.number == number)).scalar_one()
            assert "mockFilled" not in (m.attributes or {})
            assert s.execute(select(func.count()).select_from(PlanningParameter).where(PlanningParameter.material_id == m.id)).scalar_one() == 0
        assert s.execute(select(Material.safety_stock).where(Material.number == "DC-330")).scalar_one() == 200
    with tenant_tx(packs["ids"]["KAC"]) as s:
        assert s.execute(select(func.count()).select_from(PlanningParameter).join(Material, Material.id == PlanningParameter.material_id).where(Material.type != "STOCK")).scalar_one() == 0


# ================================================================ master data of the demo tenants
def test_every_stock_material_of_axn_and_kac_has_a_price_a_safety_stock_and_reorder_data(packs):
    for code in ("AXN", "KAC"):
        with tenant_tx(packs["ids"][code]) as s:
            materials = [m for m in s.execute(select(Material).where(Material.type == "STOCK", Material.status == "ACTIVE")).scalars()
                         if m.number not in pack.PROTECTED.get(code, set())]
            assert materials
            params = {(p.material_id, p.plant): p for p in s.execute(select(PlanningParameter)).scalars()}
            # Materials created through master-data approval (other tests do this in the shared database) take their numbers from the
            # MATERIAL sequence, M-4xxxxx: they are new masters of their own, not data the pack fills.
            materials = [m for m in materials if not m.number.startswith("M-4")]
            assert materials
            ordered = set(s.execute(select(PoLine.material_id).distinct()).scalars())
            for m in materials:
                if not m.standard_price_minor and m.id not in ordered and not (m.attributes or {}).get("plants"):
                    continue   # no price source exists for it, so the pack invents nothing
                assert m.standard_price_minor and m.standard_price_minor > 0 and m.safety_stock > 0, (code, m.number)
                plants = (m.attributes or {}).get("plants") or []
                for plant in plants:
                    p = params[(m.id, plant)]
                    assert p.reorder_point >= 0 and p.max_stock is not None and p.max_stock >= p.reorder_point
            kac_filled = [m for m in materials if (m.attributes or {}).get("mockFilled")]
            assert kac_filled and all(m.attributes["mockFilled"]["label"] == mock.TAG for m in kac_filled)


def test_batch_and_expiry_flags_follow_the_material_and_spare_open_orders_and_batchless_stock(packs):
    with tenant_tx(packs["ids"]["KAC"]) as s:
        flagged = {m.number: m for m in s.execute(select(Material).where(Material.attributes["batchManaged"].astext == "true")).scalars()}
        assert 30 <= len(flagged) <= 80
        categories = defaultdict(set)
        for m in flagged.values():
            categories[m.category].add(bool((m.attributes or {}).get("expiryManaged")))
        assert categories["MRO-CHEMICALS"] == {True} and categories["MRO-LUBRICANTS"] == {True} and categories["RAW-MATERIALS"] <= {True, False}
        assert all(m.attributes.get("minShelfLifeDays") for m in flagged.values() if m.attributes.get("expiryManaged"))
        ids = {m.id for m in flagged.values()}
        open_lines = {r for (r,) in s.execute(select(PoLine.material_id).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id)
                                              .where(PurchaseOrder.status.in_(pack.OPEN_PO), PoLine.received_qty < PoLine.qty))}
        assert not (open_lines & ids)                                                          # a receipt in flight is not switched to batch management
        assert not ({r for (r,) in s.execute(select(Stock.material_id).where(Stock.batch == "", Stock.qty > 0))} & ids)       # nor stock that has no batch
    with tenant_tx(packs["ids"]["AXN"]) as s:
        oils = {m.number: m.attributes for m in s.execute(select(Material).where(Material.number.in_(["AXN-INV-103", "AXN-INV-104", "AXN-INV-109"]))).scalars()}
        assert oils["AXN-INV-103"]["expiryManaged"] and oils["AXN-INV-103"]["minShelfLifeDays"] == 180 and oils["AXN-INV-104"]["minShelfLifeDays"] == 90
        assert oils["AXN-INV-109"]["batchManaged"] is False and "expiryManaged" not in oils["AXN-INV-109"]       # set by the stores pack: kept; it has batchless stock


def test_a_later_receipt_still_passes_when_the_lot_is_captured_and_unflagged_materials_receive_as_before(packs):
    """The receiving code's own lot check: a flagged material needs batch (and expiry with its minimum shelf life); an unflagged one needs nothing."""
    from app.pic.services import receiving
    today = date(2026, 12, 1)
    with tenant_tx(packs["ids"]["KAC"]) as s:
        flagged = s.execute(select(Material).where(Material.attributes["expiryManaged"].astext == "true").order_by(Material.number)).scalars().first()
        plain = s.execute(select(Material).where(Material.type == "STOCK", Material.status == "ACTIVE", ~Material.attributes.has_key("batchManaged")).order_by(Material.number)).scalars().first()
        assert flagged is not None and plain is not None
        shelf = int(flagged.attributes["minShelfLifeDays"])
        line = PoLine(line_no=10, material_id=flagged.id)
        receiving._check_lot(s, line, Decimal(5), "NEWLOT1", today + timedelta(days=shelf + 30), [], today)                    # passes
        for batch, expiry in (("", today + timedelta(days=400)), ("NEWLOT1", None), ("NEWLOT1", today + timedelta(days=shelf - 1)), ("NEWLOT1", today - timedelta(days=1))):
            with pytest.raises(Problem) as refused:
                receiving._check_lot(s, line, Decimal(5), batch, expiry, [], today)
            assert refused.value.rule_ref == "RCV-LOT"
        receiving._check_lot(s, PoLine(line_no=10, material_id=plain.id), Decimal(5), "", None, [], today)                  # no lot data needed


# ================================================================ the opening position of KAC
def test_the_data_file_is_the_committed_and_deterministic_output_of_the_generator(tmp_path):
    manifest = mock.generate(tmp_path / "KAC_INVENTORY")
    committed = json.loads((mock.OUT_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["sha256"] == committed["sha256"] == hashlib.sha256((mock.OUT_DIR / mock.FILE_NAME).read_bytes()).hexdigest()
    assert manifest["rows"] == committed["rows"] == len(csv_rows()) and manifest["fictional"] and "MOCK" in manifest["label"]
    readme = (mock.OUT_DIR / "README.md").read_text(encoding="utf-8")
    assert "MOCK" in readme and "days of cover" in readme.lower() and "reconcil" in readme.lower()


def test_the_opening_position_covers_every_stock_material_with_a_plant_and_reconciles(packs):
    rows = csv_rows()
    assert all(set(r) >= set(mock.COLUMNS) for r in rows[:5])
    file_pairs = {(r["material"], r["plant"]) for r in rows}
    with tenant_tx(packs["ids"]["KAC"]) as s:
        wanted = set()
        for m in s.execute(select(Material).where(Material.type == "STOCK", Material.status == "ACTIVE")).scalars():
            for plant in (m.attributes or {}).get("plants") or []:
                wanted.add((m.number, plant))
        ops = {(number, "1100") for (number,) in s.execute(select(Material.number).join(StockMovement, StockMovement.material_id == Material.id)
                                                         .where(StockMovement.reference_id == uuid.uuid5(uuid.NAMESPACE_URL, "KAC-inventory-opening")).distinct())}
        assert len(ops) == 20 and ops <= wanted
        assert file_pairs == wanted - ops                                                       # every other pair is in the file, none twice, none of the 20
        sha = hashlib.sha256((mock.OUT_DIR / mock.FILE_NAME).read_bytes()).hexdigest()
        load_id = uuid.uuid5(loader.NS, f"KAC|{sha}")
        mine = s.execute(select(StockMovement).where(StockMovement.reference_id == load_id)).scalars().all()
        assert all(m.movement_type == "561" and m.reference_type == "OPENING_BALANCE" for m in mine)
        ids = {m.number: m.id for m in s.execute(select(Material).where(Material.number.in_({r["material"] for r in rows}))).scalars()}
        file_keys = {(ids[r["material"]], r["plant"], r["storage_location"], r["stock_type"], r["batch"]): r for r in rows if Decimal(r["qty"]) > 0}
        loaded_keys = {(m.material_id, m.plant, m.storage_location, m.stock_type, m.batch) for m in mine}
        assert loaded_keys <= set(file_keys) and len(mine) == len(loaded_keys)
        # a balance that other tests of the same run had already posted into (a goods receipt on a KAC order) is skipped, not topped up
        skipped = set(file_keys) - loaded_keys
        assert len(skipped) <= 5
        for key in skipped:
            assert s.execute(select(func.count()).select_from(StockMovement).where(StockMovement.material_id == key[0], StockMovement.plant == key[1],
                                                                                   StockMovement.storage_location == key[2], StockMovement.stock_type == key[3],
                                                                                   StockMovement.batch == key[4])).scalar_one() >= 1
        ops_ids = {x for (x,) in s.execute(select(Material.id).where(Material.number.in_([n for n, _ in ops])))}
        assert not any(m.plant == "1100" and m.material_id in ops_ids for m in mine)
        # the ledger value of the load is the file's valuation column to the paisa (less the skipped balances)
        file_value = sum(int((Decimal(r["valuation"]) * 100).to_integral_value()) for key, r in file_keys.items() if key not in skipped)
        assert sum(m.value_minor or 0 for m in mine) == file_value
        # every balance equals the sum of its movements (nothing was written behind the ledger)
        sums = defaultdict(Decimal)
        for m in mine:
            sums[(m.material_id, m.plant, m.storage_location, m.stock_type, m.batch)] += m.qty
        for key, total in list(sums.items())[:400]:
            stock = s.execute(select(Stock).where(Stock.material_id == key[0], Stock.plant == key[1], Stock.storage_location == key[2], Stock.stock_type == key[3],
                                                  Stock.batch == key[4])).scalar_one()
            assert stock.qty >= total


def test_days_of_cover_are_mostly_twenty_to_sixty(packs):
    """Cover = unrestricted quantity / (monthly usage / 30), the usage being the one the master-data formulas use."""
    rows = [r for r in csv_rows() if r["stock_type"] == "UNRESTRICTED"]
    qty = defaultdict(Decimal)
    for r in rows:
        qty[(r["material"], r["plant"])] += Decimal(r["qty"])
    history, _ = mock.kac_purchase_history()
    with tenant_tx(packs["ids"]["KAC"]) as s:
        materials = {m.number: m for m in s.execute(select(Material).where(Material.number.in_({n for n, _ in qty}))).scalars()}
        days = []
        for (number, plant), q in qty.items():
            m = materials[number]
            plan = mock.plan_material(pack._facts(m, (m.attributes or {}).get("plants"), m.standard_price_minor), {p: history[(number, p)] for p in m.attributes["plants"] if (number, p) in history})
            monthly = plan.usage[plant][0]
            if q > 0:
                days.append(float(q / (monthly / 30)))
    days.sort()
    n = len(days)
    inside = sum(1 for d in days if 20 <= d <= 60) / n
    assert n > 1400 and inside >= 0.60, inside                                                 # mostly 20-60 days
    assert sum(1 for d in days if d < 20) / n < 0.05                                           # the few deliberately low ones, not a general shortage
    assert 0.35 <= days[n // 2] / 1 and days[n // 2] <= 80                                     # the median sits in the realistic range


def test_the_deliberate_exceptions_exist(packs):
    rows = csv_rows()
    manifest = json.loads((mock.OUT_DIR / "MANIFEST.json").read_text(encoding="utf-8"))["summary"]
    stockouts = [r for r in rows if Decimal(r["qty"]) == 0]
    assert 2 <= len(stockouts) <= 4 and len(stockouts) == manifest["stockOut"]
    with tenant_tx(packs["ids"]["KAC"]) as s:
        for r in stockouts:                                                                    # a stock-out has no balance at all
            material = s.execute(select(Material).where(Material.number == r["material"])).scalar_one()
            assert s.execute(select(func.count()).select_from(Stock).where(Stock.material_id == material.id, Stock.plant == r["plant"], Stock.qty > 0)).scalar_one() == 0
        free = defaultdict(Decimal)
        for material_id, plant, q in s.execute(select(Stock.material_id, Stock.plant, func.sum(Stock.qty)).where(Stock.stock_type == "UNRESTRICTED").group_by(Stock.material_id, Stock.plant)):
            free[(material_id, plant)] = q
        keys = {(r["material"], r["plant"]) for r in rows if r["stock_type"] == "UNRESTRICTED"}
        low = below_reorder = 0
        for m in s.execute(select(Material).where(Material.number.in_({n for n, _ in keys}))).scalars():
            for plant in m.attributes["plants"]:
                if (m.number, plant) not in keys:
                    continue
                on_hand = free.get((m.id, plant), Decimal(0))
                point = s.execute(select(PlanningParameter.reorder_point).where(PlanningParameter.material_id == m.id, PlanningParameter.plant == plant)).scalar_one()
                low += 1 if 0 < on_hand < m.safety_stock else 0
                below_reorder += 1 if m.safety_stock <= on_hand <= point else 0
        assert low >= manifest["belowSafety"] >= 10 and below_reorder >= manifest["belowReorder"] >= 5
        # stock that is expiring in about 30 / 60 / 90 days (from the key date), in the batch master
        expiring = {"30": 0, "60": 0, "90": 0}
        for b in s.execute(select(StockBatch).where(StockBatch.source == "OPENING_BALANCE")).scalars():
            gap = (b.expiry_date - KEY_DATE).days
            for bucket, limit in (("30", 30), ("60", 60), ("90", 90)):
                if gap <= limit and (bucket == "30" or gap > int(bucket) - 30):
                    expiring[bucket] += 1
                    break
        assert all(v >= 2 for v in expiring.values()), expiring
        assert s.execute(select(func.count()).select_from(StockBatch).where(StockBatch.expiry_date > KEY_DATE + timedelta(days=150))).scalar_one() >= 30
        # first expiry first out sees the batch master: the earlier batch comes first
        soon = s.execute(select(StockBatch).where(StockBatch.expiry_date <= KEY_DATE + timedelta(days=30)).order_by(StockBatch.expiry_date)).scalars().first()
        assert stock_ledger.batch_expiry(s, soon.material_id)[soon.batch] == soon.expiry_date
        by_type = dict(s.execute(select(Stock.stock_type, func.count()).where(Stock.qty > 0).group_by(Stock.stock_type)).all())
        assert by_type.get("QUALITY", 0) >= 3 and by_type.get("BLOCKED", 0) >= 3 and by_type.get("CONSIGNMENT", 0) >= 1
    assert sum(1 for r in rows if r["stock_type"] == "QUALITY") == 3 and sum(1 for r in rows if r["stock_type"] == "BLOCKED") == 3 and sum(1 for r in rows if r["stock_type"] == "CONSIGNMENT") == 1


def test_every_material_with_opening_stock_has_a_price_and_reorder_data(packs):
    with tenant_tx(packs["ids"]["KAC"]) as s:
        rows = s.execute(select(Stock, Material).join(Material, Material.id == Stock.material_id).where(Stock.qty > 0)).all()
        params = {(p.material_id, p.plant) for p in s.execute(select(PlanningParameter)).scalars()}
        assert len(rows) > 1500
        for stock, material in rows:
            assert material.standard_price_minor and material.safety_stock > 0 and (stock.material_id, stock.plant) in params, (material.number, stock.plant)


# ================================================================ users per plant, maker-checker
def user(tid, email):
    with tenant_tx(tid) as s:
        row = s.execute(select(AppUser).where(AppUser.email == email)).scalar_one()
        return {"roles": list(row.roles), "attributes": dict(row.attributes), "mfa": row.mfa_enrolled, "active": row.active, "name": row.full_name, "hash": row.password_hash}


@pytest.mark.parametrize("code", ["AXN", "KAC"])
def test_two_inventory_controllers_per_plant_with_that_plant_only(packs, code):
    tid = packs["ids"][code]
    for plant in PLANTS[code]:
        for n in (1, 2):
            u = user(tid, f"inventory.controller.{plant}.{n}@{DOMAINS[code]}")
            assert u["roles"] == ["INVENTORY_CONTROLLER"] and u["attributes"]["plants"] == [plant] and u["active"] and u["name"] == f"Mock Inventory Controller {plant}-{n}"
            assert u["mfa"] is False                                                           # as the existing inventory controllers
            assert auth.verify_password(PASSWORD, u["hash"]) if hasattr(auth, "verify_password") else u["hash"]
            assert "inventory:approve" in scopes_for(u["roles"]) and "inventory:post" in scopes_for(u["roles"])
            if code == "KAC":
                assert u["attributes"]["approval_limits"] == {"INVENTORY_APPROVE": pack.CONTROLLER_LIMIT_MINOR}
            else:
                assert "approval_limits" not in u["attributes"]
    with tenant_tx(tid) as s:                                                                   # a receiver with inventory:count for every plant
        for plant in PLANTS[code]:
            receivers = [u for u in s.execute(select(AppUser)).scalars() if "RECEIVER" in u.roles and plant in ((u.attributes or {}).get("plants") or [])]
            assert receivers and any("inventory:count" in scopes_for(u.roles) for u in receivers)
    if code == "AXN":
        assert user(tid, "receiver.p200@axion.example")["name"] == "Mock Receiver P200"


def test_the_controller_limit_matches_the_approval_bands_of_the_rule(packs):
    body = pack.KAC_RULES[ir.POSTING_KEY]
    assert pack.CONTROLLER_LIMIT_MINOR == body["approvalBands"][1]["upTo"]
    policy = abac.DEFAULT_POLICY
    attrs = user(packs["ids"]["KAC"], "inventory.controller.1100.1@kaveri-auto.example")["attributes"]
    assert abac.evaluate(policy, attrs, "INVENTORY_APPROVE", {"plant": "1100"}, pack.CONTROLLER_LIMIT_MINOR)["allowed"]
    over = abac.evaluate(policy, attrs, "INVENTORY_APPROVE", {"plant": "1100"}, pack.CONTROLLER_LIMIT_MINOR + 1)
    assert not over["allowed"] and over["violations"][0]["code"] == "VALUE_LIMIT_EXCEEDED"
    other = abac.evaluate(policy, attrs, "INVENTORY_APPROVE", {"plant": "1200"}, 1000)
    assert not other["allowed"] and other["violations"][0]["code"] == "FORBIDDEN"
    # above the limit the chain no longer needs a controller, below it the controller always takes part
    assert "INVENTORY_CONTROLLER" in ir.band_chain(body, pack.CONTROLLER_LIMIT_MINOR) and "INVENTORY_CONTROLLER" not in ir.band_chain(body, pack.CONTROLLER_LIMIT_MINOR + 1)
    count = pack.KAC_RULES[ir.COUNT_KEY]
    assert count["approvalBands"][1]["upTo"] <= pack.CONTROLLER_LIMIT_MINOR


def principal_of(s, code, tid, email):
    row = s.execute(select(AppUser).where(AppUser.email == email)).scalar_one()
    p = Principal(user_id=row.id, tenant_id=tid, tenant_code=code, email=row.email, name=row.full_name, roles=list(row.roles), scopes=scopes_for(list(row.roles)),
                  attributes=row.attributes or {}, supplier_id=row.supplier_id)
    s.info["principal"], s.info["user_id"] = p, row.id
    return p


@pytest.mark.parametrize("code,plant,maker,checker", [(c, p, m, 3 - m) for c in ("AXN", "KAC") for p in PLANTS[c] for m in (1, 2)])
def test_at_every_plant_two_controllers_can_approve_and_the_maker_cannot(packs, code, plant, maker, checker):
    tid = packs["ids"][code]
    domain = DOMAINS[code]
    sc = Scenario(tid, code, domain, {})
    email = lambda n: f"inventory.controller.{plant}.{n}@{domain}"  # noqa: E731
    other_plant = next(p for p in PLANTS[code] if p != plant)
    when = ai_eval._when(date(2026, 11, 12) if code == "KAC" else date(2027, 3, 31), 10)
    with ai_eval.rolled_back(sc, email(maker), when) as s:
        row = s.execute(select(Stock, Material).join(Material, Material.id == Stock.material_id).where(
            Stock.plant == plant, Stock.storage_location == "0001", Stock.stock_type == "UNRESTRICTED", Stock.batch == "", Stock.qty >= 5,
            Material.standard_price_minor.between(100, 100_000)).order_by(Material.number)).first()
        if row is None:                                                                         # AXN P200 holds no stock: put some there in this (rolled back) transaction
            material = s.execute(select(Material).where(Material.number == "AXN-INV-101")).scalar_one()
            stock_ledger.post_movement(s, material_id=material.id, plant=plant, sloc="0001", stock_type="UNRESTRICTED", qty=Decimal(10), movement="561",
                                       ref_type="OPENING_BALANCE", ref_id=material.id, ref="TEST-OPEN", posting_ref="TEST")
            number = material.number
        else:
            number = row[1].number
        posting = inventory.create_posting(s, posting_type="SCRAP", plant=plant, reason_code="HANDLING_DAMAGE" if code == "KAC" else "DAMAGED", submit=True,
                                           reason="Crushed cartons found in the aisle", lines=[{"material": number, "qty": Decimal(1), "storage_location": "0001"}])
        assert posting.status == "SUBMITTED"
        with pytest.raises(Problem) as own:                                                     # SOD-10: the maker never approves
            inventory.decide_posting(s, posting, "APPROVE", "my own posting")
        assert own.value.status == 409 and own.value.code == "SOD_CONFLICT"
        principal_of(s, code, tid, f"inventory.controller.{other_plant}.1@{domain}")
        with pytest.raises(Problem) as elsewhere:                                               # a controller of another plant is not asked
            inventory.decide_posting(s, posting, "APPROVE", "wrong plant")
        assert elsewhere.value.status in (403, 409)
        principal_of(s, code, tid, email(checker))
        inventory.decide_posting(s, posting, "APPROVE", "Checked on the floor")
        assert posting.status == "APPROVED"
        inventory.post_posting(s, posting)
        assert posting.status == "POSTED" and posting.approved_by != posting.submitted_by and posting.erp_doc_no


# ================================================================ the KAC rule values
def test_the_kac_rule_versions_are_effective_labelled_and_valid(packs):
    tid = packs["ids"]["KAC"]
    with tenant_tx(tid) as s:
        for key in pack.KAC_RULES:
            row = s.execute(select(RuleSet).where(RuleSet.key == key, RuleSet.version == pack.RULE_VERSION)).scalar_one()
            assert row.effective_from == pack.RULE_EFFECTIVE and row.effective_to is None and row.company_code is None and row.plant is None
            assert row.description.startswith("MOCK proposal - pending client sign-off") and ir.validate(key, row.body) == []
            assert rules.resolve(s, key, on=date(2026, 11, 9)).version == pack.RULE_VERSION           # effective from 1 November 2026, ahead of the 2026.1 defaults
            assert rules.resolve(s, key, on=date(2026, 10, 15)).version == "2026.1"                    # the version before it is still the one for earlier dates
            event = s.execute(select(AuditEvent).where(AuditEvent.object_id == row.id, AuditEvent.action == "VERSION_CREATED")).scalar_one()
            assert event.object_ref == f"{key}@{pack.RULE_VERSION}" and "MOCK" in event.reason
        posting = ir.rule(s, ir.POSTING_KEY, company_code="1000", plant="1100")
        assert posting.version == pack.RULE_VERSION and posting.body["autoPostBelowMinor"] == 5_000_000
        assert ir.band_chain(posting.body, 300_000_00) == ["INVENTORY_CONTROLLER"] and ir.band_chain(posting.body, 300_000_01) == ["INVENTORY_CONTROLLER", "FINANCE_CONTROLLER"]
        assert ir.band_chain(posting.body, 1_500_000_00) == ["INVENTORY_CONTROLLER", "FINANCE_CONTROLLER"] and ir.band_chain(posting.body, 1_500_000_01) == ["FINANCE_CONTROLLER", "CPO"]
        assert "CASTING_DEFECT" in posting.body["scrapReasons"] and "SHELF_LIFE_EXPIRED" in posting.body["scrapReasons"] and "SCRAP" not in posting.body["autoPostTypes"]
        assert ir.rule(s, ir.COUNT_KEY).body["qtyTolerancePct"] == "1" and ir.rule(s, ir.RESERVATION_KEY).body["graceDays"] == 3 and ir.rule(s, ir.ALERTS_KEY).body["blockedDays"] == 15
    with tenant_tx(packs["ids"]["AXN"]) as s:                                                      # AXN keeps its defaults: the proposal is for KAC only
        assert {r.version for r in s.execute(select(RuleSet).where(RuleSet.key == ir.POSTING_KEY)).scalars()} == {"2026.1"}


def test_the_proposal_document_lists_every_value_and_a_blank_sign_off_table():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "docs", "PIC_Inventory_Rule_Values_Proposal.md")
    text = open(path, encoding="utf-8").read()
    assert "MOCK proposal - pending client sign-off" in text and "not confirmed" in text.lower()
    for value in ("50,000", "3,00,000", "15,00,000", "CASTING_DEFECT", "SHELF_LIFE_EXPIRED", "qtyTolerancePct", "graceDays", "qualityHoldDays", "blockedDays", "expiryWarnDays",
                  "autoPostBelowMinor", "approvalBands", "valueToleranceMinor", "maxOpenDays"):
        assert value in text, value
    assert "Sign-off" in text and "Approver" in text and "Date" in text
