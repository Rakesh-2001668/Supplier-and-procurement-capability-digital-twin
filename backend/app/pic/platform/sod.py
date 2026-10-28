"""Segregation of duties evaluated at command time for people and agents (§4.1, §14).

Rules are tenant data (``sod_rule``). ``guard`` checks the actor's earlier
actions on the same scope object; ``record`` logs the action once it succeeds.
A blocked attempt is written to ``sod_violation`` in its own transaction so the
evidence survives the rollback of the rejected command.
"""
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant, tenant_tx
from app.pic.models import ActionLog, SodRule, SodViolation
from app.pic.platform.errors import Problem


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


def _did(session: Session, actor_id: uuid.UUID, action: str, scope: str, scope_value: str) -> bool:
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
    rules = session.execute(select(SodRule).where(SodRule.active.is_(True))).scalars()
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
        outcome = "BLOCKED" if rule.mode == "BLOCK" else "MITIGATION_REQUIRED"
        _log_violation(current_tenant(session), rule, actor_id, action, refs, outcome)
        raise Problem(409, "SOD_CONFLICT", f"{rule.code}: {rule.description}", rule_ref=rule.code, risk=rule.risk)


def guard_and_record(session: Session, action: str, refs: dict) -> None:
    guard(session, action, refs)
    record(session, action, refs)
