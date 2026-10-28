"""Legacy supplier_twin → PIC migration (Delivery Plan §15, "current demo data").

Each legacy BUYER tenant becomes a PIC tenant. Loads follow the §15 approach per object:

  masters    suppliers (profile → screening and category status), materials with opening stock and the
             full stock-movement history, supplier finished-goods catalogue
  open docs  requisitions (order_requests), sourcing events (requests quoted more than once), purchase
             orders with the legacy number as external reference, ASNs, goods receipts
  history    paid invoices and their payments (read-only), spend lines with maverick flags

Every migrated row keeps its legacy id and is audited as MIGRATED. The open items then continue
through the same services the API uses, so the rules see the legacy data:

  F8  every supplier screened; compliance-flagged suppliers put into requalification
  F5  the PO still pending approval is validated and routed for approval
  F7  pending invoices captured → duplicate check → 3-way match → exceptions
  F9  a free-text item bought repeatedly is promoted to a material master request
  F1  consumption forecast + safety stock → MRP run → planned order converted to a requisition (F2)

`migrate()` returns a reconciliation report: legacy vs PIC counts and values, the control findings on
the legacy data, and what the live run produced.
"""
import hashlib
import json
import logging
import re
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import func, select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, Asn, AsnLine, Bid, BidLine, CatalogueItem, DemandElement, EventLine, GoodsReceipt, GrLine, Invitee, Invoice,
    InvoiceException, InvoiceLine, Material, MaterialRequest, MrpException, Payment, PlannedOrder, PoLine, PrLine, PurchaseOrder,
    Qualification, Requisition, SourcingEvent, SpendLine, Stock, StockMovement, StorageLocation, Supplier, SupplierBankAccount,
    SupplierCategoryStatus, Task, Tenant,
)
from app.pic.platform import audit, clock, crypto, workflow
from app.pic.platform.auth import hash_password
from app.pic.platform.core import link, next_number
from app.pic.seed import reference
from app.pic.seed.axion import ROLE_USER, Scenario
from app.pic.worker import tick

log = logging.getLogger("pic.seed.legacy")

SOURCE = "supplier_twin"
NS = uuid.UUID("5b0e7c1a-2f4d-5e6b-9a8c-7d1e2f3a4b5c")  # deterministic ids for legacy references
TENANT_CODES = {"Global Manufacturing Corp": "GMC", "Dummy Buyer": "DBY"}
COMPANY, PLANT, COST_CENTER = "1000", "P100", "1000"
DEFAULT_LEAD_DAYS = 14  # lead time quoted for machined parts in the legacy quotations
TEST_MARKERS = ("TEST", "E2E", "DUM")

ROSTER = [
    # local part, title, roles, ABAC attributes — every approval role the rule packs route to
    ("admin", "Tenant Administrator", ["TENANT_ADMIN"], {}),
    ("mrp.controller", "MRP Controller", ["MRP_CONTROLLER"], {"plants": [PLANT]}),
    ("requester", "Requester", ["REQUESTER"], {"cost_objects": [f"COST_CENTER:{COST_CENTER}"], "plants": [PLANT]}),
    ("plant.controller", "Plant Controller", ["COST_OBJECT_OWNER"], {"plants": [PLANT], "cost_objects": [f"COST_CENTER:{COST_CENTER}"]}),
    ("ops.head", "Head of Operations", ["DEPT_HEAD"], {"plants": [PLANT], "cost_objects": [f"COST_CENTER:{COST_CENTER}"]}),
    ("buyer", "Buyer", ["BUYER"], {"plants": [PLANT]}),
    ("buyer.lead", "Lead Buyer", ["BUYER"], {"plants": [PLANT]}),
    ("category.manager", "Category Manager", ["CATEGORY_MANAGER"], {"categories": ["*"]}),
    ("category.head", "Head of Category Management", ["CATEGORY_MANAGER"], {"categories": ["*"]}),
    ("procurement.head", "Head of Procurement", ["PROCUREMENT_HEAD"], {}),
    ("cpo", "Chief Procurement Officer", ["CPO"], {}),
    ("finance.controller", "Finance Controller", ["FINANCE_CONTROLLER"], {}),
    ("finance.controller2", "Deputy Finance Controller", ["FINANCE_CONTROLLER"], {}),
    ("legal", "Legal Counsel", ["LEGAL"], {}),
    ("contract.manager", "Contract Manager", ["CONTRACT_MANAGER"], {}),
    ("supplier.manager", "Supplier Manager", ["SUPPLIER_MANAGER"], {"categories": ["*"]}),
    ("mdm.purchasing", "MDM Steward – Purchasing", ["MDM_STEWARD"], {"steward_domains": ["PURCHASING"]}),
    ("mdm.quality", "MDM Steward – Quality", ["MDM_STEWARD"], {"steward_domains": ["QUALITY"]}),
    ("mdm.finance", "MDM Steward – Finance", ["MDM_STEWARD"], {"steward_domains": ["FINANCE"]}),
    ("mdm.plant", "MDM Steward – Plant", ["MDM_STEWARD"], {"steward_domains": ["PLANT"]}),
    ("receiver", "Goods Receiver", ["RECEIVER"], {"plants": [PLANT]}),
    ("quality.inspector", "Quality Inspector", ["QUALITY_INSPECTOR"], {"plants": [PLANT]}),
    ("service.owner", "Service Owner", ["SERVICE_OWNER"], {"cost_objects": [f"COST_CENTER:{COST_CENTER}"]}),
    ("ap.clerk", "Accounts Payable Clerk", ["AP_CLERK"], {}),
]
# People named in legacy logs ("Name (Title)") take the roster slot their title describes.
PEOPLE = [(r"receiv", "receiver"), (r"materials", "mrp.controller"), (r"\bqc\b|quality", "quality.inspector"), (r"production", "requester")]

CLASSIFIER = [
    # keywords → category, material group (spend classification run, §15)
    (("enclosure", "housing", "machined", "5-axis", "cnc", "flange", "shaft"), "AERO-MACHINED", "AERO-MACH"),
    (("injector", "nozzle", "cryogenic", "valve"), "AERO-PROPULSION", "AERO-PROP"),
    (("fastener", "bolt", "screw"), "FASTENERS", "FASTENERS"),
]
UOM = {"units": "EA", "unit": "EA", "pcs": "EA", "sets": "SET", "kg": "KG", "boxes": "BOX", "sheets": "SHT", "drums": "DRM"}
MOVEMENT = {"GOODS_IN": "101", "GOODS_RECEIPT": "101", "GOODS_OUT": "201"}


# ---------------------------------------------------------------- helpers
def tenant_code(name: str) -> str:
    return TENANT_CODES.get(name) or ("".join(w[0] for w in re.findall(r"[A-Za-z]+", name)).upper()[:6] or "LEG")


def ts(value) -> Optional[datetime]:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def day(value) -> Optional[date]:
    stamp = ts(value)
    return stamp.astimezone(clock.IST).date() if stamp else None


def legacy_ref(table: str, legacy_id: str) -> uuid.UUID:
    return uuid.uuid5(NS, f"{table}:{legacy_id}")


def classify(text: str) -> tuple[str, str, Decimal]:
    lowered = (text or "").lower()
    for words, category, group in CLASSIFIER:
        if any(w in lowered for w in words):
            return category, group, Decimal("0.900")
    return "UNCLASSIFIED", "UNCLASSIFIED", Decimal("0.300")


def is_test(*values) -> bool:
    return any(m in str(v or "").upper() for v in values for m in TEST_MARKERS)


def invoice_no(legacy_id: str) -> str:
    """Legacy invoice ids are either INV-… numbers or UUIDs; UUIDs get a short LEG- number."""
    return legacy_id if legacy_id.startswith("INV-") and len(legacy_id) <= 30 else f"LEG-{legacy_id[:8].upper()}"


def slug(text: str, size: int) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", (text or "GENERAL").upper()).strip("-")[:size]


def money(amount: float) -> str:
    return f"{Decimal(str(amount or 0)):,.2f}"


class Legacy:
    """Indexed view of a legacy snapshot."""

    def __init__(self, snapshot: dict):
        t = snapshot["tables"]
        self.snapshot = snapshot
        self.tenants = {r["id"]: r for r in t["tenants"]}
        self.users = t["users"]
        self.profiles = {r["tenant_id"]: r for r in t.get("supplier_profiles", [])}
        self.requests = t["order_requests"]
        self.quotes = sorted(t["quotations"], key=lambda r: r["created_at"])
        self.pos = sorted(t["purchase_orders"], key=lambda r: r["created_at"])
        self.po_by_id = {r["id"]: r for r in self.pos}
        self.approvals = sorted(t.get("po_approvals", []), key=lambda r: r["created_at"])
        self.asns = t.get("advance_ship_notices", [])
        self.grs = t.get("goods_receipts", [])
        self.invoices = sorted(t["sales_invoices"], key=lambda r: r["created_at"])
        self.payments = {r["invoice_id"]: r for r in t["payments"]}
        self.items = t["inventory_items"]
        self.moves = sorted(t["stock_transactions"], key=lambda r: r["created_at"])
        self.messages = t.get("negotiation_messages", [])

    def buyers(self) -> list[dict]:
        active = {r["tenant_id"] for r in self.pos} | {r["tenant_id"] for r in self.requests} | {r["tenant_id"] for r in self.items}
        return [r for r in self.tenants.values() if r["type"] == "BUYER" and r["id"] in active]

    def cutover(self) -> datetime:
        last = max(ts(r["created_at"]) for table in self.snapshot["tables"].values() for r in table if r.get("created_at"))
        return clock.at_ist(last.astimezone(clock.IST).date() + timedelta(days=1), 18)


class Ctx:
    """What one tenant's migration has created so far, keyed by legacy id."""

    def __init__(self, legacy: Legacy, buyer: dict, fx: Decimal):
        self.legacy, self.buyer, self.fx = legacy, buyer, fx
        self.code = tenant_code(buyer["name"])
        self.domain = f"{self.code.lower()}.example"
        self.users: dict[str, uuid.UUID] = {}
        self.emails: dict[str, str] = {}             # roster key → login, for keys that are not roster local parts
        self.suppliers: dict[str, uuid.UUID] = {}   # legacy supplier tenant id → supplier id
        self.supplier_codes: dict[str, str] = {}
        self.categories: dict[str, set] = defaultdict(set)
        self.banks: dict[str, uuid.UUID] = {}
        self.materials: dict[str, uuid.UUID] = {}   # sku → material id
        self.requisitions: dict[str, tuple] = {}    # legacy request id → (id, number, qty, uom, category, group, confidence)
        self.pos: dict[str, dict] = {}              # legacy po id → {"id", "number", "line_id", ...}
        self.findings: list[dict] = []
        self.live: dict = {}

    def minor(self, amount) -> int:
        return int((Decimal(str(amount or 0)) * self.fx * 100).quantize(Decimal(1), ROUND_HALF_UP))

    def finding(self, code: str, severity: str, detail: str, refs: list[str]) -> None:
        self.findings.append({"code": code, "severity": severity, "detail": detail, "refs": refs})

    # legacy rows belonging to this buyer
    def requests(self):
        return [r for r in self.legacy.requests if r["tenant_id"] == self.buyer["id"]]

    def pos_(self):
        return [r for r in self.legacy.pos if r["tenant_id"] == self.buyer["id"]]

    def quotes_for(self, request_id: str):
        return [q for q in self.legacy.quotes if q["request_id"] == request_id]

    def invoices(self):
        mine = {r["id"] for r in self.pos_()}
        return [r for r in self.legacy.invoices if r["po_id"] in mine]

    def grs_for(self, po_id: str):
        return [g for g in self.legacy.grs if g["po_id"] == po_id]

    def asns_for(self, po_id: str):
        return [a for a in self.legacy.asns if a["po_id"] == po_id]

    def supplier_tenants(self) -> list[str]:
        ids = [r["supplier_tenant_id"] for r in self.pos_()] + [q["supplier_tenant_id"] for q in self.legacy.quotes
                                                                 if q["tenant_id"] == self.buyer["id"]]
        ids += [r["target_supplier_id"] for r in self.requests() if r.get("target_supplier_id")]
        return list(dict.fromkeys(i for i in ids if i in self.legacy.tenants))


# ---------------------------------------------------------------- loads
def _users(sc: Scenario, ctx: Ctx, password: str) -> None:
    hashed = hash_password(password)
    legacy = ctx.legacy
    names: dict[str, str] = {}
    po_ids = {r["id"] for r in ctx.pos_()}
    for approval in legacy.approvals:
        approver = approval["approver_id"] or ""
        if approval["po_id"] in po_ids and approval["status"] == "APPROVED" and not approver.startswith("Pending"):
            names.setdefault("finance.controller", approver)
    item_ids = {i["id"] for i in legacy.items if i["tenant_id"] == ctx.buyer["id"]}
    for move in legacy.moves:
        m = re.match(r"^(.+?) \((.+)\)$", move.get("performed_by") or "")
        if not m or move["inventory_item_id"] not in item_ids:
            continue
        person, title = m.groups()
        for pattern, slot in PEOPLE:
            if re.search(pattern, title.lower()) and slot not in names and person not in names.values():
                names[slot] = person
                break
    with tenant_tx(sc.tenant_id) as s:
        for local, title, roles, attributes in ROSTER:
            user = AppUser(tenant_id=sc.tenant_id, email=f"{local}@{ctx.domain}", full_name=names.get(local, title), password_hash=hashed,
                           roles=roles, attributes=attributes, mfa_enrolled=any(r in roles for r in ("FINANCE_CONTROLLER", "TENANT_ADMIN", "CPO")))
            s.add(user)
            s.flush()
            ctx.users[local] = user.id
        for row in legacy.users:
            if row["tenant_id"] != ctx.buyer["id"]:
                continue
            user = AppUser(tenant_id=sc.tenant_id, email=row["email"], full_name=row["full_name"], password_hash=hashed,
                           roles=["TENANT_ADMIN", "BUYER"], attributes={"plants": [PLANT], "legacyRole": row["role"], "legacyId": row["id"]},
                           mfa_enrolled=True, created_at=ts(row["created_at"]))
            s.add(user)
            s.flush()
            ctx.users.setdefault("legacy.buyer", user.id)
            ctx.emails.setdefault("legacy.buyer", row["email"])
        audit.record(s, "MIGRATION", legacy_ref("users", ctx.buyer["id"]), "USERS_LOADED", object_ref=f"{SOURCE}:users",
                     after={"roster": len(ROSTER), "legacyNamed": names, "legacyUsers": sum(1 for r in legacy.users if r["tenant_id"] == ctx.buyer["id"])},
                     actor="migration")


def _suppliers(sc: Scenario, ctx: Ctx, password: str) -> None:
    legacy = ctx.legacy
    for request in ctx.requests():
        category = classify(request["description"])[0]
        if request.get("target_supplier_id"):
            ctx.categories[request["target_supplier_id"]].add(category)
        for quote in ctx.quotes_for(request["id"]):
            ctx.categories[quote["supplier_tenant_id"]].add(category)
    hashed = hash_password(password)
    with sc.act("admin", clock.now()) as s:
        for supplier_tenant in ctx.supplier_tenants():
            row = legacy.tenants[supplier_tenant]
            profile = legacy.profiles.get(supplier_tenant)
            terms = next((f"N{m.group(1)}" for q in legacy.quotes if q["supplier_tenant_id"] == supplier_tenant
                          for m in [re.search(r"Net (\d+)", q.get("terms") or "")] if m), "N60")
            health = profile["financial_risk_score"] if profile else None
            contact = next((u["email"] for u in legacy.users if u["tenant_id"] == supplier_tenant), None)
            supplier = Supplier(
                tenant_id=sc.tenant_id, code=next_number(s, "SUPPLIER"), legal_name=row["name"], status="ACTIVE", country="ZZ",
                payment_terms=terms, risk_tier=None if health is None else ("LOW" if health >= 80 else "MEDIUM" if health >= 65 else "HIGH"),
                screening={"outcome": "NOT_SCREENED", "legacyId": supplier_tenant, "legacyProfile": _profile(profile)}, contact_email=contact,
                created_at=ts(row["created_at"]), created_by=ctx.users["admin"],
            )
            s.add(supplier)
            s.flush()
            ctx.suppliers[supplier_tenant], ctx.supplier_codes[supplier_tenant] = supplier.id, supplier.code
            flagged = profile is not None and profile["compliance_status"] != "COMPLIANT"
            for category in sorted(ctx.categories[supplier_tenant] or {"UNCLASSIFIED"}):
                s.add(SupplierCategoryStatus(
                    tenant_id=sc.tenant_id, supplier_id=supplier.id, category=category, status="CONDITIONAL" if flagged else "QUALIFIED",
                    waiver_reason=f"Legacy compliance status {profile['compliance_status']}; requalification opened at cutover" if flagged else None,
                    qualified_on=day(profile["last_audit_date"]) if profile else None, created_by=ctx.users["admin"]))
            # Bank details were never captured in the legacy system: a placeholder carries the paid history,
            # new payments stay blocked until the supplier completes the MDM-04 bank change.
            bank = SupplierBankAccount(tenant_id=sc.tenant_id, supplier_id=supplier.id,
                                       account_enc=crypto.encrypt(sc.tenant_id, "bank_account", "NOT-CAPTURED"),
                                       account_masked="not captured (legacy)", ifsc="UNKNOWN", holder_name=row["name"], active=False,
                                       created_by=ctx.users["admin"])
            s.add(bank)
            s.flush()
            ctx.banks[supplier_tenant] = bank.id
            for user in legacy.users:
                if user["tenant_id"] == supplier_tenant:
                    s.add(AppUser(tenant_id=sc.tenant_id, email=user["email"], full_name=user["full_name"], password_hash=hashed,
                                  roles=["SUPPLIER_USER"], attributes={"legacyRole": user["role"], "legacyId": user["id"]},
                                  supplier_id=supplier.id, mfa_enrolled=True, created_at=ts(user["created_at"])))
            if flagged:
                ctx.finding("SUPPLIER_COMPLIANCE_FLAG", "Medium",
                            f"{row['name']} is flagged ({profile['compliance_status']}) in the legacy profile; loaded as CONDITIONAL and put into requalification",
                            [supplier.code])
            audit.record(s, "SUPPLIER", supplier.id, "MIGRATED", object_ref=supplier.code,
                         after={"legacyId": supplier_tenant, "legalName": row["name"], "profile": _profile(profile),
                                "categories": sorted(ctx.categories[supplier_tenant])}, actor="migration")
            if is_test(row["name"]):
                ctx.finding("TEST_DATA", "Low", f"Supplier '{row['name']}' looks like test data; migrated and flagged", [supplier.code])


def _profile(profile: Optional[dict]) -> Optional[dict]:
    if not profile:
        return None
    return {"financialHealthScore": profile["financial_risk_score"], "esgScore": profile["esg_score"],
            "complianceStatus": profile["compliance_status"], "lastAuditDate": str(day(profile["last_audit_date"]))}


def _materials(sc: Scenario, ctx: Ctx) -> None:
    legacy = ctx.legacy
    items = [i for i in legacy.items if i["tenant_id"] == ctx.buyer["id"]]
    supplier_items = [i for i in legacy.items if i["tenant_id"] in ctx.suppliers]
    if not items and not supplier_items:
        return
    with sc.act("admin", clock.now()) as s:
        slocs = {}
        for item in items:
            m = re.match(r"Warehouse ([A-Z])\b", item.get("location") or "")
            code = f"WH-{m.group(1)}" if m else "0001"
            if code not in slocs and code != "0001":
                s.add(StorageLocation(tenant_id=sc.tenant_id, plant=PLANT, code=code, name=f"Warehouse {m.group(1)}", created_by=ctx.users["admin"]))
            slocs[code] = True
            unit = (item.get("unit") or "pcs").lower()
            material = Material(
                tenant_id=sc.tenant_id, number=item["sku"][:30], description=item["name"][:200], type="STOCK",
                material_group=slug(item.get("category"), 30), category=slug(item.get("category"), 40), base_uom=UOM.get(unit, unit[:5].upper()),
                valuation_class="3000", gst_rate=Decimal(18), attributes={"legacyId": item["id"], "bin": item.get("location"),
                                                                           "maxCapacity": item.get("max_capacity"), "legacyStatus": item.get("status")},
                mrp_type="PD", lot_size_policy="MINMAX", max_lot=Decimal(item.get("max_capacity") or 0) or None,
                safety_stock=Decimal(item.get("min_threshold") or 0), planned_delivery_days=DEFAULT_LEAD_DAYS, gr_processing_days=1,
                standard_price_minor=ctx.minor(item["unit_price"]), status="ACTIVE", erp_synced=False,
                created_at=ts(item["created_at"]), created_by=ctx.users["admin"])
            s.add(material)
            s.flush()
            ctx.materials[item["sku"]] = material.id
            s.add(Stock(tenant_id=sc.tenant_id, material_id=material.id, plant=PLANT, storage_location=code, stock_type="UNRESTRICTED",
                        batch="", qty=Decimal(item["quantity_on_hand"]), created_by=ctx.users["admin"]))
            _movements(s, sc, ctx, item, material, code)
        for item in supplier_items:
            if (item.get("category") or "").lower() != "finished goods":
                continue
            supplier_tenant = item["tenant_id"]
            category, group, _ = classify(item["name"])
            s.add(CatalogueItem(tenant_id=sc.tenant_id, supplier_id=ctx.suppliers[supplier_tenant], supplier_part_no=item["sku"][:60],
                                description=item["name"][:200], material_group=group, category=category,
                                uom=UOM.get((item.get("unit") or "pcs").lower(), "EA"), price_minor=ctx.minor(item["unit_price"]),
                                gst_rate=Decimal(18), active=True, created_at=ts(item["created_at"]), created_by=ctx.users["admin"]))
        audit.record(s, "MIGRATION", legacy_ref("inventory_items", ctx.buyer["id"]), "INITIAL_LOAD", object_ref=f"{SOURCE}:inventory",
                     after={"materials": sorted(ctx.materials), "storageLocations": sorted(slocs),
                            "catalogueItems": sum(1 for i in supplier_items if (i.get("category") or "").lower() == "finished goods")},
                     actor="migration")


def _movements(s, sc: Scenario, ctx: Ctx, item: dict, material: Material, sloc: str) -> None:
    moves = [m for m in ctx.legacy.moves if m["inventory_item_id"] == item["id"]]
    on_hand = Decimal(item["quantity_on_hand"])
    opening = Decimal(moves[0]["balance_after"] - moves[0]["change_quantity"]) if moves and moves[0].get("balance_after") is not None else (
        on_hand if not moves else Decimal(0))
    first_at = ts(moves[0]["created_at"]) - timedelta(seconds=1) if moves else clock.now()
    if opening:
        s.add(StockMovement(tenant_id=sc.tenant_id, material_id=material.id, plant=PLANT, storage_location=sloc, movement_type="561",
                            stock_type="UNRESTRICTED", qty=opening, reference_type="OPENING_BALANCE",
                            reference_id=legacy_ref("opening", item["id"]), reference_ref=f"OPEN-{item['sku']}"[:60],
                            created_at=first_at, created_by=ctx.users["admin"]))
    balance = opening
    for move in moves:
        change = Decimal(move["change_quantity"])
        kind = move.get("reference_type") or "ADJUSTMENT"
        movement = MOVEMENT.get(kind) or ("701" if change > 0 else "702")
        s.add(StockMovement(tenant_id=sc.tenant_id, material_id=material.id, plant=PLANT, storage_location=sloc, movement_type=movement,
                            stock_type="UNRESTRICTED", qty=change, reference_type=kind[:40], reference_id=legacy_ref("stock_transactions", move["id"]),
                            reference_ref=(move.get("reference_id") or move["id"])[:60], created_at=ts(move["created_at"]), created_by=ctx.users["admin"]))
        balance += change
        if move.get("balance_after") is not None and Decimal(move["balance_after"]) != balance:
            ctx.finding("STOCK_LEDGER_BREAK", "Medium", f"{item['sku']}: legacy balance_after {move['balance_after']} after "
                        f"{move.get('reference_id')} but the running total is {balance}", [item["sku"]])
            balance = Decimal(move["balance_after"])
        if is_test(move.get("reference_id"), move.get("performed_by")):
            ctx.finding("TEST_DATA", "Low", f"{item['sku']}: stock transaction {move.get('reference_id')} ({change:+}) was a test posting; "
                        "migrated for ledger completeness, excluded from the consumption forecast", [item["sku"], move.get("reference_id") or move["id"]])
    if balance != on_hand:
        difference = on_hand - balance
        s.add(StockMovement(tenant_id=sc.tenant_id, material_id=material.id, plant=PLANT, storage_location=sloc,
                            movement_type="701" if difference > 0 else "702", stock_type="UNRESTRICTED", qty=difference,
                            reference_type="CUTOVER_RECONCILIATION", reference_id=legacy_ref("cutover", item["id"]),
                            reference_ref=f"CUT-{item['sku']}"[:60], created_by=ctx.users["admin"]))
        ctx.finding("STOCK_LEDGER_GAP", "Medium", f"{item['sku']}: transactions add up to {balance} but on-hand is {on_hand}; "
                    f"cutover adjustment {difference:+} posted", [item["sku"]])


def _requisitions(sc: Scenario, ctx: Ctx) -> None:
    with sc.act("admin", clock.now()) as s:
        for request in sorted(ctx.requests(), key=lambda r: r["created_at"]):
            quotes = ctx.quotes_for(request["id"])
            pos = [p for p in ctx.pos_() if p["quotation_id"] in {q["id"] for q in quotes}]
            qty, uom = _quantity(ctx, request, pos)
            category, group, confidence = classify(request["description"])
            chosen = next((q for q in reversed(quotes) if q["status"] == "APPROVED"), quotes[-1] if quotes else None)
            estimate = ctx.minor(chosen["amount"]) if chosen else (ctx.minor(pos[0]["total_amount"]) if pos else 0)
            unit_estimate = int((Decimal(estimate) / qty).quantize(Decimal(1), ROUND_HALF_UP))
            number = request["id"] if request["id"].startswith("REQ-") and len(request["id"]) <= 30 else next_number(s, "REQUISITION")
            created = ts(request["created_at"])
            asn_dates = [day(a["expected_date"]) for p in pos for a in ctx.asns_for(p["id"]) if a.get("expected_date")]
            need = min(asn_dates) if asn_dates else created.astimezone(clock.IST).date() + timedelta(days=30)
            pr = Requisition(tenant_id=sc.tenant_id, number=number, origin="MANUAL", origin_ref=f"{SOURCE}:{request['id']}"[:60],
                             purpose_code="LEGACY_MIGRATION", purpose_text=request["description"], requester_id=ctx.users["requester"],
                             company_code=COMPANY, plant=PLANT, status="ORDERED" if pos else "APPROVED", total_minor=estimate,
                             currency="INR", rule_set_version=f"MIGRATION:{SOURCE}", submitted_at=created, approved_at=created,
                             approved_snapshot={"legacyStatus": request["status"]}, created_at=created, created_by=ctx.users["requester"])
            s.add(pr)
            s.flush()
            supplier = ctx.suppliers.get(request.get("target_supplier_id")) or (ctx.suppliers.get(chosen["supplier_tenant_id"]) if chosen else None)
            s.add(PrLine(tenant_id=sc.tenant_id, requisition_id=pr.id, line_no=10, item_type="FREE_TEXT", purchase_type="NON_STOCK",
                         description=request["description"][:200], material_group=group, category=category, qty=qty, uom=uom,
                         price_est_minor=unit_estimate, currency="INR", account_assignment_type="COST_CENTER",
                         account_assignment_code=COST_CENTER, need_date=need, plant=PLANT, preferred_supplier_id=supplier,
                         quotes_attached=len(quotes), ordered_qty=qty if pos else Decimal(0), sourcing_status="ORDERED" if pos else "SOURCED",
                         created_at=created, created_by=ctx.users["requester"]))
            ctx.requisitions[request["id"]] = (pr.id, pr.number, qty, uom, category, group, confidence)
            audit.record(s, "REQUISITION", pr.id, "MIGRATED", object_ref=pr.number,
                         after={"legacyId": request["id"], "legacyStatus": request["status"], "quotes": [q["id"] for q in quotes],
                                "classification": {"category": category, "confidence": str(confidence)}}, actor="migration")
            if is_test(request["id"], request["description"]):
                ctx.finding("TEST_DATA", "Low", f"Request {request['id']} ('{request['description'][:40]}') looks like test data", [pr.number])
            if category == "UNCLASSIFIED":
                ctx.finding("UNCLASSIFIED_SPEND", "Low", f"{pr.number}: '{request['description'][:60]}' could not be classified "
                            "(no item or category in the legacy request)", [pr.number])


def _quantity(ctx: Ctx, request: Optional[dict], pos: list[dict]) -> tuple[Decimal, str]:
    m = re.search(r"\((\d+)\s*units?\)", (request or {}).get("description") or "", re.I)
    if m:
        return Decimal(m.group(1)), "EA"
    received = sum(Decimal(str(g["received_quantity"] or 0)) for p in pos for g in ctx.grs_for(p["id"]))
    if received > 0:
        return received, "EA"
    return Decimal(1), "LOT"


def _sourcing(sc: Scenario, ctx: Ctx) -> None:
    """Requests quoted more than once were competitive or negotiated: they become sourcing events."""
    with sc.act("category.manager", clock.now()) as s:
        for request in ctx.requests():
            quotes = ctx.quotes_for(request["id"])
            if len(quotes) < 2:
                continue
            pr_id, pr_no, qty, uom, category, group, _ = ctx.requisitions[request["id"]]
            first, last = ts(quotes[0]["created_at"]), ts(quotes[-1]["created_at"])
            unit = lambda q: int((Decimal(ctx.minor(q["amount"])) / qty).quantize(Decimal(1), ROUND_HALF_UP))  # noqa: E731
            rounds = Counter(q["supplier_tenant_id"] for q in quotes)
            event = SourcingEvent(
                tenant_id=sc.tenant_id, number=request["id"] if request["id"].startswith("RFQ-") else next_number(s, "SOURCING_EVENT"),
                type="RFQ", title=request["description"][:200], category=category, status="AWARDED", owner_id=ctx.users["category.manager"],
                currency="INR", round=max(rounds.values()), weights_locked=True, published_at=ts(request["created_at"]), close_at=last,
                closed_at=last, unsealed_at=last, baseline_price_minor=unit(quotes[0]), baseline_method="FIRST_QUOTE",
                constraints={}, tco_params={}, created_at=ts(request["created_at"]), created_by=ctx.users["category.manager"])
            s.add(event)
            s.flush()
            line = EventLine(tenant_id=sc.tenant_id, event_id=event.id, line_no=10, description=request["description"][:200], plant=PLANT,
                             annual_qty=qty, monthly_qty=qty, uom=uom, requisition_id=pr_id, pr_line_no=10, created_by=event.owner_id)
            s.add(line)
            s.flush()
            seen: Counter = Counter()
            for quote in quotes:
                supplier_tenant = quote["supplier_tenant_id"]
                supplier_id = ctx.suppliers[supplier_tenant]
                if not seen[supplier_tenant]:
                    status = s.execute(select(SupplierCategoryStatus.status).where(SupplierCategoryStatus.supplier_id == supplier_id,
                                                                                   SupplierCategoryStatus.category == category)).scalar()
                    s.add(Invitee(tenant_id=sc.tenant_id, event_id=event.id, supplier_id=supplier_id, category_status=status or "REGISTERED",
                                  created_by=event.owner_id))
                seen[supplier_tenant] += 1
                payload = {"quotation": quote["id"], "amount": quote["amount"], "terms": quote.get("terms")}
                bid = Bid(tenant_id=sc.tenant_id, event_id=event.id, supplier_id=supplier_id, round=seen[supplier_tenant],
                          payload_hash=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                          status="UNSEALED" if seen[supplier_tenant] == rounds[supplier_tenant] else "SUPERSEDED",
                          submitted_at=ts(quote["created_at"]), submitted_by=event.owner_id, created_at=ts(quote["created_at"]))
                s.add(bid)
                s.flush()
                terms = quote.get("terms") or ""
                lead = re.search(r"Lead Time:\s*(\d+)", terms)
                net = re.search(r"Net (\d+)", terms)
                s.add(BidLine(tenant_id=sc.tenant_id, bid_id=bid.id, event_line_id=line.id, unit_price_minor=unit(quote),
                              payment_terms_days=int(net.group(1)) if net else 30, lead_time_days=int(lead.group(1)) if lead else DEFAULT_LEAD_DAYS,
                              tco_minor=unit(quote), tco_breakdown={"price": unit(quote), "source": f"legacy quotation {quote['id']}"},
                              tco_components={"terms": terms[:300]}, created_by=event.owner_id))
            link(s, "REQUISITION", pr_id, pr_no, "SOURCING_EVENT", event.id, event.number, "sourced_by", from_line=10, to_line=10)
            ctx.requisitions[request["id"]] = (*ctx.requisitions[request["id"]][:7], event.id, event.number)
            audit.record(s, "SOURCING_EVENT", event.id, "MIGRATED", object_ref=event.number,
                         after={"legacyRequest": request["id"], "quotes": [{"id": q["id"], "amount": q["amount"], "status": q["status"]} for q in quotes],
                                "negotiatedUnitMinor": [unit(quotes[0]), unit(quotes[-1])]}, actor="migration")
            ctx.live.setdefault("sourcingEvents", []).append(
                f"{event.number}: {len(quotes)} quotes, unit price {unit(quotes[0]) / 100:,.2f} → {unit(quotes[-1]) / 100:,.2f}")


def _po_status(legacy_status: str, has_gr: bool, has_asn: bool) -> str:
    if legacy_status == "PENDING_APPROVAL":
        return "DRAFT"  # routed through the live approval after the load
    if legacy_status in ("COMPLETED", "INVOICED"):
        if has_gr:
            return "CLOSED" if legacy_status == "COMPLETED" else "INVOICED"
        return "CONFIRMED"  # paid in the legacy system but never received: stays open for the goods receipt
    if has_gr:
        return "RECEIVED"
    return "CONFIRMED" if has_asn else "TRANSMITTED"


def _purchase_orders(sc: Scenario, ctx: Ctx) -> None:
    legacy = ctx.legacy
    buyer = "legacy.buyer" if "legacy.buyer" in ctx.users else "buyer"
    with sc.act(ctx.emails.get(buyer, buyer), clock.now()) as s:
        for row in ctx.pos_():
            quote = next((q for q in legacy.quotes if q["id"] == row["quotation_id"]), None)
            request_id = quote["request_id"] if quote else None
            request = next((r for r in legacy.requests if r["id"] == request_id), None)
            grs, asns = ctx.grs_for(row["id"]), ctx.asns_for(row["id"])
            if request_id in ctx.requisitions:
                pr_id, pr_no, qty, uom, category, group, _ = ctx.requisitions[request_id][:7]
            else:
                pr_id = pr_no = None
                qty, uom = _quantity(ctx, None, [row])
                category, group, _ = classify("")
            total = ctx.minor(row["total_amount"])
            unit_price = int((Decimal(total) / qty).quantize(Decimal(1), ROUND_HALF_UP))
            quoted = ctx.minor(quote["amount"]) if quote else None
            deviation = quoted is not None and abs(quoted - total) > 100
            created = ts(row["created_at"])
            need = min((day(a["expected_date"]) for a in asns if a.get("expected_date")), default=created.astimezone(clock.IST).date() + timedelta(days=DEFAULT_LEAD_DAYS))
            status = _po_status(row["status"], bool(grs), bool(asns))
            supplier_tenant = row["supplier_tenant_id"]
            terms = next((f"N{m.group(1)}" for m in [re.search(r"Net (\d+)", (quote or {}).get("terms") or "")] if m), None)
            inco = next((m.group(1).strip()[:40] for m in [re.search(r"(DDP[^|.]*)", (quote or {}).get("terms") or "")] if m), None)
            po = PurchaseOrder(
                tenant_id=sc.tenant_id, number=row["po_number"], version=1, company_code=COMPANY, purch_org=COMPANY, plant=PLANT,
                supplier_id=ctx.suppliers[supplier_tenant], status=status, purpose_code="LEGACY_MIGRATION", currency="INR", total_minor=total,
                payment_terms=terms or "N60", incoterms=inco, tolerance={"over_pct": "0", "under_pct": "0", "price_pct": "0"},
                inherited={"migratedFrom": SOURCE, "legacyId": row["id"], "legacyStatus": row["status"], "quotation": row["quotation_id"],
                           "quotedMinor": quoted, "requisition": pr_no},
                touchless=False if status != "DRAFT" else None, released_at=created if status != "DRAFT" else None,
                released_by="legacy" if status != "DRAFT" else None, transmitted_via="PORTAL" if status != "DRAFT" else None,
                transmitted_at=created if status != "DRAFT" else None, rule_set_version=f"MIGRATION:{SOURCE}",
                created_at=created, created_by=ctx.users[buyer])
            s.add(po)
            s.flush()
            description = (request["description"] if request else f"Legacy order {row['po_number']}")[:200]
            line = PoLine(
                tenant_id=sc.tenant_id, po_id=po.id, line_no=10, item_type="FREE_TEXT", purchase_type="NON_STOCK", description=description,
                material_group=group, qty=qty, uom=uom, unit_price_minor=unit_price, net_minor=total, gst_rate=Decimal(0), need_date=need,
                plant=PLANT, account_assignment_type="COST_CENTER", account_assignment_code=COST_CENTER, gr_required=True, ir_required=True,
                price_source="QUOTE" if quote else "MANUAL", price_deviation=deviation,
                deviation_reason=(f"Legacy PO total {money(row['total_amount'])} differs from approved quotation {quote['id']} "
                                  f"({money(quote['amount'])})") if deviation else None,
                requisition_id=pr_id, pr_line_no=10 if pr_id else None, created_at=created, created_by=ctx.users[buyer])
            s.add(line)
            s.flush()
            ctx.pos[row["id"]] = {"id": po.id, "number": po.number, "line_id": line.id, "qty": qty, "total": total, "status": status,
                                  "supplier": supplier_tenant, "category": category, "group": group, "legacy": row}
            if pr_id:
                link(s, "REQUISITION", pr_id, pr_no, "PURCHASE_ORDER", po.id, po.number, "converted_from", from_line=10, to_line=10)
            event = ctx.requisitions.get(request_id, ())[7:9] if request_id in ctx.requisitions else ()
            if event:
                link(s, "SOURCING_EVENT", event[0], event[1], "PURCHASE_ORDER", po.id, po.number, "awarded_as", from_line=10, to_line=10)
            audit.record(s, "PURCHASE_ORDER", po.id, "MIGRATED", object_ref=po.number,
                         after={"legacyId": row["id"], "legacyStatus": row["status"], "status": status, "totalMinor": total,
                                "qty": str(qty), "uom": uom}, actor="migration")
            for approval in legacy.approvals:
                if approval["po_id"] != row["id"]:
                    continue
                approver = approval["approver_id"] or "unknown"
                audit.record(s, "PURCHASE_ORDER", po.id, "LEGACY_APPROVAL_" + approval["status"], object_ref=po.number,
                             after={"legacyId": approval["id"], "comments": approval["comments"], "at": approval["created_at"]},
                             actor=f"legacy:{approver}")
            if deviation:
                ctx.finding("QUOTE_PO_MISMATCH", "High", f"{po.number}: PO total {money(row['total_amount'])} vs approved quotation "
                            f"{quote['id']} {money(quote['amount'])}; loaded with a price deviation (risk +18)", [po.number, quote["id"]])
            if is_test(row["po_number"], row["id"]) or (request and is_test(request["id"])):
                ctx.finding("TEST_DATA", "Low", f"{po.number} belongs to a dummy/test request; migrated and flagged", [po.number])
            if row["status"] == "COMPLETED" and not grs:
                ctx.finding("CLOSED_WITHOUT_RECEIPT", "High", f"{po.number} is COMPLETED and paid in the legacy system with no goods receipt; "
                            "loaded as CONFIRMED so the receipt can be posted", [po.number])


def _receipts(sc: Scenario, ctx: Ctx) -> None:
    with sc.act("receiver", clock.now()) as s:
        for legacy_id, po in ctx.pos.items():
            line = s.get(PoLine, po["line_id"])
            asn_ids = []
            received = sum((Decimal(str(g["received_quantity"] or 0)) for g in ctx.grs_for(legacy_id)), Decimal(0))
            for row in ctx.asns_for(legacy_id):
                created = ts(row["created_at"])
                asn = Asn(tenant_id=sc.tenant_id, number=row["id"][:30], po_id=po["id"], supplier_id=ctx.suppliers[po["supplier"]],
                          status="RECEIVED" if received else "IN_TRANSIT", ship_date=created.astimezone(clock.IST).date(),
                          expected_date=day(row["expected_date"]) or created.astimezone(clock.IST).date(),
                          documents=[f"{row.get('carrier') or 'carrier'} {row.get('tracking_number') or ''}".strip()],
                          created_at=created, created_by=ctx.users["admin"])
                s.add(asn)
                s.flush()
                s.add(AsnLine(tenant_id=sc.tenant_id, asn_id=asn.id, po_line_id=line.id, qty=line.qty,
                              batches=[{"batch": (row.get("tracking_number") or row["id"])[:30], "qty": str(line.qty)}],
                              received_qty=min(line.qty, received), created_by=ctx.users["admin"]))
                line.shipped_qty = line.qty
                link(s, "PURCHASE_ORDER", po["id"], po["number"], "ASN", asn.id, asn.number, "shipped_as")
                audit.record(s, "ASN", asn.id, "MIGRATED", object_ref=asn.number, after={"legacyId": row["id"], "carrier": row.get("carrier"),
                                                                                          "tracking": row.get("tracking_number")}, actor="migration")
                asn_ids.append((asn.id, asn.number))
            for row in ctx.grs_for(legacy_id):
                qty = Decimal(str(row["received_quantity"] or 0))
                created = ts(row["created_at"])
                gr = GoodsReceipt(tenant_id=sc.tenant_id, number=row["id"][:30], po_id=po["id"], asn_id=asn_ids[0][0] if asn_ids else None,
                                  status="ACCEPTED", posting_date=created.astimezone(clock.IST).date(), posted_by=ctx.users["receiver"],
                                  created_at=created, created_by=ctx.users["receiver"])
                s.add(gr)
                s.flush()
                s.add(GrLine(tenant_id=sc.tenant_id, gr_id=gr.id, line_no=1, po_line_id=line.id, qty=qty, accepted_qty=qty, rejected_qty=0,
                             stock_type="UNRESTRICTED", storage_location="0001", movement_type="101", created_by=ctx.users["receiver"]))
                line.received_qty += qty
                line.accepted_qty += qty
                link(s, "PURCHASE_ORDER", po["id"], po["number"], "GOODS_RECEIPT", gr.id, gr.number, "received_against")
                for asn_id, asn_no in asn_ids:
                    link(s, "ASN", asn_id, asn_no, "GOODS_RECEIPT", gr.id, gr.number, "received_against")
                audit.record(s, "GOODS_RECEIPT", gr.id, "MIGRATED", object_ref=gr.number,
                             after={"legacyId": row["id"], "qty": str(qty), "valueLegacy": row["received_amount_value"]}, actor="migration")
                expected = ctx.minor(row["received_amount_value"])
                if abs(int(qty * line.unit_price_minor) - expected) > 100:
                    ctx.finding("GR_VALUE_MISMATCH", "Medium", f"{gr.number}: {qty} × {line.unit_price_minor / 100:,.2f} on {po['number']} ≠ legacy "
                                f"received value {money(row['received_amount_value'])}", [gr.number, po["number"]])


def _history(sc: Scenario, ctx: Ctx) -> list[dict]:
    """Paid invoices and payments are history (read-only); pending invoices go through live capture later."""
    pending = []
    paid_by_po: dict[str, int] = defaultdict(int)
    with sc.act("ap.clerk", clock.now()) as s:
        for row in ctx.invoices():
            if row["status"] != "PAID":
                pending.append(row)
                continue
            po = ctx.pos[row["po_id"]]
            line = s.get(PoLine, po["line_id"])
            created = ts(row["created_at"])
            invoice_date = created.astimezone(clock.IST).date()
            net = ctx.minor(row["amount"])
            qty = Decimal(str(row.get("invoiced_quantity") or 1))
            number = invoice_no(row["id"])
            payment_row = ctx.legacy.payments.get(row["id"])
            paid_at = ts(payment_row["created_at"]) if payment_row else created
            invoice = Invoice(
                tenant_id=sc.tenant_id, number=number, supplier_invoice_no=number, fiscal_year=clock.fiscal_year(invoice_date),
                company_code=COMPANY, supplier_id=ctx.suppliers[po["supplier"]], po_id=po["id"], invoice_date=invoice_date, channel="PORTAL",
                currency="INR", net_minor=net, tax_minor=0, gross_minor=net, status="PAID",
                match_type="3WAY" if line.received_qty else "2WAY", first_pass_matched=True if row.get("match_status") == "MATCHED" else None,
                payment_block=False, due_date=day(row.get("due_date")), approved_by=ctx.users["finance.controller"], posted_at=paid_at,
                payment_status="PAID", rule_set_version=f"MIGRATION:{SOURCE}", created_at=created, created_by=ctx.users["ap.clerk"])
            s.add(invoice)
            s.flush()
            unit_price = int((Decimal(net) / qty).quantize(Decimal(1), ROUND_HALF_UP))
            invoice_line = InvoiceLine(tenant_id=sc.tenant_id, invoice_id=invoice.id, line_no=10, po_line_id=line.id,
                                       description=(row.get("description") or line.description)[:200], qty=qty, unit_price_minor=unit_price,
                                       net_minor=net, gst_rate=Decimal(0), tax_minor=0, match_status="LEGACY",
                                       match_detail={"legacyMatchStatus": row.get("match_status"), "legacyDispatch": row.get("dispatch_status")},
                                       created_by=ctx.users["ap.clerk"])
            s.add(invoice_line)
            s.flush()
            line.invoiced_qty += qty
            line.invoiced_minor += net
            link(s, "PURCHASE_ORDER", po["id"], po["number"], "INVOICE", invoice.id, invoice.number, "invoiced_against", from_line=10, to_line=10)
            if payment_row:
                payment = Payment(tenant_id=sc.tenant_id,
                                  number=payment_row["id"][:30] if payment_row["id"].startswith("PAY-") else next_number(s, "PAYMENT"),
                                  invoice_id=invoice.id, supplier_id=invoice.supplier_id, bank_account_id=ctx.banks[po["supplier"]],
                                  amount_minor=ctx.minor(payment_row["amount"]), value_date=paid_at.astimezone(clock.IST).date(),
                                  status="COMPLETED", run_ref="LEGACY", approved_by=ctx.users["finance.controller"], created_at=paid_at,
                                  created_by=ctx.users["finance.controller"])
                s.add(payment)
                s.flush()
                link(s, "INVOICE", invoice.id, invoice.number, "PAYMENT", payment.id, payment.number, "paid_by")
            paid_by_po[row["po_id"]] += net
            flags = []
            if not line.received_qty:
                flags.append("NO_GOODS_RECEIPT")
            if po["legacy"]["status"] == "PENDING_APPROVAL":
                flags.append("PO_NOT_APPROVED")
            if paid_by_po[row["po_id"]] > po["total"]:
                flags.append("OVER_INVOICED")
            confidence = ctx.requisitions.get(next((q["request_id"] for q in ctx.legacy.quotes if q["id"] == po["legacy"]["quotation_id"]), None),
                                              (None,) * 7)[6] or Decimal("0.300")
            s.add(SpendLine(tenant_id=sc.tenant_id, invoice_line_id=invoice_line.id, invoice_ref=invoice.number, po_ref=po["number"],
                            supplier_id=invoice.supplier_id, category=po["category"], material_group=po["group"], plant=PLANT, company_code=COMPANY,
                            cost_object=f"COST_CENTER:{COST_CENTER}", period=invoice_date.strftime("%Y-%m"), amount_minor=net, currency="INR",
                            contracted=False, addressable=True, maverick_flags=flags, classification_confidence=confidence,
                            description=line.description, po_line_id=line.id, source="LEGACY", created_by=ctx.users["ap.clerk"]))
            audit.record(s, "INVOICE", invoice.id, "MIGRATED", object_ref=invoice.number,
                         after={"legacyId": row["id"], "grossMinor": net, "payment": payment_row["id"] if payment_row else None,
                                "paymentNote": (payment_row or {}).get("description"), "flags": flags}, actor="migration")
            if "PO_NOT_APPROVED" in flags:
                ctx.finding("PAID_BEFORE_APPROVAL", "Critical", f"{invoice.number} ({money(row['amount'])}) was paid against {po['number']}, "
                            "which is still pending approval in the legacy system", [invoice.number, po["number"]])
            if "NO_GOODS_RECEIPT" in flags:
                ctx.finding("PAID_WITHOUT_RECEIPT", "High", f"{invoice.number} ({money(row['amount'])}) was paid on {po['number']} without a goods receipt",
                            [invoice.number, po["number"]])
            if row.get("description") and "DISPUTE" in row["description"].upper():
                ctx.finding("PAID_DISPUTED_INVOICE", "High", f"{invoice.number} was paid while marked '{row['description'][:80]}'", [invoice.number])
        for legacy_id, paid in paid_by_po.items():
            po = ctx.pos[legacy_id]
            if paid > po["total"]:
                count = sum(1 for r in ctx.invoices() if r["po_id"] == legacy_id and r["status"] == "PAID")
                ctx.finding("OVERPAID_PO", "Critical", f"{po['number']}: {count} invoices paid for {paid / 100:,.2f} against a PO value of "
                            f"{po['total'] / 100:,.2f} (excess {(paid - po['total']) / 100:,.2f})", [po["number"]])
    return pending


# ---------------------------------------------------------------- live continuation
def _continue(sc: Scenario, ctx: Ctx, pending: list[dict], start: datetime) -> None:
    from app.pic.services import mdm, order, payables, planning
    from app.pic.services import supplier as supplier_svc
    live = ctx.live

    # F8: screening for every migrated supplier; compliance-flagged suppliers into requalification.
    with sc.act("supplier.manager", start) as s:
        screened, requalified = [], []
        for supplier_tenant, supplier_id in ctx.suppliers.items():
            supplier = s.get(Supplier, supplier_id)
            legacy_profile = supplier.screening.get("legacyProfile")
            result = supplier_svc.screen(s, supplier)
            supplier.screening = {**result, "legacyId": supplier_tenant, "legacyProfile": legacy_profile}
            screened.append(f"{supplier.code} {result['outcome']}")
            if legacy_profile and legacy_profile["complianceStatus"] != "COMPLIANT":
                for status in s.execute(select(SupplierCategoryStatus).where(SupplierCategoryStatus.supplier_id == supplier_id)).scalars():
                    q = supplier_svc.start_qualification(s, supplier, status.category)
                    supplier_svc.record_assessment(s, q, questionnaire={"source": f"{SOURCE} supplier profile"},
                                                   questionnaire_score=Decimal(legacy_profile["financialHealthScore"]))
                    requalified.append(f"{supplier.code}/{status.category}")
    live["screening"], live["requalification"] = screened, requalified

    # F5: the PO still pending approval in the legacy system goes through PO validation and the approval route.
    routed = []
    for legacy_id, po in ctx.pos.items():
        if po["status"] != "DRAFT":
            continue
        who = "legacy.buyer" if "legacy.buyer" in ctx.users else "buyer"
        with sc.act(ctx.emails.get(who, who), start + timedelta(hours=1)) as s:
            row = s.get(PurchaseOrder, po["id"])
            instance = workflow.start(s, order.PROCESS, "PURCHASE_ORDER", row.id, row.number)
            workflow.step(s, instance, "F5-02", outcome=f"migrated from {SOURCE}; pending approval in the legacy system")
            result = order.validate(s, row)
            order.route(s, row)
            routed.append(f"{row.number}: risk {result['riskScore']} ({', '.join(f['code'] for f in result['factors']) or 'no factors'}) → {row.status}")
    live["poApproval"] = routed

    # F7: pending legacy invoices are captured and matched by the PIC rules.
    captured = []
    for index, row in enumerate(pending):
        po = ctx.pos[row["po_id"]]
        qty = Decimal(str(row.get("invoiced_quantity") or 1))
        unit_price = (Decimal(str(row["amount"])) * ctx.fx / qty).quantize(Decimal("0.01"))
        with sc.act("ap.clerk", start + timedelta(hours=2, minutes=index)) as s:
            invoice = payables.capture(s, supplier=ctx.supplier_codes[po["supplier"]], supplier_invoice_no=invoice_no(row["id"]),
                                       invoice_date=day(row["created_at"]), channel="PORTAL",
                                       lines=[{"po": po["number"], "po_line": 10, "qty": str(qty), "unit_price": str(unit_price), "gst_rate": "0",
                                               **({"description": row["description"][:200]} if row.get("description") else {})}])
            audit.record(s, "INVOICE", invoice.id, "LEGACY_REFERENCE", object_ref=invoice.number,
                         after={"legacyId": row["id"], "legacyStatus": row["status"], "legacyMatchStatus": row.get("match_status")},
                         actor="migration")
            types = [e.type for e in s.execute(select(InvoiceException).where(InvoiceException.invoice_id == invoice.id,
                                                                               InvoiceException.status == "OPEN")).scalars()]
            captured.append({"invoice": invoice.number, "po": po["number"], "status": invoice.status, "exceptions": types})
    live["invoices"] = captured

    # F9: a free-text item ordered more than once becomes a material master request.
    by_text: dict[str, list] = defaultdict(list)
    for request in ctx.requests():
        if request["id"] in ctx.requisitions and not is_test(request["id"], request["description"]):
            by_text[request["description"].strip().lower()].append(request)
    promoted = []
    for text, requests in by_text.items():
        if len(requests) < 2:
            continue
        latest = max(requests, key=lambda r: r["created_at"])
        pr_id, pr_no, _, uom, category, group, _ = ctx.requisitions[latest["id"]][:7]
        with sc.act("buyer", start + timedelta(hours=4)) as s:
            line = s.execute(select(PrLine).where(PrLine.requisition_id == pr_id, PrLine.line_no == 10)).scalar_one()
            name = re.sub(r"^purchase request for [^:]+:\s*", "", latest["description"], flags=re.I)
            request = mdm.create_request(s, description=name[:200], type="STOCK", material_group=group, category=category, base_uom=uom,
                                         attributes={"orderedTimes": len(requests), "legacyRequests": [r["id"] for r in requests]}, source_pr=line)
            promoted.append(f"{request.number}: '{name[:60]}' ordered {len(requests)}× as free text → {request.status}")
    live["materialRequests"] = promoted

    # F1/F2: consumption-based forecast (test postings excluded) + safety stock → MRP → requisition.
    if ctx.materials:
        cutover_day = start.astimezone(clock.IST).date()
        issues: dict[str, Decimal] = defaultdict(Decimal)
        item_by_id = {i["id"]: i for i in ctx.legacy.items}
        window = cutover_day - timedelta(days=30)
        for move in ctx.legacy.moves:
            item = item_by_id.get(move["inventory_item_id"])
            if (item and item["sku"] in ctx.materials and move["reference_type"] == "GOODS_OUT" and move["change_quantity"] < 0
                    and not is_test(move.get("reference_id"), move.get("performed_by")) and day(move["created_at"]) >= window):
                issues[item["sku"]] += -Decimal(move["change_quantity"])
        with sc.act("mrp.controller", start + timedelta(hours=5)) as s:
            for sku, qty in issues.items():
                s.add(DemandElement(tenant_id=sc.tenant_id, material_id=ctx.materials[sku], plant=PLANT, type="FORECAST",
                                    reference=f"FC-CONS-{(cutover_day + timedelta(days=30)).strftime('%Y-%m')}", req_date=cutover_day + timedelta(days=30),
                                    qty=qty, changed_at=clock.now()))
            s.flush()
            run = planning.run(s, plant=PLANT, mode="REGENERATIVE", run_date=cutover_day)
            live["mrp"] = {"run": run.number, "materialsPlanned": run.materials_planned, "plannedOrders": run.planned_orders_created,
                           "exceptions": run.exceptions_raised, "forecast": {k: str(v) for k, v in issues.items()}}
        with sc.act("mrp.controller", start + timedelta(hours=6)) as s:
            orders = s.execute(select(PlannedOrder).where(PlannedOrder.status == "CREATED")).scalars().all()
            if orders:
                prices = {m.id: m.standard_price_minor or 0 for m in s.execute(select(Material)).scalars()}
                biggest = max(orders, key=lambda o: o.qty * prices.get(o.material_id, 0))
                planning.firm(s, biggest)
                pr = planning.convert(s, biggest)
                live["mrp"]["converted"] = f"{biggest.number} → {pr.number} ({pr.status})"
    tick()


# ---------------------------------------------------------------- reconciliation
def _reconcile(ctx: Ctx, tenant_id: uuid.UUID) -> dict:
    legacy_pos = ctx.pos_()
    legacy_invoices = ctx.invoices()
    po_ids = {p["id"] for p in legacy_pos}
    paid = [i for i in legacy_invoices if i["status"] == "PAID"]
    legacy_payments = [ctx.legacy.payments[i["id"]] for i in paid if i["id"] in ctx.legacy.payments]
    with tenant_tx(tenant_id) as s:
        count = lambda model, *where: s.execute(select(func.count()).select_from(model).where(*where)).scalar()  # noqa: E731
        total = lambda col, *where: s.execute(select(func.coalesce(func.sum(col), 0)).where(*where)).scalar()  # noqa: E731
        migrated_po = PurchaseOrder.purpose_code == "LEGACY_MIGRATION"
        rows = [
            ("Suppliers", len(ctx.supplier_tenants()), count(Supplier)),
            ("Materials (buyer inventory)", sum(1 for i in ctx.legacy.items if i["tenant_id"] == ctx.buyer["id"]), count(Material)),
            ("Stock movements (legacy transactions)", sum(1 for m in ctx.legacy.moves if m["inventory_item_id"] in
                                                          {i["id"] for i in ctx.legacy.items if i["tenant_id"] == ctx.buyer["id"]}),
             count(StockMovement, StockMovement.reference_type.notin_(["OPENING_BALANCE", "CUTOVER_RECONCILIATION"]))),
            ("Requisitions (order requests)", len(ctx.requests()), count(Requisition, Requisition.purpose_code == "LEGACY_MIGRATION")),
            ("Bids (quotations in sourcing events)", sum(len(ctx.quotes_for(r["id"])) for r in ctx.requests() if len(ctx.quotes_for(r["id"])) > 1),
             count(Bid)),
            ("Purchase orders", len(legacy_pos), count(PurchaseOrder, migrated_po)),
            ("ASNs", sum(1 for a in ctx.legacy.asns if a["po_id"] in po_ids), count(Asn)),
            ("Goods receipts", sum(1 for g in ctx.legacy.grs if g["po_id"] in po_ids), count(GoodsReceipt)),
            ("Invoices", len(legacy_invoices), count(Invoice)),
            ("Payments", len(legacy_payments), count(Payment)),
        ]
        values = [
            ("PO value", sum(ctx.minor(p["total_amount"]) for p in legacy_pos), total(PurchaseOrder.total_minor, migrated_po)),
            ("Invoice value", sum(ctx.minor(i["amount"]) for i in legacy_invoices), total(Invoice.gross_minor)),
            ("Paid invoice value", sum(ctx.minor(i["amount"]) for i in paid), total(Invoice.gross_minor, Invoice.payment_status == "PAID")),
            ("Payments", sum(ctx.minor(p["amount"]) for p in legacy_payments), total(Payment.amount_minor)),
            ("Stock value at standard price", sum(ctx.minor(i["unit_price"]) * i["quantity_on_hand"] for i in ctx.legacy.items
                                                  if i["tenant_id"] == ctx.buyer["id"]),
             s.execute(select(func.coalesce(func.sum(Stock.qty * Material.standard_price_minor), 0)).join(Material, Material.id == Stock.material_id)).scalar()),
        ]
        open_tasks = Counter(t.kind for t in s.execute(select(Task).where(Task.status == "OPEN")).scalars())
        exceptions = Counter(e.type for e in s.execute(select(InvoiceException).where(InvoiceException.status == "OPEN")).scalars())
        mrp_exceptions = Counter(e.code for e in s.execute(select(MrpException)).scalars())
        spend = s.execute(select(SpendLine.maverick_flags, SpendLine.amount_minor)).all()
    flagged = defaultdict(int)
    for flags, amount in spend:
        for flag in flags:
            flagged[flag] += amount
    return {
        "tenant": ctx.code, "name": ctx.buyer["name"], "legacyId": ctx.buyer["id"],
        "counts": [{"object": o, "legacy": int(a), "pic": int(b), "ok": int(a) == int(b)} for o, a, b in rows],
        "values": [{"object": o, "legacyMinor": int(a), "picMinor": int(b), "ok": int(a) == int(b)} for o, a, b in values],
        "findings": ctx.findings, "live": ctx.live, "openTasks": dict(open_tasks), "openInvoiceExceptions": dict(exceptions),
        "mrpExceptions": dict(mrp_exceptions), "maverickSpendMinor": dict(flagged), "fx": str(ctx.fx),
    }


# ---------------------------------------------------------------- entry point
def migrate(snapshot: dict, password: str, fx: Decimal = Decimal(1)) -> list[dict]:
    legacy = Legacy(snapshot)
    reference.deploy_process_definitions()
    reports = []
    cutover = legacy.cutover()
    for buyer in legacy.buyers():
        ctx = Ctx(legacy, buyer, fx)
        with system_tx() as s:
            existing = s.execute(select(Tenant.id).where(Tenant.code == ctx.code)).scalar_one_or_none()
        if existing:
            with tenant_tx(existing) as s:
                if s.execute(select(AppUser.id)).first():
                    reports.append({"tenant": ctx.code, "name": buyer["name"], "skipped": "tenant already migrated"})
                    continue
        clock.set_pinned(cutover)
        tenant_id = reference.create_tenant(ctx.code, buyer["name"])
        reference.bootstrap(tenant_id, company=(COMPANY, buyer["name"], None), plants=[(PLANT, f"{buyer['name']} – main plant", "00")],
                            cost_objects=[("COST_CENTER", COST_CENTER, "Operations"), ("COST_CENTER", "2000", "Engineering")])
        sc = Scenario(tenant_id, ctx.code, ctx.domain, ROLE_USER)
        _users(sc, ctx, password)
        _suppliers(sc, ctx, password)
        _materials(sc, ctx)
        _requisitions(sc, ctx)
        _sourcing(sc, ctx)
        _purchase_orders(sc, ctx)
        _receipts(sc, ctx)
        pending = _history(sc, ctx)
        with sc.act("admin", cutover) as s:
            audit.record(s, "MIGRATION", legacy_ref("tenants", buyer["id"]), "CUTOVER", object_ref=f"{SOURCE}:{buyer['id']}",
                         after={"snapshotSha256": snapshot["sha256"], "extractedAt": snapshot["extractedAt"], "fx": str(fx),
                                "findings": len(ctx.findings)}, actor="migration")
        tick()
        _continue(sc, ctx, pending, cutover + timedelta(hours=15))
        # Intelligence modules over the migrated data: classification, maverick rules, category plans, forecasts, risk.
        from app.pic.seed import intelligence
        clock.set_pinned(cutover + timedelta(hours=16))
        ctx.live["intelligence"] = intelligence.run_for_tenant(
            sc, manager="category.head", mrp="mrp.controller", supplier_mgr="supplier.manager",
            keywords={category: list(words) for words, category, _ in CLASSIFIER})
        tick()
        clock.set_pinned(None)
        reports.append(_reconcile(ctx, tenant_id))
        log.info("migrated %s (%s)", buyer["name"], ctx.code)
    clock.set_pinned(None)
    return reports
