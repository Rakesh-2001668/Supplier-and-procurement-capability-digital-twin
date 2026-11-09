"""Section 195 withholding on payments to non-residents (Income-tax Act, 1961 numbering as configured; see docs/PIC_Tax_Partial_Payments.md).

What it does
* Tax residency of a supplier (``SupplierTaxResidency``): resident / non-resident, country, payee type, PAN or no PAN, foreign tax identification
  number, Tax Residency Certificate (number, validity, document reference), Form 10F (acknowledgement, filing date, period it covers), the
  no-permanent-establishment declaration, s.195A gross-up and the default payment nature. Sensitive identifiers are encrypted.
* Rate determination (``determine``, a pure function of the rule body): the Act rate of the payment nature with surcharge and health and
  education cess, against the treaty (DTAA) rate when the treaty documents are valid on the payment date; the lower one applies. Without a PAN,
  s.206AA asks for the higher of its rate and the Act rate unless the non-resident relief applies (Rule 37BC documents). A valid lower-deduction
  certificate replaces the rate. With gross-up the company bears the tax: the income is grossed up to ``net / (1 - rate)``.
* The invoice carries a provisional determination from posting (section key ``195-<NATURE>``, rate, base); the payment run re-determines on the
  payment date (documents expire, rules change) and stores the result on the payment (INR tax and base for the 27Q return, the breakdown).
* Form 15CA / 15CB checkpoint: a remittance to a non-resident is not released until a Form 15CA acknowledgement covering it is recorded, with the
  Form 15CB CA certificate when the rule threshold applies.

Every rate, slab, threshold and label is rule data (rule set TDS-195, effective-dated, scope company code). The defaults in
platform/finance_defaults.py are MOCK values the client's chartered accountant must confirm; PIC is not a tax authority.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import Invoice, Payment, PurchaseOrder, RemittanceCertificate, Supplier, SupplierTaxResidency
from app.pic.platform import audit, clock, crypto, finance_defaults, outbox, rules
from app.pic.platform.errors import Problem, not_found
from app.pic.services.common import principal

KEY = "TDS-195"
DEFAULT = finance_defaults.TDS_195_DEFAULT
SECTION_PREFIX = "195-"
RESIDENCIES = ("RESIDENT", "NON_RESIDENT")
PAYEE_TYPES = ("COMPANY", "NON_COMPANY")
COUNTRY = re.compile(r"^[A-Z]{2}$")
DOC_NO = re.compile(r"^[A-Z0-9/\-. ]{4,40}$")
ACK = re.compile(r"^[A-Z0-9]{8,20}$")
UDIN = re.compile(r"^[A-Z0-9]{6,40}$")
MEMBERSHIP = re.compile(r"^[0-9]{6}$")
EDIT_SCOPES = frozenset({"supplier:manage", "payment:run"})
PCT = Decimal("0.0001")
# Problem codes of the release checkpoint: a remittance named in a payment run is refused with 409 when one of them applies.
BLOCKING = ("FORM_15CA_REQUIRED", "FORM_15CB_REQUIRED", "TDS_195_NOT_DETERMINED")


def _d(value) -> Decimal:
    return Decimal(str(value))


def _money(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), ROUND_HALF_UP))


# ================================================================ rule
def rule(session: Session, company_code: Optional[str], on: Optional[date] = None) -> tuple[dict, str]:
    """(body, reference) of rule set TDS-195 valid on ``on`` for the company code; the documented MOCK default when the tenant has none."""
    try:
        found = rules.resolve(session, KEY, on=on or clock.today(), company_code=company_code)
        return found.body, found.ref
    except Problem:
        return DEFAULT, f"{KEY}@default"


def natures(body: dict) -> dict:
    return body.get("natures") or {}


def section_key(nature: str) -> str:
    return f"{SECTION_PREFIX}{nature}"


def is_195(section: Optional[str]) -> bool:
    return bool(section) and section.startswith(SECTION_PREFIX)


def nature_of_section(section: Optional[str]) -> Optional[str]:
    return section[len(SECTION_PREFIX):] if is_195(section) else None


def return_form(section: Optional[str]) -> str:
    """The quarterly TDS return a deduction belongs to: 27Q for payments to non-residents (section 195), 26Q for residents."""
    return "27Q" if is_195(section) else "26Q"


def section_labels(body: dict) -> dict:
    """Labels of the s.195 section keys for returns and certificates ("195 - Royalty")."""
    label = body.get("sectionLabel") or "195"
    return {section_key(k): {"label": f"{label} - {v.get('label') or k}", "ratePct": None} for k, v in natures(body).items()}


# ================================================================ residency
def residency_of(session: Session, supplier_id) -> Optional[SupplierTaxResidency]:
    return session.execute(select(SupplierTaxResidency).where(SupplierTaxResidency.supplier_id == supplier_id)).scalar_one_or_none()


def non_resident(session: Session, supplier_id) -> Optional[SupplierTaxResidency]:
    row = residency_of(session, supplier_id)
    return row if row is not None and row.residency == "NON_RESIDENT" else None


def _decrypt(row, purpose: str, token) -> Optional[str]:
    if not token:
        return None
    try:
        return crypto.decrypt(row.tenant_id, purpose, bytes(token))
    except Exception:  # noqa: BLE001 - a key mismatch must not leak ciphertext or break a return; the caller reports it as missing
        return None


def pan_of(row: Optional[SupplierTaxResidency]) -> Optional[str]:
    return _decrypt(row, "tax-pan", row.pan_enc) if row is not None else None


def _valid(on: date, start: Optional[date], end: Optional[date]) -> bool:
    return (start is None or start <= on) and (end is None or on <= end)


def documents_on(row: SupplierTaxResidency, supplier: Supplier, on: date) -> tuple[set, dict]:
    """The documents valid on ``on`` (TRC, FORM_10F, NO_PE, TAX_ID, ADDRESS, PAN) and, for each one that is not, why."""
    have, why = set(), {}
    if row.trc_no_enc and row.trc_valid_from and row.trc_valid_to and row.trc_valid_from <= on <= row.trc_valid_to:
        have.add("TRC")
    else:
        why["TRC"] = ("no Tax Residency Certificate on file" if not row.trc_no_enc else
                      f"the Tax Residency Certificate is valid {row.trc_valid_from} to {row.trc_valid_to}, not on {on.isoformat()}")
    if row.form10f_ack_enc and row.form10f_valid_from and row.form10f_valid_to and row.form10f_valid_from <= on <= row.form10f_valid_to:
        have.add("FORM_10F")
    else:
        why["FORM_10F"] = ("no Form 10F on file" if not row.form10f_ack_enc else
                           f"Form 10F covers {row.form10f_valid_from} to {row.form10f_valid_to}, not {on.isoformat()}")
    if row.no_pe_declared and _valid(on, row.no_pe_valid_from, row.no_pe_valid_to):
        have.add("NO_PE")
    else:
        why["NO_PE"] = "no valid no-permanent-establishment declaration"
    if row.tax_id_enc:
        have.add("TAX_ID")
    else:
        why["TAX_ID"] = "no tax identification number of the country of residence"
    if str((supplier.address or {}).get("line1") or "").strip():
        have.add("ADDRESS")
    else:
        why["ADDRESS"] = "no address in the country of residence"
    if row.pan_enc or supplier.pan_hash:
        have.add("PAN")
    return have, why


def _require_editor(session: Session) -> None:
    if not principal(session).scopes & EDIT_SCOPES:
        raise Problem(403, "FORBIDDEN", "Tax residency is maintained by supplier management or finance (permission supplier:manage or payment:run)")


def set_residency(session: Session, supplier: Supplier, *, residency: str, country: str, payee_type: str = "COMPANY", reason: str,
                  pan: Optional[str] = None, tax_id: Optional[str] = None, trc_no: Optional[str] = None, trc_valid_from: Optional[date] = None,
                  trc_valid_to: Optional[date] = None, trc_document_ref: Optional[str] = None, form10f_ack: Optional[str] = None,
                  form10f_filed_on: Optional[date] = None, form10f_valid_from: Optional[date] = None, form10f_valid_to: Optional[date] = None,
                  no_pe_declared: bool = False, no_pe_valid_from: Optional[date] = None, no_pe_valid_to: Optional[date] = None,
                  gross_up: bool = False, default_nature: Optional[str] = None, note: Optional[str] = None,
                  clear: tuple = ()) -> SupplierTaxResidency:
    """Create or replace the supplier's tax residency. Secret identifiers (pan, tax_id, trc_no, form10f_ack) left out keep their stored value;
    name them in ``clear`` to remove them. Dates, flags and the nature are replaced as given. Audited with masked values only."""
    from app.pic.services import master_changes
    _require_editor(session)
    if len((reason or "").strip()) < 5:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for the tax residency change")
    residency, country, payee_type = (residency or "").upper(), (country or "").upper(), (payee_type or "COMPANY").upper()
    errors = []
    if residency not in RESIDENCIES:
        errors.append(f"residency is one of {', '.join(RESIDENCIES)}")
    if not COUNTRY.match(country):
        errors.append("country is a two-letter ISO code")
    elif residency == "NON_RESIDENT" and country == "IN":
        errors.append("a non-resident is resident in a country other than IN")
    elif residency == "RESIDENT" and country != "IN":
        errors.append("a resident supplier's country of residence is IN")
    if payee_type not in PAYEE_TYPES:
        errors.append(f"payee type is one of {', '.join(PAYEE_TYPES)}")
    pan = (pan or "").strip().upper() or None
    if pan:
        errors += master_changes.pan_errors(pan)
    for label, value in (("TRC number", trc_no), ("tax identification number", tax_id), ("Form 10F acknowledgement", form10f_ack)):
        if value is not None and not DOC_NO.match(value.strip().upper()):
            errors.append(f"the {label} is 4 to 40 letters, digits, spaces or / - .")
    if trc_valid_from and trc_valid_to and trc_valid_to < trc_valid_from:
        errors.append("the TRC is valid to a date before it starts")
    if form10f_valid_from and form10f_valid_to and form10f_valid_to < form10f_valid_from:
        errors.append("Form 10F covers a period that ends before it starts")
    if no_pe_valid_from and no_pe_valid_to and no_pe_valid_to < no_pe_valid_from:
        errors.append("the no-PE declaration is valid to a date before it starts")
    if trc_no and not (trc_valid_from and trc_valid_to):
        errors.append("a TRC needs its validity (from and to)")
    if form10f_ack and not (form10f_valid_from and form10f_valid_to and form10f_filed_on):
        errors.append("Form 10F needs its filing date and the period it covers")
    body, _ = rule(session, None)
    if default_nature and default_nature.upper() not in natures(body):
        errors.append(f"payment nature {default_nature} is not defined in rule TDS-195 ({', '.join(sorted(natures(body)))})")
    unknown = [c for c in clear if c not in ("pan", "tax_id", "trc_no", "form10f_ack")]
    if unknown:
        errors.append(f"only pan, tax_id, trc_no and form10f_ack can be cleared ({', '.join(unknown)})")
    if errors:
        raise Problem(422, "VALIDATION_FAILED", "; ".join(errors), rule_ref=KEY, errors=errors)
    row = residency_of(session, supplier.id)
    before = view(session, row, supplier) if row is not None else None
    if row is None:
        row = SupplierTaxResidency(tenant_id=current_tenant(session), supplier_id=supplier.id, residency=residency, country=country,
                                   created_by=principal(session).user_id)
        session.add(row)
    tid = supplier.tenant_id
    row.residency, row.country, row.payee_type = residency, country, payee_type
    for name, value, purpose, enc, masked in (("pan", pan, "tax-pan", "pan_enc", "pan_masked"),
                                              ("tax_id", tax_id, "tax-id", "tax_id_enc", "tax_id_masked"),
                                              ("trc_no", trc_no, "tax-trc", "trc_no_enc", "trc_masked"),
                                              ("form10f_ack", form10f_ack, "tax-10f", "form10f_ack_enc", "form10f_masked")):
        if name in clear:
            setattr(row, enc, None)
            setattr(row, masked, None)
        elif value:
            clean = value.strip().upper()
            setattr(row, enc, crypto.encrypt(tid, purpose, clean))
            setattr(row, masked, crypto.mask(clean))
    row.trc_valid_from, row.trc_valid_to, row.trc_document_ref = trc_valid_from, trc_valid_to, trc_document_ref
    row.form10f_filed_on, row.form10f_valid_from, row.form10f_valid_to = form10f_filed_on, form10f_valid_from, form10f_valid_to
    row.no_pe_declared, row.no_pe_valid_from, row.no_pe_valid_to = bool(no_pe_declared), no_pe_valid_from, no_pe_valid_to
    row.gross_up, row.default_nature, row.note = bool(gross_up), (default_nature or "").upper() or None, note
    if pan:
        supplier.pan_hash = crypto.blind_index(tid, pan)
    if residency == "NON_RESIDENT" and supplier.country != country:
        supplier.country = country
    session.flush()
    after = view(session, row, supplier)
    audit.record(session, "SUPPLIER", supplier.id, "TAX_RESIDENCY_CHANGED", object_ref=supplier.code, before=before, after=after, reason=reason,
                 rule_set_version=KEY)
    return row


def view(session: Session, row: Optional[SupplierTaxResidency], supplier: Supplier, on: Optional[date] = None) -> dict:
    """Masked view of the residency with the documents valid today (or on ``on``)."""
    if row is None:
        return {"supplier": supplier.code, "residency": None, "country": supplier.country}
    on = on or clock.today()
    have, why = documents_on(row, supplier, on)
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    return {"supplier": supplier.code, "residency": row.residency, "country": row.country, "payeeType": row.payee_type,
            "pan": row.pan_masked, "panOnFile": "PAN" in have, "taxId": row.tax_id_masked,
            "trc": {"number": row.trc_masked, "validFrom": iso(row.trc_valid_from), "validTo": iso(row.trc_valid_to), "documentRef": row.trc_document_ref},
            "form10f": {"acknowledgement": row.form10f_masked, "filedOn": iso(row.form10f_filed_on), "validFrom": iso(row.form10f_valid_from),
                        "validTo": iso(row.form10f_valid_to)},
            "noPe": {"declared": row.no_pe_declared, "validFrom": iso(row.no_pe_valid_from), "validTo": iso(row.no_pe_valid_to)},
            "grossUp": row.gross_up, "defaultNature": row.default_nature, "note": row.note,
            "documentsValid": sorted(have), "documentsMissing": why, "asOf": on.isoformat()}


# ================================================================ determination (pure)
def _by_payee(value, payee_type: str) -> Decimal:
    if isinstance(value, dict):
        found = value.get(payee_type, value.get("COMPANY"))
        if found is None:
            raise Problem(422, "TDS_195_RULE_INCOMPLETE", f"Rule TDS-195 has no Act rate for payee type {payee_type}", rule_ref=KEY)
        return _d(found)
    return _d(value)


def surcharge_pct(body: dict, payee_type: str, amount_inr_minor: int) -> Decimal:
    """The surcharge slab for the amount: the highest ``pct`` whose ``aboveMinor`` the amount exceeds (0 below every slab)."""
    pct = Decimal(0)
    for slab in sorted((body.get("surcharge") or {}).get(payee_type) or [], key=lambda s: int(s["aboveMinor"])):
        if amount_inr_minor > int(slab["aboveMinor"]):
            pct = _d(slab["pct"])
    return pct


def _treaty(body: dict, country: str, nature: str, docs: set, why: dict) -> tuple[Optional[dict], Optional[str]]:
    table = (body.get("dtaa") or {}).get(country)
    if not table:
        return None, f"rule TDS-195 has no treaty (DTAA) entry for {country}"
    entry = table.get(nature)
    if entry is None:
        return None, f"{table.get('label') or country} has no article for {nature}"
    if not isinstance(entry, dict):
        entry = {"ratePct": entry}
    missing = [d for d in list(body.get("treatyRequires") or []) + list(entry.get("requires") or []) if d not in docs]
    if missing:
        return None, "; ".join(why.get(d, f"{d} missing") for d in missing)
    return {"country": country, "label": table.get("label"), "article": entry.get("article"), "ratePct": _d(entry["ratePct"])}, None


def determine(body: dict, *, nature: str, country: str, payee_type: str, docs: set, why: Optional[dict] = None, base_inr_minor: int,
              gross_up: bool = False, certificate_rate: Optional[Decimal] = None) -> dict:
    """The s.195 rate for a payment of ``base_inr_minor`` (INR paise, before gross-up). Returns the effective rate (percent, 4 decimals), the basis
    (ACT | DTAA | NO_PAN_206AA | LOWER_DEDUCTION_CERTIFICATE), the breakdown and, with gross-up, the grossed-up base and the tax in INR."""
    why = why or {}
    spec = natures(body).get(nature)
    if spec is None:
        raise Problem(422, "TDS_195_NATURE_UNKNOWN", f"Payment nature {nature} is not defined in rule TDS-195 ({', '.join(sorted(natures(body)))})",
                      rule_ref=KEY)
    act_rate = _by_payee(spec.get("actRatePct"), payee_type)
    cess = _d(body.get("cessPct", 0))
    treaty, treaty_reason = _treaty(body, country, nature, docs, why)
    no_pan = "PAN" not in docs
    np_rule = body.get("noPan") or {}
    relief_rule = np_rule.get("relief") or {}
    relief = no_pan and nature in (relief_rule.get("natures") or []) and all(d in docs for d in relief_rule.get("requires") or [])
    relief_missing = [why.get(d, d) for d in relief_rule.get("requires") or [] if d not in docs] if no_pan else []

    def evaluate(amount: int) -> dict:
        surcharge = surcharge_pct(body, payee_type, amount)
        act_effective = (act_rate * (1 + surcharge / 100) * (1 + cess / 100)).quantize(PCT, ROUND_HALF_UP)
        treaty_effective = None
        if treaty is not None:
            treaty_effective = treaty["ratePct"].quantize(PCT) if body.get("treatyRateInclusive", True) else (
                treaty["ratePct"] * (1 + surcharge / 100) * (1 + cess / 100)).quantize(PCT, ROUND_HALF_UP)
        if certificate_rate is not None:
            rate, basis = _d(certificate_rate).quantize(PCT), "LOWER_DEDUCTION_CERTIFICATE"
        elif treaty_effective is not None and treaty_effective < act_effective:
            rate, basis = treaty_effective, "DTAA"
        else:
            rate, basis = act_effective, "ACT"
        if no_pan and not relief and certificate_rate is None:
            reference = rate if np_rule.get("treatyStillApplies") else act_effective
            rate, basis = max(_d(np_rule.get("ratePct", 20)), reference).quantize(PCT, ROUND_HALF_UP), "NO_PAN_206AA"
        return {"surchargePct": surcharge, "actEffectivePct": act_effective, "treatyEffectivePct": treaty_effective, "ratePct": rate, "basis": basis}

    outcome, amount = evaluate(base_inr_minor), base_inr_minor
    if gross_up:
        for _ in range(4):  # the surcharge slab depends on the grossed-up amount, which depends on the rate
            if outcome["ratePct"] >= 100:
                raise Problem(422, "TDS_195_RULE_INCOMPLETE", "A gross-up needs a rate below 100 %", rule_ref=KEY)
            amount = _money(Decimal(base_inr_minor) * 100 / (100 - outcome["ratePct"]))
            again = evaluate(amount)
            if again["ratePct"] == outcome["ratePct"]:
                break
            outcome = again if again["ratePct"] > outcome["ratePct"] else outcome
        amount = _money(Decimal(base_inr_minor) * 100 / (100 - outcome["ratePct"]))
    rounding = int(body.get("roundInrToMinor") or 1)
    tax_inr = (amount - base_inr_minor) if gross_up else _money(Decimal(base_inr_minor) * outcome["ratePct"] / 100)
    tax_inr = _money(Decimal(tax_inr) / rounding) * rounding
    return {"section": section_key(nature), "sectionLabel": body.get("sectionLabel") or "195", "act": body.get("act"), "nature": nature,
            "natureLabel": spec.get("label"), "actRef": spec.get("actRef"), "payeeType": payee_type, "country": country,
            "actRatePct": str(act_rate), "surchargePct": str(outcome["surchargePct"]), "cessPct": str(cess),
            "actEffectivePct": str(outcome["actEffectivePct"]),
            "treaty": ({**treaty, "ratePct": str(treaty["ratePct"]), "effectivePct": str(outcome["treatyEffectivePct"])} if treaty else None),
            "treatyUnavailable": treaty_reason, "noPan": no_pan, "noPanRelief": bool(relief),
            "noPanReliefMissing": relief_missing if no_pan and not relief else [],
            "noPanSection": np_rule.get("sectionLabel") or "206AA", "basis": outcome["basis"], "ratePct": str(outcome["ratePct"]),
            "grossUp": bool(gross_up), "baseInrMinor": base_inr_minor, "taxableInrMinor": amount, "taxInrMinor": tax_inr,
            "mock": bool(body.get("mock")), "returnForm": body.get("returnForm") or "27Q"}


# ================================================================ invoice context
def nature_for(invoice: Invoice, row: SupplierTaxResidency) -> Optional[str]:
    return invoice.tax_nature or nature_of_section(invoice.tds_section) or row.default_nature


def gross_up_for(session: Session, invoice: Invoice, row: SupplierTaxResidency) -> bool:
    """s.195A gross-up: the invoice's own setting, else the contract of its purchase order, else the supplier's."""
    if invoice.tax_gross_up is not None:
        return bool(invoice.tax_gross_up)
    if invoice.po_id:
        from app.pic.models import Contract
        po = session.get(PurchaseOrder, invoice.po_id)
        contract = session.get(Contract, po.contract_id) if po is not None and po.contract_id else None
        if contract is not None and contract.tax_gross_up is not None:
            return bool(contract.tax_gross_up)
    return bool(row.gross_up)


def fx_to_inr(session: Session, invoice: Invoice, on: date, body: dict) -> tuple[Decimal, date]:
    """(rate, rate date) converting the invoice currency to INR on the rule's rate date (PAYMENT_DATE: ``on``; INVOICE_DATE: the invoice date)."""
    currency = (invoice.currency or "INR").upper()
    if currency == "INR":
        return Decimal(1), on
    when = invoice.invoice_date if body.get("fxRateDate") == "INVOICE_DATE" else on
    from app.pic.services import spend_cube
    found = spend_cube._rate(session, currency, "INR", when)
    if found is None:
        raise Problem(409, "FX_RATE_MISSING", f"No {currency}->INR exchange rate is valid on {when.isoformat()}: load it before the s.195 tax is "
                      "determined", rule_ref=KEY)
    return Decimal(found[0]), found[1]


def _certificate(session: Session, invoice: Invoice, on: date, base_minor: int):
    from app.pic.services import finance_controls
    cert = finance_controls.valid_certificate(session, invoice.supplier_id, invoice.tds_section, on)
    if cert is None:
        return None
    if cert.max_base_minor is not None and int(cert.max_base_minor) - finance_controls.certificate_consumed(session, cert) < base_minor:
        return None  # a capped certificate is used only for a payment it covers in full (no split at the cap for s.195)
    return cert


def _determine_for(session: Session, invoice: Invoice, supplier: Supplier, row: SupplierTaxResidency, nature: str, base_minor: int,
                   on: date) -> tuple[dict, Decimal, date, Optional[object]]:
    body, ref = rule(session, invoice.company_code, on)
    fx, fx_date = fx_to_inr(session, invoice, on, body)
    base_inr = _money(Decimal(base_minor) * fx)
    docs, why = documents_on(row, supplier, on)
    cert = _certificate(session, invoice, on, base_minor)
    result = determine(body, nature=nature, country=row.country, payee_type=row.payee_type, docs=docs, why=why, base_inr_minor=base_inr,
                       gross_up=gross_up_for(session, invoice, row), certificate_rate=Decimal(cert.rate_pct) if cert is not None else None)
    result.update({"rule": ref, "fxRate": str(fx), "fxDate": fx_date.isoformat(), "currency": (invoice.currency or "INR").upper(),
                   "on": on.isoformat(), **({"certificate": cert.certificate_no} if cert is not None else {})})
    return result, fx, fx_date, cert


def posting_tds(session: Session, invoice: Invoice, supplier: Supplier) -> Optional[dict]:
    """Provisional s.195 determination at posting for an invoice of a non-resident (None for a resident): the section key, the rate on the
    posting date and the base (net of GST and credit notes). The payment run re-determines it on the payment date."""
    row = non_resident(session, supplier.id)
    if row is None:
        return None
    nature = nature_for(invoice, row)
    if not nature:
        raise Problem(422, "TDS_195_NATURE_REQUIRED", f"{supplier.code} is a non-resident: set the payment nature of invoice {invoice.number} "
                      "(PUT /v1/invoices/{ref}/withholding-195) or the supplier's default nature before posting", rule_ref=KEY)
    from app.pic.services import finance_controls
    base = max(int(invoice.net_minor) - finance_controls._credit_net(session, invoice), 0)
    result, fx, _, _ = _determine_for(session, invoice, supplier, row, nature, base, clock.today())
    rate = Decimal(result["ratePct"])
    tax = (_money(Decimal(base) * 100 / (100 - rate)) - base) if result["grossUp"] else _money(Decimal(base) * rate / 100)
    return {"section": section_key(nature), "label": result["natureLabel"], "ratePct": rate, "noPan": result["noPan"], "baseMinor": base,
            "taxableMinor": base, "tdsMinor": tax, "cumulativeMinor": base, "basis": result["basis"], "grossUp": result["grossUp"],
            "taxInrMinor": result["taxInrMinor"]}


def note_tds(invoice: Invoice, net_minor: int) -> dict:
    """TDS base of a debit note on a s.195 invoice: its whole net, at the invoice's provisional rate (re-determined at payment)."""
    rate = Decimal(invoice.tds_rate or 0)
    return {"section": invoice.tds_section, "ratePct": rate, "baseMinor": net_minor, "taxableMinor": net_minor,
            "tdsMinor": _money(Decimal(net_minor) * rate / 100), "cumulativeMinor": net_minor}


def payment_tax(session: Session, invoice: Invoice, notes: list, on: date, include_invoice: bool = True) -> dict:
    """The s.195 tax of one payment on ``on``: the payment_tds shape (tdsMinor in the invoice currency, ratePct, certificate, baseMinor,
    certBaseMinor) plus borneMinor (gross-up: tax the company bears, not deducted from the remittance), inrMinor / baseInrMinor and the detail."""
    from app.pic.services import finance_controls
    supplier = session.get(Supplier, invoice.supplier_id)
    row = residency_of(session, supplier.id)
    parts = []
    if include_invoice:
        late = finance_controls._credit_net(session, invoice, since=invoice.posted_at) if invoice.posted_at else 0
        parts.append(max(int(invoice.tds_base_minor or 0) - late, 0))
    parts += [int(n.tds_base_minor or 0) for n in notes]
    base = sum(parts)
    zero = {"tdsMinor": 0, "ratePct": invoice.tds_rate, "certificate": None, "baseMinor": 0, "certBaseMinor": 0, "borneMinor": 0,
            "inrMinor": 0, "baseInrMinor": 0, "detail": {}}
    if base <= 0:
        return zero
    if row is None or row.residency != "NON_RESIDENT":
        # the supplier was re-classified as resident after posting: keep the provisional rate fixed at posting (the tax team corrects it)
        tax = _money(Decimal(base) * Decimal(invoice.tds_rate or 0) / 100)
        return {**zero, "tdsMinor": tax, "baseMinor": base, "inrMinor": finance_controls.group_minor(invoice, tax),
                "baseInrMinor": finance_controls.group_minor(invoice, base), "detail": {"basis": "POSTING", "section": invoice.tds_section}}
    nature = nature_for(invoice, row)
    result, fx, _, cert = _determine_for(session, invoice, supplier, row, nature, base, on)
    rate = Decimal(result["ratePct"])
    if result["grossUp"]:
        grossed = _money(Decimal(base) * 100 / (100 - rate))
        tax, borne, taxable = grossed - base, grossed - base, grossed
    else:
        tax, borne, taxable = _money(Decimal(base) * rate / 100), 0, base
    return {"tdsMinor": tax, "ratePct": rate, "certificate": cert.certificate_no if cert is not None else None, "baseMinor": taxable,
            "certBaseMinor": base if cert is not None else 0, "borneMinor": borne, "inrMinor": result["taxInrMinor"],
            "baseInrMinor": result["taxableInrMinor"], "detail": result}


def invoice_preview(session: Session, invoice: Invoice, on: Optional[date] = None) -> dict:
    """What a payment of the invoice on ``on`` would withhold under s.195, with the Form 15CA / 15CB position."""
    supplier = session.get(Supplier, invoice.supplier_id)
    row = residency_of(session, supplier.id)
    on = on or clock.today()
    out = {"invoice": invoice.number, "supplier": supplier.code, "residency": view(session, row, supplier, on), "section": invoice.tds_section,
           "nature": invoice.tax_nature, "grossUpOverride": invoice.tax_gross_up, "on": on.isoformat(), "returnForm": return_form(invoice.tds_section),
           "forms": [form15_view(f) for f in forms_of(session, invoice)]}
    if row is None or row.residency != "NON_RESIDENT":
        return {**out, "applies": False}
    nature = nature_for(invoice, row)
    if not nature:
        return {**out, "applies": True, "determination": None, "problem": "no payment nature: set it on the invoice or as the supplier's default"}
    from app.pic.services import finance_controls
    base = int(invoice.tds_base_minor or 0) if is_195(invoice.tds_section) else max(int(invoice.net_minor) - finance_controls._credit_net(session, invoice), 0)
    result, _, _, _ = _determine_for(session, invoice, supplier, row, nature, base, on)
    rate = Decimal(result["ratePct"])
    tax = (_money(Decimal(base) * 100 / (100 - rate)) - base) if result["grossUp"] else _money(Decimal(base) * rate / 100)
    return {**out, "applies": True, "determination": {**result, "baseMinor": base, "taxMinor": tax}}


def set_invoice_tax(session: Session, invoice: Invoice, *, nature: Optional[str], gross_up: Optional[bool], reason: str) -> Invoice:
    """Payment nature and gross-up override of a non-resident invoice before it is paid; a posted invoice is re-determined at once."""
    if not principal(session).scopes & frozenset({"invoice:post", "payment:run"}):
        raise Problem(403, "FORBIDDEN", "The s.195 nature of an invoice is set by accounts payable or finance")
    if len((reason or "").strip()) < 5:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for the s.195 setting")
    supplier = session.get(Supplier, invoice.supplier_id)
    row = non_resident(session, supplier.id)
    if row is None:
        raise Problem(409, "NOT_NON_RESIDENT", f"{supplier.code} is not recorded as a non-resident (PUT /v1/suppliers/{supplier.code}/tax-residency)",
                      rule_ref=KEY)
    if invoice.paid_minor or invoice.payment_status != "UNPAID" or invoice.status in ("PAID", "REJECTED"):
        raise Problem(409, "ILLEGAL_TRANSITION", f"{invoice.number} is {invoice.status.lower()} / {(invoice.payment_status or '').lower()}: the s.195 "
                      "setting is fixed once a payment is made")
    body, _ = rule(session, invoice.company_code)
    nature = (nature or "").upper() or None
    if nature and nature not in natures(body):
        raise Problem(422, "TDS_195_NATURE_UNKNOWN", f"Payment nature {nature} is not defined in rule TDS-195 ({', '.join(sorted(natures(body)))})",
                      rule_ref=KEY)
    before = {"nature": invoice.tax_nature, "grossUp": invoice.tax_gross_up, "section": invoice.tds_section, "ratePct": str(invoice.tds_rate) if invoice.tds_rate else None}
    invoice.tax_nature, invoice.tax_gross_up = nature, gross_up
    if invoice.status == "POSTED":
        tds = posting_tds(session, invoice, supplier)
        invoice.tds_section, invoice.tds_rate, invoice.tds_base_minor, invoice.withholding_tax_minor = (
            tds["section"], tds["ratePct"], tds["taxableMinor"], tds["tdsMinor"])
    audit.record(session, "INVOICE", invoice.id, "TDS_195_SET", object_ref=invoice.number, before=before, reason=reason, rule_set_version=KEY,
                 after={"nature": nature, "grossUp": gross_up, "section": invoice.tds_section, "ratePct": str(invoice.tds_rate) if invoice.tds_rate else None})
    return invoice


# ================================================================ Form 15CA / 15CB
def forms_of(session: Session, invoice: Invoice) -> list[RemittanceCertificate]:
    return session.execute(select(RemittanceCertificate).where(RemittanceCertificate.invoice_id == invoice.id)
                           .order_by(RemittanceCertificate.created_at)).scalars().all()


def form15_view(row: RemittanceCertificate) -> dict:
    return {"id": str(row.id), "part": row.form15ca_part, "acknowledgement": row.form15ca_ack_masked, "filedOn": row.form15ca_filed_on.isoformat(),
            "amountMinor": row.amount_minor, "currency": row.currency, "form15cb": ({"certificateNo": row.form15cb_certificate_no,
            "date": row.form15cb_date.isoformat() if row.form15cb_date else None, "caName": row.ca_name, "membershipNo": row.ca_membership_no}
            if row.form15cb_certificate_no else None), "status": row.status, "payment": str(row.payment_id) if row.payment_id else None,
            "voidReason": row.void_reason, "note": row.note}


def form15_requirement(session: Session, invoice: Invoice, amount_minor: int, on: date, nature: Optional[str]) -> dict:
    """Whether a remittance of ``amount_minor`` (invoice currency) on ``on`` needs Form 15CA and Form 15CB under rule TDS-195.form15."""
    body, ref = rule(session, invoice.company_code, on)
    spec = body.get("form15") or {}
    if not spec.get("caRequired", True) or (nature and nature in (spec.get("notRequiredForNatures") or [])):
        return {"required": False, "cbRequired": False, "rule": ref}
    fx, _ = fx_to_inr(session, invoice, on, body)
    amount_inr = _money(Decimal(amount_minor) * fx)
    counted = amount_inr
    if spec.get("cbBasis", "FISCAL_YEAR_AGGREGATE") == "FISCAL_YEAR_AGGREGATE":
        from app.pic.services import finance_controls
        first, last = finance_controls.fiscal_year_range(clock.fiscal_year(on))
        counted += int(session.execute(select(func.coalesce(func.sum(func.coalesce(Payment.amount_group_minor, Payment.amount_minor)), 0)).where(
            Payment.supplier_id == invoice.supplier_id, Payment.status != "CANCELLED", Payment.value_date >= first, Payment.value_date <= last)).scalar() or 0)
    threshold = spec.get("cbAboveMinor")
    cb = threshold is not None and counted > int(threshold)
    return {"required": True, "cbRequired": cb, "amountInrMinor": amount_inr, "countedInrMinor": counted, "cbAboveMinor": threshold,
            "expectedPart": "C" if cb else "A", "rule": ref}


def form15_for(session: Session, invoice: Invoice, amount_minor: int, on: date, nature: Optional[str]) -> tuple[Optional[RemittanceCertificate], Optional[dict]]:
    """The recorded, unused Form 15CA (and 15CB) that covers a remittance, or (None, problem) with the code and detail of what is missing."""
    need = form15_requirement(session, invoice, amount_minor, on, nature)
    if not need["required"]:
        return None, None
    currency = (invoice.currency or "INR").upper()
    candidates = [f for f in forms_of(session, invoice) if f.status == "RECORDED" and f.currency == currency and f.amount_minor >= amount_minor
                  and f.form15ca_filed_on <= on]
    if not candidates:
        return None, {"code": "FORM_15CA_REQUIRED", "detail": f"{invoice.number}: a remittance of {amount_minor / 100:,.2f} {currency} to a non-resident "
                      f"needs a Form 15CA acknowledgement filed on or before {on.isoformat()} covering it: record it with POST /v1/invoices/"
                      f"{invoice.number}/form15 before the payment is released", "rule": need["rule"]}
    candidates.sort(key=lambda f: (f.amount_minor, f.created_at))
    with_cb = [f for f in candidates if f.form15cb_certificate_no]
    if need["cbRequired"] and not with_cb:
        return None, {"code": "FORM_15CB_REQUIRED", "detail": f"{invoice.number}: the remittances to the supplier this fiscal year reach "
                      f"INR {need['countedInrMinor'] / 100:,.2f}, above the Form 15CB threshold of INR {int(need['cbAboveMinor']) / 100:,.2f}: record the "
                      "chartered accountant's Form 15CB certificate with the Form 15CA (part C)", "rule": need["rule"]}
    return (with_cb if need["cbRequired"] else candidates)[0], None


def use_form15(session: Session, form: RemittanceCertificate, payment: Payment) -> None:
    form.status, form.payment_id = "USED", payment.id
    audit.record(session, "INVOICE", form.invoice_id, "FORM_15CA_USED", object_ref=payment.number,
                 after={"payment": payment.number, "acknowledgement": form.form15ca_ack_masked, "amountMinor": payment.amount_minor})


def release_form15(session: Session, payment: Payment) -> None:
    """A returned remittance frees its Form 15CA for the next attempt (the same remittance is made again)."""
    for form in session.execute(select(RemittanceCertificate).where(RemittanceCertificate.payment_id == payment.id,
                                                                     RemittanceCertificate.status == "USED")).scalars():
        form.status, form.payment_id = "RECORDED", None
        audit.record(session, "INVOICE", form.invoice_id, "FORM_15CA_RELEASED", object_ref=payment.number,
                     after={"payment": payment.number, "acknowledgement": form.form15ca_ack_masked}, reason="payment returned by the bank")


def record_form15(session: Session, invoice: Invoice, *, part: str, acknowledgement: str, filed_on: date, amount_minor: int,
                  form15cb_certificate_no: Optional[str] = None, form15cb_date: Optional[date] = None, ca_name: Optional[str] = None,
                  ca_membership_no: Optional[str] = None, note: Optional[str] = None) -> RemittanceCertificate:
    p = principal(session)
    if "payment:run" not in p.scopes:
        raise Problem(403, "FORBIDDEN", "Form 15CA / 15CB filings are recorded by finance (permission payment:run)")
    supplier = session.get(Supplier, invoice.supplier_id)
    if non_resident(session, supplier.id) is None:
        raise Problem(409, "NOT_NON_RESIDENT", f"{supplier.code} is not recorded as a non-resident: no Form 15CA is needed", rule_ref=KEY)
    if invoice.status not in ("APPROVED", "POSTED") or invoice.payment_status == "PAID":
        raise Problem(409, "ILLEGAL_TRANSITION", f"{invoice.number} is {invoice.status.lower()}: Form 15CA is recorded for an approved or posted, "
                      "unpaid invoice")
    ack = (acknowledgement or "").strip().upper()
    errors = []
    if (part or "").upper() not in ("A", "B", "C", "D"):
        errors.append("Form 15CA part is A, B, C or D")
    if not ACK.match(ack):
        errors.append("the Form 15CA acknowledgement number is 8 to 20 letters or digits")
    if filed_on > clock.today():
        errors.append("Form 15CA cannot be filed in the future")
    if amount_minor <= 0:
        errors.append("the remittance amount must be positive")
    if form15cb_certificate_no:
        if not UDIN.match(form15cb_certificate_no.strip().upper()):
            errors.append("the Form 15CB certificate number (UDIN) is 6 to 40 letters or digits")
        if not form15cb_date or not (ca_name or "").strip() or not MEMBERSHIP.match((ca_membership_no or "").strip()):
            errors.append("Form 15CB needs its date, the chartered accountant's name and six-digit membership number")
        elif form15cb_date > filed_on:
            errors.append("Form 15CB is certified before Form 15CA is filed")
    elif (part or "").upper() == "C":
        errors.append("Form 15CA part C is filed with the chartered accountant's Form 15CB")
    if errors:
        raise Problem(422, "VALIDATION_FAILED", "; ".join(errors), rule_ref=KEY, errors=errors)
    digest = crypto.blind_index(invoice.tenant_id, ack)
    if session.execute(select(RemittanceCertificate.id).where(RemittanceCertificate.form15ca_ack_hash == digest)).first():
        raise Problem(409, "DUPLICATE_FORM15CA", f"Form 15CA acknowledgement {crypto.mask(ack)} is already recorded")
    row = RemittanceCertificate(tenant_id=invoice.tenant_id, invoice_id=invoice.id, supplier_id=supplier.id, form15ca_part=part.upper(),
                                form15ca_ack_enc=crypto.encrypt(invoice.tenant_id, "tax-15ca", ack), form15ca_ack_masked=crypto.mask(ack),
                                form15ca_ack_hash=digest, form15ca_filed_on=filed_on, amount_minor=amount_minor, currency=(invoice.currency or "INR").upper(),
                                form15cb_certificate_no=(form15cb_certificate_no or "").strip().upper() or None, form15cb_date=form15cb_date,
                                ca_name=(ca_name or "").strip() or None, ca_membership_no=(ca_membership_no or "").strip() or None, status="RECORDED",
                                note=note, created_by=p.user_id)
    session.add(row)
    session.flush()
    payload = {"invoice": invoice.number, "supplier": supplier.code, "part": row.form15ca_part, "amountMinor": amount_minor, "currency": row.currency,
               "form15cb": row.form15cb_certificate_no is not None}
    audit.record(session, "INVOICE", invoice.id, "FORM_15CA_RECORDED", object_ref=invoice.number, reason=note,
                 after={**payload, "acknowledgement": row.form15ca_ack_masked, "filedOn": filed_on.isoformat()})
    outbox.emit(session, "remittance.form15.recorded", "INVOICE", invoice.id, invoice.number, payload)
    return row


def void_form15(session: Session, invoice: Invoice, form_id, reason: str) -> RemittanceCertificate:
    if "payment:run" not in principal(session).scopes:
        raise Problem(403, "FORBIDDEN", "Form 15CA filings are voided by finance")
    if len((reason or "").strip()) < 5:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for voiding the Form 15CA record")
    row = session.execute(select(RemittanceCertificate).where(RemittanceCertificate.id == form_id, RemittanceCertificate.invoice_id == invoice.id)
                          .with_for_update()).scalar_one_or_none()
    if row is None:
        raise not_found("Form 15CA record", form_id)
    if row.status != "RECORDED":
        raise Problem(409, "ILLEGAL_TRANSITION", f"The Form 15CA record is {row.status.lower()}: only an unused one can be voided")
    row.status, row.void_reason = "VOID", reason
    audit.record(session, "INVOICE", invoice.id, "FORM_15CA_VOIDED", object_ref=invoice.number, reason=reason,
                 after={"acknowledgement": row.form15ca_ack_masked})
    return row
