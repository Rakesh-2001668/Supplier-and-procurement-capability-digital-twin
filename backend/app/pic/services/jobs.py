"""Job scheduler: code-registered, tenant-scoped scheduled jobs (TD §8 "scheduled and automatic workflows").

A job is registered in code with ``@job(key, schedule=..., ...)``; each tenant gets one ``scheduled_job`` row per job (created on
the first tick) holding the cron schedule, the on/off switch and the outcome of the last run, and one ``job_run`` row per run.

``worker.tick()`` calls ``run_due(tenant)``, so the same scheduler runs in a permanent worker process (python -m app.pic.worker),
from Vercel Cron (GET/POST /internal/worker/tick -> worker.drain -> tick) and from the admin tick (POST /v1/admin/ops/tick).

Single flight: a due job is claimed in its own short transaction (FOR UPDATE SKIP LOCKED, ``running_since`` set), then run in a
second transaction that first takes a transaction-level advisory lock on (tenant, job); a claim older than the job's timeout is
treated as abandoned by a crashed worker and taken over. A handler failure rolls back that run's writes (savepoint), is recorded
on the run and the job (status, error, consecutive failures, metrics, an audit event and, from the third failure in a row, a
notification to the tenant administrators) and never stops the other jobs, tenants or the rest of the tick.

Handlers get a ``JobContext`` and return a JSON-able summary. Return ``{"errors": [...]}`` entries for per-unit failures (e.g. one
company code of several): the run is then PARTIAL. Handlers that support dry runs (``dry_run=True`` on the decorator) must not
change anything when ``ctx.dry_run`` is set.
"""
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from sqlalchemy import or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.pic.db import tenant_tx
from app.pic.models import JobRun, ScheduledJob, Tenant
from app.pic.platform import audit, clock, cron, observability as obs, rules
from app.pic.platform.auth import Principal
from app.pic.platform.errors import Problem, not_found
from app.pic.platform.serialize import jsonable

log = logging.getLogger("pic.jobs")

FAILURE_ALERT_AFTER = 3  # consecutive failed runs before the tenant administrators are notified
HISTORY_KEEP = 200  # run rows kept per job (pruned by the retention job)
SCHEDULER_ACTOR = "agent:SCHEDULER"


@dataclass
class JobContext:
    session: Session
    tenant_id: uuid.UUID
    job_key: str
    trigger: str  # SCHEDULE | MANUAL
    dry_run: bool
    params: dict
    now: datetime
    requested_by: Optional[str] = None
    notes: list = field(default_factory=list)

    def rule(self, key: str, default: Optional[dict] = None, **scope) -> tuple[dict, Optional[str]]:
        """Body and reference of a rule set, or ``default`` when the tenant has none (older tenants)."""
        try:
            resolved = rules.resolve(self.session, key, **scope)
            return resolved.body or {}, resolved.ref
        except Problem:
            return dict(default or {}), None


JobHandler = Callable[[JobContext], Optional[dict]]


@dataclass(frozen=True)
class JobDef:
    key: str
    name: str
    description: str
    schedule: str
    handler: JobHandler
    default_enabled: bool = True
    timeout_seconds: int = 900
    dry_run: bool = False


REGISTRY: dict[str, JobDef] = {}


def job(key: str, *, name: str, description: str, schedule: str, default_enabled: bool = True, timeout_seconds: int = 900,
        dry_run: bool = False):
    cron.validate(schedule)

    def decorator(fn: JobHandler) -> JobHandler:
        REGISTRY[key] = JobDef(key, name, description, schedule, fn, default_enabled, timeout_seconds, dry_run)
        return fn
    return decorator


def _now() -> datetime:
    """Scheduling runs on the wall clock: the business clock (platform/clock.py) is pinned by seeds and datasets and must never
    move a job's next run. Tests that need to move time patch this function."""
    return datetime.now(timezone.utc)


def scheduler_principal(tenant_id: uuid.UUID) -> Principal:
    return Principal(user_id=uuid.UUID(int=0), tenant_id=tenant_id, tenant_code="", email="scheduler", name="Scheduler",
                     roles=[], scopes=set(), agent_code="SCHEDULER")


def _zone(session: Session, tenant_id: uuid.UUID) -> str:
    tenant = session.get(Tenant, tenant_id)
    return tenant.timezone if tenant is not None and tenant.timezone else "Asia/Kolkata"


# ---------------------------------------------------------------- registry rows
def ensure(tenant_id: uuid.UUID) -> int:
    """Create the missing ``scheduled_job`` rows of this tenant (first run in the future: nothing fires on creation)."""
    with tenant_tx(tenant_id, None, scheduler_principal(tenant_id)) as session:
        have = set(session.execute(select(ScheduledJob.job_key)).scalars())
        missing = [d for d in REGISTRY.values() if d.key not in have]
        if not missing:
            return 0
        zone = _zone(session, tenant_id)
        now = _now()
        for d in missing:
            session.execute(insert(ScheduledJob).values(
                id=uuid.uuid7(), tenant_id=tenant_id, job_key=d.key, schedule=d.schedule, enabled=d.default_enabled,
                next_run_at=cron.Cron(d.schedule).next_after(now, zone), run_count=0, consecutive_failures=0, row_version=1,
                created_at=now).on_conflict_do_nothing(index_elements=["tenant_id", "job_key"]))
        return len(missing)


def _abandon_stale(session: Session, row: ScheduledJob) -> None:
    for run in session.execute(select(JobRun).where(JobRun.scheduled_job_id == row.id, JobRun.status == "RUNNING")).scalars():
        run.status, run.finished_at = "FAILED", _now()
        run.error = "abandoned: the worker stopped before the run finished"


def _claim(session: Session, row: ScheduledJob, trigger: str, *, dry_run: bool, requested_by: Optional[str]) -> JobRun:
    _abandon_stale(session, row)
    now = _now()
    row.running_since = now
    run = JobRun(tenant_id=row.tenant_id, scheduled_job_id=row.id, job_key=row.job_key, trigger=trigger, dry_run=dry_run, status="RUNNING",
                 started_at=now, triggered_by=requested_by or SCHEDULER_ACTOR, created_by=None)
    session.add(run)
    session.flush()
    return run


def _is_running(row: ScheduledJob, definition: Optional[JobDef]) -> bool:
    timeout = definition.timeout_seconds if definition else 900
    return row.running_since is not None and _now() - row.running_since < timedelta(seconds=timeout)


def run_due(tenant_id: uuid.UUID) -> int:
    """Run every job of the tenant whose time has come. Returns the number of runs attempted."""
    if not REGISTRY:
        return 0
    ensure(tenant_id)
    claims: list[tuple[uuid.UUID, uuid.UUID, str]] = []
    with tenant_tx(tenant_id, None, scheduler_principal(tenant_id)) as session:
        now = _now()
        due = session.execute(
            select(ScheduledJob).where(ScheduledJob.enabled.is_(True), ScheduledJob.next_run_at <= now,
                                       or_(ScheduledJob.running_since.is_(None), ScheduledJob.running_since < now))
            .order_by(ScheduledJob.next_run_at).with_for_update(skip_locked=True)).scalars().all()
        for row in due:
            definition = REGISTRY.get(row.job_key)
            if definition is None or _is_running(row, definition):
                continue
            run = _claim(session, row, "SCHEDULE", dry_run=False, requested_by=None)
            claims.append((row.id, run.id, row.job_key))
    for job_id, run_id, key in claims:
        execute(tenant_id, job_id, run_id, key, params={}, requested_by=None)
    return len(claims)


def run_now(tenant_id: uuid.UUID, key: str, *, requested_by: str, dry_run: bool = False, params: Optional[dict] = None) -> dict:
    """Manual run (admin screen, API). Refuses when the job is already running; the schedule is left unchanged."""
    definition = REGISTRY.get(key)
    if definition is None:
        raise not_found("Job", key)
    if dry_run and not definition.dry_run:
        raise Problem(422, "DRY_RUN_UNSUPPORTED", f"Job {key} has no dry-run mode")
    ensure(tenant_id)
    with tenant_tx(tenant_id, None, scheduler_principal(tenant_id)) as session:
        row = session.execute(select(ScheduledJob).where(ScheduledJob.job_key == key).with_for_update()).scalar_one()
        if _is_running(row, definition):
            raise Problem(409, "JOB_RUNNING", f"{definition.name} is running since {row.running_since.isoformat()}; wait for it to finish",
                          rule_ref="JOBS")
        run = _claim(session, row, "MANUAL", dry_run=dry_run, requested_by=requested_by)
        job_id, run_id = row.id, run.id
    return execute(tenant_id, job_id, run_id, key, params=params or {}, requested_by=requested_by, dry_run=dry_run)


# ---------------------------------------------------------------- execution
def execute(tenant_id: uuid.UUID, job_id: uuid.UUID, run_id: uuid.UUID, key: str, *, params: dict, requested_by: Optional[str],
            dry_run: bool = False) -> dict:
    definition = REGISTRY[key]
    started = time.monotonic()
    status, result, error = "SUCCESS", {}, None
    try:
        with tenant_tx(tenant_id, None, scheduler_principal(tenant_id)) as session:
            locked = session.execute(text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))"),
                                     {"k": f"pic-job:{tenant_id}:{key}"}).scalar()
            if not locked:
                status, result = "SKIPPED", {"reason": "another worker holds the lock of this job"}
            else:
                trigger = session.get(JobRun, run_id).trigger
                ctx = JobContext(session, tenant_id, key, trigger, dry_run, params, clock.now(), requested_by)
                try:
                    with obs.span("job." + key, tenant=str(tenant_id)):
                        with session.begin_nested():
                            result = jsonable(definition.handler(ctx) or {})
                    if result.get("errors"):
                        status = "PARTIAL"
                except Exception as exc:  # noqa: BLE001 - isolation boundary: the run is recorded, the tick goes on
                    log.exception("job %s failed for tenant %s", key, tenant_id)
                    status, result = "FAILED", {}
                    error = f"{type(exc).__name__}: {getattr(exc, 'detail', None) or exc}"[:1000]
                if ctx.notes:
                    result = {**result, "notes": ctx.notes}
            outcome = _finish(session, job_id, run_id, status, result, error, int((time.monotonic() - started) * 1000), requested_by)
    except Exception as exc:  # noqa: BLE001 - the transaction itself failed (connection lost, ...): record it in a fresh one
        log.exception("job %s run could not be recorded for tenant %s", key, tenant_id)
        status, error = "FAILED", f"{type(exc).__name__}: {exc}"[:1000]
        outcome = _record_failure(tenant_id, job_id, run_id, error, int((time.monotonic() - started) * 1000))
    obs.JOB_RUNS.inc(key, status)
    obs.JOB_DURATION.observe(time.monotonic() - started, key)
    if status == "SUCCESS" and not dry_run:
        obs.JOB_LAST_SUCCESS.set(key, value=time.time())
    return outcome


def _finish(session: Session, job_id: uuid.UUID, run_id: uuid.UUID, status: str, result: dict, error: Optional[str], duration_ms: int,
            requested_by: Optional[str]) -> dict:
    row = session.get(ScheduledJob, job_id)
    run = session.get(JobRun, run_id)
    now = _now()
    run.status, run.finished_at, run.duration_ms, run.result, run.error = status, now, duration_ms, result, error
    row.running_since = None
    if not run.dry_run:
        row.last_run_at, row.last_status, row.last_duration_ms, row.last_error = run.started_at, status, duration_ms, error
        if status == "PARTIAL":
            row.last_error = "; ".join(str(e) for e in result.get("errors", []))[:1000]
        if status != "SKIPPED":
            row.run_count += 1
            row.consecutive_failures = 0 if status == "SUCCESS" else row.consecutive_failures + 1
        if run.trigger == "SCHEDULE" and status != "SKIPPED":
            row.next_run_at = cron.Cron(row.schedule).next_after(now, _zone(session, row.tenant_id))
    if status in ("FAILED", "PARTIAL"):
        audit.record(session, "SCHEDULED_JOB", row.id, "JOB_FAILED" if status == "FAILED" else "JOB_PARTIAL", object_ref=row.job_key,
                     after={"run": str(run.id), "trigger": run.trigger, "errors": result.get("errors")}, reason=row.last_error or error)
        if not run.dry_run and row.consecutive_failures == FAILURE_ALERT_AFTER:
            _alert_admins(session, row)
    session.flush()
    return run_view(run, row)


def _record_failure(tenant_id: uuid.UUID, job_id: uuid.UUID, run_id: uuid.UUID, error: str, duration_ms: int) -> dict:
    try:
        with tenant_tx(tenant_id, None, scheduler_principal(tenant_id)) as session:
            return _finish(session, job_id, run_id, "FAILED", {}, error, duration_ms, None)
    except Exception:  # noqa: BLE001 - nothing more can be done; the stale claim expires with the job's timeout
        log.exception("job failure could not be recorded")
        return {"status": "FAILED", "error": error}


def _alert_admins(session: Session, row: ScheduledJob) -> None:
    from app.pic.services import notifications  # local import: notifications consumes events and imports the workflow engine
    definition = REGISTRY.get(row.job_key)
    admins = notifications.users_with_role(session, "TENANT_ADMIN")
    notifications.notify(session, admins, kind="JOB_FAILING", dedup_key=f"JOB_FAILING:{row.job_key}:{row.run_count}", title=f"Scheduled job failing: {definition.name if definition else row.job_key}",
                         body=f"{row.job_key} failed {row.consecutive_failures} times in a row. Last error: {row.last_error or 'n/a'}",
                         link="/pic/admin", object_type="SCHEDULED_JOB", object_ref=row.job_key)


# ---------------------------------------------------------------- views and administration (API)
def run_view(run: JobRun, row: Optional[ScheduledJob] = None) -> dict:
    return {"id": str(run.id), "job": run.job_key, "trigger": run.trigger, "dryRun": run.dry_run, "status": run.status,
            "startedAt": run.started_at.isoformat() if run.started_at else None,
            "finishedAt": run.finished_at.isoformat() if run.finished_at else None, "durationMs": run.duration_ms,
            "result": run.result, "error": run.error, "triggeredBy": run.triggered_by}


def job_view(row: ScheduledJob) -> dict:
    definition = REGISTRY.get(row.job_key)
    overdue = bool(row.enabled and row.next_run_at and row.next_run_at < _now() - timedelta(minutes=10) and not row.running_since)
    return {"key": row.job_key, "name": definition.name if definition else row.job_key,
            "description": definition.description if definition else "No longer registered in this release",
            "registered": definition is not None, "schedule": row.schedule, "defaultSchedule": definition.schedule if definition else None,
            "enabled": row.enabled, "nextRunAt": row.next_run_at.isoformat() if row.next_run_at else None,
            "lastRunAt": row.last_run_at.isoformat() if row.last_run_at else None, "lastStatus": row.last_status,
            "lastDurationMs": row.last_duration_ms, "lastError": row.last_error, "runCount": row.run_count,
            "consecutiveFailures": row.consecutive_failures,
            "running": bool(definition and _is_running(row, definition)), "overdue": overdue,
            "supportsDryRun": bool(definition and definition.dry_run), "timeoutSeconds": definition.timeout_seconds if definition else None,
            "version": row.row_version}


def list_jobs(session: Session) -> list[dict]:
    ensure_in_session(session)
    return [job_view(r) for r in session.execute(select(ScheduledJob).order_by(ScheduledJob.job_key)).scalars()]


def ensure_in_session(session: Session) -> None:
    """The admin screen shows every registered job even before the worker's first tick."""
    tenant_id = session.info["tenant_id"]
    have = set(session.execute(select(ScheduledJob.job_key)).scalars())
    zone = _zone(session, tenant_id)
    for d in REGISTRY.values():
        if d.key not in have:
            session.execute(insert(ScheduledJob).values(
                id=uuid.uuid7(), tenant_id=tenant_id, job_key=d.key, schedule=d.schedule, enabled=d.default_enabled,
                next_run_at=cron.Cron(d.schedule).next_after(_now(), zone), run_count=0, consecutive_failures=0, row_version=1,
                created_at=_now()).on_conflict_do_nothing(index_elements=["tenant_id", "job_key"]))
    session.flush()


def get_row(session: Session, key: str, lock: bool = False) -> ScheduledJob:
    ensure_in_session(session)
    query = select(ScheduledJob).where(ScheduledJob.job_key == key)
    row = session.execute(query.with_for_update() if lock else query).scalar_one_or_none()
    if row is None:
        raise not_found("Job", key)
    return row


def history(session: Session, key: str, limit: int = 50) -> list[dict]:
    get_row(session, key)
    runs = session.execute(select(JobRun).where(JobRun.job_key == key).order_by(JobRun.started_at.desc()).limit(limit)).scalars()
    return [run_view(r) for r in runs]


def configure(session: Session, key: str, *, enabled: Optional[bool], schedule: Optional[str], reason: Optional[str]) -> ScheduledJob:
    """Switch a job on/off or change its schedule (audited with before/after)."""
    row = get_row(session, key, lock=True)
    p = session.info["principal"]
    before = {"enabled": row.enabled, "schedule": row.schedule, "nextRunAt": row.next_run_at.isoformat() if row.next_run_at else None}
    if schedule is not None:
        try:
            schedule = cron.validate(schedule)
        except cron.CronError as exc:
            raise Problem(422, "INVALID_SCHEDULE", str(exc), rule_ref="JOBS") from exc
        row.schedule = schedule
    if enabled is not None:
        row.enabled = enabled
    if schedule is not None or (enabled and row.next_run_at is None) or (enabled and not before["enabled"]):
        row.next_run_at = cron.Cron(row.schedule).next_after(_now(), _zone(session, row.tenant_id))
    row.changed_by = p.user_id
    session.flush()
    after = {"enabled": row.enabled, "schedule": row.schedule, "nextRunAt": row.next_run_at.isoformat() if row.next_run_at else None}
    if after != before:
        audit.record(session, "SCHEDULED_JOB", row.id, "JOB_CONFIGURED", object_ref=row.job_key, before=before, after=after, reason=reason)
    return row


def cleanup_history(session: Session, keep: int = HISTORY_KEEP, older_than_days: Optional[int] = None, dry_run: bool = False) -> int:
    """Delete finished runs beyond the newest ``keep`` per job (and, with ``older_than_days``, only those older than that)."""
    removed = 0
    cutoff = _now() - timedelta(days=older_than_days) if older_than_days else None
    for key in session.execute(select(JobRun.job_key).distinct()).scalars().all():
        stale = session.execute(select(JobRun).where(JobRun.job_key == key, JobRun.status != "RUNNING")
                                .order_by(JobRun.started_at.desc()).offset(keep)).scalars().all()
        for run in stale:
            if cutoff is not None and run.started_at >= cutoff:
                continue
            removed += 1
            if not dry_run:
                session.delete(run)
    session.flush()
    return removed
