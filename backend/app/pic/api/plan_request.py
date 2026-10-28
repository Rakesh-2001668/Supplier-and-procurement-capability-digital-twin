"""F1 MRP, F2 requisitions, F9 material governance, F8 supplier onboarding."""
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

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
from app.pic.services import mdm, planning, requisition, supplier
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


@router.get("/mrp/runs/{ref}", tags=["F1 MRP"])
def get_mrp_run(ref: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return views.mrp_run(s, by_ref(s, MrpRun, ref))


@router.get("/mrp/runs/{ref}/exceptions", tags=["F1 MRP"])
def mrp_exceptions(ref: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        run = by_ref(s, MrpRun, ref)
        return rows(s.execute(select(MrpException).where(MrpException.mrp_run_id == run.id).order_by(MrpException.value_at_risk_minor.desc())).scalars())


@router.post("/planned-orders/{ref}/firm", tags=["F1 MRP"])
def firm_planned_order(ref: str, p: Principal = Depends(require("mrp:plan"))):
    with uow(p) as s:
        return row(planning.firm(s, by_ref(s, PlannedOrder, ref, lock=True)))


@router.post("/planned-orders/{ref}/convert", tags=["F1 MRP"])
def convert_planned_order(ref: str, p: Principal = Depends(require("mrp:plan")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/planned-orders/{ref}/convert", key, {})
        if idem.replay:
            return idem.replay
        pr = planning.convert(s, by_ref(s, PlannedOrder, ref, lock=True))
        return idem.store(views.requisition(s, pr))


# ---------------------------------------------------------------- F2 guided buying and requisitions
@router.get("/guided-buying/search", tags=["F2 Requisition"])
def guided_search(q: str, plant: Optional[str] = None, p: Principal = Depends(require("req:create"))):
    with uow(p) as s:
        return requisition.search(s, q, plant)


class PrLineIn(BaseModel):
    item_type: str = Field(pattern="^(MATERIAL|FREE_TEXT|CATALOGUE|CONTRACT|SERVICE)$")
    purchase_type: str
    description: Optional[str] = None
    material: Optional[str] = None
    catalogue_item_id: Optional[str] = None
    material_group: Optional[str] = None
    category: Optional[str] = None
    qty: Decimal
    uom: Optional[str] = None
    price_est_minor: Optional[int] = None
    account_assignment_type: Optional[str] = None
    account_assignment_code: Optional[str] = None
    need_date: date
    storage_location: Optional[str] = None
    quotes_attached: int = 0
    reusable: bool = False
    mpn: Optional[str] = None
    attributes: Optional[dict] = None


class RequisitionIn(BaseModel):
    origin: str = Field(pattern="^(MANUAL|PROJECT|CATALOGUE)$")
    purpose_code: Optional[str] = None
    purpose_text: Optional[str] = None
    plant: str
    company_code: str = "1000"
    lines: list[PrLineIn]


@router.post("/requisitions", status_code=201, tags=["F2 Requisition"])
def create_requisition(body: RequisitionIn, p: Principal = Depends(require("req:create")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/requisitions", key, body)
        if idem.replay:
            return idem.replay
        pr = requisition.create(s, origin=body.origin, purpose_code=body.purpose_code, purpose_text=body.purpose_text, plant=body.plant,
                                company_code=body.company_code, lines=[l.model_dump() for l in body.lines])
        return idem.store(views.requisition(s, pr), 201)


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
    qty: Optional[Decimal] = None
    price_est_minor: Optional[int] = None
    account_assignment_type: Optional[str] = None
    account_assignment_code: Optional[str] = None
    need_date: Optional[date] = None
    description: Optional[str] = None


@router.patch("/requisitions/{ref}/lines/{line_no}", tags=["F2 Requisition"])
def change_requisition_line(ref: str, line_no: int, body: LineChange, p: Principal = Depends(require("req:create"))):
    with uow(p) as s:
        pr = by_ref(s, Requisition, ref, lock=True)
        return requisition.change_line(s, pr, line_no, body.model_dump(exclude_none=True))


@router.get("/requisitions/{ref}", tags=["F2 Requisition"])
def get_requisition(ref: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return views.requisition(s, by_ref(s, Requisition, ref))


@router.get("/buyer-workbench", tags=["F2 Requisition"])
def buyer_workbench(origin: Optional[str] = None, p: Principal = Depends(require("req:buyer"))):
    with uow(p) as s:
        return requisition.buyer_queue(s, origin)


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


@router.post("/materials/requests", status_code=201, tags=["F9 MDM"])
def new_material_request(body: MaterialRequestIn, p: Principal = Depends(require("req:create"))):
    with uow(p) as s:
        request = mdm.create_request(s, **body.model_dump())
        return views.material_request(s, request)


@router.post("/requisitions/{ref}/lines/{line_no}/promote-material", status_code=201, tags=["F9 MDM"])
def promote_free_text(ref: str, line_no: int, body: MaterialRequestIn, p: Principal = Depends(require("req:create"))):
    with uow(p) as s:
        pr = by_ref(s, Requisition, ref)
        line = s.execute(select(PrLine).where(PrLine.requisition_id == pr.id, PrLine.line_no == line_no)).scalar_one()
        if line.item_type != "FREE_TEXT":
            raise Problem(422, "RULE_VIOLATION", "Only free-text lines are promoted to material requests", rule_ref="P04")
        return views.material_request(s, mdm.create_request(s, **body.model_dump(), source_pr=line))


class OverrideIn(BaseModel):
    reason: str


@router.post("/materials/requests/{ref}/override", tags=["F9 MDM"])
def override_duplicate(ref: str, body: OverrideIn, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return views.material_request(s, mdm.steward_override(s, by_ref(s, MaterialRequest, ref, lock=True), body.reason))


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
    payment_terms: str = "N60"
    incoterms: Optional[str] = None
    segment: Optional[str] = None


@router.post("/suppliers", status_code=201, tags=["F8 Supplier"])
def register_supplier(body: SupplierIn, p: Principal = Depends(require("supplier:manage"))):
    with uow(p) as s:
        return row(supplier.register(s, **body.model_dump()))


class CertificateIn(BaseModel):
    type: str
    number: str
    issued_on: date
    expires_on: date
    mandatory_for: list[str] = []


class ProfileIn(BaseModel):
    bank_account: str
    ifsc: str = Field(min_length=11, max_length=11)
    holder_name: str
    certificates: list[CertificateIn] = []


@router.post("/suppliers/{code}/profile", tags=["F8 Supplier"])
def submit_profile(code: str, body: ProfileIn, p: Principal = Depends(require_any("supplier:portal", "supplier:manage"))):
    with uow(p) as s:
        return supplier.submit_profile(s, supplier_ref(s, code), bank_account=body.bank_account, ifsc=body.ifsc,
                                       holder_name=body.holder_name, certificates=[c.model_dump() for c in body.certificates])


class BankChangeIn(BaseModel):
    bank_account: str
    ifsc: str = Field(min_length=11, max_length=11)
    holder_name: str


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
        return supplier.decide_qualification(s, q, body.decision, body.reason, body.waiver)


class BlockIn(BaseModel):
    reason: str


@router.post("/suppliers/{code}/block", tags=["F8 Supplier"])
def block_supplier(code: str, body: BlockIn, p: Principal = Depends(require("supplier:manage"))):
    with uow(p) as s:
        return supplier.block(s, supplier_ref(s, code), body.reason)


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
