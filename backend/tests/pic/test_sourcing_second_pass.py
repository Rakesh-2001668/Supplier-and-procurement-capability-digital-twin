"""Strategic sourcing (M05) second pass: defects found against the Technical Document and Blueprint, and the controls, calculations and checks built
for them (docs/PIC_Strategic_Sourcing_Analysis.md, defects R1-R18).

Every test that writes runs in one transaction that is rolled back at the end (or only reads the signature case), so the signature-case KPIs and
documents other files check never change. Times are pinned to 2029, after every seeded object. Rule versions a test needs are added inside its
own transaction.
"""
import itertools
import json
import random
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuditEvent, AwardDecision, Bid, BidLine, CategoryPlan, Criterion, FxRate, IndexValue, Material, OutboxEvent, PrLine, PriceBenchmark,
    Requisition, RuleSet, SavingsInitiative, SavingsLedgerEntry, Scorecard, SourcingEvent, Supplier, SupplierCategoryStatus, Tenant, Timer, TwinSnapshot,
)
from app.pic.platform import clock, sourcing_defaults, workflow
from app.pic.platform.auth import Principal, scopes_for
from app.pic.platform.errors import Problem
from app.pic.services import auction, kpi, savings, should_cost, sourcing, sourcing_analysis, sourcing_kpi, sourcing_tco, sourcing_templates

IST = clock.IST
SIGNATURE_EVENT = "DC-330 aluminium die-cast housing – annual requirement"
PRICE_ONLY = [{"code": "PRICE_TCO", "name": "Price / TCO", "weight": 100}]
SCORED = [{"code": "PRICE_TCO", "name": "Price / TCO", "weight": 70}, {"code": "QUALITY", "name": "Quality", "weight": 30}]
BID = {"line": 10, "unit_price": "400", "payment_terms_days": 60, "lead_time_days": 14, "capacity_per_month": "5000"}
OPEN_SHARES = {"max_suppliers": 2, "max_share": "1", "min_share": "0"}


def at(y, m, d, hh=10, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


class _Rollback(Exception):
    pass


def _tid():
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()


@contextmanager
def rolled_back(when: datetime):
    """One tenant transaction that is always rolled back."""
    clock.set_pinned(when)
    try:
        with pytest.raises(_Rollback):
            with tenant_tx(_tid()) as s:
                yield s
                raise _Rollback()
    finally:
        clock.set_pinned(None)


def act(s, who: str) -> AppUser:
    user = s.execute(select(AppUser).where(AppUser.email == f"{who}@axion.example")).scalar_one()
    s.info["principal"] = Principal(user_id=user.id, tenant_id=user.tenant_id, tenant_code="AXN", email=user.email, name=user.full_name,
                                    roles=list(user.roles), scopes=scopes_for(list(user.roles)), attributes=user.attributes or {},
                                    supplier_id=user.supplier_id)
    s.info["user_id"] = user.id
    return user


def supplier(s, code: str) -> Supplier:
    return s.execute(select(Supplier).where(Supplier.code == code)).scalar_one()


def problem(fn, *args, **kwargs) -> Problem:
    with pytest.raises(Problem) as exc:
        fn(*args, **kwargs)
    return exc.value


def material(s, number: str) -> Material:
    return s.execute(select(Material).where(Material.number == number)).scalar_one()


def policy(s, **patch):
    """A SOURCING-POLICY / SOURCING-TCO version for this transaction only (effective 2029, after the seeded 2026.1)."""
    key = patch.pop("_key", sourcing_defaults.POLICY_KEY)
    tid = _tid()
    earlier = len(s.execute(select(RuleSet.id).where(RuleSet.key == key, RuleSet.version.like("T-%"))).scalars().all())
    # each call is effective a day later than the one before, so the latest one wins deterministically
    s.add(RuleSet(tenant_id=tid, key=key, version=f"T-{uuid.uuid4().hex[:6]}", effective_from=date(2029, 1, 2) + timedelta(days=earlier), body=patch,
                  description="test"))
    s.flush()


def _draft(s, title: str, close_at: datetime, criteria=PRICE_ONLY, constraints=None, who="category.head", invitees=("TF001", "KD002"), **kw) -> SourcingEvent:
    act(s, who)
    return sourcing.create_event(
        s, type=kw.pop("type", "RFQ"), title=title, category="ALU-DIECAST",
        lines=kw.pop("lines", [{"requisition": "REQ-2312", "line": 10, "annual_qty": "20000", "monthly_qty": "2000"}]), criteria=criteria,
        invitees=[{"supplier": c} for c in invitees], close_at=close_at, baseline_method=kw.pop("baseline_method", "BUDGET"),
        baseline_price_minor=kw.pop("baseline_price_minor", 42000), constraints=constraints or OPEN_SHARES, savings_target_pct=Decimal("3.0"), **kw)


def _bid(s, who: str, event: SourcingEvent, **overrides) -> Bid:
    user = act(s, who)
    return sourcing.submit_bid(s, event, s.get(Supplier, user.supplier_id), [{**BID, **overrides}])


def _close(s, event: SourcingEvent, when: datetime, who="category.head") -> dict:
    clock.set_pinned(when)
    act(s, who)
    return sourcing.close(s, event)


def _declare(s, event, who):
    act(s, who)
    sourcing.declare_conflict(s, event, False, "No personal or financial interest in any bidder.")


def _scored_event(s, title="src2 scored", **kw) -> SourcingEvent:
    """An event with price 70 / quality 30, TF001 at 400 and KD002 at 405 bidding, closed and under evaluation."""
    event = _draft(s, title, at(2029, 3, 8, 17), criteria=SCORED, **kw)
    sourcing.publish(s, event)
    _bid(s, "tf.sales", event)
    _bid(s, "kd.sales", event, unit_price="405")
    _close(s, event, at(2029, 3, 8, 17, 5))
    return event


def _score_all(s, event, tf=80, kd=70):
    _declare(s, event, "quality.engineer")
    act(s, "quality.engineer")
    sourcing.score(s, event, [{"supplier": "TF001", "criterion": "QUALITY", "score": tf}, {"supplier": "KD002", "criterion": "QUALITY", "score": kd}])
    _declare(s, event, "category.manager")
    act(s, "category.manager")
    sourcing.score(s, event, [{"supplier": "TF001", "criterion": "QUALITY", "score": tf}, {"supplier": "KD002", "criterion": "QUALITY", "score": kd}])


def _scenarios(s, event) -> dict:
    act(s, "category.head")
    return {x["kind"]: x for x in sourcing.build_scenarios(s, event)}


def _requirement(s, lines, purpose="STOCK_REPLENISHMENT") -> Requisition:
    base = s.execute(select(Requisition).where(Requisition.number == "REQ-2312")).scalar_one()
    base_line = s.execute(select(PrLine).where(PrLine.requisition_id == base.id, PrLine.line_no == 10)).scalar_one()
    pr = Requisition(tenant_id=base.tenant_id, number=f"REQ-S2-{uuid.uuid4().hex[:8]}", origin="MANUAL", requester_id=base.requester_id,
                     company_code=base.company_code, plant=base.plant, status="APPROVED", total_minor=0, purpose_code=purpose)
    s.add(pr)
    s.flush()
    for index, (number, qty) in enumerate(lines, start=1):
        m = material(s, number)
        s.add(PrLine(tenant_id=base.tenant_id, requisition_id=pr.id, line_no=index * 10, item_type="MATERIAL", purchase_type="STOCK", material_id=m.id,
                     description=m.description, material_group=m.material_group, category=m.category, qty=Decimal(qty), uom=m.base_uom,
                     price_est_minor=40000, need_date=date(2029, 6, 1), plant=base_line.plant))
    s.flush()
    return pr


def _audit(s, event, action):
    return s.execute(select(AuditEvent).where(AuditEvent.object_id == event.id, AuditEvent.action == action).order_by(AuditEvent.seq)).scalars().all()


# ================================================================ R1 time handling
def test_src2_naive_deadlines_are_read_as_ist_and_never_compared_naive():
    with rolled_back(at(2029, 3, 1)) as s:
        event = _draft(s, "src2 naive deadline", datetime(2029, 3, 8, 17, 0), clarification_close_at=datetime(2029, 3, 6, 12, 0))
        assert event.close_at.utcoffset() == timedelta(hours=5, minutes=30) and event.clarification_close_at.hour == 12
        assert sourcing.publish(s, event).status == "OPEN"  # a naive close time used to raise TypeError when compared with the pinned (aware) clock
        _bid(s, "tf.sales", event)
        p = problem(_draft, s, "src2 bad clarification", at(2029, 3, 8, 17), clarification_close_at=at(2029, 3, 9, 9))
        assert p.code == "INVALID_CLARIFICATION_DEADLINE"


# ================================================================ R2 refused attempts are logged
def test_src2_late_uninvited_ineligible_and_early_attempts_are_logged():
    with rolled_back(at(2029, 3, 1)) as s:
        event = _draft(s, "src2 refusals", at(2029, 3, 8, 17))
        sourcing.publish(s, event)
        sla = act(s, "sla.sales")
        assert problem(sourcing.submit_bid, s, event, s.get(Supplier, sla.supplier_id), [BID]).code == "NOT_INVITED"
        act(s, "category.head")
        assert problem(sourcing.bids_view, s, event).code == "BIDS_SEALED"
        tf = act(s, "tf.sales")
        supplier(s, "TF001").status = "BLOCKED"
        assert problem(sourcing.submit_bid, s, event, s.get(Supplier, tf.supplier_id), [BID]).rule_ref == "P06/SRC-INVITE"
        supplier(s, "TF001").status = "ACTIVE"
        clock.set_pinned(at(2029, 3, 8, 17, 1))
        assert problem(sourcing.submit_bid, s, event, s.get(Supplier, tf.supplier_id), [BID]).code == "EVENT_CLOSED"
        actions = {a.action for a in s.execute(select(AuditEvent).where(AuditEvent.object_id == event.id)).scalars()}
        assert {"UNINVITED_BID_REFUSED", "BID_ACCESS_DENIED", "INELIGIBLE_BID_REFUSED", "LATE_BID_REFUSED"} <= actions


# ================================================================ R3-R5 bid input validation
def test_src2_bid_lines_refuse_nonfinite_implausible_and_inconsistent_values():
    with rolled_back(at(2029, 3, 1)) as s:
        event = _draft(s, "src2 bid validation", at(2029, 3, 8, 17))
        sourcing.publish(s, event)
        tf = s.get(Supplier, act(s, "tf.sales").supplier_id)
        bad = {
            "NaN price": {"unit_price": "NaN"}, "infinite price": {"unit_price": "Infinity"}, "decimal-point slip": {"unit_price": "40000"},
            "absurd price": {"unit_price": "1e15"}, "negative freight": {"freight": "-1"}, "absurd lead time": {"lead_time_days": 100000},
            "unknown currency": {"currency": "XXX"}, "no rate for the currency": {"currency": "GBP"}, "unknown incoterm": {"incoterm": "ABC"},
            "MOQ above capacity": {"moq": "9000"}, "tax included without a rate": {"tax_included": True}, "bad HS code": {"hs_code": "ab"},
            "zero factor": {"uom_factor": "0"},
        }
        for label, patch in bad.items():
            p = problem(sourcing.submit_bid, s, event, tf, [{**BID, **patch}])
            assert p.status == 422 and p.code == "INVALID_BID_LINES", (label, p.detail)
        # one currency per bid; offers valid beyond the close only
        s.add(FxRate(tenant_id=tf.tenant_id, from_ccy="USD", to_ccy="INR", rate=Decimal("83.5"), valid_from=date(2029, 1, 1), source="test"))
        s.flush()
        assert problem(sourcing.submit_bid, s, event, tf, [{**BID, "currency": "USD", "unit_price": "4.8"}, {**BID, "line": 20}]).code == "INVALID_BID_LINES"
        assert problem(sourcing.submit_bid, s, event, tf, [BID], valid_until=date(2029, 3, 7)).code == "INVALID_BID_VALIDITY"
        assert sourcing.submit_bid(s, event, tf, [{**BID, "currency": "USD", "unit_price": "4.8"}], valid_until=date(2029, 5, 31)).status == "SEALED"


def test_src2_prices_round_half_up_when_the_bid_is_opened():
    with rolled_back(at(2029, 3, 1)) as s:
        event = _draft(s, "src2 rounding", at(2029, 3, 8, 17))
        sourcing.publish(s, event)
        _bid(s, "tf.sales", event, unit_price="398.456")   # truncation gave 39845 paise
        _bid(s, "kd.sales", event, unit_price="398.454")
        _close(s, event, at(2029, 3, 8, 17, 5))
        prices = {m["supplier"]: m["priceMinor"] for m in sourcing.evaluation_matrix(s, event)}
        assert prices == {"TF001": 39846, "KD002": 39845}


# ================================================================ R6-R8 the TCO engine
def test_src2_missing_tco_inputs_are_flagged_never_silently_zero():
    with rolled_back(at(2029, 3, 1)) as s:
        event = _draft(s, "src2 tco missing", at(2029, 3, 8, 17))
        sourcing.publish(s, event)
        twin = s.execute(select(TwinSnapshot).where(TwinSnapshot.supplier_id == supplier(s, "KD002").id, TwinSnapshot.category == "ALU-DIECAST")).scalar_one()
        twin.ppm = None                                       # the twin has no PPM for KD002 ...
        s.execute(Scorecard.__table__.delete().where(Scorecard.supplier_id == twin.supplier_id))   # ... and neither has a scorecard
        s.flush()
        _bid(s, "tf.sales", event)
        _bid(s, "kd.sales", event, unit_price="405")
        _close(s, event, at(2029, 3, 8, 17, 5))
        rows = {m["supplier"]: m for m in sourcing.evaluation_matrix(s, event)}
        assert rows["KD002"]["tcoIncomplete"] is True and rows["KD002"]["tcoMissing"] == ["quality"] and rows["TF001"]["tcoIncomplete"] is False
        trace = {t["component"]: t for t in s.execute(select(BidLine).join(Bid, Bid.id == BidLine.bid_id).where(
            Bid.supplier_id == twin.supplier_id, Bid.event_id == event.id)).scalar_one().tco_trace if "status" in t}
        assert trace["quality"]["status"] == "MISSING" and trace["price"]["status"] == "BID" and trace["paymentTermValue"]["status"] == "BID"
        # with a scorecard the PPM comes from it (the mean of the last periods) and the stack is complete again
        s.add(Scorecard(tenant_id=twin.tenant_id, supplier_id=twin.supplier_id, period="2029-01", ppm=Decimal("600"), otif_pct=Decimal("97"),
                        invoice_accuracy_pct=Decimal("99"), receipts=10))
        s.flush()
        result = sourcing_tco.compute(s, params=sourcing_tco.snapshot(s), supplier_id=twin.supplier_id, category="ALU-DIECAST", price_minor=40500,
                                      lead_time_days=10, payment_terms_days=45)
        assert result["incomplete"] is False and {t["component"]: t for t in result["trace"]}["quality"]["status"] == "SCORECARD"
        # the rule can also refuse the line instead of flagging it
        policy(s, _key=sourcing_defaults.TCO_KEY, missingInput="REJECT", ppmFromScorecardPeriods=0)
        s.execute(Scorecard.__table__.delete().where(Scorecard.supplier_id == twin.supplier_id))
        s.flush()
        with pytest.raises(sourcing_tco.TcoInputError, match="quality"):
            sourcing_tco.compute(s, params=sourcing_tco.snapshot(s), supplier_id=twin.supplier_id, category="ALU-DIECAST", price_minor=40500,
                                 lead_time_days=10, payment_terms_days=45)


def test_src2_tco_stack_always_adds_up_to_the_total():
    with rolled_back(at(2029, 3, 1)) as s:
        act(s, "category.head")
        tf = supplier(s, "TF001")
        params = sourcing_tco.snapshot(s)
        rnd = random.Random(7)
        for _ in range(200):
            price = rnd.randint(1000, 90000)
            r = sourcing_tco.compute(s, params=params, supplier_id=tf.id, category="ALU-DIECAST", price_minor=price,
                                     price_exact=Decimal(price) + Decimal(rnd.randint(0, 99)) / 100, lead_time_days=rnd.randint(0, 120),
                                     payment_terms_days=rnd.randint(0, 120), freight=Decimal(rnd.randint(0, 900)) / 100,
                                     packaging=Decimal(rnd.randint(0, 300)) / 100, annual_qty=Decimal(rnd.randint(1000, 10 ** 6)),
                                     material=material(s, "DC-330"))
            assert sum(r["parts"].values()) + r["rounding"] == r["totalMinor"] and abs(r["rounding"]) <= 4


def test_src2_tco_components_follow_the_rule_set():
    """Freight by incoterm, duty from the HS rate table, GST stripped, carrying over lead time plus safety stock, payment value, each in the trace."""
    with rolled_back(at(2029, 3, 1)) as s:
        act(s, "category.head")
        policy(s, _key=sourcing_defaults.TCO_KEY, dutyRates={"8708": "7.5", "87089900": "10"}, freightEstimatePct={"EXW": "4"})
        params = sourcing_tco.snapshot(s)
        tf = supplier(s, "TF001")
        dc = material(s, "DC-330")
        base = dict(params=params, supplier_id=tf.id, category="ALU-DIECAST", price_minor=40000, lead_time_days=10, payment_terms_days=60)
        exw = sourcing_tco.compute(s, **base, incoterm="EXW")
        by = {t["component"]: t for t in exw["trace"] if "status" in t}
        assert exw["parts"]["freight"] == 1600 and by["freight"]["status"] == "ESTIMATED"
        dap = sourcing_tco.compute(s, **base, incoterm="DAP")
        assert dap["parts"]["freight"] == 0 and {t["component"]: t for t in dap["trace"] if "status" in t}["freight"]["status"] == "INCLUDED"
        quoted = sourcing_tco.compute(s, **base, incoterm="EXW", freight=Decimal("2.5"))
        assert quoted["parts"]["freight"] == 250
        # import duty: longest HS prefix wins, on price + freight; a missing rate is MISSING, not zero
        imp = sourcing_tco.compute(s, **base, incoterm="EXW", origin="IMPORT", hs_code="87089900")
        assert imp["parts"]["duty"] == round((40000 + 1600) * 0.10) and imp["incomplete"] is False
        short = sourcing_tco.compute(s, **base, origin="IMPORT", hs_code="870899")
        assert short["parts"]["duty"] == round(40000 * 0.075)
        none = sourcing_tco.compute(s, **base, origin="IMPORT", hs_code="123456")
        assert none["incomplete"] is True and none["missing"] == ["duty"]
        # carrying: pipeline days plus the days the safety stock lasts
        plain = sourcing_tco.compute(s, **base)
        safe = sourcing_tco.compute(s, **base, material=dc, annual_qty=Decimal("365"))     # 200 safety stock at 1 per day = 200 days, capped at 90
        assert safe["parts"]["carrying"] > plain["parts"]["carrying"]
        assert safe["parts"]["carrying"] == round(40000 * 0.18 * (10 + 90) / 365)
        # legacy events (made before the rule set) keep the original carrying formula and numbers
        legacy = {"carrying_rate_pct": "18", "cost_of_capital_pct": "12", "copq_per_defect_minor": 500000}
        old = sourcing_tco.compute(s, **{**base, "params": legacy}, material=dc, annual_qty=Decimal("365"))
        assert old["parts"]["carrying"] == plain["parts"]["carrying"]
        # normalisation: currency at the reference date, unit factor, GST stripped
        s.add(FxRate(tenant_id=tf.tenant_id, from_ccy="USD", to_ccy="INR", rate=Decimal("80"), valid_from=date(2029, 1, 1), source="test"))
        s.add(FxRate(tenant_id=tf.tenant_id, from_ccy="USD", to_ccy="INR", rate=Decimal("90"), valid_from=date(2029, 4, 1), source="test"))
        s.flush()
        n = sourcing_tco.normalise_price(s, {"unit_price": "6", "currency": "USD", "uom_factor": "2", "tax_included": True, "tax_rate_pct": "18"},
                                         date(2029, 3, 15), sourcing_tco.effective(params))
        assert n["fxRate"] == Decimal(80) and n["minor"] == round(6 * 100 * 80 / 2 / 1.18)
        assert [x["step"] for x in n["steps"]] == ["CURRENCY", "UNIT", "TAX_STRIPPED"]
        later = sourcing_tco.normalise_price(s, {"unit_price": "6", "currency": "USD"}, date(2029, 4, 2), sourcing_tco.effective(params))
        assert later["fxRate"] == Decimal(90)                       # the rate valid on the pricing date, not the latest one
        with pytest.raises(sourcing_tco.TcoInputError, match="no exchange rate"):
            sourcing_tco.normalise_price(s, {"unit_price": "6", "currency": "JPY"}, date(2029, 3, 15), sourcing_tco.effective(params))


def test_src2_partial_tco_parameters_do_not_break_the_close():
    """A TCO override without every rate used to raise KeyError inside the close and silently invalidate every bid; the rule fills what is missing."""
    with rolled_back(at(2029, 3, 1)) as s:
        event = _draft(s, "src2 partial tco", at(2029, 3, 8, 17), tco_params={"carrying_rate_pct": "20"})
        assert event.tco_params["carryingRatePct"] == "20" and event.tco_params["costOfCapitalPct"] == "12" and event.tco_params["_v"] == 2
        assert problem(_draft, s, "src2 unknown tco", at(2029, 3, 8, 17), tco_params={"no_such_rate": 1}).code == "INVALID_TCO_PARAMS"
        sourcing.publish(s, event)
        _bid(s, "tf.sales", event)
        result = _close(s, event, at(2029, 3, 8, 17, 5))
        assert result["unsealed"] == 1 and result["matrix"][0]["tcoMinor"] > 0


# ================================================================ R7 ranking, ties, scoring methods
def test_src2_equal_total_cost_is_ranked_by_score_then_time_then_code():
    with rolled_back(at(2029, 3, 1)) as s:
        event = _scored_event(s)
        # make the two bids cost the same: identical total cost, quality decides
        for bl in s.execute(select(BidLine).join(Bid, Bid.id == BidLine.bid_id).where(Bid.event_id == event.id)).scalars():
            bl.tco_minor = 41000
        s.flush()
        _score_all(s, event, tf=60, kd=90)
        rows = sourcing.evaluation_matrix(s, event)
        assert [r["supplier"] for r in rows] == ["KD002", "TF001"] and rows[1]["tiedWithPrevious"] is True and [r["rank"] for r in rows] == [1, 2]
        # same score too: the earlier bid wins, and the order does not depend on how rows are read
        _score_all(s, event, tf=70, kd=70)
        after = sourcing.evaluation_matrix(s, event)
        assert len({r["submittedAt"] for r in after}) == 1             # both bids carry the pinned clock's time: the supplier code decides, ascending
        assert [r["supplier"] for r in after] == ["KD002", "TF001"]


def test_src2_price_scores_by_method_and_the_event_stores_its_method():
    assert [round(float(x), 2) for x in sourcing.price_scores("LOWEST_RATIO", [100, 125, 200])] == [100.0, 80.0, 50.0]
    assert [round(float(x), 2) for x in sourcing.price_scores("MIN_MAX", [100, 125, 200])] == [100.0, 75.0, 0.0]
    assert [float(x) for x in sourcing.price_scores("MIN_MAX", [100, 100])] == [100.0, 100.0]
    assert [round(float(x), 2) for x in sourcing.price_scores("RANK", [100, 125, 200])] == [100.0, 66.67, 33.33]
    assert sourcing.price_scores("RANK", []) == []
    with rolled_back(at(2029, 3, 1)) as s:
        assert problem(_draft, s, "src2 method", at(2029, 3, 8, 17), scoring_method="BEST_GUESS").code == "INVALID_SCORING_METHOD"
        event = _draft(s, "src2 min max", at(2029, 3, 8, 17), scoring_method="min_max")
        sourcing.publish(s, event)
        _bid(s, "tf.sales", event)
        _bid(s, "kd.sales", event, unit_price="420")
        _close(s, event, at(2029, 3, 8, 17, 5))
        rows = {r["supplier"]: r for r in sourcing.evaluation_matrix(s, event)}
        assert rows["TF001"]["priceScore"] == "100.00" and rows["KD002"]["priceScore"] == "0.00"


# ================================================================ R10 / R13 scoring and conflict of interest
def test_src2_scores_are_numbers_from_0_to_100_and_evaluators_declare_first():
    with rolled_back(at(2029, 3, 1)) as s:
        event = _scored_event(s)
        act(s, "quality.engineer")
        entry = {"supplier": "TF001", "criterion": "QUALITY"}
        p = problem(sourcing.score, s, event, [{**entry, "score": 80}])
        assert p.code == "DECLARATION_REQUIRED" and p.status == 422
        for bad in (150, -1, "NaN", "Infinity", "abc"):
            assert problem(sourcing.score, s, event, [{**entry, "score": bad}]).code == "INVALID_SCORE", bad
        assert problem(sourcing.declare_conflict, s, event, False, "no").code == "DECLARATION_REQUIRED"
        sourcing.declare_conflict(s, event, False, "No personal or financial interest in any bidder.")
        assert sourcing.score(s, event, [{**entry, "score": 80}])["event"] == event.number
        # a declared conflict bars scoring, cannot be withdrawn, and bars the award proposal
        act(s, "category.manager")
        sourcing.declare_conflict(s, event, True, "My brother-in-law is a director of Kovai Diecast.")
        p = problem(sourcing.score, s, event, [{**entry, "score": 80}])
        assert p.code == "EVALUATOR_CONFLICT" and p.status == 403
        assert problem(sourcing.declare_conflict, s, event, False, "On reflection there is no conflict at all.").code == "CONFLICT_STANDS"
        scenarios = _scenarios_as(s, event, "category.head")
        act(s, "category.head")
        sourcing.declare_conflict(s, event, True, "I own shares in Trichy Forge, declared late.")
        p = problem(sourcing.propose_award, s, event, uuid.UUID(scenarios["LOWEST_COST"]["id"]), "x" * 30, "Conflict declared")
        assert p.code == "EVALUATOR_CONFLICT"


def _scenarios_as(s, event, who):
    act(s, who)
    return {x["kind"]: x for x in sourcing.build_scenarios(s, event)}


# ================================================================ R11 technical gate and disqualification
def test_src2_technical_gate_and_disqualification_keep_a_bidder_out_of_the_award():
    with rolled_back(at(2029, 3, 1)) as s:
        event = _scored_event(s, "src2 gate")
        crit = s.execute(select(Criterion).where(Criterion.event_id == event.id, Criterion.code == "QUALITY")).scalar_one()
        crit.min_score = Decimal("60")              # (an event defines the gate when it is created: criteria[].min_score)
        s.flush()
        _score_all(s, event, tf=80, kd=40)          # KD002 scores 40 on quality, below the gate of 60
        rows = {r["supplier"]: r for r in sourcing.evaluation_matrix(s, event)}
        assert rows["KD002"]["technicalGate"]["passed"] is False and rows["KD002"]["technicalGate"]["failed"] == ["QUALITY"]
        scenarios = _scenarios(s, event)
        assert all("KD002" not in {a["supplier"] for a in sc["allocations"]} for sc in scenarios.values())
        # an unscored gate criterion blocks the award; disqualification is a separate, written decision
        p = problem(sourcing.disqualify, s, event, supplier(s, "KD002"), "too short")
        assert p.code == "REASON_REQUIRED"
        sourcing.disqualify(s, event, supplier(s, "KD002"), "Failed the PPAP sample: the casting porosity is above the drawing limit.")
        assert [r["supplier"] for r in sourcing.evaluation_matrix(s, event)] == ["TF001"]
        stale = problem(sourcing.propose_award, s, event, uuid.UUID(scenarios["LOWEST_COST"]["id"]), None, "No conflict")
        assert stale.rule_ref == "SRC-AWARD"             # the scenario built before the disqualification is stale
        assert [a.action for a in _audit(s, event, "BID_DISQUALIFIED")] == ["BID_DISQUALIFIED"]
        assert any(e.topic == "sourcing.bid.disqualified" for e in s.execute(select(OutboxEvent).where(OutboxEvent.object_id == event.id)).scalars())
        # the disqualified supplier cannot come back in a negotiation round
        sourcing.new_round(s, event, at(2029, 3, 12, 17), "improve price")
        kd = act(s, "kd.sales")
        assert problem(sourcing.submit_bid, s, event, s.get(Supplier, kd.supplier_id), [BID]).code == "DISQUALIFIED"


# ================================================================ R12 / R15 award controls
def test_src2_award_needs_every_criterion_scored_and_a_real_rationale_for_exceptions():
    with rolled_back(at(2029, 3, 1)) as s:
        event = _scored_event(s)
        scenarios = _scenarios(s, event)
        lowest = uuid.UUID(scenarios["LOWEST_COST"]["id"])
        p = problem(sourcing.propose_award, s, event, lowest, None, "No conflict")
        assert p.code == "UNSCORED_CRITERIA" and "QUALITY" in p.detail          # an unscored criterion used to count as 0 without a word
        _score_all(s, event)
        scenarios = _scenarios(s, event)
        # best value is TF001 (cheaper and better), so give the award to KD002 through a manual split: not the lowest bid
        custom = sourcing.custom_scenario(s, event, [{"supplier": "KD002", "share_pct": "100"}])
        assert custom["feasible"] is True
        p = problem(sourcing.propose_award, s, event, uuid.UUID(custom["id"]), None, "No conflict")
        assert p.rule_ref == "SRC-RATIONALE" and p.extra["exceptions"][0]["code"] == "NOT_LOWEST"
        p = problem(sourcing.propose_award, s, event, uuid.UUID(custom["id"]), "cheaper", "No conflict")
        assert p.rule_ref == "SRC-RATIONALE" and "characters" in p.detail
        decision = sourcing.propose_award(s, event, uuid.UUID(custom["id"]), "Kovai Diecast has the better delivery record on this part and offered an extra tool.", "No conflict")
        assert event.status == "AWARD_PENDING"          # a non-lowest award always goes to the approvers
        assert [e["code"] for e in decision.exceptions] == ["NOT_LOWEST"] or "NOT_LOWEST" in [e["code"] for e in decision.exceptions]
        assert decision.authority["chain"][0] == "CATEGORY_MANAGER" and decision.authority["valueMinor"] == decision.annual_value_minor


def test_src2_limited_competition_and_negative_savings_need_a_rationale():
    with rolled_back(at(2029, 3, 1)) as s:
        policy(s, minBidders=3)
        event = _draft(s, "src2 limited", at(2029, 3, 8, 17), baseline_price_minor=30000)     # the baseline is below every bid: the award costs more
        sourcing.publish(s, event)
        _bid(s, "tf.sales", event)
        _bid(s, "kd.sales", event, unit_price="405")
        result = _close(s, event, at(2029, 3, 8, 17, 5))
        assert result["competitive"] is False and event.competitive is False and event.min_bidders == 3
        scenarios = _scenarios(s, event)
        p = problem(sourcing.propose_award, s, event, uuid.UUID(scenarios["LOWEST_COST"]["id"]), None, "No conflict")
        assert p.rule_ref == "SRC-RATIONALE"
        codes = {e["code"] for e in p.extra["exceptions"]}
        assert {"LIMITED_COMPETITION", "NEGATIVE_SAVINGS"} <= codes
        decision = sourcing.propose_award(s, event, uuid.UUID(scenarios["LOWEST_COST"]["id"]),
                                          "Only two qualified foundries bid; the baseline is the old 2027 price and the metal index has risen since.", "No conflict")
        assert {e["code"] for e in decision.exceptions} >= {"LIMITED_COMPETITION", "NEGATIVE_SAVINGS"} and event.status == "AWARD_PENDING"


def test_src2_incomplete_tco_and_unverified_capacity_are_award_exceptions():
    with rolled_back(at(2029, 3, 1)) as s:
        policy(s, incompleteTcoNeedsRationale=True, unverifiedCapacityNeedsRationale=True)
        event = _draft(s, "src2 exceptions", at(2029, 3, 8, 17))
        sourcing.publish(s, event)
        twin = s.execute(select(TwinSnapshot).where(TwinSnapshot.supplier_id == supplier(s, "TF001").id, TwinSnapshot.category == "ALU-DIECAST")).scalar_one()
        s.delete(twin)                                        # nothing verifies TF001's capacity or its quality: no twin, no scorecard
        s.execute(Scorecard.__table__.delete().where(Scorecard.supplier_id == twin.supplier_id))
        s.flush()
        _bid(s, "tf.sales", event, capacity_per_month=None)
        _bid(s, "kd.sales", event, unit_price="405")
        _close(s, event, at(2029, 3, 8, 17, 5))
        scenarios = _scenarios(s, event)
        assert scenarios["LOWEST_COST"]["allocations"][0]["supplier"] == "TF001" and scenarios["LOWEST_COST"]["allocations"][0]["capacityVerified"] is False
        p = problem(sourcing.propose_award, s, event, uuid.UUID(scenarios["LOWEST_COST"]["id"]), None, "No conflict")
        assert p.rule_ref == "SRC-RATIONALE" and {"INCOMPLETE_TCO", "UNVERIFIED_CAPACITY"} <= {e["code"] for e in p.extra["exceptions"]}
        # the policy can refuse unverified capacity outright: the scenario is then infeasible
        policy(s, unverifiedCapacity="BLOCK", incompleteTcoNeedsRationale=True, unverifiedCapacityNeedsRationale=True)
        blocked = _scenarios(s, event)
        assert blocked["LOWEST_COST"]["feasible"] is False and blocked["CAPACITY_CONSTRAINED"]["feasible"] is True \
            and blocked["CAPACITY_CONSTRAINED"]["allocations"][0]["supplier"] == "KD002"


def test_src2_savings_summary_has_a_sign_and_a_cost_increase_is_not_booked_as_saving():
    assert should_cost.savings_summary(41000, 40000, Decimal(20000), "LAST_PRICE") == {
        "method": "LAST_PRICE", "baselineMinor": 41000, "priceMinor": 40000, "annualSavingsMinor": 20_000_000, "savingsPct": "2.44", "sign": "SAVING"}
    inc = should_cost.savings_summary(40000, 41000, Decimal(100), "BUDGET")
    assert inc["sign"] == "COST_INCREASE" and inc["annualSavingsMinor"] == -100_000 and inc["savingsPct"] == "-2.50"
    assert should_cost.savings_summary(None, 100, Decimal(1))["sign"] == "NO_BASELINE" and should_cost.savings_summary(100, 100, Decimal(1))["sign"] == "NEUTRAL"
    with rolled_back(at(2029, 3, 1)) as s:
        event = _draft(s, "src2 cost increase", at(2029, 3, 8, 17), baseline_price_minor=40000)
        s.add(SavingsInitiative(tenant_id=event.tenant_id, number=f"SAV-S2-{uuid.uuid4().hex[:6]}", title=event.title, category=event.category, source_event_id=event.id,
                                owner_id=event.owner_id, stage="IDENTIFIED", baseline_method="BUDGET", baseline_price_minor=40000, annual_volume=Decimal(1)))
        s.flush()
        payload = {"weightedPriceMinor": 41000, "annualQty": "100", "baselineMethod": "BUDGET", "allocations": [{"supplierId": str(uuid.uuid4()), "priceMinor": 41000}]}
        savings._negotiated(s, SimpleNamespace(object_id=event.id, object_ref=event.number, payload=payload))
        entry = s.execute(select(SavingsLedgerEntry).join(SavingsInitiative, SavingsInitiative.id == SavingsLedgerEntry.initiative_id).where(
            SavingsInitiative.source_event_id == event.id)).scalar_one()
        assert entry.amount_minor == 0 and "cost increase" in entry.formula and "BUDGET" in entry.formula
        assert any((a.after or {}).get("costIncreaseMinor") == 100_000 for a in s.execute(select(AuditEvent).where(AuditEvent.action == "NEGOTIATE")).scalars())


def test_src2_sod_05_the_sole_evaluator_cannot_propose_the_award():
    """SOD-05 had no test: the owner who scored alone is refused, a second evaluator lifts the block."""
    with rolled_back(at(2029, 3, 1)) as s:
        event = _scored_event(s)
        _declare(s, event, "category.head")
        act(s, "category.head")
        sourcing.score(s, event, [{"supplier": "TF001", "criterion": "QUALITY", "score": 80}, {"supplier": "KD002", "criterion": "QUALITY", "score": 70}])
        scenarios = _scenarios(s, event)
        p = problem(sourcing.propose_award, s, event, uuid.UUID(scenarios["LOWEST_COST"]["id"]), None, "No conflict")
        assert p.status == 409 and p.code == "SOD_CONFLICT" and p.rule_ref == "SOD-05"
        _declare(s, event, "quality.engineer")
        act(s, "quality.engineer")
        sourcing.score(s, event, [{"supplier": "TF001", "criterion": "QUALITY", "score": 82}])
        act(s, "category.head")
        assert sourcing.propose_award(s, event, uuid.UUID(scenarios["LOWEST_COST"]["id"]), None, "No conflict").status in ("PENDING", "APPROVED")


# ================================================================ R14 manual splits
def test_src2_manual_split_must_add_up_and_respects_capacity_moq_and_share_bounds():
    with rolled_back(at(2029, 3, 1)) as s:
        event = _draft(s, "src2 split", at(2029, 3, 8, 17), constraints={"max_suppliers": 2, "max_share": "0.7", "min_share": "0.2"})
        sourcing.publish(s, event)
        _bid(s, "tf.sales", event, capacity_per_month="1000", moq="300")
        _bid(s, "kd.sales", event, unit_price="405", capacity_per_month="3000")
        _close(s, event, at(2029, 3, 8, 17, 5))
        act(s, "category.head")
        # 99.9 and 100.1 are not 100: refused (the rounding trap), also as quantities
        assert problem(sourcing.custom_scenario, s, event, [{"supplier": "TF001", "share_pct": "49.9"}, {"supplier": "KD002", "share_pct": "50"}]).code == "INVALID_SPLIT"
        assert problem(sourcing.custom_scenario, s, event, [{"supplier": "TF001", "share_pct": "50.1"}, {"supplier": "KD002", "share_pct": "50"}]).code == "INVALID_SPLIT"
        assert problem(sourcing.custom_scenario, s, event, [{"supplier": "TF001", "qty_per_month": "900"}, {"supplier": "KD002", "qty_per_month": "1000"}]).code == "INVALID_SPLIT"
        assert problem(sourcing.custom_scenario, s, event, [{"supplier": "TF001", "share_pct": "50", "qty_per_month": "1000"}, {"supplier": "KD002", "share_pct": "50"}]).code == "INVALID_SPLIT"
        assert problem(sourcing.custom_scenario, s, event, [{"supplier": "SLA003", "share_pct": "100"}]).code == "INVALID_SPLIT"
        # exactly 100: stored; capacity, MOQ and bounds are checked and listed
        ok = sourcing.custom_scenario(s, event, [{"supplier": "TF001", "qty_per_month": "1100"}, {"supplier": "KD002", "qty_per_month": "900"}])
        assert ok["feasible"] is False and any("verified capacity" in v for v in ok["explanation"]["violations"])      # TF001 is verified to 1000/month
        moq = sourcing.custom_scenario(s, event, [{"supplier": "TF001", "qty_per_month": "200"}, {"supplier": "KD002", "qty_per_month": "1800"}])
        assert any("minimum order" in v for v in moq["explanation"]["violations"])
        bounds = sourcing.custom_scenario(s, event, [{"supplier": "KD002", "share_pct": "100"}])
        assert bounds["feasible"] is False and any("maximum share" in v for v in bounds["explanation"]["violations"])      # 100 % is above the event's 70 % cap
        good = sourcing.custom_scenario(s, event, [{"supplier": "TF001", "share_pct": "30"}, {"supplier": "KD002", "share_pct": "70"}])
        assert good["feasible"] is True and Decimal(good["weightedPriceMinor"]) == Decimal("40000") * Decimal("0.3") + Decimal("40500") * Decimal("0.7")
        # an infeasible scenario can never be awarded
        _declare(s, event, "quality.engineer")
        act(s, "category.head")
        assert problem(sourcing.propose_award, s, event, uuid.UUID(ok["id"]), "x" * 30, "No conflict").rule_ref == "SRC-AWARD"


# ================================================================ R9 the optimiser
def test_src2_equal_thirds_of_capacity_are_feasible_and_moq_is_respected():
    q = Decimal(90000)
    rows = [{"supplier": f"S{i}", "supplierId": f"id{i}", "priceMinor": 40000 + i, "tcoMinor": 41000 + i * 10, "verifiedCapacityPerMonth": "30000"} for i in range(3)]
    best = sourcing._optimise(rows, q, {"max_suppliers": 3, "max_share": "1", "min_share": "0"})
    assert best is not None and sum(s for _, s in best["allocations"]) == 1       # 3 x (30000 / 90000) used to leave 1e-28 over: "infeasible"; now exactly 1
    # MOQ: a selected supplier must get at least its minimum order quantity
    moq_rows = [{**rows[0], "moq": "40000"}, {**rows[1], "verifiedCapacityPerMonth": "90000", "tcoMinor": 42000}]
    split = sourcing._optimise(moq_rows, q, {"max_suppliers": 2, "max_share": "1", "min_share": "0.1"})
    shares = {r["supplier"]: s for r, s in split["allocations"]}
    assert shares.get("S0", 0) == 0 or shares["S0"] * q >= 40000
    # unverified capacity: assumed enough unless the policy blocks it
    unverified = [{**rows[0], "verifiedCapacityPerMonth": None}]
    assert sourcing._optimise(unverified, q, {"max_suppliers": 1, "max_share": "1"}) is not None
    assert sourcing._optimise(unverified, q, {"max_suppliers": 1, "max_share": "1", "_block_unverified": True}) is None


def test_src2_optimiser_matches_brute_force_on_small_cases():
    """The allocation is exact: for random small instances (shares on a 5 % grid so every vertex of the LP is on the grid) the optimiser's cost equals
    the cheapest allocation found by enumerating every share vector, and it is infeasible exactly when the enumeration finds nothing."""
    rnd = random.Random(20261104)
    steps, q = 20, Decimal(20)
    checked = infeasible = 0
    for _ in range(160):
        n = rnd.randint(2, 4)
        max_k = rnd.randint(1, n)
        min_share = Decimal(rnd.choice([0, 0, 1, 2, 4])) / steps
        max_share = Decimal(rnd.choice([10, 12, 14, 20, 20])) / steps
        rows = [{"supplier": f"S{i}", "supplierId": f"id{i}", "priceMinor": 100, "tcoMinor": rnd.randint(90, 130) * 100,
                 "verifiedCapacityPerMonth": str(rnd.choice([4, 6, 8, 10, 14, 20, 20])),
                 "moq": rnd.choice(["2", "4"]) if rnd.random() < 0.3 else None} for i in range(n)]
        constraints = {"max_suppliers": max_k, "max_share": str(max_share), "min_share": str(min_share)}
        got = sourcing._optimise(rows, q, constraints)
        best = None
        for combo in itertools.product(range(steps + 1), repeat=n):
            if sum(combo) != steps:
                continue
            chosen = [i for i, v in enumerate(combo) if v > 0]
            if len(chosen) > max_k:
                continue
            ok = True
            for i in chosen:
                share = Decimal(combo[i]) / steps
                lower = max(min_share if len(chosen) > 1 else Decimal(1), Decimal(rows[i]["moq"]) / q if rows[i]["moq"] else Decimal(0))
                upper = min(max_share, Decimal(rows[i]["verifiedCapacityPerMonth"]) / q)
                if share < lower or share > upper:
                    ok = False
                    break
            if ok:
                cost = sum(Decimal(combo[i]) / steps * rows[i]["tcoMinor"] for i in chosen)
                best = cost if best is None or cost < best else best
        assert (got is None) == (best is None), (rows, constraints)
        if got is not None:
            assert Decimal(got["cost"]) == best, (rows, constraints, got, best)
            checked += 1
        else:
            infeasible += 1
    assert checked > 60 and infeasible > 5


# ================================================================ two-person opening, withdrawal, scheduled opening
def test_src2_two_person_bid_opening_keeps_bids_sealed_until_two_people_open_them():
    with rolled_back(at(2029, 3, 1)) as s:
        event = _draft(s, "src2 opening", at(2029, 3, 8, 17), constraints={**OPEN_SHARES, "two_person_opening": True})
        sourcing.publish(s, event)
        _bid(s, "tf.sales", event)
        _bid(s, "kd.sales", event, unit_price="405")
        result = _close(s, event, at(2029, 3, 8, 17, 5))
        assert result["awaitingOpening"] is True and event.status == "CLOSED" and event.unsealed_at is None
        assert problem(sourcing.bids_view, s, event).code == "BIDS_SEALED"          # early access: blocked and logged
        assert problem(sourcing_analysis.comparison, s, event).code == "BIDS_SEALED"
        assert problem(sourcing_analysis.export_csv, s, event).code == "BIDS_SEALED"
        assert problem(sourcing.score, s, event, []).status == 409                    # not under evaluation yet
        assert len(_audit(s, event, "BID_ACCESS_DENIED")) >= 3
        act(s, "category.head")
        first = sourcing.open_bids(s, event)
        assert first["openers"] == 1 and first["remaining"] == 1 and event.status == "CLOSED"
        assert problem(sourcing.open_bids, s, event).code == "ALREADY_OPENED_BY_YOU"      # the same person cannot be both openers
        act(s, "category.manager")
        second = sourcing.open_bids(s, event)
        assert second["unsealed"] == 2 and event.status == "UNDER_EVALUATION" and event.competitive is True
        opened = _audit(s, event, "BIDS_UNSEALED")[0]
        assert len(opened.after["openers"]) == 2 and opened.reason == "two-person opening"
        assert any(e.topic == "sourcing.bids.unsealed" for e in s.execute(select(OutboxEvent).where(OutboxEvent.object_id == event.id)).scalars())
        assert problem(sourcing.open_bids, s, event).status == 409                    # already open


def test_src2_a_supplier_can_replace_and_withdraw_a_sealed_bid_until_the_close():
    with rolled_back(at(2029, 3, 1)) as s:
        event = _draft(s, "src2 withdraw", at(2029, 3, 8, 17))
        sourcing.publish(s, event)
        first = _bid(s, "tf.sales", event)
        again = _bid(s, "tf.sales", event, unit_price="395")
        assert again.id == first.id and again.edits == 1 and len(_audit(s, event, "BID_REPLACED")) == 1
        tf = s.get(Supplier, act(s, "tf.sales").supplier_id)
        assert problem(sourcing.withdraw_bid, s, event, tf, "x").code == "REASON_REQUIRED"
        withdrawn = sourcing.withdraw_bid(s, event, tf, "We cannot hold this price after the aluminium increase.")
        assert withdrawn.status == "WITHDRAWN" and withdrawn.sealed_payload is None
        assert problem(sourcing.withdraw_bid, s, event, tf, "Withdrawing twice makes no sense").code == "NO_BID_TO_WITHDRAW"
        _bid(s, "kd.sales", event, unit_price="405")
        _bid(s, "tf.sales", event, unit_price="399")              # a withdrawn bid can be submitted again
        result = _close(s, event, at(2029, 3, 8, 17, 5))
        assert result["unsealed"] == 2 and {m["supplier"]: m["priceMinor"] for m in result["matrix"]} == {"TF001": 39900, "KD002": 40500}
        # a bid withdrawn and not re-submitted is never opened or ranked
        event2 = _draft(s, "src2 withdraw 2", at(2029, 3, 9, 17))
        sourcing.publish(s, event2)
        _bid(s, "tf.sales", event2)
        sourcing.withdraw_bid(s, event2, tf, "Capacity is committed to another customer.")
        _bid(s, "kd.sales", event2, unit_price="405")
        result = _close(s, event2, at(2029, 3, 9, 17, 5))
        assert [m["supplier"] for m in result["matrix"]] == ["KD002"] and result["unsealed"] == 1


def test_src2_scheduled_opening_makes_published_a_resting_state():
    with rolled_back(at(2029, 3, 1)) as s:
        event = _draft(s, "src2 scheduled", at(2029, 3, 20, 17), open_at=at(2029, 3, 10, 9))
        sourcing.publish(s, event)
        assert event.status == "PUBLISHED"
        tf = s.get(Supplier, act(s, "tf.sales").supplier_id)
        assert problem(sourcing.submit_bid, s, event, tf, [BID]).code == "ILLEGAL_TRANSITION"      # not open for bids yet
        question = auction.ask(s, event, "Is the drawing revision C the current one?")             # but suppliers may ask
        assert question.status == "OPEN"
        timer = s.execute(select(Timer).where(Timer.object_id == event.id, Timer.kind == "SOURCING_OPEN")).scalars().all()
        assert len(timer) == 1
        clock.set_pinned(at(2029, 3, 10, 9, 1))
        timer[0].fired_at = clock.now()
        workflow._timer_handlers["SOURCING_OPEN"](s, timer[0])
        assert event.status == "OPEN" and sourcing.submit_bid(s, event, tf, [BID]).status == "SEALED"
        assert problem(_draft, s, "src2 auction open_at", at(2029, 3, 20, 17), type="REVERSE_AUCTION", open_at=at(2029, 3, 10, 9)).code == "INVALID_OPEN_AT"


# ================================================================ lifecycle checks
def test_src2_publish_guards_budget_fields_open_hours_and_need_date():
    with rolled_back(at(2029, 3, 1)) as s:
        # an event whose requirement has no need date cannot be published as an RFQ (mandatory field of the type), an RFI can
        pr = _requirement(s, [("DC-330", 1200)])
        s.execute(select(PrLine).where(PrLine.requisition_id == pr.id)).scalar_one().need_date = date(2029, 3, 20)
        act(s, "category.head")
        line = {"requisition": pr.number, "line": 10, "annual_qty": "1200", "monthly_qty": "100"}
        event = _draft(s, "src2 need date", at(2029, 3, 25, 17), lines=[line])
        p = problem(sourcing.publish, s, event)
        assert p.rule_ref == "SRC-NEEDDATE"                       # bids close after the need date and the need date is still ahead
        event.close_at = at(2029, 3, 10, 17)
        event.need_date = None
        assert problem(sourcing.publish, s, event).code == "MANDATORY_FIELDS"
        event.need_date = date(2029, 3, 20)
        policy(s, minOpenHours={"RFQ": 240})
        assert problem(sourcing.publish, s, event).rule_ref == "SRC-OPEN-HOURS"
        policy(s, minOpenHours={"RFQ": 24}, clarificationCloseHours=48)
        assert sourcing.publish(s, event).status == "OPEN"
        assert event.clarification_close_at == at(2029, 3, 8, 17) and event.purpose_code == "STOCK_REPLENISHMENT"
        assert _audit(s, event, "PUBLISH_CHECKED")[0].after["budget"] in ("NOT_APPLICABLE", "OK")
        # clarification questions close before the bids do
        act(s, "tf.sales")
        clock.set_pinned(at(2029, 3, 9, 10))
        assert problem(auction.ask, s, event, "Can the casting be delivered unmachined?").code == "CLARIFICATION_WINDOW_CLOSED"


def test_src2_category_budget_hard_and_soft_stop_with_justification():
    with rolled_back(at(2029, 3, 1)) as s:
        year = clock.fiscal_year(clock.today())
        act(s, "category.head")
        s.add(CategoryPlan(tenant_id=s.info["principal"].tenant_id, number="CP-S2-1", category="ALU-DIECAST", fiscal_year=year, spend_minor=1, profit_impact=Decimal(5),
                           supply_risk=Decimal(5), kraljic="LEVERAGE", budget_minor=1_000_000, owner_id=s.info["principal"].user_id, status="APPROVED"))
        s.flush()
        event = _draft(s, "src2 budget", at(2029, 3, 8, 17), baseline_price_minor=42000)       # 20,000 units x 420 = 84 lakh above a 10,000 budget
        p = problem(sourcing.publish, s, event)
        assert p.code == "BUDGET_JUSTIFICATION_REQUIRED" and p.extra["budget"]["outcome"] == "EXCEEDED"
        event.budget_justification = "Volume doubled after the new platform award; the category head accepts the overrun."
        assert sourcing.publish(s, event).status == "OPEN" and event.budget_check["outcome"] == "EXCEEDED_JUSTIFIED"
        hard = _draft(s, "src2 budget hard", at(2029, 3, 8, 17), baseline_price_minor=42000)
        policy(s, budgetCheck="HARD")
        assert problem(sourcing.publish, s, hard).code == "CATEGORY_BUDGET_EXCEEDED"


def test_src2_event_definition_checks():
    with rolled_back(at(2029, 3, 1)) as s:
        assert problem(_draft, s, "src2 dup invitee", at(2029, 3, 8, 17), invitees=("TF001", "TF001")).code == "DUPLICATE_INVITEE"
        assert problem(_draft, s, "src2 dup criteria", at(2029, 3, 8, 17), criteria=[*PRICE_ONLY, {"code": "PRICE_TCO", "name": "again", "weight": 0}]).code == "INVALID_CRITERION"
        assert problem(_draft, s, "src2 neg weight", at(2029, 3, 8, 17), criteria=[{"code": "PRICE_TCO", "name": "p", "weight": -5}]).code == "INVALID_CRITERION"
        assert problem(_draft, s, "src2 float weight", at(2029, 3, 8, 17), criteria=[{"code": "PRICE_TCO", "name": "p", "weight": "99.9"}]).code == "INVALID_CRITERION"
        assert problem(_draft, s, "src2 gate on price", at(2029, 3, 8, 17), criteria=[{"code": "PRICE_TCO", "name": "p", "weight": 100, "min_score": 50}]).code == "INVALID_CRITERION"
        assert problem(_draft, s, "x" * 201, at(2029, 3, 8, 17)).code == "INVALID_EVENT"
        assert problem(_draft, s, "src2 type", at(2029, 3, 8, 17), type="RFX").code == "INVALID_EVENT_TYPE"
        assert problem(_draft, s, "src2 baseline", at(2029, 3, 8, 17), baseline_method="GUESS").code == "INVALID_BASELINE_METHOD"
        # weights that do not add up: 99.9 / 100.1 cannot even be entered; 99 and 101 are refused at publish
        for weights in ((60, 39), (60, 41)):
            event = _draft(s, f"src2 weights {sum(weights)}", at(2029, 3, 8, 17),
                           criteria=[{"code": "PRICE_TCO", "name": "p", "weight": weights[0]}, {"code": "QUALITY", "name": "q", "weight": weights[1]}])
            assert problem(sourcing.publish, s, event).rule_ref == "SRC-WEIGHTS"
        # an RFQ is awarded on price
        event = _draft(s, "src2 no price", at(2029, 3, 8, 17), criteria=[{"code": "QUALITY", "name": "q", "weight": 100}])
        assert problem(sourcing.publish, s, event).rule_ref == "SRC-CRITERIA"
        # a requirement of another category is audited for a single line and refused for a bundle or under the ENFORCE policy
        line_category = s.execute(select(PrLine.category).join(Requisition, Requisition.id == PrLine.requisition_id).where(
            Requisition.number == "REQ-2312", PrLine.line_no == 10)).scalar_one()
        if line_category != "ALU-DIECAST":                       # the shared test requirement is another category: audited by default, refused when the policy says ENFORCE
            audited = _draft(s, "src2 category warn", at(2029, 3, 8, 17))
            assert "categoryMismatch" in _audit(s, audited, "CREATED")[0].after
            policy(s, lineCategoryCheck="ENFORCE")
            assert problem(_draft, s, "src2 category", at(2029, 3, 8, 17)).rule_ref == "SRC-BUNDLE"


def test_src2_state_machine_refuses_illegal_commands_with_409():
    with rolled_back(at(2029, 3, 1)) as s:
        event = _scored_event(s)
        act(s, "category.head")
        assert problem(sourcing.publish, s, event).status == 409                             # already published and closed
        clock.set_pinned(at(2029, 3, 8, 17, 6))
        assert problem(sourcing.close, s, event).status == 409                               # closed twice
        tf = act(s, "tf.sales")
        assert problem(sourcing.submit_bid, s, event, s.get(Supplier, tf.supplier_id), [BID]).code == "ILLEGAL_TRANSITION"      # no bid after the close
        act(s, "category.head")
        assert problem(sourcing.disqualify, s, _draft(s, "src2 draft", at(2029, 3, 20, 17)), supplier(s, "TF001"), "Long enough reason text.").status == 409
        _score_all(s, event)
        scenarios = _scenarios(s, event)
        sourcing.propose_award(s, event, uuid.UUID(scenarios["BEST_VALUE"]["id"]), None, "No conflict")
        assert event.status == "AWARD_PENDING"                                                       # 80 lakh a year: above the 50 lakh threshold
        assert problem(sourcing.new_round, s, event, at(2029, 3, 30, 17)).status == 409              # an event with a pending award is not re-opened
        assert problem(sourcing.build_scenarios, s, event).status == 409
        sourcing.cancel(s, event, "Requirement withdrawn by the plant head.")
        assert event.status == "CANCELLED"
        assert problem(sourcing.cancel, s, event, "Cancelled twice.").status == 409


# ================================================================ the auction
def test_src2_auction_soft_close_stops_extending_after_the_cap_and_refuses_implausible_prices():
    with rolled_back(at(2029, 3, 1)) as s:
        policy(s, maxExtensions=2)
        event = _draft(s, "src2 auction", at(2029, 3, 8, 12), type="REVERSE_AUCTION", baseline_price_minor=42000)
        auction.configure(s, event, {"minDecrementPct": "0.5", "extensionMinutes": 5, "triggerMinutes": 2, "ceilingMinor": 45000})
        sourcing.publish(s, event)
        tf, kd = s.get(Supplier, act(s, "tf.sales").supplier_id), s.get(Supplier, act(s, "kd.sales").supplier_id)
        clock.set_pinned(at(2029, 3, 8, 10))
        assert problem(auction.place_bid, s, event, tf, 46000).rule_ref == "AUCTION-CEILING"          # above the ceiling
        assert problem(auction.place_bid, s, event, tf, 100).code == "IMPLAUSIBLE_PRICE"              # a decimal-point slip
        assert problem(auction.place_bid, s, event, tf, 900_000_000_000).code == "IMPLAUSIBLE_PRICE"
        price = 44000
        ends = []
        for step in range(6):
            bidder = tf if step % 2 == 0 else kd
            clock.set_pinned(auction.ends_at(event) - timedelta(minutes=1))
            price -= 400
            auction.place_bid(s, event, bidder, price)
            ends.append(auction.ends_at(event))
        extended = [b.extended_close for b in auction._bids(s, event)]
        assert sum(extended) == 2 and extended[:2] == [True, True] and len(set(ends[1:])) == 1          # two extensions, then the end is final
        assert len(_audit(s, event, "AUCTION_EXTENDED")) == 2


# ================================================================ should-cost and benchmarks
def test_src2_should_cost_inputs_are_validated_and_models_follow_an_index():
    params = {"net_weight_kg": "1.2", "alloy_rate_per_kg": "215", "cycle_time_min": "3.5", "machine_rate_per_min": "18", "tooling_amortisation": "12",
              "packaging": "7", "overhead_margin_pct": "15"}
    assert sourcing.should_cost(params)["unitCostMinor"] == 39100                     # the signature case's 391.00
    for patch, text in (({"overhead_margin_pct": "-5"}, "zero or positive"), ({"overhead_margin_pct": "150"}, "between 0 and 100"),
                        ({"net_weight_kg": "abc"}, "not a number"), ({"net_weight_kg": "-1"}, "zero or positive"), ({"cycle_time_min": "NaN"}, "zero or positive")):
        p = problem(sourcing.should_cost, {**params, **patch})
        assert p.status == 422 and p.code == "SHOULDCOST_INVALID" and text in p.detail, (patch, p.detail)
    assert problem(sourcing.should_cost, {k: v for k, v in params.items() if k != "alloy_rate_per_kg"}).code == "SHOULDCOST_INVALID"     # was a KeyError (500)
    spec = {"unit": "EA", "inputs": [{"code": "kg"}, {"code": "rate"}, {"code": "minutes"}, {"code": "machine"}, {"code": "margin"}],
            "components": [{"code": "MATERIAL", "type": "QTY_RATE", "qty": "kg", "rate": "rate", "yieldLossPct": "5", "index": {"code": "LME_AL", "baseDate": "2029-01-02"}},
                           {"code": "CONVERSION", "type": "TIME_RATE", "minutes": "minutes", "rate": "machine"},
                           {"code": "LOGISTICS", "type": "PCT_OF", "of": ["MATERIAL", "CONVERSION"], "pct": "2"}, {"code": "TOOLING", "type": "FIXED", "amount": "10"}],
            "marginPct": "margin"}
    assert should_cost.validate_spec(spec) == []
    assert should_cost.validate_spec({**spec, "components": [{"code": "X", "type": "MAGIC"}]})
    with rolled_back(at(2029, 3, 1)) as s:
        act(s, "category.head")
        tid = s.info["principal"].tenant_id
        for day, value in ((date(2029, 1, 2), "200"), (date(2029, 3, 1), "230")):
            s.add(IndexValue(tenant_id=tid, index_code="LME_AL", as_of=day, value=Decimal(value), unit="USD/t", source="MANUAL"))
        s.flush()
        model = should_cost.save_model(s, code="DIECAST-T", commodity="ALU-DIECAST", title="Die-cast test model", spec=spec, index_code="LME_AL")
        assert model.version == 1 and should_cost.save_model(s, code="DIECAST-T", commodity="ALU-DIECAST", title="v2", spec=spec).version == 2
        inputs = {"kg": "1.2", "rate": "100", "minutes": "3", "machine": "20", "margin": "10"}
        out = should_cost.evaluate(s, "DIECAST-T", inputs, on=date(2029, 3, 5))
        material_cost = Decimal("1.2") * Decimal("1.05") * 100 * Decimal(230) / Decimal(200)       # the rate follows the index: 230 / 200
        conversion = Decimal(60)
        subtotal = material_cost + conversion + (material_cost + conversion) * Decimal("0.02") + 10
        assert out["unitCostMinor"] == int((subtotal * Decimal("1.10")).quantize(Decimal("0.01")) * 100) and out["indexLinks"][0]["factor"] == "1.150000"
        assert out["model"] == "DIECAST-T@2" and {c["component"] for c in out["components"]} == {"MATERIAL", "CONVERSION", "LOGISTICS", "TOOLING"}
        assert problem(should_cost.evaluate, s, "DIECAST-T", inputs, date(2028, 1, 1)).code == "SHOULDCOST_INVALID"          # no index value that early
        assert problem(should_cost.evaluate, s, "DIECAST-T", {**inputs, "margin": "-3"}, date(2029, 3, 5)).code == "SHOULDCOST_INVALID"


def test_src2_baseline_methods_and_benchmark_band():
    with rolled_back(at(2029, 3, 1)) as s:
        act(s, "category.head")
        dc = material(s, "DC-331")
        tid = s.info["principal"].tenant_id
        assert should_cost.baseline_price(s, "BUDGET", material=dc, plant="P100", category="ALU-DIECAST")["source"] == "GIVEN_BY_BUYER"
        assert should_cost.baseline_price(s, "SHOULD_COST", material=dc, plant="P100", category="ALU-DIECAST", should_cost_minor=39100)["priceMinor"] == 39100
        assert should_cost.baseline_price(s, "MARKET_INDEX", material=dc, plant="P100", category="ALU-DIECAST", on=date(2029, 3, 1))["source"] == "NO_DATA"
        s.add(PriceBenchmark(tenant_id=tid, category="ALU-DIECAST", material_id=dc.id, kind="MARKET", as_of=date(2029, 2, 1), price_minor=39500, uom="EA", source="test index"))
        s.add(PriceBenchmark(tenant_id=tid, category="ALU-DIECAST", material_id=None, kind="PEER", as_of=date(2029, 2, 1), price_minor=41500, uom="EA", source="peer club"))
        s.flush()
        assert should_cost.baseline_price(s, "MARKET_INDEX", material=dc, plant="P100", category="ALU-DIECAST", on=date(2029, 3, 1))["priceMinor"] == 39500
        # weighted average of the last twelve months of orders (quantity-weighted): the signature orders split 60 / 40 between 398 and 405
        weighted = should_cost.baseline_price(s, "WEIGHTED_AVG", material=material(s, "DC-330"), plant="P100", category="ALU-DIECAST", on=date(2027, 3, 1))
        assert weighted["source"] == "PO_LINES" and 39800 <= weighted["priceMinor"] <= 40500
        assert should_cost.baseline_price(s, "WEIGHTED_AVG", material=material(s, "DC-330"), plant="P100", category="ALU-DIECAST", on=date(2029, 3, 1))["source"] == "NO_DATA"
        band = should_cost.benchmark_band(s, dc, "ALU-DIECAST", date(2029, 3, 1), should_cost_minor=39100)
        assert {"market", "peer", "shouldCost"} <= set(band["points"]) and band["highMinor"] >= 41500
        assert band["lowMinor"] == min(p["priceMinor"] for p in band["points"].values()) and band["lowMinor"] <= 39100


# ================================================================ comparison, screens, export
def test_src2_comparison_and_csv_export_only_after_the_bids_are_opened_and_are_audited():
    with rolled_back(at(2029, 3, 1)) as s:
        event = _draft(s, "src2 export", at(2029, 3, 8, 17))
        sourcing.publish(s, event)
        _bid(s, "tf.sales", event)
        _bid(s, "kd.sales", event, unit_price="405", freight="2.5")
        act(s, "category.head")
        assert problem(sourcing_analysis.comparison, s, event).code == "BIDS_SEALED"
        assert problem(sourcing_analysis.export_csv, s, event).code == "BIDS_SEALED"
        _close(s, event, at(2029, 3, 8, 17, 5))
        out = sourcing_analysis.comparison(s, event)
        assert [b["supplier"] for b in out["bids"]] == ["TF001", "KD002"] and out["validBidders"] == 2 and out["competitive"] is True
        assert out["bids"][0]["lines"][0]["tco"]["price"] == 40000 and out["screens"]["notChecked"]
        exported = sourcing_analysis.export_csv(s, event)
        rows = exported["content"].strip().split("\n")
        assert rows[0].startswith("event,round,rank,supplier") and len(rows) == 3 and exported["rows"] == 2
        import hashlib
        assert hashlib.sha256(exported["content"].encode()).hexdigest() == exported["sha256"]
        audit_row = _audit(s, event, "COMPARISON_EXPORTED")[0]
        assert audit_row.after["sha256"] == exported["sha256"] and audit_row.after["rows"] == 2
        again = sourcing_analysis.export_csv(s, event)
        assert again["sha256"] == exported["sha256"]                      # the same data gives the same file


def test_src2_outlier_and_collusion_screens_use_only_data_pic_holds():
    pol = sourcing_defaults.POLICY_DEFAULT
    flags = sourcing_analysis.detect_outliers({"A": 100_00, "B": 105_00, "C": 110_00, "D": 55_00}, 100_00, pol)
    assert {(f["supplier"], f["flag"]) for f in flags} >= {("D", "LOW_VS_MEDIAN"), ("D", "LOW_VS_SHOULD_COST")}
    assert not [f for f in sourcing_analysis.detect_outliers({"A": 100, "B": 101, "C": 102}, None, pol)]
    assert sourcing_analysis.detect_outliers({"A": 100, "B": 10}, None, pol) == []           # below the minimum number of bids: no statistics on two bids
    rows = [{"supplier": "A", "tcoMinor": 5000, "lines": [{"line": 10, "priceMinor": 1000}, {"line": 20, "priceMinor": 2000}]},
            {"supplier": "B", "tcoMinor": 5000, "lines": [{"line": 10, "priceMinor": 1100}, {"line": 20, "priceMinor": 2200}]},
            {"supplier": "C", "tcoMinor": 6100, "lines": [{"line": 10, "priceMinor": 1000}, {"line": 20, "priceMinor": 2500}]}]
    with rolled_back(at(2029, 3, 1)) as s:
        act(s, "category.head")
        event = SimpleNamespace()
        hints = sourcing_analysis.collusion_hints(s, event, [{**r, "supplier": c} for r, c in zip(rows, ("TF001", "KD002", "SLA003"))], pol)
        kinds = {h["hint"] for h in hints}
        assert {"IDENTICAL_TOTALS", "LINE_PATTERN"} <= kinds
        a, b = supplier(s, "TF001"), supplier(s, "KD002")
        b.pan_hash, a.pan_hash = "same-pan-hash", "same-pan-hash"
        b.contact_email = a.contact_email = "bids@same.example"
        s.flush()
        hints = sourcing_analysis.collusion_hints(s, event, [{**r, "supplier": c} for r, c in zip(rows, ("TF001", "KD002", "SLA003"))], pol)
        assert {"SHARED_PAN", "SHARED_CONTACT_EMAIL"} <= {h["hint"] for h in hints}


# ================================================================ hand-off, regret letters, KPIs, templates
def test_src2_the_signature_award_reads_back_with_its_hand_off_and_authority():
    with tenant_tx(_tid()) as s:
        act(s, "category.head")
        event = s.execute(select(SourcingEvent).where(SourcingEvent.title == SIGNATURE_EVENT)).scalar_one()
        out = sourcing_analysis.handoff(s, event)
        assert out["status"] == "AWARDED" and {c["supplier"] for c in out["contracts"]} == {"TF001", "KD002"} and out["decisions"][0]["status"] == "APPROVED"
        assert out["quotaArrangements"] and sorted(x["sharePct"] for x in out["quotaArrangements"][0]["suppliers"]) == ["40.00", "60.00"]
        assert {e["supplier"] for e in out["sourceListEntries"]} >= {"TF001", "KD002"} and {e["material"] for e in out["sourceListEntries"]} == {"DC-330"}
        assert all(c["poReleaseEligible"] for c in out["contracts"] if c["status"] in ("ACTIVE", "EXPIRING"))
        history = sourcing_analysis.history(s, event)
        assert {"CREATED", "PUBLISH", "AWARD", "AWARD_NOTIFIED"} <= {h["action"] for h in history} and len({h["hash"] for h in history}) == len(history)
        pipe = sourcing_analysis.pipeline(s)
        assert pipe["total"] >= 1 and {x["stage"] for x in pipe["stages"]} >= {"DRAFT", "OPEN", "AWARDED", "CANCELLED"}
        # the numbers of the signature case are what the Blueprint says
        matrix = sourcing.evaluation_matrix(s, event)
        assert {m["supplier"]: m["priceMinor"] for m in matrix} == {"TF001": 39800, "KD002": 40500, "SLA003": 40500}
        assert event.should_cost["unitCostMinor"] == 39100 and event.baseline_price_minor == 41000


def test_src2_award_sends_regret_letters_without_competitor_data_and_hand_off_follows():
    with rolled_back(at(2029, 3, 1)) as s:
        event = _draft(s, "src2 regret", at(2029, 3, 8, 17), invitees=("TF001", "KD002", "SLA003"),
                       lines=[{"requisition": "REQ-2312", "line": 10, "annual_qty": "10000", "monthly_qty": "1000"}])     # 40 lakh a year: below the approval threshold
        sourcing.publish(s, event)
        _bid(s, "tf.sales", event)
        _bid(s, "kd.sales", event, unit_price="405")
        _bid(s, "sla.sales", event, unit_price="410")
        _close(s, event, at(2029, 3, 8, 17, 5))
        scenarios = _scenarios(s, event)
        sourcing.propose_award(s, event, uuid.UUID(scenarios["LOWEST_COST"]["id"]), None, "No conflict")
        assert event.status == "AWARDED"
        topics = [(e.topic, e.payload) for e in s.execute(select(OutboxEvent).where(OutboxEvent.object_id == event.id).order_by(OutboxEvent.occurred_at)).scalars()]
        regrets = {p["supplier"]: p for t, p in topics if t == "sourcing.award.regret"}
        assert set(regrets) == {"KD002", "SLA003"} and regrets["KD002"]["rank"] == 2 and regrets["SLA003"]["rank"] == 3 and regrets["SLA003"]["bidders"] == 3
        assert all("TF001" not in json.dumps(p) and "398" not in json.dumps(p) for p in regrets.values())
        awarded = next(p for t, p in topics if t == "sourcing.event.awarded")
        assert awarded["baselineMethod"] == "BUDGET" and awarded["savings"]["sign"] == "SAVING" and awarded["scenario"] == "LOWEST_COST"
        decision = s.execute(select(AwardDecision).where(AwardDecision.event_id == event.id)).scalar_one()
        assert decision.regret_sent_at is not None


def test_src2_m05_kpis_are_defined_and_measure_what_their_names_say():
    assert kpi.REGISTRY["M05.COMPETITIVE_EVENTS"].compute is sourcing_kpi.m05_competitive and kpi.REGISTRY["M05.SOURCING_CYCLE"].compute is sourcing_kpi.m05_cycle
    assert {"M05.SUPPLIER_PARTICIPATION", "M05.AWARD_TO_CONTRACT", "M05.SAVINGS_LINK", "M05.NON_LOWEST_AWARDS"} <= set(kpi.REGISTRY)
    with tenant_tx(_tid()) as s:
        act(s, "category.head")
        values = {code: kpi.evaluate(s, kpi.REGISTRY[code]) for code in kpi.REGISTRY if code.startswith("M05.")}
        assert len(values) >= 8 and all("status" in v for v in values.values())
        cycle, competitive, bidders = values["M05.SOURCING_CYCLE"], values["M05.COMPETITIVE_EVENTS"], values["M05.BIDDERS_PER_EVENT"]
        assert cycle["value"] is not None and Decimal(str(cycle["value"])) > 0                         # publication to the approved award of the signature case
        assert competitive["denominator"] is not None and Decimal(str(competitive["numerator"])) <= Decimal(str(competitive["denominator"]))
        assert bidders["value"] is not None and Decimal(str(bidders["value"])) >= 2
        assert values["M05.SUPPLIER_PARTICIPATION"]["value"] is not None


def test_src2_templates_and_clones_keep_the_definition_and_report_dropped_invitees():
    with rolled_back(at(2029, 3, 1)) as s:
        event = _scored_event(s, "src2 original")
        act(s, "category.head")
        tpl = sourcing_templates.save(s, code="s2-diecast-rfq", name="Die-cast RFQ", event_type="RFQ", category="ALU-DIECAST", payload={
            "criteria": SCORED, "constraints": {"max_suppliers": 2, "max_share": "0.7", "min_share": "0.2"}, "scoring_method": "MIN_MAX",
            "invitee_filter": {"max": 2}, "min_bidders": 2})
        assert tpl.code == "S2-DIECAST-RFQ"
        assert problem(sourcing_templates.save, s, code="bad", name="bad", event_type="RFQ", category=None,
                       payload={"criteria": [{"code": "PRICE_TCO", "name": "p", "weight": 90}]}).code == "INVALID_TEMPLATE"
        assert problem(sourcing_templates.save, s, code="bad2", name="bad", event_type="RFQ", category=None, payload={"surprise": 1}).code == "INVALID_TEMPLATE"
        assert [t["code"] for t in sourcing_templates.listing(s, "ALU-DIECAST")].count("S2-DIECAST-RFQ") == 1
        line = {"requisition": "REQ-2312", "line": 10, "annual_qty": "20000", "monthly_qty": "2000"}
        built = sourcing_templates.create_from_template(s, "s2-diecast-rfq", title="src2 from template", category=None, lines=[line], close_at=at(2029, 4, 8, 17),
                                                        invitees=[{"supplier": "TF001"}, {"supplier": "KD002"}], baseline_price_minor=42000, baseline_method="BUDGET")
        assert built.template_code == "S2-DIECAST-RFQ" and built.scoring_method == "MIN_MAX" and built.min_bidders == 2 and built.status == "DRAFT"
        # the clone: same definition, link kept, an invitee that lost its qualification is dropped and reported
        s.execute(select(SupplierCategoryStatus).where(SupplierCategoryStatus.supplier_id == supplier(s, "KD002").id,
                                                       SupplierCategoryStatus.category == "ALU-DIECAST")).scalar_one().status = "BLOCKED"
        s.flush()
        sourcing.cancel(s, built, "Superseded by a re-run")
        done = sourcing_templates.clone(s, built, close_at=at(2029, 4, 20, 17))
        clone = s.execute(select(SourcingEvent).where(SourcingEvent.number == done["event"])).scalar_one()
        assert clone.cloned_from == built.number and clone.scoring_method == "MIN_MAX" and done["droppedInvitees"] == [{"supplier": "KD002", "status": "BLOCKED"}]
        assert done["invitees"] == ["TF001"] and any(a.after.get("clonedFrom") == built.number for a in _audit(s, clone, "CREATED"))
        del event


# ================================================================ API: ETag, supplier view, idempotency
def test_src2_api_etag_stale_write_supplier_view_and_sealed_comparison(client, login):
    head, tf = login("category.head"), login("tf.sales")
    r = client.get(f"/v1/sourcing/events/RFQ-2231", headers=head)
    assert r.status_code == 200 and r.headers["ETag"].startswith('"') and r.headers["ETag"].strip('"').isdigit()
    stale = client.post("/v1/sourcing/events/RFQ-2231/cancel", json={"reason": "stale view"}, headers={**head, "If-Match": '"0"'})
    assert stale.status_code == 412 and stale.json()["code"] == "STALE_WRITE"
    # the supplier sees the requirement and its own bid, none of the buyer's internals
    mine = client.get("/v1/sourcing/events/RFQ-2231", headers=tf).json()
    hidden = {"bundle", "budget_check", "budget_justification", "opening", "rule_versions", "min_bidders", "competitive", "baseline_method", "should_cost",
              "baseline_price_minor", "constraints", "tco_params", "scenarios", "awardDecisions", "savings_target_pct"}
    assert not hidden & set(mine) and [b["supplier"] for b in mine["bids"]] == ["TF001"]
    # a supplier cannot read the comparison or the export
    assert client.get("/v1/sourcing/events/RFQ-2231/comparison", headers=tf).status_code == 403
    assert client.get("/v1/sourcing/events/RFQ-2231/comparison.csv", headers=tf).status_code == 403
    cmp_ = client.get("/v1/sourcing/events/RFQ-2231/comparison", headers=head)
    assert cmp_.status_code == 200 and [b["supplier"] for b in cmp_.json()["bids"]][:1] == ["TF001"] and cmp_.json()["shouldCost"]["unitCostMinor"] == 39100
    assert client.post("/v1/sourcing/tco/simulate", headers=head, json={
        "supplier": "TF001", "category": "ALU-DIECAST", "material": "DC-330", "annual_qty": "1080000",
        "line": {"line": 10, "unit_price": "398", "payment_terms_days": 60, "lead_time_days": 12, "freight": "3", "packaging": "1"}}).json()["tcoMinor"] > 39800
    assert client.get("/v1/sourcing/pipeline", headers=head).json()["total"] >= 1
    assert client.get("/v1/sourcing/events/RFQ-2231/handoff", headers=head).json()["status"] == "AWARDED"
    assert "CREATED" in {h["action"] for h in client.get("/v1/sourcing/events/RFQ-2231/history", headers=head).json()}
    # create-event validation reaches the caller as 422 (and writes nothing)
    body = {"type": "RFQ", "title": "x", "category": "ALU-DIECAST", "lines": [], "criteria": [], "invitees": [], "close_at": "2031-03-01T10:00:00"}
    assert client.post("/v1/sourcing/events", json=body, headers=head).status_code == 422
    assert client.post("/v1/sourcing/events", json={**body, "lines": [{"requisition": "REQ-2312", "line": 10, "annual_qty": "1", "monthly_qty": "1"}],
                                                   "scoring_method": "GUESS"}, headers=head).status_code == 422
    assert client.post("/v1/sourcing/events/RFQ-2231/bids", json={"lines": [{"line": 10, "unit_price": "NaN", "payment_terms_days": 1, "lead_time_days": 1}]},
                       headers=tf).status_code == 422                   # refused by the request model before the event is looked at


# ================================================================ review of the combined tree: trace, template fields, policy, key mismatch
def test_src2_comparison_carries_the_tco_trace_of_every_bid_line(client, login):
    with rolled_back(at(2029, 3, 1)) as s:
        event = _draft(s, "src2 trace", at(2029, 3, 8, 17))
        sourcing.publish(s, event)
        _bid(s, "tf.sales", event, freight="2.5")
        _close(s, event, at(2029, 3, 8, 17, 5))
        out = sourcing_analysis.comparison(s, event)
        line = out["bids"][0]["lines"][0]
        trace = {t["component"]: t for t in line["tcoTrace"] if "status" in t}
        assert set(trace) == {"price", "freight", "duty", "packaging", "carrying", "quality", "paymentTermValue"}
        assert all({"valueMinor", "status", "formula", "inputs"} <= set(t) for t in trace.values())
        assert trace["freight"]["status"] == "BID" and trace["freight"]["inputs"]["quoted"] == "2.5" and out["bids"][0]["tcoTrace"] == line["tcoTrace"]
        assert any(t["component"] == "normalisation" for t in line["tcoTrace"])
    # the signature event (made by the seed with this release) carries it through the API too
    head = login("category.head")
    bids = client.get("/v1/sourcing/events/RFQ-2231/comparison", headers=head).json()["bids"]
    assert all({"price", "carrying", "quality", "paymentTermValue"} <= {t["component"] for t in b["lines"][0]["tcoTrace"]} for b in bids)


def test_src2_an_event_from_a_template_takes_the_schedule_budget_and_should_cost_fields():
    from app.pic.api.source_contract import FromTemplateIn
    assert {"open_at", "clarification_close_at", "reference_date", "min_bidders", "budget_justification", "should_cost_model"} <= set(FromTemplateIn.model_fields)
    spec = {"unit": "EA", "inputs": [{"code": "kg"}], "components": [{"code": "MATERIAL", "type": "QTY_RATE", "qty": "kg", "rate": "100"}], "marginPct": "10"}
    with rolled_back(at(2029, 3, 1)) as s:
        act(s, "category.head")
        sourcing_templates.save(s, code="s2-tpl-fields", name="Template fields", event_type="RFQ", category="ALU-DIECAST",
                                payload={"criteria": PRICE_ONLY, "constraints": OPEN_SHARES, "min_bidders": 2})
        should_cost.save_model(s, code="S2-SC", commodity="ALU-DIECAST", title="Template should-cost", spec=spec)
        line = {"requisition": "REQ-2312", "line": 10, "annual_qty": "20000", "monthly_qty": "2000"}
        common = dict(title="src2 template fields", category=None, lines=[line], close_at=at(2029, 3, 20, 17), invitees=[{"supplier": "TF001"}, {"supplier": "KD002"}],
                      baseline_price_minor=42000, baseline_method="BUDGET")
        event = sourcing_templates.create_from_template(
            s, "s2-tpl-fields", **common, open_at=at(2029, 3, 10, 9), clarification_close_at=at(2029, 3, 15, 12), reference_date=date(2029, 3, 5), min_bidders=3,
            budget_justification="Volume doubled after the platform award.", should_cost_model={"code": "S2-SC", "inputs": {"kg": "2"}})
        assert event.open_at == at(2029, 3, 10, 9) and event.clarification_close_at == at(2029, 3, 15, 12) and event.reference_date == date(2029, 3, 5)
        assert event.min_bidders == 3 and event.budget_justification.startswith("Volume doubled") and event.template_code == "S2-TPL-FIELDS"
        assert event.should_cost["unitCostMinor"] == 22000          # 2 kg x 100 x 1.10
        # validated like the normal create path
        assert problem(sourcing_templates.create_from_template, s, "s2-tpl-fields", **common, open_at=at(2029, 3, 25, 9)).code == "INVALID_OPEN_AT"
        assert problem(sourcing_templates.create_from_template, s, "s2-tpl-fields", **common, clarification_close_at=at(2029, 3, 25, 9)).code == "INVALID_CLARIFICATION_DEADLINE"
        assert problem(sourcing_templates.create_from_template, s, "s2-tpl-fields", **common, min_bidders=50).code == "INVALID_EVENT"
        assert problem(sourcing_templates.create_from_template, s, "s2-tpl-fields", **common, should_cost_model={"code": "NO-SUCH", "inputs": {}}).status == 404


def test_src2_the_event_view_carries_the_policy_values_but_not_for_suppliers(client, login):
    mine = client.get("/v1/sourcing/events/RFQ-2231", headers=login("category.head")).json()
    policy_ = mine["policy"]
    assert {"maxExtensions", "priceBand", "minRationaleChars", "minBidders", "twoPersonOpening", "requireAllCriteriaScored", "rule"} <= set(policy_)
    assert policy_["maxExtensions"] >= 1 and {"minVsBaseline", "maxVsBaseline", "maxUnitPriceMinor"} <= set(policy_["priceBand"]) and policy_["twoPersonOpeningForThisEvent"] in (True, False)
    assert "policy" not in client.get("/v1/sourcing/events/RFQ-2231", headers=login("tf.sales")).json()


def test_src2_sealed_bids_that_the_field_key_cannot_open_are_a_clear_503_audited_once(monkeypatch):
    from cryptography.fernet import InvalidToken

    def cannot_open(*args, **kwargs):
        raise InvalidToken()

    with rolled_back(at(2029, 3, 1)) as s:
        event = _draft(s, "src2 key mismatch", at(2029, 3, 8, 17))
        sourcing.publish(s, event)
        bid = _bid(s, "tf.sales", event)
        ciphertext = bytes(bid.sealed_payload).decode("latin-1")
        clock.set_pinned(at(2029, 3, 8, 17, 5))
        act(s, "category.head")
        monkeypatch.setattr(sourcing.crypto, "decrypt", cannot_open)
        for _ in range(2):
            p = problem(sourcing._unseal, s, event)
            assert p.status == 503 and p.code == "FIELD_KEY_MISMATCH" and "PIC_FIELD_KEY" in p.detail and ciphertext[:20] not in p.detail
        monkeypatch.undo()
        assert len(_audit(s, event, "FIELD_KEY_MISMATCH")) == 1                       # audited once, however often it is tried
        assert Bid.__table__ is not None and bid.status == "SEALED"                   # nothing was opened
