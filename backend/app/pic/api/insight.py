"""Command centre KPIs, Copilot (answer contract) and the real-time event stream."""
import asyncio
import json
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select

from app.pic.api.deps import uow
from app.pic.models import OutboxEvent
from app.pic.platform import agents as agent_registry
from app.pic.platform import clock, workflow
from app.pic.platform.auth import READ, Principal, require, require_any
from app.pic.services import copilot, insight

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
