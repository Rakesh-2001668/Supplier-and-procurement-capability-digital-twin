"""Postgres-native workflow engine for F1-F9 (stands in for Camunda 8, AD-01).

- Process instances record every step the token passes (process_step).
- Human tasks implement approval chains: sequential (each approver sees the
  previous decision) or parallel (e.g. MDM domain stewards). Previous
  approvers in a chain are excluded from later tasks (four-eyes).
- Timers drive SLAs, sourcing close, certificate expiry and contract renewal.

Domain services register handlers for task outcomes and timers; the engine
never changes document state itself.
"""
import uuid
from datetime import datetime, timedelta
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant, current_user, system_tx, tenant_tx
from app.pic.models import ProcessDefinition, ProcessInstance, ProcessStep, Task, Tenant, Timer
from app.pic.platform import audit, clock
from app.pic.platform.errors import Problem, not_found

TaskHandler = Callable[[Session, Task, str], None]  # (session, last task, outcome APPROVED|REJECTED|RETURNED)
TimerHandler = Callable[[Session, Timer], None]
_task_handlers: dict[str, TaskHandler] = {}
_task_guards: dict[str, Callable[[Session, Task, str], None]] = {}
_timer_handlers: dict[str, TimerHandler] = {}


def guard_task(kind: str):
    """Register a check (e.g. SoD) run before a task of this kind can be completed."""
    def decorator(fn):
        _task_guards[kind] = fn
        return fn
    return decorator


def on_task(kind: str):
    def decorator(fn: TaskHandler) -> TaskHandler:
        _task_handlers[kind] = fn
        return fn
    return decorator


def on_timer(kind: str):
    def decorator(fn: TimerHandler) -> TimerHandler:
        _timer_handlers[kind] = fn
        return fn
    return decorator


# ---------------------------------------------------------------- process instances
_definition_cache: dict[str, dict] = {}


def _definition(session: Session, key: str) -> ProcessDefinition:
    definition = session.execute(
        select(ProcessDefinition).where(ProcessDefinition.key == key, ProcessDefinition.active.is_(True))
        .order_by(ProcessDefinition.version.desc()).limit(1)
    ).scalar_one_or_none()
    if definition is None:
        raise Problem(500, "PROCESS_DEFINITION_MISSING", f"Process {key} is not deployed")
    return definition


def _step_meta(definition: ProcessDefinition, step_id: str) -> dict:
    for step in definition.definition["steps"]:
        if step["id"] == step_id:
            return step
    raise Problem(500, "PROCESS_STEP_UNKNOWN", f"{step_id} not in {definition.key}")


def _actor(session: Session) -> str:
    principal = session.info.get("principal")
    return principal.actor if principal else "system"


def start(session: Session, process_key: str, business_type: str, business_id: uuid.UUID, business_ref: str,
          variables: Optional[dict] = None) -> ProcessInstance:
    definition = _definition(session, process_key)
    instance = ProcessInstance(
        tenant_id=current_tenant(session), process_key=process_key, process_version=definition.version,
        business_type=business_type, business_id=business_id, business_ref=business_ref, status="RUNNING",
        variables=variables or {}, started_at=clock.now(), created_by=current_user(session),
    )
    session.add(instance)
    session.flush()
    first = definition.definition["steps"][0]
    step(session, instance, first["id"])
    return instance


def find(session: Session, business_type: str, business_id: uuid.UUID, process_key: Optional[str] = None) -> Optional[ProcessInstance]:
    query = select(ProcessInstance).where(ProcessInstance.business_type == business_type, ProcessInstance.business_id == business_id)
    if process_key:
        query = query.where(ProcessInstance.process_key == process_key)
    return session.execute(query.order_by(ProcessInstance.started_at.desc()).limit(1)).scalar_one_or_none()


def step(session: Session, instance: ProcessInstance, step_id: str, *, outcome: Optional[str] = None,
         actor: Optional[str] = None, status: str = "COMPLETED") -> ProcessStep:
    """Record the token passing (status COMPLETED) or waiting at (ACTIVE) a step."""
    definition = session.get(ProcessDefinition, (instance.process_key, instance.process_version))
    meta = _step_meta(definition, step_id)
    now = clock.now()
    active = session.execute(
        select(ProcessStep).where(ProcessStep.instance_id == instance.id, ProcessStep.step_id == step_id,
                                  ProcessStep.status == "ACTIVE")
    ).scalar_one_or_none()
    if active is not None:
        active.status = status
        active.completed_at = now if status != "ACTIVE" else None
        active.actor = actor or _actor(session)
        active.outcome = outcome or active.outcome
        record = active
    else:
        record = ProcessStep(
            tenant_id=instance.tenant_id, instance_id=instance.id, step_id=step_id, name=meta["name"], lane=meta["lane"],
            type=meta["type"], status=status, entered_at=now, completed_at=now if status != "ACTIVE" else None,
            actor=actor or _actor(session), outcome=outcome, created_by=current_user(session),
        )
        session.add(record)
    instance.current_step = step_id
    session.flush()
    return record


def wait(session: Session, instance: ProcessInstance, step_id: str, outcome: Optional[str] = None) -> ProcessStep:
    return step(session, instance, step_id, outcome=outcome, status="ACTIVE")


def end(session: Session, instance: ProcessInstance, step_id: str, outcome: str, status: str = "COMPLETED") -> None:
    step(session, instance, step_id, outcome=outcome)
    instance.status = status
    instance.ended_at = clock.now()


def history(session: Session, instance: ProcessInstance) -> dict:
    definition = session.get(ProcessDefinition, (instance.process_key, instance.process_version))
    steps = session.execute(
        select(ProcessStep).where(ProcessStep.instance_id == instance.id).order_by(ProcessStep.entered_at, ProcessStep.id)
    ).scalars().all()
    tasks = session.execute(select(Task).where(Task.instance_id == instance.id).order_by(Task.created_at)).scalars().all()
    return {
        "id": str(instance.id), "process": instance.process_key, "flow": definition.flow_id, "name": definition.name,
        "version": instance.process_version, "business": {"type": instance.business_type, "id": str(instance.business_id),
                                                          "ref": instance.business_ref},
        "status": instance.status, "currentStep": instance.current_step,
        "startedAt": instance.started_at.isoformat(), "endedAt": instance.ended_at.isoformat() if instance.ended_at else None,
        "path": [{"step": s.step_id, "name": s.name, "lane": s.lane, "type": s.type, "status": s.status,
                  "actor": s.actor, "outcome": s.outcome, "at": s.entered_at.isoformat()} for s in steps],
        "tasks": [{"id": str(t.id), "name": t.name, "role": t.candidate_role, "status": t.status, "decision": t.decision,
                   "comment": t.comment, "completedAt": t.completed_at.isoformat() if t.completed_at else None}
                  for t in tasks],
    }


# ---------------------------------------------------------------- human tasks
def start_approval(session: Session, instance: Optional[ProcessInstance], kind: str, *, object_type: str,
                   object_id: uuid.UUID, object_ref: str, chain: list[str], step_id: Optional[str],
                   initiator_id: Optional[uuid.UUID], mode: str = "SEQUENTIAL", scopes: Optional[dict] = None,
                   sla_business_days: int = 2, rule_set_version: Optional[str] = None,
                   evidence: Optional[dict] = None, exclude: Optional[list[uuid.UUID]] = None) -> list[Task]:
    """Create approval tasks for a chain of roles. Returns the tasks opened now."""
    if not chain:
        return []
    group_key = f"{kind}:{object_id}:{uuid.uuid4().hex[:8]}"
    excluded = [i for i in ([initiator_id] if initiator_id else []) + list(exclude or [])]
    scopes = scopes or {}
    roles = chain if mode == "PARALLEL" else chain[:1]
    created = []
    for index, role in enumerate(roles, start=1):
        created.append(_open_task(session, instance, kind, object_type, object_id, object_ref, role, scopes.get(role, {}),
                                  excluded, group_key, index, sla_business_days, rule_set_version, evidence or {}))
    if instance is not None:
        instance.variables = {**(instance.variables or {}), group_key: {"chain": chain, "mode": mode, "kind": kind,
                                                                       "scopes": scopes, "sla": sla_business_days,
                                                                       "step": step_id}}
        if step_id:
            wait(session, instance, step_id, outcome=f"awaiting {', '.join(chain)}")
    session.flush()
    return created


def _open_task(session, instance, kind, object_type, object_id, object_ref, role, scope, excluded, group_key, sequence,
               sla_days, rule_set_version, evidence) -> Task:
    due = clock.add_business_days(clock.now(), sla_days)
    task = Task(
        tenant_id=current_tenant(session), instance_id=instance.id if instance else None, kind=kind,
        name=f"{kind.replace('_', ' ').title()} · {object_ref} · {role.replace('_', ' ').title()}",
        object_type=object_type, object_id=object_id, object_ref=object_ref, candidate_role=role,
        candidate_scope=scope, excluded_user_ids=excluded, group_key=group_key, sequence=sequence, status="OPEN",
        due_at=due, rule_set_version=rule_set_version, evidence=evidence, created_by=current_user(session),
    )
    session.add(task)
    session.flush()
    create_timer(session, "TASK_SLA", "TASK", task.id, due, {"group": group_key})
    audit.record(session, object_type, object_id, "TASK_CREATED", object_ref=object_ref,
                 after={"task": str(task.id), "role": role, "due": due.isoformat()}, rule_set_version=rule_set_version)
    return task


def can_work(principal, task: Task) -> Optional[str]:
    """Return a reason the principal may not complete the task, or None."""
    if task.candidate_role not in principal.roles:
        return f"task requires role {task.candidate_role}"
    if principal.user_id in (task.excluded_user_ids or []):
        return "four-eyes rule: you initiated or already approved this document"
    scope = task.candidate_scope or {}
    if "cost_object" in scope:
        if scope["cost_object"] not in (principal.attr("cost_objects") or []):
            return f"you are not the owner of {scope['cost_object']}"
    if "steward_domain" in scope:
        if scope["steward_domain"] not in (principal.attr("steward_domains") or []):
            return f"you are not a {scope['steward_domain']} data steward"
    if "category" in scope:
        cats = principal.attr("categories") or []
        if "*" not in cats and scope["category"] not in cats:
            return f"you are not assigned to category {scope['category']}"
    if "plant" in scope:
        plants = principal.attr("plants") or []
        if "*" not in plants and scope["plant"] not in plants:
            return f"you are not assigned to plant {scope['plant']}"
    return None


def open_tasks_for(session: Session, principal) -> list[Task]:
    tasks = session.execute(
        select(Task).where(Task.status == "OPEN", Task.candidate_role.in_(principal.roles)).order_by(Task.due_at)
    ).scalars().all()
    return [t for t in tasks if can_work(principal, t) is None]


def complete(session: Session, task_id: uuid.UUID, decision: str, comment: Optional[str] = None,
             evidence: Optional[dict] = None) -> Task:
    principal = session.info["principal"]
    task = session.get(Task, task_id, with_for_update=True)
    if task is None:
        raise not_found("Task", task_id)
    if task.status != "OPEN":
        raise Problem(409, "TASK_CLOSED", f"Task is already {task.status}")
    decision = decision.upper()
    if decision not in ("APPROVE", "REJECT", "RETURN"):
        raise Problem(422, "INVALID_DECISION", "decision must be APPROVE, REJECT or RETURN")
    if decision in ("REJECT", "RETURN") and not comment:
        raise Problem(422, "COMMENT_REQUIRED", "A comment is required to reject or return")
    reason = can_work(principal, task)
    if reason:
        raise Problem(403, "NOT_YOUR_TASK", reason, rule_ref="SOD/ABAC")
    if task.kind in _task_guards:
        _task_guards[task.kind](session, task, decision)
    task.status = "COMPLETED"
    task.decision = decision
    task.comment = comment
    task.completed_at = clock.now()
    task.completed_by = principal.user_id
    if evidence:
        task.evidence = {**(task.evidence or {}), **evidence}
    _cancel_timers(session, "TASK_SLA", task.id)
    audit.record(session, task.object_type, task.object_id, f"APPROVAL_{decision}", object_ref=task.object_ref,
                 after={"task": str(task.id), "role": task.candidate_role, "decision": decision},
                 reason=comment, rule_set_version=task.rule_set_version)
    _advance(session, task)
    return task


def _advance(session: Session, task: Task) -> None:
    instance = session.get(ProcessInstance, task.instance_id) if task.instance_id else None
    meta = (instance.variables or {}).get(task.group_key, {}) if instance else {}
    handler = _task_handlers.get(task.kind)
    siblings = session.execute(select(Task).where(Task.group_key == task.group_key)).scalars().all()

    if task.decision in ("REJECT", "RETURN"):
        for other in siblings:
            if other.status == "OPEN":
                other.status = "CANCELLED"
                _cancel_timers(session, "TASK_SLA", other.id)
        outcome = "REJECTED" if task.decision == "REJECT" else "RETURNED"
        if instance and meta.get("step"):
            step(session, instance, meta["step"], outcome=f"{outcome} by {task.candidate_role}")
        if handler:
            handler(session, task, outcome)
        return

    chain = meta.get("chain", [task.candidate_role])
    if meta.get("mode") == "PARALLEL":
        if all(t.status == "COMPLETED" and t.decision == "APPROVE" for t in siblings):
            if instance and meta.get("step"):
                step(session, instance, meta["step"], outcome="all approved")
            if handler:
                handler(session, task, "APPROVED")
        return

    if task.sequence < len(chain):
        approvers = [t.completed_by for t in siblings if t.completed_by]
        _open_task(session, instance, task.kind, task.object_type, task.object_id, task.object_ref,
                   chain[task.sequence], (meta.get("scopes") or {}).get(chain[task.sequence], {}),
                   list(task.excluded_user_ids or []) + approvers, task.group_key, task.sequence + 1,
                   meta.get("sla", 2), task.rule_set_version, task.evidence or {})
        return
    if instance and meta.get("step"):
        step(session, instance, meta["step"], outcome=f"approved by {' → '.join(chain)}")
    if handler:
        handler(session, task, "APPROVED")


# ---------------------------------------------------------------- timers
def create_timer(session: Session, kind: str, object_type: str, object_id: uuid.UUID, due_at: datetime,
                 payload: Optional[dict] = None) -> Timer:
    timer = Timer(tenant_id=current_tenant(session), kind=kind, object_type=object_type, object_id=object_id,
                  due_at=due_at, payload=payload or {}, created_by=current_user(session))
    session.add(timer)
    return timer


def _cancel_timers(session: Session, kind: str, object_id: uuid.UUID) -> None:
    for timer in session.execute(select(Timer).where(Timer.kind == kind, Timer.object_id == object_id,
                                                     Timer.fired_at.is_(None))).scalars():
        timer.fired_at = clock.now()
        timer.payload = {**(timer.payload or {}), "cancelled": True}


@on_timer("TASK_SLA")
def _task_sla(session: Session, timer: Timer) -> None:
    task = session.get(Task, timer.object_id)
    if task is None or task.status != "OPEN":
        return
    task.escalation_level += 1
    task.due_at = clock.add_business_days(clock.now(), 1)
    create_timer(session, "TASK_SLA", "TASK", task.id, task.due_at, timer.payload)
    audit.record(session, task.object_type, task.object_id, "TASK_ESCALATED", object_ref=task.object_ref,
                 after={"task": str(task.id), "level": task.escalation_level, "role": task.candidate_role},
                 reason="SLA breached: reminder sent and escalated to manager")


def run_due_timers(tenant_id: uuid.UUID, principal) -> int:
    fired = 0
    with tenant_tx(tenant_id, principal.user_id, principal) as session:
        due = session.execute(
            select(Timer).where(Timer.fired_at.is_(None), Timer.due_at <= clock.now()).order_by(Timer.due_at)
            .with_for_update(skip_locked=True)
        ).scalars().all()
        for timer in due:
            handler = _timer_handlers.get(timer.kind)
            timer.fired_at = clock.now()
            if handler:
                with session.begin_nested():
                    handler(session, timer)
            fired += 1
    return fired


def tenants() -> list[uuid.UUID]:
    with system_tx() as s:
        return list(s.execute(select(Tenant.id)).scalars())
