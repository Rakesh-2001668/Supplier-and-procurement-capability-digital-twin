"""Dataset pack module_cases (AXN, May 2027): operations-module cases created through the services.

Objects are looked up by business keys the pack controls (contract titles, supplier names/codes, supplier invoice numbers,
batch references), never by numbers from shared ranges.
"""
import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    Asn, AuctionBid, AuditEvent, Contract, ContractAmendment, CreditNote, IntegrationBatch, IntegrationMessage, Invoice, Notification, PaymentFile,
    PlannedOrder, PoScheduleLine, PoTransmission, PurchaseOrder, Recommendation, ReconciliationItem, ReconciliationRun, Requisition,
    SourcingClarification, SourcingEvent, Supplier, SupplierCategoryStatus, SupplierInvitation, SupplierMasterChange, Task, Tenant,
)
from app.pic.seed import datasets
from tests.pic.conftest import PASSWORD


@pytest.fixture(scope="module")
def pack(database):
    result = datasets.apply_pack("module_cases", PASSWORD)
    assert result[0]["status"] == "LOADED", result
    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()
    return {"tenant": tenant_id, "summary": result[0]["summary"]}


def _contract(s, title: str) -> Contract:
    return s.execute(select(Contract).where(Contract.title == title)).scalar_one()


def _amendments(s, contract: Contract) -> list[ContractAmendment]:
    return s.execute(select(ContractAmendment).where(ContractAmendment.contract_id == contract.id)
                     .order_by(ContractAmendment.created_at)).scalars().all()


def test_contract_amendments_extension_renewal_and_termination(pack):
    with tenant_tx(pack["tenant"]) as s:
        c1 = _contract(s, "DC-340 motor end shields FY27-28")
        below, above = _amendments(s, c1)
        assert (below.kind, below.status, below.changes["band"], below.changes["approvalChain"]) == \
            ("VARIATION", "EFFECTIVE", "below", ["CONTRACT_MANAGER"])
        approver = s.execute(select(Task).where(Task.kind == "CONTRACT_AMENDMENT", Task.evidence["amendmentId"].astext == str(below.id))
                             ).scalar_one()
        assert approver.completed_by != below.requested_by and approver.status == "COMPLETED"
        assert (above.changes["band"], above.changes["approvalChain"], above.status) == ("above", ["LEGAL", "FINANCE_CONTROLLER"], "EFFECTIVE")
        assert c1.version == 3 and c1.status == "ACTIVE"

        c2 = _contract(s, "DC-345 inverter housings – interim agreement")
        [ext] = _amendments(s, c2)
        assert ext.kind == "EXTENSION" and ext.status == "EFFECTIVE" and ext.reason.startswith("Renewal approved")
        assert c2.status == "ACTIVE" and c2.valid_to.isoformat() == "2028-09-15"
        # The renewal draft (dated on the renewal decision, 18 May) was submitted a day later: re-dated instead of refused as back-dated.
        redated = s.execute(select(AuditEvent).where(AuditEvent.object_id == c2.id, AuditEvent.action == "AMENDMENT_REDATED")).scalar_one()
        assert redated.before["effectiveFrom"] == "2027-05-18" and redated.after["effectiveFrom"] == "2027-05-19"

        c4 = _contract(s, "HPDC die-cell preventive maintenance rate contract")
        [ext4] = _amendments(s, c4)
        assert (ext4.kind, ext4.status, ext4.changes["approvalChain"]) == ("EXTENSION", "EFFECTIVE", ["CONTRACT_MANAGER"])
        assert c4.valid_to.isoformat() == "2028-03-31"

        c3 = _contract(s, "DC-348 mounting brackets FY27-28")
        [term] = _amendments(s, c3)
        assert (term.kind, term.status, term.changes["forCause"], term.changes["approvalChain"]) == \
            ("TERMINATION", "EFFECTIVE", False, ["LEGAL", "CPO"])
        assert c3.status == "TERMINATED" and term.effective_from.isoformat() == "2027-08-31"
        po = s.execute(select(PurchaseOrder).where(PurchaseOrder.contract_id == c3.id)).scalar_one()
        review = s.execute(select(Task).where(Task.object_id == po.id, Task.kind == "TERMINATED_CONTRACT_REVIEW")).scalar_one()
        assert review.status == "OPEN" and review.evidence["contract"] == c3.number
    assert pack["summary"]["keys"]["esign"].startswith("needs supply: ESIGN_NOT_CONFIGURED")


def test_clarifications_auction_soft_close_and_award_draft(pack):
    with tenant_tx(pack["tenant"]) as s:
        event = s.execute(select(SourcingEvent).where(SourcingEvent.title == "DC-350 sensor cover – reverse auction FY27-28")).scalar_one()
        items = s.execute(select(SourcingClarification).where(SourcingClarification.event_id == event.id)
                          .order_by(SourcingClarification.seq)).scalars().all()
        assert sorted(i.status for i in items) == ["ANSWERED", "ANSWERED", "ANSWERED", "WITHDRAWN"]
        assert sum(1 for i in items if i.asked_by_supplier_id is None) == 1  # the buyer notice
        bids = s.execute(select(AuctionBid).where(AuctionBid.event_id == event.id)).scalars().all()
        assert len(bids) == 8 and sum(1 for b in bids if b.extended_close) == 2
        assert event.status == "AWARDED"
        [draft] = s.execute(select(Contract).where(Contract.source_event_id == event.id)).scalars().all()
        supplier = s.get(Supplier, draft.supplier_id)
        assert (draft.status, draft.type, supplier.code) == ("DRAFT", "SCHEDULING_AGREEMENT", "APC007")
        rejected = s.execute(select(Recommendation).where(Recommendation.agent_code == "SOURCING_STRATEGY",
                                                          Recommendation.status == "REJECTED", Recommendation.feedback_comment.like("%reverse auction%"))
                             ).scalars().all()
        accepted = s.execute(select(Recommendation).where(Recommendation.agent_code == "SOURCING_STRATEGY", Recommendation.status == "ACCEPTED",
                                                          Recommendation.feedback_comment.like("Accepted:%"))).scalars().all()
        assert len(rejected) == 1 and len(accepted) == 1


def _po(s) -> PurchaseOrder:
    invoice = s.execute(select(Invoice).where(Invoice.supplier_invoice_no == "APC/27-28/0142")).scalar_one()
    return s.get(PurchaseOrder, invoice.po_id)


def test_order_to_pay_schedule_edi_eway_four_way(pack):
    with tenant_tx(pack["tenant"]) as s:
        po = _po(s)
        assert po.version == 2 and po.status in ("PARTIALLY_RECEIVED", "CONFIRMED")
        schedule = s.execute(select(PoScheduleLine).where(PoScheduleLine.po_id == po.id).order_by(PoScheduleLine.delivery_date)).scalars().all()
        assert [(str(int(x.qty)), str(int(x.received_qty))) for x in schedule] == [("2000", "2000"), ("1200", "1200"), ("800", "0")]
        tx = {(t.po_version, t.channel): t for t in s.execute(select(PoTransmission).where(PoTransmission.po_id == po.id)).scalars()}
        assert tx[(1, "EDI")].format == "EDIFACT_ORDERS" and tx[(1, "EDI")].status == "ACKNOWLEDGED"   # ORDRSP acknowledged it
        assert tx[(2, "EDI")].format == "EDIFACT_ORDCHG" and tx[(2, "EDI")].status == "QUEUED"
        assert tx[(2, "EMAIL")].status == "QUEUED" and tx[(2, "PORTAL")].status == "ACKNOWLEDGED"
        asns = s.execute(select(Asn).where(Asn.po_id == po.id).order_by(Asn.ship_date)).scalars().all()
        assert [a.eway_bill_no for a in asns] == ["331100458921", "331100512276"]
        assert asns[0].documents == ["DESADV APC-DES-2705-11"] and asns[1].vehicle_no == "TN05BX4821"
        inv1 = s.execute(select(Invoice).where(Invoice.supplier_invoice_no == "APC/27-28/0142")).scalar_one()
        inv2 = s.execute(select(Invoice).where(Invoice.supplier_invoice_no == "APC/27-28/0171")).scalar_one()
        assert inv1.match_type == "4WAY" and inv1.first_pass_matched is False and inv1.irn_valid is True
        assert inv2.match_type == "4WAY" and inv2.first_pass_matched is True and inv2.status == "POSTED"


def test_credit_memo_reconciliation_payment_files(pack):
    with tenant_tx(pack["tenant"]) as s:
        inv1 = s.execute(select(Invoice).where(Invoice.supplier_invoice_no == "APC/27-28/0142")).scalar_one()
        note = s.execute(select(CreditNote).where(CreditNote.invoice_id == inv1.id)).scalar_one()
        memo = s.execute(select(IntegrationMessage).where(IntegrationMessage.message_type == "SUPPLIER_CREDIT_MEMO",
                                                          IntegrationMessage.object_id == inv1.id)).scalar_one()
        assert memo.status == "POSTED" and memo.idempotency_key.endswith(f"|CN|{note.number}") and memo.payload["grossMinor"] == note.gross_minor
        rec1, rec2 = pack["summary"]["keys"]["reconciliation"]
        item = s.execute(select(ReconciliationItem).join(ReconciliationRun, ReconciliationRun.id == ReconciliationItem.run_id)
                         .where(ReconciliationRun.number == rec1, ReconciliationItem.object_ref == inv1.number)).scalar_one()
        assert item.kind == "AMOUNT_MISMATCH" and item.status == "RESOLVED" and item.platform_minor == inv1.gross_minor - note.gross_minor
        assert item.erp_minor == inv1.gross_minor
        again = s.execute(select(ReconciliationItem).join(ReconciliationRun, ReconciliationRun.id == ReconciliationItem.run_id)
                          .where(ReconciliationRun.number == rec2, ReconciliationItem.object_ref == inv1.number)).first()
        assert again is None  # the posted credit memo closes the difference
        assert inv1.status == "PAID"
        files = {f.format: f for f in s.execute(select(PaymentFile).where(PaymentFile.run_ref == pack["summary"]["keys"]["paymentRun"])).scalars()}
        assert files["ISO20022_PAIN001"].status == "REJECTED"
        assert files["NEFT_CSV"].status == "ACKNOWLEDGED" and files["NEFT_CSV"].bank_ref == "AXIS-NEFT-270528-0417"


def test_masters_invitation_punchout_and_category_budget(pack):
    with tenant_tx(pack["tenant"]) as s:
        invitation = s.execute(select(SupplierInvitation).where(SupplierInvitation.email == "onboarding@krishnagiri-packaging.example")).scalar_one()
        krp = s.get(Supplier, invitation.supplier_id)
        assert invitation.status == "REGISTERED" and krp.status == "ACTIVE" and krp.state_code == "29"
        status = s.execute(select(SupplierCategoryStatus.status).where(SupplierCategoryStatus.supplier_id == krp.id,
                                                                       SupplierCategoryStatus.category == "PACKAGING")).scalar_one()
        assert status == "QUALIFIED"
        apc = s.execute(select(Supplier).where(Supplier.code == "APC007")).scalar_one()
        changes = {(c.supplier_id, c.field_group): c for c in s.execute(select(SupplierMasterChange).where(
            SupplierMasterChange.supplier_id.in_([krp.id, apc.id]))).scalars()}
        assert changes[(krp.id, "TAX")].status == "APPLIED"
        assert changes[(apc.id, "ADDRESS")].status == "REJECTED" and apc.address["pin"] == "600058"
        assert changes[(apc.id, "CONTACT")].status == "APPLIED" and apc.contact_email == "ar@ambattur-castings.example"
        pr = s.execute(select(Requisition).where(Requisition.number == pack["summary"]["keys"]["punchoutRequisition"])).scalar_one()
        assert pr.origin == "CATALOGUE" and pr.status == "APPROVED" and pr.origin_ref.startswith("PUN-")
        warn = s.execute(select(Requisition).where(Requisition.purpose_text == "FY27-28 seal kits for DC-345 housings")).scalar_one()
        assert warn.budget_result["categoryBudget"]["outcome"] == "WARNING" and warn.status == "APPROVED"
        block = s.execute(select(Requisition).where(Requisition.purpose_text == "FY27-28 damper grommets for DC-348 brackets")).scalar_one()
        assert block.status == "DRAFT"
    assert "CATEGORY_BUDGET_EXCEEDED" in " ".join(pack["summary"]["notes"])


def test_erp_import_and_notifications(pack):
    with tenant_tx(pack["tenant"]) as s:
        batch = s.execute(select(IntegrationBatch).where(IntegrationBatch.external_ref == "MD01-P100-2027W20")).scalar_one()
        assert (batch.accepted, batch.rejected) == (2, 5)
        errors = " ".join(r.get("error", "") for r in batch.results)
        assert "does not exist" in errors and "plant P300" in errors and "ISO date" in errors and "more than once" in errors
        firmed = s.execute(select(PlannedOrder).where(PlannedOrder.external_ref == "S4-PLO-0001184520")).scalar_one()
        assert firmed.status == "FIRMED" and firmed.source_system == "SAP_S4"
        c1 = _contract(s, "DC-340 motor end shields FY27-28")
        notes = s.execute(select(Notification).where(Notification.object_ref == c1.number)).scalars().all()
        assert any(n.kind == "CONTRACT_AMENDED" for n in notes)
    counts = pack["summary"]["counts"]
    assert 0 < counts["notificationsRead"] < counts["notifications"]


def test_credit_note_on_unposted_invoice_sends_no_credit_memo(pack):
    """The ERP credit memo is only for invoices already posted; a credit note during matching reduces the posted amount instead."""
    with tenant_tx(pack["tenant"]) as s:
        seeded = s.execute(select(Invoice).where(Invoice.supplier_invoice_no == "INV-TF-8812")).scalar_one()
        assert not s.execute(select(IntegrationMessage).where(IntegrationMessage.message_type == "SUPPLIER_CREDIT_MEMO",
                                                              IntegrationMessage.object_id == seeded.id)).first()


def test_pack_is_idempotent(pack):
    again = datasets.apply_pack("module_cases", PASSWORD)
    assert again[0]["status"] == "ALREADY_LOADED"
