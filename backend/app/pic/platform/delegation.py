"""Delegation of authority, read side (used by the workflow engine, the task inbox and the notifications).

An ACTIVE delegation lets its delegate work the delegator's approval tasks between ``valid_from`` and ``valid_to`` (inclusive, IST)
-- optionally only for some of the delegator's roles and only up to a value. The engine (workflow.can_work) still applies the
task's own checks to the delegator (role, scope) AND to the delegate (four-eyes exclusions), and delegated authority is never
delegated again. Creation, revocation and notification are in services/delegation.py.
"""
import uuid
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import AppUser, Delegation
from app.pic.platform import clock
from app.pic.platform.auth import Principal, scopes_for

CACHE_KEY = "pic_delegations"
VALUE_KEYS = ("totalMinor", "valueMinor", "amountMinor")  # task.evidence keys that carry the monetary value of the document


def invalidate(session: Session) -> None:
    session.info.pop(CACHE_KEY, None)


def _cache(session: Session) -> dict:
    return session.info.setdefault(CACHE_KEY, {"by_delegate": {}, "principals": {}})


def principal_of(user: AppUser) -> Principal:
    roles = list(user.roles or [])
    return Principal(user_id=user.id, tenant_id=user.tenant_id, tenant_code="", email=user.email, name=user.full_name, roles=roles,
                     scopes=scopes_for(roles), attributes=user.attributes or {}, supplier_id=user.supplier_id)


def is_current(delegation: Delegation, on: Optional[date] = None) -> bool:
    on = on or clock.today()
    return delegation.status == "ACTIVE" and delegation.valid_from <= on <= delegation.valid_to


def active_for(session: Session, delegate_id: uuid.UUID) -> list[tuple[Delegation, Principal]]:
    """(delegation, delegator principal) pairs in force today for this delegate; delegations of inactive delegators are skipped.
    Cached per session (cleared by ``invalidate`` whenever a delegation changes)."""
    cache = _cache(session)
    if delegate_id not in cache["by_delegate"]:
        today = clock.today()
        rows = session.execute(select(Delegation).where(Delegation.delegate_id == delegate_id, Delegation.status == "ACTIVE",
                                                        Delegation.valid_from <= today, Delegation.valid_to >= today)).scalars().all()
        pairs = []
        for d in rows:
            if d.delegator_id not in cache["principals"]:
                user = session.get(AppUser, d.delegator_id)
                cache["principals"][d.delegator_id] = principal_of(user) if user is not None and user.active else None
            if cache["principals"][d.delegator_id] is not None:
                pairs.append((d, cache["principals"][d.delegator_id]))
        cache["by_delegate"][delegate_id] = pairs
    return cache["by_delegate"][delegate_id]


def task_value(evidence: Optional[dict]) -> Optional[int]:
    for key in VALUE_KEYS:
        value = (evidence or {}).get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
    return None


def all_current(session: Session) -> list[Delegation]:
    today = clock.today()
    return list(session.execute(select(Delegation).where(Delegation.status == "ACTIVE", Delegation.valid_from <= today,
                                                         Delegation.valid_to >= today)).scalars())
