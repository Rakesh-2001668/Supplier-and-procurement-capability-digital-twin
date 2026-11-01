"""Shared helpers of the industry-template controls (blueprint §23): optional rule lookup, lazily created number ranges and the
one-step tasks the controls raise. A control is active for a tenant only when its rule set exists (the industry template
carries it); ``rule_or_none`` is how the hooks in the core services ask."""
import uuid
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import NumberRange
from app.pic.platform import rules, workflow
from app.pic.platform.core import next_number
from app.pic.platform.errors import Problem


def rule_or_none(session: Session, key: str, on: Optional[date] = None, **scope) -> Optional[rules.Rule]:
    """The effective rule set, or None when the tenant's template does not carry it (the control is then inactive)."""
    try:
        return rules.resolve(session, key, on, **scope)
    except Problem as exc:
        if exc.code == "RULE_SET_MISSING":
            return None
        raise


def require_rule(session: Session, key: str, control: str, on: Optional[date] = None, **scope) -> rules.Rule:
    rule = rule_or_none(session, key, on, **scope)
    if rule is None:
        raise Problem(409, "CONTROL_NOT_ENABLED", f"{control} is not enabled for this tenant (rule set {key} is not configured)", rule_ref=key)
    if rule.body.get("enabled") is False:
        raise Problem(409, "CONTROL_NOT_ENABLED", f"{control} is switched off for this tenant (rule set {key}: enabled=false)", rule_ref=key)
    return rule


def number(session: Session, object_type: str, prefix: str, first: int = 1, padding: int = 4) -> str:
    """Next document number; the range is created on first use, so tenants bootstrapped before this release need no migration."""
    exists = session.execute(select(NumberRange.id).where(NumberRange.object_type == object_type)).first()
    if exists is None:
        session.add(NumberRange(tenant_id=current_tenant(session), object_type=object_type, prefix=prefix, next_value=first, padding=padding))
        session.flush()
    return next_number(session, object_type)


def open_task(session: Session, kind: str, role: str, *, object_type: str, object_id: uuid.UUID, object_ref: str, evidence: dict,
              exclude: Optional[list] = None, scope: Optional[dict] = None, sla_business_days: int = 3,
              rule_set_version: Optional[str] = None):
    """A single-step human task (no process instance): the workflow engine handles SLA timers, escalation and notification."""
    tasks = workflow.start_approval(session, None, kind, object_type=object_type, object_id=object_id, object_ref=object_ref, chain=[role],
                                    step_id=None, initiator_id=None, scopes={role: scope} if scope else None, exclude=exclude,
                                    sla_business_days=sla_business_days, rule_set_version=rule_set_version, evidence=evidence)
    return tasks[0]
