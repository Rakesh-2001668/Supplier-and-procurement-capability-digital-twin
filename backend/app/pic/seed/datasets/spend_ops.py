"""D16 Spend datasets for the demo tenants AXN and KAC: MOCK (ILLUSTRATIVE SAMPLE; the real values need the customer's data and sign-off).

The spend cube (M01) needs, before it can show a working category-intelligence function, history in two fiscal years with several ERPs and
currencies, credit-note netting, steward and maverick workloads in every state, supplier duplicates, concentration and tail, plans in every
approval state, a forecast track record and data-quality findings. Until the customer supplies their own, this pack fills each with clearly
labelled mock data. Bulk spend lines, hit rows and review rows are written with multi-row inserts (one transaction per batch: the pack loads
on a database behind a high-latency link); everything that is a WORKFLOW (decisions, dispositions, escalations, duplicate merge, category
plans, rule versions, forecast and quality runs) goes THROUGH THE REAL SERVICES with the business clock pinned to the day of each step, so
state machines, four-eyes, SoD, audit hash chains and outbox events behave as in production. Everything is deterministic (numbers seed every
choice, nothing is random), idempotent (the pack is loaded once per tenant; a stage that finds its own rows skips) and traceable (``MOCK`` in
names, notes and reasons, ``MOCK-SP/...`` invoice references, ``data/erp_mock/KAC_SPEND/README.md``, ``tools/spend_mock.py``).

KAC (first client; company code 1000, plants 1100 Hosur, 1200 Oragadam, 1300 Bidadi), April 2025 to October 2026 (two fiscal years):
  masters     24 foreign MOCK suppliers on two more ERP systems, 60 tail suppliers, 3 heat-treatment suppliers (HHI above 2,500), 11 suppliers in
              duplicate clusters; MOCK weekly FX rates for USD / EUR / JPY / CNY before April 2026 continuing the finance pack's series
  lines       foreign-currency lines, tail, concentration, duplicates, credit memos, maverick cases for the six rules the tenant had none of,
              unclassified free text for the steward queue, and the deliberate data-quality defects of tools/spend_mock.py (DQ1..DQ8)
  workflow    steward decisions (accept, reclassify, bulk with a learned keyword, four-eyes pending / confirmed / disagreed), maverick dispositions
              in every state with reason codes, recoveries resolved, SLA escalations, duplicate merge proposed / approved / dismissed, category plans
              for the top 8 categories (draft, in approval, approved, rejected, revised), an effective-dated maverick rule version
  history     forecasts as issued for April to September 2026 (computed by the real forecast method on the data up to each month) so the forecast
              error can be shown, a data-quality run, the credit and debit notes of the finance pack netted into the cube
AXN: non-signature additions only (foreign MOCK suppliers on a second ERP, credit memos, tail, maverick cases, steward and hit work); no existing AXN
document, number, amount or status is changed. The signature case's contract coverage and maverick share stay inside their bands.

Requires ``finance-ops`` (credit and debit notes, FX series).
"""
from __future__ import annotations

import logging
import uuid
from bisect import bisect_right
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import func, select, text

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuditEvent, ClassificationReview, FxRate, MaverickHit, MaverickRule, SpendForecastSnapshot, SpendLine, Supplier, SupplierBankAccount,
    SupplierCategoryStatus, Task, TaxonomyNode, Tenant,
)
from app.pic.platform import audit, clock, crypto, workflow
from app.pic.platform.core import insert_rows, next_numbers
from app.pic.platform.errors import Problem
from app.pic.seed.axion import Scenario, at
from app.pic.seed.datasets import _tenant_kit as kit
from app.pic.tools import finance_mock
from app.pic.tools import spend_mock as mock

log = logging.getLogger(__name__)

KEY = "spend-ops"
VERSION = "1"
TITLE = "D16 Spend datasets for AXN and KAC: two fiscal years, multi-ERP and multi-currency lines, credit netting, steward and maverick workloads, duplicates, concentration, plans, forecast history, data-quality findings (MOCK, ILLUSTRATIVE SAMPLE)"
TENANTS = ("AXN", "KAC")
CREATES_TENANT = False
READY = True
REQUIRES = {"finance-ops": "1"}

LABEL = mock.TAG
ACTOR = "mock-data:spend_ops"
NS = uuid.UUID("5d3a1c7e-2f4b-4e0a-9c11-6b7d0a5e9f21")
L = 100_000 * 100
BATCH = 2000
KAC, AXN = "KAC", "AXN"
TODAY = date(2026, 11, 4)
BUSINESS_DAY = date(2026, 11, 3)


def D(month: int, day: int, year: int = 2026) -> date:
    return date(year, month, day)


SPECS = {
    KAC: {"domain": "kaveri-auto.example", "company": "1000", "plants": ["1100", "1200", "1300"], "foreign": mock.FOREIGN, "tail": 60, "heat": True,
          "dups": True, "flagged": 25, "unclassified": 140, "credits": 120, "dq": True, "plans": 8, "ic_supplier_segment": "INTERCOMPANY",
          "who": {"cm": "category.head", "cm2": "category.direct", "ph": "procurement.head", "cpo": "cpo", "st1": "mdm.purchasing", "st2": "mdm.finance",
                  "fin": "fin.controller.1", "admin": "admin"}},
    AXN: {"domain": "axion.example", "company": "1000", "plants": ["P100", "P200"], "foreign": mock.FOREIGN[:6] + mock.FOREIGN[14:17], "tail": 15, "heat": False,
          "dups": False, "flagged": 6, "unclassified": 25, "credits": 30, "dq": False, "plans": 0,
          "who": {"cm": "category.head", "cm2": "category.manager", "ph": "procurement.head", "cpo": "cpo", "st1": "mdm.purchasing", "st2": "mdm.finance",
                  "fin": "finance.controller", "admin": "admin"}},
}
# What each free-text description is (the steward's truth), by index in mock.FREE_TEXT
TRUTH = ["MRO", "MRO", "FACILITIES", "TOOLING-SERVICES", "OFFICE-SAFETY", "PROF-SERVICES", "PACKAGING", "MRO", "PROF-SERVICES", "SOFTWARE-LICENCES",
         "LOGISTICS", "FACILITIES", "FACILITIES", "OFFICE-SAFETY", "IT-HARDWARE", "MRO", "TOOLING-SERVICES", "FACILITIES", "PROF-SERVICES", "FACILITIES"]


class Ctx:
    def __init__(self, code: str, tenant_id: uuid.UUID, spec: dict):
        self.code, self.tenant_id, self.spec = code, tenant_id, spec
        self.sc = Scenario(tenant_id, tenant_code=code, domain=spec["domain"], role_user={})
        self.sup: dict[str, uuid.UUID] = {}
        self.counts: dict[str, int] = {}
        self.notes: list[str] = []

    def act(self, who: str, when: datetime):
        return self.sc.act(self.spec["who"].get(who, who), when)

    def count(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n


def ist(day: date, hour: int = 10, minute: int = 0) -> datetime:
    return at(day, hour, minute)


def _stage_done(ctx: Ctx, stage: str) -> bool:
    with tenant_tx(ctx.tenant_id) as s:
        return s.execute(select(AuditEvent.id).where(AuditEvent.object_type == "DATASET_STAGE", AuditEvent.object_ref == f"{KEY}:{stage}").limit(1)).first() is not None


def _stage_mark(ctx: Ctx, stage: str, **after) -> None:
    with tenant_tx(ctx.tenant_id) as s:
        audit.record(s, "DATASET_STAGE", uuid.uuid5(NS, f"{ctx.code}:{stage}"), "COMPLETED", object_ref=f"{KEY}:{stage}", actor=ACTOR, reason=LABEL, after=after)


# ================================================================ FX back-series
def load_fx(ctx: Ctx) -> int:
    """MOCK weekly (Monday) rates from 31 March 2025 to 30 March 2026 that continue the finance pack's curve; every rate that exists stays."""
    from app.pic.seed.datasets import finance_ops
    anchors = finance_ops.reference_anchors()
    mondays = [date(2025, 3, 31) + timedelta(days=7 * k) for k in range(53)]
    rows = []
    with tenant_tx(ctx.tenant_id) as s:
        have = {(f, d) for f, d in s.execute(select(FxRate.from_ccy, FxRate.valid_from).where(FxRate.to_ccy == "INR", FxRate.valid_from < D(4, 1)))}
        for code in ("USD", "EUR", "JPY", "CNY"):
            for day in mondays:
                if (code, day) not in have:
                    rows.append({"tenant_id": ctx.tenant_id, "from_ccy": code, "to_ccy": "INR", "rate": finance_mock.fx_rate(code, day, anchors), "valid_from": day,
                                 "source": "MOCK series (spend_ops)"})
        from app.pic.platform.core import insert_rows as ins
        ins(s, FxRate.__table__, rows)
    return len(rows)


def _rate_tables(ctx: Ctx) -> dict:
    """{currency: ([valid_from], [rate])} sorted, for the lookups of the bulk loader (no query per line)."""
    with tenant_tx(ctx.tenant_id) as s:
        rows = s.execute(select(FxRate.from_ccy, FxRate.valid_from, FxRate.rate).where(FxRate.to_ccy == "INR").order_by(FxRate.from_ccy.collate("C"), FxRate.valid_from)).all()
    tables: dict = {}
    for ccy, day, rate in rows:
        tables.setdefault(ccy, ([], []))
        tables[ccy][0].append(day)
        tables[ccy][1].append(rate)
    return tables


def _rate(tables: dict, currency: str, day: date) -> Optional[tuple]:
    if currency == "INR":
        return Decimal(1), day
    days, rates = tables.get(currency, ([], []))
    i = bisect_right(days, day) - 1
    return (rates[i], days[i]) if i >= 0 else None


# ================================================================ masters
def load_masters(ctx: Ctx) -> None:
    spec = ctx.spec
    wanted: list[dict] = []
    for sup in spec["foreign"]:
        wanted.append({"code": f"{sup[0]}" if ctx.code == KAC else sup[0].replace("MOCKF-", "MOCKF-A"), "name": sup[1], "country": sup[2], "category": sup[4], "payment_terms": "N60"})
    for t in mock.tail_suppliers(spec["tail"]):
        wanted.append({"code": t["code"] if ctx.code == KAC else t["code"].replace("MOCKT-", "MOCKT-A"), "name": t["name"], "country": "IN", "category": t["category"], "payment_terms": "N30"})
    if spec["heat"]:
        for category, (suppliers, *_rest) in mock.CONCENTRATED.items():
            for code, name, _ in suppliers:
                wanted.append({"code": code, "name": name, "country": "IN", "category": category, "payment_terms": "N45", "tier": "HIGH" if code == "MOCKH-001" else None})
    if spec["dups"]:
        for code, name, pan, _bank, category in mock.DUPLICATES:
            wanted.append({"code": code, "name": name, "country": "IN", "category": category, "payment_terms": "N45", "pan": pan})
    if spec["dq"]:
        wanted.append({"code": "MOCKK-001", "name": "Busan Precision Co Ltd", "country": "KR", "category": "TOOLING", "payment_terms": "N60"})   # DQ1: a currency with no rate at all
    with tenant_tx(ctx.tenant_id) as s:
        have = {x.code: x for x in s.execute(select(Supplier)).scalars()}
        for w in wanted:
            sup = have.get(w["code"])
            if sup is None:
                sup = Supplier(tenant_id=ctx.tenant_id, code=w["code"], legal_name=w["name"], status="QUALIFIED", country=w["country"], payment_terms=w["payment_terms"],
                               pan_hash=crypto.blind_index(ctx.tenant_id, w["pan"]) if w.get("pan") else None, risk_tier=w.get("tier"))
                s.add(sup)
                s.flush()
                s.add(SupplierCategoryStatus(tenant_id=ctx.tenant_id, supplier_id=sup.id, category=w["category"], status="QUALIFIED", qualified_on=D(4, 1, 2025)))
                ctx.count("suppliers")
            ctx.sup[w["code"]] = sup.id
        if spec["dups"]:
            existing_bank = set(s.execute(select(SupplierBankAccount.supplier_id)).scalars())
            for code, _name, _pan, bank, _cat in mock.DUPLICATES:
                if bank and ctx.sup[code] not in existing_bank:
                    s.add(SupplierBankAccount(tenant_id=ctx.tenant_id, supplier_id=ctx.sup[code], account_enc=crypto.encrypt(ctx.tenant_id, "bank", "MOCK" + bank[1][-4:]),
                                              account_masked=bank[1], ifsc=bank[0], holder_name=_name_of(code), active=True, verified_on=D(6, 1, 2025)))
        taxonomy = {n.code for n in s.execute(select(TaxonomyNode)).scalars()}
        for category in {"HEAT-TREATMENT", "SPECIAL-COATINGS", "OFFICE-SAFETY", "MRO-CHEMICALS", "MRO-LUBRICANTS", "IT-HARDWARE"} - taxonomy:
            s.add(TaxonomyNode(tenant_id=ctx.tenant_id, code=category, parent_code="DIRECT" if category in mock.CONCENTRATED else "INDIRECT", level=3,
                               name=category.replace("-", " ").title(), keywords=[w for w in category.lower().split("-") if len(w) > 3], addressable=True))
        existing_all = {x.code: x.id for x in s.execute(select(Supplier)).scalars()}
        ctx.sup.update(existing_all)


def _name_of(code: str) -> str:
    return next(d[1] for d in mock.DUPLICATES if d[0] == code)


# ================================================================ bulk lines
class Lines:
    """Rows of one batch family; every row carries the same keys (insert_rows)."""

    def __init__(self, ctx: Ctx, tables: dict):
        self.ctx, self.tables, self.rows, self.n = ctx, tables, [], 0
        self.user = None

    def add(self, family: str, key: str, *, supplier: str, category: str, period: str, amount: int, plant: str, currency: str = "INR", contracted: bool = False,
            flags: Optional[list] = None, description: str = "", po: Optional[str] = "x", source_system: str = "PIC", day: Optional[date] = None,
            confidence: Decimal = Decimal("1.000"), addressable: bool = True, variance: int = 0, material_group: Optional[str] = None,
            supplier_id: Optional[uuid.UUID] = None, rate_override: Optional[tuple] = None, buyer_id: Optional[uuid.UUID] = None) -> dict:
        doc = day or mock.doc_day(period, key)
        self.n += 1
        ref = f"{mock.MARK}/{family}/{self.ctx.code}/{self.n:06d}"
        rate = rate_override if rate_override is not None else _rate(self.tables, currency, doc)
        created = min(datetime.combine(doc + timedelta(days=1), datetime.min.time(), tzinfo=clock.IST).replace(hour=6), ist(BUSINESS_DAY, 6))
        row = {"tenant_id": self.ctx.tenant_id, "invoice_line_id": uuid.uuid5(NS, f"{self.ctx.code}|{ref}"), "invoice_ref": ref,
               "po_ref": f"MOCKPO-{self.ctx.code}-{self.n:06d}" if po else None, "supplier_id": supplier_id or self.ctx.sup[supplier], "category": category,
               "material_group": (material_group or category)[:30], "plant": plant, "company_code": self.ctx.spec["company"], "cost_object": None,
               "cost_object_type": None, "period": period, "amount_minor": amount, "currency": currency, "contracted": contracted, "addressable": addressable,
               "maverick_flags": flags or [], "classification_confidence": confidence, "description": (description or f"{category} {ref[-6:]}")[:300],
               "price_variance_minor": variance, "price_variance_last_minor": 0, "source": "ERP_HISTORY", "source_system": source_system,
               "fx_rate": rate[0] if rate and currency != "INR" else None, "fx_date": rate[1] if rate and currency != "INR" else None,
               "amount_group_minor": int((Decimal(amount) * rate[0]).quantize(Decimal(1), ROUND_HALF_UP)) if rate and rate[0] is not None and currency != "INR" else None,
               "document_type": "INVOICE", "document_ref": "", "document_date": doc, "buyer_id": buyer_id, "created_by": self.user, "created_at": created}
        self.rows.append(row)
        return row


def _existing_suppliers(ctx: Ctx, categories: set) -> dict:
    """Domestic suppliers that already have spend, per category, ordered by code (the pool the flagged cases draw from)."""
    with tenant_tx(ctx.tenant_id) as s:
        rows = s.execute(select(SpendLine.category, Supplier.code).join(Supplier, Supplier.id == SpendLine.supplier_id).where(
            ~Supplier.code.like("MOCK%"), SpendLine.source == "ERP_HISTORY", SpendLine.currency == "INR", SpendLine.addressable.is_(True)).distinct()).all()
    pool: dict = {}
    for category, code in rows:
        pool.setdefault(category, []).append(code)
    return {c: sorted(v) for c, v in pool.items()}


def build_lines(ctx: Ctx, tables: dict) -> Lines:
    spec, plants = ctx.spec, ctx.spec["plants"]
    out = Lines(ctx, tables)
    with tenant_tx(ctx.tenant_id) as s:
        out.user = s.execute(select(AppUser.id).where(AppUser.email == ctx.sc.email(spec["who"]["cm"]))).scalar_one()
        buyers = list(s.execute(select(AppUser.id).where(AppUser.roles.any("BUYER"), AppUser.active.is_(True)).order_by(AppUser.email.collate("C"))).scalars())
    pool = _existing_suppliers(ctx, set())
    all_periods = mock.periods()
    scale = 1.0 if ctx.code == KAC else 0.45
    # --- A foreign-currency lines on the second ERPs
    for sup in spec["foreign"]:
        code = sup[0] if ctx.code == KAC else sup[0].replace("MOCKF-", "MOCKF-A")
        for period in all_periods:
            n_lines = max(1, round(mock.lines_per_month(sup, period) * scale))
            for n in range(n_lines):
                amount, qty, price = mock.foreign_amount(sup, period, n)
                contracted = mock.unit("fc", code, period, n) < 0.62
                flags = ["PO_AFTER_INVOICE"] if mock.unit("ff", code, period, n) < 0.012 else []
                out.add("FX", f"{code}|{n}", supplier=code, category=sup[4], period=period, amount=max(amount, 100), plant=sup[6] if ctx.code == KAC else pick_plant(plants, code, n),
                        currency=sup[3], contracted=contracted, flags=flags, source_system=sup[5], po="x", description=f"{sup[4].title().replace('-', ' ')} {sup[3]} import lot {n + 1}",
                        buyer_id=buyers[int(mock.unit('b', code, n) * len(buyers))] if buyers else None)
    # --- B tail suppliers: small lines, 0-2 a month
    for t in mock.tail_suppliers(spec["tail"]):
        code = t["code"] if ctx.code == KAC else t["code"].replace("MOCKT-", "MOCKT-A")
        for period in all_periods:
            for n in range(int(mock.unit("tn", code, period) * 3)):
                out.add("TAIL", f"{code}|{n}", supplier=code, category=t["category"], period=period, amount=mock.tail_amount(code, period, n), plant=pick_plant(plants, code, n),
                        contracted=False, description=f"{t['category'].title().replace('-', ' ')} supplies {period}")
    # --- C concentration: HEAT-TREATMENT
    if spec["heat"]:
        for category in mock.CONCENTRATED:
            for period in all_periods:
                for n, (code, amount) in enumerate(mock.concentrated_lines(category, period)):
                    out.add("HEAT" if category == "HEAT-TREATMENT" else "COAT", f"{code}|{n}", supplier=code, category=category, period=period, amount=amount,
                            plant=pick_plant(plants, code, n), contracted=code in ("MOCKH-001", "MOCKH-004"), material_group=category,
                            description=f"{category.title().replace('-', ' ')} batch {period}-{n + 1:03d}")
    # --- D duplicate-cluster suppliers
    if spec["dups"]:
        for code, name, _pan, _bank, category in mock.DUPLICATES:
            for period in all_periods:
                for n in range(int(mock.unit("dn", code, period) * 3)):
                    out.add("DUP", f"{code}|{n}", supplier=code, category=category, period=period, amount=int((20_000 + 380_000 * mock.unit("da", code, period, n)) * 100),
                            plant=pick_plant(plants, code, n), contracted=False, description=f"{category.title().replace('-', ' ')} order {period}")
    # --- E maverick cases for the rules the tenant had none of
    for rule in mock.MAVERICK_RULES_NEW:
        for n in range(spec["flagged"]):
            category = pick_category(pool, rule, n)
            supplier = mock.pick(pool[category], rule, n, "sup")
            period = mock.pick(all_periods[6:], rule, n, "per")
            amount = int((50_000 + 5_500_000 * mock.unit("ma", rule, n) ** 2) * 100)
            variance = int(amount * (0.04 + 0.05 * mock.unit("mv", rule, n))) if rule == "OFF_CONTRACT_PRICE" else 0
            out.add(f"MAV-{rule}", f"{rule}|{n}", supplier=supplier, category=category, period=period, amount=amount, plant=pick_plant(plants, rule, n),
                    contracted=rule == "OFF_CONTRACT_PRICE", flags=[rule], variance=variance, description=f"{category.title().replace('-', ' ')} {rule.lower().replace('_', ' ')} case {n + 1}")
    # --- F unclassified free text for the steward queue (the classifier's proposal is added when the rows are loaded)
    for n in range(spec["unclassified"]):
        text_i = n % len(mock.FREE_TEXT)
        period = mock.pick(all_periods[10:], "uc", n)
        big = n < 6                                       # six lines above the four-eyes value
        amount = int((3_100_000 + 1_800_000 * mock.unit("ub", n)) * 100) if big else int((8_000 + 380_000 * mock.unit("ua", n)) * 100)
        category = mock.pick(sorted(pool), "ucat", n)
        out.add("UNCL", f"{n}", supplier=mock.pick(pool[category], "usup", n), category="UNCLASSIFIED", period=period, amount=amount, plant=pick_plant(plants, "u", n),
                description=mock.FREE_TEXT[text_i] + (f" ({n // len(mock.FREE_TEXT) + 1})" if n >= len(mock.FREE_TEXT) else ""), confidence=Decimal("0.000"),
                material_group="FREE-TEXT")
    # --- G credit memos: negative lines that net against the supplier's invoices
    for n in range(spec["credits"]):
        category = pick_category(pool, "credit", n)
        out.add("CRM", f"{n}", supplier=mock.pick(pool[category], "csup", n), category=category, period=mock.pick(all_periods[2:], "cper", n),
                amount=-int((15_000 + 640_000 * mock.unit("cm", n)) * 100), plant=pick_plant(plants, "c", n), contracted=mock.unit("cc", n) < 0.5,
                description=f"Credit memo: {mock.pick(['rejected lot return', 'volume rebate', 'price correction', 'freight recovery'], 'cd', n)}")
    # --- H deliberate data-quality defects
    if spec["dq"]:
        add_defects(ctx, out, pool, tables)
    return out


def add_defects(ctx: Ctx, out: Lines, pool: dict, tables: dict) -> None:
    plants = ctx.spec["plants"]
    krw = ctx.sup["MOCKK-001"]
    for n in range(20):      # DQ1: a currency without any rate
        period = mock.pick(mock.periods()[2:11], "dq1", n)
        out.add("DQ1", f"{n}", supplier="MOCKK-001", category="TOOLING", period=period, amount=int((900_000 + 4_000_000 * mock.unit("dq1a", n)) * 100), plant=plants[0],
                currency="KRW", source_system="SAP-APAC", description=f"[MOCK DQ1] Fine-blanking die insert KRW invoice {n + 1}", rate_override=(None, None), supplier_id=krw)
    base = [r for r in out.rows if r["invoice_ref"].startswith(f"{mock.MARK}/FX/")][:6]
    for n, source in enumerate(base):      # DQ2: loaded twice
        copy = dict(source)
        out.n += 1
        copy["invoice_ref"] = source["invoice_ref"]
        copy["invoice_line_id"] = uuid.uuid5(NS, f"{ctx.code}|DQ2|{n}")
        copy["description"] = source["description"]
        out.rows.append(copy)
    for n in range(5):      # DQ3: category typo
        out.add("DQ3", f"{n}", supplier=mock.pick(pool["FASTENERS"], "dq3", n), category="FASTNERS", period=mock.pick(mock.periods(), "dq3p", n), amount=int((12_000 + 50_000 * mock.unit("dq3a", n)) * 100),
                plant=plants[1], description=f"[MOCK DQ3] Hex bolt M10 (category typed FASTNERS) {n + 1}")
    for n in range(3):      # DQ4: zero value
        out.add("DQ4", f"{n}", supplier=mock.pick(pool["MRO"], "dq4", n), category="MRO", period=mock.pick(mock.periods(), "dq4p", n), amount=0, plant=plants[2],
                description=f"[MOCK DQ4] Zero-value delivery note {n + 1}")
    for n in range(40):     # DQ5: no order reference
        category = pick_category(pool, "dq5", n)
        out.add("DQ5", f"{n}", supplier=mock.pick(pool[category], "dq5s", n), category=category, period=mock.pick(mock.periods(), "dq5p", n),
                amount=int((5_000 + 70_000 * mock.unit("dq5a", n)) * 100), plant=plants[n % 3], po=None, description=f"[MOCK DQ5] Non-PO invoice {n + 1}")
    safety = pool.get("OFFICE-SAFETY") or pool["MRO"]       # a small category, in a month before the two fiscal years the analysis compares
    out.add("DQ6", "0", supplier=mock.pick(safety, "dq6"), category="OFFICE-SAFETY" if "OFFICE-SAFETY" in pool else "MRO", period="2025-03", amount=60 * 10_000_000 * 100,
            plant=plants[0], day=date(2025, 3, 12), description="[MOCK DQ6] Safety consumables, quantity typed with two zeros too many (Rs 60 crore)")
    with tenant_tx(ctx.tenant_id) as s:
        ic = s.execute(select(Supplier.id).where(Supplier.segment == "INTERCOMPANY").order_by(Supplier.code.collate("C"))).scalars().first()
    if ic is not None:
        for n in range(2):  # DQ7: intercompany counted as addressable
            out.add("DQ7", f"{n}", supplier="", supplier_id=ic, category="MRO", period="2026-07", amount=int((200_000 + 90_000 * n) * 100), plant=plants[0],
                    description=f"[MOCK DQ7] Group company stock transfer {n + 1}", addressable=True)
    for n in range(2):      # DQ8: supplier not in the master
        out.add("DQ8", f"{n}", supplier="", supplier_id=uuid.uuid5(NS, f"{ctx.code}|ghost|{n}"), category="MRO", period="2026-08", amount=int((30_000 + 5_000 * n) * 100),
                plant=plants[1], description=f"[MOCK DQ8] Invoice of a deleted vendor {n + 1}")


def pick_plant(plants: list, *parts) -> str:
    return plants[int(mock.unit("plant", *parts) * len(plants))]


def pick_category(pool: dict, *parts) -> str:
    cats = sorted(pool)
    return cats[int(mock.unit("pc", *parts) * len(cats))]


def load_lines(ctx: Ctx, tables: dict) -> dict:
    """Insert the generated lines, one transaction per batch, and the hits / reviews that belong to the flagged and the unclassified ones."""
    lines = build_lines(ctx, tables)
    rows = lines.rows
    with tenant_tx(ctx.tenant_id) as s:
        done = set(s.execute(select(SpendLine.invoice_line_id).where(SpendLine.invoice_ref.like(f"{mock.MARK}/%"))).scalars())
    rows = [r for r in rows if r["invoice_line_id"] not in done]
    for start in range(0, len(rows), BATCH):
        with tenant_tx(ctx.tenant_id) as s:
            insert_rows(s, SpendLine.__table__, rows[start:start + BATCH])
    ctx.count("lines", len(rows))
    flagged = [r for r in rows if r["maverick_flags"] and "/MAV-" in r["invoice_ref"]]
    unclassified = [r for r in rows if "/UNCL/" in r["invoice_ref"]]
    ctx.count("hitsInserted", add_hits(ctx, flagged))
    result = add_reviews(ctx, unclassified)
    ctx.count("reviewsInserted", result["reviews"])
    ctx.count("autoClassified", result["auto"])
    return {"lines": len(rows)}


def add_hits(ctx: Ctx, rows: list) -> int:
    """Hit rows for the flagged lines, shaped like evaluate_line shapes them (owner by rule, SLA from the document date, savings at risk)."""
    from app.pic.services import spend
    if not rows:
        return 0
    with tenant_tx(ctx.tenant_id) as s:
        rules = {r.code: r for r in s.execute(select(MaverickRule)).scalars()}
        numbers = next_numbers(s, "MAVERICK_HIT", len(rows))
        owner_cache: dict = {}
        out = []
        ids = dict(s.execute(select(SpendLine.invoice_line_id, SpendLine.id).where(SpendLine.invoice_line_id.in_([r["invoice_line_id"] for r in rows]))).all())
        for row, number in zip(rows, numbers):
            code = row["maverick_flags"][0]
            rule = rules[code]
            key = (rule.owner_role, row["category"])
            if key not in owner_cache:
                owner_cache[key] = spend._owner(s, rule.owner_role, row["category"])
            created = datetime.combine(row["document_date"] + timedelta(days=2), datetime.min.time(), tzinfo=clock.IST).replace(hour=9)
            created = min(created, ist(BUSINESS_DAY - timedelta(days=1), 9))
            line_id = ids[row["invoice_line_id"]]
            excess = int(row["amount_minor"] * 0.18) if code == "OVER_INVOICED" else 0
            out.append({"tenant_id": ctx.tenant_id, "number": number, "rule_code": code, "spend_line_id": line_id, "invoice_ref": row["invoice_ref"], "po_ref": row["po_ref"],
                        "supplier_id": row["supplier_id"], "category": row["category"], "amount_minor": row["amount_minor"], "amount_group_minor": abs(row["amount_minor"]),
                        "owner_role": rule.owner_role, "owner_id": owner_cache[key], "status": "OPEN", "due_at": created + timedelta(days=rule.sla_days or 10),
                        "savings_at_risk_minor": row["price_variance_minor"] if code in ("OFF_CONTRACT", "OFF_CONTRACT_PRICE") else excess, "escalation_level": 0,
                        "created_by": row["created_by"], "created_at": created})
        insert_rows(s, MaverickHit.__table__, out)
    return len(out)


def add_reviews(ctx: Ctx, rows: list) -> dict:
    """The classifier's proposal for every unclassified line: confident results are applied, the rest become OPEN reviews with an SLA."""
    from app.pic.services import spend
    out = {"reviews": 0, "auto": 0}
    if not rows:
        return out
    with tenant_tx(ctx.tenant_id) as s:
        nodes = spend._nodes(s)
        threshold = Decimal(str(spend.gov(s)["classificationThreshold"]))
        reviews, auto = [], []
        ids = dict(s.execute(select(SpendLine.invoice_line_id, SpendLine.id).where(SpendLine.invoice_line_id.in_([r["invoice_line_id"] for r in rows]))).all())
        review_days = int(spend.gov(s)["reviewSlaDays"])
        for row in rows:
            line_id = ids[row["invoice_line_id"]]
            category, confidence, alternatives = spend.classify_text(s, row["description"], row["supplier_id"], nodes)
            created = min(datetime.combine(row["document_date"] + timedelta(days=2), datetime.min.time(), tzinfo=clock.IST).replace(hour=9), ist(BUSINESS_DAY - timedelta(days=1), 9))
            if confidence >= threshold:
                auto.append((line_id, category, confidence))
                continue
            reviews.append({"tenant_id": ctx.tenant_id, "spend_line_id": line_id, "invoice_ref": row["invoice_ref"], "description": row["description"][:300],
                            "proposed_category": category, "confidence": confidence, "alternatives": alternatives, "status": "OPEN",
                            "value_group_minor": abs(row["amount_minor"]), "due_at": created + timedelta(days=review_days), "channel": "AGENT",
                            "created_by": row["created_by"], "created_at": created})
            s.execute(text("UPDATE pic.spend_line SET classification_confidence = :c WHERE id = :i"), {"c": confidence, "i": line_id})
        for line_id, category, confidence in auto:
            s.execute(text("UPDATE pic.spend_line SET category = :cat, classification_confidence = :c WHERE id = :i"), {"cat": category, "c": confidence, "i": line_id})
        insert_rows(s, ClassificationReview.__table__, reviews)
        out["reviews"], out["auto"] = len(reviews), len(auto)
    return out


# ================================================================ workflow through the services
def work_reviews(ctx: Ctx) -> None:
    """Steward decisions through spend.decide_review / spend_workflow.bulk_reclassify (the roles, scope, four-eyes and audit of production)."""
    from app.pic.services import spend, spend_workflow
    with tenant_tx(ctx.tenant_id) as s:
        open_ = [(str(r.id), r.description, r.proposed_category, r.value_group_minor or 0) for r in s.execute(
            select(ClassificationReview).where(ClassificationReview.status == "OPEN", ClassificationReview.invoice_ref.like(f"{mock.MARK}/UNCL/{ctx.code}/%"))
            .order_by(ClassificationReview.created_at, ClassificationReview.invoice_ref.collate("C"))).scalars()]
    if not open_:
        return
    def truth(desc: str) -> str:
        base = desc.split(" (")[0]
        return TRUTH[mock.FREE_TEXT.index(base)] if base in mock.FREE_TEXT else "MRO"
    big = [o for o in open_ if o[3] >= 250_000_000][:4]
    small = [o for o in open_ if o not in big]
    acceptable = [o for o in small if o[2] != "UNCLASSIFIED"][:12]    # a proposal of "unclassified" is not a category a steward can accept
    reclassify = [o for o in small if o not in acceptable]
    day = D(10, 5)
    for k, (rid, desc, proposed, _) in enumerate(acceptable):          # accepted as proposed
        with ctx.act("cm", ist(day + timedelta(days=k % 12), 10 + k % 6)) as s:
            spend.decide_review(s, s.get(ClassificationReview, uuid.UUID(rid)), proposed, "Accepted: the proposal matches the invoice text (MOCK)")
            ctx.count("reviewsAccepted")
    for k, (rid, desc, proposed, _) in enumerate(reclassify[:12]):     # reclassified
        category = truth(desc)
        with ctx.act("cm", ist(D(10, 14) + timedelta(days=k % 10), 11)) as s:
            spend.decide_review(s, s.get(ClassificationReview, uuid.UUID(rid)), category, "Reclassified by the category manager after reading the invoice (MOCK)",
                                reason="checked against the purchase order text")
            ctx.count("reviewsReclassified")
    # four-eyes: 1 confirmed by a second steward, 1 left waiting for its second steward, 1 disagreed (back in the queue), 1 untouched
    for k, (rid, desc, proposed, _) in enumerate(big[:3]):
        category = truth(desc) if truth(desc) != proposed else "MRO-CHEMICALS"
        with ctx.act("cm", ist(D(10, 20) + timedelta(days=k), 10)) as s:
            spend.decide_review(s, s.get(ClassificationReview, uuid.UUID(rid)), category, "First decision above the four-eyes value (MOCK)")
            ctx.count("reviewsParked")
        if k == 0:
            with ctx.act("st1", ist(D(10, 22), 15)) as s:
                spend.decide_review(s, s.get(ClassificationReview, uuid.UUID(rid)), category, "Second steward confirms (MOCK)")
                ctx.count("reviewsFourEyesConfirmed")
        elif k == 1:
            with ctx.act("st1", ist(D(10, 23), 15)) as s:
                other = "FACILITIES" if category != "FACILITIES" else "TOOLING-SERVICES"
                spend.decide_review(s, s.get(ClassificationReview, uuid.UUID(rid)), other, "Second steward disagrees: back to the queue (MOCK)")
                ctx.count("reviewsFourEyesDisagreed")
    # a bulk decision that teaches the classifier a word: the description with the most open reviews, its steward truth, a word no category owns yet
    with tenant_tx(ctx.tenant_id) as s:
        remaining = [r.description for r in s.execute(select(ClassificationReview).where(
            ClassificationReview.status == "OPEN", ClassificationReview.invoice_ref.like(f"{mock.MARK}/UNCL/{ctx.code}/%"))).scalars()]
    groups: dict = {}
    for desc in remaining:
        groups.setdefault(desc.split(" (")[0], []).append(desc)
    if groups:
        phrase = max(sorted(groups), key=lambda k: len(groups[k]))
        category = truth(phrase)
        with ctx.act("cm", ist(D(10, 27), 12)) as s:
            word = None
            for candidate in [w.strip(",.").lower() for w in phrase.split()]:
                try:
                    word = spend.learnable_keyword(s, candidate, category)
                    break
                except Problem:
                    continue
            try:
                result = spend_workflow.bulk_reclassify(s, category, text_=phrase, comment=f"'{phrase}' is {category.lower().replace('-', ' ')} spend (MOCK)", learn_keyword=word)
                ctx.count("reviewsBulk", sum(1 for r in result["results"] if r["status"] in ("RECLASSIFIED", "ACCEPTED", "PENDING_SECOND")))
                ctx.notes.append(f"bulk decision: '{phrase}' -> {category}, keyword '{word}'")
            except Problem as exc:
                ctx.notes.append(f"bulk reclassification skipped: {exc.code}")


HIT_PLAN = ["ACCEPTED_EXCEPTION", "POLICY_BREACH", "FALSE_POSITIVE", "RECOVERY", "RECOVERY_RESOLVED", "ACCEPTED_EXCEPTION", "POLICY_BREACH", "RECOVERY", "FALSE_POSITIVE"]
REASONS = {"ACCEPTED_EXCEPTION": ["EMERGENCY_BREAKDOWN", "SOLE_SOURCE", "SUPPLIER_CHANGE_PENDING", "CATALOGUE_GAP"],
           "FALSE_POSITIVE": ["DATA_ERROR", "RULE_TOO_BROAD", "CONTRACT_NOT_LOADED"]}


def work_hits(ctx: Ctx) -> None:
    """Dispositions through spend.dispose / resolve_recovery in every state, then the SLA escalation through spend.escalate_overdue."""
    from app.pic.services import spend
    with tenant_tx(ctx.tenant_id) as s:
        by_rule: dict = {}
        for h in s.execute(select(MaverickHit).where(MaverickHit.status == "OPEN").order_by(MaverickHit.rule_code, MaverickHit.amount_group_minor.nulls_last(), MaverickHit.number.collate("C"))).scalars():
            by_rule.setdefault(h.rule_code, []).append((str(h.id), h.owner_role, int(h.amount_group_minor or h.amount_minor)))
    per_rule = 9 if ctx.code == KAC else 4
    day = D(10, 8)
    for r_index, (rule, hits) in enumerate(sorted(by_rule.items())):
        for k, (hid, owner_role, value) in enumerate(hits[:per_rule]):
            kind = HIT_PLAN[(k + r_index) % len(HIT_PLAN)]
            who = {"CATEGORY_MANAGER": "cm", "PROCUREMENT_HEAD": "ph", "FINANCE_CONTROLLER": "fin"}.get(owner_role, "ph")
            when = ist(day + timedelta(days=(k * 3 + r_index) % 24), 9 + (k + r_index) % 8)
            disposition = "RECOVERY" if kind.startswith("RECOVERY") else kind
            reasons = REASONS.get(disposition)
            with ctx.act(who, when) as s:
                hit = s.get(MaverickHit, uuid.UUID(hid))
                try:
                    spend.dispose(s, hit, disposition, f"{disposition.replace('_', ' ').title()}: reviewed with the buyer and the supplier (MOCK)",
                                  reason_code=mock.pick(reasons, hid) if reasons else None)
                    ctx.count(f"hits{disposition}")
                except Problem as exc:
                    ctx.notes.append(f"{hit.number}: {exc.code}")
                    continue
                if kind == "RECOVERY_RESOLVED":
                    spend.resolve_recovery(s, hit, max(1, int(value * 0.6)), f"Credit note received for {hit.number} (MOCK)")
                    ctx.count("hitsResolved")
    with ctx.act("ph", ist(BUSINESS_DAY, 9)) as s:
        escalated = spend.escalate_overdue(s, ist(BUSINESS_DAY, 9))
        ctx.count("hitsEscalated", len(escalated))
    with ctx.act("ph", ist(BUSINESS_DAY, 10)) as s:          # second level for the oldest
        escalated = spend.escalate_overdue(s, ist(BUSINESS_DAY, 10) + timedelta(days=4))
        ctx.count("hitsEscalatedAgain", len(escalated))


def work_rule_version(ctx: Ctx) -> None:
    from app.pic.services import spend_workflow
    with ctx.act("admin", ist(D(10, 1), 9)) as s:
        try:
            spend_workflow.set_rule_version(s, "NON_CATALOGUE", effective_from=D(10, 1), reason="Catalogue coverage is thin: longer SLA until the supplier catalogues are loaded (MOCK)", sla_days=15)
            ctx.count("ruleVersions")
        except Problem as exc:
            ctx.notes.append(f"rule version: {exc.code}")


def work_duplicates(ctx: Ctx) -> None:
    """Scan, one merge proposed and approved by a second steward, one proposed and waiting, one dismissed, the rest open."""
    if not ctx.spec["dups"]:
        return
    from app.pic.services import spend_workflow
    with ctx.act("st1", ist(D(10, 12), 10)) as s:
        ctx.count("duplicateClusters", spend_workflow.scan_duplicates(s)["new"])
    keys = {}
    with tenant_tx(ctx.tenant_id) as s:
        for c in spend_workflow.find_clusters(s):
            keys[tuple(sorted(x.code for x in c["suppliers"]))] = c["key"]
    with ctx.act("cm", ist(D(10, 13), 11)) as s:
        proposal = spend_workflow.propose_merge(s, keys[("MOCKD-101", "MOCKD-102")], "MOCKD-101", "Same PAN and the same bank account: one supplier (MOCK)")
        number = proposal.proposal_number
        spend_workflow.propose_merge(s, keys[("MOCKD-201", "MOCKD-202", "MOCKD-203")], "MOCKD-201", "Name variants of one packaging supplier at Hosur (MOCK)")
        ctx.count("mergesProposed", 2)
    with ctx.act("st2", ist(D(10, 14), 10)) as s:
        task = next(t for t in s.execute(select(Task).where(Task.object_ref == number, Task.status == "OPEN")).scalars())
        workflow.complete(s, task.id, "APPROVE", "Confirmed against the GST portal and the bank mandate (MOCK)")
        ctx.count("mergesApproved")
    with ctx.act("st1", ist(D(10, 15), 10)) as s:
        spend_workflow.dismiss_cluster(s, keys[("MOCKD-401", "MOCKD-402")], "Two group companies with separate GSTINs: not duplicates (MOCK decision)")
        ctx.count("clustersDismissed")


def work_plans(ctx: Ctx) -> None:
    n_plans = ctx.spec["plans"]
    if not n_plans:
        return
    from app.pic.services import spend, spend_cube, spend_workflow
    fy = clock.fiscal_year(D(10, 20))
    with tenant_tx(ctx.tenant_id) as s:
        top = [c for c, in s.execute(select(spend_cube.C.category).where(spend_cube.C.period.between("2025-11", "2026-10"), spend_cube.C.addressable.is_(True),
                                                                          spend_cube.C.category != "UNCLASSIFIED").group_by(spend_cube.C.category)
                                     .order_by(func.sum(spend_cube.C.amount_group_minor).desc(), spend_cube.C.category.collate("C")).limit(n_plans))]
    if ctx.spec["heat"]:    # the concentrated categories and one indirect category are planned too, so the plans span the Kraljic quadrants
        extra = ["HEAT-TREATMENT", "SPECIAL-COATINGS", "MRO"]
        top = [c for c in top if c not in extra][:n_plans - len(extra)] + extra
    with ctx.act("cm", ist(D(10, 20), 10)) as s:
        plans = spend.generate_plans(s, fy, s.info["principal"].user_id, categories=top)
        numbers = [p.number for p in sorted(plans, key=lambda p: -p.spend_minor)]
        ctx.count("plans", len(numbers))
    with ctx.act("cm", ist(D(10, 21), 10)) as s:                   # 0-2 stay drafts; plan 0 is edited first
        p0 = spend.get_plan(s, numbers[0])
        spend_workflow.update_plan(s, p0, savings_target_minor=int(p0.savings_target_minor * 0.9))
    for k in (3, 4, 5):                                           # submitted
        with ctx.act("cm", ist(D(10, 22) + timedelta(days=k - 3), 10)) as s:
            spend_workflow.submit_plan(s, spend.get_plan(s, numbers[k]), "Ready for approval (MOCK)")
            ctx.count("plansSubmitted")
    for k in (3, 5):                                              # approved through the inbox task
        with ctx.act("ph", ist(D(10, 27), 10 + k)) as s:
            task = next(t for t in s.execute(select(Task).where(Task.kind == spend_workflow.PLAN_TASK, Task.object_ref == numbers[k],
                                                                           Task.status == "OPEN")).scalars())
            workflow.complete(s, task.id, "APPROVE", "Approved at the category review (MOCK)")
            ctx.count("plansApproved")
    with ctx.act("cm", ist(D(10, 28), 10)) as s:                  # an approved plan is revised: a new draft version
        spend_workflow.revise_plan(s, spend.get_plan(s, numbers[5]), "Budget re-cut after the Q2 forecast (MOCK)")
        ctx.count("plansRevised")
    with ctx.act("cpo", ist(D(10, 29), 10)) as s:                 # direct approval by the CPO (no submission needed in this tenant)
        spend.approve_plan(s, spend.get_plan(s, numbers[6]), "Approved by the CPO (MOCK)")
        ctx.count("plansApproved")
    with ctx.act("ph", ist(D(10, 30), 10)) as s:
        spend_workflow.reject_plan(s, spend.get_plan(s, numbers[7]), "Savings target not credible against the contract position; rework (MOCK)")
        ctx.count("plansRejected")


def load_forecast_history(ctx: Ctx) -> int:
    """Forecasts as issued for April to September 2026: the real method on the spend known at the end of the previous month, 6 months ahead."""
    from app.pic.services import spend_cube, spend_forecast
    rows = []
    with tenant_tx(ctx.tenant_id) as s:
        C = spend_cube.C
        series: dict = {}
        for category, period, amount in s.execute(select(C.category, C.period, func.sum(C.amount_group_minor)).group_by(C.category, C.period)):
            series.setdefault(category, {})[period] = int(amount)
        top = sorted(series, key=lambda c: -sum(series[c].values()))[:24]
        all_periods = sorted({p for v in series.values() for p in v})
        existing = {(r.as_of_period, r.category, r.period) for r in s.execute(select(SpendForecastSnapshot)).scalars()}
    for as_of in ("2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"):
        known = [p for p in all_periods if p <= as_of]
        for category in top:
            ys = [series[category].get(p, 0) for p in known]
            first = next((i for i, y in enumerate(ys) if y), len(ys))
            result = spend_forecast.forecast_series(ys[first:], 6)
            if not result:
                continue
            for h, period in enumerate(spend_forecast._months(as_of, 6), start=1):
                if (as_of, category, period) in existing:
                    continue
                mid, low, high = result["points"][h - 1]
                rows.append({"tenant_id": ctx.tenant_id, "as_of_period": as_of, "category": category, "plant": "", "period": period, "horizon": h, "method": result["method"],
                             "forecast_minor": int(mid), "low_minor": int(low), "high_minor": int(high),
                             "created_at": datetime.combine(date(int(as_of[:4]), int(as_of[5:]), 1) + timedelta(days=32), datetime.min.time(), tzinfo=clock.IST).replace(day=2, hour=6)})
    with tenant_tx(ctx.tenant_id) as s:
        insert_rows(s, SpendForecastSnapshot.__table__, rows)
    return len(rows)


# ================================================================ the pack
def refresh_cube(ctx: Ctx) -> dict:
    from app.pic.services import spend_cube
    with tenant_tx(ctx.tenant_id) as s:
        return spend_cube.refresh(s, record_audit=False)["cube"]


def apply(tenant_code: str, password: str) -> dict:
    spec = SPECS.get(tenant_code)
    if spec is None:
        raise ValueError(f"{KEY} loads tenants {', '.join(SPECS)} only")
    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == tenant_code)).scalar_one()
    ctx = Ctx(tenant_code, tenant_id, spec)
    import time as _time
    started = _time.perf_counter()
    timings: dict = {}
    try:
        clock.set_pinned(ist(D(10, 1), 8))
        from app.pic.services import spend, spend_feed, spend_quality
        with tenant_tx(tenant_id) as s:
            spend.ensure_taxonomy(s, tenant_id)
        if spec["dq"]:   # the tenant's outlier limit: a single line above Rs 25 crore is a unit error until proven otherwise (rule SPEND-GOVERNANCE.outlierAmountMinor)
            kit.rule_version(ctx.sc, "SPEND-GOVERNANCE", "2026.3-MOCK-SPEND", D(10, 1), {"outlierAmountMinor": 25 * 10_000_000 * 100},
                             "MOCK (spend_ops): outlier limit per spend line for the data-quality check")
        steps = [
            ("fx", lambda: ctx.count("fxRates", load_fx(ctx))),
            ("masters", lambda: load_masters(ctx)),
        ]
        for name, fn in steps:
            t0 = _time.perf_counter()
            fn()
            timings[name] = round(_time.perf_counter() - t0, 1)
        load_masters(ctx)                                         # idempotent: fills ctx.sup when the masters stage was skipped earlier
        t0 = _time.perf_counter()
        tables = _rate_tables(ctx)
        load_lines(ctx, tables)
        timings["lines"] = round(_time.perf_counter() - t0, 1)
        t0 = _time.perf_counter()
        with ctx.act("cm", ist(D(10, 2), 8)) as s:                # the credit and debit notes recorded before the cube knew them
            ctx.count("notesBackfilled", sum(spend_feed.backfill_notes(s).values()))
        ctx.count("cubePeriods", refresh_cube(ctx)["periods"])
        timings["cube1"] = round(_time.perf_counter() - t0, 1)
        t0 = _time.perf_counter()
        work_rule_version(ctx)
        work_reviews(ctx)
        work_hits(ctx)
        work_duplicates(ctx)
        timings["workflow1"] = round(_time.perf_counter() - t0, 1)
        t0 = _time.perf_counter()
        ctx.count("cubePeriods2", refresh_cube(ctx)["periods"])    # plans and the forecast history read the cube after the reclassifications
        work_plans(ctx)
        ctx.count("forecastSnapshots", load_forecast_history(ctx))
        timings["plans_forecast"] = round(_time.perf_counter() - t0, 1)
        with ctx.act("cm", ist(BUSINESS_DAY, 11)) as s:
            report = spend_quality.assess(s, persist=True)
            ctx.count("qualityRuns")
            ctx.notes.append(f"data-quality score {report['score']} ({', '.join(report['failing']) or 'no failing check'})")
        refresh_cube(ctx)
        with system_tx() as s:   # fresh planner statistics right after the bulk load: the first read of the quality report must not wait for autovacuum's analyze
            s.execute(text("ANALYZE pic.spend_line, pic.spend_cube_summary, pic.supplier, pic.classification_review, pic.maverick_hit, pic.spend_commitment_summary"))
    finally:
        clock.set_pinned(None)
    with tenant_tx(tenant_id) as s:
        totals = s.execute(select(func.count(), func.coalesce(func.sum(SpendLine.amount_minor), 0)).where(SpendLine.invoice_ref.like(f"{mock.MARK}/%"))).one()
    ctx.counts["mockLines"] = int(totals[0])
    return {"notes": ctx.notes[:20], "counts": ctx.counts, "seconds": round(_time.perf_counter() - started, 1), "timings": timings}
