"""Module updates: GR ↔ ASN of the same PO (F6-03), cancellation notice of a transmitted PO (F5-06), sourcing-event
cancellation and the award-rejection path (F3), word-boundary spend classification (SPD-01) and PAN / normalised-name
duplicate screening at registration (F8-03).

Committed objects are new (a requisition and two DC-330 orders created now, sourcing events on the REQ-2312 test
requirement in July 2028), so the signature case is untouched. Only the outbox events of those objects are relayed,
never the tenant's whole queue. Everything else runs in transactions that roll back.
"""
import os
import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    Asn, AuditEvent, AwardDecision, Notification, OutboxEvent, PrLine, ProcessInstance, PurchaseOrder, SavingsInitiative,
    SourcingEvent, Supplier, Task, Tenant, Timer, AppUser,
)
from app.pic.platform import clock, outbox
from app.pic.platform.auth import Principal, scopes_for
from app.pic.platform.errors import Problem
from app.pic.seed.axion import Scenario
from app.pic.services import order, receiving, requisition, spend, supplier as supplier_svc, transmission
from app.pic.services.master_changes import gstin_check_char

IST = clock.IST
EDI_ID = "TF001EDI"


class _Rollback(Exception):
    pass


def _axn():
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()


def _as(session, local: str) -> None:
    user = session.execute(select(AppUser).where(AppUser.email == f"{local}@axion.example")).scalar_one()
    session.info["principal"] = Principal(user.id, user.tenant_id, "AXN", user.email, user.full_name, list(user.roles),
                                          scopes_for(list(user.roles)), user.attributes or {}, user.supplier_id)
    session.info["user_id"] = user.id


def _relay_own(tenant_id, object_ids) -> int:
    """Dispatch the pending outbox events of the given objects (and of their tasks) only."""
    ids = {str(i) for i in object_ids}
    done = 0
    for _ in range(6):
        with tenant_tx(tenant_id) as s:
            s.info["principal"] = Principal(uuid.UUID(int=0), tenant_id, "", "event-relay", "Event relay", [], set(), agent_code="EVENT_RELAY")
            pending = [e for e in s.execute(select(OutboxEvent).where(OutboxEvent.published_at.is_(None))
                                            .order_by(OutboxEvent.occurred_at, OutboxEvent.id)).scalars()
                       if str(e.object_id) in ids or str((e.payload or {}).get("objectId")) in ids]
            if not pending:
                return done
            for event in pending:
                outbox._dispatch(s, event)
                event.published_at = clock.now()
                done += 1
    return done


def _po(sc: Scenario, now: datetime, qty: str, purpose: str):
    need = (now + timedelta(days=30)).date()
    with sc.act("buyer", now) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="BUFFER_BUILD", purpose_text=purpose, plant="P100",
                                lines=[{"item_type": "MATERIAL", "purchase_type": "STOCK", "material": "DC-330", "qty": qty,
                                        "price_est_minor": 40500, "need_date": need.isoformat(), "storage_location": "0001"}])
        requisition.submit(s, pr)
        pr_id, pr_no = pr.id, pr.number
    sc.approve_all(pr_id, now)
    with sc.act("buyer", now) as s:
        po = order.create_from_requisition(s, requisition=pr_no, lines=[10], supplier_code="TF001", unit_price_minor=40500)[0]
        po_id, number = po.id, po.number
    sc.approve_all(po_id, now, "Manual price as per quotation")
    return po_id, number


@pytest.fixture(scope="module")
def orders(database):
    """Two DC-330 orders transmitted to Trichy Forge over portal + EDI + e-mail, with no EDI gateway and no SMTP."""
    saved_env = {k: os.environ.pop(k) for k in ("PIC_EDI_GATEWAY_URL", "PIC_SMTP_HOST") if k in os.environ}
    tenant_id = _axn()
    with tenant_tx(tenant_id) as s:
        tf = s.execute(select(Supplier).where(Supplier.code == "TF001")).scalar_one()
        previous_channel = dict(tf.order_channel or {})
        tf.order_channel = {"channels": ["PORTAL", "EDI", "EMAIL"], "ediId": EDI_ID, "email": "orders@trichyforge.example"}
    sc = Scenario(tenant_id)
    now = datetime.now(IST).replace(microsecond=0)
    try:
        receive_id, receive_no = _po(sc, now, "300", "GR against ASN test")
        cancel_id, cancel_no = _po(sc, now, "200", "Cancellation notice test")
    finally:
        clock.set_pinned(None)
    with tenant_tx(tenant_id) as s:
        assert s.get(PurchaseOrder, receive_id).status == s.get(PurchaseOrder, cancel_id).status == "TRANSMITTED"
    yield {"tenant": tenant_id, "sc": sc, "receive": (receive_id, receive_no), "cancel": (cancel_id, cancel_no)}
    with tenant_tx(tenant_id) as s:
        s.execute(select(Supplier).where(Supplier.code == "TF001")).scalar_one().order_channel = previous_channel
    os.environ.update(saved_env)


# ---------------------------------------------------------------- 1. F6-03 a goods receipt cites an ASN of its own PO
def test_gr_refuses_an_asn_of_another_po(client, login, orders):
    receive_id, receive_no = orders["receive"]
    cancel_id, _ = orders["cancel"]
    with tenant_tx(orders["tenant"]) as s:
        foreign = s.execute(select(Asn).where(Asn.po_id != receive_id).order_by(Asn.created_at)).scalars().first()
        assert foreign is not None  # the signature case ships against PO-77410
        foreign_po = s.get(PurchaseOrder, foreign.po_id).number
    r = client.post("/v1/goods-receipts", headers=login("receiver"),
                    json={"po": receive_no, "asn": foreign.number, "lines": [{"line": 10, "qty": "1", "batch": "B-FIX-01"}]})
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["code"] == "ASN_PO_MISMATCH" and body["ruleRef"] == "F6-03"
    assert body["asn"] == foreign.number and body["asnPo"] == foreign_po and body["po"] == receive_no
    with tenant_tx(orders["tenant"]) as s:  # nothing was posted
        assert s.get(PurchaseOrder, receive_id).status == "TRANSMITTED"

    with pytest.raises(_Rollback):
        with tenant_tx(orders["tenant"]) as s:
            _as(s, "tf.sales")
            today = clock.today()
            asns = {}
            for po_id in (receive_id, cancel_id):
                po = s.get(PurchaseOrder, po_id)
                order.confirm(s, po, "CONFIRMED")
                asns[po_id] = receiving.create_asn(s, po, lines=[{"line": 10, "qty": "1"}], ship_date=today, expected_date=today)
            _as(s, "receiver")
            po = s.get(PurchaseOrder, receive_id)
            with pytest.raises(Problem) as exc:
                receiving.post_gr(s, po, lines=[{"line": 10, "qty": "1", "batch": "B-FIX-01"}], asn=asns[cancel_id])
            assert exc.value.status == 422 and exc.value.code == "ASN_PO_MISMATCH"
            own = receiving.post_gr(s, po, lines=[{"line": 10, "qty": "1", "batch": "B-FIX-01"}], asn=asns[receive_id])
            assert own.asn_id == asns[receive_id].id and asns[receive_id].status == "RECEIVED"
            plain = receiving.post_gr(s, po, lines=[{"line": 10, "qty": "1", "batch": "B-FIX-02"}])  # no ASN: unchanged behaviour
            assert plain.asn_id is None
            raise _Rollback


# ---------------------------------------------------------------- 2. F5-06 cancellation notice over the supplier's channels
def test_cancelled_po_is_sent_to_the_supplier_over_every_channel(client, login, orders):
    cancel_id, number = orders["cancel"]
    reason = "Requirement withdrawn: model changeover at P100"
    r = client.post(f"/v1/purchase-orders/{number}/cancel", json={"reason": reason}, headers=login("buyer"))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "CANCELLED" and r.json()["from"] == "TRANSMITTED"
    rows = client.get(f"/v1/purchase-orders/{number}/transmissions", headers=login("buyer")).json()
    notices = {t["channel"]: t for t in rows if t["purpose"] == "CANCELLATION"}
    assert len(rows) == 6 and {t["purpose"] for t in rows} == {"ORDER", "CANCELLATION"}
    assert {c: (t["format"], t["status"]) for c, t in notices.items()} == {
        "PORTAL": ("PORTAL_CANCEL", "SENT"), "EDI": ("EDIFACT_CANCEL", "QUEUED"), "EMAIL": ("HTML_EMAIL_CANCEL", "QUEUED")}
    assert notices["EDI"]["recipient"] == EDI_ID and notices["EMAIL"]["recipient"] == "orders@trichyforge.example"

    edi = client.get(f"/v1/purchase-orders/{number}/transmissions/{notices['EDI']['id']}", headers=login("buyer")).json()
    interchange = transmission.parse(edi["document"])
    message = interchange.messages[0]
    seg = {s.tag: s for s in message.segments}
    assert message.type == "ORDCHG" and seg["BGM"].elements[:3] == [["230"], [number], ["1"]]  # 1 = cancellation
    assert seg["FTX"].el(0) == "AAI" and seg["FTX"].el(3) == reason
    assert [s.elements[:2] for s in message.segments if s.tag == "LIN"] == [[["10"], ["2"]]]  # line deleted
    assert edi["segments"]["declared"] == len(message.segments)
    orders_ref = transmission.parse(next(client.get(f"/v1/purchase-orders/{number}/transmissions/{t['id']}", headers=login("buyer")).json()["document"]
                                         for t in rows if t["format"] == "EDIFACT_ORDERS")).reference
    assert interchange.reference != orders_ref  # a new interchange control reference
    portal = client.get(f"/v1/purchase-orders/{number}/transmissions/{notices['PORTAL']['id']}", headers=login("tf.sales")).json()
    assert '"action": "CANCELLED"' in portal["document"] and reason in portal["document"]
    download = client.get(f"/v1/purchase-orders/{number}/transmissions/{notices['EDI']['id']}/document", headers=login("tf.sales"))
    assert download.status_code == 200 and download.headers["content-type"].startswith("application/EDIFACT")

    with tenant_tx(orders["tenant"]) as s:
        event = s.execute(select(OutboxEvent).where(OutboxEvent.topic == "purchase_order.cancelled",
                                                    OutboxEvent.object_id == cancel_id)).scalar_one()
        assert {t["channel"] for t in event.payload["transmissions"]} == {"PORTAL", "EDI", "EMAIL"}
        assert s.execute(select(AuditEvent).where(AuditEvent.object_id == cancel_id, AuditEvent.action == "CANCELLATION_TRANSMITTED")).scalar_one().reason == reason
    _relay_own(orders["tenant"], [cancel_id])
    after = {t["channel"]: t for t in client.get(f"/v1/purchase-orders/{number}/transmissions", headers=login("buyer")).json()
             if t["purpose"] == "CANCELLATION"}
    assert after["EDI"]["status"] == "QUEUED" and after["EDI"]["error"] == "EDI gateway not configured"
    assert after["EMAIL"]["status"] == "QUEUED" and "DISABLED" in after["EMAIL"]["error"]  # shared mailer, no SMTP
    mail = client.get(f"/v1/purchase-orders/{number}/transmissions/{after['EMAIL']['id']}", headers=login("buyer")).json()["document"]
    assert f"{number} (version 1) is cancelled" in mail and reason in mail
    with tenant_tx(orders["tenant"]) as s:
        tf_user = s.execute(select(AppUser.id).where(AppUser.email == "tf.sales@axion.example")).scalar_one()
        notes = s.execute(select(Notification).where(Notification.user_id == tf_user, Notification.object_ref == number,
                                                     Notification.kind == "PO_CANCELLED")).scalars().all()
        assert len(notes) == 1 and reason in notes[0].body
    # Re-sending a queued cancellation stays queued while nothing is configured.
    resent = client.post(f"/v1/purchase-orders/{number}/transmissions/{after['EDI']['id']}/resend", headers=login("buyer"))
    assert resent.status_code == 200 and resent.json()["status"] == "QUEUED"


# ---------------------------------------------------------------- 3/4. F3 award rejection back to evaluation, event cancellation
def at(y, m, d, hh=10, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def _event(client, login, title: str, close_at: datetime, annual: str = "20000", monthly: str = "2000") -> str:
    body = {"type": "RFQ", "title": title, "category": "ALU-DIECAST",
            "lines": [{"requisition": "REQ-2312", "line": 10, "annual_qty": annual, "monthly_qty": monthly}],
            "criteria": [{"code": "PRICE_TCO", "name": "Price / TCO", "weight": 100}], "invitees": [{"supplier": "TF001"}, {"supplier": "KD002"}],
            "close_at": close_at.isoformat(), "baseline_method": "BUDGET", "baseline_price_minor": 42000}
    r = client.post("/v1/sourcing/events", json=body, headers=login("category.head"))
    assert r.status_code == 201, r.text
    return r.json()["number"]


def _award_tasks(client, login, number: str) -> list:
    return [t for t in client.get("/v1/tasks", headers=login("category.manager")).json()
            if t["object_ref"] == number and t["kind"] == "AWARD_APPROVAL"]


def test_award_rejection_returns_to_evaluation_and_cancellation_closes_the_event(client, login):
    tenant_id = _axn()
    head = login("category.head")
    try:
        clock.set_pinned(at(2028, 7, 3, 10))
        number = _event(client, login, "DC-331 cover dual source 2029 (rejection path)", at(2028, 7, 10, 17))
        assert client.post(f"/v1/sourcing/events/{number}/publish", headers=head).status_code == 200
        for who, price in (("tf.sales", "400"), ("kd.sales", "405")):
            r = client.post(f"/v1/sourcing/events/{number}/bids", headers=login(who), json={"lines": [
                {"line": 10, "unit_price": price, "payment_terms_days": 60, "lead_time_days": 14, "capacity_per_month": "5000"}]})
            assert r.status_code == 201, r.text
        clock.set_pinned(at(2028, 7, 10, 17, 5))
        assert client.post(f"/v1/sourcing/events/{number}/close", headers=head).status_code == 200
        first = {x["kind"]: x for x in client.post(f"/v1/sourcing/events/{number}/scenarios", headers=head).json()}
        assert first["LOWEST_COST"]["feasible"] and first["LOWEST_COST"]["allocations"][0]["supplier"] == "TF001"
        award = {"scenario_id": first["LOWEST_COST"]["id"], "conflict_declaration": "No conflict of interest"}
        r = client.post(f"/v1/sourcing/events/{number}/award", json=award, headers=head)
        assert r.status_code == 200 and r.json()["status"] == "AWARD_PENDING"  # ₹80 L ≥ ₹50 L: approval chain

        # F3-08 rejection: back to evaluation, waiting at the scenario step.
        [task] = _award_tasks(client, login, number)
        r = client.post(f"/v1/tasks/{task['id']}/complete", json={"decision": "REJECT", "comment": "Single source; split the volume"},
                        headers=login("category.manager"))
        assert r.status_code == 200, r.text
        event = client.get(f"/v1/sourcing/events/{number}", headers=head).json()
        assert event["status"] == "UNDER_EVALUATION" and [d["status"] for d in event["awardDecisions"]] == ["REJECTED"]
        assert event["process"]["currentStep"] == "F3-06" and not _award_tasks(client, login, number)
        # The scenarios can be rebuilt (the rejected decision keeps its scenario as evidence) and a new award proposed.
        rebuilt = client.post(f"/v1/sourcing/events/{number}/scenarios", headers=head)
        assert rebuilt.status_code == 200, rebuilt.text
        second = {x["kind"]: x for x in rebuilt.json()}
        kept = {s["id"]: s for s in client.get(f"/v1/sourcing/events/{number}", headers=head).json()["scenarios"]}
        assert first["LOWEST_COST"]["id"] in kept and kept[first["LOWEST_COST"]["id"]]["explanation"]["supersededAt"]
        stale = client.post(f"/v1/sourcing/events/{number}/award", json=award, headers=head)
        assert stale.status_code == 422 and stale.json()["ruleRef"] == "SRC-AWARD"
        r = client.post(f"/v1/sourcing/events/{number}/award", headers=head, json={
            "scenario_id": second["CAPACITY_CONSTRAINED"]["id"], "conflict_declaration": "No conflict of interest",
            "rationale": "Dual source within verified capacity"})
        assert r.status_code == 200 and r.json()["status"] == "AWARD_PENDING"
        assert len(_award_tasks(client, login, number)) == 1

        # Cancellation (from AWARD_PENDING): reason, owner / category manager only.
        with tenant_tx(tenant_id) as s:
            event_id = s.execute(select(SourcingEvent.id).where(SourcingEvent.number == number)).scalar_one()
            own_tasks = [t.id for t in s.execute(select(Task).where(Task.object_id == event_id)).scalars()]
            others_open = s.execute(select(Task.id).where(Task.status == "OPEN", Task.object_id != event_id)).scalars().all()
            others_timers = s.execute(select(Timer.id).where(Timer.fired_at.is_(None), Timer.object_id.not_in([event_id, *own_tasks]))).scalars().all()
        url = f"/v1/sourcing/events/{number}/cancel"
        r = client.post(url, json={"reason": "  "}, headers=head)
        assert r.status_code == 422 and r.json()["code"] == "REASON_REQUIRED" and r.json()["ruleRef"] == "SRC-CANCEL"
        assert client.post(url, json={"reason": "x"}, headers=login("buyer")).json()["code"] == "NOT_EVENT_MANAGER"
        assert client.post(url, json={"reason": "x"}, headers=login("tf.sales")).status_code == 403
        clock.set_pinned(at(2028, 7, 12, 11))
        reason = "Drawing revision D replaces the part; requirement re-raised"
        r = client.post(url, json={"reason": reason}, headers=head)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "CANCELLED" and r.json()["cancellation"]["reason"] == reason
        assert r.json()["cancellation"]["from"] == "AWARD_PENDING"
        assert client.post(url, json={"reason": reason}, headers=head).json()["code"] == "ILLEGAL_TRANSITION"

        with tenant_tx(tenant_id) as s:
            assert not s.execute(select(Task).where(Task.object_id == event_id, Task.status == "OPEN")).first()
            assert not s.execute(select(Timer).where(Timer.object_id.in_([event_id, *own_tasks]), Timer.fired_at.is_(None))).first()
            # Only this event's tasks and timers were closed.
            assert set(s.execute(select(Task.id).where(Task.status == "OPEN", Task.object_id != event_id)).scalars()) >= set(others_open)
            assert set(s.execute(select(Timer.id).where(Timer.fired_at.is_(None))).scalars()) >= set(others_timers)
            decisions = s.execute(select(AwardDecision.status).where(AwardDecision.event_id == event_id)
                                  .order_by(AwardDecision.created_at)).scalars().all()
            assert decisions == ["REJECTED", "CANCELLED"]
            instance = s.execute(select(ProcessInstance).where(ProcessInstance.business_id == event_id)).scalar_one()
            assert instance.status == "CANCELLED"
            trail = s.execute(select(AuditEvent).where(AuditEvent.object_id == event_id, AuditEvent.action == "CANCEL")).scalar_one()
            assert trail.reason == reason and trail.after["tasksCancelled"] == 1 and trail.after["from"] == "AWARD_PENDING"
            cancelled = s.execute(select(OutboxEvent).where(OutboxEvent.topic == "sourcing.event.cancelled",
                                                            OutboxEvent.object_id == event_id)).scalar_one()
            assert len(cancelled.payload["inviteeSupplierIds"]) == 2 and cancelled.payload["reason"] == reason
        _relay_own(tenant_id, [event_id])
        with tenant_tx(tenant_id) as s:
            users = dict(s.execute(select(AppUser.email, AppUser.id)).all())
            for who, expected in (("tf.sales", 1), ("kd.sales", 1), ("sla.sales", 0)):
                notes = s.execute(select(Notification).where(Notification.user_id == users[f"{who}@axion.example"],
                                                             Notification.object_ref == number, Notification.kind == "SOURCING_CANCELLED")).scalars().all()
                assert len(notes) == expected, who
            assert s.execute(select(SavingsInitiative.stage).where(SavingsInitiative.source_event_id == event_id)).scalar_one() == "LOST"

        # Supplier portal: listed and shown as cancelled with the reason; no more bids.
        tf = login("tf.sales")
        portal = client.get(f"/v1/sourcing/events/{number}", headers=tf).json()
        assert portal["status"] == "CANCELLED" and portal["cancellation"]["reason"] == reason and "awardDecisions" not in portal
        listed = client.get("/v1/sourcing/events?status=CANCELLED", headers=tf).json()["items"]
        assert number in {e["number"] for e in listed}
        late = client.post(f"/v1/sourcing/events/{number}/bids", headers=tf, json={"lines": [
            {"line": 10, "unit_price": "390", "payment_terms_days": 60, "lead_time_days": 14}]})
        assert late.status_code == 409

        # An awarded event cannot be cancelled; a draft is cancelled without telling anyone.
        assert client.post("/v1/sourcing/events/RFQ-2231/cancel", json={"reason": "x"}, headers=login("category.manager")).json()["code"] == "ILLEGAL_TRANSITION"
        draft = _event(client, login, "DC-331 cover draft withdrawn", at(2028, 7, 20, 17))
        r = client.post(f"/v1/sourcing/events/{draft}/cancel", json={"reason": "Raised twice by mistake"}, headers=head)
        assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
        with tenant_tx(tenant_id) as s:
            draft_id = s.execute(select(SourcingEvent.id).where(SourcingEvent.number == draft)).scalar_one()
            payload = s.execute(select(OutboxEvent.payload).where(OutboxEvent.topic == "sourcing.event.cancelled",
                                                                  OutboxEvent.object_id == draft_id)).scalar_one()
            assert payload["from"] == "DRAFT" and payload["inviteeSupplierIds"] == []
        _relay_own(tenant_id, [draft_id])
        with tenant_tx(tenant_id) as s:
            assert not s.execute(select(Notification).where(Notification.object_ref == draft)).first()
        assert client.get(f"/v1/sourcing/events/{draft}", headers=tf).status_code == 404  # drafts stay invisible
    finally:
        clock.set_pinned(None)


# ---------------------------------------------------------------- 5. SPD-01 keyword classification on word boundaries
def _taxonomy_nodes(reverse: bool = False):
    nodes = [SimpleNamespace(code=code, keywords=keywords) for code, _, level, _, keywords, _ in spend.TAXONOMY if level == 3]
    return list(reversed(nodes)) if reverse else nodes


@pytest.mark.parametrize("text, expected", [
    ("Automotive connector 12-way sealed", "ELECTRONICS"),          # "seal" is not in "sealed"
    ("Security guard services, three shifts", "FACILITIES"),       # "ecu" is not in "security"
    ("PP homopolymer resin granules for injection moulding", "RAW-MATERIALS"),  # "mould" is not in "moulding"
    ("Heat treatment furnace, sealed quench", "CAPEX-MACHINERY"),
    ("Hex bolts M8 x 50 zinc flake", "FASTENERS"),                 # plain plural of a keyword
    ("Hydraulic presses overhaul", "CAPEX-MACHINERY"),             # -es plural
    ("Die cast aluminium bracket for alternator mounting", "ALU-DIECAST"),  # tie: the phrase is more specific
    ("EPDM grommet for harness pass-through", "RUBBER-SEALS"),      # tie: the item, not the "for ..." qualifier
    ("Inbound transport of castings, trip basis", "LOGISTICS"),
    ("Forged flange blank SA105 6 inch", "FORGINGS"),               # tie: earlier taxonomy node
])
def test_classifier_matches_whole_words_and_breaks_ties_deterministically(text, expected):
    for nodes in (_taxonomy_nodes(), _taxonomy_nodes(reverse=True)):  # independent of the order nodes are read in
        category, confidence, alternatives = spend.classify_text(None, text, None, nodes)
        assert category == expected, (text, alternatives)
    assert spend.classify_text(None, "Insecurity sealant mouldings", None, _taxonomy_nodes())[0] == "UNCLASSIFIED"


# ---------------------------------------------------------------- 6. F8-03 same PAN and normalised legal names
def test_legal_name_normalisation():
    n = supplier_svc.normalise_legal_name
    assert n("VAIGAI PRECISION CASTINGS PRIVATE LIMITED") == n("Vaigai Precision Castings Pvt Ltd") == "vaigai precision castings"
    assert n("M/s Thamirabarani Fasteners Pvt. Ltd.") == n("Thamirabarani Fasteners Pvt Ltd")
    assert n("K.P.R. Polymers Pvt Ltd") == n("KPR Polymers Pvt Ltd") == "kpr polymers"
    assert n("Arul & Sons Tooling Works") == n("Arul and Sons Tooling Works")
    assert n("Coromandel Freight Movers L.L.P.") == n("Coromandel Freight Movers LLP") == "coromandel freight movers"
    assert n("The Velan Electro Controls Limited") == "velan electro controls"


def _gstin(state: str, pan: str) -> str:
    return f"{state}{pan}1Z" + gstin_check_char(f"{state}{pan}1Z")


@pytest.fixture
def unpinned():
    yield
    clock.set_pinned(None)  # Scenario.act pins the clock; later test files read the real one


def test_review_routed_free_text_line_stays_unclassified(database, unpinned):
    """HTS/1188 "Preventive maintenance visit – die casting cell" (signature case, operations case 2): the substring matcher
    auto-applied ALU-DIECAST ("die cast" inside "die casting"); on word boundaries it is a tie and goes to the steward, and its
    provisional raw material group SVC-TOOLING is not left on the line as a category (it would become a taxonomy node)."""
    sc = Scenario(_axn())
    with sc.act("category.head", at(2028, 8, 1, 9)) as s:
        from app.pic.models import ClassificationReview, SpendLine, TaxonomyNode
        line = s.execute(select(SpendLine).where(SpendLine.invoice_ref == "HTS/1188")).scalar_one()
        assert line.material_group == "SVC-TOOLING" and line.category == "UNCLASSIFIED"
        review = s.execute(select(ClassificationReview).where(ClassificationReview.spend_line_id == line.id)).scalar_one()
        assert review.status == "OPEN" and review.confidence < 0.80
        assert not s.execute(select(TaxonomyNode).where(TaxonomyNode.code == "SVC-TOOLING")).first()


def test_registration_screening_flags_same_pan_and_normalised_names(database, unpinned):
    sc = Scenario(_axn())
    with pytest.raises(_Rollback):
        with sc.act("supplier.manager", at(2028, 8, 1, 10)) as s:
            def register(code, name, state, pan):
                return supplier_svc.register(s, code=code, legal_name=name, gstin=_gstin(state, pan), pan=pan, state_code=state,
                                             contact_email=f"{code.lower()}@fix.example", categories=[])
            palani = register("FX-01", "Palani Hydraulics Pvt Ltd", "33", "AATCP4456N")
            arul = register("FX-02", "Arul & Sons Tooling Works", "33", "AANFA6620P")
            bhavani = register("FX-03", "Bhavani Steel Tubes Limited", "33", "AAMCB3304H")
            s.flush()
            branch = register("FX-11", "Palani Hydraulics - Bengaluru", "29", "AATCP4456N")   # other-state GSTIN, same PAN
            result = supplier_svc.screen(s, branch, record_step=False)
            assert {"code": palani.code, "reason": "same PAN (another GST registration of the same legal entity)"} in result["duplicates"]
            assert result["outcome"] == "REVIEW"
            again = register("FX-12", "M/s. Arul and Sons Tooling Works", "33", "ABQFA7781K")  # different PAN, same name
            assert {"code": arul.code, "reason": "similar legal name"} in supplier_svc.screen(s, again, record_step=False)["duplicates"]
            export = register("FX-13", "Bhavani Steel Tubes Exports Ltd", "33", "ABTCB6613M")  # separate company
            assert bhavani.code not in {d["code"] for d in supplier_svc.screen(s, export, record_step=False)["duplicates"]}
            raise _Rollback
