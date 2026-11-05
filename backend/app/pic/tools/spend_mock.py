"""MOCK spend datasets for the demo tenants AXN and KAC (ILLUSTRATIVE SAMPLE, not customer data).

    python -m app.pic.tools.spend_mock --check     # verify the generator's own invariants and, when DATABASE_URL holds the pack, the loaded data
    python -m app.pic.tools.spend_mock --write     # rewrite the counts section of data/erp_mock/KAC_SPEND/README.md from the generator

One module holds the deterministic rules the dataset pack ``spend_ops`` (seed/datasets/spend_ops.py), its tests and the data README share, so a
second run gives the same bytes. Nothing is random: every "random" choice is a SHA-256 of a tag and a number.

  seasonality    monthly spend of a category = base x pattern[month] x (1 + 0.6 % per month since April 2025); the patterns are:
                   AUTO     Jan 1.00 Feb 1.02 Mar 1.14 (year-end push) Apr 0.90 May 0.95 Jun 0.98 Jul 1.00 Aug 0.96 Sep 1.03 Oct 1.10 Nov 1.06 Dec 0.98
                   FESTIVE  as AUTO with Oct 1.25, Nov 1.18, Dec 1.08 (packaging, logistics: the festive-season build)
                   FLAT     1.00 in every month, +/- 2 % (software, professional services)
  foreign lines  24 MOCK suppliers in DE/IT/SE/US/JP/CN/SG/NL on second ERP systems (SAP-EU, SAP-APAC); a line is quantity x unit price in the
                 supplier's currency (EUR, USD, JPY, CNY; the platform stores every currency with two implied decimals) converted at the rate valid on
                 the document date from the finance pack's FX series; before 1 April 2026 the pack adds MOCK weekly rates continuing the same curve for
                 USD, EUR, JPY and CNY (KRW has no rate at all: a deliberate gap, see the defects below)
  tail           60 MOCK small suppliers with 0-2 small lines a month (class C of the Pareto ranking)
  concentration  HEAT-TREATMENT: three suppliers with about 80 % / 13 % / 7 % of the category spend (HHI about 6,600, above the 2,500 limit; one supplier is
                 risk tier HIGH, so the category is a STRATEGIC item) and SPECIAL-COATINGS: two suppliers with 90 % / 10 % of the lines (HHI about 8,200, small
                 spend: a BOTTLENECK item)
  duplicates     four clusters of MOCK suppliers that look like one entity (same PAN and bank; name variants; a typo) and one near-miss that is NOT a
                 duplicate (Plant 1 / Plant 2 Engineering)
  maverick       25 flagged lines for each of the six rules KAC has no cases for (SPLIT_PO, NON_CATALOGUE, OFF_CONTRACT_PRICE, NO_GOODS_RECEIPT,
                 PO_NOT_APPROVED, OVER_INVOICED); hits are created like the service creates them (owner, SLA from the line's date, savings at risk)
  steward queue  free-text lines with a low classifier confidence; the agent's proposal is computed by the real classifier at load time
  credit memos   negative ERP lines (returns, rebates) that net against the invoices of the same supplier and category

Deliberate data-quality defects (every line has invoice_ref MOCKDQ/...; the data-quality report must find each of them):
  DQ1 FX_RATE_MISSING             20 KRW lines (a currency for which the tenant has no rate at all)
  DQ2 DUPLICATE_LINES             6 lines loaded twice
  DQ3 CATEGORY_NOT_IN_TAXONOMY    5 lines with the category FASTNERS (typo)
  DQ4 NON_POSITIVE_INVOICE_LINES  3 lines of value 0
  DQ5 NO_LINEAGE                  40 lines without an order reference (non-PO spend)
  DQ6 AMOUNT_OUTLIER              1 line of Rs 60 crore in March 2025 (a quantity typed with two zeros too many; the tenant limit is Rs 25 crore)
  DQ7 INTERCOMPANY_ADDRESSABLE    2 lines of the intercompany supplier counted as addressable
  DQ8 SUPPLIER_UNKNOWN            2 lines whose supplier id is not in the supplier master
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

from app.pic.config import BACKEND_DIR

OUT_DIR = BACKEND_DIR / "data" / "erp_mock" / "KAC_SPEND"
README = OUT_DIR / "README.md"
TAG = "MOCK sample data (spend_ops)"
FIRST_PERIOD, LAST_PERIOD = "2025-04", "2026-10"
MARK = "MOCK-SP"                       # invoice_ref prefix of every generated line: MOCK-SP/<family>/<tenant>/<n>
SOURCE_SYSTEMS = ("SAP-EU", "SAP-APAC")

AUTO = [1.00, 1.02, 1.14, 0.90, 0.95, 0.98, 1.00, 0.96, 1.03, 1.10, 1.06, 0.98]
FESTIVE = [1.00, 1.02, 1.14, 0.90, 0.95, 0.98, 1.00, 0.96, 1.03, 1.25, 1.18, 1.08]
FLAT = [1.0] * 12
PATTERN = {"PACKAGING": FESTIVE, "LOGISTICS": FESTIVE, "SOFTWARE-LICENCES": FLAT, "PROF-SERVICES": FLAT, "IT-HARDWARE": FLAT}


def unit(*parts) -> float:
    """A repeatable number in [0, 1) from the parts (SHA-256), the only source of 'randomness'."""
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:12], 16) / float(16 ** 12)


def pick(seq, *parts):
    return seq[int(unit(*parts) * len(seq)) % len(seq)]


def periods(first: str = FIRST_PERIOD, last: str = LAST_PERIOD) -> list[str]:
    out, (y, m) = [], (int(first[:4]), int(first[5:]))
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def month_index(period: str) -> int:
    return (int(period[:4]) - int(FIRST_PERIOD[:4])) * 12 + int(period[5:]) - int(FIRST_PERIOD[5:])


def season(category: str, period: str) -> float:
    pattern = PATTERN.get(category, AUTO)
    flat_noise = 1 + (unit("flat", category, period) - 0.5) * 0.04 if pattern is FLAT else 1.0
    return pattern[int(period[5:]) - 1] * (1 + 0.006 * month_index(period)) * flat_noise


def doc_day(period: str, *parts) -> date:
    year, month = int(period[:4]), int(period[5:])
    last = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, 1 + int(unit("day", period, *parts) * min(last, 28)))


# ---------------------------------------------------------------- suppliers
FOREIGN = [   # code, name, country, currency, category, source system, plant, lines per month, unit price range in currency units
    ("MOCKF-DE01", "Rheinwerk Sensorik GmbH", "DE", "EUR", "ELECTRONICS", "SAP-EU", "1100", 14, (4, 90)),
    ("MOCKF-DE02", "Bavaria Power Semiconductors AG", "DE", "EUR", "ELECTRONICS", "SAP-EU", "1200", 12, (8, 140)),
    ("MOCKF-IT01", "Lombardia Fusioni S.p.A.", "IT", "EUR", "FERROUS-CASTINGS", "SAP-EU", "1100", 11, (60, 900)),
    ("MOCKF-DE03", "Stuttgart Werkzeugbau GmbH", "DE", "EUR", "TOOLING", "SAP-EU", "1300", 8, (800, 14000)),
    ("MOCKF-SE01", "Nordic Alloy Trading AB", "SE", "EUR", "RAW-MATERIALS", "SAP-EU", "1200", 12, (900, 3800)),
    ("MOCKF-US01", "Midwest Aluminium Corp", "US", "USD", "RAW-MATERIALS", "SAP-EU", "1100", 13, (1100, 2900)),
    ("MOCKF-US02", "Great Plains Tooling Inc", "US", "USD", "TOOLING", "SAP-EU", "1300", 7, (900, 16000)),
    ("MOCKF-US03", "Silicon Prairie Devices LLC", "US", "USD", "ELECTRONICS", "SAP-EU", "1200", 12, (5, 120)),
    ("MOCKF-US04", "Texas Forge & Machine Inc", "US", "USD", "FORGINGS", "SAP-EU", "1100", 10, (40, 650)),
    ("MOCKF-US05", "Cascade Software Inc", "US", "USD", "SOFTWARE-LICENCES", "SAP-EU", "1100", 6, (1200, 9000)),
    ("MOCKF-JP01", "Nagoya Seimitsu Kogyo KK", "JP", "JPY", "CAPEX-MACHINERY", "SAP-APAC", "1300", 5, (900000, 9000000)),
    ("MOCKF-JP02", "Osaka Precision Dies KK", "JP", "JPY", "TOOLING", "SAP-APAC", "1300", 7, (350000, 4200000)),
    ("MOCKF-JP03", "Yokohama Bearings Co Ltd", "JP", "JPY", "MRO", "SAP-APAC", "1100", 14, (4000, 160000)),
    ("MOCKF-JP04", "Kansai Heat Systems KK", "JP", "JPY", "CAPEX-MACHINERY", "SAP-APAC", "1200", 4, (1500000, 12000000)),
    ("MOCKF-CN01", "Suzhou Metal Components Co Ltd", "CN", "CNY", "FASTENERS", "SAP-APAC", "1100", 15, (1, 22)),
    ("MOCKF-CN02", "Ningbo Rubber & Seals Co Ltd", "CN", "CNY", "RUBBER-SEALS", "SAP-APAC", "1200", 13, (2, 60)),
    ("MOCKF-CN03", "Shenzhen Circuit Works Co Ltd", "CN", "CNY", "ELECTRONICS", "SAP-APAC", "1300", 12, (3, 90)),
    ("MOCKF-CN04", "Dongguan Packaging Co Ltd", "CN", "CNY", "PACKAGING", "SAP-APAC", "1100", 12, (1, 40)),
    ("MOCKF-CN05", "Wuxi Casting Technology Co Ltd", "CN", "CNY", "FERROUS-CASTINGS", "SAP-APAC", "1200", 9, (90, 1300)),
    ("MOCKF-CN06", "Chongqing Hardware Co Ltd", "CN", "CNY", "IT-HARDWARE", "SAP-APAC", "1300", 5, (800, 14000)),
    ("MOCKF-SG01", "Singapore Logistics Pte Ltd", "SG", "USD", "LOGISTICS", "SAP-APAC", "1100", 12, (300, 4200)),
    ("MOCKF-NL01", "Rotterdam Freight BV", "NL", "EUR", "LOGISTICS", "SAP-EU", "1200", 10, (250, 3800)),
    ("MOCKF-DE04", "Munich Engineering Services GmbH", "DE", "EUR", "PROF-SERVICES", "SAP-EU", "1100", 4, (1500, 12000)),
    ("MOCKF-JP05", "Tokyo Process Consulting KK", "JP", "JPY", "PROF-SERVICES", "SAP-APAC", "1100", 3, (400000, 3000000)),
]
HEAT = [("MOCKH-001", "Coimbatore Heat Treaters Pvt Ltd", 78), ("MOCKH-002", "Hosur Thermal Processing Ltd", 15), ("MOCKH-003", "Chennai Case Hardening Works", 7)]
COAT = [("MOCKH-004", "Hosur Powder Coating Works", 90), ("MOCKH-005", "Bidadi Surface Finishers", 10)]     # SPECIAL-COATINGS: HHI 8,200, small spend (a bottleneck item)
CONCENTRATED = {"HEAT-TREATMENT": (HEAT, 40, 240_000, 720_000), "SPECIAL-COATINGS": (COAT, 12, 60_000, 190_000)}   # category -> suppliers, lines a month, amount range (rupees)
# duplicate clusters: (code, name, PAN, bank (ifsc, masked) or None, category)
DUPLICATES = [
    ("MOCKD-101", "Precision Dies and Tools Pvt Ltd", "AAEPD1011A", ("MOCK0000101", "XXXXXXXX4101"), "TOOLING"),
    ("MOCKD-102", "Precision Dies & Tools Private Limited", "AAEPD1011A", ("MOCK0000101", "XXXXXXXX4101"), "TOOLING"),
    ("MOCKD-201", "Hosur Packaging Industries", "AAHPH2022B", None, "PACKAGING"),
    ("MOCKD-202", "Hosur Packaging Industries Ltd", "AAHPH2022C", None, "PACKAGING"),
    ("MOCKD-203", "Hosur Packaging Industry Limited", "AAHPH2022D", None, "PACKAGING"),
    ("MOCKD-301", "Sri Venkatesa Forgings", "AAFPS3033E", None, "FORGINGS"),
    ("MOCKD-302", "Sri Venkatesa Forging Works", "AAFPS3033E", None, "FORGINGS"),
    ("MOCKD-401", "Madras Industrial Gases Pvt Ltd", "AAMPM4044F", None, "MRO-CHEMICALS"),
    ("MOCKD-402", "Madras Industrial Gasses Private Limited", "AAMPM4045G", None, "MRO-CHEMICALS"),
    ("MOCKD-501", "Plant 1 Engineering Services", "AAPPP5051H", None, "FACILITIES"),     # NOT duplicates: different plants
    ("MOCKD-502", "Plant 2 Engineering Services", "AAPPP5052J", None, "FACILITIES"),
]
DUPLICATE_CLUSTERS = [("MOCKD-101", "MOCKD-102"), ("MOCKD-201", "MOCKD-202", "MOCKD-203"), ("MOCKD-301", "MOCKD-302"), ("MOCKD-401", "MOCKD-402")]
TAIL_PLACES = ["Hosur", "Oragadam", "Bidadi", "Sriperumbudur", "Ambattur", "Peenya", "Coimbatore", "Pune", "Chakan", "Manesar", "Rajkot", "Ludhiana"]
TAIL_THINGS = ["Safety Supplies", "Industrial Fasteners Trading", "Tools and Abrasives", "Lubricants Agency", "Packaging Materials", "Housekeeping Services",
               "Calibration Services", "Electricals", "Hardware Mart", "Print and Stationery", "Canteen Provisions", "Welding Consumables"]
TAIL_CATEGORIES = ["MRO", "OFFICE-SAFETY", "MRO-LUBRICANTS", "PROF-SERVICES", "FACILITIES", "MRO-CHEMICALS", "PACKAGING"]
MAVERICK_RULES_NEW = ["SPLIT_PO", "NON_CATALOGUE", "OFF_CONTRACT_PRICE", "NO_GOODS_RECEIPT", "PO_NOT_APPROVED", "OVER_INVOICED"]
FREE_TEXT = [
    "Annual maintenance charges for line 4 as per PO", "Spares for hydraulic press, assorted", "Fabrication work shed extension bay 3", "Calibration services for gauges",
    "Misc consumables for canteen and stores", "Service charges as per quotation", "Packing material assorted sizes", "Repair of forklift hydraulic hose",
    "Consultancy fee for process audit", "Software subscription renewal users", "Transport of rejected lots to supplier", "Replacement of cooling tower fan",
    "Painting and civil touch-up work", "Safety shoes and gloves for shop floor", "Laptop accessories and cables", "Annual fire extinguisher refilling",
    "Die polishing job work", "Generator servicing and diesel top-up", "Training programme for operators", "Rental of scaffolding material",
]


def tail_suppliers(count: int = 60) -> list[dict]:
    out = []
    for i in range(1, count + 1):
        place, thing = pick(TAIL_PLACES, "tp", i), pick(TAIL_THINGS, "tt", i)
        out.append({"code": f"MOCKT-{i:03d}", "name": f"{place} {thing}" + (" Enterprises" if i % 3 == 0 else " Pvt Ltd" if i % 3 == 1 else ""),
                    "category": pick(TAIL_CATEGORIES, "tc", i)})
    return out


# ---------------------------------------------------------------- line amounts (minor units, two implied decimals for every currency)
def foreign_amount(supplier: tuple, period: str, n: int) -> tuple[int, Decimal, Decimal]:
    """(amount_minor, qty, unit price in currency units) of the n-th line of a foreign supplier in a period."""
    code, _, _, currency, category, _, _, _, (low, high) = supplier
    unit_price = Decimal(low) + (Decimal(high) - Decimal(low)) * Decimal(repr(unit("fp", code, period, n)))
    unit_price = unit_price.quantize(Decimal("0.01"))
    qty = Decimal(1 + int(unit("fq", code, period, n) * (9 if low < 100 else 3)))
    amount = (qty * unit_price * Decimal(100)).quantize(Decimal("1"))
    return int(amount * Decimal(repr(season(category, period)))), qty, unit_price


def lines_per_month(supplier: tuple, period: str) -> int:
    base = supplier[7]
    return max(1, round(base * season(supplier[4], period) * (0.85 + 0.3 * unit("n", supplier[0], period))))


def tail_amount(code: str, period: str, n: int) -> int:
    return int((2_000 + 88_000 * unit("ta", code, period, n)) * 100)


def concentrated_lines(category: str, period: str) -> list[tuple[str, int]]:
    """(supplier code, amount_minor) of the lines of a concentrated category in a month: lines x season, split by the suppliers' share of the lines."""
    suppliers, per_month, low, span = CONCENTRATED[category]
    total = int(per_month * season(category, period))
    rows = []
    for n in range(total):
        share = unit("hs", category, period, n)
        cumulative, chosen = 0, suppliers[-1][0]
        for code, _, pct in suppliers:
            cumulative += pct / 100
            if share < cumulative:
                chosen = code
                break
        rows.append((chosen, int((low + span * unit("ha", category, period, n)) * 100)))
    return rows


def heat_lines(period: str) -> list[tuple[str, int]]:
    return concentrated_lines("HEAT-TREATMENT", period)


# ---------------------------------------------------------------- expected totals (README and tests)
def expected_foreign_lines() -> int:
    return sum(lines_per_month(s, p) for s in FOREIGN for p in periods())


def concentrated_shares(category: str = "HEAT-TREATMENT") -> dict:
    totals = {code: 0 for code, _, _ in CONCENTRATED[category][0]}
    for period in periods():
        for code, amount in concentrated_lines(category, period):
            totals[code] += amount
    whole = sum(totals.values())
    return {code: round(v * 100 / whole, 1) for code, v in totals.items()}


def heat_shares() -> dict:
    return concentrated_shares("HEAT-TREATMENT")


def hhi_of_heat() -> int:
    return int(sum(v * v for v in heat_shares().values()))


# ---------------------------------------------------------------- CLI
def check() -> list[str]:
    problems = []
    if len(FOREIGN) != 24 or len({s[0] for s in FOREIGN}) != 24:
        problems.append("24 distinct foreign suppliers expected")
    if {s[3] for s in FOREIGN} != {"EUR", "USD", "JPY", "CNY"}:
        problems.append("the foreign suppliers must use EUR, USD, JPY and CNY")
    if len(periods()) != 19:
        problems.append("19 periods expected (April 2025 to October 2026)")
    if hhi_of_heat() <= 2500:
        problems.append(f"the concentration category must have an HHI above 2500, got {hhi_of_heat()}")
    if any(season(c, p) <= 0 for c in ("PACKAGING", "ELECTRONICS") for p in periods()):
        problems.append("seasonality must stay positive")
    if len({unit("x", i) for i in range(1000)}) != 1000:
        problems.append("unit() must not collide on 1000 inputs")
    cluster_codes = {c for cluster in DUPLICATE_CLUSTERS for c in cluster}
    if not cluster_codes <= {d[0] for d in DUPLICATES}:
        problems.append("duplicate clusters name unknown suppliers")
    return problems


def write_readme_counts() -> None:
    text = README.read_text(encoding="utf-8") if README.exists() else ""
    marker_a, marker_b = "<!-- gen:start -->", "<!-- gen:end -->"
    block = (f"{marker_a}\n| item | value |\n|---|---|\n| periods | {FIRST_PERIOD} to {LAST_PERIOD} ({len(periods())}) |\n"
             f"| foreign lines (formula) | {expected_foreign_lines():,} |\n| HEAT-TREATMENT shares | {heat_shares()} |\n| HEAT-TREATMENT HHI | {hhi_of_heat():,} |\n{marker_b}")
    if marker_a in text and marker_b in text:
        text = text[:text.index(marker_a)] + block + text[text.index(marker_b) + len(marker_b):]
        README.write_text(text, encoding="utf-8")
    else:
        print(block)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Verify or document the MOCK spend datasets (data/erp_mock/KAC_SPEND).")
    parser.add_argument("--check", action="store_true", help="verify the generator's invariants (and the loaded data when DATABASE_URL holds the pack)")
    parser.add_argument("--write", action="store_true", help="rewrite the counts block of the README from the generator")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.write:
        write_readme_counts()
    problems = check()
    if args.check:
        print(json.dumps({"problems": problems, "foreignLines": expected_foreign_lines(), "heatShares": heat_shares(), "heatHhi": hhi_of_heat(),
                          "periods": len(periods())}))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
