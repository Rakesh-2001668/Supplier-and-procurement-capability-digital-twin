"""Wave 1 procure-to-pay completion: debit notes (M10), inbound EDI interchanges (INVOIC), early-payment / supply-chain-finance
offers (M10), receipt tolerances per material and supplier (M09)."""
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.pic.db import SCHEMA, Base, TenantScoped

DEBIT_NOTE_STATUSES = ("RECEIVED", "MATCHED", "PENDING_APPROVAL", "APPROVED", "POSTED", "REJECTED")
OFFER_STATUSES = ("OFFERED", "ACCEPTED", "DECLINED", "EXPIRED", "APPLIED", "CANCELLED")


class DebitNote(TenantScoped, Base):
    """Supplier debit note against an invoice: an upward price correction or an additional charge (GST s.34 debit note).
    Matched, approved and posted to the ERP as a vendor debit memo; the amount nets into the payment of its invoice."""
    __tablename__ = "debit_note"
    __table_args__ = (
        UniqueConstraint("tenant_id", "supplier_id", "supplier_debit_note_no", name="uq_debit_note_supplier_no"),
        UniqueConstraint("tenant_id", "number", name="uq_debit_note_tenant_number"),
        CheckConstraint("status IN (" + ",".join(f"'{s}'" for s in DEBIT_NOTE_STATUSES) + ")", name="status"),
        CheckConstraint("net_minor > 0 AND tax_minor >= 0 AND gross_minor = net_minor + tax_minor", name="amounts"),
        Index("ix_debit_note_invoice", "tenant_id", "invoice_id"),
    )
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    supplier_debit_note_no: Mapped[str] = mapped_column(String(40), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.invoice.id"), nullable=False)
    note_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RECEIVED")
    net_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gross_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    retention_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    # [{"kind": "PRICE", "invoice_line": 10, "qty": "20", "unitDebitMinor": 150, "netMinor": .., "taxMinor": .., "gstRate": "18"},
    #  {"kind": "CHARGE", "description": "Freight", "netMinor": .., "taxMinor": .., "gstRate": "18", "hsn": "9965"}]
    lines: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    match_result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    posting_key: Mapped[Optional[str]] = mapped_column(String(200))
    erp_doc_no: Mapped[Optional[str]] = mapped_column(String(40))
    payment_status: Mapped[str] = mapped_column(String(15), nullable=False, default="UNPAID", server_default="UNPAID")
    rule_set_version: Mapped[Optional[str]] = mapped_column(String(80))


class EdiInterchange(TenantScoped, Base):
    """One inbound EDIFACT interchange, kept once per sender and control reference: the idempotency anchor of the inbound
    channel and the record behind the CONTRL / APERAK acknowledgements returned to the gateway."""
    __tablename__ = "edi_interchange"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sender", "control_ref", name="uq_edi_interchange_ref"),
        CheckConstraint("status IN ('ACCEPTED','PARTIAL','REJECTED')", name="status"),
    )
    sender: Mapped[str] = mapped_column(String(35), nullable=False)
    receiver: Mapped[str] = mapped_column(String(35), nullable=False)
    control_ref: Mapped[str] = mapped_column(String(14), nullable=False)
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    message_types: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    results: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # per message: type, ref, outcome, object, errors
    raw: Mapped[str] = mapped_column(Text, nullable=False)
    contrl: Mapped[str] = mapped_column(Text, nullable=False)
    aperak: Mapped[Optional[str]] = mapped_column(Text)


class EarlyPaymentOffer(TenantScoped, Base):
    """Early-payment discount (dynamic discounting) or supply-chain-finance election on a posted invoice. No external
    provider: the SCF election raises the SCF_FINANCING connector message and the invoice event; the financier is the
    customer's own programme behind the ERP."""
    __tablename__ = "early_payment_offer"
    __table_args__ = (
        CheckConstraint("kind IN ('DISCOUNT','SCF')", name="kind"),
        CheckConstraint("status IN (" + ",".join(f"'{s}'" for s in OFFER_STATUSES) + ")", name="status"),
        CheckConstraint("source IN ('TERMS','BUYER','SUPPLIER')", name="source"),
        CheckConstraint("discount_pct >= 0 AND discount_pct < 100 AND discount_minor >= 0", name="discount"),
        Index("ix_early_payment_offer_invoice", "tenant_id", "invoice_id"),
        # One live offer per invoice: a second one is made after the first was declined, expired or cancelled.
        Index("uq_early_payment_offer_live", "tenant_id", "invoice_id", unique=True,
              postgresql_where=text("status IN ('OFFERED','ACCEPTED')")),
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.invoice.id"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="OFFERED")
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=0)
    discount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    pay_on: Mapped[Optional[date]] = mapped_column(Date)           # the date the invoice is paid when the offer is accepted
    original_due: Mapped[Optional[date]] = mapped_column(Date)
    expires_on: Mapped[date] = mapped_column(Date, nullable=False)
    annualised_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 2))
    offered_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    note: Mapped[Optional[str]] = mapped_column(Text)
    erp_doc_no: Mapped[Optional[str]] = mapped_column(String(40))


class ReceiptTolerance(TenantScoped, Base):
    """Over / under delivery tolerance override per material and/or supplier (BP M09). The most specific row wins:
    material + supplier, then supplier, then material; below that the contract or the RCV-TOLERANCE rule applies."""
    __tablename__ = "receipt_tolerance"
    __table_args__ = (
        CheckConstraint("material_id IS NOT NULL OR supplier_id IS NOT NULL", name="scope"),
        CheckConstraint("over_pct >= 0 AND over_pct <= 100 AND under_pct >= 0 AND under_pct <= 100", name="pct_range"),
        Index("uq_receipt_tolerance_scope", "tenant_id", text("COALESCE(material_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
              text("COALESCE(supplier_id, '00000000-0000-0000-0000-000000000000'::uuid)"), unique=True),
    )
    material_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"))
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"))
    over_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    under_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    set_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
