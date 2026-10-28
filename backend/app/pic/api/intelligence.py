"""M01 spend governance, M02 forecast review, M06 risk and performance, M10 payables insight and M11 initiatives."""
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.pic.api.deps import uow
from app.pic.models import (
    Capa, CategoryPlan, ClassificationReview, Forecast, MaverickHit, ReconciliationItem, ReconciliationRun, RiskSignal, SavingsInitiative, Supplier,
)
from app.pic.platform import clock
from app.pic.platform.auth import READ, Principal, require, require_any
from app.pic.platform.errors import not_found
from app.pic.platform.serialize import row
from app.pic.services import forecasting, payables, risk, savings, spend
from app.pic.services.common import by_ref, supplier_ref

router = APIRouter(prefix="/v1")


def _get(s, model, key: uuid.UUID, label: str):
    obj = s.get(model, key)
    if obj is None:
        raise not_found(label, key)
    return obj


# ---------------------------------------------------------------- M01 spend (SPD-01..09)
@router.get("/spend/overview", tags=["M01 Spend"])
def spend_overview(p: Principal = Depends(require("spend:read"))):
    with uow(p) as s:
        return spend.overview(s)


@router.get("/spend/treemap", tags=["M01 Spend"])
def spend_treemap(p: Principal = Depends(require("spend:read"))):
    with uow(p) as s:
        return spend.treemap(s)


@router.get("/spend/suppliers", tags=["M01 Spend"])
def spend_suppliers(p: Principal = Depends(require("spend:read"))):
    with uow(p) as s:
        return spend.suppliers_view(s)


@router.get("/spend/compliance", tags=["M01 Spend"])
def spend_compliance(p: Principal = Depends(require("spend:read"))):
    with uow(p) as s:
        return spend.compliance(s)


@router.get("/spend/forecast", tags=["M01 Spend"])
def spend_forecast(category: Optional[str] = None, plant: Optional[str] = None, horizon: int = Query(6, ge=1, le=12),
                   p: Principal = Depends(require("spend:read"))):
    with uow(p) as s:
        return spend.forecast(s, category, plant, horizon)


@router.get("/spend/maverick", tags=["M01 Spend"])
def maverick_hits(status: Optional[str] = "OPEN", rule: Optional[str] = None, limit: int = Query(200, le=500),
                  p: Principal = Depends(require("spend:read"))):
    with uow(p) as s:
        query = select(MaverickHit).order_by(MaverickHit.amount_minor.desc()).limit(limit)
        if status:
            query = query.where(MaverickHit.status == status)
        if rule:
            query = query.where(MaverickHit.rule_code == rule)
        suppliers = {x.id: x.code for x in s.execute(select(Supplier)).scalars()}
        hits = [row(h, extra={"supplier": suppliers.get(h.supplier_id)}) for h in s.execute(query).scalars()]
        from app.pic.models import MaverickRule
        return {"rules": [row(r) for r in s.execute(select(MaverickRule).order_by(MaverickRule.code)).scalars()], "hits": hits}


class DispositionIn(BaseModel):
    disposition: str = Field(pattern="^(ACCEPTED_EXCEPTION|RECOVERY|POLICY_BREACH|FALSE_POSITIVE)$")
    comment: str


@router.post("/spend/maverick-hits/{hit_id}/disposition", tags=["M01 Spend"])
def dispose_hit(hit_id: uuid.UUID, body: DispositionIn, p: Principal = Depends(require("spend:read"))):
    with uow(p) as s:
        return row(spend.dispose(s, _get(s, MaverickHit, hit_id, "Maverick hit"), body.disposition, body.comment))


@router.get("/spend/classification-reviews", tags=["M01 Spend"])
def classification_reviews(status: str = "OPEN", p: Principal = Depends(require_any("spend:read", "mdm:request"))):
    with uow(p) as s:
        from app.pic.models import TaxonomyNode
        reviews = s.execute(select(ClassificationReview).where(ClassificationReview.status == status)
                            .order_by(ClassificationReview.confidence)).scalars().all()
        return {"categories": [{"code": n.code, "name": n.name} for n in s.execute(select(TaxonomyNode).where(TaxonomyNode.level == 3)
                                                                                   .order_by(TaxonomyNode.code)).scalars()],
                "reviews": [row(r) for r in reviews]}


class ReviewDecisionIn(BaseModel):
    category: str
    comment: Optional[str] = None


@router.post("/spend/classification-reviews/{review_id}/decision", tags=["M01 Spend"])
def decide_review(review_id: uuid.UUID, body: ReviewDecisionIn, p: Principal = Depends(require_any("spend:read", "mdm:request"))):
    with uow(p) as s:
        return row(spend.decide_review(s, _get(s, ClassificationReview, review_id, "Classification review"), body.category, body.comment))


@router.get("/category-plans", tags=["M01 Spend"])
def category_plans(p: Principal = Depends(require("spend:read"))):
    with uow(p) as s:
        return [row(c) for c in s.execute(select(CategoryPlan).order_by(CategoryPlan.spend_minor.desc())).scalars()]


class PlanGenerateIn(BaseModel):
    fiscal_year: Optional[str] = None


@router.post("/category-plans", tags=["M01 Spend"])
def generate_category_plans(body: PlanGenerateIn, p: Principal = Depends(require("savings:manage"))):
    with uow(p) as s:
        fy = body.fiscal_year or clock.fiscal_year(clock.today())
        return [row(c) for c in spend.generate_plans(s, fy, p.user_id)]


class PlanApproveIn(BaseModel):
    comment: Optional[str] = None


@router.post("/category-plans/{ref}/approve", tags=["M01 Spend"])
def approve_category_plan(ref: str, body: PlanApproveIn, p: Principal = Depends(require("spend:read"))):
    with uow(p) as s:
        return row(spend.approve_plan(s, spend.get_plan(s, ref), body.comment))


# ---------------------------------------------------------------- M02 forecast review (MRP-04)
@router.get("/forecasts", tags=["M02 MRP"])
def forecasts(material: Optional[str] = None, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return forecasting.review(s, material)


@router.post("/forecasts/generate", tags=["M02 MRP"])
def generate_forecasts(p: Principal = Depends(require("mrp:plan"))):
    with uow(p) as s:
        created = forecasting.generate(s)
        return {"created": len(created), "recommendations": len(forecasting.sense(s))}


class OverrideIn(BaseModel):
    qty: Decimal = Field(ge=0)
    reason: str
    release: bool = True


@router.post("/forecasts/{forecast_id}/override", tags=["M02 MRP"])
def override_forecast(forecast_id: uuid.UUID, body: OverrideIn, p: Principal = Depends(require("mrp:plan"))):
    with uow(p) as s:
        return row(forecasting.override(s, _get(s, Forecast, forecast_id, "Forecast"), body.qty, body.reason, body.release))


@router.post("/forecasts/{forecast_id}/release", tags=["M02 MRP"])
def release_forecast(forecast_id: uuid.UUID, p: Principal = Depends(require("mrp:plan"))):
    with uow(p) as s:
        return row(forecasting.release_period(s, _get(s, Forecast, forecast_id, "Forecast")))


# ---------------------------------------------------------------- M06 risk, performance, CAPA (SLM-03/04)
@router.get("/supplier-risk", tags=["M06 Supplier"])
def supplier_risk(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return risk.monitor(s)


@router.post("/supplier-risk/scan", tags=["M06 Supplier"])
def supplier_risk_scan(p: Principal = Depends(require("supplier:manage"))):
    with uow(p) as s:
        return {"newSignals": len(risk.scan(s))}


class MitigationIn(BaseModel):
    action: str
    close: bool = False


@router.post("/risk-signals/{signal_id}/mitigation", tags=["M06 Supplier"])
def mitigate_signal(signal_id: uuid.UUID, body: MitigationIn, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return row(risk.mitigate(s, _get(s, RiskSignal, signal_id, "Risk signal"), body.action, body.close))


class SignalIn(BaseModel):
    source: str
    category: str
    severity: str
    title: str
    key: str
    detail: dict = {}


@router.post("/suppliers/{code}/risk-signals", status_code=201, tags=["M06 Supplier"])
def ingest_signal(code: str, body: SignalIn, p: Principal = Depends(require("supplier:manage"))):
    with uow(p) as s:
        signal = risk.ingest(s, supplier_ref(s, code), source=body.source, category=body.category, severity=body.severity, title=body.title,
                             detail=body.detail, key=body.key)
        return row(signal) if signal else {"duplicate": True}


@router.get("/supplier-performance", tags=["M06 Supplier"])
def supplier_performance(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return risk.performance(s)


@router.get("/capas", tags=["M06 Supplier"])
def capas(p: Principal = Depends(require_any(READ, "supplier:portal"))):
    with uow(p) as s:
        query = select(Capa).order_by(Capa.created_at.desc())
        if p.supplier_id:
            query = query.where(Capa.supplier_id == p.supplier_id)
        suppliers = {x.id: x.code for x in s.execute(select(Supplier)).scalars()}
        return [row(c, extra={"supplier": suppliers.get(c.supplier_id)}) for c in s.execute(query).scalars()]


class CapaIn(BaseModel):
    supplier: str
    source_ref: str
    finding: str
    due_days: int = 30


@router.post("/capas", status_code=201, tags=["M06 Supplier"])
def open_capa(body: CapaIn, p: Principal = Depends(require_any("quality:decide", "supplier:manage"))):
    with uow(p) as s:
        return row(risk.open_capa(s, supplier_ref(s, body.supplier), source_type="MANUAL", source_ref=body.source_ref, finding=body.finding,
                                  due_days=body.due_days))


class CapaResponseIn(BaseModel):
    root_cause: str
    actions: list[dict]


def _capa(s, ref: str) -> Capa:
    capa = s.execute(select(Capa).where(Capa.number == ref)).scalar_one_or_none()
    if capa is None:
        raise not_found("CAPA", ref)
    return capa


@router.post("/capas/{ref}/response", tags=["M06 Supplier"])
def respond_capa(ref: str, body: CapaResponseIn, p: Principal = Depends(require_any("supplier:portal", "quality:decide", "supplier:manage"))):
    with uow(p) as s:
        return row(risk.respond_capa(s, _capa(s, ref), root_cause=body.root_cause, actions=body.actions))


class CapaVerifyIn(BaseModel):
    effective: bool
    comment: str


@router.post("/capas/{ref}/verify", tags=["M06 Supplier"])
def verify_capa(ref: str, body: CapaVerifyIn, p: Principal = Depends(require("quality:decide"))):
    with uow(p) as s:
        return row(risk.verify_capa(s, _capa(s, ref), body.effective, body.comment))


class CategoryStatusIn(BaseModel):
    status: str = Field(pattern="^(PREFERRED|EXITED)$")
    reason: str


@router.post("/suppliers/{code}/categories/{category}/status", tags=["M06 Supplier"])
def supplier_category_status(code: str, category: str, body: CategoryStatusIn, p: Principal = Depends(require_any("supplier:manage", "sourcing:manage"))):
    with uow(p) as s:
        return row(risk.set_preferred(s, supplier_ref(s, code), category, body.status == "PREFERRED", body.reason))


# ---------------------------------------------------------------- M10 posting & reconciliation, payables insight (INV-03/04)
class ReconcileIn(BaseModel):
    company_code: str = "1000"


@router.post("/reconciliation/runs", status_code=201, tags=["M10 Invoice"])
def run_reconciliation(body: ReconcileIn, p: Principal = Depends(require_any("invoice:post", "payment:run"))):
    with uow(p) as s:
        return payables.reconcile(s, body.company_code)


@router.get("/reconciliation/runs", tags=["M10 Invoice"])
def reconciliation_runs(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        runs = s.execute(select(ReconciliationRun).order_by(ReconciliationRun.as_of.desc()).limit(20)).scalars().all()
        return [payables.reconciliation_view(s, r) for r in runs]


class ResolveItemIn(BaseModel):
    resolution: str


@router.post("/reconciliation/items/{item_id}/resolve", tags=["M10 Invoice"])
def resolve_item(item_id: uuid.UUID, body: ResolveItemIn, p: Principal = Depends(require_any("invoice:post", "payment:run"))):
    with uow(p) as s:
        return row(payables.resolve_reconciliation_item(s, _get(s, ReconciliationItem, item_id, "Reconciliation item"), body.resolution))


@router.get("/payables/insights", tags=["M10 Invoice"])
def payables_insights(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return payables.insights(s)


# ---------------------------------------------------------------- M11 initiatives (SAV-01)
class InitiativeIn(BaseModel):
    title: str
    category: str
    baseline_method: str = Field(pattern="^(LAST_PRICE|WAVG_12M|STANDARD|SHOULD_COST)$")
    annual_volume: Decimal = Field(gt=0)
    material: Optional[str] = None
    baseline_price_minor: Optional[int] = None


@router.post("/savings/initiatives", status_code=201, tags=["M11 Savings"])
def create_initiative(body: InitiativeIn, p: Principal = Depends(require("savings:manage"))):
    with uow(p) as s:
        return row(savings.create_initiative(s, title=body.title, category=body.category, baseline_method=body.baseline_method,
                                             annual_volume=body.annual_volume, material_number=body.material,
                                             baseline_price_minor=body.baseline_price_minor))


class NegotiateIn(BaseModel):
    new_price_minor: int = Field(gt=0)
    supplier: str
    evidence: str


@router.post("/savings/{ref}/negotiate", tags=["M11 Savings"])
def negotiate_initiative(ref: str, body: NegotiateIn, p: Principal = Depends(require("savings:manage"))):
    with uow(p) as s:
        return row(savings.negotiate(s, by_ref(s, SavingsInitiative, ref, lock=True), body.new_price_minor, body.supplier, body.evidence))


class LoseIn(BaseModel):
    reason: str


@router.post("/savings/{ref}/lose", tags=["M11 Savings"])
def lose_initiative(ref: str, body: LoseIn, p: Principal = Depends(require("savings:manage"))):
    with uow(p) as s:
        return row(savings.lose(s, by_ref(s, SavingsInitiative, ref, lock=True), body.reason))
