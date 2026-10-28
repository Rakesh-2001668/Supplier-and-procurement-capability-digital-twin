"""F5 purchase orders, F6 receiving and quality, F7 invoices and payments."""
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.pic import views
from app.pic.api.deps import idempotency_key, idempotent, uow
from app.pic.models import Asn, GoodsReceipt, InspectionLot, Invoice, PurchaseOrder, ServiceEntry
from app.pic.platform import workflow
from app.pic.platform.auth import READ, Principal, require, require_any
from app.pic.platform.core import check_if_match, etag
from app.pic.platform.errors import Problem, not_found
from app.pic.platform.serialize import row, rows
from app.pic.services import order, payables, receiving
from app.pic.services.common import by_ref

router = APIRouter(prefix="/v1")


# ---------------------------------------------------------------- F5 purchase orders
class PoSource(BaseModel):
    type: str = Field(pattern="^REQUISITION$")
    id: str
    lines: list[int]


class PoRelease(BaseModel):
    qty: Optional[Decimal] = None
    needDate: Optional[date] = None


class PoIn(BaseModel):
    source: PoSource
    supplierId: Optional[str] = None
    contractRef: Optional[str] = None
    release: Optional[PoRelease] = None
    unitPriceMinor: Optional[int] = None
    deviationReason: Optional[str] = None


@router.post("/purchase-orders", status_code=201, tags=["F5 Purchase Order"])
def create_po(body: PoIn, p: Principal = Depends(require("po:create")), key: Optional[str] = Depends(idempotency_key)):
    """Create PO(s) from an approved requisition. Price and terms are inherited (P07); the response mirrors §10.2."""
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/purchase-orders", key, body)
        if idem.replay:
            return idem.replay
        pos = order.create_from_requisition(
            s, requisition=body.source.id, lines=body.source.lines, supplier_code=body.supplierId, contract_ref=body.contractRef,
            release_qty=body.release.qty if body.release else None, need_date=body.release.needDate if body.release else None,
            unit_price_minor=body.unitPriceMinor, deviation_reason=body.deviationReason)
        result = [{"id": po.number, "version": po.version, "status": po.status,
                   "inherited": {"price": po.inherited.get("price", 0) / 100 if po.inherited.get("price") else None,
                                 "paymentTerms": po.payment_terms, "incoterms": po.incoterms,
                                 "tolerance": f"+{po.tolerance.get('over_pct', 0)}/-{po.tolerance.get('under_pct', 0)}"},
                   "validation": {"riskScore": po.risk_score, "touchless": po.touchless, "factors": po.risk_factors},
                   "lineage": order.lineage_refs(s, po)} for po in pos]
        return idem.store(result[0] if len(result) == 1 else {"purchaseOrders": result}, 201)


@router.get("/purchase-orders/{ref}", tags=["F5 Purchase Order"])
def get_po(ref: str, response: Response, p: Principal = Depends(require_any(READ, "supplier:portal"))):
    with uow(p) as s:
        po = by_ref(s, PurchaseOrder, ref)
        if "SUPPLIER_USER" in p.roles and po.supplier_id != p.supplier_id:
            raise not_found("Purchase order", ref)
        response.headers["ETag"] = etag(po)
        return views.purchase_order(s, po)


@router.post("/purchase-orders/{ref}/validate", tags=["F5 Purchase Order"])
def validate_po(ref: str, p: Principal = Depends(require("po:create"))):
    with uow(p) as s:
        return order.validate(s, by_ref(s, PurchaseOrder, ref, lock=True))


class ConfirmationIn(BaseModel):
    status: str = Field(pattern="^(CONFIRMED|CHANGE_REQUESTED|REJECTED)$")
    lines: Optional[list[dict]] = None
    note: Optional[str] = None


@router.post("/purchase-orders/{ref}/confirmations", tags=["F5 Purchase Order"])
def confirm_po(ref: str, body: ConfirmationIn, p: Principal = Depends(require("po:confirm"))):
    with uow(p) as s:
        return order.confirm(s, by_ref(s, PurchaseOrder, ref, lock=True), body.status, body.lines, body.note)


class ChangeIn(BaseModel):
    changes: list[dict]
    reason: str


@router.post("/purchase-orders/{ref}/versions", tags=["F5 Purchase Order"])
def change_po(ref: str, body: ChangeIn, p: Principal = Depends(require("po:change")),
              if_match: Optional[str] = Header(default=None, alias="If-Match")):
    with uow(p) as s:
        po = by_ref(s, PurchaseOrder, ref, lock=True)
        check_if_match(po, if_match)
        return order.change_order(s, po, body.changes, body.reason)


# ---------------------------------------------------------------- F6 receiving
class AsnLineIn(BaseModel):
    line: int
    qty: Decimal
    batches: list[dict] = []


class AsnIn(BaseModel):
    po: str
    lines: list[AsnLineIn]
    ship_date: date
    expected_date: date
    eway_bill_no: Optional[str] = None
    documents: list[str] = []


@router.post("/asns", status_code=201, tags=["F6 Receiving"])
def create_asn(body: AsnIn, p: Principal = Depends(require("asn:create"))):
    with uow(p) as s:
        po = by_ref(s, PurchaseOrder, body.po, lock=True)
        asn = receiving.create_asn(s, po, lines=[l.model_dump(mode="json") for l in body.lines], ship_date=body.ship_date,
                                   expected_date=body.expected_date, eway_bill_no=body.eway_bill_no, documents=body.documents)
        return views.asn(s, asn)


class GrLineIn(BaseModel):
    line: int
    qty: Decimal
    batch: str = ""
    storage_location: Optional[str] = None
    expiry: Optional[str] = None
    serials: list[str] = []


class GrIn(BaseModel):
    po: str
    asn: Optional[str] = None
    delivery_note: Optional[str] = None
    posting_date: Optional[date] = None
    lines: list[GrLineIn]


@router.post("/goods-receipts", status_code=201, tags=["F6 Receiving"])
def post_gr(body: GrIn, p: Principal = Depends(require("gr:post")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/goods-receipts", key, body)
        if idem.replay:
            return idem.replay
        po = by_ref(s, PurchaseOrder, body.po, lock=True)
        asn = by_ref(s, Asn, body.asn) if body.asn else None
        gr = receiving.post_gr(s, po, lines=[l.model_dump(mode="json") for l in body.lines], asn=asn, delivery_note=body.delivery_note,
                               posting_date=body.posting_date)
        return idem.store(views.goods_receipt(s, gr), 201)


@router.get("/goods-receipts/{ref}", tags=["F6 Receiving"])
def get_gr(ref: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return views.goods_receipt(s, by_ref(s, GoodsReceipt, ref))


class UsageDecisionIn(BaseModel):
    accepted: Decimal
    rejected: Decimal = Decimal(0)
    defect_code: Optional[str] = None
    reason: Optional[str] = None


@router.post("/inspection-lots/{ref}/usage-decision", tags=["F6 Receiving"])
def usage_decision(ref: str, body: UsageDecisionIn, p: Principal = Depends(require("quality:decide"))):
    with uow(p) as s:
        lot = by_ref(s, InspectionLot, ref, lock=True)
        return receiving.usage_decision(s, lot, **body.model_dump())


class ReverseIn(BaseModel):
    reason: str


@router.post("/goods-receipts/{ref}/reverse", tags=["F6 Receiving"])
def reverse(ref: str, body: ReverseIn, p: Principal = Depends(require("gr:post"))):
    with uow(p) as s:
        return row(receiving.reverse_gr(s, by_ref(s, GoodsReceipt, ref, lock=True), body.reason))


class SesLineIn(BaseModel):
    line: int
    description: Optional[str] = None
    qty: Decimal
    unit_rate: Optional[Decimal] = None


class SesIn(BaseModel):
    po: str
    method: str = Field(pattern="^(MILESTONE|TIME_MATERIAL|UNIT_RATE|PROGRESS)$")
    period_from: date
    period_to: date
    lines: list[SesLineIn]


@router.post("/service-entries", status_code=201, tags=["F6 Receiving"])
def create_ses(body: SesIn, p: Principal = Depends(require("ses:create"))):
    with uow(p) as s:
        po = by_ref(s, PurchaseOrder, body.po)
        ses = receiving.create_ses(s, po, method=body.method, period_from=body.period_from, period_to=body.period_to,
                                   lines=[l.model_dump(mode="json", exclude_none=True) for l in body.lines])
        receiving.submit_ses(s, ses)
        return views.service_entry(s, ses)


@router.post("/service-entries/{ref}/approve", tags=["F6 Receiving"])
def approve_ses(ref: str, p: Principal = Depends(require("ses:approve"))):
    with uow(p) as s:
        ses = by_ref(s, ServiceEntry, ref)
        tasks = [t for t in workflow.open_tasks_for(s, p) if t.object_id == ses.id]
        if not tasks:
            raise Problem(403, "NOT_YOUR_TASK", "No open approval for you on this service entry (approver must differ from the supplier and PO creator)")
        workflow.complete(s, tasks[0].id, "APPROVE")
        return views.service_entry(s, ses)


# ---------------------------------------------------------------- F7 invoices and payments
class InvoiceLineIn(BaseModel):
    po: str
    po_line: int
    qty: Decimal
    unit_price: Decimal
    gst_rate: Optional[Decimal] = None
    hsn: Optional[str] = None
    tax_minor: Optional[int] = None
    description: Optional[str] = None


class InvoiceIn(BaseModel):
    supplier: Optional[str] = None
    supplier_invoice_no: str
    invoice_date: date
    channel: str = Field(pattern="^(PORTAL|PDF_OCR|E_INVOICE|EDI)$")
    irn: Optional[str] = None
    company_code: str = "1000"
    lines: list[InvoiceLineIn]


@router.post("/invoices", status_code=201, tags=["F7 Invoice"])
def capture_invoice(body: InvoiceIn, p: Principal = Depends(require_any("invoice:capture", "invoice:submit")),
                    key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/invoices", key, body)
        if idem.replay:
            return idem.replay
        supplier = body.supplier or (str(p.supplier_id) if p.supplier_id else None)
        if supplier is None:
            raise Problem(422, "SUPPLIER_REQUIRED", "Give the supplier code")
        invoice = payables.capture(s, supplier=supplier, supplier_invoice_no=body.supplier_invoice_no, invoice_date=body.invoice_date,
                                   channel=body.channel, irn=body.irn, company_code=body.company_code,
                                   lines=[l.model_dump(mode="json", exclude_none=True) for l in body.lines])
        return idem.store(views.invoice(s, invoice), 201)


@router.get("/invoices/{ref}", tags=["F7 Invoice"])
def get_invoice(ref: str, p: Principal = Depends(require_any(READ, "supplier:portal"))):
    with uow(p) as s:
        invoice = by_ref(s, Invoice, ref)
        if "SUPPLIER_USER" in p.roles and invoice.supplier_id != p.supplier_id:
            raise not_found("Invoice", ref)
        return views.invoice(s, invoice)


@router.post("/invoices/{ref}/match", tags=["F7 Invoice"])
def rematch(ref: str, p: Principal = Depends(require("invoice:resolve"))):
    with uow(p) as s:
        return payables.match(s, by_ref(s, Invoice, ref, lock=True))


class CreditNoteIn(BaseModel):
    supplier_credit_note_no: str
    note_date: date
    reason: str
    lines: list[dict]


@router.post("/invoices/{ref}/credit-notes", status_code=201, tags=["F7 Invoice"])
def credit_note(ref: str, body: CreditNoteIn, p: Principal = Depends(require_any("invoice:submit", "invoice:capture"))):
    with uow(p) as s:
        return row(payables.submit_credit_note(s, by_ref(s, Invoice, ref, lock=True), **body.model_dump()))


class ResolveIn(BaseModel):
    resolution: str
    note: str
    credit_note: Optional[str] = None


@router.post("/invoices/{ref}/exceptions/{exception_id}/resolve", tags=["F7 Invoice"])
def resolve(ref: str, exception_id: uuid.UUID, body: ResolveIn, p: Principal = Depends(require("invoice:resolve"))):
    with uow(p) as s:
        return payables.resolve_exception(s, by_ref(s, Invoice, ref, lock=True), exception_id, body.resolution, body.note, body.credit_note)


class RejectIn(BaseModel):
    reason: str


@router.post("/invoices/{ref}/reject", tags=["F7 Invoice"])
def reject_invoice(ref: str, body: RejectIn, p: Principal = Depends(require("invoice:resolve"))):
    with uow(p) as s:
        return row(payables.reject(s, by_ref(s, Invoice, ref, lock=True), body.reason))


@router.post("/invoices/{ref}/approve", tags=["F7 Invoice"])
def approve_invoice(ref: str, p: Principal = Depends(require("invoice:approve"))):
    with uow(p) as s:
        return row(payables.approve(s, by_ref(s, Invoice, ref, lock=True)))


@router.post("/invoices/{ref}/post", tags=["F7 Invoice"])
def post_invoice(ref: str, p: Principal = Depends(require("invoice:post")),
                 key: Optional[str] = Header(default=None, alias="Idempotency-Key")):
    """Post to ERP exactly once. Retrying with the same Idempotency-Key returns the original result with replayed=true (§10.3)."""
    if not key:
        raise Problem(428, "IDEMPOTENCY_KEY_REQUIRED", "Send Idempotency-Key: tenant|company code|supplier|invoice number")
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/invoices/{ref}/post", key, {"invoice": ref})
        if idem.replay:
            return idem.replay
        result = payables.post(s, by_ref(s, Invoice, ref, lock=True), key)
        return idem.store({**result, "replayed": False})


class PaymentRunIn(BaseModel):
    run_date: date
    include_not_due: bool = False


@router.post("/payments/runs", tags=["F7 Invoice"])
def payment_run(body: PaymentRunIn, p: Principal = Depends(require("payment:run")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/payments/runs", key, body)
        if idem.replay:
            return idem.replay
        return idem.store(payables.payment_run(s, body.run_date, body.include_not_due))


@router.get("/grir", tags=["F7 Invoice"])
def grir(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return payables.grir(s)
