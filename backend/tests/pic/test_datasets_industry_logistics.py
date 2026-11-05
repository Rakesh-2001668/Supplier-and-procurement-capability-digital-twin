"""D5 dataset pack: logistics demo tenant LOG (lane CHE→PNQ 32 ft MXL, ₹54/km + demo fuel index, POD, freight audit)."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    Contract, ContractLine, CreditNote, Invoice, InvoiceException, InvoiceLine, Material, Payment, PoLine, PriceValidity,
    PurchaseOrder, RuleSet, ServiceEntry, SesLine, SpendLine, Supplier, SupplierCategoryStatus, Task, Tenant,
)
from app.pic.platform import clock
from app.pic.seed import datasets
from app.pic.seed.datasets import industry_logistics as pack
from app.pic.services.master_changes import gstin_errors
from tests.pic.conftest import PASSWORD


@pytest.fixture(scope="module")
def loaded(database):
    results = datasets.apply_pack("industry_logistics", PASSWORD)
    assert [r["status"] for r in results] == ["LOADED"], results
    with system_tx() as s:
        tenant = s.execute(select(Tenant).where(Tenant.code == "LOG")).scalar_one()
        tenant_id, template = tenant.id, tenant.industry_template
    yield {"summary": results[0]["summary"], "tenant_id": tenant_id, "template": template}
    clock.set_pinned(None)


def test_tenant_comes_from_the_logistics_template(loaded):
    assert loaded["template"] == "LOGISTICS"
    with tenant_tx(loaded["tenant_id"]) as s:
        keys = {r.key: r for r in s.execute(select(RuleSet)).scalars()}
        assert keys["FREIGHT-AUDIT"].body["rateTolerancePct"] == "0"
        assert keys["SUPPLIER-QUAL"].body["mandatoryCertificates"]["LOGISTICS"] == ["GIT_INSURANCE", "NATIONAL_PERMIT"]
        playbook = s.execute(select(RuleSet).where(RuleSet.key == "CLM-PLAYBOOK", RuleSet.version == "2026.1-LOG")).scalar_one()
        assert "FUEL_INDEX" in {c["code"] for c in playbook.body["templates"]["VALUE_CONTRACT"]}
        for supplier in s.execute(select(Supplier)).scalars():
            assert supplier.status == "ACTIVE"
            status = s.execute(select(SupplierCategoryStatus.status).where(SupplierCategoryStatus.supplier_id == supplier.id,
                                                                           SupplierCategoryStatus.category == "LOGISTICS")).scalar_one()
            assert status == "QUALIFIED"
    for spec in (pack.KRW, pack.WGC):
        assert gstin_errors(spec["gstin"]) == []
    assert gstin_errors(pack.gstin("33", pack.COMPANY_PAN)) == []


def test_lane_contract_rate_and_demo_fuel_index(loaded):
    with tenant_tx(loaded["tenant_id"]) as s:
        contract = s.execute(select(Contract).where(Contract.title.like("Lane rate contract CHE1%"))).scalar_one()
        assert contract.status == "ACTIVE" and contract.type == "VALUE_CONTRACT"
        assert contract.index_ref["index"] == "DEMO-DIESEL-IDX" and "not published diesel prices" in contract.index_ref["label"]
        line = s.execute(select(ContractLine).where(ContractLine.contract_id == contract.id)).scalar_one()
        material = s.get(Material, line.material_id)
        assert (material.type, material.base_uom, material.hsn_code, material.category) == ("SERVICE", "KM", "996791", "LOGISTICS")
        prices = {v.valid_from: (v.unit_price_minor, v.reason) for v in s.execute(select(PriceValidity).where(
            PriceValidity.contract_line_id == line.id)).scalars()}
    assert prices[date(2026, 11, 1)][0] == 5400
    assert prices[date(2026, 12, 1)] == (5400, "INDEX_RESET_ABSORBED")         # +1.5 % inside the ±2 % band
    assert prices[date(2027, 1, 1)] == (5465, "INDEX_RESET_ADJUSTED")          # +3.2 % → +1.2 %
    assert prices[date(2027, 2, 1)] == (5540, "INDEX_RESET_ADJUSTED")          # +4.6 % → +2.6 %
    assert prices[date(2027, 3, 1)] == (5443, "INDEX_RESET_ADJUSTED")          # +2.8 % → +0.8 %
    assert loaded["summary"]["counts"]["kpis"]["rateByMonthMinor"] == {"2026-11": 5400, "2026-12": 5400, "2027-01": 5465,
                                                                       "2027-02": 5540, "2027-03": 5443}


def test_trips_are_touchless_services_confirmed_by_pod(loaded):
    with tenant_tx(loaded["tenant_id"]) as s:
        contract = s.execute(select(Contract).where(Contract.title.like("Lane rate contract CHE1%"))).scalar_one()
        trip_pos = s.execute(select(PurchaseOrder).where(PurchaseOrder.contract_id == contract.id)).scalars().all()
        assert len(trip_pos) == 15 and all(po.touchless for po in trip_pos)
        for po in trip_pos:
            line = s.execute(select(PoLine).where(PoLine.po_id == po.id)).scalar_one()
            assert line.ses_required and not line.gr_required and line.qty == Decimal(1180) and line.uom == "KM"
            ses = s.execute(select(ServiceEntry).where(ServiceEntry.po_id == po.id)).scalar_one()
            assert ses.method == "POD" and ses.status == "APPROVED"
            pod = s.execute(select(SesLine).where(SesLine.ses_id == ses.id)).scalar_one()
            assert pod.description.startswith("POD KRW/LR/") and pod.qty <= Decimal(1180)
            assert line.unit_price_minor == pod.unit_rate_minor
        consumed = s.get(ContractLine, s.execute(select(ContractLine.id).where(ContractLine.contract_id == contract.id)).scalar_one())
        assert consumed.released_qty == Decimal(15 * 1180)


def test_freight_audit_flags_the_overbilled_invoice_and_recovers_it(loaded):
    with tenant_tx(loaded["tenant_id"]) as s:
        invoice = s.execute(select(Invoice).where(Invoice.supplier_invoice_no == "KRW/26-27/0408")).scalar_one()
        exceptions = s.execute(select(InvoiceException).where(InvoiceException.invoice_id == invoice.id)).scalars().all()
        assert sorted(e.type for e in exceptions) == ["FREIGHT_AUDIT", "SERVICE"]
        audit_exc = next(e for e in exceptions if e.type == "FREIGHT_AUDIT")
        # 1,240 km billed vs POD 1,177 km at the January contracted rate ₹54.65/km (demo index 103.20).
        assert audit_exc.delta["billedQty"] == "1240" and audit_exc.delta["podQty"] == "1177"
        assert audit_exc.delta["expectedMinor"] == 1177 * 5465 and audit_exc.delta["overbilledMinor"] == 63 * 5465
        assert "index 103.20" in audit_exc.detail and audit_exc.status == "RESOLVED" and audit_exc.resolution == "CREDIT_NOTE_RECEIVED"
        note = s.execute(select(CreditNote).where(CreditNote.invoice_id == invoice.id)).scalar_one()
        assert note.net_minor == 63 * 5465
        assert invoice.status in ("POSTED", "PAID") and invoice.first_pass_matched is False
        line = s.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)).scalar_one()
        assert line.match_detail["freightAudit"]["withinTolerance"] is True and Decimal(line.match_detail["netQty"]) == 1177
        # every other carrier invoice passed the freight audit first time
        clean = s.execute(select(Invoice).where(Invoice.supplier_invoice_no.like("KRW/26-27/%"), Invoice.id != invoice.id)).scalars().all()
        assert len(clean) == 14 and all(i.first_pass_matched for i in clean)
        for other in clean:
            detail = s.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == other.id)).scalar_one().match_detail["freightAudit"]
            assert detail["withinTolerance"] and detail["expectedMinor"] == detail["billedMinor"]
    assert loaded["summary"]["counts"]["kpis"]["auditRecoveriesMinor"] == 63 * 5465


def test_spot_trip_payments_spend_and_kpis(loaded):
    counts = loaded["summary"]["counts"]
    with tenant_tx(loaded["tenant_id"]) as s:
        spot = s.execute(select(Invoice).where(Invoice.supplier_invoice_no == "WGC/2026-27/1184")).scalar_one()
        assert spot.match_type == "SES" and spot.first_pass_matched and spot.status == "PAID"
        po = s.get(PurchaseOrder, spot.po_id)
        assert po.touchless is False and s.execute(select(Task).where(Task.object_id == po.id, Task.kind == "PO_APPROVAL",
                                                                       Task.status == "COMPLETED")).first()
        # the spot line has no contract: no freight audit
        assert "freightAudit" not in s.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == spot.id)).scalar_one().match_detail
        payments = s.execute(select(Payment)).scalars().all()
        assert len(payments) == counts["paid"] >= 10
        spend = s.execute(select(SpendLine).where(SpendLine.category == "LOGISTICS")).scalars().all()
        # 16 freight invoice lines. Since the spend cube takes credit and debit notes as documents of their own (spend second pass, S3), a note posted
        # against a freight invoice is a cube line of its own too (a credit note is negative, a debit note positive, in the period of the note): the
        # invoice lines stay 16 and the total is 16 plus the notes.
        invoice_lines = [line for line in spend if line.document_type == "INVOICE"]
        notes = [line for line in spend if line.document_type != "INVOICE"]
        assert len(invoice_lines) == 16 and {line.period for line in invoice_lines} >= {"2026-11", "2026-12", "2027-01", "2027-02", "2027-03"}
        assert all((line.document_type == "CREDIT_NOTE") == (line.amount_minor < 0) for line in notes)
        assert {line.document_type for line in notes} <= {"CREDIT_NOTE", "DEBIT_NOTE"} and len(spend) == 16 + len(notes)
        assert sum(1 for line in invoice_lines if line.contracted) == 15
        open_tasks = s.execute(select(Task).where(Task.status == "OPEN")).scalars().all()
        assert open_tasks == []
    kpis = counts["kpis"]
    assert kpis["contractTrips"] == 15 and Decimal(kpis["costPerKm"]) > Decimal("54")
    assert Decimal("3") < Decimal(kpis["costPerTonneKm"]) < Decimal("4")


def test_tenants_without_the_freight_audit_rule_keep_the_standard_match(loaded):
    with system_tx() as s:
        axn = s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()
    with tenant_tx(axn) as s:
        assert s.execute(select(RuleSet.id).where(RuleSet.key == "FREIGHT-AUDIT")).first() is None
        invoice = s.execute(select(Invoice).where(Invoice.supplier_invoice_no == "HTS/1107")).scalar_one()   # SES-matched service invoice
        detail = s.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)).scalar_one().match_detail
        assert "freightAudit" not in detail and invoice.first_pass_matched


def test_detention_claims_freight_movements_and_index_feed(loaded):
    """Wave 1 (item 41): rate rule per carrier and lane, a claim blocked without POD and one approved with it, freight movements for the
    cost-per-tonne-km KPI (which agrees with the pack's own calculation) and the fed demonstration index."""
    from app.pic.models import AccessorialCharge, AccessorialRate, FreightMovement, IndexValue, Tenant
    from app.pic.services import ind_kpis
    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == "LOG")).scalar_one()
    with tenant_tx(tenant_id) as s:
        rate = s.execute(select(AccessorialRate)).scalar_one()
        assert (rate.charge_type, rate.unit, rate.free_units, rate.rate_minor, rate.lane) == ("DETENTION", "HOUR", Decimal(4), 60_000, "PNQ1-CHE1")
        charges = {c.status: c for c in s.execute(select(AccessorialCharge)).scalars()}
        assert set(charges) == {"BLOCKED", "APPROVED"} and "proof of delivery" in charges["BLOCKED"].reason and charges["BLOCKED"].ses_id is None
        approved = charges["APPROVED"]
        assert (approved.units, approved.billable_units, approved.amount_minor) == (Decimal(11), Decimal(7), 7 * 60_000) and approved.pod_ses_id and approved.ses_id
        movements = s.execute(select(FreightMovement)).scalars().all()
        assert movements and all(m.lane == "CHE1-PNQ1" and m.ses_id for m in movements)
        index = s.execute(select(IndexValue).where(IndexValue.index_code == "DEMO-DIESEL-IDX").order_by(IndexValue.as_of)).scalars().all()
        assert [str(v.value) for v in index] == ["101.5000", "103.2000", "104.6000", "102.8000"] and all(v.source == "IMPORT" for v in index)
        kpi = {k["code"]: k for k in ind_kpis.industry_kpis(s, include_other_templates=True)["kpis"]}["TPL.COST_PER_TONNE_KM"]
        pack_kpis = datasets.loaded("LOG", pack.KEY).summary["counts"]["kpis"]
        assert kpi["detail"]["trips"] == len(movements)
        assert abs(Decimal(kpi["value"]) / 100 - Decimal(pack_kpis["costPerTonneKm"])) < Decimal("0.01")

def test_second_apply_is_idempotent(loaded):
    assert [r["status"] for r in datasets.apply_pack("industry_logistics", PASSWORD)] == ["ALREADY_LOADED"]
