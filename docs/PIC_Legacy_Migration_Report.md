# Legacy Data Migration Report

Migration of the legacy `supplier_twin` database (Docker Desktop container `supplier_twin_db`, PostgreSQL 15) into the Procurement Intelligence Cloud, following Delivery Plan §15 ("current demo data").

| Item | Value |
|---|---|
| Source | docker `supplier_twin_db` database `supplier_twin` (Alembic `d504090e6c08`) |
| Snapshot | `backend/data/legacy/supplier_twin.json`, extracted 2026-10-27T13:52:04+00:00, SHA-256 `f1877089910c1cf3…` |
| Rows extracted | 156 in 15 tables |
| Amount conversion | legacy amount × 1 → INR paise (the legacy schema has no currency column) |

## What was loaded where

1. **Verbatim copy.** All 15 legacy tables were copied unchanged into the `public` schema, with their legacy ids. A new legacy migration (`e3c1f2a4b5d6`) first adds 9 columns that the Docker database has but the legacy Alembic chain was missing (inventory category, unit, thresholds, location and status; stock-transaction notes, performed-by and balance).
2. **Migration into PIC.** Each legacy buyer became a PIC tenant. Masters, open documents and paid history were loaded with their legacy ids and audited as `MIGRATED`. Lineage links connect requisition → sourcing event → PO → ASN → goods receipt → invoice → payment.
3. **Live continuation.** The open items then ran through the same services the API uses, so the PIC rules were applied to the legacy data: supplier screening and requalification, PO validation and approval routing, invoice capture with duplicate check and 3-way match, promotion of a repeatedly bought free-text item to a material request, and an MRP run on the migrated stock.

| Legacy table | Rows | PIC target |
|---|---:|---|
| `tenants` | 8 | tenant (buyers) · supplier (suppliers) |
| `users` | 6 | app_user (buyer users, supplier portal users) |
| `supplier_profiles` | 6 | supplier.screening, supplier_category_status, qualification |
| `order_requests` | 11 | requisition + pr_line |
| `quotations` | 12 | PO price source; bid + bid_line when a request was quoted more than once |
| `negotiation_messages` | 0 | – (empty) |
| `purchase_orders` | 11 | purchase_order + po_line (legacy number kept) |
| `po_approvals` | 4 | audit trail of the PO (LEGACY_APPROVAL_*) |
| `contracts` | 0 | – (empty) |
| `advance_ship_notices` | 3 | asn + asn_line |
| `goods_receipts` | 3 | goods_receipt + gr_line |
| `sales_invoices` | 29 | invoice + invoice_line (paid: history; pending: live capture) |
| `payments` | 15 | payment |
| `inventory_items` | 19 | material + stock (buyer); catalogue_item (supplier finished goods) |
| `stock_transactions` | 29 | stock_movement (+ opening balance 561) |

## Tenant DBY: Dummy Buyer

Legacy tenant id `TENANT_BUYER_001`. Sign in with organisation **DBY**. Internal users are `<role>@dby.example` (for example `buyer@`, `ap.clerk@`, `finance.controller@`). Legacy buyer and supplier users keep their legacy e-mail addresses.

### Reconciliation

| Object | Legacy | PIC | Result |
|---|---:|---:|---|
| Suppliers | 1 | 1 | ✔ match |
| Materials (buyer inventory) | 9 | 9 | ✔ match |
| Stock movements (legacy transactions) | 13 | 13 | ✔ match |
| Requisitions (order requests) | 6 | 6 | ✔ match |
| Bids (quotations in sourcing events) | 2 | 2 | ✔ match |
| Purchase orders | 6 | 6 | ✔ match |
| ASNs | 3 | 3 | ✔ match |
| Goods receipts | 3 | 3 | ✔ match |
| Invoices | 24 | 24 | ✔ match |
| Payments | 13 | 13 | ✔ match |
| PO value | 229,050.00 | 229,050.00 | ✔ match |
| Invoice value | 672,200.00 | 672,200.00 | ✔ match |
| Paid invoice value | 347,700.00 | 347,700.00 | ✔ match |
| Payments | 347,700.00 | 347,700.00 | ✔ match |
| Stock value at standard price | 445,208.00 | 445,208.00 | ✔ match |

### Live continuation (PIC rules applied to the legacy data)

- **F8 screening:** SUP-1001 CLEAR.
- **F8 requalification opened** for compliance-flagged suppliers: SUP-1001/AERO-MACHINED, SUP-1001/AERO-PROPULSION, SUP-1001/UNCLASSIFIED.
- **F3 sourcing history:** RFQ-2026-092: 2 quotes, unit price 280.00 → 265.00.
- **F7 pending invoices → DUPLICATE:** INV-500BF04A (PO-2025-00123), INV-AD2889BE (PO-2025-00123), INV-551AC542 (PO-2025-00123), INV-D0B2C2D0 (PO-2025-00123), INV-7B0E150B (PO-2025-00123), INV-8AF8D579 (PO-2025-00089), INV-550B1F1C (PO-2025-00089), INV-00A855F0 (PO-2025-00089), INV-45FDBA86 (PO-2025-00089), INV-B5AA9552 (PO-2025-00089), INV-B5B9EFFD (PO-2025-00089).
- **F9 material governance:** MRQ-7731: 'Cryogenic Fuel Injector Nozzles for Starship Stage 2' ordered 2× as free text → IN_STEWARDSHIP.
- **F1 MRP MR-1043:** 9 materials planned, 1 planned order(s), 2 exception(s). The consumption forecast comes from legacy goods issues in the last 30 days, excluding test postings: HYD-ACT-SERVO 5, ELEC-MCU-CORTEX 120. Converted: PLO-55821 → REQ-2312 (IN_APPROVAL).
- **M01 spend governance:** 0 line(s) auto-classified by the Spend Classification Agent, 13 sent to steward review, 10 maverick hit(s) opened with an owner; category plans: none.
- **M02 / M06 / M05 agents:** 0 forecast period(s), 0 Demand Sensing recommendation(s), 1 supplier risk signal(s), 0 sourcing recommendation(s).

Open work created in the worklists: MDM_STEWARD tasks 4; REQ_APPROVAL tasks 1; invoice exceptions DUPLICATE 11; MRP BELOW_SAFETY 2.

Spend carrying maverick flags (paid history): OVER_INVOICED 259,200.00.

### Findings on the legacy data (24)

| Severity | Finding | Detail | References |
|---|---|---|---|
| Critical | `OVERPAID_PO` | PO-2025-00089: 7 invoices paid for 192,000.00 against a PO value of 29,500.00 (excess 162,500.00) | `PO-2025-00089` |
| Critical | `OVERPAID_PO` | PO-2025-00123: 4 invoices paid for 118,000.00 against a PO value of 29,500.00 (excess 88,500.00) | `PO-2025-00123` |
| Critical | `OVERPAID_PO` | PO-2025-00045: 2 invoices paid for 37,700.00 against a PO value of 29,500.00 (excess 8,200.00) | `PO-2025-00045` |
| High | `CLOSED_WITHOUT_RECEIPT` | PO-2026-58A9 is COMPLETED and paid in the legacy system with no goods receipt; loaded as CONFIRMED so the receipt can be posted | `PO-2026-58A9` |
| High | `CLOSED_WITHOUT_RECEIPT` | PO-2026-AE99 is COMPLETED and paid in the legacy system with no goods receipt; loaded as CONFIRMED so the receipt can be posted | `PO-2026-AE99` |
| High | `PAID_DISPUTED_INVOICE` | INV-EE51835D was paid while marked '[DISPUTE: Price Discrepancy - Unit price higher than agreed contract quotation.]' | `INV-EE51835D` |
| Medium | `GR_VALUE_MISMATCH` | GRN-71FF62: 100 × 295.00 on PO-2025-00045 ≠ legacy received value 2,500.00 | `GRN-71FF62`, `PO-2025-00045` |
| Medium | `SUPPLIER_COMPLIANCE_FLAG` | Dummy Supplier is flagged (FLAG) in the legacy profile; loaded as CONDITIONAL and put into requalification | `SUP-1001` |
| Low | `TEST_DATA` | Supplier 'Dummy Supplier' looks like test data; migrated and flagged | `SUP-1001` |
| Low | `TEST_DATA` | RAW-ALUM-A356: stock transaction PO-TEST-001 (+100) was a test posting; migrated for ledger completeness, excluded from the consumption forecast | `RAW-ALUM-A356`, `PO-TEST-001` |
| Low | `TEST_DATA` | RAW-ALUM-A356: stock transaction WO-TEST-99 (-25) was a test posting; migrated for ledger completeness, excluded from the consumption forecast | `RAW-ALUM-A356`, `WO-TEST-99` |
| Low | `TEST_DATA` | RAW-ALUM-A356: stock transaction GRN-E2E-TEST (+50) was a test posting; migrated for ledger completeness, excluded from the consumption forecast | `RAW-ALUM-A356`, `GRN-E2E-TEST` |
| Low | `TEST_DATA` | RAW-ALUM-A356: stock transaction DISP-E2E-TEST (-20) was a test posting; migrated for ledger completeness, excluded from the consumption forecast | `RAW-ALUM-A356`, `DISP-E2E-TEST` |
| Low | `TEST_DATA` | RAW-ALUM-A356: stock transaction GRN-E2E-TEST (+50) was a test posting; migrated for ledger completeness, excluded from the consumption forecast | `RAW-ALUM-A356`, `GRN-E2E-TEST` |
| Low | `TEST_DATA` | RAW-ALUM-A356: stock transaction DISP-E2E-TEST (-20) was a test posting; migrated for ledger completeness, excluded from the consumption forecast | `RAW-ALUM-A356`, `DISP-E2E-TEST` |
| Low | `TEST_DATA` | Request REQ-DUM-PO-2025-00123 ('Dummy Req') looks like test data | `REQ-DUM-PO-2025-00123` |
| Low | `TEST_DATA` | Request REQ-DUM-PO-2025-00089 ('Dummy Req') looks like test data | `REQ-DUM-PO-2025-00089` |
| Low | `TEST_DATA` | Request REQ-DUM-PO-2025-00045 ('Dummy Req') looks like test data | `REQ-DUM-PO-2025-00045` |
| Low | `TEST_DATA` | PO-2025-00123 belongs to a dummy/test request; migrated and flagged | `PO-2025-00123` |
| Low | `TEST_DATA` | PO-2025-00089 belongs to a dummy/test request; migrated and flagged | `PO-2025-00089` |
| Low | `TEST_DATA` | PO-2025-00045 belongs to a dummy/test request; migrated and flagged | `PO-2025-00045` |
| Low | `UNCLASSIFIED_SPEND` | REQ-DUM-PO-2025-00123: 'Dummy Req' could not be classified (no item or category in the legacy request) | `REQ-DUM-PO-2025-00123` |
| Low | `UNCLASSIFIED_SPEND` | REQ-DUM-PO-2025-00089: 'Dummy Req' could not be classified (no item or category in the legacy request) | `REQ-DUM-PO-2025-00089` |
| Low | `UNCLASSIFIED_SPEND` | REQ-DUM-PO-2025-00045: 'Dummy Req' could not be classified (no item or category in the legacy request) | `REQ-DUM-PO-2025-00045` |

- `OVERPAID_PO`: More invoices were paid against the PO than its value.
- `PAID_DISPUTED_INVOICE`: An invoice was paid while marked as disputed.
- `CLOSED_WITHOUT_RECEIPT`: The PO is closed and paid in the legacy system but nothing was received.
- `GR_VALUE_MISMATCH`: The goods receipt value does not equal quantity × PO price.
- `SUPPLIER_COMPLIANCE_FLAG`: The legacy supplier profile is flagged for compliance.
- `TEST_DATA`: Rows that look like test or dummy data.
- `UNCLASSIFIED_SPEND`: The legacy request has no item or category, so the spend could not be classified.

## Tenant GMC: Global Manufacturing Corp

Legacy tenant id `fb71d98d-1203-420f-95fd-7f6639403172`. Sign in with organisation **GMC**. Internal users are `<role>@gmc.example` (for example `buyer@`, `ap.clerk@`, `finance.controller@`). Legacy buyer and supplier users keep their legacy e-mail addresses.

### Reconciliation

| Object | Legacy | PIC | Result |
|---|---:|---:|---|
| Suppliers | 5 | 5 | ✔ match |
| Materials (buyer inventory) | 0 | 0 | ✔ match |
| Stock movements (legacy transactions) | 0 | 0 | ✔ match |
| Requisitions (order requests) | 5 | 5 | ✔ match |
| Bids (quotations in sourcing events) | 0 | 0 | ✔ match |
| Purchase orders | 5 | 5 | ✔ match |
| ASNs | 0 | 0 | ✔ match |
| Goods receipts | 0 | 0 | ✔ match |
| Invoices | 5 | 5 | ✔ match |
| Payments | 2 | 2 | ✔ match |
| PO value | 233,983.50 | 233,983.50 | ✔ match |
| Invoice value | 142,868.00 | 142,868.00 | ✔ match |
| Paid invoice value | 69,116.81 | 69,116.81 | ✔ match |
| Payments | 69,116.81 | 69,116.81 | ✔ match |
| Stock value at standard price | 0.00 | 0.00 | ✔ match |

### Live continuation (PIC rules applied to the legacy data)

- **F8 screening:** SUP-1001 CLEAR, SUP-1002 CLEAR, SUP-1003 CLEAR, SUP-1004 CLEAR, SUP-1005 CLEAR.
- **F8 requalification opened** for compliance-flagged suppliers: SUP-1001/UNCLASSIFIED, SUP-1004/UNCLASSIFIED, SUP-1005/UNCLASSIFIED.
- **F5 approval routing:** PO-2026-6488: risk 58 (PRICE_DEVIATION, SUPPLIER_NOT_QUALIFIED) → IN_APPROVAL.
- **F7 pending invoices → MISSING_GR:** LEG-567A1A83 (PO-2026-2473), LEG-8B1CCF63 (PO-2026-8183), LEG-66157773 (PO-2026-1175).
- **M01 spend governance:** 0 line(s) auto-classified by the Spend Classification Agent, 2 sent to steward review, 3 maverick hit(s) opened with an owner; category plans: none.
- **M02 / M06 / M05 agents:** 0 forecast period(s), 0 Demand Sensing recommendation(s), 3 supplier risk signal(s), 0 sourcing recommendation(s).

Open work created in the worklists: PO_APPROVAL tasks 1; invoice exceptions MISSING_GR 3.

Spend carrying maverick flags (paid history): NO_GOODS_RECEIPT 69,116.81, PO_NOT_APPROVED 33,884.50.

### Findings on the legacy data (12)

| Severity | Finding | Detail | References |
|---|---|---|---|
| Critical | `PAID_BEFORE_APPROVAL` | LEG-F089138D (33,884.50) was paid against PO-2026-6488, which is still pending approval in the legacy system | `LEG-F089138D`, `PO-2026-6488` |
| High | `PAID_WITHOUT_RECEIPT` | LEG-F089138D (33,884.50) was paid on PO-2026-6488 without a goods receipt | `LEG-F089138D`, `PO-2026-6488` |
| High | `PAID_WITHOUT_RECEIPT` | LEG-AD1773EE (35,232.31) was paid on PO-2026-7022 without a goods receipt | `LEG-AD1773EE`, `PO-2026-7022` |
| High | `QUOTE_PO_MISMATCH` | PO-2026-6488: PO total 125,000.00 vs approved quotation dd2a270b-18d2-4c23-a113-41c01594e55b 33,884.50; loaded with a price deviation (risk +18) | `PO-2026-6488`, `dd2a270b-18d2-4c23-a113-41c01594e55b` |
| Medium | `SUPPLIER_COMPLIANCE_FLAG` | Lawrence LLC is flagged (FLAG) in the legacy profile; loaded as CONDITIONAL and put into requalification | `SUP-1001` |
| Medium | `SUPPLIER_COMPLIANCE_FLAG` | Gonzalez Inc is flagged (FLAG) in the legacy profile; loaded as CONDITIONAL and put into requalification | `SUP-1004` |
| Medium | `SUPPLIER_COMPLIANCE_FLAG` | Morrison PLC is flagged (FLAG) in the legacy profile; loaded as CONDITIONAL and put into requalification | `SUP-1005` |
| Low | `UNCLASSIFIED_SPEND` | REQ-2311: 'Switchable next generation attitude' could not be classified (no item or category in the legacy request) | `REQ-2311` |
| Low | `UNCLASSIFIED_SPEND` | REQ-2312: 'Optional 6thgeneration projection' could not be classified (no item or category in the legacy request) | `REQ-2312` |
| Low | `UNCLASSIFIED_SPEND` | REQ-2313: 'De-engineered directional complexity' could not be classified (no item or category in the legacy request) | `REQ-2313` |
| Low | `UNCLASSIFIED_SPEND` | REQ-2314: 'Extended attitude-oriented hierarchy' could not be classified (no item or category in the legacy request) | `REQ-2314` |
| Low | `UNCLASSIFIED_SPEND` | REQ-2315: 'Automated secondary process improvement' could not be classified (no item or category in the legacy request) | `REQ-2315` |

- `PAID_BEFORE_APPROVAL`: An invoice was paid while its PO was still waiting for approval.
- `PAID_WITHOUT_RECEIPT`: An invoice was paid with no goods receipt (no 3-way match).
- `QUOTE_PO_MISMATCH`: The PO value differs from the approved quotation.
- `SUPPLIER_COMPLIANCE_FLAG`: The legacy supplier profile is flagged for compliance.
- `UNCLASSIFIED_SPEND`: The legacy request has no item or category, so the spend could not be classified.

## Decisions and actions for the business

1. **Currency.** The legacy schema stores amounts without a currency, and the legacy screens labelled prices in USD. The load kept the amounts at face value. If they are USD, re-run the load with `--fx-rate <cutover rate>`.
2. **Overpayments.** Recover or confirm the excess payments listed under `OVERPAID_PO` and `PAID_BEFORE_APPROVAL` before go-live. In PIC, the pending duplicates are held with a payment block.
3. **Bank details.** The legacy system never stored supplier bank accounts. Each migrated supplier has an inactive placeholder that carries the paid history. New payments stay blocked until the supplier completes the MDM-04 bank change (two finance approvers, call-back, cooling-off).
4. **Test data.** The rows under `TEST_DATA` were migrated so that the books reconcile. Decide whether to reverse them in PIC or purge them from the source before the final cutover.
5. **Classification.** `UNCLASSIFIED` spend needs a category before it counts towards category strategies and savings.

Regenerate this report with `python -m app.pic.tools.neon_setup` (it is rewritten whenever a legacy tenant is migrated).
