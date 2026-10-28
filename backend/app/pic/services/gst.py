"""HSN/SAC master and GST-rate validation (Technical Document §4 reference data, D11).

The master is the CBIC rate schedule loaded by the reference-data pack into the effective-dated rule set ``HSN-GST``
(there is no dedicated HSN table yet; see the pack notes). Each entry covers HSN/SAC digit prefixes, minus excluded
prefixes, at one total GST rate; a code can carry several entries when the notification sets conditional rates
(surgical vs other gloves, GTA with or without input tax credit), and then every rate of the most specific matching
entries is valid.

Validation is deliberately conservative: a code is judged only when an entry at heading level or deeper (at least
``minPrefix`` digits, default 4) matches it, because chapter-level entries ("84, 85 or 94" renewable-energy devices,
"28" inorganic chemicals) name specific goods or leave exceptions to other schedules. Codes the master does not know
are never flagged.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.pic.platform import rules
from app.pic.platform.errors import Problem

RULE_KEY = "HSN-GST"
_INDEX: dict[str, list] = {}  # rule-set ref → parsed entries (versions are immutable, P14)


@dataclass(frozen=True)
class Entry:
    prefixes: tuple
    excludes: tuple
    type: str
    rate: Decimal
    description: str
    ref: str
    notification: str

    def match_length(self, digits: str) -> int:
        if any(digits.startswith(x) for x in self.excludes):
            return 0
        return max((len(p) for p in self.prefixes if digits.startswith(p)), default=0)


def digits_of(code: Optional[str]) -> str:
    return "".join(ch for ch in (code or "") if ch.isdigit())


def _master(session: Session, on: Optional[date]):
    try:
        rule = rules.resolve(session, RULE_KEY, on)
    except Problem:
        return None, []
    key = f"{rule.ref}:{len(rule.body.get('entries', []))}"
    if key not in _INDEX:
        _INDEX[key] = [Entry(tuple(e["prefixes"]), tuple(e.get("excludes") or ()), e["type"], Decimal(str(e["rate"])), e["description"],
                             e["ref"], e["notification"]) for e in rule.body.get("entries", [])]
    return rule, _INDEX[key]


def lookup(session: Session, code: Optional[str], on: Optional[date] = None) -> dict:
    """The most specific master entries for an HSN/SAC code: {code, matchedDigits, rates, entries, ruleSetVersion}."""
    rule, entries = _master(session, on)
    digits = digits_of(code)
    out = {"code": code, "matchedDigits": 0, "rates": [], "entries": [], "ruleSetVersion": rule.ref if rule else None}
    if not digits or not entries:
        return out
    best, found = 0, []
    for entry in entries:
        n = entry.match_length(digits)
        if n > best:
            best, found = n, [entry]
        elif n and n == best:
            found.append(entry)
    out.update(matchedDigits=best, rates=sorted({e.rate for e in found}),
               entries=[{"type": e.type, "rate": str(e.rate), "description": e.description, "ref": e.ref, "notification": e.notification}
                        for e in found])
    return out


def check(session: Session, code: Optional[str], rate, on: Optional[date] = None) -> Optional[dict]:
    """None when the rate is valid for the code (or the master cannot judge it); otherwise the finding."""
    rule, entries = _master(session, on)
    if rule is None or not digits_of(code):
        return None
    min_prefix = int((rule.body.get("validation") or {}).get("minPrefix", 4))
    found = lookup(session, code, on)
    if found["matchedDigits"] < min_prefix or Decimal(str(rate)) in found["rates"]:
        return None
    return {"hsn": code, "gstRate": str(Decimal(str(rate)).normalize()), "allowedRates": [str(r.normalize()) for r in found["rates"]],
            "masterEntries": [f"{e['ref']} ({e['notification']}) {e['rate']}%" for e in found["entries"]][:4],
            "ruleSetVersion": rule.ref}
