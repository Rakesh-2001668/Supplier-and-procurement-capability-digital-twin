"""D8 manufacturing controls on the Axion tenant (pack industry_manufacturing): Kanban cards, reorder-point planning, weekly buckets.

The signature case is untouched: the pack adds three materials of its own and plans only those."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import KanbanCard, Material, MrpRun, PlannedOrder, PlanningParameter, Requisition, Tenant
from app.pic.platform import clock
from app.pic.seed import datasets
from tests.pic.conftest import PASSWORD


@pytest.fixture(scope="module")
def mfg(database):
    result = datasets.apply_pack("industry_manufacturing", PASSWORD)
    assert result[0]["status"] == "LOADED", result
    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()
    yield {"tenant_id": tenant_id, "summary": result[0]["summary"]}
    clock.set_pinned(None)


def test_materials_cards_and_requisitions(mfg):
    summary = mfg["summary"]
    with tenant_tx(mfg["tenant_id"]) as s:
        types = {k: s.execute(select(Material.mrp_type).where(Material.number == n)).scalar_one() for k, n in summary["materials"].items()}
        assert types == {"washer": "KB", "tie": "VB", "gasket": "PW"}
        cards = s.execute(select(KanbanCard).order_by(KanbanCard.number)).scalars().all()
        assert [c.number for c in cards] == summary["cards"] and all(c.bin_qty == Decimal(5000) for c in cards)
        assert [c.status for c in cards] == ["REPLENISHING", "REPLENISHING", "FULL"]
        for card in cards[:2]:
            pr = s.get(Requisition, card.requisition_id)
            assert (pr.origin, pr.origin_ref, pr.purpose_code) == ("MRP", card.number, "KANBAN_REPLENISHMENT") and pr.status in ("APPROVED", "ORDERED")
        tie = s.execute(select(PlanningParameter)).scalar_one()
        assert (tie.reorder_point, tie.max_stock, tie.plant) == (Decimal(400), Decimal(2000), "P100")


def test_reorder_point_and_weekly_bucket_runs(mfg):
    summary = mfg["summary"]
    with tenant_tx(mfg["tenant_id"]) as s:
        tie = s.execute(select(Material).where(Material.number == summary["materials"]["tie"])).scalar_one()
        order = s.execute(select(PlannedOrder).where(PlannedOrder.material_id == tie.id)).scalar_one()
        assert (order.qty, order.status, order.release_date) == (Decimal(2000), "CONVERTED", date(2027, 7, 12)) and order.requisition_id
        gasket = s.execute(select(Material).where(Material.number == summary["materials"]["gasket"])).scalar_one()
        weekly = s.execute(select(PlannedOrder).where(PlannedOrder.material_id == gasket.id).order_by(PlannedOrder.need_date)).scalars().all()
        # Five demand elements net to one planned order per week; each is needed on the Monday of its week (the first from the run date).
        assert [(o.need_date, o.qty) for o in weekly] == [(date(2027, 7, 13), Decimal(200)), (date(2027, 7, 19), Decimal(150)),
                                                          (date(2027, 7, 26), Decimal(90)), (date(2027, 8, 2), Decimal(60))]
        assert [(d, Decimal(q)) for d, q in summary["weekly"]] == [(o.need_date.isoformat(), o.qty) for o in weekly]
        assert s.execute(select(MrpRun.mode).where(MrpRun.number == summary["reorderRun"])).scalar_one() == "REGENERATIVE"


def test_pack_is_idempotent(mfg):
    assert datasets.apply_pack("industry_manufacturing", PASSWORD)[0]["status"] == "ALREADY_LOADED"
