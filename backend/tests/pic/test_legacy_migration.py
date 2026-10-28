"""Legacy supplier_twin migration (§15): reconciliation, control findings, live continuation, tenant isolation,
plus the AXN cases that fill the screening list, source list and PO versions."""
import pytest
from sqlalchemy import select

from tests.pic.conftest import PASSWORD


@pytest.fixture(scope="module")
def migrated(database):
    from app.pic.seed import legacy
    from app.pic.tools.legacy_extract import load
    reports = legacy.migrate(load(), PASSWORD)
    return {r["tenant"]: r for r in reports}


def _findings(report, code):
    return [f for f in report["findings"] if f["code"] == code]


def test_every_count_and_value_reconciles(migrated):
    assert set(migrated) == {"GMC", "DBY"}
    for report in migrated.values():
        assert all(c["ok"] for c in report["counts"]), report["counts"]
        assert all(v["ok"] for v in report["values"]), report["values"]
    total = lambda key: sum(next(c["pic"] for c in r["counts"] if c["object"] == key) for r in migrated.values())  # noqa: E731
    # Every legacy purchase order, invoice and payment lands in exactly one PIC tenant.
    assert (total("Purchase orders"), total("Invoices"), total("Payments")) == (11, 29, 15)


def test_control_findings_on_legacy_data(migrated):
    overpaid = {f["refs"][0]: f["detail"] for f in _findings(migrated["DBY"], "OVERPAID_PO")}
    assert set(overpaid) == {"PO-2025-00089", "PO-2025-00123", "PO-2025-00045"}
    assert "excess 162,500.00" in overpaid["PO-2025-00089"]
    assert [f["refs"] for f in _findings(migrated["GMC"], "PAID_BEFORE_APPROVAL")] == [["LEG-F089138D", "PO-2026-6488"]]
    assert {f["refs"][0] for f in _findings(migrated["DBY"], "CLOSED_WITHOUT_RECEIPT")} == {"PO-2026-58A9", "PO-2026-AE99"}
    assert _findings(migrated["DBY"], "PAID_DISPUTED_INVOICE")
    # Test postings are migrated (the ledger must reconcile) but flagged.
    assert any("GRN-E2E-TEST" in f["refs"] for f in _findings(migrated["DBY"], "TEST_DATA"))


def test_pending_invoices_go_through_the_pic_match(migrated):
    gmc = {i["invoice"]: i for i in migrated["GMC"]["live"]["invoices"]}
    assert {i["exceptions"][0] for i in gmc.values()} == {"MISSING_GR"}
    dby = migrated["DBY"]["live"]["invoices"]
    assert len(dby) == 11 and all(i["exceptions"] == ["DUPLICATE"] for i in dby)


def test_open_items_continue_in_live_workflows(migrated, client, login):
    headers = login("buyer.lead@gmc.example", "GMC")
    po = client.get("/v1/purchase-orders/PO-2026-6488", headers=headers).json()
    assert po["status"] == "IN_APPROVAL" and po["risk_score"] >= 58
    assert migrated["GMC"]["openTasks"] == {"PO_APPROVAL": 1}
    mrp = migrated["DBY"]["live"]["mrp"]
    assert mrp["plannedOrders"] == 1 and "IN_APPROVAL" in mrp["converted"]
    assert migrated["DBY"]["mrpExceptions"] == {"BELOW_SAFETY": 2}
    assert migrated["DBY"]["live"]["materialRequests"][0].endswith("IN_STEWARDSHIP")
    assert migrated["DBY"]["live"]["sourcingEvents"] == ["RFQ-2026-092: 2 quotes, unit price 280.00 → 265.00"]


def test_migrated_tenants_are_isolated(migrated, client, login):
    gmc = {p["number"] for p in client.get("/v1/purchase-orders?limit=100", headers=login("buyer@gmc.example", "GMC")).json()["items"]}
    dby = {p["number"] for p in client.get("/v1/purchase-orders?limit=100", headers=login("buyer@dby.example", "DBY")).json()["items"]}
    assert gmc == {"PO-2026-7022", "PO-2026-2473", "PO-2026-8183", "PO-2026-1175", "PO-2026-6488"}
    assert not gmc & dby and "PO-77410" not in gmc | dby
    # A legacy supplier user signs in to the portal of the buyer it served and sees only its own orders.
    mine = client.get("/v1/purchase-orders", headers=login("carriedavis@example.net", "GMC")).json()["items"]
    assert [p["number"] for p in mine] == ["PO-2026-7022"]


def test_migration_is_idempotent_and_audited(migrated):
    from app.pic.db import system_tx, tenant_tx
    from app.pic.models import Tenant
    from app.pic.platform.audit import verify_chain
    from app.pic.seed import legacy
    from app.pic.tools.legacy_extract import load
    again = legacy.migrate(load(), PASSWORD)
    assert all("skipped" in r for r in again)
    with system_tx() as s:
        tenants = {t.code: t.id for t in s.execute(select(Tenant)).scalars()}
    for code in ("GMC", "DBY"):
        with tenant_tx(tenants[code]) as s:
            assert verify_chain(s)["valid"]


def test_screening_list_blocks_sanctioned_name(login, client):
    supplier = client.get("/v1/suppliers/ZAT006", headers=login("supplier.manager")).json()
    assert supplier["status"] == "BLOCKED"


def test_change_order_and_supplier_change_request_create_versions():
    from app.pic.db import system_tx, tenant_tx
    from app.pic.models import PoChangeRequest, PoVersion, PurchaseOrder, SourceList, Tenant
    with system_tx() as s:
        axn = s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()
    with tenant_tx(axn) as s:
        po = s.execute(select(PurchaseOrder).where(PurchaseOrder.number == "PO-77417")).scalar_one()
        # v2: buyer change order (case 7); v3: Trichy Forge's change request accepted by the buyer (case 8).
        assert (po.version, po.status) == (3, "CONFIRMED")
        assert po.inherited["sourceDetermination"]
        versions = s.execute(select(PoVersion).where(PoVersion.po_id == po.id).order_by(PoVersion.version)).scalars().all()
        assert [v.version for v in versions] == [1, 2] and "OEM pull-in" in versions[0].change_reason
        pcr = s.execute(select(PoChangeRequest).where(PoChangeRequest.po_id == po.id)).scalar_one()
        assert (pcr.origin, pcr.status, pcr.result_version) == ("SUPPLIER", "ACCEPTED", 3) and "Furnace" in versions[1].change_reason
        assert len(s.execute(select(SourceList)).scalars().all()) == 2
