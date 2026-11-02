"""Attribute-based access control on commands (Technical Document SEC-AZ).

RBAC (platform/auth.py) decides *which command* a role may call; ABAC decides *on which objects and up to which value*:
the company codes, plants and categories in the user's ``attributes`` and the value limit (``value_limit_minor``, or a limit per
action in ``approval_limits``). One helper, called from the services' entry points::

    abac.authorize(session, principal, "PO_RELEASE", po)        # or abac.guard(session, "PO_RELEASE", po) for session.info principal

The policy is tenant data (rule ABAC, effective-dated and scoped like every rule): which dimensions each action checks, whether
the value limit applies, and the mode ENFORCE (403) | AUDIT (allow, but log the would-be denial) | OFF. A user without the
attribute (or with "*") is not restricted on that dimension, so the shipped users keep working; restricting a user means giving
them the attribute. Agents are bounded by their own autonomy limits (platform/agents.py), not by user attributes.

Every denial is audited in its own transaction (the command's transaction is rolled back by the 403) and counted in the metrics.
``evaluate`` is the pure function the approval-matrix simulator uses (services/policy_sim.py), so the simulator and the
enforcement can never disagree.
"""
import logging
from typing import Any, Optional

from sqlalchemy import select, text

from app.pic.db import tenant_tx
from app.pic.models import AppUser
from app.pic.platform import audit
from app.pic.platform.errors import Problem

log = logging.getLogger("pic.abac")

# Used when a tenant has no ABAC rule set: the same policy as the shipped rule.
DEFAULT_POLICY: dict = {
    "mode": "ENFORCE",
    "dimensions": {"company_code": "company_codes", "plant": "plants", "category": "categories"},
    "valueLimitAttribute": "value_limit_minor", "limitsAttribute": "approval_limits",
    "actions": {
        "REQ_SUBMIT": {"check": ["company_code", "plant"]},
        "REQ_APPROVE": {"check": ["company_code", "plant"], "valueLimit": True},
        "PO_CREATE": {"check": ["company_code", "plant"]},
        "PO_RELEASE": {"check": ["company_code", "plant"], "valueLimit": True},
        "PO_APPROVE": {"check": ["company_code", "plant"], "valueLimit": True},
        "GR_POST": {"check": ["company_code", "plant"]},
        "INVOICE_APPROVE": {"check": ["company_code"], "valueLimit": True},
        "INVOICE_POST": {"check": ["company_code"], "valueLimit": True},
        "PAYMENT_RUN": {"check": ["company_code"], "valueLimit": True},
        "CONTRACT_SIGN": {"check": ["company_code"], "valueLimit": True},
        "AWARD_APPROVE": {"check": ["category"], "valueLimit": True},
        "SUPPLIER_CHANGE": {"check": ["category"]},
        "MASTER_CHANGE": {"check": ["company_code", "plant"]},
    },
}
# Actions added after tenants were bootstrapped: a tenant whose ABAC rule set predates them gets these (its own entry for the action wins).
# STOCK_MOVE: any stock-changing command outside the goods receipt (usage decision, consignment withdrawal, recall, expiry write-off);
# INVENTORY_*: the inventory documents (services/inventory.py); approving is bound by the approver's value limit.
INVENTORY_ACTIONS = {
    "STOCK_MOVE": {"check": ["company_code", "plant"]},
    "INVENTORY_POST": {"check": ["company_code", "plant"]},
    "INVENTORY_APPROVE": {"check": ["company_code", "plant"], "valueLimit": True},
    "INVENTORY_COUNT": {"check": ["company_code", "plant"]},
    "INVENTORY_RESERVE": {"check": ["company_code", "plant"]},
}
DEFAULT_POLICY["actions"].update(INVENTORY_ACTIONS)

# Approval task kind -> ABAC action (workflow.complete calls ``guard_task``).
TASK_ACTIONS = {
    "REQ_APPROVAL": "REQ_APPROVE", "PO_APPROVAL": "PO_APPROVE", "PO_CHANGE_APPROVAL": "PO_APPROVE", "PO_CHANGE_REVIEW": "PO_APPROVE",
    "AWARD_APPROVAL": "AWARD_APPROVE", "CONTRACT_APPROVAL": "CONTRACT_SIGN", "BANK_CHANGE": "SUPPLIER_CHANGE",
    "SES_APPROVAL": "INVOICE_APPROVE", "MDM_STEWARD": "MASTER_CHANGE",
    "STOCK_POSTING_APPROVAL": "INVENTORY_APPROVE", "PHYSICAL_INVENTORY_APPROVAL": "INVENTORY_APPROVE",
}
VALUE_FIELDS = ("total_minor", "gross_minor", "net_minor", "amount_minor", "target_value_minor", "award_value_minor", "total_value_minor")
MODES = ("ENFORCE", "AUDIT", "OFF")


# ---------------------------------------------------------------- pure evaluation (shared with the simulator)
def _allowed(attributes: dict, attribute: str) -> Optional[list]:
    value = attributes.get(attribute)
    if value is None:
        return None
    return [value] if isinstance(value, str) else list(value)


def evaluate(policy: dict, attributes: dict, action: str, dims: dict, value_minor: Optional[int] = None) -> dict:
    """{"allowed", "enforced", "mode", "checked", "violations": [{code, dimension, attribute, value, allowed|limitMinor}]} for one
    user (attributes), action and object (dims: company_code, plant, category; value_minor)."""
    mode = str(policy.get("mode", "ENFORCE")).upper()
    spec = (policy.get("actions") or {}).get(action)
    result = {"action": action, "mode": mode, "checked": [], "violations": [], "known": spec is not None}
    if spec is None or mode == "OFF":
        result.update(allowed=True, enforced=False)
        return result
    for dim in spec.get("check") or []:
        attribute = (policy.get("dimensions") or {}).get(dim)
        value = dims.get(dim)
        if attribute is None or value is None:
            continue
        allowed = _allowed(attributes, attribute)
        result["checked"].append(dim)
        if allowed is not None and "*" not in allowed and str(value) not in {str(a) for a in allowed}:
            result["violations"].append({"code": "FORBIDDEN", "dimension": dim, "attribute": attribute, "value": str(value), "allowed": allowed})
    if spec.get("valueLimit") and value_minor is not None:
        limits = attributes.get(policy.get("limitsAttribute", "approval_limits")) or {}
        limit = limits.get(action, attributes.get(policy.get("valueLimitAttribute", "value_limit_minor")))
        result["checked"].append("value")
        if limit is not None and int(value_minor) > int(limit):
            result["violations"].append({"code": "VALUE_LIMIT_EXCEEDED", "dimension": "value", "value": int(value_minor), "limitMinor": int(limit)})
    result["allowed"] = not result["violations"]
    result["enforced"] = mode == "ENFORCE"
    return result


def describe(violation: dict) -> str:
    if violation["code"] == "VALUE_LIMIT_EXCEEDED":
        return f"amount {violation['value']} exceeds your limit of {violation['limitMinor']} (minor units)"
    dimension = violation["dimension"].replace("_", " ")
    return f"you are not assigned to {dimension} {violation['value']}"


# ---------------------------------------------------------------- object -> dimensions
def dimensions_of(obj: Any, **override: Any) -> tuple[dict, Optional[int]]:
    dims = {name: override.get(name) if override.get(name) is not None else getattr(obj, name, None)
            for name in ("company_code", "plant", "category")}
    value = override.get("value_minor")
    if value is None and obj is not None:
        for name in VALUE_FIELDS:
            candidate = getattr(obj, name, None)
            if candidate is not None:
                value = candidate
                break
    return dims, (int(value) if value is not None else None)


def policy_for(session, **scope: Optional[str]) -> dict:
    from app.pic.platform import rules  # local import: rules is imported by modules that import abac
    try:
        body = rules.resolve(session, "ABAC", **scope).body
    except Problem:
        return DEFAULT_POLICY
    missing = {k: v for k, v in INVENTORY_ACTIONS.items() if k not in (body.get("actions") or {})}
    return {**body, "actions": {**(body.get("actions") or {}), **missing}} if missing else body


def _attributes(session, principal) -> dict:
    """Current attributes from the database (an administrator's change applies at once, not at the next sign-in); the token's
    attributes for principals without a user row."""
    row = session.execute(select(AppUser.attributes).where(AppUser.id == principal.user_id)).scalar_one_or_none()
    return dict(row) if row is not None else dict(principal.attributes or {})


# ---------------------------------------------------------------- enforcement
def authorize(session, principal, action: str, obj: Any = None, *, value_minor: Optional[int] = None,
              company_code: Optional[str] = None, plant: Optional[str] = None, category: Optional[str] = None) -> dict:
    """Raise 403 (FORBIDDEN | VALUE_LIMIT_EXCEEDED, ruleRef ABAC) when the principal's attributes do not allow ``action`` on ``obj``.
    Returns the evaluation (allowed, mode, checked dimensions)."""
    if principal is None or principal.is_agent or principal.attributes.get("mfa_enrolment"):
        return {"allowed": True, "enforced": False, "mode": "AGENT", "checked": [], "violations": [], "action": action}
    dims, value = dimensions_of(obj, value_minor=value_minor, company_code=company_code, plant=plant, category=category)
    policy = policy_for(session, company_code=dims.get("company_code"), plant=dims.get("plant"), category=dims.get("category"))
    result = evaluate(policy, _attributes(session, principal), action, dims, value)
    if result["allowed"]:
        return result
    _audit_denial(session, principal, action, obj, result, dims, value)
    if not result["enforced"]:
        return result  # AUDIT mode: logged above, command continues
    first = result["violations"][0]
    raise Problem(403, first["code"], "; ".join(describe(v) for v in result["violations"]), rule_ref="ABAC",
                  action=action, violations=[{k: v for k, v in x.items() if k != "allowed"} for x in result["violations"]])


def guard(session, action: str, obj: Any = None, **kwargs: Any) -> dict:
    """``authorize`` for the principal on the session (set by ``api.deps.uow`` and the seeds' ``Scenario.act``)."""
    return authorize(session, session.info.get("principal"), action, obj, **kwargs)


def guard_task(session, task, decision: str) -> None:
    """workflow.complete hook: approving a task is an ABAC action on the document it is about (rejecting and returning are not)."""
    action = TASK_ACTIONS.get(task.kind)
    if action is None or decision.upper() != "APPROVE":
        return
    obj = _document(session, task.object_type, task.object_id)
    if obj is not None:
        guard(session, action, obj)


def _document(session, object_type: str, object_id):
    from app.pic import models
    model = {"REQUISITION": models.Requisition, "PURCHASE_ORDER": models.PurchaseOrder, "SOURCING_EVENT": models.SourcingEvent,
             "CONTRACT": models.Contract, "INVOICE": models.Invoice, "SERVICE_ENTRY": models.ServiceEntry,
             "MATERIAL_REQUEST": models.MaterialRequest, "STOCK_POSTING": models.StockPosting,
             "PHYSICAL_INVENTORY": models.PhysicalInventory}.get(object_type)
    return session.get(model, object_id) if model is not None else None


def _audit_denial(session, principal, action: str, obj: Any, result: dict, dims: dict, value: Optional[int]) -> None:
    """Own transaction: the denial is evidence and must outlive the rolled-back command."""
    try:
        with tenant_tx(principal.tenant_id, principal.user_id, principal) as s:
            # The command's own transaction may hold the tenant's audit-chain lock: wait briefly, never deadlock.
            s.execute(text("SET LOCAL lock_timeout = '1500ms'"))
            audit.record(s, getattr(obj, "__tablename__", "ABAC").upper() if obj is not None else "ABAC",
                         getattr(obj, "id", principal.user_id), "ABAC_DENIED" if result["enforced"] else "ABAC_WOULD_DENY",
                         object_ref=getattr(obj, "number", None) or getattr(obj, "code", None),
                         after={"action": action, "dimensions": {k: v for k, v in dims.items() if v is not None}, "valueMinor": value,
                                "violations": result["violations"], "mode": result["mode"]},
                         reason="; ".join(describe(v) for v in result["violations"]))
    except Exception:  # noqa: BLE001 - the audit write must never turn a denial into a 500
        log.exception("could not audit ABAC denial")
