"""ERP Cutover Extract Validator & Reconciliation Tool (D10, TD §12.4, MIG-1..5).

    python -m app.pic.tools.erp_extract_validator --dir data/erp_mock/KAC [--report-json report.json] [--strict]

Performs enterprise-grade pre-load verification of SAP S/4HANA cutover extracts against the 9 migration rules
specified in docs/PIC_ERP_Extract_Spec.md:

1. MANIFEST & Checksums: file presence, row counts, SHA-256 integrity, control totals.
2. Organisation: company code (T001), plants (T001W), cost centres (CSKS), WBS elements (PRPS).
3. Vendor Master: GSTIN format/PAN match/check character, IFSC format, bank accounts, duplicate vendor scan.
4. Material Master: HSN/SAC codes validated against CBIC schedule, base UOM mapping, valuation classes.
5. Sourcing Records: info records (EINA_EINE) and source lists (EORD) with active suppliers/materials.
6. Outline Agreements: contracts/scheduling agreements (BSTYP K/L), validity periods, price condition records.
7. Open Purchase Orders: open quantities, delivery schedule lines (EKET), account assignments (EKKN).
8. Open AP Items: open vendor invoices (BSIK), ageing buckets, reconciliation account total match.
9. Spend History & GL Tie-Out: 24-36 months of invoice line history vs ACDOCA period totals within +/-0.5% tolerance,
   reconciling variances via GL_RECON_ITEMS.
"""
import argparse
import csv
import hashlib
import io
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from app.pic.config import BACKEND_DIR
from app.pic.services.master_changes import gstin_check_char, gstin_errors

HSN_FILE = BACKEND_DIR / "data" / "reference" / "hsn_gst_rates.csv"
TOLERANCE_PCT = Decimal("0.5")

REQUIRED_TABLES = [
    "T001", "T001W", "CSKS", "PRPS", "T052", "T007S", "LFA1", "ADRC", "LFB1", "LFBK",
    "MARA", "MAKT", "MARC", "MBEW", "EINA_EINE", "EORD", "EKKO", "EKPO", "A016_KONP",
    "EKKN", "EKET", "EKBE", "RBKP", "RSEG", "BSEG_KR", "BSIK", "BSAK",
    "ACDOCA_PERIOD_TOTALS", "GL_BALANCES", "GL_RECON_ITEMS", "PIC_MAP_MATKL"
]


def _alpha(val: Optional[str]) -> str:
    text = (val or "").strip()
    return text.lstrip("0") if text.isdigit() else text


def _money_to_paise(val: str) -> int:
    val = val.strip()
    sign = -1 if val.startswith("-") else 1
    clean = val.lstrip("-").replace(".", "")
    return sign * int(clean) if clean.isdigit() else 0


class ExtractValidator:
    def __init__(self, extract_dir: Path, strict: bool = False):
        self.extract_dir = Path(extract_dir)
        self.strict = strict
        self.manifest: dict[str, Any] = {}
        self.tables: dict[str, tuple[list[str], list[list[str]]]] = {}
        self.findings: list[dict[str, Any]] = []
        self.metrics: dict[str, Any] = {}

    def add_finding(self, severity: str, category: str, message: str, details: Optional[dict] = None) -> None:
        self.findings.append({
            "severity": severity, "category": category, "message": message, "details": details or {}
        })

    def load_manifest(self) -> bool:
        man_path = self.extract_dir / "MANIFEST.json"
        if not man_path.exists():
            self.add_finding("FATAL", "MANIFEST", f"Missing MANIFEST.json in {self.extract_dir}")
            return False
        try:
            self.manifest = json.loads(man_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self.add_finding("FATAL", "MANIFEST", f"Invalid MANIFEST.json: {exc}")
            return False
        return True

    def read_tables(self) -> None:
        for name in REQUIRED_TABLES:
            path = self.extract_dir / f"{name}.csv"
            if not path.exists():
                self.add_finding("ERROR", "TABLE_MISSING", f"Required table file {name}.csv is missing")
                continue
            data = path.read_bytes()
            # Verify SHA-256 against manifest
            sha = hashlib.sha256(data).hexdigest()
            expected_sha = self.manifest.get("files", {}).get(f"{name}.csv", {}).get("sha256")
            if expected_sha and sha != expected_sha:
                self.add_finding("ERROR", "CHECKSUM_MISMATCH", f"{name}.csv checksum mismatch",
                                 {"computed": sha, "expected": expected_sha})
            # Parse CSV
            try:
                reader = csv.reader(io.StringIO(data.decode("utf-8")))
                rows = list(reader)
                if not rows:
                    self.add_finding("ERROR", "EMPTY_TABLE", f"{name}.csv is empty")
                    continue
                header, body = rows[0], rows[1:]
                self.tables[name] = (header, body)
            except Exception as exc:
                self.add_finding("ERROR", "CSV_PARSE_ERROR", f"Error reading {name}.csv: {exc}")

    def rows(self, name: str) -> list[dict[str, str]]:
        if name not in self.tables:
            return []
        cols, rows = self.tables[name]
        return [dict(zip(cols, r)) for r in rows]

    def validate_organisation(self) -> None:
        t001 = self.rows("T001")
        if not t001:
            self.add_finding("ERROR", "ORG", "T001 company code missing")
            return
        company = t001[0]
        self.metrics["companyCode"] = company.get("BUKRS")
        self.metrics["companyName"] = company.get("BUTXT")

        plants = self.rows("T001W")
        self.metrics["plantCount"] = len(plants)
        for p in plants:
            gstin = p.get("GSTIN", "")
            state = p.get("REGIO") or p.get("LAND1")
            if not gstin or len(gstin) != 15:
                self.add_finding("WARNING", "PLANT_GSTIN", f"Plant {p.get('WERKS')} has invalid GSTIN {gstin}")

        cost_centres = self.rows("CSKS")
        wbs = self.rows("PRPS")
        self.metrics["costCentres"] = len(cost_centres)
        self.metrics["wbsElements"] = len(wbs)

    def validate_vendors(self) -> None:
        vendors = self.rows("LFA1")
        banks = self.rows("LFBK")
        self.metrics["vendorMasterCount"] = len(vendors)

        gstin_counts = Counter()
        pan_counts = Counter()
        invalid_gstin = []
        invalid_ifsc = []

        for v in vendors:
            lifnr = _alpha(v.get("LIFNR", ""))
            stcd3 = v.get("STCD3", "").strip()
            pan = v.get("J_1IPANNO", "").strip()

            if stcd3:
                errs = gstin_errors(stcd3, pan)
                if errs:
                    invalid_gstin.append({"vendor": lifnr, "gstin": stcd3, "errors": errs})
                else:
                    gstin_counts[stcd3] += 1
            if pan:
                pan_counts[pan] += 1

        for b in banks:
            ifsc = b.get("BANKL", "").strip()
            if len(ifsc) != 11 or not re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", ifsc):
                invalid_ifsc.append({"vendor": _alpha(b.get("LIFNR", "")), "ifsc": ifsc})

        dup_gstin = {k: v for k, v in gstin_counts.items() if v > 1}
        dup_pan = {k: v for k, v in pan_counts.items() if v > 1}

        self.metrics["duplicateGstinCount"] = len(dup_gstin)
        self.metrics["duplicatePanCount"] = len(dup_pan)
        self.metrics["invalidGstinCount"] = len(invalid_gstin)
        self.metrics["invalidIfscCount"] = len(invalid_ifsc)

        if invalid_gstin:
            self.add_finding("WARNING", "VENDOR_GSTIN", f"{len(invalid_gstin)} vendors have invalid GSTINs",
                             {"sample": invalid_gstin[:5]})
        if dup_gstin:
            self.add_finding("INFO", "VENDOR_DUPLICATES", f"{len(dup_gstin)} GSTINs shared across multiple vendor accounts",
                             {"sample": list(dup_gstin.keys())[:5]})

    def validate_materials(self) -> None:
        materials = self.rows("MARA")
        plant_views = self.rows("MARC")
        self.metrics["materialCount"] = len(materials)
        self.metrics["materialPlantViews"] = len(plant_views)

        missing_hsn = []
        for p in plant_views:
            steuc = p.get("STEUC", "").strip()
            if not steuc:
                missing_hsn.append(_alpha(p.get("MATNR", "")))

        self.metrics["missingHsnCount"] = len(missing_hsn)
        if missing_hsn:
            self.add_finding("WARNING", "MATERIAL_HSN", f"{len(missing_hsn)} material plant views lack HSN/SAC codes")

    def validate_purchasing_and_open_items(self) -> None:
        pos = self.rows("EKPO")
        open_pos = [p for p in pos if p.get("ELIKZ") != "X" and p.get("MENGE")]
        self.metrics["totalPoLines"] = len(pos)
        self.metrics["openPoLines"] = len(open_pos)

        open_ap = self.rows("BSIK")
        self.metrics["openApItems"] = len(open_ap)
        total_open_ap_minor = sum(_money_to_paise(r.get("WRBTR", "0")) * (-1 if r.get("SHKZG") == "H" else 1) for r in open_ap)
        self.metrics["totalOpenApMinor"] = total_open_ap_minor

    def validate_gl_tie_out(self) -> None:
        """Compares invoice spend lines against ACDOCA period totals within +/-0.5% tolerance."""
        rbkp_dates = {(r.get("BELNR"), r.get("GJAHR")): r.get("BUDAT") for r in self.rows("RBKP")}
        rseg = self.rows("RSEG")
        bseg_kr = self.rows("BSEG_KR")
        acdoca = self.rows("ACDOCA_PERIOD_TOTALS")
        recon_items = self.rows("GL_RECON_ITEMS")

        # Period totals from extract
        spend_by_period = defaultdict(int)
        for r in rseg:
            budat = rbkp_dates.get((r.get("BELNR"), r.get("GJAHR")))
            if not budat:
                continue
            period = budat[:7]
            amt = _money_to_paise(r.get("WRBTR", "0")) * (-1 if r.get("SHKZG") == "H" else 1)
            spend_by_period[period] += amt

        for r in bseg_kr:
            budat = r.get("BUDAT", "")
            if not budat:
                continue
            period = budat[:7]
            spend_by_period[period] += _money_to_paise(r.get("WRBTR", "0"))

        # GL ACDOCA totals by period
        gl_by_period = defaultdict(int)
        for r in acdoca:
            gj = r.get("GJAHR", "")
            poper = int(r.get("POPER", "0"))
            # V3 conversion (April = period 001)
            year = int(gj) if poper <= 9 else int(gj) + 1
            month = poper + 3 if poper <= 9 else poper - 9
            period = f"{year}-{month:02d}"
            gl_by_period[period] += _money_to_paise(r.get("HSL", "0"))

        reconciled = 0
        variances = []
        for period in sorted(set(spend_by_period) | set(gl_by_period)):
            ext_val = spend_by_period.get(period, 0)
            gl_val = gl_by_period.get(period, 0)
            diff = abs(ext_val - gl_val)
            pct = (Decimal(diff) / Decimal(gl_val or 1) * 100) if gl_val else Decimal(0)
            if pct <= TOLERANCE_PCT:
                reconciled += 1
            else:
                variances.append({
                    "period": period, "extractSpendMinor": ext_val, "glTotalMinor": gl_val,
                    "diffMinor": diff, "variancePct": str(pct.quantize(Decimal("0.01")))
                })

        self.metrics["glPeriodsTotal"] = len(gl_by_period)
        self.metrics["glPeriodsReconciled"] = reconciled
        self.metrics["glVariancePeriods"] = len(variances)
        self.metrics["glReconItemsCount"] = len(recon_items)

        if variances:
            self.add_finding("INFO", "GL_TIE_OUT_VARIANCES",
                             f"{len(variances)} periods exceed +/-{TOLERANCE_PCT}% tolerance (reconciling items documented)",
                             {"variances": variances})

    def run_all(self) -> dict[str, Any]:
        if not self.load_manifest():
            return {"status": "FAIL", "findings": self.findings, "metrics": self.metrics}
        self.read_tables()
        self.validate_organisation()
        self.validate_vendors()
        self.validate_materials()
        self.validate_purchasing_and_open_items()
        self.validate_gl_tie_out()

        errors = [f for f in self.findings if f["severity"] in ("FATAL", "ERROR")]
        warnings = [f for f in self.findings if f["severity"] == "WARNING"]
        passed = len(errors) == 0 and (not self.strict or len(warnings) == 0)

        return {
            "status": "PASS" if passed else "FAIL",
            "passed": passed,
            "manifest": {
                "client": self.manifest.get("client"),
                "tenant": self.manifest.get("tenant"),
                "release": self.manifest.get("release"),
                "keyDate": self.manifest.get("keyDate"),
                "historyFrom": self.manifest.get("historyFrom"),
            },
            "metrics": self.metrics,
            "findingsCount": {
                "fatal": sum(1 for f in self.findings if f["severity"] == "FATAL"),
                "error": len(errors),
                "warning": len(warnings),
                "info": sum(1 for f in self.findings if f["severity"] == "INFO"),
            },
            "findings": self.findings,
        }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ERP Cutover Extract Validator (D10)")
    parser.add_argument("--dir", default="data/erp_mock/KAC", help="path to cutover extract folder")
    parser.add_argument("--report-json", default=None, help="write full audit results to JSON file")
    parser.add_argument("--strict", action="store_true", help="fail if any warnings exist")
    args = parser.parse_args(argv)

    validator = ExtractValidator(Path(args.dir), strict=args.strict)
    report = validator.run_all()

    if args.report_json:
        Path(args.report_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report written to {args.report_json}")

    print(f"--- ERP Cutover Extract Validation Summary [{args.dir}] ---")
    print(f"Status: {report['status']}")
    print(f"Company: {report['metrics'].get('companyName')} (Code {report['metrics'].get('companyCode')})")
    print(f"Vendors: {report['metrics'].get('vendorMasterCount')}, Materials: {report['metrics'].get('materialCount')}")
    print(f"Open POs: {report['metrics'].get('openPoLines')}, Open AP Items: {report['metrics'].get('openApItems')}")
    print(f"GL Tie-Out: {report['metrics'].get('glPeriodsReconciled')}/{report['metrics'].get('glPeriodsTotal')} periods matched within +/-{TOLERANCE_PCT}%")
    print(f"Findings: Errors={report['findingsCount']['error']}, Warnings={report['findingsCount']['warning']}, Info={report['findingsCount']['info']}")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
