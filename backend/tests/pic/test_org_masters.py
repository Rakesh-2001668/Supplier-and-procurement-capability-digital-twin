"""Unit tests for Legal Entity, Purchasing Org and Group Mock Datasets (TD-4a)."""
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import re
import pytest

from app.pic.seed.datasets import org_masters, PACKS
from app.pic.config import BACKEND_DIR


EXPECTED_TENANTS = {"AXN", "KAC", "CON", "ITS", "LOG", "HLT", "GEN", "GMC", "DBY"}
GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


def test_org_masters_dataset_integrity():
    """Verify canonical org_masters.csv meets all enterprise constraints (TD-4a)."""
    rows = org_masters.read_org_masters_csv()
    assert len(rows) > 0, "org_masters.csv is empty or missing"

    tenants_found = {r["tenant_code"] for r in rows}
    assert EXPECTED_TENANTS.issubset(tenants_found), f"Missing tenants in org_masters: {EXPECTED_TENANTS - tenants_found}"

    # Group by tenant
    by_tenant = {}
    for r in rows:
        by_tenant.setdefault(r["tenant_code"], []).append(r)

    for code, t_rows in by_tenant.items():
        cc_rows = [r for r in t_rows if r["entity_type"] == "COMPANY_CODE"]
        po_rows = [r for r in t_rows if r["entity_type"] == "PURCHASING_ORG"]
        pg_rows = [r for r in t_rows if r["entity_type"] == "PURCHASING_GROUP"]

        # 1. Company code constraints
        assert len(cc_rows) >= 1, f"Tenant {code} must have at least 1 company code"
        cc_codes = {r["code"] for r in cc_rows}
        assert "1000" in cc_codes, f"Tenant {code} must include default company code '1000'"
        for cc in cc_rows:
            assert len(cc["code"]) <= 10
            assert len(cc["name"]) >= 2
            assert cc["currency"] == "INR"
            if cc["gstin"]:
                assert GSTIN_REGEX.match(cc["gstin"]), f"Invalid GSTIN {cc['gstin']} for {code}/{cc['code']}"

        # 2. Purchasing org constraints
        assert len(po_rows) >= 1, f"Tenant {code} must have at least 1 purchasing org"
        po_codes = {r["code"] for r in po_rows}
        assert "1000" in po_codes, f"Tenant {code} must include purch_org '1000' for document integrity"
        for po in po_rows:
            assert len(po["code"]) <= 10
            assert len(po["name"]) >= 2
            parent_cc = po.get("parent_code")
            assert parent_cc in cc_codes, f"Purchasing org {po['code']} points to unknown company code {parent_cc} in {code}"

        # 3. Purchasing group constraints
        assert len(pg_rows) >= 1, f"Tenant {code} must have at least 1 purchasing group"
        for pg in pg_rows:
            assert len(pg["code"]) <= 10
            assert len(pg["name"]) >= 2
            parent_po = pg.get("parent_code")
            if parent_po:
                assert parent_po in po_codes, f"Purchasing group {pg['code']} points to unknown purch org {parent_po} in {code}"


def test_onboarding_kit_crosswalk_template():
    """Verify PIC_MAP_ORG_MASTERS.csv in onboarding kit aligns with canonical reference."""
    template_path = BACKEND_DIR / "data" / "onboarding_kit" / "templates" / "PIC_MAP_ORG_MASTERS.csv"
    assert template_path.exists(), "PIC_MAP_ORG_MASTERS.csv not found in onboarding kit"

    import csv
    text = template_path.read_text(encoding="utf-8")
    body = "\n".join(l for l in text.splitlines() if not l.startswith("#"))
    rows = list(csv.DictReader(body.splitlines()))

    assert len(rows) >= 50, "Expected at least 50 master rows across tenants in onboarding kit"
    tenants = {r["ERP_TENANT"] for r in rows}
    assert EXPECTED_TENANTS.issubset(tenants)


def test_dataset_pack_registry():
    """Verify org_masters is registered in PACKS and exports standard seed pack metadata."""
    assert "org_masters" in PACKS
    assert org_masters.KEY == "org-masters"
    assert org_masters.VERSION == "1"
    assert org_masters.CREATES_TENANT is False
    assert org_masters.READY is True
    assert hasattr(org_masters, "apply")
    assert hasattr(org_masters, "load_org_masters_for_tenant")


if __name__ == "__main__":
    test_org_masters_dataset_integrity()
    print("✓ test_org_masters_dataset_integrity passed")
    test_onboarding_kit_crosswalk_template()
    print("✓ test_onboarding_kit_crosswalk_template passed")
    test_dataset_pack_registry()
    print("✓ test_dataset_pack_registry passed")
    print("All org masters tests passed.")

