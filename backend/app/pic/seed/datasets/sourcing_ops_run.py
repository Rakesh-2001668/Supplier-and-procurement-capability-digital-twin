"""D17 sourcing_ops engine: the plan of a tenant is turned into dated steps that call the real services (requisition, sourcing, auction, contract).

Every step runs in its own tenant transaction as a named user with the business clock pinned to the step's time (Scenario.act), so state machines, SoD
(an owner, two evaluators, openers), ABAC, audit hash chains, outbox events and the sealed-bid rules behave as in production. A step writes a
SOURCING_OPS_STAGE audit marker in the same transaction and returns the state later steps need (ids, numbers, baselines); a second run finds the markers and
skips the steps, so nothing is written twice and an interrupted run resumes.

Not used on purpose: worker.tick() / Scenario.relay() (they fire every tenant's timers and scheduled jobs). Consumers are delivered with
outbox.relay_tenant(), a close is made by calling sourcing.close(by_timer=True) exactly as the timer does, and the timers of events that the pack closed or
cancelled are marked fired. The timers of events that are still OPEN or PUBLISHED stay: they are due after the real date.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Callable, Optional

from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import AuditEvent, Contract, EventLine, SourcingEvent, Supplier, Timer
from app.pic.platform import audit, clock, outbox
from app.pic.platform.errors import Problem
from app.pic.seed.axion import Scenario, at
from app.pic.tools import sourcing_mock as mock

log = logging.getLogger(__name__)

LABEL = mock.TAG
ACTOR = "mock-data:sourcing_ops"
KEY = "sourcing-ops"
DECLARATION = "No personal or financial interest in any bidder."


@dataclass
class Step:
    when: datetime
    seq: int
    key: str            # event key (K01) or a requisition group label
    name: str
    who: Optional[str]
    fn: Optional[Callable]
    kind: str = "act"   # act: fn(s, st) in one transaction as `who` | custom: fn(ctx, st, when) opens its own transactions | approve | relay


@dataclass
class Ctx:
    tenant_id: uuid.UUID
    code: str
    password: str
    sc: Scenario
    spec: dict
    plan: list
    steps: list = field(default_factory=list)
    st: dict = field(default_factory=dict)         # key -> state carried between steps
    done: dict = field(default_factory=dict)       # stage marker -> state returned by the step
    calls: int = 0
    skipped: int = 0
    notes: list = field(default_factory=list)
    seq: int = 0
    relay_days: set = field(default_factory=set)

    def step(self, key: str, name: str, when: datetime, who: Optional[str], fn: Optional[Callable], kind: str = "act") -> None:
        self.seq += 1
        self.steps.append(Step(when, self.seq, key, name, who, fn, kind))

    def call(self) -> None:
        self.calls += 1


# ---------------------------------------------------------------- stage ledger and executor
def stage_name(step: Step) -> str:
    return f"{step.key}:{step.name}"


def load_done(ctx: Ctx) -> None:
    with tenant_tx(ctx.tenant_id) as s:
        for ref, after in s.execute(select(AuditEvent.object_ref, AuditEvent.after).where(AuditEvent.action == "SOURCING_OPS_STAGE")).all():
            ctx.done[ref] = after or {}


def _marker(s, ctx: Ctx, step: Step, result: dict) -> None:
    audit.record(s, "DATASET", uuid.uuid5(uuid.NAMESPACE_URL, f"{KEY}:{ctx.code}:{stage_name(step)}"), "SOURCING_OPS_STAGE", object_ref=stage_name(step),
                 after=result or {}, actor=ACTOR, reason=LABEL)


def execute(ctx: Ctx) -> None:
    """Run the steps in business-time order. A step already recorded is skipped (its returned state is restored)."""
    load_done(ctx)
    for step in sorted(ctx.steps, key=lambda x: (x.when, x.seq)):
        name = stage_name(step)
        st = ctx.st.setdefault(step.key, {})
        if name in ctx.done:
            st.update(ctx.done[name])
            ctx.skipped += 1
            continue
        clock.set_pinned(step.when)
        result: dict = {}
        if step.kind == "relay":
            outbox.relay_tenant(ctx.tenant_id)
        elif step.kind == "approve":
            ctx.calls += ctx.sc.approve_all(uuid.UUID(st["id"]), step.when, step.name)
        elif step.kind == "custom":
            result = step.fn(ctx, st, step.when) or {}
        else:
            with ctx.sc.act(step.who, step.when) as s:
                result = step.fn(s, st) or {}
                _marker(s, ctx, step, result)
            st.update(result)
            continue
        with tenant_tx(ctx.tenant_id) as s:
            _marker(s, ctx, step, result)
        st.update(result)
    clock.set_pinned(None)


# ---------------------------------------------------------------- small helpers
def ist(day: date, hour: int = 10, minute: int = 0) -> datetime:
    return at(day, hour, minute)


def day_of(when: datetime) -> date:
    return when.astimezone(clock.IST).date()


def fire_timers(s, event_id) -> int:
    """The pack closed / cancelled the event itself: its unfired timers are marked fired so the worker does not run them later."""
    n = 0
    for timer in s.execute(select(Timer).where(Timer.object_id == event_id, Timer.fired_at.is_(None), Timer.kind.in_(("SOURCING_CLOSE", "SOURCING_OPEN")))).scalars():
        timer.fired_at, timer.payload = clock.now(), {**(timer.payload or {}), "firedBy": "sourcing_ops"}
        n += 1
    return n


def bidder_email(ctx: Ctx, code: str) -> str:
    return f"bids.{code.lower()}@suppliers.{ctx.spec['domain']}"


def criteria_for(row: dict) -> list[dict]:
    gate = {"min_score": "50"}
    if row["type"] == "REVERSE_AUCTION":
        return [{"code": "PRICE_TCO", "name": "Price / TCO", "weight": 70}, {"code": "QUALITY", "name": "Quality (scorecard)", "weight": 15, "data_source": "SCORECARD"},
                {"code": "DELIVERY", "name": "Delivery (scorecard)", "weight": 15, "data_source": "SCORECARD"}]
    if row["type"] == "RFI":
        return [{"code": "TECHNICAL", "name": "Technical capability", "weight": 60}, {"code": "QUALITY", "name": "Quality system", "weight": 40}]
    if row["type"] == "RFP":
        return [{"code": "PRICE_TCO", "name": "Price / TCO", "weight": 30}, {"code": "TECHNICAL", "name": "Technical solution", "weight": 40, **gate},
                {"code": "QUALITY", "name": "Quality and references", "weight": 20}, {"code": "DELIVERY", "name": "Delivery (scorecard)", "weight": 10, "data_source": "SCORECARD"}]
    return [{"code": "PRICE_TCO", "name": "Price / TCO", "weight": 50}, {"code": "QUALITY", "name": "Quality", "weight": 20},
            {"code": "DELIVERY", "name": "Delivery (scorecard)", "weight": 15, "data_source": "SCORECARD"}, {"code": "TECHNICAL", "name": "Technical", "weight": 15, **gate}]


def manual_codes(criteria: list[dict]) -> list[str]:
    return [c["code"] for c in criteria if c["code"] != "PRICE_TCO" and (c.get("data_source") or "MANUAL") == "MANUAL"]


def close_time(row: dict, created: date) -> datetime:
    if row["type"] == "REVERSE_AUCTION":
        return ist(created + timedelta(days=3), 15, 0)
    if row["outcome"] == "OPEN":
        return ist(created + timedelta(days=14), 17, 0)
    if row["outcome"] == "PUBLISHED":
        return ist(created + timedelta(days=26), 17, 0)
    return ist(created + timedelta(days=10 if row["type"] in ("RFP", "RFI") else 7), 17, 0)


# ---------------------------------------------------------------- bid construction
def bid_line(row: dict, st: dict, res: dict, code: str, index: int, discount: float = 0.0) -> dict:
    """One bid line of a supplier for event line ``index`` (deterministic from the plan key, the supplier and the line)."""
    key = row["key"]
    line = res["lines"][index]
    baseline = int(st.get("baselines", {}).get(str(line["no"]), line["price_minor"]))
    terms = mock.bid_terms(f"{key}|{line['no']}", code, baseline, low_bias=res["bias"].get(code, 0.0) - discount)
    monthly = Decimal(line["monthly_qty"])
    factor = Decimal(repr(res["capacity"].get(code, mock.between(1.15, 2.4, "cap", key, code))))
    out = {"line": line["no"], "unit_price": terms["unit_price"], "payment_terms_days": terms["payment_terms_days"], "lead_time_days": terms["lead_time_days"],
           "capacity_per_month": str((monthly * factor).quantize(Decimal("1")))}
    if mock.unit("exw", key, code) < 0.25:
        out["incoterm"] = "EXW"          # no freight quoted: the TCO rule estimates it
    else:
        out["freight"], out["packaging"], out["incoterm"] = terms["freight"], terms["packaging"], "DAP"
    importer = res.get("importers", {}).get(code)
    if importer:
        out["unit_price"] = str((Decimal(terms["unit_price"]) / Decimal(importer["rate"])).quantize(Decimal("0.0001")))
        out["currency"], out["origin"], out["incoterm"] = "USD", "IMPORT", "FOB"
        out.pop("freight", None)
        out.pop("packaging", None)
        if importer.get("hs"):
            out["hs_code"] = importer["hs"]
    return out


def valid_until(close_at: datetime) -> date:
    return day_of(close_at) + timedelta(days=45)


def get_event(s, st) -> SourcingEvent:
    return s.get(SourcingEvent, uuid.UUID(st["id"]))


def supplier_of(s, code: str) -> Supplier:
    return s.execute(select(Supplier).where(Supplier.code == code)).scalar_one()


# ---------------------------------------------------------------- one event
def plan_event(ctx: Ctx, row: dict) -> None:
    """All dated steps of one event, according to its outcome."""
    spec, key, outcome, state = ctx.spec, row["key"], row["outcome"], row["state"]
    created = date.fromisoformat(row["created"])
    owner = spec["owner_for"](row["category"])
    st0 = ctx.st.setdefault(key, {})
    res = st0["res"]                    # resolved before planning: lines, suppliers, quantities (sourcing_ops.resolve)
    criteria = criteria_for(row)
    manual = manual_codes(criteria)
    close_at = close_time(row, created)
    auction = row["type"] == "REVERSE_AUCTION"
    two_person = bool(row.get("twoPerson"))

    def create(s, st):
        from app.pic.services import should_cost as sc_svc
        from app.pic.services import sourcing

        lines = []
        for line in res["lines"]:
            entry = {"requisition": ctx.st[line["pr"]]["number"], "line": line["pr_line"], "annual_qty": line["annual_qty"], "monthly_qty": line["monthly_qty"]}
            if line.get("lot"):
                entry["lot"] = line["lot"]
            if row["baselineMethod"] in ("BUDGET", "MANUAL"):
                entry["baseline_price_minor"] = line["budget_minor"]
            lines.append(entry)
        extra: dict = {}
        model = res.get("model")
        if model and len(lines) == 1:
            target = int(Decimal(res["lines"][0]["price_minor"]) * Decimal("0.93"))
            base_inputs = dict(model["defaultInputs"])
            probe = sc_svc.evaluate_spec(s, model["spec"], base_inputs, created, code=model["code"])
            factor = Decimal(target) / Decimal(probe["unitCostMinor"]) if probe["unitCostMinor"] else Decimal(1)
            extra["should_cost_model"] = {"code": model["code"], "inputs": mock.scale_inputs(base_inputs, factor)}
        constraints = {"max_suppliers": 2, "max_share": "0.60", "min_share": "0.20"}
        if outcome in ("PENDING_NON_LOWEST", "AWARD_NON_LOWEST", "CANCEL_PENDING"):
            constraints = {"max_suppliers": 2, "max_share": "1", "min_share": "0"}   # a sole source to a bidder that is not the cheapest: the 60 % cap would refuse it
        if two_person:
            constraints["two_person_opening"] = True
        if outcome == "PUBLISHED":
            extra["open_at"] = ist(created + timedelta(days=12), 9, 0)
        ctx.call()
        if row.get("cloneOf"):
            from app.pic.services import sourcing_templates
            source = s.get(SourcingEvent, uuid.UUID(ctx.st[row["cloneOf"]]["id"]))
            event = s.get(SourcingEvent, uuid.UUID(sourcing_templates.clone(s, source, close_at=close_at, title=res["title"], lines=lines)["id"]))
        elif row.get("template"):
            from app.pic.services import sourcing_templates
            extra.pop("open_at", None)
            event = sourcing_templates.create_from_template(s, "RFQ-DIRECT-MATERIAL", title=res["title"], category=row["category"], lines=lines, close_at=close_at,
                                                            invitees=[{"supplier": code} for code in res["invitees"]], **extra)
        else:
            event = sourcing.create_event(
                s, type=row["type"], title=res["title"], category=row["category"], lines=lines, criteria=criteria,
                invitees=[{"supplier": code} for code in res["invitees"]], close_at=close_at, baseline_method=row["baselineMethod"], constraints=constraints,
                savings_target_pct=Decimal("3.0"), **extra)
        db_lines = s.execute(select(EventLine).where(EventLine.event_id == event.id).order_by(EventLine.line_no)).scalars().all()
        return {"id": str(event.id), "number": event.number, "baselines": {str(l.line_no): int(l.baseline_price_minor or res["lines"][i]["price_minor"])
                                                                           for i, l in enumerate(db_lines)},
                "reference": event.reference_date.isoformat(), "shouldCost": (event.should_cost or {}).get("unitCostMinor")}
    ctx.step(key, "create", ist(created, 10, 0), owner, create)
    if state == "DRAFT":
        return

    if outcome == "CANCEL_DRAFT":
        def cancel_draft(s, st):
            from app.pic.services import sourcing
            ctx.call()
            sourcing.cancel(s, get_event(s, st), "Requirement withdrawn by the requester before publication: the demand moved to the framework contract.")
            return {"cancelled": True}
        ctx.step(key, "cancel", ist(created, 15, 0), owner, cancel_draft)
        return

    def publish(s, st):
        from app.pic.services import sourcing
        ctx.call()
        sourcing.publish(s, get_event(s, st))
        return {"published": True}
    ctx.step(key, "publish", ist(created, 10, 30), owner, publish)
    ctx.relay_days.add(created)
    if row.get("clarifications"):
        clarifications(ctx, row, res["bidders"][0], created + timedelta(days=1), published=state == "PUBLISHED")
    if state == "PUBLISHED":
        return

    (auction_bids if auction else sealed_bids)(ctx, row, created, close_at)
    if outcome == "CANCEL_OPEN":
        def cancel_open(s, st):
            from app.pic.services import sourcing
            ctx.call()
            sourcing.cancel(s, get_event(s, st), "The specification changed after the technical review; the event is withdrawn and will be re-issued.")
            return {"cancelled": True}
        ctx.step(key, "cancel", ist(created + timedelta(days=4), 15, 0), owner, cancel_open)
        ctx.relay_days.add(created + timedelta(days=4))
        return
    if state == "OPEN":
        return

    # ---- close (the timer's own call), the refused late bid and the refused early access
    close_when = close_at + timedelta(minutes=11 if row.get("softClose") else 2)
    if row.get("lateBid"):
        def late(s, st):
            from app.pic.services import sourcing
            try:
                ctx.call()
                sourcing.submit_bid(s, get_event(s, st), supplier_of(s, res["lateBidder"]), [bid_line(row, st, res, res["lateBidder"], 0)])
            except Problem as exc:
                if exc.code != "EVENT_CLOSED":
                    raise
                return {"lateRefused": True}
            raise RuntimeError("the late bid was accepted")
        ctx.step(key, "late-bid", close_at + timedelta(minutes=1), bidder_email(ctx, res["lateBidder"]), late)

    def close(s, st):
        from app.pic.services import sourcing
        event = get_event(s, st)
        ctx.call()
        result = sourcing.close(s, event, by_timer=True)
        fire_timers(s, event.id)
        return {"awaitingOpening": bool(result.get("awaitingOpening")), "unsealed": result.get("unsealed")}
    ctx.step(key, "close", close_when, owner, close)
    if row.get("earlyOpen"):
        def early(s, st):
            from app.pic.services import sourcing
            try:
                ctx.call()
                sourcing.bids_view(s, get_event(s, st))
            except Problem as exc:
                if exc.code != "BIDS_SEALED":
                    raise
                return {"earlyRefused": True}
            raise RuntimeError("the sealed bids were shown before the opening")
        ctx.step(key, "early-open", close_when + timedelta(minutes=30), owner, early)
    t_eval = ist(day_of(close_when) + timedelta(days=1), 10, 0)
    if two_person:
        for i in range(int(row.get("openers", 2))):
            def open_(s, st, i=i):
                from app.pic.services import sourcing
                ctx.call()
                sourcing.open_bids(s, get_event(s, st))
                return {f"opener{i + 1}": True}
            ctx.step(key, f"open-{i + 1}", close_when + timedelta(hours=2 + i), spec["openers_for"](row["category"])[i], open_)
        if state == "CLOSED":
            return
    if outcome == "CANCEL_BIDS":
        def cancel_bids(s, st):
            from app.pic.services import sourcing
            ctx.call()
            sourcing.cancel(s, get_event(s, st), "Drawing revision B changes the tolerance on the bore: the bids no longer describe the part, the event is cancelled and re-tendered.")
            return {"cancelled": True}
        ctx.step(key, "cancel", t_eval, owner, cancel_bids)
        ctx.relay_days.add(day_of(t_eval))
        return

    # ---- second round of a multi-round event
    if outcome == "AWARD_ROUNDS":
        round2 = ist(day_of(close_when) + timedelta(days=1), 9, 30)
        close2 = ist(day_of(close_when) + timedelta(days=4), 17, 0)

        def new_round(s, st):
            from app.pic.services import sourcing
            ctx.call()
            sourcing.new_round(s, get_event(s, st), close2, "negotiation round: the three lowest bidders are invited to improve their prices")
            return {"round": 2}
        ctx.step(key, "round-2", round2, owner, new_round)
        for i, code in enumerate(res["bidders"][:3]):
            def rebid(s, st, code=code, i=i):
                from app.pic.services import sourcing
                ctx.call()
                sourcing.submit_bid(s, get_event(s, st), supplier_of(s, code), [bid_line(row, st, res, code, n, discount=0.035 + 0.01 * i) for n in range(len(res["lines"]))],
                                    valid_until=valid_until(close2))
                return {f"rebid{i}": True}
            ctx.step(key, f"rebid-{code}", round2 + timedelta(days=1, hours=2 + i), bidder_email(ctx, code), rebid)

        def close_2(s, st):
            from app.pic.services import sourcing
            event = get_event(s, st)
            ctx.call()
            sourcing.close(s, event, by_timer=True)
            fire_timers(s, event.id)
            return {"closed2": True}
        close_when = close2 + timedelta(minutes=2)
        ctx.step(key, "close-2", close_when, owner, close_2)
        t_eval = ist(day_of(close_when) + timedelta(days=1), 10, 0)

    # ---- evaluation: conflict declarations and scores of two evaluators
    for n, who in enumerate(spec["evaluators_for"](row["category"])):
        if outcome == "EVAL_PARTIAL" and n == 1:
            break
        if not manual and n == 1:
            break

        def evaluate(s, st, who=who, n=n):
            from app.pic.services import sourcing
            event = get_event(s, st)
            ctx.call()
            sourcing.declare_conflict(s, event, False, DECLARATION)
            entries = []
            for code in res["scored"]:
                for crit in manual:
                    if n == 1 and crit != manual[0]:
                        continue       # the second evaluator scores the first criterion independently; the other criteria have one scorer
                    value = 58 + 36 * mock.unit("score", key, code, crit, who)
                    if crit == "TECHNICAL" and code == res.get("gateFail"):
                        value = 30
                    entries.append({"supplier": code, "criterion": crit, "score": str(Decimal(repr(value)).quantize(Decimal("0.1")))})
            if entries:
                ctx.call()
                sourcing.score(s, event, entries)
            return {f"scored{n}": len(entries)}
        ctx.step(key, f"evaluate-{n + 1}", t_eval + timedelta(hours=n), who, evaluate)
    if outcome.startswith("EVAL"):
        return

    if outcome == "AWARD_DISQ":
        def disqualify(s, st):
            from app.pic.services import sourcing
            ctx.call()
            sourcing.disqualify(s, get_event(s, st), supplier_of(s, res["disqualified"]),
                                "Mandatory IATF 16949 certificate was not attached to the bid and was not supplied within the clarification period.")
            return {"disqualified": res["disqualified"]}
        ctx.step(key, "disqualify", t_eval + timedelta(hours=4), owner, disqualify)

    # ---- scenarios and the award proposal
    t_scen = t_eval + timedelta(hours=5)

    def award(s, st):
        from app.pic.services import sourcing
        event = get_event(s, st)
        ctx.call()
        built = sourcing.build_scenarios(s, event)
        kind = {"AWARD_CAPACITY": "CAPACITY_CONSTRAINED", "AWARD_BEST_VALUE": "BEST_VALUE"}.get(outcome, "LOWEST_COST")
        chosen = next((x for x in built if x["kind"] == kind and x["feasible"]), None) or next((x for x in built if x["feasible"]), None)
        rationale = ("Awarded on total cost of ownership and the weighted score; every awarded bidder passed the technical gate, has verified capacity "
                     "and a complete TCO.")
        matrix = sourcing.evaluation_matrix(s, event)
        if outcome in ("AWARD_SPLIT", "PENDING_NON_LOWEST", "AWARD_NON_LOWEST", "CANCEL_PENDING") and len(matrix) >= 2:
            if outcome == "AWARD_SPLIT":
                allocations = [{"supplier": matrix[0]["supplier"], "share_pct": "60"}, {"supplier": matrix[1]["supplier"], "share_pct": "40"}]
                rationale = "Dual source 60/40 to cover the volume and keep a second qualified source; the second supplier accepts the price level of the first."
            else:
                by_price = sorted(matrix, key=lambda r: r["priceMinor"])
                pick = by_price[-2] if len(by_price) > 2 else by_price[-1]
                allocations = [{"supplier": pick["supplier"], "share_pct": "100"}]
                rationale = ("Not the lowest price: the selected supplier has the best technical and delivery record on this part, the lowest PPM in the twin and a "
                             "shorter lead time that avoids buffer stock; the premium is covered by the lower quality cost.")
            ctx.call()
            custom = sourcing.custom_scenario(s, event, allocations)
            if custom["feasible"]:
                chosen = custom
        if chosen is None:
            raise RuntimeError(f"{key}: no feasible scenario: {[(x['kind'], x['explanation'].get('rule')) for x in built]}")
        ctx.call()
        sourcing.propose_award(s, event, uuid.UUID(chosen["id"]), rationale, DECLARATION)
        return {"scenario": chosen["kind"], "status": event.status}
    ctx.step(key, "award", t_scen, owner, award)
    ctx.relay_days.add(day_of(t_scen))
    after_award(ctx, row, t_scen)


def after_award(ctx: Ctx, row: dict, base: datetime) -> None:
    """Approvals of the award, delivery of the outbox events (contract drafts, savings, notifications) and, for some events, the contract path to ACTIVE."""
    key, spec, outcome = row["key"], ctx.spec, row["outcome"]
    if outcome.startswith("PENDING"):
        return
    if outcome == "CANCEL_PENDING":
        def cancel_pending(s, st):
            from app.pic.services import sourcing
            ctx.call()
            sourcing.cancel(s, get_event(s, st), "The award was withdrawn: the selected supplier lost its IATF certificate during the approval; the event is re-tendered.")
            return {"cancelled": True}
        ctx.step(key, "cancel", base + timedelta(days=1, hours=1), spec["owner_for"](row["category"]), cancel_pending)
        ctx.relay_days.add(day_of(base + timedelta(days=1)))
        return
    ctx.step(key, "approve", base + timedelta(days=1), None, None, kind="approve")
    ctx.relay_days.add(day_of(base + timedelta(days=1)))
    if row.get("activate"):
        activate_contracts(ctx, row, base + timedelta(days=2))


def contracts_of(ctx: Ctx, st: dict) -> list[tuple]:
    with tenant_tx(ctx.tenant_id) as s:
        return sorted(((c.id, c.number, s.get(Supplier, c.supplier_id).code) for c in
                       s.execute(select(Contract).where(Contract.source_event_id == uuid.UUID(st["id"]))).scalars()), key=lambda t: t[1])


def activate_contracts(ctx: Ctx, row: dict, start: datetime) -> None:
    """Review, submit, approve, sign (buyer and supplier) and activate every contract the award created."""
    key, spec = row["key"], ctx.spec

    def review(ctx_, st, when):
        from app.pic.services import contract as contract_svc
        out = []
        for cid, number, _ in contracts_of(ctx_, st):
            with ctx_.sc.act(spec["contract_manager"], when) as s:
                ctx_.call()
                contract_svc.ai_review(s, s.get(Contract, cid))
                ctx_.call()
                contract_svc.submit(s, s.get(Contract, cid))
            out.append(number)
        return {"contracts": out}
    ctx.step(key, "contract-review", start + timedelta(hours=1), None, review, kind="custom")

    def approve(ctx_, st, when):
        for cid, _, _ in contracts_of(ctx_, st):
            ctx_.calls += ctx_.sc.approve_all(cid, when, "Standard clauses; value approved")
        return {"contractsApproved": True}
    ctx.step(key, "contract-approve", start + timedelta(days=1), None, approve, kind="custom")

    def sign(ctx_, st, when):
        from app.pic.services import contract as contract_svc
        for cid, _, code in contracts_of(ctx_, st):
            with ctx_.sc.act(spec["contract_manager"], when) as s:
                ctx_.call()
                contract_svc.sign(s, s.get(Contract, cid), "BUYER", "Contract Manager, Kaveri Auto Components (MOCK signatory)")
            with ctx_.sc.act(bidder_email(ctx_, code), when + timedelta(hours=2)) as s:
                ctx_.call()
                contract_svc.sign(s, s.get(Contract, cid), "SUPPLIER", "Authorised signatory (MOCK)")
        return {"signed": True}
    ctx.step(key, "contract-sign", start + timedelta(days=3), None, sign, kind="custom")

    def activate(ctx_, st, when):
        from app.pic.services import contract as contract_svc
        for cid, _, _ in contracts_of(ctx_, st):
            with ctx_.sc.act(spec["contract_manager"], when) as s:
                ctx_.call()
                contract_svc.activate(s, s.get(Contract, cid))
        return {"activated": True}
    ctx.step(key, "contract-activate", start + timedelta(days=4), None, activate, kind="custom")
    ctx.relay_days.add(day_of(start + timedelta(days=4)))


# ---------------------------------------------------------------- clarification board and bids
def clarifications(ctx: Ctx, row: dict, asker: str, day: date, published: bool) -> None:
    key, spec = row["key"], ctx.spec
    texts = [("Please confirm the material grade and the inspection standard that applies to the first-off sample.",
              "The grade is as in the attached drawing; first-off sample inspection follows the customer quality plan, dimensional report required."),
             ("Is a split of the annual volume between two suppliers acceptable, and may we quote ex-works with freight on your account?",
              "A split between two suppliers is possible (see the award constraints); ex-works quotes are accepted and the freight is estimated by the buyer.")]
    for n in range(int(row["clarifications"])):
        question, answer = texts[n % 2]

        def ask(s, st, question=question, n=n):
            from app.pic.services import auction
            ctx.call()
            item = auction.ask(s, get_event(s, st), question)
            return {f"q{n}": item.seq}
        ctx.step(key, f"ask-{n + 1}", ist(day, 14, 0) + timedelta(minutes=n * 10), bidder_email(ctx, asker), ask)
        if published:
            continue

        def reply(s, st, answer=answer, n=n):
            from app.pic.services import auction
            ctx.call()
            auction.answer(s, get_event(s, st), st[f"q{n}"], answer)
            return {f"a{n}": True}
        ctx.step(key, f"answer-{n + 1}", ist(day, 16, 0) + timedelta(minutes=n * 10), spec["owner_for"](row["category"]), reply)
    if not published and key in ("K03",):
        def notice(s, st):
            from app.pic.services import auction
            ctx.call()
            auction.ask(s, get_event(s, st), "Notice to all bidders: the delivery schedule is monthly, the first lot is due 45 days after the contract starts.")
            return {"notice": True}
        ctx.step(key, "notice", ist(day + timedelta(days=1), 11, 0), spec["owner_for"](row["category"]), notice)


def sealed_bids(ctx: Ctx, row: dict, created: date, close_at: datetime) -> None:
    key, spec = row["key"], ctx.spec
    res = ctx.st[key]["res"]
    n_bids = row.get("bids", len(res["bidders"]))
    first_day = created + timedelta(days=2)
    span = max(1, (day_of(close_at) - first_day).days - 1)
    for i, code in enumerate(res["bidders"][:n_bids]):
        day = created + timedelta(days=1 + (i % 3)) if row["outcome"] == "OPEN" else first_day + timedelta(days=i % span)
        when = ist(day, 11 + (i % 5), 10 + i)

        def bid(s, st, code=code, i=i):
            from app.pic.services import sourcing
            lots = [{"lot": "L1", "discount_pct": str(2 + (i % 3)), "all_or_nothing": i == 1}] if res.get("lotTerms") else None
            ctx.call()
            sourcing.submit_bid(s, get_event(s, st), supplier_of(s, code), [bid_line(row, st, res, code, n) for n in range(len(res["lines"]))], lots,
                                valid_until=valid_until(close_at))
            return {f"bid{i}": True}
        ctx.step(key, f"bid-{code}", when, bidder_email(ctx, code), bid)
        if row.get("withdraw") and i == 0:
            def replace(s, st, code=code):
                from app.pic.services import sourcing
                ctx.call()
                sourcing.submit_bid(s, get_event(s, st), supplier_of(s, code), [bid_line(row, st, res, code, n, discount=0.015) for n in range(len(res["lines"]))],
                                    valid_until=valid_until(close_at))
                return {"replaced": code}
            ctx.step(key, f"replace-{code}", when + timedelta(days=1, hours=1), bidder_email(ctx, code), replace)
        if row.get("withdraw") and i == 1:
            def withdraw(s, st, code=code):
                from app.pic.services import sourcing
                ctx.call()
                sourcing.withdraw_bid(s, get_event(s, st), supplier_of(s, code), "Our costing sheet used an outdated alloy price; we will submit again.")
                return {"withdrawn": code}
            ctx.step(key, f"withdraw-{code}", when + timedelta(hours=3), bidder_email(ctx, code), withdraw)

            def rebid(s, st, code=code):
                from app.pic.services import sourcing
                ctx.call()
                sourcing.submit_bid(s, get_event(s, st), supplier_of(s, code), [bid_line(row, st, res, code, n, discount=0.02) for n in range(len(res["lines"]))],
                                    valid_until=valid_until(close_at))
                return {"rebid": code}
            ctx.step(key, f"rebid-{code}", when + timedelta(days=1), bidder_email(ctx, code), rebid)
    if row.get("uninvited"):
        def uninvited(s, st):
            from app.pic.services import sourcing
            try:
                ctx.call()
                sourcing.submit_bid(s, get_event(s, st), supplier_of(s, res["uninvitedBidder"]), [bid_line(row, st, res, res["uninvitedBidder"], 0)])
            except Problem as exc:
                if exc.code != "NOT_INVITED":
                    raise
                return {"uninvitedRefused": True}
            raise RuntimeError("an uninvited supplier could bid")
        ctx.step(key, "uninvited-bid", ist(first_day, 15, 0), bidder_email(ctx, res["uninvitedBidder"]), uninvited)
    if row.get("earlyView"):
        def early_view(s, st):
            from app.pic.services import sourcing
            try:
                ctx.call()
                sourcing.bids_view(s, get_event(s, st))
            except Problem as exc:
                if exc.code != "BIDS_SEALED":
                    raise
                return {"earlyRefused": True}
            raise RuntimeError("bids were shown while the event is open")
        ctx.step(key, "early-view", ist(created + timedelta(days=3), 12, 0), spec["owner_for"](row["category"]), early_view)


def auction_bids(ctx: Ctx, row: dict, created: date, close_at: datetime) -> None:
    key = row["key"]
    res = ctx.st[key]["res"]
    day = day_of(close_at)
    bidders = res["bidders"]
    for rnd in range(2):
        for i, code in enumerate(bidders):
            def bid(s, st, code=code, rnd=rnd, i=i):
                from app.pic.services import auction
                base = int(st["baselines"]["10"])
                price = int(Decimal(base) * Decimal(repr(1 + mock.between(-0.08, 0.06, "auction", key, code))) * Decimal(repr(0.985 ** rnd)))
                ctx.call()
                auction.place_bid(s, get_event(s, st), supplier_of(s, code), price)
                return {f"abid{rnd}{i}": price}
            ctx.step(key, f"auction-{rnd + 1}-{code}", ist(day, 13, 0) + timedelta(minutes=rnd * 30 + i * 5), bidder_email(ctx, code), bid)
    if row.get("softClose"):
        for n, (hh, mm) in enumerate([(14, 59), (15, 4)]):
            code = bidders[n % len(bidders)]

            def late_bid(s, st, code=code, n=n):
                from app.pic.services import auction
                ctx.call()
                auction.place_bid(s, get_event(s, st), supplier_of(s, code), int(Decimal(st["baselines"]["10"]) * Decimal(repr(0.80 - 0.01 * n))))
                return {f"soft{n}": True}
            ctx.step(key, f"auction-soft-{n + 1}", ist(day, hh, mm) + timedelta(seconds=20), bidder_email(ctx, code), late_bid)
