"""D17 strategic-sourcing datasets for AXN and KAC (pack sourcing_ops): MOCK events in every type and state, bids and TCO, awards and hand-offs, should-cost
models, indices, benchmarks, templates.

The tests assert properties (ranges, presence of every type, state and behaviour), never exact global counts: other modules of the suite share the database
and add their own rows. Events of the pack are found by their title ``MOCK K01`` ... ``MOCK K40`` (KAC) and ``MOCK A01`` ... (AXN). The signature case of AXN
(RFQ-2231 of the Axion seed) and every KAC contract, invoice, payment and stock row are hashed before the pack runs and must be byte-identical afterwards."""
import hashlib
import json
from collections import Counter
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuditEvent, AuctionBid, AwardDecision, AwardScenario, Bid, BidLine, Contract, ContractLine, EventLine, IndexValue, Invoice, Invitee, Notification,
    Payment, PriceBenchmark, PriceValidity, QuotaArrangement, QuotaLine, RuleSet, SavingsInitiative, SavingsLedgerEntry, ShouldCostModel, SourceList,
    SourcingClarification, SourcingEvent, SourcingTemplate, Stock, Tenant, Timer, TwinSnapshot,
)
from app.pic.platform import clock, rules
from app.pic.platform.audit import verify_chain
from app.pic.seed import datasets
from app.pic.seed.datasets import sourcing_ops as pack
from app.pic.tools import sourcing_mock as mock
from tests.pic.conftest import PASSWORD

# the KAC contract portfolio (KAC-*) and its lines; the pack adds contracts of its own (born from awards, default numbering) that are not part of it
KAC_CONTRACTS = {Contract: Contract.number.like("KAC-%"), ContractLine: ContractLine.contract_id.in_(select(Contract.id).where(Contract.number.like("KAC-%")))}
PREREQUISITES = ("erp_client_kac", "contracts_kac", "inventory_ops", "inventory_master", "finance_ops")


def row_hashes(session, models, where=None) -> dict:
    out = {}
    for model in models:
        query = select(model).order_by(model.id)
        if where is not None and model in where:
            query = query.where(where[model])
        for row in session.execute(query).scalars():
            values = {c.key: getattr(row, c.key) for c in model.__mapper__.column_attrs}
            out[(model.__tablename__, str(row.id))] = hashlib.sha256(json.dumps(values, default=str, sort_keys=True).encode()).hexdigest()
    return out


@pytest.fixture(scope="module")
def packs(database):
    for name in PREREQUISITES:
        assert {r["status"] for r in datasets.apply_pack(name, PASSWORD)} <= {"LOADED", "ALREADY_LOADED", "SKIPPED"}, name
    with system_tx() as s:
        ids = {code: tid for code, tid in s.execute(select(Tenant.code, Tenant.id))}
    # what exists before the pack: KAC contracts (KAC-*), invoices, payments and stock; AXN's signature case RFQ-2231 with its lines, bids, scenarios and decisions
    kac_models = (Invoice, Payment, Stock)
    with tenant_tx(ids["KAC"]) as s:
        kac_before = row_hashes(s, kac_models)
        kac_before.update(row_hashes(s, (Contract, ContractLine), where=KAC_CONTRACTS))
    with tenant_tx(ids["AXN"]) as s:
        signature = s.execute(select(SourcingEvent).where(SourcingEvent.title.like("DC-330 aluminium die-cast housing%"))).scalar_one()
        signature_id = signature.id
        axn_before = row_hashes(s, (SourcingEvent,), where={SourcingEvent: SourcingEvent.id == signature_id})
        for model in (EventLine, Bid, AwardScenario, AwardDecision):
            axn_before.update(row_hashes(s, (model,), where={model: model.event_id == signature_id}))
    results = {r["tenant"]: r for r in datasets.apply_pack("sourcing_ops", PASSWORD)}
    assert set(results) == {"AXN", "KAC"} and {r["status"] for r in results.values()} <= {"LOADED", "ALREADY_LOADED"}, results
    yield {"results": results, "ids": ids, "kac_before": kac_before, "kac_models": kac_models, "axn_before": axn_before, "signature_id": signature_id}
    clock.set_pinned(None)


def kac(packs):
    return packs["ids"]["KAC"]


def axn(packs):
    return packs["ids"]["AXN"]


def events(s, prefix: str) -> dict:
    return {e.title.split(" ")[1]: e for e in s.execute(select(SourcingEvent).where(SourcingEvent.title.like(f"MOCK {prefix}%"))).scalars()}


def audit_actions(s, ids=None) -> Counter:
    query = select(AuditEvent.action).where(AuditEvent.object_type == "SOURCING_EVENT")
    if ids is not None:
        query = query.where(AuditEvent.object_id.in_(ids))
    return Counter(a for (a,) in s.execute(query))


# ================================================================ idempotency and determinism
def test_a_second_run_writes_nothing(packs):
    assert {r["tenant"]: r["status"] for r in datasets.apply_pack("sourcing_ops", PASSWORD)} == {"AXN": "ALREADY_LOADED", "KAC": "ALREADY_LOADED"}

    def counts(tenant_id):
        with tenant_tx(tenant_id) as s:
            return {m.__tablename__: s.execute(select(func.count()).select_from(m)).scalar_one()
                    for m in (AuditEvent, SourcingEvent, Bid, BidLine, AwardDecision, Contract, AppUser, RuleSet, TwinSnapshot, IndexValue, PriceBenchmark, ShouldCostModel,
                              SourcingTemplate, SavingsInitiative, Notification)}
    for code in ("AXN", "KAC"):
        before = counts(packs["ids"][code])
        summary = pack.apply(code, PASSWORD)             # a direct second run: every stage is recorded, so no service is called
        assert summary["serviceCalls"] == 0 and summary["stepsSkipped"] > 40, summary
        assert counts(packs["ids"][code]) == before, code


def test_the_generator_is_deterministic_and_the_committed_files_match_the_manifest():
    assert mock.verify_files() == []
    assert mock.files() == mock.files()
    plan = mock.kac_plan()
    assert len(plan) == 40 and len({r["key"] for r in plan}) == 40
    assert mock.index_value("COPPER_LME", date(2025, 4, 1)) == mock.index_value("COPPER_LME", date(2025, 4, 1)) and len(mock.index_series()) == 190
    assert mock.bid_terms("K01|10", "100014", 10000) == mock.bid_terms("K01|10", "100014", 10000)


def test_database_matches_the_plan_when_the_pack_is_loaded(packs):
    assert mock.verify_database("KAC") == [] and mock.verify_database("AXN") == []


# ================================================================ KAC: events, types, states
def test_kac_has_forty_events_of_every_type_and_every_state(packs):
    with tenant_tx(kac(packs)) as s:
        found = events(s, "K")
    assert len(found) == 40
    types = Counter(e.type for e in found.values())
    states = Counter(e.status for e in found.values())
    assert types["RFI"] >= 3 and types["RFQ"] >= 25 and types["RFP"] >= 5 and types["REVERSE_AUCTION"] >= 3, types
    for state in ("DRAFT", "PUBLISHED", "OPEN", "CLOSED", "UNDER_EVALUATION", "AWARD_PENDING", "AWARDED", "CANCELLED"):
        assert states[state] >= 2, (state, states)
    assert states["AWARDED"] >= 15
    for key, row in ((r["key"], r) for r in mock.kac_plan()):
        assert found[key].status == row["state"] and found[key].type == row["type"] and found[key].category == row["category"], key
    created = [e.created_at.astimezone(clock.IST).date() for e in found.values()]
    assert min(created) == date(2025, 4, 14) and max(created) <= date(2026, 10, 31)
    assert any(e.round == 2 for e in found.values()) and sum(1 for e in found.values() if e.round == 2) >= 2     # multi-round
    assert sum(1 for e in found.values() if e.opening) >= 3                                                      # two-person opening


def test_lot_bidding_published_scheduled_opening_and_baseline_methods(packs):
    with tenant_tx(kac(packs)) as s:
        found = events(s, "K")
        lot_events = {e.id for e in found.values() if s.execute(select(func.count()).select_from(EventLine).where(EventLine.event_id == e.id, EventLine.lot_code.is_not(None))).scalar_one() >= 2}
        published = [e for e in found.values() if e.status == "PUBLISHED"]
        methods = Counter(e.baseline_method for e in found.values())
        bundles = [e for e in found.values() if e.bundle]
    assert len(lot_events) >= 2
    # a scheduled opening: after publication and before the close (the pack's dates are fixed, so "after today" would expire with the calendar)
    assert len(published) == 2 and all(e.open_at is not None and e.published_at is not None and e.published_at < e.open_at < e.close_at for e in published)
    for method in ("LAST_PRICE", "WEIGHTED_AVG", "SHOULD_COST", "MARKET_INDEX", "BUDGET"):
        assert methods[method] >= 1, (method, methods)
    assert len(bundles) >= 2


def test_bids_are_realistic_sealed_where_open_and_carry_a_tco_trace(packs):
    with tenant_tx(kac(packs)) as s:
        found = events(s, "K")
        per_event = {k: s.execute(select(func.count(func.distinct(Bid.supplier_id))).where(Bid.event_id == e.id, Bid.status.in_(("UNSEALED", "SUPERSEDED", "DISQUALIFIED")))).scalar_one()
                     for k, e in found.items() if e.status in ("AWARDED", "AWARD_PENDING", "UNDER_EVALUATION")}
        sealed = {k: s.execute(select(func.count()).select_from(Bid).where(Bid.event_id == e.id, Bid.status == "SEALED")).scalar_one()
                  for k, e in found.items() if e.status in ("OPEN", "CLOSED")}
        lines = list(s.execute(select(BidLine).join(Bid, Bid.id == BidLine.bid_id).join(SourcingEvent, SourcingEvent.id == Bid.event_id)
                               .where(SourcingEvent.title.like("MOCK K%"))).scalars())
    bidder_counts = [n for k, n in per_event.items() if found[k].type != "RFI"]
    assert min(bidder_counts) >= 2 and max(bidder_counts) <= 7 and sum(1 for n in bidder_counts if n >= 4) >= 8, per_event
    assert sum(sealed.values()) >= 8 and all(found[k].unsealed_at is None for k in sealed), sealed            # open and waiting-for-opening events keep their bids sealed
    assert lines and all(l.tco_trace and l.tco_minor > 0 for l in lines)
    assert any(l.currency == "USD" and l.fx_rate and l.price_quoted_minor for l in lines)                      # a foreign-currency bid converted at the event's reference date
    assert any(l.incoterm == "EXW" and any(t.get("component") == "freight" and t.get("status") == "ESTIMATED" for t in l.tco_trace) for l in lines)
    assert any(l.tco_incomplete for l in lines)                                                               # an import line with no duty rate: flagged, not zero-filled
    assert all(abs(l.unit_price_minor - l.price_quoted_minor * l.fx_rate) <= 50 for l in lines if l.currency == "USD")


def test_every_required_behaviour_is_in_the_audit_trail(packs):
    with tenant_tx(kac(packs)) as s:
        ids = [e.id for e in events(s, "K").values()]
        actions = audit_actions(s, ids)
        late = s.execute(select(AuditEvent).where(AuditEvent.action == "LATE_BID_REFUSED", AuditEvent.object_id.in_(ids))).scalars().all()
        denied = s.execute(select(AuditEvent).where(AuditEvent.action == "BID_ACCESS_DENIED", AuditEvent.object_id.in_(ids))).scalars().all()
    for action in ("BID_SUBMITTED", "BID_REPLACED", "BID_WITHDRAWN", "LATE_BID_REFUSED", "UNINVITED_BID_REFUSED", "BID_ACCESS_DENIED", "BID_DISQUALIFIED",
                   "BIDS_UNSEALED", "AWAITING_OPENING", "BIDS_OPEN_WITNESS", "EVALUATOR_DECLARED", "SCORED", "SCENARIO_CUSTOM", "PROPOSE_AWARD", "AWARD",
                   "AWARD_NOTIFIED", "CLARIFICATION_ASKED", "CLARIFICATION_ANSWERED", "NOTICE_PUBLISHED", "NEW_ROUND", "AUCTION_BID", "AUCTION_EXTENDED",
                   "AUCTION_CLOSED", "CANCEL", "SOURCE_LIST_UPDATED", "PUBLISH_CHECKED"):
        assert actions[action] >= 1, (action, dict(actions))
    assert len(denied) >= 2 and all("sealed" in (d.reason or "") for d in denied)
    assert len(late) == 1 and "closed at" in late[0].reason


def test_auctions_extend_on_late_bids_and_the_ladder_is_ranked(packs):
    with tenant_tx(kac(packs)) as s:
        found = events(s, "K")
        auctions = [e for e in found.values() if e.type == "REVERSE_AUCTION"]
        bids = {e.number: list(s.execute(select(AuctionBid).where(AuctionBid.event_id == e.id).order_by(AuctionBid.submitted_at)).scalars()) for e in auctions}
        clarifications = list(s.execute(select(SourcingClarification).join(SourcingEvent, SourcingEvent.id == SourcingClarification.event_id)
                                        .where(SourcingEvent.title.like("MOCK K%"))).scalars())
    assert len(auctions) == 3 and all(len(b) >= 8 for b in bids.values())
    assert any(any(x.extended_close for x in b) for b in bids.values())
    assert all(any(x.rank_at_submit == 1 for x in b) for b in bids.values())
    assert len(clarifications) >= 5 and any(c.asked_by_supplier_id is None for c in clarifications) and any(c.status == "ANSWERED" and c.answer for c in clarifications)


# ================================================================ awards
def test_award_scenarios_rationale_governance_and_regret_letters(packs):
    with tenant_tx(kac(packs)) as s:
        found = events(s, "K")
        rows = s.execute(select(AwardDecision, AwardScenario, SourcingEvent).join(AwardScenario, AwardScenario.id == AwardDecision.scenario_id)
                         .join(SourcingEvent, SourcingEvent.id == AwardDecision.event_id).where(SourcingEvent.title.like("MOCK K%"))).all()
        regrets = s.execute(select(func.count()).select_from(Notification).where(Notification.kind == "SOURCING_NOT_AWARDED", Notification.object_ref.in_([e.number for e in found.values()]))).scalar_one()
        awarded_scenarios = [(sc.kind, d.exceptions, d.rationale, d.regret_sent_at, sc.allocations, sc.risk_score) for d, sc, e in rows if d.status == "APPROVED"]
        pending = [e.status for d, sc, e in rows if d.status == "PENDING"]
    kinds = Counter(k for k, *_ in awarded_scenarios)
    for kind in ("LOWEST_COST", "BEST_VALUE", "CAPACITY_CONSTRAINED", "CUSTOM"):
        assert kinds[kind] >= 1, kinds
    assert len(awarded_scenarios) >= 15 and all(r[3] is not None for r in awarded_scenarios)                   # a regret letter run at every award
    non_lowest = [r for r in awarded_scenarios if any(e["code"] == "NOT_LOWEST" for e in r[1])]
    assert len(non_lowest) >= 2 and all(r[2] and len(r[2]) >= 15 for r in non_lowest)                          # a non-lowest award carries its written rationale
    assert any(len(r[4]) == 2 for r in awarded_scenarios if r[0] in ("CAPACITY_CONSTRAINED", "CUSTOM"))       # dual-source award
    assert any(r[1] and any(e["code"] == "LIMITED_COMPETITION" for e in r[1]) for r in awarded_scenarios)
    assert regrets >= 20 and pending and set(pending) == {"AWARD_PENDING"}


def test_disqualification_gate_two_person_opening_and_cancellations(packs):
    with tenant_tx(kac(packs)) as s:
        found = events(s, "K")
        dq = s.execute(select(Bid).where(Bid.event_id == found["K10"].id, Bid.status == "DISQUALIFIED")).scalars().all()
        opened = {k: s.execute(select(func.count()).select_from(AuditEvent).where(AuditEvent.object_id == found[k].id, AuditEvent.action == "BIDS_OPEN_WITNESS")).scalar_one()
                  for k in ("K15", "K24", "K25")}
        cancelled = {k: found[k].status for k in ("K34", "K35", "K36", "K37")}
        k36 = s.execute(select(AwardDecision.status).where(AwardDecision.event_id == found["K36"].id)).scalars().all()
    assert len(dq) == 1 and "IATF" in dq[0].disqualified_reason
    assert opened == {"K15": 2, "K24": 0, "K25": 1}, opened
    assert set(cancelled.values()) == {"CANCELLED"} and k36 == ["CANCELLED"]
    assert found["K15"].status == "AWARDED" and found["K24"].status == "CLOSED" and found["K25"].status == "CLOSED"


# ================================================================ hand-offs
def test_awards_create_contracts_with_default_numbers_for_a_separate_supplier_set(packs):
    with tenant_tx(kac(packs)) as s:
        ids = [e.id for e in events(s, "K").values()]
        born = list(s.execute(select(Contract).where(Contract.source_event_id.in_(ids)).order_by(Contract.number)).scalars())
        kac_suppliers = set(s.execute(select(Contract.supplier_id).where(Contract.number.like("KAC-%"))).scalars())
        active = [c for c in born if c.status in ("ACTIVE", "EXPIRING")]
        published = {c.id: s.execute(select(func.count()).select_from(PriceValidity).join(ContractLine, ContractLine.id == PriceValidity.contract_line_id)
                                     .where(ContractLine.contract_id == c.id, PriceValidity.published.is_(True))).scalar_one() for c in active}
        quotas = list(s.execute(select(QuotaArrangement).where(QuotaArrangement.source_event_id.in_(ids))).scalars())
        shares = {q.id: sum(l.share for l in s.execute(select(QuotaLine).where(QuotaLine.quota_id == q.id)).scalars()) for q in quotas}
        counters = [l.allocated_qty for q in quotas for l in s.execute(select(QuotaLine).where(QuotaLine.quota_id == q.id)).scalars()]
        source_list = s.execute(select(func.count()).select_from(SourceList).where(SourceList.supplier_id.in_([c.supplier_id for c in active]))).scalar_one()
        timers = s.execute(select(func.count()).select_from(Timer).where(Timer.kind.in_(("CONTRACT_EXPIRY", "CONTRACT_RENEWAL")), Timer.object_id.in_([c.id for c in active]),
                                                                         Timer.fired_at.is_not(None))).scalar_one()
    assert len(born) >= 15 and not any(c.number.startswith("KAC-") for c in born) and not ({c.supplier_id for c in born} & kac_suppliers)
    assert len(active) >= 4 and all(n >= 1 for n in published.values()), published
    assert len(quotas) >= 3 and all(abs(v - 1) <= Decimal("0.001") for v in shares.values()), shares
    assert counters and all(c == 0 for c in counters)                                                          # running counters exist; no order has consumed them yet
    assert source_list >= 4 and timers == 0                                                                    # activation timers are still to come, none fired by the pack


def test_negotiated_savings_feed_the_pipeline_with_the_baseline_method_recorded(packs):
    with tenant_tx(kac(packs)) as s:
        found = events(s, "K")
        initiatives = list(s.execute(select(SavingsInitiative).where(SavingsInitiative.source_event_id.in_([e.id for e in found.values()]))).scalars())
        methods = Counter(i.baseline_method for i in initiatives)
        stages = Counter(i.stage for i in initiatives)
        negotiated = list(s.execute(select(SavingsLedgerEntry).where(SavingsLedgerEntry.initiative_id.in_([i.id for i in initiatives]), SavingsLedgerEntry.type == "NEGOTIATED")).scalars())
    assert len(initiatives) >= 30 and stages["NEGOTIATED"] >= 10 and stages["CONTRACTED"] >= 3 and stages["LOST"] >= 2, stages
    for method in ("LAST_PRICE", "SHOULD_COST", "MARKET_INDEX", "BUDGET"):
        assert methods[method] >= 1, methods
    assert negotiated and all(e.amount_minor >= 0 and "baseline method" in e.formula for e in negotiated)      # a cost increase is never booked as a saving


# ================================================================ configuration
def test_should_cost_models_indices_benchmarks_templates_twin_and_rules(packs):
    with tenant_tx(kac(packs)) as s:
        models = {m.commodity: m for m in s.execute(select(ShouldCostModel)).scalars()}
        series = s.execute(select(IndexValue.index_code, func.count(), func.min(IndexValue.as_of), func.max(IndexValue.as_of)).where(IndexValue.source_ref == mock.SOURCE_REF)
                           .group_by(IndexValue.index_code)).all()
        bench = Counter(k for (k,) in s.execute(select(PriceBenchmark.kind).where(PriceBenchmark.source.like("MOCK (sourcing_ops)%"))))
        templates = {t.code: t for t in s.execute(select(SourcingTemplate)).scalars()}
        twin = s.execute(select(func.count()).select_from(TwinSnapshot).where(TwinSnapshot.source == "SEEDED", TwinSnapshot.model_version == "mock-sourcing-ops-v1")).scalar_one()
        history = s.execute(select(func.count()).select_from(RuleSet).where(RuleSet.version.like("%-HIST-MOCK"))).scalar_one()
        found = events(s, "K")
        policy_2025 = rules.resolve(s, "SOURCING-POLICY", on=date(2025, 6, 1), category="FASTENERS")
        policy_2026 = rules.resolve(s, "SOURCING-POLICY", on=date(2026, 6, 1), category="FASTENERS")
        tco_2026 = rules.resolve(s, "SOURCING-TCO", on=date(2026, 6, 1))
        award_rule_2025 = rules.resolve(s, "AWARD-APPROVAL", on=date(2025, 6, 1))
    assert {"castings", "forgings", "fasteners", "bearings", "wiring", "plastics", "rubber", "packaging", "MRO", "services"} <= set(models)
    assert len(series) == 10 and all(n == 19 and a == date(2025, 4, 1) and b == date(2026, 10, 1) for _, n, a, b in series)
    assert bench["MARKET"] >= 30 and bench["PEER"] >= 10
    assert {"RFQ-DIRECT-MATERIAL", "RFP-SERVICES", "AUCTION-STANDARD"} <= set(templates)
    assert twin >= 60 and history >= 60
    assert policy_2025.body["minBidders"] == 3 and policy_2026.body["lineCategoryCheck"] == "ENFORCE" and tco_2026.body["dutyRates"]["72"] == "7.5"
    assert award_rule_2025.version.endswith("-HIST-MOCK")
    assert found["K16"].cloned_from == found["K03"].number and found["K40"].template_code == "RFQ-DIRECT-MATERIAL"


def test_timers_of_closed_and_cancelled_events_are_fired_and_open_ones_are_left(packs):
    with tenant_tx(kac(packs)) as s:
        found = events(s, "K")
        by_status = {}
        for key, e in found.items():
            n = s.execute(select(func.count()).select_from(Timer).where(Timer.object_id == e.id, Timer.kind.in_(("SOURCING_CLOSE", "SOURCING_OPEN")), Timer.fired_at.is_(None))).scalar_one()
            by_status.setdefault(e.status, []).append(n)
        due = list(s.execute(select(Timer.due_at).where(Timer.object_id.in_([e.id for e in found.values()]), Timer.kind.in_(("SOURCING_CLOSE", "SOURCING_OPEN")),
                                                        Timer.fired_at.is_(None))).scalars())
    for status in ("AWARDED", "AWARD_PENDING", "UNDER_EVALUATION", "CLOSED", "CANCELLED"):
        assert all(n == 0 for n in by_status[status]), (status, by_status[status])
    assert all(n >= 1 for n in by_status["OPEN"] + by_status["PUBLISHED"]) and all(d > date_time(2026, 11, 4) for d in due)


def date_time(y, m, d):
    return clock.at_ist(date(y, m, d), 0, 0)


# ================================================================ nothing else is touched
def test_kac_contracts_invoices_payments_and_stock_are_untouched(packs):
    with tenant_tx(kac(packs)) as s:
        after = row_hashes(s, packs["kac_models"])
        after.update(row_hashes(s, (Contract, ContractLine), where=KAC_CONTRACTS))
    assert after == packs["kac_before"]


def test_axn_gets_six_non_signature_events_and_the_signature_case_is_unchanged(packs):
    with tenant_tx(axn(packs)) as s:
        found = events(s, "A")
        signature = row_hashes(s, (SourcingEvent,), where={SourcingEvent: SourcingEvent.id == packs["signature_id"]})
        for model in (EventLine, Bid, AwardScenario, AwardDecision):
            signature.update(row_hashes(s, (model,), where={model: model.event_id == packs["signature_id"]}))
        dates = [e.created_at.astimezone(clock.IST).date() for e in found.values()]
    assert len(found) == 6 and set(e.status for e in found.values()) >= {"AWARDED", "CANCELLED", "CLOSED", "UNDER_EVALUATION"}
    assert {e.type for e in found.values()} >= {"RFI", "RFP", "RFQ"} and min(dates) >= date(2027, 8, 1) and max(dates) <= date(2027, 9, 30)
    assert signature == packs["axn_before"]
    for row in mock.axn_plan():
        assert found[row["key"]].status == row["state"], row["key"]


def test_audit_hash_chains_are_valid_for_axn_and_kac(packs):
    for code in ("AXN", "KAC"):
        with tenant_tx(packs["ids"][code]) as s:
            result = verify_chain(s)
        assert result["valid"], (code, result)


def test_pack_registration_and_summary(packs):
    names = list(datasets.PACKS)
    assert names.index("sourcing_ops") > names.index("finance_ops")
    module = datasets.load("sourcing_ops")
    assert module.KEY == "sourcing-ops" and module.REQUIRES == {"finance-ops": "1"} and module.TENANTS == ("AXN", "KAC") and module.READY
    for code, minimum in (("KAC", 400), ("AXN", 40)):
        summary = packs["results"][code].get("summary") or {}
        if summary:
            assert summary["serviceCalls"] >= minimum or summary["stepsSkipped"] >= minimum, (code, summary)      # a resumed load skips the steps it already made
            assert summary["counts"]["events"] == (40 if code == "KAC" else 6)
