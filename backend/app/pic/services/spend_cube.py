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
the ``fx_rate`` stored on the line (and its ``fx_date``): the rate valid on the date of the document (the invoice date; a credit or debit
note line carries the rate of the invoice it corrects, so a credit nets its invoice exactly). Lines without a rate are counted in
``fx_missing_lines`` and left out of group amounts rather than guessed.

Documents: a line is an INVOICE line, a CREDIT_NOTE line (negative, in the period of the note) or a DEBIT_NOTE line (positive). Spend is
invoiced + debit notes - credit notes; the three parts are separate measures. A negative INVOICE line (an ERP credit memo in the history, which
the cutover loads as a signed line) counts as a credit note, not as an invoice. Purchase orders and goods receipts are not spend: open orders are
commitments (``spend_commitment_summary``) and are never added to posted spend, so a PO and its invoice are never both counted.

Invoice and PO counts are distinct counts inside each summary row: an invoice that spans two categories counts once in each; credit notes
do not count as invoices.

Scope: every query is restricted to the reader's ABAC scope (``spend_scope``) before it aggregates.
"""
import re
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
from app.pic.services import spend_scope

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
    "maverick": C.maverick, "buyer": C.buyer_id,
}
LEVEL_DIMENSIONS = {"category_l1": 1, "category_l2": 2, "category_l3": 3, "category_l4": 4}
# Calendar and fiscal roll-ups of the period (the fiscal year starts in the month of rule SPEND-GOVERNANCE.fiscalYearStartMonth, April by default).
TIME_DIMENSIONS = ("fiscal_year", "fiscal_quarter", "year", "quarter")
NIL = uuid.UUID(int=0)
# Dimensions the commitment summary shares with the cube (commitments can be joined on these).
COMMITMENT_DIMENSIONS = ("period", "category", "supplier", "parent_supplier", "plant", "company_code", "cost_object", "cost_object_type", "currency")
ALL_DIMENSIONS = tuple(DIMENSIONS) + tuple(LEVEL_DIMENSIONS) + TIME_DIMENSIONS


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
    buyers: list = field(default_factory=list)  # buyer e-mail addresses

    def describe(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, [], "")}

    def validate(self) -> "CubeFilter":
        """Refuse a malformed filter before it reaches SQL (values are always bound parameters; this is about clear errors and bounded input)."""
        for label, value in (("period_from", self.period_from), ("period_to", self.period_to)):
            if value is not None and not PERIOD_RE.fullmatch(value):
                raise Problem(422, "INVALID_PERIOD", f"{label} must be YYYY-MM with a month from 01 to 12")
        if self.period_from and self.period_to and self.period_from > self.period_to:
            raise Problem(422, "INVALID_PERIOD", f"period_from {self.period_from} is after period_to {self.period_to}")
        for name in LIST_FILTERS:
            values = getattr(self, name)
            if len(values) > 200:
                raise Problem(422, "INVALID_FILTER", f"{name}: at most 200 values")
            for value in values:
                if not isinstance(value, str) or not value or len(value) > 60 or "\x00" in value:
                    raise Problem(422, "INVALID_FILTER", f"{name}: each value is 1-60 characters")
        for value in self.currencies:
            if not re.fullmatch(r"[A-Za-z]{3}", value):
                raise Problem(422, "INVALID_FILTER", "currency must be a 3-letter ISO code")
        return self


LIST_FILTERS = ("categories", "suppliers", "parents", "plants", "company_codes", "cost_centres", "wbs", "cost_objects", "currencies", "source_systems",
                "sources", "buyers")
PERIOD_RE = re.compile(r"(19|20)\d\d-(0[1-9]|1[0-2])")


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
    flt.validate()
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
    where.extend(spend_scope.where(session, model))
    if model is C:
        if flt.buyers:
            from app.pic.models import AppUser
            # an unknown buyer matches nothing (the nil UUID is the "no buyer" bucket of the summary, so it must not stand for "unknown")
            where.append(C.buyer_id.in_(list(session.execute(select(AppUser.id).where(AppUser.email.in_(flt.buyers))).scalars()) or [uuid.UUID(int=1)]))
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
    today = clock.today()
    # The rate follows the date of the document; a line without one (ERP history, older lines) uses the end of its period (never the future).
    on = ("COALESCE(document_date, LEAST((to_date(period || '-01', 'YYYY-MM-DD') + interval '1 month - 1 day')::date, CAST(:today AS date)))")
    query = (f"SELECT DISTINCT currency, {on} FROM pic.spend_line WHERE tenant_id = :t AND currency <> :gc AND amount_group_minor IS NULL"
             + (" AND period = ANY(CAST(:periods AS text[]))" if periods else ""))
    params = {"t": tenant_id, "gc": group_currency, "today": today, **({"periods": periods} if periods else {})}
    converted = 0
    for currency, on_date in session.execute(text(query), params).all():
        found = _rate(session, currency, group_currency, on_date)
        if found is None:
            continue
        rate, rate_date = found
        result = session.execute(text(
            "UPDATE pic.spend_line SET fx_rate = :rate, fx_date = :d, amount_group_minor = round(amount_minor * CAST(:rate AS numeric)) "
            f"WHERE tenant_id = :t AND currency = :c AND amount_group_minor IS NULL AND {on} = :on"
            + (" AND period = ANY(CAST(:periods AS text[]))" if periods else "")),
            {"rate": rate, "d": rate_date, "t": tenant_id, "c": currency, "on": on_date, "today": today,
             **({"periods": periods} if periods else {})})
        converted += result.rowcount
    return converted


_CUBE_INSERT = """
INSERT INTO pic.spend_cube_summary (id, tenant_id, created_at, row_version, period, category, supplier_id, parent_supplier_id, buyer_id, plant,
    company_code, cost_object, cost_object_type, material_group, currency, group_currency, source, source_system, contracted,
    addressable, maverick, lines, invoices, pos, auto_classified_lines, amount_minor, amount_group_minor, invoiced_group_minor,
    debit_group_minor, credit_group_minor, price_variance_group_minor, price_variance_last_group_minor, fx_missing_lines)
SELECT gen_random_uuid(), CAST(:t AS uuid), :now, 1, sl.period, sl.category, sl.supplier_id, COALESCE(su.parent_supplier_id, sl.supplier_id),
    COALESCE(sl.buyer_id, CAST(:nil AS uuid)), sl.plant,
    sl.company_code, COALESCE(sl.cost_object, ''), COALESCE(sl.cost_object_type, ''), sl.material_group, sl.currency, :gc, sl.source,
    sl.source_system, sl.contracted, sl.addressable, (jsonb_array_length(sl.maverick_flags) > 0),
    count(*), count(DISTINCT sl.invoice_ref) FILTER (WHERE sl.document_type = 'INVOICE' AND sl.amount_minor >= 0),
    count(DISTINCT sl.po_ref) FILTER (WHERE sl.document_type <> 'CREDIT_NOTE'),
    count(*) FILTER (WHERE sl.document_type = 'INVOICE' AND sl.classification_confidence > 0 AND sl.classification_confidence < 1 AND cr.id IS NULL),
    sum(sl.amount_minor),
    COALESCE(sum(CASE WHEN sl.currency = :gc THEN sl.amount_minor ELSE sl.amount_group_minor END), 0),
    COALESCE(sum(CASE WHEN sl.currency = :gc THEN sl.amount_minor ELSE sl.amount_group_minor END) FILTER (WHERE sl.document_type = 'INVOICE' AND sl.amount_minor >= 0), 0),
    COALESCE(sum(CASE WHEN sl.currency = :gc THEN sl.amount_minor ELSE sl.amount_group_minor END) FILTER (WHERE sl.document_type = 'DEBIT_NOTE'), 0),
    COALESCE(sum(CASE WHEN sl.currency = :gc THEN sl.amount_minor ELSE sl.amount_group_minor END) FILTER (WHERE sl.document_type = 'CREDIT_NOTE' OR (sl.document_type = 'INVOICE' AND sl.amount_minor < 0)), 0),
    COALESCE(round(sum(COALESCE(sl.price_variance_minor, 0) * CASE WHEN sl.currency = :gc THEN 1 ELSE COALESCE(sl.fx_rate, 0) END)), 0),
    COALESCE(round(sum(COALESCE(sl.price_variance_last_minor, 0) * CASE WHEN sl.currency = :gc THEN 1 ELSE COALESCE(sl.fx_rate, 0) END)), 0),
    count(*) FILTER (WHERE sl.currency <> :gc AND sl.amount_group_minor IS NULL)
FROM pic.spend_line sl
LEFT JOIN pic.supplier su ON su.id = sl.supplier_id
LEFT JOIN pic.classification_review cr ON cr.spend_line_id = sl.id
WHERE sl.tenant_id = :t AND sl.period = :period
GROUP BY sl.period, sl.category, sl.supplier_id, COALESCE(su.parent_supplier_id, sl.supplier_id), COALESCE(sl.buyer_id, CAST(:nil AS uuid)), sl.plant,
    sl.company_code, COALESCE(sl.cost_object, ''), COALESCE(sl.cost_object_type, ''), sl.material_group, sl.currency, sl.source, sl.source_system,
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
    """The refresh state row as it is NOW (populate_existing): a refresh that waited for the lock of another one must not update a copy that
    was loaded before the other committed (that is a StaleDataError, a 412 on a read)."""
    return session.execute(select(SpendViewState).where(SpendViewState.view_name == view).execution_options(populate_existing=True)).scalar_one_or_none()


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
        session.execute(text(_CUBE_INSERT), {"t": tenant_id, "now": now, "gc": group_currency, "period": period, "nil": str(NIL)})
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
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"spendview:{tenant_id}"})   # a refresh that is asked for waits its turn
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
        if full or (periods is None and state is None):   # a cube that was never built is built whole, whatever was asked
            return refresh(s, commitments=commitments)
        chosen = sorted(set(periods)) if periods else [p for (p,) in s.execute(select(SpendViewDirty.period).order_by(SpendViewDirty.period))]
        return refresh(s, periods=chosen, commitments=commitments, record_audit=bool(chosen))
    if session is not None:
        return run(session)
    with tenant_tx(tenant_id) as s:
        return run(s)


# ---------------------------------------------------------------- freshness
FEED_TOPICS = ("invoice.posted", "debit_note.posted")


def pending_events(session: Session) -> int:
    """Posted invoices / debit notes whose event the spend consumer has not processed yet: the cube does not know them (eventual
    consistency of the outbox, normally seconds). The cube is as fresh as its last refresh AND this count being zero."""
    from app.pic.models import OutboxEvent
    return int(session.execute(select(func.count()).select_from(OutboxEvent).where(
        OutboxEvent.published_at.is_(None), OutboxEvent.topic.in_(FEED_TOPICS))).scalar() or 0)


def freshness(session: Session) -> dict:
    state = _state(session, "spend_cube_summary")
    dirty = [p for (p,) in session.execute(select(SpendViewDirty.period).order_by(SpendViewDirty.period))]
    pending = pending_events(session)
    return {"asOf": state.refreshed_at.isoformat() if state else None, "mode": state.mode if state else None,
            "durationMs": state.duration_ms if state else None, "summaryRows": state.summary_rows if state else 0,
            "dirtyPeriods": dirty, "pendingEvents": pending, "feedBehind": pending > 0, "stale": bool(dirty) or state is None}


def ensure_fresh(session: Session) -> dict:
    """Refresh dirty periods when the backlog is small; report ``stale`` when it is not (the scheduled job catches up)."""
    state = _state(session, "spend_cube_summary")
    dirty = [p for (p,) in session.execute(select(SpendViewDirty.period))]
    if state is not None and not dirty:
        return freshness(session)
    # A READ never waits for, or races with, a refresh that is running (the scheduler, the admin button, another reader): it takes the refresh lock
    # only if it is free and otherwise serves the data as it is (``freshness`` says which periods are still dirty). Under the lock the state and
    # the dirty periods are read again: the refresh that held it may have done the work.
    if not session.execute(text("SELECT pg_try_advisory_xact_lock(hashtext(:k))"), {"k": f"spendview:{current_tenant(session)}"}).scalar():
        return freshness(session)
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
    if not session.execute(text("SELECT pg_try_advisory_xact_lock(hashtext(:k))"), {"k": f"spendview:{current_tenant(session)}"}).scalar():
        return   # a refresh is running: serve the commitments as they are
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
    addr = C.addressable.is_(True)
    return {
        "spendMinor": func.sum(group), "docSpendMinor": func.sum(C.amount_minor), "lines": func.sum(C.lines), "invoices": func.sum(C.invoices),
        "pos": func.sum(C.pos), "invoicedMinor": func.sum(C.invoiced_group_minor), "debitNoteMinor": func.sum(C.debit_group_minor),
        "creditNoteMinor": func.sum(C.credit_group_minor), "contractedMinor": func.sum(case((C.contracted.is_(True), group), else_=0)),
        "maverickMinor": func.sum(case((C.maverick.is_(True), group), else_=0)),
        "addressableMinor": func.sum(case((addr, group), else_=0)),
        "contractedAddressableMinor": func.sum(case((addr & C.contracted.is_(True), group), else_=0)),
        "maverickAddressableMinor": func.sum(case((addr & C.maverick.is_(True), group), else_=0)),
        "priceVarianceMinor": func.sum(C.price_variance_group_minor), "priceVarianceLastMinor": func.sum(C.price_variance_last_group_minor),
        "fxMissingLines": func.sum(C.fx_missing_lines),
    }


def _shape(values: dict) -> dict:
    """Amounts as integers plus the ratios. Coverage and maverick share are shares of ADDRESSABLE spend (BP 7.4: intercompany and
    non-addressable categories are not part of the base); ``addressablePct`` is the addressable share of all spend. A ratio whose base is
    zero or negative is 0, never a division error or a negative percentage."""
    out = {k: int(v or 0) for k, v in values.items()}
    out["consumptionMinor"] = out["contractedMinor"]  # spend released against contracts (contract consumption)
    out["addressablePct"] = _pct(out["addressableMinor"], out["spendMinor"])
    out["contractCoveragePct"] = _pct(out["contractedAddressableMinor"], out["addressableMinor"])
    out["maverickPct"] = _pct(out["maverickAddressableMinor"], out["addressableMinor"])
    out["priceVariancePct"] = _pct(out["priceVarianceMinor"], out["spendMinor"])
    return out


def fiscal_start_month(session: Session) -> int:
    from app.pic.platform import rules
    try:
        month = int(rules.resolve(session, "SPEND-GOVERNANCE").body.get("fiscalYearStartMonth", 4))
    except Exception:  # noqa: BLE001 - a tenant without the rule set uses the Indian fiscal year
        month = 4
    return month if 1 <= month <= 12 else 4


def time_label(dimension: str, period: str, start_month: int) -> str:
    """Roll a YYYY-MM period up: ``year`` 2026, ``quarter`` 2026-Q3 (calendar), ``fiscal_year`` 2026-27, ``fiscal_quarter`` 2026-27 Q2."""
    year, month = int(period[:4]), int(period[5:])
    if dimension == "year":
        return f"{year:04d}"
    if dimension == "quarter":
        return f"{year:04d}-Q{(month - 1) // 3 + 1}"
    start_year = year if month >= start_month else year - 1
    label = f"{start_year}-{str(start_year + 1)[-2:]}" if start_month != 1 else f"{year:04d}"
    if dimension == "fiscal_year":
        return label
    return f"{label} Q{((month - start_month) % 12) // 3 + 1}"


def time_expression(dimension: str, start_month: int):
    """SQL expression of a time dimension over ``period`` (YYYY-MM), so the database rolls months up (a fiscal-year query returns a few rows
    per other dimension, not one per month)."""
    from sqlalchemy import Integer, String, cast, literal
    year, month = cast(func.substr(C.period, 1, 4), Integer), cast(func.substr(C.period, 6, 2), Integer)
    if dimension == "year":
        return func.substr(C.period, 1, 4)
    if dimension == "quarter":
        return func.substr(C.period, 1, 4) + literal("-Q") + cast((month + 2) // 3, String)
    start_year = case((month >= start_month, year), else_=year - 1)
    label = func.substr(C.period, 1, 4) if start_month == 1 else cast(start_year, String) + literal("-") + func.substr(cast(start_year + 1, String), 3, 2)
    if dimension == "fiscal_year":
        return label
    return label + literal(" Q") + cast(((month - start_month + 12) % 12) // 3 + 1, String)


def fiscal_year_periods(fiscal_year: str, start_month: int) -> list[str]:
    """The twelve YYYY-MM periods of a fiscal year label such as '2026-27'."""
    start = int(fiscal_year[:4])
    return [f"{start + (start_month - 1 + i) // 12:04d}-{(start_month - 1 + i) % 12 + 1:02d}" for i in range(12)]


def cube(session: Session, dimensions: list[str], flt: Optional[CubeFilter] = None, *, limit: int = 1000, include_commitments: bool = False,
         fresh: bool = True) -> dict:
    """The spend cube: group by any dimensions, filtered, from the summary (milliseconds at 50 M source lines)."""
    flt = flt or CubeFilter()
    unknown = [d for d in dimensions if d and d not in ALL_DIMENSIONS]
    if unknown:
        raise Problem(400, "INVALID_DIMENSION", f"Unknown spend dimension(s): {', '.join(unknown)}. Use {', '.join(sorted(ALL_DIMENSIONS))}")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_ROWS:
        raise Problem(422, "INVALID_LIMIT", f"limit must be between 1 and {MAX_ROWS}")
    if flt.period_from and flt.period_to and flt.period_from > flt.period_to:
        raise Problem(422, "INVALID_PERIOD", f"period_from {flt.period_from} is after period_to {flt.period_to}")
    dims = list(dict.fromkeys(d for d in dimensions if d)) or ["category"]
    state = ensure_fresh(session) if fresh else freshness(session)
    group_currency = _group_currency(session)
    where = _conditions(session, flt)
    expressions = measures()
    level_dims = [d for d in dims if d in LEVEL_DIMENSIONS]
    time_dims = [d for d in dims if d in TIME_DIMENSIONS]
    start_month = fiscal_start_month(session) if time_dims else 4
    sql_dims = list(dict.fromkeys([d for d in dims if d in DIMENSIONS] + (["category"] if level_dims else [])))
    time_exprs = [time_expression(d, start_month) for d in time_dims]
    columns = [DIMENSIONS[d].label(d) for d in sql_dims] + [e.label(d) for d, e in zip(time_dims, time_exprs)]
    group_columns = [DIMENSIONS[d] for d in sql_dims] + time_exprs
    query = select(*columns, *[e.label(k) for k, e in expressions.items()]).where(*where)
    if columns:
        query = query.group_by(*group_columns)
    # ties on spend are ordered by the dimension values, so the same request always returns the same rows
    query = query.order_by(func.sum(C.amount_group_minor).desc(), *group_columns)
    derived = bool(level_dims)
    if not derived:
        query = query.limit(limit + 1)
    rows = session.execute(query).mappings().all()
    taxonomy = _taxonomy(session) if (level_dims or "category" in dims) else {}
    names = _supplier_names(session, {r[d] for r in rows for d in ("supplier", "parent_supplier") if d in r})
    buyers = _buyer_names(session, {r["buyer"] for r in rows if "buyer" in r})
    merged: dict[tuple, dict] = {}
    for r in rows:
        key_values = {}
        for d in dims:
            if d in LEVEL_DIMENSIONS:
                chain = _chain(taxonomy, r["category"])
                level = LEVEL_DIMENSIONS[d]
                code = chain[level - 1] if len(chain) >= level else (chain[-1] if chain else r["category"])
                key_values[d] = code
            elif d in TIME_DIMENSIONS:
                key_values[d] = r[d]
            elif d in ("supplier", "parent_supplier"):
                key_values[d] = names.get(r[d], ("?", "Unknown supplier"))[0]
            elif d == "buyer":
                key_values[d] = buyers.get(r[d], ("", "No buyer"))[0] or None
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
        if "buyer" in dims:
            slot["buyerName"] = buyers.get(r["buyer"], ("", "No buyer"))[1]
        for d in LEVEL_DIMENSIONS:
            if d in dims:
                code = key_values[d]
                slot[f"{d}Name"] = taxonomy.get(code, (None, None, code))[2]
    ordered = sorted(merged.values(), key=lambda s: (-s["spendMinor"], [str(v) for v in s["key"].values()]))
    truncated = len(ordered) > limit
    out_rows = []
    for slot in ordered[:limit]:
        shaped = _shape({k: slot[k] for k in expressions})
        out_rows.append({**slot["key"], **{k: v for k, v in slot.items() if k.endswith("Name") or k == "name"}, **shaped})
    totals = session.execute(select(*[e.label(k) for k, e in expressions.items()]).where(*where)).mappings().one()
    total = _shape(dict(totals))
    result = {"dimensions": dims, "filters": flt.describe(), "currency": group_currency, "totalMinor": total["spendMinor"],
              "contractedPct": total["contractCoveragePct"], "maverickPct": total["maverickPct"], "totals": total, "rows": out_rows,
              "truncated": truncated, "freshness": state, "scope": spend_scope.of(session).describe() or None}
    foreign = session.execute(select(C.currency, func.sum(C.amount_minor)).where(*where).group_by(C.currency)).all()
    if len(foreign) > 1 or any(c != group_currency for c, _ in foreign):
        result["documentCurrencyTotals"] = {c: int(a or 0) for c, a in foreign}
    if include_commitments:
        result["commitments"] = commitments(session, [d for d in dims if d in COMMITMENT_DIMENSIONS], flt)
    return result


def _buyer_names(session: Session, ids: set) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    from app.pic.models import AppUser
    return {u.id: (u.email, u.full_name) for u in session.execute(select(AppUser).where(AppUser.id.in_(ids))).scalars()}


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
