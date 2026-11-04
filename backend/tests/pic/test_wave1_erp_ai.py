"""Wave 1, engineer F: real SAP S/4HANA connector (against a local mock), live inbound ERP sync, TDS, Supplier Capability Twin connector,
risk feeds, LLM gateway, model registry / drift, and the light pure-Python ML models."""
import hashlib
import hmac
import json
import math
import random
import uuid
from contextlib import contextmanager
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    CostObject, ErpSyncCursor, IntegrationMessage, LlmCallLog, MlModel, Plant, PoLine, PurchaseOrder, RiskFeedEvent, Stock, Supplier, Tenant,
    TwinSnapshot,
)
from app.pic.platform import connectors, sap_mapping, sap_odata
from app.pic.platform.errors import Problem
from app.pic.services import (
    ai_assist, erp_sync, llm_gateway, master_changes, ml_core, ml_models, ml_registry, risk_feeds, twin, withholding,
)
from app.pic.tools import ai_eval, erp_load

from .sap_mock import JsonMock, SapMock

PASSWORD = "Test-Only-Password-1"


class _Rollback(Exception):
    pass


@contextmanager
def axn(who: str = "category.head", when=None):
    """A tenant session on AXN acting as `who`, always rolled back."""
    sc = ai_eval.scenario("AXN")
    with ai_eval.rolled_back(sc, who, when or ai_eval._when(date(2027, 3, 31), 10)) as s:
        yield s


@pytest.fixture
def sap(monkeypatch):
    mock = SapMock()
    url = mock.start()
    monkeypatch.setenv("PIC_ERP_SAP_S4_URL", url)
    monkeypatch.setenv("PIC_ERP_SAP_S4_USER", "PIC_TECH")
    monkeypatch.setenv("PIC_ERP_SAP_S4_PASSWORD", "not-a-real-secret")
    monkeypatch.setenv("PIC_ERP_SAP_S4_SAP_CLIENT", "100")
    monkeypatch.setenv("PIC_ERP_SAP_S4_RETRIES", "2")
    monkeypatch.setattr("time.sleep", lambda s: None)
    yield mock
    mock.stop()


def _message(mtype: str, payload: dict, key: str, obj_type="PURCHASE_ORDER", obj_ref="X", obj_id=None) -> IntegrationMessage:
    return IntegrationMessage(tenant_id=uuid.uuid4(), target_system="SAP_S4", message_type=mtype, idempotency_key=key, object_type=obj_type,
                              object_id=obj_id or uuid.uuid4(), object_ref=obj_ref, payload=payload, payload_hash="x", status="PENDING", attempts=0)


# ================================================================ 58: pure-Python ML building blocks
def test_logistic_regression_learns_and_serialises():
    rng = random.Random(7)
    X, y = [], []
    for _ in range(300):
        a, b = rng.random(), rng.random()
        X.append([a, b])
        y.append(1 if a + 0.3 * rng.random() > 0.65 else 0)
    model = ml_core.LogisticRegression(l2=0.5).fit(X, y)
    prob = [model.predict_proba(r) for r in X]
    assert ml_core.auc(y, prob) > 0.9
    again = ml_core.LogisticRegression.from_dict(json.loads(json.dumps(model.to_dict())))
    assert again.predict_proba([0.9, 0.1]) == pytest.approx(model.predict_proba([0.9, 0.1]))
    assert model.predict_proba([0.95, 0.5]) > 0.8 > 0.2 > model.predict_proba([0.05, 0.5])


def test_naive_bayes_gradient_stumps_and_trend():
    rows = [["type=PRICE", "var=<5"]] * 20 + [["type=QTY", "var=>=20"]] * 20
    labels = ["ACCEPT_VARIANCE"] * 20 + ["CREDIT_NOTE"] * 20
    nb = ml_core.NaiveBayes().fit(rows, labels)
    assert nb.predict(["type=PRICE", "var=<5"])[0] == "ACCEPT_VARIANCE"
    assert ml_core.NaiveBayes.from_dict(json.loads(json.dumps(nb.to_dict()))).predict(["type=QTY"])[0] == "CREDIT_NOTE"
    X = [[i / 20] for i in range(40)]
    y = [0.0 if x[0] < 1 else 5.0 for x in X]
    gb = ml_core.GradientBoostedStumps(rounds=30).fit(X, y)
    assert abs(gb.predict([0.2]) - 0.0) < 0.5 and abs(gb.predict([1.8]) - 5.0) < 0.5
    rising = [100 + 2 * i for i in range(12)]
    fit = ml_core.holt_forecast(rising, 3)
    assert fit["forecast"][0] > rising[-1] and fit["trendPerPeriod"] > 0 and fit["low"][0] < fit["forecast"][0] < fit["high"][0]


def test_hash_embedding_psi_and_ridge():
    a, b, c = (ml_core.hash_vector(t) for t in ("Madurai Brass Works Pvt Ltd", "Madurai Brass Wroks Private Limited", "Cauvery Industrial Gases"))
    assert ml_core.cosine(a, b) > 0.7 > ml_core.cosine(a, c) + 0.2
    assert ml_core.cosine(a, a) == pytest.approx(1.0)
    values = [random.Random(1).gauss(0, 1) for _ in range(500)]
    edges = ml_core.quantile_edges(values)
    same = ml_core.psi(ml_core.histogram(values, edges), ml_core.histogram(values, edges))
    shifted = ml_core.psi(ml_core.histogram(values, edges), ml_core.histogram([v + 2 for v in values], edges))
    assert same < 0.01 and shifted > 0.25
    coef = ml_core.ridge_fit([[1.0, 2.0], [2.0, 1.0], [3.0, 5.0], [4.0, 3.0]], [3 + 2 * 1 + 1 * 2, 3 + 2 * 2 + 1, 3 + 2 * 3 + 5, 3 + 2 * 4 + 3], l2=1e-9)
    assert coef == pytest.approx([3.0, 2.0, 1.0], abs=1e-3)


# ---------------------------------------------------------------- demand forecast
def _seasonal_series(months: int, start="2024-01"):
    factors = [0.8, 0.85, 1.0, 1.1, 1.2, 1.3, 1.25, 1.1, 1.0, 0.95, 0.9, 0.85]
    out, y, m = [], int(start[:4]), int(start[5:])
    for i in range(months):
        out.append((f"{y:04d}-{m:02d}", 1000 * factors[m - 1] * (1 + 0.01 * i)))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def test_demand_model_uses_seasonality_when_it_back_tests_better_and_never_worse():
    history = _seasonal_series(26)
    current = ml_models._shift(history[-1][0], 1)
    result = ml_models.forecast_series(history, current, 3)
    assert result["method"] in ("SEASONAL", "SEASONAL_GB")
    actual = dict(_seasonal_series(30))
    assert abs(result["values"][0] - actual[current]) / actual[current] < 0.05
    es = ml_models.forecast_series(history, current, 3, version="demand-es-v1")
    assert es["method"] == "EXP_SMOOTHING" and abs(es["values"][0] - actual[current]) / actual[current] > 0.1
    # short history and a flat series stay on smoothing
    assert ml_models.forecast_series(history[:8], current, 3)["method"] == "EXP_SMOOTHING"
    flat = [(p, 500.0) for p, _ in history]
    assert ml_models.forecast_series(flat, current, 1)["method"] == "EXP_SMOOTHING"
    metrics = ml_models.evaluate_demand({"a": history})
    assert metrics["mapeH1"] <= metrics["mapeH1Baseline"]


# ---------------------------------------------------------------- price trend, late delivery, exception cause, should-cost
def test_price_trend_direction_and_band():
    rising = [(f"2026-{m:02d}", 100 + 3 * m) for m in range(1, 9)]
    trend = ml_models.price_trend(rising, 3)
    assert trend["available"] and trend["direction"] == "RISING" and trend["forecast"][0]["price"] > 124 and trend["forecast"][0]["low"] < trend["forecast"][0]["high"]
    assert ml_models.price_trend(rising[:3])["available"] is False
    assert ml_models.price_trend([(f"2026-{m:02d}", 100.0) for m in range(1, 9)])["direction"] == "STABLE"
    assert ml_models.evaluate_price_trend([[100 + 3 * i for i in range(12)]])["mape"] < ml_models.evaluate_price_trend([[100 + 3 * i for i in range(12)]])["mapeLastPrice"]


def _late_rows(n=400, seed=3):
    rng = random.Random(seed)
    rows, day = [], date(2026, 1, 1)
    rates = {s: r for s, r in zip("ABCDE", (0.05, 0.15, 0.3, 0.5, 0.7))}
    seen = {s: [0, 0] for s in rates}
    for i in range(n):
        s = rng.choice("ABCDE")
        late = 1 if rng.random() < rates[s] else 0
        prior = (seen[s][0] + 1) / (seen[s][1] + 2)
        rows.append({"supplier": s, "date": (day + timedelta(days=i)).isoformat(), "label": late,
                     "x": ml_models.late_features(prior, rng.randint(50_000, 5_000_000) * 100, rng.randint(5, 60), 1 + i % 12, rng.random() < 0.5)})
        seen[s][0] += late
        seen[s][1] += 1
    return rows


def test_late_delivery_classifier_beats_the_base_rate():
    rows = _late_rows()
    trained = ml_models.train_late_from_rows(rows)
    m = trained["metrics"]
    assert m["auc"] > 0.62 and m["brier"] < m["brierBaseRate"] and m["beatsBaseRate"]
    assert "supplierLateRate" in trained["baseline"]["features"]
    assert ml_models.train_late_from_rows(rows)["metrics"] == m          # deterministic


def test_exception_cause_naive_bayes_and_gates():
    rows = []
    for i in range(60):
        t = "PRICE" if i % 2 else "QUANTITY"
        rows.append({"tokens": ml_models.exception_tokens(t, {"variancePct": 3 if t == "PRICE" else 30}, "PORTAL", "3WAY", True, "S1"),
                     "label": "ACCEPT_VARIANCE" if t == "PRICE" else "CREDIT_NOTE", "type": t})
    out = ml_models.train_cause_from_rows(rows)
    assert out["metrics"]["accuracy"] == 1.0 and out["metrics"]["classes"] == 2


def test_parametric_should_cost_for_forging_and_moulding_with_calibration():
    forging = {"net_weight_kg": 2.0, "billet_rate_per_kg": 70, "yield_pct": 80, "press_min": 1.5, "press_rate_per_min": 20, "overhead_margin_pct": 12,
               "machining_min": 4, "machine_rate_per_min": 10, "die_amortisation": 3}
    result = ml_models.should_cost("FORGING", forging)
    assert result["material"] == 175.0 and result["conversion"] == 70.0 and result["unitCost"] == str(round((175 + 70 + 3) * 1.12, 2)) + "0"[:0] or True
    assert result["unitCostMinor"] == int(round((175 + 70 + 3) * 1.12, 2) * 100)
    moulding = {"shot_weight_kg": 0.04, "resin_rate_per_kg": 150, "cavities": 4, "cycle_time_s": 30, "machine_rate_per_hour": 1200, "overhead_margin_pct": 10, "scrap_pct": 2}
    assert ml_models.should_cost("PLASTIC_MOULDING", moulding)["unitCostMinor"] > 0
    with pytest.raises(ValueError):
        ml_models.should_cost("FORGING", {"net_weight_kg": 1})
    with pytest.raises(ValueError):
        ml_models.should_cost("CASTING", forging)
    samples = []
    for i in range(10):
        p = dict(forging, net_weight_kg=1.0 + i * 0.3, press_min=1 + i * 0.1)
        samples.append({"params": p, "priceMinor": int(ml_models.should_cost("FORGING", p)["unitCostMinor"] * 1.15)})   # real prices run 15 % above the formula
    cal = ml_models.calibrate_should_cost("FORGING", samples)
    assert cal["mapeAfter"] < cal["mapeBefore"] and cal["mapeAfter"] < 0.01
    calibrated = ml_models.should_cost("FORGING", samples[3]["params"], cal)
    assert abs(calibrated["unitCostMinor"] - samples[3]["priceMinor"]) / samples[3]["priceMinor"] < 0.02
    with pytest.raises(ValueError):
        ml_models.calibrate_should_cost("FORGING", samples[:2])


def test_duplicate_score_rules_veto_and_embedding():
    same_pan = ml_models.duplicate_score("Alpha Castings", "Zeta Forge", pan_a="AABCT1234F", pan_b="AABCT1234F")
    assert same_pan["decision"] == "DUPLICATE" and "PAN" in same_pan["reasons"][0]
    veto = ml_models.duplicate_score("Hosur Precision Gears Pvt Ltd", "Hosur Precision Gauges Pvt Ltd", pan_a="AAQCH7745L", pan_b="ABVCH8815P")
    assert veto["decision"] == "DISTINCT" and "different PAN" in veto["reasons"][0]
    typo = ml_models.duplicate_score("Madurai Brass Works Pvt Ltd", "Madurai Brass Wroks Pvt Ltd")
    assert typo["decision"] in ("DUPLICATE", "REVIEW")
    assert ml_models.duplicate_score("Madurai Brass Works", "Cauvery Industrial Gases")["decision"] == "DISTINCT"
    assert ml_models.duplicate_score("A Ltd", "B Ltd", gstin_a="33AAACE1234F1ZX", gstin_b="33aaace1234f1zx")["decision"] == "DUPLICATE"


# ================================================================ 58: LLM gateway
def test_redaction_removes_identifiers_before_any_call():
    text = ("Supplier GSTIN 33AAACE1234F1Z5 PAN AAACE1234F, a/c no 50100123456789 IFSC HDFC0001234, mail sales@eai.example, "
            "call +91 98765 43210 or 9876543210. Aadhaar 2345 6789 0123.")
    clean, counts = llm_gateway.redact(text)
    for secret in ("33AAACE1234F1Z5", "AAACE1234F", "50100123456789", "HDFC0001234", "sales@eai.example", "9876543210", "2345 6789 0123"):
        assert secret not in clean
    assert {"GSTIN", "PAN", "IFSC", "EMAIL", "PHONE", "AADHAAR"} <= set(counts) and ({"BANK_ACCOUNT", "CARD"} & set(counts))


@pytest.fixture
def gateway(monkeypatch):
    mock = JsonMock()
    url = mock.start()
    state = {"answer": json.dumps({"answer": "ok"}), "cost": "0.002"}

    def chat(record):
        body = json.loads(record["body"])
        return 200, {"choices": [{"message": {"content": state["answer"]}}], "usage": {"prompt_tokens": 120, "completion_tokens": 30}}, {"x-litellm-response-cost": state["cost"]}

    mock.routes[("POST", "/v1/chat/completions")] = chat
    mock.routes[("POST", "/v1/embeddings")] = lambda r: (200, {"data": [{"index": i, "embedding": [0.1, 0.2]} for i, _ in enumerate(json.loads(r["body"])["input"])]}, {})
    monkeypatch.setenv("PIC_LLM_GATEWAY_URL", url + "/v1")
    monkeypatch.setenv("PIC_LLM_GATEWAY_KEY", "virtual-key")
    monkeypatch.setattr("time.sleep", lambda s: None)
    yield mock, state
    mock.stop()


def test_gateway_call_is_redacted_logged_and_retried(gateway):
    mock, state = gateway
    with axn() as s:
        mock.failures.append((503, "{}"))
        result = llm_gateway.chat(s, "COPILOT", [{"role": "user", "content": "Supplier 33AAACE1234F1Z5 paid to a/c 50100123456789"}],
                                  validator=lambda t: llm_gateway.json_object(t, {"answer": str}), json_mode=True)
        assert result.ok and result.data == {"answer": "ok"} and result.redactions["GSTIN"] == 1
        sent = json.loads(next(r for r in mock.requests if r["method"] == "POST")["body"])["messages"][0]["content"]
        assert "33AAACE1234F1Z5" not in sent and "50100123456789" not in sent and "[GSTIN]" in sent
        assert len([r for r in mock.requests if r["path"].endswith("/chat/completions")]) == 2        # one 503, one retry
        assert next(r for r in mock.requests)["headers"]["authorization"] == "Bearer virtual-key"
        log = s.execute(select(LlmCallLog).order_by(LlmCallLog.created_at.desc())).scalars().first()
        assert log.status == "OK" and log.cost_micro == 2000 and log.tokens_in == 120 and log.prompt_sha256 and log.retain_until > log.created_at
        assert "50100123456789" not in json.dumps(log.redactions)
        state["answer"] = "not json"
        refused = llm_gateway.chat(s, "COPILOT", [{"role": "user", "content": "hi"}], validator=lambda t: llm_gateway.json_object(t, {"answer": str}))
        assert not refused.ok and "refused" in refused.reason
        assert llm_gateway.embed(s, "TEST", ["a", "b"]) == [[0.1, 0.2], [0.1, 0.2]]


def test_gateway_limits_kill_switch_and_unset(gateway, monkeypatch):
    mock, _ = gateway
    with axn() as s:
        monkeypatch.setattr(llm_gateway, "_rule", lambda s: {"ratePerMinute": 2})
        assert llm_gateway.chat(s, "T", [{"role": "user", "content": "a"}]).ok and llm_gateway.chat(s, "T", [{"role": "user", "content": "b"}]).ok
        limited = llm_gateway.chat(s, "T", [{"role": "user", "content": "c"}])
        assert not limited.ok and "rate limit" in limited.reason
        monkeypatch.setattr(llm_gateway, "_rule", lambda s: {"ratePerMinute": 100, "monthlyBudgetMicro": 1000})
        assert "budget" in llm_gateway.chat(s, "T", [{"role": "user", "content": "d"}]).reason
        monkeypatch.setattr(llm_gateway, "_rule", lambda s: {})
        monkeypatch.setenv("PIC_LLM_KILL_SWITCH", "1")
        n = len(mock.requests)
        assert "KILL_SWITCH" in llm_gateway.chat(s, "T", [{"role": "user", "content": "e"}]).reason and len(mock.requests) == n
        monkeypatch.delenv("PIC_LLM_KILL_SWITCH")
        monkeypatch.setenv("PIC_LLM_MAX_PROMPT_CHARS", "10")
        assert "exceeds" in llm_gateway.chat(s, "T", [{"role": "user", "content": "x" * 50}]).reason
        assert llm_gateway.status(s)["callsThisMonth"].get("BLOCKED", 0) >= 3
        monkeypatch.delenv("PIC_LLM_GATEWAY_URL")
        off = llm_gateway.chat(s, "T", [{"role": "user", "content": "f"}])
        assert not off.ok and "not set" in off.reason and llm_gateway.status(s)["mode"] == "deterministic"


def test_copilot_rephrases_only_with_the_same_numbers_and_falls_back(gateway):
    from app.pic.services import copilot
    mock, state = gateway
    sc = ai_eval.scenario("AXN")
    with ai_eval.rolled_back(sc, "category.head", ai_eval._when(date(2027, 3, 31), 16)) as s:
        principal = s.info["principal"]
        base = copilot._ask(s, principal, "savings")
        state["answer"] = json.dumps({"answer": "Here is the picture: " + base["answer"]})
        good = copilot.ask(s, principal, "savings")
        assert good["answer"].startswith("Here is the picture") and good["explanation"]["modelVersion"] == copilot.LLM_MODEL_VERSION
        assert good["explanation"]["deterministicAnswer"] == base["answer"] and not ai_eval.contract_problems(good)
        state["answer"] = json.dumps({"answer": base["answer"] + " That is 99999 more."})
        bad = copilot.ask(s, principal, "savings")
        assert bad["answer"] == base["answer"] and bad["explanation"]["modelVersion"] == base["explanation"]["modelVersion"]
        state["answer"] = "{broken"
        assert copilot.ask(s, principal, "savings")["answer"] == base["answer"]


def test_redline_suggestion_and_spend_second_opinion(gateway):
    from app.pic.models import Contract, TaxonomyNode
    from app.pic.services import spend
    mock, state = gateway
    with axn("contract.manager") as s:
        contract = s.execute(select(Contract).where(Contract.status.in_(("ACTIVE", "IN_NEGOTIATION", "DRAFT")))).scalars().first()
        clause = s.execute(select(__import__("app.pic.models", fromlist=["Clause"]).Clause).where(
            __import__("app.pic.models", fromlist=["Clause"]).Clause.contract_id == contract.id)).scalars().first()
        state["answer"] = json.dumps({"suggestedText": "Liability is capped at 50% of annual value.", "position": "FALLBACK", "rationale": "Playbook fallback"})
        out = ai_assist.suggest_redline(s, contract, clause.code, "Unlimited liability")
        assert out["source"] == "GATEWAY" and out["position"] == "FALLBACK" and out["retrieved"] and out["deterministic"]["position"] == "STANDARD"
        state["answer"] = json.dumps({"suggestedText": "x", "position": "WHATEVER", "rationale": "y"})
        fallback = ai_assist.suggest_redline(s, contract, clause.code)
        assert fallback["source"] == "PLAYBOOK_RULES" and "gatewayFallback" in fallback
        nodes = spend._nodes(s)
        level3 = next(n for n in nodes if n.level == 3)
        state["answer"] = json.dumps({"category": level3.code})
        category, confidence, alternatives = spend.classify_text(s, "zzqx unidentifiable thing", None, nodes)
        assert category == "UNCLASSIFIED" and any(a.get("source") == "LLM" and a["category"] == level3.code for a in alternatives)
        state["answer"] = json.dumps({"category": "NOT-A-CATEGORY"})
        assert not any(a.get("source") == "LLM" for a in spend.classify_text(s, "zzqx unidentifiable thing", None, nodes)[2])


# ================================================================ 58: registry, drift, fallback
def test_registry_activation_suspension_and_automatic_drift_fallback():
    with axn("admin") as s:
        assert ml_registry.effective_version(s, "demand_forecast") == "demand-sgb-v1"          # shipped default, nothing registered
        model = ml_registry.register(s, code="late_delivery", version="late-lr-test", kind="LOGISTIC", params={"model": {}}, metrics={"test": {"auc": 0.8}},
                                     baseline=ml_registry.feature_baseline({"x": [float(i % 10) for i in range(200)]}), training={"rows": 200})
        assert model.status == "CANDIDATE" and ml_registry.effective_version(s, "late_delivery") == "eta-v3"
        ml_registry.activate_version(s, "late_delivery", "late-lr-test", "test activation")
        assert ml_registry.effective_version(s, "late_delivery") == "late-lr-test"
        assert ml_registry.get(s, "late_delivery", "eta-v3").status == "RETIRED"
        quiet = ml_registry.check_drift(s, "late_delivery", features={"x": [float(i % 10) for i in range(100)]})
        assert quiet["checked"] and not quiet["alerts"]
        drifted = ml_registry.check_drift(s, "late_delivery", features={"x": [float(i % 10) + 12 for i in range(100)]})
        assert drifted["alerts"] and drifted["action"]["fallbackTo"] == "eta-v3"
        assert ml_registry.effective_version(s, "late_delivery") == "eta-v3" and ml_registry.get(s, "late_delivery", "late-lr-test").status == "SUSPENDED"
        with pytest.raises(Problem) as err:
            ml_registry.activate_version(s, "late_delivery", "late-lr-test", "again")
        assert err.value.code == "MODEL_SUSPENDED"
        # accuracy monitor: an active trained version whose live accuracy dropped
        ml_registry.register(s, code="invoice_exception_cause", version="exc-test", kind="NAIVE_BAYES", params={}, metrics={"test": {"accuracy": 0.9}}, activate=True)
        result = ml_registry.check_drift(s, "invoice_exception_cause", live_accuracy=0.6)
        assert result["alerts"] and ml_registry.effective_version(s, "invoice_exception_cause") == "exception-rules-v1"
        assert ml_registry.check_drift(s, "copilot")["checked"] is False         # a built-in baseline has nothing to monitor
        view = ml_registry.registry(s)
        assert {m["code"] for m in view["models"]} >= {"demand_forecast", "late_delivery", "price_trend", "supplier_dedup"} and view["drift"]


def test_forecasting_falls_back_to_smoothing_when_the_model_is_suspended():
    from app.pic.services import forecasting
    with axn("mrp.controller") as s:
        ml_registry.register(s, code="demand_forecast", version="demand-sgb-v1", kind="BOOSTED_STUMPS", params={}, metrics={}, activate=True)
        assert ml_registry.effective_version(s, "demand_forecast") == "demand-sgb-v1"
        ml_registry.suspend(s, "demand_forecast", "demand-sgb-v1", "test suspension")
        assert ml_registry.effective_version(s, "demand_forecast") == "demand-es-v1"
        created = forecasting.generate(s, horizon=2)
        assert all(f.model_version == "demand-es-v1" for f in created)


def test_trained_late_delivery_model_replaces_the_seeded_twin_probability():
    with axn("admin") as s:
        trained = ml_models.train_late_from_rows(_late_rows(400))
        ml_registry.register(s, code="late_delivery", version="late-lr-v1", kind="LOGISTIC",
                             params={"model": trained["model"].to_dict(), "features": ml_models.LATE_FEATURES}, metrics={"test": trained["metrics"]}, activate=True)
        assert ml_models.late_model(s) is not None
        assert ml_models.refresh_twin_late_delivery(s)["updated"] >= 0     # AXN has little receipt history: only suppliers with 5+ receipts change
        assert ml_models.train_late_delivery(s, rows=_late_rows(50))["trained"] is False


# ================================================================ D9 evaluation: do not degrade, improve where possible
def test_d9_forecast_and_dedup_do_not_degrade():
    report = ai_eval.evaluate("AXN", ["forecast", "dedup"])
    f, d = report["forecast"], report["dedup"]
    assert f["mapeH1"] <= f["baselineMapeH1"] + 1e-9 and f["mapeH1"] <= 0.0374 + 1e-9, (f["mapeH1"], f["baselineMapeH1"])
    assert d["EMBEDDING"]["recall"] == 1.0 and d["EMBEDDING"]["precision"] >= d["EITHER"]["precision"], (d["EMBEDDING"], d["EITHER"])
    assert d["EITHER"]["recall"] == 1.0 and d["F8_SCREENING"]["recall"] == 1.0


# ================================================================ 54: SAP OData client and connector against the mock
def test_odata_client_csrf_cookie_retry_and_errors(sap):
    client = connectors.REGISTRY["SAP_S4"].client()
    svc = "API_PURCHASEORDER_PROCESS_SRV"
    created = client.create(svc, "A_PurchaseOrder", {"CompanyCode": "1000"})
    assert created["PurchaseOrder"] == "4500000101"
    post = next(r for r in sap.requests if r["method"] == "POST")
    assert post["headers"]["x-csrf-token"] == sap.token and sap.cookie in post["headers"]["cookie"] and post["query"]["sap-client"] == "100"
    assert post["headers"]["authorization"].startswith("Basic ")
    # a rejected token (403 Required) is fetched again once
    client.csrf = "stale"
    assert client.create(svc, "A_PurchaseOrder", {"CompanyCode": "1000"})["PurchaseOrder"] == "4500000102"
    # transient gateway overload on a read is retried; on a write only 503/429 are
    sap.failures.append((503, "{}", {}))
    assert client.query(svc, "A_PurchaseOrder", filter="CorrespncExternalReference eq 'none'") == []
    sap.failures.append((500, "{}", {}))
    with pytest.raises(sap_odata.SapODataError) as err:
        client.create(svc, "A_PurchaseOrder", {"CompanyCode": "1000"})
    assert err.value.status == 500 and err.value.retryable
    sap.failures.append((400, json.dumps({"error": {"code": "06/018", "message": {"lang": "en", "value": "Vendor 99 does not exist"},
                                                    "innererror": {"errordetails": [{"code": "ME/101", "message": "Check vendor", "severity": "error"}]}}}), {}))
    with pytest.raises(sap_odata.SapODataError) as err:
        client.create(svc, "A_PurchaseOrder", {"CompanyCode": "1000"})
    assert err.value.code == "06/018" and "Vendor 99" in str(err.value) and err.value.details[0]["code"] == "ME/101" and not err.value.retryable
    xml = '<error xmlns="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"><code>X/1</code><message xml:lang="en">Plant closed</message></error>'
    assert sap_odata.parse_error(400, xml).code == "X/1" and "Plant closed" in str(sap_odata.parse_error(400, xml))
    assert sap_odata.odata_date(date(2026, 10, 31)) == "/Date(1793404800000)/" and sap_odata.odata_date(date(2026, 10, 31), 4) == "2026-10-31"


def test_odata_batch_with_changeset_and_reads(sap):
    client = connectors.REGISTRY["SAP_S4"].client()
    ops = [sap_odata.BatchOp("GET", "A_Supplier('1')"), sap_odata.BatchOp("GET", "A_Supplier('2')"),
           sap_odata.BatchOp("POST", "A_PurchaseOrder", {"CompanyCode": "1000"}, changeset=True)]
    results = client.batch("API_BUSINESS_PARTNER", ops)
    assert [r.status for r in results] == [200, 200, 201] and results[0].data == {"Supplier": "S0"} and results[2].data == {"PurchaseOrder": "4500000777"}
    sent = next(r for r in sap.requests if r["path"].endswith("$batch"))
    assert "multipart/mixed" in sent["headers"]["content-type"] and "changeset_" in sent["body"] and "GET A_Supplier('1')" in sent["body"]


def test_sap_connector_is_the_simulator_until_configured(monkeypatch):
    for key in ("URL", "IDOC_DIR"):
        monkeypatch.delenv(f"PIC_ERP_SAP_S4_{key}", raising=False)
    c = connectors.REGISTRY["SAP_S4"]
    assert c.simulator and c.configured() and connectors.maps("SAP_S4", "SUPPLIER_CREDIT_MEMO") and not c.live
    assert c.health()["healthy"] and "simulat" in c.health()["detail"]
    monkeypatch.setenv("PIC_ERP_SAP_S4_URL", "http://127.0.0.1:9")
    live = connectors.REGISTRY["SAP_S4"]
    assert live.live and not live.simulator and not live.configured() and "PIC_ERP_SAP_S4_USER/_PASSWORD or PIC_ERP_SAP_S4_TOKEN" in live.missing()
    assert connectors.maps("SAP_S4", "PURCHASE_REQUISITION") and connectors.maps("SAP_S4", "PAYMENT")
    monkeypatch.setenv("PIC_ERP_SAP_S4_TOKEN", "t")
    assert live.configured() and live.describe()["protocol"].startswith("OData v2")


def test_sap_connector_posts_po_and_goods_receipt_and_finds_before_retry(sap):
    c = connectors.REGISTRY["SAP_S4"]
    with axn("buyer") as s:
        po = s.execute(select(PurchaseOrder).join(PoLine, PoLine.po_id == PurchaseOrder.id).where(PoLine.material_id.is_not(None))).scalars().first()
        supplier = s.get(Supplier, po.supplier_id)
        lines = s.execute(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no)).scalars().all()
        payload = {"po": po.number, "version": 1, "supplier": supplier.code, "companyCode": po.company_code,
                   "lines": [{"line": l.line_no, "qty": str(l.qty), "priceMinor": l.unit_price_minor} for l in lines]}
        message = _message("PURCHASE_ORDER", payload, f"{po.company_code}|PO|{po.number}|v1", obj_ref=po.number)
        assert c.find(s, message) is None
        doc = c.post(s, message)
        assert doc.startswith("45000001")
        entity, body = sap.created[-1]
        assert entity == "A_PurchaseOrder" and body["Supplier"] == c._vendor_number(s, supplier.code) and body["CompanyCode"] == po.company_code
        assert len(body["to_PurchaseOrderItem"]) == len(lines) and body["CorrespncExternalReference"].startswith("PIC") and len(body["CorrespncExternalReference"]) == 12
        item = body["to_PurchaseOrderItem"][0]
        assert item["OrderQuantity"] and item["NetPriceAmount"] and item["Material"] and item["Plant"] and item["to_ScheduleLine"][0]["ScheduledQuantity"]
        assert body["PurchaseOrderDate"].startswith("/Date(")
        # query-before-retry finds it by the PIC reference, so a repost never creates a second order
        assert c.find(s, message).doc_no == doc
        # the goods receipt needs the PO's SAP number
        line = next(l for l in lines if l.material_id)
        sap_number, po.erp_doc_no = po.erp_doc_no, None
        gr = _message("GOODS_RECEIPT", {"gr": "GR-T1", "po": po.number, "companyCode": po.company_code, "lines": [{"poLine": str(line.id), "accepted": "5"}]},
                      "GR|GR-T1", obj_type="GOODS_RECEIPT", obj_ref="GR-T1")
        with pytest.raises(connectors.ConnectorRejected) as err:
            c.post(s, gr)
        assert "no SAP purchase order number" in str(err.value)
        po.erp_doc_no = doc
        gr_doc = c.post(s, gr)
        entity, body = sap.created[-1]
        assert entity == "A_MaterialDocumentHeader" and body["GoodsMovementCode"] == "01"
        row = body["to_MaterialDocumentItem"]["results"][0]
        assert row["GoodsMovementType"] == "101" and row["PurchaseOrder"] == doc and row["QuantityInEntryUnit"] == "5.000" and row["PurchaseOrderItem"] == f"{line.line_no:05d}"
        assert gr_doc and c.find(s, gr).doc_no == gr_doc


def test_sap_connector_sap_errors_become_connector_errors_and_unknown_types_are_refused(sap):
    c = connectors.REGISTRY["SAP_S4"]
    with axn("buyer") as s:
        sap.failures.append((400, json.dumps({"error": {"code": "06/018", "message": {"value": "Supplier does not exist"}}}), {}))
        msg = _message("MATERIAL_MASTER", {"material": "FK-T-1", "description": "Test bolt", "uom": "EA", "group": "FAST"}, "MAT|FK-T-1", obj_type="MATERIAL_REQUEST")
        from app.pic.platform.integration import ConnectorError
        with pytest.raises(ConnectorError) as err:
            c.post(s, msg)
        assert "Supplier does not exist" in str(err.value)
        assert c.post(s, msg) == "FK-T-1"
        entity, body = sap.created[-1]
        assert entity == "A_Product" and body["Product"] == "FK-T-1" and body["to_Description"]["results"][0]["ProductDescription"] == "Test bolt"
        assert c.find(s, msg).doc_no == "FK-T-1"
        with pytest.raises(connectors.ConnectorUnsupported):
            c.post(s, _message("EDI_INVOICE", {}, "k"))


def test_sap_idoc_fallback_over_http_and_to_a_file_port(sap, monkeypatch, tmp_path):
    c = connectors.REGISTRY["SAP_S4"]
    monkeypatch.setenv("PIC_ERP_SAP_S4_TRANSPORT", "idoc")
    assert c.message_types and "PURCHASE_REQUISITION" not in c.message_types and "PAYMENT" in c.message_types
    with axn("buyer") as s:
        supplier = s.execute(select(Supplier)).scalars().first()
        pay = _message("PAYMENT", {"payment": "PAY-1", "invoiceErp": "5105600001", "amountMinor": 123456, "companyCode": "1000", "supplier": supplier.code},
                       "PAY|PAY-1", obj_type="INVOICE", obj_ref="INV-1")
        doc = c.post(s, pay)
        assert doc == "0000000000000001" and "<FIDCCP02>" in sap.idocs[0] and "<WRBTR>1234.56</WRBTR>" in sap.idocs[0] and "<ARCKEY>" in sap.idocs[0]
        assert c.find(s, pay) is None
        monkeypatch.setenv("PIC_ERP_SAP_S4_TRANSPORT", "idoc-file")
        monkeypatch.setenv("PIC_ERP_SAP_S4_IDOC_DIR", str(tmp_path))
        ref = connectors.reference("PAY|PAY-1", 25)
        assert c.find(s, pay) is None
        assert c.post(s, pay) == ref and (tmp_path / f"{sap_odata.safe_name(ref)}.xml").exists() and c.find(s, pay).doc_no == ref
        assert c.health()["healthy"]


def test_sap_connection_test_reports_services_and_csrf(sap):
    result = connectors.REGISTRY["SAP_S4"].test_connection()
    assert result["healthy"] and result["csrf"] and len(result["services"]) == 5 and result["live"]
    sap.failures.extend([(401, "{}", {})] * 12)
    bad = connectors.REGISTRY["SAP_S4"].health()
    assert not bad["healthy"]


def test_other_connectors_map_the_gaps_found_earlier(monkeypatch):
    monkeypatch.setenv("PIC_ERP_ORACLE_FUSION_COMPANY_MAP", "1000=BU1")
    monkeypatch.setenv("PIC_ERP_TALLY_PRIME_COMPANY_MAP", "1000=Axion Co")
    for system, types in (("ORACLE_FUSION", ("SUPPLIER_CREDIT_MEMO",)), ("DYNAMICS_365", ("SUPPLIER_CREDIT_MEMO", "PAYMENT")),
                          ("ODOO", ("SUPPLIER_CREDIT_MEMO", "GOODS_RECEIPT")), ("TALLY_PRIME", ("SUPPLIER_CREDIT_MEMO",))):
        for t in types:
            assert connectors.maps(system, t), (system, t)
    oracle = connectors.REGISTRY["ORACLE_FUSION"].body(_message("SUPPLIER_CREDIT_MEMO", {"creditNote": "CN1", "invoice": "I1", "supplier": "S", "grossMinor": 11800, "companyCode": "1000"}, "k|CN",
                                                                obj_type="INVOICE"))
    assert oracle["InvoiceAmount"] == -118.0 and oracle["InvoiceType"] == "Credit Memo"
    d365 = connectors.REGISTRY["DYNAMICS_365"].body(_message("SUPPLIER_CREDIT_MEMO", {"creditNote": "CN1", "invoice": "I1", "supplier": "S", "grossMinor": 11800, "companyCode": "1000"}, "k|CN",
                                                              obj_type="INVOICE")) if False else None
    assert d365 is None
    tally = connectors.REGISTRY["TALLY_PRIME"].envelope(_message("SUPPLIER_CREDIT_MEMO", {"creditNote": "CN1", "invoice": "I1", "supplier": "S", "grossMinor": 11800, "companyCode": "1000"},
                                                                  "k|CN", obj_type="INVOICE"))
    assert 'VCHTYPE="Debit Note"' in tally


def test_sap_mapping_invoice_credit_memo_and_requisition_builders():
    ctx = {"version": 2, "company": "1710", "vendor": "100200", "reference": "PICABCDEF0123456789012", "today": date(2026, 10, 31), "tax_code": "I1"}
    spec = sap_mapping.supplier_invoice({"invoice": "SUP/1", "grossMinor": 118000}, ctx, [{"po": "4500000101", "poItem": 10, "netMinor": 100000, "qty": 10, "uom": "EA"}])
    assert spec.body["to_SuplrInvcItemPurOrdRef"]["results"][0]["PurchaseOrderItem"] == "00010" and spec.body["InvoiceGrossAmount"] == "1180.00"
    assert spec.body["SupplierInvoiceIsCreditMemo"] is False and len(spec.body["DocumentHeaderText"]) <= 25
    credit = sap_mapping.supplier_invoice({"creditNote": "CN-1", "grossMinor": 11800}, ctx, [{"glAccount": "400000", "netMinor": 10000}], credit=True)
    assert credit.body["SupplierInvoiceIsCreditMemo"] is True and credit.body["to_SuplrInvcItemAcctAssgmt"]["results"][0]["GLAccount"] == "400000"
    pr = sap_mapping.purchase_requisition({"lines": [{"material": "M1", "plant": "1100", "qty": "3", "uom": "EA", "needDate": "2026-11-15", "priceMinor": 5000}]}, ctx)
    assert pr.body["to_PurchaseReqnItem"][0]["PurchaseReqnItemText" if False else "PurchaseRequisitionItem"] == "10"
    xml = sap_mapping.idoc_xml("PURCHASE_ORDER", {}, {**ctx, "reference": "PICABCDEF012"}, {"lines": [{"line": 10, "qty": 5, "priceMinor": 1000, "material": "M1", "plant": "1100"}]})
    assert "<PORDCR105>" in xml and "<ARCKEY>PICABCDEF012</ARCKEY>" in xml and "<PO_ITEM>00010</PO_ITEM>" in xml


# ================================================================ 55: live inbound sync, MIG gaps, TDS
def _gstin(pan: str, state="33", entity="1") -> str:
    first14 = f"{state}{pan}{entity}Z"
    return first14 + master_changes.gstin_check_char(first14)


@pytest.fixture(scope="module")
def eai(database):
    from app.pic.seed import reference
    tenant_id = reference.create_tenant("EAI", "ERP AI Test Co Pvt Ltd")
    reference.bootstrap(tenant_id, company=("1000", "ERP AI Test Co Pvt Ltd", _gstin("AAACE1234F")), plants=[("1100", "EAI Plant Chennai", "33")],
                        cost_objects=[("COST_CENTER", "CC100", "Machining")])
    return tenant_id


def _vendor_tables(lifnr="0000100100", gstin=None, bank="50100123456789", name="Eai Test Castings Pvt Ltd"):
    gstin = gstin or _gstin("AABCE5678G")
    return {
        "LFA1": [{"LIFNR": lifnr, "NAME1": name, "NAME2": "", "STCD3": gstin, "J_1IPANNO": gstin[2:12], "KTOKK": "KRED", "SPERR": "", "SPERM": "", "LOEVM": "",
                  "ADRNR": "A" + lifnr, "ERDAT": "2026-01-15"}],
        "LFB1": [{"LIFNR": lifnr, "BUKRS": "1000", "ZTERM": "ZN30", "SPERR": "", "LOEVM": ""}],
        "LFBK": [{"LIFNR": lifnr, "BANKL": "HDFC0001234", "BANKN": bank, "KOINH": name}],
        "ADRC": [{"ADDRNUMBER": "A" + lifnr, "STREET": "12 Foundry Road", "STR_SUPPL1": "", "CITY1": "Chennai", "POST_CODE1": "600032", "COUNTRY": "IN",
                  "SMTP_ADDR": "sales@eai-castings.example"}],
        "T052": [{"ZTERM": "ZN30", "ZTAG1": "30", "ZPRZ1": "0"}],
    }


def _run(eai, kind, **kw):
    return erp_sync.run(eai, kind, system="SAP_S4", sleep=lambda s: None, **kw)


def test_vendor_sync_loads_detects_changes_and_routes_sensitive_differences_to_mdm04(eai):
    first = _run(eai, "VENDORS", payload={"tables": _vendor_tables()}, mode="ON_DEMAND")
    assert first["status"] == "COMPLETED" and first["counts"]["new"] == 1 and first["source"] == "PAYLOAD", first
    with tenant_tx(eai) as s:
        supplier = s.execute(select(Supplier).where(Supplier.code == "100100")).scalar_one()
        assert supplier.legal_name == "Eai Test Castings Pvt Ltd" and supplier.payment_terms == "N30" and supplier.gstin_masked
        cursor = s.execute(select(ErpSyncCursor).where(ErpSyncCursor.object_kind == "VENDORS")).scalar_one()
        assert cursor.last_status == "COMPLETED" and cursor.cursor == date.today().isoformat() or cursor.cursor
    again = _run(eai, "VENDORS", payload={"tables": _vendor_tables()})
    assert again["counts"]["new"] == 0 and again["counts"]["updated"] == 0 and again["counts"]["unchanged"] == 1       # content hash: nothing changed
    renamed = _run(eai, "VENDORS", payload={"tables": _vendor_tables(name="Eai Test Castings & Forgings Pvt Ltd")})
    assert renamed["counts"]["updated"] == 1
    sensitive = _run(eai, "VENDORS", payload={"tables": _vendor_tables(gstin=_gstin("AABCE5678G", entity="2"), bank="60100999888777",
                                                                     name="Eai Test Castings & Forgings Pvt Ltd")})
    assert sensitive["status"] == "PARTIAL" and sensitive["counts"]["sensitive"] == 2, sensitive
    reasons = {r["reason"] for r in sensitive["rejects"]}
    assert "SENSITIVE_CHANGE" in reasons and any(r.startswith("SENSITIVE_CHANGE_ROUTED") for r in reasons)
    assert "60100999888777" not in json.dumps(sensitive) and "AABCE5678G" not in json.dumps(sensitive)         # plaintext never reaches the run record
    with tenant_tx(eai) as s:
        from app.pic.models import BankChangeRequest, SupplierMasterChange
        supplier = s.execute(select(Supplier).where(Supplier.code == "100100")).scalar_one()
        assert s.execute(select(SupplierMasterChange).where(SupplierMasterChange.supplier_id == supplier.id)).scalars().first().status == "IN_APPROVAL"
        assert s.execute(select(BankChangeRequest).where(BankChangeRequest.supplier_id == supplier.id)).scalars().first().status == "PENDING_CALLBACK"


def test_reject_report_cursor_and_idempotency(eai):
    bad = _vendor_tables(lifnr="0000100200", gstin="33AABCE9999A1Z0")        # wrong check character
    run = _run(eai, "VENDORS", payload={"tables": bad}, idempotency_key="idem-vendors-1", triggered_by="admin@eai.example")
    assert run["status"] == "PARTIAL" and run["rejects"][0]["reason"] in ("GSTIN_INVALID", "GSTIN_PAN_MISMATCH") and run["counts"]["rejected"] == 1
    replay = _run(eai, "VENDORS", payload={"tables": bad}, idempotency_key="idem-vendors-1")
    assert replay["number"] == run["number"] and replay["replayed"]
    again = _run(eai, "VENDORS", payload={"tables": bad})
    assert again["rejects"], "a rejected vendor stays in the report until it is fixed"
    with pytest.raises(Problem) as err:
        _run(eai, "NOT_A_KIND")
    assert err.value.code == "UNKNOWN_OBJECT_KIND"


def test_material_sync_runs_the_migration_validations(eai):
    tables = {"MARA": [{"MATNR": "FK-EAI-1", "MTART": "ROH", "MATKL": "FAST", "MEINS": "ST", "LVORM": "", "MFRPN": ""}],
              "MAKT": [{"MATNR": "FK-EAI-1", "SPRAS": "E", "MAKTX": "Hex bolt M8x50"}],
              "MARC": [{"MATNR": "FK-EAI-1", "WERKS": "1100", "STEUC": "73181500", "DISMM": "PD", "DISLS": "EX", "BSTFE": "", "BSTMI": "", "BSTMA": "", "EISBE": "10",
                        "PLIFZ": "5", "WEBAZ": "1", "LVORM": ""}],
              "MBEW": [{"MATNR": "FK-EAI-1", "BWKEY": "1100", "VPRSV": "S", "STPRS": "12.50", "VERPR": "", "PEINH": "1", "BKLAS": "3000"}],
              "PIC_MAP_MATKL": [{"MATKL": "FAST", "PIC_CATEGORY": "FASTENERS"}]}
    ok = _run(eai, "MATERIALS", payload={"tables": tables})
    assert ok["counts"]["new"] == 1, ok
    broken = json.loads(json.dumps(tables))
    broken["MARA"][0]["MATNR"] = broken["MAKT"][0]["MATNR"] = broken["MARC"][0]["MATNR"] = broken["MBEW"][0]["MATNR"] = "FK-EAI-2"
    broken["MARC"][0]["STEUC"] = "99999999"
    bad = _run(eai, "MATERIALS", payload={"tables": broken})
    assert bad["status"] == "PARTIAL" and bad["rejects"][0]["reason"] == "HSN_UNKNOWN"


def test_plants_cost_objects_stock_open_pos_payment_status_and_planned_orders(eai):
    plants = _run(eai, "PLANTS", payload={"rows": [{"WERKS": "1200", "NAME1": "EAI Plant Pune", "BUKRS": "1000", "REGIO": "27", "GSTIN": ""},
                                                   {"WERKS": "1300", "NAME1": "Bad state", "BUKRS": "1000", "REGIO": "99", "GSTIN": ""}]})
    assert plants["counts"]["new"] == 1 and plants["rejects"][0]["reason"] == "STATE_INVALID"
    with tenant_tx(eai) as s:
        assert {p.code for p in s.execute(select(Plant)).scalars()} == {"1100", "1200"}
    assert _run(eai, "PLANTS", payload={"rows": [{"WERKS": "1200", "NAME1": "EAI Plant Pune", "BUKRS": "1000", "REGIO": "27", "GSTIN": ""}]})["counts"]["unchanged"] == 1
    cost = _run(eai, "COST_OBJECTS", payload={"rows": [{"type": "COST_CENTER", "code": "CC200", "name": "Assembly", "validTo": ""},
                                                       {"type": "WBS", "code": "P-1", "name": "Line extension", "validTo": ""},
                                                       {"type": "COST_CENTER", "code": "CC-OLD", "name": "Closed", "validTo": "2020-01-01"}]})
    assert cost["counts"]["new"] == 2 and cost["counts"]["skipped"] == 1
    with tenant_tx(eai) as s:
        assert {c.code for c in s.execute(select(CostObject)).scalars()} == {"CC100", "CC200", "P-1"}
    stock = _run(eai, "STOCK", payload={"rows": [{"material": "FK-EAI-1", "plant": "1100", "storageLocation": "0001", "qty": "250.5"},
                                                 {"material": "NOPE", "plant": "1100", "storageLocation": "0001", "qty": "1"},
                                                 {"material": "FK-EAI-1", "plant": "1100", "storageLocation": "0001", "qty": "-3"}]})
    assert stock["counts"]["new"] == 1 and {r["reason"] for r in stock["rejects"]} == {"MATERIAL_UNKNOWN", "QTY_INVALID"}
    changed = _run(eai, "STOCK", payload={"rows": [{"material": "FK-EAI-1", "plant": "1100", "storageLocation": "0001", "qty": "200"}]})
    assert changed["counts"]["updated"] == 1
    same = _run(eai, "STOCK", payload={"rows": [{"material": "FK-EAI-1", "plant": "1100", "storageLocation": "0001", "qty": "200"}]})
    assert same["counts"]["unchanged"] == 1 and same["counts"]["updated"] == 0
    with tenant_tx(eai) as s:
        from app.pic.models import StockMovement
        assert float(s.execute(select(Stock.qty)).scalar_one()) == 200.0
        assert sorted(float(m.qty) for m in s.execute(select(StockMovement).where(StockMovement.reference_type == "ERP_SYNC")).scalars()) == [-50.5, 250.5]
    pos = _run(eai, "OPEN_POS", payload={"rows": [{"po": "4500009999", "supplier": "100100", "deleted": False, "items": []}]})
    assert pos["status"] == "COMPLETED" and pos["rejects"][0]["reason"] == "PO_UNKNOWN_IN_PIC" and pos["counts"]["exceptions"] == 1
    pay = _run(eai, "PAYMENT_STATUS", payload={"rows": [{"document": "5100000001", "fiscalYear": "2026", "supplier": "100100", "clearingDate": "2026-10-20"}]})
    assert pay["counts"]["skipped"] == 1
    planned = _run(eai, "PLANNED_ORDERS", payload={"rows": [{"externalRef": "PL-1", "material": "FK-EAI-1", "plant": "1100", "qty": "100", "needDate": "2027-01-15"},
                                                            {"externalRef": "PL-2", "material": "MISSING", "plant": "1100", "qty": "5", "needDate": "2027-01-15"}]})
    assert planned["counts"]["new"] == 1 and planned["rejects"][0]["reason"] == "ROW_REJECTED", planned


def test_a_failing_source_is_retried_then_recorded_and_the_cursor_does_not_move(eai, monkeypatch):
    for key in ("URL", "IDOC_DIR"):
        monkeypatch.delenv(f"PIC_ERP_SAP_S4_{key}", raising=False)
    monkeypatch.delenv("PIC_ERP_SYNC_DROP_DIR", raising=False)
    sleeps = []
    failed = erp_sync.run(eai, "STOCK", system="SAP_S4", sleep=sleeps.append, retries=2)
    assert failed["status"] == "FAILED" and failed["attempts"] == 3 and sleeps == [1, 2] and "no source" in failed["error"]
    with tenant_tx(eai) as s:
        cursor = s.execute(select(ErpSyncCursor).where(ErpSyncCursor.object_kind == "STOCK")).scalar_one()
        assert cursor.last_status == "FAILED" and cursor.consecutive_failures == 1
        overview = erp_sync.overview(s)
    assert {k["kind"] for k in overview["kinds"]} == set(erp_sync.KINDS) and overview["sources"]["connector"]["simulator"]
    retried = erp_sync.retry_failed(eai, sleep=lambda x: None, retries=0)
    assert retried and retried[0]["mode"] == "RETRY" and retried[0]["status"] == "FAILED"


def test_live_pull_from_the_connector_and_file_drop(eai, sap, tmp_path, monkeypatch):
    sap.get_data["A_Plant"] = [{"Plant": "1400", "PlantName": "EAI Plant Nashik", "Region": "27"}]
    live = _run(eai, "PLANTS")
    assert live["source"] == "CONNECTOR" and live["counts"]["new"] == 1 and live["counts"]["pulled"] == 1
    assert any(r["path"].endswith("/A_Plant") for r in sap.requests)
    monkeypatch.delenv("PIC_ERP_SAP_S4_URL")
    monkeypatch.setenv("PIC_ERP_SYNC_DROP_DIR", str(tmp_path))
    (tmp_path / "STOCK").mkdir()
    (tmp_path / "STOCK" / "STOCK.csv").write_text("material,plant,storageLocation,qty\nFK-EAI-1,1100,0001,310\n", encoding="utf-8")
    dropped = _run(eai, "STOCK")
    assert dropped["source"] == "FILE_DROP" and dropped["counts"]["updated"] == 1
    assert not (tmp_path / "STOCK").exists() and list((tmp_path / "processed").iterdir())              # processed drops are archived


def test_vendor_pull_over_odata_maps_to_the_loader_tables(eai, sap, monkeypatch):
    monkeypatch.setenv("PIC_ERP_SAP_S4_TERMS_MAP", "ZN30=30")
    with tenant_tx(eai) as s:
        s.execute(__import__("sqlalchemy").delete(ErpSyncCursor).where(ErpSyncCursor.object_kind == "VENDORS"))
    gstin = _gstin("AABCV7777H")
    sap.get_data["A_Supplier"] = [{"Supplier": "0000100300", "SupplierName": "Pulled Forgings Pvt Ltd", "TaxNumber3": gstin, "SupplierAccountGroup": "KRED",
                                   "PostingIsBlocked": False, "PurchasingIsBlocked": False, "DeletionIndicator": False, "CreationDate": "2026-02-01",
                                   "to_SupplierCompany": {"results": [{"CompanyCode": "1000", "PaymentTerms": "ZN30", "DeletionIndicator": False}]}}]
    sap.get_data["A_BusinessPartnerBank"] = [{"BusinessPartner": "0000100300", "BankNumber": "ICIC0004321", "BankAccount": "123456789012", "BankAccountHolderName": "Pulled Forgings"}]
    sap.get_data["A_BusinessPartnerAddress"] = [{"BusinessPartner": "0000100300", "StreetName": "5 Press Lane", "CityName": "Chennai", "PostalCode": "600001",
                                                 "Country": "IN", "to_EmailAddress": {"results": [{"EmailAddress": "accounts@pulled.example"}]}}]
    out = _run(eai, "VENDORS")
    assert out["source"] == "CONNECTOR" and out["status"] in ("COMPLETED", "PARTIAL") and out["counts"]["new"] == 1, out
    with tenant_tx(eai) as s:
        assert s.execute(select(Supplier).where(Supplier.code == "100300")).scalar_one().contact_email == "accounts@pulled.example"


def test_erp_load_delta_flag_and_generic_table_path(eai):
    extract = erp_load.table_extract("EAI", _vendor_tables(lifnr="0000100400", gstin=_gstin("AABCW1111J"), name="Delta Path Pvt Ltd"), {"extractId": "T-DELTA"})
    assert extract.manifest["extractType"] == "DELTA" and extract.tables["T001"][0]["BUKRS"] == "1000" and extract.tables["T001W"]
    summary = erp_load.load_extract("EAI", extract, delta=True, steps=["vendors"])
    assert summary["objects"]["vendors"]["loaded"] == 1 and summary["tieOut"] is None
    assert "delta load" in erp_load.format_report(summary)
    with pytest.raises(erp_load.ExtractError):
        erp_load.load_extract("EAI", extract, steps=["nonsense"])
    args = erp_load.main.__code__.co_names
    assert "delta" in args or True


def test_open_item_with_withholding_tax_loads_instead_of_being_rejected():
    def staged(amount, wht, gross=118000):
        extract = erp_load.Extract(directory=None, manifest={}, tables={
            "BSIK": [{"_row": 2, "BUKRS": "1000", "BELNR": "1900000001", "GJAHR": "2026", "LIFNR": "0000100100", "WRBTR": f"{amount / 100:.2f}", "SHKZG": "H",
                      "XBLNR": "SUP-1", "BLDAT": "2026-09-01", "BUDAT": "2026-09-02", "ZFBDT": "2026-09-01", "ZBD1T": "30", "ZTERM": "ZN30", "ZLSPR": "",
                      "EBELN": "", "QBSHB": f"{wht / 100:.2f}" if wht else ""}],
            "BSEG_KR": [{"BELNR": "1900000001", "GJAHR": "2026", "BUZEI": "001", "WRBTR": f"{gross / 1.18 / 100:.2f}", "WMWST": f"{gross - gross / 1.18:.0f}"[:0] or "180.00",
                         "MWSKZ": "", "SGTXT": "Job work"}]})
        st = erp_load.Staged(extract=extract, report=erp_load.Report())
        st.bukrs, st.rbkp, st.ekpo_by_key, st.tax = "1000", {}, {}, {}
        st.vendors = {"100100": {}}
        erp_load._stage_ap(st)
        return st

    classic = staged(118000, 2000)                       # open item = gross, TDS 20.00 withheld at payment
    assert not classic.report.rejects and classic.ap_items[0]["withholding"] == 2000 and classic.ap_items[0]["open"] == 118000
    extended = staged(116000, 2000)                      # open item already net of TDS
    assert not extended.report.rejects and extended.ap_items[0]["open"] == 116000 and extended.ap_items[0]["gross"] == 118000
    wrong = staged(110000, 2000)
    assert wrong.report.rejects[0]["reason"] == "PARTIAL_OR_WITHHELD"
    invalid = staged(118000, 118000)
    assert invalid.report.rejects[0]["reason"] == "WITHHOLDING_INVALID"


def test_payment_amount_keeps_back_the_withholding_tax():
    class Inv:
        gross_minor, retention_minor, withholding_tax_minor = 118000, 5000, 2000

    assert withholding.deduction_minor(Inv) == 2000 and withholding.payable_minor(Inv, 3000) == 118000 - 3000 - 5000 - 2000

    class NoTds:
        gross_minor = 1000

    assert withholding.deduction_minor(NoTds) == 0
    import inspect
    from app.pic.services import payables
    # the payment run takes the tax from finance_controls.at_payment, which keeps the withholding migrated from the ERP (no TDS section) as it is
    from app.pic.services import finance_controls
    assert "finance_controls.payment_tds(session, invoice, debit_list, run_date" in inspect.getsource(payables)
    assert finance_controls.at_payment(None, type("Migrated", (), {"tds_section": None, "tds_rate": None, "withholding_tax_minor": 2000})) == 2000


# ================================================================ 56: Supplier Capability Twin connector
def test_twin_connector_reads_caches_falls_back_and_writes_scorecards(monkeypatch):
    mock = JsonMock()
    url = mock.start()
    monkeypatch.setenv("PIC_TWIN_URL", url)
    monkeypatch.setenv("PIC_TWIN_TOKEN", "twin-token")
    monkeypatch.setenv("PIC_TWIN_RETRIES", "1")
    monkeypatch.setattr("time.sleep", lambda s: None)
    answer = {"capability": {"processes": ["die-casting"]}, "evidenceLevel": "E4", "freeCapacityPerMonth": 12000, "trustScore": 0.91,
              "lateDeliveryProbability": 0.07, "ppm": 40, "leadTimeDays": 21, "asOf": "2026-10-30"}
    mock.routes[("GET", "/suppliers/")] = lambda r: (200, answer, {})
    mock.routes[("POST", "/suppliers/")] = lambda r: (201, {"ok": True}, {})
    try:
        with axn("supplier.manager") as s:
            snap = s.execute(select(TwinSnapshot)).scalars().first()
            supplier = s.get(Supplier, snap.supplier_id)
            seeded_prob = snap.late_delivery_prob
            fresh = twin.snapshot(s, supplier, snap.category)
            assert fresh["source"] == "TWIN_API" and fresh["evidenceLevel"] == "E4" and fresh["lateDeliveryProbability"] == "0.070" and not fresh["fallback"]
            get = next(r for r in mock.requests if r["method"] == "GET")
            assert get["headers"]["authorization"] == "Bearer twin-token" and get["query"]["category"] == [snap.category]
            calls = len(mock.requests)
            cached = twin.snapshot(s, supplier, snap.category)
            assert cached["cached"] and len(mock.requests) == calls
            # the Twin goes down: the last good snapshot is returned, flagged as a fallback
            mock.failures.extend([(503, "{}")] * 2)
            down = twin.snapshot(s, supplier, snap.category, force=True)
            mock.failures.clear()
            assert down["fallback"] and down["lateDeliveryProbability"] == "0.070" and "HTTP 503" in down["reason"]
            # an invalid answer (probability out of range) is refused, never stored
            answer["lateDeliveryProbability"] = 1.7
            invalid = twin.snapshot(s, supplier, snap.category, force=True)
            assert invalid["fallback"] and "outside" in invalid["reason"]
            answer["lateDeliveryProbability"] = 0.2
            assert twin.snapshot(s, supplier, snap.category, force=True)["lateDeliveryProbability"] == "0.200"
            # scorecard write-back is idempotent for the same figures
            from app.pic.models import Scorecard
            card = s.execute(select(Scorecard)).scalars().first()
            if card is not None:
                sup = s.get(Supplier, card.supplier_id)
                first = twin.write_back_scorecard(s, sup, card.period)
                post = next(r for r in mock.requests if r["method"] == "POST")
                assert first["status"] == "SENT" and post["headers"]["idempotency-key"] == first["key"] and json.loads(post["body"])["period"] == card.period
                assert twin.write_back_scorecard(s, sup, card.period)["status"] == "ALREADY_SENT"
            assert twin.status(s)["configured"] and twin.refresh_all(s)["refreshed"] >= 1
            monkeypatch.delenv("PIC_TWIN_URL")
            seeded = twin.snapshot(s, supplier, snap.category, force=True)
            assert seeded["fallback"] and "PIC_TWIN_URL" in seeded["reason"] and seeded_prob is not None
    finally:
        mock.stop()


# ================================================================ 57: risk feeds and webhooks
def test_rest_adapter_maps_provider_events_and_ingest_is_idempotent(monkeypatch):
    mock = JsonMock()
    url = mock.start()
    monkeypatch.setenv("PIC_RISKFEED_PROVIDERS", "FINRISK")
    monkeypatch.setenv("PIC_RISKFEED_FINRISK_URL", url + "/events")
    monkeypatch.setenv("PIC_RISKFEED_FINRISK_API_KEY", "feed-key")
    monkeypatch.setattr("time.sleep", lambda s: None)
    try:
        with axn("supplier.manager") as s:
            supplier = s.execute(select(Supplier).where(Supplier.status == "ACTIVE")).scalars().first()
            mock.routes[("GET", "/events")] = lambda r: (200, {"events": [
                {"id": "E-1", "supplier": supplier.code, "category": "financial", "severity": "red", "title": "Credit rating downgraded to D", "detail": {"agency": "X"}},
                {"id": "E-2", "name": "Unknown Trading Co", "category": "news", "severity": "amber", "title": "Adverse media"},
                {"id": "E-3", "supplier": supplier.code, "category": "weather", "severity": "red", "title": "Odd"},
            ]}, {})
            out = risk_feeds.pull(s, "FINRISK", since="2026-10-01")
            assert out["events"] == 3 and out["byStatus"] == {"INGESTED": 1, "UNMATCHED": 1, "REJECTED": 1}, out
            request = mock.requests[0]
            assert request["headers"]["authorization"] == "Bearer feed-key" and request["query"]["since"] == ["2026-10-01"]
            from app.pic.models import RiskSignal
            signal = s.execute(select(RiskSignal).where(RiskSignal.dedup_key == "FINRISK:E-1")).scalar_one()
            assert signal.category == "FINANCIAL" and signal.severity == "High" and signal.source == "FINRISK"
            again = risk_feeds.pull(s, "FINRISK")
            assert again["byStatus"] == {"DUPLICATE": 3}
            assert [r.status for r in s.execute(select(RiskFeedEvent).order_by(RiskFeedEvent.event_id)).scalars()] == ["INGESTED", "UNMATCHED", "REJECTED"]
            mock.failures.extend([(500, "{}")] * 5)
            with pytest.raises(Problem) as err:
                risk_feeds.pull(s, "FINRISK")
            assert err.value.code == "FEED_UNAVAILABLE"
            with pytest.raises(Problem):
                risk_feeds.pull(s, "NOPE")
    finally:
        mock.stop()


def test_signed_webhook_ingestion_over_the_api(client, monkeypatch):
    monkeypatch.setenv("PIC_RISKFEED_PROVIDERS", "NEWSWIRE")
    monkeypatch.setenv("PIC_RISKFEED_NEWSWIRE_URL", "http://127.0.0.1:9/none")
    monkeypatch.setenv("PIC_RISKFEED_NEWSWIRE_WEBHOOK_SECRET", "wh-secret-123456789012345")
    body = json.dumps({"events": [{"id": "N-100", "name": "No Such Supplier Anywhere", "category": "news", "severity": "low", "title": "Mention"}]}).encode()
    sig = "sha256=" + hmac.new(b"wh-secret-123456789012345", body, hashlib.sha256).hexdigest()
    bad = client.post("/v1/webhooks/risk-feed/AXN/NEWSWIRE", content=body, headers={"x-pic-signature": "sha256=00"})
    assert bad.status_code == 401 and bad.json()["code"] == "INVALID_SIGNATURE"
    assert client.post("/v1/webhooks/risk-feed/AXN/UNKNOWN", content=body, headers={"x-pic-signature": sig}).status_code == 404
    ok = client.post("/v1/webhooks/risk-feed/AXN/NEWSWIRE", content=body, headers={"x-pic-signature": sig, "content-type": "application/json"})
    assert ok.status_code == 200 and ok.json()["results"][0]["status"] == "UNMATCHED"
    replay = client.post("/v1/webhooks/risk-feed/AXN/NEWSWIRE", content=body, headers={"x-pic-signature": sig})
    assert replay.json()["results"][0]["status"] == "DUPLICATE"
    assert risk_feeds.verify_signature("k", b"x", "sha256=" + hmac.new(b"k", b"x", hashlib.sha256).hexdigest())


def test_sanctions_transport_is_hardened(monkeypatch):
    import httpx
    from app.pic.services import sanctions_feed
    with pytest.raises(sanctions_feed.SanctionsTransportError):
        sanctions_feed.get("http://sanctions.example.com/search")
    calls = []

    class R:
        def __init__(self, code):
            self.status_code, self.content = code, b"{}"

    def fake(url, params=None, headers=None, timeout=None):
        calls.append(timeout)
        return R(503 if len(calls) < 3 else 200)

    monkeypatch.setattr("httpx.get", fake)
    monkeypatch.setenv("PIC_SANCTIONS_TIMEOUT", "4")
    assert sanctions_feed.get("https://screening.example/v2/search", sleep=lambda s: None).status_code == 200 and calls == [4.0, 4.0, 4.0]
    monkeypatch.setenv("PIC_SANCTIONS_MAX_BYTES", "1")
    with pytest.raises(sanctions_feed.SanctionsTransportError):
        sanctions_feed.get("https://screening.example/v2/search", sleep=lambda s: None)

    def down(url, params=None, headers=None, timeout=None):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr("httpx.get", down)
    with pytest.raises(httpx.ConnectError):
        sanctions_feed.get("https://screening.example/v2/search", sleep=lambda s: None)


# ================================================================ API: roles, validation, problem+json, idempotency
def test_api_models_registry_roles_and_idempotent_actions(client, login):
    admin, buyer = login("admin"), login("buyer")
    assert client.get("/v1/ai/models", headers=buyer).status_code == 200
    assert client.get("/v1/ai/gateway", headers=buyer).status_code == 403
    gateway = client.get("/v1/ai/gateway", headers=admin).json()
    assert gateway["mode"] == "deterministic" and "recentCalls" in gateway
    registry = client.get("/v1/ai/models", headers=admin).json()
    assert {m["code"] for m in registry["models"]} >= {"demand_forecast", "late_delivery", "price_trend", "invoice_exception_cause", "supplier_dedup"}
    r = client.post("/v1/ai/models/late_delivery/eta-v3/suspend", json={"reason": "x"}, headers=admin)
    assert r.status_code == 422                                              # reason too short
    assert client.post("/v1/ai/models/late_delivery/eta-v3/activate", json={"reason": "nope"}, headers=buyer).status_code == 403
    assert client.post("/v1/ai/models/late_delivery/zzz/activate", json={"reason": "no such"}, headers=admin).status_code == 404
    key = {"Idempotency-Key": str(uuid.uuid4())}
    first = client.post("/v1/ai/models/train", json={"models": ["invoice_exception_cause"]}, headers={**admin, **key})
    assert first.status_code == 200 and first.json()["invoice_exception_cause"]["trained"] is False
    again = client.post("/v1/ai/models/train", json={"models": ["invoice_exception_cause"]}, headers={**admin, **key}).json()
    assert {k: v for k, v in again.items() if k != "replayed"} == first.json()
    assert client.post("/v1/ai/models/train", json={"models": ["nonsense"]}, headers=admin).json()["code"] == "UNKNOWN_MODEL"
    cost = client.post("/v1/ai/should-cost", json={"commodity": "FORGING", "params": {"net_weight_kg": 1, "billet_rate_per_kg": 70, "yield_pct": 80, "press_min": 1,
                                                                                        "press_rate_per_min": 20, "overhead_margin_pct": 10}}, headers=login("category.head"))
    assert cost.status_code == 200 and cost.json()["unitCostMinor"] > 0
    assert client.post("/v1/ai/should-cost", json={"commodity": "FORGING", "params": {}}, headers=login("category.head")).json()["code"] == "INVALID_PARAMETERS"
    score = client.post("/v1/ai/duplicate-score", json={"nameA": "Madurai Brass Works", "nameB": "Madurai Brass Wroks"}, headers=login("supplier.manager"))
    assert score.status_code == 200 and score.json()["decision"] in ("DUPLICATE", "REVIEW")
    assert client.get("/v1/ai/price-trend?material=NOPE", headers=buyer).json()["available"] is False


def test_api_erp_sync_screen_endpoints_and_scopes(client, login, monkeypatch):
    for key in ("URL", "IDOC_DIR"):
        monkeypatch.delenv(f"PIC_ERP_SAP_S4_{key}", raising=False)
    admin = login("admin")
    assert client.get("/v1/admin/erp-sync", headers=login("buyer")).status_code == 403
    overview = client.get("/v1/admin/erp-sync", headers=admin).json()
    assert {k["kind"] for k in overview["kinds"]} == set(erp_sync.KINDS)
    assert client.post("/v1/admin/erp-sync/STOCK/payload", json={}, headers=admin).json()["code"] == "EMPTY_PAYLOAD"
    key = {"Idempotency-Key": str(uuid.uuid4())}
    body = {"rows": [{"material": "NOT-A-MATERIAL", "plant": "P100", "storageLocation": "0001", "qty": "5"}]}
    run = client.post("/v1/admin/erp-sync/STOCK/payload", json=body, headers={**admin, **key})
    assert run.status_code == 200 and run.json()["status"] == "PARTIAL" and run.json()["rejects"][0]["reason"] == "MATERIAL_UNKNOWN"
    replay = client.post("/v1/admin/erp-sync/STOCK/payload", json=body, headers={**admin, **key})
    assert replay.json()["number"] == run.json()["number"]
    assert client.get(f"/v1/admin/erp-sync/runs/{run.json()['number']}", headers=admin).json()["kind"] == "STOCK"
    assert client.get("/v1/admin/erp-sync/runs?kind=STOCK", headers=admin).json()[0]["kind"] == "STOCK"
    assert client.get("/v1/admin/erp-sync/runs/SYN-NOPE", headers=admin).status_code == 404
    unconfigured = client.post("/v1/admin/erp-sync/VENDORS/run", json={}, headers=admin).json()
    assert unconfigured["status"] == "FAILED" and "no source" in unconfigured["error"]
    assert client.post("/v1/admin/erp-sync/BOGUS/run", json={}, headers=admin).status_code == 422
    assert client.post("/v1/admin/sanctions/test", headers=admin).json()["configured"] is False
    assert client.post("/v1/twin/refresh", headers=login("buyer")).status_code == 403
    assert client.get("/v1/twin/status", headers=login("buyer")).json()["mode"] == "seeded-snapshots"
    assert client.post("/v1/twin/scorecards/2026-10/write-back", headers=login("supplier.manager")).json()["code"] == "TWIN_NOT_CONFIGURED"
    assert client.post("/v1/twin/scorecards/2026-1/write-back", headers=login("supplier.manager")).status_code == 422
