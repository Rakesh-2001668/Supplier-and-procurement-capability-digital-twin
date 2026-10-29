"""Notifications, ERP imports and connectors, MFA and single sign-on."""
import threading
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.pic.api.deps import uow
from app.pic.api.pagination import Page, paginate
from app.pic.db import system_tx, tenant_tx
from app.pic.models import AppUser, IntegrationBatch, Notification, Tenant
from app.pic.platform import audit, connectors, http, integration, mfa, oidc
from app.pic.platform.auth import (
    MFA_CHALLENGE, Principal, current_principal, enrolment_principal, read_challenge, require, require_any, token_response,
)
from app.pic.platform.errors import Problem, not_found
from app.pic.platform.serialize import jsonable, row
from app.pic.services import erp_import, notifications

router = APIRouter(prefix="/v1")


# ---------------------------------------------------------------- M13 notifications
@router.get("/notifications", tags=["Notifications"])
def list_notifications(unread: Optional[bool] = Query(default=None, description="true: unread only, false: read only"),
                       page: Page = Depends(), p: Principal = Depends(current_principal)):
    with uow(p) as s:
        result = paginate(s, notifications.inbox(s, p.user_id, unread=unread), Notification, page)
        return {**result, "unread": notifications.unread_count(s, p.user_id)}


@router.get("/notifications/unread-count", tags=["Notifications"])
def unread_notifications(p: Principal = Depends(current_principal)):
    with uow(p) as s:
        return {"unread": notifications.unread_count(s, p.user_id)}


@router.post("/notifications/read-all", tags=["Notifications"])
def read_all_notifications(p: Principal = Depends(current_principal)):
    with uow(p) as s:
        return {"updated": notifications.mark_all_read(s, p.user_id), "unread": 0}


@router.post("/notifications/{notification_id}/read", tags=["Notifications"])
def read_notification(notification_id: uuid.UUID, p: Principal = Depends(current_principal)):
    with uow(p) as s:
        return row(notifications.mark_read(s, p.user_id, notification_id))


# ---------------------------------------------------------------- AD-05 ERP planned-order import
IMPORT_SCOPES = ("mrp:run", "admin:integration")  # MRP controller or tenant admin


class PlannedOrderImport(BaseModel):
    system: str = Field(description="Source ERP, e.g. SAP_S4, ORACLE_FUSION, DYNAMICS_365, TALLY_PRIME, ODOO")
    batchRef: str = Field(description="The ERP's batch / run reference; resending it is idempotent")
    rows: list[dict[str, Any]] = Field(description="[{externalRef, material, plant, qty, needDate, releaseDate?, supplier?, storageLocation?}]")


def _import_response(result: dict) -> JSONResponse:
    return JSONResponse(status_code=200 if result["replayed"] else 201, content=jsonable(result))


@router.post("/integration/planned-orders/import", status_code=201, tags=["Integration"])
def import_planned_orders(body: PlannedOrderImport, p: Principal = Depends(require_any(*IMPORT_SCOPES))):
    with uow(p) as s:
        result = erp_import.import_planned_orders(s, system=body.system, batch_ref=body.batchRef, rows=body.rows)
    return _import_response(result)


@router.post("/integration/planned-orders/import/csv", status_code=201, tags=["Integration"],
             openapi_extra={"requestBody": {"content": {"text/csv": {"schema": {"type": "string"}},
                                                        "multipart/form-data": {"schema": {"type": "object", "properties": {
                                                            "file": {"type": "string", "format": "binary"}, "system": {"type": "string"},
                                                            "batchRef": {"type": "string"}}}}}}})
async def import_planned_orders_csv(request: Request, system: Optional[str] = None, batchRef: Optional[str] = None,  # noqa: N803
                                    p: Principal = Depends(require_any(*IMPORT_SCOPES))):
    """CSV with header externalRef,material,plant,qty,needDate[,releaseDate,supplier,storageLocation]; text/csv or multipart field 'file'."""
    body = await request.body()
    if len(body) > 5_000_000:
        raise Problem(413, "FILE_TOO_LARGE", "The CSV file is larger than 5 MB; split the import")
    fields, content = erp_import.parse_upload(request.headers.get("content-type", ""), body)
    system, batch_ref = system or fields.get("system"), batchRef or fields.get("batchRef")
    if not system or not batch_ref:
        raise Problem(422, "BATCH_PARAMETERS", "Give system and batchRef as query parameters or form fields")
    rows = erp_import.parse_csv(content)
    with uow(p) as s:
        result = erp_import.import_planned_orders(s, system=system, batch_ref=batch_ref, rows=rows)
    return _import_response(result)


@router.get("/integration/batches", tags=["Integration"])
def integration_batches(kind: Optional[str] = None, system: Optional[str] = None, page: Page = Depends(),
                        p: Principal = Depends(require_any(*IMPORT_SCOPES))):
    with uow(p) as s:
        def render(batch):
            v = erp_import.view(s, batch)
            v["results"] = [r for r in v["results"] if r.get("status") == "REJECTED"][:20]
            return v
        return paginate(s, erp_import.batches(s, kind, system), IntegrationBatch, page, render)


@router.get("/integration/batches/{ref}", tags=["Integration"])
def integration_batch(ref: str, p: Principal = Depends(require_any(*IMPORT_SCOPES))):
    with uow(p) as s:
        try:
            batch = s.get(IntegrationBatch, uuid.UUID(ref))
        except ValueError:
            batch = s.execute(select(IntegrationBatch).where(IntegrationBatch.number == ref)).scalar_one_or_none()
        if batch is None:
            raise not_found("Integration batch", ref)
        return erp_import.view(s, batch)


# ---------------------------------------------------------------- TD §12.1 ERP connectors
@router.get("/admin/connectors", tags=["Integration"])
def list_connectors(p: Principal = Depends(require("admin:integration"))):
    with uow(p) as s:
        return {"defaultTarget": integration.target_system(s), "connectors": connectors.status(s)}


@router.post("/admin/connectors/{system}/test", tags=["Integration"])
def test_connector(system: str, p: Principal = Depends(require("admin:integration"))):
    try:
        connector = connectors.get(system)
    except connectors.ConnectorError:
        raise not_found("Connector", system)
    result = connectors.check_health(connector.system)
    with uow(p) as s:
        audit.record(s, "ERP_CONNECTOR", uuid.uuid5(uuid.NAMESPACE_URL, f"pic-connector:{connector.system}"), "HEALTH_CHECKED",
                     object_ref=connector.system, after={"healthy": result["healthy"], "detail": result["detail"]})
    return {"system": connector.system, "configured": connector.configured(), **result}


# ---------------------------------------------------------------- §14 MFA (TOTP)
_challenge_failures: dict[str, tuple[int, float]] = {}  # challenge id -> (wrong codes, challenge expiry)
_challenge_lock = threading.Lock()
MAX_CODE_ATTEMPTS = 5


def _throttle(request: Request) -> None:
    """The same per-IP brute-force window as POST /v1/auth/token (platform/http.py)."""
    window = http._login_attempts[http._client_ip(request)]
    http._prune(window)
    if len(window) >= http.LOGIN_MAX_ATTEMPTS:
        raise Problem(429, "TOO_MANY_ATTEMPTS", "Too many sign-in attempts. Wait 5 minutes and try again.")


def _failures(jti: str) -> int:
    with _challenge_lock:
        return _challenge_failures.get(jti, (0, 0.0))[0]


def _count_failure(request: Request, claims: Optional[dict] = None) -> int:
    http.record_login_failure(request)
    if not claims:
        return 0
    with _challenge_lock:
        now = time.time()
        for key in [k for k, (_, exp) in _challenge_failures.items() if exp < now]:
            _challenge_failures.pop(key, None)
        count = _challenge_failures.get(claims["jti"], (0, 0.0))[0] + 1
        _challenge_failures[claims["jti"]] = (count, float(claims.get("exp", now + 300)))
        return count


def _app_user(session, p: Principal) -> AppUser:
    user = session.get(AppUser, p.user_id)
    if user is None or not user.active:
        raise Problem(401, "UNAUTHENTICATED", "The user is not active")
    return user


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class MfaLogin(BaseModel):
    challenge: str
    code: str = Field(min_length=6, max_length=8)


@router.get("/me/mfa", tags=["Identity"])
def mfa_status(p: Principal = Depends(enrolment_principal)):
    with uow(p) as s:
        return mfa.status(s, _app_user(s, p))


@router.post("/me/mfa/totp", status_code=201, tags=["Identity"])
def mfa_enrol(p: Principal = Depends(enrolment_principal)):
    with uow(p) as s:
        return mfa.enrol(s, _app_user(s, p))


@router.post("/me/mfa/totp/confirm", tags=["Identity"])
def mfa_confirm(body: CodeIn, request: Request, p: Principal = Depends(enrolment_principal)):
    _throttle(request)
    try:
        with uow(p) as s:
            user = _app_user(s, p)
            factor = mfa.confirm(s, user, body.code)
            result = {"enrolled": True, "confirmedAt": factor.confirmed_at.isoformat()}
            if p.attr("mfa_enrolment"):  # enrolment during sign-in: finish the sign-in
                with system_tx() as ts:
                    tenant = ts.get(Tenant, p.tenant_id)
                result.update(token_response(user, tenant, amr=["pwd", "otp"]))
                http.clear_login_failures(request)
            return result
    except Problem as exc:
        if exc.code == "MFA_CODE_INVALID":
            _count_failure(request, None)
            _audit_failure(p, request, "enrolment")
        raise


def _audit_failure(p: Principal, request: Request, context: str) -> None:
    """MFA_FAILED in its own transaction: the request's transaction is rolled back with the error."""
    with tenant_tx(p.tenant_id, p.user_id, p) as s:
        user = s.get(AppUser, p.user_id)
        if user is not None:
            mfa.record_failure(s, user, context, http._client_ip(request))


@router.delete("/me/mfa/totp", tags=["Identity"])
def mfa_disable(request: Request, body: Optional[CodeIn] = Body(default=None), p: Principal = Depends(current_principal)):
    _throttle(request)
    try:
        with uow(p) as s:
            mfa.ensure_not_locked(s, p.user_id)
            mfa.disable(s, _app_user(s, p), body.code if body else "")
            return {"enrolled": False}
    except Problem as exc:
        if exc.code == "MFA_CODE_INVALID":
            _count_failure(request, None)
            _audit_failure(p, request, "disable")
        raise


@router.post("/auth/mfa", tags=["Identity"])
def mfa_login(body: MfaLogin, request: Request):
    """Second sign-in step: the challenge from POST /v1/auth/token plus the current authenticator code."""
    _throttle(request)
    claims = read_challenge(body.challenge, MFA_CHALLENGE, code="MFA_CHALLENGE_INVALID")
    if _failures(claims["jti"]) >= MAX_CODE_ATTEMPTS:
        raise Problem(401, "MFA_CHALLENGE_EXHAUSTED", "Too many wrong codes for this sign-in; sign in again")
    with system_tx() as s:
        tenant = s.get(Tenant, uuid.UUID(claims["tid"]))
    if tenant is None:
        raise Problem(401, "MFA_CHALLENGE_INVALID", "Unknown organisation")
    with tenant_tx(tenant.id) as s:
        user = s.get(AppUser, uuid.UUID(claims["sub"]))
        if user is not None:
            mfa.ensure_not_locked(s, user.id)  # per-account counter in the database: holds across replicas and fresh challenges
        factor = mfa.confirmed_factor(s, user.id) if user is not None and user.active else None
        ok = factor is not None and mfa.verify(s, factor, body.code)
        if ok:
            mfa.record_success(s, user)
            http.clear_login_failures(request)
            return token_response(user, tenant, amr=["pwd", "otp"])
        if user is not None:
            mfa.record_failure(s, user, "login", http._client_ip(request))  # committed with this transaction
    attempts = _count_failure(request, claims)
    raise Problem(401, "MFA_CODE_INVALID", "The code is not valid or was already used. Enter the current code from your authenticator app.",
                  attemptsLeft=max(MAX_CODE_ATTEMPTS - attempts, 0))


# ---------------------------------------------------------------- §14 OIDC single sign-on
class OidcCallback(BaseModel):
    code: str = Field(min_length=1, max_length=4096)
    state: str = Field(min_length=1, max_length=4096)


def _tenant_by_code(code: str) -> Optional[Tenant]:
    with system_tx() as s:
        return s.execute(select(Tenant).where(Tenant.code == code.upper())).scalar_one_or_none()


@router.get("/auth/oidc/{tenant}", tags=["Identity"])
def oidc_enabled(tenant: str):
    """Public: whether the organisation signs in with its identity provider (the login page shows the SSO button)."""
    found = _tenant_by_code(tenant)
    return {"tenant": tenant.upper(), "enabled": bool(found and oidc.config(found.code))}


@router.get("/auth/oidc/{tenant}/start", tags=["Identity"])
def oidc_start(tenant: str):
    found = _tenant_by_code(tenant)
    if found is None:
        raise Problem(404, "OIDC_NOT_CONFIGURED", f"Single sign-on is not configured for organisation {tenant}")
    return oidc.start(found)


@router.post("/auth/oidc/callback", tags=["Identity"])
def oidc_callback(body: OidcCallback, request: Request):
    _throttle(request)
    state = oidc.read_state(body.state)
    with system_tx() as s:
        tenant = s.get(Tenant, uuid.UUID(state["tid"]))
    if tenant is None:
        raise Problem(401, "OIDC_STATE_INVALID", "Unknown organisation in the sign-in state")
    identity = oidc.exchange(tenant.code, body.code, state)
    with tenant_tx(tenant.id) as s:
        user = s.execute(select(AppUser).where(AppUser.email == identity["email"], AppUser.active.is_(True))).scalar_one_or_none()
        if user is None:
            http.record_login_failure(request)
            raise Problem(403, "OIDC_USER_UNKNOWN", f"{identity['email']} has no active account in {tenant.code}; ask your administrator to create one")
        if mfa.required_for(s, user) and not identity["mfa"]:
            raise Problem(403, "IDP_MFA_REQUIRED", "Your role requires multi-factor authentication, but the identity provider did not report it "
                          "(amr). Sign in with MFA at your identity provider.", rule_ref="MFA")
        audit.record(s, "APP_USER", user.id, "SSO_LOGIN", object_ref=user.email, actor=f"u:{user.email}",
                     after={"issuer": identity["issuer"], "subject": identity["subject"], "amr": identity["amr"]})
        http.clear_login_failures(request)
        return token_response(user, tenant, amr=["sso", *identity["amr"]])
