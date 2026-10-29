"""Effective-dated rule sets (AD-07, P14) and the decision tables that read them.

Thresholds live in ``rule_set`` rows, never in code. A rule set binds to a
scope tuple (company code, plant, category, purchase type); the most specific
match on the business date wins. Documents store the returned version label.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.pic.models import RuleSet
from app.pic.platform import clock
from app.pic.platform.errors import Problem

SCOPE_FIELDS = ("company_code", "plant", "category", "purchase_type")


@dataclass
class Rule:
    key: str
    version: str
    body: dict

    @property
    def ref(self) -> str:
        return f"{self.key}@{self.version}"


def resolve(session: Session, key: str, on: Optional[date] = None, **scope: Optional[str]) -> Rule:
    on = on or clock.today()
    candidates = session.execute(
        select(RuleSet).where(
            RuleSet.key == key,
            RuleSet.effective_from <= on,
            or_(RuleSet.effective_to.is_(None), RuleSet.effective_to >= on),
        )
    ).scalars().all()
    # Deterministic: most specific, then latest effective date, then (same date) the version created last, then version label.
    never = datetime.min.replace(tzinfo=timezone.utc)
    best, best_rank = None, (-1, date.min, never, "")
    for rs in candidates:
        specificity = 0
        matches = True
        for f in SCOPE_FIELDS:
            bound = getattr(rs, f)
            if bound is None:
                continue
            if scope.get(f) != bound:
                matches = False
                break
            specificity += 1
        rank = (specificity, rs.effective_from, rs.created_at or never, rs.version or "")
        if matches and rank > best_rank:
            best, best_rank = rs, rank
    if best is None:
        raise Problem(500, "RULE_SET_MISSING", f"No active rule set {key} for {scope} on {on}")
    return Rule(best.key, best.version, best.body)


def refs(*rules: Rule) -> str:
    return ";".join(r.ref for r in rules)


# ---------------------------------------------------------------- DMN-01 requisition approval route
def requisition_chain(rule: Rule, value_minor: int, channel: str, account_type: Optional[str], purchase_type: str) -> list[str]:
    chain: list[str] = []
    for band in rule.body["bands"]:
        if band["upTo"] is None or value_minor < band["upTo"]:
            if channel in band.get("autoChannels", []):
                chain = []
            else:
                chain = list(band["chain"])
            break
    if account_type == "ASSET" or purchase_type == "ASSET":
        for role in rule.body.get("assetAdds", []):
            if role not in chain:
                chain.append(role)
    return chain


# ---------------------------------------------------------------- PO risk score (§7.4)
def po_risk(rule: Rule, *, late_prob: Decimal, price_deviation: bool, supplier_not_qualified: bool,
            value_above_band: bool, split_pattern: bool, account_changed: bool, model_version: str = "eta-v3") -> dict:
    b = rule.body
    factors = []
    p = Decimal(str(late_prob))
    if p >= Decimal(str(b["lateMed"])):
        factors.append({"code": "LATE_RISK_MED", "points": b["lateMedPts"], "evidence": f"model {model_version}: {p}"})
    if p >= Decimal(str(b["lateHigh"])):
        factors.append({"code": "LATE_RISK_HIGH", "points": b["lateHighPts"], "evidence": f"model {model_version}: {p}"})
    if price_deviation:
        factors.append({"code": "PRICE_DEVIATION", "points": b["priceDevPts"], "evidence": "price outside contract tolerance"})
    if supplier_not_qualified:
        factors.append({"code": "SUPPLIER_NOT_QUALIFIED", "points": b["notQualifiedPts"], "evidence": "supplier not Qualified/Preferred for category"})
    if value_above_band:
        factors.append({"code": "VALUE_ABOVE_BAND", "points": b["valueAboveBandPts"], "evidence": "value above touchless band"})
    if split_pattern:
        factors.append({"code": "SPLIT_PATTERN", "points": b["splitPts"], "evidence": f"split pattern within {b['splitWindowDays']} days"})
    if account_changed:
        factors.append({"code": "ACCOUNT_ASSIGNMENT_CHANGED", "points": b["acctChangedPts"], "evidence": "account assignment differs from requisition"})
    score = min(sum(f["points"] for f in factors), 100)
    return {"score": score, "factors": factors}


# ---------------------------------------------------------------- DMN-02 touchless PO
def touchless(rule: Rule, *, price_sources: set[str], supplier_status: str, value_minor: int, split_pattern: bool,
              late_prob: Decimal, risk_score: int, account_changed: bool) -> dict:
    b = rule.body
    reasons = []
    if not price_sources or not price_sources.issubset(set(b["priceSources"])):
        reasons.append(f"price source {sorted(price_sources)} is not contract/catalogue")
    if supplier_status not in b["supplierStatuses"]:
        reasons.append(f"supplier status {supplier_status} is not Qualified/Preferred")
    if value_minor > b["touchlessBandMinor"]:
        reasons.append("value above touchless band")
    if split_pattern:
        reasons.append("split pattern detected")
    if Decimal(str(late_prob)) >= Decimal(str(b["maxLateProb"])):
        reasons.append(f"late-delivery probability {late_prob} >= {b['maxLateProb']}")
    if risk_score >= b["maxRisk"]:
        reasons.append(f"risk score {risk_score} >= {b['maxRisk']}")
    if account_changed:
        reasons.append("account assignment changed")
    return {"touchless": not reasons, "reasons": reasons}


# ---------------------------------------------------------------- generic value-band chains
def band_chain(rule: Rule, value_minor: int) -> list[str]:
    for band in rule.body["bands"]:
        if band["upTo"] is None or value_minor < band["upTo"]:
            return list(band["chain"])
    return []
