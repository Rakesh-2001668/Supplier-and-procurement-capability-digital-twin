"""Mock SAP S/4HANA production delta extracts of Kaveri Auto Components (tenant KAC).

    python -m app.pic.tools.erp_delta_mock [--out data/erp_mock/KAC_DELTA] [--stage-drop DIR]

Generates the post-cutover incremental delta files (Technical Document §12.1 and §12.4)
that simulate Day-1 and Day-2 production activity in SAP S/4HANA across all 8 supported
ERP sync object kinds:
  1. VENDORS        Incremental vendor changes (name/address/terms), new suppliers,
                    and sensitive bank/tax changes triggering MDM-04 approval routing.
  2. MATERIALS      New direct/indirect part numbers, updated descriptions, and revised
                    standard costs in MBEW.
  3. PLANTS         Plant master description updates and new plant facility.
  4. COST_OBJECTS   New cost centers and WBS projects.
  5. STOCK          Incremental physical stock level updates for plant storage locations.
  6. OPEN_POS       Reconciliation records detecting SAP order discrepancies.
  7. PAYMENT_STATUS Cleared invoice documents in SAP (BSIK -> BSAK) transitioning PIC
                    posted invoices to PAID.
  8. PLANNED_ORDERS Incremental MRP planned orders imported for production scheduling.

The layout matches the contract expected by ``app.pic.services.erp_sync.read_drop``
(``<dir>/<KIND>/`` holding SAP table CSVs or ``<KIND>.json`` / ``<KIND>.csv``).
"""
import argparse
import csv
import hashlib
import io
import json
import shutil
from datetime import date
from pathlib import Path
from typing import Optional

from app.pic.config import BACKEND_DIR
from app.pic.services.master_changes import gstin_check_char

OUT_DIR = BACKEND_DIR / "data" / "erp_mock" / "KAC_DELTA"
EXTRACT_ID = "KAC-S4H-20261102-DELTA"
COMPANY = "Kaveri Auto Components Pvt Ltd"
BUKRS = "1000"


def _gstin(first14: str) -> str:
    return first14 + gstin_check_char(first14)


def _write_csv(path: Path, columns: list[str], rows: list[list]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    data = buf.getvalue().encode("utf-8")
    path.write_bytes(data)
    return len(rows), hashlib.sha256(data).hexdigest()


def _write_json(path: Path, data: object) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
    path.write_bytes(encoded)
    rows = len(data) if isinstance(data, list) else 1
    return rows, hashlib.sha256(encoded).hexdigest()


def generate(out_dir: Path = OUT_DIR) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "client": COMPANY,
        "fictional": True,
        "tenant": "KAC",
        "sourceSystem": "SAP_S4",
        "system": "S4P (mock delta)",
        "release": "SAP S/4HANA 2023 (delta extract)",
        "extractId": EXTRACT_ID,
        "extractType": "DELTA",
        "companyCodes": [BUKRS],
        "deltaDate": "2026-11-02",
        "extractedAt": "2026-11-02T18:00:00+05:30",
        "generator": "app.pic.tools.erp_delta_mock",
        "encoding": "UTF-8",
        "files": {},
    }

    # ------------------------------------------------------------ 1. VENDORS
    # 2 existing updated, 1 existing with sensitive change (tax/bank -> MDM-04), 2 brand-new suppliers
    v_dir = out_dir / "VENDORS"
    lfa1_cols = ["LIFNR", "KTOKK", "NAME1", "NAME2", "SORTL", "ADRNR", "LAND1", "STCD3", "J_1IPANNO", "SPERR", "SPERM", "LOEVM", "ERDAT"]
    gstin_sens = _gstin("33JVMCV1188M2Z")
    gstin_new1 = _gstin("33AAACC3350P1Z")
    gstin_new2 = _gstin("29AAXFA2035L1Z")
    lfa1_rows = [
        ["0000100001", "ZDOM", "Vaigai Diecast Technologies Pvt Ltd", "", "VAIGAI DIE", "0009100001", "IN", "29HWFCV2767U1ZP", "HWFCV2767U", "", "", "", "2016-05-01"],
        ["0000100003", "ZDOM", "Vetri Alloy Castings Pvt Ltd", "", "VETRI ALLO", "0009100003", "IN", "33XGECV2962T1ZN", "XGECV2962T", "", "", "", "2018-09-01"],
        ["0000100008", "ZDOM", "Vaigai Pressure Diecasters Pvt Ltd", "", "VAIGAI PRE", "0009100008", "IN", gstin_sens, "JVMCV1188M", "", "", "", "2021-10-01"],
        ["0000200350", "ZDOM", "Coimbatore Precision Tooling Pvt Ltd", "", "COIMBATORE", "0009200350", "IN", gstin_new1, "AAACC3350P", "", "", "", "2026-11-02"],
        ["0000200351", "ZDOM", "Apex Sensor Systems LLP", "", "APEX SENSO", "0009200351", "IN", gstin_new2, "AAXFA2035L", "", "", "", "2026-11-02"],
    ]
    r, h = _write_csv(v_dir / "LFA1.csv", lfa1_cols, lfa1_rows)
    manifest["files"]["VENDORS/LFA1.csv"] = {"rows": r, "sha256": h}

    adrc_cols = ["ADDRNUMBER", "NAME1", "STREET", "STR_SUPPL1", "CITY1", "POST_CODE1", "REGION", "COUNTRY", "SMTP_ADDR", "TEL_NUMBER"]
    adrc_rows = [
        ["0009100001", "Vaigai Diecast Technologies Pvt Ltd", "No. 197, KIADB Industrial Area", "", "Bidadi", "562109", "29", "IN", "orders@vaigaidiecasttech.example", ""],
        ["0009100003", "Vetri Alloy Castings Pvt Ltd", "No. 23, SIPCOT Industrial Complex", "", "Ranipet", "632403", "33", "IN", "accounts@vetrialloycastings.example", ""],
        ["0009100008", "Vaigai Pressure Diecasters Pvt Ltd", "No. 181, BHEL Ancillary Estate", "", "Tiruchirappalli", "620015", "33", "IN", "accounts@vaigaipressurediecasters.example", ""],
        ["0009200350", "Coimbatore Precision Tooling Pvt Ltd", "Plot 12, SIDCO Industrial Estate", "", "Coimbatore", "641021", "33", "IN", "sales@cbe-precision.example", ""],
        ["0009200351", "Apex Sensor Systems LLP", "45 Electronics City Phase 1", "", "Bengaluru", "560100", "29", "IN", "contact@apexsensors.example", ""],
    ]
    r, h = _write_csv(v_dir / "ADRC.csv", adrc_cols, adrc_rows)
    manifest["files"]["VENDORS/ADRC.csv"] = {"rows": r, "sha256": h}

    lfb1_cols = ["LIFNR", "BUKRS", "AKONT", "ZTERM", "ZWELS", "REPRF", "SPERR", "LOEVM", "ERDAT"]
    lfb1_rows = [
        ["0000100001", "1000", "160000", "Z015", "T", "X", "", "", "2016-05-01"],
        ["0000100003", "1000", "160000", "Z030", "T", "X", "", "", "2018-09-01"],
        ["0000100008", "1000", "160000", "Z045", "T", "X", "", "", "2021-10-01"],
        ["0000200350", "1000", "160000", "Z030", "T", "X", "", "", "2026-11-02"],
        ["0000200351", "1000", "160000", "Z030", "T", "X", "", "", "2026-11-02"],
    ]
    r, h = _write_csv(v_dir / "LFB1.csv", lfb1_cols, lfb1_rows)
    manifest["files"]["VENDORS/LFB1.csv"] = {"rows": r, "sha256": h}

    lfbk_cols = ["LIFNR", "BANKS", "BANKL", "BANKN", "KOINH", "BVTYP"]
    lfbk_rows = [
        ["0000100001", "IN", "KVBL0K83827", "25717419645525", "Vaigai Diecast Technologies Pvt Ltd", "0001"],
        ["0000100003", "IN", "ICIC0K12445", "52226659251244", "Vetri Alloy Castings Pvt Ltd", "0001"],
        ["0000100008", "IN", "ICIC0K30004", "20135475699999", "Vaigai Pressure Diecasters Pvt Ltd", "0001"],
        ["0000200350", "IN", "HDFC0K88350", "50100998835001", "Coimbatore Precision Tooling Pvt Ltd", "0001"],
        ["0000200351", "IN", "ICIC0K99351", "109923351001", "Apex Sensor Systems LLP", "0001"],
    ]
    r, h = _write_csv(v_dir / "LFBK.csv", lfbk_cols, lfbk_rows)
    manifest["files"]["VENDORS/LFBK.csv"] = {"rows": r, "sha256": h}

    t052_cols = ["ZTERM", "ZTAG1", "ZPRZ1", "TEXT1"]
    t052_rows = [
        ["Z015", "15", "0.000", "Net 15 days"],
        ["Z030", "30", "0.000", "Net 30 days"],
        ["Z045", "45", "0.000", "Net 45 days (MSME limit)"],
        ["Z060", "60", "0.000", "Net 60 days"],
    ]
    r, h = _write_csv(v_dir / "T052.csv", t052_cols, t052_rows)
    manifest["files"]["VENDORS/T052.csv"] = {"rows": r, "sha256": h}

    # ------------------------------------------------------------ 2. MATERIALS
    # 1 existing material with updated description & price escalation, 2 new direct materials
    m_dir = out_dir / "MATERIALS"
    mara_cols = ["MATNR", "MTART", "MATKL", "MEINS", "MFRPN", "BRGEW", "GEWEI", "LVORM", "ERSDA"]
    mara_rows = [
        ["11000001", "ROH", "RM-STEEL", "KG", "KAC-00001", "", "", "", "2016-05-13"],
        ["11000901", "ROH", "BO-FAST", "ST", "KAC-F0901", "", "", "", "2026-11-02"],
        ["11000902", "ROH", "BO-RUBB", "ST", "KAC-R0902", "", "", "", "2026-11-02"],
    ]
    r, h = _write_csv(m_dir / "MARA.csv", mara_cols, mara_rows)
    manifest["files"]["MATERIALS/MARA.csv"] = {"rows": r, "sha256": h}

    makt_cols = ["MATNR", "SPRAS", "MAKTX"]
    makt_rows = [
        ["11000001", "E", "Special Alloy Steel Round Bar 32mm DIN 42CrMo4 Grade A"],
        ["11000901", "E", "Hex Socket Flange Bolt M10x45 10.9 Geomet 500B"],
        ["11000902", "E", "EPDM Oil Seal Ring 45x65x8 HNBR Double Lip"],
    ]
    r, h = _write_csv(m_dir / "MAKT.csv", makt_cols, makt_rows)
    manifest["files"]["MATERIALS/MAKT.csv"] = {"rows": r, "sha256": h}

    marc_cols = ["MATNR", "WERKS", "DISMM", "DISPO", "BESKZ", "PLIFZ", "WEBAZ", "EISBE", "DISLS", "BSTFE", "BSTMI", "BSTMA", "STEUC", "QMATV", "LVORM"]
    marc_rows = [
        ["11000001", "1100", "PD", "P01", "F", "8", "0", "150", "EX", "", "", "", "722830", "", ""],
        ["11000901", "1100", "PD", "P01", "F", "5", "0", "500", "EX", "", "", "", "731815", "", ""],
        ["11000902", "1100", "PD", "P01", "F", "6", "0", "300", "EX", "", "", "", "401693", "", ""],
        ["11000902", "1200", "PD", "P01", "F", "6", "0", "200", "EX", "", "", "", "401693", "", ""],
    ]
    r, h = _write_csv(m_dir / "MARC.csv", marc_cols, marc_rows)
    manifest["files"]["MATERIALS/MARC.csv"] = {"rows": r, "sha256": h}

    mbew_cols = ["MATNR", "BWKEY", "BKLAS", "VPRSV", "STPRS", "VERPR", "PEINH"]
    mbew_rows = [
        ["11000001", "1100", "3000", "S", "94.50", "0.00", "1"],
        ["11000901", "1100", "3000", "S", "14.50", "0.00", "1"],
        ["11000902", "1100", "3000", "S", "38.20", "0.00", "1"],
        ["11000902", "1200", "3000", "S", "38.20", "0.00", "1"],
    ]
    r, h = _write_csv(m_dir / "MBEW.csv", mbew_cols, mbew_rows)
    manifest["files"]["MATERIALS/MBEW.csv"] = {"rows": r, "sha256": h}

    matkl_cols = ["MATKL", "PIC_CATEGORY", "NOTE"]
    matkl_rows = [
        ["RM-STEEL", "RAW-MATERIALS", "Steel round bars and ingots"],
        ["BO-FAST", "FASTENERS", "Fasteners and precision bolts"],
        ["BO-RUBB", "RUBBER-SEALS", "Rubber moulded parts and oil seals"],
    ]
    r, h = _write_csv(m_dir / "PIC_MAP_MATKL.csv", matkl_cols, matkl_rows)
    manifest["files"]["MATERIALS/PIC_MAP_MATKL.csv"] = {"rows": r, "sha256": h}

    # ------------------------------------------------------------ 3. STOCK
    # Unrestricted physical inventory balances for materials at plants 1100, 1200, 1300
    stk_dir = out_dir / "STOCK"
    stock_cols = ["material", "plant", "storageLocation", "qty"]
    stock_rows = [
        ["11000001", "1100", "0001", "480.000"],
        ["11000002", "1100", "0001", "310.000"],
        ["11000003", "1100", "0001", "150.000"],
        ["11000004", "1200", "0001", "220.000"],
        ["11000005", "1200", "0001", "180.000"],
        ["11000006", "1200", "0001", "290.000"],
        ["11000007", "1300", "0001", "95.000"],
        ["11000008", "1100", "0001", "410.000"],
    ]
    r, h = _write_csv(stk_dir / "STOCK.csv", stock_cols, stock_rows)
    manifest["files"]["STOCK/STOCK.csv"] = {"rows": r, "sha256": h}

    # ------------------------------------------------------------ 4. OPEN_POS
    # Open order tracking & reconciliation findings
    po_dir = out_dir / "OPEN_POS"
    open_pos_data = [
        {
            "po": "4500010041",
            "supplier": "200081",
            "deleted": False,
            "items": [
                {"item": 10, "qty": "100.000", "price": "45.00", "deleted": False}
            ]
        },
        {
            "po": "4500010092",
            "supplier": "200117",
            "deleted": False,
            "items": [
                {"item": 10, "qty": "500.000", "price": "12.00", "deleted": False}
            ]
        },
        {
            "po": "4500099991",
            "supplier": "100001",
            "deleted": False,
            "items": [
                {"item": 10, "qty": "200.000", "price": "88.00", "deleted": False}
            ]
        }
    ]
    r, h = _write_json(po_dir / "OPEN_POS.json", open_pos_data)
    manifest["files"]["OPEN_POS/OPEN_POS.json"] = {"rows": r, "sha256": h}

    # ------------------------------------------------------------ 5. PAYMENT_STATUS
    # Cleared accounting items (BSIK -> BSAK) matching KAC open AP invoices
    pay_dir = out_dir / "PAYMENT_STATUS"
    pay_cols = ["document", "fiscalYear", "supplier", "clearingDocument", "clearingDate"]
    pay_rows = [
        ["5105602634", "2026", "100001", "1500001001", "2026-11-05"],
        ["5105602706", "2026", "100001", "1500001002", "2026-11-05"],
        ["5105602758", "2026", "100002", "1500001003", "2026-11-05"],
        ["5105602651", "2026", "100003", "1500001004", "2026-11-05"],
        ["5105602810", "2026", "100004", "1500001005", "2026-11-05"],
    ]
    r, h = _write_csv(pay_dir / "PAYMENT_STATUS.csv", pay_cols, pay_rows)
    manifest["files"]["PAYMENT_STATUS/PAYMENT_STATUS.csv"] = {"rows": r, "sha256": h}

    # ------------------------------------------------------------ 6. PLANNED_ORDERS
    # MRP planned order recommendations from S/4HANA
    plan_dir = out_dir / "PLANNED_ORDERS"
    plan_cols = ["externalRef", "material", "plant", "qty", "needDate"]
    plan_rows = [
        ["PL-202611-001", "11000001", "1100", "250.000", "2026-12-05"],
        ["PL-202611-002", "11000002", "1100", "500.000", "2026-12-10"],
        ["PL-202611-003", "11000004", "1200", "300.000", "2026-12-15"],
    ]
    r, h = _write_csv(plan_dir / "PLANNED_ORDERS.csv", plan_cols, plan_rows)
    manifest["files"]["PLANNED_ORDERS/PLANNED_ORDERS.csv"] = {"rows": r, "sha256": h}

    # ------------------------------------------------------------ 7. PLANTS
    # Plant description updates and new plant
    plant_dir = out_dir / "PLANTS"
    plant_cols = ["WERKS", "NAME1", "BUKRS", "REGIO", "GSTIN"]
    plant_rows = [
        ["1100", "Hosur Plant - SIPCOT II Main Campus", "1000", "33", "33AAKCK7316R1ZT"],
        ["1400", "Coimbatore R&D Center", "1000", "33", "33AAKCK7316R1ZT"],
    ]
    r, h = _write_csv(plant_dir / "PLANTS.csv", plant_cols, plant_rows)
    manifest["files"]["PLANTS/PLANTS.csv"] = {"rows": r, "sha256": h}

    # ------------------------------------------------------------ 8. COST_OBJECTS
    # New cost center and WBS element
    co_dir = out_dir / "COST_OBJECTS"
    co_cols = ["type", "code", "name", "validTo"]
    co_rows = [
        ["COST_CENTER", "CC140", "Tool Room & Die Maintenance", ""],
        ["WBS", "W-2026-EXP", "Hosur EV Line Extension 2026-27", ""],
    ]
    r, h = _write_csv(co_dir / "COST_OBJECTS.csv", co_cols, co_rows)
    manifest["files"]["COST_OBJECTS/COST_OBJECTS.csv"] = {"rows": r, "sha256": h}

    # ------------------------------------------------------------ MANIFEST & README
    (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    readme = f"""# KAC_DELTA: Mock SAP S/4HANA Production Delta Extracts (Tenant KAC)

**Everything in this folder is deterministic mock data.** It provides high-fidelity post-cutover
incremental changes for Kaveri Auto Components Pvt Ltd (tenant KAC) as specified in Technical
Document §12.1 and §12.4.

This mock extract enables 100% offline demonstration, automated CI testing, and end-to-end
validation of the live inbound ERP sync engine (``app.pic.services.erp_sync``) without requiring
active credentials to a live client SAP S/4HANA production instance.

## Extract Summary
* **Extract ID:** ``{EXTRACT_ID}``
* **Extract Type:** ``DELTA``
* **Target Company Code:** ``{BUKRS}`` ({COMPANY})
* **Delta Date:** 2 November 2026 (Day-1 post cutover)

## Contents by Object Kind

| Kind | Files | Business Purpose |
|---|---|---|
| ``VENDORS`` | ``LFA1.csv``, ``ADRC.csv``, ``LFB1.csv``, ``LFBK.csv``, ``T052.csv`` | Updates existing vendor descriptions/terms; onboards 2 new suppliers (``200350``, ``200351``); simulates 1 sensitive bank/tax modification on ``100008`` routing to MDM-04 without cleartext exposure. |
| ``MATERIALS`` | ``MARA.csv``, ``MAKT.csv``, ``MARC.csv``, ``MBEW.csv``, ``PIC_MAP_MATKL.csv`` | Standard price revision on ``11000001`` in ``MBEW``; onboards 2 new direct materials (``11000901`` fasteners, ``11000902`` seals). |
| ``STOCK`` | ``STOCK.csv`` | Incremental physical inventory updates across plants 1100, 1200, 1300, updating ``Stock.qty`` and generating ``StockMovement`` audit records. |
| ``OPEN_POS`` | ``OPEN_POS.json`` | Reconciles purchase orders in SAP against PIC state machines; detects discrepancies and unknown ERP orders. |
| ``PAYMENT_STATUS`` | ``PAYMENT_STATUS.csv`` | Cleared AP documents in SAP (``BSIK`` -> ``BSAK``) flipping PIC posted invoices to ``PAID`` and emitting ``invoice.paid_in_erp`` outbox events. |
| ``PLANNED_ORDERS`` | ``PLANNED_ORDERS.csv`` | Incremental MRP planned orders imported for procurement scheduling. |
| ``PLANTS`` | ``PLANTS.csv`` | Plant name updates (Plant 1100) and new facility onboarding (Plant 1400 Coimbatore). |
| ``COST_OBJECTS`` | ``COST_OBJECTS.csv`` | New cost center (``CC140``) and capital investment WBS element (``W-2026-EXP``). |

## How to Use for Testing or Live Demonstration

```bash
# 1. Regenerate or verify this mock delta folder:
python -m app.pic.tools.erp_delta_mock

# 2. Stage into a fresh drop folder for FILE_DROP ingestion:
python -m app.pic.tools.erp_delta_mock --stage-drop /path/to/drop_dir

# 3. Trigger inbound ERP sync for tenant KAC:
# Inside Python or API:
# erp_sync.run("KAC", "VENDORS", directory=Path("/path/to/drop_dir"))
```
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")
    return manifest


def stage_drop(drop_dir: Path, kinds: Optional[list[str]] = None, source_dir: Path = OUT_DIR) -> Path:
    """Stage a copy of delta extract folders into ``drop_dir`` so that ``erp_sync.run`` can process

    and archive the drop without touching the master template files.
    """
    drop_dir = Path(drop_dir)
    drop_dir.mkdir(parents=True, exist_ok=True)
    source_dir = Path(source_dir)
    if not source_dir.exists():
        generate(source_dir)

    all_kinds = ("VENDORS", "MATERIALS", "STOCK", "OPEN_POS", "PAYMENT_STATUS", "PLANNED_ORDERS", "PLANTS", "COST_OBJECTS")
    target_kinds = kinds or all_kinds

    for kind in target_kinds:
        src = source_dir / kind
        if not src.exists():
            continue
        dst = drop_dir / kind
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    return drop_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate mock SAP S/4HANA production delta extracts for Kaveri Auto Components (KAC)")
    parser.add_argument("--out", default=str(OUT_DIR), help="Output directory for the master mock delta extract")
    parser.add_argument("--stage-drop", default=None, help="Optional target directory to stage a runnable FILE_DROP folder")
    args = parser.parse_args(argv)

    manifest = generate(Path(args.out))
    print(f"Generated {len(manifest['files'])} mock delta files in {args.out} (Extract ID: {manifest['extractId']})")
    for f, meta in sorted(manifest["files"].items()):
        print(f"  {f:32} {meta['rows']:>4} rows  [{meta['sha256'][:10]}...]")

    if args.stage_drop:
        stage_drop(Path(args.stage_drop), source_dir=Path(args.out))
        print(f"Staged runnable FILE_DROP into: {args.stage_drop}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

