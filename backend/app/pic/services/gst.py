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


# ---------------------------------------------------------------- tax heads (CGST / SGST / IGST) and reverse charge
RCM_RULE_KEY = "GST-RCM"


def supplier_state(session: Session, supplier) -> Optional[str]:
    """The supplier's GST state code (master data, else the first two digits of its GSTIN); None for a foreign supplier."""
    from app.pic.platform import crypto
    if (supplier.country or "IN").upper() != "IN":
        return None
    if supplier.state_code:
        return supplier.state_code
    from app.pic.services import finance_controls
    gstin = finance_controls.supplier_gstin(session, supplier)
    return gstin[:2] if len(gstin) == 15 else None


def place_of_supply(session: Session, company_code: str, plant: Optional[str]) -> Optional[str]:
    """State code of the place of supply of goods delivered to a plant (the plant's state), else the registered state of the company code (GSTIN)."""
    from sqlalchemy import select
    from app.pic.models import CompanyCode, Plant
    if plant:
        state = session.execute(select(Plant.state_code).where(Plant.code == plant)).scalar_one_or_none()
        if state:
            return state
    gstin = session.execute(select(CompanyCode.gstin).where(CompanyCode.code == company_code)).scalar_one_or_none()
    return gstin[:2] if gstin and len(gstin) == 15 else None


def split_tax(tax_minor: int, supply: Optional[str]) -> dict:
    """The tax heads of an amount: CGST and SGST (half each, the odd paisa to SGST) inside the state, IGST between states; {} when unknown."""
    if supply == "INTRA":
        cgst = tax_minor // 2
        return {"cgst": cgst, "sgst": tax_minor - cgst, "igst": 0}
    if supply == "INTER":
        return {"cgst": 0, "sgst": 0, "igst": tax_minor}
    return {}


def reverse_charge(session: Session, supplier, hsn_code: Optional[str], on: Optional[date] = None) -> bool:
    """Whether GST on this supply is paid by the buyer under reverse charge (rule set GST-RCM, tenant data: ``hsnPrefixes`` of the notified goods and
    services, ``unregisteredSupplier`` for a supplier without a GSTIN). Without the rule no supply is reverse charge, except an import of services:
    a service (SAC chapter 99) from a supplier located outside India is always reverse charge (IGST Act s.5(3), notification 10/2017-Integrated
    Tax (Rate) entry 1); the foreign supplier charges no Indian GST. Imported goods are not: their IGST is paid at customs on the bill of entry."""
    digits = digits_of(hsn_code)
    country = getattr(supplier, "country", None)
    if digits and digits.startswith("99") and country and country not in ("IN", "ZZ"):  # ZZ: country not known (legacy spend suppliers)
        return True
    try:
        body = rules.resolve(session, RCM_RULE_KEY, on).body
    except Problem:
        return False
    if digits and any(digits.startswith(str(prefix)) for prefix in body.get("hsnPrefixes") or []):
        return True
    return bool(body.get("unregisteredSupplier")) and not supplier.gstin_enc
