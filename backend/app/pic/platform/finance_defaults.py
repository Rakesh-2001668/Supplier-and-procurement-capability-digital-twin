"""Default bodies of the finance rule sets MSME and TDS (seeded for every tenant, editable through POST /v1/admin/rules; the code
falls back to them for a tenant without the rule set). Starting points for the tax and treasury team to confirm, not legal advice."""

MSME_DEFAULT = {"maxDays": 45, "classes": ["MICRO", "SMALL"], "bankRatePct": None, "interestMultiple": 3,
                "note": "MSMED Act 2006 s.15-16: payment within the agreed period, never more than 45 days from the day of acceptance; "
                        "interest at three times the RBI bank rate, compounded monthly (set bankRatePct to compute it)"}
TDS_DEFAULT = {
    "noPanRatePct": 20,
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
