"""Wave 1 platform API: scheduled jobs, delegation of authority, the AI switch, audit archive and retention, event catalogue."""
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.pic.api.deps import idempotency_key, idempotent, uow
from app.pic.models import Agent, AuditArchiveBatch
from app.pic.platform import agents, audit
from app.pic.platform.auth import READ, Principal, current_principal, require
from app.pic.platform.core import check_if_match, etag
from app.pic.platform.errors import Problem
from app.pic.services import delegation as delegation_svc
from app.pic.services import jobs, privacy

router = APIRouter(prefix="/v1")


# ---------------------------------------------------------------- scheduled jobs (admin:ops)
class JobPatch(BaseModel):
    enabled: Optional[bool] = None
    schedule: Optional[str] = Field(default=None, min_length=5, max_length=80, description="cron: minute hour day-of-month month day-of-week, or @daily")
    reason: Optional[str] = Field(default=None, max_length=500)


class JobRunIn(BaseModel):
    dryRun: bool = False
    params: dict = Field(default_factory=dict, description="job parameters, e.g. {\"period\": \"2026-09\"} for scorecard-monthly")


@router.get("/admin/jobs", tags=["Scheduler"])
def list_jobs(p: Principal = Depends(require("admin:ops"))):
    with uow(p) as s:
        return jobs.list_jobs(s)


@router.get("/admin/jobs/{job_key}/runs", tags=["Scheduler"])
def job_runs(job_key: str, limit: int = Query(default=50, ge=1, le=200), p: Principal = Depends(require("admin:ops"))):
    with uow(p) as s:
        return jobs.history(s, job_key, limit)


@router.put("/admin/jobs/{job_key}", tags=["Scheduler"])
def configure_job(job_key: str, body: JobPatch, response: Response, p: Principal = Depends(require("admin:ops")),
                  if_match: Optional[str] = Header(default=None, alias="If-Match")):
    if body.enabled is None and body.schedule is None:
        raise Problem(422, "NOTHING_TO_CHANGE", "Give enabled and/or schedule", rule_ref="JOBS")
    with uow(p) as s:
        row = jobs.get_row(s, job_key)
        check_if_match(row, if_match)
        row = jobs.configure(s, job_key, enabled=body.enabled, schedule=body.schedule, reason=body.reason)
        response.headers["ETag"] = etag(row)
        return jobs.job_view(row)


@router.post("/admin/jobs/{job_key}/run", tags=["Scheduler"])
def run_job(job_key: str, body: JobRunIn, p: Principal = Depends(require("admin:ops")), idem_key: Optional[str] = Depends(idempotency_key)):
    """Run a job now (or its dry run). The run is executed in its own transactions, single-flight with the scheduled runs."""
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/admin/jobs/{job_key}/run", idem_key, body)
        if idem.replay:
            return idem.replay
        # The run uses its own transactions: nothing may be written (registry rows, audit lock) in this one before it finishes.
        outcome = jobs.run_now(p.tenant_id, job_key, requested_by=p.actor, dry_run=body.dryRun, params=body.params)
        audit.record(s, "SCHEDULED_JOB", jobs.get_row(s, job_key).id, "JOB_RUN_REQUESTED", object_ref=job_key,
                     after={"run": outcome.get("id"), "status": outcome.get("status"), "dryRun": body.dryRun, "params": body.params})
        return idem.store(outcome)


# ---------------------------------------------------------------- delegation of authority
class DelegationIn(BaseModel):
    delegateId: Optional[uuid.UUID] = None
    delegateEmail: Optional[str] = Field(default=None, max_length=200)
    delegatorId: Optional[uuid.UUID] = Field(default=None, description="administrators only: create it for this user")
    validFrom: date
    validTo: date
    roles: list[str] = Field(default_factory=list, max_length=20)
    valueLimitMinor: Optional[int] = Field(default=None, gt=0)
    reason: str = Field(min_length=5, max_length=500)


class RevokeIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


def _create_delegation(s, body: DelegationIn, delegator_id: Optional[uuid.UUID]) -> dict:
    if body.delegateId is None and not body.delegateEmail:
        raise Problem(422, "DELEGATE_REQUIRED", "Choose the delegate", rule_ref="DELEGATION")
    delegate_id = body.delegateId or delegation_svc.user_by_email(s, body.delegateEmail).id
    return delegation_svc.create(s, delegator_id=delegator_id, delegate_id=delegate_id, valid_from=body.validFrom, valid_to=body.validTo,
                                 roles=body.roles, value_limit_minor=body.valueLimitMinor, reason=body.reason)


@router.get("/me/delegations", tags=["Delegation"])
def my_delegations(p: Principal = Depends(current_principal)):
    with uow(p) as s:
        return delegation_svc.mine(s)


@router.get("/me/delegation-candidates", tags=["Delegation"])
def delegation_candidates(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return delegation_svc.candidates(s)


@router.post("/me/delegations", status_code=201, tags=["Delegation"])
def create_my_delegation(body: DelegationIn, p: Principal = Depends(require(READ)), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/me/delegations", key, body)
        if idem.replay:
            return idem.replay
        return idem.store(_create_delegation(s, body, None), 201)


@router.post("/me/delegations/{delegation_id}/revoke", tags=["Delegation"])
def revoke_my_delegation(delegation_id: uuid.UUID, body: RevokeIn, p: Principal = Depends(require(READ)),
                         key: Optional[str] = Depends(idempotency_key), if_match: Optional[str] = Header(default=None, alias="If-Match")):
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/me/delegations/{delegation_id}/revoke", key, body)
        if idem.replay:
            return idem.replay
        _check_version(s, delegation_id, if_match)
        return idem.store(delegation_svc.revoke(s, delegation_id, body.reason))


def _check_version(s, delegation_id: uuid.UUID, if_match: Optional[str]) -> None:
    from app.pic.models import Delegation
    d = s.get(Delegation, delegation_id)
    if d is not None:
        check_if_match(d, if_match)


@router.get("/admin/delegations", tags=["Delegation"])
def delegation_overview(status: Optional[str] = Query(default=None, pattern="^(ACTIVE|SCHEDULED|EXPIRED|REVOKED)$"),
                        p: Principal = Depends(require("admin:ops"))):
    with uow(p) as s:
        return delegation_svc.overview(s, status)


@router.post("/admin/delegations", status_code=201, tags=["Delegation"])
def create_delegation_for(body: DelegationIn, p: Principal = Depends(require("admin:ops")), key: Optional[str] = Depends(idempotency_key)):
    if body.delegatorId is None:
        raise Problem(422, "DELEGATOR_REQUIRED", "Give delegatorId: whose approvals are delegated", rule_ref="DELEGATION")
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/admin/delegations", key, body)
        if idem.replay:
            return idem.replay
        return idem.store(_create_delegation(s, body, body.delegatorId), 201)


@router.post("/admin/delegations/{delegation_id}/revoke", tags=["Delegation"])
def revoke_delegation(delegation_id: uuid.UUID, body: RevokeIn, p: Principal = Depends(require("admin:ops")),
                      key: Optional[str] = Depends(idempotency_key), if_match: Optional[str] = Header(default=None, alias="If-Match")):
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/admin/delegations/{delegation_id}/revoke", key, body)
        if idem.replay:
            return idem.replay
        _check_version(s, delegation_id, if_match)
        return idem.store(delegation_svc.revoke(s, delegation_id, body.reason))


# ---------------------------------------------------------------- AI switch and agent acceptance
class AiSwitchIn(BaseModel):
    enabled: bool
    reason: str = Field(min_length=5, max_length=500)


@router.get("/admin/ai/switch", tags=["Agents"])
def ai_switch(response: Response, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        state = agents.ai_switch_state(s)
        response.headers["ETag"] = f'"{state["version"]}"'
        return state


@router.put("/admin/ai/switch", tags=["Agents"])
def set_ai_switch(body: AiSwitchIn, response: Response, p: Principal = Depends(require("agents:manage")),
                  key: Optional[str] = Depends(idempotency_key), if_match: Optional[str] = Header(default=None, alias="If-Match")):
    """Tenant-wide AI kill switch: while off, every agent call is refused by the guard (and logged as DENIED)."""
    with uow(p) as s:
        idem = idempotent(s, "PUT /v1/admin/ai/switch", key, body)
        if idem.replay:
            return idem.replay
        if if_match is not None and if_match.strip('"') != str(agents.ai_switch_state(s)["version"]):
            raise Problem(412, "STALE_WRITE", "The AI switch changed since you loaded it")
        state = agents.set_ai_switch(s, body.enabled, body.reason)
        response.headers["ETag"] = f'"{state["version"]}"'
        return idem.store(state)


@router.get("/agents-acceptance", tags=["Agents"])
def agents_acceptance(p: Principal = Depends(require(READ))):
    """Per agent: feedback events in the window, acceptance rate, minimum, and whether it was suspended (and why)."""
    with uow(p) as s:
        out = []
        for agent in s.execute(select(Agent).order_by(Agent.module, Agent.code)).scalars():
            stats = agents.acceptance_stats(s, agent.code)
            out.append({"code": agent.code, "events": stats["events"], "accepted": stats["accepted"],
                        "rate": float(stats["rate"]) if stats["rate"] is not None else None, "minFeedback": stats["minFeedback"],
                        "minimum": float(agent.min_acceptance_rate), "killSwitch": agent.kill_switch,
                        "suspendedAt": agent.suspended_at.isoformat() if agent.suspended_at else None,
                        "suspendedBy": agent.suspended_by, "suspensionReason": agent.suspension_reason})
        return out


# ---------------------------------------------------------------- audit archive and retention (admin)
class DryRunIn(BaseModel):
    dryRun: bool = True


@router.get("/admin/audit/archive", tags=["Lineage & Audit"])
def audit_archive_batches(p: Principal = Depends(require("admin:audit"))):
    with uow(p) as s:
        rows = s.execute(select(AuditArchiveBatch).order_by(AuditArchiveBatch.seq_from)).scalars().all()
        return {"batches": [{"id": str(b.id), "seqFrom": b.seq_from, "seqTo": b.seq_to, "events": b.event_count, "anchorHash": b.anchor_hash,
                             "headHash": b.head_hash, "contentSha256": b.content_sha256, "from": b.first_ts.isoformat(),
                             "to": b.last_ts.isoformat(), "archivedAt": b.archived_at.isoformat(), "archivedBy": b.archived_by,
                             "status": b.status} for b in rows],
                "verification": audit.verify_chain(s)}


@router.post("/admin/audit/archive", tags=["Lineage & Audit"])
def run_audit_archive(body: DryRunIn, p: Principal = Depends(require("admin:audit")), key: Optional[str] = Depends(idempotency_key)):
    """Archive audit events older than the hot window now (default: dry run). The hash chain is verified before and after."""
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/admin/audit/archive", key, body)
        if idem.replay:
            return idem.replay
        privacy._require_admin(s)
        result = privacy.archive_audit(s, dry_run=body.dryRun)
        result["verification"] = audit.verify_chain(s)
        return idem.store(result)


@router.post("/admin/privacy/retention/purge", tags=["Privacy"])
def run_retention_purge(body: DryRunIn, p: Principal = Depends(require("admin:ops")), key: Optional[str] = Depends(idempotency_key)):
    """Apply PRIVACY-RETENTION now (default: dry run, only the counts)."""
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/admin/privacy/retention/purge", key, body)
        if idem.replay:
            return idem.replay
        privacy._require_admin(s)
        return idem.store(privacy.apply_retention(s, dry_run=body.dryRun))


# ---------------------------------------------------------------- event catalogue
@router.get("/admin/events/catalogue", tags=["Events"])
def event_catalogue(p: Principal = Depends(require("admin:ops"))):
    from app.pic.events import catalogue
    return catalogue.catalogue()
