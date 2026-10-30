"""ERP data migration and cutover (Technical Document §12.4, MIG-1..5 / D10): load a client's SAP S/4HANA extract into a tenant.

    python -m app.pic.tools.erp_load --tenant KAC --dir data/erp_mock/KAC [--validate-only] [--report] [--report-dir DIR]

The extract layout (one CSV per SAP table, MANIFEST.json with row counts and SHA-256) is specified in
docs/PIC_ERP_Extract_Spec.md; ``app.pic.tools.erp_mock`` generates a complete fictional one. Load order (§12.4):

  1 org            company code (T001), plants (T001W), cost centres (CSKS) and WBS elements (PRPS); the tenant is bootstrapped
                   from them when it has no configuration yet; taxonomy extension from the mapping workshop (PIC_MAP_TAXONOMY)
  2 vendors        LFA1 + ADRC + LFB1 + LFBK -> supplier masters (GSTIN and bank account field-encrypted with the platform crypto,
                   blind indexes for duplicate search), qualified categories from info records / agreements / history, then the
                   F8-03 duplicate and sanctions screening (services.supplier.screen) plus a shared-bank-account check
  3 materials      MARA + MAKT + MARC + MBEW (+ PIC_MAP_MATKL) -> material masters (HSN/SAC and GST rate checked against the CBIC
                   master data/reference/hsn_gst_rates.csv), info records (EINA/EINE) and source lists (EORD)
  4 agreements     EKKO/EKPO (BSTYP L scheduling agreements, K contracts) + A016/KONP conditions -> ACTIVE contracts with their
                   price validities, template clauses, consumption so far, renewal and expiry timers; expired agreements are
                   used for the contract coverage of the spend history only
  5 open POs       EKKO/EKPO (BSTYP F) + EKKN + EKET + EKBE -> purchase orders with the SAP number as external reference
                   (erp_doc_no), open quantities and the received / invoiced quantities so far, waiting for delivery (F5-09)
  6 open AP        BSIK + RBKP/RSEG (+ BSEG_KR) -> posted invoices awaiting payment (F7-07), linked to the ERP document;
                   on the SAP simulator the documents are registered so the nightly reconciliation (§12.2) agrees
  7 spend history  RSEG/RBKP + BSEG_KR -> spend lines (source ERP_HISTORY), then the Spend Classification Agent and the
                   maverick rules (services.spend.refresh)
  8 GL tie-out     per company code and period: extract vs loaded vs ACDOCA period totals (±0.5 %), reconciling items
                   (GL_RECON_ITEMS); open AP vs the vendor reconciliation account; open PO value per supplier; contracts.

Every row is validated; a rejected row goes to the reject report with its reason and never stops the load. Everything is
idempotent: a second run of the same extract finds every row loaded and writes nothing. Each object type is audited as
INITIAL_LOAD (first load) or ERP_DELTA (later extracts) by ``integration:SAP_S4``; every write runs in a tenant transaction
(RLS). A delta extract updates descriptive master fields (name, address, terms, block flag, material text/HSN/price);
bank or tax-ID changes are never applied silently: they are rejected as SENSITIVE_CHANGE and go through MDM-04.
"""
import argparse
import csv
import hashlib
import io
import json
import logging
import sys
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from sqlalchemy import func, select

from app.pic.config import BACKEND_DIR
from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuditEvent, Clause, CompanyCode, Contract, ContractLine, CostObject, ErpDocument, InfoRecord, Invoice, InvoiceLine,
    Material, NumberRange, Plant, PoLine, PoScheduleLine, PriceValidity, PurchaseOrder, SourceList, SpendLine, StorageLocation, Supplier,
    SupplierBankAccount, SupplierCategoryStatus, TaxonomyNode, Tenant,
)
from app.pic.platform import audit, clock, crypto, integration, rules, workflow
from app.pic.platform.auth import Principal
from app.pic.platform.core import insert_rows, link, next_number
from app.pic.services import master_changes
from app.pic.services.gst import Entry, digits_of

log = logging.getLogger("pic.erp_load")

SOURCE = "SAP_S4"
ACTOR = "integration:SAP_S4"
NS = uuid.UUID("2b6f4f6e-9c1d-4f3a-8d2e-5a7c0e1b9d44")
TOLERANCE_PCT = Decimal("0.5")
HSN_FILE = BACKEND_DIR / "data" / "reference" / "hsn_gst_rates.csv"
REQUIRED = ["T001", "T001W", "CSKS", "PRPS", "T052", "T007S", "LFA1", "ADRC", "LFB1", "LFBK", "MARA", "MAKT", "MARC", "MBEW", "EINA_EINE",
            "EORD", "EKKO", "EKPO", "A016_KONP", "EKKN", "EKET", "EKBE", "RBKP", "RSEG", "BSEG_KR", "BSIK", "BSAK", "ACDOCA_PERIOD_TOTALS",
            "GL_BALANCES", "PIC_MAP_MATKL"]
OPTIONAL = ["GL_RECON_ITEMS", "PIC_MAP_TAXONOMY", "T023T"]
UOM = {"ST": "EA", "PC": "EA", "EA": "EA", "KG": "KG", "L": "L", "M": "M", "SET": "SET", "AU": "AU", "LE": "AU", "MON": "MON", "PAC": "PAC",
       "PAA": "PR", "PR": "PR", "TO": "TON", "TON": "TON", "M2": "M2", "M3": "M3", "H": "HR", "HR": "HR", "D": "DAY", "DAY": "DAY", "KM": "KM"}
MTART_TYPE = {"ROH": "STOCK", "HALB": "STOCK", "VERP": "STOCK", "ERSA": "STOCK", "HIBE": "STOCK", "FHMI": "STOCK", "NLAG": "NON_STOCK",
              "DIEN": "SERVICE", "UNBW": "NON_STOCK"}
CONTRACT_TYPE = {("L", ""): "SCHEDULING_AGREEMENT", ("K", "MK"): "QUANTITY_CONTRACT", ("K", "WK"): "VALUE_CONTRACT"}
IFSC_LEN = 11


class ExtractError(Exception):
    """The extract cannot be loaded at all (missing or altered file, unknown tenant): nothing is written."""


@dataclass
class IntegrationPrincipal(Principal):
    """The ERP inbound integration: every audit record of the load carries the actor integration:SAP_S4."""

    @property
    def actor(self) -> str:
        return ACTOR


# ---------------------------------------------------------------- parsing helpers
def alpha(value: Optional[str]) -> str:
    """SAP ALPHA conversion out: numeric keys without leading zeros (0000100023 -> 100023), others unchanged."""
    text = (value or "").strip()
    if text.isdigit():
        return text.lstrip("0") or "0"
    return text


def dec(value: Optional[str]) -> Optional[Decimal]:
    text = (value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def minor(value: Optional[str]) -> Optional[int]:
    """Amount in document currency (2 decimals) -> paise; None when unreadable."""
    number = dec(value)
    if number is None:
        return None
    return int((number * 100).to_integral_value(rounding=ROUND_HALF_UP))


def day(value: Optional[str]) -> Optional[date]:
    text = (value or "").strip()
    if not text or text.startswith("9999"):
        return date(9999, 12, 31) if text.startswith("9999") else None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def money(value: int) -> str:
    sign = "-" if value < 0 else ""
    value = abs(int(value))
    return f"{sign}{value // 100}.{value % 100:02d}"


def pct(numerator: int, denominator: int) -> Decimal:
    if not denominator:
        return Decimal(0)
    return (Decimal(numerator) * 100 / abs(Decimal(denominator))).quantize(Decimal("0.001"))


# ---------------------------------------------------------------- extract
@dataclass
class Extract:
    directory: Path
    manifest: dict
    tables: dict

    def rows(self, name: str) -> list[dict]:
        return self.tables.get(name, [])


def read_extract(directory) -> Extract:
    """Read and verify the extract: every file named in MANIFEST.json must be present with the stated row count and SHA-256
    (completeness and integrity of the hand-over). Values are stripped strings; rows carry their 1-based file line in '_row'."""
    directory = Path(directory)
    manifest_path = directory / "MANIFEST.json"
    if not manifest_path.exists():
        raise ExtractError(f"{manifest_path} is missing: the extract hand-over needs MANIFEST.json (row counts and SHA-256 per file)")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files") or {}
    missing = [f"{name}.csv" for name in REQUIRED if f"{name}.csv" not in files]
    if missing:
        raise ExtractError(f"MANIFEST.json does not list required file(s): {', '.join(missing)}")
    tables = {}
    for name, entry in sorted(files.items()):
        path = directory / name
        if not path.exists():
            raise ExtractError(f"{name} is listed in MANIFEST.json but missing from {directory}")
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if entry.get("sha256") and digest != entry["sha256"]:
            raise ExtractError(f"{name}: SHA-256 {digest[:12]}… differs from MANIFEST.json ({entry['sha256'][:12]}…): file changed after extraction")
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
        rows = []
        for index, record in enumerate(reader, start=2):
            row = {k.strip(): (v or "").strip() for k, v in record.items() if k}
            row["_row"] = index
            rows.append(row)
        if "rows" in entry and int(entry["rows"]) != len(rows):
            raise ExtractError(f"{name}: {len(rows)} data rows, MANIFEST.json says {entry['rows']}")
        tables[name[:-4]] = rows
    return Extract(directory=directory, manifest=manifest, tables=tables)


def hsn_master() -> list[Entry]:
    text = HSN_FILE.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    return [Entry(tuple(r["prefixes"].split()), tuple(r["excludes"].split()), r["type"], Decimal(r["gst_rate"]), r["description"],
                  r["schedule_ref"], r["notification"]) for r in csv.DictReader(io.StringIO(body))]


def gst_lookup(entries: list[Entry], code: str) -> list[Decimal]:
    """Rates of the most specific CBIC entry of at least 4 digits (as services.gst.lookup); [] = code unknown."""
    digits = digits_of(code)
    best, rates = 0, set()
    for entry in entries:
        n = entry.match_length(digits)
        if n > best:
            best, rates = n, {entry.rate}
        elif n and n == best:
            rates.add(entry.rate)
    return sorted(rates) if best >= 4 else []


# ---------------------------------------------------------------- report
@dataclass
class Report:
    rejects: list = field(default_factory=list)
    warnings: Counter = field(default_factory=Counter)
    warning_samples: dict = field(default_factory=dict)
    counts: dict = field(default_factory=lambda: defaultdict(lambda: {"extract": 0, "loaded": 0, "existing": 0, "rejected": 0, "skipped": 0}))

    def reject(self, obj: str, file: str, row: dict, key: str, reason: str, detail: str, amount: Optional[int] = None) -> None:
        self.rejects.append({"object": obj, "file": f"{file}.csv", "row": row.get("_row") if row else None, "key": key, "reason": reason,
                             "detail": detail, **({"amountMinor": amount} if amount is not None else {})})
        self.counts[obj]["rejected"] += 1

    def warn(self, code: str, key: str, detail: str) -> None:
        self.warnings[code] += 1
        self.warning_samples.setdefault(code, f"{key}: {detail}")

    def by_reason(self) -> dict:
        out = defaultdict(Counter)
        for r in self.rejects:
            out[r["object"]][r["reason"]] += 1
        return {obj: dict(sorted(c.items())) for obj, c in sorted(out.items())}


# ---------------------------------------------------------------- staging (pure validation, no database)
@dataclass
class Staged:
    extract: Extract
    report: Report
    company: dict = None
    plants: dict = field(default_factory=dict)
    cost_objects: list = field(default_factory=list)
    terms: dict = field(default_factory=dict)
    tax: dict = field(default_factory=dict)
    matkl: dict = field(default_factory=dict)
    taxonomy: list = field(default_factory=list)
    vendors: dict = field(default_factory=dict)       # code -> staged vendor
    vendor_rejected: set = field(default_factory=set)
    materials: dict = field(default_factory=dict)     # matnr -> staged material
    material_known: set = field(default_factory=set)  # MARA numbers, loaded or not
    info_records: list = field(default_factory=list)
    source_lists: list = field(default_factory=list)
    agreements: dict = field(default_factory=dict)    # ebeln -> agreement (all, with 'active')
    open_pos: dict = field(default_factory=dict)      # ebeln -> {header, lines}
    open_value_extract: dict = field(default_factory=lambda: defaultdict(int))
    ap_items: list = field(default_factory=list)
    spend: list = field(default_factory=list)
    spend_extract: dict = field(default_factory=lambda: defaultdict(int))     # (bukrs, period) -> amount
    spend_rejected: dict = field(default_factory=lambda: defaultdict(int))
    spend_rejected_genuine: dict = field(default_factory=lambda: defaultdict(int))
    gl: dict = field(default_factory=lambda: defaultdict(int))
    recon: dict = field(default_factory=lambda: defaultdict(list))
    ap_gl_balance: dict = field(default_factory=dict)
    ap_extract: list = field(default_factory=list)
    vendor_categories: dict = field(default_factory=lambda: defaultdict(set))


def _period(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _fiscal_period(gjahr: str, poper: str) -> Optional[str]:
    try:
        year, period = int(gjahr), int(poper)
    except ValueError:
        return None
    if not 1 <= period <= 12:
        return None
    month = (period + 2) % 12 + 1          # fiscal year variant V3: period 001 = April
    return f"{year + (1 if month <= 3 else 0):04d}-{month:02d}"


def stage(extract: Extract, key_date: Optional[date] = None) -> Staged:
    st = Staged(extract=extract, report=Report())
    rep = st.report
    key_date = key_date or day(extract.manifest.get("keyDate")) or clock.today()
    st.key_date = key_date
    companies = {r["BUKRS"]: r for r in extract.rows("T001")}
    codes = extract.manifest.get("companyCodes") or sorted(companies)
    if not codes or codes[0] not in companies:
        raise ExtractError("T001 has no row for the company code named in MANIFEST.json")
    bukrs = codes[0]
    c = companies[bukrs]
    errors = master_changes.gstin_errors(c.get("GSTIN", ""))
    if errors:
        raise ExtractError(f"company code {bukrs}: {'; '.join(errors)}")
    st.company = {"code": bukrs, "name": c["BUTXT"], "gstin": c["GSTIN"], "currency": c.get("WAERS") or "INR"}
    st.bukrs = bukrs
    for r in extract.rows("T001W"):
        state = (r.get("GSTIN") or "")[:2] or r.get("REGIO", "")
        if r.get("BUKRS") != bukrs:
            rep.counts["plants"]["skipped"] += 1
            continue
        if state not in master_changes.STATE_CODES:
            raise ExtractError(f"T001W plant {r['WERKS']}: no valid GST state (business-place GSTIN or region)")
        st.plants[r["WERKS"]] = {"code": r["WERKS"], "name": r["NAME1"], "state": state}
        rep.counts["plants"]["extract"] += 1
    for r in extract.rows("CSKS"):
        if r.get("BUKRS") == bukrs and (day(r.get("DATBI")) or date.max) >= key_date:
            st.cost_objects.append(("COST_CENTER", r["KOSTL"], r.get("LTEXT") or r.get("KTEXT") or r["KOSTL"]))
    for r in extract.rows("PRPS"):
        if r.get("PBUKR") == bukrs:
            st.cost_objects.append(("WBS", r["POSID"], r.get("POST1") or r["POSID"]))
    rep.counts["costObjects"]["extract"] = len(st.cost_objects)
    for r in extract.rows("T052"):
        days = dec(r.get("ZTAG1"))
        disc = dec(r.get("ZPRZ1")) or Decimal(0)
        if days is None:
            continue
        st.terms[r["ZTERM"]] = (f"{disc.normalize()}/{int(days)} N{int(days)}" if disc else f"N{int(days)}")
    for r in extract.rows("T007S"):
        st.tax[r["MWSKZ"]] = dec(r.get("RATE")) or Decimal(0)
    st.matkl = {r["MATKL"]: r["PIC_CATEGORY"] for r in extract.rows("PIC_MAP_MATKL") if r.get("PIC_CATEGORY")}
    for r in extract.rows("PIC_MAP_TAXONOMY"):
        st.taxonomy.append((r["CATEGORY"], r.get("PARENT") or None, int(r.get("LEVEL") or 3), r.get("NAME") or r["CATEGORY"],
                            [k.strip() for k in (r.get("KEYWORDS") or "").split(";") if k.strip()], r.get("ADDRESSABLE", "X") == "X"))
    _stage_vendors(st)
    _stage_materials(st)
    _stage_agreements(st)
    _stage_purchasing(st)
    _stage_ap(st)
    _stage_gl(st)
    return st


def _stage_vendors(st: Staged) -> None:
    rep, x = st.report, st.extract
    adrc = {r["ADDRNUMBER"]: r for r in x.rows("ADRC")}
    lfb1 = {(alpha(r["LIFNR"]), r["BUKRS"]): r for r in x.rows("LFB1")}
    banks = defaultdict(list)
    for r in x.rows("LFBK"):
        banks[alpha(r["LIFNR"])].append(r)
    seen = set()
    for r in x.rows("LFA1"):
        code = alpha(r["LIFNR"])
        rep.counts["vendors"]["extract"] += 1
        if code in seen:
            rep.reject("vendors", "LFA1", r, code, "DUPLICATE_KEY", "LIFNR appears twice in LFA1")
            continue
        seen.add(code)
        name = " ".join(p for p in (r.get("NAME1"), r.get("NAME2")) if p).strip()
        gstin = (r.get("STCD3") or "").upper()
        pan = (r.get("J_1IPANNO") or "").upper()
        if not gstin:
            rep.reject("vendors", "LFA1", r, code, "GSTIN_MISSING", f"{name}: no GSTIN (LFA1-STCD3); register the GSTIN or confirm the "
                       "vendor is unregistered before it can be loaded")
            st.vendor_rejected.add(code)
            continue
        errors = master_changes.gstin_errors(gstin, pan or None) + (master_changes.pan_errors(pan) if pan else [])
        if errors:
            reason = "GSTIN_PAN_MISMATCH" if any("PAN must match" in e for e in errors) else "GSTIN_INVALID"
            rep.reject("vendors", "LFA1", r, code, reason, f"{name} {gstin}: {'; '.join(errors)}")
            st.vendor_rejected.add(code)
            continue
        company = lfb1.get((code, st.bukrs))
        if company is None:
            rep.reject("vendors", "LFB1", r, code, "NO_COMPANY_CODE_DATA", f"{name}: not extended to company code {st.bukrs} (LFB1)")
            st.vendor_rejected.add(code)
            continue
        terms = st.terms.get(company.get("ZTERM"))
        if terms is None:
            rep.reject("vendors", "LFB1", company, code, "PAYMENT_TERMS_UNKNOWN", f"terms key {company.get('ZTERM')!r} not in T052")
            st.vendor_rejected.add(code)
            continue
        address = adrc.get(r.get("ADRNR"), {})
        staged = {"code": code, "lifnr": r["LIFNR"], "name": name[:200], "gstin": gstin, "pan": gstin[2:12], "state": gstin[:2],
                  "terms": terms, "zterm": company.get("ZTERM"), "account_group": r.get("KTOKK"),
                  "blocked": bool(r.get("SPERR") or r.get("SPERM") or company.get("SPERR")), "deleted": bool(r.get("LOEVM") or company.get("LOEVM")),
                  "email": (address.get("SMTP_ADDR") or "").lower() or None, "created": day(r.get("ERDAT")),
                  "address": master_changes.normalise_address({"line1": address.get("STREET"), "line2": address.get("STR_SUPPL1"),
                                                               "city": address.get("CITY1"), "state_code": gstin[:2],
                                                               "pin": address.get("POST_CODE1"), "country": address.get("COUNTRY") or "IN"}),
                  "bank": None}
        for b in banks.get(code, [])[:1]:
            ifsc, account = (b.get("BANKL") or "").upper(), (b.get("BANKN") or "").strip()
            if len(ifsc) != IFSC_LEN or not ifsc[:4].isalpha() or ifsc[4] != "0" or not ifsc[5:].isalnum():
                rep.reject("vendorBanks", "LFBK", b, code, "BANK_IFSC_INVALID", f"IFSC {ifsc!r} is not 4 letters + 0 + 6 characters; "
                           "vendor loaded without bank account")
            elif not account.isdigit() or not 6 <= len(account) <= 18:
                rep.reject("vendorBanks", "LFBK", b, code, "BANK_ACCOUNT_INVALID", "account number must be 6-18 digits; vendor loaded without bank")
            else:
                staged["bank"] = {"ifsc": ifsc, "account": account, "holder": b.get("KOINH") or name}
        if banks.get(code):
            rep.counts["vendorBanks"]["extract"] += 1
        st.vendors[code] = staged


def _stage_materials(st: Staged) -> None:
    rep, x = st.report, st.extract
    entries = hsn_master()
    st.hsn_entries = entries
    texts = {r["MATNR"]: r["MAKTX"] for r in x.rows("MAKT") if r.get("SPRAS", "E") in ("E", "EN")}
    marc = defaultdict(list)
    for r in x.rows("MARC"):
        marc[alpha(r["MATNR"])].append(r)
    mbew = defaultdict(list)
    for r in x.rows("MBEW"):
        mbew[alpha(r["MATNR"])].append(r)
    seen = set()
    for r in x.rows("MARA"):
        number = alpha(r["MATNR"])
        rep.counts["materials"]["extract"] += 1
        st.material_known.add(number)
        if number in seen:
            rep.reject("materials", "MARA", r, number, "DUPLICATE_KEY", "MATNR appears twice in MARA")
            continue
        seen.add(number)
        if r.get("LVORM"):
            rep.counts["materials"]["skipped"] += 1
            continue
        plants = sorted((p for p in marc.get(number, []) if p["WERKS"] in st.plants and not p.get("LVORM")), key=lambda p: p["WERKS"])
        text = texts.get(r["MATNR"]) or texts.get(number)
        category = st.matkl.get(r.get("MATKL"))
        uom = UOM.get((r.get("MEINS") or "").upper())
        hsn = (plants[0].get("STEUC") if plants else "") or ""
        if not text:
            rep.reject("materials", "MAKT", r, number, "NO_DESCRIPTION", "no English text in MAKT")
            continue
        if not plants:
            rep.reject("materials", "MARC", r, number, "NO_PLANT_DATA", "no MARC row for a loaded plant")
            continue
        if category is None:
            rep.reject("materials", "MARA", r, number, "MATERIAL_GROUP_UNMAPPED", f"material group {r.get('MATKL')} is not in PIC_MAP_MATKL")
            continue
        if uom is None:
            rep.reject("materials", "MARA", r, number, "UOM_UNKNOWN", f"unit {r.get('MEINS')!r} has no PIC unit")
            continue
        if not hsn:
            rep.reject("materials", "MARC", plants[0], number, "HSN_MISSING", "MARC-STEUC (HSN/SAC) is empty")
            continue
        rates = gst_lookup(entries, hsn)
        if not rates:
            rep.reject("materials", "MARC", plants[0], number, "HSN_UNKNOWN", f"HSN/SAC {hsn} is not in the CBIC rate schedule")
            continue
        if len(rates) > 1:
            rep.warn("GST_RATE_AMBIGUOUS", number, f"HSN/SAC {hsn} carries rates {', '.join(str(x) for x in rates)}; {max(rates)} used - confirm with tax")
        lead = plants[0]
        dismm = lead.get("DISMM") or "ND"
        if dismm not in ("PD", "ND"):
            rep.warn("MRP_TYPE_MAPPED", number, f"MRP type {dismm} (reorder point) has no PIC equivalent; loaded as ND")
        valuation = next((v for v in mbew.get(number, []) if v.get("BWKEY") == lead["WERKS"]), None)
        std = None
        if valuation:
            price = dec(valuation.get("STPRS") if valuation.get("VPRSV") == "S" else valuation.get("VERPR"))
            unit = dec(valuation.get("PEINH")) or Decimal(1)
            if price:
                std = int((price * 100 / unit).to_integral_value(rounding=ROUND_HALF_UP))
        disls = lead.get("DISLS") or "EX"
        st.materials[number] = {
            "number": number, "description": text[:200], "type": MTART_TYPE.get(r.get("MTART"), "STOCK"), "group": r.get("MATKL"),
            "category": category, "uom": uom, "valuation_class": (valuation or {}).get("BKLAS") or None, "hsn": digits_of(hsn), "gst": max(rates),
            "mpn": r.get("MFRPN") or None, "mrp_type": "PD" if dismm == "PD" else "ND", "lot": "FIXED" if disls == "FX" else "EXACT",
            "lot_qty": dec(lead.get("BSTFE")), "min_lot": dec(lead.get("BSTMI")), "max_lot": dec(lead.get("BSTMA")),
            "safety": dec(lead.get("EISBE")) or Decimal(0), "pdt": int(dec(lead.get("PLIFZ")) or 0), "grt": int(dec(lead.get("WEBAZ")) or 0),
            "qm": lead.get("QMATV") == "X", "std": std, "plants": [p["WERKS"] for p in plants], "mtart": r.get("MTART"),
        }
    for r in x.rows("EINA_EINE"):
        rep.counts["infoRecords"]["extract"] += 1
        vendor, number = alpha(r["LIFNR"]), alpha(r["MATNR"])
        key = f"{r.get('INFNR')} {vendor}/{number}/{r.get('WERKS')}"
        if r.get("LOEKZ"):
            rep.counts["infoRecords"]["skipped"] += 1
            continue
        if vendor not in st.vendors:
            rep.reject("infoRecords", "EINA_EINE", r, key, "VENDOR_NOT_LOADED", f"vendor {vendor} rejected or missing")
            continue
        if number not in st.materials:
            rep.reject("infoRecords", "EINA_EINE", r, key, "MATERIAL_NOT_LOADED", "material rejected, deleted or missing")
            continue
        if r.get("WERKS") not in st.plants:
            rep.reject("infoRecords", "EINA_EINE", r, key, "PLANT_UNKNOWN", f"plant {r.get('WERKS')} not in T001W")
            continue
        price, unit = dec(r.get("NETPR")), dec(r.get("PEINH")) or Decimal(1)
        if not price or price <= 0:
            rep.reject("infoRecords", "EINA_EINE", r, key, "PRICE_INVALID", f"net price {r.get('NETPR')!r}")
            continue
        st.info_records.append({"vendor": vendor, "material": number, "plant": r["WERKS"], "lead": int(dec(r.get("APLFZ")) or 0),
                                "price": int((price * 100 / unit).to_integral_value(rounding=ROUND_HALF_UP))})
        st.vendor_categories[vendor].add(st.materials[number]["category"])
    for r in x.rows("EORD"):
        rep.counts["sourceLists"]["extract"] += 1
        vendor, number = alpha(r["LIFNR"]), alpha(r["MATNR"])
        key = f"{number}/{r.get('WERKS')}/{r.get('ZEORD')}"
        start, end = day(r.get("VDATU")), day(r.get("BDATU"))
        if vendor not in st.vendors or number not in st.materials:
            rep.reject("sourceLists", "EORD", r, key, "VENDOR_NOT_LOADED" if vendor not in st.vendors else "MATERIAL_NOT_LOADED",
                       f"vendor {vendor} rejected or missing" if vendor not in st.vendors else f"material {number} rejected or missing")
            continue
        if not start or not end or end < start:
            rep.reject("sourceLists", "EORD", r, key, "VALIDITY_INVALID", f"{r.get('VDATU')} - {r.get('BDATU')}")
            continue
        if end < st.key_date:
            rep.counts["sourceLists"]["skipped"] += 1
            continue
        st.source_lists.append({"vendor": vendor, "material": number, "plant": r["WERKS"], "fixed": r.get("FLIFN") == "X", "from": start,
                                "to": min(end, date(9999, 12, 31))})


def _stage_agreements(st: Staged) -> None:
    rep, x = st.report, st.extract
    items = defaultdict(list)
    for r in x.rows("EKPO"):
        items[r["EBELN"]].append(r)
    conditions = defaultdict(list)
    for r in x.rows("A016_KONP"):
        conditions[(r["EVRTN"], r["EVRTP"])].append(r)
    st.ekpo = items
    for r in x.rows("EKKO"):
        if r.get("BSTYP") not in ("K", "L"):
            continue
        ebeln = r["EBELN"]
        start, end = day(r.get("KDATB")), day(r.get("KDATE"))
        vendor = alpha(r["LIFNR"])
        kind = CONTRACT_TYPE.get((r["BSTYP"], "" if r["BSTYP"] == "L" else r.get("BSART")))
        agreement = {"ebeln": ebeln, "bstyp": r["BSTYP"], "bsart": r.get("BSART"), "type": kind, "vendor": vendor, "start": start, "end": end,
                     "terms": st.terms.get(r.get("ZTERM")), "incoterms": " ".join(p for p in (r.get("INCO1"), r.get("INCO2")) if p) or None,
                     "header_value": minor(r.get("KTWRT")) or 0, "items": [], "active": False}
        st.agreements[ebeln] = agreement
        if not start or not end or end < start:
            rep.counts["agreements"]["extract"] += 1
            rep.reject("agreements", "EKKO", r, ebeln, "VALIDITY_INVALID", f"validity {r.get('KDATB')} - {r.get('KDATE')}")
            continue
        for item in items.get(ebeln, []):
            if item.get("LOEKZ"):
                continue
            conds = sorted(((day(c["DATAB"]), day(c["DATBI"]), dec(c["KBETR"]), dec(c.get("KPEIN")) or Decimal(1))
                            for c in conditions.get((ebeln, item["EBELP"]), [])), key=lambda c: c[0] or date.min)
            agreement["items"].append({"ebelp": int(item["EBELP"]), "material": alpha(item.get("MATNR")) or None, "text": item.get("TXZ01"),
                                       "plant": item.get("WERKS"), "uom": UOM.get((item.get("MEINS") or "").upper(), item.get("MEINS")),
                                       "target": dec(item.get("KTMNG")) or Decimal(0), "group": item.get("MATKL"),
                                       "over": dec(item.get("UEBTO")) or Decimal(0), "under": dec(item.get("UNTTO")) or Decimal(0),
                                       "conditions": [(s, e, int((p * 100 / u).to_integral_value(rounding=ROUND_HALF_UP))) for s, e, p, u in conds
                                                      if s and e and p is not None]})
            if item.get("MATNR") and alpha(item["MATNR"]) in st.materials:
                st.vendor_categories[vendor].add(st.materials[alpha(item["MATNR"])]["category"])
        if not (start <= st.key_date <= end):
            rep.counts["agreements"]["skipped"] += 1           # expired (or not yet valid): contract coverage of the history only
            continue
        rep.counts["agreements"]["extract"] += 1
        agreement["active"] = True
        if kind is None:
            rep.reject("agreements", "EKKO", r, ebeln, "AGREEMENT_TYPE_UNKNOWN", f"BSTYP {r['BSTYP']} / BSART {r.get('BSART')}")
            agreement["active"] = False
        elif vendor not in st.vendors:
            rep.reject("agreements", "EKKO", r, ebeln, "VENDOR_NOT_LOADED", f"vendor {vendor} rejected or missing")
            agreement["active"] = False
        elif not agreement["items"] or any(not i["conditions"] for i in agreement["items"]):
            rep.reject("agreements", "A016_KONP", r, ebeln, "CONDITION_MISSING", "an item has no price condition (A016/KONP)")
            agreement["active"] = False
        elif any(i["material"] and i["material"] not in st.materials for i in agreement["items"]):
            rep.reject("agreements", "EKPO", r, ebeln, "MATERIAL_NOT_LOADED", "an item's material was rejected")
            agreement["active"] = False


def _stage_purchasing(st: Staged) -> None:
    """Open purchase-order lines and the spend history (RSEG/RBKP + BSEG_KR) with their validations."""
    rep, x = st.report, st.extract
    ekko = {r["EBELN"]: r for r in x.rows("EKKO")}
    ekpo = {(r["EBELN"], r["EBELP"]): r for r in x.rows("EKPO")}
    ekkn = {(r["EBELN"], r["EBELP"]): r for r in x.rows("EKKN")}
    eket = defaultdict(list)
    for r in x.rows("EKET"):
        eket[(r["EBELN"], r["EBELP"])].append(r)
    history = defaultdict(lambda: {"gr_qty": Decimal(0), "gr_value": 0, "ir_qty": Decimal(0), "ir_value": 0})
    for r in x.rows("EKBE"):
        h = history[(r["EBELN"], r["EBELP"])]
        sign = -1 if r.get("SHKZG") == "H" else 1
        qty, value = (dec(r.get("MENGE")) or Decimal(0)) * sign, (minor(r.get("DMBTR")) or 0) * sign
        if r.get("VGABE") == "1":
            h["gr_qty"] += qty
            h["gr_value"] += value
        elif r.get("VGABE") == "2":
            h["ir_qty"] += qty
            h["ir_value"] += value
    st.history = history
    st.ekko = ekko
    st.ekpo_by_key = ekpo
    st.ekkn = ekkn
    coverage = defaultdict(list)          # (material, plant) -> agreements (any validity) for OFF_CONTRACT
    for a in st.agreements.values():
        if a["start"] and a["end"] and a["start"] <= a["end"]:
            for item in a["items"]:
                if item["material"]:
                    coverage[(item["material"], item["plant"])].append((a["start"], a["end"]))
    st.coverage = coverage
    # ---- open purchase-order lines
    for (ebeln, ebelp), r in ekpo.items():
        header = ekko.get(ebeln)
        if header is None or header.get("BSTYP") != "F" or r.get("LOEKZ") or header.get("LOEKZ"):
            continue
        if r.get("ELIKZ") == "X" and r.get("EREKZ") == "X":
            continue
        key = f"{ebeln}/{ebelp}"
        rep.counts["openPoLines"]["extract"] += 1
        h = history[(ebeln, ebelp)]
        vendor = alpha(header["LIFNR"])
        qty, price, unit = dec(r.get("MENGE")), dec(r.get("NETPR")), dec(r.get("PEINH")) or Decimal(1)
        net = minor(r.get("NETWR")) or 0
        st.open_value_extract[vendor] += max(0, net - h["ir_value"])
        reason = None
        number = alpha(r.get("MATNR")) or None
        if vendor not in st.vendors:
            reason = ("VENDOR_NOT_LOADED", f"vendor {vendor} rejected or missing")
        elif st.vendors[vendor]["blocked"] or st.vendors[vendor]["deleted"]:
            reason = ("VENDOR_BLOCKED", f"vendor {vendor} is blocked in SAP: close the PO in SAP or unblock the vendor")
        elif qty is None or qty <= 0:
            reason = ("QTY_INVALID", f"order quantity {r.get('MENGE')!r}")
        elif price is None or price <= 0:
            reason = ("PRICE_INVALID", f"net price {r.get('NETPR')!r}")
        elif number and number not in st.material_known:
            reason = ("MATERIAL_UNKNOWN", f"material {number} is not in MARA")
        elif number and number not in st.materials:
            reason = ("MATERIAL_NOT_LOADED", f"material {number} was rejected")
        elif r.get("WERKS") not in st.plants:
            reason = ("PLANT_UNKNOWN", f"plant {r.get('WERKS')}")
        if reason:
            rep.reject("openPoLines", "EKPO", r, key, reason[0], reason[1], amount=max(0, net - h["ir_value"]))
            continue
        unit_price = price * 100 / unit
        if unit_price != unit_price.to_integral_value():
            rep.warn("PRICE_UNIT_ROUNDED", key, f"{r.get('NETPR')} per {unit} is not a whole number of paise per unit")
        schedule = sorted(eket.get((ebeln, ebelp), []), key=lambda e: e.get("ETENR", ""))
        konnr = r.get("KONNR") or None
        contract = st.agreements.get(konnr) if konnr else None
        if konnr and not (contract and contract["active"]):
            rep.warn("AGREEMENT_NOT_LOADED", key, f"outline agreement {konnr} is not an active loaded contract; line loaded without the link")
            contract = None
        assignment = ekkn.get((ebeln, ebelp), {})
        po = st.open_pos.setdefault(ebeln, {"header": header, "lines": []})
        po["lines"].append({"ebelp": int(ebelp), "row": r, "qty": qty, "unit_price": int(unit_price.to_integral_value(rounding=ROUND_HALF_UP)),
                            "net": net, "material": number, "history": h, "schedule": schedule, "contract": contract,
                            "contract_item": int(r["KTPNR"]) if contract and r.get("KTPNR") else None, "assignment": assignment})
    # ---- spend history: MM invoices
    rbkp = {(r["BELNR"], r["GJAHR"]): r for r in x.rows("RBKP")}
    st.rbkp = rbkp
    seen = set()
    for r in x.rows("RSEG"):
        doc = rbkp.get((r["BELNR"], r["GJAHR"]))
        key = f"{r['BELNR']}/{r['GJAHR']}/{r['BUZEI']}"
        rep.counts["spendLines"]["extract"] += 1
        amount = minor(r.get("WRBTR")) or 0
        signed = -amount if r.get("SHKZG") == "H" else amount
        if doc is None:
            rep.reject("spendLines", "RSEG", r, key, "INVOICE_HEADER_MISSING", "no RBKP row for this item")
            continue
        posting = day(doc.get("BUDAT"))
        bukrs = doc.get("BUKRS") or st.bukrs
        period = _period(posting) if posting else None
        if period:
            st.spend_extract[(bukrs, period)] += signed
        reason = None
        po_row = ekpo.get((r.get("EBELN"), r.get("EBELP")))
        header = ekko.get(r.get("EBELN"))
        vendor = alpha(doc.get("LIFNR"))
        qty = dec(r.get("MENGE"))
        number = alpha(r.get("MATNR")) or None
        if (r["BELNR"], r["GJAHR"], r["BUZEI"]) in seen:
            reason = ("DUPLICATE_KEY", "the same invoice item (BELNR/GJAHR/BUZEI) appears twice in RSEG")
        elif posting is None:
            reason = ("DATE_INVALID", f"posting date {doc.get('BUDAT')!r}")
        elif vendor not in st.vendors:
            reason = ("VENDOR_NOT_LOADED", f"vendor {vendor} rejected or missing")
        elif po_row is None or header is None:
            reason = ("PO_UNKNOWN", f"purchasing document {r.get('EBELN')}/{r.get('EBELP')} is not in EKKO/EKPO")
        elif qty is None or qty < 0:
            reason = ("QTY_NEGATIVE" if qty is not None else "QTY_INVALID", f"quantity {r.get('MENGE')!r} (credit memos carry SHKZG H, not a negative quantity)")
        elif number and number not in st.material_known:
            reason = ("MATERIAL_UNKNOWN", f"material {number} is not in MARA")
        seen.add((r["BELNR"], r["GJAHR"], r["BUZEI"]))
        if reason:
            rep.reject("spendLines", "RSEG", r, key, reason[0], reason[1], amount=signed)
            if period:
                st.spend_rejected[(bukrs, period)] += signed
                if reason[0] != "DUPLICATE_KEY":
                    st.spend_rejected_genuine[(bukrs, period)] += signed
            continue
        group = po_row.get("MATKL") or ""
        category = st.matkl.get(group)
        if number and number in st.materials:
            category = st.materials[number]["category"]
        elif number and number not in st.materials:
            rep.warn("SPEND_MATERIAL_NOT_LOADED", key, f"material {number} was rejected; spend classified from the material group")
        v = st.vendors[vendor]
        intercompany = v["account_group"] == "ZICO"
        if intercompany:
            category = "IC-TRANSFER"
        bldat = day(doc.get("BLDAT")) or posting
        is_agreement = header.get("BSTYP") in ("K", "L")
        contracted = is_agreement or bool(po_row.get("KONNR"))
        flags = []
        bedat = day(header.get("BEDAT"))
        if header.get("BSTYP") == "F" and bedat and bldat and bedat > bldat:
            flags.append("PO_AFTER_INVOICE")
        if not contracted and number and any(s <= bldat <= e for s, e in coverage.get((number, r.get("WERKS")), [])):
            flags.append("OFF_CONTRACT")
        assignment = ekkn.get((r.get("EBELN"), r.get("EBELP")), {})
        cost_object = (f"COST_CENTER:{assignment['KOSTL']}" if assignment.get("KOSTL") else
                       f"WBS:{assignment['POSID']}" if assignment.get("POSID") else None)
        variance = 0
        std = st.materials.get(number, {}).get("std") if number else None
        if std and qty and r.get("SHKZG") != "H":
            variance = max(0, amount - int((qty * std).to_integral_value(rounding=ROUND_HALF_UP)))
        st.spend.append({"key": (bukrs, r["GJAHR"], r["BELNR"], r["BUZEI"]), "ref": key, "po_ref": r.get("EBELN"), "vendor": vendor,
                         "category": category or "UNCLASSIFIED", "group": group[:30] or "UNMAPPED", "plant": r.get("WERKS") or po_row.get("WERKS"),
                         "bukrs": bukrs, "cost_object": cost_object, "period": period, "amount": signed, "contracted": contracted,
                         "addressable": not intercompany, "flags": flags, "confidence": Decimal("1.000") if category not in (None, "UNCLASSIFIED")
                         else Decimal("0.000"), "description": (po_row.get("TXZ01") or group)[:300], "variance": variance})
    # qualified categories: sourced through info records or agreements, or at least three invoice lines in the history
    lines_per = Counter((s["vendor"], s["category"]) for s in st.spend if s["category"] not in ("UNCLASSIFIED", "IC-TRANSFER"))
    categories = defaultdict(set)
    for vendor in st.vendors:
        categories[vendor] |= _sourced(st, vendor)
    for (vendor, category), n in lines_per.items():
        if n >= 3:
            categories[vendor].add(category)
    st.vendor_categories = categories
    # ---- spend history: FI vendor invoices without PO
    cost_plant = {r["KOSTL"]: r.get("WERKS") for r in x.rows("CSKS")}
    for r in x.rows("BSEG_KR"):
        key = f"{r['BELNR']}/{r['GJAHR']}/{r['BUZEI']}"
        rep.counts["spendLines"]["extract"] += 1
        amount = minor(r.get("WRBTR")) or 0
        posting = day(r.get("BUDAT"))
        bukrs = r.get("BUKRS") or st.bukrs
        period = _period(posting) if posting else None
        if period:
            st.spend_extract[(bukrs, period)] += amount
        vendor = alpha(r.get("LIFNR"))
        if vendor not in st.vendors or posting is None:
            rep.reject("spendLines", "BSEG_KR", r, key, "VENDOR_NOT_LOADED" if vendor not in st.vendors else "DATE_INVALID",
                       f"vendor {vendor} rejected or missing" if vendor not in st.vendors else f"posting date {r.get('BUDAT')!r}", amount=amount)
            if period:
                st.spend_rejected[(bukrs, period)] += amount
                st.spend_rejected_genuine[(bukrs, period)] += amount
            continue
        st.spend.append({"key": (bukrs, r["GJAHR"], r["BELNR"], r["BUZEI"]), "ref": key, "po_ref": None, "vendor": vendor, "category": "UNCLASSIFIED",
                         "group": f"GL-{r.get('HKONT')}"[:30], "plant": cost_plant.get(r.get("KOSTL")) or sorted(st.plants)[0], "bukrs": bukrs,
                         "cost_object": f"COST_CENTER:{r['KOSTL']}" if r.get("KOSTL") else None, "period": period, "amount": amount,
                         "contracted": False, "addressable": True, "flags": [], "confidence": Decimal("0.000"),
                         "description": (r.get("SGTXT") or r.get("HKONT"))[:300], "variance": 0})


def _sourced(st: Staged, vendor: str) -> set:
    if not hasattr(st, "_sourced"):
        st._sourced = defaultdict(set)
        for i in st.info_records:
            st._sourced[i["vendor"]].add(st.materials[i["material"]]["category"])
        for a in st.agreements.values():
            for item in a["items"]:
                if item["material"] in st.materials:
                    st._sourced[a["vendor"]].add(st.materials[item["material"]]["category"])
    return st._sourced[vendor]


def _stage_ap(st: Staged) -> None:
    rep, x = st.report, st.extract
    rseg = defaultdict(list)
    for r in x.rows("RSEG"):
        rseg[(r["BELNR"], r["GJAHR"])].append(r)
    fi = defaultdict(list)
    for r in x.rows("BSEG_KR"):
        fi[(r["BELNR"], r["GJAHR"])].append(r)
    seen_keys = {}
    for r in x.rows("BSIK"):
        if r.get("BUKRS") != st.bukrs:
            continue
        key = f"{r['BELNR']}/{r['GJAHR']}"
        rep.counts["openAp"]["extract"] += 1
        amount = minor(r.get("WRBTR")) or 0
        signed = amount if r.get("SHKZG") == "H" else -amount
        vendor = alpha(r["LIFNR"])
        baseline, days_ = day(r.get("ZFBDT")) or day(r.get("BLDAT")), int(dec(r.get("ZBD1T")) or 0)
        due = baseline + timedelta(days=days_) if baseline else None
        st.ap_extract.append({"vendor": vendor, "amount": signed, "due": due})
        reason = None
        doc = st.rbkp.get((r["BELNR"], r["GJAHR"]))
        lines = rseg.get((r["BELNR"], r["GJAHR"]), []) if doc else fi.get((r["BELNR"], r["GJAHR"]), [])
        bldat = day(r.get("BLDAT"))
        fiscal = clock.fiscal_year(bldat) if bldat else None
        dup_key = (vendor, (r.get("XBLNR") or "").upper(), fiscal)
        if vendor not in st.vendors:
            reason = ("VENDOR_NOT_LOADED", f"vendor {vendor} rejected or missing")
        elif r.get("SHKZG") != "H":
            reason = ("DEBIT_ITEM", "open debit item (credit memo / down payment): settle it in SAP before cutover")
        elif not r.get("XBLNR") or bldat is None or due is None:
            reason = ("REFERENCE_MISSING", "supplier invoice number (XBLNR), document date and baseline date are required")
        elif dup_key in seen_keys:
            reason = ("DUPLICATE_INVOICE", f"supplier invoice {r.get('XBLNR')} of {vendor} ({fiscal}) is already open as {seen_keys[dup_key]}: "
                      "posted twice in SAP - reverse one before payment")
        elif (minor(r.get("QBSHB")) or 0) != 0:
            reason = ("WITHHOLDING_NOT_SUPPORTED", "withholding tax on the open item: PIC has no withholding amount on invoices yet")
        elif not lines:
            reason = ("DOCUMENT_NOT_FOUND", "no RBKP/RSEG or BSEG_KR lines for the open item")
        if reason:
            rep.reject("openAp", "BSIK", r, key, reason[0], reason[1], amount=signed)
            continue
        seen_keys[dup_key] = key
        if doc:
            gross, tax = minor(doc.get("RMWWR")) or 0, minor(doc.get("WMWST1")) or 0
        else:
            net_fi = sum(minor(l.get("WRBTR")) or 0 for l in lines)
            tax = sum(minor(l.get("WMWST")) or 0 for l in lines)
            gross = net_fi + tax
        if gross != amount:
            rep.reject("openAp", "BSIK", r, key, "PARTIAL_OR_WITHHELD", f"open amount {money(amount)} differs from the document gross {money(gross)}",
                       amount=signed)
            continue
        out_lines = []
        for k, l in enumerate(lines, start=1):
            net = minor(l.get("WRBTR")) or 0
            qty = dec(l.get("MENGE")) or Decimal(1)
            po_row = st.ekpo_by_key.get((l.get("EBELN"), l.get("EBELP"))) if doc else None
            rate = st.tax.get(l.get("MWSKZ"), Decimal(18))
            out_lines.append({"line_no": k * 10, "ebeln": l.get("EBELN"), "ebelp": l.get("EBELP"), "qty": qty if qty > 0 else Decimal(1),
                              "net": net, "rate": rate, "hsn": (po_row or {}).get("J_1BNBM") or None,
                              "description": ((po_row or {}).get("TXZ01") or l.get("SGTXT") or "ERP invoice line")[:200]})
        st.ap_items.append({"key": key, "belnr": r["BELNR"], "gjahr": r["GJAHR"], "vendor": vendor, "xblnr": r["XBLNR"], "bldat": bldat,
                            "budat": day(r.get("BUDAT")), "due": due, "gross": gross, "tax": tax, "net": gross - tax, "block": r.get("ZLSPR") or "",
                            "ebeln": r.get("EBELN") or None, "lines": out_lines, "zterm": r.get("ZTERM"), "fiscal": fiscal})


def _stage_gl(st: Staged) -> None:
    x = st.extract
    for r in x.rows("ACDOCA_PERIOD_TOTALS"):
        period = _fiscal_period(r.get("GJAHR", ""), r.get("POPER", ""))
        if period and r.get("RBUKRS") == st.bukrs:
            st.gl[(st.bukrs, period)] += minor(r.get("HSL")) or 0
    for r in x.rows("GL_RECON_ITEMS"):
        period = _fiscal_period(r.get("GJAHR", ""), r.get("POPER", ""))
        if period:
            st.recon[(r.get("RBUKRS"), period)].append({"account": r.get("RACCT"), "amountMinor": minor(r.get("HSL")) or 0,
                                                        "reason": r.get("REASON"), "document": r.get("BELNR"), "description": r.get("DESCRIPTION")})
    for r in x.rows("GL_BALANCES"):
        st.ap_gl_balance[(r.get("RBUKRS"), r.get("RACCT"))] = minor(r.get("HSL")) or 0


# ---------------------------------------------------------------- loading
class Loader:
    def __init__(self, tenant_code: str, st: Staged, when: Optional[datetime]):
        self.st, self.code, self.when = st, tenant_code, when
        with system_tx() as s:
            tenant = s.execute(select(Tenant).where(Tenant.code == tenant_code)).scalar_one_or_none()
        if tenant is None:
            raise ExtractError(f"Tenant {tenant_code} does not exist: create it first (tenant onboarding, or the dataset pack erp-client-kac)")
        self.tenant_id = tenant.id
        self.principal = IntegrationPrincipal(user_id=uuid.UUID(int=0), tenant_id=tenant.id, tenant_code=tenant_code, email="integration.sap_s4",
                                              name="SAP S/4HANA inbound", roles=[], scopes={"spend:read"}, agent_code=None)
        self.audit_actions = {}

    def tx(self):
        if self.when:
            clock.set_pinned(self.when)
        return tenant_tx(self.tenant_id, self.principal.user_id, self.principal)

    def record_load(self, s, obj: str, new: int, existed: int, extra: Optional[dict] = None) -> None:
        """INITIAL_LOAD the first time an object type is loaded from the ERP, ERP_DELTA for every later extract."""
        if not new:
            return
        object_ref = f"{SOURCE} {obj}"[:60]
        earlier = s.execute(select(AuditEvent.event_id).where(AuditEvent.tenant_id == self.tenant_id, AuditEvent.object_type == "MIGRATION",
                                                        AuditEvent.object_ref == object_ref,
                                                        AuditEvent.action.in_(("INITIAL_LOAD", "ERP_DELTA"))).limit(1)).first()
        action = "ERP_DELTA" if earlier else "INITIAL_LOAD"
        self.audit_actions[obj] = action
        ref = f"{self.st.extract.manifest.get('extractId')}:{obj}"
        audit.record(s, "MIGRATION", uuid.uuid5(NS, f"{self.code}|{ref}"), action, object_ref=object_ref,
                     after={"extract": self.st.extract.manifest.get("extractId"), "object": obj, "loaded": new, "alreadyLoaded": existed,
                            **(extra or {})}, actor=ACTOR)

    # -------------------------------------------------------------- 1 org
    def org(self) -> None:
        from app.pic.seed import reference
        from app.pic.services import spend
        st, rep = self.st, self.st.report
        with self.tx() as s:
            bootstrapped = s.execute(select(NumberRange.id)).first() is not None
        if not bootstrapped:
            reference.deploy_process_definitions()
            reference.bootstrap(self.tenant_id, company=(st.company["code"], st.company["name"], st.company["gstin"]),
                                plants=[(p["code"], p["name"], p["state"]) for p in st.plants.values()], cost_objects=st.cost_objects)
            reference.ensure_extensions(self.tenant_id)
        with self.tx() as s:
            new = existed = 0
            if not s.execute(select(CompanyCode.id).where(CompanyCode.code == st.company["code"])).first():
                s.add(CompanyCode(tenant_id=self.tenant_id, code=st.company["code"], name=st.company["name"], gstin=st.company["gstin"], currency="INR"))
            have = set(s.execute(select(Plant.code)).scalars())
            for p in st.plants.values():
                if p["code"] in have:
                    existed += 1
                    continue
                s.add(Plant(tenant_id=self.tenant_id, code=p["code"], name=p["name"], company_code=st.company["code"], state_code=p["state"],
                            working_days=[0, 1, 2, 3, 4, 5], holidays=[]))
                s.add(StorageLocation(tenant_id=self.tenant_id, plant=p["code"], code="0001", name="Raw material & bought-out parts"))
                new += 1
            rep.counts["plants"]["loaded"] += new
            rep.counts["plants"]["existing"] += existed
            have_co = {(c.type, c.code) for c in s.execute(select(CostObject)).scalars()}
            new_co = 0
            for type_, code, name in st.cost_objects:
                if (type_, code) in have_co:
                    rep.counts["costObjects"]["existing"] += 1
                    continue
                s.add(CostObject(tenant_id=self.tenant_id, type=type_, code=code, name=name[:200], company_code=st.company["code"]))
                new_co += 1
            rep.counts["costObjects"]["loaded"] += new_co
            spend.ensure_taxonomy(s, self.tenant_id)
            nodes = set(s.execute(select(TaxonomyNode.code)).scalars())
            added = []
            for code, parent, level, name, keywords, addressable in st.taxonomy:
                if code in nodes:
                    continue
                s.add(TaxonomyNode(tenant_id=self.tenant_id, code=code, parent_code=parent, level=level, name=name, keywords=keywords,
                                   addressable=addressable))
                nodes.add(code)
                added.append(code)
            s.flush()
            self.record_load(s, "org", new + new_co + len(added), existed, {"plants": new, "costObjects": new_co, "taxonomy": added})

    # -------------------------------------------------------------- 2 vendors
    def vendors(self) -> None:
        from app.pic.services import supplier as supplier_svc
        st, rep = self.st, self.st.report
        tid = self.tenant_id
        with self.tx() as s:
            existing = {x.code: x for x in s.execute(select(Supplier)).scalars()}
            had_any = bool(existing)
            new_ids = []
            for code, v in st.vendors.items():
                sup = existing.get(code)
                if sup is not None:
                    rep.counts["vendors"]["existing"] += 1
                    self._vendor_delta(s, sup, v)
                    continue
                status = "BLOCKED" if (v["blocked"] or v["deleted"]) else "ACTIVE"
                sup = Supplier(tenant_id=tid, code=code, legal_name=v["name"], status=status, gstin_enc=crypto.encrypt(tid, "gstin", v["gstin"]),
                               gstin_masked=crypto.mask(v["gstin"]), gstin_hash=crypto.blind_index(tid, v["gstin"]), pan_hash=crypto.blind_index(tid, v["pan"]),
                               state_code=v["state"], country="IN", payment_terms=v["terms"], contact_email=v["email"], address=v["address"],
                               segment="INTERCOMPANY" if v["account_group"] == "ZICO" else None, created_by=self.principal.user_id,
                               screening={"source": "ERP_INITIAL_LOAD", "erpVendor": v["lifnr"]})
                s.add(sup)
                s.flush()
                existing[code] = sup
                new_ids.append(sup.id)
                for category in sorted(st.vendor_categories.get(code, ())):
                    s.add(SupplierCategoryStatus(tenant_id=tid, supplier_id=sup.id, category=category, status="EXITED" if v["deleted"] else "QUALIFIED",
                                                 qualified_on=v["created"], created_by=self.principal.user_id))
                if v["bank"] and not v["deleted"]:
                    b = v["bank"]
                    s.add(SupplierBankAccount(tenant_id=tid, supplier_id=sup.id, account_enc=crypto.encrypt(tid, "bank", b["account"]),
                                              account_masked=crypto.mask(b["account"]), ifsc=b["ifsc"], holder_name=b["holder"][:200], active=True,
                                              verified_on=v["created"], created_by=self.principal.user_id))
                audit.record(s, "SUPPLIER", sup.id, "MIGRATED", object_ref=code,
                             after={"source": "SAP_S4 vendor master (LFA1/LFB1/LFBK)", "legalName": v["name"], "gstin": sup.gstin_masked,
                                    "status": status, "paymentTerms": v["terms"], "erpBlock": "deletion flag" if v["deleted"] else ("posting/purchasing block" if v["blocked"] else None),
                                    "bank": crypto.mask(v["bank"]["account"]) if v["bank"] else None,
                                    "categories": sorted(st.vendor_categories.get(code, ()))})
                rep.counts["vendors"]["loaded"] += 1
                if v["bank"] and not v["deleted"]:
                    rep.counts["vendorBanks"]["loaded"] += 1
            s.flush()
            # F8-03 duplicate and sanctions screening of the new vendor masters, plus the shared-bank-account check
            accounts = defaultdict(list)
            for acc, sup_code in s.execute(select(SupplierBankAccount, Supplier.code).join(Supplier, Supplier.id == SupplierBankAccount.supplier_id)).all():
                accounts[crypto.blind_index(tid, f"{acc.ifsc}|{crypto.decrypt(tid, 'bank', acc.account_enc)}")].append(sup_code)
            shared = {}
            for codes in accounts.values():
                if len(codes) > 1:
                    for c in codes:
                        shared[c] = sorted(x for x in codes if x != c)
            for sup_id in new_ids:
                sup = s.get(Supplier, sup_id)
                v = st.vendors[sup.code]
                result = supplier_svc.screen(s, sup, record_step=False)
                screening = {**result, "source": "ERP_INITIAL_LOAD" if not had_any else "ERP_DELTA", "erpVendor": v["lifnr"],
                             "accountGroup": v["account_group"]}
                if v["blocked"] or v["deleted"]:
                    screening["erpBlock"] = "LOEVM" if v["deleted"] else "SPERR"
                if sup.code in shared:
                    screening["bankDuplicates"] = shared[sup.code]
                    screening["duplicates"] = list(screening.get("duplicates") or []) + [
                        {"code": c, "reason": "same bank account (IFSC and account number)"} for c in shared[sup.code]]
                    if screening["outcome"] == "CLEAR":
                        screening["outcome"] = "REVIEW"
                sup.screening = screening
            self.record_load(s, "vendors", len(new_ids), rep.counts["vendors"]["existing"],
                             {"banks": rep.counts["vendorBanks"]["loaded"], "screened": len(new_ids)})

    def _vendor_delta(self, s, sup: Supplier, v: dict) -> None:
        """Delta extract on an existing vendor: descriptive fields are updated, tax ID and bank changes go through MDM-04."""
        rep, tid = self.st.report, self.tenant_id
        if sup.gstin_hash != crypto.blind_index(tid, v["gstin"]):
            rep.reject("vendors", "LFA1", {}, sup.code, "SENSITIVE_CHANGE", "GSTIN differs from the PIC master: raise an MDM-04 tax-ID change")
            return
        if v["bank"]:
            current = s.execute(select(SupplierBankAccount).where(SupplierBankAccount.supplier_id == sup.id, SupplierBankAccount.active.is_(True))).scalars().first()
            if current is not None and (current.ifsc != v["bank"]["ifsc"] or crypto.decrypt(tid, "bank", current.account_enc) != v["bank"]["account"]):
                rep.reject("vendorBanks", "LFBK", {}, sup.code, "SENSITIVE_CHANGE", "bank account differs from PIC: raise a bank change (call-back, "
                           "dual approval, cooling-off) - not applied from the ERP")
        changes = {}
        status = "BLOCKED" if (v["blocked"] or v["deleted"]) else ("ACTIVE" if sup.status == "BLOCKED" and (sup.screening or {}).get("erpBlock") else sup.status)
        for attr, value in (("legal_name", v["name"]), ("payment_terms", v["terms"]), ("address", v["address"]), ("contact_email", v["email"]),
                            ("status", status)):
            if getattr(sup, attr) != value:
                changes[attr] = (getattr(sup, attr), value)
                setattr(sup, attr, value)
        if changes:
            if "status" in changes:
                sup.screening = {**(sup.screening or {}), "erpBlock": ("LOEVM" if v["deleted"] else "SPERR") if status == "BLOCKED" else None}
            audit.record(s, "SUPPLIER", sup.id, "ERP_DELTA", object_ref=sup.code, before={k: b for k, (b, _) in changes.items()},
                         after={k: a for k, (_, a) in changes.items()}, actor=ACTOR)
            rep.counts["vendors"]["updated"] = rep.counts["vendors"].get("updated", 0) + 1

    # -------------------------------------------------------------- 3 materials, info records, source lists
    def materials(self) -> None:
        st, rep, tid = self.st, self.st.report, self.tenant_id
        with self.tx() as s:
            existing = {m.number: m for m in s.execute(select(Material)).scalars()}
            new = 0
            for number, m in st.materials.items():
                mat = existing.get(number)
                if mat is not None:
                    rep.counts["materials"]["existing"] += 1
                    changes = {}
                    for attr, value in (("description", m["description"]), ("hsn_code", m["hsn"]), ("gst_rate", m["gst"]),
                                        ("standard_price_minor", m["std"])):
                        if getattr(mat, attr) != value:
                            changes[attr] = (str(getattr(mat, attr)), str(value))
                            setattr(mat, attr, value)
                    if changes:
                        audit.record(s, "MATERIAL", mat.id, "ERP_DELTA", object_ref=number, before={k: b for k, (b, _) in changes.items()},
                                     after={k: a for k, (_, a) in changes.items()}, actor=ACTOR)
                    continue
                s.add(Material(tenant_id=tid, number=number, description=m["description"], type=m["type"], material_group=m["group"][:30],
                               category=m["category"], base_uom=m["uom"], valuation_class=m["valuation_class"], hsn_code=m["hsn"], gst_rate=m["gst"],
                               mpn=m["mpn"], attributes={"erpMaterialType": m["mtart"], "plants": m["plants"], "source": SOURCE},
                               mrp_type=m["mrp_type"], lot_size_policy=m["lot"], lot_size_qty=m["lot_qty"], min_lot=m["min_lot"], max_lot=m["max_lot"],
                               safety_stock=m["safety"], planned_delivery_days=m["pdt"], gr_processing_days=m["grt"], quality_managed=m["qm"],
                               standard_price_minor=m["std"], status="ACTIVE", erp_synced=True, created_by=self.principal.user_id))
                new += 1
            rep.counts["materials"]["loaded"] += new
            s.flush()
            self.record_load(s, "materials", new, rep.counts["materials"]["existing"])
            materials = {m.number: m.id for m in s.execute(select(Material)).scalars()}
            suppliers = {x.code: x.id for x in s.execute(select(Supplier)).scalars()}
            have = {(i.supplier_id, i.material_id, i.plant): i for i in s.execute(select(InfoRecord)).scalars()}
            new_ir = 0
            for i in st.info_records:
                k = (suppliers[i["vendor"]], materials[i["material"]], i["plant"])
                if k in have:
                    rep.counts["infoRecords"]["existing"] += 1
                    if have[k].last_price_minor != i["price"]:
                        have[k].last_price_minor = i["price"]
                    continue
                have[k] = InfoRecord(tenant_id=tid, supplier_id=k[0], material_id=k[1], plant=k[2], last_price_minor=i["price"],
                                     lead_time_days=i["lead"], created_by=self.principal.user_id)
                s.add(have[k])
                new_ir += 1
            rep.counts["infoRecords"]["loaded"] += new_ir
            self.record_load(s, "infoRecords", new_ir, rep.counts["infoRecords"]["existing"])
            have_sl = {(x.supplier_id, x.material_id, x.plant, x.valid_from) for x in s.execute(select(SourceList)).scalars()}
            new_sl = 0
            for i in st.source_lists:
                k = (suppliers[i["vendor"]], materials[i["material"]], i["plant"], i["from"])
                if k in have_sl:
                    rep.counts["sourceLists"]["existing"] += 1
                    continue
                s.add(SourceList(tenant_id=tid, supplier_id=k[0], material_id=k[1], plant=k[2], fixed=i["fixed"], valid_from=i["from"], valid_to=i["to"],
                                 created_by=self.principal.user_id))
                have_sl.add(k)
                new_sl += 1
            rep.counts["sourceLists"]["loaded"] += new_sl
            self.record_load(s, "sourceLists", new_sl, rep.counts["sourceLists"]["existing"])

    # -------------------------------------------------------------- 4 agreements
    def agreements(self) -> None:
        st, rep, tid = self.st, self.st.report, self.tenant_id
        with self.tx() as s:
            existing = set(s.execute(select(Contract.number)).scalars())
            suppliers = {x.code: x for x in s.execute(select(Supplier)).scalars()}
            materials = {m.number: m.id for m in s.execute(select(Material)).scalars()}
            owner = s.execute(select(AppUser.id).where(AppUser.roles.any("CONTRACT_MANAGER"), AppUser.active.is_(True))
                              .order_by(AppUser.email)).scalars().first() or self.principal.user_id
            playbook = rules.resolve(s, "CLM-PLAYBOOK")
            approval = rules.resolve(s, "CONTRACT-APPROVAL", company_code=st.bukrs)
            released = self._released()
            new = 0
            for ebeln, a in sorted(st.agreements.items()):
                if not a["active"]:
                    continue
                if ebeln in existing:
                    rep.counts["agreements"]["existing"] += 1
                    continue
                supplier = suppliers[a["vendor"]]
                first = a["items"][0]
                contract = Contract(tenant_id=tid, number=ebeln, type=a["type"], title=f"{_TYPE_TITLE[a['type']]} {ebeln} - {supplier.legal_name}"[:200],
                                    supplier_id=supplier.id, company_code=st.bukrs, status="ACTIVE", valid_from=a["start"], valid_to=a["end"],
                                    payment_terms=a["terms"] or supplier.payment_terms, incoterms=a["incoterms"], over_tolerance_pct=first["over"],
                                    under_tolerance_pct=first["under"], price_tolerance_pct=Decimal(0), owner_id=owner,
                                    rule_set_version=playbook.ref, activated_at=clock.at_ist(a["start"], 0), created_by=self.principal.user_id)
                s.add(contract)
                s.flush()
                target = 0
                for item in a["items"]:
                    current = next((p for s_, e_, p in item["conditions"] if s_ <= st.key_date <= e_), item["conditions"][-1][2])
                    qty, value = released.get((ebeln, item["ebelp"]), (Decimal(0), 0))
                    line = ContractLine(tenant_id=tid, contract_id=contract.id, line_no=item["ebelp"], material_id=materials.get(item["material"]),
                                        description=(item["text"] or item["material"] or "")[:200], plant=item["plant"], uom=(item["uom"] or "EA")[:5],
                                        target_qty=item["target"], released_qty=qty, released_value_minor=value, created_by=self.principal.user_id)
                    s.add(line)
                    s.flush()
                    for start, end, price in item["conditions"]:
                        s.add(PriceValidity(tenant_id=tid, contract_line_id=line.id, valid_from=start, valid_to=end, unit_price_minor=price,
                                            reason="ERP_CONDITION", published=True, created_by=self.principal.user_id))
                    target += int((item["target"] * current).to_integral_value(rounding=ROUND_HALF_UP))
                contract.target_value_minor = a["header_value"] or target
                for template in playbook.body["templates"].get(a["type"], []):
                    text = template["text"].format(terms=contract.payment_terms, incoterms=contract.incoterms or "", supplier=supplier.legal_name,
                                                   band="", over=first["over"], under=first["under"])
                    s.add(Clause(tenant_id=tid, contract_id=contract.id, code=template["code"], title=template["title"], text=text, position="STANDARD",
                                 risk_score=0, created_by=self.principal.user_id))
                instance = workflow.start(s, "pic.contract", "CONTRACT", contract.id, contract.number, {"trigger": "migration", "source": SOURCE})
                workflow.step(s, instance, "F4-08", outcome=f"migrated from {SOURCE} agreement {ebeln}: active, "
                              f"{sum(len(i['conditions']) for i in a['items'])} price validity period(s) published")
                workflow.wait(s, instance, "F4-09", outcome="tracking consumption & obligations")
                notice = int(approval.body["renewalNoticeDays"])
                workflow.create_timer(s, "CONTRACT_RENEWAL", "CONTRACT", contract.id,
                                      max(clock.at_ist(a["end"] - timedelta(days=notice), 9), clock.now()))
                workflow.create_timer(s, "CONTRACT_EXPIRY", "CONTRACT", contract.id, clock.at_ist(a["end"] + timedelta(days=1), 0, 5))
                audit.record(s, "CONTRACT", contract.id, "MIGRATED", object_ref=contract.number,
                             after={"source": f"{SOURCE} EKKO/EKPO/A016", "type": a["type"], "supplier": supplier.code, "validFrom": a["start"],
                                    "validTo": a["end"], "targetValueMinor": contract.target_value_minor,
                                    "releasedValueMinor": sum(released.get((ebeln, i["ebelp"]), (0, 0))[1] for i in a["items"])})
                new += 1
            rep.counts["agreements"]["loaded"] += new
            self.record_load(s, "agreements", new, rep.counts["agreements"]["existing"])

    def _released(self) -> dict:
        """Consumption so far per agreement item: goods receipts against scheduling agreements, release orders of contracts."""
        st = self.st
        out = defaultdict(lambda: [Decimal(0), 0])
        for (ebeln, ebelp), h in st.history.items():
            a = st.agreements.get(ebeln)
            if a is not None and a["bstyp"] == "L":
                out[(ebeln, int(ebelp))][0] += h["gr_qty"]
                out[(ebeln, int(ebelp))][1] += h["gr_value"]
        for r in st.ekpo_by_key.values():
            if r.get("KONNR") and r.get("KTPNR") and not r.get("LOEKZ") and st.ekko.get(r["EBELN"], {}).get("BSTYP") == "F":
                k = (r["KONNR"], int(r["KTPNR"]))
                out[k][0] += dec(r.get("MENGE")) or Decimal(0)
                out[k][1] += minor(r.get("NETWR")) or 0
        return {k: (v[0], v[1]) for k, v in out.items()}

    # -------------------------------------------------------------- 5 open purchase orders
    def open_pos(self) -> None:
        st, rep, tid = self.st, self.st.report, self.tenant_id
        with self.tx() as s:
            existing = set(s.execute(select(PurchaseOrder.erp_doc_no).where(PurchaseOrder.erp_doc_no.is_not(None))).scalars())
            suppliers = {x.code: x for x in s.execute(select(Supplier)).scalars()}
            materials = {m.number: m for m in s.execute(select(Material)).scalars()}
            contracts = {c.number: c for c in s.execute(select(Contract)).scalars()}
            contract_lines = {(c.contract_id, c.line_no): c for c in s.execute(select(ContractLine)).scalars()}
            infos = {(i.supplier_id, i.material_id) for i in s.execute(select(InfoRecord)).scalars()}
            tolerance_rule = rules.resolve(s, "RCV-TOLERANCE", company_code=st.bukrs)
            new_pos = new_lines = 0
            for ebeln, po in sorted(st.open_pos.items()):
                if ebeln in existing:
                    rep.counts["openPoLines"]["existing"] += len(po["lines"])
                    continue
                header = po["header"]
                supplier = suppliers[alpha(header["LIFNR"])]
                lines = sorted(po["lines"], key=lambda l: l["ebelp"])
                contract_numbers = {l["contract"]["ebeln"] for l in lines if l["contract"]}
                contract = contracts.get(next(iter(contract_numbers))) if len(contract_numbers) == 1 else None
                over = max((dec(l["row"].get("UEBTO")) or Decimal(0)) for l in lines)
                under = max((dec(l["row"].get("UNTTO")) or Decimal(0)) for l in lines)
                tolerance = ({"over_pct": str(over), "under_pct": str(under), "price_pct": "0"} if (over or under) else dict(tolerance_rule.body))
                bedat = day(header.get("BEDAT")) or st.key_date
                plant = lines[0]["row"].get("WERKS")
                goods = [l for l in lines if l["row"].get("WEPOS") == "X"]
                if goods and all(l["history"]["gr_qty"] >= l["qty"] for l in goods):
                    status = "RECEIVED"
                elif any(l["history"]["gr_qty"] > 0 for l in goods):
                    status = "PARTIALLY_RECEIVED"
                else:
                    status = "CONFIRMED"
                order = PurchaseOrder(tenant_id=tid, number=next_number(s, "PURCHASE_ORDER"), version=1, company_code=header.get("BUKRS") or st.bukrs,
                                      purch_org=header.get("EKORG") or "1000", plant=plant, supplier_id=supplier.id, status=status,
                                      contract_id=contract.id if contract else None, purpose_code="ERP_OPEN_PO", currency=header.get("WAERS") or "INR",
                                      total_minor=sum(l["net"] for l in lines), payment_terms=st.terms.get(header.get("ZTERM")) or supplier.payment_terms,
                                      incoterms=" ".join(p for p in (header.get("INCO1"), header.get("INCO2")) if p) or None, tolerance=tolerance,
                                      inherited={"migratedFrom": SOURCE, "erpDocument": ebeln, "orderDate": bedat.isoformat(),
                                                 "purchasingGroup": header.get("EKGRP"), "extract": st.extract.manifest.get("extractId")},
                                      rule_set_version="MIGRATION", released_by=SOURCE, released_at=clock.at_ist(bedat, 9), transmitted_via="ERP",
                                      transmitted_at=clock.at_ist(bedat, 9), erp_doc_no=ebeln, touchless=False, created_by=self.principal.user_id)
                s.add(order)
                s.flush()
                for l in lines:
                    r, h = l["row"], l["history"]
                    material = materials.get(l["material"]) if l["material"] else None
                    knttp = r.get("KNTTP") or ""
                    if knttp in ("A", "P"):
                        purchase_type = "ASSET"
                    elif material is not None and material.type == "SERVICE" or (material is None and r.get("WEPOS") != "X"):
                        purchase_type = "SERVICE"
                    elif knttp:
                        purchase_type = "NON_STOCK"
                    else:
                        purchase_type = "STOCK"
                    contract_line = None
                    if l["contract"] and l["contract_item"] and l["contract"]["ebeln"] in contracts:
                        contract_line = contract_lines.get((contracts[l["contract"]["ebeln"]].id, l["contract_item"]))
                    validity = None
                    if contract_line is not None:
                        validity = s.execute(select(PriceValidity).where(PriceValidity.contract_line_id == contract_line.id,
                                                                         PriceValidity.valid_from <= bedat, PriceValidity.valid_to >= bedat)).scalars().first()
                    assignment = l["assignment"]
                    a_type, a_code = (("COST_CENTER", assignment["KOSTL"]) if assignment.get("KOSTL") else
                                      ("WBS", assignment["POSID"]) if assignment.get("POSID") else (None, None))
                    received = max(h["gr_qty"], Decimal(0))
                    need = min((day(e["EINDT"]) for e in l["schedule"] if day(e.get("EINDT"))), default=bedat)
                    gst = st.tax.get(r.get("MWSKZ"), material.gst_rate if material else Decimal(18))
                    line = PoLine(tenant_id=tid, po_id=order.id, line_no=l["ebelp"],
                                  item_type="CONTRACT" if contract_line is not None and material is not None else ("MATERIAL" if material else "FREE_TEXT"),
                                  purchase_type=purchase_type, material_id=material.id if material else None, description=(r.get("TXZ01") or "")[:200] or "ERP line",
                                  material_group=(r.get("MATKL") or (material.material_group if material else "UNMAPPED"))[:30], qty=l["qty"],
                                  uom=UOM.get((r.get("MEINS") or "").upper(), (r.get("MEINS") or "EA")[:5]), unit_price_minor=l["unit_price"],
                                  net_minor=l["net"], gst_rate=gst, hsn_code=digits_of(r.get("J_1BNBM")) or (material.hsn_code if material else None),
                                  need_date=need, plant=r.get("WERKS"), storage_location=r.get("LGORT") or None, account_assignment_type=a_type,
                                  account_assignment_code=a_code, gr_required=r.get("WEPOS") == "X", ir_required=r.get("REPOS") == "X",
                                  ses_required=purchase_type == "SERVICE", ers=False, quality_managed=bool(material and material.quality_managed),
                                  price_source="CONTRACT" if contract_line is not None else (
                                      "INFO_RECORD" if material and (supplier.id, material.id) in infos else "MANUAL"),
                                  contract_line_id=contract_line.id if contract_line is not None else None,
                                  price_validity_id=validity.id if validity else None, received_qty=received, accepted_qty=received,
                                  invoiced_qty=max(h["ir_qty"], Decimal(0)), invoiced_minor=max(h["ir_value"], 0), shipped_qty=received,
                                  ses_approved_minor=max(h["gr_value"], 0) if purchase_type == "SERVICE" else 0, created_by=self.principal.user_id)
                    s.add(line)
                    s.flush()
                    entries = l["schedule"] or [{"ETENR": "1", "EINDT": need.isoformat(), "MENGE": str(l["qty"]), "WEMNG": str(received)}]
                    for k, e in enumerate(entries, start=1):
                        s.add(PoScheduleLine(tenant_id=tid, po_id=order.id, po_line_id=line.id, seq=k, qty=dec(e.get("MENGE")) or l["qty"],
                                             delivery_date=day(e.get("EINDT")) or need, received_qty=dec(e.get("WEMNG")) or Decimal(0),
                                             created_by=self.principal.user_id))
                    if contract_line is not None:
                        link(s, "CONTRACT", contract_line.contract_id, l["contract"]["ebeln"], "PURCHASE_ORDER", order.id, order.number,
                             "priced_by_contract", from_line=contract_line.line_no, to_line=line.line_no)
                    new_lines += 1
                instance = workflow.start(s, "pic.po", "PURCHASE_ORDER", order.id, order.number, {"migratedFrom": SOURCE, "erpDocument": ebeln})
                workflow.step(s, instance, "F5-06", outcome=f"migrated open order {ebeln} (ordered {bedat.isoformat()} in {SOURCE})")
                workflow.wait(s, instance, "F5-09", outcome=f"{status.lower().replace('_', ' ')}: awaiting delivery / invoice")
                audit.record(s, "PURCHASE_ORDER", order.id, "MIGRATED", object_ref=order.number,
                             after={"erpDocument": ebeln, "supplier": supplier.code, "status": status, "lines": len(lines),
                                    "openValueMinor": sum(max(0, l["net"] - l["history"]["ir_value"]) for l in lines)})
                new_pos += 1
            rep.counts["openPoLines"]["loaded"] += new_lines
            rep.counts["openPos"]["loaded"] += new_pos
            rep.counts["openPos"]["extract"] = len(st.open_pos)
            self.record_load(s, "openPos", new_pos, rep.counts["openPoLines"]["existing"], {"lines": new_lines})

    # -------------------------------------------------------------- 6 open AP
    def open_ap(self) -> None:
        from app.pic.services import payables
        st, rep, tid = self.st, self.st.report, self.tenant_id
        with self.tx() as s:
            existing = set(s.execute(select(Invoice.erp_doc_no, Invoice.fiscal_year).where(Invoice.erp_doc_no.is_not(None))).all())
            suppliers = {x.code: x for x in s.execute(select(Supplier)).scalars()}
            pos = {p.erp_doc_no: p for p in s.execute(select(PurchaseOrder).where(PurchaseOrder.erp_doc_no.is_not(None))).scalars()}
            po_lines = {}
            for line, erp in s.execute(select(PoLine, PurchaseOrder.erp_doc_no).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id)
                                       .where(PurchaseOrder.erp_doc_no.is_not(None))).all():
                po_lines[(erp, line.line_no)] = line
            target = integration.target_system(s, st.bukrs)
            simulator = target == "SAP_S4"
            taken = {(i.supplier_id, i.supplier_invoice_no, i.fiscal_year): i.number for i in s.execute(
                select(Invoice).where(Invoice.company_code == st.bukrs)).scalars()}
            registered = set(s.execute(select(ErpDocument.external_ref).where(ErpDocument.system == SOURCE)).scalars())
            new = 0
            for item in st.ap_items:
                if (item["belnr"], item["fiscal"]) in existing:
                    rep.counts["openAp"]["existing"] += 1
                    continue
                supplier = suppliers[item["vendor"]]
                clash = taken.get((supplier.id, item["xblnr"], item["fiscal"]))
                if clash:
                    rep.reject("openAp", "BSIK", {}, item["key"], "DUPLICATE_INVOICE", f"{item['xblnr']} of {supplier.code} already exists in PIC as {clash}",
                               amount=item["gross"])
                    continue
                po = pos.get(item["ebeln"]) if item["ebeln"] else None
                invoice = Invoice(tenant_id=tid, number=payables._internal_number(s, supplier.code, item["xblnr"], item["fiscal"]),
                                  supplier_invoice_no=item["xblnr"], fiscal_year=item["fiscal"], company_code=st.bukrs, supplier_id=supplier.id,
                                  po_id=po.id if po else None, invoice_date=item["bldat"], channel="ERP_MIGRATION", currency="INR",
                                  net_minor=item["net"], tax_minor=item["tax"], gross_minor=item["gross"], status="POSTED",
                                  payment_block=bool(item["block"]) or supplier.status in ("BLOCKED", "MERGED"), due_date=item["due"],
                                  erp_doc_no=item["belnr"], posting_key=f"{self.code}|{st.bukrs}|{supplier.code}|{item['xblnr']}",
                                  posted_at=clock.at_ist(item["budat"] or item["bldat"], 10), payment_status="UNPAID", rule_set_version="MIGRATION",
                                  created_by=self.principal.user_id)
                s.add(invoice)
                s.flush()
                for l in item["lines"]:
                    po_line = po_lines.get((l["ebeln"], int(l["ebelp"]))) if l["ebeln"] and l["ebelp"] else None
                    tax = int((Decimal(l["net"]) * l["rate"] / 100).to_integral_value(rounding=ROUND_HALF_UP))
                    s.add(InvoiceLine(tenant_id=tid, invoice_id=invoice.id, line_no=l["line_no"], po_line_id=po_line.id if po_line else None,
                                      description=l["description"], qty=l["qty"],
                                      unit_price_minor=int((Decimal(l["net"]) / l["qty"]).to_integral_value(rounding=ROUND_HALF_UP)), net_minor=l["net"],
                                      hsn_code=digits_of(l["hsn"]) or None, gst_rate=l["rate"], tax_minor=tax, match_status="ERP_POSTED",
                                      created_by=self.principal.user_id))
                taken[(supplier.id, item["xblnr"], item["fiscal"])] = invoice.number
                if simulator and invoice.posting_key not in registered:
                    registered.add(invoice.posting_key)
                    s.add(ErpDocument(tenant_id=tid, system=SOURCE, doc_type=integration.DOC_TYPES["SUPPLIER_INVOICE"][0], doc_no=item["belnr"],
                                      external_ref=invoice.posting_key, company_code=st.bukrs, amount_minor=item["gross"],
                                      payload={"migrated": True, "fiscalYear": item["gjahr"], "supplier": supplier.code, "invoice": item["xblnr"]}))
                instance = workflow.start(s, payables.PROCESS, "INVOICE", invoice.id, invoice.number, {"migratedFrom": SOURCE})
                workflow.step(s, instance, "F7-06", outcome=f"posted in {SOURCE} as {item['belnr']}/{item['gjahr']} (migrated open item)")
                workflow.wait(s, instance, "F7-07", outcome=f"due {item['due'].isoformat()}" + (f"; payment block {item['block']}" if item["block"] else ""))
                audit.record(s, "INVOICE", invoice.id, "MIGRATED", object_ref=invoice.number,
                             after={"erpDocument": item["belnr"], "fiscalYear": item["gjahr"], "supplier": supplier.code, "grossMinor": item["gross"],
                                    "due": item["due"], "paymentBlock": invoice.payment_block})
                existing.add((item["belnr"], item["fiscal"]))
                new += 1
            rep.counts["openAp"]["loaded"] += new
            self.record_load(s, "openAp", new, rep.counts["openAp"]["existing"])

    # -------------------------------------------------------------- 7 spend history
    def spend(self) -> None:
        from app.pic.services import spend as spend_svc
        st, rep, tid = self.st, self.st.report, self.tenant_id
        with self.tx() as s:
            existing = set(s.execute(select(SpendLine.invoice_line_id).where(SpendLine.source == "ERP_HISTORY")).scalars())
            had_any = bool(existing)
            suppliers = {x.code: x.id for x in s.execute(select(Supplier)).scalars()}
            rows = []
            for line in st.spend:
                key = uuid.uuid5(NS, f"{self.code}|" + "|".join(line["key"]))
                if key in existing:
                    rep.counts["spendLines"]["existing"] += 1
                    continue
                existing.add(key)
                rows.append({"tenant_id": tid, "invoice_line_id": key, "invoice_ref": line["ref"][:60], "po_ref": line["po_ref"],
                             "supplier_id": suppliers[line["vendor"]], "category": line["category"], "material_group": line["group"],
                             "plant": line["plant"], "company_code": line["bukrs"], "cost_object": line["cost_object"], "period": line["period"],
                             "amount_minor": line["amount"], "currency": "INR", "contracted": line["contracted"], "addressable": line["addressable"],
                             "maverick_flags": line["flags"], "classification_confidence": line["confidence"], "description": line["description"],
                             "po_line_id": None, "price_variance_minor": line["variance"], "source": "ERP_HISTORY", "created_by": self.principal.user_id})
            insert_rows(s, SpendLine.__table__, rows)
            rep.counts["spendLines"]["loaded"] += len(rows)
            spend_svc.ensure_taxonomy(s, tid)
        result = self._classify([r["invoice_line_id"] for r in rows]) if rows else {"auto": 0, "review": 0, "hits": 0}
        st.classification = result
        with self.tx() as s:
            self.record_load(s, "spendLines", len(rows), rep.counts["spendLines"]["existing"] if had_any else 0,
                             {"periods": sorted({r["period"] for r in rows})[:1] + sorted({r["period"] for r in rows})[-1:], "classification": result})

    def _classify(self, keys: list, chunk: int = 1000) -> dict:
        """Spend Classification Agent and maverick rules on the loaded lines: the per-line steps of services.spend.refresh, run in
        transactions of ``chunk`` lines so a 25k-line history does not keep every line in one session."""
        from app.pic.models import MaverickRule
        from app.pic.services import spend as spend_svc
        out = {"auto": 0, "review": 0, "hits": 0, "evaluated": 0}
        with self.tx() as s:
            limit = int(rules.resolve(s, "SPEND-GOVERNANCE").body["oneTimeVendorLimitMinor"])
            qualified = set(s.execute(select(SupplierCategoryStatus.supplier_id, SupplierCategoryStatus.category).where(
                SupplierCategoryStatus.status.in_(("QUALIFIED", "PREFERRED", "CONDITIONAL")))).all())

        def can_fire(line: SpendLine) -> bool:
            # evaluate_line acts only on lines with flags (hits), a PO line (NON_CATALOGUE) or an addressable line above the
            # one-time-vendor limit whose supplier is not qualified for the category (ONE_TIME_VENDOR); the rest is skipped
            return bool(line.maverick_flags or line.po_line_id or (line.addressable and line.amount_minor > limit and line.category != "UNCLASSIFIED"
                                                                   and (line.supplier_id, line.category) not in qualified))

        for start in range(0, len(keys), chunk):
            with self.tx() as s:
                nodes = spend_svc._nodes(s)
                active = {r.code: r for r in s.execute(select(MaverickRule).where(MaverickRule.active.is_(True))).scalars()}
                lines = s.execute(select(SpendLine).where(SpendLine.invoice_line_id.in_(keys[start:start + chunk]))
                                  .order_by(SpendLine.period, SpendLine.invoice_ref)).scalars().all()
                for line in lines:
                    result = spend_svc.classify_line(s, line, nodes)
                    if result:
                        out["auto" if result == "AUTO" else "review"] += 1
                    if can_fire(line):
                        out["evaluated"] += 1
                        out["hits"] += len(spend_svc.evaluate_line(s, line, active))
        return out

    # -------------------------------------------------------------- 8 tie-out
    def tie_out(self) -> dict:
        st = self.st
        with self.tx() as s:
            loaded = defaultdict(int)
            for bukrs, period, amount in s.execute(select(SpendLine.company_code, SpendLine.period, func.sum(SpendLine.amount_minor))
                                                   .where(SpendLine.source == "ERP_HISTORY").group_by(SpendLine.company_code, SpendLine.period)).all():
                loaded[(bukrs, period)] = int(amount)
            open_value = defaultdict(int)
            for code, net, invoiced in s.execute(select(Supplier.code, PoLine.net_minor, PoLine.invoiced_minor).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id)
                                                 .join(Supplier, Supplier.id == PurchaseOrder.supplier_id).where(PurchaseOrder.erp_doc_no.is_not(None))).all():
                open_value[code] += max(0, net - invoiced)
            ap_loaded = s.execute(select(Supplier.code, Invoice.gross_minor, Invoice.due_date).join(Supplier, Supplier.id == Invoice.supplier_id)
                                  .where(Invoice.channel == "ERP_MIGRATION", Invoice.status.in_(("POSTED",)))).all()
            contracts = s.execute(select(Contract).where(Contract.rule_set_version.is_not(None))).scalars().all()
            contracts = [c for c in contracts if c.number in st.agreements]
        return tie_out(st, loaded, open_value, [(c, g, d) for c, g, d in ap_loaded], contracts)


_TYPE_TITLE = {"SCHEDULING_AGREEMENT": "Scheduling agreement", "QUANTITY_CONTRACT": "Quantity contract", "VALUE_CONTRACT": "Value contract"}


def _bucket(due: Optional[date], key_date: date) -> str:
    if due is None:
        return "NO_DUE_DATE"
    overdue = (key_date - due).days
    if overdue <= 0:
        return "NOT_DUE"
    return "1-30" if overdue <= 30 else "31-60" if overdue <= 60 else "61-90" if overdue <= 90 else ">90"


def tie_out(st: Staged, loaded: Optional[dict] = None, open_value: Optional[dict] = None, ap_loaded: Optional[list] = None,
            contracts: Optional[list] = None) -> dict:
    """Extract vs loaded vs GL per company code and period (spend ±0.5 %), open AP vs the vendor reconciliation account,
    open PO value per supplier, contract value and validity. Without loaded figures (validate-only) the loaded column is
    what would load (extract minus rejects)."""
    validate_only = loaded is None
    periods = []
    keys = sorted(set(st.spend_extract) | set(st.gl))
    totals = defaultdict(int)
    for bukrs, period in keys:
        extract = st.spend_extract.get((bukrs, period), 0)
        rejected = st.spend_rejected.get((bukrs, period), 0)
        genuine = st.spend_rejected_genuine.get((bukrs, period), 0)
        done = extract - rejected if validate_only else loaded.get((bukrs, period), 0)
        gl = st.gl.get((bukrs, period), 0)
        recon = st.recon.get((bukrs, period), [])
        recon_total = sum(i["amountMinor"] for i in recon)
        difference = gl - done
        unexplained = difference - recon_total - genuine
        diff_pct = pct(difference, gl)
        if abs(diff_pct) <= TOLERANCE_PCT:
            status = "BALANCED"
        elif unexplained == 0:
            status = "EXPLAINED"
        else:
            status = "UNEXPLAINED"
        periods.append({"companyCode": bukrs, "period": period, "extractMinor": extract, "rejectedMinor": rejected, "loadedMinor": done,
                        "glMinor": gl, "glMinusLoadedMinor": difference, "differencePct": str(diff_pct), "reconcilingItemsMinor": recon_total,
                        "reconcilingItems": recon, "unexplainedMinor": unexplained, "status": status})
        for k, v in (("extract", extract), ("rejected", rejected), ("loaded", done), ("gl", gl)):
            totals[k] += v
    statuses = Counter(p["status"] for p in periods)
    spend = {"tolerancePct": str(TOLERANCE_PCT), "periods": periods, "byStatus": dict(sorted(statuses.items())),
             "exceptions": [{"period": p["period"], "status": p["status"], "differencePct": p["differencePct"], "glMinusLoadedMinor": p["glMinusLoadedMinor"],
                             "reconcilingItems": [i["reason"] for i in p["reconcilingItems"]]} for p in periods if p["status"] != "BALANCED"],
             "totals": {**{f"{k}Minor": v for k, v in totals.items()}, "differencePct": str(pct(totals["gl"] - totals["loaded"], totals["gl"]))}}
    # open AP vs vendor reconciliation account (ageing at the key date)
    ageing_extract, ageing_loaded = Counter(), Counter()
    for item in st.ap_extract:
        ageing_extract[_bucket(item["due"], st.key_date)] += item["amount"]
    loaded_items = ([(i["vendor"], i["gross"], i["due"]) for i in st.ap_items] if validate_only else (ap_loaded or []))
    for _code, gross, due in loaded_items:
        ageing_loaded[_bucket(due, st.key_date)] += gross
    gl_ap = -sum(v for (b, acc), v in st.ap_gl_balance.items() if b == st.bukrs and acc.startswith("16"))
    ap_rejected = sum(r.get("amountMinor", 0) for r in st.report.rejects if r["object"] == "openAp")
    extract_ap, loaded_ap = sum(ageing_extract.values()), sum(ageing_loaded.values())
    open_ap = {"extractMinor": extract_ap, "loadedMinor": loaded_ap, "glReconciliationAccountMinor": gl_ap, "rejectedMinor": ap_rejected,
               "extractMatchesGl": extract_ap == gl_ap, "loadedPlusRejectedMatchesGl": loaded_ap + ap_rejected == gl_ap,
               "ageingExtract": dict(sorted(ageing_extract.items())), "ageingLoaded": dict(sorted(ageing_loaded.items())),
               "items": {"extract": len(st.ap_extract), "loaded": len(loaded_items)}}
    # open PO value per supplier
    loaded_value = ({v: 0 for v in st.open_value_extract} if open_value is None else open_value)
    if validate_only:
        loaded_value = defaultdict(int)
        for po in st.open_pos.values():
            for l in po["lines"]:
                loaded_value[alpha(po["header"]["LIFNR"])] += max(0, l["net"] - l["history"]["ir_value"])
    rejected_value = defaultdict(int)
    for r in st.report.rejects:
        if r["object"] == "openPoLines":
            rejected_value[alpha(st.ekko.get(r["key"].split("/")[0], {}).get("LIFNR"))] += r.get("amountMinor", 0)
    differences = []
    for vendor in sorted(set(st.open_value_extract) | set(loaded_value)):
        e, l_ = st.open_value_extract.get(vendor, 0), loaded_value.get(vendor, 0)
        if e != l_:
            differences.append({"supplier": vendor, "extractMinor": e, "loadedMinor": l_, "rejectedMinor": rejected_value.get(vendor, 0),
                                "explainedByRejects": e - l_ == rejected_value.get(vendor, 0)})
    open_po = {"suppliers": len(st.open_value_extract), "extractMinor": sum(st.open_value_extract.values()), "loadedMinor": sum(loaded_value.values()),
               "suppliersMatching": len(set(st.open_value_extract) | set(loaded_value)) - len(differences), "differences": differences}
    # contracts: value and validity
    active = [a for a in st.agreements.values() if a["start"] and a["end"] and a["start"] <= st.key_date <= a["end"] and a["start"] <= a["end"]]

    def validity(end: date) -> str:
        months = (end.year - st.key_date.year) * 12 + end.month - st.key_date.month
        return "<=3 months" if months <= 3 else "4-6 months" if months <= 6 else ">6 months"

    loaded_contracts = contracts if contracts is not None else []
    contract_tie = {"activeInExtract": len(active), "loaded": len(loaded_contracts) if not validate_only else len([a for a in active if a["active"]]),
                    "validityExtract": dict(Counter(validity(a["end"]) for a in active)),
                    "validityLoaded": dict(Counter(validity(c.valid_to) for c in loaded_contracts)) if not validate_only else None,
                    "targetValueLoadedMinor": sum(c.target_value_minor for c in loaded_contracts) if not validate_only else None,
                    "expiredUsedForCoverage": sum(1 for a in st.agreements.values() if a["start"] and a["end"] and a["start"] <= a["end"]
                                                  and a["end"] < st.key_date)}
    return {"keyDate": st.key_date.isoformat(), "validateOnly": validate_only, "spend": spend, "openAp": open_ap, "openPo": open_po, "contracts": contract_tie}


# ---------------------------------------------------------------- entry points
def load(tenant_code: str, directory, *, validate_only: bool = False, report_dir=None, when: Optional[datetime] = None) -> dict:
    """Validate (and unless validate_only, load) one extract into a tenant. Returns the summary stored by the dataset pack."""
    started = time.monotonic()
    extract = read_extract(directory)
    st = stage(extract)
    timings = {}
    loader = None
    if not validate_only:
        loader = Loader(tenant_code, st, when)
        for step in ("org", "vendors", "materials", "agreements", "open_pos", "open_ap", "spend"):
            t0 = time.monotonic()
            getattr(loader, step)()
            timings[step] = round(time.monotonic() - t0, 1)
            log.info("erp load %s: %s done in %.1fs", tenant_code, step, timings[step])
        tie = loader.tie_out()
    else:
        tie = tie_out(st)
    rep = st.report
    summary = {
        "tenant": tenant_code, "extract": {k: extract.manifest.get(k) for k in ("extractId", "extractType", "sourceSystem", "client", "keyDate",
                                                                                "historyFrom", "historyTo", "companyCodes")},
        "validateOnly": validate_only,
        "objects": {k: dict(v) for k, v in sorted(rep.counts.items())},
        "rejects": {"count": len(rep.rejects), "byReason": rep.by_reason(), "rows": rep.rejects},
        "warnings": {"counts": dict(sorted(rep.warnings.items())), "samples": rep.warning_samples},
        "audit": loader.audit_actions if loader else {},
        "classification": getattr(st, "classification", None),
        "tieOut": tie,
        "bankVerificationSample": _bank_sample(st),
        "durationSeconds": round(time.monotonic() - started, 1), "stepSeconds": timings,
    }
    if loader:
        summary["duplicates"] = _duplicates(loader)
    if report_dir:
        write_report(summary, Path(report_dir))
    return summary


def _bank_sample(st: Staged) -> list[dict]:
    """§12.4 bank verification sample: 10 % of the loaded bank accounts (at least 10), chosen deterministically, for call-back."""
    with_bank = sorted((c for c, v in st.vendors.items() if v["bank"] and not v["deleted"]),
                       key=lambda c: hashlib.sha256(f"{st.extract.manifest.get('extractId')}|{c}".encode()).hexdigest())
    size = max(10, len(with_bank) // 10)
    return [{"supplier": c, "name": st.vendors[c]["name"], "ifsc": st.vendors[c]["bank"]["ifsc"],
             "account": crypto.mask(st.vendors[c]["bank"]["account"])} for c in sorted(with_bank[:size])]


def _duplicates(loader: Loader) -> list[dict]:
    with loader.tx() as s:
        out = []
        for sup in s.execute(select(Supplier).order_by(Supplier.code)).scalars():
            screening = sup.screening or {}
            if screening.get("source") in ("ERP_INITIAL_LOAD", "ERP_DELTA") and screening.get("duplicates"):
                out.append({"supplier": sup.code, "name": sup.legal_name, "outcome": screening.get("outcome"),
                            "duplicates": screening["duplicates"]})
        return out


def write_report(summary: dict, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / "rejects.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["object", "file", "row", "key", "reason", "detail", "amount"])
        for r in summary["rejects"]["rows"]:
            writer.writerow([r["object"], r["file"], r["row"], r["key"], r["reason"], r["detail"],
                             money(r["amountMinor"]) if r.get("amountMinor") is not None else ""])
    with open(directory / "tieout_spend.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["company_code", "period", "extract", "rejected", "loaded", "gl", "gl_minus_loaded", "difference_pct", "reconciling_items",
                         "unexplained", "status"])
        for p in summary["tieOut"]["spend"]["periods"]:
            writer.writerow([p["companyCode"], p["period"], money(p["extractMinor"]), money(p["rejectedMinor"]), money(p["loadedMinor"]),
                             money(p["glMinor"]), money(p["glMinusLoadedMinor"]), p["differencePct"], money(p["reconcilingItemsMinor"]),
                             money(p["unexplainedMinor"]), p["status"]])
    (directory / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")


def format_report(summary: dict) -> str:
    lines = [f"ERP load {summary['tenant']} - extract {summary['extract']['extractId']} (key date {summary['extract']['keyDate']})"
             + (" - VALIDATE ONLY" if summary["validateOnly"] else "")]
    lines.append(f"{'object':16} {'extract':>8} {'loaded':>8} {'existing':>9} {'rejected':>9} {'skipped':>8}")
    for name, c in summary["objects"].items():
        lines.append(f"{name:16} {c.get('extract', 0):>8} {c.get('loaded', 0):>8} {c.get('existing', 0):>9} {c.get('rejected', 0):>9} {c.get('skipped', 0):>8}")
    lines.append(f"rejects: {summary['rejects']['count']}")
    for obj, reasons in summary["rejects"]["byReason"].items():
        lines.append(f"  {obj}: " + ", ".join(f"{r} {n}" for r, n in reasons.items()))
    if summary["warnings"]["counts"]:
        lines.append("warnings: " + ", ".join(f"{k} {v}" for k, v in summary["warnings"]["counts"].items()))
    spend = summary["tieOut"]["spend"]
    lines.append(f"spend tie-out (±{spend['tolerancePct']} % vs GL): {spend['byStatus']}")
    lines.append(f"{'cc':5} {'period':8} {'extract':>16} {'loaded':>16} {'GL':>16} {'GL-loaded':>13} {'%':>7}  status")
    for p in spend["periods"]:
        lines.append(f"{p['companyCode']:5} {p['period']:8} {money(p['extractMinor']):>16} {money(p['loadedMinor']):>16} {money(p['glMinor']):>16} "
                     f"{money(p['glMinusLoadedMinor']):>13} {p['differencePct']:>7}  {p['status']}"
                     + (f" ({', '.join(i['reason'] for i in p['reconcilingItems'])})" if p["reconcilingItems"] else ""))
    t = spend["totals"]
    lines.append(f"total {money(t['extractMinor']):>22} {money(t['loadedMinor']):>16} {money(t['glMinor']):>16} {t['differencePct']:>21} %")
    ap = summary["tieOut"]["openAp"]
    lines.append(f"open AP: extract {money(ap['extractMinor'])}, loaded {money(ap['loadedMinor'])}, rejected {money(ap['rejectedMinor'])}, "
                 f"GL 160000 {money(ap['glReconciliationAccountMinor'])} -> extract = GL: {ap['extractMatchesGl']}, loaded + rejected = GL: "
                 f"{ap['loadedPlusRejectedMatchesGl']}")
    po = summary["tieOut"]["openPo"]
    lines.append(f"open PO value: extract {money(po['extractMinor'])}, loaded {money(po['loadedMinor'])}; {po['suppliersMatching']} of "
                 f"{po['suppliers']} supplier(s) match; differences explained by rejects: "
                 f"{all(d['explainedByRejects'] for d in po['differences'])}")
    c = summary["tieOut"]["contracts"]
    lines.append(f"contracts: {c['activeInExtract']} active in extract, {c['loaded']} loaded, validity {c['validityExtract']}, "
                 f"{c['expiredUsedForCoverage']} expired used for coverage")
    lines.append(f"duration {summary['durationSeconds']} s {summary.get('stepSeconds') or ''}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Load a client's SAP S/4HANA cutover extract into a PIC tenant (TD §12.4)")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--dir", required=True, help="extract directory with MANIFEST.json")
    parser.add_argument("--validate-only", action="store_true", help="validate and tie out the extract; write nothing to the database")
    parser.add_argument("--report", action="store_true", help="print the load and tie-out report")
    parser.add_argument("--report-dir", default=None, help="write rejects.csv, tieout_spend.csv and summary.json (default data/erp_load_reports/<tenant>)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import app.pic.services  # noqa: F401  (registers the outbox consumers, timers and posting handlers)
    report_dir = args.report_dir or str(BACKEND_DIR / "data" / "erp_load_reports" / args.tenant)
    try:
        summary = load(args.tenant, args.dir, validate_only=args.validate_only, report_dir=report_dir)
    except ExtractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(format_report(summary) if args.report else json.dumps({k: summary[k] for k in ("objects", "audit", "durationSeconds")}, default=str, indent=1))
    print(f"report files: {report_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
