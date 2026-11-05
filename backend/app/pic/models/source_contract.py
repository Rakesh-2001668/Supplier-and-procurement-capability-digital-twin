"""M05 strategic sourcing (F3) and M07 contract lifecycle (F4)."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, LargeBinary, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.pic.db import SCHEMA, Base, TenantScoped

QTY = Numeric(18, 3)


class SourcingEvent(TenantScoped, Base):
    __tablename__ = "sourcing_event"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # RFI | RFQ | RFP | REVERSE_AUCTION
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    round: Mapped[int] = mapped_column(Integer, default=1)
    weights_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    close_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    unsealed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    baseline_price_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    baseline_method: Mapped[Optional[str]] = mapped_column(String(20))
    should_cost: Mapped[Optional[dict]] = mapped_column(JSONB)
    constraints: Mapped[dict] = mapped_column(JSONB, default=dict)  # max_suppliers, max_share, min_share
    tco_params: Mapped[dict] = mapped_column(JSONB, default=dict)  # carrying rate, cost of capital, CoPQ per defect
    savings_target_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    auction: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")  # minDecrementPct, extensionMinutes, triggerMinutes
    auction_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    bundle: Mapped[Optional[dict]] = mapped_column(JSONB)  # requirement bundling: sources (PR / MRP / category plan) and line counts
    # M05 second pass (migration 0022)
    scoring_method: Mapped[str] = mapped_column(String(12), nullable=False, default="LOWEST_RATIO", server_default="LOWEST_RATIO")  # LOWEST_RATIO | MIN_MAX | RANK
    purpose_code: Mapped[Optional[str]] = mapped_column(String(40))  # P01: taken from the requirements the event sources
    need_date: Mapped[Optional[date]] = mapped_column(Date)  # the earliest need date of the sourced lines
    budget_check: Mapped[Optional[dict]] = mapped_column(JSONB)  # outcome of the category-budget check at publish
    budget_justification: Mapped[Optional[str]] = mapped_column(Text)
    clarification_close_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reference_date: Mapped[Optional[date]] = mapped_column(Date)  # pricing date: bid currencies convert at the rate valid on this day
    min_bidders: Mapped[Optional[int]] = mapped_column(Integer)  # SOURCING-POLICY.minBidders frozen at publish
    competitive: Mapped[Optional[bool]] = mapped_column(Boolean)  # set at close: valid bidders >= min_bidders
    opening: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")  # two-person bid opening state
    template_code: Mapped[Optional[str]] = mapped_column(String(40))
    cloned_from: Mapped[Optional[str]] = mapped_column(String(30))
    rule_versions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")  # SOURCING-POLICY / SOURCING-TCO versions the event ran under
    open_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))  # scheduled opening: published (visible, questions) but not yet open for bids


class EventLine(TenantScoped, Base):
    __tablename__ = "event_line"
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.sourcing_event.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    material_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"))
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    annual_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    monthly_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    uom: Mapped[str] = mapped_column(String(5), nullable=False)
    requisition_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    pr_line_no: Mapped[Optional[int]] = mapped_column(Integer)
    lot_code: Mapped[Optional[str]] = mapped_column(String(20))  # lines of one lot can be bid and awarded as a bundle
    baseline_price_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    need_date: Mapped[Optional[date]] = mapped_column(Date)  # earliest need date of the requirement lines behind this line


class Invitee(TenantScoped, Base):
    __tablename__ = "invitee"
    __table_args__ = (UniqueConstraint("tenant_id", "event_id", "supplier_id"),)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.sourcing_event.id"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    category_status: Mapped[str] = mapped_column(String(25), nullable=False)
    waiver_reason: Mapped[Optional[str]] = mapped_column(Text)


class Criterion(TenantScoped, Base):
    __tablename__ = "criterion"
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.sourcing_event.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)  # PRICE_TCO | QUALITY | DELIVERY | TECHNICAL | ESG | RISK
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    data_source: Mapped[str] = mapped_column(String(12), nullable=False, default="MANUAL", server_default="MANUAL")  # MANUAL | SCORECARD | ESG | RISK
    min_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))  # technical gate: a bid scoring below this on the criterion is not eligible


class Bid(TenantScoped, Base):
    """Sealed bid. Commercial content is encrypted until the event closes."""
    __tablename__ = "bid"
    __table_args__ = (UniqueConstraint("tenant_id", "event_id", "supplier_id", "round"),)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.sourcing_event.id"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sealed_payload: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="SEALED")  # SEALED | UNSEALED | SUPERSEDED | INVALID | WITHDRAWN | DISQUALIFIED
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    auto_scores: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")  # data-driven criteria frozen at close
    valid_until: Mapped[Optional[date]] = mapped_column(Date)  # the supplier's offer validity (unsealed with the bid)
    withdrawn_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    withdrawn_reason: Mapped[Optional[str]] = mapped_column(Text)
    disqualified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    disqualified_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    disqualified_reason: Mapped[Optional[str]] = mapped_column(Text)
    edits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")  # times the supplier replaced the sealed bid before close


class BidLine(TenantScoped, Base):
    """Unsealed commercial values, written only when the event closes."""
    __tablename__ = "bid_line"
    bid_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bid.id"), nullable=False)
    event_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.event_line.id"), nullable=False)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tco_components: Mapped[dict] = mapped_column(JSONB, default=dict)
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    offered_capacity_per_month: Mapped[Optional[Decimal]] = mapped_column(QTY)
    tco_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    tco_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict)
    # M05 second pass (migration 0022): what the supplier quoted and how it was normalised
    price_quoted_minor: Mapped[Optional[int]] = mapped_column(BigInteger)  # in the quoted currency and unit, before conversion
    currency: Mapped[Optional[str]] = mapped_column(String(3))
    fx_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8))  # INR per unit of the quoted currency on the event's reference date
    fx_date: Mapped[Optional[date]] = mapped_column(Date)
    incoterm: Mapped[Optional[str]] = mapped_column(String(10))
    origin: Mapped[Optional[str]] = mapped_column(String(10))  # DOMESTIC | IMPORT
    moq: Mapped[Optional[Decimal]] = mapped_column(QTY)  # minimum order quantity per month the supplier needs to supply at this price
    price_uom: Mapped[Optional[str]] = mapped_column(String(5))
    uom_factor: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))  # base units in one quoted unit (price per base unit = price / factor)
    tax_included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    tax_rate_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    hs_code: Mapped[Optional[str]] = mapped_column(String(10))
    tco_incomplete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    tco_trace: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")  # one entry per TCO component: value, inputs, status


class Evaluation(TenantScoped, Base):
    __tablename__ = "evaluation"
    __table_args__ = (UniqueConstraint("tenant_id", "bid_id", "criterion_code", "evaluator_id"),)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.sourcing_event.id"), nullable=False)
    bid_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bid.id"), nullable=False)
    criterion_code: Mapped[str] = mapped_column(String(20), nullable=False)
    evaluator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)  # 0..100
    comment: Mapped[Optional[str]] = mapped_column(Text)


class AwardScenario(TenantScoped, Base):
    __tablename__ = "award_scenario"
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.sourcing_event.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)  # LOWEST_COST | BEST_VALUE | CAPACITY_CONSTRAINED
    feasible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allocations: Mapped[list] = mapped_column(JSONB, default=list)
    weighted_price_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    weighted_tco_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    annual_savings_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    explanation: Mapped[dict] = mapped_column(JSONB, default=dict)
    risk_score: Mapped[Optional[int]] = mapped_column(Integer)  # value-weighted supplier risk score of the awarded suppliers (0 best .. 100)


class AwardDecision(TenantScoped, Base):
    __tablename__ = "award_decision"
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.sourcing_event.id"), nullable=False)
    scenario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.award_scenario.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")  # PENDING | APPROVED | REJECTED
    rationale: Mapped[Optional[str]] = mapped_column(Text)
    conflict_declarations: Mapped[list] = mapped_column(JSONB, default=list)
    proposed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    annual_value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rule_set_version: Mapped[Optional[str]] = mapped_column(String(80))
    authority: Mapped[Optional[dict]] = mapped_column(JSONB)  # approval band, chain and value the decision was routed on
    exceptions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")  # why the award needed a rationale
    regret_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class EvaluatorDeclaration(TenantScoped, Base):
    """Conflict-of-interest declaration of a bid evaluator: required before the user scores in an event; a declared conflict bars the user."""
    __tablename__ = "evaluator_declaration"
    __table_args__ = (UniqueConstraint("tenant_id", "event_id", "user_id"),)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.sourcing_event.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    has_conflict: Mapped[bool] = mapped_column(Boolean, nullable=False)
    declaration: Mapped[str] = mapped_column(Text, nullable=False)
    declared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BidOpening(TenantScoped, Base):
    """Opening ceremony of a closed event under the two-person rule: the bids are unsealed when two different people have opened them."""
    __tablename__ = "bid_opening"
    __table_args__ = (UniqueConstraint("tenant_id", "event_id", "round", "user_id"),)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.sourcing_event.id"), nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ShouldCostModel(TenantScoped, Base):
    """Parametric should-cost model of a commodity (TD 12.4 should-cost): cost components and a margin, material rates linked to an index."""
    __tablename__ = "should_cost_model"
    __table_args__ = (UniqueConstraint("tenant_id", "code", "version"),)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    commodity: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    spec: Mapped[dict] = mapped_column(JSONB, nullable=False)
    index_code: Mapped[Optional[str]] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    note: Mapped[Optional[str]] = mapped_column(Text)


class PriceBenchmark(TenantScoped, Base):
    """A dated reference price for a category or material: market quote, peer price or catalogue price (the baselines of last price and
    weighted average are computed from the tenant's own purchase orders and awards)."""
    __tablename__ = "price_benchmark"
    __table_args__ = (Index("ix_price_benchmark_category", "tenant_id", "category", "as_of"),)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    material_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"))
    kind: Mapped[str] = mapped_column(String(15), nullable=False)  # MARKET | PEER | CATALOGUE
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uom: Mapped[str] = mapped_column(String(5), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text)


class SourcingTemplate(TenantScoped, Base):
    """A reusable event definition (criteria and weights, constraints, TCO overrides, invitation filter): an event is created from it or cloned."""
    __tablename__ = "sourcing_template"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class Contract(TenantScoped, Base):
    __tablename__ = "contract"
    __table_args__ = (UniqueConstraint("tenant_id", "number"), Index("ix_contract_framework", "tenant_id", "framework_contract_id"))
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)  # SCHEDULING_AGREEMENT | QUANTITY | VALUE | MASTER | RATE_CARD | SOW
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    payment_terms: Mapped[str] = mapped_column(String(10), nullable=False)
    incoterms: Mapped[Optional[str]] = mapped_column(String(40))
    over_tolerance_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    under_tolerance_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    price_tolerance_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    target_value_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    index_ref: Mapped[Optional[dict]] = mapped_column(JSONB)  # {"index":"LME_AL","base":..,"band_pct":3,"reset":"QUARTERLY"}
    source_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    thresholds_hit: Mapped[list] = mapped_column(JSONB, default=list)
    rule_set_version: Mapped[Optional[str]] = mapped_column(String(80))
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    terminated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    termination_reason: Mapped[Optional[str]] = mapped_column(Text)
    framework_contract_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.contract.id"))  # call-off of a master agreement
    jurisdiction: Mapped[Optional[str]] = mapped_column(String(10))  # governing-law code of the clause library variant (IN-MH, IN-DL, ...)
    category: Mapped[Optional[str]] = mapped_column(String(40))  # category whose clause overlay (CLM-PLAYBOOK.categoryClauses) the draft used


class ContractLine(TenantScoped, Base):
    __tablename__ = "contract_line"
    __table_args__ = (Index("ix_contract_line_material_plant", "tenant_id", "material_id", "plant"),
                      Index("ix_contract_line_contract", "tenant_id", "contract_id"))
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.contract.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    material_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"))
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    uom: Mapped[str] = mapped_column(String(5), nullable=False)
    target_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    released_qty: Mapped[Decimal] = mapped_column(QTY, default=0)
    released_value_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    thresholds_hit: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")  # consumption alerts raised for this line


class PriceValidity(TenantScoped, Base):
    """Price per period. Index resets add a new period; existing periods are never overwritten."""
    __tablename__ = "price_validity"
    __table_args__ = (Index("ix_price_validity_contract_line", "tenant_id", "contract_line_id"),)
    contract_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.contract_line.id"), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    index_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))
    reason: Mapped[str] = mapped_column(String(60), nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, default=False)


class Clause(TenantScoped, Base):
    __tablename__ = "clause"
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.contract.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[str] = mapped_column(String(15), nullable=False)  # STANDARD | FALLBACK | NON_STANDARD
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    standard_text: Mapped[Optional[str]] = mapped_column(Text)  # the library wording the clause was drafted from; None for a clause added later


class Obligation(TenantScoped, Base):
    __tablename__ = "obligation"
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.contract.id"), nullable=False)
    party: Mapped[str] = mapped_column(String(10), nullable=False)  # BUYER | SUPPLIER
    description: Mapped[str] = mapped_column(Text, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(15), default="OPEN")
    kind: Mapped[str] = mapped_column(String(12), nullable=False, default="OBLIGATION", server_default="OBLIGATION")  # OBLIGATION | MILESTONE
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    completion_note: Mapped[Optional[str]] = mapped_column(Text)


class Signature(TenantScoped, Base):
    __tablename__ = "signature"
    __table_args__ = (UniqueConstraint("tenant_id", "contract_id", "party"),)
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.contract.id"), nullable=False)
    party: Mapped[str] = mapped_column(String(10), nullable=False)
    signer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    signer_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    envelope_ref: Mapped[str] = mapped_column(String(60), nullable=False)
    document_hash: Mapped[str] = mapped_column(String(64), nullable=False)
