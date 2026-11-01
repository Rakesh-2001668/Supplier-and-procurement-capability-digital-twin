"""Command centre KPIs, Copilot (answer contract) and the real-time event stream."""
import asyncio
import json
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select

from app.pic.api.deps import idempotency_key, idempotent, uow
from app.pic.models import OutboxEvent
from app.pic.platform import agents as agent_registry
from app.pic.platform import clock, workflow
from app.pic.platform.auth import READ, TASKS, Principal, require, require_any
from app.pic.platform.core import check_if_match, etag
from app.pic.platform.errors import Problem
from app.pic.platform.serialize import row
from app.pic.services import copilot, insight, kpi, workspace

router = APIRouter(prefix="/v1", tags=["Command centre & Copilot"])


@router.get("/dashboard")
def dashboard(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return insight.dashboard(s, p)


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=500)


@router.post("/copilot/ask")
def ask(body: Question, p: Principal = Depends(require_any(READ, "supplier:portal"))):
    with uow(p) as s:
        if agent_registry.exists(s, "COPILOT"):  # the tenant-wide AI switch, the agent's kill switch and its suspension apply
            allowed, reason = agent_registry.guard(s, "COPILOT", required_level="L1")
            if not allowed:
                raise Problem(409, "AGENT_DISABLED", f"The Procurement Copilot is not available: {reason}", rule_ref="AI-CONTROL")
        answer = copilot.ask(s, p, body.question)
        try:
            agent_registry.log_run(s, "COPILOT", object_type="QUESTION", object_id=uuid.uuid4(), object_ref=body.question[:60],
                                   inputs={"question": body.question}, evidence=[e["ref"] for e in answer["evidence"]],
                                   output={"answer": answer["answer"]}, confidence=answer["confidence"]["score"], action_taken="RECOMMENDED")
        except Exception:  # tenants bootstrapped before the Copilot agent existed
            pass
        return answer


def _poll(principal: Principal, since: Optional[tuple]) -> tuple[list[dict], int, tuple]:
    with uow(principal) as s:
        events = []
        if "SUPPLIER_USER" not in principal.roles:
            q = select(OutboxEvent).order_by(OutboxEvent.occurred_at, OutboxEvent.id).limit(50)
            if since:
                q = q.where(or_(OutboxEvent.occurred_at > since[0], and_(OutboxEvent.occurred_at == since[0], OutboxEvent.id > since[1])))
            else:
                q = select(OutboxEvent).order_by(OutboxEvent.occurred_at.desc(), OutboxEvent.id.desc()).limit(1)
            rows = s.execute(q).scalars().all()
            for e in rows:
                events.append({"id": str(e.id), "type": e.topic, "ref": e.object_ref, "objectType": e.object_type,
                               "actor": e.actor, "at": e.occurred_at.isoformat()})
            if rows:
                since = (rows[-1].occurred_at, rows[-1].id)
            elif since is None:
                since = (clock.now(), uuid.UUID(int=0))
        tasks = len(workflow.open_tasks_for(s, principal)) if "tasks:work" in principal.scopes else 0
        return events, tasks, since


@router.get("/stream")
async def stream(request: Request, p: Principal = Depends(require_any(READ, "supplier:portal"))):
    """Server-sent events: domain events for the tenant and the caller's open-task count, every 3 s."""

    async def generate():
        since, last_tasks, first = None, None, True
        while True:
            if await request.is_disconnected():
                break
            events, tasks, since = await run_in_threadpool(_poll, p, since)
            if first:
                events, first = [], False  # the first poll only positions the cursor
            for e in events:
                yield f"event: domain\nid: {e['id']}\ndata: {json.dumps(e)}\n\n"
            if tasks != last_tasks:
                yield f"event: tasks\ndata: {json.dumps({'open': tasks})}\n\n"
                last_tasks = tasks
            yield ": keep-alive\n\n"
            await asyncio.sleep(3)

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- KPI framework (BP Table 28)
@router.get("/kpis", tags=["KPIs"])
def kpis(module: Optional[str] = Query(None, pattern="^(M0[1-9]|M1[0-3]|TEMPLATE)$"), period: Optional[str] = None, plant: Optional[str] = None,
         trend: bool = True, all_templates: bool = False, p: Principal = Depends(require(READ))):
    """Current value, status against target and the last six month-end snapshots of every KPI (optionally one module, month, plant)."""
    with uow(p) as s:
        items = kpi.read(s, module, period, plant, with_trend=trend, include_other_templates=all_templates)
        return {"period": period, "plant": plant, "items": items,
                "summary": {k: sum(1 for i in items if i["status"] == k) for k in ("GOOD", "WARN", "BAD", "NA")}}


@router.get("/kpis/registry", tags=["KPIs"])
def kpi_registry(p: Principal = Depends(require(READ))):
    """The KPI definitions: formula, unit, scope, thresholds, source."""
    with uow(p) as s:
        out = []
        for d in kpi.applicable(s, include_other_templates=True):
            target, warn = kpi.thresholds(s, d)
            out.append({"code": d.code, "module": d.module, "name": d.name, "unit": d.unit, "direction": d.direction, "formula": d.formula,
                        "source": d.source, "target": target, "warn": warn, "scopes": list(d.scopes), "pointInTime": d.point_in_time,
                        "templates": list(d.templates), "computable": d.compute is not None, "needs": d.needs})
        return out


@router.get("/kpis/{code}", tags=["KPIs"])
def kpi_detail(code: str, period: Optional[str] = None, plant: Optional[str] = None, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        definition = kpi.definition_of(code)
        return {**kpi.evaluate(s, definition, period, plant), "history": kpi.history(s, definition.code, 24)}


class SnapshotIn(BaseModel):
    period: Optional[str] = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


@router.post("/admin/kpis/snapshot", tags=["KPIs"])
def kpi_snapshot(body: SnapshotIn, p: Principal = Depends(require("admin:integration")), key: Optional[str] = Depends(idempotency_key)):
    """Persist the KPI values of a month now (the scheduler runs the same function at month end)."""
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/admin/kpis/snapshot", key, body)
        if idem.replay:
            return idem.replay
        return idem.store(kpi.snapshot_kpis(p.tenant_id, body.period, session=s))


# ---------------------------------------------------------------- tenant profile (workspace header)
TEMPLATE_LABELS = {"MANUFACTURING": "Manufacturing", "CONSTRUCTION": "Construction", "IT_SERVICES": "IT services", "LOGISTICS": "Logistics",
                   "HEALTHCARE": "Healthcare & life sciences", "GENERAL": "General enterprise"}


@router.get("/tenant", tags=["Identity"])
def tenant_profile(p: Principal = Depends(require_any(READ, "supplier:portal"))):
    """The signed-in tenant: code, name, industry template (with its display name), base currency and time zone."""
    from app.pic.models import Tenant
    with uow(p) as s:
        t = s.get(Tenant, p.tenant_id)
        return {"code": t.code, "name": t.name, "industryTemplate": t.industry_template,
                "templateLabel": TEMPLATE_LABELS.get(t.industry_template, (t.industry_template or "").replace("_", " ").title()),
                "baseCurrency": t.base_currency, "timezone": t.timezone}


# ---------------------------------------------------------------- saved views (per user, optionally shared)
class ViewIn(BaseModel):
    screen: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=80)
    filters: dict = Field(default_factory=dict)
    shared: bool = False
    is_default: bool = False


class ViewPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    filters: Optional[dict] = None
    shared: Optional[bool] = None
    is_default: Optional[bool] = None


@router.get("/saved-views", tags=["Saved views"])
def saved_views(screen: str = Query(min_length=1, max_length=60), p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return workspace.list_views(s, screen)


@router.post("/saved-views", status_code=201, tags=["Saved views"])
def create_saved_view(body: ViewIn, response: Response, p: Principal = Depends(require(READ)), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/saved-views", key, body)
        if idem.replay:
            return idem.replay
        view = workspace.create_view(s, body.screen, body.name, body.filters, body.shared, body.is_default)
        response.headers["ETag"] = etag(view)
        return idem.store(row(view, extra={"etag": etag(view)}), 201)


@router.patch("/saved-views/{view_id}", tags=["Saved views"])
def update_saved_view(view_id: uuid.UUID, body: ViewPatch, response: Response, p: Principal = Depends(require(READ)),
                      if_match: Optional[str] = Header(default=None, alias="If-Match")):
    with uow(p) as s:
        view = workspace.get_own_view(s, view_id)
        check_if_match(view, if_match)
        view = workspace.update_view(s, view, name=body.name, filters=body.filters, shared=body.shared, is_default=body.is_default)
        s.flush()
        response.headers["ETag"] = etag(view)
        return row(view, extra={"etag": etag(view)})


@router.delete("/saved-views/{view_id}", status_code=204, tags=["Saved views"])
def delete_saved_view(view_id: uuid.UUID, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        workspace.delete_view(s, workspace.get_own_view(s, view_id))
    return Response(status_code=204)


# ---------------------------------------------------------------- object page tabs: approvals and documents
@router.get("/documents/{object_type}/{ref}/approvals", tags=["Workflow"])
def document_approvals(object_type: str, ref: str, p: Principal = Depends(require(READ))):
    """Every approval task of a document, open and decided, with who decided what and when."""
    from app.pic.api.platform import resolve_document
    with uow(p) as s:
        return workspace.approvals_of(s, object_type, resolve_document(s, object_type, ref))


@router.get("/documents/{object_type}/{ref}/files", tags=["Workflow"])
def document_files(object_type: str, ref: str, p: Principal = Depends(require(READ))):
    """Printouts, EDI and ERP documents, signed documents, supplier-supplied files and linked documents of a document."""
    from app.pic.api.platform import resolve_document
    with uow(p) as s:
        return workspace.documents_of(s, object_type, resolve_document(s, object_type, ref))


# ---------------------------------------------------------------- bulk task decisions with a result per row
class BulkRow(BaseModel):
    task_id: uuid.UUID
    decision: str = Field(pattern="^(APPROVE|REJECT|RETURN)$")
    comment: Optional[str] = Field(default=None, max_length=2000)


class BulkIn(BaseModel):
    items: list[BulkRow] = Field(min_length=1, max_length=workspace.MAX_BULK)


@router.post("/tasks/bulk-complete", tags=["Workflow"])
def bulk_complete(body: BulkIn, p: Principal = Depends(require(TASKS)), key: Optional[str] = Depends(idempotency_key)):
    """Approve, reject or return several tasks at once. Rows are independent: a refused row (role, segregation of duties, missing
    comment, already decided) is reported with its error code and the other rows are still applied."""
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/tasks/bulk-complete", key, body)
        if idem.replay:
            return idem.replay
        return idem.store(workspace.bulk_decide(s, [{"task_id": r.task_id, "decision": r.decision, "comment": r.comment} for r in body.items]))
