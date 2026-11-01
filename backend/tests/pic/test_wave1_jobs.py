"""Wave 1 (engineer A): the job scheduler and its jobs, retention and the verifiable audit archive, delegation of authority,
overdue-task reassignment, the event catalogue contract, the new event consumers and AI controls (kill switch, drift suspension,
SoD, Guided Buying). Everything runs in tenants of its own (WJA1, WJA2); the AXN signature tenant is only read."""
import ast
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.pic import worker
from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    Agent, AgentRun, AppUser, AuditArchiveBatch, AuditEvent, AuditEventArchive, CompanyCode, Delegation, IdempotencyRecord, Invoice,
    JobRun, Material, MrpRun, Notification, OutboxEvent, PurchaseOrder, Requisition, RuleSet, ScheduledJob, Scorecard, SodRule, Supplier,
    Task, Tenant,
)
from app.pic.platform import agents, audit, clock, cron, observability, outbox, workflow
from app.pic.platform import delegation as lookup
from app.pic.platform.auth import hash_password
from app.pic.platform.errors import Problem
from app.pic.seed import reference
from app.pic.services import delegation as delegation_svc
from app.pic.services import job_handlers, jobs, privacy
from tests.pic.conftest import PASSWORD

BACKEND = Path(__file__).resolve().parents[2]
UTC = timezone.utc

USERS = [  # local part, roles, attributes
    ("admin", ["TENANT_ADMIN"], {}),
    ("fc", ["FINANCE_CONTROLLER"], {}), ("ap", ["AP_CLERK"], {}), ("buyer", ["BUYER"], {}), ("mrp", ["MRP_CONTROLLER"], {}),
    ("cpo", ["CPO"], {}), ("requester", ["REQUESTER"], {"cost_objects": ["COST_CENTER:7100"]}),
    ("coo", ["COST_OBJECT_OWNER"], {"cost_objects": ["COST_CENTER:7100"]}),
    ("coo2", ["COST_OBJECT_OWNER"], {"cost_objects": ["COST_CENTER:7100"]}),
    ("dh", ["DEPT_HEAD"], {"cost_objects": ["COST_CENTER:7100"]}),
    ("dh.other", ["DEPT_HEAD"], {"cost_objects": ["COST_CENTER:9900"]}),
    ("ph", ["PROCUREMENT_HEAD"], {}),
    ("deputy", ["BUYER"], {}), ("deputy2", ["BUYER"], {}),
]


def _tenant(code: str, name: str) -> uuid.UUID:
    tid = reference.create_tenant(code, name, "GENERAL", mfa_enforce=False)
    reference.bootstrap(tid, company=("1000", name, "27AAAAA0000A1Z5"), plants=[("P100", "Plant 100", "27")],
                        cost_objects=[("COST_CENTER", "7100", "Cost centre 7100")])
    with tenant_tx(tid) as s:
        for local, roles, attrs in USERS:
            s.add(AppUser(tenant_id=tid, email=f"{local}@{code.lower()}.example", full_name=local.upper(), password_hash=hash_password(PASSWORD),
                          roles=roles, attributes=attrs))
    return tid


@pytest.fixture(scope="module")
def wja():
    return _tenant("WJA1", "Wave1 Jobs Test Pvt Ltd")


@pytest.fixture(scope="module")
def wja2():
    return _tenant("WJA2", "Wave1 Archive Test Pvt Ltd")


def act(s, local: str, code: str = "wja1"):
    user = s.execute(select(AppUser).where(AppUser.email == f"{local}@{code}.example")).scalar_one()
    p = lookup.principal_of(user)
    s.info["principal"], s.info["user_id"] = p, p.user_id
    return p


def uid(tenant: uuid.UUID, local: str, code: str = "wja1") -> uuid.UUID:
    with tenant_tx(tenant) as s:
        return s.execute(select(AppUser.id).where(AppUser.email == f"{local}@{code}.example")).scalar_one()


def relay(tenant: uuid.UUID) -> None:
    outbox.relay_tenant(tenant)


def notes(tenant: uuid.UUID, prefix: str) -> list[Notification]:
    with tenant_tx(tenant) as s:
        return list(s.execute(select(Notification).where(Notification.dedup_key.like(f"{prefix}%"))).scalars())


def add_rule(tenant: uuid.UUID, key: str, version: str, body: dict, from_: date = None) -> None:
    with tenant_tx(tenant) as s:
        s.add(RuleSet(tenant_id=tenant, key=key, version=version, effective_from=from_ or clock.today(), body=body, description="test"))


def supplier(tenant: uuid.UUID, code: str = "WJS1") -> uuid.UUID:
    with tenant_tx(tenant) as s:
        existing = s.execute(select(Supplier.id).where(Supplier.code == code)).scalar()
        if existing:
            return existing
        sup = Supplier(tenant_id=tenant, code=code, legal_name=f"Supplier {code}", status="ACTIVE")
        s.add(sup)
        s.flush()
        return sup.id


def invoice(tenant: uuid.UUID, number: str, *, due: date, block: bool = False, status: str = "POSTED", posting_key: str = None,
            invoice_date: date = None, first_pass: bool = None, payment_status: str = "UNPAID") -> uuid.UUID:
    sup = supplier(tenant)
    with tenant_tx(tenant) as s:
        inv = Invoice(tenant_id=tenant, number=number, supplier_invoice_no=f"SI-{number}", fiscal_year="2026-27", company_code="1000", supplier_id=sup,
                      invoice_date=invoice_date or clock.today(), channel="PORTAL", net_minor=100_000, tax_minor=18_000, gross_minor=118_000,
                      status=status, payment_block=block, due_date=due, posting_key=posting_key, payment_status=payment_status,
                      first_pass_matched=first_pass)
        s.add(inv)
        s.flush()
        return inv.id


# ================================================================ cron
def test_cron_next_after():
    start = datetime(2026, 10, 30, 0, 0, tzinfo=UTC)  # 05:30 IST
    assert cron.Cron("30 6 * * *").next_after(start) == datetime(2026, 10, 30, 1, 0, tzinfo=UTC)
    assert cron.Cron("30 6 * * *").next_after(datetime(2026, 10, 30, 1, 0, tzinfo=UTC)) == datetime(2026, 10, 31, 1, 0, tzinfo=UTC)
    assert cron.Cron("*/15 * * * *").next_after(datetime(2026, 10, 30, 0, 7, tzinfo=UTC)) == datetime(2026, 10, 30, 0, 15, tzinfo=UTC)
    assert cron.Cron("0 3 1 * *").next_after(start).astimezone(cron.ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M") == "2026-11-01 03:00"
    assert cron.Cron("0 0 * * 1").next_after(start).astimezone(cron.ZoneInfo("Asia/Kolkata")).weekday() == 0  # Monday
    assert cron.Cron("@hourly").next_after(start) == datetime(2026, 10, 30, 0, 30, tzinfo=UTC)  # :00 IST = :30 UTC
    assert cron.Cron("0 9 * JAN-MAR MON-FRI").months == {1, 2, 3}
    for bad in ("", "* * * *", "61 * * * *", "* 24 * * *", "*/0 * * * *", "a b c d e", "5-1 * * * *"):
        with pytest.raises(cron.CronError):
            cron.Cron(bad)


def test_registry_has_the_platform_jobs_and_vercel_cron_runs_every_minute():
    assert {"payment-due", "erp-reconciliation", "mrp-schedule", "scorecard-monthly", "retention-purge", "audit-archive",
            "idempotency-purge"} <= set(jobs.REGISTRY)
    config = json.loads((BACKEND / "vercel.json").read_text(encoding="utf-8"))
    assert {"path": "/internal/worker/tick", "schedule": "* * * * *"} in config["crons"]


# ================================================================ scheduler
def test_first_tick_creates_the_rows_and_runs_nothing(wja):
    assert jobs.run_due(wja) == 0
    with tenant_tx(wja) as s:
        rows = {r.job_key: r for r in s.execute(select(ScheduledJob)).scalars()}
        assert set(jobs.REGISTRY) <= set(rows)
        assert all(r.next_run_at > datetime.now(UTC) and r.enabled for r in rows.values())
        assert s.execute(select(func.count()).select_from(JobRun)).scalar_one() == 0


def test_due_jobs_run_record_and_reschedule(wja, monkeypatch):
    jobs.run_due(wja)
    later = datetime.now(UTC) + timedelta(days=3)
    monkeypatch.setattr(jobs, "_now", lambda: later)
    before = observability.JOB_RUNS.value("payment-due", "SUCCESS")
    ran = jobs.run_due(wja)
    assert ran >= len(jobs.REGISTRY) - 1
    with tenant_tx(wja) as s:
        for row in s.execute(select(ScheduledJob).where(ScheduledJob.job_key.in_(list(job_handlers_keys())))).scalars():
            assert row.last_status in ("SUCCESS",), (row.job_key, row.last_status, row.last_error)
            assert row.next_run_at > later and row.running_since is None and row.run_count >= 1 and row.last_duration_ms is not None
    assert observability.JOB_RUNS.value("payment-due", "SUCCESS") == before + 1
    assert jobs.run_due(wja) == 0, "nothing is due right after a run"
    assert "pic_job_runs_total" in "\n".join(line for m in observability._REGISTRY for line in m.render())


def job_handlers_keys():
    return [k for k in jobs.REGISTRY if not k.startswith("test-")]


def test_a_failing_job_is_isolated_recorded_and_alerts_the_administrators(wja, monkeypatch):
    @jobs.job("test-fail", name="Failing test job", description="raises", schedule="* * * * *")
    def _fail(ctx):
        ctx.session.add(Notification(tenant_id=ctx.tenant_id, user_id=uuid.uuid4(), kind="X", title="half written", body="x"))
        ctx.session.flush()
        raise RuntimeError("job exploded")

    @jobs.job("test-ok", name="Test job", description="works", schedule="* * * * *")
    def _ok(ctx):
        return {"hello": "world"}

    @jobs.job("test-partial", name="Partial test job", description="one unit fails", schedule="* * * * *")
    def _partial(ctx):
        return {"done": 1, "errors": ["unit B: failed"]}

    try:
        jobs.ensure(wja)
        with tenant_tx(wja) as s:  # only the test jobs are due
            for row in s.execute(select(ScheduledJob)).scalars():
                row.next_run_at = datetime.now(UTC) + timedelta(days=1) if row.job_key not in ("test-fail", "test-ok", "test-partial") else \
                    datetime.now(UTC) - timedelta(minutes=1)
        for round_ in range(jobs.FAILURE_ALERT_AFTER):
            assert jobs.run_due(wja) == 3
            with tenant_tx(wja) as s:
                for row in s.execute(select(ScheduledJob).where(ScheduledJob.job_key.like("test-%"))).scalars():
                    row.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
        with tenant_tx(wja) as s:
            rows = {r.job_key: r for r in s.execute(select(ScheduledJob).where(ScheduledJob.job_key.like("test-%"))).scalars()}
            assert rows["test-fail"].last_status == "FAILED" and "job exploded" in rows["test-fail"].last_error
            assert rows["test-fail"].consecutive_failures == jobs.FAILURE_ALERT_AFTER
            assert rows["test-ok"].last_status == "SUCCESS" and rows["test-ok"].consecutive_failures == 0, "the other jobs still ran"
            assert rows["test-partial"].last_status == "PARTIAL" and "unit B" in rows["test-partial"].last_error
            assert s.execute(select(func.count()).select_from(Notification).where(Notification.title == "half written")).scalar_one() == 0, "rolled back"
            runs = s.execute(select(JobRun).where(JobRun.job_key == "test-fail")).scalars().all()
            assert len(runs) == jobs.FAILURE_ALERT_AFTER and all(r.status == "FAILED" and r.error for r in runs)
            assert s.execute(select(AuditEvent).where(AuditEvent.action == "JOB_FAILED", AuditEvent.object_ref == "test-fail")).first()
        assert notes(wja, "JOB_FAILING:test-fail"), "the tenant administrators were told on the third failure"
    finally:
        for key in ("test-fail", "test-ok", "test-partial"):
            jobs.REGISTRY.pop(key, None)


def test_single_flight_running_claim_stale_takeover_and_advisory_lock(wja):
    jobs.ensure(wja)
    with tenant_tx(wja) as s:
        row = s.execute(select(ScheduledJob).where(ScheduledJob.job_key == "idempotency-purge")).scalar_one()
        row.running_since = datetime.now(UTC)
    with pytest.raises(Problem) as running:
        jobs.run_now(wja, "idempotency-purge", requested_by="u:test")
    assert running.value.code == "JOB_RUNNING" and running.value.status == 409
    with tenant_tx(wja) as s:  # the claim of a crashed worker is stale after the job's timeout
        row = s.execute(select(ScheduledJob).where(ScheduledJob.job_key == "idempotency-purge")).scalar_one()
        row.running_since = datetime.now(UTC) - timedelta(seconds=jobs.REGISTRY["idempotency-purge"].timeout_seconds + 5)
        s.add(JobRun(tenant_id=wja, scheduled_job_id=row.id, job_key=row.job_key, trigger="SCHEDULE", status="RUNNING",
                     started_at=row.running_since))
    outcome = jobs.run_now(wja, "idempotency-purge", requested_by="u:test")
    assert outcome["status"] == "SUCCESS"
    with tenant_tx(wja) as s:
        abandoned = s.execute(select(JobRun).where(JobRun.job_key == "idempotency-purge", JobRun.error.like("abandoned%"))).scalars().all()
        assert len(abandoned) == 1 and abandoned[0].status == "FAILED"
    # another worker holds the job's advisory lock: this run is skipped, not run twice
    with tenant_tx(wja) as holder:
        holder.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"pic-job:{wja}:idempotency-purge"})
        skipped = jobs.run_now(wja, "idempotency-purge", requested_by="u:test")
    assert skipped["status"] == "SKIPPED" and "lock" in skipped["result"]["reason"]
    with pytest.raises(Problem) as unknown:
        jobs.run_now(wja, "nonexistent", requested_by="u:test")
    assert unknown.value.status == 404


def test_configure_enable_disable_and_schedule_are_audited(wja):
    with tenant_tx(wja) as s:
        act(s, "admin")
        row = jobs.configure(s, "payment-due", enabled=False, schedule="0 7 * * *", reason="finance asked for 07:00")
        assert row.enabled is False and row.schedule == "0 7 * * *"
        with pytest.raises(Problem) as bad:
            jobs.configure(s, "payment-due", enabled=None, schedule="every day", reason=None)
        assert bad.value.code == "INVALID_SCHEDULE"
        row = jobs.configure(s, "payment-due", enabled=True, schedule=None, reason=None)
        assert row.next_run_at > datetime.now(UTC)
        actions = [e.action for e in s.execute(select(AuditEvent).where(AuditEvent.object_ref == "payment-due")).scalars()]
        assert actions.count("JOB_CONFIGURED") == 2


def test_tick_runs_the_scheduler_for_the_tenant(wja, monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "run_due", lambda tenant_id: calls.append(tenant_id) or 4)
    stats = worker.tick(tenant_id=wja)
    assert calls == [wja] and stats["jobs"] == 4


# ================================================================ idempotency purge (6)
def test_idempotency_records_older_than_24_hours_are_purged(wja):
    old = datetime.now(UTC) - timedelta(hours=25)
    with tenant_tx(wja) as s:
        s.add(IdempotencyRecord(tenant_id=wja, scope="POST /t", key="old-1", request_hash="a" * 64, created_at=old))
        s.add(IdempotencyRecord(tenant_id=wja, scope="POST /t", key="old-2", request_hash="b" * 64, created_at=old))
        s.add(IdempotencyRecord(tenant_id=wja, scope="POST /t", key="fresh", request_hash="c" * 64, created_at=datetime.now(UTC)))
    dry = jobs.run_now(wja, "idempotency-purge", requested_by="u:test", dry_run=True)
    assert dry["status"] == "SUCCESS" and dry["result"]["wouldDelete"] == 2
    with tenant_tx(wja) as s:
        assert s.execute(select(func.count()).select_from(IdempotencyRecord)).scalar_one() == 3
    real = jobs.run_now(wja, "idempotency-purge", requested_by="u:test")
    assert real["result"]["deleted"] == 2
    with tenant_tx(wja) as s:
        assert [r.key for r in s.execute(select(IdempotencyRecord)).scalars()] == ["fresh"]


# ================================================================ retention (5)
def test_retention_purge_is_a_dry_run_until_the_rule_says_otherwise(wja):
    old = datetime.now(UTC) - timedelta(days=400)
    admin_id = uid(wja, "admin")
    with tenant_tx(wja) as s:
        s.add(Notification(tenant_id=wja, user_id=admin_id, kind="K", title="old", body="b", created_at=old, dedup_key="RET-OLD"))
        s.add(Notification(tenant_id=wja, user_id=admin_id, kind="K", title="new", body="b", dedup_key="RET-NEW"))
    job = jobs.run_now(wja, "retention-purge", requested_by="u:test")
    assert job["status"] == "SUCCESS" and job["result"]["dryRun"] is True
    assert job["result"]["categories"]["notifications"]["wouldDelete"] == 1
    with tenant_tx(wja) as s:
        assert s.execute(select(func.count()).select_from(Notification).where(Notification.dedup_key.like("RET-%"))).scalar_one() == 2
    # the applied purge (admin API / rule purge.dryRun=false)
    with tenant_tx(wja) as s:
        act(s, "admin")
        result = privacy.apply_retention(s, dry_run=False)
        assert result["categories"]["notifications"]["deleted"] == 1 and result["total"] >= 1
        assert [n.dedup_key for n in s.execute(select(Notification).where(Notification.dedup_key.like("RET-%"))).scalars()] == ["RET-NEW"]
        assert s.execute(select(AuditEvent).where(AuditEvent.action == "RETENTION_PURGE_APPLIED")).first()
        assert audit.verify_chain(s)["valid"]
    add_rule(wja, "PRIVACY-RETENTION", "t-apply", {"categories": {"notification": {"days": 1}}, "purge": {"dryRun": False}})
    applied = jobs.run_now(wja, "retention-purge", requested_by="u:test")
    assert applied["result"]["dryRun"] is False and "deleted" in applied["result"]["categories"]["notifications"]
    # a dry run requested from the screen stays a dry run even when the rule allows the purge
    again = jobs.run_now(wja, "retention-purge", requested_by="u:test", dry_run=True)
    assert again["result"]["dryRun"] is True


def test_deactivated_users_are_pseudonymised_after_the_retention_period(wja):
    add_rule(wja, "PRIVACY-RETENTION", "t-users", {"categories": {"user_profile": {"days": 30}}, "purge": {"dryRun": False}},
             from_=clock.today() + timedelta(days=0))
    with tenant_tx(wja) as s:
        user = AppUser(tenant_id=wja, email="leaver@wja1.example", full_name="Leaver Person", password_hash="x", roles=["REQUESTER"], active=False,
                       attributes={"phone": "999"})
        s.add(user)
        s.flush()
        user_id = user.id
        s.execute(text("UPDATE pic.app_user SET updated_at = now() - interval '90 days' WHERE id = :i"), {"i": user_id})
    with tenant_tx(wja) as s:
        act(s, "admin")
        dry = privacy.apply_retention(s, dry_run=True)
        assert dry["categories"]["usersPseudonymised"]["wouldPseudonymise"] == 1
        assert s.get(AppUser, user_id).email == "leaver@wja1.example"
    with tenant_tx(wja) as s:
        act(s, "admin")
        done = privacy.apply_retention(s, dry_run=False)
        assert done["categories"]["usersPseudonymised"]["pseudonymised"] == 1
        erased = s.get(AppUser, user_id)
        assert erased.email.endswith("@erased.invalid") and "phone" not in erased.attributes
        assert s.execute(select(AuditEvent).where(AuditEvent.action == "PERSONAL_DATA_ERASED", AuditEvent.object_id == user_id)).first()


# ================================================================ audit archive (5)
def test_audit_archive_keeps_the_hash_chain_verifiable(wja2):
    from datetime import datetime as dt
    old = dt.now(UTC) - timedelta(days=1200)
    with tenant_tx(wja2) as s:
        act(s, "admin", "wja2")
        with clock.pinned(old):
            for i in range(12):
                audit.record(s, "TEST_DOC", uuid.UUID(int=5), "OLD_EVENT", object_ref="DOC-OLD", after={"i": i})
        for i in range(3):
            audit.record(s, "TEST_DOC", uuid.UUID(int=6), "NEW_EVENT", object_ref="DOC-NEW", after={"i": i})
    with tenant_tx(wja2) as s:
        act(s, "admin", "wja2")
        before = audit.verify_chain(s)
        assert before["valid"] and "archived" not in before
        total = s.execute(select(func.count()).select_from(AuditEvent)).scalar_one()
        dry = privacy.archive_audit(s, dry_run=True)
        assert dry["wouldArchive"] >= 12 and s.execute(select(func.count()).select_from(AuditEvent)).scalar_one() == total
    with tenant_tx(wja2) as s:
        act(s, "admin", "wja2")
        result = privacy.archive_audit(s, dry_run=False)
        moved = result["archived"]
        assert moved >= 12 and result["batches"][0]["id"]
    with tenant_tx(wja2) as s:
        act(s, "admin", "wja2")
        live = s.execute(select(func.count()).select_from(AuditEvent)).scalar_one()
        assert live == total - moved + 1, "the archive left the live events and added its own audit event"
        after = audit.verify_chain(s)
        assert after["valid"], after
        assert after["archived"]["events"] == moved and after["archived"]["batches"] == 1
        # an event written now still links to the live head, and the trail of an archived object is complete
        audit.record(s, "TEST_DOC", uuid.UUID(int=7), "AFTER_ARCHIVE", object_ref="DOC-7")
        assert audit.verify_chain(s)["valid"]
        assert len(audit.trail(s, "TEST_DOC", uuid.UUID(int=5))) == 12
        batch = s.execute(select(AuditArchiveBatch)).scalar_one()
        assert batch.event_count == moved and batch.anchor_hash is None and batch.status == "ARCHIVED"
        assert s.execute(select(func.min(AuditEvent.seq))).scalar_one() == batch.seq_to + 1
        assert s.execute(select(AuditEvent).where(AuditEvent.action == "AUDIT_ARCHIVED")).first()
        # the application role cannot touch the audit trail or the archive directly
        for statement in ("DELETE FROM pic.audit_event", "UPDATE pic.audit_event_archive SET reason = 'x'", "DELETE FROM pic.audit_event_archive",
                          "INSERT INTO pic.audit_archive_batch (id) VALUES (gen_random_uuid())"):
            with pytest.raises(Exception):
                with s.begin_nested():
                    s.execute(text(statement))
    # tampering with an archived row (as the database owner) is detected
    with system_tx() as s:
        s.execute(text("UPDATE pic.audit_event_archive SET reason = 'tampered' WHERE tenant_id = :t AND seq = (SELECT min(seq) FROM pic.audit_event_archive WHERE tenant_id = :t)"),
                  {"t": wja2})
    with tenant_tx(wja2) as s:
        broken = audit.verify_chain(s)
        assert broken["valid"] is False and broken.get("batch")
    with system_tx() as s:
        s.execute(text("UPDATE pic.audit_event_archive SET reason = NULL WHERE tenant_id = :t AND reason = 'tampered'"), {"t": wja2})
    with tenant_tx(wja2) as s:
        assert audit.verify_chain(s)["valid"]


def test_archived_events_expire_after_the_statutory_retention_but_the_checkpoint_stays(wja2):
    add_rule(wja2, "PRIVACY-RETENTION", "t-expire", {"categories": {"audit_actor": {"days": 365}}, "purge": {"dryRun": False}})
    with tenant_tx(wja2) as s:
        act(s, "admin", "wja2")
        result = privacy.archive_audit(s, dry_run=False)
        assert len(result["expired"]) == 1
    with tenant_tx(wja2) as s:
        assert s.execute(select(func.count()).select_from(AuditEventArchive)).scalar_one() == 0
        batch = s.execute(select(AuditArchiveBatch)).scalar_one()
        assert batch.status == "EXPIRED" and batch.expired_at is not None
        verdict = audit.verify_chain(s)
        assert verdict["valid"] and verdict["archived"]["expiredBatches"] == 1
        audit.record(s, "TEST_DOC", uuid.UUID(int=8), "STILL_FINE", object_ref="DOC-8")
        assert audit.verify_chain(s)["valid"]


# ================================================================ scorecards (4)
def test_monthly_scorecard_recalculation_corrects_drift_and_is_idempotent(wja):
    sup = supplier(wja)
    month_start = clock.today().replace(day=1) - timedelta(days=1)
    period = month_start.strftime("%Y-%m")
    far = clock.today() + timedelta(days=400)  # not due: these invoices must not show up in the payment-due tests
    invoice(wja, "SC-1", due=far, status="POSTED", invoice_date=month_start.replace(day=5), first_pass=True)
    invoice(wja, "SC-2", due=far, status="POSTED", invoice_date=month_start.replace(day=6), first_pass=False)
    invoice(wja, "SC-3", due=far, status="PAID", invoice_date=month_start.replace(day=7), first_pass=True)
    with tenant_tx(wja) as s:  # a counter that drifted (a missed event)
        s.add(Scorecard(tenant_id=wja, supplier_id=sup, period=period, receipts=0, on_time_in_full=0, qty_received=0, qty_rejected=0,
                        invoices=7, invoices_first_pass=7, invoice_accuracy_pct=Decimal("100.00")))
    dry = jobs.run_now(wja, "scorecard-monthly", requested_by="u:test", dry_run=True, params={"period": period})
    assert dry["result"]["corrected"] == 1
    with tenant_tx(wja) as s:
        assert s.execute(select(Scorecard.invoices).where(Scorecard.period == period)).scalar_one() == 7
    real = jobs.run_now(wja, "scorecard-monthly", requested_by="u:test", params={"period": period})
    assert real["result"]["corrected"] == 1 and real["result"]["changes"][0]["before"]["invoices"] == "7"
    with tenant_tx(wja) as s:
        card = s.execute(select(Scorecard).where(Scorecard.period == period)).scalar_one()
        assert (card.invoices, card.invoices_first_pass, card.invoice_accuracy_pct) == (3, 2, Decimal("66.67"))
        audit_event = s.execute(select(AuditEvent).where(AuditEvent.action == "SCORECARD_RECALCULATED")).scalar_one()
        assert audit_event.before["invoices"] == "7" and audit_event.after["invoices"] == "3"
    again = jobs.run_now(wja, "scorecard-monthly", requested_by="u:test", params={"period": period})
    assert again["result"]["corrected"] == 0 and again["result"]["unchanged"] == 1, "idempotent per month"
    with pytest.raises(Problem):
        with tenant_tx(wja) as s:
            from app.pic.services import supplier as supplier_svc
            supplier_svc.recalculate_scorecards(s, "2026-13")
    assert job_handlers.previous_period(date(2026, 1, 15)) == "2025-12"


def test_scorecard_recalculation_agrees_with_the_event_driven_counters_of_the_signature_case():
    """On real seeded data the document-based recalculation must reproduce the incremental counters (no drift)."""
    from app.pic.services import supplier as supplier_svc
    with system_tx() as s:
        axn = s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()
    with tenant_tx(axn) as s:
        act_user = s.execute(select(AppUser).where(AppUser.email == "admin@axion.example")).scalar_one()
        p = lookup.principal_of(act_user)
        s.info["principal"], s.info["user_id"] = p, p.user_id
        periods = list(s.execute(select(Scorecard.period).distinct()).scalars())
        assert periods
        for period in periods:
            result = supplier_svc.recalculate_scorecards(s, period, dry_run=True)
            assert result["corrected"] == 0, (period, result["changes"])


# ================================================================ payment-due trigger (1)
def test_payment_due_proposes_the_run_to_the_finance_controller(wja, monkeypatch):
    today = clock.today()
    invoice(wja, "PD-1", due=today + timedelta(days=2))
    invoice(wja, "PD-2", due=today)
    invoice(wja, "PD-FAR", due=today + timedelta(days=30))
    invoice(wja, "PD-BLOCK", due=today, block=True)
    invoice(wja, "PD-PAID", due=today, payment_status="PAID")
    dry = jobs.run_now(wja, "payment-due", requested_by="u:test", dry_run=True)
    assert dry["result"]["due"] == 2 and dry["result"]["action"] == "PROPOSE"
    with tenant_tx(wja) as s:
        assert s.execute(select(func.count()).select_from(Task).where(Task.kind == job_handlers.PROPOSAL_KIND)).scalar_one() == 0
    first = jobs.run_now(wja, "payment-due", requested_by="u:test")
    assert first["result"]["action"] == "PROPOSED"
    second = jobs.run_now(wja, "payment-due", requested_by="u:test")
    assert second["result"]["action"] == "PROPOSAL_EXISTS", "one proposal per day"
    relay(wja)
    with tenant_tx(wja) as s:
        task = s.execute(select(Task).where(Task.kind == job_handlers.PROPOSAL_KIND)).scalar_one()
        assert task.candidate_role == "FINANCE_CONTROLLER" and sorted(task.evidence["invoices"]) == ["PD-1", "PD-2"]
        assert task.evidence["totalMinor"] == 236_000
        task_id = task.id
    assert notes(wja, f"TASK_ASSIGNED:{task_id}"), "the finance controller was notified"

    captured = {}
    from app.pic.services import payables

    def fake_run(session, run_date, include_not_due=False, supplier_codes=None, invoice_numbers=None):
        captured.update(run_date=run_date, include_not_due=include_not_due, invoices=invoice_numbers)
        return {"run": "PRUN-TEST", "paid": [{"invoice": n} for n in invoice_numbers], "skipped": []}

    monkeypatch.setattr(payables, "payment_run", fake_run)
    with tenant_tx(wja) as s:  # a role without the payment scope cannot approve: the run would execute under their name
        act(s, "fc")
        workflow.complete(s, task_id, "APPROVE")
    assert captured["include_not_due"] is True and sorted(captured["invoices"]) == ["PD-1", "PD-2"]
    with tenant_tx(wja) as s:
        task = s.get(Task, task_id)
        assert task.status == "COMPLETED" and task.evidence["result"]["run"] == "PRUN-TEST"
        assert s.execute(select(AuditEvent).where(AuditEvent.action == "PAYMENT_RUN_EXECUTED")).first()


def test_payment_due_auto_run_pays_only_what_is_due_today(wja, monkeypatch):
    today = clock.today()
    add_rule(wja, "PAYMENT-RUN", "t-auto", {"horizonDays": 3, "autoRun": True, "approverRole": "FINANCE_CONTROLLER", "slaBusinessDays": 1},
             from_=today)
    invoice(wja, "AR-DUE", due=today)
    invoice(wja, "AR-LATER", due=today + timedelta(days=2))
    seen = {}
    from app.pic.services import payables

    def fake_run(session, run_date, include_not_due=False, supplier_codes=None, invoice_numbers=None):
        seen.update(include_not_due=include_not_due, invoices=sorted(invoice_numbers or []))
        return {"run": "PRUN-AUTO", "paid": [{"invoice": n} for n in invoice_numbers or []], "skipped": []}

    monkeypatch.setattr(payables, "payment_run", fake_run)
    result = jobs.run_now(wja, "payment-due", requested_by="u:test", params={})
    assert result["result"]["action"] == "AUTO_RUN" and seen["include_not_due"] is False
    assert "AR-LATER" not in seen["invoices"] and "AR-DUE" in seen["invoices"]
    with tenant_tx(wja) as s:
        assert s.execute(select(AuditEvent).where(AuditEvent.action == "AUTO_RUN_BY_SCHEDULE")).first()


# ================================================================ nightly reconciliation (2)
def test_reconciliation_runs_per_company_code_and_notifies_finance_of_differences(wja):
    invoice(wja, "RC-1", due=clock.today(), status="POSTED", posting_key="PK|RC-1")
    dry = jobs.run_now(wja, "erp-reconciliation", requested_by="u:test", dry_run=True)
    assert dry["result"]["companyCodes"][0]["companyCode"] == "1000"
    result = jobs.run_now(wja, "erp-reconciliation", requested_by="u:test")
    assert result["status"] == "SUCCESS" and result["result"]["differences"] >= 1
    number = result["result"]["companyCodes"][0]["run"]
    assert notes(wja, f"RECONCILIATION:{number}"), "finance was notified of the differences"
    users = {n.user_id for n in notes(wja, f"RECONCILIATION:{number}")}
    assert uid(wja, "fc") in users and uid(wja, "ap") in users


# ================================================================ scheduled MRP (3)
def test_scheduled_mrp_runs_per_plant_and_never_overlaps(wja):
    empty = jobs.run_now(wja, "mrp-schedule", requested_by="u:test")
    assert empty["result"]["plants"] == [] and "no plant" in empty["result"]["note"]
    add_rule(wja, "MRP-SCHEDULE", "t-plants", {"plants": ["P100", "NOPE"], "mode": "NET_CHANGE", "overlapMinutes": 120})
    result = jobs.run_now(wja, "mrp-schedule", requested_by="u:test")
    assert result["status"] == "PARTIAL" and "NOPE: unknown plant" in result["result"]["errors"][0]
    run_number = result["result"]["plants"][0]["run"]
    with tenant_tx(wja) as s:
        run = s.execute(select(MrpRun).where(MrpRun.number == run_number)).scalar_one()
        assert run.plant == "P100" and run.status == "COMPLETED"
        run.status = "RUNNING"  # a run that is still going
        run.completed_at = None
    skipped = jobs.run_now(wja, "mrp-schedule", requested_by="u:test")
    assert "still running" in skipped["result"]["plants"][0]["skipped"]
    with tenant_tx(wja) as s:
        s.execute(select(MrpRun)).scalars().first().status = "COMPLETED"
    relay(wja)
    assert notes(wja, "MRP_RUN:"), "the MRP controllers were told about the finished run (event consumer)"


# ================================================================ delegation of authority (59)
def _task(tenant, ref, *, initiator="requester", role="COST_OBJECT_OWNER", chain=None, evidence=None, kind="TEST_DELEG", scope=None):
    with tenant_tx(tenant) as s:
        p = act(s, initiator)
        return workflow.start_approval(s, None, kind, object_type="TEST", object_id=uuid.uuid4(), object_ref=ref, chain=chain or [role],
                                       step_id=None, initiator_id=p.user_id, scopes={role: {"cost_object": "COST_CENTER:7100"} if scope is None else scope},
                                       evidence=evidence)[0].id


def _delegate(tenant, delegator, delegate, *, days=3, roles=None, limit=None, by="admin"):
    with tenant_tx(tenant) as s:
        act(s, by)
        return delegation_svc.create(s, delegator_id=uid(tenant, delegator), delegate_id=uid(tenant, delegate), valid_from=clock.today(),
                                     valid_to=clock.today() + timedelta(days=days), roles=roles, value_limit_minor=limit, reason="annual leave")


def test_a_delegate_works_the_delegators_tasks_on_their_behalf(wja):
    task_id = _task(wja, "DEL-1")
    with tenant_tx(wja) as s:
        task = s.get(Task, task_id)
        deputy = act(s, "deputy")
        assert workflow.can_work(deputy, task) is not None and task_id not in [t.id for t in workflow.open_tasks_for(s, deputy)]
    grant = _delegate(wja, "coo", "deputy")
    relay(wja)
    assert notes(wja, f"DELEGATION_CREATED:{grant['id']}:delegate") and notes(wja, f"DELEGATION_CREATED:{grant['id']}:delegator")
    with tenant_tx(wja) as s:
        task = s.get(Task, task_id)
        deputy = act(s, "deputy")
        assert workflow.can_work(deputy, task) is None
        assert task_id in [t.id for t in workflow.open_tasks_for(s, deputy)]
        info = workflow.acting_for(s, deputy, task)
        assert info["delegator"] == "COO" and info["until"]
        assert workflow.acting_for(s, act(s, "coo"), task) is None, "the delegator works it in his own right"
        assert workflow.can_work(act(s, "coo2"), task) is None
        # a stranger without a delegation still cannot
        assert workflow.can_work(act(s, "deputy2"), task) is not None
        act(s, "deputy")
        workflow.complete(s, task_id, "APPROVE", "approved while coo is away")
    with tenant_tx(wja) as s:
        event = s.execute(select(AuditEvent).where(AuditEvent.object_ref == "DEL-1", AuditEvent.action == "APPROVAL_APPROVE")).scalar_one()
        assert event.actor == "u:deputy@wja1.example" and event.on_behalf_of == "u:coo@wja1.example"
        assert event.after["delegatedFrom"] == str(uid(wja, "coo")) and event.after["actingRole"] == "COST_OBJECT_OWNER"
        assert audit.verify_chain(s)["valid"]
    # the new task notification reaches the delegate too
    task2 = _task(wja, "DEL-2")
    relay(wja)
    assert uid(wja, "deputy") in {n.user_id for n in notes(wja, f"TASK_ASSIGNED:{task2}")}


def test_four_eyes_holds_for_both_people_under_delegation(wja):
    # the delegate initiated the document: a delegation never lets him approve it
    own = _task(wja, "DEL-OWN", initiator="deputy")
    # the delegator initiated it: nobody acts for him on it
    theirs = _task(wja, "DEL-THEIRS", initiator="coo2")
    with tenant_tx(wja) as s:
        assert workflow.can_work(act(s, "deputy"), s.get(Task, own)) is not None
        assert workflow.can_work(act(s, "deputy"), s.get(Task, theirs)) is None, "coo2 is a candidate himself; deputy acts for coo (not excluded)"
    _delegate(wja, "coo2", "deputy2")
    with tenant_tx(wja) as s:
        assert workflow.can_work(act(s, "deputy2"), s.get(Task, theirs)) is not None, "the delegator is excluded from his own document"
        assert workflow.can_work(act(s, "deputy2"), s.get(Task, own)) is None, "other candidates' delegates are unaffected"
    # sequential chain: whoever approved step 1 (delegate and delegator) is excluded from step 2
    chain_task = _task(wja, "DEL-CHAIN", chain=["COST_OBJECT_OWNER", "DEPT_HEAD"], scope={"cost_object": "COST_CENTER:7100"})
    with tenant_tx(wja) as s:
        act(s, "deputy")
        workflow.complete(s, chain_task, "APPROVE")
        second = s.execute(select(Task).where(Task.object_ref == "DEL-CHAIN", Task.sequence == 2)).scalar_one()
        assert uid(wja, "deputy") in second.excluded_user_ids and uid(wja, "coo") in second.excluded_user_ids
        assert workflow.DELEGATED_KEY not in (second.evidence or {})


def test_sod_guards_run_for_the_delegator_as_well(wja):
    blocked = uid(wja, "coo")

    @workflow.guard_task("TEST_SOD_DELEG")
    def _guard(session, task, decision):
        if session.info["principal"].user_id == blocked:
            raise Problem(409, "SOD_CONFLICT", "SOD-T: the delegator has a conflict on this document")

    try:
        task_id = _task(wja, "DEL-SOD", kind="TEST_SOD_DELEG")
        with tenant_tx(wja) as s:
            act(s, "deputy")
            with pytest.raises(Problem) as conflict:
                workflow.complete(s, task_id, "APPROVE")
            assert conflict.value.code == "SOD_CONFLICT"
        with tenant_tx(wja) as s:  # the delegator's own colleague without the conflict is fine
            act(s, "coo2")
            workflow.complete(s, task_id, "APPROVE")
    finally:
        workflow._task_guards.pop("TEST_SOD_DELEG", None)


def test_delegation_scope_roles_and_value_limit(wja):
    role_only = _delegate(wja, "dh", "deputy2", roles=["DEPT_HEAD"], limit=100_000_00)
    dh_task = _task(wja, "DEL-DH", role="DEPT_HEAD", evidence={"totalMinor": 50_000_00})
    big = _task(wja, "DEL-BIG", role="DEPT_HEAD", evidence={"totalMinor": 500_000_00})
    unknown = _task(wja, "DEL-UNK", role="DEPT_HEAD")
    coo_task = _task(wja, "DEL-ROLE")
    with tenant_tx(wja) as s:
        p = act(s, "deputy2")
        assert workflow.can_work(p, s.get(Task, dh_task)) is None
        assert workflow.can_work(p, s.get(Task, big)) is not None, "above the value limit"
        assert workflow.can_work(p, s.get(Task, unknown)) is not None, "a task of unknown value is outside a value limit"
    with tenant_tx(wja) as s:
        act(s, "dh")
        delegation_svc.revoke(s, uuid.UUID(role_only["id"]), "back early")
    relay(wja)
    with tenant_tx(wja) as s:
        assert workflow.can_work(act(s, "deputy2"), s.get(Task, dh_task)) is not None, "revoked"
        assert s.execute(select(AuditEvent).where(AuditEvent.action == "DELEGATION_REVOKED")).first()
        with pytest.raises(Problem) as twice:
            delegation_svc.revoke(s, uuid.UUID(role_only["id"]), "again")
        assert twice.value.code == "ALREADY_REVOKED"
    assert notes(wja, f"DELEGATION_REVOKED:{role_only['id']}")
    del coo_task


def test_delegation_creation_controls(wja):
    sup = supplier(wja)
    with tenant_tx(wja) as s:
        s.add(AppUser(tenant_id=wja, email="portal@wja1.example", full_name="Portal", password_hash="x", roles=["SUPPLIER_USER"], supplier_id=sup))
    with tenant_tx(wja) as s:
        act(s, "ph")
        base = dict(delegator_id=None, valid_from=clock.today(), valid_to=clock.today() + timedelta(days=5), roles=None, value_limit_minor=None,
                    reason="holiday leave")

        def attempt(**over):
            with pytest.raises(Problem) as caught:
                with s.begin_nested():
                    delegation_svc.create(s, **{**base, "delegate_id": uid(wja, "deputy"), **over})
            return caught.value.code

        assert attempt(delegate_id=uid(wja, "ph")) == "DELEGATE_IS_DELEGATOR"
        assert attempt(valid_to=clock.today() - timedelta(days=1), valid_from=clock.today() - timedelta(days=3)) == "INVALID_PERIOD"
        assert attempt(valid_to=clock.today() + timedelta(days=200)) == "PERIOD_TOO_LONG"
        assert attempt(roles=["CPO"]) == "ROLE_NOT_HELD"
        assert attempt(reason="x") == "REASON_REQUIRED"
        assert attempt(value_limit_minor=-5) == "INVALID_LIMIT"
        assert attempt(delegator_id=uid(wja, "dh")) == "FORBIDDEN", "only administrators create for someone else"
        first = delegation_svc.create(s, **{**base, "delegate_id": uid(wja, "deputy")})
        assert first["status"] == "ACTIVE"
        assert attempt() == "DELEGATION_OVERLAP"
        act(s, "deputy")
        with pytest.raises(Problem) as loop:
            with s.begin_nested():
                delegation_svc.create(s, **{**base, "delegate_id": uid(wja, "ph")})
        assert loop.value.code == "DELEGATION_LOOP"
        act(s, "ph")
        assert attempt(delegate_id=uid(wja, "portal")) == "DELEGATE_NOT_ELIGIBLE"
        listing = delegation_svc.mine(s)
        assert len(listing["given"]) == 1 and listing["given"][0]["delegateEmail"] == "deputy@wja1.example"


def test_delegation_api(client, login, wja):
    ph, deputy, admin, buyer = (login(f"{n}@wja1.example", "WJA1") for n in ("ph", "deputy", "admin", "buyer"))
    candidates = client.get("/v1/me/delegation-candidates", headers=ph).json()
    deputy2 = next(c for c in candidates if c["email"] == "deputy2@wja1.example")
    body = {"delegateId": deputy2["id"], "validFrom": clock.today().isoformat(), "validTo": (clock.today() + timedelta(days=4)).isoformat(),
            "roles": ["PROCUREMENT_HEAD"], "valueLimitMinor": 5_000_000, "reason": "Conference in Singapore"}
    r = client.post("/v1/me/delegations", json=body, headers={**ph, "Idempotency-Key": "del-1"})
    assert r.status_code == 201, r.text
    again = client.post("/v1/me/delegations", json=body, headers={**ph, "Idempotency-Key": "del-1"})
    assert again.json()["id"] == r.json()["id"] and again.json().get("replayed") is True
    assert client.post("/v1/me/delegations", json={**body, "reason": "x"}, headers=ph).status_code == 422
    mine = client.get("/v1/me/delegations", headers=ph).json()
    assert [d["id"] for d in mine["given"]] == [r.json()["id"]]
    assert [d["id"] for d in client.get("/v1/me/delegations", headers=login("deputy2@wja1.example", "WJA1")).json()["received"]] == [r.json()["id"]]
    assert client.get("/v1/admin/delegations", headers=buyer).status_code == 403
    overview = client.get("/v1/admin/delegations?status=ACTIVE", headers=admin).json()
    assert any(d["id"] == r.json()["id"] for d in overview)
    stale = client.post(f"/v1/me/delegations/{r.json()['id']}/revoke", json={"reason": "plans changed"}, headers={**ph, "If-Match": '"99"'})
    assert stale.status_code == 412
    assert client.post(f"/v1/me/delegations/{r.json()['id']}/revoke", json={"reason": "x"}, headers=deputy).status_code in (403, 422)
    ok = client.post(f"/v1/me/delegations/{r.json()['id']}/revoke", json={"reason": "plans changed"},
                     headers={**ph, "If-Match": f'"{r.json()["version"]}"'})
    assert ok.status_code == 200 and ok.json()["status"] == "REVOKED"
    # an administrator sets one up for someone who is away; the task inbox shows whom the delegate acts for
    on_behalf = client.post("/v1/admin/delegations", json={**body, "delegatorId": mine["given"][0]["delegatorId"], "delegateId": deputy2["id"],
                                                          "roles": [], "valueLimitMinor": None}, headers=admin)
    assert on_behalf.status_code == 201, on_behalf.text
    task_id = _task(wja, "DEL-API", role="PROCUREMENT_HEAD", scope={})
    tasks = client.get("/v1/tasks", headers=login("deputy2@wja1.example", "WJA1")).json()
    mine_task = next(t for t in tasks if t["id"] == str(task_id))
    assert mine_task["actingFor"]["delegator"] == "PH"
    done = client.post(f"/v1/tasks/{task_id}/complete", json={"decision": "APPROVE"}, headers=login("deputy2@wja1.example", "WJA1"))
    assert done.status_code == 200, done.text


# ================================================================ overdue-task reassignment (48)
def _breach(tenant, task_id):
    from app.pic.models import Timer
    with tenant_tx(tenant) as s:
        act(s, "ph")
        timer = s.execute(select(Timer).where(Timer.kind == "TASK_SLA", Timer.object_id == task_id, Timer.fired_at.is_(None))).scalar_one()
        timer.fired_at = clock.now()
        workflow._task_sla(s, timer)


def test_escalation_modes_from_the_rule():
    assert workflow.escalation_mode({}, 2) == "ADD" and workflow.escalation_mode({}, 3) == "REASSIGN"
    assert workflow.escalation_mode({"mode": "ADD"}, 5) == "ADD" and workflow.escalation_mode({"mode": "REASSIGN"}, 2) == "REASSIGN"
    assert workflow.escalation_mode({"mode": {"2": "REASSIGN", "default": "ADD"}}, 2) == "REASSIGN"
    assert workflow.escalation_mode({"mode": {"2": "REASSIGN", "default": "ADD"}}, 4) == "ADD"
    assert workflow.escalation_mode({"managerAtLevel": 3}, 3) == "ADD" and workflow.escalation_mode({"managerAtLevel": 3}, 4) == "REASSIGN"
    assert reference.RULE_SETS["ESCALATION"][0]["mode"] == {"2": "ADD", "default": "REASSIGN"}


def test_overdue_task_is_added_then_reassigned_to_the_manager_role(wja):
    task_id = _task(wja, "ESC-1", initiator="dh.other")
    _breach(wja, task_id)  # level 1: reminder
    _breach(wja, task_id)  # level 2: the department head is added
    relay(wja)
    with tenant_tx(wja) as s:
        task = s.get(Task, task_id)
        assert [e["role"] for e in task.candidate_scope[workflow.ESCALATION_KEY]] == ["DEPT_HEAD"]
        assert workflow.can_work(act(s, "coo"), task) is None and workflow.can_work(act(s, "dh"), task) is None
    _breach(wja, task_id)  # level 3: reassigned; the original candidates lose the task
    relay(wja)
    with tenant_tx(wja) as s:
        task = s.get(Task, task_id)
        assert task.candidate_role == "DEPT_HEAD" and workflow.ESCALATION_KEY not in task.candidate_scope
        history = task.candidate_scope[workflow.REASSIGNED_KEY]
        assert history[0]["from"] == ["COST_OBJECT_OWNER", "DEPT_HEAD"] and history[0]["to"] == "DEPT_HEAD" and history[0]["level"] == 3
        assert task.name.endswith("Dept Head")
        assert workflow.can_work(act(s, "coo"), task) is not None, "the original candidate lost the task"
        assert workflow.can_work(act(s, "dh"), task) is None
        assert workflow.can_work(act(s, "dh.other"), task) is not None
        assert task_id not in [t.id for t in workflow.open_tasks_for(s, act(s, "coo"))]
        event = s.execute(select(AuditEvent).where(AuditEvent.object_ref == "ESC-1", AuditEvent.action == "TASK_REASSIGNED")).scalar_one()
        assert event.after["escalatedTo"] == "DEPT_HEAD" and event.after["mode"] == "REASSIGN" and "lose the task" in event.reason
    titles = {n.user_id: n.title for n in notes(wja, f"TASK_ESCALATED:{task_id}:3")}
    assert titles[uid(wja, "dh")].startswith("Reassigned to you")
    former = {n.user_id: n.title for n in notes(wja, f"TASK_REASSIGNED:{task_id}:3")}
    assert uid(wja, "coo") in former and former[uid(wja, "coo")].startswith("No longer yours")
    _breach(wja, task_id)  # level 4: one step further up
    with tenant_tx(wja) as s:
        task = s.get(Task, task_id)
        assert task.candidate_role == "PROCUREMENT_HEAD" and len(task.candidate_scope[workflow.REASSIGNED_KEY]) == 2
    _breach(wja, task_id)  # level 5: the CPO is the top of the chain
    with tenant_tx(wja) as s:
        task = s.get(Task, task_id)
        assert task.candidate_role == "CPO" and len(task.candidate_scope[workflow.REASSIGNED_KEY]) == 3
    _breach(wja, task_id)  # level 6: nobody above the CPO: reminder only
    with tenant_tx(wja) as s:
        assert s.get(Task, task_id).candidate_role == "CPO" and s.get(Task, task_id).escalation_level == 6


def test_a_task_is_not_reassigned_to_a_role_nobody_eligible_holds(wja):
    task_id = _task(wja, "ESC-NOELIG", initiator="cpo", role="CATEGORY_MANAGER", scope={})
    for _ in range(3):  # level 2 adds the CPO; at level 3 the only CPO is the initiator (four-eyes), so nobody could take it over
        _breach(wja, task_id)
    with tenant_tx(wja) as s:
        task = s.get(Task, task_id)
        assert task.candidate_role == "CATEGORY_MANAGER" and workflow.REASSIGNED_KEY not in task.candidate_scope
        last = s.execute(select(AuditEvent).where(AuditEvent.object_ref == "ESC-NOELIG", AuditEvent.action == "TASK_ESCALATED")
                         .order_by(AuditEvent.seq.desc())).scalars().first()
        assert "no eligible" in last.reason


def test_add_mode_rule_keeps_the_original_candidates(wja):
    body = dict(reference.RULE_SETS["ESCALATION"][0], mode="ADD")
    add_rule(wja, "ESCALATION", "t-add", body, from_=clock.today() + timedelta(days=0))
    task_id = _task(wja, "ESC-ADD", initiator="dh.other")
    for _ in range(3):
        _breach(wja, task_id)
    with tenant_tx(wja) as s:
        task = s.get(Task, task_id)
        assert task.candidate_role == "COST_OBJECT_OWNER" and [e["role"] for e in task.candidate_scope[workflow.ESCALATION_KEY]] == ["DEPT_HEAD", "PROCUREMENT_HEAD"]
        s.execute(text("DELETE FROM pic.rule_set WHERE key = 'ESCALATION' AND version = 't-add'"))


# ================================================================ AI controls (47, 51, 52)
def test_tenant_ai_switch_stops_every_agent_call_and_is_audited(wja):
    with tenant_tx(wja) as s:
        act(s, "admin")
        assert agents.guard(s, "PO_VALIDATION", required_level="L1") == (True, None)
        agents.set_ai_switch(s, False, "model incident INC-77")
        allowed, reason = agents.guard(s, "PO_VALIDATION", required_level="L1")
        assert allowed is False and "switched off for this organisation" in reason and "INC-77" in reason
        assert agents.permit(s, "COPILOT", object_type="QUESTION", object_id=uuid.uuid4(), object_ref="q", log_denial=True) is False
        denied = s.execute(select(AgentRun).where(AgentRun.agent_code == "COPILOT", AgentRun.action_taken == "DENIED")).scalars().all()
        assert denied and "INC-77" in denied[0].denial_reason
        with pytest.raises(Problem):
            agents.set_ai_switch(s, True, "x")
        agents.set_ai_switch(s, True, "incident closed, model re-validated")
        assert agents.guard(s, "PO_VALIDATION", required_level="L1")[0] is True
        actions = [e.action for e in s.execute(select(AuditEvent).where(AuditEvent.object_ref == "AI_SWITCH")).scalars()]
        assert actions == ["AI_SWITCHED_OFF", "AI_SWITCHED_ON"]
    relay(wja)
    assert notes(wja, "AI_SWITCH:")


def test_ai_switch_api_and_copilot_refusal(client, login, wja):
    admin, buyer = login("admin@wja1.example", "WJA1"), login("buyer@wja1.example", "WJA1")
    assert client.put("/v1/admin/ai/switch", json={"enabled": False, "reason": "audit freeze"}, headers=buyer).status_code == 403
    r = client.put("/v1/admin/ai/switch", json={"enabled": False, "reason": "audit freeze"}, headers={**admin, "Idempotency-Key": "ai-1"})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert client.get("/v1/admin/ai/switch", headers=buyer).json()["enabled"] is False
    refused = client.post("/v1/copilot/ask", json={"question": "what is my spend?"}, headers=admin)
    assert refused.status_code == 409 and refused.json()["code"] == "AGENT_DISABLED"
    assert client.put("/v1/admin/ai/switch", json={"enabled": True, "reason": "freeze over"}, headers={**admin, "If-Match": '"1"'}).status_code == 412
    assert client.put("/v1/admin/ai/switch", json={"enabled": True, "reason": "freeze over"}, headers=admin).json()["enabled"] is True


def test_agent_is_suspended_automatically_when_acceptance_drifts_below_70_percent(wja):
    def feedback(s, accepted: bool):
        ref = agents.log_run(s, "SUPPLIER_RISK", object_type="SUPPLIER", object_id=uuid.uuid4(), object_ref="S", inputs={}, evidence=[],
                             output={}, confidence=0.8, action_taken="RECOMMENDED")
        agents.feedback(s, ref, "ACCEPTED" if accepted else "REJECTED")

    with tenant_tx(wja) as s:
        act(s, "admin")
        for i in range(19):  # 19 events, 30% accepted: not enough feedback to judge
            feedback(s, i % 10 < 3)
        assert agents.get(s, "SUPPLIER_RISK").kill_switch is False and agents.acceptance_rate(s, "SUPPLIER_RISK") is None
        feedback(s, False)  # the 20th event
        agent = agents.get(s, "SUPPLIER_RISK")
        assert agent.kill_switch is True and agent.suspended_by == "AUTO" and "below the minimum 70%" in agent.suspension_reason
        assert agents.guard(s, "SUPPLIER_RISK", required_level="L1")[0] is False
        assert s.execute(select(AuditEvent).where(AuditEvent.action == "AGENT_AUTO_SUSPENDED", AuditEvent.object_ref == "SUPPLIER_RISK")).first()
    relay(wja)
    assert notes(wja, "AGENT_SUSPENDED:"), "the CPO and administrators were told"
    with tenant_tx(wja) as s:  # resuming restarts the window: the old feedback does not suspend it again at once
        act(s, "admin")
        agents.set_kill_switch(s, "SUPPLIER_RISK", False, "model re-validated")
        agent = agents.get(s, "SUPPLIER_RISK")
        assert agent.kill_switch is False and agent.suspension_reason is None and agent.acceptance_reset_at is not None
        feedback(s, False)
        assert agents.get(s, "SUPPLIER_RISK").kill_switch is False
        stats = agents.acceptance_stats(s, "SUPPLIER_RISK")
        assert stats["events"] == 1 and stats["rate"] is None


def test_agents_are_checked_for_segregation_of_duties(wja):
    with tenant_tx(wja) as s:
        s.add(SodRule(tenant_id=wja, code="SOD-T1", action_a="TEST_ACT_A", action_b="TEST_ACT_B", scope="obj", risk="High", mode="BLOCK",
                      description="test pair"))
    obj = uuid.uuid4()
    with tenant_tx(wja) as s:
        act(s, "buyer")
        assert agents.guard(s, "BID_ANALYSIS", required_level="L2", sod_action="TEST_ACT_B", sod_refs={"obj": obj}) == (True, None)
        agents.record_action(s, "BID_ANALYSIS", "TEST_ACT_A", {"obj": obj})  # the agent did A on this object
        allowed, reason = agents.guard(s, "BID_ANALYSIS", required_level="L2", sod_action="TEST_ACT_B", sod_refs={"obj": obj})
        assert allowed is False and "SOD-T1" in reason and "agent BID_ANALYSIS" in reason
        other = uuid.uuid4()
        assert agents.guard(s, "BID_ANALYSIS", required_level="L2", sod_action="TEST_ACT_B", sod_refs={"obj": other})[0] is True
        # the person the agent acts for did A on another object: the agent cannot be used to do B there
        from app.pic.platform import sod
        sod.record(s, "TEST_ACT_A", {"obj": other})
        allowed, reason = agents.guard(s, "BID_ANALYSIS", required_level="L2", sod_action="TEST_ACT_B", sod_refs={"obj": other})
        assert allowed is False and "the requesting user" in reason
        assert agents.permit(s, "BID_ANALYSIS", object_type="SOURCING_EVENT", object_id=other, object_ref="E", required_level="L2",
                             sod_action="TEST_ACT_B", sod_refs={"obj": other}) is False
        run = s.execute(select(AgentRun).where(AgentRun.agent_code == "BID_ANALYSIS", AgentRun.action_taken == "DENIED")).scalars().first()
        assert run and "segregation of duties" in run.denial_reason
        from app.pic.models import SodViolation
        assert s.execute(select(SodViolation.id).where(SodViolation.rule_code == "SOD-T1")).first()


def test_every_site_where_an_agent_acts_calls_the_guard():
    """Contract: any function that logs an agent run (log_run) also calls permit/guard (item 47)."""
    offenders = []
    for path in sorted((BACKEND / "app" / "pic").rglob("*.py")):
        if path.name == "agents.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            names = {c.func.attr for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
            if "log_run" in names and not names & {"permit", "guard"}:
                offenders.append(f"{path.name}:{fn.name}")
    assert not offenders, f"agent runs logged without agents.permit/guard: {offenders}"


def test_guided_buying_agent_is_invoked_by_search_and_requisition_creation(client, login, wja):
    with tenant_tx(wja) as s:
        s.add(Material(tenant_id=wja, number="WJM-1", description="Hydraulic pump seal kit", type="NON_STOCK", material_group="SEALS", category="MRO",
                       base_uom="EA", status="ACTIVE"))
    req = login("requester@wja1.example", "WJA1")
    found = client.get("/v1/guided-buying/search?q=hydraulic pump seal kit", headers=req).json()
    assert found["agent"]["agent"] == "GUIDED_BUYING" and found["agent"]["channel"] == "MATERIAL"
    assert found["agent"]["suggestion"]["material"] == "WJM-1" and found["agent"]["aiRef"].startswith("agent-run:")
    nothing = client.get("/v1/guided-buying/search?q=zzzz qqqq unknown thing", headers=req).json()
    assert nothing["agent"]["channel"] == "FREE_TEXT" and nothing["agent"]["suggestion"] is None

    def line(text, item_type, run=None, **extra):
        return {"item_type": item_type, "purchase_type": "NON_STOCK", "description": text, "material_group": "SEALS", "qty": "2", "uom": "EA",
                "price_est_minor": 150_000, "need_date": (clock.today() + timedelta(days=14)).isoformat(),
                "account_assignment_type": "COST_CENTER", "account_assignment_code": "7100", "guided_run": run, **extra}

    # the requester ignores the recommendation and types free text: REJECTED feedback + the line carries the suggestion
    r = client.post("/v1/requisitions", json={"origin": "MANUAL", "plant": "P100", "purpose_text": "seals", "lines": [
        line("Hydraulic pump seal kit", "FREE_TEXT", found["agent"]["aiRef"])]}, headers={**req, "Idempotency-Key": "gb-1"})
    assert r.status_code == 201, r.text
    with tenant_tx(wja) as s:
        run = s.get(AgentRun, uuid.UUID(found["agent"]["aiRef"].split(":")[1]))
        assert run.human_feedback == "REJECTED" and run.action_taken in ("DRAFTED", "RECOMMENDED")
    # free text without a search: the agent reviews the line at creation and stores its suggestion
    r2 = client.post("/v1/requisitions", json={"origin": "MANUAL", "plant": "P100", "purpose_text": "seals 2", "lines": [
        line("Hydraulic pump seal kit", "FREE_TEXT")]}, headers={**req, "Idempotency-Key": "gb-2"})
    assert r2.status_code == 201, r2.text
    with tenant_tx(wja) as s:
        from app.pic.models import PrLine
        pr = s.execute(select(Requisition).where(Requisition.number == r2.json()["number"])).scalar_one()
        pr_line = s.execute(select(PrLine).where(PrLine.requisition_id == pr.id)).scalar_one()
        assert pr_line.source_determination["guidedBuying"]["suggestion"]["material"] == "WJM-1"
        assert s.execute(select(AuditEvent).where(AuditEvent.action == "GUIDED_BUYING_SUGGESTED", AuditEvent.object_id == pr.id)).first()
        runs = s.execute(select(AgentRun).where(AgentRun.agent_code == "GUIDED_BUYING")).scalars().all()
        assert len(runs) >= 3
    # accepting the recommended channel is ACCEPTED feedback
    accepted = client.get("/v1/guided-buying/search?q=zzzz qqqq unknown thing", headers=req).json()["agent"]["aiRef"]
    r3 = client.post("/v1/requisitions", json={"origin": "MANUAL", "plant": "P100", "purpose_text": "x", "lines": [
        line("zzzz qqqq unknown thing", "FREE_TEXT", accepted)]}, headers={**req, "Idempotency-Key": "gb-3"})
    assert r3.status_code == 201, r3.text
    with tenant_tx(wja) as s:
        assert s.get(AgentRun, uuid.UUID(accepted.split(":")[1])).human_feedback == "ACCEPTED"
    # the kill switch (and the tenant switch) stop it: the search still works, without the agent
    admin = login("admin@wja1.example", "WJA1")
    assert client.put("/v1/agents/GUIDED_BUYING/kill-switch", json={"on": True, "reason": "test stop"}, headers=admin).status_code == 200
    stopped = client.get("/v1/guided-buying/search?q=hydraulic pump seal kit", headers=req).json()
    assert "agent" not in stopped and stopped["recommendedChannel"] == "MATERIAL"
    assert client.put("/v1/agents/GUIDED_BUYING/kill-switch", json={"on": False, "reason": "test resume"}, headers=admin).status_code == 200


# ================================================================ events (53)
def test_event_catalogue_has_a_schema_for_every_event_and_every_real_payload_validates():
    from app.pic.events import catalogue
    scan = catalogue.scan()
    emitted = {t for t, e in scan.items() if e["producers"]}
    assert len(emitted) >= 45
    missing = sorted(t for t in emitted if catalogue.load_schema(t) is None)
    if missing and __import__("os").environ.get("PIC_EVENT_CATALOGUE_STRICT", "1") == "0":
        import warnings
        warnings.warn(f"events without a schema file: {missing}")
    else:
        assert not missing, f"no schema file in app/pic/events/schemas for {missing}: run python -m app.pic.events.catalogue write"
    checked = set()
    with system_tx() as s:
        tenant_ids = list(s.execute(select(Tenant.id)).scalars())
    for tid in tenant_ids:
        with tenant_tx(tid) as s:
            for event in s.execute(select(OutboxEvent)).scalars():
                if catalogue.load_schema(event.topic) is None:
                    continue
                assert catalogue.validate(event.topic, event.payload) == [], (event.topic, event.payload)
                checked.add(event.topic)
    assert len(checked) >= 20, f"too few topics had real payloads to validate: {sorted(checked)}"
    # a payload that breaks the contract is caught
    assert catalogue.validate("requisition.cancelled", {"reason": "x"}) != []


ORIGINAL_GAPS = ["asn.received", "integration.batch.imported", "invoice.captured", "invoice.disputed", "lot.recalled", "material_request.approved",
                 "mrp.run.completed", "payment.completed", "payment_file.generated", "planned_order.firmed", "purchase_order.confirmed",
                 "requisition.approved", "requisition.cancelled", "requisition.submitted", "return_delivery.replacement_requested",
                 "savings.realised", "service_entry.approved", "subcontracting.components_provided", "supplier.invitation.sent",
                 "supplier.registered", "supplier.status.changed", "punchout.cart.returned", "sourcing.bid.submitted"]


def test_every_catalogue_event_is_consumed_or_documented_as_stream_only():
    """Item 53: the events that had no consumer now have one, or are documented as stream-only with the reason."""
    from app.pic.events import catalogue
    scan = catalogue.scan()
    for topic in ORIGINAL_GAPS:
        assert topic in scan and scan[topic]["producers"], topic
        assert scan[topic]["consumers"] or topic in catalogue.STREAM_ONLY, f"{topic}: no consumer and not documented as stream-only"
    doc = BACKEND.parent / "docs" / "PIC_Event_Catalogue.md"
    assert doc.exists() and "supplier.status.changed" in doc.read_text(encoding="utf-8")


def _emit(tenant, topic, object_type, object_id, ref, payload, local="admin"):
    with tenant_tx(tenant) as s:
        act(s, local)
        outbox.emit(s, topic, object_type, object_id, ref, payload)


def test_supplier_status_change_flags_open_pos_and_sourcing_events_and_notifies_the_owners(wja):
    sup = supplier(wja, "WJS2")
    buyer_id = uid(wja, "buyer")
    with tenant_tx(wja) as s:
        po = PurchaseOrder(tenant_id=wja, number="PO-WJ-1", company_code="1000", purch_org="1000", plant="P100", supplier_id=sup, status="RELEASED",
                           purpose_code="TEST", payment_terms="N30", rule_set_version="t", created_by=buyer_id)
        closed = PurchaseOrder(tenant_id=wja, number="PO-WJ-2", company_code="1000", purch_org="1000", plant="P100", supplier_id=sup,
                               status="CLOSED", purpose_code="TEST", payment_terms="N30", rule_set_version="t", created_by=buyer_id)
        s.add_all([po, closed])
        s.flush()
        po_id = po.id
    _emit(wja, "supplier.status.changed", "SUPPLIER", sup, "WJS2",
          {"supplierCode": "WJS2", "category": "SEALS", "from": "QUALIFIED", "to": "BLOCKED", "reason": "quality audit failed"})
    relay(wja)
    with tenant_tx(wja) as s:
        flagged = s.execute(select(AuditEvent).where(AuditEvent.action == "SUPPLIER_STATUS_FLAGGED")).scalars().all()
        assert [e.object_ref for e in flagged] == ["PO-WJ-1"] and flagged[0].after["to"] == "BLOCKED"
    mine = [n for n in notes(wja, "SUPPLIER_STATUS:") if n.user_id == buyer_id]
    assert len(mine) == 1 and "quality audit failed" in mine[0].body and mine[0].object_ref == "PO-WJ-1"
    # a supplier that becomes qualified again clears it; a plain re-qualification between healthy states is not news
    _emit(wja, "supplier.status.changed", "SUPPLIER", sup, "WJS2", {"supplierCode": "WJS2", "from": "QUALIFIED", "to": "PREFERRED", "reason": "x"})
    relay(wja)
    assert len([n for n in notes(wja, "SUPPLIER_STATUS:") if n.user_id == buyer_id]) == 1
    del po_id


def test_new_consumers_notify_the_right_people(wja, client, login):
    req = login("requester@wja1.example", "WJA1")
    r = client.post("/v1/requisitions", json={"origin": "MANUAL", "plant": "P100", "purpose_text": "consumers", "lines": [{
        "item_type": "FREE_TEXT", "purchase_type": "NON_STOCK", "description": "Consumer test item", "material_group": "MISC", "qty": "1",
        "uom": "EA", "price_est_minor": 10_000, "need_date": (clock.today() + timedelta(days=10)).isoformat(),
        "account_assignment_type": "COST_CENTER", "account_assignment_code": "7100"}]}, headers=req)
    assert r.status_code == 201, r.text
    with tenant_tx(wja) as s:
        pr_id = s.execute(select(Requisition.id).where(Requisition.number == r.json()["number"])).scalar_one()
    requester = uid(wja, "requester")
    _emit(wja, "requisition.approved", "REQUISITION", pr_id, r.json()["number"], {"origin": "MANUAL", "totalMinor": 10_000, "lines": [10]})
    _emit(wja, "requisition.cancelled", "REQUISITION", pr_id, r.json()["number"], {"reason": "not needed", "previousStatus": "APPROVED"})
    _emit(wja, "mrp.run.completed", "MRP_RUN", uuid.uuid4(), "MR-X", {"plant": "P100", "mode": "NET_CHANGE", "plannedOrders": 3, "exceptions": 2})
    _emit(wja, "lot.recalled", "MATERIAL", uuid.uuid4(), "WJM-1", {"material": "WJM-1", "batch": "B1", "notice": "RC-1",
                                                                  "quarantined": [{"plant": "P100", "storageLocation": "0001", "qty": "5"}]})
    _emit(wja, "supplier.registered", "SUPPLIER", supplier(wja), "WJS1", {"supplierCode": "WJS1", "channel": "SELF_REGISTRATION", "categories": [],
                                                                         "screening": "CLEAR"})
    relay(wja)
    assert requester in {n.user_id for n in notes(wja, f"REQUISITION_APPROVED:{pr_id}")}
    assert uid(wja, "buyer") in {n.user_id for n in notes(wja, f"REQUISITION_APPROVED:{pr_id}")}
    cancelled = notes(wja, f"REQUISITION_CANCELLED:{pr_id}")
    assert {n.user_id for n in cancelled} >= {requester, uid(wja, "buyer")}, "it had reached the buyer"
    assert uid(wja, "mrp") in {n.user_id for n in notes(wja, "MRP_RUN:")}
    recalled = {n.user_id for n in notes(wja, "LOT_RECALLED:")}
    assert uid(wja, "buyer") in recalled
    assert notes(wja, "SUPPLIER_REGISTERED:") == [], "this tenant has no supplier manager to tell"
    # consumers are idempotent: relaying again delivers nothing twice
    before = len(notes(wja, "REQUISITION_"))
    relay(wja)
    assert len(notes(wja, "REQUISITION_")) == before


# ================================================================ jobs API
def test_jobs_api_list_configure_run_and_history(client, login):
    admin, buyer = login("admin"), login("buyer")
    assert client.get("/v1/admin/jobs", headers=buyer).status_code == 403
    listing = client.get("/v1/admin/jobs", headers=admin)
    assert listing.status_code == 200
    by_key = {j["key"]: j for j in listing.json()}
    assert {"payment-due", "idempotency-purge", "audit-archive"} <= set(by_key)
    job = by_key["idempotency-purge"]
    assert job["enabled"] and job["supportsDryRun"] and job["schedule"] == "15 * * * *" and job["running"] is False
    # configure with optimistic concurrency
    stale = client.put("/v1/admin/jobs/audit-archive", json={"enabled": False}, headers={**admin, "If-Match": '"999"'})
    assert stale.status_code == 412
    current = by_key["audit-archive"]
    off = client.put("/v1/admin/jobs/audit-archive", json={"enabled": False, "reason": "freeze"}, headers={**admin, "If-Match": f'"{current["version"]}"'})
    assert off.status_code == 200 and off.json()["enabled"] is False and off.headers["ETag"]
    assert client.put("/v1/admin/jobs/audit-archive", json={"schedule": "not a cron"}, headers=admin).json()["code"] == "INVALID_SCHEDULE"
    assert client.put("/v1/admin/jobs/audit-archive", json={}, headers=admin).status_code == 422
    assert client.put("/v1/admin/jobs/audit-archive", json={"enabled": True}, headers=admin).json()["enabled"] is True
    # run a dry run now; the Idempotency-Key replays it
    run = client.post("/v1/admin/jobs/idempotency-purge/run", json={"dryRun": True}, headers={**admin, "Idempotency-Key": "job-run-1"})
    assert run.status_code == 200, run.text
    assert run.json()["status"] == "SUCCESS" and run.json()["dryRun"] is True and "wouldDelete" in run.json()["result"]
    replay = client.post("/v1/admin/jobs/idempotency-purge/run", json={"dryRun": True}, headers={**admin, "Idempotency-Key": "job-run-1"})
    assert replay.json()["id"] == run.json()["id"]
    history = client.get("/v1/admin/jobs/idempotency-purge/runs", headers=admin).json()
    assert history[0]["id"] == run.json()["id"] and history[0]["triggeredBy"] == "u:admin@axion.example" and history[0]["trigger"] == "MANUAL"
    assert client.post("/v1/admin/jobs/nope/run", json={}, headers=admin).status_code == 404
    # the audit archive screen: batches and the chain verification
    archive = client.get("/v1/admin/audit/archive", headers=admin).json()
    assert archive["verification"]["valid"] is True
    dry = client.post("/v1/admin/audit/archive", json={"dryRun": True}, headers={**admin, "Idempotency-Key": "arch-1"}).json()
    assert "cutoff" in dry and dry["verification"]["valid"]
    purge = client.post("/v1/admin/privacy/retention/purge", json={"dryRun": True}, headers=admin).json()
    assert "categories" in purge
    catalogue = client.get("/v1/admin/events/catalogue", headers=admin).json()
    assert any(e["topic"] == "supplier.status.changed" and "supplier-status-flags" in e["consumers"] for e in catalogue)
    agents_acceptance = client.get("/v1/agents-acceptance", headers=admin).json()
    assert {a["code"] for a in agents_acceptance} >= {"GUIDED_BUYING", "COPILOT"}
