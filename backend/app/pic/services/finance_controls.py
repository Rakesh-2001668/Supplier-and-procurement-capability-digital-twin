"""M10 finance controls that sit around the match: duplicate variants, the MSME 45-day rule, TDS, foreign-currency invoices and
posting periods (period close / cut-off). Rule bodies are tenant data (rule sets MSME, TDS) with the defaults below when a tenant
has none; every default is a starting point for the tenant's tax and treasury team to confirm, not legal advice.
"""
import re
import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (CompanyCode, CreditNote, GoodsReceipt, GrLine, Invoice, InvoiceLine, PoLine, PostingPeriod, ServiceEntry, SesLine,
                            Supplier)
from app.pic.platform import audit, clock, finance_defaults, outbox, rules
from app.pic.platform.errors import Problem
from app.pic.services.common import principal

# ---------------------------------------------------------------- encrypted supplier fields
def supplier_gstin(session: Session, supplier: Supplier) -> str:
    """The supplier's GSTIN, decrypted. A key that cannot open it (PIC_FIELD_KEY differs from the one the data was written under) is a clear 503
    problem, audited once per supplier, never a bare 500 and never the ciphertext."""
    if not supplier.gstin_enc:
        return ""
    from app.pic.platform import crypto
    try:
        return crypto.decrypt(supplier.tenant_id, "gstin", supplier.gstin_enc)
    except Exception:  # noqa: BLE001 - InvalidToken or an unknown key id: the stored value cannot be opened with this configuration
        _audit_key_mismatch(session, supplier)
        raise Problem(503, "FIELD_KEY_MISMATCH", f"The encrypted GSTIN of supplier {supplier.code} cannot be read with the configured PIC_FIELD_KEY: it differs from "
                      "the key the data was encrypted with. Restore the original key (or re-encrypt with tools/reencrypt.py); no data was changed", rule_ref="SEC-FIELD")


def _audit_key_mismatch(session: Session, supplier: Supplier) -> None:
    from app.pic.db import tenant_tx
    from app.pic.models import AuditEvent
    p = session.info.get("principal")
    if p is None:
        return
    try:
        with tenant_tx(p.tenant_id, p.user_id, p) as s:
            s.execute(text("SET LOCAL lock_timeout = '1500ms'"))
            if s.execute(select(AuditEvent.seq).where(AuditEvent.object_type == "SUPPLIER", AuditEvent.object_id == supplier.id,
                                                      AuditEvent.action == "FIELD_KEY_MISMATCH").limit(1)).first() is None:
                audit.record(s, "SUPPLIER", supplier.id, "FIELD_KEY_MISMATCH", object_ref=supplier.code, after={"field": "gstin"},
                             reason="encrypted field cannot be read with the configured PIC_FIELD_KEY")
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- duplicate variants (OCR / formatting)
_OCR = str.maketrans({"O": "0", "I": "1", "L": "1"})


def normalise_invoice_no(number: str) -> str:
    """A supplier invoice number as OCR and re-keying garble it: upper case, separators and spaces dropped, look-alike letters
    (O/0, I/L/1) folded, leading zeros of a numeric run dropped. ``INV-0012``, ``inv 12`` and ``INVO12`` share one key."""
    folded = re.sub(r"[^A-Z0-9]", "", (number or "").upper()).translate(_OCR)
    return re.sub(r"(?<![0-9])0+(?=[0-9])", "", folded)


def number_variant_of(session: Session, invoice: Invoice, window_days: int = 400) -> Optional[Invoice]:
    """Another invoice of the supplier whose number normalises to the same key (but is not the exact same number: the exact key is
    the hard 409 at capture)."""
    key = normalise_invoice_no(invoice.supplier_invoice_no)
    if not key:
        return None
    window = timedelta(days=window_days)
    others = session.execute(select(Invoice).where(
        Invoice.supplier_id == invoice.supplier_id, Invoice.id != invoice.id, Invoice.status != "REJECTED",
        func.coalesce(Invoice.match_type, "") != "RETENTION", Invoice.channel != "ERS",
        Invoice.invoice_date.between(invoice.invoice_date - window, invoice.invoice_date + window)).order_by(Invoice.created_at).limit(5000)).scalars()
    for other in others:
        if normalise_invoice_no(other.supplier_invoice_no) == key:
            return other
    return None


# ---------------------------------------------------------------- rule defaults
MSME_DEFAULT, TDS_DEFAULT = finance_defaults.MSME_DEFAULT, finance_defaults.TDS_DEFAULT


def rule_body(session: Session, key: str, default: dict, **scope) -> dict:
    try:
        return rules.resolve(session, key, **scope).body
    except Problem:
        return default


# ---------------------------------------------------------------- MSME 45-day rule
def acceptance_date(session: Session, invoice: Invoice) -> date:
    """The day the goods / services were accepted (MSMED Act s.15 starts its clock there, not at the invoice date): the latest posted
    goods receipt or approved service entry on the invoice's order lines that is not after the invoice date; the invoice date without one."""
    line_ids = [l.po_line_id for l in session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)).scalars() if l.po_line_id]
    if not line_ids:
        return invoice.invoice_date
    goods = session.execute(select(func.max(GoodsReceipt.posting_date)).select_from(GrLine).join(GoodsReceipt, GoodsReceipt.id == GrLine.gr_id).where(
        GrLine.po_line_id.in_(line_ids), GoodsReceipt.status != "REVERSED", GoodsReceipt.reversal_of.is_(None),
        GoodsReceipt.posting_date <= invoice.invoice_date)).scalar()
    services = session.execute(select(func.max(ServiceEntry.period_to)).select_from(SesLine).join(ServiceEntry, ServiceEntry.id == SesLine.ses_id).where(
        SesLine.po_line_id.in_(line_ids), ServiceEntry.status == "APPROVED", ServiceEntry.period_to <= invoice.invoice_date)).scalar()
    dates = [d for d in (goods, services) if d]
    return max(dates) if dates else invoice.invoice_date


def is_msme(session: Session, supplier: Supplier) -> bool:
    body = rule_body(session, "MSME", MSME_DEFAULT)
    return (supplier.msme_class or "").upper() in [c.upper() for c in body.get("classes", MSME_DEFAULT["classes"])]


def due_date(session: Session, invoice: Invoice, terms_days: int) -> tuple[date, bool, date]:
    """(due date, MSME cap applied, acceptance date). The contractual due date (invoice date + net days) is pulled forward to acceptance
    + 45 days for a micro / small enterprise supplier."""
    contractual = invoice.invoice_date + timedelta(days=terms_days)
    accepted = acceptance_date(session, invoice)
    supplier = session.get(Supplier, invoice.supplier_id)
    if supplier is None or not is_msme(session, supplier):
        return contractual, False, accepted
    body = rule_body(session, "MSME", MSME_DEFAULT)
    # s.15(1): within the agreed period, at most 45 days from acceptance; without a written agreement within 15 days of acceptance.
    days = int(body.get("maxDays", 45)) if supplier.msme_written_agreement is not False else int(body.get("noAgreementDays", 15))
    cap = accepted + timedelta(days=days)
    return (cap, True, accepted) if cap < contractual else (contractual, False, accepted)


def accrue_msme_interest(session: Session, payment, invoice: Invoice, supplier: Supplier, interest_minor: Optional[int], paid_on: date):
    """Record the interest owed on a late payment to an MSME supplier (MSMED Act s.16) when the tenant publishes the bank rate: one MsmeInterest
    row per payment, an audit event and msme.interest.accrued. None without a rate or when the payment is not late."""
    from app.pic.models import MsmeInterest
    if not interest_minor or interest_minor <= 0 or invoice.due_date is None or paid_on <= invoice.due_date:
        return None
    body = rule_body(session, "MSME", MSME_DEFAULT)
    rate = Decimal(str(body["bankRatePct"])) * Decimal(str(body.get("interestMultiple", 3)))
    row = MsmeInterest(tenant_id=invoice.tenant_id, invoice_id=invoice.id, payment_id=payment.id, supplier_id=supplier.id, company_code=invoice.company_code,
                       due_date=invoice.due_date, paid_on=paid_on, days_late=(paid_on - invoice.due_date).days, principal_minor=payment.amount_minor,
                       rate_pct=rate, interest_minor=interest_minor, status="ACCRUED", created_by=principal(session).user_id)
    session.add(row)
    session.flush()
    audit.record(session, "INVOICE", invoice.id, "MSME_INTEREST_ACCRUED", object_ref=invoice.number,
                 after={"payment": payment.number, "dueDate": invoice.due_date.isoformat(), "paidOn": paid_on.isoformat(), "daysLate": row.days_late,
                        "interestMinor": interest_minor, "ratePct": str(rate)}, reason="MSMED Act s.16: interest on delayed payment")
    outbox.emit(session, "msme.interest.accrued", "INVOICE", invoice.id, invoice.number,
                {"supplier": supplier.code, "payment": payment.number, "interestMinor": interest_minor, "daysLate": row.days_late})
    return row


def msme_interest_register(session: Session, supplier: Optional[str] = None, company_codes: Optional[list[str]] = None) -> dict:
    from app.pic.models import MsmeInterest
    query = select(MsmeInterest, Supplier, Invoice).join(Supplier, Supplier.id == MsmeInterest.supplier_id).join(Invoice, Invoice.id == MsmeInterest.invoice_id)
    if supplier:
        query = query.where(Supplier.code == supplier)
    if company_codes is not None:
        query = query.where(MsmeInterest.company_code.in_(company_codes))
    items = [{"id": str(r.id), "supplier": s.code, "invoice": i.number, "dueDate": r.due_date.isoformat(), "paidOn": r.paid_on.isoformat(), "daysLate": r.days_late,
              "principalMinor": r.principal_minor, "ratePct": str(r.rate_pct), "interestMinor": r.interest_minor, "status": r.status}
             for r, s, i in session.execute(query.order_by(MsmeInterest.paid_on.desc()).limit(500)).all()]
    return {"items": items, "totalMinor": sum(x["interestMinor"] for x in items if x["status"] == "ACCRUED")}


def msme_interest_minor(session: Session, amount_minor: int, due: date, paid_on: date) -> Optional[int]:
    """Interest owed on an overdue MSME payment: compounded monthly at ``interestMultiple`` x the bank rate (rule MSME.bankRatePct);
    None until the tenant publishes the bank rate."""
    body = rule_body(session, "MSME", MSME_DEFAULT)
    rate = body.get("bankRatePct")
    if rate is None or paid_on <= due:
        return 0 if rate is not None else None
    monthly = Decimal(str(rate)) * Decimal(str(body.get("interestMultiple", 3))) / 100 / 12
    months = Decimal((paid_on - due).days) / Decimal(30)
    factor = (1 + monthly) ** months
    return int((Decimal(amount_minor) * (factor - 1)).quantize(Decimal(1), ROUND_HALF_UP))


# ---------------------------------------------------------------- TDS
def _credit_net(session: Session, invoice: Invoice, since=None) -> int:
    query = select(func.coalesce(func.sum(CreditNote.net_minor), 0)).where(CreditNote.invoice_id == invoice.id)
    if since is not None:
        query = query.where(CreditNote.created_at >= since)
    return int(session.execute(query).scalar() or 0)


def _prior(session: Session, supplier: Supplier, section: str, fiscal_year: str, *, exclude_invoice=None, exclude_note=None) -> tuple[int, int]:
    """(taxable value, value already taxed) of the supplier's posted invoices and posted debit notes of this section in the fiscal year."""
    from app.pic.models import DebitNote
    invoices = select(func.coalesce(func.sum(Invoice.net_minor), 0), func.coalesce(func.sum(Invoice.tds_base_minor), 0)).where(
        Invoice.supplier_id == supplier.id, Invoice.fiscal_year == fiscal_year, Invoice.tds_section == section, Invoice.status.in_(("POSTED", "PAID")))
    if exclude_invoice is not None:
        invoices = invoices.where(Invoice.id != exclude_invoice)
    total, taxed = session.execute(invoices).one()
    notes = select(func.coalesce(func.sum(DebitNote.net_minor), 0), func.coalesce(func.sum(DebitNote.tds_base_minor), 0)).where(
        DebitNote.supplier_id == supplier.id, DebitNote.status == "POSTED",
        DebitNote.invoice_id.in_(select(Invoice.id).where(Invoice.fiscal_year == fiscal_year, Invoice.tds_section == section)))
    if exclude_note is not None:
        notes = notes.where(DebitNote.id != exclude_note)
    note_total, note_taxed = session.execute(notes).one()
    return int(total) + int(note_total), int(taxed) + int(note_taxed)


def _determine(spec: dict, base: int, prior_total: int, prior_taxed: int, rate: Decimal) -> dict:
    cumulative = prior_total + base
    single, annual = spec.get("singleThresholdMinor"), spec.get("annualThresholdMinor")
    if spec.get("excessOnly"):
        taxable_cumulative = max(cumulative - int(annual or 0), 0)
    elif annual is not None and cumulative > int(annual):
        taxable_cumulative = cumulative
    elif single is not None and base > int(single):
        taxable_cumulative = prior_taxed + base
    elif single is None and annual is None:
        taxable_cumulative = prior_taxed + base
    else:
        taxable_cumulative = 0
    taxable = max(taxable_cumulative - prior_taxed, 0)
    tds = int((Decimal(taxable) * rate / 100).quantize(Decimal(1), ROUND_HALF_UP))
    return {"baseMinor": base, "taxableMinor": taxable, "tdsMinor": tds, "cumulativeMinor": cumulative}


def _section_spec(session: Session, supplier: Supplier, section: str, company_code: str) -> tuple[dict, Decimal, bool, dict]:
    body = rule_body(session, "TDS", TDS_DEFAULT, company_code=company_code)
    spec = (body.get("sections") or {}).get(section)
    if spec is None:
        raise Problem(422, "TDS_SECTION_UNKNOWN", f"Supplier {supplier.code} has TDS section {section}, which rule set TDS does not define: "
                      "correct the supplier master or publish the section", rule_ref="TDS")
    rate = Decimal(str(spec["ratePct"]))
    no_pan = supplier.pan_hash is None
    if no_pan:
        rate = max(rate, Decimal(str(body.get("noPanRatePct", 20))))
    return spec, rate, no_pan, body


def compute_tds(session: Session, invoice: Invoice, supplier: Supplier) -> dict:
    """TDS the payment of this invoice keeps back, from the supplier's section: ``rate`` on the taxable base (net of GST and credit
    notes), nothing below the single-payment / annual threshold, the whole cumulative base once an annual threshold is crossed (earlier
    untaxed payments are caught up), the higher no-PAN rate when the supplier has no PAN. Returns {} when the supplier has no section
    (or the invoice already carries the withholding migrated from the ERP). A valid s.197 certificate is applied at payment, not here."""
    if invoice.tds_section is None and (invoice.withholding_tax_minor or 0) > 0:
        return {}
    if (getattr(supplier, "country", None) or "IN").upper() != "IN":  # set_residency keeps a non-resident's country outside IN
        from app.pic.services import nonresident_tax
        nr = nonresident_tax.posting_tds(session, invoice, supplier)  # a non-resident supplier: section 195 instead of the resident sections
        if nr is not None:
            return nr
    section = (supplier.tds_section or "").strip()
    if not section:
        return {}
    spec, rate, no_pan, _ = _section_spec(session, supplier, section, invoice.company_code)
    base = max(invoice.net_minor - _credit_net(session, invoice) - advance_taxed_minor(session, invoice), 0)
    prior_total, prior_taxed = _prior(session, supplier, section, invoice.fiscal_year, exclude_invoice=invoice.id)
    return {"section": section, "label": spec.get("label"), "ratePct": rate, "noPan": no_pan,
            **_determine(spec, base, prior_total, prior_taxed, rate)}


def tcs_spec(session: Session, company_code: str) -> dict:
    return rule_body(session, "TDS", TDS_DEFAULT, company_code=company_code).get("tcs") or {}


def compute_tcs(session: Session, invoice: Invoice, supplier: Supplier) -> dict:
    """TCS the supplier collects on this invoice (rule TDS.tcs, off by default): ``ratePct`` of the gross value, only on the part of the supplier's
    cumulative gross in the fiscal year that is above ``annualThresholdMinor`` when one is set. {} when the rule is off or nothing is taxable."""
    spec = tcs_spec(session, invoice.company_code)
    if not spec.get("enabled"):
        return {}
    rate = Decimal(str(spec.get("ratePct", 1)))
    threshold = spec.get("annualThresholdMinor")
    gross = int(invoice.gross_minor)
    if threshold is None:
        taxable = gross
    else:
        prior = int(session.execute(select(func.coalesce(func.sum(Invoice.gross_minor), 0)).where(
            Invoice.supplier_id == supplier.id, Invoice.fiscal_year == invoice.fiscal_year, Invoice.id != invoice.id, Invoice.status.in_(("POSTED", "PAID")),
            func.coalesce(Invoice.match_type, "").notin_(("RETENTION", "ERS")))).scalar() or 0)
        taxable = max(prior + gross - int(threshold), 0) - max(prior - int(threshold), 0)
    tcs = int((Decimal(taxable) * rate / 100).quantize(Decimal(1), ROUND_HALF_UP))
    if tcs <= 0:
        return {}
    return {"section": spec.get("section") or "206C(1H)", "ratePct": rate, "baseMinor": taxable, "tcsMinor": tcs}


def tcs_payable(session: Session, invoice: Invoice) -> bool:
    """Whether the TCS of the invoice is paid to the supplier with it (rule TDS.tcs.addToPayable); otherwise it is only carried to the ERP posting."""
    return bool(invoice.tcs_minor) and bool(tcs_spec(session, invoice.company_code).get("addToPayable"))


def advance_taxed_minor(session: Session, invoice: Invoice) -> int:
    """Base of this running bill on which TDS was already deducted when the advance was paid: the advance recovered from the bill (net of GST) times
    the share of the advance document that was taxed. The bill's TDS is on its value less that amount (D30: the recovered advance was taxed twice)."""
    from app.pic.models import AdvancePayment, AdvanceRecovery
    total = Decimal(0)
    for recovery, advance, document in session.execute(
            select(AdvanceRecovery, AdvancePayment, Invoice).join(AdvancePayment, AdvancePayment.id == AdvanceRecovery.advance_id)
            .join(Invoice, Invoice.id == AdvancePayment.invoice_id)
            .where(AdvanceRecovery.invoice_id == invoice.id, AdvanceRecovery.status.in_(("PLANNED", "APPLIED")))).all():
        if not advance.gross_minor or not advance.net_minor:
            continue
        net_share = Decimal(recovery.amount_minor) * Decimal(advance.net_minor) / Decimal(advance.gross_minor)
        taxed_share = min(Decimal(document.tds_base_minor or 0) / Decimal(advance.net_minor), Decimal(1))
        total += net_share * taxed_share
    return int(total.quantize(Decimal(1), ROUND_HALF_UP))


def compute_note_tds(session: Session, invoice: Invoice, note) -> dict:
    """TDS on the additional taxable value of a supplier debit note (price correction or charge), net of GST, under the section and rate of its
    invoice; thresholds count the supplier's invoices and earlier debit notes of the section in the fiscal year. {} when the invoice carries no TDS section."""
    if not invoice.tds_section or invoice.tds_rate is None:
        return {}
    from app.pic.services import nonresident_tax
    if nonresident_tax.is_195(invoice.tds_section):
        return nonresident_tax.note_tds(invoice, int(note.net_minor))
    supplier = session.get(Supplier, invoice.supplier_id)
    spec, _, _, _ = _section_spec(session, supplier, invoice.tds_section, invoice.company_code)
    prior_total, prior_taxed = _prior(session, supplier, invoice.tds_section, invoice.fiscal_year, exclude_note=note.id)
    return {"section": invoice.tds_section, "ratePct": Decimal(invoice.tds_rate),
            **_determine(spec, int(note.net_minor), prior_total, prior_taxed, Decimal(invoice.tds_rate))}


# ---------------------------------------------------------------- s.197 lower-deduction certificates
def valid_certificate(session: Session, supplier_id, section: Optional[str], on: date):
    """The ACTIVE certificate valid on ``on`` for the supplier (and the section, or any section) with the lowest rate; None without one."""
    from app.pic.models import TdsCertificate
    rows = session.execute(select(TdsCertificate).where(
        TdsCertificate.supplier_id == supplier_id, TdsCertificate.status == "ACTIVE", TdsCertificate.valid_from <= on, TdsCertificate.valid_to >= on)
        .order_by(TdsCertificate.rate_pct, TdsCertificate.certificate_no)).scalars().all()
    for cert in rows:
        if cert.section is None or cert.section == section:
            return cert
    return None


def certificate_consumed(session: Session, cert) -> int:
    """Base already taxed at the certificate's rate on live payments (counts against its amount cap)."""
    from app.pic.models import Payment
    return int(session.execute(select(func.coalesce(func.sum(Payment.tds_cert_base_minor), 0)).where(
        Payment.supplier_id == cert.supplier_id, Payment.tds_certificate == cert.certificate_no, Payment.status != "CANCELLED")).scalar() or 0)


def payment_tds(session: Session, invoice: Invoice, notes: Optional[list] = None, on: Optional[date] = None, used: Optional[dict] = None,
                include_invoice: bool = True) -> dict:
    """TDS to keep back from one payment: the invoice base fixed at posting (reduced for credit notes that arrived after posting) plus the TDS base of
    the debit notes netted into it, at the rate of a valid s.197 certificate on the payment date. A certificate with an amount cap (``max_base_minor``)
    applies its rate only to the base left under the cap (consumed by earlier live payments, plus ``used`` for the payments of the same proposal);
    the rest is taxed at the section rate fixed at posting. Migrated withholding without a section is kept as it is.
    Returns tdsMinor, baseMinor (invoice + notes), certBaseMinor (taxed at the certificate rate), ratePct (the certificate rate, the section rate, or
    the blended rate when the cap splits the payment), certificate (number, only when it was used)."""
    notes = notes or []
    from app.pic.services import nonresident_tax
    if nonresident_tax.is_195(invoice.tds_section):  # section 195: re-determined on the payment date (treaty documents, FX, gross-up)
        return nonresident_tax.payment_tax(session, invoice, notes, on or clock.today(), include_invoice=include_invoice)
    if not invoice.tds_section or invoice.tds_rate is None:
        legacy = max(int(invoice.withholding_tax_minor or 0), 0) if include_invoice else 0
        return {"tdsMinor": legacy, "ratePct": None, "certificate": None, "baseMinor": 0, "certBaseMinor": 0}
    parts = []
    if include_invoice:
        late = _credit_net(session, invoice, since=invoice.posted_at) if invoice.posted_at else 0
        parts.append(max(int(invoice.tds_base_minor or 0) - late, 0))
    parts += [int(n.tds_base_minor or 0) for n in notes]
    cert = valid_certificate(session, invoice.supplier_id, invoice.tds_section, on or clock.today())
    normal = Decimal(invoice.tds_rate)
    remaining = None
    if cert is not None and cert.max_base_minor is not None:
        remaining = max(int(cert.max_base_minor) - certificate_consumed(session, cert) - int((used or {}).get(cert.certificate_no, 0)), 0)
    money = lambda base, rate: int((Decimal(base) * Decimal(rate) / 100).quantize(Decimal(1), ROUND_HALF_UP))  # noqa: E731
    tds, cert_base = 0, 0
    for base in parts:
        if cert is None:
            taken = 0
        elif remaining is None:
            taken = base
        else:
            taken = min(base, remaining)
            remaining -= taken
        tds += (money(taken, cert.rate_pct) if taken else 0) + money(base - taken, normal)
        cert_base += taken
    total = sum(parts)
    if cert is not None and cert_base and cert_base == total:
        rate = Decimal(cert.rate_pct)
    elif cert_base == 0 or total == 0:
        rate = normal
    else:
        rate = (Decimal(tds) * 100 / Decimal(total)).quantize(Decimal("0.001"))
    return {"tdsMinor": tds, "ratePct": rate, "certificate": cert.certificate_no if cert is not None and cert_base else None, "baseMinor": total,
            "certBaseMinor": cert_base}


def at_payment_detail(session: Session, invoice: Invoice, on: Optional[date] = None) -> dict:
    """TDS of the invoice alone at payment time (see ``payment_tds``)."""
    return payment_tds(session, invoice, [], on)


def at_payment(session: Session, invoice: Invoice, on: Optional[date] = None) -> int:
    return at_payment_detail(session, invoice, on)["tdsMinor"]


def note_tds_at_payment(note, rate: Optional[Decimal]) -> int:
    """TDS of a debit note netted into a payment, at the rate of that payment (a certificate lowers it for the notes too)."""
    if not note.tds_base_minor or rate is None:
        return 0
    return int((Decimal(note.tds_base_minor) * Decimal(rate) / 100).quantize(Decimal(1), ROUND_HALF_UP))


def add_certificate(session: Session, supplier: Supplier, *, certificate_no: str, rate_pct: Decimal, valid_from: date, valid_to: date,
                    section: Optional[str], note: Optional[str], max_base_minor: Optional[int] = None):
    from app.pic.models import TdsCertificate
    if "supplier:manage" not in principal(session).scopes and "payment:run" not in principal(session).scopes:
        raise Problem(403, "FORBIDDEN", "Lower-deduction certificates are recorded by supplier management or finance")
    certificate_no = (certificate_no or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9/\-]{6,40}", certificate_no):
        raise Problem(422, "VALIDATION_FAILED", "The certificate number is 6 to 40 letters, digits, / or -")
    if valid_to < valid_from:
        raise Problem(422, "VALIDATION_FAILED", "The certificate is valid to a date before it starts")
    if max_base_minor is not None and max_base_minor <= 0:
        raise Problem(422, "VALIDATION_FAILED", "The amount cap of the certificate must be positive")
    if section:
        sections = rule_body(session, "TDS", TDS_DEFAULT).get("sections") or {}
        if section not in sections:
            raise Problem(422, "TDS_SECTION_UNKNOWN", f"TDS section {section} is not defined in rule set TDS ({', '.join(sorted(sections))})")
    if session.execute(select(TdsCertificate.id).where(TdsCertificate.supplier_id == supplier.id, TdsCertificate.certificate_no == certificate_no)).first():
        raise Problem(409, "DUPLICATE_CERTIFICATE", f"Certificate {certificate_no} is already recorded for {supplier.code}")
    p = principal(session)
    cert = TdsCertificate(tenant_id=current_tenant(session), supplier_id=supplier.id, certificate_no=certificate_no, section=section or None,
                          rate_pct=rate_pct, valid_from=valid_from, valid_to=valid_to, status="ACTIVE", note=note, max_base_minor=max_base_minor,
                          created_by=p.user_id)
    session.add(cert)
    session.flush()
    audit.record(session, "SUPPLIER", supplier.id, "TDS_CERTIFICATE_ADDED", object_ref=supplier.code, reason=note,
                 after={"certificate": certificate_no, "ratePct": str(rate_pct), "section": section, "validFrom": valid_from.isoformat(), "validTo": valid_to.isoformat(),
                        "maxBaseMinor": max_base_minor})
    return cert


def revoke_certificate(session: Session, supplier: Supplier, certificate_no: str, reason: str):
    from app.pic.models import TdsCertificate
    if len((reason or "").strip()) < 5:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for revoking the certificate")
    cert = session.execute(select(TdsCertificate).where(TdsCertificate.supplier_id == supplier.id,
                                                        TdsCertificate.certificate_no == certificate_no.upper()).with_for_update()).scalar_one_or_none()
    if cert is None:
        raise Problem(404, "NOT_FOUND", f"Certificate {certificate_no} not found for {supplier.code}")
    if cert.status == "REVOKED":
        raise Problem(409, "ILLEGAL_TRANSITION", f"Certificate {cert.certificate_no} is already revoked")
    cert.status, cert.revoked_reason = "REVOKED", reason
    audit.record(session, "SUPPLIER", supplier.id, "TDS_CERTIFICATE_REVOKED", object_ref=supplier.code, reason=reason, after={"certificate": cert.certificate_no})
    return cert


def certificates_of(session: Session, supplier: Supplier) -> list[dict]:
    from app.pic.models import TdsCertificate
    today = clock.today()
    return [{"certificateNo": c.certificate_no, "section": c.section, "ratePct": str(c.rate_pct), "validFrom": c.valid_from.isoformat(),
             "validTo": c.valid_to.isoformat(), "status": c.status, "validNow": c.status == "ACTIVE" and c.valid_from <= today <= c.valid_to,
             "note": c.note, "revokedReason": c.revoked_reason, "maxBaseMinor": c.max_base_minor,
             "consumedBaseMinor": certificate_consumed(session, c),
             "remainingBaseMinor": None if c.max_base_minor is None else max(c.max_base_minor - certificate_consumed(session, c), 0)}
            for c in session.execute(select(TdsCertificate).where(TdsCertificate.supplier_id == supplier.id)
                                     .order_by(TdsCertificate.valid_from.desc(), TdsCertificate.certificate_no)).scalars()]


# ---------------------------------------------------------------- foreign-currency invoices
def company_currency(session: Session, company_code: str) -> str:
    from app.pic.platform import batch
    row = batch.memo(session, ("company-currency", company_code), lambda: session.execute(select(CompanyCode.currency).where(CompanyCode.code == company_code)).scalar())
    return (row or "INR").upper()


def fx_for(session: Session, invoice: Invoice) -> Optional[tuple[Decimal, date, int]]:
    """(rate, rate date, gross in the company-code currency) for a foreign-currency invoice; None for a home-currency one.
    409 FX_RATE_MISSING when the tenant has no rate valid on the invoice date."""
    home = company_currency(session, invoice.company_code)
    currency = (invoice.currency or "INR").upper()
    if currency == home:
        return None
    from app.pic.services import spend_cube
    found = spend_cube._rate(session, currency, home, invoice.invoice_date)
    if found is None:
        raise Problem(409, "FX_RATE_MISSING", f"No {currency}->{home} exchange rate is valid on {invoice.invoice_date.isoformat()}: load it "
                      "(ADM reference data, fx_rate) before posting", rule_ref="P14")
    rate, rate_date = found
    return rate, rate_date, int((Decimal(invoice.gross_minor) * rate).quantize(Decimal(1), ROUND_HALF_UP))


def fx_at_payment(session: Session, invoice: Invoice, amount_minor: int, paid_on: date) -> Optional[dict]:
    """Realised exchange difference of a foreign-currency payment: the amount in the company-code currency at the rate on the payment date against
    the rate fixed on the invoice (a payable that costs more home currency than booked is a loss). None for a home-currency invoice; raises
    409 FX_RATE_MISSING when the tenant has no rate for the payment date."""
    home = company_currency(session, invoice.company_code)
    currency = (invoice.currency or "INR").upper()
    if currency == home or invoice.fx_rate is None:
        return None
    from app.pic.services import spend_cube
    found = spend_cube._rate(session, currency, home, paid_on)
    if found is None:
        raise Problem(409, "FX_RATE_MISSING", f"No {currency}->{home} exchange rate is valid on {paid_on.isoformat()}: load it before paying", rule_ref="P14")
    rate, rate_date = found
    booked = Decimal(amount_minor) * Decimal(invoice.fx_rate)
    paid = Decimal(amount_minor) * Decimal(rate)
    return {"fxRate": rate, "rateDate": rate_date, "amountGroupMinor": int(paid.quantize(Decimal(1), ROUND_HALF_UP)),
            "bookedGroupMinor": int(booked.quantize(Decimal(1), ROUND_HALF_UP)),
            "gainLossMinor": int((booked - paid).quantize(Decimal(1), ROUND_HALF_UP))}


def group_minor(invoice: Invoice, amount_minor: int) -> int:
    """An amount of the invoice in the company-code currency (the amount itself for a home-currency invoice or one without a rate yet)."""
    return int((Decimal(amount_minor) * Decimal(invoice.fx_rate)).quantize(Decimal(1), ROUND_HALF_UP)) if invoice.fx_rate else int(amount_minor)


# ---------------------------------------------------------------- posting periods (cut-off)
def period_of(on: date) -> str:
    return f"{on.year:04d}-{on.month:02d}"


def _period_end(period: str) -> date:
    year, month = int(period[:4]), int(period[5:])
    return date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)


def is_closed(session: Session, company_code: str, on: date) -> bool:
    return session.execute(select(PostingPeriod.id).where(PostingPeriod.company_code == company_code, PostingPeriod.period == period_of(on),
                                                          PostingPeriod.status == "CLOSED")).first() is not None


def _record_refusal(session: Session, company_code: str, on: date, what: str) -> None:
    """The refusal rolls the request back, so the evidence (who tried to post what into which closed period) is written in its own transaction,
    like an ABAC denial or a SoD violation."""
    from app.pic.db import tenant_tx
    from sqlalchemy import text
    p = session.info.get("principal")
    row = session.execute(select(PostingPeriod).where(PostingPeriod.company_code == company_code, PostingPeriod.period == period_of(on))).scalar_one_or_none()
    if p is None or row is None:
        return
    try:
        with tenant_tx(p.tenant_id, p.user_id, p) as s:
            s.execute(text("SET LOCAL lock_timeout = '1500ms'"))
            audit.record(s, "POSTING_PERIOD", row.id, "POSTING_REFUSED", object_ref=f"{company_code}/{period_of(on)}",
                         after={"what": what, "documentDate": on.isoformat(), "attemptedBy": p.name}, reason="posting period is closed (cut-off)")
    except Exception:  # noqa: BLE001 - the evidence must never turn the refusal into a 500
        pass


def assert_open(session: Session, company_code: str, on: date, what: str) -> None:
    if is_closed(session, company_code, on):
        _record_refusal(session, company_code, on, what)
        raise Problem(409, "PERIOD_CLOSED", f"Posting period {period_of(on)} of company code {company_code} is closed: {what} cannot be "
                      "posted or dated into it. Reopen rule: finance (scope period:close) reopens the period with an audited reason of at least 10 "
                      "characters and closes it again afterwards; otherwise date the document in the open period", rule_ref="CUT-OFF",
                      period=period_of(on), companyCode=company_code, reopenScope="period:close")


def _require_finance(session: Session) -> None:
    if "period:close" not in principal(session).scopes:
        raise Problem(403, "FORBIDDEN", "Posting periods are closed and reopened by finance")


def cutoff_snapshot(session: Session, company_code: str, period: str) -> dict:
    """What is still in flight at the cut-off: invoices captured on or before the period end that are not yet posted, and the GR/IR
    accrual (accepted, not invoiced) at close."""
    from app.pic.services import payables
    end = _period_end(period)
    open_invoices = session.execute(select(Invoice).where(
        Invoice.company_code == company_code, Invoice.invoice_date <= end, Invoice.status.in_(("CAPTURED", "DUPLICATE_CHECK", "MATCHING", "EXCEPTION", "MATCHED", "APPROVED")))).scalars().all()
    accrual = sum(row["accrualMinor"] for row in payables.grir(session, company_code))
    return {"periodEnd": end.isoformat(), "unpostedInvoices": len(open_invoices), "unpostedGrossMinor": sum(i.gross_minor for i in open_invoices),
            "unpostedByStatus": {s: sum(1 for i in open_invoices if i.status == s) for s in sorted({i.status for i in open_invoices})},
            "grirAccrualMinor": accrual}


def close_period(session: Session, company_code: str, period: str, reason: Optional[str] = None) -> PostingPeriod:
    _require_finance(session)
    from app.pic.platform import abac
    abac.guard(session, "PERIOD_CLOSE", None, company_code=company_code)
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period or ""):
        raise Problem(422, "VALIDATION_FAILED", "period must be YYYY-MM")
    if _period_end(period) >= clock.today():
        raise Problem(409, "PERIOD_NOT_ENDED", f"Period {period} has not ended yet: it can be closed from {( _period_end(period) + timedelta(days=1)).isoformat()}",
                      rule_ref="CUT-OFF")
    if session.execute(select(CompanyCode.id).where(CompanyCode.code == company_code)).first() is None:
        raise Problem(404, "NOT_FOUND", f"Company code {company_code} not found")
    p = principal(session)
    row = session.execute(select(PostingPeriod).where(PostingPeriod.company_code == company_code, PostingPeriod.period == period)
                          .with_for_update()).scalar_one_or_none()
    if row is not None and row.status == "CLOSED":
        raise Problem(409, "ILLEGAL_TRANSITION", f"Period {period} of {company_code} is already closed")
    cutoff = cutoff_snapshot(session, company_code, period)
    if row is None:
        row = PostingPeriod(tenant_id=current_tenant(session), company_code=company_code, period=period, status="CLOSED", created_by=p.user_id)
        session.add(row)
    row.status, row.closed_by, row.closed_at, row.cutoff = "CLOSED", p.user_id, clock.now(), cutoff
    row.reason = reason or row.reason
    session.flush()
    snapshot = persist_grir_snapshot(session, company_code, period)
    cutoff["grirSnapshot"] = str(snapshot.id)
    row.cutoff = cutoff
    audit.record(session, "POSTING_PERIOD", row.id, "CLOSED", object_ref=f"{company_code}/{period}", after={"cutoff": cutoff}, reason=reason)
    outbox.emit(session, "finance.period.closed", "POSTING_PERIOD", row.id, f"{company_code}/{period}",
                {"companyCode": company_code, "period": period, "unpostedInvoices": cutoff["unpostedInvoices"],
                 "grirAccrualMinor": cutoff["grirAccrualMinor"]})
    return row


def persist_grir_snapshot(session: Session, company_code: str, period: str):
    """The GR/IR accrual (received, not invoiced) of the company code at the moment the period is closed, line by line; one row per close."""
    from app.pic.models import GrirSnapshot
    from app.pic.services import payables
    lines = payables.grir(session, company_code)
    p = principal(session)
    snapshot = GrirSnapshot(tenant_id=current_tenant(session), company_code=company_code, period=period, closed_at=clock.now(), closed_by=p.user_id,
                            total_minor=sum(l["accrualMinor"] for l in lines), line_count=len(lines), lines=lines[:5000], created_by=p.user_id)
    session.add(snapshot)
    session.flush()
    return snapshot


def grir_snapshots(session: Session, period: Optional[str] = None, company_code: Optional[str] = None) -> list[dict]:
    from app.pic.models import GrirSnapshot
    query = select(GrirSnapshot).order_by(GrirSnapshot.closed_at.desc())
    if period:
        query = query.where(GrirSnapshot.period == period)
    if company_code:
        query = query.where(GrirSnapshot.company_code == company_code)
    return [{"id": str(g.id), "companyCode": g.company_code, "period": g.period, "closedAt": g.closed_at.isoformat(), "totalMinor": g.total_minor,
             "lineCount": g.line_count, "lines": g.lines} for g in session.execute(query.limit(50)).scalars()]


def reopen_period(session: Session, company_code: str, period: str, reason: str) -> PostingPeriod:
    _require_finance(session)
    from app.pic.platform import abac
    abac.guard(session, "PERIOD_CLOSE", None, company_code=company_code)
    if len((reason or "").strip()) < 10:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for reopening the period (at least 10 characters)")
    row = session.execute(select(PostingPeriod).where(PostingPeriod.company_code == company_code, PostingPeriod.period == period)
                          .with_for_update()).scalar_one_or_none()
    if row is None or row.status != "CLOSED":
        raise Problem(409, "ILLEGAL_TRANSITION", f"Period {period} of {company_code} is not closed")
    p = principal(session)
    row.status, row.reopened_by, row.reopened_at, row.reason = "OPEN", p.user_id, clock.now(), reason
    session.flush()
    audit.record(session, "POSTING_PERIOD", row.id, "REOPENED", object_ref=f"{company_code}/{period}", reason=reason)
    outbox.emit(session, "finance.period.reopened", "POSTING_PERIOD", row.id, f"{company_code}/{period}",
                {"companyCode": company_code, "period": period, "reason": reason})
    return row


def periods(session: Session, company_code: Optional[str] = None) -> list[dict]:
    query = select(PostingPeriod).order_by(PostingPeriod.company_code, PostingPeriod.period.desc())
    if company_code:
        query = query.where(PostingPeriod.company_code == company_code)
    from app.pic.models import AuditEvent
    rows = session.execute(query).scalars().all()
    refused: dict = {}  # POSTING_REFUSED events per period (visible to finance without the audit scope): count, last actor, last time
    if rows:
        for event in session.execute(select(AuditEvent).where(AuditEvent.object_type == "POSTING_PERIOD", AuditEvent.action == "POSTING_REFUSED",
                                                              AuditEvent.object_id.in_([r.id for r in rows])).order_by(AuditEvent.seq)).scalars():
            entry = refused.setdefault(event.object_id, {"count": 0, "lastActor": None, "lastAt": None})
            entry["count"] += 1
            entry["lastActor"], entry["lastAt"] = (event.after or {}).get("attemptedBy") or event.actor, event.ts.isoformat()
    return [{"id": str(r.id), "companyCode": r.company_code, "period": r.period, "status": r.status,
             "closedAt": r.closed_at.isoformat() if r.closed_at else None, "reopenedAt": r.reopened_at.isoformat() if r.reopened_at else None,
             "reason": r.reason, "cutoff": r.cutoff,
             "refusedAttempts": refused.get(r.id, {"count": 0, "lastActor": None, "lastAt": None})} for r in rows]


# ---------------------------------------------------------------- TDS register (Form 26Q source)
def tds_register(session: Session, fiscal_year: Optional[str] = None, supplier: Optional[str] = None, company_codes: Optional[list[str]] = None) -> dict:
    """TDS withheld on paid invoices by supplier and section: the source of the quarterly TDS return."""
    from app.pic.models import Payment
    query = (select(Payment, Invoice, Supplier).join(Invoice, Invoice.id == Payment.invoice_id).join(Supplier, Supplier.id == Payment.supplier_id)
             .where(Payment.status == "COMPLETED", Payment.tds_minor > 0).order_by(Payment.value_date, Payment.number))
    if fiscal_year:
        first, last = fiscal_year_range(fiscal_year)
        query = query.where(Payment.value_date >= first, Payment.value_date <= last)  # deducted in the year of the payment (D25)
    if supplier:
        query = query.where(Supplier.code == supplier)
    if company_codes is not None:
        query = query.where(Invoice.company_code.in_(company_codes))
    from app.pic.services import nonresident_tax
    rows, totals = [], {}
    for payment, invoice, sup in session.execute(query).all():
        tds_inr = int(payment.tds_inr_minor) if payment.tds_inr_minor is not None else int(payment.tds_minor)
        rows.append({"payment": payment.number, "invoice": invoice.number, "supplier": sup.code, "section": invoice.tds_section,
                     "ratePct": str(payment.tds_rate if payment.tds_rate is not None else invoice.tds_rate) if (payment.tds_rate or invoice.tds_rate) is not None else None,
                     "baseMinor": invoice.tds_base_minor, "tdsMinor": payment.tds_minor, "tdsInrMinor": tds_inr, "currency": payment.currency,
                     "returnForm": nonresident_tax.return_form(invoice.tds_section), "basis": (payment.tax_detail or {}).get("basis"),
                     "valueDate": payment.value_date.isoformat(), "fiscalYear": invoice.fiscal_year,
                     "panOnFile": sup.pan_hash is not None})
        key = f"{sup.code}|{invoice.tds_section}"
        totals[key] = totals.get(key, 0) + tds_inr
    return {"fiscalYear": fiscal_year, "items": rows, "totalTdsMinor": sum(totals.values()),
            "bySupplierSection": [{"supplier": k.split("|")[0], "section": k.split("|")[1], "tdsMinor": v} for k, v in sorted(totals.items())]}


# ---------------------------------------------------------------- Form 26Q / 16A style export
QUARTERS = {"Q1": (4, 6), "Q2": (7, 9), "Q3": (10, 12), "Q4": (1, 3)}


def quarter_range(fiscal_year: str, quarter: str) -> tuple[date, date]:
    """First and last day of an Indian fiscal-year quarter (Q1 April-June ... Q4 January-March)."""
    if quarter not in QUARTERS or not re.fullmatch(r"\d{4}-\d{2}", fiscal_year or ""):
        raise Problem(422, "VALIDATION_FAILED", "Give fiscal_year as YYYY-YY and quarter as Q1, Q2, Q3 or Q4")
    first, last = QUARTERS[quarter]
    year = int(fiscal_year[:4]) if first >= 4 else int(fiscal_year[:4]) + 1
    following = date(year + (1 if last == 12 else 0), last % 12 + 1, 1)
    return date(year, first, 1), following - timedelta(days=1)


def fiscal_year_range(fiscal_year: str) -> tuple[date, date]:
    """First and last day of an Indian fiscal year written YYYY-YY (2026-27 is 1 April 2026 to 31 March 2027)."""
    if not re.fullmatch(r"\d{4}-\d{2}", fiscal_year or ""):
        raise Problem(422, "VALIDATION_FAILED", "Give fiscal_year as YYYY-YY")
    year = int(fiscal_year[:4])
    return date(year, 4, 1), date(year + 1, 3, 31)


def _safe(cell) -> str:
    """CSV cells that start with a formula character are quoted as text (spreadsheet formula injection)."""
    text = "" if cell is None else str(cell)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") and not re.fullmatch(r"-?\d+(\.\d+)?", text) else text


def tds_export(session: Session, fiscal_year: str, quarter: str, kind: str = "26Q", company_codes: Optional[list[str]] = None) -> dict:
    """Deducted TDS of a quarter as CSV. 26Q: one line per payment with TDS or a certificate (deductee, section, amount, rate, tax, dates, s.197
    certificate). 16A: one line per deductee and section with the quarter's totals (the figures of the TDS certificate). The PAN is the one
    inside the supplier's GSTIN; a supplier without GSTIN is exported as PANNOTAVBL."""
    import csv
    import hashlib
    import io
    from app.pic.models import DebitNote, Payment
    from app.pic.platform import crypto
    from app.pic.services import nonresident_tax
    kind = (kind or "26Q").upper()
    if kind not in ("26Q", "27Q", "16A"):
        raise Problem(422, "VALIDATION_FAILED", "format must be 26Q, 27Q or 16A")
    first, last = quarter_range(fiscal_year, quarter)
    rows = session.execute(
        select(Payment, Invoice, Supplier).join(Invoice, Invoice.id == Payment.invoice_id).join(Supplier, Supplier.id == Payment.supplier_id)
        .where(Payment.status == "COMPLETED", Payment.value_date >= first, Payment.value_date <= last,  # the quarter of the payment, not of the invoice (D25)
               (Payment.tds_minor > 0) | Payment.tds_certificate.is_not(None),
               *([Invoice.company_code.in_(company_codes)] if company_codes is not None else []))
        .order_by(Supplier.code, Payment.value_date, Payment.number)).all()
    lines = []
    for payment, invoice, supplier in rows:
        form = nonresident_tax.return_form(invoice.tds_section)
        if kind in ("26Q", "27Q") and form != kind:  # residents go to 26Q, non-residents (section 195) to 27Q; 16A carries both
            continue
        residency = nonresident_tax.residency_of(session, supplier.id) if form == "27Q" else None
        gstin = supplier_gstin(session, supplier) if form == "26Q" else ""
        pan = (gstin[2:12] if len(gstin) == 15 else None) or nonresident_tax.pan_of(residency) or "PANNOTAVBL"
        detail = payment.tax_detail or {}
        base = int(payment.tds_base_inr_minor) if payment.tds_base_inr_minor is not None else int(payment.tds_base_minor or 0)
        tds = int(payment.tds_inr_minor) if payment.tds_inr_minor is not None else int(payment.tds_minor)
        note = session.get(DebitNote, payment.debit_note_id) if payment.debit_note_id else None
        lines.append({"payment": payment.number, "invoice": note.number if note else invoice.number, "supplier": supplier.code, "name": supplier.legal_name,
                      "pan": pan, "code": "02" if pan[3:4] == "P" else "01", "section": invoice.tds_section, "date": payment.value_date,
                      "base": base, "rate": payment.tds_rate if payment.tds_rate is not None else invoice.tds_rate, "tds": tds,
                      "certificate": payment.tds_certificate, "form": form, "detail": detail,
                      "country": residency.country if residency is not None else supplier.country, "currency": payment.currency,
                      "foreignTds": int(payment.tds_minor), "borne": int(payment.tax_borne_minor or 0)})
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    money = lambda minor: f"{minor / 100:.2f}"  # noqa: E731
    if kind == "26Q":
        writer.writerow(["Sr No", "Deductee Code", "PAN", "Name of Deductee", "Section", "Date of Payment/Credit", "Amount Paid/Credited", "Rate of TDS %",
                         "TDS Deducted", "Surcharge", "Education Cess", "Total Tax Deducted", "Date of Deduction", "Certificate u/s 197",
                         "Payment", "Invoice / Debit note", "Supplier Code", "Quarter", "Fiscal Year"])
        for n, l in enumerate(lines, start=1):
            writer.writerow([_safe(x) for x in (n, l["code"], l["pan"], l["name"], l["section"], l["date"].isoformat(), money(l["base"]), l["rate"],
                                                money(l["tds"]), "0.00", "0.00", money(l["tds"]), l["date"].isoformat(), l["certificate"] or "",
                                                l["payment"], l["invoice"], l["supplier"], quarter, fiscal_year)])
    elif kind == "27Q":
        writer.writerow(["Sr No", "Deductee Code", "PAN", "Name of Deductee", "Country of Residence", "Section", "Nature of Remittance",
                         "Date of Payment/Credit", "Amount Paid/Credited (INR)", "Rate of TDS %", "Basis (DTAA / Act / 206AA)", "DTAA Article",
                         "Act Rate %", "Surcharge %", "Health and Education Cess %", "Total Tax Deducted (INR)", "Grossed Up", "Tax Borne by Deductor",
                         "Currency", "Tax in Currency", "FX Rate", "FX Date", "Date of Deduction", "Certificate u/s 197", "Payment", "Invoice / Debit note",
                         "Supplier Code", "Quarter", "Fiscal Year"])
        for n, l in enumerate(lines, start=1):
            d = l["detail"]
            writer.writerow([_safe(x) for x in (n, "01" if d.get("payeeType", "COMPANY") == "COMPANY" else "02", l["pan"], l["name"], l["country"],
                                                d.get("sectionLabel") or "195", d.get("natureLabel") or l["section"], l["date"].isoformat(), money(l["base"]),
                                                l["rate"], d.get("basis") or "", (d.get("treaty") or {}).get("article") or "", d.get("actRatePct") or "",
                                                d.get("surchargePct") or "", d.get("cessPct") or "", money(l["tds"]), "Y" if d.get("grossUp") else "N",
                                                money(l["borne"]) if l["borne"] else "0.00", l["currency"], money(l["foreignTds"]), d.get("fxRate") or "",
                                                d.get("fxDate") or "", l["date"].isoformat(), l["certificate"] or "", l["payment"], l["invoice"],
                                                l["supplier"], quarter, fiscal_year)])
    else:
        grouped: dict[tuple, dict] = {}
        for l in lines:
            g = grouped.setdefault((l["pan"], l["supplier"], l["section"]), {**l, "count": 0, "base": 0, "tds": 0, "payments": [], "certs": set()})
            g["count"] += 1
            g["base"] += l["base"]
            g["tds"] += l["tds"]
            g["payments"].append(l["payment"])
            if l["certificate"]:
                g["certs"].add(l["certificate"])
        writer.writerow(["Deductee PAN", "Name of Deductee", "Supplier Code", "Section", "Quarter", "Fiscal Year", "Number of Payments",
                         "Total Amount Paid/Credited", "Total Tax Deducted", "Certificate u/s 197", "Payments"])
        for (pan, code, section), g in sorted(grouped.items()):
            writer.writerow([_safe(x) for x in (pan, g["name"], code, section, quarter, fiscal_year, g["count"], money(g["base"]), money(g["tds"]),
                                                " ".join(sorted(g["certs"])), " ".join(g["payments"]))])
    content = out.getvalue()
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    audit.record(session, "TDS_EXPORT", uuid.uuid5(uuid.NAMESPACE_URL, f"tds-export:{current_tenant(session)}:{fiscal_year}:{quarter}"), "EXPORTED",
                 object_ref=f"{fiscal_year}/{quarter}/{kind}", after={"rows": len(lines), "totalTdsMinor": sum(l["tds"] for l in lines), "sha256": sha})
    return {"content": content, "sha256": sha, "rows": len(lines), "fileName": f"TDS_{kind}_{fiscal_year}_{quarter}.csv"}


# ---------------------------------------------------------------- supplier finance attributes (MSME class, Udyam, TDS section, PAN)
UDYAM_RE = re.compile(r"^UDYAM-[A-Z]{2}-\d{2}-\d{7}$")


def set_supplier_finance(session: Session, supplier: Supplier, *, msme_class: Optional[str], udyam_no: Optional[str], tds_section: Optional[str],
                         pan: Optional[str], msme_written_agreement: Optional[bool], reason: str) -> dict:
    """Maintain the finance attributes of a supplier: the MSME class needs the Udyam number (format UDYAM-KA-03-0012345), the TDS section must exist in rule set
    TDS, a PAN must be well formed and the one inside the supplier's GSTIN (kept as a hash, only the masked value is audited). Returns {"before", "after"}.
    The caller holds the row lock and has checked If-Match."""
    from app.pic.platform import crypto
    from app.pic.services import master_changes
    if tds_section:
        sections = rule_body(session, "TDS", TDS_DEFAULT).get("sections") or {}
        if tds_section not in sections:
            raise Problem(422, "TDS_SECTION_UNKNOWN", f"TDS section {tds_section} is not defined in rule set TDS ({', '.join(sorted(sections))})")
    errors = []
    udyam = (udyam_no or "").strip().upper() or None
    if udyam and not UDYAM_RE.match(udyam):
        errors.append("Udyam registration number must look like UDYAM-KA-03-0012345 (state, district, seven digits)")
    if msme_class and not (udyam or supplier.udyam_no):
        raise Problem(422, "UDYAM_REQUIRED", "An MSME class needs the Udyam registration number")
    pan = (pan or "").strip().upper() or None
    if pan:
        errors += master_changes.pan_errors(pan)
        gstin = supplier_gstin(session, supplier)
        if len(gstin) == 15 and gstin[2:12] != pan:
            errors.append("the PAN must be the one inside the supplier's GSTIN")
    if errors:
        raise Problem(422, "VALIDATION_FAILED", "; ".join(errors), rule_ref="MDM-04", errors=errors)
    before = {"msmeClass": supplier.msme_class, "udyamNo": supplier.udyam_no, "tdsSection": supplier.tds_section, "panOnFile": supplier.pan_hash is not None,
              "msmeWrittenAgreement": supplier.msme_written_agreement}
    supplier.msme_class, supplier.udyam_no, supplier.tds_section = msme_class, udyam or (supplier.udyam_no if msme_class else None), tds_section
    if msme_written_agreement is not None:
        supplier.msme_written_agreement = msme_written_agreement
    if pan:
        supplier.pan_hash = crypto.blind_index(supplier.tenant_id, pan)
    session.flush()
    after = {"msmeClass": supplier.msme_class, "udyamNo": supplier.udyam_no, "tdsSection": supplier.tds_section, "panOnFile": supplier.pan_hash is not None,
             "msmeWrittenAgreement": supplier.msme_written_agreement, **({"panSet": crypto.mask(pan)} if pan else {})}
    audit.record(session, "SUPPLIER", supplier.id, "FINANCE_ATTRIBUTES_CHANGED", object_ref=supplier.code, before=before, after=after, reason=reason)
    return {"before": before, "after": after}
