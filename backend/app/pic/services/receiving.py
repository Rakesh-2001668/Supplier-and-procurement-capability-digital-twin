"""F6 Goods receipt / service entry → quality (M09)."""
import math
import re
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    Asn, AsnLine, AuditEvent, GoodsReceipt, GrLine, InspectionLot, Invoice, InvoiceLine, Material, PoLine, PurchaseOrder, ReturnDelivery,
    ServiceEntry, SesLine, Stock, StockMovement, Supplier, Task,
)
from app.pic.platform import abac
from app.pic.platform import audit, clock, integration, outbox, rules, sod, workflow
from app.pic.platform.core import StateMachine, link, next_number
from app.pic.platform.errors import Problem, illegal_transition, rule_violation
from app.pic.platform.money import D, line_amount, tax_amount
from app.pic.platform.serialize import jsonable
from app.pic.services import ind_healthcare
from app.pic.services import mandatory, org_guard, p2p_rules, po_controls, stock_ledger
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
# Return deliveries (flow fixes C1): a return awaiting a credit note is CREDITED when quantity credit notes cover it, one awaiting a
# replacement is REPLACED when the replacement is received; either can be CLOSED by hand (with a reason) when nothing more is due.
RD_SM = StateMachine("RETURN_DELIVERY", {
    ("CREATED", "request_replacement"): "REPLACEMENT_DUE",
    ("CREATED", "credit"): "CREDITED",
    ("REPLACEMENT_DUE", "replace"): "REPLACED",
    ("REPLACED", "reopen"): "REPLACEMENT_DUE",   # the replacement receipt was reversed (102)
    ("CREATED", "close"): "CLOSED",
    ("REPLACEMENT_DUE", "close"): "CLOSED",
})
OPEN_RETURNS = ("CREATED", "REPLACEMENT_DUE")
RETURN_STATUSES = ("CREATED", "REPLACEMENT_DUE", "CREDITED", "REPLACED", "CLOSED")

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


def _guard_stock_change(session: Session, plant: str, what: str, company_code: Optional[str] = None) -> None:
    """A command that moves stock of a plant outside the receipt itself (consignment withdrawal, recall, components to a subcontractor,
    expiry write-off): the user must be assigned to the plant (SEC-AZ, action STOCK_MOVE) and the posting period of its company code must be
    open (cut-off)."""
    from app.pic.services import finance_controls
    abac.guard(session, "STOCK_MOVE", None, plant=plant, company_code=company_code)
    finance_controls.assert_open(session, company_code or stock_ledger.plant_company(session, plant), clock.today(), what)


def _positive(qty, what: str) -> Decimal:
    """Shipped, received and service quantities are strictly positive (a negative receipt is a reversal, never a line)."""
    value = D(qty)
    if not value.is_finite() or value <= 0:
        raise Problem(422, "INVALID_QUANTITY", f"{what}: the quantity must be positive (got {qty})", rule_ref="RCV")
    return value


def _move(session: Session, *, material_id, plant, sloc, stock_type, batch, qty: Decimal, movement: str, ref_type, ref_id, ref) -> None:
    """Thin alias of ``stock_ledger.post_movement`` (kept for the modules that import it from here)."""
    stock_ledger.post_movement(session, material_id=material_id, plant=plant, sloc=sloc, stock_type=stock_type, batch=batch, qty=qty,
                               movement=movement, ref_type=ref_type, ref_id=ref_id, ref=ref)


# ---------------------------------------------------------------- ASN (F5-09/10) and e-way bill (Technical Document §12.3)
VEHICLE_NO = re.compile(r"^([A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}|[0-9]{2}BH[0-9]{4}[A-Z]{1,2})$")  # state series or Bharat (BH) series


def _eway(session: Session, po: PurchaseOrder, consignment_minor: int, *, ship_date: date, eway_bill_no: Optional[str],
          valid_until: Optional[datetime], vehicle_no: Optional[str], distance_km: Optional[int]) -> dict:
    """EWAY-BILL rule: above requiredAboveMinor (consignment value including GST, CGST Rule 138: "exceeds fifty thousand
    rupees") the e-way bill number (rule ``format``), the vehicle number and the validity are mandatory. The validity is
    taken as given or computed from the distance: one day per ``kmPerDay`` km or part of it, ending at midnight of the last day."""
    rule = rules.resolve(session, "EWAY-BILL", company_code=po.company_code, plant=po.plant)
    required = consignment_minor > int(rule.body["requiredAboveMinor"])
    eway_bill_no = (eway_bill_no or "").strip() or None
    vehicle_no = re.sub(r"[\s-]", "", vehicle_no or "").upper() or None
    if required:
        missing = [name for name, value in (("eway_bill_no", eway_bill_no), ("vehicle_no", vehicle_no)) if not value]
        if valid_until is None and not distance_km:
            missing.append("eway_bill_valid_until (or distance_km)")
        if missing:
            raise Problem(422, "EWAY_BILL_REQUIRED", f"Consignment value {consignment_minor / 100:,.2f} exceeds "
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
    if not lines:
        raise Problem(422, "LINES_REQUIRED", "An ASN lists at least one shipped line", rule_ref="RCV")
    consignment = 0
    for data in lines:
        line = po_lines.get(int(data["line"]))
        if line is None:
            raise Problem(422, "UNKNOWN_LINE", f"{po.number} has no line {data['line']}")
        net = line_amount(_positive(data["qty"], f"Line {line.line_no}"), line.unit_price_minor)
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
        limit = line.qty * (1 + po_controls.line_tolerance(po, line)[0] / 100)  # BP M09: per material / supplier override
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
def _mandatory_fields(session: Session, po: PurchaseOrder, lines: list[dict], asn: Optional[Asn], delivery_note: Optional[str],
                      posting_date: Optional[date]) -> None:
    """Rule MANDATORY-FIELDS (document GR_POST), scoped by company code, plant and the received lines' category / purchase type."""
    po_lines = {l.line_no: l for l in order_svc.lines_of(session, po)}
    received = [po_lines[int(d["line"])] for d in lines if int(d["line"]) in po_lines]
    category, purchase_type = mandatory.dominant((l.material_group, l.purchase_type, l.net_minor) for l in received)
    header = {"delivery_note": delivery_note, "asn": asn.number if asn else None, "posting_date": posting_date or clock.today()}
    body = [{**{k: d.get(k) for k in mandatory.CATALOGUE["GR_POST"]["lines"]}, "_line_no": d.get("line")} for d in lines]
    supplier = session.get(Supplier, po.supplier_id)
    mandatory.check(session, "GR_POST", header, body, company_code=po.company_code, plant=po.plant, category=category,
                    purchase_type=purchase_type, supplier_group=supplier.supplier_group if supplier else None)


def capitalisation(session: Session, po: PurchaseOrder, gr: GoodsReceipt) -> list[dict]:
    """Capitalisation data of the asset lines of a receipt for the ERP posting: asset class (rule ASSET-CAPITALISATION by valuation
    class, then material group, then the default), the asset number or WBS element the line is assigned to, the cost centre and
    the capitalise flag. ``needsAssetClass`` is true when the tenant has not configured an asset class for the line."""
    from app.pic.models import AppUser, Requisition
    rows = session.execute(select(GrLine, PoLine).join(PoLine, PoLine.id == GrLine.po_line_id).where(
        GrLine.gr_id == gr.id, PoLine.purchase_type == "ASSET").order_by(GrLine.line_no)).all()
    if not rows:
        return []
    rule = p2p_rules.rule(session, "ASSET-CAPITALISATION", company_code=po.company_code)
    body = rule.body
    out = []
    for gr_line, line in rows:
        material = session.get(Material, line.material_id) if line.material_id else None
        asset_class = ((body.get("assetClassByValuationClass") or {}).get(material.valuation_class) if material and material.valuation_class else None
                       ) or (body.get("assetClassByMaterialGroup") or {}).get(line.material_group) or body.get("defaultAssetClass")
        cost_centre = (body.get("costCentreByPlant") or {}).get(line.plant)
        if not cost_centre and line.requisition_id:
            requisition = session.get(Requisition, line.requisition_id)
            owner = session.get(AppUser, requisition.requester_id) if requisition else None
            cost_centre = next((c.split(":", 1)[1] for c in (owner.attributes or {}).get("cost_objects", []) if str(c).startswith("COST_CENTER:")), None) \
                if owner else None
        if not cost_centre and line.account_assignment_type == "COST_CENTER":
            cost_centre = line.account_assignment_code
        out.append({"poLine": line.line_no, "grLine": gr_line.line_no, "material": material.number if material else None,
                    "description": line.description, "acceptedQty": str(gr_line.accepted_qty),
                    "valueMinor": line_amount(gr_line.accepted_qty, line.unit_price_minor), "capitalise": bool(body.get("capitalise", True)),
                    "assetClass": asset_class, "needsAssetClass": asset_class is None,
                    "assetNumber": line.account_assignment_code if line.account_assignment_type == "ASSET" else None,
                    "wbsElement": line.account_assignment_code if line.account_assignment_type == "WBS" else None,
                    "costCentre": cost_centre, "capitalisationDate": gr.posting_date.isoformat(), "rule": rule.ref})
    return out


def post_gr(session: Session, po: PurchaseOrder, *, lines: list[dict], asn: Optional[Asn] = None, delivery_note: Optional[str] = None,
            posting_date: Optional[date] = None) -> GoodsReceipt:
    p = principal(session)
    if po.status not in ("TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED"):
        raise illegal_transition("Purchase order", po.number, po.status, "receive")
    if asn is not None and asn.po_id != po.id:
        # F6-03: the receipt quantities are booked onto the ASN lines; an ASN of another order would be closed by the wrong goods.
        other = session.get(PurchaseOrder, asn.po_id)
        raise Problem(422, "ASN_PO_MISMATCH", f"ASN {asn.number} was shipped against {other.number if other else 'another order'}, "
                      f"not {po.number}; post the receipt against that order or without the ASN", rule_ref="F6-03",
                      asn=asn.number, asnPo=other.number if other else None, po=po.number)
    sod.guard(session, "GR_POST", {"po_id": po.id})
    po_lines = {l.line_no: l for l in order_svc.lines_of(session, po)}
    # SEC-AZ: the receiver must be assigned to the plant of every line received (an order can carry lines for several plants; the
    # header plant is only where it was raised). Lines that do not exist are reported below.
    for plant in sorted({po_lines[int(d["line"])].plant for d in lines if int(d["line"]) in po_lines} or {po.plant}):
        abac.guard(session, "GR_POST", po, plant=plant)
    if not lines:
        raise Problem(422, "LINES_REQUIRED", "A goods receipt lists at least one received line", rule_ref="RCV")
    for data in lines:
        if int(data["line"]) not in po_lines:
            raise Problem(422, "UNKNOWN_LINE", f"{po.number} has no line {data['line']}")
        _positive(data["qty"], f"Line {data['line']}")
    _mandatory_fields(session, po, lines, asn, delivery_note, posting_date)
    # ADM-01: a deactivated plant or storage location is refused on a new receipt (the order may predate the deactivation)
    org_guard.ensure_active(session, "goods receipt", company_code=po.company_code)
    from app.pic.services import finance_controls
    for when in {posting_date or clock.today(), clock.today()}:  # cut-off: neither the posting date nor today may lie in a closed period
        finance_controls.assert_open(session, po.company_code, when, f"goods receipt for {po.number}")
    for data in lines:
        line = po_lines[int(data["line"])]
        org_guard.ensure_active(session, "goods receipt", plant=line.plant,
                                storage_location=data.get("storage_location") or line.storage_location)
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
        over = po_controls.line_tolerance(po, line)[0]
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
        _settle_by_receipt(session, gr, gr_line)  # C1: a receipt on a line that owes a replacement settles the return(s) first
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
    ind_healthcare.on_goods_receipt(session, gr)  # cold chain: an excursion reported on the ASN quarantines these goods (healthcare rule)
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
                   reason: Optional[str] = None, replacement: bool = False) -> dict:
    """F6-06 usage decision on one inspection lot. A receipt with several quality-managed lines has one lot per line: each
    decision releases (321) or returns (350/122) its own line; the receipt's status, the ERP material document and the end of
    its process follow when the last open lot is decided. With replacement=True the rejected quantity is returned for
    replacement: it is open again on the order for a new ASN and receipt instead of being settled by credit note."""
    p = principal(session)
    if lot.status != "OPEN":
        raise illegal_transition("Inspection lot", lot.number, lot.status, "decide")
    accepted, rejected = D(accepted), D(rejected)
    if accepted < 0 or rejected < 0:
        raise Problem(422, "INVALID_QUANTITY", "Accepted and rejected quantities cannot be negative", rule_ref="QM-UD")
    if replacement and rejected <= 0:
        raise rule_violation("A replacement is requested for a rejected quantity", "QM-UD")
    if accepted + rejected != lot.qty:
        raise rule_violation(f"Accepted + rejected must equal the lot quantity {lot.qty}", "QM-UD")
    if rejected > 0 and not (defect_code and reason):
        raise rule_violation("Rejections need a defect code and a reason", "QM-UD")
    gr = session.get(GoodsReceipt, lot.gr_id)
    gr_line = session.get(GrLine, lot.gr_line_id)
    po_line = session.get(PoLine, gr_line.po_line_id)
    po = session.get(PurchaseOrder, gr.po_id)
    abac.guard(session, "STOCK_MOVE", po, plant=po_line.plant)  # SEC-AZ: the inspector is assigned to the plant whose stock the decision moves
    from app.pic.services import finance_controls
    finance_controls.assert_open(session, po.company_code, clock.today(), f"usage decision on {lot.number}")  # cut-off, as at the receipt
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
        if replacement:
            _reopen_for_replacement(session, return_delivery, po, po_line)
    session.flush()
    still_open = session.execute(select(InspectionLot.number).where(InspectionLot.gr_id == gr.id, InspectionLot.status == "OPEN")
                                 .order_by(InspectionLot.number)).scalars().all()
    instance = workflow.find(session, "GOODS_RECEIPT", gr.id, PROCESS)
    if not still_open:
        # The receipt's outcome covers every line: all accepted, all rejected, or partly rejected.
        gr_lines = session.execute(select(GrLine).where(GrLine.gr_id == gr.id)).scalars().all()
        total_accepted = sum((D(g.accepted_qty) for g in gr_lines), Decimal(0))
        total_rejected = sum((D(g.rejected_qty) for g in gr_lines), Decimal(0))
        command = "accept" if total_rejected == 0 else ("reject" if total_accepted == 0 else "partially_reject")
        GR_SM.apply(session, gr, command, reason=reason, extra_after={"accepted": str(accepted), "rejected": str(rejected), "lot": lot.number,
                                                                      "receiptAccepted": str(total_accepted), "receiptRejected": str(total_rejected)})
    else:
        audit.record(session, "GOODS_RECEIPT", gr.id, "LOT_DECIDED", object_ref=gr.number, reason=reason, rule_set_version="QM-UD",
                     after={"lot": lot.number, "accepted": str(accepted), "rejected": str(rejected), "openLots": still_open})
    if not still_open:
        # One event per receipt (the scorecard scores the receipt once; a rejection opens one CAPA): the quantities of all
        # its lots, the lot with the largest rejection as the reference.
        lots = session.execute(select(InspectionLot).where(InspectionLot.gr_id == gr.id, InspectionLot.status == "DECIDED")
                               .order_by(InspectionLot.number)).scalars().all()
        worst = max(lots, key=lambda x: (D(x.rejected_qty or 0), x.id == lot.id))
        outbox.emit(session, "quality.usage_decision", "GOODS_RECEIPT", gr.id, gr.number,
                    {"grId": str(gr.id), "lot": worst.number, "accepted": str(sum((D(x.accepted_qty or 0) for x in lots), Decimal(0))),
                     "rejected": str(sum((D(x.rejected_qty or 0) for x in lots), Decimal(0))),
                     "defect": ", ".join(sorted({x.defect_code for x in lots if x.defect_code})) or None, "po": po.number,
                     "lots": [{"lot": x.number, "accepted": str(x.accepted_qty), "rejected": str(x.rejected_qty)} for x in lots]})
    workflow.step(session, instance, "F6-06", outcome=f"{lot.number}: {accepted} accepted, {rejected} rejected" + (f" ({defect_code})" if rejected else "")
                  + (f"; still open: {', '.join(still_open)}" if still_open else ""), status="ACTIVE" if still_open else "COMPLETED")
    if return_delivery is not None:
        workflow.step(session, instance, "F6-07", outcome=f"{return_delivery.number}: {rejected} returned; "
                      + ("replacement requested from supplier" if replacement else "credit note requested from supplier"))
        if still_open:
            workflow.wait(session, instance, "F6-06", outcome="inspection " + ", ".join(still_open))
    if not still_open:
        _complete_receipt(session, gr, instance, "stock, GRIR and scorecard updated")
    return {"gr": gr.number, "status": gr.status, "lot": lot.number, "accepted": str(accepted), "rejected": str(rejected),
            "returnDelivery": return_delivery.number if return_delivery else None, "openLots": still_open,
            "replacement": bool(replacement and return_delivery is not None)}


def _complete_receipt(session: Session, gr: GoodsReceipt, instance, outcome: str) -> None:
    po = session.get(PurchaseOrder, gr.po_id)
    capitalised = capitalisation(session, po, gr)  # BP §22: asset lines carry asset class, cost centre and the capitalise flag
    message = integration.enqueue(session, target_system=integration.target_system(session, po.company_code), message_type="GOODS_RECEIPT",
                                  idempotency_key=f"GR|{gr.number}",
                                  object_type="GOODS_RECEIPT", object_id=gr.id, object_ref=gr.number,
                                  payload={"gr": gr.number, "po": po.number, "companyCode": po.company_code,
                                           "lines": [{"poLine": str(l.po_line_id), "accepted": str(l.accepted_qty),
                                                      **({"batch": l.batch} if l.batch else {}),
                                                      **({"storageLocation": l.storage_location} if l.storage_location else {})}
                                                     for l in session.execute(select(GrLine).where(GrLine.gr_id == gr.id)).scalars()],
                                           **({"capitalisation": capitalised} if capitalised else {})})
    integration.process(session, message)
    workflow.step(session, instance, "F6-08", outcome=f"{outcome}; ERP material document {message.erp_doc_no}")
    workflow.end(session, instance, "F6-09", outcome=gr.status.lower().replace("_", " "))


def reverse_gr(session: Session, gr: GoodsReceipt, reason: str) -> GoodsReceipt:
    # Any invoice on these PO lines that is not rejected was (or is being) matched against this receipt: reversing it would
    # let an approved invoice post without a receipt.
    invoices = session.execute(select(Invoice.number, Invoice.status).join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id).join(
        GrLine, GrLine.po_line_id == InvoiceLine.po_line_id).where(GrLine.gr_id == gr.id, Invoice.status != "REJECTED")
        .order_by(Invoice.number).distinct()).all()
    if invoices:
        listed = ", ".join(f"{number} ({status.lower()})" for number, status in invoices)
        raise Problem(409, "RECEIPT_INVOICED", f"{gr.number} cannot be reversed: invoice {listed} references its order lines. Reject the "
                      "invoice first, or use a return delivery for goods already invoiced and posted", rule_ref="RCV-REVERSE",
                      invoices=[{"invoice": number, "status": status} for number, status in invoices])
    if not GR_SM.can(gr.status, "reverse"):
        raise illegal_transition("Goods receipt", gr.number, gr.status, "reverse")
    po = session.get(PurchaseOrder, gr.po_id)
    gr_lines = session.execute(select(GrLine, PoLine).join(PoLine, PoLine.id == GrLine.po_line_id).where(GrLine.gr_id == gr.id)).all()
    for plant in sorted({po_line.plant for _, po_line in gr_lines} or {po.plant}):
        abac.guard(session, "GR_POST", po, plant=plant)  # SEC-AZ: reversing a receipt takes stock out of its plant
    from app.pic.services import finance_controls
    finance_controls.assert_open(session, po.company_code, clock.today(), f"reversal of {gr.number}")  # cut-off, as at the receipt
    lots = {l.gr_line_id: l for l in session.execute(select(InspectionLot).where(InspectionLot.gr_id == gr.id)).scalars()}
    returned = [l.number for l in lots.values() if l.status == "DECIDED" and D(l.rejected_qty or 0) > 0]
    if returned:
        raise rule_violation(f"{gr.number}: lot {', '.join(returned)} was already rejected and returned to the supplier; reverse is not "
                             "possible, correct the remaining quantity with a return delivery", "RCV-REVERSE")
    for gr_line in session.execute(select(GrLine).where(GrLine.gr_id == gr.id)).scalars():
        po_line = session.get(PoLine, gr_line.po_line_id)
        po_line.received_qty -= gr_line.qty
        po_line.accepted_qty -= gr_line.accepted_qty
        order_svc.allocate_receipts(session, session.get(PurchaseOrder, gr.po_id), po_line)
        if gr_line.material_id and po_line.purchase_type in STOCK_PURCHASE_TYPES:  # non-stock lines never moved stock at receipt
            # Each line is taken back from where it is now: quality stock while its own lot is open, else released stock.
            lot = lots.get(gr_line.id)
            in_quality = gr_line.stock_type == "QUALITY" and lot is not None and lot.status == "OPEN"
            remaining_type = "QUALITY" if in_quality else (
                CONSIGNMENT if po_line.purchase_type == "CONSIGNMENT" else "UNRESTRICTED")
            qty = gr_line.qty if in_quality else gr_line.accepted_qty
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
    _unsettle_by_receipt(session, gr)  # C1: a reversed replacement receipt leaves its return(s) due again
    if original is not None:
        # C2: the reversal carries the lines the ERP received with the 101 (same PO items, quantities and batches), so a live connector
        # can post the 102 against the PO items; the simulator ignores them.
        lines = [dict(line) for line in (original.payload or {}).get("lines") or []]
        message = integration.enqueue(session, target_system=original.target_system, message_type="GOODS_RECEIPT",
                                      idempotency_key=f"GR|{gr.number}|102", object_type="GOODS_RECEIPT", object_id=gr.id,
                                      object_ref=gr.number, payload={"gr": gr.number, "po": po.number, "companyCode": po.company_code,
                                                                     "movement": "102", "reverses": original.erp_doc_no, "reason": reason,
                                                                     "lines": lines})
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


# ---------------------------------------------------------------- replacement of returned goods (M09 "returns and replacements")
REPLACEABLE_PO = ("TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED", "RECEIVED")


def _reopen_for_replacement(session: Session, rd: ReturnDelivery, po: PurchaseOrder, po_line: PoLine) -> None:
    """The returned quantity is owed again by the supplier: it leaves the received (and rejected) quantity of the PO line and
    the shipped quantity, so a new ASN and goods receipt can be posted for it; no credit note is expected for it."""
    if po.status not in REPLACEABLE_PO:
        raise illegal_transition("Purchase order", po.number, po.status, "receive a replacement")
    if po_line.rejected_qty < rd.qty or po_line.received_qty < rd.qty:
        raise rule_violation(f"{rd.number}: {jsonable(rd.qty)} returned but the line holds only {jsonable(po_line.rejected_qty)} rejected; "
                             "this return is settled by credit note", "RCV-RETURN")
    if not RD_SM.can(rd.status, "request_replacement"):
        raise illegal_transition("Return delivery", rd.number, rd.status, "request replacement")
    po_line.received_qty -= rd.qty
    po_line.rejected_qty -= rd.qty
    po_line.shipped_qty = max(po_line.shipped_qty - rd.qty, Decimal(0))
    order_svc.allocate_receipts(session, po, po_line)
    rd.replacement_required, rd.credit_note_expected, rd.status = True, False, "REPLACEMENT_DUE"
    order_svc.receipt_reversed(session, po, rd.number, reason=f"{rd.number}: {jsonable(rd.qty)} returned for replacement")
    audit.record(session, "RETURN_DELIVERY", rd.id, "REPLACEMENT_REQUESTED", object_ref=rd.number, rule_set_version="RCV-RETURN",
                 after={"po": po.number, "poLine": po_line.line_no, "qty": jsonable(rd.qty), "openQty": jsonable(po_line.qty - po_line.received_qty),
                        "poStatus": po.status})
    outbox.emit(session, "return_delivery.replacement_requested", "RETURN_DELIVERY", rd.id, rd.number,
                {"po": po.number, "poLine": po_line.line_no, "qty": jsonable(rd.qty), "supplierId": str(po.supplier_id)})


def request_replacement(session: Session, rd: ReturnDelivery, reason: Optional[str] = None) -> ReturnDelivery:
    """Turn a return delivery that awaits a credit note into a replacement (e.g. the supplier offers to re-deliver)."""
    if rd.status != "CREATED" or not rd.credit_note_expected:
        raise illegal_transition("Return delivery", rd.number, rd.status, "request replacement")
    po_line = session.get(PoLine, rd.po_line_id)
    po = session.get(PurchaseOrder, po_line.po_id)
    _reopen_for_replacement(session, rd, po, po_line)
    if reason:
        audit.record(session, "RETURN_DELIVERY", rd.id, "REPLACEMENT_REASON", object_ref=rd.number, reason=reason)
    return rd


def _settle(session: Session, rd: ReturnDelivery, qty: Decimal, kind: str, ref: str) -> Decimal:
    """Book ``qty`` of a settling document (credit note or replacement receipt) against an open return; the return is CREDITED /
    REPLACED (audited, event) once its whole quantity is covered. Returns the quantity taken."""
    take = min(D(qty), D(rd.qty) - D(rd.settled_qty or 0))
    if take <= 0:
        return Decimal(0)
    rd.settled_qty = D(rd.settled_qty or 0) + take
    rd.settlements = [*(rd.settlements or []), {"type": kind, "ref": ref, "qty": jsonable(take), "at": clock.now().isoformat()}]
    po_line = session.get(PoLine, rd.po_line_id)
    po = session.get(PurchaseOrder, po_line.po_id)
    if rd.settled_qty < rd.qty:
        audit.record(session, "RETURN_DELIVERY", rd.id, "PARTIALLY_SETTLED", object_ref=rd.number, rule_set_version="RCV-RETURN",
                     after={"by": kind, "ref": ref, "qty": jsonable(take), "settledQty": jsonable(rd.settled_qty), "qtyReturned": jsonable(rd.qty)})
        return take
    rd.closed_at = clock.now()
    detail = {"po": po.number, "poLine": po_line.line_no, "qty": jsonable(rd.qty), "settlements": rd.settlements, "supplierId": str(po.supplier_id)}
    if kind == "CREDIT_NOTE":
        RD_SM.apply(session, rd, "credit", rule_set_version="RCV-RETURN", extra_after={"creditNotes": [x["ref"] for x in rd.settlements]})
        outbox.emit(session, "return_delivery.credited", "RETURN_DELIVERY", rd.id, rd.number, detail)
    else:
        RD_SM.apply(session, rd, "replace", rule_set_version="RCV-RETURN", extra_after={"receipts": [x["ref"] for x in rd.settlements]})
        outbox.emit(session, "return_delivery.replaced", "RETURN_DELIVERY", rd.id, rd.number, detail)
    return take


def settle_by_credit_note(session: Session, invoice: Invoice, note, return_delivery: Optional[str] = None) -> list[str]:
    """A supplier credit note was received: its quantity lines settle the open returns awaiting a credit note on the same PO lines (oldest
    first), or only the return named by the supplier / AP (``return_delivery``). Value (price-difference) lines settle no return.
    Returns the numbers of the returns the note closed."""
    by_line = {l.line_no: l for l in session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)).scalars()}
    credited_lines = {by_line[int(e["invoice_line"])].po_line_id for e in note.lines
                      if e.get("unitCreditMinor") is None and int(e["invoice_line"]) in by_line}
    named = None
    if return_delivery:
        named = session.execute(select(ReturnDelivery).where(ReturnDelivery.number == return_delivery).with_for_update()).scalar_one_or_none()
        if named is None:
            raise Problem(404, "NOT_FOUND", f"Return delivery {return_delivery} not found")
        if named.po_line_id not in credited_lines:
            raise rule_violation(f"{named.number} is not on an order line this credit note credits by quantity", "RCV-RETURN")
        if named.status != "CREATED" or not named.credit_note_expected:
            raise illegal_transition("Return delivery", named.number, named.status, "credit")
    closed = []
    for entry in note.lines:
        if entry.get("unitCreditMinor") is not None:
            continue
        line = by_line.get(int(entry["invoice_line"]))
        if line is None or line.po_line_id is None:
            continue
        left = D(entry["qty"])
        candidates = [named] if named is not None else session.execute(
            select(ReturnDelivery).where(ReturnDelivery.po_line_id == line.po_line_id, ReturnDelivery.status == "CREATED",
                                         ReturnDelivery.credit_note_expected.is_(True))
            .order_by(ReturnDelivery.created_at, ReturnDelivery.number).with_for_update()).scalars().all()
        for rd in candidates:
            if rd.po_line_id != line.po_line_id or left <= 0 or rd.status != "CREATED":
                continue
            left -= _settle(session, rd, left, "CREDIT_NOTE", note.number)
            if rd.status == "CREDITED":
                closed.append(rd.number)
    return closed


def _settle_by_receipt(session: Session, gr: GoodsReceipt, gr_line: GrLine) -> None:
    """A receipt on a PO line that owes a replacement (returns in REPLACEMENT_DUE) settles them first, oldest first."""
    left = D(gr_line.qty)
    for rd in session.execute(select(ReturnDelivery).where(ReturnDelivery.po_line_id == gr_line.po_line_id,
                                                           ReturnDelivery.status == "REPLACEMENT_DUE")
                              .order_by(ReturnDelivery.created_at, ReturnDelivery.number).with_for_update()).scalars().all():
        if left <= 0:
            break
        left -= _settle(session, rd, left, "GOODS_RECEIPT", gr.number)


def _unsettle_by_receipt(session: Session, gr: GoodsReceipt) -> None:
    """The replacement receipt was reversed (102): the returns it settled are due again."""
    po_lines = list(session.execute(select(GrLine.po_line_id).where(GrLine.gr_id == gr.id)).scalars())
    for rd in session.execute(select(ReturnDelivery).where(ReturnDelivery.po_line_id.in_(po_lines or [uuid.UUID(int=0)]),
                                                           ReturnDelivery.status.in_(("REPLACEMENT_DUE", "REPLACED")))).scalars().all():
        taken = [x for x in rd.settlements or [] if x.get("type") == "GOODS_RECEIPT" and x.get("ref") == gr.number]
        if not taken:
            continue
        qty = sum((D(x["qty"]) for x in taken), Decimal(0))
        rd.settled_qty = max(D(rd.settled_qty or 0) - qty, Decimal(0))
        rd.settlements = [x for x in rd.settlements if x not in taken]
        if rd.status == "REPLACED":
            rd.closed_at = None
            RD_SM.apply(session, rd, "reopen", reason=f"replacement receipt {gr.number} reversed", rule_set_version="RCV-RETURN")
        else:
            audit.record(session, "RETURN_DELIVERY", rd.id, "SETTLEMENT_REVERSED", object_ref=rd.number,
                         after={"receipt": gr.number, "qty": jsonable(qty), "settledQty": jsonable(rd.settled_qty)})


def close_return(session: Session, rd: ReturnDelivery, reason: str) -> ReturnDelivery:
    """Close an open return by hand when nothing more is due (e.g. the rejected quantity was never invoiced, or the supplier settled it
    outside PIC). The reason is required and audited; the return keeps what was settled before."""
    if len((reason or "").strip()) < 10:
        raise Problem(422, "REASON_REQUIRED", "Say why the return is closed without a credit note or replacement (at least 10 characters)",
                      rule_ref="RCV-RETURN")
    po_line = session.get(PoLine, rd.po_line_id)
    po = session.get(PurchaseOrder, po_line.po_id)
    abac.guard(session, "STOCK_MOVE", po, plant=po_line.plant)
    RD_SM.apply(session, rd, "close", reason=reason, rule_set_version="RCV-RETURN",
                extra_after={"settledQty": jsonable(rd.settled_qty or 0), "qty": jsonable(rd.qty)})
    rd.settlements = [*(rd.settlements or []), {"type": "MANUAL", "ref": principal(session).email,
                                                "qty": jsonable(max(D(rd.qty) - D(rd.settled_qty or 0), Decimal(0))),
                                                "at": clock.now().isoformat(), "reason": reason}]
    rd.closed_at = clock.now()
    outbox.emit(session, "return_delivery.closed", "RETURN_DELIVERY", rd.id, rd.number,
                {"po": po.number, "poLine": po_line.line_no, "qty": jsonable(rd.qty), "reason": reason, "supplierId": str(po.supplier_id)})
    return rd


def return_view(session: Session, rd: ReturnDelivery, *, po_line: Optional[PoLine] = None, po: Optional[PurchaseOrder] = None,
                gr_number: Optional[str] = None, supplier: Optional[Supplier] = None) -> dict:
    po_line = po_line or session.get(PoLine, rd.po_line_id)
    po = po or session.get(PurchaseOrder, po_line.po_id)
    supplier = supplier or session.get(Supplier, po.supplier_id)
    if gr_number is None:
        gr_number = session.execute(select(GoodsReceipt.number).where(GoodsReceipt.id == rd.gr_id)).scalar_one_or_none()
    material = session.get(Material, po_line.material_id) if po_line.material_id else None
    open_qty = max(D(rd.qty) - D(rd.settled_qty or 0), Decimal(0)) if rd.status in OPEN_RETURNS else Decimal(0)
    return {"id": str(rd.id), "number": rd.number, "status": rd.status, "gr": gr_number, "po": po.number, "poLine": po_line.line_no,
            "supplier": supplier.code if supplier else None, "supplierName": supplier.legal_name if supplier else None,
            "material": material.number if material else None, "description": po_line.description, "uom": po_line.uom, "plant": po_line.plant,
            "qty": jsonable(rd.qty), "settledQty": jsonable(rd.settled_qty or 0), "openQty": jsonable(open_qty),
            "valueMinor": line_amount(D(rd.qty), po_line.unit_price_minor), "openValueMinor": line_amount(open_qty, po_line.unit_price_minor),
            "reason": rd.reason, "replacementRequired": rd.replacement_required, "creditNoteExpected": rd.credit_note_expected,
            "settlements": rd.settlements or [], "createdAt": rd.created_at.isoformat() if rd.created_at else None,
            "closedAt": rd.closed_at.isoformat() if rd.closed_at else None, "version": rd.row_version}


def list_returns(session: Session, *, status: Optional[str] = None, open_only: bool = False, supplier: Optional[str] = None,
                 po: Optional[str] = None, gr: Optional[str] = None, plant: Optional[str] = None, supplier_id: Optional[uuid.UUID] = None,
                 plants: Optional[list] = None, limit: int = 200) -> dict:
    """Return deliveries with their settlement (filters: status, open, supplier code, PO, receipt, plant). ``supplier_id`` limits a supplier
    user to their own returns; ``plants`` is the caller's plant read scope (ABAC)."""
    if status and status.upper() not in RETURN_STATUSES:
        raise Problem(422, "INVALID_STATUS", f"status must be one of {', '.join(RETURN_STATUSES)}")
    query = (select(ReturnDelivery, PoLine, PurchaseOrder, Supplier, GoodsReceipt.number)
             .join(PoLine, PoLine.id == ReturnDelivery.po_line_id).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id)
             .join(Supplier, Supplier.id == PurchaseOrder.supplier_id).join(GoodsReceipt, GoodsReceipt.id == ReturnDelivery.gr_id))
    if status:
        query = query.where(ReturnDelivery.status == status.upper())
    if open_only:
        query = query.where(ReturnDelivery.status.in_(OPEN_RETURNS))
    if supplier:
        query = query.where(Supplier.code == supplier)
    if supplier_id is not None:
        query = query.where(PurchaseOrder.supplier_id == supplier_id)
    if po:
        query = query.where(PurchaseOrder.number == po)
    if gr:
        query = query.where(GoodsReceipt.number == gr)
    if plant:
        query = query.where(PoLine.plant == plant)
    if plants is not None:
        query = query.where(PoLine.plant.in_(plants))
    found = session.execute(query.order_by(ReturnDelivery.created_at.desc(), ReturnDelivery.number.desc())
                            .limit(min(max(int(limit), 1), 500))).all()
    items = [return_view(session, rd, po_line=pl, po=po_row, gr_number=gr_no, supplier=sup) for rd, pl, po_row, sup, gr_no in found]
    counts: dict = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {"items": items, "total": len(items), "countsByStatus": counts,
            "openValueMinor": sum(i["openValueMinor"] for i in items)}


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
        # One indexed query (GIN on gr_line.serials): serials of receipts that were reversed (102) are free again, so the corrected receipt
        # of the same serial numbers is accepted.
        repeated = sorted({serial for (found,) in session.execute(
            select(GrLine.serials).join(GoodsReceipt, GoodsReceipt.id == GrLine.gr_id).where(
                GrLine.material_id == line.material_id, GoodsReceipt.status != "REVERSED", GrLine.serials.has_any(postgresql.array(list(serials)))))
            for serial in (found or []) if serial in serials})
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
    _guard_stock_change(session, line.plant, f"components for {po.number}/{line.line_no}", company_code=po.company_code)
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
    _guard_stock_change(session, plant, f"consignment withdrawal of {mat.number}")
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
        _guard_stock_change(session, stock.plant, f"recall of lot {batch}")
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
    po_lines = {l.line_no: l for l in order_svc.lines_of(session, po)}
    if not lines:
        raise Problem(422, "LINES_REQUIRED", "A service entry lists at least one service line", rule_ref="RCV-SES")
    for data in lines:
        if int(data["line"]) not in po_lines:
            raise Problem(422, "UNKNOWN_LINE", f"{po.number} has no line {data['line']}")
        _positive(data["qty"], f"Line {data['line']}")
        if "unit_rate" in data and D(data["unit_rate"]) <= 0:
            raise Problem(422, "INVALID_RATE", f"Line {data['line']}: the unit rate must be positive", rule_ref="RCV-SES")
    entered: dict = {}  # this sheet's value per PO line (a sheet may list a PO line more than once); checked before the sheet exists
    for data in lines:
        line = po_lines[int(data["line"])]
        if not line.ses_required:
            raise rule_violation(f"Line {line.line_no} is not a service line", "P08")
        rate = int(D(data["unit_rate"]) * 100) if "unit_rate" in data else line.unit_price_minor
        entered[line.id] = entered.get(line.id, 0) + line_amount(D(data["qty"]), rate)
        # Approved value + value of other sheets still in approval + this sheet must stay within the PO line.
        in_approval = _ses_value(session, line.id, ("SUBMITTED",))
        if line.ses_approved_minor + in_approval + entered[line.id] > line.net_minor:
            raise rule_violation(f"Line {line.line_no}: service value exceeds the PO line ({line.ses_approved_minor / 100:,.2f} approved, "
                                 f"{in_approval / 100:,.2f} in approval, {entered[line.id] / 100:,.2f} on this sheet; line value "
                                 f"{line.net_minor / 100:,.2f})", "RCV-SES", approvedMinor=line.ses_approved_minor, inApprovalMinor=in_approval,
                                 enteredMinor=entered[line.id], lineValueMinor=line.net_minor)
    ses = ServiceEntry(tenant_id=po.tenant_id, number=next_number(session, "SERVICE_ENTRY"), po_id=po.id, status="DRAFT", method=method.upper(),
                       period_from=period_from, period_to=period_to, entered_by=p.user_id, created_by=p.user_id)
    session.add(ses)
    session.flush()
    total = 0
    for data in lines:
        line = po_lines[int(data["line"])]
        rate = int(D(data["unit_rate"]) * 100) if "unit_rate" in data else line.unit_price_minor
        amount = line_amount(D(data["qty"]), rate)
        session.add(SesLine(tenant_id=po.tenant_id, ses_id=ses.id, po_line_id=line.id, description=data.get("description", line.description),
                            qty=D(data["qty"]), unit_rate_minor=rate, amount_minor=amount, created_by=p.user_id))
        total += amount
    ses.total_minor = total
    return ses


def _ses_value(session: Session, po_line_id, statuses: tuple, exclude=None) -> int:
    query = select(func.coalesce(func.sum(SesLine.amount_minor), 0)).join(ServiceEntry, ServiceEntry.id == SesLine.ses_id).where(
        SesLine.po_line_id == po_line_id, ServiceEntry.status.in_(statuses))
    if exclude is not None:
        query = query.where(ServiceEntry.id != exclude)
    return int(session.execute(query).scalar_one())


def _check_ses_cap(session: Session, ses: ServiceEntry, *, lock: bool) -> None:
    """RCV-SES: approved + in-approval value of every PO line on the sheet stays within the line value (PO lines locked at approval)."""
    amounts: dict = {}
    for line in session.execute(select(SesLine).where(SesLine.ses_id == ses.id)).scalars():
        amounts[line.po_line_id] = amounts.get(line.po_line_id, 0) + line.amount_minor
    for po_line_id, amount in sorted(amounts.items(), key=lambda item: str(item[0])):
        po_line = session.get(PoLine, po_line_id, with_for_update=lock, populate_existing=lock)
        others = _ses_value(session, po_line_id, ("SUBMITTED",), exclude=ses.id) if not lock else 0
        if po_line.ses_approved_minor + others + amount > po_line.net_minor:
            raise rule_violation(f"{ses.number}: line {po_line.line_no} would reach {(po_line.ses_approved_minor + others + amount) / 100:,.2f} "
                                 f"approved / in approval against a line value of {po_line.net_minor / 100:,.2f}", "RCV-SES",
                                 approvedMinor=po_line.ses_approved_minor, sheetMinor=amount, lineValueMinor=po_line.net_minor)


def submit_ses(session: Session, ses: ServiceEntry) -> ServiceEntry:
    po = session.get(PurchaseOrder, ses.po_id)
    if po.status not in ("TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED"):
        raise illegal_transition("Purchase order", po.number, po.status, "service entry")
    if ses.status == "REJECTED":
        _check_ses_cap(session, ses, lock=False)  # a re-submitted sheet competes with the sheets entered since
    SES_SM.apply(session, ses, "submit")
    instance = workflow.start(session, PROCESS, "SERVICE_ENTRY", ses.id, ses.number, {"po": po.number})
    workflow.step(session, instance, "F6-02", outcome="service")
    # SES approver must differ from the supplier user who entered it and from the PO creator.
    workflow.start_approval(session, instance, "SES_APPROVAL", object_type="SERVICE_ENTRY", object_id=ses.id, object_ref=ses.number,
                            chain=["SERVICE_OWNER"], step_id="F6-04", initiator_id=ses.entered_by, exclude=[po.created_by],
                            evidence={"totalMinor": ses.total_minor, "method": ses.method})
    return ses


def resubmit_ses(session: Session, ses: ServiceEntry) -> ServiceEntry:
    """POST /v1/service-entries/{ref}/submit: a DRAFT sheet (created with submit=false) or a REJECTED one is submitted (again) by the
    supplier; ``submit_ses`` re-checks the PO line value against the sheets entered since and opens a new approval."""
    require_supplier_user(session, session.get(PurchaseOrder, ses.po_id).supplier_id)
    if not SES_SM.can(ses.status, "submit"):
        raise illegal_transition("Service entry", ses.number, ses.status, "submit")
    if ses.status == "DRAFT":
        _check_ses_cap(session, ses, lock=False)
    return submit_ses(session, ses)


def revoke_ses(session: Session, ses: ServiceEntry, reason: str) -> ServiceEntry:
    """APPROVED -> REVOKED: the service owner withdraws an approval given in error. The approved value leaves the PO line again; refused while
    an invoice that is not rejected claims the line's approved service value beyond what would remain (reject or credit it first)."""
    if len((reason or "").strip()) < 10:
        raise Problem(422, "REASON_REQUIRED", "Say why the approval is revoked (at least 10 characters)", rule_ref="RCV-SES")
    if not SES_SM.can(ses.status, "revoke"):
        raise illegal_transition("Service entry", ses.number, ses.status, "revoke")
    po = session.get(PurchaseOrder, ses.po_id)
    if principal(session).user_id in (ses.entered_by, po.created_by):  # the same four-eyes exclusions as the approval itself
        raise Problem(409, "SOD_CONFLICT", "The approval of a service entry is revoked by a service owner other than the supplier and the "
                      "PO creator", rule_ref="RCV-SES")
    amounts: dict = {}
    for line in session.execute(select(SesLine).where(SesLine.ses_id == ses.id)).scalars():
        amounts[line.po_line_id] = amounts.get(line.po_line_id, 0) + line.amount_minor
    from app.pic.services import payables
    for po_line_id, amount in sorted(amounts.items(), key=lambda item: str(item[0])):
        po_line = session.get(PoLine, po_line_id, with_for_update=True, populate_existing=True)
        abac.guard(session, "GR_POST", po, plant=po_line.plant)
        _, pending_value = payables.pending_on_line(session, po_line.id, None)
        if po_line.ses_approved_minor - amount < po_line.invoiced_minor + pending_value:
            raise rule_violation(f"{ses.number}: line {po_line.line_no} is invoiced against the approved service value "
                                 f"({fmt_minor(po_line.invoiced_minor + pending_value)} invoiced or in matching); reject or credit the invoice first",
                                 "RCV-SES")
        po_line.ses_approved_minor -= amount
    SES_SM.apply(session, ses, "revoke", reason=reason, extra_after={"totalMinor": ses.total_minor})
    outbox.emit(session, "service_entry.revoked", "SERVICE_ENTRY", ses.id, ses.number, {"po": po.number, "totalMinor": ses.total_minor, "reason": reason})
    instance = workflow.find(session, "SERVICE_ENTRY", ses.id, PROCESS)
    if instance is not None:
        workflow.step(session, instance, "F6-09", outcome=f"approval revoked: {reason}")
    return ses


def fmt_minor(minor: int) -> str:
    return f"{minor / 100:,.2f}"


@workflow.on_task("SES_APPROVAL")
def _ses_decided(session: Session, task: Task, outcome: str) -> None:
    ses = session.get(ServiceEntry, task.object_id)
    instance = workflow.find(session, "SERVICE_ENTRY", ses.id, PROCESS)
    if outcome != "APPROVED":
        SES_SM.apply(session, ses, "reject", reason=task.comment)
        workflow.end(session, instance, "F6-09", outcome=f"rejected: {task.comment}")
        return
    # Two sheets approved concurrently must not overrun the PO line: re-check under a lock on the PO line(s).
    _check_ses_cap(session, ses, lock=True)
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
