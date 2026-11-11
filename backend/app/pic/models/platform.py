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
    # New tenants start with MFA enforced for approver / finance / admin roles (bootstrap writes rule MFA with enforce=true);
    # the bundled demo tenants stay false until the operator flips them.
    mfa_enforce: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # One platform for buyers and suppliers: what the organisation is, and where it is in its registration (sign-in needs ACTIVE).
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="BUYER", server_default="BUYER")  # BUYER | SUPPLIER | PLATFORM
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", server_default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrgRegistration(Base):
    """Self-service organisation registration request (migration 0030). Global and not granted to the application role: the public
    registration endpoints and the platform operator console use it as the owner, after their own checks (services/registration.py)."""
    __tablename__ = "org_registration"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # BUYER | SUPPLIER
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    state_code: Mapped[Optional[str]] = mapped_column(String(2))
    industry_template: Mapped[str] = mapped_column(String(40), nullable=False)
    gstin: Mapped[Optional[str]] = mapped_column(String(15))
    org_email: Mapped[str] = mapped_column(String(200), nullable=False)       # the company's shared mailbox: verification and decisions
    org_domain: Mapped[str] = mapped_column(String(200), nullable=False)
    admin_name: Mapped[str] = mapped_column(String(200), nullable=False)      # the named first administrator (the sign-in account)
    admin_email: Mapped[str] = mapped_column(String(200), nullable=False)
    admin_phone: Mapped[Optional[str]] = mapped_column(String(20))
    authorised_by_name: Mapped[Optional[str]] = mapped_column(String(200))    # optional senior person who vouches (e.g. CEO, director)
    authorised_by_designation: Mapped[Optional[str]] = mapped_column(String(120))
    expected_users: Mapped[Optional[int]] = mapped_column(Integer)
    verify_token_hash: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    verify_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    screening: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    organisation_code: Mapped[Optional[str]] = mapped_column(String(20))
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.tenant.id"))
    decided_by: Mapped[Optional[str]] = mapped_column(String(200))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[Optional[str]] = mapped_column(Text)
    request_ip: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoginDirectory(Base):
    """E-mail -> (organisation, user) for sign-in by e-mail (migration 0029). Global, not row-level secured, and not granted to the
    application role: only the sign-in code reads it, as the owner. A database trigger on app_user maintains it; never written by services."""
    __tablename__ = "login_directory"
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.tenant.id", ondelete="CASCADE"), primary_key=True)
    app_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CompanyCode(TenantScoped, Base):
    __tablename__ = "company_code"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    gstin: Mapped[Optional[str]] = mapped_column(String(15))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    fiscal_year_start_month: Mapped[int] = mapped_column(Integer, default=4)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")  # deactivated instead of deleted once referenced


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
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")  # deactivated instead of deleted once referenced


class StorageLocation(TenantScoped, Base):
    __tablename__ = "storage_location"
    __table_args__ = (UniqueConstraint("tenant_id", "plant", "code"),)
    plant: Mapped[str] = mapped_column(String(10), nullable=False)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")  # deactivated instead of deleted once referenced


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
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")  # deactivated instead of deleted once referenced


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
    # Bumped to sign the user out everywhere (admin "revoke sessions", password reset): the token carries the value it was issued at.
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # True from the admin invitation until the user sets a password through the single-use activation link.
    activation_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


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
    supplier_group: Mapped[Optional[str]] = mapped_column(String(30))  # BP M10: tolerances by company code and supplier group
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
    # Versioned, editable definitions (item 49): DRAFT -> ACTIVE -> RETIRED. ``active`` mirrors status == ACTIVE. Version 1 of
    # each flow is shared (tenant_id NULL); a tenant's own drafts and published versions carry its tenant_id (RLS in migration
    # 0013) and take precedence over the shared one for that tenant. Version numbers are unique per key across both.
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ACTIVE", server_default="ACTIVE")
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.tenant.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")  # ETag of an editable draft
    note: Mapped[Optional[str]] = mapped_column(Text)
    base_version: Mapped[Optional[int]] = mapped_column(Integer)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


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
    # Field mapping (item 50): what the connector actually received, and the mapping version that produced it.
    outbound_payload: Mapped[Optional[dict]] = mapped_column(JSONB)
    mapping_version: Mapped[Optional[int]] = mapped_column(Integer)


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
    # Why and when the switch was turned on (automatic drift suspension or a person); acceptance_reset_at restarts the feedback window
    suspended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    suspension_reason: Mapped[Optional[str]] = mapped_column(Text)
    suspended_by: Mapped[Optional[str]] = mapped_column(String(80))
    acceptance_reset_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


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
