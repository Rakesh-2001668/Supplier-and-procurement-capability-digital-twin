"""Read models returned by the API: header, lines, process path, lineage."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import (
    Asn, AsnLine, AwardDecision, AwardScenario, Bid, Clause, Contract, ContractLine, CreditNote, Criterion, EventLine, GoodsReceipt, GrLine,
    InspectionLot, Invitee, Invoice, InvoiceException, InvoiceLine, Material, MaterialRequest, MrpException, MrpRun, Payment,
    PlannedOrder, PoLine, PrLine, PriceValidity, PurchaseOrder, Requisition, ReturnDelivery, ServiceEntry, SesLine, Signature,
    SourcingEvent, Supplier,
)
from app.pic.platform import workflow
from app.pic.platform.core import lineage
from app.pic.platform.serialize import row, rows


def _process(session: Session, business_type: str, obj) -> dict | None:
    instance = workflow.find(session, business_type, obj.id)
    return workflow.history(session, instance) if instance else None


def _supplier(session: Session, supplier_id) -> dict:
    s = session.get(Supplier, supplier_id)
    return {"id": str(s.id), "code": s.code, "name": s.legal_name}


def requisition(session: Session, pr: Requisition) -> dict:
    lines = session.execute(select(PrLine).where(PrLine.requisition_id == pr.id).order_by(PrLine.line_no)).scalars().all()
    return row(pr, extra={"lines": [row(l, extra={"requisition": pr.number}) for l in lines], "process": _process(session, "REQUISITION", pr),
                          "lineage": lineage(session, "REQUISITION", pr.id)})


def mrp_run(session: Session, run: MrpRun) -> dict:
    orders = session.execute(select(PlannedOrder).where(PlannedOrder.mrp_run_id == run.id)).scalars().all()
    exceptions = session.execute(select(MrpException).where(MrpException.mrp_run_id == run.id)).scalars().all()
    materials = {m.id: m.number for m in session.execute(select(Material)).scalars()}
    prs = {r.id: r.number for r in session.execute(select(Requisition).where(
        Requisition.id.in_([o.requisition_id for o in orders if o.requisition_id]))).scalars()}
    return row(run, extra={
        "plannedOrders": [row(o, extra={"material": materials.get(o.material_id), "requisition": prs.get(o.requisition_id)}) for o in orders],
        "exceptions": [row(e, extra={"material": materials.get(e.material_id)}) for e in exceptions],
        "process": _process(session, "MRP_RUN", run)})


def material_request(session: Session, request: MaterialRequest) -> dict:
    from app.pic.platform import rules
    number = lambda mid: session.get(Material, mid).number if mid else None  # noqa: E731
    source = session.get(Requisition, request.source_pr_id) if request.source_pr_id else None
    try:
        thresholds = rules.resolve(session, "MDM-DUP", category=request.category).body
    except Exception:
        thresholds = {}
    return row(request, extra={"material": number(request.material_id), "mergedIntoMaterial": number(request.merged_into_material_id),
                               "sourceRequisition": source.number if source else None,
                               "thresholds": {"blockAt": thresholds.get("blockAt"), "warnAt": thresholds.get("warnAt")},
                               "process": _process(session, "MATERIAL_REQUEST", request),
                               "lineage": lineage(session, "MATERIAL_REQUEST", request.id)})


def sourcing_event(session: Session, event: SourcingEvent) -> dict:
    lines = session.execute(select(EventLine).where(EventLine.event_id == event.id)).scalars().all()
    criteria = session.execute(select(Criterion).where(Criterion.event_id == event.id)).scalars().all()
    invitees = session.execute(select(Invitee).where(Invitee.event_id == event.id)).scalars().all()
    bids = session.execute(select(Bid).where(Bid.event_id == event.id)).scalars().all()
    scenarios = session.execute(select(AwardScenario).where(AwardScenario.event_id == event.id)).scalars().all()
    decisions = session.execute(select(AwardDecision).where(AwardDecision.event_id == event.id)).scalars().all()
    pr_numbers = {r.id: r.number for r in session.execute(select(Requisition).where(
        Requisition.id.in_([l.requisition_id for l in lines if l.requisition_id]))).scalars()}
    return row(event, extra={
        "lines": [row(l, extra={"requisition": pr_numbers.get(l.requisition_id)}) for l in lines], "criteria": rows(criteria),
        "invitees": [{**_supplier(session, i.supplier_id), "categoryStatus": i.category_status, "waiver": i.waiver_reason} for i in invitees],
        # Only metadata is shown for bids; commercial content is in the evaluation matrix after close.
        "bids": [{"supplier": _supplier(session, b.supplier_id)["code"], "round": b.round, "status": b.status,
                  "submittedAt": b.submitted_at.isoformat(), "hash": b.payload_hash} for b in bids],
        "scenarios": rows(scenarios), "awardDecisions": rows(decisions),
        "process": _process(session, "SOURCING_EVENT", event), "lineage": lineage(session, "SOURCING_EVENT", event.id),
    })


def contract(session: Session, c: Contract) -> dict:
    lines = session.execute(select(ContractLine).where(ContractLine.contract_id == c.id)).scalars().all()
    validities = session.execute(select(PriceValidity).where(PriceValidity.contract_line_id.in_([l.id for l in lines]))
                                 .order_by(PriceValidity.valid_from)).scalars().all()
    clauses = session.execute(select(Clause).where(Clause.contract_id == c.id)).scalars().all()
    signatures = session.execute(select(Signature).where(Signature.contract_id == c.id)).scalars().all()
    return row(c, extra={"supplier": _supplier(session, c.supplier_id), "lines": rows(lines), "priceValidity": rows(validities),
                         "clauses": rows(clauses),
                         "signatures": [row(x, extra={"documentHash": x.document_hash}) for x in signatures], "process": _process(session, "CONTRACT", c),
                         "lineage": lineage(session, "CONTRACT", c.id)})


def purchase_order(session: Session, po: PurchaseOrder) -> dict:
    from app.pic.services.order import lineage_refs
    lines = session.execute(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no)).scalars().all()
    return row(po, extra={"supplier": _supplier(session, po.supplier_id), "lines": rows(lines),
                          "validation": {"riskScore": po.risk_score, "touchless": po.touchless, "factors": po.risk_factors,
                                         "reasons": po.touchless_reasons},
                          "lineageChain": lineage_refs(session, po), "lineage": lineage(session, "PURCHASE_ORDER", po.id),
                          "process": _process(session, "PURCHASE_ORDER", po)})


def asn(session: Session, a: Asn) -> dict:
    lines = session.execute(select(AsnLine).where(AsnLine.asn_id == a.id)).scalars().all()
    return row(a, extra={"lines": rows(lines)})


def goods_receipt(session: Session, gr: GoodsReceipt) -> dict:
    lines = session.execute(select(GrLine).where(GrLine.gr_id == gr.id)).scalars().all()
    po = session.get(PurchaseOrder, gr.po_id)
    asn_row = session.get(Asn, gr.asn_id) if gr.asn_id else None
    po_lines = {pl.id: pl for pl in session.execute(select(PoLine).where(PoLine.po_id == gr.po_id)).scalars()}
    lots = session.execute(select(InspectionLot).where(InspectionLot.gr_id == gr.id)).scalars().all()
    returns = session.execute(select(ReturnDelivery).where(ReturnDelivery.gr_id == gr.id)).scalars().all()
    return row(gr, extra={"po": po.number, "asn": asn_row.number if asn_row else None, "supplier": _supplier(session, po.supplier_id),
                          "lines": [row(x, extra={"poLine": po_lines[x.po_line_id].line_no, "description": po_lines[x.po_line_id].description,
                                                  "uom": po_lines[x.po_line_id].uom}) for x in lines],
                          "inspectionLots": rows(lots),
                          "returns": [row(r, extra={"poLine": po_lines[r.po_line_id].line_no}) for r in returns],
                          "process": _process(session, "GOODS_RECEIPT", gr), "lineage": lineage(session, "GOODS_RECEIPT", gr.id)})


def service_entry(session: Session, ses: ServiceEntry) -> dict:
    lines = session.execute(select(SesLine).where(SesLine.ses_id == ses.id)).scalars().all()
    return row(ses, extra={"lines": rows(lines), "process": _process(session, "SERVICE_ENTRY", ses)})


def invoice(session: Session, inv: Invoice) -> dict:
    lines = session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id).order_by(InvoiceLine.line_no)).scalars().all()
    exceptions = session.execute(select(InvoiceException).where(InvoiceException.invoice_id == inv.id)).scalars().all()
    notes = session.execute(select(CreditNote).where(CreditNote.invoice_id == inv.id)).scalars().all()
    payments = session.execute(select(Payment).where(Payment.invoice_id == inv.id)).scalars().all()
    po_refs = {pl.id: (pl.line_no, number) for pl, number in session.execute(
        select(PoLine, PurchaseOrder.number).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(
            PoLine.id.in_([x.po_line_id for x in lines if x.po_line_id]))).all()}
    return row(inv, extra={"supplier": _supplier(session, inv.supplier_id),
                           "lines": [row(x, extra={"po": po_refs.get(x.po_line_id, (None, None))[1],
                                                   "poLine": po_refs.get(x.po_line_id, (None, None))[0]}) for x in lines], "exceptions": rows(exceptions),
                           "creditNotes": rows(notes), "payments": rows(payments), "process": _process(session, "INVOICE", inv),
                           "lineage": lineage(session, "INVOICE", inv.id)})


def material(session: Session, m: Material) -> dict:
    return row(m)
