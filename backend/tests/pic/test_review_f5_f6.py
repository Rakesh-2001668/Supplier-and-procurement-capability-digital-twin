"""Review fixes F5 purchase order → F6 receipt / service entry (M08/M09): multi-lot usage decisions, GR reversal guards,
SES value cap, positive quantities, change-order approval (P07 / value band), partly received orders (change, re-confirmation,
change requests, short-close), mixed-lot reversal, per-version confirmation SLA, cancellation guards and paths, ERP
cancellation after a retried release, replacement of rejected goods, schedule edits after transmission, e-way bill threshold,
idempotent ASN / SES and unknown lines.

Almost everything runs in transactions that roll back (orders created, approved, received and decided inside one
transaction, switching users), so the signature case and the KPIs other test files check are untouched. Only the API
idempotency test commits: one small FK-M8-50 order and one service order of its own, whose open tasks it closes again.
"""
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, Asn, AuditEvent, Contract, ContractLine, GoodsReceipt, GrLine, InspectionLot, IntegrationMessage, Invoice, OutboxEvent,
    PoConfirmation, PoLine, PoTransmission, PrLine, PurchaseOrder, ReturnDelivery, RuleSet, ServiceEntry, Stock, StockMovement, Supplier,
    Task, Tenant, Timer,
)
from app.pic.platform import clock, integration, workflow
from app.pic.platform.auth import Principal, scopes_for
from app.pic.platform.errors import Problem
from app.pic.seed.axion import ROLE_USER, Scenario
from app.pic.services import order, payables, receiving, requisition, source, transmission

IST = clock.IST


class _Rollback(Exception):
    pass


def _axn():
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()


def _as(s, local: str) -> None:
    user = s.execute(select(AppUser).where(AppUser.email == f"{local}@axion.example")).scalar_one()
    s.info["principal"] = Principal(user.id, user.tenant_id, "AXN", user.email, user.full_name, list(user.roles),
                                    scopes_for(list(user.roles)), user.attributes or {}, user.supplier_id)
    s.info["user_id"] = user.id


def _approve(s, object_id, comment: str = "Approved", kind: str = None) -> int:
    """Complete every open approval task of one object in this transaction, as the role's user (like Scenario.approve_all)."""
    done = 0
    for _ in range(12):
        query = select(Task).where(Task.object_id == object_id, Task.status == "OPEN")
        if kind:
            query = query.where(Task.kind == kind)
        tasks = s.execute(query.order_by(Task.sequence)).scalars().all()
        if not tasks:
            return done
        for task in tasks:
            candidates = ROLE_USER[task.candidate_role] if isinstance(ROLE_USER[task.candidate_role], list) else [ROLE_USER[task.candidate_role]]
            for who in candidates:
                _as(s, who)
                if workflow.can_work(s.info["principal"], task) is None:
                    workflow.complete(s, task.id, "APPROVE", comment)
                    done += 1
                    break
    return done


def _need(days: int = 30) -> date:
    return clock.today() + timedelta(days=days)


def _po(s, lines: list[tuple], supplier: str = "TF001", purpose: str = "Review F5/F6 test", contract: str = None,
        unit_price_minor: int = None) -> PurchaseOrder:
    """lines: (material, qty, price_est_minor). Created, approved and transmitted inside the caller's transaction."""
    _as(s, "buyer")
    pr = requisition.create(s, origin="MANUAL", purpose_code="BUFFER_BUILD", purpose_text=purpose, plant="P100",
                            lines=[{"item_type": "MATERIAL", "purchase_type": "STOCK", "material": m, "qty": str(q), "price_est_minor": p,
                                    "need_date": _need().isoformat(), "storage_location": "0001"} for m, q, p in lines])
    requisition.submit(s, pr)
    _approve(s, pr.id)
    _as(s, "buyer")
    po = order.create_from_requisition(s, requisition=pr.number, lines=[10 * (i + 1) for i in range(len(lines))],
                                       supplier_code=None if contract else supplier, contract_ref=contract, unit_price_minor=unit_price_minor)[0]
    _approve(s, po.id, "Price as per quotation")
    assert po.status == "TRANSMITTED", po.status
    return po


def _service_po(s, hours: str = "10", rate_minor: int = 300_000) -> PurchaseOrder:
    _as(s, "requester")
    pr = requisition.create(s, origin="MANUAL", purpose_code="MAINTENANCE", purpose_text="Review F5/F6 service test", plant="P100",
                            lines=[{"item_type": "FREE_TEXT", "purchase_type": "SERVICE", "description": "Die polishing (T&M) – review test",
                                    "material_group": "SVC-TOOLING", "category": "TOOLING-SERVICES", "qty": hours, "uom": "H",
                                    "price_est_minor": rate_minor, "account_assignment_type": "COST_CENTER", "account_assignment_code": "4100",
                                    "need_date": _need().isoformat(),
                                    "quotes": [{"supplier": "HTS004", "reference": "HTS/Q/REVIEW", "date": clock.today().isoformat()}]}])
    requisition.submit(s, pr)
    _approve(s, pr.id)
    _as(s, "buyer")
    po = order.create_from_requisition(s, requisition=pr.number, lines=[10], supplier_code="HTS004", unit_price_minor=rate_minor)[0]
    _approve(s, po.id, "Rate as per quote")
    _as(s, "hts.service")
    order.confirm(s, po, "CONFIRMED")
    return po


def _confirm(s, po, who: str = "tf.sales"):
    _as(s, who)
    return order.confirm(s, po, "CONFIRMED")


def _lines(s, po) -> dict:
    return {l.line_no: l for l in order.lines_of(s, po)}


def _lots(s, gr) -> list[InspectionLot]:
    return s.execute(select(InspectionLot).where(InspectionLot.gr_id == gr.id).order_by(InspectionLot.number)).scalars().all()


def _stock(s, material: str, stock_type: str, batch: str) -> Decimal:
    from app.pic.models import Material
    material_id = s.execute(select(Material.id).where(Material.number == material)).scalar_one()
    row = s.execute(select(Stock).where(Stock.material_id == material_id, Stock.stock_type == stock_type, Stock.batch == batch,
                                       Stock.plant == "P100")).scalar_one_or_none()
    return row.qty if row is not None else Decimal(0)


def _problem(fn, *args, **kwargs) -> Problem:
    with pytest.raises(Problem) as exc:
        fn(*args, **kwargs)
    return exc.value


def _batch(tag: str) -> str:
    return f"RV-{tag}-{uuid.uuid4().hex[:6].upper()}"


@pytest.fixture
def tx(database):
    """One transaction that always rolls back."""
    holder = {}
    with pytest.raises(_Rollback):
        with tenant_tx(_axn()) as s:
            holder["s"] = s
            yield s
            raise _Rollback
    clock.set_pinned(None)


# ---------------------------------------------------------------- 1. multi-lot receipt: decided when the last lot is
def test_receipt_with_two_quality_lots_is_decided_by_the_last_lot(tx):
    s = tx
    po = _po(s, [("DC-330", 100, 40500), ("DC-331", 100, 21500)])
    _confirm(s, po)
    _as(s, "receiver")
    b1, b2 = _batch("A"), _batch("B")
    gr = receiving.post_gr(s, po, lines=[{"line": 10, "qty": "100", "batch": b1}, {"line": 20, "qty": "100", "batch": b2}])
    assert gr.status == "QUALITY_HOLD"
    first, second = _lots(s, gr)
    _as(s, "quality.inspector")
    result = receiving.usage_decision(s, first, accepted=Decimal(100), rejected=Decimal(0))
    assert result["status"] == "QUALITY_HOLD" and result["openLots"] == [second.number]
    assert _stock(s, "DC-330", "UNRESTRICTED", b1) == 100 and _stock(s, "DC-331", "QUALITY", b2) == 100
    assert not s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == f"GR|{gr.number}")).first()
    assert not s.execute(select(OutboxEvent).where(OutboxEvent.topic == "quality.usage_decision", OutboxEvent.object_id == gr.id)).first()
    instance = workflow.find(s, "GOODS_RECEIPT", gr.id, receiving.PROCESS)
    assert instance.status == "RUNNING"
    result = receiving.usage_decision(s, second, accepted=Decimal(90), rejected=Decimal(10), defect_code="POROSITY", reason="Gas porosity at boss")
    assert result["status"] == "PARTIALLY_REJECTED" and result["openLots"] == [] and result["returnDelivery"]
    erp = s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == f"GR|{gr.number}")).scalar_one()
    assert erp.status == "POSTED" and {Decimal(l["accepted"]) for l in erp.payload["lines"]} == {Decimal(100), Decimal(90)}
    [event] = s.execute(select(OutboxEvent).where(OutboxEvent.topic == "quality.usage_decision", OutboxEvent.object_id == gr.id)).scalars().all()
    assert (event.payload["lot"], Decimal(event.payload["accepted"]), Decimal(event.payload["rejected"])) == (second.number, Decimal(190), Decimal(10))
    assert instance.status == "COMPLETED"
    lines = _lines(s, po)
    assert (lines[10].accepted_qty, lines[20].accepted_qty, lines[20].rejected_qty) == (100, 90, 10)


def test_receipt_with_two_lots_all_accepted_and_all_rejected(tx):
    s = tx
    po = _po(s, [("DC-330", 40, 40500), ("DC-331", 40, 21500)])
    _confirm(s, po)
    _as(s, "receiver")
    gr = receiving.post_gr(s, po, lines=[{"line": 10, "qty": "40", "batch": _batch("C")}, {"line": 20, "qty": "40", "batch": _batch("D")}])
    first, second = _lots(s, gr)
    _as(s, "quality.inspector")
    receiving.usage_decision(s, first, accepted=Decimal(0), rejected=Decimal(40), defect_code="COLD_SHUT", reason="Cold shuts")
    assert gr.status == "QUALITY_HOLD"
    receiving.usage_decision(s, second, accepted=Decimal(0), rejected=Decimal(40), defect_code="COLD_SHUT", reason="Cold shuts")
    assert gr.status == "REJECTED"


# ---------------------------------------------------------------- 2. no reversal while an invoice references the receipt
def test_reversal_blocked_by_any_invoice_that_is_not_rejected(tx, client, login):
    s = tx
    po = _po(s, [("FK-M8-50", 100, 1250)])
    _confirm(s, po)
    _as(s, "receiver")
    gr = receiving.post_gr(s, po, lines=[{"line": 10, "qty": "100"}])
    assert gr.status == "ACCEPTED"
    _as(s, "tf.sales")
    invoice = payables.capture(s, supplier="TF001", supplier_invoice_no=f"TF/RV/{uuid.uuid4().hex[:6]}", invoice_date=clock.today(),
                               channel="PORTAL", lines=[{"po": po.number, "po_line": 10, "qty": "100", "unit_price": "12.50", "gst_rate": "18"}])
    assert invoice.status not in ("POSTED", "PAID", "REJECTED")
    _as(s, "receiver")
    problem = _problem(receiving.reverse_gr, s, gr, "Posted against the wrong delivery note")
    assert problem.status == 409 and problem.code == "RECEIPT_INVOICED" and problem.rule_ref == "RCV-REVERSE" and invoice.number in problem.detail
    invoice.status = "REJECTED"  # (rolled back) a rejected invoice no longer holds the receipt
    s.flush()
    reversed_gr = receiving.reverse_gr(s, gr, "Posted against the wrong delivery note")
    assert reversed_gr.status == "REVERSED" and _lines(s, po)[10].received_qty == 0


# ---------------------------------------------------------------- 3 and 10. SES value cap and cancellation guard
def test_ses_cap_counts_sheets_in_approval_and_is_rechecked_at_approval(tx):
    s = tx
    po = _service_po(s, hours="10", rate_minor=300_000)  # ₹30,000
    _as(s, "hts.service")
    first = receiving.create_ses(s, po, method="TIME_MATERIAL", period_from=clock.today(), period_to=clock.today(),
                                 lines=[{"line": 10, "qty": "6", "unit_rate": "3000"}])
    receiving.submit_ses(s, first)
    problem = _problem(receiving.create_ses, s, po, method="TIME_MATERIAL", period_from=clock.today(), period_to=clock.today(),
                       lines=[{"line": 10, "qty": "5", "unit_rate": "3000"}])
    assert problem.code == "RULE_VIOLATION" and "in approval" in problem.detail
    second = receiving.create_ses(s, po, method="TIME_MATERIAL", period_from=clock.today(), period_to=clock.today(),
                                  lines=[{"line": 10, "qty": "4", "unit_rate": "3000"}])
    receiving.submit_ses(s, second)
    unknown = _problem(receiving.create_ses, s, po, method="TIME_MATERIAL", period_from=clock.today(), period_to=clock.today(),
                       lines=[{"line": 99, "qty": "1"}])
    assert unknown.status == 422 and unknown.code == "UNKNOWN_LINE"
    # 10. Cancelling the order is refused while service entries are in approval (they would stay approvable).
    _as(s, "buyer")
    blocked = _problem(order.cancel, s, po, "Scope withdrawn")
    assert blocked.status == 409 and blocked.code == "SERVICE_ENTRIES_OPEN" and set(blocked.extra["serviceEntries"]) == {first.number, second.number}
    # The line value drops (8 h) while both sheets are in approval: the second approval would overrun it.
    order.change_order(s, po, [{"line": 10, "qty": "8"}], reason="Scope reduced to 8 h")
    assert _approve(s, first.id, "Timesheet verified") == 1 and first.status == "APPROVED"
    task = s.execute(select(Task).where(Task.object_id == second.id, Task.status == "OPEN")).scalar_one()
    _as(s, "service.owner")
    with pytest.raises(Problem) as exc:
        with s.begin_nested():
            workflow.complete(s, task.id, "APPROVE", "Timesheet verified")
    assert exc.value.code == "RULE_VIOLATION" and exc.value.rule_ref == "RCV-SES"


def _extra(problem: Problem) -> dict:
    return getattr(problem, "extra", {}) or {}


# ---------------------------------------------------------------- 4. positive quantities (API and service)
@pytest.mark.parametrize("path, body", [
    ("/v1/goods-receipts", {"po": "PO-77410", "lines": [{"line": 10, "qty": "-5"}]}),
    ("/v1/goods-receipts", {"po": "PO-77410", "lines": [{"line": 10, "qty": "0"}]}),
    ("/v1/goods-receipts", {"po": "PO-77410", "lines": []}),
    ("/v1/asns", {"po": "PO-77410", "ship_date": "2026-11-01", "expected_date": "2026-11-02", "lines": [{"line": 10, "qty": "-1"}]}),
    ("/v1/service-entries", {"po": "PO-77410", "method": "UNIT_RATE", "period_from": "2026-11-01", "period_to": "2026-11-01",
                             "lines": [{"line": 10, "qty": "-2"}]}),
    ("/v1/service-entries", {"po": "PO-77410", "method": "UNIT_RATE", "period_from": "2026-11-01", "period_to": "2026-11-01",
                             "lines": [{"line": 10, "qty": "1", "unit_rate": "-5"}]}),
    ("/v1/inspection-lots/QL-2210/usage-decision", {"accepted": "-1", "rejected": "0"}),
    ("/v1/inspection-lots/QL-2210/usage-decision", {"accepted": "10", "rejected": "-10"}),
])
def test_api_rejects_negative_and_zero_quantities(client, login, path, body):
    who = {"/v1/goods-receipts": "receiver", "/v1/asns": "tf.sales", "/v1/service-entries": "hts.service"}.get(path, "quality.inspector")
    r = client.post(path, json=body, headers=login(who))
    assert r.status_code == 422, r.text


def test_services_reject_negative_and_zero_quantities(tx):
    s = tx
    po = _po(s, [("FK-M8-50", 50, 1250)])
    _confirm(s, po)
    _as(s, "tf.sales")
    for qty in ("0", "-3"):
        problem = _problem(receiving.create_asn, s, po, lines=[{"line": 10, "qty": qty}], ship_date=clock.today(), expected_date=clock.today())
        assert problem.code == "INVALID_QUANTITY"
    _as(s, "receiver")
    assert _problem(receiving.post_gr, s, po, lines=[{"line": 10, "qty": "-5"}]).code == "INVALID_QUANTITY"
    assert _problem(receiving.post_gr, s, po, lines=[{"line": 30, "qty": "5"}]).code == "UNKNOWN_LINE"  # 16f: was a KeyError (500)
    assert _lines(s, po)[10].received_qty == 0
    dc = _po(s, [("DC-330", 10, 40500)])
    _confirm(s, dc)
    _as(s, "receiver")
    gr = receiving.post_gr(s, dc, lines=[{"line": 10, "qty": "10", "batch": _batch("N")}])
    _as(s, "quality.inspector")
    problem = _problem(receiving.usage_decision, s, _lots(s, gr)[0], accepted=Decimal(15), rejected=Decimal(-5), defect_code="X", reason="y")
    assert problem.code == "INVALID_QUANTITY"


# ---------------------------------------------------------------- 5. change orders: P07 deviation and PO approval
def _contract_po(s):
    contract = s.execute(select(Contract).where(Contract.number == "SA-5520")).scalar_one()
    if contract.status not in ("ACTIVE", "EXPIRING") or not (contract.valid_from <= _need() <= contract.valid_to):
        pytest.skip("SA-5520 is not valid for a call-off today")
    po = _po(s, [("DC-330", 200, 39800)], contract="SA-5520")
    line = _lines(s, po)[10]
    price = source.contract_price(s, line.contract_line_id, line.need_date).unit_price_minor
    return po, line, price


def test_change_order_price_deviation_needs_reason_and_approval(tx):
    s = tx
    po, line, contract_price = _contract_po(s)
    tolerance = Decimal(po.tolerance.get("price_pct", 0))
    high = Decimal(contract_price) * (1 + tolerance / 100) / 100 + Decimal("5")  # rupees, beyond tolerance
    _as(s, "buyer")
    problem = _problem(order.change_order, s, po, [{"line": 10, "unit_price": str(high)}], reason="Alloy surcharge")
    assert problem.code == "RULE_VIOLATION" and problem.rule_ref == "P07"
    transmissions_before = len(s.execute(select(PoTransmission).where(PoTransmission.po_id == po.id)).scalars().all())
    result = order.change_order(s, po, [{"line": 10, "unit_price": str(high)}], reason="Alloy surcharge",
                                deviation_reason="LME aluminium +9% since award; surcharge agreed for one lot")
    assert result["approval"] == "PENDING" and result["version"] == 1 and "PRICE_DEVIATION" in result["triggers"]
    assert po.version == 1 and line.unit_price_minor == contract_price  # nothing applied, nothing sent
    assert len(s.execute(select(PoTransmission).where(PoTransmission.po_id == po.id)).scalars().all()) == transmissions_before
    assert _problem(order.change_order, s, po, [{"line": 10, "qty": "150"}], reason="x").code == "CHANGE_PENDING_APPROVAL"
    assert _approve(s, po.id, "Surcharge accepted for this lot", kind="PO_CHANGE_APPROVAL") == 1
    assert po.version == 2 and po.status == "TRANSMITTED" and line.unit_price_minor == int(high * 100)
    assert line.price_deviation is True and line.deviation_reason.startswith("LME aluminium")
    v2 = s.execute(select(PoTransmission).where(PoTransmission.po_id == po.id, PoTransmission.po_version == 2)).scalars().all()
    assert {t.channel for t in v2} >= {"PORTAL"}
    # A price back within tolerance clears the deviation and needs no approval.
    _as(s, "buyer")
    result = order.change_order(s, po, [{"line": 10, "unit_price": str(Decimal(contract_price) / 100)}], reason="Surcharge withdrawn")
    assert "approval" not in result and po.version == 3 and line.price_deviation is False and line.deviation_reason is None


def _enable_band_reapproval(s) -> None:
    for rs in s.execute(select(RuleSet).where(RuleSet.key == "PO-APPROVAL")).scalars():
        rs.body = {**rs.body, "changeApproval": {"onBandIncrease": True}}
    s.flush()


def test_change_order_into_a_higher_band_is_approved_first_when_enabled(tx):
    s = tx
    po = _po(s, [("DC-330", 1000, 40500)])  # ₹4.05 L: buyer band
    _confirm(s, po)
    _as(s, "buyer")
    # The seeded rule set enables it (BP §14.1: approval by value); signature case 7 is approved by the procurement head.
    assert any((rs.body.get("changeApproval") or {}).get("onBandIncrease")
               for rs in s.execute(select(RuleSet).where(RuleSet.key == "PO-APPROVAL")).scalars())
    _enable_band_reapproval(s)
    _as(s, "buyer")
    result = order.change_order(s, po, [{"line": 10, "qty": "1300"}], reason="OEM pull-in")  # ₹5.27 L: buyer + procurement head
    assert result["approval"] == "PENDING" and result["triggers"] == ["BAND_INCREASE"] and result["chain"] == ["BUYER", "PROCUREMENT_HEAD"]
    assert po.version == 1 and po.status == "CONFIRMED" and _lines(s, po)[10].qty == 1000
    assert _approve(s, po.id, "Pull-in confirmed by sales", kind="PO_CHANGE_APPROVAL") == 2
    assert po.version == 2 and po.status == "TRANSMITTED" and _lines(s, po)[10].qty == 1300
    # Reductions and date changes need no approval.
    _as(s, "buyer")
    result = order.change_order(s, po, [{"line": 10, "qty": "1200", "need_date": _need(35).isoformat()}], reason="Trimmed")  # ₹4.86 L
    assert "approval" not in result and po.version == 3
    # Back above ₹5 L: approval again; a rejected approval leaves the version in force.
    assert order.change_order(s, po, [{"line": 10, "qty": "1250"}], reason="Top-up")["approval"] == "PENDING"
    task = s.execute(select(Task).where(Task.object_id == po.id, Task.kind == "PO_CHANGE_APPROVAL", Task.status == "OPEN")).scalar_one()
    _as(s, "buyer.lead")
    workflow.complete(s, task.id, "REJECT", "Top-up not budgeted")
    assert po.version == 3 and _lines(s, po)[10].qty == 1200
    assert s.execute(select(AuditEvent).where(AuditEvent.object_id == po.id, AuditEvent.action == "CHANGE_APPROVAL_REJECTED")).scalar_one()


# ---------------------------------------------------------------- 6. partly received: change, re-confirmation, PCR, short-close
def test_partly_received_order_can_be_changed_reconfirmed_and_changed_by_request(tx):
    s = tx
    po = _po(s, [("FK-M8-50", 100, 1250)])
    _confirm(s, po)
    _as(s, "receiver")
    receiving.post_gr(s, po, lines=[{"line": 10, "qty": "40"}])
    assert po.status == "PARTIALLY_RECEIVED"
    _as(s, "buyer")
    assert _problem(order.change_order, s, po, [{"line": 10, "qty": "30"}], reason="x").code == "BELOW_RECEIVED"
    result = order.change_order(s, po, [{"line": 10, "qty": "80"}], reason="Demand reduced")
    assert result["version"] == 2 and po.status == "PARTIALLY_RECEIVED" and order.awaiting_confirmation(s, po)
    assert s.execute(select(Timer).where(Timer.object_id == po.id, Timer.kind == "PO_CONFIRMATION_SLA",
                                         Timer.payload["version"].astext == "2")).scalar_one()
    _confirm(s, po)
    assert po.status == "PARTIALLY_RECEIVED" and not order.awaiting_confirmation(s, po)
    # PO-03 supplier change request from PARTIALLY_RECEIVED.
    _as(s, "tf.sales")
    pcr = order.request_change(s, po, [{"line": 10, "qty": "60"}], "Wire rod shortage; 20 kits less")
    _approve(s, po.id, "Accepted", kind="PO_CHANGE_REQUEST")
    assert pcr.status == "ACCEPTED" and pcr.result_version == 3 and _lines(s, po)[10].qty == 60
    # Reduced to what was received: the order is fully received.
    _as(s, "buyer")
    order.change_order(s, po, [{"line": 10, "qty": "40"}], reason="Balance not needed")
    assert po.status == "RECEIVED" and po.version == 4


def test_short_close_after_the_received_value_is_invoiced(tx):
    s = tx
    po = _po(s, [("FK-M8-50", 100, 1250)])
    _confirm(s, po)
    _as(s, "receiver")
    receiving.post_gr(s, po, lines=[{"line": 10, "qty": "40"}])
    _as(s, "buyer")
    blocked = _problem(order.short_close, s, po, "Supplier cannot deliver the balance")
    assert blocked.code == "RULE_VIOLATION" and "to invoice" in blocked.detail
    _as(s, "tf.sales")
    number = f"TF/RV/{uuid.uuid4().hex[:6]}"
    invoice = payables.capture(s, supplier="TF001", supplier_invoice_no=number, invoice_date=clock.today(), channel="PORTAL",
                               lines=[{"po": po.number, "po_line": 10, "qty": "40", "unit_price": "12.50", "gst_rate": "18"}])
    assert invoice.status == "MATCHED", invoice.status
    _as(s, "ap.clerk")
    payables.approve(s, invoice)
    payables.post(s, invoice, f"AXN|1000|TF001|{number}")
    line = _lines(s, po)[10]
    pr_line = s.execute(select(PrLine).where(PrLine.requisition_id == line.requisition_id, PrLine.line_no == line.pr_line_no)).scalar_one()
    ordered_before = pr_line.ordered_qty
    _as(s, "buyer")
    result = order.short_close(s, po, "Supplier cannot deliver the balance; re-sourced")
    assert result["status"] == "CLOSED" and result["released"][0]["releasedQty"] == "60"
    assert pr_line.ordered_qty == ordered_before - 60
    event = s.execute(select(OutboxEvent).where(OutboxEvent.topic == "purchase_order.closed", OutboxEvent.object_id == po.id)).scalar_one()
    assert event.payload["shortClose"] is True and event.payload["lines"][0]["releasedValueMinor"] == 60 * 1250
    assert event.payload["from"] == "PARTIALLY_RECEIVED"
    assert _problem(order.short_close, s, po, "again").code == "ILLEGAL_TRANSITION"


# ---------------------------------------------------------------- 7. reversal of a mixed receipt from each line's own stock
def test_mixed_receipt_in_quality_hold_is_reversed_line_by_line(tx):
    s = tx
    po = _po(s, [("DC-330", 30, 40500), ("FK-M8-50", 100, 1250)])
    _confirm(s, po)
    _as(s, "receiver")
    b1, b2 = _batch("Q"), _batch("U")
    gr = receiving.post_gr(s, po, lines=[{"line": 10, "qty": "30", "batch": b1}, {"line": 20, "qty": "100", "batch": b2}])
    assert gr.status == "QUALITY_HOLD"
    assert (_stock(s, "DC-330", "QUALITY", b1), _stock(s, "FK-M8-50", "UNRESTRICTED", b2)) == (30, 100)
    receiving.reverse_gr(s, gr, "Wrong delivery note")
    assert gr.status == "REVERSED"
    assert (_stock(s, "DC-330", "QUALITY", b1), _stock(s, "FK-M8-50", "UNRESTRICTED", b2)) == (0, 0)
    moves = {(m.stock_type, m.qty) for m in s.execute(select(StockMovement).where(StockMovement.reference_id == gr.id,
                                                                                  StockMovement.movement_type == "102")).scalars()}
    assert moves == {("QUALITY", Decimal(-30)), ("UNRESTRICTED", Decimal(-100))}


def test_two_lot_receipt_with_one_lot_accepted_is_reversed_and_a_returned_lot_blocks(tx):
    s = tx
    po = _po(s, [("DC-330", 20, 40500), ("DC-331", 20, 21500)])
    _confirm(s, po)
    _as(s, "receiver")
    b1, b2 = _batch("E"), _batch("F")
    gr = receiving.post_gr(s, po, lines=[{"line": 10, "qty": "20", "batch": b1}, {"line": 20, "qty": "20", "batch": b2}])
    first, second = _lots(s, gr)
    _as(s, "quality.inspector")
    receiving.usage_decision(s, first, accepted=Decimal(20), rejected=Decimal(0))
    assert gr.status == "QUALITY_HOLD"
    _as(s, "receiver")
    receiving.reverse_gr(s, gr, "Posted twice")
    assert gr.status == "REVERSED" and second.status == "CANCELLED"
    assert _stock(s, "DC-330", "UNRESTRICTED", b1) == 0 and _stock(s, "DC-331", "QUALITY", b2) == 0
    assert all(l.received_qty == 0 and l.accepted_qty == 0 for l in _lines(s, po).values())


def test_receipt_with_a_returned_lot_cannot_be_reversed(tx):
    s = tx
    po = _po(s, [("DC-330", 20, 40500), ("DC-331", 20, 21500)])
    _confirm(s, po)
    _as(s, "receiver")
    gr = receiving.post_gr(s, po, lines=[{"line": 10, "qty": "20", "batch": _batch("G")}, {"line": 20, "qty": "20", "batch": _batch("H")}])
    first, _ = _lots(s, gr)
    _as(s, "quality.inspector")
    receiving.usage_decision(s, first, accepted=Decimal(0), rejected=Decimal(20), defect_code="CRACK", reason="Cracks at the rib")
    _as(s, "receiver")
    problem = _problem(receiving.reverse_gr, s, gr, "Posted twice")
    assert problem.code == "RULE_VIOLATION" and problem.rule_ref == "RCV-REVERSE" and first.number in problem.detail


# ---------------------------------------------------------------- 8 and 16a. confirmation SLA per version, rejected review
def _fire(s, timer: Timer) -> int:
    before = s.execute(select(Task).where(Task.object_id == timer.object_id, Task.kind == "EXPEDITE")).scalars().all()
    timer.fired_at = clock.now()
    order._confirmation_overdue(s, timer)
    return len(s.execute(select(Task).where(Task.object_id == timer.object_id, Task.kind == "EXPEDITE")).scalars().all()) - len(before)


def test_each_version_has_its_own_confirmation_sla_and_answers_stop_expediting(tx):
    s = tx
    po = _po(s, [("FK-M8-50", 60, 1250)])
    _confirm(s, po)
    v1_due = po.confirmation_due_at
    _as(s, "buyer")
    order.change_order(s, po, [{"line": 10, "qty": "70"}], reason="Top-up")
    assert po.version == 2 and po.confirmation_due_at >= v1_due
    timers = {int(t.payload["version"]): t for t in s.execute(select(Timer).where(Timer.object_id == po.id, Timer.kind == "PO_CONFIRMATION_SLA")).scalars()}
    assert set(timers) == {1, 2}
    assert _fire(s, timers[1]) == 0  # superseded version
    # The supplier rejects version 2: no expediting, and the buyer cannot "accept" a rejection (16a).
    _as(s, "tf.sales")
    answer = order.confirm(s, po, "REJECTED", note="No capacity in the requested week")
    assert answer["confirmation"] == "CHANGE_REQUESTED"
    assert _fire(s, timers[2]) == 0
    review = s.execute(select(Task).where(Task.object_id == po.id, Task.kind == "PO_CHANGE_REVIEW", Task.status == "OPEN")).scalar_one()
    _as(s, "buyer.lead")
    problem = _problem(workflow.complete, s, review.id, "APPROVE", "ok")
    assert problem.status == 422 and problem.code == "NOTHING_TO_ACCEPT"
    workflow.complete(s, review.id, "REJECT", "Rejected by the supplier; re-sourcing")
    assert po.version == 2


def test_unanswered_current_version_is_expedited(tx):
    s = tx
    po = _po(s, [("FK-M8-50", 60, 1250)])
    timer = s.execute(select(Timer).where(Timer.object_id == po.id, Timer.kind == "PO_CONFIRMATION_SLA")).scalar_one()
    assert _fire(s, timer) == 1


# ---------------------------------------------------------------- 11. re-submit after a rejected approval; more cancel paths
def test_rejected_po_is_corrected_and_resubmitted_or_cancelled_in_approval(tx):
    s = tx
    _as(s, "buyer")
    pr = requisition.create(s, origin="MANUAL", purpose_code="BUFFER_BUILD", purpose_text="Review F5/F6 resubmit", plant="P100",
                            lines=[{"item_type": "MATERIAL", "purchase_type": "STOCK", "material": "FK-M8-50", "qty": "500",
                                    "price_est_minor": 1250, "need_date": _need().isoformat(), "storage_location": "0001"}])
    requisition.submit(s, pr)
    _approve(s, pr.id)
    _as(s, "buyer")
    po = order.create_from_requisition(s, requisition=pr.number, lines=[10], supplier_code="TF001", release_qty=Decimal(400))[0]
    assert po.status == "IN_APPROVAL"
    task = s.execute(select(Task).where(Task.object_id == po.id, Task.status == "OPEN")).scalar_one()
    _as(s, "buyer.lead")
    workflow.complete(s, task.id, "REJECT", "Order the full 500; one delivery")
    assert po.status == "DRAFT"
    _as(s, "buyer")
    assert _problem(order.resubmit, s, po, "Full quantity", [{"line": 10, "qty": "600"}]).code == "RULE_VIOLATION"  # beyond the PR
    result = order.resubmit(s, po, "Full quantity as requested", [{"line": 10, "qty": "500"}])
    assert result["status"] == "IN_APPROVAL" and _lines(s, po)[10].qty == 500 and po.total_minor == 500 * 1250
    pr_line = s.execute(select(PrLine).where(PrLine.requisition_id == pr.id, PrLine.line_no == 10)).scalar_one()
    assert pr_line.ordered_qty == 500
    # IN_APPROVAL → cancel closes the approval task.
    cancelled = order.cancel(s, po, "Requirement moved to the annual agreement")
    assert cancelled["from"] == "IN_APPROVAL" and po.status == "CANCELLED"
    assert not s.execute(select(Task).where(Task.object_id == po.id, Task.status == "OPEN")).first()
    assert pr_line.ordered_qty == 0


def test_confirmed_po_can_be_cancelled_before_shipment(tx):
    s = tx
    po = _po(s, [("FK-M8-50", 60, 1250)])
    _confirm(s, po)
    _as(s, "buyer")
    result = order.cancel(s, po, "Model change; kits no longer needed")
    assert result["from"] == "CONFIRMED" and po.status == "CANCELLED"
    notices = s.execute(select(PoTransmission).where(PoTransmission.po_id == po.id, PoTransmission.format == "PORTAL_CANCEL")).scalars().all()
    assert len(notices) == 1


# ---------------------------------------------------------------- 12. ERP cancellation after a retried release
def test_erp_cancellation_follows_a_release_that_was_still_retrying(tx):
    s = tx
    po = _po(s, [("FK-M8-50", 60, 1250)])
    released = s.execute(select(OutboxEvent).where(OutboxEvent.topic == "purchase_order.released", OutboxEvent.object_id == po.id)).scalar_one()
    integration.FAULTS["fail"] = 1
    try:
        order._post_po(s, released)
    finally:
        integration.FAULTS["fail"] = 0
    message = s.execute(select(IntegrationMessage).where(IntegrationMessage.object_id == po.id, IntegrationMessage.message_type == "PURCHASE_ORDER")).scalar_one()
    assert message.status == "RETRY" and po.erp_doc_no is None
    _as(s, "buyer")
    order.cancel(s, po, "Duplicate of an existing call-off")
    cancelled = s.execute(select(OutboxEvent).where(OutboxEvent.topic == "purchase_order.cancelled", OutboxEvent.object_id == po.id)).scalar_one()
    order._post_po_cancellation(s, cancelled)
    key = f"{po.company_code}|PO|{po.number}|CANCEL"
    assert not s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == key)).first()
    assert s.execute(select(AuditEvent).where(AuditEvent.object_id == po.id, AuditEvent.action == "ERP_CANCEL_DEFERRED")).scalar_one()
    integration.process(s, message)  # the retry posts the order ...
    assert message.status == "POSTED" and po.erp_doc_no
    cancel = s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == key)).scalar_one()
    assert cancel.status == "POSTED" and cancel.payload["erpDocument"] == po.erp_doc_no  # ... and the cancellation follows it
    order._post_po_cancellation(s, cancelled)  # a late cancel event changes nothing (same key, same payload)
    assert len(s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == key)).scalars().all()) == 1


# ---------------------------------------------------------------- 14. rejected goods replaced instead of credited
def test_rejected_quantity_returned_for_replacement_is_open_again(tx):
    s = tx
    po = _po(s, [("DC-330", 20, 40500)])
    _confirm(s, po)
    _as(s, "tf.sales")
    asn = receiving.create_asn(s, po, lines=[{"line": 10, "qty": "20"}], ship_date=clock.today(), expected_date=clock.today())
    _as(s, "receiver")
    gr = receiving.post_gr(s, po, lines=[{"line": 10, "qty": "20", "batch": _batch("R")}], asn=asn)
    assert po.status == "RECEIVED"
    _as(s, "quality.inspector")
    result = receiving.usage_decision(s, _lots(s, gr)[0], accepted=Decimal(15), rejected=Decimal(5), defect_code="POROSITY",
                                      reason="Porosity at the boss", replacement=True)
    assert result["replacement"] is True
    rd = s.execute(select(ReturnDelivery).where(ReturnDelivery.number == result["returnDelivery"])).scalar_one()
    assert (rd.replacement_required, rd.credit_note_expected, rd.status) == (True, False, "REPLACEMENT_DUE")
    line = _lines(s, po)[10]
    assert (line.received_qty, line.rejected_qty, line.accepted_qty, line.shipped_qty) == (15, 0, 15, 15)
    assert po.status == "PARTIALLY_RECEIVED" and gr.status == "PARTIALLY_REJECTED"
    _as(s, "tf.sales")
    again = receiving.create_asn(s, po, lines=[{"line": 10, "qty": "5"}], ship_date=clock.today(), expected_date=clock.today())
    _as(s, "receiver")
    receiving.post_gr(s, po, lines=[{"line": 10, "qty": "5", "batch": _batch("R2")}], asn=again)
    assert po.status == "RECEIVED" and _lines(s, po)[10].received_qty == 20


def test_credit_note_return_can_be_turned_into_a_replacement(tx):
    s = tx
    po = _po(s, [("DC-330", 10, 40500)])
    _confirm(s, po)
    _as(s, "receiver")
    gr = receiving.post_gr(s, po, lines=[{"line": 10, "qty": "10", "batch": _batch("S")}])
    _as(s, "quality.inspector")
    result = receiving.usage_decision(s, _lots(s, gr)[0], accepted=Decimal(6), rejected=Decimal(4), defect_code="CRACK", reason="Cracked")
    rd = s.execute(select(ReturnDelivery).where(ReturnDelivery.number == result["returnDelivery"])).scalar_one()
    assert rd.credit_note_expected is True and _lines(s, po)[10].received_qty == 10
    receiving.request_replacement(s, rd, "Supplier re-delivers next week")
    assert rd.status == "REPLACEMENT_DUE" and _lines(s, po)[10].received_qty == 6 and po.status == "PARTIALLY_RECEIVED"
    assert _problem(receiving.request_replacement, s, rd).code == "ILLEGAL_TRANSITION"


# ---------------------------------------------------------------- 15. schedule edit after transmission
def test_schedule_edit_of_a_transmitted_order(tx):
    s = tx
    tf = s.execute(select(Supplier).where(Supplier.code == "TF001")).scalar_one()
    tf.order_channel = {"channels": ["PORTAL", "EDI"], "ediId": "TF001EDI"}  # rolled back
    po = _po(s, [("FK-M8-50", 100, 1250)])
    edi = s.execute(select(PoTransmission).where(PoTransmission.po_id == po.id, PoTransmission.channel == "EDI")).scalar_one()
    original = edi.document
    assert edi.status == "QUEUED"
    _as(s, "buyer")
    need = _need()
    entries = [{"qty": "60", "deliveryDate": need.isoformat()}, {"qty": "40", "deliveryDate": (need + timedelta(days=10)).isoformat()}]
    result = order.set_schedule(s, po, 10, entries, "Split delivery")
    # Nothing left the building yet: edited in place, the queued EDI document regenerated, the portal view republished.
    assert result["mode"] == "IN_PLACE" and po.version == 1
    assert edi.document != original and edi.document_sha256 == transmission._sha(edi.document)
    assert len(s.execute(select(PoTransmission).where(PoTransmission.po_id == po.id, PoTransmission.channel == "PORTAL")).scalars().all()) == 2
    # Once the EDI order reached the supplier, the next edit is version 2 (ORDCHG).
    edi.status = "SENT"
    s.flush()
    entries = [{"qty": "50", "deliveryDate": need.isoformat()}, {"qty": "50", "deliveryDate": (need + timedelta(days=10)).isoformat()}]
    result = order.set_schedule(s, po, 10, entries, "Even split")
    assert result["mode"] == "NEW_VERSION" and po.version == 2
    assert s.execute(select(PoTransmission).where(PoTransmission.po_id == po.id, PoTransmission.po_version == 2,
                                                  PoTransmission.channel == "EDI")).scalar_one().format == "EDIFACT_ORDCHG"


# ---------------------------------------------------------------- 16b. e-way bill only above ₹50,000
def test_eway_bill_required_only_above_the_threshold(tx):
    s = tx
    po = s.execute(select(PurchaseOrder).where(PurchaseOrder.number == "PO-77410")).scalar_one()
    common = dict(ship_date=clock.today(), eway_bill_no=None, valid_until=None, vehicle_no=None, distance_km=None)
    assert receiving._eway(s, po, 50_000 * 100, **common)["required"] is False
    problem = _problem(receiving._eway, s, po, 50_000 * 100 + 1, **common)
    assert problem.code == "EWAY_BILL_REQUIRED" and "exceeds" in problem.detail


# ---------------------------------------------------------------- 16e. ASN and SES creation are idempotent (commits own objects)
def test_asn_and_service_entry_creation_honour_the_idempotency_key(client, login):
    tenant_id = _axn()
    sc = Scenario(tenant_id)
    now = datetime.now(IST).replace(microsecond=0)
    try:
        with sc.act("buyer", now) as s:
            pr = requisition.create(s, origin="MANUAL", purpose_code="BUFFER_BUILD", purpose_text="Review F5/F6 idempotent ASN", plant="P100",
                                    lines=[{"item_type": "MATERIAL", "purchase_type": "STOCK", "material": "FK-M8-50", "qty": "20",
                                            "price_est_minor": 1250, "need_date": _need().isoformat(), "storage_location": "0001"}])
            requisition.submit(s, pr)
            pr_id, pr_no = pr.id, pr.number
        sc.approve_all(pr_id, now)
        with sc.act("buyer", now) as s:
            po = order.create_from_requisition(s, requisition=pr_no, lines=[10], supplier_code="TF001")[0]
            po_id, po_no = po.id, po.number
        sc.approve_all(po_id, now, "Price as per quotation")
        with sc.act("tf.sales", now) as s:
            order.confirm(s, s.get(PurchaseOrder, po_id), "CONFIRMED")
        with sc.act("requester", now) as s:
            svc = requisition.create(s, origin="MANUAL", purpose_code="MAINTENANCE", purpose_text="Review F5/F6 idempotent SES", plant="P100",
                                     lines=[{"item_type": "FREE_TEXT", "purchase_type": "SERVICE", "description": "Die polishing – review test",
                                             "material_group": "SVC-TOOLING", "category": "TOOLING-SERVICES", "qty": "4", "uom": "H",
                                             "price_est_minor": 300_000, "account_assignment_type": "COST_CENTER", "account_assignment_code": "4100",
                                             "need_date": _need().isoformat(),
                                             "quotes": [{"supplier": "HTS004", "reference": "HTS/Q/REVIEW-2", "date": clock.today().isoformat()}]}])
            requisition.submit(s, svc)
            svc_id, svc_no = svc.id, svc.number
        sc.approve_all(svc_id, now)
        with sc.act("buyer", now) as s:
            svc_po = order.create_from_requisition(s, requisition=svc_no, lines=[10], supplier_code="HTS004", unit_price_minor=300_000)[0]
            svc_po_id, svc_po_no = svc_po.id, svc_po.number
        sc.approve_all(svc_po_id, now, "Rate as per quote")
        with sc.act("hts.service", now) as s:
            order.confirm(s, s.get(PurchaseOrder, svc_po_id), "CONFIRMED")
    finally:
        clock.set_pinned(None)

    key = {"Idempotency-Key": f"asn-{uuid.uuid4()}"}
    body = {"po": po_no, "ship_date": clock.today().isoformat(), "expected_date": clock.today().isoformat(), "lines": [{"line": 10, "qty": "20"}]}
    first = client.post("/v1/asns", json=body, headers={**login("tf.sales"), **key})
    assert first.status_code == 201, first.text
    again = client.post("/v1/asns", json=body, headers={**login("tf.sales"), **key})
    assert again.status_code in (200, 201) and again.json()["replayed"] is True and again.json()["number"] == first.json()["number"]
    unknown = client.post("/v1/asns", json={**body, "lines": [{"line": 90, "qty": "1"}]}, headers=login("tf.sales"))
    assert unknown.status_code == 422 and unknown.json()["code"] == "UNKNOWN_LINE"

    key = {"Idempotency-Key": f"ses-{uuid.uuid4()}"}
    body = {"po": svc_po_no, "method": "TIME_MATERIAL", "period_from": clock.today().isoformat(), "period_to": clock.today().isoformat(),
            "lines": [{"line": 10, "qty": "4", "unit_rate": "3000"}]}
    first = client.post("/v1/service-entries", json=body, headers={**login("hts.service"), **key})
    assert first.status_code == 201, first.text
    again = client.post("/v1/service-entries", json=body, headers={**login("hts.service"), **key})
    assert again.json()["replayed"] is True and again.json()["number"] == first.json()["number"]
    unknown = client.post("/v1/service-entries", json={**body, "lines": [{"line": 90, "qty": "1"}]}, headers=login("hts.service"))
    assert unknown.status_code == 422 and unknown.json()["code"] == "UNKNOWN_LINE"
    with tenant_tx(tenant_id) as s:
        assert len(s.execute(select(Asn).where(Asn.po_id == po_id)).scalars().all()) == 1
        entries = s.execute(select(ServiceEntry).where(ServiceEntry.po_id == svc_po_id)).scalars().all()
        assert len(entries) == 1
        ses_id = entries[0].id
    # Leave no open work behind: the service owner rejects the sheet (the order stays open, nothing is accrued).
    ses_no = first.json()["number"]
    task = next(t for t in client.get("/v1/tasks", headers=login("service.owner")).json() if t["object_ref"] == ses_no)
    r = client.post(f"/v1/tasks/{task['id']}/complete", json={"decision": "REJECT", "comment": "Review test sheet withdrawn"},
                    headers=login("service.owner"))
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------- new endpoints are wired
def test_new_po_endpoints_are_wired(client, login):
    buyer = login("buyer")
    r = client.post("/v1/purchase-orders/PO-77410/resubmit", json={"reason": "Corrected"}, headers=buyer)
    assert r.status_code == 409 and r.json()["code"] == "ILLEGAL_TRANSITION"
    r = client.post("/v1/purchase-orders/PO-77410/short-close", json={"reason": "Balance not needed"}, headers=buyer)
    assert r.status_code == 409 and r.json()["code"] == "ILLEGAL_TRANSITION"
    r = client.post("/v1/return-deliveries/RD-NOPE/replacement", json={}, headers=login("quality.inspector"))
    assert r.status_code == 404
    assert client.post("/v1/purchase-orders/PO-77410/short-close", json={"reason": "x"}, headers=login("tf.sales")).status_code in (403, 422)
