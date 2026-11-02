"""Roles beyond the built-in catalogue (ADM-04): the assignable scope catalogue, scope-level segregation-of-duties pairs and the
resolution of tenant-defined roles (``role_def``) into scopes.

Built-in roles live in ``auth.ROLE_SCOPES`` and are read-only. A tenant-defined role is a named subset of the *assignable* scopes:
never a platform-level scope (``admin:*``, ``agents:manage``) and never a supplier-portal scope, so a tenant cannot mint a second
administrator role or give an internal user supplier powers. The scopes of a custom role travel in the access token (claim ``xs``,
filtered against the catalogue again on read); changing a role bumps the session version of everyone holding it, so the new scopes
apply from their next sign-in and the hot path (one query per request, already made for revocation) stays unchanged.
"""
import re
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.platform.auth import READ, ROLE_SCOPES, TASKS

ROLE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,39}$")
# Platform-level authority that only the built-in TENANT_ADMIN role carries.
PLATFORM_SCOPES = {"admin:rules", "admin:audit", "admin:integration", "admin:ops", "admin:workflow", "agents:manage"}

SCOPE_DESCRIPTIONS = {
    READ: "Read documents and master data the user is assigned to",
    TASKS: "Work the approval inbox and tasks addressed to the user",
    "req:create": "Create and submit requisitions", "ses:create": "Create service entry sheets",
    "mrp:run": "Run material requirements planning", "mrp:plan": "Convert planned orders into requisitions and orders",
    "req:buyer": "Process requisitions as a buyer (sourcing, conversion)", "po:create": "Create purchase orders",
    "po:release": "Release purchase orders", "po:change": "Change purchase orders and schedules",
    "sourcing:manage": "Create and run sourcing events", "sourcing:evaluate": "Score bids and technical evaluations",
    "savings:manage": "Maintain savings initiatives", "savings:validate": "Validate realised savings (finance)",
    "spend:read": "See the spend cube and analytics", "supplier:manage": "Maintain suppliers and onboarding",
    "supplier:bank": "Change supplier bank details", "contract:manage": "Maintain contracts", "contract:sign": "Sign contracts",
    "mdm:request": "Raise and decide master data requests", "gr:post": "Post goods receipts", "quality:decide": "Take quality decisions",
    "ses:approve": "Approve service entry sheets", "invoice:capture": "Capture invoices", "invoice:resolve": "Resolve invoice exceptions",
    "invoice:approve": "Approve invoices", "invoice:post": "Post invoices", "payment:run": "Run and release payments",
    "period:close": "Close and reopen posting periods (cut-off)",
}

# Scope pairs one person must not hold together: the scope-level form of the role pairs in services.admin.TOXIC_PAIRS
# (blueprint section 4.1). Checked when a custom role is saved and whenever roles are assigned.
SCOPE_CONFLICTS = [
    ({"supplier:bank"}, {"payment:run"}, "SOD-02", "bank changes and payment approval"),
    ({"po:create", "po:release"}, {"gr:post"}, "SOD-03", "PO creation and goods receipt"),
    ({"po:create", "po:release"}, {"invoice:capture", "invoice:resolve", "invoice:post"}, "SOD-04", "PO creation and invoice exceptions"),
]


def assignable_scopes() -> list[str]:
    """Scopes a tenant-defined role may hold: everything the built-in internal roles use, minus platform-level authority."""
    supplier_only = set(ROLE_SCOPES["SUPPLIER_USER"])
    for role, scopes in ROLE_SCOPES.items():
        if role != "SUPPLIER_USER":
            supplier_only -= scopes
    internal = set().union(*(s for r, s in ROLE_SCOPES.items() if r != "SUPPLIER_USER"))
    return sorted(internal - PLATFORM_SCOPES - supplier_only)


def catalogue() -> list[dict]:
    return [{"scope": s, "description": SCOPE_DESCRIPTIONS.get(s, s)} for s in assignable_scopes()]


def scope_conflicts(scopes: Iterable[str]) -> list[dict]:
    """The SoD pairs a holder of ``scopes`` would span."""
    have = set(scopes)
    hits = []
    for a, b, code, text in SCOPE_CONFLICTS:
        if have & a and have & b:
            hits.append({"rule": code, "description": text, "sideA": sorted(have & a), "sideB": sorted(have & b)})
    return hits


def validate_code(code: str) -> Optional[str]:
    if not ROLE_CODE_RE.match(code or ""):
        return "role code must be 3-40 characters: capital letters, digits and underscores, starting with a letter"
    if code in ROLE_SCOPES:
        return f"{code} is a built-in role and cannot be redefined"
    return None


# ---------------------------------------------------------------- resolution (cached per session = per request)
def definitions(session: Session) -> dict:
    cache = session.info.get("_role_defs")
    if cache is None:
        from app.pic.models import RoleDef
        cache = {r.code: r for r in session.execute(select(RoleDef)).scalars()}
        session.info["_role_defs"] = cache
    return cache


def forget(session: Session) -> None:
    session.info.pop("_role_defs", None)


def scopes_of(session: Session, roles: Iterable[str]) -> set[str]:
    """Scopes of the tenant-defined roles among ``roles`` (built-in roles are ignored here), restricted to the catalogue."""
    unknown = [r for r in roles if r not in ROLE_SCOPES]
    if not unknown:
        return set()
    allowed = set(assignable_scopes())
    defs = definitions(session)
    out: set[str] = set()
    for code in unknown:
        d = defs.get(code)
        if d is not None and d.active:
            out |= set(d.scopes or []) & allowed
    return out


def effective_scopes(session: Session, roles: Iterable[str]) -> set[str]:
    roles = list(roles)
    out: set[str] = set()
    for r in roles:
        out |= ROLE_SCOPES.get(r, set())
    return out | scopes_of(session, roles)


def known_roles(session: Session) -> set[str]:
    return set(ROLE_SCOPES) | {c for c, d in definitions(session).items() if d.active}
