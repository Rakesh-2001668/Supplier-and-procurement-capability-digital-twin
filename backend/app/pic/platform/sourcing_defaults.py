"""Default bodies of the strategic-sourcing rule sets (M05). Seeded for every tenant by seed/reference.py RULE_SETS and migration 0022, editable
through POST /v1/admin/rules as new effective-dated versions; the code falls back to them for a tenant without the rule set (like INVENTORY-* and MSME).

SOURCING-POLICY  how events are run and governed: minimum bidders, the scoring / award controls, two-person bid opening, clarification and
                 lead-time rules, plausibility limits of a bid price, outlier and collusion screens, the policy for capacity nobody verified
SOURCING-TCO     the total-cost-of-ownership rule set (TD 9.3): carrying and capital rates, cost of poor quality, freight estimates by incoterm,
                 customs-duty rate table by HS prefix, tax treatment, and what to do when an input is missing. An event takes a copy of the
                 values when it is created (``tco_params``) so a later rule version never moves a running event.

All amounts are minor units (paise) unless a name says Pct. Starting points for the category and finance teams to confirm.
"""
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.pic.platform import rules
from app.pic.platform.errors import Problem

POLICY_KEY, TCO_KEY = "SOURCING-POLICY", "SOURCING-TCO"

POLICY_DEFAULT = {
    # competition
    "minBidders": 2,                           # valid bidders below this = limited competition (event.competitive = false)
    "limitedCompetitionNeedsRationale": True,  # an award on fewer valid bidders needs the written rationale
    # evaluation and award controls
    "requireAllCriteriaScored": True,          # every manual criterion scored for every bidder in the award before an award can be proposed
    "minRationaleChars": 15,                   # the written rationale of a non-lowest / exceptional award is a sentence, not a word
    # D5 (docs/PIC_Default_Decisions.md): an award on a bid whose offer validity has ended is BLOCKED (409 BID_OFFER_EXPIRED). The honest path is a
    # new round in which the supplier confirms or extends its offer; the block is lifted only by an override with a written reason from a holder of
    # one of these roles (a CATEGORY_MANAGER only for the event's category). An overridden award always goes to the AWARD-APPROVAL approvers.
    "expiredOfferOverride": {"roles": ["CATEGORY_MANAGER"], "minReasonChars": 20, "requiresApproval": True},
    "incompleteTcoNeedsRationale": False,      # an award on a bid whose TCO has a missing input is flagged and recorded; True: it also needs the written rationale
                                               # (off by default: older data has no PPM; the KAC rule version turns it on)
    "unverifiedCapacityNeedsRationale": False, # volume to a supplier whose capacity nobody verified is flagged and recorded; True: it also needs the written rationale
    "unverifiedCapacity": "FLAG",              # volume to a supplier whose capacity no bid or twin verifies: FLAG (shown, rationale) | BLOCK
    "twoPersonOpening": False,                 # the bids of a closed event are opened by two different people (opening ceremony)
    "tieBreak": ["WEIGHTED_SCORE", "EARLIEST_BID", "SUPPLIER_CODE"],  # applied in this order when two bids have the same total cost
    # lifecycle checks
    "minOpenHours": {"RFI": 0, "RFQ": 0, "RFP": 0, "REVERSE_AUCTION": 0},  # an event stays open at least this long (publish to close)
    "clarificationCloseHours": 0,              # questions close this many hours before the bid deadline (0: at the deadline)
    "leadTimeCheck": "WARN",                   # a bid whose lead time cannot meet the need date: ENFORCE | WARN | OFF
    "budgetCheck": "SOFT",                     # event value above the category plan budget: HARD | SOFT (justification) | OFF
    "mandatoryFields": {"RFI": [], "RFQ": ["need_date"], "RFP": ["need_date"], "REVERSE_AUCTION": ["need_date"]},
    "lineCategoryCheck": "WARN",               # a requirement line whose category differs from the event's: ENFORCE (refused) | WARN (audited); bundles always ENFORCE
    "maxExtensions": 12,                       # reverse auction: soft-close extensions before the end is final
    # plausibility of a bid line
    "priceBand": {"minVsBaseline": "0.05", "maxVsBaseline": "20", "maxUnitPriceMinor": 1_000_000_000 * 100},
    "maxLeadTimeDays": 730, "maxPaymentTermsDays": 365, "maxValidityDays": 730,
    # screens
    "outlier": {"zScore": "2.0", "vsMedianPct": "30", "vsShouldCostPct": "25", "minBids": 3},
    "collusion": {"identicalTotals": True, "identicalLinePattern": True, "sharedMasterData": True},
    # savings
    "baselineMethods": ["LAST_PRICE", "WEIGHTED_AVG", "SHOULD_COST", "MARKET_INDEX", "BUDGET", "MANUAL"],
    "competitiveBy": "VALID_BIDS",
}

TCO_DEFAULT = {
    "carryingRatePct": "18",                   # annual inventory carrying rate (capital, storage, obsolescence) on the purchase price
    "costOfCapitalPct": "12",                  # annual cost of capital: what an extra payment day is worth
    "copqPerDefectMinor": 500000,              # cost of poor quality of one defective unit; quality cost = ppm / 1,000,000 x this
    "includeSafetyStock": True,                # carrying cost covers the pipeline (lead time) plus the days the safety stock lasts
    "maxSafetyDays": 90,
    "defaultPpm": None,                        # PPM used when neither the twin nor the scorecards have one (null: the component is MISSING)
    "ppmFromScorecardPeriods": 3,              # twin PPM first, else the mean of the last N scorecards
    "buyerPaysFreightIncoterms": ["EXW", "FCA", "FAS", "FOB"],   # the buyer carries the freight: estimated when the bid gives none
    "freightEstimatePct": {"EXW": "3.0", "FCA": "2.5", "FAS": "3.5", "FOB": "3.5"},   # of the unit price (illustrative until logistics confirms)
    "deliveredIncoterms": ["DAP", "DPU", "DDP", "CIF", "CIP", "CPT", "CFR", "FOR"],   # the price already includes carriage to the buyer
    "dutyBasis": "PRICE_PLUS_FREIGHT",         # customs duty is charged on price + freight (CIF value) for imports
    "dutyRates": {},                           # HS prefix -> effective customs duty % (basic duty + social welfare surcharge): fill per tenant
    "taxCreditable": True,                     # GST paid on purchases is credited: compare prices without tax
    "missingInput": "FLAG",                    # FLAG: the TCO is marked incomplete and the award needs a rationale | REJECT: the bid line is refused
    "roundingMinor": 1,
}

DEFAULTS = {POLICY_KEY: POLICY_DEFAULT, TCO_KEY: TCO_DEFAULT}
BODIES = {
    POLICY_KEY: (POLICY_DEFAULT, "Strategic sourcing policy: minimum bidders, scoring and award controls, two-person bid opening, lifecycle checks, "
                                 "plausibility limits and outlier / collusion screens (BP M05)"),
    TCO_KEY: (TCO_DEFAULT, "Total cost of ownership rule set: carrying and capital rates, cost of poor quality, freight by incoterm, customs-duty "
                           "rate table, tax treatment and the missing-input policy (TD 9.3)"),
}


def rule(session: Session, key: str, **scope: Optional[str]) -> rules.Rule:
    """The effective rule set of the scope, else the documented default; a partial body is completed with the default's keys."""
    try:
        found = rules.resolve(session, key, **scope)
        return rules.Rule(found.key, found.version, {**DEFAULTS[key], **(found.body or {})})
    except Problem as exc:
        if exc.code != "RULE_SET_MISSING":
            raise
        return rules.Rule(key, "code-default", dict(DEFAULTS[key]))


def policy(session: Session, **scope: Optional[str]) -> rules.Rule:
    return rule(session, POLICY_KEY, **scope)


def tco_rule(session: Session, **scope: Optional[str]) -> rules.Rule:
    return rule(session, TCO_KEY, **scope)


def _dec(value, name: str, errors: list[str], low: Optional[Decimal] = None, high: Optional[Decimal] = None) -> None:
    try:
        number = Decimal(str(value))
    except Exception:  # noqa: BLE001
        errors.append(f"{name} must be a number")
        return
    if (low is not None and number < low) or (high is not None and number > high):
        errors.append(f"{name} must be between {low} and {high}")


def validate(key: str, body: dict) -> list[str]:
    """Errors in a new version of a sourcing rule set (POST /v1/admin/rules): an empty list when it is usable."""
    errors: list[str] = []
    if key not in DEFAULTS:
        return errors
    if not isinstance(body, dict):
        return ["the body must be an object"]
    unknown = sorted(set(body) - set(DEFAULTS[key]))
    if unknown:
        errors.append(f"unknown key(s) {', '.join(unknown)}; allowed: {', '.join(sorted(DEFAULTS[key]))}")
    if key == TCO_KEY:
        for name in ("carryingRatePct", "costOfCapitalPct"):
            if name in body:
                _dec(body[name], name, errors, Decimal(0), Decimal(100))
        if "copqPerDefectMinor" in body and (not isinstance(body["copqPerDefectMinor"], int) or body["copqPerDefectMinor"] < 0):
            errors.append("copqPerDefectMinor must be a non-negative integer (minor units)")
        if body.get("missingInput", "FLAG") not in ("FLAG", "REJECT"):
            errors.append("missingInput must be FLAG or REJECT")
        for prefix, pct in (body.get("dutyRates") or {}).items():
            if not str(prefix).isdigit() or not 2 <= len(str(prefix)) <= 10:
                errors.append(f"dutyRates key {prefix!r} must be an HS prefix of 2 to 10 digits")
            _dec(pct, f"dutyRates[{prefix}]", errors, Decimal(0), Decimal(300))
        for name, pct in (body.get("freightEstimatePct") or {}).items():
            _dec(pct, f"freightEstimatePct[{name}]", errors, Decimal(0), Decimal(100))
    if key == POLICY_KEY:
        if "minBidders" in body and (not isinstance(body["minBidders"], int) or not 1 <= body["minBidders"] <= 20):
            errors.append("minBidders must be a whole number from 1 to 20")
        if body.get("unverifiedCapacity", "FLAG") not in ("FLAG", "BLOCK"):
            errors.append("unverifiedCapacity must be FLAG or BLOCK")
        if body.get("leadTimeCheck", "WARN") not in ("ENFORCE", "WARN", "OFF"):
            errors.append("leadTimeCheck must be ENFORCE, WARN or OFF")
        if body.get("budgetCheck", "SOFT") not in ("HARD", "SOFT", "OFF"):
            errors.append("budgetCheck must be HARD, SOFT or OFF")
        for name in ("minOpenHours",):
            for event_type, hours in (body.get(name) or {}).items():
                if not isinstance(hours, int) or hours < 0:
                    errors.append(f"{name}[{event_type}] must be a non-negative whole number of hours")
        for method in body.get("baselineMethods") or []:
            if method not in POLICY_DEFAULT["baselineMethods"]:
                errors.append(f"baseline method {method} is unknown")
        if "expiredOfferOverride" in body:
            errors.extend(_override_errors(body["expiredOfferOverride"]))
    return errors


def _override_errors(value) -> list[str]:
    """Problems of SOURCING-POLICY.expiredOfferOverride (who may lift the expired-offer block of an award, D5)."""
    if not isinstance(value, dict):
        return ["expiredOfferOverride must be an object {roles, minReasonChars, requiresApproval}"]
    errors = []
    roles = value.get("roles", [])
    if not isinstance(roles, list) or not all(isinstance(r, str) and r.isupper() for r in roles):
        errors.append("expiredOfferOverride.roles must be a list of role codes (an empty list: nobody may override)")
    elif "SUPPLIER_USER" in roles:
        errors.append("expiredOfferOverride.roles: a supplier user cannot override an award block")
    chars = value.get("minReasonChars", 20)
    if not isinstance(chars, int) or isinstance(chars, bool) or not 10 <= chars <= 1000:
        errors.append("expiredOfferOverride.minReasonChars must be a whole number from 10 to 1000")
    if not isinstance(value.get("requiresApproval", True), bool):
        errors.append("expiredOfferOverride.requiresApproval must be true or false")
    return errors


# ---------------------------------------------------------------- ABAC actions of the sourcing commands
# Creating an event is bound to the user's categories / plants / company codes; managing it (publish, close, open the bids, disqualify, propose the
# award, export the comparison) to its category. Registered here (not in platform/abac.py) so the policy of a tenant whose ABAC rule set predates them
# gets them through ``abac.policy_for`` (ADDED_ACTIONS) and a tenant without the rule set through DEFAULT_POLICY.
SOURCING_ACTIONS = {
    "SOURCING_CREATE": {"check": ["category", "plant", "company_code"]},
    "SOURCING_MANAGE": {"check": ["category"]},
    "SOURCING_EXPORT": {"check": ["category"]},
}


def _register_abac_actions() -> None:
    from app.pic.platform import abac
    abac.ADDED_ACTIONS.update(SOURCING_ACTIONS)
    abac.DEFAULT_POLICY["actions"].update(SOURCING_ACTIONS)


_register_abac_actions()
