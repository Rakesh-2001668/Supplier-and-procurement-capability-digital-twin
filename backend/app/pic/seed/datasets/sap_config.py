"""D21 SAP S/4HANA mapping configuration for AXN and KAC (MOCK customizing, backend/data/erp_mock/SAP_CONFIG).

Writes the SAP mapping rules of the live connector as explicit, editable tenant rule versions (platform/sap_defaults.py), so the values the
connector sends are visible in the rules administration instead of being code defaults:

  SAP-OUTLINE-AGREEMENT  tenant-wide: MK / WK / LP document types, master agreements and NDAs not sent, text items with material group
                         SERVICES; per company code (AXN 1000, 1100; KAC 1000, 2000): purchasing organisation and group of the mock
                         customizing (T024E / T024, the same codes as the PIC org masters D19)
  SAP-PAYMENT-REVERSAL   reason 01 with the original posting date, 02 when the period is closed, reset of the cleared items
  SAP-SCF-FINANCING      document type KA, posting keys 21 / 31 / 50, the mock SCF financier business partner of the tenant (BP_FINANCIER)

The bodies come from SAP_CONFIG/PIC_RULES.json. A company-code version is written complete (the tenant-wide body with the company's values):
the rules engine uses the most specific version alone, it does not merge versions. Every body is validated by sap_defaults.validate before it
is written. Nothing else changes: documents already posted keep what they were posted with. Existing versions are never edited (P14); a version
label that already exists is skipped, so the pack can run again after a rebuild.
"""
import copy
import json
from datetime import date

from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import RuleSet, Tenant
from app.pic.platform import audit, sap_customizing, sap_defaults

KEY = "sap-config"
VERSION = "1"
TITLE = "D21 SAP S/4HANA mapping configuration: outline agreement types, reversal reason, SCF financier (AXN and KAC, MOCK customizing)"
TENANTS = ("AXN", "KAC")
CREATES_TENANT = False
READY = True
REQUIRES: dict = {}        # rule versions only: needs the tenant's bootstrap (reference.RULE_SETS), not any other pack

RULES_FILE = sap_customizing.DIRECTORY / "PIC_RULES.json"


def rule_plan(tenant_code: str) -> list[dict]:
    """The rule versions the pack writes for a tenant: [{"key", "companyCode", "version", "effectiveFrom", "body"}] with complete bodies."""
    data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    entries = data["tenants"].get(tenant_code) or []
    base = {e["key"]: e["body"] for e in entries if e.get("companyCode") is None}
    plan = []
    for entry in entries:
        company = entry.get("companyCode")
        body = copy.deepcopy(entry["body"]) if company is None else {**copy.deepcopy(base.get(entry["key"], {})), **entry["body"]}
        problems = sap_defaults.validate(entry["key"], body)
        if problems:
            raise ValueError(f"SAP_CONFIG/PIC_RULES.json {tenant_code} {entry['key']} {company or ''}: {'; '.join(problems)}")
        plan.append({"key": entry["key"], "companyCode": company, "body": body, "effectiveFrom": date.fromisoformat(data["effectiveFrom"]),
                     "version": data["version"] + (f"-{company}" if company else "")})
    return plan


def apply(tenant_code: str, password: str) -> dict:
    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == tenant_code)).scalar_one_or_none()
    if tenant_id is None:
        return {"notes": [f"{tenant_code}: tenant not found"], "counts": {}}
    plan = rule_plan(tenant_code)
    counts = {"ruleVersions": 0, "alreadyThere": 0}
    notes = []
    with tenant_tx(tenant_id) as s:
        for item in plan:
            if s.execute(select(RuleSet.id).where(RuleSet.key == item["key"], RuleSet.version == item["version"])).first():
                counts["alreadyThere"] += 1
                continue
            description = sap_defaults.BODIES[item["key"]][1] + (f" - company code {item['companyCode']}" if item["companyCode"] else "") + " (MOCK customizing D21)"
            rule = RuleSet(tenant_id=tenant_id, key=item["key"], version=item["version"], effective_from=item["effectiveFrom"],
                           company_code=item["companyCode"], body=item["body"], description=description)
            s.add(rule)
            s.flush()
            audit.record(s, "RULE_SET", rule.id, "VERSION_CREATED", object_ref=f"{rule.key}@{rule.version}",
                         after={"companyCode": item["companyCode"], "body": item["body"]}, actor="configuration",
                         reason="D21 SAP mapping configuration (MOCK customizing, confirm in the client's sandbox)")
            counts["ruleVersions"] += 1
            notes.append(f"{item['key']}@{item['version']}" + (f" for company code {item['companyCode']}" if item["companyCode"] else " (tenant-wide)"))
    return {"notes": notes, "counts": counts}
