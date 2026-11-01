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
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant, tenant_tx
from app.pic.models import (
    AwardDecision, AwardScenario, Bid, BidLine, BidLot, CategoryPlan, Criterion, EventLine, EventLineSource, Evaluation, InfoRecord, Invitee,
    Material, PrLine, Requisition, Scorecard, SourcingEvent, Supplier, SupplierCategoryStatus, SupplierSegment, Task, Timer,
)
from app.pic.platform import abac
from app.pic.platform import agents, audit, clock, crypto, outbox, rules, sod, workflow
from app.pic.platform.core import StateMachine, link, next_number
from app.pic.platform.errors import Problem, illegal_transition, not_found, rule_violation
from app.pic.platform.money import D, fmt_inr
from app.pic.services import auction as auction_svc
from app.pic.services import ind_healthcare
from app.pic.services import risk as risk_svc
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


def should_cost(params: dict) -> dict:
    """Parametric should-cost by commodity (die-casting): material + conversion + tooling + packaging, then margin."""
    material = D(params["net_weight_kg"]) * D(params["alloy_rate_per_kg"])
    conversion = D(params["cycle_time_min"]) * D(params["machine_rate_per_min"])
    tooling = D(params.get("tooling_amortisation", 0))
    packaging = D(params.get("packaging", 0))
    subtotal = material + conversion + tooling + packaging
    total = (subtotal * (1 + D(params["overhead_margin_pct"]) / 100)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return {"model": params.get("model", "diecast-param-v1"), "material": str(material), "conversion": str(conversion),
            "tooling": str(tooling), "packaging": str(packaging), "subtotal": str(subtotal),
            "overheadMarginPct": str(params["overhead_margin_pct"]), "unitCost": str(total),
            "unitCostMinor": int(total * 100)}


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
                 savings_target_pct: Optional[Decimal] = None, bundle: Optional[dict] = None) -> SourcingEvent:
    p = principal(session)
    _require_lines(lines)
    multi = len(lines) > 1 or any(len(_line_sources(l)) > 1 for l in lines) or bundle is not None
    if len(lines) > 1 and type.upper() == "REVERSE_AUCTION":
        raise rule_violation("A live reverse auction ranks one price ladder: it runs per item (one event line). Use an RFQ or RFP for several lines",
                             "SRC-AUCTION")
    if len(lines) > 1 and should_cost_params:
        raise rule_violation("Should-cost is calculated per item: use a single-line event", "SRC-SHOULDCOST")
    _check_lots([l.get("lot") and str(l["lot"]).upper() for l in lines])
    constraints = _validate_constraints(constraints or {"max_suppliers": 2, "max_share": "0.60", "min_share": "0.20"})
    _check_criteria(criteria)
    event = SourcingEvent(
        tenant_id=current_tenant(session), number=next_number(session, "SOURCING_EVENT"), type=type.upper(), title=title,
        category=category, status="DRAFT", owner_id=p.user_id, close_at=close_at, baseline_method=baseline_method,
        constraints=constraints,
        tco_params=tco_params or {"carrying_rate_pct": "18", "cost_of_capital_pct": "12", "copq_per_defect_minor": 500000},
        savings_target_pct=savings_target_pct, should_cost=should_cost(should_cost_params) if should_cost_params else None,
        created_by=p.user_id,
    )
    session.add(event)
    session.flush()
    instance = workflow.start(session, PROCESS, "SOURCING_EVENT", event.id, event.number)
    # P06: events start only from approved requirements.
    company_codes, seen, origins, requisitions = set(), set(), set(), []
    baseline_value, baselines_complete = 0, True
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
            if multi:
                if pr_line.sourcing_status != "OPEN":
                    raise rule_violation(f"Requisition line {pr.number}/{pr_line.line_no} is {pr_line.sourcing_status}; bundle only open lines", "SRC-BUNDLE")
                line_category = pr_line.category or pr_line.material_group
                if line_category != category:
                    raise rule_violation(f"Requisition line {pr.number}/{pr_line.line_no} is category {line_category}, not {category}", "SRC-BUNDLE")
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
                         requisition_id=pr.id, pr_line_no=pr_line.line_no, lot_code=lot, created_by=p.user_id)
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
        if line_baseline is None and material is not None and baseline_method == "LAST_PRICE":
            info = session.execute(select(InfoRecord).where(InfoRecord.material_id == material.id)
                                   .order_by(InfoRecord.updated_at.desc().nullslast(), InfoRecord.created_at.desc())).scalars().first()
            line_baseline = info.last_price_minor if info else None
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
                              data_source=str(c.get("data_source") or "MANUAL").upper(), created_by=p.user_id))
    for inv in invitees:
        supplier = supplier_by_code(session, inv["supplier"])
        status = category_status(session, supplier.id, category)
        waiver = inv.get("waiver_reason")
        if status not in ELIGIBLE and not (status == "CONDITIONAL" and waiver):
            raise rule_violation(f"{supplier.code} is {status} for {category}; only Qualified suppliers (or Conditional with waiver) may be invited", "P06/SRC-INVITE")
        session.add(Invitee(tenant_id=event.tenant_id, event_id=event.id, supplier_id=supplier.id, category_status=status,
                            waiver_reason=waiver, created_by=p.user_id))
    session.flush()
    workflow.wait(session, instance, "F3-02", outcome="event drafted; scoring model and invitees set")
    audit.record(session, "SOURCING_EVENT", event.id, "CREATED", object_ref=event.number,
                 after={"type": event.type, "lines": len(lines), "invitees": [i["supplier"] for i in invitees],
                        "baselineMinor": event.baseline_price_minor, "shouldCost": event.should_cost,
                        **({"bundle": event.bundle} if event.bundle else {})})
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
    for c in criteria:
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


def publish(session: Session, event: SourcingEvent) -> SourcingEvent:
    auction_svc._require_manager(session, event)
    lines = _lines(session, event)
    _require_lines(lines)
    _check_lots([l.lot_code for l in lines])
    weights = sum(c.weight for c in _criteria(session, event))
    if weights != 100:
        raise rule_violation(f"Scoring weights must sum to 100 (currently {weights})", "SRC-WEIGHTS")
    if not session.execute(select(Invitee).where(Invitee.event_id == event.id)).first():
        raise rule_violation("Invite at least one qualified supplier", "P06")
    if event.close_at <= clock.now():
        raise rule_violation("Close time must be in the future", "SRC-CLOSE")
    if event.type == "REVERSE_AUCTION":
        auction_svc.on_publish(session, event)  # freeze AUCTION settings, start the live clock
    event.weights_locked = True
    event.published_at = clock.now()
    SM.apply(session, event, "publish", reason="weights locked")
    SM.apply(session, event, "open")
    workflow.create_timer(session, "SOURCING_CLOSE", "SOURCING_EVENT", event.id, event.close_at, {"round": event.round})
    outbox.emit(session, "sourcing.event.published", "SOURCING_EVENT", event.id, event.number,
                {"category": event.category, "baselineMinor": event.baseline_price_minor, "closeAt": event.close_at.isoformat(),
                 "lines": _published_lines(session, event)})
    instance = workflow.find(session, "SOURCING_EVENT", event.id, PROCESS)
    workflow.step(session, instance, "F3-02", outcome="published; weights locked")
    workflow.wait(session, instance, "F3-03", outcome=(f"round {event.round}: live reverse auction until {event.close_at.isoformat()} (soft close)"
                                                       if event.type == "REVERSE_AUCTION" else
                                                       f"round {event.round}: bids sealed until {event.close_at.isoformat()}"))
    return event


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
def submit_bid(session: Session, event: SourcingEvent, supplier: Supplier, lines: list[dict], lots: Optional[list[dict]] = None) -> Bid:
    p = principal(session)
    if event.status != "OPEN":
        raise illegal_transition("Sourcing event", event.number, event.status, "bid")
    if event.type == "REVERSE_AUCTION":
        raise Problem(409, "USE_AUCTION_BIDDING", f"{event.number} is a live reverse auction; bid through /auction/bids", rule_ref="SRC-AUCTION")
    if clock.now() >= event.close_at:
        raise Problem(409, "EVENT_CLOSED", f"{event.number} closed at {event.close_at.isoformat()}")
    if not session.execute(select(Invitee).where(Invitee.event_id == event.id, Invitee.supplier_id == supplier.id)).first():
        raise Problem(403, "NOT_INVITED", f"{supplier.code} is not invited to {event.number}")
    _require_eligible(session, event, supplier, "bid")
    event_lines = _lines(session, event)
    lots = _check_bid_lines(event, event_lines, lines, lots or [])
    body = {"lines": lines}
    if lots:
        body["lots"] = lots
    payload = json.dumps(body, sort_keys=True, default=str)
    previous = session.execute(select(Bid).where(Bid.event_id == event.id, Bid.supplier_id == supplier.id,
                                                 Bid.round == event.round)).scalar_one_or_none()
    if previous:
        previous.sealed_payload = crypto.encrypt(event.tenant_id, f"bid:{event.id}", payload)
        previous.payload_hash = hashlib.sha256(payload.encode()).hexdigest()
        previous.submitted_at = clock.now()
        bid = previous
    else:
        bid = Bid(tenant_id=event.tenant_id, event_id=event.id, supplier_id=supplier.id, round=event.round,
                  sealed_payload=crypto.encrypt(event.tenant_id, f"bid:{event.id}", payload),
                  payload_hash=hashlib.sha256(payload.encode()).hexdigest(), status="SEALED", submitted_at=clock.now(),
                  submitted_by=p.user_id, created_by=p.user_id)
        session.add(bid)
    session.flush()
    audit.record(session, "SOURCING_EVENT", event.id, "BID_SUBMITTED", object_ref=event.number,
                 after={"supplier": supplier.code, "round": event.round, "hash": bid.payload_hash, "lines": len(lines),
                        **({"lots": [l["lot"] for l in lots]} if lots else {})})
    outbox.emit(session, "sourcing.bid.submitted", "SOURCING_EVENT", event.id, event.number,
                {"supplier": supplier.code, "round": event.round})
    return bid


def _check_bid_lines(event: SourcingEvent, event_lines: list[EventLine], lines: list[dict], lots: list[dict]) -> list[dict]:
    """Well-formed bid lines (a malformed sealed bid would otherwise only fail at close). A single-line event, or one that sets
    ``require_all_lines``, needs a price for every line; otherwise a supplier may bid some lines. Lot terms (bundle discount, all-or-nothing)
    need a price for every line of the lot."""
    line_nos = [l.line_no for l in event_lines]

    def bad(detail: str) -> Problem:
        return Problem(422, "INVALID_BID_LINES", f"{event.number}: {detail}", rule_ref="SRC-BID")

    if not lines:
        raise bad("a bid needs one line per event line" if len(line_nos) == 1 else "a bid needs at least one line")
    seen = []
    for data in lines:
        try:
            line_no = int(data["line"])
            price = D(data["unit_price"])
            terms, lead = int(data["payment_terms_days"]), int(data["lead_time_days"])
            for key in ("freight", "duty", "packaging"):
                if D(data.get(key) or 0) < 0:
                    raise bad(f"line {line_no}: {key} cannot be negative")
            capacity = D(data["capacity_per_month"]) if data.get("capacity_per_month") not in (None, "") else None
        except Problem:
            raise
        except (KeyError, TypeError, ValueError, ArithmeticError):
            raise bad("each bid line needs line, unit_price, payment_terms_days and lead_time_days as numbers")
        if line_no not in line_nos:
            raise bad(f"line {line_no} is not a line of the event (lines: {', '.join(str(n) for n in line_nos)})")
        if line_no in seen:
            raise bad(f"line {line_no} is bid twice")
        if price <= 0 or terms < 0 or lead < 0 or (capacity is not None and capacity < 0):
            raise bad(f"line {line_no}: unit price must be positive; terms, lead time and capacity cannot be negative")
        seen.append(line_no)
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
        if discount < 0 or discount >= 100:
            raise bad(f"lot {code}: the discount must be at least 0 and below 100 percent")
        absent = [n for n in lot_lines[code] if n not in seen]
        if (discount > 0 or all_or_nothing) and absent:
            raise Problem(422, "INCOMPLETE_LOT", f"{event.number}: lot {code} terms (discount or all-or-nothing) need a price for every line of the lot; "
                          f"missing line(s) {', '.join(str(n) for n in absent)}", rule_ref="SRC-LOT")
        seen_lots.add(code)
        if discount > 0 or all_or_nothing:
            clean.append({"lot": code, "discount_pct": str(discount), "all_or_nothing": all_or_nothing})
    return clean


def bids_view(session: Session, event: SourcingEvent) -> list[dict]:
    """Commercial bid content. Before close the attempt is blocked and logged (§11.4)."""
    if event.status in ("DRAFT", "PUBLISHED", "OPEN") or event.unsealed_at is None:
        p = principal(session)
        with tenant_tx(event.tenant_id, p.user_id, p) as s:
            audit.record(s, "SOURCING_EVENT", event.id, "BID_ACCESS_DENIED", object_ref=event.number,
                         reason="bids are sealed until close")
        raise Problem(423, "BIDS_SEALED", f"Bids for {event.number} stay sealed until {event.close_at.isoformat()}", rule_ref="SRC-SEALED")
    return evaluation_matrix(session, event)


def close(session: Session, event: SourcingEvent, by_timer: bool = False) -> dict:
    if not by_timer:
        auction_svc._require_manager(session, event)  # the close timer (system) closes on time without an owner check
    closes_at = auction_svc.ends_at(event)  # a reverse auction may have been extended (soft close)
    if clock.now() < closes_at:
        raise Problem(409, "CLOSE_TIME_NOT_REACHED", f"{event.number} closes at {closes_at.isoformat()}")
    SM.apply(session, event, "close")
    event.closed_at = clock.now()
    if event.type == "REVERSE_AUCTION":
        auction_svc.to_sealed_bids(session, event)  # last auction prices become sealed bids for the normal evaluation
    unsealed = _unseal(session, event)
    SM.apply(session, event, "evaluate")
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
    return {"event": event.number, "unsealed": unsealed, "matrix": matrix, "aiRef": ai_ref,
            **({"lineMatrix": line_matrix(session, event)} if multi else {})}


@workflow.on_timer("SOURCING_CLOSE")
def _close_timer(session: Session, timer) -> None:
    event = session.get(SourcingEvent, timer.object_id)
    # An extended auction leaves earlier close timers behind; only the one at or after the live end closes it.
    if event and event.status == "OPEN" and timer.payload.get("round") == event.round and clock.now() >= auction_svc.ends_at(event):
        close(session, event, by_timer=True)


def _unseal(session: Session, event: SourcingEvent) -> int:
    count = 0
    for bid in session.execute(select(Bid).where(Bid.event_id == event.id, Bid.round == event.round,
                                                 Bid.status == "SEALED")).scalars():
        payload = json.loads(crypto.decrypt(event.tenant_id, f"bid:{event.id}", bid.sealed_payload))
        if hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest() != bid.payload_hash:
            raise Problem(500, "BID_INTEGRITY", "Bid content does not match its submission hash")
        lines = {l.line_no: l for l in _lines(session, event)}
        lot_codes = {l.lot_code for l in lines.values() if l.lot_code}
        valid, rejected, seen = 0, [], set()
        for data in payload.get("lines") or []:
            # Bids are validated on submission; a malformed or foreign line (e.g. from an older submission) is skipped and
            # recorded instead of failing the close for every bidder.
            try:
                event_line = lines.get(int(data["line"]))
                if event_line is None or event_line.id in seen:
                    raise ValueError("unknown or duplicate line")
                components = {k: str(data.get(k) or 0) for k in ("freight", "duty", "packaging")}
                line = BidLine(tenant_id=event.tenant_id, bid_id=bid.id, event_line_id=event_line.id,
                               unit_price_minor=int(D(data["unit_price"]) * 100), tco_components=components,
                               payment_terms_days=int(data["payment_terms_days"]), lead_time_days=int(data["lead_time_days"]),
                               offered_capacity_per_month=D(data["capacity_per_month"]) if data.get("capacity_per_month") else None,
                               created_by=bid.submitted_by)
                if line.unit_price_minor <= 0:
                    raise ValueError("unit price must be positive")
                tco, breakdown = _tco(session, event, bid.supplier_id, line)
            except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError) as exc:
                rejected.append({"line": data.get("line") if isinstance(data, dict) else None, "error": str(exc)[:200]})
                continue
            line.tco_minor, line.tco_breakdown = tco, breakdown
            session.add(line)
            seen.add(event_line.id)
            valid += 1
        if valid == 0:
            bid.status = "INVALID"
            audit.record(session, "SOURCING_EVENT", event.id, "BID_INVALID", object_ref=event.number,
                         after={"supplier": session.get(Supplier, bid.supplier_id).code, "round": event.round, "rejectedLines": rejected},
                         reason="sealed bid has no valid line for this event; it is not evaluated")
            continue
        if rejected:
            audit.record(session, "SOURCING_EVENT", event.id, "BID_LINES_SKIPPED", object_ref=event.number,
                         after={"supplier": session.get(Supplier, bid.supplier_id).code, "round": event.round, "rejectedLines": rejected})
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
                 after={"round": event.round, "bids": count}, reason="close time reached")
    return count


def _tco(session: Session, event: SourcingEvent, supplier_id: uuid.UUID, line: BidLine) -> tuple[int, dict]:
    """tco = price + freight + duty + packaging + carrying(lead time) + quality(ppm × CoPQ) − payment-term value."""
    params = event.tco_params
    price = Decimal(line.unit_price_minor)
    twin = supplier_svc.twin(session, supplier_id, event.category)
    ppm = Decimal(twin.ppm) if twin and twin.ppm is not None else Decimal(0)
    carrying = price * D(params["carrying_rate_pct"]) / 100 * line.lead_time_days / 365
    quality = ppm / 1_000_000 * D(params["copq_per_defect_minor"])
    payment = price * D(params["cost_of_capital_pct"]) / 100 * line.payment_terms_days / 365
    parts = {"price": price, "freight": D(line.tco_components.get("freight", 0)) * 100,
             "duty": D(line.tco_components.get("duty", 0)) * 100, "packaging": D(line.tco_components.get("packaging", 0)) * 100,
             "carrying": carrying, "quality": quality, "paymentTermValue": -payment}
    total = sum(parts.values(), Decimal(0)).quantize(Decimal("1"), ROUND_HALF_UP)
    return int(total), {k: int(v.quantize(Decimal("1"), ROUND_HALF_UP)) for k, v in parts.items()}


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
    return {"line": event_line.line_no, "eventLineId": str(event_line.id), "lot": event_line.lot_code, "priceMinor": line.unit_price_minor,
            "tcoMinor": line.tco_minor, "tco": line.tco_breakdown, "leadTimeDays": line.lead_time_days,
            "paymentTermsDays": line.payment_terms_days, "verifiedCapacityPerMonth": str(capacity) if capacity is not None else None,
            "twinCapacityPerMonth": str(twin.free_capacity_per_month) if twin and twin.free_capacity_per_month is not None else None}


def evaluation_matrix(session: Session, event: SourcingEvent) -> list[dict]:
    criteria = _criteria(session, event)
    bids = _latest_bids(session, event)
    event_lines = _lines(session, event)
    multi = len(event_lines) > 1
    by_id = {l.id: l for l in event_lines}
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
                "lateDeliveryProb": str(twin.late_delivery_prob) if twin else None, "lines": line_rows, "lots": lots,
                "autoScores": bid.auto_scores or {}, "basis": "ANNUAL_VALUE" if multi else "UNIT",
                "coverage": {"bid": len(line_rows), "of": len(event_lines)}, "complete": len(line_rows) == len(event_lines)}
        if not multi:
            first = line_rows[0]
            rows.append({**base, "priceMinor": first["priceMinor"], "tcoMinor": first["tcoMinor"], "tco": first["tco"],
                         "leadTimeDays": first["leadTimeDays"], "paymentTermsDays": first["paymentTermsDays"],
                         "verifiedCapacityPerMonth": first["verifiedCapacityPerMonth"],
                         "shouldCostDeltaMinor": first["priceMinor"] - event.should_cost["unitCostMinor"] if event.should_cost else None})
        else:
            annual = {l.line_no: l.annual_qty for l in event_lines}
            rows.append({**base, "priceMinor": int(sum(Decimal(r["priceMinor"]) * annual[r["line"]] for r in line_rows)),
                         "tcoMinor": int(sum(Decimal(r["tcoMinor"]) * annual[r["line"]] for r in line_rows)),
                         "leadTimeDays": max(r["leadTimeDays"] for r in line_rows),
                         "paymentTermsDays": min(r["paymentTermsDays"] for r in line_rows),
                         "verifiedCapacityPerMonth": None, "shouldCostDeltaMinor": None})
    if rows:
        rounds = {b.id: b.round for b in session.execute(select(Bid).where(Bid.event_id == event.id)).scalars()}
        # price score per line against the best TCO bid on that line; a supplier's price score is the value-weighted mean over all lines
        best_line = {l.line_no: min((r_l["tcoMinor"] for r in rows for r_l in r["lines"] if r_l["line"] == l.line_no), default=None) for l in event_lines}
        weight_line = {l.line_no: Decimal(best_line[l.line_no] or 0) * l.annual_qty for l in event_lines}
        total_weight = sum(weight_line.values()) or Decimal(1)
        for r in rows:
            line_price_scores = {}
            for r_l in r["lines"]:
                line_price_scores[r_l["line"]] = Decimal(best_line[r_l["line"]]) / Decimal(r_l["tcoMinor"]) * 100
            if multi:
                price_score = sum(weight_line[n] * s for n, s in line_price_scores.items()) / total_weight
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
            # the weighted score of each line: that line's price score with the supplier's other criteria
            for r_l in r["lines"]:
                other = sum(Decimal(c.weight) * Decimal(final.get(c.code, 0)) / 100 for c in criteria if c.code != "PRICE_TCO")
                price_weight = next((Decimal(c.weight) for c in criteria if c.code == "PRICE_TCO"), Decimal(0))
                r_l["weightedScore"] = str((price_weight * line_price_scores[r_l["line"]] / 100 + other).quantize(Decimal("0.01")))
    if multi:
        return sorted(rows, key=lambda r: (not r["complete"], r["tcoMinor"]))
    return sorted(rows, key=lambda r: r["tcoMinor"])


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


def score(session: Session, event: SourcingEvent, scores: list[dict]) -> dict:
    p = principal(session)
    if event.status != "UNDER_EVALUATION":
        raise illegal_transition("Sourcing event", event.number, event.status, "score")
    criteria = {c.code: c for c in _criteria(session, event)}
    for item in scores:
        if item["criterion"] not in criteria or item["criterion"] == "PRICE_TCO":
            raise Problem(422, "INVALID_CRITERION", f"{item['criterion']} is not a manually scored criterion of {event.number}")
        if criteria[item["criterion"]].data_source != "MANUAL":
            raise Problem(422, "INVALID_CRITERION", f"{item['criterion']} is scored from {criteria[item['criterion']].data_source} data at close, "
                          "not by an evaluator", rule_ref="SRC-CRITERIA")
        supplier = supplier_by_code(session, item["supplier"])
        bid = session.execute(select(Bid).where(Bid.event_id == event.id, Bid.supplier_id == supplier.id,
                                                Bid.status == "UNSEALED")).scalar_one_or_none()
        if bid is None:
            raise Problem(422, "NO_VALID_BID", f"{supplier.code} has no evaluated bid in {event.number}")
        existing = session.execute(select(Evaluation).where(Evaluation.bid_id == bid.id, Evaluation.criterion_code == item["criterion"],
                                                            Evaluation.evaluator_id == p.user_id)).scalar_one_or_none()
        if existing:
            existing.score = D(item["score"])
        else:
            session.add(Evaluation(tenant_id=event.tenant_id, event_id=event.id, bid_id=bid.id, criterion_code=item["criterion"],
                                   evaluator_id=p.user_id, score=D(item["score"]), comment=item.get("comment"), created_by=p.user_id))
    session.flush()
    sod.record(session, "BID_SCORE", {"event_id": event.id})
    audit.record(session, "SOURCING_EVENT", event.id, "SCORED", object_ref=event.number, after={"entries": len(scores)})
    return {"event": event.number, "matrix": evaluation_matrix(session, event)}


def new_round(session: Session, event: SourcingEvent, close_at: datetime, note: str = "") -> SourcingEvent:
    auction_svc._require_manager(session, event)
    if close_at <= clock.now():
        raise rule_violation("Close time must be in the future", "SRC-CLOSE")
    instance = workflow.find(session, "SOURCING_EVENT", event.id, PROCESS)
    workflow.step(session, instance, "F3-05", outcome=f"yes: negotiation round {event.round + 1}" + (f" ({note})" if note else ""))
    SM.apply(session, event, "new_round", reason=note or "negotiation round")
    event.round += 1
    event.close_at = close_at
    event.unsealed_at = None
    auction_svc.on_new_round(event)
    workflow.create_timer(session, "SOURCING_CLOSE", "SOURCING_EVENT", event.id, close_at, {"round": event.round})
    workflow.wait(session, instance, "F3-03", outcome=f"round {event.round}: sealed bids until {close_at.isoformat()}")
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
    for k in range(1, max_k + 1):
        for subset in itertools.combinations(rows, k):
            uppers = []
            for r in subset:
                cap = Decimal(r["verifiedCapacityPerMonth"]) / q if r["verifiedCapacityPerMonth"] else Decimal(1)
                uppers.append(min(max_share, cap))  # max_share binds a single supplier too (sole source only if max_share is 1)
            lowers = [min_share if k > 1 else Decimal(1)] * k
            if any(lo > up for lo, up in zip(lowers, uppers)) or sum(uppers) < 1 or sum(lowers) > 1:
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
            if remaining > 0 or (cond_cap is not None and cond_used > cond_cap):
                continue
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
    info = _supplier_risk_info(session, event, [uuid.UUID(r["supplierId"]) for r in matrix])
    excluded = _exclusions(info, rc)
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


def _store(session: Session, event: SourcingEvent, results: list, kind: str, allocations: list, feasible: bool, explanation: dict,
           weighted_price, weighted_tco, savings) -> AwardScenario:
    scenario = AwardScenario(
        tenant_id=event.tenant_id, event_id=event.id, kind=kind, feasible=feasible, allocations=allocations,
        weighted_price_minor=int(weighted_price.quantize(Decimal("1"), ROUND_HALF_UP)) if weighted_price is not None else None,
        weighted_tco_minor=int(weighted_tco.quantize(Decimal("1"), ROUND_HALF_UP)) if weighted_tco is not None else None,
        annual_savings_minor=savings, explanation=explanation, created_by=principal(session).user_id)
    session.add(scenario)
    session.flush()
    results.append(scenario)
    return scenario


def _single_line_scenarios(session: Session, event: SourcingEvent, line: EventLine, matrix: list[dict], rc: dict, info: dict, excluded: dict) -> list:
    q = line.monthly_qty
    rows = _supplier_rows(matrix, info, excluded)
    # With one line the value share equals the volume share: the single-source cap is a cap on the share of the line.
    constraints = dict(event.constraints or {})
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
              "priceMinor": r["priceMinor"], "tcoMinor": r["tcoMinor"]} for r, s in allocations],
            feasible, explanation, weighted_price, weighted_tco, savings)

    lowest = rows[0] if rows else None
    if lowest:
        cap = Decimal(lowest["verifiedCapacityPerMonth"] or q)
        store("LOWEST_COST", [(lowest, Decimal(1))], cap >= q,
              {"rule": "all volume to lowest TCO", "capacityCheck": f"{lowest['supplier']} verified capacity {cap} vs {q}/month"})
    best_value = max(rows, key=lambda r: Decimal(r.get("weightedScore", "0"))) if rows else None
    if best_value:
        cap = Decimal(best_value["verifiedCapacityPerMonth"] or q)
        store("BEST_VALUE", [(best_value, Decimal(1))], cap >= q,
              {"rule": "all volume to highest weighted score", "capacityCheck": f"{best_value['supplier']} verified capacity {cap} vs {q}/month"})
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
                    "priceMinor": int(price), "tcoMinor": int(tco),
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
                    and (Decimal(r["verifiedCapacityPerMonth"]) >= line.monthly_qty if r["verifiedCapacityPerMonth"] else True)]
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


# ---------------------------------------------------------------- award (F3-07/08/09)
def propose_award(session: Session, event: SourcingEvent, scenario_id: uuid.UUID, rationale: Optional[str],
                  conflict_declaration: str) -> AwardDecision:
    p = principal(session)
    auction_svc._require_manager(session, event)
    scenario = session.get(AwardScenario, scenario_id)
    if scenario is None or scenario.event_id != event.id or not scenario.feasible:
        raise rule_violation("Choose a feasible scenario of this event", "SRC-AWARD")
    for allocation in scenario.allocations:
        _require_eligible(session, event, session.get(Supplier, uuid.UUID(allocation["supplierId"])), "be awarded")
    if (scenario.explanation or {}).get("supersededAt"):
        raise rule_violation("This scenario was superseded when the scenarios were rebuilt; choose a current one", "SRC-AWARD")
    if not conflict_declaration:
        raise rule_violation("A conflict-of-interest declaration is required", "SRC-05")
    rows = evaluation_matrix(session, event)
    event_lines = _lines(session, event)
    multi = len(event_lines) > 1
    if multi:
        lowest = {}
        for r in rows:
            for l in r["lines"]:
                lowest[l["line"]] = min(lowest.get(l["line"], l["priceMinor"]), l["priceMinor"])
        not_lowest = any(l["priceMinor"] > lowest.get(l["line"], 0) for a in scenario.allocations for l in a["lines"])
        annual_value = int(scenario.weighted_price_minor)
    else:
        lowest_price = min(r["priceMinor"] for r in rows)
        not_lowest = any(a["priceMinor"] > lowest_price for a in scenario.allocations)
        annual_value = int(Decimal(scenario.weighted_price_minor) * event_lines[0].annual_qty)
    if not_lowest and not rationale:
        raise rule_violation("Award to a non-lowest bid needs a written rationale", "SRC-RATIONALE")
    abac.guard(session, "AWARD_APPROVE", event, value_minor=annual_value)
    sod.guard_and_record(session, "SOURCING_AWARD", {"event_id": event.id})
    rule = rules.resolve(session, "AWARD-APPROVAL", category=event.category)
    chain = ind_healthcare.award_chain(rule, rules.band_chain(rule, annual_value), event.category)  # + clinical sign-off (healthcare rule)
    decision = AwardDecision(tenant_id=event.tenant_id, event_id=event.id, scenario_id=scenario.id, status="PENDING",
                             rationale=rationale, conflict_declarations=[{"user": p.email, "declaration": conflict_declaration}],
                             proposed_by=p.user_id, annual_value_minor=annual_value, rule_set_version=rule.ref, created_by=p.user_id)
    session.add(decision)
    session.flush()
    SM.apply(session, event, "propose_award", reason=rationale, rule_set_version=rule.ref)
    instance = workflow.find(session, "SOURCING_EVENT", event.id, PROCESS)
    workflow.step(session, instance, "F3-06", outcome=f"{scenario.kind} proposed")
    needs_approval = annual_value >= rule.body["approvalAboveMinor"] or not_lowest or ind_healthcare.signoff_required(rule, event.category)
    workflow.step(session, instance, "F3-07", outcome=("yes" if needs_approval else "no") +
                  f": annual value {fmt_inr(annual_value)}" + (", not lowest bid" if not_lowest else ""))
    if not needs_approval:
        _award(session, event, decision, instance)
        return decision
    workflow.start_approval(session, instance, "AWARD_APPROVAL", object_type="SOURCING_EVENT", object_id=event.id,
                            object_ref=event.number, chain=chain, step_id="F3-08", initiator_id=p.user_id,
                            scopes={"CATEGORY_MANAGER": {"category": event.category}}, rule_set_version=rule.ref,
                            evidence={"scenario": scenario.kind, "allocations": scenario.allocations, "rationale": rationale})
    return decision


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
    payload = {"category": event.category, "baselineMinor": event.baseline_price_minor, "weightedPriceMinor": scenario.weighted_price_minor,
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
    outbox.emit(session, "sourcing.event.awarded", "SOURCING_EVENT", event.id, event.number,
                _award_payload(session, event, scenario, decision, event_lines))
    awarded = {a["supplier"] for a in scenario.allocations}
    audit.record(session, "SOURCING_EVENT", event.id, "AWARD_NOTIFIED", object_ref=event.number,
                 after={"awarded": [a["supplier"] for a in scenario.allocations],
                        "notifiedUnsuccessful": [r["supplier"] for r in evaluation_matrix(session, event) if r["supplier"] not in awarded]})
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
