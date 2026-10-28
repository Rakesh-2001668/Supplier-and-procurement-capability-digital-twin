"""D4 IT services demo tenant ITS (pack industry_it): SOW-4410 T&M, rate card RC-22, timesheet SES, licence renewal."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    Certificate, Clause, CompanyCode, Contract, ContractAmendment, ContractLine, GoodsReceipt, Invoice, PoLine, PurchaseOrder, ServiceEntry,
    SesLine, Supplier, Task, Tenant, Timer,
)
from app.pic.platform import clock, rules
from app.pic.seed import datasets
from app.pic.seed.datasets import industry_it as pack
from app.pic.seed.datasets._tenant_kit import gstin_valid
from tests.pic.conftest import PASSWORD


@pytest.fixture(scope="module")
def its(database):
    result = datasets.apply_pack("industry_it", PASSWORD)
    assert result[0]["status"] == "LOADED", result
    with system_tx() as s:
        tenant = s.execute(select(Tenant).where(Tenant.code == "ITS")).scalar_one()
        tenant_id, template = tenant.id, tenant.industry_template
    yield {"tenant_id": tenant_id, "template": template, "summary": result[0]["summary"]}
    clock.set_pinned(None)


def _contract(s, number: str) -> Contract:
    return s.execute(select(Contract).where(Contract.number == number)).scalar_one()


def test_tenant_template_and_infosec_qualification(its):
    assert its["template"] == "IT_SERVICES"
    with tenant_tx(its["tenant_id"]) as s:
        company = s.execute(select(CompanyCode)).scalar_one()
        assert gstin_valid(company.gstin) and company.gstin[:2] == "27"
        clock.set_pinned(clock.at_ist(date(2026, 12, 1), 10))
        assert rules.resolve(s, "CONTRACT-APPROVAL").body["renewalNoticeDays"] == 90
        assert rules.resolve(s, "SUPPLIER-QUAL").body["mandatoryCertificates"] == {"IT-SERVICES": ["ISO27001"]}
        clock.set_pinned(None)
        pcc = s.execute(select(Supplier).where(Supplier.code == "PCC001")).scalar_one()
        iso = s.execute(select(Certificate).where(Certificate.supplier_id == pcc.id, Certificate.type == "ISO27001")).scalar_one()
        assert iso.verified and pcc.status == "ACTIVE"
    assert all(gstin_valid(x.gstin) for x in pack.SUPPLIERS)


def test_sow_4410_with_rate_card_rc22(its, client, login):
    with tenant_tx(its["tenant_id"]) as s:
        sow = _contract(s, "SOW-4410")
        assert sow.status == "ACTIVE" and "RC-22" in sow.title and sow.type == "VALUE_CONTRACT"
        lines = s.execute(select(ContractLine).where(ContractLine.contract_id == sow.id).order_by(ContractLine.line_no)).scalars().all()
        assert [(l.uom, l.target_qty) for l in lines] == [(uom, Decimal(qty)) for _, _, uom, qty, _ in pack.RC22]
        assert all("RC-22" in l.description for l in lines)
        rates = s.execute(select(Clause).where(Clause.contract_id == sow.id, Clause.code == "RATES")).scalar_one()
        assert "rate card RC-22" in rates.text
        assert sow.target_value_minor == sum(q * r for _, _, _, q, r in pack.RC22) == 64_84_000_00
        po_ids = set(s.execute(select(PoLine.po_id).where(PoLine.contract_line_id.in_([l.id for l in lines]))).scalars())
        [po_id] = po_ids
        po = s.get(PurchaseOrder, po_id)
        assert po.status == "CONFIRMED" and po.retention_pct is None
        po_lines = s.execute(select(PoLine).where(PoLine.po_id == po.id)).scalars().all()
        assert len(po_lines) == 5 and {l.price_source for l in po_lines} == {"CONTRACT"} and all(l.ses_required for l in po_lines)
    headers = login(f"contract.manager@{pack.DOMAIN}", "ITS")
    r = client.get("/v1/contracts/SOW-4410", headers=headers)
    assert r.status_code == 200, r.text


def test_timesheet_ses_320_hours_and_invoice_matched_to_ses(its):
    with tenant_tx(its["tenant_id"]) as s:
        invoice = s.execute(select(Invoice).where(Invoice.supplier_invoice_no == "PCC/INV/2026-27/0098")).scalar_one()
        ses = s.execute(select(ServiceEntry).where(ServiceEntry.po_id == invoice.po_id)).scalar_one()
        assert ses.method == "TIME_MATERIAL" and ses.status == "APPROVED"
        assert (ses.period_from, ses.period_to) == (date(2026, 11, 1), date(2026, 11, 30))
        ses_lines = s.execute(select(SesLine).where(SesLine.ses_id == ses.id)).scalars().all()
        assert sum(l.qty for l in ses_lines) == Decimal(320) and ses.total_minor == 7_00_000_00
        assert invoice.match_type == "SES" and invoice.first_pass_matched is True and invoice.status == "PAID"
        assert invoice.net_minor == ses.total_minor and invoice.retention_minor == 0
        po_lines = s.execute(select(PoLine).where(PoLine.po_id == invoice.po_id)).scalars().all()
        assert sum(l.ses_approved_minor for l in po_lines) == sum(l.invoiced_minor for l in po_lines) == ses.total_minor


def test_licence_renewal_alert_decision_and_extension(its):
    with tenant_tx(its["tenant_id"]) as s:
        lic = _contract(s, "LIC-2601")
        assert lic.status == "ACTIVE" and lic.valid_to == date(2028, 3, 31) and lic.version == 2
        renewal = s.execute(select(Task).where(Task.kind == "CONTRACT_RENEWAL", Task.object_id == lic.id)).scalar_one()
        assert renewal.status == "COMPLETED" and renewal.decision == "APPROVE" and "FY 2027-28" in renewal.comment
        fired = s.execute(select(Timer).where(Timer.kind == "CONTRACT_RENEWAL", Timer.object_id == lic.id, Timer.fired_at.is_not(None))).scalar_one()
        assert fired.due_at.astimezone(clock.IST).date() == date(2027, 3, 31) - timedelta(days=90) == date(2026, 12, 31)
        rearmed = s.execute(select(Timer).where(Timer.kind == "CONTRACT_RENEWAL", Timer.object_id == lic.id, Timer.fired_at.is_(None))).scalar_one()
        assert rearmed.due_at.astimezone(clock.IST).date() == date(2028, 3, 31) - timedelta(days=90)
        [extension] = s.execute(select(ContractAmendment).where(ContractAmendment.contract_id == lic.id)).scalars().all()
        assert extension.kind == "EXTENSION" and extension.status == "EFFECTIVE" and extension.approved_by != extension.requested_by
        line = s.execute(select(ContractLine).where(ContractLine.contract_id == lic.id)).scalar_one()
        po_line = s.execute(select(PoLine).where(PoLine.contract_line_id == line.id)).scalar_one()
        gr = s.execute(select(GoodsReceipt).where(GoodsReceipt.po_id == po_line.po_id)).scalar_one()
        # A licence entitlement is not quality-managed: the receipt is accepted on posting (GR_SM POSTED → accept → ACCEPTED).
        assert gr.status == "ACCEPTED" and po_line.received_qty == po_line.accepted_qty == Decimal(150)
        invoice = s.execute(select(Invoice).where(Invoice.supplier_invoice_no == "MSD/26-27/1187")).scalar_one()
        assert invoice.match_type == "3WAY" and invoice.status == "PAID" and invoice.first_pass_matched is True
    assert its["summary"]["renewal"] == {"contract": "LIC-2601", "status": "ACTIVE", "validTo": "2028-03-31",
                                         "extension": its["summary"]["renewal"]["extension"], "alertFired": 1}


def test_pack_is_idempotent(its):
    assert datasets.apply_pack("industry_it", PASSWORD)[0]["status"] == "ALREADY_LOADED"
