# PIC Module Gap Analysis and Build Status

| | |
|---|---|
| Compared against | Product Blueprint AHG/PRC/PIC/2026-10/01 (13 modules, 58 screens, 14 agents, 6 industry templates) and Development Technical Document AHG/PRC/PIC/2026-10/02 (services, data model, APIs, events, integration, AI, security, NFRs) |
| Codebase | `backend/app/pic` (FastAPI, schema `pic`), `frontend/src/app/pic` (Next.js) |
| Date | 27 October 2026 |
| Status legend | **Built**: implemented, seeded with data, tested. **Built (this release)**: added in this release. **Partial**: works, but part of the specification is missing. **Open**: not built |

## Contents

1. [Summary](#1-summary)
2. [What this release added](#2-what-this-release-added)
3. [Module status M01–M13](#3-module-status-m01m13)
4. [Screen catalogue (58 screens)](#4-screen-catalogue-58-screens)
5. [AI agents (14 + Copilot)](#5-ai-agents-14--copilot)
6. [Still open, and why](#6-still-open-and-why)
7. [Technology deviations from the Technical Document](#7-technology-deviations-from-the-technical-document)
8. [Data delivered](#8-data-delivered)
9. [What you need to supply or decide](#9-what-you-need-to-supply-or-decide)

---

## 1. Summary

Before this release, flows F1–F9 were complete end to end. The analytical and governance parts of the blueprint were missing or partial:
- spend intelligence beyond the cube (SPD-01..09);
- demand forecast review (MRP-04);
- supplier risk and performance (SLM-03/04, CAPA);
- obligations and renewals (CLM-04);
- PO confirmations and expediting (PO-03/04);
- posting reconciliation and payables insights (INV-03/04);
- manual savings initiatives and contracts;
- five of the 14 agents;
- the agent console commands;
- organisation, user and template administration (ADM-01/04).

This release builds all of those (§2). Their APIs, screens, seeded datasets and tests are in place, and they run on Neon through the same `neon_setup` command.

**What remains open** falls into two groups (§6):
- items that need an external system or credentials you hold: identity provider, ERP sandboxes, e-invoice, e-sign, LLM gateway, risk feeds and hosting;
- later-phase items: the Phase 4 industry demo tenants, platform infrastructure at production scale, and ML models trained on your data.

## 2. What this release added

| Module | Added | Screens | API |
|---|---|---|---|
| M01 Spend | Taxonomy (segment → family → category), Spend Classification Agent (L3, threshold 0.80) with steward queue, nine tenant-configurable maverick rules with owner + disposition, supplier concentration (HHI), duplicate-supplier clusters, contract compliance and price-variance leakage, spend forecast with 80% band, category plans with Kraljic positioning, levers, wave plan, budget and savings target, approval with owner ≠ approver | SPD-01, 02, 03, 05, 06, 07, 09 (SPD-04 cube and SPD-08 savings existed) | `/v1/spend/overview, treemap, suppliers, compliance, forecast, maverick, maverick-hits/{id}/disposition, classification-reviews, category-plans` |
| M02 MRP | Forecast table, exponential-smoothing forecast from consumption, bias and MAPE, override with mandatory reason, release to FORECAST demand elements for net-change MRP, Demand Sensing Agent (L1) | MRP-04 | `/v1/forecasts, forecasts/generate, forecasts/{id}/override, /release` |
| M06 Supplier | Risk signals from screening, certificate expiry, scorecard OTIF/PPM, the supplier twin, financial tier and the bank-change-plus-invoice fraud rule (§14), with a feed adapter for licensed risk providers. Also: Supplier Risk Agent (L1), CAPA (opened automatically on a quality rejection; supplier response; quality verification), Preferred status (needs 3-period scorecard evidence) and Exited status | SLM-03, SLM-04, portal CAPA response | `/v1/supplier-risk, supplier-risk/scan, risk-signals/{id}/mitigation, suppliers/{code}/risk-signals, supplier-performance, capas, suppliers/{code}/categories/{cat}/status` |
| M05 Sourcing | Sourcing Strategy Agent (L1): event type, ranked qualified invitees and scoring weights by Kraljic quadrant for unsourced requisition lines | (recommendations inbox) | `/v1/agents/SOURCING_STRATEGY/runs` |
| M07 Contract | Manual contract creation (`POST /v1/contracts`, idempotent) from SCHEDULING_AGREEMENT, QUANTITY_CONTRACT and VALUE_CONTRACT templates, obligation tracker, renewals calendar | CLM-01 (new form), CLM-03 renewals, CLM-04 | `/v1/contracts, contract-templates, obligations, contracts-renewals` |
| M08 PO | Change requests after confirmation (supplier or buyer → buyer decision → version n+1 → re-confirmation), confirmation SLA and change-rate KPIs, expediting cockpit with twin late-risk and drafted follow-ups | PO-03, PO-04, portal change request | `/v1/purchase-orders/{ref}/change-requests, po-confirmations, expediting, purchase-orders/{ref}/expedite` |
| M10 Invoice | Reconciliation of platform postings against ERP documents (count, amount net of credit notes, document number) with items and resolution (§12.2 step 5). Payables insights: due-date ladder, DPO, discount capture, first-pass match, duplicates prevented and GR/IR ageing | INV-03, INV-04 | `/v1/reconciliation/runs, reconciliation/items/{id}/resolve, payables/insights` |
| M11 Savings | Manual initiatives with the four baseline methods of blueprint §26 (last price, 12-month weighted average, standard, should-cost) fixed at creation; negotiated price; lost | SAV-01 | `/v1/savings/initiatives, savings/{ref}/negotiate, /lose` |
| M12 Agents | Recommendations with human accept/reject feeding the acceptance rate and automatic suspension; on-demand runs; autonomy changes with L3/L4 guards and audit | AIX-03 | `/v1/agents/{code}/autonomy` (PUT), `/agents/{code}/runs`, `/recommendations`, `/recommendations/{id}/feedback` |
| M13 Admin | Currencies and effective-dated FX rates with conversion; organisation view (company codes, plants, calendars, storage locations, cost objects); user role editor that checks SoD role pairs and MFA for sensitive roles; six industry template packs applied at tenant creation (rule overrides); upgrade path for tenants created by earlier releases (`ensure_extensions`) | ADM-01, ADM-04, templates | `/v1/admin/organisation, fx-rates, users, users/{id}/roles, users/{id}/active, templates` |

**Verification:**
- 63 backend tests pass, 16 of them new for these modules. They cover RLS on the new tables, SoD on approvals and role assignment, idempotent contract creation and an idempotent upgrade path.
- A real-browser run in Edge passes on all 21 new or extended screens, signed in as the role that owns each one.
- The full Neon load was rehearsed on a fresh database: all three audit chains are valid and legacy reconciliation is OK.

Schema: migration `0003` adds 14 tables, each with forced row-level security and `pic_app` grants. The append-only and read-only grants from `0002` are unchanged. It also adds four columns to `spend_line`: description, PO line, price variance and source.

## 3. Module status M01–M13

| Module | Status | What is still missing against the specification |
|---|---|---|
| M01 Spend & Category Intelligence | **Built (this release)** | ClickHouse cube for 50 M lines (Postgres serves the MVP volume); multi-currency normalisation in the cube is ready (`fx_rate`, `admin.convert`) but all current spend is INR |
| M02 Demand Planning & MRP | **Built** + MRP-04 this release | ERP planned-order import adapter (AD-05) for tenants that run MRP in the ERP; gradient-boosted forecast model (exponential smoothing today) |
| M03 Material & Supplier MDM | **Partial** | MDM-04 covers bank changes (dual approval, call-back, cooling-off); tax-ID and address changes through `supplier_master_change` are not built |
| M04 Requisitioning & Guided Buying | **Partial** | cXML/OCI punch-out sessions; the Guided Buying Agent is the rules-based search (contract → catalogue → material → free text) and does not yet log agent runs |
| M05 Strategic Sourcing | **Built** + strategy agent this release | Clarification Q&A board; reverse-auction live bidding UI |
| M06 Supplier Lifecycle & Performance | **Built (this release)** | Licensed risk feeds (adapter endpoint ready); questionnaire builder |
| M07 Contract Lifecycle | **Built** + CLM-04 this release | External e-signature provider (signatures are recorded with a document hash); AI clause extraction from uploaded legacy contracts |
| M08 Operational Purchasing | **Built** + PO-03/04 this release | EDI ORDERS/ORDCHG/ORDRSP transmission (portal transmission only) |
| M09 Fulfilment, GR & SES | **Built** | EDI DESADV; e-way bill capture on ASN |
| M10 Invoice & Finance | **Built** + INV-03/04 this release | GST IRP validation of IRN/QR (checked locally); real ERP connector; EDI INVOIC |
| M11 Savings | **Built** + initiatives this release | — |
| M12 Predictive Intelligence & Agents | **Partial** | LLM gateway, pgvector retrieval (`retrieval_chunk`), trained models with MLflow and offline evaluation sets (§13.1) |
| M13 Platform, Workflow & Admin | **Partial** | SSO/MFA through an IdP; BPMN designer and simulation (ADM-03 shows live process paths but does not edit models); notifications (e-mail/SMS); separate supplier-portal app |

## 4. Screen catalogue (58 screens)

| Screen | Name | Route | Status |
|---|---|---|---|
| SPD-01 | Spend Intelligence Overview | `/pic/spend` (Overview) | Built (this release) |
| SPD-02 | Spend by Category | `/pic/spend` (Categories) | Built (this release) |
| SPD-03 | Spend by Supplier | `/pic/spend` (Suppliers) | Built (this release) |
| SPD-04 | Spend by Plant & Company Code | `/pic/spend` (Cube) | Built |
| SPD-05 | Contracted vs Non-Contracted | `/pic/spend` (Contract compliance) | Built (this release) |
| SPD-06 | Maverick Spend Analysis | `/pic/spend` (Maverick) | Built (this release) |
| SPD-07 | Category Strategy Workbench | `/pic/spend` (Category strategy) | Built (this release) |
| SPD-08 | Savings & Pipeline Tracker | `/pic/savings` | Built |
| SPD-09 | Spend Forecast | `/pic/spend` (Forecast) | Built (this release) |
| MRP-01 | MRP Run Console | `/pic/mrp` | Built |
| MRP-02 | Planner Workbench | `/pic/mrp/[ref]` | Built |
| MRP-03 | Exception Monitor | `/pic/mrp` | Built |
| MRP-04 | Demand Forecast Review | `/pic/mrp/forecast` | Built (this release) |
| MDM-01 | New Material Request | `/pic/materials` | Built |
| MDM-02 | Steward Workbench | `/pic/materials/[ref]` | Built |
| MDM-03 | Duplicate Resolution | `/pic/materials/[ref]` | Built |
| MDM-04 | Supplier Master Change | `/pic/suppliers/[code]` | Partial (bank only) |
| REQ-01 | Guided Buying Home | `/pic/requisitions/new` | Built (no punch-out) |
| REQ-02 | Requisition Form | `/pic/requisitions/new` | Built |
| REQ-03 | Approval Inbox | `/pic/tasks` | Built |
| REQ-04 | Buyer Workbench | `/pic/buyer` | Built |
| SRC-01 | Sourcing Project Cockpit | `/pic/sourcing` | Built |
| SRC-02 | Event Builder | `/pic/sourcing/new` | Built |
| SRC-03 | Bid Comparison & TCO | `/pic/sourcing/[ref]` | Built |
| SRC-04 | Award Scenario Studio | `/pic/sourcing/[ref]` (scenarios) | Built |
| SRC-05 | Award Approval | `/pic/sourcing/[ref]` | Built |
| SLM-01 | Supplier 360 | `/pic/suppliers/[code]` | Built |
| SLM-02 | Onboarding & Qualification | `/pic/suppliers`, `/pic/suppliers/new` | Built |
| SLM-03 | Performance Scorecard | `/pic/suppliers/performance` | Built (this release) |
| SLM-04 | Supplier Risk Monitor | `/pic/suppliers/risk` | Built (this release) |
| SLM-05 | Supplier Portal | `/pic/portal` | Built (same app; separate app open) |
| CLM-01 | Contract Workspace | `/pic/contracts/[ref]`, `/pic/contracts/new` | Built (manual create this release) |
| CLM-02 | Clause Review & Redline | `/pic/contracts/[ref]` | Built |
| CLM-03 | Consumption & Compliance | `/pic/contracts/[ref]`, renewals in `/pic/contracts/obligations` | Built |
| CLM-04 | Obligation Tracker | `/pic/contracts/obligations` | Built (this release) |
| PO-01 | PO Workbench | `/pic/purchase-orders` | Built |
| PO-02 | PO Detail & Validation | `/pic/purchase-orders/[ref]` | Built |
| PO-03 | Confirmations & Changes | `/pic/purchase-orders/changes` | Built (this release) |
| PO-04 | Expediting Cockpit | `/pic/purchase-orders/expediting` | Built (this release) |
| RCV-01 | Inbound & ASN Monitor | `/pic/receiving` | Built |
| RCV-02 | Goods Receipt | `/pic/receiving/[ref]` | Built |
| RCV-03 | Service Entry Sheet | `/pic/receiving` | Built |
| RCV-04 | Returns & Quality Results | `/pic/receiving` | Built |
| INV-01 | Invoice Inbox | `/pic/invoices` | Built |
| INV-02 | Match & Exception Resolver | `/pic/invoices/[id]` | Built |
| INV-03 | Posting & Reconciliation | `/pic/invoices/reconciliation` | Built (this release) |
| INV-04 | Payables Insights | `/pic/invoices/insights` | Built (this release) |
| SAV-01 | Savings Register | `/pic/savings` | Built (+ new initiatives) |
| SAV-02 | Realisation Waterfall | `/pic/savings` | Built |
| AIX-01 | Procurement Command Centre | `/pic` | Built |
| AIX-02 | Copilot | `/pic/copilot` | Built (deterministic; LLM gateway open) |
| AIX-03 | Agent Console | `/pic/agents` | Built (autonomy, runs, recommendations this release) |
| ADM-01 | Organisation & Tenant Setup | `/pic/admin` | Built (this release) |
| ADM-02 | Rules & Thresholds | `/pic/admin` | Built |
| ADM-03 | Workflow & Approval Designer | `/pic/processes` | Partial (monitor and approval matrix; no designer/simulation) |
| ADM-04 | Roles & SoD | `/pic/admin` | Built (role editor this release) |
| ADM-05 | Integration Monitor | `/pic/admin` | Built |
| ADM-06 | Audit Explorer | `/pic/admin` | Built |

The blueprint's appendix lists 57 IDs; its count of 58 includes the external supplier portal. 54 are built and 4 are partial (MDM-04, SLM-05 as a separate app, AIX-02 without the LLM, ADM-03).

## 5. AI agents (14 + Copilot)

| Agent | Default | Status |
|---|---|---|
| Demand Sensing | L1 | Built (this release): bias over three periods above 15% leads to an override proposal |
| MRP Exception | L2 | Built |
| Guided Buying | L2 | Partial: rules-based search, no agent run log |
| Material Dedup | L2 | Built |
| Spend Classification | L3 | Built (this release): applies results at confidence ≥ 0.80 and sends the rest to the steward queue |
| Sourcing Strategy | L1 | Built (this release) |
| Bid Analysis | L2 | Built |
| Contract Review | L2 | Built (playbook rules; LLM redline open) |
| PO Validation | L3 | Built |
| Touchless PO | L4 | Built |
| Expediting | L2 | Built (+ cockpit drafts this release) |
| Invoice Exception | L2 | Built |
| Supplier Risk | L1 | Built (this release) |
| Savings Validation | L3 | Built |
| Copilot | L1 | Built (answer contract; numbers from SQL) |

Every agent runs under its role's scopes, is checked by the autonomy guard (level, value, category, kill switch, acceptance rate) and logs each run. The models are explainable rules and statistics. No ML model has been trained on tenant data yet (§6).

## 6. Still open, and why

| # | Item | Spec reference | Why it is open | What unblocks it |
|---|---|---|---|---|
| 1 | SSO (SAML/OIDC) and MFA enforcement | TD §14 | Needs your identity provider; local login with bcrypt and an `mfa_enrolled` flag today | IdP tenant, client ID/secret, MFA policy |
| 2 | Real ERP connectors (SAP S/4HANA OData/IDoc, Oracle, Dynamics, Tally, Odoo) | TD §12.1 | A SAP S/4 simulator posts with the real idempotency and reconciliation logic | Sandbox URLs and technical users per ERP |
| 3 | Punch-out (cXML/OCI), EDI gateway, GST IRP e-invoice validation, e-way bill | TD §12.3 | External networks and credentials | Punch-out supplier endpoints, EDI VAN/AS2 details, IRP/GSP credentials |
| 4 | E-signature provider | BP CLM | Internal signature with a document hash | Provider choice and API key |
| 5 | Licensed risk feeds (sanctions, financial, news) | TD §12.3 | Adapter `POST /v1/suppliers/{code}/risk-signals` is ready; screening uses a SAMPLE-LIST | Feed contracts and API keys |
| 6 | LLM gateway (LiteLLM), pgvector retrieval, LLM redlines | TD §13 | Copilot answers deterministically from SQL; `PIC_LLM_GATEWAY_URL` is the switch | Gateway URL and key, approved model list |
| 7 | Trained ML models, MLflow, feature store, AI evaluation sets | TD §13.1, §17 | Needs tenant history and labelled sets; heuristics stand in | 24–36 months of real data, labelling time from stewards |
| 8 | Industry demo tenants (construction WBS/retention/measurement SES, IT T&M, logistics freight audit, healthcare lot/expiry/consignment, general punch-out) | BP §23, Phase 4 | Template packs and rule overrides are built; the industry-specific mechanics and demo cases are Phase 4 (Aug–Sep 2027) | Confirm which industry goes first |
| 9 | Production infrastructure: Kafka + schema registry, ClickHouse, OpenSearch, GCP/Terraform, OpenTelemetry/Grafana, blue/green, DR (RPO 15 min / RTO 4 h) | TD §2, §15 | Runs as outbox relay + Postgres on Neon (decisions in Delivery Plan §3) | Hosting decision and cloud account |
| 10 | Non-functional verification: k6 load (P95 < 400 ms, 50 M-line cube), ZAP/DAST, WCAG 2.1 AA audit | TD §15, §17 | Needs a production-like environment | Environment from item 9 |
| 11 | BPMN designer and simulation (bpmn-js), separate supplier-portal app, GraphQL read models, notifications | TD §16 | Front-end scope after MVP | Agreement on priority |
| 12 | MDM-04 tax-ID and address changes; clarification board; reverse-auction live UI | BP M03, M05 | Smaller functional gaps | None (can be built next) |
| 13 | Test workbook E2E mapping | TD §17 (AHG/PRC/PIC/2026-10/03) | The workbook was not provided | The workbook file |

## 7. Technology deviations from the Technical Document

These were taken deliberately in the Delivery Plan and still stand.

| Spec | Implemented | Reason |
|---|---|---|
| NestJS services | FastAPI modular monolith, one package per bounded context | DD-01: existing Python codebase and team |
| Camunda 8 | Postgres-native workflow engine with versioned process definitions, human tasks, SLAs and timers | No Camunda cluster; process keys `pic.*` are kept so a later move is mechanical |
| Kafka | Transactional outbox and an idempotent relay worker | Same exactly-once semantics; a Kafka publisher can be added to `outbox._publish_external` |
| ClickHouse spend cube | Postgres queries over `spend_line` | Sufficient for current volumes (2,588 lines) |
| GraphQL read models | REST read endpoints | Simpler for the BFF |

## 8. Data delivered

The data is the same in the local rehearsal and on Neon. `neon_setup` loads it, and reloading is safe.

| Tenant | New datasets in this release |
|---|---|
| AXN Axion (demo, manufacturing) | ERP initial load at go-live: 20 vendor masters and 2,568 posted spend lines from Oct 2024 to Sep 2026, calibrated to blueprint AIX-01 (≈ 412 Cr, contracted ≈ 71%, maverick ≈ 6%). 25 taxonomy nodes and 9 maverick rules with 433 hits. 48 classification reviews (44 decided, 4 open for Aug–Sep 2026). 15 category plans (ALU-DIECAST approved as strategic). ERP consumption feed and forecasts for DC-330, DC-331 and FK-M8-50, with a Demand Sensing recommendation accepted and released to MRP. Risk signals and recommendations; CAPA-301 (Trichy Forge response). Case 8 change request PCR-501, which takes PO-77417 to v3. Expediting follow-up; reconciliation REC-101 with 0 differences; SV-0413 fastener initiative; SA-5522 value contract; five currencies |
| GMC, DBY (migrated from Docker) | The legacy spend lines go through the Spend Classification Agent. Their text is too thin for automatic classification, so all 15 lines (GMC 2, DBY 13) wait in the steward queue. Category plans follow once stewards have classified them. Maverick hits (GMC 3, DBY 10) are opened from the legacy control findings, risk signals are raised for compliance-flagged suppliers (GMC 3, DBY 1), and recommendations are made |

These datasets have no rows: `fx_rate` (no FX rates are seeded; you provide them, §9), `reconciliation_item` (no differences were found) and `idempotency_record` (filled at runtime).

## 9. What you need to supply or decide

1. **Neon connection string** in `backend/.env` (`DATABASE_URL`). Then run `python -m app.pic.tools.neon_setup`. On a database that already has tenants, it runs `ensure_extensions` instead of re-seeding.
2. **FX rates and the legacy currency.** Add rates in ADM-01, or tell me the treasury source. If the legacy amounts are USD, give the cutover rate for `--fx-rate`.
3. **Identity provider** for SSO/MFA (item 1 in §6).
4. **ERP sandbox access**, at least SAP S/4HANA, plus Tally or another ERP if it is in scope.
5. **E-invoice (IRP/GSP), e-sign and EDI/punch-out credentials.**
6. **LLM gateway URL and key**, and the approved models.
7. **Risk-feed providers** (sanctions, financial, news).
8. **Hosting decision** (GCP per the Technical Document, or another cloud) for the production infrastructure and NFR tests.
9. **The test workbook** AHG/PRC/PIC/2026-10/03, so that E2E cases can be mapped one to one.
10. **Which industry pack to build first** for Phase 4.
11. **Business decisions on the migrated data**, as before: overpayment recovery, purging test data and supplier bank details.
