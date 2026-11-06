"""Tests for mock SAP S/4HANA production delta extracts and live inbound ERP sync (Technical Document §12.1 & §12.4)."""
import json
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import (
    AuditEvent, BankChangeRequest, CostObject, Invoice, Material, Plant, PoLine, PurchaseOrder, Stock, StockMovement,
    Supplier, SupplierBankAccount, SupplierMasterChange, Tenant,
)
from app.pic.platform import crypto
from app.pic.services import erp_sync, master_changes
from app.pic.tools import erp_delta_mock


def _gstin(pan: str, state="33", entity="1") -> str:
    first14 = f"{state}{pan}{entity}Z"
    return first14 + master_changes.gstin_check_char(first14)


@pytest.fixture(scope="module")
def delta_tenant(database):
    """An isolated tenant seeded with company 1000, plants 1100, 1200, 1300, baseline vendor & material."""
    from app.pic.seed import reference
    tenant_id = reference.create_tenant("DLT", "Delta Inbound Sync Test Ltd")
    reference.bootstrap(
        tenant_id,
        company=("1000", "Delta Inbound Sync Test Ltd", _gstin("AAACD9999K")),
        plants=[("1100", "Hosur Plant", "33"), ("1200", "Oragadam Plant", "33"), ("1300", "Bidadi Plant", "29")],
        cost_objects=[("COST_CENTER", "CC110", "Production Hosur")],
    )

    # Seed baseline suppliers 100001, 100003, 100008
    with tenant_tx(tenant_id) as s:
        s1 = Supplier(
            tenant_id=tenant_id, code="100001", legal_name="Vaigai Diecast Industries Pvt Ltd", status="ACTIVE",
            gstin_enc=crypto.encrypt(tenant_id, "gstin", "29HWFCV2767U1ZP"),
            gstin_masked=crypto.mask("29HWFCV2767U1ZP"),
            gstin_hash=crypto.blind_index(tenant_id, "29HWFCV2767U1ZP"),
            pan_hash=crypto.blind_index(tenant_id, "HWFCV2767U"),
            state_code="29", country="IN", payment_terms="N15", contact_email="sales@vaigai.example",
            address={"city": "Bidadi"},
        )
        s3 = Supplier(
            tenant_id=tenant_id, code="100003", legal_name="Vetri Alloy Castings Pvt Ltd", status="ACTIVE",
            gstin_enc=crypto.encrypt(tenant_id, "gstin", "33XGECV2962T1ZN"),
            gstin_masked=crypto.mask("33XGECV2962T1ZN"),
            gstin_hash=crypto.blind_index(tenant_id, "33XGECV2962T1ZN"),
            pan_hash=crypto.blind_index(tenant_id, "XGECV2962T"),
            state_code="33", country="IN", payment_terms="N15", contact_email="sales@vetri.example",
            address={"city": "Ranipet"},
        )
        s8 = Supplier(
            tenant_id=tenant_id, code="100008", legal_name="Vaigai Pressure Diecasters Pvt Ltd", status="ACTIVE",
            gstin_enc=crypto.encrypt(tenant_id, "gstin", "33JVMCV1188M1ZC"),
            gstin_masked=crypto.mask("33JVMCV1188M1ZC"),
            gstin_hash=crypto.blind_index(tenant_id, "33JVMCV1188M1ZC"),
            pan_hash=crypto.blind_index(tenant_id, "JVMCV1188M"),
            state_code="33", country="IN", payment_terms="N45", contact_email="sales@vaigaipressure.example",
            address={"city": "Tiruchirappalli"},
        )
        s.add_all([s1, s3, s8])
        s.flush()

        # Seed bank account for 100008
        s.add(SupplierBankAccount(
            tenant_id=tenant_id, supplier_id=s8.id,
            account_enc=crypto.encrypt(tenant_id, "bank", "20135475692295"),
            account_masked=crypto.mask("20135475692295"),
            ifsc="ICIC0K30004", holder_name="Vaigai Pressure Diecasters Pvt Ltd", active=True,
        ))

        # Seed baseline material 11000001
        m1 = Material(
            tenant_id=tenant_id, number="11000001", description="Special Alloy Steel Round Bar 32mm",
            type="STOCK", material_group="RM-STEEL", category="RAW-MATERIALS", base_uom="KG", hsn_code="722830",
            gst_rate=Decimal("18"), standard_price_minor=8910, status="ACTIVE",
        )
        s.add(m1)
        s.flush()

        # Seed baseline open PO 4500010041
        po = PurchaseOrder(
            tenant_id=tenant_id, number="PO-DLT-10041", version=1, supplier_id=s1.id, company_code="1000",
            purch_org="PO10", plant="1100", status="RELEASED", purpose_code="DIRECT", payment_terms="N30",
            rule_set_version="v1", erp_doc_no="4500010041", currency="INR", total_minor=450000,
        )
        s.add(po)
        s.flush()
        s.add(PoLine(
            tenant_id=tenant_id, po_id=po.id, line_no=10, item_type="MATERIAL", purchase_type="STANDARD",
            material_id=m1.id, description="Steel Bar", material_group="RM-STEEL", qty=Decimal("100"),
            uom="KG", unit_price_minor=4500, net_minor=450000, gst_rate=Decimal("18"), hsn_code="722830",
            need_date=date(2026, 11, 15), plant="1100", gr_required=True, price_source="MANUAL",
        ))

        # Seed baseline posted invoice 5105602634
        inv = Invoice(
            tenant_id=tenant_id, number="INV-DLT-2634", supplier_invoice_no="VDI/26-27/0032", fiscal_year="2026-27",
            company_code="1000", supplier_id=s1.id, invoice_date=date(2026, 10, 17), channel="PORTAL",
            currency="INR", net_minor=32816339, tax_minor=5906941, gross_minor=38723280,
            status="POSTED", payment_status="UNPAID", erp_doc_no="5105602634",
        )
        s.add(inv)

    return tenant_id


def test_erp_delta_mock_files_generated_and_manifest_valid():
    manifest = erp_delta_mock.generate()
    assert manifest["extractType"] == "DELTA"
    assert manifest["extractId"] == "KAC-S4H-20261102-DELTA"
    assert len(manifest["files"]) == 16

    out_dir = erp_delta_mock.OUT_DIR
    assert (out_dir / "MANIFEST.json").exists()
    assert (out_dir / "README.md").exists()
    assert (out_dir / "VENDORS" / "LFA1.csv").exists()
    assert (out_dir / "MATERIALS" / "MARA.csv").exists()
    assert (out_dir / "STOCK" / "STOCK.csv").exists()
    assert (out_dir / "OPEN_POS" / "OPEN_POS.json").exists()
    assert (out_dir / "PAYMENT_STATUS" / "PAYMENT_STATUS.csv").exists()
    assert (out_dir / "PLANNED_ORDERS" / "PLANNED_ORDERS.csv").exists()
    assert (out_dir / "PLANTS" / "PLANTS.csv").exists()
    assert (out_dir / "COST_OBJECTS" / "COST_OBJECTS.csv").exists()


def test_stage_drop_and_read_drop(tmp_path):
    drop_dir = tmp_path / "drop"
    erp_delta_mock.stage_drop(drop_dir)

    for kind in ("VENDORS", "MATERIALS", "STOCK", "OPEN_POS", "PAYMENT_STATUS", "PLANNED_ORDERS", "PLANTS", "COST_OBJECTS"):
        res = erp_sync.read_drop(kind, drop_dir)
        assert res is not None
        assert res.pulled > 0
        assert res.kind == kind


def test_erp_delta_ingestion_end_to_end(delta_tenant, tmp_path):
    """Execute live inbound delta sync on all 8 kinds against a staged mock drop folder."""
    drop_dir = tmp_path / "run_drop"
    erp_delta_mock.stage_drop(drop_dir)

    # 1. PLANTS
    res_plant = erp_sync.run(delta_tenant, "PLANTS", directory=drop_dir, mode="ON_DEMAND")
    assert res_plant["status"] == "COMPLETED"
    assert res_plant["counts"]["new"] == 1       # Plant 1400 Coimbatore
    assert res_plant["counts"]["updated"] == 1   # Plant 1100 Hosur description updated

    # 2. COST_OBJECTS
    res_cost = erp_sync.run(delta_tenant, "COST_OBJECTS", directory=drop_dir, mode="ON_DEMAND")
    assert res_cost["status"] == "COMPLETED"
    assert res_cost["counts"]["new"] == 2        # CC140 and W-2026-EXP

    # 3. VENDORS
    res_vend = erp_sync.run(delta_tenant, "VENDORS", directory=drop_dir, mode="ON_DEMAND")
    assert res_vend["status"] == "PARTIAL"       # Sensitive change on 100008 routes to MDM-04
    assert res_vend["counts"]["new"] == 2        # 200350 and 200351 onboarded
    assert res_vend["counts"]["updated"] >= 1    # 100001 name/address updated
    assert res_vend["counts"]["sensitive"] == 2  # Tax & bank change routed to MDM-04

    with tenant_tx(delta_tenant) as s:
        # Check new vendors onboarded
        sup_new = s.execute(select(Supplier).where(Supplier.code == "200350")).scalar_one_or_none()
        assert sup_new is not None and "Coimbatore" in sup_new.legal_name

        # Check existing updated vendor
        sup_upd = s.execute(select(Supplier).where(Supplier.code == "100001")).scalar_one()
        assert "Technologies" in sup_upd.legal_name

        # Check sensitive change routed to MDM-04
        sup_sens = s.execute(select(Supplier).where(Supplier.code == "100008")).scalar_one()
        mc = s.execute(select(SupplierMasterChange).where(SupplierMasterChange.supplier_id == sup_sens.id)).scalars().first()
        assert mc is not None and mc.status == "IN_APPROVAL"
        bc = s.execute(select(BankChangeRequest).where(BankChangeRequest.supplier_id == sup_sens.id)).scalars().first()
        assert bc is not None and bc.status == "PENDING_CALLBACK"

    # 4. MATERIALS
    res_mat = erp_sync.run(delta_tenant, "MATERIALS", directory=drop_dir, mode="ON_DEMAND")
    assert res_mat["status"] == "COMPLETED"
    assert res_mat["counts"]["new"] == 2        # 11000901 and 11000902
    assert res_mat["counts"]["updated"] == 1    # 11000001 price updated in MBEW

    with tenant_tx(delta_tenant) as s:
        mat_upd = s.execute(select(Material).where(Material.number == "11000001")).scalar_one()
        assert mat_upd.standard_price_minor == 9450  # Updated from 89.10 to 94.50

        mat_new = s.execute(select(Material).where(Material.number == "11000901")).scalar_one_or_none()
        assert mat_new is not None and mat_new.category == "FASTENERS"

    # 5. STOCK
    res_stk = erp_sync.run(delta_tenant, "STOCK", directory=drop_dir, mode="ON_DEMAND")
    assert res_stk["status"] in ("COMPLETED", "PARTIAL")
    assert res_stk["counts"]["new"] >= 1

    with tenant_tx(delta_tenant) as s:
        stk_rows = s.execute(select(Stock).where(Stock.plant == "1100")).scalars().all()
        assert len(stk_rows) >= 1
        mv_rows = s.execute(select(StockMovement).where(StockMovement.reference_type == "ERP_SYNC")).scalars().all()
        assert len(mv_rows) >= 1

    # 6. OPEN_POS
    res_po = erp_sync.run(delta_tenant, "OPEN_POS", directory=drop_dir, mode="ON_DEMAND")
    assert res_po["status"] in ("COMPLETED", "PARTIAL")
    # PO 4500099991 is not in PIC, generating a reconciliation exception
    assert any(r["reason"] == "PO_UNKNOWN_IN_PIC" for r in res_po["rejects"])

    # 7. PAYMENT_STATUS
    res_pay = erp_sync.run(delta_tenant, "PAYMENT_STATUS", directory=drop_dir, mode="ON_DEMAND")
    assert res_pay["status"] in ("COMPLETED", "PARTIAL")
    assert res_pay["counts"]["updated"] >= 1     # Invoice 5105602634 marked PAID

    with tenant_tx(delta_tenant) as s:
        inv_cleared = s.execute(select(Invoice).where(Invoice.erp_doc_no == "5105602634")).scalar_one()
        assert inv_cleared.status == "PAID"
        assert inv_cleared.payment_status == "PAID"

    # 8. PLANNED_ORDERS
    res_plan = erp_sync.run(delta_tenant, "PLANNED_ORDERS", directory=drop_dir, mode="ON_DEMAND")
    assert res_plan["status"] in ("COMPLETED", "PARTIAL")
    assert res_plan["counts"]["new"] >= 1


def test_dataset_pack_erp_delta_kac_metadata():
    from app.pic.seed.datasets import erp_delta_kac
    assert erp_delta_kac.KEY == "erp-delta-kac"
    assert erp_delta_kac.READY is True
    assert erp_delta_kac.TENANTS == ("KAC",)
    assert "erp-client-kac" in erp_delta_kac.REQUIRES

