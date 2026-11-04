"""M05 should-cost models and price benchmarks (Technical Document 12.4 should-cost, Blueprint M05 "should-cost and price benchmarks").

A should-cost model is data (``should_cost_model.spec``), not code: cost components of a commodity, a margin, and the link of material rates to a
published index (``index_value``), so the same model gives a new should-cost every time the index moves.

    spec = {"unit": "EA",
            "inputs": [{"code": "net_weight_kg", "label": "Net weight", "unit": "kg"}, ...],
            "components": [
                {"code": "MATERIAL", "type": "QTY_RATE", "qty": "net_weight_kg", "rate": "alloy_rate_per_kg", "yieldLossPct": "4",
                 "index": {"code": "LME_AL", "baseDate": "2026-04-01"}},          # rate x index(on) / index(baseDate)
                {"code": "CONVERSION", "type": "TIME_RATE", "minutes": "cycle_time_min", "rate": "machine_rate_per_min"},
                {"code": "TOOLING", "type": "FIXED", "amount": "tooling_amortisation"},
                {"code": "LOGISTICS", "type": "PCT_OF", "of": ["MATERIAL", "CONVERSION"], "pct": "2"}],
            "marginPct": "overhead_margin_pct"}       # an input code or a number: overhead and profit on the subtotal

    unit cost = subtotal x (1 + margin / 100); subtotal = sum of the components. QTY_RATE = qty x (1 + yield loss) x rate x index factor;
    TIME_RATE = minutes x rate per minute; FIXED = amount; PCT_OF = pct of the named components. Every figure is in rupees per unit.

Baselines (the reference an award's negotiated saving is measured against; the method is recorded on the event and on the savings initiative):
    LAST_PRICE    the purchasing info record's last price          WEIGHTED_AVG   quantity-weighted price of the last 12 months of orders
    SHOULD_COST   the event's should-cost                          MARKET_INDEX   the latest market benchmark of the material or category
    BUDGET, MANUAL   given by the buyer (nothing is derived)
"""
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.models import IndexValue, InfoRecord, Material, PoLine, PriceBenchmark, PurchaseOrder, ShouldCostModel
from app.pic.platform import audit, clock
from app.pic.platform.errors import Problem, not_found
from app.pic.platform.money import D

TYPES = ("QTY_RATE", "TIME_RATE", "FIXED", "PCT_OF")
CENT = Decimal("0.01")


def invalid(detail: str) -> Problem:
    return Problem(422, "SHOULDCOST_INVALID", detail, rule_ref="SRC-SHOULDCOST")


# ---------------------------------------------------------------- the original parametric die-casting model
def parametric(params: dict) -> dict:
    """Parametric should-cost by commodity (die-casting): material + conversion + tooling + packaging, then margin. Inputs are validated: a
    missing key, a non-numeric or negative figure, or a margin outside 0..100 % is refused (a negative margin would price below cost)."""
    try:
        material = _num(params["net_weight_kg"], "net_weight_kg") * _num(params["alloy_rate_per_kg"], "alloy_rate_per_kg")
        conversion = _num(params["cycle_time_min"], "cycle_time_min") * _num(params["machine_rate_per_min"], "machine_rate_per_min")
        tooling = _num(params.get("tooling_amortisation", 0), "tooling_amortisation")
        packaging = _num(params.get("packaging", 0), "packaging")
        margin = _num(params["overhead_margin_pct"], "overhead_margin_pct")
    except KeyError as exc:
        raise invalid(f"should-cost input {exc.args[0]} is missing")
    if margin > 100:
        raise invalid("overhead_margin_pct must be between 0 and 100")
    subtotal = material + conversion + tooling + packaging
    total = (subtotal * (1 + margin / 100)).quantize(CENT, ROUND_HALF_UP)
    return {"model": params.get("model", "diecast-param-v1"), "material": str(material), "conversion": str(conversion),
            "tooling": str(tooling), "packaging": str(packaging), "subtotal": str(subtotal), "overheadMarginPct": str(margin),
            "unitCost": str(total), "unitCostMinor": int(total * 100)}


def _num(value, name: str) -> Decimal:
    try:
        number = D(value)
    except Exception:  # noqa: BLE001
        raise invalid(f"should-cost input {name} is not a number")
    if not number.is_finite() or number < 0:
        raise invalid(f"should-cost input {name} must be zero or positive")
    return number


# ---------------------------------------------------------------- index
def index_on(session: Session, code: str, on: date) -> tuple[Decimal, date]:
    row = session.execute(select(IndexValue).where(IndexValue.index_code == code, IndexValue.as_of <= on)
                          .order_by(IndexValue.as_of.desc()).limit(1)).scalar_one_or_none()
    if row is None:
        raise invalid(f"no value of index {code} on or before {on.isoformat()}")
    return Decimal(row.value), row.as_of


# ---------------------------------------------------------------- generic model
def validate_spec(spec: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(spec, dict) or not isinstance(spec.get("components"), list) or not spec["components"]:
        return ["spec needs a list of components"]
    inputs = {i.get("code") for i in spec.get("inputs") or [] if isinstance(i, dict)}
    codes: list[str] = []
    for c in spec["components"]:
        code = c.get("code") if isinstance(c, dict) else None
        if not code or code in codes:
            errors.append(f"component code {code!r} is missing or used twice")
            continue
        if c.get("type") not in TYPES:
            errors.append(f"{code}: type must be one of {', '.join(TYPES)}")
        needed = {"QTY_RATE": ("qty", "rate"), "TIME_RATE": ("minutes", "rate"), "FIXED": ("amount",), "PCT_OF": ("of", "pct")}.get(c.get("type"), ())
        for key in needed:
            if c.get(key) in (None, "", []):
                errors.append(f"{code}: {key} is required for {c.get('type')}")
        if c.get("type") == "PCT_OF":
            for ref in c.get("of") or []:
                if ref not in codes:
                    errors.append(f"{code}: PCT_OF refers to {ref}, which must be an earlier component")
        if c.get("index") and not c["index"].get("code"):
            errors.append(f"{code}: index needs a code")
        codes.append(code)
    if "marginPct" not in spec:
        errors.append("spec needs marginPct (an input code or a number)")
    for key in ("qty", "rate", "minutes", "amount", "pct"):
        for c in spec["components"]:
            ref = c.get(key) if isinstance(c, dict) else None
            if isinstance(ref, str) and not _is_number(ref) and inputs and ref not in inputs:
                errors.append(f"{c.get('code')}: {key} refers to input {ref}, which the spec does not declare")
    return errors


def _is_number(text: str) -> bool:
    try:
        Decimal(text)
        return True
    except Exception:  # noqa: BLE001
        return False


def _value(ref, values: dict, name: str) -> Decimal:
    if isinstance(ref, (int, float, Decimal)):
        return _num(ref, name)
    if isinstance(ref, str) and ref in values:
        return _num(values[ref], ref)
    if isinstance(ref, str) and _is_number(ref):
        return _num(ref, name)
    raise invalid(f"input {ref!r} for {name} is missing")


def evaluate_spec(session: Session, spec: dict, inputs: dict, on: date, *, code: str = "ad hoc", version: int = 1) -> dict:
    problems = validate_spec(spec)
    if problems:
        raise invalid("; ".join(problems))
    values = {k: v for k, v in (inputs or {}).items()}
    amounts: dict[str, Decimal] = {}
    detail, links = [], []
    for c in spec["components"]:
        kind = c["type"]
        if kind == "QTY_RATE":
            qty, rate = _value(c["qty"], values, "qty"), _value(c["rate"], values, "rate")
            loss = _num(c.get("yieldLossPct", 0), "yieldLossPct")
            factor = Decimal(1)
            if c.get("index"):
                now_value, now_date = index_on(session, c["index"]["code"], on)
                base_date = date.fromisoformat(str(c["index"]["baseDate"])) if c["index"].get("baseDate") else on
                base_value, base_as_of = index_on(session, c["index"]["code"], base_date)
                factor = now_value / base_value
                links.append({"component": c["code"], "index": c["index"]["code"], "base": str(base_value), "baseAsOf": base_as_of.isoformat(),
                              "current": str(now_value), "currentAsOf": now_date.isoformat(), "factor": str(factor.quantize(Decimal("0.000001")))})
            amount = qty * (1 + loss / 100) * rate * factor
            formula = f"{qty} x (1 + {loss}%) x {rate}" + (f" x index {factor.quantize(Decimal('0.0001'))}" if c.get("index") else "")
        elif kind == "TIME_RATE":
            amount = _value(c["minutes"], values, "minutes") * _value(c["rate"], values, "rate")
            formula = f"{_value(c['minutes'], values, 'minutes')} min x {_value(c['rate'], values, 'rate')}"
        elif kind == "FIXED":
            amount = _value(c["amount"], values, "amount")
            formula = "fixed amount"
        else:
            base = sum((amounts[ref] for ref in c["of"]), Decimal(0))
            amount = base * _value(c["pct"], values, "pct") / 100
            formula = f"{_value(c['pct'], values, 'pct')}% of {'+'.join(c['of'])}"
        amounts[c["code"]] = amount
        detail.append({"component": c["code"], "label": c.get("label") or c["code"], "amount": str(amount.quantize(Decimal("0.0001"))), "formula": formula})
    margin = _value(spec["marginPct"], values, "marginPct")
    if margin > 100:
        raise invalid("the margin must be between 0 and 100 %")
    subtotal = sum(amounts.values(), Decimal(0))
    unit_cost = (subtotal * (1 + margin / 100)).quantize(CENT, ROUND_HALF_UP)
    out = {"model": f"{code}@{version}", "unit": spec.get("unit", "EA"), "components": detail, "subtotal": str(subtotal.quantize(Decimal("0.0001"))),
           "marginPct": str(margin), "marginMinor": int(((subtotal * margin / 100) * 100).quantize(Decimal(1), ROUND_HALF_UP)),
           "unitCost": str(unit_cost), "unitCostMinor": int(unit_cost * 100), "indexLinks": links, "asOf": on.isoformat(), "inputs": {k: str(v) for k, v in values.items()}}
    # the keys the bid matrix and the original model use
    out["overheadMarginPct"] = out["marginPct"]
    for key in ("material", "conversion", "tooling", "packaging"):
        if key.upper() in amounts:
            out[key] = str(amounts[key.upper()])
    return out


def current_model(session: Session, code: str) -> ShouldCostModel:
    model = session.execute(select(ShouldCostModel).where(ShouldCostModel.code == code, ShouldCostModel.active.is_(True))
                            .order_by(ShouldCostModel.version.desc()).limit(1)).scalar_one_or_none()
    if model is None:
        raise not_found("Should-cost model", code)
    return model


def evaluate(session: Session, code: str, inputs: dict, on: Optional[date] = None) -> dict:
    model = current_model(session, code)
    return evaluate_spec(session, model.spec, inputs, on or clock.today(), code=model.code, version=model.version)


def save_model(session: Session, *, code: str, commodity: str, title: str, spec: dict, index_code: Optional[str] = None, note: Optional[str] = None) -> ShouldCostModel:
    """A new version of a model (never an edit: an event that used version n keeps reading it)."""
    from app.pic.db import current_tenant
    from app.pic.services.common import principal

    problems = validate_spec(spec)
    if problems:
        raise invalid("; ".join(problems))
    last = session.execute(select(func.max(ShouldCostModel.version)).where(ShouldCostModel.code == code)).scalar() or 0
    model = ShouldCostModel(tenant_id=current_tenant(session), code=code, version=last + 1, commodity=commodity, title=title, spec=spec,
                            index_code=index_code, note=note, created_by=principal(session).user_id)
    session.add(model)
    session.flush()
    audit.record(session, "SHOULD_COST_MODEL", model.id, "VERSION_CREATED", object_ref=f"{code}@{model.version}", after={"commodity": commodity, "title": title})
    return model


# ---------------------------------------------------------------- baselines and benchmarks
def _last_price(session: Session, material: Optional[Material], plant: Optional[str]) -> Optional[dict]:
    if material is None:
        return None
    query = select(InfoRecord).where(InfoRecord.material_id == material.id).order_by(InfoRecord.updated_at.desc().nullslast(), InfoRecord.created_at.desc())
    info = session.execute(query).scalars().first()
    return {"priceMinor": info.last_price_minor, "source": "INFO_RECORD", "asOf": (info.updated_at or info.created_at).date().isoformat()} if info else None


def _weighted_average(session: Session, material: Optional[Material], on: date, months: int = 12) -> Optional[dict]:
    if material is None:
        return None
    since = on - timedelta(days=round(months * 30.4375))
    rows = session.execute(select(PoLine.qty, PoLine.unit_price_minor).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(
        PoLine.material_id == material.id, PurchaseOrder.status.notin_(("DRAFT", "CANCELLED")),
        func.date(PurchaseOrder.created_at) >= since, func.date(PurchaseOrder.created_at) <= on, PoLine.qty > 0)).all()
    qty = sum((Decimal(q) for q, _ in rows), Decimal(0))
    if not rows or qty <= 0:
        return None
    value = sum((Decimal(q) * Decimal(p) for q, p in rows), Decimal(0))
    return {"priceMinor": int((value / qty).quantize(Decimal(1), ROUND_HALF_UP)), "source": "PO_LINES", "orderLines": len(rows), "since": since.isoformat()}


def _market(session: Session, material: Optional[Material], category: str, on: date) -> Optional[dict]:
    query = select(PriceBenchmark).where(PriceBenchmark.kind == "MARKET", PriceBenchmark.as_of <= on)
    row = None
    if material is not None:
        row = session.execute(query.where(PriceBenchmark.material_id == material.id).order_by(PriceBenchmark.as_of.desc()).limit(1)).scalar_one_or_none()
    if row is None:
        row = session.execute(query.where(PriceBenchmark.category == category, PriceBenchmark.material_id.is_(None))
                              .order_by(PriceBenchmark.as_of.desc()).limit(1)).scalar_one_or_none()
    return {"priceMinor": row.price_minor, "source": row.source, "asOf": row.as_of.isoformat()} if row else None


def baseline_price(session: Session, method: str, *, material: Optional[Material], plant: Optional[str], category: str,
                   should_cost_minor: Optional[int] = None, on: Optional[date] = None) -> dict:
    """The baseline unit price of a method (``priceMinor`` None when the method derives nothing or has no data) with where it came from."""
    on = on or clock.today()
    found: Optional[dict] = None
    if method == "LAST_PRICE":
        found = _last_price(session, material, plant)
    elif method == "WEIGHTED_AVG":
        found = _weighted_average(session, material, on)
    elif method == "SHOULD_COST":
        found = {"priceMinor": int(should_cost_minor), "source": "SHOULD_COST"} if should_cost_minor else None
    elif method == "MARKET_INDEX":
        found = _market(session, material, category, on)
    if found is None:
        return {"priceMinor": None, "source": "NO_DATA" if method in ("LAST_PRICE", "WEIGHTED_AVG", "SHOULD_COST", "MARKET_INDEX") else "GIVEN_BY_BUYER"}
    return found


def benchmark_band(session: Session, material: Optional[Material], category: str, on: Optional[date] = None, should_cost_minor: Optional[int] = None) -> dict:
    """Every reference price PIC holds for an item and the band they span: where a bid should fall."""
    on = on or clock.today()
    points = {}
    for name, found in (("lastPrice", _last_price(session, material, None)), ("weightedAverage", _weighted_average(session, material, on)),
                        ("market", _market(session, material, category, on))):
        if found:
            points[name] = found
    if should_cost_minor:
        points["shouldCost"] = {"priceMinor": int(should_cost_minor), "source": "SHOULD_COST"}
    peers = session.execute(select(PriceBenchmark).where(PriceBenchmark.kind.in_(("PEER", "CATALOGUE")), PriceBenchmark.as_of <= on,
                                                         PriceBenchmark.category == category)
                            .where((PriceBenchmark.material_id == (material.id if material else None)) | PriceBenchmark.material_id.is_(None))
                            .order_by(PriceBenchmark.as_of.desc()).limit(5)).scalars().all()
    for row in peers:
        points.setdefault(row.kind.lower(), {"priceMinor": row.price_minor, "source": row.source, "asOf": row.as_of.isoformat()})
    prices = sorted(int(v["priceMinor"]) for v in points.values())
    return {"points": points, "lowMinor": prices[0] if prices else None, "highMinor": prices[-1] if prices else None,
            "medianMinor": prices[len(prices) // 2] if prices else None}


# ---------------------------------------------------------------- negotiated savings
def savings_summary(baseline_minor: Optional[int], price_minor: Optional[int], annual_qty: Decimal, method: Optional[str] = None) -> dict:
    """Negotiated saving of an award: (baseline - awarded price) x annual quantity, as a share of the baseline value. A negative result is a
    cost increase and is reported as such (never booked as a saving). Nothing is calculated without a baseline."""
    if not baseline_minor or price_minor is None:
        return {"method": method, "baselineMinor": baseline_minor, "priceMinor": price_minor, "annualSavingsMinor": None, "savingsPct": None, "sign": "NO_BASELINE"}
    amount = int(((Decimal(baseline_minor) - Decimal(price_minor)) * Decimal(annual_qty)).quantize(Decimal(1), ROUND_HALF_UP))
    pct = ((Decimal(baseline_minor) - Decimal(price_minor)) * 100 / Decimal(baseline_minor)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return {"method": method, "baselineMinor": int(baseline_minor), "priceMinor": int(price_minor), "annualSavingsMinor": amount, "savingsPct": str(pct),
            "sign": "SAVING" if amount > 0 else "COST_INCREASE" if amount < 0 else "NEUTRAL"}
