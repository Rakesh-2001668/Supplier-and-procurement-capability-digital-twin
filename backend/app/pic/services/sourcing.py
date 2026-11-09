"""F3 Strategic sourcing → award (M05, Technical Document §9.3).

An event has one or more lines (items). Suppliers bid per line; lines of a lot can also be bid as a bundle (a discount for the whole lot and
an all-or-nothing flag). Evaluation, TCO, scenarios and the award work per line and lot: the award allocates every line to one or more
suppliers and each awarded supplier gets one contract covering its lines. Requirement lines of every event line are moved into sourcing
and closed on award (pending workflows 19-23).
"""
import hashlib
import itertools
import json
import re
import uuid
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.pic.db import current_tenant, tenant_tx
from app.pic.models import (
    AwardDecision, AwardScenario, Bid, BidLine, BidLot, BidOpening, CategoryPlan, Criterion, EvaluatorDeclaration, EventLine, EventLineSource,
    AuditEvent, Evaluation, InfoRecord, Invitee, Material, PrLine, Requisition, Scorecard, SourcingEvent, Supplier, SupplierCategoryStatus, SupplierSegment,
    Task, Timer,
)
from app.pic.platform import abac
from app.pic.platform import agents, audit, clock, crypto, outbox, rules, sod, sourcing_defaults, workflow
from app.pic.platform.core import StateMachine, link, next_number
from app.pic.platform.errors import Problem, illegal_transition, not_found, rule_violation
from app.pic.platform.money import D, fmt_inr
from app.pic.services import auction as auction_svc
from app.pic.services import ind_healthcare
from app.pic.services import risk as risk_svc
from app.pic.services import sourcing_tco as tco_svc
from app.pic.services import supplier as supplier_svc
from app.pic.services.common import category_status, principal, supplier_by_code

PROCESS = "pic.sourcing-award"
SM = StateMachine("SOURCING_EVENT", {
    ("DRAFT", "publish"): "PUBLISHED",
    ("PUBLISHED", "open"): "OPEN",
    ("OPEN", "close"): "CLOSED",
    ("CLOSED", "evaluate"): "UNDER_EVALUATION",
    ("UNDER_EVALUATION", "new_round"): "OPEN",
    ("UNDER_EVALUATION", "propose_award"): "AWARD_PENDING",
    ("AWARD_PENDING", "award"): "AWARDED",
    ("AWARD_PENDING", "reject_award"): "UNDER_EVALUATION",
    ("DRAFT", "cancel"): "CANCELLED",
    ("PUBLISHED", "cancel"): "CANCELLED",
    ("OPEN", "cancel"): "CANCELLED",
    ("UNDER_EVALUATION", "cancel"): "CANCELLED",
    ("CLOSED", "cancel"): "CANCELLED",
    ("AWARD_PENDING", "cancel"): "CANCELLED",  # withdraws the pending award decision and its approval tasks
})
ELIGIBLE = ("QUALIFIED", "PREFERRED")
MAX_EVENT_LINES = 50
LOT_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,19}$")
# Criteria whose score comes from platform data instead of an evaluator (pending workflow 23).
DATA_SOURCES = {"MANUAL": None, "SCORECARD": ("QUALITY", "DELIVERY", "RESPONSIVENESS"), "ESG": ("ESG",), "RISK": ("RISK",)}
AWARD_RISK_RULE = "AWARD-RISK"
AWARD_RISK_DEFAULT = {"maxRiskScore": None, "maxSingleSourcePct": None, "maxConditionalSharePct": None, "noDataScore": 50}
BNB_NODE_LIMIT = 200_000
QUANT4, QUANT3 = Decimal("0.0001"), Decimal("0.001")
EPS = Decimal("1e-9")  # shares are decimal fractions of a division (capacity / quantity): equal within this is equal
EVENT_TYPES = ("RFI", "RFQ", "RFP", "REVERSE_AUCTION")
SCORING_METHODS = ("LOWEST_RATIO", "MIN_MAX", "RANK")
BID_FIELDS = ("line", "unit_price", "freight", "duty", "packaging", "payment_terms_days", "lead_time_days", "capacity_per_month", "currency",
              "incoterm", "origin", "moq", "price_uom", "uom_factor", "tax_included", "tax_rate_pct", "hs_code")
EXCEPTION_NEEDS_RATIONALE = ("NOT_LOWEST", "LIMITED_COMPETITION", "INCOMPLETE_TCO", "UNVERIFIED_CAPACITY", "NEGATIVE_SAVINGS")


# Own number range per event type for new events (flow fixes B6): RFQ keeps the original SOURCING_EVENT range (RFQ-2231 of the
# signature case), the others get their own prefix. A tenant whose ranges predate the split (no row yet) keeps numbering from the
# SOURCING_EVENT range until migration 0024 / reference.ensure_extensions adds them; existing numbers are never renumbered.
EVENT_NUMBER_RANGES = {"RFQ": "SOURCING_EVENT", "RFI": "SOURCING_EVENT_RFI", "RFP": "SOURCING_EVENT_RFP", "REVERSE_AUCTION": "SOURCING_EVENT_AUC"}


def event_number(session: Session, type: str) -> str:
    object_type = EVENT_NUMBER_RANGES.get((type or "").upper(), "SOURCING_EVENT")
    try:
        return next_number(session, object_type)
    except Problem as exc:
        if exc.code != "NUMBER_RANGE_MISSING" or object_type == "SOURCING_EVENT":
            raise
        return next_number(session, "SOURCING_EVENT")


def aware(value: Optional[datetime]) -> Optional[datetime]:
    """A deadline without a zone is read as Indian Standard Time (the business time of the tenant), never compared naive."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=clock.IST)
    return value


def policy_of(session: Session, event: Optional[SourcingEvent] = None, *, category: Optional[str] = None) -> dict:
    return sourcing_defaults.policy(session, category=category or (event.category if event else None)).body


def log_refusal(session: Session, event: SourcingEvent, action: str, reason: str, **after) -> None:
    """A refused attempt (late bid, uninvited or blocked supplier, early access) is audited in its own transaction: the command's own
    transaction is rolled back by the error, and the BP asks for the attempt to be logged."""
    p = principal(session)
    try:
        with tenant_tx(event.tenant_id, p.user_id, p) as s:
            s.execute(text("SET LOCAL lock_timeout = '1500ms'"))  # the caller's transaction may hold the audit chain lock: do not wait for it
            audit.record(s, "SOURCING_EVENT", event.id, action, object_ref=event.number, reason=reason, after=after or None)
    except DBAPIError:
        audit.record(session, "SOURCING_EVENT", event.id, action, object_ref=event.number, reason=reason, after=after or None)


def should_cost(params: dict) -> dict:
    """Parametric should-cost by commodity (die-casting): material + conversion + tooling + packaging, then margin (validated: services/should_cost.py)."""
    from app.pic.services import should_cost as should_cost_svc
    return should_cost_svc.parametric(params)


# ---------------------------------------------------------------- build (F3-01/02)
def _validate_constraints(constraints: dict) -> dict:
    """Share bounds and the risk constraints of the award optimisation (pending workflow 21) are checked when the event is built."""
    def number(key: str, low: Decimal, high: Decimal, whole: bool = False):
        if constraints.get(key) in (None, ""):
            return
        try:
            value = D(constraints[key])
        except Exception:  # noqa: BLE001
            raise Problem(422, "INVALID_CONSTRAINT", f"{key} must be a number", rule_ref="SRC-AWARD-CONSTRAINTS")
        if value < low or value > high or (whole and value != value.to_integral_value()):
            raise Problem(422, "INVALID_CONSTRAINT", f"{key} must be {'a whole number ' if whole else ''}between {low} and {high}",
                          rule_ref="SRC-AWARD-CONSTRAINTS")
    number("max_suppliers", Decimal(1), Decimal(10), True)
    number("max_share", Decimal("0.01"), Decimal(1))
    number("min_share", Decimal(0), Decimal(1))
    number("max_total_suppliers", Decimal(1), Decimal(50), True)
    number("max_risk_score", Decimal(0), Decimal(100), True)
    number("max_single_source_pct", Decimal(1), Decimal(100))
    number("max_conditional_share_pct", Decimal(0), Decimal(100))
    if constraints.get("min_share") not in (None, "") and constraints.get("max_share") not in (None, "") and D(constraints["min_share"]) > D(constraints["max_share"]):
        raise Problem(422, "INVALID_CONSTRAINT", "min_share cannot exceed max_share", rule_ref="SRC-AWARD-CONSTRAINTS")
    return constraints


def _line_sources(data: dict) -> list[dict]:
    if data.get("sources"):
        return [dict(s) for s in data["sources"]]
    if data.get("requisition") is None or data.get("line") is None:
        raise Problem(422, "INVALID_LINES", "Each event line needs a requisition line (requisition and line) or a list of sources", rule_ref="P06")
    return [{"requisition": data["requisition"], "line": data["line"]}]


def _require_lines(lines: list) -> None:
    if not lines:
        raise Problem(422, "INVALID_LINES", "A sourcing event needs at least one requirement line", rule_ref="SRC-LINES")
    if len(lines) > MAX_EVENT_LINES:
        raise Problem(422, "INVALID_LINES", f"A sourcing event has at most {MAX_EVENT_LINES} lines (got {len(lines)}); split it by category or lot",
                      rule_ref="SRC-LINES")


def _check_lots(codes: list[Optional[str]]) -> None:
    counts: dict = {}
    for code in codes:
        if code:
            if not LOT_RE.match(code):
                raise Problem(422, "INVALID_LOT", f"Lot code {code!r} must be 1-20 characters: capitals, digits, - or _", rule_ref="SRC-LOT")
            counts[code] = counts.get(code, 0) + 1
    single = [c for c, n in counts.items() if n == 1]
    if single:
        raise Problem(422, "INVALID_LOT", f"Lot {', '.join(sorted(single))} has a single line; a lot groups at least two lines", rule_ref="SRC-LOT")


def create_event(session: Session, *, type: str, title: str, category: str, lines: list[dict], criteria: list[dict],
                 invitees: list[dict], close_at: datetime, baseline_method: str = "LAST_PRICE",
                 baseline_price_minor: Optional[int] = None, should_cost_params: Optional[dict] = None,
                 constraints: Optional[dict] = None, tco_params: Optional[dict] = None,
                 savings_target_pct: Optional[Decimal] = None, bundle: Optional[dict] = None, scoring_method: str = "LOWEST_RATIO",
                 reference_date: Optional[date] = None, clarification_close_at: Optional[datetime] = None,
                 budget_justification: Optional[str] = None, min_bidders: Optional[int] = None, template_code: Optional[str] = None,
                 cloned_from: Optional[str] = None, should_cost_model: Optional[dict] = None, open_at: Optional[datetime] = None) -> SourcingEvent:
    p = principal(session)
    type = (type or "").upper()
    if type not in EVENT_TYPES:
        raise Problem(422, "INVALID_EVENT_TYPE", f"type must be one of {', '.join(EVENT_TYPES)}", rule_ref="SRC-TYPE")
    title, category = (title or "").strip(), (category or "").strip()
    if not title or len(title) > 200 or not category:
        raise Problem(422, "INVALID_EVENT", "An event needs a title (up to 200 characters) and a category", rule_ref="SRC-MANDATORY")
    scoring_method = (scoring_method or "LOWEST_RATIO").upper()
    if scoring_method not in SCORING_METHODS:
        raise Problem(422, "INVALID_SCORING_METHOD", f"scoring_method must be one of {', '.join(SCORING_METHODS)}", rule_ref="SRC-CRITERIA")
    pol = sourcing_defaults.policy(session, category=category)
    baseline_method = (baseline_method or "LAST_PRICE").upper()
    if baseline_method not in pol.body["baselineMethods"]:
        raise Problem(422, "INVALID_BASELINE_METHOD", f"baseline_method must be one of {', '.join(pol.body['baselineMethods'])}", rule_ref="SRC-BASELINE")
    close_at, clarification_close_at = aware(close_at), aware(clarification_close_at)
    if close_at is None:
        raise Problem(422, "INVALID_EVENT", "An event needs a close time", rule_ref="SRC-MANDATORY")
    if clarification_close_at is not None and clarification_close_at >= close_at:
        raise Problem(422, "INVALID_CLARIFICATION_DEADLINE", "Questions must close before the bid deadline", rule_ref="SRC-CLARIFY")
    open_at = aware(open_at)
    if open_at is not None and (open_at >= close_at or type == "REVERSE_AUCTION"):
        raise Problem(422, "INVALID_OPEN_AT", "A scheduled opening is before the close time and is not available for a live reverse auction", rule_ref="SRC-OPEN")
    if min_bidders is not None and not 1 <= int(min_bidders) <= 20:
        raise Problem(422, "INVALID_EVENT", "min_bidders must be a whole number from 1 to 20", rule_ref="SRC-COMPETITION")
    _require_lines(lines)
    multi = len(lines) > 1 or any(len(_line_sources(l)) > 1 for l in lines) or bundle is not None
    if len(lines) > 1 and type == "REVERSE_AUCTION":
        raise rule_violation("A live reverse auction ranks one price ladder: it runs per item (one event line). Use an RFQ or RFP for several lines",
                             "SRC-AUCTION")
    if len(lines) > 1 and (should_cost_params or should_cost_model):
        raise rule_violation("Should-cost is calculated per item: use a single-line event", "SRC-SHOULDCOST")
    if should_cost_params and should_cost_model:
        raise rule_violation("Give either should_cost_params (parametric die-casting model) or should_cost_model, not both", "SRC-SHOULDCOST")
    _check_lots([l.get("lot") and str(l["lot"]).upper() for l in lines])
    constraints = _validate_constraints(constraints or {"max_suppliers": 2, "max_share": "0.60", "min_share": "0.20"})
    _check_criteria(criteria)
    if len({i["supplier"] for i in invitees}) != len(invitees):
        raise Problem(422, "DUPLICATE_INVITEE", "A supplier can be invited once to an event", rule_ref="SRC-INVITE")
    tco_snapshot = tco_svc.snapshot(session, tco_params)
    reference_date = reference_date or clock.today()
    event = SourcingEvent(
        tenant_id=current_tenant(session), number=event_number(session, type), type=type, title=title,
        category=category, status="DRAFT", owner_id=p.user_id, close_at=close_at, baseline_method=baseline_method,
        constraints=constraints, tco_params=tco_snapshot, savings_target_pct=savings_target_pct,
        should_cost=should_cost(should_cost_params) if should_cost_params else None, scoring_method=scoring_method,
        reference_date=reference_date, clarification_close_at=clarification_close_at, budget_justification=(budget_justification or None), open_at=open_at,
        min_bidders=int(min_bidders) if min_bidders is not None else int(pol.body["minBidders"]), template_code=template_code, cloned_from=cloned_from,
        rule_versions={sourcing_defaults.POLICY_KEY: pol.ref, sourcing_defaults.TCO_KEY: tco_snapshot["_rule"]}, created_by=p.user_id,
    )
    session.add(event)
    session.flush()
    if should_cost_model:
        from app.pic.services import should_cost as should_cost_svc
        event.should_cost = should_cost_svc.evaluate(session, should_cost_model["code"], should_cost_model.get("inputs") or {}, on=reference_date)
    instance = workflow.start(session, PROCESS, "SOURCING_EVENT", event.id, event.number)
    # P06: events start only from approved requirements.
    company_codes, seen, origins, requisitions, purposes, plants = set(), set(), set(), [], [], set()
    baseline_value, baselines_complete, baseline_detail, mismatches = 0, True, [], []
    for index, data in enumerate(lines, start=1):
        sources = []
        for src in _line_sources(data):
            pr = session.execute(select(Requisition).where(Requisition.number == src["requisition"])).scalar_one_or_none()
            if pr is None or pr.status not in ("APPROVED", "PARTIALLY_ORDERED"):
                raise rule_violation(f"Requirement {src['requisition']} is not an approved requisition", "P06")
            pr_line = session.execute(select(PrLine).where(PrLine.requisition_id == pr.id, PrLine.line_no == int(src["line"]))).scalar_one_or_none()
            if pr_line is None:
                raise not_found("Requisition line", f"{pr.number}/{src['line']}")
            if (pr.id, pr_line.line_no) in seen:
                raise rule_violation(f"Requisition line {pr.number}/{pr_line.line_no} is in the event twice", "SRC-BUNDLE")
            seen.add((pr.id, pr_line.line_no))
            line_category = pr_line.category or pr_line.material_group
            if multi:
                if pr_line.sourcing_status != "OPEN":
                    raise rule_violation(f"Requisition line {pr.number}/{pr_line.line_no} is {pr_line.sourcing_status}; bundle only open lines", "SRC-BUNDLE")
            if line_category and line_category != category:
                mismatch = f"Requisition line {pr.number}/{pr_line.line_no} is category {line_category}, not {category}"
                if multi or str(pol.body.get("lineCategoryCheck", "WARN")).upper() == "ENFORCE":
                    raise rule_violation(mismatch, "SRC-BUNDLE")
                mismatches.append(mismatch)  # policy WARN: sourced under the event's category, and the audit trail says so
            if pr.purpose_code and pr.purpose_code not in purposes:
                purposes.append(pr.purpose_code)
            plants.add(pr_line.plant)
            company_codes.add(pr.company_code)
            origins.add(pr.origin)
            if pr.number not in requisitions:
                requisitions.append(pr.number)
            sources.append((pr, pr_line, D(src["qty"]) if src.get("qty") is not None else pr_line.qty))
        if len(company_codes) > 1:
            raise rule_violation("The lines of one sourcing event must belong to one company code (the award contracts are per company code); "
                                 f"got {', '.join(sorted(company_codes))}", "SRC-BUNDLE")
        pr, pr_line = sources[0][0], sources[0][1]
        keys = {(s[1].material_id, s[1].plant, s[1].uom) for s in sources}
        if len(keys) > 1:
            raise rule_violation("Sources merged into one event line must have the same material, plant and unit of measure", "SRC-BUNDLE")
        material = session.get(Material, pr_line.material_id) if pr_line.material_id else None
        lot = str(data["lot"]).upper() if data.get("lot") else None
        line = EventLine(tenant_id=event.tenant_id, event_id=event.id, line_no=index * 10,
                         material_id=material.id if material else None, description=pr_line.description, plant=pr_line.plant,
                         annual_qty=D(data["annual_qty"]), monthly_qty=D(data["monthly_qty"]), uom=pr_line.uom,
                         requisition_id=pr.id, pr_line_no=pr_line.line_no, lot_code=lot, created_by=p.user_id,
                         need_date=min((x[1].need_date for x in sources if x[1].need_date), default=None))
        if line.annual_qty <= 0 or line.monthly_qty <= 0:
            raise Problem(422, "INVALID_LINES", f"Line {index * 10}: annual and monthly quantity must be positive", rule_ref="SRC-LINES")
        session.add(line)
        session.flush()
        for source_pr, source_line, qty in sources:
            session.add(EventLineSource(tenant_id=event.tenant_id, event_line_id=line.id, requisition_id=source_pr.id, pr_line_no=source_line.line_no,
                                        qty=qty, origin=source_pr.origin, created_by=p.user_id))
            source_line.sourcing_status = "IN_SOURCING"
            link(session, "REQUISITION", source_pr.id, source_pr.number, "SOURCING_EVENT", event.id, event.number, "sourced_by",
                 from_line=source_line.line_no, to_line=index * 10)
        line_baseline = data.get("baseline_price_minor")
        if line_baseline is None and len(lines) == 1:
            line_baseline = baseline_price_minor
        if line_baseline is None:
            from app.pic.services import should_cost as should_cost_svc
            found = should_cost_svc.baseline_price(session, baseline_method, material=material, plant=pr_line.plant, category=category,
                                                   should_cost_minor=(event.should_cost or {}).get("unitCostMinor") if len(lines) == 1 else None,
                                                   on=reference_date)
            line_baseline = found["priceMinor"]
            baseline_detail.append({"line": index * 10, "method": baseline_method, **{k: v for k, v in found.items() if k != "priceMinor"}})
        elif int(line_baseline) < 0:
            raise Problem(422, "INVALID_BASELINE", f"Line {index * 10}: the baseline price cannot be negative", rule_ref="SRC-BASELINE")
        line.baseline_price_minor = line_baseline
        if line_baseline is None:
            baselines_complete = False
        else:
            baseline_value += int(Decimal(line_baseline) * line.annual_qty)
    if len(lines) == 1:
        event.baseline_price_minor = session.execute(select(EventLine.baseline_price_minor).where(EventLine.event_id == event.id)).scalar()
    else:
        event.baseline_price_minor = baseline_value if baselines_complete else None  # several lines: the baseline is the annual value
    if multi:
        event.bundle = _bundle_meta(session, bundle, lines, requisitions, origins, category)
    for c in criteria:
        session.add(Criterion(tenant_id=event.tenant_id, event_id=event.id, code=c["code"], name=c["name"], weight=int(c["weight"]),
                              data_source=str(c.get("data_source") or "MANUAL").upper(),
                              min_score=D(c["min_score"]) if c.get("min_score") not in (None, "") else None, created_by=p.user_id))
    for inv in invitees:
        supplier = supplier_by_code(session, inv["supplier"])
        status = category_status(session, supplier.id, category)
        waiver = inv.get("waiver_reason")
        if status not in ELIGIBLE and not (status == "CONDITIONAL" and waiver):
            raise rule_violation(f"{supplier.code} is {status} for {category}; only Qualified suppliers (or Conditional with waiver) may be invited", "P06/SRC-INVITE")
        session.add(Invitee(tenant_id=event.tenant_id, event_id=event.id, supplier_id=supplier.id, category_status=status,
                            waiver_reason=waiver, created_by=p.user_id))
    event.purpose_code = ", ".join(purposes)[:40] or None
    event.need_date = min((l.need_date for l in session.execute(select(EventLine).where(EventLine.event_id == event.id)).scalars() if l.need_date),
                          default=None)
    for plant in sorted(plants):
        abac.guard(session, "SOURCING_CREATE", event, plant=plant, company_code=next(iter(company_codes)))
    session.flush()
    workflow.wait(session, instance, "F3-02", outcome="event drafted; scoring model and invitees set")
    audit.record(session, "SOURCING_EVENT", event.id, "CREATED", object_ref=event.number,
                 after={"type": event.type, "lines": len(lines), "invitees": [i["supplier"] for i in invitees],
                        "baselineMinor": event.baseline_price_minor, "baselineMethod": baseline_method, "baselines": baseline_detail,
                        "shouldCost": event.should_cost, "scoringMethod": scoring_method, "purposeCode": event.purpose_code,
                        "needDate": event.need_date.isoformat() if event.need_date else None,
                        **({"categoryMismatch": mismatches} if mismatches else {}),
                        **({"templateCode": template_code} if template_code else {}), **({"clonedFrom": cloned_from} if cloned_from else {}),
                        **({"bundle": event.bundle} if event.bundle else {})},
                 rule_set_version=";".join(v for _, v in sorted(event.rule_versions.items()))[:80] or None)
    return event


def _bundle_meta(session: Session, bundle: Optional[dict], lines: list, requisitions: list, origins: set, category: str) -> dict:
    kind = (bundle or {}).get("kind") or "PR_LINES"
    ref = (bundle or {}).get("ref")
    if kind not in ("PR_LINES", "MRP_DEMAND", "CATEGORY_PLAN"):
        raise Problem(422, "INVALID_BUNDLE", "bundle kind must be PR_LINES, MRP_DEMAND or CATEGORY_PLAN", rule_ref="SRC-BUNDLE")
    if kind == "MRP_DEMAND" and origins != {"MRP"}:
        raise rule_violation("An MRP-demand bundle takes only requisitions that came from an MRP run", "SRC-BUNDLE")
    plan = None
    if kind == "CATEGORY_PLAN":
        plan = session.execute(select(CategoryPlan).where(CategoryPlan.number == ref)).scalar_one_or_none() if ref else None
        if plan is None:
            raise not_found("Category plan", ref or "")
        if plan.category != category:
            raise rule_violation(f"Category plan {plan.number} is for {plan.category}, not {category}", "SRC-BUNDLE")
    return {"kind": kind, "ref": ref, "requisitions": requisitions, "origins": sorted(origins), "eventLines": len(lines),
            "sourceLines": sum(len(_line_sources(l)) for l in lines), "categoryPlan": plan.number if plan else None}


def _check_criteria(criteria: list[dict]) -> None:
    codes = [str(c.get("code") or "").strip() for c in criteria]
    if any(not code for code in codes) or len(set(codes)) != len(codes):
        raise Problem(422, "INVALID_CRITERION", "Each scoring criterion needs its own code", rule_ref="SRC-CRITERIA")
    for c in criteria:
        try:
            weight = Decimal(str(c.get("weight")))
            valid_weight = not isinstance(c.get("weight"), bool) and weight == weight.to_integral_value() and 0 <= weight <= 100
        except Exception:  # noqa: BLE001
            valid_weight = False
        if not valid_weight:
            raise Problem(422, "INVALID_CRITERION", f"Criterion {c.get('code')}: the weight is a whole number from 0 to 100", rule_ref="SRC-WEIGHTS")
        if c.get("min_score") not in (None, ""):
            try:
                minimum = D(c["min_score"])
            except Exception:  # noqa: BLE001
                minimum = Decimal(-1)
            if not Decimal(0) <= minimum <= Decimal(100) or str(c.get("code")) == "PRICE_TCO":
                raise Problem(422, "INVALID_CRITERION", f"Criterion {c.get('code')}: min_score is a score from 0 to 100 and does not apply to PRICE_TCO",
                              rule_ref="SRC-CRITERIA")
        source = str(c.get("data_source") or "MANUAL").upper()
        if source not in DATA_SOURCES:
            raise Problem(422, "INVALID_CRITERION", f"data_source must be one of {', '.join(DATA_SOURCES)}", rule_ref="SRC-CRITERIA")
        allowed = DATA_SOURCES[source]
        if allowed is not None and c["code"] not in allowed:
            raise Problem(422, "INVALID_CRITERION", f"Criterion {c['code']} cannot take its score from {source}; {source} feeds {', '.join(allowed)}",
                          rule_ref="SRC-CRITERIA")
        if source != "MANUAL" and c["code"] == "PRICE_TCO":
            raise Problem(422, "INVALID_CRITERION", "PRICE_TCO is always calculated from the bids", rule_ref="SRC-CRITERIA")


def _criteria(session: Session, event: SourcingEvent) -> list[Criterion]:
    return session.execute(select(Criterion).where(Criterion.event_id == event.id)).scalars().all()


def _require_eligible(session: Session, event: SourcingEvent, supplier: Supplier, action: str) -> None:
    """Category status (BLOCKED included) is re-checked when a supplier bids or is awarded, like auction.place_bid."""
    invitee = session.execute(select(Invitee).where(Invitee.event_id == event.id, Invitee.supplier_id == supplier.id)).scalar_one_or_none()
    status = category_status(session, supplier.id, event.category)
    if status not in ELIGIBLE and not (status == "CONDITIONAL" and invitee is not None and invitee.waiver_reason):
        raise rule_violation(f"{supplier.code} is {status} for {event.category} and cannot {action}", "P06/SRC-INVITE")


def _published_lines(session: Session, event: SourcingEvent) -> list[dict]:
    lines = _lines(session, event)
    if len(lines) == 1:
        return [{"material": str(lines[0].material_id), "annualQty": str(lines[0].annual_qty)}]
    # Several lines: the savings tracker follows the event on an annual-value basis (baseline value, award value), not per unit.
    return [{"material": None, "annualQty": "1", "aggregate": True,
             "itemLines": [{"line": l.line_no, "material": str(l.material_id) if l.material_id else None, "annualQty": str(l.annual_qty),
                            "lot": l.lot_code} for l in lines]}]


def category_budget_check(session: Session, event: SourcingEvent, lines: list[EventLine], mode: str) -> dict:
    """Budget check of the Draft to Published guard (TD 6.1): the value the event is expected to award above what its requirements already
    commit, against the category plan's remaining budget (rule CATEGORY-BUDGET semantics: the committed spend of the requisition module).
    HARD: refused above 100 %. SOFT: refused without a justification. No approved plan with a budget: not applicable."""
    from app.pic.services import requisition as requisition_svc

    if mode == "OFF":
        return {"outcome": "OFF"}
    fiscal_year = clock.fiscal_year(clock.today())
    plan = session.execute(select(CategoryPlan).where(CategoryPlan.category == event.category, CategoryPlan.fiscal_year == fiscal_year,
                                                      CategoryPlan.status == "APPROVED", CategoryPlan.budget_minor.is_not(None))
                           .order_by(CategoryPlan.created_at.desc()).limit(1).with_for_update()).scalar_one_or_none()
    if plan is None:
        return {"outcome": "NOT_APPLICABLE", "fiscalYear": fiscal_year}
    estimate, requirement = Decimal(0), Decimal(0)
    for line in lines:
        sources = line_sources(session, line)
        source_value = Decimal(0)
        for requisition_id, pr_line_no in sources:
            pr_line = session.execute(select(PrLine).where(PrLine.requisition_id == requisition_id, PrLine.line_no == pr_line_no)).scalar_one_or_none()
            if pr_line is not None:
                source_value += Decimal(pr_line.price_est_minor) * pr_line.qty
        requirement += source_value
        estimate += (Decimal(line.baseline_price_minor) * line.annual_qty) if line.baseline_price_minor else source_value
    incremental = max(Decimal(0), estimate - requirement)
    committed = requisition_svc.category_committed(session, {event.category}, fiscal_year)[event.category]
    projected = Decimal(committed) + incremental
    used = (projected * 100 / Decimal(plan.budget_minor)).quantize(Decimal("0.1")) if plan.budget_minor > 0 else Decimal(999)
    result = {"outcome": "OK" if projected <= plan.budget_minor else "EXCEEDED", "fiscalYear": fiscal_year, "plan": plan.number, "mode": mode,
              "budgetMinor": plan.budget_minor, "committedMinor": int(committed), "eventEstimateMinor": int(estimate), "requirementsMinor": int(requirement),
              "incrementalMinor": int(incremental), "projectedMinor": int(projected), "usedPct": str(used)}
    if result["outcome"] == "EXCEEDED":
        message = (f"{event.category}: the event takes the {fiscal_year} category budget ({plan.number}) to {used}% "
                   f"(committed {int(committed)} + above-requirement {int(incremental)} of {plan.budget_minor} paise)")
        if mode == "HARD":
            raise Problem(422, "CATEGORY_BUDGET_EXCEEDED", f"{message}; hard stop", rule_ref="SRC-BUDGET", budget=result)
        if not (event.budget_justification or "").strip():
            raise Problem(422, "BUDGET_JUSTIFICATION_REQUIRED", f"{message}; add a budget justification to the event", rule_ref="SRC-BUDGET", budget=result)
        result["outcome"] = "EXCEEDED_JUSTIFIED"
        result["justification"] = event.budget_justification.strip()
    return result


def publish_checks(session: Session, event: SourcingEvent, lines: list[EventLine], pol: dict) -> dict:
    """The guards of Draft to Published (TD 6.1) that depend on the policy: purpose code (P01), mandatory fields of the event type, how long the
    event stays open, the clarification deadline, close time against the need date and the budget. Returns the findings kept in the audit trail."""
    findings: dict = {}
    if not event.purpose_code:
        codes = []
        for line in lines:
            for requisition_id, _ in line_sources(session, line):
                code = session.get(Requisition, requisition_id).purpose_code
                if code and code not in codes:
                    codes.append(code)
        event.purpose_code = ", ".join(codes)[:40] or None
    if not event.purpose_code:
        raise rule_violation("A sourcing event needs the purpose code of the requirements it sources", "P01")
    missing = [f for f in (pol.get("mandatoryFields") or {}).get(event.type, []) if not getattr(event, f, None)]
    if missing:
        raise Problem(422, "MANDATORY_FIELDS", f"{event.type} needs {', '.join(missing)} before it is published", rule_ref="SRC-MANDATORY", fields=missing)
    open_hours = int((pol.get("minOpenHours") or {}).get(event.type, 0))
    if open_hours and event.close_at - clock.now() < timedelta(hours=open_hours):
        raise rule_violation(f"A {event.type} stays open at least {open_hours} hours: close no earlier than "
                             f"{(clock.now() + timedelta(hours=open_hours)).astimezone(clock.IST).strftime('%d %b %Y %H:%M')} IST", "SRC-OPEN-HOURS")
    hours = int(pol.get("clarificationCloseHours") or 0)
    if event.clarification_close_at is None and hours:
        event.clarification_close_at = event.close_at - timedelta(hours=hours)
    if event.clarification_close_at is not None and event.clarification_close_at >= event.close_at:
        raise rule_violation("Questions must close before the bid deadline", "SRC-CLARIFY")
    if event.clarification_close_at is not None and event.clarification_close_at <= clock.now():
        raise rule_violation("The clarification deadline must be in the future when the event is published", "SRC-CLARIFY")
    if event.need_date is not None and event.close_at.astimezone(clock.IST).date() >= event.need_date:
        if event.need_date >= clock.today():
            raise rule_violation(f"Bids close on {event.close_at.astimezone(clock.IST).date()}, on or after the need date {event.need_date}: "
                                 "there is no time left to award, contract and deliver", "SRC-NEEDDATE")
        findings["needDateAlreadyPassed"] = event.need_date.isoformat()  # the requirement is already late: sourcing it is not refused, the audit trail says so
    event.budget_check = category_budget_check(session, event, lines, str(pol.get("budgetCheck", "SOFT")).upper())
    findings["budget"] = event.budget_check.get("outcome")
    invited = session.execute(select(func.count()).select_from(Invitee).where(Invitee.event_id == event.id)).scalar()
    minimum = int(event.min_bidders or pol.get("minBidders", 1))
    if invited < minimum and event.type != "RFI":
        findings["fewerInviteesThanMinBidders"] = {"invited": invited, "minBidders": minimum}
    return findings


def publish(session: Session, event: SourcingEvent) -> SourcingEvent:
    auction_svc._require_manager(session, event)
    abac.guard(session, "SOURCING_MANAGE", event)
    if not SM.can(event.status, "publish"):
        raise illegal_transition("Sourcing event", event.number, event.status, "publish")
    lines = _lines(session, event)
    _require_lines(lines)
    _check_lots([l.lot_code for l in lines])
    criteria = _criteria(session, event)
    weights = sum(c.weight for c in criteria)
    if weights != 100:
        raise rule_violation(f"Scoring weights must sum to 100 (currently {weights})", "SRC-WEIGHTS")
    if event.type in ("RFQ", "REVERSE_AUCTION") and not any(c.code == "PRICE_TCO" and c.weight > 0 for c in criteria):
        raise rule_violation(f"A {event.type} is awarded on price: include the PRICE_TCO criterion with a weight above zero", "SRC-CRITERIA")
    if not session.execute(select(Invitee).where(Invitee.event_id == event.id)).first():
        raise rule_violation("Invite at least one qualified supplier", "P06")
    if event.close_at <= clock.now():
        raise rule_violation("Close time must be in the future", "SRC-CLOSE")
    pol = policy_of(session, event)
    findings = publish_checks(session, event, lines, pol)
    event.min_bidders = int(event.min_bidders or pol.get("minBidders", 1))
    if event.type == "REVERSE_AUCTION":
        auction_svc.on_publish(session, event)  # freeze AUCTION settings, start the live clock
    event.weights_locked = True
    event.published_at = clock.now()
    audit.record(session, "SOURCING_EVENT", event.id, "PUBLISH_CHECKED", object_ref=event.number,
                 after={"purposeCode": event.purpose_code, "needDate": event.need_date.isoformat() if event.need_date else None,
                        "clarificationCloseAt": event.clarification_close_at.isoformat() if event.clarification_close_at else None,
                        "budget": event.budget_check, "minBidders": event.min_bidders, **findings},
                 rule_set_version=(event.rule_versions or {}).get(sourcing_defaults.POLICY_KEY))
    SM.apply(session, event, "publish", reason="weights locked")
    scheduled = event.open_at is not None and event.open_at > clock.now()
    if scheduled:
        # Published but not open: suppliers see the requirement and may ask questions; bids are accepted from open_at (timer SOURCING_OPEN).
        workflow.create_timer(session, "SOURCING_OPEN", "SOURCING_EVENT", event.id, event.open_at, {"round": event.round})
    else:
        SM.apply(session, event, "open")
    workflow.create_timer(session, "SOURCING_CLOSE", "SOURCING_EVENT", event.id, event.close_at, {"round": event.round})
    outbox.emit(session, "sourcing.event.published", "SOURCING_EVENT", event.id, event.number,
                {"category": event.category, "baselineMinor": event.baseline_price_minor, "closeAt": event.close_at.isoformat(),
                 "lines": _published_lines(session, event), "type": event.type,
                 "openAt": event.open_at.isoformat() if event.open_at else None, "inviteeSupplierIds": _invitee_ids(session, event)})
    instance = workflow.find(session, "SOURCING_EVENT", event.id, PROCESS)
    workflow.step(session, instance, "F3-02", outcome="published; weights locked")
    workflow.wait(session, instance, "F3-03", outcome=(f"round {event.round}: live reverse auction until {event.close_at.isoformat()} (soft close)"
                                                       if event.type == "REVERSE_AUCTION" else
                                                       f"round {event.round}: opens {event.open_at.isoformat()}, bids sealed until {event.close_at.isoformat()}" if scheduled else
                                                       f"round {event.round}: bids sealed until {event.close_at.isoformat()}"))
    return event


@workflow.on_timer("SOURCING_OPEN")
def _open_timer(session: Session, timer) -> None:
    """Scheduled opening: a published event starts accepting bids at its open time."""
    event = session.get(SourcingEvent, timer.object_id)
    if event and event.status == "PUBLISHED" and timer.payload.get("round") == event.round and clock.now() >= event.open_at:
        SM.apply(session, event, "open", reason="scheduled opening")
        audit.record(session, "SOURCING_EVENT", event.id, "OPENED_FOR_BIDS", object_ref=event.number, after={"openAt": event.open_at.isoformat()})


def _lines(session: Session, event: SourcingEvent) -> list[EventLine]:
    return session.execute(select(EventLine).where(EventLine.event_id == event.id).order_by(EventLine.line_no)).scalars().all()


def is_multi(session: Session, event: SourcingEvent) -> bool:
    return len(_lines(session, event)) > 1


def line_sources(session: Session, line: EventLine) -> list[tuple[uuid.UUID, int]]:
    """The requisition lines behind an event line (the line's own requisition for events made before sources were kept)."""
    found = [(s.requisition_id, s.pr_line_no) for s in session.execute(select(EventLineSource).where(EventLineSource.event_line_id == line.id)
                                                                      .order_by(EventLineSource.pr_line_no)).scalars()]
    if not found and line.requisition_id is not None and line.pr_line_no is not None:
        found = [(line.requisition_id, line.pr_line_no)]
    return found


# ---------------------------------------------------------------- sealed bids (F3-03)
def _bid_gate(session: Session, event: SourcingEvent, supplier: Supplier, action: str) -> Invitee:
    """The checks every supplier command on a sealed event shares. A refused attempt is logged in its own transaction."""
    if event.status != "OPEN":
        log_refusal(session, event, f"{action.upper()}_REFUSED", f"event is {event.status}", supplier=supplier.code)
        raise illegal_transition("Sourcing event", event.number, event.status, action)
    if event.type == "REVERSE_AUCTION":
        raise Problem(409, "USE_AUCTION_BIDDING", f"{event.number} is a live reverse auction; bid through /auction/bids", rule_ref="SRC-AUCTION")
    if clock.now() >= event.close_at:
        log_refusal(session, event, f"LATE_{action.upper()}_REFUSED", f"closed at {event.close_at.isoformat()}", supplier=supplier.code,
                    attemptedAt=clock.now().isoformat())
        raise Problem(409, "EVENT_CLOSED", f"{event.number} closed at {event.close_at.isoformat()}")
    invitee = session.execute(select(Invitee).where(Invitee.event_id == event.id, Invitee.supplier_id == supplier.id)).scalar_one_or_none()
    if invitee is None:
        log_refusal(session, event, f"UNINVITED_{action.upper()}_REFUSED", "supplier is not an invitee", supplier=supplier.code)
        raise Problem(403, "NOT_INVITED", f"{supplier.code} is not invited to {event.number}")
    if session.execute(select(Bid.id).where(Bid.event_id == event.id, Bid.supplier_id == supplier.id, Bid.status == "DISQUALIFIED").limit(1)).first():
        log_refusal(session, event, f"DISQUALIFIED_{action.upper()}_REFUSED", "supplier was disqualified from this event", supplier=supplier.code)
        raise Problem(403, "DISQUALIFIED", f"{supplier.code} was disqualified from {event.number} and cannot bid again", rule_ref="SRC-DISQUALIFY")
    try:
        _require_eligible(session, event, supplier, action)
    except Problem as exc:
        log_refusal(session, event, f"INELIGIBLE_{action.upper()}_REFUSED", exc.detail if hasattr(exc, "detail") else str(exc), supplier=supplier.code)
        raise
    return invitee


def submit_bid(session: Session, event: SourcingEvent, supplier: Supplier, lines: list[dict], lots: Optional[list[dict]] = None,
               valid_until: Optional[date] = None) -> Bid:
    """A sealed bid. Submitting again before the close replaces the earlier bid of the round (the number of edits is kept); a withdrawn bid can be
    re-submitted. Nothing of the commercial content is readable until the close: only the hash is stored in clear."""
    p = principal(session)
    _bid_gate(session, event, supplier, "bid")
    event_lines = _lines(session, event)
    pol = policy_of(session, event)
    lines, lots = _check_bid_lines(session, event, event_lines, lines, lots or [], pol)
    if valid_until is not None:
        if valid_until <= event.close_at.astimezone(clock.IST).date():
            raise Problem(422, "INVALID_BID_VALIDITY", f"{event.number}: the offer must stay valid beyond the close date "
                          f"{event.close_at.astimezone(clock.IST).date().isoformat()}", rule_ref="SRC-BID")
        if (valid_until - clock.today()).days > int(pol["maxValidityDays"]):
            raise Problem(422, "INVALID_BID_VALIDITY", f"{event.number}: an offer is valid at most {pol['maxValidityDays']} days", rule_ref="SRC-BID")
    body = {"lines": lines}
    if lots:
        body["lots"] = lots
    if valid_until is not None:
        body["valid_until"] = valid_until.isoformat()
    payload = json.dumps(body, sort_keys=True, default=str)
    previous = session.execute(select(Bid).where(Bid.event_id == event.id, Bid.supplier_id == supplier.id,
                                                 Bid.round == event.round).with_for_update()).scalar_one_or_none()
    edited = False
    if previous:
        edited = previous.status in ("SEALED", "WITHDRAWN")
        previous.sealed_payload = crypto.encrypt(event.tenant_id, f"bid:{event.id}", payload)
        previous.payload_hash = hashlib.sha256(payload.encode()).hexdigest()
        previous.submitted_at = clock.now()
        previous.submitted_by = p.user_id
        previous.status, previous.withdrawn_at, previous.withdrawn_reason = "SEALED", None, None
        previous.edits = (previous.edits or 0) + 1
        bid = previous
    else:
        bid = Bid(tenant_id=event.tenant_id, event_id=event.id, supplier_id=supplier.id, round=event.round,
                  sealed_payload=crypto.encrypt(event.tenant_id, f"bid:{event.id}", payload),
                  payload_hash=hashlib.sha256(payload.encode()).hexdigest(), status="SEALED", submitted_at=clock.now(),
                  submitted_by=p.user_id, created_by=p.user_id)
        session.add(bid)
    session.flush()
    audit.record(session, "SOURCING_EVENT", event.id, "BID_REPLACED" if edited else "BID_SUBMITTED", object_ref=event.number,
                 after={"supplier": supplier.code, "round": event.round, "hash": bid.payload_hash, "lines": len(lines), "edits": bid.edits,
                        **({"lots": [l["lot"] for l in lots]} if lots else {})})
    outbox.emit(session, "sourcing.bid.submitted", "SOURCING_EVENT", event.id, event.number,
                {"supplier": supplier.code, "round": event.round})
    return bid


def withdraw_bid(session: Session, event: SourcingEvent, supplier: Supplier, reason: str) -> Bid:
    """The supplier withdraws its sealed bid before the close (the bid is not opened and not evaluated; it can bid again until the close)."""
    p = principal(session)
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for withdrawing the bid", rule_ref="SRC-BID")
    _bid_gate(session, event, supplier, "withdraw")
    bid = session.execute(select(Bid).where(Bid.event_id == event.id, Bid.supplier_id == supplier.id, Bid.round == event.round)
                          .with_for_update()).scalar_one_or_none()
    if bid is None or bid.status != "SEALED":
        raise Problem(409, "NO_BID_TO_WITHDRAW", f"{supplier.code} has no sealed bid in round {event.round} of {event.number}")
    bid.status, bid.withdrawn_at, bid.withdrawn_reason = "WITHDRAWN", clock.now(), reason
    bid.sealed_payload = None  # the content is destroyed: a withdrawn bid is never opened
    session.flush()
    audit.record(session, "SOURCING_EVENT", event.id, "BID_WITHDRAWN", object_ref=event.number, reason=reason,
                 after={"supplier": supplier.code, "round": event.round, "hash": bid.payload_hash})
    outbox.emit(session, "sourcing.bid.withdrawn", "SOURCING_EVENT", event.id, event.number, {"supplier": supplier.code, "round": event.round})
    return bid


def _finite(value, name: str, bad) -> Decimal:
    try:
        number = D(value)
    except (TypeError, ValueError, ArithmeticError):
        raise bad(f"{name} must be a number")
    if not number.is_finite():
        raise bad(f"{name} must be a finite number")
    return number


def _check_bid_lines(session: Session, event: SourcingEvent, event_lines: list[EventLine], lines: list[dict], lots: list[dict],
                     pol: dict) -> tuple[list[dict], list[dict]]:
    """Well-formed bid lines (a malformed sealed bid would otherwise only fail at close). A single-line event, or one that sets
    ``require_all_lines``, needs a price for every line; otherwise a supplier may bid some lines. Lot terms (bundle discount, all-or-nothing)
    need a price for every line of the lot. Prices must be plausible against the line's baseline (a misplaced decimal point is refused, not
    ranked), in one currency per bid that has a rate on the event's pricing date.
    Returns the normalised lines (only the known fields) and the lot terms."""
    line_nos = [l.line_no for l in event_lines]
    by_no = {l.line_no: l for l in event_lines}

    def bad(detail: str) -> Problem:
        return Problem(422, "INVALID_BID_LINES", f"{event.number}: {detail}", rule_ref="SRC-BID")

    if not lines:
        raise bad("a bid needs one line per event line" if len(line_nos) == 1 else "a bid needs at least one line")
    from app.pic.models import Currency
    known_currencies = set(session.execute(select(Currency.code).where(Currency.active.is_(True))).scalars())
    band = pol.get("priceBand") or {}
    max_price = Decimal(str(band.get("maxUnitPriceMinor", 10 ** 12)))
    on = event.reference_date or clock.today()
    seen, clean_lines, currencies = [], [], set()
    for data in lines:
        if not isinstance(data, dict):
            raise bad("each bid line is an object")
        try:
            line_no = int(data["line"])
            terms, lead = int(data["payment_terms_days"]), int(data["lead_time_days"])
            price_value = data["unit_price"]
        except (KeyError, TypeError, ValueError, ArithmeticError):
            raise bad("each bid line needs line, unit_price, payment_terms_days and lead_time_days as numbers")
        price = _finite(price_value, "unit_price", bad)
        extras = {}
        for key in ("freight", "duty", "packaging"):
            if data.get(key) not in (None, ""):
                extras[key] = _finite(data[key], key, bad)
                if extras[key] < 0:
                    raise bad(f"line {line_no}: {key} cannot be negative")
        capacity = _finite(data["capacity_per_month"], "capacity_per_month", bad) if data.get("capacity_per_month") not in (None, "") else None
        moq = _finite(data["moq"], "moq", bad) if data.get("moq") not in (None, "") else None
        if line_no not in line_nos:
            raise bad(f"line {line_no} is not a line of the event (lines: {', '.join(str(n) for n in line_nos)})")
        if line_no in seen:
            raise bad(f"line {line_no} is bid twice")
        if price <= 0 or terms < 0 or lead < 0 or (capacity is not None and capacity < 0) or (moq is not None and moq < 0):
            raise bad(f"line {line_no}: unit price must be positive; terms, lead time, capacity and MOQ cannot be negative")
        if terms > int(pol["maxPaymentTermsDays"]) or lead > int(pol["maxLeadTimeDays"]):
            raise bad(f"line {line_no}: payment terms are at most {pol['maxPaymentTermsDays']} days and lead time at most {pol['maxLeadTimeDays']} days")
        if moq is not None and capacity is not None and moq > capacity:
            raise bad(f"line {line_no}: the minimum order quantity {moq} is above the offered capacity {capacity}")
        currency = str(data.get("currency") or "INR").upper()
        if currency not in known_currencies and currency != "INR":
            raise bad(f"line {line_no}: currency {currency} is not set up for this tenant")
        currencies.add(currency)
        incoterm = str(data.get("incoterm") or "").upper() or None
        if incoterm and incoterm not in tco_svc.INCOTERMS:
            raise bad(f"line {line_no}: incoterm {incoterm} is unknown (use {', '.join(tco_svc.INCOTERMS)})")
        origin = str(data.get("origin") or "").upper() or None
        if origin and origin not in ("DOMESTIC", "IMPORT"):
            raise bad(f"line {line_no}: origin is DOMESTIC or IMPORT")
        factor = _finite(data["uom_factor"], "uom_factor", bad) if data.get("uom_factor") not in (None, "") else None
        if factor is not None and factor <= 0:
            raise bad(f"line {line_no}: uom_factor must be positive")
        tax_rate = _finite(data["tax_rate_pct"], "tax_rate_pct", bad) if data.get("tax_rate_pct") not in (None, "") else None
        if tax_rate is not None and not Decimal(0) <= tax_rate <= Decimal(50):
            raise bad(f"line {line_no}: tax_rate_pct is from 0 to 50")
        if data.get("tax_included") and tax_rate is None:
            raise bad(f"line {line_no}: the price includes tax: give tax_rate_pct")
        hs = str(data.get("hs_code") or "") or None
        if hs and not (hs.isdigit() and 2 <= len(hs) <= 10):
            raise bad(f"line {line_no}: hs_code is 2 to 10 digits")
        # plausibility: unit price in INR per base unit against the line's baseline
        try:
            rate, _ = tco_svc.fx_rate_on(session, currency, on)
        except tco_svc.TcoInputError as exc:
            raise bad(f"line {line_no}: {exc}")
        in_inr = price * 100 * rate / (factor or Decimal(1))
        if in_inr > max_price:
            raise bad(f"line {line_no}: the unit price is above the limit of {int(max_price) // 100:,} rupees per unit; check the decimal point")
        baseline = by_no[line_no].baseline_price_minor
        if baseline:
            low, high = Decimal(str(band.get("minVsBaseline", "0"))) * baseline, Decimal(str(band.get("maxVsBaseline", "1000000"))) * baseline
            if not low <= in_inr <= high:
                raise bad(f"line {line_no}: the unit price is {(in_inr / baseline).quantize(Decimal('0.01'))} times the baseline; outside "
                          f"{band.get('minVsBaseline')} to {band.get('maxVsBaseline')} times it is refused as an input error (check the decimal point and the unit)")
        seen.append(line_no)
        item = {"line": line_no, "unit_price": str(price), "payment_terms_days": terms, "lead_time_days": lead}
        for key, value in (("freight", extras.get("freight")), ("duty", extras.get("duty")), ("packaging", extras.get("packaging")),
                           ("capacity_per_month", capacity), ("moq", moq), ("uom_factor", factor), ("tax_rate_pct", tax_rate)):
            if value is not None:
                item[key] = str(value)
        for key, value in (("currency", currency if currency != "INR" else None), ("incoterm", incoterm), ("origin", origin), ("hs_code", hs),
                           ("price_uom", (str(data["price_uom"])[:5] if data.get("price_uom") else None))):
            if value:
                item[key] = value
        if data.get("tax_included"):
            item["tax_included"] = True
        clean_lines.append(item)
    if len(currencies) > 1:
        raise bad(f"a bid is quoted in one currency (got {', '.join(sorted(currencies))}); submit a single currency")
    missing = [n for n in line_nos if n not in seen]
    if missing and (len(line_nos) == 1 or event.constraints.get("require_all_lines")):
        raise bad(f"no bid for line(s) {', '.join(str(n) for n in missing)}")
    lot_lines: dict = {}
    for l in event_lines:
        if l.lot_code:
            lot_lines.setdefault(l.lot_code, []).append(l.line_no)
    clean, seen_lots = [], set()
    for entry in lots:
        try:
            code = str(entry["lot"]).upper()
            discount = D(entry.get("discount_pct") or 0)
            all_or_nothing = bool(entry.get("all_or_nothing"))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            raise bad("each lot term needs lot, discount_pct and all_or_nothing")
        if code not in lot_lines:
            raise bad(f"lot {code} is not a lot of the event (lots: {', '.join(sorted(lot_lines)) or 'none'})")
        if code in seen_lots:
            raise bad(f"lot {code} appears twice")
        if not discount.is_finite() or discount < 0 or discount >= 100:
            raise bad(f"lot {code}: the discount must be at least 0 and below 100 percent")
        absent = [n for n in lot_lines[code] if n not in seen]
        if (discount > 0 or all_or_nothing) and absent:
            raise Problem(422, "INCOMPLETE_LOT", f"{event.number}: lot {code} terms (discount or all-or-nothing) need a price for every line of the lot; "
                          f"missing line(s) {', '.join(str(n) for n in absent)}", rule_ref="SRC-LOT")
        seen_lots.add(code)
        if discount > 0 or all_or_nothing:
            clean.append({"lot": code, "discount_pct": str(discount), "all_or_nothing": all_or_nothing})
    return clean_lines, clean


def bids_view(session: Session, event: SourcingEvent) -> list[dict]:
    """Commercial bid content. Before the opening the attempt is blocked and logged (§11.4)."""
    if event.status in ("DRAFT", "PUBLISHED", "OPEN") or event.unsealed_at is None:
        log_refusal(session, event, "BID_ACCESS_DENIED", "bids are sealed until close" if event.status != "CLOSED" else "bids are sealed until two people open them")
        raise Problem(423, "BIDS_SEALED", f"Bids for {event.number} stay sealed until {event.close_at.isoformat()}"
                      + (" and are then opened by two people" if event.status == "CLOSED" else ""), rule_ref="SRC-SEALED")
    abac.guard(session, "SOURCING_MANAGE", event)
    return evaluation_matrix(session, event)


def two_person_opening(session: Session, event: SourcingEvent) -> bool:
    return bool(policy_of(session, event).get("twoPersonOpening")) or bool((event.constraints or {}).get("two_person_opening"))


def close(session: Session, event: SourcingEvent, by_timer: bool = False) -> dict:
    if not by_timer:
        auction_svc._require_manager(session, event)  # the close timer (system) closes on time without an owner check
        abac.guard(session, "SOURCING_MANAGE", event)
    closes_at = auction_svc.ends_at(event)  # a reverse auction may have been extended (soft close)
    if clock.now() < closes_at:
        raise Problem(409, "CLOSE_TIME_NOT_REACHED", f"{event.number} closes at {closes_at.isoformat()}")
    SM.apply(session, event, "close")
    event.closed_at = clock.now()
    if event.type == "REVERSE_AUCTION":
        auction_svc.to_sealed_bids(session, event)  # last auction prices become sealed bids for the normal evaluation
    if two_person_opening(session, event):
        # Opening ceremony: the event stays CLOSED and every bid sealed until two different people have opened them (open_bids).
        event.opening = {"required": True, "round": event.round, "openers": []}
        audit.record(session, "SOURCING_EVENT", event.id, "AWAITING_OPENING", object_ref=event.number,
                     after={"round": event.round, "sealedBids": session.execute(select(func.count()).select_from(Bid).where(
                         Bid.event_id == event.id, Bid.round == event.round, Bid.status == "SEALED")).scalar()},
                     reason="two-person bid opening: the bids stay sealed until two people open them")
        instance = workflow.find(session, "SOURCING_EVENT", event.id, PROCESS)
        workflow.step(session, instance, "F3-03", outcome=f"round {event.round} closed; waiting for the two-person bid opening")
        workflow.wait(session, instance, "F3-03", outcome=f"round {event.round}: bids closed, waiting for the two-person opening")
        return {"event": event.number, "unsealed": 0, "awaitingOpening": True, "matrix": [], "aiRef": None}
    return _open_and_evaluate(session, event)


def open_bids(session: Session, event: SourcingEvent) -> dict:
    """Bid opening ceremony (two-person rule): each call records one opener; the second different opener unseals the bids and starts the evaluation."""
    p = principal(session)
    if event.status != "CLOSED" or not (event.opening or {}).get("required"):
        raise illegal_transition("Sourcing event", event.number, event.status, "open bids")
    abac.guard(session, "SOURCING_MANAGE", event)
    already = session.execute(select(BidOpening).where(BidOpening.event_id == event.id, BidOpening.round == event.round,
                                                       BidOpening.user_id == p.user_id)).scalar_one_or_none()
    if already is not None:
        raise Problem(409, "ALREADY_OPENED_BY_YOU", "You have already opened these bids: a second, different person must open them too", rule_ref="SRC-OPENING")
    session.add(BidOpening(tenant_id=event.tenant_id, event_id=event.id, round=event.round, user_id=p.user_id, opened_at=clock.now(), created_by=p.user_id))
    session.flush()
    openers = session.execute(select(BidOpening.user_id).where(BidOpening.event_id == event.id, BidOpening.round == event.round)).scalars().all()
    event.opening = {**event.opening, "openers": [str(u) for u in openers]}
    audit.record(session, "SOURCING_EVENT", event.id, "BIDS_OPEN_WITNESS", object_ref=event.number, after={"round": event.round, "opener": p.email,
                                                                                                         "openers": len(openers)})
    if len(openers) < 2:
        return {"event": event.number, "unsealed": 0, "openers": len(openers), "remaining": 2 - len(openers), "awaitingOpening": True}
    return _open_and_evaluate(session, event)


def _open_and_evaluate(session: Session, event: SourcingEvent) -> dict:
    pol = policy_of(session, event)
    unsealed = _unseal(session, event)
    event.competitive = len(_latest_bids(session, event)) >= int(event.min_bidders or pol.get("minBidders", 1))
    SM.apply(session, event, "evaluate")
    outbox.emit(session, "sourcing.bids.unsealed", "SOURCING_EVENT", event.id, event.number,
                {"round": event.round, "bids": unsealed, "competitive": event.competitive, "minBidders": event.min_bidders})
    instance = workflow.find(session, "SOURCING_EVENT", event.id, PROCESS)
    workflow.step(session, instance, "F3-03", outcome=f"round {event.round} closed; {unsealed} bid(s) unsealed")
    matrix = evaluation_matrix(session, event)
    ai_ref = (agents.log_run(session, "BID_ANALYSIS", object_type="SOURCING_EVENT", object_id=event.id, object_ref=event.number,
                            inputs={"round": event.round}, evidence=[m["supplier"] for m in matrix],
                            output={"ranking": [(m["supplier"], m["tcoMinor"]) for m in matrix],
                                    "shouldCostMinor": (event.should_cost or {}).get("unitCostMinor")},
                            confidence=0.85, action_taken="DRAFTED")
             if agents.permit(session, "BID_ANALYSIS", object_type="SOURCING_EVENT", object_id=event.id, object_ref=event.number, required_level="L2", sod_action="BID_SCORE", sod_refs={"event_id": event.id}) else None)
    multi = is_multi(session, event)
    workflow.step(session, instance, "F3-04", outcome=("annual TCO: " if multi else "TCO: ") + ", ".join(
        f"{m['supplier']} {m['priceMinor']/100:.2f}→{m['tcoMinor']/100:.2f}" for m in matrix))
    workflow.wait(session, instance, "F3-05", outcome="another round or proceed to award scenarios")
    return {"event": event.number, "unsealed": unsealed, "competitive": event.competitive, "matrix": matrix, "aiRef": ai_ref,
            **({"lineMatrix": line_matrix(session, event)} if multi else {})}


@workflow.on_timer("SOURCING_CLOSE")
def _close_timer(session: Session, timer) -> None:
    event = session.get(SourcingEvent, timer.object_id)
    # An extended auction leaves earlier close timers behind; only the one at or after the live end closes it.
    if event and event.status == "OPEN" and timer.payload.get("round") == event.round and clock.now() >= auction_svc.ends_at(event):
        close(session, event, by_timer=True)


def _audit_key_mismatch(session: Session, event: SourcingEvent) -> None:
    """FIELD_KEY_MISMATCH on the event, once (the same shape as finance_controls.supplier_gstin): in its own transaction so it outlives the failed command, in
    the caller's session when the audit-chain lock is held. Never the ciphertext."""
    def exists(s: Session) -> bool:
        return s.execute(select(AuditEvent.seq).where(AuditEvent.object_type == "SOURCING_EVENT", AuditEvent.object_id == event.id,
                                                      AuditEvent.action == "FIELD_KEY_MISMATCH").limit(1)).first() is not None

    p = session.info.get("principal")
    if p is None or exists(session):
        return
    reason = "sealed bids cannot be opened with the configured PIC_FIELD_KEY"
    try:
        with tenant_tx(p.tenant_id, p.user_id, p) as s:
            s.execute(text("SET LOCAL lock_timeout = '1500ms'"))
            if not exists(s):
                audit.record(s, "SOURCING_EVENT", event.id, "FIELD_KEY_MISMATCH", object_ref=event.number, after={"round": event.round}, reason=reason)
    except DBAPIError:
        audit.record(session, "SOURCING_EVENT", event.id, "FIELD_KEY_MISMATCH", object_ref=event.number, after={"round": event.round}, reason=reason)


def policy_summary(session: Session, event: SourcingEvent) -> dict:
    """The policy values the screens need next to an event (so the UI does not read the admin rules): limits of a bid and an auction, award rules."""
    rule = sourcing_defaults.policy(session, category=event.category)
    keys = ("minBidders", "maxExtensions", "priceBand", "minRationaleChars", "twoPersonOpening", "requireAllCriteriaScored", "minOpenHours", "clarificationCloseHours",
            "leadTimeCheck", "budgetCheck", "unverifiedCapacity", "incompleteTcoNeedsRationale", "unverifiedCapacityNeedsRationale",
            "limitedCompetitionNeedsRationale", "maxLeadTimeDays", "maxPaymentTermsDays", "maxValidityDays", "tieBreak", "baselineMethods")
    return {"rule": rule.ref, **{k: rule.body[k] for k in keys if k in rule.body}, "twoPersonOpeningForThisEvent": two_person_opening(session, event)}


def _unseal(session: Session, event: SourcingEvent) -> int:
    count = 0
    params = tco_svc.effective(event.tco_params)
    on = event.reference_date or (event.published_at.astimezone(clock.IST).date() if event.published_at else clock.today())
    lines = {l.line_no: l for l in _lines(session, event)}
    lot_codes = {l.lot_code for l in lines.values() if l.lot_code}
    for bid in session.execute(select(Bid).where(Bid.event_id == event.id, Bid.round == event.round,
                                                 Bid.status == "SEALED").order_by(Bid.submitted_at, Bid.id)).scalars():
        try:
            payload = json.loads(crypto.decrypt(event.tenant_id, f"bid:{event.id}", bid.sealed_payload))
        except Exception as exc:  # noqa: BLE001 - InvalidToken or an unknown key id: the bid cannot be opened with this configuration
            _audit_key_mismatch(session, event)
            raise Problem(503, "FIELD_KEY_MISMATCH", f"The sealed bids of {event.number} cannot be opened with the configured PIC_FIELD_KEY: it differs from the key "
                          "they were encrypted with. Restore the original key (or re-encrypt with tools/reencrypt.py); nothing was opened and no data was changed",
                          rule_ref="SEC-FIELD") from None
        if hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest() != bid.payload_hash:
            raise Problem(500, "BID_INTEGRITY", "Bid content does not match its submission hash")
        supplier = session.get(Supplier, bid.supplier_id)
        valid, rejected, seen = 0, [], set()
        if payload.get("valid_until"):
            bid.valid_until = date.fromisoformat(payload["valid_until"])
        for data in payload.get("lines") or []:
            # Bids are validated on submission; a malformed or foreign line (e.g. from an older submission) is skipped and
            # recorded instead of failing the close for every bidder.
            try:
                event_line = lines.get(int(data["line"]))
                if event_line is None or event_line.id in seen:
                    raise ValueError("unknown or duplicate line")
                components = {k: str(data.get(k) or 0) for k in ("freight", "duty", "packaging")}
                material = session.get(Material, event_line.material_id) if event_line.material_id else None
                norm = tco_svc.normalise_price(session, data, on, params)
                if norm["minor"] <= 0:
                    raise ValueError("unit price must be positive")
                origin = str(data.get("origin") or ("IMPORT" if (supplier.country or "IN") != "IN" else "DOMESTIC")).upper()
                hs_code = data.get("hs_code") or (material.hsn_code if material else None)
                result = tco_svc.compute(
                    session, params=event.tco_params, supplier_id=bid.supplier_id, category=event.category, price_minor=norm["minor"],
                    price_exact=norm["exact"], lead_time_days=int(data["lead_time_days"]), payment_terms_days=int(data["payment_terms_days"]),
                    annual_qty=event_line.annual_qty, material=material,
                    freight=D(data["freight"]) if data.get("freight") not in (None, "") else None,
                    duty=D(data["duty"]) if data.get("duty") not in (None, "") else None,
                    packaging=D(data["packaging"]) if data.get("packaging") not in (None, "") else None,
                    incoterm=data.get("incoterm"), origin=origin, hs_code=hs_code)
                if result["totalMinor"] <= 0:
                    raise ValueError("the total cost of ownership is not positive")
                line = BidLine(tenant_id=event.tenant_id, bid_id=bid.id, event_line_id=event_line.id,
                               unit_price_minor=norm["minor"], tco_components=components,
                               payment_terms_days=int(data["payment_terms_days"]), lead_time_days=int(data["lead_time_days"]),
                               offered_capacity_per_month=D(data["capacity_per_month"]) if data.get("capacity_per_month") else None,
                               price_quoted_minor=norm["quotedMinor"], currency=norm["currency"], fx_rate=norm["fxRate"], fx_date=norm["fxDate"],
                               incoterm=(data.get("incoterm") or None), origin=origin, moq=D(data["moq"]) if data.get("moq") else None,
                               price_uom=data.get("price_uom"), uom_factor=D(data["uom_factor"]) if data.get("uom_factor") else None,
                               tax_included=bool(data.get("tax_included")), tax_rate_pct=D(data["tax_rate_pct"]) if data.get("tax_rate_pct") else None,
                               hs_code=hs_code, created_by=bid.submitted_by)
            except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError) as exc:  # TcoInputError is a ValueError
                rejected.append({"line": data.get("line") if isinstance(data, dict) else None, "error": str(exc)[:200]})
                continue
            line.tco_minor, line.tco_breakdown = result["totalMinor"], result["parts"]
            line.tco_incomplete, line.tco_trace = result["incomplete"], [*result["trace"], {"component": "normalisation", "steps": norm["steps"]},
                                                                      {"component": "rounding", "valueMinor": result["rounding"]}]
            session.add(line)
            seen.add(event_line.id)
            valid += 1
        if valid == 0:
            bid.status = "INVALID"
            audit.record(session, "SOURCING_EVENT", event.id, "BID_INVALID", object_ref=event.number,
                         after={"supplier": supplier.code, "round": event.round, "rejectedLines": rejected},
                         reason="sealed bid has no valid line for this event; it is not evaluated")
            continue
        if rejected:
            audit.record(session, "SOURCING_EVENT", event.id, "BID_LINES_SKIPPED", object_ref=event.number,
                         after={"supplier": supplier.code, "round": event.round, "rejectedLines": rejected})
        for entry in payload.get("lots") or []:
            try:
                code = str(entry["lot"]).upper()
                if code in lot_codes and {l.id for l in lines.values() if l.lot_code == code} <= seen:
                    session.add(BidLot(tenant_id=event.tenant_id, bid_id=bid.id, lot_code=code, discount_pct=D(entry.get("discount_pct") or 0),
                                       all_or_nothing=bool(entry.get("all_or_nothing")), created_by=bid.submitted_by))
            except (KeyError, TypeError, ValueError, ArithmeticError):
                continue
        bid.status = "UNSEALED"
        bid.auto_scores = _auto_scores(session, event, bid.supplier_id)
        count += 1
    # Earlier rounds are superseded by the latest bid per supplier.
    for bid in session.execute(select(Bid).where(Bid.event_id == event.id, Bid.round < event.round, Bid.status == "UNSEALED")).scalars():
        if session.execute(select(Bid).where(Bid.event_id == event.id, Bid.supplier_id == bid.supplier_id, Bid.round == event.round,
                                             Bid.status == "UNSEALED")).first():  # an invalid re-bid keeps the earlier valid bid
            bid.status = "SUPERSEDED"
    event.unsealed_at = clock.now()
    session.flush()
    audit.record(session, "SOURCING_EVENT", event.id, "BIDS_UNSEALED", object_ref=event.number,
                 after={"round": event.round, "bids": count, "openers": (event.opening or {}).get("openers") or []},
                 reason="close time reached" if not (event.opening or {}).get("required") else "two-person opening")
    return count


# ---------------------------------------------------------------- data-driven criteria (ESG, risk, scorecard)
def award_risk_rule(session: Session) -> dict:
    try:
        return {**AWARD_RISK_DEFAULT, **rules.resolve(session, AWARD_RISK_RULE).body}
    except Problem as exc:
        if exc.code != "RULE_SET_MISSING":
            raise
        return dict(AWARD_RISK_DEFAULT)


def _auto_scores(session: Session, event: SourcingEvent, supplier_id: uuid.UUID) -> dict:
    """Scores of the data-driven criteria, taken at close from the scorecard, the accepted ESG assessment and the open risk signals, and
    kept on the bid (so a later change in the data does not move an evaluated award). Missing data scores the rule's ``noDataScore``."""
    wanted = [c for c in _criteria(session, event) if c.data_source != "MANUAL"]
    if not wanted:
        return {}
    from app.pic.services import supplier_mgmt

    no_data = Decimal(str(award_risk_rule(session)["noDataScore"]))
    supplier = session.get(Supplier, supplier_id)
    cards = session.execute(select(Scorecard).where(Scorecard.supplier_id == supplier_id).order_by(Scorecard.period.desc()).limit(3)).scalars().all()
    out = {}
    for criterion in wanted:
        score, inputs, source = None, {}, criterion.data_source
        if criterion.data_source == "SCORECARD":
            if criterion.code == "DELIVERY":
                values = [Decimal(c.otif_pct) for c in cards if c.otif_pct is not None]
                if values:
                    score, inputs = sum(values) / len(values), {"otifPct": str(sum(values) / len(values)), "periods": [c.period for c in cards]}
            elif criterion.code == "QUALITY":
                values = [Decimal(c.ppm) for c in cards if c.ppm is not None]
                if values:
                    limit = Decimal(str(rules.resolve(session, "SUPPLIER-RISK").body["maxPpm"]))
                    avg = sum(values) / len(values)
                    score, inputs = max(Decimal(0), Decimal(100) - avg * 50 / limit), {"ppm": str(avg), "maxPpm": str(limit)}
            elif criterion.code == "RESPONSIVENESS":
                invited = sum(c.rfq_invited for c in cards)
                if invited:
                    rate = Decimal(sum(c.rfq_responded for c in cards)) * 100 / invited
                    score, inputs = rate, {"rfqResponseRatePct": str(rate.quantize(Decimal("0.1"))), "invited": invited}
        elif criterion.data_source == "ESG":
            assessment = supplier_mgmt.current_assessment(session, supplier_id, "ESG")
            if assessment is not None:
                score, inputs = Decimal(assessment.score), {"assessmentAsOf": str(assessment.as_of), "score": str(assessment.score)}
        elif criterion.data_source == "RISK":
            risk = risk_svc.supplier_risk_score(session, supplier)
            score, inputs = Decimal(100 - risk["score"]), {"riskScore": risk["score"], "level": risk["level"],
                                                          "signals": [f["evidence"] for f in risk["factors"]][:5]}
        out[criterion.code] = {"score": str((score if score is not None else no_data).quantize(Decimal("0.01"))), "source": source,
                               "noData": score is None, "inputs": inputs}
    return out


# ---------------------------------------------------------------- evaluation matrix
def _latest_bids(session: Session, event: SourcingEvent) -> list[Bid]:
    return session.execute(select(Bid).where(Bid.event_id == event.id, Bid.status == "UNSEALED")).scalars().all()


def _line_row(line: BidLine, event_line: EventLine, twin) -> dict:
    capacity = min([c for c in (line.offered_capacity_per_month, twin.free_capacity_per_month if twin else None) if c is not None], default=None)
    missing = [t["component"] for t in (line.tco_trace or []) if t.get("status") == "MISSING"]
    return {"line": event_line.line_no, "eventLineId": str(event_line.id), "lot": event_line.lot_code, "priceMinor": line.unit_price_minor,
            "tcoMinor": line.tco_minor, "tco": line.tco_breakdown, "tcoTrace": line.tco_trace or [], "leadTimeDays": line.lead_time_days,
            "paymentTermsDays": line.payment_terms_days, "verifiedCapacityPerMonth": str(capacity) if capacity is not None else None,
            "capacityVerified": capacity is not None, "moq": str(line.moq) if line.moq is not None else None,
            "twinCapacityPerMonth": str(twin.free_capacity_per_month) if twin and twin.free_capacity_per_month is not None else None,
            "currency": line.currency or "INR", "quotedPriceMinor": line.price_quoted_minor, "fxRate": str(line.fx_rate) if line.fx_rate is not None else None,
            "incoterm": line.incoterm, "origin": line.origin, "tcoIncomplete": bool(line.tco_incomplete), "tcoMissing": missing}


def price_scores(method: str, values: list[int]) -> list[Decimal]:
    """The price score (0..100) of each total cost in ``values`` (all bids on one line). LOWEST_RATIO: lowest / this x 100 (the lowest scores 100);
    MIN_MAX: (highest - this) / (highest - lowest) x 100 (all equal: 100); RANK: 100 x (n - rank + 1) / n with rank 1 + the number of cheaper bids."""
    if not values:
        return []
    low, high, n = min(values), max(values), len(values)
    out = []
    for value in values:
        if method == "MIN_MAX":
            out.append(Decimal(100) if high == low else Decimal(high - value) * 100 / Decimal(high - low))
        elif method == "RANK":
            rank = 1 + sum(1 for v in values if v < value)
            out.append(Decimal(100) * (n - rank + 1) / n)
        else:
            out.append(Decimal(low) / Decimal(value) * 100)
    return out


def evaluation_matrix(session: Session, event: SourcingEvent) -> list[dict]:
    """The normalised comparison of the valid bids: total cost of ownership per line, price score by the event's scoring method, the manual and
    data-driven scores, the weighted score, the technical gate and the ranking. Equal total cost is ranked by the weighted score, then by the
    earlier submission, then by supplier code (so the order never depends on how the rows were read)."""
    criteria = _criteria(session, event)
    bids = _latest_bids(session, event)
    event_lines = _lines(session, event)
    multi = len(event_lines) > 1
    by_id = {l.id: l for l in event_lines}
    method = event.scoring_method or "LOWEST_RATIO"
    rows = []
    for bid in bids:
        supplier = session.get(Supplier, bid.supplier_id)
        bid_lines = {by_id[bl.event_line_id].line_no: bl for bl in session.execute(select(BidLine).where(BidLine.bid_id == bid.id)).scalars()
                     if bl.event_line_id in by_id}
        if not bid_lines:
            continue  # a bid without a valid line for the evaluated item is not ranked (see _unseal)
        twin = supplier_svc.twin(session, bid.supplier_id, event.category)
        lots = [{"lot": b.lot_code, "discountPct": str(b.discount_pct), "allOrNothing": b.all_or_nothing}
                for b in session.execute(select(BidLot).where(BidLot.bid_id == bid.id).order_by(BidLot.lot_code)).scalars()]
        line_rows = [_line_row(bid_lines[l.line_no], l, twin) for l in event_lines if l.line_no in bid_lines]
        base = {"supplier": supplier.code, "supplierId": str(supplier.id), "round": bid.round, "bidId": str(bid.id),
                "submittedAt": bid.submitted_at.isoformat(), "validUntil": bid.valid_until.isoformat() if bid.valid_until else None,
                "lateDeliveryProb": str(twin.late_delivery_prob) if twin else None, "lines": line_rows, "lots": lots,
                "autoScores": bid.auto_scores or {}, "basis": "ANNUAL_VALUE" if multi else "UNIT",
                "coverage": {"bid": len(line_rows), "of": len(event_lines)}, "complete": len(line_rows) == len(event_lines),
                "tcoIncomplete": any(r["tcoIncomplete"] for r in line_rows),
                "tcoMissing": sorted({m for r in line_rows for m in r["tcoMissing"]})}
        if not multi:
            first = line_rows[0]
            rows.append({**base, "priceMinor": first["priceMinor"], "tcoMinor": first["tcoMinor"], "tco": first["tco"], "tcoTrace": first["tcoTrace"],
                         "leadTimeDays": first["leadTimeDays"], "paymentTermsDays": first["paymentTermsDays"],
                         "verifiedCapacityPerMonth": first["verifiedCapacityPerMonth"], "capacityVerified": first["capacityVerified"],
                         "moq": first["moq"],
                         "shouldCostDeltaMinor": first["priceMinor"] - event.should_cost["unitCostMinor"] if event.should_cost else None})
        else:
            annual = {l.line_no: l.annual_qty for l in event_lines}
            rows.append({**base, "priceMinor": int(sum(Decimal(r["priceMinor"]) * annual[r["line"]] for r in line_rows)),
                         "tcoMinor": int(sum(Decimal(r["tcoMinor"]) * annual[r["line"]] for r in line_rows)),
                         "leadTimeDays": max(r["leadTimeDays"] for r in line_rows),
                         "paymentTermsDays": min(r["paymentTermsDays"] for r in line_rows),
                         "verifiedCapacityPerMonth": None, "capacityVerified": all(r["capacityVerified"] for r in line_rows), "moq": None,
                         "shouldCostDeltaMinor": None})
    if rows:
        rounds = {b.id: b.round for b in session.execute(select(Bid).where(Bid.event_id == event.id)).scalars()}
        # price score per line against the other bids on that line; a supplier's price score is the value-weighted mean over all lines
        line_score: dict = {}
        best_line = {}
        for l in event_lines:
            entries = [(r["supplierId"], r_l["tcoMinor"]) for r in rows for r_l in r["lines"] if r_l["line"] == l.line_no]
            best_line[l.line_no] = min((t for _, t in entries), default=None)
            scored = price_scores(method, [t for _, t in entries])
            for (sid, _), value in zip(entries, scored):
                line_score[(sid, l.line_no)] = value
        weight_line = {l.line_no: Decimal(best_line[l.line_no] or 0) * l.annual_qty for l in event_lines}
        total_weight = sum(weight_line.values()) or Decimal(1)
        for r in rows:
            line_price_scores = {r_l["line"]: line_score[(r["supplierId"], r_l["line"])] for r_l in r["lines"]}
            if multi:
                price_score = sum(weight_line[n] * s_ for n, s_ in line_price_scores.items()) / total_weight
            else:
                price_score = next(iter(line_price_scores.values()))
            scores = {"PRICE_TCO": price_score}
            # Manual scores belong to the supplier in this event, not to one round's bid: an evaluator's latest score per criterion
            # (on any of the supplier's bids) carries over to the bid of a new negotiation round.
            latest: dict = {}
            for ev in session.execute(select(Evaluation).join(Bid, Bid.id == Evaluation.bid_id).where(
                    Evaluation.event_id == event.id, Bid.supplier_id == uuid.UUID(r["supplierId"]))).scalars():
                key = (ev.criterion_code, ev.evaluator_id)
                if key not in latest or (rounds.get(ev.bid_id, 0), ev.updated_at or ev.created_at) > (
                        rounds.get(latest[key].bid_id, 0), latest[key].updated_at or latest[key].created_at):
                    latest[key] = ev
            for ev in latest.values():
                scores.setdefault(ev.criterion_code, [])
                if isinstance(scores[ev.criterion_code], list):
                    scores[ev.criterion_code].append(ev.score)
            for code, auto in (r["autoScores"] or {}).items():
                scores[code] = Decimal(auto["score"])
            final = {k: (sum(v) / len(v) if isinstance(v, list) and v else v) for k, v in scores.items()}
            weighted = sum(Decimal(c.weight) * Decimal(final.get(c.code, 0)) / 100 for c in criteria)
            r["scores"] = {k: str(Decimal(v).quantize(Decimal("0.01"))) for k, v in final.items() if not isinstance(v, list)}
            r["weightedScore"] = str(weighted.quantize(Decimal("0.01")))
            r["priceScore"] = str(Decimal(price_score).quantize(Decimal("0.01")))
            r["evaluators"] = len({ev_id for (_, ev_id) in latest})
            # criteria nobody scored yet count as zero in the weighted score; they are listed so nobody mistakes the zero for a judgement
            r["unscored"] = sorted(c.code for c in criteria if c.code != "PRICE_TCO" and c.weight > 0 and c.code not in final)
            failed = sorted(c.code for c in criteria if c.min_score is not None and c.code in final and Decimal(final[c.code]) < c.min_score)
            pending = sorted(c.code for c in criteria if c.min_score is not None and c.code not in final)
            r["technicalGate"] = {"passed": not failed, "failed": failed, "pending": pending,
                                  "thresholds": {c.code: str(c.min_score) for c in criteria if c.min_score is not None}}
            # the weighted score of each line: that line's price score with the supplier's other criteria
            for r_l in r["lines"]:
                other = sum(Decimal(c.weight) * Decimal(final.get(c.code, 0)) / 100 for c in criteria if c.code != "PRICE_TCO")
                price_weight = next((Decimal(c.weight) for c in criteria if c.code == "PRICE_TCO"), Decimal(0))
                r_l["weightedScore"] = str((price_weight * line_price_scores[r_l["line"]] / 100 + other).quantize(Decimal("0.01")))
    rows.sort(key=lambda r: ((not r["complete"]) if multi else False, r["tcoMinor"], -Decimal(r.get("weightedScore", "0")), r["submittedAt"], r["supplier"]))
    for rank, r in enumerate(rows, start=1):
        r["rank"] = rank
        r["tiedWithPrevious"] = rank > 1 and rows[rank - 2]["tcoMinor"] == r["tcoMinor"]
    return rows


def line_matrix(session: Session, event: SourcingEvent) -> list[dict]:
    """Per event line: every bid on the line ranked by TCO (the evaluation matrix by line)."""
    matrix = evaluation_matrix(session, event)
    out = []
    for line in _lines(session, event):
        entries = sorted(({"supplier": r["supplier"], "supplierId": r["supplierId"], "priceMinor": l["priceMinor"], "tcoMinor": l["tcoMinor"],
                           "leadTimeDays": l["leadTimeDays"], "paymentTermsDays": l["paymentTermsDays"],
                           "verifiedCapacityPerMonth": l["verifiedCapacityPerMonth"], "weightedScore": l.get("weightedScore")}
                          for r in matrix for l in r["lines"] if l["line"] == line.line_no), key=lambda e: e["tcoMinor"])
        for rank, entry in enumerate(entries, start=1):
            entry["rank"] = rank
        out.append({"line": line.line_no, "description": line.description, "lot": line.lot_code, "uom": line.uom, "annualQty": str(line.annual_qty),
                    "monthlyQty": str(line.monthly_qty), "baselineMinor": line.baseline_price_minor, "bids": entries})
    return out


def declare_conflict(session: Session, event: SourcingEvent, has_conflict: bool, declaration: str) -> EvaluatorDeclaration:
    """The evaluator's conflict-of-interest declaration for this event (BP M05 SRC-05). Required before the user scores; a user who declares a
    conflict is barred from scoring and from proposing the award of the event. A declaration can be tightened (no conflict to conflict), never relaxed."""
    p = principal(session)
    text_ = (declaration or "").strip()
    if len(text_) < 10:
        raise Problem(422, "DECLARATION_REQUIRED", "Write the declaration: say whether you have any personal or financial interest in a bidder", rule_ref="SRC-05")
    existing = session.execute(select(EvaluatorDeclaration).where(EvaluatorDeclaration.event_id == event.id,
                                                                  EvaluatorDeclaration.user_id == p.user_id)).scalar_one_or_none()
    if existing is not None:
        if existing.has_conflict and not has_conflict:
            raise Problem(409, "CONFLICT_STANDS", "A declared conflict of interest cannot be withdrawn; ask the event owner to replace the evaluator", rule_ref="SRC-05")
        existing.has_conflict, existing.declaration, existing.declared_at = bool(has_conflict), text_, clock.now()
        declared = existing
    else:
        declared = EvaluatorDeclaration(tenant_id=event.tenant_id, event_id=event.id, user_id=p.user_id, has_conflict=bool(has_conflict),
                                        declaration=text_, declared_at=clock.now(), created_by=p.user_id)
        session.add(declared)
    session.flush()
    audit.record(session, "SOURCING_EVENT", event.id, "EVALUATOR_DECLARED", object_ref=event.number,
                 after={"evaluator": p.email, "hasConflict": bool(has_conflict)}, reason=text_[:300])
    return declared


def _require_declaration(session: Session, event: SourcingEvent) -> None:
    p = principal(session)
    declared = session.execute(select(EvaluatorDeclaration).where(EvaluatorDeclaration.event_id == event.id,
                                                                  EvaluatorDeclaration.user_id == p.user_id)).scalar_one_or_none()
    if declared is None:
        raise Problem(422, "DECLARATION_REQUIRED", f"Declare any conflict of interest in {event.number} before you score its bids", rule_ref="SRC-05")
    if declared.has_conflict:
        raise Problem(403, "EVALUATOR_CONFLICT", f"You declared a conflict of interest in {event.number}: you cannot score its bids", rule_ref="SRC-05")


def disqualify(session: Session, event: SourcingEvent, supplier: Supplier, reason: str) -> Bid:
    """Take a bidder out of the evaluation with a written reason (non-compliance, failed technical gate, conflict, integrity). The bid stays on record,
    is no longer ranked or awardable, and the supplier is told. Allowed while the bids are evaluated, before an award is proposed."""
    p = principal(session)
    reason = (reason or "").strip()
    if len(reason) < 10:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for the disqualification (at least a sentence)", rule_ref="SRC-DISQUALIFY")
    auction_svc._require_manager(session, event)
    abac.guard(session, "SOURCING_MANAGE", event)
    if event.status != "UNDER_EVALUATION":
        raise illegal_transition("Sourcing event", event.number, event.status, "disqualify")
    bid = session.execute(select(Bid).where(Bid.event_id == event.id, Bid.supplier_id == supplier.id, Bid.status == "UNSEALED")
                          .with_for_update()).scalar_one_or_none()
    if bid is None:
        raise Problem(422, "NO_VALID_BID", f"{supplier.code} has no evaluated bid in {event.number}")
    bid.status, bid.disqualified_at, bid.disqualified_by, bid.disqualified_reason = "DISQUALIFIED", clock.now(), p.user_id, reason
    # earlier scenarios included the bid: they are stale (kept as evidence, marked superseded) and must be rebuilt
    for old in session.execute(select(AwardScenario).where(AwardScenario.event_id == event.id)).scalars():
        if not (old.explanation or {}).get("supersededAt"):
            old.explanation = {**(old.explanation or {}), "supersededAt": clock.now().isoformat(), "supersededBy": f"{supplier.code} disqualified"}
    session.flush()
    audit.record(session, "SOURCING_EVENT", event.id, "BID_DISQUALIFIED", object_ref=event.number, reason=reason,
                 after={"supplier": supplier.code, "round": bid.round})
    outbox.emit(session, "sourcing.bid.disqualified", "SOURCING_EVENT", event.id, event.number,
                {"supplier": supplier.code, "supplierId": str(supplier.id), "reason": reason, "round": bid.round, "ownerId": str(event.owner_id)})
    return bid


def score(session: Session, event: SourcingEvent, scores: list[dict]) -> dict:
    p = principal(session)
    if event.status != "UNDER_EVALUATION":
        raise illegal_transition("Sourcing event", event.number, event.status, "score")
    criteria = {c.code: c for c in _criteria(session, event)}
    if not scores:
        raise Problem(422, "NO_SCORES", "Send at least one score", rule_ref="SRC-CRITERIA")
    checked = []
    for item in scores:
        if item["criterion"] not in criteria or item["criterion"] == "PRICE_TCO":
            raise Problem(422, "INVALID_CRITERION", f"{item['criterion']} is not a manually scored criterion of {event.number}")
        if criteria[item["criterion"]].data_source != "MANUAL":
            raise Problem(422, "INVALID_CRITERION", f"{item['criterion']} is scored from {criteria[item['criterion']].data_source} data at close, "
                          "not by an evaluator", rule_ref="SRC-CRITERIA")
        try:
            value = D(item["score"])
        except (KeyError, TypeError, ValueError, ArithmeticError):
            raise Problem(422, "INVALID_SCORE", "A score is a number from 0 to 100", rule_ref="SRC-CRITERIA")
        if not value.is_finite() or not Decimal(0) <= value <= Decimal(100):
            raise Problem(422, "INVALID_SCORE", f"A score is from 0 to 100 (got {item['score']})", rule_ref="SRC-CRITERIA")
        supplier = supplier_by_code(session, item["supplier"])
        bid = session.execute(select(Bid).where(Bid.event_id == event.id, Bid.supplier_id == supplier.id,
                                                Bid.status == "UNSEALED")).scalar_one_or_none()
        if bid is None:
            raise Problem(422, "NO_VALID_BID", f"{supplier.code} has no evaluated bid in {event.number}")
        checked.append((item, bid, value))
    _require_declaration(session, event)  # after the input checks: a malformed request is told what is wrong with it first
    for item, bid, value in checked:
        existing = session.execute(select(Evaluation).where(Evaluation.bid_id == bid.id, Evaluation.criterion_code == item["criterion"],
                                                            Evaluation.evaluator_id == p.user_id)).scalar_one_or_none()
        if existing:
            existing.score = value
        else:
            session.add(Evaluation(tenant_id=event.tenant_id, event_id=event.id, bid_id=bid.id, criterion_code=item["criterion"],
                                   evaluator_id=p.user_id, score=value, comment=item.get("comment"), created_by=p.user_id))
    session.flush()
    sod.record(session, "BID_SCORE", {"event_id": event.id})
    audit.record(session, "SOURCING_EVENT", event.id, "SCORED", object_ref=event.number, after={"entries": len(scores)})
    return {"event": event.number, "matrix": evaluation_matrix(session, event)}


def new_round(session: Session, event: SourcingEvent, close_at: datetime, note: str = "") -> SourcingEvent:
    auction_svc._require_manager(session, event)
    abac.guard(session, "SOURCING_MANAGE", event)
    close_at = aware(close_at)
    if close_at is None or close_at <= clock.now():
        raise rule_violation("Close time must be in the future", "SRC-CLOSE")
    instance = workflow.find(session, "SOURCING_EVENT", event.id, PROCESS)
    workflow.step(session, instance, "F3-05", outcome=f"yes: negotiation round {event.round + 1}" + (f" ({note})" if note else ""))
    SM.apply(session, event, "new_round", reason=note or "negotiation round")
    event.round += 1
    event.close_at = close_at
    event.unsealed_at = None
    event.competitive = None
    event.opening = {}
    event.clarification_close_at = None  # the questions of a new round run until its close
    auction_svc.on_new_round(event)
    workflow.create_timer(session, "SOURCING_CLOSE", "SOURCING_EVENT", event.id, close_at, {"round": event.round})
    workflow.wait(session, instance, "F3-03", outcome=f"round {event.round}: sealed bids until {close_at.isoformat()}")
    outbox.emit(session, "sourcing.round.opened", "SOURCING_EVENT", event.id, event.number,
                {"round": event.round, "closeAt": close_at.isoformat(), "note": note or None, "inviteeSupplierIds": _invitee_ids(session, event)})
    return event


def _invitee_ids(session: Session, event: SourcingEvent) -> list[str]:
    return [str(i) for i in session.execute(select(Invitee.supplier_id).where(Invitee.event_id == event.id).order_by(Invitee.created_at)).scalars()]


def extend_deadline(session: Session, event: SourcingEvent, close_at: datetime, reason: str) -> SourcingEvent:
    """Move the bid deadline of a published or open event later (owner or category manager, reason required). Bids already sealed
    stay sealed and valid; the clarification window moves with the deadline when it was derived from it; every invited supplier is
    told (``sourcing.deadline.extended``). A deadline can only move later: an earlier close would cut short suppliers still preparing
    their bid. A live reverse auction extends itself by its soft-close rule instead."""
    auction_svc._require_manager(session, event)
    abac.guard(session, "SOURCING_MANAGE", event)
    reason = (reason or "").strip()
    if not reason:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for the extension", rule_ref="SRC-EXTEND")
    if event.status not in ("PUBLISHED", "OPEN"):
        raise illegal_transition("Sourcing event", event.number, event.status, "extend_deadline")
    if event.type == "REVERSE_AUCTION":
        raise rule_violation("A reverse auction is extended by its soft-close rule, not by hand", "SRC-EXTEND")
    close_at = aware(close_at)
    previous = event.close_at
    if close_at is None or close_at <= previous:
        raise rule_violation(f"The new deadline must be after the current one ({previous.isoformat()})", "SRC-EXTEND")
    if close_at <= clock.now():
        raise rule_violation("Close time must be in the future", "SRC-CLOSE")
    event.close_at = close_at
    workflow.create_timer(session, "SOURCING_CLOSE", "SOURCING_EVENT", event.id, close_at, {"round": event.round})
    audit.record(session, "SOURCING_EVENT", event.id, "DEADLINE_EXTENDED", object_ref=event.number,
                 before={"closeAt": previous.isoformat()}, after={"closeAt": close_at.isoformat(), "round": event.round}, reason=reason)
    outbox.emit(session, "sourcing.deadline.extended", "SOURCING_EVENT", event.id, event.number,
                {"round": event.round, "previousCloseAt": previous.isoformat(), "closeAt": close_at.isoformat(), "reason": reason,
                 "inviteeSupplierIds": _invitee_ids(session, event)})
    return event


# ---------------------------------------------------------------- award optimisation (F3-06)
def _line_candidates(rows: list[dict], q: Decimal, constraints: dict, single_only: bool = False):
    """Every supplier set (up to max_suppliers) with its cheapest feasible fill for one line:
    minimise Σ x_s·tco_s  s.t. Σ x_s = 1, x_s·Q ≤ verified capacity, min_share ≤ x_s ≤ max_share, Σ_conditional x_s ≤ cap.
    Exact: enumerate supplier sets, fill cheapest first (optimal for one equality). Yields (unit cost, [(row, share)])."""
    max_k = 1 if single_only else int(constraints.get("max_suppliers", 2))
    max_share = Decimal(str(constraints.get("max_share", 1))) if not single_only else Decimal(1)
    min_share = Decimal(str(constraints.get("min_share", 0)))
    cond_cap = Decimal(str(constraints["max_conditional_share_pct"])) / 100 if constraints.get("max_conditional_share_pct") not in (None, "") else None
    block_unverified = bool(constraints.get("_block_unverified"))
    for k in range(1, max_k + 1):
        for subset in itertools.combinations(rows, k):
            uppers, lowers = [], []
            for r in subset:
                if r.get("verifiedCapacityPerMonth"):
                    cap = Decimal(r["verifiedCapacityPerMonth"]) / q
                else:  # nobody verified this supplier's capacity: assumed enough (and flagged on the award) unless the policy blocks it
                    cap = Decimal(0) if block_unverified else Decimal(1)
                uppers.append(min(max_share, cap))  # max_share binds a single supplier too (sole source only if max_share is 1)
                moq_share = Decimal(str(r["moq"])) / q if r.get("moq") not in (None, "") and q > 0 else Decimal(0)  # a selected supplier gets at least its MOQ
                lowers.append(max(min_share if k > 1 else Decimal(1), moq_share))
            if any(lo > up + EPS for lo, up in zip(lowers, uppers)) or sum(uppers) < 1 - EPS or sum(lowers) > 1 + EPS:
                continue
            shares = list(lowers)
            remaining = Decimal(1) - sum(lowers)
            cond_used = sum((s for s, r in zip(shares, subset) if r.get("conditional")), Decimal(0))
            for index in sorted(range(k), key=lambda i: subset[i]["tcoMinor"]):
                room = uppers[index] - shares[index]
                if cond_cap is not None and subset[index].get("conditional"):
                    room = min(room, max(cond_cap - cond_used, Decimal(0)))  # the Conditional suppliers together stay within their cap
                add = min(room, remaining)
                shares[index] += add
                remaining -= add
                if subset[index].get("conditional"):
                    cond_used += add
            if remaining > EPS or (cond_cap is not None and cond_used > cond_cap + EPS):
                continue
            if remaining > 0:   # a division left less than EPS over (equal thirds of capacity): the cheapest supplier takes it so the shares add up to exactly 1
                shares[min(range(k), key=lambda i: subset[i]["tcoMinor"])] += remaining
            cost = sum(s * r["tcoMinor"] for s, r in zip(shares, subset))
            yield cost, [(r, s) for r, s in zip(subset, shares) if s > 0]


def _optimise(rows: list[dict], q: Decimal, constraints: dict, single_only: bool = False) -> Optional[dict]:
    """minimise Σ x_s·tco_s·Q  s.t. Σ x_s = 1, x_s·Q ≤ verified capacity, min_share ≤ x_s ≤ max_share,
    count ≤ max_suppliers. Exact: enumerate supplier sets, fill cheapest first (optimal for one equality)."""
    best = None
    for cost, allocations in _line_candidates(rows, q, constraints, single_only):
        if best is None or cost < best["cost"]:
            best = {"cost": cost, "allocations": allocations}
    return best


def _risk_constraints(session: Session, event: SourcingEvent) -> dict:
    """Event constraints over the tenant's AWARD-RISK defaults. Keys: max_risk_score, max_single_source_pct, max_conditional_share_pct,
    max_total_suppliers."""
    rule = award_risk_rule(session)
    own = event.constraints or {}
    out = {}
    for key, rule_key in (("max_risk_score", "maxRiskScore"), ("max_single_source_pct", "maxSingleSourcePct"),
                          ("max_conditional_share_pct", "maxConditionalSharePct")):
        value = own.get(key) if own.get(key) not in (None, "") else rule.get(rule_key)
        if value not in (None, ""):
            out[key] = value
    if own.get("max_total_suppliers") not in (None, ""):
        out["max_total_suppliers"] = own["max_total_suppliers"]
    return out


def _supplier_risk_info(session: Session, event: SourcingEvent, supplier_ids: list) -> dict:
    info = {}
    for sid in supplier_ids:
        supplier = session.get(Supplier, sid)
        status = category_status(session, sid, event.category)
        risk = risk_svc.supplier_risk_score(session, supplier)
        info[str(sid)] = {"supplier": supplier.code, "status": status, "blocked": status == "BLOCKED", "conditional": status == "CONDITIONAL",
                          "riskScore": risk["score"], "riskLevel": risk["level"]}
    return info


def _exclusions(info: dict, rc: dict) -> dict:
    """supplierId → why the supplier cannot be awarded: blocked, or a risk score above the cap."""
    out = {}
    cap = int(rc["max_risk_score"]) if rc.get("max_risk_score") not in (None, "") else None
    for sid, item in info.items():
        if item["blocked"]:
            out[sid] = f"{item['supplier']} is BLOCKED"
        elif cap is not None and item["riskScore"] > cap:
            out[sid] = f"{item['supplier']} has risk score {item['riskScore']}, above the cap {cap}"
    return out


def _risk_explanation(info: dict, rc: dict, excluded: dict, checks: list) -> dict:
    return {"constraints": rc, "excluded": [{"supplierId": sid, "reason": why} for sid, why in excluded.items()],
            "suppliers": {i["supplier"]: {"status": i["status"], "riskScore": i["riskScore"], "riskLevel": i["riskLevel"]} for i in info.values()},
            "checks": checks}


def _share_checks(values: dict, info: dict, rc: dict) -> list[dict]:
    """Single-source and conditional-share caps over the awarded value per supplier id (the value share of each supplier)."""
    total = sum(values.values())
    checks = []
    if total <= 0:
        return checks
    shares = {sid: Decimal(v) * 100 / Decimal(total) for sid, v in values.items()}
    if rc.get("max_single_source_pct") not in (None, ""):
        cap = Decimal(str(rc["max_single_source_pct"]))
        top = max(shares, key=shares.get)
        checks.append({"rule": "max_single_source_pct", "limit": str(cap), "top": info[top]["supplier"], "topSharePct": str(shares[top].quantize(Decimal("0.1"))),
                       "ok": shares[top] <= cap})
    if rc.get("max_conditional_share_pct") not in (None, ""):
        cap = Decimal(str(rc["max_conditional_share_pct"]))
        cond = sum((s for sid, s in shares.items() if info[sid]["conditional"]), Decimal(0))
        checks.append({"rule": "max_conditional_share_pct", "limit": str(cap), "conditionalSharePct": str(cond.quantize(Decimal("0.1"))), "ok": cond <= cap})
    if rc.get("max_total_suppliers") not in (None, ""):
        n = len([v for v in values.values() if v > 0])
        checks.append({"rule": "max_total_suppliers", "limit": int(rc["max_total_suppliers"]), "suppliers": n, "ok": n <= int(rc["max_total_suppliers"])})
    return checks


def _supplier_rows(rows: list[dict], info: dict, excluded: dict) -> list[dict]:
    kept = []
    for r in rows:
        if r["supplierId"] in excluded:
            continue
        kept.append({**r, "conditional": info[r["supplierId"]]["conditional"]})
    return kept


def build_scenarios(session: Session, event: SourcingEvent) -> list[dict]:
    auction_svc._require_manager(session, event)
    if event.status != "UNDER_EVALUATION":
        raise illegal_transition("Sourcing event", event.number, event.status, "scenarios")
    # F3-08: a scenario an award decision was taken on (e.g. a rejected award) stays as evidence and is marked superseded;
    # the others are rebuilt. Deleting it would break the decision's reference and leave the event stuck in evaluation.
    decided = set(session.execute(select(AwardDecision.scenario_id).where(AwardDecision.event_id == event.id)).scalars())
    for old in session.execute(select(AwardScenario).where(AwardScenario.event_id == event.id)).scalars():
        if old.id in decided:
            if not (old.explanation or {}).get("supersededAt"):
                old.explanation = {**(old.explanation or {}), "supersededAt": clock.now().isoformat()}
        else:
            session.delete(old)
    session.flush()
    matrix = evaluation_matrix(session, event)
    rc = _risk_constraints(session, event)
    if str(policy_of(session, event).get("unverifiedCapacity", "FLAG")).upper() == "BLOCK":
        rc["_block_unverified"] = True
    info = _supplier_risk_info(session, event, [uuid.UUID(r["supplierId"]) for r in matrix])
    excluded = _exclusions(info, rc)
    for r in matrix:  # a bid that failed the technical gate is not awardable (the gate is a precondition, not a score)
        if not r["technicalGate"]["passed"]:
            excluded.setdefault(r["supplierId"], f"{r['supplier']} scored below the minimum on {', '.join(r['technicalGate']['failed'])}")
    event_lines = _lines(session, event)
    if len(event_lines) == 1:
        results = _single_line_scenarios(session, event, event_lines[0], matrix, rc, info, excluded)
    else:
        results = _multi_line_scenarios(session, event, event_lines, matrix, rc, info, excluded)
    instance = workflow.find(session, "SOURCING_EVENT", event.id, PROCESS)
    if instance.current_step == "F3-05":
        workflow.step(session, instance, "F3-05", outcome="no further round")
    workflow.wait(session, instance, "F3-06", outcome="; ".join(
        f"{s.kind}: {'feasible' if s.feasible else 'infeasible'}" + (f" @ {s.weighted_price_minor/100:.2f}" if s.weighted_price_minor else "")
        for s in results))
    return [{"id": str(s.id), "kind": s.kind, "feasible": s.feasible, "allocations": s.allocations,
             "weightedPriceMinor": s.weighted_price_minor, "weightedTcoMinor": s.weighted_tco_minor,
             "annualSavingsMinor": s.annual_savings_minor, "explanation": s.explanation} for s in results]


def _scenario_risk(allocations: list, explanation: dict) -> Optional[int]:
    """Value-weighted supplier risk score (0 best .. 100) of the suppliers an allocation uses, from the risk scores the scenario was built on."""
    scores = {code: item.get("riskScore") for code, item in ((explanation.get("risk") or {}).get("suppliers") or {}).items()}
    total, weighted = Decimal(0), Decimal(0)
    for a in allocations or []:
        weight = Decimal(a["valueMinor"]) if a.get("valueMinor") is not None else Decimal(a.get("share") or 0) * Decimal(a.get("priceMinor") or 0)
        if scores.get(a["supplier"]) is None or weight <= 0:
            continue
        total += weight
        weighted += weight * Decimal(scores[a["supplier"]])
    return int((weighted / total).quantize(Decimal(1), ROUND_HALF_UP)) if total > 0 else None


def _store(session: Session, event: SourcingEvent, results: list, kind: str, allocations: list, feasible: bool, explanation: dict,
           weighted_price, weighted_tco, savings) -> AwardScenario:
    scenario = AwardScenario(
        tenant_id=event.tenant_id, event_id=event.id, kind=kind, feasible=feasible, allocations=allocations,
        weighted_price_minor=int(weighted_price.quantize(Decimal("1"), ROUND_HALF_UP)) if weighted_price is not None else None,
        weighted_tco_minor=int(weighted_tco.quantize(Decimal("1"), ROUND_HALF_UP)) if weighted_tco is not None else None,
        annual_savings_minor=savings, explanation=explanation, created_by=principal(session).user_id,
        risk_score=_scenario_risk(allocations, explanation))
    session.add(scenario)
    session.flush()
    results.append(scenario)
    return scenario


def _single_line_scenarios(session: Session, event: SourcingEvent, line: EventLine, matrix: list[dict], rc: dict, info: dict, excluded: dict) -> list:
    q = line.monthly_qty
    rows = _supplier_rows(matrix, info, excluded)
    # With one line the value share equals the volume share: the single-source cap is a cap on the share of the line.
    constraints = dict(event.constraints or {})
    if str(policy_of(session, event).get("unverifiedCapacity", "FLAG")).upper() == "BLOCK":
        constraints["_block_unverified"] = True
    if rc.get("max_single_source_pct") not in (None, ""):
        constraints["max_share"] = str(min(Decimal(str(constraints.get("max_share", 1))), Decimal(str(rc["max_single_source_pct"])) / 100))
    if rc.get("max_conditional_share_pct") not in (None, ""):
        constraints["max_conditional_share_pct"] = rc["max_conditional_share_pct"]
    results: list = []

    def store(kind: str, allocations, feasible: bool, explanation: dict) -> AwardScenario:
        weighted_price = sum(Decimal(r["priceMinor"]) * s for r, s in allocations) if allocations else None
        weighted_tco = sum(Decimal(r["tcoMinor"]) * s for r, s in allocations) if allocations else None
        savings = int((Decimal(event.baseline_price_minor) - weighted_price) * line.annual_qty) if allocations and event.baseline_price_minor else None
        values = {r["supplierId"]: Decimal(r["tcoMinor"]) * s for r, s in allocations}
        checks = _share_checks(values, info, rc) if allocations else []
        explanation = {**explanation, "risk": _risk_explanation(info, rc, excluded, checks)}
        if any(not c["ok"] for c in checks):
            feasible = False
        return _store(
            session, event, results, kind,
            [{"supplier": r["supplier"], "supplierId": r["supplierId"], "share": str(s.quantize(QUANT4)),
              "monthlyQty": str((q * s).quantize(Decimal("1"))), "annualQty": str((line.annual_qty * s).quantize(Decimal("1"))),
              "priceMinor": r["priceMinor"], "tcoMinor": r["tcoMinor"], "capacityVerified": bool(r.get("capacityVerified", True)),
              "tcoIncomplete": bool(r.get("tcoIncomplete"))} for r, s in allocations],
            feasible, explanation, weighted_price, weighted_tco, savings)

    block = bool(constraints.get("_block_unverified"))

    def sole_feasible(row: dict) -> bool:
        cap = Decimal(row["verifiedCapacityPerMonth"] or q)
        moq = Decimal(str(row["moq"])) if row.get("moq") not in (None, "") else Decimal(0)
        return cap >= q and moq <= q and not (block and not row.get("capacityVerified", True))

    lowest = rows[0] if rows else None
    if lowest:
        cap = Decimal(lowest["verifiedCapacityPerMonth"] or q)
        store("LOWEST_COST", [(lowest, Decimal(1))], sole_feasible(lowest),
              {"rule": "all volume to lowest TCO", "capacityCheck": f"{lowest['supplier']} verified capacity {cap} vs {q}/month"
               + ("" if lowest.get("capacityVerified", True) else " (capacity not verified)")})
    best_value = max(rows, key=lambda r: (Decimal(r.get("weightedScore", "0")), -r["tcoMinor"])) if rows else None
    if best_value:
        cap = Decimal(best_value["verifiedCapacityPerMonth"] or q)
        store("BEST_VALUE", [(best_value, Decimal(1))], sole_feasible(best_value),
              {"rule": "all volume to highest weighted score", "capacityCheck": f"{best_value['supplier']} verified capacity {cap} vs {q}/month"
               + ("" if best_value.get("capacityVerified", True) else " (capacity not verified)")})
    optimum = _optimise(rows, q, constraints)
    if optimum:
        store("CAPACITY_CONSTRAINED", optimum["allocations"], True,
              {"rule": "MIP: min Σ x·TCO·Q s.t. capacity (digital twin), share bounds, max suppliers",
               "Q": str(q), "constraints": event.constraints,
               "bounds": {r["supplier"]: f"x ≤ min({constraints.get('max_share')}, {r['verifiedCapacityPerMonth']}/{q})" for r in rows}})
    else:
        store("CAPACITY_CONSTRAINED", [], False, {"rule": "no feasible allocation under constraints"})
    return results


# ---- several lines and lots
def _multi_line_scenarios(session: Session, event: SourcingEvent, event_lines: list[EventLine], matrix: list[dict], rc: dict, info: dict,
                          excluded: dict) -> list:
    results: list = []
    context = _AwardContext(event, event_lines, [r for r in matrix if r["supplierId"] not in excluded], info, rc)
    baseline_value = (sum(Decimal(l.baseline_price_minor) * l.annual_qty for l in event_lines)
                      if all(l.baseline_price_minor is not None for l in event_lines) else None)

    def store(kind: str, plan: Optional["_Plan"], rule: str, extra: Optional[dict] = None) -> AwardScenario:
        if plan is None:
            return _store(session, event, results, kind, [], False,
                          {"rule": rule, "basis": "ANNUAL_VALUE", "uncovered": context.uncovered(),
                           "risk": _risk_explanation(info, rc, excluded, []), **(extra or {})}, None, None, None)
        price, tco = plan.price_value(), plan.tco_value()
        checks = _share_checks(plan.supplier_values(), info, rc)
        feasible = all(c["ok"] for c in checks)
        return _store(session, event, results, kind, plan.allocations(context), feasible,
                      {"rule": rule, "basis": "ANNUAL_VALUE", "constraints": event.constraints, "lots": plan.lot_decisions,
                       "risk": _risk_explanation(info, rc, excluded, checks), **(extra or {})},
                      price, tco, int(baseline_value - price) if baseline_value is not None else None)

    store("LOWEST_COST", context.greedy("tco"), "each line (or lot) to the supplier with the lowest TCO that can cover it")
    store("BEST_VALUE", context.greedy("score"), "each line (or lot) to the supplier with the highest weighted score that can cover it")
    optimum, nodes, exhausted = context.optimise()
    store("CAPACITY_CONSTRAINED", optimum,
          "MIP per line and lot: min Σ x·TCO·annual qty s.t. capacity, share bounds, max suppliers per line, lot bundles, risk constraints",
          {"search": {"nodes": nodes, "complete": not exhausted}})
    return results


class _Plan:
    """One award across all lines: per line the (supplier row, share) pairs, plus the lots awarded as a bundle."""

    def __init__(self):
        self.lines: dict = {}      # line_no -> [(row_for_line, share, price_unit, tco_unit)]
        self.lot_decisions: list = []
        self.bundles: dict = {}    # lot -> supplier id awarded as a bundle
        self.annual: dict = {}     # line_no -> annual qty

    def copy(self) -> "_Plan":
        out = _Plan()
        out.lines = {k: list(v) for k, v in self.lines.items()}
        out.lot_decisions = list(self.lot_decisions)
        out.bundles = dict(self.bundles)
        out.annual = self.annual
        return out

    def price_value(self) -> Decimal:
        return sum((Decimal(price) * share * self.annual[n] for n, entries in self.lines.items() for _, share, price, _ in entries), Decimal(0))

    def tco_value(self) -> Decimal:
        return sum((Decimal(tco) * share * self.annual[n] for n, entries in self.lines.items() for _, share, _, tco in entries), Decimal(0))

    def supplier_values(self) -> dict:
        out: dict = {}
        for n, entries in self.lines.items():
            for row, share, _, tco in entries:
                out[row["supplierId"]] = out.get(row["supplierId"], Decimal(0)) + Decimal(tco) * share * self.annual[n]
        return out

    def allocations(self, context: "_AwardContext") -> list:
        by_supplier: dict = {}
        for n, entries in sorted(self.lines.items()):
            line = context.line_by_no[n]
            for row, share, price, tco in entries:
                entry = by_supplier.setdefault(row["supplierId"], {"supplier": row["supplier"], "supplierId": row["supplierId"], "lines": []})
                entry["lines"].append({
                    "line": n, "eventLineId": str(line.id), "lot": line.lot_code, "bundle": line.lot_code in self.bundles
                    and self.bundles[line.lot_code] == row["supplierId"], "share": str(share.quantize(QUANT4)),
                    "monthlyQty": str((line.monthly_qty * share).quantize(QUANT3)), "annualQty": str((line.annual_qty * share).quantize(QUANT3)),
                    "priceMinor": int(price), "tcoMinor": int(tco), "capacityVerified": bool(row.get("capacityVerified", True)),
                    "tcoIncomplete": bool(row.get("tcoIncomplete")),
                    "valueMinor": int((Decimal(price) * share * line.annual_qty).quantize(Decimal("1"), ROUND_HALF_UP))})
        total = sum(sum(l["valueMinor"] for l in e["lines"]) for e in by_supplier.values()) or 1
        for entry in by_supplier.values():
            value = sum(l["valueMinor"] for l in entry["lines"])
            entry.update(valueMinor=value, share=str((Decimal(value) / Decimal(total)).quantize(QUANT4)), priceMinor=None, annualQty=None)
        return sorted(by_supplier.values(), key=lambda e: -e["valueMinor"])


class _AwardContext:
    """Bids of the eligible suppliers re-arranged per line and lot for the multi-line optimiser."""

    def __init__(self, event: SourcingEvent, event_lines: list[EventLine], rows: list[dict], info: dict, rc: dict):
        self.event, self.event_lines, self.rows, self.info, self.rc = event, event_lines, rows, info, rc
        self.line_by_no = {l.line_no: l for l in event_lines}
        self.constraints = dict(event.constraints or {})
        self.block_unverified = bool(rc.get("_block_unverified"))
        if self.block_unverified:
            self.constraints["_block_unverified"] = True
        if rc.get("max_conditional_share_pct") not in (None, ""):
            self.constraints["max_conditional_share_pct"] = rc["max_conditional_share_pct"]
        self.lots: dict = {}
        for l in event_lines:
            if l.lot_code:
                self.lots.setdefault(l.lot_code, []).append(l)
        # (line_no) -> rows with the line bid; (supplierId, lot) -> lot terms
        self.by_line: dict = {l.line_no: [] for l in event_lines}
        self.lot_terms: dict = {}
        for r in rows:
            lots = {t["lot"]: t for t in r["lots"]}
            for lr in r["lines"]:
                line = self.line_by_no[lr["line"]]
                term = lots.get(line.lot_code) if line.lot_code else None
                self.by_line[lr["line"]].append({
                    "supplier": r["supplier"], "supplierId": r["supplierId"], "priceMinor": lr["priceMinor"], "tcoMinor": lr["tcoMinor"],
                    "verifiedCapacityPerMonth": lr["verifiedCapacityPerMonth"], "weightedScore": lr.get("weightedScore", "0"),
                    "twinCapacity": Decimal(lr["twinCapacityPerMonth"]) if lr.get("twinCapacityPerMonth") is not None else None,
                    "moq": lr.get("moq"), "capacityVerified": bool(lr.get("capacityVerified", True)), "tcoIncomplete": bool(lr.get("tcoIncomplete")),
                    "conditional": info[r["supplierId"]]["conditional"], "allOrNothing": bool(term and term["allOrNothing"])})
            for t in r["lots"]:
                self.lot_terms[(r["supplierId"], t["lot"])] = t
        self.total_cap = {}  # supplierId -> twin capacity is not aggregated: the per-line verified capacity applies

    def uncovered(self) -> list:
        return [n for n, rows in self.by_line.items() if not rows]

    # -- candidates of a unit
    def line_options(self, line: EventLine, only_split: bool = False) -> list:
        """Options for one line as (cost, [(row, share, price, tco)]) sorted by cost."""
        rows = [r for r in self.by_line[line.line_no] if not (only_split and r["allOrNothing"])]
        out = []
        for cost, allocation in _line_candidates(rows, line.monthly_qty, self.constraints):
            out.append((Decimal(cost) * line.annual_qty, [(r, s, r["priceMinor"], r["tcoMinor"]) for r, s in allocation]))
        out.sort(key=lambda o: o[0])
        return out[:12]

    def bundle_options(self, lot: str) -> list:
        """Whole-lot awards to one supplier that bid lot terms and covered every line within its capacity."""
        out = []
        for sid, code in sorted(k for k in self.lot_terms if k[1] == lot):
            term = self.lot_terms[(sid, code)]
            discount = Decimal(term["discountPct"]) / 100
            entries, cost, ok = {}, Decimal(0), True
            for line in self.lots[lot]:
                row = next((r for r in self.by_line[line.line_no] if r["supplierId"] == sid), None)
                cap = Decimal(row["verifiedCapacityPerMonth"]) if row and row["verifiedCapacityPerMonth"] else None
                if row is None or (cap is not None and cap < line.monthly_qty):
                    ok = False
                    break
                price = Decimal(row["priceMinor"]) * (1 - discount)
                tco = Decimal(row["tcoMinor"]) - Decimal(row["priceMinor"]) * discount
                entries[line.line_no] = [(row, Decimal(1), price, tco)]
                cost += tco * line.annual_qty
            if ok:
                out.append((cost, entries, sid))
        out.sort(key=lambda o: o[0])
        return out

    # -- greedy scenarios
    def greedy(self, mode: str) -> Optional[_Plan]:
        plan = _Plan()
        plan.annual = {l.line_no: l.annual_qty for l in self.event_lines}

        def single(line: EventLine, only_split: bool) -> Optional[list]:
            rows = [r for r in self.by_line[line.line_no] if not (only_split and r["allOrNothing"])
                    and (Decimal(r["verifiedCapacityPerMonth"]) >= line.monthly_qty if r["verifiedCapacityPerMonth"] else not self.block_unverified)
                    and (r.get("moq") in (None, "") or Decimal(str(r["moq"])) <= line.monthly_qty)]
            if not rows:
                return None
            key = (lambda r: r["tcoMinor"]) if mode == "tco" else (lambda r: -Decimal(r["weightedScore"]))
            row = min(rows, key=key)
            return [(row, Decimal(1), row["priceMinor"], row["tcoMinor"])]

        for line in self.event_lines:
            if line.lot_code:
                continue
            entry = single(line, False)
            if entry is None:
                return None
            plan.lines[line.line_no] = entry
        for lot, lines in self.lots.items():
            options = []
            bundles = self.bundle_options(lot)
            if mode == "tco":
                if bundles:
                    options.append(("bundle", bundles[0][0], bundles[0]))
            else:  # best value: the bundle supplier with the best value-weighted score for the lot
                def lot_score(sid):
                    rows = [next((r for r in self.by_line[l.line_no] if r["supplierId"] == sid), None) for l in lines]
                    return sum(Decimal(r["weightedScore"]) for r in rows) / len(rows)
                if bundles:
                    best = max(bundles, key=lambda b: lot_score(b[2]))
                    options.append(("bundle", -lot_score(best[2]), best))
            split, split_cost = {}, Decimal(0)
            for line in lines:
                entry = single(line, True)
                if entry is None:
                    split = None
                    break
                split[line.line_no] = entry
                split_cost += Decimal(entry[0][3]) * line.annual_qty
            if split is not None:
                if mode == "tco":
                    options.append(("split", split_cost, split))
                else:
                    avg = sum(Decimal(e[0][0]["weightedScore"]) for e in split.values()) / len(split)
                    options.append(("split", -avg, split))
            if not options:
                return None
            kind, _, chosen = min(options, key=lambda o: o[1])
            if kind == "bundle":
                _, entries, sid = chosen
                plan.lines.update(entries)
                plan.bundles[lot] = sid
                plan.lot_decisions.append({"lot": lot, "decision": "BUNDLE", "supplierId": sid})
            else:
                plan.lines.update(chosen)
                plan.lot_decisions.append({"lot": lot, "decision": "SPLIT"})
        return plan

    # -- branch and bound
    def optimise(self) -> tuple[Optional[_Plan], int, bool]:
        """min Σ cost over units (free lines, lots) s.t. line constraints, total-supplier and value-share caps. Depth-first with the cheapest
        option first and the sum of each remaining unit's cheapest option as the bound; stops after BNB_NODE_LIMIT nodes."""
        units = []
        for line in sorted(self.event_lines, key=lambda l: -(l.annual_qty * (l.baseline_price_minor or 1))):
            if line.lot_code:
                continue
            options = self.line_options(line)
            if not options:
                return None, 0, False
            units.append({"kind": "LINE", "line": line, "options": [("LINE", c, {line.line_no: e}, None) for c, e in options], "bound": options[0][0]})
        for lot, lines in self.lots.items():
            options = [("BUNDLE", c, e, sid) for c, e, sid in self.bundle_options(lot)]
            split_bound, split_ok = Decimal(0), True
            for line in lines:
                opts = self.line_options(line, only_split=True)
                if not opts:
                    split_ok = False
                    break
                split_bound += opts[0][0]
            if split_ok:
                options.append(("SPLIT", Decimal(0), {}, None))
            if not options:
                return None, 0, False
            bound = min([o[1] for o in options if o[0] == "BUNDLE"] + ([split_bound] if split_ok else []))
            units.append({"kind": "LOT", "lot": lot, "lines": lines, "options": sorted(options, key=lambda o: o[1]), "bound": bound,
                          "split_ok": split_ok})
            for line in lines:
                opts = self.line_options(line, only_split=True)
                units.append({"kind": "SPLITLINE", "line": line, "lot": lot, "options": [("LINE", c, {line.line_no: e}, None) for c, e in opts],
                              "bound": Decimal(0)})
        remaining_bound = [Decimal(0)] * (len(units) + 1)
        for i in range(len(units) - 1, -1, -1):
            remaining_bound[i] = remaining_bound[i + 1] + units[i]["bound"]
        max_total = int(self.rc["max_total_suppliers"]) if self.rc.get("max_total_suppliers") not in (None, "") else None
        best = {"cost": None, "plan": None}
        nodes = [0]
        exhausted = [False]
        annual = {l.line_no: l.annual_qty for l in self.event_lines}
        decisions: dict = {}
        selected: list = []

        def feasible_leaf() -> Optional[_Plan]:
            plan = _Plan()
            plan.annual = annual
            for entries in selected:
                plan.lines.update(entries)
            plan.bundles = {lot: sid for lot, (kind, sid) in decisions.items() if kind == "BUNDLE"}
            plan.lot_decisions = [{"lot": lot, "decision": kind, **({"supplierId": sid} if sid else {})} for lot, (kind, sid) in decisions.items()]
            checks = _share_checks(plan.supplier_values(), self.info, {k: v for k, v in self.rc.items() if k != "max_total_suppliers"})
            return plan if all(c["ok"] for c in checks) else None

        def load_ok() -> bool:
            """Distinct suppliers within max_total_suppliers, and the monthly quantity a supplier takes in one unit of measure within the
            capacity its twin verified (the per-line bid and twin capacity is already applied to each line's options)."""
            suppliers, load = set(), {}
            for entries in selected:
                for n, lst in entries.items():
                    line = self.line_by_no[n]
                    for row, share, _, _ in lst:
                        suppliers.add(row["supplierId"])
                        key = (row["supplierId"], line.uom)
                        load[key] = load.get(key, Decimal(0)) + share * line.monthly_qty
                        if row.get("twinCapacity") is not None and load[key] > row["twinCapacity"]:
                            return False
            return max_total is None or len(suppliers) <= max_total

        def search(i: int, cost: Decimal) -> None:
            if exhausted[0]:
                return
            nodes[0] += 1
            if nodes[0] > BNB_NODE_LIMIT:
                exhausted[0] = True
                return
            if best["cost"] is not None and cost + remaining_bound[i] >= best["cost"]:
                return
            if i == len(units):
                plan = feasible_leaf()
                if plan is not None and (best["cost"] is None or cost < best["cost"]):
                    best["cost"], best["plan"] = cost, plan.copy()
                return
            unit = units[i]
            if unit["kind"] == "SPLITLINE" and decisions.get(unit["lot"], ("SPLIT", None))[0] == "BUNDLE":
                search(i + 1, cost)
                return
            for kind, option_cost, entries, sid in unit["options"]:
                if unit["kind"] == "LOT":
                    decisions[unit["lot"]] = (kind, sid)
                    selected.append(entries)
                    if load_ok():
                        search(i + 1, cost + (option_cost if kind == "BUNDLE" else Decimal(0)))
                    selected.pop()
                    del decisions[unit["lot"]]
                else:
                    selected.append(entries)
                    if load_ok():
                        search(i + 1, cost + option_cost)
                    selected.pop()

        search(0, Decimal(0))
        return best["plan"], nodes[0], exhausted[0]


# ---------------------------------------------------------------- manual split scenario (SRC-04 Award Scenario Studio)
def _split_error(detail: str, **extra) -> Problem:
    return Problem(422, "INVALID_SPLIT", detail, rule_ref="SRC-AWARD-SPLIT", **extra)


def custom_scenario(session: Session, event: SourcingEvent, allocations: list[dict]) -> dict:
    """A split the buyer entered, by percentage (``share_pct``) or by monthly quantity (``qty_per_month``) per supplier (and per ``line`` of a
    several-line event), checked like the optimiser's output: every supplier has an evaluated bid, the shares of a line add up to exactly 100 %,
    no supplier is above its verified capacity or below its MOQ, the share bounds and the supplier count of the event hold, and the risk caps
    hold. A split that does not add up to 100 % is refused (422); one that breaks a constraint is stored as an infeasible scenario with the
    violations listed, so the Studio can show why and the award refuses it. Lot bundle discounts are not applied to a manual split."""
    auction_svc._require_manager(session, event)
    abac.guard(session, "SOURCING_MANAGE", event)
    if event.status != "UNDER_EVALUATION":
        raise illegal_transition("Sourcing event", event.number, event.status, "scenarios")
    if not allocations:
        raise _split_error("Give at least one supplier with its share or quantity")
    event_lines = _lines(session, event)
    multi = len(event_lines) > 1
    matrix = evaluation_matrix(session, event)
    rc = _risk_constraints(session, event)
    info = _supplier_risk_info(session, event, [uuid.UUID(r["supplierId"]) for r in matrix])
    excluded = _exclusions(info, rc)
    for r in matrix:
        if not r["technicalGate"]["passed"]:
            excluded.setdefault(r["supplierId"], f"{r['supplier']} failed the technical gate")
    by_code = {r["supplier"]: r for r in matrix}
    constraints = dict(event.constraints or {})
    violations: list[str] = []
    per_line: dict = {}
    for entry in allocations:
        code = entry.get("supplier")
        row = by_code.get(code)
        if row is None:
            raise _split_error(f"{code} has no evaluated bid in {event.number}")
        if row["supplierId"] in excluded:
            violations.append(excluded[row["supplierId"]])
        line_no = int(entry["line"]) if entry.get("line") is not None else (event_lines[0].line_no if not multi else None)
        if line_no is None or line_no not in {l.line_no for l in event_lines}:
            raise _split_error(f"Give the line of the event this share is for (lines: {', '.join(str(l.line_no) for l in event_lines)})")
        line = next(l for l in event_lines if l.line_no == line_no)
        if (entry.get("share_pct") is None) == (entry.get("qty_per_month") is None):
            raise _split_error(f"{code}: give either share_pct or qty_per_month, not both and not neither")
        try:
            share = D(entry["share_pct"]) / 100 if entry.get("share_pct") is not None else D(entry["qty_per_month"]) / line.monthly_qty
        except (TypeError, ValueError, ArithmeticError):
            raise _split_error(f"{code}: the share must be a number")
        if not share.is_finite() or share <= 0 or share > 1:
            raise _split_error(f"{code}: the share must be above 0 and at most 100 %")
        if any(code == c for c, _ in per_line.get(line_no, [])):
            raise _split_error(f"{code} appears twice for line {line_no}")
        per_line.setdefault(line_no, []).append((code, share))
    for line in event_lines:
        entries = per_line.get(line.line_no, [])
        total = sum((sh for _, sh in entries), Decimal(0))
        if not entries or abs(total - 1) > Decimal("0.0001"):
            raise _split_error(f"Line {line.line_no}: the shares add up to {(total * 100).quantize(Decimal('0.01'))} %, not 100 %",
                               line=line.line_no, totalPct=str((total * 100).quantize(Decimal("0.01"))))
        line_row = {code: next(l for l in by_code[code]["lines"] if l["line"] == line.line_no) for code, _ in entries if any(l["line"] == line.line_no for l in by_code[code]["lines"])}
        for code, share in entries:
            lr = line_row.get(code)
            if lr is None:
                violations.append(f"{code} did not bid on line {line.line_no}")
                continue
            qty = share * line.monthly_qty
            if lr["verifiedCapacityPerMonth"] and qty > Decimal(lr["verifiedCapacityPerMonth"]) + EPS:
                violations.append(f"{code}: {qty.quantize(Decimal('1'))} per month on line {line.line_no} is above its verified capacity {lr['verifiedCapacityPerMonth']}")
            if lr["moq"] and qty < Decimal(lr["moq"]) - EPS:
                violations.append(f"{code}: {qty.quantize(Decimal('1'))} per month on line {line.line_no} is below its minimum order quantity {lr['moq']}")
            if not lr["capacityVerified"] and str(policy_of(session, event).get("unverifiedCapacity", "FLAG")).upper() == "BLOCK":
                violations.append(f"{code}: capacity on line {line.line_no} is not verified and the policy blocks it")
            if len(entries) > 1 and constraints.get("min_share") not in (None, "") and share < D(constraints["min_share"]) - EPS:
                violations.append(f"{code}: {(share * 100).quantize(Decimal('0.1'))} % is below the minimum share {D(constraints['min_share']) * 100} %")
            if constraints.get("max_share") not in (None, "") and share > D(constraints["max_share"]) + EPS:   # binds a sole source too, like the optimiser
                violations.append(f"{code}: {(share * 100).quantize(Decimal('0.1'))} % is above the maximum share {D(constraints['max_share']) * 100} %")
        if constraints.get("max_suppliers") and len(entries) > int(constraints["max_suppliers"]):
            violations.append(f"line {line.line_no}: {len(entries)} suppliers, the event allows {constraints['max_suppliers']}")
        for lot_line in [l for l in event_lines if l.lot_code and l.line_no == line.line_no]:
            for code, share in entries:
                row = by_code[code]
                if any(t["lot"] == lot_line.lot_code and t["allOrNothing"] for t in row["lots"]) and len(entries) > 1:
                    violations.append(f"{code} accepts lot {lot_line.lot_code} only as a whole: line {line.line_no} cannot be split")
    results: list = []
    if not multi:
        line = event_lines[0]
        pairs = [(by_code[code], share) for code, share in per_line[line.line_no]]
        weighted_price = sum(Decimal(r["priceMinor"]) * sh for r, sh in pairs)
        weighted_tco = sum(Decimal(r["tcoMinor"]) * sh for r, sh in pairs)
        savings = int((Decimal(event.baseline_price_minor) - weighted_price) * line.annual_qty) if event.baseline_price_minor else None
        checks = _share_checks({r["supplierId"]: Decimal(r["tcoMinor"]) * sh for r, sh in pairs}, info, rc)
        for c in checks:
            if not c["ok"]:
                violations.append(f"{c['rule']}: limit {c['limit']} exceeded")
        scenario = _store(session, event, results, "CUSTOM", [
            {"supplier": r["supplier"], "supplierId": r["supplierId"], "share": str(sh.quantize(QUANT4)), "monthlyQty": str((line.monthly_qty * sh).quantize(Decimal("1"))),
             "annualQty": str((line.annual_qty * sh).quantize(Decimal("1"))), "priceMinor": r["priceMinor"], "tcoMinor": r["tcoMinor"],
             "capacityVerified": bool(r.get("capacityVerified", True)), "tcoIncomplete": bool(r.get("tcoIncomplete"))} for r, sh in pairs],
            not violations, {"rule": "manual split entered by the buyer", "violations": violations, "risk": _risk_explanation(info, rc, excluded, checks)},
            weighted_price, weighted_tco, savings)
    else:
        context = _AwardContext(event, event_lines, [r for r in matrix if r["supplierId"] not in excluded], info, rc)
        plan = _Plan()
        plan.annual = {l.line_no: l.annual_qty for l in event_lines}
        for line_no, entries in per_line.items():
            plan.lines[line_no] = []
            for code, share in entries:
                row = next((r for r in context.by_line[line_no] if r["supplier"] == code), None)
                if row is None:
                    violations.append(f"{code} is not an eligible bidder on line {line_no}")
                    continue
                plan.lines[line_no].append((row, share, row["priceMinor"], row["tcoMinor"]))
        checks = _share_checks(plan.supplier_values(), info, rc)
        for c in checks:
            if not c["ok"]:
                violations.append(f"{c['rule']}: limit {c['limit']} exceeded")
        baseline_value = (sum(Decimal(l.baseline_price_minor) * l.annual_qty for l in event_lines)
                          if all(l.baseline_price_minor is not None for l in event_lines) else None)
        price = plan.price_value()
        scenario = _store(session, event, results, "CUSTOM", plan.allocations(context), not violations,
                          {"rule": "manual split entered by the buyer", "basis": "ANNUAL_VALUE", "violations": violations, "lots": [],
                           "risk": _risk_explanation(info, rc, excluded, checks)}, price, plan.tco_value(),
                          int(baseline_value - price) if baseline_value is not None else None)
    audit.record(session, "SOURCING_EVENT", event.id, "SCENARIO_CUSTOM", object_ref=event.number,
                 after={"scenario": str(scenario.id), "feasible": scenario.feasible, "violations": violations})
    return {"id": str(scenario.id), "kind": scenario.kind, "feasible": scenario.feasible, "allocations": scenario.allocations,
            "weightedPriceMinor": scenario.weighted_price_minor, "weightedTcoMinor": scenario.weighted_tco_minor,
            "annualSavingsMinor": scenario.annual_savings_minor, "riskScore": scenario.risk_score, "explanation": scenario.explanation}


# ---------------------------------------------------------------- award (F3-07/08/09)
def award_gate(session: Session, event: SourcingEvent, scenario: AwardScenario, rows: list[dict], pol: dict, rationale: Optional[str],
               expired_override: Optional[str] = None) -> dict:
    """Everything that must hold before an award is proposed, and the exceptions that make a written rationale mandatory.

    Blocks (422): a supplier whose bid is no longer in the evaluation (disqualified, withdrawn), a failed or pending technical gate, criteria nobody
    scored (policy requireAllCriteriaScored), a lead time that cannot meet the need date (policy leadTimeCheck ENFORCE). Block (409
    BID_OFFER_EXPIRED, D5): an awarded bid whose offer validity has ended, unless ``expired_override`` gives the written reason of a user the policy
    (``expiredOfferOverride``) allows to override; the override is then recorded as exception BID_OFFER_EXPIRED. Exceptions: NOT_LOWEST (a bid
    that is not the lowest eligible price), LIMITED_COMPETITION (fewer valid bidders than the minimum), INCOMPLETE_TCO (a missing TCO input), UNVERIFIED_CAPACITY (volume to a supplier nobody verified), NEGATIVE_SAVINGS (the award costs
    more than the baseline), LEAD_TIME_AFTER_NEED (policy WARN). The first five need the rationale of at least ``minRationaleChars`` characters."""
    by_supplier = {r["supplier"]: r for r in rows}
    awarded = [a["supplier"] for a in scenario.allocations]
    lines_of = {a["supplier"]: a.get("lines") for a in scenario.allocations}
    for code in awarded:
        row = by_supplier.get(code)
        if row is None:
            raise Problem(422, "BID_NOT_EVALUATED", f"{code} has no evaluated bid in {event.number} any more (disqualified or withdrawn): rebuild the scenarios",
                          rule_ref="SRC-AWARD")
        gate = row["technicalGate"]
        if not gate["passed"] or gate["pending"]:
            raise Problem(422, "TECHNICAL_GATE", f"{code} " + (f"scored below the minimum on {', '.join(gate['failed'])}" if gate["failed"]
                                                                 else f"has no score yet on {', '.join(gate['pending'])} (technical gate)"), rule_ref="SRC-AWARD")
        if pol.get("requireAllCriteriaScored", True) and row["unscored"]:
            raise Problem(422, "UNSCORED_CRITERIA", f"{code} was not scored on {', '.join(row['unscored'])}: every manual criterion needs a score before the award",
                          rule_ref="SRC-AWARD")
    expired = expired_offers(session, event, awarded, by_supplier)
    override = check_expired_override(session, event, expired, pol, expired_override) if expired else None
    # lowest eligible price (the bids the award could have gone to)
    excluded_ids = {e["supplierId"] for e in ((scenario.explanation or {}).get("risk") or {}).get("excluded", [])}
    eligible = [r for r in rows if r["technicalGate"]["passed"] and r["supplierId"] not in excluded_ids] or rows
    multi = len(_lines(session, event)) > 1
    exceptions: list[dict] = []
    if multi:
        lowest = {}
        for r in eligible:
            for l in r["lines"]:
                lowest[l["line"]] = min(lowest.get(l["line"], l["priceMinor"]), l["priceMinor"])
        not_lowest = any(l["priceMinor"] > lowest.get(l["line"], 0) for a in scenario.allocations for l in a["lines"])
    else:
        lowest_price = min(r["priceMinor"] for r in eligible)
        not_lowest = any(a["priceMinor"] > lowest_price for a in scenario.allocations)
    if not_lowest:
        exceptions.append({"code": "NOT_LOWEST", "detail": "the award includes a bid that is not the lowest eligible price"})
    if pol.get("limitedCompetitionNeedsRationale", True) and len(rows) < int(event.min_bidders or 1):
        exceptions.append({"code": "LIMITED_COMPETITION", "detail": f"{len(rows)} valid bidder(s); the minimum is {event.min_bidders}"})
    incomplete = sorted(code for code in awarded if by_supplier[code]["tcoIncomplete"])
    if incomplete:
        exceptions.append({"code": "INCOMPLETE_TCO", "detail": "total cost has a missing input for " + ", ".join(
            f"{c} ({', '.join(by_supplier[c]['tcoMissing'])})" for c in incomplete)})
    unverified = sorted(code for code in awarded if not by_supplier[code]["capacityVerified"])
    if unverified:
        exceptions.append({"code": "UNVERIFIED_CAPACITY", "detail": "capacity is not verified (no bid capacity and no twin figure) for " + ", ".join(unverified)})
    if override:
        exceptions.append({"code": "BID_OFFER_EXPIRED", "detail": "awarded on an expired offer (override): " + ", ".join(
            f"{b['supplier']} valid until {b['validUntil']}" for b in expired) + f". Reason: {override['reason']}", "override": override})
    if scenario.annual_savings_minor is not None and scenario.annual_savings_minor < 0:
        exceptions.append({"code": "NEGATIVE_SAVINGS", "detail": f"the award costs {abs(int(scenario.annual_savings_minor)) / 100:,.2f} a year more than the baseline"})
    check = str(pol.get("leadTimeCheck", "WARN")).upper()
    if check != "OFF" and event.need_date is not None:
        late = sorted(code for code in awarded if clock.today() + timedelta(days=int(by_supplier[code]["leadTimeDays"])) > event.need_date)
        if late and check == "ENFORCE":
            raise Problem(422, "LEAD_TIME_AFTER_NEED", f"{', '.join(late)} cannot deliver by the need date {event.need_date}: their lead time starts today",
                          rule_ref="SRC-NEEDDATE")
        if late:
            exceptions.append({"code": "LEAD_TIME_AFTER_NEED", "detail": f"{', '.join(late)} cannot deliver by the need date {event.need_date} (lead time from today)"})
    optional = {"INCOMPLETE_TCO": "incompleteTcoNeedsRationale", "UNVERIFIED_CAPACITY": "unverifiedCapacityNeedsRationale"}   # recorded always, a rationale when the policy says so
    needs = [e for e in exceptions if e["code"] in EXCEPTION_NEEDS_RATIONALE and (e["code"] not in optional or pol.get(optional[e["code"]], False))]
    minimum = int(pol.get("minRationaleChars", 15))
    if needs and not (rationale or "").strip():
        first = needs[0]
        raise rule_violation("Award to a non-lowest bid needs a written rationale" if first["code"] == "NOT_LOWEST" else
                             f"This award needs a written rationale: {first['detail']}", "SRC-RATIONALE", exceptions=needs)
    if needs and len((rationale or "").strip()) < minimum:
        raise rule_violation(f"The written rationale is at least {minimum} characters (say why: {needs[0]['detail']})", "SRC-RATIONALE", exceptions=needs)
    needs_approval = bool(needs) or bool(override and override_policy(pol)["requiresApproval"])
    return {"exceptions": exceptions, "notLowest": not_lowest, "needsApproval": needs_approval, "bidders": len(rows), "override": override}


# ---------------------------------------------------------------- D5: an award on an expired offer is blocked unless overridden
EXPIRED_OFFER_CODE = "BID_OFFER_EXPIRED"


def override_policy(pol: dict) -> dict:
    """SOURCING-POLICY.expiredOfferOverride with its defaults (sourcing_defaults.POLICY_DEFAULT)."""
    default = sourcing_defaults.POLICY_DEFAULT["expiredOfferOverride"]
    value = pol.get("expiredOfferOverride") if isinstance(pol.get("expiredOfferOverride"), dict) else {}
    return {**default, **value}


def expired_offers(session: Session, event: SourcingEvent, awarded: list[str], by_supplier: dict) -> list[dict]:
    """The awarded bids whose offer validity (``valid_until``, given by the supplier) ended before today: [{supplier, supplierName, validUntil,
    round, daysExpired}]."""
    out = []
    for code in awarded:
        row = by_supplier.get(code) or {}
        if row.get("validUntil") and date.fromisoformat(row["validUntil"]) < clock.today():
            until = date.fromisoformat(row["validUntil"])
            supplier = session.get(Supplier, uuid.UUID(row["supplierId"]))
            out.append({"supplier": code, "supplierName": supplier.legal_name if supplier else None, "validUntil": row["validUntil"],
                        "round": row.get("round", event.round), "daysExpired": (clock.today() - until).days})
    return out


def may_override_expired(principal_, event: SourcingEvent, pol: dict) -> bool:
    """Whether the user may lift the expired-offer block: holds a role of SOURCING-POLICY.expiredOfferOverride.roles (a category manager only for
    the event's category, as in auction._require_manager)."""
    for role in override_policy(pol)["roles"] or []:
        if role not in principal_.roles:
            continue
        if role == "CATEGORY_MANAGER":
            categories = principal_.attr("categories") or []
            if "*" not in categories and event.category not in categories:
                continue
        return True
    return False


def check_expired_override(session: Session, event: SourcingEvent, expired: list[dict], pol: dict, reason: Optional[str]) -> dict:
    """Raise 409 BID_OFFER_EXPIRED (the expired bids, who may override, how to get the offers extended) when no override is given; 403 when the user
    may not override; 422 when the reason is too short. Returns the override record {by, byEmail, byName, at, reason, bids} kept on the award
    decision."""
    p = principal(session)
    policy = override_policy(pol)
    allowed = may_override_expired(p, event, pol)
    text_ = (reason or "").strip()
    if not text_:
        names = ", ".join(f"{b['supplier']} (valid until {b['validUntil']})" for b in expired)
        log_refusal(session, event, "AWARD_BLOCKED_OFFER_EXPIRED", f"award refused: offer validity ended for {names}", bids=expired, user=p.email)
        raise Problem(409, EXPIRED_OFFER_CODE,
                      f"{event.number}: the offer of {names} has expired. Ask the supplier to confirm or extend its offer in a new round "
                      f"(POST /v1/sourcing/events/{event.number}/rounds) before awarding, or override with a written reason "
                      f"(at least {policy['minReasonChars']} characters; {' / '.join(policy['roles']) or 'nobody'} of the category).",
                      rule_ref="SRC-AWARD", expiredBids=expired, overrideAllowed=allowed, overrideRoles=list(policy["roles"]),
                      minReasonChars=int(policy["minReasonChars"]),
                      extendValidity={"action": "NEW_ROUND", "method": "POST", "path": f"/v1/sourcing/events/{event.number}/rounds",
                                      "hint": "A new round asks the suppliers to resubmit with a new offer validity (valid_until)"})
    if not allowed:
        raise Problem(403, "OVERRIDE_NOT_ALLOWED", f"Only a {' / '.join(policy['roles']) or '(nobody)'} of category {event.category} may award on an "
                      "expired offer (SOURCING-POLICY.expiredOfferOverride)", rule_ref="SRC-AWARD", expiredBids=expired)
    if len(text_) < int(policy["minReasonChars"]):
        raise Problem(422, "REASON_REQUIRED", f"The override reason is at least {policy['minReasonChars']} characters: say why the expired price "
                      "still holds (e.g. the supplier confirmed it in writing)", rule_ref="SRC-AWARD", expiredBids=expired)
    return {"by": str(p.user_id), "byEmail": p.email, "byName": p.name, "at": clock.now().isoformat(), "reason": text_, "bids": expired}


def propose_award(session: Session, event: SourcingEvent, scenario_id: uuid.UUID, rationale: Optional[str],
                  conflict_declaration: str, expired_offer_override: Optional[str] = None) -> AwardDecision:
    p = principal(session)
    auction_svc._require_manager(session, event)
    abac.guard(session, "SOURCING_MANAGE", event)
    if event.status != "UNDER_EVALUATION":
        raise illegal_transition("Sourcing event", event.number, event.status, "propose_award")
    scenario = session.get(AwardScenario, scenario_id)
    if scenario is None or scenario.event_id != event.id or not scenario.feasible:
        raise rule_violation("Choose a feasible scenario of this event", "SRC-AWARD")
    for allocation in scenario.allocations:
        _require_eligible(session, event, session.get(Supplier, uuid.UUID(allocation["supplierId"])), "be awarded")
    if (scenario.explanation or {}).get("supersededAt"):
        raise rule_violation("This scenario was superseded when the scenarios were rebuilt; choose a current one", "SRC-AWARD")
    if not (conflict_declaration or "").strip():
        raise rule_violation("A conflict-of-interest declaration is required", "SRC-05")
    declared = session.execute(select(EvaluatorDeclaration).where(EvaluatorDeclaration.event_id == event.id,
                                                                  EvaluatorDeclaration.user_id == p.user_id)).scalar_one_or_none()
    if declared is not None and declared.has_conflict:
        raise Problem(403, "EVALUATOR_CONFLICT", f"You declared a conflict of interest in {event.number}: you cannot propose its award", rule_ref="SRC-05")
    pol = policy_of(session, event)
    rows = evaluation_matrix(session, event)
    event_lines = _lines(session, event)
    multi = len(event_lines) > 1
    gate = award_gate(session, event, scenario, rows, pol, rationale, expired_offer_override)
    not_lowest = gate["notLowest"]
    annual_value = int(scenario.weighted_price_minor) if multi else int(Decimal(scenario.weighted_price_minor) * event_lines[0].annual_qty)
    abac.guard(session, "AWARD_APPROVE", event, value_minor=annual_value)
    sod.guard_and_record(session, "SOURCING_AWARD", {"event_id": event.id})
    rule = rules.resolve(session, "AWARD-APPROVAL", category=event.category)
    band_chain = rules.band_chain(rule, annual_value)
    chain = ind_healthcare.award_chain(rule, band_chain, event.category)  # + clinical sign-off (healthcare rule)
    decision = AwardDecision(tenant_id=event.tenant_id, event_id=event.id, scenario_id=scenario.id, status="PENDING",
                             rationale=rationale, conflict_declarations=[{"user": p.email, "declaration": conflict_declaration}],
                             proposed_by=p.user_id, annual_value_minor=annual_value, rule_set_version=rule.ref, created_by=p.user_id,
                             authority={"valueMinor": annual_value, "chain": chain, "bandChain": band_chain, "approvalAboveMinor": rule.body["approvalAboveMinor"],
                                        "rule": rule.ref}, exceptions=gate["exceptions"])
    session.add(decision)
    session.flush()
    SM.apply(session, event, "propose_award", reason=rationale, rule_set_version=rule.ref)
    if gate["override"]:
        _record_expired_override(session, event, decision, gate["override"])
    instance = workflow.find(session, "SOURCING_EVENT", event.id, PROCESS)
    workflow.step(session, instance, "F3-06", outcome=f"{scenario.kind} proposed")
    needs_approval = (annual_value >= rule.body["approvalAboveMinor"] or not_lowest or gate["needsApproval"]
                      or ind_healthcare.signoff_required(rule, event.category))
    workflow.step(session, instance, "F3-07", outcome=("yes" if needs_approval else "no") +
                  f": annual value {fmt_inr(annual_value)}" + (", not lowest bid" if not_lowest else "")
                  + (f", {len(gate['exceptions'])} exception(s): " + ", ".join(e["code"] for e in gate["exceptions"]) if gate["exceptions"] else ""))
    if not needs_approval:
        _award(session, event, decision, instance)
        return decision
    workflow.start_approval(session, instance, "AWARD_APPROVAL", object_type="SOURCING_EVENT", object_id=event.id,
                            object_ref=event.number, chain=chain, step_id="F3-08", initiator_id=p.user_id,
                            scopes={"CATEGORY_MANAGER": {"category": event.category}}, rule_set_version=rule.ref,
                            evidence={"scenario": scenario.kind, "allocations": scenario.allocations, "rationale": rationale,
                                      "exceptions": gate["exceptions"]})
    return decision


def _record_expired_override(session: Session, event: SourcingEvent, decision: AwardDecision, override: dict) -> None:
    """The override of the expired-offer block (D5): audited on the event and emitted (sourcing.award.offer_expiry_overridden)."""
    audit.record(session, "SOURCING_EVENT", event.id, "AWARD_EXPIRED_OFFER_OVERRIDDEN", object_ref=event.number, reason=override["reason"],
                 after={"decision": str(decision.id), "bids": override["bids"], "by": override["byEmail"]})
    outbox.emit(session, "sourcing.award.offer_expiry_overridden", "SOURCING_EVENT", event.id, event.number,
                {"decisionId": str(decision.id), "scenarioId": str(decision.scenario_id), "category": event.category, "round": event.round,
                 "reason": override["reason"], "overriddenBy": override["byEmail"], "overriddenAt": override["at"],
                 "bids": [{"supplier": b["supplier"], "validUntil": b["validUntil"], "daysExpired": b["daysExpired"]} for b in override["bids"]],
                 "annualValueMinor": int(decision.annual_value_minor)})


def _expired_without_override(session: Session, event: SourcingEvent, decision: Optional[AwardDecision]) -> list[dict]:
    """Bids of the pending award whose offer has expired since it was proposed (or that the proposer did not override)."""
    if decision is None:
        return []
    scenario = session.get(AwardScenario, decision.scenario_id)
    if scenario is None:
        return []
    overridden = {b["supplier"] for e in decision.exceptions or [] if e.get("code") == EXPIRED_OFFER_CODE
                  for b in (e.get("override") or {}).get("bids") or []}
    by_supplier = {r["supplier"]: r for r in evaluation_matrix(session, event)}
    return [b for b in expired_offers(session, event, [a["supplier"] for a in scenario.allocations], by_supplier) if b["supplier"] not in overridden]


@workflow.guard_task("AWARD_APPROVAL")
def _award_sod(session: Session, task: Task, decision: str) -> None:
    if decision == "APPROVE":
        sod.guard(session, "SOURCING_AWARD", {"event_id": task.object_id})
        event = session.get(SourcingEvent, task.object_id)
        pending = session.execute(select(AwardDecision).where(AwardDecision.event_id == event.id,
                                                              AwardDecision.status == "PENDING")).scalar_one_or_none()
        scenario = session.get(AwardScenario, pending.scenario_id) if pending else None
        for allocation in (scenario.allocations if scenario else []):
            _require_eligible(session, event, session.get(Supplier, uuid.UUID(allocation["supplierId"])), "be awarded")
        expired = _expired_without_override(session, event, pending)
        if expired:  # D5: an offer ran out while the award waited for its approvers, and nobody overrode it
            raise Problem(409, EXPIRED_OFFER_CODE, f"{event.number}: the offer of " + ", ".join(f"{b['supplier']} (valid until {b['validUntil']})"
                          for b in expired) + " expired while the award waited for approval. Return the award: the proposer asks for an extension "
                          "in a new round or proposes again with a written override", rule_ref="SRC-AWARD", expiredBids=expired)


@workflow.on_task("AWARD_APPROVAL")
def _award_decided(session: Session, task: Task, outcome: str) -> None:
    event = session.get(SourcingEvent, task.object_id)
    decision = session.execute(select(AwardDecision).where(AwardDecision.event_id == event.id, AwardDecision.status == "PENDING")).scalar_one()
    instance = workflow.find(session, "SOURCING_EVENT", event.id, PROCESS)
    if outcome != "APPROVED":
        decision.status = "REJECTED"
        SM.apply(session, event, "reject_award", reason=task.comment)
        workflow.wait(session, instance, "F3-06", outcome=f"award {outcome.lower()}: {task.comment}")
        return
    _award(session, event, decision, instance)


def _award_payload(session: Session, event: SourcingEvent, scenario: AwardScenario, decision: AwardDecision, event_lines: list[EventLine]) -> dict:
    first = event_lines[0]
    requisition = session.get(Requisition, first.requisition_id) if first.requisition_id else None
    from app.pic.services import should_cost as should_cost_svc

    multi = len(event_lines) > 1
    payload = {"category": event.category, "baselineMinor": event.baseline_price_minor, "weightedPriceMinor": scenario.weighted_price_minor,
               "baselineMethod": event.baseline_method, "scenario": scenario.kind, "exceptions": [e["code"] for e in (decision.exceptions or [])],
               "savings": should_cost_svc.savings_summary(event.baseline_price_minor, scenario.weighted_price_minor,
                                                          Decimal(1) if multi else event_lines[0].annual_qty, event.baseline_method),
               "needDate": event.need_date.isoformat() if event.need_date else None,
               "allocations": scenario.allocations, "ownerId": str(event.owner_id), "rationale": decision.rationale,
               "companyCode": requisition.company_code if requisition else None,  # the award contract's company code
               "inviteeSupplierIds": [str(i.supplier_id) for i in session.execute(select(Invitee).where(Invitee.event_id == event.id)).scalars()]}
    if len(event_lines) == 1:
        payload.update(materialId=str(first.material_id) if first.material_id else None, description=first.description, plant=first.plant,
                       annualQty=str(first.annual_qty), monthlyQty=str(first.monthly_qty), uom=first.uom,
                       requisitionId=str(first.requisition_id), prLine=first.pr_line_no)
        return payload
    # Several lines: the value fields follow the annual-value basis the savings tracker uses (baseline value, award value, quantity 1).
    payload.update(multiLine=True, annualQty="1", materialId=None, description=event.title, plant=first.plant, uom="EA",
                   requisitionId=str(first.requisition_id), prLine=first.pr_line_no,
                   lines=[{"line": l.line_no, "eventLineId": str(l.id), "materialId": str(l.material_id) if l.material_id else None,
                           "description": l.description, "plant": l.plant, "uom": l.uom, "annualQty": str(l.annual_qty),
                           "monthlyQty": str(l.monthly_qty), "lot": l.lot_code, "baselineMinor": l.baseline_price_minor,
                           "sources": [{"requisitionId": str(rid), "prLine": n} for rid, n in line_sources(session, l)]} for l in event_lines])
    return payload


def _regret_letters(session: Session, event: SourcingEvent, decision: AwardDecision, awarded: set) -> list[dict]:
    """One regret letter per bidder that was not awarded (not selected, disqualified, bid not evaluable). The letter says what happened to the
    supplier's own bid and its own rank, never a competitor's name, price or score. Withdrawn bids get none (the supplier withdrew)."""
    rows = {r["supplier"]: r for r in evaluation_matrix(session, event)}
    letters = []
    for bid in session.execute(select(Bid).where(Bid.event_id == event.id, Bid.status.in_(("UNSEALED", "DISQUALIFIED", "INVALID")))
                               .order_by(Bid.created_at)).scalars():
        supplier = session.get(Supplier, bid.supplier_id)
        if supplier.code in awarded:
            continue
        if bid.status == "UNSEALED":
            row = rows.get(supplier.code)
            reason, detail = "NOT_SELECTED", f"your bid ranked {row['rank']} of {len(rows)} on total cost of ownership and score" if row else "your bid was not selected"
        elif bid.status == "DISQUALIFIED":
            reason, detail = "DISQUALIFIED", bid.disqualified_reason or "your bid was disqualified"
        else:
            reason, detail = "NOT_EVALUABLE", "your bid had no line that could be evaluated against the event"
        letters.append({"supplier": supplier.code, "supplierId": str(supplier.id), "reason": reason})
        outbox.emit(session, "sourcing.award.regret", "SOURCING_EVENT", event.id, event.number,
                    {"supplier": supplier.code, "supplierId": str(supplier.id), "reason": reason, "detail": detail, "round": bid.round,
                     "rank": rows[supplier.code]["rank"] if supplier.code in rows else None, "bidders": len(rows)})
    decision.regret_sent_at = clock.now()
    return letters


def _award(session: Session, event: SourcingEvent, decision: AwardDecision, instance) -> None:
    decision.status = "APPROVED"
    scenario = session.get(AwardScenario, decision.scenario_id)
    SM.apply(session, event, "award", rule_set_version=decision.rule_set_version)
    sod.record(session, "SOURCING_AWARD", {"event_id": event.id})
    event_lines = _lines(session, event)
    for line in event_lines:
        for requisition_id, pr_line_no in line_sources(session, line):
            for pr_line in session.execute(select(PrLine).where(PrLine.requisition_id == requisition_id, PrLine.line_no == pr_line_no)).scalars():
                pr_line.sourcing_status = "SOURCED"
    awarded = {a["supplier"] for a in scenario.allocations}
    regrets = _regret_letters(session, event, decision, awarded)
    payload = _award_payload(session, event, scenario, decision, event_lines)
    payload["regretSupplierIds"] = [r["supplierId"] for r in regrets]  # told by their own letter: the generic "awarded elsewhere" notice skips them
    outbox.emit(session, "sourcing.event.awarded", "SOURCING_EVENT", event.id, event.number, payload)
    audit.record(session, "SOURCING_EVENT", event.id, "AWARD_NOTIFIED", object_ref=event.number,
                 after={"awarded": [a["supplier"] for a in scenario.allocations],
                        "notifiedUnsuccessful": [r["supplier"] for r in evaluation_matrix(session, event) if r["supplier"] not in awarded],
                        "regretLetters": [r["supplier"] for r in regrets]})
    workflow.step(session, instance, "F3-09", outcome="suppliers notified; handed off to contract (CLM)")
    if len(event_lines) == 1:
        summary = " / ".join(f"{a['supplier']} {Decimal(a['share'])*100:.0f}% @ {a['priceMinor']/100:.2f}" for a in scenario.allocations) \
            + f"; weighted {scenario.weighted_price_minor/100:.2f}"
    else:
        summary = " / ".join(f"{a['supplier']} {len(a['lines'])} line(s) {a['valueMinor']/100:,.2f}" for a in scenario.allocations) \
            + f"; annual value {scenario.weighted_price_minor/100:,.2f}"
    workflow.end(session, instance, "F3-10", outcome=summary)


# ---------------------------------------------------------------- cancellation (any state before the award)
def cancel(session: Session, event: SourcingEvent, reason: str) -> dict:
    """Cancel an event that is not awarded yet (owner or category manager, reason required). Only this event's open tasks
    (award approval) and timers (close, task SLA) are closed, a pending award decision is withdrawn, requirement lines no
    other live event is sourcing go back to OPEN, and ``sourcing.event.cancelled`` notifies the invited suppliers (once the
    event was published) and marks the savings initiative lost."""
    reason = (reason or "").strip()
    if not reason:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for the cancellation", rule_ref="SRC-CANCEL")
    if not SM.can(event.status, "cancel"):
        raise illegal_transition("Sourcing event", event.number, event.status, "cancel")
    auction_svc._require_manager(session, event)
    now, before = clock.now(), event.status
    tasks = session.execute(select(Task).where(Task.object_type == "SOURCING_EVENT", Task.object_id == event.id,
                                               Task.status == "OPEN")).scalars().all()
    for task in tasks:
        task.status = "CANCELLED"
    timers = list(session.execute(select(Timer).where(Timer.object_id == event.id, Timer.fired_at.is_(None))).scalars())
    if tasks:
        timers += session.execute(select(Timer).where(Timer.object_id.in_([t.id for t in tasks]), Timer.fired_at.is_(None))).scalars().all()
    for timer in timers:
        timer.fired_at, timer.payload = now, {**(timer.payload or {}), "cancelled": True}
    withdrawn = []
    for decision in session.execute(select(AwardDecision).where(AwardDecision.event_id == event.id, AwardDecision.status == "PENDING")).scalars():
        decision.status = "CANCELLED"
        withdrawn.append(str(decision.id))
    released = []
    for line in _lines(session, event):
        for requisition_id, pr_line_no in line_sources(session, line):
            pr_line = session.execute(select(PrLine).where(PrLine.requisition_id == requisition_id, PrLine.line_no == pr_line_no)).scalar_one_or_none()
            if pr_line is None or pr_line.sourcing_status != "IN_SOURCING":
                continue
            elsewhere = session.execute(select(EventLine.id).join(SourcingEvent, SourcingEvent.id == EventLine.event_id).where(
                EventLine.event_id != event.id, SourcingEvent.status.not_in(("CANCELLED", "AWARDED")),
                (EventLine.requisition_id == requisition_id) & (EventLine.pr_line_no == pr_line_no)
                | EventLine.id.in_(select(EventLineSource.event_line_id).where(EventLineSource.requisition_id == requisition_id,
                                                                               EventLineSource.pr_line_no == pr_line_no))).limit(1)).first()
            if elsewhere is None:
                pr_line.sourcing_status = "OPEN"
                released.append(f"{session.get(Requisition, requisition_id).number}/{pr_line_no}")
    invitees = [str(i.supplier_id) for i in session.execute(select(Invitee).where(Invitee.event_id == event.id)).scalars()]
    SM.apply(session, event, "cancel", reason=reason,
             extra_after={"from": before, "round": event.round, "tasksCancelled": len(tasks), "timersCancelled": len(timers),
                          "awardDecisionsWithdrawn": withdrawn, "requirementsReleased": released})
    # Suppliers never saw a draft; once published every invitee is told.
    outbox.emit(session, "sourcing.event.cancelled", "SOURCING_EVENT", event.id, event.number,
                {"from": before, "reason": reason, "round": event.round, "category": event.category, "ownerId": str(event.owner_id),
                 "inviteeSupplierIds": invitees if before != "DRAFT" else []})
    instance = workflow.find(session, "SOURCING_EVENT", event.id, PROCESS)
    if instance is not None and instance.status == "RUNNING":
        workflow.end(session, instance, instance.current_step or "F3-02", outcome=f"cancelled: {reason}", status="CANCELLED")
    return {"event": event.number, "status": event.status, "from": before, "tasksCancelled": len(tasks),
            "timersCancelled": len(timers), "requirementsReleased": released}


# ---------------------------------------------------------------- invitation filters by segment and risk (22)
def invitee_candidates(session: Session, category: str, *, segment: Optional[str] = None, max_risk_score: Optional[int] = None,
                       statuses: Optional[list] = None, search: Optional[str] = None, exclude_signal_categories: Optional[list] = None) -> dict:
    """Suppliers that may be invited to an event in the category, with segment and risk, filtered by segment, risk score, qualification
    status and open risk-signal categories. Conditional suppliers are listed with ``waiverNeeded``."""
    wanted = [s.upper() for s in (statuses or ["QUALIFIED", "PREFERRED", "CONDITIONAL"])]
    bad = [s for s in wanted if s not in ("QUALIFIED", "PREFERRED", "CONDITIONAL")]
    if bad:
        raise Problem(422, "INVALID_FILTER", "status must be QUALIFIED, PREFERRED or CONDITIONAL", rule_ref="SRC-INVITE")
    if segment and segment.upper() not in ("STRATEGIC", "LEVERAGE", "BOTTLENECK", "ROUTINE", "UNSEGMENTED"):
        raise Problem(422, "INVALID_FILTER", "segment must be STRATEGIC, LEVERAGE, BOTTLENECK, ROUTINE or UNSEGMENTED", rule_ref="SRC-INVITE")
    out, hidden = [], {"segment": 0, "risk": 0, "signals": 0}
    from app.pic.models import RiskSignal

    for status, supplier in session.execute(
            select(SupplierCategoryStatus.status, Supplier).join(Supplier, Supplier.id == SupplierCategoryStatus.supplier_id).where(
                SupplierCategoryStatus.category == category, SupplierCategoryStatus.status.in_(wanted), Supplier.status != "BLOCKED")
            .order_by(Supplier.code)).all():
        if search and search.lower() not in f"{supplier.code} {supplier.legal_name}".lower():
            continue
        seg = supplier.segment or "UNSEGMENTED"
        if segment and seg != segment.upper():
            hidden["segment"] += 1
            continue
        risk = risk_svc.supplier_risk_score(session, supplier)
        if max_risk_score is not None and risk["score"] > max_risk_score:
            hidden["risk"] += 1
            continue
        open_signals = sorted({s.category for s in session.execute(select(RiskSignal).where(
            RiskSignal.supplier_id == supplier.id, RiskSignal.status != "CLOSED")).scalars()})
        if exclude_signal_categories and set(c.upper() for c in exclude_signal_categories) & set(open_signals):
            hidden["signals"] += 1
            continue
        out.append({"code": supplier.code, "name": supplier.legal_name, "status": status, "waiverNeeded": status == "CONDITIONAL",
                    "segment": seg, "riskScore": risk["score"], "riskLevel": risk["level"], "openSignals": open_signals,
                    "state": supplier.state_code})
    return {"category": category, "filters": {"segment": segment, "maxRiskScore": max_risk_score, "statuses": wanted, "search": search,
                                              "excludeSignalCategories": exclude_signal_categories or []},
            "hiddenByFilter": hidden, "candidates": out}


# ---------------------------------------------------------------- requirement bundling (20)
def bundle_candidates(session: Session, *, category: Optional[str] = None, origin: Optional[str] = None, category_plan: Optional[str] = None,
                      plant: Optional[str] = None) -> dict:
    """Approved requisition lines still open for sourcing, optionally for the category of a category plan or only those that came from
    an MRP run, grouped by category, material and plant. The result feeds the bundle preview."""
    plan = None
    if category_plan:
        plan = session.execute(select(CategoryPlan).where(CategoryPlan.number == category_plan)).scalar_one_or_none()
        if plan is None:
            raise not_found("Category plan", category_plan)
        category = plan.category
    query = select(PrLine, Requisition).join(Requisition, Requisition.id == PrLine.requisition_id).where(
        Requisition.status.in_(("APPROVED", "PARTIALLY_ORDERED")), PrLine.sourcing_status == "OPEN").order_by(Requisition.number, PrLine.line_no)
    if origin:
        query = query.where(Requisition.origin == origin.upper())
    if plant:
        query = query.where(PrLine.plant == plant)
    items = []
    for line, pr in session.execute(query).all():
        line_category = line.category or line.material_group
        if category and line_category != category:
            continue
        items.append({"requisition": pr.number, "line": line.line_no, "origin": pr.origin, "category": line_category, "description": line.description,
                      "materialId": str(line.material_id) if line.material_id else None, "plant": line.plant, "qty": str(line.qty), "uom": line.uom,
                      "needDate": line.need_date.isoformat(), "valueMinor": int(Decimal(line.price_est_minor) * line.qty),
                      "companyCode": pr.company_code})
    return {"category": category, "categoryPlan": plan.number if plan else None, "origin": origin, "items": items,
            "totalValueMinor": sum(i["valueMinor"] for i in items)}


def bundle_preview(session: Session, selections: list[dict], *, kind: str = "PR_LINES", ref: Optional[str] = None) -> dict:
    """Merge selected requisition lines into proposed event lines: lines with the same material, plant and unit become one line whose
    quantity is the sum (every source stays linked); free-text lines stay separate. Warns about mixed company codes and lines already in
    sourcing. The proposal is sent to POST /sourcing/events as ``lines`` (with ``sources``)."""
    if not selections:
        raise Problem(422, "INVALID_LINES", "Select at least one requisition line", rule_ref="SRC-BUNDLE")
    merged, order, warnings, companies, origins, categories = {}, [], [], set(), set(), set()
    for sel in selections:
        pr = session.execute(select(Requisition).where(Requisition.number == sel["requisition"])).scalar_one_or_none()
        if pr is None:
            raise not_found("Requisition", sel["requisition"])
        if pr.status not in ("APPROVED", "PARTIALLY_ORDERED"):
            raise rule_violation(f"Requirement {pr.number} is not an approved requisition", "P06")
        line = session.execute(select(PrLine).where(PrLine.requisition_id == pr.id, PrLine.line_no == int(sel["line"]))).scalar_one_or_none()
        if line is None:
            raise not_found("Requisition line", f"{pr.number}/{sel['line']}")
        if line.sourcing_status != "OPEN":
            warnings.append(f"{pr.number}/{line.line_no} is {line.sourcing_status} and cannot be bundled")
            continue
        companies.add(pr.company_code)
        origins.add(pr.origin)
        categories.add(line.category or line.material_group)
        key = (str(line.material_id), line.plant, line.uom) if line.material_id else ("FREE", pr.number, line.line_no)
        if key not in merged:
            merged[key] = {"description": line.description, "materialId": str(line.material_id) if line.material_id else None, "plant": line.plant,
                           "uom": line.uom, "qty": Decimal(0), "sources": [], "valueMinor": 0, "needDate": line.need_date}
            order.append(key)
        entry = merged[key]
        entry["qty"] += line.qty
        entry["valueMinor"] += int(Decimal(line.price_est_minor) * line.qty)
        entry["needDate"] = min(entry["needDate"], line.need_date)
        entry["sources"].append({"requisition": pr.number, "line": line.line_no, "qty": str(line.qty)})
    if len(companies) > 1:
        warnings.append(f"The lines belong to several company codes ({', '.join(sorted(companies))}); one event needs one company code")
    if len(categories) > 1:
        warnings.append(f"The lines belong to several categories ({', '.join(sorted(categories))}); one event has one category")
    if kind == "MRP_DEMAND" and origins != {"MRP"}:
        warnings.append("Not every selected requisition came from an MRP run")
    proposed = [{"description": merged[k]["description"], "materialId": merged[k]["materialId"], "plant": merged[k]["plant"], "uom": merged[k]["uom"],
                 "qty": str(merged[k]["qty"]), "annual_qty": str(merged[k]["qty"]), "monthly_qty": str((merged[k]["qty"] / 12).quantize(QUANT3)),
                 "needDate": merged[k]["needDate"].isoformat(), "valueMinor": merged[k]["valueMinor"], "sources": merged[k]["sources"]} for k in order]
    return {"kind": kind, "ref": ref, "lines": proposed, "category": next(iter(categories)) if len(categories) == 1 else None,
            "companyCodes": sorted(companies), "origins": sorted(origins), "warnings": warnings,
            "estimatedValueMinor": sum(p["valueMinor"] for p in proposed),
            "note": "annual_qty defaults to the requirement quantity and monthly_qty to one twelfth of it: adjust before creating the event"}


# ---------------------------------------------------------------- offer-validity expiry (flow fixes B9)
OFFER_OPEN_EVENTS = ("CLOSED", "UNDER_EVALUATION", "AWARD_PENDING", "OPEN")


def expire_offers(session: Session, *, dry_run: bool = False) -> dict:
    """Bids whose offer validity (``valid_until``, given by the supplier) has passed while the event is still being evaluated or awarded:
    each is recorded once in the audit trail (OFFER_EXPIRED) and the event owner is told, so the buyer asks the supplier to extend its
    offer (or a new round) before awarding on a price the supplier no longer holds."""
    from app.pic.services.notifications import _user, link_for, notify
    today = clock.today()
    expired = []
    rows = session.execute(select(Bid, SourcingEvent).join(SourcingEvent, SourcingEvent.id == Bid.event_id).where(
        Bid.valid_until.is_not(None), Bid.valid_until < today, Bid.status.in_(("SEALED", "UNSEALED")),
        SourcingEvent.status.in_(OFFER_OPEN_EVENTS), Bid.round == SourcingEvent.round).order_by(SourcingEvent.number, Bid.created_at)).all()
    for bid, event in rows:
        supplier = session.get(Supplier, bid.supplier_id)
        expired.append({"event": event.number, "supplier": supplier.code, "validUntil": bid.valid_until.isoformat()})
        if dry_run:
            continue
        already = session.execute(select(AuditEvent.seq).where(AuditEvent.object_id == event.id, AuditEvent.action == "OFFER_EXPIRED",
                                                              AuditEvent.after["bidId"].astext == str(bid.id)).limit(1)).first()
        if already:
            continue
        audit.record(session, "SOURCING_EVENT", event.id, "OFFER_EXPIRED", object_ref=event.number,
                     after={"bidId": str(bid.id), "supplier": supplier.code, "validUntil": bid.valid_until.isoformat(), "round": bid.round})
        notify(session, _user(session, event.owner_id), kind="SOURCING_OFFER_EXPIRED", dedup_key=f"SOURCING_OFFER_EXPIRED:{bid.id}",
               title=f"{event.number}: the offer of {supplier.code} has expired",
               body=f"The offer of {supplier.legal_name} in {event.number} was valid until {bid.valid_until.isoformat()}. Ask the supplier to "
                    "extend its validity, or run a new round, before awarding on this price.",
               link=link_for("SOURCING_EVENT", event.number), object_type="SOURCING_EVENT", object_ref=event.number)
    return {"expired": expired[:500], "count": len(expired), "dryRun": dry_run}


def _register_jobs() -> None:
    from app.pic.services import jobs

    @jobs.job("bid-offer-expiry", name="Bid offer-validity expiry", schedule="30 0 * * *", dry_run=True,
              description="Finds the bids whose offer validity has passed while their event is still open, in evaluation or awaiting the award "
                          "decision, records each once (OFFER_EXPIRED) and tells the event owner.")
    def bid_offer_expiry(ctx) -> dict:
        return expire_offers(ctx.session, dry_run=ctx.dry_run)


_register_jobs()
