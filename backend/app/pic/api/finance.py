"""M10 finance controls (F7): payment proposal, payments, bank results per payment, posting periods (cut-off), TDS register,
supplier finance attributes (MSME class, TDS section). Every write is audited; unsafe repeats are refused or replayed."""
import re
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
from app.pic.services import bank_files, bank_statement, finance_controls, master_changes, payables
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
        codes = {sup.id: sup.code for sup in s.execute(select(Supplier)).scalars()}
        numbers = {i.id: i.number for i in s.execute(select(Invoice)).scalars()}
        return paginate(s, query, Payment, page, lambda x: {
            k: v for k, v in row(x, extra={"supplier_code": codes.get(x.supplier_id), "invoice_number": numbers.get(x.invoice_id)}).items()
            if k != "bank_account_id"})


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
        return {"items": finance_controls.periods(s, company_code)}


@router.get("/finance/periods/{period}/cutoff")
def period_cutoff(period: str, company_code: str, p: Principal = Depends(require(READ))):
    """What closing the period would leave in flight (unposted invoices, GR/IR accrual): a preview, nothing is closed."""
    with uow(p) as s:
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
        return finance_controls.tds_register(s, fiscal_year, supplier)


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
    reason: str = Field(min_length=3, max_length=500)


def _finance_view(s, supplier) -> dict:
    gstin = crypto.decrypt(supplier.tenant_id, "gstin", supplier.gstin_enc) if supplier.gstin_enc else ""
    return {"supplier": supplier.code, "name": supplier.legal_name, "etag": etag(supplier), "msmeClass": supplier.msme_class, "udyamNo": supplier.udyam_no,
            "tdsSection": supplier.tds_section, "panOnFile": supplier.pan_hash is not None,
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
        errors = []
        if body.tdsSection:
            sections = (finance_controls.rule_body(s, "TDS", finance_controls.TDS_DEFAULT).get("sections") or {})
            if body.tdsSection not in sections:
                raise Problem(422, "TDS_SECTION_UNKNOWN", f"TDS section {body.tdsSection} is not defined in rule set TDS ({', '.join(sorted(sections))})")
        udyam = (body.udyamNo or "").strip().upper() or None
        if udyam and not UDYAM_RE.match(udyam):
            errors.append("Udyam registration number must look like UDYAM-KA-03-0012345 (state, district, seven digits)")
        if body.msmeClass and not (udyam or supplier.udyam_no):
            raise Problem(422, "UDYAM_REQUIRED", "An MSME class needs the Udyam registration number")
        pan = (body.pan or "").strip().upper() or None
        if pan:
            errors += master_changes.pan_errors(pan)
            gstin = crypto.decrypt(supplier.tenant_id, "gstin", supplier.gstin_enc) if supplier.gstin_enc else ""
            if len(gstin) == 15 and gstin[2:12] != pan:
                errors.append("the PAN must be the one inside the supplier's GSTIN")
        if errors:
            raise Problem(422, "VALIDATION_FAILED", "; ".join(errors), rule_ref="MDM-04", errors=errors)
        before = {"msmeClass": supplier.msme_class, "udyamNo": supplier.udyam_no, "tdsSection": supplier.tds_section, "panOnFile": supplier.pan_hash is not None}
        supplier.msme_class, supplier.udyam_no, supplier.tds_section = body.msmeClass, udyam or (supplier.udyam_no if body.msmeClass else None), body.tdsSection
        if pan:
            supplier.pan_hash = crypto.blind_index(supplier.tenant_id, pan)
        s.flush()
        after = {"msmeClass": supplier.msme_class, "udyamNo": supplier.udyam_no, "tdsSection": supplier.tds_section, "panOnFile": supplier.pan_hash is not None,
                 **({"panSet": crypto.mask(pan)} if pan else {})}
        audit.record(s, "SUPPLIER", supplier.id, "FINANCE_ATTRIBUTES_CHANGED", object_ref=supplier.code, before=before, after=after, reason=body.reason)
        response.headers["ETag"] = etag(supplier)
        return _finance_view(s, supplier)


# ---------------------------------------------------------------- s.197 lower-deduction certificates
class CertificateIn(BaseModel):
    certificateNo: str = Field(min_length=6, max_length=40)
    section: Optional[str] = Field(default=None, max_length=20)
    ratePct: Decimal = Field(ge=0, le=100)
    validFrom: date
    validTo: date
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
                                         valid_to=body.validTo, section=body.section, note=body.note)
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
        result = finance_controls.tds_export(s, fiscal_year, quarter, format)
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
