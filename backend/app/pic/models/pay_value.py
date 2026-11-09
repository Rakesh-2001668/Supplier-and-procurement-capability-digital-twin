"""M10 invoices and payments (F7), M11 savings ledger and M01 spend lines."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
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
        CheckConstraint("payment_option IN ('STANDARD','EARLY_DISCOUNT','SCF')", name="payment_option"),
        CheckConstraint("paid_minor >= 0", name="paid_minor"),
        # Copilot / search by the supplier's own invoice number across suppliers and company codes (flow fixes C6).
        Index("ix_invoice_tenant_supplier_invoice_no", "tenant_id", "supplier_invoice_no"),
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
    # TDS / withholding tax deducted from the payment to the supplier (migrated open items; see services/withholding.py)
    withholding_tax_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    erp_doc_no: Mapped[Optional[str]] = mapped_column(String(40))
    posting_key: Mapped[Optional[str]] = mapped_column(String(200))
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    payment_status: Mapped[str] = mapped_column(String(15), default="UNPAID")
    rule_set_version: Mapped[Optional[str]] = mapped_column(String(80))
    duplicate_of: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    # M10 early-payment / supply-chain finance: STANDARD | EARLY_DISCOUNT | SCF; the accepted discount reduces the payment.
    payment_option: Mapped[str] = mapped_column(String(15), nullable=False, default="STANDARD", server_default="STANDARD")
    discount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    # Finance completion (migration 0017). MSMED Act s.15: the day goods / services were accepted starts the 45-day clock; ``msme_capped``
    # says the due date was pulled forward to it. TDS: section key, rate and the base (net of credit notes) it applies to.
    acceptance_date: Mapped[Optional[date]] = mapped_column(Date)
    msme_capped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    tds_section: Mapped[Optional[str]] = mapped_column(String(20))
    tds_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 3))
    tds_base_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    # Foreign-currency invoices: rate to the company-code currency on the invoice date, and the gross in that currency.
    fx_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8))
    fx_date: Mapped[Optional[date]] = mapped_column(Date)
    gross_group_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    posting_date: Mapped[Optional[date]] = mapped_column(Date)  # the accounting date the ERP document was posted on (open posting period)
    # Finance second pass (migration 0020). GST: place of supply (state code) and the tax heads of the invoice (CGST + SGST inside the state, IGST between
    # states); reverse charge: the supplier charges no GST, the buyer self-assesses ``rcm_tax_minor``. TCS (s.206C(1H) style, rule TDS.tcs, off by default).
    place_of_supply: Mapped[Optional[str]] = mapped_column(String(2))
    cgst_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    sgst_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    igst_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    reverse_charge: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    rcm_tax_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    tcs_section: Mapped[Optional[str]] = mapped_column(String(20))
    tcs_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 3))
    tcs_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    # Migration 0028. Partial payments: cash paid to the supplier by the live (not cancelled) payments of the invoice; payment_status is
    # PARTIALLY_PAID while it is below the amount payable. Section 195: the nature of the payment to a non-resident (ROYALTY | FTS | INTEREST |
    # OTHER, rule TDS-195) and the s.195A gross-up of this invoice (NULL: the contract's, else the supplier's setting).
    paid_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    tax_nature: Mapped[Optional[str]] = mapped_column(String(20))
    tax_gross_up: Mapped[Optional[bool]] = mapped_column(Boolean)


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
    tax_split: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")  # tax heads the supplier charged: cgst / sgst / igst (minor)


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
    # A debit note posted after its invoice was paid is paid on its own (payment_run); null for the invoice payment itself.
    debit_note_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    # Bank confirmation (migration 0017): NOT_SENT -> SENT (file sent) -> CREDITED (bank UTR) | RETURNED (bank returned the credit).
    bank_status: Mapped[str] = mapped_column(String(10), nullable=False, default="NOT_SENT", server_default="NOT_SENT")
    bank_utr: Mapped[Optional[str]] = mapped_column(String(40))
    bank_confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    return_reason: Mapped[Optional[str]] = mapped_column(Text)
    tds_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")  # withheld from this payment (Form 26Q)
    tds_base_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")  # the amount the TDS was deducted on
    tds_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 3))        # rate applied at payment (certificate rate when s.197 applied)
    tds_certificate: Mapped[Optional[str]] = mapped_column(String(40))         # s.197 certificate number used, if any
    reversal_doc: Mapped[Optional[str]] = mapped_column(String(40))            # ERP reversal document of a returned payment
    # Migration 0020: base taxed at the s.197 certificate rate (counts against the certificate's cap), TCS paid to the supplier, and the realised
    # exchange difference of a foreign-currency payment (rate on the payment date against the invoice rate; positive = gain).
    tds_cert_base_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    tcs_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    fx_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8))
    amount_group_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    fx_gain_loss_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    # Migration 0028. Partial payments: the sequence number of the payment on its invoice (returned payments keep theirs), whether it settles the
    # invoice (the last or only payment), the reason given for a partial amount and the gross of the debit notes netted into it.
    installment_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    settles_invoice: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    partial_reason: Mapped[Optional[str]] = mapped_column(Text)
    debit_memo_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    # Section 195 (non-resident): the tax in INR (what the 27Q return and the challan carry) and the INR base, the tax the company bears under a
    # s.195A gross-up (not deducted from the remittance) and the determination (basis DTAA / ACT / NO_PAN_206AA, rates, surcharge, cess, FX, 15CA).
    tds_inr_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    tds_base_inr_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    tax_borne_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    tax_detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    __table_args__ = (
        CheckConstraint("bank_status IN ('NOT_SENT','SENT','CREDITED','RETURNED')", name="bank_status"),
        # One live settling payment per invoice: blocks double payment at the database level. Partial payments (settles_invoice false) are
        # numbered per invoice instead; the payment run holds the invoice row lock while it adds one, and never pays more than is open.
        Index("uq_payment_invoice_live", "tenant_id", "invoice_id", unique=True,
              postgresql_where=text("status <> 'CANCELLED' AND debit_note_id IS NULL AND settles_invoice")),
        Index("uq_payment_invoice_installment", "tenant_id", "invoice_id", "installment_no", unique=True,
              postgresql_where=text("debit_note_id IS NULL")),
        Index("uq_payment_debit_note_live", "tenant_id", "debit_note_id", unique=True,
              postgresql_where=text("status <> 'CANCELLED' AND debit_note_id IS NOT NULL")),
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
    __table_args__ = (
        # One row per source line and document: the invoice line itself ('INVOICE', ref ''), each credit note line that reduces it
        # ('CREDIT_NOTE', note number, negative amount) and each debit note line that adds to it ('DEBIT_NOTE', note number).
        UniqueConstraint("tenant_id", "invoice_line_id", "document_type", "document_ref", name="uq_spend_line_invoice_line_document"),
        CheckConstraint("document_type IN ('INVOICE','CREDIT_NOTE','DEBIT_NOTE')", name="document_type"),
        # a line this large is a unit error; summed into the BIGINT cube it would stop the refresh for everyone (Rs 10 billion crore)
        CheckConstraint("abs(amount_minor) <= 1000000000000000", name="amount_range"),
        # Cube refresh and drill-down paths (a period is the unit of incremental refresh).
        Index("ix_spend_line_tenant_period", "tenant_id", "period"),
        Index("ix_spend_line_invoice_ref", "tenant_id", "invoice_ref"),
        Index("ix_spend_line_tenant_supplier_period", "tenant_id", "supplier_id", "period"),
        Index("ix_spend_line_tenant_category_period", "tenant_id", "category", "period"),
        # SPD-05 off-contract worklist: the largest off-contract lines without scanning the table.
        Index("ix_spend_line_offcontract", "tenant_id", text("amount_minor DESC"),
              postgresql_where=text("maverick_flags ?| array['OFF_CONTRACT','OFF_CONTRACT_PRICE']")),
    )
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
    # Spend cube (M01, wave 1): ERP tagging for multi-ERP tenants, cost-object type (COST_CENTER | WBS | ...), the FX rate and its
    # date used to convert the document-currency amount to the group currency, and the variance against the last price paid.
    source_system: Mapped[str] = mapped_column(String(30), nullable=False, default="PIC", server_default="PIC")
    cost_object_type: Mapped[Optional[str]] = mapped_column(String(20))
    fx_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8))  # NULL: foreign-currency line without a rate on its date
    fx_date: Mapped[Optional[date]] = mapped_column(Date)
    amount_group_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    price_variance_last_minor: Mapped[Optional[int]] = mapped_column(BigInteger)  # above the last price paid for the material
    # Spend cube second pass (migration 0021): which document the line is (credit / debit notes are own signed lines in the period of
    # the note), the date of that document (the FX rate and the fiscal period follow it) and the buyer of the order.
    document_type: Mapped[str] = mapped_column(String(12), nullable=False, default="INVOICE", server_default="INVOICE")
    document_ref: Mapped[str] = mapped_column(String(60), nullable=False, default="", server_default="")
    document_date: Mapped[Optional[date]] = mapped_column(Date)
    buyer_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
