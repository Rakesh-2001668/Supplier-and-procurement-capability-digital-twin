"""Enterprise platform tables (wave 1): SoD mitigation grants and tenant ERP field mappings."""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.pic.db import Base, TenantScoped

__all__ = ["SodMitigation", "IntegrationFieldMapping"]


class SodMitigation(TenantScoped, Base):
    """Exception path for a segregation-of-duties conflict (rule SOD-MITIGATION): the actor asks, a configured approver
    decides, and an approved request is a time-boxed (and use-limited) grant that lets the blocked command proceed."""
    __tablename__ = "sod_mitigation"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING','APPROVED','REJECTED','REVOKED')", name="ck_sod_mitigation_status"),
        CheckConstraint("requested_validity_hours > 0", name="ck_sod_mitigation_validity_positive"),
        CheckConstraint("valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from", name="ck_sod_mitigation_window"),
        Index("ix_sod_mitigation_lookup", "tenant_id", "requester_id", "action", "status"),
    )
    rule_code: Mapped[str] = mapped_column(String(10), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    requester_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    refs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    scope_value: Mapped[str] = mapped_column(String(80), nullable=False)  # the value of refs[rule.scope] the grant covers
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="PENDING")
    requested_validity_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    compensating_control: Mapped[str] = mapped_column(Text, nullable=False)
    approver_roles: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decision_comment: Mapped[Optional[str]] = mapped_column(Text)
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class IntegrationFieldMapping(TenantScoped, Base):
    """Versioned outbound field-mapping rules for one target system and message type (item 50). At most one ACTIVE version;
    without one the payload is sent as the services built it."""
    __tablename__ = "integration_field_mapping"
    __table_args__ = (
        UniqueConstraint("tenant_id", "target_system", "message_type", "version", name="uq_integration_field_mapping_version"),
        CheckConstraint("status IN ('DRAFT','ACTIVE','RETIRED')", name="ck_integration_field_mapping_status"),
        CheckConstraint("version > 0", name="ck_integration_field_mapping_version"),
        Index("uq_integration_field_mapping_active", "tenant_id", "target_system", "message_type", unique=True,
              postgresql_where=text("status = 'ACTIVE'")),
    )
    target_system: Mapped[str] = mapped_column(String(30), nullable=False)
    message_type: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="DRAFT")
    rules: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    note: Mapped[Optional[str]] = mapped_column(Text)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
