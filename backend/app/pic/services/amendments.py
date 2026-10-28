"""M07 contract amendments (variation, extension, terms) and termination.

An amendment is a change set against one contract version. It is validated and
priced first (``plan``, also used for the live preview), routed through the
CONTRACT-AMENDMENT approval chain (the requester never approves), and applied
on its effective date: immediately when that date has arrived, otherwise by a
timer. Applying raises ``contract.version``; the before-snapshot keeps the
history. Price changes and extensions add price-validity periods; existing
periods are never re-priced. Termination ends prices and quota from the
effective date, flags open purchase orders and closes the F4 process.
"""
import calendar
import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    AppUser, Clause, Contract, ContractAmendment, ContractLine, PoLine, PriceValidity, PurchaseOrder, QuotaArrangement, QuotaLine,
    Task, Timer,
)
from app.pic.platform import audit, clock, outbox, rules, workflow
from app.pic.platform.core import next_number
from app.pic.platform.errors import Problem, illegal_transition, not_found, rule_violation
from app.pic.platform.money import D, fmt_inr, line_amount
from app.pic.platform.serialize import jsonable, row
from app.pic.services import contract as contract_svc
from app.pic.services import source
from app.pic.services.common import principal

KINDS = ("VARIATION", "EXTENSION", "TERMS", "TERMINATION")
PENDING = ("DRAFT", "IN_APPROVAL", "APPROVED")
LIVE = ("ACTIVE", "EXPIRING")
OPEN_PO = ("DRAFT", "IN_APPROVAL", "RELEASED", "TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED")
TASK_KIND = "CONTRACT_AMENDMENT"
PO_REVIEW_KIND = "TERMINATED_CONTRACT_REVIEW"
TIMER_KIND = "CONTRACT_AMENDMENT_EFFECTIVE"
RULE_REF = "CLM-AMEND"
META_KEYS = ("valueDeltaMinor", "approvalChain", "band", "ruleSet")


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    last = calendar.monthrange(year, month)[1]
    # Month-end stays month-end (31 Oct + 12 months → 31 Oct; 30 Apr + 1 → 31 May).
    day = last if d.day == calendar.monthrange(d.year, d.month)[1] else min(d.day, last)
    return date(year, month, day)


def _lines(session: Session, contract: Contract) -> dict[int, ContractLine]:
    return {l.line_no: l for l in contract_svc._lines(session, contract)}


def _price_on(session: Session, line: ContractLine, on: date) -> Optional[PriceValidity]:
    validity = source.contract_price(session, line.id, on)
    if validity is None:
        validity = session.execute(select(PriceValidity).where(PriceValidity.contract_line_id == line.id, PriceValidity.published.is_(True))
                                   .order_by(PriceValidity.valid_from.desc(), PriceValidity.created_at.desc()).limit(1)).scalar_one_or_none()
    return validity


def _requested(changes: dict) -> dict:
    return {k: v for k, v in (changes or {}).items() if k not in META_KEYS}


def _date(value, field: str) -> date:
    try:
        return value if isinstance(value, date) else date.fromisoformat(str(value))
    except ValueError:
        raise Problem(422, "INVALID_DATE", f"{field} must be an ISO date (YYYY-MM-DD)")


# ---------------------------------------------------------------- plan (validation, value delta, approval route)
def plan(session: Session, contract: Contract, kind: str, changes: dict, effective_from: date, *, check_dates: bool = True) -> dict:
    """Validate an amendment and compute its effect without saving anything (also the live preview)."""
    kind = (kind or "").upper()
    if kind not in KINDS:
        raise Problem(422, "INVALID_AMENDMENT_KIND", f"kind must be one of {', '.join(KINDS)}")
    if contract.status not in LIVE:
        raise illegal_transition("Contract", contract.number, contract.status, "amend")
    rule = rules.resolve(session, "CONTRACT-AMENDMENT", company_code=contract.company_code)
    today = clock.today()
    changes = _requested(changes)
    if check_dates and effective_from < today:
        raise rule_violation(f"Amendments cannot be back-dated: effective date {effective_from} is before today ({today})", RULE_REF)
    if kind != "EXTENSION" and effective_from > contract.valid_to:
        raise rule_violation(f"Effective date {effective_from} is after the contract end {contract.valid_to}", RULE_REF)
    lines = _lines(session, contract)
    priced_on = max(effective_from, contract.valid_from)
    before: dict = {"version": contract.version}
    after: dict = {}
    normalised: dict = {}
    delta = 0
    extra: dict = {}

    if kind == "VARIATION":
        requested = changes.get("lines") or []
        if not requested:
            raise Problem(422, "NO_CHANGES", "A variation needs at least one line with a new unit price or target quantity")
        before["lines"], after["lines"], normalised["lines"] = [], [], []
        seen = set()
        for item in requested:
            line_no = int(item.get("line", 0))
            if line_no not in lines or line_no in seen:
                raise Problem(422, "INVALID_LINE", f"Line {line_no} is not a line of {contract.number} (or is listed twice)")
            seen.add(line_no)
            line = lines[line_no]
            validity = _price_on(session, line, priced_on)
            old_price = validity.unit_price_minor if validity else 0
            new_price = int(item["unitPriceMinor"]) if item.get("unitPriceMinor") not in (None, "") else old_price
            new_qty = D(item["targetQty"]) if item.get("targetQty") not in (None, "") else line.target_qty
            if new_price <= 0 or new_qty <= 0:
                raise Problem(422, "INVALID_VALUE", f"Line {line_no}: price and quantity must be positive")
            if new_qty < line.released_qty:
                raise rule_violation(f"Line {line_no}: target quantity {new_qty} is below the {line.released_qty} already released", RULE_REF)
            if new_price == old_price and new_qty == line.target_qty:
                raise Problem(422, "NO_CHANGES", f"Line {line_no} has no change")
            line_delta = (line_amount(new_qty - line.released_qty, new_price) - line_amount(line.target_qty - line.released_qty, old_price))
            delta += line_delta
            before["lines"].append({"line": line_no, "description": line.description, "unitPriceMinor": old_price,
                                    "targetQty": jsonable(line.target_qty), "releasedQty": jsonable(line.released_qty)})
            after["lines"].append({"line": line_no, "description": line.description, "unitPriceMinor": new_price,
                                   "targetQty": jsonable(new_qty), "valueDeltaMinor": line_delta})
            entry = {"line": line_no}
            if new_price != old_price:
                entry["unitPriceMinor"] = new_price
            if new_qty != line.target_qty:
                entry["targetQty"] = jsonable(new_qty)
            normalised["lines"].append(entry)
        before["targetValueMinor"] = contract.target_value_minor
        after["targetValueMinor"] = contract.target_value_minor + delta

    elif kind == "EXTENSION":
        new_to = _date(changes["validTo"], "validTo") if changes.get("validTo") else add_months(contract.valid_to, 12)
        if new_to <= contract.valid_to:
            raise rule_violation(f"The new end date {new_to} must be after the current end {contract.valid_to}", RULE_REF)
        term_days = (contract.valid_to - contract.valid_from).days + 1
        extra_days = (new_to - contract.valid_to).days
        # Value of the extra period, pro rata to the current term.
        delta = int((Decimal(contract.target_value_minor) * extra_days / term_days).quantize(Decimal("1"), ROUND_HALF_UP))
        before.update({"validTo": contract.valid_to.isoformat(), "targetValueMinor": contract.target_value_minor})
        after.update({"validTo": new_to.isoformat(), "targetValueMinor": contract.target_value_minor + delta, "extraDays": extra_days})
        normalised["validTo"] = new_to.isoformat()

    elif kind == "TERMS":
        if changes.get("paymentTerms") not in (None, "") and changes["paymentTerms"] != contract.payment_terms:
            terms = str(changes["paymentTerms"]).strip().upper()
            if len(terms) > 10:
                raise Problem(422, "INVALID_VALUE", "paymentTerms is at most 10 characters (e.g. N45)")
            before["paymentTerms"], after["paymentTerms"], normalised["paymentTerms"] = contract.payment_terms, terms, terms
        if changes.get("incoterms") not in (None, "") and changes["incoterms"] != contract.incoterms:
            before["incoterms"], after["incoterms"] = contract.incoterms, str(changes["incoterms"])[:40]
            normalised["incoterms"] = after["incoterms"]
        tolerances = changes.get("tolerances") or {}
        current = {"over_pct": contract.over_tolerance_pct, "under_pct": contract.under_tolerance_pct, "price_pct": contract.price_tolerance_pct}
        changed_tol = {}
        for key, value in tolerances.items():
            if key not in current:
                raise Problem(422, "INVALID_VALUE", f"Unknown tolerance {key}; use over_pct, under_pct or price_pct")
            if value in (None, ""):
                continue
            pct = D(value)
            if pct < 0 or pct > 100:
                raise Problem(422, "INVALID_VALUE", f"{key} must be between 0 and 100")
            if pct != current[key]:
                changed_tol[key] = jsonable(pct)
        if changed_tol:
            before["tolerances"] = {k: jsonable(current[k]) for k in changed_tol}
            after["tolerances"], normalised["tolerances"] = changed_tol, changed_tol
        clauses = {c.code: c for c in session.execute(select(Clause).where(Clause.contract_id == contract.id)).scalars()}
        clause_changes = []
        for item in changes.get("clauses") or []:
            code = str(item.get("code", "")).strip().upper()
            text = str(item.get("text", "")).strip()
            if not code or not text:
                raise Problem(422, "INVALID_VALUE", "Each clause change needs a code and the new text")
            existing = clauses.get(code)
            if existing is None and not item.get("title"):
                raise Problem(422, "INVALID_VALUE", f"Clause {code} is new; give it a title")
            if existing is not None and existing.text == text:
                continue
            position = str(item.get("position") or (existing.position if existing else "STANDARD")).upper()
            if position not in ("STANDARD", "FALLBACK", "NON_STANDARD"):
                raise Problem(422, "INVALID_VALUE", "position must be STANDARD, FALLBACK or NON_STANDARD")
            clause_changes.append({"code": code, "title": item.get("title") or existing.title, "text": text, "position": position,
                                   "before": existing.text if existing else None})
        if clause_changes:
            before["clauses"] = [{"code": c["code"], "text": c["before"]} for c in clause_changes]
            after["clauses"] = [{k: c[k] for k in ("code", "title", "text", "position")} for c in clause_changes]
            normalised["clauses"] = after["clauses"]
        if len(normalised) == 0:
            raise Problem(422, "NO_CHANGES", "Change at least one of payment terms, incoterms, tolerances or clause text")

    else:  # TERMINATION
        for_cause = bool(changes.get("forCause"))
        notice = int(rule.body["noticeDays"])
        earliest = today + timedelta(days=notice)
        if check_dates and not for_cause and effective_from < earliest:
            raise rule_violation(f"Termination without cause needs {notice} days' notice: the earliest effective date is {earliest}",
                                 f"CONTRACT-AMENDMENT@{rule.version}", earliestEffective=earliest.isoformat())
        remaining = 0
        for l in lines.values():
            validity = _price_on(session, l, priced_on)
            remaining += line_amount(max(l.target_qty - l.released_qty, Decimal(0)), validity.unit_price_minor if validity else 0)
        delta = -remaining
        before.update({"status": contract.status, "validTo": contract.valid_to.isoformat()})
        after.update({"status": "TERMINATED", "lastDayInForce": (effective_from - timedelta(days=1)).isoformat(),
                      "remainingValueMinor": remaining})
        normalised["forCause"] = for_cause
        extra["noticeDays"] = notice
        extra["earliestWithoutCause"] = earliest.isoformat()
        extra["openPurchaseOrders"] = [{"number": po.number, "status": po.status, "totalMinor": po.total_minor}
                                       for po in open_purchase_orders(session, contract)]

    if kind == "TERMINATION":
        band, chain = "termination", list(rule.body["termination"])
    elif abs(delta) >= int(rule.body["thresholdMinor"]):
        band, chain = "above", list(rule.body["above"])
    else:
        band, chain = "below", list(rule.body["below"])
    return {"contract": contract.number, "kind": kind, "effectiveFrom": effective_from.isoformat(), "fromVersion": contract.version,
            "changes": normalised, "before": before, "after": after, "valueDeltaMinor": delta, "valueDelta": fmt_inr(delta),
            "band": band, "approvalChain": chain, "thresholdMinor": int(rule.body["thresholdMinor"]), "ruleSet": rule.ref, **extra}


def open_purchase_orders(session: Session, contract: Contract) -> list[PurchaseOrder]:
    line_ids = [l.id for l in contract_svc._lines(session, contract)]
    po_ids = select(PoLine.po_id).where(PoLine.contract_line_id.in_(line_ids)) if line_ids else None
    condition = PurchaseOrder.contract_id == contract.id
    if po_ids is not None:
        condition = or_(condition, PurchaseOrder.id.in_(po_ids))
    return session.execute(select(PurchaseOrder).where(condition, PurchaseOrder.status.in_(OPEN_PO))
                           .order_by(PurchaseOrder.number)).scalars().all()


# ---------------------------------------------------------------- create, submit, withdraw
def _pending(session: Session, contract: Contract) -> Optional[ContractAmendment]:
    return session.execute(select(ContractAmendment).where(ContractAmendment.contract_id == contract.id,
                                                           ContractAmendment.status.in_(PENDING)).limit(1)).scalar_one_or_none()


def create(session: Session, contract: Contract, *, kind: str, changes: dict, reason: str, effective_from: date,
           submit_now: bool = True) -> ContractAmendment:
    p = principal(session)
    if not (reason or "").strip():
        raise Problem(422, "REASON_REQUIRED", "Give the business reason for the amendment")
    pending = _pending(session, contract)
    if pending is not None:
        raise Problem(409, "AMENDMENT_PENDING", f"{pending.number} ({pending.kind}, {pending.status}) must be decided or withdrawn first",
                      rule_ref=RULE_REF, amendment=pending.number)
    result = plan(session, contract, kind, changes, effective_from)
    amendment = ContractAmendment(
        tenant_id=current_tenant(session), number=next_number(session, "CONTRACT_AMENDMENT"), contract_id=contract.id,
        kind=result["kind"], changes={**result["changes"], **{k: result[k] for k in META_KEYS}}, reason=reason.strip(),
        status="DRAFT", effective_from=effective_from, from_version=contract.version, snapshot=result["before"],
        requested_by=p.user_id, created_by=p.user_id,
    )
    session.add(amendment)
    session.flush()
    audit.record(session, "CONTRACT", contract.id, "AMENDMENT_DRAFTED", object_ref=contract.number, reason=amendment.reason,
                 after={"amendment": amendment.number, "kind": amendment.kind, "effectiveFrom": effective_from.isoformat(),
                        "changes": result["changes"], "valueDeltaMinor": result["valueDeltaMinor"]}, rule_set_version=result["ruleSet"])
    if submit_now:
        submit(session, amendment)
    return amendment


def submit(session: Session, amendment: ContractAmendment) -> ContractAmendment:
    """Re-validate against the current contract version and open the approval chain."""
    p = principal(session)
    if amendment.status != "DRAFT":
        raise illegal_transition("Contract amendment", amendment.number, amendment.status, "submit")
    contract = session.get(Contract, amendment.contract_id)
    if amendment.kind == "EXTENSION" and amendment.effective_from < clock.today():
        # A draft (e.g. from an approved renewal) submitted on a later day: an extension only adds validity after the current end,
        # so it becomes effective on approval; moving the date forward avoids an unsubmittable back-dated draft.
        audit.record(session, "CONTRACT", contract.id, "AMENDMENT_REDATED", object_ref=contract.number,
                     before={"amendment": amendment.number, "effectiveFrom": amendment.effective_from.isoformat()},
                     after={"amendment": amendment.number, "effectiveFrom": clock.today().isoformat()}, reason="submitted after the draft date")
        amendment.effective_from = clock.today()
    result = plan(session, contract, amendment.kind, amendment.changes, amendment.effective_from)
    amendment.changes = {**result["changes"], **{k: result[k] for k in META_KEYS}}
    amendment.snapshot = result["before"]
    amendment.from_version = contract.version
    amendment.status = "IN_APPROVAL"
    audit.record(session, "CONTRACT", contract.id, "AMENDMENT_SUBMITTED", object_ref=contract.number,
                 after={"amendment": amendment.number, "chain": result["approvalChain"], "band": result["band"],
                        "valueDeltaMinor": result["valueDeltaMinor"]}, rule_set_version=result["ruleSet"])
    workflow.start_approval(
        session, contract_svc._instance(session, contract), TASK_KIND, object_type="CONTRACT", object_id=contract.id,
        object_ref=contract.number, chain=result["approvalChain"], step_id=None, initiator_id=p.user_id,
        exclude=[amendment.requested_by], rule_set_version=result["ruleSet"],
        evidence={"amendment": amendment.number, "amendmentId": str(amendment.id), "kind": amendment.kind,
                  "effectiveFrom": amendment.effective_from.isoformat(), "valueDeltaMinor": result["valueDeltaMinor"],
                  "before": result["before"], "after": result["after"], "reason": amendment.reason},
    )
    return amendment


def _amendment_tasks(session: Session, amendment: ContractAmendment) -> list[Task]:
    return session.execute(select(Task).where(Task.kind == TASK_KIND, Task.object_id == amendment.contract_id,
                                              Task.evidence["amendmentId"].astext == str(amendment.id))
                           .order_by(Task.created_at)).scalars().all()


def _close_tasks(session: Session, amendment: ContractAmendment) -> None:
    for task in _amendment_tasks(session, amendment):
        if task.status == "OPEN":
            task.status = "CANCELLED"
            _cancel_timers(session, "TASK_SLA", task.id)


def withdraw(session: Session, amendment: ContractAmendment, reason: str) -> ContractAmendment:
    if amendment.status not in PENDING:
        raise illegal_transition("Contract amendment", amendment.number, amendment.status, "withdraw")
    _lapse(session, amendment, f"withdrawn: {reason}")
    return amendment


def _lapse(session: Session, amendment: ContractAmendment, reason: str) -> None:
    """Close a pending amendment without applying it (withdrawn, or the contract ended first)."""
    _close_tasks(session, amendment)
    _cancel_timers(session, TIMER_KIND, amendment.id)
    before = amendment.status
    amendment.status = "REJECTED"
    amendment.decided_at = clock.now()
    contract = session.get(Contract, amendment.contract_id)
    audit.record(session, "CONTRACT", contract.id, "AMENDMENT_CLOSED", object_ref=contract.number, reason=reason,
                 before={"amendment": amendment.number, "status": before}, after={"amendment": amendment.number, "status": "REJECTED"})


def close_pending(session: Session, contract: Contract, reason: str) -> None:
    for amendment in session.execute(select(ContractAmendment).where(ContractAmendment.contract_id == contract.id,
                                                                     ContractAmendment.status.in_(PENDING))).scalars().all():
        _lapse(session, amendment, reason)


def _cancel_timers(session: Session, kind: str, object_id: uuid.UUID) -> None:
    for timer in session.execute(select(Timer).where(Timer.kind == kind, Timer.object_id == object_id, Timer.fired_at.is_(None))).scalars():
        timer.fired_at = clock.now()
        timer.payload = {**(timer.payload or {}), "cancelled": True}


# ---------------------------------------------------------------- approval
@workflow.guard_task(TASK_KIND)
def _guard(session: Session, task: Task, decision: str) -> None:
    amendment = session.get(ContractAmendment, uuid.UUID(task.evidence["amendmentId"]))
    if principal(session).user_id == amendment.requested_by:
        raise Problem(403, "NOT_YOUR_TASK", "four-eyes rule: the requester cannot approve their own amendment", rule_ref="SOD/ABAC")
    contract = session.get(Contract, amendment.contract_id)
    if decision == "APPROVE" and contract.version != amendment.from_version:
        raise Problem(409, "AMENDMENT_STALE", f"{contract.number} moved to version {contract.version}; {amendment.number} was raised "
                                              f"against version {amendment.from_version}", rule_ref=RULE_REF)


@workflow.on_task(TASK_KIND)
def _decided(session: Session, task: Task, outcome: str) -> None:
    amendment = session.get(ContractAmendment, uuid.UUID(task.evidence["amendmentId"]))
    contract = session.get(Contract, amendment.contract_id)
    amendment.decided_at = clock.now()
    if outcome != "APPROVED":
        # Rejected is final; returned goes back to draft for rework and resubmission.
        amendment.status = "REJECTED" if outcome == "REJECTED" else "DRAFT"
        audit.record(session, "CONTRACT", contract.id, f"AMENDMENT_{outcome}", object_ref=contract.number, reason=task.comment,
                     after={"amendment": amendment.number, "status": amendment.status}, rule_set_version=task.rule_set_version)
        return
    amendment.status = "APPROVED"
    amendment.approved_by = task.completed_by
    audit.record(session, "CONTRACT", contract.id, "AMENDMENT_APPROVED", object_ref=contract.number,
                 after={"amendment": amendment.number, "effectiveFrom": amendment.effective_from.isoformat()},
                 rule_set_version=task.rule_set_version)
    if amendment.effective_from <= clock.today():
        apply(session, amendment)
    else:
        workflow.create_timer(session, TIMER_KIND, "CONTRACT_AMENDMENT", amendment.id, clock.at_ist(amendment.effective_from, 0, 1),
                              {"amendment": amendment.number, "contract": contract.number})


@workflow.on_timer(TIMER_KIND)
def _effective(session: Session, timer: Timer) -> None:
    amendment = session.get(ContractAmendment, timer.object_id)
    if amendment is not None and amendment.status == "APPROVED":
        apply(session, amendment)


# ---------------------------------------------------------------- apply
def apply(session: Session, amendment: ContractAmendment) -> None:
    """Make an approved amendment effective. Never raises: it runs from task handlers and timers."""
    contract = session.get(Contract, amendment.contract_id, with_for_update=True)
    if contract.status not in LIVE:
        _lapse(session, amendment, f"contract is {contract.status}")
        return
    if contract.version != amendment.from_version:
        _lapse(session, amendment, f"contract moved to version {contract.version}")
        return
    try:
        result = plan(session, contract, amendment.kind, amendment.changes, amendment.effective_from, check_dates=False)
    except Problem as exc:  # e.g. more quantity was released while the amendment was in approval
        _lapse(session, amendment, f"no longer applicable: {exc.detail}")
        return
    requested = result["changes"]
    effect: dict = {}
    if amendment.kind == "VARIATION":
        effect = _apply_variation(session, contract, amendment, requested, result)
    elif amendment.kind == "EXTENSION":
        effect = _apply_extension(session, contract, amendment, requested, result)
    elif amendment.kind == "TERMS":
        effect = _apply_terms(session, contract, requested)
    contract.version += 1
    amendment.to_version = contract.version
    amendment.status = "EFFECTIVE"
    if amendment.kind == "TERMINATION":
        effect = _apply_termination(session, contract, amendment, requested)
    audit.record(session, "CONTRACT", contract.id, "AMENDED" if amendment.kind != "TERMINATION" else "TERMINATED_BY_AMENDMENT",
                 object_ref=contract.number, before=amendment.snapshot,
                 after={"amendment": amendment.number, "kind": amendment.kind, "version": contract.version, **result["after"], **effect},
                 reason=amendment.reason, rule_set_version=result["ruleSet"])
    payload = {"amendment": amendment.number, "amendmentId": str(amendment.id), "kind": amendment.kind,
               "fromVersion": amendment.from_version, "toVersion": amendment.to_version,
               "effectiveFrom": amendment.effective_from.isoformat(), "supplierId": str(contract.supplier_id),
               "ownerId": str(contract.owner_id), "changes": requested, "reason": amendment.reason}
    if amendment.kind == "TERMINATION":
        outbox.emit(session, "contract.terminated", "CONTRACT", contract.id, contract.number,
                    {**payload, "forCause": bool(requested.get("forCause")), "openPurchaseOrders": effect.get("flaggedPurchaseOrders", [])})
    else:
        outbox.emit(session, "contract.amended", "CONTRACT", contract.id, contract.number, payload)
        instance = contract_svc._instance(session, contract)
        if instance is not None and instance.status == "RUNNING":
            workflow.step(session, instance, "F4-09", outcome=f"{amendment.number} {amendment.kind.lower()} effective: version {contract.version}")
            workflow.wait(session, instance, "F4-09", outcome="tracking consumption & obligations")


def _apply_variation(session, contract, amendment, requested, result) -> dict:
    lines = _lines(session, contract)
    start = max(amendment.effective_from, contract.valid_from)
    added = []
    for item in requested["lines"]:
        line = lines[int(item["line"])]
        if "unitPriceMinor" in item:
            current = _price_on(session, line, start)
            session.add(PriceValidity(tenant_id=contract.tenant_id, contract_line_id=line.id, valid_from=start, valid_to=contract.valid_to,
                                      unit_price_minor=int(item["unitPriceMinor"]), index_value=current.index_value if current else None,
                                      reason=f"AMENDMENT {amendment.number}"[:60], published=True, created_by=principal(session).user_id))
            added.append({"line": line.line_no, "from": start.isoformat(), "unitPriceMinor": int(item["unitPriceMinor"])})
        if "targetQty" in item:
            line.target_qty = D(item["targetQty"])
    contract.target_value_minor += int(result["valueDeltaMinor"])
    session.flush()
    return {"priceValidityAdded": added}


def _apply_extension(session, contract, amendment, requested, result) -> dict:
    old_to = contract.valid_to
    new_to = date.fromisoformat(requested["validTo"])
    user_id = principal(session).user_id
    for line in contract_svc._lines(session, contract):
        current = _price_on(session, line, old_to)
        if current is not None:
            session.add(PriceValidity(tenant_id=contract.tenant_id, contract_line_id=line.id, valid_from=old_to + timedelta(days=1),
                                      valid_to=new_to, unit_price_minor=current.unit_price_minor, index_value=current.index_value,
                                      reason=f"EXTENSION {amendment.number}"[:60], published=True, created_by=user_id))
    contract.valid_to = new_to
    contract.target_value_minor += int(result["valueDeltaMinor"])
    quota = _extend_quota(session, contract, old_to, new_to)
    # Re-arm the renewal notice and expiry for the new end date.
    _cancel_timers(session, "CONTRACT_RENEWAL", contract.id)
    _cancel_timers(session, "CONTRACT_EXPIRY", contract.id)
    notice = int(rules.resolve(session, "CONTRACT-APPROVAL", company_code=contract.company_code).body["renewalNoticeDays"])
    renewal_at = clock.at_ist(new_to - timedelta(days=notice), 9)
    workflow.create_timer(session, "CONTRACT_RENEWAL", "CONTRACT", contract.id, renewal_at)
    workflow.create_timer(session, "CONTRACT_EXPIRY", "CONTRACT", contract.id, clock.at_ist(new_to + timedelta(days=1), 0, 5))
    if contract.status == "EXPIRING":
        contract_svc.SM.apply(session, contract, "extend", reason=f"extended to {new_to} by {amendment.number}")
    session.flush()
    return {"previousValidTo": old_to.isoformat(), "renewalNoticeAt": renewal_at.isoformat(), "quota": quota}


def _apply_terms(session, contract, requested) -> dict:
    if "paymentTerms" in requested:
        contract.payment_terms = requested["paymentTerms"]
    if "incoterms" in requested:
        contract.incoterms = requested["incoterms"]
    fields = {"over_pct": "over_tolerance_pct", "under_pct": "under_tolerance_pct", "price_pct": "price_tolerance_pct"}
    for key, value in (requested.get("tolerances") or {}).items():
        setattr(contract, fields[key], D(value))
    risk = rules.resolve(session, "CLM-PLAYBOOK").body["positionRisk"]
    clauses = {c.code: c for c in session.execute(select(Clause).where(Clause.contract_id == contract.id)).scalars()}
    for item in requested.get("clauses") or []:
        clause = clauses.get(item["code"])
        if clause is None:
            session.add(Clause(tenant_id=contract.tenant_id, contract_id=contract.id, code=item["code"], title=item["title"],
                               text=item["text"], position=item["position"], risk_score=int(risk[item["position"]]),
                               created_by=principal(session).user_id))
        else:
            clause.text, clause.position, clause.risk_score = item["text"], item["position"], int(risk[item["position"]])
    session.flush()
    return {}


def _apply_termination(session, contract, amendment, requested) -> dict:
    effective = amendment.effective_from
    reason = amendment.reason
    contract_svc.SM.apply(session, contract, "terminate", reason=reason,
                          extra_after={"amendment": amendment.number, "forCause": bool(requested.get("forCause"))})
    contract.terminated_at = clock.now()
    contract.termination_reason = reason
    _cancel_timers(session, "CONTRACT_RENEWAL", contract.id)
    _cancel_timers(session, "CONTRACT_EXPIRY", contract.id)
    for task in session.execute(select(Task).where(Task.kind == "CONTRACT_RENEWAL", Task.object_id == contract.id,
                                                   Task.status == "OPEN")).scalars():
        task.status = "CANCELLED"
        _cancel_timers(session, "TASK_SLA", task.id)
    # Prices stop on the effective date: periods are ended, never re-priced.
    ended = []
    for line in contract_svc._lines(session, contract):
        for validity in session.execute(select(PriceValidity).where(PriceValidity.contract_line_id == line.id,
                                                                    PriceValidity.valid_to >= effective)).scalars():
            if validity.valid_from >= effective:
                validity.published = False
            else:
                validity.valid_to = effective - timedelta(days=1)
            ended.append({"line": line.line_no, "validFrom": validity.valid_from.isoformat(), "validTo": validity.valid_to.isoformat(),
                          "published": validity.published})
    quota = _end_quota(session, contract, effective)
    flagged = _flag_open_pos(session, contract, amendment)
    instance = contract_svc._instance(session, contract)
    if instance is not None and instance.status == "RUNNING":
        workflow.step(session, instance, "F4-09", outcome=f"consumption tracking ended by {amendment.number}")
        workflow.end(session, instance, "F4-10", outcome=f"terminated{' for cause' if requested.get('forCause') else ''} "
                                                         f"from {effective.isoformat()}: {reason}")
    session.flush()
    return {"priceValidityEnded": ended, "quota": quota, "flaggedPurchaseOrders": flagged, "terminatedAt": contract.terminated_at.isoformat()}


def _flag_open_pos(session, contract, amendment) -> list[str]:
    flagged = []
    for po in open_purchase_orders(session, contract):
        audit.record(session, "PURCHASE_ORDER", po.id, "CONTRACT_TERMINATED", object_ref=po.number, reason=amendment.reason,
                     after={"contract": contract.number, "amendment": amendment.number, "effectiveFrom": amendment.effective_from.isoformat(),
                            "poStatus": po.status})
        workflow.start_approval(session, None, PO_REVIEW_KIND, object_type="PURCHASE_ORDER", object_id=po.id, object_ref=po.number,
                                chain=["BUYER"], step_id=None, initiator_id=None, scopes={"BUYER": {"plant": po.plant}},
                                evidence={"contract": contract.number, "amendment": amendment.number, "reason": amendment.reason,
                                          "effectiveFrom": amendment.effective_from.isoformat(), "poStatus": po.status,
                                          "action": "Approve to keep the PO open under the old terms or reject (with comment) to cancel/re-source it"})
        flagged.append(po.number)
    return flagged


@workflow.on_task(PO_REVIEW_KIND)
def _po_reviewed(session: Session, task: Task, outcome: str) -> None:
    audit.record(session, "PURCHASE_ORDER", task.object_id, "TERMINATION_REVIEWED", object_ref=task.object_ref, reason=task.comment,
                 after={"contract": task.evidence.get("contract"), "decision": "KEEP" if outcome == "APPROVED" else "RE-SOURCE"})


# ---------------------------------------------------------------- quota arrangements
def _quota_of(session, contract) -> list[tuple[QuotaArrangement, QuotaLine]]:
    return session.execute(select(QuotaArrangement, QuotaLine).join(QuotaLine, QuotaLine.quota_id == QuotaArrangement.id)
                           .where(QuotaLine.contract_id == contract.id)).all()


def _continue_quota(session, template: QuotaArrangement, start: date, end: date, members: list[tuple[uuid.UUID, uuid.UUID, Decimal, Decimal]]):
    """New arrangement period with the members' shares renormalised to 1 (members: contract, supplier, share, allocated)."""
    total = sum(m[2] for m in members)
    successor = QuotaArrangement(tenant_id=template.tenant_id, material_id=template.material_id, plant=template.plant,
                                 valid_from=start, valid_to=end, source_event_id=template.source_event_id,
                                 created_by=principal(session).user_id)
    session.add(successor)
    session.flush()
    assigned = Decimal(0)
    for index, (contract_id, supplier_id, share, allocated) in enumerate(members):
        part = (Decimal(1) - assigned) if index == len(members) - 1 else (share / total).quantize(Decimal("0.0001"))
        assigned += part
        session.add(QuotaLine(tenant_id=template.tenant_id, quota_id=successor.id, supplier_id=supplier_id, contract_id=contract_id,
                              share=part, allocated_qty=allocated, created_by=principal(session).user_id))
    session.flush()
    return successor


def _end_quota(session, contract, effective: date) -> list[dict]:
    """End every arrangement the contract is part of the day before termination; the other suppliers continue, renormalised."""
    out = []
    for quota, qline in _quota_of(session, contract):
        if quota.valid_to < effective:
            continue
        start = max(effective, quota.valid_from)
        old_to = quota.valid_to
        quota.valid_to = start - timedelta(days=1)
        others = []
        for other in session.execute(select(QuotaLine).where(QuotaLine.quota_id == quota.id, QuotaLine.id != qline.id)).scalars():
            other_contract = session.get(Contract, other.contract_id) if other.contract_id else None
            if other_contract is not None and other_contract.status in LIVE and other_contract.valid_to >= start:
                others.append((other.contract_id, other.supplier_id, other.share, other.allocated_qty or Decimal(0)))
        successor = _continue_quota(session, quota, start, old_to, others) if others else None
        out.append({"quota": str(quota.id), "endedOn": quota.valid_to.isoformat(),
                    "continuedWith": len(others), "successor": str(successor.id) if successor else None})
    session.flush()
    return out


def _extend_quota(session, contract, old_to: date, new_to: date) -> list[dict]:
    """Carry the quota split into the extension period for the contracts that are extended."""
    out = []
    for quota, qline in _quota_of(session, contract):
        if quota.valid_to != old_to:
            continue
        successor = session.execute(select(QuotaArrangement).where(
            QuotaArrangement.material_id == quota.material_id, QuotaArrangement.plant == quota.plant,
            QuotaArrangement.source_event_id == quota.source_event_id, QuotaArrangement.valid_from == old_to + timedelta(days=1))
        ).scalar_one_or_none()
        if successor is None:
            # First contract of the split to be extended: it carries the arrangement alone until the others join.
            successor = _continue_quota(session, quota, old_to + timedelta(days=1), new_to,
                                        [(contract.id, contract.supplier_id, qline.share, Decimal(0))])
            out.append({"quota": str(successor.id), "created": True})
            continue
        members = {l.contract_id: l for l in session.execute(select(QuotaLine).where(QuotaLine.quota_id == successor.id)).scalars()}
        original = {l.contract_id: l.share for l in session.execute(select(QuotaLine).where(QuotaLine.quota_id == quota.id)).scalars()}
        total = sum(original.get(c, Decimal(0)) for c in [*members, contract.id])
        for contract_id, line in members.items():
            line.share = (original.get(contract_id, line.share) / total).quantize(Decimal("0.0001"))
        session.add(QuotaLine(tenant_id=contract.tenant_id, quota_id=successor.id, supplier_id=contract.supplier_id, contract_id=contract.id,
                              share=Decimal(1) - sum(l.share for l in members.values()), allocated_qty=0,
                              created_by=principal(session).user_id))
        successor.valid_to = min(successor.valid_to, new_to)
        out.append({"quota": str(successor.id), "joined": True})
    session.flush()
    return out


# ---------------------------------------------------------------- renewal (F4-10 renew) and read models
def renewal_draft(session: Session, contract: Contract, task: Task) -> Optional[ContractAmendment]:
    """An approved renewal becomes an EXTENSION draft (+12 months unless the rule says otherwise), ready for approval."""
    if contract.status not in LIVE:
        return None
    pending = _pending(session, contract)
    if pending is not None:
        audit.record(session, "CONTRACT", contract.id, "RENEWAL_DRAFT_SKIPPED", object_ref=contract.number,
                     reason=f"{pending.number} is still {pending.status}")
        return None
    rule = rules.resolve(session, "CONTRACT-AMENDMENT", company_code=contract.company_code)
    months = int(rule.body.get("renewalExtensionMonths", 12))
    new_to = add_months(contract.valid_to, months)
    return create(session, contract, kind="EXTENSION", changes={"validTo": new_to.isoformat()},
                  reason=f"Renewal approved ({task.comment or 'renewal notice period reached'}): extend {months} months to {new_to.isoformat()}",
                  effective_from=clock.today(), submit_now=False)


def _user(session: Session, user_id: Optional[uuid.UUID]) -> Optional[dict]:
    if user_id is None:
        return None
    user = session.get(AppUser, user_id)
    return {"id": str(user_id), "name": user.full_name, "email": user.email} if user else {"id": str(user_id)}


def view(session: Session, amendment: ContractAmendment, internal: bool = True) -> dict:
    contract = session.get(Contract, amendment.contract_id)
    out = row(amendment, extra={"contract": contract.number, "requestedBy": _user(session, amendment.requested_by),
                                "approvedBy": _user(session, amendment.approved_by)})
    if internal:
        out["tasks"] = [{"id": str(t.id), "role": t.candidate_role, "status": t.status, "decision": t.decision, "comment": t.comment,
                         "dueAt": t.due_at.isoformat() if t.due_at else None,
                         "completedBy": _user(session, t.completed_by), "completedAt": t.completed_at.isoformat() if t.completed_at else None}
                        for t in _amendment_tasks(session, amendment)]
    else:
        for key in ("requested_by", "approved_by", "requestedBy", "approvedBy"):
            out.pop(key, None)
        out["changes"] = _requested(amendment.changes)
    return out


def listing(session: Session, contract: Contract, internal: bool = True) -> dict:
    query = select(ContractAmendment).where(ContractAmendment.contract_id == contract.id)
    if not internal:
        query = query.where(ContractAmendment.status.in_(("APPROVED", "EFFECTIVE")))
    items = session.execute(query.order_by(ContractAmendment.created_at.desc(), ContractAmendment.id.desc())).scalars().all()
    rule = rules.resolve(session, "CONTRACT-AMENDMENT", company_code=contract.company_code)
    return {"contract": contract.number, "status": contract.status, "version": contract.version,
            "terminatedAt": contract.terminated_at.isoformat() if contract.terminated_at else None,
            "terminationReason": contract.termination_reason,
            "rule": {"ref": rule.ref, "thresholdMinor": rule.body["thresholdMinor"], "noticeDays": rule.body["noticeDays"],
                     "above": rule.body["above"], "below": rule.body["below"], "termination": rule.body["termination"]},
            "items": [view(session, a, internal) for a in items]}


def by_number(session: Session, contract: Contract, number: str, lock: bool = False) -> ContractAmendment:
    query = select(ContractAmendment).where(ContractAmendment.contract_id == contract.id, ContractAmendment.number == number)
    if lock:
        query = query.with_for_update()
    amendment = session.execute(query).scalar_one_or_none()
    if amendment is None:
        raise not_found("Contract amendment", number)
    return amendment
