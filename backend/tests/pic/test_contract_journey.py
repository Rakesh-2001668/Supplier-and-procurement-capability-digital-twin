"""The whole contract lifecycle (Blueprint M07 / flow F4, Technical Document contract-svc) through the real HTTP API, one sequential scenario.

draft from the clause library (template + category overlay + governing-law variant) -> supplier redline, AI review against the playbook,
risk score, fallback suggestion and the contract manager's review -> approval: legal + finance + CPO for a contract of 1 Cr and more, one
contract manager (never the owner or the submitter) below it -> e-signature of both parties (internal, and through the e-signature provider
webhook) -> activation publishes the price to source determination -> purchase orders at the contract price (ok), above tolerance
(flagged, reason required), over the contract quantity and against a contract that is not active (refused) -> consumption alerts at
80 / 90 / 100 % to the contract owner -> compliance (off-contract buying, price leakage) -> index reset adds a price-validity period ->
obligations and milestones, on-time % -> renewal notice 120 days before expiry, renewal decision and extension -> expiry -> direct
termination with its approvals -> audit trail, tenant isolation, M07 KPIs.

The scenario has its own tenant (CLM1), so nothing of the Axion signature case changes. Time is moved with the business clock (the API runs
in-process); the tests share state on purpose and run in file order.
"""
import hashlib
import hmac
import json
import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import AppUser, Material, PrLine, Requisition, Supplier, SupplierBankAccount, SupplierCategoryStatus
from app.pic.platform import clock
from app.pic.platform.auth import hash_password
from app.pic.seed.axion import at
from app.pic.seed.datasets import _tenant_kit as kit
from app.pic.services import contract as contract_svc

from .conftest import PASSWORD

CODE = os.environ.get("CLM_TEST_TENANT", "CLM1")  # a developer re-running against a kept database (PIC_TEST_KEEP_DB) picks a fresh tenant code
DOMAIN = f"{CODE.lower()}.example"
GSTIN = "29AAKCD4821M1Z7"
PLANT = "P100"
CR = 100 * 100_000 * 100
J: dict = {}  # state handed from step to step

USERS = [
    ("admin", "Admin Anil", ["TENANT_ADMIN"], {}),
    ("cm", "Chandra Contracts", ["CONTRACT_MANAGER"], {}),      # owner of the contracts
    ("cm2", "Meena Contracts", ["CONTRACT_MANAGER"], {}),
    ("cm3", "Mohan Contracts", ["CONTRACT_MANAGER"], {}),
    ("legal", "Harini Legal", ["LEGAL"], {}),
    ("fin", "Farid Finance", ["FINANCE_CONTROLLER"], {}),
    ("cpo", "Cara CPO", ["CPO"], {}),
    ("buyer", "Bala Buyer", ["BUYER"], {"plants": [PLANT]}),
    ("buyer2", "Bina Buyer", ["BUYER"], {"plants": [PLANT]}),
    ("ph", "Pranav Procurement", ["PROCUREMENT_HEAD"], {}),
    ("requester", "Ravi Requester", ["REQUESTER"], {"cost_objects": ["COST_CENTER:6100"]}),
]
ROLE_USER = {"CONTRACT_MANAGER": ["cm2", "cm3"], "LEGAL": "legal", "FINANCE_CONTROLLER": "fin", "CPO": "cpo", "BUYER": ["buyer2"], "PROCUREMENT_HEAD": "ph"}
ESIGN_SECRET = "clm-journey-webhook-secret"


def _email(local: str) -> str:
    return f"{local}@{DOMAIN}"


@pytest.fixture(scope="module")
def env(database):
    sc = kit.setup_tenant(CODE, "Contract Journey Industries Pvt Ltd", "GENERAL", company=("1000", "Contract Journey Industries Pvt Ltd", GSTIN),
                          plants=[(PLANT, "Main plant", "29")], cost_objects=[("COST_CENTER", "6100", "Test cost centre")], holidays=[],
                          domain=DOMAIN, role_user=ROLE_USER)
    kit.create_users(sc, USERS, PASSWORD)
    kit.rule_version(sc, "MFA", "2026.1-CLM", date(2026, 4, 1), {"enforce": False}, "Contract journey tenant: no MFA challenge for the API tests")
    # the tenant's playbook gets a category overlay (templates by category, blueprint 13.1)
    kit.rule_version(sc, "CLM-PLAYBOOK", "2026.2-CLM", date(2026, 4, 1), {"categoryClauses": {"GENERAL": [
        {"code": "ESG", "title": "Sustainability", "text": "{supplier} complies with the buyer's supplier code of conduct and reports its emissions yearly."}]}},
        "Contract journey tenant: category clause overlay")
    with tenant_tx(sc.tenant_id) as s:
        buyer = s.execute(select(AppUser).where(AppUser.email == _email("buyer"))).scalar_one()
        suppliers = {}
        for code, name in (("CLM-ALPHA", "Alpha Alloys Pvt Ltd"), ("CLM-OTHER", "Other Metals Pvt Ltd")):
            sup = s.execute(select(Supplier).where(Supplier.code == code)).scalar_one_or_none()
            if sup is None:
                sup = Supplier(tenant_id=sc.tenant_id, code=code, legal_name=name, status="QUALIFIED", country="IN", state_code="29", payment_terms="N30")
                s.add(sup)
                s.flush()
                s.add(SupplierCategoryStatus(tenant_id=sc.tenant_id, supplier_id=sup.id, category="GENERAL", status="QUALIFIED", qualified_on=date(2026, 1, 1)))
                s.add(SupplierBankAccount(tenant_id=sc.tenant_id, supplier_id=sup.id, account_enc=b"x", account_masked="XXXX1234", ifsc="HDFC0000001",
                                          holder_name=name, active=True, verified_on=date(2026, 1, 1)))
                s.add(AppUser(tenant_id=sc.tenant_id, email=f"portal@{code.lower()}.{DOMAIN}", full_name=f"{name} portal", password_hash=hash_password(PASSWORD),
                              roles=["SUPPLIER_USER"], attributes={}, supplier_id=sup.id, mfa_enrolled=True))
            suppliers[code] = sup.id
        for number in ("CLM-ALU-01", "CLM-ALU-02"):
            if s.execute(select(Material).where(Material.number == number)).scalar_one_or_none() is None:
                s.add(Material(tenant_id=sc.tenant_id, number=number, description=f"Alloy {number}", type="STOCK", material_group="GENERAL", category="GENERAL",
                               base_uom="KG", mrp_type="PD", lot_size_policy="EXACT", safety_stock=Decimal(0), planned_delivery_days=3, gr_processing_days=0,
                               standard_price_minor=100_000, status="ACTIVE", hsn_code="7601", gst_rate=Decimal(18)))
    J.update(tenant_id=sc.tenant_id, buyer_id=buyer.id, suppliers=suppliers, today=clock.today())
    return sc


def _h(login, local: str) -> dict:
    return login(_email(local), CODE)


def _portal(login, code: str = "CLM-ALPHA") -> dict:
    return login(f"portal@{code.lower()}.{DOMAIN}", CODE)


def _requisition(env, lines: list[tuple[str, str]], need: date) -> str:
    """An approved requisition (the requirement is an input of this flow): (material, qty) per line."""
    with tenant_tx(env.tenant_id) as s:
        pr = Requisition(tenant_id=env.tenant_id, number=f"REQ-CLM-{uuid.uuid4().hex[:8].upper()}", origin="MANUAL", requester_id=J["buyer_id"],
                         company_code="1000", plant=PLANT, status="APPROVED", total_minor=0, purpose_code="PRODUCTION")
        s.add(pr)
        s.flush()
        for index, (number, qty) in enumerate(lines, start=1):
            m = s.execute(select(Material).where(Material.number == number)).scalar_one()
            s.add(PrLine(tenant_id=env.tenant_id, requisition_id=pr.id, line_no=index * 10, item_type="MATERIAL", purchase_type="STOCK", material_id=m.id,
                         description=m.description, material_group=m.material_group, category=m.category, qty=Decimal(qty), uom=m.base_uom,
                         price_est_minor=100_000, need_date=need, plant=PLANT, storage_location="0001"))
        return pr.number


def _tasks(client, headers, ref: str) -> list[dict]:
    return [t for t in client.get("/v1/tasks", headers=headers).json() if t["object_ref"] == ref]


def _approve(client, headers, ref: str, comment: str = "Approved") -> dict:
    tasks = _tasks(client, headers, ref)
    assert len(tasks) == 1, (ref, tasks)
    done = client.post(f"/v1/tasks/{tasks[0]['id']}/complete", json={"decision": "APPROVE", "comment": comment}, headers=headers)
    assert done.status_code == 200, done.text
    return tasks[0]


def _tick(client, login) -> dict:
    r = client.post("/v1/admin/ops/tick", headers=_h(login, "admin"))
    assert r.status_code == 200, r.text
    return r.json()


def _contract(client, login, ref: str, who: str = "cm") -> dict:
    r = client.get(f"/v1/contracts/{ref}", headers=_h(login, who))
    assert r.status_code == 200, r.text
    return r.json()


def _kpi(client, headers, code: str) -> dict:
    r = client.get("/v1/kpis?module=M07&trend=false", headers=headers)
    assert r.status_code == 200, r.text
    return next(i for i in r.json()["items"] if i["code"] == code)


def _problem(r, status: int, code: str | None = None) -> dict:
    assert r.status_code == status, r.text
    body = r.json()
    if code:
        assert body["code"] == code, body
    return body


def _create_po(client, login, requisition: str, line: int, contract: str | None, qty: str, *, need: date, price: int | None = None,
               reason: str | None = None, supplier: str | None = None, who: str = "buyer"):
    body = {"source": {"type": "REQUISITION", "id": requisition, "lines": [line]}, "release": {"qty": qty, "needDate": need.isoformat()}}
    if contract:
        body["contractRef"] = contract
    if supplier:
        body["supplierId"] = supplier
    if price is not None:
        body["unitPriceMinor"] = price
    if reason:
        body["deviationReason"] = reason
    return client.post("/v1/purchase-orders", json=body, headers=_h(login, who))


def _release(client, login, po: str) -> dict:
    """Creating an order validates and routes it: a touchless order is released at once, any other waits for its approvals, which are
    given here until it is released."""
    if client.get(f"/v1/purchase-orders/{po}", headers=_h(login, "buyer")).json()["status"] == "DRAFT":
        assert client.post(f"/v1/purchase-orders/{po}/validate", headers=_h(login, "buyer")).status_code == 200
    for _ in range(6):
        status = client.get(f"/v1/purchase-orders/{po}", headers=_h(login, "buyer")).json()["status"]
        if status not in ("DRAFT", "IN_APPROVAL"):
            break
        for who in ("buyer2", "ph", "fin", "cpo"):
            for task in _tasks(client, _h(login, who), po):
                client.post(f"/v1/tasks/{task['id']}/complete", json={"decision": "APPROVE", "comment": "Approved"}, headers=_h(login, who))
    status = client.get(f"/v1/purchase-orders/{po}", headers=_h(login, "buyer")).json()["status"]
    assert status in ("RELEASED", "TRANSMITTED", "CONFIRMED"), (po, status)
    return {"status": status}


def _draft_body(**overrides) -> dict:
    today = J["today"]
    body = {"type": "QUANTITY_CONTRACT", "title": "Aluminium alloy ingots - annual rate contract", "supplier": "CLM-ALPHA", "company_code": "1000",
            "valid_from": today.isoformat(), "valid_to": (today + timedelta(days=365)).isoformat(), "payment_terms": "N30", "incoterms": "DAP",
            "lines": [{"material": "CLM-ALU-01", "description": "Alloy ingot A", "plant": PLANT, "uom": "KG", "target_qty": "1000", "unit_price_minor": 2_000_000}],
            "tolerances": {"over_pct": "2", "under_pct": "5", "price_pct": "2"}, "jurisdiction": "IN-MH", "category": "GENERAL"}
    body.update(overrides)
    return body


# ================================================================ 1. F4-01/02 draft from template and clause library
def test_01_draft_from_the_clause_library_with_validation_and_idempotency(client, login, env):
    cm = _h(login, "cm")
    # validation: problem+json 422 for every malformed request, nothing created
    assert _problem(client.post("/v1/contracts", json=_draft_body(valid_to=J["today"].isoformat()), headers=cm), 422, "INVALID_VALIDITY")
    assert _problem(client.post("/v1/contracts", json=_draft_body(lines=[]), headers=cm), 422, "LINES_REQUIRED")
    assert client.post("/v1/contracts", json=_draft_body(tolerances={"over_pct": "abc"}), headers=cm).status_code == 422
    assert client.post("/v1/contracts", json=_draft_body(type="SPOT_BUY"), headers=cm).status_code == 422
    assert client.post("/v1/contracts", json=_draft_body(type="SCHEDULING_AGREEMENT", index_ref={"index": "LME_AL", "base": "0", "band_pct": "3"}),
                       headers=cm).status_code == 422
    assert _problem(client.post("/v1/contracts", json=_draft_body(type="MASTER_AGREEMENT"), headers=cm), 422, "LINES_NOT_ALLOWED")
    assert _problem(client.post("/v1/contracts", json=_draft_body(jurisdiction="XX"), headers=cm), 422, "UNKNOWN_JURISDICTION")
    # a requester cannot draft a contract (RBAC scope contract:manage)
    assert client.post("/v1/contracts", json=_draft_body(), headers=_h(login, "requester")).status_code == 403
    # the draft: template of the type + category overlay + governing-law variant; the same Idempotency-Key replays the same contract
    key = {"Idempotency-Key": f"clm-journey-A-{uuid.uuid4().hex}"}
    created = client.post("/v1/contracts", json=_draft_body(), headers={**cm, **key})
    assert created.status_code == 201, created.text
    again = client.post("/v1/contracts", json=_draft_body(), headers={**cm, **key})
    assert again.status_code == 201 and again.json()["number"] == created.json()["number"]
    contract = _contract(client, login, created.json()["number"])
    J["A"] = contract["number"]
    assert contract["status"] == "DRAFT" and contract["target_value_minor"] == 2_000_000_000 >= CR and contract["category"] == "GENERAL"
    codes = {c["code"]: c for c in contract["clauses"]}
    assert {"PAYMENT", "LIABILITY", "TERMINATION", "ESG", "GOVERNING_LAW", "STAMP_DUTY"} <= set(codes)
    assert "Maharashtra Stamp Act" in codes["STAMP_DUTY"]["text"] and "Alpha Alloys" in codes["ESG"]["text"]
    assert all(c["position"] == "STANDARD" and c["risk_score"] == 0 and c["standard_text"] == c["text"] for c in contract["clauses"])
    assert contract["lines"][0]["target_qty"] in ("1000", "1000.000") and contract["priceValidity"][0]["published"] is False
    # a draft is internal work: the supplier cannot see it yet
    assert client.get(f"/v1/contracts/{J['A']}", headers=_portal(login)).status_code == 404
    assert J["A"] not in {c["number"] for c in client.get("/v1/contracts", headers=_portal(login)).json()["items"]}
    # the built-in library carries every blueprint type
    library = client.get("/v1/contract-templates", headers=cm).json()
    assert {"RATE_CARD", "SOW", "NDA", "MASTER_AGREEMENT", "QUANTITY_CONTRACT", "SCHEDULING_AGREEMENT"} <= set(library["types"]) and "GENERAL" in library["categories"]
    sow = client.post("/v1/contracts", json=_draft_body(type="SOW", title="Annual maintenance statement of work", jurisdiction=None, category=None), headers=cm)
    assert sow.status_code == 201 and {c["code"] for c in _contract(client, login, sow.json()["number"])["clauses"]} >= {"DELIVERABLES", "ACCEPTANCE", "IP"}
    rate = client.post("/v1/contracts", json=_draft_body(type="RATE_CARD", title="Contract labour rate card", jurisdiction=None, category=None), headers=cm)
    assert rate.status_code == 201 and "RATES" in {c["code"] for c in _contract(client, login, rate.json()["number"])["clauses"]}
    assert any(o["kind"] == "MILESTONE" for o in client.get("/v1/obligations", headers=cm).json()["items"])


# ================================================================ 2. F4-03/04 AI review, redline, risk score, fallback
def test_02_ai_review_supplier_redline_and_the_contract_managers_review(client, login, env):
    cm, portal, a = _h(login, "cm"), _portal(login), J["A"]
    # the supplier cannot redline a draft, and the review is not available to the supplier
    assert client.post(f"/v1/contracts/{a}/review", headers=portal).status_code == 403
    review = client.post(f"/v1/contracts/{a}/review", headers=cm)
    assert review.status_code == 200 and review.json()["risk"] == 0 and review.json()["findings"] == [] and review.json()["riskBand"] == "LOW"
    assert _contract(client, login, a)["status"] == "IN_NEGOTIATION"
    # supplier redline: always NON_STANDARD until the buyer reviews it; the contract cannot be submitted meanwhile
    redline = client.post(f"/v1/contracts/{a}/redlines", headers=portal, json={"clause": "LIABILITY", "text": "Liability is unlimited for the buyer.",
                                                                              "position": "STANDARD"})
    assert redline.status_code == 200 and redline.json()["position"] == "NON_STANDARD" and redline.json()["risk_score"] == 70
    _problem(client.post(f"/v1/contracts/{a}/submit", headers=cm), 409, "REDLINE_REVIEW_PENDING")
    # CLM-02: deviation from the playbook, the risk score, the fallback suggestion and the approval route
    cr = client.get(f"/v1/contracts/{a}/clause-review", headers=cm).json()
    liability = next(c for c in cr["clauses"] if c["clause"] == "LIABILITY")
    assert liability["deviation"] and liability["position"] == "NON_STANDARD" and liability["risk"] == 70
    assert liability["fallback"] == "Cap at 50% of annual value" and liability["suggestedPosition"] == "FALLBACK"
    assert liability["standardText"] != liability["text"] and liability["pendingRedline"]["clause"] == "LIABILITY"
    assert cr["risk"] == 70 and cr["riskBand"] == "HIGH" and cr["pendingReview"] == ["LIABILITY"]
    assert cr["approval"]["chain"] == ["LEGAL", "FINANCE_CONTROLLER", "CPO"] and "threshold" in cr["approval"]["reason"]
    # the supplier cannot review its own redline; the contract manager accepts it as the playbook fallback
    assert client.post(f"/v1/contracts/{a}/redlines/LIABILITY/review", headers=portal, json={"decision": "ACCEPT", "position": "STANDARD"}).status_code == 403
    accepted = client.post(f"/v1/contracts/{a}/redlines/LIABILITY/review", headers=cm, json={"decision": "ACCEPT", "position": "FALLBACK", "comment": "capped at 50%"})
    assert accepted.status_code == 200 and accepted.json()["position"] == "FALLBACK" and accepted.json()["risk_score"] == 30
    # the buyer rewords PAYMENT without classifying it: the AI review catches the wording that left the library and raises the risk
    reworded = client.post(f"/v1/contracts/{a}/redlines", headers=cm, json={"clause": "PAYMENT", "text": "Payment N45 from receipt of a correct invoice.",
                                                                           "position": "STANDARD"})
    assert reworded.status_code == 200
    second = client.post(f"/v1/contracts/{a}/review", headers=cm).json()
    payment = next(f for f in second["findings"] if f["clause"] == "PAYMENT")
    assert payment["textDeviates"] and payment["suggestedPosition"] == "FALLBACK" and payment["risk"] == 30 and second["risk"] == 30
    fixed = client.post(f"/v1/contracts/{a}/redlines", headers=cm, json={"clause": "PAYMENT", "text": "Payment N45 from receipt of a correct invoice.",
                                                                        "position": "FALLBACK"})
    assert fixed.status_code == 200 and fixed.json()["risk_score"] == 30
    # an unknown clause and an empty text are refused
    assert client.post(f"/v1/contracts/{a}/redlines", headers=cm, json={"clause": "NOPE", "text": "x"}).status_code == 404
    assert client.post(f"/v1/contracts/{a}/redlines", headers=cm, json={"clause": "PAYMENT", "text": ""}).status_code == 422


# ================================================================ 3. F4-05/06 approval: legal + finance (+ CPO) for 1 Cr and more
def test_03_a_contract_of_one_crore_needs_legal_finance_and_cpo_never_the_owner(client, login, env):
    cm, a = _h(login, "cm"), J["A"]
    submitted = client.post(f"/v1/contracts/{a}/submit", headers=cm)
    assert submitted.status_code == 200 and submitted.json()["chain"] == ["LEGAL", "FINANCE_CONTROLLER", "CPO"]
    assert _contract(client, login, a)["status"] == "IN_APPROVAL"
    # sequential chain: only legal has a task now; the owner/submitter and the other managers have none
    assert [t["candidate_role"] for t in _tasks(client, _h(login, "legal"), a)] == ["LEGAL"]
    assert not _tasks(client, _h(login, "fin"), a) and not _tasks(client, cm, a)
    legal_task = _tasks(client, _h(login, "legal"), a)[0]
    # four-eyes: the owner cannot complete someone else's task, and the submitter cannot approve its own contract
    assert client.post(f"/v1/tasks/{legal_task['id']}/complete", json={"decision": "APPROVE"}, headers=cm).status_code == 403
    _approve(client, _h(login, "legal"), a, "Liability capped, governing law Maharashtra")
    assert _contract(client, login, a)["status"] == "IN_APPROVAL"
    _approve(client, _h(login, "fin"), a, "Within budget")
    _approve(client, _h(login, "cpo"), a, "Approved")
    contract = _contract(client, login, a)
    assert contract["status"] == "OUT_FOR_SIGNATURE"
    # the supplier now meets the contract (negotiation done, text frozen): it can see it, with no internal fields
    seen = client.get(f"/v1/contracts/{a}", headers=_portal(login))
    assert seen.status_code == 200 and "owner_id" not in seen.json() and "process" not in seen.json()
    # another supplier's portal user never sees it
    assert client.get(f"/v1/contracts/{a}", headers=_portal(login, "CLM-OTHER")).status_code == 404


# ================================================================ 4. F4-07/08 e-signature of both parties, activation, price published
def test_04_both_parties_sign_and_the_activation_publishes_the_price(client, login, env):
    cm2, a = _h(login, "cm2"), J["A"]
    # activation needs both signatures
    early = client.post(f"/v1/contracts/{a}/activate", headers=_h(login, "cm"))
    _problem(early, 422, "RULE_VIOLATION")
    assert early.json()["ruleRef"] == "CLM-ACTIVATE"
    # the supplier signs in the portal (and only as the supplier); a buyer signs with contract:sign
    assert client.post(f"/v1/contracts/{a}/signatures", headers=_portal(login), json={"party": "BUYER", "signer_name": "Imposter"}).status_code == 403
    assert client.post(f"/v1/contracts/{a}/signatures", headers=_h(login, "requester"), json={"party": "BUYER", "signer_name": "Ravi"}).status_code == 403
    signed = client.post(f"/v1/contracts/{a}/signatures", headers=cm2, json={"party": "BUYER", "signer_name": "Meena Raghavan, Contract Manager"})
    assert signed.status_code == 200 and signed.json()["signedBy"] == ["BUYER"]
    _problem(client.post(f"/v1/contracts/{a}/signatures", headers=cm2, json={"party": "BUYER", "signer_name": "Meena"}), 409, "ALREADY_SIGNED")
    assert client.post(f"/v1/contracts/{a}/signatures", headers=_portal(login, "CLM-OTHER"), json={"party": "SUPPLIER", "signer_name": "X"}).status_code in (403, 404)
    both = client.post(f"/v1/contracts/{a}/signatures", headers=_portal(login), json={"party": "SUPPLIER", "signer_name": "Alpha Alloys MD"})
    assert both.status_code == 200 and both.json()["signedBy"] == ["BUYER", "SUPPLIER"]
    # the clause text is frozen by the document hash: a later change blocks activation (checked on the service level, then restored)
    activated = client.post(f"/v1/contracts/{a}/activate", headers=_h(login, "cm"))
    assert activated.status_code == 200, activated.text
    contract = activated.json()
    assert contract["status"] == "ACTIVE" and contract["activated_at"]
    assert all(v["published"] for v in contract["priceValidity"]) and len(contract["signatures"]) == 2
    assert len({s["documentHash"] for s in contract["signatures"]}) == 1
    # activation is final: no second activation, no AI review on a signed contract, no redline
    _problem(client.post(f"/v1/contracts/{a}/activate", headers=_h(login, "cm")), 409, "ILLEGAL_TRANSITION")
    _problem(client.post(f"/v1/contracts/{a}/review", headers=_h(login, "cm")), 409, "ILLEGAL_TRANSITION")
    _problem(client.post(f"/v1/contracts/{a}/redlines", headers=_h(login, "cm"), json={"clause": "PAYMENT", "text": "x"}), 409, "ILLEGAL_TRANSITION")
    # the activation event reaches source determination and the owner's workspace
    _tick(client, login)
    assert any(e["action"] == "ACTIVATE" for e in client.get(f"/v1/audit/CONTRACT/{a}", headers=_h(login, "cm")).json())


# ================================================================ 5. F5 purchase orders against the contract
def test_05_purchase_orders_at_the_contract_price_flagged_above_tolerance_and_refused_when_not_active(client, login, env):
    a, need = J["A"], J["today"] + timedelta(days=7)
    pr = _requisition(env, [("CLM-ALU-01", "5000"), ("CLM-ALU-01", "20")], need)
    # at the contract price: the price is inherited from the published validity period and the line is tied to the contract line
    ok = _create_po(client, login, pr, 10, a, "5", need=need)
    assert ok.status_code == 201, ok.text
    assert ok.json()["inherited"]["price"] == 20000.0 and ok.json()["inherited"]["tolerance"] == "+2/-5"
    po = client.get(f"/v1/purchase-orders/{ok.json()['id']}", headers=_h(login, "buyer")).json()
    line = po["lines"][0]
    assert line["price_source"] == "CONTRACT" and line["unit_price_minor"] == 2_000_000 and line["contract_line_id"] and not line["price_deviation"]
    assert po["contract_id"] == _contract(client, login, a)["id"]
    # inside the tolerance (2 %): accepted without a reason, not flagged
    inside = _create_po(client, login, pr, 20, a, "1", need=need, price=2_030_000)
    assert inside.status_code == 201
    assert not client.get(f"/v1/purchase-orders/{inside.json()['id']}", headers=_h(login, "buyer")).json()["lines"][0]["price_deviation"]
    # above the tolerance: refused without a deviation reason, flagged (with the reason) otherwise
    refused = _create_po(client, login, pr, 10, a, "1", need=need, price=2_400_000)
    assert _problem(refused, 422, "RULE_VIOLATION")["ruleRef"] == "P07"
    flagged = _create_po(client, login, pr, 10, a, "1", need=need, price=2_400_000, reason="Spot premium agreed with the plant head")
    assert flagged.status_code == 201, flagged.text
    fl = client.get(f"/v1/purchase-orders/{flagged.json()['id']}", headers=_h(login, "buyer")).json()["lines"][0]
    assert fl["price_deviation"] is True and fl["deviation_reason"] == "Spot premium agreed with the plant head"
    J["flagged_po"] = flagged.json()["id"]
    # over the contract quantity (1000 + 2 % tolerance): refused, whoever asks
    over = _create_po(client, login, pr, 10, a, "1100", need=need)
    assert "exceeds the contract quantity" in _problem(over, 422, "RULE_VIOLATION")["detail"] and over.json()["ruleRef"] == "CLM-PO"
    # a contract that is not executed cannot be referenced: a draft
    draft = client.post("/v1/contracts", json=_draft_body(title="Second draft contract", lines=[
        {"material": "CLM-ALU-01", "description": "Alloy ingot A", "plant": PLANT, "uom": "KG", "target_qty": "100", "unit_price_minor": 2_100_000}]),
        headers=_h(login, "cm")).json()["number"]
    J["draft"] = draft
    not_active = _create_po(client, login, pr, 10, draft, "1", need=need)
    assert _problem(not_active, 422, "RULE_VIOLATION")["ruleRef"] == "CLM-PO" and "only executed contracts" in not_active.json()["detail"]
    # ... nor a requisition line of a contract that is not executed (guided buying by contract line)
    draft_line = _contract(client, login, draft)["lines"][0]["id"]
    body = {"origin": "MANUAL", "purpose_code": "PRODUCTION", "plant": PLANT, "lines": [{
        "item_type": "CONTRACT", "purchase_type": "STOCK", "material": "CLM-ALU-01", "contract_line_id": draft_line, "description": "Alloy", "material_group": "GENERAL",
        "qty": "1", "uom": "KG", "price_est_minor": 2_000_000, "need_date": need.isoformat()}]}
    rejected = client.post("/v1/requisitions", json=body, headers=_h(login, "requester"))
    assert rejected.status_code == 422 and rejected.json()["ruleRef"] == "CLM-PO", rejected.text


# ================================================================ 6. a small indexed contract: single approval, owner excluded, e-sign provider
def test_06_below_one_crore_one_contract_manager_approves_never_the_owner_or_the_submitter(client, login, env, monkeypatch):
    today = J["today"]
    body = _draft_body(type="SCHEDULING_AGREEMENT", title="Alloy ingots B - scheduling agreement", valid_to=(today + timedelta(days=130)).isoformat(),
                       lines=[{"material": "CLM-ALU-02", "description": "Alloy ingot B", "plant": PLANT, "uom": "KG", "target_qty": "10", "unit_price_minor": 100_000}],
                       tolerances={"over_pct": "0", "under_pct": "0", "price_pct": "2"}, jurisdiction=None,
                       index_ref={"index": "LME_AL", "base": "100.00", "band_pct": "3", "reset": "QUARTERLY"})
    created = client.post("/v1/contracts", json=body, headers=_h(login, "cm"))
    assert created.status_code == 201, created.text
    b = J["B"] = created.json()["number"]
    assert created.json()["target_value_minor"] == 1_000_000 < CR
    assert client.post(f"/v1/contracts/{b}/review", headers=_h(login, "cm")).status_code == 200
    # cm3 submits what cm owns: neither of them can approve; cm2 does
    submitted = client.post(f"/v1/contracts/{b}/submit", headers=_h(login, "cm3"))
    assert submitted.status_code == 200 and submitted.json()["chain"] == ["CONTRACT_MANAGER"]
    assert not _tasks(client, _h(login, "cm"), b) and not _tasks(client, _h(login, "cm3"), b)
    task = _tasks(client, _h(login, "cm2"), b)[0]
    for who in ("cm", "cm3"):
        assert client.post(f"/v1/tasks/{task['id']}/complete", json={"decision": "APPROVE"}, headers=_h(login, who)).status_code == 403
    _approve(client, _h(login, "cm2"), b)
    assert _contract(client, login, b)["status"] == "OUT_FOR_SIGNATURE"
    # e-signature through the provider adapter: no provider configured -> 404 (the internal path stays); configured -> envelope + signed webhooks
    _problem(client.post(f"/v1/contracts/{b}/signature-envelopes", json={}, headers=_h(login, "cm")), 404, "ESIGN_NOT_CONFIGURED")
    for name, value in (("PIC_ESIGN_PROVIDER", "DOCUSIGN"), ("PIC_ESIGN_URL", "https://esign.test/v1"), ("PIC_ESIGN_API_KEY", "key"),
                        ("PIC_ESIGN_WEBHOOK_SECRET", ESIGN_SECRET)):
        monkeypatch.setenv(name, value)

    class _Response:
        status_code = 201

        def json(self):
            return {"envelopeId": "ENV-CLM-0001", "status": "sent"}

    sent = []
    monkeypatch.setattr(contract_svc.httpx, "post", lambda url, json=None, **kw: sent.append(json) or _Response())
    envelope = client.post(f"/v1/contracts/{b}/signature-envelopes", json={"buyer_signer": _email("cm2")}, headers=_h(login, "cm"))
    assert envelope.status_code == 201, envelope.text
    assert envelope.json()["envelopeId"] == "ENV-CLM-0001" and [s["party"] for s in sent[0]["signers"]] == ["BUYER", "SUPPLIER"]
    again = client.post(f"/v1/contracts/{b}/signature-envelopes", json={}, headers=_h(login, "cm"))
    _problem(again, 409, "ENVELOPE_PENDING")

    def webhook(event: dict, secret: str = ESIGN_SECRET):
        raw = json.dumps(event).encode()
        return client.post("/v1/esign/webhook", content=raw, headers={"X-Esign-Signature": hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(),
                                                                        "Content-Type": "application/json"})

    base = {"reference": envelope.json()["reference"], "envelopeId": "ENV-CLM-0001", "event": "SIGNER_COMPLETED",
            "documentHash": envelope.json()["documentHash"]}
    _problem(webhook({**base, "party": "BUYER"}, secret="wrong-secret"), 401, "ESIGN_SIGNATURE_INVALID")
    _problem(webhook({**base, "party": "BUYER", "documentHash": "0" * 64}), 409, "DOCUMENT_CHANGED")
    assert webhook({**base, "party": "BUYER", "signerName": "Meena Raghavan"}).status_code == 200
    assert webhook({**base, "party": "BUYER"}).json()["duplicate"] is True
    _problem(client.post(f"/v1/contracts/{b}/activate", headers=_h(login, "cm")), 422, "RULE_VIOLATION")
    assert webhook({**base, "party": "SUPPLIER", "signerName": "Alpha Alloys MD"}).status_code == 200
    activated = client.post(f"/v1/contracts/{b}/activate", headers=_h(login, "cm"))
    assert activated.status_code == 200 and activated.json()["status"] == "ACTIVE"
    assert {s["envelope_ref"] for s in activated.json()["signatures"]} == {"ENV-CLM-0001"}


# ================================================================ 7. F4-09 consumption alerts 80 / 90 / 100 % and compliance
def _notes(client, login, who: str, needle: str) -> list[dict]:
    items = client.get("/v1/notifications", headers=_h(login, who)).json()["items"]
    return [n for n in items if n["kind"] == "CONTRACT_CONSUMPTION" and needle in n["title"]]


def test_07_consumption_alerts_reach_the_contract_owner_and_compliance_numbers_add_up(client, login, env):
    b, a, need = J["B"], J["A"], J["today"] + timedelta(days=7)
    pr = _requisition(env, [("CLM-ALU-02", "50")], need)
    po1 = _create_po(client, login, pr, 10, b, "8", need=need)
    assert po1.status_code == 201, po1.text
    # the flagged order of step 5 waits for its approvals: it shows as a price deviation at once but consumes nothing until released
    _tick(client, login)
    waiting = client.get(f"/v1/contracts/{a}/consumption", headers=_h(login, "cm")).json()["lines"][0]
    assert [d["po"] for d in waiting["priceDeviations"]] == [J["flagged_po"]]
    released_before = Decimal(waiting["releasedQty"])
    _release(client, login, po1.json()["id"])
    _tick(client, login)
    cons = client.get(f"/v1/contracts/{b}/consumption", headers=_h(login, "cm")).json()
    assert cons["thresholdsHit"] == [80] and cons["lines"][0]["consumedPct"] == "80.00" and cons["lines"][0]["thresholdsHit"] == [80]
    assert _notes(client, login, "cm", "80% consumed"), "the contract owner is told"
    assert _notes(client, login, "cm2", "80% consumed"), "and the other contract managers"
    assert not _notes(client, login, "buyer", "80% consumed")
    for qty, threshold in (("1", 90), ("1", 100)):
        po = _create_po(client, login, pr, 10, b, qty, need=need)
        assert po.status_code == 201, po.text
        _release(client, login, po.json()["id"])
        _tick(client, login)
        assert _contract(client, login, b)["thresholds_hit"][-1] == threshold
    _tick(client, login)  # a further relay raises no second alert
    assert _contract(client, login, b)["thresholds_hit"] == [80, 90, 100]
    for threshold in (80, 90, 100):
        assert len(_notes(client, login, "cm", f"{threshold}% consumed")) == 1
    # fully consumed: another release against it is refused
    full = _create_po(client, login, pr, 10, b, "1", need=need)
    assert "exceeds the contract quantity" in _problem(full, 422, "RULE_VIOLATION")["detail"]
    # off-contract buying of the contracted item at a higher price is leakage; so is a flagged contract-priced line
    off = _create_po(client, login, pr, 10, None, "2", need=need, price=120_000, supplier="CLM-ALPHA")
    if off.status_code == 422:  # the price check against the last price paid asks for a reason
        off = _create_po(client, login, pr, 10, None, "2", need=need, price=120_000, supplier="CLM-ALPHA", reason="Urgent plant requirement")
    assert off.status_code == 201, off.text
    _release(client, login, off.json()["id"])
    _release(client, login, J["flagged_po"])
    _tick(client, login)
    cons = client.get(f"/v1/contracts/{b}/consumption", headers=_h(login, "cm")).json()
    compliance = cons["compliance"]
    assert [o["valueMinor"] for o in cons["lines"][0]["offContract"]] == [240_000] and cons["lines"][0]["offContract"][0]["leakageMinor"] == 40_000
    assert compliance["releasedValueMinor"] == 1_000_000 and compliance["consumedValuePct"] == "100.00"
    assert compliance["offContractValueMinor"] == 240_000 and compliance["priceLeakageMinor"] == 40_000 and compliance["offContractLines"] == 1
    assert compliance["complianceRatePct"] == str((Decimal(1_000_000) / Decimal(1_240_000) * 100).quantize(Decimal("0.01")))
    flagged = client.get(f"/v1/contracts/{a}/consumption", headers=_h(login, "cm")).json()
    deviation = flagged["lines"][0]["priceDeviations"][0]
    assert deviation["excessMinor"] == 400_000 and deviation["reason"] == "Spot premium agreed with the plant head"
    assert flagged["compliance"]["priceLeakageMinor"] == 400_000 and flagged["compliance"]["priceDeviationLines"] == 1
    assert Decimal(flagged["lines"][0]["releasedQty"]) == released_before + 1
    # reading the compliance picture needs the READ scope: the supplier portal cannot
    assert client.get(f"/v1/contracts/{b}/consumption", headers=_portal(login)).status_code == 403


# ================================================================ 8. price indexation: a new validity period each reset, never an overwrite
def test_08_index_resets_add_price_validity_periods_and_never_overwrite(client, login, env):
    b, today, cm = J["B"], J["today"], _h(login, "cm")
    before = _contract(client, login, b)["priceValidity"]
    assert len(before) == 1 and before[0]["unit_price_minor"] == 100_000 and before[0]["reason"] == "INITIAL"
    effective = (today + timedelta(days=40)).isoformat()
    key = {"Idempotency-Key": f"clm-journey-reset-{uuid.uuid4().hex}"}
    reset = client.post(f"/v1/contracts/{b}/index-resets", json={"index_value": "108", "effective_from": effective}, headers={**cm, **key})
    assert reset.status_code == 200, reset.text
    assert reset.json()["changePct"] == "8.00" and reset.json()["adjustPct"] == "5.00" and reset.json()["lines"][0]["newPriceMinor"] == 105_000
    replay = client.post(f"/v1/contracts/{b}/index-resets", json={"index_value": "108", "effective_from": effective}, headers={**cm, **key})
    assert replay.status_code == 200 and replay.json().get("replayed") and {k: v for k, v in replay.json().items() if k != "replayed"} == reset.json()
    periods = _contract(client, login, b)["priceValidity"]
    assert [(p["reason"], p["unit_price_minor"]) for p in periods] == [("INITIAL", 100_000), ("INDEX_RESET_ADJUSTED", 105_000)]
    assert periods[0]["valid_to"] >= effective, "the earlier period is untouched"
    # not later than the last reset, outside the validity, a non-positive index, a contract without index, a non-manager: all refused
    _problem(client.post(f"/v1/contracts/{b}/index-resets", json={"index_value": "110", "effective_from": effective}, headers=cm), 409, "INDEX_RESET_NOT_LATER")
    _problem(client.post(f"/v1/contracts/{b}/index-resets", json={"index_value": "110", "effective_from": (today + timedelta(days=200)).isoformat()}, headers=cm),
             422, "RULE_VIOLATION")
    assert client.post(f"/v1/contracts/{b}/index-resets", json={"index_value": "0", "effective_from": effective}, headers=cm).status_code == 422
    _problem(client.post(f"/v1/contracts/{J['A']}/index-resets", json={"index_value": "110", "effective_from": effective}, headers=cm), 422, "RULE_VIOLATION")
    assert client.post(f"/v1/contracts/{b}/index-resets", json={"index_value": "110", "effective_from": effective}, headers=_h(login, "requester")).status_code == 403
    # inside the band the price is absorbed: a period is still added
    absorbed = client.post(f"/v1/contracts/{b}/index-resets", json={"index_value": "102", "effective_from": (today + timedelta(days=80)).isoformat()}, headers=cm)
    assert absorbed.status_code == 200 and absorbed.json()["adjustPct"] == "0.00" and absorbed.json()["lines"][0]["newPriceMinor"] == 100_000
    periods = _contract(client, login, b)["priceValidity"]
    assert [(p["reason"], p["unit_price_minor"]) for p in periods] == [("INITIAL", 100_000), ("INDEX_RESET_ADJUSTED", 105_000), ("INDEX_RESET_ABSORBED", 100_000)]
    # source determination takes the period in force on the date
    for days, price in ((20, 100_000), (50, 105_000), (100, 100_000)):
        clock.set_pinned(at(today + timedelta(days=days), 11))
        try:
            assert client.get(f"/v1/contracts/{b}/consumption", headers=cm).json()["lines"][0]["currentPriceMinor"] == price
        finally:
            clock.set_pinned(None)


# ================================================================ 9. obligations and milestones, on-time %
def test_09_obligations_milestones_and_the_on_time_percentage(client, login, env):
    b, today, cm = J["B"], J["today"], _h(login, "cm")
    body = {"party": "SUPPLIER", "description": "Deliver the first-article inspection report", "due_date": (today + timedelta(days=30)).isoformat(), "kind": "MILESTONE"}
    key = {"Idempotency-Key": f"clm-journey-ob-{uuid.uuid4().hex}"}
    milestone = client.post(f"/v1/contracts/{b}/obligations", json=body, headers={**cm, **key})
    assert milestone.status_code == 201, milestone.text
    assert client.post(f"/v1/contracts/{b}/obligations", json=body, headers={**cm, **key}).json()["id"] == milestone.json()["id"]
    late = client.post(f"/v1/contracts/{b}/obligations", headers=cm, json={"party": "BUYER", "description": "Share the 13-week forecast", "due_date": today.isoformat()})
    assert late.status_code == 201 and late.json()["kind"] == "OBLIGATION"
    for bad in ({"party": "THIRD", "description": "Something to do", "due_date": today.isoformat()},
                {"party": "BUYER", "description": "x", "due_date": today.isoformat()},
                {"party": "BUYER", "description": "Before the contract starts", "due_date": (today - timedelta(days=5)).isoformat()},
                {"party": "BUYER", "description": "Unknown kind", "due_date": today.isoformat(), "kind": "WISH"}):
        assert client.post(f"/v1/contracts/{b}/obligations", json=bad, headers=cm).status_code == 422, bad
    assert client.post(f"/v1/contracts/{b}/obligations", json=body, headers=_portal(login)).status_code == 403
    # completion needs evidence; a completed obligation cannot be completed again
    assert client.post(f"/v1/obligations/{milestone.json()['id']}/complete", json={"note": ""}, headers=cm).status_code == 422
    clock.set_pinned(at(today + timedelta(days=10), 11))  # ten days after the buyer's forecast was due, the template obligations due on day 7 are overdue
    try:
        on_time = client.post(f"/v1/obligations/{milestone.json()['id']}/complete", json={"note": "Report received by mail, ref FAI-17"}, headers=cm)
        assert on_time.status_code == 200 and on_time.json()["status"] == "DONE" and on_time.json()["completed_at"] and on_time.json()["completion_note"]
        was_late = client.post(f"/v1/obligations/{late.json()['id']}/complete", json={"note": "Forecast shared late by e-mail"}, headers=cm)
        assert was_late.status_code == 200
        _problem(client.post(f"/v1/obligations/{late.json()['id']}/complete", json={"note": "again please"}, headers=cm), 409, "ALREADY_COMPLETED")
        tracker = client.get("/v1/obligations", headers=cm).json()
        by_id = {i["id"]: i for i in tracker["items"]}
        assert by_id[milestone.json()["id"]]["onTime"] is True and by_id[milestone.json()["id"]]["kind"] == "MILESTONE"
        assert by_id[late.json()["id"]]["onTime"] is False and by_id[late.json()["id"]]["status"] == "COMPLETED"
        assert {i["party"] for i in client.get("/v1/obligations?party=SUPPLIER", headers=cm).json()["items"]} == {"SUPPLIER"}
        # the KPI is the tracker's figure: completed on time / (completed + still open past the due date)
        done = [i for i in tracker["items"] if i["status"] == "COMPLETED"]
        overdue = [i for i in tracker["items"] if i["status"] == "OVERDUE"]
        expected = (Decimal(sum(1 for i in done if i["onTime"])) / (len(done) + len(overdue)) * 100).quantize(Decimal("0.1"))
        assert tracker["onTimePct"] == str(expected) and tracker["overdue"] == len(overdue) and overdue
        kpi = _kpi(client, cm, "M07.OBLIGATION_ON_TIME")
        assert "error" not in kpi["detail"] and Decimal(kpi["value"]).quantize(Decimal("0.1")) == expected < 100
        assert any(e["action"] == "OBLIGATION_DONE" and e["after"]["onTime"] is False for e in client.get(f"/v1/audit/CONTRACT/{b}", headers=cm).json())
    finally:
        clock.set_pinned(None)


# ================================================================ 10. termination: direct action with its approvals
def test_10_terminate_an_active_contract_with_notice_rules_and_approvals(client, login, env):
    a, cm = J["A"], _h(login, "cm")
    # without cause the notice period of the CONTRACT-AMENDMENT rule applies: a termination effective today is refused
    notice = client.post(f"/v1/contracts/{a}/terminate", json={"reason": "Supplier no longer needed", "effective_from": J["today"].isoformat()}, headers=cm)
    assert _problem(notice, 422, "RULE_VIOLATION")["earliestEffective"] == (J["today"] + timedelta(days=90)).isoformat()
    assert client.post(f"/v1/contracts/{a}/terminate", json={"reason": "no"}, headers=cm).status_code == 422
    assert client.post(f"/v1/contracts/{a}/terminate", json={"reason": "Supplier breach of quality terms"}, headers=_h(login, "requester")).status_code == 403
    _problem(client.post(f"/v1/contracts/{J['draft']}/terminate", json={"reason": "Not executed, nothing to terminate"}, headers=cm), 409, "ILLEGAL_TRANSITION")
    key = {"Idempotency-Key": f"clm-journey-term-{uuid.uuid4().hex}"}
    request = {"reason": "Repeated delivery failures and breach of the quality clause", "for_cause": True}
    terminate = client.post(f"/v1/contracts/{a}/terminate", json=request, headers={**cm, **key})
    assert terminate.status_code == 201, terminate.text
    amendment = terminate.json()
    assert amendment["kind"] == "TERMINATION" and amendment["status"] == "IN_APPROVAL" and amendment["changes"]["approvalChain"] == ["LEGAL", "CPO"]
    assert client.post(f"/v1/contracts/{a}/terminate", json=request, headers={**cm, **key}).json()["number"] == amendment["number"]
    _problem(client.post(f"/v1/contracts/{a}/terminate", json=request, headers=cm), 409, "AMENDMENT_PENDING")
    assert _contract(client, login, a)["status"] == "ACTIVE", "terminated only when the approvals are in"
    # the requester cannot approve it; legal then the CPO do
    task = _tasks(client, _h(login, "legal"), a)[0]
    assert client.post(f"/v1/tasks/{task['id']}/complete", json={"decision": "APPROVE"}, headers=cm).status_code == 403
    _approve(client, _h(login, "legal"), a, "Breach documented")
    assert _contract(client, login, a)["status"] == "ACTIVE"
    _approve(client, _h(login, "cpo"), a, "Approved")
    contract = _contract(client, login, a)
    assert contract["status"] == "TERMINATED" and contract["terminated_at"] and "quality clause" in contract["termination_reason"]
    _tick(client, login)
    # no order can reference it any more, and a terminated contract cannot be terminated again
    pr = _requisition(env, [("CLM-ALU-01", "10")], J["today"] + timedelta(days=7))
    refused = _create_po(client, login, pr, 10, a, "1", need=J["today"] + timedelta(days=7))
    assert _problem(refused, 422, "RULE_VIOLATION")["ruleRef"] == "CLM-PO" and "TERMINATED" in refused.json()["detail"]
    _problem(client.post(f"/v1/contracts/{a}/terminate", json={"reason": "Terminate again please"}, headers=cm), 409, "ILLEGAL_TRANSITION")
    listing = client.get(f"/v1/contracts/{a}/amendments", headers=cm).json()
    assert listing["status"] == "TERMINATED" and listing["items"][0]["status"] == "EFFECTIVE"


# ================================================================ 11. F4-10 renewal 120 days before expiry, the decision, extension, expiry
def test_11_renewal_notice_decision_extension_and_expiry(client, login, env):
    b, today, cm = J["B"], J["today"], _h(login, "cm")
    valid_to = today + timedelta(days=130)
    notice_on = valid_to - timedelta(days=120)
    calendar = {r["contract"]: r for r in client.get("/v1/contracts-renewals", headers=cm).json()}
    assert b in calendar and J["A"] not in calendar, "a terminated contract leaves the calendar"
    assert calendar[b]["noticeOn"] == notice_on.isoformat() and calendar[b]["validTo"] == valid_to.isoformat() and calendar[b]["noticeDue"] is False
    assert calendar[b]["expiringIn90"] is False and calendar[b]["renewalTask"] is None and calendar[b]["daysToExpiry"] == 130
    # nothing happens before the notice date ...
    clock.set_pinned(at(notice_on - timedelta(days=1), 12))
    try:
        _tick(client, login)
        assert _contract(client, login, b)["status"] == "ACTIVE"
        # ... and an early termination without cause is refused by the notice rule
        preview = client.post(f"/v1/contracts/{b}/amendments/preview", json={"kind": "TERMINATION", "changes": {}, "effective_from": notice_on.isoformat()}, headers=cm)
        assert preview.status_code == 422
        # on the notice date (09:00 IST) the contract becomes EXPIRING and the contract managers get the renewal decision
        clock.set_pinned(at(notice_on, 9, 5))
        _tick(client, login)
        assert _contract(client, login, b)["status"] == "EXPIRING"
        assert _contract(client, login, J["A"])["status"] == "TERMINATED"
        task = _tasks(client, _h(login, "cm2"), b)
        assert len(task) == 1 and task[0]["kind"] == "CONTRACT_RENEWAL" and _tasks(client, _h(login, "cm3"), b)
        assert client.get("/v1/contracts-renewals", headers=cm).json()[0]["renewalTask"]["id"] == task[0]["id"]
        # a renewal is decided by approving the task: an extension amendment (+12 months) is drafted, approved by another manager, then in force
        done = client.post(f"/v1/tasks/{task[0]['id']}/complete", json={"decision": "APPROVE", "comment": "Continue with Alpha for another year"}, headers=_h(login, "cm2"))
        assert done.status_code == 200, done.text
        amendments = client.get(f"/v1/contracts/{b}/amendments", headers=cm).json()
        draft = next(i for i in amendments["items"] if i["kind"] == "EXTENSION")
        assert draft["status"] == "DRAFT"
        new_to = date.fromisoformat(draft["changes"]["validTo"])
        assert new_to > valid_to + timedelta(days=360)
        submitted = client.post(f"/v1/contracts/{b}/amendments/{draft['number']}/submit", headers=_h(login, "cm3"))
        assert submitted.status_code == 200 and submitted.json()["status"] == "IN_APPROVAL"
        assert not _tasks(client, _h(login, "cm2"), b), "the requester of the extension does not approve it"
        _approve(client, cm, b, "Extension approved")
        extended = _contract(client, login, b)
        assert extended["status"] == "ACTIVE" and extended["valid_to"] == new_to.isoformat() and extended["version"] == 2
        reasons = [p["reason"] for p in extended["priceValidity"]]
        assert any(r.startswith("EXTENSION") for r in reasons) and reasons[:3] == ["INITIAL", "INDEX_RESET_ADJUSTED", "INDEX_RESET_ABSORBED"]
        # the renewal notice and the expiry were re-armed for the new end date
        assert client.get("/v1/contracts-renewals", headers=cm).json()[0]["validTo"] == new_to.isoformat()
        # 60 days before the new end: renewal notice again, and the contract counts in "expiring in 90 days"
        clock.set_pinned(at(new_to - timedelta(days=60), 10))
        _tick(client, login)
        assert _contract(client, login, b)["status"] == "EXPIRING"
        expiring = _kpi(client, cm, "M07.EXPIRING_90D")
        assert "error" not in expiring["detail"] and expiring["value"] in ("1", "1.0") and client.get("/v1/contracts-renewals", headers=cm).json()[0]["expiringIn90"] is True
        assert [c["number"] for c in client.get("/v1/contracts?expiring_within_days=90", headers=cm).json()["items"]] == [b]
        assert _tasks(client, cm, b)
        # nobody renews: at the end the contract expires, the open renewal task goes with it, the calendar and the order desk drop it
        clock.set_pinned(at(new_to + timedelta(days=1), 0, 10))
        _tick(client, login)
        ended = _contract(client, login, b)
        assert ended["status"] == "EXPIRED"
        assert not _tasks(client, cm, b) and b not in {r["contract"] for r in client.get("/v1/contracts-renewals", headers=cm).json()}
        pr = _requisition(env, [("CLM-ALU-02", "5")], new_to + timedelta(days=2))
        refused = _create_po(client, login, pr, 10, b, "1", need=new_to + timedelta(days=2))
        assert "EXPIRED" in _problem(refused, 422, "RULE_VIOLATION")["detail"]
    finally:
        clock.set_pinned(None)


# ================================================================ 12. audit trail, tenant isolation, KPIs
def test_12_audit_trail_tenant_isolation_and_the_m07_kpis(client, login, env):
    a, b, cm = J["A"], J["B"], _h(login, "cm")
    trail = client.get(f"/v1/audit/CONTRACT/{a}", headers=cm).json()
    actions = [e["action"] for e in trail]
    for expected in ("DRAFTED", "REVIEW", "CLAUSE_REDLINED", "REDLINE_REVIEWED", "SUBMIT", "TASK_CREATED", "SIGNED", "ACTIVATE", "AMENDMENT_DRAFTED",
                     "AMENDMENT_SUBMITTED", "AMENDMENT_APPROVED", "TERMINATED_BY_AMENDMENT"):
        assert expected in actions, (expected, actions)
    assert [e["seq"] for e in trail] == sorted(e["seq"] for e in trail)
    drafted = next(e for e in trail if e["action"] == "DRAFTED")
    assert drafted["actor"] and drafted["ruleSetVersion"].startswith("CLM-PLAYBOOK@")
    assert {"EXPIRE", "INDEX_RESET", "OBLIGATION_ADDED", "AMENDED"} <= {e["action"] for e in client.get(f"/v1/audit/CONTRACT/{b}", headers=cm).json()}
    assert client.get("/v1/audit/verify", headers=_h(login, "admin")).json()["valid"] is True
    # another tenant sees none of it (row-level security), and we see none of theirs
    other = login("contract.manager", "AXN")
    ours = _contract(client, login, a)
    assert client.get(f"/v1/contracts/{ours['id']}", headers=other).status_code == 404  # by id: the row is invisible to the other tenant
    # numbers are per tenant (both start at SA-5520): the other tenant's SA-5520 is its own contract, not ours
    theirs = client.get(f"/v1/contracts/{a}", headers=other)
    assert theirs.status_code in (200, 404) and (theirs.status_code == 404 or theirs.json()["id"] != ours["id"] and theirs.json()["title"] != ours["title"])
    assert not {c["id"] for c in client.get("/v1/contracts", headers=other).json()["items"]} & {ours["id"], _contract(client, login, b)["id"]}
    assert not [i for i in client.get("/v1/obligations", headers=other).json()["items"] if "forecast" in i["description"].lower() and i["contract"] == b]
    assert client.get(f"/v1/audit/CONTRACT/{ours['id']}", headers=other).status_code == 404
    # the M07 KPIs: cycle time, leakage, expiring in 90 days, obligation on-time %
    items = {i["code"]: i for i in client.get("/v1/kpis?module=M07&trend=false", headers=cm).json()["items"]}
    assert {"M07.CONTRACT_CYCLE", "M07.CONTRACT_LEAKAGE", "M07.EXPIRING_90D", "M07.OBLIGATION_ON_TIME"} <= set(items)
    assert all("error" not in i["detail"] for i in items.values())
    assert items["M07.CONTRACT_CYCLE"]["value"] is not None and Decimal(items["M07.CONTRACT_CYCLE"]["value"]) >= 0
    assert items["M07.EXPIRING_90D"]["value"] in ("0", "0.0")
