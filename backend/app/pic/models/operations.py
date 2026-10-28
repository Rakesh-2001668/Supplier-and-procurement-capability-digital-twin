"""Contract amendments (M07), sourcing clarifications and auction bids (M05), PO schedule lines and transmissions (M08),
bank payment files (M10), supplier master changes and invitations (M03/M06), punch-out sessions (M04),
notifications, ERP import batches and MFA factors (M13)."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.pic.db import SCHEMA, Base, TenantScoped
from app.pic.models.governance import QTY


# ---------------------------------------------------------------- M07 contract amendments and termination
class ContractAmendment(TenantScoped, Base):
    """A change to an active contract: VARIATION (lines/qty/price), EXTENSION (validity), TERMS, or TERMINATION.
    Approved amendments raise contract.version; the before/after snapshot keeps the history (P10)."""
    __tablename__ = "contract_amendment"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.contract.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(15), nullable=False)  # VARIATION | EXTENSION | TERMS | TERMINATION
    changes: Mapped[dict] = mapped_column(JSONB, default=dict)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="DRAFT")  # DRAFT | IN_APPROVAL | APPROVED | REJECTED | EFFECTIVE
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    from_version: Mapped[int] = mapped_column(Integer, nullable=False)
    to_version: Mapped[Optional[int]] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- M05 clarifications and reverse auction
class SourcingClarification(TenantScoped, Base):
    """Supplier question during an open event; the answer is published to every invitee without the asker's name."""
    __tablename__ = "sourcing_clarification"
    __table_args__ = (UniqueConstraint("tenant_id", "event_id", "seq"),)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.sourcing_event.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    asked_by_supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))  # None for buyer-initiated notices
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[Optional[str]] = mapped_column(Text)
    answered_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="OPEN")  # OPEN | ANSWERED | WITHDRAWN


class AuctionBid(TenantScoped, Base):
    """Live reverse-auction bid ledger (append-only). Rank is computed at submission; suppliers see only their own rank."""
    __tablename__ = "auction_bid"
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.sourcing_event.id"), nullable=False, index=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rank_at_submit: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    extended_close: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------- M08 schedule lines and transmissions
class PoScheduleLine(TenantScoped, Base):
    __tablename__ = "po_schedule_line"
    __table_args__ = (UniqueConstraint("tenant_id", "po_line_id", "seq"),)
    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.purchase_order.id"), nullable=False)
    po_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.po_line.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    delivery_date: Mapped[date] = mapped_column(Date, nullable=False)
    confirmed_date: Mapped[Optional[date]] = mapped_column(Date)
    received_qty: Mapped[Decimal] = mapped_column(QTY, default=0)


class PoTransmission(TenantScoped, Base):
    """Each sending of a PO version over a channel, with the exact document sent and the acknowledgement."""
    __tablename__ = "po_transmission"
    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.purchase_order.id"), nullable=False, index=True)
    po_version: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(String(10), nullable=False)  # PORTAL | EDI | EMAIL
    format: Mapped[str] = mapped_column(String(20), nullable=False)  # PORTAL | EDIFACT_ORDERS | EDIFACT_ORDCHG | PDF_EMAIL
    document: Mapped[str] = mapped_column(Text, nullable=False)
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient: Mapped[Optional[str]] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="QUEUED")  # QUEUED | SENT | ACKNOWLEDGED | FAILED
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ack_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error: Mapped[Optional[str]] = mapped_column(Text)


# ---------------------------------------------------------------- M10 bank payment files
class PaymentFile(TenantScoped, Base):
    __tablename__ = "payment_file"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    run_ref: Mapped[str] = mapped_column(String(30), nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False)  # ISO20022_PAIN001 | NEFT_CSV
    file_name: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payments: Mapped[int] = mapped_column(Integer, nullable=False)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="GENERATED")  # GENERATED | SENT | ACKNOWLEDGED | REJECTED
    bank_ref: Mapped[Optional[str]] = mapped_column(String(60))
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- M03 supplier master change, M06 invitations
class SupplierMasterChange(TenantScoped, Base):
    """MDM-04 for tax IDs, address and contacts: finance + compliance approval, never the requester. Values encrypted."""
    __tablename__ = "supplier_master_change"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    field_group: Mapped[str] = mapped_column(String(15), nullable=False)  # TAX | ADDRESS | CONTACT
    before_masked: Mapped[dict] = mapped_column(JSONB, default=dict)
    after_masked: Mapped[dict] = mapped_column(JSONB, default=dict)
    after_enc: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="IN_APPROVAL")  # IN_APPROVAL | APPLIED | REJECTED
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approvals: Mapped[list] = mapped_column(JSONB, default=list)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class SupplierInvitation(TenantScoped, Base):
    """Invitation link for supplier self-registration (F8-01). Only the token hash is stored."""
    __tablename__ = "supplier_invitation"
    __table_args__ = (UniqueConstraint("tenant_id", "token_hash"),)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    categories: Mapped[list] = mapped_column(ARRAY(String(40)), default=list)
    invited_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="SENT")  # SENT | REGISTERED | EXPIRED | REVOKED
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    registered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- M04 punch-out
class PunchoutSession(TenantScoped, Base):
    """cXML / OCI punch-out: setup request to the supplier catalogue, returned cart, conversion to requisition lines."""
    __tablename__ = "punchout_session"
    __table_args__ = (UniqueConstraint("tenant_id", "buyer_cookie"),)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.supplier.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    protocol: Mapped[str] = mapped_column(String(5), nullable=False)  # CXML | OCI
    buyer_cookie: Mapped[str] = mapped_column(String(64), nullable=False)
    start_url: Mapped[Optional[str]] = mapped_column(String(500))
    setup_request: Mapped[Optional[str]] = mapped_column(Text)
    cart: Mapped[list] = mapped_column(JSONB, default=list)
    cart_document: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="OPEN")  # OPEN | RETURNED | CONVERTED | EXPIRED
    requisition_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------- M13 notifications, ERP import batches, MFA
class Notification(TenantScoped, Base):
    __tablename__ = "notification"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[Optional[str]] = mapped_column(String(300))
    object_type: Mapped[Optional[str]] = mapped_column(String(40))
    object_ref: Mapped[Optional[str]] = mapped_column(String(60))
    dedup_key: Mapped[Optional[str]] = mapped_column(String(160))
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    email_status: Mapped[str] = mapped_column(String(15), nullable=False, default="NOT_SENT")  # NOT_SENT | SENT | FAILED | DISABLED
    emailed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class IntegrationBatch(TenantScoped, Base):
    """Inbound bulk loads from an ERP (planned orders, masters, stock) with per-row results."""
    __tablename__ = "integration_batch"
    __table_args__ = (UniqueConstraint("tenant_id", "source_system", "kind", "external_ref"),)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    source_system: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)  # PLANNED_ORDERS | ...
    external_ref: Mapped[str] = mapped_column(String(80), nullable=False)
    rows: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted: Mapped[int] = mapped_column(Integer, nullable=False)
    rejected: Mapped[int] = mapped_column(Integer, nullable=False)
    results: Mapped[list] = mapped_column(JSONB, default=list)


class MfaFactor(TenantScoped, Base):
    """TOTP (RFC 6238) factor per user; the shared secret is field-encrypted."""
    __tablename__ = "mfa_factor"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "kind"),)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.app_user.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="TOTP")
    secret_enc: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_used_step: Mapped[Optional[int]] = mapped_column(BigInteger)  # replay protection
