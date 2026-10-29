"""M10 invoices and payments (F7), M11 savings ledger and M01 spend lines."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.pic.db import SCHEMA, Base, TenantScoped

QTY = Numeric(18, 3)


class Invoice(TenantScoped, Base):
    __tablename__ = "invoice"
    __table_args__ = (
        # §5.2: hard duplicate key per supplier invoice number and fiscal year.
        UniqueConstraint("tenant_id", "company_code", "supplier_id", "supplier_invoice_no", "fiscal_year"),
        # Internal document number (payables._internal_number) is the key every screen, payment run and lookup uses.
        UniqueConstraint("tenant_id", "number", name="uq_invoice_tenant_number"),
    )
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    supplier_invoice_no: Mapped[str] = mapped_column(String(40), nullable=False)
    fiscal_year: Mapped[str] = mapped_column(String(7), nullable=False)
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    po_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.purchase_order.id"))
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    channel: Mapped[str] = mapped_column(String(15), nullable=False)  # PORTAL | PDF_OCR | E_INVOICE | EDI
    irn: Mapped[Optional[str]] = mapped_column(String(64))
    irn_valid: Mapped[Optional[bool]] = mapped_column(Boolean)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    net_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gross_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="CAPTURED")
    match_type: Mapped[Optional[str]] = mapped_column(String(10))  # 2WAY | 3WAY | SES | ERS
    first_pass_matched: Mapped[Optional[bool]] = mapped_column(Boolean)
    payment_block: Mapped[bool] = mapped_column(Boolean, default=False)
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    retention_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")  # withheld until release
    erp_doc_no: Mapped[Optional[str]] = mapped_column(String(40))
    posting_key: Mapped[Optional[str]] = mapped_column(String(200))
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    payment_status: Mapped[str] = mapped_column(String(15), default="UNPAID")
    rule_set_version: Mapped[Optional[str]] = mapped_column(String(80))
    duplicate_of: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))


class InvoiceLine(TenantScoped, Base):
    __tablename__ = "invoice_line"
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.invoice.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    po_line_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.po_line.id"))
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    net_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    hsn_code: Mapped[Optional[str]] = mapped_column(String(10))
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    tax_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    match_status: Mapped[Optional[str]] = mapped_column(String(15))
    match_detail: Mapped[dict] = mapped_column(JSONB, default=dict)


class InvoiceException(TenantScoped, Base):
    __tablename__ = "invoice_exception"
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.invoice.id"), nullable=False)
    invoice_line_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # PRICE | QUANTITY | SERVICE | TAX | DUPLICATE | MISSING_GR
    delta: Mapped[dict] = mapped_column(JSONB, default=dict)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_action: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="OPEN")  # OPEN | RESOLVED
    resolution: Mapped[Optional[str]] = mapped_column(String(30))
    resolution_note: Mapped[Optional[str]] = mapped_column(Text)
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    ai_ref: Mapped[Optional[str]] = mapped_column(String(80))


class CreditNote(TenantScoped, Base):
    __tablename__ = "credit_note"
    __table_args__ = (UniqueConstraint("tenant_id", "supplier_id", "supplier_credit_note_no"),
                      UniqueConstraint("tenant_id", "supplier_id", "number", name="uq_credit_note_supplier_number"))
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    supplier_credit_note_no: Mapped[str] = mapped_column(String(40), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.invoice.id"), nullable=False)
    note_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    net_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gross_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lines: Mapped[list] = mapped_column(JSONB, default=list)  # [{"invoice_line_no":1,"qty":"20"}]


class Payment(TenantScoped, Base):
    __tablename__ = "payment"
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.invoice.id"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    bank_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    value_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="COMPLETED")
    run_ref: Mapped[str] = mapped_column(String(30), nullable=False)
    approved_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    __table_args__ = (
        # One live payment per invoice: blocks double payment at the database level.
        Index("uq_payment_invoice_live", "tenant_id", "invoice_id", unique=True,
              postgresql_where=text("status <> 'CANCELLED'")),
    )


class SavingsInitiative(TenantScoped, Base):
    __tablename__ = "savings_initiative"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    material_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    source_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    stage: Mapped[str] = mapped_column(String(15), nullable=False, default="IDENTIFIED")
    baseline_method: Mapped[str] = mapped_column(String(20), nullable=False)  # fixed at creation
    baseline_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    new_price_minor: Mapped[Optional[int]] = mapped_column(BigInteger)  # weighted award price
    annual_volume: Mapped[Optional[Decimal]] = mapped_column(QTY)
    supplier_prices: Mapped[dict] = mapped_column(JSONB, default=dict)  # supplier_id -> agreed unit price
    validated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class SavingsLedgerEntry(TenantScoped, Base):
    __tablename__ = "savings_ledger_entry"
    __table_args__ = (UniqueConstraint("tenant_id", "initiative_id", "type", "source_ref"),)
    initiative_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.savings_initiative.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(15), nullable=False)  # NEGOTIATED | AVOIDANCE | REALISED
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    counts_toward_budget: Mapped[bool] = mapped_column(Boolean, nullable=False)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(60), nullable=False)
    posting_date: Mapped[date] = mapped_column(Date, nullable=False)


class SpendLine(TenantScoped, Base):
    __tablename__ = "spend_line"
    __table_args__ = (UniqueConstraint("tenant_id", "invoice_line_id"),)
    invoice_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    invoice_ref: Mapped[str] = mapped_column(String(60), nullable=False)
    po_ref: Mapped[Optional[str]] = mapped_column(String(60))
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    material_group: Mapped[str] = mapped_column(String(30), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)
    cost_object: Mapped[Optional[str]] = mapped_column(String(40))
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    contracted: Mapped[bool] = mapped_column(Boolean, default=False)
    addressable: Mapped[bool] = mapped_column(Boolean, default=True)
    maverick_flags: Mapped[list] = mapped_column(JSONB, default=list)
    classification_confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=1)
    description: Mapped[Optional[str]] = mapped_column(String(300))
    po_line_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    price_variance_minor: Mapped[Optional[int]] = mapped_column(BigInteger)  # above contract / standard price (PPV)
    source: Mapped[str] = mapped_column(String(20), default="PLATFORM")  # PLATFORM | ERP_HISTORY | LEGACY
