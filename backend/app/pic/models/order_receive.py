"""M08 purchase orders (F5) and M09 ASN, goods receipt, quality, service entry (F6)."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.pic.db import SCHEMA, Base, TenantScoped

QTY = Numeric(18, 3)

PO_STATUSES = ("DRAFT", "IN_APPROVAL", "RELEASED", "TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED",
               "RECEIVED", "INVOICED", "CLOSED", "CANCELLED")


class PurchaseOrder(TenantScoped, Base):
    __tablename__ = "purchase_order"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number"),
        CheckConstraint("status IN (" + ",".join(f"'{s}'" for s in PO_STATUSES) + ")", name="status"),
    )
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)
    purch_org: Mapped[str] = mapped_column(String(10), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    contract_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    purpose_code: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    payment_terms: Mapped[str] = mapped_column(String(10), nullable=False)
    incoterms: Mapped[Optional[str]] = mapped_column(String(40))
    tolerance: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"over_pct":2,"under_pct":5,"price_pct":1}
    inherited: Mapped[dict] = mapped_column(JSONB, default=dict)
    overrides: Mapped[list] = mapped_column(JSONB, default=list)  # P07: flagged manual overrides with reason
    risk_score: Mapped[Optional[int]] = mapped_column(Integer)
    risk_factors: Mapped[list] = mapped_column(JSONB, default=list)
    touchless: Mapped[Optional[bool]] = mapped_column(Boolean)
    touchless_reasons: Mapped[list] = mapped_column(JSONB, default=list)
    released_by: Mapped[Optional[str]] = mapped_column(String(80))
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    transmitted_via: Mapped[Optional[str]] = mapped_column(String(20))
    transmitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    confirmation_due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rule_set_version: Mapped[str] = mapped_column(String(120), nullable=False)
    erp_doc_no: Mapped[Optional[str]] = mapped_column(String(40))
    retention_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))  # construction/subcontract retention withheld per invoice


class PoLine(TenantScoped, Base):
    __tablename__ = "po_line"
    __table_args__ = (
        UniqueConstraint("tenant_id", "po_id", "line_no"),
        Index("ix_po_line_material_plant", "tenant_id", "material_id", "plant"),
        # §5.2: a contract-priced line outside tolerance must carry a justification.
        CheckConstraint("NOT price_deviation OR deviation_reason IS NOT NULL", name="deviation_reason"),
    )
    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.purchase_order.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    item_type: Mapped[str] = mapped_column(String(15), nullable=False)
    purchase_type: Mapped[str] = mapped_column(String(15), nullable=False)
    material_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"))
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    material_group: Mapped[str] = mapped_column(String(30), nullable=False)
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    uom: Mapped[str] = mapped_column(String(5), nullable=False)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    net_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    hsn_code: Mapped[Optional[str]] = mapped_column(String(10))
    need_date: Mapped[date] = mapped_column(Date, nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    storage_location: Mapped[Optional[str]] = mapped_column(String(10))
    account_assignment_type: Mapped[Optional[str]] = mapped_column(String(20))
    account_assignment_code: Mapped[Optional[str]] = mapped_column(String(30))
    gr_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ir_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ses_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ers: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quality_managed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    price_source: Mapped[str] = mapped_column(String(15), nullable=False)  # CONTRACT | CATALOGUE | INFO_RECORD | MANUAL | QUOTE
    contract_line_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    price_validity_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    price_deviation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deviation_reason: Mapped[Optional[str]] = mapped_column(Text)
    requisition_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    pr_line_no: Mapped[Optional[int]] = mapped_column(Integer)
    shipped_qty: Mapped[Decimal] = mapped_column(QTY, default=0)
    received_qty: Mapped[Decimal] = mapped_column(QTY, default=0)
    accepted_qty: Mapped[Decimal] = mapped_column(QTY, default=0)
    rejected_qty: Mapped[Decimal] = mapped_column(QTY, default=0)
    ses_approved_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    invoiced_qty: Mapped[Decimal] = mapped_column(QTY, default=0)
    invoiced_minor: Mapped[int] = mapped_column(BigInteger, default=0)


class PoVersion(TenantScoped, Base):
    __tablename__ = "po_version"
    __table_args__ = (UniqueConstraint("tenant_id", "po_id", "version"),)
    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.purchase_order.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    change_reason: Mapped[Optional[str]] = mapped_column(Text)
    changes: Mapped[list] = mapped_column(JSONB, default=list)


class PoConfirmation(TenantScoped, Base):
    __tablename__ = "po_confirmation"
    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.purchase_order.id"), nullable=False)
    po_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # CONFIRMED | REJECTED | CHANGE_REQUESTED
    confirmed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    lines: Mapped[list] = mapped_column(JSONB, default=list)
    note: Mapped[Optional[str]] = mapped_column(Text)
    hours_to_confirm: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))


class Asn(TenantScoped, Base):
    __tablename__ = "asn"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.purchase_order.id"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="IN_TRANSIT")  # IN_TRANSIT | RECEIVED
    ship_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_date: Mapped[date] = mapped_column(Date, nullable=False)
    eway_bill_no: Mapped[Optional[str]] = mapped_column(String(20))
    eway_bill_valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    vehicle_no: Mapped[Optional[str]] = mapped_column(String(15))
    documents: Mapped[list] = mapped_column(JSONB, default=list)  # CoC, packing list


class AsnLine(TenantScoped, Base):
    __tablename__ = "asn_line"
    __table_args__ = (Index("ix_asn_line_asn", "tenant_id", "asn_id"), Index("ix_asn_line_po_line", "tenant_id", "po_line_id"))
    asn_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.asn.id"), nullable=False)
    po_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.po_line.id"), nullable=False)
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    batches: Mapped[list] = mapped_column(JSONB, default=list)  # [{"batch":..,"qty":..,"expiry":..}]
    received_qty: Mapped[Decimal] = mapped_column(QTY, default=0)


class GoodsReceipt(TenantScoped, Base):
    __tablename__ = "goods_receipt"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.purchase_order.id"), nullable=False)
    asn_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # POSTED | QUALITY_HOLD | ACCEPTED | PARTIALLY_REJECTED | REJECTED | REVERSED
    posting_date: Mapped[date] = mapped_column(Date, nullable=False)
    delivery_note: Mapped[Optional[str]] = mapped_column(String(40))
    posted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reversal_of: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))


class GrLine(TenantScoped, Base):
    __tablename__ = "gr_line"
    gr_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.goods_receipt.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    po_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.po_line.id"), nullable=False)
    material_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    accepted_qty: Mapped[Decimal] = mapped_column(QTY, default=0)
    rejected_qty: Mapped[Decimal] = mapped_column(QTY, default=0)
    batch: Mapped[str] = mapped_column(String(30), default="")
    serials: Mapped[list] = mapped_column(JSONB, default=list)
    expiry: Mapped[Optional[date]] = mapped_column(Date)
    stock_type: Mapped[str] = mapped_column(String(15), nullable=False)
    storage_location: Mapped[str] = mapped_column(String(10), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(5), nullable=False, default="101")


class InspectionLot(TenantScoped, Base):
    __tablename__ = "inspection_lot"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    gr_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.goods_receipt.id"), nullable=False)
    gr_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.gr_line.id"), nullable=False)
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")  # OPEN | DECIDED
    accepted_qty: Mapped[Optional[Decimal]] = mapped_column(QTY)
    rejected_qty: Mapped[Optional[Decimal]] = mapped_column(QTY)
    defect_code: Mapped[Optional[str]] = mapped_column(String(40))
    usage_decision: Mapped[Optional[str]] = mapped_column(String(25))
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))


class ReturnDelivery(TenantScoped, Base):
    __tablename__ = "return_delivery"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    gr_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.goods_receipt.id"), nullable=False)
    po_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.po_line.id"), nullable=False)
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    replacement_required: Mapped[bool] = mapped_column(Boolean, default=False)
    credit_note_expected: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="CREATED")


class ServiceEntry(TenantScoped, Base):
    __tablename__ = "service_entry"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.purchase_order.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="DRAFT")  # DRAFT | SUBMITTED | APPROVED | REJECTED | REVOKED
    method: Mapped[str] = mapped_column(String(15), nullable=False)  # MILESTONE | TIME_MATERIAL | UNIT_RATE | PROGRESS
    period_from: Mapped[date] = mapped_column(Date, nullable=False)
    period_to: Mapped[date] = mapped_column(Date, nullable=False)
    total_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    entered_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approver_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))


class SesLine(TenantScoped, Base):
    __tablename__ = "ses_line"
    ses_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.service_entry.id"), nullable=False)
    po_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.po_line.id"), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)  # hours, units or progress %
    unit_rate_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
