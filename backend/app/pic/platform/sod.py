"""Segregation of duties evaluated at command time for people and agents (§4.1, §14).

Rules are tenant data (``sod_rule``). ``guard`` checks the actor's earlier
actions on the same scope object; ``record`` logs the action once it succeeds.
A blocked attempt is written to ``sod_violation`` in its own transaction so the
evidence survives the rollback of the rejected command.

Exception path (item 46): a rule in mode MITIGATE does not only block. The actor asks for a MITIGATION
(``request_mitigation``), the approver chain configured in rule SOD-MITIGATION decides through an ordinary workflow task, and an
approved request is a grant that is time-boxed (``maxValidityHours`` by risk) and use-limited (``maxUses``), with the compensating
control text shown to the approver and kept on the grant. ``guard`` lets the original command proceed only while a valid grant
for exactly that actor, action and scope object exists; every request, decision and use is audited and reported in the admin
SoD screen. Critical risks are never mitigable (no approver chain in the rule).
"""
import uuid
from datetime import timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant, tenant_tx
from app.pic.models import ActionLog, SodMitigation, SodRule, SodViolation, Task
from app.pic.platform import audit, batch, clock, outbox, workflow
from app.pic.platform.errors import Problem, not_found

MITIGATION_KIND = "SOD_MITIGATION"
# Used when a tenant has no SOD-MITIGATION rule set (older tenants): High and below can be mitigated, Critical never.
DEFAULT_MITIGATION = {
    "approvers": {"Low": ["PROCUREMENT_HEAD"], "Medium": ["PROCUREMENT_HEAD"], "High": ["PROCUREMENT_HEAD", "CPO"]},
    "maxValidityHours": {"Low": 168, "Medium": 72, "High": 24},
    "maxUses": {"Low": 5, "Medium": 3, "High": 1},
    "compensatingControls": {"default": "The approver reviews every transaction the actor completes under this exception within five "
                                        "working days and confirms it in the audit trail."},
    "minJustificationLength": 20, "slaBusinessDays": 2,
}


def _principal(session: Session):
    principal = session.info.get("principal")
    if principal is None:
        raise RuntimeError("SoD check needs a principal on the session")
    return principal


def record(session: Session, action: str, refs: dict, actor_id: Optional[uuid.UUID] = None) -> None:
    principal = _principal(session)
    session.add(ActionLog(
        tenant_id=current_tenant(session), actor_id=actor_id or principal.user_id, action=action,
        refs={k: str(v) for k, v in refs.items() if v is not None}, is_agent=principal.is_agent,
        created_by=principal.user_id,
    ))
    session.flush()
    if batch.active(session):  # keep the batch's remembered "what the actor already did" current
        for scope, value in refs.items():
            seen = batch.peek(session, ("sod-did", actor_id or principal.user_id, action, scope))
            if seen is not None and value is not None:
                seen.add(str(value))


def _did(session: Session, actor_id: uuid.UUID, action: str, scope: str, scope_value: str) -> bool:
    if batch.active(session):  # one query per (actor, action, scope) for the whole batch; record() keeps the set current
        values = batch.memo(session, ("sod-did", actor_id, action, scope), lambda: set(session.execute(
            select(ActionLog.refs[scope].astext).where(ActionLog.actor_id == actor_id, ActionLog.action == action).distinct()).scalars()))
        return scope_value in values
    return session.execute(
        select(ActionLog.id).where(
            ActionLog.actor_id == actor_id, ActionLog.action == action,
            ActionLog.refs[scope].astext == scope_value,
        ).limit(1)
    ).first() is not None


def _sole_evaluator(session: Session, actor_id: uuid.UUID, event_id: str) -> bool:
    evaluators = session.execute(
        select(ActionLog.actor_id).where(ActionLog.action == "BID_SCORE", ActionLog.refs["event_id"].astext == event_id).distinct()
    ).scalars().all()
    return len(evaluators) == 1 and evaluators[0] == actor_id


def conflicts(session: Session, action: str, refs: dict, actor_id: uuid.UUID) -> list[SodRule]:
    hits = []
    rules = batch.memo(session, "sod-rules", lambda: session.execute(select(SodRule).where(SodRule.active.is_(True))).scalars().all())
    for rule in rules:
        if action not in (rule.action_a, rule.action_b):
            continue
        other = rule.action_b if action == rule.action_a else rule.action_a
        scope_value = refs.get(rule.scope)
        if scope_value is None:
            continue
        scope_value = str(scope_value)
        if rule.condition == "SOLE_EVALUATOR":
            if action == "SOURCING_AWARD" and _sole_evaluator(session, actor_id, scope_value):
                hits.append(rule)
            continue
        if _did(session, actor_id, other, rule.scope, scope_value):
            hits.append(rule)
    return hits


def _log_violation(tenant_id: uuid.UUID, rule: SodRule, actor_id: uuid.UUID, action: str, refs: dict, outcome: str) -> None:
    with tenant_tx(tenant_id) as s:
        s.add(SodViolation(
            tenant_id=tenant_id, rule_code=rule.code, actor_id=actor_id, attempted_action=action,
            conflicting_action=rule.action_b if action == rule.action_a else rule.action_a,
            refs={k: str(v) for k, v in refs.items() if v is not None}, outcome=outcome, created_by=actor_id,
        ))


def guard(session: Session, action: str, refs: dict, actor_id: Optional[uuid.UUID] = None) -> None:
    principal = _principal(session)
    actor_id = actor_id or principal.user_id
    for rule in conflicts(session, action, refs, actor_id):
        if rule.mode == "MITIGATE":
            grant = _valid_grant(session, rule, actor_id, action, refs)
            if grant is not None:
                _use(session, grant, rule, actor_id, action, refs)
                continue
            _log_violation(current_tenant(session), rule, actor_id, action, refs, "MITIGATION_REQUIRED")
            terms = _terms(session, rule)
            hint = (f"This rule allows an approved exception: request a mitigation (approvers: {', '.join(terms['approverRoles'])})."
                    if terms["approverRoles"] else "This risk level cannot be mitigated.")
            raise Problem(409, "SOD_CONFLICT", f"{rule.code}: {rule.description}. {hint}", rule_ref=rule.code, risk=rule.risk,
                          mitigation=offer(session, rule, action, refs, actor_id))
        _log_violation(current_tenant(session), rule, actor_id, action, refs, "BLOCKED")
        raise Problem(409, "SOD_CONFLICT", f"{rule.code}: {rule.description}", rule_ref=rule.code, risk=rule.risk)


def guard_and_record(session: Session, action: str, refs: dict) -> None:
    guard(session, action, refs)
    record(session, action, refs)


# ---------------------------------------------------------------- mitigation (item 46)
def _policy(session: Session) -> tuple[dict, Optional[str]]:
    from app.pic.platform import rules  # local import: rules has no dependency on sod
    try:
        rule = rules.resolve(session, "SOD-MITIGATION")
        return rule.body, rule.ref
    except Problem:
        return DEFAULT_MITIGATION, None


def _terms(session: Session, rule: SodRule) -> dict:
    """Who may approve an exception for this rule, for how long and how often, and the compensating control. approverRoles is
    empty when the risk is not mitigable (Critical)."""
    body, ref = _policy(session)
    risk = rule.risk
    controls = body.get("compensatingControls") or {}
    return {"approverRoles": list((body.get("approvers") or {}).get(risk) or []),
            "maxValidityHours": int((body.get("maxValidityHours") or {}).get(risk) or 0),
            "maxUses": int((body.get("maxUses") or {}).get(risk) or 1),
            "compensatingControl": controls.get(rule.code) or controls.get("default") or "",
            "minJustificationLength": int(body.get("minJustificationLength", 20)),
            "slaBusinessDays": int(body.get("slaBusinessDays", 2)), "ruleRef": ref}


def _scope_value(rule: SodRule, refs: dict) -> str:
    return str(refs[rule.scope])


def _valid_grant(session: Session, rule: SodRule, actor_id: uuid.UUID, action: str, refs: dict, lock: bool = True) -> Optional[SodMitigation]:
    now = clock.now()
    query = select(SodMitigation).where(
        SodMitigation.rule_code == rule.code, SodMitigation.requester_id == actor_id, SodMitigation.action == action,
        SodMitigation.scope_value == _scope_value(rule, refs), SodMitigation.status == "APPROVED",
        SodMitigation.valid_from <= now, SodMitigation.valid_until > now, SodMitigation.use_count < SodMitigation.max_uses,
    ).order_by(SodMitigation.valid_until).limit(1)
    return session.execute(query.with_for_update() if lock else query).scalar_one_or_none()


def _use(session: Session, grant: SodMitigation, rule: SodRule, actor_id: uuid.UUID, action: str, refs: dict) -> None:
    grant.use_count += 1
    grant.last_used_at = clock.now()
    session.add(SodViolation(
        tenant_id=current_tenant(session), rule_code=rule.code, actor_id=actor_id, attempted_action=action,
        conflicting_action=rule.action_b if action == rule.action_a else rule.action_a,
        refs={k: str(v) for k, v in refs.items() if v is not None}, outcome="MITIGATED", created_by=actor_id))
    audit.record(session, "SOD_MITIGATION", grant.id, "USED", object_ref=_ref(grant),
                 after={"rule": rule.code, "action": action, "use": grant.use_count, "of": grant.max_uses,
                        "validUntil": grant.valid_until.isoformat()}, reason=f"Conflict {rule.code} proceeded under approved mitigation")


def _ref(m: SodMitigation) -> str:
    return f"{m.rule_code}/{str(m.id)[-8:]}"


def offer(session: Session, rule: SodRule, action: str, refs: dict, actor_id: uuid.UUID) -> dict:
    """What the 409 tells the client about the exception path (the body of POST /v1/sod/mitigations to send back)."""
    terms = _terms(session, rule)
    pending = session.execute(select(SodMitigation.id).where(
        SodMitigation.rule_code == rule.code, SodMitigation.requester_id == actor_id, SodMitigation.action == action,
        SodMitigation.scope_value == _scope_value(rule, refs), SodMitigation.status == "PENDING")).scalar_one_or_none()
    return {"available": bool(terms["approverRoles"]), "ruleCode": rule.code, "action": action,
            "refs": {k: str(v) for k, v in refs.items() if v is not None}, "approverRoles": terms["approverRoles"],
            "maxValidityHours": terms["maxValidityHours"], "compensatingControl": terms["compensatingControl"],
            "pendingRequest": str(pending) if pending else None}


def request_mitigation(session: Session, *, rule_code: str, action: str, refs: dict, justification: str,
                       validity_hours: Optional[int] = None) -> SodMitigation:
    """Ask for an exception to a conflict the actor just hit. The conflict must exist now; Critical rules and BLOCK-mode rules have
    no exception path."""
    principal = _principal(session)
    rule = session.execute(select(SodRule).where(SodRule.code == rule_code, SodRule.active.is_(True))).scalar_one_or_none()
    if rule is None:
        raise not_found("SoD rule", rule_code)
    if rule.mode != "MITIGATE":
        raise Problem(422, "NOT_MITIGABLE", f"{rule.code} blocks without an exception path (mode {rule.mode})", rule_ref=rule.code)
    terms = _terms(session, rule)
    if not terms["approverRoles"]:
        raise Problem(422, "NOT_MITIGABLE", f"{rule.code} is {rule.risk} risk: it cannot be mitigated", rule_ref="SOD-MITIGATION")
    if rule.scope not in refs:
        raise Problem(422, "VALIDATION_FAILED", f"refs must include {rule.scope}")
    if rule.code not in {r.code for r in conflicts(session, action, refs, principal.user_id)}:
        raise Problem(422, "NO_CONFLICT", f"You have no {rule.code} conflict for {action} on this object; nothing to mitigate", rule_ref=rule.code)
    if len((justification or "").strip()) < terms["minJustificationLength"]:
        raise Problem(422, "JUSTIFICATION_REQUIRED", f"Explain the business reason in at least {terms['minJustificationLength']} characters")
    hours = int(validity_hours or terms["maxValidityHours"])
    if hours < 1 or hours > terms["maxValidityHours"]:
        raise Problem(422, "VALIDITY_TOO_LONG", f"{rule.risk}-risk exceptions are valid for at most {terms['maxValidityHours']} hours")
    if _valid_grant(session, rule, principal.user_id, action, refs, lock=False) is not None:
        raise Problem(409, "MITIGATION_ACTIVE", "You already hold a valid exception for this; use it")
    scope_value = _scope_value(rule, refs)
    if session.execute(select(SodMitigation.id).where(
            SodMitigation.rule_code == rule.code, SodMitigation.requester_id == principal.user_id, SodMitigation.action == action,
            SodMitigation.scope_value == scope_value, SodMitigation.status == "PENDING")).first():
        raise Problem(409, "MITIGATION_PENDING", "An exception request for this is already waiting for its approver")
    m = SodMitigation(
        tenant_id=current_tenant(session), rule_code=rule.code, action=action, requester_id=principal.user_id,
        refs={k: str(v) for k, v in refs.items() if v is not None}, scope_value=scope_value, justification=justification.strip(),
        status="PENDING", requested_validity_hours=hours, compensating_control=terms["compensatingControl"],
        approver_roles=terms["approverRoles"], max_uses=terms["maxUses"], use_count=0, created_by=principal.user_id)
    session.add(m)
    session.flush()
    audit.record(session, "SOD_MITIGATION", m.id, "REQUESTED", object_ref=_ref(m),
                 after={"rule": rule.code, "action": action, "refs": m.refs, "hours": hours, "approvers": terms["approverRoles"],
                        "compensatingControl": m.compensating_control}, reason=m.justification, rule_set_version=terms["ruleRef"])
    workflow.start_approval(session, None, MITIGATION_KIND, object_type="SOD_MITIGATION", object_id=m.id, object_ref=_ref(m),
                            chain=terms["approverRoles"], step_id=None, initiator_id=principal.user_id,
                            sla_business_days=terms["slaBusinessDays"], rule_set_version=terms["ruleRef"],
                            evidence={"ruleCode": rule.code, "action": action, "refs": m.refs, "justification": m.justification,
                                      "compensatingControl": m.compensating_control, "validityHours": hours})
    return m


@workflow.on_task(MITIGATION_KIND)
def _mitigation_decided(session: Session, task: Task, outcome: str) -> None:
    m = session.get(SodMitigation, task.object_id)
    if m is None or m.status != "PENDING":
        return
    now = clock.now()
    m.decided_by, m.decided_at, m.decision_comment = task.completed_by, now, task.comment
    if outcome == "APPROVED":
        m.status, m.valid_from = "APPROVED", now
        m.valid_until = now + timedelta(hours=m.requested_validity_hours)
    else:
        m.status = "REJECTED"
    audit.record(session, "SOD_MITIGATION", m.id, "APPROVED" if outcome == "APPROVED" else "REJECTED", object_ref=_ref(m),
                 after={"status": m.status, "validFrom": m.valid_from.isoformat() if m.valid_from else None,
                        "validUntil": m.valid_until.isoformat() if m.valid_until else None, "maxUses": m.max_uses,
                        "compensatingControl": m.compensating_control}, reason=task.comment)
    outbox.emit(session, "sod.mitigation.decided", "SOD_MITIGATION", m.id, _ref(m),
                {"mitigationId": str(m.id), "rule": m.rule_code, "action": m.action, "status": m.status,
                 "requester": str(m.requester_id), "validUntil": m.valid_until.isoformat() if m.valid_until else None})


def revoke(session: Session, mitigation_id: uuid.UUID, reason: str) -> SodMitigation:
    m = session.get(SodMitigation, mitigation_id)
    if m is None:
        raise not_found("SoD mitigation", mitigation_id)
    if m.status not in ("APPROVED", "PENDING"):
        raise Problem(409, "ILLEGAL_TRANSITION", f"Mitigation is {m.status}; only a pending or approved exception can be revoked")
    before = m.status
    m.status = "REVOKED"
    audit.record(session, "SOD_MITIGATION", m.id, "REVOKED", object_ref=_ref(m), before={"status": before}, after={"status": "REVOKED"},
                 reason=reason)
    for task in session.execute(select(Task).where(Task.object_id == m.id, Task.status == "OPEN")).scalars():
        task.status = "CANCELLED"
    return m


def effective_status(m: SodMitigation) -> str:
    if m.status == "APPROVED":
        if m.use_count >= m.max_uses:
            return "EXHAUSTED"
        if m.valid_until is not None and m.valid_until <= clock.now():
            return "EXPIRED"
    return m.status


def mitigation_view(m: SodMitigation) -> dict:
    return {"id": str(m.id), "ref": _ref(m), "ruleCode": m.rule_code, "action": m.action, "refs": m.refs,
            "requesterId": str(m.requester_id), "justification": m.justification, "status": effective_status(m),
            "recordedStatus": m.status, "requestedValidityHours": m.requested_validity_hours,
            "compensatingControl": m.compensating_control, "approverRoles": m.approver_roles, "maxUses": m.max_uses,
            "useCount": m.use_count, "decidedBy": str(m.decided_by) if m.decided_by else None,
            "decidedAt": m.decided_at.isoformat() if m.decided_at else None, "decisionComment": m.decision_comment,
            "validFrom": m.valid_from.isoformat() if m.valid_from else None,
            "validUntil": m.valid_until.isoformat() if m.valid_until else None,
            "lastUsedAt": m.last_used_at.isoformat() if m.last_used_at else None, "createdAt": m.created_at.isoformat()}


def report(session: Session, limit: int = 200) -> dict:
    """Admin report: every exception with its effective status, counts, and the grants that expire within a day."""
    items = session.execute(select(SodMitigation).order_by(SodMitigation.created_at.desc()).limit(limit)).scalars().all()
    views = [mitigation_view(m) for m in items]
    counts: dict[str, int] = {}
    for v in views:
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    horizon = clock.now() + timedelta(hours=24)
    expiring = [v["ref"] for m, v in zip(items, views) if v["status"] == "APPROVED" and m.valid_until and m.valid_until <= horizon]
    return {"summary": {"byStatus": counts, "activeGrants": counts.get("APPROVED", 0), "expiringWithin24h": expiring,
                        "uses": sum(m.use_count for m in items)}, "items": views}
