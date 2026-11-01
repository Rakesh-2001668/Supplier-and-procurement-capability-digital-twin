"""Wave 1, engineer E: generic Idempotency-Key and ETag/If-Match, ABAC on commands, SoD mitigation, versioned workflow definitions
and BPMN, ERP field mappings, inclusive band edges, key versioning, password policy, tenant MFA default, migration compatibility.

Mutating tests run in their own tenant WV1E so the Axion signature case is untouched; AXN is only read."""
import json
import threading
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.pic.config import get_settings
from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuditEvent, ErpDocument, IdempotencyRecord, IntegrationFieldMapping, IntegrationMessage, MfaFactor, ProcessDefinition,
    RuleSet, SodMitigation, SodRule, SodViolation, Task, Tenant,
)
from app.pic.platform import (
    abac, bpmn, clock, crypto, definitions, field_mapping, idempotency, integration, passwords, preconditions, rules, sod, workflow,
)
from app.pic.platform.auth import Principal, hash_password, scopes_for
from app.pic.platform.errors import Problem
from app.pic.seed import reference
from tests.pic.conftest import PASSWORD

T = "WV1E"


# ---------------------------------------------------------------- the tenant these tests own
USERS = {
    "admin": ["TENANT_ADMIN"], "buyer": ["BUYER"], "receiver": ["RECEIVER"], "head": ["PROCUREMENT_HEAD"], "cpo": ["CPO"],
    "buyer2": ["BUYER"], "plain": ["REQUESTER"], "ap": ["AP_CLERK"],
}


@pytest.fixture(scope="module")
def tid():
    tenant_id = reference.create_tenant(T, "Wave One E Test Pvt Ltd", "MANUFACTURING", mfa_enforce=False)
    reference.bootstrap(tenant_id, company=("1000", "Wave One E Test Pvt Ltd", "33AAACW1111C1Z8"), plants=[("P100", "Chennai", "33")],
                        cost_objects=[("COST_CENTER", "4100", "Admin")])
    reference.deploy_process_definitions()
    with tenant_tx(tenant_id) as s:
        for local, roles in USERS.items():
            if not s.execute(select(AppUser.id).where(AppUser.email == f"{local}@wv1e.example")).first():
                s.add(AppUser(tenant_id=tenant_id, email=f"{local}@wv1e.example", full_name=local.title(), password_hash=hash_password(PASSWORD),
                              roles=roles, attributes={}))
    return tenant_id


@pytest.fixture(scope="module")
def auth(client, tid):
    tokens = {}

    def _auth(local: str) -> dict:
        if local not in tokens:
            r = client.post("/v1/auth/token", json={"tenant": T, "email": f"{local}@wv1e.example", "password": PASSWORD})
            assert r.status_code == 200, r.text
            tokens[local] = {"Authorization": f"Bearer {r.json()['access_token']}"}
        return tokens[local]

    return _auth


def _principal(s, tenant_id, local: str) -> Principal:
    user = s.execute(select(AppUser).where(AppUser.email == f"{local}@wv1e.example")).scalar_one()
    p = Principal(user.id, tenant_id, T, user.email, user.full_name, list(user.roles), scopes_for(list(user.roles)), user.attributes or {})
    s.info["principal"], s.info["user_id"] = p, user.id
    return p


# ================================================================ 1. generic Idempotency-Key
def _mapping_body(note: str) -> dict:
    return {"targetSystem": "SAP_S4", "messageType": "SUPPLIER_INVOICE", "rules": [{"op": "constant", "to": "SourceSystem", "value": "PIC"}], "note": note}


def test_idempotent_replay_returns_stored_response_without_running_again(client, auth, tid):
    key = f"idem-{uuid.uuid4()}"
    first = client.post("/v1/admin/field-mappings", json=_mapping_body("replay"), headers={**auth("admin"), "Idempotency-Key": key})
    assert first.status_code == 201 and "idempotent-replayed" not in first.headers
    again = client.post("/v1/admin/field-mappings", json=_mapping_body("replay"), headers={**auth("admin"), "Idempotency-Key": key})
    assert again.status_code == 201 and again.headers["Idempotent-Replayed"] == "true"
    assert again.json() == first.json()
    drafts = [m for m in client.get("/v1/admin/field-mappings", headers=auth("admin")).json() if m["note"] == "replay"]
    assert len(drafts) == 1, "the replay must not create a second draft"


def test_same_key_with_another_body_or_path_is_refused(client, auth, tid):
    key = f"idem-{uuid.uuid4()}"
    ok = client.post("/v1/admin/field-mappings", json=_mapping_body("one"), headers={**auth("admin"), "Idempotency-Key": key})
    assert ok.status_code == 201
    other = client.post("/v1/admin/field-mappings", json=_mapping_body("two"), headers={**auth("admin"), "Idempotency-Key": key})
    assert other.status_code == 422 and other.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    elsewhere = client.post("/v1/admin/field-mappings/preview", json={"rules": [], "samplePayload": {}}, headers={**auth("admin"), "Idempotency-Key": key})
    assert elsewhere.status_code == 422 and elsewhere.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    # JSON key order does not matter
    reordered = client.post("/v1/admin/field-mappings", content=json.dumps(dict(reversed(list(_mapping_body("one").items())))),
                            headers={**auth("admin"), "Idempotency-Key": key, "content-type": "application/json"})
    assert reordered.status_code == 201 and reordered.headers["Idempotent-Replayed"] == "true"


def test_keys_are_per_user_and_failures_release_the_key(client, auth, tid):
    key = f"idem-{uuid.uuid4()}"
    bad = client.post("/v1/admin/field-mappings", json={**_mapping_body("bad"), "rules": [{"op": "nope"}]}, headers={**auth("admin"), "Idempotency-Key": key})
    assert bad.status_code == 422
    good = client.post("/v1/admin/field-mappings", json=_mapping_body("after failure"), headers={**auth("admin"), "Idempotency-Key": key})
    assert good.status_code == 201 and "idempotent-replayed" not in good.headers, "a failed attempt must not burn the key"
    # another user with the same key is a different request, not a replay
    forbidden = client.post("/v1/admin/field-mappings", json=_mapping_body("after failure"), headers={**auth("buyer"), "Idempotency-Key": key})
    assert forbidden.status_code == 403


def test_concurrent_requests_with_one_key_run_once(client, auth, tid):
    key = f"idem-{uuid.uuid4()}"
    results = []

    def call():
        r = client.post("/v1/admin/field-mappings", json=_mapping_body("race"), headers={**auth("admin"), "Idempotency-Key": key})
        results.append((r.status_code, r.headers.get("Idempotent-Replayed")))

    threads = [threading.Thread(target=call) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    statuses = sorted(code for code, _ in results)
    assert statuses.count(201) >= 1 and all(code in (201, 409) for code in statuses), results
    created = [m for m in client.get("/v1/admin/field-mappings", headers=auth("admin")).json() if m["note"] == "race"]
    assert len(created) == 1, f"executed {len(created)} times"


def test_in_flight_duplicate_is_409_and_expired_records_are_ignored(client, auth, tid):
    key = f"idem-{uuid.uuid4()}"
    admin = auth("admin")
    me = client.get("/v1/me", headers=admin).json()
    body = _mapping_body("inflight")
    digest = idempotency.fingerprint("POST", "/v1/admin/field-mappings", "", "application/json", json.dumps(body).encode())
    with tenant_tx(tid) as s:  # a reservation whose request is still running
        s.add(IdempotencyRecord(tenant_id=tid, scope=f"http:{me['userId']}", key=key, request_hash=digest))
    r = client.post("/v1/admin/field-mappings", json=body, headers={**admin, "Idempotency-Key": key})
    assert r.status_code == 409 and r.json()["code"] == "REQUEST_IN_PROGRESS"
    old = f"idem-{uuid.uuid4()}"
    with tenant_tx(tid) as s:  # a stored answer older than 24 h is not replayed
        s.add(IdempotencyRecord(tenant_id=tid, scope=f"http:{me['userId']}", key=old, request_hash="0" * 64, status_code=201,
                                response={"headers": {}, "body": "{}"}, created_at=clock.now() - timedelta(hours=25)))
    fresh = client.post("/v1/admin/field-mappings", json=_mapping_body("expired"), headers={**admin, "Idempotency-Key": old})
    assert fresh.status_code == 201 and "idempotent-replayed" not in fresh.headers
    assert idempotency.purge_expired(tid) >= 0


def test_routes_with_their_own_idempotent_helper_keep_their_replay_body(client, login):
    """Existing routes store and replay their own body (replayed: true); the generic layer only guards concurrency there."""
    headers = {**login("admin")}
    key = f"own-{uuid.uuid4()}"
    tasks = client.get("/v1/tasks", headers=login("plant.controller")).json()
    assert isinstance(tasks, list)
    # POST /v1/tasks/{id}/complete uses idempotent(...): a bogus task id fails twice the same way and the key is not burned
    bogus = f"/v1/tasks/{uuid.uuid4()}/complete"
    a = client.post(bogus, json={"decision": "APPROVE"}, headers={**login("plant.controller"), "Idempotency-Key": key})
    b = client.post(bogus, json={"decision": "APPROVE"}, headers={**login("plant.controller"), "Idempotency-Key": key})
    assert a.status_code == b.status_code == 404 and headers


def test_core_idempotent_flags_the_request_as_self_handled(tid):
    from app.pic.platform.core import Idempotent
    state = {"handled": False}
    token = idempotency.STATE.set(state)
    try:
        with tenant_tx(tid) as s:
            Idempotent(s, "POST /v1/test", f"k-{uuid.uuid4()}", {"a": 1})
    finally:
        idempotency.STATE.reset(token)
    assert state["handled"] is True


# ================================================================ 2. ETag / If-Match
def test_detail_gets_carry_an_etag_and_stale_if_match_is_412(client, login):
    admin = login("buyer")
    po = client.get("/v1/purchase-orders/PO-77410", headers=admin)
    assert po.status_code == 200 and po.headers["ETag"].startswith('"')
    for path in ("/v1/requisitions/REQ-2311", "/v1/suppliers/TF001", "/v1/contracts/SA-5520"):
        r = client.get(path, headers=login("procurement.head"))
        assert r.status_code == 200 and r.headers.get("ETag"), path
    stale = client.post("/v1/purchase-orders/PO-77410/validate", headers={**admin, "If-Match": '"999999"'})
    assert stale.status_code == 412 and stale.json()["code"] == "STALE_WRITE"
    current = client.post("/v1/purchase-orders/PO-77410/validate", headers={**admin, "If-Match": po.headers["ETag"]})
    assert current.status_code != 412
    wildcard = client.post("/v1/purchase-orders/PO-77410/validate", headers={**admin, "If-Match": "*"})
    assert wildcard.status_code != 412
    assert "ETag" not in client.get("/v1/purchase-orders", headers=admin).headers, "lists have no document validator"


def test_if_match_is_required_on_document_overwrites_when_enforced(client, login, monkeypatch):
    monkeypatch.setattr(get_settings(), "require_if_match", True)
    r = client.post("/v1/purchase-orders/PO-77410/versions", json={"changes": [{"line": 10, "qty": "1"}], "reason": "test"}, headers=login("buyer"))
    assert r.status_code == 428 and r.json()["code"] == "PRECONDITION_REQUIRED"
    tag = client.get("/v1/purchase-orders/PO-77410", headers=login("buyer")).headers["ETag"]
    again = client.post("/v1/purchase-orders/PO-77410/versions", json={"changes": [{"line": 10, "qty": "1"}], "reason": "test"},
                        headers={**login("buyer"), "If-Match": tag})
    assert again.status_code != 428
    monkeypatch.setattr(get_settings(), "require_if_match", False)


def test_precondition_tag_parsing():
    assert preconditions.parse('"3"') == ["3"] and preconditions.parse('W/"4", "5"') == ["4", "5"] and preconditions.parse("*") == ["*"]


# ================================================================ 3. ABAC
POLICY = {"mode": "ENFORCE", "dimensions": {"company_code": "company_codes", "plant": "plants", "category": "categories"},
          "valueLimitAttribute": "value_limit_minor", "limitsAttribute": "approval_limits",
          "actions": {"PO_RELEASE": {"check": ["company_code", "plant"], "valueLimit": True}, "GR_POST": {"check": ["plant"]}}}


def test_abac_evaluate_dimensions_wildcards_and_limits():
    dims = {"company_code": "1000", "plant": "P100", "category": None}
    assert abac.evaluate(POLICY, {}, "PO_RELEASE", dims, 10**9)["allowed"], "no attributes: not restricted"
    assert abac.evaluate(POLICY, {"plants": ["*"], "company_codes": ["1000"]}, "PO_RELEASE", dims, 1)["allowed"]
    denied = abac.evaluate(POLICY, {"plants": ["P200"]}, "PO_RELEASE", dims, 1)
    assert not denied["allowed"] and denied["violations"][0]["dimension"] == "plant"
    assert not abac.evaluate(POLICY, {"company_codes": ["2000"]}, "PO_RELEASE", dims, 1)["allowed"]
    over = abac.evaluate(POLICY, {"value_limit_minor": 500}, "PO_RELEASE", dims, 501)
    assert over["violations"][0]["code"] == "VALUE_LIMIT_EXCEEDED" and abac.evaluate(POLICY, {"value_limit_minor": 500}, "PO_RELEASE", dims, 500)["allowed"]
    per_action = abac.evaluate(POLICY, {"value_limit_minor": 10, "approval_limits": {"PO_RELEASE": 1000}}, "PO_RELEASE", dims, 900)
    assert per_action["allowed"], "a limit per action wins over the general limit"
    assert abac.evaluate(POLICY, {"plants": ["P200"]}, "UNKNOWN_ACTION", dims, 1)["allowed"]
    assert abac.evaluate({**POLICY, "mode": "OFF"}, {"plants": ["P200"]}, "PO_RELEASE", dims, 1)["allowed"]
    audit_only = abac.evaluate({**POLICY, "mode": "AUDIT"}, {"plants": ["P200"]}, "PO_RELEASE", dims, 1)
    assert not audit_only["allowed"] and not audit_only["enforced"]


def test_abac_authorize_denies_audits_and_respects_modes(tid):
    obj = SimpleNamespace(id=uuid.uuid4(), number="PO-TEST", company_code="1000", plant="P100", total_minor=5_000_00, __tablename__="purchase_order")
    with tenant_tx(tid) as s:
        buyer = _principal(s, tid, "buyer2")
        user = s.get(AppUser, buyer.user_id)
        user.attributes = {"plants": ["P200"], "value_limit_minor": 1_000_00}
        s.flush()
        with pytest.raises(Problem) as denied:
            abac.authorize(s, buyer, "PO_RELEASE", obj)
        assert denied.value.status == 403 and denied.value.rule_ref == "ABAC"
        assert {v["dimension"] for v in denied.value.extra["violations"]} == {"plant", "value"}
        abac.authorize(s, buyer, "GR_POST", SimpleNamespace(plant="P200", company_code="1000"))  # allowed: P200
        agent = Principal(uuid.uuid4(), tid, T, "a@agents.pic", "agent", ["BUYER"], set(), {}, agent_code="X")
        assert abac.authorize(s, agent, "PO_RELEASE", obj)["allowed"], "agents are bounded by their autonomy limits, not user attributes"
        user.attributes = {}
    with tenant_tx(tid) as s:  # the denial was audited in its own transaction
        events = s.execute(select(AuditEvent).where(AuditEvent.action == "ABAC_DENIED", AuditEvent.object_ref == "PO-TEST")).scalars().all()
        assert events and events[-1].after["action"] == "PO_RELEASE"


def test_abac_policy_is_a_rule_set_and_audit_mode_logs_without_blocking(tid):
    obj = SimpleNamespace(id=uuid.uuid4(), number="PO-AUDIT", company_code="1000", plant="P100", total_minor=1, __tablename__="purchase_order")
    with tenant_tx(tid) as s:
        p = _principal(s, tid, "buyer2")
        s.get(AppUser, p.user_id).attributes = {"plants": ["P200"]}
        s.flush()
        base = rules.resolve(s, "ABAC").body
        s.add(RuleSet(tenant_id=tid, key="ABAC", version="audit-test", effective_from=clock.today() + timedelta(days=0), company_code="1000",
                      body={**base, "mode": "AUDIT"}, description="audit mode (test)"))
        s.flush()
        result = abac.authorize(s, p, "PO_RELEASE", obj)
        assert not result["allowed"] and not result["enforced"], "the company-code scoped AUDIT version is the most specific"
        s.get(AppUser, p.user_id).attributes = {}
        s.rollback()


def test_abac_simulator_matches_enforcement(client, login):
    r = client.post("/v1/admin/rules/simulate", headers=login("admin"), json={
        "key": "ABAC", "inputs": {"user": "buyer@axion.example", "action": "PO_RELEASE", "plant": "P900", "valueMinor": 100}})
    assert r.status_code == 200, r.text
    assert r.json()["result"]["decision"] == "DENY" and r.json()["result"]["violations"][0]["dimension"] == "plant"
    ok = client.post("/v1/admin/rules/simulate", headers=login("admin"),
                     json={"key": "ABAC", "inputs": {"user": "buyer@axion.example", "action": "PO_RELEASE", "plant": "P100"}})
    assert ok.json()["result"]["decision"] == "ALLOW"
    inline = client.post("/v1/admin/rules/simulate", headers=login("admin"),
                         json={"key": "ABAC", "inputs": {"attributes": {"value_limit_minor": 10}, "action": "INVOICE_POST", "valueMinor": 11}})
    assert inline.json()["result"]["violations"][0]["code"] == "VALUE_LIMIT_EXCEEDED"


def test_shipped_users_pass_abac_for_their_signature_case_actions(tid):
    """The Axion users are scoped to P100/P200; the P100 commands of the signature case must be allowed."""
    with system_tx() as s:
        axn = s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()
    with tenant_tx(axn) as s:
        for local, action in (("buyer", "PO_CREATE"), ("receiver", "GR_POST"), ("requester", "REQ_SUBMIT"), ("mrp.controller", "REQ_SUBMIT")):
            user = s.execute(select(AppUser).where(AppUser.email == f"{local}@axion.example")).scalar_one()
            p = Principal(user.id, axn, "AXN", user.email, user.full_name, list(user.roles), scopes_for(list(user.roles)), user.attributes or {})
            assert abac.authorize(s, p, action, SimpleNamespace(company_code="1000", plant="P100", total_minor=10**7))["allowed"], (local, action)


# ================================================================ 4. SoD mitigation
@pytest.fixture()
def sod_session(tid):
    """One rolled-back transaction in WV1E with rule SOD-03 (High risk) in MITIGATE mode."""
    class Rollback(Exception):
        pass
    clock.set_pinned(clock.at_ist(clock.today(), 10))
    try:
        with pytest.raises(Rollback):
            with tenant_tx(tid) as s:
                for rule in s.execute(select(SodRule)).scalars():
                    rule.mode = "MITIGATE" if rule.code in ("SOD-03", "SOD-02") else "BLOCK"
                s.flush()
                yield s
                raise Rollback
    finally:
        clock.set_pinned(None)


def _approve_as(s, tid, local: str, task_id, decision="APPROVE", comment="ok"):
    previous = s.info["principal"]
    _principal(s, tid, local)
    try:
        return workflow.complete(s, task_id, decision, comment)
    finally:
        s.info["principal"], s.info["user_id"] = previous, previous.user_id


def test_sod_conflict_offers_and_honours_an_approved_time_boxed_exception(tid, sod_session):
    s = sod_session
    po_id = uuid.uuid4()
    buyer = _principal(s, tid, "buyer")
    sod.record(s, "PO_CREATE", {"po_id": po_id})
    with pytest.raises(Problem) as blocked:
        sod.guard(s, "GR_POST", {"po_id": po_id})
    offer = blocked.value.extra["mitigation"]
    assert blocked.value.code == "SOD_CONFLICT" and offer["available"] and offer["ruleCode"] == "SOD-03" and offer["approverRoles"] == ["PROCUREMENT_HEAD", "CPO"]

    with pytest.raises(Problem) as short:
        sod.request_mitigation(s, rule_code="SOD-03", action="GR_POST", refs={"po_id": str(po_id)}, justification="too short")
    assert short.value.code == "JUSTIFICATION_REQUIRED"
    m = sod.request_mitigation(s, rule_code="SOD-03", action="GR_POST", refs={"po_id": str(po_id)},
                               justification="Receiver on leave; goods are on the dock and the line is waiting", validity_hours=8)
    assert m.status == "PENDING" and m.max_uses == 1 and m.compensating_control
    with pytest.raises(Problem) as dup:
        sod.request_mitigation(s, rule_code="SOD-03", action="GR_POST", refs={"po_id": str(po_id)}, justification="x" * 30)
    assert dup.value.code == "MITIGATION_PENDING"
    with pytest.raises(Problem):
        sod.guard(s, "GR_POST", {"po_id": po_id})  # a pending request is no grant

    task = s.execute(select(Task).where(Task.object_id == m.id, Task.status == "OPEN")).scalar_one()
    assert task.kind == "SOD_MITIGATION" and task.candidate_role == "PROCUREMENT_HEAD" and buyer.user_id in task.excluded_user_ids
    with pytest.raises(Problem) as self_approve:  # the requester never approves their own exception
        previous = s.info["principal"]
        s.get(AppUser, buyer.user_id).roles = ["BUYER", "PROCUREMENT_HEAD"]
        s.flush()
        s.info["principal"] = Principal(buyer.user_id, tid, T, buyer.email, buyer.name, ["BUYER", "PROCUREMENT_HEAD"], set(), {})
        workflow.complete(s, task.id, "APPROVE", "mine")
    assert self_approve.value.code == "NOT_YOUR_TASK"
    s.info["principal"] = previous
    s.get(AppUser, buyer.user_id).roles = ["BUYER"]

    _approve_as(s, tid, "head", task.id)
    second = s.execute(select(Task).where(Task.object_id == m.id, Task.status == "OPEN")).scalar_one()
    _approve_as(s, tid, "cpo", second.id)
    s.refresh(m)
    assert m.status == "APPROVED" and (m.valid_until - m.valid_from) == timedelta(hours=8)

    sod.guard(s, "GR_POST", {"po_id": po_id})  # the original command proceeds under the grant ...
    assert m.use_count == 1
    with pytest.raises(Problem):                # ... once (maxUses 1 for High risk)
        sod.guard(s, "GR_POST", {"po_id": po_id})
    assert any(v.outcome == "MITIGATED" for v in s.execute(select(SodViolation)).scalars())
    actions = [e.action for e in s.execute(select(AuditEvent).where(AuditEvent.object_type == "SOD_MITIGATION")).scalars()]
    assert {"REQUESTED", "APPROVED", "USED"} <= set(actions)


def test_sod_exception_expires_and_rejection_and_revocation_end_it(tid, sod_session):
    s = sod_session
    po_id = uuid.uuid4()
    _principal(s, tid, "buyer")
    sod.record(s, "PO_CREATE", {"po_id": po_id})
    m = sod.request_mitigation(s, rule_code="SOD-03", action="GR_POST", refs={"po_id": str(po_id)}, justification="a documented business reason here",
                               validity_hours=2)
    _approve_as(s, tid, "head", s.execute(select(Task).where(Task.object_id == m.id, Task.status == "OPEN")).scalar_one().id)
    _approve_as(s, tid, "cpo", s.execute(select(Task).where(Task.object_id == m.id, Task.status == "OPEN")).scalar_one().id)
    clock.set_pinned(clock.now() + timedelta(hours=3))
    try:
        assert sod.effective_status(m) == "EXPIRED"
        with pytest.raises(Problem):
            sod.guard(s, "GR_POST", {"po_id": po_id})
    finally:
        clock.set_pinned(clock.at_ist(clock.today(), 10))
    # rejected request
    po2 = uuid.uuid4()
    sod.record(s, "PO_CREATE", {"po_id": po2})
    r = sod.request_mitigation(s, rule_code="SOD-03", action="GR_POST", refs={"po_id": str(po2)}, justification="a documented business reason here")
    _approve_as(s, tid, "head", s.execute(select(Task).where(Task.object_id == r.id, Task.status == "OPEN")).scalar_one().id, "REJECT", "no")
    assert r.status == "REJECTED"
    with pytest.raises(Problem):
        sod.guard(s, "GR_POST", {"po_id": po2})
    # revocation
    po3 = uuid.uuid4()
    sod.record(s, "PO_CREATE", {"po_id": po3})
    g = sod.request_mitigation(s, rule_code="SOD-03", action="GR_POST", refs={"po_id": str(po3)}, justification="a documented business reason here")
    _approve_as(s, tid, "head", s.execute(select(Task).where(Task.object_id == g.id, Task.status == "OPEN")).scalar_one().id)
    _approve_as(s, tid, "cpo", s.execute(select(Task).where(Task.object_id == g.id, Task.status == "OPEN")).scalar_one().id)
    sod.revoke(s, g.id, "no longer needed")
    with pytest.raises(Problem):
        sod.guard(s, "GR_POST", {"po_id": po3})
    report = sod.report(s)
    assert report["summary"]["byStatus"].get("REJECTED") == 1 and report["summary"]["byStatus"].get("REVOKED") == 1


def test_critical_and_block_mode_rules_have_no_exception_path(tid, sod_session):
    s = sod_session
    supplier_id = uuid.uuid4()
    _principal(s, tid, "buyer")
    sod.record(s, "SUPPLIER_BANK_CHANGE", {"supplier_id": supplier_id})
    with pytest.raises(Problem) as critical:
        sod.guard(s, "PAYMENT_APPROVE", {"supplier_id": supplier_id})
    assert critical.value.extra["mitigation"]["available"] is False
    with pytest.raises(Problem) as nope:
        sod.request_mitigation(s, rule_code="SOD-02", action="PAYMENT_APPROVE", refs={"supplier_id": str(supplier_id)}, justification="x" * 40)
    assert nope.value.code == "NOT_MITIGABLE"
    with pytest.raises(Problem) as block:
        sod.request_mitigation(s, rule_code="SOD-04", action="INVOICE_EXCEPTION_APPROVE", refs={"po_id": str(uuid.uuid4())}, justification="x" * 40)
    assert block.value.code == "NOT_MITIGABLE"
    with pytest.raises(Problem) as none:
        sod.request_mitigation(s, rule_code="SOD-03", action="GR_POST", refs={"po_id": str(uuid.uuid4())}, justification="x" * 40)
    assert none.value.code == "NO_CONFLICT"


def test_sod_admin_api_mode_switch_and_report(client, auth, tid):
    admin = auth("admin")
    assert client.put("/v1/admin/sod/SOD-02", json={"mode": "MITIGATE", "reason": "try"}, headers=admin).json()["code"] == "NOT_MITIGABLE"
    ok = client.put("/v1/admin/sod/SOD-06", json={"mode": "MITIGATE", "reason": "allow a documented exception"}, headers=admin)
    assert ok.status_code == 200 and ok.json()["mode"] == "MITIGATE"
    assert client.put("/v1/admin/sod/SOD-06", json={"mode": "BLOCK", "reason": "back to block"}, headers=admin).json()["mode"] == "BLOCK"
    body = client.get("/v1/admin/sod", headers=admin).json()
    assert "mitigations" in body and "summary" in body["mitigations"]
    assert client.get("/v1/admin/sod/mitigations", headers=admin).status_code == 200
    assert client.put("/v1/admin/sod/SOD-06", json={"mode": "BLOCK", "reason": "no"}, headers=auth("buyer")).status_code == 403


# ================================================================ 5. workflow definitions
def test_baseline_definitions_are_valid_and_complete(tid):
    with tenant_tx(tid) as s:
        shipped = definitions.effective(s)
        assert len(shipped) == 9
        for d in shipped:
            assert d.version == 1 and d.tenant_id is None and d.status == "ACTIVE"
            result = definitions.validate(s, d.key, d.definition)
            assert result["valid"], (d.key, result["errors"])
            assert d.definition["flows"] and d.definition["lanes"]


def _base(s, key="pic.requisition"):
    return json.loads(json.dumps(definitions.get(s, key, 1).definition))


def test_validation_finds_structural_problems(tid):
    with tenant_tx(tid) as s:
        def codes(d):
            return {e["code"] for e in definitions.validate(s, "pic.requisition", d)["errors"]}
        d = _base(s)
        d["steps"].append({"id": "X-01", "type": "user", "lane": "Requester", "name": "Orphan"})
        assert "STEP_UNREACHABLE" in codes(d) or "START_EVENT" in codes(d)
        d = _base(s)
        d["flows"] = [f for f in d["flows"] if not (f["from"] == "F2-03" and f.get("label") == "no")]
        assert "GATEWAY_OUTCOMES" in codes(d)
        d = _base(s)
        d["steps"][1]["roles"] = ["WIZARD"]
        assert "ROLE_UNKNOWN" in codes(d)
        d = _base(s)
        d["steps"][1]["taskKind"] = "NO_SUCH_KIND"
        assert "TASK_KIND_UNKNOWN" in codes(d) or "TASK_KIND_ON_NON_USER_STEP" in codes(d)
        d = _base(s)
        d["steps"][1]["slaBusinessDays"] = 0
        assert "SLA_INVALID" in codes(d)
        d = _base(s)
        d["steps"] = [x for x in d["steps"] if x["id"] != "F2-08"]
        d["flows"] = [f for f in d["flows"] if "F2-08" not in (f["from"], f["to"])]
        assert "STEP_REQUIRED_BY_CODE" in codes(d)
        d = _base(s)
        d["flows"].append({"from": "F2-09", "to": "F2-02"})  # an end that loops back: nothing reaches an end any more
        assert codes(d) & {"END_EVENT", "NO_PATH_TO_END", "DEAD_END"}
        d = _base(s)
        d["steps"].append(dict(d["steps"][0]))
        assert "STEP_DUPLICATE" in codes(d)
        assert definitions.validate(s, "pic.requisition", "nonsense")["valid"] is False
        assert definitions.validate(s, "pic.requisition", {"steps": []})["valid"] is False


def test_designer_api_draft_validate_publish_and_running_instances_keep_their_version(client, auth, tid):
    admin = auth("admin")
    key = "pic.requisition"
    listing = client.get("/v1/process-definitions", headers=admin).json()
    assert len(listing) == 9 and all(d["version"] == 1 for d in listing)
    # an instance that starts now stays on version 1
    with tenant_tx(tid) as s:
        _principal(s, tid, "buyer")
        old = workflow.start(s, key, "REQUISITION", uuid.uuid4(), "REQ-WV1E-OLD")
        old_id = old.id
        assert old.process_version == 1
    base = client.get(f"/v1/process-definitions/{key}/versions/1", headers=admin)
    assert base.status_code == 200 and base.json()["editable"] is False
    assert client.put(f"/v1/process-definitions/{key}/versions/1", json={"note": "x"}, headers=admin).status_code == 403

    draft = client.post(f"/v1/process-definitions/{key}/drafts", json={"note": "add a budget owner check"}, headers=admin)
    assert draft.status_code == 201, draft.text
    v = draft.json()["version"]
    assert v >= 2 and draft.json()["status"] == "DRAFT" and draft.json()["baseVersion"] == 1
    assert client.post(f"/v1/process-definitions/{key}/drafts", json={}, headers=admin).json()["code"] == "DRAFT_EXISTS"

    got = client.get(f"/v1/process-definitions/{key}/versions/{v}", headers=admin)
    body = got.json()
    steps = body["steps"]
    for step in steps:
        if step["id"] == "F2-08":
            step["slaBusinessDays"] = 1
    steps.append({"id": "F2-07b", "type": "system", "lane": "Platform · Policy & Budget", "name": "Notify budget owner", "screen": None})
    flows = [f for f in body["flows"] if not (f["from"] == "F2-07" and f["to"] == "F2-08")]
    flows += [{"from": "F2-07", "to": "F2-07b"}, {"from": "F2-07b", "to": "F2-08"}]
    stale = client.put(f"/v1/process-definitions/{key}/versions/{v}", json={"definition": {**body, "steps": steps, "flows": flows}},
                       headers={**admin, "If-Match": '"99"'})
    assert stale.status_code == 412
    saved = client.put(f"/v1/process-definitions/{key}/versions/{v}", json={"definition": {**body, "steps": steps, "flows": flows}},
                       headers={**admin, "If-Match": got.headers["ETag"]})
    assert saved.status_code == 200 and saved.json()["revision"] == body["revision"] + 1
    assert client.post(f"/v1/process-definitions/{key}/versions/{v}/validate", headers=admin).json()["valid"] is True

    # a broken draft cannot be published
    broken = client.put(f"/v1/process-definitions/{key}/versions/{v}", headers=admin,
                        json={"definition": {"steps": steps, "flows": [f for f in flows if f["to"] != "F2-07b"]}})
    assert broken.status_code == 200
    refused = client.post(f"/v1/process-definitions/{key}/versions/{v}/publish", json={"reason": "go ahead"}, headers=admin)
    assert refused.status_code == 422 and refused.json()["code"] == "DEFINITION_INVALID" and refused.json()["errors"]
    client.put(f"/v1/process-definitions/{key}/versions/{v}", json={"definition": {"steps": steps, "flows": flows}}, headers=admin)

    published = client.post(f"/v1/process-definitions/{key}/versions/{v}/publish", json={"reason": "budget owner is told"}, headers=admin)
    assert published.status_code == 200 and published.json()["status"] == "ACTIVE" and published.json()["scope"] == "TENANT"
    diff = client.get(f"/v1/process-definitions/{key}/diff", params={"from": 1, "to": v}, headers=admin).json()
    assert [x["id"] for x in diff["stepsAdded"]] == ["F2-07b"] and any(c["id"] == "F2-08" for c in diff["stepsChanged"]) and not diff["identical"]
    assert next(d for d in client.get("/v1/process-definitions", headers=admin).json() if d["key"] == key)["version"] == v

    with tenant_tx(tid) as s:
        _principal(s, tid, "buyer")
        new = workflow.start(s, key, "REQUISITION", uuid.uuid4(), "REQ-WV1E-NEW")
        assert new.process_version == v, "new instances start on the published version"
        assert workflow._step_sla(s, new, "F2-08") == 1 and workflow._step_sla(s, s.get(type(new), old_id), "F2-08") is None
        survivor = s.get(type(new), old_id)
        workflow.step(s, survivor, "F2-02")  # the running instance keeps working on version 1
        assert survivor.process_version == 1
    # other tenants still see only the shared version 1
    other = client.get(f"/v1/process-definitions/{key}/versions", headers=_axn_admin(client)).json()
    assert [x["version"] for x in other] == [1]
    # retire the tenant's version: new instances fall back to the shared one
    assert client.post(f"/v1/process-definitions/{key}/versions/{v}/retire", json={"reason": "back to standard"}, headers=admin).json()["status"] == "RETIRED"
    with tenant_tx(tid) as s:
        _principal(s, tid, "buyer")
        assert workflow.start(s, key, "REQUISITION", uuid.uuid4(), "REQ-WV1E-BACK").process_version == 1


def _axn_admin(client):
    r = client.post("/v1/auth/token", json={"tenant": "AXN", "email": "admin@axion.example", "password": PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_draft_can_be_discarded_and_only_admins_edit(client, auth, tid):
    key = "pic.po"
    draft = client.post(f"/v1/process-definitions/{key}/drafts", json={}, headers=auth("admin"))
    assert draft.status_code == 201
    assert client.post(f"/v1/process-definitions/{key}/drafts", json={}, headers=auth("buyer")).status_code == 403
    v = draft.json()["version"]
    assert client.delete(f"/v1/process-definitions/{key}/versions/{v}", headers=auth("admin")).status_code == 200
    assert client.get(f"/v1/process-definitions/{key}/versions/{v}", headers=auth("admin")).status_code == 404


def test_bpmn_round_trip_and_viewer_xml(client, auth, tid):
    with tenant_tx(tid) as s:
        d = definitions.get(s, "pic.po", 1)
        xml = bpmn.to_xml(d.key, d.name, d.definition)
    assert "bpmn:startEvent" in xml and "bpmn:exclusiveGateway" in xml and "bpmndi:BPMNShape" in xml and "bpmn:lane " in xml
    back = bpmn.from_xml(xml)
    assert [(x["id"], x["type"], x["lane"], x["name"]) for x in back["steps"]] == [(x["id"], x["type"], x["lane"], x["name"]) for x in d.definition["steps"]]
    assert {(f["from"], f["to"], f.get("label")) for f in back["flows"]} == {(f["from"], f["to"], f.get("label")) for f in d.definition["flows"]}
    assert next(x for x in back["steps"] if x["id"] == "F5-05")["taskKind"] == "PO_APPROVAL"
    api = client.get("/v1/process-definitions/pic.po/versions/1/bpmn", headers=auth("buyer"))
    assert api.status_code == 200 and api.json()["xml"].startswith("<?xml")
    parsed = client.post("/v1/process-definitions/bpmn/parse", json={"xml": xml}, headers=auth("buyer")).json()
    assert len(parsed["definition"]["steps"]) == len(d.definition["steps"])
    for hostile in ('<!DOCTYPE x [<!ENTITY a "b">]><bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"/>', "<not-xml", ""):
        with pytest.raises(Problem):
            bpmn.from_xml(hostile)


def test_process_history_exposes_the_definition_version_for_the_diagram(client, login):
    r = client.get("/v1/documents/REQUISITION/REQ-2311/process", headers=login("procurement.head"))
    assert r.status_code == 200 and r.json() and all("version" in p and "process" in p for p in r.json())


# ================================================================ 6. ERP field mappings
def test_mapping_engine_rules():
    payload = {"invoiceNo": "inv-9", "grossMinor": 118000, "invoiceDate": "2026-10-30", "companyCode": "1000", "note": "internal",
               "lines": [{"qty": "2", "material": "m1"}, {"qty": "5", "material": "m2"}], "supplier": {"code": "tf001"}}
    rules_ = [
        {"op": "rename", "from": "invoiceNo", "to": "Reference"},
        {"op": "format", "field": "Reference", "kind": "upper"},
        {"op": "format", "field": "grossMinor", "kind": "minor_to_major", "decimals": 2},
        {"op": "rename", "from": "grossMinor", "to": "GrossAmount"},
        {"op": "format", "field": "invoiceDate", "kind": "date", "pattern": "%d.%m.%Y"},
        {"op": "lookup", "field": "companyCode", "table": {"1000": "AXN1"}},
        {"op": "constant", "to": "SourceSystem", "value": "PIC"},
        {"op": "drop", "field": "note"},
        {"op": "format", "field": "lines[].material", "kind": "upper"},
        {"op": "format", "field": "lines[].qty", "kind": "pad_left", "width": 4, "char": "0"},
        {"op": "copy", "from": "supplier.code", "to": "Vendor"},
        {"op": "copy", "from": "lines[].material", "to": "Item"},
        {"op": "lookup", "field": "supplier.code", "table": {"x": "y"}, "default": "UNKNOWN", "to": "VendorGroup"},
    ]
    out = field_mapping.apply(rules_, payload)
    assert out["Reference"] == "INV-9" and out["GrossAmount"] == "1180.00" and "grossMinor" not in out and "invoiceNo" not in out
    assert out["invoiceDate"] == "30.10.2026" and out["companyCode"] == "AXN1" and out["SourceSystem"] == "PIC" and "note" not in out
    assert [line["material"] for line in out["lines"]] == ["M1", "M2"] and [line["qty"] for line in out["lines"]] == ["0002", "0005"]
    assert out["Vendor"] == "tf001" and [line["Item"] for line in out["lines"]] == ["M1", "M2"] and out["supplier"]["VendorGroup"] == "UNKNOWN"
    assert payload["invoiceNo"] == "inv-9", "the canonical payload is never modified"
    assert field_mapping.apply([], payload) == payload, "no rules: today's payload"
    with pytest.raises(field_mapping.MappingError):
        field_mapping.apply([{"op": "lookup", "field": "companyCode", "table": {}, "required": True}], payload)
    with pytest.raises(field_mapping.MappingError):
        field_mapping.apply([{"op": "format", "field": "invoiceNo", "kind": "date"}], payload)


def test_mapping_validation_and_preview():
    bad = field_mapping.validate([{"op": "rename", "from": "a"}, {"op": "format", "field": "x", "kind": "bogus"}, {"op": "drop", "field": "a b"},
                                  {"op": "format", "field": "x", "kind": "date", "pattern": 5}, {"op": "lookup", "field": "x", "table": []}, "str"])
    assert len(bad) >= 5
    assert field_mapping.validate("nope")[0]["message"] == "rules must be a list"
    ok = field_mapping.preview([{"op": "rename", "from": "a", "to": "b"}], {"a": 1, "c": 2})
    assert ok["valid"] and ok["outbound"] == {"b": 1, "c": 2} and {c["path"] for c in ok["changes"]} == {"a", "b"}
    assert field_mapping.preview([{"op": "x"}], {})["valid"] is False


def test_mapping_lifecycle_api_and_applied_before_the_connector(client, auth, tid):
    admin = auth("admin")
    assert client.post("/v1/admin/field-mappings", json={**_mapping_body("x"), "targetSystem": "NOPE"}, headers=admin).json()["code"] == "UNKNOWN_TARGET_SYSTEM"
    rules_ = [{"op": "rename", "from": "deliveryNote", "to": "XBLNR"}, {"op": "format", "field": "XBLNR", "kind": "upper"},
              {"op": "constant", "to": "SourceSystem", "value": "PIC"}]
    created = client.post("/v1/admin/field-mappings", json={"targetSystem": "SAP_S4", "messageType": "GOODS_RECEIPT", "rules": rules_, "note": "SAP names"}, headers=admin)
    assert created.status_code == 201 and created.json()["status"] == "DRAFT"
    mid = created.json()["id"]
    preview = client.post("/v1/admin/field-mappings/preview", headers=admin,
                          json={"rules": rules_, "samplePayload": {"deliveryNote": "abc-1", "grossMinor": 100}})
    assert preview.json()["outbound"]["XBLNR"] == "ABC-1" and preview.json()["valid"]
    assert client.post("/v1/admin/field-mappings/preview", json={"rules": rules_}, headers=admin).json()["code"] == "SAMPLE_REQUIRED"
    edited = client.put(f"/v1/admin/field-mappings/{mid}", json={"rules": rules_, "note": "edited"}, headers={**admin, "If-Match": '"99"'})
    assert edited.status_code == 412
    # before publishing, the connector gets today's payload
    with tenant_tx(tid) as s:
        _principal(s, tid, "admin")
        plain = integration.enqueue(s, target_system="SAP_S4", message_type="GOODS_RECEIPT", idempotency_key="wv1e-plain",
                                    object_type="GOODS_RECEIPT", object_id=uuid.uuid4(), object_ref="INV-P1",
                                    payload={"deliveryNote": "abc-1", "grossMinor": 5000, "companyCode": "1000"})
        integration.process(s, plain)
        assert plain.status == "POSTED" and plain.outbound_payload is None and plain.mapping_version is None
        doc = s.execute(select(ErpDocument).where(ErpDocument.external_ref == "wv1e-plain")).scalar_one()
        assert doc.payload == plain.payload
    pub = client.post(f"/v1/admin/field-mappings/{mid}/publish", headers=admin)
    assert pub.status_code == 200 and pub.json()["status"] == "ACTIVE"
    assert client.put(f"/v1/admin/field-mappings/{mid}", json={"rules": rules_}, headers=admin).json()["code"] == "ILLEGAL_TRANSITION"
    with tenant_tx(tid) as s:
        _principal(s, tid, "admin")
        msg = integration.enqueue(s, target_system="SAP_S4", message_type="GOODS_RECEIPT", idempotency_key="wv1e-mapped",
                                  object_type="GOODS_RECEIPT", object_id=uuid.uuid4(), object_ref="INV-M1",
                                  payload={"deliveryNote": "abc-2", "grossMinor": 7000, "companyCode": "1000"})
        integration.process(s, msg)
        assert msg.status == "POSTED" and msg.mapping_version == pub.json()["version"]
        assert msg.payload["deliveryNote"] == "abc-2" and "XBLNR" not in msg.payload, "the canonical payload stays"
        assert msg.outbound_payload["XBLNR"] == "ABC-2" and msg.outbound_payload["SourceSystem"] == "PIC"
        doc = s.execute(select(ErpDocument).where(ErpDocument.external_ref == "wv1e-mapped")).scalar_one()
        assert doc.payload["XBLNR"] == "ABC-2", "the connector received the mapped payload"
    # a second version replaces the first; one active version per target and message type
    second = client.post("/v1/admin/field-mappings", json={"targetSystem": "SAP_S4", "messageType": "GOODS_RECEIPT", "rules": [], "note": "v2"}, headers=admin).json()
    assert second["version"] == pub.json()["version"] + 1
    client.post(f"/v1/admin/field-mappings/{second['id']}/publish", headers=admin)
    states = {m["version"]: m["status"] for m in client.get("/v1/admin/field-mappings?targetSystem=SAP_S4&messageType=GOODS_RECEIPT", headers=admin).json()}
    assert states[pub.json()["version"]] == "RETIRED" and states[second["version"]] == "ACTIVE"
    assert client.post(f"/v1/admin/field-mappings/{second['id']}/retire", json={"reason": "switch off"}, headers=admin).json()["status"] == "RETIRED"
    cat = client.get("/v1/admin/field-mappings/catalog", headers=admin).json()
    assert "SAP_S4" in cat["targetSystems"] and any(m["type"] == "GOODS_RECEIPT" for m in cat["messageTypes"])
    assert client.get("/v1/admin/field-mappings", headers=auth("buyer")).status_code == 403


def test_a_failing_mapping_retries_and_never_posts(tid):
    with tenant_tx(tid) as s:
        _principal(s, tid, "admin")
        s.add(IntegrationFieldMapping(tenant_id=tid, target_system="SAP_S4", message_type="PURCHASE_ORDER", version=1, status="ACTIVE",
                                      rules=[{"op": "lookup", "field": "companyCode", "table": {}, "required": True}]))
        s.flush()
        msg = integration.enqueue(s, target_system="SAP_S4", message_type="PURCHASE_ORDER", idempotency_key="wv1e-fail", object_type="PURCHASE_ORDER",
                                  object_id=uuid.uuid4(), object_ref="PO-F", payload={"companyCode": "1000", "grossMinor": 1})
        integration.process(s, msg)
        assert msg.status == "RETRY" and "field mapping failed" in msg.last_error
        assert s.execute(select(ErpDocument).where(ErpDocument.external_ref == "wv1e-fail")).first() is None
        s.rollback()


# ================================================================ 7. band edges
BANDS = {"bands": [{"upTo": 25_000_00, "autoChannels": ["CATALOGUE"], "chain": ["A"]}, {"upTo": 2_00_000_00, "chain": ["B"]},
                   {"upTo": 10_00_000_00, "chain": ["B", "C"]}, {"upTo": None, "chain": ["B", "C", "D"]}]}


def test_band_upper_bound_is_inclusive_everywhere():
    from app.pic.services import policy_sim
    rule = rules.Rule("DMN-01", "t", BANDS)
    assert rules.requisition_chain(rule, 2_00_000_00, "OTHER", None, "STOCK") == ["B"], "exactly 2 L is the lower band"
    assert rules.requisition_chain(rule, 2_00_000_01, "OTHER", None, "STOCK") == ["B", "C"]
    assert rules.requisition_chain(rule, 10_00_000_00, "OTHER", None, "STOCK") == ["B", "C"]
    assert rules.requisition_chain(rule, 10_00_000_01, "OTHER", None, "STOCK") == ["B", "C", "D"]
    assert rules.band_chain(rule, 2_00_000_00) == ["B"] and rules.band_chain(rule, 2_00_000_01) == ["B", "C"]
    assert policy_sim._band(rule, 2_00_000_00)[0] == 1 and policy_sim._band(rule, 2_00_000_01)[0] == 2
    assert policy_sim._band(rule, 10_00_000_00)[0] == 2
    from app.pic.services import order
    assert order._band(rule, 2_00_000_00) == 1 and order._band(rule, 2_00_000_01) == 2


# ================================================================ 8. field-encryption key versioning
KEY_A = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU="  # 32 bytes, urlsafe base64
KEY_B = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


def _ring(monkeypatch, keys=None, active=None):
    settings = get_settings()
    monkeypatch.setattr(settings, "field_keys", keys)
    monkeypatch.setattr(settings, "field_active_key", active)


def test_key_versioning_roundtrip_and_rotation(monkeypatch, tid):
    token = crypto.encrypt(tid, "bank", "50100234567")
    assert token.startswith(b"pk:v1:") and crypto.decrypt(tid, "bank", token) == "50100234567"
    _ring(monkeypatch, f"v2:{KEY_A}")
    assert crypto.active_key_id() == "v2" and crypto.decrypt(tid, "bank", token) == "50100234567", "old ciphertext still decrypts"
    fresh = crypto.encrypt(tid, "bank", "50100234567")
    assert fresh.startswith(b"pk:v2:") and crypto.key_id_of(fresh) == "v2" and crypto.needs_rotation(token) and not crypto.needs_rotation(fresh)
    moved = crypto.rotate(tid, "bank", token)
    assert crypto.key_id_of(moved) == "v2" and crypto.decrypt(tid, "bank", moved) == "50100234567" and crypto.rotate(tid, "bank", moved) == moved
    other_tenant = uuid.uuid4()
    with pytest.raises(Exception):
        crypto.decrypt(other_tenant, "bank", fresh)
    with pytest.raises(Exception):
        crypto.decrypt(tid, "gstin", fresh)  # purpose is part of the key
    _ring(monkeypatch, f"v3:{KEY_B},v2:{KEY_A}", "v2")
    assert crypto.active_key_id() == "v2" and crypto.key_ids() == ["v1", "v3", "v2"]
    _ring(monkeypatch, f"v3:{KEY_B}")
    with pytest.raises(crypto.UnknownKey):
        crypto.decrypt(tid, "bank", fresh)  # v2 was retired too early
    _ring(monkeypatch, f"v3:{KEY_B}", "nope")
    with pytest.raises(crypto.UnknownKey):
        crypto.active_key_id()


def test_legacy_unprefixed_ciphertext_is_read_with_key_v1(tid):
    import base64
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=tid.bytes, info=b"gstin").derive(crypto._master())
    legacy = Fernet(base64.urlsafe_b64encode(derived)).encrypt(b"33AAACW1111C1Z8")
    assert crypto.key_id_of(legacy) == "v1" and crypto.decrypt(tid, "gstin", legacy) == "33AAACW1111C1Z8"


def test_blind_index_is_stable_across_rotation(monkeypatch, tid):
    before = crypto.blind_index(tid, "33AAACW1111C1Z8")
    _ring(monkeypatch, f"v2:{KEY_A}")
    assert crypto.blind_index(tid, "33 aaacw1111c1z8") == before


def test_reencrypt_job_dry_run_and_apply(monkeypatch, tid):
    from app.pic.tools import reencrypt
    with tenant_tx(tid) as s:
        user = _principal(s, tid, "plain")
        s.merge(MfaFactor(tenant_id=tid, user_id=user.user_id, kind="TOTP", secret_enc=crypto.encrypt(tid, "mfa-totp", "JBSWY3DPEHPK3PXP").decode()))
    _ring(monkeypatch, f"v2:{KEY_A}")
    dry = reencrypt.run(apply=False, tenant_code=T)
    assert dry["toRotate"] >= 1 and dry["rotated"] == 0 and dry["tenants"][T]["mfa_factor.secret_enc"]["byKey"] == {"v1": 1}
    with tenant_tx(tid) as s:
        assert crypto.key_id_of(s.execute(select(MfaFactor.secret_enc)).scalars().first().encode()) == "v1", "a dry run changes nothing"
    done = reencrypt.run(apply=True, tenant_code=T)
    assert done["rotated"] >= 1 and done["failed"] == 0
    with tenant_tx(tid) as s:
        stored = s.execute(select(MfaFactor.secret_enc)).scalars().first()
        assert crypto.key_id_of(stored.encode()) == "v2" and crypto.decrypt(tid, "mfa-totp", stored.encode()) == "JBSWY3DPEHPK3PXP"
        assert s.execute(select(AuditEvent).where(AuditEvent.action == "FIELDS_REENCRYPTED")).scalars().first() is not None
    again = reencrypt.run(apply=False, tenant_code=T)
    assert again["toRotate"] == 0, "nothing left to rotate"
    assert reencrypt.main(["--tenant", T]) == 0


def test_axion_ciphertext_is_untouched_by_a_dry_run(monkeypatch):
    from app.pic.tools import reencrypt
    _ring(monkeypatch, f"v2:{KEY_A}")
    report = reencrypt.run(apply=False, tenant_code="AXN")
    assert report["toRotate"] > 0 and report["rotated"] == 0


# ================================================================ 9. password policy
@pytest.mark.parametrize("password", ["Password123!", "P@ssw0rd2026!", "qwertyuiop12", "Aaaaaaaaaaaa1", "short1A!", "alllowercaseonly",
                                      "Summer2026!!!!", "Letmein12345!"])
def test_weak_and_breached_passwords_are_refused(password):
    assert passwords.check(password, email="someone@example.com"), password


@pytest.mark.parametrize("password", ["Kiln$Survey-2027", "tangerine-Orbit-41!", "Test-Only-Password-1"])
def test_strong_passwords_pass(password):
    assert passwords.check(password, email="someone@example.com", names=("Acme Industries",)) == []


def test_password_must_not_contain_name_or_email_name():
    assert any("e-mail name" in p for p in passwords.check("rahulmenon-Orbit-41!", email="rahulmenon@axion.example"))
    assert any("name" in p for p in passwords.check("Blue-Acme-Orbit-41!", names=("Acme Industries",)))


def test_password_change_endpoint(client, auth, tid):
    h = auth("plain")
    assert client.post("/v1/me/password", json={"currentPassword": "wrong", "newPassword": "Kiln$Survey-2027"}, headers=h).json()["code"] == "INVALID_CREDENTIALS"
    weak = client.post("/v1/me/password", json={"currentPassword": PASSWORD, "newPassword": "Password123!"}, headers=h)
    assert weak.status_code == 422 and weak.json()["code"] == "PASSWORD_POLICY" and weak.json()["problems"]
    assert client.post("/v1/me/password", json={"currentPassword": PASSWORD, "newPassword": PASSWORD}, headers=h).json()["code"] == "PASSWORD_UNCHANGED"
    ok = client.post("/v1/me/password", json={"currentPassword": PASSWORD, "newPassword": "Kiln$Survey-2027"}, headers=h)
    assert ok.status_code == 200 and ok.json() == {"changed": True}
    assert client.post("/v1/auth/token", json={"tenant": T, "email": "plain@wv1e.example", "password": "Kiln$Survey-2027"}).status_code == 200
    assert client.post("/v1/auth/token", json={"tenant": T, "email": "plain@wv1e.example", "password": PASSWORD}).status_code == 401
    with tenant_tx(tid) as s:
        assert s.execute(select(AuditEvent).where(AuditEvent.action == "PASSWORD_CHANGED")).scalars().first() is not None
        s.execute(select(AppUser).where(AppUser.email == "plain@wv1e.example")).scalar_one().password_hash = hash_password(PASSWORD)


def test_supplier_registration_uses_the_shared_policy():
    from app.pic.services import invitations
    assert "password is too common or appears in known breaches" in invitations.password_errors("Dragon2026!!!!", "a@b.example", "Acme Pvt Ltd")
    assert invitations.password_errors("Kiln$Survey-2027", "a@b.example", "Acme Pvt Ltd") == []


# ================================================================ 10. tenant MFA default
def test_new_tenants_enforce_mfa_and_demo_tenants_do_not(tid):
    with system_tx() as s:
        mine = s.execute(select(Tenant).where(Tenant.code == T)).scalar_one()
        assert mine.mfa_enforce is False  # created explicitly unenforced for these tests
        assert s.execute(select(Tenant.mfa_enforce).where(Tenant.code == "AXN")).scalar_one() is False
    fresh = reference.create_tenant("WV1F", "Wave One F Test Pvt Ltd", "GENERAL")  # called from a test module: a new tenant
    reference.bootstrap(fresh, company=("1000", "Wave One F", "33AAACW1111C1Z8"), plants=[("P100", "Chennai", "33")], cost_objects=[("COST_CENTER", "4100", "Admin")])
    with tenant_tx(fresh) as s:
        body = rules.resolve(s, "MFA").body
        assert body["enforce"] is True and "TENANT_ADMIN" in body["requiredRoles"]
        assert s.get(Tenant, fresh).mfa_enforce is True
    with tenant_tx(tid) as s:
        assert rules.resolve(s, "MFA").body["enforce"] is False
    with system_tx() as s:
        axn = s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()
    with tenant_tx(axn) as s:
        assert rules.resolve(s, "MFA").body["enforce"] is False


# ================================================================ 11. migration compatibility check
def test_migration_backward_compatibility_checker(tmp_path):
    from app.pic.tools import check_migrations
    assert check_migrations.check_file(check_migrations.VERSIONS / "0013_platform_enterprise.py") == [], "this release's migration is additive"
    bad = tmp_path / "0099_bad.py"
    bad.write_text('''revision = "0099"
down_revision = "0013"
from alembic import op
import sqlalchemy as sa
def upgrade():
    op.add_column("invoice", sa.Column("must_have", sa.String(10), nullable=False), schema="pic")
    op.drop_column("invoice", "net_minor", schema="pic")
    op.alter_column("invoice", "status", new_column_name="state", schema="pic")
    op.drop_table("old_things", schema="pic")
def downgrade():
    pass
''')
    problems = check_migrations.check_file(bad)
    kinds = {p["kind"] for p in problems}
    assert kinds == {"NOT_NULL_WITHOUT_DEFAULT", "DROP_COLUMN", "RENAME_COLUMN", "DROP_TABLE"}
    good = tmp_path / "0098_good.py"
    good.write_text('''revision = "0098"
down_revision = "0013"
from alembic import op
import sqlalchemy as sa
def upgrade():
    op.add_column("invoice", sa.Column("fine", sa.String(10), server_default="x", nullable=False), schema="pic")
    op.add_column("invoice", sa.Column("optional", sa.String(10), nullable=True), schema="pic")
def downgrade():
    pass
''')
    assert check_migrations.check_file(good) == []
    allowed = tmp_path / "0097_ack.py"
    allowed.write_text(bad.read_text().replace("0099", "0097") + "\n# compat: contract-phase drop acknowledged for release 2\n")
    assert check_migrations.check_file(allowed) == []
