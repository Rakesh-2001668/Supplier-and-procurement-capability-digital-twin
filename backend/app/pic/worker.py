"""Background worker: outbox relay, ERP connector retries and workflow timers.

Run alongside the API:  python -m app.pic.worker
Liveness probe:         python -m app.pic.worker --check-heartbeat   (exit 1 when the last tick is older than PIC_WORKER_STALE_SECONDS)
Serverless (Vercel):    no process; drain() runs from GET /internal/worker/tick (Vercel Cron) and, with PIC_INLINE_WORKER,
                        after every successful write (platform/http.py)

Heartbeat: after every tick the worker (a) touches PIC_WORKER_HEARTBEAT_FILE for its own container probe and (b) sets the
``application_name`` of one dedicated database session to ``pic-worker hb=<epoch>``, which the API's /readyz and /metrics
read from pg_stat_activity — no table needed, and the heartbeat disappears when the worker's connection does. Use the
direct (non-pooler) Neon host for the worker: a transaction-mode pooler does not keep session settings.
"""
import argparse
import contextvars
import logging
import os
import socket
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional


def _fast_check() -> int:
    """Liveness probe without importing the application (the probe runs every few seconds)."""
    target = Path(os.environ.get("PIC_WORKER_HEARTBEAT_FILE", "/tmp/pic-worker.heartbeat"))
    limit = int(os.environ.get("PIC_WORKER_STALE_SECONDS", "60"))
    try:
        age = time.time() - target.stat().st_mtime
    except OSError:
        print(f"no heartbeat file at {target}", file=sys.stderr)
        return 1
    if age > limit:
        print(f"heartbeat is {age:.0f}s old (limit {limit}s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__" and "--check-heartbeat" in sys.argv:
    sys.exit(_fast_check())

import app.pic.services  # noqa: F401,E402  (registers consumers and handlers)
from app.pic.config import get_settings  # noqa: E402
from app.pic.platform import integration, observability as obs, outbox, workflow  # noqa: E402
from app.pic.platform.auth import Principal  # noqa: E402

log = logging.getLogger("pic.worker")


def system_principal(tenant_id: uuid.UUID) -> Principal:
    return Principal(user_id=uuid.UUID(int=0), tenant_id=tenant_id, tenant_code="", email="scheduler", name="Scheduler",
                     roles=[], scopes=set(), agent_code="SCHEDULER")


_tick_tenant: contextvars.ContextVar[Optional[uuid.UUID]] = contextvars.ContextVar("pic_worker_tenant", default=None)


def tick(tenant_id: Optional[uuid.UUID] = None) -> dict:
    """One round of background work: every tenant (worker process, cron), or only ``tenant_id`` (inline drain after a
    tenant's write, admin tick). Each tenant's timers, ERP messages and outbox run in isolation: a failure is logged and
    counted (pic_worker_tenant_failures_total) and the other tenants and the second relay still run."""
    tenant_id = tenant_id or _tick_tenant.get()
    stats = {"events": _relay(tenant_id), "integration": 0, "timers": 0}
    for tid in ([tenant_id] if tenant_id else workflow.tenants()):
        principal = system_principal(tid)
        try:
            with obs.span("worker.timers", tenant=str(tid)):
                stats["timers"] += workflow.run_due_timers(tid, principal)
        except Exception:
            _tenant_failed("timers", tid)
        try:
            with obs.span("worker.integration", tenant=str(tid)):
                stats["integration"] += integration.run_pending(tid, principal)
        except Exception:
            _tenant_failed("integration", tid)
    stats["events"] += _relay(tenant_id)
    return stats


def _relay(tenant_id: Optional[uuid.UUID]) -> int:
    if tenant_id is None:
        return outbox.relay_once()  # isolates each tenant itself
    try:
        return outbox.relay_tenant(tenant_id)
    except Exception:
        _tenant_failed("outbox", tenant_id)
        return 0


def _tenant_failed(stage: str, tenant_id: uuid.UUID) -> None:
    obs.WORKER_TENANT_FAILURES.inc(stage)
    log.exception("worker %s failed for tenant %s", stage, tenant_id,
                  extra={"fields": {"event": "worker_tenant_failed", "stage": stage, "tenant": str(tenant_id)}})


_drain_lock = threading.Lock()


def drain(budget_seconds: float = 50.0, max_rounds: int = 20, tenant_id: Optional[uuid.UUID] = None) -> dict:
    """Serverless worker (Vercel Cron, inline drain after writes): tick until there is no work left or the time budget is
    spent. One drain per process at a time; a concurrent caller returns at once (the running drain picks its work up).
    Safe across processes: outbox, timers and connector messages are claimed with SKIP LOCKED. With ``tenant_id`` (inline
    drain after a write) only that tenant's work runs; the cron drain stays global."""
    if not _drain_lock.acquire(blocking=False):
        return {"skipped": "a drain is already running in this process"}
    started = time.monotonic()
    totals = {"rounds": 0, "events": 0, "integration": 0, "timers": 0}
    scope = _tick_tenant.set(tenant_id)
    try:
        with obs.span("worker.drain", kind="INTERNAL"):
            while totals["rounds"] < max_rounds and time.monotonic() - started < budget_seconds:
                stats = tick()
                totals["rounds"] += 1
                for key, value in stats.items():
                    totals[key] += value
                if not any(stats.values()):
                    break
        obs.WORKER_TICKS.inc("ok")
    except Exception:
        obs.WORKER_TICKS.inc("error")
        log.exception("worker drain failed")
        totals["error"] = True
    finally:
        _tick_tenant.reset(scope)
        _drain_lock.release()
    totals["ms"] = round((time.monotonic() - started) * 1000)
    if totals["events"] or totals["integration"] or totals["timers"]:
        log.info("drain %s", totals, extra={"fields": {"event": "worker_drain", **totals}})
    return totals


class Heartbeat:
    """Publishes liveness through a dedicated database session's application_name and a local file."""

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path or get_settings().worker_heartbeat_file)
        self.instance = (os.environ.get("HOSTNAME") or socket.gethostname() or "worker")[:30]
        self._conn = None

    def beat(self, ok: bool = True) -> None:
        now = int(time.time())
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(f"{now} {'ok' if ok else 'error'}\n", encoding="utf-8")
        except OSError:
            log.warning("could not write the heartbeat file %s", self.path)
        try:
            from sqlalchemy import text
            from app.pic.db import engine
            if self._conn is None or self._conn.closed:
                self._conn = engine().connect()
            name = f"{obs.WORKER_APP_NAME} hb={now} {self.instance}"[:63]
            self._conn.execute(text("SELECT set_config('application_name', :n, false)"), {"n": name})
            self._conn.commit()
        except Exception as exc:
            log.warning("database heartbeat failed: %s", type(exc).__name__)
            self.close()

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.invalidate()
                self._conn.close()
            except Exception:
                pass
            self._conn = None


def main(interval_seconds: Optional[float] = None) -> None:
    settings = get_settings()
    obs.configure_logging("pic-worker", settings.json_logs, settings.log_level)
    obs.setup_tracing("pic-worker", settings.otel_enabled)
    interval = interval_seconds or settings.worker_interval_seconds
    heartbeat = Heartbeat()
    log.info("PIC worker started", extra={"fields": {"event": "worker_started", "intervalSeconds": interval}})
    while True:
        ok = True
        with obs.span("worker.tick", kind="INTERNAL"):
            try:
                stats = tick()
                obs.WORKER_TICKS.inc("ok")
                if any(stats.values()):
                    log.info("tick %s", stats, extra={"fields": {"event": "worker_tick", **stats}})
            except Exception:
                ok = False
                obs.WORKER_TICKS.inc("error")
                log.exception("worker tick failed")
        heartbeat.beat(ok)
        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PIC background worker")
    parser.add_argument("--check-heartbeat", action="store_true", help="exit 0 when the heartbeat file is fresh (container liveness probe)")
    parser.parse_args()
    main()
