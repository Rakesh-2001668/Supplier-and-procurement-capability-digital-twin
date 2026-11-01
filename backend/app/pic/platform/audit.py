"""Append-only, hash-chained audit trail (§14, Appendix 19.3)."""
import hashlib
import json
import uuid
from datetime import timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import AuditArchiveBatch, AuditEvent, AuditEventArchive
from app.pic.platform import clock
from app.pic.platform.serialize import jsonable


def _actor(session: Session) -> str:
    principal = session.info.get("principal")
    return principal.actor if principal else "system"


def _canonical(event: AuditEvent) -> str:
    body = {
        "eventId": str(event.event_id),
        "objectType": event.object_type,
        "objectId": str(event.object_id),
        "action": event.action,
        "actor": event.actor,
        "onBehalfOf": event.on_behalf_of,
        "before": event.before,
        "after": event.after,
        "reason": event.reason,
        "ruleSetVersion": event.rule_set_version,
        "aiRef": event.ai_ref,
        # Normalise to UTC: the database returns timestamptz in UTC whatever zone it was written in.
        "ts": event.ts.astimezone(timezone.utc).isoformat(),
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)


def event_hash(prev: Optional[str], event) -> str:
    """The chain hash of an event (a live AuditEvent or an archived row): sha256(prev_hash + canonical body)."""
    return hashlib.sha256(((prev or "") + _canonical(event)).encode()).hexdigest()


def _chain_head(session: Session, tenant_id) -> Optional[str]:
    """Hash the next event links to: the newest live event, else the head of the newest archived batch (an archive never takes
    the newest event, so the second case only covers a trail that was archived completely by hand)."""
    prev = session.execute(
        select(AuditEvent.hash).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.seq.desc()).limit(1)
    ).scalar()
    if prev is None:
        prev = session.execute(select(AuditArchiveBatch.head_hash).where(AuditArchiveBatch.tenant_id == tenant_id)
                               .order_by(AuditArchiveBatch.seq_to.desc()).limit(1)).scalar()
    return prev


def record(session: Session, object_type: str, object_id: uuid.UUID, action: str, *,
           object_ref: Optional[str] = None, before: Any = None, after: Any = None,
           reason: Optional[str] = None, rule_set_version: Optional[str] = None,
           ai_ref: Optional[str] = None, actor: Optional[str] = None, on_behalf_of: Optional[str] = None) -> AuditEvent:
    tenant_id = current_tenant(session)
    # Serialise chain appends per tenant so prev_hash is always the true predecessor.
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"audit:{tenant_id}"})
    prev = _chain_head(session, tenant_id)
    event = AuditEvent(
        event_id=uuid.uuid7(), tenant_id=tenant_id, object_type=object_type, object_id=object_id, object_ref=object_ref,
        action=action, actor=actor or _actor(session), on_behalf_of=on_behalf_of,
        before=jsonable(before), after=jsonable(after), reason=reason, rule_set_version=rule_set_version,
        ai_ref=ai_ref, ts=clock.now(), prev_hash=prev,
    )
    event.hash = hashlib.sha256(((prev or "") + _canonical(event)).encode()).hexdigest()
    session.add(event)
    session.flush()
    return event


def verify_chain(session: Session) -> dict:
    """Recompute every hash for the current tenant; report the first break. Archived batches (audit_archive_batch) are verified
    from their rows and checkpoints: each batch must start at the previous head and end at its recorded head, and the live events
    continue from the newest batch. Batches whose rows were dropped after the statutory retention (EXPIRED) are verified by their
    checkpoints only."""
    tenant_id = current_tenant(session)
    prev = None
    count = 0
    archived = {"batches": 0, "events": 0, "expiredBatches": 0}
    batches = session.execute(select(AuditArchiveBatch).where(AuditArchiveBatch.tenant_id == tenant_id)
                              .order_by(AuditArchiveBatch.seq_from)).scalars().all()
    for batch in batches:
        if batch.anchor_hash != prev:
            return {"valid": False, "checked": count, "broken_at_seq": batch.seq_from, "batch": str(batch.id),
                    "reason": "archived batch does not start at the previous head"}
        if batch.status == "EXPIRED":
            archived["expiredBatches"] += 1
            prev = batch.head_hash
            continue
        digest = hashlib.sha256()
        seen = 0
        for event in session.execute(select(AuditEventArchive).where(AuditEventArchive.tenant_id == tenant_id,
                                                                     AuditEventArchive.batch_id == batch.id)
                                     .order_by(AuditEventArchive.seq)).scalars():
            if event.prev_hash != prev or event.hash != event_hash(prev, event):
                return {"valid": False, "checked": count, "broken_at_seq": event.seq, "event_id": str(event.event_id),
                        "batch": str(batch.id), "reason": "archived event does not match its hash"}
            digest.update(event.hash.encode())
            prev = event.hash
            seen += 1
            count += 1
        if seen != batch.event_count or prev != batch.head_hash or digest.hexdigest() != batch.content_sha256:
            return {"valid": False, "checked": count, "broken_at_seq": batch.seq_from, "batch": str(batch.id),
                    "reason": "archived batch is incomplete or altered"}
        archived["batches"] += 1
        archived["events"] += seen
    events = session.execute(
        select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.seq)
    ).scalars()
    for event in events:
        expected = event_hash(prev, event)
        if event.prev_hash != prev or event.hash != expected:
            return {"valid": False, "checked": count, "broken_at_seq": event.seq, "event_id": str(event.event_id)}
        prev = event.hash
        count += 1
    result = {"valid": True, "checked": count, "head": prev}
    if batches:
        result["archived"] = archived
    return result


def trail(session: Session, object_type: str, object_id: uuid.UUID) -> list[dict]:
    events = list(session.execute(
        select(AuditEvent).where(AuditEvent.object_type == object_type, AuditEvent.object_id == object_id).order_by(AuditEvent.seq)
    ).scalars())
    # Events moved to the audit archive stay part of the object's trail.
    archived = list(session.execute(
        select(AuditEventArchive).where(AuditEventArchive.object_type == object_type, AuditEventArchive.object_id == object_id)
        .order_by(AuditEventArchive.seq)).scalars())
    return [
        {"eventId": str(e.event_id), "seq": e.seq, "objectType": e.object_type, "objectId": str(e.object_id),
         "objectRef": e.object_ref, "action": e.action, "actor": e.actor, "onBehalfOf": e.on_behalf_of,
         "reason": e.reason, "before": e.before, "after": e.after, "ruleSetVersion": e.rule_set_version,
         "aiRef": e.ai_ref, "ts": e.ts.isoformat(), "prevHash": e.prev_hash, "hash": e.hash}
        for e in archived + events
    ]
