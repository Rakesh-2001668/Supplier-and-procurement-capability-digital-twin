"""Exactly-once ERP integration (§12.2, P13).

1. The domain service writes an ``integration_message`` (PENDING) in the same
   transaction as the business change, keyed by (tenant, target, idempotency key).
2. The connector worker posts it. Before any retry it queries the ERP by
   external reference, so a lost response never causes a second posting.
3. Failures back off exponentially; after 8 attempts the message is dead-lettered
   and can be replayed from ADM-05.

``SapS4Connector`` simulates the SAP S/4HANA sandbox with the ``erp_document``
table. Replace ``post``/``lookup`` with OData calls for a real system.
"""
import hashlib
import json
import uuid
from datetime import timedelta
from typing import Callable, Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.pic.db import current_tenant, current_user, tenant_tx
from app.pic.models import ErpDocument, IntegrationMessage
from app.pic.platform import audit, clock
from app.pic.platform.errors import Problem, not_found
from app.pic.platform.serialize import jsonable

MAX_ATTEMPTS = 8
_on_posted: dict[str, Callable[[Session, IntegrationMessage], None]] = {}

# Fault injection for resilience tests: {"fail": n} raises before posting,
# {"lose_response": n} posts in the ERP and then loses the response.
FAULTS: dict[str, int] = {"fail": 0, "lose_response": 0}

DOC_TYPES = {
    "SUPPLIER_INVOICE": ("RE", 5100004421),
    "PURCHASE_ORDER": ("NB", 4500018820),
    "GOODS_RECEIPT": ("WE", 5000071230),
    "MATERIAL_MASTER": ("MM", 100000331),
    "SUPPLIER_MASTER": ("KR", 300001),
    "PAYMENT": ("ZP", 1500002210),
}


def on_posted(message_type: str):
    def decorator(fn):
        _on_posted[message_type] = fn
        return fn
    return decorator


def enqueue(session: Session, *, target_system: str, message_type: str, idempotency_key: str, object_type: str,
            object_id: uuid.UUID, object_ref: str, payload: dict) -> IntegrationMessage:
    payload = jsonable(payload)
    payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    existing = session.execute(select(IntegrationMessage).where(
        IntegrationMessage.target_system == target_system, IntegrationMessage.idempotency_key == idempotency_key)).scalar_one_or_none()
    if existing:
        if existing.payload_hash != payload_hash:
            raise Problem(409, "IDEMPOTENCY_CONFLICT", f"Key {idempotency_key} was already used for a different {message_type}")
        return existing
    message = IntegrationMessage(
        tenant_id=current_tenant(session), target_system=target_system, message_type=message_type,
        idempotency_key=idempotency_key, object_type=object_type, object_id=object_id, object_ref=object_ref,
        payload=payload, payload_hash=payload_hash, status="PENDING", next_attempt_at=clock.now(),
        created_by=current_user(session),
    )
    session.add(message)
    session.flush()
    return message


class ConnectorTimeout(Exception):
    pass


class SapS4Connector:
    system = "SAP_S4"

    def lookup(self, session: Session, external_ref: str) -> Optional[ErpDocument]:
        return session.execute(select(ErpDocument).where(ErpDocument.system == self.system,
                                                         ErpDocument.external_ref == external_ref)).scalar_one_or_none()

    def post(self, session: Session, message: IntegrationMessage) -> str:
        if FAULTS["fail"] > 0:
            FAULTS["fail"] -= 1
            raise ConnectorTimeout("ERP did not answer (simulated)")
        doc_type, start = DOC_TYPES[message.message_type]
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"erp:{current_tenant(session)}:{doc_type}"})
        last = session.execute(select(func.max(ErpDocument.doc_no)).where(ErpDocument.system == self.system,
                                                                         ErpDocument.doc_type == doc_type)).scalar()
        doc_no = str(int(last) + 1) if last else str(start)
        session.add(ErpDocument(
            tenant_id=current_tenant(session), system=self.system, doc_type=doc_type, doc_no=doc_no,
            external_ref=message.idempotency_key, company_code=message.payload.get("companyCode", "1000"),
            amount_minor=message.payload.get("grossMinor"), payload=message.payload,
        ))
        session.flush()
        return doc_no

    def after_post(self) -> None:
        """The ERP has committed the document; the response may still be lost on the way back."""
        if FAULTS["lose_response"] > 0:
            FAULTS["lose_response"] -= 1
            raise ConnectorTimeout("ERP posted but the response was lost (simulated)")


CONNECTORS = {"SAP_S4": SapS4Connector()}


def process(session: Session, message: IntegrationMessage) -> IntegrationMessage:
    if message.status == "POSTED":
        return message
    connector = CONNECTORS[message.target_system]
    message.attempts += 1
    # Query-before-retry: if the ERP already has the document, acknowledge without reposting.
    existing = connector.lookup(session, message.idempotency_key)
    try:
        if existing is not None:
            doc_no = existing.doc_no
        else:
            with session.begin_nested():
                doc_no = connector.post(session, message)
            connector.after_post()
    except ConnectorTimeout as exc:
        existing = connector.lookup(session, message.idempotency_key)
        if existing is None:
            message.last_error = str(exc)
            if message.attempts >= MAX_ATTEMPTS:
                message.status = "DEAD_LETTER"
                audit.record(session, message.object_type, message.object_id, "INTEGRATION_DEAD_LETTER",
                             object_ref=message.object_ref, after={"attempts": message.attempts}, reason=str(exc))
            else:
                message.status = "RETRY"
                message.next_attempt_at = clock.now() + timedelta(minutes=2 ** message.attempts)
            return message
        doc_no = existing.doc_no
    message.status = "POSTED"
    message.erp_doc_no = doc_no
    message.posted_at = clock.now()
    message.last_error = None
    audit.record(session, message.object_type, message.object_id, "ERP_POSTED", object_ref=message.object_ref,
                 after={"system": message.target_system, "erpDocument": doc_no, "key": message.idempotency_key,
                        "attempts": message.attempts})
    handler = _on_posted.get(message.message_type)
    if handler:
        handler(session, message)
    return message


def run_pending(tenant_id: uuid.UUID, principal) -> int:
    processed = 0
    with tenant_tx(tenant_id, principal.user_id, principal) as session:
        messages = session.execute(
            select(IntegrationMessage).where(IntegrationMessage.status.in_(("PENDING", "RETRY")),
                                             IntegrationMessage.next_attempt_at <= clock.now())
            .order_by(IntegrationMessage.created_at).with_for_update(skip_locked=True)
        ).scalars().all()
        for message in messages:
            process(session, message)
            processed += 1
    return processed


def replay(session: Session, message_id: uuid.UUID) -> IntegrationMessage:
    message = session.get(IntegrationMessage, message_id)
    if message is None:
        raise not_found("Integration message", message_id)
    if message.status == "POSTED":
        raise Problem(409, "ALREADY_POSTED", f"Message already posted as {message.erp_doc_no}")
    message.status = "PENDING"
    message.attempts = 0
    message.next_attempt_at = clock.now()
    audit.record(session, message.object_type, message.object_id, "INTEGRATION_REPLAY", object_ref=message.object_ref)
    return process(session, message)
