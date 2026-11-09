"""Section 195 withholding on payments to non-residents (migration 0028): the supplier's tax residency with its treaty documents, and the
Form 15CA / 15CB filings recorded against an invoice before a remittance is released.

Identifiers that are personal or tax-sensitive (PAN, foreign tax identification number, Tax Residency Certificate number, Form 10F and Form 15CA
acknowledgement numbers) are stored encrypted with the tenant's field key (platform/crypto.py, purposes ``tax-pan``, ``tax-id``, ``tax-trc``,
``tax-10f`` and ``tax-15ca``) next to a masked copy for display, exactly as the supplier's GSTIN and bank account are.
"""
import uuid
from datetime import date
from typing import Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, ForeignKey, Index, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.pic.db import SCHEMA, Base, TenantScoped


class SupplierTaxResidency(TenantScoped, Base):
    __tablename__ = "supplier_tax_residency"
    __table_args__ = (
        UniqueConstraint("tenant_id", "supplier_id"),
        CheckConstraint("residency IN ('RESIDENT','NON_RESIDENT')", name="residency"),
        CheckConstraint("payee_type IN ('COMPANY','NON_COMPANY')", name="payee_type"),
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    residency: Mapped[str] = mapped_column(String(15), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)              # country of tax residence (ISO 3166 alpha-2)
    payee_type: Mapped[str] = mapped_column(String(12), nullable=False, default="COMPANY", server_default="COMPANY")
    pan_enc: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    pan_masked: Mapped[Optional[str]] = mapped_column(String(12))
    tax_id_enc: Mapped[Optional[bytes]] = mapped_column(LargeBinary)              # tax identification number in the country of residence
    tax_id_masked: Mapped[Optional[str]] = mapped_column(String(40))
    trc_no_enc: Mapped[Optional[bytes]] = mapped_column(LargeBinary)              # Tax Residency Certificate
    trc_masked: Mapped[Optional[str]] = mapped_column(String(40))
    trc_valid_from: Mapped[Optional[date]] = mapped_column(Date)
    trc_valid_to: Mapped[Optional[date]] = mapped_column(Date)
    trc_document_ref: Mapped[Optional[str]] = mapped_column(String(200))           # document store reference (file name / hash) of the scanned TRC
    form10f_ack_enc: Mapped[Optional[bytes]] = mapped_column(LargeBinary)          # Form 10F acknowledgement (filed on the income-tax portal)
    form10f_masked: Mapped[Optional[str]] = mapped_column(String(40))
    form10f_filed_on: Mapped[Optional[date]] = mapped_column(Date)
    form10f_valid_from: Mapped[Optional[date]] = mapped_column(Date)
    form10f_valid_to: Mapped[Optional[date]] = mapped_column(Date)
    no_pe_declared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    no_pe_valid_from: Mapped[Optional[date]] = mapped_column(Date)
    no_pe_valid_to: Mapped[Optional[date]] = mapped_column(Date)
    gross_up: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")   # s.195A: the company bears the tax
    default_nature: Mapped[Optional[str]] = mapped_column(String(20))             # ROYALTY | FTS | INTEREST | OTHER (rule TDS-195 natures)
    note: Mapped[Optional[str]] = mapped_column(Text)


class RemittanceCertificate(TenantScoped, Base):
    """A Form 15CA filing (with the Form 15CB chartered-accountant certificate where the rule threshold applies) recorded for one remittance of an
    invoice; the payment run uses it for one payment (``payment_id``) and refuses to release a non-resident payment without one."""
    __tablename__ = "remittance_certificate"
    __table_args__ = (
        UniqueConstraint("tenant_id", "form15ca_ack_hash"),
        CheckConstraint("status IN ('RECORDED','USED','VOID')", name="status"),
        CheckConstraint("form15ca_part IN ('A','B','C','D')", name="form15ca_part"),
        CheckConstraint("amount_minor > 0", name="amount"),
        Index("ix_remittance_certificate_invoice", "tenant_id", "invoice_id"),
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.invoice.id"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    payment_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.payment.id"))
    form15ca_part: Mapped[str] = mapped_column(String(1), nullable=False)
    form15ca_ack_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    form15ca_ack_masked: Mapped[str] = mapped_column(String(40), nullable=False)
    form15ca_ack_hash: Mapped[str] = mapped_column(String(64), nullable=False)    # blind index: one acknowledgement is recorded once
    form15ca_filed_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)          # remittance covered, invoice currency
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    form15cb_certificate_no: Mapped[Optional[str]] = mapped_column(String(40))     # CA certificate (UDIN)
    form15cb_date: Mapped[Optional[date]] = mapped_column(Date)
    ca_name: Mapped[Optional[str]] = mapped_column(String(200))
    ca_membership_no: Mapped[Optional[str]] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="RECORDED", server_default="RECORDED")
    void_reason: Mapped[Optional[str]] = mapped_column(Text)
    note: Mapped[Optional[str]] = mapped_column(Text)
