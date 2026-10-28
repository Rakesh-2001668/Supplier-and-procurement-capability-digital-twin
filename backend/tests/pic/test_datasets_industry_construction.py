"""D3 construction demo tenant CON (pack industry_construction) and the retention behaviour of F7 (payables)."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AuditEvent, Budget, CompanyCode, Contract, ContractAmendment, ContractLine, IntegrationMessage, Invoice, Material, Payment, PoLine,
    PurchaseOrder, RuleSet, ServiceEntry, Supplier, SupplierCategoryStatus, Tenant,
)
from app.pic.platform import clock, rules
from app.pic.seed import datasets
from app.pic.seed.axion import Scenario, at
from app.pic.seed.datasets import _tenant_kit as kit
from app.pic.seed.datasets import industry_construction as pack
from app.pic.seed.datasets._tenant_kit import gstin_valid
from app.pic.services import order, payables, receiving, requisition
from tests.pic.conftest import PASSWORD

@pytest.fixture(scope="module")
def con(database):
    result = datasets.apply_pack("industry_construction", PASSWORD)
    assert result[0]["status"] == "LOADED", result
    with system_tx() as s:
        tenant = s.execute(select(Tenant).where(Tenant.code == "CON")).scalar_one()
        tenant_id, template = tenant.id, tenant.industry_template
    yield {"tenant_id": tenant_id, "template": template, "summary": result[0]["summary"],
           "sc": Scenario(tenant_id, tenant_code="CON", domain=pack.DOMAIN, role_user=pack.ROLE_USER)}
    clock.set_pinned(None)


def _po(s, contract_number: str) -> PurchaseOrder:
    contract = s.execute(select(Contract).where(Contract.number == contract_number)).scalar_one()
    line_ids = [l.id for l in s.execute(select(ContractLine).where(ContractLine.contract_id == contract.id)).scalars()]
    po_id = s.execute(select(PoLine.po_id).where(PoLine.contract_line_id.in_(line_ids))).scalars().first()
    return s.get(PurchaseOrder, po_id)


def test_tenant_bootstrap_users_and_masters(con):
    assert con["template"] == "CONSTRUCTION"
    with tenant_tx(con["tenant_id"]) as s:
        company = s.execute(select(CompanyCode)).scalar_one()
        assert gstin_valid(company.gstin) and company.gstin[:2] == "29"
        budget = s.execute(select(Budget).where(Budget.cost_object_type == "WBS", Budget.cost_object_code == "C-2207")).scalar_one()
        assert budget.control == "HARD" and budget.amount_minor == 350 * pack.L
        assert budget.consumed_minor > 0  # posted running-account bills consumed the WBS budget
        assert rules.resolve(s, "PROJECT-CONTROLS").body["retentionPct"] == "5"
        statuses = {(sup.code, st.category): st.status for sup, st in s.execute(
            select(Supplier, SupplierCategoryStatus).join(SupplierCategoryStatus, SupplierCategoryStatus.supplier_id == Supplier.id)
            .where(Supplier.code.in_([x.code for x in pack.SUPPLIERS]))).all()}
        assert statuses == {("SRF001", "CIVIL-SUBCONTRACT"): "QUALIFIED", ("TRM002", "CONSTRUCTION-MATERIALS"): "QUALIFIED",
                            ("KEH003", "EQUIPMENT-HIRE"): "QUALIFIED"}
        qual = s.execute(select(RuleSet).where(RuleSet.key == "SUPPLIER-QUAL", RuleSet.version == "2026.1-CON")).scalar_one()
        assert qual.body["mandatoryCertificates"] == {"CIVIL-SUBCONTRACT": ["ISO45001"]}
    assert all(gstin_valid(x.gstin) for x in pack.SUPPLIERS)


def test_subcontract_variation_and_po(con):
    with tenant_tx(con["tenant_id"]) as s:
        contract = s.execute(select(Contract).where(Contract.number == "SC-118")).scalar_one()
        assert contract.status == "ACTIVE" and contract.version == 2
        lines = {l.line_no: l for l in s.execute(select(ContractLine).where(ContractLine.contract_id == contract.id)).scalars()}
        assert (lines[10].target_qty, lines[20].target_qty) == (Decimal(135), Decimal(6500))
        assert contract.target_value_minor == 135 * pack.REBAR["rate"] + 6500 * pack.FORMWORK["rate"]
        [vo] = s.execute(select(ContractAmendment).where(ContractAmendment.contract_id == contract.id)).scalars().all()
        assert vo.kind == "VARIATION" and vo.status == "EFFECTIVE" and vo.reason.startswith("VO-01")
        assert vo.approved_by != vo.requested_by
        po = _po(s, "SC-118")
        assert po.retention_pct == Decimal(5) and po.version == 2 and po.status == "CONFIRMED"
        po_lines = {l.line_no: l for l in s.execute(select(PoLine).where(PoLine.po_id == po.id)).scalars()}
        assert po_lines[10].qty == Decimal(135) and po_lines[10].ses_required
        assert po_lines[10].ses_approved_minor == po_lines[10].net_minor  # 100% measured
        assert po_lines[20].ses_approved_minor == po_lines[20].net_minor
        sess = s.execute(select(ServiceEntry).where(ServiceEntry.po_id == po.id).order_by(ServiceEntry.period_from)).scalars().all()
        assert [x.method for x in sess] == ["PROGRESS"] * 3 and all(x.status == "APPROVED" for x in sess)
        original = 120 * pack.REBAR["rate"] + 6500 * pack.FORMWORK["rate"]
        assert sess[0].total_minor == original * 35 // 100  # first SES at 35% progress


def test_running_bills_withhold_retention_and_pay_net(con):
    with tenant_tx(con["tenant_id"]) as s:
        po = _po(s, "SC-118")
        bills = s.execute(select(Invoice).where(Invoice.po_id == po.id, Invoice.match_type == "SES").order_by(Invoice.invoice_date)).scalars().all()
        assert [b.supplier_invoice_no for b in bills] == [f"SRF/RA/2026-27/0{i}" for i in (1, 2, 3)]
        for bill in bills:
            assert bill.retention_minor == round(bill.net_minor * Decimal("0.05")) and bill.retention_minor > 0
            assert bill.status == "PAID" and bill.first_pass_matched is True
            payment = s.execute(select(Payment).where(Payment.invoice_id == bill.id)).scalar_one()
            assert payment.amount_minor == bill.gross_minor - bill.retention_minor
        assert bills[0].retention_minor == 2_18_925_00
        message = s.execute(select(IntegrationMessage).where(IntegrationMessage.message_type == "SUPPLIER_INVOICE",
                                                             IntegrationMessage.object_id == bills[0].id)).scalar_one()
        assert message.payload["grossMinor"] == bills[0].gross_minor  # ERP books the full liability
        assert message.payload["retentionMinor"] == bills[0].retention_minor
        assert message.payload["netPayableMinor"] == bills[0].gross_minor - bills[0].retention_minor
        withheld = s.execute(select(AuditEvent).where(AuditEvent.object_id == bills[0].id, AuditEvent.action == "RETENTION_WITHHELD")).scalars().all()
        assert len(withheld) == 1
        # Material supply to the project carries no retention (the PROJECT-CONTROLS default covers works orders only).
        rmc = s.execute(select(Invoice).where(Invoice.supplier_invoice_no == "TRM/2627/0412")).scalar_one()
        assert rmc.retention_minor == 0 and rmc.match_type == "3WAY" and rmc.status == "PAID"
        assert s.get(PurchaseOrder, rmc.po_id).retention_pct is None


def test_retention_released_at_completion_and_paid(con, client, login):
    with tenant_tx(con["tenant_id"]) as s:
        po = _po(s, "SC-118")
        release = s.execute(select(Invoice).where(Invoice.po_id == po.id, Invoice.match_type == "RETENTION")).scalar_one()
        bills = s.execute(select(Invoice).where(Invoice.po_id == po.id, Invoice.match_type == "SES")).scalars().all()
        assert release.gross_minor == sum(b.retention_minor for b in bills) == release.net_minor
        assert release.tax_minor == 0 and release.status == "PAID" and release.channel == "RETENTION"
        payment = s.execute(select(Payment).where(Payment.invoice_id == release.id)).scalar_one()
        assert payment.amount_minor == release.gross_minor
        message = s.execute(select(IntegrationMessage).where(IntegrationMessage.message_type == "PAYMENT",
                                                             IntegrationMessage.object_id == release.id)).scalar_one()
        assert message.payload["retentionRelease"] is True
        assert {i["invoice"] for i in message.payload["retentionItems"]} == {b.supplier_invoice_no for b in bills}
        po_number, release_number = po.number, release.number
    headers = login(f"ap.clerk@{pack.DOMAIN}", "CON")
    position = client.get(f"/v1/purchase-orders/{po_number}/retention", headers=headers).json()
    assert position["retentionPct"] == "5.00" or Decimal(position["retentionPct"]) == 5
    assert position["outstandingMinor"] == 0 and position["releasedMinor"] == position["withheldMinor"] > 0
    assert position["releases"][0]["paymentStatus"] == "PAID"
    assert "Completion certificate" in position["releases"][0]["reference"]
    view = client.get(f"/v1/invoices/{release_number}", headers=headers).json()
    assert view["match_type"] == "RETENTION" and len(view["lines"]) == 3
    again = client.post(f"/v1/purchase-orders/{po_number}/retention-release", headers=headers,
                        json={"reference": "CC-01", "reason": "second release"})
    assert again.status_code == 422 and "No retention outstanding" in again.json()["detail"]


def test_project_controls_default_and_partial_release_api(con, client, login):
    """A works order on a WBS gets the template's 5% retention without the buyer setting it; partial releases are allocated
    and the outstanding balance follows; releases are guarded by role, amount and PO."""
    sc = con["sc"]
    when = at(date(2027, 3, 31), 17)
    with sc.act("site.engineer", when) as s:
        material = s.execute(select(ContractLine.material_id).where(ContractLine.line_no == 20)).scalars().first()
        number = s.get(Material, material).number
        pr = requisition.create(s, origin="MANUAL", purpose_code="PROJECT_EXECUTION", purpose_text="MEP shaft formwork", plant=pack.SITE,
                                lines=[{"item_type": "MATERIAL", "purchase_type": "SERVICE", "material": number, "qty": "100",
                                        "price_est_minor": 660_00, "account_assignment_type": "WBS", "account_assignment_code": "C-2208",
                                        "need_date": "2027-04-30"}])
        requisition.submit(s, pr)
        pr_id, pr_no = pr.id, pr.number
    sc.approve_all(pr_id, at(date(2027, 3, 31), 17, 10))
    with sc.act("buyer", at(date(2027, 3, 31), 17, 20)) as s:
        po = order.create_from_requisition(s, requisition=pr_no, lines=[10], supplier_code="SRF001", unit_price_minor=660_00)[0]
        po_id, po_no = po.id, po.number
        assert po.retention_pct == Decimal(5)
        event = s.execute(select(AuditEvent).where(AuditEvent.object_id == po_id, AuditEvent.action == "RETENTION_SET")).scalar_one()
        assert event.after["source"].startswith("PROJECT-CONTROLS@")
    sc.approve_all(po_id, at(date(2027, 3, 31), 17, 30))
    kit.relay(sc, at(date(2027, 3, 31), 17, 35))
    supplier_user = kit.supplier_email(pack.SUPPLIERS[0])
    with sc.act(supplier_user, at(date(2027, 3, 31), 17, 40)) as s:
        order.confirm(s, s.get(PurchaseOrder, po_id), "CONFIRMED")
        ses = receiving.create_ses(s, s.get(PurchaseOrder, po_id), method="PROGRESS", period_from=date(2027, 3, 1), period_to=date(2027, 3, 31),
                                   lines=[{"line": 10, "qty": "100", "unit_rate": "660"}])
        receiving.submit_ses(s, ses)
        ses_id = ses.id
    sc.approve_all(ses_id, at(date(2027, 3, 31), 17, 45))
    with sc.act(supplier_user, at(date(2027, 3, 31), 17, 50)) as s:
        inv = payables.capture(s, supplier="SRF001", supplier_invoice_no="SRF/C2208/01", invoice_date=date(2027, 3, 31), channel="PORTAL",
                               lines=[{"po": po_no, "po_line": 10, "qty": "100", "unit_price": "660", "gst_rate": "18", "hsn": "995454"}])
        assert inv.retention_minor == 3_300_00 and inv.status == "MATCHED"
        inv_id = inv.id
    clock.set_pinned(at(date(2027, 3, 31), 18))
    ap = login(f"ap.clerk@{pack.DOMAIN}", "CON")
    # Not posted yet: retention is pending and cannot be released.
    pending = client.post(f"/v1/purchase-orders/{po_no}/retention-release", headers=ap, json={"reference": "CC-02", "reason": "early"})
    assert pending.status_code == 422 and "still being matched" in pending.json()["detail"]
    with sc.act("ap.clerk", at(date(2027, 3, 31), 18, 5)) as s:
        invoice = s.get(Invoice, inv_id)
        payables.approve(s, invoice)
        payables.post(s, invoice, payables.posting_key(s, invoice))
    clock.set_pinned(at(date(2027, 3, 31), 18, 10))
    assert client.get(f"/v1/purchase-orders/{po_no}/retention", headers=ap).json()["outstandingMinor"] == 3_300_00
    buyer = login(f"buyer@{pack.DOMAIN}", "CON")
    assert client.post(f"/v1/purchase-orders/{po_no}/retention-release", headers=buyer,
                       json={"reference": "CC-02", "reason": "partial"}).status_code == 403
    too_much = client.post(f"/v1/purchase-orders/{po_no}/retention-release", headers=ap,
                           json={"reference": "CC-02", "reason": "partial", "amountMinor": 5_000_00})
    assert too_much.status_code == 422
    first = client.post(f"/v1/purchase-orders/{po_no}/retention-release", headers=ap,
                        json={"reference": "Shaft handover SH-01", "reason": "50% on handover", "amountMinor": 1_650_00,
                              "releaseDate": "2027-03-31"})
    assert first.status_code == 201, first.text
    assert first.json()["match_type"] == "RETENTION" and first.json()["gross_minor"] == 1_650_00 and first.json()["status"] == "POSTED"
    position = client.get(f"/v1/purchase-orders/{po_no}/retention", headers=ap).json()
    assert (position["withheldMinor"], position["releasedMinor"], position["outstandingMinor"]) == (3_300_00, 1_650_00, 1_650_00)
    assert position["invoices"][0]["invoice"] == "SRF/C2208/01"
    # A supply order without retention cannot release anything.
    with tenant_tx(con["tenant_id"]) as s:
        rmc_po = s.get(PurchaseOrder, s.execute(select(Invoice.po_id).where(Invoice.supplier_invoice_no == "TRM/2627/0412")).scalar_one())
        rmc_no = rmc_po.number
    none = client.post(f"/v1/purchase-orders/{rmc_no}/retention-release", headers=ap, json={"reference": "x-1", "reason": "none"})
    assert none.status_code == 422 and "carries no retention" in none.json()["detail"]
    clock.set_pinned(None)


def test_pack_is_idempotent(con):
    assert datasets.apply_pack("industry_construction", PASSWORD)[0]["status"] == "ALREADY_LOADED"
