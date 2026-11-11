"""Sign-in by e-mail and password, without an organisation code (one platform for buyers and suppliers).

1. The e-mail is looked up in the sign-in directory (``pic.login_directory``, migration 0029): every active user with that e-mail in an
   ACTIVE organisation is a candidate.
2. The password is checked in each candidate's organisation (passwords stay per user, inside the organisation). The organisations where
   it matches are the ones this person has proved; the session token lists them (claim ``orgs``) so the person can switch between them.
3. One match: the sign-in continues in that organisation exactly as before (MFA second step, MFA enrolment, token). Several: the answer
   lists them with a short-lived signed choice; ``choose`` continues in the chosen one.

Answers never reveal whether an e-mail exists: an unknown e-mail and a wrong password give the same 401, and an unknown e-mail still costs
one password check so the timing does not tell them apart.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from fastapi import Request
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import AppUser, LoginDirectory, Tenant
from app.pic.platform import http, mfa
from app.pic.platform.auth import (
    MFA_CHALLENGE, MFA_ENROLMENT, hash_password, issue_challenge, read_challenge, token_response, user_challenge, verify_password,
)
from app.pic.platform.errors import Problem

CHOICE_PURPOSE = "org-choice"
CHOICE_TTL_SECONDS = 300
MAX_CANDIDATES = 25  # one person in more organisations than this is not a sign-in case; the rest are ignored
_DUMMY_HASH = hash_password("timing-equaliser-not-a-password")
INVALID = "Unknown e-mail or password"


@dataclass(frozen=True)
class Membership:
    tenant: Tenant
    user_id: uuid.UUID
    roles: tuple[str, ...]


def _invalid(request: Request) -> Problem:
    http.record_login_failure(request)
    return Problem(401, "INVALID_CREDENTIALS", INVALID)


def _candidates(email: str) -> list[tuple[Tenant, uuid.UUID]]:
    with system_tx() as s:
        rows = s.execute(
            select(Tenant, LoginDirectory.app_user_id)
            .join(LoginDirectory, LoginDirectory.org_id == Tenant.id)
            .where(LoginDirectory.email == email, LoginDirectory.active.is_(True), Tenant.status == "ACTIVE")
            .order_by(Tenant.code)
            .limit(MAX_CANDIDATES)
        ).all()
        for tenant, _ in rows:
            s.expunge(tenant)
    return [(tenant, user_id) for tenant, user_id in rows]


def _matching(email: str, password: str) -> list[Membership]:
    candidates = _candidates(email)
    if not candidates:
        verify_password(password, _DUMMY_HASH)
        return []
    found: list[Membership] = []
    for tenant, user_id in candidates:
        with tenant_tx(tenant.id) as s:
            user = s.get(AppUser, user_id)
            if user is not None and user.active and user.email == email and verify_password(password, user.password_hash):
                found.append(Membership(tenant, user.id, tuple(user.roles or ())))
    return found


def organisation_view(membership: Membership) -> dict:
    t = membership.tenant
    return {"code": t.code, "name": t.name, "kind": t.kind, "roles": list(membership.roles),
            "supplierUser": "SUPPLIER_USER" in membership.roles}


def continue_in(tenant: Tenant, user_id: uuid.UUID, request: Request, organisations: list[str]) -> dict:
    """The organisation-specific part of the sign-in: the MFA second step or enrolment if needed, otherwise the session token."""
    with tenant_tx(tenant.id) as s:
        user = s.get(AppUser, user_id)
        if user is None or not user.active:
            raise _invalid(request)
        if mfa.confirmed_factor(s, user.id) is not None:
            return {"mfaRequired": True, "challenge": user_challenge(MFA_CHALLENGE, user, tenant, organisations=organisations), "expiresIn": 300,
                    "methods": ["TOTP"], "tenant": tenant.code}
        if mfa.required_for(s, user):
            raise Problem(403, "MFA_ENROLMENT_REQUIRED", "Your role requires multi-factor authentication. Register an authenticator app to continue.",
                          rule_ref="MFA", enrolmentChallenge=user_challenge(MFA_ENROLMENT, user, tenant, ttl_seconds=900, organisations=organisations))
        http.clear_login_failures(request)
        return token_response(user, tenant, organisations=organisations)


def sign_in(email: str, password: str, request: Request) -> dict:
    """Step 1 of the sign-in by e-mail: one organisation continues at once, several return the choice."""
    email = (email or "").strip().lower()
    if not email or len(email) > 200 or not password:
        raise _invalid(request)
    found = _matching(email, password)
    if not found:
        raise _invalid(request)
    codes = [m.tenant.code for m in found]
    if len(found) == 1:
        return continue_in(found[0].tenant, found[0].user_id, request, codes)
    choice = issue_challenge(CHOICE_PURPOSE, {"email": email, "orgs": [[m.tenant.code, str(m.user_id)] for m in found]}, CHOICE_TTL_SECONDS)
    return {"organisationChoice": True, "challenge": choice, "expiresIn": CHOICE_TTL_SECONDS,
            "organisations": [organisation_view(m) for m in found]}


def _tenant(code: str) -> Optional[Tenant]:
    with system_tx() as s:
        tenant = s.execute(select(Tenant).where(Tenant.code == (code or "").upper())).scalar_one_or_none()
        if tenant is not None:
            s.expunge(tenant)
    return tenant


def choose(challenge: str, organisation: str, request: Request) -> dict:
    """Step 2 when the e-mail belongs to several organisations: continue in the chosen one."""
    claims = read_challenge(challenge, CHOICE_PURPOSE, code="ORGANISATION_CHOICE_INVALID")
    pairs = {code: user_id for code, user_id in claims.get("orgs") or []}
    code = (organisation or "").upper()
    tenant = _tenant(code) if code in pairs else None
    if tenant is None or tenant.status != "ACTIVE":
        raise Problem(403, "ORGANISATION_NOT_AVAILABLE", "Choose one of the organisations offered at sign-in")
    return continue_in(tenant, uuid.UUID(pairs[code]), request, list(pairs))


def switch(principal, organisation: str, request: Request) -> dict:
    """Header organisation switcher: only to an organisation proved at sign-in (token claim ``orgs``), for the same e-mail.
    The target organisation's MFA still applies (a second step may be returned)."""
    code = (organisation or "").upper()
    if code not in principal.organisations:
        raise Problem(403, "ORGANISATION_NOT_AVAILABLE", "Sign in again to open this organisation")
    tenant = _tenant(code)
    if tenant is None or tenant.status != "ACTIVE":
        raise Problem(403, "ORGANISATION_NOT_AVAILABLE", "This organisation is not available")
    with system_tx() as s:
        user_id = s.execute(select(LoginDirectory.app_user_id).where(
            LoginDirectory.org_id == tenant.id, LoginDirectory.email == principal.email.lower(), LoginDirectory.active.is_(True))).scalar_one_or_none()
    if user_id is None:
        raise Problem(403, "ORGANISATION_NOT_AVAILABLE", "Your account in this organisation is not active")
    return continue_in(tenant, user_id, request, list(principal.organisations))


def organisations_of(principal) -> list[dict]:
    """The organisations the session may switch to, for the header (name and type; the current one first)."""
    codes = list(dict.fromkeys([principal.tenant_code, *principal.organisations]))
    with system_tx() as s:
        tenants = {t.code: t for t in s.execute(select(Tenant).where(Tenant.code.in_(codes))).scalars()}
        return [{"code": c, "name": tenants[c].name, "kind": tenants[c].kind, "current": c == principal.tenant_code}
                for c in codes if c in tenants and tenants[c].status == "ACTIVE"]
