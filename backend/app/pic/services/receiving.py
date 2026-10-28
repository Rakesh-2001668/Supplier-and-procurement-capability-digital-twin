"""F6 Goods receipt / service entry → quality (M09)."""
import math
import re
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    Asn, AsnLine, AuditEvent, GoodsReceipt, GrLine, InspectionLot, Invoice, InvoiceLine, Material, PoLine, PurchaseOrder, ReturnDelivery,
    ServiceEntry, SesLine, Stock, StockMovement, Supplier, Task,
)
from app.pic.platform import audit, clock, integration, outbox, rules, sod, workflow
from app.pic.platform.core import StateMachine, link, next_number
from app.pic.platform.errors import Problem, illegal_transition, rule_violation
from app.pic.platform.money import D, line_amount, tax_amount
from app.pic.platform.serialize import jsonable
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

# P08 purchase types that move stock at goods receipt, and the stock types of the special stocks (BP §22).
STOCK_PURCHASE_TYPES = ("STOCK", "CONSIGNMENT", "SUBCONTRACTING")
CONSIGNMENT = "CONSIGNMENT"      # supplier-owned consignment stock at the receiving location; liability arises on withdrawal
SUBCONTRACTOR = "SUBCONTRACTOR"  # own components held at a subcontractor; storage location = the subcontractor's supplier code
WITHDRAWAL_MOVEMENTS = {"CONSUMPTION": "201K", "TRANSFER": "411K"}  # consignment → cost object | consignment → own stock

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


# ---------------------------------------------------------------- ASN (F5-09/10) and e-way bill (Technical Document §12.3)
VEHICLE_NO = re.compile(r"^([A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}|[0-9]{2}BH[0-9]{4}[A-Z]{1,2})$")  # state series or Bharat (BH) series


def _eway(session: Session, po: PurchaseOrder, consignment_minor: int, *, ship_date: date, eway_bill_no: Optional[str],
          valid_until: Optional[datetime], vehicle_no: Optional[str], distance_km: Optional[int]) -> dict:
    """EWAY-BILL rule: at or above requiredAboveMinor (consignment value including GST, CGST Rule 138) the e-way bill
    number (rule ``format``), the vehicle number and the validity are mandatory. The validity is taken as given or computed
    from the distance: one day per ``kmPerDay`` km or part of it, ending at midnight of the last day."""
    rule = rules.resolve(session, "EWAY-BILL", company_code=po.company_code, plant=po.plant)
    required = consignment_minor >= int(rule.body["requiredAboveMinor"])
    eway_bill_no = (eway_bill_no or "").strip() or None
    vehicle_no = re.sub(r"[\s-]", "", vehicle_no or "").upper() or None
    if required:
        missing = [name for name, value in (("eway_bill_no", eway_bill_no), ("vehicle_no", vehicle_no)) if not value]
        if valid_until is None and not distance_km:
            missing.append("eway_bill_valid_until (or distance_km)")
        if missing:
            raise Problem(422, "EWAY_BILL_REQUIRED", f"Consignment value {consignment_minor / 100:,.2f} is at or above "
                          f"{int(rule.body['requiredAboveMinor']) / 100:,.2f}: an e-way bill is required ({', '.join(missing)} missing)",
                          rule_ref=rule.ref, missing=missing, consignmentValueMinor=consignment_minor)
    if eway_bill_no and not re.fullmatch(rule.body["format"], eway_bill_no):
        raise rule_violation(f"E-way bill number {eway_bill_no} does not match the required format (12 digits)", rule.ref)
    if vehicle_no and not VEHICLE_NO.fullmatch(vehicle_no):
        raise rule_violation(f"Vehicle number {vehicle_no} is not a valid Indian registration number (e.g. TN45AB1234)", rule.ref)
    if valid_until is None and distance_km and eway_bill_no:
        days = max(1, math.ceil(int(distance_km) / int(rule.body["kmPerDay"])))
        valid_until = datetime.combine(ship_date + timedelta(days=days), time(23, 59, 59), tzinfo=clock.IST)
    if valid_until is not None:
        if valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=clock.IST)
        if valid_until.astimezone(clock.IST).date() <= ship_date:
            raise rule_violation(f"E-way bill validity {valid_until.isoformat()} must be after the ship date {ship_date.isoformat()}", rule.ref)
    return {"required": required, "eway_bill_no": eway_bill_no, "valid_until": valid_until, "vehicle_no": vehicle_no, "rule": rule.ref}


def create_asn(session: Session, po: PurchaseOrder, *, lines: list[dict], ship_date: date, expected_date: date,
               eway_bill_no: Optional[str] = None, documents: Optional[list] = None, eway_bill_valid_until: Optional[datetime] = None,
               vehicle_no: Optional[str] = None, distance_km: Optional[int] = None) -> Asn:
    p = principal(session)
    require_supplier_user(session, po.supplier_id)
    if po.status not in ("CONFIRMED", "PARTIALLY_RECEIVED"):
        raise illegal_transition("Purchase order", po.number, po.status, "ship")
    po_lines = {l.line_no: l for l in order_svc.lines_of(session, po)}
    consignment = 0
    for data in lines:
        line = po_lines.get(int(data["line"]))
        if line is None:
            raise Problem(422, "UNKNOWN_LINE", f"{po.number} has no line {data['line']}")
        net = line_amount(D(data["qty"]), line.unit_price_minor)
        consignment += net + tax_amount(net, line.gst_rate)
    eway = _eway(session, po, consignment, ship_date=ship_date, eway_bill_no=eway_bill_no, valid_until=eway_bill_valid_until,
                 vehicle_no=vehicle_no, distance_km=distance_km)
    asn = Asn(tenant_id=po.tenant_id, number=next_number(session, "ASN"), po_id=po.id, supplier_id=po.supplier_id, status="IN_TRANSIT",
              ship_date=ship_date, expected_date=expected_date, eway_bill_no=eway["eway_bill_no"], eway_bill_valid_until=eway["valid_until"],
              vehicle_no=eway["vehicle_no"], documents=documents or [], created_by=p.user_id)
    session.add(asn)
    session.flush()
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
    audit.record(session, "ASN", asn.id, "CREATED", object_ref=asn.number,
                 after={"po": po.number, "eway": eway["eway_bill_no"], "ewayValidUntil": eway["valid_until"], "vehicle": eway["vehicle_no"],
                        "ewayRequired": eway["required"], "consignmentValueMinor": consignment, "documents": documents or []},
                 rule_set_version=eway["rule"])
    instance = workflow.find(session, "PURCHASE_ORDER", po.id, order_svc.PROCESS)
    if instance:
        workflow.step(session, instance, "F5-09", outcome=f"{asn.number} with {sum(len(l.get('batches', [])) for l in lines)} batch(es)")
        workflow.end(session, instance, "F5-10", outcome=f"in transit, expected {expected_date.isoformat()}")
    return asn


def eway_warnings(session: Session, gr: GoodsReceipt) -> list[dict]:
    """A receipt against an ASN whose e-way bill had expired is allowed but flagged (audited when posted)."""
    asn = session.get(Asn, gr.asn_id) if gr.asn_id else None
    if asn is None or asn.eway_bill_valid_until is None or gr.created_at <= asn.eway_bill_valid_until:
        return []
    return [{"code": "EWAY_BILL_EXPIRED", "asn": asn.number, "ewayBillNo": asn.eway_bill_no,
             "validUntil": asn.eway_bill_valid_until.isoformat(), "receivedAt": gr.created_at.isoformat(),
             "detail": f"E-way bill {asn.eway_bill_no} of {asn.number} expired on "
                       f"{asn.eway_bill_valid_until.astimezone(clock.IST):%d %b %Y %H:%M} IST, before the goods were received; "
                       "check the consignment documents"}]


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
        if line.ses_required:
            raise rule_violation(f"Line {line.line_no} ({line.purchase_type.lower()}) is confirmed by service entry, not goods receipt", "P08")
        if not line.gr_required:
            raise rule_violation(f"Line {line.line_no} ({line.purchase_type.lower()}) is receipt-less below the threshold: "
                                 "the invoice is matched 2-way against the order, no goods receipt is posted", "P08")
        qty = D(data["qty"])
        over = D(po.tolerance.get("over_pct", 0))
        if line.received_qty + qty > line.qty * (1 + over / 100):
            raise rule_violation(f"Line {line.line_no}: over-delivery beyond +{over}% is blocked at receipt "
                                 f"({line.received_qty + qty} > {line.qty})", "RCV-TOLERANCE")
        # P08: consignment goods are received into supplier-owned consignment stock (no liability until withdrawal).
        stock_type = "QUALITY" if line.quality_managed else (CONSIGNMENT if line.purchase_type == "CONSIGNMENT" else "UNRESTRICTED")
        batch = data.get("batch", "")
        expiry = data["expiry"] if isinstance(data.get("expiry"), date) else (date.fromisoformat(str(data["expiry"])) if data.get("expiry") else None)
        serials = list(data.get("serials") or [])
        _check_lot(session, line, qty, batch, expiry, serials, posting_date or clock.today())
        sloc = data.get("storage_location") or line.storage_location or "0001"
        gr_line = GrLine(tenant_id=po.tenant_id, gr_id=gr.id, line_no=index * 10, po_line_id=line.id, material_id=line.material_id,
                         qty=qty, accepted_qty=0 if line.quality_managed else qty, rejected_qty=0, batch=batch,
                         serials=serials, expiry=expiry, stock_type=stock_type, storage_location=sloc, created_by=p.user_id)
        session.add(gr_line)
        session.flush()
        line.received_qty += qty
        if not line.quality_managed:
            line.accepted_qty += qty
        order_svc.allocate_receipts(session, po, line)
        if line.material_id and line.purchase_type in STOCK_PURCHASE_TYPES:
            _move(session, material_id=line.material_id, plant=line.plant, sloc=sloc, stock_type=stock_type, batch=batch, qty=qty,
                  movement="101", ref_type="GOODS_RECEIPT", ref_id=gr.id, ref=gr.number)
        if line.purchase_type == "SUBCONTRACTING":
            # P08: the finished part is received; the components provided to the subcontractor are consumed (543).
            _consume_components(session, po, line, gr, gr_line)
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
    session.flush()
    for warning in eway_warnings(session, gr):
        audit.record(session, "GOODS_RECEIPT", gr.id, "EWAY_BILL_EXPIRED_WARNING", object_ref=gr.number, after=warning,
                     reason="Goods received after the e-way bill validity", rule_set_version="EWAY-BILL")
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
        released_to = CONSIGNMENT if po_line.purchase_type == "CONSIGNMENT" else "UNRESTRICTED"  # consignment stays supplier-owned
        _move(session, stock_type="QUALITY", qty=-accepted, movement="321", **common)
        _move(session, stock_type=released_to, qty=accepted, movement="321", **common)
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
    message = integration.enqueue(session, target_system=integration.target_system(session, po.company_code), message_type="GOODS_RECEIPT",
                                  idempotency_key=f"GR|{gr.number}",
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
        order_svc.allocate_receipts(session, session.get(PurchaseOrder, gr.po_id), po_line)
        if gr_line.material_id and po_line.purchase_type in STOCK_PURCHASE_TYPES:  # non-stock lines never moved stock at receipt
            remaining_type = "QUALITY" if gr.status == "QUALITY_HOLD" else (
                CONSIGNMENT if po_line.purchase_type == "CONSIGNMENT" else "UNRESTRICTED")
            qty = gr_line.qty if gr.status == "QUALITY_HOLD" else gr_line.accepted_qty
            _move(session, material_id=gr_line.material_id, plant=po_line.plant, sloc=gr_line.storage_location, stock_type=remaining_type,
                  batch=gr_line.batch, qty=-qty, movement="102", ref_type="GOODS_RECEIPT", ref_id=gr.id, ref=gr.number)
        if po_line.purchase_type == "SUBCONTRACTING":
            _consume_components(session, session.get(PurchaseOrder, gr.po_id), po_line, gr, gr_line, reverse=True)
    was = gr.status
    GR_SM.apply(session, gr, "reverse", reason=reason)
    _after_reversal(session, gr, was, reason)
    return gr


def _after_reversal(session: Session, gr: GoodsReceipt, was: str, reason: str) -> None:
    """Movement 102 follow-up: close the open inspection lot, give the ASN its open quantity back, re-open the PO for the
    quantity taken back (so the correct receipt can be posted), reverse the ERP material document if it was posted, and
    record the reversal on the receipt's process."""
    from app.pic.models import IntegrationMessage

    po = session.get(PurchaseOrder, gr.po_id)
    lots = []
    for lot in session.execute(select(InspectionLot).where(InspectionLot.gr_id == gr.id, InspectionLot.status == "OPEN")).scalars():
        lot.status, lot.usage_decision = "CANCELLED", "REVERSED"
        lots.append(lot.number)
    if gr.asn_id:
        asn = session.get(Asn, gr.asn_id)
        for gr_line in session.execute(select(GrLine).where(GrLine.gr_id == gr.id)).scalars():
            for asn_line in session.execute(select(AsnLine).where(AsnLine.asn_id == asn.id, AsnLine.po_line_id == gr_line.po_line_id)).scalars():
                asn_line.received_qty = max(asn_line.received_qty - gr_line.qty, Decimal(0))
        asn.status = "IN_TRANSIT"
    order_svc.receipt_reversed(session, po, gr.number)
    original = session.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == f"GR|{gr.number}",
                                                                IntegrationMessage.status == "POSTED")).scalar_one_or_none()
    erp_reversal = None
    if original is not None:
        message = integration.enqueue(session, target_system=original.target_system, message_type="GOODS_RECEIPT",
                                      idempotency_key=f"GR|{gr.number}|102", object_type="GOODS_RECEIPT", object_id=gr.id,
                                      object_ref=gr.number, payload={"gr": gr.number, "po": po.number, "companyCode": po.company_code,
                                                                     "movement": "102", "reverses": original.erp_doc_no, "reason": reason})
        integration.process(session, message)
        erp_reversal = message.erp_doc_no or message.status
    audit.record(session, "GOODS_RECEIPT", gr.id, "REVERSAL_COMPLETED", object_ref=gr.number, reason=reason,
                 after={"from": was, "po": po.number, "poStatus": po.status, "inspectionLotsCancelled": lots, "erpReversal": erp_reversal})
    outbox.emit(session, "goods_receipt.reversed", "GOODS_RECEIPT", gr.id, gr.number,
                {"grId": str(gr.id), "po": po.number, "from": was, "reason": reason})
    instance = workflow.find(session, "GOODS_RECEIPT", gr.id, PROCESS)
    if instance is not None:
        if instance.status == "RUNNING":
            workflow.end(session, instance, instance.current_step or "F6-06", outcome=f"reversed (102): {reason}", status="CANCELLED")
        else:
            workflow.step(session, instance, "F6-09", outcome=f"reversed (102): {reason}")


# ---------------------------------------------------------------- P08 special stocks: lots, subcontracting, consignment (BP §22, §23)
def _check_lot(session: Session, line: PoLine, qty: Decimal, batch: str, expiry: Optional[date], serials: list, posting_date: date) -> None:
    """Lot capture at receipt for materials that require it (material attributes batchManaged, expiryManaged, serialManaged,
    minShelfLifeDays — e.g. the healthcare template: lot, expiry and serial on every implant). Expired goods are never received."""
    material = session.get(Material, line.material_id) if line.material_id else None
    attrs = (material.attributes or {}) if material is not None else {}
    missing = []
    if attrs.get("batchManaged") and not batch:
        missing.append("batch / lot number")
    if attrs.get("expiryManaged") and expiry is None:
        missing.append("expiry date")
    if attrs.get("serialManaged") and Decimal(len(serials)) != qty:
        missing.append(f"{qty} serial number(s) (got {len(serials)})")
    if missing:
        raise rule_violation(f"Line {line.line_no}: {material.number} is lot-controlled; capture {', '.join(missing)} at receipt",
                             "RCV-LOT", missing=missing)
    if expiry is not None and expiry <= posting_date:
        raise rule_violation(f"Line {line.line_no}: lot {batch or '(no batch)'} expired on {expiry.isoformat()}; expired goods are not received",
                             "RCV-LOT")
    min_days = int(attrs.get("minShelfLifeDays") or 0)
    if expiry is not None and min_days and (expiry - posting_date).days < min_days:
        raise rule_violation(f"Line {line.line_no}: lot {batch} has {(expiry - posting_date).days} days of shelf life left; "
                             f"{material.number} needs at least {min_days} days at receipt", "RCV-LOT")
    if serials:
        if len(set(serials)) != len(serials):
            raise rule_violation(f"Line {line.line_no}: serial numbers must be unique", "RCV-LOT")
        known = {s for g in session.execute(select(GrLine).where(GrLine.material_id == line.material_id)).scalars() for s in (g.serials or [])}
        repeated = sorted(set(serials) & known)
        if repeated:
            raise rule_violation(f"Line {line.line_no}: serial number(s) {', '.join(repeated)} already received", "RCV-LOT")


def subcontracting_components(po: PurchaseOrder, line: PoLine) -> list[dict]:
    """Components the buyer provides for a subcontracting line (copied from the material's subcontracting BOM at PO creation)."""
    return list(((po.inherited or {}).get("components") or {}).get(str(line.line_no), []))


def subcontractor_stock(session: Session, supplier: Supplier) -> list[dict]:
    materials = {m.id: m.number for m in session.execute(select(Material)).scalars()}
    return [{"material": materials.get(s.material_id), "plant": s.plant, "batch": s.batch, "qty": str(s.qty)}
            for s in session.execute(select(Stock).where(Stock.stock_type == SUBCONTRACTOR, Stock.storage_location == supplier.code[:10],
                                                         Stock.qty != 0).order_by(Stock.created_at)).scalars()]


def provide_components(session: Session, po: PurchaseOrder, line_no: int, *, components: Optional[list[dict]] = None,
                       storage_location: str = "0001") -> dict:
    """Subcontracting (P08): transfer posting 541 of own components to stock at the subcontractor for one PO line. Without
    ``components`` the full planned quantity is provided; entries are {"material", "qty", "batch"?, "storage_location"?}."""
    if po.status not in ("RELEASED", "TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED"):
        raise illegal_transition("Purchase order", po.number, po.status, "provide components")
    line = next((l for l in order_svc.lines_of(session, po) if l.line_no == int(line_no)), None)
    if line is None:
        raise Problem(404, "NOT_FOUND", f"{po.number} has no line {line_no}")
    if line.purchase_type != "SUBCONTRACTING":
        raise rule_violation(f"{po.number}/{line.line_no} is a {line.purchase_type.lower()} line; components are provided for subcontracting only", "P08")
    planned = {c["material"]: c for c in subcontracting_components(po, line)}
    if not planned:
        raise rule_violation(f"{po.number}/{line.line_no} has no component list", "P08")
    supplier = session.get(Supplier, po.supplier_id)
    issues = components or [{"material": number, "qty": c["qty"]} for number, c in planned.items()]
    moved = []
    for entry in issues:
        component = planned.get(entry["material"])
        if component is None:
            raise rule_violation(f"{entry['material']} is not a component of {po.number}/{line.line_no}", "P08")
        qty = D(entry["qty"])
        if qty <= 0:
            raise rule_violation("Component quantities must be positive", "P08")
        batch = entry.get("batch") or ""
        sloc = entry.get("storage_location") or storage_location
        common = dict(material_id=uuid.UUID(component["materialId"]), plant=line.plant, batch=batch, movement="541",
                      ref_type="PURCHASE_ORDER", ref_id=po.id, ref=f"{po.number}/{line.line_no}")
        _move(session, sloc=sloc, stock_type="UNRESTRICTED", qty=-qty, **common)
        _move(session, sloc=supplier.code[:10], stock_type=SUBCONTRACTOR, qty=qty, **common)
        moved.append({"material": component["material"], "qty": str(qty), "batch": batch, "from": f"{line.plant}/{sloc}"})
    audit.record(session, "PURCHASE_ORDER", po.id, "COMPONENTS_PROVIDED", object_ref=po.number, rule_set_version="P08",
                 after={"line": line.line_no, "subcontractor": supplier.code, "components": moved})
    outbox.emit(session, "subcontracting.components_provided", "PURCHASE_ORDER", po.id, po.number,
                {"line": line.line_no, "supplier": supplier.code, "components": moved})
    return {"po": po.number, "line": line.line_no, "subcontractor": supplier.code, "components": moved,
            "atSubcontractor": subcontractor_stock(session, supplier)}


def _consume_components(session: Session, po: PurchaseOrder, line: PoLine, gr: GoodsReceipt, gr_line: GrLine, reverse: bool = False) -> None:
    """543 component consumption at the subcontractor on receipt of the finished part (first provided, first consumed);
    544 puts the same quantities back when the receipt is reversed."""
    supplier = session.get(Supplier, po.supplier_id)
    sloc, ref = supplier.code[:10], f"{gr.number}/{gr_line.line_no}"
    if reverse:
        for m in session.execute(select(StockMovement).where(StockMovement.reference_id == gr.id, StockMovement.reference_ref == ref,
                                                             StockMovement.movement_type == "543")).scalars().all():
            _move(session, material_id=m.material_id, plant=m.plant, sloc=sloc, stock_type=SUBCONTRACTOR, batch=m.batch, qty=-m.qty,
                  movement="544", ref_type="GOODS_RECEIPT", ref_id=gr.id, ref=ref)
        return
    planned = subcontracting_components(po, line)
    if not planned:
        raise rule_violation(f"{po.number}/{line.line_no} is subcontracting but has no component list", "P08")
    for component in planned:
        material_id = uuid.UUID(component["materialId"])
        need = D(component["qtyPer"]) * gr_line.qty
        rows = session.execute(select(Stock).where(Stock.material_id == material_id, Stock.plant == line.plant, Stock.storage_location == sloc,
                                                   Stock.stock_type == SUBCONTRACTOR, Stock.qty > 0).order_by(Stock.created_at)).scalars().all()
        available = sum((r.qty for r in rows), Decimal(0))
        if available < need:
            raise Problem(422, "COMPONENTS_MISSING", f"{po.number}/{line.line_no}: receiving {gr_line.qty} consumes {need} {component['material']}, "
                          f"but only {available} are at {supplier.code}; provide the components first (541)", rule_ref="P08",
                          material=component["material"], neededQty=str(need), availableQty=str(available))
        remaining = need
        for row in rows:
            take = min(row.qty, remaining)
            if take <= 0:
                break
            _move(session, material_id=material_id, plant=line.plant, sloc=sloc, stock_type=SUBCONTRACTOR, batch=row.batch, qty=-take,
                  movement="543", ref_type="GOODS_RECEIPT", ref_id=gr.id, ref=ref)
            remaining -= take


def _consignment_out(session: Session, gr_line_ids: list) -> dict:
    """Quantity that left consignment stock per receipt line: withdrawals (201K/411K) and recall quarantine (344K)."""
    if not gr_line_ids:
        return {}
    rows = session.execute(select(StockMovement.reference_id, func.sum(StockMovement.qty)).where(
        StockMovement.reference_id.in_(gr_line_ids), StockMovement.stock_type == CONSIGNMENT,
        StockMovement.movement_type.in_(("201K", "411K", "344K"))).group_by(StockMovement.reference_id)).all()
    return {ref_id: -D(total) for ref_id, total in rows}


def consignment_withdrawn(session: Session, po_line_ids: list, until: Optional[datetime] = None) -> dict:
    """Withdrawn (liability-creating) consignment quantity per PO line — the quantity self-billing (ERS) settles."""
    if not po_line_ids:
        return {}
    query = select(GrLine.po_line_id, func.sum(StockMovement.qty)).join(StockMovement, StockMovement.reference_id == GrLine.id).where(
        GrLine.po_line_id.in_(po_line_ids), StockMovement.stock_type == CONSIGNMENT,
        StockMovement.movement_type.in_(tuple(WITHDRAWAL_MOVEMENTS.values())))
    if until is not None:
        query = query.where(StockMovement.created_at < until)
    rows = session.execute(query.group_by(GrLine.po_line_id)).all()
    return {po_line_id: -D(total) for po_line_id, total in rows}


def _consignment_lots(session: Session, material_id: uuid.UUID, plant: str, sloc: str, batch: Optional[str]) -> list[list]:
    """Open consignment quantity per receipt line at a location, first-expiry-first-out: [gr_line, po_line, gr, open qty]."""
    query = select(GrLine, PoLine, GoodsReceipt).join(PoLine, PoLine.id == GrLine.po_line_id).join(GoodsReceipt, GoodsReceipt.id == GrLine.gr_id).where(
        GrLine.material_id == material_id, PoLine.purchase_type == "CONSIGNMENT", PoLine.plant == plant, GrLine.storage_location == sloc,
        GoodsReceipt.status != "REVERSED")
    if batch:
        query = query.where(GrLine.batch == batch)
    rows = session.execute(query).all()
    out_qty = _consignment_out(session, [g.id for g, _, _ in rows])
    lots = [[g, pl, gr, D(g.accepted_qty) - out_qty.get(g.id, Decimal(0))] for g, pl, gr in rows]
    lots = [lot for lot in lots if lot[3] > 0]
    return sorted(lots, key=lambda lot: (lot[0].expiry or date.max, lot[0].created_at))


def _used_serials(session: Session, gr_ids: list) -> set:
    if not gr_ids:
        return set()
    return {serial for event in session.execute(select(AuditEvent).where(
        AuditEvent.object_type == "GOODS_RECEIPT", AuditEvent.object_id.in_(gr_ids),
        AuditEvent.action.in_(("CONSIGNMENT_WITHDRAWN", "LOT_RECALLED")))).scalars() for serial in (event.after or {}).get("serials", [])}


def _replenishment_requisition(session: Session, material: Material, plant: str, sloc: str, qty: Decimal, po_line: PoLine, gr: GoodsReceipt,
                               reference: str, why: str) -> dict:
    """Consignment replenishment: a requisition for the same quantity from the consignor, linked to the receipt it replaces."""
    from app.pic.services import requisition as req_svc
    po = session.get(PurchaseOrder, po_line.po_id)
    need = clock.today() + timedelta(days=max(int(material.planned_delivery_days or 0), 2))
    pr = req_svc.create(session, origin="MANUAL", origin_ref=reference[:60], purpose_code="CONSIGNMENT_REPLENISHMENT",
                        purpose_text=f"{why}: {qty} {material.base_uom} {material.number} ({reference})", plant=plant,
                        lines=[{"item_type": "MATERIAL", "purchase_type": "CONSIGNMENT", "material": material.number, "qty": str(qty),
                                "price_est_minor": po_line.unit_price_minor, "need_date": need, "storage_location": sloc,
                                "preferred_supplier_id": po.supplier_id}])
    link(session, "GOODS_RECEIPT", gr.id, gr.number, "REQUISITION", pr.id, pr.number, "replenished_by")
    submitted = req_svc.submit(session, pr)
    return {"requisition": pr.number, "status": submitted["status"], "qty": str(qty), "plant": plant, "storageLocation": sloc}


def withdraw_consignment(session: Session, *, material: str, plant: str, qty, usage_ref: str, purpose: str = "CONSUMPTION",
                         storage_location: str = "0001", batch: Optional[str] = None, serials: Optional[list] = None,
                         cost_object: Optional[str] = None, replenish: bool = False) -> dict:
    """Withdrawal from consignment stock (BP §22): it creates the liability to the supplier at the consignment PO price, which
    self-billing settles later (payables.settle_consignment). CONSUMPTION (201K) issues to a cost object — e.g. an implant used
    in a surgical case; TRANSFER (411K) moves the quantity into own unrestricted stock (VMI). Lots go first-expiry-first-out
    unless a batch or the serial numbers are given. With replenish=True a replenishment requisition for the same quantity is
    raised against the consignor (healthcare template: implant usage triggers replenishment)."""
    from app.pic.services.common import material_by_number
    purpose = (purpose or "").upper()
    if purpose not in WITHDRAWAL_MOVEMENTS:
        raise Problem(422, "INVALID_PURPOSE", f"purpose must be one of {sorted(WITHDRAWAL_MOVEMENTS)}")
    qty = D(qty)
    usage_ref = (usage_ref or "").strip()
    if qty <= 0:
        raise rule_violation("The withdrawal quantity must be positive", "P08")
    if not usage_ref:
        raise rule_violation("A usage reference (surgical case, production order or pick list) is required", "P08")
    if purpose == "CONSUMPTION" and not (cost_object and ":" in cost_object):
        raise rule_violation("A consumption is charged to a cost object, e.g. COST_CENTER:6100", "P08")
    mat = material_by_number(session, material)
    serials = [str(s) for s in (serials or [])]
    if (mat.attributes or {}).get("serialManaged") and Decimal(len(serials)) != qty:
        raise rule_violation(f"{mat.number} is serial-managed: give the {qty} serial number(s) used", "RCV-LOT")
    lots = _consignment_lots(session, mat.id, plant, storage_location, batch)
    available = sum((lot[3] for lot in lots), Decimal(0))
    if available < qty:
        raise Problem(422, "CONSIGNMENT_STOCK_SHORT", f"Only {available} {mat.base_uom} {mat.number} in consignment stock at {plant}/{storage_location}"
                      + (f" lot {batch}" if batch else "") + f"; {qty} requested", rule_ref="P08", availableQty=str(available))
    allocations = []  # [gr_line, po_line, gr, qty, serials]
    if serials:
        used = _used_serials(session, [lot[2].id for lot in lots])
        for serial in serials:
            lot = next((lot for lot in lots if serial in (lot[0].serials or [])), None)
            if lot is None or serial in used:
                raise rule_violation(f"Serial {serial} is not in consignment stock of {mat.number} at {plant}/{storage_location}", "RCV-LOT")
            entry = next((a for a in allocations if a[0].id == lot[0].id), None)
            if entry is None:
                entry = [lot[0], lot[1], lot[2], Decimal(0), []]
                allocations.append(entry)
            entry[3] += 1
            entry[4].append(serial)
        for entry in allocations:
            lot = next(lot for lot in lots if lot[0].id == entry[0].id)
            if entry[3] > lot[3]:
                raise rule_violation(f"Lot {entry[0].batch}: {entry[3]} serials given but only {lot[3]} open", "RCV-LOT")
    else:
        remaining = qty
        for gr_line, po_line, gr, open_qty in lots:
            take = min(open_qty, remaining)
            if take > 0:
                allocations.append([gr_line, po_line, gr, take, []])
                remaining -= take
    movement = WITHDRAWAL_MOVEMENTS[purpose]
    taken, liability = [], 0
    for gr_line, po_line, gr, take, lot_serials in allocations:
        common = dict(material_id=mat.id, plant=plant, sloc=storage_location, batch=gr_line.batch, movement=movement,
                      ref_type="CONSIGNMENT_WITHDRAWAL", ref_id=gr_line.id, ref=usage_ref[:60])
        _move(session, stock_type=CONSIGNMENT, qty=-take, **common)
        if purpose == "TRANSFER":
            _move(session, stock_type="UNRESTRICTED", qty=take, **common)
        po = session.get(PurchaseOrder, po_line.po_id)
        value = line_amount(take, po_line.unit_price_minor)
        liability += value
        entry = {"grLine": str(gr_line.id), "gr": gr.number, "po": po.number, "poLine": po_line.line_no, "batch": gr_line.batch,
                 "expiry": gr_line.expiry, "qty": str(take), "serials": lot_serials, "liabilityMinor": value}
        audit.record(session, "GOODS_RECEIPT", gr.id, "CONSIGNMENT_WITHDRAWN", object_ref=gr.number, rule_set_version="P08",
                     after={**entry, "purpose": purpose, "movement": movement, "usageRef": usage_ref, "costObject": cost_object,
                            "plant": plant, "storageLocation": storage_location})
        taken.append(entry)
    outbox.emit(session, "consignment.withdrawn", "MATERIAL", mat.id, mat.number,
                {"material": mat.number, "plant": plant, "qty": str(qty), "purpose": purpose, "usageRef": usage_ref,
                 "costObject": cost_object, "liabilityMinor": liability, "lots": [{"batch": t["batch"], "qty": t["qty"], "po": t["po"]} for t in taken]})
    result = {"material": mat.number, "plant": plant, "storageLocation": storage_location, "qty": str(qty), "purpose": purpose,
              "movement": movement, "usageRef": usage_ref, "costObject": cost_object, "liabilityMinor": liability, "lots": taken}
    if replenish:
        gr_line, po_line, gr = allocations[0][0], allocations[0][1], allocations[0][2]
        result["replenishment"] = _replenishment_requisition(session, mat, plant, storage_location, qty, po_line, gr, usage_ref,
                                                             "Usage-triggered consignment replenishment")
    return result


def trace_lot(session: Session, material: str, batch: str) -> dict:
    """Recall traceability (BP §23.1): every receipt of a lot with its receiving location, every stock movement, the cases or
    orders that used it (with serials), what is still on hand where, and the return deliveries."""
    from app.pic.services.common import material_by_number
    mat = material_by_number(session, material)
    rows = session.execute(select(GrLine, GoodsReceipt, PoLine, PurchaseOrder).join(GoodsReceipt, GoodsReceipt.id == GrLine.gr_id)
                           .join(PoLine, PoLine.id == GrLine.po_line_id).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id)
                           .where(GrLine.material_id == mat.id, GrLine.batch == batch).order_by(GoodsReceipt.posting_date, GrLine.created_at)).all()
    if not rows:
        raise Problem(404, "NOT_FOUND", f"No receipt of {mat.number} lot {batch}")
    suppliers = {s.id: s.code for s in session.execute(select(Supplier)).scalars()}
    gr_ids = sorted({gr.id for _, gr, _, _ in rows})
    receipts = [{"gr": gr.number, "grLine": g.line_no, "po": po.number, "poLine": pl.line_no, "purchaseType": pl.purchase_type,
                 "supplier": suppliers.get(po.supplier_id), "plant": pl.plant, "storageLocation": g.storage_location,
                 "postingDate": gr.posting_date.isoformat(), "status": gr.status, "qty": jsonable(g.qty), "expiry": g.expiry.isoformat() if g.expiry else None,
                 "serials": list(g.serials or [])} for g, gr, pl, po in rows]
    events = session.execute(select(AuditEvent).where(AuditEvent.object_type == "GOODS_RECEIPT", AuditEvent.object_id.in_(gr_ids),
                                                      AuditEvent.action.in_(("CONSIGNMENT_WITHDRAWN", "LOT_RECALLED")))
                             .order_by(AuditEvent.seq)).scalars().all()
    lot_lines = {str(g.id) for g, _, _, _ in rows}
    usage = [{"usageRef": e.after.get("usageRef"), "purpose": e.after.get("purpose"), "plant": e.after.get("plant"),
              "storageLocation": e.after.get("storageLocation"), "qty": e.after.get("qty"), "serials": e.after.get("serials", []),
              "costObject": e.after.get("costObject"), "at": e.ts.isoformat()}
             for e in events if e.action == "CONSIGNMENT_WITHDRAWN" and e.after.get("grLine") in lot_lines]
    recalls = [e.after for e in events if e.action == "LOT_RECALLED" and e.after.get("grLine") in lot_lines]
    movements = [{"movement": m.movement_type, "stockType": m.stock_type, "plant": m.plant, "storageLocation": m.storage_location,
                  "qty": jsonable(m.qty), "referenceType": m.reference_type, "reference": m.reference_ref, "at": m.created_at.isoformat()}
                 for m in session.execute(select(StockMovement).where(StockMovement.material_id == mat.id, StockMovement.batch == batch)
                                          .order_by(StockMovement.created_at)).scalars()]
    on_hand = [{"plant": s.plant, "storageLocation": s.storage_location, "stockType": s.stock_type, "qty": jsonable(s.qty)}
               for s in session.execute(select(Stock).where(Stock.material_id == mat.id, Stock.batch == batch, Stock.qty != 0)
                                        .order_by(Stock.plant, Stock.storage_location, Stock.stock_type)).scalars()]
    returns = [{"returnDelivery": r.number, "qty": jsonable(r.qty), "reason": r.reason, "status": r.status}
               for r in session.execute(select(ReturnDelivery).where(ReturnDelivery.gr_id.in_(gr_ids), ReturnDelivery.po_line_id.in_(
                   [pl.id for _, _, pl, _ in rows])).order_by(ReturnDelivery.created_at)).scalars()]
    return {"material": mat.number, "description": mat.description, "batch": batch,
            "suppliers": sorted({r["supplier"] for r in receipts if r["supplier"]}), "receipts": receipts,
            "receivedQty": jsonable(sum((D(r["qty"]) for r in receipts), Decimal(0))), "usage": usage,
            "usedQty": jsonable(sum((D(u["qty"]) for u in usage), Decimal(0))), "onHand": on_hand, "returns": returns, "recalls": recalls,
            "recalled": bool(recalls), "movements": movements}


def recall_lot(session: Session, *, material: str, batch: str, notice_ref: str, reason: str, replenish: bool = False) -> dict:
    """Supplier recall / field safety notice for one lot: quarantine every unit still on hand (344, 344K for consignment) and
    return it to the supplier (122) with a return delivery per receipt line. Units already used stay listed in the trace for
    clinical follow-up. With replenish=True the recalled consignment quantity is re-ordered from the consignor."""
    from app.pic.services.common import material_by_number
    if not (notice_ref or "").strip() or not (reason or "").strip():
        raise rule_violation("A recall needs the supplier's notice reference and a reason", "RCV-RECALL")
    mat = material_by_number(session, material)
    trace_lot(session, material, batch)  # 404 when the lot was never received
    quarantined, replenishments = [], []
    for stock in session.execute(select(Stock).where(Stock.material_id == mat.id, Stock.batch == batch, Stock.qty > 0,
                                                     Stock.stock_type.in_((CONSIGNMENT, "UNRESTRICTED")))
                                 .order_by(Stock.plant, Stock.storage_location)).scalars().all():
        consignment = stock.stock_type == CONSIGNMENT
        if consignment:
            parts = [(g, pl, gr, q) for g, pl, gr, q in _consignment_lots(session, mat.id, stock.plant, stock.storage_location, batch)]
        else:
            parts, left = [], D(stock.qty)
            for g, pl, gr in session.execute(select(GrLine, PoLine, GoodsReceipt).join(PoLine, PoLine.id == GrLine.po_line_id)
                                             .join(GoodsReceipt, GoodsReceipt.id == GrLine.gr_id).where(
                    GrLine.material_id == mat.id, GrLine.batch == batch, GrLine.storage_location == stock.storage_location,
                    PoLine.plant == stock.plant, PoLine.purchase_type != "CONSIGNMENT").order_by(GrLine.created_at.desc())).all():
                take = min(left, D(g.accepted_qty))
                if take > 0:
                    parts.append((g, pl, gr, take))
                    left -= take
        used = _used_serials(session, [gr.id for _, _, gr, _ in parts])
        movement = "344K" if consignment else "344"
        for gr_line, po_line, gr, take in parts:
            common = dict(material_id=mat.id, plant=stock.plant, sloc=stock.storage_location, batch=batch)
            _move(session, stock_type=stock.stock_type, qty=-take, movement=movement, ref_type="LOT_RECALL", ref_id=gr_line.id, ref=notice_ref[:60], **common)
            _move(session, stock_type="BLOCKED", qty=take, movement=movement, ref_type="LOT_RECALL", ref_id=gr_line.id, ref=notice_ref[:60], **common)
            rd = ReturnDelivery(tenant_id=gr.tenant_id, number=next_number(session, "RETURN_DELIVERY"), gr_id=gr.id, po_line_id=po_line.id,
                                qty=take, reason=f"RECALL {notice_ref}: {reason}", replacement_required=True,
                                credit_note_expected=not consignment, status="CREATED", created_by=principal(session).user_id)
            session.add(rd)
            session.flush()
            _move(session, stock_type="BLOCKED", qty=-take, movement="122", ref_type="RETURN_DELIVERY", ref_id=rd.id, ref=rd.number, **common)
            if not consignment:
                po_line.rejected_qty += take  # own stock: invoiced value comes back by credit note
            link(session, "GOODS_RECEIPT", gr.id, gr.number, "RETURN_DELIVERY", rd.id, rd.number, "returned_as")
            serials = [s for s in (gr_line.serials or []) if s not in used][: int(take)] if gr_line.serials else []
            entry = {"grLine": str(gr_line.id), "gr": gr.number, "plant": stock.plant, "storageLocation": stock.storage_location,
                     "stockType": stock.stock_type, "qty": jsonable(take), "serials": serials, "returnDelivery": rd.number}
            audit.record(session, "GOODS_RECEIPT", gr.id, "LOT_RECALLED", object_ref=gr.number, reason=f"{notice_ref}: {reason}",
                         rule_set_version="RCV-RECALL", after={**entry, "notice": notice_ref, "batch": batch, "material": mat.number})
            quarantined.append(entry)
            if consignment and replenish:
                replenishments.append(_replenishment_requisition(session, mat, stock.plant, stock.storage_location, take, po_line, gr,
                                                                 f"{notice_ref} {batch}", "Replacement for recalled lot"))
    outbox.emit(session, "lot.recalled", "MATERIAL", mat.id, mat.number,
                {"material": mat.number, "batch": batch, "notice": notice_ref, "quarantined": [{k: q[k] for k in ("plant", "storageLocation", "qty")}
                                                                                               for q in quarantined]})
    return {"notice": notice_ref, "material": mat.number, "batch": batch, "quarantined": quarantined, "replenishments": replenishments,
            "trace": trace_lot(session, material, batch)}


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
