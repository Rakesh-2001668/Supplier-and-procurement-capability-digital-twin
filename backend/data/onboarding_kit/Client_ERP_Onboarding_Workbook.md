# Client ERP Production Onboarding Workbook (TD §12)

This technical workbook guides enterprise integration teams, SAP Basis/IT leads, and procurement directors through onboarding a client ERP system (SAP S/4HANA or Oracle Fusion) with the Purchasing Intelligence Cloud (PIC).

---

## 5-Stage Onboarding Methodology

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ Stage 1         │     │ Stage 2          │     │ Stage 3          │     │ Stage 4          │     │ Stage 5         │
│ Data Discovery  │ ──► │ Taxonomy Mapping │ ──► │ Org & Accounting │ ──► │ Field Mapping &  │ ──► │ Dry-Run &       │
│ & Extraction    │     │ Workshop         │     │ Crosswalk        │     │ Test Diff        │     │ Production Cut  │
└─────────────────┘     └──────────────────┘     └──────────────────┘     └──────────────────┘     └─────────────────┘
```

---

### Stage 1: Data Discovery & Initial Extract

1. **Extraction Scope**:
   Extract baseline master and transactional data from the client's SAP S/4HANA or ECC system using standard extract definitions:
   - Vendor Masters: `LFA1`, `LFB1`, `LFBK`, `ADRC`, `T052`
   - Material Masters: `MARA`, `MAKT`, `MARC`, `MBEW`
   - Purchasing Documents: `EKKO`, `EKPO`, `EKKN`, `EKET`, `EKBE`
   - Open AP & Accounting: `BSIK`, `RBKP`, `RSEG`, `ACDOCA`
2. **File Generation & Manifest**:
   Generate CSVs and compile `MANIFEST.json` containing row counts and SHA-256 checksums matching `docs/PIC_ERP_Extract_Spec.md`.
3. **Data Quality & CBIC Tax Schedule Pre-Check**:
   Run `erp_extract_validator.py` to identify malformed GSTINs, unmapped HSN/SAC codes, missing units of measure, and non-cleared balances.

---

### Stage 2: Taxonomy & Material Group Mapping Workshop

1. **Material Groups Crosswalk (`PIC_MAP_MATKL.csv`)**:
   - Map each client SAP Material Group (`MATKL`) to the client's target PIC Category.
   - Assign primary Buyer Groups and Criticality tiers (Low, Medium, High, Critical).
2. **Category Hierarchy (`PIC_MAP_TAXONOMY.csv`)**:
   - Establish Level 1 (Direct, Indirect, Services, Capex), Level 2 (Sub-categories), and Level 3 (Commodities).
   - Link each node to official UNSPSC codes for cross-company spend benchmarking.
   - Configure Sourcing Strategies (e.g. Index-Linked Contracts, Should-Cost, Framework Catalogs) and Approval Tiers.

---

### Stage 3: Organization & Accounting Crosswalk

1. **Company Code & Plant Alignment (`PIC_MAP_ORG.csv`)**:
   - Map SAP Company Code (`T001`) to PIC `CompanyCode`.
   - Map SAP Plants (`T001W`) and Storage Locations (`T001L`) with state GSTIN registrations.
2. **Cost Objects & Accounting Assignments**:
   - Reconcile Cost Centers (`CSKS`) and WBS Elements (`PRPS`) for automated budget commitments and requisition validations.
   - Configure Purchasing Organizations (`T024E`) and Purchasing Groups (`T024`).
3. **Payment Terms & GST / TDS Codes (`PIC_MAP_TERMS_AND_TAX.csv`)**:
   - Align payment terms (e.g. `Z030` &rarr; `NET30`, MSME 45-day limits).
   - Configure Input GST tax codes (`I0`..`I4`) and withholding tax sections (`194C`, `194J`, `194Q`).

---

### Stage 4: Outbound Field Mapping & Dry-Run Test Diffs

1. **Target System Rules Loading**:
   - Load pre-configured JSON rule sets into `pic.integration_field_mapping` in the database:
     - `rules/SAP_S4_PURCHASE_ORDER.json`
     - `rules/SAP_S4_SUPPLIER_INVOICE.json`
     - `rules/SAP_S4_GOODS_RECEIPT.json`
     - `rules/SAP_S4_PAYMENT.json`
2. **Live Visual Preview in Admin UI**:
   - Navigate to **Admin &rarr; ERP field mappings** (`/pic/admin?tab=mappings`).
   - Paste real client document samples into the test panel.
   - Review rule transformations and verify line-by-line diffs before activating.
3. **Publishing**:
   - Click **Publish** to make version 1 active.
   - PIC's Outbox pattern guarantees that canonical payloads remain unaltered while the outbound payload conforms strictly to client SAP BAPI/OData requirements.

---

### Stage 5: Dry-Run Rehearsal & Cutover Sign-Off

1. **End-to-End Simulation**:
   - Transmit mock Purchase Order, Goods Receipt, and Supplier Invoice through the staging connector.
   - Validate that external document numbers (`EBELN`, `BELNR`, `MBLNR`) round-trip successfully.
2. **Reconciliation Tie-Out**:
   - Verify that GL balances, Open AP, and Open PO commitments match within ±0.0% variance.
3. **Go-Live Switch**:
   - Enable scheduled jobs, activate the delta extraction poller (`erp_sync.py`), and promote the tenant to production status.
