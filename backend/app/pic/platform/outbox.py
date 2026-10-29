"""Transactional outbox and in-process event consumers (AD-03, §11).

``emit`` writes the event in the caller's transaction, so an event exists if
and only if the business change committed. ``relay_once`` publishes pending
events to registered consumers; each consumer is idempotent through
``processed_event``. A Kafka producer can be added in ``_publish_external``
without changing producers or consumers.
"""
import logging
import time
import uuid
from datetime import timedelta
from typing import Callable, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant, system_tx, tenant_tx
from app.pic.models import OutboxEvent, ProcessedEvent, Tenant
from app.pic.platform import clock, observability as obs
from app.pic.platform.serialize import jsonable

log = logging.getLogger("pic.outbox")

Consumer = Callable[[Session, OutboxEvent], None]
_consumers: dict[str, list[tuple[str, Consumer]]] = {}


def consumer(topic: str, name: str):
    def decorator(fn: Consumer) -> Consumer:
        _consumers.setdefault(topic, []).append((name, fn))
        return fn
    return decorator


def emit(session: Session, topic: str, object_type: str, object_id: uuid.UUID, object_ref: str, payload: dict) -> OutboxEvent:
    principal = session.info.get("principal")
    event = OutboxEvent(
        id=uuid.uuid7(), tenant_id=current_tenant(session), topic=topic, object_type=object_type, object_id=object_id,
        object_ref=object_ref, payload=jsonable(payload), actor=principal.actor if principal else "system",
        occurred_at=clock.now(),
    )
    session.add(event)
    session.flush()
    return event


def envelope(event: OutboxEvent) -> dict:
    return {
        "eventId": str(event.id), "tenantId": str(event.tenant_id), "type": event.topic,
        "occurredAt": event.occurred_at.isoformat(), "actor": event.actor,
        "objectRef": {"type": event.object_type, "id": str(event.object_id), "ref": event.object_ref},
        "version": event.schema_version, "traceId": event.trace_id, "data": event.payload,
    }


def _publish_external(event: OutboxEvent) -> None:
    """Hook for Kafka/Pub-Sub publishing (topic pic.<tier>.<event>). Not configured in this deployment."""
    return None


def _dispatch(session: Session, event: OutboxEvent) -> None:
    for name, fn in _consumers.get(event.topic, []):
        if session.get(ProcessedEvent, (name, event.id)):
            continue
        with session.begin_nested():
            fn(session, event)
            session.add(ProcessedEvent(tenant_id=event.tenant_id, consumer=name, event_id=event.id))


MAX_ATTEMPTS = 8
RETRY_BASE_SECONDS = 30  # back-off after a failed delivery: 30 s, 60 s, 2 min, ... capped at RETRY_MAX_SECONDS
RETRY_MAX_SECONDS = 3600
# Durable back-off needs outbox_event.next_attempt_at (migration 0007); until the model has it, failed events wait in this
# per-process map (the long-running worker) and are never re-picked within the same relay pass.
_retry_after: dict[uuid.UUID, float] = {}


def _backoff_seconds(attempts: int) -> int:
    return min(RETRY_BASE_SECONDS * 2 ** max(attempts - 1, 0), RETRY_MAX_SECONDS)


def relay_tenant(tenant_id: uuid.UUID, limit: int = 200) -> int:
    """Publish pending events for one tenant. Consumers may emit further events; loop until drained. An event whose consumer
    failed is retried with back-off (not again in this pass) and dead-lettered after MAX_ATTEMPTS."""
    from app.pic.platform.auth import Principal  # local import avoids a cycle
    published = 0
    failed: set[uuid.UUID] = set()
    durable = getattr(OutboxEvent, "next_attempt_at", None)
    for _ in range(25):
        with tenant_tx(tenant_id) as session:
            session.info["principal"] = Principal(
                user_id=uuid.UUID(int=0), tenant_id=tenant_id, tenant_code="", email="event-relay", name="Event relay",
                roles=[], scopes=set(), agent_code="EVENT_RELAY",
            )
            now = time.monotonic()
            waiting = failed | {k for k, until in list(_retry_after.items()) if until > now}
            query = select(OutboxEvent).where(OutboxEvent.published_at.is_(None))
            if waiting:
                query = query.where(OutboxEvent.id.not_in(waiting))
            if durable is not None:
                query = query.where(or_(durable.is_(None), durable <= clock.now()))
            pending = session.execute(
                query.order_by(OutboxEvent.occurred_at, OutboxEvent.id).limit(limit).with_for_update(skip_locked=True)
            ).scalars().all()
            if not pending:
                return published
            for event in pending:
                try:
                    _dispatch(session, event)
                    _publish_external(event)
                    event.published_at = clock.now()
                    _retry_after.pop(event.id, None)
                    published += 1
                except Exception as exc:  # keep the event for retry, record why
                    log.exception("consumer failed for %s %s", event.topic, event.id)
                    event.attempts += 1
                    event.last_error = str(exc)[:2000]
                    failed.add(event.id)
                    if event.attempts >= MAX_ATTEMPTS:
                        event.published_at = clock.now()
                        event.last_error = f"DEAD_LETTER: {event.last_error}"
                        _retry_after.pop(event.id, None)
                    else:
                        wait = _backoff_seconds(event.attempts)
                        _retry_after[event.id] = time.monotonic() + wait
                        if durable is not None:
                            setattr(event, "next_attempt_at", clock.now() + timedelta(seconds=wait))
    return published


def relay_once() -> int:
    """Relay every tenant; one tenant's failure (e.g. a lost connection) is logged and does not stop the others."""
    with system_tx() as s:
        tenant_ids = [t for t in s.execute(select(Tenant.id)).scalars()]
    published = 0
    for tenant_id in tenant_ids:
        try:
            published += relay_tenant(tenant_id)
        except Exception:  # noqa: BLE001 - isolation boundary
            obs.WORKER_TENANT_FAILURES.inc("outbox")
            log.exception("outbox relay failed for tenant %s", tenant_id)
    return published


def pending_count(session: Session) -> int:
    return len(session.execute(select(OutboxEvent.id).where(OutboxEvent.published_at.is_(None))).all())
