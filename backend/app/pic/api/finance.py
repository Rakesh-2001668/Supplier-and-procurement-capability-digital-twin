"""M10 finance controls (F7): payment proposal, payments, bank results per payment, posting periods (cut-off), TDS register,
supplier finance attributes (MSME class, TDS section). Every write is audited; unsafe repeats are refused or replayed."""
import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, Header, Query, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.pic.api.deps import idempotency_key, idempotent, uow
from app.pic.api.pagination import Page, paginate
from app.pic.config import get_settings
from app.pic.models import Invoice, Payment, Supplier
from app.pic.platform import audit, crypto
from app.pic.platform.auth import READ, Principal, require, require_any
from app.pic.platform.core import check_if_match, etag
from app.pic.platform.errors import Problem, not_found
from app.pic.platform.serialize import row
from app.pic.services import bank_files, bank_statement, finance_controls, finance_scope, master_changes, payables, tds_returns
from app.pic.services.common import supplier_ref

router = APIRouter(prefix="/v1", tags=["M10 Finance"])


# ---------------------------------------------------------------- payment proposal and payments
@router.get("/payments/proposal")
def proposal(run_date: date, include_not_due: bool = False, supplier: list[str] = Query(default=[]), invoice: list[str] = Query(default=[]),
             p: Principal = Depends(require("payment:run"))):
    """What a payment run on run_date would pay and skip (and why); nothing is written and no ERP is called."""
    with uow(p) as s:
        return payables.payment_proposal(s, run_date, include_not_due, supplier or None, invoice or None)


@router.get("/payments")
def payments(run: Optional[str] = None, supplier: Optional[str] = None, bank_status: Optional[str] = None, status: Optional[str] = None,
             invoice: Optional[str] = None, page: Page = Depends(), p: Principal = Depends(require(READ))):
    with uow(p) as s:
        query = select(Payment)
        if (allowed := finance_scope.companies(s)) is not None:  # ABAC read scope
            query = query.where(Payment.invoice_id.in_(select(Invoice.id).where(Invoice.company_code.in_(allowed))))
        if run:
            query = query.where(Payment.run_ref == run)
        if supplier:
            query = query.where(Payment.supplier_id == supplier_ref(s, supplier).id)
        if bank_status:
            query = query.where(Payment.bank_status.in_([x.strip().upper() for x in bank_status.split(",")]))
        if status:
            query = query.where(Payment.status.in_([x.strip().upper() for x in status.split(",")]))
        if invoice:
            query = query.where(Payment.invoice_id.in_(select(Invoice.id).where(Invoice.number == invoice)))
        result = paginate(s, query, Payment, page, lambda x: {k: v for k, v in row(x).items() if k != "bank_account_id"})
        # supplier code and invoice number of the page only (one query each), not of every supplier and invoice of the tenant
        suppliers = {str(i): c for i, c in s.execute(select(Supplier.id, Supplier.code).where(Supplier.id.in_({uuid.UUID(str(x["supplier_id"])) for x in result["items"]}))).all()}
        invoices = {str(i): n for i, n in s.execute(select(Invoice.id, Invoice.number).where(Invoice.id.in_({uuid.UUID(str(x["invoice_id"])) for x in result["items"]}))).all()}
        for item in result["items"]:
            item["supplier_code"], item["invoice_number"] = suppliers.get(str(item["supplier_id"])), invoices.get(str(item["invoice_id"]))
        return result


class BankResultIn(BaseModel):
    payment: str = Field(min_length=1, max_length=30)
    status: str = Field(pattern="^(CREDITED|RETURNED)$")
    utr: Optional[str] = Field(default=None, max_length=40)
    reason: Optional[str] = Field(default=None, max_length=500)


class BankResultsIn(BaseModel):
    items: list[BankResultIn] = Field(min_length=1, max_length=500)


@router.post("/payment-files/{number}/bank-results")
def bank_results(number: str, body: BankResultsIn, p: Principal = Depends(require("payment:run")), key: Optional[str] = Depends(idempotency_key)):
    """The bank's answer per payment: CREDITED with the UTR, or RETURNED with the reason (the invoice becomes payable again)."""
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/payment-files/{number}/bank-results", key, body)
        if idem.replay:
            return idem.replay
        pf = bank_files.by_number(s, number, lock=True)
        return idem.store(bank_files.record_bank_results(s, pf, [i.model_dump() for i in body.items]))


@router.get("/payment-files/{number}/reconciliation")
def payment_file_reconciliation(number: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return bank_files.file_reconciliation(s, bank_files.by_number(s, number))


# ---------------------------------------------------------------- posting periods (cut-off)
class PeriodIn(BaseModel):
    companyCode: str = Field(min_length=1, max_length=10)
    reason: Optional[str] = Field(default=None, max_length=500)


class ReopenIn(BaseModel):
    companyCode: str = Field(min_length=1, max_length=10)
    reason: str = Field(min_length=10, max_length=500)


def _view(period) -> dict:
    return {"id": str(period.id), "companyCode": period.company_code, "period": period.period, "status": period.status,
            "closedAt": period.closed_at.isoformat() if period.closed_at else None, "reason": period.reason, "cutoff": period.cutoff}


@router.get("/finance/periods")
def list_periods(company_code: Optional[str] = None, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        finance_scope.guard_company(s, company_code)
        allowed = finance_scope.companies(s)
        return {"items": [x for x in finance_controls.periods(s, company_code) if allowed is None or x["companyCode"] in allowed]}


@router.get("/finance/periods/{period}/cutoff")
def period_cutoff(period: str, company_code: str, p: Principal = Depends(require(READ))):
    """What closing the period would leave in flight (unposted invoices, GR/IR accrual): a preview, nothing is closed."""
    with uow(p) as s:
        finance_scope.guard_company(s, company_code)
        return finance_controls.cutoff_snapshot(s, company_code, period)


@router.post("/finance/periods/{period}/close")
def close_period(period: str, body: PeriodIn, p: Principal = Depends(require("period:close")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/finance/periods/{period}/close", key, body)
        if idem.replay:
            return idem.replay
        return idem.store(_view(finance_controls.close_period(s, body.companyCode, period, body.reason)))


@router.post("/finance/periods/{period}/reopen")
def reopen_period(period: str, body: ReopenIn, p: Principal = Depends(require("period:close")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/finance/periods/{period}/reopen", key, body)
        if idem.replay:
            return idem.replay
        return idem.store(_view(finance_controls.reopen_period(s, body.companyCode, period, body.reason)))


# ---------------------------------------------------------------- TDS and MSME
@router.get("/finance/tds-register")
def tds_register(fiscal_year: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"), supplier: Optional[str] = None,
                 p: Principal = Depends(require(READ))):
    """TDS withheld from completed payments by supplier and section (source of the quarterly TDS return)."""
    with uow(p) as s:
        return finance_controls.tds_register(s, fiscal_year, supplier, company_codes=finance_scope.companies(s))


@router.get("/finance/controls")
def controls(p: Principal = Depends(require(READ))):
    """The effective MSME and TDS rules (tenant rule sets, else the documented defaults)."""
    with uow(p) as s:
        return {"msme": finance_controls.rule_body(s, "MSME", finance_controls.MSME_DEFAULT),
                "tds": finance_controls.rule_body(s, "TDS", finance_controls.TDS_DEFAULT)}


UDYAM_RE = re.compile(r"^UDYAM-[A-Z]{2}-\d{2}-\d{7}$")


class SupplierFinanceIn(BaseModel):
    msmeClass: Optional[str] = Field(default=None, pattern="^(MICRO|SMALL|MEDIUM)$")
    udyamNo: Optional[str] = Field(default=None, max_length=30)
    tdsSection: Optional[str] = Field(default=None, max_length=20)
    pan: Optional[str] = Field(default=None, max_length=10, description="Set the supplier's PAN (kept as a hash); omitted leaves it unchanged")
    msmeWrittenAgreement: Optional[bool] = Field(default=None, description="MSMED Act s.15: false = no written payment agreement (paid within 15 days of acceptance); omitted leaves it unchanged")
    reason: str = Field(min_length=3, max_length=500)


def _finance_view(s, supplier) -> dict:
    gstin = finance_controls.supplier_gstin(s, supplier)
    return {"supplier": supplier.code, "name": supplier.legal_name, "etag": etag(supplier), "msmeClass": supplier.msme_class, "udyamNo": supplier.udyam_no,
            "tdsSection": supplier.tds_section, "panOnFile": supplier.pan_hash is not None,
            "msmeWrittenAgreement": supplier.msme_written_agreement,
            "panFromGstin": (crypto.mask(gstin[2:12]) if len(gstin) == 15 else None), "gstinOnFile": bool(gstin),
            "isMsme": finance_controls.is_msme(s, supplier), "certificates": finance_controls.certificates_of(s, supplier),
            "tdsSections": {k: {"label": v.get("label"), "ratePct": v.get("ratePct")}
                            for k, v in (finance_controls.rule_body(s, "TDS", finance_controls.TDS_DEFAULT).get("sections") or {}).items()}}


@router.get("/suppliers/{code}/finance")
def get_supplier_finance(code: str, response: Response, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        supplier = supplier_ref(s, code)
        response.headers["ETag"] = etag(supplier)
        return _finance_view(s, supplier)


@router.put("/suppliers/{code}/finance")
def set_supplier_finance(code: str, body: SupplierFinanceIn, response: Response, p: Principal = Depends(require_any("supplier:manage", "payment:run")),
                         if_match: Optional[str] = Header(default=None, alias="If-Match")):
    """MSME class (Udyam), PAN and TDS section of the supplier: they decide the payment due date and what a payment keeps back."""
    if if_match is None and get_settings().if_match_required:
        raise Problem(428, "PRECONDITION_REQUIRED", "Send If-Match with the ETag of GET /v1/suppliers/{code}/finance")
    with uow(p) as s:
        supplier = supplier_ref(s, code)
        s.refresh(supplier, with_for_update=True)
        check_if_match(supplier, if_match)
        finance_controls.set_supplier_finance(s, supplier, msme_class=body.msmeClass, udyam_no=body.udyamNo, tds_section=body.tdsSection, pan=body.pan,
                                              msme_written_agreement=body.msmeWrittenAgreement, reason=body.reason)
        response.headers["ETag"] = etag(supplier)
        return _finance_view(s, supplier)


# ---------------------------------------------------------------- s.197 lower-deduction certificates
class CertificateIn(BaseModel):
    certificateNo: str = Field(min_length=6, max_length=40)
    section: Optional[str] = Field(default=None, max_length=20)
    ratePct: Decimal = Field(ge=0, le=100)
    validFrom: date
    validTo: date
    maxBaseMinor: Optional[int] = Field(default=None, gt=0, description="Amount cap of the certificate (paise of taxable base); beyond it the section rate applies")
    note: Optional[str] = Field(default=None, max_length=500)


class RevokeIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


@router.post("/suppliers/{code}/tds-certificates", status_code=201)
def add_certificate(code: str, body: CertificateIn, p: Principal = Depends(require_any("supplier:manage", "payment:run")),
                    key: Optional[str] = Depends(idempotency_key)):
    """A certificate under s.197 (lower or nil deduction): its rate replaces the section rate for payments dated inside its validity."""
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/suppliers/{code}/tds-certificates", key, body)
        if idem.replay:
            return idem.replay
        supplier = supplier_ref(s, code)
        finance_controls.add_certificate(s, supplier, certificate_no=body.certificateNo, rate_pct=body.ratePct, valid_from=body.validFrom,
                                         valid_to=body.validTo, section=body.section, note=body.note, max_base_minor=body.maxBaseMinor)
        return idem.store({"supplier": supplier.code, "certificates": finance_controls.certificates_of(s, supplier)}, 201)


@router.post("/suppliers/{code}/tds-certificates/{certificate_no:path}/revoke")
def revoke_certificate(code: str, certificate_no: str, body: RevokeIn, p: Principal = Depends(require_any("supplier:manage", "payment:run"))):
    with uow(p) as s:
        supplier = supplier_ref(s, code)
        finance_controls.revoke_certificate(s, supplier, certificate_no, body.reason)
        return {"supplier": supplier.code, "certificates": finance_controls.certificates_of(s, supplier)}


@router.get("/finance/tds-export")
def tds_export(fiscal_year: str = Query(pattern=r"^\d{4}-\d{2}$"), quarter: str = Query(pattern="^Q[1-4]$"), format: str = Query("26Q", pattern="^(26Q|16A)$"),
               p: Principal = Depends(require("payment:run"))):
    """Form 26Q / 16A style CSV of the TDS deducted in a quarter (finance only; every export is audited with its hash)."""
    with uow(p) as s:
        result = finance_controls.tds_export(s, fiscal_year, quarter, format, company_codes=finance_scope.companies(s))
        return Response(content=result["content"].encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{result["fileName"]}"', "X-Content-SHA256": result["sha256"],
                                 "X-Row-Count": str(result["rows"])})


@router.get("/finance/periods/{period}/grir-snapshots")
def period_grir_snapshots(period: str, company_code: Optional[str] = None, p: Principal = Depends(require(READ))):
    """The GR/IR accrual persisted at each close of the period (line by line)."""
    with uow(p) as s:
        return {"items": finance_controls.grir_snapshots(s, period, company_code)}


# ---------------------------------------------------------------- bank statement import (camt.053 / MT940)
@router.post("/bank-statements/import")
def import_bank_statement(file: UploadFile = File(...), dry_run: bool = Query(True), p: Principal = Depends(require("payment:run"))):
    """Read a bank statement and record what it says about the payments: dry run (default) shows what would happen, ``dry_run=false`` applies it.
    Idempotent per statement id."""
    data = file.file.read(bank_statement.MAX_BYTES + 1)
    with uow(p) as s:
        return bank_statement.run_import(s, data, dry_run=dry_run)


@router.get("/bank-statements")
def bank_statements(p: Principal = Depends(require("payment:run"))):
    with uow(p) as s:
        return {"items": bank_statement.listing(s)}


# ---------------------------------------------------------------- TDS challans, reconciliation, Form 16A data
class ChallanIn(BaseModel):
    companyCode: str = Field(min_length=1, max_length=10)
    fiscalYear: str = Field(pattern=r"^\d{4}-\d{2}$")
    quarter: str = Field(pattern="^Q[1-4]$")
    section: str = Field(min_length=1, max_length=20)
    challanNo: str = Field(pattern=r"^[0-9]{5}$")
    bsrCode: str = Field(pattern=r"^[0-9]{7}$")
    depositDate: date
    amountMinor: int = Field(gt=0)
    note: Optional[str] = Field(default=None, max_length=500)


@router.post("/finance/tds-challans", status_code=201)
def record_tds_challan(body: ChallanIn, p: Principal = Depends(require("payment:run")), key: Optional[str] = Depends(idempotency_key)):
    """Record a TDS deposit challan (BSR code, challan serial, deposit date) against the quarter and section it pays."""
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/finance/tds-challans", key, body)
        if idem.replay:
            return idem.replay
        finance_scope.guard_company(s, body.companyCode)
        row_ = tds_returns.record_challan(s, company_code=body.companyCode, fiscal_year=body.fiscalYear, quarter=body.quarter, section=body.section,
                                          challan_no=body.challanNo, bsr_code=body.bsrCode, deposit_date=body.depositDate, amount_minor=body.amountMinor,
                                          note=body.note)
        return idem.store(tds_returns.challan_view(row_), 201)


class VoidChallanIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


@router.post("/finance/tds-challans/{challan_id}/void")
def void_tds_challan(challan_id: uuid.UUID, body: VoidChallanIn, p: Principal = Depends(require("payment:run")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/finance/tds-challans/{challan_id}/void", key, body)
        if idem.replay:
            return idem.replay
        return idem.store(tds_returns.challan_view(tds_returns.void_challan(s, challan_id, body.reason)))


@router.get("/finance/tds-challans")
def list_tds_challans(fiscal_year: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"), quarter: Optional[str] = Query(None, pattern="^Q[1-4]$"),
                      p: Principal = Depends(require("payment:run"))):
    with uow(p) as s:
        return {"items": tds_returns.challans(s, fiscal_year, quarter, company_codes=finance_scope.companies(s))}


@router.get("/finance/tds-challans/reconciliation")
def tds_challan_reconciliation(fiscal_year: str = Query(pattern=r"^\d{4}-\d{2}$"), quarter: str = Query(pattern="^Q[1-4]$"), p: Principal = Depends(require("payment:run"))):
    """TDS deducted against deposited per company code and section for the quarter, with the difference."""
    with uow(p) as s:
        return tds_returns.reconciliation(s, fiscal_year, quarter, company_codes=finance_scope.companies(s))


@router.get("/finance/tds-certificates/data")
def tds_certificate_data(fiscal_year: str = Query(pattern=r"^\d{4}-\d{2}$"), quarter: str = Query(pattern="^Q[1-4]$"), supplier: Optional[str] = None,
                         format: str = Query("json", pattern="^(json|csv)$"), p: Principal = Depends(require("payment:run"))):
    """Form 16A data per deductee and quarter (JSON or CSV; the certificate itself is generated in TRACES). Every export is audited."""
    with uow(p) as s:
        data = tds_returns.certificate_data(s, fiscal_year, quarter, supplier, company_codes=finance_scope.companies(s))
        audit.record(s, "TDS_EXPORT", uuid.uuid5(uuid.NAMESPACE_URL, f"tds-16a:{p.tenant_id}:{fiscal_year}:{quarter}"), "EXPORTED",
                     object_ref=f"{fiscal_year}/{quarter}/16A-DATA", after={"certificates": data["count"], "supplier": supplier, "format": format})
        if format == "csv":
            return Response(content=tds_returns.certificate_csv(data).encode("utf-8"), media_type="text/csv; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="FORM16A_{fiscal_year}_{quarter}.csv"'})
        return data


@router.get("/finance/msme-interest")
def msme_interest(supplier: Optional[str] = None, p: Principal = Depends(require(READ))):
    """Interest accrued on late payments to MSME suppliers (recorded when the tenant publishes the bank rate in rule MSME)."""
    with uow(p) as s:
        return finance_controls.msme_interest_register(s, supplier, company_codes=finance_scope.companies(s))
