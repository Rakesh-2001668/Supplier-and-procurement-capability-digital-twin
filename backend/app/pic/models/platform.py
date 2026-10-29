"""Platform tables (M13): organisation, identity, numbering, rules, SoD, audit,
outbox, idempotency, lineage, workflow, integration and agents."""
import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Identity, Integer, Numeric, String, Text,
    UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.pic.db import SCHEMA, Base, TenantScoped, new_id, utcnow


class Tenant(Base):
    """Tenant directory. Not row-level secured: it holds only names and is needed to log in."""
    __tablename__ = "tenant"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    industry_template: Mapped[str] = mapped_column(String(40), nullable=False, default="MANUFACTURING")
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    timezone: Mapped[str] = mapped_column(String(40), nullable=False, default="Asia/Kolkata")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CompanyCode(TenantScoped, Base):
    __tablename__ = "company_code"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    gstin: Mapped[Optional[str]] = mapped_column(String(15))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    fiscal_year_start_month: Mapped[int] = mapped_column(Integer, default=4)


class Plant(TenantScoped, Base):
    __tablename__ = "plant"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    # Factory calendar: working weekdays (0=Mon) and holidays.
    working_days: Mapped[list] = mapped_column(ARRAY(Integer), default=lambda: [0, 1, 2, 3, 4, 5])
    holidays: Mapped[list] = mapped_column(ARRAY(Date), default=list)


class StorageLocation(TenantScoped, Base):
    __tablename__ = "storage_location"
    __table_args__ = (UniqueConstraint("tenant_id", "plant", "code"),)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class CostObject(TenantScoped, Base):
    """Cost centres, WBS elements, internal orders and assets (account assignment targets)."""
    __tablename__ = "cost_object"
    __table_args__ = (UniqueConstraint("tenant_id", "type", "code"),)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # COST_CENTER | WBS | ORDER | ASSET
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)
    owner_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    department_head_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))


class AppUser(TenantScoped, Base):
    __tablename__ = "app_user"
    __table_args__ = (UniqueConstraint("tenant_id", "email"),)
    email: Mapped[str] = mapped_column(String(200), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    roles: Mapped[list] = mapped_column(ARRAY(String(40)), nullable=False, default=list)
    # ABAC attributes: company_codes, plants, cost_objects, categories, steward_domains, value_limit_minor
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    mfa_enrolled: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class NumberRange(TenantScoped, Base):
    __tablename__ = "number_range"
    __table_args__ = (UniqueConstraint("tenant_id", "object_type"),)
    object_type: Mapped[str] = mapped_column(String(30), nullable=False)
    prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    next_value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    padding: Mapped[int] = mapped_column(Integer, default=0)


class RuleSet(TenantScoped, Base):
    """Effective-dated, scoped rule data (AD-07, P14). The most specific scope wins."""
    __tablename__ = "rule_set"
    __table_args__ = (UniqueConstraint("tenant_id", "key", "version"),)
    key: Mapped[str] = mapped_column(String(40), nullable=False)  # DMN-01, DMN-02, DMN-03, PO-RISK, ...
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    company_code: Mapped[Optional[str]] = mapped_column(String(10))
    plant: Mapped[Optional[str]] = mapped_column(String(10))
    category: Mapped[Optional[str]] = mapped_column(String(40))
    purchase_type: Mapped[Optional[str]] = mapped_column(String(30))
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Optional[date]] = mapped_column(Date)
    body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)


class SodRule(TenantScoped, Base):
    __tablename__ = "sod_rule"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    action_a: Mapped[str] = mapped_column(String(40), nullable=False)
    action_b: Mapped[str] = mapped_column(String(40), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)  # supplier_id | po_id | event_id | ...
    condition: Mapped[Optional[str]] = mapped_column(String(30))  # e.g. SOLE_EVALUATOR
    risk: Mapped[str] = mapped_column(String(10), nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="BLOCK")  # BLOCK | MITIGATE
    description: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ActionLog(TenantScoped, Base):
    """Who performed which SoD-relevant action on which objects (evaluated at command time)."""
    __tablename__ = "action_log"
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    refs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_agent: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (Index("ix_action_log_refs", "refs", postgresql_using="gin"),)


class SodViolation(TenantScoped, Base):
    __tablename__ = "sod_violation"
    rule_code: Mapped[str] = mapped_column(String(10), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    attempted_action: Mapped[str] = mapped_column(String(40), nullable=False)
    conflicting_action: Mapped[str] = mapped_column(String(40), nullable=False)
    refs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # BLOCKED | MITIGATION_REQUIRED


class AuditEvent(Base):
    """Append-only, hash-chained audit trail (§14, Appendix 19.3).

    The pic_app role only has INSERT and SELECT on this table, so rows cannot be
    altered from the application.
    """
    __tablename__ = "audit_event"
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=new_id, unique=True, nullable=False)
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
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    prev_hash: Mapped[Optional[str]] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (Index("ix_audit_event_object", "tenant_id", "object_type", "object_id"),)


class OutboxEvent(Base):
    """Transactional outbox (AD-03). Written in the same transaction as the domain change."""
    __tablename__ = "outbox_event"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.tenant.id"), index=True, nullable=False)
    topic: Mapped[str] = mapped_column(String(60), nullable=False)
    object_type: Mapped[str] = mapped_column(String(40), nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    object_ref: Mapped[Optional[str]] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    actor: Mapped[Optional[str]] = mapped_column(String(80))
    trace_id: Mapped[Optional[str]] = mapped_column(String(40))
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    # Back-off after a failed consumer (NULL: due now); outbox.relay_tenant skips events not yet due.
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_outbox_event_unpublished", "tenant_id", "published_at"),
                      Index("ix_outbox_event_due", "tenant_id", "published_at", "next_attempt_at"))


class ProcessedEvent(Base):
    """Consumer idempotency: each consumer handles an event at most once."""
    __tablename__ = "processed_event"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.tenant.id"), nullable=False)
    consumer: Mapped[str] = mapped_column(String(60), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_record"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.tenant.id"), primary_key=True)
    scope: Mapped[str] = mapped_column(String(200), primary_key=True)
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[Optional[int]] = mapped_column(Integer)
    response: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DocumentLink(Base):
    """Explicit lineage between document lines (§5.1, P10)."""
    __tablename__ = "document_link"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.tenant.id"), index=True, nullable=False)
    from_type: Mapped[str] = mapped_column(String(40), nullable=False)
    from_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    from_ref: Mapped[str] = mapped_column(String(60), nullable=False)
    from_line: Mapped[Optional[int]] = mapped_column(Integer)
    to_type: Mapped[str] = mapped_column(String(40), nullable=False)
    to_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    to_ref: Mapped[str] = mapped_column(String(60), nullable=False)
    to_line: Mapped[Optional[int]] = mapped_column(Integer)
    link_type: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (
        Index("ix_document_link_from", "tenant_id", "from_type", "from_id"),
        Index("ix_document_link_to", "tenant_id", "to_type", "to_id"),
    )


class ProcessDefinition(Base):
    """Versioned process models F1-F9 (shared, not tenant data)."""
    __tablename__ = "process_definition"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    flow_id: Mapped[str] = mapped_column(String(5), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProcessInstance(TenantScoped, Base):
    __tablename__ = "process_instance"
    process_key: Mapped[str] = mapped_column(String(60), nullable=False)
    process_version: Mapped[int] = mapped_column(Integer, nullable=False)
    business_type: Mapped[str] = mapped_column(String(40), nullable=False)
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    business_ref: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RUNNING")
    current_step: Mapped[Optional[str]] = mapped_column(String(60))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    variables: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (Index("ix_process_instance_business", "tenant_id", "business_type", "business_id"),)


class ProcessStep(TenantScoped, Base):
    """Token history: each step the instance passed through, with actor and outcome."""
    __tablename__ = "process_step"
    instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.process_instance.id"), index=True, nullable=False)
    step_id: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    lane: Mapped[str] = mapped_column(String(60), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # ACTIVE | COMPLETED | SKIPPED
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actor: Mapped[Optional[str]] = mapped_column(String(80))
    outcome: Mapped[Optional[str]] = mapped_column(Text)


class Task(TenantScoped, Base):
    """Human task (approval, steward decision, review)."""
    __tablename__ = "task"
    instance_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.process_instance.id"))
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    object_type: Mapped[str] = mapped_column(String(40), nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    object_ref: Mapped[str] = mapped_column(String(60), nullable=False)
    candidate_role: Mapped[str] = mapped_column(String(40), nullable=False)
    candidate_scope: Mapped[dict] = mapped_column(JSONB, default=dict)
    excluded_user_ids: Mapped[list] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    group_key: Mapped[Optional[str]] = mapped_column(String(120))
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    decision: Mapped[Optional[str]] = mapped_column(String(20))
    comment: Mapped[Optional[str]] = mapped_column(Text)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    rule_set_version: Mapped[Optional[str]] = mapped_column(String(80))
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (Index("ix_task_open", "tenant_id", "status", "candidate_role"),)


class Timer(TenantScoped, Base):
    __tablename__ = "timer"
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    object_type: Mapped[str] = mapped_column(String(40), nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    fired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)


class IntegrationMessage(TenantScoped, Base):
    """Exactly-once ERP posting ledger (§12.2)."""
    __tablename__ = "integration_message"
    __table_args__ = (UniqueConstraint("tenant_id", "target_system", "idempotency_key"),)
    target_system: Mapped[str] = mapped_column(String(30), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="OUTBOUND")
    message_type: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    object_type: Mapped[str] = mapped_column(String(40), nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    object_ref: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    erp_doc_no: Mapped[Optional[str]] = mapped_column(String(40))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ErpDocument(TenantScoped, Base):
    """Documents held by the simulated ERP (SAP S/4HANA sandbox stand-in).

    Lets the connector demonstrate query-before-retry: the ERP is looked up by
    external reference before any repost.
    """
    __tablename__ = "erp_document"
    __table_args__ = (UniqueConstraint("tenant_id", "system", "external_ref"),)
    system: Mapped[str] = mapped_column(String(30), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(30), nullable=False)
    doc_no: Mapped[str] = mapped_column(String(40), nullable=False)
    external_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)
    amount_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)


class Agent(TenantScoped, Base):
    __tablename__ = "agent"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    module: Mapped[str] = mapped_column(String(10), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    autonomy_level: Mapped[str] = mapped_column(String(2), nullable=False)  # L0..L4
    run_as_role: Mapped[str] = mapped_column(String(40), nullable=False)
    value_limit_minor: Mapped[Optional[int]] = mapped_column(BigInteger)
    categories: Mapped[list] = mapped_column(ARRAY(String(40)), default=list)
    kill_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    model_version: Mapped[str] = mapped_column(String(40), nullable=False)
    min_acceptance_rate: Mapped[float] = mapped_column(Numeric(4, 3), default=0.7)


class AgentRun(TenantScoped, Base):
    __tablename__ = "agent_run"
    agent_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    object_type: Mapped[str] = mapped_column(String(40), nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    object_ref: Mapped[str] = mapped_column(String(60), nullable=False)
    inputs: Mapped[dict] = mapped_column(JSONB, default=dict)
    evidence: Mapped[list] = mapped_column(JSONB, default=list)
    model_version: Mapped[str] = mapped_column(String(40), nullable=False)
    output: Mapped[dict] = mapped_column(JSONB, default=dict)
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(4, 3))
    autonomy_level: Mapped[str] = mapped_column(String(2), nullable=False)
    action_taken: Mapped[str] = mapped_column(String(40), nullable=False)  # EXECUTED | DRAFTED | RECOMMENDED | DENIED
    denial_reason: Mapped[Optional[str]] = mapped_column(Text)
    human_feedback: Mapped[Optional[str]] = mapped_column(String(20))  # ACCEPTED | REJECTED
