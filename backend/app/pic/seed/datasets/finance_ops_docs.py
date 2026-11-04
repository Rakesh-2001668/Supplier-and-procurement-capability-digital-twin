"""Document events of the finance_ops pack for KAC: goods receipts, supplier invoices, exception resolutions, credit notes (see finance_ops_kac for the plan)."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import CreditNote, GoodsReceipt, Invoice, InvoiceException, InvoiceLine, PoLine, PurchaseOrder, Supplier
from app.pic.platform import clock, crypto
from app.pic.platform.money import line_amount, tax_amount
from app.pic.seed.datasets import finance_ops as F
from app.pic.seed.datasets.finance_ops import Ctx, ist, rupees
from app.pic.seed.datasets.finance_ops_kac import clamp, day_of, finish_dates
from app.pic.tools import finance_mock as mock


RECEIVING_SLOC = "0002"


def _sup_id(scn):
    return uuid.UUID(scn["supplier_id"])


def find_invoice(s, supplier_code: str, number: str) -> Optional[Invoice]:
    return s.execute(select(Invoice).join(Supplier, Supplier.id == Invoice.supplier_id).where(
        Supplier.code == supplier_code, Invoice.supplier_invoice_no == number)).scalar_one_or_none()


def invoice_lines(scn: dict, *, price_pct: str = "0", qty_pct: str = "0", gst: Optional[str] = None) -> list[dict]:
    out = []
    for l in scn["lines"]:
        price = int((Decimal(l["price"]) * (1 + Decimal(price_pct) / 100)).quantize(Decimal(1), ROUND_HALF_UP))
        qty = (Decimal(l["qty"]) * (1 + Decimal(qty_pct) / 100)).quantize(Decimal("0.001"), ROUND_HALF_UP)
        out.append({"po": scn["po"], "po_line": l["line"], "qty": str(qty.normalize() if qty == qty.to_integral() else qty), "unit_price": rupees(price),
                    "gst_rate": gst or l["gst"], "hsn": l["hsn"], "_price": price, "_qty": qty, "_gst": Decimal(gst or l["gst"])})
    return out


def gross_of(lines: list[dict]) -> int:
    total = 0
    for l in lines:
        net = line_amount(l["_qty"], l["_price"])
        total += net + tax_amount(net, l["_gst"])
    return total


def approver_for(gross: int) -> str:
    if gross > 300 * F.L:      # above the mock controllers' limit: the unrestricted legacy controller (finance.controller2)
        return "finance.controller2"
    return F.AP_APPROVE if gross <= 10 * F.L else F.FC_APPROVE


def ev_gr(ctx: Ctx, scn: dict) -> None:
    from app.pic.services import receiving
    day = day_of(scn["gr"])
    receiver = ctx.spec["receivers"][scn["lines"][0]["plant"]]
    note = f"DN-{F.PREFIX}-{scn['id']}"
    with ctx.act(receiver, ist(day, 10)) as s:
        if s.execute(select(GoodsReceipt.id).where(GoodsReceipt.delivery_note == note)).first():
            return
        po = s.execute(select(PurchaseOrder).where(PurchaseOrder.number == scn["po"])).scalar_one()
        # goods go into storage location 0002 (receiving area): the opening-stock balances in 0001 and the inventory datasets' ledger stay as they are
        receiving.post_gr(s, po, lines=[{"line": l["line"], "qty": l["qty"], "storage_location": RECEIVING_SLOC} for l in scn["lines"]], delivery_note=note, posting_date=day)
    ctx.count("goodsReceipts")


def ev_capture(ctx: Ctx, scn: dict, *, price_pct="0", qty_pct="0", gst=None, mode: str = "valid", number: Optional[str] = None, lines: Optional[list] = None,
               hour: int = 11) -> None:
    from app.pic.models import CompanyCode
    from app.pic.services import payables
    number = number or scn["inv_no"]
    day = day_of(scn["inv"])
    with ctx.act(F.AP_CAPTURE, ist(day, hour)) as s:
        if find_invoice(s, scn["supplier"], number) is not None:
            return
        data = lines or invoice_lines(scn, price_pct=price_pct, qty_pct=qty_pct, gst=gst)
        gross = gross_of(data)
        irn = qr = None
        if scn["channel"] == "E_INVOICE":
            sup = s.get(Supplier, _sup_id(scn))
            gstin = crypto.decrypt(sup.tenant_id, "gstin", sup.gstin_enc)
            buyer = s.execute(select(CompanyCode.gstin).where(CompanyCode.code == ctx.spec["company"])).scalar_one()
            irn = mock.irn_of(gstin, clock.fiscal_year(day), "INV", number + ("-X" if mode == "bad_irn" else ""))
            total = gross + (500_000 if mode == "bad_qr" else 0)
            qr = mock.signed_qr(irn=irn, seller_gstin=gstin, buyer_gstin=buyer, doc_no=number, doc_date=day, total_minor=total, hsn=data[0]["hsn"], items=len(data))
        payables.capture(s, supplier=scn["supplier"], supplier_invoice_no=number, invoice_date=day, channel=scn["channel"], irn=irn, signed_qr=qr,
                         company_code=ctx.spec["company"], lines=[{k: v for k, v in l.items() if not k.startswith("_")} for l in data])
    ctx.count("invoicesCaptured")


def _gross(ctx: Ctx, supplier: str, number: str) -> int:
    with tenant_tx(ctx.tenant_id) as s:
        inv = find_invoice(s, supplier, number)
        if inv is None:
            raise F.Skip(f"invoice {number} of {supplier} does not exist")
        # Approval limits compare in the company currency, and the rate of a foreign invoice is fixed only when it is first posted: a
        # foreign-currency invoice therefore goes to the unrestricted legacy controller (no value limit).
        if (getattr(inv, "currency", None) or "INR") != "INR":
            return 10 ** 13
        return int(inv.gross_minor)


def ev_approve_post(ctx: Ctx, scn: dict, day: date, *, approve=True, post=True, number: Optional[str] = None) -> None:
    from app.pic.services import payables
    number = number or scn["inv_no"]
    gross = _gross(ctx, scn["supplier"], number)
    if approve:
        with ctx.act(approver_for(gross), ist(day, 15)) as s:
            inv = find_invoice(s, scn["supplier"], number)
            if inv.status == "MATCHED":
                payables.approve(s, inv)
                ctx.count("invoicesApproved")
    if post:
        with ctx.act(F.AP_POST if gross <= 50 * F.L else ("finance.controller2" if gross > 300 * F.L else F.FC_APPROVE), ist(day, 16)) as s:
            inv = find_invoice(s, scn["supplier"], number)
            if inv.status == "APPROVED":
                payables.post(s, inv, payables.posting_key(s, inv))
                ctx.count("invoicesPosted")


def open_exceptions(s, inv: Invoice, types: Optional[tuple] = None) -> list[InvoiceException]:
    q = select(InvoiceException).where(InvoiceException.invoice_id == inv.id, InvoiceException.status == "OPEN")
    if types:
        q = q.where(InvoiceException.type.in_(types))
    return list(s.execute(q.order_by(InvoiceException.created_at)).scalars())


def ev_credit_and_resolve(ctx: Ctx, scn: dict, day: date, kind: str) -> None:
    """Supplier credit note for the price difference (PRICE) or the excess quantity (QTY), then the exceptions are resolved with it."""
    from app.pic.services import payables
    note_no = f"CN-{F.PREFIX}-{scn['id']}"
    with ctx.act(F.AP_APPROVE, ist(day, 14)) as s:
        inv = find_invoice(s, scn["supplier"], scn["inv_no"])
        if inv.status != "EXCEPTION":
            return
        if s.execute(select(CreditNote.id).where(CreditNote.invoice_id == inv.id, CreditNote.supplier_credit_note_no == note_no)).first() is None:
            ilines = {l.line_no: l for l in s.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id)).scalars()}
            entries = []
            for l in sorted(ilines.values(), key=lambda x: x.line_no):
                po_line = s.get(PoLine, l.po_line_id)
                if kind == "PRICE":
                    entries.append({"invoice_line": l.line_no, "qty": str(l.qty), "unit_credit_minor": l.unit_price_minor - po_line.unit_price_minor})
                else:
                    excess = l.qty - (po_line.received_qty - po_line.invoiced_qty)
                    if excess > 0:
                        entries.append({"invoice_line": l.line_no, "qty": str(excess.normalize() if excess == excess.to_integral() else excess)})
            what = "price difference against the order price" if kind == "PRICE" else "quantity billed above the goods received"
            payables.submit_credit_note(s, inv, supplier_credit_note_no=note_no, note_date=day, reason=f"MOCK sample: credit note {note_no} for the {what}",
                                        lines=entries)
            ctx.count("creditNotes")
        for exc in open_exceptions(s, inv, ("PRICE",) if kind == "PRICE" else ("QUANTITY",)):
            payables.resolve_exception(s, inv, exc.id, "CREDIT_NOTE_RECEIVED", f"Resolved with credit note {note_no} (MOCK sample)", note_no)
            ctx.count("exceptionsResolved")


def ev_resolve(ctx: Ctx, scn: dict, day: date, resolution: str, types: tuple, note: str, hour: int = 14, number: Optional[str] = None) -> None:
    from app.pic.services import payables
    number = number or scn["inv_no"]
    with ctx.act(F.AP_APPROVE, ist(day, hour)) as s:
        inv = find_invoice(s, scn["supplier"], number)
        for exc in open_exceptions(s, inv, types):
            if exc.resolution in (resolution, "PRICE_APPROVAL_PENDING"):
                continue                                            # already disputed / already waiting for the buyer
            payables.resolve_exception(s, inv, exc.id, resolution, note)
            ctx.count("exceptionsDisputed" if resolution == "DISPUTE" else "priceAcceptanceRequests" if resolution == "PRICE_ACCEPTED" else "exceptionsResolved")


def ev_buyer_decides(ctx: Ctx, scn: dict, day: date) -> None:
    with tenant_tx(ctx.tenant_id) as s:
        invoice_id = find_invoice(s, scn["supplier"], scn["inv_no"]).id
    done = ctx.sc.approve_all(invoice_id, ist(day, 11), "Price accepted: the order price is raised to the supplier price (MOCK sample)")
    ctx.count("priceVarianceApprovals", done)


def ev_reject(ctx: Ctx, scn: dict, day: date, reason: str, number: Optional[str] = None) -> None:
    from app.pic.services import payables
    with ctx.act(F.AP_APPROVE, ist(day, 14)) as s:
        inv = find_invoice(s, scn["supplier"], number or scn["inv_no"])
        if inv.status == "EXCEPTION":
            payables.reject(s, inv, reason)
            ctx.count("invoicesRejected")


def build_scenario_events(ctx: Ctx, scn: dict) -> None:
    kind = scn["kind"]
    inv = day_of(scn["inv"])
    fin = finish_dates(scn)
    appr = day_of(fin["approve"])
    gr = day_of(scn["gr"]) if scn.get("gr") else None
    label = f"{scn['id']} {kind}"

    def add(day: date, hour: int, what: str, fn) -> None:
        ctx.at(ist(day, hour), f"{label} {what}", fn)

    if gr and kind not in ("DUP_REJECT", "DUP_OPEN"):
        add(gr, 10, "GR", lambda: ev_gr(ctx, scn))
    if kind in ("PAID_TDS", "PAID_MSME", "PAID_PLAIN", "POSTED_OPEN", "UNDERPRICED", "MATCHED", "APPROVED"):
        pct = "-0.2" if kind == "UNDERPRICED" else "0"
        add(inv, 11, "capture", lambda: ev_capture(ctx, scn, price_pct=pct))
        if kind != "MATCHED":
            add(appr, 15, "approve+post", lambda: ev_approve_post(ctx, scn, appr, post=kind != "APPROVED"))
    elif kind in ("PRICE_CN", "PRICE_ACCEPT", "PRICE_OPEN", "PRICE_DISPUTE"):
        pct = {"PRICE_CN": "4", "PRICE_ACCEPT": "3", "PRICE_OPEN": "5", "PRICE_DISPUTE": "6"}[kind]
        add(inv, 11, "capture", lambda: ev_capture(ctx, scn, price_pct=pct))
        d1 = clamp(inv + timedelta(days=1))
        if kind == "PRICE_CN":
            add(d1, 14, "credit note", lambda: ev_credit_and_resolve(ctx, scn, d1, "PRICE"))
            add(appr, 15, "approve+post", lambda: ev_approve_post(ctx, scn, appr))
        elif kind == "PRICE_ACCEPT":
            add(d1, 14, "price acceptance", lambda: ev_resolve(ctx, scn, d1, "PRICE_ACCEPTED", ("PRICE",), "Supplier alloy surcharge accepted from this lot (MOCK sample)"))
            if not scn.get("leave_pending"):
                d2 = clamp(inv + timedelta(days=2))
                add(d2, 11, "buyer decides", lambda: ev_buyer_decides(ctx, scn, d2))
                add(appr, 15, "approve+post", lambda: ev_approve_post(ctx, scn, appr))
        elif kind == "PRICE_DISPUTE":
            add(d1, 14, "dispute", lambda: ev_resolve(ctx, scn, d1, "DISPUTE", ("PRICE",), "Price is above the contract price; supplier asked for a credit note (MOCK sample)"))
    elif kind in ("QTY_CN", "QTY_OPEN", "QTY_REJECT"):
        pct = {"QTY_CN": "10", "QTY_OPEN": "15", "QTY_REJECT": "20"}[kind]
        add(inv, 11, "capture", lambda: ev_capture(ctx, scn, qty_pct=pct))
        d1 = clamp(inv + timedelta(days=1))
        if kind == "QTY_CN":
            add(d1, 14, "credit note", lambda: ev_credit_and_resolve(ctx, scn, d1, "QTY"))
            add(appr, 15, "approve+post", lambda: ev_approve_post(ctx, scn, appr))
        elif kind == "QTY_REJECT":
            add(d1, 14, "reject", lambda: ev_reject(ctx, scn, d1, "Billed quantity exceeds the delivery; supplier to re-issue the invoice for the quantity received (MOCK sample)"))
    elif kind in ("MGR_RESOLVED", "MGR_OPEN"):
        add(inv, 11, "capture", lambda: ev_capture(ctx, scn))
        if kind == "MGR_RESOLVED":
            add(gr, 14, "GR posted resolution", lambda: ev_resolve(ctx, scn, gr, "GR_POSTED", ("MISSING_GR",), "Goods receipt posted at the plant (MOCK sample)"))
            add(appr, 15, "approve+post", lambda: ev_approve_post(ctx, scn, appr))
    elif kind in ("TAX_IRN", "TAX_QR", "TAX_RATE"):
        mode = {"TAX_IRN": "bad_irn", "TAX_QR": "bad_qr", "TAX_RATE": "valid"}[kind]
        gst = "12.00" if kind == "TAX_RATE" else None
        add(inv, 11, "capture", lambda: ev_capture(ctx, scn, mode=mode, gst=gst))
        d2 = clamp(inv + timedelta(days=2))
        if kind == "TAX_IRN" or (kind == "TAX_RATE" and int(scn["id"][1:]) % 2 == 0):
            add(d2, 14, "reject", lambda: ev_reject(ctx, scn, d2, "E-invoice IRN / GST rate does not match the purchase order; supplier to issue a corrected tax invoice (MOCK sample)"))
    elif kind == "DUP_VARIANT":
        if len(scn["lines"]) >= 2:
            first_lines, second_lines = scn["lines"][:1], scn["lines"][1:]
        else:                                   # one line: the supplier bills the quantity in two halves
            line = scn["lines"][0]
            half = (Decimal(line["qty"]) / 2).quantize(Decimal("1"), ROUND_HALF_UP)
            first_lines = [{**line, "qty": str(half)}]
            second_lines = [{**line, "qty": str(Decimal(line["qty"]) - half)}]
        first = dict(scn, lines=first_lines)
        second = dict(scn, lines=second_lines, inv_no=scn["inv_no"].replace("/", "-"))
        add(inv, 11, "capture first", lambda: ev_capture(ctx, first))
        add(appr, 15, "approve+post first", lambda: ev_approve_post(ctx, first, appr))
        d2 = clamp(appr + timedelta(days=1))
        add(d2, 11, "capture variant", lambda: ev_capture(ctx, second, number=second["inv_no"], lines=invoice_lines(second)))
        add(d2, 14, "not a duplicate", lambda: ev_resolve(ctx, second, d2, "NOT_DUPLICATE", ("DUPLICATE",), "Different delivery and line: not a duplicate (MOCK sample)",
                                                          number=second["inv_no"]))
        d3 = clamp(d2 + timedelta(days=1))
        add(d3, 15, "approve+post variant", lambda: ev_approve_post(ctx, second, d3, number=second["inv_no"]))
    elif kind == "FOREIGN":
        add(inv, 11, "capture", lambda: ev_capture(ctx, scn))
        add(appr, 15, "approve+post", lambda: ev_approve_post(ctx, scn, appr))
    elif kind in ("DUP_REJECT", "DUP_OPEN"):
        add(inv, 11, "capture duplicate", lambda: ev_capture(ctx, scn))
        if kind == "DUP_REJECT":
            d1 = clamp(inv + timedelta(days=1))
            add(d1, 14, "reject duplicate", lambda: ev_reject(ctx, scn, d1, "Duplicate of the invoice already posted for the same delivery (MOCK sample)"))
