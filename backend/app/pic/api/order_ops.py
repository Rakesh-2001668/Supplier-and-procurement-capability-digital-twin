"""PO schedule lines and transmission, inbound EDI, payment files, e-invoice and document capture."""
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Header, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.pic.api.deps import idempotency_key, idempotent, uow
from app.pic.models import Invoice, PurchaseOrder
from app.pic.platform.auth import READ, Principal, require, require_any
from app.pic.platform.core import check_if_match
from app.pic.platform.crypto import sha256_hex
from app.pic.platform.errors import Problem, not_found
from app.pic.services import bank_files, einvoice, ocr, order, transmission
from app.pic.services.common import by_ref

router = APIRouter(prefix="/v1")
PORTAL = require_any(READ, "supplier:portal")


def _visible_po(s, p: Principal, ref: str, lock: bool = False) -> PurchaseOrder:
    po = by_ref(s, PurchaseOrder, ref, lock=lock)
    if "SUPPLIER_USER" in p.roles and po.supplier_id != p.supplier_id:
        raise not_found("Purchase order", ref)
    return po


# ---------------------------------------------------------------- PO delivery schedule (TD §5 delivery_schedule[])
class ScheduleLineIn(BaseModel):
    qty: Decimal = Field(gt=0)
    deliveryDate: date


class ScheduleIn(BaseModel):
    lines: list[ScheduleLineIn] = Field(min_length=1, max_length=104)
    reason: Optional[str] = None


@router.get("/purchase-orders/{ref}/schedule", tags=["F5 Purchase Order"])
def get_schedule(ref: str, p: Principal = Depends(PORTAL)):
    """Schedule lines per PO line: requested and confirmed date, received and open quantity, days late."""
    with uow(p) as s:
        return order.schedule_view(s, _visible_po(s, p, ref))


@router.put("/purchase-orders/{ref}/lines/{line_no}/schedule", tags=["F5 Purchase Order"])
def put_schedule(ref: str, line_no: int, body: ScheduleIn, p: Principal = Depends(require("po:change")),
                 if_match: Optional[str] = Header(default=None, alias="If-Match")):
    """Replace a line's delivery schedule; quantities must add up to the line quantity. Before supplier confirmation the
    schedule is edited in place (audited); after confirmation it becomes version n+1 that the supplier re-confirms."""
    with uow(p) as s:
        po = by_ref(s, PurchaseOrder, ref, lock=True)
        check_if_match(po, if_match)
        return order.set_schedule(s, po, line_no, [l.model_dump() for l in body.lines], body.reason)


# ---------------------------------------------------------------- transmissions (F5-06)
@router.get("/purchase-orders/{ref}/transmissions", tags=["F5 Purchase Order"])
def list_transmissions(ref: str, p: Principal = Depends(PORTAL)):
    with uow(p) as s:
        return transmission.transmissions(s, _visible_po(s, p, ref))


@router.get("/purchase-orders/{ref}/transmissions/{transmission_id}", tags=["F5 Purchase Order"])
def get_transmission(ref: str, transmission_id: uuid.UUID, p: Principal = Depends(PORTAL)):
    """One transmission with the exact document sent (EDIFACT interchange, e-mail HTML or portal JSON)."""
    with uow(p) as s:
        return transmission.view(transmission.get(s, _visible_po(s, p, ref), transmission_id), with_document=True)


MEDIA = {"EDIFACT_ORDERS": ("application/EDIFACT", "edi"), "EDIFACT_ORDCHG": ("application/EDIFACT", "edi"),
         "HTML_EMAIL": ("text/html; charset=utf-8", "html"), "PORTAL": ("application/json", "json")}


@router.get("/purchase-orders/{ref}/transmissions/{transmission_id}/document", tags=["F5 Purchase Order"])
def download_transmission(ref: str, transmission_id: uuid.UUID, p: Principal = Depends(PORTAL)):
    with uow(p) as s:
        po = _visible_po(s, p, ref)
        record = transmission.get(s, po, transmission_id)
        media, ext = MEDIA.get(record.format, ("text/plain; charset=utf-8", "txt"))
        return Response(content=record.document.encode("utf-8"), media_type=media,
                        headers={"Content-Disposition": f'attachment; filename="{po.number}_v{record.po_version}_{record.channel.lower()}.{ext}"',
                                 "X-Content-SHA256": record.document_sha256})


@router.post("/purchase-orders/{ref}/transmissions/{transmission_id}/resend", tags=["F5 Purchase Order"])
def resend_transmission(ref: str, transmission_id: uuid.UUID, p: Principal = Depends(require("po:change")),
                        key: Optional[str] = Depends(idempotency_key)):
    """Retry a queued or failed EDI/e-mail transmission of the current version (e.g. after the gateway is configured)."""
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/purchase-orders/{ref}/transmissions/{transmission_id}/resend", key, {})
        if idem.replay:
            return idem.replay
        po = by_ref(s, PurchaseOrder, ref, lock=True)
        return idem.store(transmission.view(transmission.resend(s, po, transmission_id)))


@router.post("/edi/inbound", tags=["Integration"])
def edi_inbound(payload: str = Body(..., media_type="application/EDIFACT"), p: Principal = Depends(require("admin:integration")),
                key: Optional[str] = Depends(idempotency_key)):
    """Inbound UN/EDIFACT from the EDI gateway: ORDRSP (order response → supplier confirmation) and DESADV (→ ASN).

    Authenticated with the ``admin:integration`` scope: the gateway's service account is an integration client, not a
    supplier user, and this scope is held by no business or supplier role. The interchange sender (UNB) must be a
    supplier's ``order_channel.ediId`` and the receiver this tenant's code; each message then acts as that supplier.
    A re-delivered interchange (same sender and control reference) replays the first result."""
    interchange = transmission.parse(payload)
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/edi/inbound", key or f"EDI|{interchange.sender}|{interchange.reference}", {"sha256": sha256_hex(payload)})
        if idem.replay:
            return idem.replay
        return idem.store(transmission.inbound(s, payload))


# ---------------------------------------------------------------- bank payment files (F7-07)
class PaymentFileIn(BaseModel):
    format: str = Field(pattern="^(ISO20022_PAIN001|NEFT_CSV)$")


@router.get("/payments/runs", tags=["F7 Invoice"])
def payment_runs(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return bank_files.runs(s)


@router.post("/payments/runs/{run}/file", status_code=201, tags=["F7 Invoice"])
def generate_payment_file(run: str, body: PaymentFileIn, p: Principal = Depends(require("payment:run")),
                          key: Optional[str] = Depends(idempotency_key)):
    """Generate the bank file for a payment run: pain.001.001.03 XML or NEFT bulk CSV. 409 until the debtor account is
    configured in the PAYMENT-FILE rule set, and 409 when the run already has a live file."""
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/payments/runs/{run}/file", key, body)
        if idem.replay:
            return idem.replay
        return idem.store(bank_files.view(bank_files.generate(s, run, body.format)), 201)


@router.get("/payment-files", tags=["F7 Invoice"])
def payment_files(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return bank_files.listing(s)


@router.get("/payment-files/{number}/content", tags=["F7 Invoice"])
def payment_file_content(number: str, p: Principal = Depends(require("payment:run"))):
    """The file as sent to the bank (finance only; every download is audited)."""
    with uow(p) as s:
        pf = bank_files.by_number(s, number)
        content = bank_files.content_of(s, pf)
        media = "application/xml" if pf.format == "ISO20022_PAIN001" else "text/csv"
        return Response(content=content.encode("utf-8"), media_type=media,
                        headers={"Content-Disposition": f'attachment; filename="{pf.file_name}"', "X-Content-SHA256": pf.sha256})


class PaymentFileStatusIn(BaseModel):
    status: str = Field(pattern="^(SENT|ACKNOWLEDGED|REJECTED)$")
    bankRef: Optional[str] = Field(default=None, max_length=60)
    reason: Optional[str] = None


@router.post("/payment-files/{number}/status", tags=["F7 Invoice"])
def payment_file_status(number: str, body: PaymentFileStatusIn, p: Principal = Depends(require("payment:run"))):
    """Record what the bank did with the file (manual until a host-to-host connector is configured)."""
    with uow(p) as s:
        return bank_files.view(bank_files.set_status(s, bank_files.by_number(s, number, lock=True), body.status, body.bankRef, body.reason))


@router.post("/payment-files/{number}/transmit", tags=["F7 Invoice"])
def payment_file_transmit(number: str, p: Principal = Depends(require("payment:run"))):
    with uow(p) as s:
        return bank_files.transmit(bank_files.by_number(s, number))


# ---------------------------------------------------------------- GST e-invoice (TD §12.3)
def _visible_invoice(s, p: Principal, ref: str, lock: bool = False) -> Invoice:
    invoice = by_ref(s, Invoice, ref, lock=lock)
    if "SUPPLIER_USER" in p.roles and invoice.supplier_id != p.supplier_id:
        raise not_found("Invoice", ref)
    return invoice


@router.get("/invoices/{ref}/e-invoice", tags=["F7 Invoice"])
def e_invoice(ref: str, p: Principal = Depends(PORTAL)):
    """IRN / signed-QR verification result and level (IRP or LOCAL)."""
    with uow(p) as s:
        return einvoice.verification_of(s, _visible_invoice(s, p, ref))


class EInvoiceVerifyIn(BaseModel):
    signedQr: Optional[str] = Field(default=None, max_length=8000)


@router.post("/invoices/{ref}/e-invoice/verify", tags=["F7 Invoice"])
def verify_e_invoice(ref: str, body: EInvoiceVerifyIn, p: Principal = Depends(require_any("invoice:capture", "invoice:resolve"))):
    """Re-verify the IRN (and a signed QR) — e.g. once IRP access is configured. A changed result is re-matched by AP."""
    with uow(p) as s:
        invoice = by_ref(s, Invoice, ref, lock=True)
        if not invoice.irn and not body.signedQr:
            raise Problem(422, "IRN_REQUIRED", f"{invoice.number} has no IRN to verify")
        einvoice.verify_invoice(s, invoice, body.signedQr)
        return einvoice.verification_of(s, invoice)


# ---------------------------------------------------------------- document capture (OCR/IDP)
@router.post("/invoices/documents", tags=["F7 Invoice"])
def capture_document(file: UploadFile = File(...), p: Principal = Depends(require("invoice:capture"))):
    """Extract header and lines from an invoice PDF/image for the capture form. Nothing is stored. 503 OCR_NOT_CONFIGURED
    without PIC_OCR_URL."""
    if not ocr.configured():
        raise Problem(503, "OCR_NOT_CONFIGURED", "No document-capture engine is configured (PIC_OCR_URL); enter the invoice manually")
    content = file.file.read(ocr.MAX_BYTES + 1)
    with uow(p) as s:
        return ocr.extract(s, filename=file.filename or "document", content_type=(file.content_type or "").split(";")[0], content=content)
