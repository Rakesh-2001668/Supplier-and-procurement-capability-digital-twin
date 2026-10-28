"""D6 healthcare demo tenant HLT (BP §23): consignment implant KN-77, lot / expiry / serial at receipt, usage-triggered
replenishment, monthly self-billing and the recall trace of lot VOD-KN77-2610A.

Everything is looked up by business keys the pack controls (tenant HLT, supplier VOD001, MPN KN-77, lots, case references).
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AuditEvent, Contract, GrLine, Invoice, Material, PoLine, PurchaseOrder, Requisition, ReturnDelivery, RuleSet, Stock,
    StockMovement, Supplier, SupplierCategoryStatus, Tenant,
)
from app.pic.platform import clock
from app.pic.platform.errors import Problem
from app.pic.seed.axion import Scenario
from app.pic.seed.datasets import industry_healthcare as hc
from tests.pic.conftest import PASSWORD

LOT = hc.RECALLED_LOT


@pytest.fixture(scope="module")
def pack(database):
    from app.pic.seed import datasets
    result = datasets.apply_pack("industry_healthcare", PASSWORD)
    assert result[0]["status"] == "LOADED", result
    yield result[0]["summary"]
    clock.set_pinned(None)


@pytest.fixture(scope="module")
def sc(pack):
    with system_tx() as s:
        tenant = s.execute(select(Tenant).where(Tenant.code == "HLT")).scalar_one()
        assert tenant.industry_template == "HEALTHCARE"
        tenant_id = tenant.id
    return Scenario(tenant_id, "HLT", hc.DOMAIN, hc.ROLE_USER)


def _kn77(s) -> Material:
    return s.execute(select(Material).where(Material.mpn == "KN-77")).scalar_one()


def test_supplier_material_and_contract(sc, pack):
    with tenant_tx(sc.tenant_id) as s:
        supplier = s.execute(select(Supplier).where(Supplier.code == "VOD001")).scalar_one()
        status = s.execute(select(SupplierCategoryStatus.status).where(SupplierCategoryStatus.supplier_id == supplier.id,
                                                                       SupplierCategoryStatus.category == hc.CATEGORY)).scalar_one()
        assert supplier.status == "ACTIVE" and status == "QUALIFIED"
        rule = s.execute(select(RuleSet).where(RuleSet.key == "SUPPLIER-QUAL", RuleSet.category == hc.CATEGORY)).scalar_one()
        assert rule.body["mandatoryCertificates"][hc.CATEGORY] == ["ISO13485", "CDSCO_MFG_LICENCE"]
        kn77 = _kn77(s)
        assert kn77.hsn_code == "90213100" and kn77.gst_rate == hc.GST_RATE and kn77.erp_synced
        assert kn77.attributes["serialManaged"] and kn77.attributes["expiryManaged"] and kn77.attributes["minShelfLifeDays"] == 180
        contract = s.execute(select(Contract).where(Contract.supplier_id == supplier.id)).scalar_one()
        assert contract.status == "ACTIVE" and contract.type == "QUANTITY_CONTRACT" and contract.target_value_minor == 120 * hc.PRICE_MINOR
    assert pack["counts"]["surgicalCases"] == 5 and pack["keys"]["recalledLot"] == LOT


def test_every_implant_receipt_carries_lot_expiry_and_serials(sc):
    with tenant_tx(sc.tenant_id) as s:
        kn77 = _kn77(s)
        lines = s.execute(select(GrLine).where(GrLine.material_id == kn77.id)).scalars().all()
        assert len(lines) == 4 + 5 + 2  # opening (2 lots per hospital), five replenishments, two recall replacements
        for line in lines:
            assert line.batch.startswith("VOD-KN77-") and line.expiry is not None and len(line.serials) == int(line.qty)
            assert line.stock_type == "CONSIGNMENT" and line.storage_location == "OT01"
            assert line.expiry == date.fromisoformat(hc.LOTS[line.batch])
        serials = [x for line in lines for x in line.serials]
        assert len(serials) == len(set(serials)) == 18  # 10 opening + 5 replenishments + 3 recall replacements
        # par levels restored after every case and the recall: 6 in Chennai, 4 in Coimbatore, all supplier-owned
        on_hand = dict(s.execute(select(Stock.plant, func.sum(Stock.qty)).where(Stock.material_id == kn77.id, Stock.stock_type == "CONSIGNMENT")
                                 .group_by(Stock.plant)).all())
        assert on_hand == {"H100": Decimal(6), "H200": Decimal(4)}
        assert not s.execute(select(Stock.id).where(Stock.material_id == kn77.id, Stock.stock_type != "CONSIGNMENT", Stock.qty != 0)).first()


def test_usage_triggers_replenishment_po(sc):
    with tenant_tx(sc.tenant_id) as s:
        kn77 = _kn77(s)
        usage = s.execute(select(StockMovement).where(StockMovement.material_id == kn77.id, StockMovement.movement_type == "201K")).scalars().all()
        assert sorted(m.reference_ref for m in usage) == sorted(c[2] for c in hc.CASES) and all(m.qty == -1 for m in usage)
        for day_, plant, case, serial, new_lot, _ in hc.CASES:
            event = s.execute(select(AuditEvent).where(AuditEvent.action == "CONSIGNMENT_WITHDRAWN",
                                                       AuditEvent.after["usageRef"].astext == case)).scalar_one()
            assert event.after["serials"] == [serial] and event.after["costObject"] == hc.PLANTS[plant][3]
            pr = s.execute(select(Requisition).where(Requisition.origin_ref == case)).scalar_one()
            assert pr.purpose_code == "CONSIGNMENT_REPLENISHMENT" and pr.status == "ORDERED"
            po_line = s.execute(select(PoLine).where(PoLine.requisition_id == pr.id)).scalar_one()
            po = s.get(PurchaseOrder, po_line.po_id)
            assert po.touchless and po_line.purchase_type == "CONSIGNMENT" and po_line.price_source == "CONTRACT" and po_line.plant == plant
            gr_line = s.execute(select(GrLine).where(GrLine.po_line_id == po_line.id)).scalar_one()
            assert gr_line.batch == new_lot


def test_month_end_self_billing_settles_exactly_the_implants_used(sc):
    with tenant_tx(sc.tenant_id) as s:
        invoices = {i.number: i for i in s.execute(select(Invoice).where(Invoice.channel == "ERS")).scalars()}
        assert sorted(invoices) == ["ERS-VOD001-202612", "ERS-VOD001-202701", "ERS-VOD001-202702"]
        assert [invoices[n].net_minor for n in sorted(invoices)] == [2 * hc.PRICE_MINOR, 2 * hc.PRICE_MINOR, hc.PRICE_MINOR]
        assert all(i.match_type == "ERS" and i.tax_minor == i.net_minor * 5 // 100 for i in invoices.values())
        assert invoices["ERS-VOD001-202612"].status == invoices["ERS-VOD001-202701"].status == "PAID"
        assert invoices["ERS-VOD001-202702"].status == "POSTED" and invoices["ERS-VOD001-202702"].due_date == date(2027, 4, 14)
        # liability = withdrawn: the opening PO lines are settled for the five used implants only
        opening = s.execute(select(PoLine).where(PoLine.ers.is_(True), PoLine.qty == 6)).scalar_one()
        assert opening.received_qty == 6 and opening.invoiced_qty == 3


def test_recall_trace_and_quarantine(sc, client, login):
    with tenant_tx(sc.tenant_id) as s:
        kn77 = _kn77(s).number
        returns = s.execute(select(ReturnDelivery).where(ReturnDelivery.reason.like(f"RECALL {hc.NOTICE}%"))).scalars().all()
        assert sorted(r.qty for r in returns) == [1, 2] and all(r.replacement_required and not r.credit_note_expected for r in returns)
    clock.set_pinned(clock.at_ist(date(2027, 3, 31), 12))
    headers = login("quality.manager@tamravati.example", "HLT")
    trace = client.get(f"/v1/lots/{kn77}/{LOT}/trace", headers=headers)
    assert trace.status_code == 200, trace.text
    body = trace.json()
    assert body["recalled"] and body["suppliers"] == ["VOD001"] and body["receivedQty"] == "6"
    assert sorted((r["plant"], r["storageLocation"], int(Decimal(r["qty"]))) for r in body["receipts"]) == [("H100", "OT01", 4), ("H200", "OT01", 2)]
    assert sorted((u["usageRef"], u["serials"][0]) for u in body["usage"]) == [
        ("OT-H100-2612-0031", f"{LOT}-001"), ("OT-H100-2701-0026", f"{LOT}-002"), ("OT-H200-2612-0014", f"{LOT}-005")]
    assert body["onHand"] == [] and len(body["returns"]) == 2
    assert sorted(x for r in body["recalls"] for x in r["serials"]) == [f"{LOT}-003", f"{LOT}-004", f"{LOT}-006"]
    # A recalled lot cannot be used any more.
    used = client.post("/v1/consignment/withdrawals", json={"material": kn77, "plant": "H100", "qty": "1", "usage_ref": "OT-H100-TEST-0001",
                                                            "storage_location": "OT01", "serials": [f"{LOT}-003"], "cost_object": "COST_CENTER:6100"},
                       headers=login("ot.coordinator@tamravati.example", "HLT"))
    assert used.status_code == 422 and "not in consignment stock" in used.json()["detail"], used.text
    clock.set_pinned(None)


def test_lot_controls_at_receipt(sc):
    """RCV-LOT: lot, expiry and one serial per unit are mandatory for KN-77; expired or short-dated lots and repeated serials are refused."""
    from app.pic.services import receiving
    with sc.act("stores.chennai", clock.at_ist(date(2027, 3, 1), 10)) as s:
        kn77 = _kn77(s)
        line = PoLine(material_id=kn77.id, line_no=10, purchase_type="CONSIGNMENT")
        today = date(2027, 3, 1)
        cases = [
            (dict(batch="", expiry=date(2031, 1, 31), serials=["X-1"]), "batch"),
            (dict(batch="VOD-KN77-TEST", expiry=None, serials=["X-1"]), "expiry"),
            (dict(batch="VOD-KN77-TEST", expiry=date(2031, 1, 31), serials=[]), "serial"),
            (dict(batch="VOD-KN77-TEST", expiry=date(2027, 2, 28), serials=["X-1"]), "expired"),
            (dict(batch="VOD-KN77-TEST", expiry=date(2027, 6, 30), serials=["X-1"]), "shelf life"),
            (dict(batch="VOD-KN77-TEST", expiry=date(2031, 1, 31), serials=[f"{LOT}-001"]), "already received"),
        ]
        for kwargs, text in cases:
            with pytest.raises(Problem) as exc:
                receiving._check_lot(s, line, Decimal(1), posting_date=today, **kwargs)
            assert exc.value.rule_ref == "RCV-LOT" and text in exc.value.detail, (kwargs, exc.value.detail)
        receiving._check_lot(s, line, Decimal(1), "VOD-KN77-TEST", date(2031, 1, 31), ["VOD-KN77-TEST-001"], today)  # complete lot passes


def test_second_apply_is_idempotent(pack):
    from app.pic.seed import datasets
    assert datasets.apply_pack("industry_healthcare", PASSWORD)[0]["status"] == "ALREADY_LOADED"
