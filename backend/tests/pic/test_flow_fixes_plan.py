"""Flow-audit fixes for plan to requisition (M01 to M04; docs/PIC_Workflow_Flow_Audit.md §3 #1, #4, #8, #11 and the Workflow Guide's
Appendix A A1 to A13).

Every test that writes runs in one AXN transaction that is rolled back at the end (materials, demand and documents of its own, on a
business clock pinned after the signature case), so the signature case and the KPIs other files check never change. API tests only take
paths that are refused before anything is written, or read.
"""
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuditEvent, CatalogueItem, DemandElement, EventLine, GoodsReceipt, GrLine, IntegrationMessage, Material,
    MaterialChangeRequest, MrpException, MrpRun, PlannedOrder, PoLine, PrLine, RuleSet, StockMovement, Supplier,
    Task, Tenant,
)
from app.pic.platform import clock, workflow
from app.pic.platform.auth import Principal, scopes_for
from app.pic.platform.errors import Problem
from app.pic.seed import axion
from app.pic.seed.axion import ROLE_USER, at
from app.pic.services import catalogue, ind_manufacturing, kpi, material_changes, mdm, planning, requisition

PLANT = "P100"
T0 = at(date(2027, 2, 1), 10)  # after the signature case; demand of the tests lies in February / March 2027
REPO = Path(__file__).resolve().parents[3]
FRONTEND = REPO / "frontend" / "src" / "app" / "pic"


class _Rollback(Exception):
    pass


def _tid():
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()


@contextmanager
def rolled_back(when: datetime = T0):
    clock.set_pinned(when)
    try:
        with pytest.raises(_Rollback):
            with tenant_tx(_tid()) as s:
                yield s
                raise _Rollback()
    finally:
        clock.set_pinned(None)


def tick(minutes: int = 5) -> None:
    clock.set_pinned(clock.now() + timedelta(minutes=minutes))


def act(s, who: str) -> AppUser:
    user = s.execute(select(AppUser).where(AppUser.email == f"{who}@axion.example")).scalar_one()
    s.info["principal"] = Principal(user_id=user.id, tenant_id=user.tenant_id, tenant_code="AXN", email=user.email, name=user.full_name,
                                    roles=list(user.roles), scopes=scopes_for(list(user.roles)), attributes=user.attributes or {},
                                    supplier_id=user.supplier_id)
    s.info["user_id"] = user.id
    return user


def act_as(s, roles: list, attributes: dict) -> uuid.UUID:
    """A principal without a user row (its attributes come from the token), e.g. an MRP controller scoped to another plant."""
    uid = uuid.uuid4()
    s.info["principal"] = Principal(user_id=uid, tenant_id=_tid(), tenant_code="AXN", email=f"{uid.hex[:8]}@axion.example", name="Scoped user",
                                    roles=roles, scopes=scopes_for(roles), attributes=attributes, supplier_id=None)
    s.info["user_id"] = uid
    return uid


def problem(fn, *args, **kwargs) -> Problem:
    with pytest.raises(Problem) as exc:
        fn(*args, **kwargs)
    return exc.value


def approve_all(s, object_id, comment: str = "Approved") -> int:
    done = 0
    for _ in range(12):
        tasks = s.execute(select(Task).where(Task.object_id == object_id, Task.status == "OPEN").order_by(Task.sequence)).scalars().all()
        if not tasks:
            return done
        progressed = False
        for task in tasks:
            people = ROLE_USER[task.candidate_role] if isinstance(ROLE_USER[task.candidate_role], list) else [ROLE_USER[task.candidate_role]]
            for who in people:
                act(s, who)
                if workflow.can_work(s.info["principal"], task) is None:
                    workflow.complete(s, task.id, "APPROVE", comment)
                    done += 1
                    progressed = True
                    break
        if not progressed:
            return done
    return done


def new_material(s, *, mrp_type: str = "PD", safety: int = 0, policy: str = "EXACT", price: int = 12_500_00, attributes=None) -> Material:
    number = f"FX-{uuid.uuid4().hex[:8].upper()}"
    m = Material(tenant_id=_tid(), number=number, description=f"Flow fix test material {number}", type="STOCK", material_group=axion.CATEGORY,
                 category=axion.CATEGORY, base_uom="EA", mrp_type=mrp_type, safety_stock=Decimal(safety), lot_size_policy=policy,
                 standard_price_minor=price, planned_delivery_days=5, gr_processing_days=1, status="ACTIVE", attributes=attributes or {},
                 created_by=s.info["user_id"])
    s.add(m)
    s.flush()
    return m


def demand(s, material: Material, day: date, qty: int, ref: str = None) -> DemandElement:
    d = DemandElement(tenant_id=_tid(), material_id=material.id, plant=PLANT, type="RESERVATION", reference=ref or f"RSV-{uuid.uuid4().hex[:6]}",
                      req_date=day, qty=Decimal(qty), changed_at=clock.now(), created_by=s.info["user_id"])
    s.add(d)
    s.flush()
    return d


def orders_of(s, material: Material, status: str = None) -> list[PlannedOrder]:
    q = select(PlannedOrder).where(PlannedOrder.material_id == material.id)
    if status:
        q = q.where(PlannedOrder.status == status)
    return s.execute(q.order_by(PlannedOrder.need_date)).scalars().all()


def clone(s, obj, **changes):
    """A copy of an existing signature-case row (PO line, goods receipt, event line) with new identity and the given changes."""
    data = {c.key: getattr(obj, c.key) for c in obj.__mapper__.column_attrs}
    data.update(id=uuid.uuid7(), row_version=1, updated_at=None, **changes)
    new = type(obj)(**data)
    s.add(new)
    s.flush()
    return new


def audit_actions(s, object_id) -> list[str]:
    return [a for (a,) in s.execute(select(AuditEvent.action).where(AuditEvent.object_id == object_id).order_by(AuditEvent.seq))]


# ================================================================ 1 (A12): category SOW forms
def test_flowfix1_sow_description_over_200_is_422_not_500(client, login):
    body = {"origin": "MANUAL", "purpose_code": "SERVICES", "plant": PLANT, "lines": [{
        "item_type": "SERVICE", "purchase_type": "SERVICE", "description": "STATEMENT OF WORK " + "x" * 3800, "material_group": "PROF-SERVICES",
        "qty": "1", "uom": "AU", "price_est_minor": 100_000, "need_date": "2027-03-01", "account_assignment_type": "COST_CENTER",
        "account_assignment_code": "4100"}]}
    r = client.post("/v1/requisitions", json=body, headers=login("requester"))
    assert r.status_code == 422, r.text
    assert "200" in r.json()["detail"] and "sow" in r.json()["detail"]
    with rolled_back() as s:
        act(s, "requester")
        err = problem(requisition.create, s, origin="MANUAL", purpose_code="SERVICES", plant=PLANT, lines=[{
            **body["lines"][0], "need_date": date(2027, 3, 1)}])
        assert err.status == 422 and err.code == "DESCRIPTION_TOO_LONG"


def test_flowfix1_sow_attributes_stored_on_the_line_and_carried_to_po_and_event_line():
    with rolled_back() as s:
        act(s, "requester")
        sow = {"template": "SVC-PROFESSIONAL", "title": "SAP integration architecture", "text": "STATEMENT OF WORK\n" + "Milestone. " * 400,
               "attributes": {"sowType": "PROFESSIONAL_SERVICES", "milestones": [{"title": "Phase 1", "pct": 30}], "deliveryModel": "MILESTONE"}}
        pr = requisition.create(s, origin="MANUAL", purpose_code="SERVICES", plant=PLANT, lines=[{
            "item_type": "SERVICE", "purchase_type": "SERVICE", "description": "SOW: SAP integration architecture", "material_group": "PROF-SERVICES",
            "qty": "1", "uom": "AU", "price_est_minor": 20 * 100_000 * 100, "need_date": date(2027, 5, 31), "account_assignment_type": "COST_CENTER",
            "account_assignment_code": "4100", "template": "SVC-PROFESSIONAL", "sow": sow}])
        line = s.execute(select(PrLine).where(PrLine.requisition_id == pr.id)).scalar_one()
        assert line.sow["template"] == "SVC-PROFESSIONAL" and line.sow["attributes"]["milestones"][0]["pct"] == 30 and len(line.sow["text"]) > 3000
        assert line.description == "SOW: SAP integration architecture"
        # an older client sending only the form attributes on a template line keeps them as the SOW too
        legacy = requisition.create(s, origin="MANUAL", purpose_code="SERVICES", plant=PLANT, lines=[{
            "item_type": "SERVICE", "purchase_type": "SERVICE", "description": "Marketing campaign", "material_group": "MARKETING", "qty": "1",
            "uom": "AU", "price_est_minor": 100_000, "need_date": date(2027, 5, 31), "account_assignment_type": "COST_CENTER",
            "account_assignment_code": "4100", "template": "MKT-CAMPAIGN-EVENT", "attributes": {"sowType": "MARKETING_CAMPAIGN", "channel": "Digital"}}])
        legacy_line = s.execute(select(PrLine).where(PrLine.requisition_id == legacy.id)).scalar_one()
        assert legacy_line.sow == {"template": "MKT-CAMPAIGN-EVENT", "title": None, "text": None,
                                   "attributes": {"sowType": "MARKETING_CAMPAIGN", "channel": "Digital"}}
        # the SOW travels with the line: a PO line and a sourcing-event line made from it carry it (mapper hook, every creation path)
        po_line = clone(s, s.execute(select(PoLine).limit(1)).scalar_one(), line_no=9910, requisition_id=pr.id, pr_line_no=10, sow=None)
        assert po_line.sow["title"] == "SAP integration architecture"
        event_line = clone(s, s.execute(select(EventLine).limit(1)).scalar_one(), line_no=9910, requisition_id=pr.id, pr_line_no=10, sow=None)
        assert event_line.sow["attributes"]["deliveryModel"] == "MILESTONE"
        too_long = problem(requisition.create, s, origin="MANUAL", purpose_code="SERVICES", plant=PLANT, lines=[{
            "item_type": "SERVICE", "purchase_type": "SERVICE", "description": "SOW", "material_group": "PROF-SERVICES", "qty": "1", "uom": "AU",
            "price_est_minor": 100, "need_date": date(2027, 5, 31), "sow": {"text": "x" * (requisition.SOW_TEXT_LIMIT + 1)}}])
        assert too_long.status == 422 and too_long.code == "SOW_TOO_LONG"


# ================================================================ 2 (audit #4): converted demand is not planned twice; ERP orders are kept
def test_flowfix1_mrp_counts_open_requisitions_as_supply_and_does_not_plan_converted_demand_again():
    with rolled_back() as s:
        act(s, "mrp.controller")
        m = new_material(s, safety=200)
        demand(s, m, date(2027, 3, 1), 800)
        run1 = planning.run(s, plant=PLANT, mode="REGENERATIVE", materials=[m.number])
        (order,) = orders_of(s, m, "CREATED")
        assert order.qty == Decimal(1000)
        pr = planning.convert(s, order)
        assert pr.status in ("IN_APPROVAL", "APPROVED")
        tick()
        demand(s, m, date(2027, 3, 8), 300)
        tick()
        run2 = planning.run(s, plant=PLANT, mode="NET_CHANGE", materials=[m.number])
        new = [o for o in orders_of(s, m, "CREATED") if o.mrp_run_id == run2.id]
        assert [o.qty for o in new] == [Decimal(300)], [(o.qty, o.need_date) for o in new]
        result = run2.results[0]
        assert Decimal(result["open_req"]) == Decimal(1000) and Decimal(result["net"]) == Decimal(300)
        assert run1.id != run2.id
        # the requirements list (MRP-02) shows the requisition as a receipt
        profile = planning.requirements_profile(s, m, PLANT, date(2027, 2, 1))
        assert profile["openRequisitions"] == Decimal(1000) and any(r["kind"] == "OPEN_REQUISITION" for r in profile["receipts"])


def test_flowfix1_sourcing_requirement_requisitions_are_not_mrp_receipts():
    """Rule MRP-SUPPLY: an annual requirement raised to source an agreement (purpose ANNUAL_SOURCING) is not a delivery, so it does not
    cover the demand MRP plans; a manual stock requisition for a delivery does."""
    with rolled_back() as s:
        act(s, "mrp.controller")
        m = new_material(s, price=150_00)
        demand(s, m, date(2027, 3, 1), 500)
        act(s, "buyer")
        for purpose, qty in (("ANNUAL_SOURCING", "18000"), ("BUFFER_BUILD", "200")):
            pr = requisition.create(s, origin="MANUAL", purpose_code=purpose, purpose_text="flow fix", plant=PLANT, lines=[{
                "item_type": "MATERIAL", "purchase_type": "STOCK", "material": m.number, "qty": qty, "price_est_minor": 150_00,
                "need_date": date(2027, 3, 1), "storage_location": "0001"}])
            requisition.submit(s, pr)
        assert "ANNUAL_SOURCING" in planning.requisitions_not_supply(s)
        act(s, "mrp.controller")
        run = planning.run(s, plant=PLANT, mode="REGENERATIVE", materials=[m.number])
        assert Decimal(run.results[0]["open_req"]) == Decimal(200) and Decimal(run.results[0]["net"]) == Decimal(300)
        assert [o.qty for o in orders_of(s, m, "CREATED")] == [Decimal(300)]


def test_flowfix1_platform_run_keeps_erp_imported_planned_orders_and_counts_them_as_supply():
    with rolled_back() as s:
        act(s, "mrp.controller")
        m = new_material(s)
        demand(s, m, date(2027, 3, 1), 250)
        erp_run = MrpRun(tenant_id=_tid(), number=f"MR-X{uuid.uuid4().hex[:5]}", mode="ERP_IMPORT", plant=PLANT, scope={}, run_date=date(2027, 2, 1),
                         status="COMPLETED", started_by=s.info["user_id"], results=[])
        s.add(erp_run)
        s.flush()
        erp_order = PlannedOrder(tenant_id=_tid(), number=f"PLO-X{uuid.uuid4().hex[:5]}", mrp_run_id=erp_run.id, material_id=m.id, plant=PLANT,
                                 storage_location="0001", qty=Decimal(250), need_date=date(2027, 3, 1), release_date=date(2027, 2, 20), status="CREATED",
                                 source={}, exception_codes=[], source_system="SAP_S4", external_ref="ERP-PLO-1")
        s.add(erp_order)
        s.flush()
        tick()
        run = planning.run(s, plant=PLANT, mode="REGENERATIVE", materials=[m.number])
        s.refresh(erp_order)
        assert erp_order.status == "CREATED", "a platform run must not delete the ERP's planned order"
        assert [o for o in orders_of(s, m, "CREATED") if o.mrp_run_id == run.id] == []
        assert Decimal(run.results[0]["firm_receipts"]) == Decimal(250)


# ================================================================ 3 (audit #8, A7): MRP type of new materials and its governance
def test_flowfix1_new_stock_material_is_created_plannable_and_mcr_mrp_types_match_the_engine():
    with rolled_back() as s:
        act(s, "requester")
        assert mdm.initial_mrp_type(s, "STOCK", axion.CATEGORY, None) == "PD"
        assert mdm.initial_mrp_type(s, "NON_STOCK", axion.CATEGORY, None) == "ND"
        assert problem(mdm.initial_mrp_type, s, "NON_STOCK", axion.CATEGORY, "PD").status == 422
        request = mdm.create_request(s, description=f"Flow fix forged hub blank {uuid.uuid4().hex[:6]} 42CrMo4 quenched tempered", type="STOCK",
                                     material_group="FASTENERS", category="FASTENERS", base_uom="EA", mpn=f"FX-{uuid.uuid4().hex[:6]}")
        assert request.mrp_type == "PD"
        if request.status == "IN_STEWARDSHIP":
            approve_all(s, request.id, "Data complete")
            s.refresh(request)
            material = s.get(Material, request.material_id)
            assert material.mrp_type == "PD"
        m = new_material(s, mrp_type="ND")
        for code in ("PD", "PW", "PM", "VB", "KB", "ND"):
            if code != "ND":
                assert material_changes.classify(s, m, {"mrp_type": code}, ["PLANT"])["changes"][0]["to"] == code
        assert problem(material_changes.classify, s, m, {"mrp_type": "VM"}, ["PLANT"]).code == "INVALID_FIELD"


def test_flowfix1_mrp_type_change_goes_through_steward_approval_version_and_erp(client, login):
    r = client.put("/v1/materials/ANY/mrp-type", json={"mrpType": "VM"}, headers=login("mrp.controller"))
    assert r.status_code == 422
    with rolled_back() as s:
        act(s, "mrp.controller")
        m = new_material(s, mrp_type="PD")
        request = ind_manufacturing.request_mrp_type(s, m.number, "VB", "Reorder-point planning for this C-part")
        assert request.status == "IN_APPROVAL" and m.mrp_type == "PD", "the type changes only after the steward's approval"
        assert [c["field"] for c in request.changes] == ["mrp_type"] and request.domains == ["PLANT"]
        act(s, "mdm.plant")
        material_changes.decide(s, request, "APPROVE", "Planning mode checked")
        s.refresh(m)
        assert request.status == "APPLIED" and m.mrp_type == "VB" and m.version == 2
        assert s.execute(select(IntegrationMessage.status).where(IntegrationMessage.idempotency_key == f"MAT|{m.number}|2")).scalar() == "POSTED"
        # a data load (dataset pack) is versioned, audited and sent to the ERP as well
        act(s, "mrp.controller")
        ind_manufacturing.set_mrp_type(s, m.number, "KB")
        s.refresh(m)
        assert m.mrp_type == "KB" and m.version == 3
        assert s.execute(select(MaterialChangeRequest.status).where(MaterialChangeRequest.material_id == m.id, MaterialChangeRequest.to_version == 3)
                         ).scalar() == "APPLIED"


# ================================================================ 4 (A5): plant scoping of MRP
def test_flowfix1_mrp_run_firm_convert_and_reads_are_plant_scoped(client, login):
    r = client.post("/v1/mrp/runs", json={"plant": "P200", "mode": "SIMULATION"}, headers=login("mrp.controller"))  # AXN controller: plants P100
    assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN"
    with rolled_back() as s:
        act(s, "mrp.controller")
        m = new_material(s)
        demand(s, m, date(2027, 3, 1), 100)
        planning.run(s, plant=PLANT, mode="REGENERATIVE", materials=[m.number])
        (order,) = orders_of(s, m, "CREATED")
        act_as(s, ["MRP_CONTROLLER"], {"plants": ["P200"]})
        assert problem(planning.run, s, plant=PLANT, mode="SIMULATION").status == 403
        assert problem(planning.firm, s, order).status == 403
        assert problem(planning.convert, s, order).status == 403
        assert problem(planning.cancel, s, order, "not mine").status == 403
        assert problem(planning.ensure_readable, s, PLANT, "Planned order", order.number).status == 404
        assert planning.readable_plants(s) == ["P200"]
        act(s, "mrp.controller")
        assert planning.firm(s, order).status == "FIRMED"


# ================================================================ 5 (A1): exceptions close and supersede; the backlog KPI counts open ones
def test_flowfix1_mrp_exceptions_are_superseded_by_a_newer_run_and_can_be_closed():
    with rolled_back() as s:
        act(s, "mrp.controller")
        m = new_material(s, safety=50)
        run1 = planning.run(s, plant=PLANT, mode="REGENERATIVE", materials=[m.number])
        first = s.execute(select(MrpException).where(MrpException.mrp_run_id == run1.id)).scalars().all()
        assert [e.code for e in first] == ["BELOW_SAFETY"] and first[0].plant == PLANT
        backlog = kpi.m02_exception_backlog(kpi.Ctx(s))[0]
        tick()
        run2 = planning.run(s, plant=PLANT, mode="REGENERATIVE", materials=[m.number])
        s.refresh(first[0])
        assert first[0].status == "SUPERSEDED" and first[0].superseded_by_run_id == run2.id and first[0].closed_at is not None
        (current,) = s.execute(select(MrpException).where(MrpException.mrp_run_id == run2.id)).scalars().all()
        assert kpi.m02_exception_backlog(kpi.Ctx(s))[0] == backlog, "the superseded exception no longer counts"
        planning.close_exception(s, current, "Expedited the open PO with the supplier")
        assert current.status == "CLOSED" and current.close_reason.startswith("Expedited") and current.closed_by == s.info["user_id"]
        assert kpi.m02_exception_backlog(kpi.Ctx(s))[0] == backlog - 1
        assert problem(planning.close_exception, s, current, "again").status == 409
        assert problem(planning.close_exception, s, first[0], "x").status == 422  # reason too short is checked first
        assert "CLOSED" in audit_actions(s, current.id)


# ================================================================ 6 (A2): cancel and unfirm planned orders
def test_flowfix1_planned_order_cancel_and_unfirm_with_guards_and_audit():
    with rolled_back() as s:
        act(s, "mrp.controller")
        m = new_material(s)
        d = demand(s, m, date(2027, 3, 1), 400)
        planning.run(s, plant=PLANT, mode="REGENERATIVE", materials=[m.number])
        (order,) = orders_of(s, m, "CREATED")
        assert problem(planning.unfirm, s, order, "not firmed yet").status == 409
        planning.firm(s, order)
        planning.unfirm(s, order, "Demand under review")
        assert order.status == "CREATED"
        planning.firm(s, order)
        # the demand goes away: the next run tells the controller the firmed order is not needed (CANCEL), and the controller acts on it
        d.qty, d.changed_at = Decimal(0), clock.now()
        tick()
        run = planning.run(s, plant=PLANT, mode="REGENERATIVE", materials=[m.number])
        (cancel_msg,) = s.execute(select(MrpException).where(MrpException.mrp_run_id == run.id, MrpException.code == "CANCEL")).scalars().all()
        assert cancel_msg.planned_order_id == order.id
        planning.cancel(s, order, "Customer order withdrawn")
        s.refresh(cancel_msg)
        assert order.status == "CANCELLED" and cancel_msg.status == "CLOSED" and "cancelled" in cancel_msg.close_reason
        assert problem(planning.cancel, s, order, "twice").status == 409
        assert problem(planning.convert, s, order).status == 409
        assert {"FIRMED", "UNFIRMED", "CANCELLED"} <= set(audit_actions(s, order.id))


# ================================================================ 7 (A3): net change picks up supply changes
def test_flowfix1_net_change_replans_materials_whose_supply_changed():
    with rolled_back() as s:
        act(s, "mrp.controller")
        m = new_material(s, safety=10)
        demand(s, m, date(2027, 3, 1), 100)
        tick()
        planning.run(s, plant=PLANT, mode="NET_CHANGE")
        tick()
        assert m.id not in planning.changed_since(s, PLANT, clock.now() - timedelta(minutes=1))
        tick()
        quiet = planning.run(s, plant=PLANT, mode="NET_CHANGE")
        assert m.number not in [r["material"] for r in quiet.results]
        tick()
        since = clock.now()
        tick()
        s.add(StockMovement(tenant_id=_tid(), material_id=m.id, plant=PLANT, storage_location="0001", movement_type="561", stock_type="UNRESTRICTED",
                            qty=Decimal(60), reference_type="TEST", reference_id=uuid.uuid4(), reference_ref="flow fix", created_by=s.info["user_id"]))
        s.flush()
        assert m.id in planning.changed_since(s, PLANT, since)
        tick()
        run = planning.run(s, plant=PLANT, mode="NET_CHANGE")
        assert m.number in [r["material"] for r in run.results], "a stock-only change brings the material into the net-change scope"
        # a firmed planned order is a supply change too
        (order,) = [o for o in orders_of(s, m, "CREATED") if o.mrp_run_id == run.id] or [orders_of(s, m)[-1]]
        tick()
        since = clock.now()
        tick()
        if order.status == "CREATED":
            planning.firm(s, order)
            s.flush()
            assert m.id in planning.changed_since(s, PLANT, since)


# ================================================================ 8 (A4): PERIOD lot size
def test_flowfix1_period_lot_size_groups_the_week_and_the_month():
    with rolled_back() as s:
        act(s, "mrp.controller")
        weekly = new_material(s, policy="PERIOD")
        for day, qty in ((date(2027, 3, 1), 100), (date(2027, 3, 3), 150), (date(2027, 3, 5), 50), (date(2027, 3, 9), 70)):  # Mon/Wed/Fri, next Tue
            demand(s, weekly, day, qty)
        planning.run(s, plant=PLANT, mode="REGENERATIVE", materials=[weekly.number])
        assert [(o.need_date, o.qty) for o in orders_of(s, weekly, "CREATED")] == [(date(2027, 3, 1), Decimal(300)), (date(2027, 3, 9), Decimal(70))]
        monthly = new_material(s, policy="PERIOD", attributes={"lotSizePeriod": "MONTH"})
        for day, qty in ((date(2027, 3, 2), 40), (date(2027, 3, 20), 60), (date(2027, 4, 2), 25)):
            demand(s, monthly, day, qty)
        tick()
        planning.run(s, plant=PLANT, mode="REGENERATIVE", materials=[monthly.number])
        assert [(o.need_date, o.qty) for o in orders_of(s, monthly, "CREATED")] == [(date(2027, 3, 2), Decimal(100)), (date(2027, 4, 2), Decimal(25))]
        exact = new_material(s)
        for day, qty in ((date(2027, 3, 1), 100), (date(2027, 3, 3), 150)):
            demand(s, exact, day, qty)
        planning.run(s, plant=PLANT, mode="REGENERATIVE", materials=[exact.number])
        assert [o.qty for o in orders_of(s, exact, "CREATED")] == [Decimal(100), Decimal(150)]


# ================================================================ 9 (A6): Kanban rule flags and refill on goods receipt
def test_flowfix1_kanban_honours_rule_flags_and_refills_on_the_goods_receipt_of_its_replenishment():
    with rolled_back() as s:
        act(s, "mrp.controller")
        rule = s.execute(select(RuleSet).where(RuleSet.key == "KANBAN").order_by(RuleSet.effective_from.desc())).scalars().first()
        if rule is None:
            rule = RuleSet(tenant_id=_tid(), key="KANBAN", version="T-1", effective_from=date(2026, 1, 1), body={}, description="test")
            s.add(rule)
        rule.body = {"enabled": True, "purposeCode": "LINE_SIDE_REPLEN", "autoRequisition": False}
        s.flush()
        m = new_material(s, mrp_type="KB", price=4_00)
        card = ind_manufacturing.create_card(s, material=m.number, plant=PLANT, bin_qty=500)
        ind_manufacturing.signal_empty(s, card)
        assert card.status == "EMPTY" and card.requisition_id is None, "autoRequisition false: the card waits for the controller"
        ind_manufacturing._signalled(s, SimpleNamespace(object_id=card.id))  # the event consumer respects the flag too
        assert card.status == "EMPTY"
        pr = ind_manufacturing.replenish(s, card)
        assert card.status == "REPLENISHING" and pr.purpose_code == "LINE_SIDE_REPLEN"
        # goods receipt of its replenishment, in two deliveries: the card is full again once the bin is covered
        template_line = s.execute(select(PoLine).limit(1)).scalar_one()
        po_line = clone(s, template_line, line_no=9920, material_id=m.id, plant=PLANT, requisition_id=pr.id, pr_line_no=10, qty=Decimal(500),
                        received_qty=Decimal(200))
        template_gr = s.execute(select(GoodsReceipt).limit(1)).scalar_one()
        template_gr_line = s.execute(select(GrLine).where(GrLine.gr_id == template_gr.id)).scalars().first()
        gr1 = clone(s, template_gr, number=f"GR-X{uuid.uuid4().hex[:6]}", po_id=po_line.po_id)
        clone(s, template_gr_line, gr_id=gr1.id, line_no=10, po_line_id=po_line.id, material_id=m.id, qty=Decimal(200), accepted_qty=Decimal(200),
              rejected_qty=Decimal(0), serials=[])
        ind_manufacturing._received(s, SimpleNamespace(payload={"grId": str(gr1.id)}))
        assert card.status == "REPLENISHING"
        po_line.received_qty = Decimal(500)
        gr2 = clone(s, template_gr, number=f"GR-X{uuid.uuid4().hex[:6]}", po_id=po_line.po_id)
        clone(s, template_gr_line, gr_id=gr2.id, line_no=10, po_line_id=po_line.id, material_id=m.id, qty=Decimal(300), accepted_qty=Decimal(300),
              rejected_qty=Decimal(0), serials=[])
        ind_manufacturing._received(s, SimpleNamespace(payload={"grId": str(gr2.id)}))
        assert card.status == "FULL" and card.cycles == 1


# ================================================================ 10 (A8): material request withdraw
def test_flowfix1_material_request_withdraw_including_duplicate_blocked():
    with rolled_back() as s:
        existing = s.execute(select(Material).where(Material.status == "ACTIVE", Material.mpn.is_not(None)).order_by(Material.number)).scalars().first()
        act(s, "requester")
        request = mdm.create_request(s, description=existing.description, type=existing.type, material_group=existing.material_group,
                                     category=existing.category, base_uom=existing.base_uom, mpn=existing.mpn, attributes=existing.attributes)
        assert request.status == "DUPLICATE_BLOCKED"
        act(s, "buyer")
        assert problem(mdm.withdraw, s, request, "not mine").status == 403
        act(s, "requester")
        assert problem(mdm.withdraw, s, request, "").status == 422
        mdm.withdraw(s, request, "Using the existing material instead")
        assert request.status == "WITHDRAWN" and request.withdrawal_reason.startswith("Using")
        assert problem(mdm.withdraw, s, request, "again please").status == 409
        assert "WITHDRAWN" in audit_actions(s, request.id)
        # a request in stewardship is withdrawn with its steward tasks
        fresh = mdm.create_request(s, description=f"Flow fix unique gland packing {uuid.uuid4().hex} PTFE braided", type="NON_STOCK",
                                   material_group="MRO", category="MRO", base_uom="M")
        assert fresh.status == "IN_STEWARDSHIP"
        mdm.withdraw(s, fresh, "Raised by mistake")
        assert not s.execute(select(Task).where(Task.object_id == fresh.id, Task.status == "OPEN")).scalars().all()


# ================================================================ 11 (A9): screen label and the demo case
def test_flowfix1_material_change_screen_label_and_demo_pack():
    changes = (FRONTEND / "materials" / "_changes.tsx").read_text(encoding="utf-8")
    assert "MDM-04" not in changes and "MDM-02 · Steward workbench · Material change request" in changes
    from app.pic.seed import datasets
    assert "material_changes" in datasets.PACKS
    pack = datasets.load("material_changes")
    assert pack.KEY == "axn-material-governance" and pack.TENANTS == ("AXN",) and pack.READY


# ================================================================ 12 (A10): approved requisitions to the ERP
def test_flowfix1_approved_requisition_is_sent_to_the_erp_unless_the_rule_turns_it_off():
    with rolled_back() as s:
        act(s, "mrp.controller")
        m = new_material(s, price=150_00)
        act(s, "requester")
        pr = requisition.create(s, origin="MANUAL", purpose_code="BUFFER_BUILD", purpose_text="flow fix", plant=PLANT, lines=[{
            "item_type": "MATERIAL", "purchase_type": "STOCK", "material": m.number, "qty": "20", "price_est_minor": 150_00,
            "need_date": date(2027, 3, 1), "storage_location": "0001"}])
        requisition.submit(s, pr)
        approve_all(s, pr.id)
        assert pr.status == "APPROVED"
        (message,) = s.execute(select(IntegrationMessage).where(IntegrationMessage.message_type == "PURCHASE_REQUISITION",
                                                                IntegrationMessage.object_id == pr.id)).scalars().all()
        assert message.idempotency_key == f"{pr.company_code}|PR|{pr.number}|r1" and message.status == "POSTED" and message.erp_doc_no
        assert message.payload["lines"][0]["material"] == m.number
        # the tenant turns it off (rule ERP-TARGET sendPurchaseRequisitions false)
        target = s.execute(select(RuleSet).where(RuleSet.key == "ERP-TARGET").order_by(RuleSet.effective_from.desc())).scalars().first()
        if target is None:
            s.add(RuleSet(tenant_id=_tid(), key="ERP-TARGET", version="T-1", effective_from=date(2026, 1, 1), body={"system": "SAP_S4",
                                                                                                                   "sendPurchaseRequisitions": False}))
        else:
            target.body = {**target.body, "sendPurchaseRequisitions": False}
        s.flush()
        assert requisition.erp_enabled(s, pr.company_code) is False
        assert requisition.send_to_erp(s, pr) is None


# ================================================================ 13 (A11): hosted catalogue maintenance
def test_flowfix1_catalogue_items_are_maintained_with_validation_validity_abac_and_audit(client, login):
    assert client.post("/v1/catalogue-items", json={"supplier": "X", "supplier_part_no": "P", "description": "d", "material_group": "G", "uom": "EA",
                                                    "price_minor": 100}, headers=login("requester")).status_code == 403
    assert client.get("/v1/catalogue-items", headers=login("buyer")).status_code == 200
    with rolled_back() as s:
        supplier = s.execute(select(Supplier).where(Supplier.status.not_in(catalogue.SUPPLIER_REFUSED)).order_by(Supplier.code)).scalars().first()
        act(s, "category.manager")
        part = f"FX-{uuid.uuid4().hex[:6]}"
        base = dict(description="Flow fix catalogue item", material_group=axion.CATEGORY, category=axion.CATEGORY, uom="EA", price_minor=2_500_00,
                    gst_rate=18, valid_from=date(2027, 1, 1), valid_to=date(2027, 12, 31))
        assert problem(catalogue.create, s, supplier=supplier.code, supplier_part_no=part, **{**base, "price_minor": 0}).status == 422
        assert problem(catalogue.create, s, supplier=supplier.code, supplier_part_no=part, **{**base, "valid_to": date(2026, 6, 1)}).status == 422
        assert problem(catalogue.create, s, supplier=supplier.code, supplier_part_no=part, **{**base, "gst_rate": 17}).status == 422
        item = catalogue.create(s, supplier=supplier.code, supplier_part_no=part, **base)
        assert problem(catalogue.create, s, supplier=supplier.code, supplier_part_no=part, **base).code == "CATALOGUE_ITEM_EXISTS"
        catalogue.update(s, item, {"price_minor": 2_400_00, "lead_time_days": 4}, "Q1 price list")
        assert item.price_minor == 2_400_00 and {"CREATED", "CHANGED"} <= set(audit_actions(s, item.id))
        assert any(h["id"] == str(item.id) for h in requisition.search(s, "Flow fix catalogue item")["results"]["catalogue"])
        act_as(s, ["CATEGORY_MANAGER"], {"categories": ["SOMETHING-ELSE"]})
        assert problem(catalogue.update, s, item, {"price_minor": 1}, "not my category").status == 403
        act(s, "category.manager")
        catalogue.set_active(s, item, False, "Supplier discontinued the part")
        assert not any(h["id"] == str(item.id) for h in requisition.search(s, "Flow fix catalogue item")["results"]["catalogue"])
        act(s, "requester")
        refused = problem(requisition.create, s, origin="CATALOGUE", purpose_code="MAINTENANCE", plant=PLANT, lines=[{
            "item_type": "CATALOGUE", "purchase_type": "NON_STOCK", "catalogue_item_id": str(item.id), "qty": "2", "need_date": date(2027, 3, 1),
            "account_assignment_type": "COST_CENTER", "account_assignment_code": "4100"}])
        assert refused.status == 422 and "not offered" in refused.detail
        assert s.get(CatalogueItem, item.id).active is False


def test_flowfix1_catalogue_csv_loader_validates_all_or_nothing():
    from app.pic.tools import load_catalogue

    with tenant_tx(_tid()) as s:
        supplier = s.execute(select(Supplier).where(Supplier.status.not_in(catalogue.SUPPLIER_REFUSED)).order_by(Supplier.code)).scalars().first().code
        before = s.execute(select(func.count()).select_from(CatalogueItem)).scalar()
    part = f"FX-{uuid.uuid4().hex[:6]}"
    good = ("supplier,supplier_part_no,description,material_group,category,uom,price,gst_rate,valid_from,valid_to\n"
            f"{supplier},{part},Flow fix loader item,{axion.CATEGORY},{axion.CATEGORY},EA,125.50,18,2027-01-01,2027-12-31\n")
    summary = load_catalogue.load("AXN", good, dry_run=True)
    assert summary["status"] == "VALIDATED" and summary["created"] == 1 and not summary["errors"]
    bad = good + f"{supplier},{part}-B,Bad row,{axion.CATEGORY},{axion.CATEGORY},EA,0,18,2027-01-01,2027-12-31\n"
    refused = load_catalogue.load("AXN", bad)
    assert refused["status"] == "REFUSED" and refused["errors"][0]["line"] == 3
    with tenant_tx(_tid()) as s:
        assert s.execute(select(func.count()).select_from(CatalogueItem)).scalar() == before
    assert load_catalogue.read_rows("supplier,description\nX,Y\n")[1], "missing columns are reported"


# ================================================================ 14 (A13) and 15: the promote button, preview without a reason, frontend limits
def test_flowfix1_promote_button_sow_limit_and_mcr_preview_without_reason(client, login):
    page = (FRONTEND / "requisitions" / "[ref]" / "page.tsx").read_text(encoding="utf-8")
    assert "promote-material" in page and "Promote to material" in page
    sow_form = (FRONTEND / "requisitions" / "new" / "category-sow-forms.tsx").read_text(encoding="utf-8")
    assert "SOW_DESCRIPTION_LIMIT = 200" in sow_form and "sow:" in sow_form
    assert (FRONTEND / "buyer" / "catalogue" / "page.tsx").exists()
    with tenant_tx(_tid()) as s:
        material = s.execute(select(Material).where(Material.status == "ACTIVE", Material.type == "STOCK").order_by(Material.number)).scalars().first()
    r = client.post(f"/v1/materials/{material.number}/change-requests/preview", json={"changes": {"safety_stock": "999"}}, headers=login("requester"))
    assert r.status_code == 200, r.text
    assert r.json()["changes"][0]["field"] == "safety_stock"
