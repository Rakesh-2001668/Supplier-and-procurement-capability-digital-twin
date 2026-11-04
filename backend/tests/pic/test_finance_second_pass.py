"""Finance second pass (3 November 2026): adversarial probes and the gaps closed after the first analysis (docs/PIC_Finance_Module_Analysis.md,
section "Second analysis"). Own tenant FIN2; every test names the defect (D19..) or gap it proves.

The tests build real purchase orders / goods receipts / invoices through the HTTP API (like test_finance_journey.py); bulk fixtures for the
scale tests are written straight to the database because only the payment-run logic is under test there.
"""
import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.pic.db import tenant_tx
from app.pic.models import (AppUser, ErpDocument, FxRate, IntegrationMessage, Invoice, Material, Payment, PoLine, PrLine, PurchaseOrder, Requisition,
                            Supplier, SupplierBankAccount, SupplierCategoryStatus)
from app.pic.platform import clock, crypto
from app.pic.platform.auth import hash_password
from app.pic.seed.axion import at
from app.pic.seed.datasets import _tenant_kit as kit
from app.pic.services import supplier as supplier_svc

from .conftest import PASSWORD

CODE = os.environ.get("FIN2_TEST_TENANT", "FIN2")
DOMAIN = f"{CODE.lower()}.example"
GSTIN = "29AAKCD4821M1Z7"
PLANT = "P200"
J: dict = {}
USERS = [
    ("admin", "Admin Anil", ["TENANT_ADMIN"], {}),
    ("buyer", "Bala Buyer", ["BUYER"], {"plants": [PLANT]}),
    ("buyer2", "Bina Buyer", ["BUYER"], {"plants": [PLANT]}),
    ("ph", "Pranav Procurement", ["PROCUREMENT_HEAD"], {}),
    ("cpo", "Cara CPO", ["CPO"], {}),
    ("fin", "Farid Finance", ["FINANCE_CONTROLLER"], {}),
    ("fin2", "Fatima Finance", ["FINANCE_CONTROLLER"], {}),
    ("ap1", "Asha AP", ["AP_CLERK"], {}),
    ("ap2", "Arun AP", ["AP_CLERK"], {}),
    ("ap3", "Anita AP", ["AP_CLERK"], {}),
    ("receiver", "Ravi Receiver", ["RECEIVER"], {"plants": [PLANT]}),
    ("supmgr", "Sana Suppliers", ["SUPPLIER_MANAGER"], {}),
    # an AP clerk who may only work company code 2000 and has a small approval limit
    ("apscoped", "Sam Scoped-AP", ["AP_CLERK", "FINANCE_CONTROLLER"], {"company_codes": ["2000"], "plants": ["P999"]}),
    ("aplimit", "Lena Limit-AP", ["AP_CLERK"], {"value_limit_minor": 1_000_000}),
    ("owner", "Omar Owner-Finance", ["CATEGORY_MANAGER", "FINANCE_CONTROLLER"], {}),
    ("cm", "Chandra Category", ["CATEGORY_MANAGER"], {}),
]
ROLE_USER = {"BUYER": ["buyer2"], "PROCUREMENT_HEAD": "ph", "FINANCE_CONTROLLER": "fin", "CPO": "cpo"}
SUPPLIERS = {
    "F2-ALPHA": ("Alpha Alloys Two Pvt Ltd", "AABCA2234F", "N30"),
    "F2-BETA": ("Beta Bearings Two Pvt Ltd", "AABCB2234K", "2/10 N30"),
    "F2-MICRO": ("Micro Machining Two Works", "AABCM2234L", "N60"),
    "F2-TDS": ("TDS Fabricators Two Pvt Ltd", "AABCT2234M", "N30"),
    "F2-MUM": ("Mumbai Metals Two Pvt Ltd", "AABCU2234P", "N30"),       # state 27: inter-state supplies to the plant in state 29
    "F2-GLOBAL": ("Global Forge Two LLC", "AABCG2234Q", "N30"),         # foreign beneficiary bank in the US
}
MATERIALS = {f"F2-MAT-{n:02d}": 100_000 for n in range(1, 41)}
MATERIALS["F2-MAT-RCM"] = 100_000                                      # HSN 996511 (goods transport agency): reverse charge in the RCM tests
D0 = date(2026, 12, 1)


def _gstin(pan: str, state: str = "29") -> str:
    base = f"{state}{pan}1Z"
    total = 0
    for i, ch in enumerate(base):
        v = kit.GSTIN_CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += v // 36 + v % 36
    return base + kit.GSTIN_CHARS[(36 - total % 36) % 36]


def _email(local: str) -> str:
    return f"{local}@{DOMAIN}"


def _h(login, local: str) -> dict:
    return login(_email(local), CODE)


def _portal(login, code: str = "F2-ALPHA") -> dict:
    return login(f"portal@{code.lower()}.{DOMAIN}", CODE)


def _pin(day: date, hour: int = 10) -> None:
    clock.set_pinned(at(day, hour))


def _problem(r, status: int, code: str | None = None) -> dict:
    assert r.status_code == status, r.text
    body = r.json()
    if code:
        assert body["code"] == code, body
    return body


def _tasks(client, headers, ref: str) -> list[dict]:
    return [t for t in client.get("/v1/tasks", headers=headers).json() if t["object_ref"] == ref]


def _tick(client, login) -> None:
    assert client.post("/v1/admin/ops/tick", headers=_h(login, "admin")).status_code == 200


def _requisition(env, material: str, qty: str, price_minor: int, need: date | None = None) -> str:
    with tenant_tx(env.tenant_id) as s:
        pr = Requisition(tenant_id=env.tenant_id, number=f"REQ-F2-{uuid.uuid4().hex[:8].upper()}", origin="MANUAL", requester_id=J["buyer_id"],
                         company_code="1000", plant=PLANT, status="APPROVED", total_minor=0, purpose_code="PRODUCTION")
        s.add(pr)
        s.flush()
        m = s.execute(select(Material).where(Material.number == material)).scalar_one()
        s.add(PrLine(tenant_id=env.tenant_id, requisition_id=pr.id, line_no=10, item_type="MATERIAL", purchase_type="STOCK", material_id=m.id,
                     description=m.description, material_group=m.material_group, category=m.category, qty=Decimal(qty), uom=m.base_uom,
                     price_est_minor=price_minor, need_date=need or D0 + timedelta(days=20), plant=PLANT, storage_location="0001"))
        return pr.number


def _create_po(client, login, material: str, qty: str, supplier: str, need: date | None = None) -> str:
    pr = _requisition(J["env"], material, qty, MATERIALS[material], need)
    body = {"source": {"type": "REQUISITION", "id": pr, "lines": [10]}, "supplierId": supplier,
            "release": {"qty": qty, "needDate": (need or D0 + timedelta(days=20)).isoformat()}}
    r = client.post("/v1/purchase-orders", json=body, headers=_h(login, "buyer"))
    assert r.status_code == 201, r.text
    po = r.json()["id"]
    if client.get(f"/v1/purchase-orders/{po}", headers=_h(login, "buyer")).json()["status"] == "DRAFT":
        assert client.post(f"/v1/purchase-orders/{po}/validate", headers=_h(login, "buyer")).status_code == 200
    for _ in range(6):
        status = client.get(f"/v1/purchase-orders/{po}", headers=_h(login, "buyer")).json()["status"]
        if status not in ("DRAFT", "IN_APPROVAL"):
            break
        for who in ("buyer2", "ph", "fin", "cpo"):
            for task in _tasks(client, _h(login, who), po):
                client.post(f"/v1/tasks/{task['id']}/complete", json={"decision": "APPROVE", "comment": "Approved"}, headers=_h(login, who))
    _tick(client, login)
    if client.get(f"/v1/purchase-orders/{po}", headers=_h(login, "buyer")).json()["status"] != "CONFIRMED":
        r = client.post(f"/v1/purchase-orders/{po}/confirmations", json={"status": "CONFIRMED"}, headers=_portal(login, supplier))
        assert r.status_code == 200, r.text
    return po


def _gr(client, login, po: str, qty: str, day: date, note: str) -> dict:
    _pin(day)
    r = client.post("/v1/goods-receipts", json={"po": po, "delivery_note": note, "posting_date": day.isoformat(),
                                                 "lines": [{"line": 10, "qty": qty, "storage_location": "0001"}]}, headers=_h(login, "receiver"))
    assert r.status_code == 201, r.text
    return r.json()


def _capture(client, headers, supplier: str, number: str, day: date, po: str, qty: str, price: str, *, channel: str = "PORTAL",
             irn: str | None = None, extra: dict | None = None, idem: str | None = None, company: str | None = None):
    _pin(day)
    line = {"po": po, "po_line": 10, "qty": qty, "unit_price": price, **(extra or {})}
    body = {"supplier": supplier, "supplier_invoice_no": number, "invoice_date": day.isoformat(), "channel": channel, "lines": [line]}
    if irn:
        body["irn"] = irn
    if company:
        body["company_code"] = company
    return client.post("/v1/invoices", json=body, headers={**headers, **({"Idempotency-Key": idem} if idem else {})})


def _invoice(client, login, ref: str, who: str = "ap1") -> dict:
    r = client.get(f"/v1/invoices/{ref}", headers=_h(login, who))
    assert r.status_code == 200, r.text
    return r.json()


def _approve(client, login, ref: str, who: str):
    return client.post(f"/v1/invoices/{ref}/approve", headers=_h(login, who))


def _post(client, login, ref: str, who: str, key: str | None = None):
    inv = _invoice(client, login, ref, who)
    key = key or f"{CODE}|1000|{inv['supplier']['code']}|{inv['supplier_invoice_no']}"
    return client.post(f"/v1/invoices/{ref}/post", headers={**_h(login, who), "Idempotency-Key": key}), key


def _posted_invoice(client, login, supplier: str, number: str, day: date, *, material: str, qty: str = "10", price: str = "1000.00",
                    po: str | None = None, receive: bool = True) -> tuple[str, str]:
    """PO (if none given) -> GR -> capture by AP clerk 1 -> approve by AP clerk 2 -> post. Returns (invoice id, PO number)."""
    po = po or _create_po(client, login, material, qty, supplier)
    if receive:
        _gr(client, login, po, qty, day, f"DN-{number}"[:20])
    r = _capture(client, _h(login, "ap1"), supplier, number, day, po, qty, price)
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["status"] == "MATCHED", inv
    assert _approve(client, login, inv["id"], "ap2").status_code == 200
    r, _ = _post(client, login, inv["id"], "ap2")
    assert r.status_code == 200 and r.json().get("erpDocument"), r.text
    return inv["id"], po


@pytest.fixture(scope="module")
def env(database):
    sc = kit.setup_tenant(CODE, "Finance Second Pass Industries Pvt Ltd", "GENERAL", company=("1000", "Finance Second Pass Industries Pvt Ltd", GSTIN),
                          plants=[(PLANT, "Second plant", "29")], cost_objects=[("COST_CENTER", "6100", "Test cost centre")], holidays=[],
                          domain=DOMAIN, role_user=ROLE_USER)
    kit.create_users(sc, USERS, PASSWORD)
    kit.rule_version(sc, "MFA", "2026.1-FIN2", date(2026, 4, 1), {"enforce": False}, "Finance second pass tenant: no MFA challenge for the API tests")
    kit.rule_version(sc, "PAYMENT-FILE", "2026.1-FIN2", date(2026, 4, 1),
                     {"debtorName": "Finance Second Pass Industries Pvt Ltd", "debtorAccountRef": "50200011223399", "debtorIfsc": "HDFC0000123"},
                     "Finance second pass tenant: debtor account of the bank file")
    J["env"] = sc
    with sc.act("supmgr", at(D0, 9)) as s:
        for code, (name, pan, terms) in SUPPLIERS.items():
            state = "27" if code == "F2-MUM" else "29"
            sup = supplier_svc.register(s, code=code, legal_name=name, gstin=_gstin(pan, state), pan=pan, state_code=state,
                                        contact_email=f"accounts@{code.lower()}.{DOMAIN}", categories=["GENERAL"], payment_terms=terms)
            foreign = code == "F2-GLOBAL"
            s.add(SupplierBankAccount(tenant_id=sc.tenant_id, supplier_id=sup.id, account_enc=crypto.encrypt(sc.tenant_id, "bank", "US00123456789012" if foreign else "50100012345678"),
                                      account_masked="XXXXXXXXXXXX9012" if foreign else "XXXXXXXXXX5678", ifsc="" if foreign else "HDFC0000001",
                                      holder_name=name, active=True, verified_on=date(2026, 6, 1), country="US" if foreign else "IN"))
            if foreign:
                sup.country = "US"
            if code == "F2-TDS":
                sup.tds_section = "194C-OTH"
            s.add(AppUser(tenant_id=sc.tenant_id, email=f"portal@{code.lower()}.{DOMAIN}", full_name=f"{name} portal", password_hash=hash_password(PASSWORD),
                          roles=["SUPPLIER_USER"], attributes={}, supplier_id=sup.id, mfa_enrolled=True))
            sup.status = "QUALIFIED"
            for row in s.execute(select(SupplierCategoryStatus).where(SupplierCategoryStatus.supplier_id == sup.id)).scalars():
                row.status, row.qualified_on = "QUALIFIED", date(2026, 6, 1)
    with tenant_tx(sc.tenant_id) as s:
        for number, price in MATERIALS.items():
            s.add(Material(tenant_id=sc.tenant_id, number=number, description=f"Finance second pass material {number}", type="STOCK",
                           material_group="GENERAL", category="GENERAL", base_uom="EA", mrp_type="PD", lot_size_policy="EXACT", safety_stock=Decimal(0),
                           planned_delivery_days=3, gr_processing_days=0, standard_price_minor=price, status="ACTIVE",
                           hsn_code="996511" if number == "F2-MAT-RCM" else "7601", gst_rate=Decimal(18)))
        J["buyer_id"] = s.execute(select(AppUser).where(AppUser.email == _email("buyer"))).scalar_one().id
    J.update(tenant_id=sc.tenant_id, mat=iter(MATERIALS))
    return sc


def _material() -> str:
    return next(J["mat"])


# ================================================================ 0. shared order: one big PO and receipt the probes draw on
def test_fin2_00_setup_orders(client, login, env):
    _pin(D0)
    J["po_big"] = _create_po(client, login, _material(), "1000", "F2-ALPHA")
    _gr(client, login, J["po_big"], "1000", date(2026, 12, 2), "DN-BIG-1")


# ================================================================ 1. invoice numbers, route encoding, input limits
def test_fin2_invoice_numbers_with_slashes_spaces_unicode_work_in_every_route(client, login, env):
    day = date(2026, 12, 3)
    number = "F2/27-28/0311 é"
    r = _capture(client, _h(login, "ap1"), "F2-ALPHA", number, day, J["po_big"], "1", "1000.00")
    assert r.status_code == 201, r.text
    inv = r.json()
    from urllib.parse import quote
    ref = quote(inv["number"], safe="")
    for path in (f"/v1/invoices/{ref}", f"/v1/invoices/{ref}/debit-notes", f"/v1/invoices/{ref}/early-payment"):
        g = client.get(path, headers=_h(login, "ap1"))
        assert g.status_code == 200, (path, g.status_code, g.text[:200])
    a = client.post(f"/v1/invoices/{ref}/approve", headers=_h(login, "ap2"))
    assert a.status_code == 200, a.text
    key = quote(f"{CODE}|1000|F2-ALPHA|{number}", safe="|/-_.~")  # a header is ASCII without spaces: D20
    p = client.post(f"/v1/invoices/{ref}/post", headers={**_h(login, "ap2"), "Idempotency-Key": key})
    assert p.status_code == 200 and p.json().get("erpDocument"), p.text
    J["slash_invoice"] = inv["id"]


def test_fin2_overlong_and_blank_invoice_numbers_are_422_not_500(client, login, env):
    day = date(2026, 12, 3)
    for number in ("X" * 41, "   ", ""):
        r = _capture(client, _h(login, "ap1"), "F2-ALPHA", number, day, J["po_big"], "1", "1000.00")
        assert r.status_code == 422, (number, r.status_code, r.text[:200])


def test_fin2_malformed_filters_and_huge_pages_are_clean_422(client, login, env):
    h = _h(login, "ap1")
    for q in ("date_from=2026-13-45", "limit=100000", "limit=0", "due_from=banana", "min_gross_minor=-5", "cursor=%%%"):
        r = client.get(f"/v1/invoices?{q}", headers=h)
        assert r.status_code in (400, 422), (q, r.status_code, r.text[:200])
    r = client.get("/v1/invoices?limit=200", headers=h)
    assert r.status_code == 200
    assert client.get("/v1/payments?limit=1000", headers=h).status_code == 422
    assert client.get("/v1/payments/proposal?run_date=2026-02-30", headers=_h(login, "fin")).status_code == 422


def test_fin2_ocr_and_whitespace_case_variants_of_a_number_are_held_as_duplicates(client, login, env):
    day = date(2026, 12, 4)
    r = _capture(client, _h(login, "ap1"), "F2-ALPHA", "inv-00077", day, J["po_big"], "1", "1001.00")
    assert r.status_code == 201, r.text
    for variant in ("INV-77", " INV 0077", "inv77", "INVO077"):
        v = _capture(client, _h(login, "ap1"), "F2-ALPHA", variant, day + timedelta(days=20), J["po_big"], "1", "1002.00")
        assert v.status_code in (201, 409), v.text
        if v.status_code == 201:
            assert v.json()["status"] == "EXCEPTION", (variant, v.json()["status"])


# ================================================================ 2. idempotency, amounts, credit notes
def test_fin2_replayed_idempotency_key_with_a_different_body_is_refused(client, login, env):
    day = date(2026, 12, 4)
    key = f"fin2-cap-{uuid.uuid4()}"
    first = _capture(client, _h(login, "ap1"), "F2-ALPHA", "IDEM-0001", day, J["po_big"], "3", "1000.00", idem=key)
    assert first.status_code == 201, first.text
    same = _capture(client, _h(login, "ap1"), "F2-ALPHA", "IDEM-0001", day, J["po_big"], "3", "1000.00", idem=key)
    assert same.status_code == 201 and same.json()["id"] == first.json()["id"]
    other = _capture(client, _h(login, "ap1"), "F2-ALPHA", "IDEM-0001", day, J["po_big"], "4", "1000.00", idem=key)
    assert other.status_code in (409, 422), other.text
    approve_key = f"fin2-appr-{uuid.uuid4()}"
    h = {**_h(login, "ap2"), "Idempotency-Key": approve_key}
    a1 = client.post(f"/v1/invoices/{first.json()['id']}/approve", headers=h)
    a2 = client.post(f"/v1/invoices/{first.json()['id']}/approve", headers=h)
    assert a1.status_code == 200 and a2.status_code == 200 and a2.headers.get("Idempotent-Replayed") == "true"


def test_fin2_zero_negative_and_overflow_amounts_are_422(client, login, env):
    day = date(2026, 12, 4)
    h = _h(login, "ap1")
    for qty, price in (("0", "100"), ("-1", "100"), ("1", "0"), ("1", "-5"), ("1e12", "1e12"), ("99999999999999", "99999999999999")):
        r = _capture(client, h, "F2-ALPHA", f"AMT-{qty}-{price}"[:30], day, J["po_big"], qty, price)
        assert r.status_code == 422, (qty, price, r.status_code, r.text[:200])


def test_fin2_credit_note_cannot_exceed_the_invoice_and_rejects_bad_lines(client, login, env):
    day = date(2026, 12, 5)
    r = _capture(client, _h(login, "ap1"), "F2-ALPHA", "CN-BASE-1", day, J["po_big"], "10", "1000.00")
    assert r.status_code == 201, r.text
    inv = r.json()
    portal = _portal(login)
    ref = inv["id"]
    base = {"supplier_credit_note_no": "CN-1", "note_date": day.isoformat(), "reason": "short supply", "lines": [{"invoice_line": 10, "qty": "11"}]}
    _problem(client.post(f"/v1/invoices/{ref}/credit-notes", json=base, headers=portal), 422, "INVALID_CREDIT_NOTE")
    for qty in ("0", "-2"):
        assert client.post(f"/v1/invoices/{ref}/credit-notes", json={**base, "lines": [{"invoice_line": 10, "qty": qty}]}, headers=portal).status_code == 422
    big = {**base, "lines": [{"invoice_line": 10, "qty": "1", "unit_credit_minor": 100_001}]}  # more than the unit price (1,000.00 = 100,000 paise)
    _problem(client.post(f"/v1/invoices/{ref}/credit-notes", json=big, headers=portal), 422, "INVALID_CREDIT_NOTE")
    ok = client.post(f"/v1/invoices/{ref}/credit-notes", json={**base, "lines": [{"invoice_line": 10, "qty": "10"}]}, headers=portal)
    assert ok.status_code == 201, ok.text
    again = client.post(f"/v1/invoices/{ref}/credit-notes", json={**base, "supplier_credit_note_no": "CN-2", "lines": [{"invoice_line": 10, "qty": "1"}]},
                        headers=portal)
    _problem(again, 422, "INVALID_CREDIT_NOTE")
    # another supplier's portal user does not see the invoice at all
    assert client.post(f"/v1/invoices/{ref}/credit-notes", json=base, headers=_portal(login, "F2-BETA")).status_code == 404
    assert client.get(f"/v1/invoices/{ref}", headers=_portal(login, "F2-BETA")).status_code == 404


def test_fin2_a_supplier_user_cannot_read_finance_registers(client, login, env):
    portal = _portal(login)
    for path in ("/v1/payments", "/v1/payments/proposal?run_date=2026-12-10", "/v1/finance/tds-register", "/v1/grir", "/v1/finance/periods",
                 "/v1/bank-statements", "/v1/finance/controls"):
        assert client.get(path, headers=portal).status_code in (401, 403), path


# ================================================================ 3. ABAC: company-code / plant scope on every read and write, value limits
def _big_invoice(client, login, number: str, qty: str, day: date, who: str = "ap1") -> dict:
    r = _capture(client, _h(login, who), "F2-ALPHA", number, day, J["po_big"], qty, "1000.00")
    assert r.status_code == 201, r.text
    return r.json()


def test_fin2_abac_company_scope_covers_finance_reads_and_writes(client, login, env):
    day = date(2026, 12, 6)
    inv = _big_invoice(client, login, "ABAC-0001", "7", day)
    assert inv["status"] == "MATCHED"
    scoped = _h(login, "apscoped")
    # reads: a user limited to company code 2000 sees nothing of company code 1000, and does not learn that it exists
    assert client.get("/v1/invoices?limit=200", headers=scoped).json()["items"] == []
    assert client.get(f"/v1/invoices/{inv['id']}", headers=scoped).status_code == 404
    assert client.get("/v1/payments", headers=scoped).json()["items"] == []
    assert client.get("/v1/grir", headers=scoped).json() == []
    assert client.get("/v1/payables/insights", headers=scoped).json()["duplicatesPrevented"] == 0
    assert client.get("/v1/finance/periods?company_code=1000", headers=scoped).status_code == 404
    assert client.get("/v1/finance/tds-register", headers=scoped).json()["items"] == []
    assert client.get("/v1/invoices?limit=200", headers=_h(login, "ap1")).json()["items"], "an unrestricted AP clerk still sees the invoices"
    # writes: the same user cannot capture, approve, resolve, close a period, or reconcile for company code 1000
    assert client.post(f"/v1/invoices/{inv['id']}/approve", headers=scoped).status_code == 404
    assert client.post(f"/v1/invoices/{inv['id']}/match", headers=scoped).status_code == 404
    r = _capture(client, scoped, "F2-ALPHA", "ABAC-0002", day, J["po_big"], "1", "1000.00")
    assert r.status_code == 403 and r.json().get("ruleRef", r.json().get("rule_ref")) in ("ABAC", None) or r.status_code == 403, r.text
    assert client.post("/v1/finance/periods/2026-09/close", json={"companyCode": "1000"}, headers=scoped).status_code == 403
    assert client.post("/v1/reconciliation/runs", json={"company_code": "1000"}, headers=scoped).status_code == 404


def test_fin2_abac_value_limit_stops_a_large_approval(client, login, env):
    inv = _big_invoice(client, login, "ABAC-LIMIT-1", "12", date(2026, 12, 7))  # 12 x 1,000.00 + 18 % = 14,160.00 INR
    assert inv["status"] == "MATCHED"
    r = client.post(f"/v1/invoices/{inv['id']}/approve", headers=_h(login, "aplimit"))  # limit 10,000.00 INR
    _problem(r, 403, "VALUE_LIMIT_EXCEEDED")
    assert _invoice(client, login, inv["id"])["status"] == "MATCHED"
    assert _approve(client, login, inv["id"], "ap2").status_code == 200


# ================================================================ 4. concurrency: double post, double payment run
def test_fin2_concurrent_double_post_posts_once(client, login, env):
    import threading
    inv = _big_invoice(client, login, "CONC-POST-1", "8", date(2026, 12, 8))
    assert _approve(client, login, inv["id"], "ap2").status_code == 200
    key = f"{CODE}|1000|F2-ALPHA|CONC-POST-1"
    out = []

    def go(tag):
        try:
            out.append((tag, client.post(f"/v1/invoices/{inv['id']}/post", headers={**_h(login, "ap2"), "Idempotency-Key": key}).status_code))
        except Exception as exc:  # noqa: BLE001
            out.append((tag, repr(exc)))

    threads = [threading.Thread(target=go, args=(n,)) for n in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert all(code in (200, 409) for _, code in out), out
    assert any(code == 200 for _, code in out), out
    with tenant_tx(J["tenant_id"]) as s:
        assert s.execute(select(func.count()).select_from(IntegrationMessage).where(IntegrationMessage.idempotency_key == key)).scalar() == 1
        assert s.execute(select(Invoice.status).where(Invoice.supplier_invoice_no == "CONC-POST-1")).scalar() == "POSTED"
    J["posted_for_pay"] = [inv["number"]]


def test_fin2_concurrent_payment_runs_pay_each_invoice_once_without_a_500(client, login, env):
    import threading
    day = date(2026, 12, 9)
    numbers = list(J["posted_for_pay"])
    for n, qty in (("CONC-PAY-2", "9"), ("CONC-PAY-3", "13")):
        inv = _big_invoice(client, login, n, qty, day)
        assert _approve(client, login, inv["id"], "ap2").status_code == 200
        assert _post(client, login, inv["id"], "ap2")[0].status_code == 200
        numbers.append(inv["number"])
    _pin(date(2027, 2, 1), 11)
    out = []

    def go(tag):
        try:
            r = client.post("/v1/payments/runs", json={"run_date": "2027-02-01", "invoice_numbers": numbers}, headers={**_h(login, "fin"), "Idempotency-Key": f"run-{tag}"})
            out.append((tag, r.status_code, len(r.json().get("paid", [])) if r.status_code == 200 else r.text[:200]))
        except Exception as exc:  # noqa: BLE001
            out.append((tag, "EXC", repr(exc)[:200]))

    threads = [threading.Thread(target=go, args=(n,)) for n in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert all(code == 200 for _, code, _ in out), out
    assert sorted(paid for _, _, paid in out) == [0, 3], out  # one run paid the three invoices, the other found nothing left
    with tenant_tx(J["tenant_id"]) as s:
        live = s.execute(select(func.count()).select_from(Payment).join(Invoice, Invoice.id == Payment.invoice_id).where(
            Invoice.number.in_(numbers), Payment.status != "CANCELLED")).scalar()
        assert live == 3
    _pin(day)


def test_fin2_rejected_and_disputed_invoices_are_never_paid(client, login, env):
    day = date(2026, 12, 10)
    bad = _capture(client, _h(login, "ap1"), "F2-ALPHA", "REJ-0001", day, J["po_big"], "14", "1100.00")  # price outside tolerance -> exception
    assert bad.status_code == 201 and bad.json()["status"] == "EXCEPTION", bad.text
    ex = client.get(f"/v1/invoices/{bad.json()['id']}", headers=_h(login, "ap1")).json()["exceptions"][0]
    d = client.post(f"/v1/invoices/{bad.json()['id']}/exceptions/{ex['id']}/resolve", json={"resolution": "DISPUTE", "note": "price query"}, headers=_h(login, "ap2"))
    assert d.status_code == 200, d.text
    assert _approve(client, login, bad.json()["id"], "ap2").status_code == 409  # disputed = still in EXCEPTION
    assert client.post(f"/v1/invoices/{bad.json()['id']}/reject", json={"reason": "supplier to re-issue"}, headers=_h(login, "ap2")).status_code == 200
    _pin(date(2027, 2, 2), 11)
    r = client.post("/v1/payments/runs", json={"run_date": "2027-02-02", "include_not_due": True, "invoice_numbers": [bad.json()["number"]]}, headers=_h(login, "fin"))
    assert r.status_code == 200 and r.json()["paid"] == [], r.text
    _pin(day)


# ================================================================ 5. scale: 650 open invoices, proposal under 20 s, filtered worklists
SCALE = int(os.environ.get("FIN2_SCALE", "650"))


def _scale_fixture(env) -> list[str]:
    """SCALE posted, unpaid invoices spread over 40 suppliers (every 7th a micro enterprise) written straight to the database."""
    import random
    random.seed(7)
    sc = env
    codes = []
    with sc.act("supmgr", at(D0, 9)) as s:
        for n in range(40):
            code = f"F2-S{n:02d}"
            pan = f"AABCS{n:04d}F"
            sup = supplier_svc.register(s, code=code, legal_name=f"Scale Supplier {n:02d} Pvt Ltd", gstin=_gstin(pan), pan=pan, state_code="29",
                                        contact_email=f"accounts@{code.lower()}.{DOMAIN}", categories=["GENERAL"], payment_terms="N30")
            s.add(SupplierBankAccount(tenant_id=sc.tenant_id, supplier_id=sup.id, account_enc=crypto.encrypt(sc.tenant_id, "bank", f"6010001234{n:04d}"),
                                      account_masked=f"XXXXXX{n:04d}", ifsc="HDFC0000001", holder_name=sup.legal_name, active=True, verified_on=date(2026, 6, 1)))
            sup.status = "QUALIFIED"
            if n % 7 == 0:
                sup.msme_class, sup.udyam_no = "SMALL", f"UDYAM-KA-03-{n:07d}"
            if n % 5 == 0:
                sup.tds_section = "194C-OTH"
            codes.append(code)
    with tenant_tx(sc.tenant_id) as s:
        ids = {x.code: x.id for x in s.execute(select(Supplier).where(Supplier.code.in_(codes))).scalars()}
        admin = s.execute(select(AppUser).where(AppUser.email == _email("ap2"))).scalar_one()
        numbers = []
        for n in range(SCALE):
            code = codes[n % len(codes)]
            net = random.randint(1_000, 90_000) * 100
            tax = net * 18 // 100
            number = f"SCL-{n:05d}"
            numbers.append(number)
            s.add(Invoice(tenant_id=sc.tenant_id, number=number, supplier_invoice_no=number, fiscal_year="2026-27", company_code="1000", supplier_id=ids[code],
                          invoice_date=date(2026, 12, 1) + timedelta(days=n % 20), channel="PORTAL", currency="INR", net_minor=net, tax_minor=tax,
                          gross_minor=net + tax, status="POSTED", match_type="3WAY", first_pass_matched=n % 4 != 0, payment_block=False,
                          due_date=date(2026, 12, 31) + timedelta(days=n % 30), approved_by=admin.id, erp_doc_no=f"51{n:08d}",
                          posting_key=f"{CODE}|1000|{code}|{number}", posted_at=at(date(2026, 12, 5)), payment_status="UNPAID",
                          posting_date=date(2026, 12, 5), created_by=admin.id))
    return numbers


def test_fin2_payment_proposal_over_650_open_invoices_is_fast_and_the_run_pays_each_once(client, login, env):
    import time
    J["scale"] = _scale_fixture(env)
    _pin(date(2027, 3, 1), 11)
    fin = _h(login, "fin")
    started = time.perf_counter()
    r = client.get("/v1/payments/proposal?run_date=2027-03-01", headers=fin)
    proposal_s = time.perf_counter() - started
    assert r.status_code == 200, r.text
    body = r.json()
    print(f"\nproposal {proposal_s:.1f}s items={len(body['items'])} skipped={len(body['skipped'])}")
    assert len(body["items"]) + len(body["skipped"]) >= SCALE
    assert proposal_s < 20, f"proposal over {SCALE} invoices took {proposal_s:.1f}s"
    assert body["items"][0]["msme"] is True  # micro and small enterprises first
    started = time.perf_counter()
    run = client.post("/v1/payments/runs", json={"run_date": "2027-03-01", "invoice_numbers": J["scale"][:500]}, headers={**fin, "Idempotency-Key": "scale-run-1"})
    run_s = time.perf_counter() - started
    print(f"run of 500 {run_s:.1f}s")
    assert run.status_code == 200, run.text
    assert len(run.json()["paid"]) == 500 and not run.json()["skipped"]
    J["scale_run"] = run.json()["run"]
    J["scale_pay"] = [(x["payment"], x["amountMinor"]) for x in run.json()["paid"]]
    assert run_s < 120, f"payment run over 500 invoices took {run_s:.1f}s"
    again = client.post("/v1/payments/runs", json={"run_date": "2027-03-01", "invoice_numbers": J["scale"][:500]}, headers=fin)
    assert again.status_code == 200 and again.json()["paid"] == []
    _pin(date(2026, 12, 10))


def test_fin2_worklists_with_filters_stay_fast_at_650_invoices(client, login, env):
    import time
    h = _h(login, "ap1")
    for query in ("status=POSTED", "payment_status=PAID&limit=200", "msme=true&limit=100", "q=SCL-0010&limit=50", "min_gross_minor=100000&max_gross_minor=900000",
                  "supplier=F2-S03&status=POSTED", "has_open_exceptions=false&limit=200", "due_from=2027-01-01&due_to=2027-01-15&limit=200"):
        started = time.perf_counter()
        r = client.get(f"/v1/invoices?{query}", headers=h)
        elapsed = time.perf_counter() - started
        assert r.status_code == 200, (query, r.text[:200])
        assert elapsed < 10, (query, elapsed)   # solo they take about a second; the bound catches a per-invoice query, not a loaded machine
    seen, cursor, pages = set(), None, 0
    while True:
        r = client.get("/v1/invoices?limit=200" + (f"&cursor={cursor}" if cursor else ""), headers=h).json()
        pages += 1
        assert not ({i["id"] for i in r["items"]} & seen), "a page repeated an invoice"
        seen |= {i["id"] for i in r["items"]}
        cursor = r["nextCursor"]
        if not cursor:
            break
    assert len(seen) >= SCALE and pages >= 4
    started = time.perf_counter()
    assert client.get("/v1/payments?limit=200", headers=h).status_code == 200
    assert time.perf_counter() - started < 3


# ================================================================ 6. gap a: SOD-08 capturer of system-built AP documents, realised savings from a value credit note
def test_fin2_gap_a_capturer_is_recorded_for_retention_releases_and_consignment_settlements(client, login, env):
    from app.pic.platform import sod
    from app.pic.services import payables, receiving
    day = date(2026, 12, 11)
    po = _create_po(client, login, _material(), "10", "F2-ALPHA")
    with tenant_tx(J["tenant_id"]) as s:
        s.execute(select(PurchaseOrder).where(PurchaseOrder.number == po)).scalar_one().retention_pct = Decimal(10)
    _gr(client, login, po, "10", day, "DN-RET-1")
    r = _capture(client, _h(login, "ap1"), "F2-ALPHA", "RET-0001", day, po, "10", "1000.00")
    assert r.status_code == 201 and r.json()["status"] == "MATCHED", r.text
    assert _approve(client, login, r.json()["id"], "ap2").status_code == 200
    assert _post(client, login, r.json()["id"], "ap2")[0].status_code == 200
    rel = client.post(f"/v1/purchase-orders/{po}/retention-release", json={"reference": "COMPLETION-CERT-1", "reason": "work complete"}, headers=_h(login, "ap1"))
    assert rel.status_code == 201, rel.text
    sc = J["env"]
    with sc.act("ap1", at(day, 14)) as s:
        user = s.execute(select(AppUser).where(AppUser.email == _email("ap1"))).scalar_one()
        assert {x.code for x in sod.conflicts(s, "INVOICE_APPROVE", {"invoice_id": rel.json()["id"]}, user.id)} == {"SOD-08"}
        assert {x.code for x in sod.conflicts(s, "PAYMENT_APPROVE", {"invoice_id": rel.json()["id"], "supplier_id": rel.json()["supplier_id"]}, user.id)} == {"SOD-09"}
    # consignment settlement: the receipt-less ERS line, withdrawals taken from the stock ledger (stubbed here: the stock side is covered by the inventory tests)
    po2 = _create_po(client, login, _material(), "5", "F2-ALPHA")
    with tenant_tx(J["tenant_id"]) as s:
        line = s.execute(select(PoLine).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(PurchaseOrder.number == po2)).scalar_one()
        line.ers, line.ir_required = True, False
        line_id = line.id
    original = receiving.consignment_withdrawn
    receiving.consignment_withdrawn = lambda session, ids, until=None: {i: Decimal(5) for i in ids if i == line_id}
    try:
        with sc.act("ap1", at(day, 15)) as s:
            user = s.execute(select(AppUser).where(AppUser.email == _email("ap1"))).scalar_one()
            doc = payables.settle_consignment(s, supplier="F2-ALPHA", period_to=day)
            assert doc.status == "MATCHED" and doc.channel == "ERS", doc.status
            assert {x.code for x in sod.conflicts(s, "INVOICE_APPROVE", {"invoice_id": doc.id}, user.id)} == {"SOD-08"}
            number = doc.number
    finally:
        receiving.consignment_withdrawn = original
    _problem(_approve(client, login, number, "ap1"), 409, "SOD_CONFLICT")   # whoever ran the settlement cannot approve it
    assert _approve(client, login, number, "ap2").status_code == 200


def test_fin2_gap_a_realised_savings_are_net_of_a_value_credit_note(client, login, env):
    day = date(2026, 12, 12)
    material = _material()
    owner = _h(login, "owner")
    r = client.post("/v1/savings/initiatives", json={"title": "Alloy rate FY27 second pass", "category": "GENERAL", "baseline_method": "SHOULD_COST",
                                                      "annual_volume": "1000", "material": material, "baseline_price_minor": 110_000}, headers=owner)
    assert r.status_code == 201, r.text
    number = r.json()["number"]
    assert client.post(f"/v1/savings/{number}/negotiate", json={"new_price_minor": 100_000, "supplier": "F2-ALPHA", "evidence": "Rate agreed"}, headers=owner).status_code == 200
    po = _create_po(client, login, material, "10", "F2-ALPHA")
    _gr(client, login, po, "10", day, "DN-SAV-1")
    r = _capture(client, _h(login, "ap1"), "F2-ALPHA", "SAV-0001", day, po, "10", "1005.00")  # 5.00 above the PO price, inside the tolerance
    assert r.status_code == 201 and r.json()["status"] == "MATCHED", r.text
    cn = client.post(f"/v1/invoices/{r.json()['id']}/credit-notes", json={"supplier_credit_note_no": "SAV-CN-1", "note_date": day.isoformat(), "reason": "price difference",
                                                                           "lines": [{"invoice_line": 10, "qty": "10", "unit_credit_minor": 500}]}, headers=_portal(login))
    assert cn.status_code == 201, cn.text
    assert _approve(client, login, r.json()["id"], "ap2").status_code == 200
    assert _post(client, login, r.json()["id"], "ap2")[0].status_code == 200
    _tick(client, login)
    register = {e["number"]: e for e in client.get("/v1/savings", headers=owner).json()}
    # paid value 10 x 1,005.00 - 10 x 5.00 = 10,000.00 against the baseline 10 x 1,100.00 = 11,000.00: realised 1,000.00 (not 950.00 as without the credit)
    assert register[number]["realisedMinor"] == 100_000, register[number]


# ================================================================ 7. gap b: bank statements, CAMT.054, batch entries
def _stmt(name: str, **fill) -> str:
    from pathlib import Path
    text = (Path(__file__).parent / "fixtures" / "bank" / name).read_text(encoding="utf-8")
    for key, value in fill.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _upload(client, headers, text: str, dry_run: bool):
    flag = "true" if dry_run else "false"
    return client.post(f"/v1/bank-statements/import?dry_run={flag}", files={"file": ("stmt", text.encode("utf-8"), "application/octet-stream")}, headers=headers)


def test_fin2_gap_b_camt054_batch_entries_and_repeated_mt940_lines_match_individual_payments(client, login, env):
    fin = _h(login, "fin")
    _pin(date(2027, 3, 3), 9)
    pays = J["scale_pay"][10:21]
    run = J["scale_run"]
    f = client.post(f"/v1/payments/runs/{run}/file", json={"format": "NEFT_CSV"}, headers=fin)
    assert f.status_code == 201, f.text
    file_no = f.json()["number"]
    assert client.post(f"/v1/payment-files/{file_no}/status", json={"status": "SENT"}, headers=fin).status_code == 200
    money = lambda minor: f"{minor / 100:.2f}"  # noqa: E731
    mt = lambda minor: f"{minor / 100:.2f}".replace(".", ",")  # noqa: E731
    p = [x[0] for x in pays]
    a = [x[1] for x in pays]
    # CAMT.054: a debit notification for one payment
    note = _stmt("camt054_notification.xml", STMT="F2-N54-001", PAY1=p[0], AMT1=money(a[0]))
    dry = _upload(client, fin, note, True)
    assert dry.status_code == 200 and dry.json()["format"] == "CAMT054" and dry.json()["counts"] == {"READY": 1}, dry.text
    done = _upload(client, fin, note, False)
    assert done.status_code == 200 and done.json()["credited"] == 1 and done.json()["replayed"] is False, done.text
    assert _upload(client, fin, note, False).json()["replayed"] is True                                  # idempotent per statement id
    assert _upload(client, fin, note.replace(money(a[0]), money(a[0] + 1)), False).status_code in (409, 422)   # same id, other content
    # CAMT.053 batch: one entry, two transactions with their own amounts (credited), one returned transaction, one bulk credit that only names two payments
    batch = _stmt("camt053_batch.xml", STMT="F2-B53-001", PAY1=p[1], PAY2=p[2], PAY3=p[3], PAY4=p[4], PAY5=p[5], AMT1=money(a[1]), AMT2=money(a[2]),
                  AMT3=money(a[3]), BATCH_TOTAL=money(a[1] + a[2]), TOTAL_ONLY=money(a[4] + a[5]))
    dry = _upload(client, fin, batch, True).json()
    states = [(i["payment"], i["state"], i["action"], i["batch"]) for i in dry["items"]]
    assert states == [(p[1], "READY", "CREDITED", False), (p[2], "READY", "CREDITED", False), (p[3], "READY", "RETURNED", False),
                      (p[4], "READY", "CREDITED", True), (p[5], "READY", "CREDITED", True)], states
    wrong_total = _stmt("camt053_batch.xml", STMT="F2-B53-BAD", PAY1=p[1], PAY2=p[2], PAY3=p[3], PAY4=p[4], PAY5=p[5], AMT1=money(a[1]), AMT2=money(a[2]),
                        AMT3=money(a[3]), BATCH_TOTAL=money(a[1] + a[2] + 100), TOTAL_ONLY=money(a[4] + a[5]))
    _problem(_upload(client, fin, wrong_total, True), 422, "INVALID_STATEMENT")                          # the transactions do not add up to the entry
    short = _stmt("camt053_batch.xml", STMT="F2-B53-AMB", PAY1=p[1], PAY2=p[2], PAY3=p[3], PAY4=p[4], PAY5=p[5], AMT1=money(a[1]), AMT2=money(a[2]),
                  AMT3=money(a[3]), BATCH_TOTAL=money(a[1] + a[2]), TOTAL_ONLY=money(a[4] + a[5] + 5000))
    amb = _upload(client, fin, short, True).json()
    assert [i["state"] for i in amb["items"]][-1] == "AMBIGUOUS" and "totalling" in amb["items"][-1]["detail"], amb
    applied = _upload(client, fin, batch, False).json()
    assert applied["credited"] == 4 and applied["returned"] == 1 and applied["applied"] == 5, applied
    # MT940: repeated :61: lines under one batch reference, and one :61: for two payments
    mt940 = _stmt("mt940_batch.sta", STMT="F2-MT-001", PAY6=p[6], PAY7=p[7], PAY8=p[8], PAY9=p[9], AMT6=mt(a[6]), AMT7=mt(a[7]), AMT8=mt(a[8]),
                  PAY10=p[10], TOTAL_9_10=mt(a[9] + a[10]))
    r = _upload(client, fin, mt940, False)
    assert r.status_code == 200 and r.json()["credited"] == 5 and r.json()["applied"] == 5, r.text
    with tenant_tx(J["tenant_id"]) as s:
        by_number = {x.number: {"bank_status": x.bank_status, "bank_utr": x.bank_utr} for x in s.execute(select(Payment).where(Payment.number.in_(p))).scalars()}
    assert by_number[p[0]] == {"bank_status": "CREDITED", "bank_utr": "HDFCNTF2027030300001"}
    assert by_number[p[2]]["bank_utr"] == "HDFCBTX0002" and by_number[p[3]]["bank_status"] == "RETURNED"
    assert {by_number[x]["bank_utr"] for x in (p[6], p[7], p[8])} == {"HDFCBATCHMT0001"}                # one batch reference, three payments
    assert by_number[p[4]]["bank_status"] == "CREDITED" and by_number[p[10]]["bank_status"] == "CREDITED"
    _pin(date(2026, 12, 12))


# ================================================================ 8. gap c: TDS certificate cap, return quarter by payment date, challans, Form 16A data, TCS, advance
def _payment_row(number: str):
    with tenant_tx(J["tenant_id"]) as s:
        pay = s.execute(select(Payment).join(Invoice, Invoice.id == Payment.invoice_id).where(Invoice.number == number, Payment.status != "CANCELLED")).scalar_one()
        return {c.name: getattr(pay, c.name) for c in Payment.__table__.columns}


def test_fin2_gap_c_certificate_amount_cap_taxes_the_rest_at_the_section_rate(client, login, env):
    from app.pic.models import Invoice as Inv
    fin = _h(login, "fin")
    inv_a, _ = _posted_invoice(client, login, "F2-TDS", "TDS-A-1", date(2026, 12, 5), material=_material(), qty="40")
    inv_b, _ = _posted_invoice(client, login, "F2-TDS", "TDS-B-1", date(2026, 12, 8), material=_material(), qty="41")
    numbers = [_invoice(client, login, i)["number"] for i in (inv_a, inv_b)]
    J["tds_numbers"] = numbers
    cert = client.post("/v1/suppliers/F2-TDS/tds-certificates", json={"certificateNo": "CERT197-2026-01", "ratePct": "0.5", "validFrom": "2026-12-01",
                                                                        "validTo": "2027-12-31", "maxBaseMinor": 2_500_000, "note": "capped at 25,000"}, headers=fin)
    assert cert.status_code == 201, cert.text
    _problem(client.post("/v1/suppliers/F2-TDS/tds-certificates", json={"certificateNo": "CERT197-2026-02", "ratePct": "0.5", "validFrom": "2026-12-01",
                                                                         "validTo": "2027-12-31", "maxBaseMinor": -5}, headers=fin), 422)
    _pin(date(2027, 2, 15), 11)
    proposal = client.get("/v1/payments/proposal?run_date=2027-02-15&include_not_due=true&invoice=" + "&invoice=".join(numbers), headers=fin).json()
    tds = {i["invoice"]: i["tdsMinor"] for i in proposal["items"]}
    # A: 25,000.00 at 0.5 % (125.00) + 15,000.00 at 2 % (300.00); B: the cap is used up by A in the same proposal, so 41,000.00 at 2 % (820.00)
    assert tds == {numbers[0]: 42_500, numbers[1]: 82_000}, proposal
    run = client.post("/v1/payments/runs", json={"run_date": "2027-02-15", "include_not_due": True, "invoice_numbers": numbers}, headers=fin)
    assert run.status_code == 200 and {x["invoice"]: x["tdsMinor"] for x in run.json()["paid"]} == tds, run.text
    pay_a, pay_b = _payment_row(numbers[0]), _payment_row(numbers[1])
    assert pay_a["tds_certificate"] == "CERT197-2026-01" and pay_a["tds_cert_base_minor"] == 2_500_000 and pay_a["tds_base_minor"] == 4_000_000
    assert Decimal("1.06") <= pay_a["tds_rate"] <= Decimal("1.07")                      # blended rate of the split payment
    assert pay_b["tds_certificate"] is None and pay_b["tds_cert_base_minor"] == 0 and pay_b["tds_rate"] == Decimal("2")
    view = client.get("/v1/suppliers/F2-TDS/finance", headers=fin).json()["certificates"][0]
    assert view["maxBaseMinor"] == 2_500_000 and view["consumedBaseMinor"] == 2_500_000 and view["remainingBaseMinor"] == 0
    _pin(date(2026, 12, 14))


def test_fin2_d25_tds_return_follows_the_payment_date_not_the_invoice_year(client, login, env):
    fin = _h(login, "fin")
    inv_c, _ = _posted_invoice(client, login, "F2-TDS", "TDS-C-1", date(2027, 3, 20), material=_material(), qty="40")   # FY 2026-27 invoice
    number = _invoice(client, login, inv_c)["number"]
    J["tds_c"] = number
    _pin(date(2027, 4, 10), 11)                                                           # paid in FY 2027-28, quarter Q1
    run = client.post("/v1/payments/runs", json={"run_date": "2027-04-10", "include_not_due": True, "invoice_numbers": [number]}, headers=fin)
    assert run.status_code == 200 and run.json()["paid"][0]["tdsMinor"] == 80_000, run.text   # cap used up: the section rate on 40,000.00
    export = client.get("/v1/finance/tds-export?fiscal_year=2027-28&quarter=Q1&format=26Q", headers=fin)
    assert export.status_code == 200 and export.headers["X-Row-Count"] == "1" and number in export.text, export.text
    old = client.get("/v1/finance/tds-export?fiscal_year=2026-27&quarter=Q4&format=26Q", headers=fin)
    assert old.headers["X-Row-Count"] == "2" and number not in old.text
    register = client.get("/v1/finance/tds-register?fiscal_year=2027-28", headers=fin).json()
    assert [x["invoice"] for x in register["items"]] == [number] and register["totalTdsMinor"] == 80_000
    assert [x["invoice"] for x in client.get("/v1/finance/tds-register?fiscal_year=2026-27", headers=fin).json()["items"]] == J["tds_numbers"]
    _pin(date(2026, 12, 14))


def test_fin2_gap_c_challans_reconcile_deducted_against_deposited_and_form_16a_data(client, login, env):
    from app.pic.platform import finance_defaults
    fin = _h(login, "fin")
    _pin(date(2027, 5, 10), 11)
    base = {"companyCode": "1000", "fiscalYear": "2027-28", "quarter": "Q1", "section": "194C-OTH", "challanNo": "00123", "bsrCode": "6360280",
            "depositDate": "2027-05-07", "amountMinor": 50_000}
    recon = lambda: client.get("/v1/finance/tds-challans/reconciliation?fiscal_year=2027-28&quarter=Q1", headers=fin).json()   # noqa: E731
    assert recon()["rows"] == [{"companyCode": "1000", "section": "194C-OTH", "deductedMinor": 80_000, "depositedMinor": 0, "challans": 0, "differenceMinor": 80_000,
                                "status": "SHORT_DEPOSITED"}]
    assert client.post("/v1/finance/tds-challans", json=base, headers=_h(login, "ap1")).status_code == 403
    for patch, code in (({"bsrCode": "123"}, 422), ({"challanNo": "12"}, 422), ({"amountMinor": 0}, 422), ({"section": "999Z"}, 422),
                        ({"depositDate": "2027-03-31"}, 422), ({"depositDate": "2027-06-30"}, 422), ({"companyCode": "9999"}, 404)):
        assert client.post("/v1/finance/tds-challans", json={**base, **patch}, headers=fin).status_code == code, patch
    first = client.post("/v1/finance/tds-challans", json=base, headers={**fin, "Idempotency-Key": "challan-1"})
    assert first.status_code == 201, first.text
    _problem(client.post("/v1/finance/tds-challans", json=base, headers=fin), 409, "DUPLICATE_CHALLAN")
    assert recon()["rows"][0]["differenceMinor"] == 30_000 and recon()["reconciled"] is False
    second = client.post("/v1/finance/tds-challans", json={**base, "challanNo": "00124", "amountMinor": 30_000}, headers=fin)
    assert second.status_code == 201
    done = recon()
    assert done["reconciled"] is True and done["rows"][0]["differenceMinor"] == 0 and done["rows"][0]["challans"] == 2
    assert client.post(f"/v1/finance/tds-challans/{second.json()['id']}/void", json={"reason": "wrong challan keyed"}, headers=fin).status_code == 200
    assert recon()["rows"][0]["differenceMinor"] == 30_000                                       # a voided challan does not count
    # Form 16A data: the deductor's TAN is tenant data, so it is reported missing until the tax team publishes it
    data = client.get("/v1/finance/tds-certificates/data?fiscal_year=2027-28&quarter=Q1", headers=fin).json()
    cert = data["certificates"][0]
    assert data["count"] == 1 and cert["form"] == "16A" and cert["assessmentYear"] == "2028-29" and cert["deductee"]["supplier"] == "F2-TDS"
    assert cert["totals"]["taxDeductedMinor"] == 80_000 and cert["totals"]["amountPaidCreditedMinor"] == 4_000_000 and len(cert["payments"]) == 1
    assert cert["deductee"]["pan"] == "AABCT2234M" and cert["missingMandatory"] == ["deductor.tan", "deductor.pan"]
    assert [c["challanSerialNo"] for c in cert["challans"]] == ["00123"] and cert["totals"]["taxDepositedMinor"] == 50_000
    csv_text = client.get("/v1/finance/tds-certificates/data?fiscal_year=2027-28&quarter=Q1&format=csv", headers=fin)
    assert csv_text.status_code == 200 and csv_text.text.splitlines()[0].startswith("Financial Year,Assessment Year") and "AABCT2234M" in csv_text.text
    kit.rule_version(J["env"], "TDS", "2027.1-FIN2", date(2027, 5, 1),
                     {**finance_defaults.TDS_DEFAULT, "deductor": {"tan": "BLRA12345B", "pan": "AAKCD4821M", "name": "Finance Second Pass Industries Pvt Ltd", "address": "Bengaluru"}},
                     "Finance second pass: deductor TAN")
    again = client.get("/v1/finance/tds-certificates/data?fiscal_year=2027-28&quarter=Q1&supplier=F2-TDS", headers=fin).json()["certificates"][0]
    assert again["missingMandatory"] == [] and again["deductor"]["tan"] == "BLRA12345B"
    assert client.get("/v1/finance/tds-certificates/data?fiscal_year=2027-28&quarter=Q1", headers=_h(login, "ap1")).status_code == 403
    _pin(date(2026, 12, 14))


def test_fin2_gap_c_tcs_flag_is_off_by_default_and_carried_to_the_erp_payload(client, login, env):
    from app.pic.platform import finance_defaults
    fin = _h(login, "fin")
    inv0, _ = _posted_invoice(client, login, "F2-TDS", "TCS-OFF-1", date(2027, 5, 4), material=_material(), qty="42")
    with tenant_tx(J["tenant_id"]) as s:
        assert s.execute(select(Invoice.tcs_minor, Invoice.tcs_section).where(Invoice.id == uuid.UUID(inv0))).one() == (0, None)
    tcs = {"enabled": True, "section": "206C(1H)", "ratePct": 1, "annualThresholdMinor": None, "addToPayable": False}
    kit.rule_version(J["env"], "TDS", "2027.2-FIN2", date(2027, 5, 11), {**finance_defaults.TDS_DEFAULT, "tcs": tcs,
                                                                          "deductor": {"tan": "BLRA12345B", "pan": "AAKCD4821M", "name": None, "address": None}},
                     "Finance second pass: TCS on")
    inv1, _ = _posted_invoice(client, login, "F2-TDS", "TCS-ON-1", date(2027, 5, 12), material=_material(), qty="43")
    with tenant_tx(J["tenant_id"]) as s:
        row = s.execute(select(Invoice).where(Invoice.id == uuid.UUID(inv1))).scalar_one()
        assert row.tcs_section == "206C(1H)" and row.tcs_rate == Decimal("1") and row.tcs_minor == row.gross_minor // 100, (row.tcs_minor, row.gross_minor)
        message = s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == row.posting_key)).scalar_one()
        assert message.payload["tcsMinor"] == row.tcs_minor and message.payload["tcsSection"] == "206C(1H)"
        gross, tcs_minor = row.gross_minor, row.tcs_minor
    _pin(date(2027, 6, 15), 11)
    p = client.get("/v1/payments/proposal?run_date=2027-06-15&invoice=" + _invoice(client, login, inv1)["number"], headers=fin).json()["items"][0]
    assert p["amountMinor"] == gross - p["tdsMinor"], p                                             # addToPayable false: TCS is posted, not paid with the invoice
    _pin(date(2026, 12, 14))


def test_fin2_gap_c_tds_already_deducted_on_an_advance_is_not_deducted_again_on_the_bill(client, login, env):
    from app.pic.models import AdvancePayment, AdvanceRecovery
    from app.pic.services import finance_controls
    sc = J["env"]
    with sc.act("fin", at(date(2027, 6, 20), 10)) as s:
        user = s.execute(select(AppUser).where(AppUser.email == _email("fin"))).scalar_one()
        supplier = s.execute(select(Supplier).where(Supplier.code == "F2-TDS")).scalar_one()
        po = s.execute(select(PurchaseOrder).where(PurchaseOrder.supplier_id == supplier.id)).scalars().first()
        common = dict(tenant_id=sc.tenant_id, fiscal_year="2027-28", company_code="1000", supplier_id=supplier.id, po_id=po.id, invoice_date=date(2027, 6, 20), currency="INR")
        doc = Invoice(number="ADV-F2-T1", supplier_invoice_no="ADV-F2-REF-1", channel="ADVANCE", net_minor=1_000_000, tax_minor=180_000, gross_minor=1_180_000, status="PAID",
                      match_type="ADVANCE", tds_section="194C-OTH", tds_rate=Decimal(2), tds_base_minor=1_000_000, created_by=user.id, **common)
        bill = Invoice(number="BILL-F2-T1", supplier_invoice_no="BILL-F2-REF-1", channel="PORTAL", net_minor=5_000_000, tax_minor=900_000, gross_minor=5_900_000, status="MATCHED",
                       match_type="3WAY", created_by=user.id, **common)
        s.add_all([doc, bill])
        s.flush()
        advance = AdvancePayment(tenant_id=sc.tenant_id, number="ADV-F2-T1", po_id=po.id, supplier_id=supplier.id, net_minor=1_000_000, tax_minor=180_000, gross_minor=1_180_000,
                                 recovery_pct=Decimal(10), recovered_minor=0, status="PAID", reference="ADV-F2-REF-1", invoice_id=doc.id, requested_by=user.id, created_by=user.id)
        s.add(advance)
        s.flush()
        recovery = AdvanceRecovery(tenant_id=sc.tenant_id, advance_id=advance.id, invoice_id=bill.id, amount_minor=590_000, status="PLANNED", created_by=user.id)
        s.add(recovery)
        s.flush()
        with_advance = finance_controls.compute_tds(s, bill, supplier)
        recovery.status = "CANCELLED"
        s.flush()
        without = finance_controls.compute_tds(s, bill, supplier)
        # the 5,90,000.00-gross bill recovers 5,900.00 of the advance (5,000.00 net of GST), which was taxed when the advance was paid
        assert without["baseMinor"] == 5_000_000 and with_advance["baseMinor"] == 4_500_000, (without, with_advance)
        s.rollback()


# ================================================================ 9. gap d: MSME 15 days without a written agreement, interest accrual record
def test_fin2_gap_d_msme_fifteen_day_rule_and_interest_accrual(client, login, env):
    from app.pic.models import MsmeInterest, OutboxEvent
    from app.pic.platform import finance_defaults
    supmgr, fin = _h(login, "supmgr"), _h(login, "fin")
    etag = client.get("/v1/suppliers/F2-MICRO/finance", headers=supmgr).headers["ETag"]
    body = {"msmeClass": "SMALL", "udyamNo": "UDYAM-KA-03-0012345", "msmeWrittenAgreement": False, "reason": "No written payment agreement on file"}
    r = client.put("/v1/suppliers/F2-MICRO/finance", json=body, headers={**supmgr, "If-Match": etag})
    assert r.status_code == 200 and r.json()["msmeWrittenAgreement"] is False, r.text
    inv, _ = _posted_invoice(client, login, "F2-MICRO", "MSME-0001", date(2026, 12, 14), material=_material(), qty="20")
    number = _invoice(client, login, inv)["number"]
    with tenant_tx(J["tenant_id"]) as s:
        row = s.execute(select(Invoice).where(Invoice.id == uuid.UUID(inv))).scalar_one()
        assert row.acceptance_date == date(2026, 12, 14) and row.due_date == date(2026, 12, 29) and row.msme_capped is True   # 15 days, not 45 (and not N60)
        gross = row.gross_minor
    kit.rule_version(J["env"], "MSME", "2027.1-FIN2", date(2026, 12, 15), {**finance_defaults.MSME_DEFAULT, "bankRatePct": 6.5}, "Finance second pass: RBI bank rate")
    _pin(date(2027, 1, 28), 11)
    run = client.post("/v1/payments/runs", json={"run_date": "2027-01-28", "invoice_numbers": [number]}, headers=fin)
    assert run.status_code == 200, run.text
    paid = run.json()["paid"][0]
    expected = int((Decimal(gross) * ((1 + Decimal("6.5") * 3 / 100 / 12) ** (Decimal(30) / 30) - 1)).quantize(Decimal(1)))
    assert paid["msmeInterestMinor"] == expected == 38_350, (paid, expected)
    with tenant_tx(J["tenant_id"]) as s:
        rec = s.execute(select(MsmeInterest).join(Invoice, Invoice.id == MsmeInterest.invoice_id).where(Invoice.number == number)).scalar_one()
        assert (rec.days_late, rec.interest_minor, rec.principal_minor, rec.rate_pct, rec.status) == (30, expected, gross, Decimal("19.500"), "ACCRUED")
        assert s.execute(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.topic == "msme.interest.accrued")).scalar() >= 1
        message = s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == f"PAY|{paid['payment']}")).scalar_one()
        assert message.payload["msmeInterestMinor"] == expected
    register = client.get("/v1/finance/msme-interest?supplier=F2-MICRO", headers=fin).json()
    assert [x["interestMinor"] for x in register["items"]] == [expected] and register["totalMinor"] == expected
    _pin(date(2026, 12, 14))


# ================================================================ 10. closed-period edges
def test_fin2_closed_period_edges_last_and_first_day(client, login, env):
    fin = _h(login, "fin")
    slash = _invoice(client, login, J["slash_invoice"])["number"]
    _pin(date(2026, 12, 31), 10)
    _problem(client.post("/v1/finance/periods/2026-12/close", json={"companyCode": "1000"}, headers=fin), 409, "PERIOD_NOT_ENDED")   # the last day is not over
    _pin(date(2027, 1, 1), 10)
    r = client.post("/v1/finance/periods/2026-12/close", json={"companyCode": "1000", "reason": "December close"}, headers=fin)
    assert r.status_code == 200 and r.json()["status"] == "CLOSED", r.text
    last = client.get(f"/v1/payments/proposal?run_date=2026-12-31&include_not_due=true&invoice={slash}", headers=fin).json()
    assert last["items"] == [] and "closed" in last["skipped"][0]["reason"], last                           # a payment dated on the last day is refused
    first = client.get(f"/v1/payments/proposal?run_date=2027-01-01&include_not_due=true&invoice={slash}", headers=fin).json()
    assert [i["invoice"] for i in first["items"]] == [slash], first                                          # the first day of the next period is open
    assert client.post("/v1/finance/periods/2026-12/reopen", json={"companyCode": "1000", "reason": "continue the second pass tests"}, headers=fin).status_code == 200
    _pin(date(2026, 12, 14))


# ================================================================ 11. gap e: foreign payment, realised exchange difference, SWIFT data, pain.001
def test_fin2_gap_e_foreign_payment_realised_fx_swift_data_and_pain001(client, login, env):
    fin, supmgr = _h(login, "fin"), _h(login, "supmgr")
    with tenant_tx(J["tenant_id"]) as s:
        s.add(FxRate(tenant_id=J["tenant_id"], from_ccy="USD", to_ccy="INR", rate=Decimal("83.25"), valid_from=date(2026, 12, 1), source="TEST"))
        s.add(FxRate(tenant_id=J["tenant_id"], from_ccy="USD", to_ccy="INR", rate=Decimal("84.00"), valid_from=date(2027, 2, 10), source="TEST"))
    po = _create_po(client, login, _material(), "10", "F2-GLOBAL")
    with tenant_tx(J["tenant_id"]) as s:
        s.execute(select(PurchaseOrder).where(PurchaseOrder.number == po)).scalar_one().currency = "USD"
    day = date(2026, 12, 13)
    _gr(client, login, po, "10", day, "DN-FX-1")
    r = _capture(client, _h(login, "ap1"), "F2-GLOBAL", "FX-0001", day, po, "10", "1000.00")
    assert r.status_code == 201 and r.json()["status"] == "MATCHED" and r.json()["currency"] == "USD", r.text
    assert _approve(client, login, r.json()["id"], "ap2").status_code == 200
    assert _post(client, login, r.json()["id"], "ap2")[0].status_code == 200
    usd = r.json()["number"]
    slash = _invoice(client, login, J["slash_invoice"])["number"]
    _pin(date(2027, 2, 12), 11)
    q = f"run_date=2027-02-12&include_not_due=true&invoice={usd}&invoice={slash}"
    proposal = client.get(f"/v1/payments/proposal?{q}", headers=fin).json()
    assert [i["invoice"] for i in proposal["items"]] == [slash]
    assert proposal["skipped"][0]["invoice"] == usd and "foreign beneficiary bank" in proposal["skipped"][0]["reason"] and "SWIFT" in proposal["skipped"][0]["reason"]
    with tenant_tx(J["tenant_id"]) as s:   # the beneficiary bank is completed (in production through the dual-approved bank change)
        account = s.execute(select(SupplierBankAccount).join(Supplier, Supplier.id == SupplierBankAccount.supplier_id).where(Supplier.code == "F2-GLOBAL")).scalar_one()
        account.swift_bic, account.charge_bearer, account.purpose_code, account.intermediary_bic = "BOFAUS3N", "SHAR", "P0802", "CITIUS33"
    run = client.post("/v1/payments/runs", json={"run_date": "2027-02-12", "include_not_due": True, "invoice_numbers": [usd, slash]}, headers=fin)
    assert run.status_code == 200 and len(run.json()["paid"]) == 2, run.text
    pay = _payment_row(usd)
    assert pay["currency"] == "USD" and pay["amount_minor"] == 1_180_000 and pay["fx_rate"] == Decimal("84")
    assert pay["amount_group_minor"] == 99_120_000 and pay["fx_gain_loss_minor"] == -885_000        # booked 83.25, paid at 84.00: a loss of 8,850.00 INR
    with tenant_tx(J["tenant_id"]) as s:
        message = s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == f"PAY|{pay['number']}")).scalar_one()
        assert message.payload["fxGainLossMinor"] == -885_000 and message.payload["amountGroupMinor"] == 99_120_000 and message.payload["currency"] == "USD"
        assert _payment_row(slash)["fx_rate"] is None
    run_ref = run.json()["run"]
    _problem(client.post(f"/v1/payments/runs/{run_ref}/file", json={"format": "NEFT_CSV"}, headers=fin), 422, "NEFT_INR_ONLY")
    with tenant_tx(J["tenant_id"]) as s:
        s.execute(select(SupplierBankAccount).join(Supplier, Supplier.id == SupplierBankAccount.supplier_id).where(Supplier.code == "F2-GLOBAL")).scalar_one().swift_bic = None
    _problem(client.post(f"/v1/payments/runs/{run_ref}/file", json={"format": "ISO20022_PAIN001"}, headers=fin), 409, "PAYMENT_FILE_INCOMPLETE")
    with tenant_tx(J["tenant_id"]) as s:
        s.execute(select(SupplierBankAccount).join(Supplier, Supplier.id == SupplierBankAccount.supplier_id).where(Supplier.code == "F2-GLOBAL")).scalar_one().swift_bic = "BOFAUS3N"
    f = client.post(f"/v1/payments/runs/{run_ref}/file", json={"format": "ISO20022_PAIN001"}, headers=fin)
    assert f.status_code == 201, f.text
    xml = client.get(f"/v1/payment-files/{f.json()['number']}/content", headers=fin).text
    assert "pain.001.001.09" in xml and "<BICFI>BOFAUS3N</BICFI>" in xml and "<ChrgBr>SHAR</ChrgBr>" in xml and "<Cd>P0802</Cd>" in xml, xml
    assert "<IntrmyAgt1>" in xml and "CITIUS33" in xml
    assert xml.count("<PmtInf>") == 2 and 'Ccy="USD"' in xml and 'Ccy="INR"' in xml                    # one PmtInf per currency (a debit account has one currency)
    # the dual-approved bank change carries the foreign details and refuses an incomplete or mixed-up set
    body = {"bank_account": "US99887766554433", "holder_name": "Global Forge Two LLC", "country": "US", "swift_bic": "BOFAUS3N", "charge_bearer": "SHAR"}
    _problem(client.post("/v1/suppliers/F2-GLOBAL/bank-changes", json=body, headers=supmgr), 422)
    ok = client.post("/v1/suppliers/F2-GLOBAL/bank-changes", json={**body, "purpose_code": "P0802"}, headers=supmgr)
    assert ok.status_code == 201, ok.text
    _problem(client.post("/v1/suppliers/F2-ALPHA/bank-changes", json={"bank_account": "50100012349999", "ifsc": "HDFC0000001", "holder_name": "Alpha Alloys", "swift_bic": "BOFAUS3N"},
                         headers=supmgr), 422)
    _pin(date(2026, 12, 14))


# ================================================================ 12. GST tax heads and reverse charge
def test_fin2_gst_tax_heads_follow_the_place_of_supply(client, login, env):
    day = date(2026, 12, 14)
    inv = _big_invoice(client, login, "GST-INTRA-1", "15", day)                      # supplier and plant in state 29: CGST + SGST
    assert inv["status"] == "MATCHED"
    with tenant_tx(J["tenant_id"]) as s:
        row = s.execute(select(Invoice).where(Invoice.id == uuid.UUID(inv["id"]))).scalar_one()
        assert (row.place_of_supply, row.igst_minor) == ("29", 0) and row.cgst_minor + row.sgst_minor == row.tax_minor and row.cgst_minor == row.tax_minor // 2
    po = _create_po(client, login, _material(), "20", "F2-MUM")                       # supplier in state 27 delivering to a plant in state 29: IGST
    _gr(client, login, po, "20", day, "DN-MUM-1")
    wrong = _capture(client, _h(login, "ap1"), "F2-MUM", "MUM-0001", day, po, "10", "1000.00", extra={"cgst_minor": 90_000, "sgst_minor": 90_000})
    assert wrong.status_code == 201 and wrong.json()["status"] == "EXCEPTION", wrong.text
    exc = client.get(f"/v1/invoices/{wrong.json()['id']}", headers=_h(login, "ap1")).json()["exceptions"]
    assert exc[0]["type"] == "TAX" and "IGST is due" in exc[0]["detail"], exc
    _problem(_capture(client, _h(login, "ap1"), "F2-MUM", "MUM-0002", day + timedelta(days=5), po, "11", "1000.00", extra={"cgst_minor": 1, "igst_minor": 1}), 422, "VALIDATION_FAILED")
    right = _capture(client, _h(login, "ap1"), "F2-MUM", "MUM-0003", day + timedelta(days=10), po, "12", "1000.00", extra={"igst_minor": 216_000})
    assert right.status_code == 201 and right.json()["status"] == "MATCHED", right.text
    derived = _capture(client, _h(login, "ap1"), "F2-MUM", "MUM-0004", day + timedelta(days=20), po, "6", "1000.00")
    assert derived.status_code == 201 and derived.json()["status"] == "MATCHED"
    with tenant_tx(J["tenant_id"]) as s:
        for ref, (cgst, igst) in ((right.json()["id"], (0, 216_000)), (derived.json()["id"], (0, 108_000))):
            row = s.execute(select(Invoice).where(Invoice.id == uuid.UUID(ref))).scalar_one()
            assert (row.place_of_supply, row.cgst_minor, row.sgst_minor, row.igst_minor) == ("29", cgst, 0, igst)


def test_fin2_gst_reverse_charge_supply_carries_no_supplier_tax(client, login, env):
    kit.rule_version(J["env"], "GST-RCM", "2026.1-FIN2", date(2026, 12, 1), {"hsnPrefixes": ["9965"], "unregisteredSupplier": False}, "Finance second pass: reverse charge on GTA")
    day = date(2026, 12, 15)
    po = _create_po(client, login, "F2-MAT-RCM", "10", "F2-ALPHA")
    _gr(client, login, po, "10", day, "DN-RCM-1")
    r = _capture(client, _h(login, "ap1"), "F2-ALPHA", "RCM-0001", day, po, "5", "1000.00")
    assert r.status_code == 201 and r.json()["status"] == "MATCHED", r.text
    with tenant_tx(J["tenant_id"]) as s:
        row = s.execute(select(Invoice).where(Invoice.id == uuid.UUID(r.json()["id"]))).scalar_one()
        assert (row.tax_minor, row.gross_minor, row.net_minor) == (0, 500_000, 500_000) and row.reverse_charge is True and row.rcm_tax_minor == 90_000
    bad = _capture(client, _h(login, "ap1"), "F2-ALPHA", "RCM-0002", day + timedelta(days=6), po, "3", "1000.00", extra={"tax_minor": 54_000})   # supplier charged GST
    assert bad.status_code == 201 and bad.json()["status"] == "EXCEPTION", bad.text
    exc = client.get(f"/v1/invoices/{bad.json()['id']}", headers=_h(login, "ap1")).json()["exceptions"][0]
    assert exc["type"] == "TAX" and exc["delta"]["reverseCharge"] is True and "Reverse charge" in exc["detail"]
    assert _approve(client, login, r.json()["id"], "ap2").status_code == 200
    assert _post(client, login, r.json()["id"], "ap2")[0].status_code == 200
    with tenant_tx(J["tenant_id"]) as s:
        message = s.execute(select(IntegrationMessage).where(IntegrationMessage.object_id == uuid.UUID(r.json()["id"]), IntegrationMessage.message_type == "SUPPLIER_INVOICE")).scalar_one()
        assert message.payload["reverseCharge"] is True and message.payload["rcmTaxMinor"] == 90_000 and message.payload["taxHeads"]["igst"] == 0


# ================================================================ 13. duplicates prevented (evidence), IRN uniqueness, KPIs
def test_fin2_duplicates_refused_at_capture_leave_evidence_and_count_in_the_kpi(client, login, env):
    day = date(2026, 12, 16)
    ap1, admin = _h(login, "ap1"), _h(login, "admin")
    first = _capture(client, ap1, "F2-ALPHA", "IRN-0001", day, J["po_big"], "16", "1000.00", channel="E_INVOICE", irn="a" * 64)
    assert first.status_code == 201, first.text
    again = _capture(client, ap1, "F2-ALPHA", "IRN-0002", day + timedelta(days=9), J["po_big"], "17", "1000.00", channel="E_INVOICE", irn="a" * 64)
    _problem(again, 409, "DUPLICATE_IRN")
    same_no = _capture(client, ap1, "F2-ALPHA", "  IRN-0001 ", day + timedelta(days=9), J["po_big"], "18", "1000.00")        # whitespace is not a different number
    _problem(same_no, 409, "DUPLICATE_INVOICE")
    trail = client.get(f"/v1/audit/INVOICE/{first.json()['id']}", headers=admin).json()
    actions = [e["action"] for e in (trail["items"] if isinstance(trail, dict) else trail)]
    assert actions.count("DUPLICATE_BLOCKED") == 2, actions
    kpis = {i["code"]: i for i in client.get("/v1/kpis?module=M10&trend=false", headers=_h(login, "fin")).json()["items"]}
    for code in ("FIRST_PASS_MATCH", "EXCEPTION_CYCLE", "DUPLICATES_PREVENTED", "DISCOUNT_CAPTURE", "DPO", "TOUCHLESS_INVOICE", "MSME_ON_TIME", "EXCEPTION_AGEING"):
        assert f"M10.{code}" in kpis or code in kpis, (code, sorted(kpis))
    dup = kpis.get("M10.DUPLICATES_PREVENTED") or kpis["DUPLICATES_PREVENTED"]
    assert float(dup["value"]) >= 2


# ================================================================ 14. quantity tolerance by amount (last: it changes the tenant's DMN-03)
def test_fin2_quantity_tolerance_by_absolute_units(client, login, env):
    day = date(2026, 12, 17)
    po1 = _create_po(client, login, _material(), "20", "F2-ALPHA")
    _gr(client, login, po1, "20", day, "DN-QTY-1")
    before = _capture(client, _h(login, "ap1"), "F2-ALPHA", "QTY-0001", day, po1, "22", "1000.00")
    assert before.json()["status"] == "EXCEPTION"                                          # default DMN-03: quantity 0 %
    kit.rule_version(J["env"], "DMN-03", "2026.9-FIN2-QTY", date(2026, 12, 17), {"qtyAbs": 2}, "Finance second pass: two units over-invoicing allowed")
    po2 = _create_po(client, login, _material(), "20", "F2-ALPHA")
    _gr(client, login, po2, "20", day, "DN-QTY-2")
    inside = _capture(client, _h(login, "ap1"), "F2-ALPHA", "QTY-0002", day + timedelta(days=5), po2, "22", "1000.00")
    assert inside.json()["status"] == "MATCHED", inside.text
    po3 = _create_po(client, login, _material(), "20", "F2-ALPHA")
    _gr(client, login, po3, "20", day, "DN-QTY-3")
    beyond = _capture(client, _h(login, "ap1"), "F2-ALPHA", "QTY-0003", day + timedelta(days=10), po3, "23", "1000.00")
    assert beyond.json()["status"] == "EXCEPTION"
    _pin(date(2026, 12, 14))


# ================================================================ 15. service issues found while building the finance data pack
def test_fin2_empty_payment_selection_is_refused_not_read_as_pay_everything(client, login, env):
    fin = _h(login, "fin")
    for body in ({"run_date": "2027-02-20", "invoice_numbers": []}, {"run_date": "2027-02-20", "supplier_codes": []}):
        _problem(client.post("/v1/payments/runs", json=body, headers=fin), 422, "EMPTY_SELECTION")
    assert client.get("/v1/payments/proposal?run_date=2027-02-20", headers=fin).status_code == 200      # no filter at all is still "everything due"


def test_fin2_a_payment_block_loaded_from_the_erp_can_be_lifted_by_finance_and_by_unblocking_the_supplier(client, login, env):
    day = date(2026, 12, 18)
    inv, _ = _posted_invoice(client, login, "F2-BETA", "BLK-0001", day, material=_material(), qty="9")
    number = _invoice(client, login, inv)["number"]
    with tenant_tx(J["tenant_id"]) as s:
        s.execute(select(Invoice).where(Invoice.id == uuid.UUID(inv))).scalar_one().payment_block = True        # as the ERP load leaves it: no audit event explains it
    body = {"reason": "Block came with the SAP load; cleared with the vendor"}
    assert client.post(f"/v1/invoices/{inv}/payment-block/release", json=body, headers=_h(login, "ap1")).status_code == 403
    _problem(client.post(f"/v1/invoices/{inv}/payment-block/release", json={"reason": "x"}, headers=_h(login, "fin")), 422)
    r = client.post(f"/v1/invoices/{inv}/payment-block/release", json=body, headers=_h(login, "fin"))
    assert r.status_code == 200 and r.json()["payment_block"] is False, r.text
    _problem(client.post(f"/v1/invoices/{inv}/payment-block/release", json=body, headers=_h(login, "fin")), 409)
    trail = client.get(f"/v1/audit/INVOICE/{inv}", headers=_h(login, "admin")).json()
    assert "PAYMENT_BLOCK_LIFTED" in [e["action"] for e in (trail["items"] if isinstance(trail, dict) else trail)]
    # a blocked supplier: the block of every open invoice is lifted by the unblock, also when no audit event lists them
    inv2, _ = _posted_invoice(client, login, "F2-BETA", "BLK-0002", day + timedelta(days=5), material=_material(), qty="11")
    with tenant_tx(J["tenant_id"]) as s:
        s.execute(select(Invoice).where(Invoice.id == uuid.UUID(inv2))).scalar_one().payment_block = True
        s.execute(select(Supplier).where(Supplier.code == "F2-BETA")).scalar_one().status = "BLOCKED"
    out = client.post("/v1/suppliers/F2-BETA/unblock", json={"reason": "Vendor cleared by the bank call-back"}, headers=_h(login, "supmgr"))
    assert out.status_code == 200 and _invoice(client, login, inv2)["number"] in out.json()["paymentBlockLifted"], out.text
    assert _invoice(client, login, inv2)["payment_block"] is False


def test_fin2_foreign_supplier_invoice_skips_the_indian_rate_master_and_the_limit_is_compared_in_rupees(client, login, env):
    from app.pic.services import gst
    day = date(2026, 12, 19)
    po = _create_po(client, login, _material(), "2", "F2-GLOBAL")
    with tenant_tx(J["tenant_id"]) as s:
        s.execute(select(PurchaseOrder).where(PurchaseOrder.number == po)).scalar_one().currency = "USD"
    _gr(client, login, po, "2", day, "DN-IMP-1")
    original = gst.check
    gst.check = lambda *a, **k: (_ for _ in ()).throw(AssertionError("the CBIC rate master must not judge a foreign supplier's invoice"))
    try:
        r = _capture(client, _h(login, "ap1"), "F2-GLOBAL", "IMP-0001", day, po, "2", "1000.00")
    finally:
        gst.check = original
    assert r.status_code == 201 and r.json()["status"] == "MATCHED", r.text
    # USD 2,360.00 is 236,000 in minor units: under the 10,000.00 INR limit of the approver if compared as it stands, over it at 83.25
    _problem(_approve(client, login, r.json()["id"], "aplimit"), 403, "VALUE_LIMIT_EXCEEDED")
    assert _approve(client, login, r.json()["id"], "ap2").status_code == 200


def test_fin2_a_refused_posting_into_a_closed_period_leaves_an_audit_event(client, login, env):
    fin = _h(login, "fin")
    _pin(date(2027, 1, 5), 10)
    closed = client.post("/v1/finance/periods/2026-12/close", json={"companyCode": "1000", "reason": "December close for the refusal test"}, headers=fin)
    assert closed.status_code == 200, closed.text
    _pin(date(2026, 12, 20), 10)                                                       # the business date lies inside the closed period
    note = {"supplier_credit_note_no": "CLOSED-CN-1", "note_date": "2026-12-20", "reason": "late credit", "lines": [{"invoice_line": 10, "qty": "1"}]}
    _problem(client.post(f"/v1/invoices/{J['slash_invoice']}/credit-notes", json=note, headers=_portal(login)), 409, "PERIOD_CLOSED")
    from app.pic.models import AuditEvent
    with tenant_tx(J["tenant_id"]) as s:
        events = s.execute(select(AuditEvent).where(AuditEvent.object_type == "POSTING_PERIOD", AuditEvent.object_id == uuid.UUID(closed.json()["id"]),
                                                    AuditEvent.action == "POSTING_REFUSED")).scalars().all()
        assert events and "credit note" in events[0].after["what"] and events[0].object_ref == "1000/2026-12", [e.after for e in events]
    _pin(date(2027, 1, 5), 10)
    assert client.post("/v1/finance/periods/2026-12/reopen", json={"companyCode": "1000", "reason": "reopen after the refusal test"}, headers=fin).status_code == 200
    _pin(date(2026, 12, 14))


# ================================================================ 16. findings of the browser pass over the finance screens
def test_fin2_proposal_and_run_expose_the_tax_parts_they_compute(client, login, env):
    fin = _h(login, "fin")
    inv, _ = _posted_invoice(client, login, "F2-TDS", "EXP-0001", date(2026, 12, 21), material=_material(), qty="44")
    number = _invoice(client, login, inv)["number"]
    with tenant_tx(J["tenant_id"]) as s:
        stored = s.execute(select(Invoice.tds_base_minor).where(Invoice.id == uuid.UUID(inv))).scalar_one()
    _pin(date(2027, 2, 25), 11)
    item = client.get(f"/v1/payments/proposal?run_date=2027-02-25&include_not_due=true&invoice={number}", headers=fin).json()["items"][0]
    keys = ("tdsMinor", "tcsMinor", "tdsCertificate", "tdsCertBaseMinor", "tdsBaseMinor")
    assert all(k in item for k in keys), item
    assert item["tdsBaseMinor"] == stored > 0 and item["tcsMinor"] == 0 and item["tdsCertBaseMinor"] == 0 and item["tdsCertificate"] is None
    paid = client.post("/v1/payments/runs", json={"run_date": "2027-02-25", "include_not_due": True, "invoice_numbers": [number]}, headers=fin).json()["paid"][0]
    assert all(k in paid for k in keys) and paid["tdsBaseMinor"] == stored and paid["tdsMinor"] == item["tdsMinor"]
    _pin(date(2026, 12, 14))


def test_fin2_credit_and_debit_notes_dated_into_a_closed_period_are_refused(client, login, env):
    fin = _h(login, "fin")
    _pin(date(2027, 1, 5), 10)
    closed = client.post("/v1/finance/periods/2026-11/close", json={"companyCode": "1000", "reason": "November close for the dated-document test"}, headers=fin)
    assert closed.status_code == 200, closed.text
    _pin(date(2026, 12, 14), 10)                                        # today is in an open period; the documents carry a date in the closed one
    cn = {"supplier_credit_note_no": "CLOSED-CN-NOV", "note_date": "2026-11-15", "reason": "late credit", "lines": [{"invoice_line": 10, "qty": "1"}]}
    _problem(client.post(f"/v1/invoices/{J['slash_invoice']}/credit-notes", json=cn, headers=_portal(login)), 409, "PERIOD_CLOSED")
    dn = {"supplier_debit_note_no": "CLOSED-DN-NOV", "note_date": "2026-11-15", "reason": "freight", "lines": [
        {"kind": "CHARGE", "charge": "FREIGHT", "description": "Freight", "amount_minor": 10_000, "gst_rate": "18", "hsn": "996511"}]}
    _problem(client.post(f"/v1/invoices/{J['slash_invoice']}/debit-notes", json=dn, headers=_portal(login)), 409, "PERIOD_CLOSED")
    ok = client.post(f"/v1/invoices/{J['slash_invoice']}/credit-notes", json={**cn, "supplier_credit_note_no": "OPEN-CN-DEC", "note_date": "2026-12-14"},
                     headers=_portal(login))
    assert ok.status_code == 201, ok.text                               # the same note dated in the open period is accepted
    # finance sees the refusals on the period list (no audit scope needed)
    period = next(x for x in client.get("/v1/finance/periods?company_code=1000", headers=fin).json()["items"] if x["period"] == "2026-11")
    assert period["refusedAttempts"]["count"] == 2 and period["refusedAttempts"]["lastActor"] and period["refusedAttempts"]["lastAt"], period
    assert client.get("/v1/finance/periods?company_code=1000", headers=fin).json()["items"][0]["refusedAttempts"]["count"] >= 0
    _pin(date(2027, 1, 5), 10)
    assert client.post("/v1/finance/periods/2026-11/reopen", json={"companyCode": "1000", "reason": "reopen after the dated-document test"}, headers=fin).status_code == 200
    _pin(date(2026, 12, 14))


def test_fin2_bank_statement_items_name_their_bank_entry_and_amounts_are_in_rupees(client, login, env):
    from app.pic.services import bank_statement
    stmt = _stmt("camt053_batch.xml", STMT="F2-ENTRY-001", PAY1="PAY-A", PAY2="PAY-B", PAY3="PAY-C", PAY4="PAY-D", PAY5="PAY-E", AMT1="100.00", AMT2="50.50",
                 AMT3="10.00", BATCH_TOTAL="150.50", TOTAL_ONLY="228675.97")
    parsed = bank_statement.parse(stmt.encode())
    assert len(parsed["entries"]) == 4                                  # the two-transaction batch entry is split, the bulk credit stays one entry
    refs = [e["batchRef"] for e in parsed["entries"]]
    assert refs[0] == refs[1] == "HDFCBATCH2027030400001" and refs[2] == "HDFCRTNB2027030500002" and refs[3] == "HDFCBATCH2027030400003"
    fin = _h(login, "fin")
    items = _upload(client, fin, stmt, True).json()["items"]
    assert [i["entry"] for i in items][:2] == ["HDFCBATCH2027030400001"] * 2 and items[2]["entry"] == "HDFCRTNB2027030500002"
    assert all(i["entry"] for i in items)
    ambiguous = _stmt("camt053_batch.xml", STMT="F2-ENTRY-002", PAY1="PAY-A", PAY2="PAY-B", PAY3="PAY-C", PAY4=J["scale_pay"][30][0], PAY5=J["scale_pay"][31][0],
                      AMT1="100.00", AMT2="50.50", AMT3="10.00", BATCH_TOTAL="150.50", TOTAL_ONLY="228675.97")
    detail = [i for i in _upload(client, fin, ambiguous, True).json()["items"] if i["state"] == "AMBIGUOUS"][0]["detail"]
    assert "INR 2" in detail and "paise" not in detail and "totalling INR" in detail, detail


def test_fin2_kpi_strip_with_trend_is_fast_over_the_scale_data(client, login, env):
    import time
    fin = _h(login, "fin")
    started = time.perf_counter()
    r = client.get("/v1/kpis?module=M10&trend=true", headers=fin)
    elapsed = time.perf_counter() - started
    assert r.status_code == 200 and len(r.json()["items"]) >= 8, r.text[:200]
    assert not [i for i in r.json()["items"] if "error" in (i.get("detail") or {})]
    assert elapsed < 5, f"the M10 KPI strip took {elapsed:.1f}s"        # 12 s before: three KPIs each rebuilt the payables insight (677 queries)


def test_fin2_an_unreadable_encrypted_gstin_is_a_clear_503_audited_once(client, login, env):
    from cryptography.fernet import InvalidToken
    from app.pic.models import AuditEvent
    from app.pic.platform import crypto
    original = crypto.decrypt

    def broken(tenant_id, purpose, token):
        if purpose == "gstin":
            raise InvalidToken()
        return original(tenant_id, purpose, token)

    crypto.decrypt = broken
    try:
        for _ in range(2):
            r = client.get("/v1/suppliers/F2-ALPHA/finance", headers=_h(login, "fin"))
            body = _problem(r, 503, "FIELD_KEY_MISMATCH")
            assert "PIC_FIELD_KEY" in body["detail"] and "F2-ALPHA" in body["detail"] and "gAAAA" not in r.text
        _problem(client.get("/v1/finance/tds-certificates/data?fiscal_year=2027-28&quarter=Q1", headers=_h(login, "fin")), 503, "FIELD_KEY_MISMATCH")
    finally:
        crypto.decrypt = original
    with tenant_tx(J["tenant_id"]) as s:
        assert s.execute(select(func.count()).select_from(AuditEvent).where(AuditEvent.object_type == "SUPPLIER", AuditEvent.action == "FIELD_KEY_MISMATCH")).scalar() >= 1
        per_supplier = s.execute(select(AuditEvent.object_id, func.count()).where(AuditEvent.action == "FIELD_KEY_MISMATCH").group_by(AuditEvent.object_id)).all()
        assert all(n == 1 for _, n in per_supplier), per_supplier         # once per supplier, however often it is read
