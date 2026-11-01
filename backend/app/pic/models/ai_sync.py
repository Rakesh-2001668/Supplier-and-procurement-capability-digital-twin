"""ERP inbound sync (TD §12.1), external feeds (TD §12.3) and AI/ML governance (TD §13): sync cursors and runs, LLM call log,
model registry, evaluation runs, drift events and the risk-feed ledger. Migration 0014."""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Integer, Numeric, String, Text, UniqueConstraint, Index, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.pic.db import Base, TenantScoped


class ErpSyncCursor(TenantScoped, Base):
    """Delta cursor per source system and object kind (vendors, materials, stock, open POs ...)."""
    __tablename__ = "erp_sync_cursor"
    __table_args__ = (UniqueConstraint("tenant_id", "system", "object_kind"),)
    system: Mapped[str] = mapped_column(String(30), nullable=False)
    object_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    cursor: Mapped[Optional[str]] = mapped_column(String(200))
    cursor_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    last_status: Mapped[Optional[str]] = mapped_column(String(15))
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ErpSyncState(TenantScoped, Base):
    """Content hash of every object seen per source system: change detection without comparing field by field."""
    __tablename__ = "erp_sync_state"
    __table_args__ = (UniqueConstraint("tenant_id", "system", "object_kind", "object_key"),)
    system: Mapped[str] = mapped_column(String(30), nullable=False)
    object_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    object_key: Mapped[str] = mapped_column(String(120), nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ErpSyncRun(TenantScoped, Base):
    __tablename__ = "erp_sync_run"
    __table_args__ = (UniqueConstraint("tenant_id", "number"), UniqueConstraint("tenant_id", "idempotency_key"),
                      Index("ix_erp_sync_run_kind_started", "tenant_id", "object_kind", "started_at"),
                      CheckConstraint("status IN ('RUNNING','COMPLETED','PARTIAL','FAILED')", name="status"),
                      CheckConstraint("mode IN ('SCHEDULED','ON_DEMAND','RETRY')", name="mode"),
                      CheckConstraint("source IN ('AUTO','CONNECTOR','FILE_DROP','PAYLOAD')", name="source"))
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    system: Mapped[str] = mapped_column(String(30), nullable=False)
    object_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    mode: Mapped[str] = mapped_column(String(15), nullable=False)       # SCHEDULED | ON_DEMAND | RETRY
    source: Mapped[str] = mapped_column(String(15), nullable=False)     # CONNECTOR | FILE_DROP | PAYLOAD
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="RUNNING")  # RUNNING | COMPLETED | PARTIAL | FAILED
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cursor_before: Mapped[Optional[str]] = mapped_column(String(200))
    cursor_after: Mapped[Optional[str]] = mapped_column(String(200))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    counts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    rejects: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[Optional[str]] = mapped_column(Text)
    triggered_by: Mapped[Optional[str]] = mapped_column(String(80))
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(120))


class LlmCallLog(TenantScoped, Base):
    """Metadata of every gateway call (never the redacted-or-not prompt text itself): purpose, model, sizes, cost, redactions."""
    __tablename__ = "llm_call_log"
    __table_args__ = (Index("ix_llm_call_log_tenant_created", "tenant_id", "created_at"),
                      CheckConstraint("status IN ('OK','FALLBACK','BLOCKED','ERROR')", name="status"))
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(15), nullable=False)    # OK | FALLBACK | BLOCKED | ERROR
    reason: Mapped[Optional[str]] = mapped_column(String(300))
    prompt_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_micro: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)    # millionths of the budget currency
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    redactions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    prompt_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    response_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    retain_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class MlModel(TenantScoped, Base):
    """Model registry: one row per (model code, version) with parameters, training metrics and status."""
    __tablename__ = "ml_model"
    __table_args__ = (UniqueConstraint("tenant_id", "code", "version"),
                      CheckConstraint("status IN ('CANDIDATE','ACTIVE','RETIRED','SUSPENDED')", name="status"),
                      # at most one ACTIVE version per model code
                      Index("uq_ml_model_one_active", "tenant_id", "code", unique=True, postgresql_where=text("status = 'ACTIVE'")))
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)       # RULES | STATISTICAL | LOGISTIC | NAIVE_BAYES | BOOSTED_STUMPS | EMBEDDING | PARAMETRIC
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="CANDIDATE")  # CANDIDATE | ACTIVE | RETIRED | SUSPENDED
    description: Mapped[Optional[str]] = mapped_column(String(300))
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    baseline: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)   # training-time feature distributions (PSI reference)
    training: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)   # data window, row count, content hash, seed
    previous_version: Mapped[Optional[str]] = mapped_column(String(40))
    trained_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    suspended_reason: Mapped[Optional[str]] = mapped_column(String(300))


class MlEvalRun(TenantScoped, Base):
    __tablename__ = "ml_eval_run"
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    dataset: Mapped[str] = mapped_column(String(80), nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    gate: Mapped[Optional[bool]] = mapped_column(Boolean)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MlDriftEvent(TenantScoped, Base):
    __tablename__ = "ml_drift_event"
    __table_args__ = (CheckConstraint("status IN ('OK','ALERT')", name="status"), CheckConstraint("monitor IN ('PSI','ACCURACY')", name="monitor"),
                      CheckConstraint("action IN ('NONE','FALLBACK')", name="action"))
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    monitor: Mapped[str] = mapped_column(String(15), nullable=False)    # PSI | ACCURACY
    feature: Mapped[Optional[str]] = mapped_column(String(60))
    value: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    threshold: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False)      # OK | ALERT
    action: Mapped[str] = mapped_column(String(12), nullable=False, default="NONE")   # NONE | FALLBACK
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RiskFeedEvent(TenantScoped, Base):
    """Ledger of financial-risk / news events received by pull or webhook; (source, event id) makes ingestion idempotent."""
    __tablename__ = "risk_feed_event"
    __table_args__ = (UniqueConstraint("tenant_id", "source", "event_id"),
                      CheckConstraint("status IN ('INGESTED','DUPLICATE','UNMATCHED','REJECTED')", name="status"))
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str] = mapped_column(String(120), nullable=False)
    supplier_code: Mapped[Optional[str]] = mapped_column(String(30))
    category: Mapped[Optional[str]] = mapped_column(String(30))
    severity: Mapped[Optional[str]] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10), nullable=False)    # INGESTED | DUPLICATE | UNMATCHED | REJECTED
    reason: Mapped[Optional[str]] = mapped_column(String(300))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
