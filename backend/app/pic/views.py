"""Read models returned by the API: header, lines, process path, lineage."""
from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.orm import Session

from app.pic.models import (
    Asn, AsnLine, AwardDecision, AwardScenario, Bid, Clause, Contract, ContractLine, CreditNote, Criterion, EventLine, GoodsReceipt, GrLine,
    InspectionLot, Invitee, Invoice, InvoiceException, InvoiceLine, Material, MaterialRequest, MrpException, MrpRun, Payment,
    PlannedOrder, PoLine, PrLine, PriceValidity, PurchaseOrder, Requisition, ReturnDelivery, ServiceEntry, SesLine, Signature,
    SourcingEvent, Supplier,
)
from app.pic.platform import workflow
from app.pic.platform.core import lineage
from app.pic.platform.serialize import column_keys, jsonable, row, rows


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


def _column_rows(session: Session, model, *where) -> list[tuple]:
    """(raw row, ``row()`` dict) per match, from a column select: the same keys and values as ``row`` on the ORM objects,
    without building them (an MRP run of 50,000 materials returns ~120,000 planned orders)."""
    keys = column_keys(sa_inspect(model))
    return [(r, {k: jsonable(v) for k, v in zip(keys, r)})
            for r in session.execute(select(*(getattr(model, k) for k in keys)).where(*where))]


MRP_DETAIL_LIMIT = 1000  # a run with more planned orders + exceptions than this answers with a summary and links to paged reads


def mrp_run(session: Session, run: MrpRun, detail: str = "auto") -> dict:
    """The run with its planned orders and exceptions. ``detail`` full | summary | auto (full up to MRP_DETAIL_LIMIT rows): a
    50,000-material run has ~120,000 planned orders, so it returns the header, counts and the paged read URLs instead; the
    per-material netting trace (``results``) is then read through /mrp/runs/{ref}/results."""
    if detail == "auto":
        detail = "full" if (run.planned_orders_created or 0) + (run.exceptions_raised or 0) <= MRP_DETAIL_LIMIT else "summary"
    if detail == "summary":
        out = row(run, only=[k for k in column_keys(sa_inspect(MrpRun)) if k != "results"], extra={"process": _process(session, "MRP_RUN", run)})
        out["resultsCount"] = len(run.results or [])
        base = f"/v1/mrp/runs/{run.number}"
        out.update({"detail": "summary", "plannedOrdersUrl": f"{base}/planned-orders", "exceptionsUrl": f"{base}/exceptions",
                    "resultsUrl": f"{base}/results"})
        return out
    orders = _column_rows(session, PlannedOrder, PlannedOrder.mrp_run_id == run.id)
    exceptions = _column_rows(session, MrpException, MrpException.mrp_run_id == run.id)
    materials = dict(session.execute(select(Material.id, Material.number)).all())  # numbers only: no full rows for a 50k-material run
    prs = {r.id: r.number for r in session.execute(select(Requisition).where(
        Requisition.id.in_([o.requisition_id for o, _ in orders if o.requisition_id]))).scalars()}
    for o, d in orders:  # in place: the lists are already JSON-safe, so they are not copied again by row(extra=...)
        d["material"], d["requisition"] = materials.get(o.material_id), prs.get(o.requisition_id)
    for e, d in exceptions:
        d["material"] = materials.get(e.material_id)
    out = row(run, extra={"process": _process(session, "MRP_RUN", run)})
    process = out.pop("process")  # key order as before: columns, plannedOrders, exceptions, process
    out.update({"plannedOrders": [d for _, d in orders], "exceptions": [d for _, d in exceptions], "process": process, "detail": "full"})
    return out


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
        "cancellation": _cancellation(session, event),
    })


def _cancellation(session: Session, event: SourcingEvent):
    """When and why a cancelled event was cancelled (from its audit trail); shown to invited suppliers too."""
    if event.status != "CANCELLED":
        return None
    from app.pic.models import AuditEvent
    entry = session.execute(select(AuditEvent).where(AuditEvent.object_type == "SOURCING_EVENT", AuditEvent.object_id == event.id,
                                                     AuditEvent.action == "CANCEL").order_by(AuditEvent.seq.desc()).limit(1)).scalar_one_or_none()
    if entry is None:
        return {"reason": None, "at": None, "from": None}
    return {"reason": entry.reason, "at": entry.ts.isoformat(), "from": (entry.before or {}).get("status")}


def contract(session: Session, c: Contract) -> dict:
    lines = session.execute(select(ContractLine).where(ContractLine.contract_id == c.id)).scalars().all()
    validities = session.execute(select(PriceValidity).where(PriceValidity.contract_line_id.in_([l.id for l in lines]))
                                 .order_by(PriceValidity.valid_from)).scalars().all()
    clauses = session.execute(select(Clause).where(Clause.contract_id == c.id)).scalars().all()
    signatures = session.execute(select(Signature).where(Signature.contract_id == c.id)).scalars().all()
    from app.pic.services.contract import DEMO_SIGNATURE_LABEL, signature_provider
    sig_rows = [row(x, extra={"documentHash": x.document_hash, "provider": signature_provider(x.envelope_ref),
                              "demoSignature": signature_provider(x.envelope_ref) == "MOCK",
                              "label": DEMO_SIGNATURE_LABEL if signature_provider(x.envelope_ref) == "MOCK" else None}) for x in signatures]
    return row(c, extra={"supplier": _supplier(session, c.supplier_id), "lines": rows(lines), "priceValidity": rows(validities),
                         "clauses": rows(clauses), "pendingRedlines": _pending_redlines(session, c),
                         "signatures": sig_rows, "demoSignature": any(x["demoSignature"] for x in sig_rows),
                         "process": _process(session, "CONTRACT", c),
                         "lineage": lineage(session, "CONTRACT", c.id)})


def _pending_redlines(session: Session, c: Contract) -> list[dict]:
    """Supplier redlines waiting for the contract manager's review (accept with a position, or restore the text)."""
    from app.pic.services.contract import pending_redlines
    return list(pending_redlines(session, c).values())


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
                           "debitNotes": _debit_notes(session, inv),
                           "lineage": lineage(session, "INVOICE", inv.id)})


def _debit_notes(session: Session, inv: Invoice) -> list[dict]:
    from app.pic.services import debit_notes
    return [debit_notes.view(session, n) for n in debit_notes.notes_of(session, inv)]


def material(session: Session, m: Material) -> dict:
    return row(m)


# ---------------------------------------------------------------- inventory documents (services/inventory.py)
def _task_views(session: Session, kind: str, object_id) -> list[dict]:
    from app.pic.models import Task
    return [{"role": t.candidate_role, "sequence": t.sequence, "status": t.status, "decision": t.decision, "comment": t.comment,
             "dueAt": t.due_at.isoformat() if t.due_at else None, "decidedAt": t.completed_at.isoformat() if t.completed_at else None,
             "decidedBy": str(t.completed_by) if t.completed_by else None, "taskId": str(t.id)}
            for t in session.execute(select(Task).where(Task.kind == kind, Task.object_id == object_id).order_by(Task.created_at, Task.sequence)).scalars()]


def stock_posting_summary(posting) -> dict:
    return {"id": str(posting.id), "number": posting.number, "type": posting.posting_type, "status": posting.status, "plant": posting.plant,
            "companyCode": posting.company_code, "postingDate": posting.posting_date.isoformat(), "reasonCode": posting.reason_code,
            "reason": posting.reason, "totalValueMinor": posting.total_value_minor, "autoPosted": posting.auto_posted,
            "erpDocument": posting.erp_doc_no, "createdAt": posting.created_at.isoformat() if posting.created_at else None,
            "postedAt": posting.posted_at.isoformat() if posting.posted_at else None, "rowVersion": posting.row_version}


def stock_posting(session: Session, posting) -> dict:
    from app.pic.models import StockMovement, StockPostingLine
    from app.pic.services import inventory, stock_ledger
    lines = session.execute(select(StockPostingLine).where(StockPostingLine.posting_id == posting.id).order_by(StockPostingLine.line_no)).scalars().all()
    materials = {m.id: m for m in session.execute(select(Material).where(Material.id.in_([l.material_id for l in lines] or [posting.id]))).scalars()}
    users = inventory._user_names(session, [posting.created_by, posting.submitted_by, posting.approved_by, posting.posted_by])  # noqa: SLF001
    warnings = []
    if posting.status in ("DRAFT", "SUBMITTED", "APPROVED"):
        for l in lines:
            if l.from_stock_type == "UNRESTRICTED":
                free = stock_ledger.on_hand(session, l.material_id, l.from_plant, l.from_storage_location) - stock_ledger.reserved_open(
                    session, l.material_id, l.from_plant, l.from_storage_location)
                if l.qty > free:
                    warnings.append({"code": "RESERVED_STOCK", "line": l.line_no, "material": materials[l.material_id].number,
                                     "detail": f"{l.qty} posted, but only {free} of the unrestricted stock is not reserved: open reservations will be short"})
    movements = []
    if posting.status == "POSTED":
        movements = [{"movementType": m.movement_type, "plant": m.plant, "storageLocation": m.storage_location, "stockType": m.stock_type, "batch": m.batch,
                      "qty": jsonable(m.qty), "valueMinor": m.value_minor, "material": materials[m.material_id].number if m.material_id in materials else None}
                     for m in session.execute(select(StockMovement).where(StockMovement.reference_type == "STOCK_POSTING", StockMovement.reference_id == posting.id)
                                              .order_by(StockMovement.created_at, StockMovement.id)).scalars()]
    return {**stock_posting_summary(posting), "rule": posting.rule_set_version, "decisionComment": posting.decision_comment,
            "createdBy": users.get(posting.created_by), "submittedBy": users.get(posting.submitted_by), "approvedBy": users.get(posting.approved_by),
            "postedBy": users.get(posting.posted_by), "submittedAt": posting.submitted_at.isoformat() if posting.submitted_at else None,
            "approvedAt": posting.approved_at.isoformat() if posting.approved_at else None,
            "lines": [{"lineNo": l.line_no, "material": materials[l.material_id].number, "description": materials[l.material_id].description,
                       "uom": materials[l.material_id].base_uom, "batch": l.batch, "qty": jsonable(l.qty), "fromPlant": l.from_plant,
                       "fromStorageLocation": l.from_storage_location, "fromStockType": l.from_stock_type, "toPlant": l.to_plant,
                       "toStorageLocation": l.to_storage_location, "toStockType": l.to_stock_type, "movementType": l.movement_type,
                       "unitPriceMinor": l.unit_price_minor, "valueMinor": l.value_minor} for l in lines],
            "approvals": _task_views(session, "STOCK_POSTING_APPROVAL", posting.id), "movements": movements, "warnings": warnings}


def physical_inventory_summary(inv, reveal: bool) -> dict:
    out = {"id": str(inv.id), "number": inv.number, "status": inv.status, "plant": inv.plant, "companyCode": inv.company_code,
           "storageLocation": inv.storage_location, "materialGroup": inv.material_group, "scope": inv.scope, "description": inv.description,
           "plannedDate": inv.planned_date.isoformat() if inv.planned_date else None, "frozenAt": inv.frozen_at.isoformat(), "lineCount": inv.line_count,
           "erpDocument": inv.erp_doc_no, "createdAt": inv.created_at.isoformat() if inv.created_at else None,
           "postedAt": inv.posted_at.isoformat() if inv.posted_at else None, "rowVersion": inv.row_version, "blind": not reveal}
    if reveal:
        out.update(gainMinor=inv.gain_minor, lossMinor=inv.loss_minor, accuracyPct=str(inv.accuracy_pct) if inv.accuracy_pct is not None else None)
    return out


def counts_revealed(session: Session, lines) -> bool:
    """Approvers and controllers see the book quantities and differences of a count; a counter (anyone who entered a count on the document) and
    every user without the approval scope never does: the count is blind."""
    p = session.info["principal"]
    counted_by = {u for l in lines for u in (l.counted_by, l.recounted_by) if u}
    return "inventory:approve" in p.scopes and p.user_id not in counted_by


def physical_inventory(session: Session, inv, reveal: bool | None = None) -> dict:
    from app.pic.services import inventory
    lines = inventory.count_lines(session, inv)
    if reveal is None:
        reveal = counts_revealed(session, lines)
    materials = {m.id: m for m in session.execute(select(Material).where(Material.id.in_([l.material_id for l in lines] or [inv.id]))).scalars()}
    users = inventory._user_names(session, [inv.created_by, inv.submitted_by, inv.approved_by, inv.posted_by]  # noqa: SLF001
                                  + [u for l in lines for u in (l.counted_by, l.recounted_by)])

    def line(l) -> dict:
        m = materials[l.material_id]
        out = {"lineNo": l.line_no, "material": m.number, "description": m.description, "uom": m.base_uom, "batch": l.batch, "stockType": l.stock_type,
               "unlisted": l.unlisted, "countStatus": l.count_status, "countedQty": jsonable(l.counted_qty), "countedBy": users.get(l.counted_by),
               "countedAt": l.counted_at.isoformat() if l.counted_at else None, "recountQty": jsonable(l.recount_qty),
               "recountedBy": users.get(l.recounted_by), "recountReason": l.recount_reason, "finalQty": jsonable(l.final_qty), "note": l.note}
        if reveal:
            out.update(bookQty=jsonable(l.book_qty), unitPriceMinor=l.unit_price_minor, diffQty=jsonable(l.diff_qty), diffValueMinor=l.diff_value_minor,
                       firstCountWithinTolerance=l.first_count_ok, postedQty=jsonable(l.posted_qty), driftQty=jsonable(l.drift_qty))
        return out

    return {**physical_inventory_summary(inv, reveal), "rule": inv.rule_set_version, "decisionComment": inv.decision_comment,
            "createdBy": users.get(inv.created_by), "submittedBy": users.get(inv.submitted_by), "approvedBy": users.get(inv.approved_by),
            "postedBy": users.get(inv.posted_by), "submittedAt": inv.submitted_at.isoformat() if inv.submitted_at else None,
            "progress": {"lines": len(lines), "counted": sum(1 for l in lines if l.counted_qty is not None),
                         "recountRequired": sum(1 for l in lines if l.count_status == "RECOUNT_REQUIRED"),
                         "accepted": sum(1 for l in lines if l.final_qty is not None)},
            "lines": [line(l) for l in lines], "approvals": _task_views(session, "PHYSICAL_INVENTORY_APPROVAL", inv.id)}


def stock_reservation(session: Session, res) -> dict:
    from app.pic.models import StockMovement
    from app.pic.services import inventory, stock_ledger
    material = session.get(Material, res.material_id)
    users = inventory._user_names(session, [res.requester_id])  # noqa: SLF001
    issues = [{"at": m.created_at.isoformat(), "batch": m.batch, "qty": jsonable(-m.qty), "valueMinor": -m.value_minor if m.value_minor is not None else None}
              for m in session.execute(select(StockMovement).where(StockMovement.reference_type == "STOCK_RESERVATION", StockMovement.reference_id == res.id)
                                       .order_by(StockMovement.created_at, StockMovement.id)).scalars()]
    live = res.status in stock_ledger.OPEN_RESERVATION
    return {"id": str(res.id), "number": res.number, "status": res.status, "companyCode": res.company_code, "material": material.number,
            "description": material.description, "uom": material.base_uom, "plant": res.plant, "storageLocation": res.storage_location, "qty": jsonable(res.qty),
            "issuedQty": jsonable(res.issued_qty), "openQty": jsonable(res.qty - res.issued_qty), "needDate": res.need_date.isoformat(),
            "costObject": f"{res.cost_object_type}:{res.cost_object_code}" if res.cost_object_code else None, "purpose": res.purpose,
            "requester": users.get(res.requester_id), "availabilityAtCreation": res.availability,
            "availableNow": jsonable(inventory.availability(session, res.material_id, res.plant, res.storage_location, exclude_id=res.id)["available"]) if live else None,
            "demandElement": str(res.demand_element_id) if res.demand_element_id else None, "rule": res.rule_set_version,
            "closedAt": res.closed_at.isoformat() if res.closed_at else None, "closedReason": res.closed_reason, "issues": issues,
            "createdAt": res.created_at.isoformat() if res.created_at else None, "rowVersion": res.row_version}
