"""Inventory documents (BP M09 / M02 stock, Technical Document section 6): stock postings (transfer, block, unblock, scrap), physical
inventory (count) documents and stock reservations. The ledger itself (``stock``, ``stock_movement``) is in models/master.py.
Every table is tenant-scoped with forced row-level security (migration 0018)."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.pic.db import SCHEMA, Base, TenantScoped

QTY = Numeric(18, 3)

POSTING_TYPES = ("TRANSFER", "BLOCK", "UNBLOCK", "RELEASE_QUALITY", "SCRAP")
POSTING_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "POSTED", "REJECTED", "CANCELLED")
COUNT_STATUSES = ("PLANNED", "COUNTING", "COUNTED", "PENDING_APPROVAL", "APPROVED", "POSTED", "CANCELLED")
RESERVATION_STATUSES = ("OPEN", "PARTIALLY_ISSUED", "ISSUED", "CANCELLED", "EXPIRED")


def _in(column: str, values: tuple) -> str:
    return f"{column} IN ({','.join(repr(v) for v in values)})"


class StockPosting(TenantScoped, Base):
    """A governed stock posting: TRANSFER (311 within a plant, 301 between plants), BLOCK (344), UNBLOCK (343) or SCRAP (551). It posts only
    when it is approved (or auto-posted under the rule's value limit), re-checking the stock and the posting period at that moment."""
    __tablename__ = "stock_posting"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),
                      CheckConstraint(_in("posting_type", POSTING_TYPES), name="type"),
                      CheckConstraint(_in("status", POSTING_STATUSES), name="status"),
                      Index("ix_stock_posting_status", "tenant_id", "status", "plant"))
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    posting_type: Mapped[str] = mapped_column(String(15), nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="DRAFT")
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)          # the plant the stock leaves (all lines)
    posting_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason_code: Mapped[Optional[str]] = mapped_column(String(30))
    reason: Mapped[Optional[str]] = mapped_column(Text)
    total_value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    auto_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rule_set_version: Mapped[Optional[str]] = mapped_column(String(80))
    submitted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    posted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decision_comment: Mapped[Optional[str]] = mapped_column(Text)
    erp_doc_no: Mapped[Optional[str]] = mapped_column(String(40))


class StockPostingLine(TenantScoped, Base):
    __tablename__ = "stock_posting_line"
    __table_args__ = (UniqueConstraint("tenant_id", "posting_id", "line_no"), CheckConstraint("qty > 0", name="qty_positive"),
                      Index("ix_stock_posting_line_posting", "tenant_id", "posting_id"))
    posting_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.stock_posting.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"), nullable=False)
    batch: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    from_plant: Mapped[str] = mapped_column(String(10), nullable=False)
    from_storage_location: Mapped[str] = mapped_column(String(10), nullable=False)
    from_stock_type: Mapped[str] = mapped_column(String(15), nullable=False)
    to_plant: Mapped[Optional[str]] = mapped_column(String(10))
    to_storage_location: Mapped[Optional[str]] = mapped_column(String(10))
    to_stock_type: Mapped[Optional[str]] = mapped_column(String(15))
    movement_type: Mapped[str] = mapped_column(String(5), nullable=False)
    unit_price_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class PhysicalInventory(TenantScoped, Base):
    """A physical-inventory (cycle count) document for one plant and storage location. The book quantities are frozen when it is created
    (``frozen_at``); counting is blind for the counters; the difference posted is relative to the freeze (701 gain / 702 loss)."""
    __tablename__ = "physical_inventory"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),
                      CheckConstraint(_in("status", COUNT_STATUSES), name="status"),
                      Index("ix_physical_inventory_status", "tenant_id", "status", "plant"))
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PLANNED")
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    storage_location: Mapped[str] = mapped_column(String(10), nullable=False)
    material_group: Mapped[Optional[str]] = mapped_column(String(30))
    scope: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)   # {"materials": [...], "abc": [...]} the selection used
    description: Mapped[Optional[str]] = mapped_column(Text)
    planned_date: Mapped[Optional[date]] = mapped_column(Date)
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gain_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    loss_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    accuracy_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2))
    rule_set_version: Mapped[Optional[str]] = mapped_column(String(80))
    submitted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    posted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decision_comment: Mapped[Optional[str]] = mapped_column(Text)
    erp_doc_no: Mapped[Optional[str]] = mapped_column(String(40))

    @property
    def total_value_minor(self) -> int:
        """Gross value of the differences (gains plus losses): what the approval band and the approver's value limit are measured on."""
        return int(self.gain_minor or 0) + int(self.loss_minor or 0)


class PhysicalInventoryLine(TenantScoped, Base):
    __tablename__ = "physical_inventory_line"
    __table_args__ = (UniqueConstraint("tenant_id", "inventory_id", "line_no"),
                      CheckConstraint("count_status IN ('PENDING','COUNTED','RECOUNT_REQUIRED','RECOUNTED')", name="count_status"),
                      Index("ix_physical_inventory_line_inventory", "tenant_id", "inventory_id"))
    inventory_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.physical_inventory.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"), nullable=False)
    batch: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    stock_type: Mapped[str] = mapped_column(String(15), nullable=False, default="UNRESTRICTED")
    book_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False, default=0)           # book quantity at the freeze
    unit_price_minor: Mapped[Optional[int]] = mapped_column(BigInteger)                    # standard price at the freeze
    unlisted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)        # found at the count, not on the freeze list
    count_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    counted_qty: Mapped[Optional[Decimal]] = mapped_column(QTY)                           # first count
    counted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    counted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    first_count_ok: Mapped[Optional[bool]] = mapped_column(Boolean)                        # first count inside the tolerance (count accuracy KPI)
    recount_qty: Mapped[Optional[Decimal]] = mapped_column(QTY)
    recounted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    recounted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    recount_reason: Mapped[Optional[str]] = mapped_column(Text)
    final_qty: Mapped[Optional[Decimal]] = mapped_column(QTY)                              # the accepted count (recount if there was one)
    diff_qty: Mapped[Optional[Decimal]] = mapped_column(QTY)                               # final_qty - book_qty
    diff_value_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    posted_qty: Mapped[Optional[Decimal]] = mapped_column(QTY)                             # the delta posted (equal to diff_qty, kept for the audit)
    drift_qty: Mapped[Optional[Decimal]] = mapped_column(QTY)                              # movement between freeze and posting
    note: Mapped[Optional[str]] = mapped_column(Text)


class StockReservation(TenantScoped, Base):
    """A reservation of unrestricted stock for a cost object or purpose. Its open quantity is RESERVATION demand for MRP
    (``demand_element``); an issue posts movement 201 and reduces both."""
    __tablename__ = "stock_reservation"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),
                      CheckConstraint(_in("status", RESERVATION_STATUSES), name="status"),
                      CheckConstraint("qty > 0 AND issued_qty >= 0 AND issued_qty <= qty", name="qty_range"),
                      Index("ix_stock_reservation_material", "tenant_id", "material_id", "plant", "status"),
                      Index("ix_stock_reservation_status", "tenant_id", "status", "need_date"))
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    storage_location: Mapped[str] = mapped_column(String(10), nullable=False)
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    issued_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False, default=0)
    need_date: Mapped[date] = mapped_column(Date, nullable=False)
    cost_object_type: Mapped[Optional[str]] = mapped_column(String(20))
    cost_object_code: Mapped[Optional[str]] = mapped_column(String(30))
    purpose: Mapped[Optional[str]] = mapped_column(String(200))
    requester_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    availability: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)      # availability check at creation
    demand_element_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    rule_set_version: Mapped[Optional[str]] = mapped_column(String(80))
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    closed_reason: Mapped[Optional[str]] = mapped_column(Text)


class StockBatch(TenantScoped, Base):
    """Batch master of a material: the expiry (and manufacturing) date of a lot that did not come in through a goods receipt, i.e. an opening
    balance (``tools/stock_opening_load.py``) or an ERP batch master (SAP MCH1-VFDAT). Goods receipts keep carrying their own expiry
    (``gr_line.expiry``); ``stock_ledger.batch_expiry`` takes the earliest of both. One row per tenant, material and batch (migration 0019)."""
    __tablename__ = "stock_batch"
    __table_args__ = (UniqueConstraint("tenant_id", "material_id", "batch"),
                      CheckConstraint("expiry_date IS NULL OR manufactured_date IS NULL OR expiry_date >= manufactured_date", name="expiry_after_manufacture"))
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"), nullable=False)
    batch: Mapped[str] = mapped_column(String(30), nullable=False)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)
    manufactured_date: Mapped[Optional[date]] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="OPENING_BALANCE")     # OPENING_BALANCE | ERP_BATCH_MASTER | MANUAL
    note: Mapped[Optional[str]] = mapped_column(Text)
