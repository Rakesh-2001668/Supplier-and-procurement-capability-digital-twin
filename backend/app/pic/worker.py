"""Background worker: outbox relay, ERP connector retries and workflow timers.

Run alongside the API:  python -m app.pic.worker
Liveness probe:         python -m app.pic.worker --check-heartbeat   (exit 1 when the last tick is older than PIC_WORKER_STALE_SECONDS)

Heartbeat: after every tick the worker (a) touches PIC_WORKER_HEARTBEAT_FILE for its own container probe and (b) sets the
``application_name`` of one dedicated database session to ``pic-worker hb=<epoch>``, which the API's /readyz and /metrics
read from pg_stat_activity — no table needed, and the heartbeat disappears when the worker's connection does. Use the
direct (non-pooler) Neon host for the worker: a transaction-mode pooler does not keep session settings.
"""
import argparse
import logging
import os
import socket
import sys
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


def tick() -> dict:
    stats = {"events": outbox.relay_once(), "integration": 0, "timers": 0}
    for tenant_id in workflow.tenants():
        principal = system_principal(tenant_id)
        with obs.span("worker.timers", tenant=str(tenant_id)):
            stats["timers"] += workflow.run_due_timers(tenant_id, principal)
        with obs.span("worker.integration", tenant=str(tenant_id)):
            stats["integration"] += integration.run_pending(tenant_id, principal)
    stats["events"] += outbox.relay_once()
    return stats


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
