"""Spend governance (M01), demand forecasts (M02), supplier risk and CAPA (M06), PO change requests (M08),
ERP reconciliation (M10), agent recommendations (M12) and currencies / FX (M13)."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.pic.db import SCHEMA, Base, TenantScoped

QTY = Numeric(18, 3)


# ---------------------------------------------------------------- M01 spend governance
class TaxonomyNode(TenantScoped, Base):
    __tablename__ = "taxonomy_node"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    parent_code: Mapped[Optional[str]] = mapped_column(String(40))
    level: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 segment · 2 family · 3 category
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    keywords: Mapped[list] = mapped_column(ARRAY(String(60)), default=list)
    addressable: Mapped[bool] = mapped_column(Boolean, default=True)


class ClassificationReview(TenantScoped, Base):
    """Spend lines classified below the confidence threshold (0.80) wait here for a steward (M01 rule)."""
    __tablename__ = "classification_review"
    __table_args__ = (UniqueConstraint("tenant_id", "spend_line_id"),)
    spend_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.spend_line.id"), nullable=False)
    invoice_ref: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    proposed_category: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    alternatives: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="OPEN")  # OPEN | ACCEPTED | RECLASSIFIED
    decided_category: Mapped[Optional[str]] = mapped_column(String(40))
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    agent_run_ref: Mapped[Optional[str]] = mapped_column(String(60))


class MaverickRule(TenantScoped, Base):
    __tablename__ = "maverick_rule"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)  # Critical | High | Medium | Low
    owner_role: Mapped[str] = mapped_column(String(40), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MaverickHit(TenantScoped, Base):
    """Each hit needs an owner and a disposition (M01 rule)."""
    __tablename__ = "maverick_hit"
    __table_args__ = (UniqueConstraint("tenant_id", "rule_code", "spend_line_id"),)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    rule_code: Mapped[str] = mapped_column(String(30), nullable=False)
    spend_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.spend_line.id"), nullable=False)
    invoice_ref: Mapped[str] = mapped_column(String(60), nullable=False)
    po_ref: Mapped[Optional[str]] = mapped_column(String(60))
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    owner_role: Mapped[str] = mapped_column(String(40), nullable=False)
    owner_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    disposition: Mapped[Optional[str]] = mapped_column(String(30))  # ACCEPTED_EXCEPTION | RECOVERY | POLICY_BREACH | FALSE_POSITIVE
    comment: Mapped[Optional[str]] = mapped_column(Text)
    disposed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    disposed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class CategoryPlan(TenantScoped, Base):
    __tablename__ = "category_plan"
    __table_args__ = (UniqueConstraint("tenant_id", "category", "fiscal_year"),)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    fiscal_year: Mapped[str] = mapped_column(String(7), nullable=False)
    spend_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    profit_impact: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)  # 0..10
    supply_risk: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)  # 0..10
    kraljic: Mapped[str] = mapped_column(String(15), nullable=False)  # STRATEGIC | LEVERAGE | BOTTLENECK | NON_CRITICAL
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    levers: Mapped[list] = mapped_column(JSONB, default=list)
    waves: Mapped[list] = mapped_column(JSONB, default=list)
    budget_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    savings_target_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="DRAFT")  # DRAFT | APPROVED
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- M02 demand forecast review
class Forecast(TenantScoped, Base):
    __tablename__ = "forecast"
    __table_args__ = (UniqueConstraint("tenant_id", "material_id", "plant", "period"),)
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    method: Mapped[str] = mapped_column(String(30), nullable=False)  # EXP_SMOOTHING | SEASONAL_NAIVE | PLAN
    statistical_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    override_qty: Mapped[Optional[Decimal]] = mapped_column(QTY)
    override_reason: Mapped[Optional[str]] = mapped_column(Text)
    override_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    actual_qty: Mapped[Optional[Decimal]] = mapped_column(QTY)
    actual_source: Mapped[Optional[str]] = mapped_column(String(40))  # GOODS_ISSUES | ERP_CONSUMPTION_HISTORY
    model_version: Mapped[str] = mapped_column(String(40), nullable=False)


# ---------------------------------------------------------------- M06 supplier risk and CAPA
class RiskSignal(TenantScoped, Base):
    __tablename__ = "risk_signal"
    __table_args__ = (UniqueConstraint("tenant_id", "supplier_id", "dedup_key"),)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)  # FINANCIAL | COMPLIANCE | DELIVERY | QUALITY | FRAUD | CERTIFICATE
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="OPEN")  # OPEN | MITIGATING | CLOSED
    mitigation: Mapped[Optional[str]] = mapped_column(Text)
    owner_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Capa(TenantScoped, Base):
    __tablename__ = "capa"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(60), nullable=False)
    finding: Mapped[str] = mapped_column(Text, nullable=False)
    root_cause: Mapped[Optional[str]] = mapped_column(Text)
    actions: Mapped[list] = mapped_column(JSONB, default=list)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="OPEN")  # OPEN | RESPONDED | VERIFIED | CLOSED
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    verified_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- M08 PO change requests
class PoChangeRequest(TenantScoped, Base):
    __tablename__ = "po_change_request"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.purchase_order.id"), nullable=False)
    po_version: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[str] = mapped_column(String(10), nullable=False)  # SUPPLIER | BUYER
    lines: Mapped[list] = mapped_column(JSONB, nullable=False)  # [{line, qty?, need_date?}]
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="OPEN")  # OPEN | ACCEPTED | REJECTED | WITHDRAWN
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decision_comment: Mapped[Optional[str]] = mapped_column(Text)
    result_version: Mapped[Optional[int]] = mapped_column(Integer)


# ---------------------------------------------------------------- M10 ERP reconciliation
class ReconciliationRun(TenantScoped, Base):
    __tablename__ = "reconciliation_run"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    target_system: Mapped[str] = mapped_column(String(20), nullable=False)
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    platform_count: Mapped[int] = mapped_column(Integer, nullable=False)
    erp_count: Mapped[int] = mapped_column(Integer, nullable=False)
    platform_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    erp_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    differences: Mapped[int] = mapped_column(Integer, nullable=False)


class ReconciliationItem(TenantScoped, Base):
    __tablename__ = "reconciliation_item"
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.reconciliation_run.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(25), nullable=False)  # MISSING_IN_ERP | MISSING_IN_PLATFORM | AMOUNT_MISMATCH
    object_type: Mapped[str] = mapped_column(String(30), nullable=False)
    object_ref: Mapped[str] = mapped_column(String(60), nullable=False)
    erp_doc_no: Mapped[Optional[str]] = mapped_column(String(40))
    platform_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    erp_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="OPEN")  # OPEN | RESOLVED
    resolution: Mapped[Optional[str]] = mapped_column(Text)
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))


# ---------------------------------------------------------------- M12 recommendations
class Recommendation(TenantScoped, Base):
    """What an L1/L2 agent proposes; a human accepts or rejects it, which feeds the acceptance rate."""
    __tablename__ = "recommendation"
    agent_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.agent_run.id"), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(160), nullable=False)
    object_type: Mapped[str] = mapped_column(String(40), nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    object_ref: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    proposal: Mapped[dict] = mapped_column(JSONB, default=dict)
    deep_link: Mapped[Optional[str]] = mapped_column(String(200))
    value_at_risk_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    candidate_role: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="OPEN")  # OPEN | ACCEPTED | REJECTED
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    feedback_comment: Mapped[Optional[str]] = mapped_column(Text)


# ---------------------------------------------------------------- M13 currencies and FX
class Currency(TenantScoped, Base):
    __tablename__ = "currency"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    code: Mapped[str] = mapped_column(String(3), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    decimals: Mapped[int] = mapped_column(Integer, default=2)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class FxRate(TenantScoped, Base):
    """Rate to convert 1 unit of from_ccy into to_ccy, valid from a date (effective-dated, P14)."""
    __tablename__ = "fx_rate"
    __table_args__ = (UniqueConstraint("tenant_id", "from_ccy", "to_ccy", "valid_from"),)
    from_ccy: Mapped[str] = mapped_column(String(3), nullable=False)
    to_ccy: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
