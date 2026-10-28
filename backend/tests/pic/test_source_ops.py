"""Contract amendments and termination (F4), clarification board (F3-03) and live reverse auction (SRC-04).

Contracts here are new DC-331 quantity contracts in 2028, so the seeded signature case is untouched. Timers are
fired one by one for the objects under test (never the whole tenant's due list).
"""
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuctionBid, Contract, ContractAmendment, ContractLine, Material, Notification, OutboxEvent, PoLine, PriceValidity, ProcessInstance, PurchaseOrder,
    SourcingEvent, Supplier, Task, Tenant, Timer,
)
from app.pic.platform import clock, outbox, workflow
from app.pic.platform.auth import hash_password
from app.pic.platform.core import next_number
from app.pic.seed.axion import ROLE_USER, Scenario
from app.pic.services import contract as contract_svc
from app.pic.services import source
from tests.pic.conftest import PASSWORD

IST = clock.IST


def at(y, m, d, hh=10, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


@pytest.fixture(scope="module")
def sc():
    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()
    with tenant_tx(tenant_id) as s:
        if not s.execute(select(AppUser.id).where(AppUser.email == "contract.manager2@axion.example")).first():
            # A second contract manager: below-threshold amendments are approved by a contract manager other than the requester.
            s.add(AppUser(tenant_id=tenant_id, email="contract.manager2@axion.example", full_name="Second contract manager",
                          password_hash=hash_password(PASSWORD), roles=["CONTRACT_MANAGER"], attributes={}))
    scenario = Scenario(tenant_id, role_user={**ROLE_USER, "CONTRACT_MANAGER": ["contract.manager", "contract.manager2"]})
    yield scenario
    clock.set_pinned(None)


def _active_contract(sc: Scenario, when: datetime, qty: str, price: int, valid_from=date(2028, 1, 1), valid_to=date(2028, 12, 31)):
    with sc.act("contract.manager", when) as s:
        tf = s.execute(select(Supplier).where(Supplier.code == "TF001")).scalar_one()
        dc331 = s.execute(select(Material).where(Material.number == "DC-331")).scalar_one()
        contract = contract_svc.create_draft(
            s, type="QUANTITY_CONTRACT", title="DC-331 covers 2028", supplier_id=tf.id, company_code="1000", valid_from=valid_from,
            valid_to=valid_to, payment_terms="N60", incoterms="FCA Trichy",
            lines=[{"material_id": dc331.id, "description": dc331.description, "plant": "P100", "uom": "EA", "target_qty": qty,
                    "unit_price_minor": price}], owner_id=s.info["principal"].user_id,
            tolerances={"over_pct": "2", "under_pct": "5", "price_pct": "0"})
        contract_svc.ai_review(s, contract)
        contract_svc.submit(s, contract)
        contract_id, number = contract.id, contract.number
    sc.approve_all(contract_id, when, "Approved for test")
    with sc.act("contract.manager", when) as s:
        contract_svc.sign(s, s.get(Contract, contract_id), "BUYER", "Ganesh Murthy")
    with sc.act("tf.sales", when) as s:
        contract_svc.sign(s, s.get(Contract, contract_id), "SUPPLIER", "Authorised signatory")
    with sc.act("contract.manager", when) as s:
        contract_svc.activate(s, s.get(Contract, contract_id))
    return contract_id, number


def _determine(sc: Scenario, on: date):
    with sc.act("buyer", clock.now()) as s:
        dc331 = s.execute(select(Material).where(Material.number == "DC-331")).scalar_one()
        return source.determine(s, dc331, "P100", on, Decimal(100))


def _tasks(client, login, who: str, ref: str, kind: str):
    return [t for t in client.get("/v1/tasks", headers=login(who)).json() if t["object_ref"] == ref and t["kind"] == kind]


def _fire(sc: Scenario, kind: str, object_id: uuid.UUID, when: datetime) -> int:
    fired = 0
    with sc.act("contract.manager", when) as s:
        for timer in s.execute(select(Timer).where(Timer.kind == kind, Timer.object_id == object_id, Timer.fired_at.is_(None),
                                                   Timer.due_at <= clock.now())).scalars().all():
            timer.fired_at = clock.now()
            workflow._timer_handlers[kind](s, timer)
            fired += 1
    return fired


# ---------------------------------------------------------------- F4 amendments
def test_variation_chain_sod_version_and_new_price_in_source_determination(client, login, sc):
    contract_id, number = _active_contract(sc, at(2027, 11, 15), qty="100000", price=21000)
    clock.set_pinned(at(2028, 2, 1))
    cm, cm2 = login("contract.manager"), login("contract.manager2@axion.example")
    assert _determine(sc, date(2028, 3, 1)).allocations[0].unit_price_minor == 21000

    # Live preview: ₹5/pc off 100,000 pcs = ₹5 L, below the ₹1 Cr threshold → CONTRACT_MANAGER chain.
    body = {"kind": "VARIATION", "changes": {"lines": [{"line": 10, "unitPriceMinor": 20500}]}, "effective_from": "2028-02-01"}
    preview = client.post(f"/v1/contracts/{number}/amendments/preview", json=body, headers=cm).json()
    assert preview["valueDeltaMinor"] == -100000 * 500 and preview["band"] == "below" and preview["approvalChain"] == ["CONTRACT_MANAGER"]
    assert preview["before"]["lines"][0]["unitPriceMinor"] == 21000 and preview["after"]["lines"][0]["unitPriceMinor"] == 20500

    headers = {**cm, "Idempotency-Key": f"amend-{number}-1"}
    created = client.post(f"/v1/contracts/{number}/amendments", json={**body, "reason": "Q1 cost-down agreed"}, headers=headers)
    assert created.status_code == 201, created.text
    amendment = created.json()
    assert amendment["status"] == "IN_APPROVAL" and amendment["from_version"] == 1 and amendment["number"].startswith("CA-")
    assert client.post(f"/v1/contracts/{number}/amendments", json={**body, "reason": "Q1 cost-down agreed"}, headers=headers).json()["replayed"]
    # Only one pending amendment per contract.
    again = client.post(f"/v1/contracts/{number}/amendments", json={**body, "reason": "duplicate"}, headers=cm)
    assert again.status_code == 409 and again.json()["code"] == "AMENDMENT_PENDING"

    # Four-eyes: the requester gets no task and cannot complete it.
    assert _tasks(client, login, "contract.manager", number, "CONTRACT_AMENDMENT") == []
    [task] = _tasks(client, login, "contract.manager2@axion.example", number, "CONTRACT_AMENDMENT")
    denied = client.post(f"/v1/tasks/{task['id']}/complete", json={"decision": "APPROVE"}, headers=cm)
    assert denied.status_code == 403
    assert client.post(f"/v1/tasks/{task['id']}/complete", json={"decision": "APPROVE"}, headers=cm2).status_code == 200

    listing = client.get(f"/v1/contracts/{number}/amendments", headers=cm).json()
    assert listing["version"] == 2
    item = listing["items"][0]
    assert item["status"] == "EFFECTIVE" and item["to_version"] == 2 and item["snapshot"]["lines"][0]["unitPriceMinor"] == 21000
    contract = client.get(f"/v1/contracts/{number}", headers=cm).json()
    assert contract["version"] == 2
    assert any(v["reason"] == f"AMENDMENT {amendment['number']}" and v["valid_from"] == "2028-02-01" for v in contract["priceValidity"])
    # New period is used from the effective date; the old one still prices earlier needs; consumption reads the new price.
    assert _determine(sc, date(2028, 3, 1)).allocations[0].unit_price_minor == 20500
    assert _determine(sc, date(2028, 1, 20)).allocations[0].unit_price_minor == 21000
    assert client.get(f"/v1/contracts/{number}/consumption", headers=cm).json()["lines"][0]["currentPriceMinor"] == 20500

    # Above the threshold (+60,000 pcs × ₹205 = ₹1.23 Cr) the chain is LEGAL → FINANCE_CONTROLLER.
    more = {"kind": "VARIATION", "changes": {"lines": [{"line": 10, "targetQty": "160000"}]}, "reason": "Volume increase",
            "effective_from": "2028-02-01"}
    big = client.post(f"/v1/contracts/{number}/amendments", json=more, headers=cm).json()
    assert big["changes"]["band"] == "above" and big["changes"]["approvalChain"] == ["LEGAL", "FINANCE_CONTROLLER"]
    [legal] = _tasks(client, login, "legal", number, "CONTRACT_AMENDMENT")
    assert client.post(f"/v1/tasks/{legal['id']}/complete", json={"decision": "APPROVE"}, headers=login("legal")).status_code == 200
    [fin] = _tasks(client, login, "finance.controller", number, "CONTRACT_AMENDMENT")
    assert client.post(f"/v1/tasks/{fin['id']}/complete", json={"decision": "APPROVE"}, headers=login("finance.controller")).status_code == 200
    contract = client.get(f"/v1/contracts/{number}", headers=cm).json()
    assert contract["version"] == 3 and contract["lines"][0]["target_qty"] == "160000"
    trail = [e["action"] for e in client.get(f"/v1/audit/CONTRACT/{number}", headers=cm).json()]
    assert trail.count("AMENDED") == 2 and "AMENDMENT_APPROVED" in trail
    with tenant_tx(sc.tenant_id) as s:
        topics = [e.topic for e in s.execute(select(OutboxEvent).where(OutboxEvent.object_id == contract_id)).scalars()]
    assert topics.count("contract.amended") == 2
    # The platform notification consumer turns each amendment into an in-app notice for contract managers and the supplier.
    outbox.relay_tenant(sc.tenant_id)
    with tenant_tx(sc.tenant_id) as s:
        kinds = {(n.kind, n.user_id) for n in s.execute(select(Notification).where(Notification.object_ref == number)).scalars()}
        cm2_id = s.execute(select(AppUser.id).where(AppUser.email == "contract.manager2@axion.example")).scalar_one()
    assert ("CONTRACT_AMENDED", cm2_id) in kinds

    # An index reset after the variation adjusts the amended price (₹205), not the original ₹210: +10% index, ±2% band → +8%.
    with sc.act("contract.manager", at(2028, 3, 30)) as s:
        indexed = s.get(Contract, contract_id)
        indexed.index_ref = {"index": "LME-AL", "base": "100", "band_pct": "2"}
        reset = contract_svc.index_reset(s, indexed, Decimal("110"), date(2028, 4, 1))
    assert reset["lines"] == [{"line": 10, "oldPriceMinor": 20500, "newPriceMinor": 22140}]


def test_termination_stops_source_determination_and_flags_open_pos(client, login, sc):
    clock.set_pinned(at(2028, 3, 1))
    number = "unset"
    with tenant_tx(sc.tenant_id) as s:
        contract = s.execute(select(Contract).where(Contract.title == "DC-331 covers 2028", Contract.status == "ACTIVE")
                             .order_by(Contract.created_at)).scalars().first()
        number, contract_id = contract.number, contract.id
        line = contract_svc._lines(s, contract)[0]
        po = PurchaseOrder(tenant_id=sc.tenant_id, number=next_number(s, "PURCHASE_ORDER"), company_code="1000", purch_org="1000",
                           plant="P100", supplier_id=contract.supplier_id, status="RELEASED", contract_id=contract.id, purpose_code="BUFFER_BUILD",
                           payment_terms="N60", total_minor=20500 * 500, rule_set_version="test")
        s.add(po)
        s.flush()
        s.add(PoLine(tenant_id=sc.tenant_id, po_id=po.id, line_no=10, item_type="MATERIAL", purchase_type="STOCK", material_id=line.material_id,
                     description=line.description, material_group="ALU-DIECAST", qty=Decimal(500), uom="EA", unit_price_minor=20500,
                     net_minor=20500 * 500, gst_rate=Decimal(18), need_date=date(2028, 4, 15), plant="P100", gr_required=True,
                     price_source="CONTRACT", contract_line_id=line.id))
        po_number = po.number
    cm = login("contract.manager")
    assert _determine(sc, date(2028, 4, 1)).method == "CONTRACT"

    # Without cause the rule's 90 days' notice applies.
    early = {"kind": "TERMINATION", "changes": {"forCause": False}, "reason": "Consolidating DC-331 with the DC-330 suppliers",
             "effective_from": "2028-03-31"}
    r = client.post(f"/v1/contracts/{number}/amendments", json=early, headers=cm)
    assert r.status_code == 422 and r.json()["ruleRef"].startswith("CONTRACT-AMENDMENT@") and r.json()["earliestEffective"] == "2028-05-30"
    preview = client.post(f"/v1/contracts/{number}/amendments/preview", json={**early, "changes": {"forCause": True}}, headers=cm).json()
    assert preview["approvalChain"] == ["LEGAL", "CPO"] and [p["number"] for p in preview["openPurchaseOrders"]] == [po_number]

    cause = {"kind": "TERMINATION", "changes": {"forCause": True}, "reason": "Repeated PPM breach (8D not closed)", "effective_from": "2028-03-01"}
    created = client.post(f"/v1/contracts/{number}/amendments", json=cause, headers={**cm, "Idempotency-Key": f"term-{number}"})
    assert created.status_code == 201 and created.json()["changes"]["band"] == "termination"
    for who in ("legal", "cpo"):
        [task] = _tasks(client, login, who, number, "CONTRACT_AMENDMENT")
        assert client.post(f"/v1/tasks/{task['id']}/complete", json={"decision": "APPROVE", "comment": "8D overdue"},
                           headers=login(who)).status_code == 200

    contract = client.get(f"/v1/contracts/{number}", headers=cm).json()
    assert contract["status"] == "TERMINATED" and contract["terminated_at"] and contract["termination_reason"].startswith("Repeated PPM")
    assert contract["version"] == 4
    assert all(v["valid_to"] <= "2028-02-29" or not v["published"] for v in contract["priceValidity"])
    assert contract["process"]["status"] == "COMPLETED" and contract["process"]["path"][-1]["step"] == "F4-10"
    # Source determination no longer uses the contract.
    determination = _determine(sc, date(2028, 4, 1))
    assert determination.method != "CONTRACT" and all(a.contract_id != contract_id for a in determination.allocations)
    # Open PO flagged: audit entry and a buyer review task.
    po_trail = client.get(f"/v1/audit/PURCHASE_ORDER/{po_number}", headers=login("buyer")).json()
    assert any(e["action"] == "CONTRACT_TERMINATED" and e["after"]["contract"] == number for e in po_trail)
    [review] = _tasks(client, login, "buyer", po_number, "TERMINATED_CONTRACT_REVIEW")
    assert review["evidence"]["contract"] == number
    with tenant_tx(sc.tenant_id) as s:
        assert not s.execute(select(Timer).where(Timer.object_id == contract_id, Timer.kind.in_(("CONTRACT_RENEWAL", "CONTRACT_EXPIRY")),
                                                 Timer.fired_at.is_(None))).first()
        event = s.execute(select(OutboxEvent).where(OutboxEvent.object_id == contract_id, OutboxEvent.topic == "contract.terminated")).scalar_one()
        assert event.payload["openPurchaseOrders"] == [po_number] and event.payload["forCause"] is True
    # A terminated contract cannot be amended again.
    r = client.post(f"/v1/contracts/{number}/amendments", json={**cause, "kind": "TERMS", "changes": {"paymentTerms": "N30"}}, headers=cm)
    assert r.status_code == 409 and r.json()["code"] == "ILLEGAL_TRANSITION"


def test_renewal_creates_extension_draft_and_timed_termination(client, login, sc):
    contract_id, number = _active_contract(sc, at(2027, 11, 20), qty="40000", price=21000)
    # Renewal notice (120 days before 31 Dec 2028) moves the contract to EXPIRING with a renewal task.
    assert _fire(sc, "CONTRACT_RENEWAL", contract_id, at(2028, 9, 2, 10)) == 1
    clock.set_pinned(at(2028, 9, 2, 11))
    cm, cm2 = login("contract.manager"), login("contract.manager2@axion.example")
    assert client.get(f"/v1/contracts/{number}", headers=cm).json()["status"] == "EXPIRING"
    [renewal] = _tasks(client, login, "contract.manager", number, "CONTRACT_RENEWAL")
    assert client.post(f"/v1/tasks/{renewal['id']}/complete", json={"decision": "APPROVE", "comment": "Renew on same terms"},
                       headers=cm).status_code == 200

    [draft] = client.get(f"/v1/contracts/{number}/amendments", headers=cm).json()["items"]
    assert draft["kind"] == "EXTENSION" and draft["status"] == "DRAFT" and draft["changes"]["validTo"] == "2029-12-31"
    submitted = client.post(f"/v1/contracts/{number}/amendments/{draft['number']}/submit", headers=cm).json()
    assert submitted["status"] == "IN_APPROVAL" and submitted["changes"]["approvalChain"] == ["CONTRACT_MANAGER"]
    assert _tasks(client, login, "contract.manager", number, "CONTRACT_AMENDMENT") == []  # requester excluded
    [task] = _tasks(client, login, "contract.manager2@axion.example", number, "CONTRACT_AMENDMENT")
    assert client.post(f"/v1/tasks/{task['id']}/complete", json={"decision": "APPROVE"}, headers=cm2).status_code == 200

    contract = client.get(f"/v1/contracts/{number}", headers=cm).json()
    assert contract["status"] == "ACTIVE" and contract["valid_to"] == "2029-12-31" and contract["version"] == 2
    assert _determine(sc, date(2029, 6, 1)).allocations[0].unit_price_minor == 21000
    with tenant_tx(sc.tenant_id) as s:
        open_timers = {t.kind: t.due_at for t in s.execute(select(Timer).where(Timer.object_id == contract_id, Timer.fired_at.is_(None))).scalars()}
    assert open_timers["CONTRACT_EXPIRY"].astimezone(IST).date() == date(2030, 1, 1) and open_timers["CONTRACT_RENEWAL"].astimezone(IST).date() == date(2029, 9, 2)

    # Termination with notice: approved now, applied by the timer on the effective date.
    clock.set_pinned(at(2028, 9, 3, 10))
    body = {"kind": "TERMINATION", "changes": {"forCause": False}, "reason": "Part superseded by DC-331B", "effective_from": "2028-12-15"}
    term = client.post(f"/v1/contracts/{number}/amendments", json=body, headers=cm).json()
    for who in ("legal", "cpo"):
        [t] = _tasks(client, login, who, number, "CONTRACT_AMENDMENT")
        client.post(f"/v1/tasks/{t['id']}/complete", json={"decision": "APPROVE"}, headers=login(who))
    assert client.get(f"/v1/contracts/{number}/amendments/{term['number']}", headers=cm).json()["status"] == "APPROVED"
    assert client.get(f"/v1/contracts/{number}", headers=cm).json()["status"] == "ACTIVE"
    with tenant_tx(sc.tenant_id) as s:
        amendment_id = s.execute(select(ContractAmendment.id).where(ContractAmendment.number == term["number"])).scalar_one()
    assert _fire(sc, "CONTRACT_AMENDMENT_EFFECTIVE", amendment_id, at(2028, 12, 15, 0, 30)) == 1
    clock.set_pinned(at(2028, 12, 15, 9))
    contract = client.get(f"/v1/contracts/{number}", headers=cm).json()
    assert contract["status"] == "TERMINATED" and contract["version"] == 3
    versions = [(a["kind"], a["from_version"], a["to_version"]) for a in client.get(f"/v1/contracts/{number}/amendments", headers=cm).json()["items"]]
    assert versions == [("TERMINATION", 2, 3), ("EXTENSION", 1, 2)]


# ---------------------------------------------------------------- F3-03 clarifications
def _event(client, login, type_: str, close_at: datetime, invitees=("TF001", "KD002")) -> str:
    body = {"type": type_, "title": f"DC-331 cover {type_.lower()}", "category": "ALU-DIECAST",
            "lines": [{"requisition": "REQ-2312", "line": 10, "annual_qty": "1000", "monthly_qty": "100"}],
            "criteria": [{"code": "PRICE_TCO", "name": "Price / TCO", "weight": 100}], "invitees": [{"supplier": c} for c in invitees],
            "close_at": close_at.isoformat(), "baseline_method": "BUDGET", "baseline_price_minor": 42000}
    r = client.post("/v1/sourcing/events", json=body, headers=login("category.head"))
    assert r.status_code == 201, r.text
    return r.json()["number"]


def test_clarifications_visibility_and_anonymity(client, login, sc):
    clock.set_pinned(at(2028, 5, 2, 10))
    number = _event(client, login, "RFQ", at(2028, 5, 9, 17))
    assert client.post(f"/v1/sourcing/events/{number}/publish", headers=login("category.head")).status_code == 200
    tf, kd, head = login("tf.sales"), login("kd.sales"), login("category.head")
    url = f"/v1/sourcing/events/{number}/clarifications"

    q1 = client.post(url, json={"text": "Is drawing revision C final for the cover?"}, headers={**tf, "Idempotency-Key": f"q1-{number}"})
    assert q1.status_code == 201 and q1.json()["mine"] is True and "askedBy" not in q1.json()
    assert client.post(url, json={"text": "Can we quote with our own packaging?"}, headers=kd).status_code == 201
    notice = client.post(url, json={"text": "Site visit on 5 May at 11:00, Plant P100."}, headers=head).json()
    assert notice["status"] == "ANSWERED" and notice["kind"] == "NOTICE"

    kd_view = client.get(url, headers=kd).json()["items"]
    assert [(i["seq"], i["status"]) for i in kd_view] == [(2, "OPEN"), (3, "ANSWERED")]  # TF's open question is not shown
    # Only the owner or the category's manager answers.
    assert client.post(f"{url}/1/answer", json={"answer": "Yes"}, headers=login("buyer")).json()["code"] == "NOT_EVENT_MANAGER"
    assert client.post(f"{url}/1/answer", json={"answer": "Yes"}, headers=tf).status_code == 403
    answered = client.post(f"{url}/1/answer", json={"answer": "Yes, rev C (ECN-2207) is frozen."}, headers=login("category.manager"))
    assert answered.status_code == 200 and answered.json()["status"] == "ANSWERED"

    kd_view = client.get(url, headers=kd)
    assert {i["seq"]: i["mine"] for i in kd_view.json()["items"]} == {1: False, 2: True, 3: False}
    assert "TF001" not in kd_view.text and "Trichy" not in kd_view.text and "askedBy" not in kd_view.text
    buyer_view = client.get(url, headers=head).json()
    assert buyer_view["openQuestions"] == 1 and buyer_view["items"][0]["askedBy"]["code"] == "TF001"
    assert buyer_view["items"][1]["askedBy"]["code"] == "KD002" and buyer_view["items"][2]["askedBy"] is None
    assert client.get(url, headers=login("sla.sales")).status_code == 404  # not invited
    assert client.post(f"{url}/2/withdraw", headers=tf).status_code == 403
    assert client.post(f"{url}/2/withdraw", headers=kd).json()["status"] == "WITHDRAWN"
    with tenant_tx(sc.tenant_id) as s:
        event_id = s.execute(select(SourcingEvent.id).where(SourcingEvent.number == number)).scalar_one()
        topics = [e.payload["kind"] for e in s.execute(select(OutboxEvent).where(OutboxEvent.object_id == event_id,
                                                                                OutboxEvent.topic == "sourcing.clarification.answered")).scalars()]
    assert sorted(topics) == ["NOTICE", "QUESTION"]
    clock.set_pinned(at(2028, 5, 9, 17, 1))
    late = client.post(url, json={"text": "One more question after close"}, headers=tf)
    assert late.status_code == 409 and late.json()["code"] == "CLARIFICATION_WINDOW_CLOSED"


# ---------------------------------------------------------------- SRC-04 reverse auction
def test_reverse_auction_decrement_rank_soft_close_and_award(client, login, sc):
    start = at(2028, 6, 6, 11)
    close_at = start + timedelta(minutes=30)
    clock.set_pinned(start - timedelta(hours=1))
    head, tf, kd = login("category.head"), login("tf.sales"), login("kd.sales")
    number = _event(client, login, "REVERSE_AUCTION", close_at)
    settings = {"minDecrementPct": "1", "extensionMinutes": 5, "triggerMinutes": 2, "showRank": True, "showBestPrice": False,
                "paymentTermsDays": 45, "leadTimeDays": 14}
    assert client.put(f"/v1/sourcing/events/{number}/auction", json=settings, headers=head).json()["minDecrementPct"] == "1"
    assert client.post(f"/v1/sourcing/events/{number}/publish", headers=head).status_code == 200
    bids = f"/v1/sourcing/events/{number}/auction/bids"

    clock.set_pinned(start)
    first = client.post(bids, json={"priceMinor": 40000}, headers={**tf, "Idempotency-Key": f"bid-{number}-1"})
    assert first.status_code == 201 and first.json()["myRank"] == 1
    assert client.post(bids, json={"priceMinor": 39500}, headers=kd).json()["myRank"] == 1
    # Must beat your own last bid by 1 % (≤ ₹396.00).
    r = client.post(bids, json={"priceMinor": 39800}, headers=tf)
    assert r.status_code == 422 and r.json()["ruleRef"] == "AUCTION-DECREMENT" and r.json()["maxAllowedMinor"] == 39600
    mine = client.post(bids, json={"priceMinor": 39600}, headers=tf).json()
    assert mine["myRank"] == 2 and mine["bestPriceMinor"] is None and mine["nextMaxPriceMinor"] == 39204
    assert [b["priceMinor"] for b in mine["myBids"]] == [39600, 40000] and "ladder" not in mine and mine["secondsLeft"] == 30 * 60
    assert client.post(bids, json={"priceMinor": 30000}, headers=login("sla.sales")).status_code == 404  # not invited
    sealed = client.post(f"/v1/sourcing/events/{number}/bids", json={"lines": [{"line": 10, "unit_price": "390", "payment_terms_days": 30,
                                                                                "lead_time_days": 10}]}, headers=tf)
    assert sealed.status_code == 409 and sealed.json()["code"] == "USE_AUCTION_BIDDING"

    # Soft close: a bid in the last 2 minutes extends the end by 5 minutes.
    clock.set_pinned(close_at - timedelta(minutes=1))
    extended = client.post(bids, json={"priceMinor": 39000}, headers=kd).json()
    assert datetime.fromisoformat(extended["endsAt"]) == close_at + timedelta(minutes=5) and extended["extensions"] == 1
    ladder = client.get(f"/v1/sourcing/events/{number}/auction", headers=head).json()
    assert [(l["rank"], l["supplier"], l["priceMinor"]) for l in ladder["ladder"]] == [(1, "KD002", 39000), (2, "TF001", 39600)]
    assert len(ladder["bids"]) == 4 and ladder["bids"][0]["extendedClose"] is True

    # The ledger is append-only for the application role.
    for statement in ("UPDATE pic.auction_bid SET price_minor = 1", "DELETE FROM pic.auction_bid"):
        with pytest.raises(DBAPIError, match="permission denied"):
            with tenant_tx(sc.tenant_id) as s:
                s.execute(text(statement))

    # The scheduled close time no longer closes it; the extended end does.
    clock.set_pinned(close_at + timedelta(minutes=1))
    assert client.post(f"/v1/sourcing/events/{number}/close", headers=head).json()["code"] == "CLOSE_TIME_NOT_REACHED"
    with tenant_tx(sc.tenant_id) as s:
        event_id = s.execute(select(SourcingEvent.id).where(SourcingEvent.number == number)).scalar_one()
    _fire(sc, "SOURCING_CLOSE", event_id, close_at + timedelta(minutes=1))
    assert client.get(f"/v1/sourcing/events/{number}", headers=head).json()["status"] == "OPEN"
    late = client.post(bids, json={"priceMinor": 38000}, headers=tf)
    assert late.status_code == 201 and late.json()["myRank"] == 1  # still inside the extended window
    assert _fire(sc, "SOURCING_CLOSE", event_id, close_at + timedelta(minutes=11)) >= 1
    clock.set_pinned(close_at + timedelta(minutes=11))
    event = client.get(f"/v1/sourcing/events/{number}", headers=head).json()
    assert event["status"] == "UNDER_EVALUATION" and {b["supplier"]: b["status"] for b in event["bids"]} == {"TF001": "UNSEALED", "KD002": "UNSEALED"}

    # Each supplier's last price is now an ordinary bid: matrix, scenarios and award work unchanged.
    matrix = client.get(f"/v1/sourcing/events/{number}/bids", headers=head).json()
    assert {(m["supplier"], m["priceMinor"], m["paymentTermsDays"], m["leadTimeDays"]) for m in matrix} == {
        ("TF001", 38000, 45, 14), ("KD002", 39000, 45, 14)}
    scenarios = client.post(f"/v1/sourcing/events/{number}/scenarios", headers=head).json()
    lowest = next(x for x in scenarios if x["kind"] == "LOWEST_COST")
    assert lowest["allocations"][0]["supplier"] == "TF001" and lowest["feasible"]
    award = client.post(f"/v1/sourcing/events/{number}/award", json={"scenario_id": lowest["id"], "conflict_declaration": "No conflict"},
                        headers=head)
    assert award.status_code == 200 and award.json()["status"] == "AWARDED"
    with tenant_tx(sc.tenant_id) as s:
        assert len(s.execute(select(AuctionBid).where(AuctionBid.event_id == event_id)).scalars().all()) == 5
        assert s.get(ProcessInstance, s.execute(select(ProcessInstance.id).where(ProcessInstance.business_id == event_id)).scalar_one()).status == "COMPLETED"

    # REQ-2312 is a free-text line (no material): the award becomes a value contract without an index, not a failed consumer.
    outbox.relay_tenant(sc.tenant_id)
    with tenant_tx(sc.tenant_id) as s:
        failed = s.execute(select(OutboxEvent).where(OutboxEvent.object_id == event_id, OutboxEvent.last_error.is_not(None))).scalars().all()
        assert not failed, [e.last_error for e in failed]
        drafts = s.execute(select(Contract).where(Contract.source_event_id == event_id)).scalars().all()
        assert [(c.type, c.index_ref, c.status) for c in drafts] == [("VALUE_CONTRACT", None, "DRAFT")]
        assert s.execute(select(ContractLine.material_id).where(ContractLine.contract_id == drafts[0].id)).scalars().all() == [None]


# ---------------------------------------------------------------- F4-07 e-signature provider adapter
@pytest.fixture
def esign_provider(monkeypatch):
    """A stand-in provider API on localhost that records envelope requests."""
    import json as _json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": _json.loads(body)})
            reply = _json.dumps({"envelopeId": f"ENV-{len(received):04d}", "status": "sent"}).encode()
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for k in ("PIC_ESIGN_PROVIDER", "PIC_ESIGN_URL", "PIC_ESIGN_API_KEY", "PIC_ESIGN_WEBHOOK_SECRET"):
        monkeypatch.delenv(k, raising=False)
    yield {"received": received, "url": f"http://127.0.0.1:{server.server_port}/api/v1"}
    server.shutdown()


def _webhook(client, secret: str, payload: dict, signature: str | None = None):
    import hashlib
    import hmac
    import json as _json
    body = _json.dumps(payload).encode()
    sig = signature or "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/v1/esign/webhook", content=body, headers={"Content-Type": "application/json", "X-Esign-Signature": sig})


def test_esign_envelope_and_hmac_webhook_record_signatures(client, login, sc, esign_provider, monkeypatch):
    when = at(2029, 10, 1)
    with sc.act("contract.manager", when) as s:
        tf = s.execute(select(Supplier).where(Supplier.code == "TF001")).scalar_one()
        dc331 = s.execute(select(Material).where(Material.number == "DC-331")).scalar_one()
        contract = contract_svc.create_draft(
            s, type="QUANTITY_CONTRACT", title="DC-331 covers 2030", supplier_id=tf.id, company_code="1000", valid_from=date(2030, 1, 1),
            valid_to=date(2030, 12, 31), payment_terms="N60", incoterms="FCA Trichy",
            lines=[{"material_id": dc331.id, "description": dc331.description, "plant": "P100", "uom": "EA", "target_qty": "100000",
                    "unit_price_minor": 21000}], owner_id=s.info["principal"].user_id, tolerances={"over_pct": "2", "under_pct": "5"})
        contract_svc.ai_review(s, contract)
        contract_svc.submit(s, contract)
        contract_id, number = contract.id, contract.number
    sc.approve_all(contract_id, when, "Approved for test")
    clock.set_pinned(when)
    cm = login("contract.manager")
    url = f"/v1/contracts/{number}/signature-envelopes"

    # Not configured: the internal signature path stays the default.
    r = client.post(url, json={}, headers=cm)
    assert r.status_code == 404 and r.json()["code"] == "ESIGN_NOT_CONFIGURED"
    assert _webhook(client, "x", {"reference": f"PIC:AXN:{number}"}).json()["code"] == "ESIGN_NOT_CONFIGURED"

    secret = "whsec-test-0001"
    monkeypatch.setenv("PIC_ESIGN_PROVIDER", "LEEGALITY")
    monkeypatch.setenv("PIC_ESIGN_URL", esign_provider["url"])
    monkeypatch.setenv("PIC_ESIGN_API_KEY", "test-api-key")
    monkeypatch.setenv("PIC_ESIGN_WEBHOOK_SECRET", secret)
    created = client.post(url, json={"supplier_signer": "tf.sales@axion.example"}, headers={**cm, "Idempotency-Key": f"env-{number}"})
    assert created.status_code == 201, created.text
    envelope = created.json()
    [sent] = esign_provider["received"]
    assert sent["path"] == "/api/v1/envelopes" and sent["auth"] == "Bearer test-api-key"
    assert sent["body"]["documentHash"]["value"] == envelope["documentHash"] and sent["body"]["reference"] == f"PIC:AXN:{number}"
    assert [(x["party"], x["email"]) for x in sent["body"]["signers"]] == [("BUYER", "contract.manager@axion.example"),
                                                                            ("SUPPLIER", "tf.sales@axion.example")]
    assert client.post(url, json={}, headers=cm).json()["code"] == "ENVELOPE_PENDING"

    event = {"event": "SIGNER_COMPLETED", "envelopeId": envelope["envelopeId"], "reference": envelope["reference"], "party": "SUPPLIER",
             "signerName": "Authorised signatory, Trichy Forge", "documentHash": envelope["documentHash"]}
    bad = _webhook(client, secret, event, signature="sha256=" + "0" * 64)
    assert bad.status_code == 401 and bad.json()["code"] == "ESIGN_SIGNATURE_INVALID"
    assert _webhook(client, "wrong-secret", event).status_code == 401
    assert client.get(f"/v1/contracts/{number}", headers=cm).json()["signatures"] == []

    ok = _webhook(client, secret, event)
    assert ok.status_code == 200 and ok.json()["signedBy"] == ["SUPPLIER"]
    assert _webhook(client, secret, event).json()["duplicate"] is True
    done = _webhook(client, secret, {**event, "party": "BUYER", "signerName": "Ganesh Murthy, Contract Manager"})
    assert done.json()["signedBy"] == ["BUYER", "SUPPLIER"] and done.json()["status"] == "COMPLETED"
    signatures = client.get(f"/v1/contracts/{number}", headers=cm).json()["signatures"]
    assert {x["envelope_ref"] for x in signatures} == {envelope["envelopeId"]}
    # Activation is unchanged: both signatures carry the current document hash.
    activated = client.post(f"/v1/contracts/{number}/activate", headers=cm)
    assert activated.status_code == 200 and activated.json()["status"] == "ACTIVE"
    trail = [e["action"] for e in client.get(f"/v1/audit/CONTRACT/{number}", headers=cm).json()]
    assert "ESIGN_ENVELOPE_SENT" in trail and trail.count("SIGNED") == 2
