# PIC Compliance with the Technical Document and Blueprint

AlphaHelion Procurement Intelligence Cloud, 29 Oct 2026, code at commit `5a63ed3`. This is the summary; every requirement
with its evidence is in [PIC_Spec_Traceability_Matrix.md](PIC_Spec_Traceability_Matrix.md) (490 rows).

## Contents

1. [Answer in one paragraph](#1-answer-in-one-paragraph)
2. [Status counts](#2-status-counts)
3. [What is complete](#3-what-is-complete)
4. [What is partly done or missing](#4-what-is-partly-done-or-missing)
5. [Datasets D1–D11](#5-datasets-d1d11)
6. [What you need to supply or decide](#6-what-you-need-to-supply-or-decide)
7. [Work we can do without you](#7-work-we-can-do-without-you)
8. [How this was checked](#8-how-this-was-checked)

## 1. Answer in one paragraph

**Not everything is complete, but the business processes are.** Built and tested:

- every Blueprint workflow F1–F9 (84 steps; all 13 decision points tested both ways);
- the state machines, approval and tolerance tables (DMN), and segregation-of-duties rules;
- all purchase types and the five industry demo companies;
- 13 of 14 AI agents;
- the Axion signature case.

**What remains:**

- **Platform choices** where the Technical Document named Camunda, Kafka, ClickHouse, an LLM gateway and GraphQL, and the
  product uses simpler equivalents nobody has signed off yet.
- **Non-functional targets** that are not yet measured or not met: API latency, spend cube, MRP at 50,000 materials,
  10,000 users, accessibility.
- **API and access conventions** applied only in part: idempotency keys, concurrency checks, attribute-based limits on commands.
- **Real external systems.** Today the ERP is a simulator and the other integrations wait for credentials.
- **Migration loaders** for your real ERP data.

## 2. Status counts

| Document | Done | Partly done | Not done | Needs you (external) | Total |
|---|---:|---:|---:|---:|---:|
| Technical Document | 82 (46%) | 68 (38%) | 17 (10%) | 10 (6%) | 177 |
| Blueprint (incl. 11 project design decisions) | 199 (66%) | 83 (28%) | 12 (4%) | 7 (2%) | 301 |
| Datasets D1–D11 | 9 | 2 | 0 | 1 | 12 |
| **All** | **290** | **153** | **29** | **18** | **490** |

The Blueprint describes the business, and two thirds of it is done. The Technical Document describes the platform and the
quality targets, and that is where most of the "partly done" rows are.

## 3. What is complete

| Area | Evidence |
|---|---|
| Workflows F1–F9 | All 84 steps executed in the full data build; 13 of 13 gateways taken both ways; 389 backend tests |
| State machines and guards (TD §6) | Requisition, PO, receipt, inspection, SES, invoice, contract, sourcing, supplier, material request |
| DMN-01/02/03 and PO risk (TD §7) | Effective-dated, scoped rule sets plus an approval simulator |
| Purchase types (BP §22) | Stock, expense, service, capital asset, consignment, subcontracting, catalogue/punch-out |
| Industry packs (BP §23) | Construction, IT services, logistics, healthcare, general enterprise: one demo company each |
| Segregation of duties (BP §4.1) | SOD-01 to SOD-07 checked when the action is taken (agents excepted, §4) |
| Audit and multi-tenancy | Hash-chained audit verified per company; row-level security forced on 112 of 115 tables |
| Operations modules | Amendments, auctions, EDI, e-way bills, 4-way match, ERS, retention, freight audit, payment files, reconciliation, supplier master changes, invitations, punch-out, notifications, MFA, OIDC |
| Security hardening | Rate and body limits, security headers, session revocation, MFA lockout, privacy export/erasure, CI security scans |
| Code-vs-workflow review | 89 findings fixed with tests ([PIC_Code_Review_Report.md](PIC_Code_Review_Report.md)) |

## 4. What is partly done or missing

### 4.1 Platform choices (decision needed: DEC-1)

| Technical Document says | Built instead | Effect |
|---|---|---|
| NestJS microservices | FastAPI modular monolith | Simpler to run; services can be split later |
| Camunda 8 workflow engine | Own workflow engine in Postgres | All flows work; no BPMN modeller or viewer |
| Kafka/Avro event bus | Postgres outbox in the same process | Exactly-once and retries work; no external consumers |
| ClickHouse spend cube | Postgres | Fine at demo size; untested at 50 M lines |
| LiteLLM gateway | Rule-based Copilot and contract review | Answers follow the answer contract; no generative AI |
| GraphQL, a separate supplier-portal app | REST only; the portal is part of the same app | Same functions |

### 4.2 Non-functional requirements (TD §15)

| Requirement | Target | Now |
|---|---|---|
| API latency | P95 < 400 ms | Not measured (k6 scripts ready; needs staging) |
| Spend cube | < 3 s on 50 M lines | Not measured; the overview screen loads every line into memory |
| MRP | 50,000 materials < 10 min | **681 s** best run (was about 8–9 h) |
| Scale | 10,000 users, 5 M invoices a year | Not measured |
| Accessibility | WCAG 2.1 AA | Not audited |
| Audit retention | 10 years | Default 8 years, configurable; no archive or purge job |
| Recovery | RPO 15 min / RTO 4 h | Runbook written; needs the Neon plan and a DR drill |
| Data residency | India by default | Neon Singapore (accepted for demo data) |

### 4.3 Conventions and controls

- **Idempotency keys:** used on 26 of 138 POST routes, with no 24-hour expiry. Only purchase orders check `If-Match`.
- **Attribute-based access:** enforced on approvals only. The checks for company code, plant and value band exist but no
  command calls them yet.
- **Segregation of duties:** there is no mitigating-approval path, and the agent guard does not check SoD rules.
- **Scheduled jobs missing:** nightly reconciliation, payment-due reminders, monthly scorecards, retention and
  idempotency-record purges, scheduled MRP.
- **KPIs:** about 29 of 55 module KPIs are not yet computed, and no industry-template KPI is computed.
- **Front-end:**
  - **Missing screens and features:** savings pipeline (SPD-08), lifecycle strip, generic Approvals/Documents tabs, a BPMN
    process viewer, saved views, bulk actions.
  - **Bug:** the header always says "Manufacturing template".
- **Industry and purchase-type controls that exist only as flags or comments:**
  - Healthcare: clinical sign-off on awards.
  - Construction: advance recovery and bank guarantees.
  - Logistics: detention and demurrage.
  - Purchase types: ERS for scheduling agreements, Kanban/reorder-point planning, P-card.
  - Checks: the "last price + 5%" PO check, and risk constraints in award optimisation.
- **Organisation model:** no legal-entity or purchasing-org masters (hard-coded `1000` / `INR`). FX rates are stored but
  not yet used to convert amounts.
- **Tests:** no Playwright end-to-end tests, coverage gate, event contract tests or accessibility checks.

## 5. Datasets D1–D11

| # | Dataset | Status |
|---|---|---|
| D1 | Branch cases 9–34 (every gateway both ways) | Done |
| D1b | Operations module cases | Done |
| D2 | Purchase types | Done |
| D3–D7 | Construction, IT services, logistics, healthcare, general enterprise | Done |
| D8 | Volume for NFRs | **Partly done.** Generator ready; only the 50,000-material MRP run was done (missed the target). 5 M invoices and 50 M spend lines never generated (needs staging) |
| D9 | AI evaluation sets | Done. Two proposed gates fail: auto-apply precision 0.857 (target 0.95) and duplicate precision 0.83 (target 0.90). The targets need your sign-off |
| D10 | Your real ERP masters and history | **Needs your ERP extract.** AXN history is generated; GMC/DBY came from the old prototype |
| D11 | Reference data | **Partly done.** FX is one day only; no holiday calendar for the GMC/DBY plants; some 2027 state holidays not yet published |

## 6. What you need to supply or decide

### 6.1 Decisions

| # | Decision |
|---|---|
| DEC-1 | Accept or reject the platform choices in §4.1 |
| DEC-2 | Hosting and data residency: Vercel (Pro or Hobby) plus Neon Singapore, or GCP Mumbai |
| DEC-3 | Neon plan: point-in-time recovery ≥ 7 days, exports, DR region |
| DEC-4 | Identity: your company login via OIDC, whether SAML is needed, switching MFA on (off in all companies today) |
| DEC-5 | LLM gateway (URL, key, models), or accept the rule-based Copilot |
| DEC-6 | Rule values: touchless band (default ₹25 L), approval band edges at exactly ₹2 L / ₹10 L, PO price-deviation rule, escalation (add manager or reassign), AI gate targets |
| DEC-7 | Legal: retention per data category (10-year audit or 8), lawful-basis wording |
| DEC-8 | Tax team: transport SAC 996791, implant GST rate, ERS self-billing under GST, job-work SAC 9988 |
| DEC-9 | Scope: multi-item sourcing events; which industry and purchase types the pilot uses first |
| DEC-10 | Make the ZAP security scan blocking after triage |

### 6.2 Systems and credentials

| # | Supply |
|---|---|
| SUP-1 | **SAP S/4HANA sandbox** (or your pilot ERP): the biggest blocker, because only a simulator exists today |
| SUP-2 | GST IRP/GSP credentials |
| SUP-3 | E-signature provider |
| SUP-4 | Bank host-to-host / SFTP and the real paying account |
| SUP-5 | EDI gateway and supplier EDI IDs; punch-out supplier accounts |
| SUP-6 | Sanctions feed licence (and risk/news feeds if wanted) |
| SUP-7 | Supplier Capability Digital Twin API |
| SUP-8 | SMTP for e-mails |
| SUP-9 | OCR engine for invoice capture |
| SUP-10 | Hosting access (Vercel team/token or GCP project), GitHub secrets, a rotated Neon password |
| SUP-11 | Tracing collector / log sink |
| SUP-12 | A production-sized staging environment for the performance tests |

### 6.3 Data and documents

| # | Supply |
|---|---|
| DAT-1 | **ERP extract**: 24–36 months of PO and invoice history, vendors with bank and tax IDs, materials, open contracts, open POs, open AP, GL totals |
| DAT-2 | FX history and the currency of the legacy amounts |
| DAT-3 | 2027 holiday lists, holidays for the GMC/DBY plants, real IFSC codes, a fuel-index feed, your spend taxonomy or licensed UNSPSC |
| DAT-4 | The Test-Case Workbook AHG/PRC/PIC/2026-10/03 |
| DAT-5 | FY 2027-28 budgets; NPPA ceiling prices for implants |

### 6.4 Pending right now

- **Neon rebuild (option A):** prepared and rehearsed, but blocked by the permission check. Either run the command
  yourself, or approve it.
- **Neon password:** rotate it.

## 7. Work we can do without you

Size: S ≤ 1 day, M 2–5 days, L 1–3 weeks.

| Rank | Work | Size |
|---:|---|---|
| 1 | Idempotency keys on all POST routes (with 24 h expiry); `If-Match` on every editable document | M |
| 2 | Attribute-based limits on commands (company code, plant, value band); SoD mitigating approval; SoD inside the agent guard | M |
| 3 | MRP under 10 minutes at 50,000 materials; weekly planning buckets | M |
| 4 | Spend cube at scale: SQL aggregates, materialised views, filters and measures; run at 50 M lines | M–L |
| 5 | Scheduled jobs: reconciliation, payment due, scorecards, purges, scheduled MRP | S–M |
| 6 | Test layers: Playwright end-to-end, coverage gate, event contract tests, accessibility checks | M–L |
| 7 | The ~29 missing KPIs and the industry KPIs | M |
| 8 | Front-end gaps, and the "Manufacturing template" header fix (S) | M |
| 9 | Industry and purchase-type controls that are only flags today | M–L |
| 10 | Organisation masters (legal entity, purchasing org), configurable mandatory fields, FX conversion | M–L |
| 11 | Migration loaders for contracts, open POs and open AP, ready for your ERP extract | M |
| 12 | Remaining event consumers; a published event schema | S–M |
| 13 | Encryption key versioning and re-encryption; breached-password check; threat model | M |
| 14 | Data fixes: signature-case realised savings and first-pass match; holidays for the GMC/DBY plants | S |

Together that is about 6–10 weeks for one engineer. Running in parallel, as in this phase, it is about 2–3 weeks.

## 8. How this was checked

- **Reviewer:** an independent read-only reviewer read both specs in full: Technical Document §1–§19 and Blueprint §2–§28
  with Tables 24–28.
- **Each requirement** was checked against the code, the migrations, the tests and a fresh full data build (8 companies,
  every dataset pack). The project's own status documents were used only as pointers.
- **Spot checks:** four claims were re-checked independently before this report, and all four were confirmed:
  - idempotency on 26 of 138 POST routes;
  - the attribute checks are never called;
  - the header hard-codes "Manufacturing template";
  - MFA is off in all 8 companies.
