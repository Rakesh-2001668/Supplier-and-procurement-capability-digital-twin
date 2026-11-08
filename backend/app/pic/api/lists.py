"""Collection endpoints (worklists) with cursor pagination and filters.

Supplier-portal users only ever see documents of their own company.
"""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

from app.pic.api.deps import uow
from app.pic.api.pagination import Page, paginate
from app.pic.models import (
    AsnLine, GrLine, PoLine, Asn, AuditEvent, BankChangeRequest, CatalogueItem, Contract, CostObject, GoodsReceipt, InspectionLot, IntegrationMessage, Invitee,
    Invoice, InvoiceException, Material, MaterialRequest, MrpRun, Plant, PlannedOrder, ProcessDefinition, ProcessInstance,
    PurchaseOrder, Requisition, ServiceEntry, SourcingEvent, Supplier, SupplierCategoryStatus,
)
from app.pic.platform import clock
from app.pic.services import finance_scope
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
    from app.pic.services import planning

    with uow(p) as s:
        plants = planning.readable_plants(s)  # SEC-AZ: a plant-scoped user lists the runs of their plants only
        q = select(MrpRun) if plants is None else select(MrpRun).where(MrpRun.plant.in_(plants))
        return paginate(s, q, MrpRun, page, lambda r: row(r, only=[
            "id", "number", "mode", "plant", "run_date", "status", "materials_planned", "planned_orders_created", "exceptions_raised",
            "created_at", "completed_at"]))


@router.get("/planned-orders")
def planned_orders(status: Optional[str] = None, page: Page = Depends(), p: Principal = Depends(require(READ))):
    with uow(p) as s:
        materials = {m.id: m.number for m in s.execute(select(Material)).scalars()}
        from app.pic.services import planning

        q = select(PlannedOrder)
        plants = planning.readable_plants(s)  # SEC-AZ: plant scope on planning reads
        if plants is not None:
            q = q.where(PlannedOrder.plant.in_(plants))
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
                        SourcingEvent.status != "DRAFT", SourcingEvent.published_at.is_not(None))
        fields = ["id", "number", "type", "title", "category", "status", "round", "close_at", "published_at", "baseline_price_minor",
                  "created_at"]
        if _is_supplier(p):
            fields.remove("baseline_price_minor")  # the buyer's baseline (target) price is never shown to bidders
        return paginate(s, q, SourcingEvent, page, lambda e: row(e, only=fields))


@router.get("/contracts")
def contracts(status: Optional[str] = None, supplier: Optional[str] = None, type: Optional[str] = None, q: Optional[str] = None,
              expiring_within_days: Optional[int] = None, page: Page = Depends(), p: Principal = Depends(PORTAL)):
    """The contract repository. Filters: status, supplier code, type, free text (number or title), contracts ending within N days."""
    with uow(p) as s:
        codes = _supplier_codes(s)
        query = select(Contract)
        if status:
            query = query.where(Contract.status.in_([x.strip().upper() for x in status.split(",") if x.strip()]))
        if supplier:
            query = query.where(Contract.supplier_id.in_([k for k, v in codes.items() if v == supplier]))
        if type:
            query = query.where(Contract.type == type.upper())
        if q and q.strip():
            like = f"%{q.strip()}%"
            query = query.where(Contract.number.ilike(like) | Contract.title.ilike(like))
        if expiring_within_days is not None:
            today = clock.today()
            query = query.where(Contract.status.in_(("ACTIVE", "EXPIRING")), Contract.valid_to >= today,
                                Contract.valid_to <= today + timedelta(days=max(0, expiring_within_days)))
        if _is_supplier(p):
            query = query.where(Contract.supplier_id == p.supplier_id, Contract.status != "DRAFT")  # a draft is internal work
        return paginate(s, query, Contract, page, _with_supplier(codes))


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
def invoices(status: Optional[str] = None, supplier: Optional[str] = None, company_code: Optional[str] = None, q: Optional[str] = None,
             date_from: Optional[date] = None, date_to: Optional[date] = None, due_from: Optional[date] = None, due_to: Optional[date] = None,
             payment_status: Optional[str] = None, payment_block: Optional[bool] = None, match_type: Optional[str] = None,
             exception_type: Optional[str] = None, has_open_exceptions: Optional[bool] = None, msme: Optional[bool] = None,
             min_gross_minor: Optional[int] = Query(None, ge=0), max_gross_minor: Optional[int] = Query(None, ge=0),
             page: Page = Depends(), p: Principal = Depends(PORTAL)):
    """INV-01 worklist: filter by status, supplier, company code, free text (document or supplier invoice number), invoice / due date,
    payment status and block, match type, open exception type, MSME suppliers and gross range."""
    with uow(p) as s:
        codes = _supplier_codes(s)
        open_exc = dict(s.execute(select(InvoiceException.invoice_id, func.count()).where(InvoiceException.status == "OPEN")
                                  .group_by(InvoiceException.invoice_id)).all())
        query = select(Invoice)
        if status:
            query = query.where(Invoice.status.in_([x.strip().upper() for x in status.split(",")]))
        if supplier:
            query = query.where(Invoice.supplier_id.in_(select(Supplier.id).where(Supplier.code.in_([x.strip() for x in supplier.split(",")]))))
        if company_code:
            query = query.where(Invoice.company_code == company_code)
        if q:
            like = f"%{q.strip().replace('%', '').replace('_', '')}%"
            query = query.where(or_(Invoice.number.ilike(like), Invoice.supplier_invoice_no.ilike(like), Invoice.erp_doc_no.ilike(like)))
        if date_from:
            query = query.where(Invoice.invoice_date >= date_from)
        if date_to:
            query = query.where(Invoice.invoice_date <= date_to)
        if due_from:
            query = query.where(Invoice.due_date >= due_from)
        if due_to:
            query = query.where(Invoice.due_date <= due_to)
        if payment_status:
            query = query.where(Invoice.payment_status.in_([x.strip().upper() for x in payment_status.split(",")]))
        if payment_block is not None:
            query = query.where(Invoice.payment_block.is_(payment_block))
        if match_type:
            query = query.where(Invoice.match_type.in_([x.strip().upper() for x in match_type.split(",")]))
        if exception_type:
            query = query.where(Invoice.id.in_(select(InvoiceException.invoice_id).where(
                InvoiceException.status == "OPEN", InvoiceException.type.in_([x.strip().upper() for x in exception_type.split(",")]))))
        if has_open_exceptions is not None:
            open_ids = select(InvoiceException.invoice_id).where(InvoiceException.status == "OPEN")
            query = query.where(Invoice.id.in_(open_ids) if has_open_exceptions else Invoice.id.not_in(open_ids))
        if msme is not None:
            msme_ids = select(Supplier.id).where(Supplier.msme_class.is_not(None))
            query = query.where(Invoice.supplier_id.in_(msme_ids) if msme else Invoice.supplier_id.not_in(msme_ids))
        if min_gross_minor is not None:
            query = query.where(Invoice.gross_minor >= min_gross_minor)
        if max_gross_minor is not None:
            query = query.where(Invoice.gross_minor <= max_gross_minor)
        if _is_supplier(p):
            query = query.where(Invoice.supplier_id == p.supplier_id)
        query = finance_scope.restrict_invoices(query, s)  # ABAC read scope: the user's company codes and plants
        return paginate(s, query, Invoice, page, lambda i: row(i, extra={"supplier_code": codes.get(i.supplier_id),
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
    """Values for form pickers: plants, cost objects, materials, suppliers, catalogue. Supplier users get only what a portal
    form can use: plants, materials without internal standard prices, and their own active catalogue items."""
    with uow(p) as s:
        if _is_supplier(p):
            own = select(CatalogueItem).where(CatalogueItem.active.is_(True), CatalogueItem.supplier_id == p.supplier_id)
            return {
                "plants": [{"code": x.code, "name": x.name} for x in s.execute(select(Plant).where(Plant.active.is_(True)).order_by(Plant.code)).scalars()],
                "costObjects": [],
                "materials": [{"number": m.number, "description": m.description, "uom": m.base_uom, "type": m.type, "category": m.category}
                              for m in s.execute(select(Material).order_by(Material.number)).scalars()],
                "suppliers": [],
                "catalogue": [{"id": str(c.id), "description": c.description, "priceMinor": c.price_minor, "uom": c.uom,
                               "category": c.category} for c in s.execute(own).scalars()],
            }
        return {
            "plants": [{"code": x.code, "name": x.name} for x in s.execute(select(Plant).where(Plant.active.is_(True)).order_by(Plant.code)).scalars()],
            "costObjects": [{"type": x.type, "code": x.code, "name": x.name} for x in s.execute(select(CostObject).where(CostObject.active.is_(True)).order_by(CostObject.code)).scalars()],
            "materials": [{"number": m.number, "description": m.description, "uom": m.base_uom, "type": m.type, "category": m.category,
                           "standardPriceMinor": m.standard_price_minor} for m in s.execute(select(Material).order_by(Material.number)).scalars()],
            "suppliers": [] if _is_supplier(p) else [{"code": x.code, "name": x.legal_name, "status": x.status}
                                                     for x in s.execute(select(Supplier).order_by(Supplier.code)).scalars()],
            "catalogue": [{"id": str(c.id), "description": c.description, "priceMinor": c.price_minor, "uom": c.uom,
                           "category": c.category} for c in s.execute(select(CatalogueItem).where(CatalogueItem.active.is_(True))).scalars()],
        }
