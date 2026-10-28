"""Master data: suppliers (M06), materials (M03), sourcing master data,
catalogue, budgets and stock."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, LargeBinary, Numeric,
    String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.pic.db import SCHEMA, Base, TenantScoped

QTY = Numeric(18, 3)


class Supplier(TenantScoped, Base):
    __tablename__ = "supplier"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Status across the whole relationship; per-category status lives in supplier_category_status.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="REGISTERED")
    gstin_enc: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    gstin_masked: Mapped[Optional[str]] = mapped_column(String(20))
    gstin_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    pan_hash: Mapped[Optional[str]] = mapped_column(String(64))
    state_code: Mapped[Optional[str]] = mapped_column(String(2))
    country: Mapped[str] = mapped_column(String(2), default="IN")
    segment: Mapped[Optional[str]] = mapped_column(String(20))  # STRATEGIC | LEVERAGE | BOTTLENECK | ROUTINE
    risk_tier: Mapped[Optional[str]] = mapped_column(String(10))
    payment_terms: Mapped[str] = mapped_column(String(10), default="N60")
    incoterms: Mapped[Optional[str]] = mapped_column(String(40))
    twin_ref: Mapped[Optional[str]] = mapped_column(String(40))
    screening: Mapped[dict] = mapped_column(JSONB, default=dict)
    contact_email: Mapped[Optional[str]] = mapped_column(String(200))
    address: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")  # line1, line2, city, state_code, pin, country
    punchout: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")  # protocol, url, identity (no secrets)
    punchout_secret_enc: Mapped[Optional[str]] = mapped_column(Text)
    order_channel: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")  # channels [PORTAL|EDI|EMAIL], ediId, email


class SupplierCategoryStatus(TenantScoped, Base):
    """Qualification is per category (blueprint §12.2)."""
    __tablename__ = "supplier_category_status"
    __table_args__ = (UniqueConstraint("tenant_id", "supplier_id", "category"),)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(25), nullable=False, default="REGISTERED")
    waiver_reason: Mapped[Optional[str]] = mapped_column(Text)
    qualified_on: Mapped[Optional[date]] = mapped_column(Date)


class Qualification(TenantScoped, Base):
    __tablename__ = "qualification"
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")  # OPEN | DECIDED
    questionnaire: Mapped[dict] = mapped_column(JSONB, default=dict)
    questionnaire_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    audit_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    sample_approval: Mapped[Optional[str]] = mapped_column(String(20))  # PPAP_APPROVED | REJECTED
    decision: Mapped[Optional[str]] = mapped_column(String(20))
    decision_reason: Mapped[Optional[str]] = mapped_column(Text)


class Certificate(TenantScoped, Base):
    __tablename__ = "certificate"
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False)  # IATF16949, ISO14001, ...
    number: Mapped[str] = mapped_column(String(60), nullable=False)
    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    expires_on: Mapped[date] = mapped_column(Date, nullable=False)
    mandatory_for: Mapped[list] = mapped_column(ARRAY(String(40)), default=list)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="VALID")  # VALID | EXPIRED


class SupplierBankAccount(TenantScoped, Base):
    __tablename__ = "supplier_bank_account"
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    account_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    account_masked: Mapped[str] = mapped_column(String(30), nullable=False)
    ifsc: Mapped[str] = mapped_column(String(11), nullable=False)
    holder_name: Mapped[str] = mapped_column(String(200), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_on: Mapped[Optional[date]] = mapped_column(Date)
    payable_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))  # end of cooling-off


class BankChangeRequest(TenantScoped, Base):
    """MDM-04 supplier bank change: two finance approvers, call-back, cooling-off."""
    __tablename__ = "bank_change_request"
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    bank_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier_bank_account.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(25), nullable=False, default="PENDING_CALLBACK")
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    callback_verified_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    callback_note: Mapped[Optional[str]] = mapped_column(Text)
    approvals: Mapped[list] = mapped_column(JSONB, default=list)


class SanctionEntry(TenantScoped, Base):
    __tablename__ = "sanction_entry"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(String(60), nullable=False)
    identifier_hash: Mapped[Optional[str]] = mapped_column(String(64))


class TwinSnapshot(TenantScoped, Base):
    """Read model from the Supplier Capability Digital Twin (§12.3)."""
    __tablename__ = "twin_snapshot"
    __table_args__ = (UniqueConstraint("tenant_id", "supplier_id", "category"),)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    capability: Mapped[dict] = mapped_column(JSONB, default=dict)
    evidence_level: Mapped[str] = mapped_column(String(10), nullable=False)  # E1..E4
    free_capacity_per_month: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    trust_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    late_delivery_prob: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    model_version: Mapped[str] = mapped_column(String(40), default="eta-v3")
    ppm: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 1))
    lead_time_days: Mapped[Optional[int]] = mapped_column(Integer)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)


class TwinFeedback(TenantScoped, Base):
    """Performance written back to the twin (OTIF, PPM, invoice accuracy)."""
    __tablename__ = "twin_feedback"
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    metric: Mapped[str] = mapped_column(String(30), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    source_event: Mapped[str] = mapped_column(String(60), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(60), nullable=False)


class Scorecard(TenantScoped, Base):
    __tablename__ = "scorecard"
    __table_args__ = (UniqueConstraint("tenant_id", "supplier_id", "period"),)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    receipts: Mapped[int] = mapped_column(Integer, default=0)
    on_time_in_full: Mapped[int] = mapped_column(Integer, default=0)
    qty_received: Mapped[Decimal] = mapped_column(QTY, default=0)
    qty_rejected: Mapped[Decimal] = mapped_column(QTY, default=0)
    invoices: Mapped[int] = mapped_column(Integer, default=0)
    invoices_first_pass: Mapped[int] = mapped_column(Integer, default=0)
    otif_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2))
    ppm: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 1))
    invoice_accuracy_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2))


class Material(TenantScoped, Base):
    __tablename__ = "material"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # STOCK | NON_STOCK | SERVICE
    material_group: Mapped[str] = mapped_column(String(30), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    base_uom: Mapped[str] = mapped_column(String(5), nullable=False)
    valuation_class: Mapped[Optional[str]] = mapped_column(String(10))
    hsn_code: Mapped[Optional[str]] = mapped_column(String(10))
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=18)
    mpn: Mapped[Optional[str]] = mapped_column(String(60))
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)
    mrp_type: Mapped[str] = mapped_column(String(4), default="ND")  # PD = MRP active, ND = no planning
    lot_size_policy: Mapped[str] = mapped_column(String(10), default="EXACT")
    lot_size_qty: Mapped[Optional[Decimal]] = mapped_column(QTY)
    min_lot: Mapped[Optional[Decimal]] = mapped_column(QTY)
    max_lot: Mapped[Optional[Decimal]] = mapped_column(QTY)
    pack_size: Mapped[Optional[Decimal]] = mapped_column(QTY)
    safety_stock: Mapped[Decimal] = mapped_column(QTY, default=0)
    planned_delivery_days: Mapped[int] = mapped_column(Integer, default=0)
    gr_processing_days: Mapped[int] = mapped_column(Integer, default=0)
    quality_managed: Mapped[bool] = mapped_column(Boolean, default=False)
    standard_price_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    annual_demand: Mapped[Optional[Decimal]] = mapped_column(QTY)
    ordering_cost_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    holding_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    erp_synced: Mapped[bool] = mapped_column(Boolean, default=False)


class MaterialRequest(TenantScoped, Base):
    """F9 material master governance request."""
    __tablename__ = "material_request"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(25), nullable=False, default="DRAFT")
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    material_group: Mapped[str] = mapped_column(String(30), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    base_uom: Mapped[str] = mapped_column(String(5), nullable=False)
    valuation_class: Mapped[Optional[str]] = mapped_column(String(10))
    hsn_code: Mapped[Optional[str]] = mapped_column(String(10))
    mpn: Mapped[Optional[str]] = mapped_column(String(60))
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_pr_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    source_pr_line: Mapped[Optional[int]] = mapped_column(Integer)
    duplicate_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 3))
    duplicate_candidates: Mapped[list] = mapped_column(JSONB, default=list)
    override_reason: Mapped[Optional[str]] = mapped_column(Text)
    material_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    merged_into_material_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    rule_set_version: Mapped[Optional[str]] = mapped_column(String(80))


class InfoRecord(TenantScoped, Base):
    """Purchasing info record: last price and lead time per supplier and material."""
    __tablename__ = "info_record"
    __table_args__ = (UniqueConstraint("tenant_id", "supplier_id", "material_id", "plant"),)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    last_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)


class SourceList(TenantScoped, Base):
    __tablename__ = "source_list"
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    fixed: Mapped[bool] = mapped_column(Boolean, default=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)


class QuotaArrangement(TenantScoped, Base):
    __tablename__ = "quota_arrangement"
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)
    source_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))


class QuotaLine(TenantScoped, Base):
    __tablename__ = "quota_line"
    quota_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.quota_arrangement.id"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    contract_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    share: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    allocated_qty: Mapped[Decimal] = mapped_column(QTY, default=0)  # running quota counter


class CatalogueItem(TenantScoped, Base):
    __tablename__ = "catalogue_item"
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    supplier_part_no: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    material_group: Mapped[str] = mapped_column(String(30), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    material_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    contract_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    uom: Mapped[str] = mapped_column(String(5), nullable=False)
    price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=18)
    hsn_code: Mapped[Optional[str]] = mapped_column(String(10))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Budget(TenantScoped, Base):
    __tablename__ = "budget"
    __table_args__ = (
        UniqueConstraint("tenant_id", "cost_object_type", "cost_object_code", "fiscal_year"),
        CheckConstraint("control IN ('HARD','SOFT')", name="control"),
    )
    cost_object_type: Mapped[str] = mapped_column(String(20), nullable=False)
    cost_object_code: Mapped[str] = mapped_column(String(30), nullable=False)
    fiscal_year: Mapped[str] = mapped_column(String(7), nullable=False)  # 2026-27
    control: Mapped[str] = mapped_column(String(4), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    committed_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    consumed_minor: Mapped[int] = mapped_column(BigInteger, default=0)


class BudgetCommitment(TenantScoped, Base):
    __tablename__ = "budget_commitment"
    budget_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.budget.id"), nullable=False)
    object_type: Mapped[str] = mapped_column(String(40), nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    object_ref: Mapped[str] = mapped_column(String(60), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")  # OPEN | RELEASED | CONSUMED
    justification: Mapped[Optional[str]] = mapped_column(Text)


class Stock(TenantScoped, Base):
    __tablename__ = "stock"
    __table_args__ = (UniqueConstraint("tenant_id", "material_id", "plant", "storage_location", "stock_type", "batch"),)
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    storage_location: Mapped[str] = mapped_column(String(10), nullable=False)
    stock_type: Mapped[str] = mapped_column(String(15), nullable=False)  # UNRESTRICTED | QUALITY | BLOCKED
    batch: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False, default=0)


class StockMovement(TenantScoped, Base):
    __tablename__ = "stock_movement"
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    storage_location: Mapped[str] = mapped_column(String(10), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(5), nullable=False)  # 101 GR, 321 QI release, 122 return, 102 reversal
    stock_type: Mapped[str] = mapped_column(String(15), nullable=False)
    batch: Mapped[str] = mapped_column(String(30), default="")
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    reference_type: Mapped[str] = mapped_column(String(40), nullable=False)
    reference_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reference_ref: Mapped[str] = mapped_column(String(60), nullable=False)
