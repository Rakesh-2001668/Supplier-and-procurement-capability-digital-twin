"""D11 reference data: HSN/SAC with GST rates, plant holiday calendars, UNSPSC mapping, FX rates (TD §4, BP §7).

Every tenant gets the same verified reference files from ``backend/data/reference`` (each file's header names its official
source and as-of date):

- ``hsn_gst_rates.csv``: the CBIC GST rate schedule (9/2025, 10/2025, 14/2025-CT(Rate) for goods; 11/2017-CT(Rate) as
  amended by 15/2025 for services) for the HSN/SAC codes procurement uses. There is no HSN/tax table yet, so the master is
  loaded as the effective-dated rule set ``HSN-GST`` (P14: a new schedule is a new version); ``services.gst`` reads it and
  the invoice match raises a TAX exception when invoice and PO agree on a rate the schedule does not allow for the code.
- ``holidays_2026_2027.csv``: state public-holiday lists (gazette / G.O.); the PUBLIC rows for each plant's state are added
  to the plant's factory calendar through the ADM-01 calendar service (union, nothing removed). States or years without
  an official list are reported as "needs supply".
- ``unspsc_category_map.csv``: UNSPSC segment/family (class where verified) per taxonomy category. taxonomy_node has no
  attribute column, so the mapping is the rule set ``TAXONOMY-UNSPSC`` keyed by category code (schema need reported).
- ``fx_reference_rates.csv``: FBIL reference rates read on the RBI homepage, loaded through the FX administration service.

Everything runs as the tenant administrator and is audited. Idempotent per tenant (dataset_load) and check-then-insert per
object, so a re-run after new tenants or plants appear only adds what is missing. Industry tenants created by later packs
get the reference data when this pack is applied again (``--only reference_data``), because ``*`` means the tenants that
exist when the pack runs.
"""
import csv
import io
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.pic.config import BACKEND_DIR
from app.pic.db import system_tx
from app.pic.models import (
    AppUser, CatalogueItem, Currency, FxRate, Material, Plant, PoLine, RuleSet, TaxonomyNode, Tenant,
)
from app.pic.platform import audit
from app.pic.seed.axion import Scenario

KEY = "reference-data"
VERSION = "1"
TITLE = "D11 reference data: HSN/SAC with GST rates, plant holiday calendars, UNSPSC mapping, FX rates"
TENANTS = ('*',)
CREATES_TENANT = False
READY = True

DATA_DIR = BACKEND_DIR / "data" / "reference"
HSN_RULE, HSN_VERSION, HSN_FROM = "HSN-GST", "CBIC-2025.09", date(2025, 9, 22)
UNSPSC_RULE, UNSPSC_VERSION, UNSPSC_FROM = "TAXONOMY-UNSPSC", "UNGM-2026.10", date(2026, 4, 1)
FX_SOURCE = "FBIL ref rate via RBI, 13:00 IST"
CALENDAR_SCOPE = "PUBLIC"
STATE_NAMES = {"IN": "Government of India (DoPT)", "33": "Tamil Nadu", "29": "Karnataka", "27": "Maharashtra", "36": "Telangana",
               "24": "Gujarat", "07": "Delhi", "06": "Haryana"}
YEARS = (2026, 2027)
# Taxonomy codes used by the templates that share (part of) another category's UNSPSC mapping: code -> (category, family or None).
ALIASES = {"IC-TRANSFER": ("INTERCOMPANY", None), "OFFICE-SUPPLIES": ("OFFICE-SAFETY", "44120000")}


# ---------------------------------------------------------------- reference files
def read_reference(name: str, directory: Path = DATA_DIR) -> tuple[list[str], list[dict]]:
    """Rows of a reference CSV plus its '#' header comment lines (source and as-of date)."""
    text = (directory / name).read_text(encoding="utf-8")
    header = [line[1:].strip() for line in text.splitlines() if line.startswith("#")]
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    return header, list(csv.DictReader(io.StringIO(body)))


def hsn_master_body() -> dict:
    header, rows = read_reference("hsn_gst_rates.csv")
    entries = [{"spec": r["code_spec"], "prefixes": r["prefixes"].split(), "excludes": r["excludes"].split(), "type": r["type"],
                "description": r["description"], "rate": r["gst_rate"], "ref": r["schedule_ref"], "notification": r["notification"],
                "effectiveFrom": r["effective_from"], "hint": r["category_hint"]} for r in rows]
    notifications = sorted({r["notification"] for r in rows})
    return {"source": "CBIC Tax Information Portal (taxinformation.cbic.gov.in), official notification texts", "asOf": "2026-10-28",
            "effectiveFrom": HSN_FROM.isoformat(), "notifications": notifications, "rateBasis": "total GST (2 x CGST = IGST), percent",
            "validation": {"minPrefix": 4}, "file": "data/reference/hsn_gst_rates.csv", "header": header, "entries": entries}


def unspsc_body() -> dict:
    header, rows = read_reference("unspsc_category_map.csv")
    nodes = defaultdict(list)
    for r in rows:
        if not r["segment"]:
            nodes[r["category"]]  # INTERCOMPANY: explicitly no UNSPSC code
            continue
        nodes[r["category"]].append({k: v for k, v in (
            ("segment", r["segment"]), ("segmentTitle", r["segment_title"]), ("family", r["family"] or None),
            ("familyTitle", r["family_title"] or None), ("class", r["class"] or None), ("classTitle", r["class_title"] or None))})
    for code, (same_as, family) in ALIASES.items():
        nodes[code] = [n for n in nodes[same_as] if family is None or n["family"] == family]
    return {"source": "UN Global Marketplace UNSPSC browser (www.ungm.org/Public/UNSPSC)", "asOf": "2026-10-28",
            "unspscVersion": "not shown by UNGM (browser as of 2026-10-28)", "licensedCodeSet": False,
            "file": "data/reference/unspsc_category_map.csv", "header": header, "nodes": dict(nodes)}


def holiday_lists() -> dict[str, dict[int, list[tuple[date, str, str]]]]:
    _, rows = read_reference("holidays_2026_2027.csv")
    out: dict = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["scope"] == CALENDAR_SCOPE:
            out[r["state_code"]][int(r["year"])].append((date.fromisoformat(r["date"]), r["name"], r["source_ref"]))
    return out


def fx_rows() -> list[dict]:
    return read_reference("fx_reference_rates.csv")[1]


# ---------------------------------------------------------------- loaders (inside a tenant-admin transaction)
def _rule_version(s, tenant_id, key: str, version: str, effective_from: date, body: dict, description: str, summary: dict) -> bool:
    if s.execute(select(RuleSet.id).where(RuleSet.key == key, RuleSet.version == version)).first():
        return False
    p = s.info["principal"]
    rule = RuleSet(tenant_id=tenant_id, key=key, version=version, effective_from=effective_from, body=body, description=description,
                   created_by=p.user_id)
    s.add(rule)
    s.flush()
    audit.record(s, "RULE_SET", rule.id, "VERSION_CREATED", object_ref=f"{key}@{version}",
                 after={**summary, "effectiveFrom": effective_from.isoformat(), "source": body["source"], "asOf": body["asOf"]},
                 reason="D11 reference data load")
    return True


def _load_hsn(s, tenant_id, notes: list, counts: dict) -> None:
    from app.pic.services import gst
    body = hsn_master_body()
    created = _rule_version(s, tenant_id, HSN_RULE, HSN_VERSION, HSN_FROM, body,
                            "HSN/SAC master with GST rates (CBIC schedules from 22.09.2025); invoice match GST check (D11)",
                            {"entries": len(body["entries"]), "notifications": body["notifications"]})
    counts["hsnEntries"] = len(body["entries"])
    counts["hsnHeadings"] = len({p for e in body["entries"] for p in e["prefixes"]})
    notes.append(f"HSN-GST@{HSN_VERSION}: {len(body['entries'])} CBIC entries ({', '.join(body['notifications'])})"
                 + ("" if created else " already present"))
    # The tenant's own HSN usage against the schedule: unknown codes and rates the schedule does not allow.
    used = defaultdict(set)
    for model in (Material, CatalogueItem, PoLine):
        for code, rate in s.execute(select(model.hsn_code, model.gst_rate).where(model.hsn_code.is_not(None)).distinct()):
            used[code].add(Decimal(rate))
    unknown, mismatched, ok = [], [], 0
    for code in sorted(used):
        found = gst.lookup(s, code)
        if found["matchedDigits"] < 4:
            unknown.append(code)
            continue
        bad = sorted(r for r in used[code] if r not in found["rates"])
        if bad:
            mismatched.append(f"{code} at {'/'.join(str(r.normalize()) for r in bad)}% (schedule {'/'.join(str(r.normalize()) for r in found['rates'])}%)")
        else:
            ok += 1
    counts["hsnCodesInUse"], counts["hsnCodesVerified"] = len(used), ok
    if unknown:
        notes.append(f"HSN/SAC codes in use but not in the master (not validated): {', '.join(unknown)}")
    if mismatched:
        notes.append(f"HSN/SAC codes used at a rate the CBIC schedule does not allow: {'; '.join(mismatched)}")
    counts["hsnUnknown"], counts["hsnMismatched"] = len(unknown), len(mismatched)


def _load_unspsc(s, tenant_id, notes: list, counts: dict) -> None:
    body = unspsc_body()
    created = _rule_version(s, tenant_id, UNSPSC_RULE, UNSPSC_VERSION, UNSPSC_FROM, body,
                            "UNSPSC segment/family per taxonomy category (UNGM browser); taxonomy_node has no attribute column (D11)",
                            {"categories": len(body["nodes"])})
    codes = sorted(s.execute(select(TaxonomyNode.code).where(TaxonomyNode.level == 3)).scalars())
    mapped = [c for c in codes if c in body["nodes"]]
    unmapped = [c for c in codes if c not in body["nodes"]]
    counts["unspscCategories"], counts["taxonomyMapped"], counts["taxonomyUnmapped"] = len(body["nodes"]), len(mapped), len(unmapped)
    notes.append(f"TAXONOMY-UNSPSC@{UNSPSC_VERSION}: {len(mapped)}/{len(codes)} taxonomy categories mapped" + ("" if created else " (already present)")
                 + (f"; no verified UNSPSC mapping for {', '.join(unmapped)}" if unmapped else ""))


def _load_fx(s, notes: list, counts: dict) -> None:
    from app.pic.services import admin
    known = set(s.execute(select(Currency.code).where(Currency.active.is_(True))).scalars())
    added, skipped = [], []
    for r in fx_rows():
        frm, to, day = r["from_ccy"], r["to_ccy"], date.fromisoformat(r["date"])
        rate = (Decimal(r["rate"]) / Decimal(r["units"])).quantize(Decimal("0.00000001"))
        if frm not in known or to not in known:
            skipped.append(f"{frm}/{to} (currency not active)")
            continue
        if s.execute(select(FxRate.id).where(FxRate.from_ccy == frm, FxRate.to_ccy == to, FxRate.valid_from == day)).first():
            continue
        admin.add_fx_rate(s, frm, to, rate, day, FX_SOURCE)
        added.append(f"{frm}/{to} {rate}")
    counts["fxRates"] = len(added)
    days = sorted({r["date"] for r in fx_rows()})
    notes.append(f"FX (FBIL via RBI, {', '.join(days)}): {', '.join(added) or 'already loaded'}"
                 + (f"; skipped {', '.join(skipped)}" if skipped else "")
                 + "; earlier and month-end rates need supply (FBIL archive not readable)")


def _load_holidays(s, notes: list, counts: dict) -> None:
    from app.pic.services import admin
    lists = holiday_lists()
    added_total, missing = 0, []
    for plant in s.execute(select(Plant).order_by(Plant.code)).scalars().all():
        state = lists.get(plant.state_code, {})
        loaded = []
        for year in YEARS:
            rows = state.get(year)
            if not rows:
                missing.append(f"{plant.code} ({STATE_NAMES.get(plant.state_code, 'state ' + plant.state_code)}) {year}")
                continue
            sources = sorted({src for _, _, src in rows})
            added = admin.add_plant_holidays(s, plant.code, [d for d, _, _ in rows], f"{year} public holidays: {'; '.join(sources)}"[:500])
            added_total += len(added)
            loaded.append(f"{year} +{len(added)}")
        if loaded:
            notes.append(f"Plant {plant.code} ({STATE_NAMES.get(plant.state_code, plant.state_code)}): calendar {', '.join(loaded)} "
                         f"({len(plant.holidays or [])} holidays)")
    counts["holidaysAdded"] = added_total
    if missing:
        notes.append("Holiday list needs supply (no official list loaded): " + ", ".join(missing))
    counts["calendarsMissing"] = len(missing)


# ---------------------------------------------------------------- pack entry point
def _admin_email(tenant_id) -> str | None:
    from app.pic.db import tenant_tx
    with tenant_tx(tenant_id) as s:
        for user in s.execute(select(AppUser).where(AppUser.supplier_id.is_(None)).order_by(AppUser.email)).scalars():
            if "TENANT_ADMIN" in (user.roles or []) and user.active:
                return user.email
    return None


def apply(tenant_code: str, password: str) -> dict:
    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == tenant_code)).scalar_one()
    email = _admin_email(tenant_id)
    if email is None:
        return {"notes": [f"{tenant_code}: no active tenant administrator; reference data not loaded"], "counts": {}}
    notes, counts = [], {}
    sc = Scenario(tenant_id, tenant_code)
    # Reference data is loaded at the real load time (wall clock), not at a business date of a story.
    with sc.act(email, datetime.now(timezone.utc)) as s:
        _load_hsn(s, tenant_id, notes, counts)
        _load_unspsc(s, tenant_id, notes, counts)
        _load_fx(s, notes, counts)
        _load_holidays(s, notes, counts)
    return {"notes": notes, "counts": counts}
