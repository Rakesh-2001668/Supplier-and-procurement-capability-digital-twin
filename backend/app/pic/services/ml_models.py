"""The platform's light ML models (Technical Document §13), trained and scored without external libraries (``ml_core``).

    demand_forecast          seasonal baseline + gradient-boosted stumps on its residuals; chosen against exponential smoothing
                             per series by a rolling back-test on data before the forecast origin (never on the future)
    late_delivery            logistic regression on receipt history (supplier late-rate prior, order value, lead time, season, ASN)
    price_trend              Holt exponential smoothing with damped trend and an 80 % band per material
    invoice_exception_cause  naive Bayes over exception features, label = how comparable exceptions were resolved
    supplier_dedup           character n-gram hashing embedding (cosine) combined with the F8-03 rules and a PAN veto
    should_cost              parametric models for forging and plastic injection moulding, calibrated on ERP price history

Each model has a version string, is trained reproducibly by ``python -m app.pic.tools.ai_train`` (same data, same parameters),
stores its metrics in the registry (``ml_registry``) and is used only while its version is ACTIVE or the shipped default.
"""
import difflib
import hashlib
import json
import math
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import (
    GoodsReceipt, Invoice, InvoiceException, Material, PoLine, PurchaseOrder, Supplier, TwinFeedback, TwinSnapshot,
)
from app.pic.platform import audit, clock
from app.pic.services import ml_core, ml_registry

DEMAND = "demand_forecast"
DEMAND_VERSION = "demand-sgb-v1"
LATE = "late_delivery"
LATE_VERSION = "late-lr-v1"
TREND = "price_trend"
TREND_VERSION = "price-holt-v1"
CAUSE = "invoice_exception_cause"
CAUSE_VERSION = "exc-nb-v1"
DEDUP = "supplier_dedup"
DEDUP_VERSION = "dedup-emb-v1"
MIN_LATE_ROWS = 200


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _shift(period: str, months: int) -> str:
    y, m = int(period[:4]), int(period[5:]) + months
    while m > 12:
        y, m = y + 1, m - 12
    while m < 1:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}"


# ================================================================ demand forecast
def _seasonal(by_period: dict, target: str, recent: int = 3) -> Optional[float]:
    """Year-ago value of the target month scaled by the recent year-on-year growth (clamped to 0.5-2)."""
    base = by_period.get(_shift(target, -12))
    if not base:
        return None
    ratios = []
    for p in sorted(by_period)[-recent:]:
        year_ago = by_period.get(_shift(p, -12))
        if year_ago:
            ratios.append(by_period[p] / year_ago)
    scale = sum(ratios) / len(ratios) if ratios else 1.0
    return base * min(max(scale, 0.5), 2.0)


def _gb_features(by_period: dict, target: str) -> list[float]:
    month = int(target[5:])
    prev = by_period.get(_shift(target, -1))
    prev2 = by_period.get(_shift(target, -2))
    change = (prev / prev2 - 1) if prev and prev2 else 0.0
    return [math.sin(2 * math.pi * month / 12), math.cos(2 * math.pi * month / 12), max(min(change, 1.0), -1.0)]


def _gb_correction(by_period: dict) -> Optional[ml_core.GradientBoostedStumps]:
    """Boosted stumps on the relative residual of the seasonal baseline, trained only on periods inside ``by_period``."""
    rows, targets = [], []
    for target in sorted(by_period):
        earlier = {p: v for p, v in by_period.items() if p < target}
        predicted = _seasonal(earlier, target)
        if predicted and by_period[target]:
            rows.append(_gb_features(earlier, target))
            targets.append(by_period[target] / predicted - 1)
    if len(rows) < 6:
        return None
    return ml_core.GradientBoostedStumps(rounds=20, learning_rate=0.3, min_leaf=2).fit(rows, targets)


def _predict(method: str, by_period: dict, target: str, alpha: float) -> Optional[float]:
    history = [by_period[p] for p in sorted(by_period)]
    if method == "EXP_SMOOTHING":
        return ml_core.exp_smoothing(history, alpha) if history else None
    base = _seasonal(by_period, target)
    if base is None:
        return None
    if method == "SEASONAL":
        return base
    model = _gb_correction(by_period)
    if model is None:
        return base
    correction = max(min(model.predict(_gb_features(by_period, target)), 0.15), -0.15)
    return base * (1 + correction)


def forecast_series(history: list[tuple[str, float]], current: str, horizon: int = 3, alpha: float = 0.3, version: str = DEMAND_VERSION) -> dict:
    """Forecast ``horizon`` months from ``current`` (history ends before it). With the shipped version the method per series is
    the one with the smallest one-step error over the last three back-test origins among exponential smoothing, the seasonal
    baseline and seasonal + boosted stumps; a challenger replaces smoothing only when it is at least 2 % better. A horizon
    month without a year-ago value uses smoothing. ``version = demand-es-v1`` forces plain smoothing (registry fallback)."""
    by_period = {p: float(v) for p, v in history if v is not None}
    periods = sorted(by_period)
    level = ml_core.exp_smoothing([by_period[p] for p in periods], alpha) if periods else 0.0
    out = {"method": "EXP_SMOOTHING", "values": [level] * horizon, "level": level, "backtest": {}}
    if version != DEMAND_VERSION or len(periods) < 13:
        return out
    scores = {}
    for method in ("EXP_SMOOTHING", "SEASONAL", "SEASONAL_GB"):
        errors = []
        for target in periods[-3:]:
            earlier = {p: v for p, v in by_period.items() if p < target}
            predicted = _predict(method, earlier, target, alpha) if len(earlier) >= 3 else None
            if predicted is not None and by_period[target]:
                errors.append(abs(predicted - by_period[target]) / by_period[target])
        if errors:
            scores[method] = (sum(errors) / len(errors), len(errors))
    chosen = "EXP_SMOOTHING"
    base = scores.get("EXP_SMOOTHING")
    for method in ("SEASONAL", "SEASONAL_GB"):
        s = scores.get(method)
        if s and s[1] >= 2 and base and s[0] < base[0] * 0.98 and (chosen == "EXP_SMOOTHING" or s[0] < scores[chosen][0] - 1e-12):
            chosen = method
    out["backtest"] = {m: round(v[0], 4) for m, v in scores.items()}
    if chosen == "EXP_SMOOTHING":
        return out
    values, methods = [], []
    for h in range(horizon):
        predicted = _predict(chosen, by_period, _shift(current, h), alpha)
        values.append(predicted if predicted is not None else level)
        methods.append(chosen if predicted is not None else "EXP_SMOOTHING")
    out.update(method=chosen, values=values, methods=methods)
    return out


def evaluate_demand(series: dict[str, list[tuple[str, float]]], min_history: int = 8) -> dict:
    """Rolling-origin horizon-1 error of smoothing and of the challenger over every series (reproducible training/evaluation)."""
    errors = {"EXP_SMOOTHING": [], "CHALLENGER": []}
    for key, history in series.items():
        history = sorted(history)
        for i in range(min_history, len(history)):
            origin = history[i][0]
            actual = history[i][1]
            if not actual:
                continue
            past = history[:i]
            base = forecast_series(past, origin, 1, version="demand-es-v1")["values"][0]
            challenger = forecast_series(past, origin, 1)["values"][0]
            errors["EXP_SMOOTHING"].append(abs(base - actual) / actual)
            errors["CHALLENGER"].append(abs(challenger - actual) / actual)
    n = len(errors["EXP_SMOOTHING"])
    return {"points": n, "mapeH1Baseline": round(sum(errors["EXP_SMOOTHING"]) / n, 4) if n else None,
            "mapeH1": round(sum(errors["CHALLENGER"]) / n, 4) if n else None}


def demand_series(session: Session) -> dict:
    from app.pic.models import Forecast
    out = defaultdict(list)
    for f in session.execute(select(Forecast).where(Forecast.actual_qty.is_not(None)).order_by(Forecast.period)).scalars():
        out[(f.material_id, f.plant)].append((f.period, float(f.actual_qty)))
    return out


def train_demand(session: Session, activate: bool = True) -> dict:
    series = demand_series(session)
    metrics = evaluate_demand(series)
    ok = metrics["mapeH1"] is not None and metrics["mapeH1Baseline"] is not None and metrics["mapeH1"] <= metrics["mapeH1Baseline"] + 1e-9
    model = ml_registry.register(
        session, code=DEMAND, version=DEMAND_VERSION, kind="BOOSTED_STUMPS", params={"alpha": 0.3, "stumps": {"rounds": 20, "learningRate": 0.3},
                                                                                     "selection": "rolling back-test, 3 origins, 2 % margin"},
        metrics={"train": metrics}, training={"series": len(series), "points": metrics["points"], "dataHash": _hash(sorted((str(k), v) for k, v in series.items()))},
        description="Seasonal baseline + boosted stumps on residuals, chosen against exponential smoothing per series")
    gate = bool(ok)
    ml_registry.record_eval(session, code=DEMAND, version=DEMAND_VERSION, dataset="tenant rolling origin", metrics=metrics, gate=gate)
    if activate and gate:
        ml_registry.ensure_baselines(session)
        ml_registry.activate_version(session, DEMAND, DEMAND_VERSION, "mean absolute error not above exponential smoothing")
    return {"model": ml_registry.view(model), "metrics": metrics, "activated": bool(activate and gate)}


# ================================================================ late delivery
LATE_FEATURES = ["supplierLateRate", "logOrderValue", "leadDays", "monthSin", "monthCos", "hasAsn"]


def late_features(prior: float, value_minor: float, lead_days: float, month: int, has_asn: bool) -> list[float]:
    return [prior, math.log1p(max(value_minor, 0) / 100), min(max(lead_days, 0), 180), math.sin(2 * math.pi * month / 12),
            math.cos(2 * math.pi * month / 12), 1.0 if has_asn else 0.0]


def late_rows(session: Session) -> list[dict]:
    """One row per posted receipt, oldest first. Label = the receipt was not on time and in full (the platform's receipt OTIF
    feedback). The supplier prior uses only earlier receipts of that supplier, so no row sees its own outcome."""
    query = (select(GoodsReceipt, PurchaseOrder, TwinFeedback.value)
             .join(PurchaseOrder, PurchaseOrder.id == GoodsReceipt.po_id)
             .join(TwinFeedback, (TwinFeedback.source_ref == GoodsReceipt.number) & (TwinFeedback.metric == "RECEIPT_OTIF")
                   & (TwinFeedback.supplier_id == PurchaseOrder.supplier_id))
             .where(GoodsReceipt.status != "REVERSED").order_by(GoodsReceipt.posting_date, GoodsReceipt.number))
    seen = defaultdict(lambda: [0, 0])      # supplier -> [late, total]
    rows = []
    for gr, po, otif in session.execute(query).all():
        late = 0 if float(otif) >= 1 else 1
        s = seen[po.supplier_id]
        prior = (s[0] + 1) / (s[1] + 2)
        lead = (gr.posting_date - po.created_at.date()).days
        rows.append({"supplier": str(po.supplier_id), "date": gr.posting_date.isoformat(), "label": late,
                     "x": late_features(prior, po.total_minor, lead, gr.posting_date.month, gr.asn_id is not None)})
        s[0] += late
        s[1] += 1
    return rows


def train_late_from_rows(rows: list[dict]) -> dict:
    """Chronological 80/20 split; reports AUC and Brier against the base-rate predictor."""
    cut = int(len(rows) * 0.8)
    train, test = rows[:cut], rows[cut:]
    X, y = [r["x"] for r in train], [r["label"] for r in train]
    model = ml_core.LogisticRegression(l2=1.0, epochs=300, lr=0.3).fit(X, y)
    prob = [model.predict_proba(r["x"]) for r in test]
    truth = [r["label"] for r in test]
    base_rate = sum(y) / len(y)
    metrics = {"rows": len(rows), "train": len(train), "test": len(test), "lateRate": round(sum(r["label"] for r in rows) / len(rows), 4),
               "auc": _round(ml_core.auc(truth, prob)), "brier": _round(ml_core.brier(truth, prob)),
               "brierBaseRate": _round(ml_core.brier(truth, [base_rate] * len(truth))), "logLoss": _round(ml_core.log_loss(truth, prob))}
    metrics["beatsBaseRate"] = bool(metrics["brier"] is not None and metrics["brier"] < metrics["brierBaseRate"]
                                    and metrics["auc"] is not None and metrics["auc"] >= 0.6)
    return {"model": model, "metrics": metrics,
            "baseline": ml_registry.feature_baseline({n: [r["x"][i] for r in train] for i, n in enumerate(LATE_FEATURES)})}


def _round(v: Optional[float], n: int = 4) -> Optional[float]:
    return round(v, n) if v is not None else None


def train_late_delivery(session: Session, *, min_rows: int = MIN_LATE_ROWS, activate: bool = True, rows: Optional[list] = None) -> dict:
    rows = rows if rows is not None else late_rows(session)
    positives = sum(r["label"] for r in rows)
    if len(rows) < min_rows or positives < 20 or len(rows) - positives < 20:
        return {"trained": False, "reason": f"not enough receipt history ({len(rows)} receipts, {positives} late; need {min_rows} with at least 20 of each outcome)",
                "rows": len(rows)}
    trained = train_late_from_rows(rows)
    model = ml_registry.register(
        session, code=LATE, version=LATE_VERSION, kind="LOGISTIC", params={"model": trained["model"].to_dict(), "features": LATE_FEATURES},
        metrics={"test": trained["metrics"]}, baseline=trained["baseline"],
        training={"rows": len(rows), "from": rows[0]["date"], "to": rows[-1]["date"], "dataHash": _hash(rows), "label": "receipt not on time and in full"},
        description="Logistic regression on receipt history; replaces the seeded twin late-delivery probability")
    gate = trained["metrics"]["beatsBaseRate"]
    ml_registry.record_eval(session, code=LATE, version=LATE_VERSION, dataset="chronological hold-out (20 %)", metrics=trained["metrics"], gate=gate)
    if activate and gate:
        ml_registry.ensure_baselines(session)
        ml_registry.activate_version(session, LATE, LATE_VERSION, "beats the base-rate predictor on the hold-out")
    return {"trained": True, "model": ml_registry.view(model), "metrics": trained["metrics"], "activated": bool(activate and gate)}


def late_model(session: Session) -> Optional[ml_core.LogisticRegression]:
    row = ml_registry.active(session, LATE)
    if row is None or ml_registry.is_baseline(LATE, row.version):
        return None
    return ml_core.LogisticRegression.from_dict(row.params["model"])


def refresh_twin_late_delivery(session: Session) -> dict:
    """Replace the seeded ``twin_snapshot.late_delivery_prob`` by the model's probability for a typical order of the supplier
    (its median order value and lead time, the current month) when a trained late-delivery model is ACTIVE."""
    model = late_model(session)
    if model is None:
        return {"updated": 0, "reason": "no trained late-delivery model is active"}
    version = ml_registry.effective_version(session, LATE)
    rows = late_rows(session)
    by_supplier = defaultdict(list)
    for r in rows:
        by_supplier[r["supplier"]].append(r)
    updated = 0
    for twin in session.execute(select(TwinSnapshot)).scalars():
        history = by_supplier.get(str(twin.supplier_id))
        if not history or len(history) < 5:
            continue
        prior = (sum(r["label"] for r in history) + 1) / (len(history) + 2)
        value = median(math.expm1(r["x"][1]) * 100 for r in history)
        lead = median(r["x"][2] for r in history)
        asn = sum(r["x"][5] for r in history) / len(history) >= 0.5
        p = model.predict_proba(late_features(prior, value, lead, clock.today().month, asn))
        twin.late_delivery_prob = Decimal(str(round(min(max(p, 0.0), 0.999), 3)))
        twin.model_version, twin.source = version, "MODEL"
        updated += 1
    session.flush()
    if updated:
        audit.record(session, "ML_MODEL", ml_registry.active(session, LATE).id, "TWIN_LATE_DELIVERY_REFRESHED", object_ref=f"{LATE}@{version}",
                     after={"snapshotsUpdated": updated})
    return {"updated": updated, "version": version}


def late_drift_inputs(session: Session, last: int = 200) -> dict:
    rows = late_rows(session)[-last:]
    return {"features": {n: [r["x"][i] for r in rows] for i, n in enumerate(LATE_FEATURES)}, "rows": rows}


# ================================================================ price trend
def price_history(session: Session, material_number: str) -> list[tuple[str, float]]:
    """Monthly average PO unit price (rupees) of a material, by order month."""
    material = session.execute(select(Material).where(Material.number == material_number)).scalar_one_or_none()
    if material is None:
        return []
    totals = defaultdict(lambda: [0.0, 0.0])
    for qty, price, created in session.execute(select(PoLine.qty, PoLine.unit_price_minor, PurchaseOrder.created_at).join(
            PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(PoLine.material_id == material.id, PurchaseOrder.status != "CANCELLED")).all():
        period = created.strftime("%Y-%m")
        totals[period][0] += float(qty) * price / 100
        totals[period][1] += float(qty)
    return [(p, t[0] / t[1]) for p, t in sorted(totals.items()) if t[1]]


def price_trend(history: list[tuple[str, float]], horizon: int = 3) -> dict:
    """Holt smoothing with damped trend. Direction: RISING / FALLING when the damped trend moves the price by more than 0.5 %
    per period, else STABLE. Needs at least 4 monthly prices."""
    if len(history) < 4:
        return {"model": TREND_VERSION, "available": False, "reason": "at least 4 months of purchase prices are needed", "points": len(history)}
    values = [v for _, v in history]
    fit = ml_core.holt_forecast(values, horizon)
    last = history[-1][0]
    relative = fit["trendPerPeriod"] / values[-1] if values[-1] else 0.0
    direction = "RISING" if relative > 0.005 else "FALLING" if relative < -0.005 else "STABLE"
    return {"model": TREND_VERSION, "available": True, "points": len(history), "direction": direction, "trendPct": round(relative * 100, 3),
            "last": {"period": last, "price": round(values[-1], 2)}, "alpha": fit["alpha"], "beta": fit["beta"],
            "forecast": [{"period": _shift(last, h + 1), "price": round(fit["forecast"][h], 2), "low": round(fit["low"][h], 2),
                          "high": round(fit["high"][h], 2)} for h in range(horizon)]}


def evaluate_price_trend(series: list[list[float]]) -> dict:
    """One-step MAPE of the trend model against 'last price' over rolling origins."""
    base, model = [], []
    for values in series:
        for i in range(6, len(values)):
            fit = ml_core.holt_forecast(values[:i], 1)
            actual = values[i]
            if actual:
                base.append(abs(values[i - 1] - actual) / actual)
                model.append(abs(fit["forecast"][0] - actual) / actual)
    n = len(base)
    return {"points": n, "mapeLastPrice": _round(sum(base) / n) if n else None, "mape": _round(sum(model) / n) if n else None}


# ================================================================ invoice exception cause
def _bucket(value: float) -> str:
    v = abs(value)
    return "0" if v == 0 else "<1" if v < 1 else "<5" if v < 5 else "<20" if v < 20 else ">=20"


def exception_tokens(exc_type: str, delta: dict, channel: Optional[str], match_type: Optional[str], has_po: bool, supplier: Optional[str]) -> list[str]:
    tokens = [f"type={exc_type}", f"channel={channel or '-'}", f"match={match_type or '-'}", f"po={'Y' if has_po else 'N'}"]
    if supplier:
        tokens.append(f"supplier={supplier}")
    for key, value in sorted((delta or {}).items()):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            tokens.append(f"{key}={_bucket(value)}")
        elif isinstance(value, str) and len(value) <= 20:
            tokens.append(f"{key}={value}")
    return tokens


def exception_rows(session: Session) -> list[dict]:
    rows = []
    query = (select(InvoiceException, Invoice, Supplier.code).join(Invoice, Invoice.id == InvoiceException.invoice_id)
             .join(Supplier, Supplier.id == Invoice.supplier_id).where(InvoiceException.status == "RESOLVED", InvoiceException.resolution.is_not(None))
             .order_by(InvoiceException.created_at))
    for exc, invoice, code in session.execute(query).all():
        rows.append({"tokens": exception_tokens(exc.type, exc.delta, invoice.channel, invoice.match_type, invoice.po_id is not None, code),
                     "label": exc.resolution, "type": exc.type})
    return rows


def train_cause_from_rows(rows: list[dict]) -> dict:
    cut = int(len(rows) * 0.8) or 1
    train, test = rows[:cut], rows[cut:] or rows[:cut]
    model = ml_core.NaiveBayes(alpha=1.0).fit([r["tokens"] for r in train], [r["label"] for r in train])
    predicted = [model.predict(r["tokens"])[0] for r in test]
    majority = defaultdict(lambda: defaultdict(int))
    for r in train:
        majority[r["type"]][r["label"]] += 1
    rule = [max(sorted(majority[r["type"]]), key=lambda k: majority[r["type"]][k]) if majority.get(r["type"]) else train[0]["label"] for r in test]
    truth = [r["label"] for r in test]
    metrics = {"rows": len(rows), "test": len(test), "classes": len(model.classes), "accuracy": _round(ml_core.accuracy(truth, predicted)),
               "accuracyByTypeRule": _round(ml_core.accuracy(truth, rule))}
    return {"model": model, "metrics": metrics}


def train_exception_cause(session: Session, activate: bool = True, rows: Optional[list] = None) -> dict:
    rows = rows if rows is not None else exception_rows(session)
    if len(rows) < 30 or len({r["label"] for r in rows}) < 2:
        return {"trained": False, "reason": f"not enough resolved exceptions ({len(rows)}; need 30 with at least two outcomes)", "rows": len(rows)}
    trained = train_cause_from_rows(rows)
    model = ml_registry.register(
        session, code=CAUSE, version=CAUSE_VERSION, kind="NAIVE_BAYES", params={"model": trained["model"].to_dict()}, metrics={"test": trained["metrics"]},
        training={"rows": len(rows), "dataHash": _hash(rows), "label": "resolution of the exception"},
        description="Naive Bayes over exception type, variance buckets, channel and supplier")
    gate = trained["metrics"]["accuracy"] is not None and trained["metrics"]["accuracy"] >= (trained["metrics"]["accuracyByTypeRule"] or 0)
    ml_registry.record_eval(session, code=CAUSE, version=CAUSE_VERSION, dataset="chronological hold-out (20 %)", metrics=trained["metrics"], gate=gate)
    if activate and gate:
        ml_registry.ensure_baselines(session)
        ml_registry.activate_version(session, CAUSE, CAUSE_VERSION, "at least as accurate as the by-type rule")
    return {"trained": True, "model": ml_registry.view(model), "metrics": trained["metrics"], "activated": bool(activate and gate)}


def classify_exception(session: Session, exc: InvoiceException) -> dict:
    """Most likely resolution for an exception; the by-type rule (the stored suggested action) when no model is active."""
    row = ml_registry.active(session, CAUSE)
    if row is None or ml_registry.is_baseline(CAUSE, row.version):
        return {"cause": None, "confidence": None, "model": ml_registry.effective_version(session, CAUSE), "suggestedAction": exc.suggested_action}
    invoice = session.get(Invoice, exc.invoice_id)
    supplier = session.get(Supplier, invoice.supplier_id)
    tokens = exception_tokens(exc.type, exc.delta, invoice.channel, invoice.match_type, invoice.po_id is not None, supplier.code)
    nb = ml_core.NaiveBayes.from_dict(row.params["model"])
    proba = nb.predict_proba(tokens)
    ranked = sorted(proba.items(), key=lambda kv: -kv[1])
    return {"cause": ranked[0][0], "confidence": round(ranked[0][1], 3), "model": row.version, "suggestedAction": exc.suggested_action,
            "alternatives": [{"cause": c, "probability": round(p, 3)} for c, p in ranked[1:3]]}


# ================================================================ supplier duplicate scoring (embedding stand-in)
DEDUP_COSINE = 0.80
DEDUP_REVIEW = 0.70


def duplicate_score(name_a: str, name_b: str, *, pan_a: Optional[str] = None, pan_b: Optional[str] = None,
                    gstin_a: Optional[str] = None, gstin_b: Optional[str] = None) -> dict:
    """Same-entity score for two supplier masters. Rules first (same GSTIN or PAN = the same legal entity; two different PANs
    = different legal entities), then the character n-gram hashing embedding (cosine) blended with the normalised-name ratio.
    ``decision`` is DUPLICATE, REVIEW (to a steward) or DISTINCT."""
    pan_a, pan_b = (pan_a or "").upper() or None, (pan_b or "").upper() or None
    if gstin_a and gstin_b and gstin_a.upper() == gstin_b.upper():
        return {"score": 1.0, "decision": "DUPLICATE", "reasons": ["same GSTIN"], "cosine": None, "ratio": None, "model": DEDUP_VERSION}
    if pan_a and pan_b and pan_a == pan_b:
        return {"score": 1.0, "decision": "DUPLICATE", "reasons": ["same PAN (same legal entity)"], "cosine": None, "ratio": None, "model": DEDUP_VERSION}
    cosine = ml_core.cosine(ml_core.hash_vector(name_a), ml_core.hash_vector(name_b))
    ratio = difflib.SequenceMatcher(None, ml_core.normalise_text(name_a), ml_core.normalise_text(name_b)).ratio()
    score = round(0.6 * cosine + 0.4 * ratio, 4)
    if pan_a and pan_b:   # both known and different
        return {"score": score, "decision": "DISTINCT", "reasons": [f"different PAN ({'similar' if score >= DEDUP_REVIEW else 'dissimilar'} names)"],
                "cosine": round(cosine, 4), "ratio": round(ratio, 4), "model": DEDUP_VERSION}
    decision = "DUPLICATE" if score >= DEDUP_COSINE else "REVIEW" if score >= DEDUP_REVIEW else "DISTINCT"
    return {"score": score, "decision": decision, "reasons": [f"name similarity {score:.2f} (embedding cosine {cosine:.2f}, ratio {ratio:.2f})"],
            "cosine": round(cosine, 4), "ratio": round(ratio, 4), "model": DEDUP_VERSION}


# ================================================================ parametric should-cost
# Defaults are structural (which cost elements exist), never market prices: rates are inputs that the category team supplies
# and that calibration scales against the tenant's own ERP price history.
COMMODITIES = {
    "FORGING": {
        "name": "Hot / warm forging (closed die)",
        "required": ["net_weight_kg", "billet_rate_per_kg", "yield_pct", "press_min", "press_rate_per_min", "overhead_margin_pct"],
        "optional": ["machining_min", "machine_rate_per_min", "die_amortisation", "heat_treatment", "packaging"],
    },
    "PLASTIC_MOULDING": {
        "name": "Plastic injection moulding",
        "required": ["shot_weight_kg", "resin_rate_per_kg", "cavities", "cycle_time_s", "machine_rate_per_hour", "overhead_margin_pct"],
        "optional": ["scrap_pct", "tooling_amortisation", "packaging", "insert_cost"],
    },
}


def _d(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def should_cost_elements(commodity: str, p: dict) -> dict:
    """Cost elements in rupees per piece before overhead and margin."""
    spec = COMMODITIES.get(commodity)
    if spec is None:
        raise ValueError(f"unknown commodity {commodity}; known: {', '.join(COMMODITIES)}")
    missing = [k for k in spec["required"] if p.get(k) in (None, "")]
    if missing:
        raise ValueError(f"missing parameter(s): {', '.join(missing)}")
    if commodity == "FORGING":
        yield_pct = _d(p["yield_pct"])
        if not 0 < yield_pct <= 100:
            raise ValueError("yield_pct must be between 0 and 100")
        material = _d(p["net_weight_kg"]) / (yield_pct / 100) * _d(p["billet_rate_per_kg"])
        conversion = _d(p["press_min"]) * _d(p["press_rate_per_min"]) + _d(p.get("machining_min")) * _d(p.get("machine_rate_per_min"))
        other = _d(p.get("die_amortisation")) + _d(p.get("heat_treatment")) + _d(p.get("packaging"))
    else:
        cavities = _d(p["cavities"])
        if cavities < 1:
            raise ValueError("cavities must be at least 1")
        scrap = 1 + _d(p.get("scrap_pct")) / 100
        material = _d(p["shot_weight_kg"]) / cavities * _d(p["resin_rate_per_kg"]) * scrap
        conversion = _d(p["cycle_time_s"]) / 3600 * _d(p["machine_rate_per_hour"]) / cavities
        other = _d(p.get("tooling_amortisation")) + _d(p.get("packaging")) + _d(p.get("insert_cost"))
    return {"material": material, "conversion": conversion, "other": other}


def should_cost(commodity: str, p: dict, calibration: Optional[dict] = None) -> dict:
    e = should_cost_elements(commodity, p)
    subtotal = e["material"] + e["conversion"] + e["other"]
    uncalibrated = subtotal * (1 + _d(p["overhead_margin_pct"]) / 100)
    cal = calibration or {}
    coefficients = cal.get("coefficients")
    if coefficients:
        total = max(coefficients[0] + coefficients[1] * e["material"] + coefficients[2] * e["conversion"] + coefficients[3] * e["other"], 0.0)
        total *= 1 + _d(p["overhead_margin_pct"]) / 100
    else:
        total = uncalibrated * _d(cal.get("scale"), 1.0)
    total = Decimal(str(total)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return {"model": cal.get("version") or f"{commodity.lower()}-param-v1", "commodity": commodity,
            "material": round(e["material"], 2), "conversion": round(e["conversion"], 2), "other": round(e["other"], 2),
            "subtotal": round(subtotal, 2), "overheadMarginPct": _d(p["overhead_margin_pct"]), "unitCost": str(total),
            "unitCostMinor": int(total * 100), "calibrated": bool(cal)}


def calibrate_should_cost(commodity: str, samples: list[dict]) -> dict:
    """Calibrate the parametric model on ERP price history. ``samples`` = [{"params": {...}, "priceMinor": int}]. With fewer than
    8 samples one scale factor (median of actual / formula); with 8 or more a ridge regression of the price on the three cost
    elements. Reports the error before and after, on the same samples."""
    prepared = []
    for s in samples:
        try:
            e = should_cost_elements(commodity, s["params"])
        except ValueError:
            continue
        mult = 1 + _d(s["params"]["overhead_margin_pct"]) / 100
        prepared.append((e, mult, s["priceMinor"] / 100))
    if len(prepared) < 3:
        raise ValueError(f"at least 3 priced samples are needed to calibrate {commodity} ({len(prepared)} usable)")
    raw = [(e["material"] + e["conversion"] + e["other"]) * m for e, m, _ in prepared]
    actual = [a for _, _, a in prepared]
    before = ml_core.mape(actual, raw)
    scale = median(a / r for a, r in zip(actual, raw) if r)
    calibration = {"scale": scale, "samples": len(prepared), "version": f"{commodity.lower()}-param-v2", "mapeBefore": _round(before)}
    predicted = [r * scale for r in raw]
    if len(prepared) >= 8:
        # the regression explains the pre-overhead price (actual / overhead factor); should_cost() multiplies the overhead back
        X = [[e["material"], e["conversion"], e["other"]] for e, m, _ in prepared]
        coefficients = ml_core.ridge_fit(X, [a / m for (_, m, _), a in zip(prepared, actual)], l2=1e-4)
        fitted = [max(coefficients[0] + coefficients[1] * x[0] + coefficients[2] * x[1] + coefficients[3] * x[2], 0.0) * m
                  for x, (_, m, _) in zip(X, prepared)]
        error_fit = ml_core.mape(actual, fitted)
        if error_fit is not None and error_fit < (ml_core.mape(actual, predicted) or 9):
            calibration["coefficients"] = list(coefficients)
            predicted = fitted
    calibration["mapeAfter"] = _round(ml_core.mape(actual, predicted))
    return calibration


def should_cost_samples(session: Session, commodity: str) -> list[dict]:
    """Priced samples from the tenant: materials whose attributes carry ``shouldCost = {commodity, params}`` and a price (the
    average purchase price from PO lines, else the standard price)."""
    out = []
    for m in session.execute(select(Material)).scalars():
        sc = (m.attributes or {}).get("shouldCost")
        if not isinstance(sc, dict) or sc.get("commodity") != commodity:
            continue
        prices = session.execute(select(PoLine.unit_price_minor).where(PoLine.material_id == m.id)).scalars().all()
        price = int(sum(prices) / len(prices)) if prices else m.standard_price_minor
        if price:
            out.append({"material": m.number, "params": sc.get("params") or {}, "priceMinor": price})
    return out


def train_should_cost(session: Session, commodity: str, samples: Optional[list] = None, activate: bool = True) -> dict:
    samples = samples if samples is not None else should_cost_samples(session, commodity)
    try:
        calibration = calibrate_should_cost(commodity, samples)
    except ValueError as exc:
        return {"trained": False, "reason": str(exc), "samples": len(samples)}
    code = f"should_cost_{commodity.lower()}"
    version = calibration["version"]
    model = ml_registry.register(session, code=code, version=version, kind="PARAMETRIC", params={"commodity": commodity, "calibration": calibration},
                                 metrics={"calibration": {k: calibration.get(k) for k in ("samples", "mapeBefore", "mapeAfter")}},
                                 training={"samples": len(samples), "dataHash": _hash(samples)}, description=COMMODITIES[commodity]["name"] + " parametric should-cost")
    gate = calibration["mapeAfter"] is not None and (calibration["mapeBefore"] is None or calibration["mapeAfter"] <= calibration["mapeBefore"])
    ml_registry.record_eval(session, code=code, version=version, dataset="ERP price history", metrics=model.metrics["calibration"], gate=gate)
    if activate and gate:
        ml_registry.activate_version(session, code, version, "calibration does not worsen the error")
    return {"trained": True, "model": ml_registry.view(model), "calibration": calibration, "activated": bool(activate and gate)}


def active_calibration(session: Session, commodity: str) -> Optional[dict]:
    row = ml_registry.active(session, f"should_cost_{commodity.lower()}")
    return row.params.get("calibration") if row is not None else None
