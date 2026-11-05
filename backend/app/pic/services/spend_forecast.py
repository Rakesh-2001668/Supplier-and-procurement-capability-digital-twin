"""Spend forecast (M01, SPD-09): monthly spend by category (and plant) with an 80% band, a documented method and a measured error.

Method (documented here and returned with every series):

* history      monthly posted spend in the group currency from the cube summary, the last 36 complete months, zero-filled; credit notes are
               already netted in their own period. Series with fewer than three months of spend are not forecast.
* candidates   ``HOLT``       Holt linear exponential smoothing (alpha 0.4, beta 0.2), needs 6 months;
               ``SEASONAL``   seasonal naive: the same month a year earlier x the recent year-on-year level ratio (last 3 months over the same 3
                              months a year before, limited to 0.5-2.0), needs 13 months of training;
               ``HOLT_WINTERS`` additive trend and 12-month season (alpha 0.3, beta 0.1, gamma 0.3), needs 24 months of training.
* selection    rolling-origin back-test: for each of the last 6 origins every candidate forecasts the next 1..3 months from the history before
               the origin; the candidate with the lowest MAPE (mean absolute percentage error, months with zero actual left out) is used.
* band         the 80% band of horizon h is the 80th percentile of the absolute back-test errors at horizon h (>= 5 errors), else the normal
               approximation 1.2816 x sigma x sqrt(h) with sigma the standard deviation of the one-step errors. It is symmetric and never negative.
* accuracy     ``snapshot`` stores the forecasts as issued; ``accuracy`` compares them with the actual spend later: MAPE per horizon and the share
               of actuals that fell inside the band (a calibrated 80% band covers about 80%).

Forecasts are restricted to the reader's spend scope like every cube read.
"""
import math
import statistics
from collections import defaultdict
from datetime import date
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.models import SpendCubeSummary, SpendForecastSnapshot
from app.pic.platform import audit, clock
from app.pic.services import spend_cube, spend_scope

FOLDS = 6
BACK_H = 3
Z80 = 1.2816


def _holt(ys: list, h_max: int, alpha: float = 0.4, beta: float = 0.2) -> list:
    level, trend = float(ys[0]), 0.0
    for y in ys[1:]:
        prev = level
        level = alpha * y + (1 - alpha) * (level + trend)
        trend = beta * (level - prev) + (1 - beta) * trend
    return [max(0.0, level + h * trend) for h in range(1, h_max + 1)]


def _seasonal(ys: list, h_max: int) -> list:
    n = len(ys)
    recent, year_ago = sum(ys[-3:]), sum(ys[-15:-12])
    ratio = min(2.0, max(0.5, recent / year_ago)) if year_ago > 0 else 1.0
    return [max(0.0, ys[n - 12 + ((h - 1) % 12)] * ratio) for h in range(1, h_max + 1)]


def _holt_winters(ys: list, h_max: int, alpha: float = 0.3, beta: float = 0.1, gamma: float = 0.3) -> list:
    m = 12
    first, second = ys[:m], ys[m:2 * m]
    level = sum(first) / m
    trend = (sum(second) - sum(first)) / (m * m)
    season = [y - level for y in first]
    for t in range(m, len(ys)):
        y = ys[t]
        s_prev = season[t % m]
        prev_level = level
        level = alpha * (y - s_prev) + (1 - alpha) * (level + trend)
        trend = beta * (level - prev_level) + (1 - beta) * trend
        season[t % m] = gamma * (y - level) + (1 - gamma) * s_prev
    n = len(ys)
    return [max(0.0, level + h * trend + season[(n + h - 1) % m]) for h in range(1, h_max + 1)]


METHODS = {"HOLT": (6, _holt), "SEASONAL": (13, _seasonal), "HOLT_WINTERS": (24, _holt_winters)}


def backtest(ys: list) -> dict:
    """Rolling-origin back-test of every candidate that has enough history: {method: {"mape", "errors": {h: [abs errors]}, "folds"}}."""
    out = {}
    n = len(ys)
    for name, (need, fn) in METHODS.items():
        errors, pct = defaultdict(list), []
        for origin in range(n - FOLDS, n):
            if origin < need:
                continue
            train = ys[:origin]
            forecast = fn(train, BACK_H)
            for h in range(1, BACK_H + 1):
                if origin + h - 1 >= n:
                    continue
                actual = ys[origin + h - 1]
                errors[h].append(abs(actual - forecast[h - 1]))
                if actual > 0:
                    pct.append(abs(actual - forecast[h - 1]) / actual)
        if pct:
            out[name] = {"mape": sum(pct) / len(pct), "errors": dict(errors), "folds": len(errors.get(1, []))}
    return out


def _band(errors: dict, h: int, sigma_fallback: float) -> float:
    pool = errors.get(min(h, BACK_H), [])
    if len(pool) >= 5:
        ordered = sorted(pool)
        k = max(0, min(len(ordered) - 1, math.ceil(0.8 * len(ordered)) - 1))
        base = ordered[k]
        return base * (math.sqrt(h / BACK_H) if h > BACK_H else 1.0)
    return Z80 * sigma_fallback * math.sqrt(h)


def forecast_series(ys: list, h_max: int) -> dict:
    """Best candidate by back-test, its forecasts for 1..h_max with the 80% band, and the back-test error. {} when the series is too thin."""
    if sum(1 for y in ys if y) < 3 or len(ys) < 6:
        return {}
    tests = backtest(ys)
    if tests:
        method = min(tests, key=lambda m: (tests[m]["mape"], list(METHODS).index(m)))
        info = tests[method]
    else:  # not enough history for a back-test: Holt with the normal band from its in-sample one-step errors
        method, info = "HOLT", {"mape": None, "errors": {}, "folds": 0}
    fn = METHODS[method][1]
    mid = fn(ys, h_max)
    ones = info["errors"].get(1) or []
    if not ones:
        residuals = []
        level, trend = float(ys[0]), 0.0
        for y in ys[1:]:
            residuals.append(y - (level + trend))
            prev = level
            level = 0.4 * y + 0.6 * (level + trend)
            trend = 0.2 * (level - prev) + 0.8 * trend
        ones = residuals
    sigma = statistics.pstdev(ones) if len(ones) > 1 else (abs(ones[0]) if ones else 0.0)
    points = [(mid[h - 1], max(0.0, mid[h - 1] - _band(info["errors"], h, sigma)), mid[h - 1] + _band(info["errors"], h, sigma))
              for h in range(1, h_max + 1)]
    return {"method": method, "mape": round(info["mape"] * 100, 1) if info["mape"] is not None else None, "folds": info["folds"],
            "bandMethod": "BACKTEST_P80" if len(info["errors"].get(min(BACK_H, 1), [])) >= 5 else "NORMAL_1.2816_SIGMA",
            "candidates": {m: round(v["mape"] * 100, 1) for m, v in tests.items()}, "points": points}


def _months(period: str, count: int) -> list:
    y, m = int(period[:4]), int(period[5:])
    out = []
    for i in range(1, count + 1):
        index = y * 12 + (m - 1) + i
        out.append(f"{index // 12:04d}-{index % 12 + 1:02d}")
    return out


def history_periods(session: Session, months: int = 36) -> list:
    from app.pic.services import spend
    return spend._window(session, months)


def forecast(session: Session, category: Optional[str] = None, plant: Optional[str] = None, horizon: int = 6) -> dict:
    """SPD-09 forecast by category (optionally one category / plant) for the next ``horizon`` months, with the 80% band."""
    C = SpendCubeSummary
    periods = history_periods(session)
    spend_cube.ensure_fresh(session)
    query = select(C.category, C.period, func.sum(C.amount_group_minor)).where(C.period.in_(periods), *spend_scope.where(session, C))
    if category:
        query = query.where(C.category == category)
    if plant:
        query = query.where(C.plant == plant)
    series = defaultdict(lambda: {p: 0 for p in periods})
    for cat, period, amount in session.execute(query.group_by(C.category, C.period)).all():
        series[cat][period] = int(amount)
    # leading months before a category had any spend are not history
    future = _months(periods[-1], horizon)
    out = []
    for cat, values in sorted(series.items(), key=lambda kv: (-sum(kv[1].values()), kv[0])):
        ys = [values[p] for p in periods]
        first = next((i for i, y in enumerate(ys) if y), len(ys))
        ys = ys[first:]
        result = forecast_series(ys, max(horizon, 12))
        if not result:
            continue
        points = [{"period": p, "actualMinor": values[p]} for p in periods[-12:]]
        for h, p in enumerate(future, start=1):
            mid, low, high = result["points"][h - 1]
            points.append({"period": p, "forecastMinor": int(mid), "lowMinor": int(low), "highMinor": int(high)})
        out.append({"category": cat, "method": result["method"], "methodNote": METHOD_NOTE[result["method"]], "mapePct": result["mape"],
                    "backtestFolds": result["folds"], "bandMethod": result["bandMethod"], "candidatesMapePct": result["candidates"],
                    "next12Minor": int(sum(m for m, _, _ in result["points"][:12])), "points": points})
    return {"history": [periods[0], periods[-1]], "horizon": future, "series": out, "bandLevel": 0.8}


METHOD_NOTE = {
    "HOLT": "Holt linear exponential smoothing (alpha 0.4, beta 0.2)",
    "SEASONAL": "Seasonal naive: same month last year x recent year-on-year level ratio",
    "HOLT_WINTERS": "Holt-Winters additive trend and 12-month season (alpha 0.3, beta 0.1, gamma 0.3)",
}


# ---------------------------------------------------------------- forecasts as issued, and their real error
def snapshot(session: Session, horizon: int = 6, plant: Optional[str] = None) -> dict:
    """Store the current forecast (all categories, 1..horizon months) so it can be judged later. Idempotent per month: a second snapshot in the
    same month for the same category and period replaces the first."""
    data = forecast(session, None, plant, horizon)
    as_of = data["history"][1]
    written = 0
    for item in data["series"]:
        for point in item["points"]:
            if "forecastMinor" not in point:
                continue
            row = session.execute(select(SpendForecastSnapshot).where(
                SpendForecastSnapshot.as_of_period == as_of, SpendForecastSnapshot.category == item["category"],
                SpendForecastSnapshot.plant == (plant or ""), SpendForecastSnapshot.period == point["period"])).scalar_one_or_none()
            h = data["horizon"].index(point["period"]) + 1
            values = dict(horizon=h, method=item["method"], forecast_minor=point["forecastMinor"], low_minor=point["lowMinor"], high_minor=point["highMinor"])
            if row is None:
                session.add(SpendForecastSnapshot(tenant_id=session.info["principal"].tenant_id, as_of_period=as_of, category=item["category"],
                                                  plant=plant or "", period=point["period"], **values))
            else:
                for k, v in values.items():
                    setattr(row, k, v)
            written += 1
    session.flush()
    audit.record(session, "SPEND_FORECAST", spend_cube.current_tenant(session), "SNAPSHOT", object_ref=as_of,
                 after={"asOf": as_of, "rows": written, "series": len(data["series"])})
    return {"asOf": as_of, "rows": written, "series": len(data["series"])}


# A forecast error is only a number worth reading when enough forecasts were judged over enough months: with a handful of points a single small
# actual month (a percentage error has the actual in the denominator) gives hundreds of percent. Below the minimum the accuracy is reported as
# INSUFFICIENT_DATA with the counts it was built on, never as a figure.
MIN_JUDGED = 12      # forecast points (category, month, horizon) compared with an actual
MIN_MONTHS = 3       # distinct months those points fall in


def accuracy(session: Session, category: Optional[str] = None) -> dict:
    """The forecasts that were issued, against the spend that happened: MAPE overall and per horizon, bias, and the share of actuals inside the
    80% band. Only months that are complete in the cube are judged. ``status`` is ``OK`` or ``INSUFFICIENT_DATA`` (fewer than ``MIN_JUDGED``
    judged points or ``MIN_MONTHS`` months: ``mapePct``, ``biasPct`` and ``bandCoveragePct`` are then null and ``reason`` says what is missing);
    ``wapePct`` (the error as a share of the total actual, not of each month) is given whenever anything was judged."""
    C = SpendCubeSummary
    spend_cube.ensure_fresh(session)
    latest = spend_cube.latest_period(session)
    if latest is None:
        return _accuracy_result(0, 0, 0, None, None, None, None, [], [], None)
    from app.pic.services import spend
    last_complete = spend._window(session, 1)[0]
    S = SpendForecastSnapshot
    query = select(S).where(S.period <= last_complete)
    if category:
        query = query.where(S.category == category)
    rows = session.execute(query).scalars().all()
    actual = defaultdict(int)
    for cat, period, amount in session.execute(select(C.category, C.period, func.sum(C.amount_group_minor)).where(
            C.period.between(min((r.period for r in rows), default=latest), last_complete), *spend_scope.where(session, C)).group_by(C.category, C.period)):
        actual[(cat, period)] = int(amount)
    errors, by_h, inside, judged, bias = [], defaultdict(list), 0, 0, []
    per_series = defaultdict(list)
    months, abs_error, total_actual = set(), 0, 0
    for r in rows:
        a = actual.get((r.category, r.period), 0)
        if a <= 0:
            continue
        err = abs(a - r.forecast_minor) / a
        errors.append(err)
        by_h[r.horizon].append(err)
        per_series[r.category].append(err)
        bias.append((r.forecast_minor - a) / a)
        judged += 1
        inside += 1 if r.low_minor <= a <= r.high_minor else 0
        months.add(r.period)
        abs_error += abs(a - r.forecast_minor)
        total_actual += a
    pct = lambda xs: round(sum(xs) / len(xs) * 100, 1) if xs else None
    return _accuracy_result(judged, len(per_series), len(months), pct(errors), pct(bias), round(inside / judged * 100, 1) if judged else None,
                            round(abs_error / total_actual * 100, 1) if total_actual else None,
                            [{"horizon": h, "mapePct": pct(v), "count": len(v)} for h, v in sorted(by_h.items())],
                            sorted(({"category": c, "mapePct": pct(v), "count": len(v)} for c, v in per_series.items()), key=lambda x: (-x["count"], x["category"]))[:40],
                            last_complete)


def _accuracy_result(judged: int, series: int, months: int, mape, bias, coverage, wape, by_horizon: list, per_series: list, last_complete) -> dict:
    missing = []
    if judged < MIN_JUDGED:
        missing.append(f"{judged} of {MIN_JUDGED} forecast points judged")
    if months < MIN_MONTHS:
        missing.append(f"{months} of {MIN_MONTHS} months")
    enough = not missing
    return {"status": "OK" if enough else "INSUFFICIENT_DATA",
            "reason": None if enough else "Not enough forecast history to judge accuracy: " + ", ".join(missing),
            "count": judged, "seriesCount": series, "monthsCount": months, "minimumJudged": MIN_JUDGED, "minimumMonths": MIN_MONTHS,
            "mapePct": mape if enough else None, "biasPct": bias if enough else None, "bandCoveragePct": coverage if enough else None,
            "wapePct": wape, "byHorizon": by_horizon if enough else [], "series": per_series if enough else [], "lastComplete": last_complete}


def plan_projection(session: Session) -> dict:
    """{category: next 12 months in the group currency} by the plain Holt linear projection (alpha 0.4, beta 0.2) on the last 24 complete months: the basis
    of a category plan's budget. It is deliberately NOT the back-tested forecast of ``forecast``: a plan budget must not move because a better method became
    available (the budgets of approved and drafted plans, and every control that reads them, keep their meaning)."""
    from app.pic.services import spend
    C = SpendCubeSummary
    periods = spend._window(session, 24)
    series = defaultdict(lambda: {p: 0 for p in periods})
    for cat, period, amount in session.execute(select(C.category, C.period, func.sum(C.amount_group_minor)).where(
            C.period.in_(periods), *spend_scope.where(session, C)).group_by(C.category, C.period)).all():
        series[cat][period] = int(amount)
    out = {}
    for cat, values in series.items():
        ys = [values[p] for p in periods]
        if sum(1 for y in ys if y) < 3:
            continue
        level, trend, alpha, beta = float(ys[0]), 0.0, 0.4, 0.2
        for y in ys[1:]:
            prev = level
            level = alpha * y + (1 - alpha) * (level + trend)
            trend = beta * (level - prev) + (1 - beta) * trend
        out[cat] = int(max(0.0, sum(level + h * trend for h in range(1, 13))))
    return out
