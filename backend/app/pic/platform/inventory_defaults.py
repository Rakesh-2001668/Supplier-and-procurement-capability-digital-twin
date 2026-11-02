"""Default bodies of the inventory rule sets (seeded for every tenant by seed/reference.py RULE_SETS and migration 0018, editable through
POST /v1/admin/rules as new effective-dated versions; the code falls back to them for a tenant without the rule set, like MSME and TDS).

INVENTORY-POSTING      stock postings (transfer, block, unblock, scrap): which types post by themselves under a value, the approval chain by value
                       band, the reasons, the limits of one document
INVENTORY-COUNT        physical inventory: the count tolerance that triggers a recount, who may recount, the approval chain by the value of the
                       differences
INVENTORY-RESERVATION  reservations: whether an unavailable quantity is refused or only warned about, the grace after the need date, purposes
INVENTORY-ALERTS       the ageing limits of the stock alerts (quality hold, blocked stock, expiry warning)
All amounts are minor units (paise). Starting points for the plant and finance teams to confirm.
"""
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.pic.platform import rules
from app.pic.platform.errors import Problem

L = 100_000 * 100  # one lakh rupees in paise

POSTING_KEY, COUNT_KEY, RESERVATION_KEY, ALERTS_KEY = "INVENTORY-POSTING", "INVENTORY-COUNT", "INVENTORY-RESERVATION", "INVENTORY-ALERTS"

POSTING_DEFAULT = {
    "autoPostBelowMinor": 25_000 * 100,
    "autoPostTypes": ["TRANSFER", "BLOCK", "UNBLOCK"],
    "approvalBands": [{"upTo": 2 * L, "chain": ["INVENTORY_CONTROLLER"]},
                      {"upTo": 10 * L, "chain": ["INVENTORY_CONTROLLER", "FINANCE_CONTROLLER"]},
                      {"upTo": None, "chain": ["INVENTORY_CONTROLLER", "FINANCE_CONTROLLER", "CPO"]}],
    "reasonRequiredFor": ["BLOCK", "SCRAP"],
    "scrapReasons": {"DAMAGED": "Damaged in handling or storage", "EXPIRED": "Expired", "OBSOLETE": "Obsolete or superseded",
                     "QUALITY": "Failed quality, not returnable", "LOST": "Lost, stolen or missing", "OTHER": "Other (explain in the reason)"},
    "blockReasons": {"QUALITY_DOUBT": "Quality doubt", "DAMAGED": "Damaged, to be assessed", "RECALL": "Supplier recall or field notice",
                     "INVESTIGATION": "Under investigation", "OTHER": "Other (explain in the reason)"},
    "crossPlantTransfer": True, "maxLines": 100, "slaBusinessDays": 2,
}
COUNT_DEFAULT = {
    "qtyTolerancePct": "2", "valueToleranceMinor": 5_000 * 100, "recountDifferentCounter": True, "maxLines": 2000, "slaBusinessDays": 3,
    "approvalBands": [{"upTo": 50_000 * 100, "chain": ["INVENTORY_CONTROLLER"]},
                      {"upTo": 5 * L, "chain": ["INVENTORY_CONTROLLER", "FINANCE_CONTROLLER"]},
                      {"upTo": None, "chain": ["INVENTORY_CONTROLLER", "FINANCE_CONTROLLER", "CPO"]}],
    "differenceReasonCode": "COUNT_DIFF",
}
RESERVATION_DEFAULT = {
    "blockWhenUnavailable": False, "graceDays": 7, "requireCostObject": True,
    "purposes": ["PRODUCTION", "MAINTENANCE", "PROJECT", "SERVICE", "OTHER"], "maxOpenDays": 365,
}
ALERTS_DEFAULT = {"qualityHoldDays": 7, "blockedDays": 30, "expiryWarnDays": 90, "negativeDrift": True}

DEFAULTS = {POSTING_KEY: POSTING_DEFAULT, COUNT_KEY: COUNT_DEFAULT, RESERVATION_KEY: RESERVATION_DEFAULT, ALERTS_KEY: ALERTS_DEFAULT}
BODIES = {
    POSTING_KEY: (POSTING_DEFAULT, "Stock postings (transfer, block, unblock, scrap): auto-post limit, approval chain by value band, reasons (BP M09)"),
    COUNT_KEY: (COUNT_DEFAULT, "Physical inventory: recount tolerance (quantity % and value), recount by a different counter, approval chain by "
                               "the value of the differences"),
    RESERVATION_KEY: (RESERVATION_DEFAULT, "Stock reservations: warn or refuse when the quantity is not available, grace days after the need date"),
    ALERTS_KEY: (ALERTS_DEFAULT, "Stock alert limits: days a quality hold / blocked stock may stand, expiry warning horizon"),
}


def rule(session: Session, key: str, **scope: Optional[str]) -> rules.Rule:
    """The effective rule set of the scope, else the documented default; a partial body is completed with the default's keys."""
    try:
        found = rules.resolve(session, key, **scope)
        return rules.Rule(found.key, found.version, {**DEFAULTS[key], **(found.body or {})})
    except Problem:
        return rules.Rule(key, "code-default", dict(DEFAULTS[key]))


def band_chain(body: dict, value_minor: int) -> list[str]:
    for band in body.get("approvalBands") or []:
        if band.get("upTo") is None or int(value_minor) <= int(band["upTo"]):
            return list(band["chain"])
    return list((body.get("approvalBands") or [{"chain": ["INVENTORY_CONTROLLER"]}])[-1]["chain"])


def validate(key: str, body: dict) -> list[str]:
    """Errors in a new version of an inventory rule set (POST /v1/admin/rules): an empty list when it is usable."""
    errors: list[str] = []
    if key not in DEFAULTS:
        return errors
    if not isinstance(body, dict):
        return ["the body must be an object"]
    unknown = sorted(set(body) - set(DEFAULTS[key]))
    if unknown:
        errors.append(f"unknown key(s) {', '.join(unknown)}; allowed: {', '.join(sorted(DEFAULTS[key]))}")
    for band_key in ("approvalBands",):
        if band_key in body:
            bands = body[band_key]
            if not isinstance(bands, list) or not bands:
                errors.append("approvalBands must be a non-empty list of {upTo, chain}")
                continue
            last = -1
            for position, band in enumerate(bands, start=1):
                chain = band.get("chain") if isinstance(band, dict) else None
                if not chain or not all(isinstance(r, str) and r for r in chain):
                    errors.append(f"approvalBands[{position}] needs a chain of role codes")
                up_to = band.get("upTo") if isinstance(band, dict) else None
                if up_to is None:
                    if position != len(bands):
                        errors.append("only the last band may have upTo null")
                elif not isinstance(up_to, int) or isinstance(up_to, bool) or up_to <= last:
                    errors.append(f"approvalBands[{position}].upTo must be an integer (minor units) above the previous band")
                else:
                    last = up_to
            if isinstance(bands[-1], dict) and bands[-1].get("upTo") is not None:
                errors.append("the last band must have upTo null so every value has an approver")
    if key == POSTING_KEY:
        if "autoPostBelowMinor" in body and (not isinstance(body["autoPostBelowMinor"], int) or body["autoPostBelowMinor"] < 0):
            errors.append("autoPostBelowMinor must be a non-negative integer (minor units)")
        if "SCRAP" in (body.get("autoPostTypes") or []):
            errors.append("SCRAP always needs approval: remove it from autoPostTypes")
    if key == COUNT_KEY:
        for name in ("qtyTolerancePct",):
            if name in body:
                try:
                    if Decimal(str(body[name])) < 0:
                        errors.append(f"{name} must not be negative")
                except Exception:  # noqa: BLE001
                    errors.append(f"{name} must be a number")
        if "valueToleranceMinor" in body and (not isinstance(body["valueToleranceMinor"], int) or body["valueToleranceMinor"] < 0):
            errors.append("valueToleranceMinor must be a non-negative integer (minor units)")
    if key == RESERVATION_KEY and "graceDays" in body and (not isinstance(body["graceDays"], int) or body["graceDays"] < 0):
        errors.append("graceDays must be a non-negative integer")
    return errors
