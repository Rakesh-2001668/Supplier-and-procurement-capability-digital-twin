"""Rule bodies of the wave 1 procure-to-pay completion rules (seeded for every tenant by seed/reference.py RULE_SETS and used as the
built-in fallback by services/p2p_rules.py when a tenant bootstrapped by an earlier release has not received them yet).

Money is in paise (``L`` = one lakh rupees). Every key is a tenant-editable, effective-dated rule set (P14)."""
L = 100_000 * 100

# BP M06 "Only Qualified/Preferred suppliers receive POs for the category unless a one-time-vendor policy applies" + BP §24.
ONE_TIME_VENDOR = {
    "enabled": True,
    "maxValueMinor": 5 * L,                  # per order; above it the exception is refused
    "minReasonLength": 10,
    "approverRoles": ["PROCUREMENT_HEAD"],   # added to the PO approval chain; the order is never released touchless
    "blockedStatuses": ["BLOCKED", "MERGED"],  # never allowed (SLM-BLOCK)
}

# BP §24 "PO deviation: price > contract + 2% or > last price + 5% → buyer lead".
PO_PRICE_CHECK = {
    "enabled": True,
    "contractBandPct": "2",                  # non-contract order priced above the contract price of the material by more than this
    "lastPriceBandPct": "5",                 # order priced above the last price paid by more than this
    "lastPriceBasis": "SUPPLIER_THEN_MATERIAL",   # SUPPLIER_THEN_MATERIAL | SUPPLIER | MATERIAL
    "lookbackMonths": 12,
}

# BP M08-C3 split detection by supplier + material (the cost-object variant is rule PO-RISK splitWindowDays/splitBandMinor).
PO_SPLIT_DETECTION = {"enabled": True, "windowDays": 7, "minOrders": 3, "perOrderBelowMinor": 2 * L}

# BP M10 credit/debit notes.
DEBIT_NOTE = {
    "maxPctOfInvoice": "25",                 # a debit note above this share of the invoice net is refused (raise a dispute / new PO)
    "unitTolerancePct": "0",                 # price correction accepted without approval up to PO price + this %
    "approvalBands": [{"upTo": 1 * L, "chain": ["BUYER"]}, {"upTo": None, "chain": ["BUYER", "PROCUREMENT_HEAD"]}],
    "chargeKinds": ["FREIGHT", "PACKING", "INSURANCE", "INSPECTION", "HANDLING", "OTHER"],
    "requiredRoles": ["AP_CLERK"],           # who may raise a debit note on the supplier's behalf (a supplier user raises their own)
}

# BP M10 early-payment discount and supply-chain-finance hooks.
EARLY_PAYMENT = {
    "enabled": True,
    "offerValidDays": 7,
    "minDaysEarly": 3,                       # the offered payment date must be at least this many days before the due date
    "maxDiscountPct": "5",
    "annualisedBasisDays": 365,
    "scf": {"enabled": True, "minInvoiceMinor": 1 * L, "financier": "PROGRAMME", "feeBasis": "FINANCIER"},
}

# BP M04 request templates for services, IT, marketing and facilities.
REQUEST_TEMPLATES = {
    "templates": {
        "SVC-PROFESSIONAL": {
            "name": "Professional services (consulting, audit, legal)", "group": "SERVICES",
            "line": {"item_type": "SERVICE", "purchase_type": "SERVICE", "material_group": "PROF-SERVICES", "category": "PROFESSIONAL-SERVICES",
                     "uom": "AU"},
            "defaultAccountType": "COST_CENTER", "requiredFields": ["description", "account_assignment_code", "need_date"],
            "quotePolicy": {"minQuotesFromMinor": 25_000 * 100, "minQuotes": 2, "sourcingEventAboveMinor": 10 * L},
            "approverHints": ["Statement of work and milestones are attached to the request", "Cost-object owner and department head approve"],
            "guidance": "Describe the scope, deliverables, duration and the milestone plan; the SOW is agreed before ordering.",
        },
        "IT-HARDWARE-SOFTWARE": {
            "name": "IT hardware, software and subscriptions", "group": "IT",
            "line": {"item_type": "FREE_TEXT", "purchase_type": "NON_STOCK", "material_group": "IT-EQUIP", "category": "IT-EQUIPMENT", "uom": "EA"},
            "defaultAccountType": "COST_CENTER", "requiredFields": ["description", "account_assignment_code", "need_date"],
            "quotePolicy": {"minQuotesFromMinor": 25_000 * 100, "minQuotes": 2, "sourcingEventAboveMinor": 10 * L},
            "approverHints": ["IT security review for software and cloud subscriptions", "Capital items above the threshold follow the asset route"],
            "guidance": "Name the product or service, licence count and term; hardware above the capitalisation limit is requested as an asset.",
        },
        "MKT-CAMPAIGN-EVENT": {
            "name": "Marketing campaigns, agencies and events", "group": "MARKETING",
            "line": {"item_type": "SERVICE", "purchase_type": "SERVICE", "material_group": "MARKETING", "category": "MARKETING-SERVICES", "uom": "AU"},
            "defaultAccountType": "COST_CENTER", "requiredFields": ["description", "account_assignment_code", "need_date"],
            "quotePolicy": {"minQuotesFromMinor": 25_000 * 100, "minQuotes": 3, "sourcingEventAboveMinor": 5 * L},
            "approverHints": ["Marketing head approves campaign scope", "Agency selection above the sourcing limit goes through an RFQ"],
            "guidance": "Give the campaign or event, dates, deliverables and the approved marketing budget line.",
        },
        "FAC-MAINTENANCE": {
            "name": "Facilities, maintenance and housekeeping", "group": "FACILITIES",
            "line": {"item_type": "SERVICE", "purchase_type": "SERVICE", "material_group": "FACILITIES", "category": "FACILITIES-SERVICES", "uom": "AU"},
            "defaultAccountType": "COST_CENTER", "requiredFields": ["description", "account_assignment_code", "need_date"],
            "quotePolicy": {"minQuotesFromMinor": 25_000 * 100, "minQuotes": 1, "sourcingEventAboveMinor": 10 * L},
            "approverHints": ["Facilities manager confirms the site and the service window"],
            "guidance": "State the site, the service (AMC, repair, housekeeping) and the period; recurring services use a rate contract.",
        },
    },
}

# BP M04 account assignment "cost centre, WBS, internal order, asset, sales order" and the budget handling for it.
SALES_ORDER_ACCOUNT = {
    "enabled": True,
    "requireDemandElement": True,            # the customer order (and line) must exist as a SALES_ORDER demand element
    "requireMaterialMatch": True,            # a material line must be demanded by that sales order (same material)
    "overAssignmentTolerancePct": "0",       # quantity assigned to the order may exceed its demand by at most this %
    "budget": "COMMITMENT_IF_BUDGETED",      # a budget for SALES_ORDER:<order> is checked like any cost object; none = settles to the order
}

# BP §22 capital assets: capitalisation data carried on the goods receipt posted to the ERP.
ASSET_CAPITALISATION = {
    "capitalise": True,
    "assetClassByValuationClass": {},        # valuation class -> asset class (tenant supplied: asset classes are ERP configuration)
    "assetClassByMaterialGroup": {},
    "defaultAssetClass": None,
    "costCentreByPlant": {},
}

# TD §6 / P14 configurable mandatory fields per document type. A rule scoped to company code, plant, category or purchase type
# replaces this one entirely for that scope (copy the fields you keep).
MANDATORY_FIELDS = {
    "documents": {
        "REQUISITION": {"header": ["purpose_code"], "lines": ["description", "material_group", "qty", "uom", "need_date"]},
        "PO_RELEASE": {"header": ["payment_terms", "purpose_code"], "lines": ["gst_rate", "need_date", "plant"]},
        "GR_POST": {"header": [], "lines": ["qty"]},
        "INVOICE_CAPTURE": {"header": ["supplier_invoice_no", "invoice_date"], "lines": ["qty", "unit_price"]},
        "SUPPLIER_REGISTER": {"header": ["legal_name", "gstin", "pan", "state_code", "contact_email"], "lines": []},
    },
}

# Default invoice value bands approved by the client (docs/PIC_Default_Decisions.md): below 10 lakh accounts payable alone; 10 lakh to below
# 1 crore AP then the finance controller; 1 crore and above AP, the finance controller, then the CFO. Gross in company-code currency, paise.
# Seeded for NEW tenants (seed/reference.bootstrap, invoice_bands) and activated for the demo tenants by dataset pack approval_bands (D22).
# Tenants bootstrapped before keep "bands": [] below (AP approval only) until their administrator publishes this as a new rule version.
INVOICE_APPROVAL_BANDS = {
    "bands": [{"fromMinor": 10 * L, "approvers": ["FINANCE_CONTROLLER"]},
              {"fromMinor": 100 * L, "approvers": ["FINANCE_CONTROLLER", "CFO"]}],
    "slaBusinessDays": 2,
}

BODIES = {
    "ONE-TIME-VENDOR": (ONE_TIME_VENDOR, "One-time-vendor exception: PO to a supplier that is not Qualified/Preferred (value cap, reason, approver)"),
    "PO-PRICE-CHECK": (PO_PRICE_CHECK, "PO price check: contract +2% band and last paid price +5% (BP §24, APR-8)"),
    "PO-SPLIT": (PO_SPLIT_DETECTION, "Split detection by supplier and material: many small POs within N days (BP M08)"),
    "DEBIT-NOTE": (DEBIT_NOTE, "Supplier debit notes: cap, tolerance and approval chain (BP M10)"),
    "EARLY-PAYMENT": (EARLY_PAYMENT, "Early-payment discount offers and supply-chain-finance hooks (BP M10)"),
    "REQUEST-TEMPLATES": (REQUEST_TEMPLATES, "Request templates for services, IT, marketing and facilities (BP M04)"),
    "SALES-ORDER-ACCOUNT": (SALES_ORDER_ACCOUNT, "Sales-order account assignment on requisition and PO lines (BP M04)"),
    "ASSET-CAPITALISATION": (ASSET_CAPITALISATION, "Capitalisation data on the goods receipt of asset lines (BP §22)"),
    "MANDATORY-FIELDS": (MANDATORY_FIELDS, "Mandatory fields per document type (TD §6, P14)"),
    # Flow fixes (C3): approval chain of an invoice by value band after the accounts-payable approval. No band = AP approval only (the default
    # matrix of BP §24 has no invoice row); add bands per company code, e.g. [{"fromMinor": 1000000000, "approvers": ["FINANCE_CONTROLLER"]}].
    "INVOICE-APPROVAL": ({"bands": [], "slaBusinessDays": 2},
                         "Invoice approval chain by value band (gross in company currency) after accounts payable: approver roles per band, "
                         "worked in the task inbox with delegation, SLA escalation, value limits and SOD-08/09"),
}
