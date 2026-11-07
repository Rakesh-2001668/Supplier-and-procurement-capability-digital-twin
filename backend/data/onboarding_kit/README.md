# Turnkey Client ERP Onboarding Accelerator Pack

This directory provides standardized templates, pre-configured ERP production field mappings, and the technical workbook for onboarding enterprise clients (such as automotive OEMs, industrial manufacturers, and service enterprises) connecting their SAP S/4HANA or Oracle Fusion ERP systems to the Purchasing Intelligence Cloud (PIC).

## Directory Structure

```
backend/data/onboarding_kit/
├── README.md                                  # This documentation
├── Client_ERP_Onboarding_Workbook.md          # 5-Stage Client Technical & Workshop Guide
├── templates/
│   ├── PIC_MAP_MATKL.csv                      # SAP Material Group (MATKL) → PIC Category mapping
│   ├── PIC_MAP_TAXONOMY.csv                   # Multi-tier Category Hierarchy & UNSPSC Crosswalk
│   ├── PIC_MAP_ORG.csv                        # Company Code, Plant, SLoc, Cost Object Crosswalk
│   └── PIC_MAP_TERMS_AND_TAX.csv              # Payment Terms (T052) & Tax Codes (T007A) Crosswalk
└── rules/
    ├── SAP_S4_PURCHASE_ORDER.json             # Outbound PO field transformation rules for SAP S/4HANA
    ├── SAP_S4_SUPPLIER_INVOICE.json          # Outbound Invoice transformation rules for SAP S/4HANA
    ├── SAP_S4_GOODS_RECEIPT.json             # Outbound GR transformation rules for SAP S/4HANA
    ├── SAP_S4_PAYMENT.json                   # Outbound Payment clearing rules for SAP S/4HANA
    └── ORACLE_FUSION_PURCHASE_ORDER.json     # Outbound PO transformation rules for Oracle Fusion
```

## How to Apply to Neon Database

To populate and activate these baseline production field mappings for any tenant in the Neon PostgreSQL database:

```bash
# Apply and activate all baseline mappings for tenant KAC
python -m app.pic.tools.onboarding_pack --tenant KAC --apply-mappings

# Apply for all tenants in the system
python -m app.pic.tools.onboarding_pack --all-tenants --apply-mappings

# Dry-run validation only (verifies rules syntax and diff against sample payloads)
python -m app.pic.tools.onboarding_pack --tenant KAC --dry-run
```
