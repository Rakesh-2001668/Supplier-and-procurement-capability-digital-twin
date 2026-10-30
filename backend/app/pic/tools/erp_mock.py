"""Mock SAP S/4HANA extract of the fictional prospect Kaveri Auto Components Pvt Ltd (tenant KAC).

    python -m app.pic.tools.erp_mock [--out data/erp_mock/KAC] [--seed 20261031]

Writes the cutover extract that docs/PIC_ERP_Extract_Spec.md asks a client's SAP team for (one CSV per SAP table, UTF-8,
ISO dates, amounts in document currency with the currency key, MANIFEST.json with row counts, control totals and SHA-256 of
every file), so the ERP loader (``app.pic.tools.erp_load``) can be demonstrated end to end before a real client sends its
own files. A real extract in the same layout drops into the same loader unchanged.

Everything is generated from a fixed random seed: the same seed gives byte-identical files (the test compares hashes).
Everything is FICTIONAL: company, vendors, people, PANs/GSTINs (valid format and check character, PAN inside the GSTIN, but
generated), bank accounts and IFSC branch codes (real bank prefixes, branch codes of the form ``0K#####`` that are not RBI
branch codes - never use them for payments), e-mail domains ``.example``, no telephone numbers. HSN/SAC codes are real
6-digit codes (SAC: 6-digit service codes) whose GST rates are read from ``data/reference/hsn_gst_rates.csv`` (CBIC, in force
from 22.09.2025). The same rate is used for the whole 24-month history; the codes were chosen among headings whose rate the
September 2025 rationalisation did not change (castings, forgings, fasteners, rubber articles, bearings, electrical
apparatus, services at 18 %, natural rubber at 5 %) - confirm against Notification 1/2017-CT(Rate) before relying on the tax
amount of a pre-22.09.2025 invoice. Freight (SAC 996791, GTA) is billed at 18 % (forward charge with ITC).

The company: Kaveri Auto Components Pvt Ltd, company code 1000 (registered office Coimbatore, Tamil Nadu), plants 1100 Hosur
(SIPCOT, Tamil Nadu, GST state 33), 1200 Oragadam (Tamil Nadu, 33) and 1300 Bidadi (Karnataka, 29). Direct material: aluminium
die castings, grey/SG iron castings, forgings, machined parts, steel bars and aluminium ingot, fasteners, rubber parts and
seals, electrical parts and harnesses, packaging; indirect: MRO, lubricants, chemicals, tooling, die/machine repair, freight,
IT, facilities, professional services, capital machinery, office and safety; a group company (intercompany).
History: 24 months of posted invoices (November 2024 - October 2026, Indian seasonality: March year-end, festive September/
October, December shutdown), key date (cutover) 31.10.2026.

Deliberate data-quality cases (the loader must reject or flag them; the test asserts each one):
  vendors      DUPLICATE: 100198 is 100031 again (same GSTIN), 100211 is the Karnataka GST registration of 100047 (same PAN),
               200202 "Mullai Industrial Suppliers" next to 200201 "Mullai Industrial Supplies" (similar name), 200203 and
               200052 share one bank account; REJECT: 200301/200302 no GSTIN, 200303 wrong check character, 200304 PAN differs
               from the PAN inside the GSTIN, 200305 state code 39; bank row of 200081 has an IFSC of 10 characters;
               six vendors blocked (LFA1-SPERR/SPERM), five with the deletion flag (LFA1-LOEVM, history only)
  materials    REJECT: 41000198/41000199 without HSN (MARC-STEUC), 41000200 HSN 999999 (not in the CBIC schedule),
               41000197 unit "XYZ", 41000196 material group ZOLD (not mapped); five materials with the deletion flag
  agreements   REJECT: 5500000999 validity end before start; 56 expired agreements (predecessors) used for spend coverage only
  PO / spend   REJECT: three RSEG lines with negative quantity, two lines (and one open PO line) of materials missing from
               MARA (29999999, 41999999), one line of a PO missing from EKKO (4500999999), one RSEG row extracted twice,
               one open PO line with quantity 0 and one with a negative price; all lines of the five rejected vendors
  open AP      REJECT: supplier invoice of 100074 posted twice (same XBLNR, 2026-27) - the second item; open items of rejected vendors
  GL tie-out   intentional variances (ACDOCA vs extract, beyond ±0.5 %):
               2025-03 +₹42,00,000 on 430100 freight provision (accrual JV 100000412, listed in GL_RECON_ITEMS -> EXPLAINED)
               2026-09 -₹36,80,000 on 191100 GR/IR maintenance MR11 (doc 5000098811, listed -> EXPLAINED)
               2026-08 +₹24,60,000 on 450100: an FI invoice (doc type KA) missing from the extract and NOT listed -> UNEXPLAINED
"""
import argparse
import csv
import hashlib
import io
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from app.pic.config import BACKEND_DIR
from app.pic.services.master_changes import gstin_check_char

SEED = 20261031
OUT_DIR = BACKEND_DIR / "data" / "erp_mock" / "KAC"
REFERENCE = BACKEND_DIR / "data" / "reference" / "hsn_gst_rates.csv"
KEY_DATE = date(2026, 10, 31)
HISTORY_FROM = date(2024, 11, 1)
ORDERS_FROM = date(2024, 10, 1)
EXTRACT_ID = "KAC-S4H-20261101-INIT"
BUKRS = "1000"
COMPANY = "Kaveri Auto Components Pvt Ltd"
COMPANY_PAN = "AAKCK7316R"
CR = 10_000_000 * 100      # one crore rupees in paise
LAKH = 100_000 * 100

# Intentional GL variances (period, account, amount in paise, documented in GL_RECON_ITEMS?, reason).
VARIANCES = [
    ("2025-03", "430100", 42_00_000 * 100, True, "ACCRUAL", "100000412",
     "Provision for unbilled freight March 2025 (JV, reversed 01.04.2025)"),
    ("2026-09", "191100", -36_80_000 * 100, True, "GRIR_MAINTENANCE", "5000098811",
     "MR11 GR/IR account maintenance: small differences written off"),
    ("2026-08", "450100", 24_60_000 * 100, False, "MISSING_FROM_EXTRACT", "1700000231",
     "IT invoice posted with document type KA, not selected by the extract (KR/RE only)"),
]


def gstin(state: str, pan: str, entity: str = "1") -> str:
    first14 = f"{state}{pan}{entity}Z"
    return first14 + gstin_check_char(first14)


# ---------------------------------------------------------------- organisation
PLANTS = [  # WERKS, name, street, city, PIN, GST state
    ("1100", "Hosur Plant", "Plot 47-52, SIPCOT Industrial Complex Phase II", "Hosur", "635109", "33"),
    ("1200", "Oragadam Plant", "Plot B-14, SIPCOT Industrial Park, Oragadam", "Sriperumbudur", "602105", "33"),
    ("1300", "Bidadi Plant", "Plot 118, KIADB Industrial Area, Bidadi", "Ramanagara", "562109", "29"),
]
PLANT_WEIGHTS = {"1100": 0.45, "1200": 0.35, "1300": 0.20}
COST_CENTERS = [  # KOSTL, plant, category, text, person responsible
    ("1110", "1100", "F", "Production - Hosur", "R. Senthil Kumar"), ("1120", "1100", "H", "Maintenance - Hosur", "K. Prabhakaran"),
    ("1130", "1100", "H", "Quality - Hosur", "M. Revathi"), ("1140", "1100", "H", "Stores and logistics - Hosur", "S. Dinesh"),
    ("1210", "1200", "F", "Production - Oragadam", "A. Vasanth"), ("1220", "1200", "H", "Maintenance - Oragadam", "P. Karthikeyan"),
    ("1230", "1200", "H", "Quality - Oragadam", "J. Nirmala"), ("1240", "1200", "H", "Stores and logistics - Oragadam", "V. Saravanan"),
    ("1310", "1300", "F", "Production - Bidadi", "H. Manjunath"), ("1320", "1300", "H", "Maintenance - Bidadi", "B. Shivakumar"),
    ("1330", "1300", "H", "Quality - Bidadi", "N. Kavya"),
    ("9100", "1100", "V", "Administration - head office", "L. Meenakshi"), ("9200", "1100", "V", "Information technology", "G. Arvind"),
    ("9300", "1100", "V", "HR and facilities", "T. Kalaiselvi"), ("9400", "1100", "V", "Finance and accounts", "C. Ramanathan"),
    ("9500", "1100", "V", "Purchase and supply chain", "D. Vijayalakshmi"),
]
WBS = [  # POSID, description, project, plant
    ("P-26001.01", "HPDC cell 4 - die casting machine and robot", "P-26001", "1100"),
    ("P-26001.02", "HPDC cell 4 - trim press and automation", "P-26001", "1100"),
    ("P-26002.01", "Bidadi CNC machining line 3", "P-26002", "1300"),
    ("P-25003.01", "Oragadam utilities upgrade - compressor house", "P-25003", "1200"),
]
TERMS = [("Z015", 15, "Net 15 days"), ("Z030", 30, "Net 30 days"), ("Z045", 45, "Net 45 days (MSME limit)"), ("Z060", 60, "Net 60 days")]
TAX_CODES = [("S5", "Input CGST 2.5% + SGST 2.5%", 5, "CGST_SGST"), ("S8", "Input CGST 9% + SGST 9%", 18, "CGST_SGST"),
             ("I5", "Input IGST 5%", 5, "IGST"), ("I8", "Input IGST 18%", 18, "IGST")]
GL_TEXT = {
    "191100": "GR/IR clearing - external procurement", "410100": "Stores and spares consumed", "410200": "Lubricants and oils consumed",
    "410300": "Chemicals and paints consumed", "410400": "Tools and dies consumed", "420100": "Repairs - plant and machinery",
    "430100": "Freight inward", "440100": "Housekeeping, security and canteen", "450100": "IT services and AMC",
    "450200": "Software subscriptions", "450300": "IT hardware below capitalisation limit", "460100": "Professional, testing and audit fees",
    "470100": "Office, safety and welfare", "129100": "Capital work in progress", "160000": "Sundry creditors - domestic",
}

# ---------------------------------------------------------------- categories, material groups, taxonomy
# category: annual spend ₹ Cr, average PO line ₹ lakh, scheduling-agreement share, contract-release share, vendors,
#           lead days, free-text share, account assignment of free-text/service lines, G/L account, service, FI-invoice share
CATS = {
    "ALU-DIECAST": dict(cr=70, line=6.0, sa=0.75, vendors=10, lead=(5, 10)),
    "FERROUS-CASTINGS": dict(cr=55, line=5.0, sa=0.60, vendors=10, lead=(6, 12)),
    "FORGINGS": dict(cr=60, line=5.0, sa=0.65, vendors=12, lead=(6, 12)),
    "MACHINING": dict(cr=40, line=6.0, sa=0.30, vendors=16, lead=(4, 10)),
    "RAW-MATERIALS": dict(cr=75, line=12.0, ct=0.70, vendors=12, lead=(3, 8)),
    "FASTENERS": dict(cr=18, line=2.0, ct=0.50, vendors=12, lead=(3, 7)),
    "RUBBER-SEALS": dict(cr=22, line=2.5, sa=0.40, vendors=12, lead=(4, 9)),
    "ELECTRONICS": dict(cr=30, line=3.5, sa=0.35, vendors=14, lead=(6, 14)),
    "PACKAGING": dict(cr=9, line=1.5, ct=0.30, vendors=9, lead=(3, 6)),
    "MRO": dict(cr=14, line=0.7, vendors=28, lead=(2, 6), ft=0.30, knttp="K", gl="410100"),
    "MRO-LUBRICANTS": dict(cr=4, line=1.0, vendors=6, lead=(2, 5), ft=0.10, knttp="K", gl="410200"),
    "MRO-CHEMICALS": dict(cr=2, line=0.8, vendors=5, lead=(2, 5), ft=0.15, knttp="K", gl="410300"),
    "TOOLING": dict(cr=10, line=2.0, vendors=10, lead=(10, 25), ft=0.20, knttp="K", gl="410400"),
    "TOOLING-SERVICES": dict(cr=6, line=2.0, vendors=9, lead=(2, 8), ft=0.50, knttp="K", gl="420100", service=True),
    "LOGISTICS": dict(cr=16, line=2.0, ct=0.50, vendors=13, lead=(0, 3), ft=0.35, knttp="K", gl="430100", service=True, fi=0.05),
    "IT-HARDWARE": dict(cr=2.5, line=1.2, vendors=5, lead=(5, 12), ft=0.30, knttp="K", gl="450300"),
    "SOFTWARE-LICENCES": dict(cr=3, line=2.5, vendors=4, lead=(0, 3), ft=0.50, knttp="K", gl="450200", service=True),
    "IT-SERVICES": dict(cr=4, line=1.0, ct=0.50, vendors=8, lead=(0, 4), ft=0.40, knttp="K", gl="450100", service=True, fi=0.10),
    "FACILITIES": dict(cr=7, line=1.5, ct=0.70, vendors=11, lead=(0, 2), ft=0.20, knttp="K", gl="440100", service=True, fi=0.10),
    "PROF-SERVICES": dict(cr=4, line=0.8, ct=0.15, vendors=13, lead=(0, 8), ft=0.50, knttp="K", gl="460100", service=True, fi=0.40),
    "CAPEX-MACHINERY": dict(cr=12, line=15.0, vendors=10, lead=(25, 60), ft=1.0, knttp="P", gl="129100"),
    "OFFICE-SAFETY": dict(cr=1.5, line=0.5, vendors=7, lead=(2, 6), ft=0.30, knttp="K", gl="470100"),
    "IC-TRANSFER": dict(cr=6, line=5.0, vendors=1, lead=(3, 6)),
}
for _c in CATS.values():
    for _k, _v in (("sa", 0.0), ("ct", 0.0), ("ft", 0.0), ("knttp", ""), ("gl", "191100"), ("service", False), ("fi", 0.0)):
        _c.setdefault(_k, _v)

MATKL = [  # MATKL, text, PIC category
    ("RM-STEEL", "Alloy steel bars and rods", "RAW-MATERIALS"), ("RM-ALUIN", "Aluminium alloy ingots", "RAW-MATERIALS"),
    ("RM-POLY", "Polymers and rubber compounds", "RAW-MATERIALS"), ("RM-NRUB", "Natural rubber", "RAW-MATERIALS"),
    ("BO-ALUDC", "Aluminium die castings", "ALU-DIECAST"), ("BO-FECST", "Grey and SG iron castings", "FERROUS-CASTINGS"),
    ("BO-FORG", "Steel forgings", "FORGINGS"), ("BO-MACH", "Machined components", "MACHINING"), ("BO-FAST", "Fasteners and springs", "FASTENERS"),
    ("BO-RUBB", "Rubber moulded parts and hoses", "RUBBER-SEALS"), ("BO-SEAL", "Seals, gaskets and O-rings", "RUBBER-SEALS"),
    ("BO-ELEC", "Electrical and electronic parts", "ELECTRONICS"), ("BO-HARN", "Wiring harnesses and cables", "ELECTRONICS"),
    ("PK-PACK", "Packaging material", "PACKAGING"), ("MR-BEAR", "Bearings and transmission parts", "MRO"),
    ("MR-TOOL", "Hand and power tools", "MRO"), ("MR-ABRS", "Abrasives and welding consumables", "MRO"),
    ("MR-HYDR", "Hydraulics, pneumatics and valves", "MRO"), ("MR-ELEC", "Electrical maintenance spares", "MRO"),
    ("MR-LUBE", "Lubricants and coolants", "MRO-LUBRICANTS"), ("MR-CHEM", "Chemicals and paints", "MRO-CHEMICALS"),
    ("TL-DIES", "Dies, moulds and fixtures", "TOOLING"), ("TL-CUTT", "Cutting tools and holders", "TOOLING"),
    ("IT-HW", "IT hardware", "IT-HARDWARE"), ("OF-SAFE", "Office and safety supplies", "OFFICE-SAFETY"),
    ("SV-LOGI", "Freight and logistics services", "LOGISTICS"), ("SV-FACL", "Facility services", "FACILITIES"),
    ("SV-ITSV", "IT services", "IT-SERVICES"), ("SV-SOFT", "Software licences", "SOFTWARE-LICENCES"),
    ("SV-PROF", "Professional services", "PROF-SERVICES"), ("SV-TEST", "Testing and calibration", "PROF-SERVICES"),
    ("SV-REPR", "Machine repair and die maintenance", "TOOLING-SERVICES"), ("CP-MACH", "Capital machinery", "CAPEX-MACHINERY"),
    ("IC-GROUP", "Intercompany supplies", "IC-TRANSFER"), ("ZMISC", "Miscellaneous (to be classified)", "UNCLASSIFIED"),
    ("ZOLD", "Obsolete group (not mapped)", None),
]
CAT_MATKL = {"MRO": "MR-BEAR", "MRO-LUBRICANTS": "MR-LUBE", "MRO-CHEMICALS": "MR-CHEM", "TOOLING": "TL-CUTT", "TOOLING-SERVICES": "SV-REPR",
             "LOGISTICS": "SV-LOGI", "IT-HARDWARE": "IT-HW", "SOFTWARE-LICENCES": "SV-SOFT", "IT-SERVICES": "SV-ITSV",
             "FACILITIES": "SV-FACL", "PROF-SERVICES": "SV-PROF", "CAPEX-MACHINERY": "CP-MACH", "OFFICE-SAFETY": "OF-SAFE"}
TAXONOMY_EXT = [  # categories the PIC default taxonomy does not have: code, parent, level, name, keywords, addressable
    ("FERROUS-CASTINGS", "DIR-METALS", 3, "Grey and SG iron castings", ["grey iron", "sg iron", "ductile iron", "cast iron", "foundry", "fg260"], True),
    ("MRO-LUBRICANTS", "IND-MRO", 3, "Lubricants and coolants", ["hydraulic oil", "gear oil", "grease", "cutting oil", "die lubricant", "way lube"], True),
    ("MRO-CHEMICALS", "IND-MRO", 3, "Chemicals and paints", ["degreaser", "degreasing", "thinner", "primer", "paint", "binder resin"], True),
    ("TOOLING", "IND-MRO", 3, "Dies, moulds and cutting tools", ["die set", "trim die", "core pin", "ejector pin", "carbide drill", "reamer", "gauge fixture"], True),
    ("IND-IT", "INDIRECT", 2, "IT and end-user computing", [], True),
    ("IT-HARDWARE", "IND-IT", 3, "IT hardware", ["laptop", "monitor", "network switch", "barcode printer", "desktop"], True),
    ("SOFTWARE-LICENCES", "IND-IT", 3, "Software licences and subscriptions", ["licence", "license", "subscription", "antivirus", "cad software"], True),
    ("IND-OFFICE", "INDIRECT", 2, "Office and workplace", [], True),
    ("OFFICE-SAFETY", "IND-OFFICE", 3, "Office and safety supplies", ["fire extinguisher", "toner", "stationery", "safety goggles", "ear plug"], True),
]

# Free-text descriptions (PO lines without material; some with material group ZMISC go through spend classification).
FREE_TEXT = {
    "MRO": ["Bearing 6205 ZZ and grease for press line", "Hydraulic hose assembly for HPDC cell", "Cylinder seal kit for trim press",
            "Abrasive discs and wire brushes", "Pneumatic fittings and PU tubes", "Maintenance spares for cooling tower pump",
            "V-belts and couplings for compressor", "Shop-floor consumables - cotton waste and gloves"],
    "MRO-LUBRICANTS": ["Hydraulic oil HLP 68 - 210 L barrels", "Die lubricant concentrate for HPDC", "Way lube oil and grease cartridges"],
    "MRO-CHEMICALS": ["Degreasing chemical for parts washer", "Paint thinner and primer for touch-up", "Binder resin for core shop"],
    "TOOLING": ["Trim die repair insert set", "Gauge fixture for knuckle inspection", "Carbide drill and reamer set", "Core pins and ejector pins for HPDC die"],
    "TOOLING-SERVICES": ["Die maintenance - HPDC die polishing and repair", "Repair of hydraulic press cylinder", "Spindle repair of VMC",
                         "Breakdown service - CNC turning centre"],
    "LOGISTICS": ["Freight charges Hosur to Pune FTL 32 ft", "Freight inward - steel bars Chennai to Oragadam", "Courier charges - document dispatch",
                  "Transport of castings Bidadi to Hosur - milk run", "Detention charges - trailer waiting at gate"],
    "IT-HARDWARE": ["Laptop for quality engineer", "24-inch monitors for design office", "Network switch for Bidadi plant", "Barcode printer for dispatch"],
    "SOFTWARE-LICENCES": ["CAD software licence renewal - 5 seats", "Antivirus subscription renewal", "MES cloud subscription - annual",
                          "Office productivity licences"],
    "IT-SERVICES": ["IT support - onsite engineer", "Network AMC - Hosur plant", "ERP basis support - monthly", "Cloud hosting charges"],
    "FACILITIES": ["Housekeeping services - Hosur plant", "Security guard services - additional shift", "Canteen services - Oragadam",
                   "Pest control services - quarterly", "Manpower supply - loading and unloading helpers"],
    "PROF-SERVICES": ["Statutory audit fee - interim", "Legal consultation - contract review", "Calibration of gauges - NABL lab",
                      "Material testing - chemical and tensile", "Training programme for quality team", "Consulting - lean manufacturing programme"],
    "CAPEX-MACHINERY": ["Vertical machining centre 850 mm - Bidadi line 3", "HPDC machine 800 T with extraction robot", "Screw air compressor 75 kW",
                        "Electric forklift 2.5 T", "Trim press 63 T for cell 4", "EOT crane 5 T for die shop"],
    "OFFICE-SAFETY": ["Fire extinguisher refilling", "Printer toner cartridges", "Stationery for stores", "Safety goggles and ear plugs"],
}
FI_TEXT = {
    "PROF-SERVICES": ["Professional fees - tax advisory", "Legal fees - arbitration matter", "Audit fee - statutory audit",
                      "Training programme - IATF internal auditor", "Consultancy fee - energy audit", "Professional fees - transfer pricing study"],
    "IT-SERVICES": ["Internet leased line charges", "Cloud subscription - email and collaboration", "Software support charges"],
    "FACILITIES": ["Annual maintenance contract - fire hydrant system", "Canteen services - festival lunch", "Pest control - annual contract"],
    "LOGISTICS": ["Courier charges - monthly", "Freight charges - urgent air shipment of samples"],
}
FI_ACCOUNT = {"PROF-SERVICES": "460100", "IT-SERVICES": "450100", "FACILITIES": "440100", "LOGISTICS": "430100"}

# Materials: category, MATKL, MTART, unit, price ₹ low/high per price unit, price unit, count, HSN/SAC by part, part names, specs
FAMILIES = [
    ("ALU-DIECAST", "BO-ALUDC", "ROH", "EA", 180, 2800, 1, 120, "761699",
     ["Gearbox housing", "Clutch housing", "Oil pump cover", "Transmission cover", "Motor end shield", "Steering column bracket",
      "Water pump body", "Thermostat housing", "Cylinder head cover", "Alternator bracket", "EV motor housing", "Inverter casing",
      "Oil sump", "Timing chain cover", "Brake caliper bracket"], ["ADC12", "A356", "LM24", "LM6"]),
    ("FERROUS-CASTINGS", "BO-FECST", "ROH", "EA", 120, 4500, 1, 100, None,
     ["Brake drum", "Flywheel housing", "Differential case", "Exhaust manifold", "Bearing cap", "Hub casting", "Pump body",
      "Crankcase cover", "Steering knuckle casting", "Engine mounting bracket"], ["FG260", "FG300", "SG400/15", "SG500/7"]),
    ("FORGINGS", "BO-FORG", "ROH", "EA", 90, 1800, 1, 110, "732619",
     ["Crankshaft forging", "Connecting rod forging", "Steering knuckle forging", "Front axle beam forging", "Gear blank forging",
      "Flange yoke forging", "Tie rod end forging", "Spindle forging", "Ring gear blank"], ["EN8", "EN19", "SAE4140", "20MnCr5", "C45"]),
    ("MACHINING", "BO-MACH", "ROH", "EA", 60, 1500, 1, 90, None,
     ["Input shaft machined", "Output shaft machined", "Pinion shaft", "Machined flange", "Machined bracket", "Spacer machined",
      "Sleeve machined", "Pump shaft machined"], ["EN8", "EN353", "SAE8620", "C45"]),
    ("RAW-MATERIALS", "RM-STEEL", "ROH", "KG", 62, 95, 1, 22, "722830",
     ["Alloy steel bar EN19", "Alloy steel bar 20MnCr5", "Alloy steel bar SAE4140", "Alloy steel bar EN353"], ["dia 32", "dia 40", "dia 55", "dia 65", "dia 80"]),
    ("RAW-MATERIALS", "RM-ALUIN", "ROH", "KG", 225, 260, 1, 4, "760120", ["Aluminium alloy ingot"], ["ADC12", "A356", "LM24", "LM6"]),
    ("RAW-MATERIALS", "RM-POLY", "ROH", "KG", 110, 320, 1, 9, None,
     ["Polyamide PA66 GF30 granules", "Polypropylene copolymer granules", "EPDM rubber compound"], ["natural", "black", "grade A"]),
    ("RAW-MATERIALS", "RM-NRUB", "ROH", "KG", 170, 210, 1, 3, "400122", ["Natural rubber ISNR 20", "Natural rubber ISNR 10", "Natural rubber ISNR 5"], [""]),
    ("FASTENERS", "BO-FAST", "ROH", "EA", 85, 4500, 100, 120, None,
     ["Hex bolt", "Hex flange bolt", "Socket head cap screw", "Hex nut", "Nyloc nut", "Plain washer", "Spring washer", "Stud",
      "Compression spring"], ["M6", "M8", "M10", "M12", "M14"]),
    ("RUBBER-SEALS", "BO-RUBB", "ROH", "EA", 4, 450, 1, 60, None,
     ["Engine mount rubber", "Bump stopper", "Grommet EPDM", "Radiator hose inlet", "Radiator hose outlet", "Fuel hose", "Rubber boot CV joint"],
     ["type A", "type B", "LH", "RH"]),
    ("RUBBER-SEALS", "BO-SEAL", "ROH", "EA", 2, 650, 1, 40, None,
     ["O-ring NBR", "Oil seal", "Gasket oil pan", "Cylinder head gasket MLS", "Valve stem seal"], ["32x2.5", "40x62x8", "55x72x10", "std"]),
    ("ELECTRONICS", "BO-ELEC", "ROH", "EA", 15, 2400, 1, 45, None,
     ["Connector 12-way sealed", "Relay 12V 40A", "Fuse blade 15A", "Reverse light switch", "Speed sensor hall type", "Oil pressure sensor"],
     ["black", "grey", "type 2", "type 3"]),
    ("ELECTRONICS", "BO-HARN", "ROH", "EA", 350, 6500, 1, 25, None,
     ["Wiring harness engine", "Wiring harness body", "Battery cable assembly", "Wiring harness EV traction"], ["LHD", "RHD", "variant 2"]),
    ("PACKAGING", "PK-PACK", "VERP", "EA", 45, 900, 1, 25, None,
     ["Plastic crate 600x400x300", "Stretch film roll 500 mm", "Thermal label roll 100x50", "BOPP tape 48 mm", "VCI poly bag 600x900"], ["blue", "grey", "std"]),
    ("MRO", "MR-BEAR", "HIBE", "EA", 120, 18000, 1, 50, None,
     ["Ball bearing", "Taper roller bearing", "V-belt", "Gear coupling"], ["6205 ZZ", "6306 2RS", "32008", "B-52", "size 4"]),
    ("MRO", "MR-TOOL", "HIBE", "EA", 150, 25000, 1, 40, None,
     ["Spanner double ended", "Angle grinder 4 inch", "Impact wrench 1/2 inch", "Torque wrench"], ["10-11", "17-19", "std", "heavy duty"]),
    ("MRO", "MR-ABRS", "HIBE", "EA", 30, 2500, 1, 35, None,
     ["Grinding wheel", "Emery paper", "Welding electrode E6013", "Flap disc"], ["180x6x22", "120 grit", "3.15 mm", "100 mm"]),
    ("MRO", "MR-HYDR", "HIBE", "EA", 450, 45000, 1, 40, None,
     ["Ball valve SS", "Pneumatic cylinder", "Solenoid valve 5/2", "Air filter element compressor"], ["1 inch", "50x100", "24V DC", "std"]),
    ("MRO", "MR-ELEC", "HIBE", "EA", 250, 60000, 1, 35, None,
     ["Induction motor", "Control cable 4C x 2.5", "Contactor 32A", "Dial gauge"], ["5.5 kW", "per metre", "3-pole", "0-10 mm"]),
    ("MRO-LUBRICANTS", "MR-LUBE", "HIBE", "L", 120, 450, 1, 20, None,
     ["Hydraulic oil ISO VG 68", "Gear oil EP 220", "Die release agent concentrate", "Soluble cutting oil", "Way lube oil ISO VG 68"], ["210 L", "50 L", "20 L"]),
    ("MRO-CHEMICALS", "MR-CHEM", "HIBE", "KG", 90, 650, 1, 15, None,
     ["Primer red oxide", "Thinner NC", "Alkaline degreaser", "Cold box binder part 1"], ["20 kg", "50 kg", "std"]),
    ("TOOLING", "TL-DIES", "FHMI", "SET", 250000, 4500000, 1, 15, "848041",
     ["HPDC die set", "Trim die set"], ["gearbox housing", "clutch housing", "oil pump cover", "motor end shield"]),
    ("TOOLING", "TL-CUTT", "FHMI", "EA", 850, 45000, 1, 45, None,
     ["Carbide drill", "Turning insert holder", "Tool holder BT40 ER32", "Reamer carbide"], ["8.5 mm", "PCLNR 2525", "std", "12 H7"]),
    ("IT-HARDWARE", "IT-HW", "NLAG", "EA", 9500, 95000, 1, 15, None,
     ["Laptop i5 16GB 512GB", "Monitor 24 inch", "Barcode label printer", "Network switch 24 port"], ["", "PoE", "industrial"]),
    ("OFFICE-SAFETY", "OF-SAFE", "NLAG", "EA", 250, 9500, 1, 15, None, ["Fire extinguisher ABC 6 kg", "Toner cartridge laser", "Fire extinguisher CO2 4.5 kg"], [""]),
    ("LOGISTICS", "SV-LOGI", "DIEN", "AU", 8500, 65000, 1, 14, None,
     ["Freight FTL 32 ft", "Freight 20 ft container", "Milk run trip", "Courier charges"], ["Hosur-Pune", "Hosur-Chennai port", "Bidadi-Hosur", "Oragadam-Bidadi"]),
    ("FACILITIES", "SV-FACL", "DIEN", "MON", 95000, 650000, 1, 12, None,
     ["Housekeeping services per month", "Security services per month", "Pest control services per month", "Manpower supply per month"],
     ["Hosur", "Oragadam", "Bidadi"]),
    ("IT-SERVICES", "SV-ITSV", "DIEN", "MON", 45000, 450000, 1, 8, None,
     ["IT onsite support per month", "Network management per month", "Leased line per month"], ["Hosur", "Oragadam", "Bidadi"]),
    ("SOFTWARE-LICENCES", "SV-SOFT", "DIEN", "AU", 25000, 900000, 1, 6, "997331", ["CAD licence annual", "MES subscription annual", "Antivirus licence annual"], ["", "seat pack"]),
    ("PROF-SERVICES", "SV-TEST", "DIEN", "AU", 450, 25000, 1, 8, "998346", ["Calibration per instrument", "Material testing per sample"], ["NABL", "std"]),
    ("PROF-SERVICES", "SV-PROF", "DIEN", "AU", 8500, 45000, 1, 6, None, ["Consulting per man-day", "Engineering design per day"], ["lean", "tooling"]),
    ("TOOLING-SERVICES", "SV-REPR", "DIEN", "AU", 6500, 185000, 1, 10, None,
     ["Die maintenance per visit", "Machine repair per call", "Installation of machine"], ["HPDC", "CNC", "press"]),
    ("IC-TRANSFER", "IC-GROUP", "ROH", "EA", 450, 3500, 1, 10, "848310", ["Machined spindle sub-assembly (group)", "Gear shaft sub-assembly (group)"], ["type A", "type B"]),
]
HSN_BY_PART = {
    "Brake drum": "732510", "Flywheel housing": "732510", "Differential case": "732599", "Exhaust manifold": "732510", "Bearing cap": "732510",
    "Hub casting": "732599", "Pump body": "732510", "Crankcase cover": "732510", "Steering knuckle casting": "732599",
    "Engine mounting bracket": "732599", "Input shaft machined": "848310", "Output shaft machined": "848310", "Pinion shaft": "848310",
    "Pump shaft machined": "848310", "Machined flange": "732690", "Machined bracket": "732690", "Spacer machined": "732690",
    "Sleeve machined": "732690", "Polyamide PA66 GF30 granules": "390810", "Polypropylene copolymer granules": "390210",
    "EPDM rubber compound": "400299", "Hex bolt": "731815", "Hex flange bolt": "731815", "Socket head cap screw": "731815", "Stud": "731815",
    "Hex nut": "731816", "Nyloc nut": "731816", "Plain washer": "731822", "Spring washer": "731821", "Compression spring": "732020",
    "Engine mount rubber": "401699", "Bump stopper": "401699", "Grommet EPDM": "401699", "Rubber boot CV joint": "401699",
    "Radiator hose inlet": "400931", "Radiator hose outlet": "400931", "Fuel hose": "400931", "O-ring NBR": "401693", "Oil seal": "401693",
    "Gasket oil pan": "401693", "Cylinder head gasket MLS": "848410", "Valve stem seal": "401693", "Connector 12-way sealed": "853669",
    "Relay 12V 40A": "853641", "Fuse blade 15A": "853610", "Reverse light switch": "853650", "Speed sensor hall type": "854370",
    "Oil pressure sensor": "902620", "Wiring harness engine": "854430", "Wiring harness body": "854430", "Battery cable assembly": "854449",
    "Wiring harness EV traction": "854430", "Plastic crate 600x400x300": "392310", "Stretch film roll 500 mm": "392010",
    "Thermal label roll 100x50": "482110", "BOPP tape 48 mm": "391910", "VCI poly bag 600x900": "392329",
    "Ball bearing": "848210", "Taper roller bearing": "848220", "V-belt": "401039", "Gear coupling": "848360",
    "Spanner double ended": "820411", "Angle grinder 4 inch": "846729", "Impact wrench 1/2 inch": "846729", "Torque wrench": "820412",
    "Grinding wheel": "680422", "Emery paper": "680520", "Welding electrode E6013": "831110", "Flap disc": "680520",
    "Ball valve SS": "848180", "Pneumatic cylinder": "841231", "Solenoid valve 5/2": "848180", "Air filter element compressor": "842139",
    "Induction motor": "850152", "Control cable 4C x 2.5": "854449", "Contactor 32A": "853649", "Dial gauge": "903180",
    "Hydraulic oil ISO VG 68": "271019", "Gear oil EP 220": "271019", "Die release agent concentrate": "340319", "Soluble cutting oil": "340319",
    "Way lube oil ISO VG 68": "271019", "Primer red oxide": "320890", "Thinner NC": "381400", "Alkaline degreaser": "340290",
    "Cold box binder part 1": "382410", "Carbide drill": "820750", "Turning insert holder": "820780", "Tool holder BT40 ER32": "846610",
    "Reamer carbide": "820760", "Laptop i5 16GB 512GB": "847130", "Monitor 24 inch": "852852", "Barcode label printer": "844332",
    "Network switch 24 port": "851762", "Fire extinguisher ABC 6 kg": "842410", "Fire extinguisher CO2 4.5 kg": "842410",
    "Toner cartridge laser": "844399", "Freight FTL 32 ft": "996791", "Freight 20 ft container": "996791", "Milk run trip": "996791",
    "Courier charges": "996812", "Housekeeping services per month": "998533", "Security services per month": "998525",
    "Pest control services per month": "998531", "Manpower supply per month": "998519", "IT onsite support per month": "998313",
    "Network management per month": "998316", "Leased line per month": "998414", "Consulting per man-day": "998311",
    "Engineering design per day": "998333", "Die maintenance per visit": "998717", "Machine repair per call": "998719",
    "Installation of machine": "998732",
}
FREE_TEXT_HSN = {"MRO": "848210", "MRO-LUBRICANTS": "271019", "MRO-CHEMICALS": "340290", "TOOLING": "820750", "TOOLING-SERVICES": "998717",
                 "LOGISTICS": "996791", "IT-HARDWARE": "847130", "SOFTWARE-LICENCES": "997331", "IT-SERVICES": "998313", "FACILITIES": "998533",
                 "PROF-SERVICES": "998311", "CAPEX-MACHINERY": "845710", "OFFICE-SAFETY": "842410"}
CAPEX_HSN = {"Vertical machining centre": "845710", "HPDC machine": "845430", "Screw air compressor": "841480", "Electric forklift": "842720",
             "Trim press": "846229", "EOT crane": "842611"}
SPECIAL = ("100198", "100211", "200202", "200203")   # duplicates / shared bank: kept out of the sourcing structures
VALUATION = {"ROH": "3000", "VERP": "3050", "HIBE": "3030", "FHMI": "3040", "NLAG": "", "DIEN": ""}

# ---------------------------------------------------------------- vendor naming (fictional)
WORDS = ["Thamarai", "Mullai", "Kurinji", "Marutham", "Neidhal", "Malligai", "Senthamarai", "Vetri", "Kalaivani", "Ilango", "Kanmani",
         "Poongodi", "Nilavu", "Mayil", "Arul", "Vaigai", "Noyyal", "Bhavani", "Amaravathi", "Tunga", "Hemavathi", "Sharavathi", "Kabini",
         "Netravathi", "Malaprabha", "Shivalik", "Aravali", "Sahyadri", "Annamalai", "Kolli", "Javadhu", "Yelagiri", "Pothigai", "Siruvani",
         "Kodai", "Valparai", "Thenmozhi", "Ezhil", "Sudar", "Oviya", "Kayal", "Iniya", "Agaram", "Magizh", "Sindhu", "Tamira", "Kapila",
         "Varuna", "Chitra", "Mukil", "Pavazham", "Muthu", "Vairam", "Ponni", "Sengol", "Kuyil", "Thendral", "Aruvi", "Sangam", "Kumari"]
TRADES = {
    "ALU-DIECAST": ["Pressure Diecasters", "Alloy Castings", "Aluminium Castings", "Diecast Industries"],
    "FERROUS-CASTINGS": ["Grey Iron Foundry", "SG Iron Castings", "Foundry Works", "Castings"],
    "FORGINGS": ["Forgings", "Drop Forge", "Precision Forgings", "Forge Works"],
    "MACHINING": ["Precision Engineering", "CNC Components", "Machine Works", "Precision Components"],
    "RAW-MATERIALS": ["Steels", "Metals and Alloys", "Polymers", "Alloys", "Rubber Traders"],
    "FASTENERS": ["Fasteners", "Bolts and Nuts", "Fastening Systems"],
    "RUBBER-SEALS": ["Rubber Products", "Seals and Gaskets", "Polymer Mouldings", "Rubber Industries"],
    "ELECTRONICS": ["Auto Electricals", "Wiring Harness", "Electronic Components", "Sensors", "Auto Electronics"],
    "PACKAGING": ["Packaging", "Plastic Crates", "Pack Solutions"],
    "MRO": ["Industrial Supplies", "Bearing House", "Tools and Hardware", "Hydraulics", "Engineering Stores", "Electricals"],
    "MRO-LUBRICANTS": ["Lubricants", "Oils and Chemicals"], "MRO-CHEMICALS": ["Chemicals", "Coatings"],
    "TOOLING": ["Tool Room", "Die and Mould Works", "Cutting Tools"], "TOOLING-SERVICES": ["Die Maintenance Services", "Machine Repairs"],
    "LOGISTICS": ["Roadways", "Transport Corporation", "Logistics", "Cargo Movers", "Freight Carriers"],
    "IT-HARDWARE": ["Computers", "Systems and Peripherals"], "SOFTWARE-LICENCES": ["Software Solutions", "Infosoft"],
    "IT-SERVICES": ["Infotech", "IT Services", "Networks"],
    "FACILITIES": ["Facility Services", "Security Services", "Housekeeping Services", "Pest Control", "Manpower Services"],
    "PROF-SERVICES": ["Consultants", "Testing Laboratories", "Advisory", "Calibration Services"],
    "CAPEX-MACHINERY": ["Machine Tools", "Compressors", "Material Handling Equipment", "Industrial Automation"],
    "OFFICE-SAFETY": ["Safety Equipments", "Office Solutions", "Fire Protection"],
}
PLACES = {  # GST state: [(city, PIN, street)]
    "33": [("Hosur", "635126", "SIDCO Industrial Estate"), ("Coimbatore", "641021", "Ganapathy Industrial Estate"),
           ("Coimbatore", "641014", "SIDCO Kurichi Industrial Estate"), ("Chennai", "600058", "Ambattur Industrial Estate"),
           ("Chennai", "600032", "Guindy Industrial Estate"), ("Sriperumbudur", "602105", "SIPCOT Industrial Park"),
           ("Ranipet", "632403", "SIPCOT Industrial Complex"), ("Madurai", "625008", "Kappalur Industrial Estate"),
           ("Tiruchirappalli", "620015", "BHEL Ancillary Estate"), ("Salem", "636004", "Suramangalam Industrial Area"),
           ("Gummidipoondi", "601201", "SIPCOT Industrial Complex"), ("Krishnagiri", "635115", "SIPCOT Industrial Park")],
    "29": [("Bengaluru", "560058", "Peenya Industrial Area"), ("Bengaluru", "560099", "Bommasandra Industrial Area"),
           ("Jigani", "562106", "KIADB Jigani Industrial Area"), ("Bidadi", "562109", "KIADB Industrial Area"),
           ("Tumakuru", "572106", "Antharasanahalli Industrial Area"), ("Mysuru", "570016", "Hebbal Industrial Area")],
    "27": [("Pune", "410501", "Chakan MIDC"), ("Pune", "411026", "Bhosari MIDC"), ("Aurangabad", "431136", "Waluj MIDC")],
    "06": [("Faridabad", "121003", "Sector 24 Industrial Area"), ("Gurugram", "122051", "IMT Manesar")],
    "24": [("Rajkot", "360004", "Aji Industrial Estate"), ("Ahmedabad", "382445", "GIDC Vatva")],
    "36": [("Hyderabad", "500037", "Balanagar Industrial Area")],
    "03": [("Ludhiana", "141003", "Focal Point Phase 5")],
}
STATE_MIX = {"direct": {"33": 0.55, "29": 0.22, "27": 0.10, "06": 0.05, "24": 0.04, "03": 0.04},
             "indirect": {"33": 0.62, "29": 0.25, "27": 0.07, "36": 0.06}}
BANKS = ["SBIN", "HDFC", "ICIC", "UTIB", "CNRB", "IOBA", "IDIB", "KVBL", "CIUB", "TMBL", "KKBK", "BARB", "PUNB", "UBIN", "INDB", "KARB"]


@dataclass
class Vendor:
    lifnr: str
    name: str
    category: str
    state: str
    city: str
    pin: str
    street: str
    pan: str
    gstin: str
    entity: str
    zterm: str
    erdat: date
    weight: float
    active_to: date = KEY_DATE
    sperr: str = ""
    loevm: str = ""
    bank: Optional[tuple] = None
    ktokk: str = "ZDOM"
    pan_field: Optional[str] = None
    gstin_field: Optional[str] = None
    plant: str = "1100"


@dataclass
class Mat:
    matnr: str
    desc: str
    category: str
    matkl: str
    mtart: str
    uom: str
    hsn: Optional[str]
    price: int            # current price per base unit, paise
    peinh: int
    plants: list
    weight: float
    vendors: list = field(default_factory=list)
    lvorm: str = ""
    qm: bool = False


def _money(minor: int) -> str:
    sign = "-" if minor < 0 else ""
    minor = abs(minor)
    return f"{sign}{minor // 100}.{minor % 100:02d}"


def _qty(q) -> str:
    return f"{q:.3f}"


def _gjahr(d: date) -> int:
    return d.year if d.month >= 4 else d.year - 1


def _poper(d: date) -> int:
    return (d.month - 4) % 12 + 1


def _months(start: date, end: date) -> list[date]:
    out, d = [], date(start.year, start.month, 1)
    while d <= end:
        out.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def _month_end(d: date) -> date:
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


SEASON = {1: 1.02, 2: 1.00, 3: 1.10, 4: 0.90, 5: 0.92, 6: 0.96, 7: 0.98, 8: 1.02, 9: 1.08, 10: 1.10, 11: 0.98, 12: 0.94}


def gst_rates() -> dict[str, list[int]]:
    """HSN/SAC prefix -> GST rates from the CBIC reference file (longest prefix wins, as services.gst.lookup)."""
    text = REFERENCE.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    rates: dict[str, set] = defaultdict(set)
    for row in csv.DictReader(io.StringIO(body)):
        for prefix in row["prefixes"].split():
            rates[prefix].add(int(row["gst_rate"]))
    return {k: sorted(v) for k, v in rates.items()}


def rate_of(rates: dict, code: str) -> Optional[int]:
    digits = "".join(c for c in code if c.isdigit())
    for n in range(len(digits), 3, -1):
        if digits[:n] in rates:
            return max(rates[digits[:n]])
    return None


class _Gen:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.rates = gst_rates()
        self.tables: dict[str, tuple[list[str], list[list]]] = {}
        self.vendors: list[Vendor] = []
        self.by_lifnr: dict[str, Vendor] = {}
        self.mats: list[Mat] = []
        self.by_matnr: dict[str, Mat] = {}
        self.agreements: list[dict] = []
        self.lines: list[dict] = []           # PO lines (EKPO, BSTYP F)
        self.invoices: list[dict] = []        # RBKP documents with RSEG lines
        self.fi: list[dict] = []              # FI vendor invoices (non-PO)
        self.ekbe: list[list] = []
        self.counters = defaultdict(int)

    # -------------------------------------------------------------- helpers
    def table(self, name: str, columns: list[str]):
        self.tables[name] = (columns, [])
        return self.tables[name][1]

    def num(self, key: str, start: int) -> int:
        self.counters[key] += 1
        return start + self.counters[key]

    def lognorm(self, sigma: float = 0.8) -> float:
        return math.exp(self.rng.gauss(0, sigma))

    def weighted(self, items: list, weights: list):
        return self.rng.choices(items, weights=weights, k=1)[0]

    def price_at(self, mat: Mat, d: date) -> int:
        """History price per base unit: inflation 3 %/year; aluminium and iron castings follow quarterly index steps."""
        years = (KEY_DATE - d).days / 365.0
        factor = 1 - 0.03 * years
        if mat.category in ("ALU-DIECAST", "FERROUS-CASTINGS", "RAW-MATERIALS"):
            quarter = (d.year * 12 + d.month - 1) // 3
            factor *= 1 + 0.012 * math.sin(quarter * 1.3)
        return max(1, int(round(mat.price * factor)))

    # -------------------------------------------------------------- organisation
    def org(self):
        t = self.table("T001", ["BUKRS", "BUTXT", "ORT01", "LAND1", "WAERS", "PERIV", "KTOPL", "PAN", "GSTIN"])
        t.append([BUKRS, COMPANY, "Coimbatore", "IN", "INR", "V3", "KACA", COMPANY_PAN, gstin("33", COMPANY_PAN)])
        t = self.table("T001W", ["WERKS", "NAME1", "BUKRS", "STRAS", "ORT01", "PSTLZ", "REGIO", "LAND1", "J_1BBRANCH", "GSTIN"])
        for werks, name, street, city, pin, state in PLANTS:
            t.append([werks, name, BUKRS, street, city, pin, state, "IN", "TN01" if state == "33" else "KA01", gstin(state, COMPANY_PAN)])
        t = self.table("CSKS", ["KOKRS", "KOSTL", "DATAB", "DATBI", "BUKRS", "WERKS", "KOSAR", "VERAK", "KTEXT", "LTEXT"])
        for kostl, werks, kosar, text, person in COST_CENTERS:
            t.append(["1000", kostl, "2015-04-01", "9999-12-31", BUKRS, werks, kosar, person, text[:20], text])
        t = self.table("PRPS", ["POSID", "POST1", "PSPHI", "PBUKR", "WERKS", "STUFE", "BELKZ"])
        for posid, text, project, werks in WBS:
            t.append([posid, text, project, BUKRS, werks, "2", "X"])
        t = self.table("T052", ["ZTERM", "ZTAG1", "ZPRZ1", "TEXT1"])
        for key, days, text in TERMS:
            t.append([key, str(days), "0.000", text])
        t = self.table("T007S", ["MWSKZ", "TEXT1", "RATE", "GST_TYPE"])
        for code, text, rate, kind in TAX_CODES:
            t.append([code, text, f"{rate}.00", kind])
        t = self.table("T023T", ["MATKL", "SPRAS", "WGBEZ"])
        m = self.table("PIC_MAP_MATKL", ["MATKL", "PIC_CATEGORY", "NOTE"])
        for code, text, category in MATKL:
            t.append([code, "E", text])
            if category is not None:
                m.append([code, category, "mapping workshop 2026-10-14" if category != "UNCLASSIFIED" else "classified by the PIC spend classifier"])
        x = self.table("PIC_MAP_TAXONOMY", ["CATEGORY", "PARENT", "LEVEL", "NAME", "KEYWORDS", "ADDRESSABLE"])
        for code, parent, level, name, keywords, addressable in TAXONOMY_EXT:
            x.append([code, parent, str(level), name, ";".join(keywords), "X" if addressable else ""])

    # -------------------------------------------------------------- vendors
    def _pan(self, entity: str, first: str) -> str:
        letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
        while True:
            pan = "".join(self.rng.choice(letters) for _ in range(3)) + entity + first + f"{self.rng.randrange(1000, 9999)}" + self.rng.choice(letters)
            if pan not in self._pans:
                self._pans.add(pan)
                return pan

    def _vendor(self, lifnr: str, category: str, *, name: str = None, state: str = None, weight: float = 1.0, erdat: date = None,
                ktokk: str = "ZDOM") -> Vendor:
        direct = category in ("ALU-DIECAST", "FERROUS-CASTINGS", "FORGINGS", "MACHINING", "RAW-MATERIALS", "FASTENERS", "RUBBER-SEALS",
                              "ELECTRONICS", "PACKAGING")
        if state is None:
            mix = STATE_MIX["direct" if direct else "indirect"]
            state = self.weighted(list(mix), list(mix.values()))
        city, pin, street = self.rng.choice(PLACES[state])
        if name is None:
            while True:
                form = self.weighted(["Pvt Ltd", "LLP", "PROP", "Ltd"], [0.66, 0.08, 0.21, 0.05])
                word = self.rng.choice(WORDS) if self.rng.random() < 0.75 else city
                trade = self.rng.choice(TRADES[category])
                if form == "PROP":
                    name = f"Sri {word} {trade}" if self.rng.random() < 0.5 else f"{word} {trade} Enterprises"
                else:
                    name = f"{word} {trade} {form}"
                if name not in self._names:
                    break
        self._names.add(name)
        entity = "C" if ("Pvt Ltd" in name or name.endswith(" Ltd")) else ("F" if "LLP" in name else "P")
        pan = self._pan(entity, name.replace("Sri ", "")[0].upper() if entity != "P" else self.rng.choice("ABCDEFGHJKLMNPRSTV"))
        zterm = self.weighted(["Z030", "Z045", "Z060", "Z015"], [0.35, 0.25, 0.1, 0.3] if direct else [0.35, 0.1, 0.05, 0.5])
        v = Vendor(lifnr=lifnr, name=name, category=category, state=state, city=city, pin=pin, street=f"No. {self.rng.randrange(2, 240)}, {street}",
                   pan=pan, gstin=gstin(state, pan), entity=entity, zterm=zterm, erdat=erdat or date(2016 + self.rng.randrange(0, 8), self.rng.randrange(1, 13), 1),
                   weight=weight, ktokk=ktokk, plant=self.weighted(list(PLANT_WEIGHTS), list(PLANT_WEIGHTS.values())))
        bank = self.rng.choice(BANKS)
        v.bank = (f"{bank}0K{self.rng.randrange(10000, 99999)}", str(self.rng.randrange(10 ** 10, 10 ** 14)), name)
        self.vendors.append(v)
        self.by_lifnr[lifnr] = v
        return v

    def vendors_(self):
        self._pans, self._names = set(), set()
        n_direct, n_service = 100000, 200000
        for category, cfg in CATS.items():
            if category == "IC-TRANSFER":
                v = self._vendor("900001", category, name="Kaveri Precision Tooling Pvt Ltd", state="33", weight=1.0, ktokk="ZICO")
                v.zterm = "Z030"
                continue
            service = cfg["service"] or category in ("MRO", "MRO-LUBRICANTS", "MRO-CHEMICALS", "TOOLING", "IT-HARDWARE", "CAPEX-MACHINERY", "OFFICE-SAFETY")
            for i in range(cfg["vendors"]):
                if service:
                    n_service += 1
                    lifnr = str(n_service)
                else:
                    n_direct += 1
                    lifnr = str(n_direct)
                weight = 1 / (i + 1) ** 1.1
                late = self.rng.random() < 0.10
                self._vendor(lifnr, category, weight=weight,
                             erdat=date(2025, self.rng.randrange(1, 13), self.rng.randrange(1, 28)) if late else None)
        # duplicates for the MDM duplicate scan
        base = self.by_lifnr["100031"]
        dup_name = base.name.replace("Pvt Ltd", "Private Limited") if "Pvt Ltd" in base.name else f"{base.name} - Unit 2"
        dup = self._vendor("100198", base.category, name=dup_name, state=base.state, weight=0.4, erdat=date(2025, 8, 12))
        dup.pan, dup.gstin, dup.city, dup.pin, dup.street = base.pan, base.gstin, base.city, base.pin, base.street
        base2 = self.by_lifnr["100047"]
        other_state = "29" if base2.state != "29" else "33"
        ka = self._vendor("100211", base2.category, name=f"{base2.name} - {'Bengaluru' if other_state == '29' else 'Hosur'} Unit",
                          state=other_state, weight=0.5, erdat=date(2025, 2, 3))
        ka.pan = base2.pan
        ka.gstin = gstin(other_state, base2.pan)
        self._vendor("200201", "MRO", name="Mullai Industrial Supplies", state="33", weight=0.5)
        self._vendor("200202", "MRO", name="Mullai Industrial Suppliers", state="33", weight=0.3, erdat=date(2025, 11, 4))
        shared = self._vendor("200203", "LOGISTICS", name="Ezhil Cargo Movers", state="33", weight=0.3, erdat=date(2026, 3, 9))
        shared.bank = (self.by_lifnr["200052"].bank[0], self.by_lifnr["200052"].bank[1], shared.name)
        # vendors the loader must reject (tax ID errors)
        for lifnr, category, name, problem in (("200301", "MRO", "Kumari Engineering Works", "missing"),
                                               ("200302", "LOGISTICS", "Kuyil Transport", "missing"),
                                               ("200303", "PACKAGING", "Varuna Packaging Industries", "check"),
                                               ("200304", "MRO", "Kapila Tools and Hardware", "pan"),
                                               ("200305", "TOOLING", "Sengol Cutting Tools", "state")):
            v = self._vendor(lifnr, category, name=name, state="33", weight=0.05)
            if problem == "missing":
                v.gstin_field = ""
            elif problem == "check":
                wrong = "0" if v.gstin[14] != "0" else "1"
                v.gstin_field = v.gstin[:14] + wrong
            elif problem == "pan":
                v.pan_field = v.pan[:5] + f"{(int(v.pan[5:9]) + 1) % 10000:04d}" + v.pan[9]
            elif problem == "state":
                first14 = f"39{v.pan}1Z"
                v.gstin_field = first14 + gstin_check_char(first14)
        # blocked and inactive vendors
        blocked = ["100012", "100025", "100058", "200017", "200044", "200071"]
        for lifnr, day in zip(blocked, [date(2026, 5, 18), date(2026, 2, 9), date(2025, 12, 1), date(2026, 7, 6), date(2026, 4, 20), date(2025, 10, 13)]):
            v = self.by_lifnr[lifnr]
            v.sperr, v.active_to = "X", day
        for lifnr, day in zip(["100019", "100066", "200023", "200063", "200096"],
                              [date(2025, 6, 30), date(2025, 3, 31), date(2025, 5, 31), date(2025, 8, 31), date(2025, 1, 31)]):
            v = self.by_lifnr[lifnr]
            v.loevm, v.active_to, v.bank = "X", day, None
        for lifnr in ("200009", "200038", "200087"):
            self.by_lifnr[lifnr].bank = None          # new service vendors paid by cheque / no bank data yet
        self.by_lifnr["200081"].bank = ("HDFC0K1234", self.by_lifnr["200081"].bank[1], self.by_lifnr["200081"].name)

        lfa1 = self.table("LFA1", ["LIFNR", "KTOKK", "NAME1", "NAME2", "SORTL", "ADRNR", "LAND1", "STCD3", "J_1IPANNO", "SPERR", "SPERM",
                                   "LOEVM", "ERDAT"])
        adrc = self.table("ADRC", ["ADDRNUMBER", "NAME1", "STREET", "STR_SUPPL1", "CITY1", "POST_CODE1", "REGION", "COUNTRY", "SMTP_ADDR", "TEL_NUMBER"])
        lfb1 = self.table("LFB1", ["LIFNR", "BUKRS", "AKONT", "ZTERM", "ZWELS", "REPRF", "SPERR", "LOEVM", "ERDAT"])
        lfbk = self.table("LFBK", ["LIFNR", "BANKS", "BANKL", "BANKN", "KOINH", "BVTYP"])
        for v in sorted(self.vendors, key=lambda x: x.lifnr):
            adrnr = f"{9000000 + int(v.lifnr) % 1000000:010d}"
            name1, name2 = (v.name[:40], v.name[40:80]) if len(v.name) > 40 else (v.name, "")
            lfa1.append([v.lifnr.zfill(10), v.ktokk, name1, name2, v.name.upper()[:10], adrnr, "IN",
                         v.gstin if v.gstin_field is None else v.gstin_field, v.pan if v.pan_field is None else v.pan_field,
                         v.sperr, v.sperr if v.lifnr in ("100012", "200017") else "", v.loevm, v.erdat.isoformat()])
            slug = "".join(ch for ch in v.name.lower().replace("pvt ltd", "").replace("private limited", "") if ch.isalnum())[:24]
            adrc.append([adrnr, name1, v.street, "", v.city, v.pin, v.state, "IN", f"accounts@{slug}.example", ""])
            lfb1.append([v.lifnr.zfill(10), BUKRS, "160000", v.zterm, "T", "X", v.sperr, v.loevm, v.erdat.isoformat()])
            if v.bank:
                lfbk.append([v.lifnr.zfill(10), "IN", v.bank[0], v.bank[1], v.bank[2][:60], "0001"])

    # -------------------------------------------------------------- materials
    def materials_(self):
        counters = defaultdict(int)
        bases = {"BO-ALUDC": 21000000, "BO-FECST": 21500000, "BO-FORG": 22000000, "BO-MACH": 23000000, "RM-STEEL": 11000000, "RM-ALUIN": 11100000,
                 "RM-POLY": 11200000, "RM-NRUB": 11300000, "BO-FAST": 24000000, "BO-RUBB": 25000000, "BO-SEAL": 25500000, "BO-ELEC": 26000000,
                 "BO-HARN": 26500000, "PK-PACK": 31000000, "MR-BEAR": 41000000, "MR-TOOL": 41000000, "MR-ABRS": 41000000, "MR-HYDR": 41000000,
                 "MR-ELEC": 41000000, "MR-LUBE": 42000000, "MR-CHEM": 42500000, "TL-DIES": 43000000, "TL-CUTT": 43500000, "IT-HW": 44000000,
                 "OF-SAFE": 45000000, "SV-LOGI": 51000000, "SV-FACL": 51100000, "SV-ITSV": 51200000, "SV-SOFT": 51300000, "SV-TEST": 51400000,
                 "SV-PROF": 51500000, "SV-REPR": 51600000, "IC-GROUP": 27000000}
        seen_desc = set()
        for category, matkl, mtart, uom, lo, hi, peinh, count, hsn, parts, specs in FAMILIES:
            base_key = bases[matkl]
            for i in range(count):
                counters[base_key] += 1
                matnr = str(base_key + counters[base_key])
                part = self.rng.choice(parts)
                spec = self.rng.choice(specs)
                drawing = f"{matkl[3:5]}-{self.rng.randrange(1000, 9999)}" if mtart in ("ROH", "VERP") and category != "RAW-MATERIALS" else ""
                desc = " ".join(x for x in (part, spec, drawing) if x)[:40]
                while desc in seen_desc:
                    desc = " ".join(x for x in (part, spec) if x)[:35] + f" {self.rng.randrange(100, 999)}"
                seen_desc.add(desc)
                code = hsn or HSN_BY_PART[part]
                rupees = math.exp(self.rng.uniform(math.log(lo), math.log(hi)))
                # price per base unit in paise; per 100 units (fasteners) the price is whole rupees, so the unit price stays in paise
                price = int(round(rupees)) if peinh == 100 else int(round(rupees * 100))
                home = self.weighted(list(PLANT_WEIGHTS), list(PLANT_WEIGHTS.values()))
                plants = [home]
                if self.rng.random() < 0.25:
                    plants.append(self.rng.choice([p for p in PLANT_WEIGHTS if p != home]))
                if mtart in ("HIBE", "NLAG", "DIEN", "FHMI") and self.rng.random() < 0.5:
                    plants = [home] + [p for p in PLANT_WEIGHTS if p != home]
                mat = Mat(matnr=matnr, desc=desc, category=category, matkl=matkl, mtart=mtart, uom=uom, hsn=code, price=price, peinh=peinh,
                          plants=plants, weight=self.lognorm(1.0),
                          qm=category in ("ALU-DIECAST", "FERROUS-CASTINGS", "FORGINGS", "MACHINING", "ELECTRONICS") and self.rng.random() < 0.6)
                self.mats.append(mat)
                self.by_matnr[matnr] = mat
        # rejects and deletion flags
        for matnr, change in (("41000198", "nohsn"), ("41000199", "nohsn"), ("41000200", "badhsn"), ("41000197", "uom"), ("41000196", "matkl")):
            mat = self.by_matnr.get(matnr)
            if mat is None:
                continue
            if change == "nohsn":
                mat.hsn = None
            elif change == "badhsn":
                mat.hsn = "999999"
            elif change == "uom":
                mat.uom = "XYZ"
            else:
                mat.matkl = "ZOLD"
        for matnr in ("41000101", "41000150", "25000044", "43500030", "26000012"):
            if matnr in self.by_matnr:
                self.by_matnr[matnr].lvorm = "X"
        # vendor assignment (info records): primary + secondary
        by_cat = defaultdict(list)
        for v in self.vendors:
            if v.lifnr.startswith("2003") or v.lifnr in SPECIAL:
                continue
            by_cat[v.category].append(v)
        for mat in self.mats:
            pool = by_cat[mat.category]
            primary = self.weighted(pool, [v.weight for v in pool])
            mat.vendors = [primary.lifnr]
            if len(pool) > 1 and self.rng.random() < 0.30:
                second = self.weighted([v for v in pool if v is not primary], [v.weight for v in pool if v is not primary])
                mat.vendors.append(second.lifnr)
        # the special vendors get a few materials so their spend has a material history
        for lifnr, donor in (("100198", "100031"), ("100211", "100047"), ("200202", "200201"), ("200203", "200052")):
            for mat in [m for m in self.mats if donor in m.vendors][:3]:
                mat.vendors.append(lifnr)
        for lifnr in ("200301", "200302", "200303", "200304", "200305"):
            category = self.by_lifnr[lifnr].category
            for mat in [m for m in self.mats if m.category == category and not m.lvorm][-2:]:
                mat.vendors.append(lifnr)

        mara = self.table("MARA", ["MATNR", "MTART", "MATKL", "MEINS", "MFRPN", "BRGEW", "GEWEI", "LVORM", "ERSDA"])
        makt = self.table("MAKT", ["MATNR", "SPRAS", "MAKTX"])
        marc = self.table("MARC", ["MATNR", "WERKS", "DISMM", "DISPO", "BESKZ", "PLIFZ", "WEBAZ", "EISBE", "DISLS", "BSTFE", "BSTMI", "BSTMA",
                                   "STEUC", "QMATV", "LVORM"])
        mbew = self.table("MBEW", ["MATNR", "BWKEY", "BKLAS", "VPRSV", "STPRS", "VERPR", "PEINH"])
        for mat in self.mats:
            cfg = CATS[mat.category]
            erdat = date(2014 + self.rng.randrange(0, 11), self.rng.randrange(1, 13), self.rng.randrange(1, 28))
            weight = f"{self.rng.uniform(0.05, 12):.3f}" if mat.mtart == "ROH" and mat.uom == "EA" else ""
            mara.append([mat.matnr, mat.mtart, mat.matkl, mat.uom, f"KAC-{mat.matnr[-5:]}" if mat.mtart == "ROH" else "", weight,
                         "KG" if weight else "", mat.lvorm, erdat.isoformat()])
            makt.append([mat.matnr, "E", mat.desc])
            for werks in mat.plants:
                if mat.mtart == "DIEN" or mat.mtart == "NLAG":
                    dismm, disls, eisbe = "ND", "", "0"
                elif mat.mtart in ("HIBE", "FHMI"):
                    dismm, disls, eisbe = "VB", "HB", str(self.rng.randrange(2, 40))
                else:
                    dismm = "PD"
                    disls = "FX" if self.rng.random() < 0.3 else "EX"
                    eisbe = str(self.rng.randrange(0, 5) * 50)
                bstfe = str(self.rng.choice([500, 1000, 2000])) if disls == "FX" else ""
                plifz = self.rng.randint(*cfg["lead"])
                marc.append([mat.matnr, werks, dismm, "P01" if dismm == "PD" else "", "F", str(plifz), "1" if mat.qm else "0", eisbe, disls,
                             bstfe, "", "", mat.hsn or "", "X" if mat.qm else "", mat.lvorm])
                if mat.mtart not in ("DIEN", "NLAG"):
                    vprsv = "S" if mat.mtart in ("ROH", "VERP") else "V"
                    unit_price = mat.price * mat.peinh
                    mbew.append([mat.matnr, werks, VALUATION[mat.mtart], vprsv, _money(unit_price) if vprsv == "S" else "0.00",
                                 _money(unit_price) if vprsv == "V" else "0.00", str(mat.peinh)])

    # -------------------------------------------------------------- sourcing: info records and source lists
    def sourcing_(self):
        eina = self.table("EINA_EINE", ["INFNR", "LIFNR", "MATNR", "EKORG", "WERKS", "ESOKZ", "NETPR", "PEINH", "WAERS", "APLFZ", "MINBM",
                                        "LOEKZ", "DATLB"])
        n = 5300000000
        for mat in self.mats:
            if mat.lvorm:
                continue
            for k, lifnr in enumerate(mat.vendors):
                n += 1
                drift = 1.0 if k == 0 else self.rng.uniform(1.01, 1.06)
                price = round(mat.price * drift) * mat.peinh
                if mat.matnr == "11000003" and k == 0:
                    price = 0                                   # info record without a price: PRICE_INVALID
                eina.append([str(n), lifnr.zfill(10), mat.matnr, "1000", mat.plants[0], "0", _money(price), str(mat.peinh), "INR",
                             str(self.rng.randint(*CATS[mat.category]["lead"])), "", "",
                             date(2026, self.rng.randrange(1, 10), self.rng.randrange(1, 28)).isoformat()])

    # -------------------------------------------------------------- outline agreements (scheduling agreements, contracts)
    def agreements_(self):
        sa_counts = {"ALU-DIECAST": 7, "FERROUS-CASTINGS": 5, "FORGINGS": 5, "MACHINING": 3, "RUBBER-SEALS": 2, "ELECTRONICS": 2}
        mk_slots = [("RAW-MATERIALS", "RM-STEEL"), ("RAW-MATERIALS", "RM-STEEL"), ("RAW-MATERIALS", "RM-STEEL"), ("RAW-MATERIALS", "RM-ALUIN"),
                    ("RAW-MATERIALS", "RM-ALUIN"), ("RAW-MATERIALS", "RM-POLY"), ("RAW-MATERIALS", "RM-NRUB"), ("FASTENERS", "BO-FAST"),
                    ("FASTENERS", "BO-FAST"), ("PACKAGING", "PK-PACK")]
        wk_slots = [("LOGISTICS", "SV-LOGI"), ("LOGISTICS", "SV-LOGI"), ("FACILITIES", "SV-FACL"), ("FACILITIES", "SV-FACL"),
                    ("IT-SERVICES", "SV-ITSV"), ("PROF-SERVICES", "SV-TEST")]
        sa_no, ct_no = 5500000100, 4600000100
        used_vendor_plant = set()
        self.sa_items: dict[tuple, dict] = {}     # (matnr, werks) -> agreement item (active SA of that date resolved later)
        index = 0
        for category, count in sa_counts.items():
            pool = sorted([v for v in self.vendors if v.category == category and not v.lifnr.startswith("2003") and not v.sperr and not v.loevm
                           and v.lifnr not in SPECIAL and v.erdat <= date(2023, 4, 1)], key=lambda v: -v.weight)
            made = 0
            for v in pool:
                if made >= count:
                    break
                mats = [m for m in self.mats if m.vendors and m.vendors[0] == v.lifnr and not m.lvorm]
                by_plant = defaultdict(list)
                for m in mats:
                    by_plant[m.plants[0]].append(m)
                plant = max(by_plant, key=lambda p: len(by_plant[p])) if by_plant else None
                if plant is None or (v.lifnr, plant) in used_vendor_plant:
                    continue
                items = sorted(by_plant[plant], key=lambda m: -m.weight)[:self.rng.randint(2, 4)]
                if len(items) < 2:
                    extra = [m for m in self.mats if m.category == category and m.plants[0] == plant and m not in items and not m.lvorm
                             and m.matnr not in {i.matnr for i in items}][:2 - len(items)]
                    for m in extra:
                        m.vendors.insert(0, v.lifnr)
                    items += extra
                used_vendor_plant.add((v.lifnr, plant))
                two_year = index < 14
                generations = ([(date(2023, 4, 1), date(2025, 3, 31)), (date(2025, 4, 1), date(2027, 3, 31))] if two_year
                               else [(date(2024, 4, 1), date(2026, 3, 31)), (date(2026, 4, 1), date(2027, 9, 30))])
                for start, end in generations:
                    sa_no += 1
                    self.agreements.append({"ebeln": str(sa_no), "bstyp": "L", "bsart": "LP", "lifnr": v.lifnr, "werks": plant, "start": start,
                                            "end": end, "category": category, "items": [{"mat": m, "ebelp": 10 * (k + 1)} for k, m in enumerate(items)],
                                            "index": category in ("ALU-DIECAST", "FERROUS-CASTINGS")})
                index += 1
                made += 1
        for kind, slots in (("MK", mk_slots), ("WK", wk_slots)):
            for category, matkl in slots:
                pool = sorted([v for v in self.vendors if v.category == category and not v.lifnr.startswith("2003") and not v.sperr and not v.loevm
                               and v.lifnr not in SPECIAL and v.erdat <= date(2024, 4, 1)
                               and not any(a["lifnr"] == v.lifnr and a["bstyp"] == "K" for a in self.agreements)], key=lambda v: -v.weight)
                v = pool[0]
                mats = [m for m in self.mats if m.matkl == matkl and not m.lvorm]
                own = [m for m in mats if v.lifnr in m.vendors] or mats
                items = sorted(own, key=lambda m: -m.weight)[:self.rng.randint(2, 5)]
                for m in items:
                    if v.lifnr not in m.vendors:
                        m.vendors.insert(0, v.lifnr)
                for start, end in ((date(2024, 4, 1), date(2025, 3, 31)), (date(2025, 4, 1), date(2026, 3, 31)), (date(2026, 4, 1), date(2027, 3, 31))):
                    ct_no += 1
                    self.agreements.append({"ebeln": str(ct_no), "bstyp": "K", "bsart": kind, "lifnr": v.lifnr, "werks": v.plant, "start": start,
                                            "end": end, "category": category, "items": [{"mat": m, "ebelp": 10 * (k + 1)} for k, m in enumerate(items)],
                                            "index": False})
        # conditions (A016/KONP): quarterly for index-linked castings, otherwise per agreement year
        for a in self.agreements:
            for item in a["items"]:
                periods = []
                if a["index"]:
                    d = a["start"]
                    while d <= a["end"]:
                        q_end = _month_end(date(d.year, ((d.month - 1) // 3) * 3 + 3, 1))
                        if q_end >= KEY_DATE or q_end >= a["end"]:
                            periods.append((d, a["end"]))
                            break
                        periods.append((d, q_end))
                        d = q_end + timedelta(days=1)
                else:
                    d = a["start"]
                    while d <= a["end"]:
                        y_end = min(a["end"], date(d.year + 1 if d.month >= 4 else d.year, 3, 31))
                        periods.append((d, y_end))
                        d = y_end + timedelta(days=1)
                item["conditions"] = [(s, e, round(self.price_at(item["mat"], s) * 0.97) if a["bstyp"] == "L" else self.price_at(item["mat"], s))
                                      for s, e in periods]
                item["released_qty"] = 0
        # one agreement with a validity typo (end before start): VALIDITY_INVALID
        broken = dict(self.agreements[-1])
        broken.update(ebeln="5500000999", bstyp="L", bsart="LP", start=date(2026, 9, 1), end=date(2026, 3, 31), index=False,
                      items=[{"mat": self.agreements[0]["items"][0]["mat"], "ebelp": 10, "conditions": [(date(2026, 9, 1), date(2026, 3, 31), 100)],
                              "released_qty": 0}], lifnr=self.agreements[0]["lifnr"], werks=self.agreements[0]["werks"], category=self.agreements[0]["category"])
        self.agreements.append(broken)
        self.sa_index = defaultdict(list)
        for a in self.agreements:
            for item in a["items"]:
                self.sa_index[(item["mat"].matnr, a["werks"])].append((a, item))

    def agreement_for(self, matnr: str, werks: str, d: date, bstyp: str = None):
        for a, item in self.sa_index.get((matnr, werks), []):
            if a["start"] <= d <= a["end"] and a["start"] <= a["end"] and (bstyp is None or a["bstyp"] == bstyp):
                return a, item
        return None, None

    def condition(self, item: dict, d: date) -> int:
        for s, e, p in item["conditions"]:
            if s <= d <= e:
                return p
        return item["conditions"][-1][2]

    # -------------------------------------------------------------- transactions
    def _vendor_active(self, v: Vendor, d: date) -> bool:
        return v.erdat <= d <= v.active_to

    def _invoice_dates(self, gr: date) -> tuple[date, date]:
        bldat = gr - timedelta(days=self.rng.randrange(0, 3))
        budat = gr + timedelta(days=self.rng.choice([0, 0, 1, 1, 2, 3]))
        return bldat, budat

    def transactions_(self):
        months = _months(ORDERS_FROM, KEY_DATE)
        cat_vendors = defaultdict(list)
        for v in self.vendors:
            cat_vendors[v.category].append(v)
        cat_mats = defaultdict(list)
        for m in self.mats:
            if not m.lvorm and m.matkl != "ZOLD":
                cat_mats[m.category].append(m)
        sa_cats = {a["category"] for a in self.agreements if a["bstyp"] == "L"}
        deliveries = []      # (agreement, items with qty, gr date)
        po_lines = []        # dicts
        for mi, month in enumerate(months):
            growth = 0.93 + 0.14 * mi / max(1, len(months) - 1)
            for category, cfg in CATS.items():
                target = cfg["cr"] * CR / 12 * SEASON[month.month] * growth * self.rng.uniform(0.94, 1.06)
                sa_target = target * cfg["sa"] if category in sa_cats else 0
                ct_target = target * cfg["ct"]
                fi_target = target * cfg["fi"]
                po_target = target - sa_target - ct_target - fi_target
                # scheduling-agreement deliveries
                if sa_target:
                    active = [a for a in self.agreements if a["bstyp"] == "L" and a["category"] == category and a["start"] <= month <= a["end"]
                              and a["start"] <= a["end"] and self._vendor_active(self.by_lifnr[a["lifnr"]], month)]
                    weights = [sum(i["mat"].weight for i in a["items"]) for a in active]
                    for a, w in zip(active, weights):
                        value = sa_target * w / sum(weights)
                        for half in (0, 1):
                            gr = month + timedelta(days=self.rng.randrange(3, 13) + 14 * half)
                            items = []
                            for item in a["items"]:
                                share = item["mat"].weight / w
                                price = self.condition(item, gr)
                                qty = max(10, int(round(value / 2 * share / price / 10)) * 10)
                                items.append((item, qty, price))
                            deliveries.append((a, items, gr))
                # contract releases and standard POs
                for kind, budget in (("CT", ct_target), ("PO", po_target)):
                    if budget <= 0:
                        continue
                    n = max(1, int(round(budget / (cfg["line"] * LAKH))))
                    weights = [self.lognorm(0.7) for _ in range(n)]
                    total_w = sum(weights)
                    for w in weights:
                        value = budget * w / total_w
                        bedat = month + timedelta(days=self.rng.randrange(0, 28))
                        line = self._po_line(category, cfg, kind, value, bedat, cat_vendors, cat_mats)
                        if line:
                            po_lines.append(line)
            # non-PO FI invoices
            for category, cfg in CATS.items():
                if month < HISTORY_FROM:
                    break
                if not cfg["fi"]:
                    continue
                fi_target = cfg["cr"] * CR / 12 * SEASON[month.month] * growth * cfg["fi"]
                n = max(1, int(round(fi_target / (0.9 * LAKH))))
                pool = [v for v in cat_vendors[category] if not v.lifnr.startswith("2003")]
                for _ in range(n):
                    v = self.weighted(pool, [x.weight for x in pool])
                    day = month + timedelta(days=self.rng.randrange(0, 28))
                    if not self._vendor_active(v, day):
                        continue
                    amount = int(fi_target / n * self.lognorm(0.5))
                    self.fi.append({"vendor": v, "bldat": day, "budat": day + timedelta(days=self.rng.randrange(0, 4)), "net": amount,
                                    "text": self.rng.choice(FI_TEXT[category]), "account": FI_ACCOUNT[category],
                                    "kostl": self.rng.choice(["9100", "9200", "9300", "9400", "1130", "1230"])})
        self._build_documents(deliveries, po_lines)

    def _po_line(self, category, cfg, kind, value, bedat, cat_vendors, cat_mats):
        rng = self.rng
        material = None
        contract = item = None
        if kind == "CT":
            active = [a for a in self.agreements if a["bstyp"] == "K" and a["category"] == category and a["start"] <= bedat <= a["end"]]
            if not active:
                return None
            contract = rng.choice(active)
            item = rng.choice(contract["items"])
            material = item["mat"]
            vendor = self.by_lifnr[contract["lifnr"]]
            werks = contract["werks"] if material.mtart in ("DIEN",) else rng.choice(material.plants)
            price = self.condition(item, bedat)
        else:
            free = rng.random() < cfg["ft"] or not cat_mats[category]
            if free:
                pool = [v for v in cat_vendors[category] if self._vendor_active(v, bedat)]
                if not pool:
                    return None
                vendor = self.weighted(pool, [v.weight for v in pool])
                werks = vendor.plant if rng.random() < 0.8 else self.weighted(list(PLANT_WEIGHTS), list(PLANT_WEIGHTS.values()))
                price = None
            else:
                mats = cat_mats[category]
                for _ in range(8):
                    material = self.weighted(mats, [m.weight for m in mats])
                    werks = rng.choice(material.plants)
                    a, _i = self.agreement_for(material.matnr, werks, bedat, "L")
                    if a is None or rng.random() < 0.05:        # SA-covered materials: only occasional spot buys (off contract)
                        break
                else:
                    return None
                candidates = [self.by_lifnr[x] for x in material.vendors if self._vendor_active(self.by_lifnr[x], bedat)]
                if not candidates:
                    return None
                vendor = candidates[0] if rng.random() < 0.8 else rng.choice(candidates)
                price = self.price_at(material, bedat)
                if a is not None and len(candidates) > 1:
                    vendor = candidates[-1]
        if not self._vendor_active(vendor, bedat):
            return None
        if material is None:
            text = rng.choice(FREE_TEXT[category])
            matkl = "ZMISC" if rng.random() < 0.35 and category != "CAPEX-MACHINERY" else CAT_MATKL.get(category, "ZMISC")
            uom = "AU" if cfg["service"] else "EA"
            qty = 1 if cfg["service"] or category == "CAPEX-MACHINERY" else rng.randint(1, 12)
            price = max(100_00, int(value / qty))
            hsn = FREE_TEXT_HSN.get(category, "848210")
            if category == "CAPEX-MACHINERY":
                hsn = next(code for key, code in CAPEX_HSN.items() if text.startswith(key))
        else:
            text, matkl, uom, hsn = material.desc, material.matkl, material.uom, material.hsn
            if material.uom in ("EA", "SET", "AU", "MON"):
                qty = max(1, int(round(value / price)))
                if material.peinh == 100:
                    qty = max(100, int(round(qty / 100)) * 100)
            else:
                qty = max(10, int(round(value / price / 10)) * 10)
        if material is not None and material.mtart == "DIEN" or (material is None and cfg["service"]):
            knttp = "K"
        elif material is None:
            knttp = cfg["knttp"] or "K"
        else:
            knttp = ""
        lead = rng.randint(*cfg["lead"])
        return {"category": category, "vendor": vendor, "material": material, "text": text, "matkl": matkl, "uom": uom, "qty": qty,
                "price": price, "werks": werks, "bedat": bedat, "eindt": bedat + timedelta(days=lead), "knttp": knttp, "hsn": hsn,
                "contract": contract, "citem": item, "service": bool(cfg["service"] or (material is not None and material.mtart == "DIEN")),
                "retro": cfg["service"] and kind == "PO" and rng.random() < 0.06}

    def _tax(self, vendor: Vendor, werks: str, hsn: Optional[str]) -> tuple[str, int]:
        rate = rate_of(self.rates, hsn or "") or 18
        plant_state = next(p[5] for p in PLANTS if p[0] == werks)
        return (("S" if vendor.state == plant_state else "I") + ("5" if rate == 5 else "8")), rate

    def _build_documents(self, deliveries, po_lines):
        rng = self.rng
        # group PO lines into PO headers: vendor, plant, ISO week, contract
        groups = defaultdict(list)
        for line in po_lines:
            # one order per vendor, plant and month (up to 8 lines); from October 2026 the buyers order twice a month
            iso = (line["bedat"].year, line["bedat"].month * 10 + (line["bedat"].day > 15 if line["bedat"] >= date(2026, 10, 1) else 0))
            key = (line["vendor"].lifnr, line["werks"], iso[0], iso[1], line["contract"]["ebeln"] if line["contract"] else "", line["knttp"] == "P",
                   line["retro"])
            groups[key].append(line)
        pos = []
        for key in sorted(groups, key=lambda k: (min(l["bedat"] for l in groups[k]), k)):
            lines = groups[key]
            for start in range(0, len(lines), 8):
                chunk = lines[start:start + 8]
                bedat = min(l["bedat"] for l in chunk)
                pos.append({"lines": chunk, "bedat": bedat, "vendor": chunk[0]["vendor"], "werks": chunk[0]["werks"], "contract": chunk[0]["contract"]})
        ebeln = 4500010000
        mblnr = defaultdict(lambda: 5000000000)
        for po in pos:
            ebeln += 1
            po["ebeln"] = str(ebeln)
            for k, line in enumerate(po["lines"]):
                line["ebeln"], line["ebelp"] = po["ebeln"], 10 * (k + 1)
                line["bedat_planned"], line["bedat"] = line["bedat"], po["bedat"]
                line["gr"] = []          # (date, qty, mblnr, gjahr)
                line["ir"] = []          # (rseg dict)
        # receipts and invoices per PO
        self.events = []
        for po in pos:
            v = po["vendor"]
            for line in po["lines"]:      # delivery dates counted from the order date of the monthly order
                line["eindt"] = po["bedat"] + (line["eindt"] - line["bedat_planned"])
            lead_end = max(l["eindt"] for l in po["lines"])
            gr_day = lead_end + timedelta(days=rng.choice([-2, -1, 0, 0, 0, 1, 2, 3, 5, 8]))
            gr_day = max(gr_day, po["bedat"])
            partial = rng.random() < (0.35 if po["bedat"] >= date(2026, 10, 1) else 0.06)   # October: split deliveries
            batches = [(gr_day, 1.0)] if not partial else [(gr_day, rng.uniform(0.5, 0.8)), (gr_day + timedelta(days=rng.randrange(7, 21)), None)]
            for bi, (day, share) in enumerate(batches):
                if day > KEY_DATE:          # orders placed before a vendor block are still delivered and billed
                    continue
                items = []
                for line in po["lines"]:
                    if line.get("pre_window"):
                        continue            # billed before the history window: the line is not part of the extract
                    if line["service"]:
                        qty = line["qty"] if bi == 0 else 0
                    else:
                        received = sum(q for _, q, _, _ in line["gr"])
                        qty = line["qty"] - received if share is None else max(1, int(line["qty"] * share))
                        qty = min(qty, line["qty"] - received)
                    if qty <= 0:
                        continue
                    if not line["service"]:
                        gj = _gjahr(day)
                        mblnr[gj] += 1
                        line["gr"].append((day, qty, str(mblnr[gj]), gj))
                    items.append((line, qty))
                if items:
                    self._invoice(v, po["werks"], day, [(line, qty, line["price"]) for line, qty in items], retro=any(l["retro"] for l, _ in items))
        for a, items, gr in deliveries:
            if gr > KEY_DATE:
                continue
            v = self.by_lifnr[a["lifnr"]]
            if not self._vendor_active(v, gr):
                continue
            lines = []
            for item, qty, price in items:
                gj = _gjahr(gr)
                mblnr[gj] += 1
                sa_line = {"ebeln": a["ebeln"], "ebelp": item["ebelp"], "material": item["mat"], "text": item["mat"].desc, "matkl": item["mat"].matkl,
                           "uom": item["mat"].uom, "werks": a["werks"], "hsn": item["mat"].hsn, "knttp": "", "service": False, "category": a["category"],
                           "sa": True, "gr": [(gr, qty, str(mblnr[gj]), gj)], "ir": []}
                item["released_qty"] += qty
                self.ekbe_gr.append(sa_line)
                lines.append((sa_line, qty, price))
            self._invoice(v, a["werks"], gr, lines)
        self.pos = pos

    def _invoice(self, vendor: Vendor, werks: str, gr: date, lines: list, retro: bool = False):
        bldat, budat = self._invoice_dates(gr)
        if budat > KEY_DATE or budat < HISTORY_FROM:
            if budat < HISTORY_FROM:
                for line, _, _ in lines:
                    line["pre_window"] = True
            return
        doc = {"vendor": vendor, "werks": werks, "bldat": bldat, "budat": budat, "lines": []}
        for line, qty, price in lines:
            amount = qty * price
            if not line.get("sa") and self.rng.random() < 0.03:
                amount = int(amount * self.rng.uniform(1.01, 1.04))    # invoiced above the PO price (price variance)
            code, rate = self._tax(vendor, werks, line["hsn"])
            rseg = {"line": line, "qty": qty, "net": amount, "mwskz": code, "rate": rate, "shkzg": "S"}
            doc["lines"].append(rseg)
            line["ir"].append(rseg)
            if retro and not line.get("sa"):
                line["bedat_override"] = bldat + timedelta(days=self.rng.randrange(1, 6))
        self.invoices.append(doc)
        # occasional credit memo (return of a part of the delivery) 2-6 weeks later
        if self.rng.random() < 0.015 and not any(l["line"]["service"] for l in doc["lines"]):
            first = doc["lines"][0]
            credit_day = budat + timedelta(days=self.rng.randrange(14, 42))
            if credit_day <= KEY_DATE - timedelta(days=60):
                qty = max(1, first["qty"] // 20)
                net = int(first["net"] * qty / first["qty"])
                memo = {"vendor": vendor, "werks": werks, "bldat": credit_day, "budat": credit_day, "credit": True,
                        "lines": [{"line": first["line"], "qty": qty, "net": net, "mwskz": first["mwskz"], "rate": first["rate"], "shkzg": "H"}]}
                first["line"]["ir"].append(memo["lines"][0])
                self.invoices.append(memo)

    # -------------------------------------------------------------- write PO / invoice tables
    def write_transactions(self):
        rng = self.rng
        ekko = self.table("EKKO", ["EBELN", "BUKRS", "BSTYP", "BSART", "LIFNR", "EKORG", "EKGRP", "BEDAT", "KDATB", "KDATE", "KTWRT", "ZTERM",
                                   "INCO1", "INCO2", "WAERS", "ERNAM", "LOEKZ"])
        ekpo = self.table("EKPO", ["EBELN", "EBELP", "LOEKZ", "MATNR", "TXZ01", "MATKL", "WERKS", "LGORT", "MENGE", "KTMNG", "MEINS", "NETPR",
                                   "PEINH", "NETWR", "KNTTP", "PSTYP", "MWSKZ", "J_1BNBM", "WEPOS", "REPOS", "WEBRE", "ELIKZ", "EREKZ", "KONNR",
                                   "KTPNR", "UEBTO", "UNTTO"])
        konp = self.table("A016_KONP", ["EVRTN", "EVRTP", "KSCHL", "DATAB", "DATBI", "KBETR", "KPEIN", "KMEIN", "KONWA", "KNUMH"])
        eord = self.table("EORD", ["MATNR", "WERKS", "ZEORD", "VDATU", "BDATU", "LIFNR", "FLIFN", "EBELN", "EBELP", "AUTET"])
        ekkn = self.table("EKKN", ["EBELN", "EBELP", "ZEKKN", "SAKTO", "KOSTL", "POSID"])
        eket = self.table("EKET", ["EBELN", "EBELP", "ETENR", "EINDT", "MENGE", "WEMNG"])
        ekbe = self.table("EKBE", ["EBELN", "EBELP", "VGABE", "GJAHR", "BELNR", "BUZEI", "BWART", "BUDAT", "MENGE", "DMBTR", "WAERS", "SHKZG"])
        knumh = 1000000
        eord_seq = defaultdict(int)
        buyers = {"direct": "PUR_DIRECT", "indirect": "PUR_INDIRECT"}
        for po in self.pos:                      # quantities released against contracts (MK/WK) by purchase orders
            for line in po["lines"]:
                if line["citem"] is not None and not line.get("pre_window"):
                    line["citem"]["released_qty"] += line["qty"]
        for a in sorted(self.agreements, key=lambda x: x["ebeln"]):
            v = self.by_lifnr[a["lifnr"]]
            value = 0
            for item in a["items"]:
                mat = item["mat"]
                months = max(1, (a["end"].year - a["start"].year) * 12 + a["end"].month - a["start"].month + 1)
                elapsed = max(1, min(months, (min(KEY_DATE, a["end"]).year - a["start"].year) * 12 + min(KEY_DATE, a["end"]).month - a["start"].month + 1))
                expected = item["released_qty"] * months / elapsed       # planned volume over the whole validity
                ktmng = max(int(round(expected * 1.1 / 10)) * 10, 10) if mat.uom not in ("MON", "AU") else max(int(round(expected * 1.1)), 1)
                item["ktmng"] = ktmng
                current = item["conditions"][-1][2]
                value += ktmng * current
                ekpo.append([a["ebeln"], f"{item['ebelp']:05d}", "", mat.matnr, mat.desc, mat.matkl, a["werks"], "0001", "0.000", _qty(ktmng),
                             mat.uom, _money(current * mat.peinh), str(mat.peinh), "0.00", "K" if mat.mtart == "DIEN" else "", "0",
                             self._tax(v, a["werks"], mat.hsn)[0], mat.hsn or "", "" if mat.mtart == "DIEN" else "X", "X", "X", "", "",
                             "", "", "2.0" if a["bstyp"] == "L" else "0.0", "5.0" if a["bstyp"] == "L" else "0.0"])
                for s, e, p in item["conditions"]:
                    knumh += 1
                    konp.append([a["ebeln"], f"{item['ebelp']:05d}", "PB00", s.isoformat(), e.isoformat(), _money(p * mat.peinh), str(mat.peinh), mat.uom,
                                 "INR", str(knumh)])
                if a["bstyp"] == "L" and a["start"] <= a["end"]:
                    eord_seq[(mat.matnr, a["werks"])] += 1
                    eord.append([mat.matnr, a["werks"], f"{eord_seq[(mat.matnr, a['werks'])]:05d}", a["start"].isoformat(), a["end"].isoformat(),
                                 a["lifnr"].zfill(10), "X" if a["end"] >= KEY_DATE else "", a["ebeln"], f"{item['ebelp']:05d}", "1"])
            a["value"] = value
            ekko.append([a["ebeln"], BUKRS, a["bstyp"], a["bsart"], a["lifnr"].zfill(10), "1000", "D01" if a["bstyp"] == "L" else "D02",
                         a["start"].isoformat(), a["start"].isoformat(), a["end"].isoformat(), _money(value) if a["bsart"] == "WK" else "0.00",
                         v.zterm, "FCA" if a["bstyp"] == "L" else "", v.city if a["bstyp"] == "L" else "", "INR", buyers["direct"], ""])
        # source lists for multi-sourced direct materials without an agreement
        for mat in self.mats:
            if mat.lvorm or len(mat.vendors) < 2 or mat.mtart != "ROH":
                continue
            if any(self.sa_index.get((mat.matnr, w)) for w in mat.plants):
                continue
            for lifnr in mat.vendors[:2]:
                eord_seq[(mat.matnr, mat.plants[0])] += 1
                eord.append([mat.matnr, mat.plants[0], f"{eord_seq[(mat.matnr, mat.plants[0])]:05d}", "2025-04-01", "9999-12-31", lifnr.zfill(10),
                             "", "", "", "1"])
        # purchase orders
        self.open_lines = []
        for po in self.pos:
            lines = [l for l in po["lines"] if not l.get("pre_window")]
            if not lines:
                continue
            v = po["vendor"]
            bedat = min(l.get("bedat_override", l["bedat"]) for l in lines)
            direct = v.lifnr.startswith("1")
            ekko.append([po["ebeln"], BUKRS, "F", "NB", v.lifnr.zfill(10), "1000", "D01" if direct else "I01", bedat.isoformat(), "", "", "0.00",
                         v.zterm, "FCA" if direct else "", v.city if direct else "", "INR", buyers["direct" if direct else "indirect"], ""])
            for line in lines:
                mat = line["material"]
                received = sum(q for _, q, _, _ in line["gr"])
                invoiced = sum(r["qty"] if r["shkzg"] == "S" else 0 for r in line["ir"])
                complete = (received >= line["qty"]) if not line["service"] else bool(line["ir"])
                final = complete and (invoiced >= received if not line["service"] else True)
                peinh = mat.peinh if mat else 1
                ekpo.append([po["ebeln"], f"{line['ebelp']:05d}", "", mat.matnr if mat else "", line["text"][:40], line["matkl"], line["werks"],
                             "" if line["knttp"] else "0001", _qty(line["qty"]), "0.000", line["uom"], _money(line["price"] * peinh), str(peinh),
                             _money(line["qty"] * line["price"]), line["knttp"], "0", self._tax(v, line["werks"], line["hsn"])[0], line["hsn"] or "",
                             "" if line["service"] else "X", "X", "" if line["service"] else "X", "X" if complete else "",
                             "X" if final else "", line["contract"]["ebeln"] if line["contract"] else "",
                             f"{line['citem']['ebelp']:05d}" if line["contract"] else "", "0.0", "0.0"])
                if line["knttp"]:
                    account = CATS[line["category"]]["gl"]
                    if line["knttp"] == "P":
                        wbs = [w for w in WBS if w[3] == line["werks"]] or WBS
                        ekkn.append([po["ebeln"], f"{line['ebelp']:05d}", "01", account, "", self.rng.choice(wbs)[0]])
                    else:
                        kostl = self._kostl(line)
                        ekkn.append([po["ebeln"], f"{line['ebelp']:05d}", "01", account, kostl, ""])
                if not final:           # open for delivery or for invoice: the loader loads it as an open PO line
                    self.open_lines.append(line)
                    eket.append([po["ebeln"], f"{line['ebelp']:05d}", "0001", line["eindt"].isoformat(), _qty(line["qty"]), _qty(received)])
                for day, qty, doc, gj in line["gr"]:
                    ekbe.append([po["ebeln"], f"{line['ebelp']:05d}", "1", str(gj), doc, "0001", "101", day.isoformat(), _qty(qty),
                                 _money(qty * line["price"]), "INR", "S"])
        for line in self.ekbe_gr:
            if line.get("pre_window"):
                continue
            for day, qty, doc, gj in line["gr"]:
                price = line["ir"][0]["net"] // max(1, line["ir"][0]["qty"]) if line["ir"] else 0
                ekbe.append([line["ebeln"], f"{line['ebelp']:05d}", "1", str(gj), doc, "0001", "101", day.isoformat(), _qty(qty),
                             _money(qty * price), "INR", "S"])

    def _kostl(self, line) -> str:
        plant_cc = {"1100": ["1110", "1120", "1130", "1140"], "1200": ["1210", "1220", "1230", "1240"], "1300": ["1310", "1320", "1330"]}
        category = line["category"]
        if category in ("IT-HARDWARE", "SOFTWARE-LICENCES", "IT-SERVICES"):
            return "9200"
        if category in ("FACILITIES", "OFFICE-SAFETY"):
            return self.rng.choice(["9300", plant_cc[line["werks"]][3 if line["werks"] != "1300" else 2]])
        if category == "PROF-SERVICES":
            return self.rng.choice(["9400", plant_cc[line["werks"]][2]])
        if category == "LOGISTICS":
            return plant_cc[line["werks"]][3] if line["werks"] != "1300" else "1310"
        return plant_cc[line["werks"]][1]

    def write_invoices(self):
        rbkp = self.table("RBKP", ["BELNR", "GJAHR", "BUKRS", "BLART", "BLDAT", "BUDAT", "XBLNR", "LIFNR", "WAERS", "RMWWR", "WMWST1", "ZTERM",
                                   "ZFBDT", "XRECH", "STBLG", "RBSTAT"])
        rseg = self.table("RSEG", ["BELNR", "GJAHR", "BUZEI", "EBELN", "EBELP", "MATNR", "WERKS", "MENGE", "BSTME", "WRBTR", "SHKZG", "MWSKZ"])
        bseg = self.table("BSEG_KR", ["BUKRS", "BELNR", "GJAHR", "BUZEI", "BLART", "BLDAT", "BUDAT", "XBLNR", "LIFNR", "HKONT", "KOSTL", "WRBTR",
                                      "MWSKZ", "WMWST", "SGTXT", "WAERS"])
        ekbe = self.tables["EKBE"][1]
        belnr = defaultdict(lambda: 5105600000)
        fi_no = defaultdict(lambda: 1900000000)
        xblnr_seq = defaultdict(int)
        self.ap_items = []           # every vendor document (for BSIK/BSAK)
        self.spend_rows = []         # (period, account, amount) for the GL totals
        docs = sorted(self.invoices, key=lambda d: (d["budat"], d["vendor"].lifnr, d["bldat"]))
        for doc in docs:
            v = doc["vendor"]
            gj = _gjahr(doc["budat"])
            belnr[gj] += 1
            doc["belnr"], doc["gjahr"] = str(belnr[gj]), gj
            fy = f"{_gjahr(doc['bldat']) % 100:02d}-{(_gjahr(doc['bldat']) + 1) % 100:02d}"
            xblnr_seq[(v.lifnr, fy)] += 1
            initials = "".join(w[0] for w in v.name.replace("Sri ", "").split()[:3]).upper()
            doc["xblnr"] = f"{initials}/{'CN' if doc.get('credit') else ''}{fy}/{xblnr_seq[(v.lifnr, fy)]:04d}"[:16]
            net = tax = 0
            for k, r in enumerate(doc["lines"], start=1):
                line = r["line"]
                r["buzei"] = k
                t = int(round(r["net"] * r["rate"] / 100))
                net += r["net"]
                tax += t
                mat = line["material"]
                rseg.append([doc["belnr"], str(gj), f"{k:06d}", line["ebeln"], f"{line['ebelp']:05d}", mat.matnr if mat else "", line["werks"],
                             _qty(r["qty"]), line["uom"], _money(r["net"]), r["shkzg"], r["mwskz"]])
                ekbe.append([line["ebeln"], f"{line['ebelp']:05d}", "2", str(gj), doc["belnr"], f"{k:04d}", "", doc["budat"].isoformat(), _qty(r["qty"]),
                             _money(r["net"]), "INR", r["shkzg"]])
                account = "191100" if not line["knttp"] else CATS[line["category"]]["gl"]
                sign = -1 if r["shkzg"] == "H" else 1
                self.spend_rows.append((doc["budat"], account, sign * r["net"], r))
            sign = -1 if doc.get("credit") else 1
            doc["gross"] = net + tax
            rbkp.append([doc["belnr"], str(gj), BUKRS, "RE", doc["bldat"].isoformat(), doc["budat"].isoformat(), doc["xblnr"], v.lifnr.zfill(10),
                         "INR", _money(net + tax), _money(tax), v.zterm, doc["bldat"].isoformat(), "" if doc.get("credit") else "X", "", "5"])
            self.ap_items.append({"bukrs": BUKRS, "vendor": v, "gjahr": gj, "belnr": doc["belnr"], "blart": "RE", "bldat": doc["bldat"],
                                  "budat": doc["budat"], "xblnr": doc["xblnr"], "gross": sign * (net + tax), "zterm": v.zterm,
                                  "ebeln": doc["lines"][0]["line"]["ebeln"], "doc": doc})
        for doc in sorted(self.fi, key=lambda d: (d["budat"], d["vendor"].lifnr)):
            v = doc["vendor"]
            gj = _gjahr(doc["budat"])
            fi_no[gj] += 1
            doc["belnr"] = str(fi_no[gj])
            fy = f"{_gjahr(doc['bldat']) % 100:02d}-{(_gjahr(doc['bldat']) + 1) % 100:02d}"
            xblnr_seq[(v.lifnr, fy)] += 1
            initials = "".join(w[0] for w in v.name.replace("Sri ", "").split()[:3]).upper()
            doc["xblnr"] = f"{initials}/{fy}/{xblnr_seq[(v.lifnr, fy)]:04d}"[:16]
            code, rate = self._tax(v, "1100", "998311")
            tax = int(round(doc["net"] * rate / 100))
            bseg.append([BUKRS, doc["belnr"], str(gj), "002", "KR", doc["bldat"].isoformat(), doc["budat"].isoformat(), doc["xblnr"],
                         v.lifnr.zfill(10), doc["account"], doc["kostl"], _money(doc["net"]), code, _money(tax), doc["text"], "INR"])
            self.spend_rows.append((doc["budat"], doc["account"], doc["net"], doc))
            self.ap_items.append({"bukrs": BUKRS, "vendor": v, "gjahr": gj, "belnr": doc["belnr"], "blart": "KR", "bldat": doc["bldat"],
                                  "budat": doc["budat"], "xblnr": doc["xblnr"], "gross": doc["net"] + tax, "zterm": v.zterm, "ebeln": "", "doc": doc})

    # -------------------------------------------------------------- open and cleared items, payments
    def payments_(self):
        bsik = self.table("BSIK", ["BUKRS", "LIFNR", "GJAHR", "BELNR", "BUZEI", "BLART", "BLDAT", "BUDAT", "XBLNR", "WAERS", "WRBTR", "DMBTR",
                                   "SHKZG", "ZFBDT", "ZTERM", "ZBD1T", "ZLSPR", "EBELN", "QBSHB"])
        bsak = self.table("BSAK", ["BUKRS", "LIFNR", "GJAHR", "BELNR", "BUZEI", "BLART", "BLDAT", "BUDAT", "XBLNR", "WAERS", "WRBTR", "DMBTR",
                                   "SHKZG", "ZFBDT", "ZTERM", "ZBD1T", "ZLSPR", "EBELN", "QBSHB", "AUGDT", "AUGBL"])
        days = {k: d for k, d, _ in TERMS}
        clearing = defaultdict(lambda: 1500000000)
        run_docs = {}
        blocked_items = set()
        recent = [i for i in self.ap_items if i["gross"] > 0 and KEY_DATE - timedelta(days=75) <= i["bldat"] <= KEY_DATE - timedelta(days=50)]
        for item in recent[::max(1, len(recent) // 6)][:6]:
            blocked_items.add(item["belnr"] + str(item["gjahr"]))      # price dispute: payment block R, overdue at cutover
        self.open_items = []
        for item in sorted(self.ap_items, key=lambda i: (i["budat"], i["belnr"])):
            v = item["vendor"]
            due = item["bldat"] + timedelta(days=days[item["zterm"]])
            pay = due
            while pay.weekday() not in (1, 4):
                pay += timedelta(days=1)
            key = item["belnr"] + str(item["gjahr"])
            zlspr = "R" if key in blocked_items else ""
            if v.sperr and item["budat"] >= v.active_to - timedelta(days=40):
                zlspr = "A"
            shkzg = "S" if item["gross"] < 0 else "H"
            row = [item["bukrs"], v.lifnr.zfill(10), str(item["gjahr"]), item["belnr"], "001", item["blart"], item["bldat"].isoformat(),
                   item["budat"].isoformat(), item["xblnr"], "INR", _money(abs(item["gross"])), _money(abs(item["gross"])), shkzg,
                   item["bldat"].isoformat(), item["zterm"], str(days[item["zterm"]]), zlspr, item["ebeln"], "0.00"]
            last_of_reject = v.lifnr == "200303" and item is max((i for i in self.ap_items if i["vendor"].lifnr == "200303"),
                                                                 key=lambda i: (i["budat"], i["belnr"]))
            if pay <= KEY_DATE and not zlspr and not last_of_reject:
                run_key = (pay, v.lifnr)
                if run_key not in run_docs:
                    gj = _gjahr(pay)
                    clearing[gj] += 1
                    run_docs[run_key] = str(clearing[gj])
                bsak.append(row + [pay.isoformat(), run_docs[run_key]])
            else:
                bsik.append(row)
                self.open_items.append((item, row))
        # the duplicate posting: a supplier invoice posted twice (second RE document with the same XBLNR), both open
        candidates = [(i, r) for i, r in self.open_items if i["blart"] == "RE" and i["gross"] > 0 and i["budat"] <= KEY_DATE - timedelta(days=5)
                      and i["vendor"].lifnr.startswith("1") and not i["vendor"].sperr and i["vendor"].lifnr not in SPECIAL]
        original, src_row = next(((i, r) for i, r in candidates if i["vendor"].lifnr == "100074"), candidates[0])
        gj = original["gjahr"]
        dup_belnr = str(5105690001)
        row = list(src_row)
        row[3] = dup_belnr
        row[7] = (original["budat"] + timedelta(days=2)).isoformat()
        bsik.append(row)
        self.duplicate = {"belnr": dup_belnr, "gjahr": gj, "of": original["belnr"], "xblnr": original["xblnr"],
                          "vendor": original["vendor"].lifnr, "gross": original["gross"]}
        rbkp = self.tables["RBKP"][1]
        src = next(r for r in rbkp if r[0] == original["belnr"] and r[1] == str(gj))
        rbkp.append([dup_belnr, str(gj), BUKRS, "RE", src[4], row[7], src[6], src[7], "INR", src[9], src[10], src[11], src[12], "X", "", "5"])
        rseg = self.tables["RSEG"][1]
        for r in [r for r in rseg if r[0] == original["belnr"] and r[1] == str(gj)]:
            rseg.append([dup_belnr] + r[1:])
        ekbe = self.tables["EKBE"][1]
        for r in [r for r in ekbe if r[2] == "2" and r[4] == original["belnr"] and r[3] == str(gj)]:
            ekbe.append(r[:4] + [dup_belnr] + r[5:7] + [row[7]] + r[8:])

    # -------------------------------------------------------------- deliberate errors
    def inject_(self):
        rseg = self.tables["RSEG"][1]
        ekpo = self.tables["EKPO"][1]
        # three lines with a negative quantity (2025-06, 2025-12, 2026-04), small MRO amounts
        def small_rows(month: str, limit: int):
            return [r for r in rseg if r[10] == "S" and int(r[9].replace(".", "")) < limit and self._rbkp_period(r) == month and r[5].startswith("41")]
        self.injected = {"negativeQty": [], "unknownMaterial": [], "unknownPo": [], "duplicateRow": []}
        for month in ("2025-06", "2025-12", "2026-04"):
            r = small_rows(month, 80_000_00)[0]
            r[7] = "-" + r[7]
            self.injected["negativeQty"].append(f"{r[0]}/{r[1]}/{r[2]}")
        for month, matnr in (("2025-09", "41999999"), ("2026-02", "29999999")):
            r = small_rows(month, 60_000_00)[1]
            ebeln, ebelp = r[3], r[4]
            r[5] = matnr
            for p in ekpo:
                if p[0] == ebeln and p[1] == ebelp:
                    p[3] = matnr
            self.injected["unknownMaterial"].append(f"{r[0]}/{r[1]}/{r[2]}")
        r = small_rows("2026-01", 60_000_00)[2]
        r[3] = "4500999999"
        self.injected["unknownPo"].append(f"{r[0]}/{r[1]}/{r[2]}")
        r = small_rows("2025-07", 60_000_00)[3]
        rseg.append(list(r))
        self.injected["duplicateRow"].append(f"{r[0]}/{r[1]}/{r[2]}")
        # open PO lines: quantity 0, negative price, unknown material
        open_keys = {(l["ebeln"], f"{l['ebelp']:05d}") for l in self.open_lines}
        open_rows = [p for p in ekpo if p[0].startswith("45") and (p[0], p[1]) in open_keys and p[21] == "" and p[3].startswith("4")
                     and p[23] == "" and int(p[13].replace(".", "")) < 2 * LAKH and not p[4].startswith(("HPDC", "Trim die"))]
        open_rows.sort(key=lambda p: (p[0], p[1]))
        open_rows[0][8] = "0.000"
        open_rows[1][11] = "-" + open_rows[1][11]
        open_rows[2][3] = "41999999"
        self.injected["openPo"] = [f"{p[0]}/{p[1]}" for p in open_rows[:3]]

    def _rbkp_period(self, rseg_row) -> str:
        if not hasattr(self, "_rbkp_budat"):
            self._rbkp_budat = {(r[0], r[1]): r[5][:7] for r in self.tables["RBKP"][1]}
        return self._rbkp_budat.get((rseg_row[0], rseg_row[1]), "")

    # -------------------------------------------------------------- GL totals, balances, reconciling items
    def gl_(self):
        totals = defaultdict(int)
        rbkp_budat = {(r[0], r[1]): r[5] for r in self.tables["RBKP"][1]}
        seen = set()
        for r in self.tables["RSEG"][1]:
            key = (r[0], r[1], r[2])
            if key in seen:            # the row extracted twice is one posting in the GL
                continue
            seen.add(key)
            budat = date.fromisoformat(rbkp_budat[(r[0], r[1])])
            ebeln, ebelp = r[3], r[4]
            account = self._account_of(ebeln, ebelp)
            amount = int(r[9].replace(".", "").replace("-", "")) * (-1 if r[10] == "H" else 1)
            totals[(_gjahr(budat), _poper(budat), account)] += amount
        for r in self.tables["BSEG_KR"][1]:
            budat = date.fromisoformat(r[6])
            totals[(_gjahr(budat), _poper(budat), r[9])] += int(r[11].replace(".", ""))
        recon = self.table("GL_RECON_ITEMS", ["RBUKRS", "GJAHR", "POPER", "RACCT", "HSL", "RHCUR", "REASON", "BELNR", "DESCRIPTION"])
        for period, account, amount, documented, reason, belnr, text in VARIANCES:
            d = date(int(period[:4]), int(period[5:]), 15)
            totals[(_gjahr(d), _poper(d), account)] += amount
            if documented:
                recon.append([BUKRS, str(_gjahr(d)), f"{_poper(d):03d}", account, _money(amount), "INR", reason, belnr, text])
        gl = self.table("ACDOCA_PERIOD_TOTALS", ["RBUKRS", "GJAHR", "POPER", "RACCT", "TXT50", "HSL", "RHCUR"])
        for (gj, poper, account), amount in sorted(totals.items()):
            gl.append([BUKRS, str(gj), f"{poper:03d}", account, GL_TEXT[account], _money(amount), "INR"])
        balance = 0
        for r in self.tables["BSIK"][1]:
            amount = int(r[10].replace(".", ""))
            balance += -amount if r[12] == "H" else amount
        bal = self.table("GL_BALANCES", ["RBUKRS", "RACCT", "TXT50", "KEYDATE", "HSL", "RHCUR"])
        bal.append([BUKRS, "160000", GL_TEXT["160000"], KEY_DATE.isoformat(), _money(balance), "INR"])

    def _account_of(self, ebeln: str, ebelp: str) -> str:
        if not hasattr(self, "_accounts"):
            self._accounts = {(r[0], r[1]): r[3] for r in self.tables["EKKN"][1]}
        return self._accounts.get((ebeln, ebelp), "191100")

    # -------------------------------------------------------------- write
    def write(self, out_dir: Path) -> dict:
        out_dir.mkdir(parents=True, exist_ok=True)
        sort_keys = {"EKBE": (0, 1, 2, 3, 4, 5), "RSEG": (0, 1, 2), "EKPO": (0, 1), "EKKO": (0,), "BSIK": (1, 2, 3), "BSAK": (1, 2, 3),
                     "RBKP": (1, 0), "EKKN": (0, 1), "EKET": (0, 1), "A016_KONP": (0, 1, 3), "EORD": (0, 1, 2), "MARC": (0, 1), "MBEW": (0, 1),
                     "EINA_EINE": (0,), "MARA": (0,), "MAKT": (0,), "BSEG_KR": (2, 1)}
        manifest = {"client": COMPANY, "fictional": True, "tenant": "KAC", "sourceSystem": "SAP_S4", "system": "S4P (mock)",
                    "release": "SAP S/4HANA 2023 (mock extract)", "extractId": EXTRACT_ID, "extractType": "INITIAL", "companyCodes": [BUKRS],
                    "keyDate": KEY_DATE.isoformat(), "historyFrom": HISTORY_FROM.isoformat(), "historyTo": KEY_DATE.isoformat(),
                    "extractedAt": "2026-11-01T02:00:00+05:30", "generator": f"app.pic.tools.erp_mock seed {SEED}", "encoding": "UTF-8",
                    "delimiter": ",", "dateFormat": "YYYY-MM-DD", "decimal": ".", "currency": "INR", "files": {}}
        amount_cols = {"RSEG": "WRBTR", "RBKP": "RMWWR", "EKPO": "NETWR", "BSIK": "WRBTR", "BSAK": "WRBTR", "BSEG_KR": "WRBTR",
                       "ACDOCA_PERIOD_TOTALS": "HSL", "EKBE": "DMBTR", "A016_KONP": "KBETR"}
        for name in sorted(self.tables):
            columns, rows = self.tables[name]
            if name in sort_keys:
                idx = sort_keys[name]
                rows.sort(key=lambda r: tuple(r[i] for i in idx))
            buffer = io.StringIO()
            writer = csv.writer(buffer, lineterminator="\n")
            writer.writerow(columns)
            writer.writerows(rows)
            data = buffer.getvalue().encode("utf-8")
            (out_dir / f"{name}.csv").write_bytes(data)
            entry = {"rows": len(rows), "sha256": hashlib.sha256(data).hexdigest()}
            if name in amount_cols:
                col = columns.index(amount_cols[name])
                total = 0
                for r in rows:
                    value = r[col]
                    total += (-1 if value.startswith("-") else 1) * int(value.lstrip("-").replace(".", ""))
                entry["controlTotal"] = {"column": amount_cols[name], "sum": _money(total)}
            manifest["files"][f"{name}.csv"] = entry
        (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        return manifest


def generate(out_dir: Path = OUT_DIR, seed: int = SEED) -> dict:
    g = _Gen(seed)
    g.ekbe_gr = []
    g.org()
    g.vendors_()
    g.materials_()
    g.sourcing_()
    g.agreements_()
    g.transactions_()
    g.write_transactions()
    g.write_invoices()
    g.payments_()
    g.inject_()
    g.gl_()
    manifest = g.write(Path(out_dir))
    manifest["_injected"] = g.injected
    manifest["_duplicate"] = g.duplicate
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate the mock SAP S/4HANA extract of Kaveri Auto Components (tenant KAC)")
    parser.add_argument("--out", default=str(OUT_DIR))
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)
    manifest = generate(Path(args.out), args.seed)
    total = sum((Path(args.out) / name).stat().st_size for name in manifest["files"])
    for name, entry in sorted(manifest["files"].items()):
        print(f"{name:28} {entry['rows']:>7} rows")
    print(f"{len(manifest['files'])} files, {total / 1e6:.1f} MB in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
