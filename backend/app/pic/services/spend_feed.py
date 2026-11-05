"""What feeds the spend cube (M01, BP 7.4 "spend is de-duplicated across PO and invoice using document lineage before aggregation").

Posted spend comes from ONE document family: the supplier invoice and the notes that correct it. Purchase orders and goods receipts never
become spend lines (an open order is a commitment, see ``spend_cube.commitments``), so an order and its invoice cannot be counted twice; the
lineage is explicit on the line (``invoice_line_id`` -> ``po_line_id`` / ``po_ref``) and in ``document_link``.

* ``invoice.posted``        one INVOICE line per invoice line, gross of credit notes (credit notes are their own lines).
* ``credit_note.received``  one negative CREDIT_NOTE line per credited invoice line, in the period of the note date, with the attributes
                            (category, supplier, plant, contract flag, FX rate) of the invoice line it reduces: the credit nets the invoice
                            exactly in group currency, and it does not rewrite a closed period.
                            A quantity credit is ``qty x invoice price``; a price (value) credit is ``qty x credit per unit`` - it does NOT
                            reduce the quantity.
* ``debit_note.posted``     one positive DEBIT_NOTE line per debit-note line (price correction on an invoice line, or an additional charge).

Every consumer is idempotent: a line exists once per (invoice line, document type, document reference). All amounts are net of GST
(recoverable tax is not spend). A cancelled or rejected invoice never reaches ``invoice.posted``, so it is never a line.
"""
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import CreditNote, DebitNote, Invoice, InvoiceLine, Material, PoLine, PriceValidity, PurchaseOrder, SpendLine, Supplier
from app.pic.platform import outbox
from app.pic.platform.errors import Problem
from app.pic.platform.money import D, line_amount
from app.pic.services import spend, spend_cube


# ---------------------------------------------------------------- helpers
def _last_price_paid(session: Session, po_line: PoLine, po: PurchaseOrder) -> Optional[int]:
    """Unit price of the material on the latest earlier PO line (the price actually paid last time)."""
    if po_line.material_id is None:
        return None
    return session.execute(
        select(PoLine.unit_price_minor).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(
            PoLine.material_id == po_line.material_id, PoLine.id != po_line.id, PurchaseOrder.created_at < po.created_at,
            PurchaseOrder.status != "CANCELLED").order_by(PurchaseOrder.created_at.desc()).limit(1)).scalar()


def _group(amount: int, rate: Optional[Decimal]) -> Optional[int]:
    return int((Decimal(amount) * rate).quantize(Decimal("1"), ROUND_HALF_UP)) if rate is not None else None


def _existing(session: Session, line_ids: list, document_type: str, document_ref: str = "") -> dict:
    if not line_ids:
        return {}
    return {x.invoice_line_id: x for x in session.execute(select(SpendLine).where(
        SpendLine.invoice_line_id.in_(line_ids), SpendLine.document_type == document_type, SpendLine.document_ref == document_ref)).scalars()}


def _originals(session: Session, invoice: Invoice) -> dict:
    """The INVOICE spend line of each invoice line number (what a note corrects)."""
    rows = session.execute(select(InvoiceLine.line_no, SpendLine).join(SpendLine, SpendLine.invoice_line_id == InvoiceLine.id).where(
        InvoiceLine.invoice_id == invoice.id, SpendLine.document_type == "INVOICE")).all()
    return {n: sl for n, sl in rows}


def _copy_of(original: SpendLine, *, document_type: str, document_ref: str, document_date: date, amount: int, description: str,
             variance: int = 0, variance_last: int = 0, flags: bool = True) -> SpendLine:
    """A note line: same business attributes as the invoice line it corrects (so the credit nets exactly), its own period and amount."""
    rate = original.fx_rate
    return SpendLine(
        tenant_id=original.tenant_id, invoice_line_id=original.invoice_line_id, invoice_ref=original.invoice_ref, po_ref=original.po_ref,
        supplier_id=original.supplier_id, category=original.category, material_group=original.material_group, plant=original.plant,
        company_code=original.company_code, cost_object=original.cost_object, cost_object_type=original.cost_object_type,
        period=document_date.strftime("%Y-%m"), amount_minor=amount, currency=original.currency, contracted=original.contracted,
        addressable=original.addressable, maverick_flags=list(original.maverick_flags or []) if flags else [],
        classification_confidence=original.classification_confidence, description=(description or original.description or "")[:300],
        po_line_id=original.po_line_id, price_variance_minor=variance, price_variance_last_minor=variance_last, source=original.source,
        source_system=original.source_system, fx_rate=rate, fx_date=original.fx_date, document_type=document_type, document_ref=document_ref,
        document_date=document_date, buyer_id=original.buyer_id, created_by=original.created_by,
        amount_group_minor=_group(amount, rate))


# ---------------------------------------------------------------- invoices
def feed_invoice(session: Session, invoice: Invoice) -> int:
    """Spend lines for a posted invoice (idempotent), then the credit and debit notes already recorded against it."""
    lines = session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id).order_by(InvoiceLine.line_no)).scalars().all()
    have = _existing(session, [l.id for l in lines], "INVOICE")
    supplier = session.get(Supplier, invoice.supplier_id)
    created = 0
    for line in lines:
        if line.id in have:
            continue
        po_line = session.get(PoLine, line.po_line_id) if line.po_line_id else None
        po = session.get(PurchaseOrder, po_line.po_id) if po_line else None
        material = session.get(Material, po_line.material_id) if po_line is not None and po_line.material_id else None
        qty = line.qty
        reference = None
        if po_line is not None and po_line.price_validity_id:
            reference = session.get(PriceValidity, po_line.price_validity_id).unit_price_minor
        elif material and material.standard_price_minor:
            reference = material.standard_price_minor
        variance = line_amount(qty, line.unit_price_minor - reference) if reference and line.unit_price_minor > reference else 0
        last_price = _last_price_paid(session, po_line, po) if po_line is not None else None
        variance_last = line_amount(qty, line.unit_price_minor - last_price) if last_price and line.unit_price_minor > last_price else 0
        amount = line_amount(qty, line.unit_price_minor)
        fx = spend_cube.rate_for_line(session, invoice.currency, invoice.invoice_date)
        category = material.category if material else (po_line.material_group if po_line is not None else "UNCLASSIFIED")
        spend_line = SpendLine(
            tenant_id=invoice.tenant_id, invoice_line_id=line.id, invoice_ref=invoice.number, po_ref=po.number if po else None,
            supplier_id=invoice.supplier_id, category=category, material_group=po_line.material_group if po_line is not None else "UNMAPPED",
            plant=po_line.plant if po_line is not None else _default_plant(session, invoice.company_code), company_code=invoice.company_code,
            cost_object=po_line.account_assignment_code if po_line is not None else None,
            period=invoice.invoice_date.strftime("%Y-%m"), amount_minor=amount, contracted=bool(po_line is not None and po_line.contract_line_id),
            addressable=spend.addressable_for(session, supplier, category), maverick_flags=[],
            classification_confidence=Decimal("1.000") if material else Decimal("0.000"), created_by=invoice.created_by,
            description=(po_line.description if po_line is not None else line.description), po_line_id=po_line.id if po_line is not None else None,
            price_variance_minor=variance, source="PLATFORM", currency=invoice.currency, source_system="PIC",
            cost_object_type=po_line.account_assignment_type if po_line is not None else None, fx_rate=fx[0] if fx else None,
            fx_date=fx[1] if fx else None, amount_group_minor=_group(amount, fx[0]) if fx else None, price_variance_last_minor=variance_last,
            document_type="INVOICE", document_ref="", document_date=invoice.invoice_date, buyer_id=po.created_by if po else None)
        session.add(spend_line)
        spend.after_spend_line(session, spend_line)
        created += 1
    session.flush()
    for note in session.execute(select(CreditNote).where(CreditNote.invoice_id == invoice.id).order_by(CreditNote.note_date)).scalars():
        created += feed_credit_note(session, note)
    for note in session.execute(select(DebitNote).where(DebitNote.invoice_id == invoice.id, DebitNote.status == "POSTED")).scalars():
        created += feed_debit_note(session, note)
    return created


def _default_plant(session: Session, company_code: str) -> str:
    from app.pic.models import Plant
    return session.execute(select(Plant.code).where(Plant.company_code == company_code).order_by(Plant.code)).scalars().first() or "NA"


# ---------------------------------------------------------------- credit notes
def feed_credit_note(session: Session, note: CreditNote) -> int:
    """Negative lines for a supplier credit note (idempotent). The invoice must already be in the cube: when it is not, nothing is
    written and ``feed_invoice`` adds the note's lines once the invoice is posted."""
    invoice = session.get(Invoice, note.invoice_id)
    originals = _originals(session, invoice)
    if not originals:
        return 0
    inv_lines = {l.line_no: l for l in session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)).scalars()}
    created = 0
    for entry in note.lines or []:
        line_no = int(entry["invoice_line"])
        original, inv_line = originals.get(line_no), inv_lines.get(line_no)
        if original is None or inv_line is None:
            continue
        if note.number in {x.document_ref for x in session.execute(select(SpendLine).where(
                SpendLine.invoice_line_id == inv_line.id, SpendLine.document_type == "CREDIT_NOTE")).scalars()}:
            continue
        qty = D(entry["qty"])
        unit_credit = entry.get("unitCreditMinor")
        if unit_credit is None:   # quantity credit: qty x the invoice price
            amount = line_amount(qty, inv_line.unit_price_minor)
            share = (qty / inv_line.qty) if inv_line.qty else Decimal(0)
            variance = -int((Decimal(original.price_variance_minor or 0) * share).quantize(Decimal("1"), ROUND_HALF_UP))
            variance_last = -int((Decimal(original.price_variance_last_minor or 0) * share).quantize(Decimal("1"), ROUND_HALF_UP))
        else:                     # price credit: qty x the credit per unit, the quantity stands
            amount = line_amount(qty, int(unit_credit))
            variance = -min(amount, int(original.price_variance_minor or 0))
            variance_last = -min(amount, int(original.price_variance_last_minor or 0))
        session.add(_copy_of(original, document_type="CREDIT_NOTE", document_ref=note.number, document_date=note.note_date, amount=-amount,
                             description=f"Credit note {note.number}: {original.description or ''}", variance=variance, variance_last=variance_last))
        created += 1
    session.flush()
    return created


# ---------------------------------------------------------------- debit notes
def feed_debit_note(session: Session, note: DebitNote) -> int:
    """Positive lines for a posted supplier debit note (price correction on an invoice line, or an additional charge)."""
    if note.status != "POSTED":
        return 0
    invoice = session.get(Invoice, note.invoice_id)
    originals = _originals(session, invoice)
    if not originals:
        return 0
    inv_lines = {l.line_no: l for l in session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)).scalars()}
    biggest = max(originals.values(), key=lambda l: (abs(l.amount_minor), l.invoice_line_id))
    done = {x.document_ref + "|" + str(x.invoice_line_id) for x in session.execute(select(SpendLine).where(
        SpendLine.invoice_ref == invoice.number, SpendLine.document_type == "DEBIT_NOTE", SpendLine.document_ref.like(f"{note.number}%"))).scalars()}
    created = 0
    for position, entry in enumerate(note.lines or [], start=1):
        net = int(entry.get("netMinor") or 0)
        if net <= 0:
            continue
        if entry.get("kind") == "PRICE" and entry.get("invoice_line") is not None:
            original, inv_line = originals.get(int(entry["invoice_line"])), inv_lines.get(int(entry["invoice_line"]))
            if original is None:
                continue
            ref = f"{note.number}#{position}"
            key_line = inv_line.id
            description = f"Debit note {note.number}: price correction on {original.description or ''}"
        else:  # an additional charge (freight, handling): it follows the invoice's main line until a steward classifies it
            original = biggest
            key_line = original.invoice_line_id
            ref = f"{note.number}#{position}"
            description = f"Debit note {note.number}: {entry.get('description') or 'additional charge'}"
        if ref + "|" + str(key_line) in done:
            continue
        copy = _copy_of(original, document_type="DEBIT_NOTE", document_ref=ref, document_date=note.note_date, amount=net, description=description,
                        flags=False)
        if entry.get("kind") != "PRICE":
            copy.classification_confidence = Decimal("0.000")   # classified from its description by the Spend Classification Agent
            copy.contracted = False
        session.add(copy)
        session.flush()
        if entry.get("kind") != "PRICE":
            spend.after_spend_line(session, copy)
        created += 1
    session.flush()
    return created


# ---------------------------------------------------------------- consumers
@outbox.consumer("invoice.posted", "spend-cube")
def _on_invoice_posted(session: Session, event) -> None:
    invoice = session.get(Invoice, uuid.UUID(event.payload["invoiceId"]))
    if invoice is not None:
        feed_invoice(session, invoice)


@outbox.consumer("credit_note.received", "spend-cube-credit")
def _on_credit_note(session: Session, event) -> None:
    note = session.get(CreditNote, uuid.UUID(event.payload["creditNoteId"]))
    if note is not None:
        feed_credit_note(session, note)


@outbox.consumer("debit_note.posted", "spend-cube-debit")
def _on_debit_note(session: Session, event) -> None:
    note = session.get(DebitNote, event.object_id)
    if note is not None:
        feed_debit_note(session, note)


def backfill_notes(session: Session) -> dict:
    """Spend lines for the credit notes and posted debit notes recorded before the cube knew them (idempotent). Notes against invoices that are
    not in the cube (an invoice migrated from the ERP, whose spend is in the ERP history) are skipped, never double counted."""
    credit = debit = 0
    for note in session.execute(select(CreditNote).order_by(CreditNote.note_date, CreditNote.number)).scalars():
        credit += feed_credit_note(session, note)
    for note in session.execute(select(DebitNote).where(DebitNote.status == "POSTED").order_by(DebitNote.note_date, DebitNote.number)).scalars():
        debit += feed_debit_note(session, note)
    return {"creditNoteLines": credit, "debitNoteLines": debit}
