"""D7 dataset pack: general enterprise demo tenant GEN (laptop punch-out ₹78,500 with one approval, indirect buying)."""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    Contract, GoodsReceipt, Invoice, InvoiceLine, Payment, PoLine, PrLine, PunchoutSession, PurchaseOrder, Requisition, RuleSet,
    ServiceEntry, SpendLine, Supplier, Task, Tenant,
)
from app.pic.platform import clock
from app.pic.seed import datasets
from app.pic.seed.datasets import industry_general as pack
from app.pic.services.master_changes import gstin_errors
from tests.pic.conftest import PASSWORD


@pytest.fixture(scope="module")
def loaded(database):
    results = datasets.apply_pack("industry_general", PASSWORD)
    assert [r["status"] for r in results] == ["LOADED"], results
    with system_tx() as s:
        tenant = s.execute(select(Tenant).where(Tenant.code == "GEN")).scalar_one()
        tenant_id, template = tenant.id, tenant.industry_template
    yield {"summary": results[0]["summary"], "tenant_id": tenant_id, "template": template}
    clock.set_pinned(None)


def _po_of_invoice(s, supplier_invoice_no):
    invoice = s.execute(select(Invoice).where(Invoice.supplier_invoice_no == supplier_invoice_no)).scalar_one()
    return invoice, s.get(PurchaseOrder, invoice.po_id)


def test_tenant_comes_from_the_general_template(loaded):
    assert loaded["template"] == "GENERAL"
    with tenant_tx(loaded["tenant_id"]) as s:
        matrix = s.execute(select(RuleSet).where(RuleSet.key == "PURCHASE-TYPE-MATRIX")).scalar_one().body
        assert matrix["EXPENSE"] == {"gr": True, "ir": True, "ses": False, "receiptlessBelowMinor": 100_000 * 100}
        assert {x.code: x.status for x in s.execute(select(Supplier)).scalars()} == {"LVIT01": "ACTIVE", "DOS02": "ACTIVE", "CFM03": "ACTIVE"}
    for spec in (pack.LVIT, pack.DOS, pack.CFM):
        assert gstin_errors(spec["gstin"]) == []


def test_laptop_punch_out_order_with_a_single_approval(loaded):
    laptop = loaded["summary"]["counts"]["laptop"]
    assert laptop["chain"] == ["COST_OBJECT_OWNER"] and laptop["approvals"] == 1 and laptop["touchless"] is True
    with tenant_tx(loaded["tenant_id"]) as s:
        pr = s.execute(select(Requisition).where(Requisition.purpose_text.like("Laptop for new joiner%"))).scalar_one()
        assert pr.origin == "CATALOGUE" and pr.total_minor == 78_500 * 100 and pr.status in ("ORDERED", "APPROVED", "PARTIALLY_ORDERED")
        tasks = s.execute(select(Task).where(Task.object_id == pr.id, Task.kind == "REQ_APPROVAL")).scalars().all()
        assert [(t.candidate_role, t.status, t.decision) for t in tasks] == [("COST_OBJECT_OWNER", "COMPLETED", "APPROVE")]
        line = s.execute(select(PrLine).where(PrLine.requisition_id == pr.id)).scalar_one()
        assert line.item_type == "CATALOGUE" and line.source_determination["method"] == "PUNCHOUT"
        assert line.source_determination["supplierPartNo"] == "LV-NB14-U5-16-512" and line.source_determination["protocol"] == "CXML"
        session = s.execute(select(PunchoutSession).where(PunchoutSession.requisition_id == pr.id)).scalar_one()
        assert session.status == "CONVERTED" and "<PunchOutOrderMessage" in session.cart_document and "SharedSecret>********" in session.setup_request
        invoice, po = _po_of_invoice(s, "LVIT/26-27/2214")
        po_line = s.execute(select(PoLine).where(PoLine.po_id == po.id)).scalar_one()
        # receipt-less below ₹1 L (2-way); HSN/GST from the catalogue item, so the e-invoice matches first time
        assert po_line.gr_required is False and po_line.price_source == "CATALOGUE" and (po_line.hsn_code, po_line.gst_rate) == ("84713010", Decimal(18))
        assert invoice.match_type == "2WAY" and invoice.first_pass_matched and invoice.irn_valid and invoice.status == "PAID"
        assert invoice.gross_minor == 78_500 * 100 + 14_130 * 100
    monitors = loaded["summary"]["counts"]["monitors"]
    assert monitors["chain"] == [] and monitors["status"] == "APPROVED"   # second punch-out ₹23,800: auto-approved under ₹25,000


def test_catalogue_orders_and_desktop_receipt_above_threshold(loaded):
    counts = loaded["summary"]["counts"]
    with tenant_tx(loaded["tenant_id"]) as s:
        supplies = s.execute(select(Requisition).where(Requisition.purpose_code == "OFFICE_CONSUMABLES")).scalars().all()
        assert len(supplies) == 5 and all(pr.approval_chain == [] for pr in supplies)
        for pr in supplies:
            assert s.execute(select(Task).where(Task.object_id == pr.id)).first() is None
        invoice, po = _po_of_invoice(s, "DOS/26-27/5390")
        line = s.execute(select(PoLine).where(PoLine.po_id == po.id)).scalar_one()
        assert line.gr_required is True and line.received_qty == 12 and invoice.match_type == "3WAY" and invoice.first_pass_matched
        gr = s.execute(select(GoodsReceipt).where(GoodsReceipt.po_id == po.id)).scalar_one()
        requester = s.execute(select(Requisition).where(Requisition.id == line.requisition_id)).scalar_one().requester_id
        assert gr.posted_by == requester and gr.posted_by != po.created_by       # desktop receipt; SOD-03 respected
        two_way = s.execute(select(Invoice).where(Invoice.supplier_invoice_no.like("DOS/26-27/5%"), Invoice.id != invoice.id)).scalars().all()
        assert len(two_way) == 5 and all(i.match_type == "2WAY" and i.first_pass_matched for i in two_way)
    assert counts["chairs"]["chain"] == ["COST_OBJECT_OWNER"] and counts["chairs"]["approvals"] == 1


def test_housekeeping_service_contract_entries_and_payments(loaded):
    counts = loaded["summary"]["counts"]
    with tenant_tx(loaded["tenant_id"]) as s:
        contract = s.execute(select(Contract).where(Contract.title.like("Housekeeping services%"))).scalar_one()
        assert contract.status == "ACTIVE" and contract.target_value_minor == 12 * 168_000 * 100
        po = s.execute(select(PurchaseOrder).where(PurchaseOrder.contract_id == contract.id)).scalar_one()
        assert po.touchless and s.execute(select(PoLine).where(PoLine.po_id == po.id)).scalar_one().ses_approved_minor == 5 * 168_000 * 100
        entries = s.execute(select(ServiceEntry).where(ServiceEntry.po_id == po.id)).scalars().all()
        assert len(entries) == 5 and all(e.status == "APPROVED" for e in entries)
        invoices = s.execute(select(Invoice).where(Invoice.supplier_invoice_no.like("CFM/26-27/%"))).scalars().all()
        assert len(invoices) == 5 and all(i.match_type == "SES" and i.first_pass_matched for i in invoices)
        lines = s.execute(select(InvoiceLine).where(InvoiceLine.invoice_id.in_([i.id for i in invoices]))).scalars().all()
        assert {l.hsn_code for l in lines} == {"998533"}
        payments = s.execute(select(Payment)).scalars().all()
        assert len(payments) == counts["paid"] >= 8
        spend = s.execute(select(SpendLine)).scalars().all()
        assert {l.category for l in spend} == {"IT-HARDWARE", "OFFICE-SUPPLIES", "OFFICE-FURNITURE", "FACILITIES"}
        assert {l.period for l in spend} >= {"2026-11", "2026-12", "2027-01", "2027-02", "2027-03"}
        assert s.execute(select(Task).where(Task.status == "OPEN")).first() is None
    kpis = counts["kpis"]
    # catalogue / punch-out ≈ 29 % of PO value, the housekeeping contract call-off the rest: all spend through guided channels
    assert Decimal(kpis["catalogueAdoptionPct"]) > 25 and kpis["guidedBuyingPct"] == "100.0" and Decimal(kpis["maverickPct"]) == 0


def test_second_apply_is_idempotent(loaded):
    assert [r["status"] for r in datasets.apply_pack("industry_general", PASSWORD)] == ["ALREADY_LOADED"]
