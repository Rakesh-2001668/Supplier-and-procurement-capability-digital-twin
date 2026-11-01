"""The whole administration journey through the real HTTP API (TestClient, real bearer tokens), one sequential scenario.

provision a tenant with the command-line tool -> first administrator activates through the link and signs in with MFA -> builds the
organisation (company code, plant, calendar, storage location, cost centre, purchasing organisation and group) -> invites a buyer and
an approver who activate -> custom role and the SoD refusal -> template preview, apply, re-apply -> new rule version with a future
effective date while a document is in flight -> new workflow definition version -> integration failure and replay -> audit explorer
and hash-chain verification -> session revocation -> a second tenant sees none of it (RLS) -> the Admin KPIs.

The tests share state on purpose and run in file order; a failing step stops the rest (pytest -x or the module-scoped ``J`` state).
"""
import argparse
import time
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import Budget, IntegrationMessage, Tenant
from app.pic.platform import clock, integration, mfa
from app.pic.tools import tenant_admin

TENANT = "JRNY1"
OTHER = "JRNY2"
ADMIN_EMAIL = "owner@jrny1.example"
PASSWORD = "Qv8#nLp3-Wk6zRt!"
J: dict = {}  # state handed from step to step


def _token_of(url: str) -> str:
    return url.split("token=", 1)[1]


def _provision(code: str, email: str, template: str = "GENERAL") -> dict:
    return tenant_admin.create(argparse.Namespace(
        code=code, name=f"{code} Industries Pvt Ltd", template=template, admin_email=email, admin_name="Olga Owner", company_code="1000",
        company_name=None, gstin="27AAAAA0000A1Z2", plant="P100", plant_name="Main plant", state_code="27"))


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _enrol_and_sign_in(client, tenant: str, email: str, password: str, step_offset: int = 0) -> tuple[dict, str]:
    """Sign in as a user whose role needs MFA: the sign-in answers MFA_ENROLMENT_REQUIRED, the user registers an authenticator and
    confirms it with a current code, and that confirmation finishes the sign-in. Returns (auth header, TOTP secret)."""
    r = client.post("/v1/auth/token", json={"tenant": tenant, "email": email, "password": password})
    assert r.status_code == 403 and r.json()["code"] == "MFA_ENROLMENT_REQUIRED", r.text
    challenge = _bearer(r.json()["enrolmentChallenge"])
    secret = client.post("/v1/me/mfa/totp", headers=challenge).json()["secret"]
    done = client.post("/v1/me/mfa/totp/confirm", json={"code": mfa.totp(secret)}, headers=challenge)
    assert done.status_code == 200, done.text
    return _bearer(done.json()["access_token"]), secret


def _mfa_sign_in(client, tenant: str, email: str, password: str, secret: str) -> dict:
    """Second and later sign-ins: password, then the next time step's code (the current step was used up by the enrolment)."""
    r = client.post("/v1/auth/token", json={"tenant": tenant, "email": email, "password": password})
    assert r.status_code == 200 and r.json()["mfaRequired"] is True, r.text
    done = client.post("/v1/auth/mfa", json={"challenge": r.json()["challenge"], "code": mfa.totp(secret, at=time.time() + 30)})
    assert done.status_code == 200, done.text
    return _bearer(done.json()["access_token"])


def _login(client, tenant: str, email: str, password: str = PASSWORD) -> dict:
    r = client.post("/v1/auth/token", json={"tenant": tenant, "email": email, "password": password})
    assert r.status_code == 200, r.text
    return _bearer(r.json()["access_token"])


def _activate(client, activation_url: str, password: str = PASSWORD) -> None:
    r = client.post(f"/v1/public/user-tokens/{_token_of(activation_url)}/complete", json={"password": password})
    assert r.status_code == 200, r.text


def _trail(client, admin, **params) -> list[dict]:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(f"/v1/audit?limit=500&{query}", headers=admin).json()["items"]


# ---------------------------------------------------------------- 1. provision and first administrator
def test_01_provision_tenant_with_the_tool_and_activate_the_first_admin(client):
    result = _provision(TENANT, ADMIN_EMAIL)
    assert result["tenant"] == TENANT and result["admin"] == ADMIN_EMAIL
    with pytest.raises(tenant_admin.ToolError):  # repeating it provisions nothing
        _provision(TENANT, ADMIN_EMAIL)
    token = _token_of(result["activationUrl"])
    # cannot sign in before activation (no password exists yet)
    assert client.post("/v1/auth/token", json={"tenant": TENANT, "email": ADMIN_EMAIL, "password": PASSWORD}).status_code == 401
    info = client.get(f"/v1/public/user-tokens/{token}")
    assert info.status_code == 200 and info.json()["purpose"] == "ACTIVATION" and info.json()["tenantCode"] == TENANT
    _activate(client, result["activationUrl"])
    reuse = client.post(f"/v1/public/user-tokens/{token}/complete", json={"password": "Zy4%hGd9-Bm2sQw"})
    assert reuse.status_code == 410 and reuse.json()["code"] == "LINK_USED"
    J["admin"], J["admin_secret"] = _enrol_and_sign_in(client, TENANT, ADMIN_EMAIL, PASSWORD)
    me = client.get("/v1/me", headers=J["admin"]).json()
    assert me["roles"] == ["TENANT_ADMIN"] and me["tenant"] == TENANT and "admin:rules" in me["scopes"]
    org = client.get("/v1/admin/organisation", headers=J["admin"]).json()
    assert [c["code"] for c in org["companyCodes"]] == ["1000"] and [p["code"] for p in org["plants"]] == ["P100"]
    assert org["tenant"]["industryTemplate"] == "GENERAL"


# ---------------------------------------------------------------- 2. the organisation
def test_02_administrator_builds_the_organisation(client):
    a = J["admin"]
    post = lambda path, body: client.post(f"/v1/admin/org/{path}", json=body, headers=a)  # noqa: E731
    cc = post("company-codes", {"code": "2000", "name": "Journey Trading Pvt Ltd", "gstin": "27AAAAA0000A1Z2", "currency": "INR", "fiscal_year_start_month": 4})
    assert cc.status_code == 201, cc.text
    plant = post("plants", {"code": "P200", "name": "Pune plant", "company_code": "2000", "state_code": "27", "working_days": [0, 1, 2, 3, 4]})
    assert plant.status_code == 201, plant.text
    J["plant_id"] = plant.json()["id"]
    assert post("storage-locations", {"plant": "P200", "code": "RM01", "name": "Raw material store"}).status_code == 201
    assert post("cost-objects", {"type": "COST_CENTER", "code": "CC-100", "company_code": "2000", "name": "Procurement office"}).status_code == 201
    assert post("purchasing-orgs", {"code": "PO20", "name": "Journey purchasing", "company_code": "2000"}).status_code == 201
    holiday = client.post(f"/v1/admin/org/plants/{J['plant_id']}/holidays", headers=a,
                          json={"dates": ["2027-01-26", "2027-08-15"], "source": "Maharashtra Government Gazette 2027"})
    assert holiday.status_code == 200 and holiday.json()["added"] == ["2027-01-26", "2027-08-15"]
    # the same company code twice, a bad GSTIN and an unknown company are refused with problem+json
    assert post("company-codes", {"code": "2000", "name": "Again"}).json()["code"] == "CODE_EXISTS"
    assert post("company-codes", {"code": "3000", "name": "Bad GSTIN Ltd", "gstin": "27AAAAA0000A1Z9"}).status_code == 422
    assert post("plants", {"code": "P900", "name": "Ghost", "company_code": "9999", "state_code": "27"}).status_code == 422


# ---------------------------------------------------------------- 3. users invite and activate
def test_03_invited_buyer_and_approver_activate_and_sign_in(client):
    a = J["admin"]
    buyer = client.post("/v1/admin/users", headers={**a, "Idempotency-Key": "jrny-buyer"}, json={
        "email": "buyer@jrny1.example", "name": "Bina Buyer", "roles": ["BUYER"],
        "attributes": {"plants": ["P200"], "company_codes": ["2000"], "value_limit_minor": 50_000_000}})
    assert buyer.status_code == 201, buyer.text
    again = client.post("/v1/admin/users", headers={**a, "Idempotency-Key": "jrny-buyer"}, json={
        "email": "buyer@jrny1.example", "name": "Bina Buyer", "roles": ["BUYER"],
        "attributes": {"plants": ["P200"], "company_codes": ["2000"], "value_limit_minor": 50_000_000}})
    assert again.json()["id"] == buyer.json()["id"] and again.json()["replayed"] is True  # idempotent: one user
    approver = client.post("/v1/admin/users", headers=a, json={
        "email": "approver@jrny1.example", "name": "Arun Approver", "roles": ["COST_OBJECT_OWNER"],
        "attributes": {"plants": ["P200"], "company_codes": ["2000"], "cost_objects": ["COST_CENTER:CC-100"]}})
    assert approver.status_code == 201, approver.text
    J["buyer_id"], J["approver_id"] = buyer.json()["id"], approver.json()["id"]
    assert {u["status"] for u in client.get("/v1/admin/users", headers=a).json() if u["email"].startswith(("buyer@", "approver@"))} == {"INVITED"}
    _activate(client, buyer.json()["activationUrl"])
    _activate(client, approver.json()["activationUrl"])
    J["buyer"] = _login(client, TENANT, "buyer@jrny1.example")
    J["approver"], J["approver_secret"] = _enrol_and_sign_in(client, TENANT, "approver@jrny1.example", PASSWORD)  # approvers need MFA
    assert client.get("/v1/me", headers=J["buyer"]).json()["attributes"]["plants"] == ["P200"]
    # the buyer is not an administrator
    assert client.post("/v1/admin/org/plants", headers=J["buyer"], json={"code": "PX", "name": "No", "company_code": "1000", "state_code": "27"}).status_code == 403
    assert client.get("/v1/admin/users", headers=J["buyer"]).status_code == 403
    # purchasing group with the buyer, now that the buyer exists
    group = client.post("/v1/admin/org/purchasing-groups", headers=a, json={"code": "PG20", "name": "Direct materials", "purchasing_org": "PO20",
                                                                          "plant": "P200", "buyer_user_ids": [J["buyer_id"]]})
    assert group.status_code == 201 and group.json()["buyerUserIds"] == [J["buyer_id"]]


# ---------------------------------------------------------------- 4. custom role and SoD
def test_04_custom_role_and_the_sod_refusal(client):
    a = J["admin"]
    role = client.post("/v1/admin/roles", headers=a, json={"code": "GR_DESK", "name": "Goods receipt desk", "scopes": ["pic:read", "tasks:work", "gr:post"]})
    assert role.status_code == 201, role.text
    # a role that spans a segregation-of-duties pair is refused, with the evidence
    both = client.post("/v1/admin/roles", headers=a, json={"code": "PO_AND_GR", "name": "Both", "scopes": ["pic:read", "po:create", "gr:post"]})
    assert both.status_code == 409 and both.json()["code"] == "SOD_CONFLICT" and both.json()["impact"]["ownConflicts"][0]["rule"] == "SOD-03"
    # a platform-level scope can never be given to a tenant-defined role
    assert client.post("/v1/admin/roles", headers=a, json={"code": "SUPER", "name": "Super", "scopes": ["pic:read", "admin:rules"]}).status_code == 422
    # and the new role cannot be put on the buyer (po:create + gr:post)
    refused = client.put(f"/v1/admin/users/{J['buyer_id']}/roles", headers=a, json={"roles": ["BUYER", "GR_DESK"], "reason": "cover for receiving"})
    assert refused.status_code == 409 and refused.json()["code"] == "SOD_CONFLICT"
    matrix = client.get("/v1/admin/roles/matrix", headers=a).json()
    assert {r["code"] for r in matrix["roles"]} >= {"BUYER", "TENANT_ADMIN", "GR_DESK"}
    assert client.get("/v1/admin/roles", headers=a).json()[-1]["role"] == "GR_DESK"


# ---------------------------------------------------------------- 5. template
def test_05_template_preview_apply_and_reapply(client):
    a = J["admin"]
    preview = client.get("/v1/admin/templates/MANUFACTURING/preview", headers=a).json()
    assert preview["switchesTemplate"] and any(c["key"] == "SELF-BILLING" and c["action"] == "ADD" for c in preview["ruleSetChanges"])
    applied = client.post("/v1/admin/templates/MANUFACTURING/apply", headers=a)
    assert applied.status_code == 200 and applied.json()["applied"] is True
    changed = {c["key"] for c in applied.json()["ruleSetChanges"]}
    assert "SELF-BILLING" in changed
    again = client.post("/v1/admin/templates/MANUFACTURING/apply", headers=a).json()
    assert again["applied"] is False and again["noop"] is True and again["ruleSetChanges"] == []
    preview2 = client.get("/v1/admin/templates/MANUFACTURING/preview", headers=a).json()
    assert preview2["alreadyApplied"] is True and preview2["noop"] is True and preview2["history"][0]["template"] == "MANUFACTURING"
    assert client.get("/v1/admin/organisation", headers=a).json()["tenant"]["industryTemplate"] == "MANUFACTURING"


# ---------------------------------------------------------------- 6. rule version with a future effective date
def test_06_new_rule_version_does_not_touch_the_document_in_flight(client):
    a, buyer, approver = J["admin"], J["buyer"], J["approver"]
    need = (clock.today() + timedelta(days=30)).isoformat()
    body = {"origin": "MANUAL", "purpose_code": "IT", "plant": "P200", "company_code": "2000", "lines": [
        {"item_type": "FREE_TEXT", "purchase_type": "EXPENSE", "description": "Label printer", "material_group": "IT-HW", "qty": "1", "uom": "EA",
         "price_est_minor": 4_500_000, "account_assignment_type": "COST_CENTER", "account_assignment_code": "CC-100", "need_date": need,
         "quotes": [{"supplier": "Printer reseller Pune", "reference": "PRP-Q-0042", "date": clock.today().isoformat()}]}]}
    # The budget for the new cost centre (there is no budget screen yet: seeded as data, like an ERP budget load would).
    year = clock.today().year if clock.today().month >= 4 else clock.today().year - 1
    with tenant_tx(system_tx_tenant(TENANT)) as s:
        s.add(Budget(tenant_id=system_tx_tenant(TENANT), cost_object_type="COST_CENTER", cost_object_code="CC-100", fiscal_year=f"{year}-{(year + 1) % 100:02d}",
                     control="SOFT", amount_minor=5_000_000_00))
    created = client.post("/v1/requisitions", json=body, headers=buyer)
    assert created.status_code == 201, created.text
    number = created.json()["number"]
    submitted = client.post(f"/v1/requisitions/{number}/submit", json={}, headers=buyer)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "IN_APPROVAL"
    old_version = client.get(f"/v1/requisitions/{number}", headers=buyer).json()["rule_set_version"]
    assert old_version.startswith("DMN-01@2026.1")
    J["req"], J["old_rule_version"] = number, old_version
    # publish DMN-01 2027.1: every requisition now needs the department head too, from a future date
    current = next(r for r in client.get("/v1/admin/rules", headers=a).json() if r["key"] == "DMN-01")
    bands = [{**b, "chain": list(dict.fromkeys([*b["chain"], "DEPT_HEAD"]))} for b in current["body"]["bands"]]
    future = (clock.today() + timedelta(days=45)).isoformat()
    new = client.post("/v1/admin/rules", headers=a, json={"key": "DMN-01", "version": "2027.1", "effective_from": future,
                                                           "body": {**current["body"], "bands": bands}, "description": "Department head on every route"})
    assert new.status_code == 201, new.text
    # the document in flight keeps the version it started under, the approval still runs on the old chain
    assert client.get(f"/v1/requisitions/{number}", headers=buyer).json()["rule_set_version"] == old_version
    sim_now = client.post("/v1/admin/rules/simulate", headers=a, json={"key": "DMN-01", "inputs": {"valueMinor": 4_500_000, "channel": "OTHER", "purchaseType": "EXPENSE"}}).json()
    sim_future = client.post("/v1/admin/rules/simulate", headers=a, json={"key": "DMN-01", "on": future, "inputs": {"valueMinor": 4_500_000, "channel": "OTHER", "purchaseType": "EXPENSE"}}).json()
    assert sim_now["resolved"]["version"] == "2026.1" and sim_now["result"]["chain"] == ["COST_OBJECT_OWNER"]
    assert sim_future["resolved"]["version"] == "2027.1" and sim_future["result"]["chain"] == ["COST_OBJECT_OWNER", "DEPT_HEAD"]
    # a document created today is still routed by the version in force today
    again = client.post("/v1/requisitions", json=body, headers=buyer).json()["number"]
    client.post(f"/v1/requisitions/{again}/submit", json={}, headers=buyer)
    assert client.get(f"/v1/requisitions/{again}", headers=buyer).json()["rule_set_version"].startswith("DMN-01@2026.1")
    # the in-flight document is approved by the cost-object owner on the old chain
    tasks = [t for t in client.get("/v1/tasks", headers=approver).json() if t["object_ref"] == number]
    assert len(tasks) == 1
    done = client.post(f"/v1/tasks/{tasks[0]['id']}/complete", json={"decision": "APPROVE"}, headers=approver)
    assert done.status_code == 200, done.text
    final = client.get(f"/v1/requisitions/{number}", headers=buyer).json()
    assert final["status"] == "APPROVED" and final["rule_set_version"] == old_version


# ---------------------------------------------------------------- 7. workflow definition
def test_07_publish_a_new_workflow_definition_version(client):
    a = J["admin"]
    keys = client.get("/v1/process-definitions", headers=a).json()
    key = next(d["key"] for d in keys if d["flow"] == "F2")  # the requisition flow
    active = next(d for d in keys if d["key"] == key)
    draft = client.post(f"/v1/process-definitions/{key}/drafts", headers=a, json={"note": "Journey draft"})
    assert draft.status_code == 201, draft.text
    version = draft.json()["version"]
    assert version > active["version"] and draft.json()["status"] == "DRAFT"
    checked = client.post(f"/v1/process-definitions/{key}/versions/{version}/validate", headers=a).json()
    assert checked["valid"] is True, checked
    published = client.post(f"/v1/process-definitions/{key}/versions/{version}/publish", headers=a, json={"reason": "Journey: publish the reviewed route"})
    assert published.status_code == 200 and published.json()["status"] == "ACTIVE"
    now_active = next(d for d in client.get("/v1/process-definitions", headers=a).json() if d["key"] == key)
    assert now_active["version"] == version
    # the requisition that was in flight finished on its own version
    inst = client.get(f"/v1/documents/REQUISITION/{J['req']}/process", headers=a)
    assert inst.status_code == 200 and inst.json()[0]["version"] == active["version"] and version > inst.json()[0]["version"]


# ---------------------------------------------------------------- 8. integration failure and replay
def _enqueue(tid, key: str, ref: str) -> uuid.UUID:
    """A goods-receipt posting to the ERP (no business document is needed: the message ledger is what the monitor shows)."""
    with tenant_tx(tid) as s:
        m = integration.enqueue(s, target_system="SAP_S4", message_type="GOODS_RECEIPT", idempotency_key=key, object_type="GOODS_RECEIPT",
                                object_id=uuid.uuid4(), object_ref=ref, payload={"companyCode": "2000", "grossMinor": 1_000_000})
        return m.id


def test_08_integration_failure_is_visible_and_replayable(client):
    a = J["admin"]
    tid = system_tx_tenant(TENANT)
    first, second = _enqueue(tid, "jrny-po-1", "PO-J-1"), _enqueue(tid, "jrny-po-2", "PO-J-2")
    integration.FAULTS["fail"] = 2
    try:
        tick = client.post("/v1/admin/ops/tick", headers=a)
        assert tick.status_code == 200, tick.text
    finally:
        integration.FAULTS["fail"] = 0
    monitor = {m["object_ref"]: m for m in client.get("/v1/integration/messages", headers=a).json()["items"]}
    assert monitor["PO-J-1"]["status"] == "RETRY" and "ERP did not answer" in monitor["PO-J-1"]["last_error"]
    assert monitor["PO-J-2"]["status"] == "RETRY"
    # an operator replays the first message: re-sent with the same idempotency key, posted once
    replayed = client.post(f"/v1/integration/messages/{first}/replay", headers=a)
    assert replayed.status_code == 200 and replayed.json()["status"] == "POSTED" and replayed.json()["erp_doc_no"]
    assert client.post(f"/v1/integration/messages/{first}/replay", headers=a).status_code == 409  # already posted
    # the second one succeeds on its scheduled retry (a retry that needed two attempts feeds the resolve-time KPI)
    with tenant_tx(tid) as s:
        s.get(IntegrationMessage, second).next_attempt_at = clock.now() - timedelta(seconds=1)
    assert client.post("/v1/admin/ops/tick", headers=a).status_code == 200
    after = {m["object_ref"]: m for m in client.get("/v1/integration/messages", headers=a).json()["items"]}
    assert after["PO-J-2"]["status"] == "POSTED" and after["PO-J-2"]["attempts"] == 2
    assert after["PO-J-1"]["erp_doc_no"] != after["PO-J-2"]["erp_doc_no"]


def system_tx_tenant(code: str) -> uuid.UUID:
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == code)).scalar_one()


# ---------------------------------------------------------------- 9. admin KPIs
def test_09_admin_kpis_are_computed(client):
    kpis = client.get("/v1/kpis?module=M13", headers=J["admin"]).json()
    items = kpis["items"] if isinstance(kpis, dict) else kpis
    by_code = {k["code"]: k for k in items}
    assert {"M13.INTEGRATION_SUCCESS", "M13.MTTR_INTEGRATION", "M13.SOD_OPEN"} <= set(by_code), sorted(by_code)
    success = by_code["M13.INTEGRATION_SUCCESS"]
    assert success["value"] is not None and float(success["value"]) == 100.0  # both messages ended POSTED
    assert by_code["M13.MTTR_INTEGRATION"]["value"] is not None  # PO-J-2 needed a retry
    assert float(by_code["M13.SOD_OPEN"]["value"]) == 0.0


# ---------------------------------------------------------------- 10. audit
def test_10_audit_explorer_shows_every_step_and_the_chain_verifies(client):
    a = J["admin"]
    seen = {(e["objectType"], e["action"]) for e in _trail(client, a)}
    expected = {("TENANT", "PROVISIONED"), ("APP_USER", "USER_INVITED"), ("APP_USER", "USER_ACTIVATED"), ("COMPANY_CODE", "CREATED"),
                ("PLANT", "CREATED"), ("PLANT", "CALENDAR_UPDATED"), ("STORAGE_LOCATION", "CREATED"), ("COST_OBJECT", "CREATED"),
                ("PURCHASING_ORG", "CREATED"), ("PURCHASING_GROUP", "CREATED"), ("ROLE", "CREATED"), ("TENANT", "TEMPLATE_APPLIED"),
                ("REQUISITION", "SUBMIT"), ("GOODS_RECEIPT", "ERP_POSTED"), ("GOODS_RECEIPT", "INTEGRATION_REPLAY")}
    missing = expected - seen
    assert not missing, f"not in the audit trail: {sorted(missing)}"
    assert {e["actor"] for e in _trail(client, a, object_type="COMPANY_CODE")} == {f"u:{ADMIN_EMAIL}"}
    assert any(e["actor"] == "agent:tenant_admin_tool" for e in _trail(client, a, object_type="TENANT", action="PROVISIONED"))
    verify = client.get("/v1/audit/verify", headers=a).json()
    assert verify["valid"] is True and verify["checked"] >= len(expected)


# ---------------------------------------------------------------- 11. revoke a session
def test_11_revoked_session_is_refused_at_once(client):
    a, buyer = J["admin"], J["buyer"]
    assert client.get("/v1/me", headers=buyer).status_code == 200 and client.get("/v1/tasks", headers=buyer).status_code == 200
    revoked = client.post(f"/v1/admin/users/{J['buyer_id']}/revoke-sessions", headers=a, json={"reason": "Journey: laptop reported lost"})
    assert revoked.status_code == 200
    old = client.get("/v1/tasks", headers=buyer)
    assert old.status_code == 401 and old.json()["code"] == "SESSION_REVOKED"
    assert client.get("/v1/me", headers=buyer).status_code == 401
    J["buyer"] = _login(client, TENANT, "buyer@jrny1.example")  # signing in again works
    assert client.get("/v1/tasks", headers=J["buyer"]).status_code == 200
    # the administrator's own session is unaffected, and a password reset ends the user's sessions once the link is used
    reset = client.post(f"/v1/admin/users/{J['buyer_id']}/password-reset", headers=a, json={"reason": "Journey: forgotten password, ticket 7"}).json()
    new_password = "Hn3@vTq8-Cs5mXe"
    assert client.get("/v1/tasks", headers=J["buyer"]).status_code == 200
    assert client.post(f"/v1/public/user-tokens/{_token_of(reset['resetUrl'])}/complete", json={"password": new_password}).status_code == 200
    assert client.get("/v1/tasks", headers=J["buyer"]).status_code == 401
    assert client.get("/v1/admin/users", headers=a).status_code == 200
    # deactivation also ends the session
    assert client.put(f"/v1/admin/users/{J['approver_id']}/active", headers=a, json={"active": False, "reason": "Journey: left the company"}).status_code == 200
    gone = client.get("/v1/tasks", headers=J["approver"])
    assert gone.status_code == 401 and gone.json()["code"] == "ACCOUNT_DISABLED"


# ---------------------------------------------------------------- 12. a second tenant sees none of it
def test_12_a_second_tenant_cannot_see_any_of_it(client):
    result = _provision(OTHER, "owner@jrny2.example")
    _activate(client, result["activationUrl"])
    other, _ = _enrol_and_sign_in(client, OTHER, "owner@jrny2.example", PASSWORD)
    org = client.get("/v1/admin/organisation", headers=other).json()
    assert [c["code"] for c in org["companyCodes"]] == ["1000"] and [p["code"] for p in org["plants"]] == ["P100"]
    assert org["purchasingOrgs"] == [] and org["purchasingGroups"] == [] and org["costObjects"] == []
    assert {u["email"] for u in client.get("/v1/admin/users", headers=other).json()} == {"owner@jrny2.example"}
    assert [r["code"] for r in client.get("/v1/admin/roles/matrix", headers=other).json()["roles"] if r["kind"] == "CUSTOM"] == []
    assert client.get("/v1/admin/templates", headers=other).json()["current"] == "GENERAL"
    assert not [r for r in client.get("/v1/admin/rules", headers=other).json() if r["version"] == "2027.1"]
    assert client.get(f"/v1/requisitions/{J['req']}", headers=other).status_code == 404
    assert client.get("/v1/integration/messages", headers=other).json()["items"] == []
    assert client.get("/v1/process-definitions", headers=other).status_code == 200
    seen = {(e["objectType"], e["action"]) for e in _trail(client, other)}
    assert ("COMPANY_CODE", "CREATED") not in seen and ("ROLE", "CREATED") not in seen and ("TENANT", "TEMPLATE_APPLIED") not in seen
    # records of tenant one are unreachable by id as well
    for path in ("plants", "purchasing-orgs"):
        mine = next(x for x in client.get(f"/v1/admin/org/{path}", headers=J["admin"]).json() if x["code"] in ("P200", "PO20"))
        assert client.put(f"/v1/admin/org/{path}/{mine['id']}", headers=other, json={"name": "Hijacked"}).status_code == 404
        assert client.delete(f"/v1/admin/org/{path}/{mine['id']}", headers=other).status_code == 404
    other_trail = client.get("/v1/audit/verify", headers=other).json()
    assert other_trail["valid"] is True
    # a token of tenant one cannot be replayed against tenant two's data: the tenant comes from the token only
    assert client.get("/v1/admin/organisation", headers=J["admin"]).json()["tenant"]["code"] == TENANT
    # the template of tenant two stays as provisioned
    with tenant_tx(system_tx_tenant(OTHER)) as s:
        assert s.execute(select(IntegrationMessage.id)).first() is None
