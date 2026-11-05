"""MOCK strategic-sourcing datasets for the demo tenants KAC and AXN (ILLUSTRATIVE SAMPLE, not market data, not a supplier's quotation).

    python -m app.pic.tools.sourcing_mock --write     # regenerate the data files in data/erp_mock/KAC_SOURCING and MANIFEST.json
    python -m app.pic.tools.sourcing_mock --check     # verify the files against MANIFEST.json and, with DATABASE_URL set, the database against the plan

One module holds the deterministic rules that the dataset pack ``sourcing_ops`` (seed/datasets/sourcing_ops*.py), its tests and the data README share, so
a second run gives the same bytes. Nothing is random: every "random" choice is a SHA-256 of a key.

  index series   monthly MOCK values 1 April 2025 - 1 October 2026 (19 points) of ten commodity indices (index_value, source IMPORT). Level:
                     value(m) = base x (1 + 0.035 sin(2 pi m / 11 + phase) + drift m) x (1 + noise),   m = months from April 2025
                 noise is +-0.4 % from SHA-256(index|month). The series is smooth and bounded and is NOT market data.
  should-cost    ten commodity models (castings, forgings, fasteners, bearings, wiring, plastics, rubber, packaging, MRO, services): material (quantity x
                 yield loss x rate x index factor), conversion (minutes x rate), tooling, packaging, logistics (% of material + conversion), then a margin.
                 The inputs of an event are scaled so that the should-cost sits at 93 % of the item's baseline price (the pack does the scaling, so
                 the should-cost delta in the comparison is meaningful for every item).
  event plan     40 KAC events (Apr 2025 - Oct 2026) and 6 AXN events (Aug - Sep 2027): type, category, outcome ("flavour"), dates, bidder count, baseline
                 method. The bids of an event follow ``bid_terms``: price = baseline x (1 + spread), spread from SHA-256(event|supplier) between
                 -11 % and +9 %, freight / packaging as a share of the price, payment terms 30-90 days, lead time 7-45 days.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import sys
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Optional

from app.pic.config import BACKEND_DIR

OUT_DIR = BACKEND_DIR / "data" / "erp_mock" / "KAC_SOURCING"
TAG = "MOCK sample data (sourcing_ops)"
SERIES_FROM, SERIES_TO = date(2025, 4, 1), date(2026, 10, 1)
SOURCE_REF = "MOCK series (sourcing_ops)"


def unit(*parts) -> float:
    """A repeatable number in [0, 1) from the parts (SHA-256), the only source of 'randomness'."""
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:12], 16) / float(16 ** 12)


def between(low: float, high: float, *parts) -> float:
    return low + (high - low) * unit(*parts)


# ---------------------------------------------------------------- indices
# code -> (base value, phase, drift per month, unit)
INDICES = {
    "CAST_IRON_SCRAP": (Decimal("100.00"), 0.3, 0.0021, "index points"),
    "MS_BILLET": (Decimal("100.00"), 1.1, 0.0016, "index points"),
    "WIRE_ROD": (Decimal("100.00"), 2.0, 0.0012, "index points"),
    "BEARING_STEEL": (Decimal("100.00"), 2.7, 0.0018, "index points"),
    "COPPER_LME": (Decimal("100.00"), 3.4, 0.0030, "index points"),
    "PP_GRADE": (Decimal("100.00"), 4.0, -0.0010, "index points"),
    "NATURAL_RUBBER": (Decimal("100.00"), 4.9, 0.0008, "index points"),
    "KRAFT_PAPER": (Decimal("100.00"), 5.6, 0.0006, "index points"),
    "MRO_PPI": (Decimal("100.00"), 0.8, 0.0015, "index points"),
    "WAGE_INDEX": (Decimal("100.00"), 1.6, 0.0035, "index points"),
}


def month_starts() -> list[date]:
    out, day = [], SERIES_FROM
    while day <= SERIES_TO:
        out.append(day)
        day = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
    return out


def index_value(code: str, day: date) -> Decimal:
    base, phase, drift, _ = INDICES[code]
    m = (day.year - SERIES_FROM.year) * 12 + day.month - SERIES_FROM.month
    noise = (unit("index", code, day.isoformat()) - 0.5) * 0.008
    raw = 1 + 0.035 * math.sin(2 * math.pi * m / 11 + phase) + drift * m
    return (base * Decimal(repr(raw * (1 + noise)))).quantize(Decimal("0.0001"), ROUND_HALF_UP)


def index_series() -> list[tuple[str, date, Decimal, str]]:
    return [(code, day, index_value(code, day), INDICES[code][3]) for code in INDICES for day in month_starts()]


# ---------------------------------------------------------------- should-cost models
# commodity -> (category of the demo items, index, title, material rate label, defaults)
def _spec(index_code: str, material: str, conversion: str, tooling: str = "Tooling and fixtures", packaging: str = "Packaging") -> dict:
    return {"unit": "EA",
            "inputs": [{"code": "qty", "label": material + " quantity per unit", "unit": "kg"}, {"code": "rate", "label": material + " rate", "unit": "INR/kg"},
                       {"code": "minutes", "label": conversion + " time", "unit": "min"}, {"code": "minute_rate", "label": conversion + " rate", "unit": "INR/min"},
                       {"code": "tooling", "label": tooling + " per unit", "unit": "INR"}, {"code": "packaging", "label": packaging + " per unit", "unit": "INR"},
                       {"code": "margin", "label": "Overhead and profit", "unit": "%"}],
            "components": [
                {"code": "MATERIAL", "label": material, "type": "QTY_RATE", "qty": "qty", "rate": "rate", "yieldLossPct": "5",
                 "index": {"code": index_code, "baseDate": SERIES_FROM.isoformat()}},
                {"code": "CONVERSION", "label": conversion, "type": "TIME_RATE", "minutes": "minutes", "rate": "minute_rate"},
                {"code": "TOOLING", "label": tooling, "type": "FIXED", "amount": "tooling"},
                {"code": "PACKAGING", "label": packaging, "type": "FIXED", "amount": "packaging"},
                {"code": "LOGISTICS", "label": "Inbound logistics", "type": "PCT_OF", "of": ["MATERIAL", "CONVERSION"], "pct": "2"}],
            "marginPct": "margin"}


COMMODITIES = [
    # code, commodity, title, category used by the events, index, material, conversion, default inputs (qty, rate, minutes, minute_rate, tooling, packaging, margin)
    ("SC-CASTING", "castings", "Grey / SG iron casting", "FERROUS-CASTINGS", "CAST_IRON_SCRAP", "Melt metal", "Fettling and machining",
     (12, 48, 6, 14, 6, 5, 14)),
    ("SC-FORGING", "forgings", "Hot-forged steel component", "FORGINGS", "MS_BILLET", "Steel billet", "Forging and heat treatment",
     (7.5, 74, 4, 22, 9, 4, 13)),
    ("SC-FASTENER", "fasteners", "Cold-headed fastener", "FASTENERS", "WIRE_ROD", "Wire rod", "Heading, threading and plating",
     (0.09, 88, 0.12, 9, 0.2, 0.1, 15)),
    ("SC-BEARING", "bearings", "Rolling bearing", "MRO", "BEARING_STEEL", "Bearing steel", "Grinding and assembly",
     (0.35, 140, 3, 18, 2, 3, 17)),
    ("SC-WIRING", "wiring", "Wiring harness / cable", "ELECTRONICS", "COPPER_LME", "Copper conductor", "Cutting, crimping and assembly",
     (1.4, 760, 8, 8, 3, 6, 16)),
    ("SC-PLASTIC", "plastics", "Injection-moulded plastic part", "ELECTRONICS", "PP_GRADE", "Polymer granules", "Moulding cycle",
     (0.18, 118, 1.1, 16, 4, 1.5, 15)),
    ("SC-RUBBER", "rubber", "Moulded rubber seal", "RUBBER-SEALS", "NATURAL_RUBBER", "Compound", "Moulding and deflashing",
     (0.12, 190, 0.9, 12, 2.5, 0.8, 16)),
    ("SC-PACKAGING", "packaging", "Corrugated / returnable packaging", "PACKAGING", "KRAFT_PAPER", "Kraft board", "Conversion and printing",
     (1.8, 62, 1.5, 6, 1, 0, 12)),
    ("SC-MRO", "MRO", "MRO consumable / spare", "MRO-LUBRICANTS", "MRO_PPI", "Base material", "Blending and filling",
     (4, 95, 2, 7, 0.5, 4, 14)),
    ("SC-SERVICES", "services", "Contracted service (per activity unit)", "PROF-SERVICES", "WAGE_INDEX", "Skilled labour (hours)", "Supervision and tools",
     (96, 310, 200, 14, 400, 150, 12)),
]


def model_for(row: tuple) -> dict:
    code, commodity, title, category, index_code, material, conversion, defaults = row
    names = ("qty", "rate", "minutes", "minute_rate", "tooling", "packaging", "margin")
    return {"code": code, "commodity": commodity, "title": title, "category": category, "indexCode": index_code, "spec": _spec(index_code, material, conversion),
            "defaultInputs": {n: str(v) for n, v in zip(names, defaults)}}


def models() -> list[dict]:
    return [model_for(r) for r in COMMODITIES]


def model_by_category(category: str) -> Optional[dict]:
    return next((m for m in models() if m["category"] == category), None)


def scale_inputs(inputs: dict, factor: Decimal) -> dict:
    """All monetary and quantity inputs of a model are linear in the unit cost except the margin: scaling them scales the unit cost."""
    out = dict(inputs)
    for key in ("qty", "minutes", "tooling", "packaging"):
        out[key] = str((Decimal(str(inputs[key])) * factor).quantize(Decimal("0.0001")))
    return out


# ---------------------------------------------------------------- bids
def bid_terms(event_key: str, supplier_code: str, baseline_minor: int, *, index: int = 0, low_bias: float = 0.0) -> dict:
    """The terms of one supplier's bid on an item with a baseline price. ``low_bias`` shifts the spread (an aggressive bidder)."""
    spread = between(-0.11, 0.09, "spread", event_key, supplier_code) + low_bias
    price = (Decimal(baseline_minor) * Decimal(repr(1 + spread)) / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return {"unit_price": str(price), "freight": str((price * Decimal(repr(between(0.008, 0.03, "freight", event_key, supplier_code)))).quantize(Decimal("0.01"))),
            "packaging": str((price * Decimal(repr(between(0.004, 0.015, "pack", event_key, supplier_code)))).quantize(Decimal("0.01"))),
            "payment_terms_days": int(30 + 15 * int(unit("terms", event_key, supplier_code) * 5)),
            "lead_time_days": int(7 + int(unit("lead", event_key, supplier_code) * 38)), "spread": spread}


def twin_terms(supplier_code: str, category: str) -> dict:
    """MOCK twin snapshot of a supplier for a category (the Supplier Capability Twin is not connected)."""
    return {"evidence_level": ("E1", "E2", "E3", "E3", "E4")[int(unit("evidence", supplier_code, category) * 5)],
            "trust": Decimal(repr(between(0.62, 0.97, "trust", supplier_code, category))).quantize(Decimal("0.001")),
            "late": Decimal(repr(between(0.03, 0.22, "late", supplier_code, category))).quantize(Decimal("0.001")),
            "ppm": Decimal(repr(between(120, 2400, "ppm", supplier_code, category))).quantize(Decimal("0.1")),
            "lead_time_days": int(7 + unit("tl", supplier_code, category) * 35)}


# ---------------------------------------------------------------- the event plan
# key, type, category, outcome, created, bidders, baseline method, extras
# outcome codes are documented in the README (data/erp_mock/KAC_SOURCING).
KAC_PLAN_ROWS = [
    ("K01", "RFQ", "FERROUS-CASTINGS", "AWARD_LOWEST", date(2025, 4, 14), 4, "LAST_PRICE", {}),
    ("K02", "RFQ", "FORGINGS", "AWARD_SPLIT", date(2025, 5, 12), 5, "BUDGET", {"big": True}),
    ("K03", "RFQ", "FASTENERS", "AWARD_LOWEST", date(2025, 6, 9), 4, "LAST_PRICE", {"clarifications": 2, "lateBid": True, "uninvited": True, "withdraw": True}),
    ("K04", "REVERSE_AUCTION", "RUBBER-SEALS", "AWARD_AUCTION", date(2025, 7, 7), 4, "LAST_PRICE", {}),
    ("K05", "RFQ", "MRO", "AWARD_NON_LOWEST", date(2025, 8, 4), 5, "MARKET_INDEX", {"commodity": "bearings"}),
    ("K06", "RFQ", "ELECTRONICS", "AWARD_CAPACITY", date(2025, 9, 1), 4, "SHOULD_COST", {"commodity": "wiring", "big": True}),
    ("K07", "RFQ", "PACKAGING", "AWARD_LOT", date(2025, 10, 6), 4, "LAST_PRICE", {"lines": 3}),
    ("K08", "RFQ", "MACHINING", "AWARD_ROUNDS", date(2025, 11, 3), 5, "LAST_PRICE", {}),
    ("K09", "RFP", "PROF-SERVICES", "AWARD_BEST_VALUE", date(2025, 12, 1), 4, "BUDGET", {}),
    ("K10", "RFQ", "FORGINGS", "AWARD_DISQ", date(2026, 1, 12), 5, "LAST_PRICE", {}),
    ("K11", "RFQ", "RAW-MATERIALS", "AWARD_IMPORT", date(2026, 4, 13), 5, "LAST_PRICE", {"import": True}),
    ("K12", "REVERSE_AUCTION", "MRO-LUBRICANTS", "AWARD_AUCTION", date(2026, 5, 4), 4, "LAST_PRICE", {"softClose": True}),
    ("K13", "RFQ", "TOOLING", "AWARD_SPLIT", date(2026, 5, 18), 4, "LAST_PRICE", {"activate": True, "big": True}),
    ("K14", "RFP", "LOGISTICS", "AWARD_LOWEST", date(2026, 6, 1), 4, "LAST_PRICE", {"activate": True}),
    ("K15", "RFQ", "MACHINING", "AWARD_LOWEST", date(2026, 6, 15), 4, "LAST_PRICE", {"activate": True, "twoPerson": True}),
    ("K16", "RFQ", "FASTENERS", "AWARD_LOWEST", date(2026, 7, 6), 4, "LAST_PRICE", {"activate": True, "cloneOf": "K03"}),
    ("K17", "RFQ", "FORGINGS", "PENDING", date(2026, 8, 3), 4, "LAST_PRICE", {"big": True}),
    ("K18", "RFQ", "ELECTRONICS", "PENDING_NON_LOWEST", date(2026, 8, 17), 4, "LAST_PRICE", {"commodity": "plastics", "big": True}),
    ("K19", "REVERSE_AUCTION", "PACKAGING", "PENDING", date(2026, 9, 7), 4, "LAST_PRICE", {"big": True}),
    ("K20", "RFI", "MRO-CHEMICALS", "EVAL_RFI", date(2025, 9, 15), 4, "LAST_PRICE", {}),
    ("K21", "RFI", "TOOLING-SERVICES", "EVAL_RFI", date(2026, 3, 2), 3, "BUDGET", {}),
    ("K22", "RFQ", "RUBBER-SEALS", "EVAL_PARTIAL", date(2026, 9, 24), 5, "WEIGHTED_AVG", {}),
    ("K23", "RFP", "IT-SERVICES", "EVAL_PARTIAL", date(2026, 9, 21), 3, "BUDGET", {}),
    ("K24", "RFQ", "FERROUS-CASTINGS", "CLOSED_WAIT", date(2026, 10, 5), 4, "LAST_PRICE", {"twoPerson": True, "earlyOpen": True, "openers": 0}),
    ("K25", "RFQ", "OFFICE-SAFETY", "CLOSED_WAIT", date(2026, 10, 12), 3, "LAST_PRICE", {"twoPerson": True, "openers": 1}),
    ("K26", "RFQ", "MRO", "OPEN", date(2026, 10, 26), 3, "LAST_PRICE", {"bids": 2}),
    ("K27", "RFQ", "FASTENERS", "OPEN", date(2026, 10, 27), 3, "WEIGHTED_AVG", {"bids": 1, "clarifications": 1, "earlyView": True}),
    ("K28", "RFP", "FACILITIES", "OPEN", date(2026, 10, 28), 3, "BUDGET", {"bids": 0}),
    ("K29", "RFQ", "PACKAGING", "PUBLISHED", date(2026, 10, 29), 3, "LAST_PRICE", {"clarifications": 1}),
    ("K30", "RFQ", "LOGISTICS", "PUBLISHED", date(2026, 10, 30), 3, "LAST_PRICE", {}),
    ("K31", "RFQ", "ELECTRONICS", "DRAFT", date(2026, 10, 30), 3, "SHOULD_COST", {"commodity": "wiring"}),
    ("K32", "RFI", "MACHINING", "DRAFT", date(2026, 10, 31), 3, "LAST_PRICE", {}),
    ("K33", "RFQ", "FORGINGS", "DRAFT", date(2026, 10, 31), 3, "LAST_PRICE", {"lines": 3}),
    ("K34", "RFQ", "MRO", "CANCEL_DRAFT", date(2025, 6, 23), 3, "LAST_PRICE", {}),
    ("K35", "RFQ", "FERROUS-CASTINGS", "CANCEL_BIDS", date(2025, 10, 20), 4, "LAST_PRICE", {}),
    ("K36", "RFQ", "ELECTRONICS", "CANCEL_PENDING", date(2026, 2, 23), 4, "LAST_PRICE", {}),
    ("K37", "RFQ", "RUBBER-SEALS", "CANCEL_OPEN", date(2026, 7, 20), 3, "LAST_PRICE", {}),
    ("K38", "RFQ", "ELECTRONICS", "AWARD_ROUNDS", date(2026, 2, 9), 4, "LAST_PRICE", {}),
    ("K39", "RFP", "LOGISTICS", "AWARD_LOWEST", date(2026, 3, 16), 3, "LAST_PRICE", {"bids": 2}),
    ("K40", "RFQ", "MRO-LUBRICANTS", "AWARD_LOWEST", date(2026, 3, 30), 6, "LAST_PRICE", {"template": True}),
]
AXN_PLAN_ROWS = [
    ("A01", "RFI", "FASTENERS", "EVAL_RFI", date(2027, 8, 2), 3, "BUDGET", {}),
    ("A02", "RFP", "ALU-DIECAST", "AWARD_BEST_VALUE", date(2027, 8, 9), 4, "BUDGET", {}),
    ("A03", "RFQ", "ALU-DIECAST", "AWARD_ROUNDS", date(2027, 8, 16), 4, "BUDGET", {}),
    ("A04", "RFQ", "ALU-DIECAST", "AWARD_LOT", date(2027, 8, 23), 4, "BUDGET", {"lines": 3}),
    ("A05", "RFQ", "FASTENERS", "CANCEL_BIDS", date(2027, 9, 1), 3, "BUDGET", {}),
    ("A06", "RFQ", "ALU-DIECAST", "CLOSED_WAIT", date(2027, 9, 8), 3, "BUDGET", {"twoPerson": True, "openers": 1}),
]
STATES = {"AWARD": "AWARDED", "PENDING": "AWARD_PENDING", "EVAL": "UNDER_EVALUATION", "CLOSED_WAIT": "CLOSED", "OPEN": "OPEN", "PUBLISHED": "PUBLISHED", "DRAFT": "DRAFT",
          "CANCEL": "CANCELLED"}


def expected_state(outcome: str) -> str:
    if outcome.startswith("PENDING"):
        return "AWARD_PENDING"
    return STATES[outcome.split("_")[0]] if outcome.split("_")[0] in STATES else STATES[outcome]


def _row(r: tuple) -> dict:
    key, type_, category, outcome, created, bidders, baseline, extra = r
    return {"key": key, "type": type_, "category": category, "outcome": outcome, "state": expected_state(outcome), "created": created.isoformat(), "bidders": bidders,
            "baselineMethod": baseline, **extra}


def kac_plan() -> list[dict]:
    return [_row(r) for r in KAC_PLAN_ROWS]


def axn_plan() -> list[dict]:
    return [_row(r) for r in AXN_PLAN_ROWS]


def plan_summary(rows: list[dict]) -> dict:
    out = {"events": len(rows), "byType": {}, "byState": {}}
    for r in rows:
        out["byType"][r["type"]] = out["byType"].get(r["type"], 0) + 1
        out["byState"][r["state"]] = out["byState"].get(r["state"], 0) + 1
    return out


# ---------------------------------------------------------------- files and manifest
def files() -> dict[str, str]:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["index_code", "as_of", "value", "unit", "source"])
    for code, day, value, unit_ in index_series():
        writer.writerow([code, day.isoformat(), str(value), unit_, SOURCE_REF])
    return {
        "index_series.csv": buf.getvalue(),
        "should_cost_models.json": json.dumps(models(), indent=2, sort_keys=True) + "\n",
        "event_plan_kac.json": json.dumps({"label": TAG, "summary": plan_summary(kac_plan()), "events": kac_plan()}, indent=2, sort_keys=True) + "\n",
        "event_plan_axn.json": json.dumps({"label": TAG, "summary": plan_summary(axn_plan()), "events": axn_plan()}, indent=2, sort_keys=True) + "\n",
    }


def manifest_for(data: dict[str, str]) -> dict:
    return {"label": TAG, "fictional": True, "client": "Kaveri Auto Components Pvt Ltd", "currency": "INR",
            "files": {name: {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "bytes": len(text.encode("utf-8"))} for name, text in sorted(data.items())},
            "kacSummary": plan_summary(kac_plan()), "axnSummary": plan_summary(axn_plan())}


def write_files(out_dir: Path = OUT_DIR) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    data = files()
    for name, text in data.items():
        (out_dir / name).write_text(text, encoding="utf-8", newline="")
    manifest = manifest_for(data)
    (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="")
    return manifest


def verify_files(out_dir: Path = OUT_DIR) -> list[str]:
    """Problems between the committed files, MANIFEST.json and what the generator builds now (empty = identical)."""
    path = out_dir / "MANIFEST.json"
    if not path.exists():
        return [f"{path} does not exist"]
    manifest = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    current = {name: hashlib.sha256(text.encode("utf-8")).hexdigest() for name, text in files().items()}
    for name, meta in manifest.get("files", {}).items():
        file = out_dir / name
        if not file.exists():
            problems.append(f"{name} is listed in the manifest but missing")
            continue
        if hashlib.sha256(file.read_bytes()).hexdigest() != meta["sha256"]:
            problems.append(f"{name} differs from its manifest hash")
        if current.get(name) != meta["sha256"]:
            problems.append(f"{name}: the generator now builds different bytes (re-run --write)")
    return problems


def verify_database(tenant_code: str = "KAC") -> list[str]:
    """When DATABASE_URL holds the pack: every planned event exists in its planned state."""
    from sqlalchemy import select

    from app.pic.db import system_tx, tenant_tx
    from app.pic.models import SourcingEvent, Tenant

    rows = kac_plan() if tenant_code == "KAC" else axn_plan()
    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == tenant_code)).scalar_one_or_none()
    if tenant_id is None:
        return [f"tenant {tenant_code} does not exist"]
    with tenant_tx(tenant_id) as s:
        found = {e.title.split(" ")[1]: e.status for e in s.execute(select(SourcingEvent).where(SourcingEvent.title.like("MOCK %"))).scalars()}
    if not found:
        return []        # the pack is not loaded in this database
    return [f"{r['key']}: expected {r['state']}, found {found.get(r['key'], 'missing')}" for r in rows if found.get(r["key"]) != r["state"]]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate or verify the MOCK sourcing datasets (data/erp_mock/KAC_SOURCING).")
    parser.add_argument("--write", action="store_true", help="rebuild the data files and MANIFEST.json")
    parser.add_argument("--check", action="store_true", help="verify the files against MANIFEST.json and, when DATABASE_URL holds the pack, the events against the plan")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not (args.write or args.check):
        parser.print_help()
        return 0
    if args.write:
        manifest = write_files(args.out)
        print(f"wrote {len(manifest['files'])} file(s) to {args.out}: " + ", ".join(sorted(manifest["files"])))
        return 0
    problems = verify_files(args.out)
    if os.environ.get("DATABASE_URL"):
        import app.pic.services  # noqa: F401
        for code in ("KAC", "AXN"):
            try:
                problems += verify_database(code)
            except Exception as exc:  # noqa: BLE001 - the database may not hold the pack
                print(f"database comparison for {code} skipped: {type(exc).__name__}: {exc}")
    for p in problems:
        print("MISMATCH:", p)
    print("OK" if not problems else "CHECK FAILED")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
