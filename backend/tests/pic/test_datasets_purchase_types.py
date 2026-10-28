"""D2 purchase types (BP §22, P08) on AXN, June 2027: expense receipt-less / 3-way, capital asset with capex committee and the
WBS hard stop, consignment with withdrawals and self-billing (ERS), subcontracting with component provision and consumption.

Objects are found by business keys the pack controls (supplier invoice numbers, supplier codes, purpose texts, lots), never
by numbers from shared ranges. Negative checks run in transactions that roll back.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.pic.db import tenant_tx
from app.pic.models import (
    Budget, GoodsReceipt, Invoice, InvoiceLine, Material, MaterialRequest, PoLine, PurchaseOrder, Requisition, Stock, StockMovement, Supplier,
    SupplierCategoryStatus, Task,
)
from app.pic.platform import clock
from app.pic.platform.errors import Problem
from app.pic.seed import axion
from app.pic.seed.axion import Scenario
from app.pic.seed.datasets import purchase_types as pack_module
from tests.pic.conftest import PASSWORD

L = 100_000 * 100


@pytest.fixture(scope="module")
def pack(database):
    from app.pic.seed import datasets
    result = datasets.apply_pack("purchase_types", PASSWORD)
    assert result[0]["status"] == "LOADED", result
    yield result[0]["summary"]
    clock.set_pinned(None)


@pytest.fixture(scope="module")
def sc(pack):
    return Scenario(pack_module.tenant_id_of("AXN"), "AXN", axion.DOMAIN, pack_module.ROLE_USER)


def _invoice(s, number: str) -> Invoice:
    return s.execute(select(Invoice).where(Invoice.supplier_invoice_no == number)).scalar_one()


def _po_of(s, invoice: Invoice) -> PurchaseOrder:
    line = s.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)).scalars().first()
    return s.get(PurchaseOrder, s.get(PoLine, line.po_line_id).po_id)


def _material(s, mpn: str) -> Material:
    return s.execute(select(Material).where(Material.mpn == mpn)).scalar_one()


def _pr(s, purpose_text: str) -> Requisition:
    return s.execute(select(Requisition).where(Requisition.purpose_text == purpose_text)).scalar_one()


def test_masters_through_f8_and_f9(sc, pack):
    with tenant_tx(sc.tenant_id) as s:
        for code, category in (("NPM201", "CAPEX-MACHINERY"), ("VFS202", "FASTENERS"), ("THT203", "HEAT-TREATMENT"),
                               ("KFP204", "STEEL-FORGINGS"), ("MOS205", "OFFICE-SAFETY")):
            supplier = s.execute(select(Supplier).where(Supplier.code == code)).scalar_one()
            assert supplier.status == "ACTIVE" and supplier.screening["outcome"] == "CLEAR"
            assert supplier.gstin_masked and supplier.state_code == "33"
            status = s.execute(select(SupplierCategoryStatus.status).where(SupplierCategoryStatus.supplier_id == supplier.id,
                                                                           SupplierCategoryStatus.category == category)).scalar_one()
            assert status == "QUALIFIED"
        for mpn in ("VFS-HFB-M10X30-109", "AXN-SH-2207-FB", "AXN-SH-2207-HT"):
            material = _material(s, mpn)
            request = s.execute(select(MaterialRequest).where(MaterialRequest.material_id == material.id)).scalar_one()
            assert request.status == "SYNCED_TO_ERP" and material.erp_synced
        shaft = _material(s, "AXN-SH-2207-HT")
        assert shaft.attributes["subcontractingBom"] == [{"material": _material(s, "AXN-SH-2207-FB").number, "qtyPer": "1"}]
    assert pack["counts"]["suppliers"] == 5 and pack["counts"]["purchaseOrders"] == 7


def test_expense_below_threshold_is_receiptless_and_matched_two_way(sc, pack):
    with tenant_tx(sc.tenant_id) as s:
        invoice = _invoice(s, "MOS/27-28/0142")
        po = _po_of(s, invoice)
        line = s.execute(select(PoLine).where(PoLine.po_id == po.id)).scalar_one()
        assert (line.purchase_type, line.gr_required, line.ir_required) == ("EXPENSE", False, True)
        assert invoice.match_type == "2WAY" and invoice.status == "POSTED" and invoice.first_pass_matched is True
        assert po.status == "INVOICED" and line.received_qty == 0 and line.invoiced_qty == 40
        assert not s.execute(select(GoodsReceipt.id).where(GoodsReceipt.po_id == po.id)).first()
    # The goods receipt the stores clerk tried while the PO was open was refused by P08 (receipt-less line).
    assert any(n.startswith("E1 goods receipt refused — P08") and "receipt-less" in n for n in pack["notes"])


def test_expense_above_threshold_needs_receipt_and_three_way(sc):
    with tenant_tx(sc.tenant_id) as s:
        invoice = _invoice(s, "MOS/27-28/0157")
        po = _po_of(s, invoice)
        line = s.execute(select(PoLine).where(PoLine.po_id == po.id)).scalar_one()
        assert line.gr_required and line.received_qty == 12 and invoice.match_type == "3WAY" and po.status == "INVOICED"
        budget = s.execute(select(Budget).where(Budget.cost_object_code == "4150", Budget.fiscal_year == "2027-28")).scalar_one()
        assert budget.consumed_minor == 40 * 42_000 + 12 * 980_000 and budget.committed_minor == 0


def test_capital_asset_capex_committee_asset_account_and_budget(sc):
    with tenant_tx(sc.tenant_id) as s:
        invoice = _invoice(s, "NPM/27-28/0057")
        po = _po_of(s, invoice)
        line = s.execute(select(PoLine).where(PoLine.po_id == po.id)).scalar_one()
        assert (line.purchase_type, line.account_assignment_type, line.account_assignment_code) == ("ASSET", "ASSET", "AST-P100-VMC-07")
        pr = s.get(Requisition, line.requisition_id)
        assert pr.approval_chain == ["COST_OBJECT_OWNER", "DEPT_HEAD", "PROCUREMENT_HEAD", "FINANCE_CONTROLLER", "CAPEX_COMMITTEE"]
        capex = s.execute(select(Task).where(Task.object_id == pr.id, Task.candidate_role == "CAPEX_COMMITTEE")).scalar_one()
        assert capex.status == "COMPLETED" and capex.decision == "APPROVE"
        assert pr.budget_result["checks"][0]["control"] == "HARD"
        budget = s.execute(select(Budget).where(Budget.cost_object_type == "ASSET", Budget.cost_object_code == "AST-P100-VMC-07")).scalar_one()
        assert budget.consumed_minor == 4_650_000_00 and budget.committed_minor == 0
        assert invoice.match_type == "3WAY" and po.status == "INVOICED" and line.received_qty == 1
        # A capital asset moves no stock: the receipt is valuated to the asset, not to inventory.
        gr = s.execute(select(GoodsReceipt).where(GoodsReceipt.po_id == po.id)).scalar_one()
        assert not s.execute(select(StockMovement.id).where(StockMovement.reference_id == gr.id)).first()


def test_wbs_hard_stop_then_rescoped_requisition_is_ordered(sc, pack, client, login):
    with tenant_tx(sc.tenant_id) as s:
        pr = _pr(s, "Line 4 cell automation")
        assert pr.total_minor == 2_260_000_00 and pr.status == "ORDERED" and "CAPEX_COMMITTEE" in pr.approval_chain
        budget = s.execute(select(Budget).where(Budget.cost_object_type == "WBS", Budget.cost_object_code == "CX-2728-04")).scalar_one()
        assert budget.committed_minor == 2_260_000_00 and budget.control == "HARD"
    assert any("BUDGET_EXCEEDED" in n for n in pack["notes"])
    clock.set_pinned(axion.at(date(2027, 6, 30), 15))  # FY 2027-28, the budgets' year
    # The remaining ₹2.4 L of the WBS element cannot take another ₹3 L: hard stop, no justification possible.
    body = {"origin": "MANUAL", "purpose_code": "CAPEX", "plant": "P100", "lines": [
        {"item_type": "FREE_TEXT", "purchase_type": "ASSET", "description": "Chip conveyor for Line 4 cell", "material_group": "AUTOMATION",
         "category": "CAPEX-MACHINERY", "qty": "1", "uom": "EA", "price_est_minor": 3 * L, "account_assignment_type": "WBS",
         "account_assignment_code": "CX-2728-04", "need_date": "2027-09-30", "quotes_attached": 3}]}
    created = client.post("/v1/requisitions", json=body, headers=login("requester"))
    assert created.status_code == 201, created.text
    submitted = client.post(f"/v1/requisitions/{created.json()['number']}/submit", json={"justification": "urgent"}, headers=login("requester"))
    assert submitted.status_code == 422 and submitted.json()["code"] == "BUDGET_EXCEEDED"
    # BP §22: a capital asset is assigned to an asset or a WBS element, never to a cost centre.
    wrong = {**body, "lines": [{**body["lines"][0], "account_assignment_type": "COST_CENTER", "account_assignment_code": "4150",
                                "price_est_minor": 1 * L}]}
    created = client.post("/v1/requisitions", json=wrong, headers=login("requester"))
    submitted = client.post(f"/v1/requisitions/{created.json()['number']}/submit", json={}, headers=login("requester"))
    assert submitted.status_code == 422 and "asset or a WBS element" in submitted.json()["detail"]
    clock.set_pinned(None)


def test_consignment_receipt_withdrawals_and_ers(sc):
    from app.pic.services import payables, receiving
    with tenant_tx(sc.tenant_id) as s:
        bolt = _material(s, "VFS-HFB-M10X30-109")
        stock = {r.stock_type: r.qty for r in s.execute(select(Stock).where(Stock.material_id == bolt.id, Stock.batch == "VFS-2706-0417")).scalars()}
        assert stock == {"CONSIGNMENT": Decimal(4500), "UNRESTRICTED": Decimal(15500)}
        moves = s.execute(select(StockMovement.movement_type, func.count(), func.sum(StockMovement.qty)).where(
            StockMovement.material_id == bolt.id, StockMovement.stock_type == "CONSIGNMENT").group_by(StockMovement.movement_type)).all()
        assert {m: (n, q) for m, n, q in moves} == {"101": (1, Decimal(20000)), "411K": (3, Decimal(-15500))}
        ers = s.execute(select(Invoice).where(Invoice.channel == "ERS", Invoice.supplier_id == s.execute(
            select(Supplier.id).where(Supplier.code == "VFS202")).scalar_one())).scalar_one()
        assert ers.match_type == "ERS" and ers.status == "POSTED" and ers.net_minor == 15500 * 640 and ers.tax_minor == 15500 * 640 * 18 // 100
        po = _po_of(s, ers)
        line = s.execute(select(PoLine).where(PoLine.po_id == po.id)).scalar_one()
        assert (line.ers, line.ir_required, line.received_qty, line.invoiced_qty) == (True, False, 20000, 15500)
        assert po.status == "RECEIVED"  # 4,500 still supplier-owned: not settled, not a liability
        assert receiving.consignment_withdrawn(s, [line.id]) == {line.id: Decimal(15500)}
        assert not [r for r in payables.grir(s) if r["po"] == po.number]  # nothing accrued: withdrawn = settled
        po_no, bolt_no = po.number, bolt.number
    # The supplier cannot invoice a consignment line; self-billing settles withdrawals.
    with pytest.raises(Problem) as exc:
        with sc.act("vmi@vfs202.example", clock.now()) as s:
            payables.capture(s, supplier="VFS202", supplier_invoice_no="VFS/27-28/9999", invoice_date=date(2027, 6, 30), channel="PORTAL",
                             lines=[{"po": po_no, "po_line": 10, "qty": "100", "unit_price": "6.40", "gst_rate": "18"}])
    assert exc.value.rule_ref == "P08" and "self-billing" in exc.value.detail
    with pytest.raises(Problem) as exc:
        with sc.act("ap.clerk", clock.now()) as s:
            payables.settle_consignment(s, supplier="VFS202", period_to=date(2027, 6, 30))
    assert "Nothing to settle" in exc.value.detail
    with pytest.raises(Problem) as exc:
        with sc.act("receiver", clock.now()) as s:
            receiving.withdraw_consignment(s, material=bolt_no, plant="P100", qty="5000", usage_ref="PL-TEST-1", purpose="TRANSFER")
    assert exc.value.code == "CONSIGNMENT_STOCK_SHORT"


def test_subcontracting_components_provided_and_consumed(sc, pack, client, login):
    with tenant_tx(sc.tenant_id) as s:
        invoice = _invoice(s, "THT/27-28/0311")
        po = _po_of(s, invoice)
        blank, shaft = _material(s, "AXN-SH-2207-FB"), _material(s, "AXN-SH-2207-HT")
        line = s.execute(select(PoLine).where(PoLine.po_id == po.id)).scalar_one()
        assert line.purchase_type == "SUBCONTRACTING" and line.material_id == shaft.id and line.received_qty == 1200
        components = po.inherited["components"]["10"]
        assert components[0]["material"] == blank.number and Decimal(components[0]["qty"]) == 1200
        moves = {m: q for m, q in s.execute(select(StockMovement.movement_type, func.sum(StockMovement.qty)).where(
            StockMovement.material_id == blank.id, StockMovement.stock_type == "SUBCONTRACTOR").group_by(StockMovement.movement_type)).all()}
        assert moves == {"541": Decimal(1200), "543": Decimal(-1200)}
        stock = {(r.storage_location, r.stock_type): r.qty for r in s.execute(select(Stock).where(Stock.material_id == blank.id)).scalars()}
        assert stock == {("0001", "UNRESTRICTED"): Decimal(800), ("THT203", "SUBCONTRACTOR"): Decimal(0)}
        assert sum(r.qty for r in s.execute(select(Stock).where(Stock.material_id == shaft.id)).scalars()) == 1200
        assert invoice.match_type == "3WAY" and po.status == "INVOICED"
        po_no = po.number
    assert any("COMPONENTS_MISSING" in n for n in pack["notes"])
    view = client.get(f"/v1/purchase-orders/{po_no}/components", headers=login("buyer")).json()
    assert view["lines"][0]["components"][0]["qtyPer"] == "1" and view["atSubcontractor"] == []  # every blank provided was consumed


def test_special_stock_api(sc, client, login):
    with tenant_tx(sc.tenant_id) as s:
        bolt = _material(s, "VFS-HFB-M10X30-109").number
    clock.set_pinned(axion.at(date(2027, 6, 30), 16))
    trace = client.get(f"/v1/lots/{bolt}/VFS-2706-0417/trace", headers=login("buyer"))
    assert trace.status_code == 200, trace.text
    body = trace.json()
    assert body["suppliers"] == ["VFS202"] and body["receipts"][0]["purchaseType"] == "CONSIGNMENT"
    assert sorted(u["usageRef"] for u in body["usage"]) == ["PL-P100-270615-03", "PL-P100-270621-01", "PL-P100-270628-02"]
    short = client.post("/v1/consignment/withdrawals", json={"material": bolt, "plant": "P100", "qty": "999999", "usage_ref": "PL-API-1",
                                                             "purpose": "TRANSFER"}, headers=login("receiver"))
    assert short.status_code == 422 and short.json()["code"] == "CONSIGNMENT_STOCK_SHORT"
    nothing = client.post("/v1/consignment/settlements", json={"supplier": "VFS202", "period_to": "2027-06-30"}, headers=login("ap.clerk"))
    assert nothing.status_code == 422
    assert client.get(f"/v1/lots/{bolt}/NO-SUCH-LOT/trace", headers=login("buyer")).status_code == 404
    clock.set_pinned(None)


def test_second_apply_is_idempotent(pack):
    from app.pic.seed import datasets
    assert datasets.apply_pack("purchase_types", PASSWORD)[0]["status"] == "ALREADY_LOADED"
