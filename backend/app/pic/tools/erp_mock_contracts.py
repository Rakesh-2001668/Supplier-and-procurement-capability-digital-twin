"""Mock contract-repository extract of the fictional prospect Kaveri Auto Components Pvt Ltd (tenant KAC).

    python -m app.pic.tools.erp_mock_contracts [--out data/erp_mock/KAC_CLM] [--seed 20261101]

The SAP extract (``erp_mock``) carries the 40 outline agreements of SAP. A real client's other contracts live in a contract repository,
a shared drive or a legal team's register, not in SAP. This generator writes what that register export looks like in the layout
docs/PIC_ERP_Extract_Spec.md section 10 asks for (CSV files, MANIFEST.json with row counts and SHA-256, same hand-over rules), so the
contract loader (``app.pic.tools.contract_load``) can be shown end to end before the client sends its own register. A real export in the
same layout drops into the same loader unchanged.

ILLUSTRATIVE SAMPLE: the portfolio is FICTIONAL and generated from a fixed seed (same seed, identical files). Vendors, materials, plants,
payment terms and prices are taken from the SAP mock extract (``data/erp_mock/KAC``), so the two agree. Clause wording comes from the
illustrative clause library (``seed/clause_library.py``, not legal advice) through the same drafting function PIC uses
(``services.contract._library``); some clauses carry the library's own pre-approved fallback wording, a few carry non-standard
(risky) wording. Dates are relative to the cutover of the SAP mock (load on 1 November 2026).

The portfolio (60 contracts):
  14 master agreements   with 20 call-off contracts (6 scheduling agreements, 8 quantity contracts, 6 value contracts)
   8 rate cards, 8 statements of work, 10 NDAs
  statuses   43 ACTIVE, 9 EXPIRING (inside the 120-day renewal notice window: 18, 27, 52, 78 (master and its two call-offs), 88, 104 and
             117 days to go; one more ACTIVE at 128 days), 3 EXPIRED, 1 TERMINATED (for cause), 2 IN_NEGOTIATION (one with three supplier
             redlines), 1 OUT_FOR_SIGNATURE, 1 DRAFT
  rebate agreements with tiers, price revisions and an amendment history on some contracts, obligations and milestones (a mix of on
  time, late and overdue), signed contracts with document reference and signers.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import io
import json
import random
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from app.pic.config import BACKEND_DIR

SEED = 20261101
OUT_DIR = BACKEND_DIR / "data" / "erp_mock" / "KAC_CLM"
SAP_DIR = BACKEND_DIR / "data" / "erp_mock" / "KAC"
LOAD_DATE = date(2026, 11, 1)
BUKRS = "1000"
EXTRACT_ID = "KAC-CLM-20261101-INIT"
EXCLUDED_VENDORS = {"100198", "100211", "200202", "200203", "200301", "200302", "200303", "200304", "200305"}   # the SAP mock's data-quality cases
BAD_MATERIALS = {"29999999", "41999999", "41000196", "41000197", "41000198", "41000199", "41000200"}
STATE_JURISDICTION = {"33": "IN-TN", "29": "IN-KA", "27": "IN-MH", "24": "IN-GJ", "06": "IN-HR", "03": "IN"}
CATEGORY_LABEL = {
    "ALU-DIECAST": "Aluminium die castings", "FERROUS-CASTINGS": "Ferrous castings", "FORGINGS": "Forgings", "MACHINING": "Machined parts",
    "RAW-MATERIALS": "Raw materials", "FASTENERS": "Fasteners", "RUBBER-SEALS": "Rubber parts and seals", "ELECTRONICS": "Electrical and electronic parts",
    "PACKAGING": "Packaging", "LOGISTICS": "Freight and logistics", "IT-SERVICES": "IT services", "FACILITIES": "Facility services",
    "MRO": "MRO supplies and services", "PROF-SERVICES": "Professional services", "TOOLING-SERVICES": "Tooling services", "TOOLING": "Tooling",
    "IT-HARDWARE": "IT hardware", "CAPEX-MACHINERY": "Capital machinery", "SOFTWARE-LICENCES": "Software licences"}
INDEX_BY_CATEGORY = {"ALU-DIECAST": "LME_AL", "FERROUS-CASTINGS": "STEEL_HRC", "FORGINGS": "STEEL_BAR", "MACHINING": "STEEL_BAR", "ELECTRONICS": "COPPER_LME"}
BUYER_SIGNERS = ["Anand Krishnaswamy, Chief Procurement Officer", "S. Balasubramanian, Head of Procurement", "Venkatesh Iyer, Contract Manager"]
SIGNATORY_FIRST = ["R.", "S.", "K.", "M.", "V.", "P.", "A.", "N.", "G.", "T."]
SIGNATORY_LAST = ["Subramanian", "Ramesh", "Kulkarni", "Naidu", "Iyengar", "Patel", "Shetty", "Menon", "Gowda", "Rajan"]

# services: (description, plant, uom, qty range, unit price range in rupees)
SERVICE_LINES = {
    "LOGISTICS": [("Full truck load Hosur to Oragadam, 32 ft MXL", "1100", "EA", (260, 900), (21000, 26000)),
                  ("Full truck load Bidadi to Hosur, 20 ft", "1300", "EA", (120, 480), (14500, 19000)),
                  ("Container haulage Chennai port to Oragadam, 40 ft", "1200", "EA", (60, 240), (31000, 42000)),
                  ("Part load Hosur to Pune, per tonne", "1100", "TON", (400, 1500), (3100, 4200))],
    "IT-SERVICES": [("Senior consultant, day rate", "1100", "DAY", (120, 300), (14500, 19500)), ("Developer, day rate", "1100", "DAY", (400, 900), (7200, 9800)),
                    ("Support engineer L2, day rate", "1100", "DAY", (240, 480), (4800, 6500))],
    "FACILITIES": [("Housekeeping, skilled person per month", "1100", "MON", (180, 420), (21500, 24800)),
                   ("Canteen operations per month, Oragadam", "1200", "MON", (12, 12), (365000, 410000)),
                   ("Security guard post per month", "1300", "MON", (36, 96), (28500, 33500))],
    "MRO": [("Preventive maintenance visit, air compressors", "1100", "EA", (24, 60), (11500, 16500)),
            ("Breakdown call-out, electrical", "1200", "EA", (40, 140), (4200, 6800))],
    "PROF-SERVICES": [("Senior auditor, day rate", "1100", "DAY", (60, 140), (11500, 16500)), ("Associate, day rate", "1100", "DAY", (120, 300), (4800, 7200))],
    "TOOLING-SERVICES": [("Die refurbishment, HPDC die up to 800 t", "1100", "EA", (14, 40), (185000, 265000)),
                         ("Die trial and correction, per shift", "1200", "EA", (40, 120), (24500, 34500))],
    "IT-HARDWARE": [("Laptop, i5 16 GB 512 GB, with 3-year onsite warranty", "1100", "EA", (60, 180), (62000, 71000)),
                    ("Network switch 24-port managed", "1200", "EA", (8, 24), (38000, 52000))],
    "CAPEX-MACHINERY": [("HPDC machine 1250 t: installation and commissioning", "1200", "EA", (1, 1), (4200000, 5200000))],
    "SOFTWARE-LICENCES": [("Design software named-user licence per year", "1100", "EA", (20, 60), (145000, 185000))],
}
SOW_MILESTONES = {
    "IT-SERVICES": ["Blueprint and interface specification signed off", "Build and unit test complete", "User acceptance test passed", "Go-live and hypercare handover"],
    "FACILITIES": ["Site survey and drawings approved", "Civil and electrical works complete", "Handover with completion certificate"],
    "PROF-SERVICES": ["Fieldwork complete", "Draft report issued", "Final report accepted"],
    "TOOLING-SERVICES": ["First batch of dies received", "Second batch of dies received", "Programme closure report"],
    "IT-HARDWARE": ["Delivery of first 50% of devices", "Delivery and imaging of all devices", "Asset register handed over"],
    "CAPEX-MACHINERY": ["Foundation ready and machine delivered", "Installation complete", "Trial run and acceptance"],
    "LOGISTICS": ["Move plan approved", "Inventory transferred", "Old warehouse handed back"],
}
# Non-standard (risky) wording by clause code, used on a few contracts; the library's own fallbacks are the FALLBACK wording.
RISKY_TEXT = {
    "PAYMENT": "Payment within 90 days from the date of acceptance of the goods; no interest is payable on a delay.",
    "LIABILITY": "The supplier's liability is limited to the price of the defective goods; the buyer's liability is not limited.",
    "TERMINATION": "The buyer may not terminate this contract before the end of its term except for a material breach by the supplier.",
    "IP": "All improvements to drawings and tooling made by the supplier belong to the supplier, which licenses them to the buyer for the term only.",
    "INDEMNITY": "The buyer indemnifies the supplier against all third-party claims arising from the use of the goods, including claims caused by defects.",
    "WARRANTY": "Warranty is limited to three months from delivery; all other warranties are excluded.",
    "AUDIT_RIGHTS": "The buyer has no right to audit the supplier's premises, records or subcontractors.",
    "FORCE_MAJEURE": "Force majeure includes rises in raw-material prices and labour disputes at the supplier's plants, and has no time limit.",
    "LIQUIDATED_DAMAGES": "No liquidated damages apply to late delivery.",
    "SUBCONTRACTING": "The supplier may subcontract any part of the work to anyone without notice to the buyer.",
}


def _money(minor: int) -> str:
    return f"{minor // 100}.{minor % 100:02d}"


def _eom(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year, month = d.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _read(name: str) -> list[dict]:
    with open(SAP_DIR / f"{name}.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class Sap:
    """What the portfolio needs from the SAP mock extract: eligible vendors, their categories, state and terms, and their items."""

    def __init__(self) -> None:
        from app.pic.services.master_changes import gstin_check_char
        category = {r["MATKL"]: r["PIC_CATEGORY"] for r in _read("PIC_MAP_MATKL")}
        terms = {r["ZTERM"]: int(r["ZTAG1"]) for r in _read("T052")}
        vendor_terms = {r["LIFNR"]: terms.get(r["ZTERM"], 30) for r in _read("LFB1")}
        materials = {r["MATNR"]: r for r in _read("MARA")}
        self.vendors: dict = {}
        for r in _read("LFA1"):
            number = r["LIFNR"].lstrip("0")
            gst = r["STCD3"]
            if (r["KTOKK"] != "ZDOM" or r["SPERR"] or r["SPERM"] or r["LOEVM"] or number in EXCLUDED_VENDORS or len(gst) != 15
                    or gst[14] != gstin_check_char(gst[:14]) or gst[:2] not in STATE_JURISDICTION):
                continue
            self.vendors[r["LIFNR"]] = {"lifnr": r["LIFNR"], "name": " ".join(x for x in (r["NAME1"], r["NAME2"]) if x).strip(), "state": gst[:2], "days": vendor_terms.get(r["LIFNR"], 30)}
        po = {r["EBELN"]: r for r in _read("EKKO") if r["BSTYP"] == "F"}
        self.count: dict = defaultdict(Counter)       # category -> vendor -> PO lines
        self.items: dict = defaultdict(lambda: defaultdict(lambda: {"lines": 0, "qty": Decimal(0)}))   # vendor -> matnr -> stats
        for r in _read("EKPO"):
            head = po.get(r["EBELN"])
            if not head or r["LOEKZ"] or head["LIFNR"] not in self.vendors:
                continue
            cat = category.get(r["MATKL"])
            if cat:
                self.count[cat][head["LIFNR"]] += 1
            matnr = r["MATNR"]
            m = materials.get(matnr)
            if not matnr or m is None or m["LVORM"] or matnr in BAD_MATERIALS or not r["WERKS"] or Decimal(r["NETPR"] or 0) <= 0:
                continue
            stat = self.items[head["LIFNR"]][matnr]
            stat.update({"matnr": matnr, "text": r["TXZ01"], "plant": r["WERKS"], "uom": r["MEINS"], "price": Decimal(r["NETPR"]) / Decimal(r["PEINH"] or 1)})
            stat["lines"] += 1
            stat["qty"] += Decimal(r["MENGE"] or 0)

    def ranked(self, category: str) -> list:
        return [v for v, _ in self.count[category].most_common() if v in self.vendors]


class Builder:
    def __init__(self, seed: int) -> None:
        from app.pic.seed import reference, templates
        self.rng = random.Random(seed)
        self.sap = Sap()
        self.playbook = templates.merged_rules(reference.RULE_SETS, "MANUFACTURING")["CLM-PLAYBOOK"][0]
        self.used: set = set()
        self.contracts: list = []
        self.seq: Counter = Counter()

    # ------------------------------------------------------------------ helpers
    def vendor(self, category: str, rank: int, distinct: bool = True) -> dict:
        ranked = self.sap.ranked(category)
        for lifnr in ranked[rank:] + ranked[:rank]:
            if not distinct or (category, lifnr) not in self.used:
                self.used.add((category, lifnr))
                return self.sap.vendors[lifnr]
        raise RuntimeError(f"no vendor left for {category}")

    def number(self, type_: str) -> str:
        key = {"MASTER_AGREEMENT": "MA", "QUANTITY_CONTRACT": "QC", "VALUE_CONTRACT": "VC", "SCHEDULING_AGREEMENT": "SA", "RATE_CARD": "RC", "SOW": "SOW", "NDA": "NDA"}[type_]
        self.seq[key] += 1
        return f"KAC-{key}-{self.seq[key]:04d}"

    def goods_lines(self, vendor: dict, n: int) -> list:
        items = sorted(self.sap.items[vendor["lifnr"]].values(), key=lambda x: (-x["lines"], x["matnr"]))[:n]
        out = []
        for i, it in enumerate(items, start=1):
            annual = max(Decimal(100), (it["qty"] / 2 * Decimal("1.1")).quantize(Decimal("1")))
            price = (it["price"] * Decimal(str(round(self.rng.uniform(0.98, 1.03), 4)))).quantize(Decimal("0.01"))
            out.append({"no": i * 10, "matnr": it["matnr"], "text": it["text"], "plant": it["plant"], "uom": it["uom"], "qty": annual, "price": price})
        return out

    def service_lines(self, category: str, n: int, plant: str = "") -> list:
        out = []
        for i, (text, werks, uom, qty, price) in enumerate(SERVICE_LINES[category][:n], start=1):
            out.append({"no": i * 10, "matnr": "", "text": text, "plant": plant or werks, "uom": uom,
                        "qty": Decimal(self.rng.randint(*qty)), "price": Decimal(self.rng.randint(*price)).quantize(Decimal("0.01"))})
        return out

    def add(self, type_: str, category: str, vendor: dict, title: str, status: str, valid_from: date, valid_to: date, **kw) -> dict:
        c = {"no": self.number(type_), "type": type_, "category": category, "vendor": vendor, "title": title[:200], "status": status,
             "from": valid_from, "to": valid_to, "parent": None, "lines": [], "terms": f"N{vendor['days']}", "inco": "", "owner": "contract.manager",
             "over": "0", "under": "0", "price_tol": "0", "index": None, "edits": {}, "amendments": [], "rebate": None, "redlines": [],
             "signed_on": None, "terminated_on": None, "termination_reason": "", "health": None, **kw}
        c["jurisdiction"] = STATE_JURISDICTION[vendor["state"]]
        self.contracts.append(c)
        return c

    def window(self, parent: dict | None, term_months: int = 24) -> tuple:
        """Validity of an ACTIVE contract: inside the parent's, at least 150 days to run."""
        rng = self.rng
        if parent is None:
            start = min(date(rng.choice([2024, 2025, 2026]), rng.randint(1, 12), 1), date(2026, 9, 1))
            end = add_months(start, term_months) - timedelta(days=1)
            while end < date(2027, 4, 1):
                end = add_months(end + timedelta(days=1), 12) - timedelta(days=1)
            return start, end
        start = parent["from"] + timedelta(days=rng.randint(0, 240))
        start = min(start, date(2026, 9, 15))
        end = min(parent["to"], add_months(start, term_months) - timedelta(days=1))
        if end < date(2027, 4, 1):
            end = parent["to"]
        return start, end

    def build(self) -> list:
        rng = self.rng
        masters: dict = {}
        master_plan = [  # key, category, rank, valid_from, term months, status
            ("M1", "ALU-DIECAST", 0, date(2024, 7, 1), 36), ("M2", "ALU-DIECAST", 1, date(2025, 4, 1), 36), ("M3", "FERROUS-CASTINGS", 0, date(2025, 4, 1), 36),
            ("M4", "FORGINGS", 0, date(2024, 7, 1), 36), ("M5", "MACHINING", 0, date(2025, 10, 1), 36), ("M6", "RAW-MATERIALS", 0, date(2026, 4, 1), 36),
            ("M7", "FASTENERS", 0, date(2025, 10, 1), 36), ("M8", "RUBBER-SEALS", 0, date(2024, 1, 19), 36), ("M9", "ELECTRONICS", 0, date(2025, 4, 1), 36),
            ("M10", "PACKAGING", 0, date(2025, 10, 1), 36), ("M11", "LOGISTICS", 0, date(2025, 4, 1), 36), ("M12", "IT-SERVICES", 0, date(2025, 10, 1), 36),
            ("M13", "FACILITIES", 0, date(2026, 4, 1), 36), ("M14", "MRO", 0, date(2024, 7, 1), 36)]
        for key, category, rank, start, term in master_plan:
            vendor = self.vendor(category, rank)
            label = "supply" if category in ("ALU-DIECAST", "FERROUS-CASTINGS", "FORGINGS", "MACHINING", "RAW-MATERIALS", "FASTENERS", "RUBBER-SEALS",
                                              "ELECTRONICS", "PACKAGING", "MRO") else "services"
            end = add_months(start, term) - timedelta(days=1)
            if key == "M8":
                end = date(2027, 1, 18)
            masters[key] = self.add("MASTER_AGREEMENT", category, vendor, f"Master {label} agreement - {CATEGORY_LABEL[category]} - {vendor['name']}",
                                    "EXPIRING" if key == "M8" else "ACTIVE", start, end, inco="FCA" if label == "supply" else "")
        m = masters

        def child(type_: str, parent_key: str, title: str, status: str = "ACTIVE", lines=None, **kw) -> dict:
            p = m[parent_key]
            if "valid_from" in kw:
                start, end = kw.pop("valid_from"), kw.pop("valid_to")
            else:
                start, end = self.window(p, kw.pop("term", 24))
            inco = kw.pop("inco", "FCA" if type_ in ("QUANTITY_CONTRACT", "SCHEDULING_AGREEMENT") else "")
            return self.add(type_, p["category"], p["vendor"], title, status, start, end, parent=p["no"], lines=lines or [], inco=inco, **kw)

        def goods(parent_key: str, n: int) -> list:
            return self.goods_lines(m[parent_key]["vendor"], n)

        # --- scheduling agreements (indexed, with tolerance) -------------------------------------------------------------------
        sa = {}
        for key, parent, n, extra in (("SA1", "M1", 3, {}), ("SA2", "M2", 3, {"valid_from": date(2025, 11, 1), "valid_to": date(2027, 3, 9)}),
                                      ("SA3", "M3", 3, {}), ("SA4", "M4", 3, {}), ("SA5", "M5", 3, {}), ("SA6", "M9", 2, {})):
            p = m[parent]
            sa[key] = child("SCHEDULING_AGREEMENT", parent, f"{CATEGORY_LABEL[p['category']]} - scheduling agreement - {p['vendor']['name']}", lines=goods(parent, n),
                            over="2", under="5", price_tol="0.5", index={"index": INDEX_BY_CATEGORY[p["category"]], "base": "100.00", "band": "3", "reset": "QUARTERLY"}, **extra)
        # --- quantity contracts ----------------------------------------------------------------------------------------------
        qc = {}
        for key, parent, n, extra in (("QC1", "M6", 2, {}), ("QC2", "M7", 3, {"valid_from": date(2025, 11, 15), "valid_to": date(2027, 2, 13)}),
                                      ("QC3", "M7", 2, {}), ("QC4", "M8", 2, {"valid_from": date(2024, 3, 1), "valid_to": date(2027, 1, 18)}),
                                      ("QC5", "M8", 2, {"valid_from": date(2025, 4, 1), "valid_to": date(2027, 1, 18)}), ("QC6", "M10", 2, {}),
                                      ("QC7", "M10", 2, {"valid_from": date(2025, 10, 16), "valid_to": date(2026, 10, 15)}), ("QC8", "M3", 2, {})):
            p = m[parent]
            status = "EXPIRING" if key in ("QC2", "QC4", "QC5") else "EXPIRED" if key == "QC7" else "ACTIVE"
            qc[key] = child("QUANTITY_CONTRACT", parent, f"{CATEGORY_LABEL[p['category']]} - quantity contract - {p['vendor']['name']}", status, lines=goods(parent, n),
                            over="2", under="3", **extra)
        # --- value contracts (services and MRO) ---------------------------------------------------------------------------------
        vc = {}
        for key, parent, cat, n, status, title, extra in (
                ("VC1", "M11", "LOGISTICS", 3, "ACTIVE", "Inbound and outbound freight, value contract", {}),
                ("VC2", "M12", "IT-SERVICES", 2, "ACTIVE", "Application support and maintenance, annual value contract", {}),
                ("VC3", "M12", "IT-SERVICES", 1, "ACTIVE", "Infrastructure managed services, value contract", {}),
                ("VC4", "M13", "FACILITIES", 3, "TERMINATED", "Housekeeping and security services, value contract",
                 {"valid_from": date(2026, 4, 15), "valid_to": date(2027, 3, 31), "terminated_on": date(2026, 9, 15),
                  "termination_reason": "Terminated for cause: repeated non-remittance of provident fund and service-level breaches in three consecutive months."}),
                ("VC5", "M14", "MRO", 2, "ACTIVE", "Plant maintenance services, value contract", {}),
                ("VC6", "M14", "MRO", 2, "EXPIRING", "Emergency electrical call-out services, value contract", {"valid_from": date(2025, 2, 1), "valid_to": date(2027, 1, 28)})):
            vc[key] = child("VALUE_CONTRACT", parent, title + f" - {m[parent]['vendor']['name']}", status, lines=self.service_lines(cat, n), **extra)
        # --- rate cards -----------------------------------------------------------------------------------------------------------
        rc = {}
        rc["RC1"] = child("RATE_CARD", "M11", f"Freight rate card by lane - {m['M11']['vendor']['name']}", lines=self.service_lines("LOGISTICS", 4))
        rc["RC2"] = child("RATE_CARD", "M12", f"IT time-and-material rate card - {m['M12']['vendor']['name']}", "EXPIRING",
                          lines=self.service_lines("IT-SERVICES", 3), valid_from=date(2025, 10, 15), valid_to=date(2027, 2, 26))
        rc["RC3"] = child("RATE_CARD", "M13", f"Manpower rate card - {m['M13']['vendor']['name']}", lines=self.service_lines("FACILITIES", 2))
        v = self.vendor("PROF-SERVICES", 0)
        rc["RC4"] = self.add("RATE_CARD", "PROF-SERVICES", v, f"Professional services rate card - {v['name']}", "ACTIVE", *self.window(None, 24),
                             lines=self.service_lines("PROF-SERVICES", 2))
        v = self.vendor("TOOLING-SERVICES", 0)
        rc["RC5"] = self.add("RATE_CARD", "TOOLING-SERVICES", v, f"Die repair and trial rate card - {v['name']}", "EXPIRING", date(2025, 11, 29), date(2026, 11, 28),
                             lines=self.service_lines("TOOLING-SERVICES", 2))
        rc["RC6"] = child("RATE_CARD", "M14", f"Maintenance services rate card - {m['M14']['vendor']['name']}", lines=self.service_lines("MRO", 2))
        v = self.vendor("IT-SERVICES", 1)
        rc["RC7"] = self.add("RATE_CARD", "IT-SERVICES", v, f"Cloud and security consulting rate card - {v['name']}", "IN_NEGOTIATION", date(2026, 12, 1), date(2028, 11, 30),
                             lines=self.service_lines("IT-SERVICES", 3))
        v = self.vendor("LOGISTICS", 1)
        rc["RC8"] = self.add("RATE_CARD", "LOGISTICS", v, f"Export freight rate card - {v['name']}", "EXPIRED", date(2025, 10, 1), date(2026, 9, 30),
                             lines=self.service_lines("LOGISTICS", 3))
        # --- statements of work ------------------------------------------------------------------------------------------------------
        sow = {}
        for key, cat, rank, parent, title, status, start, end in (
                ("S1", "IT-SERVICES", 0, "M12", "ERP integration and data migration programme", "IN_NEGOTIATION", date(2026, 12, 1), date(2027, 9, 30)),
                ("S2", "FACILITIES", 1, None, "Oragadam canteen and rest-area refurbishment", "OUT_FOR_SIGNATURE", date(2026, 11, 15), date(2027, 3, 31)),
                ("S3", "PROF-SERVICES", 1, None, "Supplier quality-system audit programme", "ACTIVE", date(2026, 5, 1), date(2027, 6, 30)),
                ("S4", "TOOLING-SERVICES", 1, None, "Die refurbishment programme, phase 2", "EXPIRING", date(2026, 1, 1), date(2026, 12, 23)),
                ("S5", "IT-HARDWARE", 0, None, "Laptop and network refresh, rollout", "ACTIVE", date(2026, 6, 1), date(2027, 5, 31)),
                ("S6", "CAPEX-MACHINERY", 0, None, "HPDC machine 1250 t, installation and commissioning", "ACTIVE", date(2026, 4, 1), date(2027, 4, 30)),
                ("S7", "LOGISTICS", 2, None, "Finished-goods warehouse relocation, Bidadi", "ACTIVE", date(2026, 7, 1), date(2027, 6, 30)),
                ("S8", "PROF-SERVICES", 2, None, "Environment, health and safety audit and certification support", "ACTIVE", date(2026, 3, 1), date(2027, 8, 31))):
            vendor = m[parent]["vendor"] if parent else self.vendor(cat, rank)
            lines = self.service_lines(cat, 2 if cat in ("IT-HARDWARE", "IT-SERVICES") else 1)
            if cat == "IT-SERVICES":
                lines = self.service_lines(cat, 2)
            sow[key] = self.add("SOW", cat, vendor, f"{title} - {vendor['name']}", status, start, end, lines=lines, parent=m[parent]["no"] if parent else None,
                                milestones=SOW_MILESTONES[cat])
        # --- NDAs -----------------------------------------------------------------------------------------------------------------------
        nda_plan = [("ALU-DIECAST", 2, "ACTIVE"), ("FORGINGS", 1, "ACTIVE"), ("MACHINING", 1, "ACTIVE"), ("ELECTRONICS", 1, "EXPIRING"),
                    ("SOFTWARE-LICENCES", 0, "ACTIVE"), ("IT-SERVICES", 2, "ACTIVE"), ("PROF-SERVICES", 3, "EXPIRED"), ("CAPEX-MACHINERY", 1, "ACTIVE"),
                    ("RAW-MATERIALS", 1, "DRAFT"), ("TOOLING", 0, "ACTIVE")]
        for category, rank, status in nda_plan:
            vendor = self.vendor(category, rank)
            start, end = ((date(2025, 11, 20), date(2026, 11, 19)) if status == "EXPIRING" else (date(2024, 9, 1), date(2026, 8, 31)) if status == "EXPIRED"
                          else (date(2026, 11, 15), date(2029, 11, 14)) if status == "DRAFT" else self.window(None, rng.choice([24, 36])))
            self.add("NDA", category, vendor, f"Mutual non-disclosure agreement - {vendor['name']}", status, start, end)
        self._finish(m, sa, qc, vc, rc, sow)
        return self.contracts

    # ------------------------------------------------------------------ decorations
    def _finish(self, m, sa, qc, vc, rc, sow) -> None:
        rng = self.rng
        # contracts that carry fallback or non-standard clause wording
        for key in ("SA3", "QC1", "QC6", "VC1", "VC2", "RC1", "M2", "M9", "S3", "S5"):
            self._by_key(key, m, sa, qc, vc, rc, sow)["edits_fallback"] = rng.randint(1, 3)
        risky = {"SA5": ["PAYMENT", "LIABILITY", "TERMINATION"], "QC3": ["IP", "WARRANTY"], "VC5": ["INDEMNITY", "AUDIT_RIGHTS"], "M7": ["LIABILITY", "FORCE_MAJEURE"],
                 "RC4": ["LIABILITY", "INDEMNITY"], "S6": ["PAYMENT", "LIQUIDATED_DAMAGES"], "QC8": ["SUBCONTRACTING", "WARRANTY", "LIABILITY"]}
        for key, codes in risky.items():
            self._by_key(key, m, sa, qc, vc, rc, sow)["edits_risky"] = codes
        # rebate agreements: (key, scope, basis, period, mode, tiers (from, ratePct))
        rebate = {"M1": ("SUPPLIER", "VALUE", "ANNUAL", "RETROACTIVE", [(0, "0.5"), (5000000, "1.0"), (10000000, "1.5")]),
                  "M3": ("SUPPLIER", "VALUE", "ANNUAL", "SLAB", [(2500000, "0.5"), (7500000, "1.0"), (15000000, "2.0")]),
                  "M7": ("SUPPLIER", "VALUE", "QUARTERLY", "SLAB", [(1000000, "0.75"), (2500000, "1.25")]),
                  "M9": ("SUPPLIER", "VALUE", "ANNUAL", "RETROACTIVE", [(0, "0.25"), (4000000, "0.75"), (8000000, "1.25")]),
                  "QC1": ("CONTRACT", "VOLUME", "ANNUAL", "RETROACTIVE", [(1000, "1.0"), (5000, "2.0")]),
                  "SA2": ("CONTRACT", "VOLUME", "QUARTERLY", "SLAB", [(500, "0.5"), (2500, "1.5"), (6000, "2.5")])}
        for key, spec in rebate.items():
            self._by_key(key, m, sa, qc, vc, rc, sow)["rebate"] = spec
        # amendment history
        a = self._by_key
        a("M1", m, sa, qc, vc, rc, sow)["amendments"] = [
            {"kind": "TERMS", "status": "EFFECTIVE", "effective": date(2025, 9, 1), "reason": "Payment terms aligned to 45 days (MSME rule, MSMED Act section 15).",
             "changes": {"paymentTerms": "N45"}, "before": {"paymentTerms": "N60"}}]
        a("SA1", m, sa, qc, vc, rc, sow)["amendments"] = [
            {"kind": "VARIATION", "status": "EFFECTIVE", "effective": date(2026, 7, 1), "reason": "Quarterly aluminium price revision: unit prices up 6.4%.",
             "changes": {"priceFactor": "1.064"}, "before": {"priceFactor": "1.000"}}]
        a("SA3", m, sa, qc, vc, rc, sow)["amendments"] = [
            {"kind": "VARIATION", "status": "EFFECTIVE", "effective": date(2026, 4, 1), "reason": "Target quantity raised for the new model launch.",
             "changes": {"qtyFactor": "1.25"}, "before": {"qtyFactor": "1.00"}},
            {"kind": "TERMS", "status": "EFFECTIVE", "effective": date(2026, 8, 1), "reason": "Liability clause moved to the playbook fallback (cap 50% of annual value) after Legal review.",
             "changes": {"clauses": ["LIABILITY"]}, "before": {"clauses": ["LIABILITY"]}}]
        a("QC2", m, sa, qc, vc, rc, sow)["amendments"] = [
            {"kind": "EXTENSION", "status": "EFFECTIVE", "effective": date(2026, 2, 10), "reason": "Extended by 12 months to follow the master agreement.",
             "changes": {"validTo": "2027-02-13"}, "before": {"validTo": "2026-02-13"}}]
        a("RC2", m, sa, qc, vc, rc, sow)["amendments"] = [
            {"kind": "TERMS", "status": "EFFECTIVE", "effective": date(2026, 1, 1), "reason": "Payment terms changed to 45 days.", "changes": {"paymentTerms": "N45"},
             "before": {"paymentTerms": "N60"}},
            {"kind": "VARIATION", "status": "REJECTED", "effective": date(2026, 9, 1), "reason": "Supplier asked for a 12% rate increase; not approved.",
             "changes": {"priceFactor": "1.12"}, "before": {"priceFactor": "1.000"}}]
        a("S4", m, sa, qc, vc, rc, sow)["amendments"] = [
            {"kind": "EXTENSION", "status": "EFFECTIVE", "effective": date(2026, 9, 20), "reason": "Programme extended to complete the last die batch.",
             "changes": {"validTo": "2026-12-23"}, "before": {"validTo": "2026-09-30"}}]
        a("VC4", m, sa, qc, vc, rc, sow)["amendments"] = [
            {"kind": "TERMINATION", "status": "EFFECTIVE", "effective": date(2026, 9, 15), "reason": vc["VC4"]["termination_reason"],
             "changes": {"forCause": True}, "before": {"status": "ACTIVE", "validTo": "2027-03-31"}}]
        # redlines on the contract in negotiation
        sow["S1"]["redlines"] = [
            ("LIABILITY", "Total liability of the supplier is limited to the fees paid in the three months before the claim.", date(2026, 10, 20)),
            ("IP", "The supplier owns all deliverables and grants the buyer a licence to use them for its own business.", date(2026, 10, 20)),
            ("PAYMENT", "Payment within 75 days from the date of the tax invoice.", date(2026, 10, 22))]
        for c in self.contracts:
            for am in c["amendments"]:      # the register shows the contract as amended
                if am["status"] == "EFFECTIVE" and "paymentTerms" in am["changes"]:
                    c["terms"] = am["changes"]["paymentTerms"]
            if c["status"] in ("ACTIVE", "EXPIRING", "EXPIRED", "TERMINATED"):
                c["signed_on"] = max(c["from"] - timedelta(days=rng.randint(7, 40)), date(2023, 4, 1))
                if c["no"] in ("KAC-MA-0001",):
                    c["signed_on"] = date(2024, 6, 14)
            elif c["status"] == "OUT_FOR_SIGNATURE":
                c["signed_on"] = date(2026, 10, 28)     # the buyer has signed
            c["health"] = rng.choices(["GOOD", "MIXED", "POOR"], weights=[55, 30, 15])[0]
        sow["S3"]["health"], sow["S6"]["health"], sow["S7"]["health"] = "MIXED", "POOR", "MIXED"

    def _by_key(self, key, m, sa, qc, vc, rc, sow) -> dict:
        return {**m, **sa, **qc, **vc, **rc, **sow}[key]


# ---------------------------------------------------------------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------------------------------------------------------------
def _library_clauses(b: Builder, c: dict) -> dict:
    from app.pic.services import contract as contract_svc
    index = {"index": c["index"]["index"], "base": c["index"]["base"], "band_pct": c["index"]["band"]} if c["index"] else None
    return contract_svc._library(b.playbook, type=c["type"], payment_terms=c["terms"], incoterms=c["inco"] or None, supplier_name=c["vendor"]["name"],
                                 index_ref=index, tolerances={"over_pct": c["over"], "under_pct": c["under"]}, jurisdiction=c["jurisdiction"], category=c["category"])


def _clause_rows(b: Builder, c: dict) -> list:
    library = _library_clauses(b, c)
    fallbacks = {x["code"]: x.get("fallbacks") or [] for x in (b.playbook.get("clauseLibrary", {}).get("clauses") or [])
                 + (b.playbook.get("clauseLibrary", {}).get("overlayClauses") or [])}
    rng = random.Random(f"{SEED}|{c['no']}")
    positions = {code: ("STANDARD", entry["text"]) for code, entry in library.items()}
    candidates = [code for code in library if fallbacks.get(code) and code not in ("DATA_PROTECTION", "DISPUTES")]
    for code in rng.sample(sorted(candidates), min(c.get("edits_fallback", 0), len(candidates))):
        positions[code] = ("FALLBACK", fallbacks[code][rng.randrange(len(fallbacks[code]))]["text"])
    for am in c["amendments"]:      # a clause an effective terms amendment moved to the playbook fallback carries the fallback wording
        for code in am["changes"].get("clauses", []):
            if am["status"] == "EFFECTIVE" and code in library and fallbacks.get(code):
                positions[code] = ("FALLBACK", fallbacks[code][-1]["text"])
    for code in c.get("edits_risky", []):
        if code in library:
            positions[code] = ("NON_STANDARD", RISKY_TEXT[code])
    for code, text, _ in c["redlines"]:
        if code in library:
            positions[code] = ("NON_STANDARD", text)
    return [{"CONTRACT_NO": c["no"], "CLAUSE_CODE": code, "TITLE": library[code]["title"], "POSITION": pos, "TEXT": text} for code, (pos, text) in sorted(positions.items())]


def _obligation_rows(c: dict, rng: random.Random) -> list:
    t, start, end = c["type"], c["from"], c["to"]
    live = c["status"] in ("ACTIVE", "EXPIRING", "EXPIRED", "TERMINATED")
    plan: list = []   # (kind, party, description, offset days from start)
    if t == "MASTER_AGREEMENT":
        plan += [("OBLIGATION", "SUPPLIER", "Submit insurance certificates and Udyam / MSME registration proof", 30),
                 ("OBLIGATION", "SUPPLIER", "Acknowledge the Supplier Code of Conduct", 45), ("OBLIGATION", "SUPPLIER", "ESG and emissions self-assessment", 180),
                 ("OBLIGATION", "BUYER", "Annual review of the master agreement terms", 330), ("OBLIGATION", "BUYER", "Quarterly business review", 90),
                 ("OBLIGATION", "BUYER", "Quarterly business review", 270), ("OBLIGATION", "SUPPLIER", "ESG and emissions self-assessment", 545)]
    elif t in ("QUANTITY_CONTRACT", "SCHEDULING_AGREEMENT"):
        plan += [("OBLIGATION", "BUYER", "Share the 13-week rolling forecast", 7), ("OBLIGATION", "SUPPLIER", "Quarterly capacity confirmation", 90),
                 ("OBLIGATION", "SUPPLIER", "Quarterly capacity confirmation", 180), ("OBLIGATION", "SUPPLIER", "Quarterly capacity confirmation", 270),
                 ("OBLIGATION", "SUPPLIER", "Annual PPAP layout inspection and certificate of conformity review", 330)]
    elif t in ("VALUE_CONTRACT", "RATE_CARD"):
        plan += [("OBLIGATION", "SUPPLIER", "Monthly service-level report", 30 * i) for i in range(1, 7)]
        plan += [("OBLIGATION", "BUYER", "Quarterly business review", 90), ("OBLIGATION", "BUYER", "Quarterly business review", 180)]
        if c["category"] == "FACILITIES":
            plan += [("OBLIGATION", "SUPPLIER", "Proof of provident fund and ESI remittance", 30 * i) for i in (1, 2, 3, 4)]
        if t == "RATE_CARD":
            plan += [("OBLIGATION", "BUYER", "Annual review of the rate card against market rates", 330)]
    elif t == "SOW":
        offsets = [round((end - start).days * f) for f in (0.2, 0.5, 0.75, 0.95)]
        for i, text in enumerate(c.get("milestones") or []):
            plan += [("MILESTONE", "SUPPLIER", f"Milestone {i + 1}: {text}", offsets[min(i, 3)]), ("MILESTONE", "BUYER", f"Accept or reject milestone {i + 1} in writing", offsets[min(i, 3)] + 10)]
    else:
        plan += [("OBLIGATION", "BUYER", "Annual review of the NDA register entry", 365), ("OBLIGATION", "SUPPLIER", "Confirm return or destruction of confidential information", max((end - start).days - 10, 30))]
    health = c["health"] or "GOOD"
    weights = {"GOOD": (100, 0, 0), "MIXED": (55, 25, 20), "POOR": (30, 20, 50)}[health]
    rows = []
    for kind, party, text, offset in plan:
        due = start + timedelta(days=offset)
        if due > end:
            continue
        status, completed, note = "OPEN", "", ""
        if not live:
            pass
        elif c["terminated_on"] and due > c["terminated_on"]:
            status = "CANCELLED"
        elif due < LOAD_DATE:
            outcome = rng.choices(["ON_TIME", "LATE", "OVERDUE"], weights=weights)[0]
            if outcome == "ON_TIME":
                status, completed, note = "DONE", due - timedelta(days=rng.randint(0, 6)), "Evidence received and filed in the contract record."
            elif outcome == "LATE":
                status, completed, note = "DONE", min(due + timedelta(days=rng.randint(3, 25)), LOAD_DATE - timedelta(days=1)), "Received after the due date; reminder sent."
        rows.append({"CONTRACT_NO": c["no"], "KIND": kind, "PARTY": party, "DESCRIPTION": text, "DUE_DATE": due.isoformat(), "STATUS": status,
                     "COMPLETED_ON": completed.isoformat() if completed else "", "NOTE": note})
    return rows


def build_tables(seed: int = SEED) -> dict:
    """The extract as {file name: (columns, rows)}."""
    b = Builder(seed)
    contracts = b.build()
    contracts.sort(key=lambda c: (0 if c["type"] == "MASTER_AGREEMENT" else 1, c["no"]))
    rng = random.Random(seed + 1)
    t: dict = {k: [] for k in ("CLM_CONTRACT", "CLM_LINE", "CLM_CLAUSE", "CLM_OBLIGATION", "CLM_REBATE", "CLM_AMENDMENT", "CLM_REDLINE")}
    for c in contracts:
        lines = c["lines"]
        for ln in lines:   # price revisions come from the variation amendments
            ln["prev_price"], ln["revised_on"] = "", ""
            for am in c["amendments"]:
                if am["kind"] == "VARIATION" and am["status"] == "EFFECTIVE" and "priceFactor" in am["changes"]:
                    ln["prev_price"], ln["revised_on"] = ln["price"], am["effective"]
                    ln["price"] = (ln["price"] * Decimal(am["changes"]["priceFactor"])).quantize(Decimal("0.01"))
                if am["kind"] == "VARIATION" and am["status"] == "EFFECTIVE" and "qtyFactor" in am["changes"]:
                    ln["qty"] = (ln["qty"] * Decimal(am["changes"]["qtyFactor"])).quantize(Decimal("1"))
        value = sum(int(ln["qty"] * ln["price"] * 100) for ln in lines)
        signer = rng.choice(SIGNATORY_FIRST) + " " + rng.choice(SIGNATORY_LAST)
        number = c["no"]
        doc_ref = f"DMS://KAC/contracts/{c['from'].year}/{number}.pdf" if c["signed_on"] else ""
        t["CLM_CONTRACT"].append({
            "CONTRACT_NO": number, "CONTRACT_TYPE": c["type"], "TITLE": c["title"], "LIFNR": c["vendor"]["lifnr"], "BUKRS": BUKRS, "STATUS": c["status"],
            "VALID_FROM": c["from"].isoformat(), "VALID_TO": c["to"].isoformat(), "PAYMENT_TERMS": c["terms"], "INCO1": c["inco"], "CATEGORY": c["category"],
            "JURISDICTION": c["jurisdiction"], "PARENT_NO": c["parent"] or "", "OWNER": c["owner"], "TARGET_VALUE": _money(value),
            "OVER_TOL": c["over"], "UNDER_TOL": c["under"], "PRICE_TOL": c["price_tol"],
            "INDEX_NAME": c["index"]["index"] if c["index"] else "", "INDEX_BASE": c["index"]["base"] if c["index"] else "",
            "INDEX_BAND": c["index"]["band"] if c["index"] else "", "INDEX_RESET": c["index"]["reset"] if c["index"] else "",
            "SIGNED_ON": c["signed_on"].isoformat() if c["signed_on"] else "",
            "BUYER_SIGNER": rng.choice(BUYER_SIGNERS) if c["signed_on"] else "", "SUPPLIER_SIGNER": f"{signer}, Authorised Signatory" if c["signed_on"] and c["status"] != "OUT_FOR_SIGNATURE" else "",
            "DOC_REF": doc_ref, "TERMINATED_ON": c["terminated_on"].isoformat() if c["terminated_on"] else "", "TERMINATION_REASON": c["termination_reason"],
            "VERSION": 1 + sum(1 for a in c["amendments"] if a["status"] == "EFFECTIVE")})
        for ln in lines:
            t["CLM_LINE"].append({"CONTRACT_NO": number, "LINE_NO": ln["no"], "MATNR": ln["matnr"], "TXZ01": ln["text"], "WERKS": ln["plant"], "MEINS": ln["uom"],
                                  "KTMNG": f"{ln['qty']:.3f}", "NETPR": f"{ln['price']:.2f}", "PREV_NETPR": f"{ln['prev_price']:.2f}" if ln["prev_price"] != "" else "",
                                  "REVISED_ON": ln["revised_on"].isoformat() if ln["revised_on"] else ""})
        t["CLM_CLAUSE"].extend(_clause_rows(b, c))
        t["CLM_OBLIGATION"].extend(_obligation_rows(c, rng))
        if c["rebate"]:
            scope, basis, period, mode, tiers = c["rebate"]
            t["CLM_REBATE"].append({"REBATE_NO": f"KAC-RB-{len(t['CLM_REBATE']) + 1:03d}", "CONTRACT_NO": number, "TITLE": f"{CATEGORY_LABEL[c['category']]} volume rebate - {c['vendor']['name']}"[:200],
                                    "BASIS": basis, "PERIOD": period, "TIER_MODE": mode, "SCOPE": scope, "VALID_FROM": max(c["from"], date(2026, 4, 1)).isoformat(), "VALID_TO": min(c["to"], date(2027, 3, 31)).isoformat(), "TIERS": "|".join(f"{a}:{r}" for a, r in tiers)})
        for seq, am in enumerate(c["amendments"], start=1):
            t["CLM_AMENDMENT"].append({"CONTRACT_NO": number, "SEQ": seq, "KIND": am["kind"], "STATUS": am["status"], "EFFECTIVE_FROM": am["effective"].isoformat(),
                                       "DECIDED_ON": (am["effective"] - timedelta(days=5)).isoformat(), "REASON": am["reason"],
                                       "CHANGES": json.dumps(am["changes"], sort_keys=True), "BEFORE": json.dumps(am["before"], sort_keys=True)})
        for code, text, on in c["redlines"]:
            t["CLM_REDLINE"].append({"CONTRACT_NO": number, "CLAUSE_CODE": code, "SUPPLIER_TEXT": text, "PROPOSED_ON": on.isoformat(), "PROPOSED_BY": c["vendor"]["name"]})
    return {name: (list(rows[0].keys()) if rows else [], rows) for name, rows in t.items()}


def generate(out_dir: Path = OUT_DIR, seed: int = SEED) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = build_tables(seed)
    manifest = {"client": "Kaveri Auto Components Pvt Ltd (fictional)", "sourceSystem": "CLM_REPOSITORY", "system": "contract register export", "release": "mock",
                "extractId": EXTRACT_ID, "extractType": "INITIAL", "companyCodes": [BUKRS], "keyDate": "2026-10-31", "extractedAt": "2026-11-01T02:30:00+05:30",
                "encoding": "UTF-8", "currency": "INR", "illustrative": "ILLUSTRATIVE SAMPLE: fictional contracts, not legal advice", "files": {}}
    for name, (columns, rows) in sorted(tables.items()):
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows([[r[c] for c in columns] for r in rows])
        data = buffer.getvalue().encode("utf-8")
        (out_dir / f"{name}.csv").write_bytes(data)
        manifest["files"][f"{name}.csv"] = {"rows": len(rows), "sha256": hashlib.sha256(data).hexdigest()}
    (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate the mock contract-repository extract of Kaveri Auto Components (tenant KAC)")
    parser.add_argument("--out", default=str(OUT_DIR))
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)
    manifest = generate(Path(args.out), args.seed)
    for name, entry in sorted(manifest["files"].items()):
        print(f"{name:22} {entry['rows']:>6} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
