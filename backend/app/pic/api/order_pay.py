"""F5 purchase orders, F6 receiving and quality, F7 invoices and payments."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.pic import views
from app.pic.api.deps import idempotency_key, idempotent, uow
from app.pic.models import Asn, GoodsReceipt, InspectionLot, Invoice, PurchaseOrder, ReturnDelivery, ServiceEntry
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
    retentionPct: Optional[Decimal] = Field(default=None, ge=0, le=20)


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
            unit_price_minor=body.unitPriceMinor, deviation_reason=body.deviationReason, retention_pct=body.retentionPct)
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
        # awaitingConfirmation: the supplier owes a response (also a partly received order changed to a new version);
        # pendingChangeApproval: a change order waiting for PO approval before it becomes version n+1.
        pending = None if "SUPPLIER_USER" in p.roles else order.pending_change_approval(s, po)  # internal: never shown to the supplier
        return {**views.purchase_order(s, po), "awaitingConfirmation": order.awaiting_confirmation(s, po),
                "pendingChangeApproval": {"role": pending.candidate_role, "evidence": pending.evidence} if pending is not None else None}


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
    changes: list[dict] = Field(min_length=1)
    reason: str
    deviationReason: Optional[str] = Field(default=None, max_length=500)


@router.post("/purchase-orders/{ref}/versions", tags=["F5 Purchase Order"])
def change_po(ref: str, body: ChangeIn, p: Principal = Depends(require("po:change")),
              if_match: Optional[str] = Header(default=None, alias="If-Match")):
    with uow(p) as s:
        po = by_ref(s, PurchaseOrder, ref, lock=True)
        check_if_match(po, if_match)
        return order.change_order(s, po, body.changes, body.reason, deviation_reason=body.deviationReason)


class ResubmitIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    changes: list[dict] = []
    deviationReason: Optional[str] = Field(default=None, max_length=500)


@router.post("/purchase-orders/{ref}/resubmit", tags=["F5 Purchase Order"])
def resubmit_po(ref: str, body: ResubmitIn, p: Principal = Depends(require("po:change")),
                if_match: Optional[str] = Header(default=None, alias="If-Match")):
    """Re-submit an order returned by its approver (DRAFT): optional line corrections (qty, unit_price, need_date), then
    validation and the approval strategy run again."""
    with uow(p) as s:
        po = by_ref(s, PurchaseOrder, ref, lock=True)
        check_if_match(po, if_match)
        return order.resubmit(s, po, body.reason, body.changes, deviation_reason=body.deviationReason)


class PoReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/purchase-orders/{ref}/cancel", tags=["F5 Purchase Order"])
def cancel_po(ref: str, body: PoReasonIn, p: Principal = Depends(require("po:change"))):
    """Cancel an order nothing was shipped, received or invoiced against; its requisition quantity is released."""
    with uow(p) as s:
        return order.cancel(s, by_ref(s, PurchaseOrder, ref, lock=True), body.reason)


@router.post("/purchase-orders/{ref}/close", tags=["F5 Purchase Order"])
def close_po(ref: str, body: PoReasonIn, p: Principal = Depends(require("po:change"))):
    """Close an order with nothing left to receive or invoice (INVOICED, or RECEIVED with every accepted quantity invoiced)."""
    with uow(p) as s:
        return order.close(s, by_ref(s, PurchaseOrder, ref, lock=True), body.reason)


@router.post("/purchase-orders/{ref}/short-close", tags=["F5 Purchase Order"])
def short_close_po(ref: str, body: PoReasonIn, p: Principal = Depends(require("po:change"))):
    """Short-close a partly received order once its received value is invoiced; the open quantity goes back to the requisition."""
    with uow(p) as s:
        return order.short_close(s, by_ref(s, PurchaseOrder, ref, lock=True), body.reason)


# ---------------------------------------------------------------- F6 receiving
class AsnLineIn(BaseModel):
    line: int
    qty: Decimal = Field(gt=0)
    batches: list[dict] = []


class AsnIn(BaseModel):
    po: str
    lines: list[AsnLineIn] = Field(min_length=1)
    ship_date: date
    expected_date: date
    eway_bill_no: Optional[str] = None
    eway_bill_valid_until: Optional[datetime] = None
    vehicle_no: Optional[str] = Field(default=None, max_length=15)
    distance_km: Optional[int] = Field(default=None, gt=0, le=4000)
    documents: list[str] = []


@router.post("/asns", status_code=201, tags=["F6 Receiving"])
def create_asn(body: AsnIn, p: Principal = Depends(require("asn:create")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/asns", key, body)
        if idem.replay:
            return idem.replay
        po = by_ref(s, PurchaseOrder, body.po, lock=True)
        asn = receiving.create_asn(s, po, lines=[l.model_dump(mode="json") for l in body.lines], ship_date=body.ship_date,
                                   expected_date=body.expected_date, eway_bill_no=body.eway_bill_no, documents=body.documents,
                                   eway_bill_valid_until=body.eway_bill_valid_until, vehicle_no=body.vehicle_no, distance_km=body.distance_km)
        return idem.store(views.asn(s, asn), 201)


class GrLineIn(BaseModel):
    line: int
    qty: Decimal = Field(gt=0)
    batch: str = ""
    storage_location: Optional[str] = None
    expiry: Optional[str] = None
    serials: list[str] = []


class GrIn(BaseModel):
    po: str
    asn: Optional[str] = None
    delivery_note: Optional[str] = None
    posting_date: Optional[date] = None
    lines: list[GrLineIn] = Field(min_length=1)


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
        return idem.store({**views.goods_receipt(s, gr), "warnings": receiving.eway_warnings(s, gr)}, 201)


@router.get("/goods-receipts/{ref}", tags=["F6 Receiving"])
def get_gr(ref: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        gr = by_ref(s, GoodsReceipt, ref)
        return {**views.goods_receipt(s, gr), "warnings": receiving.eway_warnings(s, gr)}


class UsageDecisionIn(BaseModel):
    accepted: Decimal = Field(ge=0)
    rejected: Decimal = Field(default=Decimal(0), ge=0)
    defect_code: Optional[str] = None
    reason: Optional[str] = None
    replacement: bool = False  # rejected quantity returned for replacement (re-opened on the PO) instead of a credit note


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


class ReplacementIn(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


@router.post("/return-deliveries/{ref}/replacement", tags=["F6 Receiving"])
def request_replacement(ref: str, body: ReplacementIn, p: Principal = Depends(require("quality:decide"))):
    """The supplier re-delivers instead of crediting: the returned quantity is open again on the PO for a new ASN and receipt."""
    with uow(p) as s:
        return row(receiving.request_replacement(s, by_ref(s, ReturnDelivery, ref, lock=True), body.reason))


class SesLineIn(BaseModel):
    line: int
    description: Optional[str] = None
    qty: Decimal = Field(gt=0)
    unit_rate: Optional[Decimal] = Field(default=None, gt=0)


class SesIn(BaseModel):
    po: str
    method: str = Field(pattern="^(MILESTONE|TIME_MATERIAL|UNIT_RATE|PROGRESS)$")
    period_from: date
    period_to: date
    lines: list[SesLineIn] = Field(min_length=1)


@router.post("/service-entries", status_code=201, tags=["F6 Receiving"])
def create_ses(body: SesIn, p: Principal = Depends(require("ses:create")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/service-entries", key, body)
        if idem.replay:
            return idem.replay
        po = by_ref(s, PurchaseOrder, body.po, lock=True)
        ses = receiving.create_ses(s, po, method=body.method, period_from=body.period_from, period_to=body.period_to,
                                   lines=[l.model_dump(mode="json", exclude_none=True) for l in body.lines])
        receiving.submit_ses(s, ses)
        return idem.store(views.service_entry(s, ses), 201)


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
    qty: Decimal = Field(gt=0)
    unit_price: Decimal = Field(gt=0)
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
    signed_qr: Optional[str] = Field(default=None, max_length=8000)
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
                                   channel=body.channel, irn=body.irn, company_code=body.company_code, signed_qr=body.signed_qr,
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


class CreditNoteLineIn(BaseModel):
    invoice_line: int
    qty: Decimal = Field(gt=0)
    # Value credit (price difference): paise credited per unit; omit for a quantity credit at the invoice price.
    unit_credit_minor: Optional[int] = Field(default=None, gt=0)


class CreditNoteIn(BaseModel):
    supplier_credit_note_no: str = Field(min_length=1, max_length=30)
    note_date: date
    reason: str = Field(min_length=3)
    lines: list[CreditNoteLineIn] = Field(min_length=1)


@router.post("/invoices/{ref}/credit-notes", status_code=201, tags=["F7 Invoice"])
def credit_note(ref: str, body: CreditNoteIn, p: Principal = Depends(require_any("invoice:submit", "invoice:capture"))):
    with uow(p) as s:
        invoice = by_ref(s, Invoice, ref, lock=True)
        if "SUPPLIER_USER" in p.roles and invoice.supplier_id != p.supplier_id:
            raise not_found("Invoice", ref)
        data = body.model_dump()
        data["lines"] = [{k: v for k, v in line.items() if v is not None} for line in data["lines"]]
        return row(payables.submit_credit_note(s, invoice, **data))


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
    supplier_codes: Optional[list[str]] = Field(None, max_length=200)
    invoice_numbers: Optional[list[str]] = Field(None, max_length=500)


@router.post("/payments/runs", tags=["F7 Invoice"])
def payment_run(body: PaymentRunIn, p: Principal = Depends(require("payment:run")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/payments/runs", key, body)
        if idem.replay:
            return idem.replay
        return idem.store(payables.payment_run(s, body.run_date, body.include_not_due, body.supplier_codes, body.invoice_numbers))


@router.get("/purchase-orders/{ref}/retention", tags=["F7 Invoice"])
def retention(ref: str, p: Principal = Depends(require(READ))):
    """Retention withheld on the order's posted invoices, released so far and outstanding (construction / subcontract orders)."""
    with uow(p) as s:
        return payables.retention_position(s, by_ref(s, PurchaseOrder, ref))


class RetentionReleaseIn(BaseModel):
    reference: str = Field(min_length=3, max_length=120)
    reason: str = Field(min_length=3, max_length=500)
    amountMinor: Optional[int] = Field(default=None, gt=0)
    releaseDate: Optional[date] = None


@router.post("/purchase-orders/{ref}/retention-release", status_code=201, tags=["F7 Invoice"])
def release_retention(ref: str, body: RetentionReleaseIn, p: Principal = Depends(require_any("invoice:post", "payment:run"))):
    """Release retention (all outstanding, or amountMinor): creates a RETENTION AP document that the next payment run pays."""
    with uow(p) as s:
        doc = payables.release_retention(s, by_ref(s, PurchaseOrder, ref, lock=True), reference=body.reference, reason=body.reason,
                                         amount_minor=body.amountMinor, release_date=body.releaseDate)
        return views.invoice(s, doc)


@router.get("/grir", tags=["F7 Invoice"])
def grir(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return payables.grir(s)


# ---------------------------------------------------------------- P08 special stocks: subcontracting, consignment, lots (BP §22, §23)
class ComponentIn(BaseModel):
    material: str
    qty: Decimal = Field(gt=0)
    batch: str = ""
    storage_location: Optional[str] = None


class ProvideComponentsIn(BaseModel):
    line: int
    components: list[ComponentIn] = []   # empty: provide the full planned quantity
    storage_location: str = "0001"


@router.get("/purchase-orders/{ref}/components", tags=["F6 Receiving"])
def subcontracting_components(ref: str, p: Principal = Depends(require(READ))):
    """Planned components per subcontracting line (from the material's subcontracting BOM) and the stock at the subcontractor."""
    with uow(p) as s:
        po = by_ref(s, PurchaseOrder, ref)
        from app.pic.models import Supplier
        return {"po": po.number, "lines": [{"line": l.line_no, "components": receiving.subcontracting_components(po, l)}
                                           for l in order.lines_of(s, po) if l.purchase_type == "SUBCONTRACTING"],
                "atSubcontractor": receiving.subcontractor_stock(s, s.get(Supplier, po.supplier_id))}


@router.post("/purchase-orders/{ref}/components", status_code=201, tags=["F6 Receiving"])
def provide_components(ref: str, body: ProvideComponentsIn, p: Principal = Depends(require("gr:post"))):
    """Transfer posting 541: provide own components to the subcontractor; the receipt of the finished part consumes them (543)."""
    with uow(p) as s:
        po = by_ref(s, PurchaseOrder, ref, lock=True)
        return receiving.provide_components(s, po, body.line, storage_location=body.storage_location,
                                            components=[c.model_dump() for c in body.components] or None)


class WithdrawalIn(BaseModel):
    material: str
    plant: str
    qty: Decimal = Field(gt=0)
    usage_ref: str = Field(min_length=3, max_length=60)
    purpose: str = Field(default="CONSUMPTION", pattern="^(CONSUMPTION|TRANSFER)$")
    storage_location: str = "0001"
    batch: Optional[str] = None
    serials: list[str] = []
    cost_object: Optional[str] = Field(default=None, pattern="^[A-Z_]+:[A-Za-z0-9-]+$")
    replenish: bool = False


@router.post("/consignment/withdrawals", status_code=201, tags=["F6 Receiving"])
def withdraw_consignment(body: WithdrawalIn, p: Principal = Depends(require_any("gr:post", "req:create")),
                         key: Optional[str] = Depends(idempotency_key)):
    """Withdraw from consignment stock (201K consumption to a cost object or 411K transfer to own stock): creates the liability
    that self-billing settles; replenish=true raises the replenishment requisition (usage-triggered)."""
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/consignment/withdrawals", key, body)
        if idem.replay:
            return idem.replay
        return idem.store(receiving.withdraw_consignment(s, **body.model_dump()), 201)


class SettlementIn(BaseModel):
    supplier: str
    period_to: date
    company_code: str = "1000"
    reference: Optional[str] = Field(default=None, max_length=60)


@router.post("/consignment/settlements", status_code=201, tags=["F7 Invoice"])
def settle_consignment(body: SettlementIn, p: Principal = Depends(require_any("invoice:post", "payment:run")),
                       key: Optional[str] = Depends(idempotency_key)):
    """Self-billing (ERS) for everything withdrawn from the supplier's consignment stock up to period_to and not yet settled."""
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/consignment/settlements", key, body)
        if idem.replay:
            return idem.replay
        invoice = payables.settle_consignment(s, supplier=body.supplier, period_to=body.period_to, company_code=body.company_code,
                                              reference=body.reference)
        return idem.store(views.invoice(s, invoice), 201)


@router.get("/lots/{material}/{batch}/trace", tags=["F6 Receiving"])
def trace_lot(material: str, batch: str, p: Principal = Depends(require(READ))):
    """Recall traceability: receipts with receiving location, usage (cases / orders, serials), stock on hand, returns, movements."""
    with uow(p) as s:
        return receiving.trace_lot(s, material, batch)


class RecallIn(BaseModel):
    notice_ref: str = Field(min_length=3, max_length=60)
    reason: str = Field(min_length=3, max_length=500)
    replenish: bool = False


@router.post("/lots/{material}/{batch}/recall", tags=["F6 Receiving"])
def recall_lot(material: str, batch: str, body: RecallIn, p: Principal = Depends(require("quality:decide"))):
    """Supplier recall: quarantine and return every unit of the lot still on hand; used units stay in the trace for follow-up."""
    with uow(p) as s:
        return receiving.recall_lot(s, material=material, batch=batch, notice_ref=body.notice_ref, reason=body.reason,
                                    replenish=body.replenish)
