"""F9 Material master governance (M03): request → duplicate check → domain stewards → ERP → link."""
import difflib
import re
import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import Material, MaterialRequest, PrLine, Requisition, Task
from app.pic.platform import agents, audit, integration, outbox, rules, sod, workflow
from app.pic.platform.core import link, next_number
from app.pic.platform.errors import Problem, illegal_transition, rule_violation
from app.pic.services.common import principal

PROCESS = "pic.material-request"
IN_FLIGHT = ("DUPLICATE_CHECK", "IN_STEWARDSHIP", "APPROVED")  # open requests the duplicate check also scores


def _candidate_ref(candidate: dict) -> str:
    return candidate.get("material") or f"request {candidate.get('materialRequest')}"


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t}


def duplicate_score(weights: dict, request: MaterialRequest, material: Material) -> tuple[Decimal, dict]:
    a, b = request.description.lower(), material.description.lower()
    seq = difflib.SequenceMatcher(None, a, b).ratio()
    ta, tb = _tokens(a), _tokens(b)
    jaccard = len(ta & tb) / len(ta | tb) if ta | tb else 0
    description = max(seq, jaccard)
    mpn = 1.0 if request.mpn and material.mpn and request.mpn.strip().upper() == material.mpn.strip().upper() else 0.0
    keys = set(request.attributes or {}) | set(material.attributes or {})
    same = [k for k in keys if (request.attributes or {}).get(k) == (material.attributes or {}).get(k)]
    attributes = len(same) / len(keys) if keys else 0.0
    classification = 1.0 if (request.material_group == material.material_group and request.category == material.category) else 0.0
    parts = {"description": description, "mpn": mpn, "attributes": attributes, "classification": classification}
    score = sum(weights[k] * v for k, v in parts.items())
    return Decimal(str(round(score, 3))), {k: round(v, 3) for k, v in parts.items()}


def create_request(session: Session, *, description: str, type: str, material_group: str, category: str, base_uom: str,
                   valuation_class: Optional[str] = None, hsn_code: Optional[str] = None, mpn: Optional[str] = None,
                   attributes: Optional[dict] = None, source_pr: Optional[PrLine] = None) -> MaterialRequest:
    p = principal(session)
    request = MaterialRequest(
        tenant_id=current_tenant(session), number=next_number(session, "MATERIAL_REQUEST"), status="DRAFT",
        description=description, type=type, material_group=material_group, category=category, base_uom=base_uom,
        valuation_class=valuation_class, hsn_code=hsn_code, mpn=mpn, attributes=attributes or {},
        requested_by=p.user_id, source_pr_id=source_pr.requisition_id if source_pr else None,
        source_pr_line=source_pr.line_no if source_pr else None, created_by=p.user_id,
    )
    session.add(request)
    session.flush()
    sod.record(session, "MATERIAL_REQUEST", {"material_request_id": request.id})
    instance = workflow.start(session, PROCESS, "MATERIAL_REQUEST", request.id, request.number)
    workflow.step(session, instance, "F9-02", outcome="submitted" + (f" from PR line {source_pr.line_no}" if source_pr else ""))
    if source_pr is not None:
        source_pr.mdm_request_id = request.id
        pr = session.get(Requisition, source_pr.requisition_id)
        link(session, "REQUISITION", pr.id, pr.number, "MATERIAL_REQUEST", request.id, request.number, "promoted_to",
             from_line=source_pr.line_no)
    audit.record(session, "MATERIAL_REQUEST", request.id, "CREATED", object_ref=request.number,
                 after={"description": description, "group": material_group})
    _check_duplicates(session, request, instance)
    return request


PROMOTABLE_PR = ("DRAFT", "RETURNED", "SUBMITTED", "IN_APPROVAL", "APPROVED", "PARTIALLY_ORDERED", "ORDERED")


def promote_line(session: Session, pr: Requisition, line: PrLine, **fields) -> MaterialRequest:
    """F9 from a requisition line (P04): the requester promotes a free-text or free-service line (no material, catalogue
    item or contract line) of a live requisition, once per line."""
    if principal(session).user_id != pr.requester_id:
        raise Problem(403, "FORBIDDEN", "Only the requester can promote a line of this requisition to a material request", rule_ref="P04")
    if pr.status not in PROMOTABLE_PR:
        raise illegal_transition("Requisition", pr.number, pr.status, "promote a line to a material request")
    if line.material_id or line.catalogue_item_id or line.contract_line_id:
        raise rule_violation("Only free-text and service lines without a material, catalogue item or contract are promoted "
                             "to material requests", "P04")
    if line.mdm_request_id is not None:
        existing = session.get(MaterialRequest, line.mdm_request_id)
        raise Problem(409, "ALREADY_PROMOTED", f"Line {line.line_no} already has material request {existing.number if existing else ''}".strip(),
                      rule_ref="P04")
    return create_request(session, **fields, source_pr=line)


def _check_duplicates(session: Session, request: MaterialRequest, instance) -> None:
    rule = rules.resolve(session, "MDM-DUP", category=request.category)
    request.rule_set_version = rule.ref
    request.status = "DUPLICATE_CHECK"
    candidates = []
    for material in session.execute(select(Material).where(Material.status == "ACTIVE")).scalars():
        score, parts = duplicate_score(rule.body["weights"], request, material)
        if score >= Decimal(str(rule.body["warnAt"])) - Decimal("0.25"):
            candidates.append({"kind": "MATERIAL", "material": material.number, "id": str(material.id), "score": float(score), "parts": parts})
    # Requests still in flight (no material yet) are scored too, so two people asking for the same new item in parallel
    # are caught; once such a request's material is live the requester can merge into it.
    for other in session.execute(select(MaterialRequest).where(
            MaterialRequest.status.in_(IN_FLIGHT), MaterialRequest.material_id.is_(None), MaterialRequest.id != request.id)).scalars():
        score, parts = duplicate_score(rule.body["weights"], request, other)
        if score >= Decimal(str(rule.body["warnAt"])) - Decimal("0.25"):
            candidates.append({"kind": "MATERIAL_REQUEST", "material": None, "materialRequest": other.number, "id": str(other.id),
                               "status": other.status, "score": float(score), "parts": parts})
    candidates.sort(key=lambda c: c["score"], reverse=True)
    top = Decimal(str(candidates[0]["score"])) if candidates else Decimal("0")
    request.duplicate_score = top
    request.duplicate_candidates = candidates[:5]
    ai_ref = agents.log_run(session, "MATERIAL_DEDUP", object_type="MATERIAL_REQUEST", object_id=request.id,
                            object_ref=request.number, inputs={"description": request.description, "mpn": request.mpn},
                            evidence=[_candidate_ref(c) for c in candidates[:5]], output={"topScore": float(top)},
                            confidence=0.9, action_taken="DRAFTED")
    workflow.step(session, instance, "F9-03", outcome=f"top duplicate score {top}")
    block_at = Decimal(str(rule.body["blockAt"]))
    if top >= block_at:
        request.status = "DUPLICATE_BLOCKED"
        workflow.wait(session, instance, "F9-04", outcome=f"score {top} ≥ {block_at}: redirect to {_candidate_ref(candidates[0])} or steward override")
        audit.record(session, "MATERIAL_REQUEST", request.id, "DUPLICATE_BLOCKED", object_ref=request.number,
                     after={"score": str(top), "candidate": _candidate_ref(candidates[0])}, rule_set_version=rule.ref, ai_ref=ai_ref)
        return
    warn = top >= Decimal(str(rule.body["warnAt"]))
    workflow.step(session, instance, "F9-04", outcome=f"score {top} < {block_at}" + (" (warning)" if warn else ""))
    _to_stewards(session, request, instance, rule)


def _to_stewards(session: Session, request: MaterialRequest, instance, rule) -> None:
    request.status = "IN_STEWARDSHIP"
    domains = rule.body["domains"]
    workflow.start_approval(
        session, instance, "MDM_STEWARD", object_type="MATERIAL_REQUEST", object_id=request.id, object_ref=request.number,
        chain=["MDM_STEWARD"] * len(domains), mode="PARALLEL", step_id="F9-05", initiator_id=request.requested_by,
        scopes={}, rule_set_version=rule.ref,
    )
    # Each parallel task is bound to one steward domain.
    tasks = session.execute(select(Task).where(Task.object_id == request.id, Task.kind == "MDM_STEWARD",
                                               Task.status == "OPEN").order_by(Task.sequence)).scalars().all()
    for task, domain in zip(tasks, domains):
        task.candidate_scope = {"steward_domain": domain}
        task.name = f"Approve {domain.lower()} data · {request.number}"


@workflow.guard_task("MDM_STEWARD")
def _steward_sod(session: Session, task: Task, decision: str) -> None:
    sod.guard(session, "MATERIAL_STEWARD_APPROVE", {"material_request_id": task.object_id})


def steward_override(session: Session, request: MaterialRequest, reason: str) -> MaterialRequest:
    if request.status != "DUPLICATE_BLOCKED":
        raise illegal_transition("Material request", request.number, request.status, "override")
    p = principal(session)
    if "MDM_STEWARD" not in p.roles:
        raise Problem(403, "FORBIDDEN", "Only a data steward can override a duplicate block", rule_ref="MDM-DUP")
    reason = (reason or "").strip()
    if not reason:
        raise rule_violation("A reason is required to override a duplicate block", "MDM-DUP")
    sod.guard(session, "MATERIAL_STEWARD_APPROVE", {"material_request_id": request.id})
    request.override_reason = reason
    rule = rules.resolve(session, "MDM-DUP", category=request.category)
    audit.record(session, "MATERIAL_REQUEST", request.id, "DUPLICATE_OVERRIDE", object_ref=request.number, reason=reason,
                 rule_set_version=rule.ref)
    instance = workflow.find(session, "MATERIAL_REQUEST", request.id, PROCESS)
    workflow.step(session, instance, "F9-04", outcome=f"steward override: {reason}")
    _to_stewards(session, request, instance, rule)
    return request


def merge_into_existing(session: Session, request: MaterialRequest, material: Material) -> MaterialRequest:
    """Redirect a request to an existing material: the requester or a data steward while DUPLICATE_BLOCKED, only a steward
    while IN_STEWARDSHIP, and only into an ACTIVE material listed as a duplicate candidate (or the live material of a
    candidate request that was in flight at the check)."""
    if request.status not in ("DUPLICATE_BLOCKED", "IN_STEWARDSHIP"):
        raise illegal_transition("Material request", request.number, request.status, "merge")
    p = principal(session)
    steward = "MDM_STEWARD" in p.roles
    if request.status == "IN_STEWARDSHIP" and not steward:
        raise Problem(403, "FORBIDDEN", "Only a data steward can merge a request that is in stewardship", rule_ref="MDM-DUP")
    if not steward and p.user_id != request.requested_by:
        raise Problem(403, "FORBIDDEN", "Only the requester or a data steward can merge this request", rule_ref="MDM-DUP")
    if material.status != "ACTIVE":
        raise rule_violation(f"{material.number} is {material.status}; merge only into an active material", "MDM-DUP")
    listed = {c.get("id") for c in request.duplicate_candidates or [] if c.get("kind", "MATERIAL") == "MATERIAL"}
    request_ids = [uuid.UUID(c["id"]) for c in request.duplicate_candidates or [] if c.get("kind") == "MATERIAL_REQUEST"]
    if request_ids:
        listed |= {str(r.material_id) for r in session.execute(select(MaterialRequest).where(
            MaterialRequest.id.in_(request_ids), MaterialRequest.material_id.is_not(None))).scalars()}
    if str(material.id) not in listed:
        raise rule_violation(f"{material.number} is not a duplicate candidate of {request.number}; merge only into a listed candidate",
                             "MDM-DUP")
    request.status = "MERGED"
    request.merged_into_material_id = material.id
    for task in session.execute(select(Task).where(Task.object_id == request.id, Task.status == "OPEN")).scalars():
        task.status = "CANCELLED"
    instance = workflow.find(session, "MATERIAL_REQUEST", request.id, PROCESS)
    if request.duplicate_score is not None and instance.current_step == "F9-04":
        workflow.step(session, instance, "F9-04", outcome=f"duplicate: requester redirected to {material.number}")
    _link_pr_line(session, request, material)
    workflow.end(session, instance, "F9-08", outcome=f"merged into existing material {material.number}")
    audit.record(session, "MATERIAL_REQUEST", request.id, "MERGED", object_ref=request.number, after={"material": material.number})
    return request


@workflow.on_task("MDM_STEWARD")
def _stewards_decided(session: Session, task: Task, outcome: str) -> None:
    request = session.get(MaterialRequest, task.object_id)
    instance = workflow.find(session, "MATERIAL_REQUEST", request.id, PROCESS)
    if outcome != "APPROVED":
        request.status = "REJECTED"
        audit.record(session, "MATERIAL_REQUEST", request.id, "REJECTED", object_ref=request.number, reason=task.comment,
                     before={"status": "IN_STEWARDSHIP"}, after={"status": "REJECTED", "domain": (task.candidate_scope or {}).get("steward_domain")},
                     rule_set_version=request.rule_set_version)
        workflow.end(session, instance, "F9-08", outcome=f"rejected by steward: {task.comment}", status="COMPLETED")
        return
    sod.record(session, "MATERIAL_STEWARD_APPROVE", {"material_request_id": request.id})
    request.status = "APPROVED"
    audit.record(session, "MATERIAL_REQUEST", request.id, "APPROVED", object_ref=request.number,
                 before={"status": "IN_STEWARDSHIP"}, after={"status": "APPROVED"}, rule_set_version=request.rule_set_version)
    material = Material(
        tenant_id=current_tenant(session), number=next_number(session, "MATERIAL"), description=request.description,
        type=request.type, material_group=request.material_group, category=request.category, base_uom=request.base_uom,
        valuation_class=request.valuation_class, hsn_code=request.hsn_code, mpn=request.mpn, attributes=request.attributes,
        status="ACTIVE", erp_synced=False, created_by=principal(session).user_id,
    )
    session.add(material)
    session.flush()
    request.material_id = material.id
    audit.record(session, "MATERIAL", material.id, "CREATED", object_ref=material.number,
                 after={"description": material.description, "group": material.material_group, "category": material.category,
                        "uom": material.base_uom, "fromRequest": request.number}, rule_set_version=request.rule_set_version)
    link(session, "MATERIAL_REQUEST", request.id, request.number, "MATERIAL", material.id, material.number, "created_material")
    outbox.emit(session, "material_request.approved", "MATERIAL_REQUEST", request.id, request.number,
                {"material": material.number, "materialId": str(material.id)})
    message = integration.enqueue(
        session, target_system=integration.target_system(session), message_type="MATERIAL_MASTER", idempotency_key=f"MAT|{material.number}",
        object_type="MATERIAL_REQUEST", object_id=request.id, object_ref=request.number,
        payload={"material": material.number, "description": material.description, "group": material.material_group,
                 "uom": material.base_uom, "valuationClass": material.valuation_class},
    )
    integration.process(session, message)


@integration.on_posted("MATERIAL_MASTER")
def _material_synced(session: Session, message) -> None:
    request = session.get(MaterialRequest, message.object_id)
    material = session.get(Material, request.material_id)
    material.erp_synced = True
    request.status = "SYNCED_TO_ERP"
    audit.record(session, "MATERIAL_REQUEST", request.id, "SYNCED_TO_ERP", object_ref=request.number,
                 before={"status": "APPROVED"}, after={"status": "SYNCED_TO_ERP", "material": material.number, "erpDocument": message.erp_doc_no})
    instance = workflow.find(session, "MATERIAL_REQUEST", request.id, PROCESS)
    workflow.step(session, instance, "F9-06", outcome=f"ERP material {message.erp_doc_no}")
    _link_pr_line(session, request, material)
    workflow.end(session, instance, "F9-08", outcome=f"golden record {material.number} live")


def _link_pr_line(session: Session, request: MaterialRequest, material: Material) -> None:
    instance = workflow.find(session, "MATERIAL_REQUEST", request.id, PROCESS)
    if request.source_pr_id is None:
        if instance:
            workflow.step(session, instance, "F9-07", outcome="no PR line to link")
        return
    line = session.execute(select(PrLine).where(PrLine.requisition_id == request.source_pr_id,
                                                PrLine.line_no == request.source_pr_line)).scalar_one()
    # P04: the PR line stays free text; the material is linked for future reuse.
    line.linked_material_id = material.id
    if instance:
        workflow.step(session, instance, "F9-07", outcome=f"linked to PR line {line.line_no} (line stays free text)")
