"""F3 Strategic sourcing → award (M05, Technical Document §9.3)."""
import hashlib
import itertools
import json
import uuid
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant, tenant_tx
from app.pic.models import (
    AwardDecision, AwardScenario, Bid, BidLine, Criterion, EventLine, Evaluation, InfoRecord, Invitee, Material, PrLine,
    Requisition, SourcingEvent, Supplier, Task,
)
from app.pic.platform import agents, audit, clock, crypto, outbox, rules, sod, workflow
from app.pic.platform.core import StateMachine, link, next_number
from app.pic.platform.errors import Problem, illegal_transition, rule_violation
from app.pic.platform.money import D, fmt_inr
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
})
ELIGIBLE = ("QUALIFIED", "PREFERRED")


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
def create_event(session: Session, *, type: str, title: str, category: str, lines: list[dict], criteria: list[dict],
                 invitees: list[dict], close_at: datetime, baseline_method: str = "LAST_PRICE",
                 baseline_price_minor: Optional[int] = None, should_cost_params: Optional[dict] = None,
                 constraints: Optional[dict] = None, tco_params: Optional[dict] = None,
                 savings_target_pct: Optional[Decimal] = None) -> SourcingEvent:
    p = principal(session)
    event = SourcingEvent(
        tenant_id=current_tenant(session), number=next_number(session, "SOURCING_EVENT"), type=type.upper(), title=title,
        category=category, status="DRAFT", owner_id=p.user_id, close_at=close_at, baseline_method=baseline_method,
        constraints=constraints or {"max_suppliers": 2, "max_share": "0.60", "min_share": "0.20"},
        tco_params=tco_params or {"carrying_rate_pct": "18", "cost_of_capital_pct": "12", "copq_per_defect_minor": 500000},
        savings_target_pct=savings_target_pct, should_cost=should_cost(should_cost_params) if should_cost_params else None,
        created_by=p.user_id,
    )
    session.add(event)
    session.flush()
    instance = workflow.start(session, PROCESS, "SOURCING_EVENT", event.id, event.number)
    # P06: events start only from approved requirements.
    for index, data in enumerate(lines, start=1):
        pr = session.execute(select(Requisition).where(Requisition.number == data["requisition"])).scalar_one_or_none()
        if pr is None or pr.status not in ("APPROVED", "PARTIALLY_ORDERED"):
            raise rule_violation(f"Requirement {data['requisition']} is not an approved requisition", "P06")
        pr_line = session.execute(select(PrLine).where(PrLine.requisition_id == pr.id, PrLine.line_no == int(data["line"]))).scalar_one()
        material = session.get(Material, pr_line.material_id) if pr_line.material_id else None
        line = EventLine(tenant_id=event.tenant_id, event_id=event.id, line_no=index * 10,
                         material_id=material.id if material else None, description=pr_line.description, plant=pr_line.plant,
                         annual_qty=D(data["annual_qty"]), monthly_qty=D(data["monthly_qty"]), uom=pr_line.uom,
                         requisition_id=pr.id, pr_line_no=pr_line.line_no, created_by=p.user_id)
        session.add(line)
        pr_line.sourcing_status = "IN_SOURCING"
        link(session, "REQUISITION", pr.id, pr.number, "SOURCING_EVENT", event.id, event.number, "sourced_by",
             from_line=pr_line.line_no, to_line=index * 10)
        if baseline_price_minor is None and material is not None and baseline_method == "LAST_PRICE":
            info = session.execute(select(InfoRecord).where(InfoRecord.material_id == material.id)
                                   .order_by(InfoRecord.updated_at.desc().nullslast(), InfoRecord.created_at.desc())).scalars().first()
            baseline_price_minor = info.last_price_minor if info else None
    event.baseline_price_minor = baseline_price_minor
    for c in criteria:
        session.add(Criterion(tenant_id=event.tenant_id, event_id=event.id, code=c["code"], name=c["name"], weight=int(c["weight"]),
                              created_by=p.user_id))
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
                        "baselineMinor": baseline_price_minor, "shouldCost": event.should_cost})
    return event


def _criteria(session: Session, event: SourcingEvent) -> list[Criterion]:
    return session.execute(select(Criterion).where(Criterion.event_id == event.id)).scalars().all()


def publish(session: Session, event: SourcingEvent) -> SourcingEvent:
    weights = sum(c.weight for c in _criteria(session, event))
    if weights != 100:
        raise rule_violation(f"Scoring weights must sum to 100 (currently {weights})", "SRC-WEIGHTS")
    if not session.execute(select(Invitee).where(Invitee.event_id == event.id)).first():
        raise rule_violation("Invite at least one qualified supplier", "P06")
    if event.close_at <= clock.now():
        raise rule_violation("Close time must be in the future", "SRC-CLOSE")
    event.weights_locked = True
    event.published_at = clock.now()
    SM.apply(session, event, "publish", reason="weights locked")
    SM.apply(session, event, "open")
    workflow.create_timer(session, "SOURCING_CLOSE", "SOURCING_EVENT", event.id, event.close_at, {"round": event.round})
    outbox.emit(session, "sourcing.event.published", "SOURCING_EVENT", event.id, event.number,
                {"category": event.category, "baselineMinor": event.baseline_price_minor, "closeAt": event.close_at.isoformat(),
                 "lines": [{"material": str(l.material_id), "annualQty": str(l.annual_qty)} for l in _lines(session, event)]})
    instance = workflow.find(session, "SOURCING_EVENT", event.id, PROCESS)
    workflow.step(session, instance, "F3-02", outcome="published; weights locked")
    workflow.wait(session, instance, "F3-03", outcome=f"round {event.round}: bids sealed until {event.close_at.isoformat()}")
    return event


def _lines(session: Session, event: SourcingEvent) -> list[EventLine]:
    return session.execute(select(EventLine).where(EventLine.event_id == event.id).order_by(EventLine.line_no)).scalars().all()


# ---------------------------------------------------------------- sealed bids (F3-03)
def submit_bid(session: Session, event: SourcingEvent, supplier: Supplier, lines: list[dict]) -> Bid:
    p = principal(session)
    if event.status != "OPEN":
        raise illegal_transition("Sourcing event", event.number, event.status, "bid")
    if clock.now() >= event.close_at:
        raise Problem(409, "EVENT_CLOSED", f"{event.number} closed at {event.close_at.isoformat()}")
    if not session.execute(select(Invitee).where(Invitee.event_id == event.id, Invitee.supplier_id == supplier.id)).first():
        raise Problem(403, "NOT_INVITED", f"{supplier.code} is not invited to {event.number}")
    payload = json.dumps({"lines": lines}, sort_keys=True, default=str)
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
                 after={"supplier": supplier.code, "round": event.round, "hash": bid.payload_hash})
    outbox.emit(session, "sourcing.bid.submitted", "SOURCING_EVENT", event.id, event.number,
                {"supplier": supplier.code, "round": event.round})
    return bid


def bids_view(session: Session, event: SourcingEvent) -> list[dict]:
    """Commercial bid content. Before close the attempt is blocked and logged (§11.4)."""
    if event.status in ("DRAFT", "PUBLISHED", "OPEN") or event.unsealed_at is None:
        p = principal(session)
        with tenant_tx(event.tenant_id, p.user_id, p) as s:
            audit.record(s, "SOURCING_EVENT", event.id, "BID_ACCESS_DENIED", object_ref=event.number,
                         reason="bids are sealed until close")
        raise Problem(423, "BIDS_SEALED", f"Bids for {event.number} stay sealed until {event.close_at.isoformat()}", rule_ref="SRC-SEALED")
    return evaluation_matrix(session, event)


def close(session: Session, event: SourcingEvent) -> dict:
    if clock.now() < event.close_at:
        raise Problem(409, "CLOSE_TIME_NOT_REACHED", f"{event.number} closes at {event.close_at.isoformat()}")
    SM.apply(session, event, "close")
    event.closed_at = clock.now()
    unsealed = _unseal(session, event)
    SM.apply(session, event, "evaluate")
    instance = workflow.find(session, "SOURCING_EVENT", event.id, PROCESS)
    workflow.step(session, instance, "F3-03", outcome=f"round {event.round} closed; {unsealed} bid(s) unsealed")
    matrix = evaluation_matrix(session, event)
    ai_ref = agents.log_run(session, "BID_ANALYSIS", object_type="SOURCING_EVENT", object_id=event.id, object_ref=event.number,
                            inputs={"round": event.round}, evidence=[m["supplier"] for m in matrix],
                            output={"ranking": [(m["supplier"], m["tcoMinor"]) for m in matrix],
                                    "shouldCostMinor": (event.should_cost or {}).get("unitCostMinor")},
                            confidence=0.85, action_taken="DRAFTED")
    workflow.step(session, instance, "F3-04", outcome="TCO: " + ", ".join(f"{m['supplier']} {m['priceMinor']/100:.2f}→{m['tcoMinor']/100:.2f}" for m in matrix))
    workflow.wait(session, instance, "F3-05", outcome="another round or proceed to award scenarios")
    return {"event": event.number, "unsealed": unsealed, "matrix": matrix, "aiRef": ai_ref}


@workflow.on_timer("SOURCING_CLOSE")
def _close_timer(session: Session, timer) -> None:
    event = session.get(SourcingEvent, timer.object_id)
    if event and event.status == "OPEN" and timer.payload.get("round") == event.round:
        close(session, event)


def _unseal(session: Session, event: SourcingEvent) -> int:
    count = 0
    for bid in session.execute(select(Bid).where(Bid.event_id == event.id, Bid.round == event.round,
                                                 Bid.status == "SEALED")).scalars():
        payload = json.loads(crypto.decrypt(event.tenant_id, f"bid:{event.id}", bid.sealed_payload))
        if hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest() != bid.payload_hash:
            raise Problem(500, "BID_INTEGRITY", "Bid content does not match its submission hash")
        lines = {l.line_no: l for l in _lines(session, event)}
        for data in payload["lines"]:
            event_line = lines[int(data["line"])]
            components = {k: str(data.get(k, 0)) for k in ("freight", "duty", "packaging")}
            line = BidLine(tenant_id=event.tenant_id, bid_id=bid.id, event_line_id=event_line.id,
                           unit_price_minor=int(D(data["unit_price"]) * 100), tco_components=components,
                           payment_terms_days=int(data["payment_terms_days"]), lead_time_days=int(data["lead_time_days"]),
                           offered_capacity_per_month=D(data["capacity_per_month"]) if data.get("capacity_per_month") else None,
                           created_by=bid.submitted_by)
            tco, breakdown = _tco(session, event, bid.supplier_id, line)
            line.tco_minor, line.tco_breakdown = tco, breakdown
            session.add(line)
        bid.status = "UNSEALED"
        count += 1
    # Earlier rounds are superseded by the latest bid per supplier.
    for bid in session.execute(select(Bid).where(Bid.event_id == event.id, Bid.round < event.round, Bid.status == "UNSEALED")).scalars():
        if session.execute(select(Bid).where(Bid.event_id == event.id, Bid.supplier_id == bid.supplier_id, Bid.round == event.round)).first():
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


def _latest_bids(session: Session, event: SourcingEvent) -> list[Bid]:
    return session.execute(select(Bid).where(Bid.event_id == event.id, Bid.status == "UNSEALED")).scalars().all()


def evaluation_matrix(session: Session, event: SourcingEvent) -> list[dict]:
    criteria = _criteria(session, event)
    bids = _latest_bids(session, event)
    rows = []
    for bid in bids:
        supplier = session.get(Supplier, bid.supplier_id)
        line = session.execute(select(BidLine).where(BidLine.bid_id == bid.id)).scalars().first()
        twin = supplier_svc.twin(session, bid.supplier_id, event.category)
        capacity = min([c for c in (line.offered_capacity_per_month, twin.free_capacity_per_month if twin else None) if c is not None],
                       default=None)
        rows.append({"supplier": supplier.code, "supplierId": str(supplier.id), "round": bid.round, "bidId": str(bid.id),
                     "priceMinor": line.unit_price_minor, "tcoMinor": line.tco_minor, "tco": line.tco_breakdown,
                     "leadTimeDays": line.lead_time_days, "paymentTermsDays": line.payment_terms_days,
                     "verifiedCapacityPerMonth": str(capacity) if capacity is not None else None,
                     "lateDeliveryProb": str(twin.late_delivery_prob) if twin else None,
                     "shouldCostDeltaMinor": line.unit_price_minor - event.should_cost["unitCostMinor"] if event.should_cost else None})
    if rows:
        best_tco = min(r["tcoMinor"] for r in rows)
        for r in rows:
            scores = {"PRICE_TCO": Decimal(best_tco) / Decimal(r["tcoMinor"]) * 100}
            for ev in session.execute(select(Evaluation).where(Evaluation.bid_id == uuid.UUID(r["bidId"]))).scalars():
                scores.setdefault(ev.criterion_code, [])
                if isinstance(scores[ev.criterion_code], list):
                    scores[ev.criterion_code].append(ev.score)
            final = {k: (sum(v) / len(v) if isinstance(v, list) and v else v) for k, v in scores.items()}
            weighted = sum(Decimal(c.weight) * Decimal(final.get(c.code, 0)) / 100 for c in criteria)
            r["scores"] = {k: str(Decimal(v).quantize(Decimal("0.01"))) for k, v in final.items() if not isinstance(v, list)}
            r["weightedScore"] = str(weighted.quantize(Decimal("0.01")))
    return sorted(rows, key=lambda r: r["tcoMinor"])


def score(session: Session, event: SourcingEvent, scores: list[dict]) -> dict:
    p = principal(session)
    if event.status != "UNDER_EVALUATION":
        raise illegal_transition("Sourcing event", event.number, event.status, "score")
    codes = {c.code for c in _criteria(session, event)}
    for item in scores:
        if item["criterion"] not in codes or item["criterion"] == "PRICE_TCO":
            raise Problem(422, "INVALID_CRITERION", f"{item['criterion']} is not a manually scored criterion of {event.number}")
        supplier = supplier_by_code(session, item["supplier"])
        bid = session.execute(select(Bid).where(Bid.event_id == event.id, Bid.supplier_id == supplier.id,
                                                Bid.status == "UNSEALED")).scalar_one()
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
    if close_at <= clock.now():
        raise rule_violation("Close time must be in the future", "SRC-CLOSE")
    instance = workflow.find(session, "SOURCING_EVENT", event.id, PROCESS)
    workflow.step(session, instance, "F3-05", outcome=f"yes: negotiation round {event.round + 1}" + (f" ({note})" if note else ""))
    SM.apply(session, event, "new_round", reason=note or "negotiation round")
    event.round += 1
    event.close_at = close_at
    event.unsealed_at = None
    workflow.create_timer(session, "SOURCING_CLOSE", "SOURCING_EVENT", event.id, close_at, {"round": event.round})
    workflow.wait(session, instance, "F3-03", outcome=f"round {event.round}: sealed bids until {close_at.isoformat()}")
    return event


# ---------------------------------------------------------------- award optimisation (F3-06)
def _optimise(rows: list[dict], q: Decimal, constraints: dict, single_only: bool = False) -> Optional[dict]:
    """minimise Σ x_s·tco_s·Q  s.t. Σ x_s = 1, x_s·Q ≤ verified capacity, min_share ≤ x_s ≤ max_share,
    count ≤ max_suppliers. Exact: enumerate supplier sets, fill cheapest first (optimal for one equality)."""
    max_k = 1 if single_only else int(constraints.get("max_suppliers", 2))
    max_share = Decimal(str(constraints.get("max_share", 1))) if not single_only else Decimal(1)
    min_share = Decimal(str(constraints.get("min_share", 0)))
    best = None
    for k in range(1, max_k + 1):
        for subset in itertools.combinations(rows, k):
            uppers = []
            for r in subset:
                cap = Decimal(r["verifiedCapacityPerMonth"]) / q if r["verifiedCapacityPerMonth"] else Decimal(1)
                uppers.append(min(max_share if k > 1 else Decimal(1), cap))
            lowers = [min_share if k > 1 else Decimal(1)] * k
            if any(lo > up for lo, up in zip(lowers, uppers)) or sum(uppers) < 1 or sum(lowers) > 1:
                continue
            shares = list(lowers)
            remaining = Decimal(1) - sum(lowers)
            for index in sorted(range(k), key=lambda i: subset[i]["tcoMinor"]):
                add = min(uppers[index] - shares[index], remaining)
                shares[index] += add
                remaining -= add
            cost = sum(s * r["tcoMinor"] for s, r in zip(shares, subset))
            if best is None or cost < best["cost"]:
                best = {"cost": cost, "allocations": [(r, s) for r, s in zip(subset, shares) if s > 0]}
    return best


def build_scenarios(session: Session, event: SourcingEvent) -> list[dict]:
    if event.status != "UNDER_EVALUATION":
        raise illegal_transition("Sourcing event", event.number, event.status, "scenarios")
    rows = evaluation_matrix(session, event)
    line = _lines(session, event)[0]
    q = line.monthly_qty
    for old in session.execute(select(AwardScenario).where(AwardScenario.event_id == event.id)).scalars():
        session.delete(old)
    results = []

    def store(kind: str, allocations, feasible: bool, explanation: dict) -> AwardScenario:
        weighted_price = sum(Decimal(r["priceMinor"]) * s for r, s in allocations) if allocations else None
        weighted_tco = sum(Decimal(r["tcoMinor"]) * s for r, s in allocations) if allocations else None
        savings = int((Decimal(event.baseline_price_minor) - weighted_price) * line.annual_qty) if allocations and event.baseline_price_minor else None
        scenario = AwardScenario(
            tenant_id=event.tenant_id, event_id=event.id, kind=kind, feasible=feasible,
            allocations=[{"supplier": r["supplier"], "supplierId": r["supplierId"], "share": str(s.quantize(Decimal("0.0001"))),
                          "monthlyQty": str((q * s).quantize(Decimal("1"))), "annualQty": str((line.annual_qty * s).quantize(Decimal("1"))),
                          "priceMinor": r["priceMinor"], "tcoMinor": r["tcoMinor"]} for r, s in allocations],
            weighted_price_minor=int(weighted_price.quantize(Decimal("1"), ROUND_HALF_UP)) if weighted_price is not None else None,
            weighted_tco_minor=int(weighted_tco.quantize(Decimal("1"), ROUND_HALF_UP)) if weighted_tco is not None else None,
            annual_savings_minor=savings, explanation=explanation, created_by=principal(session).user_id,
        )
        session.add(scenario)
        session.flush()
        results.append(scenario)
        return scenario

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
    optimum = _optimise(rows, q, event.constraints)
    if optimum:
        store("CAPACITY_CONSTRAINED", optimum["allocations"], True,
              {"rule": "MIP: min Σ x·TCO·Q s.t. capacity (digital twin), share bounds, max suppliers",
               "Q": str(q), "constraints": event.constraints,
               "bounds": {r["supplier"]: f"x ≤ min({event.constraints.get('max_share')}, {r['verifiedCapacityPerMonth']}/{q})"
                          for r in rows}})
    else:
        store("CAPACITY_CONSTRAINED", [], False, {"rule": "no feasible allocation under constraints"})
    instance = workflow.find(session, "SOURCING_EVENT", event.id, PROCESS)
    if instance.current_step == "F3-05":
        workflow.step(session, instance, "F3-05", outcome="no further round")
    workflow.wait(session, instance, "F3-06", outcome="; ".join(
        f"{s.kind}: {'feasible' if s.feasible else 'infeasible'}" + (f" @ {s.weighted_price_minor/100:.2f}" if s.weighted_price_minor else "")
        for s in results))
    return [{"id": str(s.id), "kind": s.kind, "feasible": s.feasible, "allocations": s.allocations,
             "weightedPriceMinor": s.weighted_price_minor, "weightedTcoMinor": s.weighted_tco_minor,
             "annualSavingsMinor": s.annual_savings_minor, "explanation": s.explanation} for s in results]


# ---------------------------------------------------------------- award (F3-07/08/09)
def propose_award(session: Session, event: SourcingEvent, scenario_id: uuid.UUID, rationale: Optional[str],
                  conflict_declaration: str) -> AwardDecision:
    p = principal(session)
    scenario = session.get(AwardScenario, scenario_id)
    if scenario is None or scenario.event_id != event.id or not scenario.feasible:
        raise rule_violation("Choose a feasible scenario of this event", "SRC-AWARD")
    if not conflict_declaration:
        raise rule_violation("A conflict-of-interest declaration is required", "SRC-05")
    rows = evaluation_matrix(session, event)
    lowest_price = min(r["priceMinor"] for r in rows)
    not_lowest = any(a["priceMinor"] > lowest_price for a in scenario.allocations)
    if not_lowest and not rationale:
        raise rule_violation("Award to a non-lowest bid needs a written rationale", "SRC-RATIONALE")
    sod.guard_and_record(session, "SOURCING_AWARD", {"event_id": event.id})
    line = _lines(session, event)[0]
    annual_value = int(Decimal(scenario.weighted_price_minor) * line.annual_qty)
    rule = rules.resolve(session, "AWARD-APPROVAL", category=event.category)
    chain = rules.band_chain(rule, annual_value)
    decision = AwardDecision(tenant_id=event.tenant_id, event_id=event.id, scenario_id=scenario.id, status="PENDING",
                             rationale=rationale, conflict_declarations=[{"user": p.email, "declaration": conflict_declaration}],
                             proposed_by=p.user_id, annual_value_minor=annual_value, rule_set_version=rule.ref, created_by=p.user_id)
    session.add(decision)
    session.flush()
    SM.apply(session, event, "propose_award", reason=rationale, rule_set_version=rule.ref)
    instance = workflow.find(session, "SOURCING_EVENT", event.id, PROCESS)
    workflow.step(session, instance, "F3-06", outcome=f"{scenario.kind} proposed")
    needs_approval = annual_value >= rule.body["approvalAboveMinor"] or not_lowest
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


def _award(session: Session, event: SourcingEvent, decision: AwardDecision, instance) -> None:
    decision.status = "APPROVED"
    scenario = session.get(AwardScenario, decision.scenario_id)
    SM.apply(session, event, "award", rule_set_version=decision.rule_set_version)
    sod.record(session, "SOURCING_AWARD", {"event_id": event.id})
    line = _lines(session, event)[0]
    for pr_line in session.execute(select(PrLine).where(PrLine.requisition_id == line.requisition_id,
                                                        PrLine.line_no == line.pr_line_no)).scalars():
        pr_line.sourcing_status = "SOURCED"
    payload = {"category": event.category, "materialId": str(line.material_id), "plant": line.plant,
               "annualQty": str(line.annual_qty), "monthlyQty": str(line.monthly_qty), "uom": line.uom,
               "baselineMinor": event.baseline_price_minor, "weightedPriceMinor": scenario.weighted_price_minor,
               "allocations": scenario.allocations, "requisitionId": str(line.requisition_id), "prLine": line.pr_line_no,
               "ownerId": str(event.owner_id), "rationale": decision.rationale}
    outbox.emit(session, "sourcing.event.awarded", "SOURCING_EVENT", event.id, event.number, payload)
    audit.record(session, "SOURCING_EVENT", event.id, "AWARD_NOTIFIED", object_ref=event.number,
                 after={"awarded": [a["supplier"] for a in scenario.allocations],
                        "notifiedUnsuccessful": [r["supplier"] for r in evaluation_matrix(session, event)
                                                 if r["supplier"] not in {a["supplier"] for a in scenario.allocations}]})
    workflow.step(session, instance, "F3-09", outcome="suppliers notified; handed off to contract (CLM)")
    workflow.end(session, instance, "F3-10", outcome=" / ".join(f"{a['supplier']} {Decimal(a['share'])*100:.0f}% @ {a['priceMinor']/100:.2f}"
                                                                for a in scenario.allocations) + f"; weighted {scenario.weighted_price_minor/100:.2f}")
