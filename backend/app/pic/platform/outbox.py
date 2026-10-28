"""Transactional outbox and in-process event consumers (AD-03, §11).

``emit`` writes the event in the caller's transaction, so an event exists if
and only if the business change committed. ``relay_once`` publishes pending
events to registered consumers; each consumer is idempotent through
``processed_event``. A Kafka producer can be added in ``_publish_external``
without changing producers or consumers.
"""
import logging
import uuid
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant, system_tx, tenant_tx
from app.pic.models import OutboxEvent, ProcessedEvent, Tenant
from app.pic.platform import clock
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


def relay_tenant(tenant_id: uuid.UUID, limit: int = 200) -> int:
    """Publish pending events for one tenant. Consumers may emit further events; loop until drained."""
    from app.pic.platform.auth import Principal  # local import avoids a cycle
    published = 0
    for _ in range(25):
        with tenant_tx(tenant_id) as session:
            session.info["principal"] = Principal(
                user_id=uuid.UUID(int=0), tenant_id=tenant_id, tenant_code="", email="event-relay", name="Event relay",
                roles=[], scopes=set(), agent_code="EVENT_RELAY",
            )
            pending = session.execute(
                select(OutboxEvent).where(OutboxEvent.published_at.is_(None)).order_by(OutboxEvent.occurred_at, OutboxEvent.id)
                .limit(limit).with_for_update(skip_locked=True)
            ).scalars().all()
            if not pending:
                return published
            for event in pending:
                try:
                    _dispatch(session, event)
                    _publish_external(event)
                    event.published_at = clock.now()
                    published += 1
                except Exception as exc:  # keep the event for retry, record why
                    log.exception("consumer failed for %s %s", event.topic, event.id)
                    event.attempts += 1
                    event.last_error = str(exc)[:2000]
                    if event.attempts >= 8:
                        event.published_at = clock.now()
                        event.last_error = f"DEAD_LETTER: {event.last_error}"
    return published


def relay_once() -> int:
    with system_tx() as s:
        tenant_ids = [t for t in s.execute(select(Tenant.id)).scalars()]
    return sum(relay_tenant(t) for t in tenant_ids)


def pending_count(session: Session) -> int:
    return len(session.execute(select(OutboxEvent.id).where(OutboxEvent.published_at.is_(None))).all())
