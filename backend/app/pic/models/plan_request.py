"""M02 planning (F1) and M04 requisitioning (F2)."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.pic.db import SCHEMA, Base, TenantScoped

QTY = Numeric(18, 3)


class DemandElement(TenantScoped, Base):
    __tablename__ = "demand_element"
    __table_args__ = (
        Index("ix_demand_element_material_plant", "tenant_id", "material_id", "plant", "req_date"),
        Index("ix_demand_element_plant_changed", "tenant_id", "plant", "changed_at"),  # net-change scope
    )
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # FORECAST | SALES_ORDER | RESERVATION | WBS_DEMAND
    reference: Mapped[str] = mapped_column(String(60), nullable=False)
    req_date: Mapped[date] = mapped_column(Date, nullable=False)
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class MrpRun(TenantScoped, Base):
    __tablename__ = "mrp_run"
    __table_args__ = (UniqueConstraint("tenant_id", "number"), Index("ix_mrp_run_plant_created", "tenant_id", "plant", "created_at"))
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    mode: Mapped[str] = mapped_column(String(15), nullable=False)  # NET_CHANGE | REGENERATIVE | SIMULATION
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    scope: Mapped[dict] = mapped_column(JSONB, default=dict)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RUNNING")
    materials_planned: Mapped[int] = mapped_column(Integer, default=0)
    planned_orders_created: Mapped[int] = mapped_column(Integer, default=0)
    exceptions_raised: Mapped[int] = mapped_column(Integer, default=0)
    results: Mapped[list] = mapped_column(JSONB, default=list)  # per-material netting trace (also used by simulation)
    started_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class PlannedOrder(TenantScoped, Base):
    __tablename__ = "planned_order"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number"),
        Index("ix_planned_order_plant_status_material", "tenant_id", "plant", "status", "material_id"),
        Index("ix_planned_order_run", "tenant_id", "mrp_run_id"),
        Index("ix_planned_order_requisition", "tenant_id", "requisition_id"),
    )
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    mrp_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.mrp_run.id"), nullable=False)
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    storage_location: Mapped[str] = mapped_column(String(10), nullable=False)
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    need_date: Mapped[date] = mapped_column(Date, nullable=False)
    release_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="CREATED")  # CREATED | FIRMED | CONVERTED | DELETED
    source: Mapped[dict] = mapped_column(JSONB, default=dict)
    exception_codes: Mapped[list] = mapped_column(JSONB, default=list)
    requisition_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    source_system: Mapped[str] = mapped_column(String(20), default="PLATFORM", server_default="PLATFORM")  # PLATFORM | SAP_S4 | ...
    external_ref: Mapped[Optional[str]] = mapped_column(String(60))


class MrpException(TenantScoped, Base):
    __tablename__ = "mrp_exception"
    __table_args__ = (Index("ix_mrp_exception_run", "tenant_id", "mrp_run_id"),)
    mrp_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.mrp_run.id"), nullable=False)
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"), nullable=False)
    planned_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    code: Mapped[str] = mapped_column(String(20), nullable=False)  # PAST_DUE | BELOW_SAFETY | RESCHEDULE_IN | RESCHEDULE_OUT | CANCEL
    message: Mapped[str] = mapped_column(Text, nullable=False)
    value_at_risk_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(15), default="OPEN")


class Requisition(TenantScoped, Base):
    __tablename__ = "requisition"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number"),
        CheckConstraint("origin IN ('MRP','MANUAL','PROJECT','CATALOGUE')", name="origin"),
    )
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    origin: Mapped[str] = mapped_column(String(10), nullable=False)  # P02: stored, never overwritten (DB trigger)
    origin_ref: Mapped[Optional[str]] = mapped_column(String(60))
    purpose_code: Mapped[Optional[str]] = mapped_column(String(30))  # P01: mandatory at submit
    purpose_text: Mapped[Optional[str]] = mapped_column(Text)
    requester_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    total_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    budget_result: Mapped[dict] = mapped_column(JSONB, default=dict)
    policy_hints: Mapped[list] = mapped_column(JSONB, default=list)
    approval_chain: Mapped[list] = mapped_column(JSONB, default=list)
    approved_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB)
    rule_set_version: Mapped[Optional[str]] = mapped_column(String(80))
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class PrLine(TenantScoped, Base):
    __tablename__ = "pr_line"
    __table_args__ = (
        UniqueConstraint("tenant_id", "requisition_id", "line_no"),
        # P04: free-text lines never point at a material master record.
        CheckConstraint("item_type <> 'FREE_TEXT' OR material_id IS NULL", name="free_text_no_material"),
        CheckConstraint(
            "purchase_type IN ('STOCK','NON_STOCK','SERVICE','EXPENSE','ASSET','CONSIGNMENT','SUBCONTRACTING')",
            name="purchase_type",
        ),
    )
    requisition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.requisition.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    item_type: Mapped[str] = mapped_column(String(15), nullable=False)  # MATERIAL | FREE_TEXT | CATALOGUE | SERVICE | CONTRACT
    purchase_type: Mapped[str] = mapped_column(String(15), nullable=False)
    material_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.material.id"))
    catalogue_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    contract_line_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    material_group: Mapped[str] = mapped_column(String(30), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(40))
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    uom: Mapped[str] = mapped_column(String(5), nullable=False)
    price_est_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    account_assignment_type: Mapped[Optional[str]] = mapped_column(String(20))  # COST_CENTER | WBS | ORDER | ASSET
    account_assignment_code: Mapped[Optional[str]] = mapped_column(String(30))
    need_date: Mapped[date] = mapped_column(Date, nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    storage_location: Mapped[Optional[str]] = mapped_column(String(10))
    preferred_supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    quotes_attached: Mapped[int] = mapped_column(Integer, default=0)
    reusable: Mapped[bool] = mapped_column(default=False)
    mdm_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    linked_material_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))  # set after F9 approval; line stays free text
    ordered_qty: Mapped[Decimal] = mapped_column(QTY, default=0)
    sourcing_status: Mapped[str] = mapped_column(String(20), default="OPEN")  # OPEN | IN_SOURCING | SOURCED | ORDERED
    source_determination: Mapped[dict] = mapped_column(JSONB, default=dict)
    planned_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
