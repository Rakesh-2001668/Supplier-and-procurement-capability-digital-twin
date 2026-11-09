"""Default bodies of the finance rule sets MSME and TDS (seeded for every tenant, editable through POST /v1/admin/rules; the code
falls back to them for a tenant without the rule set). Starting points for the tax and treasury team to confirm, not legal advice."""

MSME_DEFAULT = {"maxDays": 45, "noAgreementDays": 15, "classes": ["MICRO", "SMALL"], "bankRatePct": None, "interestMultiple": 3,
                "note": "MSMED Act 2006 s.15-16: payment within the agreed period, never more than 45 days from the day of acceptance; "
                        "interest at three times the RBI bank rate, compounded monthly (set bankRatePct to compute it)"}
TDS_DEFAULT = {
    "noPanRatePct": 20,
    # TCS the supplier collects on top of its invoice (s.206C(1H) style): off by default; the tax team decides rate, threshold and whether it is
    # paid to the supplier with the invoice (addToPayable) or only carried to the ERP posting.
    "tcs": {"enabled": False, "section": "206C(1H)", "ratePct": 1, "annualThresholdMinor": 500_000_000, "addToPayable": False},
    "deductor": {"tan": None, "pan": None, "name": None, "address": None},
    "sections": {
        "194C-IND": {"label": "Contractor, individual / HUF", "ratePct": 1, "singleThresholdMinor": 3_000_000, "annualThresholdMinor": 10_000_000},
        "194C-OTH": {"label": "Contractor, other payees", "ratePct": 2, "singleThresholdMinor": 3_000_000, "annualThresholdMinor": 10_000_000},
        "194J-TECH": {"label": "Technical services / call centre", "ratePct": 2, "annualThresholdMinor": 5_000_000},
        "194J-PRO": {"label": "Professional services / royalty", "ratePct": 10, "annualThresholdMinor": 5_000_000},
        "194H": {"label": "Commission / brokerage", "ratePct": 2, "annualThresholdMinor": 2_000_000},
        "194I-LB": {"label": "Rent, land and building", "ratePct": 10, "annualThresholdMinor": 60_000_000},
        "194I-PM": {"label": "Rent, plant and machinery", "ratePct": 2, "annualThresholdMinor": 60_000_000},
        "194Q": {"label": "Purchase of goods above the annual limit", "ratePct": 0.1, "annualThresholdMinor": 500_000_000, "excessOnly": True},
    },
    "note": "Illustrative defaults for the Income-tax Act TDS sections; the tax team confirms rates, thresholds and the section codes "
            "of the Act in force (publish a TDS rule version through POST /v1/admin/rules)",
}

# Section 195 withholding on payments to non-residents (rule set TDS-195, effective-dated, scope company code). EVERY value below is a MOCK
# starting point that the client's chartered accountant must confirm: the section label, the Act it belongs to (the Income-tax Act, 2025
# replaced the 1961 Act from 1 April 2026 and renumbers its sections), the Act rates, surcharge slabs and basis, the cess, the treaty (DTAA)
# rates and articles, the no-PAN rule (s.206AA) and its non-resident relief (Rule 37BC), the Form 15CA/15CB threshold and the FX rate date.
TDS_195_DEFAULT = {
    "mock": True,
    "act": "Income-tax Act, 1961",
    "sectionLabel": "195",
    "returnForm": "27Q",
    # Payment natures: the Act rate per payee type (COMPANY = foreign company, NON_COMPANY = any other non-resident) before surcharge and cess.
    "natures": {
        "ROYALTY": {"label": "Royalty", "actRatePct": {"COMPANY": 20, "NON_COMPANY": 20}, "actRef": "s.115A"},
        "FTS": {"label": "Fees for technical services", "actRatePct": {"COMPANY": 20, "NON_COMPANY": 20}, "actRef": "s.115A"},
        "INTEREST": {"label": "Interest", "actRatePct": {"COMPANY": 20, "NON_COMPANY": 20}, "actRef": "s.115A"},
        "OTHER": {"label": "Other income (business profits, other sums chargeable)", "actRatePct": {"COMPANY": 35, "NON_COMPANY": 30},
                  "actRef": "rates in force (Finance Act)"},
    },
    # Surcharge slabs on the Act rate by payee type; the slab is chosen by ``surchargeBasis`` (PAYMENT_AMOUNT: the INR amount of this payment, after
    # gross-up). Treaty rates are inclusive (no surcharge or cess) while ``treatyRateInclusive`` is true.
    "surchargeBasis": "PAYMENT_AMOUNT",
    "surcharge": {"COMPANY": [{"aboveMinor": 1_00_00_000_00, "pct": 2}, {"aboveMinor": 10_00_00_000_00, "pct": 5}],
                  "NON_COMPANY": [{"aboveMinor": 50_00_000_00, "pct": 10}, {"aboveMinor": 1_00_00_000_00, "pct": 15},
                                  {"aboveMinor": 2_00_00_000_00, "pct": 25}, {"aboveMinor": 5_00_00_000_00, "pct": 37}]},
    "cessPct": 4,
    "treatyRateInclusive": True,
    # The treaty rate is used only when these documents are valid on the payment date (TRC: Tax Residency Certificate, FORM_10F).
    "treatyRequires": ["TRC", "FORM_10F"],
    # MOCK DTAA table: rate per nature and the article; a nature missing for a country means the treaty has no article for it (the Act rate applies).
    # An entry may require more documents (e.g. NO_PE: the no-permanent-establishment declaration).
    "dtaa": {
        "US": {"label": "India-USA DTAA (MOCK values)", "ROYALTY": {"ratePct": 15, "article": "12"}, "FTS": {"ratePct": 15, "article": "12"},
               "INTEREST": {"ratePct": 15, "article": "11"}, "OTHER": {"ratePct": 0, "article": "7", "requires": ["NO_PE"]}},
        "DE": {"label": "India-Germany DTAA (MOCK values)", "ROYALTY": {"ratePct": 10, "article": "12"}, "FTS": {"ratePct": 10, "article": "12"},
               "INTEREST": {"ratePct": 10, "article": "11"}, "OTHER": {"ratePct": 0, "article": "7", "requires": ["NO_PE"]}},
        "JP": {"label": "India-Japan DTAA (MOCK values)", "ROYALTY": {"ratePct": 10, "article": "12"}, "FTS": {"ratePct": 10, "article": "12"},
               "INTEREST": {"ratePct": 10, "article": "11"}, "OTHER": {"ratePct": 0, "article": "7", "requires": ["NO_PE"]}},
        "SG": {"label": "India-Singapore DTAA (MOCK values)", "ROYALTY": {"ratePct": 10, "article": "12"}, "FTS": {"ratePct": 10, "article": "12"},
               "INTEREST": {"ratePct": 15, "article": "11"}, "OTHER": {"ratePct": 0, "article": "7", "requires": ["NO_PE"]}},
        "GB": {"label": "India-UK DTAA (MOCK values)", "ROYALTY": {"ratePct": 15, "article": "13"}, "FTS": {"ratePct": 15, "article": "13"},
               "INTEREST": {"ratePct": 15, "article": "12"}, "OTHER": {"ratePct": 0, "article": "7", "requires": ["NO_PE"]}},
        "AE": {"label": "India-UAE DTAA (MOCK values; no fees-for-technical-services article)", "ROYALTY": {"ratePct": 10, "article": "12"},
               "INTEREST": {"ratePct": 12.5, "article": "11"}, "OTHER": {"ratePct": 0, "article": "7", "requires": ["NO_PE"]}},
    },
    # No PAN (s.206AA): the higher of ``ratePct`` and the Act rate (with surcharge and cess). Relief for a non-resident who gives the documents of
    # Rule 37BC for the listed natures: then s.206AA does not apply and the normal treaty / Act choice is made.
    "noPan": {"sectionLabel": "206AA", "ratePct": 20, "treatyStillApplies": False,
              "relief": {"natures": ["ROYALTY", "FTS", "INTEREST"], "requires": ["TRC", "TAX_ID", "ADDRESS"]}},
    # Form 15CA (always for a taxable remittance) and Form 15CB (CA certificate) above the threshold: FISCAL_YEAR_AGGREGATE counts the INR value of
    # this and the earlier remittances to the supplier in the fiscal year; PAYMENT counts this remittance alone.
    "form15": {"caRequired": True, "cbAboveMinor": 5_00_000_00, "cbBasis": "FISCAL_YEAR_AGGREGATE", "notRequiredForNatures": []},
    # Rate date for converting the foreign-currency base to INR: PAYMENT_DATE (the day tax is deducted) or INVOICE_DATE.
    "fxRateDate": "PAYMENT_DATE",
    "roundInrToMinor": 100,
    "note": "MOCK values for illustration: the client's chartered accountant confirms every rate, slab, threshold and section label "
            "(the Income-tax Act, 2025 renumbers the 1961 sections from 1 April 2026) before go-live",
}

# Partial payments of an invoice across payment runs (rule set PARTIAL-PAYMENT, effective-dated, scope company code).
PARTIAL_PAYMENT_DEFAULT = {
    "enabled": True,
    "minAmountMinor": 1_000_00,        # smallest partial payment (invoice currency minor units)
    "maxInstallments": 12,             # payments per invoice, returned ones included
    "reasonMinLength": 10,
    "note": "A partial payment needs a reason; TDS is deducted in full with the first payment of the invoice; an accepted early-payment "
            "discount or an SCF election is earned only by paying the whole invoice",
}
