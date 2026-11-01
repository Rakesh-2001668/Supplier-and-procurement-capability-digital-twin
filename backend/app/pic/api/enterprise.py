"""Platform enterprise API (wave 1): workflow definitions and designer (item 49), ERP field mappings (item 50), SoD exception
path (item 46) and password change. Idempotency-Key is honoured on every write by the HTTP layer (platform/idempotency.py)."""
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.pic.api.deps import uow
from app.pic.config import get_settings
from app.pic.models import AppUser, IntegrationFieldMapping, IntegrationMessage, SodRule
from app.pic.platform import audit, bpmn, clock, connectors, definitions, field_mapping, passwords, sod
from app.pic.platform.auth import READ, TASKS, Principal, current_principal, hash_password, require, verify_password
from app.pic.platform.core import check_if_match
from app.pic.platform.errors import Problem, not_found
from app.pic.platform.serialize import row

router = APIRouter(prefix="/v1")


# ================================================================ workflow definitions (item 49)
class DraftIn(BaseModel):
    baseVersion: Optional[int] = Field(default=None, ge=1)  # noqa: N815
    definition: Optional[dict] = None
    note: Optional[str] = Field(default=None, max_length=500)


class DraftUpdate(BaseModel):
    definition: Optional[dict] = None
    note: Optional[str] = Field(default=None, max_length=500)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ValidateIn(BaseModel):
    key: str
    definition: dict


class BpmnIn(BaseModel):
    xml: str = Field(min_length=10)


@router.get("/process-definitions/{key}/versions", tags=["Workflow designer"])
def definition_versions(key: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        found = definitions.versions(s, key)
        if not found:
            raise not_found("Process definition", key)
        return [{**definitions.view(d), "steps": len(d.definition.get("steps", [])), "flows": len(d.definition.get("flows", []))}
                for d in found]


@router.get("/process-definitions/{key}/versions/{version}", tags=["Workflow designer"])
def definition_version(key: str, version: int, response: Response, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        d = definitions.get(s, key, version)
        response.headers["ETag"] = f'"{d.revision}"'
        return definitions.view(d)


@router.post("/process-definitions/{key}/drafts", status_code=201, tags=["Workflow designer"])
def create_draft(key: str, body: DraftIn, p: Principal = Depends(require("admin:workflow"))):
    """Start a draft from the active (or a named) version: copy it, edit the JSON, validate, publish."""
    with uow(p) as s:
        return definitions.view(definitions.create_draft(s, p, key, base_version=body.baseVersion, definition=body.definition, note=body.note))


@router.put("/process-definitions/{key}/versions/{version}", tags=["Workflow designer"])
def update_draft(key: str, version: int, body: DraftUpdate, p: Principal = Depends(require("admin:workflow")),
                 if_match: Optional[str] = Header(default=None, alias="If-Match")):
    """Edit a draft. If-Match carries the draft's revision (ETag of its GET); required when PIC_REQUIRE_IF_MATCH is on."""
    if if_match is None and get_settings().if_match_required:
        raise Problem(428, "PRECONDITION_REQUIRED", "Send If-Match with the revision you loaded (ETag of the draft's GET)")
    with uow(p) as s:
        return definitions.view(definitions.update_draft(s, p, definitions.get(s, key, version), definition=body.definition,
                                                         note=body.note, if_match=if_match))


@router.delete("/process-definitions/{key}/versions/{version}", tags=["Workflow designer"])
def discard_draft(key: str, version: int, p: Principal = Depends(require("admin:workflow"))):
    with uow(p) as s:
        definitions.discard(s, p, definitions.get(s, key, version))
        return {"discarded": f"{key}@v{version}"}


@router.post("/process-definitions/{key}/versions/{version}/validate", tags=["Workflow designer"])
def validate_version(key: str, version: int, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return definitions.validate(s, key, definitions.get(s, key, version).definition)


@router.post("/process-definitions/validate", tags=["Workflow designer"])
def validate_body(body: ValidateIn, p: Principal = Depends(require(READ))):
    """Validate a definition JSON without saving it (the designer's live check)."""
    with uow(p) as s:
        return definitions.validate(s, body.key, body.definition)


@router.post("/process-definitions/{key}/versions/{version}/publish", tags=["Workflow designer"])
def publish_version(key: str, version: int, body: Optional[ReasonIn] = None, p: Principal = Depends(require("admin:workflow"))):
    """Validate and publish: this version becomes the one new process instances start on; running instances finish on theirs."""
    with uow(p) as s:
        return definitions.view(definitions.publish(s, p, definitions.get(s, key, version), body.reason if body else None))


@router.post("/process-definitions/{key}/versions/{version}/retire", tags=["Workflow designer"])
def retire_version(key: str, version: int, body: ReasonIn, p: Principal = Depends(require("admin:workflow"))):
    with uow(p) as s:
        return definitions.view(definitions.retire(s, p, definitions.get(s, key, version), body.reason))


@router.get("/process-definitions/{key}/diff", tags=["Workflow designer"])
def definition_diff(key: str, from_: int = Query(alias="from", ge=1), to: int = Query(ge=1), p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return definitions.diff(definitions.get(s, key, from_), definitions.get(s, key, to))


@router.get("/process-definitions/{key}/versions/{version}/bpmn", tags=["Workflow designer"])
def definition_bpmn(key: str, version: int, p: Principal = Depends(require(READ))):
    """The version as BPMN 2.0 XML with diagram layout (bpmn-js viewer)."""
    with uow(p) as s:
        d = definitions.get(s, key, version)
        return {"key": d.key, "version": d.version, "status": d.status, "name": d.name, "xml": bpmn.to_xml(d.key, d.name, d.definition)}


@router.post("/process-definitions/bpmn/parse", tags=["Workflow designer"])
def parse_bpmn(body: BpmnIn, p: Principal = Depends(require(READ))):
    """BPMN XML -> definition JSON (import into a draft with PUT .../versions/{version})."""
    return {"definition": bpmn.from_xml(body.xml)}


# ================================================================ ERP field mappings (item 50)
class MappingIn(BaseModel):
    targetSystem: str = Field(min_length=2, max_length=30)  # noqa: N815
    messageType: str = Field(min_length=2, max_length=40)  # noqa: N815
    rules: list[dict] = Field(default_factory=list, max_length=field_mapping.MAX_RULES)
    note: Optional[str] = Field(default=None, max_length=500)


class MappingUpdate(BaseModel):
    rules: list[dict] = Field(max_length=field_mapping.MAX_RULES)
    note: Optional[str] = Field(default=None, max_length=500)


class PreviewIn(BaseModel):
    rules: list[dict] = Field(max_length=field_mapping.MAX_RULES)
    samplePayload: Optional[dict] = None  # noqa: N815
    targetSystem: Optional[str] = None  # noqa: N815
    messageType: Optional[str] = None  # noqa: N815


def _mapping_view(m: IntegrationFieldMapping) -> dict:
    return {"id": str(m.id), "targetSystem": m.target_system, "messageType": m.message_type, "version": m.version, "status": m.status,
            "rules": m.rules, "note": m.note, "publishedAt": m.published_at.isoformat() if m.published_at else None,
            "rowVersion": m.row_version, "updatedAt": m.updated_at.isoformat() if m.updated_at else None}


def _mapping(s, mapping_id: uuid.UUID) -> IntegrationFieldMapping:
    m = s.get(IntegrationFieldMapping, mapping_id)
    if m is None:
        raise not_found("Field mapping", mapping_id)
    return m


def _check_target(target: str, message_type: str) -> None:
    if target.upper() not in connectors.REGISTRY:
        raise Problem(422, "UNKNOWN_TARGET_SYSTEM", f"{target} is not a known ERP target system")
    from app.pic.platform.integration import DOC_TYPES
    if message_type.upper() not in DOC_TYPES:
        raise Problem(422, "UNKNOWN_MESSAGE_TYPE", f"message type must be one of {', '.join(sorted(DOC_TYPES))}")


def sample_for(s, target: str, message_type: str) -> Optional[dict]:
    return s.execute(select(IntegrationMessage.payload).where(
        IntegrationMessage.target_system == target, IntegrationMessage.message_type == message_type)
        .order_by(IntegrationMessage.created_at.desc()).limit(1)).scalar_one_or_none()


@router.get("/admin/field-mappings", tags=["Integration"])
def list_mappings(targetSystem: Optional[str] = None, messageType: Optional[str] = None,  # noqa: N803
                  p: Principal = Depends(require("admin:integration"))):
    with uow(p) as s:
        query = select(IntegrationFieldMapping).order_by(IntegrationFieldMapping.target_system, IntegrationFieldMapping.message_type,
                                                         IntegrationFieldMapping.version.desc())
        if targetSystem:
            query = query.where(IntegrationFieldMapping.target_system == targetSystem.upper())
        if messageType:
            query = query.where(IntegrationFieldMapping.message_type == messageType.upper())
        return [_mapping_view(m) for m in s.execute(query).scalars()]


@router.get("/admin/field-mappings/catalog", tags=["Integration"])
def mapping_catalog(p: Principal = Depends(require("admin:integration"))):
    """Target systems and message types a mapping can be written for, with a real payload of each type as the test sample."""
    from app.pic.platform.integration import DOC_TYPES
    with uow(p) as s:
        systems = list(connectors.REGISTRY)
        return {"targetSystems": systems, "messageTypes": [
            {"type": t, "samples": {sys_: sample_for(s, sys_, t) for sys_ in systems if sample_for(s, sys_, t) is not None}}
            for t in sorted(DOC_TYPES)],
            "ops": sorted(field_mapping.OPS), "formatKinds": sorted(field_mapping.KINDS)}


@router.post("/admin/field-mappings", status_code=201, tags=["Integration"])
def create_mapping(body: MappingIn, p: Principal = Depends(require("admin:integration"))):
    """A new DRAFT version for (target system, message type). Publish it to make it the one in use."""
    target, mtype = body.targetSystem.upper(), body.messageType.upper()
    _check_target(target, mtype)
    with uow(p) as s:
        problems = field_mapping.validate(body.rules)
        if problems:
            raise Problem(422, "MAPPING_INVALID", "; ".join(x["message"] for x in problems[:5]), problems=problems)
        version = int(s.execute(select(func.max(IntegrationFieldMapping.version)).where(
            IntegrationFieldMapping.target_system == target, IntegrationFieldMapping.message_type == mtype)).scalar() or 0) + 1
        m = IntegrationFieldMapping(tenant_id=p.tenant_id, target_system=target, message_type=mtype, version=version, status="DRAFT",
                                    rules=body.rules, note=body.note, created_by=p.user_id)
        s.add(m)
        s.flush()
        audit.record(s, "FIELD_MAPPING", m.id, "DRAFT_CREATED", object_ref=f"{target}/{mtype}@v{version}", after={"rules": len(body.rules)})
        return _mapping_view(m)


@router.put("/admin/field-mappings/{mapping_id}", tags=["Integration"])
def update_mapping(mapping_id: uuid.UUID, body: MappingUpdate, response: Response, p: Principal = Depends(require("admin:integration")),
                   if_match: Optional[str] = Header(default=None, alias="If-Match")):
    with uow(p) as s:
        m = _mapping(s, mapping_id)
        check_if_match(m, if_match)
        if m.status != "DRAFT":
            raise Problem(409, "ILLEGAL_TRANSITION", f"Version {m.version} is {m.status}; only a draft can be edited (create a new draft)")
        problems = field_mapping.validate(body.rules)
        if problems:
            raise Problem(422, "MAPPING_INVALID", "; ".join(x["message"] for x in problems[:5]), problems=problems)
        m.rules = body.rules
        if body.note is not None:
            m.note = body.note
        audit.record(s, "FIELD_MAPPING", m.id, "DRAFT_UPDATED", object_ref=f"{m.target_system}/{m.message_type}@v{m.version}",
                     after={"rules": len(body.rules)})
        return _mapping_view(m)


@router.delete("/admin/field-mappings/{mapping_id}", tags=["Integration"])
def delete_mapping(mapping_id: uuid.UUID, p: Principal = Depends(require("admin:integration"))):
    with uow(p) as s:
        m = _mapping(s, mapping_id)
        if m.status != "DRAFT":
            raise Problem(409, "ILLEGAL_TRANSITION", f"Version {m.version} is {m.status}; only a draft can be deleted")
        audit.record(s, "FIELD_MAPPING", m.id, "DRAFT_DISCARDED", object_ref=f"{m.target_system}/{m.message_type}@v{m.version}")
        s.delete(m)
        return {"discarded": str(mapping_id)}


@router.post("/admin/field-mappings/preview", tags=["Integration"])
def preview_mapping(body: PreviewIn, p: Principal = Depends(require("admin:integration"))):
    """Apply rules to a sample payload without saving anything (the admin test panel). Without a sample, the latest real payload of
    that target system and message type is used."""
    with uow(p) as s:
        sample = body.samplePayload
        if sample is None and body.targetSystem and body.messageType:
            sample = sample_for(s, body.targetSystem.upper(), body.messageType.upper())
        if sample is None:
            raise Problem(422, "SAMPLE_REQUIRED", "Send samplePayload (no message of this type exists yet to use as the sample)")
        return {**field_mapping.preview(body.rules, sample), "sample": sample}


@router.post("/admin/field-mappings/{mapping_id}/publish", tags=["Integration"])
def publish_mapping(mapping_id: uuid.UUID, p: Principal = Depends(require("admin:integration"))):
    with uow(p) as s:
        m = _mapping(s, mapping_id)
        if m.status != "DRAFT":
            raise Problem(409, "ILLEGAL_TRANSITION", f"Version {m.version} is {m.status}; only a draft can be published")
        problems = field_mapping.validate(m.rules)
        if problems:
            raise Problem(422, "MAPPING_INVALID", "; ".join(x["message"] for x in problems[:5]), problems=problems)
        current = field_mapping.active_for(s, m.target_system, m.message_type)
        if current is not None:
            current.status = "RETIRED"
            s.flush()  # one ACTIVE version per target and message type (partial unique index)
        m.status, m.published_at, m.published_by = "ACTIVE", clock.now(), p.user_id
        audit.record(s, "FIELD_MAPPING", m.id, "PUBLISHED", object_ref=f"{m.target_system}/{m.message_type}@v{m.version}",
                     before={"retired": current.version if current else None}, after={"rules": len(m.rules)})
        return _mapping_view(m)


@router.post("/admin/field-mappings/{mapping_id}/retire", tags=["Integration"])
def retire_mapping(mapping_id: uuid.UUID, body: ReasonIn, p: Principal = Depends(require("admin:integration"))):
    """Switch a mapping off: messages go out with the canonical payload again."""
    with uow(p) as s:
        m = _mapping(s, mapping_id)
        if m.status != "ACTIVE":
            raise Problem(409, "ILLEGAL_TRANSITION", f"Version {m.version} is {m.status}; only the active version can be retired")
        m.status = "RETIRED"
        audit.record(s, "FIELD_MAPPING", m.id, "RETIRED", object_ref=f"{m.target_system}/{m.message_type}@v{m.version}", reason=body.reason)
        return _mapping_view(m)


# ================================================================ SoD exception path (item 46)
class MitigationIn(BaseModel):
    ruleCode: str = Field(min_length=3, max_length=10)  # noqa: N815
    action: str = Field(min_length=3, max_length=40)
    refs: dict[str, Any]
    justification: str = Field(min_length=10, max_length=2000)
    validityHours: Optional[int] = Field(default=None, ge=1, le=720)  # noqa: N815


class SodRuleUpdate(BaseModel):
    mode: Optional[str] = Field(default=None, pattern="^(BLOCK|MITIGATE)$")
    active: Optional[bool] = None
    reason: str = Field(min_length=3, max_length=500)


@router.post("/sod/mitigations", status_code=201, tags=["Administration"])
def request_mitigation(body: MitigationIn, p: Principal = Depends(require(TASKS))):
    """Ask for an exception to a segregation-of-duties conflict you just hit (the 409 SOD_CONFLICT carries the body to send). The
    configured approver chain (rule SOD-MITIGATION) decides through their task inbox."""
    with uow(p) as s:
        return sod.mitigation_view(sod.request_mitigation(s, rule_code=body.ruleCode, action=body.action.upper(), refs=body.refs,
                                                          justification=body.justification, validity_hours=body.validityHours))


@router.get("/sod/mitigations", tags=["Administration"])
def my_mitigations(p: Principal = Depends(require(TASKS))):
    from app.pic.models import SodMitigation
    with uow(p) as s:
        return [sod.mitigation_view(m) for m in s.execute(select(SodMitigation).where(SodMitigation.requester_id == p.user_id)
                                                          .order_by(SodMitigation.created_at.desc()).limit(100)).scalars()]


@router.get("/admin/sod/mitigations", tags=["Administration"])
def mitigation_report(p: Principal = Depends(require("admin:audit"))):
    """Every SoD exception: requested, approved (with validity and compensating control), used, expired, revoked."""
    with uow(p) as s:
        return sod.report(s)


@router.post("/admin/sod/mitigations/{mitigation_id}/revoke", tags=["Administration"])
def revoke_mitigation(mitigation_id: uuid.UUID, body: ReasonIn, p: Principal = Depends(require("admin:rules"))):
    with uow(p) as s:
        return sod.mitigation_view(sod.revoke(s, mitigation_id, body.reason))


@router.put("/admin/sod/{code}", tags=["Administration"])
def update_sod_rule(code: str, body: SodRuleUpdate, p: Principal = Depends(require("admin:rules"))):
    """Switch a rule between BLOCK and MITIGATE (exception path) or deactivate it. Critical rules cannot be mitigated."""
    with uow(p) as s:
        rule = s.execute(select(SodRule).where(SodRule.code == code)).scalar_one_or_none()
        if rule is None:
            raise not_found("SoD rule", code)
        before = {"mode": rule.mode, "active": rule.active}
        if body.mode == "MITIGATE":
            terms = sod._terms(s, rule)
            if not terms["approverRoles"]:
                raise Problem(422, "NOT_MITIGABLE", f"{rule.code} is {rule.risk} risk: rule SOD-MITIGATION has no approver chain for it",
                              rule_ref="SOD-MITIGATION")
        if body.mode:
            rule.mode = body.mode
        if body.active is not None:
            rule.active = body.active
        audit.record(s, "SOD_RULE", rule.id, "RULE_CHANGED", object_ref=rule.code, before=before,
                     after={"mode": rule.mode, "active": rule.active}, reason=body.reason)
        return row(rule)


# ================================================================ password change
class PasswordChange(BaseModel):
    currentPassword: str = Field(min_length=1, max_length=128)  # noqa: N815
    newPassword: str = Field(min_length=1, max_length=128)  # noqa: N815


@router.post("/me/password", tags=["Identity"])
def change_password(body: PasswordChange, p: Principal = Depends(current_principal)):
    """Change your own password: current password, then a new one that passes the policy (length, complexity, not in the bundled
    breached/common-password list, not containing your name). Audited."""
    with uow(p) as s:
        user = s.get(AppUser, p.user_id)
        if user is None or not verify_password(body.currentPassword, user.password_hash):
            raise Problem(403, "INVALID_CREDENTIALS", "The current password is not correct")
        if body.newPassword == body.currentPassword:
            raise Problem(422, "PASSWORD_UNCHANGED", "Choose a password different from the current one")
        problems = passwords.check(body.newPassword, email=user.email, names=(user.full_name,))
        if problems:
            raise Problem(422, "PASSWORD_POLICY", "; ".join(problems), rule_ref="SEC-PWD", problems=problems)
        user.password_hash = hash_password(body.newPassword)
        audit.record(s, "USER", user.id, "PASSWORD_CHANGED", object_ref=user.email)
        return {"changed": True}
