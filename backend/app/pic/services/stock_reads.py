"""Read models of the stock ledger (BP M09 / M02 stock, KPIs Stock-out incidents, Inventory days of cover): the stock list, the summary, the alerts,
the stock card of a material (with the MRP-02 requirements profile) and the movement ledger with its CSV export.

All reads are plant-scoped by the user's ABAC attribute ``plants`` (absent or "*": every plant). Nothing here writes, except the audit record of an export."""
import base64
import csv
import hashlib
import io
import json
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, case, func, or_, select, tuple_
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    AppUser, DemandElement, GoodsReceipt, GrLine, InspectionLot, Material, PhysicalInventory, PlanningParameter, PurchaseOrder, Stock, StockMovement,
    PoLine, StockBatch, StockPosting, StockReservation,
)
from app.pic.platform import abac, audit, clock
from app.pic.platform import inventory_defaults as ir
from app.pic.platform.errors import Problem, not_found
from app.pic.platform.money import D, line_amount
from app.pic.platform.serialize import jsonable
from app.pic.services import kpi, planning, stock_ledger
from app.pic.services.common import material_by_number, principal

LIVE_TYPES = ("UNRESTRICTED", "QUALITY", "BLOCKED", "CONSIGNMENT")     # stock types that can expire (subcontractor stock is the components we sent)
SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
MAX_EXPORT_ROWS = 50_000


# ---------------------------------------------------------------- scope and small helpers
def visible_plants(session: Session) -> Optional[set]:
    """The plants the user may read (ABAC attribute ``plants``); None: all."""
    p = principal(session)
    if p.is_agent:
        return None
    attrs = abac._attributes(session, p)  # noqa: SLF001 - the same current-attribute read the command guards use
    plants = attrs.get("plants")
    if plants is None:
        return None
    plants = [plants] if isinstance(plants, str) else list(plants)
    return None if "*" in plants else {str(x) for x in plants}


def _scope(session: Session, plant: Optional[str]) -> Optional[set]:
    """Plants to filter by: the requested plant (403 when outside the user's plants) or the user's own plants; None: all plants."""
    visible = visible_plants(session)
    if plant:
        if visible is not None and plant not in visible:
            raise Problem(403, "FORBIDDEN", f"You are not assigned to plant {plant}", rule_ref="ABAC", dimension="plant", value=plant)
        return {plant}
    return visible


def _esc(term: str) -> str:
    """A search term as literal text inside a LIKE pattern (escape character backslash)."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _csv_list(value: Optional[str]) -> list[str]:
    return [x.strip().upper() for x in (value or "").split(",") if x.strip()]


def _price_value(qty, price) -> Optional[int]:
    return None if price is None else line_amount(D(qty), int(price))


def _material_filter(query, term: Optional[str]):
    if term and term.strip():
        term = term.strip()
        query = query.where(or_(Material.number.ilike(_esc(term) + "%", escape="\\"), Material.description.ilike("%" + _esc(term) + "%", escape="\\")))
    return query


def _expiry_map(session: Session, pairs: set) -> dict:
    """{(material_id, batch): earliest expiry} for the pairs: goods-receipt lines (reversed receipts excluded) and the batch master (opening balances)."""
    return stock_ledger.expiry_for_pairs(session, pairs)


def _unrestricted(session: Session, pairs: set) -> dict:
    if not pairs:
        return {}
    rows = session.execute(select(Stock.material_id, Stock.plant, func.sum(Stock.qty)).where(
        Stock.material_id.in_({m for m, _ in pairs}), Stock.plant.in_({p for _, p in pairs}), Stock.stock_type == "UNRESTRICTED")
        .group_by(Stock.material_id, Stock.plant)).all()
    return {(m, p): D(q) for m, p, q in rows}


def _daily_usage(session: Session, pairs: set, materials: dict, days: int = 90) -> dict:
    """Average daily issue per (material, plant): movements 201 / 201K of the last ``days`` days, else the material's annual demand / 365."""
    if not pairs:
        return {}
    since = clock.now() - timedelta(days=days)
    rows = session.execute(select(StockMovement.material_id, StockMovement.plant, func.sum(-StockMovement.qty)).where(
        StockMovement.material_id.in_({m for m, _ in pairs}), StockMovement.plant.in_({p for _, p in pairs}),
        StockMovement.movement_type.in_(("201", "201K")), StockMovement.created_at >= since).group_by(StockMovement.material_id, StockMovement.plant)).all()
    used = {(m, p): D(q) / Decimal(days) for m, p, q in rows if q and q > 0}
    out = {}
    for pair in pairs:
        material = materials.get(pair[0])
        out[pair] = used.get(pair) or ((D(material.annual_demand) / Decimal(365)) if material is not None and material.annual_demand else None)
    return out


def _cover(on_hand: Decimal, daily: Optional[Decimal]) -> Optional[str]:
    return str((on_hand / daily).quantize(Decimal("0.1"))) if daily and daily > 0 else None


# ---------------------------------------------------------------- GET /v1/stock
def stock_query(session: Session, *, material: Optional[str], plant: Optional[str], storage_location: Optional[str], stock_type: Optional[str],
                batch: Optional[str], material_group: Optional[str], below_safety: bool, expiring_within_days: Optional[int], only_non_zero: bool):
    query = select(Stock).join(Material, Material.id == Stock.material_id)
    scope = _scope(session, plant)
    if scope is not None:
        query = query.where(Stock.plant.in_(scope))
    query = _material_filter(query, material)
    if storage_location:
        query = query.where(Stock.storage_location == storage_location)
    if stock_type:
        query = query.where(Stock.stock_type.in_(_csv_list(stock_type)))
    if batch is not None and batch != "":
        query = query.where(Stock.batch == batch)
    if material_group:
        query = query.where(Material.material_group == material_group)
    if only_non_zero:
        query = query.where(Stock.qty != 0)
    if below_safety:
        unrestricted = (select(Stock.material_id.label("m"), Stock.plant.label("p"), func.sum(Stock.qty).label("q")).where(Stock.stock_type.in_(planning.AVAILABLE_STOCK_TYPES))
                        .group_by(Stock.material_id, Stock.plant).subquery())
        below = select(Material.id, unrestricted.c.p).join(unrestricted, unrestricted.c.m == Material.id).where(
            Material.safety_stock > 0, unrestricted.c.q < Material.safety_stock)
        query = query.where(tuple_(Stock.material_id, Stock.plant).in_(below))
    if expiring_within_days is not None:
        limit = clock.today() + timedelta(days=max(0, int(expiring_within_days)))
        expiring = (select(GrLine.material_id, GrLine.batch).join(GoodsReceipt, GoodsReceipt.id == GrLine.gr_id).where(
            GrLine.expiry.is_not(None), GrLine.expiry <= limit, GrLine.batch != "", GoodsReceipt.status != "REVERSED"))
        master = select(StockBatch.material_id, StockBatch.batch).where(StockBatch.expiry_date.is_not(None), StockBatch.expiry_date <= limit,
                                                                        StockBatch.batch != "")   # opening balances have no receipt
        query = query.where(Stock.qty > 0, Stock.stock_type.in_(LIVE_TYPES), tuple_(Stock.material_id, Stock.batch).in_(expiring.union(master)))
    return query


def stock_rows(session: Session, stocks: list[Stock]) -> list[dict]:
    """Stock list rows with material data, expiry of the batch, value at standard price, safety stock, reorder point and days of cover."""
    materials = {m.id: m for m in session.execute(select(Material).where(Material.id.in_({s.material_id for s in stocks} or {uuid.uuid4()}))).scalars()}
    pairs = {(s.material_id, s.plant) for s in stocks}
    expiry = _expiry_map(session, {(s.material_id, s.batch) for s in stocks})
    params = {(r.material_id, r.plant): r for r in session.execute(select(PlanningParameter).where(
        PlanningParameter.material_id.in_({m for m, _ in pairs} or {uuid.uuid4()}), PlanningParameter.plant.in_({p for _, p in pairs} or {""}))).scalars()}
    free = _unrestricted(session, pairs)
    daily = _daily_usage(session, pairs, materials)
    today = clock.today()
    out = []
    for s in stocks:
        m = materials[s.material_id]
        pair = (s.material_id, s.plant)
        exp = expiry.get((s.material_id, s.batch))
        safety = D(m.safety_stock or 0)
        out.append({"id": str(s.id), "material": m.number, "description": m.description, "uom": m.base_uom, "materialGroup": m.material_group,
                    "plant": s.plant, "storageLocation": s.storage_location, "stockType": s.stock_type, "batch": s.batch, "qty": jsonable(s.qty),
                    "expiry": exp.isoformat() if exp else None, "daysToExpiry": (exp - today).days if exp else None,
                    "unitPriceMinor": m.standard_price_minor, "valueMinor": _price_value(s.qty, m.standard_price_minor),
                    "safetyStock": jsonable(safety), "reorderPoint": jsonable(params[pair].reorder_point) if pair in params else None,
                    "belowSafety": bool(safety > 0 and free.get(pair, Decimal(0)) < safety),
                    "daysOfCover": _cover(free.get(pair, Decimal(0)), daily.get(pair)) if s.stock_type == "UNRESTRICTED" else None,
                    "updatedAt": (s.updated_at or s.created_at).isoformat()})
    return out


# ---------------------------------------------------------------- GET /v1/stock/summary
def _age_buckets(days: list[int]) -> dict:
    return {"0-2": sum(1 for d in days if d <= 2), "3-7": sum(1 for d in days if 3 <= d <= 7), ">7": sum(1 for d in days if d > 7)}


def summary(session: Session, plant: Optional[str] = None) -> dict:
    scope = _scope(session, plant)
    today = clock.today()
    where = [Stock.plant.in_(scope)] if scope is not None else []
    rows = session.execute(select(Stock.plant, Stock.stock_type, func.count(), func.sum(Stock.qty),
                                  func.sum(Stock.qty * func.coalesce(Material.standard_price_minor, 0))).join(Material, Material.id == Stock.material_id)
                           .where(Stock.qty != 0, *where).group_by(Stock.plant, Stock.stock_type).order_by(Stock.plant, Stock.stock_type)).all()
    by_plant: dict = {}
    by_type: dict = {}
    for pl, st, n, qty, value in rows:
        by_plant.setdefault(pl, {})[st] = {"rows": n, "qty": jsonable(qty), "valueMinor": int(value or 0)}
        agg = by_type.setdefault(st, {"rows": 0, "qty": Decimal(0), "valueMinor": 0})
        agg["rows"] += n
        agg["qty"] += D(qty)
        agg["valueMinor"] += int(value or 0)
    own = sum(v["valueMinor"] for t, v in by_type.items() if t in stock_ledger.OWN_TYPES)
    # quality hold: open inspection lots by age
    lot_ages = [(today - lot.created_at.astimezone(clock.IST).date()).days for lot in session.execute(
        select(InspectionLot).where(InspectionLot.status == "OPEN")).scalars()]
    # blocked stock value; expiry buckets
    expiry_rows = session.execute(select(Stock, Material).join(Material, Material.id == Stock.material_id).where(
        Stock.qty > 0, Stock.stock_type.in_(LIVE_TYPES), Stock.batch != "", *where)).all()
    expiry = _expiry_map(session, {(s.material_id, s.batch) for s, _ in expiry_rows})
    buckets = {"expired": {"rows": 0, "valueMinor": 0}, "within30": {"rows": 0, "valueMinor": 0}, "within60": {"rows": 0, "valueMinor": 0},
               "within90": {"rows": 0, "valueMinor": 0}}
    for s, m in expiry_rows:
        exp = expiry.get((s.material_id, s.batch))
        if exp is None:
            continue
        days = (exp - today).days
        key = "expired" if days < 0 else "within30" if days <= 30 else "within60" if days <= 60 else "within90" if days <= 90 else None
        if key:
            buckets[key]["rows"] += 1
            buckets[key]["valueMinor"] += _price_value(s.qty, m.standard_price_minor) or 0
    materials_below = session.execute(
        select(func.count()).select_from(select(Stock.material_id, Stock.plant).join(Material, Material.id == Stock.material_id)
                                         .where(Stock.stock_type.in_(planning.AVAILABLE_STOCK_TYPES), Material.safety_stock > 0, *where)
                                         .group_by(Stock.material_id, Stock.plant, Material.safety_stock)
                                         .having(func.sum(Stock.qty) < Material.safety_stock).subquery())).scalar_one()
    ctx_plants = sorted(scope) if scope is not None else [None]
    stockouts = sum(int(kpi.m02_stockouts(kpi.Ctx(session, None, pl))[0] or 0) for pl in ctx_plants)
    cover = kpi.m02_days_of_cover(kpi.Ctx(session, None, ctx_plants[0] if len(ctx_plants) == 1 else None))[0]
    reservation = session.execute(select(func.count(), func.coalesce(func.sum(StockReservation.qty - StockReservation.issued_qty), 0)).where(
        StockReservation.status.in_(stock_ledger.OPEN_RESERVATION), *([StockReservation.plant.in_(scope)] if scope is not None else []))).one()
    counts = dict(session.execute(select(PhysicalInventory.status, func.count()).where(
        PhysicalInventory.status.in_(("PLANNED", "COUNTING", "COUNTED", "PENDING_APPROVAL", "APPROVED")),
        *([PhysicalInventory.plant.in_(scope)] if scope is not None else [])).group_by(PhysicalInventory.status)).all())
    waiting = session.execute(select(func.count()).select_from(StockPosting).where(
        StockPosting.status.in_(("SUBMITTED", "APPROVED")), *([StockPosting.plant.in_(scope)] if scope is not None else []))).scalar_one()
    return {"asOf": today.isoformat(), "plant": plant, "plants": sorted(scope) if scope is not None else None,
            "byType": {t: {**v, "qty": jsonable(v["qty"])} for t, v in sorted(by_type.items())}, "byPlant": by_plant,
            "stockValueMinor": own, "stockValueNote": "own stock (unrestricted, quality, blocked) at standard price; consignment and subcontractor stock excluded",
            "qualityHold": {"openLots": len(lot_ages), "ageBucketsDays": _age_buckets(lot_ages),
                            "valueMinor": by_type.get("QUALITY", {}).get("valueMinor", 0)},
            "blockedValueMinor": by_type.get("BLOCKED", {}).get("valueMinor", 0), "expiring": buckets, "belowSafetyCount": materials_below,
            "stockOutCount": stockouts, "stockOutDefinition": "stock materials with open demand and no available (unrestricted or consignment) stock (KPI M02.STOCKOUTS)",
            "daysOfCover": str(cover) if cover is not None else None,
            "openReservations": {"count": reservation[0], "openQty": jsonable(reservation[1])},
            "openCounts": {"total": sum(counts.values()), "byStatus": counts, "awaitingApproval": counts.get("PENDING_APPROVAL", 0)},
            "postingsAwaitingApproval": waiting}


# ---------------------------------------------------------------- GET /v1/stock/alerts
def _alert(kind: str, severity: str, title: str, detail: str, *, material: Optional[Material] = None, plant=None, sloc=None, stock_type=None, batch=None,
           qty=None, value=None, since=None, obj: dict, action: str) -> dict:
    return {"id": ":".join(str(x) for x in (kind, material.number if material else "", plant or "", sloc or "", stock_type or "", batch or "")),
            "type": kind, "severity": severity, "title": title, "detail": detail, "material": material.number if material else None,
            "description": material.description if material else None, "plant": plant, "storageLocation": sloc, "stockType": stock_type, "batch": batch,
            "qty": jsonable(qty) if qty is not None else None, "valueMinor": value, "since": since.isoformat() if since else None, "object": obj,
            "suggestedAction": action}


def alerts(session: Session, plant: Optional[str] = None, types: Optional[str] = None) -> list[dict]:
    scope = _scope(session, plant)
    rule = ir.rule(session, ir.ALERTS_KEY)
    body = rule.body
    today = clock.today()
    wanted = set(_csv_list(types))
    out: list[dict] = []
    in_scope = (lambda col: col.in_(scope)) if scope is not None else (lambda col: col.is_not(None))

    def want(kind: str) -> bool:
        return not wanted or kind in wanted

    unrestricted = (select(Stock.material_id.label("m"), Stock.plant.label("p"), func.sum(Stock.qty).label("q")).where(Stock.stock_type.in_(planning.AVAILABLE_STOCK_TYPES), in_scope(Stock.plant))
                    .group_by(Stock.material_id, Stock.plant).subquery())
    demand = (select(DemandElement.material_id.label("m"), DemandElement.plant.label("p"), func.sum(DemandElement.qty).label("d")).where(
        DemandElement.qty > 0, in_scope(DemandElement.plant)).group_by(DemandElement.material_id, DemandElement.plant).subquery())
    if want("STOCK_OUT"):
        for m, pl, d, q in session.execute(select(Material, demand.c.p, demand.c.d, func.coalesce(unrestricted.c.q, 0)).join(demand, demand.c.m == Material.id)
                                           .outerjoin(unrestricted, and_(unrestricted.c.m == Material.id, unrestricted.c.p == demand.c.p))
                                           .where(Material.status != "BLOCKED", Material.type == "STOCK", func.coalesce(unrestricted.c.q, 0) <= 0)
                                           .order_by(Material.number)).all():
            out.append(_alert("STOCK_OUT", "CRITICAL", f"{m.number} is out of stock at {pl}", f"Open demand {jsonable(d)} {m.base_uom} and no available (unrestricted or consignment) stock.",
                              material=m, plant=pl, qty=q, obj={"type": "MATERIAL", "ref": m.number}, action="Expedite open supply or raise a requisition"))
    if want("BELOW_SAFETY"):
        for m, pl, q in session.execute(select(Material, unrestricted.c.p, unrestricted.c.q).join(unrestricted, unrestricted.c.m == Material.id).where(
                Material.safety_stock > 0, unrestricted.c.q > 0, unrestricted.c.q < Material.safety_stock).order_by(Material.number)).all():
            out.append(_alert("BELOW_SAFETY", "HIGH", f"{m.number} is below safety stock at {pl}", f"{jsonable(q)} on hand, safety stock {jsonable(m.safety_stock)} {m.base_uom}.",
                              material=m, plant=pl, qty=q, value=_price_value(q, m.standard_price_minor), obj={"type": "MATERIAL", "ref": m.number},
                              action="Expedite open supply or firm a planned order"))
    if want("BELOW_REORDER"):
        for m, pl, point, q in session.execute(select(Material, PlanningParameter.plant, PlanningParameter.reorder_point, func.coalesce(unrestricted.c.q, 0))
                                               .join(PlanningParameter, PlanningParameter.material_id == Material.id)
                                               .outerjoin(unrestricted, and_(unrestricted.c.m == Material.id, unrestricted.c.p == PlanningParameter.plant))
                                               .where(in_scope(PlanningParameter.plant), func.coalesce(unrestricted.c.q, 0) <= PlanningParameter.reorder_point,
                                                      or_(Material.safety_stock <= 0, func.coalesce(unrestricted.c.q, 0) >= Material.safety_stock))
                                               .order_by(Material.number)).all():
            out.append(_alert("BELOW_REORDER", "MEDIUM", f"{m.number} reached its reorder point at {pl}", f"{jsonable(q)} on hand, reorder point {jsonable(point)} {m.base_uom}.",
                              material=m, plant=pl, qty=q, obj={"type": "MATERIAL", "ref": m.number}, action="Run MRP or raise a replenishment requisition"))
    if want("EXPIRING") or want("EXPIRED"):
        rows = session.execute(select(Stock, Material).join(Material, Material.id == Stock.material_id).where(
            Stock.qty > 0, Stock.stock_type.in_(LIVE_TYPES), Stock.batch != "", in_scope(Stock.plant)).order_by(Material.number, Stock.batch)).all()
        expiry = _expiry_map(session, {(s.material_id, s.batch) for s, _ in rows})
        for s, m in rows:
            exp = expiry.get((s.material_id, s.batch))
            if exp is None:
                continue
            days = (exp - today).days
            value = _price_value(s.qty, m.standard_price_minor)
            if days < 0 and want("EXPIRED"):
                out.append(_alert("EXPIRED", "CRITICAL", f"{m.number} lot {s.batch} expired {-days} day(s) ago", f"{jsonable(s.qty)} {m.base_uom} {s.stock_type.lower()} at "
                                  f"{s.plant}/{s.storage_location} expired on {exp.isoformat()}.", material=m, plant=s.plant, sloc=s.storage_location,
                                  stock_type=s.stock_type, batch=s.batch, qty=s.qty, value=value, since=exp,
                                  obj={"type": "STOCK", "ref": f"{m.number}/{s.batch}"}, action="Block and scrap (own stock) or return to the supplier (consignment)"))
            elif 0 <= days <= int(body["expiryWarnDays"]) and want("EXPIRING"):
                out.append(_alert("EXPIRING", "HIGH" if days <= 30 else "MEDIUM", f"{m.number} lot {s.batch} expires in {days} day(s)",
                                  f"{jsonable(s.qty)} {m.base_uom} {s.stock_type.lower()} at {s.plant}/{s.storage_location} expires on {exp.isoformat()}.",
                                  material=m, plant=s.plant, sloc=s.storage_location, stock_type=s.stock_type, batch=s.batch, qty=s.qty, value=value, since=exp,
                                  obj={"type": "STOCK", "ref": f"{m.number}/{s.batch}"}, action="Use first (FEFO), transfer to where it is consumed, or return"))
    if want("QUALITY_HOLD_AGED"):
        for lot in session.execute(select(InspectionLot).where(InspectionLot.status == "OPEN").order_by(InspectionLot.created_at)).scalars():
            age = (today - lot.created_at.astimezone(clock.IST).date()).days
            if age <= int(body["qualityHoldDays"]):
                continue
            line = session.get(GrLine, lot.gr_line_id)
            m = session.get(Material, line.material_id)
            pl = session.get(PoLine, line.po_line_id).plant
            if scope is not None and pl not in scope:
                continue
            out.append(_alert("QUALITY_HOLD_AGED", "HIGH" if age > 2 * int(body["qualityHoldDays"]) else "MEDIUM", f"Inspection lot {lot.number} has been open {age} days",
                              f"{jsonable(lot.qty)} {m.base_uom} of {m.number} wait for the usage decision.", material=m, plant=pl, sloc=line.storage_location,
                              stock_type="QUALITY", batch=line.batch, qty=lot.qty, value=_price_value(lot.qty, m.standard_price_minor),
                              since=lot.created_at, obj={"type": "INSPECTION_LOT", "ref": lot.number}, action="Take the usage decision"))
    if want("BLOCKED_AGED"):
        since = (select(StockMovement.material_id.label("m"), StockMovement.plant.label("p"), StockMovement.storage_location.label("l"),
                        StockMovement.batch.label("b"), func.max(StockMovement.created_at).label("at"))
                 .where(StockMovement.stock_type == "BLOCKED", StockMovement.qty > 0).group_by(StockMovement.material_id, StockMovement.plant,
                                                                                               StockMovement.storage_location, StockMovement.batch).subquery())
        for s, m, at in session.execute(select(Stock, Material, since.c.at).join(Material, Material.id == Stock.material_id).outerjoin(
                since, and_(since.c.m == Stock.material_id, since.c.p == Stock.plant, since.c.l == Stock.storage_location, since.c.b == Stock.batch))
                .where(Stock.stock_type == "BLOCKED", Stock.qty > 0, in_scope(Stock.plant)).order_by(Material.number)).all():
            blocked_on = at or s.created_at
            age = (today - blocked_on.astimezone(clock.IST).date()).days
            if age > int(body["blockedDays"]):
                out.append(_alert("BLOCKED_AGED", "MEDIUM", f"{m.number} has been blocked {age} days", f"{jsonable(s.qty)} {m.base_uom} blocked at {s.plant}/{s.storage_location}"
                                  + (f" lot {s.batch}" if s.batch else "") + ".", material=m, plant=s.plant, sloc=s.storage_location, stock_type="BLOCKED",
                                  batch=s.batch, qty=s.qty, value=_price_value(s.qty, m.standard_price_minor), since=blocked_on,
                                  obj={"type": "STOCK", "ref": f"{m.number}/{s.batch}" if s.batch else m.number}, action="Unblock, return to the supplier or scrap"))
    if want("NEGATIVE_DRIFT") and body.get("negativeDrift", True):
        ledger = (select(StockMovement.material_id.label("m"), StockMovement.plant.label("p"), StockMovement.storage_location.label("l"),
                         StockMovement.stock_type.label("t"), StockMovement.batch.label("b"), func.sum(StockMovement.qty).label("q"))
                  .where(in_scope(StockMovement.plant)).group_by(StockMovement.material_id, StockMovement.plant, StockMovement.storage_location,
                                                                 StockMovement.stock_type, StockMovement.batch).subquery())
        for s, m, ledger_qty in session.execute(select(Stock, Material, ledger.c.q).join(Material, Material.id == Stock.material_id).outerjoin(
                ledger, and_(ledger.c.m == Stock.material_id, ledger.c.p == Stock.plant, ledger.c.l == Stock.storage_location, ledger.c.t == Stock.stock_type,
                             ledger.c.b == Stock.batch)).where(in_scope(Stock.plant), or_(Stock.qty < 0, and_(ledger.c.q.is_not(None), ledger.c.q != Stock.qty)))
                .order_by(Material.number)).all():
            out.append(_alert("NEGATIVE_DRIFT", "CRITICAL" if s.qty < 0 else "MEDIUM", f"{m.number}: stock does not equal its movements at {s.plant}/{s.storage_location}",
                              f"Balance {jsonable(s.qty)}, sum of movements {jsonable(ledger_qty) if ledger_qty is not None else 'n/a'} ({s.stock_type.lower()}"
                              + (f", lot {s.batch}" if s.batch else "") + ").", material=m, plant=s.plant, sloc=s.storage_location, stock_type=s.stock_type,
                              batch=s.batch, qty=s.qty, obj={"type": "STOCK", "ref": f"{m.number}/{s.batch}" if s.batch else m.number},
                              action="Reconcile with a physical inventory; stock changes only through postings"))
    out.sort(key=lambda a: (SEVERITY_ORDER[a["severity"]], a["type"], a["material"] or "", a["id"]))
    return out


def paged(items: list, cursor: Optional[str], limit: int) -> dict:
    """Cursor page of a computed list (the cursor is the offset)."""
    try:
        offset = int(json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())["o"]) if cursor else 0
    except Exception:  # noqa: BLE001
        raise Problem(400, "INVALID_CURSOR", "The cursor is not valid; start again without it")
    page = items[offset: offset + limit]
    more = offset + limit < len(items)
    return {"items": page, "total": len(items),
            "nextCursor": base64.urlsafe_b64encode(json.dumps({"o": offset + limit}).encode()).decode() if more else None}


# ---------------------------------------------------------------- GET /v1/stock/materials/{material}
def stock_card(session: Session, number: str, plant: Optional[str] = None, movements: int = 25, horizon_days: int = 90) -> dict:
    material = material_by_number(session, number)
    scope = _scope(session, plant)
    pf = [Stock.plant.in_(scope)] if scope is not None else []
    stocks = session.execute(select(Stock).where(Stock.material_id == material.id, Stock.qty != 0, *pf)
                             .order_by(Stock.plant, Stock.storage_location, Stock.stock_type, Stock.batch)).scalars().all()
    rows = stock_rows(session, stocks)
    plants = sorted({s.plant for s in stocks} | {r for (r,) in session.execute(select(DemandElement.plant).where(DemandElement.material_id == material.id,
                                                                                                                   DemandElement.qty > 0).distinct())}
                    | {r for (r,) in session.execute(select(PlanningParameter.plant).where(PlanningParameter.material_id == material.id))})
    if scope is not None:
        plants = [x for x in plants if x in scope]
    profiles = []
    for pl in plants:
        profile = planning.requirements_profile(session, material, pl, horizon_days=horizon_days)
        parameters = profile.pop("parameters")
        profile["reorderPoint"] = parameters[0] if parameters else None
        profile["maxStock"] = parameters[1] if parameters else None
        profile["reserved"] = stock_ledger.reserved_open(session, material.id, pl)
        profile["availableToPromise"] = profile["onHand"] - profile["reserved"]
        profiles.append(jsonable(profile))
    reservations = session.execute(select(StockReservation).where(
        StockReservation.material_id == material.id, StockReservation.status.in_(stock_ledger.OPEN_RESERVATION), *([StockReservation.plant.in_(scope)] if scope is not None else []))
        .order_by(StockReservation.need_date)).scalars().all()
    recent = session.execute(select(StockMovement).where(StockMovement.material_id == material.id, *([StockMovement.plant.in_(scope)] if scope is not None else []))
                             .order_by(StockMovement.created_at.desc(), StockMovement.id.desc()).limit(movements)).scalars().all()
    by_type: dict = {}
    for r in rows:
        agg = by_type.setdefault(r["stockType"], {"qty": Decimal(0), "valueMinor": 0})
        agg["qty"] += D(r["qty"])
        agg["valueMinor"] += r["valueMinor"] or 0
    own_qty = sum((v["qty"] for t, v in by_type.items() if t in stock_ledger.OWN_TYPES), Decimal(0))
    return {"material": {"number": material.number, "description": material.description, "uom": material.base_uom, "type": material.type,
                         "materialGroup": material.material_group, "mrpType": material.mrp_type, "status": material.status,
                         "batchManaged": bool((material.attributes or {}).get("batchManaged")), "expiryManaged": bool((material.attributes or {}).get("expiryManaged"))},
            "stock": rows, "byType": {t: {"qty": jsonable(v["qty"]), "valueMinor": v["valueMinor"]} for t, v in sorted(by_type.items())},
            "requirements": profiles,
            "reservations": [{"number": r.number, "status": r.status, "plant": r.plant, "storageLocation": r.storage_location, "qty": jsonable(r.qty),
                              "openQty": jsonable(D(r.qty) - D(r.issued_qty)), "needDate": r.need_date.isoformat(),
                              "costObject": f"{r.cost_object_type}:{r.cost_object_code}" if r.cost_object_code else None, "purpose": r.purpose}
                             for r in reservations],
            "movements": movement_rows(session, recent),
            "valuation": {"method": "STANDARD_PRICE", "standardPriceMinor": material.standard_price_minor, "valuationClass": material.valuation_class,
                          "ownStockQty": jsonable(own_qty), "ownStockValueMinor": _price_value(own_qty, material.standard_price_minor),
                          "blockedValueMinor": by_type.get("BLOCKED", {}).get("valueMinor", 0)}}


# ---------------------------------------------------------------- GET /v1/stock/movements
def movement_query(session: Session, *, material: Optional[str], plant: Optional[str], storage_location: Optional[str], movement_type: Optional[str],
                   stock_type: Optional[str], batch: Optional[str], reference_type: Optional[str], reference: Optional[str],
                   date_from: Optional[date], date_to: Optional[date]):
    query = select(StockMovement).join(Material, Material.id == StockMovement.material_id)
    scope = _scope(session, plant)
    if scope is not None:
        query = query.where(StockMovement.plant.in_(scope))
    query = _material_filter(query, material)
    if storage_location:
        query = query.where(StockMovement.storage_location == storage_location)
    if movement_type:
        query = query.where(StockMovement.movement_type.in_([x.strip() for x in movement_type.split(",") if x.strip()]))
    if stock_type:
        query = query.where(StockMovement.stock_type.in_(_csv_list(stock_type)))
    if batch is not None and batch != "":
        query = query.where(StockMovement.batch == batch)
    if reference_type:
        query = query.where(StockMovement.reference_type == reference_type.upper())
    if reference:
        query = query.where(StockMovement.reference_ref == reference)
    if date_from:
        query = query.where(StockMovement.created_at >= clock.at_ist(date_from, 0, 0))
    if date_to:
        query = query.where(StockMovement.created_at < clock.at_ist(date_to + timedelta(days=1), 0, 0))
    return query


REFERENCE_PATHS = {"GOODS_RECEIPT": "goods-receipts", "INSPECTION_LOT": "inspection-lots", "RETURN_DELIVERY": "return-deliveries", "STOCK_POSTING": "stock-postings",
                   "PHYSICAL_INVENTORY": "physical-inventories", "STOCK_RESERVATION": "reservations", "PURCHASE_ORDER": "purchase-orders"}


def movement_rows(session: Session, movements: list[StockMovement]) -> list[dict]:
    materials = {m.id: m for m in session.execute(select(Material).where(Material.id.in_({x.material_id for x in movements} or {uuid.uuid4()}))).scalars()}
    users = {u.id: u for u in session.execute(select(AppUser).where(AppUser.id.in_({x.created_by for x in movements if x.created_by} or {uuid.uuid4()}))).scalars()}
    out = []
    for x in movements:
        m = materials[x.material_id]
        actor = users.get(x.created_by)
        out.append({"id": str(x.id), "createdAt": x.created_at.isoformat(), "material": m.number, "description": m.description, "uom": m.base_uom, "plant": x.plant,
                    "storageLocation": x.storage_location, "stockType": x.stock_type, "batch": x.batch, "movementType": x.movement_type,
                    "movementText": stock_ledger.movement_text(x.movement_type), "qty": jsonable(x.qty),
                    "valueMinor": x.value_minor if x.value_minor is not None else _price_value(x.qty, m.standard_price_minor),
                    "valuedAtPosting": x.value_minor is not None, "reasonCode": x.reason_code, "postingRef": x.posting_ref,
                    "reference": {"type": x.reference_type, "ref": x.reference_ref, "id": str(x.reference_id), "path": REFERENCE_PATHS.get(x.reference_type)},
                    "actor": {"id": str(actor.id), "name": actor.full_name, "email": actor.email} if actor else None})
    return out


def export_csv(session: Session, query) -> dict:
    """The ledger lines of ``query`` as CSV (at most MAX_EXPORT_ROWS, newest first); the export is audited with its hash."""
    rows = session.execute(query.order_by(StockMovement.created_at.desc(), StockMovement.id.desc()).limit(MAX_EXPORT_ROWS + 1)).scalars().all()
    truncated = len(rows) > MAX_EXPORT_ROWS
    lines = movement_rows(session, rows[:MAX_EXPORT_ROWS])
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(["Posted at", "Material", "Description", "UoM", "Plant", "Storage location", "Stock type", "Batch", "Movement", "Movement text", "Quantity",
                     "Value (INR)", "Reason code", "Posting ref", "Reference type", "Reference", "User"])
    from app.pic.services.finance_controls import _safe
    for r in lines:
        writer.writerow([_safe(x) for x in (r["createdAt"], r["material"], r["description"], r["uom"], r["plant"], r["storageLocation"], r["stockType"], r["batch"],
                                            r["movementType"], r["movementText"], r["qty"], f"{r['valueMinor'] / 100:.2f}" if r["valueMinor"] is not None else "",
                                            r["reasonCode"] or "", r["postingRef"] or "", r["reference"]["type"], r["reference"]["ref"],
                                            r["actor"]["email"] if r["actor"] else "")])
    content = out.getvalue()
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    audit.record(session, "STOCK_LEDGER_EXPORT", uuid.uuid5(uuid.NAMESPACE_URL, f"stock-ledger-export:{current_tenant(session)}"), "EXPORTED",
                 object_ref="stock-movements", after={"rows": len(lines), "truncated": truncated, "sha256": sha})
    return {"content": content, "sha256": sha, "rows": len(lines), "truncated": truncated, "fileName": f"stock_movements_{clock.today().isoformat()}.csv"}
