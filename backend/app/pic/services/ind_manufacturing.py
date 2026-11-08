"""Manufacturing template controls (BP §23, M02-C1): self-billing (ERS) on scheduling agreements (pending workflow 35),
Kanban cards and reorder-point planning parameters for C-parts (36). The weekly / monthly MRP buckets (37) are in planning.py.

Each control is driven by a tenant rule set carried by the manufacturing template: SELF-BILLING and KANBAN. A tenant whose
template does not carry the rule gets CONTROL_NOT_ENABLED."""
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    Contract, ContractLine, GoodsReceipt, GrLine, Invoice, InvoiceLine, KanbanCard, Material, PlanningParameter, PoLine, PurchaseOrder,
    Requisition,
)
from app.pic.platform import audit, clock, outbox, workflow
from app.pic.platform.core import link
from app.pic.platform.errors import Problem, illegal_transition, not_found, rule_violation
from app.pic.platform.money import D, line_amount, tax_amount
from app.pic.platform.serialize import jsonable
from app.pic.services import ind_common
from app.pic.services.common import by_ref, material_by_number, principal, supplier_ref

ERS = "ERS"
KANBAN_STATUSES = ("FULL", "EMPTY", "REPLENISHING", "SUSPENDED")


# ---------------------------------------------------------------- 35 self-billing on scheduling agreements
def _pending_qty(session: Session, po_line_ids: list) -> dict:
    """Quantity on unposted, non-rejected invoices (including earlier ERS documents) per PO line."""
    pending: dict = {}
    if not po_line_ids:
        return pending
    for inv_line in session.execute(select(InvoiceLine.po_line_id, func.sum(InvoiceLine.qty)).join(Invoice, Invoice.id == InvoiceLine.invoice_id).where(
            InvoiceLine.po_line_id.in_(po_line_ids), Invoice.status.notin_(("POSTED", "PAID", "REJECTED"))).group_by(InvoiceLine.po_line_id)):
        pending[inv_line[0]] = D(inv_line[1])
    return pending


def open_call_offs(session: Session, supplier_id: uuid.UUID, company_code: str, period_to: date, contract_types) -> list[dict]:
    """Call-off deliveries of the supplier's scheduling agreements that were received and accepted up to ``period_to`` and are not
    yet invoiced or in an unposted invoice: what a self-billing run settles."""
    candidates = session.execute(
        select(PoLine, PurchaseOrder, Contract).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id)
        .join(ContractLine, ContractLine.id == PoLine.contract_line_id).join(Contract, Contract.id == ContractLine.contract_id)
        .where(PurchaseOrder.supplier_id == supplier_id, PurchaseOrder.company_code == company_code, Contract.type.in_(list(contract_types)),
               PoLine.gr_required.is_(True), PoLine.ers.is_(False), PurchaseOrder.status.notin_(("CANCELLED", "DRAFT")))
        .order_by(PurchaseOrder.number, PoLine.line_no)).all()
    ids = [line.id for line, _, _ in candidates]
    delivered = {}
    if ids:
        delivered = {po_line_id: D(total) for po_line_id, total in session.execute(
            select(GrLine.po_line_id, func.sum(GrLine.accepted_qty)).join(GoodsReceipt, GoodsReceipt.id == GrLine.gr_id)
            .where(GrLine.po_line_id.in_(ids), GoodsReceipt.posting_date <= period_to, GoodsReceipt.status != "REVERSED")
            .group_by(GrLine.po_line_id))}
    pending = _pending_qty(session, ids)
    out = []
    for line, po, contract in candidates:
        open_qty = delivered.get(line.id, Decimal(0)) - D(line.invoiced_qty) - pending.get(line.id, Decimal(0))
        if open_qty > 0:
            out.append({"poLine": line, "po": po, "contract": contract, "qty": open_qty, "deliveredQty": delivered.get(line.id, Decimal(0)),
                        "valueMinor": line_amount(open_qty, line.unit_price_minor)})
    return out


def preview_self_billing(session: Session, *, supplier: str, period_to: date, company_code: str = "1000") -> dict:
    rule = ind_common.require_rule(session, "SELF-BILLING", "Self-billing (ERS)", company_code=company_code)
    supplier_row = supplier_ref(session, supplier)
    rows = open_call_offs(session, supplier_row.id, company_code, period_to, rule.body.get("contractTypes") or ["SCHEDULING_AGREEMENT"])
    return {"supplier": supplier_row.code, "periodTo": period_to.isoformat(), "rule": rule.ref,
            "lines": [{"contract": r["contract"].number, "po": r["po"].number, "line": r["poLine"].line_no, "description": r["poLine"].description,
                       "qty": jsonable(r["qty"]), "unitPriceMinor": r["poLine"].unit_price_minor, "valueMinor": r["valueMinor"]} for r in rows],
            "totalMinor": sum(r["valueMinor"] for r in rows)}


def settle_scheduling_agreement(session: Session, *, supplier: str, period_to: date, company_code: str = "1000",
                                reference: Optional[str] = None) -> Invoice:
    """Self-billing (ERS) for the call-off deliveries of a supplier's scheduling agreements in a settlement period: one AP document
    for everything received and accepted up to ``period_to`` and not yet invoiced, at the call-off price (the contract price valid
    when the order was released, index resets included), with the GST rate and HSN of the order line. It runs the duplicate check
    and the three-way match (settled quantity ≤ accepted quantity) like a supplier invoice; accounts payable approves and posts it.
    Whatever is settled this way cannot be invoiced again by the supplier: the invoiced quantity of the order line is used up."""
    from app.pic.services import payables

    p = principal(session)
    rule = ind_common.require_rule(session, "SELF-BILLING", "Self-billing (ERS)", company_code=company_code)
    if not set(p.roles) & {"AP_CLERK", "FINANCE_CONTROLLER"}:
        raise Problem(403, "FORBIDDEN", "Self-billing settlement runs in accounts payable or finance")
    supplier_row = supplier_ref(session, supplier)
    enrolled = rule.body.get("suppliers") or []
    if enrolled and supplier_row.code not in enrolled:
        raise rule_violation(f"{supplier_row.code} is not enrolled for self-billing (rule SELF-BILLING suppliers: {', '.join(enrolled)})", rule.ref)
    open_lines = open_call_offs(session, supplier_row.id, company_code, period_to, rule.body.get("contractTypes") or ["SCHEDULING_AGREEMENT"])
    if not open_lines:
        raise rule_violation(f"Nothing to settle: no unsettled call-off deliveries from {supplier_row.code} up to {period_to.isoformat()}", rule.ref)
    fiscal_year = clock.fiscal_year(period_to)
    base = f"ERS-{supplier_row.code}-{period_to:%Y%m}"
    taken = {n for (n,) in session.execute(select(Invoice.number).where(Invoice.number.like(f"{base}%"))).all()}
    number = base if base not in taken else next(f"{base}-{i}" for i in range(2, 100) if f"{base}-{i}" not in taken)
    pos = {r["po"].id for r in open_lines}
    invoice = Invoice(tenant_id=current_tenant(session), number=number, supplier_invoice_no=number, fiscal_year=fiscal_year,
                      company_code=company_code, supplier_id=supplier_row.id, po_id=open_lines[0]["po"].id if len(pos) == 1 else None,
                      invoice_date=period_to, channel=ERS, irn=None, currency="INR", net_minor=0, tax_minor=0, gross_minor=0, retention_minor=0,
                      status="CAPTURED", created_by=p.user_id)
    session.add(invoice)
    session.flush()
    net_total = tax_total = 0
    for index, row in enumerate(open_lines, start=1):
        po_line, po, qty = row["poLine"], row["po"], row["qty"]
        net = line_amount(qty, po_line.unit_price_minor)
        tax = tax_amount(net, po_line.gst_rate)
        session.add(InvoiceLine(tenant_id=invoice.tenant_id, invoice_id=invoice.id, line_no=index * 10, po_line_id=po_line.id,
                                description=f"Call-off deliveries to {period_to.isoformat()} – {po_line.description}"[:200], qty=qty,
                                unit_price_minor=po_line.unit_price_minor, net_minor=net, hsn_code=po_line.hsn_code, gst_rate=po_line.gst_rate,
                                tax_minor=tax, created_by=p.user_id))
        net_total += net
        tax_total += tax
        link(session, "PURCHASE_ORDER", po.id, po.number, "INVOICE", invoice.id, invoice.number, "settled_by_ers", from_line=po_line.line_no,
             to_line=index * 10)
    invoice.net_minor, invoice.tax_minor, invoice.gross_minor = net_total, tax_total, net_total + tax_total
    session.flush()
    instance = workflow.start(session, payables.PROCESS, "INVOICE", invoice.id, invoice.number, {"ers": supplier_row.code})
    outbox.emit(session, "invoice.captured", "INVOICE", invoice.id, invoice.number,
                {"supplier": supplier_row.code, "grossMinor": invoice.gross_minor, "channel": ERS})
    audit.record(session, "INVOICE", invoice.id, "CAPTURED", object_ref=invoice.number, rule_set_version=rule.ref,
                 after={"supplier": supplier_row.code, "grossMinor": invoice.gross_minor, "channel": ERS, "periodTo": period_to.isoformat(),
                        "selfBilling": "SCHEDULING_AGREEMENT", "supplierReference": reference,
                        "lines": [{"contract": r["contract"].number, "po": r["po"].number, "line": r["poLine"].line_no, "qty": jsonable(r["qty"])}
                                  for r in open_lines]})
    payables._duplicate_check(session, invoice, instance)
    return invoice


# ---------------------------------------------------------------- 36 reorder-point parameters and Kanban
def set_parameters(session: Session, *, material: str, plant: str, reorder_point, max_stock=None, note: Optional[str] = None) -> PlanningParameter:
    """Reorder point and maximum stock of a material at a plant (MRP type VB: order up to the maximum when the reorder point is reached)."""
    p = principal(session)
    mat = material_by_number(session, material)
    reorder_point = D(reorder_point)
    max_stock = D(max_stock) if max_stock is not None else None
    if reorder_point < 0 or (max_stock is not None and max_stock < reorder_point):
        raise rule_violation("The reorder point is not negative and the maximum stock is at least the reorder point", "M02-C1")
    row = session.execute(select(PlanningParameter).where(PlanningParameter.material_id == mat.id, PlanningParameter.plant == plant)).scalar_one_or_none()
    before = None
    if row is None:
        row = PlanningParameter(tenant_id=current_tenant(session), material_id=mat.id, plant=plant, reorder_point=reorder_point, max_stock=max_stock,
                                note=note, created_by=p.user_id)
        session.add(row)
    else:
        before = {"reorderPoint": jsonable(row.reorder_point), "maxStock": jsonable(row.max_stock)}
        row.reorder_point, row.max_stock, row.note = reorder_point, max_stock, note
    session.flush()
    audit.record(session, "MATERIAL", mat.id, "PLANNING_PARAMETERS_SET", object_ref=mat.number, before=before,
                 after={"plant": plant, "reorderPoint": jsonable(reorder_point), "maxStock": jsonable(max_stock)}, rule_set_version="M02-C1")
    return row


MRP_TYPES = ("PD", "PW", "PM", "VB", "KB", "ND")


def _mrp_type(mrp_type: str) -> str:
    mrp_type = (mrp_type or "").upper()
    if mrp_type not in MRP_TYPES:
        raise Problem(422, "INVALID_MRP_TYPE", "mrp_type must be PD, PW, PM, VB, KB or ND")
    return mrp_type


def request_mrp_type(session: Session, material: str, mrp_type: str, reason: Optional[str] = None):
    """The MRP controller asks for another planning mode (MDM governance, flow fixes A7): a material change request for ``mrp_type``,
    approved by the PLANT data steward; on approval the master is versioned and the ERP material master is updated (MAT|n|version)."""
    from app.pic.services import material_changes

    mrp_type = _mrp_type(mrp_type)
    mat = session.execute(select(Material).where(Material.id == material_by_number(session, material).id).with_for_update()).scalar_one()
    text = (reason or "").strip() or f"Planning mode {mrp_type} requested by MRP planning"
    return material_changes.request_change(session, mat, {"mrp_type": mrp_type}, text)


def set_mrp_type(session: Session, material: str, mrp_type: str, reason: Optional[str] = None) -> Material:
    """Planning mode of a material set by a data load (dataset packs, onboarding): PD daily MRP, PW weekly, PM monthly, VB reorder point,
    KB Kanban (not netted), ND no planning. It is a governed change all the same (material_changes.apply_loaded): validated like a change
    request, recorded as an applied change request with a new master version, audited and sent to the ERP. Users go through
    ``request_mrp_type`` (steward approval)."""
    from app.pic.services import material_changes

    mrp_type = _mrp_type(mrp_type)
    mat = material_by_number(session, material)
    if mat.mrp_type == mrp_type:
        return mat
    before = mat.mrp_type
    material_changes.apply_loaded(session, mat, {"mrp_type": mrp_type}, reason or f"MRP type {mrp_type} set by data load")
    audit.record(session, "MATERIAL", mat.id, "MRP_TYPE_SET", object_ref=mat.number, before={"mrpType": before}, after={"mrpType": mrp_type})
    return mat


def create_card(session: Session, *, material: str, plant: str, bin_qty, storage_location: str = "0001", supplier: Optional[str] = None) -> KanbanCard:
    p = principal(session)
    ind_common.require_rule(session, "KANBAN", "Kanban replenishment")
    mat = material_by_number(session, material)
    qty = D(bin_qty)
    if qty <= 0:
        raise Problem(422, "INVALID_QUANTITY", "The bin quantity must be positive", rule_ref="KANBAN")
    supplier_row = supplier_ref(session, supplier) if supplier else None
    card = KanbanCard(tenant_id=current_tenant(session), number=ind_common.number(session, "KANBAN_CARD", "KB-", 1001, 0), material_id=mat.id,
                      plant=plant, storage_location=storage_location, supplier_id=supplier_row.id if supplier_row else None, bin_qty=qty,
                      status="FULL", cycles=0, created_by=p.user_id)
    session.add(card)
    session.flush()
    audit.record(session, "KANBAN_CARD", card.id, "CREATED", object_ref=card.number,
                 after={"material": mat.number, "plant": plant, "storageLocation": storage_location, "binQty": jsonable(qty),
                        "supplier": supplier_row.code if supplier_row else None}, rule_set_version="KANBAN")
    return card


DEFAULT_KANBAN_PURPOSE = "KANBAN_REPLENISHMENT"


def _auto_requisition(rule) -> bool:
    """Rule KANBAN ``autoRequisition`` (default true): an empty card raises its replenishment requisition by itself; false = the MRP
    controller raises it (``POST /v1/kanban/cards/{n}/replenish``)."""
    return rule.body.get("autoRequisition", True) is not False


def signal_empty(session: Session, card: KanbanCard) -> KanbanCard:
    """The bin is empty: the card signals replenishment. With rule KANBAN ``autoRequisition`` the requisition is raised at once when the
    caller is an MRP controller, otherwise by the consumer of the ``kanban.signalled`` event (an agent principal, which may create
    MRP-origin requisitions); without it the card waits EMPTY for the controller's replenish command."""
    rule = ind_common.require_rule(session, "KANBAN", "Kanban replenishment")
    if card.status != "FULL":
        raise illegal_transition("Kanban card", card.number, card.status, "signal")
    card.status, card.signalled_at = "EMPTY", clock.now()
    mat = session.get(Material, card.material_id)
    audit.record(session, "KANBAN_CARD", card.id, "SIGNALLED", object_ref=card.number, before={"status": "FULL"}, after={"status": "EMPTY"},
                 rule_set_version="KANBAN")
    outbox.emit(session, "kanban.signalled", "KANBAN_CARD", card.id, card.number, {"material": mat.number, "plant": card.plant, "binQty": str(card.bin_qty)})
    p = principal(session)
    if _auto_requisition(rule) and ("MRP_CONTROLLER" in p.roles or p.is_agent):
        replenish(session, card)
    return card


def replenish(session: Session, card: KanbanCard) -> Requisition:
    """Replenishment requisition for one bin of a signalled card (origin MRP, reference the card, purpose code from rule KANBAN
    ``purposeCode``); it follows the normal approval route."""
    from app.pic.services import requisition, source

    rule = ind_common.require_rule(session, "KANBAN", "Kanban replenishment")
    if card.status != "EMPTY":
        raise illegal_transition("Kanban card", card.number, card.status, "replenish")
    purpose_code = str(rule.body.get("purposeCode") or DEFAULT_KANBAN_PURPOSE)[:30]
    material = session.get(Material, card.material_id)
    need = clock.today() + timedelta(days=max(int(material.planned_delivery_days or 0) + int(material.gr_processing_days or 0), 2))
    determination = source.determine(session, material, card.plant, need, card.bin_qty)
    price = next((a.unit_price_minor for a in determination.allocations if a.unit_price_minor), None) or material.standard_price_minor or 0
    line = {"item_type": "MATERIAL", "purchase_type": "STOCK", "material": material.number, "qty": card.bin_qty, "uom": material.base_uom,
            "price_est_minor": price, "need_date": need, "storage_location": card.storage_location, "source_determination": determination.as_dict()}
    if card.supplier_id:
        line["preferred_supplier_id"] = card.supplier_id
    pr = requisition.create(session, origin="MRP", origin_ref=card.number, purpose_code=purpose_code,
                            purpose_text=f"Kanban {card.number}: {card.bin_qty} {material.base_uom} {material.number} (empty bin)", plant=card.plant,
                            lines=[line])
    card.status, card.requisition_id = "REPLENISHING", pr.id
    link(session, "KANBAN_CARD", card.id, card.number, "REQUISITION", pr.id, pr.number, "replenished_by")
    audit.record(session, "KANBAN_CARD", card.id, "REPLENISHMENT_REQUESTED", object_ref=card.number, before={"status": "EMPTY"},
                 after={"status": "REPLENISHING", "requisition": pr.number, "source": determination.method, "purposeCode": purpose_code},
                 rule_set_version=rule.ref)
    requisition.submit(session, pr)
    return pr


def refill(session: Session, card: KanbanCard, note: Optional[str] = None) -> KanbanCard:
    """The bin is full again (goods receipt, or confirmed at the line side)."""
    if card.status not in ("EMPTY", "REPLENISHING"):
        raise illegal_transition("Kanban card", card.number, card.status, "refill")
    before = card.status
    card.status, card.replenished_at, card.cycles = "FULL", clock.now(), (card.cycles or 0) + 1
    audit.record(session, "KANBAN_CARD", card.id, "REFILLED", object_ref=card.number, before={"status": before}, after={"status": "FULL", "cycles": card.cycles},
                 reason=note, rule_set_version="KANBAN")
    return card


def set_suspended(session: Session, card: KanbanCard, suspended: bool, reason: str) -> KanbanCard:
    if not (reason or "").strip():
        raise Problem(422, "REASON_REQUIRED", "Give the reason")
    if suspended and card.status != "FULL":
        raise illegal_transition("Kanban card", card.number, card.status, "suspend")
    if not suspended and card.status != "SUSPENDED":
        raise illegal_transition("Kanban card", card.number, card.status, "resume")
    card.status = "SUSPENDED" if suspended else "FULL"
    audit.record(session, "KANBAN_CARD", card.id, "SUSPENDED" if suspended else "RESUMED", object_ref=card.number, reason=reason)
    return card


@outbox.consumer("kanban.signalled", "kanban-replenishment")
def _signalled(session: Session, event) -> None:
    card = session.get(KanbanCard, event.object_id)
    if card is None or card.status != "EMPTY":
        return
    rule = ind_common.rule_or_none(session, "KANBAN")
    if rule is not None and rule.body.get("enabled") is not False and _auto_requisition(rule):
        replenish(session, card)


@outbox.consumer("goods_receipt.posted", "kanban-refill")
def _received(session: Session, event) -> None:
    """A goods receipt refills the replenishing cards it delivers: first the card whose replenishment requisition the received order
    lines came from, once everything received against that requisition covers its bin (partial deliveries add up); then, for receipts
    of a card's material that are not tied to a card's requisition, as many replenishing bins as the quantity covers (oldest signal first)."""
    gr = session.get(GoodsReceipt, uuid.UUID(event.payload["grId"]))
    if gr is None:
        return
    received: dict = {}
    requisitions: set = set()
    for gr_line, po_line in session.execute(select(GrLine, PoLine).join(PoLine, PoLine.id == GrLine.po_line_id).where(GrLine.gr_id == gr.id)).all():
        if not gr_line.material_id:
            continue
        cards = session.execute(select(KanbanCard).where(KanbanCard.requisition_id == po_line.requisition_id, KanbanCard.status == "REPLENISHING")
                                ).scalars().all() if po_line.requisition_id else []
        if cards:
            requisitions.add(po_line.requisition_id)
            continue
        key = (gr_line.material_id, po_line.plant)
        received[key] = received.get(key, Decimal(0)) + D(gr_line.qty)
    for requisition_id in requisitions:
        total = D(session.execute(select(func.coalesce(func.sum(PoLine.received_qty), 0)).where(PoLine.requisition_id == requisition_id)).scalar())
        for card in session.execute(select(KanbanCard).where(KanbanCard.requisition_id == requisition_id, KanbanCard.status == "REPLENISHING")).scalars():
            if total >= card.bin_qty:
                refill(session, card, note=f"goods receipt {gr.number} of its replenishment")
    for (material_id, plant), qty in received.items():
        for card in session.execute(select(KanbanCard).where(KanbanCard.material_id == material_id, KanbanCard.plant == plant,
                                                             KanbanCard.status == "REPLENISHING").order_by(KanbanCard.signalled_at)).scalars():
            if qty < card.bin_qty:
                break
            qty -= card.bin_qty
            refill(session, card, note=f"goods receipt {gr.number}")


def card_view(session: Session, card: KanbanCard) -> dict:
    mat = session.get(Material, card.material_id)
    pr = session.get(Requisition, card.requisition_id) if card.requisition_id else None
    return {"id": str(card.id), "number": card.number, "material": mat.number, "description": mat.description, "plant": card.plant,
            "storageLocation": card.storage_location, "binQty": jsonable(card.bin_qty), "uom": mat.base_uom, "status": card.status,
            "supplierId": str(card.supplier_id) if card.supplier_id else None, "requisition": pr.number if pr else None,
            "requisitionStatus": pr.status if pr else None, "signalledAt": jsonable(card.signalled_at), "replenishedAt": jsonable(card.replenished_at),
            "cycles": card.cycles, "version": card.row_version}
