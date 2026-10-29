"""Platform fixes from the code-vs-workflow review: timer isolation (F2), approval chains, locking and escalation (F1, F3, F9), worker
tenant isolation and scope (F2, F11), MFA lockout (F4), metrics under RLS (F5), ERP queue isolation and Tally lookup (F6, F7), rule
version tie-breaks (F8), supplier reference data (F10) and outbox back-off (F12)."""
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import Timer
from app.pic.platform import clock, workflow
from app.pic.platform.auth import Principal
from app.pic.seed import reference


@pytest.fixture(scope="module")
def timer_tenant():
    # A tenant of its own: run_due_timers fires every due timer of a tenant, so the signature case must not be involved.
    return reference.create_tenant("TMRT", "Timer Test Pvt Ltd", "GENERAL")


@pytest.fixture
def handlers():
    calls = []

    @workflow.on_timer("TEST_TIMER_OK")
    def _ok(session, timer):
        calls.append(("ok", timer.id))

    @workflow.on_timer("TEST_TIMER_BOOM")
    def _boom(session, timer):
        timer.payload = {**(timer.payload or {}), "halfWritten": True}  # rolled back with the savepoint
        raise RuntimeError("handler failed")

    yield calls
    workflow._timer_handlers.pop("TEST_TIMER_OK", None)
    workflow._timer_handlers.pop("TEST_TIMER_BOOM", None)


def _principal(tenant_id):
    return Principal(user_id=uuid.UUID(int=0), tenant_id=tenant_id, tenant_code="TMRT", email="scheduler", name="Scheduler",
                     roles=[], scopes=set(), agent_code="SCHEDULER")


def test_a_failing_timer_does_not_stop_the_others_and_is_retried_then_parked(timer_tenant, handlers):
    past = clock.now() - timedelta(minutes=1)
    with tenant_tx(timer_tenant) as s:
        boom = Timer(tenant_id=timer_tenant, kind="TEST_TIMER_BOOM", object_type="TEST", object_id=uuid.uuid4(), due_at=past, payload={})
        ok = Timer(tenant_id=timer_tenant, kind="TEST_TIMER_OK", object_type="TEST", object_id=uuid.uuid4(),
                   due_at=past + timedelta(seconds=1), payload={})
        s.add_all([boom, ok])
        s.flush()
        boom_id, ok_id = boom.id, ok.id

    assert workflow.run_due_timers(timer_tenant, _principal(timer_tenant)) == 2
    assert handlers == [("ok", ok_id)], "the timer after the failing one still fired"
    with tenant_tx(timer_tenant) as s:
        boom, ok = s.get(Timer, boom_id), s.get(Timer, ok_id)
        assert ok.fired_at is not None
        assert boom.fired_at is None and boom.payload["attempts"] == 1 and "handler failed" in boom.payload["lastError"]
        assert "halfWritten" not in boom.payload
        assert boom.due_at > clock.now(), "retried later with back-off"

    for attempt in range(2, workflow.TIMER_MAX_ATTEMPTS + 1):
        with tenant_tx(timer_tenant) as s:
            s.get(Timer, boom_id).due_at = clock.now() - timedelta(seconds=1)
        workflow.run_due_timers(timer_tenant, _principal(timer_tenant))
    with tenant_tx(timer_tenant) as s:
        boom = s.get(Timer, boom_id)
        assert boom.payload["attempts"] == workflow.TIMER_MAX_ATTEMPTS and boom.payload["deadLettered"] is True
        assert boom.fired_at is not None, "parked: no longer due"
        assert s.execute(select(Timer.id).where(Timer.fired_at.is_(None), Timer.kind.like("TEST_TIMER%"))).first() is None


# ================================================================ review findings F1-F12 (platform layer)
import threading  # noqa: E402
import time  # noqa: E402
from datetime import date  # noqa: E402
from typing import Optional  # noqa: E402

from sqlalchemy import func, text  # noqa: E402

from app.pic import worker  # noqa: E402
from app.pic.db import engine, system_tx  # noqa: E402
from app.pic.models import (  # noqa: E402
    AppUser, AuditEvent, CatalogueItem, ErpDocument, IntegrationMessage, Notification, OutboxEvent, RuleSet, Task, Tenant,
)
from app.pic.platform import connectors, http, integration, mfa, observability, outbox, rules  # noqa: E402
from app.pic.platform.auth import hash_password, scopes_for  # noqa: E402
from app.pic.platform.errors import Problem  # noqa: E402
from tests.pic.conftest import PASSWORD  # noqa: E402

TMRT_USERS = [
    # local part, roles, attributes
    ("fc1", ["FINANCE_CONTROLLER"], {}), ("fc2", ["FINANCE_CONTROLLER"], {}),
    ("st1", ["MDM_STEWARD"], {}), ("st2", ["MDM_STEWARD"], {}),
    ("coo", ["COST_OBJECT_OWNER"], {"cost_objects": ["COST_CENTER:7100"]}),
    ("dh1", ["DEPT_HEAD"], {"cost_objects": ["COST_CENTER:7100"]}),
    ("dh2", ["DEPT_HEAD"], {"cost_objects": ["COST_CENTER:7100"]}),
    ("dh.other", ["DEPT_HEAD"], {"cost_objects": ["COST_CENTER:9900"]}),
    ("ph", ["PROCUREMENT_HEAD"], {}),
    ("mfa", ["AP_CLERK"], {}),
]


@pytest.fixture(scope="module")
def tmrt(timer_tenant):
    """TMRT users and the rule sets these tests need (never the AXN signature tenant)."""
    with tenant_tx(timer_tenant) as s:
        for local, roles, attrs in TMRT_USERS:
            email = f"{local}@tmrt.example"
            if not s.execute(select(AppUser.id).where(AppUser.email == email)).first():
                s.add(AppUser(tenant_id=timer_tenant, email=email, full_name=local.upper(), password_hash=hash_password(PASSWORD),
                              roles=roles, attributes=attrs))
        have = set(s.execute(select(RuleSet.key)).scalars())
        if "ESCALATION" not in have:
            s.add(RuleSet(tenant_id=timer_tenant, key="ESCALATION", version="test", effective_from=date(2026, 1, 1),
                          body=reference.RULE_SETS["ESCALATION"][0], description="test"))
        if "MFA" not in have:
            s.add(RuleSet(tenant_id=timer_tenant, key="MFA", version="test", effective_from=date(2026, 1, 1),
                          body={"enforce": False, "maxFailures": 3, "lockoutMinutes": 15}, description="test lockout"))
    return timer_tenant


def _user_principal(session, local: str) -> Principal:
    user = session.execute(select(AppUser).where(AppUser.email == f"{local}@tmrt.example")).scalar_one()
    return Principal(user_id=user.id, tenant_id=user.tenant_id, tenant_code="TMRT", email=user.email, name=user.full_name,
                     roles=list(user.roles), scopes=scopes_for(list(user.roles)), attributes=user.attributes or {})


def _act(session, local: str) -> Principal:
    p = _user_principal(session, local)
    session.info["principal"], session.info["user_id"] = p, p.user_id
    return p


@pytest.fixture
def outcomes():
    seen = []
    for kind in ("TEST_CHAIN", "TEST_PAR"):
        workflow.on_task(kind)(lambda session, task, outcome: seen.append((task.kind, outcome)))
    yield seen
    for kind in ("TEST_CHAIN", "TEST_PAR"):
        workflow._task_handlers.pop(kind, None)


# ---------------------------------------------------------------- F1 instance-less chains
def test_f1_instance_less_two_role_chain_needs_two_different_approvers(tmrt, outcomes):
    with tenant_tx(tmrt) as s:
        _act(s, "ph")
        first = workflow.start_approval(s, None, "TEST_CHAIN", object_type="TEST", object_id=uuid.uuid4(), object_ref="CHAIN-1",
                                        chain=["FINANCE_CONTROLLER", "FINANCE_CONTROLLER"], step_id=None, initiator_id=None)[0].id
    with tenant_tx(tmrt) as s:
        fc1 = _act(s, "fc1")
        workflow.complete(s, first, "APPROVE")
    assert outcomes == [], "not approved after the first of two approvers"
    with tenant_tx(tmrt) as s:
        task = s.get(Task, first)
        second = s.execute(select(Task).where(Task.group_key == task.group_key, Task.status == "OPEN")).scalar_one()
        assert second.sequence == 2 and fc1.user_id in second.excluded_user_ids
        second_id = second.id
    with pytest.raises(Problem) as refused:
        with tenant_tx(tmrt) as s:
            _act(s, "fc1")
            workflow.complete(s, second_id, "APPROVE")
    assert refused.value.code == "NOT_YOUR_TASK"
    with tenant_tx(tmrt) as s:
        _act(s, "fc2")
        workflow.complete(s, second_id, "APPROVE")
    assert outcomes == [("TEST_CHAIN", "APPROVED")]


# ---------------------------------------------------------------- F3 concurrent parallel approvals
def test_f3_parallel_approvals_finishing_together_still_complete_the_object(tmrt, outcomes):
    with tenant_tx(tmrt) as s:
        _act(s, "ph")
        ids = [t.id for t in workflow.start_approval(s, None, "TEST_PAR", object_type="TEST", object_id=uuid.uuid4(), object_ref="PAR-1",
                                                     chain=["MDM_STEWARD", "MDM_STEWARD"], mode="PARALLEL", step_id=None, initiator_id=None)]
    first_done, release, errors = threading.Event(), threading.Event(), []

    def approve(local, task_id, hold):
        try:
            with tenant_tx(tmrt) as s:
                _act(s, local)
                workflow.complete(s, task_id, "APPROVE")
                if hold:  # keep the transaction (and its locks) open while the second approver acts
                    first_done.set()
                    release.wait(15)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
            first_done.set()

    one = threading.Thread(target=approve, args=("st1", ids[0], True))
    one.start()
    assert first_done.wait(15)
    two = threading.Thread(target=approve, args=("st2", ids[1], False))
    two.start()
    time.sleep(0.5)  # the second completion now waits for the group lock (without it, it would decide on stale state)
    release.set()
    one.join(15)
    two.join(15)
    assert not errors, errors
    assert outcomes == [("TEST_PAR", "APPROVED")], "exactly one completion saw both approvals"


# ---------------------------------------------------------------- F9 SLA escalation to the manager role
def _breach(tenant_id, task_id) -> None:
    with tenant_tx(tenant_id) as s:
        _act(s, "ph")
        timer = s.execute(select(Timer).where(Timer.kind == "TASK_SLA", Timer.object_id == task_id, Timer.fired_at.is_(None))).scalar_one()
        timer.fired_at = clock.now()
        workflow._task_sla(s, timer)


def test_f9_sla_escalation_adds_the_manager_role_keeping_four_eyes(tmrt):
    assert "ESCALATION" in reference.RULE_SETS
    with tenant_tx(tmrt) as s:
        initiator = _act(s, "dh2")  # the requester is a department head: excluded from his own approval
        task_id = workflow.start_approval(s, None, "TEST_ESC", object_type="TEST", object_id=uuid.uuid4(), object_ref="ESC-1",
                                          chain=["COST_OBJECT_OWNER"], step_id=None, initiator_id=initiator.user_id,
                                          scopes={"COST_OBJECT_OWNER": {"cost_object": "COST_CENTER:7100"}})[0].id
    _breach(tmrt, task_id)  # level 1: reminder only
    with tenant_tx(tmrt) as s:
        task = s.get(Task, task_id)
        assert task.escalation_level == 1 and workflow.ESCALATION_KEY not in task.candidate_scope
        assert workflow.can_work(_user_principal(s, "dh1"), task) is not None
    _breach(tmrt, task_id)  # level 2: the department head of the same cost object becomes a candidate
    outbox.relay_tenant(tmrt)
    with tenant_tx(tmrt) as s:
        task = s.get(Task, task_id)
        assert [e["role"] for e in task.candidate_scope[workflow.ESCALATION_KEY]] == ["DEPT_HEAD"]
        assert workflow.can_work(_user_principal(s, "dh1"), task) is None
        assert "four-eyes" in workflow.can_work(_user_principal(s, "dh2"), task)
        assert workflow.can_work(_user_principal(s, "dh.other"), task) is not None, "scope kept for the department head"
        assert workflow.can_work(_user_principal(s, "coo"), task) is None, "the original approver keeps the task"
        assert task_id in [t.id for t in workflow.open_tasks_for(s, _user_principal(s, "dh1"))]
        event = s.execute(select(AuditEvent).where(AuditEvent.object_id == task.object_id, AuditEvent.action == "TASK_ESCALATED")
                          .order_by(AuditEvent.seq.desc())).scalars().first()
        assert event.after["escalatedTo"] == "DEPT_HEAD" and event.rule_set_version == "ESCALATION@test"
        notes = {n.user_id: n for n in s.execute(select(Notification).where(Notification.dedup_key == f"TASK_ESCALATED:{task_id}:2")).scalars()}
        assert notes[_user_principal(s, "dh1").user_id].title.startswith("Escalated to you")
        assert _user_principal(s, "coo").user_id in notes
        assert _user_principal(s, "dh2").user_id not in notes and _user_principal(s, "dh.other").user_id not in notes
    _breach(tmrt, task_id)  # level 3: one step further up, without scope
    with tenant_tx(tmrt) as s:
        task = s.get(Task, task_id)
        assert [e["role"] for e in task.candidate_scope[workflow.ESCALATION_KEY]] == ["DEPT_HEAD", "PROCUREMENT_HEAD"]
        assert workflow.can_work(_user_principal(s, "ph"), task) is None
    with tenant_tx(tmrt) as s:
        _act(s, "dh1")
        workflow.complete(s, task_id, "APPROVE")
    with tenant_tx(tmrt) as s:
        task = s.get(Task, task_id)
        event = s.execute(select(AuditEvent).where(AuditEvent.object_id == task.object_id, AuditEvent.action == "APPROVAL_APPROVE")).scalar_one()
        assert task.status == "COMPLETED" and event.after["actingRole"] == "DEPT_HEAD"


# ---------------------------------------------------------------- F2 / F11 worker isolation and tenant scope
@pytest.fixture
def fake_work(monkeypatch):
    """Stub every unit of work: these tests must never run real timers, ERP messages or relays."""
    good, bad = uuid.uuid4(), uuid.uuid4()
    calls = {"timers": [], "integration": [], "relay_once": 0, "relay_tenant": []}

    def timers(tenant_id, principal):
        calls["timers"].append(tenant_id)
        if tenant_id == bad:
            raise RuntimeError("tenant database error")
        return 1

    def pending(tenant_id, principal):
        calls["integration"].append(tenant_id)
        return 0

    def relay_once():
        calls["relay_once"] += 1
        return 0

    def relay_tenant(tenant_id):
        calls["relay_tenant"].append(tenant_id)
        return 0

    monkeypatch.setattr(workflow, "tenants", lambda: [bad, good])
    monkeypatch.setattr(workflow, "run_due_timers", timers)
    monkeypatch.setattr(integration, "run_pending", pending)
    monkeypatch.setattr(outbox, "relay_once", relay_once)
    monkeypatch.setattr(outbox, "relay_tenant", relay_tenant)
    return good, bad, calls


def test_f2_one_tenant_failing_does_not_stop_the_others(fake_work):
    good, bad, calls = fake_work
    before = observability.WORKER_TENANT_FAILURES.value("timers")
    stats = worker.tick()
    assert calls["timers"] == [bad, good] and calls["integration"] == [bad, good], "the later tenant still ran"
    assert calls["relay_once"] == 2, "the second relay still ran"
    assert stats["timers"] == 1 and observability.WORKER_TENANT_FAILURES.value("timers") == before + 1


def test_f11_tenant_scoped_tick_and_drain(fake_work):
    good, bad, calls = fake_work
    worker.tick(tenant_id=good)
    assert calls["timers"] == [good] and calls["relay_tenant"] == [good, good] and calls["relay_once"] == 0
    totals = worker.drain(budget_seconds=5, tenant_id=good)
    assert set(calls["timers"]) == {good} and not totals.get("error")
    assert worker._tick_tenant.get() is None, "the scope ends with the drain"


def test_f11_admin_tick_and_inline_drain_use_the_callers_tenant(client, login, monkeypatch):
    from app.pic import config
    seen = []
    monkeypatch.setattr(worker, "tick", lambda tenant_id=None: seen.append(("tick", tenant_id)) or
                        {"events": 0, "integration": 0, "timers": 0})
    monkeypatch.setattr(worker, "drain", lambda budget_seconds=50.0, max_rounds=20, tenant_id=None: seen.append(("drain", tenant_id)))
    with system_tx() as s:
        axn = s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()
    r = client.post("/v1/admin/ops/tick", headers=login("admin"))
    assert r.status_code == 200 and seen == [("tick", axn)]
    monkeypatch.setattr(config.get_settings(), "inline_worker", True)
    seen.clear()
    r = client.post("/v1/admin/rules/simulate", json={"key": "DMN-01", "inputs": {"valueMinor": 1, "channel": "OTHER"}}, headers=login("admin"))
    assert r.status_code == 200 and seen == [("drain", axn)]


# ---------------------------------------------------------------- F4 MFA brute force
def test_f4_mfa_lockout_per_account_and_ip_window_kept_until_second_factor(client, tmrt, monkeypatch):
    step = mfa.time_step()
    monkeypatch.setattr(mfa, "time_step", lambda at=None: step)
    email = "mfa@tmrt.example"
    with tenant_tx(tmrt) as s:
        user = s.execute(select(AppUser).where(AppUser.email == email)).scalar_one()
        if mfa.confirmed_factor(s, user.id) is None:
            secret = mfa.enrol(s, user)["secret"]
            mfa.confirm(s, user, mfa.hotp(mfa._key(secret), step - 1))
        secret = mfa._secret(s, mfa.factor(s, user.id))
        user_id = user.id
    ips = [f"198.51.100.{i}" for i in range(1, 12)]
    try:
        # A known password no longer clears the per-IP failure window: only a completed sign-in does.
        ip = {"X-Forwarded-For": ips[0]}
        assert client.post("/v1/auth/token", json={"tenant": "TMRT", "email": email, "password": "wrong"}, headers=ip).status_code == 401
        challenge = client.post("/v1/auth/token", json={"tenant": "TMRT", "email": email, "password": PASSWORD}, headers=ip).json()
        assert challenge["mfaRequired"] is True and len(http._login_attempts[ips[0]]) == 1
        wrong = str((int(mfa.hotp(mfa._key(secret), step)) + 1) % 1_000_000).zfill(6)
        # Fresh challenges from fresh addresses: the per-account counter (in the audit trail) still locks after 3 (rule MFA).
        for n in range(3):
            headers = {"X-Forwarded-For": ips[n + 1]}
            c = client.post("/v1/auth/token", json={"tenant": "TMRT", "email": email, "password": PASSWORD}, headers=headers).json()["challenge"]
            r = client.post("/v1/auth/mfa", json={"challenge": c, "code": wrong}, headers=headers)
            assert r.status_code == 401 and r.json()["code"] == "MFA_CODE_INVALID"
        headers = {"X-Forwarded-For": ips[5]}
        c = client.post("/v1/auth/token", json={"tenant": "TMRT", "email": email, "password": PASSWORD}, headers=headers).json()["challenge"]
        good = mfa.hotp(mfa._key(secret), step)
        locked = client.post("/v1/auth/mfa", json={"challenge": c, "code": good}, headers=headers)
        assert locked.status_code == 429 and locked.json()["code"] == "MFA_LOCKED", locked.text
        with tenant_tx(tmrt) as s:
            actions = list(s.execute(select(AuditEvent.action).where(AuditEvent.object_id == user_id)).scalars())
            assert actions.count("MFA_FAILED") >= 3 and "MFA_LOCKED_OUT" in actions
        # After the lockout window the correct code signs in, clears the IP window and restarts the count.
        clock.set_pinned(clock.now() + timedelta(minutes=16))
        try:
            ok = client.post("/v1/auth/mfa", json={"challenge": challenge["challenge"], "code": good}, headers=ip)
            assert ok.status_code == 200 and "access_token" in ok.json(), ok.text
            assert ips[0] not in http._login_attempts
            with tenant_tx(tmrt) as s:
                assert mfa.locked_for(s, user_id) is None
                assert s.execute(select(AuditEvent.seq).where(AuditEvent.object_id == user_id, AuditEvent.action == "MFA_VERIFIED")).first()
        finally:
            clock.set_pinned(None)
    finally:
        for address in ips:
            http._login_attempts.pop(address, None)


# ---------------------------------------------------------------- F5 metrics and readiness under RLS
def test_f5_metrics_and_readiness_read_tenant_tables_per_tenant_under_rls(tmrt):
    with tenant_tx(tmrt) as s:
        _act(s, "ph")
        workflow.start_approval(s, None, "TEST_METRIC", object_type="TEST", object_id=uuid.uuid4(), object_ref="MET-1",
                                chain=["PROCUREMENT_HEAD"], step_id=None, initiator_id=None)
        open_tasks = s.execute(select(func.count()).select_from(Task).where(Task.status == "OPEN")).scalar()
    with engine().connect() as conn:  # what an owner subject to FORCE RLS sees without a tenant: nothing
        with conn.begin():
            conn.execute(text('SET LOCAL ROLE "pic_app"'))
            assert conn.execute(text("SELECT count(*) FROM pic.task")).scalar() == 0
    samples = {(name, tuple(sorted(labels.items()))): value for name, _, labels, value in observability._db_samples()}
    assert samples[("pic_workflow_open_tasks", (("tenant", "TMRT"),))] == open_tasks
    expected = 0
    for tenant_id in workflow.tenants():
        with tenant_tx(tenant_id) as s:
            expected += s.execute(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.published_at.is_(None))).scalar()
    with engine().connect() as conn:
        pending, _ = observability.outbox_backlog(conn)
        assert conn.execute(text("SELECT current_user")).scalar() != "pic_app", "role reset after the probe"
    assert pending == expected and pending >= 1  # the task.assigned event above is not relayed yet
    _, body = http.readiness()
    assert body["checks"]["outbox"]["pending"] >= 1


# ---------------------------------------------------------------- F6 / F7 ERP queue isolation, parse errors and Tally find
def _enqueue(session, key: str, message_type: str, target: str = "SAP_S4", payload: Optional[dict] = None) -> uuid.UUID:
    return integration.enqueue(session, target_system=target, message_type=message_type, idempotency_key=key, object_type="TEST",
                               object_id=uuid.uuid4(), object_ref=key[:60], payload=payload or {"material": key}).id


def test_f6_a_failing_message_never_poisons_the_queue(tmrt, monkeypatch):
    def boom(session, message):
        raise Problem(409, "DOMAIN_REFUSED", "domain callback refused the posting")
    monkeypatch.setattr(integration, "_on_posted", {"MATERIAL_MASTER": boom})
    key = uuid.uuid4().hex[:10]
    with tenant_tx(tmrt) as s:
        _act(s, "ph")
        bad = _enqueue(s, f"F6|BAD|{key}", "MATERIAL_MASTER")
        good = _enqueue(s, f"F6|GOOD|{key}", "SUPPLIER_MASTER", payload={"supplier": key})
    assert integration.run_pending(tmrt, _principal(tmrt)) >= 2
    with tenant_tx(tmrt) as s:
        b, g = s.get(IntegrationMessage, bad), s.get(IntegrationMessage, good)
        assert g.status == "POSTED"
        assert b.status == "RETRY" and b.attempts == 1 and "domain callback refused" in b.last_error and b.next_attempt_at > clock.now()
        assert s.execute(select(ErpDocument.id).where(ErpDocument.external_ref == f"F6|BAD|{key}")).first() is None, "rolled back"
    for _ in range(integration.MAX_ATTEMPTS - 1):
        with tenant_tx(tmrt) as s:
            s.get(IntegrationMessage, bad).next_attempt_at = clock.now() - timedelta(seconds=1)
        integration.run_pending(tmrt, _principal(tmrt))
    with tenant_tx(tmrt) as s:
        b = s.get(IntegrationMessage, bad)
        assert b.status == "DEAD_LETTER" and b.attempts == integration.MAX_ATTEMPTS
        assert s.execute(select(AuditEvent.seq).where(AuditEvent.object_id == b.object_id,
                                                     AuditEvent.action == "INTEGRATION_DEAD_LETTER")).first()


def test_f6_unreadable_erp_answers_are_rejections(monkeypatch):
    for key, value in {"URL": "https://fusion.test", "USER": "pic", "PASSWORD": "x", "COMPANY_MAP": "1000=AXN BU"}.items():
        monkeypatch.setenv(f"PIC_ERP_ORACLE_FUSION_{key}", value)
    monkeypatch.setattr(connectors, "_http", lambda *a, **k: (200, "<html>gateway error</html>"))
    message = IntegrationMessage(target_system="ORACLE_FUSION", message_type="SUPPLIER_INVOICE", idempotency_key="F6|JSON",
                                 payload={"companyCode": "1000"})
    with pytest.raises(connectors.ConnectorRejected, match="unreadable JSON"):
        connectors.get("ORACLE_FUSION").find(None, message)
    monkeypatch.setattr(connectors, "_http", lambda *a, **k: (200, "[1, 2]"))
    with pytest.raises(connectors.ConnectorRejected, match="unexpected JSON"):
        connectors.get("ORACLE_FUSION").post(None, message)


@pytest.fixture
def tally(monkeypatch):
    monkeypatch.setenv("PIC_ERP_TALLY_PRIME_URL", "http://tally.test:9000")
    monkeypatch.setenv("PIC_ERP_TALLY_PRIME_COMPANY_MAP", "1000=Timer Test Pvt Ltd")
    calls, answers = [], []

    def fake_http(method, url, *, headers=None, body=None, timeout=20):
        calls.append(body.decode())
        return 200, answers.pop(0)
    monkeypatch.setattr(connectors, "_http", fake_http)
    return calls, answers


def test_f7_tally_queries_before_retry(tally):
    calls, answers = tally
    tp = connectors.get("TALLY_PRIME")
    message = IntegrationMessage(target_system="TALLY_PRIME", message_type="SUPPLIER_INVOICE", idempotency_key="1000|INV|TF001|T7|2026",
                                 payload={"companyCode": "1000", "invoice": "T7", "supplier": "TF001", "grossMinor": 1180000})
    answers.append('<ENVELOPE><BODY><DATA><COLLECTION><VOUCHER NAME="x" VCHTYPE="Purchase"><VOUCHERNUMBER>1000|INV|TF001|T7|2026'
                   "</VOUCHERNUMBER><MASTERID>4711</MASTERID></VOUCHER></COLLECTION></DATA></BODY></ENVELOPE>")
    assert tp.find(None, message).doc_no == "4711"
    request = calls[-1]
    assert "<TALLYREQUEST>Export</TALLYREQUEST>" in request and '$VoucherNumber = "1000|INV|TF001|T7|2026"' in request
    assert '$VoucherTypeName = "Purchase"' in request and "<SVCURRENTCOMPANY>Timer Test Pvt Ltd</SVCURRENTCOMPANY>" in request
    answers.append("<ENVELOPE><BODY><DATA><COLLECTION></COLLECTION></DATA></BODY></ENVELOPE>")
    assert tp.find(None, message) is None
    answers.append("<ENVELOPE><BODY><DATA><LINEERROR>Could not find Report PICLookup</LINEERROR></DATA></BODY></ENVELOPE>")
    with pytest.raises(connectors.ConnectorRejected, match="rejected the lookup"):
        tp.find(None, message)
    answers.append("not xml at all")
    with pytest.raises(connectors.ConnectorRejected, match="unreadable XML"):
        tp.find(None, message)
    answers.append("<RESPONSE><ERRORS>n/a</ERRORS></RESPONSE>")
    with pytest.raises(connectors.ConnectorRejected, match="import status"):
        tp.post(None, message)
    alter = IntegrationMessage(target_system="TALLY_PRIME", message_type="SUPPLIER_MASTER", idempotency_key="SUP|TF001",
                               payload={"companyCode": "1000", "supplier": "TF001", "name": "Test Foundry", "change": True})
    assert tp.find(None, alter) is None, "an alteration is idempotent: nothing to look up"


def test_f7_lost_tally_response_is_acknowledged_without_reposting(tmrt, tally, monkeypatch):
    calls, answers = tally
    monkeypatch.setattr(integration, "_on_posted", {})
    answers.append("<ENVELOPE><BODY><DATA><COLLECTION><VOUCHER><VOUCHERNUMBER>v</VOUCHERNUMBER><MASTERID>91</MASTERID></VOUCHER>"
                   "</COLLECTION></DATA></BODY></ENVELOPE>")  # the ERP already has the voucher (an earlier response was lost)
    with tenant_tx(tmrt) as s:
        _act(s, "ph")
        key = f"1000|PAY|F7|{uuid.uuid4().hex[:8]}"
        message = s.get(IntegrationMessage, _enqueue(s, key, "PAYMENT", target="TALLY_PRIME",
                                                     payload={"companyCode": "1000", "payment": "F7", "amountMinor": 100}))
        integration.process_isolated(s, message)
        assert message.status == "POSTED" and message.erp_doc_no == "91"
        assert len(calls) == 1 and "Export" in calls[0], "looked up, never re-imported"


# ---------------------------------------------------------------- F8 same-date rule versions
def test_f8_same_date_versions_resolve_deterministically(tmrt):
    with tenant_tx(tmrt) as s:
        s.add(RuleSet(tenant_id=tmrt, key="TEST-TIE", version="a", effective_from=date(2026, 2, 1), body={"v": "a"},
                      created_at=clock.now() - timedelta(hours=1)))
        s.add(RuleSet(tenant_id=tmrt, key="TEST-TIE", version="b", effective_from=date(2026, 2, 1), body={"v": "b"}, created_at=clock.now()))
        s.add(RuleSet(tenant_id=tmrt, key="TEST-TIE", version="c", effective_from=date(2026, 1, 1), body={"v": "c"},
                      created_at=clock.now() + timedelta(hours=1)))
    for _ in range(3):
        with tenant_tx(tmrt) as s:
            assert rules.resolve(s, "TEST-TIE", on=date(2026, 3, 1)).version == "b", "same date: the version created last wins"


def test_f8_duplicate_scope_and_date_needs_explicit_supersede(client, login):
    admin = login("admin")
    tag = uuid.uuid4().hex[:6]
    body = {"key": f"TEST-DUP-{tag}", "version": "1", "effective_from": "2026-05-01", "company_code": "1000", "body": {"x": 1}}
    assert client.post("/v1/admin/rules", json=body, headers=admin).status_code == 201
    again = client.post("/v1/admin/rules", json={**body, "version": "2"}, headers=admin)
    assert again.status_code == 409 and again.json()["code"] == "RULE_VERSION_CONFLICT" and again.json()["conflicting"] == ["1"]
    assert client.post("/v1/admin/rules", json={**body, "version": "1", "effective_from": "2026-06-01"},
                       headers=admin).json()["code"] == "RULE_VERSION_EXISTS"
    other_scope = client.post("/v1/admin/rules", json={**body, "version": "3", "company_code": "2000"}, headers=admin)
    assert other_scope.status_code == 201
    superseding = client.post("/v1/admin/rules", json={**body, "version": "2", "body": {"x": 2}, "supersedes": "1"}, headers=admin)
    assert superseding.status_code == 201, superseding.text
    with system_tx() as s:
        axn = s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()
    with tenant_tx(axn) as s:
        assert rules.resolve(s, body["key"], on=date(2026, 5, 2), company_code="1000").body == {"x": 2}


# ---------------------------------------------------------------- F10 reference data for supplier users
def test_f10_reference_data_for_supplier_users(client, login):
    supplier = client.get("/v1/reference", headers=login("tf.sales")).json()
    internal = client.get("/v1/reference", headers=login("buyer")).json()
    assert supplier["costObjects"] == [] and supplier["suppliers"] == []
    assert supplier["materials"] and all("standardPriceMinor" not in m for m in supplier["materials"])
    assert internal["costObjects"] and "standardPriceMinor" in internal["materials"][0]
    with system_tx() as s:
        axn = s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()
    with tenant_tx(axn) as s:
        own = s.execute(select(AppUser.supplier_id).where(AppUser.email == "tf.sales@axion.example")).scalar_one()
        owners = {str(c.id): c.supplier_id for c in s.execute(select(CatalogueItem)).scalars()}
    assert all(owners[c["id"]] == own for c in supplier["catalogue"])
    assert len(supplier["catalogue"]) <= len(internal["catalogue"])


# ---------------------------------------------------------------- F12 outbox back-off
def test_f12_failed_event_is_not_retried_in_the_same_pass_and_backs_off(tmrt):
    calls = []

    def flaky(session, event):
        calls.append(event.id)
        raise RuntimeError("consumer down")
    outbox.consumer("test.flaky", "test-flaky")(flaky)
    event_id = None
    try:
        with tenant_tx(tmrt) as s:
            _act(s, "ph")
            event_id = outbox.emit(s, "test.flaky", "TEST", uuid.uuid4(), "FLAKY-1", {}).id
        outbox.relay_tenant(tmrt)
        outbox.relay_tenant(tmrt)
        with tenant_tx(tmrt) as s:
            event = s.get(OutboxEvent, event_id)
            assert event.attempts == 1 and event.published_at is None and "consumer down" in event.last_error
        assert calls == [event_id], "one attempt, then back-off"
        assert outbox._retry_after[event_id] > time.monotonic() + outbox.RETRY_BASE_SECONDS - 5
        with tenant_tx(tmrt) as s:  # durable back-off (migration 0007): due in the future, not re-picked
            event = s.get(OutboxEvent, event_id)
            assert event.next_attempt_at is not None and event.next_attempt_at > clock.now()
            event.next_attempt_at = clock.now() - timedelta(seconds=1)  # the back-off has elapsed
        outbox._retry_after.pop(event_id)
        outbox.relay_tenant(tmrt)
        with tenant_tx(tmrt) as s:
            assert s.get(OutboxEvent, event_id).attempts == 2
    finally:
        outbox._consumers.pop("test.flaky", None)
        if event_id is not None:
            outbox._retry_after.pop(event_id, None)
            with tenant_tx(tmrt) as s:
                s.get(OutboxEvent, event_id).published_at = clock.now()
