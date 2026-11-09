"""F3 sourcing, F4 contracts, M11 savings and M01 spend."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.pic import views
from app.pic.api.deps import idempotency_key, idempotent, uow
from app.pic.models import Contract, Obligation, SavingsInitiative, SourcingEvent, Supplier
from app.pic.platform.auth import READ, Principal, require, require_any
from app.pic.platform.core import check_if_match, etag
from app.pic.platform.errors import Problem, not_found
from app.pic.platform.serialize import row, rows
from app.pic.services import contract as contract_svc
from app.pic.services import savings, should_cost, sourcing, sourcing_analysis, sourcing_templates
from app.pic.services.common import by_ref

router = APIRouter(prefix="/v1")


# ---------------------------------------------------------------- F3 sourcing
class SourceIn(BaseModel):
    requisition: str
    line: int
    qty: Optional[Decimal] = Field(default=None, gt=0)


class EventLineIn(BaseModel):
    requisition: Optional[str] = None  # one requirement line ...
    line: Optional[int] = None
    sources: Optional[list[SourceIn]] = None  # ... or several merged into one event line (requirement bundling)
    annual_qty: Decimal = Field(gt=0)
    monthly_qty: Decimal = Field(gt=0)
    lot: Optional[str] = Field(default=None, max_length=20)  # lines with the same lot code can be bid and awarded as a bundle
    baseline_price_minor: Optional[int] = Field(default=None, ge=0)


class CriterionIn(BaseModel):
    code: str
    name: str
    weight: int = Field(ge=0, le=100)
    data_source: Optional[str] = Field(default=None, pattern="^(MANUAL|SCORECARD|ESG|RISK)$")  # score taken from platform data at close
    min_score: Optional[Decimal] = Field(default=None, ge=0, le=100)  # technical gate: a bid below it on this criterion is not awardable


class BundleIn(BaseModel):
    kind: str = Field(default="PR_LINES", pattern="^(PR_LINES|MRP_DEMAND|CATEGORY_PLAN)$")
    ref: Optional[str] = None


class InviteeIn(BaseModel):
    supplier: str
    waiver_reason: Optional[str] = None


class ShouldCostModelRef(BaseModel):
    code: str
    inputs: dict = Field(default_factory=dict)


class EventIn(BaseModel):
    type: str = Field(pattern="^(RFI|RFQ|RFP|REVERSE_AUCTION)$")
    title: str
    category: str
    lines: list[EventLineIn] = Field(min_length=1, max_length=50)
    criteria: list[CriterionIn]
    invitees: list[InviteeIn]
    close_at: datetime
    baseline_method: str = Field(default="LAST_PRICE", pattern="^(LAST_PRICE|WEIGHTED_AVG|SHOULD_COST|MARKET_INDEX|BUDGET|MANUAL)$")
    baseline_price_minor: Optional[int] = Field(default=None, ge=0)
    should_cost_params: Optional[dict] = None
    should_cost_model: Optional[ShouldCostModelRef] = None
    constraints: Optional[dict] = None
    tco_params: Optional[dict] = None
    savings_target_pct: Optional[Decimal] = Field(default=None, ge=0, le=100)
    bundle: Optional[BundleIn] = None
    scoring_method: str = Field(default="LOWEST_RATIO", pattern="^(LOWEST_RATIO|MIN_MAX|RANK)$")
    reference_date: Optional[date] = None
    clarification_close_at: Optional[datetime] = None
    open_at: Optional[datetime] = None  # scheduled opening: published and visible now, bids accepted from this time
    budget_justification: Optional[str] = Field(default=None, max_length=2000)
    min_bidders: Optional[int] = Field(default=None, ge=1, le=20)


def _event(s, ref: str, if_match: Optional[str] = None, lock: bool = True) -> SourcingEvent:
    """The event by number or id; with If-Match the command is refused (412) when the event changed since the client read it."""
    event = by_ref(s, SourcingEvent, ref, lock=lock)
    check_if_match(event, if_match)
    return event


def _command(p: Principal, scope: str, key: Optional[str], body, work, status: int = 200):
    """One idempotent command in its own tenant transaction: a replay of the same Idempotency-Key returns the first answer."""
    with uow(p) as s:
        idem = idempotent(s, scope, key, body)
        if idem.replay:
            return idem.replay
        return idem.store(work(s), status)


@router.post("/sourcing/events", status_code=201, tags=["F3 Sourcing"])
def create_event(body: EventIn, p: Principal = Depends(require("sourcing:manage")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/sourcing/events", key, body)
        if idem.replay:
            return idem.replay
        data = body.model_dump()
        data["lines"] = [l for l in data["lines"]]
        data["criteria"] = [{**c, "min_score": str(c["min_score"]) if c.get("min_score") is not None else None} for c in data["criteria"]]
        event = sourcing.create_event(s, **data)
        return idem.store(views.sourcing_event(s, event), 201)


@router.post("/sourcing/events/{ref}/publish", tags=["F3 Sourcing"])
def publish_event(ref: str, p: Principal = Depends(require("sourcing:manage")), key: Optional[str] = Depends(idempotency_key),
                  if_match: Optional[str] = Header(default=None, alias="If-Match")):
    return _command(p, f"POST /v1/sourcing/events/{ref}/publish", key, {}, lambda s: views.sourcing_event(s, sourcing.publish(s, _event(s, ref, if_match))))


class BidLineIn(BaseModel):
    line: int
    unit_price: Decimal = Field(gt=0)
    freight: Optional[Decimal] = Field(default=None, ge=0)  # not quoted (null): estimated from the incoterm by the TCO rule, or assumed included
    duty: Optional[Decimal] = Field(default=None, ge=0)
    packaging: Optional[Decimal] = Field(default=None, ge=0)
    payment_terms_days: int = Field(ge=0)
    lead_time_days: int = Field(ge=0)
    capacity_per_month: Optional[Decimal] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)  # quoted currency (default INR); converted at the event's reference date
    incoterm: Optional[str] = Field(default=None, max_length=10)
    origin: Optional[str] = Field(default=None, pattern="^(DOMESTIC|IMPORT)$")
    moq: Optional[Decimal] = Field(default=None, ge=0)  # minimum order quantity per month at this price
    price_uom: Optional[str] = Field(default=None, max_length=5)
    uom_factor: Optional[Decimal] = Field(default=None, gt=0)  # base units in one unit of the quoted price
    tax_included: bool = False
    tax_rate_pct: Optional[Decimal] = Field(default=None, ge=0, le=50)
    hs_code: Optional[str] = Field(default=None, max_length=10)


class BidLotIn(BaseModel):
    lot: str
    discount_pct: Decimal = Field(default=Decimal(0), ge=0, lt=100)  # applies when the supplier is awarded the whole lot
    all_or_nothing: bool = False  # the supplier accepts the lot only as a whole


class BidIn(BaseModel):
    lines: list[BidLineIn] = Field(min_length=1)  # a price for every event line of a single-line event; partial bids allowed on several lines
    lots: list[BidLotIn] = []
    valid_until: Optional[date] = None  # the offer is valid until this date (after the close)


def _bid_lines(lines) -> list[dict]:
    return [{k: v for k, v in l.model_dump(mode="json").items() if v is not None} for l in lines]


@router.post("/sourcing/events/{ref}/bids", status_code=201, tags=["F3 Sourcing"])
def submit_bid(ref: str, body: BidIn, p: Principal = Depends(require("bid:submit")), key: Optional[str] = Depends(idempotency_key)):
    """The supplier's sealed bid. Submitting again before the close replaces it; a withdrawn bid can be submitted again."""
    def work(s):
        event = by_ref(s, SourcingEvent, ref, lock=True)
        bid = sourcing.submit_bid(s, event, s.get(Supplier, p.supplier_id), _bid_lines(body.lines), [l.model_dump(mode="json") for l in body.lots],
                                  valid_until=body.valid_until)
        return {"event": event.number, "round": bid.round, "status": bid.status, "hash": bid.payload_hash, "edits": bid.edits,
                "submittedAt": bid.submitted_at.isoformat()}
    return _command(p, f"POST /v1/sourcing/events/{ref}/bids", key, body, work, 201)


class WithdrawBidIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/sourcing/events/{ref}/bids/withdraw", tags=["F3 Sourcing"])
def withdraw_bid(ref: str, body: WithdrawBidIn, p: Principal = Depends(require("bid:submit")), key: Optional[str] = Depends(idempotency_key)):
    """The supplier withdraws its sealed bid before the close; the content is destroyed unread."""
    def work(s):
        event = by_ref(s, SourcingEvent, ref, lock=True)
        bid = sourcing.withdraw_bid(s, event, s.get(Supplier, p.supplier_id), body.reason)
        return {"event": event.number, "round": bid.round, "status": bid.status, "withdrawnAt": bid.withdrawn_at.isoformat()}
    return _command(p, f"POST /v1/sourcing/events/{ref}/bids/withdraw", key, body, work)


@router.get("/sourcing/events/{ref}/bids", tags=["F3 Sourcing"])
def view_bids(ref: str, p: Principal = Depends(require("sourcing:manage"))):
    with uow(p) as s:
        return sourcing.bids_view(s, by_ref(s, SourcingEvent, ref))


@router.get("/sourcing/events/{ref}/line-matrix", tags=["F3 Sourcing"])
def line_matrix(ref: str, p: Principal = Depends(require("sourcing:manage"))):
    """Per event line: every bid on the line ranked by TCO (after close)."""
    with uow(p) as s:
        event = by_ref(s, SourcingEvent, ref)
        sourcing.bids_view(s, event)  # sealed until close, the attempt is logged
        return sourcing.line_matrix(s, event)


@router.get("/sourcing/events/{ref}/comparison", tags=["F3 Sourcing"])
def comparison(ref: str, p: Principal = Depends(require("sourcing:manage"))):
    """SRC-03: the normalised comparison (TCO stack with its trace, scores, ranking, should-cost and benchmark band) with the outlier and collusion
    screens. Before the opening it is refused (423) and the attempt is logged."""
    with uow(p) as s:
        return sourcing_analysis.comparison(s, by_ref(s, SourcingEvent, ref))


@router.get("/sourcing/events/{ref}/comparison.csv", tags=["F3 Sourcing"])
def comparison_csv(ref: str, p: Principal = Depends(require("sourcing:manage"))):
    """The comparison matrix as CSV; the SHA-256 is in the X-Content-SHA256 header and in the audit trail. Only after the opening."""
    with uow(p) as s:
        out = sourcing_analysis.export_csv(s, by_ref(s, SourcingEvent, ref))
    return Response(content=out["content"], media_type=out["contentType"],
                    headers={"Content-Disposition": f'attachment; filename="{out["filename"]}"', "X-Content-SHA256": out["sha256"], "X-Rows": str(out["rows"])})


@router.post("/sourcing/events/{ref}/close", tags=["F3 Sourcing"])
def close_event(ref: str, p: Principal = Depends(require("sourcing:manage")), key: Optional[str] = Depends(idempotency_key),
                if_match: Optional[str] = Header(default=None, alias="If-Match")):
    return _command(p, f"POST /v1/sourcing/events/{ref}/close", key, {}, lambda s: sourcing.close(s, _event(s, ref, if_match)))


@router.post("/sourcing/events/{ref}/open", tags=["F3 Sourcing"])
def open_bids(ref: str, p: Principal = Depends(require("sourcing:manage")), key: Optional[str] = Depends(idempotency_key)):
    """Bid opening ceremony (two-person rule): each different person opens once; the second opening unseals the bids."""
    return _command(p, f"POST /v1/sourcing/events/{ref}/open", key, {}, lambda s: sourcing.open_bids(s, _event(s, ref)))


class ScoreIn(BaseModel):
    supplier: str
    criterion: str
    score: Decimal = Field(ge=0, le=100)
    comment: Optional[str] = None


@router.post("/sourcing/events/{ref}/scores", tags=["F3 Sourcing"])
def score_bids(ref: str, body: list[ScoreIn], p: Principal = Depends(require_any("sourcing:evaluate")), key: Optional[str] = Depends(idempotency_key)):
    return _command(p, f"POST /v1/sourcing/events/{ref}/scores", key, {"scores": [b.model_dump(mode="json") for b in body]},
                    lambda s: sourcing.score(s, _event(s, ref, lock=False), [b.model_dump(mode="json") for b in body]))


class DeclarationIn(BaseModel):
    has_conflict: bool
    declaration: str = Field(min_length=10, max_length=2000)


@router.post("/sourcing/events/{ref}/declarations", status_code=201, tags=["F3 Sourcing"])
def declare_conflict(ref: str, body: DeclarationIn, p: Principal = Depends(require_any("sourcing:evaluate", "sourcing:manage")),
                     key: Optional[str] = Depends(idempotency_key)):
    """The evaluator's conflict-of-interest declaration; required before scoring. Declaring a conflict bars the user from scoring and from the award."""
    def work(s):
        d = sourcing.declare_conflict(s, _event(s, ref, lock=False), body.has_conflict, body.declaration)
        return {"user": p.email, "hasConflict": d.has_conflict, "declaredAt": d.declared_at.isoformat()}
    return _command(p, f"POST /v1/sourcing/events/{ref}/declarations", key, body, work, 201)


@router.get("/sourcing/events/{ref}/evaluators", tags=["F3 Sourcing"])
def evaluators(ref: str, p: Principal = Depends(require("sourcing:manage"))):
    """Who declared what, and who scored what (counts), so the owner sees whether the evaluation team is complete."""
    from sqlalchemy import func, select as sa_select
    from app.pic.models import AppUser, Evaluation, EvaluatorDeclaration
    with uow(p) as s:
        event = by_ref(s, SourcingEvent, ref)
        names = {u.id: u.email for u in s.execute(sa_select(AppUser)).scalars()}
        scored = dict(s.execute(sa_select(Evaluation.evaluator_id, func.count()).where(Evaluation.event_id == event.id).group_by(Evaluation.evaluator_id)).all())
        return [{"user": names.get(d.user_id), "hasConflict": d.has_conflict, "declaration": d.declaration, "declaredAt": d.declared_at.isoformat(),
                 "scores": scored.get(d.user_id, 0)}
                for d in s.execute(sa_select(EvaluatorDeclaration).where(EvaluatorDeclaration.event_id == event.id)).scalars()]


class DisqualifyIn(BaseModel):
    supplier: str
    reason: str = Field(min_length=10, max_length=2000)


@router.post("/sourcing/events/{ref}/disqualify", tags=["F3 Sourcing"])
def disqualify(ref: str, body: DisqualifyIn, p: Principal = Depends(require("sourcing:manage")), key: Optional[str] = Depends(idempotency_key),
               if_match: Optional[str] = Header(default=None, alias="If-Match")):
    """Take a bidder out of the evaluation with a written reason; scenarios built on its bid are marked stale."""
    def work(s):
        from app.pic.services.common import supplier_by_code
        bid = sourcing.disqualify(s, _event(s, ref, if_match), supplier_by_code(s, body.supplier), body.reason)
        return {"event": ref, "supplier": body.supplier, "status": bid.status, "at": bid.disqualified_at.isoformat()}
    return _command(p, f"POST /v1/sourcing/events/{ref}/disqualify", key, body, work)


class RoundIn(BaseModel):
    close_at: datetime
    note: str = ""


@router.post("/sourcing/events/{ref}/rounds", tags=["F3 Sourcing"])
def new_round(ref: str, body: RoundIn, p: Principal = Depends(require("sourcing:manage")), key: Optional[str] = Depends(idempotency_key),
              if_match: Optional[str] = Header(default=None, alias="If-Match")):
    return _command(p, f"POST /v1/sourcing/events/{ref}/rounds", key, body,
                    lambda s: views.sourcing_event(s, sourcing.new_round(s, _event(s, ref, if_match), body.close_at, body.note)))


class ExtendIn(BaseModel):
    close_at: datetime
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/sourcing/events/{ref}/extend", tags=["F3 Sourcing"])
def extend_deadline(ref: str, body: ExtendIn, p: Principal = Depends(require("sourcing:manage")), key: Optional[str] = Depends(idempotency_key),
                    if_match: Optional[str] = Header(default=None, alias="If-Match")):
    """Move the bid deadline of a published / open event later; every invited supplier is notified (flow fixes F3)."""
    return _command(p, f"POST /v1/sourcing/events/{ref}/extend", key, body,
                    lambda s: views.sourcing_event(s, sourcing.extend_deadline(s, _event(s, ref, if_match), body.close_at, body.reason)))


@router.post("/sourcing/events/{ref}/scenarios", tags=["F3 Sourcing"])
def scenarios(ref: str, p: Principal = Depends(require("sourcing:manage")), key: Optional[str] = Depends(idempotency_key)):
    return _command(p, f"POST /v1/sourcing/events/{ref}/scenarios", key, {}, lambda s: sourcing.build_scenarios(s, _event(s, ref)))


class SplitEntryIn(BaseModel):
    supplier: str
    line: Optional[int] = None  # the event line (required on a several-line event)
    share_pct: Optional[Decimal] = Field(default=None, gt=0, le=100)
    qty_per_month: Optional[Decimal] = Field(default=None, gt=0)


class CustomScenarioIn(BaseModel):
    allocations: list[SplitEntryIn] = Field(min_length=1)


@router.post("/sourcing/events/{ref}/scenarios/custom", status_code=201, tags=["F3 Sourcing"])
def custom_scenario(ref: str, body: CustomScenarioIn, p: Principal = Depends(require("sourcing:manage")), key: Optional[str] = Depends(idempotency_key)):
    """SRC-04: a manual split by percentage or quantity per supplier (and line), checked against capacity, MOQ, share bounds and risk caps."""
    return _command(p, f"POST /v1/sourcing/events/{ref}/scenarios/custom", key, body,
                    lambda s: sourcing.custom_scenario(s, _event(s, ref), [a.model_dump(mode="json", exclude_none=True) for a in body.allocations]), 201)


class AwardIn(BaseModel):
    scenario_id: uuid.UUID
    rationale: Optional[str] = None
    conflict_declaration: str
    # D5: an award on an expired offer is refused (409 BID_OFFER_EXPIRED) unless a user allowed by SOURCING-POLICY.expiredOfferOverride
    # (default: a category manager of the event's category) gives the written reason here (default at least 20 characters)
    expired_offer_override: Optional[str] = Field(default=None, max_length=2000)


@router.post("/sourcing/events/{ref}/award", tags=["F3 Sourcing"])
def award(ref: str, body: AwardIn, p: Principal = Depends(require("sourcing:manage")), key: Optional[str] = Depends(idempotency_key),
          if_match: Optional[str] = Header(default=None, alias="If-Match")):
    def work(s):
        event = _event(s, ref, if_match)
        sourcing.propose_award(s, event, body.scenario_id, body.rationale, body.conflict_declaration, body.expired_offer_override)
        return views.sourcing_event(s, event)
    return _command(p, f"POST /v1/sourcing/events/{ref}/award", key, body, work)


class EventCancelIn(BaseModel):
    reason: str = ""


@router.post("/sourcing/events/{ref}/cancel", tags=["F3 Sourcing"])
def cancel_event(ref: str, body: EventCancelIn, p: Principal = Depends(require("sourcing:manage")),
                 key: Optional[str] = Depends(idempotency_key), if_match: Optional[str] = Header(default=None, alias="If-Match")):
    """Cancel an event that is not awarded yet; invited suppliers are notified and see it as cancelled in the portal."""
    def work(s):
        event = _event(s, ref, if_match)
        sourcing.cancel(s, event, body.reason)
        return views.sourcing_event(s, event)
    return _command(p, f"POST /v1/sourcing/events/{ref}/cancel", key, body, work)


@router.get("/sourcing/events/{ref}/handoff", tags=["F3 Sourcing"])
def handoff(ref: str, p: Principal = Depends(require(READ))):
    """What the award produced: contracts and their price publication, quota arrangement with counters, source list, PO release eligibility."""
    with uow(p) as s:
        return sourcing_analysis.handoff(s, by_ref(s, SourcingEvent, ref))


@router.get("/sourcing/events/{ref}/history", tags=["F3 Sourcing"])
def history(ref: str, p: Principal = Depends(require("sourcing:manage"))):
    """The event's audit trail (who did what when, with the rule versions), oldest first."""
    with uow(p) as s:
        return sourcing_analysis.history(s, by_ref(s, SourcingEvent, ref))


@router.get("/sourcing/pipeline", tags=["F3 Sourcing"])
def pipeline(category: Optional[str] = None, p: Principal = Depends(require("sourcing:manage"))):
    """SRC-01: events per stage with value, age and next step."""
    with uow(p) as s:
        return sourcing_analysis.pipeline(s, category)


class CloneIn(BaseModel):
    close_at: datetime
    title: Optional[str] = Field(default=None, max_length=200)
    lines: Optional[list[EventLineIn]] = None


@router.post("/sourcing/events/{ref}/clone", status_code=201, tags=["F3 Sourcing"])
def clone_event(ref: str, body: CloneIn, p: Principal = Depends(require("sourcing:manage")), key: Optional[str] = Depends(idempotency_key)):
    """A Draft copy of an event (criteria, constraints, TCO parameters, eligible invitees); a re-tender after a cancellation or the next round of a contract."""
    return _command(p, f"POST /v1/sourcing/events/{ref}/clone", key, body, lambda s: sourcing_templates.clone(
        s, by_ref(s, SourcingEvent, ref), close_at=body.close_at, title=body.title,
        lines=[l.model_dump(mode="json", exclude_none=True) for l in body.lines] if body.lines else None), 201)


class TemplateIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=120)
    event_type: str = Field(pattern="^(RFI|RFQ|RFP|REVERSE_AUCTION)$")
    category: Optional[str] = None
    payload: dict


@router.get("/sourcing/templates", tags=["F3 Sourcing"])
def templates(category: Optional[str] = None, p: Principal = Depends(require("sourcing:manage"))):
    with uow(p) as s:
        return sourcing_templates.listing(s, category)


@router.post("/sourcing/templates", status_code=201, tags=["F3 Sourcing"])
def save_template(body: TemplateIn, p: Principal = Depends(require("sourcing:manage")), key: Optional[str] = Depends(idempotency_key)):
    def work(s):
        t = sourcing_templates.save(s, code=body.code, name=body.name, event_type=body.event_type, category=body.category, payload=body.payload)
        return {"code": t.code, "name": t.name, "eventType": t.event_type, "category": t.category, "payload": t.payload}
    return _command(p, "POST /v1/sourcing/templates", key, body, work, 201)


class FromTemplateIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    category: Optional[str] = None
    lines: list[EventLineIn] = Field(min_length=1, max_length=50)
    close_at: datetime
    invitees: Optional[list[InviteeIn]] = None  # none: the template's invitation filter picks the qualified suppliers
    # what the template does not fix: validated by the normal create path
    open_at: Optional[datetime] = None
    clarification_close_at: Optional[datetime] = None
    reference_date: Optional[date] = None
    min_bidders: Optional[int] = Field(default=None, ge=1, le=20)
    budget_justification: Optional[str] = Field(default=None, max_length=2000)
    should_cost_model: Optional[ShouldCostModelRef] = None
    baseline_method: Optional[str] = Field(default=None, pattern="^(LAST_PRICE|WEIGHTED_AVG|SHOULD_COST|MARKET_INDEX|BUDGET|MANUAL)$")
    baseline_price_minor: Optional[int] = Field(default=None, ge=0)


@router.post("/sourcing/templates/{code}/events", status_code=201, tags=["F3 Sourcing"])
def event_from_template(code: str, body: FromTemplateIn, p: Principal = Depends(require("sourcing:manage")), key: Optional[str] = Depends(idempotency_key)):
    def work(s):
        data = body.model_dump(mode="json", exclude_none=True)
        extra = {k: data[k] for k in ("min_bidders", "budget_justification", "should_cost_model", "baseline_method", "baseline_price_minor") if k in data}
        extra.update({k: getattr(body, k) for k in ("open_at", "clarification_close_at", "reference_date") if getattr(body, k) is not None})
        event = sourcing_templates.create_from_template(s, code, title=data["title"], category=data.get("category"), lines=data["lines"],
                                                        close_at=body.close_at, invitees=data.get("invitees"), **extra)
        return views.sourcing_event(s, event)
    return _command(p, f"POST /v1/sourcing/templates/{code}/events", key, body, work, 201)


class ShouldCostModelIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    commodity: str = Field(min_length=2, max_length=40)
    title: str = Field(min_length=3, max_length=200)
    spec: dict
    index_code: Optional[str] = Field(default=None, max_length=30)
    note: Optional[str] = None


@router.get("/sourcing/should-cost/models", tags=["F3 Sourcing"])
def should_cost_models(p: Principal = Depends(require("sourcing:manage"))):
    from sqlalchemy import select as sa_select
    from app.pic.models import ShouldCostModel
    with uow(p) as s:
        latest: dict = {}
        for m in s.execute(sa_select(ShouldCostModel).order_by(ShouldCostModel.code, ShouldCostModel.version)).scalars():
            latest[m.code] = m
        return [{"code": m.code, "version": m.version, "commodity": m.commodity, "title": m.title, "indexCode": m.index_code, "spec": m.spec, "note": m.note}
                for m in latest.values()]


@router.post("/sourcing/should-cost/models", status_code=201, tags=["F3 Sourcing"])
def save_should_cost_model(body: ShouldCostModelIn, p: Principal = Depends(require("sourcing:manage")), key: Optional[str] = Depends(idempotency_key)):
    """A new version of a commodity should-cost model (never an edit): cost components, margin and the index its material rates follow."""
    def work(s):
        m = should_cost.save_model(s, code=body.code, commodity=body.commodity, title=body.title, spec=body.spec, index_code=body.index_code, note=body.note)
        return {"code": m.code, "version": m.version, "commodity": m.commodity, "title": m.title}
    return _command(p, "POST /v1/sourcing/should-cost/models", key, body, work, 201)


class ShouldCostEvaluateIn(BaseModel):
    code: str
    inputs: dict
    on: Optional[date] = None


@router.post("/sourcing/should-cost/evaluate", tags=["F3 Sourcing"])
def evaluate_should_cost(body: ShouldCostEvaluateIn, p: Principal = Depends(require("sourcing:manage"))):
    with uow(p) as s:
        return should_cost.evaluate(s, body.code, body.inputs, body.on)


class BenchmarkIn(BaseModel):
    category: str
    material: Optional[str] = None
    kind: str = Field(pattern="^(MARKET|PEER|CATALOGUE)$")
    as_of: date
    price_minor: int = Field(gt=0)
    uom: str = Field(max_length=5)
    source: str = Field(min_length=2, max_length=80)
    note: Optional[str] = None


@router.post("/sourcing/benchmarks", status_code=201, tags=["F3 Sourcing"])
def record_benchmark(body: BenchmarkIn, p: Principal = Depends(require("sourcing:manage")), key: Optional[str] = Depends(idempotency_key)):
    def work(s):
        from sqlalchemy import select as sa_select
        from app.pic.db import current_tenant
        from app.pic.models import Material, PriceBenchmark
        material = s.execute(sa_select(Material).where(Material.number == body.material)).scalar_one_or_none() if body.material else None
        if body.material and material is None:
            raise not_found("Material", body.material)
        row = PriceBenchmark(tenant_id=current_tenant(s), category=body.category, material_id=material.id if material else None, kind=body.kind, as_of=body.as_of,
                             price_minor=body.price_minor, uom=body.uom, source=body.source, note=body.note, created_by=p.user_id)
        s.add(row)
        s.flush()
        return {"id": str(row.id), "category": row.category, "kind": row.kind, "asOf": row.as_of.isoformat(), "priceMinor": row.price_minor}
    return _command(p, "POST /v1/sourcing/benchmarks", key, body, work, 201)


@router.get("/sourcing/benchmarks", tags=["F3 Sourcing"])
def benchmarks(category: str, material: Optional[str] = None, on: Optional[date] = None, p: Principal = Depends(require("sourcing:manage"))):
    """Every reference price PIC holds for the item (last price, 12-month weighted average, market, peer) and the band they span."""
    from sqlalchemy import select as sa_select
    from app.pic.models import Material
    with uow(p) as s:
        item = s.execute(sa_select(Material).where(Material.number == material)).scalar_one_or_none() if material else None
        if material and item is None:
            raise not_found("Material", material)
        return should_cost.benchmark_band(s, item, category, on)


class TcoSimulateIn(BaseModel):
    supplier: str
    category: str
    material: Optional[str] = None
    line: BidLineIn
    annual_qty: Optional[Decimal] = Field(default=None, gt=0)
    on: Optional[date] = None
    tco_params: Optional[dict] = None


@router.post("/sourcing/tco/simulate", tags=["F3 Sourcing"])
def simulate_tco(body: TcoSimulateIn, p: Principal = Depends(require("sourcing:manage"))):
    """What-if: the TCO stack and trace of a bid line under the tenant's SOURCING-TCO rule (or the given parameters), before an event exists."""
    with uow(p) as s:
        return sourcing_analysis.simulate_tco(s, body.model_dump(mode="json", exclude_none=True))


@router.get("/sourcing/events/{ref}", tags=["F3 Sourcing"])
def get_event(ref: str, response: Response, p: Principal = Depends(require_any(READ, "supplier:portal"))):
    with uow(p) as s:
        event = by_ref(s, SourcingEvent, ref)
        response.headers["ETag"] = etag(event)  # send it back as If-Match on publish / close / rounds / award / cancel / disqualify
        view = views.sourcing_event(s, event)
        if "SUPPLIER_USER" not in p.roles:
            view["policy"] = sourcing.policy_summary(s, event)  # limits and award rules the screens show; a supplier never sees the price band
        if "SUPPLIER_USER" in p.roles:
            mine = s.get(Supplier, p.supplier_id)
            # never published (a draft, or a draft cancelled before publishing): invisible to suppliers
            if event.status == "DRAFT" or event.published_at is None or mine.code not in {i["code"] for i in view["invitees"]}:
                raise not_found("Sourcing event", ref)
            # Suppliers see the requirement and their own bid status, not competitors, scores or award scenarios.
            view = {k: v for k, v in view.items() if k not in ("invitees", "scenarios", "awardDecisions", "lineage", "process", "should_cost",
                                                              "baseline_price_minor", "constraints", "tco_params", "bundle", "budget_check",
                                                              "budget_justification", "opening", "rule_versions", "min_bidders", "competitive",
                                                              "template_code", "cloned_from", "baseline_method")}
            # nor the buyer's savings target or internal users
            view = {k: v for k, v in view.items() if k not in ("savings_target_pct", "owner_id", "created_by", "updated_by")}
            view["bids"] = [b for b in view["bids"] if b["supplier"] == mine.code]
        return view


# ---------------------------------------------------------------- F4 contracts
@router.get("/contracts/{ref}", tags=["F4 Contract"])
def get_contract(ref: str, p: Principal = Depends(require_any(READ, "supplier:portal"))):
    with uow(p) as s:
        contract = by_ref(s, Contract, ref)
        # a draft is internal work: the supplier meets the contract when it enters negotiation
        if "SUPPLIER_USER" in p.roles and (contract.supplier_id != p.supplier_id or contract.status == "DRAFT"):
            raise not_found("Contract", ref)
        view = views.contract(s, contract)
        if "SUPPLIER_USER" in p.roles:
            # The internal approval history (tasks, approvers, comments), lineage and rule versions stay internal.
            view = {k: v for k, v in view.items() if k not in ("process", "lineage", "rule_set_version", "owner_id", "created_by", "updated_by")}
        return view


@router.post("/contracts/{ref}/review", tags=["F4 Contract"])
def review_contract(ref: str, p: Principal = Depends(require("contract:manage"))):
    with uow(p) as s:
        return contract_svc.ai_review(s, by_ref(s, Contract, ref, lock=True))


@router.get("/contracts/{ref}/clause-review", tags=["F4 Contract"])
def clause_review(ref: str, p: Principal = Depends(require(READ))):
    """CLM-02: each clause against the playbook (standard wording, deviation, risk score, fallback suggestion), the supplier redlines
    waiting for review and the approval route the contract would take."""
    with uow(p) as s:
        return contract_svc.clause_review(s, by_ref(s, Contract, ref))


class RedlineIn(BaseModel):
    clause: str
    text: str = Field(min_length=1)
    # The buyer classifies its own redline; a supplier redline is always NON_STANDARD until the buyer reviews it (position ignored).
    position: Optional[str] = Field(default=None, pattern="^(STANDARD|FALLBACK|NON_STANDARD)$")


@router.post("/contracts/{ref}/redlines", tags=["F4 Contract"])
def redline(ref: str, body: RedlineIn, p: Principal = Depends(require_any("supplier:portal", "contract:manage"))):
    with uow(p) as s:
        return row(contract_svc.redline(s, by_ref(s, Contract, ref, lock=True), body.clause, body.text, body.position))


class RedlineReviewIn(BaseModel):
    decision: str = Field(pattern="^(ACCEPT|RESTORE)$")
    position: Optional[str] = Field(default=None, pattern="^(STANDARD|FALLBACK|NON_STANDARD)$")  # required for ACCEPT
    comment: Optional[str] = Field(default=None, max_length=2000)


@router.post("/contracts/{ref}/redlines/{clause}/review", tags=["F4 Contract"])
def review_redline(ref: str, clause: str, body: RedlineReviewIn, p: Principal = Depends(require("contract:manage"))):
    """Contract manager decision on a supplier redline: accept the supplier text with a playbook position, or restore the text."""
    with uow(p) as s:
        return row(contract_svc.review_redline(s, by_ref(s, Contract, ref, lock=True), clause, body.decision, body.position, body.comment))


@router.post("/contracts/{ref}/submit", tags=["F4 Contract"])
def submit_contract(ref: str, p: Principal = Depends(require("contract:manage"))):
    with uow(p) as s:
        return contract_svc.submit(s, by_ref(s, Contract, ref, lock=True))


class SignIn(BaseModel):
    party: str = Field(pattern="^(BUYER|SUPPLIER)$")
    signer_name: str


@router.post("/contracts/{ref}/signatures", tags=["F4 Contract"])
def sign(ref: str, body: SignIn, p: Principal = Depends(require_any("contract:sign", "supplier:portal"))):
    with uow(p) as s:
        return contract_svc.sign(s, by_ref(s, Contract, ref, lock=True), body.party, body.signer_name)


@router.post("/contracts/{ref}/activate", tags=["F4 Contract"])
def activate(ref: str, p: Principal = Depends(require("contract:manage"))):
    with uow(p) as s:
        return views.contract(s, contract_svc.activate(s, by_ref(s, Contract, ref, lock=True)))


@router.get("/contracts/{ref}/consumption", tags=["F4 Contract"])
def consumption(ref: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return contract_svc.consumption(s, by_ref(s, Contract, ref))


class IndexResetIn(BaseModel):
    index_value: Decimal = Field(gt=0, lt=Decimal("1e9"))
    effective_from: date


@router.post("/contracts/{ref}/index-resets", tags=["F4 Contract"])
def index_reset(ref: str, body: IndexResetIn, p: Principal = Depends(require("contract:manage")), key: Optional[str] = Depends(idempotency_key)):
    """Always a new price-validity period from ``effective_from`` (never an overwrite); inside the band the price is unchanged."""
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/contracts/{ref}/index-resets", key, body)
        if idem.replay:
            return idem.replay
        return idem.store(contract_svc.index_reset(s, by_ref(s, Contract, ref, lock=True), body.index_value, body.effective_from))


class ObligationIn(BaseModel):
    party: str = Field(pattern="^(BUYER|SUPPLIER)$")
    description: str = Field(min_length=3, max_length=2000)
    due_date: date
    kind: str = Field(default="OBLIGATION", pattern="^(OBLIGATION|MILESTONE)$")


@router.post("/contracts/{ref}/obligations", status_code=201, tags=["F4 Contract"])
def add_obligation(ref: str, body: ObligationIn, p: Principal = Depends(require("contract:manage")), key: Optional[str] = Depends(idempotency_key)):
    """Add a buyer or supplier obligation, or a milestone, to a contract."""
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/contracts/{ref}/obligations", key, body)
        if idem.replay:
            return idem.replay
        obligation = contract_svc.add_obligation(s, by_ref(s, Contract, ref, lock=True), party=body.party, description=body.description,
                                                 due_date=body.due_date, kind=body.kind)
        return idem.store(row(obligation), 201)


class ObligationDone(BaseModel):
    note: str = Field(min_length=3, max_length=2000)  # the evidence; written to the audit trail


@router.post("/obligations/{oid}/complete", tags=["F4 Contract"])
def complete_obligation(oid: uuid.UUID, body: ObligationDone, p: Principal = Depends(require("contract:manage"))):
    with uow(p) as s:
        obligation = s.get(Obligation, oid, with_for_update=True)
        if obligation is None:
            raise not_found("Obligation", oid)
        return row(contract_svc.complete_obligation(s, obligation, body.note))


# ---------------------------------------------------------------- savings and spend
@router.get("/savings", tags=["Savings & Spend"])
def savings_register(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        register = savings.register(s)
        for entry in register:
            # SOD-07: finance validates, never the initiative owner.
            entry["canValidate"] = ("FINANCE_CONTROLLER" in p.roles and entry["stage"] == "REALISING"
                                    and entry["ownerId"] != str(p.user_id))
        return register


@router.get("/savings/{ref}/waterfall", tags=["Savings & Spend"])
def savings_waterfall(ref: str, response: Response, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        initiative = by_ref(s, SavingsInitiative, ref)
        response.headers["ETag"] = etag(initiative)
        return savings.waterfall(s, initiative)


@router.post("/savings/{ref}/validate", tags=["Savings & Spend"])
def validate_savings(ref: str, response: Response, p: Principal = Depends(require("savings:validate")),
                     if_match: Optional[str] = Header(default=None, alias="If-Match")):
    """Finance validation (M11, SOD-07). If-Match carries the ETag of GET /v1/savings/{ref}/waterfall when sent (412 on a stale view)."""
    with uow(p) as s:
        initiative = by_ref(s, SavingsInitiative, ref, lock=True)
        check_if_match(initiative, if_match)
        result = savings.validate(s, initiative)
        s.flush()
        response.headers["ETag"] = etag(result)
        return row(result)


@router.get("/spend/cube", tags=["Savings & Spend"])
def spend_cube(dims: str = Query("category"), p: Principal = Depends(require("spend:read"))):
    with uow(p) as s:
        return savings.spend_cube(s, [d.strip() for d in dims.split(",")])
