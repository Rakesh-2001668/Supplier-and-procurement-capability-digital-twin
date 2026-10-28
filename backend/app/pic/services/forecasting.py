"""M02 demand forecast review (MRP-04) and the Demand Sensing Agent.

Statistical forecasts come from consumption (goods issues, or the consumption history loaded from the ERP).
A planner's override needs a reason; released forecasts become FORECAST demand elements, so the next
net-change MRP run picks them up. Statistical forecasts never reach MRP without a release.
"""
import uuid
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import DemandElement, Forecast, Material, StockMovement
from app.pic.platform import agents, audit, clock, rules
from app.pic.platform.errors import Problem
from app.pic.platform.money import D
from app.pic.services.common import principal

ISSUE_MOVEMENTS = ("201", "261", "221", "601")
MODEL_VERSION = "demand-es-v1"


def _period(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _shift(period: str, months: int) -> str:
    y, m = int(period[:4]), int(period[5:]) + months
    while m > 12:
        y, m = y + 1, m - 12
    while m < 1:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}"


def _consumption(session: Session, material_id: uuid.UUID, plant: str) -> dict[str, Decimal]:
    out: dict[str, Decimal] = defaultdict(Decimal)
    for qty, created in session.execute(select(StockMovement.qty, StockMovement.created_at).where(
            StockMovement.material_id == material_id, StockMovement.plant == plant, StockMovement.movement_type.in_(ISSUE_MOVEMENTS))).all():
        out[_period(created.date())] += abs(qty)
    return out


def generate(session: Session, horizon: int = 3) -> list[Forecast]:
    """Refresh actuals and the statistical forecast for the next `horizon` periods (exponential smoothing, α 0.3)."""
    alpha = Decimal(str(rules.resolve(session, "DEMAND-SENSING").body["alpha"]))
    current = _period(clock.today())
    created = []
    materials = session.execute(select(Material).where(Material.type == "STOCK", Material.status == "ACTIVE")).scalars().all()
    for material in materials:
        plants = {p for p in session.execute(select(StockMovement.plant).where(StockMovement.material_id == material.id).distinct()).scalars()} \
            | {p for p in session.execute(select(Forecast.plant).where(Forecast.material_id == material.id).distinct()).scalars()}
        for plant in sorted(plants):
            rows = {f.period: f for f in session.execute(select(Forecast).where(Forecast.material_id == material.id, Forecast.plant == plant)).scalars()}
            for period, qty in _consumption(session, material.id, plant).items():
                f = rows.get(period)
                if f is not None and f.actual_source != "ERP_CONSUMPTION_HISTORY":
                    f.actual_qty, f.actual_source = qty, "GOODS_ISSUES"
            actuals = sorted((p, f.actual_qty) for p, f in rows.items() if f.actual_qty is not None and p < current)
            consumption = _consumption(session, material.id, plant)
            for period, qty in consumption.items():
                if period < current and period not in rows:
                    actuals.append((period, qty))
            actuals.sort()
            if len(actuals) < 2:
                continue
            level = actuals[0][1]
            for _, qty in actuals[1:]:
                level = alpha * qty + (1 - alpha) * level
            level = level.quantize(Decimal("1"), ROUND_HALF_UP)
            for h in range(0, horizon):
                period = _shift(current, h)
                f = rows.get(period)
                if f is None:
                    f = Forecast(tenant_id=material.tenant_id, material_id=material.id, plant=plant, period=period, method="EXP_SMOOTHING",
                                 statistical_qty=level, model_version=MODEL_VERSION, created_by=principal(session).user_id)
                    session.add(f)
                    rows[period] = f
                    created.append(f)
                elif f.override_qty is None:
                    f.statistical_qty, f.method, f.model_version = level, "EXP_SMOOTHING", MODEL_VERSION
            session.flush()
    return created


def _effective(f: Forecast) -> Decimal:
    return f.override_qty if f.override_qty is not None else f.statistical_qty


def metrics(rows: list[Forecast], periods: int = 3) -> dict:
    done = [f for f in sorted(rows, key=lambda f: f.period) if f.actual_qty is not None][-periods:]
    actual = sum((f.actual_qty for f in done), Decimal(0))
    if not done or not actual:
        return {"bias": None, "mape": None, "periods": len(done)}
    bias = sum((_effective(f) - f.actual_qty for f in done), Decimal(0)) / actual
    mape = sum((abs(_effective(f) - f.actual_qty) / f.actual_qty for f in done if f.actual_qty), Decimal(0)) / len(done)
    return {"bias": bias.quantize(Decimal("0.001")), "mape": mape.quantize(Decimal("0.001")), "periods": len(done)}


def sense(session: Session) -> list:
    """Demand Sensing Agent (L1): proposes an override when bias over the last three periods exceeds the threshold."""
    body = rules.resolve(session, "DEMAND-SENSING").body
    threshold = Decimal(str(body["biasThreshold"]))
    current = _period(clock.today())
    by_key = defaultdict(list)
    for f in session.execute(select(Forecast)).scalars():
        by_key[(f.material_id, f.plant)].append(f)
    out = []
    for (material_id, plant), rows in by_key.items():
        m = metrics(rows)
        upcoming = next((f for f in sorted(rows, key=lambda f: f.period) if f.period >= current and f.override_qty is None), None)
        if m["bias"] is None or abs(m["bias"]) < threshold or upcoming is None:
            continue
        material = session.get(Material, material_id)
        proposed = (upcoming.statistical_qty / (1 + m["bias"])).quantize(Decimal("1"), ROUND_HALF_UP)
        direction = "over" if m["bias"] > 0 else "under"
        rec = agents.recommend(
            session, "DEMAND_SENSING", object_type="MATERIAL", object_id=material.id, object_ref=material.number,
            dedup_key=f"{material.number}:{plant}:{upcoming.period}",
            title=f"{material.number}: forecast {direction}-states demand by {abs(m['bias']) * 100:.0f}%",
            rationale=(f"Over the last {m['periods']} periods the forecast {direction}-stated consumption by {abs(m['bias']) * 100:.1f}% "
                       f"(MAPE {m['mape'] * 100:.1f}%). Proposed {upcoming.period} quantity {proposed} instead of {upcoming.statistical_qty}."),
            proposal={"material": material.number, "plant": plant, "period": upcoming.period, "statisticalQty": str(upcoming.statistical_qty),
                      "proposedQty": str(proposed), "bias": str(m["bias"])},
            candidate_role="MRP_CONTROLLER", deep_link=f"/pic/mrp/forecast?material={material.number}",
            value_at_risk_minor=int(abs(upcoming.statistical_qty - proposed) * (material.standard_price_minor or 0)),
            evidence=[f.period for f in rows if f.actual_qty is not None][-3:], confidence=0.8)
        if rec is not None:
            out.append(rec)
    return out


def override(session: Session, f: Forecast, qty: Decimal, reason: str, release: bool = True) -> Forecast:
    p = principal(session)
    if "MRP_CONTROLLER" not in p.roles:
        raise Problem(403, "FORBIDDEN", "Forecast overrides are made by the MRP controller", rule_ref="MRP-04")
    if not reason or len(reason.strip()) < 5:
        raise Problem(422, "REASON_REQUIRED", "A forecast override needs a reason", rule_ref="MRP-04")
    if f.period < _period(clock.today()):
        raise Problem(409, "PERIOD_CLOSED", f"{f.period} is in the past; only current and future periods can be overridden")
    before = {"statistical": f.statistical_qty, "override": f.override_qty}
    f.override_qty, f.override_reason, f.override_by = D(qty), reason, p.user_id
    material = session.get(Material, f.material_id)
    audit.record(session, "MATERIAL", material.id, "FORECAST_OVERRIDDEN", object_ref=material.number, before=before,
                 after={"period": f.period, "override": f.override_qty}, reason=reason)
    if release:
        release_period(session, f)
    return f


def release_period(session: Session, f: Forecast) -> DemandElement:
    """Write the effective forecast as a FORECAST demand element for net-change MRP."""
    reference = f"FC-{f.period}"
    element = session.execute(select(DemandElement).where(DemandElement.material_id == f.material_id, DemandElement.plant == f.plant,
                                                          DemandElement.type == "FORECAST", DemandElement.reference == reference)).scalar_one_or_none()
    qty = _effective(f)
    need = date(int(f.period[:4]), int(f.period[5:]), 15)
    if element is None:
        element = DemandElement(tenant_id=f.tenant_id, material_id=f.material_id, plant=f.plant, type="FORECAST", reference=reference,
                                req_date=need, qty=qty, changed_at=clock.now(), created_by=principal(session).user_id)
        session.add(element)
    else:
        element.qty, element.changed_at = qty, clock.now()
    session.flush()
    return element


def review(session: Session, material: Optional[str] = None) -> list[dict]:
    query = select(Forecast, Material).join(Material, Material.id == Forecast.material_id)
    if material:
        query = query.where(Material.number == material)
    by_key = defaultdict(list)
    names = {}
    for f, m in session.execute(query.order_by(Material.number, Forecast.period)).all():
        by_key[(m.number, f.plant)].append(f)
        names[m.number] = (m.description, m.base_uom)
    released = {(e.material_id, e.plant, e.reference) for e in session.execute(select(DemandElement).where(DemandElement.type == "FORECAST")).scalars()}
    out = []
    for (number, plant), rows in by_key.items():
        out.append({"material": number, "description": names[number][0], "uom": names[number][1], "plant": plant, **{("metricPeriods" if k == "periods" else k): (str(v) if v is not None else None) for k, v in metrics(rows).items()},
                    "periods": [{"id": str(f.id), "period": f.period, "method": f.method, "statisticalQty": str(f.statistical_qty),
                                 "overrideQty": str(f.override_qty) if f.override_qty is not None else None, "overrideReason": f.override_reason,
                                 "effectiveQty": str(_effective(f)), "actualQty": str(f.actual_qty) if f.actual_qty is not None else None,
                                 "actualSource": f.actual_source, "released": (f.material_id, f.plant, f"FC-{f.period}") in released}
                                for f in rows]})
    return out
