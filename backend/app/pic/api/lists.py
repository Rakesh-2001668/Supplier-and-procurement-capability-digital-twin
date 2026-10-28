"""Collection endpoints (worklists) with cursor pagination and filters.

Supplier-portal users only ever see documents of their own company.
"""
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.pic.api.deps import uow
from app.pic.api.pagination import Page, paginate
from app.pic.models import (
    AsnLine, GrLine, PoLine, Asn, AuditEvent, BankChangeRequest, CatalogueItem, Contract, CostObject, GoodsReceipt, InspectionLot, IntegrationMessage, Invitee,
    Invoice, InvoiceException, Material, MaterialRequest, MrpRun, Plant, PlannedOrder, ProcessDefinition, ProcessInstance,
    PurchaseOrder, Requisition, ServiceEntry, SourcingEvent, Supplier, SupplierCategoryStatus,
)
from app.pic.platform.auth import READ, Principal, require, require_any
from app.pic.platform.serialize import jsonable, row

router = APIRouter(prefix="/v1", tags=["Worklists"])
PORTAL = require_any(READ, "supplier:portal")


def _supplier_codes(session) -> dict:
    return {s.id: s.code for s in session.execute(select(Supplier)).scalars()}


def _is_supplier(p: Principal) -> bool:
    return "SUPPLIER_USER" in p.roles


def _with_supplier(codes: dict):
    return lambda obj: row(obj, extra={"supplier_code": codes.get(obj.supplier_id)})


@router.get("/requisitions")
def requisitions(status: Optional[str] = None, origin: Optional[str] = None, mine: bool = False, page: Page = Depends(),
                 p: Principal = Depends(require(READ))):
    with uow(p) as s:
        q = select(Requisition)
        if status:
            q = q.where(Requisition.status == status.upper())
        if origin:
            q = q.where(Requisition.origin == origin.upper())
        if mine:
            q = q.where(Requisition.requester_id == p.user_id)
        return paginate(s, q, Requisition, page)


@router.get("/mrp/runs")
def mrp_runs(page: Page = Depends(), p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return paginate(s, select(MrpRun), MrpRun, page, lambda r: row(r, only=[
            "id", "number", "mode", "plant", "run_date", "status", "materials_planned", "planned_orders_created", "exceptions_raised",
            "created_at", "completed_at"]))


@router.get("/planned-orders")
def planned_orders(status: Optional[str] = None, page: Page = Depends(), p: Principal = Depends(require(READ))):
    with uow(p) as s:
        materials = {m.id: m.number for m in s.execute(select(Material)).scalars()}
        q = select(PlannedOrder)
        if status:
            q = q.where(PlannedOrder.status == status.upper())
        return paginate(s, q, PlannedOrder, page, lambda o: row(o, extra={"material": materials.get(o.material_id)}))


@router.get("/sourcing/events")
def sourcing_events(status: Optional[str] = None, page: Page = Depends(), p: Principal = Depends(PORTAL)):
    with uow(p) as s:
        q = select(SourcingEvent)
        if status:
            q = q.where(SourcingEvent.status == status.upper())
        if _is_supplier(p):
            q = q.where(SourcingEvent.id.in_(select(Invitee.event_id).where(Invitee.supplier_id == p.supplier_id)),
                        SourcingEvent.status != "DRAFT")
        return paginate(s, q, SourcingEvent, page, lambda e: row(e, only=[
            "id", "number", "type", "title", "category", "status", "round", "close_at", "published_at", "baseline_price_minor",
            "created_at"]))


@router.get("/contracts")
def contracts(status: Optional[str] = None, page: Page = Depends(), p: Principal = Depends(PORTAL)):
    with uow(p) as s:
        codes = _supplier_codes(s)
        q = select(Contract)
        if status:
            q = q.where(Contract.status == status.upper())
        if _is_supplier(p):
            q = q.where(Contract.supplier_id == p.supplier_id)
        return paginate(s, q, Contract, page, _with_supplier(codes))


@router.get("/purchase-orders")
def purchase_orders(status: Optional[str] = None, supplier: Optional[str] = None, page: Page = Depends(), p: Principal = Depends(PORTAL)):
    with uow(p) as s:
        codes = _supplier_codes(s)
        q = select(PurchaseOrder)
        if status:
            q = q.where(PurchaseOrder.status.in_([x.strip().upper() for x in status.split(",")]))
        if supplier:
            q = q.where(PurchaseOrder.supplier_id.in_([k for k, v in codes.items() if v == supplier]))
        if _is_supplier(p):
            q = q.where(PurchaseOrder.supplier_id == p.supplier_id)
        services: dict = {}
        for pl in s.execute(select(PoLine)).scalars():
            services[pl.po_id] = services.get(pl.po_id, True) and pl.ses_required
        return paginate(s, q, PurchaseOrder, page, lambda po: row(po, extra={"supplier_code": codes.get(po.supplier_id),
                                                                              "services": services.get(po.id, False)}))


@router.get("/asns")
def asns(status: Optional[str] = None, page: Page = Depends(), p: Principal = Depends(PORTAL)):
    with uow(p) as s:
        codes = _supplier_codes(s)
        pos = {po.id: po.number for po in s.execute(select(PurchaseOrder)).scalars()}
        q = select(Asn)
        if status:
            q = q.where(Asn.status == status.upper())
        if _is_supplier(p):
            q = q.where(Asn.supplier_id == p.supplier_id)
        po_lines = {pl.id: pl for pl in s.execute(select(PoLine)).scalars()}

        def render(a):
            lines = [{"poLineId": str(x.po_line_id), "line": po_lines[x.po_line_id].line_no, "description": po_lines[x.po_line_id].description,
                      "qty": jsonable(x.qty), "receivedQty": jsonable(x.received_qty), "batches": x.batches}
                     for x in s.execute(select(AsnLine).where(AsnLine.asn_id == a.id)).scalars()]
            return row(a, extra={"supplier_code": codes.get(a.supplier_id), "po": pos.get(a.po_id), "lines": lines})
        return paginate(s, q, Asn, page, render)


@router.get("/goods-receipts")
def goods_receipts(status: Optional[str] = None, page: Page = Depends(), p: Principal = Depends(require(READ))):
    with uow(p) as s:
        pos = {po.id: po.number for po in s.execute(select(PurchaseOrder)).scalars()}
        q = select(GoodsReceipt)
        if status:
            q = q.where(GoodsReceipt.status == status.upper())
        return paginate(s, q, GoodsReceipt, page, lambda g: row(g, extra={"po": pos.get(g.po_id)}))


@router.get("/inspection-lots")
def inspection_lots(status: Optional[str] = "OPEN", page: Page = Depends(), p: Principal = Depends(require(READ))):
    with uow(p) as s:
        grs = {g.id: g for g in s.execute(select(GoodsReceipt)).scalars()}
        pos = {po.id: po for po in s.execute(select(PurchaseOrder)).scalars()}
        codes = _supplier_codes(s)
        gr_lines = {gl.id: gl for gl in s.execute(select(GrLine)).scalars()}
        po_lines = {pl.id: pl for pl in s.execute(select(PoLine)).scalars()}

        def render(lot):
            gr = grs.get(lot.gr_id)
            po = pos.get(gr.po_id) if gr else None
            gl = gr_lines.get(lot.gr_line_id)
            pl = po_lines.get(gl.po_line_id) if gl else None
            return row(lot, extra={"gr": gr.number if gr else None, "po": po.number if po else None,
                                   "supplier_code": codes.get(po.supplier_id) if po else None,
                                   "description": pl.description if pl else None, "batch": gl.batch if gl else None})
        q = select(InspectionLot)
        if status:
            q = q.where(InspectionLot.status == status.upper())
        return paginate(s, q, InspectionLot, page, render)


@router.get("/service-entries")
def service_entries(status: Optional[str] = None, page: Page = Depends(), p: Principal = Depends(PORTAL)):
    with uow(p) as s:
        pos = {po.id: (po.number, po.supplier_id) for po in s.execute(select(PurchaseOrder)).scalars()}
        q = select(ServiceEntry)
        if status:
            q = q.where(ServiceEntry.status == status.upper())
        if _is_supplier(p):
            q = q.where(ServiceEntry.po_id.in_([k for k, v in pos.items() if v[1] == p.supplier_id]))
        codes = _supplier_codes(s)
        return paginate(s, q, ServiceEntry, page, lambda e: row(e, extra={"po": pos.get(e.po_id, (None, None))[0],
                                                                            "supplier_code": codes.get(pos.get(e.po_id, (None, None))[1])}))


@router.get("/invoices")
def invoices(status: Optional[str] = None, page: Page = Depends(), p: Principal = Depends(PORTAL)):
    with uow(p) as s:
        codes = _supplier_codes(s)
        open_exc = {}
        for exc in s.execute(select(InvoiceException).where(InvoiceException.status == "OPEN")).scalars():
            open_exc[exc.invoice_id] = open_exc.get(exc.invoice_id, 0) + 1
        q = select(Invoice)
        if status:
            q = q.where(Invoice.status.in_([x.strip().upper() for x in status.split(",")]))
        if _is_supplier(p):
            q = q.where(Invoice.supplier_id == p.supplier_id)
        return paginate(s, q, Invoice, page, lambda i: row(i, extra={"supplier_code": codes.get(i.supplier_id),
                                                                         "open_exceptions": open_exc.get(i.id, 0)}))


@router.get("/suppliers")
def suppliers(page: Page = Depends(), p: Principal = Depends(require(READ))):
    with uow(p) as s:
        cats: dict = {}
        for c in s.execute(select(SupplierCategoryStatus)).scalars():
            cats.setdefault(c.supplier_id, {})[c.category] = c.status
        return paginate(s, select(Supplier), Supplier, page, lambda sup: row(sup, extra={"categories": cats.get(sup.id, {})}))


@router.get("/bank-changes")
def bank_changes(status: Optional[str] = None, supplier: Optional[str] = None, page: Page = Depends(),
                 p: Principal = Depends(require(READ))):
    with uow(p) as s:
        codes = _supplier_codes(s)
        q = select(BankChangeRequest)
        if supplier:
            q = q.where(BankChangeRequest.supplier_id.in_([k for k, v in codes.items() if v == supplier]))
        if status:
            q = q.where(BankChangeRequest.status == status.upper())
        return paginate(s, q, BankChangeRequest, page, _with_supplier(codes))


@router.get("/materials")
def materials(page: Page = Depends(), p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return paginate(s, select(Material), Material, page)


@router.get("/materials/requests")
def material_requests(status: Optional[str] = None, page: Page = Depends(), p: Principal = Depends(require(READ))):
    with uow(p) as s:
        q = select(MaterialRequest)
        if status:
            q = q.where(MaterialRequest.status == status.upper())
        return paginate(s, q, MaterialRequest, page)


@router.get("/processes")
def processes(flow: Optional[str] = None, status: Optional[str] = None, page: Page = Depends(), p: Principal = Depends(require(READ))):
    with uow(p) as s:
        q = select(ProcessInstance)
        if flow:
            keys = [d.key for d in s.execute(select(ProcessDefinition).where(ProcessDefinition.flow_id == flow.upper())).scalars()]
            q = q.where(ProcessInstance.process_key.in_(keys))
        if status:
            q = q.where(ProcessInstance.status == status.upper())
        return paginate(s, q, ProcessInstance, page, lambda i: row(i, only=[
            "id", "process_key", "business_type", "business_ref", "status", "current_step", "started_at", "ended_at", "created_at"]))


@router.get("/integration/messages")
def integration_messages(status: Optional[str] = None, page: Page = Depends(), p: Principal = Depends(require("admin:integration"))):
    with uow(p) as s:
        q = select(IntegrationMessage)
        if status:
            q = q.where(IntegrationMessage.status == status.upper())
        return paginate(s, q, IntegrationMessage, page)


@router.get("/audit")
def audit_explorer(object_type: Optional[str] = None, action: Optional[str] = None, actor: Optional[str] = None, limit: int = 100,
                   p: Principal = Depends(require("admin:audit"))):
    with uow(p) as s:
        q = select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(min(limit, 500))
        if object_type:
            q = q.where(AuditEvent.object_type == object_type.upper())
        if action:
            q = q.where(AuditEvent.action == action.upper())
        if actor:
            q = q.where(AuditEvent.actor.ilike(f"%{actor}%"))
        return {"items": [{"seq": e.seq, "ts": e.ts.isoformat(), "objectType": e.object_type, "objectRef": e.object_ref,
                           "action": e.action, "actor": e.actor, "reason": e.reason, "ruleSetVersion": e.rule_set_version,
                           "aiRef": e.ai_ref, "hash": e.hash[:16]} for e in s.execute(q).scalars()], "nextCursor": None}


@router.get("/reference")
def reference_data(p: Principal = Depends(PORTAL)):
    """Values for form pickers: plants, cost objects, materials, suppliers, catalogue."""
    with uow(p) as s:
        return {
            "plants": [{"code": x.code, "name": x.name} for x in s.execute(select(Plant).order_by(Plant.code)).scalars()],
            "costObjects": [{"type": x.type, "code": x.code, "name": x.name} for x in s.execute(select(CostObject).order_by(CostObject.code)).scalars()],
            "materials": [{"number": m.number, "description": m.description, "uom": m.base_uom, "type": m.type, "category": m.category,
                           "standardPriceMinor": m.standard_price_minor} for m in s.execute(select(Material).order_by(Material.number)).scalars()],
            "suppliers": [] if _is_supplier(p) else [{"code": x.code, "name": x.legal_name, "status": x.status}
                                                     for x in s.execute(select(Supplier).order_by(Supplier.code)).scalars()],
            "catalogue": [{"id": str(c.id), "description": c.description, "priceMinor": c.price_minor, "uom": c.uom,
                           "category": c.category} for c in s.execute(select(CatalogueItem).where(CatalogueItem.active.is_(True))).scalars()],
        }
