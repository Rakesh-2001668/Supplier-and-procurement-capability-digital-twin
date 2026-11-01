"""Wave 1 (engineer C2): spend cube at scale, savings pipeline and P&L, KPI framework, saved views, object-page tabs, bulk decisions."""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, text

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    FxRate, SavedView, SavingsLedgerEntry, SpendCommitmentSummary, SpendCubeSummary, SpendLine, SpendViewDirty, Supplier, Tenant,
)
from app.pic.platform import clock
from app.pic.platform.errors import Problem
from app.pic.seed import reference
from app.pic.services import kpi, spend, spend_cube, workspace


@pytest.fixture(scope="module")
def axn(database):
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()


@pytest.fixture(scope="module")
def own(database):
    """A tenant of this file's own (no signature-case data) with three suppliers, one parent link and a USD currency."""
    tenant_id = reference.create_tenant("C2K", "C2 Cube Test Co", "GENERAL", mfa_enforce=False)
    reference.bootstrap(tenant_id, company=("1000", "C2 Cube Test Co", None), plants=[("P1", "Plant 1", "33"), ("P2", "Plant 2", "29")],
                        cost_objects=[("COST_CENTER", "CC1", "Cost centre 1"), ("WBS", "W1", "Project W1")])
    with tenant_tx(tenant_id) as s:
        for code in ("PARENT", "CHILD1", "CHILD2"):
            s.add(Supplier(tenant_id=tenant_id, code=code, legal_name=f"{code} Pvt Ltd", status="QUALIFIED"))
        s.flush()
        parent = s.execute(select(Supplier).where(Supplier.code == "PARENT")).scalar_one()
        for code in ("CHILD1", "CHILD2"):
            s.execute(select(Supplier).where(Supplier.code == code)).scalar_one().parent_supplier_id = parent.id
    return tenant_id


def _line(tenant_id, supplier_id, *, period="2026-08", category="ALU-DIECAST", amount=1_000_00, plant="P1", currency="INR", **kw):
    ref = f"C2-{uuid.uuid4().hex[:10]}"
    return SpendLine(tenant_id=tenant_id, invoice_line_id=uuid.uuid4(), invoice_ref=ref, po_ref=f"PO-{ref}", supplier_id=supplier_id, category=category,
                     material_group=category, plant=plant, company_code="1000", period=period, amount_minor=amount, currency=currency, **kw)


def _suppliers(tenant_id):
    with tenant_tx(tenant_id) as s:
        return {x.code: x.id for x in s.execute(select(Supplier)).scalars()}


# ---------------------------------------------------------------- spend cube: summaries, filters, hierarchy, currency
def test_cube_matches_the_source_lines_and_every_dimension_adds_up(axn):
    with tenant_tx(axn) as s:
        expected = s.execute(select(func.sum(SpendLine.amount_minor))).scalar()
        lines = s.execute(select(func.count()).select_from(SpendLine)).scalar()
        by_category = spend_cube.cube(s, ["category"], limit=5000)
        assert by_category["totalMinor"] == expected and by_category["totals"]["lines"] == lines
        assert sum(r["spendMinor"] for r in by_category["rows"]) == expected
        for dims in (["category_l1"], ["category_l2", "plant"], ["supplier"], ["parent_supplier", "currency"], ["period", "contracted"], ["source_system"]):
            cube = spend_cube.cube(s, dims, limit=5000)
            assert cube["totalMinor"] == expected and sum(r["spendMinor"] for r in cube["rows"]) == expected, dims
        assert {r["category_l1"] for r in spend_cube.cube(s, ["category_l1"])["rows"]} >= {"DIRECT"}


def test_unknown_dimension_and_limit_are_refused(axn):
    with tenant_tx(axn) as s:
        with pytest.raises(Problem) as exc:
            spend_cube.cube(s, ["colour"])
        assert exc.value.code == "INVALID_DIMENSION"
        with pytest.raises(Problem) as exc:
            spend_cube.cube(s, ["category"], limit=0)
        assert exc.value.code == "INVALID_LIMIT"


def test_filters_by_category_level_supplier_plant_and_period(axn):
    with tenant_tx(axn) as s:
        everything = spend_cube.cube(s, ["category"], limit=5000)
        direct = spend_cube.cube(s, ["category"], spend_cube.CubeFilter(categories=["DIRECT"]), limit=5000)
        assert direct["rows"] and direct["totalMinor"] < everything["totalMinor"]
        window = spend_cube.cube(s, ["period"], spend_cube.CubeFilter(period_from="2026-01", period_to="2026-03"), limit=5000)
        assert window["rows"] and all("2026-01" <= r["period"] <= "2026-03" for r in window["rows"])
        none = spend_cube.cube(s, ["category"], spend_cube.CubeFilter(plants=["NOPLANT"]))
        assert none["rows"] == [] and none["totalMinor"] == 0


def test_parent_child_rollup_currency_and_fx_missing(own):
    ids = _suppliers(own)
    with tenant_tx(own) as s:
        s.add_all([
            _line(own, ids["CHILD1"], amount=10_000_00, cost_object="CC1", cost_object_type="COST_CENTER"),
            _line(own, ids["CHILD2"], amount=5_000_00, cost_object="W1", cost_object_type="WBS", contracted=True, plant="P2"),
            _line(own, ids["PARENT"], amount=2_000_00, source_system="SAP-EU"),
            # USD line converted at posting: 100.00 USD x 83.25 = 8,325.00 INR, rate and date stored on the line
            _line(own, ids["CHILD1"], amount=100_00, currency="USD", fx_rate=Decimal("83.25"), fx_date=date(2026, 8, 31), amount_group_minor=8_325_00),
            # USD line with no rate on its date: counted as missing, never guessed
            _line(own, ids["CHILD2"], amount=50_00, currency="USD", period="2026-09"),
        ])
    with tenant_tx(own) as s:
        assert spend_cube.freshness(s)["stale"]
        cube = spend_cube.cube(s, ["parent_supplier"])
        assert cube["rows"][0]["parent_supplier"] == "PARENT"
        assert cube["rows"][0]["spendMinor"] == 10_000_00 + 5_000_00 + 2_000_00 + 8_325_00 and len(cube["rows"]) == 1
        child = spend_cube.cube(s, ["supplier"])
        assert {r["supplier"] for r in child["rows"]} == {"PARENT", "CHILD1", "CHILD2"}
        assert cube["totals"]["fxMissingLines"] == 1 and cube["currency"] == "INR"
        assert cube["documentCurrencyTotals"]["USD"] == 150_00
        assert spend_cube.cube(s, ["cost_object"], spend_cube.CubeFilter(cost_centres=["CC1"]))["totalMinor"] == 10_000_00
        assert spend_cube.cube(s, ["cost_object"], spend_cube.CubeFilter(wbs=["W1"]))["totalMinor"] == 5_000_00
        assert spend_cube.cube(s, ["plant"], spend_cube.CubeFilter(source_systems=["SAP-EU"]))["totalMinor"] == 2_000_00
        assert spend_cube.cube(s, ["supplier"], spend_cube.CubeFilter(parents=["PARENT"]))["totals"]["lines"] == 5
        assert spend_cube.cube(s, ["plant"], spend_cube.CubeFilter(contracted=True))["totalMinor"] == 5_000_00
    # a rate added later converts the pending line at the next refresh and stores the rate with its date
    with tenant_tx(own) as s:
        s.add(FxRate(tenant_id=own, from_ccy="USD", to_ccy="INR", rate=Decimal("84.00"), valid_from=date(2026, 9, 1), source="test"))
    with tenant_tx(own) as s:
        result = spend_cube.refresh_spend_views(own, full=True, session=s)
        assert result["cube"]["fxConverted"] == 1
        line = s.execute(select(SpendLine).where(SpendLine.currency == "USD", SpendLine.period == "2026-09")).scalar_one()
        assert line.fx_rate == Decimal("84.00000000") and line.amount_group_minor == 4_200_00 and line.fx_date == date(2026, 9, 1)
        assert spend_cube.cube(s, ["currency"])["totals"]["fxMissingLines"] == 0


def test_dirty_periods_are_marked_refreshed_incrementally_and_cleared(own):
    ids = _suppliers(own)
    with tenant_tx(own) as s:
        spend_cube.refresh_spend_views(own, full=True, session=s)
        assert s.execute(select(func.count()).select_from(SpendViewDirty)).scalar() == 0
        s.add(_line(own, ids["PARENT"], period="2026-11", amount=7_000_00))
        s.flush()
        assert s.execute(select(SpendViewDirty.period)).scalars().all() == ["2026-11"]
        before = s.execute(select(func.count()).select_from(SpendCubeSummary).where(SpendCubeSummary.period == "2026-11")).scalar()
        assert before == 0  # summary not rebuilt yet
        result = spend_cube.refresh_spend_views(own, dirty_only=True, session=s)
        assert result["cube"]["mode"] == "PERIODS" and result["cube"]["periods"] == 1
        assert s.execute(select(func.sum(SpendCubeSummary.amount_group_minor)).where(SpendCubeSummary.period == "2026-11")).scalar() == 7_000_00
        assert s.execute(select(func.count()).select_from(SpendViewDirty)).scalar() == 0
        # reading with a small backlog refreshes by itself
        s.add(_line(own, ids["PARENT"], period="2026-12", amount=1_000_00))
        s.flush()
        cube = spend_cube.cube(s, ["period"])
        assert {r["period"] for r in cube["rows"]} >= {"2026-11", "2026-12"} and not cube["freshness"]["stale"]


def test_summaries_are_tenant_isolated(axn, own):
    with tenant_tx(own) as s:
        spend_cube.refresh_spend_views(own, full=True, session=s)
        own_total = s.execute(select(func.sum(SpendCubeSummary.amount_group_minor))).scalar()
        assert s.execute(select(func.count()).select_from(SpendCubeSummary).where(SpendCubeSummary.tenant_id == axn)).scalar() == 0
    with tenant_tx(axn) as s:
        assert s.execute(select(func.count()).select_from(SpendCubeSummary).where(SpendCubeSummary.tenant_id == own)).scalar() == 0
        assert spend_cube.cube(s, ["category"])["totalMinor"] != own_total


def test_overview_is_served_from_the_summary_and_has_the_new_measures(axn):
    with tenant_tx(axn) as s:
        o = spend.overview(s)
        assert o["totalMinor"] > 0 and "priceVarianceMinor" in o and "aggregationOpportunityMinor" in o and "openCommitmentsMinor" in o
        assert o["freshness"]["asOf"] and o["groupCurrency"] == "INR"
        rows = s.execute(text("SELECT count(*) FROM pic.spend_cube_summary")).scalar()
        assert 0 < rows <= s.execute(select(func.count()).select_from(SpendLine)).scalar()


def test_commitments_equal_open_po_value(axn):
    with tenant_tx(axn) as s:
        spend_cube.refresh_spend_views(axn, dirty_only=True, session=s)  # commitments are rebuilt by the job (or on read when older than 5 minutes)
        result = spend_cube.commitments(s, ["supplier"])
        expected = s.execute(text(
            "SELECT coalesce(sum(pl.net_minor - pl.invoiced_minor), 0) FROM pic.po_line pl JOIN pic.purchase_order po ON po.id = pl.po_id "
            "WHERE po.status IN ('RELEASED','TRANSMITTED','CONFIRMED','PARTIALLY_RECEIVED','RECEIVED') AND pl.net_minor > pl.invoiced_minor")).scalar()
        assert result["totals"]["committedMinor"] == int(expected)
        assert s.execute(select(func.count()).select_from(SpendCommitmentSummary)).scalar() > 0


def test_spend_api_analysis_status_and_admin_refresh(client, login):
    r = client.get("/v1/spend/analysis?dims=category_l1,plant&category=DIRECT&commitments=true", headers=login("category.head"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dimensions"] == ["category_l1", "plant"] and body["filters"] == {"categories": ["DIRECT"]} and body["commitments"]["totals"]
    assert client.get("/v1/spend/analysis?dims=nonsense", headers=login("category.head")).status_code == 400
    assert client.get("/v1/spend/analysis?period_from=2026", headers=login("category.head")).status_code == 422
    assert client.get("/v1/spend/analysis", headers=login("buyer")).status_code == 403
    assert client.get("/v1/spend/cube-status", headers=login("cpo")).json()["cube"]["asOf"]
    assert client.post("/v1/admin/spend/refresh", json={}, headers=login("category.head")).status_code == 403
    admin = {**login("admin"), "Idempotency-Key": "c2-refresh-1"}
    first = client.post("/v1/admin/spend/refresh", json={"full": True}, headers=admin)
    assert first.status_code == 200 and first.json()["cube"]["mode"] == "FULL"
    assert client.post("/v1/admin/spend/refresh", json={"full": True}, headers=admin).json()["replayed"] is True
    assert client.post("/v1/admin/spend/refresh", json={"periods": ["2026-13x"]}, headers=login("admin")).status_code == 422
    assert client.get("/v1/spend/cube?dims=category,period", headers=login("category.head")).json()["rows"]  # legacy route still works


# ---------------------------------------------------------------- signature case: Blueprint section 20 figures
def test_signature_savings_and_first_pass_match_the_blueprint(client, login):
    register = client.get("/v1/savings", headers=login("finance.controller")).json()[0]
    assert register["number"] == "SV-0412" and register["negotiatedCr"] == "0.99"
    assert Decimal("0.37") <= Decimal(register["realisedCr"]) <= Decimal("0.39"), register["realisedCr"]  # realised YTD 0.38 Cr
    kpis = client.get("/v1/kpis?module=M10", headers=login("cpo")).json()
    first_pass = next(i for i in kpis["items"] if i["code"] == "M10.FIRST_PASS_MATCH")
    assert round(Decimal(first_pass["value"])) == 86  # first-pass match 86%


def test_legacy_plants_get_the_national_holiday_calendar():
    from app.pic.seed import legacy
    days = legacy._national_holidays()
    assert date(2026, 1, 26) in days and date(2027, 1, 26) in days and days == sorted(set(days)) and 20 < len(days) < 60


# ---------------------------------------------------------------- SPD-08 pipeline and M11-C4 P&L
def test_pipeline_tracker_by_stage_with_filters(client, login):
    h = login("finance.controller")
    full = client.get("/v1/savings/pipeline", headers=h).json()
    stages = {s["stage"]: s for s in full["stages"]}
    assert stages["VALIDATED"]["count"] >= 1 and stages["VALIDATED"]["realisedMinor"] > 0
    assert full["totals"]["realisedMinor"] == sum(i["realisedMinor"] for i in full["initiatives"] if i["stage"] != "LOST")
    register = client.get("/v1/savings", headers=h).json()
    assert full["totals"]["negotiatedMinor"] == sum(r["negotiatedMinor"] for r in register if r["stage"] != "LOST")
    only = client.get("/v1/savings/pipeline?stage=VALIDATED", headers=h).json()
    assert only["initiatives"] and {i["stage"] for i in only["initiatives"]} == {"VALIDATED"}
    category = full["categories"][0]
    assert {i["category"] for i in client.get(f"/v1/savings/pipeline?category={category}", headers=h).json()["initiatives"]} == {category}
    assert client.get("/v1/savings/pipeline?stage=BOGUS", headers=h).status_code == 422
    identified = [i for i in full["initiatives"] if i["stage"] == "IDENTIFIED"]
    assert all(i["forecastBasis"] in ("TARGET", "NONE") for i in identified)


def test_savings_pnl_counts_only_validated_realised_savings(client, login):
    h = login("finance.controller")
    pnl = client.get("/v1/savings/pnl?fiscal_year=2026-27", headers=h).json()
    assert pnl["fiscalYear"] == "2026-27" and len(pnl["months"]) == 12
    totals = pnl["totals"]
    assert totals["budgetImpactMinor"] == totals["validatedMinor"] and totals["realisedMinor"] == totals["validatedMinor"] + totals["pendingValidationMinor"]
    assert totals["negotiatedMinor"] > 0 and totals["avoidanceMinor"] > 0  # reported, never counted in the budget impact


def test_savings_pnl_rejects_a_bad_fiscal_year(client, login):
    assert client.get("/v1/savings/pnl?fiscal_year=2026", headers=login("cpo")).status_code == 422


# ---------------------------------------------------------------- KPI framework
BP_TABLE_28 = {
    "M01": 5, "M02": 5, "M03": 4, "M04": 4, "M05": 4, "M06": 5, "M07": 4, "M08": 4, "M09": 4, "M10": 5, "M11": 4, "M12": 4, "M13": 3,
}


def test_registry_covers_every_kpi_of_blueprint_table_28():
    for module, count in BP_TABLE_28.items():
        codes = [d.code for d in kpi.REGISTRY.values() if d.module == module]
        assert len(codes) >= count, (module, codes)
    assert all(d.unit in kpi.UNITS and d.formula and d.source for d in kpi.REGISTRY.values())
    assert {"TPL.PPV", "TPL.RATE_COMPLIANCE", "TPL.CATALOGUE_ADOPTION", "TPL.COST_TO_COMPLETE", "TPL.COST_PER_TONNE_KM", "TPL.EXPIRY_WRITE_OFFS"} <= set(kpi.REGISTRY)


def test_every_computable_kpi_evaluates_without_error(axn):
    with tenant_tx(axn) as s:
        items = kpi.read(s, with_trend=False, include_other_templates=True)
    broken = [(i["code"], i["detail"]["error"]) for i in items if "error" in i["detail"]]
    assert not broken, broken
    # The three industry KPIs wait for the industry modules to register a compute function (kpi.register); until then they say what they need.
    needs_data = {i["code"] for i in items if i["detail"].get("needs")}
    assert needs_data <= {"TPL.COST_TO_COMPLETE", "TPL.COST_PER_TONNE_KM", "TPL.EXPIRY_WRITE_OFFS"}
    assert all(i["value"] is None and i["status"] == "NA" for i in items if i["code"] in needs_data)


def test_kpi_values_follow_their_formulas(axn):
    with tenant_tx(axn) as s:
        by_code = {i["code"]: i for i in kpi.read(s, with_trend=False, include_other_templates=True)}
        invoices = s.execute(text("SELECT count(*) FILTER (WHERE first_pass_matched), count(*) FROM pic.invoice WHERE first_pass_matched IS NOT NULL")).one()
        released = s.execute(text("SELECT count(*) FILTER (WHERE touchless), count(*) FROM pic.purchase_order WHERE released_at IS NOT NULL")).one()
        rejected = s.execute(text("SELECT sum(l.rejected_qty), sum(l.qty) FROM pic.gr_line l JOIN pic.goods_receipt g ON g.id = l.gr_id WHERE g.reversal_of IS NULL")).one()
        realised = s.execute(select(func.sum(SavingsLedgerEntry.amount_minor)).where(SavingsLedgerEntry.type == "REALISED")).scalar()
    assert Decimal(by_code["M10.FIRST_PASS_MATCH"]["value"]) == (Decimal(invoices[0]) * 100 / invoices[1]).quantize(Decimal("0.1"))
    assert Decimal(by_code["M08.TOUCHLESS_PO"]["value"]) == (Decimal(released[0]) * 100 / released[1]).quantize(Decimal("0.1"))
    assert Decimal(by_code["M09.QUALITY_REJECTION"]["value"]) == (rejected[0] * 100 / rejected[1]).quantize(Decimal("0.1"))
    assert Decimal(by_code["M11.REALISED_SAVINGS"]["value"]) == realised
    assert by_code["M13.SOD_OPEN"]["unit"] == "COUNT" and by_code["M12.HOURS_SAVED"]["detail"]["assumption"]
    assert by_code["M10.FIRST_PASS_MATCH"]["status"] in ("GOOD", "WARN")  # 85.7% against a target of 85


def test_kpi_status_thresholds_and_scope():
    higher = kpi.REGISTRY["M10.FIRST_PASS_MATCH"]
    lower = kpi.REGISTRY["M08.PO_CHANGE_RATE"]
    assert [kpi.status_of(higher, Decimal(v), 85, 70) for v in (90, 75, 50)] == ["GOOD", "WARN", "BAD"]
    assert [kpi.status_of(lower, Decimal(v), 10, 20) for v in (5, 15, 30)] == ["GOOD", "WARN", "BAD"]
    assert kpi.status_of(higher, None, 85, 70) == "NA" and kpi.status_of(kpi.REGISTRY["M03.BANK_FRAUD_BLOCKED"], Decimal(3), None, None) == "NA"


def test_kpi_api_module_filter_detail_plant_scope_and_snapshot(client, login):
    r = client.get("/v1/kpis?module=M04", headers=login("cpo")).json()
    assert {i["code"] for i in r["items"]} == {"M04.CATALOGUE_CHANNEL", "M04.APPROVAL_CYCLE", "M04.FREE_TEXT_PCT", "M04.BUDGET_BLOCKED"}
    assert sum(r["summary"].values()) == 4
    plant = client.get("/v1/kpis?plant=P100", headers=login("cpo")).json()
    assert plant["items"] and all("PLANT" in i["scopes"] for i in plant["items"])
    assert client.get("/v1/kpis/M10.DPO?plant=P100", headers=login("cpo")).status_code == 422
    assert client.get("/v1/kpis/NOPE", headers=login("cpo")).status_code == 404
    assert client.get("/v1/kpis?module=M99", headers=login("cpo")).status_code == 422
    assert client.get("/v1/kpis?period=2027-13", headers=login("cpo")).status_code == 422
    registry = client.get("/v1/kpis/registry", headers=login("cpo")).json()
    assert len(registry) >= 57 and next(x for x in registry if x["code"] == "TPL.COST_TO_COMPLETE")["computable"] in (True, False)
    assert client.post("/v1/admin/kpis/snapshot", json={}, headers=login("cpo")).status_code == 403
    h = {**login("admin"), "Idempotency-Key": "c2-kpi-snap"}
    done = client.post("/v1/admin/kpis/snapshot", json={"period": "2027-03"}, headers=h)
    assert done.status_code == 200 and done.json()["period"] == "2027-03" and done.json()["kpis"] >= 50
    assert client.post("/v1/admin/kpis/snapshot", json={"period": "2027-03"}, headers=h).json()["replayed"] is True
    again = client.post("/v1/admin/kpis/snapshot", json={"period": "2027-03"}, headers=login("admin"))  # same month again: updated, not duplicated
    assert again.status_code == 200
    detail = client.get("/v1/kpis/M10.FIRST_PASS_MATCH", headers=login("cpo")).json()
    assert [h_["period"] for h_ in detail["history"]] == ["2027-03"] and detail["history"][0]["status"] in ("GOOD", "WARN", "BAD")
    trend = client.get("/v1/kpis?module=M10", headers=login("cpo")).json()["items"][0]["trend"]
    assert trend and trend[-1]["period"] == "2027-03"
    monthly = client.get("/v1/kpis/M10.FIRST_PASS_MATCH?period=2027-02", headers=login("cpo")).json()
    assert monthly["period"] == "2027-02" and monthly["value"] is not None  # INV-TF-9031 and the call-off invoices of February


def test_kpi_threshold_override_from_the_rule_set(axn):
    from app.pic.models import RuleSet
    with tenant_tx(axn) as s:
        rule = s.execute(select(RuleSet).where(RuleSet.key == "KPI-THRESHOLDS")).scalars().first()
        assert rule is not None and rule.body["minutesSavedPerAgentRun"] == 6
        original = dict(rule.body)
        rule.body = {**original, "overrides": {"M10.FIRST_PASS_MATCH": {"target": 99, "warn": 95}}}
        s.flush()
        s.expire_all()
        item = kpi.evaluate(s, kpi.REGISTRY["M10.FIRST_PASS_MATCH"])
        assert item["target"] == 99 and item["status"] == "BAD"
        rule.body = original


# ---------------------------------------------------------------- workspace: tenant profile, saved views, tabs, bulk decisions
def test_tenant_profile_names_the_industry_template(client, login):
    body = client.get("/v1/tenant", headers=login("buyer")).json()
    assert body["code"] == "AXN" and body["industryTemplate"] == "MANUFACTURING" and body["templateLabel"] == "Manufacturing" and body["baseCurrency"] == "INR"


def test_saved_views_crud_etag_sharing_and_validation(client, login):
    mine, other = login("buyer"), login("category.head")
    created = client.post("/v1/saved-views", json={"screen": "tasks", "name": "Overdue approvals", "filters": {"overdue": True}, "is_default": True},
                          headers={**mine, "Idempotency-Key": "c2-sv-1"})
    assert created.status_code == 201, created.text
    view = created.json()
    assert client.post("/v1/saved-views", json={"screen": "tasks", "name": "Overdue approvals", "filters": {"overdue": True}, "is_default": True},
                       headers={**mine, "Idempotency-Key": "c2-sv-1"}).json()["replayed"] is True  # same key, same body: replayed
    assert client.post("/v1/saved-views", json={"screen": "tasks", "name": "overdue approvals", "filters": {}}, headers=mine).status_code == 409
    assert client.post("/v1/saved-views", json={"screen": "nowhere", "name": "x", "filters": {}}, headers=mine).status_code == 422
    assert client.post("/v1/saved-views", json={"screen": "tasks", "name": "x", "filters": {"k": "v" * 5000}}, headers=mine).status_code == 422
    second = client.post("/v1/saved-views", json={"screen": "tasks", "name": "All", "filters": {}, "is_default": True}, headers=mine).json()
    listed = {v["name"]: v for v in client.get("/v1/saved-views?screen=tasks", headers=mine).json()}
    assert listed["All"]["isDefault"] and not listed["Overdue approvals"]["isDefault"]  # one default per screen
    assert client.get("/v1/saved-views?screen=tasks", headers=other).json() == []  # private to the owner
    stale = client.patch(f"/v1/saved-views/{view['id']}", json={"shared": True}, headers={**mine, "If-Match": '"99"'})
    assert stale.status_code == 412
    ok = client.patch(f"/v1/saved-views/{view['id']}", json={"shared": True, "name": "Overdue"}, headers={**mine, "If-Match": view["etag"]})
    assert ok.status_code == 200 and ok.json()["shared"] is True and ok.headers["ETag"]
    shared = client.get("/v1/saved-views?screen=tasks", headers=other).json()
    assert [v["name"] for v in shared] == ["Overdue"] and shared[0]["mine"] is False
    assert client.patch(f"/v1/saved-views/{view['id']}", json={"name": "Hijack"}, headers=other).status_code == 403
    assert client.delete(f"/v1/saved-views/{view['id']}", headers=other).status_code == 403
    assert client.delete(f"/v1/saved-views/{view['id']}", headers=mine).status_code == 204
    assert client.delete(f"/v1/saved-views/{second['id']}", headers=mine).status_code == 204
    assert client.get("/v1/saved-views?screen=tasks", headers=mine).json() == []


def test_saved_view_limit_per_screen(axn):
    with tenant_tx(axn) as s:
        from app.pic.models import AppUser
        user = s.execute(select(AppUser).where(AppUser.email == "buyer@axion.example")).scalar_one()
        from app.pic.platform.auth import Principal, scopes_for
        s.info["principal"] = Principal(user_id=user.id, tenant_id=axn, tenant_code="AXN", email=user.email, name=user.full_name,
                                        roles=list(user.roles), scopes=scopes_for(list(user.roles)), attributes={})
        for n in range(workspace.MAX_VIEWS_PER_SCREEN):
            workspace.create_view(s, "kpis", f"v{n}", {"n": n})
        with pytest.raises(Problem) as exc:
            workspace.create_view(s, "kpis", "one too many", {})
        assert exc.value.code == "TOO_MANY_VIEWS"
        s.execute(delete(SavedView).where(SavedView.screen == "kpis"))


def test_approvals_tab_lists_every_task_of_the_document(client, login):
    body = client.get("/v1/documents/REQUISITION/REQ-2311/approvals", headers=login("buyer")).json()
    assert body["chain"] == ["COST_OBJECT_OWNER", "DEPT_HEAD", "PROCUREMENT_HEAD", "FINANCE_CONTROLLER"]
    assert len(body["tasks"]) >= 4 and all(t["status"] == "COMPLETED" and t["decision"] == "APPROVE" and t["decidedBy"] for t in body["tasks"])
    assert [t["role"] for t in body["tasks"]][:4] == body["chain"] or {t["role"] for t in body["tasks"]} >= set(body["chain"])
    assert client.get("/v1/documents/NOPE/X/approvals", headers=login("buyer")).status_code == 404


def test_documents_tab_lists_transmissions_erp_documents_and_links(client, login):
    po = client.get("/v1/documents/PURCHASE_ORDER/PO-77410/files", headers=login("buyer")).json()
    kinds = set(po["counts"])
    assert "LINK" in kinds and kinds & {"PRINTOUT", "EDI"} and any(i.get("href") for i in po["items"] if i["kind"] in ("PRINTOUT", "EDI"))
    assert any(i["kind"] == "ATTACHMENT" and "CoC" in i["title"] for i in po["items"])
    invoice = client.get("/v1/documents/INVOICE/INV-TF-8812/files", headers=login("ap.clerk")).json()
    assert any(i["kind"] == "ERP_DOCUMENT" and "5100004421" in i["title"] for i in invoice["items"])
    contract = client.get("/v1/documents/CONTRACT/SA-5520/files", headers=login("contract.manager")).json()
    assert contract["counts"].get("SIGNED_DOCUMENT", 0) >= 2
    assert client.get("/v1/documents/PURCHASE_ORDER/PO-77410/files", headers=login("tf.sales")).status_code == 403


def test_bulk_decisions_report_every_row_and_apply_none_blindly(client, login):
    h = login("finance.controller")
    assert client.post("/v1/tasks/bulk-complete", json={"items": []}, headers=h).status_code == 422
    missing, other = str(uuid.uuid4()), str(uuid.uuid4())
    body = {"items": [{"task_id": missing, "decision": "APPROVE"}, {"task_id": other, "decision": "REJECT"},
                      {"task_id": missing, "decision": "APPROVE"}]}
    r = client.post("/v1/tasks/bulk-complete", json=body, headers={**h, "Idempotency-Key": "c2-bulk-1"})
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["succeeded"] == 0 and result["failed"] == 3
    codes = [row["error"]["code"] for row in result["results"]]
    assert codes[1] == "COMMENT_REQUIRED" and codes[2] == "DUPLICATE_ROW" and codes[0] != "COMMENT_REQUIRED"
    assert client.post("/v1/tasks/bulk-complete", json=body, headers={**h, "Idempotency-Key": "c2-bulk-1"}).json()["replayed"] is True
    assert client.post("/v1/tasks/bulk-complete", json={"items": [{"task_id": missing, "decision": "MAYBE"}]}, headers=h).status_code == 422
    assert client.post("/v1/tasks/bulk-complete", json={"items": [{"task_id": missing, "decision": "APPROVE"}]}, headers=login("tf.sales")).status_code == 403
