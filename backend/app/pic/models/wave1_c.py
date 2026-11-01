"""Wave 1 (engineer C1): master data, sourcing, contracts and supplier management (migration 0010).

Material change requests with versioned history, requirement sources of an event line, lot (bundle) bids, supplier rebates and their
settlement, clause extraction review, supplier segmentation history, development plans and the supplier ESG / cyber assessments.
Every table is a tenant table with forced row-level security."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.pic.db import SCHEMA, Base, TenantScoped

QTY = Numeric(18, 3)


# ---------------------------------------------------------------- M03 material change requests (17, 18)
class MaterialChangeRequest(TenantScoped, Base):
    """A change to an existing material: before/after of the fields, the impact analysis, and one steward task per owning domain."""
    __tablename__ = "material_change_request"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number"),
        CheckConstraint("status IN ('IN_APPROVAL','APPLIED','REJECTED','CANCELLED')", name="status"),
        Index("ix_material_change_request_material", "tenant_id", "material_id"),
    )
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="IN_APPROVAL")
    material_type: Mapped[str] = mapped_column(String(20), nullable=False)
    changes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # [{field, label, from, to, domain, owner}]
    domains: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # steward domains that approve
    impact: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    from_version: Mapped[int] = mapped_column(Integer, nullable=False)
    to_version: Mapped[Optional[int]] = mapped_column(Integer)
    approvals: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    rule_set_version: Mapped[Optional[str]] = mapped_column(String(80))
    erp_key: Mapped[Optional[str]] = mapped_column(String(80))
    erp_document: Mapped[Optional[str]] = mapped_column(String(40))
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)


class MaterialVersion(TenantScoped, Base):
    """Full snapshot of the material master per version (append-only history)."""
    __tablename__ = "material_version"
    __table_args__ = (UniqueConstraint("tenant_id", "material_id", "version"), CheckConstraint("version >= 1", name="version_positive"))
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    changed_fields: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    change_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[Optional[str]] = mapped_column(Text)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------- M05 lots and requirement bundling (19, 20)
class EventLineSource(TenantScoped, Base):
    """The requisition lines merged into one event line (requirement bundling). All of them move IN_SOURCING and are closed on award."""
    __tablename__ = "event_line_source"
    __table_args__ = (UniqueConstraint("tenant_id", "event_line_id", "requisition_id", "pr_line_no"),
                      CheckConstraint("qty > 0", name="qty_positive"))
    event_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.event_line.id"), nullable=False)
    requisition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    pr_line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    origin: Mapped[Optional[str]] = mapped_column(String(20))  # requisition origin (MANUAL | MRP | ...)


class BidLot(TenantScoped, Base):
    """Bundle terms of a bid for one lot, unsealed at close like the bid lines: a discount that applies when the supplier is awarded the whole
    lot, and the all-or-nothing flag (the supplier accepts the lot only as a whole)."""
    __tablename__ = "bid_lot"
    __table_args__ = (UniqueConstraint("tenant_id", "bid_id", "lot_code"),
                      CheckConstraint("discount_pct >= 0 AND discount_pct < 100", name="discount_range"))
    bid_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bid.id"), nullable=False)
    lot_code: Mapped[str] = mapped_column(String(20), nullable=False)
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    all_or_nothing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


# ---------------------------------------------------------------- M07 supplier rebates (26)
class RebateAgreement(TenantScoped, Base):
    __tablename__ = "rebate_agreement"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number"),
        CheckConstraint("basis IN ('VOLUME','VALUE')", name="basis"),
        CheckConstraint("period IN ('MONTHLY','QUARTERLY','ANNUAL')", name="period"),
        CheckConstraint("tier_mode IN ('SLAB','RETROACTIVE')", name="tier_mode"),
        CheckConstraint("scope IN ('CONTRACT','SUPPLIER')", name="scope"),
        CheckConstraint("status IN ('ACTIVE','CLOSED','CANCELLED')", name="status"),
        CheckConstraint("valid_to >= valid_from", name="validity"),
        Index("ix_rebate_agreement_contract", "tenant_id", "contract_id"),
    )
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.contract.id"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    basis: Mapped[str] = mapped_column(String(10), nullable=False)
    period: Mapped[str] = mapped_column(String(10), nullable=False)
    tier_mode: Mapped[str] = mapped_column(String(12), nullable=False, default="RETROACTIVE")
    scope: Mapped[str] = mapped_column(String(10), nullable=False, default="CONTRACT")
    tiers: Mapped[list] = mapped_column(JSONB, nullable=False)  # [{"from": "100000.00", "ratePct": "2.0"}] ascending; value in rupees or quantity
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ACTIVE")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)


class RebateAccrual(TenantScoped, Base):
    """The accrued rebate of one agreement period; recomputed idempotently from posted invoices net of credit notes."""
    __tablename__ = "rebate_accrual"
    __table_args__ = (UniqueConstraint("tenant_id", "agreement_id", "period_label"),
                      CheckConstraint("status IN ('OPEN','SETTLED')", name="status"),
                      CheckConstraint("accrued_minor >= 0", name="accrued_not_negative"))
    agreement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.rebate_agreement.id"), nullable=False)
    period_label: Mapped[str] = mapped_column(String(12), nullable=False)  # 2026-Q3 | 2026-07 | FY2026-27
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    basis_value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    basis_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False, default=0)
    rate_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=0)
    accrued_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="OPEN")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class RebateSettlement(TenantScoped, Base):
    """Settlement of an accrual as a vendor credit memo, posted to the ERP exactly once (message SUPPLIER_CREDIT_MEMO)."""
    __tablename__ = "rebate_settlement"
    __table_args__ = (UniqueConstraint("tenant_id", "number"), UniqueConstraint("tenant_id", "accrual_id"),
                      CheckConstraint("amount_minor > 0", name="amount_positive"),
                      CheckConstraint("status IN ('PENDING_ERP','POSTED')", name="status"))
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    agreement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.rebate_agreement.id"), nullable=False)
    accrual_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.rebate_accrual.id"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="PENDING_ERP")
    settled_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    erp_key: Mapped[str] = mapped_column(String(120), nullable=False)
    erp_document: Mapped[Optional[str]] = mapped_column(String(40))
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- TD §12.4 clause extraction (27)
class ClauseExtraction(TenantScoped, Base):
    __tablename__ = "clause_extraction"
    __table_args__ = (UniqueConstraint("tenant_id", "number"), UniqueConstraint("tenant_id", "source_hash", "contract_ref"),
                      CheckConstraint("status IN ('EXTRACTED','REVIEWED','APPLIED','REJECTED')", name="status"))
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_ref: Mapped[str] = mapped_column(String(40), nullable=False)  # contract number the clauses belong to
    contract_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="EXTRACTED")
    items: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    unmatched: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    extractor_version: Mapped[str] = mapped_column(String(30), nullable=False)
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- M06 segmentation, development plans, assessments (28, 29, 30, 31)
class SupplierSegment(TenantScoped, Base):
    """Segment history: the row without effective_to is the current segment (also copied to supplier.segment)."""
    __tablename__ = "supplier_segment"
    __table_args__ = (
        CheckConstraint("segment IN ('STRATEGIC','LEVERAGE','BOTTLENECK','ROUTINE')", name="segment"),
        CheckConstraint("method IN ('AUTO','MANUAL')", name="method"),
        Index("ix_supplier_segment_supplier", "tenant_id", "supplier_id", "effective_to"),
        Index("uq_supplier_segment_current", "tenant_id", "supplier_id", unique=True, postgresql_where=text("effective_to IS NULL")),
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    segment: Mapped[str] = mapped_column(String(12), nullable=False)
    method: Mapped[str] = mapped_column(String(6), nullable=False, default="AUTO")
    spend_share: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False, default=0)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    criticality: Mapped[str] = mapped_column(String(10), nullable=False, default="LOW")
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    rule_set_version: Mapped[Optional[str]] = mapped_column(String(80))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class DevelopmentPlan(TenantScoped, Base):
    __tablename__ = "development_plan"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),
                      CheckConstraint("status IN ('DRAFT','ACTIVE','COMPLETED','CANCELLED')", name="status"),
                      Index("ix_development_plan_supplier", "tenant_id", "supplier_id"))
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="DRAFT")
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    capa_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.capa.id"))
    metric: Mapped[Optional[str]] = mapped_column(String(25))  # OTIF | PPM | INVOICE_ACCURACY | RFQ_RESPONSE | ESG
    baseline_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    target_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    result_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    outcome: Mapped[Optional[str]] = mapped_column(Text)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class DevelopmentAction(TenantScoped, Base):
    __tablename__ = "development_action"
    __table_args__ = (UniqueConstraint("tenant_id", "plan_id", "seq"),
                      CheckConstraint("status IN ('OPEN','DONE','CANCELLED')", name="status"),
                      Index("ix_development_action_due", "tenant_id", "status", "due_date"))
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.development_plan.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="OPEN")
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # [{note, ref, by, at}]
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reminders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SupplierAssessment(TenantScoped, Base):
    """ESG and cyber-security questionnaires (supplier portal input, buyer review) with their certificate evidence."""
    __tablename__ = "supplier_assessment"
    __table_args__ = (UniqueConstraint("tenant_id", "supplier_id", "kind", "as_of"),
                      CheckConstraint("kind IN ('ESG','CYBER')", name="kind"),
                      CheckConstraint("status IN ('SUBMITTED','ACCEPTED','REJECTED')", name="status"),
                      CheckConstraint("score >= 0 AND score <= 100", name="score_range"),
                      Index("ix_supplier_assessment_supplier", "tenant_id", "supplier_id", "kind"))
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(6), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    expires_on: Mapped[Optional[date]] = mapped_column(Date)
    answers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="SUBMITTED")
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # certificate numbers
    submitted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    review_note: Mapped[Optional[str]] = mapped_column(Text)
    rule_set_version: Mapped[Optional[str]] = mapped_column(String(80))
