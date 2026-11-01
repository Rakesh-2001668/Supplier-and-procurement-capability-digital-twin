"""F3 sourcing, F4 contracts, M11 savings and M01 spend."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.pic import views
from app.pic.api.deps import idempotency_key, idempotent, uow
from app.pic.models import Contract, Obligation, SavingsInitiative, SourcingEvent, Supplier
from app.pic.platform.auth import READ, Principal, require, require_any
from app.pic.platform.errors import Problem, not_found
from app.pic.platform.serialize import row, rows
from app.pic.services import contract as contract_svc
from app.pic.services import savings, sourcing
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


class BundleIn(BaseModel):
    kind: str = Field(default="PR_LINES", pattern="^(PR_LINES|MRP_DEMAND|CATEGORY_PLAN)$")
    ref: Optional[str] = None


class InviteeIn(BaseModel):
    supplier: str
    waiver_reason: Optional[str] = None


class EventIn(BaseModel):
    type: str = Field(pattern="^(RFI|RFQ|RFP|REVERSE_AUCTION)$")
    title: str
    category: str
    lines: list[EventLineIn] = Field(min_length=1, max_length=50)
    criteria: list[CriterionIn]
    invitees: list[InviteeIn]
    close_at: datetime
    baseline_method: str = "LAST_PRICE"
    baseline_price_minor: Optional[int] = None
    should_cost_params: Optional[dict] = None
    constraints: Optional[dict] = None
    tco_params: Optional[dict] = None
    savings_target_pct: Optional[Decimal] = None
    bundle: Optional[BundleIn] = None


@router.post("/sourcing/events", status_code=201, tags=["F3 Sourcing"])
def create_event(body: EventIn, p: Principal = Depends(require("sourcing:manage")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/sourcing/events", key, body)
        if idem.replay:
            return idem.replay
        data = body.model_dump()
        data["lines"] = [l for l in data["lines"]]
        event = sourcing.create_event(s, **data)
        return idem.store(views.sourcing_event(s, event), 201)


@router.post("/sourcing/events/{ref}/publish", tags=["F3 Sourcing"])
def publish_event(ref: str, p: Principal = Depends(require("sourcing:manage"))):
    with uow(p) as s:
        return views.sourcing_event(s, sourcing.publish(s, by_ref(s, SourcingEvent, ref, lock=True)))


class BidLineIn(BaseModel):
    line: int
    unit_price: Decimal
    freight: Decimal = Decimal(0)
    duty: Decimal = Decimal(0)
    packaging: Decimal = Decimal(0)
    payment_terms_days: int
    lead_time_days: int
    capacity_per_month: Optional[Decimal] = None


class BidLotIn(BaseModel):
    lot: str
    discount_pct: Decimal = Field(default=Decimal(0), ge=0, lt=100)  # applies when the supplier is awarded the whole lot
    all_or_nothing: bool = False  # the supplier accepts the lot only as a whole


class BidIn(BaseModel):
    lines: list[BidLineIn] = Field(min_length=1)  # a price for every event line of a single-line event; partial bids allowed on several lines
    lots: list[BidLotIn] = []


@router.post("/sourcing/events/{ref}/bids", status_code=201, tags=["F3 Sourcing"])
def submit_bid(ref: str, body: BidIn, p: Principal = Depends(require("bid:submit"))):
    with uow(p) as s:
        event = by_ref(s, SourcingEvent, ref, lock=True)
        bid = sourcing.submit_bid(s, event, s.get(Supplier, p.supplier_id), [l.model_dump(mode="json") for l in body.lines],
                                  [l.model_dump(mode="json") for l in body.lots])
        return {"event": event.number, "round": bid.round, "status": bid.status, "hash": bid.payload_hash,
                "submittedAt": bid.submitted_at.isoformat()}


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


@router.post("/sourcing/events/{ref}/close", tags=["F3 Sourcing"])
def close_event(ref: str, p: Principal = Depends(require("sourcing:manage"))):
    with uow(p) as s:
        return sourcing.close(s, by_ref(s, SourcingEvent, ref, lock=True))


class ScoreIn(BaseModel):
    supplier: str
    criterion: str
    score: Decimal = Field(ge=0, le=100)
    comment: Optional[str] = None


@router.post("/sourcing/events/{ref}/scores", tags=["F3 Sourcing"])
def score_bids(ref: str, body: list[ScoreIn], p: Principal = Depends(require_any("sourcing:evaluate"))):
    with uow(p) as s:
        return sourcing.score(s, by_ref(s, SourcingEvent, ref), [b.model_dump(mode="json") for b in body])


class RoundIn(BaseModel):
    close_at: datetime
    note: str = ""


@router.post("/sourcing/events/{ref}/rounds", tags=["F3 Sourcing"])
def new_round(ref: str, body: RoundIn, p: Principal = Depends(require("sourcing:manage"))):
    with uow(p) as s:
        return views.sourcing_event(s, sourcing.new_round(s, by_ref(s, SourcingEvent, ref, lock=True), body.close_at, body.note))


@router.post("/sourcing/events/{ref}/scenarios", tags=["F3 Sourcing"])
def scenarios(ref: str, p: Principal = Depends(require("sourcing:manage"))):
    with uow(p) as s:
        return sourcing.build_scenarios(s, by_ref(s, SourcingEvent, ref, lock=True))


class AwardIn(BaseModel):
    scenario_id: uuid.UUID
    rationale: Optional[str] = None
    conflict_declaration: str


@router.post("/sourcing/events/{ref}/award", tags=["F3 Sourcing"])
def award(ref: str, body: AwardIn, p: Principal = Depends(require("sourcing:manage"))):
    with uow(p) as s:
        event = by_ref(s, SourcingEvent, ref, lock=True)
        sourcing.propose_award(s, event, body.scenario_id, body.rationale, body.conflict_declaration)
        return views.sourcing_event(s, event)


class EventCancelIn(BaseModel):
    reason: str = ""


@router.post("/sourcing/events/{ref}/cancel", tags=["F3 Sourcing"])
def cancel_event(ref: str, body: EventCancelIn, p: Principal = Depends(require("sourcing:manage")),
                 key: Optional[str] = Depends(idempotency_key)):
    """Cancel an event that is not awarded yet; invited suppliers are notified and see it as cancelled in the portal."""
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/sourcing/events/{ref}/cancel", key, body)
        if idem.replay:
            return idem.replay
        event = by_ref(s, SourcingEvent, ref, lock=True)
        sourcing.cancel(s, event, body.reason)
        return idem.store(views.sourcing_event(s, event))


@router.get("/sourcing/events/{ref}", tags=["F3 Sourcing"])
def get_event(ref: str, p: Principal = Depends(require_any(READ, "supplier:portal"))):
    with uow(p) as s:
        event = by_ref(s, SourcingEvent, ref)
        view = views.sourcing_event(s, event)
        if "SUPPLIER_USER" in p.roles:
            mine = s.get(Supplier, p.supplier_id)
            # never published (a draft, or a draft cancelled before publishing): invisible to suppliers
            if event.status == "DRAFT" or event.published_at is None or mine.code not in {i["code"] for i in view["invitees"]}:
                raise not_found("Sourcing event", ref)
            # Suppliers see the requirement and their own bid status, not competitors, scores or award scenarios.
            view = {k: v for k, v in view.items() if k not in ("invitees", "scenarios", "awardDecisions", "lineage", "process", "should_cost",
                                                              "baseline_price_minor", "constraints", "tco_params")}
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
def savings_waterfall(ref: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return savings.waterfall(s, by_ref(s, SavingsInitiative, ref))


@router.post("/savings/{ref}/validate", tags=["Savings & Spend"])
def validate_savings(ref: str, p: Principal = Depends(require("savings:validate"))):
    with uow(p) as s:
        return row(savings.validate(s, by_ref(s, SavingsInitiative, ref, lock=True)))


@router.get("/spend/cube", tags=["Savings & Spend"])
def spend_cube(dims: str = Query("category"), p: Principal = Depends(require("spend:read"))):
    with uow(p) as s:
        return savings.spend_cube(s, [d.strip() for d in dims.split(",")])
