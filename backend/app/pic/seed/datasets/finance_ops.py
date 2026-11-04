"""D15 Finance datasets for the demo tenants AXN and KAC: MOCK (ILLUSTRATIVE SAMPLE; the real values need the customer's data and sign-off).

The finance module (M10, flow F7) needs, before it can show a working accounts-payable function, a payment history, exception and note
workloads, tax master data, exchange rates, closed periods, bank statements and treasury rule values. Until the customer supplies them, this pack
fills each with clearly labelled mock values and builds the documents THROUGH THE REAL SERVICES (payables, bank_files, bank_statement,
debit_notes, early_payment, finance_controls) with the business clock pinned to each document's date, so state machines, SoD, audit hash chains,
outbox events, ERP messages and GR/IR behave as in production. Everything is deterministic (document numbers seed every choice, nothing is
random), idempotent (a stage recorded in the audit trail is skipped; every document is looked up by its business key before it is created; a value
that is set is never overwritten) and traceable (``MOCK`` in names, notes, reasons, rule descriptions and ``data/erp_mock/KAC_FINANCE/README.md``).

KAC (first client; one company code 1000, plants 1100 Hosur, 1200 Oragadam, 1300 Bidadi), business dates 1 September to 31 October 2026:
  config      rule versions MSME (MOCK bank rate), TDS (MOCK, pending tax sign-off), PAYMENT-FILE (MOCK debtor accounts), PAYMENT-RUN; users with
              approval limits; supplier PAN / TDS section / MSME class / Udyam; s.197 certificates; the FX series; supplier portal users
  documents   goods receipts and supplier invoices on the open purchase orders (clean, price / quantity / missing-GR / tax / duplicate exceptions in
              every resolution state, rejected, disputed, foreign-currency imports), credit and debit notes, early-payment offers and SCF
  payments    seven payment runs (18 Sep, then October), pain.001 / NEFT files, bank acknowledgements, TDS withheld, MSME suppliers paid inside
              45 days and breached with interest, returned payments reversed through the real return path
  bank        camt.053 and MT940 statements built from the pack's own payments and imported through the real importer
  periods     April to September 2026 closed with a GR/IR snapshot per close, September reopened and closed again once, October left open
AXN: non-signature additions only (FX series, closed periods before the signature case, one s.197 certificate, PAN / TDS / MSME on its suppliers,
credit and debit notes on non-signature invoices, one returned payment); no existing AXN document is changed.

Requires ``inventory-master`` (the last pack that leaves KAC's masters and users in their go-live state).
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, Optional

from sqlalchemy import func, insert, select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuditEvent, Currency, FxRate, Invoice, RuleSet, Supplier, SupplierBankAccount, SupplierCategoryStatus, TdsCertificate, Tenant,
)
from app.pic.platform import audit, clock
from app.pic.platform import finance_defaults
from app.pic.seed.axion import Scenario, at
from app.pic.seed.datasets import _tenant_kit as kit
from app.pic.tools import finance_mock as mock

log = logging.getLogger(__name__)

KEY = "finance-ops"
VERSION = "1"
TITLE = "D15 Finance datasets for AXN and KAC: payment history, exceptions, notes, tax data, FX, periods, bank statements, treasury rules (MOCK, ILLUSTRATIVE SAMPLE)"
TENANTS = ("AXN", "KAC")
CREATES_TENANT = False
READY = True
REQUIRES = {"inventory-master": "1"}

LABEL = mock.TAG
ACTOR = "mock-data:finance_ops"
L = 100_000 * 100                                   # one lakh rupees in paise
RULE_VERSION = "2026.2-KAC-MOCK"
RULE_EFFECTIVE = date(2026, 9, 1)
MSME_BANK_RATE = "6.50"                             # MOCK: the RBI bank rate the tenant's treasury must confirm (rule MSME.bankRatePct)
PREFIX = "FO26"                                     # supplier invoice numbers of the pack: FO26/<supplier>/<nnnn>

KAC = "KAC"
AXN = "AXN"


def D(month: int, day: int, year: int = 2026) -> date:
    return date(year, month, day)


# ------------------------------------------------------------------------------------------------ tenant specs
KAC_ROLE_USER = {}   # filled lazily from erp_client_kac.ROLE_USER (import cycle free)


def _kac_roles() -> dict:
    from app.pic.seed.datasets import erp_client_kac
    return {**erp_client_kac.ROLE_USER, "AP_CLERK": ["ap.clerk"], "FINANCE_CONTROLLER": ["fin.controller.1", "fin.controller.2"]}


SPECS = {
    KAC: {"domain": "kaveri-auto.example", "company": "1000", "plants": ["1100", "1200", "1300"],
          "receivers": {"1100": "receiver.hosur", "1200": "receiver.oragadam", "1300": "receiver.bidadi"}},
    AXN: {"domain": "axion.example", "company": "1000", "plants": ["P100", "P200"], "receivers": {"P100": "receiver", "P200": "receiver.p200"}},
}

# Users the pack creates for KAC (local part, name, roles, attributes). Limits are in paise. Unrestricted legacy users (ap.clerk,
# finance.controller, finance.controller2) are left as they are.
KAC_USERS = [
    ("ap.clerk.1", "Mock AP Clerk 1 (finance_ops)", ["AP_CLERK"],
     {"company_codes": ["1000"], "approval_limits": {"INVOICE_APPROVE": 10 * L, "INVOICE_POST": 50 * L}, "mock": KEY}),
    ("ap.clerk.2", "Mock AP Clerk 2 (finance_ops)", ["AP_CLERK"],
     {"company_codes": ["1000"], "approval_limits": {"INVOICE_APPROVE": 10 * L, "INVOICE_POST": 50 * L}, "mock": KEY}),
    ("fin.controller.1", "Mock Finance Controller 1 (finance_ops)", ["FINANCE_CONTROLLER"],
     {"company_codes": ["1000"], "approval_limits": {"INVOICE_APPROVE": 300 * L, "INVOICE_POST": 300 * L, "PAYMENT_RUN": 0}, "mock": KEY}),
    ("fin.controller.2", "Mock Finance Controller 2 (finance_ops)", ["FINANCE_CONTROLLER"],
     {"company_codes": ["1000"], "approval_limits": {"INVOICE_APPROVE": 300 * L, "INVOICE_POST": 300 * L, "PAYMENT_RUN": 0}, "mock": KEY}),
    ("treasury.1000", "Mock Treasury Approver 1000 (finance_ops)", ["FINANCE_CONTROLLER"],
     {"company_codes": ["1000"], "function": "TREASURY", "approval_limits": {"PAYMENT_RUN": 500 * L, "INVOICE_APPROVE": 0, "INVOICE_POST": 0}, "mock": KEY}),
    ("tax.manager", "Mock Tax Manager (finance_ops)", ["FINANCE_CONTROLLER"],
     {"company_codes": ["1000"], "function": "TAX", "approval_limits": {"PAYMENT_RUN": 0, "INVOICE_APPROVE": 0, "INVOICE_POST": 0}, "mock": KEY}),
]
AP_CAPTURE, AP_APPROVE, AP_POST = "ap.clerk.1", "ap.clerk.2", "ap.clerk.1"
FC_APPROVE, FC_CLOSE, TREASURY, TAX = "fin.controller.1", "fin.controller.2", "treasury.1000", "tax.manager"

STATE_ABBR = {"29": "KA", "33": "TN", "27": "MH", "36": "TS", "37": "AP", "32": "KL", "24": "GJ", "07": "DL", "06": "HR", "09": "UP", "19": "WB", "23": "MP"}

# TDS section by supplier category (first match in this order wins). The default sections are the illustrative ones of rule set TDS.
TDS_CATEGORY = [("PROF-SERVICES", "194J-PRO"), ("IT-SERVICES", "194J-TECH"), ("SOFTWARE-LICENCES", "194J-TECH"), ("LOGISTICS", "194C-OTH"),
                ("TOOLING-SERVICES", "194C-OTH"), ("FACILITIES", "194C-OTH"), ("MACHINING", "194C-OTH"), ("MRO", "194C-OTH")]
FORCED_MSME = {"100012": "SMALL", "100025": "MICRO", "200017": "SMALL"}        # suppliers with old open invoices: the MSME breach cases

# Payment runs (key, date, bank account key). Run dates stay on or before 31 October 2026.
RUNS = [("R1", D(9, 18), "A"), ("R2", D(10, 2), "A"), ("R3", D(10, 9), "A"), ("R4", D(10, 16), "A"), ("R5", D(10, 23), "B"), ("R6", D(10, 30), "B")]
FOREIGN_RUN = ("RF", D(10, 30), "B")
RUN_DATE = {key: day for key, day, _ in RUNS + [FOREIGN_RUN]}
DEBTOR = {"A": {"debtorName": "Kaveri Auto Components Pvt Ltd (MOCK debtor account A)", "debtorAccountRef": "MOCK-CA-0001", "debtorIfsc": "MOCK0000001"},
          "B": {"debtorName": "Kaveri Auto Components Pvt Ltd (MOCK debtor account B)", "debtorAccountRef": "MOCK-CA-0002", "debtorIfsc": "MOCK0000002"}}
ACCOUNT_B_FROM = D(10, 19)
PERIODS_CLOSE_1 = (D(9, 2), ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08"])
PERIOD_SEP_CLOSE = D(10, 5)
PERIOD_SEP_REOPEN, PERIOD_SEP_RECLOSE = D(10, 27), D(10, 28)

# Scenario kinds and counts per KAC (see _plan). PO-consuming kinds first; the DUP_REJECT / DUP_OPEN kinds re-bill an earlier POSTED_OPEN invoice.
KINDS = [("PAID_TDS", 14), ("PAID_MSME", 6), ("PAID_PLAIN", 22), ("POSTED_OPEN", 10), ("MATCHED", 4), ("APPROVED", 4), ("UNDERPRICED", 3),
         ("PRICE_CN", 2), ("PRICE_ACCEPT", 2), ("PRICE_OPEN", 2), ("PRICE_DISPUTE", 1), ("QTY_CN", 3), ("QTY_OPEN", 2), ("QTY_REJECT", 1),
         ("MGR_RESOLVED", 3), ("MGR_OPEN", 2), ("TAX_IRN", 1), ("TAX_QR", 1), ("TAX_RATE", 2), ("DUP_VARIANT", 2), ("DUP_REJECT", 2), ("DUP_OPEN", 1)]
PAID_KINDS = ("PAID_TDS", "PAID_MSME", "PAID_PLAIN")


# ------------------------------------------------------------------------------------------------ small helpers
def ist(day: date, hour: int = 10, minute: int = 0) -> datetime:
    return at(day, hour, minute)


def rupees(minor: int) -> str:
    return f"{Decimal(minor) / 100:.2f}"


def money(minor: int) -> str:
    return f"INR {Decimal(minor) / 100:,.2f}"


def _div(minor: int, pct: Decimal) -> int:
    return int((Decimal(minor) * pct).quantize(Decimal(1), ROUND_HALF_UP))


class Skip(Exception):
    """A step that cannot apply (the document it needs is not there): reported in the pack summary, never raised to the caller."""


@dataclass
class Ev:
    when: datetime
    seq: int
    label: str
    fn: Callable


@dataclass
class Ctx:
    tenant_id: uuid.UUID
    code: str
    password: str
    sc: Scenario
    spec: dict
    events: list = field(default_factory=list)
    plan: dict = field(default_factory=dict)
    counts: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    seq: int = 0

    def at(self, when: datetime, label: str, fn: Callable) -> None:
        self.seq += 1
        self.events.append(Ev(when, self.seq, label, fn))

    def count(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n

    def act(self, who: str, when: datetime):
        return self.sc.act(who, when)


# ------------------------------------------------------------------------------------------------ stage ledger (idempotency)
def _stage_done(s, key: str) -> Optional[dict]:
    row = s.execute(select(AuditEvent).where(AuditEvent.action == "FINANCE_OPS_STAGE", AuditEvent.object_ref == key).order_by(AuditEvent.seq.desc())).scalars().first()
    return (row.after or {}) if row is not None else None


def stage_done(tenant_id, key: str) -> Optional[dict]:
    with tenant_tx(tenant_id) as s:
        return _stage_done(s, key)


def stage_mark(tenant_id, key: str, after: Optional[dict] = None) -> None:
    with tenant_tx(tenant_id) as s:
        audit.record(s, "DATASET", uuid.uuid5(uuid.NAMESPACE_URL, f"{KEY}:{key}"), "FINANCE_OPS_STAGE", object_ref=key, after=after or {}, actor=ACTOR,
                     reason=LABEL)


# ------------------------------------------------------------------------------------------------ rules (effective-dated versions)
def publish_rule(s, tenant_id, key: str, version: str, effective_from: date, body: dict, description: str, company_code: Optional[str] = None) -> bool:
    if s.execute(select(RuleSet.id).where(RuleSet.key == key, RuleSet.version == version)).first():
        return False
    rule = RuleSet(tenant_id=tenant_id, key=key, version=version, effective_from=effective_from, body=body, description=description, company_code=company_code)
    s.add(rule)
    s.flush()
    audit.record(s, "RULE_SET", rule.id, "VERSION_CREATED", object_ref=f"{key}@{version}", actor=ACTOR, reason=LABEL,
                 after={"key": key, "version": version, "effective_from": effective_from.isoformat(), "company_code": company_code, "body": body,
                        "description": description})
    return True


def kac_rules(tenant_id) -> dict:
    """MOCK rule versions of KAC (values and rationale: docs/PIC_Finance_Rule_Values_Proposal.md)."""
    published = []
    with tenant_tx(tenant_id) as s:
        msme = {**finance_defaults.MSME_DEFAULT, "bankRatePct": MSME_BANK_RATE,
                "note": "MOCK - pending treasury sign-off: bank rate " + MSME_BANK_RATE + " % is a placeholder; interest = 3 x bank rate compounded monthly"}
        tds = {**finance_defaults.TDS_DEFAULT, "note": "MOCK - pending tax team sign-off. Illustrative TDS sections, rates and thresholds; the tax team "
               "confirms them before go-live (docs/PIC_Finance_Rule_Values_Proposal.md)."}
        run = {"horizonDays": 7, "autoRun": False, "approverRole": "FINANCE_CONTROLLER", "slaBusinessDays": 1}
        desc = "MOCK - pending client sign-off (finance_ops). See docs/PIC_Finance_Rule_Values_Proposal.md."
        for key, body in (("MSME", msme), ("TDS", tds), ("PAYMENT-RUN", run)):
            if publish_rule(s, tenant_id, key, RULE_VERSION, RULE_EFFECTIVE, body, desc):
                published.append(f"{key}@{RULE_VERSION}")
        advance = {"enabled": True, "maxPct": "20", "needsGuarantee": False, "approverRole": "FINANCE_CONTROLLER", "recovery": "PRO_RATA"}
        guarantee = {"enabled": True, "minPct": "5", "requiredFor": [], "alertDays": [60, 30, 7], "releaseAfter": "RETENTION_RELEASED"}
        for key, body in (("ADVANCE-PAYMENT", advance), ("PERFORMANCE-GUARANTEE", guarantee)):
            if publish_rule(s, tenant_id, key, RULE_VERSION, RULE_EFFECTIVE, body, desc + " Advances to suppliers (up to 20 % of the order, a bank guarantee optional) recovered pro rata from the bills."):
                published.append(f"{key}@{RULE_VERSION}")
        for account, effective in (("A", RULE_EFFECTIVE), ("B", ACCOUNT_B_FROM)):
            body = {"format": "ISO20022_PAIN001", **DEBTOR[account]}
            version = f"2026.2-CC1000-MOCK-{account}"
            if publish_rule(s, tenant_id, "PAYMENT-FILE", version, effective, body, desc + f" MOCK debtor account {account}: not a real account.", "1000"):
                published.append(f"PAYMENT-FILE@{version}")
    return {"published": published}


# ------------------------------------------------------------------------------------------------ users
def ensure_users(ctx: Ctx) -> int:
    if ctx.code != KAC:
        return 0
    return kit.create_users(ctx.sc, KAC_USERS, ctx.password)


def supplier_portal_users(ctx: Ctx, supplier_codes: list[str]) -> int:
    """SUPPLIER_USER logins for the suppliers that take part in early payment (the buyer's offer is accepted by the supplier)."""
    from app.pic.platform.auth import hash_password
    added = 0
    with tenant_tx(ctx.tenant_id) as s:
        have = set(s.execute(select(AppUser.email)).scalars())
        hashed = hash_password(ctx.password)
        for code in supplier_codes:
            email = supplier_email(ctx, code)
            if email in have:
                continue
            sup = s.execute(select(Supplier).where(Supplier.code == code)).scalar_one()
            s.add(AppUser(tenant_id=ctx.tenant_id, email=email, full_name=f"{sup.legal_name} - accounts receivable (MOCK login)", password_hash=hashed,
                          roles=["SUPPLIER_USER"], attributes={"mock": KEY}, supplier_id=sup.id, mfa_enrolled=True))
            added += 1
    return added


def supplier_email(ctx: Ctx, code: str) -> str:
    return f"ar.{code.lower()}@suppliers.{ctx.spec['domain']}"


# ------------------------------------------------------------------------------------------------ supplier finance attributes
UDYAM = re.compile(r"^UDYAM-[A-Z]{2}-\d{2}-\d{7}$")


def set_finance(s, supplier: Supplier, *, msme_class=None, udyam=None, tds_section=None, reason: str) -> bool:
    """The change PUT /v1/suppliers/{code}/finance makes (same checks, same audit event), without overwriting a value that is already set."""
    before = {"msmeClass": supplier.msme_class, "udyamNo": supplier.udyam_no, "tdsSection": supplier.tds_section, "panOnFile": supplier.pan_hash is not None}
    changed = False
    if tds_section and not supplier.tds_section:
        supplier.tds_section = tds_section
        changed = True
    if msme_class and not supplier.msme_class:
        if not UDYAM.match(udyam or ""):
            raise ValueError(f"Udyam number {udyam} has the wrong format")
        supplier.msme_class, supplier.udyam_no = msme_class, udyam
        changed = True
    if changed:
        s.flush()
        audit.record(s, "SUPPLIER", supplier.id, "FINANCE_ATTRIBUTES_CHANGED", object_ref=supplier.code, before=before, actor=ACTOR, reason=reason,
                     after={"msmeClass": supplier.msme_class, "udyamNo": supplier.udyam_no, "tdsSection": supplier.tds_section,
                            "panOnFile": supplier.pan_hash is not None})
    return changed


def udyam_for(supplier: Supplier) -> str:
    state = STATE_ABBR.get(supplier.state_code or "", "TN")
    district = 1 + int(mock.unit("udyam-district", supplier.code) * 38)
    serial = 1_000_000 + int(mock.unit("udyam-serial", supplier.code) * 8_999_999)
    return f"UDYAM-{state}-{district:02d}-{serial:07d}"


def assign_finance_attributes(ctx: Ctx) -> dict:
    """PAN is already on file (from the GSTIN). TDS section by category, MSME class on about 15 % of the suppliers (and on the three suppliers with old
    open invoices), 194Q on the one supplier with the largest purchases."""
    out = {"tds": 0, "msme": 0, "sections": {}}
    reason = f"{LABEL}: supplier tax master filled by rule (category -> TDS section; 15 % of suppliers MSME); the client's tax team confirms or replaces it"
    with tenant_tx(ctx.tenant_id) as s:
        suppliers = list(s.execute(select(Supplier).order_by(Supplier.code)).scalars())
        categories: dict = {}
        for sid, category in s.execute(select(SupplierCategoryStatus.supplier_id, SupplierCategoryStatus.category)):
            categories.setdefault(sid, set()).add(category)
        value = dict(s.execute(select(Invoice.supplier_id, func.sum(Invoice.gross_minor)).group_by(Invoice.supplier_id)).all())
        goods = [x for x in suppliers if not (categories.get(x.id, set()) & {c for c, _ in TDS_CATEGORY}) and "IC-TRANSFER" not in categories.get(x.id, set())]
        big = max(goods, key=lambda x: (value.get(x.id, 0), x.code), default=None)
        banked = set(s.execute(select(SupplierBankAccount.supplier_id).where(SupplierBankAccount.active.is_(True))).scalars())
        overdue = [x for x, _ in s.execute(select(Supplier, Invoice.due_date).join(Invoice, Invoice.supplier_id == Supplier.id).where(
            Invoice.channel == "ERP_MIGRATION", Invoice.status == "POSTED", Invoice.payment_status == "UNPAID", Invoice.payment_block.is_(False),
            Supplier.status == "ACTIVE", Invoice.due_date <= D(10, 15)).order_by(Invoice.due_date, Invoice.number)).all() if x.id in banked]
        forced = dict(FORCED_MSME)
        for x in overdue[:4]:
            forced.setdefault(x.code, "SMALL")
        facilities = sorted((x for x in suppliers if "FACILITIES" in categories.get(x.id, set())), key=lambda x: mock.unit("rent", x.code))
        rent = {x.code for x in facilities[:2]}
        for x in suppliers:
            section = None
            cats = categories.get(x.id, set())
            if x.code in rent:
                section = "194I-LB"
            elif big is not None and x.id == big.id:
                section = "194Q"
            elif "IC-TRANSFER" not in cats:
                section = next((sec for cat, sec in TDS_CATEGORY if cat in cats), None)
                if section == "194C-OTH" and re.search(r"\b(enterprises|proprietor|traders)\b", x.legal_name, re.I):
                    section = "194C-IND"
            msme = udyam = None
            if x.code in forced:
                msme = forced[x.code]
            elif mock.unit("msme", x.code) < 0.15:
                msme = "MICRO" if mock.unit("msme-class", x.code) < 0.45 else "SMALL"
            if msme:
                udyam = udyam_for(x)
            if set_finance(s, x, msme_class=msme, udyam=udyam, tds_section=section, reason=reason):
                out["tds"] += 1 if section else 0
                out["msme"] += 1 if msme else 0
                if section:
                    out["sections"][section] = out["sections"].get(section, 0) + 1
    return out


def promote(s, supplier: Supplier, *, tds: bool = False, msme: bool = False) -> None:
    """A scenario needs a TDS / MSME supplier and the category rule left none among the purchase orders at hand: the supplier gets the attribute."""
    reason = f"{LABEL}: attribute added so the demonstration case exists (job-work contractor / micro-small enterprise)"
    set_finance(s, supplier, tds_section="194C-OTH" if tds else None, msme_class="SMALL" if msme else None, udyam=udyam_for(supplier) if msme else None, reason=reason)


# ------------------------------------------------------------------------------------------------ certificates, FX, currencies
def certificates(ctx: Ctx, picks: list[tuple]) -> int:
    """s.197 lower-deduction certificates through finance_controls.add_certificate, recorded by the tax manager. A pick may end with an amount cap
    (max_base_minor): it is passed only when the service accepts it, so the pack runs with and without the cap field."""
    import inspect

    from app.pic.services import finance_controls
    takes_cap = "max_base_minor" in inspect.signature(finance_controls.add_certificate).parameters
    added = 0
    for code, number, rate, valid_from, valid_to, note, *cap in picks:
        with ctx.act(TAX, ist(D(9, 1), 9, 30)) as s:
            supplier = s.execute(select(Supplier).where(Supplier.code == code)).scalar_one()
            if s.execute(select(TdsCertificate.id).where(TdsCertificate.supplier_id == supplier.id, TdsCertificate.certificate_no == number)).first():
                continue
            extra = {"max_base_minor": cap[0]} if cap and cap[0] and takes_cap else {}
            finance_controls.add_certificate(s, supplier, certificate_no=number, rate_pct=rate, valid_from=valid_from, valid_to=valid_to,
                                             section=supplier.tds_section, note=f"{LABEL}: {note}", **extra)
            added += 1
    return added


def reference_anchors() -> dict:
    """The FBIL values of the reference file (28 October 2026) as per-unit anchors of the FX series."""
    from app.pic.seed.datasets import reference_data
    anchors = {}
    for r in reference_data.fx_rows():
        if r["to_ccy"] == "INR" and r["date"] == mock.FX_ANCHOR.isoformat():
            anchors[r["from_ccy"]] = (Decimal(r["rate"]) / Decimal(r["units"])).quantize(Decimal("0.00000001"))
    return anchors


def load_fx(ctx: Ctx) -> dict:
    """Weekday reference rates 1 April to 31 October 2026 for USD, EUR, GBP, JPY, CNY -> INR in single multi-row inserts. Rates that exist stay."""
    anchors = reference_anchors()
    series = mock.fx_series(anchors)
    with tenant_tx(ctx.tenant_id) as s:
        if s.execute(select(Currency.id).where(Currency.code == "CNY")).first() is None:
            s.add(Currency(tenant_id=ctx.tenant_id, code="CNY", name="Chinese yuan renminbi", decimals=2, active=True))
        have = {(f, d) for f, d in s.execute(select(FxRate.from_ccy, FxRate.valid_from).where(FxRate.to_ccy == "INR",
                                                                                              FxRate.valid_from >= mock.FX_START, FxRate.valid_from <= mock.FX_END))}
        rows = [{"id": uuid.uuid7(), "tenant_id": ctx.tenant_id, "from_ccy": code, "to_ccy": "INR", "rate": rate, "valid_from": day,
                 "source": "FBIL" if (day == mock.FX_ANCHOR and code in anchors) else mock.FX_SOURCE}
                for code, day, rate in series if (code, day) not in have]
        if rows:
            s.execute(insert(FxRate), rows)
            audit.record(s, "FX_RATE", uuid.uuid5(uuid.NAMESPACE_URL, f"{KEY}:fx:{ctx.code}"), "SERIES_LOADED", object_ref="MOCK FX series", actor=ACTOR,
                         reason=LABEL, after={"rows": len(rows), "currencies": sorted(mock.FX_ANCHORS), "from": mock.FX_START.isoformat(), "to": mock.FX_END.isoformat(),
                                              "anchorDay": mock.FX_ANCHOR.isoformat(), "anchored": sorted(anchors)})
    return {"fxRates": len(rows)}


# ------------------------------------------------------------------------------------------------ the pack
def apply(tenant_code: str, password: str) -> dict:
    spec = SPECS.get(tenant_code)
    if spec is None:
        raise ValueError(f"{KEY} loads tenants {', '.join(SPECS)} only")
    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == tenant_code)).scalar_one()
    role_user = _kac_roles() if tenant_code == KAC else None            # AXN: the default role -> user table of the signature case
    sc = Scenario(tenant_id, tenant_code=tenant_code, domain=spec["domain"], role_user=role_user)
    ctx = Ctx(tenant_id=tenant_id, code=tenant_code, password=password, sc=sc, spec=spec)
    try:
        if tenant_code == KAC:
            from app.pic.seed.datasets import finance_ops_run
            return finance_ops_run.run(ctx)
        from app.pic.seed.datasets import finance_ops_axn
        return finance_ops_axn.run(ctx)
    finally:
        clock.set_pinned(None)


def rebuild_statement_files(tenant_id):
    """Bank statement files rebuilt from the specs the pack stored (used by tools/finance_mock --write / --check and the tests)."""
    from app.pic.seed.datasets import finance_ops_pay
    return finance_ops_pay.rebuild_statement_files(tenant_id)
