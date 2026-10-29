"""Review fixes F7 (invoice → match → post → pay) and F8 (supplier onboarding, certificates, bank changes, scorecard).

Every test runs in a transaction that is rolled back (users are switched inside it), on PO-77416 (KD002, 2,000 fastener
kits FK-M8-50 received, nothing invoiced) and the onboarded Axion suppliers, so the signature case and every KPI stay
exactly as seeded.
"""
import uuid
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuditEvent, BankChangeRequest, Certificate, GoodsReceipt, GrLine, IntegrationMessage, Invoice, InvoiceException, Payment,
    PoLine, PoScheduleLine, ProcessInstance, PurchaseOrder, Qualification, Scorecard, Supplier, SupplierBankAccount, SupplierCategoryStatus,
    Task, Tenant, Timer, TwinFeedback,
)
from app.pic.platform import clock, integration, workflow
from app.pic.platform.auth import Principal, hash_password, scopes_for
from app.pic.platform.errors import Problem
from app.pic.services import payables, supplier as supplier_svc
from app.pic.services.common import days_from_terms
from app.pic.services.master_changes import gstin_check_char

FASTENER_PO = "PO-77416"
WHEN = clock.at_ist(date(2027, 3, 20), 10)


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
                yield s
                raise _Rollback()
    finally:
        clock.set_pinned(None)
        integration.FAULTS.update(fail=0, lose_response=0)


def _invoice(s, number: str, qty: str, price: str = "12.50", day: date = date(2027, 3, 20), supplier: str = "KD002", po: str = FASTENER_PO):
    _as(s, "kd.sales" if supplier == "KD002" else "tf.sales")
    return payables.capture(s, supplier=supplier, supplier_invoice_no=number, invoice_date=day, channel="PORTAL",
                            lines=[{"po": po, "po_line": 10, "qty": qty, "unit_price": price, "gst_rate": "18", "hsn": "73181500"}])


def _open(s, invoice, etype=None):
    query = select(InvoiceException).where(InvoiceException.invoice_id == invoice.id, InvoiceException.status == "OPEN")
    if etype:
        query = query.where(InvoiceException.type == etype)
    return s.execute(query).scalars().all()


def _post(s, invoice):
    _as(s, "ap.clerk")
    payables.approve(s, invoice)
    return payables.post(s, invoice, payables.posting_key(s, invoice))


def _extra_user(s, local: str, roles: list[str]) -> None:
    s.add(AppUser(tenant_id=_axn(), email=f"{local}@axion.example", full_name=local.replace(".", " ").title(),
                  password_hash=hash_password("Unused-Password-1"), roles=roles, attributes={"categories": ["*"]}, mfa_enrolled=True))
    s.flush()


def _complete_all(s, object_id, users: list[str], comment="Verified") -> list[uuid.UUID]:
    """Complete the open tasks on an object as the first listed user who may work each; returns who completed them."""
    done = []
    for _ in range(6):
        tasks = s.execute(select(Task).where(Task.object_id == object_id, Task.status == "OPEN").order_by(Task.sequence)).scalars().all()
        if not tasks:
            return done
        for task in tasks:
            for who in users:
                _as(s, who)
                if workflow.can_work(s.info["principal"], task) is None:
                    workflow.complete(s, task.id, "APPROVE", comment)
                    done.append(s.info["principal"].user_id)
                    break
            else:
                raise AssertionError(f"nobody of {users} may work task {task.name}")
    return done


# ---------------------------------------------------------------- 1. duplicate hold survives "Re-run match"
def test_duplicate_hold_survives_rematch_and_is_released_only_as_not_duplicate():
    with _rolled_back() as s:
        first = _invoice(s, "KD/FK-REV-01", "100")
        assert first.status == "MATCHED"
        dup = _invoice(s, "KD/FK-REV-01-R", "100")
        assert dup.status == "EXCEPTION" and [e.type for e in _open(s, dup)] == ["DUPLICATE"]
        _as(s, "ap.clerk")
        with pytest.raises(Problem) as held:
            payables.match(s, dup)
        assert held.value.code == "DUPLICATE_HOLD" and dup.status == "EXCEPTION" and dup.payment_block is True
        exc = _open(s, dup, "DUPLICATE")[0]
        with pytest.raises(Problem) as wrong:
            payables.resolve_exception(s, dup, exc.id, "GR_POSTED", "receipt is there")
        assert wrong.value.code == "INVALID_RESOLUTION"
        result = payables.resolve_exception(s, dup, exc.id, "NOT_DUPLICATE", "Second delivery, confirmed with Kovai")
        assert result["status"] == "MATCHED" and dup.duplicate_of is None


def test_reject_closes_a_held_invoice(client, login):
    with _rolled_back() as s:
        _invoice(s, "KD/FK-REV-02", "100")
        dup = _invoice(s, "KD/FK-REV-02-R", "100")
        _as(s, "ap.clerk")
        payables.reject(s, dup, "Duplicate of KD/FK-REV-02")
        assert dup.status == "REJECTED" and not _open(s, dup)
        with pytest.raises(Problem):
            payables.reject(s, dup, "again")  # REJECTED → reject is not a transition
    r = client.post("/v1/invoices/NO-SUCH-INVOICE/reject", json={"reason": "x"}, headers=login("buyer"))
    assert r.status_code == 403  # invoice:resolve only


# ---------------------------------------------------------------- 2. own purchase orders only
def test_capture_refuses_another_suppliers_po_and_unknown_po():
    with _rolled_back() as s:
        with pytest.raises(Problem) as other:
            _invoice(s, "TF/FK-REV-03", "10", supplier="TF001")
        assert other.value.status == 404
        with pytest.raises(Problem) as unknown:
            _invoice(s, "KD/FK-REV-03", "10", po="PO-NO-SUCH")
        assert unknown.value.status == 404
        with pytest.raises(Problem) as line:
            _as(s, "kd.sales")
            payables.capture(s, supplier="KD002", supplier_invoice_no="KD/FK-REV-03B", invoice_date=date(2027, 3, 20), channel="PORTAL",
                             lines=[{"po": FASTENER_PO, "po_line": 990, "qty": "1", "unit_price": "12.50"}])
        assert line.value.status == 404


# ---------------------------------------------------------------- 3. the same receipt is not invoiced twice
def test_second_unposted_invoice_cannot_claim_the_same_receipt_and_approval_rechecks():
    with _rolled_back() as s:
        a = _invoice(s, "KD/FK-REV-04A", "1500")
        assert a.status == "MATCHED"
        b = _invoice(s, "KD/FK-REV-04B", "1000", day=date(2027, 3, 10))
        quantity = _open(s, b, "QUANTITY")
        assert b.status == "EXCEPTION" and quantity and quantity[0].delta == {"qty": "500"}
        assert "already on other invoices not yet posted" in quantity[0].detail
        assert payables._lines(s, b)[0].match_detail["pendingInvoicedQty"] == "1500"
        # Re-check at approval: the receipt shrank after the match (e.g. a return) → back through the match.
        po_line = s.execute(select(PoLine).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id)
                            .where(PurchaseOrder.number == FASTENER_PO)).scalar_one()
        po_line.received_qty = Decimal(1000)
        po_line.accepted_qty = Decimal(1000)
        s.flush()
        _as(s, "ap.clerk")
        payables.approve(s, a)
        assert a.status == "EXCEPTION" and _open(s, a, "QUANTITY")


# ---------------------------------------------------------------- 4. blocked supplier: no invoice, no payment
def test_blocked_supplier_is_not_paid_and_cannot_invoice_until_unblocked():
    with _rolled_back() as s:
        inv = _invoice(s, "KD/FK-REV-05", "200")
        assert _post(s, inv)["status"] == "POSTED"
        _as(s, "supplier.manager")
        kd = s.execute(select(Supplier).where(Supplier.code == "KD002")).scalar_one()
        result = supplier_svc.block(s, kd, "Sanctions alert under review")
        assert inv.number in result["paymentBlocked"] and inv.payment_block is True
        assert s.execute(select(AuditEvent).where(AuditEvent.object_id == inv.id, AuditEvent.action == "PAYMENT_BLOCKED")).first()
        inv.payment_block = False  # even if someone clears the flag, the run skips a blocked supplier
        _as(s, "finance.controller")
        run = payables.payment_run(s, date(2027, 3, 20), include_not_due=True, invoice_numbers=[inv.number])
        assert run["paid"] == [] and "blocked" in run["skipped"][0]["reason"]
        inv.payment_block = True
        with pytest.raises(Problem) as refused:
            _invoice(s, "KD/FK-REV-05B", "10")
        assert refused.value.code == "SUPPLIER_BLOCKED"
        _as(s, "supplier.manager")
        lifted = supplier_svc.unblock(s, kd, "Alert was a false positive (name match only)")
        assert lifted["status"] == "ACTIVE" and inv.number in lifted["paymentBlockLifted"] and inv.payment_block is False
        assert s.execute(select(SupplierCategoryStatus.status).where(SupplierCategoryStatus.supplier_id == kd.id,
                                                                     SupplierCategoryStatus.category == "ALU-DIECAST")).scalar_one() == "QUALIFIED"
        _as(s, "finance.controller")
        run = payables.payment_run(s, date(2027, 3, 20), include_not_due=True, invoice_numbers=[inv.number])
        assert [p["invoice"] for p in run["paid"]] == [inv.number] and inv.status == "PAID"


# ---------------------------------------------------------------- 5. credit note and invoice quantities
def test_credit_notes_are_validated_and_nothing_payable_is_skipped(client, login):
    with _rolled_back() as s:
        inv = _invoice(s, "KD/FK-REV-06", "100")
        _as(s, "kd.sales")
        for lines, code in (([{"invoice_line": 10, "qty": "101"}], "INVALID_CREDIT_NOTE"),
                            ([{"invoice_line": 20, "qty": "1"}], "INVALID_CREDIT_NOTE"),
                            ([{"invoice_line": 10, "qty": "0"}], "INVALID_CREDIT_NOTE"),
                            ([{"invoice_line": 10, "qty": "-5"}], "INVALID_CREDIT_NOTE"),
                            ([{"invoice_line": 10, "qty": "10", "unit_credit_minor": 5000}], "INVALID_CREDIT_NOTE")):
            with pytest.raises(Problem) as bad:
                payables.submit_credit_note(s, inv, supplier_credit_note_no="CN-FK-X", note_date=date(2027, 3, 20), reason="test", lines=lines)
            assert bad.value.code == code
        payables.submit_credit_note(s, inv, supplier_credit_note_no="CN-FK-1", note_date=date(2027, 3, 20), reason="Short shipment",
                                    lines=[{"invoice_line": 10, "qty": "60"}])
        with pytest.raises(Problem):  # 60 already credited: only 40 left
            payables.submit_credit_note(s, inv, supplier_credit_note_no="CN-FK-2", note_date=date(2027, 3, 20), reason="again",
                                        lines=[{"invoice_line": 10, "qty": "41"}])
        payables.submit_credit_note(s, inv, supplier_credit_note_no="CN-FK-3", note_date=date(2027, 3, 20), reason="rest",
                                    lines=[{"invoice_line": 10, "qty": "40"}])
        assert _post(s, inv)["status"] == "POSTED"
        _as(s, "finance.controller")
        run = payables.payment_run(s, date(2027, 3, 20), include_not_due=True, invoice_numbers=[inv.number])
        assert run["paid"] == [] and run["skipped"][0]["reason"].startswith("nothing payable")
    r = client.post("/v1/invoices", headers=login("kd.sales"), json={
        "supplier_invoice_no": "KD/NEG-1", "invoice_date": "2027-03-20", "channel": "PORTAL",
        "lines": [{"po": FASTENER_PO, "po_line": 10, "qty": "-5", "unit_price": "12.50"}]})
    assert r.status_code == 422
    r = client.post("/v1/invoices/NO-SUCH/credit-notes", headers=login("kd.sales"), json={
        "supplier_credit_note_no": "CN-NEG", "note_date": "2027-03-20", "reason": "neg", "lines": [{"invoice_line": 10, "qty": "-1"}]})
    assert r.status_code == 422


# ---------------------------------------------------------------- 6. payment terms
def test_terms_parse_net_days_and_due_date_follows_the_po():
    assert [days_from_terms(t) for t in ("N60", "60", "2/10 N45", "n30", "", "IMMEDIATE")] == [60, 60, 45, 30, 0, 0]
    assert supplier_svc.payment_terms_errors("2/10 N45") == [] and supplier_svc.payment_terms_errors("N60") == []
    assert supplier_svc.payment_terms_errors("2/10N45x") and supplier_svc.payment_terms_errors("net sixty")
    with _rolled_back() as s:
        po = s.execute(select(PurchaseOrder).where(PurchaseOrder.number == FASTENER_PO)).scalar_one()
        po.payment_terms = "2/10 N15"  # the PO's terms, not the supplier master's N45
        inv = _invoice(s, "KD/FK-REV-07", "10")
        _post(s, inv)
        assert inv.due_date == date(2027, 3, 20) + timedelta(days=15)
        _as(s, "supplier.manager")
        with pytest.raises(Problem) as bad:
            supplier_svc.register(s, code="TRM901", legal_name="Terms Test Works Pvt Ltd", gstin=_gstin("AABCT9011Q"), pan="AABCT9011Q",
                                  state_code="33", contact_email="a@terms.example", categories=["MRO"], payment_terms="2/10N45x")
        assert bad.value.code == "VALIDATION_FAILED"


# ---------------------------------------------------------------- 7/8. price variance: line level, value credit, buyer approval
def test_price_tolerance_is_line_level():
    with _rolled_back() as s:
        po_line = s.execute(select(PoLine).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(PurchaseOrder.number == FASTENER_PO)).scalar_one()
        po_line.unit_price_minor = 40000  # ₹400: ₹403 is 0.75 % per unit (inside the old per-unit test)...
        s.flush()
        inv = _invoice(s, "KD/FK-REV-08", "1000", price="403")
        price = _open(s, inv, "PRICE")
        assert inv.status == "EXCEPTION" and price  # ...but ₹3,000 on the line, above min(1 % = ₹4,000, ₹500)
        assert price[0].delta["lineVarianceMinor"] == 300000
        small = _invoice(s, "KD/FK-REV-08B", "10", price="403", day=date(2027, 3, 5))  # ₹30 on the line: within ₹500 / 1 %
        assert not _open(s, small, "PRICE")


def test_value_credit_note_clears_a_price_exception():
    with _rolled_back() as s:
        inv = _invoice(s, "KD/FK-REV-09", "1000", price="13.50")
        exc = _open(s, inv, "PRICE")[0]
        _as(s, "kd.sales")
        payables.submit_credit_note(s, inv, supplier_credit_note_no="CN-FK-PRICE", note_date=date(2027, 3, 21), reason="Price as per PO",
                                    lines=[{"invoice_line": 10, "qty": "1000", "unit_credit_minor": 100}])
        _as(s, "ap.clerk")
        result = payables.resolve_exception(s, inv, exc.id, "CREDIT_NOTE_RECEIVED", "Value credit received", "CN-FK-PRICE")
        assert result["status"] == "MATCHED"
        assert payables._lines(s, inv)[0].match_detail["priceVarianceMinor"] == 0


def test_price_acceptance_needs_a_buyer_and_reprices_the_po():
    with _rolled_back() as s:
        inv = _invoice(s, "KD/FK-REV-10", "1000", price="13.50")
        exc = _open(s, inv, "PRICE")[0]
        po = s.execute(select(PurchaseOrder).where(PurchaseOrder.number == FASTENER_PO)).scalar_one()
        po_line = s.execute(select(PoLine).where(PoLine.po_id == po.id)).scalar_one()
        _as(s, "ap.clerk")
        result = payables.resolve_exception(s, inv, exc.id, "PRICE_ACCEPTED", "Zinc surcharge agreed")
        assert exc.status == "OPEN" and inv.status == "EXCEPTION" and po_line.unit_price_minor == 1250 and result["priceApproval"]
        task = s.execute(select(Task).where(Task.object_id == inv.id, Task.kind == "PRICE_VARIANCE", Task.status == "OPEN")).scalar_one()
        assert task.candidate_role == "BUYER" and po.created_by in task.excluded_user_ids
        with pytest.raises(Problem):
            payables.resolve_exception(s, inv, exc.id, "PRICE_ACCEPTED", "again")  # already waiting
        _as(s, "stores.buyer")  # created the PO: may not approve its price change
        assert workflow.can_work(s.info["principal"], task)
        _as(s, "buyer.lead")
        workflow.complete(s, task.id, "APPROVE", "Surcharge agreed for March")
        assert exc.status == "RESOLVED" and exc.resolution == "PRICE_ACCEPTED" and po_line.unit_price_minor == 1350
        assert inv.status == "MATCHED"
        assert s.execute(select(AuditEvent).where(AuditEvent.object_id == po.id, AuditEvent.action == "PRICE_VARIANCE_ACCEPTED")).first()


# ---------------------------------------------------------------- 9. paid and reconciled only on the ERP outcome
def test_payment_is_reconciled_only_when_the_erp_posts_it():
    from app.pic.platform import connectors
    with _rolled_back() as s:
        inv = _invoice(s, "KD/FK-REV-11", "100")
        _post(s, inv)
        _as(s, "finance.controller")
        integration.FAULTS["fail"] = 1  # the ERP does not answer the payment posting
        run = payables.payment_run(s, date(2027, 3, 20), include_not_due=True, invoice_numbers=[inv.number])
        assert run["paid"][0]["integrationStatus"] == "RETRY" and run["paid"][0]["clearing"] is None
        payment = s.execute(select(Payment).where(Payment.invoice_id == inv.id)).scalar_one()
        instance = payables._instance(s, inv)
        assert inv.status == "POSTED" and inv.payment_status == "IN_PAYMENT" and instance.status == "RUNNING"
        _as(s, "ap.clerk")
        recon = payables.reconcile(s, "1000")
        assert {"kind": "PAYMENT_MISSING_IN_ERP", "ref": payment.number} in [{"kind": i["kind"], "ref": i["ref"]} for i in recon["items"]]
        message = s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == f"PAY|{payment.number}")).scalar_one()
        integration.process(s, message)  # the connector worker retries
        assert inv.status == "PAID" and inv.payment_status == "PAID" and instance.status == "COMPLETED"
        assert "reconciled" in [st for st in workflow.history(s, instance)["path"] if st["step"] == "F7-09"][0]["outcome"]
        again = payables.reconcile(s, "1000")
        assert payment.number not in [i["ref"] for i in again["items"]]
    assert connectors.maps("SAP_S4", "SUPPLIER_CREDIT_MEMO") and not connectors.maps("TALLY_PRIME", "SUPPLIER_CREDIT_MEMO")
    assert not connectors.maps("DYNAMICS_365", "PAYMENT") and not connectors.maps("ODOO", "GOODS_RECEIPT")
    with pytest.raises(Problem) as unmapped:
        connectors.require_mapped("DYNAMICS_365", "PAYMENT")
    assert unmapped.value.code == "MESSAGE_TYPE_NOT_MAPPED"


# ---------------------------------------------------------------- 10/14. screening disposition and per-category qualification
def _gstin(pan: str, state: str = "33") -> str:
    body = f"{state}{pan}1Z"
    return body + gstin_check_char(body)


def _onboard_to_qualification(s, legal_name: str, pan: str, categories: list[str]):
    _as(s, "supplier.manager")
    sup = supplier_svc.register(s, code=f"RV{uuid.uuid4().hex[:5].upper()}", legal_name=legal_name, gstin=_gstin(pan), pan=pan,
                                state_code="33", contact_email="ap@review.example", categories=categories, payment_terms="N30")
    result = supplier_svc.submit_profile(s, sup, bank_account="123456789012", ifsc="SBIN0001234", holder_name=legal_name, certificates=[])
    change = s.execute(select(BankChangeRequest).where(BankChangeRequest.number == result["bankChange"])).scalar_one()
    _extra_user(s, "supplier.manager2", ["SUPPLIER_MANAGER"])
    _as(s, "supplier.manager2")
    supplier_svc.callback_verify(s, change, "Called the registered landline")
    approvers = _complete_all(s, change.id, ["finance.controller", "finance.controller2"])
    assert len(set(approvers)) == 2 and change.status == "APPROVED"
    _as(s, "supplier.manager")
    quals = []
    for category in categories:
        q = supplier_svc.start_qualification(s, sup, category)
        supplier_svc.record_assessment(s, q, questionnaire_score=Decimal(80), audit_score=Decimal(80))
        quals.append(q)
    return sup, result["screening"], quals


def test_review_screening_gates_qualification_until_disposed_by_another_manager():
    with _rolled_back() as s:
        sup, screening, (fasteners, mro) = _onboard_to_qualification(s, "Kovai Diecast Private Limited", "AABCK7712R", ["FASTENERS", "MRO"])
        assert screening["outcome"] == "REVIEW" and any(d["code"] == "KD002" for d in screening["duplicates"])
        with pytest.raises(Problem) as gated:
            supplier_svc.decide_qualification(s, fasteners, "QUALIFIED", "Audit 80/100")
        assert gated.value.rule_ref == "F8-03" and sup.status == "REGISTERED"
        with pytest.raises(Problem) as own:
            supplier_svc.dispose_screening(s, sup, "CLEAR", "Different legal entity")  # the registrant
        assert own.value.code == "SOD_CONFLICT"
        _as(s, "supplier.manager2")
        supplier_svc.dispose_screening(s, sup, "CLEAR", "Different PAN and GSTIN; unrelated to Kovai Diecast (MCA check)")
        assert sup.screening["disposition"]["decision"] == "CLEARED"
        first = supplier_svc.decide_qualification(s, fasteners, "QUALIFIED", "Audit 80/100")
        instance = s.execute(select(ProcessInstance).where(ProcessInstance.business_id == sup.id)).scalar_one()
        assert first["stillQualifying"] == ["MRO"] and instance.status == "RUNNING" and sup.status == "ACTIVE"
        with pytest.raises(Problem) as twice:
            supplier_svc.decide_qualification(s, fasteners, "REJECTED", "again")
        assert twice.value.code == "ILLEGAL_TRANSITION"
        supplier_svc.decide_qualification(s, mro, "REJECTED", "No MRO capability")
        assert instance.status == "COMPLETED"


def test_merge_disposition_closes_the_duplicate_registration():
    with _rolled_back() as s:
        sup, screening, (q,) = _onboard_to_qualification(s, "Kovai Diecast Pvt. Ltd.", "AABCK7713S", ["FASTENERS"])
        _as(s, "supplier.manager2")
        with pytest.raises(Problem):
            supplier_svc.dispose_screening(s, sup, "MERGE", "Same group", merge_into="TF001")  # not a suspected duplicate
        supplier_svc.dispose_screening(s, sup, "MERGE", "Same company re-registered", merge_into="KD002")
        assert sup.status == "MERGED" and q.status == "DECIDED"
        with pytest.raises(Problem):
            supplier_svc.decide_qualification(s, s.get(Qualification, q.id), "QUALIFIED", "x")


# ---------------------------------------------------------------- 11 + coordinator: bank details through the profile only in onboarding
def test_active_supplier_bank_change_needs_the_bank_change_process_and_two_controllers():
    with _rolled_back() as s:
        tf = s.execute(select(Supplier).where(Supplier.code == "TF001")).scalar_one()
        _as(s, "tf.sales")
        with pytest.raises(Problem) as refused:
            supplier_svc.submit_profile(s, tf, bank_account="30112345999", ifsc="SBIN0001234", holder_name="Trichy Forge Pvt Ltd")
        assert refused.value.code == "BANK_CHANGE_PROCESS_REQUIRED" and "/bank-changes" in refused.value.detail
        verified_before = {c.id: c.verified for c in s.execute(select(Certificate).where(Certificate.supplier_id == tf.id)).scalars()}
        _as(s, "supplier.manager")
        change = supplier_svc.request_bank_change(s, tf, bank_account="30112345999", ifsc="SBIN0001234", holder_name="Trichy Forge Pvt Ltd")
        _extra_user(s, "supplier.manager2", ["SUPPLIER_MANAGER"])
        _as(s, "supplier.manager2")
        supplier_svc.callback_verify(s, change, "Called the TF001 accounts head")
        first = s.execute(select(Task).where(Task.object_id == change.id, Task.status == "OPEN")).scalar_one()
        _as(s, "finance.controller")
        workflow.complete(s, first.id, "APPROVE", "Bank letter checked")
        second = s.execute(select(Task).where(Task.object_id == change.id, Task.status == "OPEN")).scalar_one()
        assert change.status == "PENDING_APPROVAL" and second.candidate_role == "FINANCE_CONTROLLER"
        assert workflow.can_work(s.info["principal"], second)  # finance.controller cannot approve twice
        account = s.get(SupplierBankAccount, change.bank_account_id)
        assert account.active is False
        _as(s, "finance.controller2")
        workflow.complete(s, second.id, "APPROVE", "Cancelled cheque checked")
        assert change.status == "APPROVED" and account.active is True and len(set(change.approvals)) == 2
        # the bank approval no longer marks certificates verified
        assert {c.id: c.verified for c in s.execute(select(Certificate).where(Certificate.supplier_id == tf.id)).scalars()} == verified_before


def test_onboarding_bank_change_after_onboarding_ended_still_gets_dual_approval():
    with _rolled_back() as s:
        tf = s.execute(select(Supplier).where(Supplier.code == "TF001")).scalar_one()
        _as(s, "supplier.manager")
        change = supplier_svc.request_bank_change(s, tf, bank_account="30112345888", ifsc="SBIN0001234", holder_name="Trichy Forge Pvt Ltd",
                                                  in_onboarding=True)
        _extra_user(s, "supplier.manager2", ["SUPPLIER_MANAGER"])
        _as(s, "supplier.manager2")
        supplier_svc.callback_verify(s, change, "Called back")
        assert workflow.find(s, "BANK_CHANGE", change.id) is not None
        approvers = _complete_all(s, change.id, ["finance.controller", "finance.controller2"])
        assert len(set(approvers)) == 2 and change.status == "APPROVED"


def test_profile_api_is_role_gated(client, login):
    r = client.post("/v1/suppliers/TF001/profile", headers=login("buyer"), json={"certificates": []})
    assert r.status_code == 403
    r = client.post("/v1/suppliers/TF001/profile", headers=login("kd.sales"), json={"certificates": [
        {"type": "ISO9001", "number": "QMS-X", "issued_on": "2026-01-01", "expires_on": "2029-01-01"}]})
    assert r.status_code == 403  # another supplier's profile
    r = client.post("/v1/suppliers/TF001/bank-changes", headers=login("tf.sales"),
                    json={"bank_account": "30112345999", "ifsc": "SBIN0001234", "holder_name": "Trichy Forge Pvt Ltd"})
    assert r.status_code == 403
    r = client.post("/v1/suppliers/TF001/bank-changes", headers=login("supplier.manager"),
                    json={"bank_account": "30112345999", "ifsc": "sbin01234", "holder_name": "Trichy Forge Pvt Ltd"})
    assert r.status_code == 422


# ---------------------------------------------------------------- 12/13. certificates
def test_certificate_upload_arms_expiry_and_renewal_keeps_the_category():
    with _rolled_back(clock.at_ist(date(2027, 5, 20), 10)) as s:
        tf = s.execute(select(Supplier).where(Supplier.code == "TF001")).scalar_one()
        old = s.execute(select(Certificate).where(Certificate.supplier_id == tf.id, Certificate.type == "ISO14001")).scalar_one()
        old.mandatory_for = []  # what the supplier declared does not matter: SUPPLIER-QUAL makes ISO 14001 mandatory for ALU-DIECAST
        _as(s, "tf.sales")
        (renewal,) = supplier_svc.add_certificates(s, tf, [{"type": "ISO14001", "number": "EMS-TF001-2207-R1", "issued_on": "2027-05-15",
                                                           "expires_on": "2030-05-14", "mandatory_for": ["SOMETHING-ELSE"]}])
        assert renewal.mandatory_for == ["ALU-DIECAST"] and renewal.verified is False
        timer = s.execute(select(Timer).where(Timer.object_id == renewal.id, Timer.kind == "CERTIFICATE_EXPIRY", Timer.fired_at.is_(None))).scalar_one()
        assert timer.due_at == clock.at_ist(date(2030, 5, 15), 0, 5)
        assert supplier_svc.current_certificate(s, tf.id, "ISO14001").id == renewal.id
        clock.set_pinned(clock.at_ist(date(2027, 6, 1), 0, 5))
        supplier_svc._certificate_expired(s, SimpleNamespace(object_id=old.id, due_at=clock.now(), payload={}))
        status = s.execute(select(SupplierCategoryStatus.status).where(SupplierCategoryStatus.supplier_id == tf.id,
                                                                       SupplierCategoryStatus.category == "ALU-DIECAST")).scalar_one()
        assert old.status == "EXPIRED" and status == "QUALIFIED"


def test_expiry_without_renewal_downgrades_from_the_rule():
    with _rolled_back(clock.at_ist(date(2027, 6, 1), 0, 5)) as s:
        tf = s.execute(select(Supplier).where(Supplier.code == "TF001")).scalar_one()
        old = s.execute(select(Certificate).where(Certificate.supplier_id == tf.id, Certificate.type == "ISO14001")).scalar_one()
        old.mandatory_for = []
        supplier_svc._certificate_expired(s, SimpleNamespace(object_id=old.id, due_at=clock.now(), payload={}))
        status = s.execute(select(SupplierCategoryStatus.status).where(SupplierCategoryStatus.supplier_id == tf.id,
                                                                       SupplierCategoryStatus.category == "ALU-DIECAST")).scalar_one()
        assert status == "CONDITIONAL"


def test_certificate_verification_is_explicit_audited_and_four_eyes():
    with _rolled_back() as s:
        tf = s.execute(select(Supplier).where(Supplier.code == "TF001")).scalar_one()
        _as(s, "supplier.manager")
        (mine,) = supplier_svc.add_certificates(s, tf, [{"type": "ISO45001", "number": "OHS-TF-1", "issued_on": "2027-01-01",
                                                         "expires_on": "2030-01-01"}])
        with pytest.raises(Problem) as own:
            supplier_svc.verify_certificate(s, mine, "Register checked")
        assert own.value.code == "SOD_CONFLICT"
        _as(s, "buyer")
        with pytest.raises(Problem) as role:
            supplier_svc.verify_certificate(s, mine, "Register checked")
        assert role.value.status == 403
        _as(s, "quality.inspector")
        supplier_svc.verify_certificate(s, mine, "Certification body register checked")
        assert mine.verified is True
        assert s.execute(select(AuditEvent).where(AuditEvent.object_id == tf.id, AuditEvent.action == "CERTIFICATE_VERIFIED")).first()
        with pytest.raises(Problem) as again:
            supplier_svc.verify_certificate(s, mine, "again")
        assert again.value.code == "ALREADY_VERIFIED"


# ---------------------------------------------------------------- 15. internal invoice numbers
def test_internal_invoice_number_never_collides_or_truncates():
    with _rolled_back() as s:
        inv = _invoice(s, "INV-TF-8812", "10")  # TF001's number: Kovai's gets a prefixed internal number
        assert inv.number == "KD002/INV-TF-8812" and inv.supplier_invoice_no == "INV-TF-8812"
        assert payables._internal_number(s, "KD002", "INV-TF-8812", "2026-27") == "KD002/2026-27/INV-TF-8812"
        long_no = "KD/" + "9" * 34
        number = payables._internal_number(s, "KD002", long_no, "2026-27")
        assert len(number) <= 30 and number.startswith("KD002-")
        priced = _invoice(s, "KD/FK-REV-12", "10", price="12.505", day=date(2027, 3, 1))
        assert payables._lines(s, priced)[0].unit_price_minor == 1251  # rounded, not truncated


# ---------------------------------------------------------------- 16. scorecard OTIF against delivery schedules; reversals leave it
def _gr_and_line(s):
    po = s.execute(select(PurchaseOrder).where(PurchaseOrder.number == FASTENER_PO)).scalar_one()
    gr = s.execute(select(GoodsReceipt).where(GoodsReceipt.po_id == po.id)).scalar_one()
    return po, gr, s.execute(select(GrLine).where(GrLine.gr_id == gr.id)).scalar_one()


def test_receipt_is_scored_against_the_schedule_lines_it_fulfils():
    with _rolled_back() as s:
        po, gr, line = _gr_and_line(s)
        assert supplier_svc.receipt_line_otif(s, gr, po, line) is True  # one schedule line, need date 24 Feb, received 23 Feb
        for sl in s.execute(select(PoScheduleLine).where(PoScheduleLine.po_line_id == line.po_line_id)).scalars():
            s.delete(sl)
        s.flush()
        for seq, day in ((1, date(2027, 2, 20)), (2, date(2027, 3, 10))):
            s.add(PoScheduleLine(tenant_id=po.tenant_id, po_id=po.id, po_line_id=line.po_line_id, seq=seq, qty=Decimal(1000),
                                 delivery_date=day, received_qty=0, created_by=gr.posted_by))
        s.flush()
        assert supplier_svc.receipt_line_otif(s, gr, po, line) is False  # the first 1,000 were due on 20 Feb


def test_reversed_receipt_is_taken_out_of_the_scorecard():
    with _rolled_back() as s:
        po, gr, line = _gr_and_line(s)
        card = s.execute(select(Scorecard).where(Scorecard.supplier_id == po.supplier_id, Scorecard.period == "2027-02")).scalar_one()
        before = (card.receipts, card.on_time_in_full, card.qty_received)
        assert s.execute(select(TwinFeedback).where(TwinFeedback.metric == "RECEIPT_OTIF", TwinFeedback.source_ref == gr.number)).first()
        event = SimpleNamespace(payload={"grId": str(gr.id)}, topic="goods_receipt.reversed")
        supplier_svc._scorecard_on_reversal(s, event)
        assert (card.receipts, card.on_time_in_full, card.qty_received) == (before[0] - 1, before[1] - 1, before[2] - line.qty)
        supplier_svc._scorecard_on_reversal(s, event)  # idempotent
        assert card.receipts == before[0] - 1
