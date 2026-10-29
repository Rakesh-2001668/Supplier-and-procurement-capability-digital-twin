"""Shared API helpers: one tenant-scoped transaction per request and idempotent POSTs."""
from contextlib import contextmanager
from typing import Any, Optional

from fastapi import Header
from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import AppUser
from app.pic.platform.auth import Principal
from app.pic.platform.core import Idempotent
from app.pic.platform.errors import Problem


@contextmanager
def uow(principal: Principal):
    with tenant_tx(principal.tenant_id, principal.user_id, principal) as session:
        _ensure_session_current(session, principal)
        yield session


def _ensure_session_current(session, principal: Principal) -> None:
    """Revocation without waiting for the token to expire: a deactivated (or erased) user, or one whose roles changed since
    sign-in, is refused on the next request. Agent principals and the MFA-enrolment challenge carry no user roles."""
    if principal.agent_code or principal.attributes.get("mfa_enrolment"):
        return
    row = session.execute(select(AppUser.active, AppUser.roles).where(AppUser.id == principal.user_id)).one_or_none()
    if row is None or not row.active:
        raise Problem(401, "ACCOUNT_DISABLED", "This account is deactivated; contact your administrator")
    if sorted(row.roles or []) != sorted(principal.roles or []):
        raise Problem(401, "SESSION_OUTDATED", "Your roles changed since you signed in; sign in again")


def idempotency_key(key: Optional[str] = Header(default=None, alias="Idempotency-Key")) -> Optional[str]:
    return key


def body_of(model: Any) -> dict:
    return model.model_dump(mode="json") if hasattr(model, "model_dump") else dict(model or {})


def idempotent(session, scope: str, key: Optional[str], body: Any) -> Idempotent:
    return Idempotent(session, scope, key, body_of(body))
