"""AXN part of the finance_ops pack: non-signature finance data only, under 60 documents. No existing AXN document, number, amount or status changes.

  FX series          the KAC series (same weekdays, same MOCK levels, anchored on the FBIL values of 28 October 2026)
  periods            April to October 2026 closed (the months before the signature case, which starts on 14 November 2026); the close runs on 5 July 2027
                     so the GR/IR snapshots show what was open when they were written (a late back-fill close)
  tax master data   PAN is on file; TDS section / MSME class / Udyam only on the ERP-loaded vendors (V-*) and the registered SUP-* vendors, never on a
                     supplier of the signature case or of another pack
  certificate        one s.197 certificate on a TDS vendor
  documents          up to three new invoices on open orders of non-signature suppliers, goods received 6 July 2027: one credit note and one debit note
                     on each of two of them, one payment returned by the bank and paid again in the next run. Every new invoice ends PAID, so no
                     unpaid invoice is added to the tenant; the existing AXN payments and invoices are not touched (no bank statement is imported: it
                     would change the bank status of signature-case payments).
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import CreditNote, DebitNote, GoodsReceipt, Invoice, InvoiceLine, Payment, PurchaseOrder, Supplier, SupplierCategoryStatus
from app.pic.platform import clock, rules
from app.pic.platform.errors import Problem
from app.pic.seed.datasets import finance_ops as F
from app.pic.seed.datasets.finance_ops import Ctx, ist
from app.pic.seed.datasets.finance_ops_docs import find_invoice, invoice_lines
from app.pic.seed.datasets.finance_ops_kac import iso
from app.pic.tools import finance_mock as mock

SIGNATURE_SUPPLIERS = {"TF001", "KD002", "HTS004"}     # suppliers of the signature case
PERIODS = [f"2026-{m:02d}" for m in range(4, 11)]
CLOSE_DAY = date(2027, 7, 5)
GR_DAY, CAPTURE_DAY, POST_DAY = date(2027, 7, 6), date(2027, 7, 7), date(2027, 7, 8)
NOTE_DAY, RUN_A, RETURN_DAY, RUN_B, CREDIT_DAY = date(2027, 7, 9), date(2027, 7, 13), date(2027, 7, 14), date(2027, 7, 15), date(2027, 7, 16)
DEBTOR_VERSION = "2027.2-CC1000-MOCK"


def debtor_rule(ctx: Ctx) -> bool:
    """AXN may have no debtor account yet (module_cases publishes one for the same company code): publish a MOCK one only when none is configured."""
    with tenant_tx(ctx.tenant_id) as s:
        try:
            body = rules.resolve(s, "PAYMENT-FILE", on=RUN_A, company_code=ctx.spec["company"]).body
        except Problem:
            body = {}
        if body.get("debtorName"):
            return False
        F.publish_rule(s, ctx.tenant_id, "PAYMENT-FILE", DEBTOR_VERSION, date(2027, 7, 1), {"format": "ISO20022_PAIN001", **F.DEBTOR["A"]},
                       "MOCK debtor account for the AXN demo tenant (finance_ops): not a real account.", ctx.spec["company"])
        return True


def run(ctx: Ctx) -> dict:
    started = time.time()
    from app.pic.services import bank_files, debit_notes, finance_controls, payables
    notes, counts = [], {}
    if F.stage_done(ctx.tenant_id, "axn-config") is None:
        fx = F.load_fx(ctx)
        counts.update(fx)
        attributes = assign_attributes(ctx)
        counts.update({f"attr:{k}": v for k, v in attributes.items() if isinstance(v, int)})
        F.stage_mark(ctx.tenant_id, "axn-config", {**fx, **attributes})
    # periods before the signature case
    for period in PERIODS:
        with ctx.act("finance.controller", ist(CLOSE_DAY, 10)) as s:
            from app.pic.models import PostingPeriod
            row = s.execute(select(PostingPeriod).where(PostingPeriod.company_code == ctx.spec["company"], PostingPeriod.period == period)).scalar_one_or_none()
            if row is None or row.status != "CLOSED":
                finance_controls.close_period(s, ctx.spec["company"], period, f"{F.LABEL}: months before the signature case closed")
                counts["periodsClosed"] = counts.get("periodsClosed", 0) + 1
    # one s.197 certificate
    with ctx.act("finance.controller", ist(CLOSE_DAY, 11)) as s:
        vendor = s.execute(select(Supplier).where(Supplier.tds_section.is_not(None), Supplier.code.notin_(SIGNATURE_SUPPLIERS)).order_by(Supplier.code)).scalars().first()
        if vendor is not None:
            from app.pic.models import TdsCertificate
            if not s.execute(select(TdsCertificate.id).where(TdsCertificate.certificate_no == "LDC-MOCK-AXN-0001")).first():
                finance_controls.add_certificate(s, vendor, certificate_no="LDC-MOCK-AXN-0001", rate_pct=Decimal("1.0"), valid_from=date(2027, 4, 1), valid_to=date(2028, 3, 31),
                                                 section=vendor.tds_section, note=f"{F.LABEL}: lower deduction 1 % on the section")
                counts["certificates"] = 1
    # documents
    from app.pic.seed.datasets import finance_ops_run
    masters = finance_ops_run.import_masters(ctx, finance_ops_run.AXN_ORDERS, date(2027, 7, 1), "45019")
    counts.update(documents(ctx, masters))
    clock.set_pinned(None)
    notes.append(f"AXN ({F.LABEL}): {counts}; duration {time.time() - started:.0f} s")
    return {"notes": notes, "counts": counts, "label": F.LABEL}


def assign_attributes(ctx: Ctx) -> dict:
    out = {"tds": 0, "msme": 0}
    reason = f"{F.LABEL}: supplier tax master filled by rule; the client's tax team confirms or replaces it"
    with tenant_tx(ctx.tenant_id) as s:
        categories: dict = {}
        for sid, category in s.execute(select(SupplierCategoryStatus.supplier_id, SupplierCategoryStatus.category)):
            categories.setdefault(sid, set()).add(category)
        for x in s.execute(select(Supplier).order_by(Supplier.code)).scalars():
            if not (x.code.startswith("V-") or x.code.startswith("SUP-")) or x.code == "V-219001":
                continue
            cats = categories.get(x.id, set()) | {x.legal_name}
            section = None
            text = " ".join(cats).lower()
            if any(w in text for w in ("advisory", "infotech", "services", "facility")):
                section = "194J-PRO" if "advisory" in text else "194C-OTH"
            elif any(w in text for w in ("roadlines", "machine tools", "cnc")):
                section = "194C-OTH"
            msme = None
            udyam = None
            if mock.unit("axn-msme", x.code) < 0.2:
                msme, udyam = ("MICRO" if mock.unit("axn-msme-class", x.code) < 0.5 else "SMALL"), F.udyam_for(x)
            if F.set_finance(s, x, msme_class=msme, udyam=udyam, tds_section=section, reason=reason):
                out["tds"] += 1 if section else 0
                out["msme"] += 1 if msme else 0
    return out


def documents(ctx: Ctx, chosen: list[dict]) -> dict:
    from app.pic.services import bank_files, debit_notes, payables, receiving
    out = {}
    scns = []
    for i, p in enumerate(chosen):
        scns.append({**p, "id": f"A{i + 1:02d}", "inv_no": f"{F.PREFIX}/{p['supplier']}/A{i + 1:03d}", "channel": "PDF_OCR", "gr": iso(GR_DAY), "inv": iso(CAPTURE_DAY)})
    debtor_rule(ctx)
    for scn in scns:                                                       # goods receipt, invoice, approval, posting
        receiver = ctx.spec["receivers"][scn["plant"]]
        note = f"DN-{F.PREFIX}-{scn['id']}"
        with ctx.act(receiver, ist(GR_DAY, 10)) as s:
            if not s.execute(select(GoodsReceipt.id).where(GoodsReceipt.delivery_note == note)).first():
                po = s.execute(select(PurchaseOrder).where(PurchaseOrder.number == scn["po"])).scalar_one()
                receiving.post_gr(s, po, lines=[{"line": l["line"], "qty": l["qty"]} for l in scn["lines"]], delivery_note=note, posting_date=GR_DAY)
                out["goodsReceipts"] = out.get("goodsReceipts", 0) + 1
        with ctx.act("ap.clerk", ist(CAPTURE_DAY, 11)) as s:
            if find_invoice(s, scn["supplier"], scn["inv_no"]) is None:
                data = invoice_lines(scn)
                payables.capture(s, supplier=scn["supplier"], supplier_invoice_no=scn["inv_no"], invoice_date=CAPTURE_DAY, channel="PDF_OCR",
                                 company_code=ctx.spec["company"], lines=[{k: v for k, v in l.items() if not k.startswith("_")} for l in data])
                out["invoicesCaptured"] = out.get("invoicesCaptured", 0) + 1
        with ctx.act("finance.controller", ist(POST_DAY, 10)) as s:
            inv = find_invoice(s, scn["supplier"], scn["inv_no"])
            if inv.status == "MATCHED":
                payables.approve(s, inv)
        with ctx.act("ap.clerk", ist(POST_DAY, 11)) as s:
            inv = find_invoice(s, scn["supplier"], scn["inv_no"])
            if inv.status == "APPROVED":
                payables.post(s, inv, payables.posting_key(s, inv))
                out["invoicesPosted"] = out.get("invoicesPosted", 0) + 1
    # one credit note and one debit note on each of the first two invoices
    for k, scn in enumerate(scns[:2]):
        cn_no = f"CN-{F.PREFIX}-{scn['id']}"
        with ctx.act("ap.clerk", ist(NOTE_DAY, 10)) as s:
            inv = find_invoice(s, scn["supplier"], scn["inv_no"])
            if s.execute(select(CreditNote.id).where(CreditNote.invoice_id == inv.id, CreditNote.supplier_credit_note_no == cn_no)).first() is None:
                line = s.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id).order_by(InvoiceLine.line_no)).scalars().first()
                qty = min(line.qty, max(Decimal(1), (line.qty * Decimal("0.04")).quantize(Decimal(1))))
                payables.submit_credit_note(s, inv, supplier_credit_note_no=cn_no, note_date=NOTE_DAY, lines=[{"invoice_line": line.line_no, "qty": str(qty)}],
                                            reason=f"MOCK sample: {'quality' if k == 0 else 'quantity'} credit note")
                out["creditNotes"] = out.get("creditNotes", 0) + 1
        dn_no = f"DN-{F.PREFIX}-{scn['id']}"
        with ctx.act("ap.clerk", ist(NOTE_DAY, 11)) as s:
            inv = find_invoice(s, scn["supplier"], scn["inv_no"])
            if s.execute(select(DebitNote.id).where(DebitNote.supplier_debit_note_no == dn_no, DebitNote.supplier_id == inv.supplier_id)).first() is None:
                amount = max(150_000, int(Decimal(inv.net_minor) * Decimal("0.02")))
                debit_notes.submit(s, inv, supplier_debit_note_no=dn_no, note_date=NOTE_DAY, reason="MOCK sample: freight recovery charge",
                                   lines=[{"kind": "CHARGE", "charge": "FREIGHT", "description": "Freight recovery (MOCK sample)", "amount_minor": amount, "gst_rate": "18", "hsn": "996511"}])
                out["debitNotes"] = out.get("debitNotes", 0) + 1
        with tenant_tx(ctx.tenant_id) as s:
            note = s.execute(select(DebitNote).where(DebitNote.supplier_debit_note_no == dn_no)).scalar_one_or_none()
            note_id, status = (note.id, note.status) if note else (None, None)
        if note_id and status == "PENDING_APPROVAL":
            ctx.sc.approve_all(note_id, ist(NOTE_DAY + timedelta(days=1), 10), "Charge accepted by the buyer (MOCK sample)")
        with ctx.act("finance.controller", ist(NOTE_DAY + timedelta(days=1), 12)) as s:
            note = s.execute(select(DebitNote).where(DebitNote.supplier_debit_note_no == dn_no)).scalar_one_or_none()
            if note is not None and note.status == "MATCHED":
                debit_notes.approve(s, note)
        with ctx.act("finance.controller", ist(NOTE_DAY + timedelta(days=1), 14)) as s:
            note = s.execute(select(DebitNote).where(DebitNote.supplier_debit_note_no == dn_no)).scalar_one_or_none()
            if note is not None and note.status == "APPROVED":
                debit_notes.post(s, note)
                out["debitNotesPosted"] = out.get("debitNotesPosted", 0) + 1
    numbers = [s_["inv_no"] for s_ in scns]
    # run A pays the three invoices; the bank returns the third; run B pays it again
    for key, day, selection in (("A", RUN_A, numbers), ("B", RUN_B, numbers[2:])):
        marker = f"axn-run:{key}"
        if F.stage_done(ctx.tenant_id, marker) is not None:
            continue
        with ctx.act("finance.controller2", ist(day, 10)) as s:
            result = payables.payment_run(s, day, include_not_due=True, invoice_numbers=selection)
            pf = bank_files.generate(s, result["run"], "ISO20022_PAIN001")
            bank_files.set_status(s, pf, "SENT")
            pf_no, run_ref = pf.number, result["run"]
        out["payments"] = out.get("payments", 0) + len(result["paid"])
        F.stage_mark(ctx.tenant_id, marker, {"run": run_ref, "file": pf_no, "paid": [p["payment"] for p in result["paid"]]})
        with ctx.act("finance.controller2", ist(RETURN_DAY if key == "A" else CREDIT_DAY, 11)) as s:
            pays = list(s.execute(select(Payment).join(Invoice, Invoice.id == Payment.invoice_id).where(Payment.run_ref == run_ref, Payment.status == "COMPLETED")
                                  .order_by(Payment.number)).scalars())
            items = [{"payment": p.number, "status": "CREDITED", "utr": mock.utr("AXIS", RETURN_DAY, n)} for n, p in enumerate(pays, start=1)]
            if key == "A" and items:
                items[-1] = {"payment": pays[-1].number, "status": "RETURNED", "reason": "AC04 Beneficiary account closed (MOCK sample)"}
            bank_files.record_bank_results(s, bank_files.by_number(s, pf_no, lock=True), items)
            if key == "A":
                out["paymentsReturned"] = 1
    return out
