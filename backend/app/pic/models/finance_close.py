"""Posting periods per company code (M10 period close and cut-off, migration 0017)."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.pic.db import SCHEMA, Base, TenantScoped


class PostingPeriod(TenantScoped, Base):
    """A closed (or reopened) accounting period of a company code. A period without a row is open. Invoices are not posted, and payments
    not dated, into a CLOSED period; closing records the cut-off: invoices still in flight and the received-not-invoiced (GR/IR) accrual."""
    __tablename__ = "posting_period"
    __table_args__ = (UniqueConstraint("tenant_id", "company_code", "period"),
                      CheckConstraint("status IN ('OPEN','CLOSED')", name="status"))
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="CLOSED")
    closed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reopened_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    reopened_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reason: Mapped[Optional[str]] = mapped_column(Text)
    cutoff: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # in-flight invoices and GR/IR accrual at close


class GrirSnapshot(TenantScoped, Base):
    """The received-not-invoiced (GR/IR) accrual as it stood when a posting period was closed; one row per close (a reclose adds a new one)."""
    __tablename__ = "grir_snapshot"
    __table_args__ = (Index("ix_grir_snapshot_period", "tenant_id", "company_code", "period"),)
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    lines: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # [{po, line, qty, accrualMinor}]


class TdsCertificate(TenantScoped, Base):
    """Lower / nil deduction certificate under s.197 of the Income-tax Act: the rate the supplier's payments are taxed at while it is valid."""
    __tablename__ = "tds_certificate"
    __table_args__ = (UniqueConstraint("tenant_id", "supplier_id", "certificate_no"), Index("ix_tds_certificate_supplier", "tenant_id", "supplier_id"),
                      CheckConstraint("rate_pct >= 0 AND rate_pct <= 100 AND valid_to >= valid_from", name="valid"),
                      CheckConstraint("status IN ('ACTIVE','REVOKED')", name="status"))
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    certificate_no: Mapped[str] = mapped_column(String(40), nullable=False)
    section: Mapped[Optional[str]] = mapped_column(String(20))   # a key of rule set TDS; empty = every section of the supplier
    rate_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ACTIVE")
    note: Mapped[Optional[str]] = mapped_column(Text)
    revoked_reason: Mapped[Optional[str]] = mapped_column(Text)
    max_base_minor: Mapped[Optional[int]] = mapped_column(BigInteger)  # amount cap of the certificate (migration 0020); beyond it the normal rate applies


class BankStatementImport(TenantScoped, Base):
    """A bank statement (camt.053 or MT940) applied to payment results; the statement id makes the import idempotent."""
    __tablename__ = "bank_statement_import"
    __table_args__ = (UniqueConstraint("tenant_id", "statement_id"),)
    statement_id: Mapped[str] = mapped_column(String(60), nullable=False)
    format: Mapped[str] = mapped_column(String(10), nullable=False)
    account: Mapped[Optional[str]] = mapped_column(String(60))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    entries: Mapped[int] = mapped_column(Integer, nullable=False)
    credited: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    returned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class TdsChallan(TenantScoped, Base):
    """A tax deposit challan (ITNS 281) for TDS deducted in a quarter: BSR code of the bank branch, challan serial and deposit date identify it in the
    tax department's records; the deposits are reconciled against the TDS deducted per section (migration 0020)."""
    __tablename__ = "tds_challan"
    __table_args__ = (UniqueConstraint("tenant_id", "bsr_code", "deposit_date", "challan_no"),
                      Index("ix_tds_challan_quarter", "tenant_id", "company_code", "fiscal_year", "quarter"),
                      CheckConstraint("amount_minor > 0", name="amount"), CheckConstraint("status IN ('RECORDED','VOID')", name="status"))
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)
    fiscal_year: Mapped[str] = mapped_column(String(7), nullable=False)
    quarter: Mapped[str] = mapped_column(String(2), nullable=False)   # Q1..Q4 of the quarter the tax was deducted in
    section: Mapped[str] = mapped_column(String(20), nullable=False)  # key of rule set TDS
    challan_no: Mapped[str] = mapped_column(String(10), nullable=False)
    bsr_code: Mapped[str] = mapped_column(String(7), nullable=False)
    deposit_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="RECORDED")
    note: Mapped[Optional[str]] = mapped_column(Text)
    void_reason: Mapped[Optional[str]] = mapped_column(Text)


class MsmeInterest(TenantScoped, Base):
    """Interest owed to an MSME supplier for a payment made after its due date (MSMED Act s.16): one record per late payment, kept when the tenant
    publishes the bank rate (rule MSME.bankRatePct); the ERP payload of the payment carries it (migration 0020)."""
    __tablename__ = "msme_interest"
    __table_args__ = (UniqueConstraint("tenant_id", "payment_id"), Index("ix_msme_interest_supplier", "tenant_id", "supplier_id"),
                      CheckConstraint("status IN ('ACCRUED','WAIVED','SETTLED')", name="status"))
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.invoice.id"), nullable=False)
    payment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.payment.id"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    days_late: Mapped[int] = mapped_column(Integer, nullable=False)
    principal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rate_pct: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False)   # annual rate applied: interestMultiple x bank rate
    interest_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ACCRUED")
    note: Mapped[Optional[str]] = mapped_column(Text)
