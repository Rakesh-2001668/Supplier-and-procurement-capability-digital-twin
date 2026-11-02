"""Inventory (BP M09 / M02 stock): the stock ledger reads (list, summary, alerts, stock card, movement ledger and CSV export) and the governed
inventory commands: stock postings (transfer, block, unblock, scrap) with maker-checker approval, physical inventory (blind cycle count, recount,
approval, difference posting) and stock reservations (demand for MRP). Every write is audited; unsafe repeats are refused or replayed.

Document references are numbers (STP-1001, PHI-1001, RSV-1001) or ids; a number that contains slashes is accepted as is or as %2F."""
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.pic import views
from app.pic.api.deps import idempotency_key, idempotent, uow
from app.pic.api.pagination import Page, paginate
from app.pic.config import get_settings
from app.pic.models import PhysicalInventory, StockPosting, StockReservation
from app.pic.platform import inventory_defaults as ir
from app.pic.platform.auth import READ, Principal, require, require_any
from app.pic.platform.core import check_if_match, etag
from app.pic.platform.errors import Problem, not_found
from app.pic.platform.serialize import jsonable
from app.pic.services import inventory, stock_ledger, stock_reads

router = APIRouter(prefix="/v1", tags=["Inventory"])
IfMatch = Header(default=None, alias="If-Match")


def _precondition(doc, if_match: Optional[str], what: str) -> None:
    """If-Match (the ETag of the document's GET) refuses a write on a stale view with 412; required when PIC_REQUIRE_IF_MATCH is on."""
    if if_match is None and get_settings().if_match_required:
        raise Problem(428, "PRECONDITION_REQUIRED", f"Send If-Match with the ETag of GET {what}")
    check_if_match(doc, if_match)


def _in_plants(s, doc) -> None:
    """A document of a plant outside the user's plants does not exist for them."""
    plants = stock_reads.visible_plants(s)
    if plants is not None and doc.plant not in plants:
        raise not_found(type(doc).__name__, getattr(doc, "number", doc.id))


def _csv(value: Optional[str]) -> list[str]:
    return [x.strip().upper() for x in (value or "").split(",") if x.strip()]


# ================================================================ reads: the stock ledger
@router.get("/stock")
def list_stock(material: Optional[str] = Query(None, description="material number (prefix) or description text"), plant: Optional[str] = None,
               storage_location: Optional[str] = None, stock_type: Optional[str] = Query(None, description="comma list: UNRESTRICTED,QUALITY,BLOCKED,CONSIGNMENT,SUBCONTRACTOR"),
               batch: Optional[str] = None, material_group: Optional[str] = None, belowSafety: bool = False, expiringWithinDays: Optional[int] = Query(None, ge=0, le=3650),
               onlyNonZero: bool = True, page: Page = Depends(), p: Principal = Depends(require(READ))):
    """The stock balances by plant, storage location, stock type and batch with value at standard price, expiry, safety stock, reorder point and days of cover."""
    with uow(p) as s:
        query = stock_reads.stock_query(s, material=material, plant=plant, storage_location=storage_location, stock_type=stock_type, batch=batch,
                                        material_group=material_group, below_safety=belowSafety, expiring_within_days=expiringWithinDays,
                                        only_non_zero=onlyNonZero)
        found = paginate(s, query, stock_reads.Stock, page, lambda x: x)
        return {"items": stock_reads.stock_rows(s, found["items"]), "nextCursor": found["nextCursor"]}


@router.get("/stock/summary")
def stock_summary(plant: Optional[str] = None, p: Principal = Depends(require(READ))):
    """Totals by stock type and plant, stock value, quality hold and blocked stock, expiry buckets, below-safety and stock-out counts, days of cover,
    open reservations and open counts / postings awaiting approval."""
    with uow(p) as s:
        return stock_reads.summary(s, plant)


@router.get("/stock/alerts")
def stock_alerts(plant: Optional[str] = None, type: Optional[str] = Query(None, description="comma list: STOCK_OUT,BELOW_SAFETY,BELOW_REORDER,EXPIRING,EXPIRED,"
                                                                                                "QUALITY_HOLD_AGED,BLOCKED_AGED,NEGATIVE_DRIFT"),
                 cursor: Optional[str] = None, limit: int = Query(50, ge=1, le=500), p: Principal = Depends(require(READ))):
    """Typed alerts with a severity and the object to act on, most severe first."""
    with uow(p) as s:
        items = stock_reads.alerts(s, plant, type)
        counts: dict = {}
        for a in items:
            counts[a["type"]] = counts.get(a["type"], 0) + 1
        return {**stock_reads.paged(items, cursor, limit), "countsByType": counts}


@router.get("/stock/movements")
def stock_movements(material: Optional[str] = None, plant: Optional[str] = None, storage_location: Optional[str] = None,
                    movement_type: Optional[str] = Query(None, description="comma list of movement types, e.g. 101,311"), stock_type: Optional[str] = None,
                    batch: Optional[str] = None, reference_type: Optional[str] = None, reference: Optional[str] = None, date_from: Optional[date] = None,
                    date_to: Optional[date] = None, page: Page = Depends(), p: Principal = Depends(require(READ))):
    """The movement ledger, newest first: signed quantity, value at the time of posting, movement text, the document that caused it and who posted it."""
    with uow(p) as s:
        query = stock_reads.movement_query(s, material=material, plant=plant, storage_location=storage_location, movement_type=movement_type,
                                           stock_type=stock_type, batch=batch, reference_type=reference_type, reference=reference, date_from=date_from,
                                           date_to=date_to)
        found = paginate(s, query, stock_reads.StockMovement, page, lambda x: x)
        return {"items": stock_reads.movement_rows(s, found["items"]), "nextCursor": found["nextCursor"]}


@router.get("/stock/movements/export")
def export_movements(material: Optional[str] = None, plant: Optional[str] = None, storage_location: Optional[str] = None, movement_type: Optional[str] = None,
                     stock_type: Optional[str] = None, batch: Optional[str] = None, reference_type: Optional[str] = None, reference: Optional[str] = None,
                     date_from: Optional[date] = None, date_to: Optional[date] = None, p: Principal = Depends(require(READ))):
    """The movement ledger as CSV (same filters; at most 50,000 rows, newest first; every export is audited with its hash)."""
    with uow(p) as s:
        query = stock_reads.movement_query(s, material=material, plant=plant, storage_location=storage_location, movement_type=movement_type,
                                           stock_type=stock_type, batch=batch, reference_type=reference_type, reference=reference, date_from=date_from,
                                           date_to=date_to)
        result = stock_reads.export_csv(s, query)
        return Response(content=result["content"].encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{result["fileName"]}"', "X-Content-SHA256": result["sha256"],
                                 "X-Row-Count": str(result["rows"]), "X-Truncated": str(result["truncated"]).lower()})


@router.get("/stock/materials/{material:path}")
def stock_card(material: str, plant: Optional[str] = None, horizonDays: int = Query(90, ge=7, le=365), p: Principal = Depends(require(READ))):
    """The stock card of a material: stock by plant, location, type and batch; the MRP-02 requirements profile per plant (on hand, open PO, in transit,
    firm planned receipts, demand incl. reservations, safety stock, projected balance per bucket); reservations; recent movements; valuation."""
    with uow(p) as s:
        return stock_reads.stock_card(s, material, plant, horizon_days=horizonDays)


# ================================================================ rules and enumerations
@router.get("/inventory/rules")
def inventory_rules(plant: Optional[str] = None, p: Principal = Depends(require(READ))):
    """The effective inventory rule sets (tenant versions, else the documented defaults), the enumerations the forms need and what the caller may do."""
    with uow(p) as s:
        from app.pic.models import Plant
        company = s.execute(select(Plant.company_code).where(Plant.code == plant)).scalar_one_or_none() if plant else None
        out = {}
        for name, key in (("posting", ir.POSTING_KEY), ("count", ir.COUNT_KEY), ("reservation", ir.RESERVATION_KEY), ("alerts", ir.ALERTS_KEY)):
            rule = ir.rule(s, key, company_code=company, plant=plant)
            out[name] = {"key": key, "ref": rule.ref, "body": jsonable(rule.body)}
        attrs = stock_reads.abac._attributes(s, p)  # noqa: SLF001
        return {**out, "enums": {
            "postingTypes": ["TRANSFER", "BLOCK", "UNBLOCK", "SCRAP", "RELEASE_QUALITY"],
            "postingStatuses": ["DRAFT", "SUBMITTED", "APPROVED", "POSTED", "REJECTED", "CANCELLED"],
            "countStatuses": ["PLANNED", "COUNTING", "COUNTED", "PENDING_APPROVAL", "APPROVED", "POSTED", "CANCELLED"],
            "countLineStatuses": ["PENDING", "COUNTED", "RECOUNT_REQUIRED", "RECOUNTED"],
            "reservationStatuses": ["OPEN", "PARTIALLY_ISSUED", "ISSUED", "CANCELLED", "EXPIRED"],
            "stockTypes": list(stock_ledger.STOCK_TYPES), "alertTypes": ["STOCK_OUT", "BELOW_SAFETY", "BELOW_REORDER", "EXPIRING", "EXPIRED", "QUALITY_HOLD_AGED",
                                                                       "BLOCKED_AGED", "NEGATIVE_DRIFT"],
            "movementTypes": stock_ledger.MOVEMENT_TEXT, "releaseQualityNote": "Stock in quality inspection is released by the usage decision of its inspection lot"},
            "me": {"canPost": "inventory:post" in p.scopes, "canCount": "inventory:count" in p.scopes, "canApprove": "inventory:approve" in p.scopes,
                   "plants": attrs.get("plants")}}


# ================================================================ stock postings
class PostingLineIn(BaseModel):
    material: str = Field(min_length=1, max_length=30)
    qty: Decimal = Field(gt=0, max_digits=15, decimal_places=3)
    batch: str = Field(default="", max_length=30)
    storageLocation: str = Field(min_length=1, max_length=10, description="where the stock is now")
    stockType: Optional[str] = Field(default=None, pattern="^(UNRESTRICTED|BLOCKED)$", description="TRANSFER and SCRAP: the stock taken (default UNRESTRICTED)")
    toStorageLocation: Optional[str] = Field(default=None, max_length=10, description="TRANSFER: the target storage location")
    toPlant: Optional[str] = Field(default=None, max_length=10, description="TRANSFER between plants of one company code")


class PostingIn(BaseModel):
    type: str = Field(pattern="^(TRANSFER|BLOCK|UNBLOCK|SCRAP|RELEASE_QUALITY)$")
    plant: str = Field(min_length=1, max_length=10, description="the plant the stock leaves")
    reasonCode: Optional[str] = Field(default=None, max_length=30)
    reason: Optional[str] = Field(default=None, max_length=500)
    postingDate: Optional[date] = None
    lines: list[PostingLineIn] = Field(min_length=1, max_length=500)
    submit: bool = Field(default=False, description="submit straight away (and auto-post when the rule allows)")


class CommentIn(BaseModel):
    comment: Optional[str] = Field(default=None, max_length=2000)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


def _posting(s, ref: str, lock: bool = False) -> StockPosting:
    posting = inventory.posting_by_ref(s, ref, lock=lock)
    _in_plants(s, posting)
    return posting


@router.post("/stock-postings", status_code=201)
def create_posting(body: PostingIn, response: Response, p: Principal = Depends(require("inventory:post")), key: Optional[str] = Depends(idempotency_key)):
    """Create a stock posting (DRAFT, or submitted straight away with submit=true). RELEASE_QUALITY is refused: use the inspection lot's usage decision."""
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/stock-postings", key, body)
        if idem.replay:
            return idem.replay
        posting = inventory.create_posting(s, posting_type=body.type, plant=body.plant, lines=[l.model_dump() for l in body.lines], reason_code=body.reasonCode,
                                           reason=body.reason, posting_date=body.postingDate, submit=body.submit)
        s.flush()
        response.headers["ETag"] = etag(posting)
        return idem.store(views.stock_posting(s, posting), 201)


@router.get("/stock-postings")
def list_postings(status: Optional[str] = None, type: Optional[str] = None, plant: Optional[str] = None, mine: bool = False, q: Optional[str] = None,
                  page: Page = Depends(), p: Principal = Depends(require(READ))):
    with uow(p) as s:
        query = select(StockPosting)
        scope = stock_reads._scope(s, plant)  # noqa: SLF001
        if scope is not None:
            query = query.where(StockPosting.plant.in_(scope))
        if status:
            query = query.where(StockPosting.status.in_(_csv(status)))
        if type:
            query = query.where(StockPosting.posting_type.in_(_csv(type)))
        if mine:
            query = query.where(StockPosting.created_by == p.user_id)
        if q and q.strip():
            query = query.where(StockPosting.number.ilike(stock_reads._esc(q.strip()) + "%", escape="\\"))  # noqa: SLF001
        return paginate(s, query, StockPosting, page, views.stock_posting_summary)


@router.get("/stock-postings/{ref:path}")
def get_posting(ref: str, response: Response, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        posting = _posting(s, ref)
        response.headers["ETag"] = etag(posting)
        return views.stock_posting(s, posting)


def _action(name: str, ref: str, body, key, s):
    idem = idempotent(s, f"POST /v1/stock-postings/{ref}/{name}", key, body)
    return idem


@router.post("/stock-postings/{ref:path}/submit")
def submit_posting(ref: str, response: Response, p: Principal = Depends(require("inventory:post")), key: Optional[str] = Depends(idempotency_key),
                   if_match: Optional[str] = IfMatch):
    """Submit a draft: it posts at once when the rule's auto-post limit allows (transfer / block / unblock), else it goes to the approval chain of its value band."""
    with uow(p) as s:
        idem = _action("submit", ref, {}, key, s)
        if idem.replay:
            return idem.replay
        posting = _posting(s, ref, lock=True)
        _precondition(posting, if_match, "/v1/stock-postings/{ref}")
        inventory.submit_posting(s, posting)
        s.flush()
        response.headers["ETag"] = etag(posting)
        return idem.store(views.stock_posting(s, posting))


@router.post("/stock-postings/{ref:path}/approve")
def approve_posting(ref: str, response: Response, body: CommentIn = CommentIn(), p: Principal = Depends(require("inventory:approve")),
                    key: Optional[str] = Depends(idempotency_key), if_match: Optional[str] = IfMatch):
    """Approve (the open approval step of the caller's role). Whoever created or submitted the posting is refused (SOD-10)."""
    with uow(p) as s:
        idem = _action("approve", ref, body, key, s)
        if idem.replay:
            return idem.replay
        posting = _posting(s, ref, lock=True)
        _precondition(posting, if_match, "/v1/stock-postings/{ref}")
        inventory.decide_posting(s, posting, "APPROVE", body.comment)
        s.flush()
        s.refresh(posting)
        response.headers["ETag"] = etag(posting)
        return idem.store(views.stock_posting(s, posting))


@router.post("/stock-postings/{ref:path}/reject")
def reject_posting(ref: str, body: ReasonIn, response: Response, p: Principal = Depends(require("inventory:approve")),
                   key: Optional[str] = Depends(idempotency_key), if_match: Optional[str] = IfMatch):
    with uow(p) as s:
        idem = _action("reject", ref, body, key, s)
        if idem.replay:
            return idem.replay
        posting = _posting(s, ref, lock=True)
        _precondition(posting, if_match, "/v1/stock-postings/{ref}")
        inventory.decide_posting(s, posting, "REJECT", body.reason)
        s.flush()
        s.refresh(posting)
        response.headers["ETag"] = etag(posting)
        return idem.store(views.stock_posting(s, posting))


@router.post("/stock-postings/{ref:path}/cancel")
def cancel_posting(ref: str, body: ReasonIn, response: Response, p: Principal = Depends(require("inventory:post")),
                   key: Optional[str] = Depends(idempotency_key), if_match: Optional[str] = IfMatch):
    with uow(p) as s:
        idem = _action("cancel", ref, body, key, s)
        if idem.replay:
            return idem.replay
        posting = _posting(s, ref, lock=True)
        _precondition(posting, if_match, "/v1/stock-postings/{ref}")
        inventory.cancel_posting(s, posting, body.reason)
        s.flush()
        response.headers["ETag"] = etag(posting)
        return idem.store(views.stock_posting(s, posting))


@router.post("/stock-postings/{ref:path}/post")
def post_posting(ref: str, response: Response, p: Principal = Depends(require("inventory:post")), key: Optional[str] = Depends(idempotency_key),
                 if_match: Optional[str] = IfMatch):
    """Post an approved stock posting: the stock and the posting period are checked again under the row locks; an ERP STOCK_POSTING follows."""
    with uow(p) as s:
        idem = _action("post", ref, {}, key, s)
        if idem.replay:
            return idem.replay
        posting = _posting(s, ref, lock=True)
        _precondition(posting, if_match, "/v1/stock-postings/{ref}")
        inventory.post_posting(s, posting)
        s.flush()
        response.headers["ETag"] = etag(posting)
        return idem.store(views.stock_posting(s, posting))


# ================================================================ physical inventory
class CountCreateIn(BaseModel):
    plant: str = Field(min_length=1, max_length=10)
    storageLocation: str = Field(min_length=1, max_length=10)
    materialGroup: Optional[str] = Field(default=None, max_length=30)
    materials: Optional[list[str]] = Field(default=None, max_length=2000, description="material numbers to count")
    abc: Optional[list[str]] = Field(default=None, description="ABC classes (by value issued in the last 12 months): A, B, C")
    description: Optional[str] = Field(default=None, max_length=500)
    plannedDate: Optional[date] = None


class CountEntryIn(BaseModel):
    material: str = Field(min_length=1, max_length=30)
    batch: str = Field(default="", max_length=30)
    qty: Decimal = Field(ge=0, max_digits=15, decimal_places=3)
    note: Optional[str] = Field(default=None, max_length=500)


class CountsIn(BaseModel):
    counts: list[CountEntryIn] = Field(min_length=1, max_length=2000)


class RecountIn(BaseModel):
    materials: Optional[list[str]] = Field(default=None, description="material numbers to recount; empty: every line outside the tolerance")
    reason: str = Field(min_length=3, max_length=500)


COUNT_ANY = ("inventory:count", "inventory:post")


def _count(s, ref: str, lock: bool = False) -> PhysicalInventory:
    inv = inventory.count_by_ref(s, ref, lock=lock)
    _in_plants(s, inv)
    return inv


@router.post("/physical-inventories", status_code=201)
def create_count(body: CountCreateIn, response: Response, p: Principal = Depends(require_any(*COUNT_ANY)), key: Optional[str] = Depends(idempotency_key)):
    """Create a count for a plant and storage location (optionally one material group, named materials or ABC classes): the book quantities are frozen now."""
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/physical-inventories", key, body)
        if idem.replay:
            return idem.replay
        inv = inventory.create_count(s, plant=body.plant, storage_location=body.storageLocation, material_group=body.materialGroup, materials=body.materials,
                                     abc=body.abc, description=body.description, planned_date=body.plannedDate)
        s.flush()
        response.headers["ETag"] = etag(inv)
        return idem.store(views.physical_inventory(s, inv), 201)


@router.get("/physical-inventories")
def list_counts(status: Optional[str] = None, plant: Optional[str] = None, storage_location: Optional[str] = None, page: Page = Depends(),
                p: Principal = Depends(require(READ))):
    with uow(p) as s:
        query = select(PhysicalInventory)
        scope = stock_reads._scope(s, plant)  # noqa: SLF001
        if scope is not None:
            query = query.where(PhysicalInventory.plant.in_(scope))
        if status:
            query = query.where(PhysicalInventory.status.in_(_csv(status)))
        if storage_location:
            query = query.where(PhysicalInventory.storage_location == storage_location)
        reveal = "inventory:approve" in p.scopes
        return paginate(s, query, PhysicalInventory, page, lambda inv: views.physical_inventory_summary(inv, reveal))


@router.get("/physical-inventories/{ref:path}")
def get_count(ref: str, response: Response, p: Principal = Depends(require(READ))):
    """The count document. Counters see their own counts only; approvers and controllers also see the book quantities and the differences."""
    with uow(p) as s:
        inv = _count(s, ref)
        response.headers["ETag"] = etag(inv)
        return views.physical_inventory(s, inv)


@router.put("/physical-inventories/{ref:path}/counts")
def put_counts(ref: str, body: CountsIn, response: Response, p: Principal = Depends(require("inventory:count")), if_match: Optional[str] = IfMatch):
    """Enter the counted quantities (or the recount of a line that needs one). A line outside the tolerance of rule INVENTORY-COUNT must be recounted by
    someone other than its first counter; found stock that is not on the list is added as an unlisted line."""
    with uow(p) as s:
        inv = _count(s, ref, lock=True)
        _precondition(inv, if_match, "/v1/physical-inventories/{ref}")
        inventory.enter_counts(s, inv, [e.model_dump() for e in body.counts])
        s.flush()
        response.headers["ETag"] = etag(inv)
        return views.physical_inventory(s, inv)


@router.post("/physical-inventories/{ref:path}/recount")
def recount(ref: str, body: RecountIn, response: Response, p: Principal = Depends(require_any("inventory:post", "inventory:approve")),
            key: Optional[str] = Depends(idempotency_key), if_match: Optional[str] = IfMatch):
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/physical-inventories/{ref}/recount", key, body)
        if idem.replay:
            return idem.replay
        inv = _count(s, ref, lock=True)
        _precondition(inv, if_match, "/v1/physical-inventories/{ref}")
        inventory.request_recount(s, inv, materials=body.materials, reason=body.reason)
        s.flush()
        response.headers["ETag"] = etag(inv)
        return idem.store(views.physical_inventory(s, inv))


def _count_action(name: str, ref: str, body, key, s):
    return idempotent(s, f"POST /v1/physical-inventories/{ref}/{name}", key, body)


@router.post("/physical-inventories/{ref:path}/submit")
def submit_count(ref: str, response: Response, p: Principal = Depends(require_any(*COUNT_ANY)), key: Optional[str] = Depends(idempotency_key),
                 if_match: Optional[str] = IfMatch):
    """Submit a fully counted document for approval (the approval chain follows the value of the differences; counters never approve: SOD-11)."""
    with uow(p) as s:
        idem = _count_action("submit", ref, {}, key, s)
        if idem.replay:
            return idem.replay
        inv = _count(s, ref, lock=True)
        _precondition(inv, if_match, "/v1/physical-inventories/{ref}")
        inventory.submit_count(s, inv)
        s.flush()
        response.headers["ETag"] = etag(inv)
        return idem.store(views.physical_inventory(s, inv))


@router.post("/physical-inventories/{ref:path}/approve")
def approve_count(ref: str, response: Response, body: CommentIn = CommentIn(), p: Principal = Depends(require("inventory:approve")),
                  key: Optional[str] = Depends(idempotency_key), if_match: Optional[str] = IfMatch):
    with uow(p) as s:
        idem = _count_action("approve", ref, body, key, s)
        if idem.replay:
            return idem.replay
        inv = _count(s, ref, lock=True)
        _precondition(inv, if_match, "/v1/physical-inventories/{ref}")
        inventory.decide_count(s, inv, "APPROVE", body.comment)
        s.flush()
        s.refresh(inv)
        response.headers["ETag"] = etag(inv)
        return idem.store(views.physical_inventory(s, inv))


@router.post("/physical-inventories/{ref:path}/reject")
def reject_count(ref: str, body: ReasonIn, response: Response, p: Principal = Depends(require("inventory:approve")),
                 key: Optional[str] = Depends(idempotency_key), if_match: Optional[str] = IfMatch):
    """Send the count back to the counters (the document returns to COUNTING)."""
    with uow(p) as s:
        idem = _count_action("reject", ref, body, key, s)
        if idem.replay:
            return idem.replay
        inv = _count(s, ref, lock=True)
        _precondition(inv, if_match, "/v1/physical-inventories/{ref}")
        inventory.decide_count(s, inv, "REJECT", body.reason)
        s.flush()
        s.refresh(inv)
        response.headers["ETag"] = etag(inv)
        return idem.store(views.physical_inventory(s, inv))


@router.post("/physical-inventories/{ref:path}/post")
def post_count(ref: str, response: Response, p: Principal = Depends(require("inventory:post")), key: Optional[str] = Depends(idempotency_key),
               if_match: Optional[str] = IfMatch):
    """Post the differences of an approved count (701 gain / 702 loss relative to the freeze)."""
    with uow(p) as s:
        idem = _count_action("post", ref, {}, key, s)
        if idem.replay:
            return idem.replay
        inv = _count(s, ref, lock=True)
        _precondition(inv, if_match, "/v1/physical-inventories/{ref}")
        inventory.post_count(s, inv)
        s.flush()
        response.headers["ETag"] = etag(inv)
        return idem.store(views.physical_inventory(s, inv))


@router.post("/physical-inventories/{ref:path}/cancel")
def cancel_count(ref: str, body: ReasonIn, response: Response, p: Principal = Depends(require_any(*COUNT_ANY)),
                 key: Optional[str] = Depends(idempotency_key), if_match: Optional[str] = IfMatch):
    with uow(p) as s:
        idem = _count_action("cancel", ref, body, key, s)
        if idem.replay:
            return idem.replay
        inv = _count(s, ref, lock=True)
        _precondition(inv, if_match, "/v1/physical-inventories/{ref}")
        inventory.cancel_count(s, inv, body.reason)
        s.flush()
        response.headers["ETag"] = etag(inv)
        return idem.store(views.physical_inventory(s, inv))


# ================================================================ reservations
class ReservationIn(BaseModel):
    material: str = Field(min_length=1, max_length=30)
    plant: str = Field(min_length=1, max_length=10)
    storageLocation: str = Field(min_length=1, max_length=10)
    qty: Decimal = Field(gt=0, max_digits=15, decimal_places=3)
    needDate: date
    costObject: Optional[str] = Field(default=None, max_length=60, pattern=r"^[A-Z_]+:[A-Za-z0-9._-]+$", description="e.g. COST_CENTER:6100")
    purpose: Optional[str] = Field(default=None, max_length=200)


class IssueIn(BaseModel):
    qty: Optional[Decimal] = Field(default=None, gt=0, max_digits=15, decimal_places=3, description="omitted: everything still reserved")
    batch: Optional[str] = Field(default=None, max_length=30, description="omitted: first expiry first out")


def _reservation(s, ref: str, lock: bool = False) -> StockReservation:
    res = inventory.reservation_by_ref(s, ref, lock=lock)
    _in_plants(s, res)
    return res


@router.post("/reservations", status_code=201)
def create_reservation(body: ReservationIn, response: Response, p: Principal = Depends(require("inventory:post")), key: Optional[str] = Depends(idempotency_key)):
    """Reserve unrestricted stock for a cost object. An unavailable quantity is a warning (it still becomes MRP demand) unless rule INVENTORY-RESERVATION
    blocks it; the open quantity is RESERVATION demand for MRP."""
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/reservations", key, body)
        if idem.replay:
            return idem.replay
        res = inventory.create_reservation(s, material=body.material, plant=body.plant, storage_location=body.storageLocation, qty=body.qty,
                                           need_date=body.needDate, cost_object=body.costObject, purpose=body.purpose)
        s.flush()
        response.headers["ETag"] = etag(res)
        return idem.store(views.stock_reservation(s, res), 201)


@router.get("/reservations")
def list_reservations(status: Optional[str] = None, material: Optional[str] = None, plant: Optional[str] = None, mine: bool = False,
                      page: Page = Depends(), p: Principal = Depends(require(READ))):
    from app.pic.models import Material
    with uow(p) as s:
        query = select(StockReservation)
        scope = stock_reads._scope(s, plant)  # noqa: SLF001
        if scope is not None:
            query = query.where(StockReservation.plant.in_(scope))
        if status:
            query = query.where(StockReservation.status.in_(_csv(status)))
        if material:
            query = query.where(StockReservation.material_id.in_(select(Material.id).where(Material.number.ilike(stock_reads._esc(material.strip()) + "%", escape="\\"))))  # noqa: SLF001
        if mine:
            query = query.where(StockReservation.requester_id == p.user_id)
        found = paginate(s, query, StockReservation, page, lambda x: x)
        return {"items": [views.stock_reservation(s, r) for r in found["items"]], "nextCursor": found["nextCursor"]}


@router.get("/reservations/{ref:path}")
def get_reservation(ref: str, response: Response, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        res = _reservation(s, ref)
        response.headers["ETag"] = etag(res)
        return views.stock_reservation(s, res)


@router.post("/reservations/{ref:path}/issue")
def issue_reservation(ref: str, response: Response, body: IssueIn = IssueIn(), p: Principal = Depends(require("inventory:post")),
                      key: Optional[str] = Depends(idempotency_key), if_match: Optional[str] = IfMatch):
    """Issue the goods (movement 201 from unrestricted stock to the cost object), all of it or a part; the demand for MRP is reduced by what was issued."""
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/reservations/{ref}/issue", key, body)
        if idem.replay:
            return idem.replay
        res = _reservation(s, ref, lock=True)
        _precondition(res, if_match, "/v1/reservations/{ref}")
        inventory.issue_reservation(s, res, qty=body.qty, batch=body.batch)
        s.flush()
        response.headers["ETag"] = etag(res)
        return idem.store(views.stock_reservation(s, res))


@router.post("/reservations/{ref:path}/cancel")
def cancel_reservation(ref: str, body: ReasonIn, response: Response, p: Principal = Depends(require(READ)), key: Optional[str] = Depends(idempotency_key),
                       if_match: Optional[str] = IfMatch):
    """Cancel what is still reserved (its requester, or a stock poster); the demand for MRP is released."""
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/reservations/{ref}/cancel", key, body)
        if idem.replay:
            return idem.replay
        res = _reservation(s, ref, lock=True)
        _precondition(res, if_match, "/v1/reservations/{ref}")
        inventory.cancel_reservation(s, res, body.reason)
        s.flush()
        response.headers["ETag"] = etag(res)
        return idem.store(views.stock_reservation(s, res))
