"""D9 AI evaluation sets on AXN: labelled spend lines from the seeded ERP history (+ curated texts), forecast holdout, supplier
duplicate pairs and the Copilot question set, evaluated against the platform's own services (TD §17).

The evaluation never writes business data (everything runs in rolled-back transactions); the pack only records the results
in the audit trail. Metric bounds are loose on purpose: other tests run on the same tenant before this file.
"""
import pytest
from sqlalchemy import func, select

from app.pic.db import tenant_tx
from app.pic.models import AuditEvent, Forecast, SpendLine, Supplier
from app.pic.platform import clock
from app.pic.tools import ai_eval
from tests.pic.conftest import PASSWORD


@pytest.fixture(scope="module")
def counts_before(database):
    sc = ai_eval.scenario("AXN")
    with tenant_tx(sc.tenant_id) as s:
        return {"suppliers": s.execute(select(func.count()).select_from(Supplier)).scalar(),
                "spend": s.execute(select(func.count()).select_from(SpendLine)).scalar(),
                "forecasts": s.execute(select(func.count()).select_from(Forecast)).scalar()}


@pytest.fixture(scope="module")
def pack(counts_before):
    from app.pic.seed import datasets
    result = datasets.apply_pack("ai_eval", PASSWORD)
    assert result[0]["status"] == "LOADED", result
    yield result[0]["summary"]
    clock.set_pinned(None)


def test_sets_are_versioned_files():
    _, erp = ai_eval.read_csv("spend_erp_history.csv")
    _, curated = ai_eval.read_csv("spend_curated.csv")
    _, holdout = ai_eval.read_csv("forecast_holdout.csv")
    header, pairs = ai_eval.read_csv("supplier_dedup_pairs.csv")
    questions = ai_eval.copilot_set()["questions"]
    assert len(erp) > 2000 and all(r["ref"].startswith("ERP-") and r["truth_category"] for r in erp)
    assert len(curated) >= 80 and len({r["truth_category"] for r in curated}) >= 15
    assert len(holdout) == 18 and {r["material"] for r in holdout} == {"DC-330", "DC-331", "FK-M8-50"}
    assert len(pairs) >= 40 and {r["label"] for r in pairs} == {"DUPLICATE", "DISTINCT"} and any("fictional" in h for h in header)
    for r in pairs:  # synthetic GSTINs carry a valid check character and embed the PAN
        for side in ("a", "b"):
            g = r[f"{side}_gstin"]
            if g:
                assert len(g) == 15 and g[2:12] == r[f"{side}_pan"] and g[-1] == _check(g[:14]), r["pair_id"]
    assert len(questions) >= 40 and {q["intent"] for q in questions} >= {"DOCUMENT", "TASKS", "SPEND", "SUPPLIER", "NO_MATCH", "PERMISSION_DENIED"}


def _check(first14: str) -> str:
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    total = 0
    for i, ch in enumerate(first14):
        prod = chars.index(ch) * (1 if i % 2 == 0 else 2)
        total += prod // 36 + prod % 36
    return chars[(36 - total % 36) % 36]


def test_metrics_from_the_platform_services(pack):
    m, counts = pack["metrics"], pack["counts"]
    assert counts["erpHistoryLines"] > 2000 and counts["curatedLines"] >= 80 and counts["forecastPoints"] == 45
    assert m["classificationAccuracy"] >= 0.95                      # ERP texts dominate; every line has its ERP ground truth
    assert 0.5 <= m["curatedAccuracy"] < 1.0                         # the hand-labelled texts are harder (keyword classifier)
    assert m["forecastMapeH1"] is not None and m["forecastMapeH1"] < 0.15
    assert m["spendForecastMape"] is not None and m["spendForecastMape"] < 0.25
    f8_precision, f8_recall = m["dedupF8"]
    spd_precision, spd_recall = m["dedupSpd"]
    assert f8_recall >= 0.95 and spd_recall >= 0.95                  # F8-03 screening checks the PAN and normalises legal names
    assert 0.5 < f8_precision < 1.0 and 0.5 < spd_precision < 1.0     # similar-name different companies raise review flags
    assert m["copilotCompleteness"] >= 0.99                          # the documented gate
    assert any("Copilot" in n and "completeness" in n for n in pack["notes"])


def test_full_report_details():
    report = ai_eval.evaluate("AXN", ["copilot", "dedup"])
    q, d = report["copilot"], report["dedup"]
    assert q["routingAccuracy"] >= 0.9 and q["evidenceAccuracy"] >= 0.9 and q["documentStatusAccuracy"] >= 0.9, q["failures"]
    assert not [f for f in q["failures"] if not f["complete"]]
    assert "DP-021" not in d["SPD_CLUSTERS"]["missed"]                 # the two Kanchi ERP vendor masters are clustered
    assert "OTHER_STATE_GSTIN" not in d["F8_SCREENING"]["missedKinds"]  # same PAN, other state: caught by the registration screening
    assert report["gates"]["copilotCompleteness"]["documented"] is True


def test_evaluation_writes_no_business_data(pack, counts_before):
    sc = ai_eval.scenario("AXN")
    with tenant_tx(sc.tenant_id) as s:
        assert s.execute(select(func.count()).select_from(Supplier)).scalar() == counts_before["suppliers"]
        assert not s.execute(select(Supplier.id).where(Supplier.code.like("EV-%"))).first()
        assert s.execute(select(func.count()).select_from(SpendLine)).scalar() == counts_before["spend"]
        assert s.execute(select(func.count()).select_from(Forecast)).scalar() == counts_before["forecasts"]


def test_results_in_the_audit_trail(pack):
    sc = ai_eval.scenario("AXN")
    with tenant_tx(sc.tenant_id) as s:
        summary = s.execute(select(AuditEvent).where(AuditEvent.object_type == "AI_EVALUATION")).scalar_one()
        assert set(summary.after) >= {"classification", "forecast", "dedup", "copilot", "gates"}
        agents = s.execute(select(AuditEvent).where(AuditEvent.object_type == "AGENT", AuditEvent.action == "EVALUATED")).scalars().all()
        assert {e.object_ref for e in agents} == {"SPEND_CLASSIFICATION", "DEMAND_SENSING", "COPILOT"}
        assert all(e.ai_ref == str(summary.event_id) for e in agents)
        copilot = next(e for e in agents if e.object_ref == "COPILOT")
        assert copilot.after["completeness"] >= 0.99


def test_cli_report(capsys):
    assert ai_eval.main(["--set", "copilot"]) == 0
    out = capsys.readouterr().out
    assert "contract completeness" in out and "gate copilotCompleteness" in out


def test_idempotent(pack):
    from app.pic.seed import datasets
    assert datasets.apply_pack("ai_eval", PASSWORD)[0]["status"] == "ALREADY_LOADED"
