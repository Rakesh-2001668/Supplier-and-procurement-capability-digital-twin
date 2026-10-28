"""Background worker: outbox relay, ERP connector retries and workflow timers.

Run alongside the API:  python -m app.pic.worker
"""
import logging
import time
import uuid

import app.pic.services  # noqa: F401  (registers consumers and handlers)
from app.pic.platform import integration, outbox, workflow
from app.pic.platform.auth import Principal

log = logging.getLogger("pic.worker")


def system_principal(tenant_id: uuid.UUID) -> Principal:
    return Principal(user_id=uuid.UUID(int=0), tenant_id=tenant_id, tenant_code="", email="scheduler", name="Scheduler",
                     roles=[], scopes=set(), agent_code="SCHEDULER")


def tick() -> dict:
    stats = {"events": outbox.relay_once(), "integration": 0, "timers": 0}
    for tenant_id in workflow.tenants():
        principal = system_principal(tenant_id)
        stats["timers"] += workflow.run_due_timers(tenant_id, principal)
        stats["integration"] += integration.run_pending(tenant_id, principal)
    stats["events"] += outbox.relay_once()
    return stats


def main(interval_seconds: float = 2.0) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log.info("PIC worker started")
    while True:
        try:
            stats = tick()
            if any(stats.values()):
                log.info("tick %s", stats)
        except Exception:
            log.exception("worker tick failed")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
