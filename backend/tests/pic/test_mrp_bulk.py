"""MRP bulk execution (TD §15 NFR: 50,000 materials < 10 min): ``planning.run`` bulk-loads every read once per run and
writes planned orders, exceptions and links in multi-row statements. These tests prove the plan is identical to the
per-material reads (``net_material`` / ``source.determine`` without a preloaded context, the pre-NFR code path) on a
representative tenant: every source-determination branch (contract, quota, source list, info record, none, blocked and
unqualified suppliers excluded), every exception (BELOW_SAFETY, PAST_DUE, RESCHEDULE_IN/OUT, CANCEL), every lot-size
policy, open POs, in-transit ASNs and the replacement of unfirmed orders from earlier runs.

Everything runs in transactions that are rolled back, so the signature case and later tests see the seed unchanged.
"""
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import MultipleResultsFound

from app.pic.db import system_tx
from app.pic.models import (
    AuditEvent, Contract, ContractLine, DemandElement, DocumentLink, InfoRecord, Material, MrpException, MrpRun, NumberRange,
    OutboxEvent, PlannedOrder, PriceValidity, ProcessInstance, ProcessStep, QuotaArrangement, QuotaLine, SourceList, Stock,
    Supplier, Tenant,
)
from app.pic.platform import clock
from app.pic.platform.core import link_many, next_number, next_numbers
from app.pic.seed.axion import CATEGORY, Scenario, at
from app.pic.services import planning, source

PLANT = "P100"
RUN_DATE = date(2026, 10, 20)
WHEN = at(RUN_DATE, 9)


class _Rollback(Exception):
    pass


@pytest.fixture(scope="module")
def sc(database):
    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()
    yield Scenario(tenant_id)
    clock.set_pinned(None)


def _material(s, number: str, **kw) -> Material:
    values = dict(description=f"MRP bulk test {number}", type="STOCK", material_group=CATEGORY, category=CATEGORY, base_uom="EA",
                  mrp_type="PD", lot_size_policy="EXACT", safety_stock=Decimal(50), planned_delivery_days=5, gr_processing_days=1,
                  standard_price_minor=10_000, status="ACTIVE")
    values.update(kw)
    m = Material(tenant_id=s.info["tenant_id"], number=number, **values)
    s.add(m)
    s.flush()
    return m


def _demand(s, m: Material, *rows):
    for days, qty in rows:
        s.add(DemandElement(tenant_id=s.info["tenant_id"], material_id=m.id, plant=PLANT, type="FORECAST", reference=f"{m.number}-{days}",
                            req_date=RUN_DATE + timedelta(days=days), qty=Decimal(qty), changed_at=WHEN))


def _stock(s, m: Material, qty, stock_type="UNRESTRICTED"):
    s.add(Stock(tenant_id=s.info["tenant_id"], material_id=m.id, plant=PLANT, storage_location="0001", stock_type=stock_type, batch="",
                qty=Decimal(qty)))


def _order(s, m: Material, run_id, number: str, qty, days: int, status: str) -> PlannedOrder:
    o = PlannedOrder(tenant_id=s.info["tenant_id"], number=number, mrp_run_id=run_id, material_id=m.id, plant=PLANT, storage_location="0001",
                     qty=Decimal(qty), need_date=RUN_DATE + timedelta(days=days), release_date=RUN_DATE + timedelta(days=days - 6),
                     status=status, source={}, exception_codes=[])
    s.add(o)
    return o


def _representative_tenant(s) -> dict:
    """Crafted materials on top of the signature case (DC-330 with open PO / in-transit ASN, DC-331 with source lists)."""
    tid = s.info["tenant_id"]
    sup = {x.code: x for x in s.execute(select(Supplier)).scalars()}
    earlier = s.execute(select(MrpRun).where(MrpRun.number == "MR-1043")).scalar_one()
    m = {}
    # 1 contract (TF001, published price), EXACT lot size.
    m["contract"] = _material(s, "MB-CONTRACT")
    contract = Contract(tenant_id=tid, number="MB-SA-1", type="SCHEDULING_AGREEMENT", title="MRP bulk test SA", supplier_id=sup["TF001"].id,
                        company_code="1000", status="ACTIVE", valid_from=RUN_DATE - timedelta(days=30), valid_to=RUN_DATE + timedelta(days=365),
                        payment_terms="N60", owner_id=s.info["user_id"])
    s.add(contract)
    s.flush()
    line = ContractLine(tenant_id=tid, contract_id=contract.id, line_no=10, material_id=m["contract"].id, description="MB-CONTRACT",
                        plant=PLANT, uom="EA", target_qty=Decimal(100_000), released_qty=Decimal(0))
    s.add(line)
    s.flush()
    s.add(PriceValidity(tenant_id=tid, contract_line_id=line.id, valid_from=RUN_DATE - timedelta(days=30), valid_to=RUN_DATE + timedelta(days=40),
                        unit_price_minor=9_900, reason="INITIAL", published=True))
    s.add(PriceValidity(tenant_id=tid, contract_line_id=line.id, valid_from=RUN_DATE + timedelta(days=41), valid_to=RUN_DATE + timedelta(days=365),
                        unit_price_minor=10_400, reason="INDEX_RESET", published=True))
    _demand(s, m["contract"], (10, 300), (60, 500))
    _stock(s, m["contract"], 100)
    # 2 quota 60/40 (TF001 / KD002), FIXED lot size; an unfirmed order of an earlier run is replaced.
    m["quota"] = _material(s, "MB-QUOTA", lot_size_policy="FIXED", lot_size_qty=Decimal(250))
    quota = QuotaArrangement(tenant_id=tid, material_id=m["quota"].id, plant=PLANT, valid_from=RUN_DATE - timedelta(days=5),
                             valid_to=RUN_DATE + timedelta(days=200))
    s.add(quota)
    s.flush()
    s.add_all([QuotaLine(tenant_id=tid, quota_id=quota.id, supplier_id=sup["TF001"].id, share=Decimal("0.6000")),
               QuotaLine(tenant_id=tid, quota_id=quota.id, supplier_id=sup["KD002"].id, share=Decimal("0.4000"))])
    _demand(s, m["quota"], (20, 333))
    m["stale"] = _order(s, m["quota"], earlier.id, "MB-PLO-STALE", 100, 20, "CREATED")
    # 3 source list: fixed HTS004 (not registered for the category, excluded), then KD002 with an info record; MINMAX.
    m["srclist"] = _material(s, "MB-SRCLIST", lot_size_policy="MINMAX", max_lot=Decimal(900))
    for code, fixed in (("HTS004", True), ("KD002", False)):
        s.add(SourceList(tenant_id=tid, supplier_id=sup[code].id, material_id=m["srclist"].id, plant=PLANT, fixed=fixed,
                         valid_from=RUN_DATE - timedelta(days=1), valid_to=RUN_DATE + timedelta(days=90)))
    s.add(InfoRecord(tenant_id=tid, supplier_id=sup["KD002"].id, material_id=m["srclist"].id, plant=PLANT, last_price_minor=8_800, lead_time_days=7))
    _demand(s, m["srclist"], (15, 400), (45, 200))
    # 4 info records: the cheapest supplier is blocked (excluded), the next one wins; EOQ with pack size.
    m["info"] = _material(s, "MB-INFO", lot_size_policy="EOQ", annual_demand=Decimal(12_000), ordering_cost_minor=150_000,
                          holding_rate=Decimal("0.2000"), pack_size=Decimal(25))
    blocked = Supplier(tenant_id=tid, code="MBBLK9", legal_name="MRP Bulk Blocked Supplier Pvt Ltd", status="BLOCKED")
    s.add(blocked)
    s.flush()
    s.add(InfoRecord(tenant_id=tid, supplier_id=blocked.id, material_id=m["info"].id, plant=PLANT, last_price_minor=5_000, lead_time_days=5))
    s.add(InfoRecord(tenant_id=tid, supplier_id=sup["TF001"].id, material_id=m["info"].id, plant=PLANT, last_price_minor=6_000, lead_time_days=6))
    _demand(s, m["info"], (30, 120))
    # 5 no source; PAST_DUE (needed inside the lead time) and BELOW_SAFETY with a minimum lot.
    m["none"] = _material(s, "MB-NONE", min_lot=Decimal(500), planned_delivery_days=20)
    _demand(s, m["none"], (2, 40), (35, 60))
    _stock(s, m["none"], 10)
    _stock(s, m["none"], 999, "BLOCKED")  # not available to MRP
    # 6 firmed orders: reschedule in, reschedule out, cancel.
    m["in"] = _material(s, "MB-RESCHED-IN")
    _demand(s, m["in"], (10, 200), (80, 100))
    _stock(s, m["in"], 50)
    _order(s, m["in"], earlier.id, "MB-PLO-IN", 400, 50, "FIRMED")
    m["out"] = _material(s, "MB-RESCHED-OUT")
    _demand(s, m["out"], (40, 200))
    _stock(s, m["out"], 60)
    _order(s, m["out"], earlier.id, "MB-PLO-OUT", 200, 5, "FIRMED")
    m["cancel"] = _material(s, "MB-CANCEL")
    _demand(s, m["cancel"], (12, 100))
    _stock(s, m["cancel"], 500)
    _order(s, m["cancel"], earlier.id, "MB-PLO-CANCEL", 300, 12, "FIRMED")
    # Not planned: inactive, or no MRP (their unfirmed order must survive).
    m["inactive"] = _material(s, "MB-INACTIVE", status="BLOCKED")
    _demand(s, m["inactive"], (5, 100))
    m["inactive_order"] = _order(s, m["inactive"], earlier.id, "MB-PLO-INACTIVE", 100, 5, "CREATED")
    s.flush()
    s.expire_all()  # reload as a run sees them (NUMERIC(18,3) scale, server defaults)
    return m


def _serialise(result: dict) -> dict:  # exactly as planning.run stores mrp_run.results
    return ({k: (str(v) if isinstance(v, Decimal) else v) for k, v in result.items() if k not in ("proposals", "exceptions")}
            | {"proposals": [{k: str(v) for k, v in pr.items()} for pr in result["proposals"]], "exceptions": result["exceptions"]})


def _run_and_reference(s, mode: str = "REGENERATIVE", materials=None):
    """The bulk run, then the per-material reference computed in the same transaction from the same rows."""
    next_before = s.execute(select(NumberRange.next_value).where(NumberRange.object_type == "PLANNED_ORDER")).scalar_one()
    created_before = {o.number: o.row_version for o in s.execute(select(PlannedOrder).where(
        PlannedOrder.plant == PLANT, PlannedOrder.status == "CREATED")).scalars()}
    run = planning.run(s, plant=PLANT, mode=mode, materials=materials, run_date=RUN_DATE)
    s.flush()
    numbers = [r["material"] for r in run.results]
    by_number = {x.number: x for x in s.execute(select(Material).where(Material.number.in_(numbers))).scalars()}
    reference = [planning.net_material(s, by_number[n], PLANT, RUN_DATE) for n in numbers]  # one query per read
    return run, reference, by_number, next_before, created_before


def test_bulk_run_equals_per_material_reads(sc):
    try:
        with sc.act("mrp.controller", WHEN) as s:
            crafted = _representative_tenant(s)
            run, reference, materials, next_before, created_before = _run_and_reference(s)

            # Netting trace: identical to the per-material reads, material by material, in the same order.
            assert run.results == [_serialise(r) for r in reference]
            assert {"DC-330", "DC-331", "MB-CONTRACT", "MB-QUOTA", "MB-NONE"} <= set(materials) and "MB-INACTIVE" not in materials

            # Planned orders: one per proposal, consecutive numbers from the range, the per-call source determination.
            orders = s.execute(select(PlannedOrder).where(PlannedOrder.mrp_run_id == run.id).order_by(PlannedOrder.number)).scalars().all()
            expected = []
            for result in reference:
                m = materials[result["material"]]
                past_due = [e["code"] for e in result["exceptions"] if e["code"] == "PAST_DUE"]
                for pr in result["proposals"]:
                    determination = source.determine(s, m, PLANT, pr["need_date"], pr["qty"])  # default lookup: per-call queries
                    expected.append((m.id, pr["qty"], pr["need_date"], pr["release_date"], determination.as_dict(), past_due))
            assert [(o.material_id, o.qty, o.need_date, o.release_date, o.source, o.exception_codes) for o in orders] == expected
            assert run.planned_orders_created == len(orders) > 0
            prefix = orders[0].number.rstrip("0123456789")
            assert [int(o.number[len(prefix):]) for o in orders] == list(range(next_before, next_before + len(orders)))
            assert s.execute(select(NumberRange.next_value).where(NumberRange.object_type == "PLANNED_ORDER")).scalar_one() == next_before + len(orders)
            assert {(o.status, o.storage_location, o.plant, o.row_version, o.source_system, o.created_by) for o in orders} == \
                {("CREATED", "0001", PLANT, 1, "PLATFORM", s.info["user_id"])}

            # Exceptions: one row per netting exception, in material order, value at risk = standard price x net.
            rows = s.execute(select(MrpException).where(MrpException.mrp_run_id == run.id).order_by(MrpException.id)).scalars().all()
            assert [(e.material_id, e.code, e.message, e.recommended_action, e.value_at_risk_minor, e.status) for e in rows] == [
                (materials[r["material"]].id, x["code"], x["message"], x["action"],
                 int(Decimal(materials[r["material"]].standard_price_minor or 0) * r["net"]), "OPEN")
                for r in reference for x in r["exceptions"]]
            assert run.exceptions_raised == len(rows)

            # Lineage: one planned_by link per order.
            links = s.execute(select(DocumentLink).where(DocumentLink.from_id == run.id)).scalars().all()
            assert sorted((l.from_type, l.from_ref, l.to_type, l.to_ref, l.link_type) for l in links) == \
                [("MRP_RUN", run.number, "PLANNED_ORDER", o.number, "planned_by") for o in orders]
            assert {l.to_id for l in links} == {o.id for o in orders}

            # Unfirmed orders of planned materials are replaced (version bumped); others are untouched.
            after = {o.number: (o.status, o.row_version) for o in s.execute(select(PlannedOrder).where(
                PlannedOrder.number.in_(list(created_before)))).scalars()}
            planned_ids = {m.id for m in materials.values()}
            for number, version in created_before.items():
                order = s.execute(select(PlannedOrder).where(PlannedOrder.number == number)).scalar_one()
                assert after[number] == (("DELETED", version + 1) if order.material_id in planned_ids else ("CREATED", version)), number
            s.refresh(crafted["stale"])
            assert (crafted["stale"].status, crafted["stale"].row_version) == ("DELETED", 2)
            assert after["MB-PLO-INACTIVE"] == ("CREATED", 1)

            # The representative cases really exercise every branch.
            by_material = {}
            for o in orders:
                by_material.setdefault(o.material_id, []).append(o)
            method = {n: {o.source["method"] for o in by_material.get(materials[n].id, [])} for n in materials}
            assert method["MB-CONTRACT"] == {"CONTRACT"} and method["MB-QUOTA"] == {"QUOTA"} and method["MB-NONE"] == {"NONE"}
            assert method["MB-SRCLIST"] == {"SOURCE_LIST"} and method["MB-INFO"] == {"INFO_RECORD"}
            quota_order = by_material[materials["MB-QUOTA"].id][0]
            assert quota_order.qty == Decimal(500)  # 333 + 50 safety, FIXED 250 -> 500
            assert [(a["supplier"], Decimal(a["qty"]), Decimal(a["share"])) for a in quota_order.source["allocations"]] == \
                [("TF001", 300, Decimal("0.6")), ("KD002", 200, Decimal("0.4"))]
            assert [x["supplier"] for x in by_material[materials["MB-SRCLIST"].id][0].source["excluded"]] == ["HTS004"]  # not qualified for the category
            assert {a["supplier"] for o in by_material[materials["MB-SRCLIST"].id] for a in o.source["allocations"]} == {"KD002"}
            assert by_material[materials["MB-INFO"].id][0].source["excluded"] == [{"supplier": "MBBLK9", "status": "BLOCKED"}]
            assert {a["unitPriceMinor"] for o in by_material[materials["MB-CONTRACT"].id] for a in o.source["allocations"]} == {9_900, 10_400}
            codes = {}
            for e in rows:
                codes.setdefault(e.material_id, set()).add(e.code)
            assert {"BELOW_SAFETY", "PAST_DUE"} <= codes[materials["MB-NONE"].id]
            assert codes[materials["MB-RESCHED-IN"].id] == {"RESCHEDULE_IN"}
            assert codes[materials["MB-RESCHED-OUT"].id] == {"RESCHEDULE_OUT"}
            assert codes[materials["MB-CANCEL"].id] == {"CANCEL"}
            dc330 = next(r for r in run.results if r["material"] == "DC-330")
            assert Decimal(dc330["open_po"]) + Decimal(dc330["in_transit"]) > 0  # signature-case open supply is read in bulk too

            # Run-level audit, outbox and process steps: once per run, as before.
            instance = s.execute(select(ProcessInstance).where(ProcessInstance.business_id == run.id)).scalar_one()
            steps = s.execute(select(ProcessStep.step_id).where(ProcessStep.instance_id == instance.id).order_by(ProcessStep.entered_at, ProcessStep.id)).scalars().all()
            assert steps[-6:] == ["F1-02", "F1-03", "F1-04", "F1-05", "F1-06", "F1-07"] and steps.count("F1-04") == 1
            assert [t for t in s.execute(select(OutboxEvent.topic).where(OutboxEvent.object_id == run.id)).scalars()] == ["mrp.run.completed"]
            assert [a for a in s.execute(select(AuditEvent.action).where(AuditEvent.object_id == run.id)).scalars()] == ["COMPLETED"]
            raise _Rollback
    except _Rollback:
        pass


def test_bulk_run_equals_per_material_reads_for_scoped_and_simulation_runs(sc):
    """Scoped runs load by material id (small scopes) or the whole plant (large ones): both give the same plan."""
    try:
        with sc.act("mrp.controller", WHEN) as s:
            _representative_tenant(s)
            scope = ["MB-QUOTA", "MB-RESCHED-OUT", "DC-330"]
            run, reference, _, _, _ = _run_and_reference(s, "REGENERATIVE", scope)
            assert run.results == [_serialise(r) for r in reference] and {r["material"] for r in run.results} == set(scope)
            simulation, reference, _, _, _ = _run_and_reference(s, "SIMULATION")
            assert simulation.results == [_serialise(r) for r in reference] and simulation.status == "SIMULATED"
            assert not s.execute(select(PlannedOrder.id).where(PlannedOrder.mrp_run_id == simulation.id)).first()
            assert not s.execute(select(MrpException.id).where(MrpException.mrp_run_id == simulation.id)).first()
            raise _Rollback
    except _Rollback:
        pass
    sources = {}
    for limit in (0, planning.BULK_SCOPE_LIMIT):  # 0: every run loads the whole plant
        saved = planning.BULK_SCOPE_LIMIT
        planning.BULK_SCOPE_LIMIT = limit
        try:
            with sc.act("mrp.controller", WHEN) as s:
                _representative_tenant(s)
                run = planning.run(s, plant=PLANT, mode="REGENERATIVE", materials=["MB-CONTRACT", "MB-SRCLIST", "MB-CANCEL"], run_date=RUN_DATE)
                s.flush()
                contract_id = str(s.execute(select(Contract.id).where(Contract.number == "MB-SA-1")).scalar_one())  # new each pass
                sources[limit] = (run.results, [(o.qty, o.need_date, json.loads(json.dumps(o.source).replace(contract_id, "MB-SA-1")))
                                                for o in s.execute(select(PlannedOrder).where(
                    PlannedOrder.mrp_run_id == run.id).order_by(PlannedOrder.number)).scalars()])
                raise _Rollback
        except _Rollback:
            pass
        finally:
            planning.BULK_SCOPE_LIMIT = saved
    assert sources[0] == sources[planning.BULK_SCOPE_LIMIT] and sources[0][1]


def test_preloaded_lookup_matches_per_call_queries_and_falls_back_outside_its_scope(sc):
    try:
        with sc.act("mrp.controller", WHEN) as s:
            m = _representative_tenant(s)
            dc331 = s.execute(select(Material).where(Material.number == "DC-331")).scalar_one()
            lookup = source.Preloaded(s, PLANT, [m["contract"].id, m["quota"].id, m["srclist"].id])
            for material in (m["contract"], m["quota"], m["srclist"], m["info"], m["none"], dc331):  # the last three: fallback
                for days in (0, 30, 60, 200, 400):
                    on = RUN_DATE + timedelta(days=days)
                    assert source.determine(s, material, PLANT, on, Decimal(777), lookup=lookup).as_dict() == \
                        source.determine(s, material, PLANT, on, Decimal(777)).as_dict(), (material.number, days)
            # Two quota arrangements valid on the same day: the same error as the per-call query.
            s.add(QuotaArrangement(tenant_id=s.info["tenant_id"], material_id=m["quota"].id, plant=PLANT,
                                   valid_from=RUN_DATE, valid_to=RUN_DATE + timedelta(days=10)))
            s.flush()
            with pytest.raises(MultipleResultsFound):
                source.determine(s, m["quota"], PLANT, RUN_DATE + timedelta(days=1), Decimal(1))
            with pytest.raises(MultipleResultsFound):
                source.determine(s, m["quota"], PLANT, RUN_DATE + timedelta(days=1), Decimal(1), lookup=source.Preloaded(s, PLANT))
            raise _Rollback
    except _Rollback:
        pass


def test_next_numbers_and_link_many_match_their_single_row_forms(sc):
    try:
        with sc.act("mrp.controller", WHEN) as s:
            singles = [next_number(s, "PLANNED_ORDER") for _ in range(3)]
            block = next_numbers(s, "PLANNED_ORDER", 4)
            prefix = singles[0].rstrip("0123456789")
            values = [int(n[len(prefix):]) for n in singles + block]
            assert values == list(range(values[0], values[0] + 7)) and all(n.startswith(prefix) for n in block)
            assert int(next_number(s, "PLANNED_ORDER")[len(prefix):]) == values[-1] + 1
            assert next_numbers(s, "PLANNED_ORDER", 0) == []
            run = s.execute(select(MrpRun).where(MrpRun.number == "MR-1043")).scalar_one()
            orders = s.execute(select(PlannedOrder).where(PlannedOrder.mrp_run_id == run.id)).scalars().all()
            assert link_many(s, "MRP_RUN", run.id, run.number, [("PLANNED_ORDER", o.id, o.number) for o in orders], "test_link") == len(orders)
            rows = s.execute(select(DocumentLink).where(DocumentLink.link_type == "test_link")).scalars().all()
            assert {(l.tenant_id, l.from_type, l.from_id, l.from_ref, l.to_type, l.to_ref, l.created_by, l.from_line, l.to_line) for l in rows} == \
                {(s.info["tenant_id"], "MRP_RUN", run.id, run.number, "PLANNED_ORDER", o.number, s.info["user_id"], None, None) for o in orders}
            assert all(l.created_at is not None for l in rows)
            raise _Rollback
    except _Rollback:
        pass
    with sc.act("mrp.controller", WHEN) as s:
        assert s.execute(select(func.count()).select_from(DocumentLink).where(DocumentLink.link_type == "test_link")).scalar() == 0


# ---------------------------------------------------------------- serialisation fast paths (large MRP responses)
def _jsonable_reference(value):  # the previous platform/serialize.jsonable, kept as the oracle
    import uuid as _uuid
    from datetime import datetime as _datetime
    if isinstance(value, (_uuid.UUID,)):
        return str(value)
    if isinstance(value, _datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        normalised = value.normalize()
        return format(normalised, "f") if normalised == normalised.to_integral() else str(normalised)
    if isinstance(value, bytes):
        return None
    if isinstance(value, dict):
        return {k: _jsonable_reference(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable_reference(v) for v in value]
    return value


def test_jsonable_and_row_fast_paths_match_the_reference(sc):
    import enum
    import uuid as _uuid
    from collections import OrderedDict, defaultdict

    from app.pic.models import AppUser
    from app.pic.platform.serialize import SECRET_SUFFIXES, SKIP, jsonable, row

    class Code(str, enum.Enum):
        A = "A"

    class Level(enum.IntEnum):
        HIGH = 3

    nested = defaultdict(list, {"x": [Decimal("1.500"), Decimal("2.000"), Decimal("1E+2")]})
    values = ["s", "", 0, 7, -1.5, True, False, None, Code.A, Level.HIGH, Decimal("0.000"), Decimal("12.340"), _uuid.uuid7(),
              clock.at_ist(RUN_DATE, 9), RUN_DATE, b"secret", (1, Decimal("2.50")), {3, 4}, [None, [Decimal("1"), {"k": RUN_DATE}]],
              {"a": {"b": [Decimal("3.10"), _uuid.UUID(int=5)], "c": Code.A}}, OrderedDict(z=Decimal("9.9")), nested, object]
    for value in values:
        assert jsonable(value) == _jsonable_reference(value) and type(jsonable(value)) is type(_jsonable_reference(value)), value

    def row_reference(obj, only=None, extra=None):
        from sqlalchemy import inspect
        mapper = inspect(obj).mapper
        keys = list(only) if only else [c.key for c in mapper.column_attrs]
        out = {k: _jsonable_reference(getattr(obj, k)) for k in keys if k not in SKIP and not k.endswith(SECRET_SUFFIXES)}
        if extra:
            out.update(_jsonable_reference(extra))
        return out

    with sc.act("mrp.controller", WHEN) as s:
        objects = [s.execute(select(AppUser)).scalars().first(), s.execute(select(Supplier)).scalars().first(),
                   s.execute(select(MrpRun).where(MrpRun.number == "MR-1043")).scalar_one(),
                   *s.execute(select(PlannedOrder).limit(5)).scalars()]
        for obj in objects:
            assert row(obj) == row_reference(obj) and list(row(obj)) == list(row_reference(obj))
            assert "password_hash" not in row(obj) and "tenant_id" not in row(obj) and "row_version" not in row(obj)
            assert row(obj, only=["id", "tenant_id", "created_at"], extra={"n": Decimal("1.0")}) == \
                row_reference(obj, only=["id", "tenant_id", "created_at"], extra={"n": Decimal("1.0")})
        assert row(None) is None


def test_release_dates_are_memoised_per_run_with_the_plant_calendar(sc):
    with sc.act("mrp.controller", WHEN) as s:
        reads = planning._Reads(s, PLANT)
        working_days, holidays = reads.calendar()
        for day in (RUN_DATE + timedelta(days=d) for d in range(0, 120, 7)):
            for lead in (0, 1, 6, 11, 30):
                expected = clock.subtract_working_days(day, lead, working_days, holidays)
                assert reads.release_date(day, lead) == expected and reads.release_date(day, lead) == expected
        assert len(reads._releases) == 18 * 5


def test_subtract_working_days_matches_the_day_by_day_calendar_test():
    def reference(d, days, working_days, holidays):  # the previous implementation: is_working_day per day
        current, remaining = d, days
        while remaining > 0:
            current -= timedelta(days=1)
            if clock.is_working_day(current, working_days, holidays):
                remaining -= 1
        return current

    holidays = [date(2026, 10, 2), date(2026, 10, 20), date(2026, 10, 21), date(2026, 11, 1), date(2026, 12, 25), date(2027, 1, 15)]
    for working_days in ([0, 1, 2, 3, 4, 5], [0, 1, 2, 3, 4], [5, 6], [2]):
        for offset in range(0, 120, 3):
            for lead in (0, 1, 2, 5, 13, 40):
                day = date(2026, 10, 1) + timedelta(days=offset)
                assert clock.subtract_working_days(day, lead, working_days, holidays) == reference(day, lead, working_days, holidays)
    assert clock.subtract_working_days(date(2026, 10, 22), 1) == date(2026, 10, 21)  # defaults: Mon–Sat, no holidays


def test_mrp_run_view_from_column_selects_equals_the_orm_rows(sc):
    from app.pic import views
    from app.pic.platform.serialize import row

    def reference(s, run):  # the previous views.mrp_run: ORM objects through row()
        orders = s.execute(select(PlannedOrder).where(PlannedOrder.mrp_run_id == run.id)).scalars().all()
        exceptions = s.execute(select(MrpException).where(MrpException.mrp_run_id == run.id)).scalars().all()
        materials = {m.id: m.number for m in s.execute(select(Material)).scalars()}
        prs = {r.id: r.number for r in s.execute(select(Requisition).where(
            Requisition.id.in_([o.requisition_id for o in orders if o.requisition_id]))).scalars()}
        return row(run, extra={
            "plannedOrders": [row(o, extra={"material": materials.get(o.material_id), "requisition": prs.get(o.requisition_id)}) for o in orders],
            "exceptions": [row(e, extra={"material": materials.get(e.material_id)}) for e in exceptions],
            "process": views._process(s, "MRP_RUN", run)})

    from app.pic.models import Requisition
    try:
        with sc.act("mrp.controller", WHEN) as s:
            signature = s.execute(select(MrpRun).where(MrpRun.number == "MR-1043")).scalar_one()  # converted order with its PR
            got = views.mrp_run(s, signature)
            assert got == reference(s, signature) and any(o["requisition"] for o in got["plannedOrders"])
            _representative_tenant(s)
            run = planning.run(s, plant=PLANT, mode="REGENERATIVE", run_date=RUN_DATE)
            got = views.mrp_run(s, run)
            assert got == reference(s, run) and len(got["plannedOrders"]) == run.planned_orders_created
            expected = reference(s, run)
            assert list(got) == list(expected) and [list(o) for o in got["plannedOrders"]] == [list(o) for o in expected["plannedOrders"]]
            assert [list(e) for e in got["exceptions"]] == [list(e) for e in expected["exceptions"]]  # key order too
            raise _Rollback
    except _Rollback:
        pass


NOTE = "ünïcödé \\ backslash, \"double\" and 'single' quotes, {braces}, comma, NULL"


def test_insert_rows_stores_what_a_core_insert_stores(sc):
    """core.insert_rows (unnest arrays) vs session.execute(insert(table), rows): same values, defaults and bind processing."""
    from sqlalchemy import insert

    from app.pic.platform.core import insert_rows

    def logical(s, model, ids):  # every column but the generated id / created_at
        cols = [c for c in model.__table__.columns if c.key not in ("id", "created_at", "number")]
        got = s.execute(select(*cols).where(model.__table__.c.id.in_(ids)).order_by(model.__table__.c.id)).all()
        return [tuple(r) for r in got]

    try:
        with sc.act("mrp.controller", WHEN) as s:
            tid, uid = s.info["tenant_id"], s.info["user_id"]
            run = s.execute(select(MrpRun).where(MrpRun.number == "MR-1043")).scalar_one()
            material = s.execute(select(Material).where(Material.number == "DC-330")).scalar_one()
            import uuid as _uuid

            def orders(prefix):
                return [{"id": _uuid.uuid7(), "tenant_id": tid, "number": f"{prefix}-{i}", "mrp_run_id": run.id, "material_id": material.id,
                         "plant": PLANT, "storage_location": "0001", "qty": q, "need_date": RUN_DATE + timedelta(days=i),
                         "release_date": RUN_DATE, "source": src, "exception_codes": codes, "created_by": uid}
                        for i, (q, src, codes) in enumerate([(Decimal("383.000"), {"method": "NONE", "allocations": [], "excluded": []}, []),
                                                             (Decimal("0.125"), {"method": "QUOTA", "allocations": [{"qty": "1", "share": "0.6"}],
                                                                                 "excluded": [{"supplier": "X'Y", "status": "BLOCKED"}]}, ["PAST_DUE"]),
                                                             (Decimal("123456789012.5"), {"note": NOTE}, None)])]
            core, bulk = orders("MB-CORE"), orders("MB-BULK")
            s.execute(insert(PlannedOrder.__table__), core)
            assert insert_rows(s, PlannedOrder.__table__, bulk, batch=2) == 3
            assert logical(s, PlannedOrder, [r["id"] for r in core]) == logical(s, PlannedOrder, [r["id"] for r in bulk])
            stored = s.execute(select(PlannedOrder).where(PlannedOrder.number == "MB-BULK-2")).scalar_one()
            assert (stored.status, stored.source_system, stored.row_version, stored.exception_codes) == ("CREATED", "PLATFORM", 1, None)
            assert stored.created_at is not None and stored.source == {"note": NOTE}
            assert s.execute(select(func.count()).select_from(PlannedOrder).where(PlannedOrder.number.like("MB-BULK-%"))).scalar() == 3
            exc = [{"tenant_id": tid, "mrp_run_id": run.id, "material_id": material.id, "code": "CANCEL", "message": "m", "value_at_risk_minor": 7,
                    "recommended_action": "a", "status": "OPEN", "created_by": uid, "planned_order_id": None}]
            s.execute(insert(MrpException.__table__), [dict(exc[0], id=_uuid.uuid7())])
            insert_rows(s, MrpException.__table__, [dict(exc[0], id=_uuid.uuid7())])
            rows = s.execute(select(MrpException).where(MrpException.message == "m", MrpException.mrp_run_id == run.id)).scalars().all()
            assert len(rows) == 2 and len({(r.code, r.value_at_risk_minor, r.status, r.row_version, r.created_by) for r in rows}) == 1
            with pytest.raises(ValueError):
                insert_rows(s, MrpException.__table__, [dict(exc[0], id=_uuid.uuid7()), {"code": "X"}])
            with pytest.raises(Exception):  # VARCHAR(30) still enforced (no silent truncation by the array cast)
                with s.begin_nested():
                    insert_rows(s, PlannedOrder.__table__, [dict(orders("MB-LONG")[0], number="N" * 31)])
            raise _Rollback
    except _Rollback:
        pass
