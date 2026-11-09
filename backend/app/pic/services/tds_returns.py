"""TDS return support (M10 finance second pass): challan records (BSR code, challan serial, deposit date), the reconciliation of the TDS deducted per
quarter and section against the deposits, and the Form 16A certificate data per deductee and quarter as JSON or CSV (no PDF: the certificate itself is
generated and signed in TRACES from the return; this is the data the tax team files and checks it against).

Figures come from completed payments dated in the quarter (the tax is deducted when the supplier is paid); the deductor's TAN and PAN are tenant data
(rule set TDS, ``deductor``) because the platform does not hold them: a missing mandatory field is listed in ``missingMandatory`` instead of being invented.

Payments to non-residents (section 195, rule TDS-195) belong to the Form 27Q return, residents to 26Q: every reconciliation row and certificate says
which (``returnForm``). Amounts are INR: a foreign-currency payment carries its tax and base converted on the rule's rate date (``tds_inr_minor``).
``certificate_pdf`` renders an INFORMATION COPY of the certificate data per deductee and quarter (services/form16a_pdf.py); the statutory Form 16A is
downloaded from TRACES.
"""
import csv
import io
import re
import uuid
from datetime import date
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import CompanyCode, Invoice, Payment, Supplier, TdsChallan
from app.pic.platform import audit, clock, crypto, outbox
from app.pic.platform.errors import Problem, not_found
from app.pic.services import finance_controls, nonresident_tax
from app.pic.services.common import principal

BSR = re.compile(r"^[0-9]{7}$")
SERIAL = re.compile(r"^[0-9]{5}$")


def assessment_year(fiscal_year: str) -> str:
    start = int(fiscal_year[:4]) + 1
    return f"{start}-{str(start + 1)[-2:]}"


def _sections(session: Session, company_code: str) -> dict:
    """The resident sections of rule set TDS and the s.195 section keys of rule set TDS-195 (195-ROYALTY, 195-FTS, ...)."""
    resident = finance_controls.rule_body(session, "TDS", finance_controls.TDS_DEFAULT, company_code=company_code).get("sections") or {}
    return {**resident, **nonresident_tax.section_labels(nonresident_tax.rule(session, company_code)[0])}


# Tax and base in INR: the converted figures of a foreign-currency (s.195) payment, the payment's own otherwise.
TDS_INR = func.coalesce(Payment.tds_inr_minor, Payment.tds_minor)


def record_challan(session: Session, *, company_code: str, fiscal_year: str, quarter: str, section: str, challan_no: str, bsr_code: str,
                   deposit_date: date, amount_minor: int, note: Optional[str] = None) -> TdsChallan:
    first, last = finance_controls.quarter_range(fiscal_year, quarter)
    if "payment:run" not in principal(session).scopes:
        raise Problem(403, "FORBIDDEN", "TDS challans are recorded by finance")
    if not BSR.match(bsr_code or ""):
        raise Problem(422, "VALIDATION_FAILED", "The BSR code of the bank branch is seven digits")
    if not SERIAL.match(challan_no or ""):
        raise Problem(422, "VALIDATION_FAILED", "The challan serial number is five digits")
    if amount_minor <= 0:
        raise Problem(422, "VALIDATION_FAILED", "The challan amount must be positive")
    if deposit_date < first:
        raise Problem(422, "VALIDATION_FAILED", f"A challan for {fiscal_year} {quarter} cannot be deposited before the quarter starts ({first.isoformat()})")
    if deposit_date > clock.today():
        raise Problem(422, "VALIDATION_FAILED", "The deposit date is in the future")
    if session.execute(select(CompanyCode.id).where(CompanyCode.code == company_code)).first() is None:
        raise not_found("Company code", company_code)
    if section not in _sections(session, company_code):
        raise Problem(422, "TDS_SECTION_UNKNOWN", f"TDS section {section} is not defined in rule set TDS ({', '.join(sorted(_sections(session, company_code)))})")
    if session.execute(select(TdsChallan.id).where(TdsChallan.bsr_code == bsr_code, TdsChallan.deposit_date == deposit_date,
                                                   TdsChallan.challan_no == challan_no)).first():
        raise Problem(409, "DUPLICATE_CHALLAN", f"Challan {challan_no} of BSR {bsr_code} deposited on {deposit_date.isoformat()} is already recorded")
    row = TdsChallan(tenant_id=current_tenant(session), company_code=company_code, fiscal_year=fiscal_year, quarter=quarter, section=section,
                     challan_no=challan_no, bsr_code=bsr_code, deposit_date=deposit_date, amount_minor=amount_minor, status="RECORDED", note=note,
                     created_by=principal(session).user_id)
    session.add(row)
    session.flush()
    audit.record(session, "TDS_CHALLAN", row.id, "RECORDED", object_ref=f"{bsr_code}/{challan_no}",
                 after={"companyCode": company_code, "fiscalYear": fiscal_year, "quarter": quarter, "section": section, "amountMinor": amount_minor,
                        "depositDate": deposit_date.isoformat()}, reason=note)
    outbox.emit(session, "tds.challan.recorded", "TDS_CHALLAN", row.id, f"{bsr_code}/{challan_no}",
                {"companyCode": company_code, "fiscalYear": fiscal_year, "quarter": quarter, "section": section, "amountMinor": amount_minor})
    return row


def void_challan(session: Session, challan_id: uuid.UUID, reason: str) -> TdsChallan:
    if "payment:run" not in principal(session).scopes:
        raise Problem(403, "FORBIDDEN", "TDS challans are voided by finance")
    if len((reason or "").strip()) < 5:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for voiding the challan")
    row = session.execute(select(TdsChallan).where(TdsChallan.id == challan_id).with_for_update()).scalar_one_or_none()
    if row is None:
        raise not_found("TDS challan", challan_id)
    if row.status == "VOID":
        raise Problem(409, "ILLEGAL_TRANSITION", "The challan is already void")
    row.status, row.void_reason = "VOID", reason
    audit.record(session, "TDS_CHALLAN", row.id, "VOIDED", object_ref=f"{row.bsr_code}/{row.challan_no}", reason=reason)
    return row


def challan_view(row: TdsChallan) -> dict:
    return {"id": str(row.id), "companyCode": row.company_code, "fiscalYear": row.fiscal_year, "quarter": row.quarter, "section": row.section,
            "challanNo": row.challan_no, "bsrCode": row.bsr_code, "depositDate": row.deposit_date.isoformat(), "amountMinor": row.amount_minor,
            "status": row.status, "note": row.note}


def challans(session: Session, fiscal_year: Optional[str] = None, quarter: Optional[str] = None, company_codes: Optional[list[str]] = None) -> list[dict]:
    query = select(TdsChallan).order_by(TdsChallan.deposit_date.desc(), TdsChallan.challan_no)
    if fiscal_year:
        query = query.where(TdsChallan.fiscal_year == fiscal_year)
    if quarter:
        query = query.where(TdsChallan.quarter == quarter)
    if company_codes is not None:
        query = query.where(TdsChallan.company_code.in_(company_codes))
    return [challan_view(r) for r in session.execute(query.limit(1000)).scalars()]


def deducted(session: Session, fiscal_year: str, quarter: str, company_codes: Optional[list[str]] = None) -> dict[tuple[str, str], int]:
    """TDS deducted by completed payments dated in the quarter, per company code and section."""
    first, last = finance_controls.quarter_range(fiscal_year, quarter)
    query = (select(Invoice.company_code, Invoice.tds_section, func.sum(TDS_INR)).join(Invoice, Invoice.id == Payment.invoice_id)
             .where(Payment.status == "COMPLETED", Payment.tds_minor > 0, Payment.value_date >= first, Payment.value_date <= last)
             .group_by(Invoice.company_code, Invoice.tds_section))
    if company_codes is not None:
        query = query.where(Invoice.company_code.in_(company_codes))
    return {(company, section or "UNKNOWN"): int(total) for company, section, total in session.execute(query).all()}


def reconciliation(session: Session, fiscal_year: str, quarter: str, company_codes: Optional[list[str]] = None) -> dict:
    """Deducted against deposited per company code and section for the quarter: the difference (deducted - deposited) is what is still to be deposited
    (positive) or deposited in excess (negative). Voided challans do not count."""
    first, last = finance_controls.quarter_range(fiscal_year, quarter)
    taken = deducted(session, fiscal_year, quarter, company_codes)
    query = (select(TdsChallan.company_code, TdsChallan.section, func.sum(TdsChallan.amount_minor), func.count())
             .where(TdsChallan.fiscal_year == fiscal_year, TdsChallan.quarter == quarter, TdsChallan.status == "RECORDED")
             .group_by(TdsChallan.company_code, TdsChallan.section))
    if company_codes is not None:
        query = query.where(TdsChallan.company_code.in_(company_codes))
    deposited = {(company, section): (int(total), int(count)) for company, section, total, count in session.execute(query).all()}
    rows = []
    for key in sorted(set(taken) | set(deposited)):
        out, (dep, count) = taken.get(key, 0), deposited.get(key, (0, 0))
        diff = out - dep
        rows.append({"companyCode": key[0], "section": key[1], "returnForm": nonresident_tax.return_form(key[1]), "deductedMinor": out,
                     "depositedMinor": dep, "challans": count, "differenceMinor": diff,
                     "status": "RECONCILED" if diff == 0 else "SHORT_DEPOSITED" if diff > 0 else "EXCESS_DEPOSITED"})
    by_form = {form: {"deductedMinor": sum(r["deductedMinor"] for r in rows if r["returnForm"] == form),
                      "depositedMinor": sum(r["depositedMinor"] for r in rows if r["returnForm"] == form)} for form in ("26Q", "27Q")}
    return {"fiscalYear": fiscal_year, "quarter": quarter, "from": first.isoformat(), "to": last.isoformat(), "rows": rows, "byReturnForm": by_form,
            "deductedMinor": sum(r["deductedMinor"] for r in rows), "depositedMinor": sum(r["depositedMinor"] for r in rows),
            "differenceMinor": sum(r["differenceMinor"] for r in rows), "reconciled": all(r["differenceMinor"] == 0 for r in rows)}


# ---------------------------------------------------------------- Form 16A data
def certificate_data(session: Session, fiscal_year: str, quarter: str, supplier_code: Optional[str] = None,
                     company_codes: Optional[list[str]] = None) -> dict:
    """Form 16A (TDS certificate for non-salary payments) data per deductee, company code and section for the quarter: deductor, deductee, every
    payment with the amount paid, the tax deducted and the date of deduction, the challans of the section and the tax deposited attributable to the
    deductee (pro rata to the tax deducted). ``missingMandatory`` lists what the platform cannot fill (the deductor's TAN and PAN, the deductee's PAN)."""
    first, last = finance_controls.quarter_range(fiscal_year, quarter)
    query = (select(Payment, Invoice, Supplier).join(Invoice, Invoice.id == Payment.invoice_id).join(Supplier, Supplier.id == Payment.supplier_id)
             .where(Payment.status == "COMPLETED", Payment.value_date >= first, Payment.value_date <= last,
                    (Payment.tds_minor > 0) | Payment.tds_certificate.is_not(None))
             .order_by(Supplier.code, Invoice.company_code, Payment.value_date, Payment.number))
    if supplier_code:
        query = query.where(Supplier.code == supplier_code)
    if company_codes is not None:
        query = query.where(Invoice.company_code.in_(company_codes))
    groups: dict[tuple[str, str, str], dict] = {}
    for payment, invoice, supplier in session.execute(query).all():
        key = (invoice.company_code, supplier.code, invoice.tds_section or "UNKNOWN")
        group = groups.setdefault(key, {"supplier": supplier, "payments": []})
        group["payments"].append((payment, invoice))
    chal = {}
    for row in session.execute(select(TdsChallan).where(TdsChallan.fiscal_year == fiscal_year, TdsChallan.quarter == quarter, TdsChallan.status == "RECORDED")
                               .order_by(TdsChallan.deposit_date)).scalars():
        chal.setdefault((row.company_code, row.section), []).append(row)
    section_total: dict[tuple[str, str], int] = {}
    for (company, _, section), group in groups.items():
        section_total[(company, section)] = section_total.get((company, section), 0) + sum(_tds_inr(p) for p, _ in group["payments"])
    certificates = []
    for (company, code, section), group in sorted(groups.items()):
        supplier = group["supplier"]
        rule = finance_controls.rule_body(session, "TDS", finance_controls.TDS_DEFAULT, company_code=company)
        deductor = {**{"tan": None, "pan": None, "name": None, "address": None}, **(rule.get("deductor") or {})}
        company_row = session.execute(select(CompanyCode).where(CompanyCode.code == company)).scalar_one_or_none()
        deductor["name"] = deductor["name"] or (company_row.name if company_row else None)
        form = nonresident_tax.return_form(section)
        residency = nonresident_tax.residency_of(session, supplier.id)
        gstin = finance_controls.supplier_gstin(session, supplier) if form == "26Q" else ""
        pan = (gstin[2:12] if len(gstin) == 15 else None) or nonresident_tax.pan_of(residency)
        paid = sum(_base_inr(p) for p, _ in group["payments"])
        tds = sum(_tds_inr(p) for p, _ in group["payments"])
        challan_rows = chal.get((company, section), [])
        pool = sum(c.amount_minor for c in challan_rows)
        share = int(pool * tds / section_total[(company, section)]) if section_total.get((company, section)) else 0
        missing = [f for f, v in (("deductor.tan", deductor["tan"]), ("deductor.pan", deductor["pan"]), ("deductee.pan", pan)) if not v]
        certificates.append({
            "form": "16A", "financialYear": fiscal_year, "assessmentYear": assessment_year(fiscal_year), "quarter": quarter, "periodFrom": first.isoformat(),
            "periodTo": last.isoformat(), "companyCode": company, "certificateNo": None,
            "returnForm": form,
            "deductor": deductor, "deductee": {"supplier": code, "name": supplier.legal_name, "pan": pan or "PANNOTAVBL",
                                               "residency": residency.residency if residency is not None else "RESIDENT",
                                               "country": residency.country if residency is not None else (supplier.country or "IN"),
                                               "address": supplier.address or {}},
            "section": section, "sectionLabel": (_sections(session, company).get(section) or {}).get("label"),
            "payments": [{"payment": p.number, "invoice": i.number, "dateOfPaymentCredit": p.value_date.isoformat(), "amountPaidCreditedMinor": _base_inr(p),
                          "ratePct": str(p.tds_rate) if p.tds_rate is not None else None, "taxDeductedMinor": _tds_inr(p),
                          "dateOfDeduction": p.value_date.isoformat(), "certificate197": p.tds_certificate,
                          **({"basis": (p.tax_detail or {}).get("basis"), "dtaaArticle": ((p.tax_detail or {}).get("treaty") or {}).get("article"),
                              "grossedUp": bool((p.tax_detail or {}).get("grossUp")), "currency": p.currency, "taxInCurrencyMinor": int(p.tds_minor),
                              "fxRate": (p.tax_detail or {}).get("fxRate")} if form == "27Q" else {})} for p, i in group["payments"]],
            "totals": {"amountPaidCreditedMinor": int(paid), "taxDeductedMinor": int(tds), "taxDepositedMinor": share},
            "challans": [{"bsrCode": c.bsr_code, "challanSerialNo": c.challan_no, "depositDate": c.deposit_date.isoformat(), "challanAmountMinor": c.amount_minor}
                         for c in challan_rows],
            "depositAllocation": "PRO_RATA_BY_TAX_DEDUCTED", "missingMandatory": missing})
    return {"fiscalYear": fiscal_year, "quarter": quarter, "certificates": certificates, "count": len(certificates)}


def _tds_inr(payment: Payment) -> int:
    return int(payment.tds_inr_minor) if payment.tds_inr_minor is not None else int(payment.tds_minor)


def _base_inr(payment: Payment) -> int:
    return int(payment.tds_base_inr_minor) if payment.tds_base_inr_minor is not None else int(payment.tds_base_minor)


def certificate_pdf(data: dict, supplier_code: str) -> bytes:
    """The information copy of the Form 16A data of one deductee and quarter as PDF (one page or more per certificate)."""
    from app.pic.services import form16a_pdf
    certificates = [c for c in data["certificates"] if c["deductee"]["supplier"] == supplier_code]
    if not certificates:
        raise Problem(404, "NOT_FOUND", f"No TDS was deducted from supplier {supplier_code} in {data['fiscalYear']} {data['quarter']}")
    return form16a_pdf.render(certificates)


def certificate_csv(data: dict) -> str:
    """One line per payment of every certificate with the mandatory 16A columns."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(["Financial Year", "Assessment Year", "Quarter", "Deductor TAN", "Deductor PAN", "Deductor Name", "Deductee PAN", "Deductee Name", "Section",
                     "Date of Payment/Credit", "Amount Paid/Credited", "Rate %", "Tax Deducted", "Date of Deduction", "Certificate u/s 197", "Payment",
                     "Invoice", "BSR Code", "Challan Serial No", "Deposit Date", "Tax Deposited (deductee share)"])
    money = lambda minor: f"{minor / 100:.2f}"  # noqa: E731
    for cert in data["certificates"]:
        challan = cert["challans"][0] if cert["challans"] else {}
        for line in cert["payments"]:
            writer.writerow([finance_controls._safe(x) for x in (
                cert["financialYear"], cert["assessmentYear"], cert["quarter"], cert["deductor"]["tan"] or "", cert["deductor"]["pan"] or "", cert["deductor"]["name"] or "",
                cert["deductee"]["pan"], cert["deductee"]["name"], cert["section"], line["dateOfPaymentCredit"], money(line["amountPaidCreditedMinor"]),
                line["ratePct"] or "", money(line["taxDeductedMinor"]), line["dateOfDeduction"], line["certificate197"] or "", line["payment"], line["invoice"],
                challan.get("bsrCode", ""), challan.get("challanSerialNo", ""), challan.get("depositDate", ""), money(cert["totals"]["taxDepositedMinor"]))])
    return out.getvalue()
