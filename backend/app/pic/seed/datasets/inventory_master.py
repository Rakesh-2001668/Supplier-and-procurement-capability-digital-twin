"""D14 Inventory go-live inputs for the demo tenants AXN and KAC: MOCK (ILLUSTRATIVE SAMPLE; the real values need the customer's data and sign-off).

The inventory module needs five inputs before a tenant goes live. Until the customer supplies them for real, this pack fills each with clearly
labelled mock values, derived from the tenant's own data and loaded through the same code a real tenant would use, so the demo tenants behave like a
configured production tenant. Everything is idempotent (seed-if-missing; a value that is already set is never overwritten) and traceable (audit
events, ``MOCK`` in names, notes, descriptions and the data README ``data/erp_mock/KAC_INVENTORY/README.md``).

  1  master data     standard price, safety stock and reorder point / maximum stock of STOCK materials where they are missing, by the formulas of
                     ``tools/inventory_mock.py``; batch / expiry flags on chemicals, lubricants, rubber compounds, raw-material lots and adhesive
                     tapes / labels. One audit event MASTER_DATA_FILLED per material (the normal change request needs a steward approval per change
                     and an ERP update, which a bulk mock fill cannot use). The three signature-case materials of AXN are never touched.
  2  opening stock   KAC only: the 1,600-line file ``data/erp_mock/KAC_INVENTORY/opening_stock.csv`` through ``tools/stock_opening_load.py`` (movement
                     561, reconciled to the file's valuation column); the 20 materials of the ``inventory_ops`` pack are skipped
  3  users           two INVENTORY_CONTROLLER users per plant (``inventory.controller.<plant>.1`` / ``.2``, ABAC plant = that plant only, KAC with a value
                     limit that matches its approval bands) and a RECEIVER for every plant that has none
  4  rule values     KAC only: new effective-dated versions of INVENTORY-POSTING / -COUNT / -RESERVATION / -ALERTS labelled "MOCK proposal - pending client
                     sign-off" (the values and their rationale: docs/PIC_Inventory_Rule_Values_Proposal.md)

Requires ``inventory-ops`` (its opening position is the 20 balances this pack must not duplicate).
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.pic.db import tenant_tx
from app.pic.models import (
    AppUser, ContractLine, InfoRecord, Material, Plant, PlanningParameter, PoLine, PriceValidity, PurchaseOrder, RuleSet, Stock, Tenant,
)
from app.pic.platform import audit, clock
from app.pic.platform import inventory_defaults as ir
from app.pic.platform.errors import Problem
from app.pic.seed.axion import Scenario, at
from app.pic.seed.datasets import _tenant_kit as kit
from app.pic.tools import inventory_mock as mock

KEY = "inventory-master"
VERSION = "1"
TITLE = "D14 Inventory go-live inputs for AXN and KAC: master data, KAC opening stock, controllers per plant, KAC rule values (MOCK, ILLUSTRATIVE SAMPLE)"
TENANTS = ("AXN", "KAC")
CREATES_TENANT = False
READY = True
REQUIRES = {"inventory-ops": "1"}

LABEL = mock.TAG
ACTOR = "mock-data:inventory_master"
PROTECTED = {"AXN": {"DC-330", "DC-331", "FK-M8-50"}}     # the signature case's materials: no pack changes their planning outcome
OPEN_PO = ("DRAFT", "IN_APPROVAL", "RELEASED", "TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED")
L = 100_000 * 100                                           # one lakh rupees in paise

# KAC rule values (MOCK proposal, rationale in docs/PIC_Inventory_Rule_Values_Proposal.md). Amounts in paise.
RULE_VERSION = "2026.2-KAC-MOCK"
RULE_EFFECTIVE = date(2026, 11, 1)
RULE_DESCRIPTION = ("MOCK proposal - pending client sign-off. Values proposed from KAC's own stock value range (median stock line INR 97,000, 90th "
                    "percentile INR 6.4 lakh); the customer has not confirmed them. See docs/PIC_Inventory_Rule_Values_Proposal.md.")
POSTING_BANDS = [{"upTo": 3 * L, "chain": ["INVENTORY_CONTROLLER"]},
                 {"upTo": 15 * L, "chain": ["INVENTORY_CONTROLLER", "FINANCE_CONTROLLER"]},
                 {"upTo": None, "chain": ["FINANCE_CONTROLLER", "CPO"]}]
KAC_RULES = {
    ir.POSTING_KEY: {
        "autoPostBelowMinor": 50_000 * 100, "autoPostTypes": ["TRANSFER", "BLOCK", "UNBLOCK"], "approvalBands": POSTING_BANDS,
        "reasonRequiredFor": ["BLOCK", "SCRAP"],
        "scrapReasons": {"CASTING_DEFECT": "Casting defect (porosity, cold shut, blow hole), not recoverable",
                         "MACHINING_REJECT": "Machining reject, out of tolerance, not reworkable",
                         "HANDLING_DAMAGE": "Damaged in handling or storage (forklift, crate, stacking)",
                         "CORROSION": "Rust or corrosion in storage",
                         "SHELF_LIFE_EXPIRED": "Shelf life expired (rubber, adhesive, chemical, lubricant)",
                         "SUPERSEDED_ECN": "Superseded by an engineering change, no further use",
                         "FIRE_OR_SPILL": "Fire, water or spill loss", "OTHER": "Other (explain in the reason)"},
        "blockReasons": {"QUALITY_DOUBT": "Quality doubt", "SUPPLIER_8D": "Supplier containment (8D) in progress", "CUSTOMER_COMPLAINT": "Customer complaint trace-back",
                         "DAMAGED": "Damaged, to be assessed", "RECALL": "Supplier recall or field notice", "OTHER": "Other (explain in the reason)"},
        "crossPlantTransfer": True, "maxLines": 100, "slaBusinessDays": 2,
    },
    ir.COUNT_KEY: {
        "qtyTolerancePct": "1", "valueToleranceMinor": 10_000 * 100, "recountDifferentCounter": True, "maxLines": 2000, "slaBusinessDays": 3,
        "approvalBands": [{"upTo": 50_000 * 100, "chain": ["INVENTORY_CONTROLLER"]},
                          {"upTo": 5 * L, "chain": ["INVENTORY_CONTROLLER", "FINANCE_CONTROLLER"]},
                          {"upTo": None, "chain": ["FINANCE_CONTROLLER", "CPO"]}],
        "differenceReasonCode": "COUNT_DIFF",
    },
    ir.RESERVATION_KEY: {
        "blockWhenUnavailable": False, "graceDays": 3, "requireCostObject": True,
        "purposes": ["PRODUCTION", "MAINTENANCE", "TOOLING", "QUALITY_TRIAL", "PROJECT", "OTHER"], "maxOpenDays": 90,
    },
    ir.ALERTS_KEY: {"qualityHoldDays": 3, "blockedDays": 15, "expiryWarnDays": 90, "negativeDrift": True},
}
CONTROLLER_LIMIT_MINOR = POSTING_BANDS[1]["upTo"]           # a controller approves up to the top of the highest band their role is in

SPECS = {
    "AXN": {"domain": "axion.example", "plants": ["P100", "P200"], "when": (date(2027, 8, 9), 7), "limit": None},
    "KAC": {"domain": "kaveri-auto.example", "plants": ["1100", "1200", "1300"], "when": (date(2026, 11, 9), 7), "limit": CONTROLLER_LIMIT_MINOR},
}


def controller_email_local(plant: str, n: int) -> str:
    return f"inventory.controller.{plant}.{n}"


# ---------------------------------------------------------------- 1 master data
def _prices(session, material_ids: list) -> dict:
    """{material_id: price} from the tenant's own purchase history: latest PO line, else latest contract price period, else latest info record."""
    out: dict = {}
    if not material_ids:
        return out
    for mid, price in session.execute(select(PoLine.material_id, PoLine.unit_price_minor).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id)
                                      .where(PoLine.material_id.in_(material_ids), PoLine.unit_price_minor > 0, PurchaseOrder.status != "CANCELLED")
                                      .order_by(PurchaseOrder.created_at, PoLine.line_no)):
        out[mid] = int(price)
    for mid, price in session.execute(select(ContractLine.material_id, PriceValidity.unit_price_minor).join(PriceValidity, PriceValidity.contract_line_id == ContractLine.id)
                                      .where(ContractLine.material_id.in_(material_ids), PriceValidity.unit_price_minor > 0)
                                      .order_by(PriceValidity.valid_to)):
        out.setdefault(mid, int(price))
    for mid, price in session.execute(select(InfoRecord.material_id, InfoRecord.last_price_minor).where(InfoRecord.material_id.in_(material_ids), InfoRecord.last_price_minor > 0)
                                      .order_by(InfoRecord.created_at)):
        out.setdefault(mid, int(price))
    return out


def _db_history(session, until: date) -> dict:
    """{(material number, plant): units per month} bought in the 12 months before ``until`` (else the 24 months), from the tenant's purchase orders."""
    from datetime import timedelta
    rows = session.execute(select(Material.number, PoLine.plant, func.date(PurchaseOrder.created_at), PoLine.qty).join(PoLine, PoLine.material_id == Material.id)
                           .join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(PurchaseOrder.status != "CANCELLED")).all()
    last12, last24 = {}, {}
    for number, plant, ordered, qty in rows:
        key = (number, plant)
        if until - timedelta(days=365) < ordered <= until:
            last12[key] = last12.get(key, Decimal(0)) + Decimal(qty)
        if until - timedelta(days=730) < ordered <= until:
            last24[key] = last24.get(key, Decimal(0)) + Decimal(qty)
    return {k: (last12[k] / 12 if last12.get(k) else last24[k] / 24) for k in set(last12) | set(last24)}


def _facts(m: Material, plants: list, price) -> "mock.Facts":
    return mock.Facts(number=m.number, uom=m.base_uom, category=m.category, group=m.material_group, std_minor=price, safety=Decimal(m.safety_stock or 0),
                      lead_days=int(m.planned_delivery_days or 0) + int(m.gr_processing_days or 0), lot_qty=m.lot_size_qty, min_lot=m.min_lot,
                      pack_size=m.pack_size, plants=sorted(plants), quality_managed=bool(m.quality_managed), description=m.description)


def _purchase_history(tenant_code: str, session) -> tuple:
    """(history, open_po): KAC's from its cutover extract (the history the PIC database does not keep per material), others' from their purchase orders."""
    if tenant_code == "KAC":
        from app.pic.seed.datasets import erp_client_kac
        history, open_po = mock.kac_purchase_history(erp_client_kac.data_dir())
        return history, open_po
    return _db_history(session, clock.today()), set()


def fill_master(tenant_id, tenant_code: str, when=None) -> dict:
    """Fill missing standard prices, safety stocks and reorder point / maximum stock per plant of the tenant's STOCK materials. A value that is set
    is never changed; every material that gets a value gets one audit event. Returns the counts."""
    if when:
        clock.set_pinned(when)
    counts = {"materialsChecked": 0, "materialsFilled": 0, "priceFilled": 0, "priceNoSource": 0, "safetyFilled": 0, "planningRowsAdded": 0, "maxStockFilled": 0}
    with tenant_tx(tenant_id) as s:
        history, _ = _purchase_history(tenant_code, s)
        use_stock = tenant_code != "KAC"
        materials = [m for m in s.execute(select(Material).where(Material.type == "STOCK", Material.status == "ACTIVE").order_by(Material.number)).scalars()
                     if m.number not in PROTECTED.get(tenant_code, set())]
        prices = _prices(s, [m.id for m in materials if not m.standard_price_minor])
        on_hand: dict = {}
        stock_plants: dict = {}
        for mid, plant, qty in s.execute(select(Stock.material_id, Stock.plant, func.sum(Stock.qty)).where(Stock.qty > 0).group_by(Stock.material_id, Stock.plant)):
            stock_plants.setdefault(mid, set()).add(plant)
        for mid, plant, qty in s.execute(select(Stock.material_id, Stock.plant, func.sum(Stock.qty)).where(Stock.stock_type == "UNRESTRICTED").group_by(Stock.material_id, Stock.plant)):
            on_hand.setdefault(mid, {})[plant] = Decimal(qty)
        known_plants = {p.code for p in s.execute(select(Plant)).scalars()}
        params = {(r.material_id, r.plant): r for r in s.execute(select(PlanningParameter)).scalars()}
        for m in materials:
            counts["materialsChecked"] += 1
            plants = sorted(set((m.attributes or {}).get("plants") or []) | stock_plants.get(m.id, set()))
            plants = [p for p in plants if p in known_plants]
            before, after = {}, {}
            price = m.standard_price_minor
            if not price:
                found = prices.get(m.id)
                if found:
                    before["standardPriceMinor"], after["standardPriceMinor"] = price, found
                    m.standard_price_minor, price = found, found
                    counts["priceFilled"] += 1
                else:
                    counts["priceNoSource"] += 1
            if not plants:
                if before:
                    _record(s, m, before, after)
                    counts["materialsFilled"] += 1
                continue
            plan = mock.plan_material(_facts(m, plants, price), {p: history[(m.number, p)] for p in plants if (m.number, p) in history},
                                      on_hand.get(m.id) if use_stock else None)
            if plan.safety_filled:
                before["safetyStock"], after["safetyStock"] = str(m.safety_stock or 0), str(plan.safety)
                m.safety_stock = plan.safety
                counts["safetyFilled"] += 1
            planning = []
            for plant in plants:
                row = params.get((m.id, plant))
                if row is None:
                    row = PlanningParameter(tenant_id=tenant_id, material_id=m.id, plant=plant, reorder_point=plan.reorder[plant], max_stock=plan.maximum[plant],
                                            note=f"{LABEL}: reorder point = daily usage x lead time + safety stock; max = reorder point + lot size")
                    s.add(row)
                    params[(m.id, plant)] = row
                    counts["planningRowsAdded"] += 1
                    planning.append({"plant": plant, "reorderPoint": str(plan.reorder[plant]), "maxStock": str(plan.maximum[plant]),
                                     "usageBasis": plan.usage[plant][1], "unitsPerMonth": str(plan.usage[plant][0].quantize(Decimal("0.001")))})
                elif row.max_stock is None:
                    row.max_stock = max(plan.maximum[plant], row.reorder_point)
                    counts["maxStockFilled"] += 1
                    planning.append({"plant": plant, "reorderPoint": str(row.reorder_point), "maxStock": str(row.max_stock), "usageBasis": "EXISTING_REORDER_POINT"})
            if planning:
                after["planning"] = planning
            if after:
                _record(s, m, before, after)
                counts["materialsFilled"] += 1
    return counts


def _record(session, m: Material, before: dict, after: dict) -> None:
    filled = sorted(k for k in after if k != "planning") + (["planningParameters"] if "planning" in after else [])
    m.attributes = {**(m.attributes or {}), "mockFilled": {"label": LABEL, "fields": filled, "pack": KEY}}
    audit.record(session, "MATERIAL", m.id, "MASTER_DATA_FILLED", object_ref=m.number, before=before or None, after=after, actor=ACTOR,
                 reason=f"{LABEL}: missing planning data filled by formula (tools/inventory_mock.py); the customer's own values replace them at go-live")


def apply_flags(tenant_id, tenant_code: str, when=None) -> dict:
    """Batch / expiry flags (material attributes batchManaged, expiryManaged, minShelfLifeDays) on materials that age or are traced by lot. A key that is
    already in the attributes is kept; a material with an open purchase-order line or with stock that has no batch is skipped (SAP does not convert such
    a material either, and a receipt in flight has no batch)."""
    if when:
        clock.set_pinned(when)
    counts = {"flagged": 0, "expiryManaged": 0, "skippedOpenPo": 0, "skippedStockWithoutBatch": 0}
    with tenant_tx(tenant_id) as s:
        _, open_numbers = _purchase_history(tenant_code, s)
        open_ids = {r for (r,) in s.execute(select(PoLine.material_id).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id)
                                            .where(PurchaseOrder.status.in_(OPEN_PO), PoLine.received_qty < PoLine.qty, PoLine.material_id.is_not(None)))}
        no_batch = {r for (r,) in s.execute(select(Stock.material_id).where(Stock.batch == "", Stock.qty > 0))}
        for m in s.execute(select(Material).where(Material.type == "STOCK", Material.status == "ACTIVE").order_by(Material.number)).scalars():
            if m.number in PROTECTED.get(tenant_code, set()):
                continue
            flags = mock.flag_attributes(m.category, m.material_group, m.description)
            if not flags:
                continue
            attrs = dict(m.attributes or {})
            missing = {k: v for k, v in flags.items() if k not in attrs}
            if not missing:
                continue
            if m.id in open_ids or m.number in open_numbers:
                counts["skippedOpenPo"] += 1
                continue
            if m.id in no_batch:
                counts["skippedStockWithoutBatch"] += 1
                continue
            m.attributes = {**attrs, **missing}
            audit.record(s, "MATERIAL", m.id, "BATCH_EXPIRY_FLAGS_SET", object_ref=m.number, before={k: attrs.get(k) for k in missing}, after=missing, actor=ACTOR,
                         reason=f"{LABEL}: batch / expiry management for a {m.category} material")
            counts["flagged"] += 1
            counts["expiryManaged"] += 1 if missing.get("expiryManaged") else 0
    return counts


# ---------------------------------------------------------------- 2 opening stock
def load_opening_stock(tenant_code: str, when=None) -> dict:
    from app.pic.tools import stock_opening_load

    path = mock.OUT_DIR / mock.FILE_NAME
    if not path.exists():
        return {"status": "FILE_MISSING", "file": str(path)}
    try:
        summary = stock_opening_load.load(tenant_code, path, when=when)
    except stock_opening_load.LoadRefused as refused:
        errors = refused.summary.get("errors", [])
        raise RuntimeError(f"opening stock {path.name} was refused for {tenant_code}: " + "; ".join(f"line {e['line']} {e.get('code')}" for e in errors[:10])) from refused
    finally:
        clock.set_pinned(None)
    return summary


# ---------------------------------------------------------------- 3 users
def ensure_users(tenant_id, tenant_code: str, password: str) -> dict:
    """Two mock INVENTORY_CONTROLLER users per plant and a RECEIVER for every plant without one (check-then-insert by e-mail, never changes a user)."""
    spec = SPECS[tenant_code]
    sc = Scenario(tenant_id, tenant_code=tenant_code, domain=spec["domain"], role_user={})
    with tenant_tx(tenant_id) as s:
        existing = list(s.execute(select(AppUser)).scalars())
        receivers = {p for u in existing if u.roles == ["RECEIVER"] and u.active for p in ((u.attributes or {}).get("plants") or [])}
    users = []
    for plant in spec["plants"]:
        attrs = {"plants": [plant], "mock": KEY}
        if spec["limit"] is not None:
            attrs["approval_limits"] = {"INVENTORY_APPROVE": spec["limit"]}
        for n in (1, 2):
            users.append((controller_email_local(plant, n), f"Mock Inventory Controller {plant}-{n}", ["INVENTORY_CONTROLLER"], attrs))
        if plant not in receivers:
            users.append((f"receiver.{plant.lower()}", f"Mock Receiver {plant}", ["RECEIVER"], {"plants": [plant], "mock": KEY}))
    return {"created": kit.create_users(sc, users, password), "controllers": 2 * len(spec["plants"]), "receiversAdded": sum(1 for u in users if u[2] == ["RECEIVER"])}


# ---------------------------------------------------------------- 4 rule values
def publish_rules(tenant_id, tenant_code: str, when=None) -> dict:
    """The KAC rule versions through the rule-versioning path (the checks and the audit event of POST /v1/admin/rules): a new effective-dated version per
    rule set, labelled in its description; an existing version label is left as it is."""
    if when:
        clock.set_pinned(when)
    published = []
    with tenant_tx(tenant_id) as s:
        have = {(r.key, r.version) for r in s.execute(select(RuleSet).where(RuleSet.key.in_(list(KAC_RULES)))).scalars()}
        for key, body in KAC_RULES.items():
            if (key, RULE_VERSION) in have:
                continue
            problems = ir.validate(key, body)
            if problems:
                raise Problem(422, "RULE_INVALID", f"{key}: " + "; ".join(problems), rule_ref=key, errors=problems)
            rule = RuleSet(tenant_id=tenant_id, key=key, version=RULE_VERSION, effective_from=RULE_EFFECTIVE, body=body, description=RULE_DESCRIPTION)
            s.add(rule)
            s.flush()
            audit.record(s, "RULE_SET", rule.id, "VERSION_CREATED", object_ref=f"{key}@{RULE_VERSION}", actor=ACTOR, reason=LABEL,
                         after={"key": key, "version": RULE_VERSION, "effective_from": RULE_EFFECTIVE.isoformat(), "body": body, "description": RULE_DESCRIPTION})
            published.append(f"{key}@{RULE_VERSION}")
    return {"published": published}


# ---------------------------------------------------------------- the pack
def _tenant_id(code: str):
    from app.pic.db import system_tx
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == code)).scalar_one()


def apply(tenant_code: str, password: str) -> dict:
    spec = SPECS.get(tenant_code)
    if spec is None:
        raise ValueError(f"{KEY} loads tenants {', '.join(SPECS)} only")
    tenant_id = _tenant_id(tenant_code)
    day, hour = spec["when"]
    when = at(day, hour)
    notes, counts = [], {}

    master = fill_master(tenant_id, tenant_code, when)
    notes.append(f"Master data ({LABEL}): checked {master['materialsChecked']} stock material(s); filled safety stock on {master['safetyFilled']}, standard price on "
                 f"{master['priceFilled']} ({master['priceNoSource']} without a price source), added {master['planningRowsAdded']} reorder point / max stock row(s)")
    flags = apply_flags(tenant_id, tenant_code, when)
    notes.append(f"Batch / expiry flags: {flags['flagged']} material(s) flagged ({flags['expiryManaged']} with expiry management); skipped {flags['skippedOpenPo']} with an "
                 f"open purchase-order line and {flags['skippedStockWithoutBatch']} with stock that has no batch")
    counts.update(master)
    counts.update({f"flags:{k}": v for k, v in flags.items()})

    documents = {}
    if tenant_code == "KAC":
        opening = load_opening_stock(tenant_code, when)
        r = opening.get("reconciliation", {})
        notes.append(f"Opening stock ({LABEL}): {opening.get('status')}; posted {opening.get('posted', 0)} balance(s) of {opening.get('materials', 0)} material(s) at "
                     f"{', '.join(opening.get('plants', []))}; {opening.get('alreadyLoaded', 0)} already loaded (the file leaves out the 20 balances of the inventory_ops pack), {opening.get('zeroQuantity', 0)} stock-out line(s) with nothing to post; "
                     f"file {(r.get('fileMinor') or 0) / 100:,.2f} vs PIC {(r.get('picMinor') or 0) / 100:,.2f} INR [{r.get('status')}]")
        counts.update({"openingBalancesPosted": opening.get("posted", 0), "openingAlreadyLoaded": opening.get("alreadyLoaded", 0),
                       "openingStockOuts": opening.get("zeroQuantity", 0), "openingBatchesRecorded": opening.get("batchesRecorded", 0)})
        documents["openingStock"] = {k: opening.get(k) for k in ("file", "sha256", "status", "posted", "postedValueMinor")}

    users = ensure_users(tenant_id, tenant_code, password)
    notes.append(f"Users ({LABEL}): {users['created']} created ({users['controllers']} inventory controllers: two per plant for {', '.join(spec['plants'])}; "
                 f"{users['receiversAdded']} receiver(s) for plants that had none)"
                 + ("; each controller may approve up to INR {:,.0f} (approval_limits.INVENTORY_APPROVE)".format(spec["limit"] / 100) if spec["limit"] else ""))
    counts["usersCreated"] = users["created"]

    if tenant_code == "KAC":
        rules = publish_rules(tenant_id, tenant_code, when)
        notes.append(f"Rule values ({LABEL}, pending client sign-off): published {', '.join(rules['published']) or 'nothing new'} effective {RULE_EFFECTIVE.isoformat()}")
        counts["ruleVersionsPublished"] = len(rules["published"])
    clock.set_pinned(None)
    return {"notes": notes, "counts": counts, "documents": documents, "label": LABEL}
