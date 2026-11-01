"""M13 enterprise administration API: organisation masters (ADM-01), user lifecycle and custom roles (ADM-04), template packs.

Conventions of the platform: tenant from the token only, problem+json errors, Idempotency-Key on creating POSTs, the record's row
version as ETag (``If-Match`` on updates is checked by the HTTP layer; the response carries the new ETag), every write audited.
Tenant provisioning is deliberately not here: it is the command-line tool ``python -m app.pic.tools.tenant_admin``.
"""
import uuid
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.pic.api.deps import idempotency_key, idempotent, uow
from app.pic.api.master_ops import _failed, _tenant, _throttle
from app.pic.db import tenant_tx
from app.pic.models import AppUser
from app.pic.platform.auth import READ, Principal, require
from app.pic.platform.errors import Problem
from app.pic.services import org_admin, role_admin, template_admin, user_admin

router = APIRouter(prefix="/v1")
ADMIN = "admin:rules"


def _etag(response: Response, view: dict) -> dict:
    if view.get("version") is not None:
        response.headers["ETag"] = f'"{view["version"]}"'
    return view


class ReasonIn(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


class RequiredReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


# ---------------------------------------------------------------- ADM-01 organisation masters
class MasterIn(BaseModel):
    """Fields by master. company-codes: code, name, gstin, currency, fiscal_year_start_month. plants: code, company_code, name,
    state_code, working_days. storage-locations: plant, code, name. cost-objects: type, code, company_code, name, owner_user_id,
    department_head_user_id. purchasing-orgs: code, company_code, name. purchasing-groups: code, name, purchasing_org, plant,
    buyer_user_ids. currencies: code, name, decimals. On update only the editable fields are read (a code never changes)."""
    model_config = {"extra": "allow"}
    reason: Optional[str] = Field(default=None, max_length=500)


def _body(model: BaseModel) -> dict:
    data = model.model_dump(mode="json")
    data.pop("reason", None)
    return data


@router.get("/admin/org/{kind}", tags=["Admin · organisation"])
def list_masters(kind: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return org_admin.list_all(s, org_admin.kind_of(kind))


class HolidaysIn(BaseModel):
    dates: list[date] = Field(min_length=1, max_length=400)
    source: str = Field(min_length=5, max_length=300, description="Gazette notification / G.O. the dates come from")


@router.post("/admin/org/plants/{record_id}/holidays", tags=["Admin · organisation"])
def add_holidays(record_id: uuid.UUID, body: HolidaysIn, response: Response, p: Principal = Depends(require(ADMIN))):
    with uow(p) as s:
        return _etag(response, org_admin.add_holidays(s, record_id, body.dates, body.source))


@router.delete("/admin/org/plants/{record_id}/holidays/{day}", tags=["Admin · organisation"])
def remove_holiday(record_id: uuid.UUID, day: date, response: Response, reason: str = Query(min_length=5, max_length=300),
                   p: Principal = Depends(require(ADMIN))):
    with uow(p) as s:
        return _etag(response, org_admin.remove_holiday(s, record_id, day, reason))


@router.post("/admin/org/{kind}", status_code=201, tags=["Admin · organisation"])
def create_master(kind: str, body: MasterIn, response: Response, p: Principal = Depends(require(ADMIN)),
                  key: Optional[str] = Depends(idempotency_key)):
    k = org_admin.kind_of(kind)
    with uow(p) as s:
        guard = idempotent(s, f"POST /v1/admin/org/{kind}", key, body)
        if guard.replay:
            return guard.replay
        return guard.store(_etag(response, org_admin.create(s, k, _body(body))), 201)


@router.put("/admin/org/{kind}/{record_id}", tags=["Admin · organisation"])
def update_master(kind: str, record_id: uuid.UUID, body: MasterIn, response: Response, p: Principal = Depends(require(ADMIN))):
    with uow(p) as s:
        return _etag(response, org_admin.update(s, org_admin.kind_of(kind), record_id, _body(body), body.reason))


@router.post("/admin/org/{kind}/{record_id}/deactivate", tags=["Admin · organisation"])
def deactivate_master(kind: str, record_id: uuid.UUID, response: Response, body: ReasonIn = ReasonIn(), p: Principal = Depends(require(ADMIN))):
    with uow(p) as s:
        return _etag(response, org_admin.set_active(s, org_admin.kind_of(kind), record_id, False, body.reason))


@router.post("/admin/org/{kind}/{record_id}/activate", tags=["Admin · organisation"])
def activate_master(kind: str, record_id: uuid.UUID, response: Response, body: ReasonIn = ReasonIn(), p: Principal = Depends(require(ADMIN))):
    with uow(p) as s:
        return _etag(response, org_admin.set_active(s, org_admin.kind_of(kind), record_id, True, body.reason))


@router.delete("/admin/org/{kind}/{record_id}", tags=["Admin · organisation"])
def delete_master(kind: str, record_id: uuid.UUID, reason: Optional[str] = Query(default=None, max_length=500),
                  p: Principal = Depends(require(ADMIN))):
    """Deletes an unreferenced record; a record that anything refers to is deactivated instead (the outcome says which)."""
    with uow(p) as s:
        return org_admin.delete(s, org_admin.kind_of(kind), record_id, reason)


# ---------------------------------------------------------------- ADM-04 user lifecycle
class InviteIn(BaseModel):
    email: str = Field(min_length=5, max_length=200)
    name: str = Field(min_length=2, max_length=200)
    roles: list[str] = Field(min_length=1)
    attributes: dict = Field(default_factory=dict, description="plants, company_codes (lists of codes or '*'), value_limit_minor (paise)")


@router.post("/admin/users", status_code=201, tags=["Admin · users"])
def invite_user(body: InviteIn, p: Principal = Depends(require(ADMIN)), key: Optional[str] = Depends(idempotency_key)):
    """Creates the user (no password) and a single-use activation link, returned once here and e-mailed when SMTP is configured."""
    with uow(p) as s:
        guard = idempotent(s, "POST /v1/admin/users", key, body)
        if guard.replay:
            return guard.replay
        return guard.store(user_admin.invite(s, body.email, body.name, body.roles, body.attributes), 201)


def _user(s, user_id: uuid.UUID) -> AppUser:
    return user_admin.get_user(s, user_id)


@router.post("/admin/users/{user_id}/resend-invitation", tags=["Admin · users"])
def resend_invitation(user_id: uuid.UUID, p: Principal = Depends(require(ADMIN))):
    with uow(p) as s:
        return user_admin.resend_invitation(s, _user(s, user_id))


@router.post("/admin/users/{user_id}/password-reset", tags=["Admin · users"])
def password_reset(user_id: uuid.UUID, body: RequiredReasonIn, p: Principal = Depends(require(ADMIN))):
    with uow(p) as s:
        return user_admin.reset_password(s, _user(s, user_id), body.reason)


@router.post("/admin/users/{user_id}/revoke-sessions", tags=["Admin · users"])
def revoke_sessions(user_id: uuid.UUID, body: RequiredReasonIn, p: Principal = Depends(require(ADMIN))):
    with uow(p) as s:
        return user_admin.revoke_sessions(s, _user(s, user_id), body.reason)


class AttributesIn(BaseModel):
    attributes: dict
    reason: str = Field(min_length=3, max_length=500)


@router.put("/admin/users/{user_id}/attributes", tags=["Admin · users"])
def set_attributes(user_id: uuid.UUID, body: AttributesIn, response: Response, p: Principal = Depends(require(ADMIN))):
    """Replace the ABAC attributes (plants, company codes, value limit). The user's sessions end so the new limits apply at once."""
    from app.pic.platform import audit
    with uow(p) as s:
        user_admin._admin(s)
        user = _user(s, user_id)
        attrs, errors = user_admin.clean_attributes(s, body.attributes)
        if errors:
            raise Problem(422, "VALIDATION_FAILED", "; ".join(errors), rule_ref="ADM-04", errors=errors)
        before = dict(user.attributes or {})
        user.attributes = attrs
        user.session_version = (user.session_version or 1) + 1
        s.flush()
        audit.record(s, "APP_USER", user.id, "ATTRIBUTES_CHANGED", object_ref=user.email, before={"attributes": before},
                     after={"attributes": attrs}, reason=body.reason)
        return _etag(response, user_admin.view(user))


class ImportIn(BaseModel):
    csv: str = Field(min_length=10, max_length=500_000)
    dry_run: bool = True


@router.post("/admin/users/import", tags=["Admin · users"])
def import_users(body: ImportIn, p: Principal = Depends(require(ADMIN)), key: Optional[str] = Depends(idempotency_key)):
    """Bulk invite from CSV (email, name, roles, plants, company_codes, value_limit_minor). Default is a dry run that reports every row."""
    with uow(p) as s:
        guard = idempotent(s, "POST /v1/admin/users/import", key, body)
        if guard.replay:
            return guard.replay
        return guard.store(user_admin.import_csv(s, body.csv, body.dry_run))


# ---------------------------------------------------------------- public: activation and reset links
def _link_tenant(request: Request, token: str):
    _throttle(request)
    tenant = _tenant(user_admin_tenant_code(token))
    if tenant is None:
        _failed(request)
        raise Problem(404, "LINK_NOT_FOUND", "This link is not valid")
    return tenant


def user_admin_tenant_code(token: str) -> Optional[str]:
    from app.pic.services import invitations
    return invitations.tenant_code_of(token)


@router.get("/public/user-tokens/{token}", tags=["Admin · users · public"])
def link_info(token: str, request: Request):
    tenant = _link_tenant(request, token)
    try:
        with tenant_tx(tenant.id) as s:
            row = user_admin.find(s, token)
            user_admin.check_usable(row)
            return user_admin.public_view(s, row, tenant)
    except Problem as exc:
        if exc.status in (404, 410):
            _failed(request)
        raise


class CompleteIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


@router.post("/public/user-tokens/{token}/complete", tags=["Admin · users · public"])
def link_complete(token: str, body: CompleteIn, request: Request):
    """Sets the password and uses the link up. Works once; every earlier session of the user ends."""
    tenant = _link_tenant(request, token)
    try:
        with tenant_tx(tenant.id) as s:
            row = user_admin.find(s, token, lock=True)
            return user_admin.complete(s, row, tenant, body.password)
    except Problem as exc:
        if exc.status in (404, 410):
            _failed(request)
        raise


# ---------------------------------------------------------------- ADM-04 custom roles and the permission matrix
@router.get("/admin/roles/matrix", tags=["Admin · roles"])
def role_matrix(p: Principal = Depends(require(READ))):
    """Scopes by role (built-in read-only, tenant-defined editable), the assignable scope catalogue and the SoD scope pairs."""
    with uow(p) as s:
        return role_admin.matrix(s)


class RolePreviewIn(BaseModel):
    code: str = Field(min_length=3, max_length=40)
    scopes: list[str]


@router.post("/admin/roles/preview", tags=["Admin · roles"])
def preview_role(body: RolePreviewIn, p: Principal = Depends(require(ADMIN))):
    """SoD impact of saving a role with these scopes: its own pairs and the effect on each user who holds it. Saves nothing."""
    with uow(p) as s:
        return role_admin.preview(s, body.code.strip().upper(), body.scopes)


class RoleIn(BaseModel):
    code: str = Field(min_length=3, max_length=40)
    name: str = Field(min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    scopes: list[str] = Field(min_length=1)


@router.post("/admin/roles", status_code=201, tags=["Admin · roles"])
def create_role(body: RoleIn, response: Response, p: Principal = Depends(require(ADMIN)), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        guard = idempotent(s, "POST /v1/admin/roles", key, body)
        if guard.replay:
            return guard.replay
        return guard.store(_etag(response, role_admin.create(s, body.code, body.name, body.description, body.scopes)), 201)


class RoleUpdateIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    scopes: Optional[list[str]] = None
    reason: Optional[str] = Field(default=None, max_length=500)


@router.put("/admin/roles/{role_id}", tags=["Admin · roles"])
def update_role(role_id: uuid.UUID, body: RoleUpdateIn, response: Response, p: Principal = Depends(require(ADMIN))):
    with uow(p) as s:
        return _etag(response, role_admin.update(s, role_id, body.name, body.description, body.scopes, body.reason))


@router.post("/admin/roles/{role_id}/deactivate", tags=["Admin · roles"])
def deactivate_role(role_id: uuid.UUID, response: Response, body: ReasonIn = ReasonIn(), p: Principal = Depends(require(ADMIN))):
    with uow(p) as s:
        return _etag(response, role_admin.set_active(s, role_id, False, body.reason))


@router.post("/admin/roles/{role_id}/activate", tags=["Admin · roles"])
def activate_role(role_id: uuid.UUID, response: Response, body: ReasonIn = ReasonIn(), p: Principal = Depends(require(ADMIN))):
    with uow(p) as s:
        return _etag(response, role_admin.set_active(s, role_id, True, body.reason))


@router.delete("/admin/roles/{role_id}", tags=["Admin · roles"])
def delete_role(role_id: uuid.UUID, reason: Optional[str] = Query(default=None, max_length=500), p: Principal = Depends(require(ADMIN))):
    with uow(p) as s:
        return role_admin.delete(s, role_id, reason)


# ---------------------------------------------------------------- industry template packs
@router.get("/admin/templates/{code}/preview", tags=["Admin · templates"])
def template_preview(code: str, p: Principal = Depends(require(READ))):
    """What applying the template would change: rule sets added, re-versioned or returned to default, and what is left alone."""
    with uow(p) as s:
        return template_admin.preview(s, code.upper())


@router.post("/admin/templates/{code}/apply", tags=["Admin · templates"])
def template_apply(code: str, p: Principal = Depends(require(ADMIN)), key: Optional[str] = Depends(idempotency_key)):
    """Applies the template (new effective-dated rule versions, never edits). Applying it again changes nothing."""
    from app.pic.seed import reference
    reference.ensure_extensions(p.tenant_id)  # number ranges, currencies, agents and baselines an older release may lack (idempotent)
    with uow(p) as s:
        guard = idempotent(s, f"POST /v1/admin/templates/{code}/apply", key, {"code": code})
        if guard.replay:
            return guard.replay
        return guard.store(template_admin.apply(s, code.upper()))
