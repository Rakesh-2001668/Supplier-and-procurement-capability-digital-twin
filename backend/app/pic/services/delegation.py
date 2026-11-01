"""Delegation of authority (out-of-office approvers), TD §8 / enterprise expectation.

A person (the delegator) hands their approval tasks to a colleague (the delegate) for a period, optionally for some of their roles
and up to a value. How a delegation is *applied* is in platform/workflow.py (can_work, open_tasks_for, complete); this module
creates and revokes delegations with their controls, audits them, emits ``delegation.created`` / ``delegation.revoked`` and
notifies both people (and the delegate of every open task that becomes workable).

Controls: the delegate is an active internal user other than the delegator; the period is today or later and at most rule
DELEGATION ``maxDays`` (90) long; role scope is a subset of the delegator's roles; no overlapping delegation of the same pair, and no
two-way delegation of overlapping periods (A->B with B->A); a tenant administrator may create one for someone who is away. Whoever
the delegate is, four-eyes is evaluated per task at work time (workflow.delegated_authority), so a delegate who initiated or
already approved a document can never approve it through a delegation; the open tasks that would be blocked are reported when the
delegation is created.
"""
import uuid
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import AppUser, Delegation, OutboxEvent, Task
from app.pic.platform import audit, clock, delegation as lookup, outbox, rules, workflow
from app.pic.platform.errors import Problem, not_found
from app.pic.services import notifications
from app.pic.services.common import principal
from app.pic.services.privacy import is_erased

DEFAULT_MAX_DAYS = 90


def _user(session: Session, user_id: uuid.UUID) -> AppUser:
    user = session.get(AppUser, user_id)
    if user is None:
        raise not_found("User", user_id)
    return user


def user_by_email(session: Session, email: str) -> AppUser:
    user = session.execute(select(AppUser).where(AppUser.email == email.strip().lower())).scalar_one_or_none()
    if user is None:
        user = session.execute(select(AppUser).where(AppUser.email == email.strip())).scalar_one_or_none()
    if user is None:
        raise not_found("User", email)
    return user


def view(session: Session, d: Delegation, names: Optional[dict] = None) -> dict:
    names = names if names is not None else {}
    for uid in (d.delegator_id, d.delegate_id):
        if uid not in names:
            user = session.get(AppUser, uid)
            names[uid] = {"name": user.full_name, "email": user.email} if user is not None else {"name": "unknown", "email": ""}
    today = clock.today()
    status = d.status if d.status != "ACTIVE" else ("EXPIRED" if d.valid_to < today else ("SCHEDULED" if d.valid_from > today else "ACTIVE"))
    return {"id": str(d.id), "delegatorId": str(d.delegator_id), "delegator": names[d.delegator_id]["name"],
            "delegatorEmail": names[d.delegator_id]["email"], "delegateId": str(d.delegate_id), "delegate": names[d.delegate_id]["name"],
            "delegateEmail": names[d.delegate_id]["email"], "validFrom": d.valid_from.isoformat(), "validTo": d.valid_to.isoformat(),
            "roles": list(d.roles or []), "valueLimitMinor": d.value_limit_minor, "reason": d.reason, "status": status,
            "revokedAt": d.revoked_at.isoformat() if d.revoked_at else None, "revokeReason": d.revoke_reason,
            "createdAt": d.created_at.isoformat() if d.created_at else None, "version": d.row_version}


def create(session: Session, *, delegator_id: Optional[uuid.UUID], delegate_id: uuid.UUID, valid_from: date, valid_to: date,
           roles: Optional[list[str]], value_limit_minor: Optional[int], reason: str) -> dict:
    p = principal(session)
    delegator_id = delegator_id or p.user_id
    on_behalf = delegator_id != p.user_id
    if on_behalf and "TENANT_ADMIN" not in p.roles:
        raise Problem(403, "FORBIDDEN", "Only a tenant administrator can create a delegation for someone else", rule_ref="DELEGATION")
    delegator, delegate = _user(session, delegator_id), _user(session, delegate_id)
    if delegator.id == delegate.id:
        raise Problem(422, "DELEGATE_IS_DELEGATOR", "You cannot delegate to yourself", rule_ref="DELEGATION")
    if not delegator.active or delegator.supplier_id is not None or is_erased(delegator):
        raise Problem(409, "DELEGATOR_NOT_ELIGIBLE", "Only active internal users can delegate", rule_ref="DELEGATION")
    if not delegate.active or delegate.supplier_id is not None or is_erased(delegate):
        raise Problem(422, "DELEGATE_NOT_ELIGIBLE", "The delegate must be an active internal user", rule_ref="DELEGATION")
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise Problem(422, "REASON_REQUIRED", "Give the reason (e.g. leave from 3 to 14 November)", rule_ref="DELEGATION")
    today = clock.today()
    if valid_to < valid_from:
        raise Problem(422, "INVALID_PERIOD", "The end date is before the start date", rule_ref="DELEGATION")
    if valid_to < today:
        raise Problem(422, "INVALID_PERIOD", "The delegation would already be over", rule_ref="DELEGATION")
    try:
        max_days = int(rules.resolve(session, "DELEGATION").body.get("maxDays", DEFAULT_MAX_DAYS))
    except Problem:
        max_days = DEFAULT_MAX_DAYS
    if (valid_to - valid_from).days + 1 > max_days:
        raise Problem(422, "PERIOD_TOO_LONG", f"A delegation can run for at most {max_days} days; create a new one when it ends",
                      rule_ref="DELEGATION")
    roles = sorted({r.strip().upper() for r in (roles or []) if r and r.strip()})
    foreign = [r for r in roles if r not in (delegator.roles or [])]
    if foreign:
        raise Problem(422, "ROLE_NOT_HELD", f"{delegator.full_name} does not hold {', '.join(foreign)}", rule_ref="DELEGATION")
    if value_limit_minor is not None and value_limit_minor <= 0:
        raise Problem(422, "INVALID_LIMIT", "The value limit must be positive", rule_ref="DELEGATION")
    overlapping = session.execute(select(Delegation).where(
        Delegation.status == "ACTIVE", Delegation.valid_from <= valid_to, Delegation.valid_to >= valid_from,
        ((Delegation.delegator_id == delegator.id) & (Delegation.delegate_id == delegate.id))
        | ((Delegation.delegator_id == delegate.id) & (Delegation.delegate_id == delegator.id)))).scalars().all()
    if overlapping:
        loop = overlapping[0].delegator_id == delegate.id
        raise Problem(409, "DELEGATION_LOOP" if loop else "DELEGATION_OVERLAP",
                      ("The delegate already delegates to you in this period" if loop
                       else "There is already a delegation to this person in this period; revoke it first"), rule_ref="DELEGATION")
    d = Delegation(tenant_id=p.tenant_id, delegator_id=delegator.id, delegate_id=delegate.id, valid_from=valid_from, valid_to=valid_to,
                   roles=roles, value_limit_minor=value_limit_minor, reason=reason, status="ACTIVE", created_by=p.user_id)
    session.add(d)
    session.flush()
    lookup.invalidate(session)
    blocked = _blocked_tasks(session, delegator, delegate, roles)
    out = view(session, d)
    out["blockedTasks"] = blocked
    audit.record(session, "DELEGATION", d.id, "DELEGATION_CREATED", object_ref=f"{delegator.email} -> {delegate.email}",
                 after={"validFrom": valid_from.isoformat(), "validTo": valid_to.isoformat(), "roles": roles, "valueLimitMinor": value_limit_minor,
                        "delegate": str(delegate.id), "delegator": str(delegator.id), "blockedTasks": [b["ref"] for b in blocked]},
                 reason=reason, on_behalf_of=delegator.email if on_behalf else None, rule_set_version="DELEGATION")
    outbox.emit(session, "delegation.created", "DELEGATION", d.id, f"{delegator.email} -> {delegate.email}",
                {"delegationId": str(d.id), "delegatorId": str(delegator.id), "delegateId": str(delegate.id), "validFrom": valid_from.isoformat(),
                 "validTo": valid_to.isoformat(), "roles": roles, "valueLimitMinor": value_limit_minor, "createdByAdmin": on_behalf})
    return out


def _blocked_tasks(session: Session, delegator: AppUser, delegate: AppUser, roles: list[str]) -> list[dict]:
    """Open tasks the delegator can work today that the delegate could never work for them (four-eyes: he initiated or already
    approved the document)."""
    delegator_p = lookup.principal_of(delegator)
    out = []
    for task in session.execute(select(Task).where(Task.status == "OPEN")).scalars():
        if roles and task.candidate_role not in roles:
            continue
        if workflow.can_work(delegator_p, task) is None and delegate.id in (task.excluded_user_ids or []):
            out.append({"ref": task.object_ref, "task": task.name, "reason": "four-eyes: the delegate initiated or already approved this document"})
    return out


def revoke(session: Session, delegation_id: uuid.UUID, reason: str) -> dict:
    p = principal(session)
    d = session.get(Delegation, delegation_id, with_for_update=True)
    if d is None:
        raise not_found("Delegation", delegation_id)
    if p.user_id not in (d.delegator_id, d.delegate_id) and "TENANT_ADMIN" not in p.roles:
        raise Problem(403, "FORBIDDEN", "Only the delegator, the delegate or a tenant administrator can revoke a delegation", rule_ref="DELEGATION")
    if d.status != "ACTIVE":
        raise Problem(409, "ALREADY_REVOKED", "This delegation is already revoked", rule_ref="DELEGATION")
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for revoking", rule_ref="DELEGATION")
    d.status, d.revoked_at, d.revoked_by, d.revoke_reason = "REVOKED", clock.now(), p.user_id, reason
    session.flush()
    lookup.invalidate(session)
    audit.record(session, "DELEGATION", d.id, "DELEGATION_REVOKED", object_ref=str(d.id), before={"status": "ACTIVE"}, after={"status": "REVOKED"},
                 reason=reason, rule_set_version="DELEGATION")
    outbox.emit(session, "delegation.revoked", "DELEGATION", d.id, str(d.id),
                {"delegationId": str(d.id), "delegatorId": str(d.delegator_id), "delegateId": str(d.delegate_id), "revokedBy": str(p.user_id),
                 "reason": reason})
    return view(session, d)


def mine(session: Session) -> dict:
    p = principal(session)
    names: dict = {}
    given = session.execute(select(Delegation).where(Delegation.delegator_id == p.user_id).order_by(Delegation.valid_from.desc())).scalars().all()
    received = session.execute(select(Delegation).where(Delegation.delegate_id == p.user_id).order_by(Delegation.valid_from.desc())).scalars().all()
    return {"given": [view(session, d, names) for d in given], "received": [view(session, d, names) for d in received]}


def overview(session: Session, status: Optional[str] = None, limit: int = 200) -> list[dict]:
    names: dict = {}
    rows = session.execute(select(Delegation).order_by(Delegation.valid_from.desc()).limit(limit)).scalars().all()
    views = [view(session, d, names) for d in rows]
    return [v for v in views if status is None or v["status"] == status.upper()]


def candidates(session: Session) -> list[dict]:
    """Colleagues a user can pick as delegate (active internal users; name, e-mail, roles)."""
    p = principal(session)
    users = session.execute(select(AppUser).where(AppUser.active.is_(True), AppUser.supplier_id.is_(None), AppUser.id != p.user_id)
                            .order_by(AppUser.full_name)).scalars()
    return [{"id": str(u.id), "name": u.full_name, "email": u.email, "roles": list(u.roles or [])} for u in users if not is_erased(u)]


# ---------------------------------------------------------------- events -> notifications
def _event_delegation(session: Session, event: OutboxEvent) -> Optional[Delegation]:
    return session.get(Delegation, event.object_id)


@outbox.consumer("delegation.created", "notify-delegation-created")
def _created(session: Session, event: OutboxEvent) -> None:
    d = _event_delegation(session, event)
    if d is None or d.status != "ACTIVE":
        return
    delegator, delegate = _user(session, d.delegator_id), _user(session, d.delegate_id)
    scope = (f" for the role(s) {', '.join(r.replace('_', ' ').lower() for r in d.roles)}" if d.roles else "") + (
        f" up to ₹{d.value_limit_minor / 100:,.2f}" if d.value_limit_minor else "")
    period = f"{d.valid_from.isoformat()} to {d.valid_to.isoformat()}"
    notifications.notify(session, [delegate], kind="DELEGATION", dedup_key=f"DELEGATION_CREATED:{d.id}:delegate",
                         title=f"{delegator.full_name} delegated their approvals to you",
                         body=f"From {period}{scope}, you can decide {delegator.full_name}'s approval tasks; your decisions are recorded on "
                              f"their behalf. Reason: {d.reason}", link="/pic/tasks", object_type="DELEGATION", object_ref=str(d.id))
    notifications.notify(session, [delegator], kind="DELEGATION", dedup_key=f"DELEGATION_CREATED:{d.id}:delegator",
                         title=f"Delegation to {delegate.full_name} is set",
                         body=f"{delegate.full_name} can decide your approval tasks from {period}{scope}. You can revoke it at any time under "
                              "My account.", link="/pic/account", object_type="DELEGATION", object_ref=str(d.id))


@outbox.consumer("delegation.revoked", "notify-delegation-revoked")
def _revoked(session: Session, event: OutboxEvent) -> None:
    d = _event_delegation(session, event)
    if d is None:
        return
    delegator, delegate = _user(session, d.delegator_id), _user(session, d.delegate_id)
    body = f"The delegation from {delegator.full_name} to {delegate.full_name} ({d.valid_from.isoformat()} to {d.valid_to.isoformat()}) " \
           f"was revoked. Reason: {d.revoke_reason}"
    notifications.notify(session, [delegate, delegator], kind="DELEGATION", dedup_key=f"DELEGATION_REVOKED:{d.id}", title="Delegation revoked",
                         body=body, link="/pic/account", object_type="DELEGATION", object_ref=str(d.id))

