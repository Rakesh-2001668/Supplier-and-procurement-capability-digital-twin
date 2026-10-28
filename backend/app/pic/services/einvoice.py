"""M10 GST e-invoice: IRN and signed QR validated on capture (Technical Document §12.3).

Verification levels
- IRP:   the IRN is looked up at the Invoice Registration Portal through a GSP. Configure
         PIC_IRP_URL, PIC_IRP_CLIENT_ID, PIC_IRP_CLIENT_SECRET and PIC_IRP_GSTIN (the buyer GSTIN registered with the GSP).
         The adapter calls ``GET {PIC_IRP_URL}/irn/{irn}`` with the client credentials as headers and expects the IRP
         "get e-invoice by IRN" response (Irn, Status ACT/CNL, SellerGstin/DocNo or SignedQRCode).
- LOCAL: without IRP access (or when the IRP cannot be reached) the platform checks the IRN format and hash
         (SHA-256 of supplier GSTIN, financial year, document type and number) and decodes the signed QR JWT payload
         (structure, IRN, seller GSTIN, document number and total). The NIC signature is not verified locally.

The result is recorded on the invoice (``irn_valid``) and as an E_INVOICE_VERIFIED audit event, which is how
``verification_of`` finds the level later.
"""
import base64
import json
import logging
import os
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import AuditEvent, CompanyCode, Invoice, Supplier
from app.pic.platform import audit, clock, crypto

log = logging.getLogger("pic.einvoice")
IRN_FORMAT = re.compile(r"^[0-9a-f]{64}$")


def irp_configured() -> bool:
    return all(os.environ.get(k) for k in ("PIC_IRP_URL", "PIC_IRP_CLIENT_ID", "PIC_IRP_CLIENT_SECRET", "PIC_IRP_GSTIN"))


def _http_get(url: str, headers: dict) -> tuple[int, dict]:
    try:
        import httpx
        response = httpx.get(url, headers=headers, timeout=15)
        return response.status_code, response.json() if response.content else {}
    except ImportError:  # pragma: no cover - httpx is a dependency; urllib keeps the adapter usable without it
        import urllib.request
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - configured IRP/GSP endpoint
            return response.status, json.loads(response.read() or b"{}")


def decode_qr(token: str) -> dict:
    """Decode the signed QR (a JWS: header.payload.signature) without verifying the signature."""
    parts = (token or "").strip().split(".")
    if len(parts) != 3 or not all(parts[:2]):
        raise ValueError("signed QR is not a JWT (header.payload.signature)")

    def b64(segment: str) -> dict:
        return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))

    header, payload = b64(parts[0]), b64(parts[1])
    data = payload.get("data")
    data = json.loads(data) if isinstance(data, str) else (data or payload)
    return {"header": header, "iss": payload.get("iss"), "data": data}


def _check(checks: list, code: str, ok: bool, detail: str) -> None:
    checks.append({"code": code, "ok": bool(ok), "detail": detail})


def _qr_checks(checks: list, qr: dict, *, irn: str, seller_gstin: str, buyer_gstin: Optional[str], doc_no: str, invoice_date: date,
               gross_minor: int) -> None:
    data = qr["data"]
    _check(checks, "QR_ALGORITHM", str(qr["header"].get("alg", "")).upper().startswith(("RS", "ES", "PS")),
           f"JWS algorithm {qr['header'].get('alg')}")
    _check(checks, "QR_IRN", data.get("Irn") == irn, "QR IRN matches the invoice IRN")
    _check(checks, "QR_SELLER_GSTIN", data.get("SellerGstin") == seller_gstin, "QR seller GSTIN is the supplier's GSTIN")
    if buyer_gstin and data.get("BuyerGstin"):
        _check(checks, "QR_BUYER_GSTIN", data.get("BuyerGstin") == buyer_gstin, "QR buyer GSTIN is the company code's GSTIN")
    _check(checks, "QR_DOC_NO", data.get("DocNo") == doc_no, f"QR document number {data.get('DocNo')}")
    if data.get("DocDt"):
        try:
            qr_date = datetime.strptime(str(data["DocDt"]), "%d/%m/%Y").date()
            _check(checks, "QR_DOC_DATE", qr_date == invoice_date, f"QR document date {data['DocDt']}")
        except ValueError:
            _check(checks, "QR_DOC_DATE", False, f"QR document date {data['DocDt']} is not dd/mm/yyyy")
    try:
        total = int((Decimal(str(data.get("TotInvVal"))) * 100).to_integral_value())
        _check(checks, "QR_TOTAL", abs(total - gross_minor) <= 100, f"QR total {data.get('TotInvVal')} vs invoice {gross_minor / 100:.2f}")
    except Exception:
        _check(checks, "QR_TOTAL", False, "QR carries no invoice total (TotInvVal)")


def verify(session: Session, *, supplier: Supplier, company_code: str, supplier_invoice_no: str, invoice_date: date, gross_minor: int,
           irn: Optional[str], signed_qr: Optional[str] = None, doc_type: str = "INV") -> dict:
    from app.pic.services.payables import expected_irn
    checks: list[dict] = []
    seller = crypto.decrypt(supplier.tenant_id, "gstin", supplier.gstin_enc) if supplier.gstin_enc else ""
    company = session.execute(select(CompanyCode).where(CompanyCode.code == company_code)).scalar_one_or_none()
    buyer = company.gstin if company else None
    fiscal_year = clock.fiscal_year(invoice_date)
    level, irp_error, qr = "LOCAL", None, None
    irn = (irn or "").strip()
    if irp_configured() and irn:
        try:
            status, body = _http_get(f"{os.environ['PIC_IRP_URL'].rstrip('/')}/irn/{irn}",
                                     {"client_id": os.environ["PIC_IRP_CLIENT_ID"], "client_secret": os.environ["PIC_IRP_CLIENT_SECRET"],
                                      "gstin": os.environ["PIC_IRP_GSTIN"], "accept": "application/json"})
            if status == 200:
                level = "IRP"
                result = body.get("data") or body.get("Data") or body
                if isinstance(result, str):
                    result = json.loads(result)
                _check(checks, "IRP_FOUND", result.get("Irn") == irn, "IRN registered at the IRP")
                _check(checks, "IRP_ACTIVE", str(result.get("Status", "ACT")).upper() == "ACT", f"IRP status {result.get('Status', 'ACT')}")
                signed_qr = signed_qr or result.get("SignedQRCode")
            else:
                irp_error = f"IRP answered HTTP {status}"
        except Exception as exc:  # noqa: BLE001 - fall back to local checks, keep the reason
            irp_error = f"IRP unreachable: {type(exc).__name__}"
            log.warning("IRP lookup failed: %s", irp_error)
    _check(checks, "IRN_FORMAT", bool(IRN_FORMAT.fullmatch(irn)), "IRN is 64 lowercase hex characters")
    _check(checks, "IRN_HASH", bool(seller) and irn == expected_irn(seller, fiscal_year, doc_type, supplier_invoice_no),
           f"IRN = SHA-256(supplier GSTIN, {fiscal_year}, {doc_type}, {supplier_invoice_no})")
    if signed_qr:
        try:
            qr = decode_qr(signed_qr)
            _check(checks, "QR_STRUCTURE", True, "signed QR decodes as a JWT")
            _qr_checks(checks, qr, irn=irn, seller_gstin=seller, buyer_gstin=buyer, doc_no=supplier_invoice_no, invoice_date=invoice_date,
                       gross_minor=gross_minor)
        except (ValueError, json.JSONDecodeError) as exc:
            _check(checks, "QR_STRUCTURE", False, f"signed QR could not be decoded: {exc}")
    return {"level": level, "valid": all(c["ok"] for c in checks), "checks": checks, "irpError": irp_error,
            "qrSignatureVerified": False if level == "LOCAL" else None, "qr": qr["data"] if qr else None}


def record(session: Session, invoice: Invoice, result: dict) -> None:
    invoice.irn_valid = result["valid"]
    audit.record(session, "INVOICE", invoice.id, "E_INVOICE_VERIFIED", object_ref=invoice.number,
                 after={"level": result["level"], "valid": result["valid"], "checks": result["checks"], "irpError": result["irpError"],
                        "qrPresent": result["qr"] is not None})


def verify_invoice(session: Session, invoice: Invoice, signed_qr: Optional[str] = None) -> dict:
    supplier = session.get(Supplier, invoice.supplier_id)
    result = verify(session, supplier=supplier, company_code=invoice.company_code, supplier_invoice_no=invoice.supplier_invoice_no,
                    invoice_date=invoice.invoice_date, gross_minor=invoice.gross_minor, irn=invoice.irn, signed_qr=signed_qr)
    record(session, invoice, result)
    return result


def verification_of(session: Session, invoice: Invoice) -> dict:
    """Latest verification recorded for the invoice; invoices captured before this check existed fall back to irn_valid."""
    event = session.execute(select(AuditEvent).where(AuditEvent.object_type == "INVOICE", AuditEvent.object_id == invoice.id,
                                                     AuditEvent.action == "E_INVOICE_VERIFIED").order_by(AuditEvent.seq.desc())).scalars().first()
    if event is not None:
        return {"invoice": invoice.number, "irn": invoice.irn, "irnValid": invoice.irn_valid, **(event.after or {}),
                "verifiedAt": event.ts.isoformat(), "verifiedBy": event.actor, "irpConfigured": irp_configured()}
    return {"invoice": invoice.number, "irn": invoice.irn, "irnValid": invoice.irn_valid, "level": "LOCAL" if invoice.irn else None,
            "valid": invoice.irn_valid, "checks": [], "verifiedAt": None, "irpConfigured": irp_configured()}
