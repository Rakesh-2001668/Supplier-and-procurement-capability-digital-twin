"""F7 Invoice → match → ERP posting → payment (M10, Technical Document §9.4)."""
import hashlib
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    BudgetCommitment, CreditNote, Invoice, InvoiceException, InvoiceLine, Payment, PoLine, PurchaseOrder, ReturnDelivery, Supplier,
    SupplierBankAccount,
)
from app.pic.platform import agents, audit, clock, crypto, integration, outbox, rules, sod, workflow
from app.pic.platform.core import StateMachine, link, next_number
from app.pic.platform.errors import Problem, illegal_transition, rule_violation
from app.pic.platform.money import D, fmt_inr, line_amount, pct_of, tax_amount
from app.pic.platform.serialize import jsonable
from app.pic.services import einvoice
from app.pic.services import order as order_svc
from app.pic.services.common import days_from_terms, principal, require_supplier_user, supplier_ref

PROCESS = "pic.invoice"
RETENTION = "RETENTION"  # channel and match type of a retention-release AP document (release_retention)
ERS = "ERS"  # channel and match type of a consignment self-billing settlement (settle_consignment, P08)
SM = StateMachine("INVOICE", {
    ("CAPTURED", "check_duplicates"): "DUPLICATE_CHECK",
    ("DUPLICATE_CHECK", "match"): "MATCHING",
    ("DUPLICATE_CHECK", "hold"): "EXCEPTION",
    ("MATCHING", "matched"): "MATCHED",
    ("MATCHING", "exception"): "EXCEPTION",
    ("EXCEPTION", "rematch"): "MATCHING",
    ("MATCHED", "approve"): "APPROVED",
    ("APPROVED", "post"): "POSTED",
    ("POSTED", "pay"): "PAID",
    ("EXCEPTION", "reject"): "REJECTED",
    ("CAPTURED", "reject"): "REJECTED",
})


def expected_irn(gstin: str, fiscal_year: str, doc_type: str, doc_no: str) -> str:
    """GST e-invoice IRN: SHA-256 of supplier GSTIN, financial year, document type and number."""
    return hashlib.sha256(f"{gstin}{fiscal_year}{doc_type}{doc_no}".encode()).hexdigest()


def _instance(session: Session, invoice: Invoice):
    return workflow.find(session, "INVOICE", invoice.id, PROCESS)


def _lines(session: Session, invoice: Invoice) -> list[InvoiceLine]:
    return session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id).order_by(InvoiceLine.line_no)).scalars().all()


def _credited_qty(session: Session, invoice: Invoice) -> dict[int, Decimal]:
    credited: dict[int, Decimal] = {}
    for note in session.execute(select(CreditNote).where(CreditNote.invoice_id == invoice.id)).scalars():
        for entry in note.lines:
            credited[int(entry["invoice_line"])] = credited.get(int(entry["invoice_line"]), Decimal(0)) + D(entry["qty"])
    return credited


def retention_by_po(session: Session, invoice: Invoice) -> dict[uuid.UUID, int]:
    """Retention withheld on this invoice per purchase order: retention_pct of the taxable value invoiced against each PO
    that carries a retention percentage (construction / subcontract orders), net of credit notes. GST is charged on the
    full value; the retention only reduces what is paid until it is released (release_retention)."""
    if invoice.match_type == RETENTION:
        return {}
    credited = _credited_qty(session, invoice)
    base: dict[uuid.UUID, int] = {}
    pct: dict[uuid.UUID, Decimal] = {}
    for line in _lines(session, invoice):
        po_line = session.get(PoLine, line.po_line_id) if line.po_line_id else None
        if po_line is None:
            continue
        if po_line.po_id not in pct:
            pct[po_line.po_id] = D(session.get(PurchaseOrder, po_line.po_id).retention_pct or 0)
        if pct[po_line.po_id] > 0:
            net_qty = line.qty - credited.get(line.line_no, Decimal(0))
            base[po_line.po_id] = base.get(po_line.po_id, 0) + line_amount(net_qty, line.unit_price_minor)
    return {po_id: pct_of(amount, pct[po_id]) for po_id, amount in base.items() if pct_of(amount, pct[po_id]) > 0}


# ---------------------------------------------------------------- capture & duplicate check (F7-01/02)
def capture(session: Session, *, supplier: str, supplier_invoice_no: str, invoice_date: date, channel: str, lines: list[dict],
            irn: Optional[str] = None, company_code: str = "1000", signed_qr: Optional[str] = None) -> Invoice:
    p = principal(session)
    supplier_row = supplier_ref(session, supplier)
    require_supplier_user(session, supplier_row.id)
    fiscal_year = clock.fiscal_year(invoice_date)
    existing = session.execute(select(Invoice).where(Invoice.company_code == company_code, Invoice.supplier_id == supplier_row.id,
                                                     Invoice.supplier_invoice_no == supplier_invoice_no, Invoice.fiscal_year == fiscal_year)).scalar_one_or_none()
    if existing:
        raise Problem(409, "DUPLICATE_INVOICE", f"{supplier_invoice_no} from {supplier_row.code} is already captured as {existing.number}",
                      rule_ref="§5.2", duplicateOf=existing.number)
    po_numbers = {l["po"] for l in lines}
    pos = {n: session.execute(select(PurchaseOrder).where(PurchaseOrder.number == n)).scalar_one() for n in po_numbers}
    taken = session.execute(select(Invoice.id).where(Invoice.number == supplier_invoice_no)).first()
    invoice = Invoice(
        tenant_id=current_tenant(session), number=supplier_invoice_no if not taken else f"{supplier_row.code}/{supplier_invoice_no}",
        supplier_invoice_no=supplier_invoice_no, fiscal_year=fiscal_year, company_code=company_code, supplier_id=supplier_row.id,
        po_id=list(pos.values())[0].id if len(pos) == 1 else None, invoice_date=invoice_date, channel=channel.upper(), irn=irn,
        currency="INR", net_minor=0, tax_minor=0, gross_minor=0, status="CAPTURED", created_by=p.user_id,
    )
    session.add(invoice)
    session.flush()
    net_total = tax_total = 0
    for index, data in enumerate(lines, start=1):
        po = pos[data["po"]]
        po_line = session.execute(select(PoLine).where(PoLine.po_id == po.id, PoLine.line_no == int(data["po_line"]))).scalar_one()
        if not po_line.ir_required:
            # P08: consignment is settled by self-billing (ERS) on withdrawal; the supplier does not invoice the order line.
            raise rule_violation(f"{po.number}/{po_line.line_no} is a {po_line.purchase_type.lower()} line: it is settled by self-billing "
                                 "(ERS) on withdrawal, not by a supplier invoice", "P08")
        qty = D(data["qty"])
        price = int(D(data["unit_price"]) * 100)
        net = line_amount(qty, price)
        rate = D(data.get("gst_rate", po_line.gst_rate))
        tax = int(data["tax_minor"]) if "tax_minor" in data else tax_amount(net, rate)
        session.add(InvoiceLine(tenant_id=invoice.tenant_id, invoice_id=invoice.id, line_no=index * 10, po_line_id=po_line.id,
                                description=data.get("description", po_line.description), qty=qty, unit_price_minor=price, net_minor=net,
                                hsn_code=data.get("hsn", po_line.hsn_code), gst_rate=rate, tax_minor=tax, created_by=p.user_id))
        net_total += net
        tax_total += tax
        link(session, "PURCHASE_ORDER", po.id, po.number, "INVOICE", invoice.id, invoice.number, "invoiced_against",
             from_line=po_line.line_no, to_line=index * 10)
    invoice.net_minor, invoice.tax_minor, invoice.gross_minor = net_total, tax_total, net_total + tax_total
    invoice.retention_minor = sum(retention_by_po(session, invoice).values())  # withheld from payment for POs with retention_pct
    verification = None
    if irn or signed_qr:
        # IRN and signed QR validated on capture (§12.3): IRP lookup when configured, local hash/QR checks otherwise.
        verification = einvoice.verify(session, supplier=supplier_row, company_code=company_code, supplier_invoice_no=supplier_invoice_no,
                                       invoice_date=invoice_date, gross_minor=invoice.gross_minor, irn=irn, signed_qr=signed_qr)
        invoice.irn_valid = verification["valid"]
    session.flush()
    instance = workflow.start(session, PROCESS, "INVOICE", invoice.id, invoice.number)
    outbox.emit(session, "invoice.captured", "INVOICE", invoice.id, invoice.number,
                {"supplier": supplier_row.code, "grossMinor": invoice.gross_minor, "channel": invoice.channel})
    audit.record(session, "INVOICE", invoice.id, "CAPTURED", object_ref=invoice.number,
                 after={"supplier": supplier_row.code, "grossMinor": invoice.gross_minor, "irnValid": invoice.irn_valid,
                        "eInvoiceVerification": verification["level"] if verification else None,
                        **({"retentionMinor": invoice.retention_minor} if invoice.retention_minor else {})})
    if verification:
        einvoice.record(session, invoice, verification)
    _duplicate_check(session, invoice, instance)
    return invoice


def _duplicate_check(session: Session, invoice: Invoice, instance) -> None:
    rule = rules.resolve(session, "DMN-03", company_code=invoice.company_code)
    invoice.rule_set_version = rule.ref
    SM.apply(session, invoice, "check_duplicates", rule_set_version=rule.ref)
    window = timedelta(days=int(rule.body["dupDays"]))
    fuzzy = session.execute(select(Invoice).where(
        Invoice.supplier_id == invoice.supplier_id, Invoice.id != invoice.id, Invoice.status != "REJECTED",
        func.coalesce(Invoice.match_type, "") != RETENTION,  # a retention release is not a supplier invoice
        func.abs(Invoice.gross_minor - invoice.gross_minor) <= int(rule.body["dupAmountMinor"]),
        Invoice.invoice_date.between(invoice.invoice_date - window, invoice.invoice_date + window))).scalars().first()
    if fuzzy:
        invoice.duplicate_of = fuzzy.id
        invoice.payment_block = True
        session.add(InvoiceException(tenant_id=invoice.tenant_id, invoice_id=invoice.id, type="DUPLICATE",
                                     delta={"similarTo": fuzzy.number}, detail=f"Amount and date match {fuzzy.number} within tolerance",
                                     suggested_action="Hold; confirm with supplier whether this is a duplicate", status="OPEN",
                                     created_by=principal(session).user_id))
        SM.apply(session, invoice, "hold", rule_set_version=rule.ref)
        workflow.step(session, instance, "F7-02", outcome=f"possible duplicate of {fuzzy.number}: held")
        workflow.wait(session, instance, "F7-05", outcome="resolve duplicate hold")
        return
    workflow.step(session, instance, "F7-02", outcome="captured; no duplicate (exact key and amount ±₹1 / date ±3 days)")
    match(session, invoice)


# ---------------------------------------------------------------- freight audit (BP §23 Logistics template, rule FREIGHT-AUDIT)
def _freight_rule(session: Session, company_code: str):
    """FREIGHT-AUDIT comes with the Logistics industry template; tenants without it keep the standard match only."""
    try:
        return rules.resolve(session, "FREIGHT-AUDIT", company_code=company_code)
    except Problem:
        return None


def _freight_audit(session: Session, rule, line: InvoiceLine, po_line: PoLine, net_qty: Decimal) -> Optional[dict]:
    """BP §23.1 Logistics: a freight invoice is validated against the contracted lane rate valid on the loading date (fuel-index
    resets included) times the distance on the approved proof of delivery, not against the PO quantity. None when no proof of
    delivery is approved yet (the SERVICE check already parks such an invoice)."""
    from app.pic.models import ServiceEntry, SesLine
    from app.pic.services import source

    pods = session.execute(select(SesLine, ServiceEntry).join(ServiceEntry, ServiceEntry.id == SesLine.ses_id).where(
        SesLine.po_line_id == po_line.id, ServiceEntry.status == "APPROVED")).all()
    if not pods:
        return None
    pod_qty = sum((ses_line.qty for ses_line, _ in pods), Decimal(0))
    loaded_on = min(entry.period_from for _, entry in pods)
    validity = source.contract_price(session, po_line.contract_line_id, loaded_on)
    rate = validity.unit_price_minor if validity else po_line.unit_price_minor
    billable = max(min(net_qty, pod_qty - po_line.invoiced_qty), Decimal(0))
    expected = line_amount(billable, rate)
    billed = line_amount(net_qty, line.unit_price_minor)
    over = billed - expected
    return {"loadedOn": loaded_on.isoformat(), "uom": po_line.uom, "contractRateMinor": rate,
            "rateValidFrom": validity.valid_from.isoformat() if validity else None, "rateBasis": validity.reason if validity else "PO_PRICE",
            "indexValue": f"{validity.index_value:.2f}" if validity is not None and validity.index_value is not None else None,
            "podQty": format(pod_qty.normalize(), "f"), "billedQty": format(net_qty.normalize(), "f"), "expectedMinor": expected, "billedMinor": billed,
            "overbilledMinor": max(over, 0), "withinTolerance": over <= pct_of(expected, rule.body.get("rateTolerancePct", 0)),
            "ruleSetVersion": rule.ref}


# ---------------------------------------------------------------- match (F7-03/04)
def match(session: Session, invoice: Invoice) -> dict:
    p = principal(session)
    rule = rules.resolve(session, "DMN-03", company_code=invoice.company_code)
    if invoice.status == "EXCEPTION":
        SM.apply(session, invoice, "rematch")
    else:
        SM.apply(session, invoice, "match")
    credited = _credited_qty(session, invoice)
    exceptions, results = [], []
    match_types = set()
    for line in _lines(session, invoice):
        po_line = session.get(PoLine, line.po_line_id)
        net_qty = line.qty - credited.get(line.line_no, Decimal(0))
        detail = {"invoicedQty": str(line.qty), "creditedQty": str(credited.get(line.line_no, 0)), "netQty": str(net_qty),
                  "poQty": str(po_line.qty), "poPriceMinor": po_line.unit_price_minor, "invoicePriceMinor": line.unit_price_minor}
        if po_line.ses_required:
            match_types.add("SES")
            available = po_line.ses_approved_minor - po_line.invoiced_minor
            net_value = line_amount(net_qty, line.unit_price_minor)
            detail["sesApprovedMinor"] = po_line.ses_approved_minor
            if net_value > available:
                exceptions.append((line, "SERVICE", {"valueMinor": net_value - available},
                                   f"Invoiced service value exceeds approved service entries by {(net_value - available)/100:,.2f}",
                                   "Ask the service owner to approve the missing service entry or request a credit note"))
        elif po_line.ers:
            # P08 consignment: the self-billing (ERS) document settles what was withdrawn from consignment stock, not what was received.
            from app.pic.services.receiving import consignment_withdrawn
            match_types.add("ERS")
            withdrawn = consignment_withdrawn(session, [po_line.id]).get(po_line.id, Decimal(0))
            available = withdrawn - po_line.invoiced_qty
            detail.update({"receivedQty": str(po_line.received_qty), "withdrawnQty": str(withdrawn),
                           "alreadyInvoicedQty": str(po_line.invoiced_qty), "matchBasis": "CONSIGNMENT_WITHDRAWN"})
            if net_qty > available:
                exceptions.append((line, "QUANTITY", {"qty": jsonable(net_qty - available)},
                                   f"Settled {net_qty} vs withdrawn and not yet settled {available}",
                                   "Settle only quantities withdrawn from consignment stock"))
        elif po_line.gr_required and not po_line.ers:
            # F7-03: 3-way = PO + goods receipt + invoice (quantity received, net of returns).
            #        4-way = PO + goods receipt + inspection + invoice for quality-managed lines: only the quantity the
            #        usage decision ACCEPTED can be invoiced, so stock still in quality inspection is not payable yet.
            four_way = po_line.quality_managed
            match_types.add("4WAY" if four_way else "3WAY")
            basis = po_line.accepted_qty if four_way else po_line.received_qty - po_line.rejected_qty
            available = basis - po_line.invoiced_qty
            in_inspection = max(po_line.received_qty - po_line.accepted_qty - po_line.rejected_qty, Decimal(0)) if four_way else Decimal(0)
            detail.update({"receivedQty": str(po_line.received_qty), "acceptedQty": str(po_line.accepted_qty),
                           "alreadyInvoicedQty": str(po_line.invoiced_qty), "matchBasis": "INSPECTION_ACCEPTED" if four_way else "RECEIVED",
                           "inInspectionQty": str(in_inspection)})
            if po_line.received_qty == 0:
                exceptions.append((line, "MISSING_GR", {"qty": jsonable(net_qty)}, "No goods receipt posted yet",
                                   "Wait for the goods receipt; the invoice stays parked"))
            elif net_qty > available * (1 + D(rule.body["qtyPct"]) / 100):
                delta = net_qty - available
                rejected = po_line.rejected_qty
                cause = f"; {rejected} rejected at quality inspection" if rejected else ""
                if in_inspection:
                    cause += f"; {in_inspection} still in quality inspection"
                exceptions.append((line, "QUANTITY", {"qty": jsonable(delta)},
                                   f"Billed {net_qty} vs {'accepted' if four_way else 'received'} {available}{cause}",
                                   "Wait for the usage decision on the open inspection lot" if in_inspection and not rejected
                                   else f"Request credit note for {delta} units"))
        else:
            match_types.add("2WAY")
            available = po_line.qty - po_line.invoiced_qty
            if net_qty > available:
                exceptions.append((line, "QUANTITY", {"qty": jsonable(net_qty - available)}, f"Billed {net_qty} vs open PO {available}",
                                   "Amend the PO or request a credit note"))
        price_tol = min(Decimal(po_line.unit_price_minor) * D(rule.body["pricePct"]) / 100, Decimal(rule.body["priceAbsMinor"]))
        if abs(Decimal(line.unit_price_minor - po_line.unit_price_minor)) > price_tol:
            exceptions.append((line, "PRICE", {"perUnitMinor": line.unit_price_minor - po_line.unit_price_minor},
                               f"Unit price {line.unit_price_minor/100:.2f} vs PO {po_line.unit_price_minor/100:.2f} (tolerance {price_tol/100:.2f})",
                               "Request a credit note or obtain buyer price-variance approval"))
        freight = _freight_rule(session, invoice.company_code) if po_line.ses_required and po_line.contract_line_id else None
        freight_audit = _freight_audit(session, freight, line, po_line, net_qty) if freight is not None else None
        if freight_audit is not None:
            detail["freightAudit"] = freight_audit
            if not freight_audit["withinTolerance"]:
                fa = freight_audit
                exceptions.append((line, "FREIGHT_AUDIT", {"overbilledMinor": fa["overbilledMinor"], "expectedMinor": fa["expectedMinor"],
                                                           "billedMinor": fa["billedMinor"], "podQty": fa["podQty"], "billedQty": fa["billedQty"]},
                                   f"Freight audit: billed {fa['billedQty']} {fa['uom']} × {line.unit_price_minor/100:.2f} = {fmt_inr(fa['billedMinor'])} "
                                   f"vs proof of delivery {fa['podQty']} {fa['uom']} × contracted {fa['contractRateMinor']/100:.2f} "
                                   f"(rate valid from {fa['rateValidFrom']}" + (f", index {fa['indexValue']}" if fa["indexValue"] else "") +
                                   f") = {fmt_inr(fa['expectedMinor'])}; over-billed {fmt_inr(fa['overbilledMinor'])}",
                                   "Request a credit note for the over-billed amount (freight audit recovery)"))
        tax_ok = (D(line.gst_rate) == D(po_line.gst_rate) and (line.hsn_code or "") == (po_line.hsn_code or "")
                  and line.tax_minor == tax_amount(line.net_minor, line.gst_rate)
                  and (invoice.channel != "E_INVOICE" or invoice.irn_valid is True))
        if not tax_ok:
            exceptions.append((line, "TAX", {}, "Tax rate, HSN, tax amount or IRN does not match",
                               "Verify HSN/SAC code and the e-invoice IRN with the supplier"))
        else:
            # D11: invoice and PO agree, but the rate must also be a scheduled GST rate for the HSN/SAC (CBIC master, rule HSN-GST).
            from app.pic.services import gst
            finding = gst.check(session, line.hsn_code, line.gst_rate, invoice.invoice_date)
            if finding:
                detail["gstMaster"] = finding
                exceptions.append((line, "TAX", finding,
                                   f"GST {finding['gstRate']}% is not a scheduled rate for HSN/SAC {line.hsn_code} "
                                   f"(CBIC master: {', '.join(finding['allowedRates'])}%)",
                                   "Ask the supplier for a corrected invoice at the scheduled rate and correct the PO line tax code"))
        line.match_status = "OK" if not any(e[0] is line for e in exceptions) else "EXCEPTION"
        line.match_detail = detail
        results.append({"line": line.line_no, "status": line.match_status, **detail})
    invoice.match_type = ("SES" if match_types == {"SES"} else "ERS" if match_types == {"ERS"} else "4WAY" if "4WAY" in match_types
                          else "3WAY" if "3WAY" in match_types else "2WAY")
    for old in session.execute(select(InvoiceException).where(InvoiceException.invoice_id == invoice.id,
                                                              InvoiceException.status == "OPEN")).scalars():
        old.status = "SUPERSEDED"
    instance = _instance(session, invoice)
    first_attempt = invoice.first_pass_matched is None
    if exceptions:
        invoice.payment_block = True
        if first_attempt:
            invoice.first_pass_matched = False
        created = []
        for line, etype, delta, text, action in exceptions:
            exc = InvoiceException(tenant_id=invoice.tenant_id, invoice_id=invoice.id, invoice_line_id=line.id, type=etype, delta=delta,
                                   detail=text, suggested_action=action, status="OPEN", created_by=p.user_id)
            session.add(exc)
            created.append(exc)
        session.flush()
        ai_ref = agents.log_run(session, "INVOICE_EXCEPTION", object_type="INVOICE", object_id=invoice.id, object_ref=invoice.number,
                                inputs={"exceptions": [e.type for e in created]},
                                evidence=[r.number for r in session.execute(select(ReturnDelivery).join(PoLine, PoLine.id == ReturnDelivery.po_line_id)
                                                                             .where(PoLine.id.in_([l.po_line_id for l in _lines(session, invoice)]))).scalars()],
                                output={"explanation": [e.detail for e in created], "proposal": [e.suggested_action for e in created]},
                                confidence=0.88, action_taken="DRAFTED")
        for exc in created:
            exc.ai_ref = ai_ref
        SM.apply(session, invoice, "exception", rule_set_version=rule.ref, ai_ref=ai_ref)
        outbox.emit(session, "invoice.exception.raised", "INVOICE", invoice.id, invoice.number,
                    {"exceptions": [{"type": e.type, "delta": e.delta} for e in created]})
        workflow.step(session, instance, "F7-03", outcome=f"{invoice.match_type}: " + "; ".join(f"{e.type} {e.delta}" for e in created))
        workflow.step(session, instance, "F7-04", outcome="no: outside tolerance → payment block")
        workflow.wait(session, instance, "F7-05", outcome="; ".join(e.suggested_action for e in created))
    else:
        invoice.payment_block = False
        if first_attempt:
            invoice.first_pass_matched = True
        SM.apply(session, invoice, "matched", rule_set_version=rule.ref)
        workflow.step(session, instance, "F7-03", outcome=f"{invoice.match_type}: all lines within tolerance")
        if instance.current_step != "F7-05":
            workflow.step(session, instance, "F7-04", outcome="yes: within tolerance")
    return {"invoice": invoice.number, "status": invoice.status, "matchType": invoice.match_type, "lines": results,
            "exceptions": [{"type": e[1], "delta": e[2], "detail": e[3], "suggestedAction": e[4]} for e in exceptions]}


# ---------------------------------------------------------------- exceptions (F7-05)
def submit_credit_note(session: Session, invoice: Invoice, *, supplier_credit_note_no: str, note_date: date, reason: str,
                       lines: list[dict]) -> CreditNote:
    p = principal(session)
    require_supplier_user(session, invoice.supplier_id)
    inv_lines = {l.line_no: l for l in _lines(session, invoice)}
    net = tax = 0
    for entry in lines:
        line = inv_lines[int(entry["invoice_line"])]
        amount = line_amount(D(entry["qty"]), line.unit_price_minor)
        net += amount
        tax += tax_amount(amount, line.gst_rate)
    note = CreditNote(tenant_id=invoice.tenant_id, number=supplier_credit_note_no, supplier_credit_note_no=supplier_credit_note_no,
                      supplier_id=invoice.supplier_id, invoice_id=invoice.id, note_date=note_date, reason=reason, net_minor=net,
                      tax_minor=tax, gross_minor=net + tax, lines=[{"invoice_line": int(e["invoice_line"]), "qty": str(e["qty"])} for e in lines],
                      created_by=p.user_id)
    session.add(note)
    session.flush()
    link(session, "INVOICE", invoice.id, invoice.number, "CREDIT_NOTE", note.id, note.number, "credited_by")
    memo = None
    if invoice.posting_key and invoice.status in ("POSTED", "PAID"):
        # The invoice is already in the ERP for its gross amount: the credit note goes there as a vendor credit memo, posted by
        # the connector worker (exactly-once key), so the ERP liability and the platform (gross net of credit notes) agree again.
        supplier = session.get(Supplier, invoice.supplier_id)
        memo = integration.enqueue(session, target_system=integration.target_system(session, invoice.company_code),
                                   message_type="SUPPLIER_CREDIT_MEMO", idempotency_key=f"{invoice.posting_key}|CN|{note.number}",
                                   object_type="INVOICE", object_id=invoice.id, object_ref=invoice.number,
                                   payload={"creditNote": note.number, "invoice": invoice.supplier_invoice_no, "invoiceErp": invoice.erp_doc_no,
                                            "supplier": supplier.code, "companyCode": invoice.company_code, "grossMinor": note.gross_minor,
                                            "fiscalYear": invoice.fiscal_year})
    audit.record(session, "INVOICE", invoice.id, "CREDIT_NOTE_RECEIVED", object_ref=invoice.number,
                 after={"creditNote": note.number, "grossMinor": note.gross_minor,
                        **({"erpCreditMemo": memo.idempotency_key} if memo is not None else {})}, reason=reason)
    return note


def resolve_exception(session: Session, invoice: Invoice, exception_id: uuid.UUID, resolution: str, note: str,
                      credit_note: Optional[str] = None) -> dict:
    p = principal(session)
    exc = session.get(InvoiceException, exception_id)
    if exc is None or exc.invoice_id != invoice.id or exc.status != "OPEN":
        raise Problem(404, "NOT_FOUND", "Open exception not found on this invoice")
    resolution = resolution.upper()
    allowed = {"CREDIT_NOTE_RECEIVED", "PRICE_ACCEPTED", "NOT_DUPLICATE", "DISPUTE", "GR_POSTED"}
    if resolution not in allowed:
        raise Problem(422, "INVALID_RESOLUTION", f"resolution must be one of {sorted(allowed)}")
    if resolution == "CREDIT_NOTE_RECEIVED":
        if not credit_note or not session.execute(select(CreditNote).where(CreditNote.invoice_id == invoice.id,
                                                                           CreditNote.number == credit_note)).first():
            raise rule_violation("Reference the credit note received for this invoice", "DMN-03")
    po_line = session.get(PoLine, session.get(InvoiceLine, exc.invoice_line_id).po_line_id) if exc.invoice_line_id else None
    if po_line is not None:
        sod.guard(session, "INVOICE_EXCEPTION_APPROVE", {"po_id": po_line.po_id})
        sod.record(session, "INVOICE_EXCEPTION_APPROVE", {"po_id": po_line.po_id})
    if resolution == "DISPUTE":
        # Raising a dispute does not resolve the exception: it stays OPEN (payment block) and marked as disputed until the
        # supplier's credit note, an accepted variance or a corrected invoice (this one rejected) closes it.
        exc.resolution, exc.resolution_note = "DISPUTE", note
        audit.record(session, "INVOICE", invoice.id, "EXCEPTION_DISPUTED", object_ref=invoice.number,
                     after={"exception": exc.type, "delta": exc.delta}, reason=note, ai_ref=exc.ai_ref,
                     rule_set_version=invoice.rule_set_version)
        outbox.emit(session, "invoice.disputed", "INVOICE", invoice.id, invoice.number,
                    {"exception": exc.type, "delta": exc.delta, "note": note})
        instance = _instance(session, invoice)
        if instance is not None and instance.status == "RUNNING":
            workflow.wait(session, instance, "F7-05", outcome=f"{exc.type.lower()} disputed with supplier: {note}")
        return {"invoice": invoice.number, "status": invoice.status, "dispute": True, "exception": str(exc.id)}
    before = {"status": "EXCEPTION", "exception": exc.type}
    exc.status, exc.resolution, exc.resolution_note, exc.resolved_by = "RESOLVED", resolution, note, p.user_id
    if resolution == "PRICE_ACCEPTED" and po_line is not None:
        line = session.get(InvoiceLine, exc.invoice_line_id)
        po_line.unit_price_minor = line.unit_price_minor  # accepted variance becomes the price to match against
    if resolution == "NOT_DUPLICATE":
        invoice.duplicate_of = None
    audit.record(session, "INVOICE", invoice.id, "EXCEPTION_RESOLVED", object_ref=invoice.number, before=before,
                 after={"resolution": resolution, "creditNote": credit_note}, reason=note, ai_ref=exc.ai_ref,
                 rule_set_version=invoice.rule_set_version)
    still_open = session.execute(select(InvoiceException).where(InvoiceException.invoice_id == invoice.id,
                                                                InvoiceException.status == "OPEN")).first()
    if still_open:
        return {"invoice": invoice.number, "status": invoice.status}
    instance = _instance(session, invoice)
    workflow.step(session, instance, "F7-05", outcome=f"{resolution.lower().replace('_', ' ')}" + (f" {credit_note}" if credit_note else ""))
    result = match(session, invoice)
    return {"invoice": invoice.number, "status": invoice.status, "match": result}


def reject(session: Session, invoice: Invoice, reason: str) -> Invoice:
    """Reject a held invoice (e.g. a confirmed duplicate). Open exceptions close with it; nothing is posted or paid."""
    if not reason:
        raise rule_violation("A rejection reason is required", "DMN-03")
    SM.apply(session, invoice, "reject", reason=reason)
    invoice.payment_block = True
    for exc in session.execute(select(InvoiceException).where(InvoiceException.invoice_id == invoice.id,
                                                              InvoiceException.status == "OPEN")).scalars():
        exc.status, exc.resolution, exc.resolution_note = "RESOLVED", "REJECTED", reason
        exc.resolved_by = principal(session).user_id
    instance = _instance(session, invoice)
    if instance and instance.status == "RUNNING":
        workflow.end(session, instance, "F7-09", outcome=f"rejected: {reason}")
    return invoice


def approve(session: Session, invoice: Invoice) -> Invoice:
    sod.guard(session, "INVOICE_POST", {"supplier_id": invoice.supplier_id})
    SM.apply(session, invoice, "approve", rule_set_version=invoice.rule_set_version)
    invoice.approved_by = principal(session).user_id
    return invoice


# ---------------------------------------------------------------- post (F7-06)
def posting_key(session: Session, invoice: Invoice) -> str:
    supplier = session.get(Supplier, invoice.supplier_id)
    return f"{principal(session).tenant_code}|{invoice.company_code}|{supplier.code}|{invoice.supplier_invoice_no}"


def post(session: Session, invoice: Invoice, idempotency_key: Optional[str]) -> dict:
    expected = posting_key(session, invoice)
    if idempotency_key and idempotency_key != expected:
        raise rule_violation(f"Posting key must be tenant|company code|supplier|invoice number ({expected})", "P13")
    if invoice.status == "POSTED" or invoice.status == "PAID":
        return {"status": invoice.status, "erpDocument": invoice.erp_doc_no}
    if invoice.status != "APPROVED":
        raise illegal_transition("Invoice", invoice.number, invoice.status, "post")
    if session.execute(select(InvoiceException).where(InvoiceException.invoice_id == invoice.id, InvoiceException.status == "OPEN")).first():
        raise rule_violation("Open exceptions block posting", "DMN-03")
    sod.guard(session, "INVOICE_POST", {"supplier_id": invoice.supplier_id})
    sod.record(session, "INVOICE_POST", {"supplier_id": invoice.supplier_id})
    invoice.posting_key = expected
    credit = sum(n.gross_minor for n in session.execute(select(CreditNote).where(CreditNote.invoice_id == invoice.id)).scalars())
    supplier = session.get(Supplier, invoice.supplier_id)
    # Retention is recomputed at posting (credit notes may have arrived since capture) and posted as a blocked item of the
    # vendor liability: the ERP books the full gross; netPayableMinor is what the next payment run may pay.
    invoice.retention_minor = sum(retention_by_po(session, invoice).values())
    retention = ({"retentionMinor": invoice.retention_minor, "netPayableMinor": invoice.gross_minor - credit - invoice.retention_minor}
                 if invoice.retention_minor else {})
    message = integration.enqueue(session, target_system=integration.target_system(session, invoice.company_code), message_type="SUPPLIER_INVOICE",
                                  idempotency_key=expected,
                                  object_type="INVOICE", object_id=invoice.id, object_ref=invoice.number,
                                  payload={"invoice": invoice.supplier_invoice_no, "supplier": supplier.code, "companyCode": invoice.company_code,
                                           "grossMinor": invoice.gross_minor - credit, "creditNotes": credit,
                                           "irn": invoice.irn, "fiscalYear": invoice.fiscal_year, **retention})
    if retention and message.attempts == 0:
        audit.record(session, "INVOICE", invoice.id, "RETENTION_WITHHELD", object_ref=invoice.number,
                     after={**retention, "grossMinor": invoice.gross_minor - credit})
    integration.process(session, message)
    if message.status != "POSTED":
        return {"status": "POSTING", "integrationStatus": message.status, "attempts": message.attempts, "error": message.last_error}
    return {"status": invoice.status, "erpDocument": invoice.erp_doc_no}


@integration.on_posted("SUPPLIER_INVOICE")
def _invoice_posted(session: Session, message) -> None:
    invoice = session.get(Invoice, message.object_id)
    SM.apply(session, invoice, "post", rule_set_version=invoice.rule_set_version, extra_after={"erpDocument": message.erp_doc_no})
    invoice.erp_doc_no = message.erp_doc_no
    invoice.posted_at = clock.now()
    invoice.payment_block = False
    supplier = session.get(Supplier, invoice.supplier_id)
    invoice.due_date = invoice.invoice_date + timedelta(days=days_from_terms(supplier.payment_terms))
    credited = _credited_qty(session, invoice)
    touched_pos = set()
    by_requisition: dict[uuid.UUID, int] = {}
    for line in _lines(session, invoice):
        po_line = session.get(PoLine, line.po_line_id)
        net_qty = line.qty - credited.get(line.line_no, Decimal(0))
        value = line_amount(net_qty, line.unit_price_minor)
        po_line.invoiced_qty += net_qty
        po_line.invoiced_minor += value
        touched_pos.add(po_line.po_id)
        if po_line.requisition_id and po_line.account_assignment_code:
            by_requisition[po_line.requisition_id] = by_requisition.get(po_line.requisition_id, 0) + value
    for po_id in touched_pos:
        po = session.get(PurchaseOrder, po_id)
        if po.status == "RECEIVED" and all(l.invoiced_qty >= l.accepted_qty for l in order_svc.lines_of(session, po)):
            order_svc.SM.apply(session, po, "invoice")
        elif po.status == "CONFIRMED" and all(not l.gr_required and not l.ses_required and l.invoiced_qty >= l.qty
                                              for l in order_svc.lines_of(session, po)):
            order_svc.SM.apply(session, po, "invoice")  # P08 receipt-less expense order, 2-way matched in full
    _consume_budget(session, by_requisition)
    link(session, "INVOICE", invoice.id, invoice.number, "ERP_DOCUMENT", invoice.id, message.erp_doc_no, "posted_as")
    outbox.emit(session, "invoice.posted", "INVOICE", invoice.id, invoice.number,
                {"invoiceId": str(invoice.id), "erpDocument": message.erp_doc_no, "supplier": supplier.code, "grossMinor": invoice.gross_minor})
    instance = _instance(session, invoice)
    workflow.step(session, instance, "F7-06", outcome=f"posted as ERP document {message.erp_doc_no} (key {message.idempotency_key})")
    workflow.wait(session, instance, "F7-07", outcome=f"due {invoice.due_date.isoformat()} ({supplier.payment_terms})")


def _consume_budget(session: Session, amounts_by_requisition: dict[uuid.UUID, int]) -> None:
    """Move this invoice's value from commitment to consumption on the requisition's cost objects."""
    from app.pic.models import Budget
    for requisition_id, amount in amounts_by_requisition.items():
        for commitment in session.execute(select(BudgetCommitment).where(BudgetCommitment.object_id == requisition_id,
                                                                         BudgetCommitment.status == "OPEN")).scalars():
            take = min(amount, commitment.amount_minor)
            if take <= 0:
                continue
            budget = session.get(Budget, commitment.budget_id)
            budget.committed_minor -= take
            budget.consumed_minor += take
            commitment.amount_minor -= take  # remaining commitment
            amount -= take
            if commitment.amount_minor == 0:
                commitment.status = "CONSUMED"


# ---------------------------------------------------------------- payment run (F7-07/09)
def payment_run(session: Session, run_date: date, include_not_due: bool = False) -> dict:
    p = principal(session)
    run_ref = next_number(session, "PAYMENT_RUN")
    query = select(Invoice).where(Invoice.status == "POSTED", Invoice.payment_status == "UNPAID", Invoice.payment_block.is_(False))
    if not include_not_due:
        query = query.where(Invoice.due_date <= run_date)
    paid, skipped = [], []
    for invoice in session.execute(query.order_by(Invoice.due_date)).scalars().all():
        supplier = session.get(Supplier, invoice.supplier_id)
        account = session.execute(select(SupplierBankAccount).where(SupplierBankAccount.supplier_id == supplier.id,
                                                                    SupplierBankAccount.active.is_(True))).scalar_one_or_none()
        if account is None:
            skipped.append({"invoice": invoice.number, "reason": "no verified bank account"})
            continue
        if account.payable_from and account.payable_from > clock.now():
            skipped.append({"invoice": invoice.number, "reason": f"bank change cooling-off until {account.payable_from.isoformat()}"})
            continue
        try:
            sod.guard(session, "PAYMENT_APPROVE", {"supplier_id": supplier.id})
        except Problem as exc:
            skipped.append({"invoice": invoice.number, "reason": exc.detail})
            continue
        if account.verified_on and (run_date - account.verified_on).days <= 30:
            audit.record(session, "INVOICE", invoice.id, "BANK_CHANGE_RECENT_ALERT", object_ref=invoice.number,
                         reason="Bank details changed within 30 days of this payment", after={"verifiedOn": account.verified_on.isoformat()})
        credit = sum(n.gross_minor for n in session.execute(select(CreditNote).where(CreditNote.invoice_id == invoice.id)).scalars())
        payment = Payment(tenant_id=invoice.tenant_id, number=next_number(session, "PAYMENT"), invoice_id=invoice.id, supplier_id=supplier.id,
                          bank_account_id=account.id, amount_minor=invoice.gross_minor - credit - (invoice.retention_minor or 0),
                          value_date=run_date, status="COMPLETED", run_ref=run_ref, approved_by=p.user_id, created_by=p.user_id)
        session.add(payment)
        session.flush()
        sod.record(session, "PAYMENT_APPROVE", {"supplier_id": supplier.id})
        SM.apply(session, invoice, "pay", extra_after={"payment": payment.number})
        invoice.payment_status = "PAID"
        message = integration.enqueue(session, target_system=integration.target_system(session, invoice.company_code), message_type="PAYMENT",
                                      idempotency_key=f"PAY|{payment.number}",
                                      object_type="INVOICE", object_id=invoice.id, object_ref=invoice.number,
                                      payload={"payment": payment.number, "invoiceErp": invoice.erp_doc_no, "amountMinor": payment.amount_minor,
                                               "companyCode": invoice.company_code, **_retention_payment_refs(session, invoice)})
        integration.process(session, message)
        link(session, "INVOICE", invoice.id, invoice.number, "PAYMENT", payment.id, payment.number, "paid_by")
        outbox.emit(session, "payment.completed", "INVOICE", invoice.id, invoice.number,
                    {"payment": payment.number, "amountMinor": payment.amount_minor, "clearingDocument": message.erp_doc_no})
        instance = _instance(session, invoice)
        workflow.step(session, instance, "F7-07", outcome=f"{run_ref}: {payment.number} {fmt_inr(payment.amount_minor)}")
        workflow.end(session, instance, "F7-09", outcome=f"paid; ERP clearing {message.erp_doc_no}; reconciled")
        paid.append({"invoice": invoice.number, "payment": payment.number, "amountMinor": payment.amount_minor, "clearing": message.erp_doc_no})
    audit.record(session, "PAYMENT_RUN", uuid.uuid5(uuid.NAMESPACE_URL, run_ref), "EXECUTED", object_ref=run_ref,
                 after={"paid": len(paid), "skipped": skipped})
    return {"run": run_ref, "paid": paid, "skipped": skipped}


# ---------------------------------------------------------------- retention (construction / subcontract orders, BP §23)
SETTLED = ("POSTED", "PAID")


def _retention_payment_refs(session: Session, invoice: Invoice) -> dict:
    """Extra PAYMENT payload: a release pays (and clears) the retention items of the source invoices; an ordinary invoice
    with retention is paid net and its retention item stays blocked in the ERP."""
    if invoice.match_type == RETENTION:
        return {"retentionRelease": True,
                "retentionItems": [{"invoice": (l.match_detail or {}).get("sourceInvoice"), "erpDocument": (l.match_detail or {}).get("erpDocument"),
                                    "amountMinor": l.net_minor} for l in _lines(session, invoice)]}
    return {"retentionWithheldMinor": invoice.retention_minor} if invoice.retention_minor else {}


def _retention_sources(session: Session, po: PurchaseOrder) -> list[Invoice]:
    ids = select(InvoiceLine.invoice_id).join(PoLine, PoLine.id == InvoiceLine.po_line_id).where(PoLine.po_id == po.id)
    return session.execute(select(Invoice).where(Invoice.id.in_(ids), func.coalesce(Invoice.match_type, "") != RETENTION,
                                                 Invoice.status != "REJECTED")
                           .order_by(Invoice.invoice_date, Invoice.created_at)).scalars().all()


def _retention_releases(session: Session, po: PurchaseOrder) -> list[Invoice]:
    return session.execute(select(Invoice).where(Invoice.po_id == po.id, Invoice.match_type == RETENTION, Invoice.status != "REJECTED")
                           .order_by(Invoice.created_at)).scalars().all()


def retention_position(session: Session, po: PurchaseOrder) -> dict:
    """Retention withheld on the PO's posted invoices, released so far and outstanding (per invoice and in total)."""
    releases = _retention_releases(session, po)
    released: dict[str, int] = {}
    for doc in releases:
        for line in _lines(session, doc):
            source = (line.match_detail or {}).get("retentionOf")
            if source:
                released[source] = released.get(source, 0) + line.net_minor
    items = []
    for inv in _retention_sources(session, po):
        amount = inv.retention_minor if inv.po_id == po.id else retention_by_po(session, inv).get(po.id, 0)
        settled = inv.status in SETTLED
        withheld = amount if settled else 0
        items.append({"invoice": inv.number, "invoiceId": str(inv.id), "status": inv.status, "erpDocument": inv.erp_doc_no,
                      "withheldMinor": withheld, "pendingMinor": 0 if settled else amount, "releasedMinor": released.get(str(inv.id), 0),
                      "outstandingMinor": withheld - released.get(str(inv.id), 0)})
    return {"po": po.number, "retentionPct": jsonable(po.retention_pct),
            "withheldMinor": sum(i["withheldMinor"] for i in items), "pendingMinor": sum(i["pendingMinor"] for i in items),
            "releasedMinor": sum(i["releasedMinor"] for i in items), "outstandingMinor": sum(i["outstandingMinor"] for i in items),
            "invoices": items,
            "releases": [{"number": d.number, "amountMinor": d.gross_minor, "releaseDate": d.invoice_date.isoformat(), "status": d.status,
                          "paymentStatus": d.payment_status, "reference": next(((l.match_detail or {}).get("reference") for l in _lines(session, d)), None)}
                         for d in releases]}


def release_retention(session: Session, po: PurchaseOrder, *, reference: str, reason: str, amount_minor: Optional[int] = None,
                      release_date: Optional[date] = None) -> Invoice:
    """Explicit retention release (e.g. at completion or after the defect-liability period): an AP document of type RETENTION
    for the released amount, allocated oldest invoice first, due on the release date. The next payment run pays it and the
    PAYMENT message clears the retention items of the source ERP documents. No GST: tax was charged on the full invoices."""
    p = principal(session)
    if not set(p.roles) & {"AP_CLERK", "FINANCE_CONTROLLER"}:
        raise Problem(403, "FORBIDDEN", "Retention is released by accounts payable or finance")
    if not po.retention_pct:
        raise rule_violation(f"{po.number} carries no retention", RETENTION)
    if not (reference or "").strip() or not (reason or "").strip():
        raise Problem(422, "REASON_REQUIRED", "Give the release reference (e.g. completion certificate) and the reason")
    position = retention_position(session, po)
    if position["pendingMinor"]:
        raise rule_violation(f"Invoices against {po.number} are still being matched or approved; post or reject them before releasing "
                             f"retention", RETENTION)
    outstanding = position["outstandingMinor"]
    amount = outstanding if amount_minor is None else int(amount_minor)
    if outstanding <= 0:
        raise rule_violation(f"No retention outstanding on {po.number}", RETENTION)
    if amount <= 0 or amount > outstanding:
        raise rule_violation(f"Release amount must be positive and at most the outstanding {fmt_inr(outstanding)}", RETENTION)
    sod.guard(session, "INVOICE_POST", {"supplier_id": po.supplier_id})
    sod.record(session, "INVOICE_POST", {"supplier_id": po.supplier_id})
    when = release_date or clock.today()
    number = f"RET-{po.number}-{len(position['releases']) + 1}"[:30]
    sources = [i for i in position["invoices"] if i["outstandingMinor"] > 0]
    doc = Invoice(tenant_id=po.tenant_id, number=number, supplier_invoice_no=number, fiscal_year=clock.fiscal_year(when),
                  company_code=po.company_code, supplier_id=po.supplier_id, po_id=po.id, invoice_date=when, channel=RETENTION,
                  currency=po.currency or "INR", net_minor=amount, tax_minor=0, gross_minor=amount, retention_minor=0, status="POSTED",
                  match_type=RETENTION, payment_block=False, due_date=when, approved_by=p.user_id, posted_at=clock.now(),
                  erp_doc_no=sources[-1]["erpDocument"] if sources else None, rule_set_version=RETENTION, created_by=p.user_id)
    session.add(doc)
    session.flush()
    remaining, allocated = amount, []
    for index, item in enumerate(sources, start=1):
        take = min(remaining, item["outstandingMinor"])
        if take <= 0:
            break
        session.add(InvoiceLine(tenant_id=doc.tenant_id, invoice_id=doc.id, line_no=index * 10, po_line_id=None,
                                description=f"Retention release – {item['invoice']}"[:200], qty=Decimal(1), unit_price_minor=take, net_minor=take,
                                hsn_code=None, gst_rate=Decimal(0), tax_minor=0, match_status="OK",
                                match_detail={"retentionOf": item["invoiceId"], "sourceInvoice": item["invoice"],
                                              "erpDocument": item["erpDocument"], "withheldMinor": item["withheldMinor"], "reference": reference},
                                created_by=p.user_id))
        link(session, "INVOICE", uuid.UUID(item["invoiceId"]), item["invoice"], "INVOICE", doc.id, doc.number, "retention_released_by")
        allocated.append({"invoice": item["invoice"], "amountMinor": take})
        remaining -= take
    link(session, "PURCHASE_ORDER", po.id, po.number, "INVOICE", doc.id, doc.number, "retention_released_by")
    session.flush()
    after = {"po": po.number, "amountMinor": amount, "outstandingAfterMinor": outstanding - amount, "allocation": allocated,
             "reference": reference, "releaseDate": when.isoformat()}
    audit.record(session, "INVOICE", doc.id, "RETENTION_RELEASED", object_ref=doc.number, after=after, reason=reason)
    audit.record(session, "PURCHASE_ORDER", po.id, "RETENTION_RELEASED", object_ref=po.number, after={**after, "document": doc.number},
                 reason=reason)
    instance = workflow.start(session, PROCESS, "INVOICE", doc.id, doc.number, {"retentionRelease": po.number})
    workflow.step(session, instance, "F7-01", outcome=f"retention release {fmt_inr(amount)} on {po.number}: {reference}")
    workflow.wait(session, instance, "F7-07", outcome=f"retention payment block lifted; due {when.isoformat()}")
    return doc


def settle_consignment(session: Session, *, supplier: str, period_to: date, company_code: str = "1000",
                       reference: Optional[str] = None) -> Invoice:
    """P08 consignment settlement (self-billing, ERS): one AP document for everything withdrawn from the supplier's consignment
    stock up to ``period_to`` and not yet settled, priced at the consignment PO line with its GST rate and HSN. It runs the
    duplicate check and the ERS match (settled ≤ withdrawn) like any invoice; accounts payable then approves and posts it.
    ``reference`` records the supplier's GST tax invoice for the withdrawn quantity where the supplier issues one."""
    from app.pic.services.receiving import consignment_withdrawn
    p = principal(session)
    if not set(p.roles) & {"AP_CLERK", "FINANCE_CONTROLLER"}:
        raise Problem(403, "FORBIDDEN", "Consignment settlement runs in accounts payable or finance")
    supplier_row = supplier_ref(session, supplier)
    candidates = session.execute(select(PoLine, PurchaseOrder).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(
        PurchaseOrder.supplier_id == supplier_row.id, PurchaseOrder.company_code == company_code, PoLine.ers.is_(True))
        .order_by(PurchaseOrder.number, PoLine.line_no)).all()
    until = clock.at_ist(period_to + timedelta(days=1), 0, 0)
    withdrawn = consignment_withdrawn(session, [l.id for l, _ in candidates], until=until)
    pending: dict[uuid.UUID, Decimal] = {}
    for inv_line, inv in session.execute(select(InvoiceLine, Invoice).join(Invoice, Invoice.id == InvoiceLine.invoice_id).where(
            InvoiceLine.po_line_id.in_([l.id for l, _ in candidates]), Invoice.status.notin_(("POSTED", "PAID", "REJECTED")))).all():
        pending[inv_line.po_line_id] = pending.get(inv_line.po_line_id, Decimal(0)) + inv_line.qty
    open_lines = [(l, po, withdrawn.get(l.id, Decimal(0)) - l.invoiced_qty - pending.get(l.id, Decimal(0))) for l, po in candidates]
    open_lines = [(l, po, qty) for l, po, qty in open_lines if qty > 0]
    if not open_lines:
        raise rule_violation(f"Nothing to settle: no unsettled consignment withdrawals from {supplier_row.code} up to {period_to.isoformat()}", "P08")
    fiscal_year = clock.fiscal_year(period_to)
    base = f"ERS-{supplier_row.code}-{period_to:%Y%m}"
    taken = {n for (n,) in session.execute(select(Invoice.number).where(Invoice.number.like(f"{base}%"))).all()}
    number = base if base not in taken else next(f"{base}-{i}" for i in range(2, 100) if f"{base}-{i}" not in taken)
    invoice = Invoice(tenant_id=current_tenant(session), number=number, supplier_invoice_no=number, fiscal_year=fiscal_year,
                      company_code=company_code, supplier_id=supplier_row.id, po_id=open_lines[0][1].id if len({po.id for _, po, _ in open_lines}) == 1 else None,
                      invoice_date=period_to, channel=ERS, irn=None, currency="INR", net_minor=0, tax_minor=0, gross_minor=0, retention_minor=0,
                      status="CAPTURED", created_by=p.user_id)
    session.add(invoice)
    session.flush()
    net_total = tax_total = 0
    for index, (po_line, po, qty) in enumerate(open_lines, start=1):
        net = line_amount(qty, po_line.unit_price_minor)
        tax = tax_amount(net, po_line.gst_rate)
        session.add(InvoiceLine(tenant_id=invoice.tenant_id, invoice_id=invoice.id, line_no=index * 10, po_line_id=po_line.id,
                                description=f"Consignment withdrawals to {period_to.isoformat()} – {po_line.description}"[:200], qty=qty,
                                unit_price_minor=po_line.unit_price_minor, net_minor=net, hsn_code=po_line.hsn_code, gst_rate=po_line.gst_rate,
                                tax_minor=tax, created_by=p.user_id))
        net_total += net
        tax_total += tax
        link(session, "PURCHASE_ORDER", po.id, po.number, "INVOICE", invoice.id, invoice.number, "settled_by_ers",
             from_line=po_line.line_no, to_line=index * 10)
    invoice.net_minor, invoice.tax_minor, invoice.gross_minor = net_total, tax_total, net_total + tax_total
    session.flush()
    instance = workflow.start(session, PROCESS, "INVOICE", invoice.id, invoice.number, {"ers": supplier_row.code})
    outbox.emit(session, "invoice.captured", "INVOICE", invoice.id, invoice.number,
                {"supplier": supplier_row.code, "grossMinor": invoice.gross_minor, "channel": ERS})
    audit.record(session, "INVOICE", invoice.id, "CAPTURED", object_ref=invoice.number, rule_set_version="P08",
                 after={"supplier": supplier_row.code, "grossMinor": invoice.gross_minor, "channel": ERS, "periodTo": period_to.isoformat(),
                        "supplierTaxInvoice": reference, "lines": [{"po": po.number, "line": l.line_no, "qty": jsonable(q)} for l, po, q in open_lines]})
    _duplicate_check(session, invoice, instance)
    return invoice


def grir(session: Session) -> list[dict]:
    """Received-not-invoiced accruals by PO line (consignment: withdrawn-not-settled, the only quantity that is a liability)."""
    from app.pic.services.receiving import consignment_withdrawn
    rows = []
    found = session.execute(select(PoLine, PurchaseOrder).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(
        PoLine.accepted_qty > PoLine.invoiced_qty)).all()
    withdrawn = consignment_withdrawn(session, [line.id for line, _ in found if line.ers])
    for line, po in found:
        qty = (withdrawn.get(line.id, Decimal(0)) if line.ers else line.accepted_qty) - line.invoiced_qty
        if qty <= 0:
            continue
        rows.append({"po": po.number, "line": line.line_no, "qty": str(qty), "accrualMinor": line_amount(qty, line.unit_price_minor)})
    return rows


# ---------------------------------------------------------------- INV-03 posting & reconciliation, INV-04 payables insights
def reconcile(session: Session, company_code: str, target_system: str = "SAP_S4") -> dict:
    """Nightly reconciliation (§12.2 step 5): platform postings vs ERP documents by count, amount and status."""
    from app.pic.models import ErpDocument, ReconciliationItem, ReconciliationRun
    doc_type = integration.DOC_TYPES["SUPPLIER_INVOICE"][0]
    invoices = session.execute(select(Invoice).where(Invoice.company_code == company_code, Invoice.posting_key.is_not(None),
                                                     Invoice.status.in_(("POSTED", "PAID")))).scalars().all()
    docs = {d.external_ref: d for d in session.execute(select(ErpDocument).where(ErpDocument.system == target_system, ErpDocument.doc_type == doc_type,
                                                                                ErpDocument.company_code == company_code)).scalars()}
    memos: dict[str, int] = {}  # ERP credit memos (credit notes received after posting), per invoice posting key
    for memo in session.execute(select(ErpDocument).where(ErpDocument.system == target_system,
                                                          ErpDocument.doc_type == integration.DOC_TYPES["SUPPLIER_CREDIT_MEMO"][0],
                                                          ErpDocument.company_code == company_code)).scalars():
        key = memo.external_ref.split("|CN|", 1)[0]
        memos[key] = memos.get(key, 0) + (memo.amount_minor or 0)
    erp_amount = {key: (d.amount_minor or 0) - memos.get(key, 0) for key, d in docs.items()}
    credits = {}
    for note in session.execute(select(CreditNote).where(CreditNote.invoice_id.in_([i.id for i in invoices]))).scalars():
        credits[note.invoice_id] = credits.get(note.invoice_id, 0) + note.gross_minor
    posted = {i.id: i.gross_minor - credits.get(i.id, 0) for i in invoices}  # the ERP receives gross net of credit notes
    p = principal(session)
    run = ReconciliationRun(tenant_id=current_tenant(session), number=next_number(session, "RECONCILIATION"), target_system=target_system,
                            company_code=company_code, as_of=clock.now(), platform_count=len(invoices), erp_count=len(docs),
                            platform_minor=sum(posted.values()), erp_minor=sum(erp_amount.values()),
                            differences=0, created_by=p.user_id)
    session.add(run)
    session.flush()
    items, seen = [], set()
    for invoice in invoices:
        doc = docs.get(invoice.posting_key)
        seen.add(invoice.posting_key)
        if doc is None:
            items.append(("MISSING_IN_ERP", invoice.number, invoice.erp_doc_no, posted[invoice.id], None))
        elif erp_amount[invoice.posting_key] != posted[invoice.id]:
            items.append(("AMOUNT_MISMATCH", invoice.number, doc.doc_no, posted[invoice.id], erp_amount[invoice.posting_key]))
        elif invoice.erp_doc_no != doc.doc_no:
            items.append(("DOCUMENT_MISMATCH", invoice.number, doc.doc_no, posted[invoice.id], doc.amount_minor))
    for key, doc in docs.items():
        if key not in seen:
            items.append(("MISSING_IN_PLATFORM", key, doc.doc_no, None, doc.amount_minor))
    for kind, ref, doc_no, platform_minor, erp_minor in items:
        session.add(ReconciliationItem(tenant_id=run.tenant_id, run_id=run.id, kind=kind, object_type="INVOICE", object_ref=ref, erp_doc_no=doc_no,
                                       platform_minor=platform_minor, erp_minor=erp_minor, created_by=p.user_id))
    run.differences = len(items)
    session.flush()
    audit.record(session, "RECONCILIATION_RUN", run.id, "EXECUTED", object_ref=run.number,
                 after={"companyCode": company_code, "platform": run.platform_count, "erp": run.erp_count, "differences": run.differences})
    return reconciliation_view(session, run)


def reconciliation_view(session: Session, run) -> dict:
    from app.pic.models import ReconciliationItem
    items = session.execute(select(ReconciliationItem).where(ReconciliationItem.run_id == run.id)).scalars().all()
    return {"number": run.number, "system": run.target_system, "companyCode": run.company_code, "asOf": run.as_of.isoformat(),
            "platformCount": run.platform_count, "erpCount": run.erp_count, "platformMinor": run.platform_minor, "erpMinor": run.erp_minor,
            "differences": run.differences,
            "items": [{"id": str(i.id), "kind": i.kind, "ref": i.object_ref, "erpDocNo": i.erp_doc_no, "platformMinor": i.platform_minor,
                       "erpMinor": i.erp_minor, "status": i.status, "resolution": i.resolution} for i in items]}


def resolve_reconciliation_item(session: Session, item, resolution: str):
    p = principal(session)
    if not set(p.roles) & {"AP_CLERK", "FINANCE_CONTROLLER"}:
        raise Problem(403, "FORBIDDEN", "Reconciliation items are resolved by accounts payable or finance")
    if item.status != "OPEN":
        raise Problem(409, "ILLEGAL_TRANSITION", "Item already resolved")
    item.status, item.resolution, item.resolved_by = "RESOLVED", resolution, p.user_id
    audit.record(session, "RECONCILIATION_RUN", item.run_id, "ITEM_RESOLVED", object_ref=item.object_ref, after={"kind": item.kind}, reason=resolution)
    return item


def _discount_terms(terms: Optional[str]) -> Optional[tuple[Decimal, int]]:
    """'2/10 N45' → (2%, 10 days)."""
    import re
    m = re.match(r"\s*(\d+(?:\.\d+)?)/(\d+)", terms or "")
    return (Decimal(m.group(1)), int(m.group(2))) if m else None


def insights(session: Session) -> dict:
    """INV-04: due-date ladder, discount capture, DPO, first-pass match and GR/IR ageing."""
    today = clock.today()
    invoices = session.execute(select(Invoice)).scalars().all()
    suppliers = {s.id: s for s in session.execute(select(Supplier)).scalars()}
    ladder = {"overdue": 0, "0-7": 0, "8-30": 0, "31-60": 0, "60+": 0}
    for i in invoices:
        if i.status == "POSTED" and i.payment_status == "UNPAID" and i.due_date:
            days = (i.due_date - today).days
            bucket = "overdue" if days < 0 else "0-7" if days <= 7 else "8-30" if days <= 30 else "31-60" if days <= 60 else "60+"
            ladder[bucket] += i.gross_minor
    payments = session.execute(select(Payment, Invoice).join(Invoice, Invoice.id == Payment.invoice_id).where(Payment.status == "COMPLETED")).all()
    weighted = sum(Decimal((pay.value_date - inv.invoice_date).days) * pay.amount_minor for pay, inv in payments)
    paid_total = sum(pay.amount_minor for pay, _ in payments)
    available = captured = 0
    for pay, inv in payments:
        terms = _discount_terms(suppliers[inv.supplier_id].payment_terms if inv.supplier_id in suppliers else None)
        if terms:
            value = int(Decimal(inv.gross_minor) * terms[0] / 100)
            available += value
            if (pay.value_date - inv.invoice_date).days <= terms[1]:
                captured += value
    matched = [i for i in invoices if i.first_pass_matched is not None]
    accruals = []
    from app.pic.services.receiving import consignment_withdrawn
    open_lines = session.execute(select(PoLine, PurchaseOrder).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(
        PoLine.accepted_qty > PoLine.invoiced_qty)).all()
    withdrawn = consignment_withdrawn(session, [line.id for line, _ in open_lines if line.ers])  # consignment: liability = withdrawn
    for line, po in open_lines:
        accrual_qty = (withdrawn.get(line.id, Decimal(0)) if line.ers else line.accepted_qty) - line.invoiced_qty
        if accrual_qty <= 0:
            continue
        age = max(0, (today - (po.released_at.date() if po.released_at else po.created_at.date())).days)
        accruals.append({"po": po.number, "line": line.line_no, "supplier": suppliers[po.supplier_id].code,
                         "accrualMinor": line_amount(accrual_qty, line.unit_price_minor), "ageDays": age,
                         "bucket": "0-30" if age <= 30 else "31-90" if age <= 90 else "90+"})
    ageing = {b: sum(a["accrualMinor"] for a in accruals if a["bucket"] == b) for b in ("0-30", "31-90", "90+")}
    return {"dueLadderMinor": ladder,
            "dpoDays": str((weighted / paid_total).quantize(Decimal("0.1"))) if paid_total else None,
            "discountAvailableMinor": available, "discountCapturedMinor": captured,
            "discountCapturePct": f"{captured * 100 / available:.1f}" if available else None,
            "discountNote": None if available else "No supplier has early-payment discount terms (e.g. 2/10 N45)",
            "firstPassMatchPct": f"{sum(1 for i in matched if i.first_pass_matched) * 100 / len(matched):.1f}" if matched else None,
            "duplicatesPrevented": session.execute(select(func.count()).select_from(InvoiceException).where(InvoiceException.type == "DUPLICATE")).scalar(),
            "grirAgeingMinor": ageing, "grir": sorted(accruals, key=lambda a: -a["ageDays"])}
