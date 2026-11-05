"""KPI framework (Blueprint §27, Table 28): a registry of KPI definitions with formula, unit, scope, thresholds and source, a
compute function per KPI over the live tables, month-end snapshots for the trend, and the API read model.

* ``REGISTRY``       every KPI of the 13 modules plus the industry-template KPIs, keyed by code (``M10.FIRST_PASS_MATCH``).
* ``evaluate``       the current value of one KPI (optionally for one month and one plant).
* ``snapshot_kpis``  persists the month's values (``kpi_snapshot``); the scheduler calls it at month end (engineer A's job).
* ``register``       lets another module add or replace a KPI (the industry modules register the ones that need their data).

Thresholds are the defaults below unless the tenant's ``KPI-THRESHOLDS`` rule set overrides ``target`` / ``warn`` per code.
A KPI with nothing to measure yet reports ``value: null`` and status ``NA``; it never invents a number.
"""
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.pic.db import current_tenant, tenant_tx
from app.pic.models import KpiSnapshot
from app.pic.platform import audit, clock, rules
from app.pic.platform.errors import Problem

UNITS = ("PCT", "DAYS", "HOURS", "COUNT", "MINOR", "PPM", "RATIO")
Result = tuple  # (value, numerator, denominator, detail)


@dataclass(frozen=True)
class KpiDef:
    code: str
    module: str  # M01..M13 or TEMPLATE
    name: str
    unit: str
    direction: str  # HIGHER_BETTER | LOWER_BETTER | INFO
    formula: str
    source: str
    target: Optional[float] = None
    warn: Optional[float] = None
    scopes: tuple = ("TENANT",)  # TENANT | PLANT
    point_in_time: bool = False  # a backlog / stock KPI: the value is as of the run, not of the month
    templates: tuple = ()  # industry templates the KPI is for ((): every tenant)
    compute: Optional[Callable] = field(default=None, compare=False, repr=False)
    needs: Optional[str] = None  # what the KPI waits for when it has no compute function yet


REGISTRY: dict[str, KpiDef] = {}


def register(definition: KpiDef) -> KpiDef:
    """Add or replace a KPI definition (an industry module registers the compute function of its own KPIs here)."""
    if definition.unit not in UNITS:
        raise ValueError(f"{definition.code}: unit must be one of {UNITS}")
    if definition.direction not in ("HIGHER_BETTER", "LOWER_BETTER", "INFO"):
        raise ValueError(f"{definition.code}: direction")
    REGISTRY[definition.code] = definition
    return definition


# ---------------------------------------------------------------- compute context
class Ctx:
    """SQL helper bound to a session, an optional month and an optional plant."""

    def __init__(self, session: Session, period: Optional[str] = None, plant: Optional[str] = None):
        self.session, self.period, self.plant = session, period, plant
        if period:
            year, month = int(period[:4]), int(period[5:])
            self.start = date(year, month, 1)
            self.end = date(year + month // 12, month % 12 + 1, 1)
        else:
            self.start = self.end = None

    def when(self, column: str) -> str:
        """`AND <column>` falls inside the month (nothing for the whole history)."""
        return f" AND {column} >= :kstart AND {column} < :kend" if self.period else ""

    def at(self, column: str) -> str:
        """`AND <column>` is on or before the end of the month (balances: backlog, expiries)."""
        return f" AND {column} < :kend" if self.period else ""

    def at_plant(self, column: str) -> str:
        return f" AND {column} = :kplant" if self.plant else ""

    def params(self, **extra) -> dict:
        out = dict(extra)
        if self.period:
            out.update(kstart=self.start, kend=self.end)
        if self.plant:
            out["kplant"] = self.plant
        return out

    def one(self, sql: str, **extra):
        return self.session.execute(text(sql), self.params(**extra)).one()

    def scalar(self, sql: str, **extra):
        return self.session.execute(text(sql), self.params(**extra)).scalar()

    def periods(self) -> tuple[str, str]:
        return (self.period, self.period) if self.period else ("0000-00", "9999-99")


def _d(value) -> Optional[Decimal]:
    return None if value is None else Decimal(str(value))


def pct(num, den, detail: Optional[dict] = None) -> Result:
    num, den = _d(num) or Decimal(0), _d(den) or Decimal(0)
    return ((num * 100 / den).quantize(Decimal("0.1"), ROUND_HALF_UP) if den else None, num, den, detail or {})


def mean(total, count, scale=Decimal(1), detail: Optional[dict] = None) -> Result:
    total, count = _d(total), _d(count) or Decimal(0)
    if not count or total is None:
        return None, total, count, detail or {}
    return (total / count / scale).quantize(Decimal("0.1"), ROUND_HALF_UP), total, count, detail or {}


def count_of(n, detail: Optional[dict] = None) -> Result:
    return Decimal(int(n or 0)), Decimal(int(n or 0)), None, detail or {}


DAY, HOUR = 86400, 3600
MINUTES_SAVED_PER_AGENT_RUN = Decimal(6)


# ---------------------------------------------------------------- M01 spend & category intelligence
def _portfolio(c: Ctx) -> dict:
    from app.pic.services import spend
    return spend.portfolio(c.session, *c.periods(), plant=c.plant)


def m01_under_management(c: Ctx) -> Result:
    p = _portfolio(c)
    return pct(p["managedMinor"], p["addressableMinor"])


def m01_contract_coverage(c: Ctx) -> Result:
    p = _portfolio(c)
    return pct(p["contractedMinor"], p["addressableMinor"])


def m01_maverick(c: Ctx) -> Result:
    p = _portfolio(c)
    return pct(p["maverickMinor"], p["addressableMinor"])


def m01_classification(c: Ctx) -> Result:
    p = _portfolio(c)
    decided = dict(c.session.execute(text("SELECT status, count(*) FROM pic.classification_review GROUP BY status")).all())
    accepted = p["autoClassifiedLines"] + decided.get("ACCEPTED", 0)
    return pct(accepted, p["autoClassifiedLines"] + decided.get("ACCEPTED", 0) + decided.get("RECLASSIFIED", 0))


def m01_tail_spend(c: Ctx) -> Result:
    """Share of spend with the long-tail suppliers: parent suppliers beyond 80% cumulative spend (class C of the Pareto ranking)."""
    from app.pic.services import spend_analytics, spend_cube
    lo, hi = c.periods()
    flt = spend_cube.CubeFilter(period_from=None if lo == "0000-00" else lo, period_to=None if hi == "9999-99" else hi, plants=[c.plant] if c.plant else [],
                                addressable=True)
    p = spend_analytics.pareto(c.session, "parent_supplier", flt, limit=1)
    return pct(p["tailSpendMinor"], p["totalMinor"], {"tailSuppliers": p["tailCount"], "suppliers": p["count"]})


def m01_suppliers_per_category(c: Ctx) -> Result:
    """Supplier consolidation: average number of parent suppliers per category (addressable spend, categories with spend)."""
    from app.pic.services import spend_analytics, spend_cube
    lo, hi = c.periods()
    flt = spend_cube.CubeFilter(period_from=None if lo == "0000-00" else lo, period_to=None if hi == "9999-99" else hi, plants=[c.plant] if c.plant else [],
                                addressable=True)
    rows = spend_analytics.category_structure(c.session, flt)["rows"]
    return mean(sum(r["suppliers"] for r in rows), len(rows), Decimal(1), {"categories": len(rows)})


def m01_queue_overdue(c: Ctx) -> Result:
    n = c.scalar("SELECT count(*) FROM pic.classification_review WHERE status IN ('OPEN', 'PENDING_SECOND') AND due_at < :know", know=clock.now())
    return count_of(n, {"definition": "steward-queue items past their SLA"})


def m01_maverick_overdue(c: Ctx) -> Result:
    n = c.scalar("SELECT count(*) FROM pic.maverick_hit WHERE status = 'OPEN' AND due_at < :know", know=clock.now())
    return count_of(n, {"definition": "open maverick hits past their SLA"})


def m01_quality_score(c: Ctx) -> Result:
    from app.pic.services import spend_quality
    report = spend_quality.assess(c.session)
    return Decimal(str(report["score"])), Decimal(str(report["score"])), Decimal(100), {"failing": report["failing"], "grade": report["grade"]}


def m01_spend_forecast_mape(c: Ctx) -> Result:
    from app.pic.services import spend_forecast
    a = spend_forecast.accuracy(c.session)
    # thin history: no number (a MAPE over a handful of points is not a measurement); the details say why and how much data there was
    return ((Decimal(str(a["mapePct"])) if a["mapePct"] is not None else None), None, Decimal(a["count"]),
            {"status": a["status"], "reason": a["reason"], "bandCoveragePct": a["bandCoveragePct"], "wapePct": a["wapePct"], "judged": a["count"],
             "series": a["seriesCount"], "months": a["monthsCount"], "minimumJudged": a["minimumJudged"], "minimumMonths": a["minimumMonths"]})


def m01_savings_pipeline(c: Ctx) -> Result:
    t = _savings_totals(c)
    open_ = max(0, t.get("NEGOTIATED", 0) - t.get("REALISED", 0))
    return Decimal(open_), Decimal(t.get("NEGOTIATED", 0)), Decimal(t.get("REALISED", 0)), {"definition": "negotiated savings not yet realised"}


def _savings_totals(c: Ctx) -> dict:
    rows = c.session.execute(text(
        "SELECT type, coalesce(sum(amount_minor), 0) FROM pic.savings_ledger_entry WHERE true" + c.when("posting_date") + " GROUP BY type"),
        c.params()).all()
    return {t: int(v) for t, v in rows}


def m01_realisation_rate(c: Ctx) -> Result:
    t = _savings_totals(c)
    return pct(t.get("REALISED", 0), t.get("NEGOTIATED", 0))


# ---------------------------------------------------------------- M02 demand planning & MRP
def m02_mape(c: Ctx) -> Result:
    lo, hi = c.periods()
    row = c.session.execute(text(
        "SELECT avg(abs(coalesce(override_qty, statistical_qty) - actual_qty) / actual_qty) * 100, count(*) FROM pic.forecast "
        "WHERE actual_qty > 0 AND period BETWEEN :lo AND :hi" + c.at_plant("plant")), c.params(lo=lo, hi=hi)).one()
    return (_d(row[0]).quantize(Decimal("0.1")) if row[0] is not None else None), None, _d(row[1]), {"forecasts": int(row[1])}


def m02_exception_backlog(c: Ctx) -> Result:
    return count_of(c.scalar("SELECT count(*) FROM pic.mrp_exception WHERE status = 'OPEN'" + c.at("created_at")))


def m02_conversion_lead(c: Ctx) -> Result:
    row = c.one("SELECT sum(greatest(0, extract(epoch FROM (r.created_at - po.created_at)))), count(*) FROM pic.planned_order po "
                "JOIN pic.requisition r ON r.id = po.requisition_id WHERE po.status = 'CONVERTED'" + c.when("r.created_at")
                + c.at_plant("po.plant"))
    return mean(row[0], row[1], Decimal(DAY))


def m02_stockouts(c: Ctx) -> Result:
    n = c.scalar("SELECT count(*) FROM (SELECT m.id FROM pic.material m LEFT JOIN pic.stock s ON s.material_id = m.id "
                 "AND s.stock_type IN ('UNRESTRICTED', 'CONSIGNMENT')" + c.at_plant("s.plant") + " WHERE m.status <> 'BLOCKED' AND m.type = 'STOCK' GROUP BY m.id "
                 "HAVING coalesce(sum(s.qty), 0) <= 0 AND EXISTS (SELECT 1 FROM pic.demand_element d WHERE d.material_id = m.id AND d.qty > 0"
                 + c.at_plant("d.plant") + ")) x")
    return count_of(n, {"definition": "stock materials with demand and no available (unrestricted or consignment) stock"})


def m02_days_of_cover(c: Ctx) -> Result:
    row = c.one("SELECT coalesce(sum(s.qty * coalesce(m.standard_price_minor, 0)), 0), coalesce(sum(m.annual_demand * coalesce(m.standard_price_minor, 0)), 0) / 365 "
                "FROM pic.stock s JOIN pic.material m ON m.id = s.material_id WHERE s.stock_type = 'UNRESTRICTED'" + c.at_plant("s.plant"))
    inventory, daily = _d(row[0]), _d(row[1])
    return ((inventory / daily).quantize(Decimal("0.1")) if daily else None), inventory, daily, {}


# ---------------------------------------------------------------- M03 master data governance
def m03_request_cycle(c: Ctx) -> Result:
    row = c.one("SELECT sum(extract(epoch FROM (m.created_at - r.created_at))), count(*) FROM pic.material_request r "
                "JOIN pic.material m ON m.id = r.material_id WHERE true" + c.when("m.created_at"))
    return mean(row[0], row[1], Decimal(DAY))


def m03_duplicate_rate(c: Ctx) -> Result:
    row = c.one("SELECT count(*) FILTER (WHERE status IN ('DUPLICATE_BLOCKED', 'MERGED') OR merged_into_material_id IS NOT NULL), count(*) "
                "FROM pic.material_request WHERE true" + c.when("created_at"))
    return pct(row[0], row[1])


def m03_first_time_right(c: Ctx) -> Result:
    row = c.one("SELECT count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM pic.task t WHERE t.object_type = 'MATERIAL_REQUEST' AND t.object_id = r.id "
                "AND t.decision IN ('RETURN', 'REJECT'))), count(*) FROM pic.material_request r WHERE r.status NOT IN ('DRAFT')" + c.when("r.created_at"))
    return pct(row[0], row[1])


def m03_bank_fraud_blocked(c: Ctx) -> Result:
    return count_of(c.scalar("SELECT count(*) FROM pic.bank_change_request WHERE status = 'REJECTED'" + c.when("created_at")),
                    {"definition": "supplier bank-change requests rejected at callback verification or approval"})


# ---------------------------------------------------------------- M04 requisitioning
def m04_catalogue_channel(c: Ctx) -> Result:
    row = c.one("SELECT count(*) FILTER (WHERE l.item_type = 'CATALOGUE' OR l.catalogue_item_id IS NOT NULL OR l.contract_line_id IS NOT NULL), count(*) "
                "FROM pic.pr_line l JOIN pic.requisition r ON r.id = l.requisition_id WHERE r.status <> 'DRAFT'" + c.when("r.created_at")
                + c.at_plant("l.plant"))
    return pct(row[0], row[1])


def m04_approval_cycle(c: Ctx) -> Result:
    row = c.one("SELECT sum(extract(epoch FROM (approved_at - submitted_at))), count(*) FROM pic.requisition WHERE approved_at IS NOT NULL "
                "AND submitted_at IS NOT NULL" + c.when("approved_at") + c.at_plant("plant"))
    return mean(row[0], row[1], Decimal(HOUR))


def m04_free_text(c: Ctx) -> Result:
    row = c.one("SELECT count(*) FILTER (WHERE l.item_type = 'FREE_TEXT'), count(*) FROM pic.pr_line l JOIN pic.requisition r ON r.id = l.requisition_id "
                "WHERE r.status <> 'DRAFT'" + c.when("r.created_at") + c.at_plant("l.plant"))
    return pct(row[0], row[1])


def m04_budget_blocked(c: Ctx) -> Result:
    n = c.scalar("SELECT count(*) FROM pic.requisition WHERE (budget_result->>'outcome' IN ('HARD_STOP', 'BLOCKED', 'EXCEEDED') "
                 "OR budget_result->'categoryBudget'->>'outcome' IN ('HARD_STOP', 'BLOCKED', 'EXCEEDED'))" + c.when("created_at") + c.at_plant("plant"))
    return count_of(n, {"definition": "requisitions stopped or held by a budget check"})


# ---------------------------------------------------------------- M05 sourcing
def m05_cycle(c: Ctx) -> Result:
    row = c.one("SELECT sum(extract(epoch FROM (d.created_at - e.published_at))), count(*) FROM pic.sourcing_event e "
                "JOIN LATERAL (SELECT min(created_at) AS created_at FROM pic.award_decision WHERE event_id = e.id AND status = 'APPROVED') d ON true "
                "WHERE e.published_at IS NOT NULL AND d.created_at IS NOT NULL" + c.when("d.created_at"))
    return mean(row[0], row[1], Decimal(DAY))


def m05_competitive(c: Ctx) -> Result:
    row = c.one("SELECT count(*) FILTER (WHERE bidders >= 2), count(*) FROM (SELECT e.id, (SELECT count(DISTINCT b.supplier_id) FROM pic.bid b "
                "WHERE b.event_id = e.id) AS bidders FROM pic.sourcing_event e WHERE e.status IN ('AWARDED', 'CLOSED', 'CONTRACTED', 'COMPLETED')"
                + c.when("e.published_at") + ") x")
    return pct(row[0], row[1])


def m05_negotiated_pct(c: Ctx) -> Result:
    t = _savings_totals(c)
    base = c.scalar("SELECT coalesce(sum(baseline_price_minor * annual_volume), 0) FROM pic.savings_initiative WHERE stage <> 'LOST' AND annual_volume IS NOT NULL"
                    + c.when("created_at"))
    return pct(t.get("NEGOTIATED", 0), base)


def m05_bidders(c: Ctx) -> Result:
    row = c.one("SELECT sum(bidders), count(*) FROM (SELECT (SELECT count(DISTINCT b.supplier_id) FROM pic.bid b WHERE b.event_id = e.id) AS bidders "
                "FROM pic.sourcing_event e WHERE e.published_at IS NOT NULL" + c.when("e.published_at") + ") x WHERE bidders > 0")
    return mean(row[0], row[1])


# ---------------------------------------------------------------- M06 supplier lifecycle
def m06_onboarding_cycle(c: Ctx) -> Result:
    row = c.one("SELECT sum(extract(epoch FROM (q.created_at - s.created_at))), count(*) FROM pic.supplier s JOIN LATERAL (SELECT min(created_at) AS created_at "
                "FROM pic.qualification WHERE supplier_id = s.id AND decision IN ('QUALIFIED', 'CONDITIONAL')) q ON q.created_at IS NOT NULL WHERE true"
                + c.when("q.created_at"))
    return mean(row[0], row[1], Decimal(DAY))


def m06_qualified_coverage(c: Ctx) -> Result:
    row = c.one("SELECT count(*) FILTER (WHERE status IN ('QUALIFIED', 'PREFERRED')), count(*) FROM pic.supplier_category_status WHERE status <> 'EXITED'")
    return pct(row[0], row[1])


def m06_otif(c: Ctx) -> Result:
    row = c.one("SELECT sum(on_time_in_full), sum(receipts) FROM pic.scorecard WHERE true" + c.when("to_date(period, 'YYYY-MM')"))
    return pct(row[0], row[1])


def m06_ppm(c: Ctx) -> Result:
    row = c.one("SELECT sum(qty_rejected), sum(qty_received) FROM pic.scorecard WHERE true" + c.when("to_date(period, 'YYYY-MM')"))
    if not row[1]:
        return None, None, None, {}
    return (_d(row[0]) * 1_000_000 / _d(row[1])).quantize(Decimal("1")), _d(row[0]), _d(row[1]), {}


def m06_high_risk(c: Ctx) -> Result:
    row = c.one("SELECT count(*) FILTER (WHERE risk_tier = 'HIGH'), count(*) FROM pic.supplier WHERE status NOT IN ('BLOCKED', 'MERGED', 'REGISTERED', 'REJECTED', 'EXITED')")
    return pct(row[0], row[1])


# ---------------------------------------------------------------- M07 contracts
def m07_cycle(c: Ctx) -> Result:
    row = c.one("SELECT sum(extract(epoch FROM (activated_at - created_at))), count(*) FROM pic.contract WHERE activated_at IS NOT NULL" + c.when("activated_at"))
    return mean(row[0], row[1], Decimal(DAY))


def m07_leakage(c: Ctx) -> Result:
    n = c.scalar("SELECT coalesce(sum(amount_minor), 0) FROM pic.maverick_hit WHERE rule_code IN ('OFF_CONTRACT', 'OFF_CONTRACT_PRICE') "
                 "AND status <> 'DISPOSED'" + c.when("created_at"))
    return Decimal(int(n or 0)), Decimal(int(n or 0)), None, {"definition": "value of open off-contract and off-contract-price hits"}


def m07_expiring(c: Ctx) -> Result:
    on = clock.today() if not c.period else min(c.end, clock.today())
    n = c.session.execute(text("SELECT count(*) FROM pic.contract WHERE status IN ('ACTIVE', 'EXPIRING') AND valid_to >= :d AND valid_to <= :d90"),
                          {"d": on, "d90": on + timedelta(days=90)}).scalar()
    return count_of(n)


def m07_obligations(c: Ctx) -> Result:
    # on time = completed on or before the due date in IST (UTC+05:30, a fixed offset: no tz database needed). A completion without a timestamp predates completion tracking: it counts as met.
    row = c.one("SELECT count(*) FILTER (WHERE status IN ('DONE', 'COMPLETED', 'FULFILLED', 'MET') "
                "AND (completed_at IS NULL OR ((completed_at AT TIME ZONE 'UTC') + interval '5 hours 30 minutes')::date <= due_date)), "
                "count(*) FILTER (WHERE status IN ('DONE', 'COMPLETED', 'FULFILLED', 'MET') OR due_date < :today) FROM pic.obligation WHERE true"
                + c.when("due_date"), today=clock.today())
    return pct(row[0], row[1], {"definition": "obligations completed on or before the due date / obligations due (completed, or open past the due date)"})


# ---------------------------------------------------------------- M08 purchase orders
def m08_touchless(c: Ctx) -> Result:
    row = c.one("SELECT count(*) FILTER (WHERE touchless), count(*) FROM pic.purchase_order WHERE released_at IS NOT NULL" + c.when("released_at")
                + c.at_plant("plant"))
    return pct(row[0], row[1])


def m08_cycle(c: Ctx) -> Result:
    row = c.one("SELECT sum(extract(epoch FROM (released_at - created_at))), count(*) FROM pic.purchase_order WHERE released_at IS NOT NULL" + c.when("released_at")
                + c.at_plant("plant"))
    return mean(row[0], row[1], Decimal(HOUR))


def m08_confirmation_sla(c: Ctx) -> Result:
    row = c.one("SELECT count(*) FILTER (WHERE pc.created_at <= po.confirmation_due_at), count(*) FROM pic.po_confirmation pc "
                "JOIN pic.purchase_order po ON po.id = pc.po_id WHERE pc.status = 'CONFIRMED' AND po.confirmation_due_at IS NOT NULL" + c.when("pc.created_at")
                + c.at_plant("po.plant"))
    return pct(row[0], row[1])


def m08_change_rate(c: Ctx) -> Result:
    row = c.one("SELECT count(*) FILTER (WHERE version > 1), count(*) FROM pic.purchase_order WHERE released_at IS NOT NULL" + c.when("released_at")
                + c.at_plant("plant"))
    return pct(row[0], row[1])


# ---------------------------------------------------------------- M09 receipt & service entry
def m09_receipt_accuracy(c: Ctx) -> Result:
    row = c.one("SELECT count(*) FILTER (WHERE l.received_qty <= l.qty * (1 + coalesce((po.tolerance->>'over_pct')::numeric, 2) / 100) "
                "AND l.received_qty >= l.qty * (1 - coalesce((po.tolerance->>'under_pct')::numeric, 5) / 100)), count(*) FROM pic.po_line l "
                "JOIN pic.purchase_order po ON po.id = l.po_id WHERE l.received_qty > 0 AND po.status IN ('RECEIVED', 'INVOICED', 'CLOSED')"
                + c.when("po.created_at") + c.at_plant("l.plant"))
    return pct(row[0], row[1], {"definition": "fully received PO lines whose received quantity is inside the PO tolerance"})


def m09_dock_to_stock(c: Ctx) -> Result:
    row = c.one("SELECT sum(extract(epoch FROM (updated_at - created_at))), count(*) FROM pic.inspection_lot WHERE usage_decision IS NOT NULL "
                "AND updated_at IS NOT NULL" + c.when("updated_at"))
    return mean(row[0], row[1], Decimal(HOUR))


def m09_ses_approval(c: Ctx) -> Result:
    row = c.one("SELECT sum(extract(epoch FROM (completed_at - created_at))), count(*) FROM pic.task WHERE object_type = 'SERVICE_ENTRY' "
                "AND decision = 'APPROVE' AND completed_at IS NOT NULL" + c.when("completed_at"))
    return mean(row[0], row[1], Decimal(HOUR))


def m09_quality_rejection(c: Ctx) -> Result:
    row = c.one("SELECT sum(l.rejected_qty), sum(l.qty) FROM pic.gr_line l JOIN pic.goods_receipt g ON g.id = l.gr_id WHERE g.reversal_of IS NULL"
                + c.when("g.posting_date"))
    return pct(row[0], row[1])


def m09_inventory_turns(c: Ctx) -> Result:
    """Value issued (movements 201 / 201K at the standard price) annualised, over the average own stock value of the window (opening and closing
    value at the standard price; the opening is the closing less the window's net movement of own stock)."""
    end = c.end or (clock.today() + timedelta(days=1))
    start = c.start or (end - timedelta(days=365))
    days = max((end - start).days, 1)
    row = c.one("SELECT coalesce(sum(-m.qty * coalesce(mat.standard_price_minor, 0)) FILTER (WHERE m.movement_type IN ('201', '201K')), 0), "
                "coalesce(sum(m.qty * coalesce(mat.standard_price_minor, 0)) FILTER (WHERE m.stock_type IN ('UNRESTRICTED', 'QUALITY', 'BLOCKED')), 0) "
                "FROM pic.stock_movement m JOIN pic.material mat ON mat.id = m.material_id WHERE m.created_at >= :wfrom AND m.created_at < :wto"
                + c.at_plant("m.plant"), wfrom=start, wto=end)
    closing = _d(c.scalar("SELECT coalesce(sum(s.qty * coalesce(mat.standard_price_minor, 0)), 0) FROM pic.stock s JOIN pic.material mat ON mat.id = s.material_id "
                          "WHERE s.stock_type IN ('UNRESTRICTED', 'QUALITY', 'BLOCKED')" + c.at_plant("s.plant")))
    issues, net = _d(row[0]), _d(row[1])
    average = ((closing - net) + closing) / 2
    annual = issues * Decimal(365) / Decimal(days)
    detail = {"windowDays": days, "issuesMinor": int(issues), "annualisedIssuesMinor": int(annual), "averageStockValueMinor": int(average)}
    return ((annual / average).quantize(Decimal("0.1"), ROUND_HALF_UP) if average > 0 else None), annual, average, detail


def m09_count_accuracy(c: Ctx) -> Result:
    row = c.one("SELECT count(*) FILTER (WHERE l.first_count_ok), count(*) FROM pic.physical_inventory_line l JOIN pic.physical_inventory i ON i.id = l.inventory_id "
                "WHERE i.status = 'POSTED' AND l.first_count_ok IS NOT NULL" + c.when("i.posted_at") + c.at_plant("i.plant"))
    return pct(row[0], row[1], {"definition": "counted lines whose first count was inside the count tolerance (rule INVENTORY-COUNT) / counted lines of posted counts"})


def m09_adjustment_value(c: Ctx) -> Result:
    row = c.one("SELECT coalesce(sum(abs(coalesce(m.value_minor, m.qty * coalesce(mat.standard_price_minor, 0)))), 0), count(*) "
                "FROM pic.stock_movement m JOIN pic.material mat ON mat.id = m.material_id WHERE m.movement_type IN ('701', '702', '551')"
                + c.when("m.created_at") + c.at_plant("m.plant"))
    return _d(row[0]), _d(row[0]), None, {"movements": int(row[1]), "definition": "inventory differences (701 / 702) and scrapping (551), absolute value"}


# ---------------------------------------------------------------- M10 invoices
def m10_first_pass(c: Ctx) -> Result:
    row = c.one("SELECT count(*) FILTER (WHERE first_pass_matched), count(*) FROM pic.invoice WHERE first_pass_matched IS NOT NULL" + c.when("invoice_date"))
    return pct(row[0], row[1])


def m10_exception_cycle(c: Ctx) -> Result:
    row = c.one("SELECT sum(extract(epoch FROM (updated_at - created_at))), count(*) FROM pic.invoice_exception WHERE status = 'RESOLVED' AND updated_at IS NOT NULL"
                + c.when("updated_at"))
    return mean(row[0], row[1], Decimal(HOUR))


def m10_duplicates(c: Ctx) -> Result:
    """Duplicates held for review that were not released as "not a duplicate", plus duplicates refused outright at capture (same supplier invoice number
    or IRN: the request is rejected, the audit event DUPLICATE_BLOCKED is the evidence)."""
    held = c.scalar("SELECT count(*) FROM pic.invoice_exception WHERE type = 'DUPLICATE' AND coalesce(resolution, '') <> 'NOT_DUPLICATE'" + c.when("created_at"))
    refused = c.scalar("SELECT count(*) FROM pic.audit_event WHERE action = 'DUPLICATE_BLOCKED'" + c.when("ts"))
    return count_of((held or 0) + (refused or 0), {"held": held or 0, "refusedAtCapture": refused or 0})


def _payables(c: Ctx) -> dict:
    from app.pic.platform import batch
    from app.pic.services import payables
    # three KPIs read the same payables insight: computed once per request (kpi.read opens the batch)
    return batch.memo(c.session, ("payables-insights", c.period, c.plant), lambda: payables.insights(c.session))


def m10_discount(c: Ctx) -> Result:
    data = _payables(c)
    return pct(data["discountCapturedMinor"], data["discountAvailableMinor"]) if data["discountAvailableMinor"] else (None, None, None, {"note": data.get("discountNote")})


def m10_dpo(c: Ctx) -> Result:
    # weighted by the amount in the company-code currency (a foreign-currency payment counts at the invoice's exchange rate), like payables.insights
    row = c.one("SELECT sum(extract(epoch FROM (p.value_date::timestamp - i.invoice_date::timestamp)) / 86400 * p.amount_minor * coalesce(i.fx_rate, 1)), "
                "sum(p.amount_minor * coalesce(i.fx_rate, 1)) FROM pic.payment p JOIN pic.invoice i ON i.id = p.invoice_id WHERE p.status = 'COMPLETED'"
                + c.when("p.value_date"))
    return mean(row[0], row[1])


def m10_touchless(c: Ctx) -> Result:
    row = c.one("SELECT count(*) FILTER (WHERE i.first_pass_matched AND NOT EXISTS (SELECT 1 FROM pic.credit_note n WHERE n.invoice_id = i.id) "
                "AND NOT EXISTS (SELECT 1 FROM pic.debit_note d WHERE d.invoice_id = i.id) "
                "AND NOT EXISTS (SELECT 1 FROM pic.invoice_exception e WHERE e.invoice_id = i.id)), count(*) "
                "FROM pic.invoice i WHERE i.status IN ('POSTED', 'PAID') AND coalesce(i.channel, '') NOT IN ('RETENTION', 'ERS', 'ADVANCE')" + c.when("i.invoice_date"))
    return pct(row[0], row[1], {"definition": "matched first time with no exception, credit note or debit note, over invoices posted or paid (approval stays a human four-eyes step)"})


def m10_msme_on_time(c: Ctx) -> Result:
    data = _payables(c)["msme"]
    return pct(data["paidInvoices"] - data["paidLate"], data["paidInvoices"], {"overdueUnpaid": data["overdueInvoices"]})


def m10_exception_ageing(c: Ctx) -> Result:
    ageing = _payables(c)["exceptionAgeing"]
    return count_of(ageing["8-30"] + ageing["30+"], {"buckets": ageing})


# ---------------------------------------------------------------- M11 savings
def m11_negotiated(c: Ctx) -> Result:
    value = _savings_totals(c).get("NEGOTIATED", 0)
    return Decimal(value), Decimal(value), None, {}


def m11_realised(c: Ctx) -> Result:
    value = _savings_totals(c).get("REALISED", 0)
    return Decimal(value), Decimal(value), None, {}


def m11_leakage(c: Ctx) -> Result:
    from app.pic.models import SavingsInitiative
    from app.pic.services import savings
    total = 0
    for initiative in c.session.execute(select(SavingsInitiative).where(SavingsInitiative.material_id.is_not(None),
                                                                        SavingsInitiative.stage.in_(("NEGOTIATED", "CONTRACTED", "REALISING", "VALIDATED")))).scalars():
        total += sum(max(0, item["amountMinor"]) for item in savings.waterfall(c.session, initiative)["leakage"])
    return Decimal(total), Decimal(total), None, {"definition": "invoiced above the agreed price, or from a supplier outside the award"}


# ---------------------------------------------------------------- M12 agents
def m12_agent_assisted(c: Ctx) -> Result:
    executed = c.scalar("SELECT count(*) FROM pic.agent_run WHERE action_taken = 'EXECUTED'" + c.when("created_at"))
    human = c.scalar("SELECT count(*) FROM pic.task WHERE status = 'COMPLETED'" + c.when("completed_at"))
    return pct(executed, (executed or 0) + (human or 0), {"definition": "decisions taken by agents inside their autonomy limit / all decisions"})


def m12_acceptance(c: Ctx) -> Result:
    row = c.one("SELECT count(*) FILTER (WHERE status = 'ACCEPTED'), count(*) FROM pic.recommendation WHERE status IN ('ACCEPTED', 'REJECTED')" + c.when("decided_at"))
    return pct(row[0], row[1])


def m12_prediction_accuracy(c: Ctx) -> Result:
    mape = m02_mape(c)
    if mape[0] is None:
        return None, None, None, {"basis": "1 − forecast MAPE"}
    return max(Decimal(0), Decimal(100) - mape[0]), None, mape[2], {"basis": "1 − forecast MAPE"}


def m12_hours_saved(c: Ctx) -> Result:
    try:
        minutes = Decimal(str(rules.resolve(c.session, "KPI-THRESHOLDS").body.get("minutesSavedPerAgentRun", MINUTES_SAVED_PER_AGENT_RUN)))
    except Problem:
        minutes = MINUTES_SAVED_PER_AGENT_RUN
    runs = c.scalar("SELECT count(*) FROM pic.agent_run WHERE action_taken = 'EXECUTED'" + c.when("created_at"))
    return (Decimal(runs or 0) * minutes / 60).quantize(Decimal("0.1")), Decimal(runs or 0), minutes, {"assumption": f"{minutes} minutes per executed agent run (rule KPI-THRESHOLDS)"}


# ---------------------------------------------------------------- M13 platform
def m13_integration_success(c: Ctx) -> Result:
    row = c.one("SELECT count(*) FILTER (WHERE status = 'POSTED'), count(*) FROM pic.integration_message WHERE true" + c.when("created_at"))
    return pct(row[0], row[1])


def m13_mttr(c: Ctx) -> Result:
    row = c.one("SELECT sum(extract(epoch FROM (posted_at - created_at))), count(*) FROM pic.integration_message WHERE status = 'POSTED' AND attempts > 1 "
                "AND posted_at IS NOT NULL" + c.when("posted_at"))
    return mean(row[0], row[1], Decimal(HOUR))


def m13_sod_open(c: Ctx) -> Result:
    return count_of(c.scalar("SELECT count(*) FROM pic.sod_violation WHERE outcome IN ('BLOCKED', 'MITIGATION_REQUIRED')" + c.when("created_at")))


# ---------------------------------------------------------------- industry-template KPIs
def t_ppv(c: Ctx) -> Result:
    lo, hi = c.periods()
    row = c.session.execute(text(
        "SELECT coalesce(sum(price_variance_group_minor), 0), coalesce(sum(amount_group_minor), 0) FROM pic.spend_cube_summary "
        "WHERE period BETWEEN :lo AND :hi AND addressable"), {"lo": lo, "hi": hi}).one()
    return pct(row[0], row[1], {"definition": "price paid above the contract or standard price, as % of addressable spend"})


def t_rate_compliance(c: Ctx) -> Result:
    row = c.one("SELECT count(*) FILTER (WHERE NOT l.price_deviation), count(*) FROM pic.po_line l JOIN pic.purchase_order po ON po.id = l.po_id "
                "WHERE l.price_source IN ('CONTRACT', 'INFO_RECORD', 'CATALOGUE')" + c.when("po.created_at") + c.at_plant("l.plant"))
    return pct(row[0], row[1], {"definition": "PO lines priced at the agreed rate / PO lines with an agreed rate"})


def t_catalogue_adoption(c: Ctx) -> Result:
    row = c.one("SELECT count(*) FILTER (WHERE l.item_type = 'CATALOGUE' OR l.catalogue_item_id IS NOT NULL), count(*) FROM pic.pr_line l "
                "JOIN pic.requisition r ON r.id = l.requisition_id WHERE r.status <> 'DRAFT'" + c.when("r.created_at"))
    return pct(row[0], row[1])


def _define(code, module, name, unit, direction, formula, source, target=None, warn=None, compute=None, **kw):
    register(KpiDef(f"{module}.{code}" if module != "TEMPLATE" else f"TPL.{code}", module, name, unit, direction, formula, source, target, warn,
                    compute=compute, **kw))


H, L, I = "HIGHER_BETTER", "LOWER_BETTER", "INFO"
for _args, _kw in [
    (("SPEND_UNDER_MGMT", "M01", "Spend under management %", "PCT", H, "addressable spend on contract/catalogue or bought clean from a qualified supplier in a planned category / addressable spend", "spend_cube_summary, category_plan, supplier_category_status", 75, 60), {"compute": m01_under_management, "scopes": ("TENANT", "PLANT")}),
    (("CONTRACT_COVERAGE", "M01", "Contract coverage %", "PCT", H, "contracted addressable spend / addressable spend", "spend_cube_summary", 70, 55), {"compute": m01_contract_coverage, "scopes": ("TENANT", "PLANT")}),
    (("MAVERICK_PCT", "M01", "Maverick spend %", "PCT", L, "addressable spend with a maverick flag / addressable spend", "spend_cube_summary", 8, 12), {"compute": m01_maverick, "scopes": ("TENANT", "PLANT")}),
    (("CLASSIFICATION_ACCURACY", "M01", "Classification accuracy %", "PCT", H, "(auto-classified + steward-accepted) / (auto-classified + steward decisions)", "spend_cube_summary, classification_review", 90, 80), {"compute": m01_classification, "scopes": ("TENANT", "PLANT")}),
    (("SAVINGS_REALISATION_RATE", "M01", "Savings realisation rate %", "PCT", H, "realised savings / negotiated savings", "savings_ledger_entry", 70, 50), {"compute": m01_realisation_rate}),
    (("TAIL_SPEND_PCT", "M01", "Tail spend %", "PCT", L, "spend with class C parent suppliers (beyond 80% cumulative spend) / addressable spend", "spend_cube_summary", 8, 15), {"compute": m01_tail_spend, "scopes": ("TENANT", "PLANT")}),
    (("SUPPLIERS_PER_CATEGORY", "M01", "Suppliers per category", "RATIO", I, "parent suppliers with addressable spend / categories with addressable spend", "spend_cube_summary"), {"compute": m01_suppliers_per_category, "scopes": ("TENANT", "PLANT")}),
    (("SPEND_FORECAST_MAPE", "M01", "Spend forecast error (MAPE) %", "PCT", L, "mean |forecast issued - actual| / actual over issued forecasts of complete months", "spend_forecast_snapshot, spend_cube_summary", 12, 20), {"compute": m01_spend_forecast_mape, "point_in_time": True}),
    (("SAVINGS_PIPELINE", "M01", "Savings pipeline", "MINOR", I, "negotiated savings not yet realised", "savings_ledger_entry"), {"compute": m01_savings_pipeline}),
    (("QUEUE_OVERDUE", "M01", "Steward queue past SLA", "COUNT", L, "classification reviews open past their due date", "classification_review", 0, 25), {"compute": m01_queue_overdue, "point_in_time": True}),
    (("MAVERICK_OVERDUE", "M01", "Maverick hits past SLA", "COUNT", L, "open maverick hits past their due date", "maverick_hit", 0, 10), {"compute": m01_maverick_overdue, "point_in_time": True}),
    (("DATA_QUALITY_SCORE", "M01", "Spend data-quality score", "PCT", H, "100 minus the penalties of the spend-cube data-quality checks", "spend_line, spend_cube_summary", 90, 75), {"compute": m01_quality_score, "point_in_time": True}),
    (("FORECAST_MAPE", "M02", "Forecast accuracy (MAPE) %", "PCT", L, "mean |effective forecast − actual| / actual over closed forecast periods", "forecast", 20, 30), {"compute": m02_mape, "scopes": ("TENANT", "PLANT")}),
    (("EXCEPTION_BACKLOG", "M02", "Open MRP exceptions", "COUNT", L, "MRP exceptions with status OPEN", "mrp_exception", 20, 50), {"compute": m02_exception_backlog, "point_in_time": True}),
    (("PO_CONVERSION_LEAD", "M02", "Planned-order conversion lead time (days)", "DAYS", L, "mean time from planned order creation to the requisition it became", "planned_order, requisition", 3, 7), {"compute": m02_conversion_lead, "scopes": ("TENANT", "PLANT")}),
    (("STOCKOUTS", "M02", "Stock-out incidents", "COUNT", L, "stock materials with open demand and no available (unrestricted or consignment) stock", "material, stock, demand_element", 0, 3), {"compute": m02_stockouts, "scopes": ("TENANT", "PLANT"), "point_in_time": True}),
    (("DAYS_OF_COVER", "M02", "Inventory days of cover", "DAYS", L, "unrestricted stock value / (annual demand value / 365)", "stock, material", 45, 75), {"compute": m02_days_of_cover, "scopes": ("TENANT", "PLANT"), "point_in_time": True}),
    (("REQUEST_CYCLE", "M03", "Material request cycle time (days)", "DAYS", L, "mean time from material request to the created material", "material_request, material", 3, 5), {"compute": m03_request_cycle}),
    (("DUPLICATE_RATE", "M03", "Duplicate rate %", "PCT", L, "requests blocked as duplicates or merged / requests", "material_request", 5, 10), {"compute": m03_duplicate_rate}),
    (("FIRST_TIME_RIGHT", "M03", "First-time-right %", "PCT", H, "requests never returned or rejected by a steward / submitted requests", "material_request, task", 90, 75), {"compute": m03_first_time_right}),
    (("BANK_FRAUD_BLOCKED", "M03", "Bank-change fraud attempts blocked", "COUNT", I, "supplier bank-change requests rejected at callback or approval", "bank_change_request"), {"compute": m03_bank_fraud_blocked}),
    (("CATALOGUE_CHANNEL", "M04", "Catalogue / contract channel %", "PCT", H, "requisition lines from a catalogue or contract / lines", "pr_line", 60, 40), {"compute": m04_catalogue_channel, "scopes": ("TENANT", "PLANT")}),
    (("APPROVAL_CYCLE", "M04", "PR approval cycle time (hours)", "HOURS", L, "mean time from submit to final approval", "requisition", 24, 48), {"compute": m04_approval_cycle, "scopes": ("TENANT", "PLANT")}),
    (("FREE_TEXT_PCT", "M04", "Free-text %", "PCT", L, "free-text requisition lines / lines", "pr_line", 15, 25), {"compute": m04_free_text, "scopes": ("TENANT", "PLANT")}),
    (("BUDGET_BLOCKED", "M04", "Budget-blocked PRs", "COUNT", L, "requisitions held or stopped by a budget check", "requisition", 0, 5), {"compute": m04_budget_blocked, "scopes": ("TENANT", "PLANT")}),
    (("SOURCING_CYCLE", "M05", "Sourcing cycle time (days)", "DAYS", L, "mean time from publication to an approved award", "sourcing_event, award_decision", 30, 45), {"compute": m05_cycle}),
    (("COMPETITIVE_EVENTS", "M05", "Competitive events %", "PCT", H, "awarded events with two or more bidders / awarded events", "sourcing_event, bid", 80, 60), {"compute": m05_competitive}),
    (("NEGOTIATED_SAVINGS_PCT", "M05", "Negotiated savings %", "PCT", H, "negotiated savings / (baseline price × annual volume)", "savings_ledger_entry, savings_initiative", 5, 2), {"compute": m05_negotiated_pct}),
    (("BIDDERS_PER_EVENT", "M05", "Bidders per event", "RATIO", H, "distinct bidders / events that received bids", "bid", 3, 2), {"compute": m05_bidders}),
    (("ONBOARDING_CYCLE", "M06", "Onboarding cycle time (days)", "DAYS", L, "mean time from registration to the first qualification decision", "supplier, qualification", 30, 60), {"compute": m06_onboarding_cycle}),
    (("QUALIFIED_COVERAGE", "M06", "Qualified supplier coverage %", "PCT", H, "qualified or preferred supplier-category pairs / pairs not exited", "supplier_category_status", 90, 75), {"compute": m06_qualified_coverage, "point_in_time": True}),
    (("SUPPLIER_OTIF", "M06", "Supplier OTIF %", "PCT", H, "receipts on time and in full / receipts", "scorecard", 95, 90), {"compute": m06_otif}),
    (("SUPPLIER_PPM", "M06", "Supplier PPM", "PPM", L, "rejected quantity / received quantity × 1,000,000", "scorecard", 1000, 2500), {"compute": m06_ppm}),
    (("HIGH_RISK_SUPPLIERS", "M06", "High-risk suppliers %", "PCT", L, "active suppliers with risk tier HIGH / active suppliers", "supplier", 10, 20), {"compute": m06_high_risk, "point_in_time": True}),
    (("CONTRACT_CYCLE", "M07", "Contract cycle time (days)", "DAYS", L, "mean time from contract draft to activation", "contract", 21, 45), {"compute": m07_cycle}),
    (("CONTRACT_LEAKAGE", "M07", "Contract leakage (minor units)", "MINOR", L, "value of open off-contract and off-contract-price hits", "maverick_hit"), {"compute": m07_leakage}),
    (("EXPIRING_90D", "M07", "Contracts expiring in 90 days", "COUNT", L, "active contracts with valid-to within 90 days", "contract", 5, 15), {"compute": m07_expiring, "point_in_time": True}),
    (("OBLIGATION_ON_TIME", "M07", "Obligation on-time %", "PCT", H, "obligations met / obligations due", "obligation", 95, 85), {"compute": m07_obligations}),
    (("TOUCHLESS_PO", "M08", "Touchless PO %", "PCT", H, "POs released without human touch / POs released", "purchase_order", 40, 25), {"compute": m08_touchless, "scopes": ("TENANT", "PLANT")}),
    (("PO_CYCLE", "M08", "PO cycle time (hours)", "HOURS", L, "mean time from PO creation to release", "purchase_order", 24, 72), {"compute": m08_cycle, "scopes": ("TENANT", "PLANT")}),
    (("CONFIRMATION_SLA", "M08", "Confirmation rate within SLA %", "PCT", H, "confirmations received before the due time / confirmations", "po_confirmation, purchase_order", 90, 75), {"compute": m08_confirmation_sla, "scopes": ("TENANT", "PLANT")}),
    (("PO_CHANGE_RATE", "M08", "PO change rate %", "PCT", L, "released POs with more than one version / released POs", "purchase_order", 10, 20), {"compute": m08_change_rate, "scopes": ("TENANT", "PLANT")}),
    (("RECEIPT_ACCURACY", "M09", "Receipt-to-PO accuracy %", "PCT", H, "received PO lines inside the PO tolerance / received PO lines", "po_line, purchase_order", 98, 95), {"compute": m09_receipt_accuracy, "scopes": ("TENANT", "PLANT")}),
    (("DOCK_TO_STOCK", "M09", "Dock-to-stock time (hours)", "HOURS", L, "mean time from goods receipt to the quality usage decision", "inspection_lot", 24, 48), {"compute": m09_dock_to_stock}),
    (("INVENTORY_TURNS", "M09", "Inventory turns", "RATIO", H, "value issued (201 / 201K, annualised) / average own stock value at standard price", "stock_movement, stock, material", 6, 3), {"compute": m09_inventory_turns, "scopes": ("TENANT", "PLANT")}),
    (("STOCK_COUNT_ACCURACY", "M09", "Stock count accuracy %", "PCT", H, "counted lines inside the count tolerance at the first count / counted lines of posted physical inventories", "physical_inventory_line, physical_inventory", 98, 95), {"compute": m09_count_accuracy, "scopes": ("TENANT", "PLANT")}),
    (("STOCK_ADJUSTMENT_VALUE", "M09", "Stock adjustment value (minor units)", "MINOR", L, "absolute value of inventory differences (701 / 702) and scrapping (551)", "stock_movement", None, None), {"compute": m09_adjustment_value, "scopes": ("TENANT", "PLANT")}),
    (("SES_APPROVAL", "M09", "SES approval time (hours)", "HOURS", L, "mean time to approve a service entry sheet", "task", 24, 72), {"compute": m09_ses_approval}),
    (("QUALITY_REJECTION", "M09", "Quality rejection rate %", "PCT", L, "rejected quantity / received quantity", "gr_line", 1, 3), {"compute": m09_quality_rejection}),
    (("FIRST_PASS_MATCH", "M10", "First-pass match %", "PCT", H, "invoices matched without an exception / invoices matched", "invoice", 85, 70), {"compute": m10_first_pass}),
    (("EXCEPTION_CYCLE", "M10", "Exception cycle time (hours)", "HOURS", L, "mean time to resolve an invoice exception", "invoice_exception", 48, 96), {"compute": m10_exception_cycle}),
    (("DUPLICATES_PREVENTED", "M10", "Duplicate invoices prevented", "COUNT", I, "invoices held as duplicates", "invoice_exception"), {"compute": m10_duplicates}),
    (("DISCOUNT_CAPTURE", "M10", "Discount capture %", "PCT", H, "early-payment discount captured / available", "payment, invoice, supplier", 80, 50), {"compute": m10_discount, "point_in_time": True}),
    (("DPO", "M10", "DPO (days)", "DAYS", H, "payment-weighted days from invoice date to payment", "payment, invoice", 45, 30), {"compute": m10_dpo}),
    (("TOUCHLESS_INVOICE", "M10", "Touchless invoice %", "PCT", H, "invoices matched first time with no exception, credit or debit note / invoices posted or paid", "invoice", 50, 30), {"compute": m10_touchless}),
    (("MSME_ON_TIME", "M10", "MSME payment compliance %", "PCT", H, "payments to MSME suppliers made by their due date (MSMED Act s.15) / completed MSME payments", "payment, invoice, supplier", 98, 90), {"compute": m10_msme_on_time, "point_in_time": True}),
    (("EXCEPTION_AGEING", "M10", "Open exceptions older than 7 days", "COUNT", L, "open invoice exceptions raised more than 7 days ago", "invoice_exception", 5, 20), {"compute": m10_exception_ageing, "point_in_time": True}),
    (("NEGOTIATED_SAVINGS", "M11", "Negotiated savings (minor units)", "MINOR", I, "sum of NEGOTIATED ledger entries", "savings_ledger_entry"), {"compute": m11_negotiated}),
    (("REALISED_SAVINGS", "M11", "Realised savings (minor units)", "MINOR", I, "sum of REALISED ledger entries", "savings_ledger_entry"), {"compute": m11_realised}),
    (("REALISATION_RATE", "M11", "Realisation rate %", "PCT", H, "realised / negotiated savings", "savings_ledger_entry", 70, 50), {"compute": m01_realisation_rate}),
    (("SAVINGS_LEAKAGE", "M11", "Savings leakage (minor units)", "MINOR", L, "invoiced above the agreed price or outside the award", "savings_initiative, po_line", 0, None), {"compute": m11_leakage, "point_in_time": True}),
    (("AGENT_ASSISTED", "M12", "Agent-assisted transactions %", "PCT", H, "agent-executed decisions / all decisions", "agent_run, task", 30, 15), {"compute": m12_agent_assisted}),
    (("RECOMMENDATION_ACCEPTANCE", "M12", "Recommendation acceptance %", "PCT", H, "accepted / decided recommendations", "recommendation", 70, 50), {"compute": m12_acceptance}),
    (("PREDICTION_ACCURACY", "M12", "Prediction accuracy %", "PCT", H, "100 − forecast MAPE", "forecast", 80, 70), {"compute": m12_prediction_accuracy}),
    (("HOURS_SAVED", "M12", "Hours saved", "HOURS", I, "executed agent runs × minutes per run (rule KPI-THRESHOLDS)", "agent_run"), {"compute": m12_hours_saved}),
    (("INTEGRATION_SUCCESS", "M13", "Integration success %", "PCT", H, "messages posted / messages", "integration_message", 98, 95), {"compute": m13_integration_success}),
    (("MTTR_INTEGRATION", "M13", "Mean time to resolve integration error (hours)", "HOURS", L, "mean time from first attempt to posting for messages that needed a retry", "integration_message", 4, 24), {"compute": m13_mttr}),
    (("SOD_OPEN", "M13", "SoD conflicts open", "COUNT", L, "recorded segregation-of-duties violations awaiting mitigation or blocked", "sod_violation", 0, 5), {"compute": m13_sod_open}),
    (("PPV", "TEMPLATE", "Purchase price variance (PPV) %", "PCT", L, "price paid above contract or standard price / addressable spend", "spend_cube_summary", 1, 3),
     {"compute": t_ppv, "templates": ("MANUFACTURING", "GENERAL", "HEALTHCARE", "LOGISTICS")}),
    (("RATE_COMPLIANCE", "TEMPLATE", "Rate compliance %", "PCT", H, "PO lines priced at the agreed rate / PO lines with an agreed rate", "po_line", 95, 85),
     {"compute": t_rate_compliance, "templates": ("LOGISTICS", "CONSTRUCTION", "IT_SERVICES"), "scopes": ("TENANT", "PLANT")}),
    (("CATALOGUE_ADOPTION", "TEMPLATE", "Catalogue adoption %", "PCT", H, "requisition lines from a catalogue / lines", "pr_line", 60, 40),
     {"compute": t_catalogue_adoption, "templates": ("HEALTHCARE", "GENERAL", "IT_SERVICES")}),
    (("COST_TO_COMPLETE", "TEMPLATE", "Cost to complete (minor units)", "MINOR", I, "WBS budget − (committed + paid) per project", "wbs budget, po_line", None, None),
     {"templates": ("CONSTRUCTION",), "needs": "WBS budget and progress data (construction pack); registered by the industry module"}),
    (("COST_PER_TONNE_KM", "TEMPLATE", "Cost per tonne-km (minor units)", "MINOR", L, "freight cost / (tonnes × km)", "freight invoices, consignments", None, None),
     {"templates": ("LOGISTICS",), "needs": "consignment tonnage and distance (logistics pack); registered by the industry module"}),
    (("EXPIRY_WRITE_OFFS", "TEMPLATE", "Expiry write-offs (minor units)", "MINOR", L, "value of stock written off after expiry", "stock, batch expiry", 0, None),
     {"templates": ("HEALTHCARE",), "needs": "batch expiry and write-off postings (healthcare pack); registered by the industry module"}),
]:
    _define(*_args, **_kw)


# ---------------------------------------------------------------- thresholds and status
def thresholds(session: Session, definition: KpiDef) -> tuple[Optional[float], Optional[float]]:
    target, warn = definition.target, definition.warn
    try:
        override = (rules.resolve(session, "KPI-THRESHOLDS").body.get("overrides") or {}).get(definition.code) or {}
    except Problem:
        override = {}
    return override.get("target", target), override.get("warn", warn)


def status_of(definition: KpiDef, value: Optional[Decimal], target: Optional[float], warn: Optional[float]) -> str:
    if value is None or definition.direction == "INFO" or target is None:
        return "NA"
    v, t = float(value), float(target)
    w = float(warn) if warn is not None else t
    if definition.direction == "HIGHER_BETTER":
        return "GOOD" if v >= t else "WARN" if v >= w else "BAD"
    return "GOOD" if v <= t else "WARN" if v <= w else "BAD"


# ---------------------------------------------------------------- evaluate / snapshot / read model
def definition_of(code: str) -> KpiDef:
    found = REGISTRY.get(code) or REGISTRY.get(code.upper())
    if found is None:
        raise Problem(404, "UNKNOWN_KPI", f"No KPI {code}; see GET /v1/kpis/registry")
    return found


def evaluate(session: Session, definition: KpiDef, period: Optional[str] = None, plant: Optional[str] = None) -> dict:
    if plant and "PLANT" not in definition.scopes:
        raise Problem(422, "SCOPE_NOT_SUPPORTED", f"{definition.code} is measured for the whole tenant, not per plant")
    target, warn = thresholds(session, definition)
    value = num = den = None
    detail: dict = {}
    if definition.compute is None:
        detail = {"needs": definition.needs or "no compute function registered"}
    else:
        savepoint = session.begin_nested()
        try:
            value, num, den, detail = definition.compute(Ctx(session, period, plant))
            savepoint.commit()
        except Exception as exc:  # one KPI never breaks the page: the failure is shown, the others still compute
            savepoint.rollback()
            detail = {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    return {"code": definition.code, "module": definition.module, "name": definition.name, "unit": definition.unit, "direction": definition.direction,
            "formula": definition.formula, "source": definition.source, "target": target, "warn": warn, "scopes": list(definition.scopes),
            "pointInTime": definition.point_in_time, "templates": list(definition.templates), "period": period, "plant": plant,
            "value": str(value) if value is not None else None, "numerator": str(num) if num is not None else None,
            "denominator": str(den) if den is not None else None, "status": status_of(definition, value, target, warn), "detail": detail}


def applicable(session: Session, module: Optional[str] = None, template: Optional[str] = None, include_other_templates: bool = False) -> list[KpiDef]:
    from app.pic.models import Tenant
    tenant = session.get(Tenant, current_tenant(session))
    own = (template or (tenant.industry_template if tenant else "") or "").upper()
    out = []
    for definition in REGISTRY.values():
        if module and definition.module != module.upper():
            continue
        if definition.templates and not include_other_templates and own and own not in definition.templates:
            continue
        out.append(definition)
    return sorted(out, key=lambda d: (d.module == "TEMPLATE", d.module, d.code))


def history(session: Session, code: str, limit: int = 12) -> list[dict]:
    rows = session.execute(select(KpiSnapshot).where(KpiSnapshot.kpi_code == code, KpiSnapshot.scope_key == "")
                           .order_by(KpiSnapshot.period.desc()).limit(limit)).scalars().all()
    return [{"period": r.period, "value": str(r.value) if r.value is not None else None, "status": r.status, "computedAt": r.computed_at.isoformat()}
            for r in reversed(rows)]


def read(session: Session, module: Optional[str] = None, period: Optional[str] = None, plant: Optional[str] = None,
         with_trend: bool = True, include_other_templates: bool = False) -> list[dict]:
    if period and not (len(period) == 7 and period[4] == "-" and period[:4].isdigit() and period[5:].isdigit() and 1 <= int(period[5:]) <= 12):
        raise Problem(422, "INVALID_PERIOD", "period must be YYYY-MM")
    from app.pic.platform import batch
    out = []
    with batch.reading(session):
        for definition in applicable(session, module, None, include_other_templates):
            if plant and "PLANT" not in definition.scopes:
                continue
            item = evaluate(session, definition, period, plant)
            if with_trend:
                item["trend"] = history(session, definition.code, 6)
            out.append(item)
    return out


def snapshot_kpis(tenant_id: uuid.UUID, period: Optional[str] = None, *, session: Optional[Session] = None) -> dict:
    """Persist this month's value of every KPI (idempotent: a rerun in the same month refreshes the values). The scheduler runs it
    at month end; ``period`` defaults to the month of today. Opens its own tenant transaction unless a session is passed."""
    def run(s: Session) -> dict:
        month = period or clock.today().strftime("%Y-%m")
        now, stored, na = clock.now(), 0, 0
        for definition in applicable(s, include_other_templates=False):
            item = evaluate(s, definition, month)
            if item["value"] is None:
                na += 1
            values = dict(value=_d(item["value"]), numerator=_d(item["numerator"]), denominator=_d(item["denominator"]), unit=definition.unit,
                          status=item["status"], computed_at=now, detail=item["detail"])
            existing = s.execute(select(KpiSnapshot).where(KpiSnapshot.kpi_code == definition.code, KpiSnapshot.period == month,
                                                           KpiSnapshot.scope_key == "")).scalar_one_or_none()
            if existing is None:
                s.add(KpiSnapshot(tenant_id=current_tenant(s), kpi_code=definition.code, period=month, scope_key="", **values))
            else:
                for key, value in values.items():
                    setattr(existing, key, value)
            stored += 1
        s.flush()
        audit.record(s, "KPI", current_tenant(s), "SNAPSHOT", object_ref=month, after={"period": month, "kpis": stored, "withoutValue": na})
        return {"period": month, "kpis": stored, "withoutValue": na}
    if session is not None:
        return run(session)
    with tenant_tx(tenant_id) as s:
        return run(s)
