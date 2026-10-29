"""Code-review fixes for F3 sourcing and F4 contracts (findings F#1-F#16).

Every test that writes runs in one transaction that is rolled back at the end (or only reads the signature case), so the
signature-case KPIs other files check never change. Times are pinned to 2029-2030, after every seeded object.
"""
import hashlib
import json
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.pic import views
from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuctionBid, AuditEvent, Bid, Clause, Contract, ContractLine, EventLine, Material, Notification, OutboxEvent, PoLine,
    PriceValidity, PurchaseOrder, Requisition, SourcingEvent, Supplier, Task, Tenant, Timer,
)
from app.pic.platform import clock, crypto, outbox, workflow
from app.pic.platform.auth import Principal, scopes_for
from app.pic.platform.errors import Problem
from app.pic.platform.money import line_amount
from app.pic.services import amendments, auction, notifications, sourcing
from app.pic.services import contract as contract_svc

IST = clock.IST
SIGNATURE_EVENT = "DC-330 aluminium die-cast housing – annual requirement"


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


PRICE_ONLY = [{"code": "PRICE_TCO", "name": "Price / TCO", "weight": 100}]
BID = {"line": 10, "unit_price": "400", "payment_terms_days": 60, "lead_time_days": 14, "capacity_per_month": "5000"}


def _draft(s, title: str, close_at: datetime, criteria=PRICE_ONLY, constraints=None) -> SourcingEvent:
    act(s, "category.head")
    return sourcing.create_event(
        s, type="RFQ", title=title, category="ALU-DIECAST",
        lines=[{"requisition": "REQ-2312", "line": 10, "annual_qty": "20000", "monthly_qty": "2000"}], criteria=criteria,
        invitees=[{"supplier": "TF001"}, {"supplier": "KD002"}], close_at=close_at, baseline_method="BUDGET", baseline_price_minor=42000,
        constraints=constraints, savings_target_pct=Decimal("3.0"))


def _bid(s, who: str, event: SourcingEvent, **overrides) -> Bid:
    user = act(s, who)
    return sourcing.submit_bid(s, event, s.get(Supplier, user.supplier_id), [{**BID, **overrides}])


def _close(s, event: SourcingEvent, when: datetime) -> dict:
    clock.set_pinned(when)
    act(s, "category.head")
    return sourcing.close(s, event)


# ---------------------------------------------------------------- F#1 malformed bids, F#15 eligibility at bid
def test_malformed_bids_are_rejected_on_submission_and_cannot_break_the_close(client, login):
    assert client.post("/v1/sourcing/events/SE-NONE/bids", json={"lines": []}, headers=login("tf.sales")).status_code == 422
    with rolled_back(at(2029, 3, 1)) as s:
        event = _draft(s, "F#1 malformed bid", at(2029, 3, 8, 17))
        sourcing.publish(s, event)
        tf = act(s, "tf.sales")
        sup = s.get(Supplier, tf.supplier_id)
        for lines in ([], [{**BID, "line": 20}], [BID, BID], [{k: v for k, v in BID.items() if k != "unit_price"}],
                      [{**BID, "unit_price": "0"}], [{**BID, "lead_time_days": "soon"}]):
            p = problem(sourcing.submit_bid, s, event, sup, lines)
            assert p.status == 422 and p.code == "INVALID_BID_LINES", lines
        # F#15: a supplier blocked after the invitation cannot bid.
        sup.status = "BLOCKED"
        p = problem(sourcing.submit_bid, s, event, sup, [BID])
        assert p.status == 422 and p.rule_ref == "P06/SRC-INVITE"
        sup.status = "ACTIVE"
        assert sourcing.submit_bid(s, event, sup, [BID]).status == "SEALED"
        # A sealed bid stored before validation existed (foreign line): the close skips it instead of failing for every bidder.
        kd = act(s, "kd.sales")
        payload = json.dumps({"lines": [{**BID, "line": 99, "unit_price": "390"}]}, sort_keys=True, default=str)
        s.add(Bid(tenant_id=event.tenant_id, event_id=event.id, supplier_id=kd.supplier_id, round=1, status="SEALED",
                  sealed_payload=crypto.encrypt(event.tenant_id, f"bid:{event.id}", payload),
                  payload_hash=hashlib.sha256(payload.encode()).hexdigest(), submitted_at=clock.now(), submitted_by=kd.id, created_by=kd.id))
        s.flush()
        result = _close(s, event, at(2029, 3, 8, 17, 5))
        assert event.status == "UNDER_EVALUATION" and result["unsealed"] == 1
        assert [m["supplier"] for m in result["matrix"]] == ["TF001"]
        statuses = {b.supplier_id: b.status for b in s.execute(select(Bid).where(Bid.event_id == event.id)).scalars()}
        assert statuses == {tf.supplier_id: "UNSEALED", kd.supplier_id: "INVALID"}
        invalid = s.execute(select(AuditEvent).where(AuditEvent.object_id == event.id, AuditEvent.action == "BID_INVALID")).scalar_one()
        assert invalid.after["supplier"] == "KD002" and invalid.after["rejectedLines"][0]["line"] == 99
        assert problem(sourcing.score, s, event, [{"supplier": "KD002", "criterion": "QUALITY", "score": 80}]).status == 422


# ---------------------------------------------------------------- F#5 owner / category manager, F#6 one line per event
def test_event_commands_need_the_owner_or_a_category_manager_and_the_close_timer_still_closes():
    with rolled_back(at(2029, 3, 1)) as s:
        event = _draft(s, "F#5 manager checks", at(2029, 3, 8, 17))
        act(s, "buyer")  # sourcing:manage, but neither the owner nor a category manager
        assert problem(sourcing.publish, s, event).code == "NOT_EVENT_MANAGER"
        act(s, "category.manager")  # category manager of ALU-DIECAST (not the owner)
        sourcing.publish(s, event)
        _bid(s, "tf.sales", event)
        _bid(s, "kd.sales", event, unit_price="405")
        clock.set_pinned(at(2029, 3, 8, 17, 5))
        act(s, "buyer")
        assert problem(sourcing.close, s, event).code == "NOT_EVENT_MANAGER"
        # The close timer runs without an owner check (system), whoever the session principal is.
        timer = s.execute(select(Timer).where(Timer.object_id == event.id, Timer.kind == "SOURCING_CLOSE", Timer.fired_at.is_(None))).scalar_one()
        timer.fired_at = clock.now()
        workflow._timer_handlers["SOURCING_CLOSE"](s, timer)
        assert event.status == "UNDER_EVALUATION"
        assert problem(sourcing.new_round, s, event, at(2029, 3, 12, 17)).code == "NOT_EVENT_MANAGER"
        assert problem(sourcing.build_scenarios, s, event).code == "NOT_EVENT_MANAGER"
        act(s, "category.head")
        scenarios = {x["kind"]: x for x in sourcing.build_scenarios(s, event)}
        act(s, "buyer")
        p = problem(sourcing.propose_award, s, event, uuid.UUID(scenarios["LOWEST_COST"]["id"]), None, "No conflict")
        assert p.code == "NOT_EVENT_MANAGER" and p.status == 403
        # F#15: eligibility is re-checked at award; a supplier blocked after bidding cannot be awarded.
        act(s, "category.head")
        supplier(s, "TF001").status = "BLOCKED"
        p = problem(sourcing.propose_award, s, event, uuid.UUID(scenarios["LOWEST_COST"]["id"]), None, "No conflict")
        assert p.status == 422 and p.rule_ref == "P06/SRC-INVITE"


def test_an_event_is_evaluated_per_item_so_it_has_exactly_one_line():
    with rolled_back(at(2029, 3, 1)) as s:
        act(s, "category.head")
        line = {"requisition": "REQ-2312", "line": 10, "annual_qty": "20000", "monthly_qty": "2000"}
        p = problem(sourcing.create_event, s, type="RFP", title="F#6 two lines", category="ALU-DIECAST", lines=[line, line],
                    criteria=PRICE_ONLY, invitees=[{"supplier": "TF001"}], close_at=at(2029, 3, 8, 17))
        assert p.status == 422 and p.rule_ref == "SRC-ONE-LINE"
        event = _draft(s, "F#6 publish check", at(2029, 3, 8, 17))
        first = s.execute(select(EventLine).where(EventLine.event_id == event.id)).scalar_one()
        s.add(EventLine(tenant_id=event.tenant_id, event_id=event.id, line_no=20, material_id=first.material_id, description=first.description,
                        plant=first.plant, annual_qty=first.annual_qty, monthly_qty=first.monthly_qty, uom=first.uom))
        s.flush()
        assert problem(sourcing.publish, s, event).rule_ref == "SRC-ONE-LINE"


# ---------------------------------------------------------------- F#7 max share binds a single supplier, F#13 rank, F#14 scores
def test_capacity_constrained_scenario_applies_max_share_to_a_single_supplier():
    row = {"supplier": "TF001", "supplierId": str(uuid.uuid4()), "priceMinor": 40000, "tcoMinor": 41000, "verifiedCapacityPerMonth": "9000"}
    q = Decimal(2000)
    assert sourcing._optimise([row], q, {"max_suppliers": 2, "max_share": "0.60", "min_share": "0.20"}) is None
    sole = sourcing._optimise([row], q, {"max_suppliers": 2, "max_share": "1", "min_share": "0.20"})
    assert [(r["supplier"], s) for r, s in sole["allocations"]] == [("TF001", Decimal(1))]
    other = {**row, "supplier": "KD002", "supplierId": str(uuid.uuid4()), "tcoMinor": 42000}
    split = sourcing._optimise([row, other], q, {"max_suppliers": 2, "max_share": "0.60", "min_share": "0.20"})
    assert [(r["supplier"], s) for r, s in split["allocations"]] == [("TF001", Decimal("0.60")), ("KD002", Decimal("0.40"))]


def test_auction_rank_is_hidden_from_suppliers_when_show_rank_is_off():
    bid = AuctionBid(id=uuid.uuid4(), supplier_id=uuid.uuid4(), price_minor=9000, rank_at_submit=2, submitted_at=at(2029, 1, 1),
                     extended_close=False)
    assert "rankAtSubmit" not in auction._bid_row(bid, {}, False, False)
    assert auction._bid_row(bid, {}, False, True)["rankAtSubmit"] == 2
    assert auction._bid_row(bid, {bid.supplier_id: "TF001"}, True)["rankAtSubmit"] == 2  # buyers always see it


def test_manual_scores_carry_over_to_the_bid_of_a_new_round():
    criteria = [{"code": "PRICE_TCO", "name": "Price / TCO", "weight": 70}, {"code": "QUALITY", "name": "Quality", "weight": 30}]
    with rolled_back(at(2029, 3, 1)) as s:
        event = _draft(s, "F#14 scores across rounds", at(2029, 3, 8, 17), criteria=criteria)
        sourcing.publish(s, event)
        _bid(s, "tf.sales", event)
        _bid(s, "kd.sales", event, unit_price="405")
        _close(s, event, at(2029, 3, 8, 17, 5))
        sourcing.score(s, event, [{"supplier": "TF001", "criterion": "QUALITY", "score": 90},
                                  {"supplier": "KD002", "criterion": "QUALITY", "score": 70}])
        sourcing.new_round(s, event, at(2029, 3, 12, 17), "improve price")
        _bid(s, "tf.sales", event, unit_price="395")
        _close(s, event, at(2029, 3, 12, 17, 5))
        matrix = {m["supplier"]: m for m in sourcing.evaluation_matrix(s, event)}
        assert matrix["TF001"]["round"] == 2 and matrix["TF001"]["scores"]["QUALITY"] == "90.00"
        assert matrix["KD002"]["round"] == 1 and matrix["KD002"]["scores"]["QUALITY"] == "70.00"
        # A new score by the same evaluator on the new bid replaces the carried one.
        sourcing.score(s, event, [{"supplier": "TF001", "criterion": "QUALITY", "score": 60}])
        assert {m["supplier"]: m for m in sourcing.evaluation_matrix(s, event)}["TF001"]["scores"]["QUALITY"] == "60.00"


# ---------------------------------------------------------------- F#2 / F#10 supplier views, F#12 / F#16 award hand-off
def _signature(s):
    event = s.execute(select(SourcingEvent).where(SourcingEvent.title == SIGNATURE_EVENT)).scalar_one()
    tf_contract = s.execute(select(Contract).where(Contract.source_event_id == event.id, Contract.supplier_id == supplier(s, "TF001").id)).scalar_one()
    return event, tf_contract


def test_suppliers_never_see_the_baseline_savings_target_or_internal_contract_history(client, login):
    with tenant_tx(_tid()) as s:
        event, contract = _signature(s)
        number, contract_no = event.number, contract.number
    tf, buyer = login("tf.sales"), login("category.manager")
    mine = [e for e in client.get("/v1/sourcing/events?limit=200", headers=tf).json()["items"] if e["number"] == number]
    assert mine and "baseline_price_minor" not in mine[0]
    internal = [e for e in client.get("/v1/sourcing/events?limit=200", headers=buyer).json()["items"] if e["number"] == number]
    assert internal[0]["baseline_price_minor"] is not None
    detail = client.get(f"/v1/sourcing/events/{number}", headers=tf).json()
    assert not {"savings_target_pct", "owner_id", "baseline_price_minor", "process"} & set(detail)
    assert {"savings_target_pct", "owner_id"} <= set(client.get(f"/v1/sourcing/events/{number}", headers=buyer).json())
    portal = client.get(f"/v1/contracts/{contract_no}", headers=tf).json()
    assert not {"process", "lineage", "rule_set_version", "owner_id"} & set(portal) and portal["clauses"]
    assert {"process", "lineage", "rule_set_version"} <= set(client.get(f"/v1/contracts/{contract_no}", headers=login("contract.manager")).json())


def test_award_payload_carries_company_code_and_invitees_and_award_contracts_use_it():
    with tenant_tx(_tid()) as s:
        event, contract = _signature(s)
        awarded = s.execute(select(OutboxEvent).where(OutboxEvent.topic == "sourcing.event.awarded", OutboxEvent.object_id == event.id)).scalar_one()
        requisition = s.get(Requisition, uuid.UUID(awarded.payload["requisitionId"]))
        assert awarded.payload["companyCode"] == requisition.company_code == contract.company_code
        assert len(awarded.payload["inviteeSupplierIds"]) == 3
        assert contract_svc._award_company_code(s, {"requisitionId": str(requisition.id)}) == requisition.company_code


def test_award_and_consumption_threshold_notifications_reach_suppliers_and_contract_managers():
    names = {(topic, name) for topic in ("sourcing.event.awarded", "contract.consumption.threshold") for name, _ in outbox._consumers[topic]}
    assert {("sourcing.event.awarded", "notify-sourcing-awarded"), ("contract.consumption.threshold", "notify-contract-consumption")} <= names

    def notes(s, who: str, kind: str, ref: str):
        user = s.execute(select(AppUser).where(AppUser.email == f"{who}@axion.example")).scalar_one()
        return s.execute(select(Notification).where(Notification.user_id == user.id, Notification.kind == kind,
                                                    Notification.object_ref == ref)).scalars().all()

    # The signature case's award (TF 60 % @ 398, KD 40 % @ 405, SLA not awarded) was relayed through the new consumer.
    with tenant_tx(_tid()) as s:
        event, contract = _signature(s)
        [tf] = notes(s, "tf.sales", "SOURCING_AWARDED", event.number)
        [kd] = notes(s, "kd.sales", "SOURCING_AWARDED", event.number)
        [sla] = notes(s, "sla.sales", "SOURCING_NOT_AWARDED", event.number)
        assert "60% of the volume" in tf.body and "₹398.00" in tf.body and "40% of the volume" in kd.body and "₹405.00" in kd.body
        assert "TF001" not in sla.body and "398" not in sla.body  # no competitor name or price
        assert not notes(s, "sla.sales", "SOURCING_AWARDED", event.number) and not notes(s, "tf.sales", "SOURCING_NOT_AWARDED", event.number)
    with rolled_back(at(2029, 5, 1)) as s:
        event, contract = _signature(s)
        act(s, "category.manager")
        replay = SimpleNamespace(id=uuid.uuid4(), object_type="SOURCING_EVENT", object_id=event.id, object_ref=event.number,
                                 payload=s.execute(select(OutboxEvent.payload).where(OutboxEvent.topic == "sourcing.event.awarded",
                                                                                     OutboxEvent.object_id == event.id)).scalar_one())
        notifications._sourcing_awarded(s, replay)  # once per supplier (dedup)
        assert len(notes(s, "tf.sales", "SOURCING_AWARDED", event.number)) == 1
        threshold = SimpleNamespace(id=uuid.uuid4(), object_type="CONTRACT", object_id=contract.id, object_ref=contract.number,
                                    payload={"threshold": 85, "consumedPct": "85.25"})
        notifications._contract_consumption(s, threshold)
        owner = s.execute(select(AppUser).where(AppUser.id == contract.owner_id)).scalar_one().email.split("@")[0]
        for who in {"contract.manager", "contract.manager2", owner}:  # the contract managers and the owner
            fresh = [n for n in notes(s, who, "CONTRACT_CONSUMPTION", contract.number) if "85.25%" in n.body]
            assert len(fresh) == 1, who
        assert not notes(s, "tf.sales", "CONTRACT_CONSUMPTION", contract.number)


# ---------------------------------------------------------------- F#3 supplier redlines, F#4 four-eyes on contract approval
def _contract_draft(s, title: str, owner: str = "category.manager", index_ref=None) -> Contract:
    owner_id = act(s, owner).id
    act(s, "contract.manager")
    dc331 = s.execute(select(Material).where(Material.number == "DC-331")).scalar_one()
    contract = contract_svc.create_draft(
        s, type="QUANTITY_CONTRACT", title=title, supplier_id=supplier(s, "TF001").id, company_code="1000", valid_from=date(2029, 1, 1),
        valid_to=date(2029, 12, 31), payment_terms="N60", incoterms="FCA Trichy",
        lines=[{"material_id": dc331.id, "description": dc331.description, "plant": "P100", "uom": "EA", "target_qty": "1000",
                "unit_price_minor": 21000}], owner_id=owner_id, tolerances={"over_pct": "2", "under_pct": "5", "price_pct": "0"},
        index_ref=index_ref)
    contract_svc.ai_review(s, contract)
    return contract


def test_supplier_redline_is_non_standard_until_the_contract_manager_reviews_it():
    with rolled_back(at(2028, 12, 1)) as s:
        contract = _contract_draft(s, "F#3 redline review")
        clause = s.execute(select(Clause).where(Clause.contract_id == contract.id).order_by(Clause.code)).scalars().first()
        code, original = clause.code, clause.text
        act(s, "tf.sales")
        contract_svc.redline(s, contract, code, "Supplier wording: liability capped at the order value", "STANDARD")
        assert clause.position == "NON_STANDARD"  # the supplier cannot classify its own deviation
        entry = s.execute(select(AuditEvent).where(AuditEvent.object_id == contract.id, AuditEvent.action == "CLAUSE_REDLINED")).scalar_one()
        assert entry.before["text"] == original and entry.after["text"].startswith("Supplier wording") and entry.after["pendingReview"]
        assert entry.after["proposedPosition"] == "STANDARD" and entry.after["party"] == "SUPPLIER"
        [pending] = views.contract(s, contract)["pendingRedlines"]
        assert pending["clause"] == code and pending["originalText"] == original
        act(s, "contract.manager")
        p = problem(contract_svc.submit, s, contract)
        assert p.status == 409 and p.code == "REDLINE_REVIEW_PENDING"
        for who in ("buyer", "tf.sales"):
            act(s, who)
            assert problem(contract_svc.review_redline, s, contract, code, "ACCEPT", "STANDARD").status == 403
        act(s, "contract.manager")
        assert problem(contract_svc.review_redline, s, contract, code, "ACCEPT").code == "INVALID_POSITION"
        contract_svc.review_redline(s, contract, code, "RESTORE", comment="Playbook wording stays")
        assert (clause.text, clause.position) == (original, "STANDARD") and not views.contract(s, contract)["pendingRedlines"]
        reviewed = s.execute(select(AuditEvent).where(AuditEvent.object_id == contract.id, AuditEvent.action == "REDLINE_REVIEWED")).scalar_one()
        assert reviewed.before["text"].startswith("Supplier wording") and reviewed.after["text"] == original and reviewed.reason == "Playbook wording stays"
        assert problem(contract_svc.review_redline, s, contract, code, "RESTORE").code == "NO_PENDING_REDLINE"
        # Accepted as a non-standard deviation: the approval goes through LEGAL (above chain).
        act(s, "tf.sales")
        contract_svc.redline(s, contract, code, "Supplier wording, second proposal")
        act(s, "contract.manager")
        contract_svc.review_redline(s, contract, code, "ACCEPT", "NON_STANDARD")
        assert clause.text == "Supplier wording, second proposal" and clause.position == "NON_STANDARD"
        assert contract_svc.submit(s, contract)["chain"][0] == "LEGAL"


def test_neither_the_owner_nor_the_submitter_can_approve_the_contract():
    with rolled_back(at(2028, 12, 1)) as s:
        contract = _contract_draft(s, "F#4 four eyes")  # owner: category.manager, submitted by contract.manager
        submitter = act(s, "contract.manager")
        assert contract_svc.submit(s, contract)["chain"] == ["CONTRACT_MANAGER"]
        task = s.execute(select(Task).where(Task.object_id == contract.id, Task.kind == "CONTRACT_APPROVAL", Task.status == "OPEN")).scalar_one()
        assert {submitter.id, contract.owner_id} <= set(task.excluded_user_ids)
        assert workflow.can_work(s.info["principal"], task) is not None
        act(s, "contract.manager2")
        assert workflow.can_work(s.info["principal"], task) is None
        workflow.complete(s, task.id, "APPROVE", "Second contract manager")
        assert contract.status == "OUT_FOR_SIGNATURE"


# ---------------------------------------------------------------- F#8 index resets never compound, F#11 non-standard terms
INDEX = {"index": "LME-AL", "base": "2400", "band_pct": "5"}


def _activate(s, contract: Contract) -> None:
    act(s, "contract.manager")
    contract_svc.submit(s, contract)
    task = s.execute(select(Task).where(Task.object_id == contract.id, Task.kind == "CONTRACT_APPROVAL", Task.status == "OPEN")).scalar_one()
    act(s, "contract.manager2")
    workflow.complete(s, task.id, "APPROVE", "ok")
    act(s, "contract.manager")
    contract_svc.sign(s, contract, "BUYER", "Ganesh Murthy")
    act(s, "tf.sales")
    contract_svc.sign(s, contract, "SUPPLIER", "Authorised signatory")
    act(s, "contract.manager")
    contract_svc.activate(s, contract)


def test_an_index_reset_after_an_extension_starts_from_the_negotiated_price():
    with rolled_back(at(2028, 12, 1)) as s:
        contract = _contract_draft(s, "F#8 index after extension", index_ref=INDEX)
        _activate(s, contract)
        clock.set_pinned(at(2029, 6, 1))
        first = contract_svc.index_reset(s, contract, Decimal("2640"), date(2029, 4, 1))  # +10 %, band 5 % → +5 %
        assert first["lines"][0]["newPriceMinor"] == 22050
        amendment = amendments.create(s, contract, kind="EXTENSION", changes={"validTo": "2030-12-31"}, reason="Extension for 2030",
                                      effective_from=date(2029, 6, 1))
        [task] = s.execute(select(Task).where(Task.object_id == contract.id, Task.kind == "CONTRACT_AMENDMENT", Task.status == "OPEN")).scalars().all()
        act(s, "contract.manager2")
        workflow.complete(s, task.id, "APPROVE", "ok")
        assert amendment.status == "EFFECTIVE" and contract.valid_to == date(2030, 12, 31)
        line = s.execute(select(ContractLine).where(ContractLine.contract_id == contract.id)).scalar_one()
        extension = s.execute(select(PriceValidity).where(PriceValidity.contract_line_id == line.id,
                                                          PriceValidity.reason.like("EXTENSION%"))).scalar_one()
        assert extension.unit_price_minor == 22050  # the price in force continues into the extension period
        act(s, "contract.manager")
        again = contract_svc.index_reset(s, contract, Decimal("2640"), date(2030, 4, 1))
        assert again["lines"][0]["oldPriceMinor"] == 21000 and again["lines"][0]["newPriceMinor"] == 22050  # not 23153 (compounded)
        # F#11: a TERMS amendment that introduces a NON_STANDARD clause is routed through LEGAL, below the value threshold too.
        code = s.execute(select(Clause.code).where(Clause.contract_id == contract.id).order_by(Clause.code)).scalars().first()
        clause = {"code": code, "text": "Non-standard: liability capped at 50% of the annual order value"}
        plan = amendments.plan(s, contract, "TERMS", {"clauses": [{**clause, "position": "NON_STANDARD"}]}, date(2029, 6, 1))
        assert plan["band"] == "non_standard" and "LEGAL" in plan["approvalChain"] and plan["nonStandardClauses"] == [code]
        plain = amendments.plan(s, contract, "TERMS", {"clauses": [{**clause, "position": "STANDARD"}]}, date(2029, 6, 1))
        assert plain["band"] == "below" and plain["approvalChain"] == ["CONTRACT_MANAGER"]


# ---------------------------------------------------------------- F#9 consumption follows changes, cancellations and closes
def test_contract_consumption_is_recomputed_from_the_live_order_lines():
    topics = {topic for topic, consumers in outbox._consumers.items() if any(name == "contract-consumption" for name, _ in consumers)}
    assert topics == {"purchase_order.released", "purchase_order.changed", "purchase_order.cancelled", "purchase_order.closed"}
    with rolled_back(at(2029, 5, 1)) as s:
        act(s, "buyer")
        pl, po = s.execute(select(PoLine, PurchaseOrder).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(
            PoLine.contract_line_id.is_not(None), PurchaseOrder.status.in_(contract_svc.CONSUMING_PO))
            .order_by(PurchaseOrder.number)).first()
        cl = s.get(ContractLine, pl.contract_line_id)
        base_qty, base_value = contract_svc.recompute_consumption(s, cl)
        event = SimpleNamespace(object_id=po.id, payload={})
        ordered, ordered_value = pl.qty, pl.net_minor
        pl.qty = ordered + 100  # change order v+1
        pl.net_minor = line_amount(pl.qty, pl.unit_price_minor)
        contract_svc._consume(s, event)
        contract_svc._consume(s, event)  # idempotent: relaying twice or out of order changes nothing
        assert cl.released_qty == base_qty + 100 and cl.released_value_minor == base_value - ordered_value + pl.net_minor
        po.status = "CANCELLED"
        contract_svc._consume(s, event)
        assert cl.released_qty == base_qty - ordered and cl.released_value_minor == base_value - ordered_value
        po.status, pl.accepted_qty, pl.invoiced_qty = "CLOSED", Decimal(40), Decimal(40)  # short close: 40 delivered
        contract_svc._consume(s, event)
        assert cl.released_qty == base_qty - ordered + 40
        assert cl.released_value_minor == base_value - ordered_value + line_amount(Decimal(40), pl.unit_price_minor)
