"""M10 finance controls that sit around the match: duplicate variants, the MSME 45-day rule, TDS, foreign-currency invoices and
posting periods (period close / cut-off). Rule bodies are tenant data (rule sets MSME, TDS) with the defaults below when a tenant
has none; every default is a starting point for the tenant's tax and treasury team to confirm, not legal advice.
"""
import re
import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (CompanyCode, CreditNote, GoodsReceipt, GrLine, Invoice, InvoiceLine, PoLine, PostingPeriod, ServiceEntry, SesLine,
                            Supplier)
from app.pic.platform import audit, clock, finance_defaults, outbox, rules
from app.pic.platform.errors import Problem
from app.pic.services.common import principal

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
    cap = accepted + timedelta(days=int(rule_body(session, "MSME", MSME_DEFAULT).get("maxDays", 45)))
    return (cap, True, accepted) if cap < contractual else (contractual, False, accepted)


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
    section = (supplier.tds_section or "").strip()
    if not section:
        return {}
    spec, rate, no_pan, _ = _section_spec(session, supplier, section, invoice.company_code)
    base = invoice.net_minor - _credit_net(session, invoice)
    prior_total, prior_taxed = _prior(session, supplier, section, invoice.fiscal_year, exclude_invoice=invoice.id)
    return {"section": section, "label": spec.get("label"), "ratePct": rate, "noPan": no_pan,
            **_determine(spec, base, prior_total, prior_taxed, rate)}


def compute_note_tds(session: Session, invoice: Invoice, note) -> dict:
    """TDS on the additional taxable value of a supplier debit note (price correction or charge), net of GST, under the section and rate of its
    invoice; thresholds count the supplier's invoices and earlier debit notes of the section in the fiscal year. {} when the invoice carries no TDS section."""
    if not invoice.tds_section or invoice.tds_rate is None:
        return {}
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


def at_payment_detail(session: Session, invoice: Invoice, on: Optional[date] = None) -> dict:
    """TDS to keep back at payment time: the base fixed at posting, reduced for credit notes that arrived after the posting, at the rate of a
    valid s.197 certificate on the payment date (else the section rate fixed at posting). Migrated withholding without a section is kept as it is."""
    if not invoice.tds_section or invoice.tds_rate is None:
        return {"tdsMinor": max(int(invoice.withholding_tax_minor or 0), 0), "ratePct": None, "certificate": None, "baseMinor": 0}
    late = _credit_net(session, invoice, since=invoice.posted_at) if invoice.posted_at else 0
    taxable = max(int(invoice.tds_base_minor or 0) - late, 0)
    cert = valid_certificate(session, invoice.supplier_id, invoice.tds_section, on or clock.today())
    rate = Decimal(cert.rate_pct) if cert is not None else Decimal(invoice.tds_rate)
    return {"tdsMinor": int((Decimal(taxable) * rate / 100).quantize(Decimal(1), ROUND_HALF_UP)), "ratePct": rate,
            "certificate": cert.certificate_no if cert is not None else None, "baseMinor": taxable}


def at_payment(session: Session, invoice: Invoice, on: Optional[date] = None) -> int:
    return at_payment_detail(session, invoice, on)["tdsMinor"]


def note_tds_at_payment(note, rate: Optional[Decimal]) -> int:
    """TDS of a debit note netted into a payment, at the rate of that payment (a certificate lowers it for the notes too)."""
    if not note.tds_base_minor or rate is None:
        return 0
    return int((Decimal(note.tds_base_minor) * Decimal(rate) / 100).quantize(Decimal(1), ROUND_HALF_UP))


def add_certificate(session: Session, supplier: Supplier, *, certificate_no: str, rate_pct: Decimal, valid_from: date, valid_to: date,
                    section: Optional[str], note: Optional[str]):
    from app.pic.models import TdsCertificate
    if "supplier:manage" not in principal(session).scopes and "payment:run" not in principal(session).scopes:
        raise Problem(403, "FORBIDDEN", "Lower-deduction certificates are recorded by supplier management or finance")
    certificate_no = (certificate_no or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9/\-]{6,40}", certificate_no):
        raise Problem(422, "VALIDATION_FAILED", "The certificate number is 6 to 40 letters, digits, / or -")
    if valid_to < valid_from:
        raise Problem(422, "VALIDATION_FAILED", "The certificate is valid to a date before it starts")
    if section:
        sections = rule_body(session, "TDS", TDS_DEFAULT).get("sections") or {}
        if section not in sections:
            raise Problem(422, "TDS_SECTION_UNKNOWN", f"TDS section {section} is not defined in rule set TDS ({', '.join(sorted(sections))})")
    if session.execute(select(TdsCertificate.id).where(TdsCertificate.supplier_id == supplier.id, TdsCertificate.certificate_no == certificate_no)).first():
        raise Problem(409, "DUPLICATE_CERTIFICATE", f"Certificate {certificate_no} is already recorded for {supplier.code}")
    p = principal(session)
    cert = TdsCertificate(tenant_id=current_tenant(session), supplier_id=supplier.id, certificate_no=certificate_no, section=section or None,
                          rate_pct=rate_pct, valid_from=valid_from, valid_to=valid_to, status="ACTIVE", note=note, created_by=p.user_id)
    session.add(cert)
    session.flush()
    audit.record(session, "SUPPLIER", supplier.id, "TDS_CERTIFICATE_ADDED", object_ref=supplier.code, reason=note,
                 after={"certificate": certificate_no, "ratePct": str(rate_pct), "section": section, "validFrom": valid_from.isoformat(), "validTo": valid_to.isoformat()})
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
             "note": c.note, "revokedReason": c.revoked_reason}
            for c in session.execute(select(TdsCertificate).where(TdsCertificate.supplier_id == supplier.id)
                                     .order_by(TdsCertificate.valid_from.desc(), TdsCertificate.certificate_no)).scalars()]


# ---------------------------------------------------------------- foreign-currency invoices
def company_currency(session: Session, company_code: str) -> str:
    row = session.execute(select(CompanyCode.currency).where(CompanyCode.code == company_code)).scalar()
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


def assert_open(session: Session, company_code: str, on: date, what: str) -> None:
    if is_closed(session, company_code, on):
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
    return [{"id": str(r.id), "companyCode": r.company_code, "period": r.period, "status": r.status,
             "closedAt": r.closed_at.isoformat() if r.closed_at else None, "reopenedAt": r.reopened_at.isoformat() if r.reopened_at else None,
             "reason": r.reason, "cutoff": r.cutoff} for r in session.execute(query).scalars()]


# ---------------------------------------------------------------- TDS register (Form 26Q source)
def tds_register(session: Session, fiscal_year: Optional[str] = None, supplier: Optional[str] = None) -> dict:
    """TDS withheld on paid invoices by supplier and section: the source of the quarterly TDS return."""
    from app.pic.models import Payment
    query = (select(Payment, Invoice, Supplier).join(Invoice, Invoice.id == Payment.invoice_id).join(Supplier, Supplier.id == Payment.supplier_id)
             .where(Payment.status == "COMPLETED", Payment.tds_minor > 0).order_by(Payment.value_date, Payment.number))
    if fiscal_year:
        query = query.where(Invoice.fiscal_year == fiscal_year)
    if supplier:
        query = query.where(Supplier.code == supplier)
    rows, totals = [], {}
    for payment, invoice, sup in session.execute(query).all():
        rows.append({"payment": payment.number, "invoice": invoice.number, "supplier": sup.code, "section": invoice.tds_section,
                     "ratePct": str(invoice.tds_rate) if invoice.tds_rate is not None else None, "baseMinor": invoice.tds_base_minor,
                     "tdsMinor": payment.tds_minor, "valueDate": payment.value_date.isoformat(), "fiscalYear": invoice.fiscal_year,
                     "panOnFile": sup.pan_hash is not None})
        key = f"{sup.code}|{invoice.tds_section}"
        totals[key] = totals.get(key, 0) + payment.tds_minor
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


def _safe(cell) -> str:
    """CSV cells that start with a formula character are quoted as text (spreadsheet formula injection)."""
    text = "" if cell is None else str(cell)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") and not re.fullmatch(r"-?\d+(\.\d+)?", text) else text


def tds_export(session: Session, fiscal_year: str, quarter: str, kind: str = "26Q") -> dict:
    """Deducted TDS of a quarter as CSV. 26Q: one line per payment with TDS or a certificate (deductee, section, amount, rate, tax, dates, s.197
    certificate). 16A: one line per deductee and section with the quarter's totals (the figures of the TDS certificate). The PAN is the one
    inside the supplier's GSTIN; a supplier without GSTIN is exported as PANNOTAVBL."""
    import csv
    import hashlib
    import io
    from app.pic.models import DebitNote, Payment
    from app.pic.platform import crypto
    kind = (kind or "26Q").upper()
    if kind not in ("26Q", "16A"):
        raise Problem(422, "VALIDATION_FAILED", "format must be 26Q or 16A")
    first, last = quarter_range(fiscal_year, quarter)
    rows = session.execute(
        select(Payment, Invoice, Supplier).join(Invoice, Invoice.id == Payment.invoice_id).join(Supplier, Supplier.id == Payment.supplier_id)
        .where(Payment.status == "COMPLETED", Payment.value_date >= first, Payment.value_date <= last, Invoice.fiscal_year == fiscal_year,
               (Payment.tds_minor > 0) | Payment.tds_certificate.is_not(None)).order_by(Supplier.code, Payment.value_date, Payment.number)).all()
    lines = []
    for payment, invoice, supplier in rows:
        gstin = crypto.decrypt(supplier.tenant_id, "gstin", supplier.gstin_enc) if supplier.gstin_enc else ""
        pan = gstin[2:12] if len(gstin) == 15 else "PANNOTAVBL"
        base = int(payment.tds_base_minor or 0)
        note = session.get(DebitNote, payment.debit_note_id) if payment.debit_note_id else None
        lines.append({"payment": payment.number, "invoice": note.number if note else invoice.number, "supplier": supplier.code, "name": supplier.legal_name,
                      "pan": pan, "code": "02" if pan[3:4] == "P" else "01", "section": invoice.tds_section, "date": payment.value_date,
                      "base": base, "rate": payment.tds_rate if payment.tds_rate is not None else invoice.tds_rate, "tds": int(payment.tds_minor),
                      "certificate": payment.tds_certificate})
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
