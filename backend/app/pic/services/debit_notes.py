"""Supplier debit notes (BP M10 "credit/debit notes and retention").

A debit note is the supplier's document that *increases* what is owed on an invoice (GST Act s.34): an upward price correction on an
invoice line (``PRICE``: qty × unit debit) or an additional charge such as freight or packing (``CHARGE``). It is raised by the
supplier in the portal (or by accounts payable on the supplier's behalf) against an invoice and then

    RECEIVED ─ match ─▶ MATCHED ─ approve (AP) ─▶ APPROVED ─ post ─▶ POSTED (ERP vendor debit memo, message SUPPLIER_DEBIT_MEMO)
        └─ outside the order price, or any charge ─▶ PENDING_APPROVAL ─ buyer chain (rule DEBIT-NOTE bands) ─▶ MATCHED

Matching: a price correction is within the order when invoice price + all debits on that line ≤ PO price (+ ``unitTolerancePct``);
anything else, and every additional charge (not covered by a PO line), needs the buyer chain of rule DEBIT-NOTE. A note may not
exceed ``maxPctOfInvoice`` of the invoice net together with earlier notes.

A posted debit note nets into the payment of its invoice (payables.payment_run adds it), is paid on its own when the invoice was
already paid, adds retention on price corrections of orders with a retention percentage, increases the ERP-side amount in the
nightly reconciliation (``|DN|`` memos) and the invoiced value of the PO lines it corrects."""
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import DebitNote, Invoice, InvoiceLine, PoLine, PurchaseOrder, Supplier, Task
from app.pic.platform import audit, clock, integration, outbox, sod, workflow
from app.pic.platform.core import StateMachine, link
from app.pic.platform.errors import Problem, illegal_transition, not_found, rule_violation
from app.pic.platform.money import D, fmt_inr, line_amount, pct_of, tax_amount
from app.pic.platform.serialize import jsonable
from app.pic.services import p2p_rules
from app.pic.services.common import principal, require_supplier_user

KEY = "DEBIT-NOTE"
MESSAGE_TYPE = "SUPPLIER_DEBIT_MEMO"
APPROVAL_TASK = "DEBIT_NOTE_APPROVAL"
SM = StateMachine("DEBIT_NOTE", {
    ("RECEIVED", "match"): "MATCHED",
    ("RECEIVED", "refer"): "PENDING_APPROVAL",
    ("PENDING_APPROVAL", "approve_variance"): "MATCHED",
    ("MATCHED", "approve"): "APPROVED",
    ("APPROVED", "post"): "POSTED",
    ("RECEIVED", "reject"): "REJECTED",
    ("MATCHED", "reject"): "REJECTED",
    ("PENDING_APPROVAL", "reject"): "REJECTED",
    ("APPROVED", "reject"): "REJECTED",
})
SETTLED = ("POSTED",)
NOT_COUNTED = ("REJECTED",)


# ---------------------------------------------------------------- reading
def notes_of(session: Session, invoice: Invoice, statuses: Optional[tuple] = None) -> list[DebitNote]:
    query = select(DebitNote).where(DebitNote.invoice_id == invoice.id).order_by(DebitNote.created_at)
    if statuses:
        query = query.where(DebitNote.status.in_(statuses))
    return session.execute(query).scalars().all()


def posted_value_by_line(session: Session, invoice: Invoice) -> dict[int, int]:
    """Net value of posted price-correction debits per invoice line number (feeds the retention base and the PO line's invoiced value)."""
    out: dict[int, int] = {}
    for note in notes_of(session, invoice, SETTLED):
        for entry in note.lines:
            if entry.get("kind") == "PRICE":
                out[int(entry["invoice_line"])] = out.get(int(entry["invoice_line"]), 0) + int(entry["netMinor"])
    return out


def _debited_net(session: Session, invoice: Invoice, line_no: int, exclude: Optional[uuid.UUID] = None) -> int:
    """Net value of the live price corrections other notes make on an invoice line."""
    total = 0
    for note in notes_of(session, invoice):
        if note.status in NOT_COUNTED or note.id == exclude:
            continue
        total += sum(int(e["netMinor"]) for e in note.lines if e.get("kind") == "PRICE" and int(e["invoice_line"]) == line_no)
    return total


def payable_adjustment(session: Session, invoice: Invoice) -> tuple[int, list[DebitNote]]:
    """Gross of the posted, unpaid debit notes that settle with this invoice's payment. The retention they withhold is already part of
    ``invoice.retention_minor`` (added when the note was posted), so the payment run subtracts it there."""
    notes = [n for n in notes_of(session, invoice, SETTLED) if n.payment_status == "UNPAID"]
    return sum(n.gross_minor for n in notes), notes


# ---------------------------------------------------------------- raising
def submit(session: Session, invoice: Invoice, *, supplier_debit_note_no: str, note_date: date, reason: str, lines: list[dict]) -> DebitNote:
    """A supplier debit note against an invoice. Lines: ``{"kind": "PRICE", "invoice_line": 10, "qty": "20", "unit_debit_minor": 150}`` or
    ``{"kind": "CHARGE", "charge": "FREIGHT", "description": "Freight", "amount_minor": 120000, "gst_rate": "18", "hsn": "996511"}``."""
    p = principal(session)
    rule = p2p_rules.rule(session, KEY, company_code=invoice.company_code)
    require_supplier_user(session, invoice.supplier_id)
    if "SUPPLIER_USER" not in p.roles and not set(p.roles) & set(rule.body.get("requiredRoles") or ["AP_CLERK"]):
        raise Problem(403, "FORBIDDEN", "A debit note is raised by the supplier, or by accounts payable on the supplier's behalf")
    if invoice.status == "REJECTED":
        raise illegal_transition("Invoice", invoice.number, invoice.status, "debit")
    if invoice.match_type == "RETENTION":
        raise rule_violation(f"{invoice.number} is a retention release; a debit note is raised against the supplier's invoice", KEY)
    from app.pic.services import finance_controls
    for day in dict.fromkeys((clock.today(), note_date)):  # the day it is posted and the date the document carries (D42)
        finance_controls.assert_open(session, invoice.company_code, day, f"debit note against {invoice.number} dated {note_date.isoformat()}")
    if len((reason or "").strip()) < 3:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for the debit note", rule_ref=KEY)
    if not lines:
        raise Problem(422, "VALIDATION_FAILED", "A debit note needs at least one line", rule_ref=KEY)
    note_no = (supplier_debit_note_no or "").strip()
    if not note_no:
        raise Problem(422, "VALIDATION_FAILED", "Give the supplier's debit note number", rule_ref=KEY)
    if note_date > clock.today():
        raise rule_violation(f"The debit note date {note_date.isoformat()} is in the future", KEY)
    supplier = session.get(Supplier, invoice.supplier_id)
    existing = session.execute(select(DebitNote).where(DebitNote.supplier_id == invoice.supplier_id,
                                                       DebitNote.supplier_debit_note_no == note_no)).scalar_one_or_none()
    if existing is not None:
        raise Problem(409, "DUPLICATE_DEBIT_NOTE", f"{note_no} from {supplier.code} is already recorded as {existing.number}", rule_ref=KEY,
                      duplicateOf=existing.number)
    inv_lines = {l.line_no: l for l in session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)).scalars()}
    from app.pic.services import payables
    credited_qty = payables._credited_qty(session, invoice)
    stored, errors = [], []
    net = tax = 0
    seen_price: dict[int, Decimal] = {}
    for earlier_note in notes_of(session, invoice):  # quantity already corrected by earlier (live) debit notes counts too
        if earlier_note.status in NOT_COUNTED:
            continue
        for e in earlier_note.lines:
            if e.get("kind") == "PRICE":
                seen_price[int(e["invoice_line"])] = seen_price.get(int(e["invoice_line"]), Decimal(0)) + D(e["qty"])
    for position, entry in enumerate(lines, start=1):
        kind = str(entry.get("kind") or ("PRICE" if entry.get("invoice_line") is not None else "CHARGE")).upper()
        try:
            if kind == "PRICE":
                line_no = int(entry["invoice_line"])
                qty = D(entry["qty"])
                unit = int(entry["unit_debit_minor"])
            elif kind == "CHARGE":
                amount = int(entry["amount_minor"])
            else:
                errors.append(f"line {position}: kind must be PRICE or CHARGE")
                continue
        except (KeyError, TypeError, ValueError, ArithmeticError):
            errors.append(f"line {position}: a PRICE line needs invoice_line, qty and unit_debit_minor; a CHARGE line needs amount_minor")
            continue
        if kind == "PRICE":
            line = inv_lines.get(line_no)
            if line is None:
                errors.append(f"line {position}: invoice line {line_no} does not exist")
                continue
            open_qty = line.qty - credited_qty.get(line_no, Decimal(0))
            already = seen_price.get(line_no, Decimal(0))
            if not qty.is_finite() or qty <= 0 or unit <= 0:
                errors.append(f"line {position}: quantity and unit debit must be positive")
                continue
            if qty + already > open_qty:
                errors.append(f"line {position}: quantity {jsonable(qty)} exceeds the invoiced quantity of line {line_no} ({jsonable(open_qty)})")
                continue
            seen_price[line_no] = already + qty
            amount_net = line_amount(qty, unit)
            rate = line.gst_rate
            stored.append({"kind": "PRICE", "invoice_line": line_no, "qty": str(entry["qty"]), "unitDebitMinor": unit, "netMinor": amount_net,
                           "taxMinor": tax_amount(amount_net, rate), "gstRate": str(rate), "hsn": line.hsn_code, "description": line.description})
        else:
            charge = str(entry.get("charge") or "OTHER").upper()
            if charge not in (rule.body.get("chargeKinds") or ["OTHER"]):
                errors.append(f"line {position}: charge kind {charge} is not allowed ({', '.join(rule.body.get('chargeKinds') or [])})")
                continue
            if amount <= 0:
                errors.append(f"line {position}: the charge must be positive")
                continue
            rate = D(entry.get("gst_rate", 18))
            description = (entry.get("description") or charge.title())[:200]
            stored.append({"kind": "CHARGE", "charge": charge, "description": description, "netMinor": amount, "taxMinor": tax_amount(amount, rate),
                           "gstRate": str(rate), "hsn": entry.get("hsn")})
            amount_net = amount
        net += amount_net
        tax += stored[-1]["taxMinor"]
    if errors:
        raise Problem(422, "INVALID_DEBIT_NOTE", "; ".join(errors), rule_ref=KEY, errors=errors)
    earlier = sum(n.net_minor for n in notes_of(session, invoice) if n.status not in NOT_COUNTED)
    cap = pct_of(invoice.net_minor, D(rule.body.get("maxPctOfInvoice", 25)))
    if earlier + net > cap:
        raise Problem(422, "DEBIT_NOTE_LIMIT", f"Debit notes would total {fmt_inr(earlier + net)}, above {rule.body.get('maxPctOfInvoice', 25)}% of the "
                      f"invoice net ({fmt_inr(cap)}); raise a purchase order change or a dispute instead", rule_ref=rule.ref,
                      limitMinor=cap, totalMinor=earlier + net)
    number = f"DN-{supplier.code}-{note_no}"[:40]
    if session.execute(select(DebitNote.id).where(DebitNote.number == number)).first():
        number = f"{number[:34]}-{uuid.uuid4().hex[:5]}"
    note = DebitNote(tenant_id=invoice.tenant_id, number=number, supplier_debit_note_no=note_no, supplier_id=invoice.supplier_id,
                     invoice_id=invoice.id, note_date=note_date, reason=reason.strip(), status="RECEIVED", net_minor=net, tax_minor=tax,
                     gross_minor=net + tax, lines=stored, match_result={}, rule_set_version=rule.ref, created_by=p.user_id)
    session.add(note)
    session.flush()
    link(session, "INVOICE", invoice.id, invoice.number, "DEBIT_NOTE", note.id, note.number, "debited_by")
    audit.record(session, "DEBIT_NOTE", note.id, "RECEIVED", object_ref=note.number, reason=note.reason, rule_set_version=rule.ref,
                 after={"invoice": invoice.number, "supplier": supplier.code, "grossMinor": note.gross_minor, "lines": len(stored),
                        "raisedBy": p.actor})
    audit.record(session, "INVOICE", invoice.id, "DEBIT_NOTE_RECEIVED", object_ref=invoice.number,
                 after={"debitNote": note.number, "grossMinor": note.gross_minor}, reason=note.reason)
    outbox.emit(session, "debit_note.received", "DEBIT_NOTE", note.id, note.number,
                {"invoice": invoice.number, "supplier": supplier.code, "grossMinor": note.gross_minor})
    match(session, note, invoice)
    return note


# ---------------------------------------------------------------- matching and approval
def _band_chain(rule, gross_minor: int) -> list[str]:
    for band in rule.body.get("approvalBands") or []:
        if band.get("upTo") is None or gross_minor <= int(band["upTo"]):
            return list(band["chain"])
    return ["BUYER"]


def match(session: Session, note: DebitNote, invoice: Optional[Invoice] = None) -> dict:
    """Price corrections within the order price (+ tolerance) match; the rest, and every charge, go to the buyer chain."""
    invoice = invoice or session.get(Invoice, note.invoice_id)
    rule = p2p_rules.rule(session, KEY, company_code=invoice.company_code)
    inv_lines = {l.line_no: l for l in session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)).scalars()}
    tolerance = D(rule.body.get("unitTolerancePct", 0))
    findings, checks, creators = [], [], []
    for entry in note.lines:
        if entry["kind"] == "CHARGE":
            findings.append({"kind": "CHARGE", "detail": f"{entry['description']} {fmt_inr(entry['netMinor'])} is not covered by an order line"})
            continue
        line = inv_lines[int(entry["invoice_line"])]
        po_line = session.get(PoLine, line.po_line_id) if line.po_line_id else None
        # the corrected unit price of the line: its price plus every live correction (this note's included) spread over the invoiced quantity
        effective = int((Decimal(line.unit_price_minor) + Decimal(_debited_net(session, invoice, line.line_no, exclude=note.id)
                                                                  + int(entry["netMinor"])) / line.qty).quantize(Decimal(1)))
        allowed = int(Decimal(po_line.unit_price_minor) * (1 + tolerance / 100)) if po_line else line.unit_price_minor
        check = {"invoiceLine": line.line_no, "invoicePriceMinor": line.unit_price_minor, "correctedPriceMinor": effective,
                 "poPriceMinor": po_line.unit_price_minor if po_line else None, "allowedMinor": allowed, "withinOrder": effective <= allowed}
        checks.append(check)
        if effective > allowed:
            findings.append({"kind": "PRICE", "detail": f"line {line.line_no}: corrected price {effective / 100:,.2f} is above the order price "
                             f"{(po_line.unit_price_minor if po_line else 0) / 100:,.2f}"})
        if po_line is not None:
            creators.append(session.get(PurchaseOrder, po_line.po_id).created_by)
    # SOD-04 reaches every debit note on the invoice, not only those with a price line: whoever created an order the invoice bills may
    # not approve a charge or price correction on it (a CHARGE line carries no order line of its own).
    for inv_line in inv_lines.values():
        charged_line = session.get(PoLine, inv_line.po_line_id) if inv_line.po_line_id else None
        if charged_line is not None:
            creators.append(session.get(PurchaseOrder, charged_line.po_id).created_by)
    note.match_result = {"checks": checks, "findings": findings, "rule": rule.ref}
    if not findings:
        SM.apply(session, note, "match", rule_set_version=rule.ref, extra_after={"checks": len(checks)})
        return {"status": note.status, "findings": []}
    chain = _band_chain(rule, note.gross_minor)
    SM.apply(session, note, "refer", rule_set_version=rule.ref, extra_after={"findings": [f["detail"] for f in findings], "chain": chain})
    workflow.start_approval(session, None, APPROVAL_TASK, object_type="DEBIT_NOTE", object_id=note.id, object_ref=note.number, chain=chain,
                            step_id=None, initiator_id=principal(session).user_id, exclude=[c for c in creators if c],
                            rule_set_version=rule.ref,
                            evidence={"invoice": invoice.number, "grossMinor": note.gross_minor, "findings": findings, "reason": note.reason})
    return {"status": note.status, "findings": findings, "chain": chain}


@workflow.on_task(APPROVAL_TASK)
def _variance_decided(session: Session, task: Task, outcome: str) -> None:
    note = session.get(DebitNote, task.object_id)
    if outcome == "APPROVED":
        SM.apply(session, note, "approve_variance", reason=task.comment, extra_after={"approvedBy": str(task.completed_by)})
        note.approved_by = task.completed_by
    else:
        SM.apply(session, note, "reject", reason=task.comment or "variance not approved")
        _after_reject(session, note, task.comment)


def _after_reject(session: Session, note: DebitNote, reason: Optional[str]) -> None:
    invoice = session.get(Invoice, note.invoice_id)
    audit.record(session, "INVOICE", invoice.id, "DEBIT_NOTE_REJECTED", object_ref=invoice.number, reason=reason,
                 after={"debitNote": note.number})
    for task in session.execute(select(Task).where(Task.kind == APPROVAL_TASK, Task.object_id == note.id, Task.status == "OPEN")).scalars():
        task.status = "CANCELLED"
    outbox.emit(session, "debit_note.rejected", "DEBIT_NOTE", note.id, note.number, {"invoice": invoice.number, "reason": reason})


def approve(session: Session, note: DebitNote) -> DebitNote:
    """Accounts payable approves a matched debit note for posting (four-eyes: not the user who raised it on the supplier's behalf)."""
    invoice = session.get(Invoice, note.invoice_id)
    p = principal(session)
    if note.created_by == p.user_id and "SUPPLIER_USER" not in p.roles:
        raise Problem(403, "FOUR_EYES", "The debit note was raised by you on the supplier's behalf; another approver must approve it",
                      rule_ref="SOD")
    sod.guard(session, "INVOICE_POST", {"supplier_id": note.supplier_id})
    SM.apply(session, note, "approve", rule_set_version=note.rule_set_version, extra_after={"invoice": invoice.number})
    note.approved_by = p.user_id
    return note


def reject(session: Session, note: DebitNote, reason: str) -> DebitNote:
    if len((reason or "").strip()) < 3:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for rejecting the debit note", rule_ref=KEY)
    SM.apply(session, note, "reject", reason=reason.strip())
    _after_reject(session, note, reason.strip())
    return note


# ---------------------------------------------------------------- posting to the ERP
def posting_key(session: Session, note: DebitNote, invoice: Invoice) -> str:
    from app.pic.services import payables
    return f"{invoice.posting_key or payables.posting_key(session, invoice)}|DN|{note.number}"


def post(session: Session, note: DebitNote) -> dict:
    """Post an approved debit note to the ERP as a vendor debit memo (exactly once: the key is the invoice's posting key + |DN| + number)."""
    invoice = session.get(Invoice, note.invoice_id)
    if note.status == "POSTED":
        return {"status": note.status, "erpDocument": note.erp_doc_no}
    if note.status != "APPROVED":
        raise illegal_transition("Debit note", note.number, note.status, "post")
    if invoice.status not in ("POSTED", "PAID"):
        raise Problem(409, "INVOICE_NOT_POSTED", f"{invoice.number} is {invoice.status}; post the invoice to the ERP before its debit note",
                      rule_ref=KEY)
    sod.guard(session, "INVOICE_POST", {"supplier_id": note.supplier_id})
    target = integration.target_system(session, invoice.company_code)
    from app.pic.platform import connectors
    connectors.require_mapped(target, MESSAGE_TYPE)
    from app.pic.services import finance_controls
    for day in dict.fromkeys((clock.today(), note.note_date)):
        finance_controls.assert_open(session, invoice.company_code, day, f"debit note {note.number} dated {note.note_date.isoformat()}")  # cut-off
    sod.record(session, "INVOICE_POST", {"supplier_id": note.supplier_id})
    supplier = session.get(Supplier, note.supplier_id)
    if note.posting_key is None:  # TDS on the additional taxable value is fixed once, at the first posting attempt (a retry sends the same payload)
        tds = finance_controls.compute_note_tds(session, invoice, note)
        if tds:
            note.tds_base_minor, note.tds_minor = tds["taxableMinor"], tds["tdsMinor"]
            audit.record(session, "DEBIT_NOTE", note.id, "TDS_DETERMINED", object_ref=note.number, rule_set_version="TDS",
                         after={"section": tds["section"], "ratePct": str(tds["ratePct"]), "taxableMinor": tds["taxableMinor"], "tdsMinor": tds["tdsMinor"]})
    note.posting_key = posting_key(session, note, invoice)
    note.retention_minor = _retention_of(session, note)
    message = integration.enqueue(
        session, target_system=target, message_type=MESSAGE_TYPE, idempotency_key=note.posting_key, object_type="DEBIT_NOTE",
        object_id=note.id, object_ref=note.number,
        payload={"debitNote": note.number, "supplierDebitNote": note.supplier_debit_note_no, "invoice": invoice.supplier_invoice_no,
                 "invoiceErp": invoice.erp_doc_no, "supplier": supplier.code, "companyCode": invoice.company_code, "grossMinor": note.gross_minor,
                 "netMinor": note.net_minor, "taxMinor": note.tax_minor, "retentionMinor": note.retention_minor, "fiscalYear": invoice.fiscal_year,
                 **({"tdsMinor": note.tds_minor, "tdsSection": invoice.tds_section} if note.tds_minor else {}),
                 "lines": [{k: v for k, v in e.items() if k in ("kind", "invoice_line", "charge", "netMinor", "taxMinor", "gstRate", "hsn")}
                           for e in note.lines]})
    integration.process(session, message)
    if message.status != "POSTED":
        return {"status": "POSTING", "integrationStatus": message.status, "attempts": message.attempts, "error": message.last_error}
    return {"status": note.status, "erpDocument": note.erp_doc_no}


def _retention_of(session: Session, note: DebitNote) -> int:
    """Retention withheld on the price corrections of orders that carry a retention percentage (construction / subcontract)."""
    invoice = session.get(Invoice, note.invoice_id)
    inv_lines = {l.line_no: l for l in session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)).scalars()}
    total = 0
    for entry in note.lines:
        if entry["kind"] != "PRICE":
            continue
        line = inv_lines.get(int(entry["invoice_line"]))
        po_line = session.get(PoLine, line.po_line_id) if line is not None and line.po_line_id else None
        po = session.get(PurchaseOrder, po_line.po_id) if po_line is not None else None
        if po is not None and po.retention_pct:
            total += pct_of(int(entry["netMinor"]), D(po.retention_pct))
    return total


@integration.on_posted(MESSAGE_TYPE)
def _debit_posted(session: Session, message) -> None:
    from app.pic.services import payables
    note = session.get(DebitNote, message.object_id)
    invoice = session.get(Invoice, note.invoice_id)
    SM.apply(session, note, "post", rule_set_version=note.rule_set_version, extra_after={"erpDocument": message.erp_doc_no})
    note.erp_doc_no = message.erp_doc_no
    by_requisition: dict[uuid.UUID, int] = {}
    inv_lines = {l.line_no: l for l in session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)).scalars()}
    for entry in note.lines:
        if entry["kind"] != "PRICE":
            continue
        line = inv_lines.get(int(entry["invoice_line"]))
        po_line = session.get(PoLine, line.po_line_id) if line is not None and line.po_line_id else None
        if po_line is None:
            continue
        po_line.invoiced_minor += int(entry["netMinor"])  # the corrected price is part of what was invoiced against the line
        if po_line.requisition_id and po_line.account_assignment_code:
            by_requisition[po_line.requisition_id] = by_requisition.get(po_line.requisition_id, 0) + int(entry["netMinor"])
    payables._consume_budget(session, by_requisition)
    if note.retention_minor:
        invoice.retention_minor = sum(payables.retention_by_po(session, invoice).values())  # now includes this note's price corrections
        audit.record(session, "INVOICE", invoice.id, "RETENTION_WITHHELD", object_ref=invoice.number,
                     after={"debitNote": note.number, "retentionMinor": note.retention_minor, "invoiceRetentionMinor": invoice.retention_minor})
    link(session, "DEBIT_NOTE", note.id, note.number, "ERP_DOCUMENT", note.id, message.erp_doc_no, "posted_as")
    audit.record(session, "INVOICE", invoice.id, "DEBIT_NOTE_POSTED", object_ref=invoice.number,
                 after={"debitNote": note.number, "erpDocument": message.erp_doc_no, "grossMinor": note.gross_minor})
    outbox.emit(session, "debit_note.posted", "DEBIT_NOTE", note.id, note.number,
                {"invoice": invoice.number, "erpDocument": message.erp_doc_no, "grossMinor": note.gross_minor})


# ---------------------------------------------------------------- views
def view(session: Session, note: DebitNote) -> dict:
    invoice = session.get(Invoice, note.invoice_id)
    tasks = session.execute(select(Task).where(Task.kind == APPROVAL_TASK, Task.object_id == note.id).order_by(Task.created_at)).scalars().all()
    return {"id": str(note.id), "number": note.number, "supplierDebitNoteNo": note.supplier_debit_note_no, "invoice": invoice.number,
            "invoiceId": str(invoice.id), "supplierId": str(note.supplier_id), "noteDate": note.note_date.isoformat(), "reason": note.reason,
            "status": note.status, "netMinor": note.net_minor, "taxMinor": note.tax_minor, "grossMinor": note.gross_minor,
            "retentionMinor": note.retention_minor, "lines": note.lines, "match": note.match_result, "erpDocument": note.erp_doc_no,
            "postingKey": note.posting_key, "paymentStatus": note.payment_status, "rule": note.rule_set_version,
            "approvals": [{"role": t.candidate_role, "status": t.status, "decision": t.decision, "comment": t.comment} for t in tasks],
            "rowVersion": note.row_version, "createdAt": note.created_at.isoformat() if note.created_at else None}


def by_ref(session: Session, ref: str, lock: bool = False) -> DebitNote:
    from app.pic.platform.http import unescape_ref
    ref = unescape_ref(str(ref))
    query = select(DebitNote)
    try:
        query = query.where(DebitNote.id == uuid.UUID(str(ref)))
    except ValueError:
        query = query.where(DebitNote.number == ref)
    if lock:
        query = query.with_for_update()
    note = session.execute(query).scalar_one_or_none()
    if note is None:
        raise not_found("Debit note", ref)
    return note
