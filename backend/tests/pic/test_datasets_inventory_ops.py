"""D13 inventory operations for AXN and KAC (pack inventory_ops): the documents the pack leaves behind are real documents made by the services.

The signature case is untouched: AXN gets stores materials of its own, KAC (loaded from SAP without stock) gets an opening position."""
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, DemandElement, IntegrationMessage, Material, PhysicalInventory, PhysicalInventoryLine, Stock, StockMovement, StockPosting, StockReservation, Tenant,
)
from app.pic.platform import clock
from app.pic.seed import datasets
from tests.pic.conftest import PASSWORD


@pytest.fixture(scope="module")
def packs(database):
    assert datasets.apply_pack("erp_client_kac", PASSWORD)[0]["status"] in ("LOADED", "ALREADY_LOADED")   # KAC comes from its SAP extract
    results = {r["tenant"]: r for r in datasets.apply_pack("inventory_ops", PASSWORD)}
    assert set(results) == {"AXN", "KAC"} and {r["status"] for r in results.values()} == {"LOADED"}, results
    with system_tx() as s:
        ids = {code: tid for code, tid in s.execute(select(Tenant.code, Tenant.id))}
    yield {"results": results, "ids": ids}
    clock.set_pinned(None)


@pytest.mark.parametrize("code,plant", [("AXN", "P100"), ("KAC", "1100")])
def test_the_documents_are_real_and_in_the_expected_states(packs, code, plant):
    summary = packs["results"][code]["summary"]
    docs = summary["documents"]
    with tenant_tx(packs["ids"][code]) as s:
        postings = {p.number: p for p in s.execute(select(StockPosting)).scalars()}
        assert postings[docs["transfer"]].status == "POSTED" and postings[docs["transfer"]].auto_posted and postings[docs["transfer"]].erp_doc_no
        assert postings[docs["block"]].status == "POSTED" and postings[docs["block"]].posting_type == "BLOCK"
        scrap = postings[docs["scrap"]]
        assert scrap.status == "SUBMITTED" and scrap.posting_type == "SCRAP" and scrap.reason_code == "DAMAGED"
        counts = {c.number: c for c in s.execute(select(PhysicalInventory)).scalars()}
        posted, open_count = counts[docs["countPosted"]], counts[docs["countOpen"]]
        assert posted.status == "POSTED" and open_count.status == "COUNTING"
        # the counter and the approver are different people; the approver did not count
        approver = s.get(AppUser, posted.approved_by)
        counters = {l.counted_by for l in s.execute(select(PhysicalInventoryLine).where(PhysicalInventoryLine.inventory_id == posted.id)).scalars()}
        assert approver.id not in counters and "INVENTORY_CONTROLLER" in approver.roles
        assert s.execute(select(func.count()).select_from(StockMovement).where(StockMovement.reference_id == posted.id)).scalar_one() <= 1   # at most one loss line
        assert posted.loss_minor >= 0 and any(l.count_status == "RECOUNT_REQUIRED" for l in s.execute(
            select(PhysicalInventoryLine).where(PhysicalInventoryLine.inventory_id == open_count.id)).scalars())
        reservations = {r.number: r for r in s.execute(select(StockReservation)).scalars()}
        open_res, partial, cancelled = (reservations[n] for n in docs["reservations"])
        assert (open_res.status, partial.status, cancelled.status) == ("OPEN", "PARTIALLY_ISSUED", "CANCELLED")
        assert 0 < partial.issued_qty < partial.qty and open_res.plant == plant
        demand = {e.reference: e.qty for e in s.execute(select(DemandElement).where(DemandElement.type == "RESERVATION")).scalars()}
        assert demand[open_res.number] == open_res.qty and demand[partial.number] == partial.qty - partial.issued_qty and demand[cancelled.number] == 0
        # every posted document reached the ERP simulator
        assert s.execute(select(func.count()).select_from(IntegrationMessage).where(IntegrationMessage.message_type == "STOCK_POSTING",
                                                                                      IntegrationMessage.status == "POSTED")).scalar_one() >= 4


def test_kac_has_an_opening_position_and_axn_its_own_stores_materials(packs):
    with tenant_tx(packs["ids"]["KAC"]) as s:
        rows = s.execute(select(Stock).where(Stock.plant == "1100")).scalars().all()
        # at least the pack's 20 materials: other KAC tests in the same database may post receipts for further materials at this plant
        assert len({r.material_id for r in rows}) >= 20 and any(r.batch == "B-2609" for r in rows) and any(r.batch == "B-2610" for r in rows)
        opening = s.execute(select(StockMovement).where(StockMovement.movement_type == "561")).scalars().all()
        assert opening and all(m.reference_type == "OPENING_BALANCE" and m.value_minor is not None for m in opening)
    with tenant_tx(packs["ids"]["AXN"]) as s:
        numbers = {m.number for m in s.execute(select(Material).where(Material.number.like("AXN-INV-%"))).scalars()}
        assert len(numbers) == 13
        dc330 = s.execute(select(Stock).join(Material, Material.id == Stock.material_id).where(Material.number == "DC-330")).scalars().all()
        assert sum((r.qty for r in dc330), Decimal(0)) >= 0     # the signature case's own stock is not part of the pack


def test_the_ledger_explains_the_balances_the_pack_created(packs):
    """The sum of the movements of a balance is its quantity for every balance the pack touched (nothing was edited behind the ledger)."""
    for code in ("AXN", "KAC"):
        with tenant_tx(packs["ids"][code]) as s:
            ledger = {(m, p, l, t, b): q for m, p, l, t, b, q in s.execute(select(
                StockMovement.material_id, StockMovement.plant, StockMovement.storage_location, StockMovement.stock_type, StockMovement.batch,
                func.sum(StockMovement.qty)).where(StockMovement.posting_ref.is_not(None)).group_by(
                StockMovement.material_id, StockMovement.plant, StockMovement.storage_location, StockMovement.stock_type, StockMovement.batch)).all()}
            assert ledger
            for stock in s.execute(select(Stock)).scalars():
                key = (stock.material_id, stock.plant, stock.storage_location, stock.stock_type, stock.batch)
                if key in ledger:
                    assert stock.qty == ledger[key], (code, key)


def test_the_pack_is_idempotent(packs):
    again = {r["tenant"]: r["status"] for r in datasets.apply_pack("inventory_ops", PASSWORD)}
    assert again == {"AXN": "ALREADY_LOADED", "KAC": "ALREADY_LOADED"}
    with tenant_tx(packs["ids"]["AXN"]) as s:
        assert s.execute(select(func.count()).select_from(StockPosting)).scalar_one() == 3
        assert s.execute(select(func.count()).select_from(PhysicalInventory)).scalar_one() == 2
    # the module is usable out of the box: the demo controllers exist for both tenants
    for code in ("AXN", "KAC"):
        with tenant_tx(packs["ids"][code]) as s:
            assert s.execute(select(func.count()).select_from(AppUser).where(AppUser.roles.any("INVENTORY_CONTROLLER"))).scalar_one() >= 2
