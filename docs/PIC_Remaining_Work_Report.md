# PIC Remaining Work: Workflows and Datasets

| | |
|---|---|
| Basis | Product Blueprint /01 (flows F1–F9, §22 purchase types, §23 industry templates), Technical Document /02 (§6 state machines, §8 process definitions, §12 integration, §15 NFRs) |
| Evidence | Process definitions in `backend/app/pic/platform/process_defs.py`; step, branch and row counts from a full rehearsal of the Neon load (identical data to Neon) |
| Date | 28 October 2026 |
| Companion | `docs/PIC_Module_Gap_Analysis.md` (modules, screens, agents) |

## Contents

1. [Summary](#1-summary)
2. [Workflows F1–F9](#2-workflows-f1f9)
3. [Workflows of the intelligence and governance modules](#3-workflows-of-the-intelligence-and-governance-modules)
4. [Datasets](#4-datasets)
5. [Work plan](#5-work-plan)
6. [What you need to supply](#6-what-you-need-to-supply)

---

## 1. Summary

**Workflows.** All nine blueprint flows are implemented: 84 process steps across F1–F9, each with its gateways, human tasks, SLAs and audit. The seeded data has run through **83 of the 84 steps**. The one step never reached is F4-10, contract renew / expire / terminate, because the seeded contracts are still within their validity.

**What remains in the workflows** is of three kinds:

| Kind | Count | Examples |
|---|---|---|
| A. Branches that are built and tested but **never exercised by the seeded data** | 22 | Rejection and return paths, MRP simulation, GR reversal, ERS, invoice dispute, contract expiry and renewal, integration dead-letter and replay |
| B. **Functional pieces not built** | 14 | Punch-out, EDI/e-mail PO transmission, ERP planned-order import, reverse-auction live bidding, clarification board, contract termination and amendments, MDM-04 tax/address change, 4-way match |
| C. **External connections** | 8 | Real ERP posting, GST IRP, e-signature, bank payment files, sanctions/risk feeds, SSO, notifications, LLM |

**Datasets.** Every PIC table that should have data does, with one exception: `fx_rate`, which waits for your rates. Two tables are empty on purpose:
- `reconciliation_item`: the platform and ERP reconcile with no differences;
- `idempotency_record`: it fills only from live API calls.

Three gaps remain in the datasets:
1. **Depth.** Only the Axion demo tenant exercises sourcing, contracts, receiving with quality, service entries, budgets, scorecards and forecasting. The migrated GMC and DBY tenants hold only what the legacy system had.
2. **Realism.** The Axion ERP history and the supplier twins are generated demo data. No real ERP extract has been loaded.
3. **Breadth.** There are no datasets for:
   - the five other industry templates;
   - the non-standard purchase types (expense, capital asset, consignment, subcontracting);
   - the volumes needed for the NFR tests.

## 2. Workflows F1–F9

Legend:
- **Exercised**: the seeded data passes through this branch.
- **Built, not exercised**: the code and tests cover it, but no seeded case does.
- **Not built**: the specification asks for it and it does not exist yet.

### F1 · MRP run → planned order → requisition (`pic.mrp-to-pr`, 10 steps)

| | |
|---|---|
| Exercised | Net-change run MR-1043 (AXN) and a regenerative run on the migrated stock (DBY), netting 12,000 − (1,400 + 1,200 + 600) + 200 = 9,000, planned order firmed and converted to REQ-2311 with source determination, BELOW_SAFETY exceptions, forecast override released to MRP |
| Built, not exercised | **Simulation run** (F1-05 "yes": results only, no documents); PAST_DUE and RESCHEDULE_IN/OUT exceptions; deletion of unfirmed planned orders by the next run; second plant P200; lot-sizing policies other than the seeded ones (EOQ, period, fixed) |
| Not built | **ERP planned-order import** (AD-05, for tenants that run MRP in the ERP); factory calendar maintenance screen; WBS and reservation demand |

### F2 · Guided buying → requisition (`pic.requisition`, 9 steps)

| | |
|---|---|
| Exercised | Contract, catalogue, material and free-text routes (F2-03); reusable item → parallel MDM request (F2-05 yes and no); budget check; DMN-01 approval chains, including the auto-approved catalogue line under ₹25,000 |
| Built, not exercised | **Approver rejects or returns** a requisition (all 42 seeded task decisions are approvals); budget **hard stop** for capex/WBS; soft stop with justification; capex committee for asset lines; re-approval after a value, account or supplier change; DMN-01 band edges (24,999 / 25,000 / 2 L / 10 L) |
| Not built | **Punch-out** (cXML / OCI) carts returning as catalogue lines; P-card policy; mobile approval UI |

### F3 · Strategic sourcing → award (`pic.sourcing-award`, 10 steps)

| | |
|---|---|
| Exercised | RFQ-2231 with weights locked at publish, sealed bids, TCO and should-cost, a second negotiation round (F3-05 yes), capacity-constrained award scenarios, 60/40 award above ₹50 L with approval and conflict declaration; legacy RFQ-2026-092 (two rounds) |
| Built, not exercised | Award below ₹50 L and lowest bid (F3-07 "no", no approval needed); event cancellation; early-unseal attempt being blocked (tested in the suite, not seeded) |
| Not built | **Clarification Q&A board** (F3-03 "clarifications" exists only as the step name); **reverse-auction live bidding**; RFI/RFP-specific templates (the event types exist; RFQ is the only one seeded) |

### F4 · Contract lifecycle (`pic.contract`, 10 steps)

| | |
|---|---|
| Exercised | Draft from award with playbook clauses, AI redline, supplier redline, approval above ₹1 Cr (F4-05 yes), two-party signature, activation publishing prices and the 60/40 quota, LME index reset creating new validity periods, consumption tracking; a manual value contract drafted (SA-5522) |
| Built, not exercised | **F4-10 renewal / expiry**: the renewal timer fires 120 days before expiry and the expiry timer at validity end, but no seeded contract has reached either; approval below ₹1 Cr (F4-05 no); consumption threshold alerts at 80/90/100% (no contract has reached 80%); completing an obligation |
| Not built | **Termination** and **amendments / variations** as contract versions; external **e-signature** provider (signatures are recorded internally with a document hash); AI extraction of clauses from uploaded legacy contracts |

### F5 · Purchase order → confirmation → delivery (`pic.po`, 10 steps)

| | |
|---|---|
| Exercised | Inheritance from requisition, contract and source list; risk score; touchless release (F5-04 yes) and every non-touchless reason (info record, manual, quote); approval; confirmation within tolerance; buyer change order (v2); supplier change request after confirmation (v3); expediting follow-up |
| Built, not exercised | **Supplier proposes a change outside tolerance at confirmation** (F5-08 "no" → buyer review); **supplier rejects** the PO; confirmation SLA breach → expediting task; release to a blocked supplier being refused; PO cancellation and **closure** (no PO is CLOSED) |
| Not built | **Transmission by EDI (ORDERS/ORDCHG/ORDRSP) or e-mail** (portal only); schedule lines (multiple delivery dates per line) |

### F6 · Goods receipt / service entry → quality (`pic.receipt`, 9 steps)

| | |
|---|---|
| Exercised | GR against ASN; quality-managed lot GR-90231 with 5,380 accepted and 20 rejected → return delivery RD-4410 → CAPA-301; non-quality GR; service entry sheets approved; stock, GR/IR and scorecard updates |
| Built, not exercised | **GR reversal**; fully rejected lot; over-delivery above tolerance being blocked; **consignment** GR (liability on withdrawal) and **subcontracting** GR (component consumption), configured in the purchase-type matrix but no PO of those types; SES rejection |
| Not built | **E-way bill** capture on ASN; **EDI DESADV**; batch/serial/expiry traceability beyond the batch field; measurement- or milestone-based SES (construction / IT templates) |

### F7 · Invoice → match → ERP posting → payment (`pic.invoice`, 9 steps)

| | |
|---|---|
| Exercised | Portal capture, hard and fuzzy duplicate check, 2-way, 3-way and SES match, quantity exception → credit note, price exception → variance accepted, duplicate rejected, idempotent posting with replay, payment runs, realised savings; legacy capture with 11 duplicates and 3 missing-GR holds; reconciliation REC-101 |
| Built, not exercised | **ERS** (self-billing) for consignment and scheduling agreements; **dispute** resolution; tax exception (IRN mismatch); **ERP timeout, retry, dead-letter and replay** (covered by tests with simulated faults, not in the seed); bank-change cooling-off blocking a payment |
| Not built | **4-way match** (named in F7-03); **GST IRP** validation of IRN and QR; **bank payment file** (H2H / NEFT batch); EDI INVOIC; OCR capture of PDF invoices (the channel exists, extraction does not) |

### F8 · Supplier onboarding & qualification (`pic.supplier-onboarding`, 9 steps)

| | |
|---|---|
| Exercised | Registration, profile and certificates, screening (duplicates and sanctions: ZAT006 blocked), dual bank verification with call-back, qualification QUALIFIED and CONDITIONAL with a waiver, ERP sync, risk monitoring |
| Built, not exercised | **Qualification rejected** (F8-06 "no"); **certificate expiry** turning a supplier Conditional (all 8 certificates are valid); Preferred / Exited status changes; block with open POs |
| Not built | Supplier **self-registration by invitation e-mail**; questionnaire builder; licensed sanctions / financial / news feeds |

### F9 · Material master governance (`pic.material-request`, 8 steps)

| | |
|---|---|
| Exercised | Duplicate score below 0.92 → four domain stewards → ERP sync → linked to the PR line (MRQ-7731); duplicate ≥ 0.92 merged (MRQ-7732); a migrated request in stewardship (DBY) |
| Built, not exercised | **Steward rejects** a request; steward override of a duplicate block with a reason; the 0.75–0.92 warning band |
| Not built | **MDM-04 supplier tax-ID and address changes** (bank changes are built); bulk material import / cleansing |

### Process step coverage

| Flow | Steps | Executed | Gateways exercised on both branches |
|---|---:|---:|---|
| F1 | 10 | 10 | 0 of 1 (simulation never run) |
| F2 | 9 | 9 | 2 of 2 |
| F3 | 10 | 10 | 1 of 2 |
| F4 | 10 | 9 | 0 of 1 |
| F5 | 10 | 10 | 1 of 2 |
| F6 | 9 | 9 | 2 of 2 |
| F7 | 9 | 9 | 1 of 1 |
| F8 | 9 | 9 | 1 of 1 (qualified and conditional; rejected never) |
| F9 | 8 | 8 | 1 of 1 |
| **Total** | **84** | **83** | **9 of 13** |

## 3. Workflows of the intelligence and governance modules

| Module flow | Exercised | Remaining |
|---|---|---|
| Spend classification → steward review | 218 auto-classified, 48 reviewed (44 decided, 4 open); legacy lines queued | **Reclassification** by a steward (all decisions so far confirmed the proposal); a UNSPSC or customer taxonomy import |
| Maverick hit → disposition | 446 hits in total; policy breach and recovery dispositions | Accepted-exception and false-positive dispositions; recovery follow-up into a debit note |
| Category plan → approval | 15 plans, ALU-DIECAST approved | Plan budget used as a **budget check** at requisition (category budgets are not yet linked to DMN-01) |
| Forecast → Demand Sensing → release | DC-331 over-forecast by 22% → recommendation accepted → override released | A **rejected** recommendation; forecasts for legacy materials (too few goods issues) |
| Risk signal → mitigation | 8 signals, recommendations raised | **Mitigate / close** a signal; feed ingestion (adapter ready, no feed) |
| CAPA | CAPA-301 opened from a rejection and responded to by the supplier | **Quality verification and closure** (left open on purpose in the seed) |
| Reconciliation | REC-101, 0 differences | A difference and its resolution (needs a real ERP or a simulated mismatch) |
| Agent autonomy | Defaults and on-demand runs | Automatic **suspension** when acceptance falls below 70% (needs ≥ 20 feedback events) |

## 4. Datasets

### 4.1 Coverage by tenant

| Area | AXN (demo, manufacturing) | GMC (migrated) | DBY (migrated) |
|---|---|---|---|
| Organisation | 1 company code, 2 plants, 2 storage locations, 3 cost objects | 1 / 1 / 1 / 2 | 1 / 1 / 4 / 2 |
| Users | 31 | 30 | 24 |
| Suppliers | 26 (6 onboarded through F8 and 20 ERP vendor masters) | 5 | 1 |
| Materials | 4 | 0 | 9 |
| Requisitions / POs | 7 / 9 | 5 / 5 | 7 / 6 |
| Sourcing / contracts | 1 event, 3 contracts | — | 1 event, — |
| Receiving | 5 ASN, 4 GR, 3 inspection lots, 2 SES | — | 3 ASN, 3 GR |
| Invoices / payments | 6 / 4 | 5 / 2 | 24 / 13 |
| Spend lines | 2,573 (24 months ERP history + platform) | 2 | 13 |
| Forecasts / MRP | 60 forecast periods, 1 MRP run | — | 1 MRP run |
| Scorecards, certificates, twin | 5 / 8 / 4 | — | — |
| Budgets, savings | 3 budgets, 2 initiatives | — | — |

GMC and DBY are thin because the legacy system held little: 156 rows in 15 tables, no contracts, no certificates, no budgets. They can only become richer from real ERP data (§4.4).

### 4.2 Empty tables

| Table | Why it is empty | What fills it |
|---|---|---|
| `fx_rate` | No rates were invented | You provide treasury rates (ADM-01 or the API); needed if the legacy amounts are USD |
| `reconciliation_item` | No differences between platform and ERP | A real ERP, or a seeded mismatch case (§5 A) |
| `idempotency_record` | Filled only by API calls with an Idempotency-Key | Live use |

### 4.3 Generated or placeholder data

The data in this table is generated or a placeholder; it must be replaced before production.

| Data | Status | Replace with |
|---|---|---|
| AXN ERP spend history (2,568 lines, Oct 2024 – Sep 2026) and 20 ERP vendors | Generated, calibrated to blueprint AIX-01 | A real SAP/ERP extract: 24–36 months of invoices and POs (TD §12.4) |
| AXN consumption history (DC-330, DC-331, FK-M8-50) | Generated | The ERP stock and consumption feed |
| Supplier twins (capacity, trust, late probability) | Seeded for 4 suppliers | The Supplier Capability Digital Twin service |
| Sanctions list | 4 fictitious SAMPLE-LIST names | A licensed sanctions feed |
| Certificates | 8 records, all valid | Supplier uploads with expiry dates |
| Bank accounts of migrated suppliers | Inactive placeholders | MDM-04 bank changes by the suppliers |
| GST / IRN | IRN computed locally | GST IRP validation |
| Industry templates | Configuration for 6 packs; data only for manufacturing | The demo datasets in §4.4 |

### 4.4 Datasets not created yet

| # | Dataset | Spec | Purpose | Size |
|---|---|---|---|---|
| D1 | **Branch cases** for the 22 unexercised branches in §2, seeded as operating cases 9–n so every gateway has both outcomes | TD §17 E2E | Demo and regression coverage | M |
| D2 | **Purchase-type cases**: expense (receipt-less below threshold), capital asset (capex committee + WBS hard stop), consignment (GR to consignment stock, ERS settlement), subcontracting (component consumption) | BP §22 | P08 differentiation | M |
| D3 | **Construction** demo tenant: WBS C-2207 "Tower B structure", subcontract SC-118, SES at 35% progress, 5% retention, variation order | BP §23 | Industry pack | L |
| D4 | **IT services** demo tenant: SOW-4410 T&M, rate card RC-22, timesheet SES 320 h, licence renewal alert | BP §23 | Industry pack | M |
| D5 | **Logistics** demo tenant: lane CHE→PNQ 32 ft MXL, rate 54/km + fuel index, POD confirmation, freight audit | BP §23 | Industry pack | M |
| D6 | **Healthcare** demo tenant: consignment implant KN-77, lot/expiry, usage-triggered PO, recall trace | BP §23 | Industry pack | L |
| D7 | **General enterprise** demo tenant: laptop punch-out order ₹78,500, single approval | BP §23 | Industry pack (needs punch-out) | M |
| D8 | **Volume datasets** for NFRs: 50,000 materials (MRP < 10 min), 5 M invoices/year, 50 M spend lines (cube < 3 s), 10,000 concurrent users | TD §15 | Performance tests | L |
| D9 | **AI evaluation sets**: labelled spend lines (classification accuracy), forecast actuals (MAPE), duplicate pairs (dedup precision/recall), Copilot questions (answer-contract completeness ≥ 99%) | TD §17 | Before raising autonomy levels | M |
| D10 | **Real tenant masters**: materials, suppliers (with bank and tax IDs), contracts, open POs and open AP from your ERP | TD §12.4 | Pilot | Depends on ERP |
| D11 | **Reference data**: FX rates, HSN/SAC and GST rates, holiday calendars per plant, UNSPSC or your own taxonomy | TD §4, BP §7 | Correct tax, dates and classification | S |

Sizes: S ≈ 1–2 days, M ≈ 3–5 days, L ≈ 1–2 weeks of build and verification.

## 5. Work plan

### A. Can be built now (no external input)

| Priority | Item | Covers |
|---|---|---|
| 1 | Operating cases 9–20 for the unexercised branches. Each needs its own seeded case: requisition rejected and returned; MRP simulation; PAST_DUE / reschedule exceptions; GR reversal; fully rejected lot; supplier rejects a PO; change outside tolerance; ERS settlement; invoice dispute; ERP timeout → dead-letter → replay; certificate expiry → Conditional; qualification rejected; steward rejects a material; contract below ₹1 Cr; contract reaching 80/90/100%; contract expiry → renewal decision; PO closure | §2 A, D1 |
| 2 | Purchase-type cases: expense, capital asset with capex committee and WBS hard stop, consignment, subcontracting | D2 |
| 3 | Contract termination and amendments (variation orders as versions) | F4 |
| 4 | MDM-04 tax-ID and address changes with dual approval | F9 / M03 |
| 5 | Clarification board and reverse-auction live bidding | F3 |
| 6 | 4-way match (PO + GR + inspection + invoice) and the category budget check at requisition | F7, M01 |
| 7 | ERP planned-order import adapter (file / API) | F1, AD-05 |
| 8 | Volume generator and the k6 / MRP / cube performance runs (on a production-like environment) | D8 |
| 9 | AI evaluation sets from the seeded and migrated data, plus a labelling screen for stewards | D9 |
| 10 | Industry demo tenants D4 and D5 (no external system needed), then D3 and D6 | Phase 4 |

### B. Needs your input or a third-party system

Real ERP posting and inbound masters (D10), GST IRP, e-signature, bank payment files, EDI / punch-out (needed for D7), sanctions and risk feeds, SSO / MFA, e-mail/SMS notifications, the LLM gateway.

## 6. What you need to supply

1. **An ERP extract or sandbox** (SAP S/4HANA first): vendors, materials, contracts, open POs, open AP and 24–36 months of invoice/PO history. This replaces the generated AXN history and fills GMC/DBY properly.
2. **FX rates** and the currency of the legacy amounts.
3. **Reference data**: HSN/SAC master and GST rates, plant holiday calendars, your spend taxonomy (or confirm UNSPSC).
4. **Credentials**: GST IRP / GSP, e-sign provider, bank host-to-host, EDI / punch-out suppliers, sanctions feed, identity provider, LLM gateway.
5. **The test workbook** AHG/PRC/PIC/2026-10/03, so that the branch cases (§5 A1) match its E2E numbering.
6. **Priorities**: which purchase types and which industry template come first.
