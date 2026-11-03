"""MOCK inventory master data and opening stock for the demo tenants AXN and KAC (ILLUSTRATIVE SAMPLE, not the client's numbers).

    python -m app.pic.tools.inventory_mock [--out data/erp_mock/KAC_INVENTORY]

One module holds the deterministic rules that turn what the tenant already has (purchase history, standard prices, lead times, lot sizes)
into plausible planning data, so that the dataset pack ``inventory_master`` (fills the master data), the opening-stock generator below (writes
``data/erp_mock/KAC_INVENTORY/opening_stock.csv``) and the tests all use the same formulas. Nothing is random: every "random" choice is a
SHA-256 of the material number and plant, so the same inputs always give the same output and a re-run changes nothing.

Formulas (documented in data/erp_mock/KAC_INVENTORY/README.md). Quantities are rounded UP to whole units; a month is 30 days.

    usage         units per month, first source that exists
                  HISTORY   quantity bought in the last 12 months before the key date / 12 (else the last 24 months / 24): KAC reads the
                            cutover extract (EKPO x EKKO), other tenants their own purchase orders (po_line x purchase_order)
                  ON_HAND   no history, stock on hand: on hand / 1.5 (the opening stock is assumed to be 45 days of cover)
                  LOT       typical lot per month: fixed lot, else minimum lot, else pack size, else INR 50,000 / standard price
                  a floor of 1 unit a month applies to every source (a slow mover still gets a stock-keeping minimum)
    safety stock  only where the material has none (0 or empty): SAFETY_DAYS[category] x daily usage (average over the material's plants);
                  without usable usage 20 % of the typical lot
    reorder point daily usage of the plant x lead time days + safety stock;  lead time = planned delivery days + goods-receipt processing days
                  (7 days when the material has neither)
    max stock     reorder point + lot size;  lot size = fixed lot, else minimum lot, else pack size, else 30 days of usage (at least 1)
    standard      only where the material has none: the price of its latest purchase order line, else its latest contract price, else its latest
    price         info-record price (the tenant's own data; nothing is invented when there is none)
    opening       cover = 20 + 40 x u days (u from the hash of material|plant), quantity = max(ceil(daily x cover), ceil(1.05 x reorder point)), the
    stock         second term capped at INR 25 lakh of stock per line (a die set of INR 35 lakh with a SAP safety stock of 34 pieces is not stocked 37 times);
    stock         deliberate exceptions are picked by hash: stock-outs (quantity 0), below safety stock, between safety stock and reorder point,
                  lots expiring in about 30 / 60 / 90 days, quality-hold and blocked lots, one consignment line
"""
from __future__ import annotations

import argparse
import csv
import functools
import hashlib
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Optional

from app.pic.config import BACKEND_DIR

OUT_DIR = BACKEND_DIR / "data" / "erp_mock" / "KAC_INVENTORY"
FILE_NAME = "opening_stock.csv"
COLUMNS = ["material", "plant", "storage_location", "stock_type", "batch", "qty", "uom", "expiry", "valuation"]
KEY_DATE = date(2026, 10, 31)            # the cutover key date of the KAC extract (opening stock is as of this day)
TAG = "MOCK sample data (inventory_master)"

MONTH_DAYS = Decimal(30)
FALLBACK_MONTHLY_VALUE_MINOR = 5_000_000        # INR 50,000 a month when nothing else is known
USAGE_FLOOR = Decimal(1)
DEFAULT_LEAD_DAYS = 7
DEFAULT_SAFETY_DAYS = 7
FLOOR_VALUE_CAP_MINOR = 250_000_000            # INR 25 lakh: the stock kept up to reorder point + 5 % is capped at this value per line
# Days of average usage kept as safety stock, by category (material.category): direct material that stops the line gets fewer days than
# low-value consumables that are cheap to hold.
SAFETY_DAYS = {
    "ALU-DIECAST": 7, "FERROUS-CASTINGS": 7, "FORGINGS": 7, "MACHINING": 7, "IC-TRANSFER": 7,
    "RAW-MATERIALS": 10, "RUBBER-SEALS": 10, "ELECTRONICS": 10, "PACKAGING": 10,
    "FASTENERS": 14, "MRO": 14, "MRO-LUBRICANTS": 14, "MRO-CHEMICALS": 14, "TOOLING": 14, "OFFICE-SAFETY": 14,
}


# ---------------------------------------------------------------- deterministic choices
def unit(*parts) -> float:
    """A repeatable number in [0, 1) from the parts (SHA-256), the only source of 'randomness'."""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(digest[:12], 16) / float(16 ** 12)


def ceil_qty(value) -> Decimal:
    return Decimal(math.ceil(Decimal(value)))


@dataclass
class Facts:
    """What the plan needs to know about one stock material (from the database or from the staged extract)."""
    number: str
    uom: str
    category: str
    group: str
    std_minor: Optional[int]
    safety: Decimal
    lead_days: int
    lot_qty: Optional[Decimal]
    min_lot: Optional[Decimal]
    pack_size: Optional[Decimal]
    plants: list
    quality_managed: bool = False
    description: str = ""


@dataclass
class Plan:
    safety: Decimal                                  # final material safety stock (existing, else filled)
    safety_filled: bool
    usage: dict = field(default_factory=dict)        # plant -> (units per month, basis)
    reorder: dict = field(default_factory=dict)      # plant -> reorder point
    maximum: dict = field(default_factory=dict)      # plant -> max stock
    lot: Decimal = Decimal(1)


def typical_lot(f: Facts) -> Decimal:
    for candidate in (f.lot_qty, f.min_lot, f.pack_size):
        if candidate and candidate > 0:
            return Decimal(candidate)
    price = Decimal(f.std_minor or 0)
    return max(Decimal(1), ceil_qty(Decimal(FALLBACK_MONTHLY_VALUE_MINOR) / price)) if price > 0 else Decimal(10)


def usage_for(f: Facts, history: Optional[Decimal], on_hand: Optional[Decimal]) -> tuple[Decimal, str]:
    """(units per month, basis) of one material at one plant."""
    if history is not None and history > 0:
        return max(history, USAGE_FLOOR), "HISTORY"
    if on_hand is not None and on_hand > 0:
        return max(on_hand / Decimal("1.5"), USAGE_FLOOR), "ON_HAND"
    return max(typical_lot(f), USAGE_FLOOR), "LOT"


def plan_material(f: Facts, history: dict, on_hand: Optional[dict] = None) -> Plan:
    """The planning data of one material: usage per plant, final safety stock, reorder point and maximum stock per plant.
    ``history``: plant -> units per month bought (missing: none); ``on_hand``: plant -> quantity on hand (only for tenants without history)."""
    usage = {p: usage_for(f, history.get(p), (on_hand or {}).get(p)) for p in f.plants}
    lot = typical_lot(f)
    existing = Decimal(f.safety or 0)
    if existing > 0:
        safety, filled = existing, False
    else:
        measured = [u for u, basis in usage.values() if basis != "LOT"]
        if measured:
            daily = sum(measured, Decimal(0)) / len(measured) / MONTH_DAYS
            safety = ceil_qty(daily * SAFETY_DAYS.get(f.category, DEFAULT_SAFETY_DAYS))
        else:
            safety = ceil_qty(lot * Decimal("0.2"))
        safety, filled = max(safety, Decimal(1)), True
    lead = Decimal(f.lead_days or DEFAULT_LEAD_DAYS)
    plan = Plan(safety=safety, safety_filled=filled, usage=usage, lot=lot)
    for plant, (monthly, _) in usage.items():
        daily = monthly / MONTH_DAYS
        plan.reorder[plant] = ceil_qty(daily * lead + safety)
        size = f.lot_qty if f.lot_qty and f.lot_qty > 0 else f.min_lot if f.min_lot and f.min_lot > 0 else f.pack_size if f.pack_size and f.pack_size > 0 else None
        plan.maximum[plant] = plan.reorder[plant] + (Decimal(size) if size else max(Decimal(1), ceil_qty(monthly)))
    return plan


# ---------------------------------------------------------------- batch / expiry flags
def flag_attributes(category: str, group: str, description: str = "") -> Optional[dict]:
    """Material attributes for batch / expiry management, by what the material is: chemicals, lubricants and rubber compounds age; steel,
    aluminium and polymer lots are traced by batch (IATF 16949); adhesive tapes and labels have a shelf life. None: no flag."""
    text = (description or "").lower()
    if category == "MRO-CHEMICALS":
        return {"batchManaged": True, "expiryManaged": True, "minShelfLifeDays": 90}
    if category == "MRO-LUBRICANTS":
        return {"batchManaged": True, "expiryManaged": True, "minShelfLifeDays": 180}
    if category == "RAW-MATERIALS":
        if group == "RM-NRUB":
            return {"batchManaged": True, "expiryManaged": True, "minShelfLifeDays": 60}
        return {"batchManaged": True}
    if category == "PACKAGING" and re.search(r"\b(tape|label)\b", text):
        return {"batchManaged": True, "expiryManaged": True, "minShelfLifeDays": 90}
    return None


# ---------------------------------------------------------------- KAC: facts and history from the cutover extract
@functools.lru_cache(maxsize=2)
def _history_cached(directory: str) -> tuple:
    return _history(Path(directory))


def kac_purchase_history(extract_dir=None) -> tuple[dict, set]:
    """Cached per directory (the extract is read once per process)."""
    from app.pic.tools import erp_mock
    history, open_po = _history_cached(str(extract_dir or erp_mock.OUT_DIR))
    return dict(history), set(open_po)


def _history(extract_dir) -> tuple[dict, set]:
    """(history, open_po) of tenant KAC from its cutover extract: {(material number, plant): units per month bought} (last 12 months before the key
    date, else the last 24) and the numbers of materials with a purchase-order line that is not yet delivered in full."""
    from app.pic.tools import erp_load

    extract = erp_load.read_extract(extract_dir)
    headers = {r["EBELN"]: r for r in extract.rows("EKKO")}
    last12, last24, open_po = defaultdict(Decimal), defaultdict(Decimal), set()
    for line in extract.rows("EKPO"):
        number = erp_load.alpha(line.get("MATNR"))
        if not number or line.get("LOEKZ"):
            continue
        if line.get("ELIKZ") != "X":
            open_po.add(number)
        header = headers.get(line["EBELN"])
        qty = erp_load.dec(line.get("MENGE"))
        if header is None or not qty or qty <= 0:
            continue
        ordered = erp_load.day(header.get("BEDAT"))
        key = (number, line.get("WERKS"))
        if ordered and KEY_DATE - timedelta(days=365) < ordered <= KEY_DATE:
            last12[key] += qty
        if ordered and KEY_DATE - timedelta(days=730) < ordered <= KEY_DATE:
            last24[key] += qty
    history = {key: (last12[key] / 12) if last12.get(key) else (last24[key] / 24) for key in set(last12) | set(last24)}
    return history, open_po


def kac_facts(extract_dir=None) -> tuple[dict, dict, dict]:
    """(facts, history, exclusions) of tenant KAC from its SAP cutover extract, the materials the loader accepts (so the ones the database holds):
    facts {number: Facts}, history {(number, plant): units per month}, exclusions {'openPo': set of numbers, 'inventoryOps': set of numbers}."""
    from app.pic.tools import erp_load, erp_mock

    extract = erp_load.read_extract(extract_dir or erp_mock.OUT_DIR)
    st = erp_load.stage(extract, KEY_DATE)
    facts = {}
    for number, m in st.materials.items():
        if m["type"] != "STOCK":
            continue
        facts[number] = Facts(number=number, uom=m["uom"], category=m["category"], group=m["group"][:30], std_minor=m["std"], safety=m["safety"] or Decimal(0),
                              lead_days=int(m["pdt"] or 0) + int(m["grt"] or 0), lot_qty=m["lot_qty"], min_lot=m["min_lot"], pack_size=None,
                              plants=sorted(m["plants"]), quality_managed=bool(m["qm"]), description=m["description"])
    history, open_po = kac_purchase_history(extract_dir)
    # the 20 materials the inventory_ops pack opens at plant 1100 (first 20 stock materials by number planned there, one of them in two batches)
    ops = sorted(n for n in facts if "1100" in facts[n].plants)
    return facts, history, {"openPo": open_po, "inventoryOps": set(ops[:20])}


def kac_flags(facts: dict, exclusions: dict) -> dict:
    """{number: attributes} the pack sets on KAC materials: not on a material with an open purchase order line (the receipt in flight has no batch)
    or with batch-less opening stock (SAP does not convert a material that has stock to batch management either)."""
    out = {}
    for number, f in facts.items():
        flags = flag_attributes(f.category, f.group, f.description)
        if flags and number not in exclusions["openPo"] and number not in exclusions["inventoryOps"]:
            out[number] = flags
    return out


# ---------------------------------------------------------------- opening stock rows
def _money(value_minor: int) -> str:
    return f"{value_minor // 100}.{value_minor % 100:02d}"


def opening_rows(facts: dict, history: dict, flags: dict, exclusions: dict) -> tuple[list, dict]:
    """(rows, info): the opening-stock lines of every KAC stock material and plant, in material and plant order, and the facts the README quotes."""
    plans = {n: plan_material(f, {p: history[(n, p)] for p in f.plants if (n, p) in history}) for n, f in facts.items()}
    pairs = [(n, p) for n in sorted(facts) for p in facts[n].plants if not (p == "1100" and n in exclusions["inventoryOps"])]
    plain = [(n, p) for n, p in pairs if n not in flags]
    measured = [(n, p) for n, p in plain if plans[n].usage[p][1] == "HISTORY" and plans[n].usage[p][0] >= 5]

    def ranked(pool, tag, take, ok=lambda n, p: True):
        chosen = [x for x in sorted(pool, key=lambda x: unit(tag, *x)) if ok(*x)]
        return chosen[:take]

    used: set = set()
    kinds: dict = {}
    for tag, take, ok in (("stockout", 3, lambda n, p: True),
                          ("below_safety", 12, lambda n, p: plans[n].safety >= 4),
                          ("below_reorder", 8, lambda n, p: plans[n].reorder[p] - plans[n].safety >= 4)):
        for pair in [x for x in ranked(measured, tag, len(measured), ok) if x not in used][:take]:
            kinds[pair] = tag
            used.add(pair)
    quality = [x for x in ranked(plain, "quality", len(plain)) if x not in used and facts[x[0]].quality_managed][:3]
    blocked = [x for x in ranked(plain, "blocked", len(plain)) if x not in used and x not in quality][:3]
    consign = [x for x in ranked(measured, "consignment", len(measured)) if x not in used and x not in quality and x not in blocked][:1]
    expiry_materials = sorted({n for n, _ in pairs if flags.get(n, {}).get("expiryManaged")})
    soon = {}      # material -> (expiry of its first batch, bucket): one batch has one expiry date, whichever plant holds it
    for bucket, (low, high) in (("30", (21, 27)), ("60", (44, 58)), ("90", (72, 88))):
        for number in [n for n in sorted(expiry_materials, key=lambda n: unit("expiring" + bucket, n)) if n not in soon][:2]:
            soon[number] = (KEY_DATE + timedelta(days=low + int(unit("expiring-days", number) * (high - low))), bucket)

    rows, counts = [], defaultdict(int)

    def add(number, plant, stock_type, batch, qty, expiry=None):
        f = facts[number]
        value = int((Decimal(f.std_minor or 0) * Decimal(qty)).to_integral_value(rounding=ROUND_HALF_UP))
        rows.append({"material": number, "plant": plant, "storage_location": "0001", "stock_type": stock_type, "batch": batch, "qty": f"{Decimal(qty):f}",
                     "uom": f.uom, "expiry": expiry.isoformat() if expiry else "", "valuation": _money(value)})

    for number, plant in pairs:
        f, plan = facts[number], plans[number]
        monthly = plan.usage[plant][0]
        daily = monthly / MONTH_DAYS
        reorder = plan.reorder[plant]
        pair = (number, plant)
        kind = kinds.get(pair)
        cover = 20 + 40 * unit("cover", number, plant)
        floor = ceil_qty(Decimal("1.05") * reorder)
        if floor > 1 and floor * Decimal(f.std_minor or 0) > FLOOR_VALUE_CAP_MINOR:
            floor = max(Decimal(1), Decimal(FLOOR_VALUE_CAP_MINOR // max(int(f.std_minor or 1), 1)))      # die sets: not 37 pieces of INR 35 lakh each
            counts["floorCapped"] += 1
        qty = max(ceil_qty(daily * Decimal(str(round(cover, 4)))), floor, Decimal(1))
        if kind == "stockout":
            add(number, plant, "UNRESTRICTED", "", 0)
            counts["stockOut"] += 1
            continue
        if kind == "below_safety":
            qty = max(Decimal(1), (plan.safety / 2).to_integral_value(rounding="ROUND_FLOOR"))
            counts["belowSafety"] += 1
        elif kind == "below_reorder":
            qty = plan.safety + ceil_qty((reorder - plan.safety) / 2)
            counts["belowReorder"] += 1
        flagged = flags.get(number)
        if flagged and flagged.get("expiryManaged"):
            first = (qty * Decimal("0.6")).to_integral_value(rounding="ROUND_CEILING")
            far = KEY_DATE + timedelta(days=200 + int(unit("expiry", number) * 400))
            add(number, plant, "UNRESTRICTED", "L2609A", first, soon[number][0] if number in soon else far)
            add(number, plant, "UNRESTRICTED", "L2610B", max(qty - first, Decimal(1)), far + timedelta(days=30))
            counts["expiryManagedLines"] += 2
            if number in soon:
                counts["expiringLines" + soon[number][1]] += 1
        elif flagged:
            add(number, plant, "UNRESTRICTED", "L2610A", qty)
        else:
            add(number, plant, "UNRESTRICTED", "", qty)
        if pair in quality:
            add(number, plant, "QUALITY", "", max(Decimal(1), ceil_qty(daily * 5)))
            counts["qualityHold"] += 1
        if pair in blocked:
            add(number, plant, "BLOCKED", "", max(Decimal(1), ceil_qty(daily * 3)))
            counts["blocked"] += 1
        if pair in consign:
            add(number, plant, "CONSIGNMENT", "", max(Decimal(1), ceil_qty(daily * 20)))
            counts["consignment"] += 1
    info = {"materials": len({r["material"] for r in rows}), "pairs": len(pairs), "rows": len(rows), "plans": plans, **dict(counts)}
    return rows, info


def write_csv(rows: list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def generate(out_dir: Path = OUT_DIR, extract_dir=None) -> dict:
    """Write opening_stock.csv (and MANIFEST.json with its SHA-256 and row count) from the KAC cutover extract."""
    facts, history, exclusions = kac_facts(extract_dir)
    flags = kac_flags(facts, exclusions)
    rows, info = opening_rows(facts, history, flags, exclusions)
    out_dir = Path(out_dir)
    path = out_dir / FILE_NAME
    write_csv(rows, path)
    summary = {k: v for k, v in info.items() if k != "plans"}
    manifest = {"client": "Kaveri Auto Components Pvt Ltd", "fictional": True, "label": TAG, "asOf": KEY_DATE.isoformat(), "currency": "INR",
                "file": FILE_NAME, "rows": len(rows), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "summary": summary,
                "flaggedMaterials": len(flags)}
    (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate the MOCK opening-stock file of tenant KAC from its cutover extract.")
    parser.add_argument("--out", default=str(OUT_DIR))
    args = parser.parse_args(argv)
    manifest = generate(Path(args.out))
    print(f"{manifest['rows']} opening-stock lines -> {Path(args.out) / FILE_NAME}  {manifest['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
