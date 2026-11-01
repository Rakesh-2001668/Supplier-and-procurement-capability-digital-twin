"""Industry-template controls (blueprint §23, §23.1): planning parameters and Kanban (manufacturing), advance payment and bank
guarantees (construction), licence entitlements (IT), accessorial charges and index values (logistics), cold chain and par levels
(healthcare), purchasing cards (general). Every table is tenant-scoped with forced row-level security (migration 0012)."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.pic.db import SCHEMA, Base, TenantScoped

QTY = Numeric(18, 3)


def _fk(table: str):
    return ForeignKey(f"{SCHEMA}.{table}.id")


# ---------------------------------------------------------------- manufacturing (items 36, 37)
class PlanningParameter(TenantScoped, Base):
    """Reorder-point / min-max planning data per material and plant (MRP type VB; Kanban cards use the card table)."""
    __tablename__ = "planning_parameter"
    __table_args__ = (UniqueConstraint("tenant_id", "material_id", "plant"),
                      CheckConstraint("reorder_point >= 0", name="reorder_point_not_negative"),
                      CheckConstraint("max_stock IS NULL OR max_stock >= reorder_point", name="max_above_reorder_point"))
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("material"), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    reorder_point: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    max_stock: Mapped[Optional[Decimal]] = mapped_column(QTY)
    note: Mapped[Optional[str]] = mapped_column(Text)


class KanbanCard(TenantScoped, Base):
    __tablename__ = "kanban_card"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),
                      CheckConstraint("bin_qty > 0", name="bin_qty_positive"),
                      CheckConstraint("status IN ('FULL','EMPTY','REPLENISHING','SUSPENDED')", name="status"),
                      Index("ix_kanban_card_material_plant", "tenant_id", "material_id", "plant"))
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("material"), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    storage_location: Mapped[str] = mapped_column(String(10), nullable=False, default="0001")
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), _fk("supplier"))
    bin_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="FULL")
    requisition_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    signalled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    replenished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cycles: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# ---------------------------------------------------------------- construction (items 38, 39)
class BankGuarantee(TenantScoped, Base):
    __tablename__ = "bank_guarantee"
    __table_args__ = (UniqueConstraint("tenant_id", "number"), UniqueConstraint("tenant_id", "bank_name", "bank_ref"),
                      CheckConstraint("amount_minor > 0", name="amount_positive"),
                      CheckConstraint("expiry_date > issue_date", name="expiry_after_issue"),
                      CheckConstraint("kind IN ('PERFORMANCE','ADVANCE')", name="kind"),
                      CheckConstraint("status IN ('PENDING_VERIFICATION','ACTIVE','EXPIRED','RELEASED','CLAIMED')", name="status"),
                      Index("ix_bank_guarantee_po", "tenant_id", "po_id"))
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    kind: Mapped[str] = mapped_column(String(15), nullable=False)
    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("purchase_order"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("supplier"), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(120), nullable=False)
    bank_ref: Mapped[str] = mapped_column(String(60), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(25), nullable=False, default="PENDING_VERIFICATION")
    recorded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    verified_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    released_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    release_reason: Mapped[Optional[str]] = mapped_column(Text)
    alerts_sent: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)


class AdvancePayment(TenantScoped, Base):
    __tablename__ = "advance_payment"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),
                      CheckConstraint("net_minor > 0 AND gross_minor >= net_minor", name="amounts"),
                      CheckConstraint("recovered_minor >= 0 AND recovered_minor <= gross_minor", name="recovered_within_advance"),
                      CheckConstraint("status IN ('REQUESTED','APPROVED','REJECTED','PAID','RECOVERED','CANCELLED')", name="status"),
                      Index("ix_advance_payment_po", "tenant_id", "po_id"))
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("purchase_order"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("supplier"), nullable=False)
    net_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    gross_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recovery_pct: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)  # share of every running bill recovered
    recovered_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="REQUESTED")
    reference: Mapped[str] = mapped_column(String(60), nullable=False)  # supplier's advance invoice / proforma number
    reason: Mapped[Optional[str]] = mapped_column(Text)
    invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    guarantee_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), _fk("bank_guarantee"))
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    rule_set_version: Mapped[Optional[str]] = mapped_column(String(80))


class AdvanceRecovery(TenantScoped, Base):
    __tablename__ = "advance_recovery"
    __table_args__ = (UniqueConstraint("tenant_id", "advance_id", "invoice_id"),
                      CheckConstraint("amount_minor > 0", name="amount_positive"),
                      CheckConstraint("status IN ('PLANNED','APPLIED','CANCELLED')", name="status"))
    advance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("advance_payment"), nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("invoice"), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="PLANNED")


# ---------------------------------------------------------------- IT services (item 40)
class LicenceEntitlement(TenantScoped, Base):
    __tablename__ = "licence_entitlement"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),
                      CheckConstraint("entitled_qty > 0", name="entitled_positive"),
                      CheckConstraint("term_end > term_start", name="term_order"),
                      CheckConstraint("status IN ('ACTIVE','ENDED')", name="status"))
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    contract_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), _fk("contract"))
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("supplier"), nullable=False)
    product: Mapped[str] = mapped_column(String(120), nullable=False)
    metric: Mapped[str] = mapped_column(String(20), nullable=False, default="USER")
    entitled_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)  # per licence per year
    term_start: Mapped[date] = mapped_column(Date, nullable=False)
    term_end: Mapped[date] = mapped_column(Date, nullable=False)  # renewal date
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ACTIVE")
    peak_used_qty: Mapped[Optional[Decimal]] = mapped_column(QTY)
    utilisation_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2))
    unused_qty: Mapped[Optional[Decimal]] = mapped_column(QTY)
    potential_saving_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    last_usage_on: Mapped[Optional[date]] = mapped_column(Date)
    flag: Mapped[Optional[str]] = mapped_column(String(15))  # UNUSED when utilisation is below the rule threshold
    flagged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class LicenceUsage(TenantScoped, Base):
    __tablename__ = "licence_usage"
    __table_args__ = (UniqueConstraint("tenant_id", "entitlement_id", "as_of"), CheckConstraint("used_qty >= 0", name="used_not_negative"))
    entitlement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("licence_entitlement"), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    used_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    source: Mapped[str] = mapped_column(String(15), nullable=False, default="IMPORT")  # IMPORT | API | MANUAL


# ---------------------------------------------------------------- logistics (item 41)
class AccessorialRate(TenantScoped, Base):
    __tablename__ = "accessorial_rate"
    __table_args__ = (CheckConstraint("rate_minor >= 0 AND free_units >= 0", name="not_negative"),
                      CheckConstraint("unit IN ('HOUR','DAY','TRIP')", name="unit"),
                      Index("ix_accessorial_rate_lookup", "tenant_id", "charge_type", "supplier_id"))
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), _fk("supplier"))  # carrier; None = every carrier
    lane: Mapped[Optional[str]] = mapped_column(String(40))  # None = every lane
    charge_type: Mapped[str] = mapped_column(String(15), nullable=False)  # DETENTION | DEMURRAGE | LOADING | UNLOADING | WAITING
    unit: Mapped[str] = mapped_column(String(5), nullable=False, default="HOUR")
    free_units: Mapped[Decimal] = mapped_column(QTY, nullable=False, default=0)
    rate_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[Optional[date]] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AccessorialCharge(TenantScoped, Base):
    __tablename__ = "accessorial_charge"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),
                      CheckConstraint("units > 0 AND billable_units >= 0 AND amount_minor >= 0", name="amounts"),
                      CheckConstraint("status IN ('CLAIMED','APPROVED','REJECTED','BLOCKED')", name="status"),
                      Index("ix_accessorial_charge_po_line", "tenant_id", "po_line_id"))
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("purchase_order"), nullable=False)
    po_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("po_line"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("supplier"), nullable=False)
    lane: Mapped[Optional[str]] = mapped_column(String(40))
    charge_type: Mapped[str] = mapped_column(String(15), nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    units: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    free_units: Mapped[Decimal] = mapped_column(QTY, nullable=False, default=0)
    billable_units: Mapped[Decimal] = mapped_column(QTY, nullable=False, default=0)
    rate_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    pod_ses_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), _fk("service_entry"))
    ses_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), _fk("service_entry"))
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="CLAIMED")
    reason: Mapped[Optional[str]] = mapped_column(Text)
    rate_rule: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class FreightMovement(TenantScoped, Base):
    """Distance and payload of a freight trip, the denominator of the cost-per-tonne-km KPI."""
    __tablename__ = "freight_movement"
    __table_args__ = (UniqueConstraint("tenant_id", "reference"),
                      CheckConstraint("distance_km > 0 AND payload_tonnes > 0", name="positive"))
    reference: Mapped[str] = mapped_column(String(60), nullable=False)  # LR / consignment note number
    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("purchase_order"), nullable=False)
    po_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("po_line"), nullable=False)
    ses_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), _fk("service_entry"))
    lane: Mapped[Optional[str]] = mapped_column(String(40))
    distance_km: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    payload_tonnes: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    moved_on: Mapped[date] = mapped_column(Date, nullable=False)


class IndexValue(TenantScoped, Base):
    """Published index values (diesel, aluminium, ...) fed by import or API; contract index resets read them."""
    __tablename__ = "index_value"
    __table_args__ = (UniqueConstraint("tenant_id", "index_code", "as_of"), CheckConstraint("value > 0", name="value_positive"),
                      CheckConstraint("source IN ('IMPORT','API','MANUAL')", name="source"))
    index_code: Mapped[str] = mapped_column(String(30), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="IMPORT")
    source_ref: Mapped[Optional[str]] = mapped_column(String(80))


# ---------------------------------------------------------------- healthcare (items 43, 44)
class ColdChainSpec(TenantScoped, Base):
    __tablename__ = "cold_chain_spec"
    __table_args__ = (UniqueConstraint("tenant_id", "material_id"), CheckConstraint("max_c > min_c", name="range"))
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("material"), nullable=False)
    min_c: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    max_c: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    max_excursion_minutes: Mapped[Optional[int]] = mapped_column(Integer)  # None = the COLD-CHAIN rule default
    label: Mapped[Optional[str]] = mapped_column(String(40))


class ColdChainReading(TenantScoped, Base):
    __tablename__ = "cold_chain_reading"
    __table_args__ = (UniqueConstraint("tenant_id", "logger_id", "object_type", "object_id", "material_id"),
                      CheckConstraint("object_type IN ('ASN','GOODS_RECEIPT')", name="object_type"),
                      CheckConstraint("status IN ('OK','EXCURSION','QUARANTINED','RELEASED','REJECTED')", name="status"),
                      Index("ix_cold_chain_reading_object", "tenant_id", "object_type", "object_id"))
    logger_id: Mapped[str] = mapped_column(String(40), nullable=False)
    object_type: Mapped[str] = mapped_column(String(15), nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    object_ref: Mapped[str] = mapped_column(String(40), nullable=False)
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("material"), nullable=False)
    po_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    batch: Mapped[Optional[str]] = mapped_column(String(30))
    readings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # [{"at": iso, "tempC": 5.1}, ...]
    min_seen_c: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    max_seen_c: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    excursion_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="OK")
    quarantined_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False, default=0)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    disposition_note: Mapped[Optional[str]] = mapped_column(Text)
    spec: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # range and allowance applied when evaluated


class ParLevel(TenantScoped, Base):
    __tablename__ = "par_level"
    __table_args__ = (UniqueConstraint("tenant_id", "plant", "storage_location", "material_id"),
                      CheckConstraint("par_qty > 0 AND trigger_qty >= 0 AND trigger_qty < par_qty", name="levels"))
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    storage_location: Mapped[str] = mapped_column(String(10), nullable=False)
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("material"), nullable=False)
    par_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)  # replenish up to this quantity
    trigger_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)  # replenish when on hand falls to or below this
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_replenished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    open_requisition_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))


# ---------------------------------------------------------------- general (item 45)
class PCard(TenantScoped, Base):
    __tablename__ = "pcard"
    __table_args__ = (UniqueConstraint("tenant_id", "number"), UniqueConstraint("tenant_id", "issuer", "card_last4", "holder_name"),
                      CheckConstraint("per_txn_limit_minor > 0 AND monthly_limit_minor >= per_txn_limit_minor", name="limits"),
                      CheckConstraint("status IN ('ACTIVE','SUSPENDED','CLOSED')", name="status"))
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    holder_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    holder_name: Mapped[str] = mapped_column(String(120), nullable=False)
    issuer: Mapped[str] = mapped_column(String(60), nullable=False)
    card_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    per_txn_limit_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    monthly_limit_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    blocked_mccs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    allowed_mccs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # empty = every category not blocked
    cost_object_type: Mapped[Optional[str]] = mapped_column(String(20))
    cost_object_code: Mapped[Optional[str]] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ACTIVE")
    valid_to: Mapped[Optional[date]] = mapped_column(Date)


class PCardStatement(TenantScoped, Base):
    __tablename__ = "pcard_statement"
    __table_args__ = (UniqueConstraint("tenant_id", "number"), UniqueConstraint("tenant_id", "issuer", "period"),
                      CheckConstraint("status IN ('IMPORTED','RECONCILED')", name="status"))
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    issuer: Mapped[str] = mapped_column(String(60), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="IMPORTED")
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    imported_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class PCardTransaction(TenantScoped, Base):
    __tablename__ = "pcard_transaction"
    __table_args__ = (UniqueConstraint("tenant_id", "pcard_id", "txn_ref"),
                      CheckConstraint("amount_minor > 0", name="amount_positive"),
                      CheckConstraint("status IN ('MATCHED','UNMATCHED','EXCEPTION','CLEARED')", name="status"),
                      Index("ix_pcard_transaction_card_date", "tenant_id", "pcard_id", "txn_date"))
    statement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("pcard_statement"), nullable=False)
    pcard_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("pcard"), nullable=False)
    txn_ref: Mapped[str] = mapped_column(String(60), nullable=False)
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    merchant: Mapped[str] = mapped_column(String(120), nullable=False)
    mcc: Mapped[str] = mapped_column(String(4), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    po_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), _fk("purchase_order"))
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="UNMATCHED")
    exception_codes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    review_note: Mapped[Optional[str]] = mapped_column(Text)
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
