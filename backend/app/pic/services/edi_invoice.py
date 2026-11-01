"""Inbound EDI invoices: UN/EDIFACT D.96A INVOIC (TD §12.3, BP M10 "invoice capture: portal, PDF/OCR, e-invoice, EDI").

``POST /v1/edi/inbound`` (services/transmission.inbound) hands every INVOIC message here. Implementation guide (UNOC level C):

INVOIC   UNH+<ref>+INVOIC:D:96A:UN
         BGM+<380 invoice | 381 credit note | 383 debit note>+<supplier document number>+9
         DTM+137:<yyyymmdd>:102
         RFF+ON:<PO number>               order reference (380); RFF+IV:<invoice number> the invoice being credited / debited (381, 383)
         RFF+ZZZ:<IRN>                    optional GST e-invoice IRN (mutually defined qualifier), validated like a portal e-invoice
         NAD+BY+<company code>::92   NAD+SU+<supplier code>::92   CUX+2:INR:4
         per line  LIN+<PO line | invoice line>++<material>:IN   PIA+1+<HSN/SAC>:HS   IMD+F++:::<description>
                   QTY+47:<qty>:<uom>  (381: QTY+61, credit quantity)   PRI+AAA:<unit price>   (383: unit debit)
                   MOA+203:<line net>   TAX+7+GST+++:::<rate>+S   MOA+124:<line tax>
         383 charge  ALC+C+<FREIGHT|PACKING|INSURANCE|INSPECTION|HANDLING|OTHER>  MOA+23:<net amount>  TAX+7+GST+++:::<rate>+S
         UNS+S   MOA+77:<invoice gross>   MOA+79:<net total>   MOA+124:<tax total>   CNT+2:<lines>   UNT   UNZ

A 380 becomes an invoice capture with channel EDI (``payables.capture``: supplier's own order only, exact-key and fuzzy duplicate
check, blocked supplier refused, IRN check, mandatory fields, then the match); 381 a credit note and 383 a debit note on the
referenced invoice. Declared totals (MOA+77/79/124) must equal the computed ones.

Acknowledgements are EDIFACT too: a CONTRL (syntax, per interchange and message; action 7 accepted / 4 rejected) and an APERAK
(application, per message: BGM+312 function 29 accepted / 27 not accepted, RFF+IV the document number, ERC the error code and FTX+AAO
the text). A rejected message is rolled back completely and acknowledged with its error; the other messages of the interchange are
unaffected. The interchange is stored once per sender and control reference (``edi_interchange``): a re-delivery returns the stored
acknowledgements (``replayed``), a different document under a used reference is refused (409 EDI_REFERENCE_REUSED).

ERC codes (mutually defined): Z01 duplicate invoice, Z02 order / line / invoice not found for this supplier, Z03 supplier blocked,
Z04 invalid line or amount, Z05 declared totals differ, Z06 supplier identity differs from the sender, Z07 syntax, Z08 mandatory
field missing, Z09 business rule, Z99 other."""
import hashlib
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import EdiInterchange, Invoice, PurchaseOrder, Supplier
from app.pic.platform import audit, clock
from app.pic.platform.errors import Problem
from app.pic.platform.money import D, to_minor
from app.pic.services import transmission as tx

ERC = {"DUPLICATE_INVOICE": ("Z01", "Duplicate invoice"), "DUPLICATE_DEBIT_NOTE": ("Z01", "Duplicate debit note"),
       "NOT_FOUND": ("Z02", "Order, line or invoice not found for this supplier"), "UNKNOWN_LINE": ("Z02", "Line not found"),
       "SUPPLIER_BLOCKED": ("Z03", "Supplier is blocked"), "VALIDATION_FAILED": ("Z04", "Invalid line or amount"),
       "INVALID_CREDIT_NOTE": ("Z04", "Invalid credit note"), "INVALID_DEBIT_NOTE": ("Z04", "Invalid debit note"),
       "EDI_TOTAL_MISMATCH": ("Z05", "Declared totals differ from the lines"), "EDI_SUPPLIER_MISMATCH": ("Z06", "Supplier identity differs"),
       "EDI_SYNTAX": ("Z07", "Syntax error"), "MANDATORY_FIELDS_MISSING": ("Z08", "Mandatory field missing"),
       "RULE_VIOLATION": ("Z09", "Business rule violated"), "DEBIT_NOTE_LIMIT": ("Z09", "Business rule violated"),
       "FORBIDDEN": ("Z06", "Supplier identity differs")}
BGM_TYPES = {"380": "INVOICE", "381": "CREDIT_NOTE", "383": "DEBIT_NOTE"}


# ---------------------------------------------------------------- building (tests, fixtures and the gateway simulator)
def build_invoic(*, sender: str, receiver: str, control_ref: str, document: str, document_date: date, po: Optional[str], lines: list[dict],
                 function: str = "380", irn: Optional[str] = None, original_invoice: Optional[str] = None, company_code: str = "1000",
                 supplier_code: Optional[str] = None, declared_gross_minor: Optional[int] = None, extra_messages: int = 1,
                 at: Optional[datetime] = None) -> str:
    """One interchange of INVOIC message(s). Each line: ``line``, ``qty``, ``unit_price`` (rupees), ``gst_rate``; optional ``hsn``,
    ``material``, ``description``, ``uom``, ``tax_minor``. For 383 a charge line has ``charge`` and ``amount`` (rupees) instead."""
    at = (at or clock.now()).astimezone(clock.IST)
    esc = tx._esc
    body = [f"UNH+1+INVOIC:D:96A:UN", f"BGM+{function}+{esc(document)}+9", f"DTM+137:{document_date:%Y%m%d}:102"]
    if po:
        body.append(f"RFF+ON:{esc(po)}")
    if original_invoice:
        body.append(f"RFF+IV:{esc(original_invoice)}")
    if irn:
        body.append(f"RFF+ZZZ:{esc(irn)}")
    body += [f"NAD+BY+{esc(company_code)}::92", f"NAD+SU+{esc(supplier_code or sender)}::92", "CUX+2:INR:4"]
    net_total = tax_total = 0
    count = 0
    for entry in lines:
        rate = D(entry.get("gst_rate", 18))
        if entry.get("charge"):
            net = to_minor(entry["amount"])
            body += [f"ALC+C+{esc(entry['charge'])}", f"MOA+23:{D(net) / 100:.2f}", f"TAX+7+GST+++:::{rate:f}+S"]
            tax = int(entry["tax_minor"]) if "tax_minor" in entry else int((D(net) * rate / 100).quantize(Decimal(1)))
        else:
            qty = D(entry["qty"])
            price = D(entry["unit_price"])
            net = int((qty * price * 100).quantize(Decimal(1)))
            tax = int(entry["tax_minor"]) if "tax_minor" in entry else int((D(net) * rate / 100).quantize(Decimal(1)))
            material = f"{esc(entry['material'])}:IN" if entry.get("material") else ""
            body.append(f"LIN+{entry['line']}++{material}".rstrip("+"))
            if entry.get("hsn"):
                body.append(f"PIA+1+{esc(entry['hsn'])}:HS")
            if entry.get("description"):
                body.append(f"IMD+F++:::{esc(str(entry['description'])[:35])}")
            body += [f"QTY+{'61' if function == '381' else '47'}:{qty:f}:{esc(entry.get('uom', 'EA'))}", f"PRI+AAA:{price:f}",
                     f"MOA+203:{D(net) / 100:.2f}", f"TAX+7+GST+++:::{rate:f}+S", f"MOA+124:{D(tax) / 100:.2f}"]
        net_total += net
        tax_total += tax
        count += 1
    gross = net_total + tax_total if declared_gross_minor is None else declared_gross_minor
    body += ["UNS+S", f"MOA+77:{D(gross) / 100:.2f}", f"MOA+79:{D(net_total) / 100:.2f}", f"MOA+124:{D(tax_total) / 100:.2f}", f"CNT+2:{count}"]
    body.append(f"UNT+{len(body) + 1}+1")
    messages = list(body)
    segments = [f"UNB+UNOC:3+{esc(sender)}:{tx._party_qualifier(sender)}+{esc(receiver)}:{tx._party_qualifier(receiver)}"
                f"+{at:%y%m%d}:{at:%H%M}+{control_ref}", *messages, f"UNZ+1+{control_ref}"]
    return tx.UNA + "".join(s + "'" for s in segments)


# ---------------------------------------------------------------- acknowledgements
def _envelope(from_party: str, to_party: str, ref: str, messages: list[list[str]], at: datetime) -> str:
    esc = tx._esc
    segs = [f"UNB+UNOC:3+{esc(from_party)}:{tx._party_qualifier(from_party)}+{esc(to_party)}:"
            f"{tx._party_qualifier(to_party)}+{at:%y%m%d}:{at:%H%M}+{ref}"]
    for number, body in enumerate(messages, start=1):
        segs.append(body[0].replace("UNH+1+", f"UNH+{number}+", 1))
        segs += body[1:]
        segs.append(f"UNT+{len(body) + 1}+{number}")
    segs.append(f"UNZ+{len(messages)}+{ref}")
    return tx.UNA + "".join(s + "'" for s in segs)


def _ack_ref(control_ref: str, kind: str) -> str:
    return (kind + control_ref)[:14]


def contrl(sender: str, receiver: str, control_ref: str, messages: list[tuple[str, str, bool, Optional[str]]], *, syntax_error: Optional[str] = None,
           at: Optional[datetime] = None) -> str:
    """CONTRL D.96A: UCI for the interchange (7 accepted / 4 rejected) and a UCM per message (reference, type, accepted, syntax error code)."""
    at = (at or clock.now()).astimezone(clock.IST)
    esc = tx._esc
    accepted = syntax_error is None
    body = ["UNH+1+CONTRL:D:96A:UN",
            f"UCI+{esc(control_ref)}+{esc(sender)}:{tx._party_qualifier(sender)}+{esc(receiver)}:{tx._party_qualifier(receiver)}+{7 if accepted else 4}"
            + (f"+{esc(syntax_error)}" if syntax_error else "")]
    for reference, mtype, ok, error in messages:
        body.append(f"UCM+{esc(reference)}+{esc(mtype)}:D:96A:UN+{7 if ok else 4}" + (f"+{esc(error)}" if error else ""))
    return _envelope(receiver, sender, _ack_ref(control_ref, "C"), [body], at)


def aperak(sender: str, receiver: str, control_ref: str, results: list[dict], *, at: Optional[datetime] = None) -> str:
    """APERAK D.96A, one message per acknowledged document: BGM+312 (29 accepted / 27 not accepted), RFF+IV document number, ERC + FTX on rejection."""
    at = (at or clock.now()).astimezone(clock.IST)
    esc = tx._esc
    messages = []
    for r in results:
        ok = r["outcome"] == "ACCEPTED"
        body = ["UNH+1+APERAK:D:96A:UN", f"BGM+312+{esc(r['reference'])}+{29 if ok else 27}", f"DTM+137:{at:%Y%m%d}:102",
                f"RFF+ACW:{esc(r['messageRef'])}", f"RFF+IV:{esc(r['document'])}"]
        if ok:
            body.append(f"FTX+AAI+++{esc(r.get('detail') or 'Accepted')}")
        else:
            for error in r["errors"]:
                body += [f"ERC+{error['code']}", f"FTX+AAO+++{esc(error['text'])[:512]}"]
        messages.append(body)
    return _envelope(receiver, sender, _ack_ref(control_ref, "A"), messages, at) if messages else ""


def contrl_reject(raw: str, detail: str) -> str:
    """Best-effort CONTRL for an interchange that could not be parsed: sender, receiver and reference are read from the UNB if present."""
    match = re.search(r"UNB\+[^+]*\+([^+:']*)[^+]*\+([^+:']*)[^+]*\+[^+]*\+([^+']*)", raw or "")
    sender, receiver, ref = (match.groups() if match else ("UNKNOWN", "UNKNOWN", "0"))
    return contrl(sender or "UNKNOWN", receiver or "UNKNOWN", (ref or "0")[:14], [], syntax_error="2")


# ---------------------------------------------------------------- reading a message
def _segments(message: tx.Message, tag: str) -> list[tx.Segment]:
    return [s for s in message.segments if s.tag == tag]


def _first(message: tx.Message, tag: str, qualifier: Optional[str] = None) -> Optional[tx.Segment]:
    for s in message.segments:
        if s.tag == tag and (qualifier is None or s.el(0) == qualifier):
            return s
    return None


def _decimal(text: str, what: str) -> Decimal:
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        raise Problem(422, "EDI_SYNTAX", f"{what}: '{text}' is not a number")
    if not value.is_finite():
        raise Problem(422, "EDI_SYNTAX", f"{what}: '{text}' is not a number")
    return value


def _line_groups(message: tx.Message) -> list[tuple[Optional[tx.Segment], list[tx.Segment]]]:
    """LIN / ALC groups in order (a charge group starts at ALC)."""
    groups, current = [], None
    for s in message.segments:
        if s.tag in ("LIN", "ALC"):
            current = (s, [])
            groups.append(current)
        elif s.tag in ("UNS", "CNT", "UNT"):
            current = None
        elif current is not None:
            current[1].append(s)
    return groups


def parse_message(message: tx.Message) -> dict:
    bgm = _first(message, "BGM")
    if bgm is None or bgm.el(0) not in BGM_TYPES:
        raise Problem(422, "EDI_SYNTAX", f"INVOIC {message.reference}: BGM document name code must be 380, 381 or 383")
    number = bgm.el(1).strip()
    if not number:
        raise Problem(422, "EDI_SYNTAX", f"INVOIC {message.reference}: the document number (BGM) is missing")
    dtm = _first(message, "DTM", "137")
    if dtm is None:
        raise Problem(422, "EDI_SYNTAX", f"INVOIC {number}: the document date (DTM+137) is missing")
    rff = lambda q: next((s.el(0, 1) for s in message.segments if s.tag == "RFF" and s.el(0) == q), None)  # noqa: E731
    lines = []
    for head, segs in _line_groups(message):
        tax_seg = next((s for s in segs if s.tag == "TAX"), None)
        rate = _decimal(tax_seg.el(4, 3) or "0", f"{number} tax rate") if tax_seg is not None else None
        moa = {s.el(0): s.el(0, 1) for s in segs if s.tag == "MOA"}
        if head.tag == "ALC":
            lines.append({"charge": head.el(1) or "OTHER", "amount": _decimal(moa.get("23", ""), f"{number} charge amount"), "gst_rate": rate})
            continue
        qty_seg = next((s for s in segs if s.tag == "QTY" and s.el(0) in ("47", "61")), None)
        price_seg = next((s for s in segs if s.tag == "PRI" and s.el(0) == "AAA"), None)
        if qty_seg is None or price_seg is None:
            raise Problem(422, "EDI_SYNTAX", f"INVOIC {number} line {head.el(0)}: quantity (QTY+47/61) and price (PRI+AAA) are required")
        pia = next((s for s in segs if s.tag == "PIA"), None)
        lines.append({"line": int(head.el(0) or 0), "qty": _decimal(qty_seg.el(0, 1), f"{number} quantity"),
                      "unit_price": _decimal(price_seg.el(0, 1), f"{number} price"), "gst_rate": rate,
                      "hsn": pia.el(1) if pia is not None and pia.el(1, 1) == "HS" else None,
                      "tax": _decimal(moa["124"], f"{number} line tax") if "124" in moa else None,
                      "net": _decimal(moa["203"], f"{number} line amount") if "203" in moa else None})
    if not lines:
        raise Problem(422, "EDI_SYNTAX", f"INVOIC {number} has no lines")
    totals = {}
    after_uns = False
    for s in message.segments:
        if s.tag == "UNS":
            after_uns = True
        elif after_uns and s.tag == "MOA":
            totals[s.el(0)] = _decimal(s.el(0, 1), f"{number} total")
    su = _first(message, "NAD", "SU")
    return {"function": bgm.el(0), "number": number, "date": tx._edi_date(dtm).date(), "po": rff("ON"), "original": rff("IV"), "irn": rff("ZZZ"),
            "supplierParty": su.el(1) if su is not None else None, "company": (_first(message, "NAD", "BY").el(1) if _first(message, "NAD", "BY") else None),
            "lines": lines, "totals": totals}


# ---------------------------------------------------------------- application mapping
def _to_minor(value: Decimal) -> int:
    return int((value * 100).quantize(Decimal(1)))


def _capture(session: Session, doc: dict, supplier: Supplier) -> dict:
    from app.pic.services import payables
    if not doc["po"]:
        raise Problem(422, "VALIDATION_FAILED", f"INVOIC {doc['number']}: the order reference (RFF+ON) is missing")
    po = session.execute(select(PurchaseOrder).where(PurchaseOrder.number == doc["po"], PurchaseOrder.supplier_id == supplier.id)).scalar_one_or_none()
    if po is None:
        raise Problem(404, "NOT_FOUND", f"Purchase order {doc['po']} of supplier {supplier.code} not found")
    if doc["company"] and doc["company"] != po.company_code:
        raise Problem(422, "VALIDATION_FAILED", f"INVOIC {doc['number']}: buyer {doc['company']} differs from the company code {po.company_code} of {po.number}")
    lines = []
    for l in doc["lines"]:
        if l.get("charge"):
            raise Problem(422, "VALIDATION_FAILED", f"INVOIC {doc['number']}: an additional charge is a debit note (BGM 383), not an invoice line")
        entry = {"po": po.number, "po_line": l["line"], "qty": str(l["qty"]), "unit_price": str(l["unit_price"])}
        if l["gst_rate"] is not None:
            entry["gst_rate"] = str(l["gst_rate"])
        if l["hsn"]:
            entry["hsn"] = l["hsn"]
        if l["tax"] is not None:
            entry["tax_minor"] = _to_minor(l["tax"])
        lines.append(entry)
    invoice = payables.capture(session, supplier=supplier.code, supplier_invoice_no=doc["number"], invoice_date=doc["date"], channel="EDI",
                               lines=lines, irn=doc["irn"], company_code=po.company_code)
    totals = doc["totals"]
    for code, label, actual in (("77", "gross", invoice.gross_minor), ("79", "net", invoice.net_minor), ("124", "tax", invoice.tax_minor)):
        if code in totals and _to_minor(totals[code]) != actual:
            raise Problem(422, "EDI_TOTAL_MISMATCH", f"INVOIC {doc['number']}: declared {label} {_to_minor(totals[code]) / 100:,.2f} differs from the "
                          f"lines {actual / 100:,.2f}")
    return {"object": "INVOICE", "number": invoice.number, "status": invoice.status, "grossMinor": invoice.gross_minor,
            "detail": f"Captured as {invoice.number}, status {invoice.status}"}


def _referenced_invoice(session: Session, doc: dict, supplier: Supplier) -> Invoice:
    if not doc["original"]:
        raise Problem(422, "VALIDATION_FAILED", f"{doc['number']}: the invoice being corrected (RFF+IV) is missing")
    invoice = session.execute(select(Invoice).where(Invoice.supplier_id == supplier.id, Invoice.supplier_invoice_no == doc["original"])
                              .order_by(Invoice.created_at.desc())).scalars().first()
    if invoice is None:
        raise Problem(404, "NOT_FOUND", f"Invoice {doc['original']} of supplier {supplier.code} not found")
    return invoice


def _credit(session: Session, doc: dict, supplier: Supplier) -> dict:
    from app.pic.services import payables
    invoice = _referenced_invoice(session, doc, supplier)
    note = payables.submit_credit_note(session, invoice, supplier_credit_note_no=doc["number"], note_date=doc["date"],
                                       reason=f"EDI credit note {doc['number']} against {invoice.supplier_invoice_no}",
                                       lines=[{"invoice_line": l["line"], "qty": str(l["qty"])} for l in doc["lines"] if not l.get("charge")])
    return {"object": "CREDIT_NOTE", "number": note.number, "status": "RECEIVED", "grossMinor": note.gross_minor,
            "detail": f"Credit note {note.number} recorded against {invoice.number}"}


def _debit(session: Session, doc: dict, supplier: Supplier) -> dict:
    from app.pic.services import debit_notes
    invoice = _referenced_invoice(session, doc, supplier)
    lines = []
    for l in doc["lines"]:
        if l.get("charge"):
            lines.append({"kind": "CHARGE", "charge": l["charge"], "amount_minor": _to_minor(l["amount"]), "gst_rate": str(l["gst_rate"] or 18)})
        else:
            lines.append({"kind": "PRICE", "invoice_line": l["line"], "qty": str(l["qty"]), "unit_debit_minor": _to_minor(l["unit_price"])})
    note = debit_notes.submit(session, invoice, supplier_debit_note_no=doc["number"], note_date=doc["date"],
                              reason=f"EDI debit note {doc['number']} against {invoice.supplier_invoice_no}", lines=lines)
    return {"object": "DEBIT_NOTE", "number": note.number, "status": note.status, "grossMinor": note.gross_minor,
            "detail": f"Debit note {note.number} recorded against {invoice.number}, status {note.status}"}


def handle(session: Session, message: tx.Message, supplier: Supplier, interchange: tx.Interchange) -> dict:
    """Process one INVOIC message in a savepoint. Never raises for a business or content error: the message is rolled back and the result
    carries the APERAK error."""
    base = {"type": "INVOIC", "messageRef": message.reference, "reference": f"{interchange.reference}-{message.reference}"}
    document = None
    try:
        doc = parse_message(message)
        document = doc["number"]
        if doc["supplierParty"] and doc["supplierParty"] not in (supplier.code, interchange.sender):
            raise Problem(422, "EDI_SUPPLIER_MISMATCH", f"INVOIC {document}: seller {doc['supplierParty']} is not the sender {interchange.sender} "
                          f"({supplier.code})")
        with session.begin_nested():
            outcome = {"380": _capture, "381": _credit, "383": _debit}[doc["function"]](session, doc, supplier)
        return {**base, "document": document, "outcome": "ACCEPTED", "documentType": BGM_TYPES[doc["function"]], **outcome}
    except Problem as exc:
        code, text = ERC.get(exc.code, ("Z99", "Rejected"))
        return {**base, "document": document or message.reference, "outcome": "REJECTED", "problemCode": exc.code,
                "errors": [{"code": code, "text": f"{text}: {exc.detail}"}]}


# ---------------------------------------------------------------- the interchange record (idempotency anchor)
def stored(session: Session, sender: str, control_ref: str) -> Optional[EdiInterchange]:
    return session.execute(select(EdiInterchange).where(EdiInterchange.sender == sender, EdiInterchange.control_ref == control_ref)).scalar_one_or_none()


def record(session: Session, interchange: tx.Interchange, supplier: Supplier, raw: str, results: list[dict], contrl_doc: str,
           aperak_doc: Optional[str]) -> EdiInterchange:
    rejected = [r for r in results if r.get("outcome") == "REJECTED"]
    status = "REJECTED" if rejected and len(rejected) == len(results) else "PARTIAL" if rejected else "ACCEPTED"
    row = EdiInterchange(tenant_id=supplier.tenant_id, sender=interchange.sender[:35], receiver=interchange.receiver[:35],
                         control_ref=interchange.reference[:14], supplier_id=supplier.id, sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                         status=status, message_types=sorted({m.type for m in interchange.messages}), results=results, raw=raw,
                         contrl=contrl_doc, aperak=aperak_doc)
    session.add(row)
    session.flush()
    audit.record(session, "EDI_INTERCHANGE", row.id, status, object_ref=f"{row.sender}/{row.control_ref}",
                 after={"supplier": supplier.code, "messages": [{"document": r.get("document"), "outcome": r.get("outcome"),
                                                                "object": r.get("number"), "errors": r.get("errors")} for r in results]})
    return row


def view(row: EdiInterchange, replayed: bool = False) -> dict:
    return {"interchange": row.control_ref, "sender": row.sender, "status": row.status, "messages": row.results, "contrl": row.contrl,
            "aperak": row.aperak, "sha256": row.sha256, **({"replayed": True} if replayed else {})}
