"""Wave 1 (engineer A): scheduled jobs and their run history, delegation of authority, audit archive batches and the generic
tenant flag (AI switch). All tables are tenant tables with forced row-level security (migration 0008)."""
import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.pic.db import SCHEMA, Base, TenantScoped, utcnow


class ScheduledJob(TenantScoped, Base):
    """One row per (tenant, code-registered job): its schedule, switch and the outcome of the last run (services/jobs.py)."""
    __tablename__ = "scheduled_job"
    __table_args__ = (
        UniqueConstraint("tenant_id", "job_key"),
        CheckConstraint("last_status IS NULL OR last_status IN ('SUCCESS','FAILED','PARTIAL','SKIPPED','RUNNING')", name="last_status"),
        CheckConstraint("consecutive_failures >= 0 AND run_count >= 0", name="counters_not_negative"),
        Index("ix_scheduled_job_due", "tenant_id", "enabled", "next_run_at"),
    )
    job_key: Mapped[str] = mapped_column(String(60), nullable=False)
    schedule: Mapped[str] = mapped_column(String(80), nullable=False)  # cron "m h dom mon dow" in the tenant's time zone, or @daily ...
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[Optional[str]] = mapped_column(String(10))
    last_duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    running_since: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))  # claim of the run in progress (stale after the job's timeout)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    changed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))


class JobRun(TenantScoped, Base):
    __tablename__ = "job_run"
    __table_args__ = (
        CheckConstraint("status IN ('RUNNING','SUCCESS','FAILED','PARTIAL','SKIPPED')", name="status"),
        CheckConstraint("trigger IN ('SCHEDULE','MANUAL')", name="trigger"),
        Index("ix_job_run_history", "tenant_id", "job_key", "started_at"),
    )
    job_key: Mapped[str] = mapped_column(String(60), nullable=False)
    scheduled_job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.scheduled_job.id"), nullable=False)
    trigger: Mapped[str] = mapped_column(String(10), nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[Optional[str]] = mapped_column(Text)
    triggered_by: Mapped[Optional[str]] = mapped_column(String(80))  # actor of a manual run


class Delegation(TenantScoped, Base):
    """Out-of-office delegation of authority (workflow.can_work): the delegate may work the delegator's approval tasks between
    valid_from and valid_to (inclusive, IST), optionally only for some roles and up to a value."""
    __tablename__ = "delegation"
    __table_args__ = (
        CheckConstraint("delegator_id <> delegate_id", name="not_self"),
        CheckConstraint("valid_to >= valid_from", name="dates_ordered"),
        CheckConstraint("value_limit_minor IS NULL OR value_limit_minor > 0", name="limit_positive"),
        CheckConstraint("status IN ('ACTIVE','REVOKED')", name="status"),
        Index("ix_delegation_delegate", "tenant_id", "delegate_id", "status"),
        Index("ix_delegation_delegator", "tenant_id", "delegator_id", "status"),
    )
    delegator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.app_user.id"), nullable=False)
    delegate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.app_user.id"), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)
    roles: Mapped[list] = mapped_column(ARRAY(String(40)), nullable=False, default=list)  # empty = every role of the delegator
    value_limit_minor: Mapped[Optional[int]] = mapped_column(BigInteger)  # tasks above this value (or of unknown value) are excluded
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ACTIVE")
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    revoke_reason: Mapped[Optional[str]] = mapped_column(Text)


class AuditArchiveBatch(Base):
    """A verified range of audit events moved out of audit_event by pic.audit_archive_range(). The checkpoint (anchor_hash = the
    prev_hash of the first archived event, head_hash = the hash of the last) keeps the hash chain verifiable across the gap."""
    __tablename__ = "audit_archive_batch"
    __table_args__ = (
        UniqueConstraint("tenant_id", "seq_from"),
        CheckConstraint("seq_to >= seq_from AND event_count > 0", name="range_valid"),
        CheckConstraint("status IN ('ARCHIVED','EXPIRED')", name="status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.tenant.id"), index=True, nullable=False)
    seq_from: Mapped[int] = mapped_column(BigInteger, nullable=False)
    seq_to: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    anchor_hash: Mapped[Optional[str]] = mapped_column(String(64))
    head_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    first_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    archived_by: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ARCHIVED")
    expired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class AuditEventArchive(Base):
    """Audit events of archived batches (same columns as audit_event, original seq kept)."""
    __tablename__ = "audit_event_archive"
    __table_args__ = (Index("ix_audit_event_archive_batch", "tenant_id", "batch_id", "seq"),
                      Index("ix_audit_event_archive_object", "tenant_id", "object_type", "object_id"))
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.audit_archive_batch.id"), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.tenant.id"), index=True, nullable=False)
    object_type: Mapped[str] = mapped_column(String(40), nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    object_ref: Mapped[Optional[str]] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    actor: Mapped[str] = mapped_column(String(80), nullable=False)
    on_behalf_of: Mapped[Optional[str]] = mapped_column(String(80))
    before: Mapped[Optional[dict]] = mapped_column(JSONB)
    after: Mapped[Optional[dict]] = mapped_column(JSONB)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    rule_set_version: Mapped[Optional[str]] = mapped_column(String(80))
    ai_ref: Mapped[Optional[str]] = mapped_column(String(80))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prev_hash: Mapped[Optional[str]] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), nullable=False)


class TenantFlag(TenantScoped, Base):
    """Operational switches that are not versioned rules (e.g. AI_SWITCH: the tenant-wide AI kill switch)."""
    __tablename__ = "tenant_flag"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    changed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
