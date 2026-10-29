"""M13 in-app notifications and e-mail delivery.

Consumers turn domain events into one notification per recipient:
- task.assigned / task.escalated (workflow engine): users who can work the task — candidate role, scope (cost object, steward
  domain, category, plant) and four-eyes exclusions, using ``workflow.can_work``;
- agent recommendations (L1/L2 output, platform/agents.py): users holding the recommendation's candidate role;
- sourcing.clarification.answered, contract.amended / contract.terminated, purchase_order.transmitted, invoice.exception.raised,
  supplier.master.changed: the internal owners and the supplier's portal users;
- sourcing.event.awarded: every invited supplier (awarded / not awarded); contract.consumption.threshold: the contract owner and
  the contract managers.
Each recipient gets a notification once per ``dedup_key``. E-mail is sent when rule NOTIFICATIONS.email is true, the kind is listed
in NOTIFICATIONS.kinds and SMTP is configured (platform/mailer.py); otherwise ``email_status`` is DISABLED (or NOT_SENT for kinds
not subscribed to e-mail). PIC_WEB_URL (optional) makes the e-mail link absolute.
"""
import os
import uuid
from typing import Iterable, Optional

from sqlalchemy import event as sa_event, func, select, update
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    AppUser, Contract, Invitee, Invoice, Notification, OutboxEvent, PurchaseOrder, Recommendation, SourcingEvent, Supplier, Task,
)
from app.pic.platform import clock, mailer, outbox, rules, workflow
from app.pic.platform.auth import Principal, scopes_for
from app.pic.platform.errors import not_found
from app.pic.platform.serialize import jsonable

RECOMMENDATION_TOPIC = "agent.recommendation.created"
ROUTES = {
    "REQUISITION": "/pic/requisitions/", "PURCHASE_ORDER": "/pic/purchase-orders/", "SOURCING_EVENT": "/pic/sourcing/",
    "CONTRACT": "/pic/contracts/", "INVOICE": "/pic/invoices/", "GOODS_RECEIPT": "/pic/receiving/", "MATERIAL_REQUEST": "/pic/materials/",
    "MRP_RUN": "/pic/mrp/", "SUPPLIER": "/pic/suppliers/",
}


def link_for(object_type: Optional[str], object_ref: Optional[str], object_id: Optional[uuid.UUID] = None,
             fallback: Optional[str] = "/pic/tasks") -> Optional[str]:
    base = ROUTES.get(object_type or "")
    if not base or not object_ref:
        return fallback
    if object_type == "INVOICE" and object_id:
        return f"{base}{object_id}"
    return f"{base}{object_ref}"


# ---------------------------------------------------------------- recipients
def _principal(user: AppUser) -> Principal:
    roles = list(user.roles or [])
    return Principal(user_id=user.id, tenant_id=user.tenant_id, tenant_code="", email=user.email, name=user.full_name, roles=roles,
                     scopes=scopes_for(roles), attributes=user.attributes or {}, supplier_id=user.supplier_id)


def users_with_role(session: Session, role: str) -> list[AppUser]:
    return list(session.execute(select(AppUser).where(AppUser.active.is_(True), AppUser.roles.any(role))
                                .order_by(AppUser.email)).scalars())


def task_workers(session: Session, task: Task) -> list[AppUser]:
    """Everyone who could complete the task now (same rules as the task inbox and ``workflow.complete``)."""
    return [u for u in users_with_role(session, task.candidate_role) if workflow.can_work(_principal(u), task) is None]


def supplier_users(session: Session, supplier_id: Optional[uuid.UUID]) -> list[AppUser]:
    if supplier_id is None:
        return []
    return list(session.execute(select(AppUser).where(AppUser.active.is_(True), AppUser.supplier_id == supplier_id)).scalars())


def _user(session: Session, user_id: Optional[uuid.UUID]) -> list[AppUser]:
    user = session.get(AppUser, user_id) if user_id else None
    return [user] if user is not None and user.active else []


# ---------------------------------------------------------------- delivery
def _email_policy(session: Session) -> tuple[bool, Optional[set]]:
    try:
        body = rules.resolve(session, "NOTIFICATIONS").body
    except Exception:  # noqa: BLE001 - a tenant without the rule set gets in-app notifications only
        return False, None
    kinds = body.get("kinds")
    return bool(body.get("email")), set(kinds) if kinds else None


def notify(session: Session, users: Iterable[AppUser], *, kind: str, title: str, body: str, dedup_key: str,
           link: Optional[str] = None, object_type: Optional[str] = None, object_ref: Optional[str] = None) -> list[Notification]:
    email_on, kinds = _email_policy(session)
    web = (os.environ.get("PIC_WEB_URL") or "").rstrip("/")
    created, seen = [], set()
    for user in users:
        if user is None or user.id in seen:
            continue
        seen.add(user.id)
        exists = session.execute(select(Notification.id).where(Notification.user_id == user.id, Notification.dedup_key == dedup_key)
                                 .limit(1)).first()
        if exists:
            continue
        note = Notification(tenant_id=current_tenant(session), user_id=user.id, kind=kind, title=title[:200], body=body, link=link,
                            object_type=object_type, object_ref=(object_ref or "")[:60] or None, dedup_key=dedup_key[:160],
                            email_status="DISABLED")
        if email_on and mailer.configured():
            if kinds is not None and kind not in kinds:
                note.email_status = "NOT_SENT"
            else:
                text = f"{body}\n\n{web}{link}" if web and link else body
                note.email_status = mailer.send(user.email, f"[PIC] {title}", text)
                if note.email_status == "SENT":
                    note.emailed_at = clock.now()
        session.add(note)
        created.append(note)
    session.flush()
    return created


# ---------------------------------------------------------------- workflow tasks
def _task(session: Session, event: OutboxEvent) -> Optional[Task]:
    task = session.get(Task, event.object_id)
    return task if task is not None and task.status == "OPEN" else None


def _label(kind: str) -> str:
    return kind.replace("_", " ").capitalize()


@outbox.consumer("task.assigned", "notify-task-assigned")
def _task_assigned(session: Session, event: OutboxEvent) -> None:
    task = _task(session, event)
    if task is None:
        return
    due = task.due_at.astimezone(clock.IST).strftime("%d %b %Y %H:%M") if task.due_at else "no due date"
    notify(session, task_workers(session, task), kind="TASK_ASSIGNED", dedup_key=f"TASK_ASSIGNED:{task.id}",
           title=f"{_label(task.kind)}: {task.object_ref}", body=f"{task.name} is waiting for you. Due {due} IST.",
           link=link_for(task.object_type, task.object_ref, task.object_id), object_type=task.object_type, object_ref=task.object_ref)


@outbox.consumer("task.escalated", "notify-task-escalated")
def _task_escalated(session: Session, event: OutboxEvent) -> None:
    task = _task(session, event)
    if task is None:
        return
    level = event.payload.get("level", task.escalation_level)
    link = link_for(task.object_type, task.object_ref, task.object_id)
    # Rule ESCALATION added a manager role as candidate (workflow._escalate): its eligible holders are told first (four-eyes
    # exclusions and scope apply through can_work); every notification below shares the dedup key, so nobody gets two.
    target = event.payload.get("escalatedTo")
    if target:
        managers = [u for u in users_with_role(session, target) if workflow.can_work(_principal(u), task) is None]
        notify(session, managers, kind="TASK_ESCALATED", dedup_key=f"TASK_ESCALATED:{task.id}:{level}",
               title=f"Escalated to you: {task.object_ref}",
               body=f"{task.name} passed its SLA (escalation {level}); as {target.replace('_', ' ').lower()} you can now decide it.",
               link=link, object_type=task.object_type, object_ref=task.object_ref)
    escalated = [e.get("role") for e in (task.candidate_scope or {}).get(workflow.ESCALATION_KEY) or []]
    others = [u for role in escalated for u in users_with_role(session, role) if workflow.can_work(_principal(u), task) is None]
    notify(session, task_workers(session, task) + others, kind="TASK_ESCALATED", dedup_key=f"TASK_ESCALATED:{task.id}:{level}",
           title=f"Overdue (escalation {level}): {task.object_ref}", body=f"{task.name} has passed its SLA and was escalated.",
           link=link, object_type=task.object_type, object_ref=task.object_ref)


# ---------------------------------------------------------------- agent recommendations
@sa_event.listens_for(Session, "before_flush")
def _recommendation_events(session: Session, flush_context, instances) -> None:
    """Emit an outbox event in the same transaction for every new Recommendation (platform/agents.py ``recommend``)."""
    for obj in list(session.new):
        if not isinstance(obj, Recommendation):
            continue
        if obj.id is None:
            obj.id = uuid.uuid7()
        done = session.info.setdefault("pic_recommendation_events", set())
        if obj.id in done:
            continue
        done.add(obj.id)
        principal = session.info.get("principal")
        session.add(OutboxEvent(
            id=uuid.uuid7(), tenant_id=obj.tenant_id, topic=RECOMMENDATION_TOPIC, object_type="RECOMMENDATION", object_id=obj.id,
            object_ref=obj.object_ref, actor=principal.actor if principal else "system", occurred_at=clock.now(),
            payload=jsonable({"agent": obj.agent_code, "title": obj.title, "candidateRole": obj.candidate_role, "objectType": obj.object_type,
                              "objectId": obj.object_id, "objectRef": obj.object_ref, "deepLink": obj.deep_link,
                              "valueAtRiskMinor": obj.value_at_risk_minor}),
        ))


@outbox.consumer(RECOMMENDATION_TOPIC, "notify-recommendation")
def _recommendation(session: Session, event: OutboxEvent) -> None:
    rec = session.get(Recommendation, event.object_id)
    if rec is None or rec.status != "OPEN":
        return
    users = [u for u in users_with_role(session, rec.candidate_role) if u.supplier_id is None]
    notify(session, users, kind="RECOMMENDATION", dedup_key=f"RECOMMENDATION:{rec.id}", title=f"{rec.agent_code.replace('_', ' ').title()}: {rec.title}",
           body=rec.rationale, link=rec.deep_link or link_for(rec.object_type, rec.object_ref, rec.object_id, fallback="/pic/agents"),
           object_type=rec.object_type, object_ref=rec.object_ref)


# ---------------------------------------------------------------- document events
def _object(session: Session, event: OutboxEvent, model, object_type: str, payload_key: str):
    ref = event.payload.get(payload_key)
    if event.object_type == object_type:
        return session.get(model, event.object_id)
    try:
        return session.get(model, uuid.UUID(str(ref))) if ref else None
    except ValueError:
        return session.execute(select(model).where(getattr(model, "number" if hasattr(model, "number") else "code") == ref)).scalar_one_or_none()


@outbox.consumer("sourcing.clarification.answered", "notify-clarification")
def _clarification(session: Session, event: OutboxEvent) -> None:
    sourcing = _object(session, event, SourcingEvent, "SOURCING_EVENT", "eventId")
    if sourcing is None:
        return
    invited = session.execute(select(Invitee.supplier_id).where(Invitee.event_id == sourcing.id)).scalars().all()
    users = [u for sid in invited for u in supplier_users(session, sid)]
    notify(session, users, kind="CLARIFICATION_ANSWERED", dedup_key=f"CLARIFICATION_ANSWERED:{sourcing.id}:{event.payload.get('seq') or event.id}",
           title=f"Clarification answered: {sourcing.number}", body=event.payload.get("question") and
           f"Q: {event.payload['question']}\nA: {event.payload.get('answer', '')}" or f"A clarification on {sourcing.number} was answered for all bidders.",
           link="/pic/portal", object_type="SOURCING_EVENT", object_ref=sourcing.number)


def _contract_event(session: Session, event: OutboxEvent, kind: str, verb: str) -> None:
    contract = _object(session, event, Contract, "CONTRACT", "contractId")
    if contract is None:
        return
    internal = _user(session, contract.owner_id) + [u for u in users_with_role(session, "CONTRACT_MANAGER") if u.supplier_id is None]
    detail = event.payload.get("amendment") or event.payload.get("number") or ""
    body = f"Contract {contract.number} was {verb}{f' by {detail}' if detail else ''}." + (
        f" Reason: {event.payload['reason']}" if event.payload.get("reason") else "")
    key = f"{kind}:{contract.id}:{detail or event.id}"
    notify(session, internal, kind=kind, dedup_key=key, title=f"Contract {verb}: {contract.number}", body=body,
           link=link_for("CONTRACT", contract.number), object_type="CONTRACT", object_ref=contract.number)
    notify(session, supplier_users(session, contract.supplier_id), kind=kind, dedup_key=key, title=f"Contract {verb}: {contract.number}",
           body=body, link="/pic/portal", object_type="CONTRACT", object_ref=contract.number)


@outbox.consumer("contract.amended", "notify-contract-amended")
def _contract_amended(session: Session, event: OutboxEvent) -> None:
    _contract_event(session, event, "CONTRACT_AMENDED", "amended")


@outbox.consumer("contract.terminated", "notify-contract-terminated")
def _contract_terminated(session: Session, event: OutboxEvent) -> None:
    _contract_event(session, event, "CONTRACT_TERMINATED", "terminated")


@outbox.consumer("purchase_order.transmitted", "notify-po-transmitted")
def _po_transmitted(session: Session, event: OutboxEvent) -> None:
    po = _object(session, event, PurchaseOrder, "PURCHASE_ORDER", "po")
    if po is None:
        return
    version = event.payload.get("version", po.version)
    channel = event.payload.get("channel")
    key = f"PO_TRANSMITTED:{po.id}:v{version}:{channel or event.id}"
    notify(session, supplier_users(session, po.supplier_id), kind="PO_TRANSMITTED", dedup_key=key,
           title=f"Purchase order {po.number} (version {version})", body=f"Purchase order {po.number} version {version} was sent to you. "
           "Please review and confirm it.", link="/pic/portal", object_type="PURCHASE_ORDER", object_ref=po.number)
    notify(session, _user(session, po.created_by), kind="PO_TRANSMITTED", dedup_key=key, title=f"{po.number} transmitted",
           body=f"{po.number} version {version} was sent to the supplier{f' via {channel}' if channel else ''}.",
           link=link_for("PURCHASE_ORDER", po.number), object_type="PURCHASE_ORDER", object_ref=po.number)


@outbox.consumer("purchase_order.cancelled", "notify-po-cancelled")
def _po_cancelled(session: Session, event: OutboxEvent) -> None:
    po = _object(session, event, PurchaseOrder, "PURCHASE_ORDER", "po")
    if po is None or not event.payload.get("transmissions"):
        return  # never transmitted: the supplier never saw the order
    reason = event.payload.get("reason") or "not given"
    notify(session, supplier_users(session, po.supplier_id), kind="PO_CANCELLED", dedup_key=f"PO_CANCELLED:{po.id}",
           title=f"Purchase order {po.number} cancelled", body=f"Purchase order {po.number} (version {event.payload.get('version', po.version)}) "
           f"was cancelled by the buyer. Reason: {reason}. Please do not ship against it.", link="/pic/portal",
           object_type="PURCHASE_ORDER", object_ref=po.number)


@outbox.consumer("sourcing.event.cancelled", "notify-sourcing-cancelled")
def _sourcing_cancelled(session: Session, event: OutboxEvent) -> None:
    sourcing = _object(session, event, SourcingEvent, "SOURCING_EVENT", "eventId")
    if sourcing is None:
        return
    users = [u for sid in event.payload.get("inviteeSupplierIds") or [] for u in supplier_users(session, uuid.UUID(sid))]
    notify(session, users, kind="SOURCING_CANCELLED", dedup_key=f"SOURCING_CANCELLED:{sourcing.id}",
           title=f"Sourcing event cancelled: {sourcing.number}",
           body=f"{sourcing.number} ({sourcing.title}) was cancelled by the buyer. Reason: {event.payload.get('reason') or 'not given'}. "
           "No award will be made from this event.", link="/pic/portal", object_type="SOURCING_EVENT", object_ref=sourcing.number)


@outbox.consumer("sourcing.event.awarded", "notify-sourcing-awarded")
def _sourcing_awarded(session: Session, event: OutboxEvent) -> None:
    """F3-09: every invited supplier hears the outcome. Awarded suppliers get their share and price; the others only that the
    event was awarded elsewhere (no competitor names, prices or ranks)."""
    sourcing = _object(session, event, SourcingEvent, "SOURCING_EVENT", "eventId")
    if sourcing is None:
        return
    allocations = {str(a["supplierId"]): a for a in event.payload.get("allocations") or []}
    invited = event.payload.get("inviteeSupplierIds")
    if invited is None:  # events awarded before the payload carried the invitees
        invited = [str(i) for i in session.execute(select(Invitee.supplier_id).where(Invitee.event_id == sourcing.id)).scalars()]
    for supplier_id in dict.fromkeys([*allocations, *invited]):
        users = supplier_users(session, uuid.UUID(supplier_id))
        allocation = allocations.get(supplier_id)
        if allocation is not None:
            share = f"{float(allocation.get('share') or 0) * 100:.0f}%"
            notify(session, users, kind="SOURCING_AWARDED", dedup_key=f"SOURCING_AWARDED:{sourcing.id}:{supplier_id}",
                   title=f"Awarded: {sourcing.number}",
                   body=f"{sourcing.number} ({sourcing.title}) was awarded to you: {share} of the volume "
                        f"({allocation.get('annualQty')} {event.payload.get('uom') or ''}/year) at ₹{int(allocation.get('priceMinor') or 0) / 100:,.2f} "
                        "per unit. The contract follows for review and signature.",
                   link="/pic/portal", object_type="SOURCING_EVENT", object_ref=sourcing.number)
        else:
            notify(session, users, kind="SOURCING_NOT_AWARDED", dedup_key=f"SOURCING_NOT_AWARDED:{sourcing.id}:{supplier_id}",
                   title=f"Not awarded: {sourcing.number}",
                   body=f"Thank you for taking part in {sourcing.number} ({sourcing.title}). The event has been awarded to another "
                        "supplier; your bid was not successful this time.",
                   link="/pic/portal", object_type="SOURCING_EVENT", object_ref=sourcing.number)


@outbox.consumer("contract.consumption.threshold", "notify-contract-consumption")
def _contract_consumption(session: Session, event: OutboxEvent) -> None:
    contract = _object(session, event, Contract, "CONTRACT", "contractId")
    if contract is None:
        return
    threshold = event.payload.get("threshold")
    internal = _user(session, contract.owner_id) + [u for u in users_with_role(session, "CONTRACT_MANAGER") if u.supplier_id is None]
    notify(session, internal, kind="CONTRACT_CONSUMPTION", dedup_key=f"CONTRACT_CONSUMPTION:{contract.id}:{threshold}",
           title=f"Contract {contract.number} {threshold}% consumed",
           body=f"{contract.number} ({contract.title}) has reached {event.payload.get('consumedPct') or threshold}% of its target "
                f"quantity (alert at {threshold}%). Plan the renewal, a variation or a new sourcing event.",
           link=link_for("CONTRACT", contract.number), object_type="CONTRACT", object_ref=contract.number)


@outbox.consumer("invoice.exception.raised", "notify-invoice-exception")
def _invoice_exception(session: Session, event: OutboxEvent) -> None:
    invoice = _object(session, event, Invoice, "INVOICE", "invoiceId")
    if invoice is None:
        return
    types = ", ".join(sorted({str(e.get("type")) for e in event.payload.get("exceptions", []) if isinstance(e, dict)})) or "match exception"
    notify(session, [u for u in users_with_role(session, "AP_CLERK") if u.supplier_id is None], kind="INVOICE_EXCEPTION",
           dedup_key=f"INVOICE_EXCEPTION:{invoice.id}:{event.id}", title=f"Invoice exception: {invoice.number}",
           body=f"{invoice.number} is blocked for payment: {types}. Review the proposed resolution.",
           link=link_for("INVOICE", invoice.number, invoice.id), object_type="INVOICE", object_ref=invoice.number)


@outbox.consumer("supplier.master.changed", "notify-supplier-master")
def _supplier_master(session: Session, event: OutboxEvent) -> None:
    supplier = _object(session, event, Supplier, "SUPPLIER", "supplierId")
    if supplier is None:
        return
    group = str(event.payload.get("fieldGroup") or "master data").lower()
    change = event.payload.get("change") or event.id
    key = f"SUPPLIER_MASTER:{supplier.id}:{change}"
    notify(session, [u for u in users_with_role(session, "SUPPLIER_MANAGER") if u.supplier_id is None], kind="CHANGE_REQUEST",
           dedup_key=key, title=f"Supplier {supplier.code}: {group} changed", body=f"The {group} of {supplier.legal_name} was changed ({change}).",
           link=link_for("SUPPLIER", supplier.code), object_type="SUPPLIER", object_ref=supplier.code)
    # Security notice to the supplier's own users: changes to tax, address or contact data must never go unnoticed.
    notify(session, supplier_users(session, supplier.id), kind="CHANGE_REQUEST", dedup_key=key, title=f"Your {group} was changed",
           body=f"Your {group} on record was updated ({change}). If you did not request this, contact your buyer immediately.",
           link="/pic/portal", object_type="SUPPLIER", object_ref=supplier.code)


# ---------------------------------------------------------------- inbox
def inbox(session: Session, user_id: uuid.UUID, *, unread: Optional[bool] = None):
    query = select(Notification).where(Notification.user_id == user_id)
    if unread is True:
        query = query.where(Notification.read_at.is_(None))
    elif unread is False:
        query = query.where(Notification.read_at.is_not(None))
    return query


def unread_count(session: Session, user_id: uuid.UUID) -> int:
    return session.execute(select(func.count()).select_from(Notification).where(Notification.user_id == user_id,
                                                                              Notification.read_at.is_(None))).scalar()


def mark_read(session: Session, user_id: uuid.UUID, notification_id: uuid.UUID) -> Notification:
    note = session.get(Notification, notification_id)
    if note is None or note.user_id != user_id:
        raise not_found("Notification", notification_id)
    if note.read_at is None:
        note.read_at = clock.now()
        session.flush()
    return note


def mark_all_read(session: Session, user_id: uuid.UUID) -> int:
    result = session.execute(update(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None))
                             .values(read_at=clock.now(), row_version=Notification.row_version + 1)
                             .execution_options(synchronize_session=False))
    return result.rowcount or 0
