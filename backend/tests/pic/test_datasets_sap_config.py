"""D21 SAP mapping configuration (seed/datasets/sap_config.py): explicit, editable rule versions for AXN and KAC from the mock SAP customizing
(backend/data/erp_mock/SAP_CONFIG), consistent with the tenants' company codes and purchasing organisations, and used by the connector."""
import json
from datetime import date

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import RuleSet, Tenant
from app.pic.platform import sap_customizing as cz, sap_defaults as sd
from app.pic.seed import datasets
from app.pic.seed.datasets import sap_config

from .conftest import PASSWORD


@pytest.fixture(scope="module")
def loaded():
    if datasets.loaded("KAC", "erp-client-kac") is None:                 # the KAC tenant comes from its SAP cutover (D10)
        assert datasets.apply_pack("erp_client_kac", PASSWORD)[0]["status"] in ("LOADED", "ALREADY_LOADED")
    return {r["tenant"]: r for r in datasets.apply_pack("sap_config", PASSWORD)}


def tenant_id(code):
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == code)).scalar_one()


def test_the_pack_is_registered_with_the_conventions():
    assert "sap_config" in datasets.PACKS and datasets.PACKS.index("sap_config") > datasets.PACKS.index("org_masters")
    pack = datasets.load("sap_config")
    assert (pack.KEY, pack.VERSION, pack.TENANTS, pack.READY, pack.CREATES_TENANT, pack.REQUIRES) == ("sap-config", "1", ("AXN", "KAC"), True, False, {})


def test_the_rule_plan_is_complete_valid_and_consistent_with_the_mock_customizing():
    c = cz.load()
    data = json.loads(sap_config.RULES_FILE.read_text(encoding="utf-8"))
    for tenant in ("AXN", "KAC"):
        plan = sap_config.rule_plan(tenant)
        assert {(p["key"], p["companyCode"]) for p in plan} >= {(sd.OUTLINE_KEY, None), (sd.REVERSAL_KEY, None), (sd.SCF_KEY, None)}
        for item in plan:
            assert sd.validate(item["key"], item["body"]) == [] and item["effectiveFrom"] == date.fromisoformat(data["effectiveFrom"])
            if item["key"] == sd.OUTLINE_KEY:
                assert set(item["body"]) == set(sd.DEFAULTS[sd.OUTLINE_KEY])          # complete bodies: the engine does not merge versions
                assert set(item["body"]["documentTypes"].values()) <= c.document_types["K"] | c.document_types["L"]
                assert item["body"]["textItemMaterialGroup"] in c.material_groups
            if item["key"] == sd.OUTLINE_KEY and item["companyCode"]:
                orgs = {r["EKORG"]: r["BUKRS"] for r in cz._rows("T024E.csv") if r["TENANT"] == tenant}
                groups = {r["EKGRP"] for r in cz._rows("T024.csv") if r["TENANT"] == tenant}
                assert orgs[item["body"]["purchasingOrg"]] == item["companyCode"] and item["body"]["purchasingGroup"] in groups
                assert item["version"].endswith(f"-{item['companyCode']}")
            if item["key"] == sd.REVERSAL_KEY:
                assert item["body"]["reversalReason"] in c.reversal_reasons and item["body"]["closedPeriodReason"] in c.reversal_reasons
            if item["key"] == sd.SCF_KEY:
                financier = item["body"]["financiers"]["PROGRAMME"]
                companies = {r["BUKRS"] for r in cz._rows("T001.csv") if r["TENANT"] == tenant}
                assert c.financiers[financier["businessPartner"]] == companies and financier["paymentMethod"] in c.payment_methods
                assert item["body"]["documentType"] in c.fi_document_types
    assert sap_config.rule_plan("CON") == []


def test_a_broken_rule_file_is_refused_before_anything_is_written(monkeypatch, tmp_path):
    broken = json.loads(sap_config.RULES_FILE.read_text(encoding="utf-8"))
    broken["tenants"]["AXN"][0]["body"]["documentTypes"]["SOW"] = "LP"
    path = tmp_path / "PIC_RULES.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    monkeypatch.setattr(sap_config, "RULES_FILE", path)
    with pytest.raises(ValueError, match="SOW is LP, which is not in contractTypes"):
        sap_config.rule_plan("AXN")


def test_the_pack_writes_the_rules_for_axn_and_kac_and_the_connector_uses_them(loaded):
    assert loaded["AXN"]["status"] in ("LOADED", "ALREADY_LOADED") and loaded["KAC"]["status"] in ("LOADED", "ALREADY_LOADED")
    expected = {"AXN": {"1000": ("PO10", "G01"), "1100": ("PO30", "G04")}, "KAC": {"1000": ("PO10", "G03"), "2000": ("PO21", "G01")}}
    for tenant, companies in expected.items():
        with tenant_tx(tenant_id(tenant)) as s:
            rows = s.execute(select(RuleSet).where(RuleSet.version.like("D21-%"))).scalars().all()
            assert len(rows) == len(sap_config.rule_plan(tenant))
            for company, (org, group) in companies.items():
                config = sd.resolve(s, sd.OUTLINE_KEY, company)
                assert (config["purchasingOrg"], config["purchasingGroup"], config["textItemMaterialGroup"]) == (org, group, "SERVICES")
                assert config.ref.startswith(f"{sd.OUTLINE_KEY}@D21-2026.1-{company}")
                assert sd.api_of(config, "SCHEDULING_AGREEMENT") == "SCHEDULING_AGREEMENT" and sd.skip_reason(config, "NDA")
            scf = sd.resolve(s, sd.SCF_KEY, "1000")
            assert scf.ref == f"{sd.SCF_KEY}@D21-2026.1" and scf["financiers"]["PROGRAMME"]["businessPartner"] in cz.load().financiers
            assert sd.resolve(s, sd.REVERSAL_KEY, "1000")["reversalReason"] == "01"
    if loaded["AXN"]["status"] == "LOADED":
        assert loaded["AXN"]["summary"]["counts"]["ruleVersions"] == len(sap_config.rule_plan("AXN"))


def test_the_pack_runs_once_and_a_forced_rerun_writes_nothing_twice(loaded):
    assert {r["tenant"]: r["status"] for r in datasets.apply_pack("sap_config", PASSWORD)} == {"AXN": "ALREADY_LOADED", "KAC": "ALREADY_LOADED"}
    again = datasets.apply_pack("sap_config", PASSWORD, tenants=["AXN"], force=True)
    assert again[0]["status"] == "LOADED" and again[0]["summary"]["counts"] == {"ruleVersions": 0, "alreadyThere": len(sap_config.rule_plan("AXN"))}
    assert sap_config.apply("NO-SUCH-TENANT", PASSWORD) == {"notes": ["NO-SUCH-TENANT: tenant not found"], "counts": {}}
