"""ADM-03 approval-matrix simulation: which rule version and approver chain applies to given inputs.

Read-only. The rule version is chosen by ``rules.resolve`` (most specific scope on the business date) and evaluated with
the same decision functions the services call: ``requisition_chain`` (requisitions, DMN-01), ``band_chain`` (PO and award
approval), ``po_risk`` + ``touchless`` (PO validation, DMN-02). Contract approval/amendment and invoice-tolerance (DMN-03)
logic is inline in the services; it is mirrored here line for line (services/contract.py ``submit``, services/amendments.py
``preview``, services/payables.py ``match``) — keep them in step.

Compare mode evaluates a draft body (not saved) for the same key and inputs next to the resolved version.
"""
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.pic.models import RuleSet
from app.pic.platform import clock, rules
from app.pic.platform.money import line_amount, pct_of
from app.pic.platform.errors import Problem
from app.pic.platform.rules import Rule

KEYS = ("DMN-01", "PO-APPROVAL", "AWARD-APPROVAL", "CONTRACT-APPROVAL", "CONTRACT-AMENDMENT", "DMN-02", "DMN-03")
SCOPE_ALIASES = {"companyCode": "company_code", "plant": "plant", "category": "category", "purchaseType": "purchase_type",
                 "company_code": "company_code", "purchase_type": "purchase_type"}


def _int(inputs: dict, name: str, default: Optional[int] = None) -> int:
    value = inputs.get(name, default)
    if value is None:
        raise Problem(422, "SIMULATION_INPUT", f"Input '{name}' is required", rule_ref="ADM-03")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise Problem(422, "SIMULATION_INPUT", f"Input '{name}' must be an integer amount in minor units (paise)", rule_ref="ADM-03")


def _dec(inputs: dict, name: str, default: str = "0") -> Decimal:
    try:
        return Decimal(str(inputs.get(name, default)))
    except InvalidOperation:
        raise Problem(422, "SIMULATION_INPUT", f"Input '{name}' must be a number", rule_ref="ADM-03")


def _bool(inputs: dict, name: str) -> bool:
    value = inputs.get(name, False)
    return value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes", "y")


def _band(rule: Rule, value_minor: int) -> tuple[int, Optional[int]]:
    for index, band in enumerate(rule.body["bands"]):
        if band["upTo"] is None or value_minor < band["upTo"]:
            return index, band["upTo"]
    return -1, None


def _band_text(index: int, up_to: Optional[int], value: int) -> str:
    bound = "no upper limit" if up_to is None else f"below {up_to} (exclusive)"
    return f"value {value} falls in band {index + 1} ({bound})"


# ---------------------------------------------------------------- evaluators: (rule, inputs, session, scope) -> decision
def _dmn01(rule: Rule, inputs: dict, session: Session, scope: dict) -> dict:
    value = _int(inputs, "valueMinor")
    channel = str(inputs.get("channel", "OTHER")).upper()
    account_type = inputs.get("accountType")
    purchase_type = str(inputs.get("purchaseType") or scope.get("purchase_type") or "STOCK").upper()
    chain = rules.requisition_chain(rule, value, channel, account_type, purchase_type)
    index, up_to = _band(rule, value)
    band = rule.body["bands"][index] if index >= 0 else {}
    reasons = [_band_text(index, up_to, value)]
    if channel in band.get("autoChannels", []):
        reasons.append(f"channel {channel} is auto-approved in this band")
    if account_type == "ASSET" or purchase_type == "ASSET":
        reasons.append(f"asset purchase adds {', '.join(rule.body.get('assetAdds', [])) or 'nothing'}")
    return {"chain": chain, "autoApproved": not chain, "band": index + 1, "bandUpToMinor": up_to,
            "slaBusinessDays": rule.body.get("slaBusinessDays"), "reasons": reasons}


def _po_approval(rule: Rule, inputs: dict, session: Session, scope: dict) -> dict:
    value = _int(inputs, "valueMinor")
    chain = rules.band_chain(rule, value)
    index, up_to = _band(rule, value)
    reasons = [_band_text(index, up_to, value)]
    if _bool(inputs, "priceDeviation"):
        chain = list(dict.fromkeys(chain + rule.body.get("deviationChain", [])))
        reasons.append("price deviation adds the deviation chain")
    return {"chain": chain, "band": index + 1, "bandUpToMinor": up_to, "confirmationSlaHours": rule.body.get("confirmationSlaHours"),
            "reasons": reasons, "note": "Applies only when the PO is not released touchless (simulate DMN-02 for that)."}


def _award(rule: Rule, inputs: dict, session: Session, scope: dict) -> dict:
    value = _int(inputs, "annualValueMinor", inputs.get("valueMinor"))
    not_lowest = _bool(inputs, "notLowest")
    chain = rules.band_chain(rule, value)
    index, up_to = _band(rule, value)
    needs = value >= rule.body["approvalAboveMinor"] or not_lowest
    reasons = [_band_text(index, up_to, value),
               f"approval {'required' if needs else 'not required'}: annual value {'≥' if value >= rule.body['approvalAboveMinor'] else '<'} "
               f"{rule.body['approvalAboveMinor']}" + ("; award is not to the lowest bid" if not_lowest else "")]
    return {"chain": chain if needs else [], "approvalRequired": needs, "band": index + 1, "reasons": reasons}


def _contract(rule: Rule, inputs: dict, session: Session, scope: dict) -> dict:
    value = _int(inputs, "valueMinor")
    non_standard = _bool(inputs, "nonStandardClause")
    large = value >= rule.body["thresholdMinor"]
    chain = list(rule.body["above"]) if (large or non_standard) else list(rule.body["below"])
    reasons = [f"target value {value} {'≥' if large else '<'} threshold {rule.body['thresholdMinor']}"]
    if non_standard:
        reasons.append("a non-standard clause position routes to the 'above' chain")
    return {"chain": chain, "band": "above" if (large or non_standard) else "below", "reasons": reasons}


def _amendment(rule: Rule, inputs: dict, session: Session, scope: dict) -> dict:
    kind = str(inputs.get("kind", "VARIATION")).upper()
    if kind not in ("VARIATION", "EXTENSION", "TERMS", "TERMINATION"):
        raise Problem(422, "SIMULATION_INPUT", "kind must be VARIATION, EXTENSION, TERMS or TERMINATION", rule_ref="ADM-03")
    delta = _int(inputs, "valueDeltaMinor", 0)
    if kind == "TERMINATION":
        band, chain = "termination", list(rule.body["termination"])
        reasons = ["terminations always use the termination chain", f"{rule.body['noticeDays']} days' notice without cause"]
    elif abs(delta) >= int(rule.body["thresholdMinor"]):
        band, chain = "above", list(rule.body["above"])
        reasons = [f"|value change| {abs(delta)} ≥ threshold {rule.body['thresholdMinor']}"]
    else:
        band, chain = "below", list(rule.body["below"])
        reasons = [f"|value change| {abs(delta)} < threshold {rule.body['thresholdMinor']}"]
    return {"chain": chain, "band": band, "reasons": reasons + ["the requester is always excluded from approving"]}


def _dmn02(rule: Rule, inputs: dict, session: Session, scope: dict) -> dict:
    status = str(inputs.get("supplierStatus", "QUALIFIED")).upper()
    value = _int(inputs, "valueMinor")
    late = _dec(inputs, "lateProb")
    split = _bool(inputs, "splitPattern")
    account_changed = _bool(inputs, "accountChanged")
    price_dev = _bool(inputs, "priceDeviation")
    sources = {str(s).upper() for s in (inputs.get("priceSources") or ["CONTRACT"])}
    risk = None
    risk_ref = None
    if inputs.get("riskScore") is not None:
        score = _int(inputs, "riskScore")
    else:
        # Same composition as services/order.py validate(): PO-RISK for the company code, then DMN-02.
        risk_rule = rules.resolve(session, "PO-RISK", scope.get("_on"), company_code=scope.get("company_code"))
        risk_ref = risk_rule.ref
        risk = rules.po_risk(risk_rule, late_prob=late, price_deviation=price_dev, supplier_not_qualified=status not in ("QUALIFIED", "PREFERRED"),
                             value_above_band=value > risk_rule.body["valueBandMinor"], split_pattern=split, account_changed=account_changed,
                             model_version="simulation")
        score = risk["score"]
    decision = rules.touchless(rule, price_sources=sources, supplier_status=status, value_minor=value, split_pattern=split,
                               late_prob=late, risk_score=score, account_changed=account_changed)
    return {"decision": "TOUCHLESS_RELEASE" if decision["touchless"] else "APPROVAL_REQUIRED", "touchless": decision["touchless"],
            "reasons": decision["reasons"] or ["all touchless criteria met"], "riskScore": score,
            "riskFactors": risk["factors"] if risk else None, "riskRuleSet": risk_ref,
            "note": "Touchless release still requires the TOUCHLESS_PO agent at autonomy L4 and within its value limit."}


def _dmn03(rule: Rule, inputs: dict, session: Session, scope: dict) -> dict:
    po_price = _int(inputs, "poUnitPriceMinor")
    inv_price = _int(inputs, "invoiceUnitPriceMinor", po_price)
    qty = _dec(inputs, "invoicedQty", "0")
    available = _dec(inputs, "availableQty", str(qty))
    b = rule.body
    # Same line-level reading as payables.match: variance of the line value against min(pricePct of the line value, priceAbsMinor).
    po_value = line_amount(qty, po_price)
    variance = line_amount(qty, inv_price) - po_value
    price_tol = min(pct_of(po_value, Decimal(str(b["pricePct"]))), int(b["priceAbsMinor"]))
    qty_limit = available * (1 + Decimal(str(b["qtyPct"])) / 100)
    reasons = []
    if abs(variance) > price_tol:
        reasons.append(f"PRICE: line value differs by {variance} (unit {inv_price - po_price}; tolerance {price_tol} = "
                       f"min({b['pricePct']}% of the line, {b['priceAbsMinor']}))")
    if qty > qty_limit:
        reasons.append(f"QUANTITY: billed {qty} > available {available} + {b['qtyPct']}%")
    return {"decision": "EXCEPTION" if reasons else "MATCHED", "priceToleranceMinor": str(price_tol), "qtyLimit": str(qty_limit),
            "reasons": reasons or ["price and quantity within tolerance"],
            "duplicateWindow": {"amountMinor": b.get("dupAmountMinor"), "days": b.get("dupDays")}}


EVALUATORS: dict[str, Callable[[Rule, dict, Session, dict], dict]] = {
    "DMN-01": _dmn01, "PO-APPROVAL": _po_approval, "AWARD-APPROVAL": _award, "CONTRACT-APPROVAL": _contract,
    "CONTRACT-AMENDMENT": _amendment, "DMN-02": _dmn02, "DMN-03": _dmn03,
}


def _candidates(session: Session, key: str, on: date, scope: dict) -> list[dict]:
    rows = session.execute(select(RuleSet).where(RuleSet.key == key, RuleSet.effective_from <= on,
                                                 or_(RuleSet.effective_to.is_(None), RuleSet.effective_to >= on))
                           .order_by(RuleSet.effective_from)).scalars().all()
    out = []
    for rs in rows:
        mismatch = [f for f in rules.SCOPE_FIELDS if getattr(rs, f) is not None and scope.get(f) != getattr(rs, f)]
        out.append({"version": rs.version, "effectiveFrom": rs.effective_from.isoformat(),
                    "effectiveTo": rs.effective_to.isoformat() if rs.effective_to else None,
                    "scope": {f: getattr(rs, f) for f in rules.SCOPE_FIELDS if getattr(rs, f) is not None},
                    "specificity": sum(1 for f in rules.SCOPE_FIELDS if getattr(rs, f) is not None),
                    "applies": not mismatch, "excludedBecause": [f"{f} ≠ {getattr(rs, f)}" for f in mismatch]})
    return out


def simulate(session: Session, key: str, inputs: dict, on: Optional[date] = None, scope: Optional[dict] = None,
             draft_body: Optional[dict] = None) -> dict:
    key = (key or "").upper()
    if key not in EVALUATORS:
        raise Problem(422, "UNKNOWN_RULE_KEY", f"key must be one of {', '.join(KEYS)}", rule_ref="ADM-03")
    on = on or clock.today()
    normalised = {SCOPE_ALIASES[k]: v for k, v in (scope or {}).items() if k in SCOPE_ALIASES and v not in (None, "")}
    try:
        rule = rules.resolve(session, key, on, **normalised)
    except Problem as exc:
        if exc.code != "RULE_SET_MISSING":
            raise
        raise Problem(404, "RULE_SET_MISSING", f"No version of {key} is effective on {on} for scope {normalised or 'tenant default'}",
                      rule_ref="ADM-03")
    context = {**normalised, "_on": on}
    evaluate = EVALUATORS[key]
    try:
        result = evaluate(rule, inputs or {}, session, context)
    except (KeyError, TypeError) as exc:
        raise Problem(422, "RULE_BODY_INCOMPATIBLE", f"Rule {rule.ref} body is missing or has the wrong type for {exc}", rule_ref=rule.ref)
    response: dict[str, Any] = {
        "key": key, "on": on.isoformat(), "scope": normalised, "inputs": inputs or {},
        "resolved": {"ref": rule.ref, "version": rule.version, "body": rule.body,
                     "why": "most specific scope match effective on the date; ties go to the latest effective-from"},
        "candidates": _candidates(session, key, on, normalised),
        "result": result,
    }
    if draft_body is not None:
        if not isinstance(draft_body, dict):
            raise Problem(422, "SIMULATION_INPUT", "draftBody must be a JSON object", rule_ref="ADM-03")
        draft = Rule(key, "draft", draft_body)
        try:
            draft_result = evaluate(draft, inputs or {}, session, context)
        except (KeyError, TypeError) as exc:
            raise Problem(422, "RULE_BODY_INCOMPATIBLE", f"The draft body is missing or has the wrong type for {exc}", rule_ref="ADM-03")
        changed = {k for k in set(result) | set(draft_result) if k != "reasons" and result.get(k) != draft_result.get(k)}
        response["compare"] = {"draft": {"ref": draft.ref, "result": draft_result}, "changed": bool(changed), "changedFields": sorted(changed)}
    return response
