"""MDM-04 supplier master changes, F8-01 invitations and self-registration, M04 punch-out, M01 category budget."""
import hashlib
import html
import re
import uuid
from datetime import date

import pytest
from sqlalchemy import select, text

from app.pic.db import system_tx, tenant_tx
from app.pic.services import master_changes, punchout

AXN_PASSWORD = "Kaveri-River-Delta-2026!"


def _tenant_id() -> uuid.UUID:
    from app.pic.models import Tenant
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()


def _sql(statement: str, **params):
    with tenant_tx(_tenant_id()) as s:
        result = s.execute(text(statement), params)
        return result.mappings().all() if result.returns_rows else None


def gstin(state: str, pan: str, entity: str = "1") -> str:
    base = f"{state}{pan}{entity}Z"
    return base + master_changes.gstin_check_char(base)


def _task(client, login, who: str, ref: str):
    return next((t for t in client.get("/v1/tasks", headers=login(who)).json() if t["object_ref"] == ref), None)


def _decide(client, login, who: str, ref: str, decision: str = "APPROVE", comment: str = None):
    task = _task(client, login, who, ref)
    assert task, f"{who} has no task for {ref}"
    return client.post(f"/v1/tasks/{task['id']}/complete", json={"decision": decision, "comment": comment}, headers=login(who))


def _changes(client, login, who: str, code: str) -> dict:
    return {c["number"]: c for c in client.get(f"/v1/suppliers/{code}/master-changes", headers=login(who)).json()}


# ---------------------------------------------------------------- validation
def test_gstin_pan_and_address_validation():
    valid = gstin("33", "AAACN4821Q")
    assert master_changes.gstin_errors(valid, pan="AAACN4821Q", state_code="33") == []
    assert master_changes.gstin_errors("27AAPFU0939F1ZV") == []                       # published sample GSTIN
    assert any("check character" in e for e in master_changes.gstin_errors(valid[:14] + ("A" if valid[14] != "A" else "B")))
    assert any("15 characters" in e for e in master_changes.gstin_errors("33AAACN4821Q1Z"))
    assert any("PAN must match" in e for e in master_changes.gstin_errors(valid, pan="AAACN4821R"))
    assert any("does not match the address state" in e for e in master_changes.gstin_errors(valid, state_code="29"))
    assert any("not a valid GST state" in e for e in master_changes.gstin_errors(gstin("45", "AAACN4821Q")))
    assert master_changes.pan_errors("AAACN4821Q") == [] and master_changes.pan_errors("AAAC4821Q1")
    assert master_changes.address_errors({"line1": "1 Mill Rd", "city": "Coimbatore", "state_code": "33", "pin": "641001"}) == []
    assert any("PIN" in e for e in master_changes.address_errors({"line1": "x", "city": "y", "state_code": "33", "pin": "64100"}))


def test_master_change_api_rejects_invalid_tax_ids(client, login):
    headers = login("supplier.manager")
    bad = client.post("/v1/suppliers/SLA003/master-changes", headers=headers, json={
        "fieldGroup": "TAX", "values": {"gstin": "33AABCS9012M1Z0", "pan": "AABCS9012M"}, "reason": "GST amendment"})
    assert bad.status_code == 422 and bad.json()["code"] == "VALIDATION_FAILED"
    assert any("check character" in e for e in bad.json()["errors"])
    wrong_state = client.post("/v1/suppliers/SLA003/master-changes", headers=headers, json={
        "fieldGroup": "ADDRESS", "values": {"line1": "Plot 4, SIPCOT", "city": "Bengaluru", "state_code": "29", "pin": "560001"},
        "reason": "Moved"})
    assert wrong_state.status_code == 422 and "GSTIN state" in wrong_state.json()["detail"]


# ---------------------------------------------------------------- dual approval, supplier-user scope, apply, ERP
def test_contact_change_by_supplier_user_dual_approval_and_erp_sync(client, login):
    portal = login("hts.service")
    # A supplier user acts only for their own company.
    other = client.post("/v1/suppliers/KD002/master-changes", headers=portal, json={
        "fieldGroup": "CONTACT", "values": {"email": "x@kd002.example"}, "reason": "not mine"})
    assert other.status_code == 403 and other.json()["ruleRef"] == "SUPPLIER_SCOPE"
    assert client.get("/v1/suppliers/KD002/master-changes", headers=portal).status_code == 403

    r = client.post("/v1/suppliers/HTS004/master-changes", headers=portal, json={
        "fieldGroup": "CONTACT", "values": {"email": "Accounts@HTS004.example", "phone": "+91 98400 12345"},
        "reason": "Accounts desk now handles purchase orders"})
    assert r.status_code == 201, r.text
    change = r.json()
    number = change["number"]
    assert number.startswith("SMC-") and change["status"] == "IN_APPROVAL" and change["field_group"] == "CONTACT"
    assert change["after_masked"]["email"] == "a•••@hts004.example" and change["after_masked"]["phone"].endswith("2345")
    assert "accounts@hts004.example" not in r.text and "after_enc" not in change
    assert {t["role"] for t in change["tasks"]} == {"FINANCE_CONTROLLER", "SUPPLIER_MANAGER"}   # parallel tasks
    stored = _sql("SELECT after_enc FROM pic.supplier_master_change WHERE number = :n", n=number)[0]["after_enc"]
    assert "accounts@hts004.example" not in stored                                             # field-encrypted

    # Pending in-approval change for the same field group is refused.
    again = client.post("/v1/suppliers/HTS004/master-changes", headers=portal, json={
        "fieldGroup": "CONTACT", "values": {"email": "other@hts004.example"}, "reason": "again"})
    assert again.status_code == 409 and again.json()["code"] == "CHANGE_PENDING"

    assert _decide(client, login, "finance.controller", number).status_code == 200
    assert _changes(client, login, "supplier.manager", "HTS004")[number]["status"] == "IN_APPROVAL"   # both are required
    assert _decide(client, login, "supplier.manager", number).status_code == 200
    applied = _changes(client, login, "hts.service", "HTS004")[number]
    assert applied["status"] == "APPLIED" and applied["applied_at"] and len(applied["approvals"]) == 2

    sup = client.get("/v1/suppliers/HTS004", headers=login("supplier.manager")).json()
    assert sup["contact_email"] == "accounts@hts004.example" and sup["address"]["phone"] == "+91 98400 12345"
    message = _sql("SELECT message_type, payload FROM pic.integration_message WHERE idempotency_key = :k",
                   k=f"HTS004|CONTACT|{number}")
    assert message and message[0]["message_type"] == "SUPPLIER_MASTER"
    assert "accounts@hts004.example" not in str(message[0]["payload"])
    event = _sql("SELECT payload FROM pic.outbox_event WHERE topic = 'supplier.master.changed' AND object_ref = 'HTS004'")
    assert event and event[-1]["payload"]["change"] == number
    audit_rows = _sql("SELECT action, after::text AS after FROM pic.audit_event WHERE object_ref = 'HTS004' "
                      "AND action LIKE 'MASTER_CHANGE%' ORDER BY seq")
    assert [a["action"] for a in audit_rows][-2:] == ["MASTER_CHANGE_REQUESTED", "MASTER_CHANGE_APPLIED"]
    assert all("accounts@hts004.example" not in a["after"] for a in audit_rows)


def test_requester_cannot_approve_and_rejection_ends_the_change(client, login):
    headers = login("supplier.manager")
    sup = client.get("/v1/suppliers/SLA003", headers=headers).json()
    r = client.post("/v1/suppliers/SLA003/master-changes", headers=headers, json={
        "fieldGroup": "ADDRESS", "values": {"line1": "SF 112, Omalur Main Road", "city": "Salem", "state_code": "33", "pin": "636009"},
        "reason": "Registered office moved within Salem"})
    assert r.status_code == 201, r.text
    number = r.json()["number"]
    # Four-eyes: the requester's own SUPPLIER_MANAGER task is not theirs to complete.
    assert _task(client, login, "supplier.manager", number) is None
    task_id = next(t["id"] for t in r.json()["tasks"] if t["role"] == "SUPPLIER_MANAGER")
    blocked = client.post(f"/v1/tasks/{task_id}/complete", json={"decision": "APPROVE"}, headers=headers)
    assert blocked.status_code == 403 and blocked.json()["code"] == "NOT_YOUR_TASK"
    # Defence in depth: even without the exclusion list, the SoD guard refuses the requester.
    _sql("UPDATE pic.task SET excluded_user_ids = '{}' WHERE id = :t", t=task_id)
    guarded = client.post(f"/v1/tasks/{task_id}/complete", json={"decision": "APPROVE"}, headers=headers)
    assert guarded.status_code == 409 and guarded.json()["code"] == "SOD_CONFLICT" and guarded.json()["ruleRef"] == "MDM-04"

    rejected = _decide(client, login, "finance.controller", number, "REJECT", "Rent agreement not attached")
    assert rejected.status_code == 200
    change = _changes(client, login, "supplier.manager", "SLA003")[number]
    assert change["status"] == "REJECTED"
    assert {t["role"]: t["status"] for t in change["tasks"]}["SUPPLIER_MANAGER"] == "CANCELLED"
    assert client.get("/v1/suppliers/SLA003", headers=headers).json()["address"] == sup["address"]


# ---------------------------------------------------------------- invitations and self-registration
def _invite(client, login, email: str, legal_name: str, categories: list[str]) -> dict:
    r = client.post("/v1/supplier-invitations", headers=login("supplier.manager"),
                    json={"email": email, "legalName": legal_name, "categories": categories})
    assert r.status_code == 201, r.text
    return r.json()


def _registration(legal_name: str, pan: str, email: str, password: str = AXN_PASSWORD) -> dict:
    return {"legalName": legal_name, "gstin": gstin("33", pan), "pan": pan, "stateCode": "33",
            "address": {"line1": "14 Avinashi Road", "city": "Coimbatore", "stateCode": "33", "pin": "641018"},
            "contactName": "Meera Natarajan", "email": email, "phone": "+91 422 4567890", "password": password}


@pytest.fixture(scope="module")
def registered(client, login):
    """Two self-registered suppliers (used again by the TAX change test)."""
    out = {}
    for key, name, pan, email in (("a", "Nilgiri Fasteners Private Limited", "AAACN4821Q", "onboarding@nilgiri.example"),
                                  ("b", "Coromandel Gaskets Private Limited", "AAACC7310K", "sales@coromandel.example")):
        invitation = _invite(client, login, email, name, ["FASTENERS"])
        r = client.post(f"/v1/public/invitations/{invitation['token']}/register", json=_registration(name, pan, email))
        assert r.status_code == 201, r.text
        token = client.post("/v1/auth/token", json={"tenant": "AXN", "email": email, "password": AXN_PASSWORD}).json()["access_token"]
        out[key] = {"code": r.json()["supplier"], "headers": {"Authorization": f"Bearer {token}"}, "pan": pan, "email": email}
    return out


def test_invitation_stores_only_the_token_hash(client, login):
    assert client.post("/v1/supplier-invitations", headers=login("requester"),
                       json={"email": "x@y.example", "legalName": "X Ltd", "categories": ["MRO"]}).status_code == 403
    invitation = _invite(client, login, "hello@kaveri-tools.example", "Kaveri Tools LLP", ["mro", "TOOLING-SERVICES"])
    token = invitation["token"]
    assert token.startswith("AXN.") and len(token) > 40
    assert invitation["registrationUrl"].endswith(f"/pic/register?token={token}")
    assert invitation["emailStatus"] in ("SENT", "DISABLED", "FAILED") and invitation["status"] == "SENT"
    assert invitation["categories"] == ["MRO", "TOOLING-SERVICES"] and "token_hash" not in invitation
    rows = _sql("SELECT token_hash FROM pic.supplier_invitation WHERE id = :i", i=invitation["id"])
    assert rows[0]["token_hash"] == hashlib.sha256(token.encode()).hexdigest() != token
    assert not _sql("SELECT 1 FROM pic.audit_event WHERE after::text LIKE :t OR before::text LIKE :t", t=f"%{token.split('.', 1)[1]}%")
    assert not _sql("SELECT 1 FROM pic.idempotency_record WHERE response::text LIKE :t", t=f"%{token.split('.', 1)[1]}%")
    dup = client.post("/v1/supplier-invitations", headers=login("supplier.manager"),
                      json={"email": "hello@kaveri-tools.example", "legalName": "Kaveri Tools LLP", "categories": ["MRO"]})
    assert dup.status_code == 409 and dup.json()["code"] == "INVITATION_PENDING"

    # Public validation needs no session.
    public = client.get(f"/v1/public/invitations/{token}")
    assert public.status_code == 200, public.text
    assert public.json()["legalName"] == "Kaveri Tools LLP" and public.json()["tenant"] == "Axion Mobility Systems Pvt Ltd"
    assert client.get("/v1/public/invitations/AXN.not-a-real-token").status_code == 404
    assert client.get("/v1/public/invitations/NOPE.whatever").status_code == 404

    revoked = client.post(f"/v1/supplier-invitations/{invitation['id']}/revoke", headers=login("supplier.manager"), json={"reason": "duplicate"})
    assert revoked.status_code == 200 and revoked.json()["status"] == "REVOKED"
    gone = client.get(f"/v1/public/invitations/{token}")
    assert gone.status_code == 410 and gone.json()["code"] == "INVITATION_REVOKED"


def test_self_registration_creates_supplier_onboarding_and_login(client, login, registered):
    a = registered["a"]
    sup = client.get(f"/v1/suppliers/{a['code']}", headers=login("supplier.manager")).json()
    assert sup["legal_name"] == "Nilgiri Fasteners Private Limited" and sup["status"] == "REGISTERED"
    assert sup["gstin_masked"].endswith(gstin("33", a["pan"])[-4:]) and sup["address"]["city"] == "Coimbatore"
    assert sup["screening"]["outcome"] in ("CLEAR", "REVIEW")
    assert {c["category"]: c["status"] for c in sup["categories"]} == {"FASTENERS": "UNDER_QUALIFICATION"}
    assert [q["category"] for q in sup["qualifications"]] == ["FASTENERS"]
    path = [p["step"] for p in sup["process"][0]["path"]]
    assert path[:2] == ["F8-01", "F8-02"] and "F8-03" in path and "F8-05" in path
    me = client.get("/v1/me", headers=a["headers"]).json()
    assert me["roles"] == ["SUPPLIER_USER"] and me["supplierId"] == sup["id"]
    user = _sql("SELECT mfa_enrolled, password_hash FROM pic.app_user WHERE email = :e", e=a["email"])[0]
    assert user["mfa_enrolled"] is False and user["password_hash"].startswith("$2") and AXN_PASSWORD not in user["password_hash"]
    invitations = {i["email"]: i for i in client.get("/v1/supplier-invitations", headers=login("supplier.manager")).json()}
    assert invitations[a["email"]]["status"] == "REGISTERED" and invitations[a["email"]]["supplier"] == a["code"]
    audit_actions = [r["action"] for r in _sql("SELECT action FROM pic.audit_event WHERE object_ref = :c ORDER BY seq", c=a["code"])]
    assert "REGISTERED" in audit_actions and "SCREENED" in audit_actions


def test_registration_is_single_use_validated_and_expires(client, login):
    invitation = _invite(client, login, "hello@palani-pack.example", "Palani Packaging Works", ["PACKAGING"])
    token = invitation["token"]
    weak = client.post(f"/v1/public/invitations/{token}/register",
                       json=_registration("Palani Packaging Works", "AAAFP2231H", "hello@palani-pack.example", password="palani123"))
    assert weak.status_code == 422 and weak.json()["code"] == "WEAK_PASSWORD"
    body = _registration("Palani Packaging Works", "AAAFP2231H", "hello@palani-pack.example")
    bad = client.post(f"/v1/public/invitations/{token}/register", json={**body, "gstin": body["gstin"][:14] + "0"
                                                                        if body["gstin"][14] != "0" else body["gstin"][:14] + "1"})
    assert bad.status_code == 422 and bad.json()["code"] == "VALIDATION_FAILED"
    other_email = client.post(f"/v1/public/invitations/{token}/register", json={**body, "email": "someone@else.example"})
    assert other_email.status_code == 422
    ok = client.post(f"/v1/public/invitations/{token}/register", json=body)
    assert ok.status_code == 201, ok.text
    again = client.post(f"/v1/public/invitations/{token}/register", json=body)
    assert again.status_code == 410 and again.json()["code"] == "INVITATION_USED"
    assert client.get(f"/v1/public/invitations/{token}").status_code == 410

    late = _invite(client, login, "hello@vaigai-mro.example", "Vaigai MRO Supplies", ["MRO"])
    _sql("UPDATE pic.supplier_invitation SET expires_at = now() - interval '1 minute' WHERE id = :i", i=late["id"])
    expired = client.get(f"/v1/public/invitations/{late['token']}")
    assert expired.status_code == 410 and expired.json()["code"] == "INVITATION_EXPIRED"
    reg = client.post(f"/v1/public/invitations/{late['token']}/register",
                      json=_registration("Vaigai MRO Supplies", "AAAFV5512C", "hello@vaigai-mro.example"))
    assert reg.status_code == 410
    listed = {i["id"]: i["status"] for i in client.get("/v1/supplier-invitations", headers=login("supplier.manager")).json()}
    assert listed[late["id"]] == "EXPIRED"


def test_tax_change_rescreens_for_duplicate_gstin(client, login, registered):
    a, b = registered["a"], registered["b"]
    r = client.post(f"/v1/suppliers/{b['code']}/master-changes", headers=b["headers"], json={
        "fieldGroup": "TAX", "values": {"gstin": gstin("33", a["pan"]), "pan": a["pan"]}, "reason": "Merged into the parent company GSTIN"})
    assert r.status_code == 201, r.text
    number = r.json()["number"]
    assert r.json()["after_masked"]["gstin"].endswith(gstin("33", a["pan"])[-4:]) and gstin("33", a["pan"]) not in r.text
    evidence = _task(client, login, "finance.controller", number)["evidence"]
    assert evidence["duplicates"] == [{"code": a["code"], "reason": "same GSTIN"}]
    assert _decide(client, login, "finance.controller", number).status_code == 200
    assert _decide(client, login, "supplier.manager", number).status_code == 200
    sup = client.get(f"/v1/suppliers/{b['code']}", headers=login("supplier.manager")).json()
    assert sup["gstin_masked"].endswith(gstin("33", a["pan"])[-4:]) and sup["state_code"] == "33"
    assert sup["screening"]["outcome"] == "REVIEW"
    assert {"code": a["code"], "reason": "same GSTIN"} in sup["screening"]["duplicates"]
    # Not yet created in the ERP (REGISTERED): no ERP update; the create message later carries the current master.
    assert not _sql("SELECT 1 FROM pic.integration_message WHERE idempotency_key = :k", k=f"{b['code']}|TAX|{number}")


# ---------------------------------------------------------------- punch-out
@pytest.fixture(scope="module")
def builtin_cxml(client, login):
    r = client.put("/v1/suppliers/HTS004/punchout", headers=login("supplier.manager"),
                   json={"protocol": "CXML", "url": "builtin", "identity": "HTS004-CAT", "sharedSecret": "hts-shared-secret-1"})
    assert r.status_code == 200, r.text
    return r.json()


def _start(client, login, supplier="HTS004", who="requester") -> dict:
    r = client.post("/v1/punchout/sessions", headers=login(who), json={"supplier": supplier})
    assert r.status_code == 201, r.text
    return r.json()


def _shop(client, session: dict, qty: str = "2") -> str:
    """Use the built-in supplier's catalogue page and return the cXML the browser would post back."""
    page = client.get(session["startUrl"].split("/api/pic", 1)[1])
    assert page.status_code == 200 and "HTS-PM-STD" in page.text
    item_id = re.search(r"name='qty_([0-9a-f-]+)'", page.text).group(1)
    checkout = client.post("/v1/punchout/simulator/checkout", data={"cookie": session["buyer_cookie"], f"qty_{item_id}": qty})
    assert checkout.status_code == 200, checkout.text
    assert 'action="http' in checkout.text and "/api/public/punchout/return" in checkout.text
    return html.unescape(re.search(r'name="cxml-urlencoded" value="([^"]*)"', checkout.text).group(1))


def test_punchout_configuration_keeps_the_secret(client, login, builtin_cxml):
    assert builtin_cxml["protocol"] == "CXML" and builtin_cxml["secretConfigured"] is True
    assert "hts-shared-secret-1" not in str(builtin_cxml)
    assert client.put("/v1/suppliers/HTS004/punchout", headers=login("requester"),
                      json={"protocol": "CXML", "url": "builtin", "identity": "x", "sharedSecret": "12345678"}).status_code == 403
    sup = client.get("/v1/suppliers/HTS004", headers=login("supplier.manager"))
    assert sup.json()["punchout"]["identity"] == "HTS004-CAT" and "hts-shared-secret-1" not in sup.text
    stored = _sql("SELECT punchout_secret_enc FROM pic.supplier WHERE code = 'HTS004'")[0]["punchout_secret_enc"]
    assert stored and "hts-shared-secret-1" not in stored
    codes = [s["code"] for s in client.get("/v1/punchout/suppliers", headers=login("requester")).json()]
    assert "HTS004" in codes


def test_punchout_cxml_end_to_end_with_builtin_supplier(client, login, builtin_cxml):
    session = _start(client, login)
    cookie = session["buyer_cookie"]
    assert cookie.startswith("AXN.") and session["status"] == "OPEN" and session["number"].startswith("PUN-")
    assert "/api/pic/v1/punchout/simulator/catalogue?cookie=" in session["startUrl"] and session["method"] == "GET"
    setup = _sql("SELECT setup_request FROM pic.punchout_session WHERE buyer_cookie = :c", c=cookie)[0]["setup_request"]
    assert "<PunchOutSetupRequest" in setup and "<BuyerCookie>" in setup and "/api/public/punchout/return" in setup
    assert "hts-shared-secret-1" not in setup and "<SharedSecret>********</SharedSecret>" in setup

    cxml = _shop(client, session, qty="2")
    assert "<PunchOutOrderMessage>" in cxml and f"<BuyerCookie>{cookie}</BuyerCookie>" in cxml
    returned = client.post("/v1/punchout/return", data={"cxml-urlencoded": cxml})
    assert returned.status_code == 200, returned.text
    assert returned.json()["status"] == "RETURNED" and returned.json()["items"] == 1
    assert client.post("/v1/punchout/return", data={"cxml-urlencoded": cxml}).json()["code"] == "PUNCHOUT_SESSION_CLOSED"

    assert client.get(f"/v1/punchout/sessions/{cookie}", headers=login("buyer")).status_code == 404   # someone else's session
    cart = client.get(f"/v1/punchout/sessions/{cookie}", headers=login("requester")).json()
    item = cart["cart"][0]
    assert cart["status"] == "RETURNED" and cart["totalMinor"] == 2 * 1_850_000
    assert (item["supplierPartNo"], item["qty"], item["uom"], item["unitPriceMinor"], item["currency"]) == \
        ("HTS-PM-STD", "2", "EA", 1_850_000, "INR")
    assert item["classification"]["MaterialGroup"] == "SVC-TOOLING" and item["description"].startswith("Preventive maintenance")

    converted = client.post(f"/v1/punchout/sessions/{cookie}/convert", headers=login("requester"),
                            json={"purposeCode": "MAINTENANCE", "purposeText": "Die-cell PM via punch-out", "needDate": "2026-12-15"})
    assert converted.status_code == 200, converted.text
    pr = converted.json()
    line = pr["lines"][0]
    hts = client.get("/v1/suppliers/HTS004", headers=login("supplier.manager")).json()
    assert pr["origin"] == "CATALOGUE" and pr["origin_ref"] == session["number"] and pr["status"] == "DRAFT"
    assert line["item_type"] == "CATALOGUE" and line["catalogue_item_id"] and line["preferred_supplier_id"] == hts["id"]
    assert line["source_determination"]["supplierPartNo"] == "HTS-PM-STD" and line["source_determination"]["method"] == "PUNCHOUT"
    assert line["price_est_minor"] == 1_850_000 and line["qty"] == "2" and line["category"] == "TOOLING-SERVICES"
    assert line["purchase_type"] == "SERVICE" and line["account_assignment_code"] == "4100"   # requester's cost centre
    assert any(e["type"] == "PUNCHOUT_CART" for e in pr["lineage"]["edges"])
    assert pr["punchoutSession"]["status"] == "CONVERTED" and pr["punchoutSession"]["requisition"] == pr["number"]
    assert client.post(f"/v1/punchout/sessions/{cookie}/convert", headers=login("requester"), json={}).status_code == 409

    # A second cart goes onto the same draft requisition.
    second = _start(client, login)
    client.post("/v1/punchout/return", data={"cxml-urlencoded": _shop(client, second, qty="1")})
    added = client.post(f"/v1/punchout/sessions/{second['buyer_cookie']}/convert", headers=login("requester"),
                        json={"requisition": pr["number"]})
    assert added.status_code == 200, added.text
    assert [l["line_no"] for l in added.json()["lines"]] == [10, 20] and added.json()["total_minor"] == 3 * 1_850_000


def test_punchout_posts_setup_request_to_a_real_supplier(client, login, monkeypatch):
    sent = {}

    class Answer:
        status_code = 200
        text = ('<?xml version="1.0"?><cXML payloadID="1@kd" timestamp="2026-10-28T10:00:00+05:30"><Response>'
                '<Status code="200" text="success"/><PunchOutSetupResponse><StartPage><URL>https://shop.kd002.example/start?s=91</URL>'
                '</StartPage></PunchOutSetupResponse></Response></cXML>')

    def fake_post(url, content, headers, timeout):
        sent.update(url=url, document=content.decode(), headers=headers)
        return Answer()

    monkeypatch.setattr(punchout.httpx, "post", fake_post)
    assert client.put("/v1/suppliers/KD002/punchout", headers=login("supplier.manager"), json={
        "protocol": "CXML", "url": "https://shop.kd002.example/cxml/setup", "identity": "KD002-NET", "sharedSecret": "kd-secret-123"}).status_code == 200
    session = _start(client, login, supplier="KD002", who="buyer")
    assert session["startUrl"] == "https://shop.kd002.example/start?s=91"
    doc = sent["document"]
    assert sent["url"] == "https://shop.kd002.example/cxml/setup" and sent["headers"]["content-type"].startswith("text/xml")
    assert doc.startswith('<?xml version="1.0" encoding="UTF-8"?>') and "cXML.dtd" in doc
    root = punchout.parse_xml(doc)
    assert root.find("./Header/To/Credential/Identity").text == "KD002-NET"
    assert root.find("./Header/From/Credential/Identity").text == "AXN"
    assert root.find("./Header/Sender/Credential/SharedSecret").text == "kd-secret-123"
    request = root.find("./Request/PunchOutSetupRequest")
    assert request.get("operation") == "create" and request.find("BuyerCookie").text == session["buyer_cookie"]
    assert request.find("./BrowserFormPost/URL").text.endswith("/api/public/punchout/return")


def test_expired_punchout_session_is_rejected(client, login, builtin_cxml):
    session = _start(client, login)
    cxml = _shop(client, session)
    _sql("UPDATE pic.punchout_session SET expires_at = now() - interval '1 minute' WHERE buyer_cookie = :c", c=session["buyer_cookie"])
    late = client.post("/v1/punchout/return", data={"cxml-urlencoded": cxml})
    assert late.status_code == 410 and late.json()["code"] == "PUNCHOUT_SESSION_EXPIRED"
    status = _sql("SELECT status FROM pic.punchout_session WHERE buyer_cookie = :c", c=session["buyer_cookie"])[0]["status"]
    assert status == "EXPIRED"
    assert client.get(session["startUrl"].split("/api/pic", 1)[1]).status_code == 410
    unknown = client.post("/v1/punchout/return", data={"cxml-urlencoded": cxml.replace(session["buyer_cookie"], "AXN.unknown-cookie")})
    assert unknown.status_code == 404


def test_oci_return_parsing_and_builtin_oci_flow(client, login, builtin_cxml):
    cookie, protocol, items, _ = punchout.decode_return({
        "NEW_ITEM-DESCRIPTION[1]": "Hex bolt M8x50 8.8 zinc flake", "NEW_ITEM-QUANTITY[1]": "100", "NEW_ITEM-UNIT[1]": "PCE",
        "NEW_ITEM-PRICE[1]": "250,00", "NEW_ITEM-PRICEUNIT[1]": "10", "NEW_ITEM-CURRENCY[1]": "INR", "NEW_ITEM-VENDORMAT[1]": "HB-M8-50",
        "NEW_ITEM-MATGROUP[1]": "FASTENERS", "NEW_ITEM-EXT_CATEGORY_ID[1]": "31161500",
        "NEW_ITEM-DESCRIPTION[2]": "Washer M8", "NEW_ITEM-QUANTITY[2]": "100", "NEW_ITEM-UNIT[2]": "EA", "NEW_ITEM-PRICE[2]": "1.50",
        "NEW_ITEM-VENDORMAT[2]": "W-M8"}, "AXN.cookie-from-hook-url")
    assert cookie == "AXN.cookie-from-hook-url" and protocol == "OCI" and len(items) == 2
    assert (items[0]["supplierPartNo"], items[0]["qty"], items[0]["uom"], items[0]["unitPriceMinor"], items[0]["unspsc"]) == \
        ("HB-M8-50", "100", "EA", 2500, "31161500")
    assert items[0]["materialGroup"] == "FASTENERS" and items[1]["unitPriceMinor"] == 150 and items[1]["currency"] == "INR"

    assert client.put("/v1/suppliers/HTS004/punchout", headers=login("supplier.manager"),
                      json={"protocol": "OCI", "url": "builtin", "identity": "HTS004-CAT"}).status_code == 200   # secret kept
    session = _start(client, login)
    form = session["formFields"]
    assert session["method"] == "POST" and form["~OkCode"] == "ADDI" and form["HOOK_URL"].endswith(f"?cookie={session['buyer_cookie']}")
    assert client.post("/v1/punchout/simulator/catalogue", data={**form, "PASSWORD": "wrong-password"}).status_code == 401
    page = client.post("/v1/punchout/simulator/catalogue", data=form)
    assert page.status_code == 200 and "HTS-PM-STD" in page.text
    item_id = re.search(r"name='qty_([0-9a-f-]+)'", page.text).group(1)
    checkout = client.post("/v1/punchout/simulator/checkout", data={"cookie": session["buyer_cookie"], f"qty_{item_id}": "3"})
    fields = {html.unescape(k): html.unescape(v) for k, v in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', checkout.text)}
    assert fields["NEW_ITEM-VENDORMAT[1]"] == "HTS-PM-STD" and fields["NEW_ITEM-QUANTITY[1]"] == "3"
    action = html.unescape(re.search(r'action="([^"]+)"', checkout.text).group(1))
    returned = client.post("/v1/punchout/return?" + action.split("?", 1)[1], data=fields)
    assert returned.status_code == 200, returned.text
    cart = client.get(f"/v1/punchout/sessions/{session['buyer_cookie']}", headers=login("requester")).json()
    assert cart["protocol"] == "OCI" and cart["cart"][0]["unitPriceMinor"] == 1_850_000 and cart["cart"][0]["qty"] == "3"
    # A cXML document is refused on an OCI session.
    mismatch = _start(client, login)
    doc = ('<cXML><Message><PunchOutOrderMessage><BuyerCookie>' + mismatch["buyer_cookie"] + '</BuyerCookie>'
           '<ItemIn quantity="1"><ItemID><SupplierPartID>X</SupplierPartID></ItemID><ItemDetail><UnitPrice><Money currency="INR">1.00</Money>'
           '</UnitPrice><Description>X</Description><UnitOfMeasure>EA</UnitOfMeasure></ItemDetail></ItemIn></PunchOutOrderMessage></Message></cXML>')
    assert client.post("/v1/punchout/return", data={"cxml-urlencoded": doc}).json()["code"] == "PROTOCOL_MISMATCH"
    entity = '<!DOCTYPE x [<!ENTITY a "aaaa">]>' + doc
    assert client.post("/v1/punchout/return", data={"cxml-urlencoded": entity}).json()["code"] == "INVALID_CXML"


# ---------------------------------------------------------------- category budget (§24.1, M01)
@pytest.fixture(scope="module")
def category_budgets():
    from app.pic.platform import clock
    tenant_id = _tenant_id()
    fiscal_year = clock.fiscal_year(clock.today())
    with tenant_tx(tenant_id) as s:
        owner = s.execute(text("SELECT id FROM pic.app_user WHERE email = 'category.head@axion.example'")).scalar()
        for number, category in (("CP-T901", "MOT-SOFT"), ("CP-T902", "MOT-HARD")):
            s.execute(text(
                "INSERT INTO pic.category_plan (id, tenant_id, number, category, fiscal_year, spend_minor, profit_impact, supply_risk, kraljic, "
                "evidence, levers, waves, budget_minor, owner_id, status, approved_by, approved_at, created_at, row_version) VALUES "
                "(:id, :t, :n, :c, :fy, 0, 1, 1, 'NON_CRITICAL', '{}', '[]', '[]', 1000000, :o, 'APPROVED', :o, now(), now(), 1)"),
                {"id": uuid.uuid4(), "t": tenant_id, "n": number, "c": category, "fy": fiscal_year, "o": owner})
        s.execute(text(
            "INSERT INTO pic.rule_set (id, tenant_id, key, version, category, effective_from, body, description, created_at, row_version) VALUES "
            "(:id, :t, 'CATEGORY-BUDGET', '2026.1-MOT', 'MOT-HARD', :f, CAST(:b AS jsonb), 'test: hard stop for MOT-HARD', now(), 1)"),
            {"id": uuid.uuid4(), "t": tenant_id, "f": date(2026, 4, 1), "b": '{"mode": "HARD", "warnAtPct": 80}'})
    return fiscal_year


def _requisition(client, login, category: str, price_minor: int) -> str:
    r = client.post("/v1/requisitions", headers=login("requester"), json={
        "origin": "MANUAL", "purpose_code": "MAINTENANCE", "plant": "P100", "lines": [{
            "item_type": "FREE_TEXT", "purchase_type": "NON_STOCK", "description": f"{category} budget test item", "material_group": category,
            "category": category, "qty": "1", "price_est_minor": price_minor, "account_assignment_type": "COST_CENTER",
            "account_assignment_code": "4100", "need_date": "2026-12-15"}]})
    assert r.status_code == 201, r.text
    return r.json()["number"]


def test_category_budget_soft_warning_and_justification(client, login, category_budgets):
    first = _requisition(client, login, "MOT-SOFT", 950_000)                         # 95% of a ₹10,000 plan, warn at 90%
    r = client.post(f"/v1/requisitions/{first}/submit", headers=login("requester"), json={})
    assert r.status_code == 200, r.text
    check = r.json()["budget_result"]["categoryBudget"]
    assert check["outcome"] == "WARNING" and check["fiscalYear"] == category_budgets and "committed" in check["measure"]
    assert check["checks"][0]["usedPct"] == "95.0" and check["checks"][0]["mode"] == "SOFT" and check["warnings"]
    assert "CATEGORY-BUDGET@2026.1" in r.json()["rule_set_version"]
    assert _sql("SELECT 1 FROM pic.audit_event WHERE object_ref = :n AND action = 'CATEGORY_BUDGET_CHECKED'", n=first)

    second = _requisition(client, login, "MOT-SOFT", 200_000)                        # 950k committed (in approval) + 200k = 115%
    refused = client.post(f"/v1/requisitions/{second}/submit", headers=login("requester"), json={})
    assert refused.status_code == 422 and refused.json()["code"] == "CATEGORY_BUDGET_JUSTIFICATION_REQUIRED"
    assert refused.json()["categoryBudget"]["committedMinor"] == 950_000 and refused.json()["categoryBudget"]["usedPct"] == "115.0"
    ok = client.post(f"/v1/requisitions/{second}/submit", headers=login("requester"),
                     json={"justification": "Line-2 die breakdown; reallocated from Q4 MRO plan"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["budget_result"]["categoryBudget"]["outcome"] == "EXCEEDED_JUSTIFIED"


def test_category_budget_hard_block(client, login, category_budgets):
    number = _requisition(client, login, "MOT-HARD", 1_200_000)
    r = client.post(f"/v1/requisitions/{number}/submit", headers=login("requester"), json={"justification": "urgent"})
    assert r.status_code == 422 and r.json()["code"] == "CATEGORY_BUDGET_EXCEEDED" and r.json()["ruleRef"] == "CATEGORY-BUDGET@2026.1-MOT"
    assert r.json()["categoryBudget"]["mode"] == "HARD"
    assert client.get(f"/v1/requisitions/{number}", headers=login("requester")).json()["status"] == "DRAFT"
    small = _requisition(client, login, "MOT-HARD", 850_000)                          # 85%: warning at 80% under the HARD rule
    passed = client.post(f"/v1/requisitions/{small}/submit", headers=login("requester"), json={})
    assert passed.status_code == 200 and passed.json()["budget_result"]["categoryBudget"]["outcome"] == "WARNING"


def test_seeded_requisitions_unaffected_by_category_budget(client, login):
    # The approved ALU-DIECAST plan is for 2027-28; no seeded requisition was submitted in that fiscal year.
    pr = client.get("/v1/requisitions/REQ-2311", headers=login("buyer")).json()
    assert pr["approval_chain"] == ["COST_OBJECT_OWNER", "DEPT_HEAD", "PROCUREMENT_HEAD", "FINANCE_CONTROLLER"]
    assert (pr["budget_result"].get("categoryBudget") or {"outcome": "NOT_APPLICABLE"})["outcome"] == "NOT_APPLICABLE"



# ---------------------------------------------------------------- F8-03 licensed sanctions / watch-list provider (mocked)
class _Response:
    def __init__(self, status_code: int, data):
        self.status_code, self._data = status_code, data

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=None, response=None)


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("PIC_SANCTIONS_PROVIDER", "WatchList-Pro")
    monkeypatch.setenv("PIC_SANCTIONS_URL", "https://screening.watchlist.example/v2/")
    monkeypatch.setenv("PIC_SANCTIONS_API_KEY", "wl-key-123")
    state = {"calls": [], "search": lambda params: _Response(200, {"results": []}), "list": lambda: _Response(404, {})}

    def fake_get(url, params=None, headers=None, timeout=None):
        state["calls"].append({"url": url, "params": params, "headers": headers})
        return state["search"](params) if url.endswith("/search") else state["list"]()

    monkeypatch.setattr("httpx.get", fake_get)
    return state


def _self_register(client, login, name: str, pan: str, email: str) -> dict:
    invitation = _invite(client, login, email, name, ["MRO"])
    r = client.post(f"/v1/public/invitations/{invitation['token']}/register", json=_registration(name, pan, email))
    assert r.status_code == 201, r.text
    return client.get(f"/v1/suppliers/{r.json()['supplier']}", headers=login("supplier.manager")).json()


def test_sanctions_provider_hit_blocks_the_supplier(client, login, provider):
    provider["search"] = lambda params: _Response(200, {"results": [
        {"name": "Thanjavur Metal Exports", "score": 0.97, "list": "OFAC-SDN", "id": "ofac-77"},
        {"name": "Unrelated Trading", "score": 0.31}]})
    sup = _self_register(client, login, "Thanjavur Metal Exports", "AAACT6612M", "hello@thanjavur-metal.example")
    assert sup["status"] == "BLOCKED" and sup["screening"]["outcome"] == "BLOCKED"
    assert "WATCHLIST-PRO" in sup["screening"]["sanctionsHits"] and sup["screening"]["provider"] == "WATCHLIST-PRO"
    assert [(h["name"], h["list"], h["ref"]) for h in sup["screening"]["providerHits"]] == [("Thanjavur Metal Exports", "OFAC-SDN", "ofac-77")]
    call = provider["calls"][-1]
    assert call["url"] == "https://screening.watchlist.example/v2/search" and call["params"]["name"] == "Thanjavur Metal Exports"
    assert call["headers"]["authorization"] == "Bearer wl-key-123"


def test_sanctions_provider_outage_does_not_block_registration(client, login, provider):
    import httpx

    def down(params):
        raise httpx.ConnectError("connection refused")

    provider["search"] = down
    sup = _self_register(client, login, "Madurai Brass Works", "AAACM9081L", "hello@madurai-brass.example")
    assert sup["status"] == "REGISTERED" and sup["screening"]["outcome"] == "REVIEW"
    assert sup["screening"]["providerError"].startswith("WATCHLIST-PRO: ConnectError")
    assert {c["category"]: c["status"] for c in sup["categories"]} == {"MRO": "UNDER_QUALIFICATION"}


def test_sanctions_list_sync_replaces_only_the_provider_source(client, login, provider, monkeypatch):
    def count(source):
        return _sql("SELECT count(*) AS n FROM pic.sanction_entry WHERE source = :s", s=source)[0]["n"]

    sample = count("SAMPLE-LIST")
    assert sample > 0
    assert client.post("/v1/admin/sanctions/sync", headers=login("supplier.manager")).status_code == 403
    no_list = client.post("/v1/admin/sanctions/sync", headers=login("admin"))
    assert no_list.status_code == 409 and no_list.json()["code"] == "SANCTIONS_LIST_UNAVAILABLE"
    provider["list"] = lambda: _Response(200, {"entries": [{"name": "Alpha Sanctioned Co", "id": "1"}, {"name": "Beta Embargoed Ltd", "id": "2"}]})
    first = client.post("/v1/admin/sanctions/sync", headers=login("admin"))
    assert first.status_code == 200, first.text
    assert first.json()["loaded"] == 2 and "SAMPLE-LIST" in first.json()["otherSourcesKept"] and count("WATCHLIST-PRO") == 2
    provider["list"] = lambda: _Response(200, [{"name": "Gamma Restricted Pvt Ltd"}])
    second = client.post("/v1/admin/sanctions/sync", headers=login("admin")).json()
    assert (second["loaded"], second["replaced"], count("WATCHLIST-PRO"), count("SAMPLE-LIST")) == (1, 2, 1, sample)
    provider["list"] = lambda: _Response(200, {"entries": []})
    assert client.post("/v1/admin/sanctions/sync", headers=login("admin")).json()["replaced"] == 1 and count("WATCHLIST-PRO") == 0
    monkeypatch.delenv("PIC_SANCTIONS_PROVIDER")
    unconfigured = client.post("/v1/admin/sanctions/sync", headers=login("admin"))
    assert unconfigured.status_code == 409 and unconfigured.json()["code"] == "SANCTIONS_PROVIDER_NOT_CONFIGURED"


def test_without_a_provider_the_local_list_still_blocks(client, login):
    zat = client.get("/v1/suppliers/ZAT006", headers=login("supplier.manager")).json()
    assert zat["status"] == "BLOCKED" and zat["screening"]["outcome"] == "BLOCKED" and "provider" not in zat["screening"]


def test_supplier_registration_validates_tax_ids(client, login):
    """F8-01 applies the MDM-04 tax-ID checks: a mistyped GSTIN (wrong check character) or a PAN outside it is refused."""
    headers = login("supplier.manager")
    body = {"legal_name": "Typo Castings Pvt Ltd", "gstin": "33AABCT9999Q1Z0", "pan": "AABCT9999Q", "state_code": "33",
            "contact_email": "sales@typo-castings.example", "categories": ["ALU-DIECAST"]}
    bad = client.post("/v1/suppliers", headers=headers, json=body)
    assert bad.status_code == 422 and bad.json()["code"] == "VALIDATION_FAILED"
    assert any("check character" in e for e in bad.json()["errors"])
    other_pan = client.post("/v1/suppliers", headers=headers, json={**body, "gstin": "33AABCT9999Q1Z" + master_changes.gstin_check_char("33AABCT9999Q1Z"),
                                                                     "pan": "AABCT8888Q"})
    assert other_pan.status_code == 422 and any("PAN must match" in e for e in other_pan.json()["errors"])
