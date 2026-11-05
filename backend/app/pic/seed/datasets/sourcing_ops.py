"""D17 Strategic-sourcing datasets for the demo tenants KAC and AXN: MOCK (ILLUSTRATIVE SAMPLE; real values need the customer's data and sign-off).

The strategic-sourcing module (M05, flow F3) needs, before it can show a working sourcing function, events in every type and state, bids with a TCO
stack, clarifications, evaluations, awards with their hand-offs, should-cost models, indices and benchmarks. Until the customer supplies their own,
this pack fills each with clearly labelled mock values and builds the documents THROUGH THE REAL SERVICES (requisition, sourcing, auction, contract,
sourcing_templates, should_cost) with the business clock pinned to each step's time, so state machines, SoD, sealed-bid rules, ABAC, audit hash chains,
outbox events, contract drafts, savings initiatives and notifications behave as in production. Everything is deterministic (SHA-256 of keys, no random),
idempotent (a stage recorded in the audit trail is skipped) and traceable (``MOCK`` in titles, reasons, rule descriptions and
``data/erp_mock/KAC_SOURCING/README.md``).

KAC (first client; company code 1000, plants 1100 Hosur, 1200 Oragadam, 1300 Bidadi), 40 events created between 14 April 2025 and 31 October 2026:
  config     history rule versions back to 1 April 2025, SOURCING-POLICY / SOURCING-TCO values, bidder portal logins, MOCK twin snapshots, ten commodity
             should-cost models, index series, market / peer benchmarks, event templates
  events     every type (RFI, RFQ, RFP, reverse auction, multi-round, lot bidding) and every state (draft, published = scheduled opening, open, closed =
             waiting for the two-person opening, under evaluation, award pending, awarded, cancelled)
  awards     lowest cost, 60/40 split, non-lowest with rationale, capacity-constrained, lot, best value, auction; contracts, savings initiatives and
             regret letters through the consumers; four awards go on to active contracts (price validities, quota arrangements, source-list entries)
AXN: six non-signature events (Aug - Sep 2027); RFQ-2231, its bids, award and every existing AXN document are not touched.

Requires ``finance-ops`` (the last pack that leaves KAC's masters, users and FX series in their go-live state).
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuctionBid, AwardDecision, Bid, Contract, ContractLine, CostObject, Currency, EventLine, FxRate, IndexValue, InfoRecord, Material, PoLine, PriceBenchmark,
    PurchaseOrder, QuotaArrangement, RuleSet, SavingsInitiative, ShouldCostModel, SourceList, SourcingClarification, SourcingEvent, SourcingTemplate, Supplier,
    SupplierCategoryStatus, Tenant, TwinSnapshot,
)
from app.pic.platform import audit, clock
from app.pic.seed.axion import Scenario
from app.pic.seed.datasets import sourcing_ops_run as run
from app.pic.tools import sourcing_mock as mock

log = logging.getLogger(__name__)

KEY = "sourcing-ops"
VERSION = "1"
TITLE = "D17 Strategic-sourcing datasets for AXN and KAC: events in every type and state, bids and TCO, awards and hand-offs, should-cost models, indices (MOCK, ILLUSTRATIVE SAMPLE)"
TENANTS = ("AXN", "KAC")
CREATES_TENANT = False
READY = True
REQUIRES = {"finance-ops": "1"}

LABEL = mock.TAG
ACTOR = run.ACTOR
KAC, AXN = "KAC", "AXN"
DIRECT = ["ALU-DIECAST", "FERROUS-CASTINGS", "FORGINGS", "MACHINING", "RAW-MATERIALS", "FASTENERS", "RUBBER-SEALS", "ELECTRONICS", "PACKAGING"]
HIST_FROM, HIST_TO = date(2025, 4, 1), date(2026, 3, 31)
RULES_FROM = date(2026, 4, 1)

SPECS = {
    KAC: {"domain": "kaveri-auto.example", "owner": "category.head", "requester": "buyer.direct", "contract_manager": "contract.manager", "company": "1000",
          "plants": ["1100", "1200", "1300"], "no_contract": True, "cost_center": "1120"},
    AXN: {"domain": "axion.example", "owner": "category.manager", "requester": "buyer", "contract_manager": "contract.manager", "company": "1000",
          "plants": ["P100"], "no_contract": False, "cost_center": "4100"},
}
KAC_POLICY = {"minBidders": 3, "incompleteTcoNeedsRationale": True, "unverifiedCapacityNeedsRationale": True, "lineCategoryCheck": "ENFORCE", "leadTimeCheck": "ENFORCE", "clarificationCloseHours": 24, "maxExtensions": 12,
              "minOpenHours": {"RFI": 48, "RFQ": 72, "RFP": 120, "REVERSE_AUCTION": 2}}
KAC_TCO = {"carryingRatePct": "17", "costOfCapitalPct": "11.5", "copqPerDefectMinor": 400000,
           "dutyRates": {"72": "7.5", "7616": "10.0", "3926": "10.0", "85": "10.0", "40": "10.0", "73": "7.5"},
           "freightEstimatePct": {"EXW": "2.8", "FCA": "2.4", "FAS": "3.2", "FOB": "3.4"}}
SOURCE = "MOCK (sourcing_ops)"


def owner_for(category: str) -> str:
    """The event owner (and award proposer) of KAC: the category manager of the category; the head of category approves the award (four eyes)."""
    return "category.direct" if category in DIRECT else "category.indirect"


def plant_for(spec: dict, category: str) -> str:
    return spec["plants"][int(mock.unit("plant", category) * len(spec["plants"]))]


# ------------------------------------------------------------------------------------------------ reading what exists
def _read_masters(ctx: run.Ctx, rows: list[dict]) -> dict:
    """Suppliers, materials and prices the plan needs, read once."""
    categories = sorted({r["category"] for r in rows})
    out: dict = {"eligible": {}, "materials": {}, "po_materials": set(), "used": set(), "cost_center": None, "fx": None, "twin": set(), "model_codes": set()}
    with tenant_tx(ctx.tenant_id) as s:
        contract_suppliers = set(s.execute(select(Contract.supplier_id).where(Contract.number.like("KAC-%"))).scalars()) if ctx.spec["no_contract"] else set()
        # ordered in Python (code points), never by the database: the collation of a text ORDER BY differs between servers and would change which items are picked
        for supplier_id, code, category in sorted(s.execute(
                select(Supplier.id, Supplier.code, SupplierCategoryStatus.category).join(SupplierCategoryStatus, SupplierCategoryStatus.supplier_id == Supplier.id)
                .where(SupplierCategoryStatus.category.in_(categories), SupplierCategoryStatus.status.in_(("QUALIFIED", "PREFERRED")),
                       Supplier.status == "ACTIVE")).all(), key=lambda r: (r[1], r[2])):
            if supplier_id not in contract_suppliers:
                out["eligible"].setdefault(category, []).append(code)
        prices: dict = {}
        for material_id, price in s.execute(select(InfoRecord.material_id, InfoRecord.last_price_minor).order_by(InfoRecord.updated_at.nulls_first(), InfoRecord.created_at)).all():
            prices[material_id] = price
        for m in sorted(s.execute(select(Material).where(Material.category.in_(categories))).scalars(), key=lambda x: x.number):
            price = prices.get(m.id) or m.standard_price_minor
            if price is None and ctx.code == AXN:
                price = 45000
            if price and m.type in ("STOCK", "NON_STOCK", "SERVICE"):
                out["materials"].setdefault(m.category, []).append({"id": str(m.id), "number": m.number, "desc": m.description, "type": m.type, "uom": m.base_uom,
                                                                    "hsn": m.hsn_code, "price_minor": int(price), "group": m.material_group})
        out["po_materials"] = set(str(x) for x in s.execute(select(PoLine.material_id).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id)
                                                           .where(PurchaseOrder.status.notin_(("DRAFT", "CANCELLED")), PoLine.qty > 0)).scalars() if x)
        out["used"] = set(str(x) for x in s.execute(select(EventLine.material_id).join(SourcingEvent, SourcingEvent.id == EventLine.event_id)
                                                    .where(EventLine.material_id.is_not(None), SourcingEvent.title.not_like("MOCK %"))).scalars())
        # source determination at requisition approval marks a line SOURCED when a contract, quota, source list or info record covers the material at the plant:
        # such materials would never reach an event, so they are left out
        blocked = set()
        for model, column in ((InfoRecord, InfoRecord.plant), (SourceList, SourceList.plant), (QuotaArrangement, QuotaArrangement.plant)):
            blocked |= {(str(mid), plant) for mid, plant in s.execute(select(model.material_id, column)).all() if mid}
        blocked |= {(str(mid), plant) for mid, plant in s.execute(select(ContractLine.material_id, ContractLine.plant).join(Contract, Contract.id == ContractLine.contract_id)
                                                                   .where(Contract.status.in_(("ACTIVE", "EXPIRING")))).all() if mid}
        out["blocked"] = blocked
        centers = sorted(s.execute(select(CostObject.code).where(CostObject.type == "COST_CENTER")).scalars())
        out["cost_center"] = next((c for c in (ctx.spec["cost_center"], *centers) if c in centers), None)   # one the cost-object owner of the approval chain owns
        out["fx"] = {d: Decimal(r) for d, r in s.execute(select(FxRate.valid_from, FxRate.rate).where(FxRate.from_ccy == "USD", FxRate.to_ccy == "INR")).all()}
    return out


def _fx_on(fx: dict, day: date) -> Optional[Decimal]:
    days = [d for d in fx if d <= day]
    return fx[max(days)] if days else None


def resolve(ctx: run.Ctx, rows: list[dict], masters: dict) -> None:
    """Suppliers, materials, quantities and prices of every event (deterministic from the plan and the data in the database)."""
    spec = ctx.spec
    used_materials: set = set(masters["used"])
    chosen_suppliers: dict = {}
    for row in rows:
        key, category = row["key"], row["category"]
        elig = masters["eligible"].get(category, [])
        if not elig:
            raise RuntimeError(f"{key}: no qualified supplier for {category}")
        if row.get("cloneOf"):
            source = chosen_suppliers[row["cloneOf"]]
            invitees, bidders = list(source["invitees"]), list(source["bidders"])[: row["bidders"]]
        else:
            n_bid = min(row["bidders"], len(elig))
            n_inv = min(n_bid + 1, len(elig))
            offset = int(mock.unit("pick", key, category) * len(elig))
            picked = [elig[(offset + i) % len(elig)] for i in range(n_inv)]
            invitees, bidders = picked, picked[:n_bid]
        chosen_suppliers[key] = {"invitees": invitees, "bidders": bidders}
        extra_invitee = [c for c in invitees if c not in bidders]
        other = [c for cat, codes in masters["eligible"].items() if cat != category for c in codes if c not in invitees]
        n_lines = int(row.get("lines", 1))
        plant = plant_for(spec, category)
        pool = [m for m in masters["materials"].get(category, []) if m["id"] not in used_materials and (m["id"], plant) not in masters["blocked"]]
        if row["baselineMethod"] == "WEIGHTED_AVG":
            with_po = [m for m in pool if m["id"] in masters["po_materials"]]
            pool = with_po or pool
        lines = []
        for i in range(n_lines):
            usable = [m for m in pool if m["id"] not in {x["material_id"] for x in lines}]
            if not usable:
                raise RuntimeError(f"{key}: not enough {category} materials")
            m = usable[int(mock.unit("mat", key, i) * len(usable))]
            if spec["no_contract"]:        # KAC has hundreds of materials per category: one event per material; AXN has a handful, so its events may share one
                used_materials.add(m["id"])
            target_inr = Decimal(6_00_000 + int(mock.unit("value", key) * 30_00_000))
            if row.get("big"):
                target_inr = Decimal(65_00_000 + int(mock.unit("value", key) * 60_00_000))
            if n_lines > 1:
                target_inr = target_inr / n_lines
            price = Decimal(m["price_minor"]) / 100
            annual = max(Decimal(12), (target_inr / price).quantize(Decimal(1)))
            lines.append({"no": (i + 1) * 10, "material_id": m["id"], "material": m["number"], "desc": m["desc"], "type": m["type"], "uom": m["uom"], "hsn": m["hsn"],
                          "price_minor": m["price_minor"], "budget_minor": int(Decimal(m["price_minor"]) * Decimal("1.04")),
                          "annual_qty": str(annual), "monthly_qty": str((annual / 12).quantize(Decimal("0.001"))),
                          "lot": "L1" if n_lines == 3 and i < 2 else None, "pr_line": None, "pr": None})
        title = f"MOCK {key} {lines[0]['desc'][:70]}" + (f" and {n_lines - 1} more" if n_lines > 1 else "") + f" ({row['type'].replace('_', ' ').lower()})"
        res = {"title": title, "lines": lines, "invitees": invitees, "bidders": bidders, "scored": list(bidders[: row.get("bids", len(bidders))]),
               "bias": {}, "capacity": {}, "importers": {}, "lotTerms": n_lines == 3 and row["outcome"] in ("AWARD_LOT",),
               "uninvitedBidder": other[0] if other else bidders[-1], "lateBidder": extra_invitee[0] if extra_invitee else bidders[-1]}
        commodity = row.get("commodity")
        model = next((m for m in mock.models() if m["commodity"] == commodity), None) if commodity else mock.model_by_category(category)
        res["model"] = model if (model and n_lines == 1 and spec.get("models")) else None
        if row["outcome"] == "AWARD_CAPACITY":
            res["bias"][bidders[0]], res["capacity"][bidders[0]] = -0.12, 0.55
        if row["outcome"] == "AWARD_DISQ":
            res["disqualified"], res["gateFail"] = bidders[0], bidders[1]
            res["bias"][bidders[0]], res["bias"][bidders[1]] = -0.12, -0.08
        if row.get("import"):
            rate = _fx_on(masters["fx"], date.fromisoformat(row["created"]))
            if rate is None:
                raise RuntimeError(f"{key}: no USD rate on {row['created']}")
            res["import"] = True
            res["importers"] = {bidders[0]: {"rate": str(rate), "hs": None}, bidders[1]: {"rate": str(rate), "hs": "8479"}}
            res["bias"][bidders[1]] = 0.08
        st = ctx.st.setdefault(key, {})
        st["res"] = res


def dump_plan(ctx: run.Ctx, rows: list[dict]) -> dict:
    return {r["key"]: {**ctx.st[r["key"]]["res"], "model": (ctx.st[r["key"]]["res"]["model"] or {}).get("code")} for r in rows}


def load_plan(ctx: run.Ctx, events: dict) -> None:
    models = {m["code"]: m for m in mock.models()}
    for key, res in events.items():
        ctx.st.setdefault(key, {})["res"] = {**res, "model": models.get(res.get("model"))}


def ensure_materials(ctx: run.Ctx, rows: list[dict], masters: dict) -> int:
    """A category with fewer free items than its events need (a small demo tenant: AXN has two die-cast items, both under contract) gets MOCK items
    ``SRCMOCK-<category>-nnn`` with a standard price, so the requirement lines reach the events as OPEN. KAC has hundreds of items and gets none."""
    spec = ctx.spec
    need: dict = {}
    for row in rows:
        lines = int(row.get("lines", 1))
        need[row["category"]] = need.get(row["category"], 0) + lines if spec["no_contract"] else max(need.get(row["category"], 0), lines)
    made = 0
    with tenant_tx(ctx.tenant_id) as s:
        have = set(s.execute(select(Material.number).where(Material.number.like("SRCMOCK-%"))).scalars())
        for category, count in sorted(need.items()):
            plant = plant_for(spec, category)
            free = [m for m in masters["materials"].get(category, []) if m["id"] not in masters["used"] and (m["id"], plant) not in masters["blocked"]]
            if len(free) >= count:
                continue
            sample = next(iter(masters["materials"].get(category, [])), None)
            for i in range(1, count - len(free) + 1):
                number = f"SRCMOCK-{category[:6]}-{i:03d}"
                if number in have:
                    continue
                price = 9000 + int(mock.unit("mock-item", category, i) * 52000)
                s.add(Material(tenant_id=ctx.tenant_id, number=number, description=f"MOCK sourcing item {category} {i:03d}", type="STOCK", material_group=category,
                               category=category, base_uom="EA", valuation_class="3000", hsn_code=(sample or {}).get("hsn") or "73181500", gst_rate=Decimal(18),
                               mrp_type="ND", standard_price_minor=price, status="ACTIVE", erp_synced=True, attributes={"mock": KEY}))
                made += 1
        if made:
            s.flush()
            audit.record(s, "MATERIAL", uuid.uuid5(uuid.NAMESPACE_URL, f"{KEY}:materials:{ctx.code}"), "MOCK_ITEMS_ADDED", object_ref="SRCMOCK", actor=ACTOR, reason=LABEL,
                         after={"items": made})
    return made


def requisition_groups(ctx: run.Ctx, rows: list[dict], masters: dict) -> dict:
    """One approved requisition per category and quarter holds the lines of the events of that group (a line is OPEN until its event takes it)."""
    groups: dict = {}
    for row in rows:
        created = date.fromisoformat(row["created"])
        group = f"PR:{row['category']}:{created.year}Q{(created.month - 1) // 3 + 1}"
        groups.setdefault(group, {"category": row["category"], "events": [], "first": created})
        groups[group]["events"].append(row)
        groups[group]["first"] = min(groups[group]["first"], created)
    for group, info in groups.items():
        n = sum(len(ctx.st[r["key"]]["res"]["lines"]) for r in info["events"])
        cap = Decimal(1_80_000 * 100) / n
        k = 0
        for row in info["events"]:
            created = date.fromisoformat(row["created"])
            for line in ctx.st[row["key"]]["res"]["lines"]:
                k += 1
                line["pr"], line["pr_line"] = group, k * 10
                line["pr_qty"] = str(max(1, min(50, int(cap // Decimal(line["price_minor"])))))
                line["need_date"] = (created + timedelta(days=180)).isoformat()
        info["lines"] = [line for row in info["events"] for line in ctx.st[row["key"]]["res"]["lines"]]
    return groups


def plan_requisitions(ctx: run.Ctx, groups: dict, masters: dict) -> None:
    spec = ctx.spec
    for group, info in groups.items():
        category = info["category"]
        plant = plant_for(spec, category)
        created = info["first"]
        lines = []
        for line in info["lines"]:
            entry = {"item_type": "MATERIAL", "purchase_type": line["type"], "material": line["material"], "qty": line["pr_qty"], "price_est_minor": line["price_minor"],
                     "need_date": line["need_date"]}
            if line["type"] == "STOCK":
                entry["storage_location"] = "0001"
            else:
                entry.update({"account_assignment_type": "COST_CENTER", "account_assignment_code": masters["cost_center"]})
            lines.append(entry)

        def create(s, st, lines=lines, plant=plant, group=group):
            from app.pic.services import requisition
            ctx.call()
            pr = requisition.create(s, origin="MANUAL", purpose_code="ANNUAL_SOURCING", purpose_text=f"MOCK sourcing demand {group}", plant=plant, lines=lines)
            ctx.call()
            requisition.submit(s, pr)
            return {"id": str(pr.id), "number": pr.number}
        ctx.st.setdefault(group, {})
        ctx.step(group, "create", run.ist(created - timedelta(days=4), 9, 0), spec["requester"], create)
        ctx.step(group, "approve", run.ist(created - timedelta(days=3), 11, 0), None, None, kind="approve")


# ------------------------------------------------------------------------------------------------ configuration
def once(ctx: run.Ctx, name: str, when, fn) -> None:
    stage = f"config:{name}"
    if stage in ctx.done:
        return
    clock.set_pinned(when)
    result = fn() or {}
    with tenant_tx(ctx.tenant_id) as s:
        audit.record(s, "DATASET", uuid.uuid5(uuid.NAMESPACE_URL, f"{KEY}:{ctx.code}:{stage}"), "SOURCING_OPS_STAGE", object_ref=stage, after=result, actor=ACTOR, reason=LABEL)
    ctx.done[stage] = result


def history_rules(ctx: run.Ctx) -> dict:
    """KAC's rule versions are effective from 1 April 2026; the events start in April 2025. Every open-ended version effective on 2026-04-01 gets a copy
    '<version>-HIST-MOCK' effective 2025-04-01 to 2026-03-31, so the services resolve the same rules for the historical dates."""
    copied = 0
    with tenant_tx(ctx.tenant_id) as s:
        have = {(r.key, r.version) for r in s.execute(select(RuleSet)).scalars()}
        for rs in s.execute(select(RuleSet).where(RuleSet.effective_from == RULES_FROM, RuleSet.effective_to.is_(None))).scalars().all():
            version = f"{rs.version}-HIST-MOCK"
            if (rs.key, version) in have:
                continue
            s.add(RuleSet(tenant_id=ctx.tenant_id, key=rs.key, version=version, effective_from=HIST_FROM, effective_to=HIST_TO, company_code=rs.company_code, plant=rs.plant,
                          category=rs.category, purchase_type=rs.purchase_type, supplier_group=rs.supplier_group, body=rs.body,
                          description=f"{LABEL}: copy of {rs.key}@{rs.version} so the history events of April 2025 - March 2026 resolve the same rule"))
            copied += 1
        s.flush()
        audit.record(s, "RULE_SET", uuid.uuid5(uuid.NAMESPACE_URL, f"{KEY}:hist-rules:{ctx.code}"), "HISTORY_COPIED", object_ref="HIST-MOCK", actor=ACTOR,
                     reason=LABEL, after={"copied": copied, "from": HIST_FROM.isoformat(), "to": HIST_TO.isoformat()})
    return {"historyRules": copied}


def sourcing_rules(ctx: run.Ctx) -> dict:
    """MOCK SOURCING-POLICY / SOURCING-TCO values of KAC (effective a day after the defaults so they win; for the history period too)."""
    from app.pic.seed.datasets.finance_ops import publish_rule

    published = []
    desc = f"{LABEL}: pending client sign-off. See data/erp_mock/KAC_SOURCING/README.md."
    with tenant_tx(ctx.tenant_id) as s:
        for key, body in (("SOURCING-POLICY", KAC_POLICY), ("SOURCING-TCO", KAC_TCO)):
            for version, start in (("2025.2-KAC", date(2025, 4, 2)), ("2026.2-KAC", date(2026, 4, 2))):
                if publish_rule(s, ctx.tenant_id, key, version, start, body, desc):
                    published.append(f"{key}@{version}")
                    if start < RULES_FROM:
                        rs = s.execute(select(RuleSet).where(RuleSet.key == key, RuleSet.version == version)).scalar_one()
                        rs.effective_to = HIST_TO
    return {"rules": published}


def budgets(ctx: run.Ctx, cost_center: str) -> dict:
    """The requisitions of service and non-stock items are checked against a cost-centre budget of their fiscal year (BP M04): KAC has none loaded for the
    historical years, so a MOCK soft-control budget of INR 5 crore per year is loaded for the cost centre the demand is booked to."""
    from app.pic.models import Budget

    added = 0
    with tenant_tx(ctx.tenant_id) as s:
        have = {(b.cost_object_code, b.fiscal_year) for b in s.execute(select(Budget).where(Budget.cost_object_type == "COST_CENTER")).scalars()}
        for fiscal_year in ("2025-26", "2026-27", "2027-28"):
            if (cost_center, fiscal_year) not in have:
                s.add(Budget(tenant_id=ctx.tenant_id, cost_object_type="COST_CENTER", cost_object_code=cost_center, fiscal_year=fiscal_year, control="SOFT",
                             amount_minor=5_00_00_000 * 100, committed_minor=0, consumed_minor=0))
                added += 1
    return {"budgets": added}


def bidder_logins(ctx: run.Ctx, codes: set) -> dict:
    from app.pic.platform.auth import hash_password

    added = 0
    with tenant_tx(ctx.tenant_id) as s:
        have = set(s.execute(select(AppUser.email)).scalars())
        hashed = hash_password(ctx.password)
        suppliers = {x.code: x for x in s.execute(select(Supplier).where(Supplier.code.in_(sorted(codes)))).scalars()}
        for code in sorted(codes):
            email = run.bidder_email(ctx, code)
            if email in have or code not in suppliers:
                continue
            s.add(AppUser(tenant_id=ctx.tenant_id, email=email, full_name=f"{suppliers[code].legal_name} - sales / tenders (MOCK login)", password_hash=hashed,
                          roles=["SUPPLIER_USER"], attributes={"mock": KEY}, supplier_id=suppliers[code].id, mfa_enrolled=True))
            added += 1
    return {"bidderLogins": added}


def twin_snapshots(ctx: run.Ctx, pairs: set, capacity: dict) -> dict:
    added = 0
    with tenant_tx(ctx.tenant_id) as s:
        suppliers = {x.code: x.id for x in s.execute(select(Supplier)).scalars()}
        have = {(sid, cat) for sid, cat in s.execute(select(TwinSnapshot.supplier_id, TwinSnapshot.category)).all()}
        for code, category in sorted(pairs):
            sid = suppliers[code]
            if (sid, category) in have:
                continue
            t = mock.twin_terms(code, category)
            s.add(TwinSnapshot(tenant_id=ctx.tenant_id, supplier_id=sid, category=category, capability={"note": LABEL, "processes": [category]}, evidence_level=t["evidence_level"],
                               free_capacity_per_month=capacity.get(category, Decimal(100000)), trust_score=t["trust"], late_delivery_prob=t["late"], ppm=t["ppm"],
                               lead_time_days=t["lead_time_days"], as_of=date(2026, 10, 1), source="SEEDED", synced_at=None, model_version="mock-sourcing-ops-v1"))
            added += 1
    return {"twinSnapshots": added}


def indices(ctx: run.Ctx) -> dict:
    with tenant_tx(ctx.tenant_id) as s:
        have = {(c, d) for c, d in s.execute(select(IndexValue.index_code, IndexValue.as_of)).all()}
        for code, day, value, unit_ in mock.index_series():
            if (code, day) not in have:
                s.add(IndexValue(tenant_id=ctx.tenant_id, index_code=code, as_of=day, value=value, unit=unit_, source="IMPORT", source_ref=mock.SOURCE_REF))
        s.flush()
        n = s.execute(select(func.count()).select_from(IndexValue).where(IndexValue.source_ref == mock.SOURCE_REF)).scalar()
    return {"indexValues": n}


def should_cost_models(ctx: run.Ctx) -> dict:
    from app.pic.services import should_cost

    saved = 0
    with ctx.sc.act(ctx.spec["owner"], run.ist(date(2025, 4, 8), 9, 0)) as s:
        have = {m.code for m in s.execute(select(ShouldCostModel)).scalars()}
        for model in mock.models():
            if model["code"] in have:
                continue
            ctx.call()
            should_cost.save_model(s, code=model["code"], commodity=model["commodity"], title=f"MOCK {model['title']}", spec=model["spec"], index_code=model["indexCode"],
                                   note=f"{LABEL}: illustrative cost structure of {model['commodity']}; the category team replaces the inputs with its own cost data")
            saved += 1
    return {"shouldCostModels": saved}


def benchmarks(ctx: run.Ctx, rows: list[dict]) -> dict:
    """MARKET quote per sourced material (97 % of the last price a month before the event) and PEER price per category (median last price, two dates)."""
    added = 0
    with tenant_tx(ctx.tenant_id) as s:
        if s.execute(select(PriceBenchmark.id).where(PriceBenchmark.source.like(f"{SOURCE}%")).limit(1)).first():
            return {"benchmarks": 0}
        for row in rows:
            for line in ctx.st[row["key"]]["res"]["lines"]:
                s.add(PriceBenchmark(tenant_id=ctx.tenant_id, category=row["category"], material_id=uuid.UUID(line["material_id"]), kind="MARKET",
                                     as_of=date.fromisoformat(row["created"]) - timedelta(days=30), price_minor=int(line["price_minor"] * 0.97), uom=line["uom"],
                                     source=f"{SOURCE} market quote", note=f"{LABEL}: 97 % of the last price"))
                added += 1
        seen: set = set()
        for row in rows:
            if row["category"] in seen:
                continue
            seen.add(row["category"])
            prices = sorted(l["price_minor"] for r in rows if r["category"] == row["category"] for l in ctx.st[r["key"]]["res"]["lines"])
            median = prices[len(prices) // 2]
            first = ctx.st[row["key"]]["res"]["lines"][0]
            for as_of, factor in ((date(2025, 4, 1), 0.99), (date(2026, 4, 1), 1.03)):
                s.add(PriceBenchmark(tenant_id=ctx.tenant_id, category=row["category"], material_id=None, kind="PEER", as_of=as_of, price_minor=int(median * factor),
                                     uom=first["uom"], source=f"{SOURCE} peer survey", note=f"{LABEL}: median of the sourced items x {factor}"))
                added += 1
    return {"benchmarks": added}


def templates(ctx: run.Ctx) -> dict:
    from app.pic.services import sourcing_templates

    saved = 0
    base = run.criteria_for({"type": "RFQ"})
    with ctx.sc.act(ctx.spec["owner"], run.ist(date(2025, 4, 8), 10, 0)) as s:
        have = {t.code for t in s.execute(select(SourcingTemplate)).scalars()}
        wanted = [
            ("RFQ-DIRECT-MATERIAL", "RFQ for direct material (price 50, quality 20, delivery 15, technical 15)", "RFQ", None,
             {"criteria": base, "constraints": {"max_suppliers": 2, "max_share": "0.60", "min_share": "0.20"}, "scoring_method": "LOWEST_RATIO", "baseline_method": "LAST_PRICE",
              "invitee_filter": {"maxRiskScore": 60, "max": 5}, "savings_target_pct": "3.0"}),
            ("RFP-SERVICES", "RFP for services (technical 40 with a gate of 50)", "RFP", None,
             {"criteria": run.criteria_for({"type": "RFP"}), "constraints": {"max_suppliers": 1, "max_share": "1", "min_share": "0"}, "scoring_method": "MIN_MAX",
              "baseline_method": "BUDGET", "min_bidders": 3}),
            ("AUCTION-STANDARD", "Reverse auction (price 70, scorecard quality and delivery)", "REVERSE_AUCTION", None,
             {"criteria": run.criteria_for({"type": "REVERSE_AUCTION"}), "scoring_method": "LOWEST_RATIO", "baseline_method": "LAST_PRICE", "auction": {"minDecrementPct": "0.5"}}),
        ]
        for code, name, event_type, category, payload in wanted:
            if code in have:
                continue
            ctx.call()
            sourcing_templates.save(s, code=code, name=f"MOCK {name}", event_type=event_type, category=category, payload=payload)
            saved += 1
    return {"templates": saved}


# ------------------------------------------------------------------------------------------------ the pack
def apply(tenant_code: str, password: str) -> dict:
    spec = SPECS.get(tenant_code)
    if spec is None:
        raise ValueError(f"{KEY} loads tenants {', '.join(SPECS)} only")
    started = time.monotonic()
    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == tenant_code)).scalar_one()
    role_user = None
    if tenant_code == KAC:
        from app.pic.seed.datasets import finance_ops
        role_user = finance_ops._kac_roles()
    if tenant_code == KAC:
        spec = {**spec, "models": True, "owner_for": owner_for, "evaluators_for": lambda cat: ["quality.inspector", "category.head"],
                "openers_for": lambda cat: [owner_for(cat), "category.head"]}
    else:
        spec = {**spec, "models": False, "owner_for": lambda cat: "category.manager" if cat == "ALU-DIECAST" else "category.head",
                "evaluators_for": lambda cat: ["quality.engineer", "category.head" if cat == "ALU-DIECAST" else "category.manager"],
                "openers_for": lambda cat: ["category.manager", "category.head"]}
    sc = Scenario(tenant_id, tenant_code=tenant_code, domain=spec["domain"], role_user=role_user)
    rows = mock.kac_plan() if tenant_code == KAC else mock.axn_plan()
    ctx = run.Ctx(tenant_id=tenant_id, code=tenant_code, password=password, sc=sc, spec=spec, plan=rows)
    try:
        run.load_done(ctx)
        masters = _read_masters(ctx, rows)
        saved = ctx.done.get("config:plan")
        if saved:
            load_plan(ctx, saved["events"])         # a resumed or repeated run reads the plan it made first (data the pack's own awards changed would pick other items)
        else:
            if ensure_materials(ctx, rows, masters):
                masters = _read_masters(ctx, rows)
            resolve(ctx, rows, masters)
        groups = requisition_groups(ctx, rows, masters)
        if not saved:
            once(ctx, "plan", run.ist(date(2026, 10, 31), 10, 55), lambda: {"events": dump_plan(ctx, rows)})
        if tenant_code == KAC:
            once(ctx, "history-rules", run.ist(date(2026, 10, 31), 11, 0), lambda: history_rules(ctx))
            once(ctx, "sourcing-rules", run.ist(date(2026, 10, 31), 11, 10), lambda: sourcing_rules(ctx))
            once(ctx, "indices", run.ist(date(2026, 10, 31), 11, 20), lambda: indices(ctx))
            once(ctx, "models", run.ist(date(2025, 4, 8), 9, 0), lambda: should_cost_models(ctx))
            once(ctx, "templates", run.ist(date(2025, 4, 8), 10, 0), lambda: templates(ctx))
            once(ctx, "budgets", run.ist(date(2026, 10, 31), 11, 25), lambda: budgets(ctx, masters["cost_center"]))
        codes = {c for r in rows for c in ctx.st[r["key"]]["res"]["invitees"]} | {ctx.st[r["key"]]["res"]["uninvitedBidder"] for r in rows if r.get("uninvited")} \
            | {ctx.st[r["key"]]["res"]["lateBidder"] for r in rows if r.get("lateBid")}
        once(ctx, "bidder-logins", run.ist(date(2026, 10, 31), 11, 30), lambda: bidder_logins(ctx, codes))
        pairs = {(c, r["category"]) for r in rows for c in ctx.st[r["key"]]["res"]["invitees"]}
        monthly = {}
        for r in rows:
            monthly[r["category"]] = max(monthly.get(r["category"], Decimal(0)), max(Decimal(l["monthly_qty"]) for l in ctx.st[r["key"]]["res"]["lines"]))
        once(ctx, "twin", run.ist(date(2026, 10, 31), 11, 40), lambda: twin_snapshots(ctx, pairs, {k: (v * 6).quantize(Decimal(1)) for k, v in monthly.items()}))
        once(ctx, "benchmarks", run.ist(date(2026, 10, 31), 11, 50), lambda: benchmarks(ctx, rows))
        plan_requisitions(ctx, groups, masters)
        for row in rows:
            run.plan_event(ctx, row)
        for day in sorted(ctx.relay_days):
            ctx.step("relay", f"relay-{day.isoformat()}", run.ist(day, 23, 30), None, None, kind="relay")
        run.execute(ctx)
        summary = summarise(ctx, tenant_code)
        summary["serviceCalls"] = ctx.calls
        summary["stepsSkipped"] = ctx.skipped
        summary["seconds"] = round(time.monotonic() - started, 1)
        summary["config"] = {k.removeprefix("config:"): v for k, v in ctx.done.items() if k.startswith("config:")}
        summary["notes"] = [f"{tenant_code}: {summary['counts']['events']} MOCK events {summary['eventsByState']}; {ctx.calls} service-driven calls in {summary['seconds']} s"]
        return summary
    finally:
        clock.set_pinned(None)


def summarise(ctx: run.Ctx, tenant_code: str) -> dict:
    with tenant_tx(ctx.tenant_id) as s:
        events = s.execute(select(SourcingEvent).where(SourcingEvent.title.like("MOCK %"))).scalars().all()
        ids = [e.id for e in events]
        by_state: dict = {}
        by_type: dict = {}
        for e in events:
            by_state[e.status] = by_state.get(e.status, 0) + 1
            by_type[e.type] = by_type.get(e.type, 0) + 1

        def count(model, *where):
            return s.execute(select(func.count()).select_from(model).where(*where)).scalar()
        contracts = s.execute(select(Contract).where(Contract.source_event_id.in_(ids))).scalars().all() if ids else []
        counts = {
            "events": len(events), "bids": count(Bid, Bid.event_id.in_(ids)) if ids else 0, "auctionBids": count(AuctionBid, AuctionBid.event_id.in_(ids)) if ids else 0,
            "awardDecisions": count(AwardDecision, AwardDecision.event_id.in_(ids)) if ids else 0,
            "clarifications": count(SourcingClarification, SourcingClarification.event_id.in_(ids)) if ids else 0,
            "contracts": len(contracts), "contractsActive": sum(1 for c in contracts if c.status in ("ACTIVE", "EXPIRING")),
            "quotaArrangements": count(QuotaArrangement, QuotaArrangement.source_event_id.in_(ids)) if ids else 0,
            "savingsInitiatives": count(SavingsInitiative, SavingsInitiative.source_event_id.in_(ids)) if ids else 0,
            "shouldCostModels": count(ShouldCostModel), "benchmarks": count(PriceBenchmark, PriceBenchmark.source.like(f"{SOURCE}%")),
            "templates": count(SourcingTemplate), "indexValues": count(IndexValue, IndexValue.source_ref == mock.SOURCE_REF),
            "sourceListEntries": count(SourceList, SourceList.supplier_id.in_([c.supplier_id for c in contracts]), SourceList.valid_from >= min([c.valid_from for c in contracts]))
            if contracts else 0,
        }
        by_bid: dict = {}
        if ids:
            for status, n in s.execute(select(Bid.status, func.count()).where(Bid.event_id.in_(ids)).group_by(Bid.status)).all():
                by_bid[status] = n
    return {"counts": counts, "eventsByState": by_state, "eventsByType": by_type, "bidsByStatus": by_bid, "tenant": tenant_code}
