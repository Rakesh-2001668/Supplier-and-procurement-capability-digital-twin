"""Identity, tasks, processes, lineage, audit, integration monitor, rules and agents (M13, AIX-03)."""
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.pic.api.deps import idempotency_key, idempotent, uow
from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    Agent, AgentRun, AppUser, Contract, GoodsReceipt, IntegrationMessage, Invoice, MaterialRequest, MrpRun, ProcessDefinition,
    ProcessInstance, PurchaseOrder, Requisition, RuleSet, ServiceEntry, SodRule, SodViolation, SourcingEvent, Supplier, Task, Tenant,
)
from app.pic.platform import audit, http, integration, mfa, workflow
from app.pic.platform.auth import (
    MFA_CHALLENGE, MFA_ENROLMENT, READ, TASKS, Principal, current_principal, require, token_response, user_challenge, verify_password,
)
from app.pic.platform.core import lineage
from app.pic.platform.errors import Problem, not_found
from app.pic.platform.serialize import row, rows

router = APIRouter(prefix="/v1")

DOC_MODELS = {
    "REQUISITION": Requisition, "PURCHASE_ORDER": PurchaseOrder, "SOURCING_EVENT": SourcingEvent, "CONTRACT": Contract,
    "INVOICE": Invoice, "GOODS_RECEIPT": GoodsReceipt, "SERVICE_ENTRY": ServiceEntry, "MATERIAL_REQUEST": MaterialRequest,
    "MRP_RUN": MrpRun,
}


def resolve_document(session, object_type: str, ref: str):
    model = DOC_MODELS.get(object_type.upper())
    if model is None:
        if object_type.upper() == "SUPPLIER":
            obj = session.execute(select(Supplier).where(Supplier.code == ref)).scalar_one_or_none()
            if obj:
                return obj
        raise Problem(404, "UNKNOWN_OBJECT_TYPE", f"Unknown object type {object_type}")
    try:
        obj = session.get(model, uuid.UUID(ref))
    except ValueError:
        obj = session.execute(select(model).where(model.number == ref)).scalar_one_or_none()
    if obj is None:
        raise not_found(object_type, ref)
    return obj


# ---------------------------------------------------------------- identity
class TokenRequest(BaseModel):
    tenant: str = Field(description="Tenant code, e.g. AXN")
    email: str
    password: str


@router.post("/auth/token", tags=["Identity"])
def token(body: TokenRequest, request: Request):
    with system_tx() as s:
        tenant = s.execute(select(Tenant).where(Tenant.code == body.tenant)).scalar_one_or_none()
    if tenant is None:
        http.record_login_failure(request)
        raise Problem(401, "INVALID_CREDENTIALS", "Unknown tenant, email or password")
    with tenant_tx(tenant.id) as s:
        user = s.execute(select(AppUser).where(AppUser.email == body.email.lower(), AppUser.active.is_(True))).scalar_one_or_none()
        if user is None or not verify_password(body.password, user.password_hash):
            http.record_login_failure(request)
            raise Problem(401, "INVALID_CREDENTIALS", "Unknown tenant, email or password")
        http.clear_login_failures(request)
        # §14 MFA: a confirmed authenticator means a second step; enforced roles without one must enrol first.
        if mfa.confirmed_factor(s, user.id) is not None:
            return {"mfaRequired": True, "challenge": user_challenge(MFA_CHALLENGE, user, tenant), "expiresIn": 300,
                    "methods": ["TOTP"], "tenant": tenant.code}
        if mfa.required_for(s, user):
            raise Problem(403, "MFA_ENROLMENT_REQUIRED", "Your role requires multi-factor authentication. Register an authenticator app to continue.",
                          rule_ref="MFA", enrolmentChallenge=user_challenge(MFA_ENROLMENT, user, tenant, ttl_seconds=900))
        return token_response(user, tenant)


@router.get("/me", tags=["Identity"])
def me(p: Principal = Depends(current_principal)):
    return {"userId": str(p.user_id), "user": p.email, "name": p.name, "tenant": p.tenant_code, "roles": p.roles, "scopes": sorted(p.scopes),
            "attributes": p.attributes, "supplierId": str(p.supplier_id) if p.supplier_id else None}


# ---------------------------------------------------------------- tasks (REQ-03 approval inbox)
class TaskDecision(BaseModel):
    decision: str = Field(pattern="^(APPROVE|REJECT|RETURN)$")
    comment: Optional[str] = None


@router.get("/tasks", tags=["Workflow"])
def my_tasks(p: Principal = Depends(require(TASKS))):
    with uow(p) as s:
        return [row(t, extra={"canComplete": True}) for t in workflow.open_tasks_for(s, p)]


@router.post("/tasks/{task_id}/complete", tags=["Workflow"])
def complete_task(task_id: uuid.UUID, body: TaskDecision, p: Principal = Depends(require(TASKS)),
                  key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/tasks/{task_id}/complete", key, body)
        if idem.replay:
            return idem.replay
        task = workflow.complete(s, task_id, body.decision, body.comment)
        return idem.store(row(task))


# ---------------------------------------------------------------- processes (BPMN token position)
@router.get("/process-definitions", tags=["Workflow"])
def process_definitions(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return [{"key": d.key, "flow": d.flow_id, "version": d.version, "name": d.name, "steps": d.definition["steps"],
                 "branches": d.definition.get("branches")}
                for d in s.execute(select(ProcessDefinition).order_by(ProcessDefinition.flow_id)).scalars()]


@router.get("/processes/{instance_id}", tags=["Workflow"])
def process(instance_id: uuid.UUID, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        instance = s.get(ProcessInstance, instance_id)
        if instance is None:
            raise not_found("Process instance", instance_id)
        return workflow.history(s, instance)


@router.get("/documents/{object_type}/{ref}/process", tags=["Workflow"])
def document_process(object_type: str, ref: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        obj = resolve_document(s, object_type, ref)
        instances = s.execute(select(ProcessInstance).where(ProcessInstance.business_id == obj.id).order_by(ProcessInstance.started_at)).scalars()
        return [workflow.history(s, i) for i in instances]


# ---------------------------------------------------------------- lineage and audit (P10, ADM-06)
@router.get("/lineage/{object_type}/{ref}", tags=["Lineage & Audit"])
def get_lineage(object_type: str, ref: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        obj = resolve_document(s, object_type, ref)
        return lineage(s, object_type.upper(), obj.id)


@router.get("/audit/verify", tags=["Lineage & Audit"])
def verify_audit(p: Principal = Depends(require("admin:audit"))):
    with uow(p) as s:
        return audit.verify_chain(s)


@router.get("/audit/{object_type}/{ref}", tags=["Lineage & Audit"])
def audit_trail(object_type: str, ref: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        obj = resolve_document(s, object_type, ref)
        return audit.trail(s, object_type.upper(), obj.id)


# ---------------------------------------------------------------- integration monitor (ADM-05)
@router.post("/integration/messages/{message_id}/replay", tags=["Integration"])
def replay_message(message_id: uuid.UUID, p: Principal = Depends(require("admin:integration"))):
    with uow(p) as s:
        return row(integration.replay(s, message_id))


# ---------------------------------------------------------------- rules (ADM-02) and SoD (ADM-04)
class RuleSetIn(BaseModel):
    key: str
    version: str
    effective_from: date
    effective_to: Optional[date] = None
    company_code: Optional[str] = None
    plant: Optional[str] = None
    category: Optional[str] = None
    purchase_type: Optional[str] = None
    body: dict
    description: Optional[str] = None


@router.get("/admin/rules", tags=["Administration"])
def list_rules(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return rows(s.execute(select(RuleSet).order_by(RuleSet.key, RuleSet.effective_from)).scalars())


@router.post("/admin/rules", status_code=201, tags=["Administration"])
def new_rule_version(body: RuleSetIn, p: Principal = Depends(require("admin:rules"))):
    """Rule changes are new effective-dated versions; existing versions are never edited (P14)."""
    with uow(p) as s:
        rule = RuleSet(tenant_id=p.tenant_id, created_by=p.user_id, **body.model_dump())
        s.add(rule)
        s.flush()
        audit.record(s, "RULE_SET", rule.id, "VERSION_CREATED", object_ref=f"{rule.key}@{rule.version}", after=body.model_dump(mode="json"))
        return row(rule)


@router.get("/admin/sod", tags=["Administration"])
def sod_rules(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return {"rules": rows(s.execute(select(SodRule).order_by(SodRule.code)).scalars()),
                "violations": rows(s.execute(select(SodViolation).order_by(SodViolation.created_at.desc())).scalars())}


# ---------------------------------------------------------------- agents (AIX-03)
@router.get("/agents", tags=["Agents"])
def list_agents(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return rows(s.execute(select(Agent).order_by(Agent.module, Agent.code)).scalars())


@router.get("/agents/{code}/runs", tags=["Agents"])
def agent_runs(code: str, limit: int = Query(default=50, ge=1, le=200), p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return rows(s.execute(select(AgentRun).where(AgentRun.agent_code == code.upper())
                              .order_by(AgentRun.created_at.desc()).limit(limit)).scalars())


class KillSwitch(BaseModel):
    on: bool
    reason: str


@router.put("/agents/{code}/kill-switch", tags=["Agents"])
def kill_switch(code: str, body: KillSwitch, p: Principal = Depends(require("agents:manage"))):
    with uow(p) as s:
        agent = s.execute(select(Agent).where(Agent.code == code.upper())).scalar_one_or_none()
        if agent is None:
            raise not_found("Agent", code)
        agent.kill_switch = body.on
        audit.record(s, "AGENT", agent.id, "KILL_SWITCH_ON" if body.on else "KILL_SWITCH_OFF", object_ref=agent.code, reason=body.reason)
        return row(agent)


# ---------------------------------------------------------------- operations
@router.post("/admin/ops/tick", tags=["Administration"])
def ops_tick(p: Principal = Depends(require("admin:ops"))):
    """Run the background worker once: outbox relay, due timers, ERP retries."""
    from app.pic.worker import tick
    return tick()
