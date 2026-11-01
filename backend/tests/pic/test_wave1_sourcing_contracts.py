"""Wave 1, engineer C1: material change requests (17, 18), multi-item and lot bidding (19), requirement bundling (20), risk constraints
(21), invitation filters (22), ESG / risk criteria (23), master agreement and NDA (24), jurisdiction templates (25), rebates (26), clause
extraction (27), supplier segmentation (28), development plans (29), responsiveness and ESG measures (30) and risk signals (31).

Every test that writes runs in one transaction that is rolled back (or cancels what it created), so the signature-case figures other
test files check never change. Times are pinned to 2029-2030, after every seeded object.
"""
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuditEvent, Bid, Capa, Clause, Contract, ContractLine, CreditNote, EventLine, IntegrationMessage, Invoice, InvoiceLine, Material,
    MaterialChangeRequest, MaterialVersion, Notification, OutboxEvent, PrLine, RebateAccrual, RiskSignal, Requisition, RuleSet, Scorecard,
    SourcingEvent, SpendLine, Supplier, SupplierSegment, Task, Tenant, Timer,
)
from app.pic.platform import clock, rules, workflow
from app.pic.platform.auth import Principal, scopes_for
from app.pic.platform.errors import Problem
from app.pic.services import clause_extract, material_changes, rebates, risk, sourcing, supplier_mgmt
from app.pic.services import contract as contract_svc

IST = clock.IST
PRICE_ONLY = [{"code": "PRICE_TCO", "name": "Price / TCO", "weight": 100}]
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


# ================================================================ 17 / 18 material change requests
def _mat_change(s, number="DC-331", changes=None, who="requester", reason="Revised planning parameters"):
    act(s, who)
    return material_changes.request_change(s, material(s, number), changes or {"description": "Aluminium die-cast cover DC-331 rev B", "safety_stock": "50"}, reason)


def test_material_change_request_goes_to_the_owning_domains_and_is_applied_with_a_version_and_one_erp_message():
    with rolled_back(at(2029, 3, 1)) as s:
        request = _mat_change(s)
        assert request.status == "IN_APPROVAL" and request.domains == ["PURCHASING", "PLANT"]
        assert {c["field"]: (c["domain"], c["routed"]) for c in request.changes} == {"description": ("PURCHASING", True), "safety_stock": ("PLANT", True)}
        assert "openPurchaseOrders" in request.impact and "contracts" in request.impact and "catalogueItems" in request.impact
        assert request.impact["infoRecords"]["count"] >= 1  # DC-331 has TF001's info record
        tasks = s.execute(select(Task).where(Task.object_id == request.id, Task.kind == "MATERIAL_CHANGE")).scalars().all()
        assert sorted(t.candidate_scope["steward_domain"] for t in tasks) == ["PLANT", "PURCHASING"]
        # one open request per material
        act(s, "buyer")
        assert problem(material_changes.request_change, s, material(s, "DC-331"), {"mpn": "X1"}, "second change").code == "CHANGE_PENDING"
        # the steward of another domain cannot work a task of a domain he does not own; the right ones approve
        act(s, "mdm.quality")
        assert problem(material_changes.decide, s, request, "APPROVE", None).code == "NOT_YOUR_TASK"
        act(s, "mdm.purchasing")
        material_changes.decide(s, request, "APPROVE", "description fine")
        assert request.status == "IN_APPROVAL" and material(s, "DC-331").version == 1
        act(s, "mdm.plant")
        material_changes.decide(s, request, "APPROVE", "stock policy ok")
        m = material(s, "DC-331")
        assert request.status == "APPLIED" and m.version == 2 and m.description.endswith("rev B") and m.safety_stock == Decimal(50)
        versions = {v.version: v for v in s.execute(select(MaterialVersion).where(MaterialVersion.material_id == m.id)).scalars()}
        assert set(versions) == {1, 2} and versions[1].snapshot["safety_stock"] != versions[2].snapshot["safety_stock"]
        assert versions[2].changed_fields == ["description", "safety_stock"] and versions[2].change_request_id == request.id
        # exactly one ERP update with the version key; the simulator posted it and the master is in sync again
        messages = s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == "MAT|DC-331|2")).scalars().all()
        assert len(messages) == 1 and messages[0].message_type == "MATERIAL_MASTER" and messages[0].status == "POSTED"
        assert messages[0].payload["change"] == request.number and messages[0].payload["version"] == 2
        assert request.erp_document == messages[0].erp_doc_no and m.erp_synced is True
        actions = {a.action for a in s.execute(select(AuditEvent).where(AuditEvent.object_id.in_([m.id, request.id]))).scalars()}
        assert {"CHANGE_REQUESTED", "CHANGE_APPLIED", "APPLIED", "SYNCED_TO_ERP"} <= actions


def test_the_requester_cannot_approve_his_own_material_change_and_a_rejection_ends_the_request():
    with rolled_back(at(2029, 3, 1)) as s:
        request = _mat_change(s, changes={"mpn": "AXN-DC-331-B"}, who="mdm.purchasing")
        p = problem(material_changes.decide, s, request, "APPROVE", None)
        assert p.code in ("SOD_CONFLICT", "NOT_YOUR_TASK") and p.status in (403, 409)
        task = s.execute(select(Task).where(Task.object_id == request.id, Task.status == "OPEN")).scalars().first()
        assert task is not None and task.candidate_scope["steward_domain"] == "PURCHASING"
        # the requester is excluded from the task (four-eyes), another purchasing steward is not required: a different domain steward rejects nothing
        assert request.requested_by in task.excluded_user_ids
        act(s, "admin")
        s.info["principal"].roles.append("MDM_STEWARD")
        s.info["principal"].attributes["steward_domains"] = ["PURCHASING"]
        workflow.complete(s, task.id, "REJECT", "mpn belongs to the old drawing")
        assert request.status == "REJECTED" and "old drawing" in request.rejection_reason
        assert material(s, "DC-331").version == 1


def test_fields_outside_the_material_type_or_identity_are_refused_and_routing_follows_the_rule():
    with rolled_back(at(2029, 3, 1)) as s:
        act(s, "requester")
        m = material(s, "DC-331")
        assert problem(material_changes.request_change, s, m, {"number": "X"}, "identity cannot change").code == "FIELD_NOT_CHANGEABLE"
        assert problem(material_changes.request_change, s, m, {"description": m.description}, "no change at all").code == "NO_CHANGES"
        assert problem(material_changes.request_change, s, m, {"gst_rate": "17"}, "not a GST slab").code == "INVALID_FIELD"
        assert problem(material_changes.request_change, s, m, {"description": "x"}, "").code == "REASON_REQUIRED"
        # a service material has no stock fields
        service = SimpleNamespace(type="SERVICE", category="ALU-DIECAST", description="d", safety_stock=0, base_uom="HR")
        p = problem(material_changes.classify, s, service, {"safety_stock": "5"}, [])
        assert p.code == "FIELD_NOT_CHANGEABLE"
        # stock materials: a unit-of-measure change also needs quality and finance, a steward of the owning domain is not routed
        stock = SimpleNamespace(type="STOCK", category="ALU-DIECAST", description="d", base_uom="EA", valuation_class=None)
        plan = material_changes.classify(s, stock, {"base_uom": "KG"}, ["PLANT"])
        assert plan["domains"] == ["QUALITY", "FINANCE", "PLANT"] or set(plan["domains"]) == {"PLANT", "QUALITY", "FINANCE"}
        assert plan["changes"][0]["routed"] is False and plan["outside"] == []
        # the tenant can refuse changes outside the requester's domains instead of routing them
        s.add(RuleSet(tenant_id=m.tenant_id, key="MATERIAL-FIELD-OWNERSHIP", version="2029.1", effective_from=date(2029, 1, 1),
                      body={**material_changes.DEFAULT_RULE, "outsideOwnership": "REFUSE"}, description="refuse"))
        s.flush()
        refused = problem(material_changes.classify, s, m, {"safety_stock": "5"}, ["PURCHASING"])
        assert refused.status == 403 and refused.code == "OUTSIDE_OWNERSHIP"
        assert material_changes.classify(s, m, {"safety_stock": "5"}, ["PLANT"])["outside"] == []


def test_a_unit_of_measure_change_is_blocked_while_the_material_has_stock():
    with rolled_back(at(2029, 3, 1)) as s:
        act(s, "mdm.plant")
        p = problem(material_changes.request_change, s, material(s, "DC-330"), {"base_uom": "KG"}, "unit mix-up fix")
        assert p.code == "IMPACT_BLOCKED" and "stock" in p.detail
        preview = material_changes.preview(s, material(s, "DC-330"), {"description": "Aluminium die-cast housing DC-330 rev C"})
        assert preview["impact"]["stockQty"] != "0" and preview["domains"] == ["PURCHASING"]


def test_material_change_api_is_idempotent_and_can_be_withdrawn(client, login):
    body = {"changes": {"mpn": "AXN-DC-331-API"}, "reason": "Drawing revision per ECN-77"}
    key = {"Idempotency-Key": "c1-mcr-1"}
    assert client.post("/v1/materials/DC-331/change-requests", json=body, headers=login("receiver")).status_code == 403
    r = client.post("/v1/materials/DC-331/change-requests", json=body, headers={**login("requester"), **key})
    assert r.status_code == 201, r.text
    again = client.post("/v1/materials/DC-331/change-requests", json=body, headers={**login("requester"), **key})
    assert again.status_code == 201 and again.json()["number"] == r.json()["number"] and again.json().get("replayed") is True
    number = r.json()["number"]
    assert client.get(f"/v1/material-change-requests/{number}", headers=login("buyer")).json()["status"] == "IN_APPROVAL"
    assert client.post("/v1/materials/DC-331/change-requests/preview", json={"changes": {"mpn": "Z"}, "reason": "preview only"},
                       headers=login("requester")).json()["domains"] == ["PURCHASING"]
    ownership = client.get("/v1/material-field-ownership?type=SERVICE", headers=login("buyer")).json()
    assert "safety_stock" not in {f["field"] for f in ownership["fields"]} and ownership["outsideOwnership"] in ("ROUTE", "REFUSE")
    assert client.post(f"/v1/material-change-requests/{number}/cancel", json={"reason": "x"}, headers=login("buyer")).status_code == 403
    done = client.post(f"/v1/material-change-requests/{number}/cancel", json={"reason": "superseded"}, headers=login("requester"))
    assert done.status_code == 200 and done.json()["status"] == "CANCELLED"
    assert client.get("/v1/materials/DC-331/versions", headers=login("buyer")).json()["version"] == 1


# ================================================================ requirements, events, bids
def _requirement(s, lines, origin="MANUAL") -> Requisition:
    """An approved requisition with one line per (material, qty) copied from the signature requirement REQ-2312."""
    base = s.execute(select(Requisition).where(Requisition.number == "REQ-2312")).scalar_one()
    base_line = s.execute(select(PrLine).where(PrLine.requisition_id == base.id, PrLine.line_no == 10)).scalar_one()
    pr = Requisition(tenant_id=base.tenant_id, number=f"REQ-C1-{uuid.uuid4().hex[:8]}", origin=origin, requester_id=base.requester_id,
                     company_code=base.company_code, plant=base.plant, status="APPROVED", total_minor=0)
    s.add(pr)
    s.flush()
    for index, (number, qty) in enumerate(lines, start=1):
        m = material(s, number)
        s.add(PrLine(tenant_id=base.tenant_id, requisition_id=pr.id, line_no=index * 10, item_type="MATERIAL", purchase_type="STOCK",
                     material_id=m.id, description=m.description, material_group=m.material_group, category=m.category,
                     qty=Decimal(qty), uom=m.base_uom, price_est_minor=40000, need_date=date(2029, 6, 1), plant=base_line.plant))
    s.flush()
    return pr


def _event(s, title, pr, lines, *, close_at=None, constraints=OPEN_SHARES, criteria=PRICE_ONLY, invitees=("TF001", "KD002"), type="RFQ", **kw):
    act(s, "category.head")
    return sourcing.create_event(
        s, type=type, title=title, category="ALU-DIECAST", lines=lines, criteria=criteria, invitees=[{"supplier": c} for c in invitees],
        close_at=close_at or at(2029, 3, 8, 17), baseline_method="LAST_PRICE", constraints=constraints, **kw)


def _l(pr, line, annual="1200", monthly="100", **kw):
    return {"requisition": pr.number, "line": line, "annual_qty": annual, "monthly_qty": monthly, **kw}


def _bl(line, price, terms=60, lead=14, cap="5000"):
    return {"line": line, "unit_price": str(price), "payment_terms_days": terms, "lead_time_days": lead, "capacity_per_month": cap}


def _bid(s, who, event, lines, lots=None):
    user = act(s, who)
    return sourcing.submit_bid(s, event, s.get(Supplier, user.supplier_id), lines, lots)


def _close(s, event, when=at(2029, 3, 8, 17, 5)):
    clock.set_pinned(when)
    act(s, "category.head")
    return sourcing.close(s, event)


def _scenarios(s, event):
    act(s, "category.head")
    return {x["kind"]: x for x in sourcing.build_scenarios(s, event)}


def _award(s, event, scenario):
    act(s, "category.head")
    decision = sourcing.propose_award(s, event, uuid.UUID(scenario["id"]), None, "No conflict of interest")
    assert event.status == "AWARDED", event.status
    return decision


def _contracts(s, event):
    for outbox_event in s.execute(select(OutboxEvent).where(OutboxEvent.topic == "sourcing.event.awarded", OutboxEvent.object_id == event.id)).scalars():
        contract_svc._from_award(s, outbox_event)
    s.flush()
    return s.execute(select(Contract).where(Contract.source_event_id == event.id).order_by(Contract.number)).scalars().all()


# ================================================================ 19 multi-item bidding
def test_an_event_has_several_lines_and_the_award_gives_each_supplier_one_contract_for_its_lines():
    with rolled_back(at(2029, 3, 1)) as s:
        pr = _requirement(s, [("DC-330", 1200), ("DC-331", 1200)])
        event = _event(s, "C1 two items", pr, [_l(pr, 10), _l(pr, 20)])
        lines = s.execute(select(EventLine).where(EventLine.event_id == event.id).order_by(EventLine.line_no)).scalars().all()
        assert [l.line_no for l in lines] == [10, 20] and all(l.baseline_price_minor for l in lines)
        # several lines: the event baseline is the annual value
        assert event.baseline_price_minor == sum(int(l.baseline_price_minor * l.annual_qty) for l in lines)
        statuses = s.execute(select(PrLine.sourcing_status).where(PrLine.requisition_id == pr.id)).scalars().all()
        assert statuses == ["IN_SOURCING", "IN_SOURCING"]
        sourcing.publish(s, event)
        _bid(s, "tf.sales", event, [_bl(10, 380), _bl(20, 200)])
        _bid(s, "kd.sales", event, [_bl(10, 400), _bl(20, 215)])
        result = _close(s, event)
        matrix = {m["supplier"]: m for m in result["matrix"]}
        assert matrix["TF001"]["complete"] and matrix["TF001"]["basis"] == "ANNUAL_VALUE" and len(matrix["TF001"]["lines"]) == 2
        assert matrix["TF001"]["tcoMinor"] < matrix["KD002"]["tcoMinor"] and result["matrix"][0]["supplier"] == "TF001"
        by_line = {l["line"]: [b["supplier"] for b in l["bids"]] for l in result["lineMatrix"]}
        assert by_line == {10: ["TF001", "KD002"], 20: ["TF001", "KD002"]}
        sc = _scenarios(s, event)
        assert set(sc) == {"LOWEST_COST", "BEST_VALUE", "CAPACITY_CONSTRAINED"} and sc["LOWEST_COST"]["feasible"] and sc["CAPACITY_CONSTRAINED"]["feasible"]
        allocation = sc["LOWEST_COST"]["allocations"]
        assert len(allocation) == 1 and allocation[0]["supplier"] == "TF001" and [l["line"] for l in allocation[0]["lines"]] == [10, 20]
        assert sc["LOWEST_COST"]["explanation"]["basis"] == "ANNUAL_VALUE" and sc["LOWEST_COST"]["annualSavingsMinor"] is not None
        _award(s, event, sc["LOWEST_COST"])
        assert set(s.execute(select(PrLine.sourcing_status).where(PrLine.requisition_id == pr.id)).scalars()) == {"SOURCED"}
        contracts = _contracts(s, event)
        assert len(contracts) == 1 and contracts[0].supplier_id == supplier(s, "TF001").id
        contract_lines = s.execute(select(ContractLine).where(ContractLine.contract_id == contracts[0].id).order_by(ContractLine.line_no)).scalars().all()
        assert [l.target_qty for l in contract_lines] == [Decimal(1200), Decimal(1200)] and contracts[0].type == "SCHEDULING_AGREEMENT"
        assert contracts[0].target_value_minor == 380 * 100 * 1200 + 200 * 100 * 1200


def test_lines_can_be_split_between_suppliers_and_partial_bids_are_ranked_below_complete_ones():
    with rolled_back(at(2029, 3, 1)) as s:
        pr = _requirement(s, [("DC-330", 1200), ("DC-331", 1200)])
        event = _event(s, "C1 split award", pr, [_l(pr, 10), _l(pr, 20)])
        sourcing.publish(s, event)
        _bid(s, "tf.sales", event, [_bl(10, 410), _bl(20, 200)])
        _bid(s, "kd.sales", event, [_bl(10, 380)])  # no price for line 20: allowed on a multi-line event
        result = _close(s, event)
        assert [m["supplier"] for m in result["matrix"]] == ["TF001", "KD002"]  # the complete bid ranks first although its total is higher
        assert result["matrix"][1]["coverage"] == {"bid": 1, "of": 2} and result["matrix"][1]["complete"] is False
        sc = _scenarios(s, event)
        by_supplier = {a["supplier"]: [l["line"] for l in a["lines"]] for a in sc["LOWEST_COST"]["allocations"]}
        assert by_supplier == {"KD002": [10], "TF001": [20]}
        assert sc["CAPACITY_CONSTRAINED"]["feasible"]
        _award(s, event, sc["LOWEST_COST"])
        contracts = _contracts(s, event)
        assert len(contracts) == 2  # one contract per awarded supplier
        for c in contracts:
            assert len(s.execute(select(ContractLine).where(ContractLine.contract_id == c.id)).scalars().all()) == 1


def test_single_line_events_still_need_a_price_for_the_line_and_multi_line_bids_are_validated():
    with rolled_back(at(2029, 3, 1)) as s:
        pr = _requirement(s, [("DC-330", 1200), ("DC-331", 1200)])
        one = _event(s, "C1 single", pr, [_l(pr, 10)])
        sourcing.publish(s, one)
        tf = supplier(s, "TF001")
        act(s, "tf.sales")
        assert problem(sourcing.submit_bid, s, one, tf, [_bl(30, 400)]).code == "INVALID_BID_LINES"
        assert "bid twice" in problem(sourcing.submit_bid, s, one, tf, [_bl(10, 400), _bl(10, 400)]).detail
        assert problem(sourcing.submit_bid, s, one, tf, [{**_bl(10, 400), "unit_price": "0"}]).code == "INVALID_BID_LINES"
        pr2 = _requirement(s, [("DC-330", 1200), ("DC-331", 1200)])
        two = _event(s, "C1 two", pr2, [_l(pr2, 10), _l(pr2, 20, annual="500", monthly="50")], constraints={**OPEN_SHARES, "require_all_lines": True})
        sourcing.publish(s, two)
        act(s, "tf.sales")
        p = problem(sourcing.submit_bid, s, two, tf, [_bl(10, 400)])
        assert p.code == "INVALID_BID_LINES" and "no bid for line" in p.detail
        assert problem(sourcing.submit_bid, s, two, tf, [_bl(10, 400), _bl(20, 200)], [{"lot": "Z", "discount_pct": "1"}]).code == "INVALID_BID_LINES"
        assert sourcing.submit_bid(s, two, tf, [_bl(10, 400), _bl(20, 200)]).status == "SEALED"


def test_the_one_item_rule_is_gone_but_malformed_events_are_still_refused():
    with rolled_back(at(2029, 3, 1)) as s:
        act(s, "category.head")
        common = dict(type="RFP", title="C1 refusals", category="ALU-DIECAST", criteria=PRICE_ONLY, invitees=[{"supplier": "TF001"}], close_at=at(2029, 3, 8, 17))

        def fresh():  # a failed create_event leaves its work in this session (the API rolls the request back), so each case has its own requirement
            return _requirement(s, [("DC-330", 1200), ("DC-331", 1200)])

        assert problem(sourcing.create_event, s, lines=[], **common).code == "INVALID_LINES"
        pr = fresh()
        assert problem(sourcing.create_event, s, lines=[_l(pr, 10), _l(pr, 10)], **common).rule_ref == "SRC-BUNDLE"  # the same requirement line twice
        pr = fresh()
        assert problem(sourcing.create_event, s, lines=[_l(pr, 10), _l(pr, 20)], **{**common, "type": "REVERSE_AUCTION"}).rule_ref == "SRC-AUCTION"
        pr = fresh()
        assert problem(sourcing.create_event, s, lines=[_l(pr, 10, lot="A"), _l(pr, 20)], **common).code == "INVALID_LOT"  # a lot of one line
        assert problem(sourcing.create_event, s, lines=[_l(pr, 10), _l(pr, 20)], should_cost_params={"x": 1}, **common).rule_ref == "SRC-SHOULDCOST"
        assert problem(sourcing.create_event, s, lines=[_l(pr, 10)], **dict(common, constraints={"max_share": "1.5"})).code == "INVALID_CONSTRAINT"
        pr = fresh()
        event = sourcing.create_event(s, lines=[_l(pr, 10), _l(pr, 20)], **common)
        assert event.bundle["eventLines"] == 2 and event.bundle["kind"] == "PR_LINES"
        assert problem(sourcing.create_event, s, lines=[_l(pr, 10), _l(pr, 20)], **common).rule_ref == "SRC-BUNDLE"  # lines already in sourcing


# ================================================================ 19 lots
def test_a_lot_is_bid_as_a_bundle_with_a_discount_and_awarded_whole_to_one_supplier():
    with rolled_back(at(2029, 3, 1)) as s:
        pr = _requirement(s, [("DC-330", 1200), ("DC-331", 1200)])
        event = _event(s, "C1 lot", pr, [_l(pr, 10, lot="a"), _l(pr, 20, lot="A")], constraints={"max_suppliers": 2, "max_share": "0.60", "min_share": "0.20"})
        sourcing.publish(s, event)
        tf = supplier(s, "TF001")
        act(s, "tf.sales")
        assert problem(sourcing.submit_bid, s, event, tf, [_bl(10, 395)], [{"lot": "A", "discount_pct": "5", "all_or_nothing": True}]).code == "INCOMPLETE_LOT"
        _bid(s, "tf.sales", event, [_bl(10, 395), _bl(20, 205)], [{"lot": "A", "discount_pct": "5", "all_or_nothing": True}])
        _bid(s, "kd.sales", event, [_bl(10, 392), _bl(20, 202)])
        result = _close(s, event)
        tf_row = next(m for m in result["matrix"] if m["supplier"] == "TF001")
        assert tf_row["lots"] == [{"lot": "A", "discountPct": "5.00", "allOrNothing": True}]
        sc = _scenarios(s, event)
        optimum = sc["CAPACITY_CONSTRAINED"]
        # without the bundle the 60 % cap forces a split; the bundle (indivisible, 5 % off) is cheaper and goes whole to TF001
        assert optimum["feasible"] and [a["supplier"] for a in optimum["allocations"]] == ["TF001"]
        assert all(l["bundle"] and l["share"] == "1.0000" for l in optimum["allocations"][0]["lines"])
        assert optimum["allocations"][0]["lines"][0]["priceMinor"] == int(39500 * 0.95)
        assert optimum["explanation"]["lots"] == [{"lot": "A", "decision": "BUNDLE", "supplierId": str(tf.id)}]
        assert sc["LOWEST_COST"]["explanation"]["lots"][0]["decision"] == "BUNDLE"


def test_an_all_or_nothing_bidder_is_not_used_for_a_split_and_the_lot_can_fall_back_to_per_line_awards():
    with rolled_back(at(2029, 3, 1)) as s:
        pr = _requirement(s, [("DC-330", 1200), ("DC-331", 1200)])
        event = _event(s, "C1 lot split", pr, [_l(pr, 10, lot="A"), _l(pr, 20, lot="A")])
        sourcing.publish(s, event)
        _bid(s, "tf.sales", event, [_bl(10, 420), _bl(20, 230)], [{"lot": "A", "discount_pct": "0", "all_or_nothing": True}])  # dear, whole lot only
        _bid(s, "kd.sales", event, [_bl(10, 390), _bl(20, 215)])
        _close(s, event)
        sc = _scenarios(s, event)
        for kind in ("LOWEST_COST", "CAPACITY_CONSTRAINED"):
            assert [a["supplier"] for a in sc[kind]["allocations"]] == ["KD002"], kind
        decisions = sc["CAPACITY_CONSTRAINED"]["explanation"]["lots"]
        assert decisions and decisions[0]["decision"] in ("SPLIT", "BUNDLE")


# ================================================================ 20 requirement bundling
def test_bundle_candidates_and_preview_merge_requirement_lines_of_one_material():
    with rolled_back(at(2029, 3, 1)) as s:
        mrp = _requirement(s, [("DC-330", 500), ("DC-331", 300)], origin="MRP")
        manual = _requirement(s, [("DC-330", 700)])
        act(s, "category.head")
        candidates = sourcing.bundle_candidates(s, origin="MRP", category="ALU-DIECAST")
        assert {(i["requisition"], i["line"]) for i in candidates["items"]} >= {(mrp.number, 10), (mrp.number, 20)}
        assert all(i["origin"] == "MRP" for i in candidates["items"]) and manual.number not in {i["requisition"] for i in candidates["items"]}
        preview = sourcing.bundle_preview(s, [{"requisition": mrp.number, "line": 10}, {"requisition": manual.number, "line": 10},
                                              {"requisition": mrp.number, "line": 20}], kind="PR_LINES")
        merged = next(l for l in preview["lines"] if l["materialId"] == str(material(s, "DC-330").id))
        assert Decimal(merged["qty"]) == 1200 and len(merged["sources"]) == 2 and len(preview["lines"]) == 2
        assert preview["category"] == "ALU-DIECAST" and preview["warnings"] == []
        mixed = sourcing.bundle_preview(s, [{"requisition": mrp.number, "line": 10}, {"requisition": manual.number, "line": 10}], kind="MRP_DEMAND")
        assert any("MRP" in w for w in mixed["warnings"])
        # the proposal becomes an event: both requirement lines of the merged line move into sourcing and come back on cancel
        event = _event(s, "C1 bundle", mrp, [{"sources": merged["sources"], "annual_qty": "1200", "monthly_qty": "100"},
                                              {"requisition": mrp.number, "line": 20, "annual_qty": "300", "monthly_qty": "25"}],
                       bundle={"kind": "PR_LINES", "ref": None})
        assert event.bundle["sourceLines"] == 3 and event.bundle["requisitions"] == [mrp.number, manual.number]
        assert set(s.execute(select(PrLine.sourcing_status).where(PrLine.requisition_id.in_([mrp.id, manual.id]))).scalars()) == {"IN_SOURCING"}
        assert problem(sourcing.create_event, s, type="RFQ", title="again", category="ALU-DIECAST", lines=[{"requisition": manual.number, "line": 10,
                       "annual_qty": "1", "monthly_qty": "1"}, _l(mrp, 20)], criteria=PRICE_ONLY, invitees=[{"supplier": "TF001"}],
                       close_at=at(2029, 3, 8, 17)).rule_ref == "SRC-BUNDLE"
        sourcing.cancel(s, event, "bundle was wrong")
        assert set(s.execute(select(PrLine.sourcing_status).where(PrLine.requisition_id.in_([mrp.id, manual.id]))).scalars()) == {"OPEN"}
        wrong = problem(sourcing.create_event, s, type="RFQ", title="mrp only", category="ALU-DIECAST", lines=[_l(manual, 10)], criteria=PRICE_ONLY,
                        invitees=[{"supplier": "TF001"}], close_at=at(2029, 3, 8, 17), bundle={"kind": "MRP_DEMAND"})
        assert wrong.rule_ref == "SRC-BUNDLE"


def test_a_bundle_award_closes_every_merged_requirement_line():
    with rolled_back(at(2029, 3, 1)) as s:
        a = _requirement(s, [("DC-330", 500)])
        b = _requirement(s, [("DC-330", 700)])
        event = _event(s, "C1 merged award", a, [{"sources": [{"requisition": a.number, "line": 10}, {"requisition": b.number, "line": 10}],
                                                  "annual_qty": "1200", "monthly_qty": "100"}], bundle={"kind": "PR_LINES"})
        sourcing.publish(s, event)
        _bid(s, "tf.sales", event, [_bl(10, 380)])
        _bid(s, "kd.sales", event, [_bl(10, 390)])
        _close(s, event)
        sc = _scenarios(s, event)
        _award(s, event, sc["LOWEST_COST"])
        assert set(s.execute(select(PrLine.sourcing_status).where(PrLine.requisition_id.in_([a.id, b.id]))).scalars()) == {"SOURCED"}


# ================================================================ 21 risk constraints
def test_single_source_cap_and_risk_score_cap_shape_the_scenarios_with_an_explanation():
    with rolled_back(at(2029, 3, 1)) as s:
        pr = _requirement(s, [("DC-330", 1200)])
        event = _event(s, "C1 risk caps", pr, [_l(pr, 10)], constraints={**OPEN_SHARES, "max_single_source_pct": 60})
        sourcing.publish(s, event)
        _bid(s, "tf.sales", event, [_bl(10, 380)])
        _bid(s, "kd.sales", event, [_bl(10, 390)])
        _close(s, event)
        sc = _scenarios(s, event)
        # all volume to the cheapest supplier breaks the 60 % cap; the optimiser splits 60 / 40
        assert sc["LOWEST_COST"]["feasible"] is False
        failed = [c for c in sc["LOWEST_COST"]["explanation"]["risk"]["checks"] if not c["ok"]]
        assert failed and failed[0]["rule"] == "max_single_source_pct"
        split = {a["supplier"]: Decimal(a["share"]) for a in sc["CAPACITY_CONSTRAINED"]["allocations"]}
        assert sc["CAPACITY_CONSTRAINED"]["feasible"] and split == {"TF001": Decimal("0.6"), "KD002": Decimal("0.4")}


def test_a_supplier_above_the_risk_cap_or_blocked_is_left_out_of_every_scenario():
    with rolled_back(at(2029, 3, 1)) as s:
        pr = _requirement(s, [("DC-330", 1200), ("DC-331", 1200)])
        event = _event(s, "C1 risk exclusion", pr, [_l(pr, 10), _l(pr, 20)], constraints={**OPEN_SHARES, "max_risk_score": 20})
        sourcing.publish(s, event)
        _bid(s, "tf.sales", event, [_bl(10, 380), _bl(20, 200)])
        _bid(s, "kd.sales", event, [_bl(10, 390), _bl(20, 210)])
        _close(s, event)
        tf = supplier(s, "TF001")
        s.add(RiskSignal(tenant_id=tf.tenant_id, supplier_id=tf.id, dedup_key="c1-test-critical", category="COMPLIANCE", severity="Critical",
                         source="TEST", title="test signal", detail={}, status="OPEN", detected_at=clock.now()))
        s.flush()
        assert risk.supplier_risk_score(s, tf)["score"] >= 40
        sc = _scenarios(s, event)
        for kind, scenario in sc.items():
            assert {a["supplier"] for a in scenario["allocations"]} == {"KD002"}, kind
        excluded = sc["LOWEST_COST"]["explanation"]["risk"]["excluded"]
        assert excluded and "TF001" in excluded[0]["reason"] and "risk score" in excluded[0]["reason"]


def test_conditional_suppliers_are_capped_by_value_share():
    rows = [{"supplier": "TF001", "supplierId": "a", "tcoMinor": 100, "priceMinor": 100, "verifiedCapacityPerMonth": None, "conditional": True},
            {"supplier": "KD002", "supplierId": "b", "tcoMinor": 120, "priceMinor": 120, "verifiedCapacityPerMonth": None, "conditional": False}]
    best = sourcing._optimise(rows, Decimal(100), {"max_suppliers": 2, "max_share": "1", "min_share": "0", "max_conditional_share_pct": 25})
    assert {r["supplier"]: s for r, s in best["allocations"]} == {"TF001": Decimal("0.25"), "KD002": Decimal("0.75")}
    info = {"a": {"supplier": "TF001", "conditional": True}, "b": {"supplier": "KD002", "conditional": False}}
    checks = sourcing._share_checks({"a": Decimal(50), "b": Decimal(50)}, info, {"max_conditional_share_pct": 25, "max_single_source_pct": 60})
    assert {c["rule"]: c["ok"] for c in checks} == {"max_single_source_pct": True, "max_conditional_share_pct": False}


# ================================================================ 22 invitation filters
def test_invitee_candidates_are_filtered_by_segment_and_risk():
    with rolled_back(at(2029, 3, 1)) as s:
        act(s, "category.head")
        tf, kd = supplier(s, "TF001"), supplier(s, "KD002")
        tf.segment, kd.segment = "STRATEGIC", "LEVERAGE"
        s.add(RiskSignal(tenant_id=kd.tenant_id, supplier_id=kd.id, dedup_key="c1-high", category="DELIVERY", severity="High", source="TEST",
                         title="late", detail={}, status="OPEN", detected_at=clock.now()))
        s.flush()
        everyone = {c["code"]: c for c in sourcing.invitee_candidates(s, "ALU-DIECAST")["candidates"]}
        assert {"TF001", "KD002"} <= set(everyone) and everyone["TF001"]["segment"] == "STRATEGIC" and everyone["KD002"]["riskScore"] >= 25
        strategic = sourcing.invitee_candidates(s, "ALU-DIECAST", segment="STRATEGIC")
        assert "TF001" in [c["code"] for c in strategic["candidates"]] and "KD002" not in [c["code"] for c in strategic["candidates"]]
        assert strategic["hiddenByFilter"]["segment"] >= 1
        calm = sourcing.invitee_candidates(s, "ALU-DIECAST", max_risk_score=10)
        assert "KD002" not in {c["code"] for c in calm["candidates"]} and calm["hiddenByFilter"]["risk"] >= 1
        assert "KD002" not in {c["code"] for c in sourcing.invitee_candidates(s, "ALU-DIECAST", exclude_signal_categories=["delivery"])["candidates"]}
        assert problem(sourcing.invitee_candidates, s, "ALU-DIECAST", segment="NOPE").code == "INVALID_FILTER"


def test_invitee_candidate_api(client, login):
    r = client.get("/v1/sourcing/invitee-candidates?category=ALU-DIECAST&maxRisk=100&status=QUALIFIED,PREFERRED", headers=login("category.head"))
    assert r.status_code == 200 and r.json()["candidates"] and {"segment", "riskScore", "status"} <= set(r.json()["candidates"][0])
    assert client.get("/v1/sourcing/invitee-candidates?category=ALU-DIECAST", headers=login("tf.sales")).status_code == 403


# ================================================================ 23 ESG and risk criteria
def _esg_answers(value="YES"):
    return {q["id"]: value for q in supplier_mgmt.ESG_QUESTIONS}


def test_esg_and_risk_criteria_take_their_scores_from_platform_data_and_are_frozen_at_close():
    criteria = [{"code": "PRICE_TCO", "name": "Price", "weight": 60}, {"code": "ESG", "name": "ESG", "weight": 20, "data_source": "ESG"},
                {"code": "RISK", "name": "Risk", "weight": 20, "data_source": "RISK"}]
    with rolled_back(at(2029, 3, 1)) as s:
        pr = _requirement(s, [("DC-330", 1200)])
        act(s, "category.head")
        for bad in ({"code": "PRICE_TCO", "name": "x", "weight": 100, "data_source": "ESG"}, {"code": "ESG", "name": "x", "weight": 100, "data_source": "RISK"}):
            assert problem(sourcing.create_event, s, type="RFQ", title="bad", category="ALU-DIECAST", lines=[_l(pr, 10)], criteria=[bad],
                           invitees=[{"supplier": "TF001"}], close_at=at(2029, 3, 8, 17)).code == "INVALID_CRITERION"
        # TF001 submits a full ESG questionnaire; supplier management accepts it
        tf = supplier(s, "TF001")
        act(s, "tf.sales")
        item = supplier_mgmt.submit_assessment(s, tf, "ESG", _esg_answers("YES"), date(2029, 2, 20))
        assert item.status == "SUBMITTED" and Decimal(item.score) < 100  # YES to certified systems without a valid certificate counts half
        act(s, "supplier.manager")
        supplier_mgmt.review_assessment(s, item, True, "reviewed")
        assert item.status == "ACCEPTED" and item.expires_on == date(2029, 2, 20) + timedelta(days=365)
        event = _event(s, "C1 criteria", pr, [_l(pr, 10)], criteria=criteria)
        sourcing.publish(s, event)
        _bid(s, "tf.sales", event, [_bl(10, 390)])
        _bid(s, "kd.sales", event, [_bl(10, 390)])
        result = _close(s, event)
        rows = {m["supplier"]: m for m in result["matrix"]}
        assert rows["TF001"]["autoScores"]["ESG"]["score"] == str(item.score.quantize(Decimal("0.01"))) and rows["TF001"]["autoScores"]["ESG"]["noData"] is False
        assert rows["KD002"]["autoScores"]["ESG"]["noData"] is True and rows["KD002"]["scores"]["ESG"] == "50.00"  # no assessment: the neutral score
        assert rows["TF001"]["scores"]["RISK"] == str(Decimal(100 - risk.supplier_risk_score(s, tf)["score"]).quantize(Decimal("0.01")))
        assert Decimal(rows["TF001"]["weightedScore"]) > Decimal(rows["KD002"]["weightedScore"])
        # a new signal after close does not move the evaluated score; evaluators cannot score a data-driven criterion
        s.add(RiskSignal(tenant_id=tf.tenant_id, supplier_id=tf.id, dedup_key="c1-later", category="DELIVERY", severity="Critical", source="TEST",
                         title="later", detail={}, status="OPEN", detected_at=clock.now()))
        s.flush()
        again = {m["supplier"]: m for m in sourcing.evaluation_matrix(s, event)}
        assert again["TF001"]["scores"]["RISK"] == rows["TF001"]["scores"]["RISK"]
        act(s, "category.head")
        assert problem(sourcing.score, s, event, [{"supplier": "TF001", "criterion": "ESG", "score": 90}]).code == "INVALID_CRITERION"


# ================================================================ 24 / 25 master agreements, NDAs, jurisdictions
def _draft(s, type, *, supplier_code="TF001", lines=None, **kw):
    act(s, "contract.manager")
    sup = supplier(s, supplier_code)
    defaults = dict(type=type, title=f"C1 {type}", supplier_id=sup.id, company_code="1000", valid_from=date(2029, 4, 1), valid_to=date(2030, 3, 31),
                    payment_terms="N60", incoterms="FCA", lines=lines or [], owner_id=s.info["user_id"], tolerances={"over_pct": "2", "under_pct": "5", "price_pct": "0"})
    return contract_svc.create_draft(s, **{**defaults, **kw})


CALL_OFF_LINE = {"material_id": None, "description": "Service hours", "plant": "P100", "uom": "HR", "target_qty": "100", "unit_price_minor": 150000}


def test_master_agreement_and_nda_carry_no_value_and_call_offs_refer_to_a_live_framework():
    with rolled_back(at(2029, 3, 1)) as s:
        master = _draft(s, "MASTER_AGREEMENT")
        nda = _draft(s, "NDA", supplier_code="KD002")
        assert master.target_value_minor == 0 and nda.target_value_minor == 0
        assert not s.execute(select(ContractLine).where(ContractLine.contract_id.in_([master.id, nda.id]))).scalars().all()
        codes = {c.code for c in s.execute(select(Clause).where(Clause.contract_id == master.id)).scalars()}
        assert {"SCOPE", "LIABILITY", "TERMINATION"} <= codes
        assert {c.code for c in s.execute(select(Clause).where(Clause.contract_id == nda.id)).scalars()} >= {"DEFINITION", "TERM"}
        assert problem(_draft, s, "MASTER_AGREEMENT", lines=[CALL_OFF_LINE]).rule_ref == "CLM-FRAMEWORK"
        assert problem(_draft, s, "NDA", framework_contract_id=master.id).rule_ref == "CLM-FRAMEWORK"
        assert problem(_draft, s, "VALUE_CONTRACT", lines=[]).code == "LINES_REQUIRED"
        # a draft master agreement cannot be referenced; once active it can, within its validity and for the same supplier
        assert problem(_draft, s, "VALUE_CONTRACT", lines=[CALL_OFF_LINE], framework_contract_id=master.id).rule_ref == "CLM-FRAMEWORK"
        master.status = "ACTIVE"
        call_off = _draft(s, "VALUE_CONTRACT", lines=[CALL_OFF_LINE], framework_contract_id=master.id, valid_from=date(2029, 6, 1), valid_to=date(2030, 3, 31))
        assert call_off.framework_contract_id == master.id and call_off.target_value_minor == 100 * 150000
        assert problem(_draft, s, "VALUE_CONTRACT", lines=[CALL_OFF_LINE], framework_contract_id=master.id, valid_to=date(2031, 3, 31)).rule_ref == "CLM-FRAMEWORK"
        assert problem(_draft, s, "VALUE_CONTRACT", supplier_code="KD002", lines=[CALL_OFF_LINE], framework_contract_id=master.id).rule_ref == "CLM-FRAMEWORK"
        assert contract_svc.active_framework(s, master.supplier_id, "1000", date(2029, 6, 1), date(2030, 3, 31)).id == master.id
        # the approval of a value-free framework goes the low-value route; it has nothing to consume
        master.status = "DRAFT"
        contract_svc.ai_review(s, master)
        assert contract_svc.submit(s, master)["chain"] == ["CONTRACT_MANAGER"]
        assert contract_svc.consumption(s, master)["lines"] == []


def test_a_master_agreement_with_live_call_offs_cannot_be_terminated():
    from app.pic.services import amendments

    with rolled_back(at(2029, 3, 1)) as s:
        master = _draft(s, "MASTER_AGREEMENT")
        master.status = "ACTIVE"
        call_off = _draft(s, "VALUE_CONTRACT", lines=[CALL_OFF_LINE], framework_contract_id=master.id, valid_from=date(2029, 6, 1))
        call_off.status = "ACTIVE"
        s.flush()
        p = problem(amendments.plan, s, master, "TERMINATION", {"forCause": True}, date(2029, 3, 5))
        assert p.rule_ref == "CLM-FRAMEWORK" and call_off.number in p.detail
        call_off.status = "TERMINATED"
        s.flush()
        assert amendments.plan(s, master, "TERMINATION", {"forCause": True}, date(2029, 3, 5))["kind"] == "TERMINATION"
        # a call-off cannot be activated once its framework ended
        master.status = "TERMINATED"
        call_off.status = "OUT_FOR_SIGNATURE"
        s.flush()
        assert problem(contract_svc.activate, s, call_off).rule_ref == "CLM-FRAMEWORK"


def test_clause_library_variants_follow_the_governing_law():
    with rolled_back(at(2029, 3, 1)) as s:
        mh = _draft(s, "VALUE_CONTRACT", lines=[CALL_OFF_LINE], jurisdiction="in-mh")
        clauses = {c.code: c for c in s.execute(select(Clause).where(Clause.contract_id == mh.id)).scalars()}
        assert mh.jurisdiction == "IN-MH" and "Mumbai" in clauses["GOVERNING_LAW"].text and "Maharashtra Stamp Act" in clauses["STAMP_DUTY"].text
        assert {"DISPUTES", "DATA_PROTECTION", "PAYMENT"} <= set(clauses)
        ka = _draft(s, "VALUE_CONTRACT", lines=[CALL_OFF_LINE], jurisdiction="IN-KA")
        assert "Bengaluru" in next(c.text for c in s.execute(select(Clause).where(Clause.contract_id == ka.id, Clause.code == "DISPUTES")).scalars())
        plain = _draft(s, "VALUE_CONTRACT", lines=[CALL_OFF_LINE])
        assert not s.execute(select(Clause).where(Clause.contract_id == plain.id, Clause.code == "GOVERNING_LAW")).scalars().all()
        assert problem(_draft, s, "VALUE_CONTRACT", lines=[CALL_OFF_LINE], jurisdiction="ZZ").code == "UNKNOWN_JURISDICTION"
        library = contract_svc.templates(s, "SG")
        assert library["jurisdictionClauses"][0]["text"].startswith("This contract is governed by the laws of Singapore")
        assert {"NDA", "MASTER_AGREEMENT"} <= set(library["types"]) and any(j["code"] == "IN-TN" for j in library["jurisdictions"])


def test_contract_api_accepts_the_new_types_and_jurisdictions(client, login):
    h = login("contract.manager")
    body = {"type": "NDA", "title": "C1 API NDA", "supplier": "SLA003", "valid_from": "2030-01-01", "valid_to": "2031-12-31", "payment_terms": "N30"}
    r = client.post("/v1/contracts", json=body, headers={**h, "Idempotency-Key": "c1-nda-1"})
    assert r.status_code == 201, r.text
    assert client.post("/v1/contracts", json={**body, "type": "VALUE_CONTRACT"}, headers=h).json()["code"] == "LINES_REQUIRED"
    assert client.post("/v1/contracts", json={**body, "jurisdiction": "in-mh"}, headers=h).status_code == 422  # pattern is upper case
    ok = client.post("/v1/contracts", json={**body, "title": "C1 API NDA 2", "jurisdiction": "IN-DL"}, headers=h)
    assert ok.status_code == 201
    view = client.get(f"/v1/contracts/{ok.json()['number']}", headers=h).json()
    assert view["jurisdiction"] == "IN-DL" and any(c["code"] == "GOVERNING_LAW" and "New Delhi" in c["text"] for c in view["clauses"])
    framework = client.get(f"/v1/contracts/{ok.json()['number']}/framework", headers=h).json()
    assert framework["framework"] is None and framework["callOffs"] == []
    assert client.get("/v1/contract-templates?jurisdiction=IN-GJ", headers=login("buyer")).json()["jurisdictionClauses"][0]["code"] == "GOVERNING_LAW"
    assert client.post("/v1/contracts", json=body, headers=login("buyer")).status_code == 403


# ================================================================ 26 rebates
def test_rebate_tiers_apply_retroactively_or_by_slab_and_periods_follow_the_fiscal_year():
    agreement = SimpleNamespace(tier_mode="RETROACTIVE", basis="VALUE", tiers=[{"from": "0", "ratePct": "1"}, {"from": "1000000", "ratePct": "2"},
                                                                           {"from": "2000000", "ratePct": "3"}])
    amount, rate, _ = rebates.rebate_for(agreement, 1_500_000 * 100, Decimal(0))
    assert (amount, rate) == (30_000_00, Decimal("2.000"))  # the 2 % tier applies to the whole 15 lakh
    agreement.tier_mode = "SLAB"
    amount, rate, working = rebates.rebate_for(agreement, 2_500_000 * 100, Decimal(0))
    assert amount == (1_000_000 * 1 + 1_000_000 * 2 + 500_000 * 3) // 100 * 100 and len(working) == 3
    volume = SimpleNamespace(tier_mode="RETROACTIVE", basis="VOLUME", tiers=[{"from": "1000", "ratePct": "1.5"}])
    assert rebates.rebate_for(volume, 5_000_000, Decimal(999))[0] == 0 and rebates.rebate_for(volume, 5_000_000, Decimal(1000))[0] == 75_000
    assert rebates.period_of("QUARTERLY", date(2029, 5, 20)) == ("FY2029-30-Q1", date(2029, 4, 1), date(2029, 6, 30))
    assert rebates.period_of("QUARTERLY", date(2029, 2, 1))[0] == "FY2028-29-Q4" and rebates.period_of("QUARTERLY", date(2029, 2, 1))[2] == date(2029, 3, 31)
    assert rebates.period_of("ANNUAL", date(2029, 3, 31))[0] == "FY2028-29" and rebates.period_of("MONTHLY", date(2029, 12, 5))[2] == date(2029, 12, 31)
    assert problem(rebates._tiers, [{"from": "10", "ratePct": "2"}, {"from": "5", "ratePct": "3"}], "VALUE").code == "INVALID_TIERS"
    assert problem(rebates._tiers, [{"from": "0", "ratePct": "3"}, {"from": "5", "ratePct": "2"}], "VALUE").code == "INVALID_TIERS"


def _posted_invoice(s, sup, number, day, net, qty=10):
    inv = Invoice(tenant_id=sup.tenant_id, number=number, supplier_invoice_no=number, fiscal_year="2029-30", company_code="1000", supplier_id=sup.id,
                  invoice_date=day, channel="PORTAL", net_minor=net, tax_minor=0, gross_minor=net, status="POSTED")
    s.add(inv)
    s.flush()
    line = InvoiceLine(tenant_id=sup.tenant_id, invoice_id=inv.id, line_no=1, description="goods", qty=Decimal(qty), unit_price_minor=net // qty,
                       net_minor=net, gst_rate=Decimal(0), tax_minor=0)
    s.add(line)
    s.flush()
    return inv


def test_rebate_accrues_from_posted_invoices_net_of_credit_notes_and_settles_once_as_a_credit_memo():
    with rolled_back(at(2029, 5, 20)) as s:
        master = _draft(s, "MASTER_AGREEMENT")
        tf = supplier(s, "TF001")
        agreement = rebates.create_agreement(s, master if False else _draft(s, "VALUE_CONTRACT", lines=[CALL_OFF_LINE]), title="Quarterly value rebate", basis="VALUE",
                                              period="QUARTERLY", tiers=[{"from": "500000", "ratePct": "1"}, {"from": "1000000", "ratePct": "2"}],
                                              scope="SUPPLIER", valid_from=date(2029, 4, 1), valid_to=date(2030, 3, 31))
        assert agreement.number.startswith("RBA-") and problem(rebates.create_agreement, s, master, title="x", basis="VALUE", period="MONTHLY",
                                                              tiers=[{"from": "1", "ratePct": "1"}], scope="CONTRACT").rule_ref == "CLM-REBATE"
        i1 = _posted_invoice(s, tf, "C1-INV-1", date(2029, 4, 10), 800_000 * 100)
        _posted_invoice(s, tf, "C1-INV-2", date(2029, 6, 5), 400_000 * 100)
        _posted_invoice(s, tf, "C1-INV-OUT", date(2029, 7, 5), 900_000 * 100)  # next quarter
        accrual = rebates.accrue(s, agreement, date(2029, 5, 20))
        assert accrual.period_label == "FY2029-30-Q1" and accrual.basis_value_minor == 1_200_000 * 100
        assert accrual.accrued_minor == 24_000 * 100 and accrual.rate_pct == Decimal("2.000")  # 2 % tier reached: 12 lakh x 2 %
        # a credit note of 3 lakh (10 units at the invoice price = full line is 8 lakh; credit 3 units at 80,000) lowers the basis below the 2 % tier
        s.add(CreditNote(tenant_id=tf.tenant_id, number="C1-CN-1", supplier_credit_note_no="C1-CN-1", supplier_id=tf.id, invoice_id=i1.id,
                         note_date=date(2029, 5, 1), reason="rejected lot", net_minor=320_000 * 100, tax_minor=0, gross_minor=320_000 * 100,
                         lines=[{"invoice_line": 1, "qty": "4"}]))
        s.flush()
        accrual = rebates.accrue(s, agreement, date(2029, 5, 20))
        assert accrual.basis_value_minor == 880_000 * 100 and accrual.accrued_minor == 8_800 * 100 and accrual.rate_pct == Decimal("1.000")
        # settlement: only after the period, only finance or the contract manager, once
        act(s, "finance.controller")
        assert problem(rebates.settle, s, accrual).rule_ref == "CLM-REBATE"  # the period has not ended
        clock.set_pinned(at(2029, 7, 10))
        act(s, "buyer")
        assert problem(rebates.settle, s, accrual).status == 403
        act(s, "finance.controller")
        settlement = rebates.settle(s, accrual)
        assert settlement.amount_minor == 8_800 * 100 and settlement.status == "POSTED" and settlement.erp_document and accrual.status == "SETTLED"
        message = s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == f"REBATE|{agreement.number}|FY2029-30-Q1")).scalar_one()
        assert message.message_type == "SUPPLIER_CREDIT_MEMO" and message.payload["grossMinor"] == 8_800 * 100 and message.status == "POSTED"
        assert problem(rebates.settle, s, accrual).code == "ILLEGAL_TRANSITION"
        assert s.execute(select(OutboxEvent).where(OutboxEvent.topic == "rebate.settled", OutboxEvent.object_id == settlement.id)).scalar_one()
        # a settled period is not recomputed, and an agreement with an unsettled accrual cannot be cancelled
        assert rebates.accrue(s, agreement, date(2029, 5, 20)).accrued_minor == 8_800 * 100
        _posted_invoice(s, tf, "C1-INV-3", date(2029, 7, 6), 700_000 * 100)
        rebates.accrue(s, agreement, date(2029, 7, 10))
        assert problem(rebates.cancel_agreement, s, agreement, "no longer needed").rule_ref == "CLM-REBATE"
        view = rebates.agreement_view(s, agreement)
        assert view["settledMinor"] == 8_800 * 100 and len(view["accruals"]) == 2


def test_rebate_api_creates_accrues_and_enforces_roles(client, login):
    h = login("contract.manager")
    with tenant_tx(_tid()) as s:
        number, last_day = s.execute(select(Contract.number, Contract.valid_to).where(Contract.type == "SCHEDULING_AGREEMENT")
                                     .order_by(Contract.number)).first()
    # the agreement covers only the contract's last day, so it has no purchases yet and can be cancelled again at the end of the test
    body = {"title": "API volume rebate", "basis": "VOLUME", "period": "ANNUAL", "tier_mode": "SLAB", "valid_from": last_day.isoformat(),
            "valid_to": last_day.isoformat(), "tiers": [{"from": "1000", "ratePct": "1"}, {"from": "5000", "ratePct": "2"}], "scope": "CONTRACT"}
    assert client.post(f"/v1/contracts/{number}/rebates", json=body, headers=login("buyer")).status_code == 403
    assert client.post(f"/v1/contracts/{number}/rebates", json={**body, "tiers": []}, headers=h).status_code == 422
    r = client.post(f"/v1/contracts/{number}/rebates", json=body, headers={**h, "Idempotency-Key": "c1-reb-1"})
    assert r.status_code == 201, r.text
    again = client.post(f"/v1/contracts/{number}/rebates", json=body, headers={**h, "Idempotency-Key": "c1-reb-1"})
    assert again.json()["number"] == r.json()["number"]
    rebate = r.json()
    assert rebate["basis"] == "VOLUME" and rebate["tiers"][0]["from"] == "1000" and rebate["tier_mode"] == "SLAB"
    accrued = client.post(f"/v1/rebates/{rebate['number']}/accrue?on={last_day.isoformat()}", headers=h)
    assert accrued.status_code == 200 and accrued.json()["accruals"][0]["status"] == "OPEN" and accrued.json()["accruals"][0]["accrued_minor"] == 0
    assert client.post(f"/v1/rebates/{rebate['number']}/accrue?on={(last_day + timedelta(days=400)).isoformat()}", headers=h).status_code == 200
    assert client.get(f"/v1/contracts/{number}/rebates", headers=login("buyer")).json()[0]["number"] == rebate["number"]
    cancelled = client.post(f"/v1/rebates/{rebate['number']}/cancel", json={"reason": "test clean-up"}, headers=h)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"


# ================================================================ 27 clause extraction
CONTRACT_TEXT = """SUPPLY AGREEMENT
This agreement is made between Axion Mobility Systems Pvt Ltd (hereinafter the Buyer) and Trichy Forge Pvt Ltd (hereinafter the Supplier),
effective from 1 April 2029 and valid until 31 March 2030. The agreement shall automatically renew for one year unless terminated.

1. PAYMENT TERMS
The Buyer shall pay each correct invoice within 60 days of receipt of the invoice.

2. PRICE ADJUSTMENT
Prices follow the LME aluminium index, reset quarterly.

3. LIMITATION OF LIABILITY
The aggregate liability of the Supplier is limited to 100% of the annual contract value.

4. TERMINATION
Either party may terminate this agreement by giving 90 days' written notice.

5. GOVERNING LAW AND ARBITRATION
This agreement is governed by the laws of India. Disputes are referred to arbitration under the Arbitration and Conciliation Act, 1996; the seat of arbitration shall be Mumbai.

6. MISCELLANEOUS
The parties may sign in counterparts and the schedule of drawings is attached.
"""


def test_extractor_reads_clauses_attributes_and_playbook_positions_from_contract_text():
    result = clause_extract.extract(CONTRACT_TEXT, {"positionRisk": {"STANDARD": 0, "FALLBACK": 30, "NON_STANDARD": 70}, "templates": {}})
    items = {i["code"]: i for i in result["items"]}
    assert {"PAYMENT", "PRICE_INDEX", "LIABILITY", "TERMINATION"} <= set(items) and {"GOVERNING_LAW", "DISPUTES"} & set(items)
    assert items["PAYMENT"]["attributes"] == {"paymentDays": 60, "paymentTerms": "N60"} and items["PAYMENT"]["position"] == "STANDARD"
    assert items["LIABILITY"]["attributes"]["liabilityCapPct"] == 100.0 and items["LIABILITY"]["position"] == "STANDARD"
    assert items["TERMINATION"]["attributes"]["noticeDays"] == 90
    law = items.get("GOVERNING_LAW") or items["DISPUTES"]  # one block carries both: the better heading match wins
    assert law["attributes"]["jurisdiction"] == "IN-MH" and law["position"] == "STANDARD"
    assert all(0 < i["confidence"] <= 0.98 for i in result["items"]) and items["LIABILITY"]["confidence"] > 0.6
    assert result["attributes"]["validFrom"] == "2029-04-01" and result["attributes"]["validTo"] == "2030-03-31" and result["attributes"]["autoRenewal"] is True
    assert result["attributes"]["parties"][0].startswith("Axion Mobility")
    assert any("MISCELLANEOUS" in (u["heading"] or "").upper() for u in result["unmatched"])  # nothing in the library fits: left for the reviewer
    weak = clause_extract.extract("LIABILITY\nThe Supplier's liability is unlimited for all losses.\n\nTERMINATION\nEither party may terminate on 15 days' notice.\n"
                                  "\nPAYMENT\nInvoices are payable within 30 days.", {"positionRisk": {"STANDARD": 0, "FALLBACK": 30, "NON_STANDARD": 70}, "templates": {}})
    positions = {i["code"]: (i["position"], i["risk"]) for i in weak["items"]}
    assert positions == {"LIABILITY": ("NON_STANDARD", 70), "TERMINATION": ("NON_STANDARD", 70), "PAYMENT": ("NON_STANDARD", 70)}
    assert problem(clause_extract.extract, "   ").code == "TEXT_REQUIRED"


def test_extraction_is_reviewed_by_a_person_before_the_clauses_reach_the_contract():
    with rolled_back(at(2029, 3, 1)) as s:
        contract = _draft(s, "VALUE_CONTRACT", lines=[CALL_OFF_LINE], payment_terms="N45", valid_to=date(2030, 3, 30))
        act(s, "contract.manager")
        extraction = clause_extract.create_extraction(s, contract_ref=contract.number, text=CONTRACT_TEXT, source_name="signed.pdf")
        assert extraction.number.startswith("CLX-") and extraction.status == "EXTRACTED"
        assert clause_extract.create_extraction(s, contract_ref=contract.number, text=CONTRACT_TEXT, source_name="again.pdf").id == extraction.id
        fields = {d["field"] for d in extraction.attributes["discrepancies"]}
        assert {"paymentTerms", "validTo"} <= fields  # the document says N60 and 31 March 2030
        act(s, "buyer")
        assert problem(clause_extract.review, s, extraction, [{"seq": 1, "action": "ACCEPT"}]).status == 403
        act(s, "contract.manager")
        assert problem(clause_extract.apply, s, extraction).code == "ILLEGAL_TRANSITION"  # not reviewed yet
        decisions = [{"seq": i["seq"], "action": "ACCEPT"} for i in extraction.items]
        decisions[0] = {"seq": extraction.items[0]["seq"], "action": "EDIT", "text": "Payment within 60 days of a correct invoice.", "position": "FALLBACK"}
        rejected = next(i for i in extraction.items if i["code"] == "PRICE_INDEX")
        decisions = [{"seq": rejected["seq"], "action": "REJECT"} if d["seq"] == rejected["seq"] else d for d in decisions]
        clause_extract.review(s, extraction, decisions)
        assert extraction.status == "REVIEWED"
        before = {c.code: c.text for c in s.execute(select(Clause).where(Clause.contract_id == contract.id)).scalars()}
        outcome = clause_extract.apply(s, extraction)
        assert extraction.status == "APPLIED" and outcome["replaced"] >= 1 and outcome["added"] >= 1
        after = {c.code: c for c in s.execute(select(Clause).where(Clause.contract_id == contract.id)).scalars()}
        first = extraction.items[0]
        assert after[first["code"]].text.startswith("Payment within 60 days") and after[first["code"]].position == "FALLBACK" and before[first["code"]] != after[first["code"]].text
        assert (after.get("GOVERNING_LAW") or after["DISPUTES"]).position == "STANDARD" and "PRICE_INDEX" not in after
        logged = s.execute(select(AuditEvent).where(AuditEvent.object_id == contract.id, AuditEvent.action == "CLAUSE_EXTRACTED")).scalars().all()
        assert logged and any(e.before for e in logged)  # the replaced text stays in the audit trail


def test_migration_hook_applies_confident_clauses_and_keeps_the_rest_for_review():
    with rolled_back(at(2029, 3, 1)) as s:
        contract = _draft(s, "VALUE_CONTRACT", lines=[CALL_OFF_LINE])
        act(s, "contract.manager")
        result = clause_extract.from_migration(s, contract, CONTRACT_TEXT, "ERP CONTRACT_TEXT")
        assert result["applied"] >= 3 and result["extraction"].startswith("CLX-")
        assert clause_extract.from_migration(s, contract, CONTRACT_TEXT, "ERP CONTRACT_TEXT")["existing"] is True  # idempotent
        extraction = s.execute(select(clause_extract.ClauseExtraction).where(clause_extract.ClauseExtraction.contract_ref == contract.number)).scalar_one()
        accepted = [i for i in extraction.items if i["decision"] == "ACCEPTED"]
        assert accepted and all(i["reviewedBy"] == "migration" and i["position"] != "NON_STANDARD" for i in accepted)


def test_clause_extraction_api(client, login):
    h = login("contract.manager")
    with tenant_tx(_tid()) as s:
        number = s.execute(select(Contract.number).where(Contract.type == "SCHEDULING_AGREEMENT").order_by(Contract.number)).scalars().first()
    body = {"contract": number, "text": CONTRACT_TEXT + "\n(API)", "source_name": "signed.pdf"}
    assert client.post("/v1/clause-extractions", json=body, headers=login("buyer")).status_code == 403
    r = client.post("/v1/clause-extractions", json=body, headers={**h, "Idempotency-Key": "c1-clx-1"})
    assert r.status_code == 201, r.text
    ref = r.json()["number"]
    assert r.json()["summary"]["items"] >= 4 and client.get(f"/v1/clause-extractions/{ref}", headers=h).json()["status"] == "EXTRACTED"
    assert client.post(f"/v1/clause-extractions/{ref}/apply", headers=h).status_code == 409
    assert client.post(f"/v1/clause-extractions/{ref}/reject", json={"reason": ""}, headers=h).status_code == 422
    done = client.post(f"/v1/clause-extractions/{ref}/reject", json={"reason": "test clean-up"}, headers=h)
    assert done.status_code == 200 and done.json()["status"] == "REJECTED"


# ================================================================ 28 segmentation
def test_segments_come_from_spend_share_and_risk_with_history_and_manual_override():
    body = {"highSpendSharePct": 5, "highRiskScore": 40}
    assert supplier_mgmt.classify_supplier(Decimal(12), 10, "LOW", body)[0] == "LEVERAGE"
    assert supplier_mgmt.classify_supplier(Decimal(12), 55, "LOW", body)[0] == "STRATEGIC"
    assert supplier_mgmt.classify_supplier(Decimal(1), 55, "LOW", body)[0] == "BOTTLENECK"
    assert supplier_mgmt.classify_supplier(Decimal(1), 5, "HIGH", body)[0] == "BOTTLENECK"
    assert supplier_mgmt.classify_supplier(Decimal(1), 5, "LOW", body)[0] == "ROUTINE"
    with rolled_back(at(2029, 3, 1)) as s:
        act(s, "supplier.manager")
        summary = supplier_mgmt.recompute_segments(s)
        assert summary["suppliers"] >= 4 and all(r["segment"] in supplier_mgmt.SEGMENTS for r in summary["results"])
        tf = supplier(s, "TF001")
        assert tf.segment in supplier_mgmt.SEGMENTS
        first = tf.segment
        history = supplier_mgmt.segment_view(s, tf)["history"]
        assert len(history) == 1 and history[0]["effective_to"] is None and history[0]["inputs"]["totalSpendMinor"] >= 0
        assert supplier_mgmt.recompute_segments(s, tf)["changed"] == 0  # nothing moved: no new history row
        # a critical risk signal moves a low-spend supplier to the exposed row: a new history entry, the old one closed
        s.add(RiskSignal(tenant_id=tf.tenant_id, supplier_id=tf.id, dedup_key="c1-seg", category="COMPLIANCE", severity="Critical", source="TEST",
                         title="seg", detail={}, status="OPEN", detected_at=clock.now()))
        s.flush()
        supplier_mgmt.recompute_segments(s, tf)
        history = supplier_mgmt.segment_view(s, tf)["history"]
        if tf.segment != first:
            assert len(history) == 2 and history[1]["effective_to"] is not None
        # manual override sticks until cleared
        manual = "ROUTINE" if tf.segment != "ROUTINE" else "BOTTLENECK"
        act(s, "buyer")
        assert problem(supplier_mgmt.set_segment_manually, s, tf, manual, "buyer tries").status == 403
        act(s, "supplier.manager")
        supplier_mgmt.set_segment_manually(s, tf, manual, "strategic review decided")
        assert tf.segment == manual
        supplier_mgmt.recompute_segments(s)
        assert tf.segment == manual
        supplier_mgmt.set_segment_manually(s, tf, None, "back to automatic")
        assert s.execute(select(SupplierSegment).where(SupplierSegment.supplier_id == tf.id, SupplierSegment.effective_to.is_(None))).scalar_one().method == "AUTO"
        shares = supplier_mgmt.segment_summary(s)
        assert {x["segment"] for x in shares["segments"]} == {*supplier_mgmt.SEGMENTS, "UNSEGMENTED"}


def test_segment_api(client, login):
    assert client.get("/v1/supplier-segments", headers=login("buyer")).status_code == 403
    summary = client.get("/v1/supplier-segments", headers=login("category.head")).json()
    assert len(summary["segments"]) == 5
    r = client.get("/v1/suppliers/TF001/segment", headers=login("buyer"))
    assert r.status_code == 200 and "history" in r.json()
    assert client.put("/v1/suppliers/TF001/segment", json={"segment": "ROUTINE", "reason": "x"}, headers=login("supplier.manager")).status_code in (200, 422)


# ================================================================ 29 development plans
def test_development_plan_runs_from_capa_to_review_with_reminders_evidence_and_a_measured_result():
    with rolled_back(at(2029, 3, 1)) as s:
        act(s, "supplier.manager")
        tf = supplier(s, "TF001")
        capa = risk.open_capa(s, tf, source_type="TEST", source_ref="C1-DEVPLAN", finding="Late deliveries in Q4")
        quality = s.execute(select(AppUser).where(AppUser.email == "quality.engineer@axion.example")).scalar_one()
        portal = s.execute(select(AppUser).where(AppUser.email == "tf.sales@axion.example")).scalar_one()
        plan = supplier_mgmt.create_plan(
            s, tf, title="Delivery recovery", objective="Raise OTIF to 95 percent", start_date=date(2029, 3, 5), target_date=date(2029, 6, 30), capa=capa,
            metric="OTIF", target_value=Decimal(95), actions=[{"description": "Weekly dispatch review", "owner_id": quality.id, "due_date": date(2029, 4, 15)},
                                                                {"description": "Add a second shift on the cover line", "owner_id": portal.id, "due_date": date(2029, 5, 31)}])
        assert plan.number.startswith("SDP-") and plan.status == "DRAFT" and plan.capa_id == capa.id
        assert problem(supplier_mgmt.add_action, s, plan, description="late", owner_id=quality.id, due_date=date(2029, 8, 1)).rule_ref == "SLM-DEVPLAN"
        other = s.execute(select(AppUser).where(AppUser.email == "kd.sales@axion.example")).scalar_one()
        assert problem(supplier_mgmt.add_action, s, plan, description="wrong supplier", owner_id=other.id, due_date=date(2029, 4, 1)).code == "INVALID_OWNER"
        supplier_mgmt.activate_plan(s, plan)
        timers = s.execute(select(Timer).where(Timer.kind == "DEV_ACTION_REMINDER", Timer.fired_at.is_(None))).scalars().all()
        assert len(timers) == 4 and plan.status == "ACTIVE"
        # reminder before the due date reaches the owner
        due_soon = next(t for t in timers if t.payload["stage"] == "DUE_SOON")
        supplier_mgmt._remind(s, due_soon)
        assert s.execute(select(Notification).where(Notification.kind == "DEV_ACTION_DUE", Notification.object_ref == plan.number)).scalars().first()
        # only the owner (or supplier management) works an action; a supplier user needs evidence first and sees only own plans
        act(s, "tf.sales")
        assert problem(supplier_mgmt.complete_action, s, plan, 2, note="done").code == "EVIDENCE_REQUIRED"
        assert problem(supplier_mgmt.complete_action, s, plan, 1, note="not mine").status == 403
        supplier_mgmt.add_evidence(s, plan, 2, note="Second shift roster signed", ref="HR-2029-07")
        supplier_mgmt.complete_action(s, plan, 2, note="shift started")
        act(s, "quality.engineer")
        supplier_mgmt.add_evidence(s, plan, 1, note="Minutes of 12 weekly reviews")
        supplier_mgmt.complete_action(s, plan, 1, note="done")
        review = s.execute(select(Task).where(Task.kind == "DEV_PLAN_REVIEW", Task.object_id == plan.id, Task.status == "OPEN")).scalar_one()
        assert review.candidate_role == "SUPPLIER_MANAGER"
        # the linked CAPA is still open: the review cannot close the plan
        act(s, "supplier.manager")
        workflow.complete(s, review.id, "APPROVE", "all actions done")
        assert plan.status == "ACTIVE" and s.execute(select(Timer).where(Timer.kind == "DEV_PLAN_RECHECK", Timer.object_id == plan.id)).scalar_one()
        capa.status = "CLOSED"
        s.flush()
        supplier_mgmt._recheck(s, s.execute(select(Timer).where(Timer.kind == "DEV_PLAN_RECHECK")).scalars().first())
        review = s.execute(select(Task).where(Task.kind == "DEV_PLAN_REVIEW", Task.object_id == plan.id, Task.status == "OPEN")).scalar_one()
        workflow.complete(s, review.id, "APPROVE", "CAPA verified, OTIF recovered")
        assert plan.status == "COMPLETED" and plan.closed_at and plan.outcome.startswith("CAPA verified")
        view = supplier_mgmt.plan_view(s, plan)
        assert view["progress"] == {"done": 2, "total": 2} and view["capa"] == capa.number
        assert supplier_mgmt.list_plans(s, tf)[0]["number"] == plan.number


def test_development_plan_api_and_portal_visibility(client, login):
    h = login("supplier.manager")
    with tenant_tx(_tid()) as s:
        owner = s.execute(select(AppUser.id).where(AppUser.email == "quality.engineer@axion.example")).scalar_one()
    body = {"title": "API plan", "objective": "Reduce PPM below 1000", "start_date": "2030-01-10", "target_date": "2030-06-30", "metric": "PPM", "target_value": "900",
            "actions": [{"description": "8D on casting porosity", "owner_id": str(owner), "due_date": "2030-03-31"}]}
    assert client.post("/v1/suppliers/KD002/development-plans", json=body, headers=login("buyer")).status_code == 403
    r = client.post("/v1/suppliers/KD002/development-plans", json=body, headers={**h, "Idempotency-Key": "c1-sdp-1"})
    assert r.status_code == 201, r.text
    ref = r.json()["number"]
    assert client.post("/v1/suppliers/KD002/development-plans", json=body, headers={**h, "Idempotency-Key": "c1-sdp-1"}).json()["number"] == ref
    assert client.get(f"/v1/development-plans/{ref}", headers=login("kd.sales")).status_code == 404  # drafts are internal
    assert client.post(f"/v1/development-plans/{ref}/activate", headers=h).json()["status"] == "ACTIVE"
    assert client.get(f"/v1/development-plans/{ref}", headers=login("kd.sales")).json()["number"] == ref
    assert client.get(f"/v1/development-plans/{ref}", headers=login("tf.sales")).status_code == 404  # another supplier's plan
    assert [p["number"] for p in client.get("/v1/development-plans", headers=login("kd.sales")).json()] == [ref]
    cancelled = client.post(f"/v1/development-plans/{ref}/cancel", json={"reason": "test clean-up"}, headers=h)
    assert cancelled.json()["status"] == "CANCELLED" and cancelled.json()["actions"][0]["status"] == "CANCELLED"


# ================================================================ 30 assessments and responsiveness
def test_assessment_scores_come_from_the_answers_and_certificates_and_a_second_person_reviews():
    with rolled_back(at(2029, 3, 1)) as s:
        tf = supplier(s, "TF001")
        act(s, "tf.sales")
        assert problem(supplier_mgmt.submit_assessment, s, tf, "ESG", {"E1": "YES"}).code == "INVALID_ANSWERS"
        none = supplier_mgmt.submit_assessment(s, tf, "ESG", _esg_answers("NO"), date(2029, 2, 1))
        assert none.score == Decimal("0.00")
        partial = supplier_mgmt.submit_assessment(s, tf, "CYBER", {q["id"]: "PARTIAL" for q in supplier_mgmt.CYBER_QUESTIONS}, date(2029, 2, 1))
        assert partial.score == Decimal("50.00")
        act(s, "kd.sales")
        assert problem(supplier_mgmt.submit_assessment, s, tf, "ESG", _esg_answers()).status == 403  # another supplier's questionnaire
        act(s, "tf.sales")
        assert problem(supplier_mgmt.review_assessment, s, partial, True, "self review").status == 403
        act(s, "supplier.manager")
        assert problem(supplier_mgmt.review_assessment, s, partial, False, "").code == "COMMENT_REQUIRED"
        supplier_mgmt.review_assessment(s, partial, True, "accepted")
        assert partial.status == "ACCEPTED" and supplier_mgmt.current_assessment(s, tf.id, "CYBER").id == partial.id
        assert supplier_mgmt.current_assessment(s, tf.id, "ESG") is None  # a submitted one is not current
        again = problem(supplier_mgmt.submit_assessment, s, tf, "CYBER", {q["id"]: "YES" for q in supplier_mgmt.CYBER_QUESTIONS}, date(2029, 2, 1))
        assert again.code == "ASSESSMENT_ACCEPTED"
        # the accepted ESG score lands on the scorecard of the month
        act(s, "tf.sales")
        esg = supplier_mgmt.submit_assessment(s, tf, "ESG", _esg_answers("PARTIAL"), date(2029, 3, 1))
        act(s, "supplier.manager")
        supplier_mgmt.review_assessment(s, esg, True, "ok")
        card = s.execute(select(Scorecard).where(Scorecard.supplier_id == tf.id, Scorecard.period == "2029-03")).scalar_one()
        assert card.esg_score == Decimal("50.00")


def test_rfq_participation_and_response_time_reach_the_scorecard():
    with rolled_back(at(2029, 3, 1)) as s:
        pr = _requirement(s, [("DC-330", 1200)])
        event = _event(s, "C1 responsiveness", pr, [_l(pr, 10)])
        sourcing.publish(s, event)
        clock.set_pinned(at(2029, 3, 1, 16))  # six hours after the publication
        _bid(s, "tf.sales", event, [_bl(10, 380)])
        tf, kd = supplier(s, "TF001"), supplier(s, "KD002")
        for sup in (tf, kd):
            supplier_mgmt.update_scorecard_measures(s, sup, "2029-03")
        card = lambda sup: s.execute(select(Scorecard).where(Scorecard.supplier_id == sup.id, Scorecard.period == "2029-03")).scalar_one()  # noqa: E731
        assert (card(tf).rfq_invited, card(tf).rfq_responded) == (1, 1) and card(tf).rfq_response_hours == Decimal("6.00")
        assert (card(kd).rfq_invited, card(kd).rfq_responded) == (1, 0) and card(kd).rfq_response_hours is None
        view = supplier_mgmt.responsiveness_view(s, tf)
        assert view[-1]["rfqResponseRatePct"] == "100.0" and view[-1]["rfqResponseHours"] == "6.00"
        # recomputing is idempotent
        supplier_mgmt.update_scorecard_measures(s, tf, "2029-03")
        assert card(tf).rfq_invited == 1


# ================================================================ 31 risk signals
def _open_signals(s, category, supplier_id=None):
    query = select(RiskSignal).where(RiskSignal.category == category, RiskSignal.status != "CLOSED")
    if supplier_id is not None:
        query = query.where(RiskSignal.supplier_id == supplier_id)
    return s.execute(query).scalars().all()


def test_scan_raises_concentration_geographic_and_cyber_signals_and_opens_mitigation_tasks():
    with rolled_back(at(2029, 3, 20)) as s:
        act(s, "supplier.manager")
        tf, kd, sla = supplier(s, "TF001"), supplier(s, "KD002"), supplier(s, "SLA003")
        sla.state_code = "27"
        tf.segment = "STRATEGIC"
        # spend inside the 12-month window of the pinned date (the signature case's spend lies years earlier)
        for sup, amount in ((tf, 7_000_000 * 100), (kd, 2_000_000 * 100), (sla, 1_000_000 * 100)):
            s.add(SpendLine(tenant_id=sup.tenant_id, invoice_line_id=uuid.uuid4(), invoice_ref=f"C1-{sup.code}", supplier_id=sup.id, category="ALU-DIECAST",
                            material_group="ALU-DIECAST", plant="P100", company_code="1000", period="2029-02", amount_minor=amount))
        s.flush()
        risk.scan(s)
        concentration = _open_signals(s, "CONCENTRATION", tf.id)
        assert concentration and concentration[0].detail["sharePct"] == "70.0" and concentration[0].detail["windowMonths"] == 12  # limit 30 %
        geographic = _open_signals(s, "GEOGRAPHIC")
        assert any(g.detail.get("region") == "IN-33" and "Tamil Nadu" in g.title for g in geographic)  # most spend sits in Tamil Nadu
        cyber = [x for x in _open_signals(s, "CYBER", tf.id) if x.dedup_key == "cyber-missing"]
        assert cyber  # a strategic supplier without an accepted questionnaire
        tasks = s.execute(select(Task).where(Task.kind == "RISK_MITIGATION", Task.status == "OPEN")).scalars().all()
        assert tasks and {t.candidate_role for t in tasks} == {"SUPPLIER_MANAGER"}
        # deciding the task records the mitigation on the signal
        signal = concentration[0]
        task = next(t for t in tasks if t.object_id == signal.id)
        workflow.complete(s, task.id, "APPROVE", "Second source RFQ planned for Q2")
        assert signal.status == "MITIGATING" and "Second source" in signal.mitigation
        # a scan again raises nothing new for it: signals are de-duplicated and a mitigating one is not reopened
        assert [x for x in risk.scan(s) if x.supplier_id == tf.id and x.category == "CONCENTRATION"] == []
        # an accepted questionnaire closes the cyber gap on the next scan
        act(s, "tf.sales")
        item = supplier_mgmt.submit_assessment(s, tf, "CYBER", {q["id"]: "YES" for q in supplier_mgmt.CYBER_QUESTIONS}, date(2029, 3, 1))
        act(s, "supplier.manager")
        supplier_mgmt.review_assessment(s, item, True, "ok")
        risk.scan(s)
        assert not [x for x in _open_signals(s, "CYBER", tf.id) if x.dedup_key == "cyber-missing"]
        assert not s.execute(select(Task).where(Task.kind == "RISK_MITIGATION", Task.status == "OPEN", Task.object_id.in_([c.id for c in cyber]))).scalars().all()


def test_single_source_materials_raise_a_signal_on_the_only_qualified_supplier():
    with rolled_back(at(2029, 3, 20)) as s:
        act(s, "supplier.manager")
        risk.scan(s)
        single = _open_signals(s, "SINGLE_SOURCE")
        assert single and all(x.detail["materials"] and x.detail["count"] == len(x.detail["materials"]) for x in single)
        info = risk.supplier_risk_score(s, supplier(s, "TF001"))
        assert info["level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL") and 0 <= info["score"] <= 100
        blocked = supplier(s, "SLA003")
        blocked.status = "BLOCKED"
        assert risk.supplier_risk_score(s, blocked)["score"] == 100


def test_qualification_helper_for_the_po_block():
    from app.pic.services import supplier as supplier_svc

    with rolled_back(at(2029, 3, 1)) as s:
        tf = supplier(s, "TF001")
        assert supplier_svc.qualification_status(s, tf.id, "ALU-DIECAST")["status"] in ("QUALIFIED", "PREFERRED", "CONDITIONAL", "REGISTERED")
        missing = supplier_svc.qualification_status(s, tf.id, "UNKNOWN-CAT")
        assert missing == {"status": "NOT_REGISTERED", "allowed": False, "needsWaiver": False, "reason": "supplier is NOT_REGISTERED for UNKNOWN-CAT"}
        tf.status = "BLOCKED"
        assert supplier_svc.qualification_status(s, tf.id, "ALU-DIECAST")["allowed"] is False


# ================================================================ migration constraints
def test_database_constraints_protect_the_new_tables():
    from sqlalchemy.exc import IntegrityError

    with rolled_back(at(2029, 3, 1)) as s:
        tf = supplier(s, "TF001")
        act(s, "supplier.manager")
        supplier_mgmt.recompute_segments(s, tf)
        s.add(SupplierSegment(tenant_id=tf.tenant_id, supplier_id=tf.id, segment="ROUTINE", method="AUTO", effective_from=clock.now()))
        with pytest.raises(IntegrityError):  # one current segment per supplier
            s.flush()
