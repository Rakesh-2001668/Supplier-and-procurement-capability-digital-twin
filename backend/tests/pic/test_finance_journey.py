"""The whole finance flow (Blueprint M10 / flow F7, M11 finance validation, Technical Document payables-svc) through the real HTTP API, one
sequential scenario in its own tenant.

purchase orders and goods receipts -> invoice capture (portal, AP clerk, GST e-invoice IRN; exact and OCR-variant duplicates refused / held) ->
3-way match clean -> quantity, price, tax (IRN), missing-GR and duplicate exceptions, resolved by AP (credit note, dispute + reject, GR posted)
and by a buyer other than the PO creator (price variance) -> credit note, debit note (buyer chain, AP approval) -> four-eyes approval (SOD-08)
-> post to ERP with the Idempotency-Key (replay, ERP failure then retry, lost response then query-before-retry) -> early-payment discount ->
payment proposal and runs (due date, MSME 45-day cap, TDS, blocked supplier, bank-change cooling-off, SOD-09 payer != approver) -> payment file,
bank result per payment (credited with UTR, returned and payable again), ERP reconciliation -> payment completed -> foreign-currency invoice and
posting-period cut-off -> savings realised from posted invoices and finance validation (SOD-07) -> audit trail, M10 KPIs, tenant isolation.

The scenario has its own tenant (FIN1), so nothing of the Axion signature case changes. Time is moved with the business clock (the API runs
in-process); the tests share state on purpose and run in file order.
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
from app.pic.platform import clock, crypto, integration
from app.pic.platform.auth import hash_password
from app.pic.seed.axion import at
from app.pic.seed.datasets import _tenant_kit as kit
from app.pic.services import payables
from app.pic.services import supplier as supplier_svc

from .conftest import PASSWORD

CODE = os.environ.get("FIN_TEST_TENANT", "FIN1")  # a developer re-running against a kept database (PIC_TEST_KEEP_DB) picks a fresh tenant code
DOMAIN = f"{CODE.lower()}.example"
GSTIN = "29AAKCD4821M1Z7"
PLANT = "P100"
J: dict = {}  # state handed from step to step

USERS = [
    ("admin", "Admin Anil", ["TENANT_ADMIN"], {}),
    ("buyer", "Bala Buyer", ["BUYER"], {"plants": [PLANT]}),            # creator of every purchase order
    ("buyer2", "Bina Buyer", ["BUYER"], {"plants": [PLANT]}),
    ("ph", "Pranav Procurement", ["PROCUREMENT_HEAD"], {}),
    ("cpo", "Cara CPO", ["CPO"], {}),
    ("fin", "Farid Finance", ["FINANCE_CONTROLLER"], {}),               # period close, payment runs, savings validation
    ("finap", "Fiona Finance-AP", ["AP_CLERK", "FINANCE_CONTROLLER"], {}),  # approves and pays: SOD-09 must stop her paying her own approvals
    ("ap1", "Asha AP", ["AP_CLERK"], {}),
    ("ap2", "Arun AP", ["AP_CLERK"], {}),
    ("receiver", "Ravi Receiver", ["RECEIVER"], {"plants": [PLANT]}),
    ("supmgr", "Sana Suppliers", ["SUPPLIER_MANAGER"], {}),
    ("cm", "Chandra Category", ["CATEGORY_MANAGER"], {}),
    ("owner", "Omar Owner-Finance", ["CATEGORY_MANAGER", "FINANCE_CONTROLLER"], {}),  # owns an initiative and also holds the finance role
    ("requester", "Reena Requester", ["REQUESTER"], {"cost_objects": ["COST_CENTER:6100"]}),
]
ROLE_USER = {"BUYER": ["buyer2"], "PROCUREMENT_HEAD": "ph", "FINANCE_CONTROLLER": "fin", "CPO": "cpo"}

# code -> (legal name, PAN, payment terms, state)
SUPPLIERS = {
    "FIN-ALPHA": ("Alpha Alloys Pvt Ltd", "AABCA1234F", "2/10 N30"),
    "FIN-MICRO": ("Micro Machining Works", "AABCM5678K", "N60"),
    "FIN-BLOCK": ("Blocked Bearings Pvt Ltd", "AABCB9012L", "N30"),
    "FIN-COOL": ("Cooling Castings Pvt Ltd", "AABCC3456M", "N30"),
}
MATERIALS = {"FIN-MAT-01": 50_000, "FIN-MAT-02": 100_000, "FIN-MAT-03": 100_000, "FIN-MAT-04": 200_000, "FIN-MAT-05": 100_000, "FIN-MAT-06": 1_200}
D0 = date(2026, 12, 1)


def _check_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        v = kit.GSTIN_CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += v // 36 + v % 36
    return kit.GSTIN_CHARS[(36 - total % 36) % 36]


def _gstin(pan: str) -> str:
    base = f"29{pan}1Z"
    return base + _check_char(base)


def _email(local: str) -> str:
    return f"{local}@{DOMAIN}"


def _h(login, local: str) -> dict:
    return login(_email(local), CODE)


def _portal(login, code: str = "FIN-ALPHA") -> dict:
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


def _tick(client, login) -> dict:
    r = client.post("/v1/admin/ops/tick", headers=_h(login, "admin"))
    assert r.status_code == 200, r.text
    return r.json()


def _kpi(client, headers, code: str) -> dict:
    r = client.get("/v1/kpis?module=M10&trend=false", headers=headers)
    assert r.status_code == 200, r.text
    return next(i for i in r.json()["items"] if i["code"] in (code, f"M10.{code}"))


def _requisition(env, material: str, qty: str, price_minor: int, need: date | None = None) -> str:
    """An approved requisition (the requirement is an input of this flow)."""
    with tenant_tx(env.tenant_id) as s:
        pr = Requisition(tenant_id=env.tenant_id, number=f"REQ-FIN-{uuid.uuid4().hex[:8].upper()}", origin="MANUAL", requester_id=J["buyer_id"],
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
    status = client.get(f"/v1/purchase-orders/{po}", headers=_h(login, "buyer")).json()["status"]
    if status != "CONFIRMED":
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
             irn: str | None = None, extra: dict | None = None, idem: str | None = None):
    _pin(day)
    line = {"po": po, "po_line": 10, "qty": qty, "unit_price": price, **(extra or {})}
    body = {"supplier": supplier, "supplier_invoice_no": number, "invoice_date": day.isoformat(), "channel": channel, "lines": [line]}
    if irn:
        body["irn"] = irn
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


@pytest.fixture(scope="module")
def env(database):
    sc = kit.setup_tenant(CODE, "Finance Journey Industries Pvt Ltd", "GENERAL", company=("1000", "Finance Journey Industries Pvt Ltd", GSTIN),
                          plants=[(PLANT, "Main plant", "29")], cost_objects=[("COST_CENTER", "6100", "Test cost centre")], holidays=[],
                          domain=DOMAIN, role_user=ROLE_USER)
    kit.create_users(sc, USERS, PASSWORD)
    kit.rule_version(sc, "MFA", "2026.1-FIN", date(2026, 4, 1), {"enforce": False}, "Finance journey tenant: no MFA challenge for the API tests")
    kit.rule_version(sc, "PAYMENT-FILE", "2026.1-FIN", date(2026, 4, 1),
                     {"debtorName": "Finance Journey Industries Pvt Ltd", "debtorAccountRef": "50200011223344", "debtorIfsc": "HDFC0000123"},
                     "Finance journey tenant: debtor account of the bank file")
    J["env"] = sc
    with sc.act("supmgr", at(D0, 9)) as s:
        for code, (name, pan, terms) in SUPPLIERS.items():
            sup = supplier_svc.register(s, code=code, legal_name=name, gstin=_gstin(pan), pan=pan, state_code="29",
                                        contact_email=f"accounts@{code.lower()}.{DOMAIN}", categories=["GENERAL"], payment_terms=terms)
            s.add(SupplierBankAccount(tenant_id=sc.tenant_id, supplier_id=sup.id, account_enc=crypto.encrypt(sc.tenant_id, "bank", "50100012345678"),
                                      account_masked="XXXXXXXXXX5678", ifsc="HDFC0000001", holder_name=name, active=True, verified_on=date(2026, 6, 1)))
            s.add(AppUser(tenant_id=sc.tenant_id, email=f"portal@{code.lower()}.{DOMAIN}", full_name=f"{name} portal", password_hash=hash_password(PASSWORD),
                          roles=["SUPPLIER_USER"], attributes={}, supplier_id=sup.id, mfa_enrolled=True))
            sup.status = "QUALIFIED"
            for row in s.execute(select(SupplierCategoryStatus).where(SupplierCategoryStatus.supplier_id == sup.id)).scalars():
                row.status, row.qualified_on = "QUALIFIED", date(2026, 6, 1)
    with tenant_tx(sc.tenant_id) as s:
        for number, price in MATERIALS.items():
            s.add(Material(tenant_id=sc.tenant_id, number=number, description=f"Finance journey material {number}", type="STOCK", material_group="GENERAL",
                           category="GENERAL", base_uom="EA", mrp_type="PD", lot_size_policy="EXACT", safety_stock=Decimal(0), planned_delivery_days=3,
                           gr_processing_days=0, standard_price_minor=price, status="ACTIVE", hsn_code="7601", gst_rate=Decimal(18)))
        buyer = s.execute(select(AppUser).where(AppUser.email == _email("buyer"))).scalar_one()
        J["buyer_id"] = buyer.id
    J.update(tenant_id=sc.tenant_id)
    return sc


# ================================================================ 1. orders, receipts, the savings initiative
def test_01_orders_receipts_and_savings_initiative(client, login, env):
    _pin(D0)
    J["po_a"] = _create_po(client, login, "FIN-MAT-01", "1000", "FIN-ALPHA")
    J["po_a2"] = _create_po(client, login, "FIN-MAT-02", "200", "FIN-ALPHA")
    J["po_m"] = _create_po(client, login, "FIN-MAT-03", "100", "FIN-MICRO")
    J["po_b"] = _create_po(client, login, "FIN-MAT-04", "10", "FIN-BLOCK")
    J["po_c"] = _create_po(client, login, "FIN-MAT-05", "10", "FIN-COOL")
    J["po_f"] = _create_po(client, login, "FIN-MAT-06", "50", "FIN-ALPHA")
    with tenant_tx(env.tenant_id) as s:  # the foreign-currency order: USD 12.00 per piece
        po = s.execute(select(PurchaseOrder).where(PurchaseOrder.number == J["po_f"])).scalar_one()
        po.currency = "USD"
    # M11: the owner (category manager who also holds the finance role) records the negotiated price before any invoice exists
    owner = _h(login, "owner")
    r = client.post("/v1/savings/initiatives", json={"title": "Alloy casting rate FY27", "category": "GENERAL", "baseline_method": "SHOULD_COST",
                                                      "annual_volume": "1000", "material": "FIN-MAT-01", "baseline_price_minor": 55_000}, headers=owner)
    assert r.status_code == 201, r.text
    J["initiative"] = r.json()["number"]
    r = client.post(f"/v1/savings/{J['initiative']}/negotiate", json={"new_price_minor": 50_000, "supplier": "FIN-ALPHA", "evidence": "Annual rate agreed 2026-11"},
                    headers=owner)
    assert r.status_code == 200 and r.json()["stage"] == "NEGOTIATED", r.text
    # goods receipts: a receiver other than the PO creator (SOD-03)
    _gr(client, login, J["po_a"], "600", date(2026, 12, 2), "DN-A-1")
    _gr(client, login, J["po_m"], "100", date(2026, 12, 2), "DN-M-1")
    _gr(client, login, J["po_b"], "10", date(2026, 12, 2), "DN-B-1")
    _gr(client, login, J["po_f"], "50", date(2026, 12, 2), "DN-F-1")
    assert client.post("/v1/goods-receipts", json={"po": J["po_a"], "delivery_note": "DN-X", "lines": [{"line": 10, "qty": "1"}]},
                       headers=_h(login, "buyer")).status_code == 403  # buyer has no gr:post


# ================================================================ 2. capture: validation, e-invoice IRN, duplicates, 3-way match
def test_02_capture_validation_irn_idempotency_and_exact_duplicate(client, login, env):
    day = date(2026, 12, 3)
    alpha = _portal(login)
    gstin = _gstin(SUPPLIERS["FIN-ALPHA"][1])
    # RBAC and validation: problem+json, nothing created
    r = _capture(client, _h(login, "requester"), "FIN-ALPHA", "INV-X-1", day, J["po_a"], "1", "500")
    assert r.status_code == 403
    _problem(_capture(client, alpha, "FIN-ALPHA", "INV-X-2", day, J["po_m"], "1", "500"), 404)        # another supplier's order
    assert _capture(client, alpha, "FIN-ALPHA", "INV-X-3", day, J["po_a"], "0", "500").status_code == 422
    assert _capture(client, alpha, "FIN-ALPHA", "INV-X-4", day, J["po_a"], "1", "-5").status_code == 422
    assert _capture(client, alpha, "FIN-ALPHA", "INV-X-5", day, J["po_a"], "1", "500", channel="FAX").status_code == 422
    _problem(client.post("/v1/invoices", json={"supplier_invoice_no": "INV-X-6", "invoice_date": day.isoformat(), "channel": "PDF_OCR",
                                               "lines": [{"po": J["po_a"], "po_line": 10, "qty": "1", "unit_price": "500"}]}, headers=_h(login, "ap1")),
             422, "SUPPLIER_REQUIRED")
    assert _capture(client, _h(login, "ap1"), "NO-SUCH", "INV-X-7", day, J["po_a"], "1", "500", channel="PDF_OCR").status_code == 404
    with tenant_tx(env.tenant_id) as s:
        assert s.execute(select(func.count()).select_from(Invoice)).scalar() == 0
    # INV1: GST e-invoice with a valid IRN, 600 of the 600 received, price and tax as ordered -> first-pass 3-way match
    irn = payables.expected_irn(gstin, "2026-27", "INV", "INV-A-0001")
    r = _capture(client, alpha, "FIN-ALPHA", "INV-A-0001", day, J["po_a"], "600", "500", channel="E_INVOICE", irn=irn, idem="cap-inv1")
    assert r.status_code == 201, r.text
    inv1 = r.json()
    J["inv1"] = inv1["number"]
    assert inv1["status"] == "MATCHED" and inv1["match_type"] == "3WAY" and inv1["first_pass_matched"] is True
    assert inv1["irn_valid"] is True and inv1["payment_block"] is False and inv1["gross_minor"] == 35_400_000 and not inv1["exceptions"]
    assert inv1["currency"] == "INR" and inv1["rule_set_version"].startswith("DMN-03")
    # the same Idempotency-Key replays the same invoice; a new key for the same supplier invoice number is the hard duplicate (409)
    again = _capture(client, alpha, "FIN-ALPHA", "INV-A-0001", day, J["po_a"], "600", "500", channel="E_INVOICE", irn=irn, idem="cap-inv1")
    assert again.status_code in (200, 201) and again.json()["number"] == J["inv1"]
    dup = _problem(_capture(client, alpha, "FIN-ALPHA", "INV-A-0001", day, J["po_a"], "600", "500", channel="E_INVOICE", irn=irn, idem="cap-inv1-b"), 409,
                   "DUPLICATE_INVOICE")
    assert dup["duplicateOf"] == J["inv1"]
    with tenant_tx(env.tenant_id) as s:
        assert s.execute(select(func.count()).select_from(Invoice)).scalar() == 1
    # the portal user cannot read another supplier's invoice, AP can
    assert client.get(f"/v1/invoices/{J['inv1']}", headers=_portal(login, "FIN-MICRO")).status_code == 404
    assert client.get(f"/v1/invoices/{J['inv1']}", headers=_h(login, "ap1")).headers["ETag"]


# ================================================================ 3. approval (RBAC, ETag), posting key, idempotent replay
def test_03_approve_with_etag_post_with_idempotency_key(client, login, env):
    _pin(date(2026, 12, 3), 14)
    ref = J["inv1"]
    assert _approve(client, login, ref, "buyer").status_code == 403                    # a buyer cannot approve invoices
    etag = client.get(f"/v1/invoices/{ref}", headers=_h(login, "ap2")).headers["ETag"]
    _problem(client.post(f"/v1/invoices/{ref}/approve", headers={**_h(login, "ap2"), "If-Match": '"999"'}), 412)  # stale view
    r = client.post(f"/v1/invoices/{ref}/approve", headers={**_h(login, "ap2"), "If-Match": etag})
    assert r.status_code == 200 and r.json()["status"] == "APPROVED", r.text
    # posting needs the Idempotency-Key; it must be tenant|company code|supplier|invoice number (P13)
    _problem(client.post(f"/v1/invoices/{ref}/post", headers=_h(login, "ap2")), 428, "IDEMPOTENCY_KEY_REQUIRED")
    bad = client.post(f"/v1/invoices/{ref}/post", headers={**_h(login, "ap2"), "Idempotency-Key": "wrong-key"})
    assert bad.status_code in (409, 422), bad.text
    r, key = _post(client, login, ref, "ap2")
    assert key == f"{CODE}|1000|FIN-ALPHA|INV-A-0001"
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["status"] == "POSTED" and first["erpDocument"] and first["replayed"] is False
    replay, _ = _post(client, login, ref, "ap2", key)
    assert replay.status_code == 200 and replay.json()["erpDocument"] == first["erpDocument"] and replay.json()["replayed"] is True
    with tenant_tx(env.tenant_id) as s:
        assert s.execute(select(func.count()).select_from(ErpDocument).where(ErpDocument.external_ref == key)).scalar() == 1
    inv = _invoice(client, login, ref)
    assert inv["status"] == "POSTED" and inv["erp_doc_no"] == first["erpDocument"] and inv["due_date"] == "2027-01-02" and inv["msme_capped"] is False
    assert inv["posting_date"] == "2026-12-03" and inv["posting_key"] == key


# ================================================================ 4. quantity exception, OCR duplicate, credit note, four-eyes, ERP failure then retry
def test_04_quantity_exception_credit_note_four_eyes_and_erp_retry(client, login, env):
    _gr(client, login, J["po_a"], "400", date(2026, 12, 4), "DN-A-2")
    ap1, alpha = _h(login, "ap1"), _portal(login)
    # INV2 keyed by the AP clerk from a PDF (OCR): 450 billed, 400 left to invoice -> QUANTITY +50, payment block
    r = _capture(client, ap1, "FIN-ALPHA", "INV-A-0002", date(2026, 12, 4), J["po_a"], "450", "500", channel="PDF_OCR")
    assert r.status_code == 201, r.text
    inv2 = r.json()
    J["inv2"] = inv2["number"]
    assert inv2["status"] == "EXCEPTION" and inv2["payment_block"] is True and inv2["first_pass_matched"] is False
    quantity = [e for e in inv2["exceptions"] if e["status"] == "OPEN"]
    assert [e["type"] for e in quantity] == ["QUANTITY"] and quantity[0]["delta"]["qty"] in ("50", "50.000")
    # OCR / formatting variant of the same number from the same supplier, different amount: held as a duplicate, not captured silently
    r = _capture(client, alpha, "FIN-ALPHA", "inv a 0002", date(2026, 12, 4), J["po_a"], "10", "500")
    assert r.status_code == 201, r.text
    variant = r.json()
    assert variant["status"] == "EXCEPTION" and [e["type"] for e in variant["exceptions"]] == ["DUPLICATE"]
    assert variant["exceptions"][0]["delta"].get("variant") == "NUMBER_NORMALISED" and variant["exceptions"][0]["delta"]["similarTo"] == J["inv2"]
    # the hold is released only as NOT_DUPLICATE; a credit-note style resolution is refused; here AP rejects the invoice
    exc_id = variant["exceptions"][0]["id"]
    _problem(client.post(f"/v1/invoices/{variant['number']}/exceptions/{exc_id}/resolve", json={"resolution": "GR_POSTED", "note": "x"}, headers=ap1), 422,
             "INVALID_RESOLUTION")
    assert client.post(f"/v1/invoices/{variant['number']}/match", headers=ap1).status_code == 409  # re-running the match does not release the hold
    assert client.post(f"/v1/invoices/{variant['number']}/reject", json={"reason": "Same invoice as INV-A-0002 re-sent"}, headers=ap1).status_code == 200
    assert _invoice(client, login, variant["number"])["status"] == "REJECTED"
    assert client.post(f"/v1/invoices/{variant['number']}/reject", json={"reason": "again"}, headers=ap1).status_code == 409
    # the credit note arrives from the supplier; the buyer who created the order cannot resolve (no invoice:resolve scope)
    qid = quantity[0]["id"]
    assert client.post(f"/v1/invoices/{J['inv2']}/exceptions/{qid}/resolve", json={"resolution": "CREDIT_NOTE_RECEIVED", "note": "x"},
                       headers=_h(login, "buyer")).status_code == 403
    r = client.post(f"/v1/invoices/{J['inv2']}/credit-notes", json={"supplier_credit_note_no": "CN-A-0002", "note_date": "2026-12-04",
                                                                   "reason": "Credit for 50 pieces billed above the receipt",
                                                                   "lines": [{"invoice_line": 10, "qty": "50"}]}, headers={**alpha, "Idempotency-Key": "cn-a-2"})
    assert r.status_code == 201, r.text
    note = r.json()
    assert note["gross_minor"] == 2_950_000
    assert client.post(f"/v1/invoices/{J['inv2']}/credit-notes", json={"supplier_credit_note_no": "CN-A-0002", "note_date": "2026-12-04", "reason": "dup",
                                                                      "lines": [{"invoice_line": 10, "qty": "1"}]}, headers=alpha).status_code in (409, 422)
    resolve = f"/v1/invoices/{J['inv2']}/exceptions/{qid}/resolve"
    _problem(client.post(resolve, json={"resolution": "PRICE_ACCEPTED", "note": "x"}, headers=ap1), 422, "INVALID_RESOLUTION")
    assert client.post(resolve, json={"resolution": "CREDIT_NOTE_RECEIVED", "note": "credit note"}, headers=ap1).status_code in (409, 422)  # must name the note
    r = client.post(resolve, json={"resolution": "CREDIT_NOTE_RECEIVED", "note": "Credit note CN-A-0002 for 50 pieces", "credit_note": "CN-A-0002"}, headers=ap1)
    assert r.status_code == 200, r.text
    inv = _invoice(client, login, J["inv2"])
    assert inv["status"] == "MATCHED" and inv["payment_block"] is False
    # four-eyes (SOD-08): ap1 keyed the invoice and cannot approve it; ap2 can
    sod = _problem(_approve(client, login, J["inv2"], "ap1"), 409, "SOD_CONFLICT")
    assert sod["ruleRef"] == "SOD-08"
    assert _approve(client, login, J["inv2"], "ap2").status_code == 200
    # ERP does not answer: the post parks as POSTING (RETRY), the invoice stays APPROVED; the admin replays it; the key posts once
    key = f"{CODE}|1000|FIN-ALPHA|INV-A-0002"
    integration.FAULTS["fail"] = 1
    try:
        r, _ = _post(client, login, J["inv2"], "ap2")
    finally:
        integration.FAULTS["fail"] = 0
    assert r.status_code == 200 and r.json()["status"] == "POSTING" and r.json()["integrationStatus"] == "RETRY", r.text
    assert _invoice(client, login, J["inv2"])["status"] == "APPROVED"
    with tenant_tx(env.tenant_id) as s:
        message = s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == key)).scalar_one()
        message_id = message.id
        assert message.status == "RETRY" and message.attempts == 1
    r = client.post(f"/v1/integration/messages/{message_id}/replay", headers=_h(login, "admin"))
    assert r.status_code == 200 and r.json()["status"] == "POSTED", r.text
    inv = _invoice(client, login, J["inv2"])
    assert inv["status"] == "POSTED" and inv["erp_doc_no"]
    again, _ = _post(client, login, J["inv2"], "ap2", key)
    assert again.json()["status"] == "POSTED" and again.json()["erpDocument"] == inv["erp_doc_no"]     # the retry with the same key sees the final state
    assert _post(client, login, J["inv2"], "ap2", key)[0].json()["replayed"] is True                    # and is now replayed
    with tenant_tx(env.tenant_id) as s:
        assert s.execute(select(func.count()).select_from(ErpDocument).where(ErpDocument.external_ref == key)).scalar() == 1


# ================================================================ 5. tax (IRN) and price exceptions: AP dispute + reject, buyer price-variance approval
def test_05_tax_and_price_exceptions_resolved_by_ap_and_by_the_buyer(client, login, env):
    _gr(client, login, J["po_a2"], "200", date(2026, 12, 4), "DN-A2-1")
    ap1, alpha = _h(login, "ap1"), _portal(login)
    # an e-invoice whose IRN is not the hash of GSTIN + FY + type + number: captured, but a TAX exception (IRN invalid)
    r = _capture(client, alpha, "FIN-ALPHA", "INV-A-0003", date(2026, 12, 4), J["po_a2"], "200", "1000", channel="E_INVOICE", irn="a" * 64)
    assert r.status_code == 201, r.text
    bad = r.json()
    assert bad["irn_valid"] is False and bad["status"] == "EXCEPTION" and [e["type"] for e in bad["exceptions"]] == ["TAX"]
    exc = bad["exceptions"][0]["id"]
    r = client.post(f"/v1/invoices/{bad['number']}/exceptions/{exc}/resolve", json={"resolution": "DISPUTE", "note": "Ask supplier for a valid IRN"}, headers=ap1)
    assert r.status_code == 200 and r.json()["dispute"] is True
    assert _invoice(client, login, bad["number"])["payment_block"] is True                     # a dispute does not release the block
    assert client.post(f"/v1/invoices/{bad['number']}/reject", json={"reason": "Supplier will re-issue with a valid IRN"}, headers=ap1).status_code == 200
    # a price above the order price: 200 x 10.00 over (INR 2,000) -> PRICE (tolerance is the lower of 1 % and 500)
    r = _capture(client, alpha, "FIN-ALPHA", "INV-A-0004", date(2026, 12, 4), J["po_a2"], "200", "1010")
    assert r.status_code == 201, r.text
    inv = r.json()
    J["inv4"] = inv["number"]
    assert inv["status"] == "EXCEPTION" and [e["type"] for e in inv["exceptions"]] == ["PRICE"]
    assert inv["exceptions"][0]["delta"]["lineVarianceMinor"] == 200_000
    price_exc = inv["exceptions"][0]["id"]
    url = f"/v1/invoices/{J['inv4']}/exceptions/{price_exc}/resolve"
    _problem(client.post(url, json={"resolution": "PRICE_ACCEPTED", "note": ""}, headers=ap1), 422, "REASON_REQUIRED")
    r = client.post(url, json={"resolution": "PRICE_ACCEPTED", "note": "Steel surcharge agreed with the supplier on the phone"}, headers=ap1)
    assert r.status_code == 200 and r.json()["priceApproval"], r.text
    assert _invoice(client, login, J["inv4"])["status"] == "EXCEPTION"                          # AP cannot accept a price on its own
    _problem(client.post(url, json={"resolution": "PRICE_ACCEPTED", "note": "again"}, headers=ap1), 409, "APPROVAL_PENDING")
    assert _tasks(client, _h(login, "buyer"), J["inv4"]) == []                                  # the PO creator is excluded from the approval
    tasks = _tasks(client, _h(login, "buyer2"), J["inv4"])
    assert len(tasks) == 1
    done = client.post(f"/v1/tasks/{tasks[0]['id']}/complete", json={"decision": "APPROVE", "comment": "Surcharge accepted, PO re-priced"}, headers=_h(login, "buyer2"))
    assert done.status_code == 200, done.text
    inv = _invoice(client, login, J["inv4"])
    assert inv["status"] == "MATCHED" and inv["payment_block"] is False
    with tenant_tx(env.tenant_id) as s:
        po_line = s.execute(select(PoLine).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(PurchaseOrder.number == J["po_a2"])).scalar_one()
        assert po_line.unit_price_minor == 101_000
    # finap approves (she did not capture it) -- she will not be allowed to pay it (SOD-09, test 13)
    _pin(date(2026, 12, 7))
    assert _approve(client, login, J["inv4"], "finap").status_code == 200
    r, _ = _post(client, login, J["inv4"], "ap2")
    assert r.status_code == 200 and r.json()["status"] == "POSTED", r.text


# ================================================================ 6. missing goods receipt, resolved when the receipt is posted
def test_06_missing_gr_then_goods_receipt_posted(client, login, env):
    ap1 = _h(login, "ap1")
    r = _capture(client, _portal(login, "FIN-COOL"), "FIN-COOL", "INV-C-0001", date(2026, 12, 5), J["po_c"], "10", "1000")
    assert r.status_code == 201, r.text
    inv = r.json()
    J["inv_c"] = inv["number"]
    assert inv["status"] == "EXCEPTION" and [e["type"] for e in inv["exceptions"]] == ["MISSING_GR"] and inv["payment_block"] is True
    _gr(client, login, J["po_c"], "10", date(2026, 12, 6), "DN-C-1")
    r = client.post(f"/v1/invoices/{J['inv_c']}/exceptions/{inv['exceptions'][0]['id']}/resolve", json={"resolution": "GR_POSTED", "note": "Receipt DN-C-1 posted"},
                    headers=ap1)
    assert r.status_code == 200, r.text
    assert _invoice(client, login, J["inv_c"])["status"] == "MATCHED"
    assert _approve(client, login, J["inv_c"], "ap2").status_code == 200
    # TDS 194J-TECH (2 %, annual threshold INR 50,000): 10 x 1,000.00 is below it, so nothing is withheld, but the section and base are kept
    supmgr = _h(login, "supmgr")
    etag = client.get("/v1/suppliers/FIN-COOL/finance", headers=supmgr).headers["ETag"]
    assert client.put("/v1/suppliers/FIN-COOL/finance", json={"tdsSection": "194J-TECH", "reason": "Technical services declaration"},
                      headers={**supmgr, "If-Match": etag}).status_code == 200
    r, _ = _post(client, login, J["inv_c"], "ap1")
    assert r.status_code == 200 and r.json()["status"] == "POSTED", r.text
    inv_c = _invoice(client, login, J["inv_c"])
    assert inv_c["tds_section"] == "194J-TECH" and inv_c["tds_base_minor"] == 0 and inv_c["withholding_tax_minor"] == 0 and inv_c["msme_capped"] is False
    with tenant_tx(env.tenant_id) as s:  # a bank change was made on the supplier master: no payment until the cooling-off ends
        account = s.execute(select(SupplierBankAccount).join(Supplier, Supplier.id == SupplierBankAccount.supplier_id).where(Supplier.code == "FIN-COOL")).scalar_one()
        account.payable_from = at(date(2027, 2, 1), 0)


# ================================================================ 7. lost ERP response (query before retry), blocked supplier
def test_07_lost_erp_response_and_blocked_supplier(client, login, env):
    r = _capture(client, _portal(login, "FIN-BLOCK"), "FIN-BLOCK", "INV-B-0001", date(2026, 12, 5), J["po_b"], "10", "2000")
    assert r.status_code == 201 and r.json()["status"] == "MATCHED", r.text
    J["inv_b"] = r.json()["number"]
    assert _approve(client, login, J["inv_b"], "ap1").status_code == 200
    key = f"{CODE}|1000|FIN-BLOCK|INV-B-0001"
    integration.FAULTS["lose_response"] = 1                 # the ERP posts the document, the answer is lost
    try:
        r, _ = _post(client, login, J["inv_b"], "ap2")
    finally:
        integration.FAULTS["lose_response"] = 0
    assert r.status_code == 200 and r.json()["status"] in ("POSTING", "POSTED"), r.text
    r, _ = _post(client, login, J["inv_b"], "ap2", key)     # retry: the platform asks the ERP first and finds its own document
    assert r.status_code == 200 and r.json()["status"] == "POSTED" and r.json()["erpDocument"], r.text
    with tenant_tx(env.tenant_id) as s:
        assert s.execute(select(func.count()).select_from(ErpDocument).where(ErpDocument.external_ref == key)).scalar() == 1
    # the supplier is blocked (e.g. sanctions hit): its posted invoice is payment-blocked and it cannot invoice any more
    assert client.post("/v1/suppliers/FIN-BLOCK/block", json={"reason": "Sanctions screening hit under review"}, headers=_h(login, "ap1")).status_code == 403
    assert client.post("/v1/suppliers/FIN-BLOCK/block", json={"reason": "Sanctions screening hit under review"}, headers=_h(login, "supmgr")).status_code == 200
    assert _invoice(client, login, J["inv_b"])["payment_block"] is True
    _problem(_capture(client, _portal(login, "FIN-BLOCK"), "FIN-BLOCK", "INV-B-0002", date(2026, 12, 6), J["po_b"], "1", "2000"), 409, "SUPPLIER_BLOCKED")


# ================================================================ 8. debit note: buyer chain, AP approval, ERP debit memo
def test_08_debit_note_buyer_chain_ap_approval_and_posting(client, login, env):
    _pin(date(2026, 12, 7), 11)
    alpha, ap1 = _portal(login), _h(login, "ap1")
    body = {"supplier_debit_note_no": "DN-A-0001", "note_date": "2026-12-07", "reason": "Freight charged on delivery",
            "lines": [{"kind": "CHARGE", "charge": "FREIGHT", "description": "Freight", "amount_minor": 100_000, "gst_rate": "18", "hsn": "996511"}]}
    r = client.post(f"/v1/invoices/{J['inv1']}/debit-notes", json=body, headers={**alpha, "Idempotency-Key": "dn-a-1"})
    assert r.status_code == 201, r.text
    note = r.json()
    J["dn"] = note["number"]
    assert note["status"] == "PENDING_APPROVAL" and note["grossMinor"] == 118_000
    _problem(client.post(f"/v1/invoices/{J['inv1']}/debit-notes", json=body, headers=alpha), 409, "DUPLICATE_DEBIT_NOTE")
    assert client.post(f"/v1/debit-notes/{J['dn']}/approve", headers=ap1).status_code == 409        # the buyer chain has not decided yet
    assert _tasks(client, _h(login, "buyer"), J["dn"]) == []
    tasks = _tasks(client, _h(login, "buyer2"), J["dn"])
    assert len(tasks) == 1
    assert client.post(f"/v1/tasks/{tasks[0]['id']}/complete", json={"decision": "APPROVE", "comment": "Freight as per delivery terms"},
                       headers=_h(login, "buyer2")).status_code == 200
    r = client.post(f"/v1/debit-notes/{J['dn']}/approve", headers=ap1)
    assert r.status_code == 200 and r.json()["status"] == "APPROVED", r.text
    r = client.post(f"/v1/debit-notes/{J['dn']}/post", headers={**ap1, "Idempotency-Key": "dn-post-1"})
    assert r.status_code == 200 and r.json()["status"] == "POSTED" and r.json()["erpDocument"], r.text
    inv = _invoice(client, login, J["inv1"])
    assert [n["number"] for n in inv["debitNotes"]] == [J["dn"]]


# ================================================================ 9. early-payment discount, proposal, payment run, bank file, bank result
def test_09_early_payment_discount_proposal_run_file_and_bank_credit(client, login, env):
    _pin(date(2026, 12, 8))
    ap1, ap2, fin = _h(login, "ap1"), _h(login, "ap2"), _h(login, "fin")
    state = client.get(f"/v1/invoices/{J['inv1']}/early-payment", headers=ap1).json()
    assert state["eligible"] is True and state["termsDiscount"]["pct"] == "2" and state["termsDiscount"]["available"] is True
    r = client.post(f"/v1/invoices/{J['inv1']}/early-payment/offers", json={"source": "TERMS"}, headers={**ap1, "Idempotency-Key": "ep-1"})
    assert r.status_code == 201 and r.json()["status"] == "ACCEPTED" and r.json()["discountMinor"] > 0, r.text
    discount = r.json()["discountMinor"]
    inv = _invoice(client, login, J["inv1"])
    assert inv["payment_option"] == "EARLY_DISCOUNT" and inv["due_date"] == "2026-12-08" and inv["discount_minor"] == discount
    # proposal: nothing is written; the numbers are exactly what the run will pay; only finance may ask
    proposal_url = f"/v1/payments/proposal?run_date=2026-12-08&supplier=FIN-ALPHA&invoice={J['inv1']}"
    assert client.get(proposal_url, headers=ap2).status_code == 403
    proposal = client.get(proposal_url, headers=fin).json()
    assert [i["invoice"] for i in proposal["items"]] == [J["inv1"]] and proposal["skipped"] == []
    item = proposal["items"][0]
    assert item["discountMinor"] == discount and item["debitNotesMinor"] == 118_000
    assert item["amountMinor"] == item["grossMinor"] - item["creditNotesMinor"] + item["debitNotesMinor"] - item["discountMinor"] - item["tdsMinor"]
    with tenant_tx(env.tenant_id) as s:
        assert s.execute(select(func.count()).select_from(Payment)).scalar() == 0
    assert client.post("/v1/payments/runs", json={"run_date": "2026-12-08", "supplier_codes": ["FIN-ALPHA"]}, headers=ap2).status_code == 403
    _problem(client.post("/v1/payments/runs", json={"run_date": "2026-12-08", "supplier_codes": ["NO-SUCH"]}, headers=fin), 404, "SUPPLIER_NOT_FOUND")
    body = {"run_date": "2026-12-08", "supplier_codes": ["FIN-ALPHA"], "invoice_numbers": [J["inv1"]]}
    run = client.post("/v1/payments/runs", json=body, headers={**fin, "Idempotency-Key": "run-1"})
    assert run.status_code == 200, run.text
    result = run.json()
    assert len(result["paid"]) == 1 and result["skipped"] == [] and result["paid"][0]["amountMinor"] == item["amountMinor"]
    assert result["paid"][0]["clearing"] and result["paid"][0]["discountMinor"] == discount
    replay = client.post("/v1/payments/runs", json=body, headers={**fin, "Idempotency-Key": "run-1"})
    assert replay.json()["run"] == result["run"]
    J["run1"], J["pay1"] = result["run"], result["paid"][0]["payment"]
    inv = _invoice(client, login, J["inv1"])
    assert inv["status"] == "PAID" and inv["payment_status"] == "PAID" and len(inv["payments"]) == 1
    # a second run does not pay it again
    again = client.post("/v1/payments/runs", json=body, headers=fin).json()
    assert again["paid"] == []
    payments = client.get(f"/v1/payments?run={J['run1']}", headers=fin).json()["items"]
    assert len(payments) == 1 and payments[0]["bank_status"] == "NOT_SENT" and payments[0]["invoice_number"] == J["inv1"]
    # bank file for the run: finance only; one live file per run; the content is audited
    assert client.post(f"/v1/payments/runs/{J['run1']}/file", json={"format": "ISO20022_PAIN001"}, headers=ap2).status_code == 403
    r = client.post(f"/v1/payments/runs/{J['run1']}/file", json={"format": "ISO20022_PAIN001"}, headers=fin)
    assert r.status_code == 201 and r.json()["status"] == "GENERATED", r.text
    J["file1"] = r.json()["number"]
    _problem(client.post(f"/v1/payments/runs/{J['run1']}/file", json={"format": "NEFT_CSV"}, headers=fin), 409, "PAYMENT_FILE_EXISTS")
    content = client.get(f"/v1/payment-files/{J['file1']}/content", headers=fin)
    assert content.status_code == 200 and "pain.001.001.03" in content.text and f"{item['amountMinor'] / 100:.2f}" in content.text
    # results cannot be recorded before the file was sent; then per payment: UTR required, credited, repeat is idempotent
    results = f"/v1/payment-files/{J['file1']}/bank-results"
    assert client.post(results, json={"items": [{"payment": J["pay1"], "status": "CREDITED", "utr": "UTR0001"}]}, headers=fin).status_code == 409
    assert client.post(f"/v1/payment-files/{J['file1']}/status", json={"status": "SENT"}, headers=fin).status_code == 200
    assert client.get(f"/v1/payments?run={J['run1']}", headers=fin).json()["items"][0]["bank_status"] == "SENT"
    _problem(client.post(results, json={"items": [{"payment": J["pay1"], "status": "CREDITED"}]}, headers=fin), 422, "UTR_REQUIRED")
    _problem(client.post(results, json={"items": [{"payment": "PAY-NOPE", "status": "CREDITED", "utr": "U1"}]}, headers=fin), 404)
    r = client.post(results, json={"items": [{"payment": J["pay1"], "status": "CREDITED", "utr": "UTR0001"}]}, headers={**fin, "Idempotency-Key": "br-1"})
    assert r.status_code == 200 and r.json()["credited"] == [J["pay1"]] and r.json()["reconciled"] is True, r.text
    assert client.post(results, json={"items": [{"payment": J["pay1"], "status": "CREDITED", "utr": "UTR0001"}]}, headers=fin).json()["unchanged"] == [J["pay1"]]
    _problem(client.post(results, json={"items": [{"payment": J["pay1"], "status": "CREDITED", "utr": "OTHER"}]}, headers=fin), 409, "BANK_RESULT_CONFLICT")
    _problem(client.post(results, json={"items": [{"payment": J["pay1"], "status": "RETURNED", "reason": "late"}]}, headers=fin), 409, "BANK_RESULT_CONFLICT")
    assert client.post(f"/v1/payment-files/{J['file1']}/status", json={"status": "ACKNOWLEDGED", "bankRef": "HDFC-ACK-0001"}, headers=fin).status_code == 200
    rec = client.get(f"/v1/payment-files/{J['file1']}/reconciliation", headers=fin).json()
    assert rec["fileStatus"] == "ACKNOWLEDGED" and rec["reconciled"] is True and rec["creditedMinor"] == item["amountMinor"] and rec["pendingMinor"] == 0


# ================================================================ 10. MSME class and TDS section on the supplier, MSME invoice posted
def test_10_msme_and_tds_master_data_and_posting(client, login, env):
    supmgr = _h(login, "supmgr")
    etag = client.get("/v1/suppliers/FIN-MICRO/finance", headers=supmgr).headers["ETag"]
    body = {"msmeClass": "MICRO", "udyamNo": "UDYAM-KA-03-0012345", "tdsSection": "194C-OTH", "reason": "Udyam certificate and TDS declaration on file"}
    assert client.put("/v1/suppliers/FIN-MICRO/finance", json=body, headers=_h(login, "ap1")).status_code == 403
    _problem(client.put("/v1/suppliers/FIN-MICRO/finance", json=body, headers={**supmgr, "If-Match": '"999"'}), 412)
    _problem(client.put("/v1/suppliers/FIN-MICRO/finance", json={**body, "udyamNo": None}, headers={**supmgr, "If-Match": etag}), 422, "UDYAM_REQUIRED")
    _problem(client.put("/v1/suppliers/FIN-MICRO/finance", json={**body, "tdsSection": "999Z"}, headers={**supmgr, "If-Match": etag}), 422, "TDS_SECTION_UNKNOWN")
    r = client.put("/v1/suppliers/FIN-MICRO/finance", json=body, headers={**supmgr, "If-Match": etag})
    assert r.status_code == 200 and r.headers["ETag"] != etag and r.json()["msmeClass"] == "MICRO", r.text
    assert client.get("/v1/suppliers/FIN-MICRO/finance", headers=supmgr).json()["isMsme"] is True
    controls = client.get("/v1/finance/controls", headers=supmgr).json()
    assert controls["msme"]["maxDays"] == 45 and "194C-OTH" in controls["tds"]["sections"]
    # the invoice: 100 x 1,000.00 + 18 % GST, dated three weeks after the receipt, N60 terms
    r = _capture(client, _portal(login, "FIN-MICRO"), "FIN-MICRO", "INV-M-0001", date(2026, 12, 21), J["po_m"], "100", "1000")
    assert r.status_code == 201 and r.json()["status"] == "MATCHED", r.text
    J["inv_m"] = r.json()["number"]
    assert _approve(client, login, J["inv_m"], "ap1").status_code == 200
    _pin(date(2026, 12, 22))
    r, _ = _post(client, login, J["inv_m"], "ap2")
    assert r.status_code == 200 and r.json()["status"] == "POSTED", r.text
    inv = _invoice(client, login, J["inv_m"])
    assert inv["gross_minor"] == 11_800_000
    # MSMED Act s.15: 45 days from the acceptance (receipt) date, not the N60 terms from the invoice date
    assert inv["acceptance_date"] == "2026-12-02" and inv["due_date"] == (date(2026, 12, 2) + timedelta(days=45)).isoformat() and inv["msme_capped"] is True
    # TDS 2 % on the net of GST, fixed at posting
    assert inv["tds_section"] == "194C-OTH" and Decimal(str(inv["tds_rate"])) == Decimal("2") and inv["tds_base_minor"] == 10_000_000
    assert inv["withholding_tax_minor"] == 200_000


# ================================================================ 11. foreign-currency invoice and posting-period cut-off
def test_11_foreign_currency_invoice_and_period_cutoff(client, login, env):
    r = _capture(client, _portal(login), "FIN-ALPHA", "INV-F-0001", date(2026, 12, 28), J["po_f"], "50", "12.00")
    assert r.status_code == 201 and r.json()["status"] == "MATCHED", r.text
    inv = r.json()
    J["inv_f"] = inv["number"]
    assert inv["currency"] == "USD" and inv["gross_minor"] == 70_800
    assert _approve(client, login, J["inv_f"], "ap1").status_code == 200
    _pin(date(2026, 12, 29))
    # no exchange rate is valid on the invoice date: the post is refused, nothing reaches the ERP
    _problem(_post(client, login, J["inv_f"], "ap2")[0], 409, "FX_RATE_MISSING")
    # cut-off: finance previews, then closes December on 4 January; AP and a not-yet-ended period are refused
    _pin(date(2027, 1, 4))
    fin, ap1 = _h(login, "fin"), _h(login, "ap1")
    cut = client.get("/v1/finance/periods/2026-12/cutoff?company_code=1000", headers=fin).json()
    assert cut["unpostedInvoices"] >= 1 and cut["unpostedByStatus"].get("APPROVED", 0) >= 1 and cut["periodEnd"] == "2026-12-31"
    assert client.post("/v1/finance/periods/2026-12/close", json={"companyCode": "1000"}, headers=ap1).status_code == 403
    _problem(client.post("/v1/finance/periods/2027-01/close", json={"companyCode": "1000"}, headers=fin), 409, "PERIOD_NOT_ENDED")
    _problem(client.post("/v1/finance/periods/2026-13/close", json={"companyCode": "1000"}, headers=fin), 422)
    r = client.post("/v1/finance/periods/2026-12/close", json={"companyCode": "1000", "reason": "December close"}, headers={**fin, "Idempotency-Key": "close-12"})
    assert r.status_code == 200 and r.json()["status"] == "CLOSED" and r.json()["cutoff"]["unpostedInvoices"] >= 1, r.text
    _problem(client.post("/v1/finance/periods/2026-12/close", json={"companyCode": "1000"}, headers=fin), 409, "ILLEGAL_TRANSITION")
    _pin(date(2026, 12, 29))   # a posting dated into the closed period is refused
    _problem(_post(client, login, J["inv_f"], "ap2")[0], 409, "PERIOD_CLOSED")
    _pin(date(2027, 1, 4))
    _problem(_post(client, login, J["inv_f"], "ap2")[0], 409, "FX_RATE_MISSING")
    with tenant_tx(env.tenant_id) as s:
        s.add(FxRate(tenant_id=env.tenant_id, from_ccy="USD", to_ccy="INR", rate=Decimal("83.25"), valid_from=date(2026, 12, 1), source="TEST"))
    r, _ = _post(client, login, J["inv_f"], "ap2")
    assert r.status_code == 200 and r.json()["status"] == "POSTED", r.text
    inv = _invoice(client, login, J["inv_f"])
    assert Decimal(str(inv["fx_rate"])) == Decimal("83.25") and inv["gross_group_minor"] == 5_894_100 and inv["posting_date"] == "2027-01-04"
    # reopening needs a real reason and is audited; the register shows the status
    _problem(client.post("/v1/finance/periods/2026-12/reopen", json={"companyCode": "1000", "reason": "short"}, headers=fin), 422)
    r = client.post("/v1/finance/periods/2026-12/reopen", json={"companyCode": "1000", "reason": "Late freight accrual to be booked in December"}, headers=fin)
    assert r.status_code == 200 and r.json()["status"] == "OPEN"
    assert [p["status"] for p in client.get("/v1/finance/periods?company_code=1000", headers=fin).json()["items"]] == ["OPEN"]


# ================================================================ 12. payment run on due date: SOD-09, bank-change cooling-off, bank return, ERP reconciliation
def test_12_due_run_sod09_cooling_off_bank_return_and_reconciliation(client, login, env):
    _pin(date(2027, 1, 5))
    fin, finap = _h(login, "fin"), _h(login, "finap")
    proposal = client.get("/v1/payments/proposal?run_date=2027-01-05", headers=fin).json()
    due = {i["invoice"]: i for i in proposal["items"]}
    assert set(due) == {J["inv2"], J["inv4"]}                       # INV-M is not due before 16 Jan (MSME cap), INV-F on 27 Jan
    assert [s["invoice"] for s in proposal["skipped"]] == [J["inv_c"]] and "cooling-off" in proposal["skipped"][0]["reason"]
    assert due[J["inv2"]]["creditNotesMinor"] == 2_950_000 and due[J["inv2"]]["amountMinor"] == 26_550_000 - 2_950_000
    assert J["inv_b"] not in due and J["inv_b"] not in [s["invoice"] for s in proposal["skipped"]]   # the blocked supplier's invoice is payment-blocked
    # finap approved INV4 and may not release its payment (SOD-09); she pays INV2, which ap2 approved
    run = client.post("/v1/payments/runs", json={"run_date": "2027-01-05"}, headers={**finap, "Idempotency-Key": "run-2"})
    assert run.status_code == 200, run.text
    paid = {p["invoice"]: p for p in run.json()["paid"]}
    skipped = {s["invoice"]: s["reason"] for s in run.json()["skipped"]}
    assert set(paid) == {J["inv2"]} and "SOD-09" in skipped[J["inv4"]] and "cooling-off" in skipped[J["inv_c"]], run.json()
    J["run2"], J["pay2"] = run.json()["run"], paid[J["inv2"]]["payment"]
    run = client.post("/v1/payments/runs", json={"run_date": "2027-01-05"}, headers={**fin, "Idempotency-Key": "run-3"})
    assert {p["invoice"] for p in run.json()["paid"]} == {J["inv4"]}, run.json()
    J["run3"] = run.json()["run"]
    assert any(e["reason"].startswith("bank change cooling-off") for e in run.json()["skipped"])
    # bank file of the finap run: sent, then the beneficiary bank returns the credit (account closed)
    r = client.post(f"/v1/payments/runs/{J['run2']}/file", json={"format": "NEFT_CSV"}, headers=fin)
    assert r.status_code == 201, r.text
    file2 = r.json()["number"]
    assert client.post(f"/v1/payment-files/{file2}/status", json={"status": "SENT"}, headers=fin).status_code == 200
    r = client.post(f"/v1/payment-files/{file2}/bank-results", json={"items": [{"payment": J["pay2"], "status": "RETURNED"}]}, headers=fin)
    _problem(r, 422, "REASON_REQUIRED")
    integration.FAULTS["fail"] = 1       # the ERP does not answer the reversal request: the clearing document stays open in the reconciliation
    try:
        r = client.post(f"/v1/payment-files/{file2}/bank-results",
                        json={"items": [{"payment": J["pay2"], "status": "RETURNED", "reason": "Beneficiary account closed"}]}, headers=fin)
    finally:
        integration.FAULTS["fail"] = 0
    assert r.status_code == 200 and r.json()["returned"] == [J["pay2"]] and r.json()["reconciled"] is True, r.text
    inv2 = _invoice(client, login, J["inv2"])
    assert inv2["status"] == "POSTED" and inv2["payment_status"] == "UNPAID"                      # payable again
    assert [p["status"] for p in inv2["payments"]] == ["CANCELLED"] and inv2["payments"][0]["bank_status"] == "RETURNED"
    # the ERP clearing document of the returned payment still stands: the reconciliation lists it until finance reverses it
    run_rec = client.post("/v1/reconciliation/runs", json={"company_code": "1000"}, headers=_h(login, "ap1"))
    assert run_rec.status_code == 201, run_rec.text
    items = {i["kind"]: i for i in run_rec.json()["items"]}
    assert "PAYMENT_RETURN_OPEN" in items and items["PAYMENT_RETURN_OPEN"]["ref"] == J["pay2"]
    assert not {"MISSING_IN_ERP", "AMOUNT_MISMATCH", "PAYMENT_MISSING_IN_ERP", "PAYMENT_AMOUNT_MISMATCH", "PAYMENT_NOT_IN_PLATFORM"} & set(items), items
    r = client.post(f"/v1/reconciliation/items/{items['PAYMENT_RETURN_OPEN']['id']}/resolve", json={"resolution": "Reversal booked in the ERP by treasury"},
                    headers=fin)
    assert r.status_code == 200 and r.json()["status"] == "RESOLVED"
    # the file of the second run is credited
    r = client.post(f"/v1/payments/runs/{J['run3']}/file", json={"format": "ISO20022_PAIN001"}, headers=fin)
    file3 = r.json()["number"]
    pay4 = client.get(f"/v1/payments?run={J['run3']}", headers=fin).json()["items"][0]["number"]
    client.post(f"/v1/payment-files/{file3}/status", json={"status": "SENT"}, headers=fin)
    assert client.post(f"/v1/payment-files/{file3}/bank-results", json={"items": [{"payment": pay4, "status": "CREDITED", "utr": "UTR0004"}]},
                       headers=fin).json()["reconciled"] is True
    assert _invoice(client, login, J["inv4"])["status"] == "PAID"


# ================================================================ 13. MSME due date, TDS deducted, returned payment paid again
def test_13_msme_due_run_with_tds_and_repayment(client, login, env):
    _pin(date(2027, 1, 15))
    fin = _h(login, "fin")
    assert J["inv_m"] not in [i["invoice"] for i in client.get("/v1/payments/proposal?run_date=2027-01-15", headers=fin).json()["items"]]
    _pin(date(2027, 1, 16))
    proposal = client.get("/v1/payments/proposal?run_date=2027-01-16", headers=fin).json()
    assert [i["invoice"] for i in proposal["items"]] == [J["inv_m"], J["inv2"]]                      # the MSME invoice first
    micro = proposal["items"][0]
    assert micro["msme"] is True and micro["msmeCapped"] is True and micro["tdsMinor"] == 200_000 and micro["amountMinor"] == 11_800_000 - 200_000
    run = client.post("/v1/payments/runs", json={"run_date": "2027-01-16"}, headers={**fin, "Idempotency-Key": "run-4"})
    assert run.status_code == 200, run.text
    paid = {p["invoice"]: p for p in run.json()["paid"]}
    assert set(paid) == {J["inv_m"], J["inv2"]} and paid[J["inv_m"]]["tdsMinor"] == 200_000 and paid[J["inv_m"]]["msme"] is True
    assert paid[J["inv_m"]]["amountMinor"] == 11_600_000 and "msmeInterestMinor" not in paid[J["inv_m"]]  # no bank rate published: no interest figure
    assert _invoice(client, login, J["inv_m"])["status"] == "PAID" and _invoice(client, login, J["inv2"])["status"] == "PAID"
    inv2 = _invoice(client, login, J["inv2"])
    assert sorted(p["status"] for p in inv2["payments"]) == ["CANCELLED", "COMPLETED"]
    register = client.get("/v1/finance/tds-register?fiscal_year=2026-27", headers=fin).json()
    assert register["totalTdsMinor"] == 200_000 and register["bySupplierSection"] == [{"supplier": "FIN-MICRO", "section": "194C-OTH", "tdsMinor": 200_000}]
    assert register["items"][0]["panOnFile"] is True
    # payables insight (INV-04)
    ins = client.get("/v1/payables/insights", headers=fin).json()
    assert ins["tdsWithheldMinor"] == 200_000 and ins["msme"]["paidInvoices"] == 1 and ins["msme"]["onTimePct"] == "100.0"
    assert ins["dpoDays"] is not None and ins["discountCapturePct"] is not None and ins["firstPassMatchPct"] is not None
    assert sum(ins["exceptionAgeing"].values()) >= 0 and "dueLadderMinor" in ins
    # a payment-completed event for every paid invoice, a returned-payment event for the bank return
    with tenant_tx(env.tenant_id) as s:
        from app.pic.models import OutboxEvent
        topics = [t for (t,) in s.execute(select(OutboxEvent.topic)).all()]
    for topic in ("invoice.captured", "invoice.exception.raised", "invoice.posted", "payment.completed", "payment.returned", "finance.period.closed",
                  "payment_file.results_recorded"):
        assert topic in topics, topic
    assert topics.count("payment.completed") == 5


# ================================================================ 14. savings realised from posted invoices, finance validation (SOD-07)
def test_14_savings_realised_and_finance_validation_sod07(client, login, env):
    _pin(date(2027, 1, 18))
    _tick(client, login)
    fin, owner = _h(login, "fin"), _h(login, "owner")
    register = {e["number"]: e for e in client.get("/v1/savings", headers=owner).json()}
    entry = register[J["initiative"]]
    # realised = (baseline 550.00 - invoiced 500.00) x (600 on INV1 + 450 - 50 credited on INV2), only from posted invoices
    assert entry["stage"] == "REALISING" and entry["realisedMinor"] == 50 * 100 * 1000 and entry["negotiatedMinor"] == 5_000_000 and entry["canValidate"] is False
    assert client.post(f"/v1/savings/{J['initiative']}/validate", headers=_h(login, "cm")).status_code == 403   # no finance role
    sod = _problem(client.post(f"/v1/savings/{J['initiative']}/validate", headers=owner), 409, "SOD_CONFLICT")
    assert sod["ruleRef"] == "SOD-07"
    fin_view = {e["number"]: e for e in client.get("/v1/savings", headers=fin).json()}
    assert fin_view[J["initiative"]]["canValidate"] is True
    waterfall = client.get(f"/v1/savings/{J['initiative']}/waterfall", headers=fin)
    assert waterfall.json()["budgetImpactMinor"] == 0                                                           # not validated yet
    _problem(client.post(f"/v1/savings/{J['initiative']}/validate", headers={**fin, "If-Match": '"999"'}), 412)
    r = client.post(f"/v1/savings/{J['initiative']}/validate", headers={**fin, "If-Match": waterfall.headers["ETag"]})
    assert r.status_code == 200 and r.json()["stage"] == "VALIDATED", r.text
    assert client.post(f"/v1/savings/{J['initiative']}/validate", headers=fin).status_code == 409
    after = client.get(f"/v1/savings/{J['initiative']}/waterfall", headers=fin).json()
    assert after["budgetImpactMinor"] == 5_000_000 and after["avoidanceMinor"] == 0
    pnl = client.get("/v1/savings/pnl?fiscal_year=2026-27", headers=fin)
    assert pnl.status_code == 200


# ================================================================ 15. audit trail, SoD evidence, event schemas, KPIs
def test_15_audit_sod_evidence_event_schemas_and_kpis(client, login, env):
    import json
    from jsonschema import Draft202012Validator
    from app.pic.events.catalogue import SCHEMAS
    from app.pic.models import OutboxEvent, SodViolation
    admin = _h(login, "admin")
    trail = client.get(f"/v1/audit/INVOICE/{J['inv2']}", headers=admin).json()
    actions = [e["action"] for e in (trail["items"] if isinstance(trail, dict) else trail)]
    for expected in ("CAPTURED", "CREDIT_NOTE_RECEIVED", "EXCEPTION_RESOLVED", "ERP_POSTED", "PAYMENT_RETURNED"):
        assert expected in actions, (expected, actions)
    assert client.get("/v1/audit/verify", headers=admin).json()["valid"] is True
    with tenant_tx(env.tenant_id) as s:
        codes = {c for (c,) in s.execute(select(SodViolation.rule_code)).all()}
        events = s.execute(select(OutboxEvent)).scalars().all()
    assert {"SOD-07", "SOD-08", "SOD-09"} <= codes, codes                                                  # every refusal left evidence
    for topic in ("payment.returned", "finance.period.closed", "finance.period.reopened", "payment_file.results_recorded"):
        schema = json.loads((SCHEMAS / f"{topic}.json").read_text(encoding="utf-8"))
        rows = [e for e in events if e.topic == topic]
        assert rows, topic
        for e in rows:
            Draft202012Validator(schema).validate(json.loads(json.dumps(e.payload, default=str)))
    # M10 KPIs from the data of this tenant
    first = _kpi(client, admin, "FIRST_PASS_MATCH")
    assert first["value"] is not None and 0 < float(first["value"]) < 100
    assert float(_kpi(client, admin, "DUPLICATES_PREVENTED")["value"]) >= 1
    assert _kpi(client, admin, "EXCEPTION_CYCLE")["value"] is not None
    assert _kpi(client, admin, "DISCOUNT_CAPTURE")["value"] is not None
    assert float(_kpi(client, admin, "DPO")["value"]) > 0


# ================================================================ 16. tenant isolation
def test_16_tenant_isolation(client, login, env):
    axn = login("ap.clerk", "AXN")
    assert client.get(f"/v1/invoices/{J['inv1']}", headers=axn).status_code == 404
    axn_invoices = client.get("/v1/invoices?limit=200", headers=axn).json()["items"]
    assert axn_invoices and not {i["number"] for i in axn_invoices} & {J["inv1"], J["inv2"], J["inv4"], J["inv_m"], J["inv_f"]}
    axn_payments = client.get(f"/v1/payments?run={J['run1']}&limit=200", headers=axn).json()["items"]      # numbering is per tenant: the same run number exists there
    assert not {p["invoice_number"] for p in axn_payments} & {J["inv1"], J["inv2"], J["inv4"], J["inv_m"]}
    ours = {p["id"] for p in client.get("/v1/payments?limit=200", headers=_h(login, "fin")).json()["items"]}
    assert ours and not ours & {p["id"] for p in axn_payments}
    # AXN may have periods of its own (the finance_ops dataset closes April-October 2026); none of this tenant's rows may show up there
    axn_periods = {x["id"] for x in client.get("/v1/finance/periods", headers=axn).json()["items"]}
    our_periods = {x["id"] for x in client.get("/v1/finance/periods", headers=_h(login, "fin")).json()["items"]}
    assert our_periods and not our_periods & axn_periods
    ours = client.get("/v1/invoices?limit=200", headers=_h(login, "ap1")).json()["items"]
    assert ours and all(not i["number"].startswith("INV-TF-") for i in ours)
    # worklist filters (INV-01)
    ap1 = _h(login, "ap1")
    assert {i["number"] for i in client.get("/v1/invoices?status=PAID", headers=ap1).json()["items"]} == {J["inv1"], J["inv2"], J["inv4"], J["inv_m"]}
    assert [i["number"] for i in client.get("/v1/invoices?supplier=FIN-MICRO", headers=ap1).json()["items"]] == [J["inv_m"]]
    assert [i["number"] for i in client.get("/v1/invoices?q=INV-M-00", headers=ap1).json()["items"]] == [J["inv_m"]]
    assert [i["number"] for i in client.get("/v1/invoices?msme=true", headers=ap1).json()["items"]] == [J["inv_m"]]
    assert {i["number"] for i in client.get("/v1/invoices?payment_block=true", headers=ap1).json()["items"]} >= {J["inv_b"]}
    assert J["inv2"] in {i["number"] for i in client.get("/v1/invoices?date_from=2026-12-04&date_to=2026-12-04&match_type=3WAY", headers=ap1).json()["items"]}
    assert client.get("/v1/invoices?has_open_exceptions=true", headers=ap1).json()["items"] == []


# ================================================================ 17. payment-due job proposes, a finance approver decides (discount window, cooling-off)
def test_17_payment_due_job_proposes_and_never_pays(client, login, env):
    # two more orders: ALPHA (terms 2/10 N30: a discount window) and MICRO (TDS 194C-OTH); partly received / invoiced on purpose
    _pin(date(2027, 1, 19))
    feb = date(2027, 2, 15)
    J["po_g"] = _create_po(client, login, "FIN-MAT-02", "30", "FIN-ALPHA", feb)
    J["po_h"] = _create_po(client, login, "FIN-MAT-03", "100", "FIN-MICRO", feb)
    _gr(client, login, J["po_g"], "20", date(2027, 1, 19), "DN-G-1")
    _gr(client, login, J["po_h"], "100", date(2027, 1, 19), "DN-H-1")
    r = _capture(client, _portal(login), "FIN-ALPHA", "INV-G-0001", date(2027, 1, 19), J["po_g"], "10", "1000")
    assert r.status_code == 201 and r.json()["status"] == "MATCHED", r.text
    J["inv_g"] = r.json()["number"]
    r = _capture(client, _portal(login, "FIN-MICRO"), "FIN-MICRO", "INV-H-0001", date(2027, 1, 19), J["po_h"], "100", "1000")
    assert r.status_code == 201 and r.json()["status"] == "MATCHED", r.text
    J["inv_h"] = r.json()["number"]
    for ref in (J["inv_g"], J["inv_h"]):
        assert _approve(client, login, ref, "ap1").status_code == 200
        r, _ = _post(client, login, ref, "ap2")
        assert r.status_code == 200 and r.json()["status"] == "POSTED", r.text
    inv_h = _invoice(client, login, J["inv_h"])
    assert inv_h["withholding_tax_minor"] == 200_000 and inv_h["due_date"] == (date(2027, 1, 19) + timedelta(days=45)).isoformat()
    # 27 January: INV-F falls due (27 Jan), INV-C is due but its supplier's bank change is cooling off, INV-G's 2 % discount closes on 29 Jan
    _pin(date(2027, 1, 27), 6)
    admin, fin = _h(login, "admin"), _h(login, "fin")
    with tenant_tx(env.tenant_id) as s:
        payments_before = s.execute(select(func.count()).select_from(Payment)).scalar()
    dry = client.post("/v1/admin/jobs/payment-due/run", json={"dryRun": True}, headers=admin)
    assert dry.status_code == 200 and dry.json()["result"]["action"] == "PROPOSE" and dry.json()["result"]["discountWindows"] == 1, dry.text
    r = client.post("/v1/admin/jobs/payment-due/run", json={}, headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "SUCCESS" and r.json()["result"]["action"] == "PROPOSED", r.text
    again = client.post("/v1/admin/jobs/payment-due/run", json={}, headers=admin).json()
    assert again["result"]["action"] == "PROPOSAL_EXISTS"
    with tenant_tx(env.tenant_id) as s:
        assert s.execute(select(func.count()).select_from(Payment)).scalar() == payments_before          # the job paid nothing
        from app.pic.models import Task
        task = s.execute(select(Task).where(Task.kind == "PAYMENT_RUN_PROPOSAL", Task.status == "OPEN")).scalar_one()
        ev = task.evidence
        assert task.candidate_role == "FINANCE_CONTROLLER" and task.object_ref == "PAYPROP-2027-01-27"
        assert J["inv_f"] in ev["invoices"] and J["inv_c"] in ev["invoices"] and J["inv_g"] not in ev["invoices"]
        assert [w["invoice"] for w in ev["discountWindows"]] == [J["inv_g"]] and ev["discountWindows"][0]["closesOn"] == "2027-01-29"
        assert ev["discountWindows"][0]["discountMinor"] == 23_600                                           # 2 % of INR 11,800.00
        assert {i["invoice"] for i in ev["proposal"]["items"]} == {J["inv_f"]}
        assert [x["invoice"] for x in ev["proposal"]["skipped"]] == [J["inv_c"]] and "cooling-off" in ev["proposal"]["skipped"][0]["reason"]
        assert ev["proposal"]["msme"] == {"count": 0, "overdue": 0, "capped": 0}
    # the approval: not the AP clerk; the finance controller approves and the normal payment run executes under her name
    assert _tasks(client, _h(login, "ap1"), "PAYPROP-2027-01-27") == []
    tasks = _tasks(client, fin, "PAYPROP-2027-01-27")
    assert len(tasks) == 1
    done = client.post(f"/v1/tasks/{tasks[0]['id']}/complete", json={"decision": "APPROVE", "comment": "Pay, take the Alpha discount"}, headers=fin)
    assert done.status_code == 200, done.text
    with tenant_tx(env.tenant_id) as s:
        result = s.get(Task, task.id).evidence["result"]
    J["run17"] = result["run"]
    assert result["paid"] == 2 and result["discountTaken"] == [J["inv_g"]] and any(J["inv_c"] in str(x) for x in result["skipped"])
    g = _invoice(client, login, J["inv_g"])
    assert g["status"] == "PAID" and g["payment_option"] == "EARLY_DISCOUNT" and g["discount_minor"] == 23_600
    assert _invoice(client, login, J["inv_f"])["status"] == "PAID"
    pays = {p["invoice_number"]: p for p in client.get(f"/v1/payments?run={J['run17']}", headers=fin).json()["items"]}
    assert pays[J["inv_g"]]["amount_minor"] == 1_180_000 - 23_600 and pays[J["inv_f"]]["currency"] == "USD" and pays[J["inv_f"]]["amount_minor"] == 70_800
    J["pay_g"], J["pay_f"] = pays[J["inv_g"]]["number"], pays[J["inv_f"]]["number"]


# ================================================================ 18. supplier finance maintenance: PAN and Udyam formats, role gate, ETag
def test_18_supplier_finance_maintenance_validation(client, login, env):
    supmgr = _h(login, "supmgr")
    view = client.get("/v1/suppliers/FIN-MICRO/finance", headers=supmgr)
    assert view.status_code == 200 and view.json()["etag"] == view.headers["ETag"] and view.json()["panOnFile"] is True
    assert view.json()["panFromGstin"].endswith("678K") and "194C-OTH" in view.json()["tdsSections"]
    base = {"msmeClass": "MICRO", "udyamNo": "UDYAM-KA-03-0012345", "tdsSection": "194C-OTH", "reason": "Annual review of the supplier master"}
    headers = {**supmgr, "If-Match": view.json()["etag"]}
    bad = client.put("/v1/suppliers/FIN-MICRO/finance", json={**base, "udyamNo": "UDYAM-KA-3-12345"}, headers=headers)
    assert _problem(bad, 422, "VALIDATION_FAILED")["errors"][0].startswith("Udyam")
    assert "PAN must be" in _problem(client.put("/v1/suppliers/FIN-MICRO/finance", json={**base, "pan": "ABCDE12"}, headers=headers), 422)["detail"]
    assert "inside the supplier's GSTIN" in _problem(client.put("/v1/suppliers/FIN-MICRO/finance", json={**base, "pan": "ZZZZZ9999Z"}, headers=headers), 422)["detail"]
    assert client.put("/v1/suppliers/FIN-MICRO/finance", json={**base, "pan": "AABCM5678K"}, headers=_h(login, "buyer")).status_code == 403
    ok = client.put("/v1/suppliers/FIN-MICRO/finance", json={**base, "udyamNo": "UDYAM-KA-03-0054321", "pan": "AABCM5678K"}, headers=headers)
    assert ok.status_code == 200 and ok.json()["panOnFile"] is True and ok.json()["udyamNo"] == "UDYAM-KA-03-0054321" and ok.json()["etag"] != view.json()["etag"], ok.text
    _problem(client.put("/v1/suppliers/FIN-MICRO/finance", json=base, headers=headers), 412)                    # the old ETag is stale now
    with tenant_tx(env.tenant_id) as s:
        from app.pic.models import AuditEvent
        events = [e for e in s.execute(select(AuditEvent).where(AuditEvent.action == "FINANCE_ATTRIBUTES_CHANGED")).scalars()]
        assert any((e.after or {}).get("panSet") for e in events) and all("AABCM5678K" not in str(e.after) for e in events)   # the PAN is never in the audit trail


# ================================================================ 19. s.197 certificate, TDS on a debit note, Form 26Q / 16A export
def test_19_certificate_debit_note_tds_and_tds_export(client, login, env):
    _pin(date(2027, 1, 28))
    supmgr, fin, ap1 = _h(login, "supmgr"), _h(login, "fin"), _h(login, "ap1")
    cert = {"certificateNo": "197/2026-27/0123", "section": "194C-OTH", "ratePct": "0.5", "validFrom": "2027-01-01", "validTo": "2027-03-31", "note": "AO order dated 2026-12-20"}
    assert client.post("/v1/suppliers/FIN-MICRO/tds-certificates", json=cert, headers=ap1).status_code == 403
    assert client.post("/v1/suppliers/FIN-MICRO/tds-certificates", json={**cert, "validTo": "2026-12-31"}, headers=supmgr).status_code == 422
    assert client.post("/v1/suppliers/FIN-MICRO/tds-certificates", json={**cert, "ratePct": "120"}, headers=supmgr).status_code == 422
    _problem(client.post("/v1/suppliers/FIN-MICRO/tds-certificates", json={**cert, "section": "999Z"}, headers=supmgr), 422, "TDS_SECTION_UNKNOWN")
    r = client.post("/v1/suppliers/FIN-MICRO/tds-certificates", json=cert, headers={**supmgr, "Idempotency-Key": "cert-1"})
    assert r.status_code == 201 and r.json()["certificates"][0]["validNow"] is True, r.text
    _problem(client.post("/v1/suppliers/FIN-MICRO/tds-certificates", json=cert, headers=supmgr), 409, "DUPLICATE_CERTIFICATE")
    # a freight debit note on INV-H: buyer chain, AP approval, posting; TDS 2 % on its net INR 10,000 is fixed at posting
    body = {"supplier_debit_note_no": "DN-H-0001", "note_date": "2027-01-28", "reason": "Freight charged on delivery",
            "lines": [{"kind": "CHARGE", "charge": "FREIGHT", "description": "Freight", "amount_minor": 1_000_000, "gst_rate": "18", "hsn": "996511"}]}
    r = client.post(f"/v1/invoices/{J['inv_h']}/debit-notes", json=body, headers=_portal(login, "FIN-MICRO"))
    assert r.status_code == 201, r.text
    dn = r.json()["number"]
    tasks = _tasks(client, _h(login, "buyer2"), dn)
    assert client.post(f"/v1/tasks/{tasks[0]['id']}/complete", json={"decision": "APPROVE", "comment": "Freight as per terms"}, headers=_h(login, "buyer2")).status_code == 200
    assert client.post(f"/v1/debit-notes/{dn}/approve", headers=_h(login, "ap2")).status_code == 200
    r = client.post(f"/v1/debit-notes/{dn}/post", headers={**_h(login, "ap2"), "Idempotency-Key": "dn-h-post"})
    assert r.status_code == 200 and r.json()["status"] == "POSTED", r.text
    with tenant_tx(env.tenant_id) as s:
        from app.pic.models import DebitNote
        note = s.execute(select(DebitNote).where(DebitNote.number == dn)).scalar_one()
        assert note.tds_base_minor == 1_000_000 and note.tds_minor == 20_000
    # payment: the certificate (0.5 %) replaces the section rate on the invoice and on the note netted into the payment
    url = f"/v1/payments/proposal?run_date=2027-01-28&include_not_due=true&invoice={J['inv_h']}"
    item = client.get(url, headers=fin).json()["items"][0]
    assert item["tdsMinor"] == 50_000 + 5_000 and item["amountMinor"] == 11_800_000 + 1_180_000 - 55_000
    run = client.post("/v1/payments/runs", json={"run_date": "2027-01-28", "include_not_due": True, "invoice_numbers": [J["inv_h"]]},
                      headers={**fin, "Idempotency-Key": "run-5"})
    assert run.status_code == 200 and run.json()["paid"][0]["amountMinor"] == 12_925_000 and run.json()["paid"][0]["tdsMinor"] == 55_000, run.text
    J["run19"], J["pay_h"] = run.json()["run"], run.json()["paid"][0]["payment"]
    with tenant_tx(env.tenant_id) as s:
        pay = s.execute(select(Payment).where(Payment.number == J["pay_h"])).scalar_one()
        assert pay.tds_certificate == "197/2026-27/0123" and Decimal(pay.tds_rate) == Decimal("0.5") and pay.tds_base_minor == 11_000_000
    # the quarterly returns (finance only): Q4 holds INV-M's payment (16 Jan, 2 %) and this one (28 Jan, certificate)
    import csv
    import io
    assert client.get("/v1/finance/tds-export?fiscal_year=2026-27&quarter=Q4", headers=ap1).status_code == 403
    r = client.get("/v1/finance/tds-export?fiscal_year=2026-27&quarter=Q4&format=26Q", headers=fin)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and r.headers["X-Row-Count"] == "2" and r.headers["X-Content-SHA256"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [x["PAN"] for x in rows] == ["AABCM5678K", "AABCM5678K"] and [x["Section"] for x in rows] == ["194C-OTH", "194C-OTH"]
    assert [x["Total Tax Deducted"] for x in rows] == ["2000.00", "550.00"] and rows[1]["Certificate u/s 197"] == "197/2026-27/0123"
    assert rows[1]["Amount Paid/Credited"] == "110000.00" and rows[1]["Deductee Code"] == "01"
    r = client.get("/v1/finance/tds-export?fiscal_year=2026-27&quarter=Q4&format=16A", headers=fin)
    totals = list(csv.DictReader(io.StringIO(r.text)))
    assert len(totals) == 1 and totals[0]["Total Tax Deducted"] == "2550.00" and totals[0]["Number of Payments"] == "2"
    assert len(list(csv.DictReader(io.StringIO(client.get("/v1/finance/tds-export?fiscal_year=2026-27&quarter=Q3", headers=fin).text)))) == 0
    _problem(client.get("/v1/finance/tds-export?fiscal_year=2026&quarter=Q1", headers=fin), 422)
    # revoke: a reason is needed, an unknown number is a 404, and a revoked certificate no longer applies
    _problem(client.post("/v1/suppliers/FIN-MICRO/tds-certificates/197/2026-27/0123/revoke", json={"reason": "no"}, headers=supmgr), 422)
    assert client.post("/v1/suppliers/FIN-MICRO/tds-certificates/NO-SUCH-CERT/revoke", json={"reason": "not found test"}, headers=supmgr).status_code == 404
    r = client.post("/v1/suppliers/FIN-MICRO/tds-certificates/197/2026-27/0123/revoke", json={"reason": "Assessing officer withdrew the order"}, headers=supmgr)
    assert r.status_code == 200 and r.json()["certificates"][0]["status"] == "REVOKED" and r.json()["certificates"][0]["validNow"] is False


# ================================================================ 20. bank statements (camt.053, MT940), ERP reversal of a returned payment
def _statement(name: str, **fill) -> str:
    from pathlib import Path
    text = (Path(__file__).parent / "fixtures" / "bank" / name).read_text(encoding="utf-8")
    for key, value in fill.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _upload(client, headers, text: str, filename: str, dry_run: bool):
    return client.post(f"/v1/bank-statements/import?dry_run={'true' if dry_run else 'false'}", files={"file": (filename, text.encode("utf-8"), "application/octet-stream")},
                       headers=headers)


def test_20_bank_statement_import_and_erp_reversal(client, login, env):
    _pin(date(2027, 1, 29))
    fin, ap1 = _h(login, "fin"), _h(login, "ap1")
    amounts = {p["number"]: p["amount_minor"] for run in (J["run17"], J["run19"]) for p in client.get(f"/v1/payments?run={run}", headers=fin).json()["items"]}
    money = lambda minor, sep=".": f"{minor / 100:.2f}".replace(".", sep)  # noqa: E731
    files = {}
    for run in (J["run17"], J["run19"]):
        r = client.post(f"/v1/payments/runs/{run}/file", json={"format": "ISO20022_PAIN001"}, headers=fin)  # run 17 holds the USD payment: NEFT is rupee-only (D31b)
        assert r.status_code == 201, r.text
        files[run] = r.json()["number"]
    camt = _statement("camt053_sample.xml", STMT="STMT-FIN-001", PAY_OK=J["pay_g"], PAY_RET=J["pay_f"], AMT_OK=money(amounts[J["pay_g"]]), AMT_RET=money(amounts[J["pay_f"]]))
    # nothing is recorded before the bank file was sent; then the dry run shows the plan and writes nothing
    dry = _upload(client, fin, camt, "stmt.xml", True)
    assert dry.status_code == 200 and dry.json()["counts"] == {"FILE_NOT_SENT": 2, "UNMATCHED": 1}, dry.text
    for number in files.values():
        assert client.post(f"/v1/payment-files/{number}/status", json={"status": "SENT"}, headers=fin).status_code == 200
    assert _upload(client, ap1, camt, "stmt.xml", True).status_code == 403
    dry = _upload(client, fin, camt, "stmt.xml", True).json()
    assert dry["dryRun"] is True and dry["counts"] == {"READY": 2, "UNMATCHED": 1} and dry["format"] == "CAMT053"
    assert {i["payment"]: i["action"] for i in dry["items"] if i["payment"]} == {J["pay_g"]: "CREDITED", J["pay_f"]: "RETURNED"}
    assert client.get(f"/v1/payments?run={J['run17']}", headers=fin).json()["items"][0]["bank_status"] == "SENT"
    # apply: the ERP does not answer the reversal of the returned payment (retry), the credited payment gets the bank reference as UTR
    integration.FAULTS["fail"] = 1
    try:
        applied = _upload(client, fin, camt, "stmt.xml", False)
    finally:
        integration.FAULTS["fail"] = 0
    assert applied.status_code == 200, applied.text
    out = applied.json()
    assert out["applied"] == 2 and out["credited"] == 1 and out["returned"] == 1 and out["replayed"] is False
    pays = {p["number"]: p for p in client.get(f"/v1/payments?limit=200", headers=fin).json()["items"]}
    assert pays[J["pay_g"]]["bank_status"] == "CREDITED" and pays[J["pay_g"]]["bank_utr"] == "HDFCR52027010500123"
    assert pays[J["pay_f"]]["bank_status"] == "RETURNED" and pays[J["pay_f"]]["status"] == "CANCELLED" and "account closed" in pays[J["pay_f"]]["return_reason"]
    f = _invoice(client, login, J["inv_f"])
    assert f["status"] == "POSTED" and f["payment_status"] == "UNPAID"                                          # payable again
    key = f"PAYREV|{J['pay_f']}"
    with tenant_tx(env.tenant_id) as s:
        message = s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == key)).scalar_one()
        assert message.status == "RETRY" and message.message_type == "PAYMENT_REVERSAL"
        message_id = message.id
    recon = client.post("/v1/reconciliation/runs", json={"company_code": "1000"}, headers=ap1).json()
    assert [i["ref"] for i in recon["items"] if i["kind"] == "PAYMENT_RETURN_OPEN"] == [J["pay_f"]]
    # replay delivers the reversal exactly once; the reconciliation item closes by itself
    r = client.post(f"/v1/integration/messages/{message_id}/replay", headers=_h(login, "admin"))
    assert r.status_code == 200 and r.json()["status"] == "POSTED", r.text
    assert client.post(f"/v1/integration/messages/{message_id}/replay", headers=_h(login, "admin")).status_code == 409
    recon = client.post("/v1/reconciliation/runs", json={"company_code": "1000"}, headers=ap1).json()
    assert "PAYMENT_RETURN_OPEN" not in {i["kind"] for i in recon["items"]}
    with tenant_tx(env.tenant_id) as s:
        assert s.execute(select(Payment.reversal_doc).where(Payment.number == J["pay_f"])).scalar_one()
        assert s.execute(select(func.count()).select_from(ErpDocument).where(ErpDocument.external_ref == key)).scalar() == 1
    # idempotent per statement id: the same statement replays, other content under the same id is refused
    again = _upload(client, fin, camt, "stmt.xml", False).json()
    assert again["replayed"] is True and again["applied"] == 2
    _problem(_upload(client, fin, camt.replace("HDFCR52027010500123", "HDFCR9999"), "stmt.xml", False), 409, "STATEMENT_ID_REUSED")
    assert _upload(client, fin, "this is not a statement", "x.txt", True).status_code == 422
    # MT940: a wrong amount is reported and not applied (the id stays free), the corrected statement applies; a return for an unknown payment is unmatched
    wrong = _statement("mt940_sample.sta", STMT="STMT-FIN-002", PAY_OK=J["pay_h"], PAY_RET="PAY-000000", AMT_OK_MT=money(amounts[J["pay_h"]] + 100, ","),
                       AMT_RET_MT="1,00")
    out = _upload(client, fin, wrong, "stmt.sta", False).json()
    assert out["counts"] == {"AMOUNT_MISMATCH": 1, "UNMATCHED": 2} and out["applied"] == 0
    right = wrong.replace(money(amounts[J["pay_h"]] + 100, ","), money(amounts[J["pay_h"]], ","))
    out = _upload(client, fin, right, "stmt.sta", False).json()
    assert out["format"] == "MT940" and out["credited"] == 1 and out["returned"] == 0 and out["counts"]["READY"] == 1
    listing = client.get("/v1/bank-statements", headers=fin).json()["items"]
    assert {s["statementId"] for s in listing} == {"STMT-FIN-001", "STMT-FIN-002-00001.001"}
    for number in files.values():
        rec = client.get(f"/v1/payment-files/{number}/reconciliation", headers=fin).json()
        assert rec["pendingMinor"] == 0 and rec["reconciled"] is True


# ================================================================ 21. period close also blocks credit notes, debit notes and goods receipts; GR/IR snapshot per close
def test_21_closed_period_blocks_credit_notes_debit_notes_and_goods_receipts(client, login, env):
    _pin(date(2027, 1, 30))
    fin, alpha = _h(login, "fin"), _portal(login)
    r = client.post("/v1/finance/periods/2026-12/close", json={"companyCode": "1000", "reason": "December close, second time"}, headers=fin)
    assert r.status_code == 200 and r.json()["status"] == "CLOSED", r.text
    cutoff = r.json()["cutoff"]
    snaps = client.get("/v1/finance/periods/2026-12/grir-snapshots?company_code=1000", headers=fin).json()["items"]
    assert len(snaps) == 2 and snaps[1]["closedAt"].startswith("2027-01-04")         # the close of test 11 left its own snapshot
    assert snaps[0]["totalMinor"] == cutoff["grirAccrualMinor"] and cutoff["grirSnapshot"] == snaps[0]["id"]
    line = [l for l in snaps[0]["lines"] if l["po"] == J["po_g"]]
    assert line and line[0]["accrualMinor"] == 10 * 100_000                       # 20 received, 10 invoiced, at INR 1,000.00
    _pin(date(2026, 12, 30))                                                       # the documents are dated into the closed month
    credit = {"supplier_credit_note_no": "CN-LATE-1", "note_date": "2026-12-30", "reason": "Late credit for damaged goods",
              "lines": [{"invoice_line": 10, "qty": "1"}]}
    for problem in (client.post(f"/v1/invoices/{J['inv1']}/credit-notes", json=credit, headers=alpha),
                    client.post(f"/v1/invoices/{J['inv1']}/debit-notes", json={"supplier_debit_note_no": "DN-LATE-1", "note_date": "2026-12-30", "reason": "Late freight",
                                "lines": [{"kind": "CHARGE", "charge": "FREIGHT", "description": "Freight", "amount_minor": 50_000, "gst_rate": "18", "hsn": "996511"}]}, headers=alpha),
                    client.post("/v1/goods-receipts", json={"po": J["po_g"], "delivery_note": "DN-G-2", "posting_date": "2026-12-30",
                                                             "lines": [{"line": 10, "qty": "10", "storage_location": "0001"}]}, headers=_h(login, "receiver"))):
        body = _problem(problem, 409, "PERIOD_CLOSED")
        assert body["period"] == "2026-12" and body["reopenScope"] == "period:close" and "Reopen rule" in body["detail"]
    # the reopen rule: finance reopens with a reason, then the late goods receipt posts; closing again adds a second snapshot
    assert client.post("/v1/finance/periods/2026-12/reopen", json={"companyCode": "1000", "reason": "Late receipt of December goods"}, headers=fin).status_code == 200
    r = client.post("/v1/goods-receipts", json={"po": J["po_g"], "delivery_note": "DN-G-2", "posting_date": "2026-12-30",
                                                 "lines": [{"line": 10, "qty": "10", "storage_location": "0001"}]}, headers=_h(login, "receiver"))
    assert r.status_code == 201, r.text
    _pin(date(2027, 1, 30), 15)
    assert client.post("/v1/finance/periods/2026-12/close", json={"companyCode": "1000"}, headers=fin).status_code == 200
    snaps = client.get("/v1/finance/periods/2026-12/grir-snapshots?company_code=1000", headers=fin).json()["items"]
    assert len(snaps) == 3 and snaps[0]["totalMinor"] == snaps[1]["totalMinor"] + 10 * 100_000                    # the late receipt added 10 uninvoiced pieces
    assert client.post("/v1/finance/periods/2026-12/reopen", json={"companyCode": "1000", "reason": "Leave the month open for the next tests"}, headers=fin).status_code == 200
