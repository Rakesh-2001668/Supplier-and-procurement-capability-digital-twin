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
    row = session.execute(select(AppUser.active, AppUser.roles, AppUser.session_version).where(AppUser.id == principal.user_id)).one_or_none()
    if row is None or not row.active:
        raise Problem(401, "ACCOUNT_DISABLED", "This account is deactivated; contact your administrator")
    if (row.session_version or 1) != principal.session_version:
        raise Problem(401, "SESSION_REVOKED", "Your sessions were revoked by an administrator or after a password reset; sign in again")
    if sorted(row.roles or []) != sorted(principal.roles or []):
        raise Problem(401, "SESSION_OUTDATED", "Your roles changed since you signed in; sign in again")


def idempotency_key(idempotency_key_header: Optional[str] = Header(default=None, alias="Idempotency-Key")) -> Optional[str]:
    """The Idempotency-Key header. (The parameter is not called ``key`` so routes with a ``{key}`` path parameter can use it.)"""
    return idempotency_key_header


def body_of(model: Any) -> dict:
    return model.model_dump(mode="json") if hasattr(model, "model_dump") else dict(model or {})


def idempotent(session, scope: str, key: Optional[str], body: Any) -> Idempotent:
    return Idempotent(session, scope, key, body_of(body))
