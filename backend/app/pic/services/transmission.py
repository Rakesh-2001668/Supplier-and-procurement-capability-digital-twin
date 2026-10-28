"""M08 PO transmission over portal, EDI (EDIFACT ORDERS/ORDCHG) and e-mail, with acknowledgements (F5-06).

Every transmission stores the exact document sent and its SHA-256. The portal channel is always used; EDI and e-mail
follow ``supplier.order_channel`` ({"channels": ["PORTAL", "EDI", "EMAIL"], "ediId": "...", "email": "..."}).
Delivery happens in the ``po-transmission-delivery`` outbox consumer and never fails the purchase order:

- EDI: HTTP POST of the interchange to ``PIC_EDI_GATEWAY_URL`` (bearer ``PIC_EDI_GATEWAY_TOKEN``). Without a gateway the
  transmission stays QUEUED with the error "EDI gateway not configured" and can be re-sent once one is configured.
- E-mail: ``platform.mailer`` to ``order_channel.email`` (or the supplier contact). Without SMTP the mailer answers
  DISABLED and the transmission stays QUEUED.

Inbound EDI (``POST /v1/edi/inbound``): ORDRSP confirms the order with ``order.confirm`` semantics as the supplier and
acknowledges the EDI transmission; DESADV creates an ASN through the receiving service.

EDIFACT implementation guide (D.96A, UNOC level C):
ORDERS/ORDCHG  UNA UNB UNH BGM(220 order/9 original | 230 change request/4 change) DTM(137) NAD(BY, SU) CUX(2:INR:9)
               per line: LIN(+1229 action 3 changed / 4 no action on ORDCHG) PIA(1, HS code) IMD(F) QTY(21) DTM(2) PRI(AAA)
               and SCC(1)+QTY(21)+DTM(2) per schedule line when a line is delivered on several dates; UNS(S) CNT(2) UNT UNZ.
ORDRSP         BGM(231, function 29 accepted | 4 accepted with changes | 27 not accepted) RFF(ON:<PO number>)
               LIN(<line>) QTY(21) DTM(2 or 69 promised) PRI(AAA), SCC(1)+DTM(2/69) per schedule line in schedule order.
DESADV         BGM(351) DTM(11 despatch, 132 arrival) RFF(ON:<PO number>) RFF(ZEW:<e-way bill>)+DTM(36 valid until)
               TDT(12, vehicle registration in C222) CPS LIN(<line>) QTY(12) GIN(BX batch).
"""
import hashlib
import html
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import CompanyCode, Material, PoLine, PoScheduleLine, PoTransmission, PoVersion, PurchaseOrder, Supplier, Tenant
from app.pic.platform import audit, clock, mailer, outbox
from app.pic.platform.auth import Principal
from app.pic.platform.errors import Problem, not_found
from app.pic.platform.money import from_minor
from app.pic.platform.serialize import jsonable
from app.pic.services.common import principal

log = logging.getLogger("pic.transmission")

CHANNELS = ("PORTAL", "EDI", "EMAIL")


def channels_for(supplier: Supplier) -> list[str]:
    configured = [str(c).upper() for c in (supplier.order_channel or {}).get("channels", [])]
    return ["PORTAL"] + [c for c in ("EDI", "EMAIL") if c in configured]


def _tenant_code(session: Session) -> str:
    p = session.info.get("principal")
    if p is not None and p.tenant_code:
        return p.tenant_code
    return session.get(Tenant, current_tenant(session)).code


def _sha(document: str) -> str:
    return hashlib.sha256(document.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- the order document (one source for every channel)
@dataclass
class OrderDoc:
    po: PurchaseOrder
    supplier: Supplier
    company_name: str
    company_gstin: Optional[str]
    lines: list[dict] = field(default_factory=list)
    changed_lines: set[int] = field(default_factory=set)


def _order_doc(session: Session, po: PurchaseOrder) -> OrderDoc:
    supplier = session.get(Supplier, po.supplier_id)
    company = session.execute(select(CompanyCode).where(CompanyCode.code == po.company_code)).scalar_one_or_none()
    doc = OrderDoc(po, supplier, company.name if company else po.company_code, company.gstin if company else None)
    schedule: dict[uuid.UUID, list[PoScheduleLine]] = {}
    for sl in session.execute(select(PoScheduleLine).where(PoScheduleLine.po_id == po.id)
                              .order_by(PoScheduleLine.delivery_date, PoScheduleLine.seq)).scalars():
        schedule.setdefault(sl.po_line_id, []).append(sl)
    for line in session.execute(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no)).scalars():
        material = session.get(Material, line.material_id) if line.material_id else None
        doc.lines.append({"line": line.line_no, "material": material.number if material else None, "description": line.description,
                          "hsn": line.hsn_code, "qty": line.qty, "uom": line.uom, "unitPriceMinor": line.unit_price_minor,
                          "netMinor": line.net_minor, "gstRate": line.gst_rate, "needDate": line.need_date,
                          "schedule": [{"seq": sl.seq, "qty": sl.qty, "deliveryDate": sl.delivery_date} for sl in schedule.get(line.id, [])]
                          or [{"seq": 1, "qty": line.qty, "deliveryDate": line.need_date}]})
    if po.version > 1:
        previous = session.execute(select(PoVersion).where(PoVersion.po_id == po.id, PoVersion.version == po.version - 1)).scalar_one_or_none()
        doc.changed_lines = {int(c["line"]) for c in (previous.changes if previous else []) if "line" in c}
    return doc


def portal_document(doc: OrderDoc) -> str:
    po = doc.po
    return json.dumps(jsonable({
        "po": po.number, "version": po.version, "buyer": {"companyCode": po.company_code, "name": doc.company_name, "gstin": doc.company_gstin},
        "supplier": {"code": doc.supplier.code, "name": doc.supplier.legal_name}, "currency": po.currency, "totalMinor": po.total_minor,
        "paymentTerms": po.payment_terms, "incoterms": po.incoterms, "plant": po.plant, "lines": doc.lines,
    }), sort_keys=True, indent=2)


# ---------------------------------------------------------------- UN/EDIFACT D.96A
UNA = "UNA:+.? '"


def _esc(value) -> str:
    text = str(value if value is not None else "")
    for ch in "?+:'":  # release character first
        text = text.replace(ch, "?" + ch)
    return text


def _qty(value) -> str:
    return str(jsonable(Decimal(value)))


def _d(value: date) -> str:
    return value.strftime("%Y%m%d")


def _party_qualifier(identifier: str) -> str:
    return "14" if re.fullmatch(r"\d{13}", identifier or "") else "ZZZ"  # GLN, otherwise mutually defined


def interchange_ref(po: PurchaseOrder) -> str:
    digits = re.sub(r"\D", "", po.number)[-10:]
    return f"{digits}{po.version:03d}"[:14]


def edifact_orders(doc: OrderDoc, sender: str, receiver: str, at: Optional[datetime] = None) -> str:
    """ORDERS (version 1) or ORDCHG (later versions) as one interchange with one message."""
    po = doc.po
    change = po.version > 1
    at = (at or clock.now()).astimezone(clock.IST)
    icref = interchange_ref(po)
    body = [
        f"UNH+1+{'ORDCHG' if change else 'ORDERS'}:D:96A:UN",
        f"BGM+{'230' if change else '220'}+{_esc(po.number)}+{'4' if change else '9'}",
        f"DTM+137:{at:%Y%m%d}:102",
        f"NAD+BY+{_esc(po.company_code)}::92++{_esc(doc.company_name[:35])}",
        f"NAD+SU+{_esc(doc.supplier.code)}::92++{_esc(doc.supplier.legal_name[:35])}",
        f"CUX+2:{_esc(po.currency)}:9",
    ]
    for line in doc.lines:
        action = ("3" if line["line"] in doc.changed_lines else "4") if change else ""
        item = f"{_esc(line['material'])}:IN" if line["material"] else ""
        body.append(f"LIN+{line['line']}+{action}+{item}".rstrip("+"))
        if line["hsn"]:
            body.append(f"PIA+1+{_esc(line['hsn'])}:HS")
        description = line["description"] or ""
        body.append(f"IMD+F++:::{_esc(description[:35])}" + (f":{_esc(description[35:70])}" if len(description) > 35 else ""))
        body.append(f"QTY+21:{_qty(line['qty'])}:{_esc(line['uom'])}")
        body.append(f"DTM+2:{_d(line['schedule'][0]['deliveryDate'])}:102")
        body.append(f"PRI+AAA:{from_minor(line['unitPriceMinor'])}")
        if len(line["schedule"]) > 1:
            for sl in line["schedule"]:
                body += ["SCC+1", f"QTY+21:{_qty(sl['qty'])}:{_esc(line['uom'])}", f"DTM+2:{_d(sl['deliveryDate'])}:102"]
    body += ["UNS+S", f"CNT+2:{len(doc.lines)}"]
    body.append(f"UNT+{len(body) + 1}+1")
    segments = [f"UNB+UNOC:3+{_esc(sender)}:{_party_qualifier(sender)}+{_esc(receiver)}:{_party_qualifier(receiver)}+{at:%y%m%d}:{at:%H%M}+{icref}",
                *body, f"UNZ+1+{icref}"]
    return UNA + "".join(s + "'" for s in segments)


@dataclass
class Segment:
    tag: str
    elements: list[list[str]]

    def el(self, index: int, component: int = 0, default: str = "") -> str:
        try:
            return self.elements[index][component]
        except IndexError:
            return default


@dataclass
class Message:
    type: str
    reference: str
    segments: list[Segment]


@dataclass
class Interchange:
    sender: str
    receiver: str
    reference: str
    messages: list[Message]


def _unescape(text: str, release: str) -> str:
    out, escaped = [], False
    for ch in text:
        if escaped:
            out.append(ch)
            escaped = False
        elif ch == release:
            escaped = True
        else:
            out.append(ch)
    return "".join(out)


def parse(raw: str) -> Interchange:
    """Parse an EDIFACT interchange (UNA optional), checking UNT segment counts and the UNZ message count."""
    text = raw.lstrip("﻿").strip()
    comp, elem, release, term = ":", "+", "?", "'"
    if text.startswith("UNA"):
        if len(text) < 9:
            raise Problem(422, "EDI_SYNTAX", "Truncated UNA service string advice")
        comp, elem, release, term = text[3], text[4], text[6], text[8]
        text = text[9:]
    raw_segments = [s.strip("\r\n\t ") for s in _split_keep(text, term, release)]
    segments = []
    for raw_segment in raw_segments:
        if not raw_segment:
            continue
        fields = _split_keep(raw_segment, elem, release)
        segments.append(Segment(fields[0], [[_unescape(c, release) for c in _split_keep(f, comp, release)] for f in fields[1:]]))
    if not segments or segments[0].tag != "UNB":
        raise Problem(422, "EDI_SYNTAX", "Interchange must start with UNB")
    unb = segments[0]
    if segments[-1].tag != "UNZ":
        raise Problem(422, "EDI_SYNTAX", "Interchange must end with UNZ")
    messages, current = [], None
    for segment in segments[1:-1]:
        if segment.tag == "UNH":
            current = Message(segment.el(1, 0), segment.el(0), [segment])
        elif current is None:
            raise Problem(422, "EDI_SYNTAX", f"Segment {segment.tag} outside a message")
        else:
            current.segments.append(segment)
            if segment.tag == "UNT":
                if segment.el(0) != str(len(current.segments)):
                    raise Problem(422, "EDI_SYNTAX", f"UNT of message {current.reference} counts {segment.el(0)} segments, "
                                  f"the message has {len(current.segments)}")
                messages.append(current)
                current = None
    if current is not None:
        raise Problem(422, "EDI_SYNTAX", f"Message {current.reference} has no UNT")
    unz = segments[-1]
    if unz.el(0) != str(len(messages)) or unz.el(1) != unb.el(4):
        raise Problem(422, "EDI_SYNTAX", "UNZ message count or control reference does not match the interchange")
    return Interchange(unb.el(1), unb.el(2), unb.el(4), messages)


def _split_keep(text: str, sep: str, release: str) -> list[str]:
    """Split on ``sep`` but keep release sequences intact (unescaped later)."""
    parts, current, escaped = [], [], False
    for ch in text:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == release:
            current.append(ch)
            escaped = True
        elif ch == sep:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


def segment_count(document: str) -> dict:
    """Message segment count (UNH..UNT) and the count UNT declares — used by tests and the document viewer."""
    interchange = parse(document)
    message = interchange.messages[0]
    return {"segments": len(message.segments), "declared": int(message.segments[-1].el(0)), "type": message.type}


# ---------------------------------------------------------------- e-mail rendering
def email_document(doc: OrderDoc) -> tuple[str, str]:
    """Subject and HTML body of the order e-mail (the text part is derived from the same document)."""
    po = doc.po
    subject = f"Purchase order {po.number} version {po.version} from {doc.company_name}"
    rows = []
    for line in doc.lines:
        dates = "<br>".join(f"{jsonable(sl['qty'])} {html.escape(line['uom'])} on {sl['deliveryDate']:%d %b %Y}" for sl in line["schedule"])
        rows.append(
            f"<tr><td>{line['line']}</td><td>{html.escape(line['material'] or '')}</td><td>{html.escape(line['description'])}</td>"
            f"<td>{html.escape(line['hsn'] or '')}</td><td style=\"text-align:right\">{jsonable(line['qty'])} {html.escape(line['uom'])}</td>"
            f"<td style=\"text-align:right\">{from_minor(line['unitPriceMinor'])}</td><td style=\"text-align:right\">{from_minor(line['netMinor'])}</td>"
            f"<td>{dates}</td></tr>")
    heading = "Change to purchase order" if po.version > 1 else "Purchase order"
    body = (
        "<!doctype html><html><body style=\"font-family:Arial,sans-serif;font-size:13px;color:#0B1020\">"
        f"<h2>{heading} {html.escape(po.number)} (version {po.version})</h2>"
        f"<p>From {html.escape(doc.company_name)}" + (f" (GSTIN {html.escape(doc.company_gstin)})" if doc.company_gstin else "") +
        f" to {html.escape(doc.supplier.legal_name)} ({html.escape(doc.supplier.code)}).</p>"
        f"<p>Plant {html.escape(po.plant)} · Payment terms {html.escape(po.payment_terms)} · Incoterms {html.escape(po.incoterms or '-')} · "
        f"Currency {html.escape(po.currency)}</p>"
        "<table border=\"1\" cellpadding=\"4\" cellspacing=\"0\" style=\"border-collapse:collapse\">"
        "<tr><th>Line</th><th>Material</th><th>Description</th><th>HSN</th><th>Quantity</th><th>Unit price</th><th>Net</th><th>Delivery schedule</th></tr>"
        + "".join(rows) +
        f"</table><p><strong>Total net {from_minor(po.total_minor)} {html.escape(po.currency)}</strong> (GST extra as applicable).</p>"
        "<p>Please confirm this order (dates per schedule line) in the supplier portal or by EDI ORDRSP.</p></body></html>")
    return subject, body


def html_to_text(document: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", document)
    text = re.sub(r"</(p|h2|tr|table)>", "\n", text)
    text = re.sub(r"</t[dh]>", "\t", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(re.sub(r"\n{3,}", "\n\n", text)).strip()


# ---------------------------------------------------------------- send, deliver, acknowledge
def send(session: Session, po: PurchaseOrder, channels: Optional[list[str]] = None) -> list[PoTransmission]:
    """Create one transmission per channel for the current PO version; delivery follows in the outbox consumer."""
    supplier = session.get(Supplier, po.supplier_id)
    channels = channels or channels_for(supplier)
    doc = _order_doc(session, po)
    settings = supplier.order_channel or {}
    p = principal(session)
    created = []
    for channel in channels:
        status, error, recipient = "QUEUED", None, None
        if channel == "PORTAL":
            fmt, document, status, recipient = "PORTAL", portal_document(doc), "SENT", supplier.code
        elif channel == "EDI":
            fmt = "EDIFACT_ORDCHG" if po.version > 1 else "EDIFACT_ORDERS"
            recipient = settings.get("ediId")
            document = edifact_orders(doc, _tenant_code(session), recipient or supplier.code)
            if not recipient:
                status, error = "FAILED", "Supplier has no EDI partner id (order_channel.ediId)"
        else:
            fmt = "HTML_EMAIL"
            recipient = settings.get("email") or supplier.contact_email
            _, document = email_document(doc)
            if not recipient:
                status, error = "FAILED", "Supplier has no order e-mail address (order_channel.email)"
        record = PoTransmission(tenant_id=po.tenant_id, po_id=po.id, po_version=po.version, channel=channel, format=fmt, document=document,
                                document_sha256=_sha(document), recipient=recipient, status=status, error=error,
                                sent_at=clock.now() if status == "SENT" else None, created_by=p.user_id)
        session.add(record)
        created.append(record)
    session.flush()
    summary = [{"id": str(t.id), "channel": t.channel, "format": t.format, "status": t.status, "recipient": t.recipient,
                "sha256": t.document_sha256, "error": t.error} for t in created]
    audit.record(session, "PURCHASE_ORDER", po.id, "DOCUMENT_TRANSMITTED", object_ref=po.number,
                 after={"version": po.version, "transmissions": summary})
    outbox.emit(session, "purchase_order.transmitted", "PURCHASE_ORDER", po.id, po.number,
                {"version": po.version, "channels": channels, "transmissions": summary})
    return created


def edi_gateway() -> Optional[tuple[str, str]]:
    url = os.environ.get("PIC_EDI_GATEWAY_URL")
    return (url, os.environ.get("PIC_EDI_GATEWAY_TOKEN", "")) if url else None


def _post_edi(url: str, token: str, document: str, reference: str) -> tuple[bool, str]:
    import httpx
    try:
        response = httpx.post(url, content=document.encode("utf-8"), timeout=15,
                              headers={"Content-Type": "application/EDIFACT", "Authorization": f"Bearer {token}" if token else "",
                                       "X-Interchange-Ref": reference})
    except httpx.HTTPError as exc:
        return False, f"EDI gateway unreachable: {type(exc).__name__}"
    if 200 <= response.status_code < 300:
        return True, ""
    return False, f"EDI gateway answered HTTP {response.status_code}"


def deliver(session: Session, record: PoTransmission) -> PoTransmission:
    """Deliver one QUEUED/FAILED EDI or e-mail transmission. Errors are recorded, never raised."""
    if record.channel == "PORTAL" or record.status in ("SENT", "ACKNOWLEDGED") or not record.recipient:
        return record
    before = {"status": record.status, "error": record.error}
    po = session.get(PurchaseOrder, record.po_id)
    if record.channel == "EDI":
        gateway = edi_gateway()
        if gateway is None:
            record.status, record.error = "QUEUED", "EDI gateway not configured"
        else:
            ok, error = _post_edi(gateway[0], gateway[1], record.document, interchange_ref(po))
            record.status, record.error = ("SENT", None) if ok else ("FAILED", error)
    else:
        subject = f"Purchase order {po.number} version {record.po_version}"
        result = mailer.send(record.recipient, subject, html_to_text(record.document), record.document)
        if result == "SENT":
            record.status, record.error = "SENT", None
        elif result == "DISABLED":
            record.status, record.error = "QUEUED", "E-mail delivery disabled: SMTP is not configured (mailer DISABLED)"
        else:
            record.status, record.error = "FAILED", "SMTP delivery failed; see the mailer log"
    if record.status == "SENT":
        record.sent_at = clock.now()
    if before != {"status": record.status, "error": record.error}:
        audit.record(session, "PURCHASE_ORDER", po.id, "TRANSMISSION_" + record.status, object_ref=po.number, before=before,
                     after={"transmission": str(record.id), "channel": record.channel, "version": record.po_version, "status": record.status,
                            "error": record.error})
    return record


@outbox.consumer("purchase_order.transmitted", "po-transmission-delivery")
def _deliver_transmitted(session: Session, event) -> None:
    ids = [uuid.UUID(t["id"]) for t in event.payload.get("transmissions", []) if t.get("channel") in ("EDI", "EMAIL")]
    for record in session.execute(select(PoTransmission).where(PoTransmission.id.in_(ids))).scalars() if ids else []:
        if record.status == "QUEUED":
            deliver(session, record)


def resend(session: Session, po: PurchaseOrder, transmission_id: uuid.UUID) -> PoTransmission:
    record = session.get(PoTransmission, transmission_id)
    if record is None or record.po_id != po.id:
        raise not_found("Transmission", transmission_id)
    if record.channel == "PORTAL" or record.status in ("SENT", "ACKNOWLEDGED"):
        raise Problem(409, "ILLEGAL_TRANSITION", f"Transmission is {record.status}; only queued or failed EDI/e-mail transmissions are re-sent")
    if record.po_version != po.version:
        raise Problem(409, "SUPERSEDED", f"Transmission is for version {record.po_version}; the order is at version {po.version}")
    return deliver(session, record)


def acknowledge(session: Session, po: PurchaseOrder, channel: str) -> Optional[PoTransmission]:
    """The supplier's order response acknowledges the transmission of the current version on that channel."""
    record = session.execute(select(PoTransmission).where(PoTransmission.po_id == po.id, PoTransmission.po_version == po.version,
                                                          PoTransmission.channel == channel)
                             .order_by(PoTransmission.created_at.desc())).scalars().first()
    if record is None or record.status == "ACKNOWLEDGED":
        return record
    before = record.status
    record.status, record.ack_at, record.error = "ACKNOWLEDGED", clock.now(), None
    audit.record(session, "PURCHASE_ORDER", po.id, "TRANSMISSION_ACKNOWLEDGED", object_ref=po.number, before={"status": before},
                 after={"transmission": str(record.id), "channel": channel, "version": po.version})
    return record


def view(record: PoTransmission, with_document: bool = False) -> dict:
    out = {"id": str(record.id), "version": record.po_version, "channel": record.channel, "format": record.format,
           "recipient": record.recipient, "status": record.status, "sha256": record.document_sha256, "bytes": len(record.document.encode("utf-8")),
           "sentAt": record.sent_at.isoformat() if record.sent_at else None, "ackAt": record.ack_at.isoformat() if record.ack_at else None,
           "error": record.error, "createdAt": record.created_at.isoformat()}
    if with_document:
        out["document"] = record.document
        if record.format.startswith("EDIFACT"):
            out["segments"] = segment_count(record.document)
    return out


def transmissions(session: Session, po: PurchaseOrder) -> list[dict]:
    return [view(t) for t in session.execute(select(PoTransmission).where(PoTransmission.po_id == po.id)
                                             .order_by(PoTransmission.po_version.desc(), PoTransmission.created_at)).scalars()]


def get(session: Session, po: PurchaseOrder, transmission_id: uuid.UUID) -> PoTransmission:
    record = session.get(PoTransmission, transmission_id)
    if record is None or record.po_id != po.id:
        raise not_found("Transmission", transmission_id)
    return record


# ---------------------------------------------------------------- inbound EDI (ORDRSP, DESADV)
def _edi_date(segment: Segment) -> Optional[datetime]:
    value, fmt = segment.el(0, 1), segment.el(0, 2, "102")
    try:
        if fmt == "203":
            return datetime.strptime(value, "%Y%m%d%H%M").replace(tzinfo=clock.IST)
        return datetime.strptime(value[:8], "%Y%m%d").replace(tzinfo=clock.IST)
    except ValueError:
        raise Problem(422, "EDI_SYNTAX", f"Invalid date {value} (format {fmt}) in DTM+{segment.el(0)}")


def _partner(session: Session, interchange: Interchange) -> Supplier:
    tenant = _tenant_code(session)
    if interchange.receiver != tenant:
        raise Problem(422, "EDI_PARTNER_MISMATCH", f"Interchange is addressed to {interchange.receiver}, not {tenant}")
    for supplier in session.execute(select(Supplier)).scalars():
        if (supplier.order_channel or {}).get("ediId") == interchange.sender:
            return supplier
    raise Problem(403, "EDI_PARTNER_UNKNOWN", f"No supplier is set up with EDI partner id {interchange.sender}", rule_ref="EDI-PARTNER")


def _supplier_principal(session: Session, supplier: Supplier, edi_id: str) -> Principal:
    """Inbound messages act as the supplier (supplier-scope checks apply), attributed to the EDI channel."""
    base = principal(session)
    return Principal(user_id=uuid.uuid5(uuid.NAMESPACE_URL, f"pic-edi:{base.tenant_id}:{supplier.code}"), tenant_id=base.tenant_id,
                     tenant_code=base.tenant_code, email=f"edi.{supplier.code.lower()}@{edi_id.lower()}.edi", name=f"EDI {supplier.code}",
                     roles=["SUPPLIER_USER"], scopes={"supplier:portal", "po:confirm", "asn:create"}, attributes={}, supplier_id=supplier.id)


def _order_for(session: Session, message: Message, supplier: Supplier) -> PurchaseOrder:
    number = next((s.el(0, 1) for s in message.segments if s.tag == "RFF" and s.el(0) == "ON"), None)
    if not number:
        raise Problem(422, "EDI_SYNTAX", f"{message.type} {message.reference} carries no order reference (RFF+ON)")
    po = session.execute(select(PurchaseOrder).where(PurchaseOrder.number == number).with_for_update()).scalar_one_or_none()
    if po is None or po.supplier_id != supplier.id:
        raise not_found("Purchase order", number)
    return po


def _groups(message: Message) -> list[tuple[Segment, list[Segment]]]:
    groups, current = [], None
    for segment in message.segments:
        if segment.tag == "LIN":
            current = (segment, [])
            groups.append(current)
        elif segment.tag in ("UNS", "CNT", "UNT"):
            current = None
        elif current is not None:
            current[1].append(segment)
    return groups


def _ordrsp(session: Session, message: Message, po: PurchaseOrder) -> dict:
    from app.pic.services import order as order_svc
    bgm = next((s for s in message.segments if s.tag == "BGM"), None)
    if bgm is None:
        raise Problem(422, "EDI_SYNTAX", "ORDRSP without BGM")
    function = bgm.el(2)
    if function not in ("29", "4", "27"):
        raise Problem(422, "EDI_SYNTAX", f"ORDRSP message function {function} is not supported (29, 4 or 27)")
    po_lines = {l.line_no: l for l in order_svc.lines_of(session, po)}
    changes = []
    for lin, segments in _groups(message):
        line = po_lines.get(int(lin.el(0) or 0))
        if line is None:
            raise Problem(422, "UNKNOWN_LINE", f"{po.number} has no line {lin.el(0)}")
        schedule = order_svc.schedule_lines(session, po, line)
        change: dict = {"line": line.line_no}
        confirmations, in_scc, scc_index = [], False, 0
        for segment in segments:
            if segment.tag == "SCC":
                in_scc, scc_index = True, scc_index + 1
            elif segment.tag == "QTY" and segment.el(0) in ("21", "113") and not in_scc:
                qty = Decimal(segment.el(0, 1))
                if qty != line.qty:
                    change["qty"] = str(qty)
            elif segment.tag == "DTM" and segment.el(0) in ("2", "69"):
                when = _edi_date(segment).date().isoformat()
                index = scc_index if in_scc else 1
                if (in_scc or len(schedule) == 1) and 0 < index <= len(schedule):
                    confirmations.append({"seq": schedule[index - 1].seq, "confirmedDate": when})
            elif segment.tag == "PRI" and segment.el(0) == "AAA":
                price = Decimal(segment.el(0, 1))
                if int(price * 100) != line.unit_price_minor:
                    change["unit_price"] = str(price)
        if confirmations:
            change["scheduleConfirmations"] = confirmations
        if len(change) > 1:
            changes.append(change)
    status = "REJECTED" if function == "27" else "CONFIRMED"
    result = order_svc.confirm(session, po, status, changes or None, note=f"EDI ORDRSP {bgm.el(1)}", channel="EDI")
    return {"type": "ORDRSP", "po": po.number, "response": bgm.el(1), "result": result}


def _desadv(session: Session, message: Message, po: PurchaseOrder) -> dict:
    from app.pic import views
    from app.pic.services import order as order_svc
    from app.pic.services import receiving
    bgm = next((s for s in message.segments if s.tag == "BGM"), None)
    ship = expected = valid_until = None
    eway = vehicle = None
    previous_rff = None
    for segment in message.segments:
        if segment.tag == "DTM" and segment.el(0) == "11":
            ship = _edi_date(segment).date()
        elif segment.tag == "DTM" and segment.el(0) == "132":
            expected = _edi_date(segment).date()
        elif segment.tag == "DTM" and segment.el(0) == "36" and previous_rff == "ZEW":
            valid_until = _edi_date(segment)
        elif segment.tag == "RFF" and segment.el(0) == "ZEW":
            eway = segment.el(0, 1)
        elif segment.tag == "TDT":
            vehicle = segment.el(7) or None
        if segment.tag == "RFF":
            previous_rff = segment.el(0)
        elif segment.tag != "DTM":
            previous_rff = None
    if ship is None:
        raise Problem(422, "EDI_SYNTAX", "DESADV needs the despatch date (DTM+11)")
    po_lines = {l.line_no: l for l in order_svc.lines_of(session, po)}
    lines = []
    for lin, segments in _groups(message):
        if int(lin.el(0) or 0) not in po_lines:
            raise Problem(422, "UNKNOWN_LINE", f"{po.number} has no line {lin.el(0)}")
        qty = next((s.el(0, 1) for s in segments if s.tag == "QTY" and s.el(0) == "12"), None)
        if qty is None:
            raise Problem(422, "EDI_SYNTAX", f"DESADV line {lin.el(0)} has no despatch quantity (QTY+12)")
        batches = [s.el(1) for s in segments if s.tag == "GIN" and s.el(0) == "BX"]
        lines.append({"line": int(lin.el(0)), "qty": qty,
                      "batches": [{"batch": b, "qty": qty} for b in batches] if len(batches) == 1 else [{"batch": b} for b in batches]})
    if not lines:
        raise Problem(422, "EDI_SYNTAX", "DESADV has no lines")
    asn = receiving.create_asn(session, po, lines=lines, ship_date=ship, expected_date=expected or ship, eway_bill_no=eway,
                               eway_bill_valid_until=valid_until, vehicle_no=vehicle,
                               documents=[f"DESADV {bgm.el(1) if bgm else message.reference}"])
    return {"type": "DESADV", "po": po.number, "asn": asn.number, "result": views.asn(session, asn)}


def inbound(session: Session, raw: str) -> dict:
    interchange = parse(raw)
    supplier = _partner(session, interchange)
    human = session.info["principal"]
    session.info["principal"] = _supplier_principal(session, supplier, interchange.sender)
    results = []
    try:
        for message in interchange.messages:
            po = _order_for(session, message, supplier)
            if message.type == "ORDRSP":
                results.append(_ordrsp(session, message, po))
            elif message.type == "DESADV":
                results.append(_desadv(session, message, po))
            else:
                raise Problem(422, "EDI_UNSUPPORTED", f"Message type {message.type} is not accepted inbound (ORDRSP, DESADV)")
    finally:
        session.info["principal"] = human
    audit.record(session, "EDI_INTERCHANGE", uuid.uuid5(uuid.NAMESPACE_URL, f"edi:{interchange.sender}:{interchange.reference}"), "RECEIVED",
                 object_ref=f"{interchange.sender}/{interchange.reference}",
                 after={"sender": interchange.sender, "supplier": supplier.code, "sha256": _sha(raw),
                        "messages": [{"type": r["type"], "po": r["po"]} for r in results]})
    return {"interchange": interchange.reference, "sender": interchange.sender, "supplier": supplier.code,
            "messages": [{k: v for k, v in r.items()} for r in results]}
