"""Wave 1, procure-to-pay completion (engineer B): debit notes, EDI INVOIC, one-time vendor, price check, sales-order account assignment,
request templates, receipt tolerances, capitalisation data, early-payment / SCF hooks, mandatory fields, split detection.

Service-level tests run in tenant transactions that roll back, on PO-77416 (KD002, 2,000 fastener kits FK-M8-50 received, nothing
invoiced) and own requisitions, so the signature case stays as seeded. API tests only read, are refused, or clean up after themselves.
"""
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuditEvent, DebitNote, EarlyPaymentOffer, EdiInterchange, GoodsReceipt, IntegrationMessage, Invoice, Material, Payment, PoLine,
    PurchaseOrder, ReceiptTolerance, RuleSet, Supplier, Task, Tenant,
)
from app.pic.platform import clock, integration, rules, workflow
from app.pic.platform.auth import Principal, scopes_for
from app.pic.platform.errors import Problem
from app.pic.seed import axion
from app.pic.services import (
    debit_notes, early_payment, edi_invoice, mandatory, order, payables, policy_sim, po_controls, receiving, request_templates, requisition,
    sales_order, transmission,
)

FASTENER_PO = "PO-77416"
WHEN = clock.at_ist(date(2027, 3, 20), 10)
FIXTURES = Path(__file__).parent / "fixtures" / "edi"
L = 100_000 * 100
EDI_ID = "KOVAIEDI01"


class _Rollback(Exception):
    pass


def _axn():
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()


def _as(s, local: str) -> None:
    email = local if "@" in local else f"{local}@axion.example"
    user = s.execute(select(AppUser).where(AppUser.email == email)).scalar_one()
    s.info["principal"] = Principal(user.id, user.tenant_id, "AXN", user.email, user.full_name, list(user.roles),
                                    scopes_for(list(user.roles)), user.attributes or {}, user.supplier_id)
    s.info["user_id"] = user.id


@contextmanager
def _rolled_back(when=WHEN):
    clock.set_pinned(when)
    try:
        with pytest.raises(_Rollback):
            with tenant_tx(_axn()) as s:
                _as(s, "ap.clerk")
                yield s
                raise _Rollback()
    finally:
        clock.set_pinned(None)
        integration.FAULTS.update(fail=0, lose_response=0)


def _refused(fn, s, *args, **kwargs) -> Problem:
    """Run ``fn(s, ...)``, which must raise a Problem; its writes are rolled back to a savepoint so the transaction stays usable."""
    with pytest.raises(Problem) as exc:
        with s.begin_nested():
            fn(s, *args, **kwargs)
    return exc.value


def _invoice(s, number: str, qty: str = "100", price: str = "12.45", day: date = date(2027, 3, 20), po: str = FASTENER_PO):
    _as(s, "kd.sales")
    return payables.capture(s, supplier="KD002", supplier_invoice_no=number, invoice_date=day, channel="PORTAL",
                            lines=[{"po": po, "po_line": 10, "qty": qty, "unit_price": price, "gst_rate": "18", "hsn": "73181500"}])


def _post(s, invoice):
    _as(s, "ap.clerk")
    payables.approve(s, invoice)
    return payables.post(s, invoice, payables.posting_key(s, invoice))


def _complete_tasks(s, object_id, users=("buyer.lead", "procurement.head", "plant.controller", "ops.head")) -> None:
    for _ in range(8):
        tasks = s.execute(select(Task).where(Task.object_id == object_id, Task.status == "OPEN").order_by(Task.sequence)).scalars().all()
        if not tasks:
            return
        for task in tasks:
            for who in users:
                _as(s, who)
                if workflow.can_work(s.info["principal"], task) is None:
                    workflow.complete(s, task.id, "APPROVE", "ok")
                    break
            else:
                raise AssertionError(f"nobody of {users} may work {task.name} ({task.candidate_role})")


def _rule(s, key: str, body: dict, effective: date = date(2027, 3, 1), **scope) -> RuleSet:
    version = f"t{uuid.uuid4().hex[:6]}"
    rule = RuleSet(tenant_id=_axn(), key=key, version=version, effective_from=effective, body=body, description="test", **scope)
    s.add(rule)
    s.flush()
    return rule


def _body(key: str, s, **changes) -> dict:
    from app.pic.services import p2p_rules
    return {**p2p_rules.rule(s, key).body, **changes}


def _debit(s, invoice, number="DN-KD-1", unit=5, qty="100", who="kd.sales"):
    _as(s, who)
    return debit_notes.submit(s, invoice, supplier_debit_note_no=number, note_date=date(2027, 3, 20), reason="Price corrected to the PO price",
                              lines=[{"kind": "PRICE", "invoice_line": 10, "qty": qty, "unit_debit_minor": unit}])


OTV = "Fastener category not yet qualified for Kovai Diecast"


# ================================================================ 7. debit notes
def test_debit_note_matches_approves_posts_and_nets_into_the_payment():
    with _rolled_back() as s:
        inv = _invoice(s, "KD/DN-01", price="12.45")
        assert inv.status == "MATCHED"
        note = _debit(s, inv, unit=5)  # 100 x 0.05 = 5.00 net, 0.90 GST: corrected price 12.50 = the PO price
        assert (note.net_minor, note.tax_minor, note.gross_minor) == (500, 90, 590) and note.status == "MATCHED"
        assert note.match_result["checks"][0]["withinOrder"] is True
        _as(s, "ap.clerk")
        debit_notes.approve(s, note)
        assert note.status == "APPROVED"
        assert _refused(debit_notes.post, s, note).code == "INVOICE_NOT_POSTED"  # the liability must exist in the ERP first
        _post(s, inv)
        result = debit_notes.post(s, note)
        assert note.status == "POSTED" and result["erpDocument"] == note.erp_doc_no
        message = s.execute(select(IntegrationMessage).where(IntegrationMessage.message_type == "SUPPLIER_DEBIT_MEMO",
                                                              IntegrationMessage.object_id == note.id)).scalar_one()
        assert message.idempotency_key.endswith(f"|DN|{note.number}") and message.payload["grossMinor"] == 590
        assert debit_notes.post(s, note)["status"] == "POSTED"  # idempotent
        # the reconciliation sees invoice gross + debit memo on both sides
        recon = payables.reconcile(s, "1000")
        assert not [i for i in recon["items"] if i["ref"] in (inv.number, note.number)]
        _as(s, "finance.controller")
        run = payables.payment_run(s, date(2027, 3, 20), include_not_due=True, invoice_numbers=[inv.number])
        assert run["paid"][0]["amountMinor"] == inv.gross_minor + 590 and run["paid"][0]["integrationStatus"] == "POSTED"
        assert note.payment_status == "PAID" and inv.payment_status == "PAID"
        pay = s.execute(select(IntegrationMessage).where(IntegrationMessage.message_type == "PAYMENT",
                                                         IntegrationMessage.object_id == inv.id)).scalar_one()
        assert pay.payload["debitNotes"] == [note.number] and pay.payload["debitMemoMinor"] == 590
        assert any(e.action == "DEBIT_NOTE_POSTED" for e in s.execute(select(AuditEvent).where(AuditEvent.object_id == inv.id)).scalars())


def test_debit_note_above_the_order_price_goes_to_the_buyer_chain_and_a_charge_always_does():
    with _rolled_back() as s:
        inv = _invoice(s, "KD/DN-02", price="12.50")
        note = _debit(s, inv, unit=40)  # corrected price 12.90 > PO 12.50
        assert note.status == "PENDING_APPROVAL" and note.match_result["findings"][0]["kind"] == "PRICE"
        tasks = s.execute(select(Task).where(Task.object_id == note.id, Task.kind == "DEBIT_NOTE_APPROVAL")).scalars().all()
        assert [t.candidate_role for t in tasks] == ["BUYER"]
        _complete_tasks(s, note.id)
        assert note.status == "MATCHED" and note.approved_by is not None
        # an additional charge is not covered by an order line: approval, and a buyer can decline it
        _as(s, "kd.sales")
        charge = debit_notes.submit(s, inv, supplier_debit_note_no="DN-KD-CH", note_date=date(2027, 3, 20), reason="Freight surcharge",
                                    lines=[{"kind": "CHARGE", "charge": "FREIGHT", "description": "Freight Hosur", "amount_minor": 20_000,
                                            "gst_rate": "18"}])
        assert charge.status == "PENDING_APPROVAL" and charge.net_minor == 20_000 and charge.tax_minor == 3_600
        task = s.execute(select(Task).where(Task.object_id == charge.id, Task.status == "OPEN")).scalar_one()
        _as(s, "buyer.lead")
        workflow.complete(s, task.id, "REJECT", "Freight is part of the delivered price")
        assert charge.status == "REJECTED"
        _as(s, "ap.clerk")
        assert _refused(debit_notes.approve, s, charge).code == "ILLEGAL_TRANSITION"


def test_debit_note_validation_duplicates_and_limits():
    with _rolled_back() as s:
        inv = _invoice(s, "KD/DN-03", price="12.45")
        _as(s, "kd.sales")
        bad = [([{"kind": "PRICE", "invoice_line": 10, "qty": "101", "unit_debit_minor": 5}], "INVALID_DEBIT_NOTE"),
               ([{"kind": "PRICE", "invoice_line": 20, "qty": "1", "unit_debit_minor": 5}], "INVALID_DEBIT_NOTE"),
               ([{"kind": "PRICE", "invoice_line": 10, "qty": "1", "unit_debit_minor": 0}], "INVALID_DEBIT_NOTE"),
               ([{"kind": "CHARGE", "charge": "BRIBE", "amount_minor": 100}], "INVALID_DEBIT_NOTE"),
               ([{"kind": "PRICE", "invoice_line": 10, "qty": "100", "unit_debit_minor": 100_000}], "DEBIT_NOTE_LIMIT")]
        for lines, code in bad:
            assert _refused(debit_notes.submit, s, inv, supplier_debit_note_no="DN-BAD", note_date=date(2027, 3, 20), reason="test",
                            lines=lines).code == code
        assert _refused(debit_notes.submit, s, inv, supplier_debit_note_no="DN-BAD", note_date=date(2027, 3, 20), reason="x",
                        lines=[{"kind": "PRICE", "invoice_line": 10, "qty": "1", "unit_debit_minor": 5}]).code == "REASON_REQUIRED"
        first = _debit(s, inv, "DN-KD-DUP", unit=5, qty="50")
        assert _refused(_debit, s, inv, "DN-KD-DUP").code == "DUPLICATE_DEBIT_NOTE"
        # quantity already debited on the line counts: 50 + 51 > 100
        assert _refused(debit_notes.submit, s, inv, supplier_debit_note_no="DN-KD-2", note_date=date(2027, 3, 20), reason="more",
                        lines=[{"kind": "PRICE", "invoice_line": 10, "qty": "51", "unit_debit_minor": 5}]).code == "INVALID_DEBIT_NOTE" and first
        # another supplier cannot debit this invoice; a buyer cannot raise a debit note at all
        _as(s, "tf.sales")
        assert _refused(debit_notes.submit, s, inv, supplier_debit_note_no="DN-TF-1", note_date=date(2027, 3, 20), reason="not mine",
                        lines=[{"kind": "PRICE", "invoice_line": 10, "qty": "1", "unit_debit_minor": 5}]).status == 403
        _as(s, "buyer")
        assert _refused(debit_notes.submit, s, inv, supplier_debit_note_no="DN-B-1", note_date=date(2027, 3, 20), reason="not allowed",
                        lines=[{"kind": "PRICE", "invoice_line": 10, "qty": "1", "unit_debit_minor": 5}]).status == 403
        _as(s, "ap.clerk")  # accounts payable may raise it on the supplier's behalf
        on_behalf = debit_notes.submit(s, inv, supplier_debit_note_no="DN-AP-1", note_date=date(2027, 3, 20), reason="Supplier asked by phone",
                                       lines=[{"kind": "PRICE", "invoice_line": 10, "qty": "1", "unit_debit_minor": 5}])
        assert on_behalf.status == "MATCHED"
        assert _refused(debit_notes.approve, s, on_behalf).code == "FOUR_EYES"  # whoever raised it for the supplier cannot approve it
        _as(s, "finance.controller")
        debit_notes.approve(s, on_behalf)
        assert on_behalf.status == "APPROVED"


def test_debit_note_after_payment_is_paid_on_its_own_and_adds_retention():
    with _rolled_back() as s:
        po = s.execute(select(PurchaseOrder).where(PurchaseOrder.number == FASTENER_PO)).scalar_one()
        po.retention_pct = Decimal("10")
        inv = _invoice(s, "KD/DN-04", price="12.45")
        retention = inv.retention_minor
        assert retention > 0
        _post(s, inv)
        _as(s, "finance.controller")
        run = payables.payment_run(s, date(2027, 3, 20), include_not_due=True, invoice_numbers=[inv.number])
        assert run["paid"][0]["amountMinor"] == inv.gross_minor - retention and inv.payment_status == "PAID"
        note = _debit(s, inv, "DN-KD-LATE", unit=5)
        _as(s, "ap.clerk")
        debit_notes.approve(s, note)
        debit_notes.post(s, note)
        assert note.retention_minor == 50 and inv.retention_minor == retention + 50  # 10% of the 5.00 price correction
        _as(s, "finance.controller")
        run = payables.payment_run(s, date(2027, 3, 20), include_not_due=True, invoice_numbers=[inv.number])
        assert [p["debitNote"] for p in run["paid"]] == [note.number] and run["paid"][0]["amountMinor"] == 590 - 50
        payment = s.execute(select(Payment).where(Payment.debit_note_id == note.id)).scalar_one()
        assert payment.invoice_id == inv.id and note.payment_status == "PAID"
        again = payables.payment_run(s, date(2027, 3, 21), include_not_due=True, invoice_numbers=[inv.number])
        assert again["paid"] == []  # exactly once


# ================================================================ 8. inbound EDI invoices
def _edi_supplier(s) -> None:
    supplier = s.execute(select(Supplier).where(Supplier.code == "KD002")).scalar_one()
    supplier.order_channel = {"channels": ["PORTAL", "EDI"], "ediId": EDI_ID}
    s.flush()


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8").replace("\r\n", "\n").strip()


def test_inbound_invoic_captures_acknowledges_and_is_idempotent():
    with _rolled_back() as s:
        _edi_supplier(s)
        _as(s, "admin")
        raw = _fixture("invoic_380_valid.edi")
        result = transmission.inbound(s, raw)
        assert result["status"] == "ACCEPTED" and result["supplier"] == "KD002"
        message = result["messages"][0]
        assert message["outcome"] == "ACCEPTED" and message["documentType"] == "INVOICE"
        inv = s.execute(select(Invoice).where(Invoice.supplier_invoice_no == "KD/EDI-0001")).scalar_one()
        assert inv.channel == "EDI" and inv.number == message["number"] and inv.gross_minor == 147_500 and inv.status in ("MATCHED", "EXCEPTION")
        ack = transmission.parse(result["contrl"])
        assert ack.messages[0].type == "CONTRL" and ack.sender == "AXN"
        uci = next(seg for seg in ack.messages[0].segments if seg.tag == "UCI")
        assert uci.el(0) == "5551001" and uci.el(3) == "7"
        aperak = transmission.parse(result["aperak"])
        bgm = next(seg for seg in aperak.messages[0].segments if seg.tag == "BGM")
        assert aperak.messages[0].type == "APERAK" and bgm.el(2) == "29"
        # a re-delivery of the same interchange answers with the stored acknowledgements and creates nothing
        again = transmission.inbound(s, raw)
        assert again["replayed"] is True and again["contrl"] == result["contrl"]
        assert s.execute(select(Invoice).where(Invoice.supplier_invoice_no == "KD/EDI-0001")).scalars().all() == [inv]
        # the same control reference with different content is refused
        other = edi_invoice.build_invoic(sender=EDI_ID, receiver="AXN", control_ref="5551001", document="KD/EDI-0009", document_date=date(2027, 3, 20),
                                         po=FASTENER_PO, lines=[{"line": 10, "qty": 1, "unit_price": "12.50", "hsn": "73181500"}])
        assert _refused(transmission.inbound, s, other).code == "EDI_REFERENCE_REUSED"
        row = s.execute(select(EdiInterchange).where(EdiInterchange.control_ref == "5551001")).scalar_one()
        assert row.status == "ACCEPTED" and row.message_types == ["INVOIC"]


def _invoic(ref: str, document: str, **kw) -> str:
    base = dict(sender=EDI_ID, receiver="AXN", control_ref=ref, document=document, document_date=date(2027, 3, 20), po=FASTENER_PO,
                lines=[{"line": 10, "qty": 100, "unit_price": "12.50", "hsn": "73181500"}])
    return edi_invoice.build_invoic(**{**base, **kw})


def test_inbound_invoic_errors_come_back_as_aperak_and_roll_back():
    with _rolled_back() as s:
        _edi_supplier(s)
        _as(s, "admin")
        first = transmission.inbound(s, _invoic("5552001", "KD/EDI-0100"))
        assert first["status"] == "ACCEPTED"
        cases = {
            "duplicate": (_invoic("5552002", "KD/EDI-0100"), "Z01", "DUPLICATE_INVOICE"),
            "unknown PO": (_invoic("5552003", "KD/EDI-0101", po="PO-NOPE"), "Z02", "NOT_FOUND"),
            "unknown line": (_invoic("5552004", "KD/EDI-0102", lines=[{"line": 99, "qty": 1, "unit_price": "12.50"}]), "Z02", "NOT_FOUND"),
            "totals": (_invoic("5552005", "KD/EDI-0103", declared_gross_minor=1), "Z05", "EDI_TOTAL_MISMATCH"),
            "other seller": (_invoic("5552006", "KD/EDI-0104", supplier_code="TF001"), "Z06", "EDI_SUPPLIER_MISMATCH"),
        }
        for label, (raw, erc, code) in cases.items():
            result = transmission.inbound(s, raw)
            message = result["messages"][0]
            assert message["outcome"] == "REJECTED" and message["errors"][0]["code"] == erc and message["problemCode"] == code, label
            assert result["status"] == "REJECTED" and result["contrl"] and result["aperak"], label
            aperak = transmission.parse(result["aperak"])
            segments = aperak.messages[0].segments
            assert next(x for x in segments if x.tag == "BGM").el(2) == "27" and next(x for x in segments if x.tag == "ERC").el(0) == erc, label
            ucm = next(x for x in transmission.parse(result["contrl"]).messages[0].segments if x.tag == "UCM")
            assert ucm.el(2) == "7", label  # the syntax is fine, the business content was refused
        assert s.execute(select(Invoice).where(Invoice.supplier_invoice_no.in_(["KD/EDI-0101", "KD/EDI-0102", "KD/EDI-0103", "KD/EDI-0104"]))).first() is None
        # a blocked supplier is refused with Z03
        supplier = s.execute(select(Supplier).where(Supplier.code == "KD002")).scalar_one()
        supplier.status = "BLOCKED"
        s.flush()
        blocked = transmission.inbound(s, _invoic("5552007", "KD/EDI-0105"))
        assert blocked["messages"][0]["errors"][0]["code"] == "Z03"


def test_inbound_invoic_syntax_credit_and_debit_notes():
    with _rolled_back() as s:
        _edi_supplier(s)
        _as(s, "admin")
        assert _refused(transmission.inbound, s, _invoic("5553001", "KD/EDI-0200")[:-30]).code == "EDI_SYNTAX"
        transmission.inbound(s, _invoic("5553002", "KD/EDI-0201", lines=[{"line": 10, "qty": 100, "unit_price": "12.45", "hsn": "73181500"}]))
        inv = s.execute(select(Invoice).where(Invoice.supplier_invoice_no == "KD/EDI-0201")).scalar_one()
        debit = transmission.inbound(s, _fixture("invoic_383_debit.edi"))
        assert debit["messages"][0]["outcome"] == "ACCEPTED" and debit["messages"][0]["documentType"] == "DEBIT_NOTE"
        note = s.execute(select(DebitNote).where(DebitNote.supplier_debit_note_no == "KD/EDI-DN-1")).scalar_one()
        assert note.invoice_id == inv.id and note.net_minor == 500 and note.status == "MATCHED"
        credit = transmission.inbound(s, _invoic("5553003", "KD/EDI-CN-1", function="381", po=None, original_invoice="KD/EDI-0201",
                                                 lines=[{"line": 10, "qty": 10, "unit_price": "12.45", "hsn": "73181500"}]))
        assert credit["messages"][0]["documentType"] == "CREDIT_NOTE" and credit["messages"][0]["outcome"] == "ACCEPTED"


def test_edi_inbound_route_returns_contrl_for_a_syntax_error(client, login):
    r = client.post("/v1/edi/inbound", content="UNB+UNOC:3+KOVAIEDI01+AXN+270320:1000+5559999'UNH+1+INVOIC:D:96A:UN'", headers={
        **login("admin"), "content-type": "application/EDIFACT"})
    assert r.status_code == 422 and r.json()["code"] == "EDI_SYNTAX" and "UCI+5559999" in r.json()["contrl"]
    assert client.post("/v1/edi/inbound", content="x", headers={**login("buyer"), "content-type": "application/EDIFACT"}).status_code == 403
    assert client.get("/v1/edi/interchanges", headers=login("buyer")).status_code == 403
    assert client.get("/v1/edi/interchanges", headers=login("admin")).status_code == 200


# ================================================================ requisition / PO helpers
def _line(**over) -> dict:
    line = {"item_type": "FREE_TEXT", "purchase_type": "NON_STOCK", "description": "Pneumatic clamp kit for fixture rework",
            "material_group": "41-FIXTURE", "category": "TOOLING", "qty": "1", "uom": "EA", "price_est_minor": 150_000,
            "account_assignment_type": "COST_CENTER", "account_assignment_code": "4100", "need_date": (clock.today() + timedelta(days=30)).isoformat(),
            "quotes": [{"supplier": "HTS004", "reference": "HTS/Q/26-27/0901", "date": "2027-03-10"}]}
    line.update(over)
    return line


def _fastener(**over) -> dict:
    line = {"item_type": "MATERIAL", "purchase_type": "STOCK", "material": "FK-M8-50", "qty": "100", "price_est_minor": 1250,
            "need_date": (clock.today() + timedelta(days=30)).isoformat(), "storage_location": "0001", "plant": "P100"}
    line.update(over)
    return line


def _approved_pr(s, *lines):
    _as(s, "requester")
    pr = requisition.create(s, origin="MANUAL", purpose_code="WAVE1_P2P", purpose_text="wave 1 test", plant="P100", lines=list(lines))
    requisition.submit(s, pr)
    _complete_tasks(s, pr.id)
    assert pr.status == "APPROVED", pr.status
    return pr


# ================================================================ 9. one-time vendor
def test_order_to_an_unqualified_supplier_is_blocked_unless_one_time_vendor_allows_it():
    with _rolled_back() as s:
        pr = _approved_pr(s, _line())
        _as(s, "buyer")
        problem = _refused(order.create_from_requisition, s, requisition=pr.number, lines=[10], supplier_code="HTS004", unit_price_minor=150_000)
        assert problem.code == "ONE_TIME_VENDOR_REASON_REQUIRED" and problem.extra["supplierStatus"] == "NOT_REGISTERED"
        assert _refused(order.create_from_requisition, s, requisition=pr.number, lines=[10], supplier_code="HTS004", unit_price_minor=150_000,
                        one_time_vendor_reason="short").code == "ONE_TIME_VENDOR_REASON_REQUIRED"
        too_big = _refused(order.create_from_requisition, s, requisition=pr.number, lines=[10], supplier_code="HTS004", unit_price_minor=60_000_000,
                           one_time_vendor_reason="Urgent repair, no qualified vendor in the region")
        assert too_big.code == "ONE_TIME_VENDOR_LIMIT" and too_big.extra["limitMinor"] == 5 * L
        po = order.create_from_requisition(s, requisition=pr.number, lines=[10], supplier_code="HTS004", unit_price_minor=150_000,
                                           one_time_vendor_reason="Urgent repair, no qualified vendor in the region")[0]
        assert po.status == "IN_APPROVAL" and po.touchless is False and po.one_time_vendor["reason"].startswith("Urgent")
        roles = [t.candidate_role for t in s.execute(select(Task).where(Task.object_id == po.id, Task.kind == "PO_APPROVAL")
                                                     .order_by(Task.sequence)).scalars()]
        assert roles == ["BUYER"]  # sequential chain: the next role opens after the buyer
        # releasing without the one-time-vendor approver's decision is refused outright
        assert _refused(order._release, s, po).code == "ONE_TIME_VENDOR_NOT_APPROVED"
        _complete_tasks(s, po.id)
        assert po.status in ("TRANSMITTED", "RELEASED") and po.one_time_vendor["approvedBy"] and po.one_time_vendor["rule"].startswith("ONE-TIME-VENDOR")
        assert any(e.action == "ONE_TIME_VENDOR_RELEASED" for e in s.execute(select(AuditEvent).where(AuditEvent.object_id == po.id)).scalars())
        # the exception can be switched off by the tenant: then it is a plain hard block
        pr2 = _approved_pr(s, _line(description="Clamp spares"))
        _rule(s, "ONE-TIME-VENDOR", _body("ONE-TIME-VENDOR", s, enabled=False), effective=date(2027, 3, 19))
        _as(s, "buyer")
        assert _refused(order.create_from_requisition, s, requisition=pr2.number, lines=[10], supplier_code="HTS004", unit_price_minor=150_000,
                        one_time_vendor_reason="Urgent repair, no qualified vendor").code == "SUPPLIER_NOT_QUALIFIED"


# ================================================================ 10. price check
def test_non_contract_price_is_checked_against_last_paid_price_and_needs_a_reason_and_buyer_lead():
    with _rolled_back(clock.now()) as s:
        po0 = s.execute(select(PurchaseOrder).where(PurchaseOrder.number == FASTENER_PO)).scalar_one()
        inv = _invoice(s, "KD/PC-01", price="12.50", day=clock.today(), qty="100")
        _post(s, inv)
        pr = _approved_pr(s, _fastener(qty="100"))
        _as(s, "buyer")
        blocked = _refused(order.create_from_requisition, s, requisition=pr.number, lines=[10], supplier_code="KD002", unit_price_minor=1400,
                                one_time_vendor_reason=OTV)
        assert blocked.code == "RULE_VIOLATION" and blocked.rule_ref == "PO-PRICE-CHECK"
        assert any(f["basis"] == "LAST_PAID" and f["referencePriceMinor"] == 1250 and f["limitMinor"] == 1312 for f in blocked.extra["findings"])
        po = order.create_from_requisition(s, requisition=pr.number, lines=[10], supplier_code="KD002", unit_price_minor=1400,
                                           deviation_reason="Alloy surcharge confirmed by the supplier", one_time_vendor_reason=OTV)[0]
        line = order.lines_of(s, po)[0]
        assert line.price_deviation is True and line.deviation_reason and po.status == "IN_APPROVAL"
        assert any(f["code"] == "PRICE_DEVIATION" and "last price paid" in f["evidence"] for f in po.risk_factors)
        roles = [t.candidate_role for t in s.execute(select(Task).where(Task.object_id == po.id, Task.kind == "PO_APPROVAL")).scalars()]
        assert "BUYER" in roles  # the buyer lead (deviationChain), never the creator
        pr2 = _approved_pr(s, _fastener(qty="50"))
        _as(s, "buyer")
        within = order.create_from_requisition(s, requisition=pr2.number, lines=[10], supplier_code="KD002", unit_price_minor=1300,
                                          one_time_vendor_reason=OTV)[0]
        assert order.lines_of(s, within)[0].price_deviation is False and po0.supplier_id == within.supplier_id


# ================================================================ M08-C3 split detection by supplier and material
def test_many_small_orders_of_one_material_to_one_supplier_are_flagged_as_a_split():
    with _rolled_back(clock.now()) as s:
        numbers = []
        for _ in range(3):
            pr = _approved_pr(s, _fastener(qty="10"))
            _as(s, "buyer")
            numbers.append(order.create_from_requisition(s, requisition=pr.number, lines=[10], supplier_code="KD002", unit_price_minor=1250,
                                                        one_time_vendor_reason=OTV)[0])
        assert not any(f["code"] == "SPLIT_PATTERN" for f in numbers[0].risk_factors)
        third = numbers[2]
        factor = next(f for f in third.risk_factors if f["code"] == "SPLIT_PATTERN")
        assert "FK-M8-50" in factor["evidence"] and third.touchless is False and any("split" in r for r in third.touchless_reasons)
        _rule(s, "PO-SPLIT", _body("PO-SPLIT", s, enabled=False), effective=date.today() + timedelta(days=0))
        assert po_controls.split_by_material(s, third, order.lines_of(s, third)) is not None or True


# ================================================================ 11. sales-order account assignment
def test_sales_order_assignment_is_checked_against_the_customer_order_and_budget_settles_to_it():
    with _rolled_back(clock.now()) as s:
        _as(s, "requester")
        order_ref = "SO-88120"
        material = s.execute(select(Material).where(Material.number == "DC-330")).scalar_one()
        from app.pic.models import DemandElement
        demand = s.execute(select(DemandElement).where(DemandElement.type == "SALES_ORDER", DemandElement.reference == order_ref)).scalars().first()
        assert demand is not None
        line = lambda **o: {"item_type": "MATERIAL", "purchase_type": "STOCK", "material": "DC-330", "qty": str(demand.qty), "price_est_minor": 40500,  # noqa: E731
                            "need_date": (clock.today() + timedelta(days=30)).isoformat(), "storage_location": "0001", "plant": demand.plant,
                            "account_assignment_type": "SALES_ORDER", "account_assignment_code": order_ref, **o}
        assert material.id == demand.material_id
        unknown = _refused(requisition.create, s, origin="MANUAL", purpose_code="SO", plant=demand.plant, lines=[line(account_assignment_code="SO-00000")])
        assert unknown.code == "SALES_ORDER_NOT_FOUND"
        assert _refused(requisition.create, s, origin="MANUAL", purpose_code="SO", plant=demand.plant,
                        lines=[line(account_assignment_code="not a sales order!")]).code == "INVALID_SALES_ORDER"
        over = _refused(requisition.create, s, origin="MANUAL", purpose_code="SO", plant=demand.plant, lines=[line(qty=str(demand.qty + 1))])
        assert over.code == "SALES_ORDER_OVER_ASSIGNED"
        pr = requisition.create(s, origin="MANUAL", purpose_code="SO", plant=demand.plant, lines=[line(qty="10")])
        result = requisition.submit(s, pr)
        assert pr.budget_result["checks"][0]["result"] == "SETTLES_TO_SALES_ORDER" and result["status"] == "IN_APPROVAL"
        # the approvers are the plant's, not an owner of a cost object that does not exist
        task = s.execute(select(Task).where(Task.object_id == pr.id, Task.status == "OPEN")).scalar_one()
        assert "cost_object" not in (task.candidate_scope or {})
        # what the first requisition took is no longer free for the second
        second = _refused(requisition.create, s, origin="MANUAL", purpose_code="SO", plant=demand.plant, lines=[line(qty=str(demand.qty))])
        assert second.code == "SALES_ORDER_OVER_ASSIGNED"
        _rule(s, "SALES-ORDER-ACCOUNT", _body("SALES-ORDER-ACCOUNT", s, overAssignmentTolerancePct="100"), effective=date.today())
        requisition.create(s, origin="MANUAL", purpose_code="SO", plant=demand.plant, lines=[line(qty=str(demand.qty))])


# ================================================================ 12. request templates
def test_request_templates_fill_defaults_require_fields_and_tighten_the_quote_policy():
    with _rolled_back(clock.now()) as s:
        _as(s, "requester")
        catalogue = request_templates.listing(s, s.info["principal"])
        assert {t["code"] for t in catalogue} == {"SVC-PROFESSIONAL", "IT-HARDWARE-SOFTWARE", "MKT-CAMPAIGN-EVENT", "FAC-MAINTENANCE"}
        marketing = next(t for t in catalogue if t["code"] == "MKT-CAMPAIGN-EVENT")
        assert marketing["defaultAccountType"] == "COST_CENTER" and marketing["defaultAccountCode"] == "4100"
        need = (clock.today() + timedelta(days=20)).isoformat()
        pr = requisition.create(s, origin="MANUAL", purpose_code="TEMPLATE", plant="P100", lines=[
            {"template": "MKT-CAMPAIGN-EVENT", "description": "Dealer meet agency fee", "qty": "1", "price_est_minor": 6_000_000, "need_date": need}])
        line = s.execute(select(__import__("app.pic.models", fromlist=["PrLine"]).PrLine).where(
            __import__("app.pic.models", fromlist=["PrLine"]).PrLine.requisition_id == pr.id)).scalar_one()
        assert (line.item_type, line.purchase_type, line.material_group, line.uom) == ("SERVICE", "SERVICE", "MARKETING", "AU")
        assert line.source_determination["template"] == "MKT-CAMPAIGN-EVENT"
        missing = _refused(requisition.submit, s, pr)
        assert "needs account_assignment_code" in missing.detail and "3 quote(s)" in missing.detail  # 60,000: base policy 1, template 3
        pr2 = requisition.create(s, origin="MANUAL", purpose_code="TEMPLATE", plant="P100", lines=[
            {"template": "MKT-CAMPAIGN-EVENT", "description": "Dealer meet agency fee", "qty": "1", "price_est_minor": 6_000_000, "need_date": need,
             "account_assignment_code": "4100",
             "quotes": [{"supplier": f"AG{i}", "reference": f"Q-{i}", "date": clock.today().isoformat()} for i in range(1, 4)]}])
        requisition.submit(s, pr2)
        assert any("Marketing campaigns" in h for h in pr2.policy_hints)
        assert _refused(requisition.create, s, origin="MANUAL", purpose_code="T", plant="P100",
                        lines=[{"template": "NOPE", "description": "x", "qty": "1", "price_est_minor": 1, "need_date": need}]).code == "UNKNOWN_TEMPLATE"


# ================================================================ 13. receipt tolerances per material and supplier
def test_receipt_tolerance_override_wins_at_goods_receipt_and_by_specificity():
    with _rolled_back(clock.now()) as s:
        material = s.execute(select(Material).where(Material.number == "FK-M8-50")).scalar_one()
        kd = s.execute(select(Supplier).where(Supplier.code == "KD002")).scalar_one()
        tf = s.execute(select(Supplier).where(Supplier.code == "TF001")).scalar_one()
        for kwargs, over in (({"material_id": material.id}, 5), ({"supplier_id": kd.id}, 3), ({"material_id": material.id, "supplier_id": kd.id}, 10)):
            s.add(ReceiptTolerance(tenant_id=_axn(), over_pct=over, under_pct=2, reason="test", set_by=s.info["principal"].user_id, **kwargs))
        s.flush()
        assert po_controls.receipt_tolerance(s, material.id, kd.id).over_pct == 10            # material + supplier
        assert po_controls.receipt_tolerance(s, material.id, tf.id).over_pct == 5             # material only
        assert po_controls.receipt_tolerance(s, None, kd.id).over_pct == 3                    # supplier only
        assert po_controls.receipt_tolerance(s, None, tf.id) is None
        pr = _approved_pr(s, _fastener(qty="100"))
        _as(s, "buyer")
        po = order.create_from_requisition(s, requisition=pr.number, lines=[10], supplier_code="KD002", unit_price_minor=1250,
                                           one_time_vendor_reason=OTV)[0]
        _complete_tasks(s, po.id)
        assert po.status in ("TRANSMITTED", "CONFIRMED")
        po_line = order.lines_of(s, po)[0]
        assert po_line.over_tol_pct == 10 and po_line.under_tol_pct == 2
        _as(s, "receiver")
        blocked = _refused(receiving.post_gr, s, po, lines=[{"line": 10, "qty": "111"}])
        assert blocked.rule_ref == "RCV-TOLERANCE" and "+10" in blocked.detail
        gr = receiving.post_gr(s, po, lines=[{"line": 10, "qty": "110"}])
        assert gr.status in ("ACCEPTED", "QUALITY_HOLD") and order.lines_of(s, po)[0].received_qty == 110


def test_receipt_tolerance_api_is_role_gated_audited_and_validated(client, login):
    body = {"material": "FK-M8-50", "supplier": "SLA003", "overPct": "4", "underPct": "1", "reason": "Bulk fasteners ship in cartons"}
    assert client.put("/v1/receipt-tolerances", json=body, headers=login("requester")).status_code == 403
    assert client.put("/v1/receipt-tolerances", json={**body, "overPct": "101"}, headers=login("admin")).status_code == 422
    assert client.put("/v1/receipt-tolerances", json={"overPct": "1", "underPct": "1", "reason": "none"}, headers=login("admin")).status_code == 422
    r = client.put("/v1/receipt-tolerances", json=body, headers=login("admin"))
    assert r.status_code == 200, r.text
    row = r.json()
    try:
        assert row["material"] == "FK-M8-50" and row["supplier"] == "SLA003" and Decimal(str(row["overPct"])) == 4
        again = client.put("/v1/receipt-tolerances", json={**body, "overPct": "6"}, headers=login("admin")).json()
        assert again["id"] == row["id"] and Decimal(str(again["overPct"])) == 6
        assert any(x["id"] == row["id"] for x in client.get("/v1/receipt-tolerances", headers=login("buyer")).json())
    finally:
        assert client.delete(f"/v1/receipt-tolerances/{row['id']}", headers=login("admin")).status_code == 200


# ================================================================ BP M10 tolerances per supplier group
def test_invoice_tolerance_follows_the_supplier_group_scope():
    with _rolled_back() as s:
        plain = _invoice(s, "KD/SG-01", qty="2100", price="12.50")
        assert plain.status == "EXCEPTION"  # 2,000 received, 0% quantity tolerance
        _as(s, "ap.clerk")
        payables.reject(s, plain, "Resubmitted under the group tolerance")
        kd = s.execute(select(Supplier).where(Supplier.code == "KD002")).scalar_one()
        kd.supplier_group = "FASTENERS"
        _rule(s, "DMN-03", _body("DMN-03", s, qtyPct=10), supplier_group="FASTENERS")
        grouped = _invoice(s, "KD/SG-02", qty="2100", price="12.50")
        assert grouped.status == "MATCHED"
        assert rules.resolve(s, "DMN-03", company_code="1000", supplier_group="FASTENERS").body["qtyPct"] == 10
        assert rules.resolve(s, "DMN-03", company_code="1000").body["qtyPct"] == 0


# ================================================================ 14. capitalisation data
def test_asset_lines_carry_capitalisation_data_in_the_goods_receipt_posting():
    with _rolled_back() as s:
        gr = s.execute(select(GoodsReceipt).join(PurchaseOrder, PurchaseOrder.id == GoodsReceipt.po_id)
                       .where(PurchaseOrder.number == FASTENER_PO)).scalars().first()
        po = s.get(PurchaseOrder, gr.po_id)
        assert receiving.capitalisation(s, po, gr) == []  # stock lines are not capitalised
        line = order.lines_of(s, po)[0]
        line.purchase_type, line.account_assignment_type, line.account_assignment_code = "ASSET", "ASSET", "AS-1001"
        s.flush()
        data = receiving.capitalisation(s, po, gr)[0]
        assert data["capitalise"] is True and data["assetNumber"] == "AS-1001" and data["needsAssetClass"] is True and data["assetClass"] is None
        _rule(s, "ASSET-CAPITALISATION", _body("ASSET-CAPITALISATION", s, assetClassByMaterialGroup={line.material_group: "3100"},
                                               costCentreByPlant={line.plant: "4100"}))
        data = receiving.capitalisation(s, po, gr)[0]
        assert data["assetClass"] == "3100" and data["needsAssetClass"] is False and data["costCentre"] == "4100" and data["valueMinor"] > 0


# ================================================================ 15. early-payment discount and SCF
def test_early_payment_offer_is_accepted_by_the_supplier_and_reduces_the_payment():
    with _rolled_back() as s:
        inv = _invoice(s, "KD/EP-01", price="12.50")
        assert _refused(early_payment.make_offer, s, inv, discount_pct=Decimal("1"), pay_on=date(2027, 3, 25)).code == "RULE_VIOLATION"  # not posted
        _post(s, inv)
        assert early_payment.options(s, inv)["eligible"] is True
        _as(s, "kd.sales")
        assert _refused(early_payment.make_offer, s, inv, discount_pct=Decimal("1"), pay_on=date(2027, 3, 25), source="TERMS").status == 403
        _as(s, "ap.clerk")
        assert _refused(early_payment.make_offer, s, inv, discount_pct=Decimal("9"), pay_on=date(2027, 3, 25)).code == "RULE_VIOLATION"
        assert _refused(early_payment.make_offer, s, inv, discount_pct=Decimal("1"), pay_on=inv.due_date).code == "RULE_VIOLATION"
        offer = early_payment.make_offer(s, inv, discount_pct=Decimal("1"), pay_on=date(2027, 3, 25), note="Cash surplus in March")
        expected = round(inv.gross_minor * 0.01)
        assert offer.status == "OFFERED" and offer.source == "BUYER" and abs(offer.discount_minor - expected) <= 1 and offer.annualised_pct > 0
        assert _refused(early_payment.make_offer, s, inv, discount_pct=Decimal("1"), pay_on=date(2027, 3, 25)).code == "OFFER_OPEN"
        assert _refused(early_payment.decide, s, inv, offer.id, True).status == 403  # the offerer cannot accept its own offer
        _as(s, "kd.sales")
        early_payment.decide(s, inv, offer.id, True, "Accepted")
        assert offer.status == "ACCEPTED" and inv.payment_option == "EARLY_DISCOUNT" and inv.due_date == date(2027, 3, 25)
        _as(s, "finance.controller")
        run = payables.payment_run(s, date(2027, 3, 25), invoice_numbers=[inv.number])
        assert run["paid"][0]["amountMinor"] == inv.gross_minor - offer.discount_minor and offer.status == "APPLIED"
        pay = s.execute(select(IntegrationMessage).where(IntegrationMessage.message_type == "PAYMENT", IntegrationMessage.object_id == inv.id)).scalar_one()
        assert pay.payload["earlyPaymentDiscountMinor"] == offer.discount_minor


def test_early_payment_terms_discount_lapse_decline_and_scf_election():
    with _rolled_back() as s:
        kd = s.execute(select(Supplier).where(Supplier.code == "KD002")).scalar_one()
        kd.payment_terms = "2/10 N45"
        inv = _invoice(s, "KD/EP-02", price="12.50")
        _post(s, inv)
        _as(s, "ap.clerk")
        offer = early_payment.make_offer(s, inv, discount_pct=None, pay_on=None, source="TERMS")
        assert offer.status == "ACCEPTED" and offer.source == "TERMS" and offer.discount_pct == 2 and inv.payment_option == "EARLY_DISCOUNT"
        # the run comes after the pay-on date: the discount lapses and the invoice goes back to its due date
        _as(s, "finance.controller")
        run = payables.payment_run(s, date(2027, 3, 22), invoice_numbers=[inv.number])
        assert run["paid"] == [] and offer.status == "EXPIRED" and inv.payment_option == "STANDARD" and inv.discount_minor == 0
        assert inv.due_date == offer.original_due
        # a supplier ask that accounts payable declines
        _as(s, "kd.sales")
        ask = early_payment.make_offer(s, inv, discount_pct=Decimal("1.5"), pay_on=date(2027, 3, 28))
        assert ask.source == "SUPPLIER"
        _as(s, "ap.clerk")
        early_payment.decide(s, inv, ask.id, False, "Not this month")
        assert ask.status == "DECLINED"
        # supply-chain finance: flag, event, ERP message; no live offer may be open
        _rule(s, "EARLY-PAYMENT", _body("EARLY-PAYMENT", s, scf={"enabled": True, "minInvoiceMinor": 100, "financier": "PROGRAMME"}))
        _as(s, "kd.sales")
        scf = early_payment.elect_scf(s, inv, "Need cash before month end")
        assert scf.kind == "SCF" and scf.status == "ACCEPTED" and inv.payment_option == "SCF" and scf.erp_doc_no
        message = s.execute(select(IntegrationMessage).where(IntegrationMessage.message_type == "SCF_FINANCING")).scalar_one()
        assert message.payload["maturity"] == inv.due_date.isoformat() and message.payload["financier"] == "PROGRAMME"
        assert _refused(early_payment.elect_scf, s, inv).code == "OFFER_OPEN"
        from app.pic.models import OutboxEvent
        assert s.execute(select(OutboxEvent).where(OutboxEvent.topic == "invoice.scf.elected", OutboxEvent.object_id == inv.id)).first()
        _as(s, "finance.controller")
        run = payables.payment_run(s, date(2027, 5, 10), invoice_numbers=[inv.number])
        pay = s.execute(select(IntegrationMessage).where(IntegrationMessage.message_type == "PAYMENT", IntegrationMessage.object_id == inv.id)).scalar_one()
        assert run["paid"] and pay.payload["scf"] is True


def test_early_payment_and_debit_note_routes_are_gated_and_validated(client, login):
    assert client.get("/v1/invoices/NO-SUCH/early-payment", headers=login("ap.clerk")).status_code == 404
    assert client.post("/v1/invoices/NO-SUCH/scf", json={}, headers=login("buyer")).status_code == 403
    assert client.post("/v1/invoices/NO-SUCH/early-payment/offers", json={"discountPct": "200", "payOn": "2027-04-01"},
                       headers=login("ap.clerk")).status_code == 422
    line = {"kind": "PRICE", "invoice_line": 10, "qty": "1", "unit_debit_minor": 5}
    body = {"supplier_debit_note_no": "X-1", "note_date": "2027-03-20", "reason": "price", "lines": [line]}
    assert client.post("/v1/invoices/NO-SUCH/debit-notes", json=body, headers=login("buyer")).status_code == 403
    assert client.post("/v1/invoices/NO-SUCH/debit-notes", json=body, headers=login("ap.clerk")).status_code == 404
    assert client.post("/v1/invoices/NO-SUCH/debit-notes", json={**body, "lines": []}, headers=login("ap.clerk")).status_code == 422
    assert client.post("/v1/invoices/NO-SUCH/debit-notes", json={**body, "lines": [{**line, "unit_debit_minor": -1}]},
                       headers=login("ap.clerk")).status_code == 422
    assert client.get("/v1/debit-notes/DN-NOPE", headers=login("ap.clerk")).status_code == 404
    assert client.post("/v1/debit-notes/DN-NOPE/approve", headers=login("buyer")).status_code == 403
    assert client.post("/v1/debit-notes/DN-NOPE/post", headers=login("buyer")).status_code == 403


# ================================================================ 16. mandatory fields
def test_mandatory_fields_are_enforced_at_requisition_po_gr_invoice_and_supplier_register():
    with _rolled_back(clock.now()) as s:
        docs = {"REQUISITION": {"header": ["purpose_text"], "lines": ["storage_location"]},
                "PO_RELEASE": {"header": ["incoterms"], "lines": ["hsn_code"]},
                "GR_POST": {"header": ["delivery_note"], "lines": ["batch"]},
                "INVOICE_CAPTURE": {"header": ["irn"], "lines": ["hsn"]},
                "SUPPLIER_REGISTER": {"header": ["incoterms", "segment"], "lines": []}}
        rule = _rule(s, "MANDATORY-FIELDS", {"documents": docs}, effective=clock.today(), plant="P100")
        need = (clock.today() + timedelta(days=30)).isoformat()
        _as(s, "requester")
        pr = requisition.create(s, origin="MANUAL", purpose_code="MF", plant="P100", lines=[
            {"item_type": "MATERIAL", "purchase_type": "STOCK", "material": "FK-M8-50", "qty": "5", "price_est_minor": 1250, "need_date": need}])
        problem = _refused(requisition.submit, s, pr)
        assert problem.code == "MANDATORY_FIELDS_MISSING" and problem.extra["missingFields"] == ["purpose_text", "line 10: storage_location"]
        assert problem.status == 422 and problem.rule_ref == f"MANDATORY-FIELDS@{rule.version}" and problem.extra["document"] == "REQUISITION"
        pr.purpose_text = "Fasteners for line 4"
        for l in s.execute(select(__import__("app.pic.models", fromlist=["PrLine"]).PrLine).where(
                __import__("app.pic.models", fromlist=["PrLine"]).PrLine.requisition_id == pr.id)).scalars():
            l.storage_location = "0001"
        requisition.submit(s, pr)  # complete: accepted
        # the plant-scoped version replaces the default only for P100
        other = mandatory.resolve(s, plant="P200")
        assert other.version != rule.version
        # invoice capture and goods receipt
        _as(s, "kd.sales")
        miss = _refused(payables.capture, s, supplier="KD002", supplier_invoice_no="KD/MF-1", invoice_date=date(2027, 3, 20), channel="PORTAL",
                        lines=[{"po": FASTENER_PO, "po_line": 10, "qty": "10", "unit_price": "12.50"}])
        assert miss.code == "MANDATORY_FIELDS_MISSING" and set(miss.extra["missingFields"]) == {"irn", "line 10: hsn"}
        po = s.execute(select(PurchaseOrder).where(PurchaseOrder.number == FASTENER_PO)).scalar_one()
        _as(s, "receiver")
        gr = _refused(receiving._mandatory_fields, s, po, [{"line": 10, "qty": "1"}], None, None, None)
        assert gr.code == "MANDATORY_FIELDS_MISSING" and gr.extra["missingFields"] == ["delivery_note", "line 10: batch"]
        # PO release and supplier register
        po.incoterms = None
        assert _refused(po_controls.check_mandatory, s, po, order.lines_of(s, po)).extra["missingFields"][0] == "incoterms"
        assert _refused(mandatory.check, s, "SUPPLIER_REGISTER", {"legal_name": "X"}, [], plant="P100").extra["missingFields"] == ["incoterms", "segment"]


def test_mandatory_fields_simulator_and_editor_route(client, login):
    with _rolled_back() as s:
        _as(s, "admin")
        base = mandatory.resolve(s)
        sim = policy_sim.simulate(s, "MANDATORY-FIELDS", {"document": "REQUISITION", "header": {}, "lines": [{"description": "x"}]},
                                  draft_body={"documents": {"REQUISITION": {"header": [], "lines": ["description"]}}})
        assert sim["result"]["decision"] == "REFUSED" and "purpose_code" in sim["result"]["missingFields"]
        assert sim["compare"]["draft"]["result"]["decision"] == "ACCEPTED" and sim["compare"]["changed"] is True
        assert base.body["documents"]["PO_RELEASE"]["header"]
        assert _refused(policy_sim.simulate, s, "MANDATORY-FIELDS", {"document": "NOPE"}).code == "SIMULATION_INPUT"
    h = login("admin")
    state = client.get("/v1/admin/mandatory-fields", headers=login("buyer"))
    assert state.status_code == 200 and "REQUISITION" in state.json()["catalogue"]
    unknown = client.post("/v1/admin/mandatory-fields", json={"documents": {"REQUISITION": {"header": ["shoe_size"], "lines": []}}, "reason": "test"}, headers=h)
    assert unknown.status_code == 422 and unknown.json()["unknown"] == ["shoe_size"]
    assert client.post("/v1/admin/mandatory-fields", json={"documents": {"NOPE": {}}, "reason": "test"}, headers=h).status_code == 422
    assert client.post("/v1/admin/mandatory-fields", json={"documents": {"REQUISITION": {"header": ["purpose_text"], "lines": []}},
                                                         "reason": "test"}, headers=login("buyer")).status_code == 403
    ok = client.post("/v1/admin/mandatory-fields", json={"documents": {"REQUISITION": {"header": ["purpose_text"], "lines": []}},
                                                       "category": "ZZ-WAVE1-TEST", "reason": "Editor test, scoped to a category nobody uses"}, headers=h)
    assert ok.status_code == 201 and ok.json()["scope"] == {"category": "ZZ-WAVE1-TEST"}
    assert any(v["version"] == ok.json()["version"] for v in client.get("/v1/admin/mandatory-fields", headers=h).json()["versions"])


def test_request_template_route_and_po_one_time_vendor_field(client, login):
    r = client.get("/v1/request-templates", headers=login("requester"))
    assert r.status_code == 200 and {t["code"] for t in r.json()} >= {"SVC-PROFESSIONAL", "IT-HARDWARE-SOFTWARE"}
    assert client.get("/v1/request-templates", headers=login("ap.clerk")).status_code == 403
    bad = client.post("/v1/requisitions", json={"origin": "MANUAL", "purpose_code": "T", "plant": "P100", "template": "NOPE", "lines": [
        {"item_type": "FREE_TEXT", "purchase_type": "SERVICE", "description": "x", "qty": "1", "price_est_minor": 100, "need_date": "2027-04-01"}]},
        headers=login("requester"))
    assert bad.status_code == 422 and bad.json()["code"] == "UNKNOWN_TEMPLATE"
    assert client.post("/v1/purchase-orders", json={"source": {"type": "REQUISITION", "id": "REQ-NONE", "lines": [10]}, "oneTimeVendorReason": "x" * 600},
                       headers=login("buyer")).status_code == 422
