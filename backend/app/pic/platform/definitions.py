"""Editable, versioned workflow definitions (item 49).

``process_definition`` rows are versions of a flow (key, version). Version 1 of the nine flows is shared by all tenants (loaded
from platform/process_defs.py by migration 0013 / the seed); a tenant edits a DRAFT copy, validates it and publishes it, which
retires the tenant's previous version and makes the new one the version new process instances start on. Running instances keep
the version they started on (process_instance.process_version). Row-level security shows a tenant the shared rows and its own.

``validate`` is the gate to publish: structure, every step reachable and able to reach an end, gateways with both outcomes,
referenced roles known, task kinds that have a handler in code, and the steps the services drive by id kept.
"""
import re
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.pic.db import system_tx
from app.pic.models import ProcessDefinition
from app.pic.platform import audit, clock, outbox, workflow
from app.pic.platform.errors import Problem, not_found

STEP_TYPES = {"event", "user", "system", "gateway"}
STEP_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,29}$")
MAX_STEPS = 120
EDITABLE_FIELDS = ("steps", "flows", "lanes", "branches")


def _audit_id(key: str, version: int) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"pic:process-definition:{key}:{version}")


def ref(d: ProcessDefinition) -> str:
    return f"{d.key}@v{d.version}"


# ---------------------------------------------------------------- reading
def versions(session: Session, key: str) -> list[ProcessDefinition]:
    return list(session.execute(select(ProcessDefinition).where(ProcessDefinition.key == key)
                                .order_by(ProcessDefinition.version)).scalars())


def get(session: Session, key: str, version: int) -> ProcessDefinition:
    d = session.get(ProcessDefinition, (key, version))
    if d is None:
        raise not_found("Process definition", f"{key} v{version}")
    return d


def effective(session: Session) -> list[ProcessDefinition]:
    """For each flow the definition a new instance starts on: the tenant's own ACTIVE version, else the shared one."""
    out: dict = {}
    for d in session.execute(select(ProcessDefinition).where(ProcessDefinition.status == "ACTIVE")).scalars():
        rank = (d.tenant_id is not None, d.version)
        if d.key not in out or rank > (out[d.key].tenant_id is not None, out[d.key].version):
            out[d.key] = d
    return sorted(out.values(), key=lambda d: (d.flow_id, d.key))


def view(d: ProcessDefinition) -> dict:
    body = d.definition or {}
    return {"key": d.key, "flow": d.flow_id, "version": d.version, "name": d.name, "status": d.status,
            "scope": "TENANT" if d.tenant_id else "SHARED", "baseVersion": d.base_version, "note": d.note, "revision": d.revision,
            "publishedAt": d.published_at.isoformat() if d.published_at else None,
            "createdAt": d.created_at.isoformat() if d.created_at else None,
            "editable": d.tenant_id is not None and d.status == "DRAFT", "steps": body.get("steps", []),
            "flows": body.get("flows", []), "lanes": body.get("lanes", []), "branches": body.get("branches")}


# ---------------------------------------------------------------- validation
def _baseline_steps(session: Session, key: str) -> dict:
    """Steps the services drive by id (the shared version 1): a new version may not remove or retype them."""
    base = session.get(ProcessDefinition, (key, 1))
    return {s["id"]: s for s in (base.definition or {}).get("steps", [])} if base is not None and base.tenant_id is None else {}


def validate(session: Session, key: str, definition: Any) -> dict:
    """{"valid": bool, "errors": [{code, message, step?}], "warnings": [...]}. Pure with respect to the database (reads only)."""
    from app.pic.platform.auth import ROLE_SCOPES
    from app.pic.platform import roles as roles_mod
    import app.pic.services  # noqa: F401  (registers the task handlers the check looks for)
    errors: list = []
    warnings: list = []

    def err(code: str, message: str, step: Optional[str] = None) -> None:
        errors.append({"code": code, "message": message, **({"step": step} if step else {})})

    if not isinstance(definition, dict):
        return {"valid": False, "errors": [{"code": "DEFINITION_SHAPE", "message": "The definition must be a JSON object"}], "warnings": []}
    steps, flows = definition.get("steps"), definition.get("flows")
    if not isinstance(steps, list) or not steps:
        err("STEPS_REQUIRED", "The definition needs a non-empty list of steps")
        return {"valid": False, "errors": errors, "warnings": warnings}
    if not isinstance(flows, list):
        err("FLOWS_REQUIRED", "The definition needs a list of flows (sequence flows between steps)")
        return {"valid": False, "errors": errors, "warnings": warnings}
    if len(steps) > MAX_STEPS:
        err("TOO_MANY_STEPS", f"At most {MAX_STEPS} steps")
    ids: list = []
    kinds = workflow.registered_task_kinds()
    for s in steps:
        if not isinstance(s, dict) or not isinstance(s.get("id"), str):
            err("STEP_SHAPE", "Every step is an object with an id")
            continue
        sid = s["id"]
        if sid in ids:
            err("STEP_DUPLICATE", f"Step id {sid} is used twice", sid)
        ids.append(sid)
        if not STEP_ID.match(sid):
            err("STEP_ID_INVALID", f"Step id {sid!r}: start with a letter; letters, digits, '.', '_' and '-' only (30 characters)", sid)
        if s.get("type") not in STEP_TYPES:
            err("STEP_TYPE", f"Step {sid}: type must be one of {', '.join(sorted(STEP_TYPES))}", sid)
        if not str(s.get("name") or "").strip() or len(str(s.get("name"))) > 200:
            err("STEP_NAME", f"Step {sid}: a name of 1-200 characters is required", sid)
        if not str(s.get("lane") or "").strip():
            err("STEP_LANE", f"Step {sid}: a lane is required", sid)
        if s.get("taskKind") is not None:
            if s.get("type") != "user":
                err("TASK_KIND_ON_NON_USER_STEP", f"Step {sid}: only user steps open approval tasks", sid)
            elif s["taskKind"] not in kinds:
                err("TASK_KIND_UNKNOWN", f"Step {sid}: no handler for task kind {s['taskKind']!r} in code "
                                         f"(available: {', '.join(sorted(kinds))})", sid)
        for role in s.get("roles") or []:
            if role not in ROLE_SCOPES and role not in roles_mod.known_roles(session):
                err("ROLE_UNKNOWN", f"Step {sid}: role {role!r} does not exist", sid)
        sla = s.get("slaBusinessDays")
        if sla is not None and (not isinstance(sla, int) or isinstance(sla, bool) or not 1 <= sla <= 60):
            err("SLA_INVALID", f"Step {sid}: slaBusinessDays must be a whole number of 1-60", sid)
    known = set(ids)
    by_id = {s["id"]: s for s in steps if isinstance(s, dict) and isinstance(s.get("id"), str)}
    out_edges: dict = {i: [] for i in known}
    in_edges: dict = {i: [] for i in known}
    seen_flows = set()
    for f in flows:
        if not isinstance(f, dict) or f.get("from") not in known or f.get("to") not in known:
            err("FLOW_ENDPOINT", f"Flow {f!r} must connect two existing steps")
            continue
        if f["from"] == f["to"]:
            err("FLOW_SELF_LOOP", f"Step {f['from']} flows into itself", f["from"])
            continue
        edge = (f["from"], f["to"], f.get("label"))
        if edge in seen_flows:
            err("FLOW_DUPLICATE", f"Flow {f['from']} -> {f['to']} is listed twice", f["from"])
        seen_flows.add(edge)
        out_edges[f["from"]].append(f)
        in_edges[f["to"]].append(f)
    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings}
    starts = [i for i in ids if not in_edges[i]]
    if len(starts) != 1 or by_id[starts[0]].get("type") != "event":
        err("START_EVENT", f"Exactly one start event (an event step with no incoming flow) is required; found {starts or 'none'}")
    ends = [i for i in ids if not out_edges[i]]
    if not ends:
        err("END_EVENT", "At least one end (a step with no outgoing flow) is required")
    for i in ends:
        if by_id[i].get("type") != "event":
            err("DEAD_END", f"Step {i} has no outgoing flow but is not an end event", i)
    if starts:
        reach, frontier = {starts[0]}, [starts[0]]
        while frontier:
            for f in out_edges[frontier.pop()]:
                if f["to"] not in reach:
                    reach.add(f["to"])
                    frontier.append(f["to"])
        for i in ids:
            if i not in reach:
                err("STEP_UNREACHABLE", f"Step {i} cannot be reached from the start event", i)
    can_end, frontier = set(ends), list(ends)
    while frontier:
        for f in in_edges[frontier.pop()]:
            if f["from"] not in can_end:
                can_end.add(f["from"])
                frontier.append(f["from"])
    for i in ids:
        if i not in can_end:
            err("NO_PATH_TO_END", f"Step {i} cannot reach an end event", i)
    for i in ids:
        if by_id[i].get("type") == "gateway":
            labels = [str(f.get("label") or "").lower() for f in out_edges[i]]
            if len(out_edges[i]) < 2 or "yes" not in labels or "no" not in labels or len(set(labels)) != len(labels):
                err("GATEWAY_OUTCOMES", f"Gateway {i} needs exactly one outgoing flow labelled 'yes' and one labelled 'no' (and any others "
                                        f"with distinct labels)", i)
        elif len(out_edges[i]) > 1:
            warnings.append({"code": "PARALLEL_SPLIT", "message": f"Step {i} has {len(out_edges[i])} outgoing flows: they run in parallel", "step": i})
    lanes = definition.get("lanes")
    if lanes is not None:
        if not isinstance(lanes, list) or not all(isinstance(x, str) for x in lanes):
            err("LANES_SHAPE", "lanes must be a list of lane names")
        else:
            for i in ids:
                if by_id[i].get("lane") not in lanes:
                    warnings.append({"code": "LANE_NOT_LISTED", "message": f"Step {i} is in lane {by_id[i].get('lane')!r}, which is not in lanes", "step": i})
    for sid, base in _baseline_steps(session, key).items():
        step = by_id.get(sid)
        if step is None:
            err("STEP_REQUIRED_BY_CODE", f"Step {sid} ({base['name']}) is driven by the services and cannot be removed", sid)
        elif step.get("type") != base.get("type"):
            err("STEP_REQUIRED_BY_CODE", f"Step {sid} must stay a {base['type']} step (the services move the token through it)", sid)
        elif base.get("taskKind") and step.get("taskKind") != base["taskKind"]:
            err("STEP_REQUIRED_BY_CODE", f"Step {sid} must keep task kind {base['taskKind']}", sid)
    return {"valid": not errors, "errors": errors, "warnings": warnings}


# ---------------------------------------------------------------- editing
def _clean(definition: dict) -> dict:
    return {k: definition[k] for k in EDITABLE_FIELDS if k in definition}


def _next_version(key: str) -> int:
    """Across all tenants (a version number is unique per key): the owner connection sees every row."""
    with system_tx() as s:
        return int(s.execute(select(func.max(ProcessDefinition.version)).where(ProcessDefinition.key == key)).scalar() or 0) + 1


def create_draft(session: Session, principal, key: str, *, base_version: Optional[int] = None, definition: Optional[dict] = None,
                 note: Optional[str] = None) -> ProcessDefinition:
    known = versions(session, key)
    if not known:
        raise not_found("Process definition", key)
    if any(d.tenant_id == principal.tenant_id and d.status == "DRAFT" for d in known):
        raise Problem(409, "DRAFT_EXISTS", f"{key} already has a draft; edit or discard it first")
    base = get(session, key, base_version) if base_version else effective_of(known)
    body = _clean(definition) if definition is not None else _clean(base.definition)
    for attempt in range(3):
        version = _next_version(key)
        d = ProcessDefinition(key=key, version=version, flow_id=base.flow_id, name=base.name, definition=body, active=False,
                              status="DRAFT", tenant_id=principal.tenant_id, revision=1, note=note, base_version=base.version,
                              created_by=principal.user_id, created_at=clock.now())
        try:
            with session.begin_nested():
                session.add(d)
                session.flush()
            break
        except IntegrityError:
            session.expunge(d)
            if attempt == 2:
                raise Problem(409, "VERSION_CONFLICT", "Another administrator just created a version; retry")
    audit.record(session, "PROCESS_DEFINITION", _audit_id(key, d.version), "DRAFT_CREATED", object_ref=ref(d),
                 after={"baseVersion": base.version, "steps": len(body.get("steps", []))}, reason=note)
    return d


def effective_of(known: list) -> ProcessDefinition:
    actives = [d for d in known if d.status == "ACTIVE"]
    own = [d for d in actives if d.tenant_id is not None]
    return (own or actives or known)[-1]


def _editable(d: ProcessDefinition, principal) -> None:
    if d.tenant_id != principal.tenant_id:
        raise Problem(403, "SHARED_DEFINITION", "The shared baseline version cannot be edited; create a draft from it", rule_ref="ADM-WF")
    if d.status != "DRAFT":
        raise Problem(409, "ILLEGAL_TRANSITION", f"{ref(d)} is {d.status}; only a draft can be edited or discarded")


def update_draft(session: Session, principal, d: ProcessDefinition, *, definition: Optional[dict], note: Optional[str],
                 if_match: Optional[str]) -> ProcessDefinition:
    _editable(d, principal)
    if if_match is not None and if_match.strip().strip('"').removeprefix("W/").strip('"') not in (str(d.revision), "*"):
        raise Problem(412, "STALE_WRITE", f"The draft is at revision {d.revision}; you sent {if_match}. Reload it and retry.")
    if definition is not None:
        d.definition = _clean(definition)
    if note is not None:
        d.note = note
    d.revision += 1
    audit.record(session, "PROCESS_DEFINITION", _audit_id(d.key, d.version), "DRAFT_UPDATED", object_ref=ref(d),
                 after={"revision": d.revision, "steps": len((d.definition or {}).get("steps", []))})
    return d


def discard(session: Session, principal, d: ProcessDefinition) -> None:
    _editable(d, principal)
    audit.record(session, "PROCESS_DEFINITION", _audit_id(d.key, d.version), "DRAFT_DISCARDED", object_ref=ref(d))
    session.delete(d)


def publish(session: Session, principal, d: ProcessDefinition, reason: Optional[str] = None) -> ProcessDefinition:
    """DRAFT -> ACTIVE after validation; the tenant's previously active version of the flow becomes RETIRED (its running
    instances finish on it). New instances start on this version."""
    _editable(d, principal)
    result = validate(session, d.key, d.definition)
    if not result["valid"]:
        raise Problem(422, "DEFINITION_INVALID", f"{ref(d)} has {len(result['errors'])} validation error(s); fix them before publishing",
                      rule_ref="ADM-WF", errors=result["errors"], warnings=result["warnings"])
    for other in versions(session, d.key):
        if other.tenant_id == principal.tenant_id and other.status == "ACTIVE":
            other.status, other.active = "RETIRED", False
    d.status, d.active, d.published_at = "ACTIVE", True, clock.now()
    d.revision += 1
    audit.record(session, "PROCESS_DEFINITION", _audit_id(d.key, d.version), "PUBLISHED", object_ref=ref(d),
                 after={"version": d.version, "baseVersion": d.base_version, "warnings": len(result["warnings"])}, reason=reason)
    outbox.emit(session, "process.definition.published", "PROCESS_DEFINITION", _audit_id(d.key, d.version), ref(d),
                {"key": d.key, "version": d.version, "baseVersion": d.base_version})
    return d


def retire(session: Session, principal, d: ProcessDefinition, reason: str) -> ProcessDefinition:
    """Withdraw the tenant's own published version: new instances fall back to the previous tenant version or the shared one."""
    if d.tenant_id != principal.tenant_id:
        raise Problem(403, "SHARED_DEFINITION", "The shared baseline version cannot be retired by a tenant", rule_ref="ADM-WF")
    if d.status != "ACTIVE":
        raise Problem(409, "ILLEGAL_TRANSITION", f"{ref(d)} is {d.status}; only an active version can be retired")
    d.status, d.active = "RETIRED", False
    audit.record(session, "PROCESS_DEFINITION", _audit_id(d.key, d.version), "RETIRED", object_ref=ref(d), reason=reason)
    return d


# ---------------------------------------------------------------- diff
def diff(a: ProcessDefinition, b: ProcessDefinition) -> dict:
    def index(d):
        body = d.definition or {}
        return {s["id"]: s for s in body.get("steps", [])}, {(f["from"], f["to"], f.get("label")) for f in body.get("flows", [])}
    steps_a, flows_a = index(a)
    steps_b, flows_b = index(b)
    changed = []
    for sid in sorted(set(steps_a) & set(steps_b)):
        fields = sorted(k for k in set(steps_a[sid]) | set(steps_b[sid]) if steps_a[sid].get(k) != steps_b[sid].get(k))
        if fields:
            changed.append({"id": sid, "fields": [{"field": k, "from": steps_a[sid].get(k), "to": steps_b[sid].get(k)} for k in fields]})
    flow = lambda t: {"from": t[0], "to": t[1], **({"label": t[2]} if t[2] else {})}  # noqa: E731
    out = {"from": a.version, "to": b.version, "key": a.key,
           "stepsAdded": [steps_b[i] for i in sorted(set(steps_b) - set(steps_a))],
           "stepsRemoved": [steps_a[i] for i in sorted(set(steps_a) - set(steps_b))], "stepsChanged": changed,
           "flowsAdded": [flow(t) for t in sorted(flows_b - flows_a, key=str)],
           "flowsRemoved": [flow(t) for t in sorted(flows_a - flows_b, key=str)]}
    out["identical"] = not any(out[k] for k in ("stepsAdded", "stepsRemoved", "stepsChanged", "flowsAdded", "flowsRemoved"))
    return out
