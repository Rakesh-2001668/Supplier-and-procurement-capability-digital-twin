"""Datasets and operating cases for the intelligence and governance modules (M01, M02, M06, M07, M08, M10–M13).

Axion (manufacturing demo tenant):
- ERP initial load (Technical Document §12.4) at go-live: vendor masters and 24 months of posted spend (Oct 2024 – Sep 2026)
  with the ERP's own document numbers. The trailing-12-month portfolio is calibrated to the blueprint's AIX-01
  figures (spend 412 Cr, contract coverage ≈ 71%, maverick ≈ 6%). About one line in twelve arrives without a
  category, as in a real ERP extract, and goes through the Spend Classification Agent.
- ERP consumption feed (stock → platform): monthly consumption and the ERP plan for the castings and fastener kits.
Then the cases run through the services: classification and steward review, maverick hits and dispositions,
category plans (Kraljic) and approval, forecast review with a Demand Sensing recommendation accepted and released
to MRP, supplier risk scan, CAPA response, sourcing-strategy advice, a supplier change request after confirmation,
expediting, ERP reconciliation, a manual savings initiative and a manually drafted rate contract.

Legacy tenants (GMC, DBY) run the same scans over their migrated data (see `run_for_tenant`).
"""
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.pic.models import (
    AppUser, Capa, ClassificationReview, Forecast, MaverickHit, Material, PurchaseOrder, Recommendation, SpendLine, Supplier,
    SupplierCategoryStatus, TaxonomyNode,
)
from app.pic.platform import audit, clock
from app.pic.platform.core import next_number
from app.pic.seed.axion import Scenario, at

NS = uuid.UUID("6a0e8c1e-2b51-4c0e-9d1f-1c5a7e3b9f20")
CR = 100 * 100_000 * 100  # one crore in paise
HISTORY = [f"{y}-{m:02d}" for y, m in [(2024, 10), (2024, 11), (2024, 12)] + [(2025, m) for m in range(1, 13)] + [(2026, m) for m in range(1, 10)]]
SEASON = [0.99, 0.97, 0.93, 1.01, 1.04, 1.08, 0.96, 0.98, 1.00, 1.03, 1.02, 0.99]  # Oct..Sep

# ERP vendor master (initial load). code, legal name, terms, categories (status), risk tier
ERP_VENDORS = [
    ("V-210041", "Nilgiri Forgings Pvt Ltd", "N45", [("FORGINGS", "QUALIFIED")], "LOW"),
    ("V-210042", "Kaveri Forge Works", "N60", [("FORGINGS", "QUALIFIED")], "MEDIUM"),
    ("V-210051", "Hosur Precision Machining Pvt Ltd", "N45", [("MACHINING", "QUALIFIED")], "LOW"),
    ("V-210052", "Ambattur CNC Works", "N30", [("MACHINING", "QUALIFIED")], "HIGH"),
    ("V-210061", "Ennore Aluminium Ingots Pvt Ltd", "N30", [("RAW-MATERIALS", "QUALIFIED")], "LOW"),
    ("V-210062", "Manali Metals Pvt Ltd", "N45", [("RAW-MATERIALS", "QUALIFIED")], "LOW"),
    ("V-210071", "Palar Fasteners Pvt Ltd", "N45", [("FASTENERS", "QUALIFIED")], "LOW"),
    ("V-210072", "Ranipet Fasteners Pvt Ltd", "N45", [("FASTENERS", "QUALIFIED")], "LOW"),
    ("V-210081", "Guindy Electronics Pvt Ltd", "N60", [("ELECTRONICS", "QUALIFIED")], "HIGH"),
    ("V-210082", "Velachery Sensor Systems", "N45", [("ELECTRONICS", "QUALIFIED")], "LOW"),
    ("V-210091", "Sriperumbudur Packaging Pvt Ltd", "N30", [("PACKAGING", "QUALIFIED")], "LOW"),
    ("V-210092", "Poonamallee Rubber Products", "N30", [("RUBBER-SEALS", "QUALIFIED")], "LOW"),
    ("V-210101", "Southern Roadlines Pvt Ltd", "N30", [("LOGISTICS", "QUALIFIED")], "MEDIUM"),
    ("V-210111", "Kanchi Industrial Supplies", "N30", [("MRO", "QUALIFIED")], "LOW"),
    ("V-210112", "Kanchi Industrial Supply Co", "N30", [("MRO", "QUALIFIED")], "LOW"),
    ("V-210121", "Adyar Infotech Services Pvt Ltd", "N45", [("IT-SERVICES", "QUALIFIED")], "LOW"),
    ("V-210131", "Mylapore Facility Services", "N30", [("FACILITIES", "QUALIFIED")], "LOW"),
    ("V-210141", "Nungambakkam Advisory LLP", "N30", [], None),
    ("V-210151", "Chengalpet Machine Tools Pvt Ltd", "N60", [("CAPEX-MACHINERY", "QUALIFIED")], "MEDIUM"),
    ("V-219001", "Axion Mobility Systems – Pune Unit (intercompany)", "N30", [], None),
]

# category: (annual Cr, contracted share, [(supplier, share)], plant split P100, ERP description, growth vs prior year)
PORTFOLIO = {
    "ALU-DIECAST": (150, 0.90, [("TF001", 0.55), ("KD002", 0.30), ("SLA003", 0.15)], 0.7, "Aluminium die-cast housings and covers (ADC12)", 1.06),
    "FORGINGS": (60, 0.80, [("V-210041", 0.6), ("V-210042", 0.4)], 0.6, "Steering knuckle forgings", 1.05),
    "MACHINING": (45, 0.55, [("V-210051", 0.7), ("V-210052", 0.3)], 0.6, "CNC machined shafts and flanges", 1.04),
    "RAW-MATERIALS": (40, 0.85, [("V-210061", 0.6), ("V-210062", 0.4)], 1.0, "Aluminium alloy ingot ADC12", 1.09),
    "FASTENERS": (18, 0.35, [("V-210071", 0.65), ("V-210072", 0.35)], 0.7, "Bolts, nuts and washers – zinc flake", 1.03),
    "ELECTRONICS": (25, 0.60, [("V-210081", 0.6), ("V-210082", 0.4)], 0.5, "ECU connectors, sensors and wiring harness", 1.25),
    "PACKAGING": (9, 0.40, [("V-210091", 1.0)], 0.7, "Returnable crates, cartons and pallets", 1.02),
    "RUBBER-SEALS": (4, 0.25, [("V-210092", 1.0)], 0.7, "O-rings and gaskets", 1.00),
    "LOGISTICS": (16, 0.50, [("V-210101", 1.0)], 0.5, "FTL freight Hosur – Pune – Chennai", 1.12),
    "TOOLING-SERVICES": (12, 0.40, [("HTS004", 1.0)], 1.0, "Die maintenance and tooling inserts", 1.02),
    "MRO": (8, 0.15, [("V-210111", 0.6), ("V-210112", 0.4)], 0.6, "Bearings, lubricants and cutting tools", 0.98),
    "IT-SERVICES": (7, 0.40, [("V-210121", 1.0)], 1.0, "Cloud subscription and IT support", 1.08),
    "FACILITIES": (5, 0.70, [("V-210131", 1.0)], 0.5, "Housekeeping and security services", 1.04),
    "PROF-SERVICES": (3, 0.0, [("V-210141", 1.0)], 1.0, "Consulting – cost reduction programme", 1.00),
    "CAPEX-MACHINERY": (6, 0.0, [("V-210151", 1.0)], 1.0, "CNC machine centre and compressor", 1.00),
    "IC-TRANSFER": (4, 0.0, [("V-219001", 1.0)], 1.0, "Intercompany stock transfer – Pune unit", 1.00),
}
# Maverick share of a category's annual spend carried by flagged lines (blueprint §7.2 default rules).
MAVERICK = {
    "ALU-DIECAST": ("OFF_CONTRACT", 4.0, "SLA003", "Spot buy of DC-330 housings outside the scheduling agreement"),
    "FORGINGS": ("OFF_CONTRACT_PRICE", 3.0, "V-210042", "Knuckle forgings invoiced above the contract price"),
    "MACHINING": ("SPLIT_PO", 2.5, "V-210052", "Machined flanges – four POs in one week"),
    "FASTENERS": ("SPLIT_PO", 2.0, "V-210071", "Fastener top-ups split below approval band"),
    "LOGISTICS": ("PO_AFTER_INVOICE", 4.0, "V-210101", "Freight invoices with retrospective POs"),
    "MRO": ("NON_CATALOGUE", 2.5, "V-210112", "Bearings bought as free text although on catalogue"),
    "ELECTRONICS": ("OFF_CONTRACT", 2.0, "V-210082", "Sensors bought outside the price agreement"),
    "PACKAGING": ("PO_AFTER_INVOICE", 1.3, "V-210091", "Cartons invoiced before the PO"),
    "IT-SERVICES": ("NON_CATALOGUE", 1.0, "V-210121", "Laptop accessories bought outside the IT catalogue"),
}
# ERP lines that come without a category (material group "MISC") with their text.
UNCLASSIFIED_TEXTS = [
    ("LOGISTICS", "Freight charges Chennai to Pune FTL 32 ft"),
    ("MRO", "Bearing 6205 ZZ and lubricants for press line"),
    ("FACILITIES", "Annual maintenance contract housekeeping and canteen"),
    ("IT-SERVICES", "Software licence renewal and cloud subscription"),
    ("PACKAGING", "Stretch film and carton boxes"),
    ("MRO", "Shop-floor consumables"),
    ("CAPEX-MACHINERY", "Compressor overhaul and spare kit"),
    ("PROF-SERVICES", "Training programme for quality team"),
]
CONSUMPTION = {
    # material: (base monthly consumption, ERP plan bias over the last months)
    "DC-330": (88_000, 1.00),
    "DC-331": (21_000, 1.22),
    "FK-M8-50": (44_000, 1.03),
}


def _vendors(sc: Scenario) -> dict[str, uuid.UUID]:
    with sc.act("admin", at(date(2026, 10, 5), 18)) as s:
        ids = {x.code: x.id for x in s.execute(select(Supplier)).scalars()}
        admin_id = s.info["principal"].user_id
        for code, name, terms, categories, tier in ERP_VENDORS:
            if code in ids:
                continue
            supplier = Supplier(tenant_id=sc.tenant_id, code=code, legal_name=name, status="ACTIVE", country="IN", payment_terms=terms,
                                risk_tier=tier, segment="INTERCOMPANY" if code.startswith("V-219") else None,
                                screening={"outcome": "NOT_SCREENED", "source": "ERP_INITIAL_LOAD", "erpVendor": code}, created_by=admin_id)
            s.add(supplier)
            s.flush()
            ids[code] = supplier.id
            for category, status in categories:
                s.add(SupplierCategoryStatus(tenant_id=sc.tenant_id, supplier_id=supplier.id, category=category, status=status,
                                             qualified_on=date(2025, 4, 1), created_by=admin_id))
            audit.record(s, "SUPPLIER", supplier.id, "MIGRATED", object_ref=code, after={"source": "SAP_S4 vendor master", "legalName": name},
                         actor="migration")
    return ids


def _spend_history(sc: Scenario, ids: dict[str, uuid.UUID]) -> int:
    lines = 0
    with sc.act("ap.clerk", at(date(2026, 10, 5), 19)) as s:
        if s.execute(select(SpendLine.id).where(SpendLine.source == "ERP_HISTORY")).first():
            return 0
        user = s.info["principal"].user_id
        doc = 5105000001
        for category, (annual, contracted, suppliers, p100, text, growth) in PORTFOLIO.items():
            flag = MAVERICK.get(category)
            texts = [t for c, t in UNCLASSIFIED_TEXTS if c == category]
            for index, period in enumerate(HISTORY):
                year_factor = 1.0 if index >= 12 else 1 / growth
                month = annual * CR / 12 * SEASON[index % 12] * year_factor
                if category == "ELECTRONICS" and index >= 18:
                    month *= 1.18  # EV programme ramp-up in the last six months
                if category == "LOGISTICS" and HISTORY[index] in ("2026-08", "2026-09"):
                    month *= 1.35  # monsoon disruption premium freight
                parts = []
                flagged = (flag[1] / annual) * month if flag else 0
                if flag:
                    parts.append((flag[2], flagged, False, [flag[0]], flag[3]))
                unclassified = month * 0.08 if texts else 0
                on_contract = month * contracted
                off_contract = max(0.0, month - on_contract - flagged - unclassified)
                for code, share in suppliers:
                    parts.append((code, on_contract * share, True, [], text))
                    parts.append((code, off_contract * share, False, [], text))
                if texts:
                    parts.append((suppliers[0][0], unclassified, False, [], texts[index % len(texts)]))
                for n, (code, amount, is_contracted, flags, description) in enumerate(parts):
                    minor = int(round(amount))
                    if minor <= 0:
                        continue
                    for plant, plant_share in (("P100", p100), ("P200", 1 - p100)):
                        part = int(minor * plant_share)
                        if part <= 0:
                            continue
                        doc += 1
                        ref = f"ERP-{doc}"
                        unclassified_line = description in texts
                        s.add(SpendLine(
                            tenant_id=sc.tenant_id, invoice_line_id=uuid.uuid5(NS, ref), invoice_ref=ref,
                            po_ref=None if "PO_AFTER_INVOICE" in flags and n % 2 else f"45{doc % 100000000:08d}", supplier_id=ids[code],
                            category="UNCLASSIFIED" if unclassified_line else category, material_group="MISC" if unclassified_line else category,
                            plant=plant, company_code="1000", cost_object=None if category in ("ALU-DIECAST", "FORGINGS", "MACHINING", "RAW-MATERIALS")
                            else "COST_CENTER:4100", period=period, amount_minor=part, currency="INR", contracted=is_contracted,
                            addressable=category != "IC-TRANSFER", maverick_flags=flags,
                            classification_confidence=Decimal("0.000") if unclassified_line else Decimal("1.000"), description=description[:300],
                            price_variance_minor=int(part * 0.04) if "OFF_CONTRACT_PRICE" in flags else 0, source="ERP_HISTORY",
                            created_by=user))
                        lines += 1
        s.flush()
        audit.record(s, "SPEND_LINE", uuid.uuid5(NS, "erp-history"), "MIGRATED", object_ref="ERP spend history",
                     after={"lines": lines, "periods": [HISTORY[0], HISTORY[-1]], "source": "SAP_S4 invoices (RE) and POs (NB)"}, actor="migration")
    return lines


def _consumption_history(sc: Scenario) -> None:
    """Monthly consumption from the ERP stock feed and the ERP plan for the same months (Nov 2025 – Feb 2027)."""
    periods = HISTORY[12:] + ["2026-10", "2026-11", "2026-12", "2027-01", "2027-02"]
    with sc.act("mrp.controller", at(date(2027, 3, 31), 12)) as s:
        user = s.info["principal"].user_id
        for number, (base, bias) in CONSUMPTION.items():
            material = s.execute(select(Material).where(Material.number == number)).scalar_one()
            for i, period in enumerate(periods):
                if s.execute(select(Forecast.id).where(Forecast.material_id == material.id, Forecast.period == period)).first():
                    continue
                actual = Decimal(int(base * SEASON[(i + 12) % 12]))
                plan_factor = bias if i >= len(periods) - 4 else 1.0 + (0.02 if i % 3 == 0 else -0.015)
                s.add(Forecast(tenant_id=sc.tenant_id, material_id=material.id, plant="P100", period=period, method="ERP_PLAN",
                               statistical_qty=Decimal(int(float(actual) * plan_factor)), actual_qty=actual,
                               actual_source="ERP_CONSUMPTION_HISTORY", model_version="sap-ibp", created_by=user))


def load_erp_history(sc: Scenario) -> None:
    """Go-live load from SAP: vendor masters and posted spend history (run before the signature case)."""
    ids = _vendors(sc)
    lines = _spend_history(sc, ids)
    sc.note(f"ERP initial load: {len(ERP_VENDORS)} vendor masters, {lines} spend lines {HISTORY[0]} – {HISTORY[-1]}")


def run(sc: Scenario) -> None:
    """After month-end (31 Mar 2027): the scans and decisions of the intelligence and governance modules."""
    from app.pic.services import admin as admin_svc
    from app.pic.services import contract as contract_svc
    from app.pic.services import forecasting, order, payables, risk, savings, sourcing_strategy, spend

    # ------------------------------------------------------------ M01 classification, maverick hits, category plans
    with sc.act("category.head", at(date(2027, 3, 31), 15)) as s:
        result = spend.refresh(s, sc.tenant_id)
        overview = spend.overview(s)
    sc.note(f"Spend refresh: {result['auto']} auto-classified, {result['review']} to steward review, {result['hits']} maverick hits; "
            f"12-month spend {overview['totalMinor'] / CR:.1f} Cr, contracted {overview['contractedPct']}%, maverick {overview['maverickPct']}%")
    with sc.act("category.head", at(date(2027, 3, 31), 15, 10)) as s:
        # Stewards worked the backlog up to July 2026; August and September stay in the queue.
        reviews = s.execute(select(ClassificationReview).join(SpendLine, SpendLine.id == ClassificationReview.spend_line_id).where(
            ClassificationReview.status == "OPEN", SpendLine.period < "2026-08").order_by(ClassificationReview.invoice_ref)).scalars().all()
        decided = 0
        for review in reviews:
            truth = next((c for c, t in UNCLASSIFIED_TEXTS if t == review.description), None)
            if truth:
                spend.decide_review(s, review, truth, "Checked against the ERP invoice text")
                decided += 1
        plans = spend.generate_plans(s, "2027-28", s.info["principal"].user_id)
        hits = s.execute(select(MaverickHit).where(MaverickHit.status == "OPEN").order_by(MaverickHit.amount_minor.desc())).scalars().all()
        freight = next((h for h in hits if h.rule_code == "PO_AFTER_INVOICE"), None)
        spot = next((h for h in hits if h.rule_code == "OFF_CONTRACT"), None)
        if freight:
            spend.dispose(s, freight, "POLICY_BREACH", "Retrospective freight POs; logistics desk to raise POs at booking from April")
        if spot:
            spend.dispose(s, spot, "RECOVERY", "Spot buy above the scheduling-agreement price; debit note requested from supplier")
    quadrants = {p.category: p.kraljic for p in plans}
    sc.note(f"Steward review: {decided} lines classified; category plans 2027-28: "
            + ", ".join(f"{c} {q.lower()}" for c, q in sorted(quadrants.items())[:6]) + " …")
    with sc.act("procurement.head", at(date(2027, 3, 31), 15, 20)) as s:
        plan = spend.get_plan(s, "ALU-DIECAST")
        spend.approve_plan(s, plan, "Dual-source strategy confirmed; renew SA-5520 in Q3")
    sc.note(f"Category plan {plan.number} (ALU-DIECAST, {plan.kraljic.lower()}) approved by the procurement head")

    # ------------------------------------------------------------ M02 forecast review and Demand Sensing
    _consumption_history(sc)
    with sc.act("mrp.controller", at(date(2027, 3, 31), 12, 30)) as s:
        forecasting.generate(s)
        recs = forecasting.sense(s)
    accepted = None
    with sc.act("mrp.controller", at(date(2027, 3, 31), 13)) as s:
        rec = s.execute(select(Recommendation).where(Recommendation.agent_code == "DEMAND_SENSING", Recommendation.status == "OPEN")
                        .order_by(Recommendation.object_ref)).scalars().first()
        if rec:
            admin_svc.decide_recommendation(s, rec, True, "Bias confirmed with sales: DC-331 call-offs are below plan")
            f = s.execute(select(Forecast).join(Material, Material.id == Forecast.material_id).where(
                Material.number == rec.proposal["material"], Forecast.period == rec.proposal["period"])).scalar_one()
            forecasting.override(s, f, Decimal(rec.proposal["proposedQty"]), f"Demand Sensing recommendation accepted (bias {rec.proposal['bias']})")
            accepted = f"{rec.proposal['material']} {rec.proposal['period']}: {rec.proposal['statisticalQty']} → {rec.proposal['proposedQty']}"
    sc.note(f"Forecast review: {len(recs)} Demand Sensing recommendation(s); accepted and released to MRP: {accepted}")

    # ------------------------------------------------------------ M06 risk scan, CAPA
    with sc.act("supplier.manager", at(date(2027, 3, 31), 14)) as s:
        signals = risk.scan(s)
        monitor = risk.monitor(s)
    sc.note(f"Supplier risk scan: {len(signals)} signal(s), {monitor['suppliersWithSignals']} supplier(s) on the heat map")
    with sc.act("tf.sales", at(date(2027, 3, 31), 14, 30)) as s:
        capa = s.execute(select(Capa).where(Capa.supplier_id == s.info["principal"].supplier_id, Capa.status == "OPEN")).scalars().first()
        if capa:
            risk.respond_capa(s, capa, root_cause="Porosity from die temperature drift on cell 4 (8D D4)",
                              actions=[{"action": "Install die thermocouple alarms on cell 4", "due": "2027-04-15"},
                                       {"action": "100% X-ray on DC-330 for two weeks", "due": "2027-04-10"}])
    if capa:
        sc.note(f"{capa.number}: Trichy Forge responded to the GR-90231 rejection (root cause and two actions); awaiting quality verification")

    # ------------------------------------------------------------ M05 sourcing strategy advice
    with sc.act("category.head", at(date(2027, 3, 31), 15, 30)) as s:
        advice = sourcing_strategy.recommend_all(s)
    sc.note(f"Sourcing Strategy Agent: {len(advice)} recommendation(s) for unsourced requisition lines")

    # ------------------------------------------------------------ M08 expediting
    with sc.act("buyer", at(date(2027, 3, 31), 16, 30)) as s:
        late = [r for r in order.expediting_view(s) if r["risk"] != "ON_TRACK"]
        if late:
            first = late[0]
            order.expedite(s, s.execute(select(PurchaseOrder).where(PurchaseOrder.number == first["po"])).scalar_one(), first["line"])
    sc.note(f"Expediting cockpit: {len(late)} line(s) late or at risk" + (f"; follow-up drafted for {late[0]['po']}/{late[0]['line']}" if late else ""))

    # ------------------------------------------------------------ M10 reconciliation, M11 manual initiative, M07 manual contract
    with sc.act("ap.clerk", at(date(2027, 3, 31), 18)) as s:
        recon = payables.reconcile(s, "1000")
    sc.note(f"ERP reconciliation {recon['number']}: {recon['platformCount']} posted invoices vs {recon['erpCount']} SAP documents, "
            f"{recon['differences']} difference(s)")
    with sc.act("category.manager", at(date(2027, 3, 31), 17)) as s:
        initiative = savings.create_initiative(s, title="Fastener kit consolidation FY27-28", category="FASTENERS", baseline_method="LAST_PRICE",
                                               annual_volume=Decimal(480000), material_number="FK-M8-50")
        savings.negotiate(s, initiative, int(initiative.baseline_price_minor * 0.94), "V-210071",
                          "Palar Fasteners quote PF/Q/2027-031, 12-month validity")
    sc.note(f"{initiative.number}: fastener consolidation, baseline last price {initiative.baseline_price_minor / 100:.2f}, "
            f"negotiated −6% with Palar Fasteners")
    with sc.act("contract.manager", at(date(2027, 3, 31), 17, 30)) as s:
        hts = s.execute(select(Supplier).where(Supplier.code == "HTS004")).scalar_one()
        contract = contract_svc.create_draft(
            s, type="VALUE_CONTRACT", title="Tooling services rate contract FY 2027-28 – Hosur Tooling Services", supplier_id=hts.id,
            company_code="1000", valid_from=date(2027, 4, 1), valid_to=date(2028, 3, 31), payment_terms="N30", incoterms=None,
            lines=[{"material_id": None, "description": "Preventive die-maintenance visit", "plant": "P100", "uom": "EA", "target_qty": Decimal(48),
                    "unit_price_minor": 18500 * 100},
                   {"material_id": None, "description": "Tooling insert set DC-330 line 3", "plant": "P100", "uom": "SET", "target_qty": Decimal(24),
                    "unit_price_minor": 31250 * 100}],
            owner_id=s.info["principal"].user_id, tolerances={"over_pct": "0", "under_pct": "0", "price_pct": "0"})
        review = contract_svc.ai_review(s, contract)
    sc.note(f"{contract.number}: value contract drafted manually from the VALUE_CONTRACT template, AI review risk {review.get('riskScore', review)}")


# ---------------------------------------------------------------- legacy and other tenants
def run_for_tenant(sc: Scenario, *, manager: str, mrp: str, supplier_mgr: str, keywords: dict | None = None) -> dict:
    """Scan a tenant's own data with the new modules (used after the legacy migration)."""
    from app.pic.services import forecasting, risk, sourcing_strategy, spend
    out = {}
    with sc.act(manager, clock.now()) as s:
        spend.ensure_taxonomy(s, sc.tenant_id)
        for code, words in (keywords or {}).items():
            node = s.execute(select(TaxonomyNode).where(TaxonomyNode.code == code)).scalar_one_or_none()
            if node is None:
                s.add(TaxonomyNode(tenant_id=sc.tenant_id, code=code, parent_code="DIRECT", level=3, name=code.replace("-", " ").title(),
                                   keywords=sorted(set(words)), addressable=True))
            else:
                node.keywords = sorted(set(node.keywords or []) | set(words))
        s.flush()
        out["spend"] = spend.refresh(s, sc.tenant_id)
        out["plans"] = [f"{p.category}:{p.kraljic}" for p in spend.generate_plans(s, clock.fiscal_year(clock.today()), s.info["principal"].user_id)]
        out["sourcingAdvice"] = len(sourcing_strategy.recommend_all(s))
    with sc.act(mrp, clock.now()) as s:
        out["forecasts"] = len(forecasting.generate(s))
        out["demandSensing"] = len(forecasting.sense(s))
    with sc.act(supplier_mgr, clock.now()) as s:
        out["riskSignals"] = len(risk.scan(s))
    return out
