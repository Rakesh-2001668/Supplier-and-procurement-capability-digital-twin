"""Notifications, ERP planned-order import, ERP connector registry, TOTP MFA and OIDC single sign-on."""
import base64
import hashlib
import json
import time
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuditEvent, MfaFactor, Notification, OutboxEvent, PlannedOrder, RuleSet, Task, Tenant, Timer,
)
from app.pic.platform import clock, connectors, http, integration, mfa, oidc, outbox, workflow
from app.pic.platform.auth import Principal, hash_password, scopes_for
from app.pic.seed import reference
from tests.pic.conftest import PASSWORD

DOMAIN = "axion.example"


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    """Wrong codes and failed SSO attempts count towards the per-IP sign-in throttle; keep later tests unaffected."""
    yield
    http._login_attempts.clear()


def _tenant_id(code: str = "AXN") -> uuid.UUID:
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == code)).scalar_one()


def _user(session, email: str) -> AppUser:
    return session.execute(select(AppUser).where(AppUser.email == email)).scalar_one()


def _as(session, email: str) -> Principal:
    user = _user(session, email)
    p = Principal(user.id, user.tenant_id, "AXN", user.email, user.full_name, list(user.roles), scopes_for(list(user.roles)),
                  user.attributes or {}, user.supplier_id)
    session.info["principal"], session.info["user_id"] = p, user.id
    return p


def _ensure_user(tenant_id, email: str, roles: list[str], attributes: dict) -> uuid.UUID:
    with tenant_tx(tenant_id) as s:
        user = s.execute(select(AppUser).where(AppUser.email == email)).scalar_one_or_none()
        if user is None:
            user = AppUser(tenant_id=tenant_id, email=email, full_name=email.split("@")[0].replace(".", " ").title(),
                           password_hash=hash_password(PASSWORD), roles=roles, attributes=attributes)
            s.add(user)
            s.flush()
        return user.id


def _relay(tenant_id) -> None:
    outbox.relay_tenant(tenant_id)


# ---------------------------------------------------------------- notifications
@pytest.fixture(scope="module")
def approval_task():
    """A cost-object approval task (COST_CENTER:4100) with one four-eyes exclusion; cancelled afterwards."""
    axn = _tenant_id()
    excluded = _ensure_user(axn, f"coo.excluded@{DOMAIN}", ["COST_OBJECT_OWNER"], {"cost_objects": ["COST_CENTER:4100"], "plants": ["P100"]})
    _ensure_user(axn, f"coo.other@{DOMAIN}", ["COST_OBJECT_OWNER"], {"cost_objects": ["COST_CENTER:9999"], "plants": ["P100"]})
    with tenant_tx(axn) as s:
        p = _as(s, f"requester@{DOMAIN}")
        tasks = workflow.start_approval(s, None, "TEST_APPROVAL", object_type="REQUISITION", object_id=uuid.uuid4(),
                                        object_ref="REQ-NTF-1", chain=["COST_OBJECT_OWNER"], step_id=None, initiator_id=p.user_id,
                                        scopes={"COST_OBJECT_OWNER": {"cost_object": "COST_CENTER:4100"}}, exclude=[excluded])
        task_id = tasks[0].id
    _relay(axn)
    yield task_id
    with tenant_tx(axn) as s:
        task = s.get(Task, task_id)
        task.status = "CANCELLED"
        workflow._cancel_timers(s, "TASK_SLA", task_id)


def _notes(email: str, dedup_prefix: str) -> list[Notification]:
    with tenant_tx(_tenant_id()) as s:
        user = _user(s, email)
        return list(s.execute(select(Notification).where(Notification.user_id == user.id, Notification.dedup_key.like(f"{dedup_prefix}%")))
                    .scalars())


def test_task_notification_reaches_eligible_users_only(approval_task):
    key = f"TASK_ASSIGNED:{approval_task}"
    mine = _notes(f"plant.controller@{DOMAIN}", key)
    assert len(mine) == 1 and mine[0].kind == "TASK_ASSIGNED" and mine[0].object_ref == "REQ-NTF-1"
    assert mine[0].link == "/pic/requisitions/REQ-NTF-1"
    assert mine[0].email_status == "DISABLED"  # NOTIFICATIONS.email is false and SMTP is not configured
    assert _notes(f"coo.excluded@{DOMAIN}", key) == []  # four-eyes exclusion
    assert _notes(f"coo.other@{DOMAIN}", key) == []  # different cost object
    assert _notes(f"requester@{DOMAIN}", key) == []  # initiator, and not the candidate role


def test_task_notifications_are_deduplicated(approval_task):
    axn = _tenant_id()
    with tenant_tx(axn) as s:
        _as(s, f"requester@{DOMAIN}")
        task = s.get(Task, approval_task)
        outbox.emit(s, "task.assigned", "TASK", task.id, task.object_ref, {"taskId": str(task.id)})  # a duplicate delivery
    _relay(axn)
    assert len(_notes(f"plant.controller@{DOMAIN}", f"TASK_ASSIGNED:{approval_task}")) == 1


def test_escalation_notifies_task_workers(approval_task):
    axn = _tenant_id()
    with tenant_tx(axn) as s:
        _as(s, f"requester@{DOMAIN}")
        timer = s.execute(select(Timer).where(Timer.kind == "TASK_SLA", Timer.object_id == approval_task, Timer.fired_at.is_(None))).scalar_one()
        timer.fired_at = clock.now()
        workflow._task_sla(s, timer)
    _relay(axn)
    escalated = _notes(f"plant.controller@{DOMAIN}", f"TASK_ESCALATED:{approval_task}:")
    assert len(escalated) == 1 and "escalation 1" in escalated[0].title
    assert _notes(f"coo.excluded@{DOMAIN}", f"TASK_ESCALATED:{approval_task}") == []


def test_notification_inbox_read_and_read_all(client, login, approval_task):
    headers = login("plant.controller")
    listing = client.get("/v1/notifications?unread=true", headers=headers).json()
    assert listing["unread"] >= 2 and any(n["object_ref"] == "REQ-NTF-1" for n in listing["items"])
    first = next(n for n in listing["items"] if n["object_ref"] == "REQ-NTF-1")
    r = client.post(f"/v1/notifications/{first['id']}/read", headers=headers)
    assert r.status_code == 200 and r.json()["read_at"]
    count = client.get("/v1/notifications/unread-count", headers=headers).json()["unread"]
    assert count == listing["unread"] - 1
    # Someone else cannot read (or even see) my notification.
    assert client.post(f"/v1/notifications/{first['id']}/read", headers=login("buyer")).status_code == 404
    assert client.post("/v1/notifications/read-all", headers=headers).json()["updated"] == count
    assert client.get("/v1/notifications/unread-count", headers=headers).json()["unread"] == 0
    assert client.get("/v1/notifications?unread=false", headers=headers).json()["items"]


def test_recommendation_notifies_candidate_role():
    axn = _tenant_id()
    with tenant_tx(axn) as s:
        _as(s, f"supplier.manager@{DOMAIN}")
        from app.pic.platform import agents
        rec = agents.recommend(s, "SUPPLIER_RISK", object_type="SUPPLIER", object_id=uuid.uuid4(), object_ref="TF001",
                               dedup_key=f"test-ntf-{uuid.uuid4().hex[:8]}", title="Review risk signal", rationale="Test signal",
                               proposal={"action": "review"}, candidate_role="SUPPLIER_MANAGER", deep_link="/pic/suppliers/risk")
        assert rec is not None
        rec_id = rec.id
        assert s.execute(select(OutboxEvent).where(OutboxEvent.topic == "agent.recommendation.created",
                                                   OutboxEvent.object_id == rec_id)).scalar_one()
    _relay(axn)
    notes = _notes(f"supplier.manager@{DOMAIN}", f"RECOMMENDATION:{rec_id}")
    assert len(notes) == 1 and notes[0].link == "/pic/suppliers/risk" and notes[0].kind == "RECOMMENDATION"


# ---------------------------------------------------------------- ERP planned-order import (AD-05)
def _rows(prefix: str):
    need = (clock.today() + timedelta(days=40)).isoformat()
    return [
        {"externalRef": f"{prefix}-1", "material": "DC-330", "plant": "P200", "qty": 400, "needDate": need},
        {"externalRef": f"{prefix}-2", "material": "NOPE-1", "plant": "P200", "qty": 10, "needDate": need},
        {"externalRef": f"{prefix}-3", "material": "DC-331", "plant": "P200", "qty": 0, "needDate": need},
        {"externalRef": f"{prefix}-4", "material": "DC-331", "plant": "P999", "qty": 5, "needDate": need},
        {"externalRef": f"{prefix}-5", "material": "DC-331", "plant": "P200", "qty": 5, "needDate": "31/12/2026"},
        {"externalRef": f"{prefix}-1", "material": "DC-331", "plant": "P200", "qty": 5, "needDate": need},
        {"externalRef": f"{prefix}-7", "material": "DC-331", "plant": "P200", "qty": 5, "needDate": need,
         "releaseDate": (clock.today() + timedelta(days=60)).isoformat()},
        {"externalRef": f"{prefix}-8", "material": "DC-331", "plant": "P200", "qty": "2000", "needDate": need, "supplier": "KD002"},
    ]


@pytest.fixture(scope="module")
def imported(client, login):
    r = client.post("/v1/integration/planned-orders/import", headers=login("admin"),
                    json={"system": "SAP_S4", "batchRef": "MD01-TEST-001", "rows": _rows("PLO-EXT")})
    assert r.status_code == 201, r.text
    return r.json()


def test_import_validates_each_row(imported):
    assert imported["accepted"] == 2 and imported["rejected"] == 6 and imported["number"].startswith("IB-")
    errors = {r["row"]: r.get("error", "") for r in imported["results"] if r["status"] == "REJECTED"}
    assert "does not exist" in errors[2] and "greater than 0" in errors[3] and "plant P999" in errors[4]
    assert "ISO date" in errors[5] and "more than once" in errors[6] and "after needDate" in errors[7]
    accepted = [r for r in imported["results"] if r["status"] == "ACCEPTED"]
    assert all(r["plannedOrder"] and r["mrpRun"] for r in accepted) and len(imported["mrpRuns"]) == 1


def test_import_is_idempotent_per_batch_ref(client, login, imported):
    again = client.post("/v1/integration/planned-orders/import", headers=login("admin"),
                        json={"system": "SAP_S4", "batchRef": "MD01-TEST-001", "rows": _rows("PLO-EXT")})
    assert again.status_code == 200 and again.json()["replayed"] is True and again.json()["number"] == imported["number"]
    conflict = client.post("/v1/integration/planned-orders/import", headers=login("admin"),
                           json={"system": "SAP_S4", "batchRef": "MD01-TEST-001", "rows": _rows("PLO-OTHER")})
    assert conflict.status_code == 409 and conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    # The same external reference in a new batch is rejected as already imported.
    dup = client.post("/v1/integration/planned-orders/import", headers=login("admin"),
                      json={"system": "SAP_S4", "batchRef": "MD01-TEST-002", "rows": _rows("PLO-EXT")[:1]})
    assert dup.status_code == 201 and dup.json()["accepted"] == 0 and "already imported" in dup.json()["results"][0]["error"]


def test_import_permissions_and_plant_scope(client, login):
    rows = _rows("PLO-SCOPE")[:1]
    assert client.post("/v1/integration/planned-orders/import", headers=login("requester"),
                       json={"system": "SAP_S4", "batchRef": "X-1", "rows": rows}).status_code == 403
    r = client.post("/v1/integration/planned-orders/import", headers=login("mrp.controller"),
                    json={"system": "SAP_S4", "batchRef": "MRPC-SCOPE-1", "rows": rows})
    assert r.status_code == 201 and r.json()["accepted"] == 0 and "not assigned to plant P200" in r.json()["results"][0]["error"]
    bad = client.post("/v1/integration/planned-orders/import", headers=login("admin"), json={"system": "SAGE", "batchRef": "X", "rows": rows})
    assert bad.status_code == 422 and bad.json()["code"] == "UNKNOWN_SOURCE_SYSTEM"


def test_imported_orders_use_the_existing_mrp_flow(client, login, imported):
    numbers = [r["plannedOrder"] for r in imported["results"] if r["status"] == "ACCEPTED"]
    run = client.get(f"/v1/mrp/runs/{imported['mrpRuns'][0]}", headers=login("mrp.controller")).json()
    assert run["mode"] == "ERP_IMPORT" and run["status"] == "COMPLETED" and run["planned_orders_created"] == 2
    order = next(o for o in run["plannedOrders"] if o["number"] == numbers[0])
    assert order["source_system"] == "SAP_S4" and order["external_ref"] == "PLO-EXT-1" and order["status"] == "CREATED"
    assert run["process"]["currentStep"] == "F1-07"
    headers = login("mrp.controller")
    firmed = client.post(f"/v1/planned-orders/{numbers[0]}/firm", headers=headers)
    assert firmed.status_code == 200 and firmed.json()["status"] == "FIRMED"
    pr = client.post(f"/v1/planned-orders/{numbers[0]}/convert", headers=headers)
    assert pr.status_code == 200, pr.text
    assert pr.json()["origin"] == "MRP" and pr.json()["origin_ref"] == numbers[0]
    with tenant_tx(_tenant_id()) as s:
        assert s.execute(select(PlannedOrder.status).where(PlannedOrder.number == numbers[0])).scalar() == "CONVERTED"


def test_import_csv_and_batch_list(client, login):
    need = (clock.today() + timedelta(days=45)).isoformat()
    content = f"External Ref;Material;Plant;Qty;Need Date\nCSV-1;FK-M8-50;P200;1000;{need}\nCSV-2;FK-M8-50;P200;-1;{need}\n"
    r = client.post("/v1/integration/planned-orders/import/csv?system=ODOO&batchRef=CSV-TEST-1", headers={**login("admin"),
                    "content-type": "text/csv"}, content=content.encode())
    assert r.status_code == 201, r.text
    assert r.json()["accepted"] == 1 and r.json()["rejected"] == 1 and r.json()["sourceSystem"] == "ODOO"
    multi = client.post("/v1/integration/planned-orders/import/csv", headers=login("admin"),
                        data={"system": "ODOO", "batchRef": "CSV-TEST-2"},
                        files={"file": ("plan.csv", f"externalRef,material,plant,qty,needDate\nCSV-3,FK-M8-50,P200,250,{need}\n", "text/csv")})
    assert multi.status_code == 201, multi.text
    assert multi.json()["accepted"] == 1
    missing = client.post("/v1/integration/planned-orders/import/csv?system=ODOO&batchRef=CSV-TEST-3",
                          headers={**login("admin"), "content-type": "text/csv"}, content=b"material,qty\nX,1\n")
    assert missing.status_code == 422 and missing.json()["code"] == "CSV_HEADER"
    listing = client.get("/v1/integration/batches?kind=PLANNED_ORDERS", headers=login("admin")).json()
    refs = {b["batchRef"] for b in listing["items"]}
    assert {"MD01-TEST-001", "CSV-TEST-1", "CSV-TEST-2"} <= refs
    detail = client.get(f"/v1/integration/batches/{r.json()['number']}", headers=login("admin")).json()
    assert len(detail["results"]) == 2


# ---------------------------------------------------------------- ERP connector registry (TD §12.1)
def test_connector_registry_status(client, login):
    r = client.get("/v1/admin/connectors", headers=login("admin"))
    assert r.status_code == 200
    by_system = {c["system"]: c for c in r.json()["connectors"]}
    assert set(by_system) == {"SAP_S4", "ORACLE_FUSION", "DYNAMICS_365", "TALLY_PRIME", "ODOO"}
    assert by_system["SAP_S4"]["configured"] and by_system["SAP_S4"]["healthy"] and by_system["SAP_S4"]["total"] > 0
    assert not by_system["ORACLE_FUSION"]["configured"] and "PIC_ERP_ORACLE_FUSION_URL" in by_system["ORACLE_FUSION"]["missing"]
    assert all(not item["present"] for item in by_system["DYNAMICS_365"]["configuration"])
    test = client.post("/v1/admin/connectors/ORACLE_FUSION/test", headers=login("admin")).json()
    assert test["healthy"] is False and "not configured" in test["detail"]
    assert client.post("/v1/admin/connectors/SAGE/test", headers=login("admin")).status_code == 404
    assert client.get("/v1/admin/connectors", headers=login("buyer")).status_code == 403


class _Rollback(Exception):
    pass


def test_not_configured_connector_retries_then_dead_letters(monkeypatch):
    monkeypatch.setattr(integration, "_on_posted", {})  # no domain callbacks for the synthetic SAP message below
    with pytest.raises(_Rollback):
        with tenant_tx(_tenant_id()) as s:
            _as(s, f"admin@{DOMAIN}")
            message = integration.enqueue(s, target_system="ORACLE_FUSION", message_type="SUPPLIER_INVOICE", idempotency_key="TEST|INV|1",
                                          object_type="INVOICE", object_id=uuid.uuid4(), object_ref="INV-T1",
                                          payload={"invoice": "T1", "supplier": "TF001", "companyCode": "1000", "grossMinor": 100})
            integration.process(s, message)
            assert message.status == "RETRY" and "not configured" in message.last_error
            for _ in range(integration.MAX_ATTEMPTS - 1):
                integration.process(s, message)
            assert message.status == "DEAD_LETTER" and message.attempts == integration.MAX_ATTEMPTS
            # The SAP simulator still posts (and query-before-retry still acknowledges) in the same transaction.
            sap = integration.enqueue(s, target_system="SAP_S4", message_type="MATERIAL_MASTER", idempotency_key="TEST|MAT|1",
                                      object_type="MATERIAL", object_id=uuid.uuid4(), object_ref="TEST-MAT",
                                      payload={"material": "TEST-MAT"})
            integration.process(s, sap)
            assert sap.status == "POSTED" and sap.erp_doc_no
            assert connectors.get("SAP_S4").find(s, sap).doc_no == sap.erp_doc_no
            raise _Rollback()


def test_configured_connector_posts_over_http(monkeypatch):
    for key, value in {"URL": "https://odoo.test", "DB": "axion", "USER": "pic@axion.example", "PASSWORD": "api-key"}.items():
        monkeypatch.setenv(f"PIC_ERP_ODOO_{key}", value)
    calls = []

    def fake_http(method, url, *, headers=None, body=None, timeout=20):
        call = json.loads(body)["params"]
        calls.append(call)
        if call["method"] == "login":
            return 200, json.dumps({"result": 7})
        model, op = call["args"][3], call["args"][4]
        if op == "search":
            return 200, json.dumps({"result": [11] if model == "res.partner" else []})
        assert op == "create" and model == "account.move"
        vals = call["args"][5][0]
        assert vals["move_type"] == "in_invoice" and vals["partner_id"] == 11 and vals["payment_reference"] == "1000|INV|TF001|T2|2026"
        return 200, json.dumps({"result": 4242})

    monkeypatch.setattr(connectors, "_http", fake_http)
    monkeypatch.setattr(integration, "_on_posted", {})  # synthetic message: no domain callback
    assert connectors.get("ODOO").configured()
    with pytest.raises(_Rollback):
        with tenant_tx(_tenant_id()) as s:
            _as(s, f"admin@{DOMAIN}")
            message = integration.enqueue(s, target_system="ODOO", message_type="SUPPLIER_INVOICE", idempotency_key="1000|INV|TF001|T2|2026",
                                          object_type="INVOICE", object_id=uuid.uuid4(), object_ref="INV-T2",
                                          payload={"invoice": "T2", "supplier": "TF001", "companyCode": "1000", "grossMinor": 100})
            integration.process(s, message)
            assert message.status == "POSTED" and message.erp_doc_no == "4242"
            unsupported = integration.enqueue(s, target_system="ODOO", message_type="GOODS_RECEIPT", idempotency_key="GR|T",
                                              object_type="GOODS_RECEIPT", object_id=uuid.uuid4(), object_ref="GR-T", payload={"gr": "GR-T"})
            integration.process(s, unsupported)
            assert unsupported.status == "RETRY" and "does not map GOODS_RECEIPT" in unsupported.last_error
            raise _Rollback()
    assert any(c["method"] == "execute_kw" for c in calls)


# ---------------------------------------------------------------- TOTP (RFC 6238)
def test_totp_rfc6238_sha1_vectors():
    key = b"12345678901234567890"
    vectors = {59: "94287082", 1111111109: "07081804", 1111111111: "14050471", 1234567890: "89005924", 2000000000: "69279037",
               20000000000: "65353130"}
    for t, expected in vectors.items():
        assert mfa.hotp(key, t // 30, digits=8) == expected
    secret = base64.b32encode(key).decode()
    assert mfa.totp(secret, at=59) == "287082"
    assert mfa.match_step(secret, "287082", at=59) == 1
    assert mfa.match_step(secret, "287082", at=59 + 30) == 1  # one step of clock drift is accepted
    assert mfa.match_step(secret, "287082", at=59 + 90) is None
    assert mfa.match_step(secret, "287082", last_used_step=1, at=59) is None  # replay
    assert mfa.match_step(secret, "28708", at=59) is None
    uri = mfa.otpauth_uri(secret, "a@b.example", "AlphaHelion PIC")
    assert uri.startswith("otpauth://totp/AlphaHelion%20PIC:a@b.example?") and f"secret={secret}" in uri


@pytest.fixture
def fixed_step(monkeypatch):
    step = mfa.time_step()
    monkeypatch.setattr(mfa, "time_step", lambda at=None: step)
    return step


def _code(secret: str, step: int) -> str:
    return mfa.hotp(mfa._key(secret), step)


def test_totp_enrol_confirm_and_login_with_challenge(client, fixed_step):
    email = f"mfa.user@{DOMAIN}"
    _ensure_user(_tenant_id(), email, ["AP_CLERK"], {})
    first = client.post("/v1/auth/token", json={"tenant": "AXN", "email": email, "password": PASSWORD})
    assert first.status_code == 200 and "access_token" in first.json()  # no factor yet: login as today
    headers = {"Authorization": f"Bearer {first.json()['access_token']}"}
    assert client.get("/v1/me/mfa", headers=headers).json()["enrolled"] is False
    enrol = client.post("/v1/me/mfa/totp", headers=headers)
    assert enrol.status_code == 201
    secret = enrol.json()["secret"]
    assert enrol.json()["otpauthUri"].startswith("otpauth://totp/") and len(secret) == 32
    with tenant_tx(_tenant_id()) as s:
        stored = s.execute(select(MfaFactor).where(MfaFactor.user_id == _user(s, email).id)).scalar_one()
        assert secret not in stored.secret_enc and stored.confirmed_at is None  # encrypted at rest
    assert client.post("/v1/me/mfa/totp/confirm", headers=headers, json={"code": "000000" if _code(secret, fixed_step) != "000000" else "111111"}
                       ).json()["code"] == "MFA_CODE_INVALID"
    confirmed = client.post("/v1/me/mfa/totp/confirm", headers=headers, json={"code": _code(secret, fixed_step - 1)})
    assert confirmed.status_code == 200 and confirmed.json()["enrolled"] is True and "access_token" not in confirmed.json()
    with tenant_tx(_tenant_id()) as s:
        assert _user(s, email).mfa_enrolled is True

    second = client.post("/v1/auth/token", json={"tenant": "AXN", "email": email, "password": PASSWORD})
    assert second.status_code == 200 and second.json()["mfaRequired"] is True and "access_token" not in second.json()
    challenge = second.json()["challenge"]
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {challenge}"}).status_code == 401  # a challenge is not a token
    replay = client.post("/v1/auth/mfa", json={"challenge": challenge, "code": _code(secret, fixed_step - 1)})
    assert replay.status_code == 401 and replay.json()["code"] == "MFA_CODE_INVALID"  # step already used for confirmation
    ok = client.post("/v1/auth/mfa", json={"challenge": challenge, "code": _code(secret, fixed_step)})
    assert ok.status_code == 200, ok.text
    token = ok.json()["access_token"]
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {token}"}).json()["user"] == email
    again = client.post("/v1/auth/mfa", json={"challenge": challenge, "code": _code(secret, fixed_step)})
    assert again.status_code == 401  # replay of the same code
    assert client.post("/v1/auth/mfa", json={"challenge": "not-a-challenge", "code": "123456"}).json()["code"] == "MFA_CHALLENGE_INVALID"

    mfa_headers = {"Authorization": f"Bearer {token}"}
    assert client.request("DELETE", "/v1/me/mfa/totp", headers=mfa_headers, json={"code": "999999"}).status_code == 422
    off = client.request("DELETE", "/v1/me/mfa/totp", headers=mfa_headers, json={"code": _code(secret, fixed_step + 1)})
    assert off.status_code == 200 and off.json()["enrolled"] is False
    plain = client.post("/v1/auth/token", json={"tenant": "AXN", "email": email, "password": PASSWORD})
    assert "access_token" in plain.json()


def test_wrong_codes_exhaust_the_challenge(client, fixed_step):
    email = f"mfa.limit@{DOMAIN}"
    _ensure_user(_tenant_id(), email, ["AP_CLERK"], {})
    token = client.post("/v1/auth/token", json={"tenant": "AXN", "email": email, "password": PASSWORD}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    secret = client.post("/v1/me/mfa/totp", headers=headers).json()["secret"]
    assert client.post("/v1/me/mfa/totp/confirm", headers=headers, json={"code": _code(secret, fixed_step)}).status_code == 200
    challenge = client.post("/v1/auth/token", json={"tenant": "AXN", "email": email, "password": PASSWORD}).json()["challenge"]
    wrong = str((int(_code(secret, fixed_step + 1)) + 1) % 1_000_000).zfill(6)
    for _ in range(5):
        assert client.post("/v1/auth/mfa", json={"challenge": challenge, "code": wrong}).status_code == 401
    exhausted = client.post("/v1/auth/mfa", json={"challenge": challenge, "code": _code(secret, fixed_step + 1)})
    assert exhausted.json()["code"] == "MFA_CHALLENGE_EXHAUSTED"


def test_admin_resets_a_lost_authenticator(client, login, fixed_step):
    email = f"mfa.lost@{DOMAIN}"
    user_id = _ensure_user(_tenant_id(), email, ["AP_CLERK"], {})
    token = client.post("/v1/auth/token", json={"tenant": "AXN", "email": email, "password": PASSWORD}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    secret = client.post("/v1/me/mfa/totp", headers=headers).json()["secret"]
    assert client.post("/v1/me/mfa/totp/confirm", headers=headers, json={"code": _code(secret, fixed_step)}).status_code == 200
    assert client.post("/v1/auth/token", json={"tenant": "AXN", "email": email, "password": PASSWORD}).json()["mfaRequired"] is True

    admin = login("admin")
    path = f"/v1/admin/users/{user_id}/mfa/reset"
    assert client.post(path, json={"reason": "x"}, headers=admin).status_code == 422  # a reason is required
    assert client.post(path, json={"reason": "Lost phone, ticket 4411"}, headers=headers).status_code == 403  # not an admin
    reset = client.post(path, json={"reason": "Lost phone, ticket 4411"}, headers=admin)
    assert reset.status_code == 200 and reset.json()["mfaEnrolled"] is False
    assert client.post(path, json={"reason": "Lost phone, ticket 4411"}, headers=admin).json()["code"] == "MFA_NOT_ENROLLED"
    with tenant_tx(_tenant_id()) as s:
        assert s.execute(select(MfaFactor).where(MfaFactor.user_id == user_id)).first() is None
        admin_id = _user(s, "admin@axion.example").id
    # Signing in works again without a code; the reset is audited with its reason.
    assert "access_token" in client.post("/v1/auth/token", json={"tenant": "AXN", "email": email, "password": PASSWORD}).json()
    with tenant_tx(_tenant_id()) as s:
        event = s.execute(select(AuditEvent).where(AuditEvent.object_id == user_id, AuditEvent.action == "MFA_RESET")).scalar_one()
        assert event.reason == "Lost phone, ticket 4411" and "admin@axion.example" in event.actor
    # Never one's own: a stolen admin session must not strip its own second factor.
    own = client.post(f"/v1/admin/users/{admin_id}/mfa/reset", json={"reason": "Lost phone"}, headers=admin)
    assert own.status_code == 409 and own.json()["code"] == "SELF_RESET"


@pytest.fixture(scope="module")
def enforced_tenant():
    tenant_id = reference.create_tenant("MFAT", "MFA Enforcement Test Pvt Ltd", "MANUFACTURING")
    reference.bootstrap(tenant_id, company=("3000", "MFA Enforcement Test Pvt Ltd", "29AAACM1111C1Z1"), plants=[("M100", "Mysuru", "29")],
                        cost_objects=[("COST_CENTER", "9300", "Admin")])
    with tenant_tx(tenant_id) as s:
        if not s.execute(select(AppUser.id).where(AppUser.email == "admin@mfat.example")).first():
            s.add(AppUser(tenant_id=tenant_id, email="admin@mfat.example", full_name="MFAT admin", password_hash=hash_password(PASSWORD),
                          roles=["TENANT_ADMIN"], attributes={}))
            s.add(AppUser(tenant_id=tenant_id, email="buyer@mfat.example", full_name="MFAT buyer", password_hash=hash_password(PASSWORD),
                          roles=["BUYER"], attributes={}))
        current = s.execute(select(RuleSet).where(RuleSet.key == "MFA").order_by(RuleSet.effective_from.desc())).scalars().first()
        if not current.body.get("enforce"):
            s.add(RuleSet(tenant_id=tenant_id, key="MFA", version="test-enforce", effective_from=current.effective_from + timedelta(days=1),
                          body={**current.body, "enforce": True}, description="MFA enforced (test)"))
    return tenant_id


def test_enforced_mfa_requires_enrolment_before_access(client, enforced_tenant, fixed_step):
    r = client.post("/v1/auth/token", json={"tenant": "MFAT", "email": "admin@mfat.example", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["code"] == "MFA_ENROLMENT_REQUIRED" and "access_token" not in r.json()
    enrolment = {"Authorization": f"Bearer {r.json()['enrolmentChallenge']}"}
    assert client.get("/v1/tasks", headers=enrolment).status_code == 401  # the challenge only opens the enrolment endpoints
    assert client.get("/v1/me", headers=enrolment).status_code == 401
    assert client.get("/v1/me/mfa", headers=enrolment).json()["required"] is True
    secret = client.post("/v1/me/mfa/totp", headers=enrolment).json()["secret"]
    done = client.post("/v1/me/mfa/totp/confirm", headers=enrolment, json={"code": _code(secret, fixed_step)})
    assert done.status_code == 200 and done.json()["access_token"]
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {done.json()['access_token']}"}).json()["tenant"] == "MFAT"
    assert client.post("/v1/auth/token", json={"tenant": "MFAT", "email": "admin@mfat.example", "password": PASSWORD}).json()["mfaRequired"]
    # Roles outside MFA.requiredRoles sign in as before.
    assert "access_token" in client.post("/v1/auth/token", json={"tenant": "MFAT", "email": "buyer@mfat.example", "password": PASSWORD}).json()


# ---------------------------------------------------------------- OIDC single sign-on
ISSUER = "https://idp.test/realms/axn"
CLIENT_ID = "pic-web"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _jwk(key) -> dict:
    numbers = key.public_key().public_numbers()
    return {"kty": "RSA", "kid": "k1", "use": "sig", "alg": "RS256", "n": _b64(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
            "e": _b64(numbers.e.to_bytes(3, "big"))}


def _id_token(key, claims: dict) -> str:
    header = _b64(json.dumps({"alg": "RS256", "kid": "k1", "typ": "JWT"}).encode())
    payload = _b64(json.dumps(claims).encode())
    signature = key.sign(f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{payload}.{_b64(signature)}"


@pytest.fixture
def idp(monkeypatch):
    for k, v in {"ISSUER": ISSUER, "CLIENT_ID": CLIENT_ID, "CLIENT_SECRET": "s3cret", "REDIRECT_URI": "http://localhost:3000/api/auth/oidc/callback"}.items():
        monkeypatch.setenv(f"PIC_OIDC_AXN_{k}", v)
    oidc._cache.clear()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    state = {"key": key, "sign_with": key, "claims": {}, "forms": []}

    def fake_http(method, url, data=None, headers=None):
        if url == f"{ISSUER}/.well-known/openid-configuration":
            return {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
                    "token_endpoint": f"{ISSUER}/protocol/openid-connect/token", "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs"}
        if url.endswith("/certs"):
            return {"keys": [_jwk(key)]}
        assert method == "POST" and url.endswith("/token")
        state["forms"].append(data)
        return {"access_token": "idp-at", "token_type": "Bearer", "id_token": _id_token(state["sign_with"], state["claims"])}

    monkeypatch.setattr(oidc, "_http", fake_http)
    yield state
    oidc._cache.clear()


def _start(client) -> dict:
    r = client.get("/v1/auth/oidc/AXN/start")
    assert r.status_code == 200, r.text
    query = parse_qs(urlparse(r.json()["authorizationUrl"]).query)
    return {k: v[0] for k, v in query.items()}


def _claims(params: dict, **override) -> dict:
    now = int(time.time())
    return {"iss": ISSUER, "aud": CLIENT_ID, "sub": "idp-user-1", "email": f"buyer@{DOMAIN}", "email_verified": True, "iat": now,
            "exp": now + 300, "nonce": params["nonce"], "amr": ["pwd", "mfa"], **override}


def test_oidc_not_configured(client, monkeypatch):
    for k in ("ISSUER", "CLIENT_ID", "REDIRECT_URI"):
        monkeypatch.delenv(f"PIC_OIDC_AXN_{k}", raising=False)
        monkeypatch.delenv(f"PIC_OIDC_{k}", raising=False)
    assert client.get("/v1/auth/oidc/AXN").json() == {"tenant": "AXN", "enabled": False}
    r = client.get("/v1/auth/oidc/AXN/start")
    assert r.status_code == 404 and r.json()["code"] == "OIDC_NOT_CONFIGURED"


def test_oidc_sign_in_with_pkce(client, idp):
    assert client.get("/v1/auth/oidc/AXN").json()["enabled"] is True
    assert client.get("/v1/auth/oidc/NOPE").json()["enabled"] is False
    params = _start(client)
    assert params["client_id"] == CLIENT_ID and params["code_challenge_method"] == "S256" and params["response_type"] == "code"
    idp["claims"] = _claims(params)
    r = client.post("/v1/auth/oidc/callback", json={"code": "auth-code-1", "state": params["state"]})
    assert r.status_code == 200, r.text
    form = idp["forms"][-1]
    assert form["code"] == "auth-code-1" and form["client_secret"] == "s3cret" and form["redirect_uri"].endswith("/api/auth/oidc/callback")
    assert _b64(hashlib.sha256(form["code_verifier"].encode()).digest()) == params["code_challenge"]  # PKCE S256
    me = client.get("/v1/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me["user"] == f"buyer@{DOMAIN}" and me["tenant"] == "AXN"


@pytest.mark.parametrize("case, expected", [
    ("bad_signature", "OIDC_TOKEN_INVALID"), ("wrong_aud", "OIDC_TOKEN_INVALID"), ("expired", "OIDC_TOKEN_EXPIRED"),
    ("wrong_nonce", "OIDC_TOKEN_INVALID"), ("wrong_issuer", "OIDC_TOKEN_INVALID"), ("unknown_user", "OIDC_USER_UNKNOWN"),
    ("bad_state", "OIDC_STATE_INVALID"),
])
def test_oidc_rejections(client, idp, case, expected):
    params = _start(client)
    claims = _claims(params)
    state = params["state"]
    if case == "bad_signature":
        idp["sign_with"] = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    elif case == "wrong_aud":
        claims["aud"] = "someone-else"
    elif case == "expired":
        claims["exp"] = int(time.time()) - 600
    elif case == "wrong_nonce":
        claims["nonce"] = "other"
    elif case == "wrong_issuer":
        claims["iss"] = "https://evil.test"
    elif case == "unknown_user":
        claims["email"] = f"nobody@{DOMAIN}"
    elif case == "bad_state":
        state = state[:-4] + ("AAAA" if not state.endswith("AAAA") else "BBBB")
    idp["claims"] = claims
    r = client.post("/v1/auth/oidc/callback", json={"code": "c", "state": state})
    assert r.json()["code"] == expected, r.text
    assert r.status_code in (401, 403) and "access_token" not in r.json()


class _Rollback(Exception):
    pass


def test_erp_target_is_resolved_per_company_code():
    tenant_id = _tenant_id()
    with pytest.raises(_Rollback):
        with tenant_tx(tenant_id) as s:
            assert integration.target_system(s) == "SAP_S4" and integration.target_system(s, "1000") == "SAP_S4"
            current = s.execute(select(RuleSet).where(RuleSet.key == "ERP-TARGET")).scalars().first()
            assert current is not None and current.body == {"system": "SAP_S4"}
            s.add(RuleSet(tenant_id=tenant_id, key="ERP-TARGET", version="test-9999", effective_from=current.effective_from,
                          company_code="9999", body={"system": "ODOO"}, description="Company 9999 posts to Odoo (test)"))
            s.flush()
            assert integration.target_system(s, "9999") == "ODOO" and integration.target_system(s, "1000") == "SAP_S4"
            raise _Rollback()  # never leave the scoped rule behind
