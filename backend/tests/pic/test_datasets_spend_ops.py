"""D16 spend datasets for AXN and KAC (pack spend_ops): MOCK two-fiscal-year multi-ERP history, steward and maverick workloads, duplicates, plans, forecast history,
data-quality findings.

The tests assert properties (ranges, presence of every state, totals that must agree), never exact global counts: other modules of the suite share the database
and add their own rows. The pack's prerequisites (erp_client_kac, contracts_kac, inventory_ops, inventory_master, finance_ops) are applied first; the documents
that exist before the pack (AXN signature case, KAC contracts / invoices / payments / stock) are hashed and must be byte-identical afterwards."""
import hashlib
import json
import subprocess
import sys
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.pic.config import BACKEND_DIR
from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    CategoryPlan, ClassificationReview, Contract, ContractLine, CreditNote, DebitNote, Invoice, InvoiceLine, MaverickHit, Payment, PoLine, PurchaseOrder,
    SpendDuplicateCluster, SpendForecastSnapshot, SpendLine, SpendQualityRun, Stock, Supplier, TaxonomyNode, Tenant,
)
from app.pic.platform import clock
from app.pic.platform.audit import verify_chain
from app.pic.seed import datasets
from app.pic.seed.axion import Scenario, at
from app.pic.seed.datasets import spend_ops as pack
from app.pic.services import spend, spend_analytics, spend_cube, spend_forecast, spend_quality, spend_workflow
from app.pic.tools import spend_mock as mock
from tests.pic.conftest import PASSWORD

DATA = BACKEND_DIR / "data" / "erp_mock" / "KAC_SPEND"
GUARDED = {"AXN": (Invoice, InvoiceLine, PurchaseOrder, PoLine, Payment, CreditNote, DebitNote, Contract, ContractLine),
           "KAC": (Invoice, InvoiceLine, Payment, Contract, ContractLine, Stock)}


def row_hashes(session, models) -> dict:
    out = {}
    for model in models:
        for row in session.execute(select(model).order_by(model.id)).scalars():
            values = {c.key: getattr(row, c.key) for c in model.__mapper__.column_attrs}
            out[(model.__tablename__, str(row.id))] = hashlib.sha256(json.dumps(values, default=str, sort_keys=True).encode()).hexdigest()
    return out


@pytest.fixture(scope="module")
def packs(database):
    for name in ("erp_client_kac", "contracts_kac", "inventory_ops", "inventory_master", "finance_ops"):
        assert {r["status"] for r in datasets.apply_pack(name, PASSWORD)} <= {"LOADED", "ALREADY_LOADED", "SKIPPED"}, name
    with system_tx() as s:
        ids = {code: tid for code, tid in s.execute(select(Tenant.code, Tenant.id))}
    before = {}
    for code, models in GUARDED.items():
        with tenant_tx(ids[code]) as s:
            before[code] = row_hashes(s, models)
    import time
    t0 = time.time()
    results = {r["tenant"]: r for r in datasets.apply_pack("spend_ops", PASSWORD)}
    seconds = time.time() - t0
    assert set(results) == {"AXN", "KAC"} and {r["status"] for r in results.values()} <= {"LOADED", "ALREADY_LOADED"}, results
    yield {"results": results, "ids": ids, "before": before, "seconds": seconds}
    clock.set_pinned(None)


def tid(packs, code):
    return packs["ids"][code]


def act(packs, code, who="cm"):
    sc = Scenario(tid(packs, code), tenant_code=code, domain=pack.SPECS[code]["domain"], role_user={})
    return sc.act(pack.SPECS[code]["who"][who], at(date(2026, 11, 4), 10))


def test_spend_ops_is_loaded_once_and_changes_no_guarded_document(packs):
    assert {r["status"] for r in datasets.apply_pack("spend_ops", PASSWORD)} == {"ALREADY_LOADED"}
    for code, models in GUARDED.items():
        with tenant_tx(tid(packs, code)) as s:
            assert row_hashes(s, models) == packs["before"][code], f"{code}: a document the pack must not touch changed"
    assert pack.KEY == "spend-ops" and pack.REQUIRES == {"finance-ops": "1"} and datasets.PACKS.index("spend_ops") == datasets.PACKS.index("finance_ops") + 1


def test_kac_cube_covers_two_fiscal_years_in_several_currencies_and_erp_systems(packs):
    with act(packs, "KAC") as s:
        spend_cube.ensure_fresh(s)
        by_fy = {r["fiscal_year"]: r for r in spend_cube.cube(s, ["fiscal_year"], spend_cube.CubeFilter(period_from="2025-04", period_to="2026-10"))["rows"]}
        assert {"2025-26", "2026-27"} <= set(by_fy) and all(by_fy[k]["spendMinor"] > 0 for k in ("2025-26", "2026-27"))
        monthly = {r["period"]: r["spendMinor"] for r in spend_cube.cube(s, ["period"], spend_cube.CubeFilter(period_from="2025-04", period_to="2026-10"), limit=100)["rows"]}
        assert sorted(monthly) == mock.periods() and all(v > 0 for v in monthly.values())
        cube = spend_cube.cube(s, ["currency"], spend_cube.CubeFilter(period_from="2025-04", period_to="2026-10"))
        assert {"INR", "USD", "EUR", "JPY", "CNY"} <= {r["currency"] for r in cube["rows"]} and set(cube["documentCurrencyTotals"]) >= {"USD", "EUR", "JPY", "CNY"}
        systems = {r["source_system"] for r in spend_cube.cube(s, ["source_system"])["rows"]}
        assert {"PIC", "SAP-EU", "SAP-APAC"} <= systems
        foreign = s.execute(select(func.count()).where(SpendLine.currency.in_(("USD", "EUR", "JPY", "CNY")), SpendLine.amount_group_minor.is_(None))).scalar()
        assert foreign == 0, "every USD / EUR / JPY / CNY line is converted at the rate of its document date"
        line = s.execute(select(SpendLine).where(SpendLine.currency == "EUR", SpendLine.invoice_ref.like(f"{mock.MARK}/FX/%")).limit(1)).scalar_one()
        assert line.fx_rate is not None and line.fx_date <= line.document_date and line.amount_group_minor == int((Decimal(line.amount_minor) * line.fx_rate).quantize(Decimal(1), "ROUND_HALF_UP"))


def test_credit_notes_and_credit_memos_net_the_spend(packs):
    with act(packs, "KAC") as s:
        totals = spend_cube.cube(s, ["period"], limit=100)["totals"]
        assert totals["creditNoteMinor"] < 0 and totals["spendMinor"] == totals["invoicedMinor"] + totals["debitNoteMinor"] + totals["creditNoteMinor"]
        memos = s.execute(select(func.count(), func.sum(SpendLine.amount_minor)).where(SpendLine.invoice_ref.like(f"{mock.MARK}/CRM/%"))).one()
        assert memos[0] >= 100 and memos[1] < 0
        notes = s.execute(select(func.count()).select_from(CreditNote)).scalar()
        lines = s.execute(select(func.count()).where(SpendLine.document_type == "CREDIT_NOTE")).scalar()
        assert (notes == 0) or lines >= 1, "credit notes recorded against posted invoices are in the cube"


def test_every_maverick_rule_has_cases_in_several_states(packs):
    with tenant_tx(tid(packs, "KAC")) as s:
        hits = s.execute(select(MaverickHit)).scalars().all()
        assert {h.rule_code for h in hits} >= {c for c, *_ in spend.MAVERICK_RULES}
        assert {h.status for h in hits} >= {"OPEN", "DISPOSED", "RECOVERY_OPEN", "RESOLVED"}
        assert {h.disposition for h in hits if h.status == "DISPOSED"} >= {"ACCEPTED_EXCEPTION", "POLICY_BREACH", "FALSE_POSITIVE"}
        assert sum(1 for h in hits if h.disposition in ("ACCEPTED_EXCEPTION", "FALSE_POSITIVE") and h.reason_code) >= 10
        assert any(h.escalation_level >= 1 and h.escalated_to_role for h in hits) and all(h.owner_role and h.due_at for h in hits)
        assert any(h.recovered_minor and h.status == "RESOLVED" for h in hits) and sum(h.savings_at_risk_minor for h in hits) > 0
        for h in hits:
            assert (h.status == "OPEN") == (h.disposition is None and h.resolved_at is None), h.number
    with act(packs, "KAC") as s:
        summary = spend_workflow.hits_summary(s)
        assert summary["open"] > 0 and summary["recoveredMinor"] > 0 and summary["savingsAtRiskMinor"] > 0
        assert spend_workflow.repeat_offenders(s, 24, 3)["suppliers"] is not None
        versions = {r["code"]: r["versions"] for r in spend_workflow.rules_view(s)}
        assert versions["NON_CATALOGUE"] and versions["NON_CATALOGUE"][0]["change"] == {"slaDays": 15}


def test_steward_queue_has_decisions_pending_second_and_ageing(packs):
    with tenant_tx(tid(packs, "KAC")) as s:
        reviews = s.execute(select(ClassificationReview)).scalars().all()
        assert {r.status for r in reviews} >= {"OPEN", "PENDING_SECOND", "ACCEPTED", "RECLASSIFIED"}
        assert all(r.value_group_minor is not None and r.due_at is not None for r in reviews), "reviews from before the release carry a value and a due date too"
        parked = next(r for r in reviews if r.status == "PENDING_SECOND")
        assert parked.first_decided_by is not None and parked.first_category and parked.value_group_minor >= 250_000_000
        assert any(r.channel == "BULK" for r in reviews)
        assert any(r.learned_keyword for r in reviews), "the bulk decision taught the classifier a word"
    with act(packs, "KAC") as s:
        queue = spend_workflow.queue_summary(s)
        assert queue["open"] > 0 and queue["overdue"] > 0 and queue["oldestDays"] > 0 and queue["acceptRatePct"] is not None


def test_duplicate_clusters_concentration_and_tail(packs):
    with tenant_tx(tid(packs, "KAC")) as s:
        clusters = {tuple(c.supplier_codes): c for c in s.execute(select(SpendDuplicateCluster)).scalars()}
        wanted = {("MOCKD-101", "MOCKD-102"): "MERGE_APPROVED", ("MOCKD-201", "MOCKD-202", "MOCKD-203"): "PROPOSED", ("MOCKD-301", "MOCKD-302"): "OPEN",
                  ("MOCKD-401", "MOCKD-402"): "DISMISSED"}
        for codes, status in wanted.items():
            assert clusters[codes].status == status, (codes, clusters[codes].status)
        assert not any({"MOCKD-501", "MOCKD-502"} <= set(codes) for codes in clusters), "Plant 1 and Plant 2 Engineering are different suppliers"
        child = s.execute(select(Supplier).where(Supplier.code == "MOCKD-102")).scalar_one()
        parent = s.execute(select(Supplier).where(Supplier.code == "MOCKD-101")).scalar_one()
        assert child.parent_supplier_id == parent.id
    with act(packs, "KAC") as s:
        structure = {r["category"]: r for r in spend_analytics.category_structure(s)["rows"]}
        assert structure["HEAT-TREATMENT"]["hhi"] > 2500 and structure["SPECIAL-COATINGS"]["hhi"] > 2500 and structure["HEAT-TREATMENT"]["level"] == "HIGH"
        pareto = spend_analytics.pareto(s, "parent_supplier")
        assert pareto["classes"]["C"]["count"] >= 50 and pareto["tailSpendPct"] is not None


def test_category_plans_in_every_approval_state_and_kraljic_quadrant(packs):
    with tenant_tx(tid(packs, "KAC")) as s:
        plans = s.execute(select(CategoryPlan)).scalars().all()
        fy = [p for p in plans if p.fiscal_year == "2026-27"]
        assert len({p.category for p in fy}) == 8
        assert {p.status for p in fy} >= {"DRAFT", "IN_APPROVAL", "APPROVED", "REJECTED"} and any(p.version == 2 and p.supersedes_id for p in fy)
        assert len({p.kraljic for p in fy}) >= 3, {p.kraljic for p in fy}
        for p in fy:
            assert sum(p.savings_by_lever.values()) == p.savings_target_minor and p.wave_plan and p.budget_minor >= p.savings_target_minor >= 0
            if p.status == "APPROVED":
                assert p.owner_id != p.approved_by and spend_workflow.validate_plan(s, p) == []
    with act(packs, "KAC", "ph") as s:
        assert spend_workflow.pipeline_links(s, spend.get_plan(s, next(p.number for p in fy if p.status == "APPROVED")))["category"]


def test_forecast_history_gives_a_real_error(packs):
    with tenant_tx(tid(packs, "KAC")) as s:
        snaps = s.execute(select(SpendForecastSnapshot)).scalars().all()
        assert len(snaps) >= 500 and {x.as_of_period for x in snaps} >= {"2026-04", "2026-09"} and all(x.low_minor <= x.forecast_minor <= x.high_minor for x in snaps)
    with act(packs, "KAC") as s:
        acc = spend_forecast.accuracy(s)
        assert acc["count"] >= 100 and 0 < acc["mapePct"] < 80 and 0 < acc["bandCoveragePct"] <= 100 and len(acc["byHorizon"]) >= 3
        best = [x for x in acc["series"] if x["mapePct"] < 15]
        assert len(best) >= 5, "the large categories are forecast within 15 %"


def test_the_deliberate_data_quality_defects_are_found(packs):
    with act(packs, "KAC") as s:
        report = spend_quality.assess(s)
        checks = {c["code"]: c for c in report["checks"]}
        floors = {"FX_RATE_MISSING": 20, "DUPLICATE_LINES": 6, "CATEGORY_NOT_IN_TAXONOMY": 5, "NON_POSITIVE_INVOICE_LINES": 3, "NO_LINEAGE": 40, "AMOUNT_OUTLIER": 1,
                  "INTERCOMPANY_ADDRESSABLE": 2, "SUPPLIER_UNKNOWN": 2, "UNCLASSIFIED": 1}
        for code, floor in floors.items():
            assert checks[code]["count"] >= floor and checks[code]["status"] in ("WARN", "FAIL"), (code, checks[code])
        assert report["score"] < 100 and checks["CUBE_TIE_OUT"]["status"] == "PASS"
        defects = s.execute(select(func.count()).where(SpendLine.invoice_ref.like(f"{mock.MARK}/DQ%"))).scalar()
        assert defects >= 20 + 5 + 3 + 40 + 1 + 2 + 2      # DQ2's copies keep the reference of the line they copy, so they are not counted here
        assert s.execute(select(func.count()).select_from(SpendQualityRun)).scalar() >= 1


def test_volume_stays_inside_the_budget_and_the_signature_bands_hold(packs):
    for code, limit in (("KAC", 150_000), ("AXN", 20_000)):
        with tenant_tx(tid(packs, code)) as s:
            lines = s.execute(select(func.count()).select_from(SpendLine)).scalar()
            mock_lines = s.execute(select(func.count()).where(SpendLine.invoice_ref.like(f"{mock.MARK}/%"))).scalar()
        assert 0 < mock_lines < lines <= limit, (code, lines)
    with act(packs, "AXN") as s:
        o = spend.overview(s)
        assert 68 <= float(o["contractedPct"]) <= 74 and 5 <= float(o["maverickPct"]) <= 8, (o["contractedPct"], o["maverickPct"])
    with act(packs, "KAC") as s:
        o = spend.overview(s)
        assert Decimal(o["contractedPct"]) > 30 and Decimal(o["addressablePct"]) > 95


def test_audit_chains_verify_and_the_generator_is_deterministic_and_idempotent(packs):
    for code in ("AXN", "KAC"):
        with tenant_tx(tid(packs, code)) as s:
            assert verify_chain(s)["valid"] is True
    assert mock.check() == []
    ctx = pack.Ctx("KAC", tid(packs, "KAC"), pack.SPECS["KAC"])
    pack.load_masters(ctx)
    tables = pack._rate_tables(ctx)
    first = [(r["invoice_ref"], r["amount_minor"], str(r["invoice_line_id"])) for r in pack.build_lines(ctx, tables).rows]
    second = [(r["invoice_ref"], r["amount_minor"], str(r["invoice_line_id"])) for r in pack.build_lines(ctx, tables).rows]
    assert first == second and len({x[2] for x in first}) == len(first)      # the six deliberate duplicates share an invoice reference with their original, not a line id
    with tenant_tx(tid(packs, "KAC")) as s:
        before = s.execute(select(func.count()).select_from(SpendLine)).scalar()
    assert pack.load_lines(ctx, tables) == {"lines": 0}
    with tenant_tx(tid(packs, "KAC")) as s:
        assert s.execute(select(func.count()).select_from(SpendLine)).scalar() == before


def test_readme_and_the_generator_cli(packs):
    text = (DATA / "README.md").read_text(encoding="utf-8")
    for needle in ("DQ1", "DQ8", "tools/spend_mock.py", "MOCK", "How to regenerate"):
        assert needle in text, needle
    out = subprocess.run([sys.executable, "-m", "app.pic.tools.spend_mock", "--check"], cwd=str(BACKEND_DIR), capture_output=True, text=True)
    assert out.returncode == 0 and json.loads(out.stdout)["problems"] == [], out.stdout + out.stderr
