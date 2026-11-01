"""Industry templates (blueprint §23): configuration packs applied at tenant creation and editable afterwards.

Each pack lists its purchase types, demand sources, sourcing-event and contract templates, receipt and
match settings, special controls, KPIs and the rule-set overrides it applies on top of the default
Indian-rupee pack in reference.RULE_SETS. The manufacturing pack is the default (Axion demo tenant).
"""
L = 100_000 * 100

TEMPLATES = {
    "MANUFACTURING": {
        "name": "Manufacturing & Industrial",
        "purchaseTypes": ["STOCK", "NON_STOCK", "SERVICE", "EXPENSE", "ASSET", "CONSIGNMENT", "SUBCONTRACTING"],
        "demandSources": ["MRP from forecast and customer orders", "Kanban / reorder point for C-parts"],
        "eventTemplates": ["RFQ with should-cost (casting, forging, machining)", "PPAP-gated award", "Dual sourcing"],
        "contractTemplates": ["SCHEDULING_AGREEMENT", "QUANTITY_CONTRACT", "VALUE_CONTRACT"],
        "receipt": "GR with quality inspection, batch traceability, ASN mandatory",
        "match": "3-way; ERS for scheduling agreements",
        "controls": ["PPAP / IATF 16949 qualification", "Quota arrangements", "Safety stock"],
        "kpis": ["OTIF", "PPM", "Inventory turns", "PPV"],
        "demoCase": "Dual source: Trichy Forge 60% @ 398, Kovai Diecast 40% @ 405 (capacity-constrained scenario)",
        # Industry controls (wave 1): ERS on scheduling agreements (settled per period from accepted call-off deliveries) and Kanban cards for C-parts.
        # The weekly / monthly MRP buckets and reorder-point planning are chosen per material through its MRP type (PW, PM, VB).
        "ruleOverrides": {
            "SELF-BILLING": {"enabled": True, "contractTypes": ["SCHEDULING_AGREEMENT"], "suppliers": [], "basis": "ACCEPTED_GOODS_RECEIPT"},
            "KANBAN": {"enabled": True, "purposeCode": "KANBAN_REPLENISHMENT", "autoRequisition": True},
        },
    },
    "CONSTRUCTION": {
        "name": "Construction & Projects",
        "purchaseTypes": ["NON_STOCK", "SERVICE", "ASSET", "EXPENSE"],
        "demandSources": ["Project / WBS plan", "Bill of quantities", "Site requests"],
        "eventTemplates": ["Tender package by trade", "Technical + commercial envelope", "Retention terms"],
        "contractTemplates": ["VALUE_CONTRACT"],
        "receipt": "Site GR; measurement-based service entry (progress %); equipment-hire timesheets",
        "match": "3-way vs SES with retention and advance recovery",
        "controls": ["WBS budget hard stop", "Variation orders are contract amendments", "Retention %", "Performance bank guarantee"],
        "kpis": ["Cost to complete", "Commitments vs budget", "Variation %"],
        "demoCase": "WBS C-2207 'Tower B structure', subcontract SC-118 rebar & formwork, SES at 35% progress, 5% retention",
        "ruleOverrides": {"BUDGET": {"hardFor": ["ASSET", "WBS", "COST_CENTER"], "softFor": ["ORDER"]},
                          "PROJECT-CONTROLS": {"retentionPct": "5", "advanceRecovery": True, "variationAsAmendment": True},
                          # Advance: at most maxPct of the order value, against an advance bank guarantee, approved by finance, recovered pro rata
                          # from every running bill. Performance guarantee: at least minPct of the order value; retention release and final payment
                          # wait for a valid one; expiry alerts go to the contract manager.
                          "ADVANCE-PAYMENT": {"enabled": True, "maxPct": "15", "needsGuarantee": True, "approverRole": "FINANCE_CONTROLLER",
                                              "recovery": "PRO_RATA"},
                          "PERFORMANCE-GUARANTEE": {"enabled": True, "minPct": "5", "requiredFor": ["RETENTION_RELEASE", "FINAL_PAYMENT"],
                                                    "alertDays": [60, 30, 7], "releaseAfter": "RETENTION_RELEASED"}},
    },
    "IT_SERVICES": {
        "name": "IT & Professional Services",
        "purchaseTypes": ["SERVICE", "EXPENSE", "ASSET"],
        "demandSources": ["Project resourcing", "Licence renewals", "User requests"],
        "eventTemplates": ["RFP with technical scoring", "Rate-card benchmarking"],
        "contractTemplates": ["VALUE_CONTRACT"],
        "receipt": "Timesheet- or milestone-based SES; licence entitlement receipt",
        "match": "3-way vs SES; 2-way for subscriptions",
        "controls": ["InfoSec and data-privacy assessment", "IP clauses", "Auto-renewal alerts"],
        "kpis": ["Rate compliance", "Licence utilisation", "Renewal savings"],
        "demoCase": "SOW-4410 cloud migration T&M, rate card RC-22, timesheet SES 320 h",
        # Licence utilisation: an entitlement whose peak use over lookbackDays is below minUtilisationPct is flagged UNUSED, flagLeadDays
        # before the renewal alert (renewalNoticeDays before the term ends).
        "ruleOverrides": {"CONTRACT-APPROVAL": {"renewalNoticeDays": 90},
                          "LICENCE-UTILISATION": {"enabled": True, "minUtilisationPct": "80", "lookbackDays": 90, "flagLeadDays": 30}},
    },
    "LOGISTICS": {
        "name": "Logistics & Transportation",
        "purchaseTypes": ["SERVICE", "EXPENSE"],
        "demandSources": ["Lane volume forecast", "Shipment orders", "Spot needs"],
        "eventTemplates": ["Lane tender", "Mini-bid", "Spot auction"],
        "contractTemplates": ["VALUE_CONTRACT"],
        "receipt": "Proof of delivery as service confirmation",
        "match": "Freight audit: rate × weight/volume vs invoice, accessorials",
        "controls": ["Carrier compliance (insurance, permits)", "Detention / demurrage rules"],
        "kpis": ["Cost per tonne-km", "On-time pickup / delivery", "Audit recoveries"],
        "demoCase": "Lane CHE→PNQ 32 ft MXL, rate 54/km + fuel index, POD-based confirmation",
        # Carrier compliance: a carrier is qualified for LOGISTICS only with valid goods-in-transit insurance and a national permit.
        "ruleOverrides": {"FREIGHT-AUDIT": {"rateTolerancePct": "0", "fuelIndex": "DIESEL_IN", "accessorialsNeedPod": True},
                          "SUPPLIER-QUAL": {"mandatoryCertificates": {"LOGISTICS": ["GIT_INSURANCE", "NATIONAL_PERMIT"]}}},
    },
    "HEALTHCARE": {
        "name": "Healthcare & Life Sciences",
        "purchaseTypes": ["STOCK", "CONSIGNMENT", "SERVICE", "ASSET"],
        "demandSources": ["Par levels", "Consumption", "Clinical requests", "Formulary"],
        "eventTemplates": ["Value-analysis committee", "GPO contracts", "Tenders"],
        "contractTemplates": ["QUANTITY_CONTRACT", "VALUE_CONTRACT"],
        "receipt": "GR with lot / expiry / serial, cold chain; implant usage triggers replenishment",
        "match": "3-way; consignment settlement on usage",
        "controls": ["Regulatory approvals (CDSCO / USFDA where applicable)", "Recall traceability", "Clinical sign-off in award"],
        "kpis": ["Contract compliance", "Expiry write-offs", "Stock-outs"],
        "demoCase": "Consignment implant KN-77, lot/expiry tracking, usage-triggered PO",
        # Cold chain: an excursion longer than maxExcursionMinutes (per material range) quarantines the stock and opens a quality task.
        # Clinical sign-off: the clinical lead approves every award (or only clinicalCategories) after the value-based chain.
        "ruleOverrides": {"AWARD-APPROVAL": {"clinicalSignOff": True, "clinicalRole": "CLINICAL_LEAD"},
                          "COLD-CHAIN": {"enabled": True, "maxExcursionMinutes": 30, "taskRole": "QUALITY_INSPECTOR"},
                          "PAR-LEVEL": {"enabled": True}},
    },
    "GENERAL": {
        "name": "General Enterprise (Indirect)",
        "purchaseTypes": ["EXPENSE", "SERVICE", "ASSET"],
        "demandSources": ["Employee requests", "Budgets"],
        "eventTemplates": ["Quick quote", "3-quote policy", "Preferred suppliers"],
        "contractTemplates": ["VALUE_CONTRACT"],
        "receipt": "Desktop receipt; receipt-less below threshold",
        "match": "2-way under threshold, 3-way above",
        "controls": ["Guided-buying policy", "P-card limits", "Budget"],
        "kpis": ["Catalogue adoption %", "PR cycle time", "Maverick %"],
        "demoCase": "Laptop catalogue order via punch-out, 78,500, single approval",
        # Desktop receipt (gr) above the threshold, receipt-less (2-way) below it: "2-way under threshold, 3-way above".
        "ruleOverrides": {"PURCHASE-TYPE-MATRIX": {"EXPENSE": {"gr": True, "ir": True, "ses": False, "receiptlessBelowMinor": 1 * L}},
                          # Purchasing cards: policy ceilings, blocked merchant categories (ISO 18245: 7995 betting, 6010/6011 cash, 4829 money
                          # transfer, 5813 bars, 5921 liquor stores), PO required above poRequiredAboveMinor, statement-to-PO match tolerance.
                          "PCARD": {"enabled": True, "maxPerTransactionMinor": 1 * L, "maxMonthlyMinor": 5 * L,
                                    "blockedMccs": ["7995", "6010", "6011", "4829", "5813", "5921"], "poRequiredAboveMinor": 25_000 * 100,
                                    "matchToleranceMinor": 100, "matchWindowDays": 45, "reviewRole": "COST_OBJECT_OWNER"}},
    },
}


def merged_rules(base: dict, template: str) -> dict:
    """Default rule bodies with the template's overrides applied (shallow merge per rule key; new keys added)."""
    out = {key: (dict(body), description) for key, (body, description) in base.items()}
    for key, override in TEMPLATES[template]["ruleOverrides"].items():
        if key in out:
            body, description = out[key]
            out[key] = ({**body, **override}, description)
        else:
            out[key] = (override, f"{TEMPLATES[template]['name']} template rule")
    return out
