"""Tenant bootstrap: process definitions, number ranges, rule sets, SoD rules, agents, organisation.

This is the manufacturing industry template (blueprint §23) with the default Indian-rupee
approval pack (§24). All amounts are in paise.
"""
import copy
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
from app.pic.platform import finance_defaults, inventory_defaults, job_defaults, p2p_defaults, sap_defaults, sourcing_defaults
from app.pic.platform.process_defs import baseline
from app.pic.seed import clause_library, templates

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
    "RECONCILIATION": ("REC-", 101, 0), "CONTRACT_AMENDMENT": ("CA-", 101, 0), "PAYMENT_FILE": ("PF-", 1001, 0),
    "SUPPLIER_CHANGE": ("SMC-", 101, 0), "INTEGRATION_BATCH": ("IB-", 101, 0), "PUNCHOUT": ("PUN-", 1001, 0),
    # wave 1 (engineer C1): material change requests, rebates, clause extraction, supplier development plans
    # inventory (M09 stock): stock postings, physical-inventory documents, reservations
    "STOCK_POSTING": ("STP-", 1001, 0), "PHYSICAL_INVENTORY": ("PHI-", 1001, 0), "STOCK_RESERVATION": ("RSV-", 1001, 0),
    "MATERIAL_CHANGE": ("MCR-", 101, 0), "REBATE_AGREEMENT": ("RBA-", 101, 0), "REBATE_SETTLEMENT": ("RBS-", 101, 0),
    "CLAUSE_EXTRACTION": ("CLX-", 101, 0), "DEVELOPMENT_PLAN": ("SDP-", 101, 0),
    # flow fixes B6 (migration 0024): own range per sourcing event type and per contract type (RFQ and scheduling agreements keep theirs)
    "SOURCING_EVENT_RFI": ("RFI-", 1101, 0), "SOURCING_EVENT_RFP": ("RFP-", 3101, 0), "SOURCING_EVENT_AUC": ("AUC-", 4101, 0),
    "CONTRACT_QC": ("QC-", 6101, 0), "CONTRACT_VC": ("VC-", 6501, 0), "CONTRACT_RC": ("RC-", 7101, 0), "CONTRACT_SOW": ("SOW-", 7501, 0),
    "CONTRACT_MA": ("MA-", 8101, 0), "CONTRACT_NDA": ("NDA-", 8501, 0),
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
CURRENCIES = [
    ("INR", "Indian rupee"), ("USD", "US dollar"), ("EUR", "Euro"), ("GBP", "Pound sterling"), ("JPY", "Japanese yen"),
]

RULE_SETS = {
    **job_defaults.BODIES,  # wave 1 platform: PAYMENT-RUN, MRP-SCHEDULE, PRIVACY-RETENTION, DELEGATION, AI-CONTROL
    **p2p_defaults.BODIES,  # wave 1 P2P completion: ONE-TIME-VENDOR, PO-PRICE-CHECK, DEBIT-NOTE, EARLY-PAYMENT, MANDATORY-FIELDS, ...
    **inventory_defaults.BODIES,  # inventory: INVENTORY-POSTING, INVENTORY-COUNT, INVENTORY-RESERVATION, INVENTORY-ALERTS
    **sourcing_defaults.BODIES,  # strategic sourcing: SOURCING-POLICY, SOURCING-TCO (M05)
    **sap_defaults.BODIES,  # live SAP mapping: SAP-OUTLINE-AGREEMENT, SAP-PAYMENT-REVERSAL, SAP-SCF-FINANCING
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
                     "deviationChain": ["BUYER"], "confirmationSlaHours": 24,
                     # BP §14.1 approval by value and deviation: a change order that deviates from the contract price, or
                     # raises the PO into a higher band, is approved before the new version is sent.
                     "changeApproval": {"onPriceDeviation": True, "onBandIncrease": True}},
                    "PO approval strategy (buyer lead = second buyer)"),
    "DMN-03": ({"pricePct": 1, "priceAbsMinor": 500 * 100, "qtyPct": 0, "sesPct": 0, "dupAmountMinor": 100, "dupDays": 3},
               "Invoice tolerances"),
    "MSME": (finance_defaults.MSME_DEFAULT, "MSME payment rule: micro / small suppliers are paid within 45 days of acceptance (MSMED Act s.15-16)"),
    "TDS": (finance_defaults.TDS_DEFAULT, "TDS sections, rates and thresholds withheld when a supplier is paid (illustrative until the tax team confirms)"),
    "TDS-195": (finance_defaults.TDS_195_DEFAULT, "Section 195 withholding on payments to non-residents: Act rates, surcharge, cess, MOCK DTAA table, "
                "no-PAN rule, Form 15CA/15CB threshold (MOCK until the client's chartered accountant confirms)"),
    "PARTIAL-PAYMENT": (finance_defaults.PARTIAL_PAYMENT_DEFAULT, "Partial payments of an invoice across payment runs: minimum amount, "
                        "number of payments, reason"),
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
    "SPEND-GOVERNANCE": ({"classificationThreshold": "0.80", "oneTimeVendorLimitMinor": 5 * L, "groupCurrency": "INR",
                          "aggregationMinSuppliers": 4, "aggregationSavingPct": "3"},
                         "Spend classification threshold, one-time-vendor limit, group currency and aggregation-opportunity assumptions (M01)"),
    "KPI-THRESHOLDS": ({"overrides": {}, "minutesSavedPerAgentRun": 6},
                       "KPI target / warn overrides per KPI code and the minutes an executed agent run saves (BP Table 28, M12 hours saved)"),
    "DEMAND-SENSING": ({"alpha": "0.3", "biasThreshold": "0.15", "horizon": 3}, "Forecast smoothing and Demand Sensing Agent bias threshold (M02)"),
    "LLM-GATEWAY": ({"ratePerMinute": 30, "monthlyBudgetMicro": 0, "retentionDays": 90}, "LLM gateway: calls per minute, monthly cost budget (millionths; 0 = unlimited) and call-log retention (TD 13)"),
    "SUPPLIER-RISK": ({"minOtifPct": 90, "maxPpm": 1000, "maxLateProb": "0.30", "certificateWarnDays": 60, "bankChangeInvoiceDays": 30,
                       "preferredOtifPct": 95}, "Supplier risk signals and preferred-status threshold (M06)"),
    "CONTRACT-AMENDMENT": ({"thresholdMinor": 1 * CR, "above": ["LEGAL", "FINANCE_CONTROLLER"], "below": ["CONTRACT_MANAGER"],
                            "termination": ["LEGAL", "CPO"], "noticeDays": 90}, "Contract amendment and termination approvals (M07)"),
    "AUCTION": ({"minDecrementPct": "0.5", "extensionMinutes": 5, "triggerMinutes": 2, "showRank": True, "showBestPrice": False},
                "Reverse auction rules: minimum decrement, soft close and supplier feedback (M05)"),
    "EWAY-BILL": ({"requiredAboveMinor": 50_000 * 100, "kmPerDay": 200, "format": "^[0-9]{12}$"}, "E-way bill on ASN for goods movements (M09)"),
    "PAYMENT-FILE": ({"format": "ISO20022_PAIN001", "debtorName": None, "debtorAccountRef": None, "debtorIfsc": None},
                     "Bank payment file; debtor account details are configured per tenant (M10)"),
    "SUPPLIER-MASTER-CHANGE": ({"approvers": ["FINANCE_CONTROLLER", "SUPPLIER_MANAGER"], "fieldGroups": ["TAX", "ADDRESS", "CONTACT"]},
                               "Supplier tax-ID, address and contact changes: two approvers, never the requester (MDM-04)"),
    "SUPPLIER-INVITATION": ({"validDays": 14}, "Supplier self-registration invitation validity (F8-01)"),
    "CATEGORY-BUDGET": ({"mode": "SOFT", "warnAtPct": 90}, "Category-plan budget check at requisition submit (M01/M04)"),
    "PUNCHOUT": ({"sessionMinutes": 30, "protocols": ["CXML", "OCI"]}, "Punch-out session rules (M04)"),
    # wave 1 (engineer C1)
    "MATERIAL-FIELD-OWNERSHIP": ({
        "fields": {"description": "PURCHASING", "material_group": "PURCHASING", "category": "PURCHASING", "mpn": "PURCHASING",
                   "attributes": "PURCHASING", "base_uom": "PLANT", "valuation_class": "FINANCE", "hsn_code": "FINANCE", "gst_rate": "FINANCE",
                   "standard_price_minor": "FINANCE", "quality_managed": "QUALITY", "mrp_type": "PLANT", "lot_size_policy": "PLANT",
                   "lot_size_qty": "PLANT", "min_lot": "PLANT", "max_lot": "PLANT", "pack_size": "PLANT", "safety_stock": "PLANT",
                   "planned_delivery_days": "PLANT", "gr_processing_days": "PLANT"},
        "byType": {"SERVICE": {"notApplicable": ["base_uom", "quality_managed", "mrp_type", "lot_size_policy", "lot_size_qty", "min_lot", "max_lot",
                                                 "pack_size", "safety_stock", "planned_delivery_days", "gr_processing_days"], "alsoApprove": {}},
                   "NON_STOCK": {"notApplicable": ["mrp_type", "lot_size_policy", "lot_size_qty", "min_lot", "max_lot", "safety_stock"], "alsoApprove": {}},
                   "STOCK": {"notApplicable": [], "alsoApprove": {"base_uom": ["QUALITY", "FINANCE"], "valuation_class": ["PLANT"],
                                                                  "hsn_code": ["PURCHASING"], "gst_rate": ["PURCHASING"], "quality_managed": ["PLANT"]}}},
        "outsideOwnership": "ROUTE", "distinctApprovers": True, "domains": ["PURCHASING", "QUALITY", "FINANCE", "PLANT"]},
        "Material change requests: field to owning steward domain per material type, routing of changes outside the requester's domain (BP M03)"),
    "AWARD-RISK": ({"maxRiskScore": None, "maxSingleSourcePct": None, "maxConditionalSharePct": None, "noDataScore": 50},
                   "Risk constraints for award optimisation and the score of data-driven bid criteria; an event overrides them in its constraints (M05)"),
    "SUPPLIER-RISK-EXT": ({"riskPoints": {"Critical": 40, "High": 25, "Medium": 10, "Low": 3}, "highTierPoints": 15, "maxScore": 100,
                           "concentration": {"windowMonths": 12, "minSpendMinor": 10_00_000 * 100, "supplierSharePct": 30, "regionSharePct": 50,
                                             "categoryRegionSharePct": 70},
                           "singleSource": {"enabled": True},
                           "cyber": {"requiredSegments": ["STRATEGIC", "BOTTLENECK"], "minScore": 60, "warnDays": 60,
                                     "certificateTypes": ["ISO27001", "SOC2"]}},
                          "Supplier risk score points, spend / region concentration, single-source and cyber thresholds (M06)"),
    "SUPPLIER-SEGMENTATION": ({"windowMonths": 12, "highSpendSharePct": 5, "highRiskScore": 40, "criticalQuadrants": ["STRATEGIC", "BOTTLENECK"]},
                              "Supplier segment from spend share and risk / criticality (M06)"),
    "SUPPLIER-ASSESSMENT": ({"validDays": 365, "minAcceptScore": {"ESG": 40, "CYBER": 40}}, "ESG and cyber questionnaires: validity (M06)"),
    "CLAUSE-EXTRACTION": ({"autoApplyAbove": "0.85"}, "Clause extraction on contract migration: confidence from which a clause is written without review (TD 12.4)"),
    "NOTIFICATIONS": ({"email": False, "kinds": ["TASK_ASSIGNED", "TASK_ESCALATED", "RECOMMENDATION", "PO_TRANSMITTED", "INVOICE_EXCEPTION",
                                                 "CHANGE_REQUEST", "CLARIFICATION_ANSWERED", "CONTRACT_EXPIRING",
                                                 "CONTRACT_AMENDED", "CONTRACT_TERMINATED", "SOURCING_CANCELLED", "PO_CANCELLED",
                                                 "SOURCING_AWARDED", "SOURCING_NOT_AWARDED", "CONTRACT_CONSUMPTION"]},
                      "In-app notifications; e-mail delivery switches on when SMTP is configured"),
    "ERP-TARGET": ({"system": "SAP_S4"}, "ERP every posting goes to (connector registry); add a company-code-scoped version to route one company elsewhere"),
    "MFA": ({"enforce": False, "requiredRoles": ["TENANT_ADMIN", "FINANCE_CONTROLLER", "CFO", "CPO", "PROCUREMENT_HEAD", "COST_OBJECT_OWNER", "DEPT_HEAD",
                                                 "CAPEX_COMMITTEE", "AP_CLERK", "INVENTORY_CONTROLLER"], "issuer": "AlphaHelion PIC"},
            "MFA (TOTP) for approvers, finance and admins (§14); set enforce=true per tenant once users have enrolled"),
    "ESCALATION": ({"managerAtLevel": 2, "managers": {
        "COST_OBJECT_OWNER": "DEPT_HEAD", "DEPT_HEAD": "PROCUREMENT_HEAD", "PROCUREMENT_HEAD": "CPO", "FINANCE_CONTROLLER": "CPO",
        "BUYER": "PROCUREMENT_HEAD", "CATEGORY_MANAGER": "CPO", "SUPPLIER_MANAGER": "PROCUREMENT_HEAD", "CONTRACT_MANAGER": "PROCUREMENT_HEAD",
        "SERVICE_OWNER": "DEPT_HEAD", "AP_CLERK": "FINANCE_CONTROLLER", "RECEIVER": "DEPT_HEAD", "QUALITY_INSPECTOR": "DEPT_HEAD",
        "INVENTORY_CONTROLLER": "DEPT_HEAD"},
        "keepScopeFor": ["DEPT_HEAD"], "mode": {"2": "ADD", "default": "REASSIGN"}},
        "Approval SLA escalation (TD §8): level 1 reminds the approvers; level 2 adds the manager role as a candidate; level 3 and beyond "
        "reassigns the task to the manager role (the original candidates lose it). mode: ADD | REASSIGN, as one value or per level; "
        "four-eyes exclusions are kept"),
    # ---- wave 1 (platform): attribute-based access control on commands, SoD exception path
    "ABAC": ({"mode": "ENFORCE", "dimensions": {"company_code": "company_codes", "plant": "plants", "category": "categories"},
              "valueLimitAttribute": "value_limit_minor", "limitsAttribute": "approval_limits",
              "actions": {
                  "REQ_SUBMIT": {"check": ["company_code", "plant"]},
                  "REQ_APPROVE": {"check": ["company_code", "plant"], "valueLimit": True},
                  "PO_CREATE": {"check": ["company_code", "plant"]},
                  "PO_RELEASE": {"check": ["company_code", "plant"], "valueLimit": True},
                  "PO_APPROVE": {"check": ["company_code", "plant"], "valueLimit": True},
                  "GR_POST": {"check": ["company_code", "plant"]},
                  "INVOICE_APPROVE": {"check": ["company_code"], "valueLimit": True},
                  "INVOICE_POST": {"check": ["company_code"], "valueLimit": True},
                  "PAYMENT_RUN": {"check": ["company_code"], "valueLimit": True},
                  "CONTRACT_SIGN": {"check": ["company_code"], "valueLimit": True},
                  "AWARD_APPROVE": {"check": ["category"], "valueLimit": True},
                  "SUPPLIER_CHANGE": {"check": ["category"]},
                  "MASTER_CHANGE": {"check": ["company_code", "plant"]},
                  "STOCK_MOVE": {"check": ["company_code", "plant"]},
                  "INVENTORY_POST": {"check": ["company_code", "plant"]},
                  "INVENTORY_APPROVE": {"check": ["company_code", "plant"], "valueLimit": True},
                  "INVENTORY_COUNT": {"check": ["company_code", "plant"]},
                  "INVENTORY_RESERVE": {"check": ["company_code", "plant"]}}},
             "ABAC on commands (SEC-AZ): company code, plant, category and value limit from the user attributes; "
             "mode ENFORCE | AUDIT (log only) | OFF. A user without the attribute is not restricted on that dimension."),
    "SOD-MITIGATION": ({"approvers": {"Low": ["PROCUREMENT_HEAD"], "Medium": ["PROCUREMENT_HEAD"], "High": ["PROCUREMENT_HEAD", "CPO"]},
                        "maxValidityHours": {"Low": 168, "Medium": 72, "High": 24}, "maxUses": {"Low": 5, "Medium": 3, "High": 1},
                        "compensatingControls": {
                            "default": "The approver reviews every transaction the actor completes under this exception within five "
                                       "working days and confirms the review in the audit trail.",
                            "SOD-03": "A second person re-counts the receipt and the receiver's supervisor countersigns the goods receipt note."},
                        "minJustificationLength": 20, "slaBusinessDays": 2},
                       "SoD exception path: who may approve a mitigation by risk (Critical is never mitigable), maximum validity "
                       "and uses, compensating control text. Applies to SoD rules in mode MITIGATE."),
}

# The clause library (illustrative sample until the client's legal-approved text is loaded, see seed/clause_library.py) joins the playbook.
_playbook_body, _playbook_description = RULE_SETS["CLM-PLAYBOOK"]
RULE_SETS["CLM-PLAYBOOK"] = (clause_library.merge_into(_playbook_body, clause_library.playbook_patch()),
                             _playbook_description + " (clause library: illustrative sample)")

SOD_RULES = [
    ("SOD-01", "SUPPLIER_CREATE", "PO_CREATE", "supplier_id", None, "High", "Creator of a supplier master may not create POs for that supplier"),
    ("SOD-02", "SUPPLIER_BANK_CHANGE", "PAYMENT_APPROVE", "supplier_id", None, "Critical", "Whoever changes supplier bank details may not approve its payments"),
    ("SOD-02a", "SUPPLIER_BANK_CHANGE", "INVOICE_POST", "supplier_id", None, "Critical", "Whoever changes supplier bank details may not post its invoices"),
    ("SOD-03", "PO_CREATE", "GR_POST", "po_id", None, "High", "PO creator may not post the goods receipt for the same PO"),
    ("SOD-04", "PO_CREATE", "INVOICE_EXCEPTION_APPROVE", "po_id", None, "High", "PO creator may not approve invoice exceptions on the same PO"),
    ("SOD-05", "SOURCING_AWARD", "BID_SCORE", "event_id", "SOLE_EVALUATOR", "Medium", "The sole evaluator of an event may not award it"),
    ("SOD-06", "MATERIAL_REQUEST", "MATERIAL_STEWARD_APPROVE", "material_request_id", None, "Medium", "Requester may not approve the same material as steward"),
    ("SOD-07", "SAVINGS_INITIATE", "SAVINGS_VALIDATE", "initiative_id", None, "High", "Savings owner may not validate the same savings"),
    ("SOD-08", "INVOICE_CAPTURE", "INVOICE_APPROVE", "invoice_id", None, "High", "Whoever captured an invoice may not approve it (four-eyes)"),
    ("SOD-09", "INVOICE_APPROVE", "PAYMENT_APPROVE", "invoice_id", None, "High", "Whoever approved an invoice may not release its payment"),
    ("SOD-10", "INVENTORY_POST", "INVENTORY_APPROVE", "posting_id", None, "High", "Whoever submitted a stock posting may not approve it (maker-checker)"),
    ("SOD-11", "INVENTORY_COUNT", "INVENTORY_COUNT_APPROVE", "count_id", None, "High",
     "Whoever counted or recounted stock may not approve the differences of that count"),
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
    """Version 1 of the nine flows (platform/process_defs.py), shared by all tenants. Idempotent; never touches the versions
    tenants published themselves."""
    with system_tx() as s:
        for d in baseline():
            existing = s.get(ProcessDefinition, (d["key"], d["version"]))
            if existing:
                existing.definition = d["definition"]
                existing.name = d["name"]
                existing.status, existing.active = "ACTIVE", True
            else:
                s.add(ProcessDefinition(key=d["key"], version=d["version"], flow_id=d["flow_id"], name=d["name"],
                                        definition=d["definition"], active=True, status="ACTIVE", published_at=clock.now()))


def _is_bundled_seed(frame_depth: int = 2) -> bool:
    import sys
    module = sys._getframe(frame_depth).f_globals.get("__name__", "")
    return module.startswith(("app.pic.seed", "app.pic.tools", "__main__"))


def create_tenant(code: str, name: str, template: str = "MANUFACTURING", *, mfa_enforce: Optional[bool] = None) -> uuid.UUID:
    """Create (or find) a tenant. ``mfa_enforce`` sets the MFA rule of the tenant's bootstrap: unset, tenants created by the
    bundled demo seeds and tools (app.pic.seed, app.pic.tools) stay unenforced until the operator flips them, and every other
    new tenant starts with enforce=true for the approver, finance and admin roles."""
    enforce = (not _is_bundled_seed()) if mfa_enforce is None else mfa_enforce
    with system_tx() as s:
        tenant = s.execute(select(Tenant).where(Tenant.code == code)).scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(code=code, name=name, industry_template=template, mfa_enforce=enforce)
            s.add(tenant)
            s.flush()
        return tenant.id


def _with_mfa_default(rules: dict, tenant: Tenant) -> dict:
    """The tenant's rule bodies with the MFA default of its creation applied (copy; RULE_SETS is never modified)."""
    if not tenant.mfa_enforce or "MFA" not in rules:
        return rules
    body, description = rules["MFA"]
    return {**rules, "MFA": ({**body, "enforce": True}, description.replace("set enforce=true per tenant once users have enrolled", "enforced from tenant creation"))}


def _with_invoice_bands(rules: dict, enabled: bool) -> dict:
    """The tenant's rule bodies with the default invoice value bands (p2p_defaults.INVOICE_APPROVAL_BANDS: finance controller from 10 lakh,
    finance controller and CFO from 1 crore) in rule INVOICE-APPROVAL (copy; RULE_SETS is never modified)."""
    if not enabled or "INVOICE-APPROVAL" not in rules:
        return rules
    _, description = rules["INVOICE-APPROVAL"]
    return {**rules, "INVOICE-APPROVAL": (copy.deepcopy(p2p_defaults.INVOICE_APPROVAL_BANDS),
                                          description + " (default bands: finance controller from 10 lakh, CFO as well from 1 crore)")}


def bootstrap(tenant_id: uuid.UUID, *, company: tuple[str, str, str], plants: list[tuple[str, str, str]],
              cost_objects: list[tuple[str, str, str]], holidays: Optional[list[date]] = None,
              invoice_bands: Optional[bool] = None) -> None:
    """Number ranges, rule sets, currencies, SoD rules, agents, taxonomy and the organisation of a new tenant. ``invoice_bands`` puts the
    default invoice value bands (docs/PIC_Default_Decisions.md) into rule INVOICE-APPROVAL: unset, a tenant bootstrapped by the bundled demo
    seeds and tools (app.pic.seed, app.pic.tools) keeps accounts-payable approval only (the signature case and its tests rely on it) and
    every other new tenant starts with the bands; the onboarding tool (tools/tenant_admin.py) passes True."""
    bands = (not _is_bundled_seed()) if invoice_bands is None else invoice_bands
    with tenant_tx(tenant_id) as s:
        if s.execute(select(NumberRange.id)).first():
            return
        template = s.get(Tenant, tenant_id).industry_template
        for object_type, (prefix, first, padding) in NUMBER_RANGES.items():
            s.add(NumberRange(tenant_id=tenant_id, object_type=object_type, prefix=prefix, next_value=first, padding=padding))
        merged = _with_invoice_bands(templates.merged_rules(RULE_SETS, template), bands)
        for key, (body, description) in _with_mfa_default(merged, s.get(Tenant, tenant_id)).items():
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
        from app.pic.services import ml_registry
        ml_registry.ensure_baselines(s)          # model registry: the built-in baseline versions (rules, smoothing, seeded twin)
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
        for key, (body, description) in _with_mfa_default(templates.merged_rules(RULE_SETS, tenant.industry_template), tenant).items():
            if key not in current:
                s.add(RuleSet(tenant_id=tenant_id, key=key, version=RULES_VERSION, effective_from=RULES_FROM, body=body, description=description))
                added.append(f"rule set {key}")
            elif key == "CLM-PLAYBOOK" and (set(body["templates"]) - set(current[key].body.get("templates", {}))
                                            or ("clauseLibrary" in body and "clauseLibrary" not in current[key].body)):
                need_templates = bool(set(body["templates"]) - set(current[key].body.get("templates", {})))
                need_library = "clauseLibrary" in body and "clauseLibrary" not in current[key].body
                merged = current[key].body
                if need_templates:
                    merged = {**merged, "templates": {**body["templates"], **merged["templates"]},
                              "obligations": {**body["obligations"], **merged.get("obligations", {})}}
                if need_library:   # the clause library (seed/clause_library.py): the tenant's own categoryClauses, jurisdictions and fallbacks win
                    merged = clause_library.merge_into(merged, {k: body[k] for k in ("clauseLibrary", "categoryClauses", "jurisdictions", "fallbacks")})
                version = "2026.3" if need_library else "2026.2"
                if s.execute(select(RuleSet.id).where(RuleSet.key == key, RuleSet.version == version)).first():
                    version += "-LIB"
                s.add(RuleSet(tenant_id=tenant_id, key=key, version=version, effective_from=max(clock.today(), current[key].effective_from),
                              body=merged, description=description + (" (clause library: illustrative sample)" if need_library else " (value and quantity contract templates)")))
                added.append(f"rule set CLM-PLAYBOOK@{version}")
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
        from app.pic.services import ml_registry
        if ml_registry.ensure_baselines(s):
            added.append("ML model registry baselines")
    return added
