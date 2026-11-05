"""Spend governance (M01), demand forecasts (M02), supplier risk and CAPA (M06), PO change requests (M08),
ERP reconciliation (M10), agent recommendations (M12) and currencies / FX (M13)."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
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
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")  # retired nodes keep their history


class ClassificationReview(TenantScoped, Base):
    """Spend lines classified below the confidence threshold (0.80) wait here for a steward (M01 rule)."""
    __tablename__ = "classification_review"
    __table_args__ = (UniqueConstraint("tenant_id", "spend_line_id"), Index("ix_classification_review_status", "tenant_id", "status"))
    spend_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.spend_line.id"), nullable=False)
    invoice_ref: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    proposed_category: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    alternatives: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="OPEN")  # OPEN | PENDING_SECOND | ACCEPTED | RECLASSIFIED
    decided_category: Mapped[Optional[str]] = mapped_column(String(40))
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    agent_run_ref: Mapped[Optional[str]] = mapped_column(String(60))
    # Second pass (migration 0021): value at stake (group currency, drives four-eyes and the queue order), SLA, first decision of a
    # four-eyes review, the keyword the steward taught the classifier and the reason of the decision.
    value_group_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    first_category: Mapped[Optional[str]] = mapped_column(String(40))
    first_decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    first_decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[Optional[str]] = mapped_column(Text)
    learned_keyword: Mapped[Optional[str]] = mapped_column(String(60))
    channel: Mapped[str] = mapped_column(String(10), nullable=False, default="AGENT", server_default="AGENT")  # AGENT | BULK


class MaverickRule(TenantScoped, Base):
    __tablename__ = "maverick_rule"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)  # Critical | High | Medium | Low
    owner_role: Mapped[str] = mapped_column(String(40), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sla_days: Mapped[int] = mapped_column(Integer, nullable=False, default=10, server_default="10")  # days from the hit to its disposition
    escalate_role: Mapped[Optional[str]] = mapped_column(String(40))  # who receives the hit when the SLA is missed


class MaverickHit(TenantScoped, Base):
    """Each hit needs an owner and a disposition (M01 rule)."""
    __tablename__ = "maverick_hit"
    __table_args__ = (UniqueConstraint("tenant_id", "rule_code", "spend_line_id"), Index("ix_maverick_hit_status", "tenant_id", "status"),
                      Index("ix_maverick_hit_supplier", "tenant_id", "supplier_id"))
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
    # Second pass (migration 0021): amount in the group currency (hits of several currencies add up), SLA and escalation, the reason code of the
    # disposition, the recovery outcome and the saving at risk (the price variance of the line, or the whole amount of a policy breach).
    amount_group_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    escalation_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    escalated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    escalated_to_role: Mapped[Optional[str]] = mapped_column(String(40))
    reason_code: Mapped[Optional[str]] = mapped_column(String(30))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    recovered_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    resolution_note: Mapped[Optional[str]] = mapped_column(Text)
    savings_at_risk_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")


class CategoryPlan(TenantScoped, Base):
    """One row per version of a category's plan for a fiscal year (a revision of an approved plan is a new version; the one it
    replaces becomes SUPERSEDED when the revision is approved)."""
    __tablename__ = "category_plan"
    __table_args__ = (UniqueConstraint("tenant_id", "category", "fiscal_year", "version"),)
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
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="DRAFT")  # DRAFT | IN_APPROVAL | APPROVED | REJECTED | SUPERSEDED
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Second pass (migration 0021): version chain, submission, addressable spend the target is checked against, the dated wave plan and
    # the savings target split by lever.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    supersedes_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    submitted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decision_comment: Mapped[Optional[str]] = mapped_column(Text)
    addressable_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    wave_plan: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")  # [{name, start, end, lever, milestone}]
    savings_by_lever: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")  # {lever: minor}


class SpendForecastSnapshot(TenantScoped, Base):
    """A spend forecast as it was issued: ``as_of_period`` is the last complete month the model saw, ``period`` the month forecast.
    Comparing it with the cube's actual spend later gives the forecast's real error (MAPE) and whether the 80% band held."""
    __tablename__ = "spend_forecast_snapshot"
    __table_args__ = (UniqueConstraint("tenant_id", "as_of_period", "category", "plant", "period"),)
    as_of_period: Mapped[str] = mapped_column(String(7), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")  # '' = all plants
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    horizon: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    forecast_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    low_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    high_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)


class SpendQualityRun(TenantScoped, Base):
    """One data-quality assessment of the spend cube (score 0-100 and every check with its count and value)."""
    __tablename__ = "spend_quality_run"
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    lines: Mapped[int] = mapped_column(BigInteger, nullable=False)
    spend_group_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    run_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SpendDuplicateCluster(TenantScoped, Base):
    """A group of supplier records that look like one legal entity. The cluster key is a hash of the sorted supplier codes, so a
    steward's decision (dismissed, merge proposed) survives the next scan; a cluster whose members change is a new cluster."""
    __tablename__ = "spend_duplicate_cluster"
    __table_args__ = (UniqueConstraint("tenant_id", "cluster_key"),)
    cluster_key: Mapped[str] = mapped_column(String(40), nullable=False)
    supplier_codes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    reasons: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # same PAN | same GSTIN | same bank account | similar name
    score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    spend_group_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="OPEN")  # OPEN | PROPOSED | MERGE_APPROVED | REJECTED | DISMISSED
    survivor_code: Mapped[Optional[str]] = mapped_column(String(30))
    proposal_number: Mapped[Optional[str]] = mapped_column(String(30))
    note: Mapped[Optional[str]] = mapped_column(Text)
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


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
