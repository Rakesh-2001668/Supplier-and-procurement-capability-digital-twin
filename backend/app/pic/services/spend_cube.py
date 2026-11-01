"""Spend cube engine (M01, SPD-01..05, Technical Document AD-04 / DD-06, NFR "cube query < 3 s on 50 M lines").

Reads never scan ``spend_line``. Two tenant tables hold the aggregates:

* ``spend_cube_summary``    posted spend by period × category × supplier (and its parent) × plant × company code × cost object ×
                            material group × currency × source × ERP system × contracted / addressable / maverick;
* ``spend_commitment_summary``  open PO commitments (PO value not yet invoiced) and received-not-invoiced value.

``refresh_spend_views(tenant_id)`` rebuilds them (everything, or only the periods whose spend lines changed: writing a
spend line marks its period dirty in the same transaction, so a refresh after a posting touches one period, not 36).
Reads that find a small backlog of dirty periods refresh them first; a large backlog is reported as ``stale`` and the
scheduled job (``spend.refresh_spend_views``) catches up.

Amounts: ``amount_minor`` is the document currency, ``amount_group_minor`` the tenant's group (base) currency converted with
the ``fx_rate`` stored on the line (and its ``fx_date``). Lines without a rate are counted in ``fx_missing_lines`` and left
out of group amounts rather than guessed.

Invoice and PO counts are distinct counts inside each summary row: an invoice that spans two categories counts once in each.
"""
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import and_, case, event, func, inspect, select, text
from sqlalchemy.orm import Session

from app.pic.db import current_tenant, tenant_tx
from app.pic.models import (
    FxRate, Material, SpendCommitmentSummary, SpendCubeSummary, SpendLine, SpendViewDirty, SpendViewState, Supplier, Tenant, TaxonomyNode,
)
from app.pic.platform import audit, clock, outbox
from app.pic.platform.errors import Problem

VIEWS = ("spend_cube_summary", "spend_commitment_summary")
OPEN_PO_STATUSES = ("RELEASED", "TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED", "RECEIVED")
AUTO_REFRESH_MAX_LINES = 250_000  # a read refreshes dirty periods itself up to this many spend lines
MAX_ROWS = 5000

C = SpendCubeSummary
# cube dimension name -> summary column
DIMENSIONS = {
    "period": C.period, "category": C.category, "supplier": C.supplier_id, "parent_supplier": C.parent_supplier_id, "plant": C.plant,
    "company_code": C.company_code, "cost_object": C.cost_object, "cost_object_type": C.cost_object_type, "material_group": C.material_group,
    "currency": C.currency, "source": C.source, "source_system": C.source_system, "contracted": C.contracted, "addressable": C.addressable,
    "maverick": C.maverick,
}
LEVEL_DIMENSIONS = {"category_l1": 1, "category_l2": 2, "category_l3": 3, "category_l4": 4}
# Dimensions the commitment summary shares with the cube (commitments can be joined on these).
COMMITMENT_DIMENSIONS = ("period", "category", "supplier", "parent_supplier", "plant", "company_code", "cost_object", "cost_object_type", "currency")
ALL_DIMENSIONS = tuple(DIMENSIONS) + tuple(LEVEL_DIMENSIONS)


# ---------------------------------------------------------------- dirty marks
@event.listens_for(Session, "after_flush")
def _mark_dirty(session: Session, flush_context) -> None:
    """A spend line was added, changed or removed: its period needs a refresh (one upsert per flush per tenant)."""
    marks: dict[uuid.UUID, set[str]] = defaultdict(set)
    for collection in (session.new, session.dirty, session.deleted):
        for obj in collection:
            if isinstance(obj, SpendLine) and obj.period:
                marks[obj.tenant_id].add(obj.period)
                if collection is session.dirty:
                    # a period change leaves the old period stale as well
                    for previous in inspect(obj).attrs.period.history.deleted:
                        marks[obj.tenant_id].add(previous)
    if not marks:
        return
    now = clock.now()
    connection = session.connection()
    for tenant_id, periods in marks.items():
        connection.execute(text(
            "INSERT INTO pic.spend_view_dirty (id, tenant_id, created_at, row_version, period, marked_at) "
            "SELECT gen_random_uuid(), CAST(:t AS uuid), :now, 1, p, :now FROM unnest(CAST(:periods AS text[])) AS p "
            "ON CONFLICT (tenant_id, period) DO UPDATE SET marked_at = EXCLUDED.marked_at"),
            {"t": str(tenant_id), "now": now, "periods": sorted(periods)})


# ---------------------------------------------------------------- filters
@dataclass
class CubeFilter:
    period_from: Optional[str] = None
    period_to: Optional[str] = None
    categories: list = field(default_factory=list)  # taxonomy node codes at any level (L1..L4) or leaf categories
    suppliers: list = field(default_factory=list)  # supplier codes (child)
    parents: list = field(default_factory=list)  # parent supplier codes
    plants: list = field(default_factory=list)
    company_codes: list = field(default_factory=list)
    cost_centres: list = field(default_factory=list)  # cost objects of type COST_CENTER
    wbs: list = field(default_factory=list)  # cost objects of type WBS
    cost_objects: list = field(default_factory=list)
    currencies: list = field(default_factory=list)
    source_systems: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    contracted: Optional[bool] = None
    addressable: Optional[bool] = None
    maverick: Optional[bool] = None

    def describe(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, [], "")}


def _group_currency(session: Session) -> str:
    tenant = session.get(Tenant, current_tenant(session))
    return (tenant.base_currency if tenant and tenant.base_currency else "INR").upper()


def _taxonomy(session: Session) -> dict:
    return {n.code: (n.parent_code, n.level, n.name) for n in session.execute(select(TaxonomyNode)).scalars()}


def _chain(taxonomy: dict, code: str) -> list[str]:
    chain, seen = [], set()
    while code and code in taxonomy and code not in seen:
        seen.add(code)
        chain.append(code)
        code = taxonomy[code][0]
    return list(reversed(chain))  # root first


def _descendants(taxonomy: dict, codes: list[str]) -> set[str]:
    children: dict[str, list[str]] = defaultdict(list)
    for code, (parent, _level, _name) in taxonomy.items():
        if parent:
            children[parent].append(code)
    out, stack = set(), list(codes)
    while stack:
        code = stack.pop()
        if code in out:
            continue
        out.add(code)
        stack.extend(children.get(code, []))
    return out


def _codes_to_ids(session: Session, codes: list[str]) -> list[uuid.UUID]:
    if not codes:
        return []
    return list(session.execute(select(Supplier.id).where(Supplier.code.in_(codes))).scalars())


def _conditions(session: Session, flt: CubeFilter, model=C) -> list:
    where = []
    if flt.period_from:
        where.append(model.period >= flt.period_from)
    if flt.period_to:
        where.append(model.period <= flt.period_to)
    if flt.categories:
        where.append(model.category.in_(_descendants(_taxonomy(session), flt.categories)))
    if flt.suppliers:
        where.append(model.supplier_id.in_(_codes_to_ids(session, flt.suppliers) or [uuid.UUID(int=0)]))
    if flt.parents:
        where.append(model.parent_supplier_id.in_(_codes_to_ids(session, flt.parents) or [uuid.UUID(int=0)]))
    if flt.plants:
        where.append(model.plant.in_(flt.plants))
    if flt.company_codes:
        where.append(model.company_code.in_(flt.company_codes))
    if flt.cost_centres:
        where.append(and_(model.cost_object_type == "COST_CENTER", model.cost_object.in_(flt.cost_centres)))
    if flt.wbs:
        where.append(and_(model.cost_object_type == "WBS", model.cost_object.in_(flt.wbs)))
    if flt.cost_objects:
        where.append(model.cost_object.in_(flt.cost_objects))
    if flt.currencies:
        where.append(model.currency.in_([c.upper() for c in flt.currencies]))
    if model is C:
        if flt.source_systems:
            where.append(C.source_system.in_(flt.source_systems))
        if flt.sources:
            where.append(C.source.in_(flt.sources))
        for column, value in ((C.contracted, flt.contracted), (C.addressable, flt.addressable), (C.maverick, flt.maverick)):
            if value is not None:
                where.append(column.is_(value))
    return where


# ---------------------------------------------------------------- refresh
def _period_end(period: str) -> date:
    year, month = int(period[:4]), int(period[5:])
    return (date(year + month // 12, month % 12 + 1, 1)) - timedelta(days=1)


def _rate(session: Session, from_ccy: str, to_ccy: str, on: date) -> Optional[tuple[Decimal, date]]:
    """Latest rate valid on ``on`` (direct, else the inverse of the opposite pair); None when there is none."""
    if from_ccy == to_ccy:
        return Decimal(1), on
    for a, b, invert in ((from_ccy, to_ccy, False), (to_ccy, from_ccy, True)):
        fx = session.execute(select(FxRate).where(FxRate.from_ccy == a, FxRate.to_ccy == b, FxRate.valid_from <= on)
                             .order_by(FxRate.valid_from.desc())).scalars().first()
        if fx:
            return ((Decimal(1) / fx.rate) if invert else fx.rate), fx.valid_from
    return None


def rate_for_line(session: Session, currency: str, on: date) -> Optional[tuple[Decimal, date]]:
    """FX rate (to the tenant's group currency) valid on the document date, stored on the spend line with its date."""
    return _rate(session, (currency or "INR").upper(), _group_currency(session), on)


def convert_pending_fx(session: Session, group_currency: str, periods: Optional[list[str]] = None) -> int:
    """Convert foreign-currency spend lines that have no group amount yet (a rate may have been added since they were posted).
    The rate and its date are stored on the line. Returns the number of lines converted."""
    tenant_id = current_tenant(session)
    query = ("SELECT DISTINCT currency, period FROM pic.spend_line WHERE tenant_id = :t AND currency <> :gc AND amount_group_minor IS NULL"
             + (" AND period = ANY(CAST(:periods AS text[]))" if periods else ""))
    params = {"t": tenant_id, "gc": group_currency, **({"periods": periods} if periods else {})}
    converted = 0
    for currency, period in session.execute(text(query), params).all():
        found = _rate(session, currency, group_currency, min(_period_end(period), clock.today()))
        if found is None:
            continue
        rate, rate_date = found
        result = session.execute(text(
            "UPDATE pic.spend_line SET fx_rate = :rate, fx_date = :d, amount_group_minor = round(amount_minor * CAST(:rate AS numeric)) "
            "WHERE tenant_id = :t AND currency = :c AND period = :p AND amount_group_minor IS NULL"),
            {"rate": rate, "d": rate_date, "t": tenant_id, "c": currency, "p": period})
        converted += result.rowcount
    return converted


_CUBE_INSERT = """
INSERT INTO pic.spend_cube_summary (id, tenant_id, created_at, row_version, period, category, supplier_id, parent_supplier_id, plant,
    company_code, cost_object, cost_object_type, material_group, currency, group_currency, source, source_system, contracted,
    addressable, maverick, lines, invoices, pos, auto_classified_lines, amount_minor, amount_group_minor, price_variance_group_minor,
    price_variance_last_group_minor, fx_missing_lines)
SELECT gen_random_uuid(), CAST(:t AS uuid), :now, 1, sl.period, sl.category, sl.supplier_id, COALESCE(su.parent_supplier_id, sl.supplier_id), sl.plant,
    sl.company_code, COALESCE(sl.cost_object, ''), COALESCE(sl.cost_object_type, ''), sl.material_group, sl.currency, :gc, sl.source,
    sl.source_system, sl.contracted, sl.addressable, (jsonb_array_length(sl.maverick_flags) > 0),
    count(*), count(DISTINCT sl.invoice_ref), count(DISTINCT sl.po_ref),
    count(*) FILTER (WHERE sl.classification_confidence >= 0.80 AND sl.classification_confidence < 1),
    sum(sl.amount_minor),
    COALESCE(sum(CASE WHEN sl.currency = :gc THEN sl.amount_minor ELSE sl.amount_group_minor END), 0),
    COALESCE(round(sum(COALESCE(sl.price_variance_minor, 0) * CASE WHEN sl.currency = :gc THEN 1 ELSE COALESCE(sl.fx_rate, 0) END)), 0),
    COALESCE(round(sum(COALESCE(sl.price_variance_last_minor, 0) * CASE WHEN sl.currency = :gc THEN 1 ELSE COALESCE(sl.fx_rate, 0) END)), 0),
    count(*) FILTER (WHERE sl.currency <> :gc AND sl.amount_group_minor IS NULL)
FROM pic.spend_line sl
LEFT JOIN pic.supplier su ON su.id = sl.supplier_id
WHERE sl.tenant_id = :t AND sl.period = :period
GROUP BY sl.period, sl.category, sl.supplier_id, COALESCE(su.parent_supplier_id, sl.supplier_id), sl.plant, sl.company_code,
    COALESCE(sl.cost_object, ''), COALESCE(sl.cost_object_type, ''), sl.material_group, sl.currency, sl.source, sl.source_system,
    sl.contracted, sl.addressable, (jsonb_array_length(sl.maverick_flags) > 0)
"""

_COMMITMENT_INSERT = """
INSERT INTO pic.spend_commitment_summary (id, tenant_id, created_at, row_version, period, category, supplier_id, parent_supplier_id, plant,
    company_code, cost_object, cost_object_type, currency, group_currency, fx_rate, fx_date, pos, lines, committed_minor,
    committed_group_minor, received_not_invoiced_minor)
SELECT gen_random_uuid(), CAST(:t AS uuid), :now, 1, to_char(pl.need_date, 'YYYY-MM'), COALESCE(m.category, pl.material_group), po.supplier_id,
    COALESCE(su.parent_supplier_id, po.supplier_id), pl.plant, po.company_code, COALESCE(pl.account_assignment_code, ''),
    COALESCE(pl.account_assignment_type, ''), po.currency, :gc, max(fx.rate), max(fx.d), count(DISTINCT po.id), count(*),
    sum(pl.net_minor - pl.invoiced_minor),
    CASE WHEN max(fx.rate) IS NULL THEN NULL ELSE round(sum(pl.net_minor - pl.invoiced_minor) * max(fx.rate)) END,
    COALESCE(sum(GREATEST(0, round(pl.net_minor * LEAST(pl.accepted_qty, pl.qty) / pl.qty) - pl.invoiced_minor)), 0)
FROM pic.po_line pl
JOIN pic.purchase_order po ON po.id = pl.po_id
LEFT JOIN pic.material m ON m.id = pl.material_id
LEFT JOIN pic.supplier su ON su.id = po.supplier_id
LEFT JOIN jsonb_to_recordset(CAST(:rates AS jsonb)) AS fx(ccy text, rate numeric, d date) ON fx.ccy = po.currency
WHERE pl.tenant_id = :t AND po.status = ANY(CAST(:statuses AS text[])) AND pl.net_minor > pl.invoiced_minor AND pl.qty > 0
GROUP BY to_char(pl.need_date, 'YYYY-MM'), COALESCE(m.category, pl.material_group), po.supplier_id, COALESCE(su.parent_supplier_id, po.supplier_id),
    pl.plant, po.company_code, COALESCE(pl.account_assignment_code, ''), COALESCE(pl.account_assignment_type, ''), po.currency
"""


def _state(session: Session, view: str) -> Optional[SpendViewState]:
    return session.execute(select(SpendViewState).where(SpendViewState.view_name == view)).scalar_one_or_none()


def _save_state(session: Session, view: str, started: float, mode: str, periods: int, source_rows: int, summary_rows: int) -> None:
    state = _state(session, view)
    values = dict(refreshed_at=clock.now(), mode=mode, periods_refreshed=periods, source_rows=source_rows, summary_rows=summary_rows,
                  duration_ms=int((time.perf_counter() - started) * 1000))
    if state is None:
        session.add(SpendViewState(tenant_id=current_tenant(session), view_name=view, **values))
    else:
        for key, value in values.items():
            setattr(state, key, value)
    session.flush()


def _refresh_cube(session: Session, group_currency: str, periods: Optional[list[str]]) -> dict:
    started, tenant_id, now = time.perf_counter(), current_tenant(session), clock.now()
    converted = convert_pending_fx(session, group_currency, periods)
    if periods is None:
        periods = [p for (p,) in session.execute(text("SELECT DISTINCT period FROM pic.spend_line WHERE tenant_id = :t ORDER BY period"),
                                                  {"t": tenant_id})]
        session.execute(text("DELETE FROM pic.spend_cube_summary WHERE tenant_id = :t"), {"t": tenant_id})
        mode = "FULL"
    else:
        periods = sorted(set(periods))
        session.execute(text("DELETE FROM pic.spend_cube_summary WHERE tenant_id = :t AND period = ANY(CAST(:periods AS text[]))"),
                        {"t": tenant_id, "periods": periods})
        mode = "PERIODS"
    for period in periods:  # one period at a time: bounded hash tables, and a period is the unit of incremental refresh
        session.execute(text(_CUBE_INSERT), {"t": tenant_id, "now": now, "gc": group_currency, "period": period})
    session.execute(text("DELETE FROM pic.spend_view_dirty WHERE tenant_id = :t AND period = ANY(CAST(:periods AS text[])) AND marked_at <= :now"),
                    {"t": tenant_id, "periods": periods, "now": now})
    if mode == "FULL":  # nothing left to refresh: marks for periods that no longer exist are meaningless
        session.execute(text("DELETE FROM pic.spend_view_dirty WHERE tenant_id = :t AND marked_at <= :now"), {"t": tenant_id, "now": now})
    totals = session.execute(select(func.coalesce(func.sum(C.lines), 0), func.count())).one()
    _save_state(session, "spend_cube_summary", started, mode, len(periods), int(totals[0]), int(totals[1]))
    return {"mode": mode, "periods": len(periods), "lines": int(totals[0]), "summaryRows": int(totals[1]), "fxConverted": converted}


def _refresh_commitments(session: Session, group_currency: str) -> dict:
    started, tenant_id, now = time.perf_counter(), current_tenant(session), clock.now()
    session.execute(text("DELETE FROM pic.spend_commitment_summary WHERE tenant_id = :t"), {"t": tenant_id})
    currencies = [c for (c,) in session.execute(text(
        "SELECT DISTINCT po.currency FROM pic.purchase_order po WHERE po.tenant_id = :t AND po.status = ANY(CAST(:s AS text[]))"),
        {"t": tenant_id, "s": list(OPEN_PO_STATUSES)})]
    rates = []
    for currency in currencies:
        found = _rate(session, currency, group_currency, clock.today())
        if found:
            rates.append({"ccy": currency, "rate": str(found[0]), "d": found[1].isoformat()})
    import json
    session.execute(text(_COMMITMENT_INSERT), {"t": tenant_id, "now": now, "gc": group_currency, "rates": json.dumps(rates),
                                              "statuses": list(OPEN_PO_STATUSES)})
    totals = session.execute(select(func.coalesce(func.sum(SpendCommitmentSummary.lines), 0), func.count())).one()
    _save_state(session, "spend_commitment_summary", started, "FULL", 0, int(totals[0]), int(totals[1]))
    return {"mode": "FULL", "lines": int(totals[0]), "summaryRows": int(totals[1])}


def refresh(session: Session, *, periods: Optional[list[str]] = None, commitments: bool = True, record_audit: bool = True) -> dict:
    """Rebuild the summaries inside the caller's tenant transaction (``periods=None``: everything)."""
    tenant_id = current_tenant(session)
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"spendview:{tenant_id}"})
    group_currency = _group_currency(session)
    started = time.perf_counter()
    result = {"groupCurrency": group_currency, "cube": _refresh_cube(session, group_currency, periods)}
    if commitments:
        result["commitments"] = _refresh_commitments(session, group_currency)
    result["durationMs"] = int((time.perf_counter() - started) * 1000)
    if record_audit and (periods is None or session.info.get("principal") is not None):
        audit.record(session, "SPEND_CUBE", tenant_id, "REFRESHED", object_ref="spend_cube",
                     after={"mode": result["cube"]["mode"], "periods": result["cube"]["periods"], "lines": result["cube"]["lines"],
                            "durationMs": result["durationMs"]})
        outbox.emit(session, "spend.cube.refreshed", "SPEND_CUBE", tenant_id, "spend_cube",
                    {"mode": result["cube"]["mode"], "periods": result["cube"]["periods"], "lines": result["cube"]["lines"]})
    return result


def refresh_spend_views(tenant_id: uuid.UUID, *, periods: Optional[list[str]] = None, dirty_only: bool = False, full: bool = False,
                        commitments: bool = True, session: Optional[Session] = None) -> dict:
    """Entry point for the scheduler and the admin API. ``dirty_only`` refreshes just the periods marked dirty (the cheap
    near-real-time path: run it every few minutes); ``full`` rebuilds everything; the default does a full rebuild when the
    cube was never built and the dirty periods otherwise. Opens its own tenant transaction unless a session is passed."""
    def run(s: Session) -> dict:
        state = _state(s, "spend_cube_summary")
        if full or (periods is None and not dirty_only and state is None):
            return refresh(s, commitments=commitments)
        chosen = sorted(set(periods)) if periods else [p for (p,) in s.execute(select(SpendViewDirty.period).order_by(SpendViewDirty.period))]
        return refresh(s, periods=chosen, commitments=commitments, record_audit=bool(chosen))
    if session is not None:
        return run(session)
    with tenant_tx(tenant_id) as s:
        return run(s)


# ---------------------------------------------------------------- freshness
def freshness(session: Session) -> dict:
    state = _state(session, "spend_cube_summary")
    dirty = [p for (p,) in session.execute(select(SpendViewDirty.period).order_by(SpendViewDirty.period))]
    return {"asOf": state.refreshed_at.isoformat() if state else None, "mode": state.mode if state else None,
            "durationMs": state.duration_ms if state else None, "summaryRows": state.summary_rows if state else 0,
            "dirtyPeriods": dirty, "stale": bool(dirty) or state is None}


def ensure_fresh(session: Session) -> dict:
    """Refresh dirty periods when the backlog is small; report ``stale`` when it is not (the scheduled job catches up)."""
    state = _state(session, "spend_cube_summary")
    dirty = [p for (p,) in session.execute(select(SpendViewDirty.period))]
    if state is not None and not dirty:
        return freshness(session)
    # A cube that was never built is built whole; otherwise only the dirty periods are rebuilt.
    scope = None if state is None else dirty
    query = select(SpendLine.id)
    if scope is not None:
        query = query.where(SpendLine.period.in_(scope))
    size = session.execute(select(func.count()).select_from(query.limit(AUTO_REFRESH_MAX_LINES + 1).subquery())).scalar()
    if size and size <= AUTO_REFRESH_MAX_LINES:
        refresh(session, periods=scope, commitments=_commitments_stale(session), record_audit=False)
    elif state is None and not size:  # nothing posted yet
        pass
    return freshness(session)


def ensure_commitments_fresh(session: Session) -> None:
    if not _commitments_stale(session):
        return
    open_lines = session.execute(select(func.count()).select_from(
        text("(SELECT 1 FROM pic.po_line LIMIT :n) x").bindparams(n=AUTO_REFRESH_MAX_LINES + 1))).scalar()
    if open_lines <= AUTO_REFRESH_MAX_LINES:
        _refresh_commitments(session, _group_currency(session))


def _commitments_stale(session: Session) -> bool:
    state = _state(session, "spend_commitment_summary")
    return state is None or state.refreshed_at < clock.now() - timedelta(minutes=5)


# ---------------------------------------------------------------- queries
def _supplier_names(session: Session, ids: set) -> dict:
    if not ids:
        return {}
    return {s.id: (s.code, s.legal_name) for s in session.execute(select(Supplier).where(Supplier.id.in_(ids))).scalars()}


def _pct(num, den) -> str:
    return str((Decimal(num) * 100 / Decimal(den)).quantize(Decimal("0.1"), ROUND_HALF_UP)) if den else "0"


def measures():
    group = C.amount_group_minor
    return {
        "spendMinor": func.sum(group), "docSpendMinor": func.sum(C.amount_minor), "lines": func.sum(C.lines), "invoices": func.sum(C.invoices),
        "pos": func.sum(C.pos), "contractedMinor": func.sum(case((C.contracted.is_(True), group), else_=0)),
        "maverickMinor": func.sum(case((C.maverick.is_(True), group), else_=0)),
        "addressableMinor": func.sum(case((C.addressable.is_(True), group), else_=0)),
        "priceVarianceMinor": func.sum(C.price_variance_group_minor), "priceVarianceLastMinor": func.sum(C.price_variance_last_group_minor),
        "fxMissingLines": func.sum(C.fx_missing_lines),
    }


def _shape(values: dict) -> dict:
    out = {k: int(v or 0) for k, v in values.items()}
    out["consumptionMinor"] = out["contractedMinor"]  # spend released against contracts (contract consumption)
    out["contractCoveragePct"] = _pct(out["contractedMinor"], out["spendMinor"])
    out["maverickPct"] = _pct(out["maverickMinor"], out["spendMinor"])
    return out


def cube(session: Session, dimensions: list[str], flt: Optional[CubeFilter] = None, *, limit: int = 1000, include_commitments: bool = False,
         fresh: bool = True) -> dict:
    """The spend cube: group by any dimensions, filtered, from the summary (milliseconds at 50 M source lines)."""
    flt = flt or CubeFilter()
    unknown = [d for d in dimensions if d and d not in ALL_DIMENSIONS]
    if unknown:
        raise Problem(400, "INVALID_DIMENSION", f"Unknown spend dimension(s): {', '.join(unknown)}. Use {', '.join(sorted(ALL_DIMENSIONS))}")
    if not 1 <= limit <= MAX_ROWS:
        raise Problem(422, "INVALID_LIMIT", f"limit must be between 1 and {MAX_ROWS}")
    dims = [d for d in dimensions if d] or ["category"]
    state = ensure_fresh(session) if fresh else freshness(session)
    group_currency = _group_currency(session)
    where = _conditions(session, flt)
    expressions = measures()
    level_dims = [d for d in dims if d in LEVEL_DIMENSIONS]
    sql_dims = list(dict.fromkeys([d for d in dims if d in DIMENSIONS] + (["category"] if level_dims else [])))
    columns = [DIMENSIONS[d].label(d) for d in sql_dims]
    query = select(*columns, *[e.label(k) for k, e in expressions.items()]).where(*where)
    if columns:
        query = query.group_by(*[DIMENSIONS[d] for d in sql_dims])
    query = query.order_by(func.sum(C.amount_group_minor).desc())
    if not level_dims:
        query = query.limit(limit + 1)
    rows = session.execute(query).mappings().all()
    taxonomy = _taxonomy(session) if (level_dims or "category" in dims) else {}
    names = _supplier_names(session, {r[d] for r in rows for d in ("supplier", "parent_supplier") if d in r})
    merged: dict[tuple, dict] = {}
    for r in rows:
        key_values = {}
        for d in dims:
            if d in LEVEL_DIMENSIONS:
                chain = _chain(taxonomy, r["category"])
                level = LEVEL_DIMENSIONS[d]
                code = chain[level - 1] if len(chain) >= level else (chain[-1] if chain else r["category"])
                key_values[d] = code
            elif d in ("supplier", "parent_supplier"):
                key_values[d] = names.get(r[d], ("?", "Unknown supplier"))[0]
            else:
                key_values[d] = r[d]
        key = tuple(key_values.values())
        slot = merged.setdefault(key, {"key": key_values, **{k: 0 for k in expressions}})
        for k in expressions:
            slot[k] += int(r[k] or 0)
        if "supplier" in dims:
            slot["name"] = names.get(r["supplier"], ("?", "Unknown supplier"))[1]
        elif "parent_supplier" in dims:
            slot["name"] = names.get(r["parent_supplier"], ("?", "Unknown supplier"))[1]
        for d in LEVEL_DIMENSIONS:
            if d in dims:
                code = key_values[d]
                slot[f"{d}Name"] = taxonomy.get(code, (None, None, code))[2]
    ordered = sorted(merged.values(), key=lambda s: -s["spendMinor"])
    truncated = len(ordered) > limit
    out_rows = []
    for slot in ordered[:limit]:
        shaped = _shape({k: slot[k] for k in expressions})
        out_rows.append({**slot["key"], **{k: v for k, v in slot.items() if k.endswith("Name") or k == "name"}, **shaped})
    totals = session.execute(select(*[e.label(k) for k, e in expressions.items()]).where(*where)).mappings().one()
    total = _shape(dict(totals))
    result = {"dimensions": dims, "filters": flt.describe(), "currency": group_currency, "totalMinor": total["spendMinor"],
              "contractedPct": total["contractCoveragePct"], "maverickPct": total["maverickPct"], "totals": total, "rows": out_rows,
              "truncated": truncated, "freshness": state}
    foreign = session.execute(select(C.currency, func.sum(C.amount_minor)).where(*where).group_by(C.currency)).all()
    if len(foreign) > 1 or any(c != group_currency for c, _ in foreign):
        result["documentCurrencyTotals"] = {c: int(a or 0) for c, a in foreign}
    if include_commitments:
        result["commitments"] = commitments(session, [d for d in dims if d in COMMITMENT_DIMENSIONS], flt)
    return result


def commitments(session: Session, dimensions: list[str], flt: Optional[CubeFilter] = None) -> dict:
    """Open PO commitments and received-not-invoiced value (group currency), grouped by the shared dimensions."""
    flt = flt or CubeFilter()
    M = SpendCommitmentSummary
    mapping = {"period": M.period, "category": M.category, "supplier": M.supplier_id, "parent_supplier": M.parent_supplier_id, "plant": M.plant,
               "company_code": M.company_code, "cost_object": M.cost_object, "cost_object_type": M.cost_object_type, "currency": M.currency}
    dims = [d for d in dimensions if d in mapping]
    ensure_commitments_fresh(session)
    where = _conditions(session, flt, M)
    columns = [mapping[d].label(d) for d in dims]
    query = select(*columns, func.sum(M.committed_group_minor).label("committedMinor"), func.sum(M.committed_minor).label("docCommittedMinor"),
                   func.sum(M.received_not_invoiced_minor).label("receivedNotInvoicedMinor"), func.sum(M.pos).label("pos"),
                   func.count().filter(M.committed_group_minor.is_(None)).label("fxMissing")).where(*where)
    if columns:
        query = query.group_by(*[mapping[d] for d in dims])
    rows = session.execute(query.order_by(func.sum(M.committed_group_minor).desc().nulls_last()).limit(MAX_ROWS)).mappings().all()
    names = _supplier_names(session, {r[d] for r in rows for d in ("supplier", "parent_supplier") if d in r})
    out = []
    for r in rows:
        item = {d: (names.get(r[d], ("?", ""))[0] if d in ("supplier", "parent_supplier") else r[d]) for d in dims}
        item.update(committedMinor=int(r["committedMinor"] or 0), docCommittedMinor=int(r["docCommittedMinor"] or 0),
                    receivedNotInvoicedMinor=int(r["receivedNotInvoicedMinor"] or 0), pos=int(r["pos"] or 0), fxMissingRows=int(r["fxMissing"] or 0))
        out.append(item)
    total = {"committedMinor": sum(i["committedMinor"] for i in out), "receivedNotInvoicedMinor": sum(i["receivedNotInvoicedMinor"] for i in out)}
    state = _state(session, "spend_commitment_summary")
    return {"dimensions": dims, "totals": total, "rows": out, "asOf": state.refreshed_at.isoformat() if state else None}


def latest_period(session: Session) -> Optional[str]:
    ensure_fresh(session)
    return session.execute(select(func.max(C.period))).scalar()
