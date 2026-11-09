"""D22 default approval decisions on the demo tenants (pack approval_bands): the invoice value bands rule and a CFO for AXN and KAC, AXN invoices
in every band and state, and two sourcing events whose lowest offer expired (award blocked; award with a recorded override).

Runs last of all modules (conftest): the pack turns the bands on for AXN and KAC. KAC is checked when its ERP client pack is loaded (a full
run); alone, the module checks AXN. The documents that existed in AXN before the pack must be byte-identical afterwards.
"""
import hashlib
import json
from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuditEvent, AwardDecision, Invoice, InvoiceException, InvoiceLine, OutboxEvent, PurchaseOrder, SourcingEvent, Task, Tenant,
)
from app.pic.platform import clock, p2p_defaults, rules
from app.pic.platform.audit import verify_chain
from app.pic.seed import datasets
from app.pic.seed.datasets import approval_bands as pack
from app.pic.services import payables
from tests.pic.conftest import PASSWORD

IST = clock.IST
FC, CFO = "FINANCE_CONTROLLER", "CFO"


def _tenants() -> dict:
    with system_tx() as s:
        return {code: tid for code, tid in s.execute(select(Tenant.code, Tenant.id))}


PACK_MONTH = (datetime(2027, 9, 1, tzinfo=IST), datetime(2027, 10, 1, tzinfo=IST))


def _hashes(s, models) -> dict:
    """Row hashes of the documents that are not the pack's own: the pack writes its documents in September 2027 (a stopped earlier run of the
    pack may have left some, which the pack keeps and relays)."""
    out = {}
    for model in models:
        query = select(model).where((model.created_at < PACK_MONTH[0]) | (model.created_at >= PACK_MONTH[1]))
        for row in s.execute(query.order_by(model.id)).scalars():
            values = {c.key: getattr(row, c.key) for c in model.__mapper__.column_attrs}
            out[(model.__tablename__, str(row.id))] = hashlib.sha256(json.dumps(values, default=str, sort_keys=True).encode()).hexdigest()
    return out


@pytest.fixture(scope="module")
def loaded(database):
    ids = _tenants()
    with tenant_tx(ids["AXN"]) as s:
        before = _hashes(s, (Invoice, InvoiceLine, PurchaseOrder, AwardDecision))
    results = datasets.apply_pack("approval_bands", PASSWORD)
    with tenant_tx(ids["AXN"]) as s:
        after = _hashes(s, (Invoice, InvoiceLine, PurchaseOrder, AwardDecision))
    clock.set_pinned(None)
    return {"results": {r["tenant"]: r for r in results}, "before": before, "after": after, "ids": _tenants()}


def _summary(loaded) -> dict:
    row = datasets.loaded("AXN", pack.KEY)
    assert row is not None and row.version == pack.VERSION
    return row.summary


def test_pack_is_registered_last_and_loads(loaded):
    assert "approval_bands" in datasets.PACKS and datasets.load("approval_bands").READY
    axn = loaded["results"]["AXN"]
    assert axn["status"] in ("LOADED", "ALREADY_LOADED")
    kac = loaded["results"]["KAC"]
    assert kac["status"] in ("LOADED", "ALREADY_LOADED") if "KAC" in loaded["ids"] and datasets.loaded("KAC", "erp-client-kac") else \
        kac["status"] in ("SKIPPED", "LOADED", "ALREADY_LOADED")
    again = {r["tenant"]: r["status"] for r in datasets.apply_pack("approval_bands", PASSWORD)}
    assert again["AXN"] == "ALREADY_LOADED"


def test_existing_documents_are_untouched(loaded):
    changed = [k for k, v in loaded["before"].items() if loaded["after"].get(k) != v]
    assert changed == []


def test_bands_rule_is_effective_from_november_2026(loaded):
    with tenant_tx(loaded["ids"]["AXN"]) as s:
        rule = rules.resolve(s, pack.RULE_KEY, on=date(2027, 9, 21), company_code="1000")
        assert rule.version == pack.RULE_VERSION and rule.body["bands"] == p2p_defaults.INVOICE_APPROVAL_BANDS["bands"]
        before = rules.resolve(s, pack.RULE_KEY, on=date(2026, 10, 31), company_code="1000")
        assert before.version != pack.RULE_VERSION and before.body["bands"] == []
        trail = s.execute(select(AuditEvent).where(AuditEvent.action == "VERSION_CREATED",
                                                   AuditEvent.object_ref == f"{pack.RULE_KEY}@{pack.RULE_VERSION}")).scalars().all()
        assert len(trail) == 1
        assert verify_chain(s)["valid"] is True


def test_cfo_user_signs_in_and_sees_the_waiting_invoice(loaded, client, login):
    with tenant_tx(loaded["ids"]["AXN"]) as s:
        cfo = s.execute(select(AppUser).where(AppUser.email == "cfo@axion.example")).scalar_one()
        assert cfo.roles == [CFO] and cfo.mfa_enrolled is True
    inbox = client.get("/v1/tasks", headers=login("cfo"))
    assert inbox.status_code == 200
    refs = {t["object_ref"]: t for t in inbox.json() if t["kind"] == "INVOICE_APPROVAL"}
    invoices = _summary(loaded)["invoices"]
    assert invoices["CFO_PENDING"]["invoice"] in refs and refs[invoices["CFO_PENDING"]["invoice"]]["candidate_role"] == CFO
    assert invoices["FC_PENDING"]["invoice"] not in refs                         # the controller's step is not the CFO's
    fc_inbox = {t["object_ref"] for t in client.get("/v1/tasks", headers=login("finance.controller")).json()}
    assert invoices["FC_PENDING"]["invoice"] in fc_inbox and invoices["CFO_PENDING"]["invoice"] not in fc_inbox


@pytest.mark.parametrize("key, status, chain, waiting", [
    ("AP_ONLY", "APPROVED", [], []),
    ("FC_APPROVED", "APPROVED", [FC], []),
    ("FC_PENDING", "MATCHED", [FC], [FC]),
    ("CFO_PENDING", "MATCHED", [FC, CFO], [CFO]),
    ("CFO_APPROVED", "APPROVED", [FC, CFO], []),
    ("CFO_REJECTED", "EXCEPTION", [FC, CFO], []),
])
def test_invoices_in_every_band_and_state(loaded, key, status, chain, waiting):
    number = next(c[3] for c in pack.CASES if c[0] == key)
    with tenant_tx(loaded["ids"]["AXN"]) as s:
        invoice = s.execute(select(Invoice).where(Invoice.supplier_invoice_no == number)).scalar_one()
        state = payables.approval_state(s, invoice)
        assert invoice.status == status and state["requiredChain"] == chain
        assert [st["role"] for st in state["steps"] if st["status"] == "OPEN"] == waiting
        gross = int(invoice.gross_minor)
        band = 0 if gross < 10 * pack.L else 1 if gross < 100 * pack.L else 2
        assert band == len(chain)
        if key == "CFO_APPROVED":
            cfo = s.execute(select(AppUser.id).where(AppUser.email == "cfo@axion.example")).scalar_one()
            assert invoice.approved_by == cfo and state["status"] == "APPROVED"
        if key == "CFO_REJECTED":
            exc = s.execute(select(InvoiceException).where(InvoiceException.invoice_id == invoice.id, InvoiceException.status == "OPEN")).scalar_one()
            assert exc.type == "APPROVAL" and exc.detail.startswith("CFO rejected the invoice") and invoice.payment_block
            assert state["status"] == "REJECTED"
        if waiting:
            task = s.execute(select(Task).where(Task.object_id == invoice.id, Task.status == "OPEN")).scalar_one()
            assert task.candidate_role == waiting[0] and task.due_at is not None


def test_award_on_the_expired_offer_was_blocked_and_is_refused_by_the_api(loaded, client, login):
    events = _summary(loaded)["events"]
    blocked = events["BLOCKED"]
    assert blocked["status"] == "UNDER_EVALUATION" and blocked["blocked"] == "BID_OFFER_EXPIRED" and blocked["expiredBids"] == ["TF001"]
    with tenant_tx(loaded["ids"]["AXN"]) as s:
        event = s.execute(select(SourcingEvent).where(SourcingEvent.number == blocked["event"])).scalar_one()
        assert event.status == "UNDER_EVALUATION"
        assert not s.execute(select(AwardDecision).where(AwardDecision.event_id == event.id)).first()
        assert s.execute(select(AuditEvent).where(AuditEvent.object_id == event.id, AuditEvent.action == "AWARD_BLOCKED_OFFER_EXPIRED")).first()
    headers = login("category.head")
    view = client.get(f"/v1/sourcing/events/{blocked['event']}", headers=headers).json()
    scenario = next(x for x in view["scenarios"] if x["kind"] == "LOWEST_COST")
    clock.set_pinned(datetime(2027, 9, 29, 11, tzinfo=IST))
    try:
        r = client.post(f"/v1/sourcing/events/{blocked['event']}/award", json={"scenario_id": scenario["id"], "conflict_declaration": "No conflict"},
                        headers=headers)
        assert r.status_code == 409 and r.headers["content-type"].startswith("application/problem+json")
        body = r.json()
        assert body["code"] == "BID_OFFER_EXPIRED" and body["expiredBids"][0]["supplier"] == "TF001"
        assert body["extendValidity"]["path"].endswith("/rounds") and body["overrideAllowed"] is True
        short = client.post(f"/v1/sourcing/events/{blocked['event']}/award", json={"scenario_id": scenario["id"], "conflict_declaration": "No conflict",
                                                                                   "expired_offer_override": "price holds"}, headers=headers)
        assert short.status_code == 422 and short.json()["code"] == "REASON_REQUIRED"
        buyer = client.post(f"/v1/sourcing/events/{blocked['event']}/award", json={"scenario_id": scenario["id"], "conflict_declaration": "No conflict",
                                                                                   "expired_offer_override": "x" * 40}, headers=login("buyer"))
        assert buyer.status_code == 403
    finally:
        clock.set_pinned(None)
    with tenant_tx(loaded["ids"]["AXN"]) as s:
        assert s.execute(select(SourcingEvent.status).where(SourcingEvent.number == blocked["event"])).scalar_one() == "UNDER_EVALUATION"


def test_award_with_a_recorded_override(loaded):
    from app.pic.events import catalogue
    overridden = _summary(loaded)["events"]["OVERRIDDEN"]
    assert overridden["status"] == "AWARDED" and overridden["decision"] == "APPROVED"
    with tenant_tx(loaded["ids"]["AXN"]) as s:
        event = s.execute(select(SourcingEvent).where(SourcingEvent.number == overridden["event"])).scalar_one()
        decision = s.execute(select(AwardDecision).where(AwardDecision.event_id == event.id)).scalar_one()
        exc = next(e for e in decision.exceptions if e["code"] == "BID_OFFER_EXPIRED")
        assert exc["override"]["byEmail"] == "category.head@axion.example" and "TF/SC/2027/311" in exc["override"]["reason"]
        assert exc["override"]["bids"][0]["supplier"] == "TF001" and exc["override"]["bids"][0]["validUntil"] == "2027-09-18"
        assert s.execute(select(AuditEvent).where(AuditEvent.object_id == event.id, AuditEvent.action == "AWARD_EXPIRED_OFFER_OVERRIDDEN")).first()
        emitted = s.execute(select(OutboxEvent).where(OutboxEvent.object_id == event.id,
                                                      OutboxEvent.topic == "sourcing.award.offer_expiry_overridden")).scalar_one()
        assert catalogue.validate(emitted.topic, emitted.payload) == []
        approvals = s.execute(select(Task).where(Task.object_id == event.id, Task.kind == "AWARD_APPROVAL")).scalars().all()
        approver_ids = {t.completed_by for t in approvals if t.decision == "APPROVE"}
        head = s.execute(select(AppUser.id).where(AppUser.email == "category.head@axion.example")).scalar_one()
        assert approvals and head not in approver_ids                      # the overrider did not approve his own override


def test_kac_rule_and_cfo_when_kac_is_loaded(loaded):
    if "KAC" not in loaded["ids"] or datasets.loaded("KAC", "erp-client-kac") is None:
        assert loaded["results"]["KAC"]["status"] == "SKIPPED"
        return
    with tenant_tx(loaded["ids"]["KAC"]) as s:
        rule = rules.resolve(s, pack.RULE_KEY, on=date(2027, 1, 4))
        assert rule.version == pack.RULE_VERSION
        cfo = s.execute(select(AppUser).where(AppUser.email == "cfo@kaveri-auto.example")).scalar_one()
        assert cfo.roles == [CFO]


def test_prerequisites_and_unknown_tenant(monkeypatch):
    with pytest.raises(ValueError):
        pack.apply("ZZZ", PASSWORD)
    assert pack.PREREQUISITES["AXN"] and pack.REQUIRES == {}
    pack._check_prerequisites("AXN")                                   # the signature case of this release is loaded
    monkeypatch.setitem(pack.PREREQUISITES, "AXN", {"no-such-dataset": "1"})
    with pytest.raises(RuntimeError, match="no-such-dataset"):
        pack._check_prerequisites("AXN")
