"""Supplier master changes (MDM-04), invitations and self-registration (F8-01), punch-out (M04).

The ``/v1/public/...`` and punch-out return / simulator endpoints are unauthenticated by design: the invitee has no login
yet and a punch-out cart comes back through the browser from the supplier's site. They find the tenant from the token or
BuyerCookie prefix, run in a tenant-scoped (RLS) transaction, and failures from one client are throttled.
"""
import time
import uuid
from collections import defaultdict, deque
from datetime import date
from typing import Optional
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.pic import views
from app.pic.api.deps import idempotency_key, idempotent, uow
from app.pic.db import system_tx, tenant_tx
from app.pic.models import Tenant
from app.pic.platform import http
from app.pic.platform.auth import READ, Principal, require, require_any
from app.pic.platform.errors import Problem
from app.pic.services import invitations, master_changes, punchout
from app.pic.services.common import supplier_ref

router = APIRouter(prefix="/v1")


class CamelModel(BaseModel):
    """Accepts camelCase (as documented) and snake_case field names."""
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)


# ---------------------------------------------------------------- public-endpoint throttling
PUBLIC_WINDOW_SECONDS = 600
PUBLIC_MAX_FAILURES = 20
_public_failures: dict[str, deque] = defaultdict(deque)


def _throttle(request: Request) -> None:
    window = _public_failures[http._client_ip(request)]
    now = time.monotonic()
    while window and now - window[0] > PUBLIC_WINDOW_SECONDS:
        window.popleft()
    if len(window) >= PUBLIC_MAX_FAILURES:
        raise Problem(429, "TOO_MANY_ATTEMPTS", "Too many invalid links from this address. Wait 10 minutes and try again.")


def _failed(request: Request) -> None:
    _public_failures[http._client_ip(request)].append(time.monotonic())


def _tenant(code: Optional[str]) -> Optional[Tenant]:
    if not code:
        return None
    with system_tx() as s:
        return s.execute(select(Tenant).where(Tenant.code == code)).scalar_one_or_none()


def _gateway(tenant: Tenant, name: str) -> Principal:
    """Actor for unauthenticated partner traffic (audit shows agent:<name>)."""
    return Principal(user_id=uuid.UUID(int=0), tenant_id=tenant.id, tenant_code=tenant.code, email=f"{name.lower()}@gateway.pic",
                     name=name, roles=[], scopes=set(), agent_code=name)


async def _form(request: Request) -> dict:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        return {k: v for k, v in form.items() if isinstance(v, str)}
    body = await request.body()
    if len(body) > 2_000_000:
        raise Problem(413, "PAYLOAD_TOO_LARGE", "The posted document is larger than 2 MB")
    text = body.decode("utf-8", errors="replace")
    if "xml" in content_type:
        return {"cxml-urlencoded": text}
    return {k: v[-1] for k, v in parse_qs(text, keep_blank_values=True).items()}


def _html_error(exc: Problem) -> HTMLResponse:
    import html as html_lib
    return HTMLResponse(status_code=exc.status, content=(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Punch-out</title></head>"
        f"<body style='font-family:system-ui,sans-serif;margin:24px'><h1 style='font-size:18px'>{html_lib.escape(exc.code)}</h1>"
        f"<p>{html_lib.escape(exc.detail)}</p></body></html>"))


# ---------------------------------------------------------------- MDM-04 supplier master changes
class MasterChangeIn(CamelModel):
    field_group: str = Field(pattern="^(TAX|ADDRESS|CONTACT)$")
    values: dict
    reason: str = Field(min_length=3, max_length=2000)


@router.post("/suppliers/{code}/master-changes", status_code=201, tags=["F8 Supplier"])
def request_master_change(code: str, body: MasterChangeIn, p: Principal = Depends(require_any("supplier:manage", "supplier:portal")),
                          key: Optional[str] = Depends(idempotency_key)):
    """MDM-04: tax-ID (GSTIN/PAN), address or contact change. Dual approval (rule SUPPLIER-MASTER-CHANGE), never the requester."""
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/suppliers/{code}/master-changes", key, body)
        if idem.replay:
            return idem.replay
        supplier = supplier_ref(s, code)
        change = master_changes.request_change(s, supplier, field_group=body.field_group, values=body.values, reason=body.reason)
        return idem.store(master_changes.view(s, change, supplier.code), 201)


@router.get("/portal/profile", tags=["F8 Supplier"])
def portal_profile(p: Principal = Depends(require("supplier:portal"))):
    """The signed-in supplier user's own company master data (masked), for the portal's MDM-04 change requests."""
    if not p.supplier_id:
        raise Problem(403, "FORBIDDEN", "Only supplier users have a portal profile", rule_ref="SUPPLIER_SCOPE")
    with uow(p) as s:
        supplier = supplier_ref(s, str(p.supplier_id))
        return {"code": supplier.code, "legal_name": supplier.legal_name, "gstin_masked": supplier.gstin_masked,
                "state_code": supplier.state_code, "contact_email": supplier.contact_email, "address": supplier.address or {},
                "punchout": None, "status": supplier.status}


@router.get("/suppliers/{code}/master-changes", tags=["F8 Supplier"])
def list_master_changes(code: str, p: Principal = Depends(require_any(READ, "supplier:portal"))):
    with uow(p) as s:
        return master_changes.list_for(s, supplier_ref(s, code))


# ---------------------------------------------------------------- F8-01 invitations (supplier manager)
class InvitationIn(CamelModel):
    email: str = Field(min_length=5, max_length=200)
    legal_name: str = Field(min_length=3, max_length=200)
    categories: list[str] = Field(min_length=1, max_length=20)


@router.post("/supplier-invitations", status_code=201, tags=["F8 Supplier"])
def invite_supplier(body: InvitationIn, p: Principal = Depends(require("supplier:manage"))):
    """The clear token and link are in this response only (not replayable: it is not stored for idempotency)."""
    with uow(p) as s:
        return invitations.create(s, email=body.email, legal_name=body.legal_name, categories=body.categories)


@router.get("/supplier-invitations", tags=["F8 Supplier"])
def list_invitations(p: Principal = Depends(require("supplier:manage"))):
    with uow(p) as s:
        return invitations.list_all(s)


class RevokeIn(BaseModel):
    reason: Optional[str] = None


@router.post("/supplier-invitations/{invitation_id}/revoke", tags=["F8 Supplier"])
def revoke_invitation(invitation_id: uuid.UUID, body: RevokeIn = RevokeIn(), p: Principal = Depends(require("supplier:manage"))):
    with uow(p) as s:
        return invitations.revoke(s, invitation_id, body.reason)


# ---------------------------------------------------------------- F8-01 self-registration (public)
def _invitation_tenant(request: Request, token: str) -> Tenant:
    _throttle(request)
    tenant = _tenant(invitations.tenant_code_of(token))
    if tenant is None:
        _failed(request)
        raise Problem(404, "INVITATION_NOT_FOUND", "This registration link is not valid")
    return tenant


@router.get("/public/invitations/{token}", tags=["F8 Supplier · public"])
def public_invitation(token: str, request: Request):
    tenant = _invitation_tenant(request, token)
    try:
        with tenant_tx(tenant.id) as s:
            invitation = invitations.find(s, token)
            invitations.check_usable(invitation)
            return invitations.public_view(invitation, tenant)
    except Problem as exc:
        if exc.status in (404, 410):
            _failed(request)
        raise


class AddressIn(CamelModel):
    line1: str = Field(min_length=1, max_length=200)
    line2: Optional[str] = Field(default=None, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    state_code: Optional[str] = Field(default=None, max_length=2)
    pin: str = Field(min_length=6, max_length=6)
    country: str = Field(default="IN", max_length=2)


class RegistrationIn(CamelModel):
    legal_name: str = Field(min_length=3, max_length=200)
    gstin: str = Field(min_length=15, max_length=15)
    pan: str = Field(min_length=10, max_length=10)
    state_code: str = Field(min_length=2, max_length=2)
    address: AddressIn
    contact_name: str = Field(min_length=2, max_length=200)
    email: str = Field(min_length=5, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=20)
    password: str = Field(min_length=1, max_length=128)


@router.post("/public/invitations/{token}/register", status_code=201, tags=["F8 Supplier · public"])
def public_register(token: str, body: RegistrationIn, request: Request):
    tenant = _invitation_tenant(request, token)
    try:
        with tenant_tx(tenant.id) as s:
            invitation = invitations.find(s, token, lock=True)
            return invitations.register(
                s, invitation, tenant, legal_name=body.legal_name, gstin=body.gstin, pan=body.pan, state_code=body.state_code,
                address=body.address.model_dump(), contact_name=body.contact_name, email=body.email, password=body.password,
                phone=body.phone)
    except Problem as exc:
        if exc.status in (404, 410):
            _failed(request)
        raise


# ---------------------------------------------------------------- M04 punch-out: configuration and sessions
class PunchoutConfigIn(CamelModel):
    protocol: str = Field(pattern="^(CXML|OCI)$")
    url: str = Field(min_length=1, max_length=400)
    identity: str = Field(min_length=1, max_length=100)
    shared_secret: Optional[str] = Field(default=None, max_length=200)


@router.put("/suppliers/{code}/punchout", tags=["F2 Requisition · punch-out"])
def configure_punchout(code: str, body: PunchoutConfigIn, p: Principal = Depends(require("supplier:manage"))):
    """Store the supplier's punch-out endpoint; the shared secret is encrypted and never returned."""
    with uow(p) as s:
        return punchout.configure(s, supplier_ref(s, code), protocol=body.protocol, url=body.url, identity=body.identity,
                                  shared_secret=body.shared_secret)


@router.get("/punchout/suppliers", tags=["F2 Requisition · punch-out"])
def punchout_suppliers(p: Principal = Depends(require("req:create"))):
    with uow(p) as s:
        return punchout.configured_suppliers(s)


class SessionIn(CamelModel):
    supplier: str


@router.post("/punchout/sessions", status_code=201, tags=["F2 Requisition · punch-out"])
def start_punchout(body: SessionIn, p: Principal = Depends(require("req:create"))):
    """Not replayable by Idempotency-Key: an OCI response carries the supplier login fields for the browser form."""
    with uow(p) as s:
        return punchout.start(s, supplier_ref(s, body.supplier))


@router.get("/punchout/sessions/{cookie}", tags=["F2 Requisition · punch-out"])
def get_punchout(cookie: str, p: Principal = Depends(require("req:create"))):
    with uow(p) as s:
        return punchout.view(s, punchout.get(s, cookie))


class ConvertIn(CamelModel):
    requisition: Optional[str] = None
    plant: Optional[str] = None
    purpose_code: Optional[str] = Field(default=None, max_length=30)
    purpose_text: Optional[str] = None
    need_date: Optional[date] = None
    purchase_type: Optional[str] = Field(default=None, pattern="^(NON_STOCK|SERVICE|EXPENSE|ASSET)$")
    account_assignment_type: Optional[str] = None
    account_assignment_code: Optional[str] = None
    material_group: Optional[str] = Field(default=None, max_length=30)
    category: Optional[str] = Field(default=None, max_length=40)


@router.post("/punchout/sessions/{cookie}/convert", tags=["F2 Requisition · punch-out"])
def convert_punchout(cookie: str, body: ConvertIn = ConvertIn(), p: Principal = Depends(require("req:create")),
                     key: Optional[str] = Depends(idempotency_key)):
    """Returned cart → CATALOGUE requisition lines on a new or an existing draft requisition."""
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/punchout/sessions/{cookie}/convert", key, body)
        if idem.replay:
            return idem.replay
        ps = punchout.get(s, cookie)
        pr = punchout.convert(s, ps, requisition=body.requisition, plant=body.plant, purpose_code=body.purpose_code,
                              purpose_text=body.purpose_text, need_date=body.need_date, purchase_type=body.purchase_type,
                              account_assignment_type=body.account_assignment_type, account_assignment_code=body.account_assignment_code,
                              material_group=body.material_group, category=body.category)
        return idem.store({**views.requisition(s, pr), "punchoutSession": punchout.view(s, ps)})


# ---------------------------------------------------------------- M04 punch-out: browser return (public)
def _receive(form: dict, query_cookie: Optional[str]) -> dict:
    cookie, protocol, items, document = punchout.decode_return(form, query_cookie)
    tenant = _tenant(punchout.tenant_code_of(cookie or ""))
    if tenant is None:
        raise Problem(404, "PUNCHOUT_SESSION_NOT_FOUND", "No punch-out session matches this BuyerCookie")
    with tenant_tx(tenant.id) as s:
        s.info["principal"] = _gateway(tenant, "PUNCHOUT_RETURN")
        ps = punchout.receive(s, cookie, protocol, items, document)
        result = {"status": ps.status, "cookie": ps.buyer_cookie, "number": punchout._number_of(ps), "items": len(ps.cart or [])}
    if result["status"] == "EXPIRED":  # recorded as EXPIRED (committed above), then refused
        raise Problem(410, "PUNCHOUT_SESSION_EXPIRED", "The punch-out session expired before the cart came back; start again",
                      rule_ref="M04", cookie=result["cookie"])
    return result


@router.post("/punchout/return", tags=["F2 Requisition · punch-out"])
async def punchout_return(request: Request):
    """Cart from the supplier: cXML PunchOutOrderMessage (cxml-urlencoded / cxml-base64) or OCI NEW_ITEM-* fields."""
    form = await _form(request)
    return await run_in_threadpool(_receive, form, request.query_params.get("cookie"))


# ---------------------------------------------------------------- built-in test supplier (public, url == "builtin")
def _simulator_tenant(cookie: Optional[str]) -> Tenant:
    tenant = _tenant(punchout.tenant_code_of(cookie or ""))
    if tenant is None:
        raise Problem(404, "PUNCHOUT_SESSION_NOT_FOUND", "Unknown punch-out session")
    return tenant


def _simulate_setup(document: str) -> str:
    root = punchout.parse_xml(document)
    cookie = punchout._text(root, "./Request/PunchOutSetupRequest/BuyerCookie")
    with tenant_tx(_simulator_tenant(cookie).id) as s:
        return punchout.simulator_setup(s, document)


@router.post("/punchout/simulator/setup", tags=["F2 Requisition · punch-out"])
async def simulator_setup(request: Request):
    body = (await request.body())[:punchout.MAX_DOCUMENT + 1].decode("utf-8", errors="replace")
    answer = await run_in_threadpool(_simulate_setup, body)
    return Response(content=answer, media_type="text/xml; charset=utf-8")


def _cookie_from(form: dict, query_cookie: Optional[str]) -> Optional[str]:
    if query_cookie or form.get("cookie"):
        return query_cookie or form.get("cookie")
    hook = form.get("HOOK_URL") or ""
    values = parse_qs(hook.split("?", 1)[1]) if "?" in hook else {}
    return (values.get("cookie") or [None])[0]


def _simulate_page(kind: str, form: dict, query_cookie: Optional[str]) -> str:
    cookie = _cookie_from(form, query_cookie)
    with tenant_tx(_simulator_tenant(cookie).id) as s:
        if kind == "catalogue":
            return punchout.simulator_catalogue(s, cookie, form)
        return punchout.simulator_checkout(s, {**form, "cookie": cookie})


@router.api_route("/punchout/simulator/catalogue", methods=["GET", "POST"], tags=["F2 Requisition · punch-out"],
                  response_class=HTMLResponse)
async def simulator_catalogue(request: Request):
    form = await _form(request) if request.method == "POST" else {}
    try:
        return HTMLResponse(await run_in_threadpool(_simulate_page, "catalogue", form, request.query_params.get("cookie")))
    except Problem as exc:
        return _html_error(exc)


@router.post("/punchout/simulator/checkout", tags=["F2 Requisition · punch-out"], response_class=HTMLResponse)
async def simulator_checkout(request: Request):
    form = await _form(request)
    try:
        return HTMLResponse(await run_in_threadpool(_simulate_page, "checkout", form, request.query_params.get("cookie")))
    except Problem as exc:
        return _html_error(exc)


# ---------------------------------------------------------------- F8-03 licensed sanctions list (tenant admin)
@router.post("/admin/sanctions/sync", tags=["F8 Supplier"])
def sync_sanctions(p: Principal = Depends(require("admin:integration"))):
    """Download the configured provider's list into sanction_entry, replacing only that provider's entries."""
    from app.pic.services import supplier as supplier_svc

    with uow(p) as s:
        return supplier_svc.sync_sanctions(s)
