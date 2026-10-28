"""M05 strategic sourcing (F3) and M07 contract lifecycle (F4)."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, Numeric, String, Text, UniqueConstraint
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


class Bid(TenantScoped, Base):
    """Sealed bid. Commercial content is encrypted until the event closes."""
    __tablename__ = "bid"
    __table_args__ = (UniqueConstraint("tenant_id", "event_id", "supplier_id", "round"),)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.sourcing_event.id"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sealed_payload: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="SEALED")  # SEALED | UNSEALED | SUPERSEDED
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


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


class Contract(TenantScoped, Base):
    __tablename__ = "contract"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
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


class ContractLine(TenantScoped, Base):
    __tablename__ = "contract_line"
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.contract.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    material_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"))
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    uom: Mapped[str] = mapped_column(String(5), nullable=False)
    target_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    released_qty: Mapped[Decimal] = mapped_column(QTY, default=0)
    released_value_minor: Mapped[int] = mapped_column(BigInteger, default=0)


class PriceValidity(TenantScoped, Base):
    """Price per period. Index resets add a new period; existing periods are never overwritten."""
    __tablename__ = "price_validity"
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


class Obligation(TenantScoped, Base):
    __tablename__ = "obligation"
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.contract.id"), nullable=False)
    party: Mapped[str] = mapped_column(String(10), nullable=False)  # BUYER | SUPPLIER
    description: Mapped[str] = mapped_column(Text, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(15), default="OPEN")


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
