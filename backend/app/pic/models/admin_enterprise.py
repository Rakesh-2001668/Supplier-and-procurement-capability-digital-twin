"""Enterprise administration tables (M13, migration 0015): purchasing organisations and groups, single-use user tokens
(activation and password reset), tenant-defined roles and the record of industry-template applications."""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.pic.db import Base, TenantScoped

__all__ = ["PurchasingOrg", "PurchasingGroup", "UserToken", "RoleDef", "TemplateApplication"]


class PurchasingOrg(TenantScoped, Base):
    """Purchasing organisation (blueprint M13 org model), assigned to one company code."""
    __tablename__ = "purchasing_org"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class PurchasingGroup(TenantScoped, Base):
    """Purchasing group (the buying team): optionally under a purchasing organisation and tied to a plant, with buyer users."""
    __tablename__ = "purchasing_group"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    purchasing_org: Mapped[Optional[str]] = mapped_column(String(10))
    plant: Mapped[Optional[str]] = mapped_column(String(10))
    buyer_user_ids: Mapped[list] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default="{}")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class UserToken(TenantScoped, Base):
    """Single-use, time-limited token for account activation or password reset. Only the SHA-256 of the token is stored."""
    __tablename__ = "user_token"
    __table_args__ = (
        CheckConstraint("purpose IN ('ACTIVATION','PASSWORD_RESET')", name="ck_user_token_purpose"),
        Index("ix_user_token_user", "tenant_id", "user_id", "purpose"),
        UniqueConstraint("token_hash", name="uq_user_token_hash"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class RoleDef(TenantScoped, Base):
    """Tenant-defined role: a named set of scopes taken from the assignable catalogue (platform/roles.py). Built-in roles stay in code."""
    __tablename__ = "role_def"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    scopes: Mapped[list] = mapped_column(ARRAY(String(40)), nullable=False, default=list)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class TemplateApplication(TenantScoped, Base):
    """Who applied which industry template when, and what it changed (rule sets added or re-versioned)."""
    __tablename__ = "template_application"
    template: Mapped[str] = mapped_column(String(40), nullable=False)
    previous_template: Mapped[Optional[str]] = mapped_column(String(40))
    applied_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    changes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
