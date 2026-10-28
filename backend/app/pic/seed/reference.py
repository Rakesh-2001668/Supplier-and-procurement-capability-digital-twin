"""Tenant bootstrap: process definitions, number ranges, rule sets, SoD rules, agents, organisation.

This is the manufacturing industry template (blueprint §23) with the default Indian-rupee
approval pack (§24). All amounts are in paise.
"""
import uuid
from datetime import date
from typing import Optional

from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    Agent, CompanyCode, CostObject, Currency, NumberRange, Plant, ProcessDefinition, RuleSet, SanctionEntry, SodRule, StorageLocation, Tenant,
)
from app.pic.platform import agents as agent_catalogue
from app.pic.platform import clock
from app.pic.platform.process_defs import PROCESS_DEFINITIONS
from app.pic.seed import templates

RULES_VERSION = "2026.1"
RULES_FROM = date(2026, 4, 1)

NUMBER_RANGES = {
    # object type: (prefix, first number, padding) — chosen so the Axion signature case gets its documented numbers.
    "MRP_RUN": ("MR-", 1043, 0), "PLANNED_ORDER": ("PLO-", 55821, 0), "REQUISITION": ("REQ-", 2311, 0),
    "SOURCING_EVENT": ("RFQ-", 2231, 0), "CONTRACT": ("SA-", 5520, 0), "PURCHASE_ORDER": ("PO-", 77410, 0),
    "ASN": ("ASN-", 61207, 0), "GOODS_RECEIPT": ("GR-", 90231, 0), "INSPECTION_LOT": ("QL-", 2210, 0),
    "RETURN_DELIVERY": ("RD-", 4410, 0), "SERVICE_ENTRY": ("SES-", 3301, 0), "SAVINGS": ("SV-", 412, 4),
    "MATERIAL_REQUEST": ("MRQ-", 7731, 0), "MATERIAL": ("M-", 400001, 0), "SUPPLIER": ("SUP-", 1001, 0),
    "BANK_CHANGE": ("BCR-", 101, 0), "PAYMENT": ("PAY-", 880001, 0), "PAYMENT_RUN": ("PRUN-", 2611, 0),
    "MAVERICK_HIT": ("MAV-", 1001, 0), "CATEGORY_PLAN": ("CP-", 101, 0), "CAPA": ("CAPA-", 301, 0), "PO_CHANGE": ("PCR-", 501, 0),
    "RECONCILIATION": ("REC-", 101, 0),
}

L = 100_000 * 100   # one lakh rupees in paise
CR = 100 * L        # one crore

# CLM-01 manual contracts: value (rate) contracts for services/indirect and quantity contracts for direct material.
EXTRA_TEMPLATES = {
    "VALUE_CONTRACT": [
        {"code": "PAYMENT", "title": "Payment terms", "text": "Payment {terms} from receipt of a correct invoice and approved service entry."},
        {"code": "RATES", "title": "Rates", "text": "Services are charged at the agreed rate card; rates are fixed for the contract term."},
        {"code": "SLA", "title": "Service levels", "text": "Response and resolution times as per Schedule A; service credits apply below target."},
        {"code": "CONFIDENTIALITY", "title": "Confidentiality", "text": "Each party keeps the other's information confidential for five years."},
        {"code": "LIABILITY", "title": "Liability", "text": "Liability is capped at 100% of the annual contract value."},
        {"code": "TERMINATION", "title": "Termination", "text": "Either party may terminate with 60 days' written notice."}],
    "QUANTITY_CONTRACT": [
        {"code": "PAYMENT", "title": "Payment terms", "text": "Payment {terms} from receipt of a correct invoice."},
        {"code": "PRICE", "title": "Price", "text": "Unit prices are fixed for the contract quantity; releases are made by purchase order."},
        {"code": "DELIVERY", "title": "Delivery tolerance", "text": "Each delivery may be +{over}% / -{under}% of the ordered quantity."},
        {"code": "QUALITY", "title": "Quality", "text": "Goods conform to the drawing and specification; certificates of conformity accompany each lot."},
        {"code": "LIABILITY", "title": "Liability", "text": "Liability is capped at 100% of the contract value."},
        {"code": "TERMINATION", "title": "Termination", "text": "Either party may terminate with 90 days' written notice."}],
}
EXTRA_OBLIGATIONS = {
    "VALUE_CONTRACT": [{"party": "SUPPLIER", "description": "Monthly service-level report", "dueAfterDays": 30},
                       {"party": "BUYER", "description": "Quarterly business review", "dueAfterDays": 90}],
    "QUANTITY_CONTRACT": [{"party": "SUPPLIER", "description": "Quarterly capacity confirmation", "dueAfterDays": 90}],
}
CURRENCIES = [("INR", "Indian rupee"), ("USD", "US dollar"), ("EUR", "Euro"), ("GBP", "Pound sterling"), ("JPY", "Japanese yen")]

RULE_SETS = {
    "DMN-01": ({"bands": [
        {"upTo": 25_000 * 100, "autoChannels": ["CATALOGUE", "CONTRACT"], "chain": ["COST_OBJECT_OWNER"]},
        {"upTo": 2 * L, "chain": ["COST_OBJECT_OWNER"]},
        {"upTo": 10 * L, "chain": ["COST_OBJECT_OWNER", "DEPT_HEAD"]},
        {"upTo": None, "chain": ["COST_OBJECT_OWNER", "DEPT_HEAD", "PROCUREMENT_HEAD", "FINANCE_CONTROLLER"]}],
        "assetAdds": ["CAPEX_COMMITTEE"], "slaBusinessDays": 2}, "Requisition approval route"),
    "QUOTE-POLICY": ({"noQuoteBelow": 25_000 * 100, "oneQuoteBelow": 2 * L}, "Free-text quote policy by value"),
    "BUDGET": ({"hardFor": ["ASSET", "WBS"], "softFor": ["COST_CENTER", "ORDER"]}, "Budget control: hard stop capex/WBS, soft opex"),
    "DMN-02": ({"priceSources": ["CONTRACT", "CATALOGUE"], "supplierStatuses": ["QUALIFIED", "PREFERRED"],
                "touchlessBandMinor": 25 * L, "maxLateProb": 0.30, "maxRisk": 30}, "Touchless PO"),
    "PO-RISK": ({"lateMed": 0.15, "lateMedPts": 18, "lateHigh": 0.30, "lateHighPts": 35, "priceDevPts": 18, "notQualifiedPts": 40,
                 "valueAboveBandPts": 15, "splitPts": 25, "acctChangedPts": 12, "valueBandMinor": 25 * L, "splitWindowDays": 7,
                 "splitBandMinor": 2 * L}, "Additive explainable PO risk score"),
    "PO-APPROVAL": ({"bands": [{"upTo": 5 * L, "chain": ["BUYER"]}, {"upTo": None, "chain": ["BUYER", "PROCUREMENT_HEAD"]}],
                     "deviationChain": ["BUYER"], "confirmationSlaHours": 24}, "PO approval strategy (buyer lead = second buyer)"),
    "DMN-03": ({"pricePct": 1, "priceAbsMinor": 500 * 100, "qtyPct": 0, "sesPct": 0, "dupAmountMinor": 100, "dupDays": 3},
               "Invoice tolerances"),
    "RCV-TOLERANCE": ({"over_pct": "0", "under_pct": "0", "price_pct": "0"}, "Default receipt tolerance without contract"),
    "PURCHASE-TYPE-MATRIX": ({
        "STOCK": {"gr": True, "ir": True, "ses": False}, "NON_STOCK": {"gr": True, "ir": True, "ses": False},
        "SERVICE": {"gr": False, "ir": True, "ses": True}, "EXPENSE": {"gr": True, "ir": True, "ses": False, "receiptlessBelowMinor": 25_000 * 100},
        "ASSET": {"gr": True, "ir": True, "ses": False}, "CONSIGNMENT": {"gr": True, "ir": False, "ses": False, "ers": True},
        "SUBCONTRACTING": {"gr": True, "ir": True, "ses": False}}, "Purchase-type rules (P08)"),
    "MDM-DUP": ({"blockAt": 0.92, "warnAt": 0.75, "weights": {"description": 0.5, "mpn": 0.3, "attributes": 0.1, "classification": 0.1},
                 "domains": ["PURCHASING", "QUALITY", "FINANCE", "PLANT"]}, "Material duplicate gateway"),
    "AWARD-APPROVAL": ({"bands": [{"upTo": 50 * L, "chain": ["CATEGORY_MANAGER"]},
                                  {"upTo": None, "chain": ["CATEGORY_MANAGER", "CPO", "FINANCE_CONTROLLER"]}],
                        "approvalAboveMinor": 50 * L}, "Sourcing award approval"),
    "CONTRACT-APPROVAL": ({"thresholdMinor": 1 * CR, "above": ["LEGAL", "FINANCE_CONTROLLER", "CPO"], "below": ["CONTRACT_MANAGER"],
                           "renewalNoticeDays": 120, "consumptionThresholds": [80, 90, 100]}, "Contract approval and alerts"),
    "SUPPLIER-QUAL": ({"mandatoryCertificates": {"ALU-DIECAST": ["IATF16949", "ISO14001"]}, "minQuestionnaireScore": 70,
                       "minAuditScore": 75, "sampleApprovalRequired": ["ALU-DIECAST"], "bankApprovers": 2, "coolingOffHours": 72},
                      "Supplier qualification and bank change controls"),
    "CLM-PLAYBOOK": ({
        "templates": {"SCHEDULING_AGREEMENT": [
            {"code": "PAYMENT", "title": "Payment terms", "text": "Payment {terms} from receipt of a correct invoice."},
            {"code": "PRICE_INDEX", "title": "Price indexation",
             "text": "Prices follow the LME aluminium index, reset quarterly. Index changes within ±{band}% are absorbed by the supplier."},
            {"code": "DELIVERY", "title": "Delivery tolerance", "text": "Each schedule line may be delivered +{over}% / -{under}%."},
            {"code": "QUALITY", "title": "Quality", "text": "PPAP level 3 approval and IATF 16949 certification are maintained throughout."},
            {"code": "LIABILITY", "title": "Liability", "text": "Liability is capped at 100% of the annual contract value."},
            {"code": "TERMINATION", "title": "Termination", "text": "Either party may terminate with 90 days' written notice."}],
            **EXTRA_TEMPLATES},
        "positionRisk": {"STANDARD": 0, "FALLBACK": 30, "NON_STANDARD": 70},
        "fallbacks": {"LIABILITY": "Cap at 50% of annual value", "PAYMENT": "N45 minimum"},
        "obligations": {"SCHEDULING_AGREEMENT": [
            {"party": "BUYER", "description": "Share 13-week rolling forecast", "dueAfterDays": 7},
            {"party": "SUPPLIER", "description": "Submit quarterly capacity confirmation", "dueAfterDays": 90},
            {"party": "SUPPLIER", "description": "Renew PPAP annual layout inspection", "dueAfterDays": 330}],
            **EXTRA_OBLIGATIONS},
        "awardDefaults": {"tolerances": {"over_pct": "2", "under_pct": "5", "price_pct": "0.5"},
                          "index": {"index": "LME_AL", "base": "100.00", "band_pct": "3", "reset": "QUARTERLY"}}},
        "Clause library, playbook positions and award defaults"),
    "SPEND-GOVERNANCE": ({"classificationThreshold": "0.80", "oneTimeVendorLimitMinor": 5 * L, "groupCurrency": "INR"},
                         "Spend classification threshold, one-time-vendor limit and group currency (M01)"),
    "DEMAND-SENSING": ({"alpha": "0.3", "biasThreshold": "0.15", "horizon": 3}, "Forecast smoothing and Demand Sensing Agent bias threshold (M02)"),
    "SUPPLIER-RISK": ({"minOtifPct": 90, "maxPpm": 1000, "maxLateProb": "0.30", "certificateWarnDays": 60, "bankChangeInvoiceDays": 30,
                       "preferredOtifPct": 95}, "Supplier risk signals and preferred-status threshold (M06)"),
}

SOD_RULES = [
    ("SOD-01", "SUPPLIER_CREATE", "PO_CREATE", "supplier_id", None, "High", "Creator of a supplier master may not create POs for that supplier"),
    ("SOD-02", "SUPPLIER_BANK_CHANGE", "PAYMENT_APPROVE", "supplier_id", None, "Critical", "Whoever changes supplier bank details may not approve its payments"),
    ("SOD-02a", "SUPPLIER_BANK_CHANGE", "INVOICE_POST", "supplier_id", None, "Critical", "Whoever changes supplier bank details may not post its invoices"),
    ("SOD-03", "PO_CREATE", "GR_POST", "po_id", None, "High", "PO creator may not post the goods receipt for the same PO"),
    ("SOD-04", "PO_CREATE", "INVOICE_EXCEPTION_APPROVE", "po_id", None, "High", "PO creator may not approve invoice exceptions on the same PO"),
    ("SOD-05", "SOURCING_AWARD", "BID_SCORE", "event_id", "SOLE_EVALUATOR", "Medium", "The sole evaluator of an event may not award it"),
    ("SOD-06", "MATERIAL_REQUEST", "MATERIAL_STEWARD_APPROVE", "material_request_id", None, "Medium", "Requester may not approve the same material as steward"),
    ("SOD-07", "SAVINGS_INITIATE", "SAVINGS_VALIDATE", "initiative_id", None, "High", "Savings owner may not validate the same savings"),
]


# Screening list used by F8-03 until the licensed sanctions feed is connected. The entries are fictitious
# sample names (source SAMPLE-LIST) so screening, fuzzy matching and the automatic block can be exercised.
SANCTIONS = [
    ("Zenith Alloys Trading FZE", "SAMPLE-LIST"),
    ("Northstar Metals Export LLC", "SAMPLE-LIST"),
    ("Baltic Precision Components OOO", "SAMPLE-LIST"),
    ("Crescent Dual-Use Machinery Ltd", "SAMPLE-LIST"),
]


def deploy_process_definitions() -> None:
    with system_tx() as s:
        for d in PROCESS_DEFINITIONS:
            existing = s.get(ProcessDefinition, (d["key"], d["version"]))
            body = {"steps": d["steps"], "branches": d["branches"]}
            if existing:
                existing.definition = body
                existing.name = d["name"]
            else:
                s.add(ProcessDefinition(key=d["key"], version=d["version"], flow_id=d["flow_id"], name=d["name"], definition=body, active=True))


def create_tenant(code: str, name: str, template: str = "MANUFACTURING") -> uuid.UUID:
    with system_tx() as s:
        tenant = s.execute(select(Tenant).where(Tenant.code == code)).scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(code=code, name=name, industry_template=template)
            s.add(tenant)
            s.flush()
        return tenant.id


def bootstrap(tenant_id: uuid.UUID, *, company: tuple[str, str, str], plants: list[tuple[str, str, str]],
              cost_objects: list[tuple[str, str, str]], holidays: Optional[list[date]] = None) -> None:
    with tenant_tx(tenant_id) as s:
        if s.execute(select(NumberRange.id)).first():
            return
        template = s.get(Tenant, tenant_id).industry_template
        for object_type, (prefix, first, padding) in NUMBER_RANGES.items():
            s.add(NumberRange(tenant_id=tenant_id, object_type=object_type, prefix=prefix, next_value=first, padding=padding))
        for key, (body, description) in templates.merged_rules(RULE_SETS, template).items():
            s.add(RuleSet(tenant_id=tenant_id, key=key, version=RULES_VERSION, effective_from=RULES_FROM, body=body, description=description))
        for code, name_ in CURRENCIES:
            s.add(Currency(tenant_id=tenant_id, code=code, name=name_, decimals=0 if code == "JPY" else 2))
        for code, a, b, scope, condition, risk, description in SOD_RULES:
            s.add(SodRule(tenant_id=tenant_id, code=code, action_a=a, action_b=b, scope=scope, condition=condition, risk=risk,
                          mode="BLOCK", description=description))
        for code, name_, module, purpose, level, role, limit in agent_catalogue.CATALOGUE:
            s.add(Agent(tenant_id=tenant_id, code=code, name=name_, module=module, purpose=purpose, autonomy_level=level,
                        run_as_role=role, value_limit_minor=limit, categories=[], kill_switch=False, model_version=f"{code.lower()}-v1",
                        min_acceptance_rate=0.7))
        for name_, source in SANCTIONS:
            s.add(SanctionEntry(tenant_id=tenant_id, name=name_, source=source))
        s.flush()
        from app.pic.services import spend
        spend.ensure_taxonomy(s, tenant_id)
        cc_code, cc_name, gstin = company
        s.add(CompanyCode(tenant_id=tenant_id, code=cc_code, name=cc_name, gstin=gstin, currency="INR"))
        for code, name_, state in plants:
            s.add(Plant(tenant_id=tenant_id, code=code, name=name_, company_code=cc_code, state_code=state,
                        working_days=[0, 1, 2, 3, 4, 5], holidays=holidays or []))
            s.add(StorageLocation(tenant_id=tenant_id, plant=code, code="0001", name="Raw material & bought-out parts"))
        for type_, code, name_ in cost_objects:
            s.add(CostObject(tenant_id=tenant_id, type=type_, code=code, name=name_, company_code=cc_code))


def ensure_extensions(tenant_id: uuid.UUID) -> list[str]:
    """Bring a tenant bootstrapped by an earlier release up to date (idempotent): number ranges, rule sets,
    playbook templates, currencies, agents, taxonomy and maverick rules. Existing rule versions are never edited;
    a changed rule gets a new effective-dated version (P14)."""
    from app.pic.services import spend
    added = []
    with tenant_tx(tenant_id) as s:
        if not s.execute(select(NumberRange.id)).first():
            return added
        tenant = s.get(Tenant, tenant_id)
        have = set(s.execute(select(NumberRange.object_type)).scalars())
        for object_type, (prefix, first, padding) in NUMBER_RANGES.items():
            if object_type not in have:
                s.add(NumberRange(tenant_id=tenant_id, object_type=object_type, prefix=prefix, next_value=first, padding=padding))
                added.append(f"number range {object_type}")
        current = {}
        for rs in s.execute(select(RuleSet).where(RuleSet.company_code.is_(None), RuleSet.plant.is_(None), RuleSet.category.is_(None),
                                                  RuleSet.purchase_type.is_(None)).order_by(RuleSet.effective_from)).scalars():
            current[rs.key] = rs
        for key, (body, description) in templates.merged_rules(RULE_SETS, tenant.industry_template).items():
            if key not in current:
                s.add(RuleSet(tenant_id=tenant_id, key=key, version=RULES_VERSION, effective_from=RULES_FROM, body=body, description=description))
                added.append(f"rule set {key}")
            elif key == "CLM-PLAYBOOK" and set(body["templates"]) - set(current[key].body.get("templates", {})):
                merged = {**current[key].body, "templates": {**body["templates"], **current[key].body["templates"]},
                          "obligations": {**body["obligations"], **current[key].body.get("obligations", {})}}
                s.add(RuleSet(tenant_id=tenant_id, key=key, version="2026.2", effective_from=max(clock.today(), current[key].effective_from),
                              body=merged, description=description + " (value and quantity contract templates)"))
                added.append("rule set CLM-PLAYBOOK@2026.2")
        codes = set(s.execute(select(Currency.code)).scalars())
        for code, name_ in CURRENCIES:
            if code not in codes:
                s.add(Currency(tenant_id=tenant_id, code=code, name=name_, decimals=0 if code == "JPY" else 2))
                added.append(f"currency {code}")
        agents_have = set(s.execute(select(Agent.code)).scalars())
        for code, name_, module, purpose, level, role, limit in agent_catalogue.CATALOGUE:
            if code not in agents_have:
                s.add(Agent(tenant_id=tenant_id, code=code, name=name_, module=module, purpose=purpose, autonomy_level=level,
                            run_as_role=role, value_limit_minor=limit, categories=[], kill_switch=False, model_version=f"{code.lower()}-v1",
                            min_acceptance_rate=0.7))
                added.append(f"agent {code}")
        s.flush()
        spend.ensure_taxonomy(s, tenant_id)
    return added
