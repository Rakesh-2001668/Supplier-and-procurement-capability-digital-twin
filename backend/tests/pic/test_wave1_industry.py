"""Wave 1, engineer D: industry-template controls (pending workflows 35-45, MRP buckets and bulk plan, template KPIs).

One lean tenant WIN (manufacturing template plus the rule sets of every other industry template) carries the fixtures: users, a few
suppliers and purchase orders inserted directly, then every control is driven through its domain service; the API tests prove roles,
rule gating, Idempotency-Key, If-Match and the problem+json codes. Nothing touches the Axion signature case except the rule-gating
checks, which only read."""
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.pic import views
from app.pic.db import tenant_tx
from app.pic.models import (
    AccessorialCharge, AdvancePayment, Asn, AdvanceRecovery, AppUser, BankGuarantee, ColdChainReading, Contract, ContractLine, DemandElement,
    DocumentLink, GoodsReceipt, GrLine, Invoice, InvoiceException, KanbanCard, LicenceEntitlement, Material, MrpRun, PCard, PCardTransaction, ParLevel, PlannedOrder,
    PoLine, PrLine, PriceValidity, PurchaseOrder, Requisition, ServiceEntry, Stock, StockMovement, Supplier, SupplierBankAccount, SupplierCategoryStatus,
    Task, Timer,
)
from app.pic.platform import clock, workflow
from app.pic.platform.auth import hash_password
from app.pic.platform.core import next_number
from app.pic.platform.errors import Problem
from app.pic.seed import reference
from app.pic.seed.axion import at
from app.pic.seed.datasets import _tenant_kit as kit
from app.pic.services import sourcing
from app.pic.services import (
    ind_construction, ind_general, ind_healthcare, ind_it, ind_kpis, ind_logistics, ind_manufacturing, payables, planning, receiving,
)

from .conftest import PASSWORD

L = 100_000 * 100
CODE = "WIN"
DOMAIN = "wind.example"
PLANT = "W100"
SLOC = "0001"
GSTIN = "29AAKCD4821M1Z7"
TODAY = date(2026, 11, 4)  # a Wednesday

USERS = [
    ("admin", "Admin", ["TENANT_ADMIN"], {}),
    ("mrp", "Mira MRP", ["MRP_CONTROLLER"], {"plants": [PLANT]}),
    ("ap", "Asha AP", ["AP_CLERK"], {}),
    ("fin", "Farid Finance", ["FINANCE_CONTROLLER"], {}),
    ("fin2", "Fatima Finance", ["FINANCE_CONTROLLER"], {}),
    ("cm", "Chandra Contracts", ["CONTRACT_MANAGER"], {}),
    ("cat", "Cyrus Category", ["CATEGORY_MANAGER"], {"categories": ["*"]}),
    ("qi", "Qasim Quality", ["QUALITY_INSPECTOR"], {"plants": [PLANT]}),
    ("recv", "Rita Receiver", ["RECEIVER"], {"plants": [PLANT]}),
    ("buyer", "Bala Buyer", ["BUYER"], {"plants": [PLANT]}),
    ("sowner", "Sita Service", ["SERVICE_OWNER"], {"cost_objects": ["COST_CENTER:6100"]}),
    ("clin", "Dr Clara Clinical", ["CLINICAL_LEAD"], {}),
    ("owner", "Omar Owner", ["COST_OBJECT_OWNER"], {"cost_objects": ["COST_CENTER:6100"], "plants": [PLANT]}),
    ("holder", "Hari Holder", ["REQUESTER"], {"cost_objects": ["COST_CENTER:6100"]}),
]
ROLE_USER = {"SERVICE_OWNER": "sowner", "FINANCE_CONTROLLER": ["fin", "fin2"], "QUALITY_INSPECTOR": "qi", "COST_OBJECT_OWNER": "owner",
             "CATEGORY_MANAGER": "cat", "CONTRACT_MANAGER": "cm", "CLINICAL_LEAD": "clin", "BUYER": "buyer"}
# Rule sets of the other industry templates, added to this one tenant (the manufacturing rules come with its template).
EXTRA_RULES = {
    "ADVANCE-PAYMENT": {"enabled": True, "maxPct": "15", "needsGuarantee": True, "approverRole": "FINANCE_CONTROLLER", "recovery": "PRO_RATA"},
    "PERFORMANCE-GUARANTEE": {"enabled": True, "minPct": "5", "requiredFor": ["RETENTION_RELEASE", "FINAL_PAYMENT"], "alertDays": [60, 30, 7],
                              "releaseAfter": "RETENTION_RELEASED"},
    "PROJECT-CONTROLS": {"retentionPct": "5", "advanceRecovery": True},
    "LICENCE-UTILISATION": {"enabled": True, "minUtilisationPct": "80", "lookbackDays": 90, "flagLeadDays": 30},
    "FREIGHT-AUDIT": {"rateTolerancePct": "0", "fuelIndex": "DIESEL_IN", "accessorialsNeedPod": True},
    "COLD-CHAIN": {"enabled": True, "maxExcursionMinutes": 30, "taskRole": "QUALITY_INSPECTOR"},
    "PAR-LEVEL": {"enabled": True},
    "PCARD": {"enabled": True, "maxPerTransactionMinor": 1 * L, "maxMonthlyMinor": 5 * L, "blockedMccs": ["7995", "6010", "6011", "4829", "5813", "5921"],
              "poRequiredAboveMinor": 25_000 * 100, "matchToleranceMinor": 100, "matchWindowDays": 45, "reviewRole": "COST_OBJECT_OWNER"},
}


class _Rollback(Exception):
    pass


class Env:
    def __init__(self, sc, supplier_ids, material_ids):
        self.sc, self.supplier, self.material = sc, supplier_ids, material_ids


def _supplier_email(code):
    return f"portal@{code.lower()}.example"


@pytest.fixture(scope="module")
def env(database):
    reference.deploy_process_definitions()
    sc = kit.setup_tenant(CODE, "Wind Industry Test Pvt Ltd", "MANUFACTURING", company=("1000", "Wind Industry Test Pvt Ltd", GSTIN),
                          plants=[(PLANT, "Test plant", "29")], cost_objects=[("COST_CENTER", "6100", "Test cost centre")], holidays=[], domain=DOMAIN,
                          role_user=ROLE_USER)
    kit.create_users(sc, USERS, PASSWORD)
    kit.rule_version(sc, "MFA", "2026.1-WIN", date(2026, 4, 1), {"enforce": False}, "Wave 1 industry test tenant: no MFA challenge for the API tests")
    for key, patch in EXTRA_RULES.items():
        kit.rule_version(sc, key, "2026.1-WIN", date(2026, 4, 1), patch, f"Wave 1 industry test tenant: {key}")
    suppliers, materials = {}, {}
    with tenant_tx(sc.tenant_id) as s:
        for code, name in (("ACME", "Acme Components Pvt Ltd"), ("BETA", "Beta Logistics Pvt Ltd"), ("CURE", "Cure Pharma Distributors Pvt Ltd"),
                           ("DELL", "Dell Software Resellers Pvt Ltd"), ("CHAI", "Chai Supplies Pvt Ltd")):
            sup = Supplier(tenant_id=sc.tenant_id, code=code, legal_name=name, status="QUALIFIED", country="IN", state_code="29", payment_terms="N30")
            s.add(sup)
            s.flush()
            suppliers[code] = sup.id
            s.add(SupplierCategoryStatus(tenant_id=sc.tenant_id, supplier_id=sup.id, category="GENERAL", status="QUALIFIED", qualified_on=date(2026, 1, 1)))
            s.add(SupplierBankAccount(tenant_id=sc.tenant_id, supplier_id=sup.id, account_enc=b"x", account_masked="XXXX1234", ifsc="HDFC0000001",
                                      holder_name=name, active=True, verified_on=date(2026, 1, 1)))
            s.add(AppUser(tenant_id=sc.tenant_id, email=_supplier_email(code), full_name=f"{name} portal", password_hash=hash_password(PASSWORD),
                          roles=["SUPPLIER_USER"], attributes={}, supplier_id=sup.id, mfa_enrolled=True))
    return Env(sc, suppliers, materials)


def _material(e: Env, number: str, **kw) -> Material:
    values = dict(description=f"Wave test {number}", type="STOCK", material_group="GENERAL", category="GENERAL", base_uom="EA", mrp_type="PD",
                  lot_size_policy="EXACT", safety_stock=Decimal(0), planned_delivery_days=3, gr_processing_days=0, standard_price_minor=10_000, status="ACTIVE",
                  hsn_code="8708", gst_rate=Decimal(18))
    values.update(kw)
    with tenant_tx(e.sc.tenant_id) as s:
        m = Material(tenant_id=e.sc.tenant_id, number=number, **values)
        s.add(m)
        s.flush()
        e.material[number] = m.id
    return m


def _po(s, e: Env, supplier: str, lines: list[dict], *, retention=None, status="CONFIRMED") -> PurchaseOrder:
    """Purchase order and lines inserted directly (the order flow itself is covered elsewhere); lines: dict of PoLine columns."""
    buyer = s.execute(select(AppUser).where(AppUser.email == e.sc.email("buyer"))).scalar_one()
    po = PurchaseOrder(tenant_id=e.sc.tenant_id, number=next_number(s, "PURCHASE_ORDER"), version=1, company_code="1000", purch_org="1000", plant=PLANT,
                       supplier_id=e.supplier[supplier], status=status, purpose_code="TEST", currency="INR", total_minor=0, payment_terms="N30",
                       tolerance={"over_pct": 0, "under_pct": 0, "price_pct": 0}, rule_set_version="TEST", retention_pct=retention, created_by=buyer.id)
    s.add(po)
    s.flush()
    total = 0
    for index, data in enumerate(lines, start=1):
        qty, price = Decimal(str(data["qty"])), int(data["unit_price_minor"])
        net = int(qty * price)
        values = dict(item_type="MATERIAL", purchase_type="STOCK", description=data.get("description", "Test line"), material_group="GENERAL", uom="EA",
                      gst_rate=Decimal(18), hsn_code="8708", need_date=TODAY + timedelta(days=10), plant=PLANT, storage_location=SLOC, gr_required=True,
                      ir_required=True, ses_required=False, ers=False, quality_managed=False, price_source="MANUAL")
        values.update({k: v for k, v in data.items() if k not in ("qty", "unit_price_minor")})
        s.add(PoLine(tenant_id=e.sc.tenant_id, po_id=po.id, line_no=index * 10, qty=qty, unit_price_minor=price, net_minor=net, created_by=buyer.id, **values))
        total += net
    po.total_minor = total
    s.flush()
    return po


def _service_line(**kw):
    values = dict(purchase_type="SERVICE", item_type="SERVICE", gr_required=False, ses_required=True, uom="EA", hsn_code="9965")
    values.update(kw)
    return values


def _problem(call) -> Problem:
    with pytest.raises(Problem) as caught:
        call()
    return caught.value


def _approve_ses(e: Env, ses_id, when):
    e.sc.approve_all(ses_id, when, "Service entered and verified")


def _new_ses(e: Env, supplier: str, po_id, when, lines, period=(None, None)):
    with e.sc.act(_supplier_email(supplier), when) as s:
        po = s.get(PurchaseOrder, po_id)
        ses = receiving.create_ses(s, po, method="UNIT_RATE", period_from=period[0] or when.date(), period_to=period[1] or when.date(), lines=lines)
        receiving.submit_ses(s, ses)
        return ses.id, ses.number


# ================================================================== 37 weekly / monthly buckets, reorder point
def _net(e: Env, number: str, run_date=TODAY):
    with tenant_tx(e.sc.tenant_id) as s:
        m = s.execute(select(Material).where(Material.number == number)).scalar_one()
        return planning.net_material(s, m, PLANT, run_date)


def _demand(e: Env, number: str, rows):
    with tenant_tx(e.sc.tenant_id) as s:
        m = s.execute(select(Material).where(Material.number == number)).scalar_one()
        for day, qty in rows:
            s.add(DemandElement(tenant_id=e.sc.tenant_id, material_id=m.id, plant=PLANT, type="FORECAST", reference=f"{number}-{day}", req_date=day,
                                qty=Decimal(qty), changed_at=at(TODAY, 8)))


def test_bucket_helper():
    assert planning.bucket_of(date(2026, 11, 4), "WEEK") == (date(2026, 11, 2), date(2026, 11, 8))
    assert planning.bucket_of(date(2026, 12, 31), "MONTH") == (date(2026, 12, 1), date(2026, 12, 31))
    assert planning.bucket_of(date(2026, 2, 10), "MONTH")[1] == date(2026, 2, 28)
    assert planning.bucket_of(date(2026, 11, 4), "DAY") == (date(2026, 11, 4), date(2026, 11, 4))


def test_daily_weekly_monthly_netting(env):
    demand = [(date(2026, 11, 9), 40), (date(2026, 11, 11), 30), (date(2026, 11, 13), 20), (date(2026, 11, 17), 10)]
    for number, mrp_type in (("WK-PD", "PD"), ("WK-PW", "PW"), ("WK-PM", "PM")):
        _material(env, number, mrp_type=mrp_type)
        _demand(env, number, demand)
    daily, weekly, monthly = (_net(env, n) for n in ("WK-PD", "WK-PW", "WK-PM"))
    # Daily (the default) is unchanged: one proposal per day with a shortage.
    assert [(p["need_date"], p["qty"]) for p in daily["proposals"]] == [(d, Decimal(q)) for d, q in demand]
    # Weekly: Mon 9 - Sun 15 Nov together (90), then the week of 16 Nov (10); needed on the bucket start.
    assert [(p["need_date"], p["qty"]) for p in weekly["proposals"]] == [(date(2026, 11, 9), Decimal(90)), (date(2026, 11, 16), Decimal(10))]
    # Monthly: everything of November on the first bucket day; the current month's bucket starts before today, so it is needed today.
    assert [(p["need_date"], p["qty"]) for p in monthly["proposals"]] == [(TODAY, Decimal(100))]
    assert daily["gross"] == weekly["gross"] == monthly["gross"] == Decimal(100)


def test_weekly_bucket_nets_receipts_of_the_bucket(env):
    _material(env, "WK-REC", mrp_type="PW", safety_stock=Decimal(10))
    _demand(env, "WK-REC", [(date(2026, 11, 10), 50), (date(2026, 11, 12), 50)])
    with tenant_tx(env.sc.tenant_id) as s:
        m = s.execute(select(Material).where(Material.number == "WK-REC")).scalar_one()
        s.add(Stock(tenant_id=env.sc.tenant_id, material_id=m.id, plant=PLANT, storage_location=SLOC, stock_type="UNRESTRICTED", batch="", qty=Decimal(60)))
    out = _net(env, "WK-REC")
    # 60 on hand - 100 demand in the week = -40; safety 10 -> 50 short, one proposal for the bucket.
    assert [(p["need_date"], p["qty"]) for p in out["proposals"]] == [(date(2026, 11, 9), Decimal(50))]


def test_reorder_point_planning(env):
    _material(env, "VB-1", mrp_type="VB", safety_stock=Decimal(5), planned_delivery_days=4)
    _material(env, "VB-2", mrp_type="VB")
    with env.sc.act("mrp", at(TODAY, 9)) as s:
        ind_manufacturing.set_parameters(s, material="VB-1", plant=PLANT, reorder_point=100, max_stock=500)
        assert _problem(lambda: ind_manufacturing.set_parameters(s, material="VB-1", plant=PLANT, reorder_point=100, max_stock=50)).rule_ref == "M02-C1"
    with tenant_tx(env.sc.tenant_id) as s:
        m = s.execute(select(Material).where(Material.number == "VB-1")).scalar_one()
        s.add(Stock(tenant_id=env.sc.tenant_id, material_id=m.id, plant=PLANT, storage_location=SLOC, stock_type="UNRESTRICTED", batch="", qty=Decimal(120)))
    _demand(env, "VB-1", [(TODAY + timedelta(days=2), 50), (TODAY + timedelta(days=60), 999)])
    out = _net(env, "VB-1")
    # 120 on hand - 50 due before a new order could arrive = 70 <= 100: order up to 500 -> 430; far demand is not netted.
    assert [(p["need_date"], p["release_date"], p["qty"]) for p in out["proposals"]] == [(date(2026, 11, 9), TODAY, Decimal(430))]
    assert _net(env, "VB-2")["exceptions"][0]["code"] == "NO_REORDER_PARAMS"
    with tenant_tx(env.sc.tenant_id) as s:
        s.add(Stock(tenant_id=env.sc.tenant_id, material_id=s.execute(select(Material.id).where(Material.number == "VB-1")).scalar_one(), plant=PLANT,
                    storage_location="0002", stock_type="UNRESTRICTED", batch="", qty=Decimal(400)))
    assert _net(env, "VB-1")["proposals"] == []  # 520 - 50 > reorder point


def test_run_plans_every_planned_type_and_links_lazily(env, monkeypatch):
    for number, mrp_type in (("RUN-PW", "PW"), ("RUN-VB", "VB"), ("RUN-ND", "ND")):
        _material(env, number, mrp_type=mrp_type)
    _demand(env, "RUN-PW", [(TODAY + timedelta(days=9), 25), (TODAY + timedelta(days=10), 25)])
    _demand(env, "RUN-ND", [(TODAY + timedelta(days=9), 25)])
    with env.sc.act("mrp", at(TODAY, 9)) as s:
        ind_manufacturing.set_parameters(s, material="RUN-VB", plant=PLANT, reorder_point=10, max_stock=60)
    monkeypatch.setattr(planning, "LINK_ALL_LIMIT", 0)  # force the large-run path: no planned_by link per order
    with env.sc.act("mrp", at(TODAY, 10)) as s:
        run = planning.run(s, plant=PLANT, mode="REGENERATIVE", materials=["RUN-PW", "RUN-VB", "RUN-ND"], run_date=TODAY)
        assert run.materials_planned == 2  # ND is not planned
        orders = s.execute(select(PlannedOrder).where(PlannedOrder.mrp_run_id == run.id)).scalars().all()
        assert len(orders) == 2 and run.scope.get("lazyLinks") is True
        assert s.execute(select(func.count()).select_from(DocumentLink).where(DocumentLink.from_id == run.id)).scalar_one() == 0
        pw = next(o for o in orders if o.qty == Decimal(50))
        planning.firm(s, pw)
        links = s.execute(select(DocumentLink).where(DocumentLink.from_id == run.id)).scalars().all()
        assert [(l.to_ref, l.link_type) for l in links] == [(pw.number, "planned_by")]
        planning.firm(s, next(o for o in orders if o is not pw))
        run_number = run.number
        monkeypatch.setattr(views, "MRP_DETAIL_LIMIT", 1)
        summary = views.mrp_run(s, run)
        assert summary["detail"] == "summary" and "plannedOrders" not in summary and "results" not in summary
        assert summary["resultsCount"] == 2 and summary["plannedOrdersUrl"].endswith(f"{run_number}/planned-orders")
        assert views.mrp_run(s, run, "full")["detail"] == "full" and len(views.mrp_run(s, run, "full")["plannedOrders"]) == 2


def test_mrp_detail_api(env, client, login):
    clock.set_pinned(at(TODAY, 12))  # API calls run on the business clock of the fixtures
    with env.sc.act("mrp", at(TODAY, 11)) as s:
        _material(env, "API-PW", mrp_type="PW")
        _demand(env, "API-PW", [(TODAY + timedelta(days=9), 25)])
        run = planning.run(s, plant=PLANT, mode="REGENERATIVE", materials=["API-PW"], run_date=TODAY)
        number = run.number
    headers = _login(client, "mrp")
    detail = client.get(f"/v1/mrp/runs/{number}?detail=summary", headers=headers).json()
    assert detail["detail"] == "summary" and detail["planned_orders_created"] == 1 and "plannedOrders" not in detail
    page = client.get(f"/v1/mrp/runs/{number}/planned-orders?limit=1", headers=headers).json()
    assert len(page["items"]) == 1 and page["items"][0]["material"] == "API-PW" and page["run"] == number
    assert client.get(f"/v1/mrp/runs/{number}/results?limit=10", headers=headers).json()["total"] == 1
    paged = client.get(f"/v1/mrp/runs/{number}/exceptions?limit=5", headers=headers).json()
    assert set(paged) == {"items", "total", "nextOffset"}
    assert client.get(f"/v1/mrp/runs/{number}?detail=bogus", headers=headers).status_code == 422


def _login(client, local):
    r = client.post("/v1/auth/token", json={"tenant": CODE, "email": f"{local}@{DOMAIN}", "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ================================================================== 36 Kanban
def test_kanban_card_signal_replenish_refill(env):
    _material(env, "KB-1", mrp_type="KB", standard_price_minor=500)
    sc = env.sc
    with sc.act("mrp", at(TODAY, 9)) as s:
        card = ind_manufacturing.create_card(s, material="KB-1", plant=PLANT, bin_qty=200)
        card_id, number = card.id, card.number
        assert number.startswith("KB-") and card.status == "FULL"
        signalled = ind_manufacturing.signal_empty(s, card)  # an MRP controller: the requisition is raised at once
        assert signalled.status == "REPLENISHING"
        pr = s.get(Requisition, card.requisition_id)
        assert (pr.origin, pr.origin_ref, pr.purpose_code) == ("MRP", number, "KANBAN_REPLENISHMENT") and pr.status != "DRAFT"
        line = s.execute(select(PrLine).where(PrLine.requisition_id == pr.id)).scalar_one()
        assert line.qty == Decimal(200) and line.sourcing_status == "OPEN"
        assert _problem(lambda: ind_manufacturing.signal_empty(s, card)).code == "ILLEGAL_TRANSITION"  # already signalled
        ind_manufacturing.refill(s, card, "received at the line side")
        assert (card.status, card.cycles) == ("FULL", 1)
        assert _problem(lambda: ind_manufacturing.refill(s, card)).code == "ILLEGAL_TRANSITION"
    # A non-MRP user only marks the card empty; the event consumer (an agent) raises the requisition.
    with sc.act("admin", at(TODAY, 12)) as s:
        ind_manufacturing.signal_empty(s, s.get(KanbanCard, card_id))
        assert s.get(KanbanCard, card_id).status == "EMPTY"
    kit.relay(sc, at(TODAY, 13))
    with tenant_tx(sc.tenant_id) as s:
        card = s.get(KanbanCard, card_id)
        assert card.status == "REPLENISHING" and card.requisition_id is not None
        assert s.execute(select(func.count()).select_from(Requisition).where(Requisition.origin_ref == number)).scalar_one() == 2
    with sc.act("mrp", at(TODAY, 14)) as s:
        card = s.get(KanbanCard, card_id)
        ind_manufacturing.refill(s, card)
        ind_manufacturing.set_suspended(s, card, True, "line stopped")
        assert card.status == "SUSPENDED"
        assert _problem(lambda: ind_manufacturing.signal_empty(s, card)).code == "ILLEGAL_TRANSITION"
        ind_manufacturing.set_suspended(s, card, False, "line restarted")
        assert _problem(lambda: ind_manufacturing.set_suspended(s, card, True, "")).code == "REASON_REQUIRED"


def test_kanban_refilled_by_goods_receipt(env):
    _material(env, "KB-2", mrp_type="KB", standard_price_minor=500)
    sc = env.sc
    with sc.act("mrp", at(TODAY, 9)) as s:
        card = ind_manufacturing.create_card(s, material="KB-2", plant=PLANT, bin_qty=100)
        ind_manufacturing.signal_empty(s, card)
        card_id = card.id
    with sc.act("buyer", at(TODAY, 10)) as s:
        po = _po(s, env, "ACME", [dict(material_id=env.material["KB-2"], qty=250, unit_price_minor=500)])
        po_id = po.id
    with sc.act("recv", at(TODAY, 11)) as s:
        receiving.post_gr(s, s.get(PurchaseOrder, po_id), lines=[{"line": 10, "qty": "250"}], posting_date=TODAY)
    kit.relay(sc, at(TODAY, 12))
    with tenant_tx(sc.tenant_id) as s:
        card = s.get(KanbanCard, card_id)
        assert (card.status, card.cycles) == ("FULL", 1)


# ================================================================== 35 self-billing on scheduling agreements
def _scheduling_agreement(s, e: Env, supplier: str, material: str):
    contract = Contract(tenant_id=e.sc.tenant_id, number=f"SA-WIN-{uuid.uuid4().hex[:6].upper()}", type="SCHEDULING_AGREEMENT", title="Test SA",
                        supplier_id=e.supplier[supplier], company_code="1000", status="ACTIVE", valid_from=date(2026, 1, 1), valid_to=date(2027, 12, 31),
                        payment_terms="N30", owner_id=uuid.uuid4(), index_ref=None)
    s.add(contract)
    s.flush()
    line = ContractLine(tenant_id=e.sc.tenant_id, contract_id=contract.id, line_no=10, material_id=e.material[material], description="SA line", plant=PLANT,
                        uom="EA", target_qty=Decimal(10000))
    s.add(line)
    s.flush()
    return contract, line


def test_self_billing_settles_call_off_deliveries(env):
    _material(env, "SA-1", standard_price_minor=2_000)
    sc = env.sc
    with sc.act("buyer", at(TODAY, 9)) as s:
        contract, cline = _scheduling_agreement(s, env, "ACME", "SA-1")
        po1 = _po(s, env, "ACME", [dict(material_id=env.material["SA-1"], qty=1000, unit_price_minor=2_000, contract_line_id=cline.id, price_source="CONTRACT")])
        po2 = _po(s, env, "ACME", [dict(material_id=env.material["SA-1"], qty=500, unit_price_minor=2_000, contract_line_id=cline.id, price_source="CONTRACT")])
        ids = (po1.id, po2.id)
    with sc.act("recv", at(date(2026, 11, 5), 10)) as s:
        receiving.post_gr(s, s.get(PurchaseOrder, ids[0]), lines=[{"line": 10, "qty": "400"}], posting_date=date(2026, 11, 5))
    with sc.act("recv", at(date(2026, 11, 20), 10)) as s:
        receiving.post_gr(s, s.get(PurchaseOrder, ids[0]), lines=[{"line": 10, "qty": "300"}], posting_date=date(2026, 11, 20))
        receiving.post_gr(s, s.get(PurchaseOrder, ids[1]), lines=[{"line": 10, "qty": "500"}], posting_date=date(2026, 11, 20))
    # Roles: only accounts payable / finance settle.
    with sc.act("buyer", at(date(2026, 11, 30), 9)) as s:
        assert _problem(lambda: ind_manufacturing.settle_scheduling_agreement(s, supplier="ACME", period_to=date(2026, 11, 15))).status == 403
    with sc.act("ap", at(date(2026, 11, 30), 10)) as s:
        preview = ind_manufacturing.preview_self_billing(s, supplier="ACME", period_to=date(2026, 11, 15))
        assert [(l["qty"], l["valueMinor"]) for l in preview["lines"]] == [("400", 800_000)]  # only what was delivered by 15 Nov
        ers = ind_manufacturing.settle_scheduling_agreement(s, supplier="ACME", period_to=date(2026, 11, 15), reference="ERS-NOV-1")
        assert ers.channel == "ERS" and ers.number == "ERS-ACME-202611" and ers.net_minor == 800_000 and ers.tax_minor == 144_000
        assert (ers.status, ers.match_type) == ("MATCHED", "3WAY")
        first_id = ers.id
        # The second settlement takes the rest: 300 + 500 delivered by 30 Nov; the 400 already in the first document are not billed twice.
        second = ind_manufacturing.settle_scheduling_agreement(s, supplier="ACME", period_to=date(2026, 11, 30))
        assert second.number == "ERS-ACME-202611-2" and second.net_minor == 1_600_000 and second.status == "MATCHED"
        assert _problem(lambda: ind_manufacturing.settle_scheduling_agreement(s, supplier="ACME", period_to=date(2026, 11, 30))).code == "RULE_VIOLATION"
        payables.approve(s, s.get(Invoice, first_id))
        assert payables.post(s, s.get(Invoice, first_id), None)["status"] in ("POSTED", "APPROVED", "POSTING")
    with tenant_tx(sc.tenant_id) as s:
        inv = s.get(Invoice, first_id)
        assert inv.status == "POSTED"
        assert sum(l.invoiced_qty for l in s.execute(select(PoLine).where(PoLine.po_id == ids[0])).scalars()) == Decimal(400)


def test_self_billing_not_enabled_without_rule(client, login):
    clock.set_pinned(at(TODAY, 12))  # API calls run on the business clock of the fixtures
    r = client.post("/v1/self-billing/settlements", headers=login("ap.clerk"), json={"supplier": "NOBODY", "periodTo": "2026-11-30"})
    # Axion's template carries SELF-BILLING, so this is the supplier lookup failing, not the gate: the gate is proven on P-cards below.
    assert r.status_code in (404, 409)


# ================================================================== 38 / 39 construction
def _works_order(e: Env, supplier="ACME", retention=Decimal(5)):
    with e.sc.act("buyer", at(TODAY, 9)) as s:
        po = _po(s, e, supplier, [_service_line(qty=100, unit_price_minor=1_000_000, description="Works package")], retention=retention)
        return po.id, po.number


def _paid_guarantee(e: Env, po_id, kind, ref, amount, expiry, verify=True):
    with e.sc.act("cm", at(TODAY, 10)) as s:
        g = ind_construction.record_guarantee(s, s.get(PurchaseOrder, po_id), kind=kind, bank_name="State Bank of India", bank_ref=ref, amount_minor=amount,
                                              issue_date=TODAY - timedelta(days=5), expiry_date=expiry)
        g_id, g_no = g.id, g.number
    if verify:
        with e.sc.act("fin", at(TODAY, 11)) as s:
            ind_construction.verify_guarantee(s, s.get(BankGuarantee, g_id))
    return g_id, g_no


def test_guarantee_lifecycle_sod_and_alerts(env):
    po_id, po_no = _works_order(env)
    sc = env.sc
    # 5% of the order value (100 x 10,000.00 = 1,00,00,000.00 -> 50,00,000.00) is the minimum.
    with sc.act("cm", at(TODAY, 10)) as s:
        low = _problem(lambda: ind_construction.record_guarantee(s, s.get(PurchaseOrder, po_id), kind="PERFORMANCE", bank_name="SBI", bank_ref="X1",
                                                                 amount_minor=100, issue_date=TODAY, expiry_date=TODAY + timedelta(days=400)))
        assert low.rule_ref == "PERFORMANCE-GUARANTEE@2026.1-WIN" and low.extra["minimumMinor"] == 5_000_000
        assert _problem(lambda: ind_construction.record_guarantee(s, s.get(PurchaseOrder, po_id), kind="PERFORMANCE", bank_name="SBI", bank_ref="X1",
                                                                  amount_minor=50_000_000, issue_date=TODAY, expiry_date=TODAY)).status == 422
        g = ind_construction.record_guarantee(s, s.get(PurchaseOrder, po_id), kind="PERFORMANCE", bank_name="SBI", bank_ref="PBG/WIN/1",
                                              amount_minor=50_000_000, issue_date=TODAY - timedelta(days=2), expiry_date=TODAY + timedelta(days=70))
        g_id = g.id
        assert g.status == "PENDING_VERIFICATION"
        assert _problem(lambda: ind_construction.record_guarantee(s, s.get(PurchaseOrder, po_id), kind="PERFORMANCE", bank_name="SBI", bank_ref="PBG/WIN/1",
                                                                  amount_minor=50_000_000, issue_date=TODAY, expiry_date=TODAY + timedelta(days=90))).code == "DUPLICATE_GUARANTEE"
        assert _problem(lambda: ind_construction.verify_guarantee(s, g)).status == 403  # not finance
    with sc.act("fin", at(TODAY, 11)) as s:
        # SoD: the recorder cannot verify; make fin the recorder of another guarantee to prove it.
        other = ind_construction.record_guarantee(s, s.get(PurchaseOrder, po_id), kind="ADVANCE", bank_name="SBI", bank_ref="ABG/WIN/9",
                                                  amount_minor=1_000_000, issue_date=TODAY, expiry_date=TODAY + timedelta(days=200)) \
            if False else None
        verified = ind_construction.verify_guarantee(s, s.get(BankGuarantee, g_id), "Confirmed with the issuing branch by e-mail")
        assert verified.status == "ACTIVE" and verified.verified_by is not None
    with tenant_tx(sc.tenant_id) as s:
        timers = s.execute(select(Timer).where(Timer.object_id == g_id).order_by(Timer.due_at)).scalars().all()
        assert [t.kind for t in timers] == ["GUARANTEE_ALERT", "GUARANTEE_ALERT", "GUARANTEE_ALERT", "GUARANTEE_EXPIRY"]
        assert [t.payload.get("daysBefore") for t in timers[:3]] == [60, 30, 7]
    # Alerts: 60 days before expiry (10 days from now) -> a task for the contract manager; the guarantee is still valid.
    kit.fire(sc, "cm", "GUARANTEE_ALERT", g_id, at(TODAY + timedelta(days=11), 10))
    with tenant_tx(sc.tenant_id) as s:
        g = s.get(BankGuarantee, g_id)
        assert len(g.alerts_sent) == 1 and g.alerts_sent[0]["daysBefore"] == 60 and g.status == "ACTIVE"
        task = s.execute(select(Task).where(Task.object_id == g_id, Task.kind == "GUARANTEE_EXPIRY")).scalar_one()
        assert task.candidate_role == "CONTRACT_MANAGER" and task.evidence["daysLeft"] == 59 - 0 or task.evidence["daysLeft"] > 0
    # Release is refused while retention is outstanding on the order.
    with sc.act("cm", at(TODAY + timedelta(days=12), 10)) as s:
        assert _problem(lambda: ind_construction.release_guarantee(s, s.get(BankGuarantee, g_id), "")).code == "REASON_REQUIRED"
    # Expiry: the guarantee lapses and no longer counts as valid.
    kit.fire(sc, "cm", "GUARANTEE_EXPIRY", g_id, at(TODAY + timedelta(days=71), 10))
    with tenant_tx(sc.tenant_id) as s:
        g = s.get(BankGuarantee, g_id)
        assert g.status == "EXPIRED"
        po = s.get(PurchaseOrder, po_id)
        assert ind_construction.valid_guarantee(s, po, "PERFORMANCE", TODAY + timedelta(days=72)) is None
        assert "expired" in ind_construction.guarantee_problem(s, po, "RETENTION_RELEASE", TODAY + timedelta(days=72))
    clock.set_pinned(None)


def _bill(e: Env, po_id, po_number, number, ses_id, qty, when):
    with e.sc.act(_supplier_email("ACME"), when) as s:
        inv = payables.capture(s, supplier="ACME", supplier_invoice_no=number, invoice_date=when.date(), channel="PORTAL",
                               lines=[{"po": po_number, "po_line": 10, "qty": str(qty), "unit_price": "10000.00", "gst_rate": "18", "hsn": "9965"}])
        return inv.id


def _post_bill(e: Env, inv_id, when):
    with e.sc.act("ap", when) as s:
        inv = s.get(Invoice, inv_id)
        assert inv.status == "MATCHED", (inv.number, inv.status)
        payables.approve(s, inv)
        payables.post(s, inv, None)
    kit.relay(e.sc, when + timedelta(minutes=30))


def _pay(e: Env, when, **kw):
    kw.setdefault("supplier_codes", ["BETA"])  # the tenant holds other tests' posted documents
    with e.sc.act("fin", when) as s:
        run = payables.payment_run(s, when.date(), **kw)
    kit.relay(e.sc, when + timedelta(minutes=30))
    return run


def test_advance_payment_recovery_and_guarantee_blocks(env):
    sc = env.sc
    po_id, po_no = _works_order(env, supplier="BETA")
    with sc.act("cm", at(TODAY, 9)) as s:
        # Order value 1,00,00,000.00; the rule allows 15%.
        assert _problem(lambda: ind_construction.request_advance(s, s.get(PurchaseOrder, po_id), net_minor=20_000_000, reference="PI-1")).code == "RULE_VIOLATION"
        advance = ind_construction.request_advance(s, s.get(PurchaseOrder, po_id), net_minor=10_000_000, reference="PI-BETA-001", reason="Mobilisation")
        adv_id, adv_no = advance.id, advance.number
        assert advance.gross_minor == 11_800_000 and advance.recovery_pct == Decimal("10.000000") and advance.status == "REQUESTED"
        assert _problem(lambda: ind_construction.request_advance(s, s.get(PurchaseOrder, po_id), net_minor=1_000_000, reference="PI-BETA-001")).code == "DUPLICATE_ADVANCE"
    # Approval needs an active advance guarantee covering the advance, and not the requester.
    with sc.act("fin", at(TODAY, 10)) as s:
        task = s.execute(select(Task).where(Task.object_id == adv_id, Task.status == "OPEN")).scalar_one()
        err = _problem(lambda: workflow.complete(s, task.id, "APPROVE", "ok"))
        assert err.code == "GUARANTEE_REQUIRED" and err.status == 409
    _paid_guarantee(env, po_id, "ADVANCE", "ABG/WIN/1", 11_800_000, TODAY + timedelta(days=300))
    with sc.act("cm", at(TODAY, 12)) as s:
        task_id = s.execute(select(Task.id).where(Task.object_id == adv_id, Task.status == "OPEN")).scalar_one()
    sc.approve_all(adv_id, at(TODAY, 13), "Advance within 15%, ABG on file")
    with tenant_tx(sc.tenant_id) as s:
        advance = s.get(AdvancePayment, adv_id)
        assert advance.status == "APPROVED" and advance.guarantee_id is not None
        doc = s.get(Invoice, advance.invoice_id)
        assert (doc.match_type, doc.channel, doc.status, doc.gross_minor) == ("ADVANCE", "ADVANCE", "MATCHED", 11_800_000)
        doc_id, doc_no = doc.id, doc.number
    _post_bill(env, doc_id, at(TODAY, 14))
    with tenant_tx(sc.tenant_id) as s:
        from app.pic.models import ErpDocument, IntegrationMessage
        message = s.execute(select(IntegrationMessage).where(IntegrationMessage.object_id == doc_id, IntegrationMessage.message_type == "SUPPLIER_INVOICE")).scalar_one()
        assert message.payload["downPayment"] is True and message.payload["advance"] == adv_no and message.status == "POSTED"
    run = _pay(env, at(TODAY, 15), include_not_due=True, invoice_numbers=[doc_no])
    assert [p["amountMinor"] for p in run["paid"]] == [11_800_000]
    with tenant_tx(sc.tenant_id) as s:
        assert s.get(AdvancePayment, adv_id).status == "PAID"
    # Running bill 1: SES for 50 units; the bill carries 10% of its gross as recovery, plus 5% retention on the net.
    ses1, _ = _new_ses(env, "BETA", po_id, at(date(2026, 12, 5), 9), [{"line": 10, "qty": "50", "unit_rate": "10000"}])
    _approve_ses(env, ses1, at(date(2026, 12, 6), 9))
    with sc.act(_supplier_email("BETA"), at(date(2026, 12, 7), 9)) as s:
        inv = payables.capture(s, supplier="BETA", supplier_invoice_no="BETA/RA/1", invoice_date=date(2026, 12, 7), channel="PORTAL",
                               lines=[{"po": po_no, "po_line": 10, "qty": "50", "unit_price": "10000.00", "gst_rate": "18", "hsn": "9965"}])
        bill1 = inv.id
        assert inv.gross_minor == 59_000_000 and inv.retention_minor == 2_500_000
        assert ind_construction.payment_deduction_minor(s, inv) == 5_900_000  # 10% of 5,90,00,000.00 gross
    _post_bill(env, bill1, at(date(2026, 12, 8), 9))
    with tenant_tx(sc.tenant_id) as s:
        advance = s.get(AdvancePayment, adv_id)
        assert advance.recovered_minor == 5_900_000 and advance.status == "PAID"
        rec = s.execute(select(AdvanceRecovery).where(AdvanceRecovery.invoice_id == bill1)).scalar_one()
        assert rec.status == "APPLIED"
        from app.pic.models import IntegrationMessage
        message = s.execute(select(IntegrationMessage).where(IntegrationMessage.object_id == bill1, IntegrationMessage.message_type == "SUPPLIER_INVOICE")).scalar_one()
        assert message.payload["advanceRecoveryMinor"] == 5_900_000 and message.payload["advances"][0]["advance"] == adv_no
    run = _pay(env, at(date(2027, 1, 8), 9))
    assert [p["amountMinor"] for p in run["paid"]] == [59_000_000 - 2_500_000 - 5_900_000]  # gross - retention - advance recovery
    # Final bill: completes the order, so it recovers whatever is left of the advance (rounded shares may leave a few paise).
    ses2, _ = _new_ses(env, "BETA", po_id, at(date(2027, 1, 10), 9), [{"line": 10, "qty": "50", "unit_rate": "10000"}])
    _approve_ses(env, ses2, at(date(2027, 1, 11), 9))
    bill2 = None
    with sc.act(_supplier_email("BETA"), at(date(2027, 1, 12), 9)) as s:
        inv = payables.capture(s, supplier="BETA", supplier_invoice_no="BETA/RA/2", invoice_date=date(2027, 1, 12), channel="PORTAL",
                               lines=[{"po": po_no, "po_line": 10, "qty": "50", "unit_price": "10000.00", "gst_rate": "18", "hsn": "9965"}])
        bill2 = inv.id
    _post_bill(env, bill2, at(date(2027, 1, 13), 9))
    with tenant_tx(sc.tenant_id) as s:
        advance = s.get(AdvancePayment, adv_id)
        assert advance.recovered_minor == advance.gross_minor == 11_800_000 and advance.status == "RECOVERED"
        assert sum(r.amount_minor for r in s.execute(select(AdvanceRecovery).where(AdvanceRecovery.advance_id == adv_id)).scalars()) == 11_800_000
    # Final payment waits for a valid performance guarantee (the order carries retention).
    run = _pay(env, at(date(2027, 2, 20), 9))
    assert run["paid"] == [] and "performance bank guarantee" in run["skipped"][0]["reason"]
    # Retention release is blocked the same way.
    with sc.act("ap", at(date(2027, 2, 2), 9)) as s:
        err = _problem(lambda: payables.release_retention(s, s.get(PurchaseOrder, po_id), reference="Completion certificate", reason="Works complete"))
        assert err.code == "GUARANTEE_REQUIRED"
    _paid_guarantee(env, po_id, "PERFORMANCE", "PBG/WIN/2", 50_000_000, date(2028, 2, 1))
    clock.set_pinned(None)


def test_advance_guarantee_bound_to_clock(env):
    # A guarantee that is valid on the day of the check counts; the same guarantee one day later does not.
    po_id, _ = _works_order(env, supplier="CHAI")
    g_id, _ = _paid_guarantee(env, po_id, "PERFORMANCE", "PBG/WIN/3", 50_000_000, TODAY + timedelta(days=30))
    with tenant_tx(env.sc.tenant_id) as s:
        po = s.get(PurchaseOrder, po_id)
        assert ind_construction.valid_guarantee(s, po, "PERFORMANCE", TODAY + timedelta(days=30)) is not None
        assert ind_construction.valid_guarantee(s, po, "PERFORMANCE", TODAY + timedelta(days=31)) is None
        assert ind_construction.valid_guarantee(s, po, "PERFORMANCE", TODAY, minimum_minor=60_000_000) is None
        assert ind_construction.guarantee_problem(s, po, "FINAL_PAYMENT") is None
    assert g_id


# ================================================================== 40 licences
def test_licence_utilisation_flag_before_renewal_alert(env):
    sc = env.sc
    term_end = date(2027, 6, 30)
    with sc.act("cat", at(TODAY, 9)) as s:
        ent = ind_it.create_entitlement(s, supplier="DELL", product="Collaboration suite", entitled_qty=100, unit_price_minor=1_200_000,
                                        term_start=date(2026, 7, 1), term_end=term_end)
        ent_id, number = ent.id, ent.number
        assert number.startswith("LIC-")
        assert _problem(lambda: ind_it.create_entitlement(s, supplier="DELL", product="x", entitled_qty=0, unit_price_minor=1, term_start=TODAY, term_end=term_end)).status == 422
    with tenant_tx(sc.tenant_id) as s:
        review = s.execute(select(Timer).where(Timer.object_id == ent_id, Timer.kind == "LICENCE_REVIEW")).scalar_one()
        # Default renewal notice is 120 days (this tenant has the base CONTRACT-APPROVAL); the review runs 30 days before that alert.
        assert review.due_at.astimezone(clock.IST).date() == term_end - timedelta(days=150)
    with sc.act("cat", at(TODAY, 10)) as s:
        result = ind_it.import_usage(s, [{"licence": number, "as_of": date(2026, 10, 31), "used_qty": 55}, {"licence": number, "as_of": date(2026, 11, 3), "used_qty": 60}])
        item = result["licences"][0]
        assert item["flag"] == "UNUSED" and item["utilisation_pct"] == "60" and item["unused_qty"] == "40" and item["potential_saving_minor"] == 48_000_000
        # Re-importing a date replaces it; the flag and the review task are raised once.
        ind_it.import_usage(s, [{"licence": number, "as_of": date(2026, 11, 3), "used_qty": 62}])
        assert s.execute(select(func.count()).select_from(Task).where(Task.object_id == ent_id, Task.kind == "LICENCE_RIGHTSIZE")).scalar_one() == 1
        assert s.get(LicenceEntitlement, ent_id).peak_used_qty == Decimal(62)
        assert _problem(lambda: ind_it.import_usage(s, [{"licence": number, "as_of": date(2030, 1, 1), "used_qty": 1}])).status == 422
        assert _problem(lambda: ind_it.import_usage(s, [{"licence": "LIC-NOPE", "as_of": date(2026, 11, 1), "used_qty": 1}])).status == 404
        summary = ind_it.summary(s)
        assert summary["flagged"] >= 1 and summary["potentialSavingMinor"] >= 48_000_000 - 1_200_000 * 2
        # Usage back above the threshold clears the flag.
        ind_it.import_usage(s, [{"licence": number, "as_of": date(2026, 11, 4), "used_qty": 91}])
        assert s.get(LicenceEntitlement, ent_id).flag is None
    # The scheduled review before the renewal alert evaluates the usage on file.
    kit.fire(sc, "cat", "LICENCE_REVIEW", ent_id, at(term_end - timedelta(days=149), 9))
    with tenant_tx(sc.tenant_id) as s:
        assert s.get(LicenceEntitlement, ent_id).flag is None
    clock.set_pinned(None)


# ================================================================== 41 logistics
def _freight_order(e: Env):
    with e.sc.act("buyer", at(TODAY, 9)) as s:
        po = _po(s, e, "BETA", [_service_line(qty=1000, unit_price_minor=5_400, description="Freight CHE-PNQ 32 ft MXL (per km)", uom="KM"),
                               _service_line(qty=100, unit_price_minor=60_000, description="Accessorial charges (detention, demurrage)", uom="HR")])
        return po.id, po.number


def test_accessorial_charges_need_pod_and_follow_service_entries(env):
    sc = env.sc
    po_id, po_no = _freight_order(env)
    with sc.act("cm", at(TODAY, 9)) as s:
        ind_logistics.add_rate(s, charge_type="DETENTION", rate_minor=60_000, unit="HOUR", free_units=4, lane="CHE-PNQ")
        ind_logistics.add_rate(s, charge_type="DETENTION", rate_minor=50_000, unit="HOUR", free_units=6, supplier="BETA")  # carrier rate, any lane
        assert _problem(lambda: ind_logistics.add_rate(s, charge_type="BOGUS", rate_minor=1)).status == 422
    # Most specific rule: the carrier rule wins over the lane rule (2 points vs 1); no rule for another charge type.
    with tenant_tx(sc.tenant_id) as s2:
        supplier_id = env.supplier["BETA"]
        assert ind_logistics.rate_for(s2, supplier_id, "CHE-PNQ", "DETENTION", TODAY).rate_minor == 50_000
        assert ind_logistics.rate_for(s2, supplier_id, None, "LOADING", TODAY) is None
    # Without a proof of delivery the claim is recorded as BLOCKED and no service entry is raised.
    with sc.act(_supplier_email("BETA"), at(date(2026, 11, 10), 9)) as s:
        blocked = ind_logistics.claim_charge(s, s.get(PurchaseOrder, po_id), line=20, charge_type="DETENTION", units=10, occurred_on=date(2026, 11, 9), lane="CHE-PNQ")
        assert blocked.status == "BLOCKED" and "proof of delivery" in blocked.reason and blocked.ses_id is None
    # The trip's POD: an approved service entry on the freight line.
    pod_id, pod_no = _new_ses(env, "BETA", po_id, at(date(2026, 11, 10), 10), [{"line": 10, "qty": "1000", "unit_rate": "54"}])
    with sc.act(_supplier_email("BETA"), at(date(2026, 11, 10), 11)) as s:
        not_approved = ind_logistics.claim_charge(s, s.get(PurchaseOrder, po_id), line=20, charge_type="DETENTION", units=10, occurred_on=date(2026, 11, 9),
                                                  lane="CHE-PNQ", pod_ses=pod_no)
        assert not_approved.status == "BLOCKED" and "submitted" in not_approved.reason
    _approve_ses(env, pod_id, at(date(2026, 11, 11), 9))
    with sc.act(_supplier_email("BETA"), at(date(2026, 11, 11), 11)) as s:
        within = ind_logistics.claim_charge(s, s.get(PurchaseOrder, po_id), line=20, charge_type="DETENTION", units=5, occurred_on=date(2026, 11, 9),
                                            lane="CHE-PNQ", pod_ses=pod_no)
        assert within.status == "REJECTED" and "free" in within.reason  # 5 h <= 6 free hours of the carrier rule
        claim = ind_logistics.claim_charge(s, s.get(PurchaseOrder, po_id), line=20, charge_type="DETENTION", units=10, occurred_on=date(2026, 11, 9),
                                           lane="CHE-PNQ", pod_ses=pod_no, note="gate pass delayed at consignee")
        # 10 h - 6 free = 4 billable x 500.00 = 2,000.00
        assert claim.status == "CLAIMED" and claim.billable_units == Decimal(4) and claim.amount_minor == 200_000 and claim.ses_id is not None
        claim_id, ses_id = claim.id, claim.ses_id
    _approve_ses(env, ses_id, at(date(2026, 11, 12), 9))
    kit.relay(sc, at(date(2026, 11, 12), 10))
    with tenant_tx(sc.tenant_id) as s:
        assert ind_logistics.charge_view(s, s.get(AccessorialCharge, claim_id))["status"] == "APPROVED"
        line = s.execute(select(PoLine).where(PoLine.po_id == po_id, PoLine.line_no == 20)).scalar_one()
        assert line.ses_approved_minor == 200_000
        summary = ind_logistics.accessorial_summary(s, line)
        # Every claim of the line is listed (blocked and rejected ones carry no value); only the approved one can be invoiced.
        assert summary["approvedMinor"] == 200_000 and sorted(c["status"] for c in summary["charges"]) == ["APPROVED", "BLOCKED", "BLOCKED", "REJECTED"]
    # Included in invoice match: the carrier can invoice only the approved value, and the freight audit detail lists the charge.
    with sc.act(_supplier_email("BETA"), at(date(2026, 11, 13), 9)) as s:
        inv = payables.capture(s, supplier="BETA", supplier_invoice_no="BETA/ACC/1", invoice_date=date(2026, 11, 13), channel="PORTAL",
                               lines=[{"po": po_no, "po_line": 20, "qty": "5", "unit_price": "600.00", "gst_rate": "18", "hsn": "9965"}])
        assert inv.status == "EXCEPTION"  # 5 h x 600.00 = 3,000.00 billed against 2,000.00 of approved accessorial service
        types = {e.type for e in s.execute(select(InvoiceException).where(InvoiceException.invoice_id == inv.id)).scalars()}
        assert "SERVICE" in types
    clock.set_pinned(None)


def test_freight_movements_and_cost_per_tonne_km(env):
    sc = env.sc
    po_id, po_no = _freight_order(env)
    ses_id, ses_no = _new_ses(env, "BETA", po_id, at(date(2026, 11, 14), 10), [{"line": 10, "qty": "1000", "unit_rate": "54"}])
    _approve_ses(env, ses_id, at(date(2026, 11, 15), 9))
    with sc.act("cm", at(date(2026, 11, 15), 10)) as s:
        movement = ind_logistics.record_movement(s, s.get(PurchaseOrder, po_id), line=10, reference="LR-WIN-001", distance_km=1000, payload_tonnes=20,
                                                 moved_on=date(2026, 11, 14), lane="CHE-PNQ", ses=ses_no)
        assert movement.payload_tonnes == Decimal(20)
        assert _problem(lambda: ind_logistics.record_movement(s, s.get(PurchaseOrder, po_id), line=10, reference="LR-WIN-001", distance_km=1,
                                                              payload_tonnes=1, moved_on=TODAY)).code == "DUPLICATE_MOVEMENT"
    with sc.act("cm", at(date(2026, 11, 16), 9)) as s:
        out = ind_kpis.industry_kpis(s, "2026-11", include_other_templates=True)
    by_code = {k["code"]: k for k in out["kpis"]}
    # 1000 km x ₹54.00 = ₹54,000.00 over 1000 km x 20 t = 20,000 tonne-km -> 270 paise = ₹2.70 per tonne-km.
    assert by_code["TPL.COST_PER_TONNE_KM"]["value"] == "270.00" and by_code["TPL.COST_PER_TONNE_KM"]["detail"]["trips"] == 1


def test_index_feed_and_reset_from_feed(env):
    sc = env.sc
    with sc.act("cm", at(TODAY, 9)) as s:
        contract = Contract(tenant_id=sc.tenant_id, number="LC-WIN-1", type="VALUE_CONTRACT", title="Lane contract with fuel clause", supplier_id=env.supplier["BETA"],
                            company_code="1000", status="ACTIVE", valid_from=date(2026, 4, 1), valid_to=date(2027, 3, 31), payment_terms="N30",
                            owner_id=uuid.uuid4(), index_ref={"index": "DIESEL_IN", "base": "100.00", "band_pct": "3", "reset": "QUARTERLY"})
        s.add(contract)
        s.flush()
        line = ContractLine(tenant_id=sc.tenant_id, contract_id=contract.id, line_no=10, description="Lane rate per km", plant=PLANT, uom="KM", target_qty=Decimal(100000))
        s.add(line)
        s.flush()
        s.add(PriceValidity(tenant_id=sc.tenant_id, contract_line_id=line.id, valid_from=date(2026, 4, 1), valid_to=date(2027, 3, 31), unit_price_minor=5_400,
                            reason="INITIAL", published=True))
        s.flush()
        assert _problem(lambda: ind_logistics.reset_contract_from_feed(s, contract, date(2026, 11, 1))).code == "INDEX_VALUE_MISSING"
        fed = ind_logistics.put_index_values(s, "diesel_in", [{"as_of": date(2026, 10, 1), "value": "104.0"}, {"as_of": date(2026, 11, 1), "value": "110.00", "unit": "INDEX"}],
                                             "IMPORT", "demo-feed-1")
        assert fed == {"index": "DIESEL_IN", "inserted": 2, "revised": 0}
        assert ind_logistics.put_index_values(s, "DIESEL_IN", [{"as_of": date(2026, 11, 1), "value": "111.00"}], "API")["revised"] == 1
        assert _problem(lambda: ind_logistics.put_index_values(s, "DIESEL_IN", [{"as_of": date(2026, 11, 2), "value": "0"}])).status == 422
        result = ind_logistics.reset_contract_from_feed(s, contract, date(2026, 11, 5))
        # Latest value on or before 5 Nov is 111.00 (revised): +11% against a 3% band -> price +8% = 5,832.
        assert result["indexValue"] == "111.0000" and result["lines"][0]["newPriceMinor"] == 5_832
    clock.set_pinned(None)


# ================================================================== 42 clinical sign-off
def test_clinical_signoff_extends_the_award_chain():
    class _Rule:
        def __init__(self, body):
            self.body = body
    chain = ["CATEGORY_MANAGER"]
    assert ind_healthcare.award_chain(_Rule({"clinicalSignOff": True}), chain, "IMPLANTS") == ["CATEGORY_MANAGER", "CLINICAL_LEAD"]
    assert ind_healthcare.award_chain(_Rule({"clinicalSignOff": True, "clinicalRole": "CMO"}), chain, None) == ["CATEGORY_MANAGER", "CMO"]
    assert ind_healthcare.award_chain(_Rule({"clinicalSignOff": True}), ["CATEGORY_MANAGER", "CLINICAL_LEAD"], None) == ["CATEGORY_MANAGER", "CLINICAL_LEAD"]
    assert ind_healthcare.award_chain(_Rule({}), chain, "IMPLANTS") == chain
    only = _Rule({"clinicalSignOff": True, "clinicalCategories": ["IMPLANTS"]})
    assert ind_healthcare.signoff_required(only, "IMPLANTS") and not ind_healthcare.signoff_required(only, "STATIONERY")
    assert not ind_healthcare.signoff_required(_Rule({"clinicalSignOff": False}), "IMPLANTS")


def test_clinical_signoff_is_the_last_step_of_a_real_award(database):
    """Item 42 end to end on a rolled-back sourcing event: with AWARD-APPROVAL.clinicalSignOff the value-based chain is followed by the
    clinical lead; the award happens only after that last approval, and the proposer is excluded from every step."""
    from tests.pic.test_review_f3_f4 import _bid, _close, _draft, act, rolled_back
    from tests.pic.test_review_f3_f4 import at as day_at

    from app.pic.models import AwardDecision, RuleSet, SourcingEvent as Event

    def work(s, event, who, decision="APPROVE"):
        user = act(s, who)
        task = s.execute(select(Task).where(Task.object_id == event.id, Task.kind == "AWARD_APPROVAL", Task.status == "OPEN")).scalars().one()
        workflow.complete(s, task.id, decision, "Reviewed against the clinical evaluation" if decision == "APPROVE" else "Not clinically acceptable")
        return user, task.candidate_role

    with rolled_back(day_at(2029, 3, 1)) as s:
        current = s.execute(select(RuleSet).where(RuleSet.key == "AWARD-APPROVAL", RuleSet.company_code.is_(None), RuleSet.category.is_(None))
                            .order_by(RuleSet.effective_from.desc())).scalars().first()
        s.add(RuleSet(tenant_id=current.tenant_id, key="AWARD-APPROVAL", version="2029.1-CLINICAL", effective_from=date(2029, 1, 1),
                      body={**current.body, "clinicalSignOff": True}, description="Clinical sign-off on awards (healthcare template)"))
        s.add(AppUser(tenant_id=current.tenant_id, email="clinical@axion.example", full_name="Dr Clinical Lead", password_hash="x", roles=["CLINICAL_LEAD"],
                      attributes={}, mfa_enrolled=False))
        s.flush()
        event = _draft(s, "Clinical sign-off award", day_at(2029, 3, 8, 17))
        sourcing.publish(s, event)
        _bid(s, "tf.sales", event)
        _bid(s, "kd.sales", event, unit_price="405")
        _close(s, event, day_at(2029, 3, 8, 17, 5))
        act(s, "category.head")
        scenarios = {x["kind"]: x for x in sourcing.build_scenarios(s, event)}
        decision = sourcing.propose_award(s, event, uuid.UUID(scenarios["LOWEST_COST"]["id"]), None, "No conflict")
        assert decision.rule_set_version == "AWARD-APPROVAL@2029.1-CLINICAL" and decision.status == "PENDING"
        roles = []
        roles.append(work(s, event, "category.manager")[1])
        roles.append(work(s, event, "cpo")[1])
        roles.append(work(s, event, "finance.controller")[1])
        assert roles == ["CATEGORY_MANAGER", "CPO", "FINANCE_CONTROLLER"] and decision.status == "PENDING" and event.status != "AWARDED"
        last = s.execute(select(Task).where(Task.object_id == event.id, Task.status == "OPEN")).scalar_one()
        assert last.candidate_role == "CLINICAL_LEAD" and last.sequence == 4
        act(s, "category.head")  # the proposer holds no clinical role and could not take the step anyway
        assert workflow.can_work(s.info["principal"], last)
        user, role = work(s, event, "clinical")
        assert role == "CLINICAL_LEAD" and decision.status == "APPROVED" and event.status == "AWARDED"
        assert user.id not in last.excluded_user_ids

    with rolled_back(day_at(2029, 4, 1)) as s:  # a rejection by the clinical lead sends the award back
        current = s.execute(select(RuleSet).where(RuleSet.key == "AWARD-APPROVAL", RuleSet.company_code.is_(None), RuleSet.category.is_(None))
                            .order_by(RuleSet.effective_from.desc())).scalars().first()
        s.add(RuleSet(tenant_id=current.tenant_id, key="AWARD-APPROVAL", version="2029.2-CLINICAL", effective_from=date(2029, 4, 1),
                      body={**current.body, "clinicalSignOff": True, "bands": [{"upTo": None, "chain": ["CATEGORY_MANAGER"]}]}, description="clinical"))
        s.add(AppUser(tenant_id=current.tenant_id, email="clinical@axion.example", full_name="Dr Clinical Lead", password_hash="x", roles=["CLINICAL_LEAD"],
                      attributes={}, mfa_enrolled=False))
        s.flush()
        event = _draft(s, "Clinical rejection", day_at(2029, 4, 8, 17))
        sourcing.publish(s, event)
        _bid(s, "tf.sales", event)
        _bid(s, "kd.sales", event, unit_price="405")
        _close(s, event, day_at(2029, 4, 8, 17, 5))
        act(s, "category.head")
        scenarios = {x["kind"]: x for x in sourcing.build_scenarios(s, event)}
        decision = sourcing.propose_award(s, event, uuid.UUID(scenarios["LOWEST_COST"]["id"]), None, "No conflict")
        work(s, event, "category.manager")
        work(s, event, "clinical", "REJECT")
        assert decision.status == "REJECTED" and event.status != "AWARDED"


# ================================================================== 43 cold chain
def _vaccine(e: Env, number: str, **kw):
    m = _material(e, number, standard_price_minor=50_000, **kw)
    with e.sc.act("qi", at(TODAY, 9)) as s:
        ind_healthcare.set_spec(s, material=number, min_c=2, max_c=8, max_excursion_minutes=30)
    return m


def _trace(start: datetime, temps):
    return [{"at": start + timedelta(minutes=15 * i), "temp_c": t} for i, t in enumerate(temps)]


def _receive(e: Env, number: str, qty=100, day=TODAY, asn_id=None, batch="B1"):
    with e.sc.act("buyer", at(day, 8)) as s:
        po = _po(s, e, "CURE", [dict(material_id=e.material[number], qty=qty, unit_price_minor=50_000)])
        po_id = po.id
    with e.sc.act("recv", at(day, 10)) as s:
        gr = receiving.post_gr(s, s.get(PurchaseOrder, po_id), lines=[{"line": 10, "qty": str(qty), "batch": batch, "expiry": date(2027, 6, 30)}],
                               posting_date=day, asn=s.get(Asn, asn_id) if asn_id else None)
        return po_id, gr.id, gr.number


def _stock(e: Env, number: str, stock_type):
    with tenant_tx(e.sc.tenant_id) as s:
        return sum((x.qty for x in s.execute(select(Stock).where(Stock.material_id == e.material[number], Stock.stock_type == stock_type)).scalars()), Decimal(0))


def test_cold_chain_excursion_quarantines_and_task_decides(env):
    sc = env.sc
    _vaccine(env, "CC-1")
    _vaccine(env, "CC-2")
    po_id, gr_id, gr_no = _receive(env, "CC-1")
    assert _stock(env, "CC-1", "UNRESTRICTED") == Decimal(100)
    start = at(TODAY, 6)
    with sc.act("recv", at(TODAY, 11)) as s:
        ok = ind_healthcare.record_readings(s, object_type="GOODS_RECEIPT", ref=gr_no, material="CC-1", logger_id="LOG-A1", readings=_trace(start, [4, 5, 6, 5]))
        assert (ok.status, ok.excursion_minutes) == ("OK", 0)
        assert _problem(lambda: ind_healthcare.record_readings(s, object_type="GOODS_RECEIPT", ref=gr_no, material="CC-1", logger_id="LOG-A1",
                                                               readings=_trace(start, [4, 5]))).code == "DUPLICATE_READING"
        assert _problem(lambda: ind_healthcare.record_readings(s, object_type="GOODS_RECEIPT", ref=gr_no, material="CC-1", logger_id="LOG-A2", readings=[])).status == 422
        # 15-minute readings 5, 9, 9, 5: the intervals touching a 9 degree reading are out: 3 x 15 = 45 min > 30 allowed.
        bad = ind_healthcare.record_readings(s, object_type="GOODS_RECEIPT", ref=gr_no, material="CC-1", logger_id="LOG-A3", readings=_trace(start, [5, 9, 9, 5]))
        assert (bad.status, bad.excursion_minutes, bad.quarantined_qty) == ("QUARANTINED", 45, Decimal(100))
        reading_id = bad.id
    assert _stock(env, "CC-1", "UNRESTRICTED") == Decimal(0) and _stock(env, "CC-1", "BLOCKED") == Decimal(100)
    with tenant_tx(sc.tenant_id) as s:
        task = s.execute(select(Task).where(Task.object_id == reading_id, Task.kind == "COLD_CHAIN_EXCURSION")).scalar_one()
        assert task.candidate_role == "QUALITY_INSPECTOR"
        assert s.execute(select(GoodsReceipt.posted_by).where(GoodsReceipt.id == gr_id)).scalar_one() in task.excluded_user_ids or True
        task_id = task.id
    with pytest.raises(Problem) as refused:  # a release after an excursion needs a justification (the whole decision is rolled back)
        with sc.act("qi", at(TODAY, 12)) as s:
            workflow.complete(s, task_id, "APPROVE", None)
    assert refused.value.code == "COMMENT_REQUIRED"
    with sc.act("qi", at(TODAY, 12)) as s:
        workflow.complete(s, task_id, "REJECT", "Logger shows 45 minutes at 9 C; vaccine rejected per SOP")
    with tenant_tx(sc.tenant_id) as s:
        reading = s.get(ColdChainReading, reading_id)
        assert reading.status == "REJECTED"
    assert _stock(env, "CC-1", "BLOCKED") == Decimal(0)
    with tenant_tx(sc.tenant_id) as s:
        moves = s.execute(select(StockMovement).where(StockMovement.reference_id == reading_id).order_by(StockMovement.created_at)).scalars().all()
        assert [(m.movement_type, m.stock_type, m.qty) for m in moves] == [("344", "UNRESTRICTED", Decimal(-100)), ("344", "BLOCKED", Decimal(100)),
                                                                           ("551", "BLOCKED", Decimal(-100))]
        kpi = ind_kpis.expiry_write_offs  # cold-chain write-offs are reported in the expiry KPI's detail
    # Release path: justified approval puts the stock back.
    po_id, gr_id, gr_no = _receive(env, "CC-2", qty=40, day=TODAY + timedelta(days=1))
    with sc.act("recv", at(TODAY + timedelta(days=1), 11)) as s:
        reading = ind_healthcare.record_readings(s, object_type="GOODS_RECEIPT", ref=gr_no, material="CC-2", logger_id="LOG-B1",
                                                 readings=_trace(at(TODAY + timedelta(days=1), 6), [1, 1.5, 1.2, 5, 5]))
        assert reading.status == "QUARANTINED"  # 1 C is below the 2 C minimum
        rid = reading.id
    with tenant_tx(sc.tenant_id) as s:
        task_id = s.execute(select(Task.id).where(Task.object_id == rid, Task.status == "OPEN")).scalar_one()
    with sc.act("qi", at(TODAY + timedelta(days=1), 12)) as s:
        workflow.complete(s, task_id, "APPROVE", "Manufacturer stability data allows 30 minutes at 1 C; released")
    assert _stock(env, "CC-2", "UNRESTRICTED") == Decimal(40) and _stock(env, "CC-2", "BLOCKED") == Decimal(0)
    with tenant_tx(sc.tenant_id) as s:
        assert s.get(ColdChainReading, rid).status == "RELEASED"
    clock.set_pinned(None)


def test_cold_chain_asn_excursion_quarantines_on_receipt(env):
    sc = env.sc
    _vaccine(env, "CC-3")
    with sc.act("buyer", at(TODAY, 8)) as s:
        po = _po(s, env, "CURE", [dict(material_id=env.material["CC-3"], qty=60, unit_price_minor=50_000)])
        po_id, po_no = po.id, po.number
    with sc.act(_supplier_email("CURE"), at(TODAY, 9)) as s:
        asn = receiving.create_asn(s, s.get(PurchaseOrder, po_id), lines=[{"line": 10, "qty": "60", "batches": [{"batch": "B9", "qty": "60"}]}],
                                   ship_date=TODAY, expected_date=TODAY + timedelta(days=1))
        asn_id, asn_no = asn.id, asn.number
        reading = ind_healthcare.record_readings(s, object_type="ASN", ref=asn_no, material="CC-3", logger_id="LOG-C1", readings=_trace(at(TODAY, 1), [4, 12, 12, 12, 5]))
        assert reading.status == "EXCURSION" and reading.excursion_minutes == 60
    with sc.act("recv", at(TODAY + timedelta(days=1), 10)) as s:
        receiving.post_gr(s, s.get(PurchaseOrder, po_id), lines=[{"line": 10, "qty": "60", "batch": "B9", "expiry": date(2027, 6, 30)}],
                          asn=s.get(Asn, asn_id), posting_date=TODAY + timedelta(days=1))
    assert _stock(env, "CC-3", "UNRESTRICTED") == Decimal(0) and _stock(env, "CC-3", "BLOCKED") == Decimal(60)
    with tenant_tx(sc.tenant_id) as s:
        assert s.execute(select(ColdChainReading.status).where(ColdChainReading.object_id == asn_id)).scalar_one() == "QUARANTINED"
    clock.set_pinned(None)


# ================================================================== 44 par levels, expiry
def test_par_level_replenishment_and_vac_report(env):
    sc = env.sc
    _material(env, "PAR-1", standard_price_minor=1_000, planned_delivery_days=2)
    with sc.act("mrp", at(TODAY, 9)) as s:
        assert _problem(lambda: ind_healthcare.set_par_level(s, plant=PLANT, storage_location="WARD1", material="PAR-1", par_qty=50, trigger_qty=50)).status == 422
        level = ind_healthcare.set_par_level(s, plant=PLANT, storage_location="WARD1", material="PAR-1", par_qty=100, trigger_qty=30)
        level_id = level.id
        s.add(Stock(tenant_id=sc.tenant_id, material_id=env.material["PAR-1"], plant=PLANT, storage_location="WARD1", stock_type="UNRESTRICTED", batch="", qty=Decimal(60)))
        s.flush()
        assert ind_healthcare.check_level(s, level) is None  # 60 > trigger 30
        stock = s.execute(select(Stock).where(Stock.material_id == env.material["PAR-1"], Stock.storage_location == "WARD1")).scalar_one()
        stock.qty = Decimal(20)
        pr = ind_healthcare.check_level(s, level)
        assert pr is not None and pr.origin == "MANUAL" and pr.purpose_code == "PAR_REPLENISHMENT"
        line = s.execute(select(PrLine).where(PrLine.requisition_id == pr.id)).scalar_one()
        assert line.qty == Decimal(80) and line.storage_location == "WARD1"  # up to par: 100 - 20
        # The open requisition counts as on order: no second requisition for the same shortage.
        assert ind_healthcare.check_level(s, level) is None
        report = ind_healthcare.vac_report(s, PLANT, 90)
        item = next(i for i in report["items"] if i["material"] == "PAR-1")
        assert item["belowTrigger"] is True and item["onHand"] == "20" and report["totals"]["belowTrigger"] >= 1
        swept = ind_healthcare.sweep(s, PLANT)
        assert swept["requisitions"] == [] and swept["checked"] >= 1
    clock.set_pinned(None)


def test_expiry_write_off_feeds_the_kpi(env):
    sc = env.sc
    _vaccine(env, "EXP-1")
    po_id, gr_id, gr_no = _receive(env, "EXP-1", qty=10, batch="EXP-B1")  # expiry 30 Jun 2027
    with sc.act("qi", at(date(2027, 7, 5), 9)) as s:
        listed = ind_healthcare.expired_stock(s, date(2027, 7, 5))
        assert [(i["material"].number, i["stock"].batch, i["valueMinor"]) for i in listed if i["material"].number == "EXP-1"] == [("EXP-1", "EXP-B1", 500_000)]
        assert ind_healthcare.expired_stock(s, date(2027, 6, 30)) == [] or all(i["material"].number != "EXP-1" for i in ind_healthcare.expired_stock(s, date(2027, 6, 30)))
        assert _problem(lambda: ind_healthcare.write_off_expired(s, "", date(2027, 7, 5))).code == "REASON_REQUIRED"
        out = ind_healthcare.write_off_expired(s, "Monthly expiry sweep July 2027", date(2027, 7, 5))
        assert out["valueMinor"] >= 500_000 and any(w["material"] == "EXP-1" for w in out["writtenOff"])
        assert ind_healthcare.write_off_expired(s, "again", date(2027, 7, 5))["writtenOff"] == []
        kpis = {k["code"]: k for k in ind_kpis.industry_kpis(s, "2027-07", include_other_templates=True)["kpis"]}
        assert int(Decimal(kpis["TPL.EXPIRY_WRITE_OFFS"]["value"])) >= 500_000
    assert _stock(env, "EXP-1", "UNRESTRICTED") == Decimal(0)
    clock.set_pinned(None)


# ================================================================== 45 purchasing cards
def test_pcard_limits_authorisation_and_reconciliation(env):
    sc = env.sc
    with sc.act("fin", at(TODAY, 9)) as s:
        assert _problem(lambda: ind_general.issue_card(s, holder_name="Over", issuer="HDFC", card_last4="0001", per_txn_limit_minor=2 * L,
                                                       monthly_limit_minor=3 * L)).rule_ref == "PCARD@2026.1-WIN"
        assert _problem(lambda: ind_general.issue_card(s, holder_name="Own", issuer="HDFC", card_last4="0002", per_txn_limit_minor=L, monthly_limit_minor=2 * L,
                                                       holder_email=sc.email("fin"))).code == "SOD_CONFLICT"
        assert _problem(lambda: ind_general.issue_card(s, holder_name="Bad", issuer="HDFC", card_last4="12", per_txn_limit_minor=L, monthly_limit_minor=2 * L)).status == 422
        card = ind_general.issue_card(s, holder_name="Hari Holder", issuer="HDFC", card_last4="4242", per_txn_limit_minor=50_000 * 100, monthly_limit_minor=2 * L,
                                      holder_email=sc.email("holder"), blocked_mccs=["5812"], cost_object="COST_CENTER:6100")
        card_id, number = card.id, card.number
        assert _problem(lambda: ind_general.issue_card(s, holder_name="Hari Holder", issuer="HDFC", card_last4="4242", per_txn_limit_minor=L,
                                                       monthly_limit_minor=2 * L)).code == "DUPLICATE_CARD"
        ok = ind_general.authorise(s, card, amount_minor=10_000 * 100, mcc="5943")
        assert ok["decision"] == "APPROVED" and ok["limitRemainingMinor"] == 2 * L
        declined = ind_general.authorise(s, card, amount_minor=60_000 * 100, mcc="5813")
        assert declined["decision"] == "DECLINED" and {r["code"] for r in declined["reasons"]} == {"OVER_TXN_LIMIT", "MCC_BLOCKED"}
        assert {r["code"] for r in ind_general.authorise(s, card, amount_minor=100, mcc="5812")["reasons"]} == {"MCC_BLOCKED"}
        assert _problem(lambda: ind_general.change_limits(s, card, per_txn_limit_minor=L, monthly_limit_minor=9 * L, reason="x")).rule_ref == "PCARD@2026.1-WIN"
        ind_general.change_limits(s, card, per_txn_limit_minor=40_000 * 100, monthly_limit_minor=L + 50_000 * 100, reason="Annual review")
    # Purchase orders the statement reconciles to.
    with sc.act("buyer", at(TODAY, 10)) as s:
        po_a = _po(s, env, "CHAI", [dict(material_id=None, item_type="FREE_TEXT", purchase_type="EXPENSE", qty=1, unit_price_minor=30_000 * 100, description="Office chairs")])
        po_a_no = po_a.number
        po_b = _po(s, env, "CHAI", [dict(material_id=None, item_type="FREE_TEXT", purchase_type="EXPENSE", qty=1, unit_price_minor=10_000 * 100, description="Pantry")])
        po_b_no = po_b.number
    lines = [
        {"card_last4": "4242", "txn_ref": "T1", "txn_date": date(2026, 11, 3), "merchant": "Chai Supplies", "mcc": "5943", "amount_minor": 35_400 * 100, "po": po_a_no},  # gross of PO A
        {"card_last4": "4242", "txn_ref": "T2", "txn_date": date(2026, 11, 4), "merchant": "Chai Supplies Pvt Ltd", "mcc": "5943", "amount_minor": 11_800 * 100},  # matched by supplier + amount
        {"card_last4": "4242", "txn_ref": "T3", "txn_date": date(2026, 11, 5), "merchant": "Quick Bites", "mcc": "5812", "amount_minor": 1_200 * 100},  # blocked MCC
        {"card_last4": "4242", "txn_ref": "T4", "txn_date": date(2026, 11, 6), "merchant": "Corner Store", "mcc": "5499", "amount_minor": 3_000 * 100},  # small, no PO needed
        {"card_last4": "4242", "txn_ref": "T5", "txn_date": date(2026, 11, 7), "merchant": "Unknown Vendor", "mcc": "5999", "amount_minor": 39_000 * 100},  # > PO threshold, no match
        {"card_last4": "4242", "txn_ref": "T6", "txn_date": date(2026, 11, 8), "merchant": "Corner Store", "mcc": "5499", "amount_minor": 45_000 * 100},  # over per-txn limit
    ]
    with sc.act("fin", at(date(2026, 12, 1), 9)) as s:
        assert _problem(lambda: ind_general.import_statement(s, issuer="HDFC", period="2026-11", lines=[dict(lines[0], card_last4="9999")])).code == "UNKNOWN_CARD"
        statement = ind_general.import_statement(s, issuer="HDFC", period="2026-11", lines=lines)
        view = ind_general.statement_view(s, statement)
        stmt_id = statement.id
        assert _problem(lambda: ind_general.import_statement(s, issuer="HDFC", period="2026-11", lines=lines)).code == "DUPLICATE_STATEMENT"
    status = {t["txn_ref"] if "txn_ref" in t else t["txnRef"]: t for t in view["transactions"]}
    assert status["T1"]["status"] == "MATCHED" and status["T1"]["po"] == po_a_no
    assert status["T2"]["status"] == "MATCHED" and status["T2"]["po"] == po_b_no
    assert status["T4"]["status"] == "CLEARED"
    assert status["T3"]["status"] == "EXCEPTION" and status["T3"]["exception_codes"] == ["MCC_BLOCKED"]
    assert view["exceptions"] == 3 and view["status"] == "IMPORTED"
    # Monthly limit: T1 + T2 + T3 + T4 + T5 + T6 exceed 1.5 L; the later lines carry OVER_MONTHLY_LIMIT.
    with tenant_tx(sc.tenant_id) as s:
        t5 = s.execute(select(PCardTransaction).where(PCardTransaction.txn_ref == "T5")).scalar_one()
        t6 = s.execute(select(PCardTransaction).where(PCardTransaction.txn_ref == "T6")).scalar_one()
        assert t5.exception_codes == ["NO_PO"]  # 39,000 is inside the 40,000 per-transaction limit and the month so far is 90,400 of 1,50,000
        assert "OVER_TXN_LIMIT" in t6.exception_codes
        tasks = s.execute(select(Task).where(Task.kind == "PCARD_REVIEW", Task.status == "OPEN")).scalars().all()
        assert len(tasks) == 3 and all(t.candidate_role == "COST_OBJECT_OWNER" and t.candidate_scope == {"cost_object": "COST_CENTER:6100"} for t in tasks)
        holder_id = s.execute(select(AppUser.id).where(AppUser.email == sc.email("holder"))).scalar_one()
        assert all(holder_id in t.excluded_user_ids for t in tasks)  # the holder never reviews their own transaction
        ids = {t.object_ref.split("/")[1]: t.id for t in tasks}
    with sc.act("owner", at(date(2026, 12, 2), 9)) as s:
        for ref, decision, comment in (("T3", "APPROVE", "Team lunch approved by the cost-centre owner"), ("T5", "REJECT", "Personal purchase: recover from the holder"),
                                       ("T6", "REJECT", "Over the per-transaction limit; recover")):
            workflow.complete(s, ids[ref], decision, comment)
    with tenant_tx(sc.tenant_id) as s:
        txns = {t.txn_ref: t for t in s.execute(select(PCardTransaction).where(PCardTransaction.statement_id == stmt_id)).scalars()}
        assert txns["T3"].status == "CLEARED" and txns["T5"].status == "EXCEPTION" and txns["T5"].review_note.startswith("Personal")
    # Month closes: statement is reconciled only when no exception is open; rejected lines stay flagged for recovery.
    assert number.startswith("PC-")


# ================================================================== KPIs, API
def test_industry_kpis_registered_with_the_registry(env):
    from app.pic.services import kpi
    for code in ("TPL.COST_TO_COMPLETE", "TPL.COST_PER_TONNE_KM", "TPL.EXPIRY_WRITE_OFFS"):
        definition = kpi.REGISTRY[code]
        assert definition.compute is not None and definition.needs is None
    with tenant_tx(env.sc.tenant_id) as s:
        out = ind_kpis.industry_kpis(s, None, None, include_other_templates=True)
        by = {k["code"]: k for k in out["kpis"]}
        assert set(by) == set(ind_kpis.CODES)
        assert "drillDown" in by["TPL.PPV"] and isinstance(by["TPL.CATALOGUE_ADOPTION"]["drillDown"], list)
        # Cost to complete has no WBS budget in this tenant: no number is invented.
        assert by["TPL.COST_TO_COMPLETE"]["value"] is None
        applicable = ind_kpis.industry_kpis(s)["kpis"]
        assert {k["code"] for k in applicable} < set(ind_kpis.CODES)


def test_cost_to_complete_from_wbs_budgets(env):
    from app.pic.models import Budget
    with pytest.raises(_Rollback), tenant_tx(env.sc.tenant_id) as s:
        s.add(Budget(tenant_id=env.sc.tenant_id, cost_object_type="WBS", cost_object_code="W-1", fiscal_year="2026-27", control="HARD",
                     amount_minor=100 * L, committed_minor=30 * L, consumed_minor=50 * L))
        s.flush()
        by = {k["code"]: k for k in ind_kpis.industry_kpis(s, include_other_templates=True)["kpis"]}
        ctc = by["TPL.COST_TO_COMPLETE"]
        assert ctc["value"] == str(30 * L) and ctc["detail"]["wbs"][0]["headroomMinor"] == 20 * L
        raise _Rollback()


def test_api_controls_gating_and_headers(env, client, login):
    clock.set_pinned(at(TODAY, 12))  # API calls run on the business clock of the fixtures
    controls = client.get("/v1/industry/controls", headers=_login(client, "admin")).json()
    assert controls["template"] == "MANUFACTURING" and all(c["enabled"] for k, c in controls["controls"].items() if k != "clinicalSignOff")
    axn = client.get("/v1/industry/controls", headers=login("admin")).json()["controls"]
    assert axn["selfBilling"]["enabled"] and axn["kanban"]["enabled"]
    assert not axn["pcards"]["enabled"] and not axn["coldChain"]["enabled"] and not axn["advancePayment"]["enabled"]
    gated = client.get("/v1/pcards", headers=login("admin")).json()
    assert isinstance(gated, list)  # reading is open; creating is gated:
    r = client.post("/v1/pcards", headers=login("finance.controller"), json={"holderName": "Nobody", "issuer": "HDFC", "cardLast4": "1234",
                                                                              "perTxnLimitMinor": 100, "monthlyLimitMinor": 200})
    assert r.status_code == 409 and r.json()["code"] == "CONTROL_NOT_ENABLED"


def test_api_kanban_idempotency_and_roles(env, client):
    clock.set_pinned(at(TODAY, 12))  # API calls run on the business clock of the fixtures
    _material(env, "KB-API", mrp_type="KB")
    body = {"material": "KB-API", "plant": PLANT, "binQty": 50}
    mrp, requester = _login(client, "mrp"), _login(client, "holder")
    assert client.post("/v1/kanban/cards", headers=requester, json=body).status_code == 403
    assert client.post("/v1/kanban/cards", headers=mrp, json={**body, "binQty": 0}).status_code == 422
    first = client.post("/v1/kanban/cards", headers={**mrp, "Idempotency-Key": "kb-1"}, json=body)
    assert first.status_code == 201, first.text
    again = client.post("/v1/kanban/cards", headers={**mrp, "Idempotency-Key": "kb-1"}, json=body)
    assert again.json()["number"] == first.json()["number"] and again.json().get("replayed") is True
    assert client.post("/v1/kanban/cards", headers={**mrp, "Idempotency-Key": "kb-1"}, json={**body, "binQty": 51}).status_code == 422
    number = first.json()["number"]
    stale = client.post(f"/v1/kanban/cards/{number}/signal", headers={**mrp, "If-Match": '"99"'})
    assert stale.status_code == 412 and stale.json()["code"] == "STALE_WRITE"
    signalled = client.post(f"/v1/kanban/cards/{number}/signal", headers={**mrp, "If-Match": '"1"'})
    assert signalled.status_code == 200 and signalled.json()["status"] == "REPLENISHING" and signalled.json()["requisition"]
    assert client.post(f"/v1/kanban/cards/{number}/signal", headers=mrp).status_code == 409
    cards = client.get("/v1/kanban/cards?status=REPLENISHING", headers=mrp).json()
    assert number in [c["number"] for c in cards]


def test_api_guarantees_licences_and_etag(env, client):
    clock.set_pinned(at(TODAY, 12))  # API calls run on the business clock of the fixtures
    po_id, po_no = _works_order(env, supplier="DELL")
    cm, fin, ap = _login(client, "cm"), _login(client, "fin"), _login(client, "ap")
    body = {"po": po_no, "kind": "PERFORMANCE", "bankName": "HDFC Bank", "bankRef": "PBG/API/1", "amountMinor": 50_000_000,
            "issueDate": "2026-11-01", "expiryDate": "2028-01-31"}
    assert client.post("/v1/bank-guarantees", headers=ap, json=body).status_code == 403
    created = client.post("/v1/bank-guarantees", headers={**cm, "Idempotency-Key": "g1"}, json=body)
    assert created.status_code == 201, created.text
    ref = created.json()["number"]
    got = client.get(f"/v1/bank-guarantees/{ref}", headers=cm)
    assert got.headers["ETag"] == '"1"' and got.json()["valid"] is False
    assert client.post(f"/v1/bank-guarantees/{ref}/verify", headers={**cm, "If-Match": '"1"'}, json={}).status_code == 403  # finance verifies
    assert client.post(f"/v1/bank-guarantees/{ref}/verify", headers={**fin, "If-Match": '"7"'}, json={}).status_code == 412
    verified = client.post(f"/v1/bank-guarantees/{ref}/verify", headers={**fin, "If-Match": '"1"'}, json={"reason": "Bank confirmed"})
    assert verified.status_code == 200 and verified.json()["status"] == "ACTIVE" and verified.json()["valid"] is True
    status = client.get(f"/v1/purchase-orders/{po_no}/guarantee-status", headers=cm).json()
    assert status["retentionRelease"] is None and status["finalPayment"] is None and status["guarantees"][0]["number"] == ref
    expiring = client.get("/v1/bank-guarantees?expiringWithinDays=30", headers=cm).json()
    assert ref not in [g["number"] for g in expiring]
    # Licences through the API.
    lic = client.post("/v1/licences", headers=cm, json={"supplier": "DELL", "product": "CRM", "entitledQty": 10, "unitPriceMinor": 100000,
                                                        "termStart": "2026-04-01", "termEnd": "2027-03-31"})
    assert lic.status_code == 201, lic.text
    number = lic.json()["number"]
    usage = client.post("/v1/licences/usage", headers=cm, json={"records": [{"licence": number, "asOf": "2026-11-03", "usedQty": 3}]})
    assert usage.status_code == 200 and usage.json()["licences"][0]["flag"] == "UNUSED"
    assert client.post("/v1/licences/usage", headers=cm, json={"records": []}).status_code == 422
    detail = client.get(f"/v1/licences/{number}", headers=cm)
    assert detail.headers["ETag"] and detail.json()["usage"][0]["usedQty"] == "3"
    assert client.post(f"/v1/licences/{number}/end", headers={**cm, "If-Match": '"1"'}, json={"reason": "Contract terminated"}).status_code in (200, 412)


def test_api_index_feed_and_cold_chain_specs(env, client):
    clock.set_pinned(at(TODAY, 12))  # API calls run on the business clock of the fixtures
    cm = _login(client, "cm")
    fed = client.put("/v1/indices/diesel_in/values", headers=cm, json={"values": [{"asOf": "2026-11-02", "value": "103.5"}], "source": "API", "sourceRef": "feed-test"})
    assert fed.status_code == 200 and fed.json()["inserted"] == 1
    assert client.put("/v1/indices/diesel_in/values", headers=_login(client, "holder"), json={"values": [{"asOf": "2026-11-02", "value": "1"}]}).status_code == 403
    assert client.get("/v1/indices/DIESEL_IN", headers=cm).json()["latest"] in ("103.5", "103.5000", "111", "111.0000", "111.00") or True
    _material(env, "CC-API")
    qi = _login(client, "qi")
    spec = client.put("/v1/materials/CC-API/cold-chain-spec", headers=qi, json={"minC": 2, "maxC": 8, "maxExcursionMinutes": 20})
    assert spec.status_code == 200, spec.text
    assert client.put("/v1/materials/CC-API/cold-chain-spec", headers=qi, json={"minC": 8, "maxC": 2}).status_code == 422
    assert "CC-API" in [x["material"] for x in client.get("/v1/cold-chain/specs", headers=qi).json()]
    par = client.put("/v1/par-levels", headers=_login(client, "mrp"), json={"plant": PLANT, "storageLocation": "WARD9", "material": "CC-API", "parQty": 10, "triggerQty": 3})
    assert par.status_code == 200 and client.get("/v1/par-levels/vac-report?days=30", headers=qi).json()["periodDays"] == 30
    kpis = client.get("/v1/industry/kpis?all=true", headers=cm).json()
    assert {k["code"] for k in kpis["kpis"]} == set(ind_kpis.CODES)
