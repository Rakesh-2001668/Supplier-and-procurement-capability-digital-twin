"""ADM-04 roles and permission matrix: built-in roles (read-only, in code) next to tenant-defined roles (``role_def``).

A tenant-defined role holds scopes from the assignable catalogue only (never platform-level authority). Before a role is saved the
SoD impact is computed: the role itself must not span a scope-level SoD pair, and no user who holds it may end up with a pair he or
she did not already span. A role that would create a conflict is refused (409 SOD_CONFLICT) with the evidence; the same preview is
available without saving. Changing or deactivating a role bumps the session version of its holders so they sign in with the new scopes.
"""
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import AppUser, RoleDef, Task
from app.pic.platform import audit, roles as roles_mod
from app.pic.platform.auth import ROLE_SCOPES
from app.pic.platform.errors import Problem, not_found
from app.pic.services.common import principal

BUILTIN_NAMES = {code: code.replace("_", " ").title() for code in ROLE_SCOPES}


def _admin(session: Session) -> None:
    if "TENANT_ADMIN" not in principal(session).roles:
        raise Problem(403, "FORBIDDEN", "Requires the tenant administrator", rule_ref="RBAC")


def holders(session: Session, code: str) -> list[AppUser]:
    return list(session.execute(select(AppUser).where(AppUser.roles.any(code)).order_by(AppUser.email)).scalars())


def role_view(r: RoleDef, holder_count: int = 0) -> dict:
    return {"code": r.code, "id": str(r.id), "name": r.name, "description": r.description, "kind": "CUSTOM", "scopes": sorted(r.scopes or []),
            "active": r.active, "version": r.row_version, "holders": holder_count}


def list_roles(session: Session) -> list[dict]:
    out = [{"code": code, "name": BUILTIN_NAMES[code], "description": None, "kind": "BUILT_IN", "scopes": sorted(scopes), "active": True,
            "version": None, "holders": None, "id": None} for code, scopes in ROLE_SCOPES.items() if code not in roles_mod.PLATFORM_ROLES]
    counts: dict = {}
    for user_roles in session.execute(select(AppUser.roles)).scalars():
        for code in user_roles or []:
            counts[code] = counts.get(code, 0) + 1
    out += [role_view(r, counts.get(r.code, 0)) for r in session.execute(select(RoleDef).order_by(RoleDef.code)).scalars()]
    return out


def matrix(session: Session) -> dict:
    """Scopes by role: the permission matrix of ADM-04."""
    roles = list_roles(session)
    assignable = set(roles_mod.assignable_scopes())
    every = sorted({s for r in roles for s in r["scopes"]} | assignable)
    return {"scopes": [{"scope": s, "description": roles_mod.SCOPE_DESCRIPTIONS.get(s), "assignable": s in assignable,
                        "platformLevel": s in roles_mod.PLATFORM_SCOPES} for s in every],
            "roles": roles, "sodPairs": [{"rule": c, "description": t, "sideA": sorted(a), "sideB": sorted(b)}
                                         for a, b, c, t in roles_mod.SCOPE_CONFLICTS]}


# ---------------------------------------------------------------- SoD impact
def impact(session: Session, code: str, scopes: list[str], existing: Optional[RoleDef] = None) -> dict:
    """What saving ``code`` with ``scopes`` would do: scope changes, the role's own SoD pairs and the effect on each holder."""
    new = set(scopes)
    old = set(existing.scopes or []) if existing is not None else set()
    own = roles_mod.scope_conflicts(new)
    affected = []
    for user in holders(session, code):
        others = set()
        for r in user.roles:
            if r != code:
                others |= roles_mod.effective_scopes(session, [r])
        before = {c["rule"] for c in roles_mod.scope_conflicts(others | old)}
        after = roles_mod.scope_conflicts(others | new)
        fresh = [c for c in after if c["rule"] not in before]
        affected.append({"userId": str(user.id), "email": user.email, "roles": list(user.roles), "newConflicts": fresh})
    blocked = bool(own) or any(a["newConflicts"] for a in affected)
    return {"code": code, "added": sorted(new - old), "removed": sorted(old - new), "ownConflicts": own, "holders": len(affected),
            "affectedUsers": affected, "allowed": not blocked,
            "reason": None if not blocked else "The role would let one person span a segregation-of-duties pair"}


def _check_scopes(scopes: list[str]) -> list[str]:
    scopes = sorted({s.strip() for s in scopes or [] if s and s.strip()})
    errors = []
    if not scopes:
        errors.append("choose at least one scope")
    platform = [s for s in scopes if s in roles_mod.PLATFORM_SCOPES]
    if platform:
        errors.append(f"platform-level scopes cannot be given to a tenant-defined role: {', '.join(platform)}")
    unknown = [s for s in scopes if s not in roles_mod.assignable_scopes() and s not in roles_mod.PLATFORM_SCOPES]
    if unknown:
        errors.append(f"unknown or non-assignable scopes: {', '.join(unknown)}")
    if errors:
        raise Problem(422, "SCOPE_NOT_ASSIGNABLE", "; ".join(errors), rule_ref="ADM-04", errors=errors)
    return scopes


def _refuse_if_conflicting(result: dict) -> None:
    if not result["allowed"]:
        raise Problem(409, "SOD_CONFLICT", f"{result['reason']}: " + "; ".join(
            [f"{c['rule']} ({c['description']})" for c in result["ownConflicts"]] +
            [f"{a['email']} would span {', '.join(c['rule'] for c in a['newConflicts'])}" for a in result["affectedUsers"] if a["newConflicts"]]),
            rule_ref="SOD", impact=result)


def preview(session: Session, code: str, scopes: list[str]) -> dict:
    _admin(session)
    scopes = _check_scopes(scopes)
    existing = roles_mod.definitions(session).get(code)
    return impact(session, code, scopes, existing)


def _bump_holders(session: Session, code: str) -> int:
    users = holders(session, code)
    for u in users:
        u.session_version = (u.session_version or 1) + 1
    return len(users)


def create(session: Session, code: str, name: str, description: Optional[str], scopes: list[str]) -> dict:
    _admin(session)
    code = (code or "").strip().upper()
    error = roles_mod.validate_code(code)
    if error:
        raise Problem(422, "VALIDATION_FAILED", error, rule_ref="ADM-04")
    if not name or not 2 <= len(name.strip()) <= 100:
        raise Problem(422, "VALIDATION_FAILED", "role name must be 2-100 characters", rule_ref="ADM-04")
    if code in roles_mod.definitions(session):
        raise Problem(409, "CODE_EXISTS", f"Role {code} already exists", rule_ref="ADM-04")
    scopes = _check_scopes(scopes)
    result = impact(session, code, scopes)
    _refuse_if_conflicting(result)
    r = RoleDef(tenant_id=principal(session).tenant_id, created_by=principal(session).user_id, code=code, name=name.strip(),
                description=(description or "").strip() or None, scopes=scopes, active=True)
    session.add(r)
    session.flush()
    roles_mod.forget(session)
    audit.record(session, "ROLE", r.id, "CREATED", object_ref=code, after=role_view(r))
    return role_view(r)


def get(session: Session, role_id: uuid.UUID, lock: bool = False) -> RoleDef:
    r = session.get(RoleDef, role_id, with_for_update=lock)
    if r is None:
        raise not_found("Role", role_id)
    return r


def update(session: Session, role_id: uuid.UUID, name: Optional[str], description: Optional[str], scopes: Optional[list[str]],
           reason: Optional[str]) -> dict:
    _admin(session)
    r = get(session, role_id, lock=True)
    before = role_view(r)
    bumped = 0
    if name is not None:
        if not 2 <= len(name.strip()) <= 100:
            raise Problem(422, "VALIDATION_FAILED", "role name must be 2-100 characters", rule_ref="ADM-04")
        r.name = name.strip()
    if description is not None:
        r.description = description.strip() or None
    if scopes is not None:
        new = _check_scopes(scopes)
        if set(new) != set(r.scopes or []):
            result = impact(session, r.code, new, r)
            _refuse_if_conflicting(result)
            r.scopes = new
            bumped = _bump_holders(session, r.code)
    session.flush()
    roles_mod.forget(session)
    audit.record(session, "ROLE", r.id, "UPDATED", object_ref=r.code, before=before, after={**role_view(r), "sessionsRevoked": bumped}, reason=reason)
    return role_view(r)


def set_active(session: Session, role_id: uuid.UUID, active: bool, reason: Optional[str]) -> dict:
    _admin(session)
    r = get(session, role_id, lock=True)
    if r.active == active:
        return role_view(r)
    if active:
        result = impact(session, r.code, list(r.scopes or []), None)
        _refuse_if_conflicting(result)
    r.active = active
    bumped = _bump_holders(session, r.code)
    session.flush()
    roles_mod.forget(session)
    audit.record(session, "ROLE", r.id, "ACTIVATED" if active else "DEACTIVATED", object_ref=r.code, after={"active": active, "sessionsRevoked": bumped},
                 reason=reason)
    return role_view(r)


def delete(session: Session, role_id: uuid.UUID, reason: Optional[str]) -> dict:
    """Delete an unused role; a role that users hold or tasks name is deactivated instead."""
    _admin(session)
    r = get(session, role_id, lock=True)
    in_use = bool(holders(session, r.code)) or session.execute(select(Task.id).where(Task.candidate_role == r.code).limit(1)).first()
    if in_use:
        return {"outcome": "DEACTIVATED", "reason": "Users or tasks refer to the role, so it was deactivated instead of deleted",
                "record": set_active(session, role_id, False, reason or "Referenced; deactivated instead of deleted")}
    before = role_view(r)
    session.delete(r)
    session.flush()
    roles_mod.forget(session)
    audit.record(session, "ROLE", role_id, "DELETED", object_ref=before["code"], before=before, reason=reason)
    return {"outcome": "DELETED", "record": before}


# ---------------------------------------------------------------- assignment checks (used by user admin)
def check_assignment(session: Session, roles: list[str], user: Optional[AppUser] = None) -> None:
    """Known roles, no supplier role on internal users, no SoD pair (role pairs and scope pairs)."""
    from app.pic.services import admin
    known = roles_mod.known_roles(session)
    unknown = [r for r in roles if r not in known]
    if unknown:
        raise Problem(422, "UNKNOWN_ROLE", f"Unknown or inactive role(s): {', '.join(unknown)}")
    for a, b, rule in admin.TOXIC_PAIRS:
        if a & set(roles) and b & set(roles):
            raise Problem(409, "SOD_CONFLICT", f"Role combination not allowed ({rule})", rule_ref=rule.split(":")[0])
    hits = roles_mod.scope_conflicts(roles_mod.effective_scopes(session, roles))
    if hits:
        raise Problem(409, "SOD_CONFLICT", "Role combination not allowed: " + "; ".join(f"{h['rule']} ({h['description']})" for h in hits),
                      rule_ref=hits[0]["rule"], conflicts=hits)
