"""Enterprise mock datasets and tools verification suite for D8, D10, and D11.

Covers:
- D11: Reference Data (CBIC HSN/GST, CBDT TDS statutory schedules, FBIL multi-period FX history, factory calendars, feed simulator)
- D10: ERP Cutover Extract & Reconciliation (SAP S/4HANA 9 migration objects, GL ACDOCA tie-out report)
- D8: High-Scale Volume Data Generator (offline streaming CSV export, SQL COPY scripts, MRP netting optimization)
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.pic.config import BACKEND_DIR
from app.pic.seed.datasets import reference_data
from app.pic.tools import erp_extract_validator, feed_simulator, volume_gen


# ---------------------------------------------------------------- D11: Reference Data Tests
def test_d11_reference_datasets_integrity():
    for name in ("hsn_gst_rates.csv", "holidays_2026_2027.csv", "unspsc_category_map.csv", "fx_reference_rates.csv", "tds_schedules.csv"):
        header, rows = reference_data.read_reference(name)
        assert rows, f"{name} must contain data rows"
        assert any("As of: 2026-10-28" in line for line in header), f"{name} missing official as-of date header"

    # TDS schedules
    _, tds_rows = reference_data.read_reference("tds_schedules.csv")
    assert len(tds_rows) >= 10
    tds_sections = {r["section"] for r in tds_rows}
    assert {"194C", "194J", "194Q", "194I", "194H", "206AB", "206C_1H"} <= tds_sections

    body = reference_data.tds_body()
    assert body["sections"]["194Q-GOODS"]["ratePct"] == 0.1
    assert body["sections"]["194Q-GOODS"]["excessOnly"] is True
    assert body["sections"]["194J-PROFESSIONAL"]["ratePct"] == 10.0

    # Multi-period FX history
    _, fx_rows = reference_data.read_reference("fx_reference_rates.csv")
    assert len(fx_rows) > 300  # historical monthly closing rates
    currencies = {r["from_ccy"] for r in fx_rows}
    assert {"USD", "EUR", "GBP", "JPY", "SGD", "AED", "CNY", "CHF"} <= currencies

    # Factory calendar state coverage for 2026 and 2027
    lists = reference_data.holiday_lists()
    for state_code in ("IN", "33", "29", "27", "24", "36", "07", "06"):
        assert 2026 in lists[state_code], f"State {state_code} missing 2026 public holidays"
        assert 2027 in lists[state_code], f"State {state_code} missing 2027 public holidays"


def test_d11_feed_simulator_dry_run():
    today = date(2027, 4, 15)
    # FX feed
    fx_res = feed_simulator.sync_fx_feed(session=None, tenant_id=None, as_of=today, dry_run=True)
    assert fx_res["feed"] == "FX" and fx_res["date"] == "2027-04-15"
    assert any(r["from"] == "USD" and r["to"] == "INR" for r in fx_res["rates"])


# ---------------------------------------------------------------- D10: ERP Cutover Validation Tests
def test_d10_erp_cutover_validation():
    kac_dir = BACKEND_DIR / "data" / "erp_mock" / "KAC"
    validator = erp_extract_validator.ExtractValidator(kac_dir, strict=False)
    report = validator.run_all()

    assert report["status"] == "PASS"
    assert report["passed"] is True

    # Validate migration metrics
    metrics = report["metrics"]
    assert metrics["companyCode"] == "1000"
    assert metrics["plantCount"] == 3
    assert metrics["costCentres"] >= 10
    assert metrics["wbsElements"] >= 4
    assert metrics["vendorMasterCount"] >= 200
    assert metrics["materialCount"] >= 1000
    assert metrics["openPoLines"] > 500
    assert metrics["openApItems"] > 500

    # GL Tie-out (21 balanced, 3 intentional variance periods documented in GL_RECON_ITEMS)
    assert metrics["glPeriodsTotal"] == 24
    assert metrics["glPeriodsReconciled"] == 21
    assert metrics["glVariancePeriods"] == 3
    assert metrics["glReconItemsCount"] >= 2


# ---------------------------------------------------------------- D8: High-Scale Volume Generator Tests
def test_d8_volume_scaling_and_offline_export(tmp_path):
    vol_full = volume_gen.volumes(1.0, 1)
    assert vol_full["materials"] == 50_000
    assert vol_full["invoices"] == 5_000_000
    assert vol_full["spend_lines"] == 50_000_000

    out_dir = tmp_path / "scale_test"
    manifest = volume_gen.export_to_files(out_dir, scale=0.0002, years=1, plants=["1100"], seed=99)

    assert manifest["status"] == "PASS"
    assert manifest["volumes"]["materials"] == 10
    assert manifest["volumes"]["invoices"] == 1000
    assert manifest["volumes"]["spend_lines"] == 10000

    # Check generated files
    for fname in ("materials.csv", "suppliers.csv", "purchase_orders.csv", "po_lines.csv",
                  "invoices.csv", "invoice_lines.csv", "spend_lines.csv", "load_volume.sql", "DATASET_METADATA.json"):
        assert (out_dir / fname).exists(), f"{fname} must be generated in export directory"

