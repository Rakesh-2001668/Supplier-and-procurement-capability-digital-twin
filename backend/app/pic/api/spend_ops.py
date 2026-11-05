"""M01 spend: analytics, drill and export, data quality, forecast accuracy, steward queue, maverick lifecycle, supplier duplicates, taxonomy
and category plan workflow (second pass). The first-pass spend routes stay in api/intelligence.py."""
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.pic.api.deps import idempotency_key, idempotent, uow
from app.pic.api.intelligence import _csv, _cube_filter, _get
from app.pic.models import CategoryPlan, MaverickHit, TaxonomyNode
from app.pic.platform import audit
from app.pic.platform.auth import Principal, require, require_any
from app.pic.platform.errors import Problem
from app.pic.platform.serialize import row
from app.pic.services import spend, spend_analytics, spend_cube, spend_forecast, spend_quality, spend_scope, spend_workflow
from app.pic.services.common import principal

router = APIRouter(prefix="/v1", tags=["M01 Spend"])
READ_SPEND = "spend:read"
# What a TENANT_ADMIN may SEE of the spend module: the maverick work list (to escalate it), the rules (to version them) and the cube status (to refresh it).
# It reads, it cannot decide: dispositions, recoveries, plans and the analytics stay on spend:read, which the admin role does not hold.
OPERATE = require_any("spend:read", "admin:rules", "admin:integration")
STEWARD = require_any("spend:read", "mdm:request")   # data stewards work the queue and the duplicate clusters without the analytics scope


def _filter(period_from, period_to, category, supplier, parent, plant, company_code, cost_centre, wbs, cost_object, currency, source_system, source,
            contracted, addressable, maverick, buyer):
    return _cube_filter(period_from, period_to, category, supplier, parent, plant, company_code, cost_centre, wbs, cost_object, currency, source_system,
                        source, contracted, addressable, maverick, buyer)


# ---------------------------------------------------------------- analytics
@router.get("/spend/summary")
def spend_summary(fiscal_year: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"), plant: Optional[str] = None, p: Principal = Depends(require(READ_SPEND))):
    """The M01 measure set of a fiscal year: spend, invoiced, credit / debit notes, committed, savings, price variance, counts, coverage, maverick,
    under-management, supplier counts, tail, HHI."""
    with uow(p) as s:
        return spend_analytics.summary(s, fiscal_year, spend_cube.CubeFilter(plants=_csv(plant)))


@router.get("/spend/comparison")
def spend_comparison(dims: str = "category", anchor: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"), limit: int = Query(200, ge=1, le=5000),
                     category: Optional[str] = None, supplier: Optional[str] = None, parent: Optional[str] = None, plant: Optional[str] = None,
                     company_code: Optional[str] = None, cost_centre: Optional[str] = None, currency: Optional[str] = None,
                     contracted: Optional[bool] = None, addressable: Optional[bool] = None, maverick: Optional[bool] = None, buyer: Optional[str] = None,
                     p: Principal = Depends(require(READ_SPEND))):
    """YTD vs prior-year YTD, YoY, QoQ, run-rate and share of spend by the given dimensions."""
    flt = _filter(None, None, category, supplier, parent, plant, company_code, cost_centre, None, None, currency, None, None, contracted, addressable,
                  maverick, buyer)
    with uow(p) as s:
        return spend_analytics.comparison(s, _csv(dims), flt, anchor, limit)


@router.get("/spend/pareto")
def spend_pareto(by: str = Query("supplier", pattern="^(supplier|parent_supplier|category)$"), period_from: Optional[str] = None, period_to: Optional[str] = None,
                 category: Optional[str] = None, plant: Optional[str] = None, limit: int = Query(500, ge=1, le=5000), p: Principal = Depends(require(READ_SPEND))):
    """Pareto / ABC ranking with cumulative share and the long tail."""
    flt = _filter(period_from, period_to, category, None, None, plant, None, None, None, None, None, None, None, None, True, None, None)
    with uow(p) as s:
        return spend_analytics.pareto(s, by, flt, limit)


@router.get("/spend/category-structure")
def spend_category_structure(period_from: Optional[str] = None, period_to: Optional[str] = None, plant: Optional[str] = None,
                             p: Principal = Depends(require(READ_SPEND))):
    """Per category: spend share, supplier count, HHI on parent suppliers, top supplier."""
    flt = _filter(period_from, period_to, None, None, None, plant, None, None, None, None, None, None, None, None, True, None, None)
    with uow(p) as s:
        return spend_analytics.category_structure(s, flt)


@router.get("/spend/savings-potential")
def spend_savings_potential(category: Optional[str] = None, plant: Optional[str] = None, p: Principal = Depends(require(READ_SPEND))):
    """Indicative savings potential by lever (consolidation, contract coverage, price recovery) from the cube."""
    flt = _filter(None, None, category, None, None, plant, None, None, None, None, None, None, None, None, None, None, None)
    with uow(p) as s:
        return spend_analytics.savings_potential(s, flt)


@router.get("/spend/lines")
def spend_lines(cursor: Optional[str] = Query(None, max_length=300), limit: int = Query(100, ge=1, le=500), document_type: Optional[str] = None,
                period_from: Optional[str] = None, period_to: Optional[str] = None, category: Optional[str] = None, supplier: Optional[str] = None,
                parent: Optional[str] = None, plant: Optional[str] = None, company_code: Optional[str] = None, cost_centre: Optional[str] = None,
                wbs: Optional[str] = None, cost_object: Optional[str] = None, currency: Optional[str] = None, source_system: Optional[str] = None,
                source: Optional[str] = None, contracted: Optional[bool] = None, addressable: Optional[bool] = None, maverick: Optional[bool] = None,
                buyer: Optional[str] = None, p: Principal = Depends(require(READ_SPEND))):
    """Drill from a cube slice to its spend lines (keyset pagination) with the invoice / order / note lineage of each."""
    flt = _filter(period_from, period_to, category, supplier, parent, plant, company_code, cost_centre, wbs, cost_object, currency, source_system, source,
                  contracted, addressable, maverick, buyer)
    with uow(p) as s:
        return spend_analytics.lines(s, flt, cursor=cursor, limit=limit, document_type=document_type)


@router.get("/spend/export")
def spend_export(kind: str = Query("cube", pattern="^(cube|lines)$"), dims: str = "category", period_from: Optional[str] = None, period_to: Optional[str] = None,
                 category: Optional[str] = None, supplier: Optional[str] = None, parent: Optional[str] = None, plant: Optional[str] = None,
                 company_code: Optional[str] = None, cost_centre: Optional[str] = None, wbs: Optional[str] = None, cost_object: Optional[str] = None,
                 currency: Optional[str] = None, source_system: Optional[str] = None, source: Optional[str] = None, contracted: Optional[bool] = None,
                 addressable: Optional[bool] = None, maverick: Optional[bool] = None, buyer: Optional[str] = None, p: Principal = Depends(require(READ_SPEND))):
    """CSV of a cube slice (or its lines), capped at the tenant's export limit and audited with the file's SHA-256 (also in X-Content-SHA256)."""
    flt = _filter(period_from, period_to, category, supplier, parent, plant, company_code, cost_centre, wbs, cost_object, currency, source_system, source,
                  contracted, addressable, maverick, buyer)
    with uow(p) as s:
        out = spend_analytics.export_csv(s, kind, _csv(dims), flt)
    return Response(content=out["body"], media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{out["filename"]}"', "X-Content-SHA256": out["sha256"], "X-Row-Count": str(out["rows"]),
                             "X-Truncated": "true" if out["truncated"] else "false", "Cache-Control": "no-store"})


# ---------------------------------------------------------------- data quality and forecast accuracy
@router.get("/spend/quality")
def quality_report(p: Principal = Depends(require(READ_SPEND))):
    """The data-quality checks of the spend cube with a 0-100 score (not stored)."""
    with uow(p) as s:
        return spend_quality.assess(s, persist=False)


@router.post("/spend/quality/run")
def quality_run(p: Principal = Depends(require(READ_SPEND)), key: Optional[str] = Depends(idempotency_key)):
    """Assess and store the result in the score history (a user with a restricted scope gets the report but nothing is stored)."""
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/spend/quality/run", key, {})
        if idem.replay:
            return idem.replay
        return idem.store(spend_quality.assess(s, persist=True))


@router.get("/spend/quality/history")
def quality_history(limit: int = Query(30, ge=1, le=200), p: Principal = Depends(require(READ_SPEND))):
    with uow(p) as s:
        return {"runs": spend_quality.history(s, limit)}


@router.get("/spend/forecast/accuracy")
def forecast_accuracy(category: Optional[str] = None, p: Principal = Depends(require(READ_SPEND))):
    """The forecasts that were issued against the spend that happened: MAPE overall / per horizon / per category and band coverage."""
    with uow(p) as s:
        return spend_forecast.accuracy(s, category)


@router.post("/spend/forecast/snapshot")
def forecast_snapshot(horizon: int = Query(6, ge=1, le=12), p: Principal = Depends(require("savings:manage"))):
    with uow(p) as s:
        return spend_forecast.snapshot(s, horizon)


# ---------------------------------------------------------------- classification
@router.get("/spend/classification-queue")
def classification_queue(status: str = Query("OPEN", pattern="^(OPEN|PENDING_SECOND|ACCEPTED|RECLASSIFIED)$"), sort: str = Query("value", pattern="^(value|due|confidence|age)$"),
                         limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), overdue: Optional[bool] = None, min_value: Optional[int] = Query(None, ge=0),
                         supplier: Optional[str] = Query(None, max_length=60), text: Optional[str] = Query(None, max_length=100),
                         p: Principal = Depends(STEWARD)):
    """The steward queue with value, age, SLA and four-eyes flag, and the queue summary (ageing, overdue, accept rate)."""
    with uow(p) as s:
        return spend_workflow.review_queue(s, status, sort=sort, limit=limit, offset=offset, overdue=overdue, min_value=min_value, supplier=supplier, text_=text)


class BulkReclassifyIn(BaseModel):
    category: str = Field(max_length=40)
    comment: str = Field(min_length=5, max_length=2000)
    review_ids: Optional[list[uuid.UUID]] = Field(default=None, max_length=500)
    text: Optional[str] = Field(default=None, max_length=100, description="Every open review whose description contains this text")
    supplier: Optional[str] = Field(default=None, max_length=60)
    learn_keyword: Optional[str] = Field(default=None, max_length=40)
    reason: Optional[str] = Field(default=None, max_length=500)


@router.post("/spend/classification-reviews/bulk")
def bulk_reclassify(body: BulkReclassifyIn, p: Principal = Depends(STEWARD), key: Optional[str] = Depends(idempotency_key)):
    """Decide many open reviews with one category; each is a normal decision with its own result (four-eyes values are parked as the first decision)."""
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/spend/classification-reviews/bulk", key, body)
        if idem.replay:
            return idem.replay
        return idem.store(spend_workflow.bulk_reclassify(s, body.category, review_ids=body.review_ids, text_=body.text, supplier=body.supplier,
                                                         comment=body.comment, learn_keyword=body.learn_keyword, reason=body.reason))


class NodeIn(BaseModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9\-]{1,38}$")
    name: str = Field(min_length=2, max_length=120)
    parent_code: str = Field(max_length=40)
    keywords: list[str] = Field(default_factory=list, max_length=60)
    addressable: bool = True


class NodePatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    keywords: Optional[list[str]] = Field(default=None, max_length=60)
    addressable: Optional[bool] = None
    active: Optional[bool] = None


@router.get("/spend/taxonomy")
def taxonomy(p: Principal = Depends(STEWARD)):
    with uow(p) as s:
        counts = dict(s.execute(select(spend.SpendLine.category, spend.func.count()).group_by(spend.SpendLine.category)).all())
        return [{"code": n.code, "name": n.name, "parentCode": n.parent_code, "level": n.level, "keywords": n.keywords or [], "addressable": n.addressable,
                 "active": n.active, "lines": int(counts.get(n.code, 0))} for n in s.execute(select(TaxonomyNode).order_by(TaxonomyNode.level, TaxonomyNode.code)).scalars()]


def _steward(s) -> None:
    if not set(principal(s).roles) & {"CATEGORY_MANAGER", "MDM_STEWARD", "PROCUREMENT_HEAD", "TENANT_ADMIN"}:
        raise Problem(403, "FORBIDDEN", "The taxonomy is maintained by a category manager or data steward", rule_ref="M01")


def _keywords_free(s, words: list[str], code: str) -> None:
    for word in words:
        owner = s.execute(select(TaxonomyNode.code).where(TaxonomyNode.keywords.any(word), TaxonomyNode.code != code)).scalars().first()
        if owner:
            raise Problem(409, "KEYWORD_CONFLICT", f"'{word}' already belongs to {owner}; two categories cannot own the same keyword", rule_ref="M01")


def _clean_keywords(words: list[str]) -> list[str]:
    out = []
    for word in words:
        w = word.strip().lower()
        if not w or len(w) > 60 or len(w) < 2:
            raise Problem(422, "INVALID_KEYWORD", "A keyword is 2-60 characters")
        if w not in out:
            out.append(w)
    return out


@router.post("/spend/taxonomy", status_code=201)
def add_node(body: NodeIn, p: Principal = Depends(STEWARD)):
    """Add a category (level 3) under a family, or a commodity (level 4) under a category."""
    with uow(p) as s:
        _steward(s)
        parent = s.execute(select(TaxonomyNode).where(TaxonomyNode.code == body.parent_code, TaxonomyNode.active.is_(True))).scalar_one_or_none()
        if parent is None or parent.level not in (2, 3):
            raise Problem(422, "INVALID_PARENT", "The parent must be a family (level 2) or a category (level 3)", rule_ref="M01")
        if s.execute(select(TaxonomyNode.id).where(TaxonomyNode.code == body.code)).first():
            raise Problem(409, "NODE_EXISTS", f"{body.code} already exists", rule_ref="M01")
        keywords = _clean_keywords(body.keywords)
        _keywords_free(s, keywords, body.code)
        node = TaxonomyNode(tenant_id=p.tenant_id, code=body.code, parent_code=parent.code, level=parent.level + 1, name=body.name, keywords=keywords,
                            addressable=body.addressable, created_by=p.user_id)
        s.add(node)
        s.flush()
        audit.record(s, "TAXONOMY_NODE", node.id, "CREATED", object_ref=node.code, after={"parent": parent.code, "level": node.level, "keywords": keywords})
        return row(node)


@router.patch("/spend/taxonomy/{code}")
def patch_node(code: str, body: NodePatch, p: Principal = Depends(STEWARD)):
    with uow(p) as s:
        _steward(s)
        node = s.execute(select(TaxonomyNode).where(TaxonomyNode.code == code)).scalar_one_or_none()
        if node is None:
            raise Problem(404, "NOT_FOUND", f"Taxonomy node {code} not found")
        before = {"name": node.name, "keywords": node.keywords, "addressable": node.addressable, "active": node.active}
        if body.name is not None:
            node.name = body.name
        if body.keywords is not None:
            node.keywords = _clean_keywords(body.keywords)
            _keywords_free(s, node.keywords, code)
        if body.addressable is not None:
            node.addressable = body.addressable
        if body.active is not None:
            if not body.active and s.execute(select(spend.SpendLine.id).where(spend.SpendLine.category == code).limit(1)).first():
                raise Problem(409, "NODE_IN_USE", f"{code} has spend lines; reclassify them before retiring the node", rule_ref="M01")
            node.active = body.active
        spend._KEYWORD_PATTERNS.clear()
        audit.record(s, "TAXONOMY_NODE", node.id, "UPDATED", object_ref=code, before=before,
                     after={"name": node.name, "keywords": node.keywords, "addressable": node.addressable, "active": node.active})
        return row(node)


# ---------------------------------------------------------------- maverick
@router.get("/spend/maverick/worklist")
def maverick_worklist(status: Optional[str] = Query(None, pattern="^(OPEN|DISPOSED|RECOVERY_OPEN|RESOLVED)$"), rule: Optional[str] = Query(None, max_length=30),
                      overdue: Optional[bool] = None, supplier: Optional[str] = Query(None, max_length=60), owner: Optional[str] = Query(None, pattern="^me$"),
                      limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0), p: Principal = Depends(OPERATE)):
    """Hits with owner, SLA, escalation and savings at risk, plus the summary (open, overdue, at risk, recovered, by rule and by owner role)."""
    with uow(p) as s:
        return spend_workflow.hits_view(s, status=status, rule=rule, overdue=overdue, supplier=supplier, owner=owner, limit=limit, offset=offset)


@router.get("/spend/maverick/repeat-offenders")
def maverick_repeat_offenders(months: int = Query(12, ge=1, le=60), min_hits: int = Query(3, ge=1, le=100), p: Principal = Depends(require(READ_SPEND))):
    with uow(p) as s:
        return spend_workflow.repeat_offenders(s, months, min_hits)


@router.get("/spend/maverick-rules")
def maverick_rules(on: Optional[date] = None, p: Principal = Depends(OPERATE)):
    """The nine rules as in force on a date, with their effective-dated versions and hit counts."""
    with uow(p) as s:
        return {"rules": spend_workflow.rules_view(s, on), "reasonCodes": list(spend.REASON_CODES), "dispositions": list(spend.DISPOSITIONS)}


class RuleVersionIn(BaseModel):
    effective_from: date
    reason: str = Field(min_length=5, max_length=500)
    active: Optional[bool] = None
    severity: Optional[str] = Field(default=None, pattern="^(Critical|High|Medium|Low)$")
    owner_role: Optional[str] = Field(default=None, max_length=40)
    sla_days: Optional[int] = Field(default=None, ge=1, le=90)
    escalate_role: Optional[str] = Field(default=None, max_length=40)


@router.post("/spend/maverick-rules/{code}/versions", status_code=201)
def maverick_rule_version(code: str, body: RuleVersionIn, p: Principal = Depends(require("admin:rules"))):
    """A new effective-dated version of one maverick rule (active, severity, owner role, SLA, escalation role)."""
    with uow(p) as s:
        return spend_workflow.set_rule_version(s, code.upper(), effective_from=body.effective_from, reason=body.reason, active=body.active, severity=body.severity,
                                               owner_role=body.owner_role, sla_days=body.sla_days, escalate_role=body.escalate_role)


class RecoveryIn(BaseModel):
    recovered_minor: int = Field(ge=0)
    note: str = Field(min_length=5, max_length=2000)


@router.post("/spend/maverick-hits/{hit_id}/resolve")
def resolve_hit(hit_id: uuid.UUID, body: RecoveryIn, p: Principal = Depends(require(READ_SPEND))):
    """Close a hit that was dispositioned RECOVERY, with the amount recovered."""
    with uow(p) as s:
        return row(spend.resolve_recovery(s, _get(s, MaverickHit, hit_id, "Maverick hit"), body.recovered_minor, body.note))


@router.post("/spend/maverick/escalate")
def maverick_escalate(p: Principal = Depends(require("admin:integration"))):
    """Escalate the hits past their SLA now (the hourly job does the same)."""
    with uow(p) as s:
        hits = spend.escalate_overdue(s)
        return {"escalated": [{"number": h.number, "level": h.escalation_level, "to": h.escalated_to_role} for h in hits]}


# ---------------------------------------------------------------- supplier duplicates
@router.get("/spend/duplicates")
def duplicates(p: Principal = Depends(STEWARD)):
    with uow(p) as s:
        periods = spend._window(s, 12)
        C = spend_cube.C
        spent = {sid: int(v or 0) for sid, v in s.execute(select(C.supplier_id, spend.func.sum(C.amount_group_minor)).where(
            C.period.between(periods[0], periods[-1]), *spend_scope.where(s, C)).group_by(C.supplier_id))}
        return {"clusters": spend_workflow.duplicate_clusters(s, spent), "window": [periods[0], periods[-1]]}


@router.post("/spend/duplicates/scan")
def duplicates_scan(p: Principal = Depends(STEWARD)):
    with uow(p) as s:
        return spend_workflow.scan_duplicates(s)


class MergeIn(BaseModel):
    survivor: str = Field(max_length=30)
    note: str = Field(min_length=5, max_length=2000)


class DismissIn(BaseModel):
    note: str = Field(min_length=5, max_length=2000)


@router.post("/spend/duplicates/{cluster_key}/propose-merge", status_code=201)
def duplicates_propose(cluster_key: str, body: MergeIn, p: Principal = Depends(STEWARD)):
    """Propose treating the cluster as one supplier group under the survivor; a second steward approves it in the task inbox (nothing is merged)."""
    with uow(p) as s:
        return row(spend_workflow.propose_merge(s, cluster_key, body.survivor, body.note))


@router.post("/spend/duplicates/{cluster_key}/dismiss")
def duplicates_dismiss(cluster_key: str, body: DismissIn, p: Principal = Depends(STEWARD)):
    with uow(p) as s:
        return row(spend_workflow.dismiss_cluster(s, cluster_key, body.note))


# ---------------------------------------------------------------- category plans
class PlanPatch(BaseModel):
    budget_minor: Optional[int] = Field(default=None, ge=0)
    savings_target_minor: Optional[int] = Field(default=None, ge=0)
    levers: Optional[list[str]] = Field(default=None, max_length=12)
    wave_plan: Optional[list[dict]] = Field(default=None, max_length=24)
    savings_by_lever: Optional[dict[str, int]] = None


class PlanComment(BaseModel):
    comment: Optional[str] = Field(default=None, max_length=2000)


class PlanReject(BaseModel):
    comment: str = Field(min_length=5, max_length=2000)


@router.get("/category-plans/{ref}")
def category_plan(ref: str, p: Principal = Depends(require(READ_SPEND))):
    with uow(p) as s:
        plan = spend.get_plan(s, ref)
        history = s.execute(select(CategoryPlan).where(CategoryPlan.category == plan.category, CategoryPlan.fiscal_year == plan.fiscal_year)
                            .order_by(CategoryPlan.version)).scalars().all()
        return {**row(plan), "validation": spend_workflow.validate_plan(s, plan), "leverCatalogue": spend_workflow.LEVER_CATALOGUE,
                "versions": [{"number": v.number, "version": v.version, "status": v.status} for v in history]}


@router.patch("/category-plans/{ref}")
def update_category_plan(ref: str, body: PlanPatch, p: Principal = Depends(require(READ_SPEND))):
    with uow(p) as s:
        return row(spend_workflow.update_plan(s, spend.get_plan(s, ref), **body.model_dump(exclude_unset=True)))


@router.post("/category-plans/{ref}/submit")
def submit_category_plan(ref: str, body: PlanComment, p: Principal = Depends(require(READ_SPEND))):
    with uow(p) as s:
        return row(spend_workflow.submit_plan(s, spend.get_plan(s, ref), body.comment))


@router.post("/category-plans/{ref}/reject")
def reject_category_plan(ref: str, body: PlanReject, p: Principal = Depends(require(READ_SPEND))):
    with uow(p) as s:
        return row(spend_workflow.reject_plan(s, spend.get_plan(s, ref), body.comment))


@router.post("/category-plans/{ref}/revise", status_code=201)
def revise_category_plan(ref: str, body: PlanReject, p: Principal = Depends(require(READ_SPEND))):
    with uow(p) as s:
        return row(spend_workflow.revise_plan(s, spend.get_plan(s, ref), body.comment))


@router.get("/category-plans/{ref}/pipeline-links")
def category_plan_links(ref: str, p: Principal = Depends(require(READ_SPEND))):
    """Sourcing events and savings initiatives of the plan's category, by reference."""
    with uow(p) as s:
        return spend_workflow.pipeline_links(s, spend.get_plan(s, ref))


# ---------------------------------------------------------------- administration
class ReevaluateIn(BaseModel):
    note: str = Field(min_length=5, max_length=500)


@router.post("/admin/spend/reevaluate")
def reevaluate(body: ReevaluateIn, p: Principal = Depends(require("admin:integration"))):
    """Classify and evaluate the spend lines that were not processed yet (new rules, new taxonomy words); idempotent."""
    with uow(p) as s:
        result = spend.refresh(s, p.tenant_id)
        audit.record(s, "SPEND_CUBE", p.tenant_id, "REEVALUATED", object_ref="spend_line", after=result, reason=body.note)
        return result
