"""F1 MRP, F2 requisitions, F9 material governance, F8 supplier onboarding."""
import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select

from app.pic import views
from app.pic.api.deps import idempotency_key, idempotent, uow
from app.pic.models import (
    BankChangeRequest, Certificate, Material, MaterialRequest, MrpException, MrpRun, PlannedOrder, PrLine, Qualification, Requisition,
    Scorecard, Supplier, SupplierBankAccount, SupplierCategoryStatus, Task, TwinSnapshot,
)
from app.pic.platform import workflow
from app.pic.platform.auth import READ, Principal, require, require_any
from app.pic.platform.errors import Problem, not_found
from app.pic.platform.serialize import row, rows
from app.pic.services import catalogue, guided_buying, mandatory, mdm, planning, request_templates, requisition, supplier
from app.pic.services.common import by_ref, material_by_number, supplier_ref

router = APIRouter(prefix="/v1")


# ---------------------------------------------------------------- F1 MRP
class MrpRunIn(BaseModel):
    plant: str
    mode: str = "NET_CHANGE"
    materials: Optional[list[str]] = None
    run_date: Optional[date] = None


@router.post("/mrp/runs", status_code=201, tags=["F1 MRP"])
def start_mrp_run(body: MrpRunIn, p: Principal = Depends(require("mrp:run")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/mrp/runs", key, body)
        if idem.replay:
            return idem.replay
        run = planning.run(s, plant=body.plant, mode=body.mode, materials=body.materials, run_date=body.run_date)
        return idem.store(views.mrp_run(s, run), 201)


def _run(s, ref: str) -> MrpRun:
    run = by_ref(s, MrpRun, ref)
    planning.ensure_readable(s, run.plant, "MRP run", ref)  # SEC-AZ: plant scope on planning reads
    return run


def _planned_order(s, ref: str, lock: bool = False) -> PlannedOrder:
    order = by_ref(s, PlannedOrder, ref, lock=lock)
    planning.ensure_readable(s, order.plant, "Planned order", ref)
    return order


@router.get("/mrp/runs/{ref}", tags=["F1 MRP"])
def get_mrp_run(ref: str, detail: str = Query(default="auto", pattern="^(auto|full|summary)$"), p: Principal = Depends(require(READ))):
    """``detail=summary`` (the default for large runs) returns the header, counts and the URLs of the paged detail reads."""
    with uow(p) as s:
        return views.mrp_run(s, _run(s, ref), detail)


@router.get("/mrp/runs/{ref}/exceptions", tags=["F1 MRP"])
def mrp_exceptions(ref: str, limit: Optional[int] = Query(default=None, ge=1, le=500), offset: int = Query(default=0, ge=0),
                   status: Optional[str] = Query(default=None, pattern="^(OPEN|CLOSED|SUPERSEDED)$"), p: Principal = Depends(require(READ))):
    """Exceptions by value at risk. Without ``limit`` the whole list; with it a page ``{items, total, nextOffset}``. ``status`` filters
    OPEN, CLOSED (resolved by the controller) or SUPERSEDED (a later run of the material replaced it)."""
    with uow(p) as s:
        run = _run(s, ref)
        where = [MrpException.mrp_run_id == run.id] + ([MrpException.status == status] if status else [])
        query = select(MrpException).where(*where).order_by(MrpException.value_at_risk_minor.desc(), MrpException.id)
        if limit is None:
            return rows(s.execute(query).scalars())
        total = s.execute(select(func.count()).select_from(MrpException).where(*where)).scalar_one()
        items = rows(s.execute(query.limit(limit).offset(offset)).scalars())
        return {"items": items, "total": total, "nextOffset": offset + limit if offset + limit < total else None}


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/mrp/exceptions/{exception_id}/close", tags=["F1 MRP"])
def close_mrp_exception(exception_id: uuid.UUID, body: ReasonIn, p: Principal = Depends(require("mrp:plan")),
                        key: Optional[str] = Depends(idempotency_key)):
    """Resolve an exception message with a reason (audited); exceptions about a planned order also close when it is converted,
    cancelled or unfirmed, and every open exception of a material closes as SUPERSEDED when a later live run plans it again."""
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/mrp/exceptions/{exception_id}/close", key, body)
        if idem.replay:
            return idem.replay
        exc = s.get(MrpException, exception_id, with_for_update=True)
        if exc is None:
            raise not_found("MRP exception", exception_id)
        planning.ensure_readable(s, exc.plant or s.get(MrpRun, exc.mrp_run_id).plant, "MRP exception", str(exception_id))
        return idem.store(row(planning.close_exception(s, exc, body.reason)))


@router.post("/planned-orders/{ref}/firm", tags=["F1 MRP"])
def firm_planned_order(ref: str, p: Principal = Depends(require("mrp:plan"))):
    with uow(p) as s:
        return row(planning.firm(s, _planned_order(s, ref, lock=True)))


@router.post("/planned-orders/{ref}/cancel", tags=["F1 MRP"])
def cancel_planned_order(ref: str, body: ReasonIn, p: Principal = Depends(require("mrp:plan")), key: Optional[str] = Depends(idempotency_key)):
    """Cancel a CREATED or FIRMED planned order (e.g. on a CANCEL exception message); its open exceptions close with the reason."""
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/planned-orders/{ref}/cancel", key, body)
        if idem.replay:
            return idem.replay
        return idem.store(row(planning.cancel(s, _planned_order(s, ref, lock=True), body.reason)))


@router.post("/planned-orders/{ref}/unfirm", tags=["F1 MRP"])
def unfirm_planned_order(ref: str, body: ReasonIn, p: Principal = Depends(require("mrp:plan")), key: Optional[str] = Depends(idempotency_key)):
    """Take the firming off a FIRMED planned order (back to CREATED: the next run may change or replace it)."""
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/planned-orders/{ref}/unfirm", key, body)
        if idem.replay:
            return idem.replay
        return idem.store(row(planning.unfirm(s, _planned_order(s, ref, lock=True), body.reason)))


@router.post("/planned-orders/{ref}/convert", tags=["F1 MRP"])
def convert_planned_order(ref: str, p: Principal = Depends(require("mrp:plan")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/planned-orders/{ref}/convert", key, {})
        if idem.replay:
            return idem.replay
        pr = planning.convert(s, _planned_order(s, ref, lock=True))
        return idem.store(views.requisition(s, pr))


# ---------------------------------------------------------------- F2 guided buying and requisitions
@router.get("/guided-buying/search", tags=["F2 Requisition"])
def guided_search(q: str, plant: Optional[str] = None, p: Principal = Depends(require("req:create"))):
    with uow(p) as s:
        result = requisition.search(s, q, plant)
        agent = guided_buying.assist_search(s, q, plant, result)  # Guided Buying Agent (AG-03), when it may act
        return {**result, "agent": agent} if agent else result


class QuoteRefIn(BaseModel):
    """One supplier quote for the quote policy (no quote-document store yet: supplier, quote reference and date)."""
    supplier: str = Field(min_length=1, max_length=80)
    reference: str = Field(min_length=1, max_length=80)
    date: date


class SowIn(BaseModel):
    """Structured statement of work of a category SOW form (BP M04 request templates). Kept on the line (pr_line.sow) and carried to the
    sourcing event line and the PO line; the line description stays the short text."""
    template: Optional[str] = Field(default=None, max_length=40)
    title: Optional[str] = Field(default=None, max_length=200)
    text: Optional[str] = Field(default=None, max_length=requisition.SOW_TEXT_LIMIT)
    attributes: dict = {}


class PrLineIn(BaseModel):
    item_type: str = Field(pattern="^(MATERIAL|FREE_TEXT|CATALOGUE|CONTRACT|SERVICE)$")
    purchase_type: str
    description: Optional[str] = None
    sow: Optional[SowIn] = None

    @field_validator("description")
    @classmethod
    def _short_text(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and len(value.strip()) > requisition.DESCRIPTION_LIMIT:
            raise ValueError(requisition.DESCRIPTION_MESSAGE.format(n=len(value.strip())))
        return value
    material: Optional[str] = None
    catalogue_item_id: Optional[str] = None
    contract_line_id: Optional[str] = None
    material_group: Optional[str] = None
    category: Optional[str] = None
    qty: Decimal = Field(gt=0)
    uom: Optional[str] = None
    price_est_minor: Optional[int] = Field(default=None, ge=0)
    account_assignment_type: Optional[str] = None
    account_assignment_code: Optional[str] = None
    need_date: date
    storage_location: Optional[str] = None
    quotes_attached: int = Field(default=0, ge=0)
    quotes: list[QuoteRefIn] = []
    reusable: bool = False
    mpn: Optional[str] = None
    attributes: Optional[dict] = None
    guided_run: Optional[str] = Field(default=None, max_length=80, description="aiRef of the guided-buying search this line came from")
    template: Optional[str] = Field(default=None, max_length=40)   # BP M04 request template code (GET /v1/request-templates)


class RequisitionIn(BaseModel):
    origin: str = Field(pattern="^(MANUAL|PROJECT|CATALOGUE)$")
    purpose_code: Optional[str] = None
    purpose_text: Optional[str] = None
    plant: str
    company_code: str = "1000"
    purchasing_org: Optional[str] = Field(default=None, max_length=10)     # checked against the organisation master (ADM-01)
    purchasing_group: Optional[str] = Field(default=None, max_length=10)
    template: Optional[str] = Field(default=None, max_length=40)   # default template for lines that name none
    lines: list[PrLineIn] = Field(min_length=1)


@router.post("/requisitions", status_code=201, tags=["F2 Requisition"])
def create_requisition(body: RequisitionIn, p: Principal = Depends(require("req:create")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/requisitions", key, body)
        if idem.replay:
            return idem.replay
        pr = requisition.create(s, origin=body.origin, purpose_code=body.purpose_code, purpose_text=body.purpose_text, plant=body.plant,
                                company_code=body.company_code, purchasing_org=body.purchasing_org, purchasing_group=body.purchasing_group,
                                lines=[{**l.model_dump(), "template": l.template or body.template} for l in body.lines])
        return idem.store(views.requisition(s, pr), 201)


@router.get("/request-templates", tags=["F2 Requisition"])
def list_request_templates(p: Principal = Depends(require("req:create"))):
    """BP M04 template picker: services, IT, marketing and facilities templates (rule REQUEST-TEMPLATES) with the requester's default cost object."""
    with uow(p) as s:
        return request_templates.listing(s, p)


class SubmitIn(BaseModel):
    justification: Optional[str] = None
    request_sourcing: bool = False


@router.post("/requisitions/{ref}/submit", tags=["F2 Requisition"])
def submit_requisition(ref: str, body: SubmitIn = SubmitIn(), p: Principal = Depends(require("req:create"))):
    with uow(p) as s:
        pr = by_ref(s, Requisition, ref, lock=True)
        if pr.requester_id != p.user_id:
            raise Problem(403, "FORBIDDEN", "Only the requester can submit this requisition")
        requisition.submit(s, pr, body.justification, body.request_sourcing)
        return views.requisition(s, pr)


class LineChange(BaseModel):
    qty: Optional[Decimal] = Field(default=None, gt=0)
    price_est_minor: Optional[int] = Field(default=None, ge=0)
    account_assignment_type: Optional[str] = None
    account_assignment_code: Optional[str] = None
    need_date: Optional[date] = None
    description: Optional[str] = Field(default=None, min_length=1, max_length=200)
    justification: Optional[str] = None  # soft budget stop when a change after approval re-books the budget


@router.patch("/requisitions/{ref}/lines/{line_no}", tags=["F2 Requisition"])
def change_requisition_line(ref: str, line_no: int, body: LineChange, p: Principal = Depends(require("req:create"))):
    """The requester changes a DRAFT / RETURNED requisition; once APPROVED the requester or a buyer (re-approval rules apply)."""
    with uow(p) as s:
        pr = by_ref(s, Requisition, ref, lock=True)
        return requisition.change_line(s, pr, line_no, body.model_dump(exclude_none=True))


class CancelIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@router.post("/requisitions/{ref}/cancel", tags=["F2 Requisition"])
def cancel_requisition(ref: str, body: CancelIn, p: Principal = Depends(require("req:create"))):
    """Withdraw a requisition: the requester (DRAFT, RETURNED, IN_APPROVAL, APPROVED not yet ordered) or a buyer (APPROVED)."""
    with uow(p) as s:
        pr = by_ref(s, Requisition, ref, lock=True)
        requisition.cancel(s, pr, body.reason)
        return views.requisition(s, pr)


@router.get("/requisitions/{ref}", tags=["F2 Requisition"])
def get_requisition(ref: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return views.requisition(s, by_ref(s, Requisition, ref))


@router.get("/buyer-workbench", tags=["F2 Requisition"])
def buyer_workbench(origin: Optional[str] = None, p: Principal = Depends(require("req:buyer"))):
    with uow(p) as s:
        return requisition.buyer_queue(s, origin)


# ---------------------------------------------------------------- M04 hosted catalogue maintenance (flow fixes A11)
CATALOGUE_SCOPE = require_any("sourcing:manage", "contract:manage")


class CatalogueItemIn(BaseModel):
    supplier: str = Field(min_length=1, max_length=30)
    supplier_part_no: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=1, max_length=200)
    material_group: str = Field(min_length=1, max_length=30)
    category: Optional[str] = Field(default=None, max_length=40)
    uom: str = Field(min_length=1, max_length=5)
    price_minor: int = Field(gt=0)
    currency: str = Field(default="INR", pattern="^[A-Za-z]{3}$")
    gst_rate: Decimal = Decimal(18)
    hsn_code: Optional[str] = Field(default=None, max_length=10)
    material: Optional[str] = Field(default=None, max_length=30)
    contract: Optional[str] = Field(default=None, max_length=30)
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    lead_time_days: Optional[int] = Field(default=None, ge=0, le=730)


class CatalogueChangeIn(BaseModel):
    changes: dict = Field(min_length=1)
    reason: str = Field(min_length=3, max_length=1000)


@router.get("/catalogue-items", tags=["F2 Requisition"])
def list_catalogue_items(supplier: Optional[str] = None, active: Optional[bool] = None, q: Optional[str] = Query(default=None, max_length=100),
                         category: Optional[str] = None, limit: int = Query(default=200, ge=1, le=500), p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return catalogue.listing(s, supplier=supplier, active=active, q=q, category=category, limit=limit)


@router.get("/catalogue-items/{item_id}", tags=["F2 Requisition"])
def get_catalogue_item(item_id: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return catalogue.view(s, catalogue.get(s, item_id))


@router.post("/catalogue-items", status_code=201, tags=["F2 Requisition"])
def create_catalogue_item(body: CatalogueItemIn, p: Principal = Depends(CATALOGUE_SCOPE), key: Optional[str] = Depends(idempotency_key)):
    """A hosted catalogue item: supplier part, price and its validity, optionally the material and the contract that fixes the price."""
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/catalogue-items", key, body)
        if idem.replay:
            return idem.replay
        data = body.model_dump()
        item = catalogue.create(s, supplier=data.pop("supplier"), supplier_part_no=data.pop("supplier_part_no"),
                                **{k: v for k, v in data.items() if v is not None or k in ("valid_from", "valid_to")})
        return idem.store(catalogue.view(s, item), 201)


@router.patch("/catalogue-items/{item_id}", tags=["F2 Requisition"])
def change_catalogue_item(item_id: str, body: CatalogueChangeIn, p: Principal = Depends(CATALOGUE_SCOPE), key: Optional[str] = Depends(idempotency_key)):
    """Change price, validity, texts, tax data, lead time or the material / contract link (audited before / after, with the reason)."""
    with uow(p) as s:
        idem = idempotent(s, f"PATCH /v1/catalogue-items/{item_id}", key, body)
        if idem.replay:
            return idem.replay
        item = catalogue.get(s, item_id)
        s.refresh(item, with_for_update=True)
        return idem.store(catalogue.view(s, catalogue.update(s, item, body.changes, body.reason)))


@router.post("/catalogue-items/{item_id}/deactivate", tags=["F2 Requisition"])
def deactivate_catalogue_item(item_id: str, body: ReasonIn, p: Principal = Depends(CATALOGUE_SCOPE)):
    with uow(p) as s:
        item = catalogue.get(s, item_id)
        s.refresh(item, with_for_update=True)
        return catalogue.view(s, catalogue.set_active(s, item, False, body.reason))


@router.post("/catalogue-items/{item_id}/reactivate", tags=["F2 Requisition"])
def reactivate_catalogue_item(item_id: str, body: ReasonIn, p: Principal = Depends(CATALOGUE_SCOPE)):
    with uow(p) as s:
        item = catalogue.get(s, item_id)
        s.refresh(item, with_for_update=True)
        return catalogue.view(s, catalogue.set_active(s, item, True, body.reason))


# ---------------------------------------------------------------- F9 material governance
class MaterialRequestIn(BaseModel):
    description: str
    type: str = "NON_STOCK"
    material_group: str
    category: str
    base_uom: str
    valuation_class: Optional[str] = None
    hsn_code: Optional[str] = None
    mpn: Optional[str] = None
    attributes: Optional[dict] = None
    # Planning mode of the new material (STOCK only); omitted = the tenant default of rule MATERIAL-DEFAULTS (stock: PD)
    mrp_type: Optional[str] = Field(default=None, pattern="^(PD|PW|PM|VB|KB|ND)$")


@router.post("/materials/requests", status_code=201, tags=["F9 MDM"])
def new_material_request(body: MaterialRequestIn, p: Principal = Depends(require("req:create"))):
    with uow(p) as s:
        request = mdm.create_request(s, **body.model_dump())
        return views.material_request(s, request)


@router.post("/requisitions/{ref}/lines/{line_no}/promote-material", status_code=201, tags=["F9 MDM"])
def promote_free_text(ref: str, line_no: int, body: MaterialRequestIn, p: Principal = Depends(require("req:create"))):
    with uow(p) as s:
        pr = by_ref(s, Requisition, ref, lock=True)
        line = s.execute(select(PrLine).where(PrLine.requisition_id == pr.id, PrLine.line_no == line_no).with_for_update()).scalar_one_or_none()
        if line is None:
            raise not_found("Requisition line", f"{pr.number}/{line_no}")
        return views.material_request(s, mdm.promote_line(s, pr, line, **body.model_dump()))


class OverrideIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@router.post("/materials/requests/{ref}/override", tags=["F9 MDM"])
def override_duplicate(ref: str, body: OverrideIn, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return views.material_request(s, mdm.steward_override(s, by_ref(s, MaterialRequest, ref, lock=True), body.reason))


@router.post("/materials/requests/{ref}/withdraw", tags=["F9 MDM"])
def withdraw_material_request(ref: str, body: OverrideIn, p: Principal = Depends(require("req:create")),
                              key: Optional[str] = Depends(idempotency_key)):
    """The requester withdraws an open request (also one blocked as a duplicate); steward tasks are cancelled and the process ends."""
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/materials/requests/{ref}/withdraw", key, body)
        if idem.replay:
            return idem.replay
        return idem.store(views.material_request(s, mdm.withdraw(s, by_ref(s, MaterialRequest, ref, lock=True), body.reason)))


class MergeIn(BaseModel):
    material: str


@router.post("/materials/requests/{ref}/merge", tags=["F9 MDM"])
def merge_request(ref: str, body: MergeIn, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return views.material_request(s, mdm.merge_into_existing(s, by_ref(s, MaterialRequest, ref, lock=True), material_by_number(s, body.material)))


class StewardDecision(BaseModel):
    decision: str = Field(pattern="^(APPROVE|REJECT)$")
    comment: Optional[str] = None


@router.post("/materials/requests/{ref}/decision", tags=["F9 MDM"])
def steward_decision(ref: str, body: StewardDecision, p: Principal = Depends(require(READ))):
    """Completes the caller's open steward task for their domain."""
    with uow(p) as s:
        request = by_ref(s, MaterialRequest, ref)
        tasks = [t for t in workflow.open_tasks_for(s, p) if t.object_id == request.id and t.kind == "MDM_STEWARD"]
        if not tasks:
            raise Problem(403, "NOT_YOUR_TASK", "You have no open steward task on this request")
        workflow.complete(s, tasks[0].id, body.decision, body.comment)
        return views.material_request(s, request)


@router.get("/materials/requests/{ref}", tags=["F9 MDM"])
def get_material_request(ref: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return views.material_request(s, by_ref(s, MaterialRequest, ref))


# ---------------------------------------------------------------- F8 supplier onboarding and SLM
class SupplierIn(BaseModel):
    code: Optional[str] = None
    legal_name: str
    gstin: str = Field(min_length=15, max_length=15)
    pan: str = Field(min_length=10, max_length=10)
    state_code: str
    contact_email: str
    categories: list[str]
    # Net days (N60 or 60), optionally after an early-payment discount (2/10 N45).
    payment_terms: str = Field(default="N60", pattern=supplier.PAYMENT_TERMS_PATTERN)
    incoterms: Optional[str] = None
    segment: Optional[str] = None


@router.post("/suppliers", status_code=201, tags=["F8 Supplier"])
def register_supplier(body: SupplierIn, p: Principal = Depends(require("supplier:manage"))):
    with uow(p) as s:
        data = body.model_dump()
        mandatory.check(s, "SUPPLIER_REGISTER", data, [])  # TD §6 / P14 rule MANDATORY-FIELDS (SUPPLIER_REGISTER)
        return row(supplier.register(s, **data))


IFSC_PATTERN = r"^[A-Z]{4}0[A-Z0-9]{6}$"


class CertificateIn(BaseModel):
    type: str = Field(min_length=2, max_length=40)
    number: str = Field(min_length=2, max_length=60)
    issued_on: date
    expires_on: date
    mandatory_for: list[str] = []  # ignored: the categories a certificate is mandatory for come from SUPPLIER-QUAL


class ProfileIn(BaseModel):
    """F8-02: bank details (only while onboarding runs) and/or certificates (any time; a renewal is a new certificate)."""
    bank_account: Optional[str] = Field(default=None, pattern=r"^[0-9]{9,18}$")
    ifsc: Optional[str] = Field(default=None, pattern=IFSC_PATTERN)
    holder_name: Optional[str] = Field(default=None, min_length=3, max_length=200)
    certificates: list[CertificateIn] = []


@router.get("/suppliers/{code}/profile", tags=["F8 Supplier"])
def get_profile(code: str, p: Principal = Depends(require_any(READ, "supplier:portal"))):
    """F8-02 profile state for the portal: certificates, masked bank accounts, pending bank changes and whether bank details
    can still be given through the profile (only while onboarding runs)."""
    with uow(p) as s:
        sup = supplier_ref(s, code)
        if "SUPPLIER_USER" in p.roles and sup.id != p.supplier_id:
            raise not_found("Supplier", code)
        onboarding = workflow.find(s, "SUPPLIER", sup.id, supplier.PROCESS)
        pending = s.execute(select(BankChangeRequest).where(BankChangeRequest.supplier_id == sup.id, BankChangeRequest.status.in_(
            ("PENDING_CALLBACK", "PENDING_APPROVAL"))).order_by(BankChangeRequest.created_at)).scalars().all()
        return {"supplier": sup.code, "status": sup.status,
                "onboardingOpen": onboarding is not None and onboarding.status == "RUNNING",
                "certificates": rows(s.execute(select(Certificate).where(Certificate.supplier_id == sup.id)
                                               .order_by(Certificate.type, Certificate.expires_on.desc())).scalars()),
                "bankAccounts": [{"account_masked": b.account_masked, "ifsc": b.ifsc, "holder_name": b.holder_name, "active": b.active,
                                  "payable_from": b.payable_from} for b in s.execute(select(SupplierBankAccount).where(
                                      SupplierBankAccount.supplier_id == sup.id)).scalars()],
                "pendingBankChanges": [{"number": c.number, "status": c.status} for c in pending]}


@router.post("/suppliers/{code}/profile", tags=["F8 Supplier"])
def submit_profile(code: str, body: ProfileIn, p: Principal = Depends(require_any("supplier:portal", "supplier:manage"))):
    with uow(p) as s:
        return supplier.submit_profile(s, supplier_ref(s, code), bank_account=body.bank_account, ifsc=body.ifsc,
                                       holder_name=body.holder_name, certificates=[c.model_dump() for c in body.certificates])


class BankChangeIn(BaseModel):
    bank_account: str = Field(pattern=r"^[0-9A-Za-z]{5,34}$")   # domestic: 9 to 18 digits (checked below); foreign: account number or IBAN
    ifsc: Optional[str] = Field(default=None, min_length=11, max_length=11, pattern=IFSC_PATTERN)
    holder_name: str = Field(min_length=3, max_length=200)
    # Foreign beneficiary bank (country other than IN): SWIFT/BIC, optional intermediary bank, ISO 20022 charge bearer and the RBI purpose code.
    country: str = Field(default="IN", pattern=r"^[A-Za-z]{2}$")
    swift_bic: Optional[str] = Field(default=None, max_length=11)
    intermediary_bic: Optional[str] = Field(default=None, max_length=11)
    charge_bearer: Optional[str] = Field(default=None, pattern="^(DEBT|CRED|SHAR)$")
    purpose_code: Optional[str] = Field(default=None, max_length=10)

    @model_validator(mode="after")
    def _domestic_account_is_digits(self):
        if self.country.upper() == "IN" and not re.fullmatch(r"[0-9]{9,18}", self.bank_account):
            raise ValueError("an Indian bank account number is 9 to 18 digits")
        return self


@router.post("/suppliers/{code}/bank-changes", status_code=201, tags=["F8 Supplier"])
def request_bank_change(code: str, body: BankChangeIn, p: Principal = Depends(require("supplier:bank"))):
    with uow(p) as s:
        return row(supplier.request_bank_change(s, supplier_ref(s, code), **body.model_dump()))


class CallbackIn(BaseModel):
    note: str


@router.post("/bank-changes/{number}/callback", tags=["F8 Supplier"])
def bank_callback(number: str, body: CallbackIn, p: Principal = Depends(require("supplier:bank"))):
    with uow(p) as s:
        change = s.execute(select(BankChangeRequest).where(BankChangeRequest.number == number)).scalar_one_or_none()
        if change is None:
            raise not_found("Bank change", number)
        return row(supplier.callback_verify(s, change, body.note))


class QualificationIn(BaseModel):
    category: str


@router.post("/suppliers/{code}/qualifications", status_code=201, tags=["F8 Supplier"])
def start_qualification(code: str, body: QualificationIn, p: Principal = Depends(require("supplier:manage"))):
    with uow(p) as s:
        return row(supplier.start_qualification(s, supplier_ref(s, code), body.category))


class AssessmentIn(BaseModel):
    questionnaire: Optional[dict] = None
    questionnaire_score: Optional[Decimal] = None
    audit_score: Optional[Decimal] = None
    sample_approval: Optional[str] = None


@router.post("/qualifications/{qid}/assessment", tags=["F8 Supplier"])
def assess(qid: uuid.UUID, body: AssessmentIn, p: Principal = Depends(require("supplier:manage"))):
    with uow(p) as s:
        q = s.get(Qualification, qid)
        if q is None:
            raise not_found("Qualification", qid)
        return row(supplier.record_assessment(s, q, **body.model_dump()))


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(QUALIFIED|CONDITIONAL|REJECTED)$")
    reason: str
    waiver: Optional[str] = None


@router.post("/qualifications/{qid}/decision", tags=["F8 Supplier"])
def decide(qid: uuid.UUID, body: DecisionIn, p: Principal = Depends(require("supplier:manage"))):
    with uow(p) as s:
        q = s.get(Qualification, qid)
        if q is None:
            raise not_found("Qualification", qid)
        return supplier.decide_qualification(s, q, body.decision, body.reason, body.waiver)  # row-locked and state-guarded


class BlockIn(BaseModel):
    reason: str


@router.post("/suppliers/{code}/block", tags=["F8 Supplier"])
def block_supplier(code: str, body: BlockIn, p: Principal = Depends(require("supplier:manage"))):
    with uow(p) as s:
        return supplier.block(s, supplier_ref(s, code), body.reason)


@router.post("/suppliers/{code}/unblock", tags=["F8 Supplier"])
def unblock_supplier(code: str, body: BlockIn, p: Principal = Depends(require("supplier:manage"))):
    """Lift a block (audited): restores the previous status and the payment blocks the block set."""
    with uow(p) as s:
        sup = s.execute(select(Supplier).where(Supplier.id == supplier_ref(s, code).id).with_for_update()).scalar_one()
        return supplier.unblock(s, sup, body.reason)


class ScreeningDispositionIn(BaseModel):
    decision: str = Field(pattern="^(CLEAR|MERGE|RESCREEN)$")
    note: str = Field(min_length=3, max_length=1000)
    merge_into: Optional[str] = None


@router.post("/suppliers/{code}/screening-disposition", tags=["F8 Supplier"])
def dispose_screening(code: str, body: ScreeningDispositionIn, p: Principal = Depends(require("supplier:manage"))):
    """F8-03 REVIEW disposition by a supplier manager other than the requester: clear, merge into the duplicate, or re-screen."""
    with uow(p) as s:
        sup = s.execute(select(Supplier).where(Supplier.id == supplier_ref(s, code).id).with_for_update()).scalar_one()
        return supplier.dispose_screening(s, sup, body.decision, body.note, body.merge_into)


class CertificateVerifyIn(BaseModel):
    note: str = Field(min_length=3, max_length=500)


@router.post("/certificates/{cid}/verify", tags=["F8 Supplier"])
def verify_certificate(cid: uuid.UUID, body: CertificateVerifyIn, p: Principal = Depends(require_any("supplier:manage", "quality:decide"))):
    """Explicit certificate verification by a supplier manager or quality inspector (audited, not the uploader)."""
    with uow(p) as s:
        cert = s.get(Certificate, cid, with_for_update=True)
        if cert is None:
            raise not_found("Certificate", cid)
        return row(supplier.verify_certificate(s, cert, body.note))


@router.get("/suppliers/{code}", tags=["F8 Supplier"])
def supplier_360(code: str, p: Principal = Depends(require(READ))):
    """SLM-01 Supplier 360: status per category, twin, scorecards, certificates, bank (masked), process."""
    with uow(p) as s:
        sup = supplier_ref(s, code)
        return row(sup, extra={
            "categories": rows(s.execute(select(SupplierCategoryStatus).where(SupplierCategoryStatus.supplier_id == sup.id)).scalars()),
            "twin": rows(s.execute(select(TwinSnapshot).where(TwinSnapshot.supplier_id == sup.id)).scalars()),
            "scorecards": rows(s.execute(select(Scorecard).where(Scorecard.supplier_id == sup.id).order_by(Scorecard.period)).scalars()),
            "certificates": rows(s.execute(select(Certificate).where(Certificate.supplier_id == sup.id)).scalars()),
            "bankAccounts": rows(s.execute(select(SupplierBankAccount).where(SupplierBankAccount.supplier_id == sup.id)).scalars()),
            "qualifications": rows(s.execute(select(Qualification).where(Qualification.supplier_id == sup.id)).scalars()),
            "process": [workflow.history(s, i) for i in [workflow.find(s, "SUPPLIER", sup.id)] if i],
        })
