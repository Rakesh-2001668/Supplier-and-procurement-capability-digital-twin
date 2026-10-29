"""D1 branch cases (seed/datasets/branches.py): every F1–F9 gateway outcome the signature case never produced.

The pack runs once on top of the signature case; objects are looked up by business keys (purpose texts, titles,
supplier invoice numbers), never by numbers from shared ranges. The module fixes the cases exposed are tested here too.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AuditEvent, BankChangeRequest, Budget, BudgetCommitment, Capa, Certificate, Contract, ContractAmendment, ContractLine, ErpDocument,
    GoodsReceipt, InspectionLot, IntegrationMessage, Invoice, InvoiceException, Material, Payment, MaterialRequest, MrpException, MrpRun, Obligation,
    PlannedOrder, PoChangeRequest, PoLine, PoVersion, ProcessInstance, ProcessStep, PurchaseOrder, Qualification, QuotaArrangement,
    Requisition, ReturnDelivery, ServiceEntry, SourcingEvent, Stock, Supplier, SupplierCategoryStatus, SupplierInvitation, Task, Tenant,
    Timer,
)
from app.pic.platform import clock
from app.pic.seed import datasets
from app.pic.seed.axion import at
from app.pic.seed.datasets import branches as pack_module
from tests.pic.conftest import PASSWORD


class _Rollback(Exception):
    pass


def _signature_state():
    """Signature-case objects the pack must not change (earlier tests may have moved them; compare before/after the pack)."""
    with tenant_tx(_tid()) as s:
        invoice = s.execute(select(Invoice).where(Invoice.supplier_invoice_no == "INV-TF-9031")).scalar_one()
        state = {"INV-TF-9031": (invoice.status, invoice.payment_status)}
        for c in s.execute(select(Contract).where(Contract.number.in_(("SA-5520", "SA-5521")))).scalars():
            state[c.number] = (c.status, c.version, c.valid_to)
        for code, category, status in s.execute(select(Supplier.code, SupplierCategoryStatus.category, SupplierCategoryStatus.status).join(
                Supplier, Supplier.id == SupplierCategoryStatus.supplier_id).where(Supplier.code.in_(("TF001", "KD002", "SLA003", "HTS004")))):
            state[f"{code}:{category}"] = status
        state["payments"] = s.execute(select(func.count()).select_from(Payment)).scalar()
        state["dc330Exceptions"] = s.execute(select(func.count()).select_from(MrpException).join(Material, Material.id == MrpException.material_id)
                                             .where(Material.number.in_(("DC-330", "DC-331")))).scalar()
        return state


@pytest.fixture(scope="module")
def pack(database):
    before = _signature_state()
    first = datasets.apply_pack("branches", PASSWORD)
    after = _signature_state()  # immediately after this pack: packs applied later may legitimately move signature objects
    again = datasets.apply_pack("branches", PASSWORD)
    return first, again, (before, after)


def _tid():
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()


def _tx():
    return tenant_tx(_tid())


def _pr(s, purpose_text):
    return s.execute(select(Requisition).where(Requisition.purpose_text == purpose_text)).scalar_one()


def _pos(s, requisition_id, supplier_code=None):
    query = select(PurchaseOrder).join(PoLine, PoLine.po_id == PurchaseOrder.id).where(PoLine.requisition_id == requisition_id)
    if supplier_code:
        query = query.join(Supplier, Supplier.id == PurchaseOrder.supplier_id).where(Supplier.code == supplier_code)
    return s.execute(query.order_by(PurchaseOrder.created_at, PurchaseOrder.number)).scalars().unique().all()


def _tasks(s, object_id, kind):
    return s.execute(select(Task).where(Task.object_id == object_id, Task.kind == kind).order_by(Task.created_at, Task.sequence)).scalars().all()


def _audit(s, object_id, action):
    return s.execute(select(AuditEvent).where(AuditEvent.object_id == object_id, AuditEvent.action == action)).scalars().all()


def _steps(s, business_id):
    instance_ids = [i.id for i in s.execute(select(ProcessInstance).where(ProcessInstance.business_id == business_id)).scalars()]
    return s.execute(select(ProcessStep).where(ProcessStep.instance_id.in_(instance_ids))
                     .order_by(ProcessStep.entered_at, ProcessStep.id)).scalars().all()


def _invoice(s, number):
    return s.execute(select(Invoice).where(Invoice.supplier_invoice_no == number)).scalar_one()


def _supplier(s, code):
    return s.execute(select(Supplier).where(Supplier.code == code)).scalar_one()


def _call_offs(s):
    """The three call-offs against the bridge contract: PO-A (MRP requisition), PO-B (v2) and PO-C from the top-up."""
    mrp_pr = s.execute(select(Requisition).join(PlannedOrder, PlannedOrder.requisition_id == Requisition.id).join(
        Material, Material.id == PlannedOrder.material_id).where(Material.number == "DC-345")).scalar_one()
    po_a = _pos(s, mrp_pr.id)[0]
    po_b, po_c = _pos(s, _pr(s, pack_module.PR_TOPUP).id)
    return mrp_pr, po_a, po_b, po_c


# ---------------------------------------------------------------- pack contract
def test_pack_loads_once_and_reports_every_case(pack):
    first, again, _ = pack
    assert [r["status"] for r in first] == ["LOADED"] and [r["status"] for r in again] == ["ALREADY_LOADED"]
    summary = first[0]["summary"]
    assert all(f"| {case} " in pack_module.__doc__ for case in range(9, 35))  # every case is documented
    assert len(summary["notes"]) >= 24 and summary["counts"]["purchaseOrders"] == 7 and summary["status"]["bridge"] == "EXPIRED"
    with _tx() as s:
        # No task of this pack is left open: every gateway it opened was decided.
        mine = {_pr(s, t).id for t in (pack_module.PR_COOLANT, pack_module.PR_DESKS, pack_module.PR_PPAP, pack_module.PR_THERMAL,
                                       pack_module.PR_ANNUAL, pack_module.PR_TOPUP)}
        assert not s.execute(select(Task.id).where(Task.object_id.in_(mine), Task.status == "OPEN")).first()


# ---------------------------------------------------------------- F2-08 return / reject / re-approval (cases 9, 10)
def test_requisition_returned_resubmitted_and_reapproved_with_budget_rebooked(pack):
    with _tx() as s:
        pr = _pr(s, pack_module.PR_COOLANT)
        assert pr.status == "APPROVED" and pr.total_minor == 720 * 25_200
        decisions = [(t.candidate_role, t.decision) for t in _tasks(s, pr.id, "REQ_APPROVAL")]
        assert decisions == [("COST_OBJECT_OWNER", "RETURN"), ("COST_OBJECT_OWNER", "APPROVE"), ("COST_OBJECT_OWNER", "APPROVE")]
        assert [a.action for a in s.execute(select(AuditEvent).where(AuditEvent.object_id == pr.id, AuditEvent.action.in_(
            ("RETURN", "SUBMIT", "REAPPROVE"))).order_by(AuditEvent.seq)).scalars()] == ["SUBMIT", "RETURN", "SUBMIT", "REAPPROVE"]
        commitments = s.execute(select(BudgetCommitment).where(BudgetCommitment.object_id == pr.id).order_by(BudgetCommitment.created_at)).scalars().all()
        assert [(c.status, c.amount_minor) for c in commitments] == [("RELEASED", 1200 * 24_500), ("RELEASED", 600 * 25_200), ("OPEN", 720 * 25_200)]
        assert pr.budget_result["rebookedOnChange"] is True and pr.budget_result["outcome"] == "OK"
        budget = s.execute(select(Budget).where(Budget.cost_object_code == "4100", Budget.fiscal_year == "2027-28")).scalar_one()
        assert budget.committed_minor >= 720 * 25_200


def test_requisition_rejected_by_second_approver_releases_budget(pack):
    with _tx() as s:
        pr = _pr(s, pack_module.PR_DESKS)
        assert pr.status == "REJECTED"
        assert [(t.candidate_role, t.decision) for t in _tasks(s, pr.id, "REQ_APPROVAL")] == [("COST_OBJECT_OWNER", "APPROVE"), ("DEPT_HEAD", "REJECT")]
        assert [c.status for c in s.execute(select(BudgetCommitment).where(BudgetCommitment.object_id == pr.id)).scalars()] == ["RELEASED"]
        assert any(st.step_id == "F2-09" and st.outcome.startswith("rejected") for st in _steps(s, pr.id))


# ---------------------------------------------------------------- F1 MRP (cases 11–14)
def test_mrp_simulation_past_due_reschedule_out_and_in(pack):
    with _tx() as s:
        material = s.execute(select(Material).where(Material.number == "DC-345")).scalar_one()
        runs = [r for r in s.execute(select(MrpRun).order_by(MrpRun.run_date, MrpRun.number)).scalars() if r.scope.get("materials") == ["DC-345"]]
        assert [r.mode for r in runs] == ["SIMULATION", "NET_CHANGE", "NET_CHANGE", "NET_CHANGE"]
        simulation, run1, run2, run3 = runs
        assert simulation.status == "SIMULATED" and simulation.planned_orders_created == 0
        assert not s.execute(select(PlannedOrder.id).where(PlannedOrder.mrp_run_id == simulation.id)).first()
        assert any(st.step_id == "F1-05" and st.outcome.startswith("simulation") for st in _steps(s, simulation.id))

        def codes(run):
            return sorted(e.code for e in s.execute(select(MrpException).where(MrpException.mrp_run_id == run.id)).scalars())
        assert "PAST_DUE" in codes(run1) and codes(run2) == ["RESCHEDULE_OUT"] and codes(run3) == ["RESCHEDULE_IN"]
        statuses = {o.need_date: o.status for o in s.execute(select(PlannedOrder).where(PlannedOrder.mrp_run_id == run1.id)).scalars()}
        assert statuses == {date(2027, 4, 9): "CONVERTED", date(2027, 5, 17): "FIRMED", date(2027, 6, 14): "DELETED"}
        firmed = s.execute(select(PlannedOrder).where(PlannedOrder.mrp_run_id == run1.id, PlannedOrder.status == "FIRMED")).scalar_one()
        assert firmed.number in run2.results[0]["exceptions"][0]["message"] and firmed.number in run3.results[0]["exceptions"][0]["message"]
        # The run after the annual SA went live sources the June proposal from its quota.
        assert {o.source["method"] for o in s.execute(select(PlannedOrder).where(PlannedOrder.mrp_run_id == run3.id)).scalars()} == {"NONE", "QUOTA"}
        assert s.execute(select(func.count()).select_from(PlannedOrder).where(PlannedOrder.mrp_run_id == run2.id,
                                                                              PlannedOrder.status == "DELETED")).scalar() == 1
        unrestricted = s.execute(select(func.sum(Stock.qty)).where(Stock.material_id == material.id, Stock.stock_type == "UNRESTRICTED")).scalar()
        quality_or_blocked = s.execute(select(func.sum(Stock.qty)).where(Stock.material_id == material.id,
                                                                         Stock.stock_type.in_(("QUALITY", "BLOCKED")))).scalar()
        assert unrestricted == Decimal(1200) and quality_or_blocked == 0  # 300 opening + 800 (PO-A) + 100 (PO-C)


def test_needed_on_drives_reschedule_out_and_cancel():
    from types import SimpleNamespace

    from app.pic.services.planning import _needed_on
    order = SimpleNamespace(qty=Decimal(500), need_date=date(2027, 5, 1))
    gross = {date(2027, 6, 1): Decimal(400)}
    receipts = {date(2027, 5, 1): Decimal(500)}
    assert _needed_on(Decimal(450), gross, receipts, order, Decimal(100)) == date(2027, 6, 1)   # out: needed a month later
    assert _needed_on(Decimal(600), gross, receipts, order, Decimal(100)) is None                # cancel: covered without it
    assert _needed_on(Decimal(0), {date(2027, 4, 20): Decimal(10)}, receipts, order, Decimal(0)) == date(2027, 4, 20)


# ---------------------------------------------------------------- F8 (cases 15, 16, 33)
def test_self_registered_supplier_rejected_at_qualification(pack):
    with _tx() as s:
        vht = s.execute(select(Supplier).where(Supplier.legal_name == pack_module.VHT["legal_name"])).scalar_one()
        invitation = s.execute(select(SupplierInvitation).where(SupplierInvitation.email == pack_module.VHT["email"])).scalar_one()
        assert invitation.status == "REGISTERED" and invitation.supplier_id == vht.id
        q = s.execute(select(Qualification).where(Qualification.supplier_id == vht.id)).scalar_one()
        assert (q.status, q.decision, q.audit_score) == ("DECIDED", "REJECTED", Decimal(58))
        assert s.execute(select(SupplierCategoryStatus.status).where(SupplierCategoryStatus.supplier_id == vht.id)).scalar_one() == "EXITED"
        assert vht.status == "REGISTERED"  # never activated, never synced to the ERP
        steps = _steps(s, vht.id)
        assert any(st.step_id == "F8-06" and st.outcome.startswith("rejected") for st in steps)
        assert not any(st.step_id == "F8-07" for st in steps)


def test_certificate_expiry_downgrades_to_conditional(pack):
    with _tx() as s:
        aac = _supplier(s, "AAC202")
        cert = s.execute(select(Certificate).where(Certificate.supplier_id == aac.id, Certificate.type == "ISO14001")).scalar_one()
        assert cert.status == "EXPIRED" and cert.expires_on == date(2027, 4, 15)
        status = s.execute(select(SupplierCategoryStatus).where(SupplierCategoryStatus.supplier_id == aac.id,
                                                                SupplierCategoryStatus.category == "ALU-DIECAST")).scalar_one()
        assert status.status == "CONDITIONAL" and _audit(s, aac.id, "CERTIFICATE_EXPIRED")
        timer = s.execute(select(Timer).where(Timer.object_id == cert.id, Timer.kind == "CERTIFICATE_EXPIRY")).scalar_one()
        assert timer.due_at == clock.at_ist(date(2027, 4, 16), 0, 5)  # the day after the certificate's last valid day
        spd_cert = s.execute(select(Certificate).join(Supplier, Supplier.id == Certificate.supplier_id).where(
            Supplier.code == "SPD201", Certificate.type == "ISO14001")).scalar_one()
        assert spd_cert.status == "VALID"


def test_expiry_timer_fired_on_the_expiry_day_rearms_instead_of_skipping(pack):
    from app.pic.platform import workflow
    from app.pic.worker import system_principal
    tenant_id = _tid()
    p = system_principal(tenant_id)
    with pytest.raises(_Rollback):
        with tenant_tx(tenant_id, p.user_id, p) as s:
            cert = s.execute(select(Certificate).where(Certificate.number == "QMS-VHT-0110")).scalar_one()
            clock.set_pinned(clock.at_ist(cert.expires_on, 0, 5))
            try:
                due = clock.at_ist(cert.expires_on + timedelta(days=1), 0, 5)

                def armed():
                    return len(s.execute(select(Timer).where(Timer.object_id == cert.id, Timer.fired_at.is_(None), Timer.due_at == due)).scalars().all())
                before = armed()
                early = Timer(tenant_id=tenant_id, kind="CERTIFICATE_EXPIRY", object_type="CERTIFICATE", object_id=cert.id,
                              due_at=clock.at_ist(cert.expires_on, 0, 5), payload={}, fired_at=clock.now())
                s.add(early)
                s.flush()
                workflow._timer_handlers["CERTIFICATE_EXPIRY"](s, early)
                s.flush()
                assert cert.status == "VALID"
                assert armed() == before + 1
            finally:
                clock.set_pinned(None)
            raise _Rollback()


def test_bank_change_rejected_by_finance_keeps_existing_account(pack):
    with _tx() as s:
        aac = _supplier(s, "AAC202")
        changes = s.execute(select(BankChangeRequest).where(BankChangeRequest.supplier_id == aac.id).order_by(BankChangeRequest.created_at)).scalars().all()
        assert [c.status for c in changes] == ["APPROVED", "REJECTED"]
        assert [(t.candidate_role, t.decision) for t in _tasks(s, changes[1].id, "BANK_CHANGE")] == [("FINANCE_CONTROLLER", "REJECT")]
        assert _audit(s, aac.id, "BANK_CHANGE_REJECTED")


# ---------------------------------------------------------------- F9 (cases 17–19)
def test_material_request_rejected_warned_and_overridden(pack):
    with _tx() as s:
        oil = s.execute(select(MaterialRequest).where(MaterialRequest.description == pack_module.MRQ_OIL)).scalar_one()
        assert oil.status == "REJECTED" and oil.material_id is None
        assert sorted((t.status, t.decision or "") for t in _tasks(s, oil.id, "MDM_STEWARD")) == [
            ("CANCELLED", ""), ("CANCELLED", ""), ("COMPLETED", "APPROVE"), ("COMPLETED", "REJECT")]
        warn = s.execute(select(MaterialRequest).where(MaterialRequest.description == pack_module.MRQ_WARN)).scalar_one()
        assert Decimal("0.75") <= warn.duplicate_score < Decimal("0.92") and warn.status == "SYNCED_TO_ERP"
        block = s.execute(select(MaterialRequest).where(MaterialRequest.description == pack_module.MRQ_BLOCK)).scalar_one()
        assert block.duplicate_score >= Decimal("0.92") and block.override_reason and block.status == "SYNCED_TO_ERP"
        assert _audit(s, block.id, "DUPLICATE_BLOCKED") and _audit(s, block.id, "DUPLICATE_OVERRIDE")
        assert s.get(Material, block.material_id).valuation_class == "7920"


# ---------------------------------------------------------------- F3 / F4 (cases 20–24)
def test_sourcing_award_below_band_to_lowest_needs_no_approval(pack):
    with _tx() as s:
        event = s.execute(select(SourcingEvent).where(SourcingEvent.title == pack_module.RFQ_TITLE)).scalar_one()
        assert event.status == "AWARDED" and event.round == 1
        assert _tasks(s, event.id, "AWARD_APPROVAL") == []
        outcomes = {st.step_id: st.outcome for st in _steps(s, event.id)}
        assert outcomes["F3-05"] == "no further round" and outcomes["F3-07"].startswith("no:") and "F3-08" not in outcomes
        sa = s.execute(select(Contract).where(Contract.source_event_id == event.id)).scalar_one()
        assert sa.status == "ACTIVE" and sa.target_value_minor < 100 * 100_000 * 100
        assert [(t.candidate_role, t.decision) for t in _tasks(s, sa.id, "CONTRACT_APPROVAL")] == [("CONTRACT_MANAGER", "APPROVE")]
        assert s.execute(select(QuotaArrangement).where(QuotaArrangement.source_event_id == event.id)).scalar_one().valid_from == date(2027, 5, 1)


def test_bridge_contract_rejected_consumed_renewal_declined_and_expired(pack):
    with _tx() as s:
        bridge = s.execute(select(Contract).where(Contract.title == pack_module.BRIDGE)).scalar_one()
        assert bridge.status == "EXPIRED" and bridge.thresholds_hit == [80, 90, 100]
        assert [(t.candidate_role, t.decision) for t in _tasks(s, bridge.id, "CONTRACT_APPROVAL")] == [
            ("CONTRACT_MANAGER", "REJECT"), ("CONTRACT_MANAGER", "APPROVE")]
        assert [t.decision for t in _tasks(s, bridge.id, "CONTRACT_RENEWAL")] == ["REJECT"]
        assert _audit(s, bridge.id, "CLAUSE_REDLINED")
        steps = _steps(s, bridge.id)
        assert [st.outcome[:2] for st in steps if st.step_id == "F4-05"] == ["no", "no"]
        assert steps[-1].step_id == "F4-10" and steps[-1].outcome.startswith("expired")
        line = s.execute(select(ContractLine).where(ContractLine.contract_id == bridge.id)).scalar_one()
        # The 80/90/100 % alerts fired on release; PO-B's lot was rejected in full, returned and the order closed, so
        # consumption is recomputed to what was delivered (contract.recompute_consumption): 800 + 0 + 100 of 1,000.
        assert line.target_qty == Decimal(1000) and line.released_qty == Decimal(900)


def test_value_contract_renewal_approved_extends_to_next_year(pack):
    with _tx() as s:
        amc = s.execute(select(Contract).where(Contract.title == pack_module.AMC)).scalar_one()
        assert (amc.status, amc.version, amc.valid_to) == ("ACTIVE", 2, date(2028, 7, 31))
        assert [t.decision for t in _tasks(s, amc.id, "CONTRACT_RENEWAL")] == ["APPROVE"]
        extension = s.execute(select(ContractAmendment).where(ContractAmendment.contract_id == amc.id)).scalar_one()
        assert (extension.kind, extension.status) == ("EXTENSION", "EFFECTIVE")
        assert any(o.status == "DONE" for o in s.execute(select(Obligation).where(Obligation.contract_id == amc.id)).scalars())


# ---------------------------------------------------------------- F5 (cases 25, 26, 32, 34)
def test_supplier_rejected_po_is_cancelled_and_resourced(pack):
    with _tx() as s:
        pr = _pr(s, pack_module.PR_PPAP)
        po_d = _pos(s, pr.id, "AAC202")[0]
        po_e = _pos(s, pr.id, "SPD201")[0]
        assert po_d.status == "CANCELLED" and po_e.status == "CLOSED" and pr.status == "CLOSED"
        assert [t.decision for t in _tasks(s, po_d.id, "PO_CHANGE_REVIEW")] == ["REJECT"]
        assert _audit(s, po_d.id, "SUPPLIER_CHANGE_DECLINED") and _audit(s, po_d.id, "ERP_CANCELLED")
        cancel = s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == f"1000|PO|{po_d.number}|CANCEL")).scalar_one()
        assert cancel.status == "POSTED" and cancel.erp_doc_no != po_d.erp_doc_no
        assert s.execute(select(ProcessInstance.status).where(ProcessInstance.business_id == po_d.id)).scalar_one() == "CANCELLED"
        # PO-E missed the 24 h confirmation SLA → Expediting agent draft and a buyer task.
        assert [t.decision for t in _tasks(s, po_e.id, "EXPEDITE")] == ["APPROVE"]


def test_po_approval_rejected_then_cancelled_from_draft(pack):
    with _tx() as s:
        pr = _pr(s, pack_module.PR_THERMAL)
        rejected, approved = _pos(s, pr.id)
        assert rejected.status == "CANCELLED" and [t.decision for t in _tasks(s, rejected.id, "PO_APPROVAL")] == ["REJECT"]
        assert _audit(s, rejected.id, "REJECT") and approved.status == "CONFIRMED"
        assert rejected.erp_doc_no is None  # never released, so nothing went to the ERP


def test_changes_outside_tolerance_accepted_and_declined(pack):
    with _tx() as s:
        _, _, po_b, po_c = _call_offs(s)
        assert po_b.version == 2 and po_c.version == 1
        assert [t.decision for t in _tasks(s, po_b.id, "PO_CHANGE_REVIEW")] == ["APPROVE"]
        assert [t.decision for t in _tasks(s, po_c.id, "PO_CHANGE_REVIEW")] == ["REJECT"]
        assert s.execute(select(PoVersion).where(PoVersion.po_id == po_b.id)).scalar_one().change_reason.startswith("supplier proposal accepted")
        assert _audit(s, po_c.id, "SUPPLIER_CHANGE_DECLINED")
        assert s.execute(select(PoLine.unit_price_minor).where(PoLine.po_id == po_c.id)).scalar_one() == 18_600
        pcr = s.execute(select(PoChangeRequest).where(PoChangeRequest.po_id == po_c.id)).scalar_one()
        assert pcr.status == "REJECTED" and pcr.origin == "SUPPLIER"
        assert [s_.outcome[:2] for s_ in _steps(s, po_b.id) if s_.step_id == "F5-08"] == ["no", "ye"]


# ---------------------------------------------------------------- F6 (cases 27–29)
def test_wrong_goods_receipt_reversed_and_reposted(pack):
    with _tx() as s:
        _, _, po_b, po_c = _call_offs(s)
        receipts_b = s.execute(select(GoodsReceipt).where(GoodsReceipt.po_id == po_b.id).order_by(GoodsReceipt.created_at)).scalars().all()
        wrong, real = receipts_b
        assert wrong.status == "REVERSED" and wrong.delivery_note == "DN-SPD-1190"
        lot = s.execute(select(InspectionLot).where(InspectionLot.gr_id == wrong.id)).scalar_one()
        assert (lot.status, lot.usage_decision) == ("CANCELLED", "REVERSED")
        completed = _audit(s, wrong.id, "REVERSAL_COMPLETED")[0]
        assert completed.after["poStatus"] == "CONFIRMED" and completed.after["erpReversal"] is None  # quality stock never reached the ERP
        assert s.execute(select(ProcessInstance.status).where(ProcessInstance.business_id == wrong.id)).scalar_one() == "CANCELLED"
        gr_c = s.execute(select(GoodsReceipt).where(GoodsReceipt.po_id == po_c.id)).scalar_one()
        assert gr_c.delivery_note == "DN-SPD-1190" and gr_c.status == "ACCEPTED"
        assert real.status == "REJECTED"


def test_lot_rejected_in_full_returns_goods_and_closes_capa(pack):
    with _tx() as s:
        _, _, po_b, _ = _call_offs(s)
        gr = s.execute(select(GoodsReceipt).where(GoodsReceipt.po_id == po_b.id, GoodsReceipt.status == "REJECTED")).scalar_one()
        lot = s.execute(select(InspectionLot).where(InspectionLot.gr_id == gr.id)).scalar_one()
        assert (lot.usage_decision, lot.accepted_qty, lot.rejected_qty, lot.defect_code) == ("REJECTED", 0, 100, "COLD_SHUT")
        assert s.execute(select(ReturnDelivery.qty).where(ReturnDelivery.gr_id == gr.id)).scalar_one() == 100
        capa = s.execute(select(Capa).where(Capa.source_ref == lot.number)).scalar_one()
        assert capa.status == "CLOSED" and capa.root_cause and capa.closed_at is not None
        assert po_b.status == "CLOSED"


def test_service_entry_rejected_then_corrected(pack):
    with _tx() as s:
        po = _pos(s, _pr(s, pack_module.PR_THERMAL).id)[-1]
        entries = s.execute(select(ServiceEntry).where(ServiceEntry.po_id == po.id).order_by(ServiceEntry.created_at)).scalars().all()
        assert [e.status for e in entries] == ["REJECTED", "APPROVED"]
        assert [t.decision for t in _tasks(s, entries[0].id, "SES_APPROVAL")] == ["REJECT"]
        assert s.execute(select(PoLine.ses_approved_minor).where(PoLine.po_id == po.id)).scalar_one() == 4_200_000


# ---------------------------------------------------------------- F7 (cases 30, 31)
def test_erp_timeout_retry_dead_letter_and_replay(pack):
    with _tx() as s:
        mrp_pr, po_a, _, _ = _call_offs(s)
        assert po_a.touchless and po_a.status == "CLOSED" and mrp_pr.status == "CLOSED"
        invoice = _invoice(s, "SPD/27-28/0012")
        assert invoice.status == "POSTED" and invoice.erp_doc_no
        assert _audit(s, invoice.id, "INTEGRATION_DEAD_LETTER")[0].after == {"attempts": 8}
        assert _audit(s, invoice.id, "INTEGRATION_REPLAY")
        assert s.execute(select(func.count()).select_from(ErpDocument).where(
            ErpDocument.external_ref == "AXN|1000|SPD201|SPD/27-28/0012")).scalar() == 1
        gr = s.execute(select(GoodsReceipt).where(GoodsReceipt.po_id == po_a.id)).scalar_one()
        message = s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == f"GR|{gr.number}")).scalar_one()
        assert (message.status, message.attempts) == ("POSTED", 2)


def test_price_dispute_and_irn_mismatch(pack):
    with _tx() as s:
        disputed = _invoice(s, "SPD/27-28/0019")
        assert disputed.status == "REJECTED"
        assert _audit(s, disputed.id, "EXCEPTION_DISPUTED") and not _audit(s, disputed.id, "EXCEPTION_RESOLVED")
        price = s.execute(select(InvoiceException).where(InvoiceException.invoice_id == disputed.id, InvoiceException.type == "PRICE")).scalar_one()
        assert (price.status, price.resolution) == ("RESOLVED", "REJECTED")  # open while disputed, closed with the rejection
        assert _invoice(s, "SPD/27-28/0021").status == "POSTED"
        bad = _invoice(s, "SPD/27-28/0017")
        assert bad.status == "REJECTED" and bad.irn_valid is False
        assert s.execute(select(InvoiceException.type).where(InvoiceException.invoice_id == bad.id)).scalars().all() == ["TAX"]
        assert _invoice(s, "SPD/27-28/0018").status == "POSTED"


def test_dispute_keeps_the_exception_open_until_resolved(pack):
    """Unit check of the payables fix on a fresh PRICE exception (rolled back)."""
    from app.pic.services import payables
    tenant_id = _tid()
    with pytest.raises(_Rollback):
        with tenant_tx(tenant_id) as s:
            clock.set_pinned(at(date(2027, 4, 15), 15))
            try:
                invoice = _invoice(s, "SPD/27-28/0019")
                exc = s.execute(select(InvoiceException).where(InvoiceException.invoice_id == invoice.id)).scalar_one()
                exc.status, exc.resolution = "OPEN", None  # back to the moment before the dispute (rolled back)
                invoice.status = "EXCEPTION"
                _principal_for(s, "ap.clerk@axion.example")
                result = payables.resolve_exception(s, invoice, exc.id, "DISPUTE", "Surcharge not agreed")
                assert result["dispute"] is True and exc.status == "OPEN" and exc.resolution == "DISPUTE"
                assert invoice.payment_block is True
            finally:
                clock.set_pinned(None)
            raise _Rollback()


def _principal_for(s, email):
    from app.pic.models import AppUser
    from app.pic.platform.auth import Principal, scopes_for
    user = s.execute(select(AppUser).where(AppUser.email == email)).scalar_one()
    s.info["principal"] = Principal(user_id=user.id, tenant_id=user.tenant_id, tenant_code="AXN", email=user.email, name=user.full_name,
                                    roles=list(user.roles), scopes=scopes_for(list(user.roles)), attributes=user.attributes or {},
                                    supplier_id=user.supplier_id)
    s.info["user_id"] = user.id


def test_cancelling_a_contract_call_off_gives_back_consumption(pack):
    """order.cancel reverses contract consumption booked at release (rolled back)."""
    from app.pic.services import contract as contract_svc, order
    tenant_id = _tid()
    with pytest.raises(_Rollback):
        with tenant_tx(tenant_id) as s:
            clock.set_pinned(at(date(2027, 4, 20), 10))
            try:
                _, _, _, po_c = _call_offs(s)
                line = s.execute(select(PoLine).where(PoLine.po_id == po_c.id)).scalar_one()
                contract_line = s.get(ContractLine, line.contract_line_id)
                before = contract_line.released_qty
                po_c.status = "TRANSMITTED"  # pretend nothing was shipped yet (rolled back)
                for field in ("shipped_qty", "received_qty", "accepted_qty", "invoiced_qty"):
                    setattr(line, field, Decimal(0))
                line.invoiced_minor = 0
                _principal_for(s, "buyer@axion.example")
                order.cancel(s, po_c, "Test: call-off withdrawn")
                # Consumption is recomputed from the live PO lines by the consumer (contract.recompute_consumption):
                # a release event relayed after the cancellation consumes nothing.
                event = type("E", (), {"object_id": po_c.id})()
                contract_svc._consume(s, event)
                assert contract_line.released_qty == before - line.qty
            finally:
                clock.set_pinned(None)
            raise _Rollback()


# ---------------------------------------------------------------- signature case untouched
def test_signature_case_objects_unchanged(pack):
    # The pack runs no payment run (INV-TF-9031 falls due on 14 Apr 2027), fires no foreign timers and plans only DC-345.
    before, after = pack[2]
    assert after == before


# ---------------------------------------------------------------- API for the new PO commands (runs last: it closes PO-C)
def test_po_cancel_and_close_endpoints(pack, client, login):
    with _tx() as s:
        _, po_a, _, po_c = _call_offs(s)
        topup = _pr(s, pack_module.PR_TOPUP)
        po_a_no, po_c_no, topup_id = po_a.number, po_c.number, topup.id
    clock.set_pinned(at(date(2027, 4, 28), 10))
    try:
        buyer = login("buyer")
        assert client.post(f"/v1/purchase-orders/{po_c_no}/close", json={"reason": "x"}, headers=buyer).status_code == 422
        assert client.post(f"/v1/purchase-orders/{po_c_no}/close", json={"reason": "Paid in full"}, headers=login("spd.sales")).status_code == 403
        r = client.post(f"/v1/purchase-orders/{po_a_no}/cancel", json={"reason": "Too late to cancel"}, headers=buyer)
        assert r.status_code == 409 and r.json()["code"] == "ILLEGAL_TRANSITION"
        r = client.post(f"/v1/purchase-orders/{po_c_no}/close", json={"reason": "Invoiced in full (SPD/27-28/0021)"}, headers=buyer)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "CLOSED" and r.json()["from"] == "INVOICED" and len(r.json()["closedRequisitions"]) == 1
    finally:
        clock.set_pinned(None)
    with _tx() as s:
        assert s.get(Requisition, topup_id).status == "CLOSED"
