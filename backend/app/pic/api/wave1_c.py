"""Wave 1 (engineer C1): material change requests, requirement bundling and invitee filters, rebates, clause extraction, contract
frameworks, supplier segmentation, development plans, ESG / cyber assessments and the responsiveness measures.

Every POST takes an Idempotency-Key; every route checks a role scope; errors are problem+json with a code."""
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.pic.api.deps import idempotency_key, idempotent, uow
from app.pic.models import (
    Capa, ClauseExtraction, Contract, DevelopmentPlan, Material, MaterialChangeRequest, RebateAccrual, SupplierAssessment,
)
from app.pic.platform.auth import READ, Principal, require, require_any
from app.pic.platform.errors import Problem, not_found
from app.pic.platform.serialize import row
from app.pic.services import clause_extract, material_changes, rebates, risk, sourcing, supplier_mgmt
from app.pic.services.common import by_ref, material_by_number, supplier_ref

router = APIRouter(prefix="/v1")


def _once(s, scope: str, key: Optional[str], body, produce, status: int = 200):
    """Run ``produce`` once per Idempotency-Key and return its stored response on a replay."""
    idem = idempotent(s, scope, key, body)
    if idem.replay:
        return idem.replay
    return idem.store(produce(), status)


# ---------------------------------------------------------------- 17 / 18 material change requests
class MaterialChangeIn(BaseModel):
    changes: dict = Field(min_length=1)
    reason: str = Field(min_length=5, max_length=1000)


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(APPROVE|REJECT)$")
    comment: Optional[str] = Field(default=None, max_length=1000)


class ReasonIn(BaseModel):
    reason: str = Field(default="", max_length=1000)


@router.get("/material-field-ownership", tags=["F9 MDM"])
def field_ownership(type: str = Query("STOCK", pattern="^(STOCK|NON_STOCK|SERVICE)$"), p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return material_changes.ownership_view(s, type)


@router.post("/materials/{number}/change-requests/preview", tags=["F9 MDM"])
def preview_material_change(number: str, body: MaterialChangeIn, p: Principal = Depends(require_any("mdm:request", "req:create"))):
    """Before/after, owning domains, routing and impact analysis without creating the request."""
    with uow(p) as s:
        return material_changes.preview(s, material_by_number(s, number), body.changes)


@router.post("/materials/{number}/change-requests", status_code=201, tags=["F9 MDM"])
def request_material_change(number: str, body: MaterialChangeIn, p: Principal = Depends(require_any("mdm:request", "req:create")),
                            key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        def run():
            material = s.execute(select(Material).where(Material.number == number).with_for_update()).scalar_one_or_none()
            if material is None:
                raise not_found("Material", number)
            return material_changes.view(s, material_changes.request_change(s, material, body.changes, body.reason))
        return _once(s, f"POST /v1/materials/{number}/change-requests", key, body, run, 201)


@router.get("/materials/{number}/change-requests", tags=["F9 MDM"])
def list_material_changes(number: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return material_changes.list_for(s, material_by_number(s, number))


@router.get("/materials/{number}", tags=["F9 MDM"])
def get_material(number: str, p: Principal = Depends(require(READ))):
    """The material master with its version and the change request in approval, if any."""
    with uow(p) as s:
        material = material_by_number(s, number)
        pending = s.execute(select(MaterialChangeRequest.number).where(
            MaterialChangeRequest.material_id == material.id, MaterialChangeRequest.status == "IN_APPROVAL")).scalar()
        return row(material, extra={"pendingChange": pending})


@router.get("/materials/{number}/versions", tags=["F9 MDM"])
def material_versions(number: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        material = material_by_number(s, number)
        return {"material": material.number, "version": material.version, "versions": material_changes.versions(s, material)}


@router.get("/material-change-requests", tags=["F9 MDM"])
def material_change_queue(status: Optional[str] = Query(None, pattern="^(IN_APPROVAL|APPLIED|REJECTED|CANCELLED)$"), p: Principal = Depends(require(READ))):
    with uow(p) as s:
        query = select(MaterialChangeRequest).order_by(MaterialChangeRequest.created_at.desc()).limit(200)
        if status:
            query = query.where(MaterialChangeRequest.status == status)
        return [material_changes.view(s, r) for r in s.execute(query).scalars()]


@router.get("/material-change-requests/{ref}", tags=["F9 MDM"])
def get_material_change(ref: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return material_changes.view(s, material_changes.by_number(s, ref))


@router.post("/material-change-requests/{ref}/decision", tags=["F9 MDM"])
def decide_material_change(ref: str, body: DecisionIn, p: Principal = Depends(require("mdm:request")), key: Optional[str] = Depends(idempotency_key)):
    """Completes the caller's open steward task for their domain."""
    with uow(p) as s:
        return _once(s, f"POST /v1/material-change-requests/{ref}/decision", key, body,
                     lambda: material_changes.view(s, material_changes.decide(s, material_changes.by_number(s, ref), body.decision, body.comment)))


@router.post("/material-change-requests/{ref}/cancel", tags=["F9 MDM"])
def cancel_material_change(ref: str, body: ReasonIn, p: Principal = Depends(require_any("mdm:request", "req:create")),
                           key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        return _once(s, f"POST /v1/material-change-requests/{ref}/cancel", key, body,
                     lambda: material_changes.view(s, material_changes.cancel(s, material_changes.by_number(s, ref), body.reason)))


# ---------------------------------------------------------------- 20 / 22 bundling and invitation filters
class BundleSelectionIn(BaseModel):
    requisition: str
    line: int


class BundlePreviewIn(BaseModel):
    lines: list[BundleSelectionIn] = Field(min_length=1, max_length=200)
    kind: str = Field(default="PR_LINES", pattern="^(PR_LINES|MRP_DEMAND|CATEGORY_PLAN)$")
    ref: Optional[str] = None


@router.get("/sourcing/bundle-candidates", tags=["F3 Sourcing"])
def bundle_candidates(category: Optional[str] = None, origin: Optional[str] = Query(None, pattern="^(MRP|MANUAL|PROJECT|CATALOGUE)$"),
                      category_plan: Optional[str] = None, plant: Optional[str] = None, p: Principal = Depends(require("sourcing:manage"))):
    """Approved requisition lines open for sourcing; origin MRP = MRP demand; category_plan = the lines of that plan's category."""
    with uow(p) as s:
        return sourcing.bundle_candidates(s, category=category, origin=origin, category_plan=category_plan, plant=plant)


@router.post("/sourcing/bundles/preview", tags=["F3 Sourcing"])
def bundle_preview(body: BundlePreviewIn, p: Principal = Depends(require("sourcing:manage"))):
    with uow(p) as s:
        return sourcing.bundle_preview(s, [l.model_dump() for l in body.lines], kind=body.kind, ref=body.ref)


@router.get("/sourcing/invitee-candidates", tags=["F3 Sourcing"])
def invitee_candidates(category: str, segment: Optional[str] = None, max_risk: Optional[int] = Query(None, ge=0, le=100),
                       status: Optional[str] = None, search: Optional[str] = None, exclude_signals: Optional[str] = None,
                       p: Principal = Depends(require("sourcing:manage"))):
    """Suppliers that may be invited in the category, with segment and risk score, filtered by segment, risk and qualification status."""
    with uow(p) as s:
        return sourcing.invitee_candidates(
            s, category, segment=segment, max_risk_score=max_risk, statuses=[x for x in (status or "").split(",") if x] or None, search=search,
            exclude_signal_categories=[x for x in (exclude_signals or "").split(",") if x] or None)


# ---------------------------------------------------------------- 24 frameworks, 26 rebates
@router.get("/contracts/{ref}/framework", tags=["F4 Contract"])
def contract_framework(ref: str, p: Principal = Depends(require(READ))):
    """The master agreement a call-off refers to, or the call-offs of a master agreement."""
    with uow(p) as s:
        contract = by_ref(s, Contract, ref)
        framework = s.get(Contract, contract.framework_contract_id) if contract.framework_contract_id else None
        call_offs = s.execute(select(Contract).where(Contract.framework_contract_id == contract.id).order_by(Contract.number)).scalars().all()
        brief = lambda c: {"number": c.number, "title": c.title, "type": c.type, "status": c.status, "validFrom": c.valid_from.isoformat(),  # noqa: E731
                           "validTo": c.valid_to.isoformat(), "targetValueMinor": c.target_value_minor}
        return {"contract": contract.number, "type": contract.type, "jurisdiction": contract.jurisdiction,
                "framework": brief(framework) if framework else None, "callOffs": [brief(c) for c in call_offs]}


class TierIn(BaseModel):
    from_: Decimal = Field(alias="from", ge=0)
    ratePct: Decimal = Field(gt=0, le=100)

    model_config = {"populate_by_name": True}


class RebateIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    basis: str = Field(pattern="^(VOLUME|VALUE)$")
    period: str = Field(pattern="^(MONTHLY|QUARTERLY|ANNUAL)$")
    tier_mode: str = Field(default="RETROACTIVE", pattern="^(SLAB|RETROACTIVE)$")
    scope: str = Field(default="CONTRACT", pattern="^(CONTRACT|SUPPLIER)$")
    tiers: list[TierIn] = Field(min_length=1, max_length=12)
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None


@router.post("/contracts/{ref}/rebates", status_code=201, tags=["F4 Contract"])
def create_rebate(ref: str, body: RebateIn, p: Principal = Depends(require("contract:manage")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        def run():
            contract = by_ref(s, Contract, ref, lock=True)
            agreement = rebates.create_agreement(
                s, contract, title=body.title, basis=body.basis, period=body.period, tier_mode=body.tier_mode, scope=body.scope,
                tiers=[{"from": str(t.from_), "ratePct": str(t.ratePct)} for t in body.tiers], valid_from=body.valid_from, valid_to=body.valid_to)
            rebates.accrue(s, agreement)
            return rebates.agreement_view(s, agreement)
        return _once(s, f"POST /v1/contracts/{ref}/rebates", key, body, run, 201)


@router.get("/contracts/{ref}/rebates", tags=["F4 Contract"])
def contract_rebates(ref: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return rebates.list_for_contract(s, by_ref(s, Contract, ref))


@router.get("/rebates/{ref}", tags=["F4 Contract"])
def get_rebate(ref: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return rebates.agreement_view(s, rebates.by_number(s, ref))


@router.post("/rebates/{ref}/accrue", tags=["F4 Contract"])
def accrue_rebate(ref: str, on: Optional[date] = None, p: Principal = Depends(require_any("contract:manage", "payment:run")),
                  key: Optional[str] = Depends(idempotency_key)):
    """Recompute the accrual of the period containing ``on`` (default today)."""
    with uow(p) as s:
        def run():
            agreement = rebates.by_number(s, ref, lock=True)
            rebates.accrue(s, agreement, on)
            return rebates.agreement_view(s, agreement)
        return _once(s, f"POST /v1/rebates/{ref}/accrue", key, {"on": str(on)}, run)


@router.post("/rebate-accruals/{accrual_id}/settle", tags=["F4 Contract"])
def settle_rebate(accrual_id: uuid.UUID, p: Principal = Depends(require_any("contract:manage", "payment:run")),
                  key: Optional[str] = Depends(idempotency_key)):
    """Settle a closed period as a vendor credit memo posted to the ERP exactly once."""
    with uow(p) as s:
        def run():
            accrual = s.get(RebateAccrual, accrual_id)
            if accrual is None:
                raise not_found("Rebate accrual", accrual_id)
            settlement = rebates.settle(s, accrual)
            return {"settlement": row(settlement), "agreement": rebates.agreement_view(s, rebates.by_number(s, str(settlement.agreement_id)))}
        return _once(s, f"POST /v1/rebate-accruals/{accrual_id}/settle", key, {"id": str(accrual_id)}, run)


@router.post("/rebates/{ref}/cancel", tags=["F4 Contract"])
def cancel_rebate(ref: str, body: ReasonIn, p: Principal = Depends(require("contract:manage")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        return _once(s, f"POST /v1/rebates/{ref}/cancel", key, body,
                     lambda: rebates.agreement_view(s, rebates.cancel_agreement(s, rebates.by_number(s, ref, lock=True), body.reason)))


# ---------------------------------------------------------------- 27 clause extraction
class ExtractionIn(BaseModel):
    contract: str
    text: str = Field(min_length=20, max_length=clause_extract.MAX_TEXT)
    source_name: str = Field(default="contract text", max_length=200)


class ReviewDecisionIn(BaseModel):
    seq: int
    action: str = Field(pattern="^(ACCEPT|EDIT|REJECT)$")
    text: Optional[str] = None
    code: Optional[str] = None
    position: Optional[str] = Field(default=None, pattern="^(STANDARD|FALLBACK|NON_STANDARD)$")
    note: Optional[str] = Field(default=None, max_length=500)


class ReviewIn(BaseModel):
    decisions: list[ReviewDecisionIn] = Field(min_length=1)


def _extraction(s, ref: str, lock: bool = False) -> ClauseExtraction:
    return by_ref(s, ClauseExtraction, ref, lock=lock)


@router.post("/clause-extractions", status_code=201, tags=["F4 Contract"])
def create_clause_extraction(body: ExtractionIn, p: Principal = Depends(require("contract:manage")), key: Optional[str] = Depends(idempotency_key)):
    """Rule-based extraction of the clauses of a contract text (no language model); the result waits for review."""
    with uow(p) as s:
        return _once(s, "POST /v1/clause-extractions", key, body,
                     lambda: clause_extract.view(s, clause_extract.create_extraction(s, contract_ref=body.contract, text=body.text,
                                                                                     source_name=body.source_name)), 201)


@router.get("/clause-extractions", tags=["F4 Contract"])
def list_clause_extractions(contract: Optional[str] = None, status: Optional[str] = None, p: Principal = Depends(require("contract:manage"))):
    with uow(p) as s:
        query = select(ClauseExtraction).order_by(ClauseExtraction.created_at.desc()).limit(100)
        if contract:
            query = query.where(ClauseExtraction.contract_ref == contract)
        if status:
            query = query.where(ClauseExtraction.status == status)
        return [clause_extract.view(s, e) for e in s.execute(query).scalars()]


@router.get("/clause-extractions/{ref}", tags=["F4 Contract"])
def get_clause_extraction(ref: str, p: Principal = Depends(require("contract:manage"))):
    with uow(p) as s:
        return clause_extract.view(s, _extraction(s, ref))


@router.post("/clause-extractions/{ref}/review", tags=["F4 Contract"])
def review_clause_extraction(ref: str, body: ReviewIn, p: Principal = Depends(require("contract:manage")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        return _once(s, f"POST /v1/clause-extractions/{ref}/review", key, body,
                     lambda: clause_extract.view(s, clause_extract.review(s, _extraction(s, ref, True), [d.model_dump() for d in body.decisions])))


@router.post("/clause-extractions/{ref}/apply", tags=["F4 Contract"])
def apply_clause_extraction(ref: str, p: Principal = Depends(require("contract:manage")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        return _once(s, f"POST /v1/clause-extractions/{ref}/apply", key, {"ref": ref}, lambda: clause_extract.apply(s, _extraction(s, ref, True)))


@router.post("/clause-extractions/{ref}/reject", tags=["F4 Contract"])
def reject_clause_extraction(ref: str, body: ReasonIn, p: Principal = Depends(require("contract:manage")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        return _once(s, f"POST /v1/clause-extractions/{ref}/reject", key, body,
                     lambda: clause_extract.view(s, clause_extract.reject(s, _extraction(s, ref, True), body.reason)))


# ---------------------------------------------------------------- 28 segmentation
class SegmentIn(BaseModel):
    segment: Optional[str] = Field(default=None, pattern="^(STRATEGIC|LEVERAGE|BOTTLENECK|ROUTINE)$")  # null returns to the automatic segment
    reason: str = Field(min_length=3, max_length=500)


@router.get("/supplier-segments", tags=["M06 Supplier"])
def segment_summary(p: Principal = Depends(require("spend:read"))):
    with uow(p) as s:
        return supplier_mgmt.segment_summary(s)


@router.post("/supplier-segments/recompute", tags=["M06 Supplier"])
def recompute_segments(p: Principal = Depends(require("supplier:manage")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        return _once(s, "POST /v1/supplier-segments/recompute", key, {}, lambda: supplier_mgmt.recompute_segments(s))


@router.get("/suppliers/{code}/segment", tags=["M06 Supplier"])
def supplier_segment(code: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return supplier_mgmt.segment_view(s, supplier_ref(s, code))


@router.put("/suppliers/{code}/segment", tags=["M06 Supplier"])
def set_supplier_segment(code: str, body: SegmentIn, p: Principal = Depends(require("supplier:manage"))):
    with uow(p) as s:
        return supplier_mgmt.set_segment_manually(s, supplier_ref(s, code), body.segment, body.reason)


@router.get("/suppliers/{code}/risk-score", tags=["M06 Supplier"])
def supplier_risk_score(code: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        supplier = supplier_ref(s, code)
        return {"supplier": supplier.code, **risk.supplier_risk_score(s, supplier)}


# ---------------------------------------------------------------- 29 development plans
class ActionIn(BaseModel):
    description: str = Field(min_length=3, max_length=1000)
    owner_id: uuid.UUID
    due_date: date


class PlanIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    objective: str = Field(min_length=5, max_length=2000)
    start_date: date
    target_date: date
    capa: Optional[str] = None
    metric: Optional[str] = Field(default=None, pattern="^(OTIF|PPM|INVOICE_ACCURACY|RFQ_RESPONSE|ESG)$")
    target_value: Optional[Decimal] = None
    actions: list[ActionIn] = []


class EvidenceIn(BaseModel):
    note: str = Field(min_length=3, max_length=1000)
    ref: Optional[str] = Field(default=None, max_length=200)


class CompleteIn(BaseModel):
    note: str = Field(default="", max_length=1000)


def _plan(s, ref: str, lock: bool = False) -> DevelopmentPlan:
    plan = by_ref(s, DevelopmentPlan, ref, lock=lock)
    return plan


def _own_plan(s, p: Principal, plan: DevelopmentPlan) -> None:
    if "SUPPLIER_USER" in p.roles and (p.supplier_id != plan.supplier_id or plan.status == "DRAFT"):
        raise not_found("Development plan", plan.number)


@router.get("/development-plans", tags=["M06 Supplier"])
def list_plans(supplier: Optional[str] = None, status: Optional[str] = None, p: Principal = Depends(require_any(READ, "supplier:portal"))):
    with uow(p) as s:
        return supplier_mgmt.list_plans(s, supplier_ref(s, supplier) if supplier else None, status)


@router.post("/suppliers/{code}/development-plans", status_code=201, tags=["M06 Supplier"])
def create_plan(code: str, body: PlanIn, p: Principal = Depends(require("supplier:manage")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        def run():
            capa = None
            if body.capa:
                capa = s.execute(select(Capa).where(Capa.number == body.capa)).scalar_one_or_none()
                if capa is None:
                    raise not_found("CAPA", body.capa)
            plan = supplier_mgmt.create_plan(
                s, supplier_ref(s, code), title=body.title, objective=body.objective, start_date=body.start_date, target_date=body.target_date,
                capa=capa, metric=body.metric, target_value=body.target_value, actions=[a.model_dump() for a in body.actions])
            return supplier_mgmt.plan_view(s, plan)
        return _once(s, f"POST /v1/suppliers/{code}/development-plans", key, body, run, 201)


@router.get("/development-plans/{ref}", tags=["M06 Supplier"])
def get_plan(ref: str, p: Principal = Depends(require_any(READ, "supplier:portal"))):
    with uow(p) as s:
        plan = _plan(s, ref)
        _own_plan(s, p, plan)
        return supplier_mgmt.plan_view(s, plan)


@router.post("/development-plans/{ref}/actions", status_code=201, tags=["M06 Supplier"])
def add_action(ref: str, body: ActionIn, p: Principal = Depends(require("supplier:manage")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        def run():
            plan = _plan(s, ref, True)
            supplier_mgmt.add_action(s, plan, description=body.description, owner_id=body.owner_id, due_date=body.due_date)
            return supplier_mgmt.plan_view(s, plan)
        return _once(s, f"POST /v1/development-plans/{ref}/actions", key, body, run, 201)


@router.post("/development-plans/{ref}/activate", tags=["M06 Supplier"])
def activate_plan(ref: str, p: Principal = Depends(require("supplier:manage")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        return _once(s, f"POST /v1/development-plans/{ref}/activate", key, {"ref": ref},
                     lambda: supplier_mgmt.plan_view(s, supplier_mgmt.activate_plan(s, _plan(s, ref, True))))


@router.post("/development-plans/{ref}/actions/{seq}/evidence", tags=["M06 Supplier"])
def add_evidence(ref: str, seq: int, body: EvidenceIn, p: Principal = Depends(require_any("supplier:manage", "supplier:portal", "quality:decide")),
                 key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        def run():
            plan = _plan(s, ref)
            _own_plan(s, p, plan)
            supplier_mgmt.add_evidence(s, plan, seq, note=body.note, ref=body.ref)
            return supplier_mgmt.plan_view(s, plan)
        return _once(s, f"POST /v1/development-plans/{ref}/actions/{seq}/evidence", key, body, run)


@router.post("/development-plans/{ref}/actions/{seq}/complete", tags=["M06 Supplier"])
def complete_action(ref: str, seq: int, body: CompleteIn, p: Principal = Depends(require_any("supplier:manage", "supplier:portal", "quality:decide")),
                    key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        def run():
            plan = _plan(s, ref)
            _own_plan(s, p, plan)
            supplier_mgmt.complete_action(s, plan, seq, note=body.note)
            return supplier_mgmt.plan_view(s, plan)
        return _once(s, f"POST /v1/development-plans/{ref}/actions/{seq}/complete", key, body, run)


@router.post("/development-plans/{ref}/actions/{seq}/cancel", tags=["M06 Supplier"])
def cancel_action(ref: str, seq: int, body: ReasonIn, p: Principal = Depends(require("supplier:manage")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        def run():
            plan = _plan(s, ref, True)
            supplier_mgmt.cancel_action(s, plan, seq, body.reason)
            return supplier_mgmt.plan_view(s, plan)
        return _once(s, f"POST /v1/development-plans/{ref}/actions/{seq}/cancel", key, body, run)


@router.post("/development-plans/{ref}/cancel", tags=["M06 Supplier"])
def cancel_plan(ref: str, body: ReasonIn, p: Principal = Depends(require("supplier:manage")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        return _once(s, f"POST /v1/development-plans/{ref}/cancel", key, body,
                     lambda: supplier_mgmt.plan_view(s, supplier_mgmt.cancel_plan(s, _plan(s, ref, True), body.reason)))


# ---------------------------------------------------------------- 30 ESG / cyber assessments and responsiveness
class AssessmentIn(BaseModel):
    kind: str = Field(pattern="^(ESG|CYBER)$")
    answers: dict
    as_of: Optional[date] = None


class ReviewAssessmentIn(BaseModel):
    accept: bool
    note: str = Field(default="", max_length=1000)


@router.get("/suppliers/{code}/assessments", tags=["M06 Supplier"])
def supplier_assessments(code: str, p: Principal = Depends(require_any(READ, "supplier:portal"))):
    with uow(p) as s:
        supplier = supplier_ref(s, code)
        if "SUPPLIER_USER" in p.roles and p.supplier_id != supplier.id:
            raise not_found("Supplier", code)
        return supplier_mgmt.assessments_view(s, supplier)


@router.post("/suppliers/{code}/assessments", status_code=201, tags=["M06 Supplier"])
def submit_assessment(code: str, body: AssessmentIn, p: Principal = Depends(require_any("supplier:portal", "supplier:manage")),
                      key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        return _once(s, f"POST /v1/suppliers/{code}/assessments", key, body,
                     lambda: row(supplier_mgmt.submit_assessment(s, supplier_ref(s, code), body.kind, body.answers, body.as_of)), 201)


@router.post("/assessments/{assessment_id}/review", tags=["M06 Supplier"])
def review_assessment(assessment_id: uuid.UUID, body: ReviewAssessmentIn, p: Principal = Depends(require("supplier:manage")),
                      key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        def run():
            item = s.get(SupplierAssessment, assessment_id)
            if item is None:
                raise not_found("Assessment", assessment_id)
            return row(supplier_mgmt.review_assessment(s, item, body.accept, body.note))
        return _once(s, f"POST /v1/assessments/{assessment_id}/review", key, body, run)


@router.get("/suppliers/{code}/responsiveness", tags=["M06 Supplier"])
def supplier_responsiveness(code: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return supplier_mgmt.responsiveness_view(s, supplier_ref(s, code))


@router.post("/suppliers/{code}/scorecard-measures/refresh", tags=["M06 Supplier"])
def refresh_measures(code: str, period: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"), p: Principal = Depends(require("supplier:manage")),
                     key: Optional[str] = Depends(idempotency_key)):
    """Recompute the RFQ response, CAPA response and ESG measures of a period (default: this month)."""
    from app.pic.platform import clock

    with uow(p) as s:
        def run():
            supplier = supplier_ref(s, code)
            supplier_mgmt.update_scorecard_measures(s, supplier, period or clock.today().strftime("%Y-%m"))
            return supplier_mgmt.responsiveness_view(s, supplier)
        return _once(s, f"POST /v1/suppliers/{code}/scorecard-measures/refresh", key, {"period": period}, run)
