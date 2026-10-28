"""F6 Goods receipt / service entry → quality (M09)."""
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    Asn, AsnLine, GoodsReceipt, GrLine, InspectionLot, Invoice, InvoiceLine, PoLine, PurchaseOrder, ReturnDelivery, ServiceEntry,
    SesLine, Stock, StockMovement, Supplier, Task,
)
from app.pic.platform import audit, clock, integration, outbox, rules, sod, workflow
from app.pic.platform.core import StateMachine, link, next_number
from app.pic.platform.errors import Problem, illegal_transition, rule_violation
from app.pic.platform.money import D, line_amount
from app.pic.services import order as order_svc
from app.pic.services.common import principal, require_supplier_user

PROCESS = "pic.receipt"
GR_SM = StateMachine("GOODS_RECEIPT", {
    ("POSTED", "hold"): "QUALITY_HOLD",
    ("POSTED", "accept"): "ACCEPTED",
    ("QUALITY_HOLD", "accept"): "ACCEPTED",
    ("QUALITY_HOLD", "partially_reject"): "PARTIALLY_REJECTED",
    ("QUALITY_HOLD", "reject"): "REJECTED",
    ("POSTED", "reverse"): "REVERSED",
    ("ACCEPTED", "reverse"): "REVERSED",
    ("QUALITY_HOLD", "reverse"): "REVERSED",
})
SES_SM = StateMachine("SERVICE_ENTRY", {
    ("DRAFT", "submit"): "SUBMITTED",
    ("SUBMITTED", "approve"): "APPROVED",
    ("SUBMITTED", "reject"): "REJECTED",
    ("REJECTED", "submit"): "SUBMITTED",
    ("APPROVED", "revoke"): "REVOKED",
})

# ISO 2859-1 general inspection level II, normal: lot size → sample size.
SAMPLE_TABLE = [(8, 2), (15, 3), (25, 5), (50, 8), (90, 13), (150, 20), (280, 32), (500, 50), (1200, 80), (3200, 125),
                (10000, 200), (35000, 315), (150000, 500), (500000, 800)]


def sample_size(lot: Decimal) -> int:
    for limit, size in SAMPLE_TABLE:
        if lot <= limit:
            return size
    return 1250


def _move(session: Session, *, material_id, plant, sloc, stock_type, batch, qty: Decimal, movement: str, ref_type, ref_id, ref) -> None:
    stock = session.execute(select(Stock).where(Stock.material_id == material_id, Stock.plant == plant, Stock.storage_location == sloc,
                                                Stock.stock_type == stock_type, Stock.batch == batch).with_for_update()).scalar_one_or_none()
    if stock is None:
        stock = Stock(tenant_id=current_tenant(session), material_id=material_id, plant=plant, storage_location=sloc,
                      stock_type=stock_type, batch=batch, qty=0, created_by=principal(session).user_id)
        session.add(stock)
        session.flush()
    if stock.qty + qty < 0:
        raise Problem(422, "NEGATIVE_STOCK", f"Movement {movement} would make {stock_type} stock negative", rule_ref="RCV")
    stock.qty += qty
    session.add(StockMovement(tenant_id=current_tenant(session), material_id=material_id, plant=plant, storage_location=sloc,
                              movement_type=movement, stock_type=stock_type, batch=batch, qty=qty, reference_type=ref_type,
                              reference_id=ref_id, reference_ref=ref, created_by=principal(session).user_id))


# ---------------------------------------------------------------- ASN (F5-09/10)
def create_asn(session: Session, po: PurchaseOrder, *, lines: list[dict], ship_date: date, expected_date: date,
               eway_bill_no: Optional[str] = None, documents: Optional[list] = None) -> Asn:
    p = principal(session)
    require_supplier_user(session, po.supplier_id)
    if po.status not in ("CONFIRMED", "PARTIALLY_RECEIVED"):
        raise illegal_transition("Purchase order", po.number, po.status, "ship")
    asn = Asn(tenant_id=po.tenant_id, number=next_number(session, "ASN"), po_id=po.id, supplier_id=po.supplier_id, status="IN_TRANSIT",
              ship_date=ship_date, expected_date=expected_date, eway_bill_no=eway_bill_no, documents=documents or [], created_by=p.user_id)
    session.add(asn)
    session.flush()
    po_lines = {l.line_no: l for l in order_svc.lines_of(session, po)}
    for data in lines:
        line = po_lines[int(data["line"])]
        qty = D(data["qty"])
        limit = line.qty * (1 + D(po.tolerance.get("over_pct", 0)) / 100)
        if line.shipped_qty + qty > limit:
            raise rule_violation(f"Line {line.line_no}: shipping {qty} exceeds ordered quantity with tolerance", "RCV-TOLERANCE")
        line.shipped_qty += qty
        session.add(AsnLine(tenant_id=po.tenant_id, asn_id=asn.id, po_line_id=line.id, qty=qty, batches=data.get("batches", []),
                            received_qty=0, created_by=p.user_id))
    link(session, "PURCHASE_ORDER", po.id, po.number, "ASN", asn.id, asn.number, "shipped_as")
    outbox.emit(session, "asn.received", "ASN", asn.id, asn.number, {"po": po.number, "expected": expected_date.isoformat()})
    audit.record(session, "ASN", asn.id, "CREATED", object_ref=asn.number, after={"po": po.number, "eway": eway_bill_no,
                                                                                   "documents": documents or []})
    instance = workflow.find(session, "PURCHASE_ORDER", po.id, order_svc.PROCESS)
    if instance:
        workflow.step(session, instance, "F5-09", outcome=f"{asn.number} with {sum(len(l.get('batches', [])) for l in lines)} batch(es)")
        workflow.end(session, instance, "F5-10", outcome=f"in transit, expected {expected_date.isoformat()}")
    return asn


# ---------------------------------------------------------------- goods receipt (F6-02/03/05)
def post_gr(session: Session, po: PurchaseOrder, *, lines: list[dict], asn: Optional[Asn] = None, delivery_note: Optional[str] = None,
            posting_date: Optional[date] = None) -> GoodsReceipt:
    p = principal(session)
    if po.status not in ("TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED"):
        raise illegal_transition("Purchase order", po.number, po.status, "receive")
    sod.guard(session, "GR_POST", {"po_id": po.id})
    po_lines = {l.line_no: l for l in order_svc.lines_of(session, po)}
    gr = GoodsReceipt(tenant_id=po.tenant_id, number=next_number(session, "GOODS_RECEIPT"), po_id=po.id, asn_id=asn.id if asn else None,
                      status="POSTED", posting_date=posting_date or clock.today(), delivery_note=delivery_note, posted_by=p.user_id,
                      created_by=p.user_id)
    session.add(gr)
    session.flush()
    instance = workflow.start(session, PROCESS, "GOODS_RECEIPT", gr.id, gr.number, {"po": po.number})
    workflow.step(session, instance, "F6-02", outcome="goods")
    quality_hold = False
    lots = []
    for index, data in enumerate(lines, start=1):
        line = po_lines[int(data["line"])]
        if line.ses_required or not line.gr_required:
            raise rule_violation(f"Line {line.line_no} ({line.purchase_type.lower()}) is confirmed by service entry, not goods receipt", "P08")
        qty = D(data["qty"])
        over = D(po.tolerance.get("over_pct", 0))
        if line.received_qty + qty > line.qty * (1 + over / 100):
            raise rule_violation(f"Line {line.line_no}: over-delivery beyond +{over}% is blocked at receipt "
                                 f"({line.received_qty + qty} > {line.qty})", "RCV-TOLERANCE")
        stock_type = "QUALITY" if line.quality_managed else "UNRESTRICTED"
        batch = data.get("batch", "")
        sloc = data.get("storage_location") or line.storage_location or "0001"
        gr_line = GrLine(tenant_id=po.tenant_id, gr_id=gr.id, line_no=index * 10, po_line_id=line.id, material_id=line.material_id,
                         qty=qty, accepted_qty=0 if line.quality_managed else qty, rejected_qty=0, batch=batch,
                         serials=data.get("serials", []), expiry=date.fromisoformat(data["expiry"]) if data.get("expiry") else None,
                         stock_type=stock_type, storage_location=sloc, created_by=p.user_id)
        session.add(gr_line)
        session.flush()
        line.received_qty += qty
        if not line.quality_managed:
            line.accepted_qty += qty
        if line.material_id and line.purchase_type in ("STOCK", "CONSIGNMENT", "SUBCONTRACTING"):
            _move(session, material_id=line.material_id, plant=line.plant, sloc=sloc, stock_type=stock_type, batch=batch, qty=qty,
                  movement="101", ref_type="GOODS_RECEIPT", ref_id=gr.id, ref=gr.number)
        if line.quality_managed:
            quality_hold = True
            lot = InspectionLot(tenant_id=po.tenant_id, number=next_number(session, "INSPECTION_LOT"), gr_id=gr.id, gr_line_id=gr_line.id,
                                qty=qty, sample_size=sample_size(qty), status="OPEN", created_by=p.user_id)
            session.add(lot)
            session.flush()
            lots.append(lot)
        if asn is not None:
            for asn_line in session.execute(select(AsnLine).where(AsnLine.asn_id == asn.id, AsnLine.po_line_id == line.id)).scalars():
                asn_line.received_qty += min(qty, asn_line.qty - asn_line.received_qty)
    if asn is not None and all(l.received_qty >= l.qty for l in session.execute(select(AsnLine).where(AsnLine.asn_id == asn.id)).scalars()):
        asn.status = "RECEIVED"
    sod.record(session, "GR_POST", {"po_id": po.id})
    GR_SM.apply(session, gr, "hold" if quality_hold else "accept", extra_after={"lines": len(lines)})
    order_svc.update_receipt_status(session, po)
    link(session, "PURCHASE_ORDER", po.id, po.number, "GOODS_RECEIPT", gr.id, gr.number, "received_against")
    if asn is not None:
        link(session, "ASN", asn.id, asn.number, "GOODS_RECEIPT", gr.id, gr.number, "received_against")
    outbox.emit(session, "goods_receipt.posted", "GOODS_RECEIPT", gr.id, gr.number,
                {"grId": str(gr.id), "po": po.number, "qualityHold": quality_hold,
                 "lines": [{"line": l["line"], "qty": str(l["qty"])} for l in lines]})
    workflow.step(session, instance, "F6-03", outcome=f"{gr.number} against {po.number}" + (f"/{asn.number}" if asn else "")
                  + ": " + ", ".join(f"{l['qty']}" for l in lines) + " received")
    workflow.step(session, instance, "F6-05", outcome="yes: quality stock" if quality_hold else "no")
    if quality_hold:
        workflow.wait(session, instance, "F6-06", outcome="inspection " + ", ".join(f"{l.number} (sample {l.sample_size})" for l in lots))
    else:
        _complete_receipt(session, gr, instance, "unrestricted stock")
    return gr


def usage_decision(session: Session, lot: InspectionLot, *, accepted: Decimal, rejected: Decimal, defect_code: Optional[str] = None,
                   reason: Optional[str] = None) -> dict:
    p = principal(session)
    if lot.status != "OPEN":
        raise illegal_transition("Inspection lot", lot.number, lot.status, "decide")
    accepted, rejected = D(accepted), D(rejected)
    if accepted + rejected != lot.qty:
        raise rule_violation(f"Accepted + rejected must equal the lot quantity {lot.qty}", "QM-UD")
    if rejected > 0 and not (defect_code and reason):
        raise rule_violation("Rejections need a defect code and a reason", "QM-UD")
    gr = session.get(GoodsReceipt, lot.gr_id)
    gr_line = session.get(GrLine, lot.gr_line_id)
    po_line = session.get(PoLine, gr_line.po_line_id)
    po = session.get(PurchaseOrder, gr.po_id)
    lot.status, lot.accepted_qty, lot.rejected_qty, lot.defect_code, lot.decided_by = "DECIDED", accepted, rejected, defect_code, p.user_id
    lot.usage_decision = "ACCEPTED" if rejected == 0 else ("REJECTED" if accepted == 0 else "PARTIALLY_ACCEPTED")
    gr_line.accepted_qty, gr_line.rejected_qty = accepted, rejected
    po_line.accepted_qty += accepted
    po_line.rejected_qty += rejected
    common = dict(material_id=gr_line.material_id, plant=po_line.plant, sloc=gr_line.storage_location, batch=gr_line.batch,
                  ref_type="INSPECTION_LOT", ref_id=lot.id, ref=lot.number)
    if accepted:
        _move(session, stock_type="QUALITY", qty=-accepted, movement="321", **common)
        _move(session, stock_type="UNRESTRICTED", qty=accepted, movement="321", **common)
    return_delivery = None
    if rejected:
        _move(session, stock_type="QUALITY", qty=-rejected, movement="350", **common)
        _move(session, stock_type="BLOCKED", qty=rejected, movement="350", **common)
        return_delivery = ReturnDelivery(tenant_id=gr.tenant_id, number=next_number(session, "RETURN_DELIVERY"), gr_id=gr.id,
                                         po_line_id=po_line.id, qty=rejected, reason=f"{defect_code}: {reason}", replacement_required=False,
                                         credit_note_expected=True, status="CREATED", created_by=p.user_id)
        session.add(return_delivery)
        session.flush()
        _move(session, stock_type="BLOCKED", qty=-rejected, movement="122", **{**common, "ref_type": "RETURN_DELIVERY",
                                                                              "ref_id": return_delivery.id, "ref": return_delivery.number})
        link(session, "GOODS_RECEIPT", gr.id, gr.number, "RETURN_DELIVERY", return_delivery.id, return_delivery.number, "returned_as")
    command = "accept" if rejected == 0 else ("reject" if accepted == 0 else "partially_reject")
    GR_SM.apply(session, gr, command, reason=reason, extra_after={"accepted": str(accepted), "rejected": str(rejected), "lot": lot.number})
    outbox.emit(session, "quality.usage_decision", "GOODS_RECEIPT", gr.id, gr.number,
                {"grId": str(gr.id), "lot": lot.number, "accepted": str(accepted), "rejected": str(rejected), "defect": defect_code,
                 "po": po.number})
    instance = workflow.find(session, "GOODS_RECEIPT", gr.id, PROCESS)
    workflow.step(session, instance, "F6-06", outcome=f"{lot.number}: {accepted} accepted, {rejected} rejected" + (f" ({defect_code})" if rejected else ""))
    if return_delivery is not None:
        workflow.step(session, instance, "F6-07", outcome=f"{return_delivery.number}: {rejected} returned; credit note requested from supplier")
    _complete_receipt(session, gr, instance, "stock, GRIR and scorecard updated")
    return {"gr": gr.number, "status": gr.status, "lot": lot.number, "accepted": str(accepted), "rejected": str(rejected),
            "returnDelivery": return_delivery.number if return_delivery else None}


def _complete_receipt(session: Session, gr: GoodsReceipt, instance, outcome: str) -> None:
    po = session.get(PurchaseOrder, gr.po_id)
    message = integration.enqueue(session, target_system="SAP_S4", message_type="GOODS_RECEIPT", idempotency_key=f"GR|{gr.number}",
                                  object_type="GOODS_RECEIPT", object_id=gr.id, object_ref=gr.number,
                                  payload={"gr": gr.number, "po": po.number, "companyCode": po.company_code,
                                           "lines": [{"poLine": str(l.po_line_id), "accepted": str(l.accepted_qty)}
                                                     for l in session.execute(select(GrLine).where(GrLine.gr_id == gr.id)).scalars()]})
    integration.process(session, message)
    workflow.step(session, instance, "F6-08", outcome=f"{outcome}; ERP material document {message.erp_doc_no}")
    workflow.end(session, instance, "F6-09", outcome=gr.status.lower().replace("_", " "))


def reverse_gr(session: Session, gr: GoodsReceipt, reason: str) -> GoodsReceipt:
    invoiced = session.execute(select(InvoiceLine).join(Invoice, Invoice.id == InvoiceLine.invoice_id).join(
        GrLine, GrLine.po_line_id == InvoiceLine.po_line_id).where(GrLine.gr_id == gr.id, Invoice.status.in_(("POSTED", "PAID")))).first()
    if invoiced:
        raise rule_violation("Receipts that are already invoiced and posted cannot be reversed; use a return delivery", "RCV-REVERSE")
    for gr_line in session.execute(select(GrLine).where(GrLine.gr_id == gr.id)).scalars():
        po_line = session.get(PoLine, gr_line.po_line_id)
        po_line.received_qty -= gr_line.qty
        po_line.accepted_qty -= gr_line.accepted_qty
        if gr_line.material_id:
            remaining_type = "QUALITY" if gr.status == "QUALITY_HOLD" else "UNRESTRICTED"
            qty = gr_line.qty if gr.status == "QUALITY_HOLD" else gr_line.accepted_qty
            _move(session, material_id=gr_line.material_id, plant=po_line.plant, sloc=gr_line.storage_location, stock_type=remaining_type,
                  batch=gr_line.batch, qty=-qty, movement="102", ref_type="GOODS_RECEIPT", ref_id=gr.id, ref=gr.number)
    GR_SM.apply(session, gr, "reverse", reason=reason)
    return gr


# ---------------------------------------------------------------- service entry sheet (F6-04)
def create_ses(session: Session, po: PurchaseOrder, *, method: str, period_from: date, period_to: date, lines: list[dict]) -> ServiceEntry:
    p = principal(session)
    require_supplier_user(session, po.supplier_id)
    if po.status not in ("TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED"):
        raise illegal_transition("Purchase order", po.number, po.status, "service entry")
    ses = ServiceEntry(tenant_id=po.tenant_id, number=next_number(session, "SERVICE_ENTRY"), po_id=po.id, status="DRAFT", method=method.upper(),
                       period_from=period_from, period_to=period_to, entered_by=p.user_id, created_by=p.user_id)
    session.add(ses)
    session.flush()
    po_lines = {l.line_no: l for l in order_svc.lines_of(session, po)}
    total = 0
    for data in lines:
        line = po_lines[int(data["line"])]
        if not line.ses_required:
            raise rule_violation(f"Line {line.line_no} is not a service line", "P08")
        rate = int(D(data["unit_rate"]) * 100) if "unit_rate" in data else line.unit_price_minor
        amount = line_amount(D(data["qty"]), rate)
        if line.ses_approved_minor + amount > line.net_minor:
            raise rule_violation(f"Line {line.line_no}: service value exceeds the PO line", "RCV-SES")
        session.add(SesLine(tenant_id=po.tenant_id, ses_id=ses.id, po_line_id=line.id, description=data.get("description", line.description),
                            qty=D(data["qty"]), unit_rate_minor=rate, amount_minor=amount, created_by=p.user_id))
        total += amount
    ses.total_minor = total
    return ses


def submit_ses(session: Session, ses: ServiceEntry) -> ServiceEntry:
    po = session.get(PurchaseOrder, ses.po_id)
    SES_SM.apply(session, ses, "submit")
    instance = workflow.start(session, PROCESS, "SERVICE_ENTRY", ses.id, ses.number, {"po": po.number})
    workflow.step(session, instance, "F6-02", outcome="service")
    # SES approver must differ from the supplier user who entered it and from the PO creator.
    workflow.start_approval(session, instance, "SES_APPROVAL", object_type="SERVICE_ENTRY", object_id=ses.id, object_ref=ses.number,
                            chain=["SERVICE_OWNER"], step_id="F6-04", initiator_id=ses.entered_by, exclude=[po.created_by],
                            evidence={"totalMinor": ses.total_minor, "method": ses.method})
    return ses


@workflow.on_task("SES_APPROVAL")
def _ses_decided(session: Session, task: Task, outcome: str) -> None:
    ses = session.get(ServiceEntry, task.object_id)
    instance = workflow.find(session, "SERVICE_ENTRY", ses.id, PROCESS)
    if outcome != "APPROVED":
        SES_SM.apply(session, ses, "reject", reason=task.comment)
        workflow.end(session, instance, "F6-09", outcome=f"rejected: {task.comment}")
        return
    SES_SM.apply(session, ses, "approve")
    ses.approver_id = task.completed_by
    for line in session.execute(select(SesLine).where(SesLine.ses_id == ses.id)).scalars():
        po_line = session.get(PoLine, line.po_line_id)
        po_line.ses_approved_minor += line.amount_minor
    po = session.get(PurchaseOrder, ses.po_id)
    link(session, "PURCHASE_ORDER", po.id, po.number, "SERVICE_ENTRY", ses.id, ses.number, "received_against")
    outbox.emit(session, "service_entry.approved", "SERVICE_ENTRY", ses.id, ses.number, {"po": po.number, "totalMinor": ses.total_minor})
    workflow.step(session, instance, "F6-08", outcome="service value accrued (GRIR)")
    workflow.end(session, instance, "F6-09", outcome="service entry approved")
