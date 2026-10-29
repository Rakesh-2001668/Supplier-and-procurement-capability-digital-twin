"""M06 supplier invitations and self-registration (F8-01 "Invitation or self-registration", SLM-05).

The supplier manager invites a company by e-mail. The invitation token is ``<tenantCode>.<256-bit random>``: the tenant
code lets the public (unauthenticated) endpoints open a tenant-scoped transaction, which row-level security requires;
only the SHA-256 of the whole token is stored, so a database reader cannot use an invitation. The clear token is
returned once to the inviter and e-mailed to the invitee.

Self-registration runs the ordinary supplier registration service (screening, the onboarding process instance and the
audit trail), starts qualification for the invited categories and creates the supplier's portal login
(SUPPLIER_USER, bcrypt password, MFA not yet enrolled). An invitation can be used once.
"""
import hashlib
import hmac
import os
import re
import secrets
import uuid
from datetime import timedelta
from typing import Optional
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.config import get_settings
from app.pic.db import current_tenant
from app.pic.models import AppUser, Supplier, SupplierInvitation, Tenant
from app.pic.platform import audit, clock, mailer, outbox, rules
from app.pic.platform.auth import Principal, hash_password, scopes_for
from app.pic.platform.errors import Problem
from app.pic.platform.serialize import row
from app.pic.services import master_changes
from app.pic.services.common import principal

RULE = "SUPPLIER-INVITATION"
COMMON_PASSWORDS = {"password", "passw0rd", "welcome", "letmein", "qwerty", "admin", "changeme", "supplier", "india", "123456"}


def web_url() -> str:
    """Base URL of the web workspace for links in e-mails and punch-out return addresses."""
    explicit = os.environ.get("PIC_WEB_URL")
    if explicit:
        return explicit.rstrip("/")
    origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
    return (origins[0] if origins else "http://localhost:3000").rstrip("/")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def tenant_code_of(token: str) -> Optional[str]:
    code, sep, rest = (token or "").partition(".")
    return code if sep and code and rest and len(token) <= 120 else None


def effective_status(invitation: SupplierInvitation) -> str:
    if invitation.status == "SENT" and invitation.expires_at <= clock.now():
        return "EXPIRED"
    return invitation.status


def view(invitation: SupplierInvitation, supplier_code: Optional[str] = None) -> dict:
    return row(invitation, extra={"status": effective_status(invitation), "supplier": supplier_code})


# ---------------------------------------------------------------- invite (supplier manager)
def create(session: Session, *, email: str, legal_name: str, categories: list[str]) -> dict:
    p = principal(session)
    email = (email or "").strip().lower()
    legal_name = (legal_name or "").strip()
    categories = sorted({c.strip().upper() for c in categories or [] if c and c.strip()})
    errors = []
    if not master_changes.EMAIL_RE.match(email):
        errors.append("e-mail is not a valid address")
    if len(legal_name) < 3:
        errors.append("legal name is required")
    if not categories:
        errors.append("invite the supplier for at least one category")
    if errors:
        raise Problem(422, "VALIDATION_FAILED", "; ".join(errors), rule_ref="F8-01", errors=errors)
    if session.execute(select(AppUser.id).where(AppUser.email == email)).first():
        raise Problem(409, "USER_EXISTS", f"{email} already has a login in this tenant", rule_ref="F8-01")
    for other in session.execute(select(SupplierInvitation).where(SupplierInvitation.email == email,
                                                                  SupplierInvitation.status == "SENT")).scalars():
        if effective_status(other) == "SENT":
            raise Problem(409, "INVITATION_PENDING", f"An invitation to {email} is still open until {other.expires_at.isoformat()}; "
                          "revoke it to send a new one", rule_ref="F8-01")
    rule = rules.resolve(session, RULE)
    tenant_code = p.tenant_code or session.execute(select(Tenant.code).where(Tenant.id == current_tenant(session))).scalar()
    token = f"{tenant_code}.{secrets.token_urlsafe(32)}"
    invitation = SupplierInvitation(
        tenant_id=current_tenant(session), token_hash=token_hash(token), email=email, legal_name=legal_name, categories=categories,
        invited_by=p.user_id, expires_at=clock.now() + timedelta(days=int(rule.body.get("validDays", 14))), status="SENT",
        created_by=p.user_id,
    )
    session.add(invitation)
    session.flush()
    link = f"{web_url()}/pic/register?token={quote(token, safe='')}"
    tenant_name = session.execute(select(Tenant.name).where(Tenant.id == current_tenant(session))).scalar() or tenant_code
    email_status = mailer.send(
        email, f"Invitation to register as a supplier of {tenant_name}",
        f"Dear {legal_name},\n\n{p.name} of {tenant_name} invites you to register as a supplier for: {', '.join(categories)}.\n\n"
        f"Register here (the link works once and expires on {invitation.expires_at.date().isoformat()}):\n{link}\n\n"
        "You will be asked for your GSTIN, PAN, registered address and a password for the supplier portal.\n")
    audit.record(session, "SUPPLIER_INVITATION", invitation.id, "INVITATION_SENT", object_ref=legal_name[:60],
                 after={"email": master_changes.mask_email(email), "categories": categories, "expiresAt": invitation.expires_at,
                        "emailStatus": email_status}, rule_set_version=rule.ref)
    outbox.emit(session, "supplier.invitation.sent", "SUPPLIER_INVITATION", invitation.id, legal_name[:60],
                {"legalName": legal_name, "categories": categories, "emailStatus": email_status})
    return {**view(invitation), "token": token, "registrationUrl": link, "emailStatus": email_status}


def list_all(session: Session) -> list[dict]:
    codes = {s.id: s.code for s in session.execute(select(Supplier)).scalars()}
    return [view(i, codes.get(i.supplier_id)) for i in session.execute(
        select(SupplierInvitation).order_by(SupplierInvitation.created_at.desc())).scalars()]


def revoke(session: Session, invitation_id: uuid.UUID, reason: Optional[str]) -> dict:
    invitation = session.get(SupplierInvitation, invitation_id, with_for_update=True)
    if invitation is None:
        raise Problem(404, "NOT_FOUND", f"Invitation {invitation_id} not found")
    if invitation.status != "SENT":
        raise Problem(409, "ILLEGAL_TRANSITION", f"The invitation is {invitation.status}; only open invitations can be revoked")
    invitation.status = "REVOKED"
    audit.record(session, "SUPPLIER_INVITATION", invitation.id, "INVITATION_REVOKED", object_ref=invitation.legal_name[:60],
                 before={"status": "SENT"}, after={"status": "REVOKED"}, reason=reason)
    return view(invitation)


# ---------------------------------------------------------------- public: validate and register
def find(session: Session, token: str, lock: bool = False) -> SupplierInvitation:
    """Look the invitation up by token hash (no comparison of secrets in application code), then confirm in constant time."""
    digest = token_hash(token)
    query = select(SupplierInvitation).where(SupplierInvitation.token_hash == digest)
    if lock:
        query = query.with_for_update()
    invitation = session.execute(query).scalar_one_or_none()
    if invitation is None or not hmac.compare_digest(invitation.token_hash, digest):
        raise Problem(404, "INVITATION_NOT_FOUND", "This registration link is not valid")
    return invitation


def check_usable(invitation: SupplierInvitation) -> None:
    status = effective_status(invitation)
    if status == "REGISTERED":
        raise Problem(410, "INVITATION_USED", "This registration link has already been used. Sign in to the supplier portal instead.")
    if status == "REVOKED":
        raise Problem(410, "INVITATION_REVOKED", "This invitation was withdrawn. Contact the buyer who invited you.")
    if status == "EXPIRED":
        raise Problem(410, "INVITATION_EXPIRED", "This registration link has expired. Ask the buyer for a new invitation.")


def public_view(invitation: SupplierInvitation, tenant: Tenant) -> dict:
    return {"legalName": invitation.legal_name, "email": invitation.email, "categories": list(invitation.categories or []),
            "tenant": tenant.name, "tenantCode": tenant.code, "expiresAt": invitation.expires_at.isoformat()}


def password_errors(password: str, email: str, legal_name: str) -> list[str]:
    errors = []
    if len(password or "") < 12:
        errors.append("password must be at least 12 characters")
    classes = sum(bool(re.search(p, password or "")) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))
    if classes < 3:
        errors.append("password must mix at least three of: lower-case, upper-case, digits, symbols")
    lowered = (password or "").lower()
    local = email.split("@", 1)[0].lower()
    if len(local) >= 4 and local in lowered:
        errors.append("password must not contain your e-mail name")
    words = [w for w in re.split(r"[^a-z0-9]+", legal_name.lower()) if len(w) >= 4 and w not in ("private", "limited", "india")]
    if any(w in lowered for w in words):
        errors.append("password must not contain your company name")
    if any(c in lowered for c in COMMON_PASSWORDS):
        errors.append("password is too common")
    return errors


def register(session: Session, invitation: SupplierInvitation, tenant: Tenant, *, legal_name: str, gstin: str, pan: str,
             state_code: str, address: dict, contact_name: str, email: str, password: str, phone: Optional[str] = None) -> dict:
    from app.pic.services import supplier as supplier_svc

    check_usable(invitation)
    email = (email or "").strip().lower()
    legal_name = (legal_name or "").strip()
    gstin = (gstin or "").strip().upper().replace(" ", "")
    pan = (pan or "").strip().upper().replace(" ", "")
    state_code = (state_code or "").strip()
    clean_address = master_changes.normalise_address({**(address or {}), "state_code": (address or {}).get("state_code") or state_code})
    errors = []
    if len(legal_name) < 3:
        errors.append("legal name is required")
    if len((contact_name or "").strip()) < 2:
        errors.append("contact name is required")
    if email != invitation.email:
        errors.append("the login e-mail must be the invited address; ask the buyer to re-invite another address")
    errors += master_changes.pan_errors(pan)
    errors += master_changes.gstin_errors(gstin, pan=pan, state_code=state_code)
    errors += master_changes.address_errors(clean_address)
    if clean_address.get("state_code") and clean_address["state_code"] != state_code:
        errors.append("address state code must match the GSTIN state code")
    if phone and not master_changes.PHONE_RE.match(phone.strip()):
        errors.append("phone must be 9-18 digits, optionally with a leading + country code")
    if errors:
        raise Problem(422, "VALIDATION_FAILED", "; ".join(errors), rule_ref="F8-01", errors=errors)
    weak = password_errors(password, email, legal_name)
    if weak:
        raise Problem(422, "WEAK_PASSWORD", "; ".join(weak), rule_ref="SEC-PASSWORD", errors=weak)
    if session.execute(select(AppUser.id).where(AppUser.email == email)).first():
        raise Problem(409, "USER_EXISTS", "A login with this e-mail already exists. Sign in instead.", rule_ref="F8-01")

    # The new portal user is the actor of the registration (audit, process, created_by).
    user_id = uuid.uuid7()
    actor = Principal(user_id=user_id, tenant_id=tenant.id, tenant_code=tenant.code, email=email, name=contact_name.strip(),
                      roles=["SUPPLIER_USER"], scopes=scopes_for(["SUPPLIER_USER"]), attributes={})
    session.info["principal"], session.info["user_id"] = actor, user_id
    if phone:
        clean_address["phone"] = phone.strip()
    supplier = supplier_svc.register(session, code=None, legal_name=legal_name, gstin=gstin, pan=pan, state_code=state_code,
                                     contact_email=email, categories=list(invitation.categories or []), address=clean_address,
                                     channel="SELF_REGISTRATION")
    actor.supplier_id = supplier.id
    session.add(AppUser(id=user_id, tenant_id=tenant.id, email=email, full_name=contact_name.strip(), password_hash=hash_password(password),
                        roles=["SUPPLIER_USER"], attributes={}, supplier_id=supplier.id, mfa_enrolled=False, active=True, created_by=user_id))
    session.flush()
    screening = supplier_svc.screen(session, supplier)
    # Qualification may start on a REVIEW screening (possible duplicate, provider outage), but no category is decided
    # QUALIFIED / CONDITIONAL and no ERP vendor is created until a supplier manager disposes it (supplier.screening_gate).
    qualifications = [] if supplier.status == "BLOCKED" else [
        supplier_svc.start_qualification(session, supplier, category).category for category in invitation.categories or []]
    invitation.status = "REGISTERED"
    invitation.supplier_id = supplier.id
    invitation.registered_at = clock.now()
    audit.record(session, "SUPPLIER_INVITATION", invitation.id, "INVITATION_REGISTERED", object_ref=invitation.legal_name[:60],
                 before={"status": "SENT"}, after={"status": "REGISTERED", "supplier": supplier.code, "screening": screening["outcome"]})
    outbox.emit(session, "supplier.registered", "SUPPLIER", supplier.id, supplier.code,
                {"supplierCode": supplier.code, "channel": "SELF_REGISTRATION", "categories": list(invitation.categories or []),
                 "screening": screening["outcome"]})
    return {"supplier": supplier.code, "legalName": supplier.legal_name, "status": supplier.status, "screening": screening["outcome"],
            "qualifications": qualifications, "screeningReviewRequired": screening["outcome"] == "REVIEW",
            "login": {"tenant": tenant.code, "email": email, "mfaEnrolled": False},
            "next": "Sign in to the supplier portal to add bank details and certificates (F8-02)."}
