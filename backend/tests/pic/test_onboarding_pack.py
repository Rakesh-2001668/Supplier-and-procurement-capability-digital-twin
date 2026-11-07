"""Tests for the Turnkey Client ERP Onboarding Accelerator Pack (TD §12, Item 50)."""
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import uuid
import pytest

from app.pic.platform import field_mapping
from app.pic.tools import onboarding_pack


def test_validate_all_rules_in_onboarding_pack():
    results = onboarding_pack.validate_pack()
    assert len(results) >= 5
    for item in results:
        assert item["valid"], f"Rule file {item['file']} has problems: {item['problems']}"
        assert item["rules_count"] > 0


def test_sap_po_rules_transformation():
    rules = onboarding_pack.load_rules_from_file("SAP_S4_PURCHASE_ORDER.json")
    sample_po = {
        "orderNumber": "PO-77410",
        "supplier": {"code": "100001", "name": "Standard Steel Corp"},
        "orderDate": "2026-11-07",
        "netTotalMinor": 5000000,
        "grossTotalMinor": 5900000,
        "paymentTerms": "NET30",
        "internalNotes": "Internal sensitive remarks",
        "lines": [
            {"line": 10, "material": "steel-bar-1", "qty": "50.5", "priceMinor": 100000}
        ]
    }
    preview = field_mapping.preview(rules, sample_po)
    assert preview["valid"], f"Preview failed: {preview['problems']}"
    outbound = preview["outbound"]
    assert outbound["SourceSystem"] == "PIC"
    assert outbound["ExternalReference"] == "PO-77410"
    assert outbound["supplier"]["code"] == "0000100001"
    assert outbound["orderDate"] == "20261107"
    assert outbound["netTotalMinor"] == "50000.00"
    assert outbound["grossTotalMinor"] == "59000.00"
    assert outbound["PaymentTermsCode"] == "Z030"
    assert "internalNotes" not in outbound
    assert outbound["lines"][0]["material"] == "STEEL-BAR-1"
    assert outbound["lines"][0]["qty"] == "50.500"
    assert outbound["lines"][0]["priceMinor"] == "1000.00"


def test_sap_invoice_rules_transformation():
    rules = onboarding_pack.load_rules_from_file("SAP_S4_SUPPLIER_INVOICE.json")
    sample_inv = {
        "invoiceNo": "INV-2026-001",
        "supplier": {"code": "200055"},
        "invoiceDate": "2026-11-05",
        "postingDate": "2026-11-07",
        "grossMinor": 1180000,
        "netMinor": 1000000,
        "taxMinor": 180000,
        "gstRate": "18",
        "paymentTerms": "NET45",
        "internalNote": "Do not send to vendor",
        "lines": [{"line": 1, "qty": "10", "netMinor": 1000000}]
    }
    preview = field_mapping.preview(rules, sample_inv)
    assert preview["valid"]
    outbound = preview["outbound"]
    assert outbound["SourceSystem"] == "PIC"
    assert outbound["XBLNR"] == "INV-2026-001"
    assert outbound["supplier"]["code"] == "0000200055"
    assert outbound["invoiceDate"] == "20261105"
    assert outbound["postingDate"] == "20261107"
    assert outbound["grossMinor"] == "11800.00"
    assert outbound["netMinor"] == "10000.00"
    assert outbound["taxMinor"] == "1800.00"
    assert outbound["TaxCode"] == "I3"
    assert outbound["PaymentTermsCode"] == "Z045"
    assert "internalNote" not in outbound


def test_onboarding_pack_dry_run():
    report = onboarding_pack.apply_mappings_for_tenant("AXN", dry_run=True)
    assert report["tenant"] == "AXN"
    assert report["dry_run"] is True
    assert len(report["mappings"]) == len(onboarding_pack.DEFAULT_MAPPINGS)
    for m in report["mappings"]:
        assert m["status"] in ("DRY_RUN_VALID", "ALREADY_ACTIVE")


if __name__ == "__main__":
    print("Running onboarding pack tests...")
    test_validate_all_rules_in_onboarding_pack()
    print("✓ test_validate_all_rules_in_onboarding_pack passed")
    test_sap_po_rules_transformation()
    print("✓ test_sap_po_rules_transformation passed")
    test_sap_invoice_rules_transformation()
    print("✓ test_sap_invoice_rules_transformation passed")
    print("All unit tests passed successfully!")
