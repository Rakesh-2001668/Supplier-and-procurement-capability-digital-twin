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
