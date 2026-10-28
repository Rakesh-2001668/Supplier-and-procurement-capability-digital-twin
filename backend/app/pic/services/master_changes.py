"""M03 MDM-04 supplier tax-ID, address and contact changes with dual approval.

A change is requested by the supplier manager or by the supplier's own portal user. The new values are field-encrypted
(per-tenant key) in ``after_enc``; only masked values are stored in clear, shown on screen and written to the audit trail
(Technical Document §14). Approval runs as parallel tasks for the roles in rule SUPPLIER-MASTER-CHANGE; the requester
can never approve (four-eyes + SoD guard), and the two approvals must come from two different people. On the last
approval the change is applied to the supplier master, TAX changes are re-screened (duplicate GSTIN), the ERP supplier
master is updated through the exactly-once integration queue and ``supplier.master.changed`` is emitted.

Contact phone numbers are kept in ``supplier.address['phone']`` (the supplier master has no separate phone column).
"""
import json
import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import ActionLog, Supplier, SupplierMasterChange, Task
from app.pic.platform import audit, clock, crypto, integration, outbox, rules, sod, workflow
from app.pic.platform.core import next_number
from app.pic.platform.errors import Problem, illegal_transition
from app.pic.services.common import principal, require_supplier_user

PROCESS = "pic.supplier-onboarding"
RULE = "SUPPLIER-MASTER-CHANGE"
TASK_KIND = "SUPPLIER_MASTER_CHANGE"
SOD_ACTION = "SUPPLIER_MASTER_CHANGE"
PURPOSE = "supplier-master-change"
FIELD_GROUPS = ("TAX", "ADDRESS", "CONTACT")

# ---------------------------------------------------------------- Indian tax-ID and address validation
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
PIN_RE = re.compile(r"^[1-9][0-9]{5}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9 \-]{7,16}[0-9]$")
# GST state codes 01-38 plus 97 (other territory).
STATE_CODES = {f"{i:02d}" for i in range(1, 39)} | {"97"}
_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_char(first14: str) -> str:
    """GSTIN check character: base-36 Luhn-style checksum over the first 14 characters."""
    total = 0
    for index, char in enumerate(first14):
        product = _CHARSET.index(char) * (2 if index % 2 else 1)
        total += product // 36 + product % 36
    return _CHARSET[(36 - total % 36) % 36]


def gstin_errors(gstin: str, pan: Optional[str] = None, state_code: Optional[str] = None) -> list[str]:
    errors = []
    if not GSTIN_RE.match(gstin or ""):
        return ["GSTIN must be 15 characters: 2-digit state code, 10-character PAN, entity number, 'Z' and a check character"]
    if gstin[:2] not in STATE_CODES:
        errors.append(f"GSTIN state code {gstin[:2]} is not a valid GST state code")
    if gstin_check_char(gstin[:14]) != gstin[14]:
        errors.append("GSTIN check character does not match (typing error?)")
    if pan is not None and pan != gstin[2:12]:
        errors.append("PAN must match characters 3-12 of the GSTIN")
    if state_code is not None and state_code != gstin[:2]:
        errors.append(f"GSTIN state {gstin[:2]} does not match the address state code {state_code}")
    return errors


def pan_errors(pan: str) -> list[str]:
    return [] if PAN_RE.match(pan or "") else ["PAN must be 5 letters, 4 digits and a letter (e.g. AABCT1234K)"]


def address_errors(address: dict) -> list[str]:
    errors = []
    for field in ("line1", "city", "state_code", "pin"):
        if not str(address.get(field) or "").strip():
            errors.append(f"address {field} is required")
    country = address.get("country") or "IN"
    if country == "IN":
        if address.get("state_code") and address["state_code"] not in STATE_CODES:
            errors.append(f"state code {address['state_code']} is not a valid GST state code")
        if address.get("pin") and not PIN_RE.match(str(address["pin"])):
            errors.append("PIN code must be 6 digits")
    return errors


def validation_problem(errors: list[str]) -> Problem:
    return Problem(422, "VALIDATION_FAILED", "; ".join(errors), rule_ref="MDM-04", errors=errors)


def normalise_address(raw: dict) -> dict:
    return {"line1": str(raw.get("line1") or "").strip(), "line2": str(raw.get("line2") or "").strip() or None,
            "city": str(raw.get("city") or "").strip(), "state_code": str(raw.get("state_code") or raw.get("stateCode") or "").strip(),
            "pin": str(raw.get("pin") or "").strip(), "country": (str(raw.get("country") or "IN").strip().upper() or "IN")}


# ---------------------------------------------------------------- masking (§14)
def mask_text(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    value = str(value)
    return value[:4] + "•" * min(max(len(value) - 4, 0), 8)


def mask_email(value: Optional[str]) -> Optional[str]:
    if not value or "@" not in value:
        return mask_text(value)
    local, domain = value.split("@", 1)
    return f"{local[:1]}•••@{domain}"


def mask_address(address: Optional[dict]) -> dict:
    address = address or {}
    if not any(address.get(k) for k in ("line1", "city", "pin")):
        return {}
    return {"line1": mask_text(address.get("line1")), "line2": mask_text(address.get("line2")), "city": address.get("city"),
            "state_code": address.get("state_code"), "pin": address.get("pin"), "country": address.get("country")}


def _mask_values(field_group: str, values: dict) -> dict:
    if field_group == "TAX":
        out = {"gstin": crypto.mask(values["gstin"]), "pan": crypto.mask(values["pan"]), "stateCode": values["gstin"][:2]}
        if values.get("address"):
            out["address"] = mask_address(values["address"])
        return out
    if field_group == "ADDRESS":
        return mask_address(values)
    return {"email": mask_email(values.get("email")), "phone": crypto.mask(values["phone"]) if values.get("phone") else None}


def _current_gstin(session: Session, supplier: Supplier) -> Optional[str]:
    if not supplier.gstin_enc:
        return None
    try:
        return crypto.decrypt(current_tenant(session), "gstin", supplier.gstin_enc)
    except Exception:  # noqa: BLE001 - a key rotation must not block a correcting change
        return None


def _current_masked(session: Session, supplier: Supplier, field_group: str) -> dict:
    if field_group == "TAX":
        gstin = _current_gstin(session, supplier)
        return {"gstin": supplier.gstin_masked, "pan": crypto.mask(gstin[2:12]) if gstin else None, "stateCode": supplier.state_code}
    if field_group == "ADDRESS":
        return mask_address(supplier.address)
    phone = (supplier.address or {}).get("phone")
    return {"email": mask_email(supplier.contact_email), "phone": crypto.mask(phone) if phone else None}


# ---------------------------------------------------------------- normalise and validate a request
def _validate(session: Session, supplier: Supplier, field_group: str, raw: dict) -> dict:
    errors: list[str] = []
    if field_group == "TAX":
        gstin = str(raw.get("gstin") or "").strip().upper().replace(" ", "")
        pan = str(raw.get("pan") or "").strip().upper().replace(" ", "")
        address = normalise_address(raw["address"]) if raw.get("address") else None
        errors += pan_errors(pan)
        if address:
            errors += address_errors(address)
        state = address["state_code"] if address else ((supplier.address or {}).get("state_code") or None)
        errors += gstin_errors(gstin, pan=pan, state_code=state)
        if not errors and supplier.gstin_hash == crypto.blind_index(current_tenant(session), gstin):
            errors.append("The GSTIN is unchanged")
        values = {"gstin": gstin, "pan": pan, **({"address": address} if address else {})}
    elif field_group == "ADDRESS":
        values = normalise_address(raw)
        errors += address_errors(values)
        if values["country"] == "IN" and supplier.state_code and values["state_code"] and values["state_code"] != supplier.state_code:
            errors.append(f"The address state {values['state_code']} does not match the GSTIN state {supplier.state_code}: "
                          "a move to another state needs a TAX change with the new GSTIN and address")
        current = supplier.address or {}
        if not errors and all((current.get(k) or None) == (values.get(k) or None) for k in values):
            errors.append("The address is unchanged")
    else:
        email = str(raw.get("email") or "").strip().lower() or None
        phone = str(raw.get("phone") or "").strip() or None
        if not email and not phone:
            errors.append("Give a new contact e-mail and/or phone number")
        if email and not EMAIL_RE.match(email):
            errors.append("Contact e-mail is not a valid address")
        if phone and not PHONE_RE.match(phone):
            errors.append("Phone must be 9-18 digits, optionally with a leading + country code")
        current_phone = (supplier.address or {}).get("phone")
        if not errors and (email is None or email == supplier.contact_email) and (phone is None or phone == current_phone):
            errors.append("The contact details are unchanged")
        values = {k: v for k, v in (("email", email), ("phone", phone)) if v}
    if errors:
        raise validation_problem(errors)
    return values


def _duplicates(session: Session, supplier: Supplier, gstin: str) -> list[dict]:
    digest = crypto.blind_index(current_tenant(session), gstin)
    return [{"code": other.code, "reason": "same GSTIN"} for other in session.execute(
        select(Supplier).where(Supplier.id != supplier.id, Supplier.gstin_hash == digest)).scalars()]


# ---------------------------------------------------------------- request
def request_change(session: Session, supplier: Supplier, *, field_group: str, values: dict, reason: str) -> SupplierMasterChange:
    require_supplier_user(session, supplier.id)
    p = principal(session)
    rule = rules.resolve(session, RULE)
    field_group = (field_group or "").upper()
    if field_group not in rule.body.get("fieldGroups", FIELD_GROUPS):
        raise Problem(422, "INVALID_FIELD_GROUP", f"fieldGroup must be one of {', '.join(rule.body.get('fieldGroups', FIELD_GROUPS))}",
                      rule_ref=rule.ref)
    if not (reason or "").strip():
        raise Problem(422, "REASON_REQUIRED", "Give the reason for the change (e.g. the GST registration amendment)", rule_ref="MDM-04")
    if supplier.status == "BLOCKED":
        raise Problem(409, "SUPPLIER_BLOCKED", f"{supplier.code} is blocked; master data cannot be changed", rule_ref="MDM-04")
    pending = session.execute(select(SupplierMasterChange.number).where(
        SupplierMasterChange.supplier_id == supplier.id, SupplierMasterChange.field_group == field_group,
        SupplierMasterChange.status == "IN_APPROVAL")).scalar()
    if pending:
        raise Problem(409, "CHANGE_PENDING", f"{pending} for the {field_group.lower()} data of {supplier.code} is still in approval",
                      rule_ref="MDM-04")
    clean = _validate(session, supplier, field_group, values or {})
    tenant_id = current_tenant(session)
    before, after = _current_masked(session, supplier, field_group), _mask_values(field_group, clean)
    duplicates = _duplicates(session, supplier, clean["gstin"]) if field_group == "TAX" else []
    change = SupplierMasterChange(
        tenant_id=tenant_id, number=next_number(session, "SUPPLIER_CHANGE"), supplier_id=supplier.id, field_group=field_group,
        before_masked=before, after_masked=after, after_enc=crypto.encrypt(tenant_id, PURPOSE, json.dumps(clean)).decode(),
        reason=reason.strip(), status="IN_APPROVAL", requested_by=p.user_id, approvals=[], created_by=p.user_id,
    )
    session.add(change)
    session.flush()
    # Four-eyes: the requester is excluded from the tasks and the task guard checks this logged action as well.
    sod.record(session, SOD_ACTION, {"supplier_id": supplier.id, "change_id": change.id})
    audit.record(session, "SUPPLIER", supplier.id, "MASTER_CHANGE_REQUESTED", object_ref=supplier.code, before=before,
                 after={"request": change.number, "fieldGroup": field_group, **after, **({"duplicates": duplicates} if duplicates else {})},
                 reason=change.reason, rule_set_version=rule.ref)
    instance = workflow.start(session, PROCESS, TASK_KIND, change.id, change.number,
                              {"supplier": supplier.code, "fieldGroup": field_group})
    workflow.step(session, instance, "F8-02", outcome=f"{field_group.lower()} change requested by {p.actor}")
    workflow.start_approval(
        session, instance, TASK_KIND, object_type=TASK_KIND, object_id=change.id, object_ref=change.number,
        chain=list(rule.body["approvers"]), mode="PARALLEL", step_id="F8-04", initiator_id=p.user_id, rule_set_version=rule.ref,
        evidence={"supplier": supplier.code, "fieldGroup": field_group, "before": before, "after": after, "reason": change.reason,
                  **({"duplicates": duplicates} if duplicates else {})},
    )
    return change


# ---------------------------------------------------------------- approval
def _requested(session: Session, actor_id, change_id) -> bool:
    return session.execute(select(ActionLog.id).where(
        ActionLog.actor_id == actor_id, ActionLog.action == SOD_ACTION, ActionLog.refs["change_id"].astext == str(change_id),
    ).limit(1)).first() is not None


@workflow.guard_task(TASK_KIND)
def _guard(session: Session, task: Task, decision: str) -> None:
    p = principal(session)
    change = session.get(SupplierMasterChange, task.object_id)
    if change is None:
        return
    if change.status != "IN_APPROVAL":
        raise illegal_transition("Supplier master change", change.number, change.status, "approve")
    if p.user_id == change.requested_by or _requested(session, p.user_id, change.id):
        raise Problem(409, "SOD_CONFLICT", "The requester of a supplier master change cannot approve it", rule_ref="MDM-04")
    others = session.execute(select(Task).where(Task.group_key == task.group_key, Task.id != task.id)).scalars()
    if any(t.completed_by == p.user_id for t in others):
        raise Problem(409, "SOD_CONFLICT", "The two approvals of a supplier master change must come from different people",
                      rule_ref="MDM-04")


@workflow.on_task(TASK_KIND)
def _decided(session: Session, task: Task, outcome: str) -> None:
    from app.pic.services import supplier as supplier_svc

    change = session.get(SupplierMasterChange, task.object_id)
    supplier = session.get(Supplier, change.supplier_id)
    tasks = session.execute(select(Task).where(Task.group_key == task.group_key).order_by(Task.sequence)).scalars().all()
    change.approvals = [{"role": t.candidate_role, "by": str(t.completed_by), "decision": t.decision,
                         "at": t.completed_at.isoformat() if t.completed_at else None, "comment": t.comment}
                        for t in tasks if t.completed_by]
    instance = workflow.find(session, TASK_KIND, change.id, PROCESS)
    if outcome != "APPROVED":
        change.status = "REJECTED"
        audit.record(session, "SUPPLIER", supplier.id, "MASTER_CHANGE_REJECTED", object_ref=supplier.code,
                     after={"request": change.number, "fieldGroup": change.field_group, "rejectedBy": task.candidate_role},
                     reason=task.comment, rule_set_version=task.rule_set_version)
        if instance:
            workflow.end(session, instance, "F8-09", outcome=f"master change rejected by {task.candidate_role}: {task.comment}")
        return

    tenant_id = current_tenant(session)
    values = json.loads(crypto.decrypt(tenant_id, PURPOSE, change.after_enc.encode()))
    screening = None
    if change.field_group == "TAX":
        gstin = values["gstin"]
        supplier.gstin_enc = crypto.encrypt(tenant_id, "gstin", gstin)
        supplier.gstin_masked = crypto.mask(gstin)
        supplier.gstin_hash = crypto.blind_index(tenant_id, gstin)
        supplier.pan_hash = crypto.blind_index(tenant_id, values["pan"])
        supplier.state_code = gstin[:2]
        if values.get("address"):
            supplier.address = {**values["address"], **({"phone": supplier.address["phone"]} if (supplier.address or {}).get("phone") else {})}
        session.flush()
        if instance:
            workflow.step(session, instance, "F8-03", outcome="re-screening after tax-ID change (duplicate GSTIN, sanctions)")
        screening = supplier_svc.screen(session, supplier, record_step=False)
    elif change.field_group == "ADDRESS":
        phone = (supplier.address or {}).get("phone")
        supplier.address = {**values, **({"phone": phone} if phone else {})}
    else:
        if values.get("email"):
            supplier.contact_email = values["email"]
        if values.get("phone"):
            supplier.address = {**(supplier.address or {}), "phone": values["phone"]}
    change.status = "APPLIED"
    change.applied_at = clock.now()
    message = None
    if supplier.status != "REGISTERED":  # not yet created in the ERP: the create message carries the current master
        message = integration.enqueue(
            session, target_system=integration.target_system(session), message_type="SUPPLIER_MASTER",
            idempotency_key=f"{supplier.code}|{change.field_group}|{change.number}",
            object_type="SUPPLIER", object_id=supplier.id, object_ref=supplier.code,
            payload={"supplier": supplier.code, "change": change.number, "fieldGroup": change.field_group, **change.after_masked})
    outbox.emit(session, "supplier.master.changed", "SUPPLIER", supplier.id, supplier.code,
                {"supplierCode": supplier.code, "change": change.number, "fieldGroup": change.field_group,
                 "after": change.after_masked, "screening": screening["outcome"] if screening else None,
                 "erpMessage": str(message.id) if message else None})
    audit.record(session, "SUPPLIER", supplier.id, "MASTER_CHANGE_APPLIED", object_ref=supplier.code, before=change.before_masked,
                 after={"request": change.number, "fieldGroup": change.field_group, **change.after_masked,
                        "approvers": [a["role"] for a in change.approvals],
                        **({"screening": screening["outcome"]} if screening else {})},
                 reason=change.reason, rule_set_version=task.rule_set_version)
    if instance:
        workflow.end(session, instance, "F8-07", outcome=f"{change.field_group.lower()} change applied"
                     + ("; ERP supplier master update queued" if message else "; supplier not yet in ERP"))


# ---------------------------------------------------------------- read
def view(session: Session, change: SupplierMasterChange, supplier_code: Optional[str] = None) -> dict:
    from app.pic.platform.serialize import row

    tasks = session.execute(select(Task).where(Task.object_id == change.id).order_by(Task.created_at)).scalars().all()
    return row(change, extra={
        "supplier": supplier_code,
        "tasks": [{"id": str(t.id), "role": t.candidate_role, "status": t.status, "decision": t.decision,
                   "completedAt": t.completed_at.isoformat() if t.completed_at else None, "comment": t.comment} for t in tasks],
    })


def list_for(session: Session, supplier: Supplier) -> list[dict]:
    require_supplier_user(session, supplier.id)
    changes = session.execute(select(SupplierMasterChange).where(SupplierMasterChange.supplier_id == supplier.id)
                              .order_by(SupplierMasterChange.created_at.desc())).scalars().all()
    return [view(session, c, supplier.code) for c in changes]
