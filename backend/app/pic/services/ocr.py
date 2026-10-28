"""M10 invoice document capture adapter (OCR/IDP engine plug-in).

``POST /v1/invoices/documents`` sends a PDF or image to the configured engine and returns the extracted header and
lines so the AP clerk can review them in the capture form; nothing is stored (the invoice is created by the normal
capture call). Configure PIC_OCR_URL (multipart POST, field ``file``) and optionally PIC_OCR_TOKEN (bearer).
The engine answers JSON; common field spellings are normalised to the capture form:
header {supplierGstin, supplierInvoiceNo, invoiceDate, irn, poNumber, netMinor, taxMinor, grossMinor} and
lines [{po, po_line, description, hsn, qty, unit_price, gst_rate}], plus a confidence per field when the engine gives one.
Without PIC_OCR_URL the endpoint answers 503 OCR_NOT_CONFIGURED.
"""
import hashlib
import os
import re
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import Supplier
from app.pic.platform import audit, clock, crypto
from app.pic.platform.errors import Problem

ACCEPTED_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/tiff"}
MAX_BYTES = 10 * 1024 * 1024


def configured() -> bool:
    return bool(os.environ.get("PIC_OCR_URL"))


def _pick(data: dict, *names: str) -> Any:
    lowered = {str(k).lower().replace("_", ""): v for k, v in (data or {}).items()}
    for name in names:
        value = lowered.get(name.lower().replace("_", ""))
        if value not in (None, ""):
            return value
    return None


def _decimal(value) -> Optional[str]:
    if value is None:
        return None
    try:
        return str(Decimal(str(value).replace(",", "")))
    except InvalidOperation:
        return None


def _minor(value) -> Optional[int]:
    amount = _decimal(value)
    return int(Decimal(amount) * 100) if amount is not None else None


def _date(value) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def normalise(session: Session, raw: dict) -> dict:
    header_raw = raw.get("header") or raw.get("fields") or raw
    header = {
        "supplierGstin": _pick(header_raw, "supplierGstin", "sellerGstin", "vendorGstin", "gstin"),
        "supplierInvoiceNo": _pick(header_raw, "supplierInvoiceNo", "invoiceNumber", "invoiceNo", "docNo"),
        "invoiceDate": _date(_pick(header_raw, "invoiceDate", "docDate", "date")),
        "irn": _pick(header_raw, "irn"),
        "poNumber": _pick(header_raw, "poNumber", "purchaseOrder", "po"),
        "netMinor": _minor(_pick(header_raw, "net", "netAmount", "taxableValue")),
        "taxMinor": _minor(_pick(header_raw, "tax", "taxAmount", "totalTax")),
        "grossMinor": _minor(_pick(header_raw, "gross", "total", "totalAmount", "invoiceTotal")),
    }
    supplier = None
    if header["supplierGstin"]:
        gstin = re.sub(r"\s", "", str(header["supplierGstin"])).upper()
        supplier = session.execute(select(Supplier).where(Supplier.gstin_hash == crypto.blind_index(current_tenant(session), gstin))).scalars().first()
    lines = []
    for index, item in enumerate(raw.get("lines") or raw.get("items") or [], start=1):
        lines.append({"po": _pick(item, "po", "poNumber") or header["poNumber"], "po_line": _pick(item, "poLine", "po_line", "lineNo") or index * 10,
                      "description": _pick(item, "description", "item", "name"), "hsn": _pick(item, "hsn", "hsnCode", "sac"),
                      "qty": _decimal(_pick(item, "qty", "quantity")), "unit_price": _decimal(_pick(item, "unitPrice", "rate", "price")),
                      "gst_rate": _decimal(_pick(item, "gstRate", "taxRate"))})
    return {"header": header, "supplier": {"code": supplier.code, "name": supplier.legal_name} if supplier else None, "lines": lines,
            "confidence": raw.get("confidence") or {}, "engine": raw.get("engine") or raw.get("model")}


def extract(session: Session, *, filename: str, content_type: str, content: bytes) -> dict:
    if not configured():
        raise Problem(503, "OCR_NOT_CONFIGURED", "No document-capture engine is configured (PIC_OCR_URL); enter the invoice manually")
    if content_type not in ACCEPTED_TYPES:
        raise Problem(415, "UNSUPPORTED_MEDIA_TYPE", f"Send a PDF, PNG, JPEG or TIFF document (got {content_type})")
    if not content or len(content) > MAX_BYTES:
        raise Problem(413 if content else 422, "DOCUMENT_SIZE", "The document must be between 1 byte and 10 MB")
    import httpx
    headers = {"Authorization": f"Bearer {os.environ['PIC_OCR_TOKEN']}"} if os.environ.get("PIC_OCR_TOKEN") else {}
    try:
        response = httpx.post(os.environ["PIC_OCR_URL"], files={"file": (filename, content, content_type)}, headers=headers, timeout=60)
    except httpx.HTTPError as exc:
        raise Problem(502, "OCR_UNAVAILABLE", f"The document-capture engine could not be reached ({type(exc).__name__})")
    if response.status_code >= 300:
        raise Problem(502, "OCR_FAILED", f"The document-capture engine answered HTTP {response.status_code}")
    try:
        raw = response.json()
    except ValueError:
        raise Problem(502, "OCR_FAILED", "The document-capture engine did not answer JSON")
    result = normalise(session, raw if isinstance(raw, dict) else {"lines": raw})
    digest = hashlib.sha256(content).hexdigest()
    audit.record(session, "INVOICE_DOCUMENT", uuid.uuid5(uuid.NAMESPACE_URL, f"doc:{digest}"), "EXTRACTED", object_ref=filename[:60],
                 after={"sha256": digest, "contentType": content_type, "bytes": len(content), "lines": len(result["lines"]),
                        "supplier": result["supplier"]["code"] if result["supplier"] else None, "engine": result["engine"]})
    return {**result, "document": {"fileName": filename, "sha256": digest, "bytes": len(content), "contentType": content_type},
            "extractedOn": clock.today().isoformat()}
