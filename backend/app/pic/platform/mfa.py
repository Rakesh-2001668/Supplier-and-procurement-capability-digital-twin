"""TOTP multi-factor authentication (RFC 6238) for approvers, finance and admins (§14).

- HOTP/TOTP with HMAC-SHA-1, 30-second steps, 6 digits; codes are accepted for the current step ±1.
- A code (time step) is accepted once: ``mfa_factor.last_used_step`` rejects replays within the window.
- The base32 shared secret is field-encrypted per tenant (platform/crypto.py); it is shown once at enrolment.
- Codes are checked against the wall clock, never the pinned business clock.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
import uuid
from datetime import timedelta
from typing import Optional
from urllib.parse import quote, urlencode

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import AppUser, AuditEvent, MfaFactor
from app.pic.platform import audit, clock, crypto, rules
from app.pic.platform.errors import Problem

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1
PURPOSE = "mfa-totp"
DEFAULT_ISSUER = "AlphaHelion PIC"


# ---------------------------------------------------------------- RFC 4226 / RFC 6238
def new_secret() -> str:
    """160-bit random secret, base32 without padding (what authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret_b32: str) -> bytes:
    cleaned = secret_b32.strip().replace(" ", "").upper()
    return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))


def hotp(key: bytes, counter: int, digits: int = DIGITS, digest=hashlib.sha1) -> str:
    mac = hmac.new(key, struct.pack(">Q", counter), digest).digest()
    offset = mac[-1] & 0x0F
    binary = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10 ** digits)).zfill(digits)


def time_step(at: Optional[float] = None) -> int:
    return int((time.time() if at is None else at) // STEP_SECONDS)


def totp(secret_b32: str, at: Optional[float] = None, digits: int = DIGITS) -> str:
    return hotp(_key(secret_b32), time_step(at), digits)


def match_step(secret_b32: str, code: str, last_used_step: Optional[int] = None, at: Optional[float] = None) -> Optional[int]:
    """Return the matched time step for a valid, unused code; None otherwise."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    key = _key(secret_b32)
    current = time_step(at)
    for step in range(current - WINDOW, current + WINDOW + 1):
        if hmac.compare_digest(hotp(key, step), code):
            if last_used_step is not None and step <= last_used_step:
                return None  # replay of an already used (or older) code
            return step
    return None


def otpauth_uri(secret_b32: str, account: str, issuer: str) -> str:
    label = quote(f"{issuer}:{account}", safe="@:")
    query = urlencode({"secret": secret_b32, "issuer": issuer, "algorithm": "SHA1", "digits": DIGITS, "period": STEP_SECONDS})
    return f"otpauth://totp/{label}?{query}"


# ---------------------------------------------------------------- policy
def policy(session: Session) -> dict:
    """MFA rule set (enforce, requiredRoles, issuer). A tenant without the rule set is not enforced."""
    try:
        body = rules.resolve(session, "MFA").body
    except Problem:
        body = {}
    return {"enforce": bool(body.get("enforce", False)), "requiredRoles": list(body.get("requiredRoles") or []),
            "issuer": body.get("issuer") or DEFAULT_ISSUER}


def required_for(session: Session, user: AppUser) -> bool:
    p = policy(session)
    return p["enforce"] and bool(set(user.roles or []) & set(p["requiredRoles"]))


# ---------------------------------------------------------------- factors
def factor(session: Session, user_id: uuid.UUID, lock: bool = False) -> Optional[MfaFactor]:
    query = select(MfaFactor).where(MfaFactor.user_id == user_id, MfaFactor.kind == "TOTP")
    if lock:
        query = query.with_for_update()
    return session.execute(query).scalar_one_or_none()


def confirmed_factor(session: Session, user_id: uuid.UUID) -> Optional[MfaFactor]:
    f = factor(session, user_id)
    return f if f is not None and f.confirmed_at is not None else None


def _secret(session: Session, f: MfaFactor) -> str:
    return crypto.decrypt(current_tenant(session), PURPOSE, f.secret_enc.encode())


def status(session: Session, user: AppUser) -> dict:
    f = factor(session, user.id)
    p = policy(session)
    return {"enrolled": bool(f and f.confirmed_at), "pending": bool(f and not f.confirmed_at),
            "confirmedAt": f.confirmed_at.isoformat() if f and f.confirmed_at else None,
            "enforced": p["enforce"], "required": required_for(session, user), "issuer": p["issuer"]}


def enrol(session: Session, user: AppUser) -> dict:
    """Start (or restart) enrolment: a new unconfirmed factor with a fresh secret."""
    f = factor(session, user.id, lock=True)
    if f is not None and f.confirmed_at is not None:
        raise Problem(409, "MFA_ALREADY_ENROLLED", "An authenticator is already confirmed; disable it before enrolling a new one")
    secret = new_secret()
    encrypted = crypto.encrypt(current_tenant(session), PURPOSE, secret).decode()
    if f is None:
        f = MfaFactor(tenant_id=current_tenant(session), user_id=user.id, kind="TOTP", secret_enc=encrypted, created_by=user.id)
        session.add(f)
    else:
        f.secret_enc = encrypted
        f.last_used_step = None
    session.flush()
    issuer = policy(session)["issuer"]
    audit.record(session, "APP_USER", user.id, "MFA_ENROLMENT_STARTED", object_ref=user.email, after={"kind": "TOTP"})
    return {"factorId": str(f.id), "kind": "TOTP", "secret": secret, "otpauthUri": otpauth_uri(secret, user.email, issuer),
            "issuer": issuer, "digits": DIGITS, "period": STEP_SECONDS, "algorithm": "SHA1"}


def verify(session: Session, f: MfaFactor, code: str) -> bool:
    """Check a code and consume its time step (replay protection)."""
    step = match_step(_secret(session, f), code, f.last_used_step)
    if step is None:
        return False
    f.last_used_step = step
    session.flush()
    return True


# ---------------------------------------------------------------- per-account brute-force lockout
LOCKOUT_MAX_FAILURES = 10  # wrong codes per account (rule MFA.maxFailures) ...
LOCKOUT_WINDOW_MINUTES = 15  # ... within this window (rule MFA.lockoutMinutes) since the last successful code


def _lockout_policy(session: Session) -> tuple[int, int]:
    try:
        body = rules.resolve(session, "MFA").body
    except Problem:
        body = {}
    return int(body.get("maxFailures") or LOCKOUT_MAX_FAILURES), int(body.get("lockoutMinutes") or LOCKOUT_WINDOW_MINUTES)


def _recent_failures(session: Session, user_id: uuid.UUID) -> list:
    """Timestamps of the account's MFA_FAILED audit events in the window and after its last MFA_VERIFIED: the counter lives in
    the (shared, append-only) audit trail, so it holds across API replicas and serverless instances."""
    _, minutes = _lockout_policy(session)
    since = clock.now() - timedelta(minutes=minutes)
    last_ok = session.execute(select(func.max(AuditEvent.ts)).where(
        AuditEvent.object_type == "APP_USER", AuditEvent.object_id == user_id, AuditEvent.action == "MFA_VERIFIED")).scalar()
    if last_ok is not None and last_ok > since:
        since = last_ok
    return list(session.execute(select(AuditEvent.ts).where(
        AuditEvent.object_type == "APP_USER", AuditEvent.object_id == user_id, AuditEvent.action == "MFA_FAILED",
        AuditEvent.ts > since).order_by(AuditEvent.ts)).scalars())


def locked_for(session: Session, user_id: uuid.UUID) -> Optional[int]:
    """Seconds until the account may try codes again, or None when it is not locked."""
    limit, minutes = _lockout_policy(session)
    failures = _recent_failures(session, user_id)
    if len(failures) < limit:
        return None
    until = failures[-limit] + timedelta(minutes=minutes)
    return max(int((until - clock.now()).total_seconds()) + 1, 1)


def ensure_not_locked(session: Session, user_id: uuid.UUID) -> None:
    wait = locked_for(session, user_id)
    if wait is not None:
        raise Problem(429, "MFA_LOCKED", f"Too many wrong authenticator codes for this account. Try again in {max(wait // 60, 1)} minute(s) "
                      "or ask your administrator.", rule_ref="MFA", retryAfterSeconds=wait)


def record_failure(session: Session, user: AppUser, context: str, ip: Optional[str] = None) -> int:
    """Audit a wrong code (MFA_FAILED) and return the account's failures in the current window."""
    audit.record(session, "APP_USER", user.id, "MFA_FAILED", object_ref=user.email, actor=f"u:{user.email}",
                 after={"context": context, "ip": ip}, reason="wrong or replayed authenticator code")
    count = len(_recent_failures(session, user.id))
    limit, minutes = _lockout_policy(session)
    if count == limit:
        audit.record(session, "APP_USER", user.id, "MFA_LOCKED_OUT", object_ref=user.email, actor=f"u:{user.email}",
                     after={"failures": count, "windowMinutes": minutes}, reason="authenticator code brute-force lockout")
    return count


def record_success(session: Session, user: AppUser) -> None:
    """A correct second factor at sign-in (MFA_VERIFIED) restarts the account's failure count."""
    audit.record(session, "APP_USER", user.id, "MFA_VERIFIED", object_ref=user.email, actor=f"u:{user.email}", after={"kind": "TOTP"})


def confirm(session: Session, user: AppUser, code: str) -> MfaFactor:
    f = factor(session, user.id, lock=True)
    if f is None:
        raise Problem(404, "MFA_NOT_ENROLLING", "Start enrolment first (POST /v1/me/mfa/totp)")
    if f.confirmed_at is not None:
        raise Problem(409, "MFA_ALREADY_ENROLLED", "This authenticator is already confirmed")
    if not verify(session, f, code):
        raise Problem(422, "MFA_CODE_INVALID", "The code is not valid. Check the time on your device and enter the current code.")
    f.confirmed_at = clock.now()
    user.mfa_enrolled = True
    audit.record(session, "APP_USER", user.id, "MFA_ENROLLED", object_ref=user.email, after={"kind": "TOTP"})
    return f


def disable(session: Session, user: AppUser, code: str) -> None:
    f = factor(session, user.id, lock=True)
    if f is None:
        raise Problem(404, "MFA_NOT_ENROLLED", "No authenticator is registered")
    if f.confirmed_at is not None:
        if required_for(session, user):
            raise Problem(409, "MFA_REQUIRED", "Multi-factor authentication is mandatory for your role", rule_ref="MFA")
        if not verify(session, f, code):
            raise Problem(422, "MFA_CODE_INVALID", "The code is not valid")
    session.delete(f)
    user.mfa_enrolled = False
    audit.record(session, "APP_USER", user.id, "MFA_DISABLED", object_ref=user.email, before={"kind": "TOTP"})


def admin_reset(session: Session, user: AppUser, reason: str) -> None:
    """Tenant admin removes a user's authenticator (lost or replaced phone). Never one's own: a stolen admin session must
    not be able to strip its own second factor. If MFA is mandatory for the role, the next sign-in asks to enrol again."""
    actor = session.info["principal"]

    if user.id == actor.user_id:
        raise Problem(409, "SELF_RESET", "Remove your own authenticator from your account page with a current code", rule_ref="MFA")
    if not (reason or "").strip():
        raise Problem(422, "REASON_REQUIRED", "Give the reason for the reset (e.g. the ticket for the lost phone)", rule_ref="MFA")
    f = factor(session, user.id, lock=True)
    if f is None:
        raise Problem(404, "MFA_NOT_ENROLLED", f"{user.email} has no authenticator registered")
    confirmed = f.confirmed_at is not None
    session.delete(f)
    user.mfa_enrolled = False
    audit.record(session, "APP_USER", user.id, "MFA_RESET", object_ref=user.email, before={"kind": "TOTP", "confirmed": confirmed},
                 after={"reenrolmentRequired": required_for(session, user)}, reason=reason.strip())
