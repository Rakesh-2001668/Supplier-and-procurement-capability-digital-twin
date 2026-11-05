"""M05 total-cost-of-ownership engine (Technical Document 9.3) with a trace of every component.

    tco = price + freight + duty + packaging + carrying(lead time, safety stock) + quality(ppm x cost of poor quality) - payment-term value

All figures are per base unit of measure, in paise of the event currency (INR), after the bid has been normalised (see ``normalise_price``): the
quoted price converted at the rate valid on the event's reference date, the unit of the price converted to the base unit, GST stripped when it is
creditable. Every component carries its inputs, the formula and a status, so a buyer can see where a number came from and which ones are assumed:

    BID               the supplier quoted it             ESTIMATED       taken from a rule (freight by incoterm, duty by HS rate)
    TWIN / SCORECARD  supplier data PIC holds            RULE_DEFAULT    the rule's default
    INCLUDED          the incoterm says the price covers it                NOT_QUOTED   absent and no incoterm: assumed included, shown
    NOT_APPLICABLE    the component does not apply        MISSING        an input PIC does not have: the TCO is ``incomplete``

An incomplete TCO is never silently zero-filled: the line is flagged, the bid matrix shows it, and an award on it needs the written rationale.
The sum of the rounded components plus ``rounding`` equals the total, so the stack always adds up.

Formulas (r = annual rate, d = days):
    carrying       price x carrying_rate x (lead_time_days + safety_days) / 365, safety_days = safety_stock / (annual_qty / 365), capped
    quality        ppm / 1,000,000 x cost of poor quality per defect
    payment value  price x cost_of_capital x payment_terms_days / 365        (subtracted: paying later is worth money)
    duty (import)  (price + freight) x effective duty % of the HS prefix in the rate table
    freight (EXW, FCA, FAS, FOB, none quoted)   price x the incoterm's estimate %
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import FxRate, Material, Scorecard
from app.pic.platform import sourcing_defaults
from app.pic.platform.money import D
from app.pic.services import supplier as supplier_svc

PARTS = ("price", "freight", "duty", "packaging", "carrying", "quality", "paymentTermValue")
INCOTERMS = ("EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP", "FOR")
LEGACY_KEYS = {"carrying_rate_pct": "carryingRatePct", "cost_of_capital_pct": "costOfCapitalPct", "copq_per_defect_minor": "copqPerDefectMinor"}
SNAPSHOT_VERSION = 2


class TcoInputError(ValueError):
    """A TCO input is missing and the rule says REJECT, or a figure cannot be used (the bid line is refused with this reason)."""


def snapshot(session: Session, overrides: Optional[dict] = None) -> dict:
    """The TCO parameters an event runs on: the tenant's rule SOURCING-TCO with the creator's overrides, frozen in the event."""
    rule = sourcing_defaults.tco_rule(session)
    own = {LEGACY_KEYS.get(k, k): v for k, v in (overrides or {}).items()}
    unknown = sorted(set(own) - set(sourcing_defaults.TCO_DEFAULT))
    if unknown:
        from app.pic.platform.errors import Problem
        raise Problem(422, "INVALID_TCO_PARAMS", f"Unknown TCO parameter(s) {', '.join(unknown)}; allowed: {', '.join(sorted(sourcing_defaults.TCO_DEFAULT))}",
                      rule_ref="SRC-TCO")
    return {**rule.body, **own, "_v": SNAPSHOT_VERSION, "_rule": rule.ref}


def effective(params: dict) -> dict:
    """Parameters of an event. An event made before the TCO rule set existed (no ``_v``) keeps its three rates and the original behaviour
    (no safety stock, twin PPM only), so a running event's numbers never move."""
    params = {LEGACY_KEYS.get(k, k): v for k, v in (params or {}).items()}
    if params.get("_v"):
        return {**sourcing_defaults.TCO_DEFAULT, **params}
    return {**sourcing_defaults.TCO_DEFAULT, **params, "includeSafetyStock": False, "ppmFromScorecardPeriods": 0, "freightEstimatePct": {},
            "dutyRates": {}, "buyerPaysFreightIncoterms": []}


# ---------------------------------------------------------------- normalisation
def fx_rate_on(session: Session, currency: str, on: date) -> tuple[Decimal, date]:
    """INR per unit of ``currency`` valid on ``on`` (the latest rate with valid_from <= on), with the date it applies from."""
    if currency == "INR":
        return Decimal(1), on
    row = session.execute(select(FxRate).where(FxRate.from_ccy == currency, FxRate.to_ccy == "INR", FxRate.valid_from <= on)
                          .order_by(FxRate.valid_from.desc()).limit(1)).scalar_one_or_none()
    if row is None:
        raise TcoInputError(f"no exchange rate {currency}/INR valid on {on.isoformat()}")
    return Decimal(row.rate), row.valid_from


def normalise_price(session: Session, data: dict, on: date, params: dict) -> dict:
    """The quoted unit price of a bid line as INR paise per base unit, ex-tax when GST is creditable, with the steps taken.

    data: unit_price (decimal text, quoted currency and unit), currency, uom_factor (base units in one quoted unit), tax_included, tax_rate_pct."""
    quoted = D(data["unit_price"])
    currency = str(data.get("currency") or "INR").upper()
    factor = D(data.get("uom_factor") or 1)
    if factor <= 0:
        raise TcoInputError("uom_factor must be positive")
    rate, rate_from = fx_rate_on(session, currency, on)
    steps = []
    minor = quoted * 100 * rate
    steps.append({"step": "CURRENCY", "from": currency, "rate": str(rate), "rateFrom": rate_from.isoformat(), "onDate": on.isoformat()} if currency != "INR"
                 else {"step": "CURRENCY", "from": "INR"})
    if factor != 1:
        minor = minor / factor
        steps.append({"step": "UNIT", "perBaseUnit": f"price / {factor}"})
    tax_rate = D(data["tax_rate_pct"]) if data.get("tax_rate_pct") not in (None, "") else None
    if data.get("tax_included"):
        if tax_rate is None:
            raise TcoInputError("the price includes tax but tax_rate_pct is not given")
        if params.get("taxCreditable", True):
            minor = minor / (1 + tax_rate / 100)
            steps.append({"step": "TAX_STRIPPED", "ratePct": str(tax_rate), "reason": "GST on purchases is credited: compared without tax"})
        else:
            steps.append({"step": "TAX_KEPT", "ratePct": str(tax_rate), "reason": "tax is not creditable: part of the cost"})
    elif tax_rate is not None and not params.get("taxCreditable", True):
        minor = minor * (1 + tax_rate / 100)
        steps.append({"step": "TAX_ADDED", "ratePct": str(tax_rate), "reason": "tax is not creditable: part of the cost"})
    return {"minor": int(minor.quantize(Decimal(1), ROUND_HALF_UP)), "exact": minor, "currency": currency, "fxRate": rate, "fxDate": rate_from,
            "quotedMinor": int((quoted * 100).quantize(Decimal(1), ROUND_HALF_UP)), "steps": steps}


# ---------------------------------------------------------------- the engine
def _ppm(session: Session, params: dict, supplier_id, category: str) -> tuple[Optional[Decimal], str, dict]:
    twin = supplier_svc.twin(session, supplier_id, category)
    if twin is not None and twin.ppm is not None:
        return Decimal(twin.ppm), "TWIN", {"twin": str(twin.ppm), "evidence": twin.evidence_level}
    periods = int(params.get("ppmFromScorecardPeriods") or 0)
    if periods:
        cards = session.execute(select(Scorecard).where(Scorecard.supplier_id == supplier_id, Scorecard.ppm.is_not(None))
                                .order_by(Scorecard.period.desc()).limit(periods)).scalars().all()
        if cards:
            return sum((Decimal(c.ppm) for c in cards), Decimal(0)) / len(cards), "SCORECARD", {"periods": [c.period for c in cards]}
    if params.get("defaultPpm") not in (None, ""):
        return Decimal(str(params["defaultPpm"])), "RULE_DEFAULT", {"defaultPpm": str(params["defaultPpm"])}
    return None, "MISSING", {}


def _duty_rate(params: dict, hs_code: Optional[str]) -> Optional[tuple[str, Decimal]]:
    if not hs_code:
        return None
    best = None
    for prefix, pct in (params.get("dutyRates") or {}).items():
        if str(hs_code).startswith(str(prefix)) and (best is None or len(str(prefix)) > len(best[0])):
            best = (str(prefix), Decimal(str(pct)))
    return best


def compute(session: Session, *, params: dict, supplier_id, category: str, price_minor: int, lead_time_days: int, payment_terms_days: int,
            annual_qty: Optional[Decimal] = None, material: Optional[Material] = None, freight: Optional[Decimal] = None,
            duty: Optional[Decimal] = None, packaging: Optional[Decimal] = None, incoterm: Optional[str] = None, origin: Optional[str] = None,
            hs_code: Optional[str] = None, price_exact: Optional[Decimal] = None) -> dict:
    """The TCO of one bid line. freight, duty and packaging are rupees per base unit as quoted (None: not quoted)."""
    p = effective(params)
    price = price_exact if price_exact is not None else Decimal(price_minor)
    trace, parts, missing = [], {}, []

    def add(code: str, value: Decimal, status: str, formula: str, inputs: Optional[dict] = None) -> None:
        parts[code] = value
        trace.append({"component": code, "valueMinor": str(value.quantize(Decimal("0.0001"))), "status": status, "formula": formula, "inputs": inputs or {}})
        if status == "MISSING":
            missing.append(code)

    add("price", price, "BID", "normalised unit price", {"priceMinor": int(price_minor)})
    incoterm = (incoterm or "").upper() or None
    # freight
    if freight is not None:
        add("freight", Decimal(freight) * 100, "BID", "quoted freight per unit", {"quoted": str(freight)})
    elif incoterm in (p.get("buyerPaysFreightIncoterms") or []):
        pct = Decimal(str((p.get("freightEstimatePct") or {}).get(incoterm, "0")))
        add("freight", price * pct / 100, "ESTIMATED", f"price x {pct}% ({incoterm}: the buyer carries the freight)", {"incoterm": incoterm, "pct": str(pct)})
    elif incoterm in (p.get("deliveredIncoterms") or []):
        add("freight", Decimal(0), "INCLUDED", f"{incoterm}: the price covers carriage to the buyer", {"incoterm": incoterm})
    else:
        add("freight", Decimal(0), "NOT_QUOTED", "no freight quoted and no incoterm: assumed included in the price", {})
    # duty
    import_bid = (origin or "").upper() == "IMPORT"
    if duty is not None:
        add("duty", Decimal(duty) * 100, "BID", "quoted duty per unit", {"quoted": str(duty)})
    elif import_bid:
        found = _duty_rate(p, hs_code)
        if found is None:
            add("duty", Decimal(0), "MISSING", "import without a quoted duty and no rate for the HS code in SOURCING-TCO.dutyRates",
                {"hsCode": hs_code, "dutyBasis": p.get("dutyBasis")})
        else:
            basis = price + parts["freight"] if p.get("dutyBasis", "PRICE_PLUS_FREIGHT") == "PRICE_PLUS_FREIGHT" else price
            add("duty", basis * found[1] / 100, "ESTIMATED", f"(price + freight) x {found[1]}% (HS prefix {found[0]})",
                {"hsCode": hs_code, "prefix": found[0], "pct": str(found[1])})
    else:
        add("duty", Decimal(0), "NOT_APPLICABLE", "domestic supply: no customs duty", {})
    # packaging
    if packaging is not None:
        add("packaging", Decimal(packaging) * 100, "BID", "quoted packaging per unit", {"quoted": str(packaging)})
    else:
        add("packaging", Decimal(0), "NOT_QUOTED", "no packaging charge quoted: assumed included in the price", {})
    # carrying cost: pipeline (lead time) + safety stock
    rate = Decimal(str(p["carryingRatePct"]))
    safety_days, safety_inputs = Decimal(0), {}
    if p.get("includeSafetyStock") and material is not None and annual_qty and Decimal(annual_qty) > 0 and Decimal(material.safety_stock or 0) > 0:
        daily = Decimal(annual_qty) / 365
        safety_days = min(Decimal(material.safety_stock) / daily, Decimal(str(p.get("maxSafetyDays", 90))))
        safety_inputs = {"safetyStock": str(material.safety_stock), "dailyDemand": str(daily.quantize(Decimal("0.001"))), "safetyDays": str(safety_days.quantize(Decimal("0.01")))}
    days = Decimal(lead_time_days) + safety_days
    add("carrying", price * rate / 100 * days / 365, "BID" if lead_time_days is not None else "MISSING",
        f"price x {rate}% x ({lead_time_days} lead + {safety_days.quantize(Decimal('0.01'))} safety days) / 365",
        {"carryingRatePct": str(rate), "leadTimeDays": lead_time_days, **safety_inputs})
    # quality cost
    ppm, source, inputs = _ppm(session, p, supplier_id, category)
    copq = Decimal(str(p["copqPerDefectMinor"]))
    if ppm is None:
        add("quality", Decimal(0), "MISSING", "no PPM from the twin or the scorecards: the quality cost is unknown (not zero)", {"copqPerDefectMinor": int(copq)})
    else:
        add("quality", ppm / 1_000_000 * copq, source, f"{ppm.quantize(Decimal('0.1'))} ppm / 1,000,000 x {int(copq)}", {"ppm": str(ppm), **inputs})
    # payment-term value
    coc = Decimal(str(p["costOfCapitalPct"]))
    add("paymentTermValue", -(price * coc / 100 * Decimal(payment_terms_days) / 365), "BID",
        f"- price x {coc}% x {payment_terms_days} days / 365", {"costOfCapitalPct": str(coc), "paymentTermsDays": payment_terms_days})
    exact_total = sum(parts.values(), Decimal(0))
    total = int(exact_total.quantize(Decimal(1), ROUND_HALF_UP))
    rounded = {k: int(v.quantize(Decimal(1), ROUND_HALF_UP)) for k, v in parts.items()}
    rounding = total - sum(rounded.values())
    if missing and p.get("missingInput") == "REJECT":
        raise TcoInputError("TCO input missing: " + ", ".join(missing))
    return {"totalMinor": total, "parts": rounded, "rounding": rounding, "incomplete": bool(missing), "missing": missing, "trace": trace}
