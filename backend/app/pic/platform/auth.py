"""Identity and authorisation (§14): bearer tokens, RBAC scopes and ABAC attributes.

The tenant is taken from the token only, never from a request body or query.
This module issues HS256 tokens for the built-in login; an OIDC provider
(Keycloak) can replace ``issue_token`` without changing any endpoint.
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, Header
import jwt
from jwt import PyJWTError as JWTError

from app.pic.config import get_settings
from app.pic.platform.errors import Problem

ALGORITHM = "HS256"
READ = "pic:read"
TASKS = "tasks:work"

# Blueprint §4 roles mapped to API scopes.
ROLE_SCOPES: dict[str, set[str]] = {
    "REQUESTER": {READ, TASKS, "req:create", "ses:create"},
    "COST_OBJECT_OWNER": {READ, TASKS},
    "DEPT_HEAD": {READ, TASKS},
    "MRP_CONTROLLER": {READ, TASKS, "mrp:run", "mrp:plan", "req:create"},
    "BUYER": {READ, TASKS, "req:buyer", "po:create", "po:release", "po:change", "sourcing:manage", "req:create"},
    "CATEGORY_MANAGER": {READ, TASKS, "sourcing:manage", "sourcing:evaluate", "savings:manage", "spend:read"},
    "SUPPLIER_MANAGER": {READ, TASKS, "supplier:manage", "supplier:bank"},
    "CONTRACT_MANAGER": {READ, TASKS, "contract:manage", "contract:sign"},
    "LEGAL": {READ, TASKS},
    "MDM_STEWARD": {READ, TASKS, "mdm:request"},
    "RECEIVER": {READ, TASKS, "gr:post"},
    "QUALITY_INSPECTOR": {READ, TASKS, "quality:decide", "sourcing:evaluate"},
    "SERVICE_OWNER": {READ, TASKS, "ses:approve"},
    "AP_CLERK": {READ, TASKS, "invoice:capture", "invoice:resolve", "invoice:approve", "invoice:post"},
    "FINANCE_CONTROLLER": {READ, TASKS, "payment:run", "savings:validate", "invoice:approve", "spend:read"},
    "PROCUREMENT_HEAD": {READ, TASKS, "spend:read"},
    "CPO": {READ, TASKS, "spend:read", "agents:manage"},
    "CAPEX_COMMITTEE": {READ, TASKS},
    "TENANT_ADMIN": {READ, TASKS, "admin:rules", "admin:audit", "admin:integration", "agents:manage", "admin:ops"},
    # External supplier users: only supplier-side commands on their own documents.
    "SUPPLIER_USER": {"supplier:portal", "bid:submit", "po:confirm", "asn:create", "invoice:submit", "ses:create"},
}


@dataclass
class Principal:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_code: str
    email: str
    name: str
    roles: list[str]
    scopes: set[str]
    attributes: dict = field(default_factory=dict)
    supplier_id: Optional[uuid.UUID] = None
    agent_code: Optional[str] = None

    @property
    def actor(self) -> str:
        return f"agent:{self.agent_code}" if self.agent_code else f"u:{self.email}"

    @property
    def is_agent(self) -> bool:
        return self.agent_code is not None

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def attr(self, key: str, default=None):
        return self.attributes.get(key, default)


def scopes_for(roles: list[str]) -> set[str]:
    scopes: set[str] = set()
    for role in roles:
        scopes |= ROLE_SCOPES.get(role, set())
    return scopes


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(rounds=10)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def issue_token(user, tenant, amr: Optional[list[str]] = None) -> str:
    settings = get_settings()
    # Token lifetime follows the wall clock even when the business clock is pinned.
    issued = datetime.now(timezone.utc)
    claims = {
        "sub": str(user.id),
        "tid": str(tenant.id),
        "tcode": tenant.code,
        "email": user.email,
        "name": user.full_name,
        "roles": list(user.roles),
        "attrs": user.attributes or {},
        "sup": str(user.supplier_id) if user.supplier_id else None,
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(minutes=settings.jwt_ttl_minutes)).timestamp()),
        "iss": "pic",
        # Authentication methods used for this session (RFC 8176): pwd, otp, or the identity provider's amr after SSO.
        "amr": list(amr or ["pwd"]),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM)


def token_response(user, tenant, amr: Optional[list[str]] = None) -> dict:
    return {"access_token": issue_token(user, tenant, amr), "token_type": "bearer", "roles": user.roles, "tenant": tenant.code}


# ---------------------------------------------------------------- short-lived signed challenges (MFA, enrolment, OIDC state)
CHALLENGE_ISSUER = "pic:challenge"
MFA_CHALLENGE = "mfa-login"
MFA_ENROLMENT = "mfa-enrol"


def issue_challenge(purpose: str, claims: dict, ttl_seconds: int = 300) -> str:
    """Signed value that is never an access token: a different issuer and audience, so ``principal_from_token`` rejects it."""
    issued = datetime.now(timezone.utc)
    body = {**claims, "iss": CHALLENGE_ISSUER, "aud": purpose, "jti": uuid.uuid4().hex,
            "iat": int(issued.timestamp()), "exp": int((issued + timedelta(seconds=ttl_seconds)).timestamp())}
    return jwt.encode(body, get_settings().jwt_secret, algorithm=ALGORITHM)


def read_challenge(token: str, purpose: str, code: str = "CHALLENGE_INVALID") -> dict:
    try:
        return jwt.decode(token or "", get_settings().jwt_secret, algorithms=[ALGORITHM], issuer=CHALLENGE_ISSUER, audience=purpose)
    except JWTError as exc:
        raise Problem(401, code, f"The sign-in step has expired or is not valid ({exc}); sign in again")


def user_challenge(purpose: str, user, tenant, ttl_seconds: int = 300) -> str:
    return issue_challenge(purpose, {"sub": str(user.id), "tid": str(tenant.id), "tcode": tenant.code, "email": user.email,
                                     "name": user.full_name}, ttl_seconds)


def principal_from_token(token: str) -> Principal:
    try:
        claims = jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM], issuer="pic")
    except JWTError as exc:
        raise Problem(401, "UNAUTHENTICATED", f"Invalid or expired token: {exc}")
    roles = claims.get("roles", [])
    return Principal(
        user_id=uuid.UUID(claims["sub"]),
        tenant_id=uuid.UUID(claims["tid"]),
        tenant_code=claims.get("tcode", ""),
        email=claims.get("email", ""),
        name=claims.get("name", ""),
        roles=roles,
        scopes=scopes_for(roles),
        attributes=claims.get("attrs") or {},
        supplier_id=uuid.UUID(claims["sup"]) if claims.get("sup") else None,
    )


def current_principal(authorization: Optional[str] = Header(default=None)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Problem(401, "UNAUTHENTICATED", "Send 'Authorization: Bearer <token>' from POST /v1/auth/token")
    return principal_from_token(authorization.split(" ", 1)[1].strip())


def enrolment_principal(authorization: Optional[str] = Header(default=None)) -> Principal:
    """Accepts a normal access token, or the enrolment challenge returned with MFA_ENROLMENT_REQUIRED.
    A challenge principal has no roles or scopes, so it can only call the MFA enrolment endpoints."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Problem(401, "UNAUTHENTICATED", "Send 'Authorization: Bearer <token>' from POST /v1/auth/token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except JWTError:
        claims = {}
    if claims.get("iss") != CHALLENGE_ISSUER:
        return principal_from_token(token)
    claims = read_challenge(token, MFA_ENROLMENT)
    return Principal(user_id=uuid.UUID(claims["sub"]), tenant_id=uuid.UUID(claims["tid"]), tenant_code=claims.get("tcode", ""),
                     email=claims.get("email", ""), name=claims.get("name", ""), roles=[], scopes=set(),
                     attributes={"mfa_enrolment": True})


def require(*scopes: str):
    """Endpoint dependency: the caller must hold every listed scope."""

    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        missing = [s for s in scopes if s not in principal.scopes]
        if missing:
            raise Problem(403, "FORBIDDEN", f"Missing scope(s): {', '.join(missing)}", rule_ref="RBAC")
        return principal

    return dependency


def require_any(*scopes: str):
    """Endpoint dependency: the caller must hold at least one of the scopes (e.g. supplier user or supplier manager)."""

    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if not any(s in principal.scopes for s in scopes):
            raise Problem(403, "FORBIDDEN", f"Requires one of: {', '.join(scopes)}", rule_ref="RBAC")
        return principal

    return dependency


def check_value_limit(principal: Principal, amount_minor: int, rule_ref: str = "ABAC") -> None:
    limit = principal.attr("value_limit_minor")
    if limit is not None and amount_minor > int(limit):
        raise Problem(403, "VALUE_LIMIT_EXCEEDED", f"Amount exceeds your approval limit", rule_ref=rule_ref)


def check_attr(principal: Principal, attr: str, value: Optional[str], rule_ref: str = "ABAC") -> None:
    """ABAC: the principal must be assigned to the company code, plant or category."""
    if value is None or principal.is_agent:
        return
    allowed = principal.attr(attr)
    if allowed is None or "*" in allowed:
        return
    if value not in allowed:
        raise Problem(403, "FORBIDDEN", f"You are not assigned to {attr.rstrip('s')} {value}", rule_ref=rule_ref)


def agent_principal(base: Principal, agent_code: str, role: str) -> Principal:
    """Agents act with the permissions of the role they run under, never more (§13.2)."""
    return Principal(
        user_id=uuid.uuid5(uuid.NAMESPACE_URL, f"pic-agent:{base.tenant_id}:{agent_code}"),
        tenant_id=base.tenant_id,
        tenant_code=base.tenant_code,
        email=f"{agent_code.lower()}@agents.pic",
        name=agent_code,
        roles=[role],
        scopes=scopes_for([role]),
        attributes={"company_codes": ["*"], "plants": ["*"]},
        agent_code=agent_code,
    )
