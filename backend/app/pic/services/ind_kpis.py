"""Industry-template KPIs (BP IND-KPI): the three KPIs the KPI registry (services/kpi.py) leaves to the industry modules —
cost to complete (construction), cost per tonne-km (logistics), expiry write-offs (healthcare) — registered with their compute
functions, and the drill-downs behind PPV, rate compliance and catalogue adoption (whose headline values the registry computes).

``GET /v1/industry/kpis`` returns the template's KPIs with value, status and drill-down; a KPI with nothing to measure reports
``value: null`` and never a made-up number."""
from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.pic.models import Tenant
from app.pic.db import current_tenant
from app.pic.services import kpi

CODES = ("TPL.PPV", "TPL.COST_TO_COMPLETE", "TPL.RATE_COMPLIANCE", "TPL.COST_PER_TONNE_KM", "TPL.EXPIRY_WRITE_OFFS", "TPL.CATALOGUE_ADOPTION")


# ---------------------------------------------------------------- compute functions (registered in the KPI registry)
def cost_to_complete(c: "kpi.Ctx") -> tuple:
    """Open commitments on WBS elements: value of placed orders not yet invoiced. The detail gives, per WBS element, the budget, the
    actual cost (invoiced), the forecast at completion (actual + open commitments) and the headroom left in the budget."""
    rows = c.session.execute(text(
        "SELECT cost_object_code, amount_minor, consumed_minor, committed_minor FROM pic.budget WHERE cost_object_type = 'WBS' "
        "ORDER BY cost_object_code")).all()
    if not rows:
        return None, None, None, {"note": "no WBS budgets"}
    items = [{"wbs": code, "budgetMinor": int(budget), "actualMinor": int(consumed), "openCommitmentMinor": int(committed),
              "forecastAtCompletionMinor": int(consumed) + int(committed), "headroomMinor": int(budget) - int(consumed) - int(committed)}
             for code, budget, consumed, committed in rows]
    total = sum(i["openCommitmentMinor"] for i in items)
    return Decimal(total), Decimal(total), None, {"wbs": items, "overBudget": [i["wbs"] for i in items if i["headroomMinor"] < 0]}


def cost_per_tonne_km(c: "kpi.Ctx") -> tuple:
    """Approved trip service value ÷ (payload tonnes × km) over the trips recorded as freight movements; a service entry covering
    several movements is shared between them."""
    row = c.one(
        "WITH m AS (SELECT fm.distance_km, fm.payload_tonnes, se.total_minor, count(*) OVER (PARTITION BY fm.ses_id) AS n "
        "FROM pic.freight_movement fm JOIN pic.service_entry se ON se.id = fm.ses_id WHERE se.status = 'APPROVED'" + c.when("fm.moved_on") + ") "
        "SELECT coalesce(sum(total_minor::numeric / n), 0), coalesce(sum(distance_km * payload_tonnes), 0), count(*) FROM m")
    cost, tonne_km, trips = Decimal(row[0]), Decimal(row[1]), int(row[2])
    if not tonne_km:
        return None, cost, tonne_km, {"trips": trips}
    return (cost / tonne_km).quantize(Decimal("0.01"), ROUND_HALF_UP), cost, tonne_km, {"trips": trips}


def expiry_write_offs(c: "kpi.Ctx") -> tuple:
    """Value (standard price) of own stock written off after its batch expired, from the expiry write-off movements (551)."""
    row = c.one(
        "SELECT coalesce(sum(-m.qty * coalesce(mat.standard_price_minor, 0)), 0), count(*) FROM pic.stock_movement m "
        "JOIN pic.material mat ON mat.id = m.material_id WHERE m.movement_type = '551' AND m.reference_type = 'EXPIRY_WRITE_OFF'"
        + c.when("m.created_at") + c.at_plant("m.plant"))
    cold = c.one("SELECT coalesce(sum(-m.qty * coalesce(mat.standard_price_minor, 0)), 0) FROM pic.stock_movement m "
                 "JOIN pic.material mat ON mat.id = m.material_id WHERE m.movement_type = '551' AND m.reference_type = 'COLD_CHAIN_REJECT'"
                 + c.when("m.created_at") + c.at_plant("m.plant"))
    return Decimal(int(row[0])), Decimal(int(row[0])), None, {"batches": int(row[1]), "coldChainWriteOffMinor": int(cold[0])}


def _register() -> None:
    for code, compute, name, formula, source in (
            ("TPL.COST_TO_COMPLETE", cost_to_complete, "Cost to complete (minor units)",
             "open commitments on WBS elements (placed orders not yet invoiced); detail: budget, actual, forecast at completion, headroom",
             "budget (WBS), po_line"),
            ("TPL.COST_PER_TONNE_KM", cost_per_tonne_km, "Cost per tonne-km (minor units)",
             "approved trip service entries / (payload tonnes × km) of the recorded freight movements", "freight_movement, service_entry"),
            ("TPL.EXPIRY_WRITE_OFFS", expiry_write_offs, "Expiry write-offs (minor units)",
             "standard value of own stock written off after expiry (movement 551, reference EXPIRY_WRITE_OFF)", "stock_movement, material")):
        existing = kpi.REGISTRY.get(code)
        if existing is None:
            continue  # the registry of this release does not define it: the endpoint below still computes the function
        kpi.register(replace(existing, compute=compute, needs=None, name=name, formula=formula, source=source))


_register()


# ---------------------------------------------------------------- drill-downs
def ppv_by_material(session: Session, limit: int = 20) -> list[dict]:
    """Purchase price variance against the standard price per material: Σ (PO price − standard price) × quantity ordered."""
    rows = session.execute(text(
        "SELECT mat.number, mat.description, mat.standard_price_minor, sum(l.qty) AS qty, sum(l.net_minor) AS ordered, "
        "sum(l.net_minor - round(l.qty * mat.standard_price_minor)) AS variance, sum(round(l.qty * mat.standard_price_minor)) AS standard "
        "FROM pic.po_line l JOIN pic.material mat ON mat.id = l.material_id JOIN pic.purchase_order po ON po.id = l.po_id "
        "WHERE mat.standard_price_minor IS NOT NULL AND po.status <> 'CANCELLED' AND l.ses_required = false "
        "GROUP BY mat.number, mat.description, mat.standard_price_minor HAVING sum(l.net_minor - round(l.qty * mat.standard_price_minor)) <> 0 "
        "ORDER BY abs(sum(l.net_minor - round(l.qty * mat.standard_price_minor))) DESC LIMIT :n"), {"n": limit}).all()
    return [{"material": r[0], "description": r[1], "standardPriceMinor": int(r[2]), "qty": str(r[3]), "orderedMinor": int(r[4]), "standardMinor": int(r[6]),
             "ppvMinor": int(r[5]), "ppvPct": str((Decimal(int(r[5])) * 100 / Decimal(int(r[6]))).quantize(Decimal("0.1"))) if int(r[6]) else None}
            for r in rows]


def rate_compliance_by_supplier(session: Session) -> list[dict]:
    rows = session.execute(text(
        "SELECT s.code, s.legal_name, count(*) FILTER (WHERE NOT l.price_deviation), count(*) FROM pic.po_line l "
        "JOIN pic.purchase_order po ON po.id = l.po_id JOIN pic.supplier s ON s.id = po.supplier_id "
        "WHERE l.price_source IN ('CONTRACT', 'INFO_RECORD', 'CATALOGUE') GROUP BY s.code, s.legal_name ORDER BY s.code")).all()
    return [{"supplier": r[0], "name": r[1], "atRate": int(r[2]), "lines": int(r[3]),
             "pct": str((Decimal(int(r[2])) * 100 / Decimal(int(r[3]))).quantize(Decimal("0.1"))) if int(r[3]) else None} for r in rows]


def catalogue_adoption_by_category(session: Session) -> list[dict]:
    rows = session.execute(text(
        "SELECT coalesce(l.category, l.material_group), count(*) FILTER (WHERE l.item_type = 'CATALOGUE' OR l.catalogue_item_id IS NOT NULL), count(*) "
        "FROM pic.pr_line l JOIN pic.requisition r ON r.id = l.requisition_id WHERE r.status <> 'DRAFT' "
        "GROUP BY coalesce(l.category, l.material_group) ORDER BY 3 DESC")).all()
    return [{"category": r[0], "catalogueLines": int(r[1]), "lines": int(r[2]),
             "pct": str((Decimal(int(r[1])) * 100 / Decimal(int(r[2]))).quantize(Decimal("0.1"))) if int(r[2]) else None} for r in rows]


DRILLDOWNS = {"TPL.PPV": ppv_by_material, "TPL.RATE_COMPLIANCE": rate_compliance_by_supplier, "TPL.CATALOGUE_ADOPTION": catalogue_adoption_by_category}


def industry_kpis(session: Session, period: Optional[str] = None, plant: Optional[str] = None, include_other_templates: bool = False) -> dict:
    """The six industry KPIs applicable to the tenant's template (all six with ``include_other_templates``), each with its drill-down."""
    tenant = session.get(Tenant, current_tenant(session))
    template = tenant.industry_template if tenant else None
    out = []
    for code in CODES:
        definition = kpi.REGISTRY.get(code)
        if definition is None:
            continue
        if definition.templates and not include_other_templates and template not in definition.templates:
            continue
        if plant and "PLANT" not in definition.scopes:
            continue
        item = kpi.evaluate(session, definition, period, plant)
        drill = DRILLDOWNS.get(code)
        if drill is not None and not period:
            item["drillDown"] = drill(session)
        out.append(item)
    return {"template": template, "period": period, "kpis": out}
