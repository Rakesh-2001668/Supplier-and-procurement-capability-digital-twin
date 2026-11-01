"""Spend cube summaries (M01, AD-04), KPI history (BP Table 28) and per-user saved views.

The cube summaries are plain tenant tables maintained by ``spend.refresh_spend_views`` (full or per period): the read
side never scans ``spend_line``. Rows carry the tenant's forced row-level security like every other pic table.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.pic.db import SCHEMA, Base, TenantScoped


class SpendCubeSummary(TenantScoped, Base):
    """One row per (period, category, supplier, plant, company, cost object, material group, currency, source, flags).
    Amounts are in the group currency (``amount_group_minor``) and the document currency (``amount_minor``)."""
    __tablename__ = "spend_cube_summary"
    __table_args__ = (
        Index("uq_spend_cube_summary_grain", "tenant_id", "period", "category", "supplier_id", "plant", "company_code", "cost_object",
              "cost_object_type", "material_group", "currency", "source", "source_system", "contracted", "addressable", "maverick", unique=True),
        Index("ix_spend_cube_summary_supplier", "tenant_id", "supplier_id", "period"),
        Index("ix_spend_cube_summary_parent", "tenant_id", "parent_supplier_id", "period"),
        Index("ix_spend_cube_summary_category", "tenant_id", "category", "period"),
        Index("ix_spend_cube_summary_plant", "tenant_id", "plant", "period"),
        CheckConstraint("lines >= 0 AND invoices >= 0 AND pos >= 0 AND fx_missing_lines >= 0", name="counts"),
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    parent_supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)  # = supplier_id without a parent
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)
    cost_object: Mapped[str] = mapped_column(String(40), nullable=False, default="")  # '' = none
    cost_object_type: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    material_group: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    group_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    source_system: Mapped[str] = mapped_column(String(30), nullable=False)
    contracted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    addressable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    maverick: Mapped[bool] = mapped_column(Boolean, nullable=False)
    lines: Mapped[int] = mapped_column(BigInteger, nullable=False)
    invoices: Mapped[int] = mapped_column(BigInteger, nullable=False)  # distinct invoices within the row's grain
    pos: Mapped[int] = mapped_column(BigInteger, nullable=False)  # distinct purchase orders within the row's grain
    auto_classified_lines: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_group_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    price_variance_group_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    price_variance_last_group_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    fx_missing_lines: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)  # foreign lines without a rate (excluded from group amounts)


class SpendCommitmentSummary(TenantScoped, Base):
    """Open PO commitments (PO value not yet invoiced) and received-not-invoiced value by need-date month."""
    __tablename__ = "spend_commitment_summary"
    __table_args__ = (
        Index("uq_spend_commitment_summary_grain", "tenant_id", "period", "category", "supplier_id", "plant", "company_code", "cost_object",
              "cost_object_type", "currency", unique=True),
        Index("ix_spend_commitment_summary_supplier", "tenant_id", "supplier_id", "period"),
        CheckConstraint("committed_minor >= 0 AND received_not_invoiced_minor >= 0", name="not_negative"),
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    parent_supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)
    cost_object: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    cost_object_type: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    group_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    fx_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8))
    fx_date: Mapped[Optional[date]] = mapped_column(Date)
    pos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lines: Mapped[int] = mapped_column(BigInteger, nullable=False)
    committed_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)  # document currency
    committed_group_minor: Mapped[Optional[int]] = mapped_column(BigInteger)  # NULL without an FX rate
    received_not_invoiced_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class SpendViewState(TenantScoped, Base):
    """When each summary was last refreshed, how, and how long it took (freshness shown on every cube response)."""
    __tablename__ = "spend_view_state"
    __table_args__ = (
        UniqueConstraint("tenant_id", "view_name"),
        CheckConstraint("view_name IN ('spend_cube_summary','spend_commitment_summary')", name="view_name"),
        CheckConstraint("mode IN ('FULL','PERIODS')", name="mode"),
    )
    view_name: Mapped[str] = mapped_column(String(40), nullable=False)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    periods_refreshed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_rows: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    summary_rows: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SpendViewDirty(TenantScoped, Base):
    """Periods whose spend lines changed since the last refresh (written when a spend line is added, changed or removed)."""
    __tablename__ = "spend_view_dirty"
    __table_args__ = (UniqueConstraint("tenant_id", "period"),)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    marked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KpiSnapshot(TenantScoped, Base):
    """Month-end value of a KPI (BP Table 28); the registry in services/kpi.py defines the formula, this table the history."""
    __tablename__ = "kpi_snapshot"
    __table_args__ = (
        UniqueConstraint("tenant_id", "kpi_code", "period", "scope_key"),
        Index("ix_kpi_snapshot_code_period", "tenant_id", "kpi_code", "period"),
        CheckConstraint("status IN ('GOOD','WARN','BAD','NA')", name="status"),
    )
    kpi_code: Mapped[str] = mapped_column(String(40), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(60), nullable=False, default="")  # '' = whole tenant
    value: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    numerator: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    denominator: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    unit: Mapped[str] = mapped_column(String(15), nullable=False)
    status: Mapped[str] = mapped_column(String(5), nullable=False, default="NA")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class SavedView(TenantScoped, Base):
    """A user's saved filter set for a worklist or analysis screen (optionally shared with the tenant)."""
    __tablename__ = "saved_view"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "screen", "name"),
        Index("ix_saved_view_screen", "tenant_id", "screen"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="name_length"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.app_user.id", ondelete="CASCADE"), nullable=False)
    screen: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
