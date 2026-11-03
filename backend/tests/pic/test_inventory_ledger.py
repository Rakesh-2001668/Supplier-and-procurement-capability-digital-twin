"""The stock ledger and its reads (inventory module, M09): the posting primitive, the regression tests of the defects fixed in the receiving code
(serials of a reversed receipt, malformed expiry dates, cut-off on reversals and usage decisions, indexes and constraints, expiry of reversed
receipts, plant guards on stock-changing commands) and the stock reads (list filters, summary, alerts, stock card, movement ledger and its export).

Own tenant (INL1) with two plants of one company code; every document is inserted or posted through the real services."""
import csv
import io
import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.pic.db import tenant_tx
from app.pic.models import (
    AppUser, Asn, DemandElement, InspectionLot, Material, PlanningParameter, PoLine, PurchaseOrder, Stock, StockMovement, StorageLocation, Supplier,
    SupplierCategoryStatus,
)
from app.pic.platform import clock
from app.pic.platform.auth import hash_password
from app.pic.platform.core import next_number
from app.pic.platform.errors import Problem
from app.pic.seed.axion import at
from app.pic.seed.datasets import _tenant_kit as kit
from app.pic.services import finance_controls, ind_healthcare, receiving, stock_ledger

from .conftest import PASSWORD

CODE = os.environ.get("INL_TEST_TENANT", "INL1")   # a developer re-running against a kept database (PIC_TEST_KEEP_DB) picks a fresh tenant code
DOMAIN = f"{CODE.lower()}.example"
GSTIN = "29AAKCD4821M1Z7"
P1, P2 = "P100", "P200"
TODAY = date(2026, 11, 4)

USERS = [
    ("admin", "Admin", ["TENANT_ADMIN"], {}),
    ("buyer", "Bala Buyer", ["BUYER"], {"plants": [P1, P2]}),
    ("recv", "Rita Receiver", ["RECEIVER"], {"plants": [P1, P2]}),
    ("recv2", "Ravi Receiver (P200 only)", ["RECEIVER"], {"plants": [P2]}),
    ("qi", "Qasim Quality", ["QUALITY_INSPECTOR"], {"plants": [P1, P2]}),
    ("qi2", "Qamar Quality (P200 only)", ["QUALITY_INSPECTOR"], {"plants": [P2]}),
    ("fin", "Farid Finance", ["FINANCE_CONTROLLER"], {}),
    ("ic", "Isha Inventory", ["INVENTORY_CONTROLLER"], {"plants": [P1, P2]}),
    ("reader", "Rhea Reader", ["REQUESTER"], {}),
]
ROLE_USER = {"FINANCE_CONTROLLER": "fin", "INVENTORY_CONTROLLER": "ic", "BUYER": "buyer"}
M = {}  # material number -> id


def _email(local: str) -> str:
    return f"{local}@{DOMAIN}"


def _pin(day: date = TODAY, hour: int = 10) -> None:
    clock.set_pinned(at(day, hour))


@pytest.fixture(scope="module")
def env(database):
    sc = kit.setup_tenant(CODE, "Inventory Ledger Test Pvt Ltd", "MANUFACTURING", company=("1000", "Inventory Ledger Test Pvt Ltd", GSTIN),
                          plants=[(P1, "Plant one", "29"), (P2, "Plant two", "29")], cost_objects=[("COST_CENTER", "6100", "Test cost centre")],
                          holidays=[], domain=DOMAIN, role_user=ROLE_USER)
    kit.create_users(sc, USERS, PASSWORD)
    kit.rule_version(sc, "MFA", "2026.1-INL", date(2026, 4, 1), {"enforce": False}, "Inventory ledger test tenant: no MFA challenge")
    with tenant_tx(sc.tenant_id) as s:
        for plant in (P1, P2):
            s.add(StorageLocation(tenant_id=sc.tenant_id, plant=plant, code="0002", name="Second location"))
        sup = Supplier(tenant_id=sc.tenant_id, code="INLSUP", legal_name="Ledger Supplies Pvt Ltd", status="QUALIFIED", country="IN", state_code="29",
                       payment_terms="N30")
        s.add(sup)
        s.flush()
        s.add(SupplierCategoryStatus(tenant_id=sc.tenant_id, supplier_id=sup.id, category="GENERAL", status="QUALIFIED", qualified_on=date(2026, 1, 1)))
        s.add(AppUser(tenant_id=sc.tenant_id, email=f"portal@inlsup.{DOMAIN}", full_name="Ledger Supplies portal", password_hash=hash_password(PASSWORD),
                      roles=["SUPPLIER_USER"], attributes={}, supplier_id=sup.id, mfa_enrolled=True))
        for number, kw in (("INL-A", {}), ("INL-B", {"attributes": {"batchManaged": True, "expiryManaged": True}}), ("INL-S", {"attributes": {"serialManaged": True}}),
                           ("INL-Q", {"quality_managed": True}), ("INL-NP", {"standard_price_minor": None}),
                           ("INL-SAFE", {"safety_stock": Decimal(50)}), ("INL-CONS", {})):
            values = dict(description=f"Ledger test {number}", type="STOCK", material_group="GENERAL", category="GENERAL", base_uom="EA", mrp_type="PD",
                          lot_size_policy="EXACT", safety_stock=Decimal(0), planned_delivery_days=3, gr_processing_days=0, standard_price_minor=10_000,
                          status="ACTIVE", hsn_code="8708", gst_rate=Decimal(18))
            values.update(kw)
            m = Material(tenant_id=sc.tenant_id, number=number, **values)
            s.add(m)
            s.flush()
            M[number] = m.id
        M["supplier"] = sup.id
    return sc


def _po(s, sc, lines: list[dict], plant: str = P1, purchase_type: str = "STOCK") -> PurchaseOrder:
    buyer = s.execute(select(AppUser).where(AppUser.email == sc.email("buyer"))).scalar_one()
    po = PurchaseOrder(tenant_id=sc.tenant_id, number=next_number(s, "PURCHASE_ORDER"), version=1, company_code="1000", purch_org="1000", plant=plant,
                       supplier_id=M["supplier"], status="CONFIRMED", purpose_code="TEST", currency="INR", total_minor=0, payment_terms="N30",
                       tolerance={"over_pct": 0, "under_pct": 0, "price_pct": 0}, rule_set_version="TEST", created_by=buyer.id)
    s.add(po)
    s.flush()
    for index, data in enumerate(lines, start=1):
        qty, price = Decimal(str(data["qty"])), int(data.get("unit_price_minor", 10_000))
        s.add(PoLine(tenant_id=sc.tenant_id, po_id=po.id, line_no=index * 10, item_type="MATERIAL", purchase_type=purchase_type, description="Test line",
                     material_group="GENERAL", uom="EA", gst_rate=Decimal(18), hsn_code="8708", need_date=TODAY + timedelta(days=10), plant=plant,
                     storage_location=data.get("storage_location", "0001"), gr_required=True, ir_required=purchase_type != "CONSIGNMENT", ses_required=False,
                     ers=False, quality_managed=bool(data.get("quality_managed", False)), price_source="MANUAL", material_id=M[data["material"]], qty=qty,
                     unit_price_minor=price, net_minor=int(qty * price), created_by=buyer.id))
    s.flush()
    return po


def _receive(env, material: str, qty, *, plant: str = P1, batch: str = "", expiry=None, serials=None, day: date = TODAY, sloc: str = "0001",
             quality: bool = False, purchase_type: str = "STOCK", who: str = "recv"):
    """A confirmed order for the material and its goods receipt, as the receiver: (po id, gr id, gr number)."""
    with env.act("buyer", at(day, 8)) as s:
        po = _po(s, env, [dict(material=material, qty=qty, quality_managed=quality, storage_location=sloc)], plant, purchase_type)
        po_id = po.id
    with env.act(who, at(day, 10)) as s:
        line = {"line": 10, "qty": str(qty), "batch": batch, "storage_location": sloc}
        if expiry:
            line["expiry"] = expiry
        if serials:
            line["serials"] = serials
        gr = receiving.post_gr(s, s.get(PurchaseOrder, po_id), lines=[line], posting_date=day)
        return po_id, gr.id, gr.number


def _on_hand(env, material: str, stock_type: str = "UNRESTRICTED", plant: str = P1, sloc: str = "0001", batch: str = "") -> Decimal:
    with tenant_tx(env.tenant_id) as s:
        return stock_ledger.on_hand(s, M[material], plant, sloc, stock_type, batch)


def _problem(call) -> Problem:
    with pytest.raises(Problem) as caught:
        call()
    return caught.value


def _h(login, local: str) -> dict:
    return login(_email(local), CODE)


# ================================================================ the posting primitive
def test_post_movement_signs_value_negative_guard_and_decimals(env):
    _pin()
    with env.act("admin", at(TODAY, 9)) as s:
        ref = uuid.uuid4()
        one = dict(material_id=M["INL-A"], plant=P1, sloc="0001", stock_type="UNRESTRICTED", batch="", ref_type="TEST", ref_id=ref, ref="T-1")
        line = stock_ledger.post_movement(s, qty=Decimal("10.500"), movement="561", **one)
        assert line.value_minor == 105_000 and line.qty == Decimal("10.5")        # quantity x standard price at the time
        assert stock_ledger.post_movement(s, qty=Decimal(0), movement="561", **one) is None   # nothing to post
        wrong_sign = _problem(lambda: stock_ledger.post_movement(s, qty=Decimal(-1), movement="561", **one))
        assert wrong_sign.code == "MOVEMENT_SIGN"
        wrong_sign = _problem(lambda: stock_ledger.post_movement(s, qty=Decimal(1), movement="551", **one))
        assert wrong_sign.code == "MOVEMENT_SIGN"
        too_precise = _problem(lambda: stock_ledger.post_movement(s, qty=Decimal("0.0001"), movement="561", **one))
        assert too_precise.code == "INVALID_QUANTITY"
        bad_type = _problem(lambda: stock_ledger.post_movement(s, qty=Decimal(1), movement="561", **{**one, "stock_type": "FREE"}))
        assert bad_type.code == "INVALID_STOCK_TYPE"
        negative = _problem(lambda: stock_ledger.post_movement(s, qty=Decimal(-11), movement="551", **one))
        assert negative.code == "NEGATIVE_STOCK" and negative.extra["availableQty"] == "10.5"
        nothing = _problem(lambda: stock_ledger.post_movement(s, qty=Decimal(-1), movement="551", **{**one, "batch": "NOPE"}))
        assert nothing.code == "NEGATIVE_STOCK"
        # no standard price: the line carries no value (null), not zero
        unpriced = stock_ledger.post_movement(s, material_id=M["INL-NP"], plant=P1, sloc="0001", stock_type="UNRESTRICTED", batch="", qty=Decimal(3),
                                              movement="561", ref_type="TEST", ref_id=ref, ref="T-2", posting_ref="STP-X", reason_code="OPENING")
        assert unpriced.value_minor is None and unpriced.posting_ref == "STP-X" and unpriced.reason_code == "OPENING"
        stock_ledger.post_movement(s, qty=Decimal(-4), movement="551", **one)
    assert _on_hand(env, "INL-A") == Decimal("6.5")


def test_the_receipt_moves_through_the_same_primitive_with_a_value(env):
    _po_id, _gr_id, number = _receive(env, "INL-A", 20, day=TODAY)
    with tenant_tx(env.tenant_id) as s:
        gr_lines = s.execute(select(StockMovement).where(StockMovement.reference_ref == number)).scalars().all()
        assert len(gr_lines) == 1 and gr_lines[0].movement_type == "101" and gr_lines[0].value_minor == 200_000
    assert _on_hand(env, "INL-A") == Decimal("26.5")


# ================================================================ regression: Part 1
def test_serial_numbers_of_a_reversed_receipt_are_free_again(env):
    """Defect 1: the 'serial already received' check counted the lines of reversed receipts, so the corrected receipt of the same serials was refused."""
    _po_id, gr_id, number = _receive(env, "INL-S", 2, serials=["SN-1001", "SN-1002"])
    # the same serials on a second receipt while the first stands: refused, naming them
    with env.act("buyer", at(TODAY, 8)) as s:
        po = _po(s, env, [dict(material="INL-S", qty=2)])
        po_id = po.id
    with env.act("recv", at(TODAY, 10)) as s:
        refused = _problem(lambda: receiving.post_gr(s, s.get(PurchaseOrder, po_id), lines=[{"line": 10, "qty": "2", "serials": ["SN-1002", "SN-1003"]}],
                                                      posting_date=TODAY))
        assert refused.code == "RULE_VIOLATION" and "SN-1002" in refused.detail and "SN-1003" not in refused.detail
    with env.act("recv", at(TODAY, 11)) as s:
        from app.pic.models import GoodsReceipt
        receiving.reverse_gr(s, s.get(GoodsReceipt, gr_id), "Wrong delivery note")
    with env.act("recv", at(TODAY, 12)) as s:   # the corrected receipt of the same serials
        gr = receiving.post_gr(s, s.get(PurchaseOrder, po_id), lines=[{"line": 10, "qty": "2", "serials": ["SN-1001", "SN-1002"]}], posting_date=TODAY)
        assert gr.status == "ACCEPTED"
    with env.act("buyer", at(TODAY, 8)) as s:
        po3 = _po(s, env, [dict(material="INL-S", qty=1)]).id
    with env.act("recv", at(TODAY, 13)) as s:   # and now they are received again for good
        assert _problem(lambda: receiving.post_gr(s, s.get(PurchaseOrder, po3), lines=[{"line": 10, "qty": "1", "serials": ["SN-1001"]}],
                                                  posting_date=TODAY)).code == "RULE_VIOLATION"


def test_the_serial_check_is_an_indexed_query(env):
    with tenant_tx(env.tenant_id) as s:
        names = {r[0] for r in s.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'pic' AND tablename = 'gr_line'"))}
        assert {"ix_gr_line_serials", "ix_gr_line_material_batch"} <= names
        definition = s.execute(text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_gr_line_serials'")).scalar_one()
        assert "gin" in definition.lower()


def test_malformed_expiry_dates_are_422_problems_not_500s(env, client, login):
    """Defect 2: GrLineIn.expiry was free text that reached date.fromisoformat (HTTP 500). It is a validated date; so are the ASN batch expiries."""
    _pin()
    with env.act("buyer", at(TODAY, 8)) as s:
        po = _po(s, env, [dict(material="INL-B", qty=5)])
        po_number, po_id = po.number, po.id
    recv = _h(login, "recv")
    for bad in ("31/12/2027", "tomorrow", "2027-13-45", "20271231x"):
        r = client.post("/v1/goods-receipts", json={"po": po_number, "lines": [{"line": 10, "qty": "5", "batch": "B-X", "expiry": bad}]}, headers=recv)
        assert r.status_code == 422 and r.headers["content-type"].startswith("application/problem+json"), (bad, r.status_code, r.text)
        assert r.json()["code"] == "VALIDATION_FAILED" and "expiry" in r.json()["detail"]
    portal = login(f"portal@inlsup.{DOMAIN}", CODE)
    r = client.post("/v1/asns", json={"po": po_number, "ship_date": "2026-11-04", "expected_date": "2026-11-06",
                                      "lines": [{"line": 10, "qty": "5", "batches": [{"batch": "B-X", "qty": "5", "expiry": "next spring"}]}]}, headers=portal)
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_FAILED" and "expiry" in r.json()["detail"], r.text
    with tenant_tx(env.tenant_id) as s:
        assert s.execute(select(func.count()).select_from(Stock).where(Stock.material_id == M["INL-B"])).scalar_one() == 0
    ok = client.post("/v1/goods-receipts", json={"po": po_number, "lines": [{"line": 10, "qty": "5", "batch": "B-X", "expiry": "2027-12-31"}]}, headers=recv)
    assert ok.status_code == 201, ok.text
    assert _on_hand(env, "INL-B", batch="B-X") == 5


def test_reversal_and_usage_decision_respect_the_closed_posting_period(env):
    """Defect 3: reverse_gr and usage_decision moved stock without the cut-off that post_gr applies. A period can only be closed once it has ended,
    so the test closes October and moves the business clock back into it."""
    from app.pic.models import GoodsReceipt
    _po_id, gr_id, gr_number = _receive(env, "INL-A", 3, day=TODAY)
    _po_q, grq_id, _ = _receive(env, "INL-Q", 4, day=TODAY, quality=True)
    with tenant_tx(env.tenant_id) as s:
        lot_id = s.execute(select(InspectionLot.id).where(InspectionLot.gr_id == grq_id)).scalar_one()
    with env.act("fin", at(date(2026, 12, 2), 10)) as s:
        finance_controls.close_period(s, "1000", "2026-11", "Month-end close for the cut-off test")
    try:
        with env.act("recv", at(date(2026, 11, 20), 10)) as s:   # the clock is back inside the closed period
            refused = _problem(lambda: receiving.reverse_gr(s, s.get(GoodsReceipt, gr_id), "Wrong delivery"))
            assert refused.code == "PERIOD_CLOSED" and refused.rule_ref == "CUT-OFF"
        with env.act("qi", at(date(2026, 11, 20), 11)) as s:
            refused = _problem(lambda: receiving.usage_decision(s, s.get(InspectionLot, lot_id), accepted=Decimal(4), rejected=Decimal(0)))
            assert refused.code == "PERIOD_CLOSED"
        with tenant_tx(env.tenant_id) as s:   # nothing moved
            assert s.execute(select(InspectionLot.status).where(InspectionLot.id == lot_id)).scalar_one() == "OPEN"
            assert s.execute(select(GoodsReceipt.status).where(GoodsReceipt.id == gr_id)).scalar_one() == "ACCEPTED"
    finally:
        with env.act("fin", at(date(2026, 12, 3), 10)) as s:
            finance_controls.reopen_period(s, "1000", "2026-11", "Reopened after the cut-off test")
    with env.act("recv", at(TODAY, 15)) as s:
        assert receiving.reverse_gr(s, s.get(GoodsReceipt, gr_id), "Wrong delivery").status == "REVERSED"
    with env.act("qi", at(TODAY, 16)) as s:
        assert receiving.usage_decision(s, s.get(InspectionLot, lot_id), accepted=Decimal(4), rejected=Decimal(0))["status"] == "ACCEPTED"


def test_indexes_and_constraints_of_the_ledger(env):
    """Defect 4: indexes for the movement ledger and constraints on the stock table."""
    with tenant_tx(env.tenant_id) as s:
        names = {r[0] for r in s.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'pic'"))}
        assert {"ix_stock_movement_material_plant_created", "ix_stock_movement_reference", "ix_stock_plant_type"} <= names
        constraints = {r[0] for r in s.execute(text("SELECT conname FROM pg_constraint WHERE conrelid = 'pic.stock'::regclass"))}
        assert {"ck_stock_stock_type", "ck_stock_qty_not_negative"} <= constraints
    with pytest.raises(IntegrityError):
        with tenant_tx(env.tenant_id) as s:
            s.add(Stock(tenant_id=env.tenant_id, material_id=M["INL-A"], plant=P1, storage_location="0001", stock_type="FREE", batch="X", qty=Decimal(1)))
    with pytest.raises(IntegrityError):
        with tenant_tx(env.tenant_id) as s:
            s.add(Stock(tenant_id=env.tenant_id, material_id=M["INL-A"], plant=P1, storage_location="0001", stock_type="UNRESTRICTED", batch="NEG", qty=Decimal(-1)))


def test_expiry_of_a_reversed_receipt_never_condemns_the_stock(env):
    """Defect 5a: the expiry sweep took the earliest expiry of every receipt of a lot, including receipts that were reversed."""
    from app.pic.models import GoodsReceipt
    _, gr1, _ = _receive(env, "INL-B", 6, batch="B-REV", expiry=date(2026, 12, 31), plant=P2)
    with env.act("recv", at(TODAY, 11)) as s:
        receiving.reverse_gr(s, s.get(GoodsReceipt, gr1), "Wrong expiry keyed")
    _receive(env, "INL-B", 6, batch="B-REV", expiry=date(2027, 12, 31), plant=P2)
    with env.act("admin", at(date(2027, 2, 1), 10)) as s:
        expired = [i for i in ind_healthcare.expired_stock(s, date(2027, 2, 1)) if i["stock"].batch == "B-REV"]
        assert expired == []
        assert stock_ledger.batch_expiry(s, M["INL-B"], ["B-REV"]) == {"B-REV": date(2027, 12, 31)}


def test_stock_changing_commands_check_the_users_plants(env):
    """Defect 5b: consignment withdrawal, expiry write-off, usage decision, reversal and recall changed stock of plants the user is not assigned to."""
    from app.pic.models import GoodsReceipt
    _receive(env, "INL-CONS", 10, purchase_type="CONSIGNMENT", batch="", plant=P1)
    with env.act("recv2", at(TODAY, 12)) as s:       # assigned to P200 only
        refused = _problem(lambda: receiving.withdraw_consignment(s, material="INL-CONS", plant=P1, qty="1", usage_ref="CASE-1", purpose="TRANSFER"))
        assert refused.status == 403 and refused.rule_ref == "ABAC"
    with env.act("recv", at(TODAY, 12)) as s:        # assigned to both: allowed
        assert receiving.withdraw_consignment(s, material="INL-CONS", plant=P1, qty="1", usage_ref="CASE-1", purpose="TRANSFER")["qty"] == "1"
    _, gr_id, _ = _receive(env, "INL-A", 2, plant=P1)
    with env.act("recv2", at(TODAY, 13)) as s:
        assert _problem(lambda: receiving.reverse_gr(s, s.get(GoodsReceipt, gr_id), "Not my plant")).status == 403
    _, grq, _ = _receive(env, "INL-Q", 5, plant=P1, quality=True)
    with tenant_tx(env.tenant_id) as s:
        lot_id = s.execute(select(InspectionLot.id).where(InspectionLot.gr_id == grq)).scalar_one()
    with env.act("qi2", at(TODAY, 14)) as s:
        assert _problem(lambda: receiving.usage_decision(s, s.get(InspectionLot, lot_id), accepted=Decimal(5), rejected=Decimal(0))).status == 403
    _receive(env, "INL-B", 3, batch="B-OLD", expiry=date(2026, 12, 1), plant=P1)
    with env.act("qi2", at(date(2027, 1, 5), 10)) as s:
        assert _problem(lambda: ind_healthcare.write_off_expired(s, "January sweep")).status == 403
    with env.act("qi", at(date(2027, 1, 5), 10)) as s:
        done = ind_healthcare.write_off_expired(s, "January sweep")
        assert any(w["batch"] == "B-OLD" for w in done["writtenOff"])


# ================================================================ reads
def _stock_up(env):
    """A small, known position for the read tests (opening balances posted through the ledger)."""
    _pin(TODAY)
    _receive(env, "INL-SAFE", 20, plant=P2)                                   # below its safety stock of 50
    _receive(env, "INL-B", 8, batch="B-EXP", expiry=date(2026, 11, 25), plant=P2)   # expires in 21 days
    _receive(env, "INL-B", 5, batch="B-LATE", expiry=date(2027, 6, 30), plant=P2)
    with env.act("admin", at(TODAY, 11)) as s:
        for batch, qty in (("B-LATE", "2"),):
            stock_ledger.post_movement(s, material_id=M["INL-B"], plant=P2, sloc="0001", stock_type="UNRESTRICTED", batch=batch, qty=-Decimal(qty),
                                       movement="344", ref_type="TEST", ref_id=uuid.uuid4(), ref="BLK-1")
            stock_ledger.post_movement(s, material_id=M["INL-B"], plant=P2, sloc="0001", stock_type="BLOCKED", batch=batch, qty=Decimal(qty),
                                       movement="344", ref_type="TEST", ref_id=uuid.uuid4(), ref="BLK-1", reason_code="DAMAGED")
        # demand and no stock: a stock-out
        s.add(DemandElement(tenant_id=env.tenant_id, material_id=M["INL-NP"], plant=P2, type="SALES_ORDER", reference="SO-INL-1", req_date=TODAY + timedelta(days=5),
                            qty=Decimal(10), changed_at=clock.now()))
        s.add(PlanningParameter(tenant_id=env.tenant_id, material_id=M["INL-A"], plant=P1, reorder_point=Decimal(100), max_stock=Decimal(300)))


def test_stock_list_filters_pagination_and_plant_scope(env, client, login):
    _stock_up(env)
    _pin(TODAY, 12)
    ic = _h(login, "ic")
    everything = client.get("/v1/stock?limit=200", headers=ic).json()
    assert everything["nextCursor"] is None and all(r["qty"] != "0" for r in everything["items"])
    row = next(r for r in everything["items"] if r["material"] == "INL-SAFE")
    assert row["plant"] == P2 and row["qty"] == "20" and row["safetyStock"] == "50" and row["belowSafety"] is True and row["valueMinor"] == 200_000
    assert row["uom"] == "EA" and row["unitPriceMinor"] == 10_000 and row["stockType"] == "UNRESTRICTED"
    batch = next(r for r in everything["items"] if r["batch"] == "B-EXP")
    assert batch["expiry"] == "2026-11-25" and batch["daysToExpiry"] == 21
    # filters
    assert {r["material"] for r in client.get("/v1/stock?material=INL-S&limit=200", headers=ic).json()["items"]} >= {"INL-SAFE", "INL-S"}
    assert {r["plant"] for r in client.get(f"/v1/stock?plant={P2}&limit=200", headers=ic).json()["items"]} == {P2}
    assert {r["stockType"] for r in client.get("/v1/stock?stock_type=BLOCKED&limit=200", headers=ic).json()["items"]} == {"BLOCKED"}
    assert [r["batch"] for r in client.get("/v1/stock?batch=B-LATE&stock_type=UNRESTRICTED", headers=ic).json()["items"]] == ["B-LATE"]
    assert {r["material"] for r in client.get("/v1/stock?belowSafety=true&limit=200", headers=ic).json()["items"]} == {"INL-SAFE"}
    expiring = client.get("/v1/stock?expiringWithinDays=30&limit=200", headers=ic).json()["items"]
    assert {r["batch"] for r in expiring} == {"B-EXP"}
    assert client.get("/v1/stock?material=%25&limit=5", headers=ic).json()["items"] == []     # a LIKE wildcard is text, not a pattern
    assert client.get("/v1/stock?material_group=GENERAL&storage_location=0001&limit=200", headers=ic).status_code == 200
    # cursor pagination
    first = client.get("/v1/stock?limit=2", headers=ic).json()
    assert len(first["items"]) == 2 and first["nextCursor"]
    second = client.get(f"/v1/stock?limit=2&cursor={first['nextCursor']}", headers=ic).json()
    assert not {r["id"] for r in first["items"]} & {r["id"] for r in second["items"]}
    assert client.get("/v1/stock?cursor=garbage", headers=ic).status_code == 400
    # a zero balance is hidden unless asked for
    with env.act("admin", at(TODAY, 13)) as s:
        stock_ledger.post_movement(s, material_id=M["INL-A"], plant=P2, sloc="0001", stock_type="UNRESTRICTED", batch="", qty=Decimal(1), movement="561",
                                   ref_type="TEST", ref_id=uuid.uuid4(), ref="Z-1")
        stock_ledger.post_movement(s, material_id=M["INL-A"], plant=P2, sloc="0001", stock_type="UNRESTRICTED", batch="", qty=Decimal(-1), movement="551",
                                   ref_type="TEST", ref_id=uuid.uuid4(), ref="Z-2")
    assert not [r for r in client.get(f"/v1/stock?plant={P2}&material=INL-A&limit=50", headers=ic).json()["items"]]
    assert [r for r in client.get(f"/v1/stock?plant={P2}&material=INL-A&onlyNonZero=false&limit=50", headers=ic).json()["items"]]
    # plant scope: the P200-only receiver sees P200, and P100 is refused outright
    recv2 = _h(login, "recv2")
    assert {r["plant"] for r in client.get("/v1/stock?limit=200", headers=recv2).json()["items"]} == {P2}
    denied = client.get(f"/v1/stock?plant={P1}", headers=recv2)
    assert denied.status_code == 403 and denied.json()["ruleRef"] == "ABAC"
    assert client.get("/v1/stock", headers={}).status_code == 401


def test_stock_summary(env, client, login):
    _pin(TODAY, 12)
    ic = _h(login, "ic")
    s = client.get("/v1/stock/summary", headers=ic).json()
    assert {"UNRESTRICTED", "BLOCKED", "QUALITY"} <= set(s["byType"]) or {"UNRESTRICTED", "BLOCKED"} <= set(s["byType"])
    assert s["blockedValueMinor"] == 20_000 and s["stockValueMinor"] > 0 and P2 in s["byPlant"]
    assert s["expiring"]["within30"]["rows"] == 1 and s["expiring"]["within90"]["rows"] == 0 and s["expiring"]["expired"]["rows"] == 0
    assert s["belowSafetyCount"] == 1 and s["stockOutCount"] >= 1 and "daysOfCover" in s
    assert set(s["qualityHold"]["ageBucketsDays"]) == {"0-2", "3-7", ">7"} and s["openReservations"]["count"] == 0
    # the stock-out count is the KPI's definition
    for plant, expected in ((P2, 1), (P1, 0)):    # INL-NP has demand at P200 and no stock there; its three pieces at P100 are not a stock-out
        kpi = next(i for i in client.get(f"/v1/kpis?module=M02&trend=false&plant={plant}", headers=ic).json()["items"] if i["code"].endswith("STOCKOUTS"))
        only = client.get(f"/v1/stock/summary?plant={plant}", headers=ic).json()
        assert int(Decimal(kpi["value"])) == only["stockOutCount"] == expected and set(only["byPlant"]) <= {plant}
    assert client.get(f"/v1/stock/summary?plant={P1}", headers=_h(login, "recv2")).status_code == 403


def test_stock_alerts(env, client, login):
    _pin(TODAY, 12)
    ic = _h(login, "ic")
    # an aged quality hold (open lot, 9 days), an old block and a ledger drift
    _receive(env, "INL-Q", 7, plant=P2, quality=True, day=TODAY - timedelta(days=9))
    _pin(TODAY, 12)
    with tenant_tx(env.tenant_id) as s:
        drift = s.execute(select(Stock).where(Stock.material_id == M["INL-SAFE"], Stock.plant == P2)).scalar_one()
        drift.qty = drift.qty + Decimal(3)      # a direct edit of a balance: the ledger no longer explains it
    body = client.get("/v1/stock/alerts?limit=200", headers=ic).json()
    kinds = {a["type"] for a in body["items"]}
    assert {"STOCK_OUT", "BELOW_SAFETY", "BELOW_REORDER", "EXPIRING", "QUALITY_HOLD_AGED", "NEGATIVE_DRIFT"} <= kinds, kinds
    assert body["countsByType"]["STOCK_OUT"] >= 1 and body["total"] == len(body["items"])
    severities = [a["severity"] for a in body["items"]]
    assert severities == sorted(severities, key=lambda x: ["CRITICAL", "HIGH", "MEDIUM", "LOW"].index(x))
    by = {a["type"]: a for a in body["items"]}
    assert by["STOCK_OUT"]["material"] == "INL-NP" and by["STOCK_OUT"]["object"] == {"type": "MATERIAL", "ref": "INL-NP"} and by["STOCK_OUT"]["severity"] == "CRITICAL"
    assert by["QUALITY_HOLD_AGED"]["object"]["type"] == "INSPECTION_LOT" and by["QUALITY_HOLD_AGED"]["object"]["ref"].startswith("QL-")
    assert by["EXPIRING"]["batch"] == "B-EXP" and by["EXPIRING"]["severity"] == "HIGH"
    assert by["BELOW_REORDER"]["material"] == "INL-A" and by["NEGATIVE_DRIFT"]["material"] == "INL-SAFE"
    assert {a["type"] for a in client.get("/v1/stock/alerts?type=STOCK_OUT", headers=ic).json()["items"]} == {"STOCK_OUT"}
    page = client.get("/v1/stock/alerts?limit=2", headers=ic).json()
    assert len(page["items"]) == 2 and page["nextCursor"]
    assert client.get(f"/v1/stock/alerts?limit=2&cursor={page['nextCursor']}", headers=ic).json()["items"][0]["id"] != page["items"][0]["id"]
    # later: the early expiry has passed, the blocked stock is old
    _pin(date(2026, 12, 20), 12)
    later = {a["type"] for a in client.get("/v1/stock/alerts?limit=200", headers=ic).json()["items"]}
    assert {"EXPIRED", "BLOCKED_AGED"} <= later
    with tenant_tx(env.tenant_id) as s:   # put the balance right again for the later tests
        fixed = s.execute(select(Stock).where(Stock.material_id == M["INL-SAFE"], Stock.plant == P2)).scalar_one()
        fixed.qty = fixed.qty - Decimal(3)
    _pin(TODAY, 12)


def test_stock_card_has_the_mrp02_requirements_profile(env, client, login):
    _pin(TODAY, 12)
    ic = _h(login, "ic")
    card = client.get(f"/v1/stock/materials/INL-NP?plant={P2}", headers=ic).json()
    profile = next(p for p in card["requirements"] if p["plant"] == P2)
    assert profile["demand"] == "10" and profile["onHand"] == "0" and profile["requirements"][0]["reference"] == "SO-INL-1"
    assert profile["buckets"][0]["projected"] == "-10" and profile["buckets"][0]["shortage"] is True
    assert card["valuation"]["standardPriceMinor"] is None
    a = client.get("/v1/stock/materials/INL-A", headers=ic).json()
    p1 = next(p for p in a["requirements"] if p["plant"] == P1)
    assert p1["reorderPoint"] == "100" and p1["maxStock"] == "300"
    assert Decimal(p1["available"]) == Decimal(p1["onHand"]) + Decimal(p1["openPo"]) + Decimal(p1["inTransit"]) + Decimal(p1["firmPlannedReceipts"])   # TD 9.1
    assert Decimal(p1["openPo"]) == 3 and p1["receipts"][0]["kind"] == "OPEN_PO"       # the order of the reversed receipt is open again
    assert a["material"]["number"] == "INL-A" and a["byType"]["UNRESTRICTED"]["qty"] and a["valuation"]["ownStockValueMinor"] > 0
    assert a["movements"] and {"movementText", "valueMinor", "reference", "actor"} <= set(a["movements"][0])
    assert client.get("/v1/stock/materials/NO-SUCH", headers=ic).status_code == 404
    assert client.get(f"/v1/stock/materials/INL-A?plant={P1}", headers=_h(login, "recv2")).status_code == 403


def test_movement_ledger_filters_and_csv_export(env, client, login):
    _pin(TODAY, 12)
    ic = _h(login, "ic")
    page = client.get("/v1/stock/movements?limit=200", headers=ic).json()
    assert page["items"] and page["items"][0]["createdAt"] >= page["items"][-1]["createdAt"]
    grs = client.get("/v1/stock/movements?movement_type=101&limit=200", headers=ic).json()["items"]
    assert grs and {m["movementType"] for m in grs} == {"101"} and all(m["qty"] and not m["qty"].startswith("-") for m in grs)
    assert grs[0]["movementText"] == "Goods receipt" and grs[0]["reference"]["type"] == "GOODS_RECEIPT" and grs[0]["actor"]["email"].endswith(DOMAIN)
    blocked = client.get("/v1/stock/movements?movement_type=344&stock_type=BLOCKED&material=INL-B", headers=ic).json()["items"]
    assert len(blocked) == 1 and blocked[0]["reasonCode"] == "DAMAGED" and blocked[0]["valueMinor"] == 20_000
    by_ref = client.get(f"/v1/stock/movements?reference={grs[0]['reference']['ref']}", headers=ic).json()["items"]
    assert by_ref and {m["reference"]["ref"] for m in by_ref} == {grs[0]["reference"]["ref"]}
    assert client.get(f"/v1/stock/movements?plant={P2}&limit=200", headers=ic).json()["items"]
    assert client.get("/v1/stock/movements?date_from=2030-01-01", headers=ic).json()["items"] == []
    today_only = client.get(f"/v1/stock/movements?date_from={TODAY}&date_to={TODAY}&limit=200", headers=ic).json()["items"]
    assert today_only and all(m["createdAt"].startswith(TODAY.isoformat()) for m in today_only)
    two = client.get("/v1/stock/movements?limit=2", headers=ic).json()
    assert len(two["items"]) == 2 and two["nextCursor"]
    exported = client.get(f"/v1/stock/movements/export?movement_type=101&plant={P1}", headers=ic)
    assert exported.status_code == 200 and exported.headers["content-type"].startswith("text/csv") and "attachment" in exported.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(exported.text)))
    assert rows[0][:4] == ["Posted at", "Material", "Description", "UoM"] and len(rows) - 1 == int(exported.headers["X-Row-Count"]) >= 1
    assert exported.headers["X-Truncated"] == "false" and len(exported.headers["X-Content-SHA256"]) == 64
    with tenant_tx(env.tenant_id) as s:
        from app.pic.models import AuditEvent
        assert s.execute(select(func.count()).select_from(AuditEvent).where(AuditEvent.object_type == "STOCK_LEDGER_EXPORT")).scalar_one() >= 1
    assert client.get("/v1/stock/movements/export?plant=P100", headers=_h(login, "recv2")).status_code == 403


def test_consignment_stock_counts_as_supply_but_quality_stock_does_not(env, client, login):
    """Product decision of 2 Nov 2026 (extends TD 9.1): supplier-owned consignment stock is available supply for MRP, the stock card and the
    stock-out alert; quality and blocked stock are not. It is not part of the own-stock value or days of cover (the liability arises at withdrawal)."""
    _pin(TODAY, 12)
    ic = _h(login, "ic")
    with env.act("ic", at(TODAY, 10)) as s:   # a posting needs a signed-in user
        for number in ("INL-CSUP", "INL-QSUP"):
            m = Material(tenant_id=env.tenant_id, number=number, description=f"Ledger test {number}", type="STOCK", material_group="GENERAL", category="GENERAL",
                         base_uom="EA", mrp_type="PD", lot_size_policy="EXACT", safety_stock=Decimal(0), planned_delivery_days=3, gr_processing_days=0,
                         standard_price_minor=10_000, status="ACTIVE", hsn_code="8708", gst_rate=Decimal(18))
            s.add(m)
            s.flush()
            M[number] = m.id
        for number, stock_type in (("INL-CSUP", "CONSIGNMENT"), ("INL-QSUP", "QUALITY")):
            stock_ledger.post_movement(s, material_id=M[number], plant=P2, sloc="0001", stock_type=stock_type, batch="", qty=Decimal(50), movement="101",
                                       ref_type="TEST", ref_id=uuid.uuid4(), ref="CS-1")
            s.add(DemandElement(tenant_id=env.tenant_id, material_id=M[number], plant=P2, type="SALES_ORDER", reference=f"SO-{number}",
                                req_date=TODAY + timedelta(days=5), qty=Decimal(30), changed_at=clock.now()))
    consignment = client.get(f"/v1/stock/materials/INL-CSUP?plant={P2}", headers=ic).json()
    profile = next(p for p in consignment["requirements"] if p["plant"] == P2)
    assert profile["onHand"] == "50" and profile["buckets"][0]["shortage"] is False
    quality = client.get(f"/v1/stock/materials/INL-QSUP?plant={P2}", headers=ic).json()
    assert next(p for p in quality["requirements"] if p["plant"] == P2)["onHand"] == "0"
    outs = {a["material"] for a in client.get("/v1/stock/alerts?type=STOCK_OUT&limit=200", headers=ic).json()["items"]}
    assert "INL-CSUP" not in outs and "INL-QSUP" in outs
    with tenant_tx(env.tenant_id) as s:   # remove the demand again: later tests count stock-outs
        for row in s.execute(select(DemandElement).where(DemandElement.reference.in_(("SO-INL-CSUP", "SO-INL-QSUP")))).scalars():
            s.delete(row)
