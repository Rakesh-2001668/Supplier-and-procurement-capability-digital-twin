"""ADM-04 user lifecycle: invite an internal user, single-use activation and password-reset links, session revocation, bulk CSV import.

Tokens follow the supplier-invitation pattern (services/invitations.py): ``<tenantCode>.<256-bit random>``; the tenant code lets the
public endpoints open a tenant-scoped transaction, only the SHA-256 is stored, the clear token is returned (and e-mailed) once and is
never logged or audited. A token works once and expires (activation PIC_ACTIVATION_HOURS, default 72; reset PIC_RESET_HOURS, default
2). Issuing a new token for the same user and purpose revokes the earlier ones. Using a link sets the password, ends every open
session of the user (session version) and is audited.
"""
import csv
import hashlib
import hmac
import io
import os
import secrets
import uuid
from datetime import timedelta
from typing import Optional
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import AppUser, CompanyCode, CostObject, Plant, Tenant, UserToken
from app.pic.platform import audit, clock, mailer
from app.pic.platform.auth import Principal, hash_password
from app.pic.platform.errors import Problem, not_found
from app.pic.services import invitations, master_changes, role_admin
from app.pic.services.common import principal

MAX_IMPORT_ROWS = 500
SENSITIVE_ROLES = {"TENANT_ADMIN", "FINANCE_CONTROLLER", "CFO", "CPO"}


def _hours(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


def _admin(session: Session) -> None:
    if "TENANT_ADMIN" not in principal(session).roles:
        raise Problem(403, "FORBIDDEN", "Requires the tenant administrator", rule_ref="RBAC")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def view(u: AppUser) -> dict:
    status = "INACTIVE" if not u.active else ("INVITED" if u.activation_pending else "ACTIVE")
    return {"id": str(u.id), "email": u.email, "name": u.full_name, "roles": u.roles, "active": u.active, "status": status,
            "mfaEnrolled": u.mfa_enrolled, "supplierUser": u.supplier_id is not None, "attributes": u.attributes, "version": u.row_version}


# ---------------------------------------------------------------- attribute and input validation
ATTRIBUTE_KEYS = {"plants", "company_codes", "value_limit_minor", "cost_objects", "categories", "steward_domains"}


def clean_attributes(session: Session, raw: Optional[dict]) -> tuple[dict, list[str]]:
    """ABAC attributes (SEC-AZ): plants and company codes must exist (or be ``*``), cost objects are ``TYPE:CODE`` of existing
    cost objects, categories and steward domains are free codes, the value limit is a non-negative amount in paise."""
    errors: list[str] = []
    raw = raw or {}
    out: dict = {}
    unknown = set(raw) - ATTRIBUTE_KEYS
    if unknown:
        errors.append(f"unknown attribute(s): {', '.join(sorted(unknown))}")
    for key in ("plants", "company_codes", "cost_objects", "categories", "steward_domains"):
        if key not in raw or raw[key] is None:
            continue
        values = raw[key]
        if not isinstance(values, list) or not all(isinstance(v, str) and v.strip() for v in values):
            errors.append(f"{key} must be a list of codes")
            continue
        values = sorted({v.strip() if v.strip() == "*" or key == "cost_objects" else v.strip().upper() for v in values})
        known: Optional[set] = None
        if key == "plants":
            known = set(session.execute(select(Plant.code)).scalars())
        elif key == "company_codes":
            known = set(session.execute(select(CompanyCode.code)).scalars())
        elif key == "cost_objects":
            known = {f"{t}:{c}" for t, c in session.execute(select(CostObject.type, CostObject.code))}
        if known is not None:
            bad = [v for v in values if v != "*" and v not in known]
            if bad:
                errors.append(f"{key}: unknown code(s) {', '.join(bad)}")
        out[key] = values
    if raw.get("value_limit_minor") is not None:
        limit = raw["value_limit_minor"]
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            errors.append("value limit must be a non-negative whole number of paise")
        else:
            out["value_limit_minor"] = limit
    return out, errors


def validate_new(session: Session, email: str, name: str, roles: list[str], attributes: Optional[dict], taken: set) -> tuple[dict, list[str]]:
    """Everything an invitation needs to be valid; returns (clean values, errors). ``taken`` holds e-mails seen earlier in an import."""
    errors: list[str] = []
    email = (email or "").strip().lower()
    name = (name or "").strip()
    roles = sorted({r.strip() for r in roles or [] if r and r.strip()})
    if not master_changes.EMAIL_RE.match(email):
        errors.append("e-mail is not a valid address")
    elif email in taken or session.execute(select(AppUser.id).where(AppUser.email == email)).first():
        errors.append(f"{email} already has a login in this tenant")
    if not 2 <= len(name) <= 200:
        errors.append("name must be 2-200 characters")
    if not roles:
        errors.append("give at least one role")
    elif "SUPPLIER_USER" in roles:
        errors.append("supplier users register through a supplier invitation, not here")
    else:
        try:
            role_admin.check_assignment(session, roles)
        except Problem as exc:
            errors.append(exc.detail if hasattr(exc, "detail") else str(exc))
    attrs, attr_errors = clean_attributes(session, attributes)
    return {"email": email, "name": name, "roles": roles, "attributes": attrs}, errors + attr_errors


# ---------------------------------------------------------------- tokens
def _new_token(session: Session, user: AppUser, purpose: str, hours: int) -> tuple[str, UserToken]:
    now = clock.now()
    for old in session.execute(select(UserToken).where(UserToken.user_id == user.id, UserToken.purpose == purpose,
                                                       UserToken.used_at.is_(None), UserToken.revoked_at.is_(None))).scalars():
        old.revoked_at = now
    tenant_code = principal(session).tenant_code or session.execute(select(Tenant.code).where(Tenant.id == current_tenant(session))).scalar()
    token = f"{tenant_code}.{secrets.token_urlsafe(32)}"
    row = UserToken(tenant_id=current_tenant(session), user_id=user.id, purpose=purpose, token_hash=token_hash(token),
                    expires_at=now + timedelta(hours=hours), created_by=principal(session).user_id)
    session.add(row)
    session.flush()
    return token, row


def _link(token: str) -> str:
    return f"{invitations.web_url()}/pic/activate?token={quote(token, safe='')}"


def _mail(session: Session, user: AppUser, purpose: str, token: str, row: UserToken) -> str:
    tenant_name = session.execute(select(Tenant.name).where(Tenant.id == current_tenant(session))).scalar()
    link = _link(token)
    if purpose == "ACTIVATION":
        subject, lead = f"Your {tenant_name} procurement account", f"{principal(session).name} has created an account for you at {tenant_name}."
        action = "Set your password"
    else:
        subject, lead = f"Reset your {tenant_name} password", f"An administrator of {tenant_name} started a password reset for your account."
        action = "Choose a new password"
    return mailer.send(user.email, subject, f"Hello {user.full_name},\n\n{lead}\n\n{action} here (the link works once and expires on "
                       f"{row.expires_at.date().isoformat()}):\n{link}\n\nIf you did not expect this message, ignore it.\n")


def invite(session: Session, email: str, name: str, roles: list[str], attributes: Optional[dict]) -> dict:
    _admin(session)
    # A segregation-of-duties role pair is the same 409 SOD_CONFLICT as on role assignment (PUT /v1/admin/users/{id}/roles), not a
    # validation error; the bulk import (validate_new) keeps listing it among the row's errors.
    wanted = sorted({r.strip() for r in roles or [] if r and r.strip()})
    if wanted and "SUPPLIER_USER" not in wanted:
        try:
            role_admin.check_assignment(session, wanted)
        except Problem as exc:
            if exc.code == "SOD_CONFLICT":
                raise
    values, errors = validate_new(session, email, name, roles, attributes, set())
    if errors:
        raise Problem(422, "VALIDATION_FAILED", "; ".join(errors), rule_ref="ADM-04", errors=errors)
    return _create(session, values)


def _create(session: Session, values: dict) -> dict:
    user = AppUser(tenant_id=current_tenant(session), email=values["email"], full_name=values["name"], roles=values["roles"],
                   attributes=values["attributes"], password_hash=hash_password(secrets.token_urlsafe(24)), mfa_enrolled=False, active=True,
                   activation_pending=True, created_by=principal(session).user_id)
    session.add(user)
    session.flush()
    token, row = _new_token(session, user, "ACTIVATION", _hours("PIC_ACTIVATION_HOURS", 72))
    status = _mail(session, user, "ACTIVATION", token, row)
    audit.record(session, "APP_USER", user.id, "USER_INVITED", object_ref=user.email,
                 after={"roles": user.roles, "attributes": user.attributes, "expiresAt": row.expires_at, "emailStatus": status})
    return {**view(user), "token": token, "activationUrl": _link(token), "expiresAt": row.expires_at.isoformat(), "emailStatus": status}


def resend_invitation(session: Session, user: AppUser) -> dict:
    _admin(session)
    if not user.activation_pending:
        raise Problem(409, "ILLEGAL_TRANSITION", "The user has already activated the account; use a password reset instead")
    token, row = _new_token(session, user, "ACTIVATION", _hours("PIC_ACTIVATION_HOURS", 72))
    status = _mail(session, user, "ACTIVATION", token, row)
    audit.record(session, "APP_USER", user.id, "INVITATION_RESENT", object_ref=user.email, after={"expiresAt": row.expires_at, "emailStatus": status})
    return {**view(user), "token": token, "activationUrl": _link(token), "expiresAt": row.expires_at.isoformat(), "emailStatus": status}


def reset_password(session: Session, user: AppUser, reason: str) -> dict:
    _admin(session)
    if user.supplier_id is not None:
        raise Problem(422, "SUPPLIER_USER", "Supplier users reset their password through their own sign-in page")
    if not user.active:
        raise Problem(409, "USER_INACTIVE", "Activate the user before resetting the password")
    if user.activation_pending:
        raise Problem(409, "ACTIVATION_PENDING", "The user has not activated the account yet; resend the invitation instead")
    token, row = _new_token(session, user, "PASSWORD_RESET", _hours("PIC_RESET_HOURS", 2))
    status = _mail(session, user, "PASSWORD_RESET", token, row)
    audit.record(session, "APP_USER", user.id, "PASSWORD_RESET_REQUESTED", object_ref=user.email,
                 after={"expiresAt": row.expires_at, "emailStatus": status}, reason=reason)
    return {**view(user), "token": token, "resetUrl": _link(token), "expiresAt": row.expires_at.isoformat(), "emailStatus": status}


def revoke_sessions(session: Session, user: AppUser, reason: str) -> dict:
    """Every access token issued to the user before now is refused on its next request (401 SESSION_REVOKED)."""
    _admin(session)
    user.session_version = (user.session_version or 1) + 1
    session.flush()
    audit.record(session, "APP_USER", user.id, "SESSIONS_REVOKED", object_ref=user.email, after={"sessionVersion": user.session_version},
                 reason=reason)
    return {**view(user), "sessionVersion": user.session_version}


# ---------------------------------------------------------------- public: use a link
def find(session: Session, token: str, lock: bool = False) -> UserToken:
    digest = token_hash(token)
    query = select(UserToken).where(UserToken.token_hash == digest)
    if lock:
        query = query.with_for_update()
    row = session.execute(query).scalar_one_or_none()
    if row is None or not hmac.compare_digest(row.token_hash, digest):
        raise Problem(404, "LINK_NOT_FOUND", "This link is not valid")
    return row


def check_usable(row: UserToken) -> None:
    if row.used_at is not None:
        raise Problem(410, "LINK_USED", "This link has already been used. Sign in, or ask an administrator for a new link.")
    if row.revoked_at is not None:
        raise Problem(410, "LINK_REVOKED", "This link was replaced by a newer one or withdrawn. Ask an administrator for a new link.")
    if row.expires_at <= clock.now():
        raise Problem(410, "LINK_EXPIRED", "This link has expired. Ask an administrator for a new link.")


def public_view(session: Session, row: UserToken, tenant: Tenant) -> dict:
    user = session.get(AppUser, row.user_id)
    return {"purpose": row.purpose, "email": user.email, "name": user.full_name, "tenant": tenant.name, "tenantCode": tenant.code,
            "expiresAt": row.expires_at.isoformat()}


def complete(session: Session, row: UserToken, tenant: Tenant, password: str) -> dict:
    check_usable(row)
    user = session.get(AppUser, row.user_id, with_for_update=True)
    if user is None or not user.active:
        raise Problem(409, "USER_INACTIVE", "This account is deactivated; contact your administrator")
    weak = invitations.password_errors(password, user.email, user.full_name)
    if weak:
        raise Problem(422, "WEAK_PASSWORD", "; ".join(weak), rule_ref="SEC-PASSWORD", errors=weak)
    actor = Principal(user_id=user.id, tenant_id=tenant.id, tenant_code=tenant.code, email=user.email, name=user.full_name,
                      roles=list(user.roles), scopes=set(), attributes={})
    session.info["principal"], session.info["user_id"] = actor, user.id
    activation = row.purpose == "ACTIVATION"
    user.password_hash = hash_password(password)
    user.activation_pending = False
    user.session_version = (user.session_version or 1) + 1  # ends every session opened with the old password
    row.used_at = clock.now()
    for other in session.execute(select(UserToken).where(UserToken.user_id == user.id, UserToken.used_at.is_(None),
                                                         UserToken.revoked_at.is_(None), UserToken.id != row.id)).scalars():
        other.revoked_at = clock.now()
    session.flush()
    audit.record(session, "APP_USER", user.id, "USER_ACTIVATED" if activation else "PASSWORD_RESET_COMPLETED", object_ref=user.email,
                 after={"purpose": row.purpose})
    return {"email": user.email, "tenant": tenant.code, "activated": activation, "next": "Sign in with your new password."}


# ---------------------------------------------------------------- bulk import
def _split(value: str) -> list[str]:
    return [p.strip() for p in (value or "").replace(",", ";").split(";") if p.strip()]


def import_csv(session: Session, content: str, dry_run: bool) -> dict:
    """Columns: email, name, roles (; separated), plants (;), company_codes (;), value_limit_minor. All rows are validated; with
    ``dry_run`` or any error nothing is created. A clean run creates every user and returns each activation link once."""
    _admin(session)
    try:
        reader = csv.DictReader(io.StringIO(content.lstrip("﻿")))
        rows = list(reader)
    except csv.Error as exc:
        raise Problem(422, "CSV_INVALID", f"The CSV could not be read: {exc}")
    header = {h.strip().lower() for h in (reader.fieldnames or [])}
    if not {"email", "name", "roles"} <= header:
        raise Problem(422, "CSV_COLUMNS", "The CSV needs the columns email, name and roles (optional: plants, company_codes, value_limit_minor)")
    if not rows:
        raise Problem(422, "CSV_EMPTY", "The CSV has no data rows")
    if len(rows) > MAX_IMPORT_ROWS:
        raise Problem(422, "CSV_TOO_LARGE", f"At most {MAX_IMPORT_ROWS} users per import")
    taken: set = set()
    report, valid = [], []
    for number, raw in enumerate(rows, start=2):
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        attrs: dict = {}
        if r.get("plants"):
            attrs["plants"] = _split(r["plants"])
        if r.get("company_codes"):
            attrs["company_codes"] = _split(r["company_codes"])
        errors = []
        if r.get("value_limit_minor"):
            if r["value_limit_minor"].isdigit():
                attrs["value_limit_minor"] = int(r["value_limit_minor"])
            else:
                errors.append("value_limit_minor must be a whole number of paise")
        values, more = validate_new(session, r.get("email", ""), r.get("name", ""), _split(r.get("roles", "")), attrs, taken)
        errors += more
        if values["email"]:
            taken.add(values["email"])
        report.append({"row": number, "email": values["email"], "status": "ERROR" if errors else "OK", "errors": errors})
        if not errors:
            valid.append(values)
    failed = sum(1 for x in report if x["status"] == "ERROR")
    summary = {"rows": len(rows), "valid": len(valid), "errors": failed, "dryRun": dry_run}
    if dry_run or failed:
        audit.record(session, "APP_USER", principal(session).user_id, "USER_IMPORT_DRY_RUN" if dry_run else "USER_IMPORT_REFUSED",
                     object_ref="csv", after=summary)
        return {"summary": {**summary, "created": 0}, "report": report}
    created = [_create(session, v) for v in valid]
    audit.record(session, "APP_USER", principal(session).user_id, "USER_IMPORTED", object_ref="csv", after={**summary, "created": len(created)})
    return {"summary": {**summary, "created": len(created)}, "report": report, "users": created}


def get_user(session: Session, user_id: uuid.UUID) -> AppUser:
    user = session.get(AppUser, user_id)
    if user is None:
        raise not_found("User", user_id)
    return user
