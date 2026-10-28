# PIC Delivery Plan

**AlphaHelion Global LLP · Implementation plan · AHG/PRC/PIC/2026-10/05**

How we take the existing supplier-capability-twin codebase to an enterprise-grade AlphaHelion Purchasing Intelligence Cloud, sprint by sprint, against the Product Blueprint and the Development Technical Document.

| | |
|---|---|
| Version | 1.0 · 26 October 2026 |
| Builds on | AHG/PRC/PIC/2026-10/01 Product Blueprint · AHG/PRC/PIC/2026-10/02 Development Technical Document |
| Verified by | AHG/PRC/PIC/2026-10/03 Test-Case Workbook |
| Codebase | `backend/` (FastAPI) · `frontend/` (Next.js 16) |

## Contents

1. [Summary](#1-summary)
2. [Starting point](#2-starting-point)
3. [Delivery decisions](#3-delivery-decisions)
4. [Target code structure](#4-target-code-structure)
5. [Team and ownership](#5-team-and-ownership)
6. [Timeline](#6-timeline)
7. [Sprint plan](#7-sprint-plan)
8. [Module specifications](#8-module-specifications)
9. [Principle traceability](#9-principle-traceability)
10. [SoD implementation](#10-sod-implementation)
11. [Security and privacy](#11-security-and-privacy)
12. [NFRs and operations](#12-nfrs-and-operations)
13. [CI/CD and environments](#13-cicd-and-environments)
14. [Testing and release gates](#14-testing-and-release-gates)
15. [Data migration and cutover](#15-data-migration-and-cutover)
16. [Existing code disposition](#16-existing-code-disposition)
17. [Risks](#17-risks)
18. [Definition of done](#18-definition-of-done)
19. [First ten working days](#19-first-ten-working-days)

---

## 1. Summary

The current codebase covers most of the blueprint's 58 screens and 9 flows as a working demo. Only a thin core (PO, RFQ, invoice, payment, inventory, tenant) is stored in the database; the rest lives in process memory. There is no working authentication, no tenant isolation, no guarded state machines and no automated test suite. The business logic for the rules engine, SoD, lineage and the P2P flow is correct and will be carried forward.

This plan keeps the existing stack (FastAPI backend, Next.js frontend), adds the platform foundation the Technical Document requires, then rebuilds each module on that foundation in the order the blueprint's roadmap sets. Two phases are added to the blueprint's roadmap: a stabilisation sprint at the start and a hardening phase before general availability.

| Key figure | Value |
|---|---|
| Sprints | 26 two-week sprints, S0–S25 |
| MVP procure-to-pay gate | 12 March 2027 (end of S9) |
| General availability | 22 October 2027 (end of S25) |
| Team | 27 engineers across six squads, plus shared roles |

### MVP definition of success (blueprint §28)

- Touchless PO at least 30% for catalogue and contract lines in the pilot plant.
- First-pass invoice match at least 80%.
- Zero duplicate ERP postings across 10,000 invoices in UAT.
- Every PO line traceable to its origin in one click.

> **Team size.** Dates assume the six squads listed in the Technical Document (§18). With a team of about 8 engineers the order of work stays the same and the duration roughly doubles. Phase 0 cannot be shortened in either case.

---

## 2. Starting point

Findings from the codebase audit on 26 October 2026, each verified against the source.

| Area | Current state | Required by Technical Document |
|---|---|---|
| Persistence | PR, sourcing, contracts, savings, MRP, MDM, approvals, SoD, outbox and lineage held in module-level dicts; lost on restart | PostgreSQL 16, module-owned tables |
| ORM setup | Three separate SQLAlchemy `Base` objects; Alembic sees one; `suppliers*` tables never migrated; app DB port/name differ from docker-compose | One metadata, one engine, all tables migrated |
| Money | 29 `Float` columns, no currency | Integer minor units + ISO currency + FX rate and date |
| Authentication | `get_current_user` unused by any endpoint; `User` has no `hashed_password` column so register/login fail; login backdoor; frontend role guessed from email | SSO via OIDC/SAML, MFA for approvers, finance, admins |
| Tenancy | `tenant_id` from query string; many unscoped queries | RLS on every table; tenant from token only |
| State machines | Any PO status can be set directly; invoices can be paid twice; 3-way match creates its own goods receipt | Explicit transitions, guards, 409 on illegal transition |
| Rules | DMN-01/02/03 and PO risk score correct but hardcoded | Effective-dated rule sets; `rule_set_version` stored on documents |
| Events | Outbox is an in-memory dict with fake ERP numbers | Transactional outbox, Kafka, schema registry, idempotent consumers |
| AI | Keyword matching with canned answers | LiteLLM gateway, answer contract, autonomy guard, run log |
| Tests | Ad-hoc scripts against a live server; no frontend tests | Pytest/Jest 85% on domain logic, Pact, Testcontainers, Playwright, k6 |
| Frontend | 120 pages, about 30 fully hardcoded; `localhost:8080` in 24 files; three API calling styles; no guards, error pages, form validation or aria attributes | Typed API, object-page pattern, WCAG 2.1 AA, separate supplier portal |

---

## 3. Delivery decisions

These adapt the Technical Document's architecture decisions (AD-01 to AD-07) to the existing codebase. Each needs sign-off from the solution architect in Sprint 0 and is recorded as an ADR in `docs/adr/`.

| # | Decision | Reason | Consequence |
|---|---|---|---|
| DD-01 | Python FastAPI modular monolith instead of NestJS services | Keeps about 23k lines of working logic; the document already specifies FastAPI for ML services | One deployable with strict module boundaries (no cross-module table access, enforced by import-linter). Modules can be split into services later without data changes. |
| DD-02 | PostgreSQL 16 with RLS, SQLAlchemy 2.0, Alembic (AD-02) | As specified | App connects as a non-owner role; `SET LOCAL app.tenant_id` per transaction; RLS suite in CI |
| DD-03 | Transactional outbox to a Kafka-compatible broker (AD-03) | As specified | Redpanda locally and in dev; managed Kafka (Confluent or GCP Managed Kafka) in staging/prod; Avro schemas in a schema registry |
| DD-04 | Camunda 8 for approvals and F1–F9 (AD-01) | Business-readable, versioned processes | Python job workers via `pyzeebe`. Confirm Camunda 8 Self-Managed production licensing in Sprint 0; fallback is SaaS. |
| DD-05 | Keycloak as identity broker | Self-hostable OIDC/SAML with MFA, federates customer IdPs | Realm per environment; tenant and ABAC attributes issued as token claims |
| DD-06 | Spend cube: Postgres materialised views in MVP, ClickHouse from Phase 2 (AD-04) | MVP volumes don't need ClickHouse; avoids early ops cost | CDC with Debezium into ClickHouse from S14 |
| DD-07 | LLM access only through the LiteLLM gateway (AD-06) | As specified | `litellm` is already a dependency; PII redaction and logging at the gateway |
| DD-08 | Effective-dated rule sets in Postgres, evaluated in Python (AD-07) | Existing `rules_engine.py` logic stays; thresholds move to data | Camunda DMN used only where a decision gates a BPMN gateway |
| DD-09 | Supplier portal as a second Next.js app in a monorepo | Technical Document §16 | Built from S13; until then the existing `/supplier/*` routes stay, behind supplier scopes |
| DD-10 | Digital-twin features kept as a separate bounded context | Evidence, scoring, development, DFSC and ESG belong to the Supplier Capability Digital Twin, which PIC reads from (§12.3) | The `twin` module exposes capability, evidence level, free capacity and trust score; PIC writes back OTIF, PPM and invoice accuracy |
| DD-11 | GCP asia-south1 (Mumbai) primary, asia-south2 (Delhi) DR; Terraform | India residency default | GKE, Cloud SQL for PostgreSQL (or AlloyDB), Secret Manager, Cloud KMS, Cloud Armor |

---

## 4. Target code structure

A monorepo with one backend package per module. Each module owns its models, state machines, commands, queries and event handlers; other modules reach it only through its public service interface or its events.

```text
pic/
├─ backend/
│  ├─ app/
│  │  ├─ core/            config.py · logging.py · telemetry.py
│  │  ├─ db/              base.py (Base, TenantScoped, Money, UUIDv7) · session.py (RLS) · types.py
│  │  ├─ platform/        auth · rbac_abac · sod · rules · audit (hash chain) · outbox · idempotency
│  │  │                   errors (problem+json) · numbering · workflow (pyzeebe) · lineage · org
│  │  ├─ modules/
│  │  │  ├─ spend/        M01    ├─ sourcing/  M05    ├─ order/      M08    ├─ savings/  M11
│  │  │  ├─ planning/     M02    ├─ supplier/  M06    ├─ receiving/  M09    ├─ ai/       M12
│  │  │  ├─ mdm/          M03    ├─ contract/  M07    ├─ payables/   M10    └─ admin/    M13
│  │  │  └─ requisition/  M04
│  │  │     each: models.py · states.py · commands.py · queries.py · api.py · events.py · rules.py
│  │  ├─ integration/     connectors/{sap_s4,tally,oracle,d365,odoo} · edi · einvoice_gst · punchout
│  │  ├─ twin/            supplier capability twin context (existing evidence/scoring/profile code)
│  │  └─ main.py
│  ├─ workers/            outbox_relay · connector_worker · zeebe_workers · scheduler · mrp_worker
│  ├─ migrations/         Alembic (single history)
│  └─ tests/              unit · api · integration (Testcontainers) · rls · sod · contract (Pact)
├─ apps/
│  ├─ web/                buyer workspace (current frontend, refactored)
│  └─ supplier-portal/    from S13
├─ packages/
│  ├─ ui/                 design system: ObjectPage, DataTable, StatusChip, LifecycleStrip, ExplainPanel
│  └─ api-client/         generated from OpenAPI (openapi-typescript + openapi-fetch)
├─ processes/             BPMN/DMN models pic.mrp-to-pr … pic.material-request
├─ schemas/               Avro event schemas
├─ infra/                 terraform/ · helm/ · docker-compose.dev.yml
└─ e2e/                   Playwright suites E2E-01…, k6 scripts
```

---

## 5. Team and ownership

| Squad | Composition | Owns |
|---|---|---|
| Platform | 1 lead, 3 backend, 1 DevOps/SRE | Tenancy and RLS, identity, RBAC/ABAC, SoD, rules, workflow, audit, outbox, CI/CD, observability, infra |
| Plan & Request | 1 lead, 3 full-stack, 1 QA | requisition, mdm, planning (MRP), catalogue and punch-out |
| Source & Contract | 1 lead, 3 full-stack, 1 QA | sourcing, contract, supplier (SLM) and twin link, savings, supplier portal |
| Order to Pay | 1 lead, 3 full-stack, 1 QA | order, receiving, payables |
| Integration | 1 lead, 2 integration engineers | ERP connectors, EDI, GST e-invoice, reconciliation, data migration |
| Intelligence | 1 lead, 2 ML engineers, 1 data engineer | Spend cube, models, agent runtime, Copilot, MLflow, evaluation |
| Shared roles | Product owner, solution architect, UX designer, security engineer, delivery manager | Backlog, ADRs, design system and screen fidelity, threat models and pen-test liaison, release plan |

---

## 6. Timeline

### Sprint calendar

Each sprint is two weeks, Monday to Friday of the following week.

| Sprint | Dates | Phase |
|---|---|---|
| S0 | 26 Oct – 6 Nov 2026 | 0 · Stabilise & foundation |
| S1 | 9 – 20 Nov 2026 | 0 |
| S2 | 23 Nov – 4 Dec 2026 | 0 |
| S3 | 7 – 18 Dec 2026 | 0 · **Foundation gate** |
| S4 | 21 Dec 2026 – 1 Jan 2027 | 1 · MVP procure-to-pay |
| S5 | 4 – 15 Jan 2027 | 1 |
| S6 | 18 – 29 Jan 2027 | 1 |
| S7 | 1 – 12 Feb 2027 | 1 |
| S8 | 15 – 26 Feb 2027 | 1 |
| S9 | 1 – 12 Mar 2027 | 1 · **MVP gate** |
| S10 | 15 – 26 Mar 2027 | 2 · Source & contract |
| S11 | 29 Mar – 9 Apr 2027 | 2 |
| S12 | 12 – 23 Apr 2027 | 2 |
| S13 | 26 Apr – 7 May 2027 | 2 |
| S14 | 10 – 21 May 2027 | 2 · **Source & contract gate** |
| S15 | 24 May – 4 Jun 2027 | 3 · Plan & predict |
| S16 | 7 – 18 Jun 2027 | 3 |
| S17 | 21 Jun – 2 Jul 2027 | 3 |
| S18 | 5 – 16 Jul 2027 | 3 |
| S19 | 19 – 30 Jul 2027 | 3 · **Plan & predict gate** |
| S20 | 2 – 13 Aug 2027 | 4 · Industry packs |
| S21 | 16 – 27 Aug 2027 | 4 |
| S22 | 30 Aug – 10 Sep 2027 | 4 |
| S23 | 13 – 24 Sep 2027 | 4 · **Industry packs gate** |
| S24 | 27 Sep – 8 Oct 2027 | 5 · Hardening & GA |
| S25 | 11 – 22 Oct 2027 | 5 · **General availability** |

### Squad focus by phase

| Squad | Phase 0 (S0–S3) | Phase 1 (S4–S9) | Phase 2 (S10–S14) | Phase 3 (S15–S19) | Phase 4 (S20–S23) | Phase 5 (S24–S25) |
|---|---|---|---|---|---|---|
| Platform | **Foundation** | Platform services, SRE, security | Platform services | Platform services | Platform services | **Hardening** |
| Plan & Request | Design system | **REQ · MDM · catalogue** | Supplier master MDM, punch-out | **MRP** | **Industry packs** | Hardening |
| Source & Contract | Shared UI | Supplier status, SLM basics | **Sourcing · CLM · SLM · Savings** | Award optimisation, portal | **Industry packs** | Hardening |
| Order to Pay | Legacy API freeze | **PO · GR/SES · Invoice** | Contract inheritance, ERS | Touchless, expediting | **Industry packs** | Hardening |
| Integration | Connector skeleton (S1–S3) | **SAP S/4 · Tally · GST** (S6–S9) | CDC (S13–S14) | — | **Oracle · D365 · Odoo · EDI** | **Cutover** |
| Intelligence | — | Spend data platform (S9) | Spend cube | **Models · agents · Copilot** | Pack evaluations | Hardening |

Bold marks the squad's main delivery focus in that phase.

> **Holidays.** S4 covers 21 December to 1 January. Plan it at 60% capacity, or shift every later date by one week.

---

## 7. Sprint plan

Each sprint lists its deliverables and, at phase ends, the exit test that must pass before the next phase starts. Screen IDs, flow IDs and principle IDs refer to the blueprint.

### Phase 0 · Stabilise & foundation (S0–S3 · 26 Oct – 18 Dec 2026)

#### S0 · 26 Oct – 6 Nov · Stabilise the codebase

- Create the Git repository, branch protection, CODEOWNERS per module, PR template with the definition of done.
- Pin `requirements.txt`; add `python-jose`, `passlib[bcrypt]`, `pydantic-settings`, `uuid6`; remove the duplicate `sqlalchemy` line. Introduce a `uv` or `pip-tools` lock file.
- Delete dead code: `inventory.py.bak`, unregistered `app/api/*`, broken `api/routers/inventory.py`, `core/db.py`, duplicate notifications import.
- Remove the login backdoor, hardcoded DB password and JWT secret; add `core/config.py` with pydantic-settings and `.env.example`.
- Stop `GET /finance/invoices` from seeding data; guard `pay_invoice` against unmatched or already-paid invoices as an interim fix.
- Developer stack in `infra/docker-compose.dev.yml`: Postgres 16, Redpanda + schema registry, Keycloak, Camunda 8 (Zeebe, Operate, Tasklist), Redis, Mailpit, OpenTelemetry collector, Jaeger.
- Pytest harness with in-process `TestClient` and Testcontainers Postgres; port the useful `verify_*.py` scenarios.
- CI v1: ruff, mypy, pytest, eslint, `tsc --noEmit`, gitleaks, pip-audit, npm audit.
- Frontend: `NEXT_PUBLIC_API_URL` replaces the 24 hardcoded URLs; move `<Shell>` inside `<Providers>`.
- ADRs DD-01 to DD-11 signed off; Camunda licence confirmed; ERP sandbox access requested (SAP S/4HANA, Tally).

#### S1 · 9 – 20 Nov · Data foundation and tenancy

- Single `Base`; `TenantScoped` mixin (UUIDv7 id, tenant_id, created/updated at and by, `row_version` for optimistic locking); `Money` composite (minor units + currency); FX rate and date on converted amounts.
- New Alembic baseline that reconciles all existing tables, converts Float money to minor units and supplier ids to UUID, with a data-migration script for the current demo data.
- RLS helper applied to every tenant table; application DB role without `BYPASSRLS`; `tenant_session` dependency issuing `SET LOCAL app.tenant_id`.
- RLS isolation suite: for every table, tenant A cannot read, update or insert tenant B rows. Runs in CI.
- Org model (ADM-01): tenant, legal_entity, company_code, plant, storage_location, purch_org, purch_group, cost_center, wbs_element, currency, factory_calendar.
- Per-tenant number ranges (REQ-, PO-, GR-, INV-) using gap-free sequences.
- RFC 9457 `problem+json` handler with `code`, `ruleRef`, `traceId`; mappings for `StaleDataError`→412, illegal transition→409, `SodViolation`→409 `SOD_CONFLICT`.
- `Idempotency-Key` dependency for every POST (24 h replay, request-hash check); ETag/If-Match on updates.

#### S2 · 23 Nov – 4 Dec · Identity, authorisation, SoD and audit

- Keycloak realms; OIDC JWT verification (RS256, JWKS cache); `Principal` with tenant, roles, scopes and ABAC attributes (company codes, plants, categories, value limit). Tenant comes only from the token.
- Scope catalogue per module (e.g. `po:create`, `po:release`, `invoice:post`); `require(scope, abac=…)` dependency on every endpoint; an automated check fails CI if any route lacks it.
- The 14 blueprint roles seeded as Keycloak roles mapped to scopes; MFA required for approver, finance and admin roles.
- SoD engine on the database: `sod_rule` (tenant-configurable), `action_log` (who did what on which object), check at command time for humans and agents. Rule IDs re-aligned to blueprint SOD-01…07.
- Append-only `audit_event` with hash chain per tenant; INSERT-only grant; nightly chain verifier; `GET /v1/audit/{objectType}/{id}`.
- Frontend: Auth.js OIDC login, `middleware.ts` route guards by scope, generated typed API client in `packages/api-client`, 401 handling. Persona switch removed outside dev.
- ADM-04 Roles & SoD and ADM-06 Audit Explorer wired to real data.

#### S3 · 7 – 18 Dec · Rules, workflow, events, lineage, design system

- `rule_set` with scope tuple (tenant, company code, plant, category, purchase type), version and effective dates; most-specific resolver. DMN-01, DMN-02, DMN-03, PO risk score and quote policy moved from constants to rule-set data. ADM-02 editor writes new versions; documents store `rule_set_version`.
- Camunda 8 integration: `pyzeebe` worker framework, process deployment from `processes/`, human-task API backing the unified approval inbox, SLA timers and escalation.
- Transactional outbox: `outbox_event` written in the same transaction as the domain change; relay worker (`SELECT … FOR UPDATE SKIP LOCKED`) publishing to `pic.<tier>.<event>`; Avro event envelope (tenantId, eventId, occurredAt, actor, objectRef, version, traceId).
- `integration_message` with `UNIQUE(tenant, target_system, idempotency_key)`; connector worker framework with retry (exponential backoff, max 8), dead letter and replay (`POST /v1/integration/messages/{id}/replay`); SAP mock via WireMock.
- `document_link` table and lineage query; `lineage_service.py` logic moved onto it.
- OpenTelemetry traces across web, API, workers and Zeebe; structured JSON logs; `/healthz`, `/readyz`.
- Design system in `packages/ui`: ObjectPage (header, status chip, tabs Lines · Approvals · Documents · Lineage · Audit, action bar), DataTable with cursor pagination, StatusChip, LifecycleStrip, ExplainPanel, form kit (react-hook-form + zod), toasts, `error.tsx` / `loading.tsx` / `not-found.tsx`.

> **Exit test (Foundation gate).** A test document runs end to end: DMN-01 resolves the approver chain, Camunda creates the task, an approver completes it, SoD blocks a conflicting approver, the audit chain verifies, and the event reaches the broker once. RLS suite green.

### Phase 1 · MVP procure-to-pay (S4–S9 · 21 Dec 2026 – 12 Mar 2027)

#### S4 · 21 Dec – 1 Jan · Requisitions (M04)

- Tables requisition, pr_line, account_assignment, budget, budget_commitment; PR state machine (Draft → Submitted → In Approval → Approved → Partially Ordered → Ordered → Closed | Rejected | Returned | Cancelled).
- Purpose code mandatory (P01); origin stored and immutable via DB trigger (P02); free-text lines with `CHECK (item_type <> 'FREE_TEXT' OR material_id IS NULL)` (P04); purchase type per line driving the P08 matrix.
- Budget check at submit: hard stop for capex and WBS, soft stop with justification for opex; commitment on approval.
- F2 `pic.requisition` with DMN-01 approver chain and 2-business-day SLA. REQ-02 form and REQ-03 approval inbox rebuilt on the design system.

#### S5 · 4 – 15 Jan · Guided buying and material governance (M04, M03)

- REQ-01 search enforcing contract item → catalogue item → material → free text (P03); Postgres full-text and trigram search until OpenSearch lands.
- Catalogue and catalogue_item; quote policy by value band; PR change re-approval only when value, account or supplier changes. REQ-04 buyer workbench with origin filters, bundling and assign.
- MDM-01 material request with mandatory classification; duplicate score (description similarity, MPN, attributes, classification): ≥ 0.92 blocks, 0.75–0.92 warns. Promote free-text line to material request; the PR keeps its line.
- F9 `pic.material-request` with parallel steward tasks by domain; MDM-02 steward workbench; SOD-06.

#### S6 · 18 – 29 Jan · Purchase orders (M08)

- Tables purchase_order, po_line, po_schedule_line, po_version, po_confirmation, info_record, source_list; DDL as Technical Document §19.2.
- PO from PR with source determination (info record and source list now; contract and quota in S12/S15) and inheritance of PR, price, Incoterms, payment terms and tolerances (P07). Overrides require `deviation_reason`.
- PO validation: risk score with explainable factors, DMN-02 touchless check, split-PO detection (same supplier + material group + cost object within 7 days), blocked-supplier guard, SOD-01/03/04.
- F5 `pic.po`; transmission by portal and email; supplier confirmation; change after confirmation creates version n+1 and requires re-confirmation.
- PO-01 workbench and new `/purchase-orders/[id]` object page (PO-02) with Lineage and Audit tabs; PO-03 confirmations.

#### S7 · 1 – 12 Feb · Receiving and supplier master basics (M09, M03, M06)

- ASN, goods_receipt, gr_line, inspection_lot, usage_decision, return_delivery; quality stock until usage decision; over-delivery above tolerance blocked; batch/serial/expiry capture; GR reversal.
- Service entry sheets (milestone, T&M, unit-rate, progress %) approved by someone other than the supplier and the PO creator.
- Existing inventory module re-based on the new GR movements (stock remains the source for MRP on-hand).
- F6 `pic.receipt`; RCV-01 to RCV-04; supplier ASN in the portal.
- Supplier status per category (Registered → … → Blocked) enough to drive PO guards; MDM-04 bank-detail change with two finance approvers, call-back verification, cooling-off period and alert on change + invoice within 30 days (SOD-02).

#### S8 · 15 – 26 Feb · Invoices and ERP posting (M10)

- Capture by portal, PDF upload (OCR adapter) and GST e-invoice with IRN and signed QR validation.
- Duplicate control: unique (tenant, company code, supplier, supplier invoice no., fiscal year) plus fuzzy check (amount ± 1, date ± 3 days).
- Per-line match in Decimal: 3-way against accepted GR minus already invoiced, 2-way where GR not required, service invoices against approved SES; DMN-03 tolerances from the rule set; exceptions with type, delta and suggested action.
- Invoice state machine with payment block until all exceptions are resolved; credit notes; GRIR accrual.
- Posting only through the outbox with key `tenant|company_code|supplier|invoice_no`; SAP S/4HANA connector (OData, IDoc fallback) and Tally connector (XML via on-prem agent); query-before-retry on timeout; nightly reconciliation.
- F7 `pic.invoice`; INV-01, INV-02 (side-by-side PO · GR · invoice), INV-03 posting and reconciliation; ADM-05 integration monitor.

#### S9 · 1 – 12 Mar · MVP hardening and pilot readiness

- SPD-01 spend overview on Postgres materialised views; INV-04 payables insights.
- Legacy endpoints for PO, invoice and payment retired; all P2P pages on `/v1` commands.
- Playwright E2E-01 (manual PR path to posted invoice); idempotency soak of 10,000 invoices with injected timeouts and duplicates.
- k6 baseline (P95 < 400 ms on transactional APIs), ZAP DAST, RLS and SoD suites, WCAG check on P2P screens.
- Migration rehearsal 1 with pilot data (suppliers, materials, open POs); UAT with the pilot plant.

> **Exit test (MVP gate).** E2E-01 passes; zero duplicate ERP postings across 10,000 invoices; first-pass match and touchless rates measured in UAT against MVP targets; every PO line opens its lineage in one click.

### Phase 2 · Source & contract (S10–S14 · 15 Mar – 21 May 2027)

#### S10 · 15 – 26 Mar · Sourcing events (M05)

- sourcing_event, event_line, invitee, scoring_model, criterion, bid, bid_line, clarification; event types RFI, RFQ, RFP, reverse auction, multi-round, lot bidding.
- Events start only from approved requirements (PRs, MRP demand or category plan); invitees limited to suppliers Qualified for the category or Conditional with waiver (P06).
- Weights must sum to 100 and lock at publish. Bids sealed with envelope encryption (Cloud KMS per tenant); early access blocked and logged; unsealing at close writes `bids.unsealed`.
- F3 `pic.sourcing-award` close timer; SRC-01 cockpit and SRC-02 event builder (replacing the mock `/rfqs/create`); supplier bidding in the portal.

#### S11 · 29 Mar – 9 Apr · Evaluation and award

- Bid normalisation and TCO (price, freight, duty, packaging, carrying cost, quality cost, payment-term value); should-cost parametric baseline by commodity.
- Award scenarios: lowest cost, best value, split/dual, capacity-constrained MIP using OR-Tools with free capacity read from the twin.
- SRC-03 bid comparison, SRC-04 scenario studio, SRC-05 award approval with written rationale for non-lowest awards, conflict-of-interest declaration, threshold approvals; SOD-05.
- Award hands over to contract (S12) or PO.

#### S12 · 12 – 23 Apr · Contract lifecycle (M07)

- contract, contract_line, clause_library with fallback positions and risk scores, template, obligation, price_validity, consumption.
- Contract state machine; legal + finance approval above threshold; e-signature adapter (DocuSign or an Indian Aadhaar eSign provider).
- Activation publishes price validity to source determination; indexation (e.g. quarterly LME ± 3%) creates new validity periods and never overwrites.
- PO price must equal contract price within tolerance or the PO is flagged; consumption alerts at 80/90/100%; F4 with renewal timer at −120 days.
- CLM-01 workspace, CLM-02 clause review (redline agent placeholder until S18), CLM-03 consumption and compliance, CLM-04 obligation tracker.

#### S13 · 26 Apr – 7 May · Supplier lifecycle and portal (M06)

- Qualification per category with questionnaires, certificates, audits and sample approval (PPAP); certificate expiry timers move status to Conditional automatically.
- Blocking stops new POs and flags open POs for buyer decision; scorecards (OTIF, PPM, responsiveness, invoice accuracy, ESG) recompute monthly and on every GR/invoice event.
- Risk monitor with sanctions and financial-risk adapters; CAPA and development plans.
- Twin integration: read capability, evidence level, free-capacity band, trust score; write back OTIF, PPM, invoice accuracy.
- F8 `pic.supplier-onboarding`; SLM-01 Supplier 360 (replacing the mock page), SLM-02, SLM-03, SLM-04 (replacing the seven mock `/risk/*` pages); supplier portal app (SLM-05) with supplier scopes.

#### S14 · 10 – 21 May · Savings and spend cube (M11, M01)

- savings_initiative and savings_ledger; baseline methods fixed at creation; lifecycle Identified → Negotiated → Contracted → Realising → Validated | Lost.
- Realised savings only from `invoice.posted`; cost avoidance never counts towards budget; SOD-07 finance validation. SAV-01 register, SAV-02 waterfall.
- Debezium CDC into ClickHouse; spend cube dimensions and measures from blueprint §7.2; SPD-02 to SPD-06 including maverick rules with owner and disposition; OpenSearch for global search.
- Migration rehearsal 2 (open contracts, 24–36 months of spend history).

> **Exit test (Source & contract gate).** RFQ-2231 awards 60/40 at weighted 400.8, activates SA-5520, and PO-77410 inherits price 398, N60 and FCA Trichy. Savings register shows SV-0412 negotiated 0.99 Cr/yr.

### Phase 3 · Plan & predict (S15–S19 · 24 May – 30 Jul 2027)

#### S15 · 24 May – 4 Jun · MRP engine (M02)

- Planning parameters, demand elements (forecast, sales orders, reservations, WBS demand), factory calendar, quota arrangements.
- Netting, lot sizing (exact, fixed, EOQ, period, min/max, pack rounding) and lead-time scheduling as pure, property-tested functions (Technical Document §9.1).
- Run modes net-change, regenerative and simulation (results only, no documents); exceptions PAST_DUE, BELOW_SAFETY, RESCHEDULE_IN/OUT, CANCEL.
- Firm and convert to PR with source determination including contract and quota; ERP planned-order import adapter for tenants running MRP in the ERP.
- MRP-01 run console, MRP-02 planner workbench, MRP-03 exception monitor.

#### S16 · 7 – 18 Jun · MRP scale and forecasting

- Partitioned MRP workers to meet 50,000 materials in under 10 minutes; F1 `pic.mrp-to-pr`.
- Demand forecast model (gradient boosting + seasonal baseline), MLflow registry, MRP-04 forecast review with override reason.
- Spend classification model (text classifier + embeddings); below 0.80 confidence goes to the steward queue; SPD-09 spend forecast.

#### S17 · 21 Jun – 2 Jul · Agent runtime (M12)

- Agent registry (purpose, input events, tool scopes, default autonomy, value/category limits, run-as role).
- Autonomy guard before every tool call: role permission, SoD, autonomy level for tenant and category, value limit, kill switch. Denied calls become L2 drafts.
- Run log with inputs, evidence ids, model and prompt version, output, confidence, action, feedback; auto-suspend when acceptance falls below threshold or drift is detected.
- LiteLLM gateway with PII and bank-data redaction and per-tenant retention.
- First agents: Guided Buying (L2), PO Validation (L3), Invoice Exception (L2), Spend Classification (L3).

#### S18 · 5 – 16 Jul · Copilot and command centre

- AIX-02 Copilot returning the §13.3 answer contract, validated by JSON schema; tenant-scoped, permission-filtered retrieval (pgvector) before the model sees text; numbers computed by SQL and cube tools.
- AIX-01 command centre on real KPIs; AIX-03 agent console with autonomy settings and kill switches.
- Agents: Touchless PO (L4 within policy), Bid Analysis, Contract Review (redline vs playbook), Material Dedup, MRP Exception, Expediting with late-delivery model.

#### S19 · 19 – 30 Jul · Remaining agents and AI evaluation

- Demand Sensing, Sourcing Strategy, Supplier Risk, Savings Validation agents.
- Offline evaluation sets per model (classification accuracy, MAPE, answer-contract completeness) gating any autonomy increase; model cards.

> **Exit test (Plan & predict gate).** MR-1043 nets 12,000 − 1,400 − 1,200 − 600 + 200 = 9,000 and creates PLO-55821; six agents in production at L1–L3; autonomy guard tests prove no agent exceeds its role, SoD or value limit.

### Phase 4 · Industry packs (S20–S23 · 2 Aug – 24 Sep 2027)

#### S20 · 2 – 13 Aug · Template engine, manufacturing and general enterprise

- Versioned seed bundles (purchase types, number ranges, event and contract templates, approval matrix, KPIs, demo data) applied at tenant creation and editable after.
- Manufacturing: PPAP/IATF gates, quota arrangements, scheduling agreements, ERS, metal-index clauses.
- General enterprise: punch-out (cXML PunchOutSetupRequest/OrderMessage, SAP OCI), P-card limits, receipt-less below threshold.

#### S21 · 16 – 27 Aug · Construction and IT services

- Construction: WBS on every line with hard budget stop, BOQ, retention and advance recovery, variation orders as contract amendments, progress-based SES.
- IT services: MSA + SOW, rate cards, timesheet and milestone SES, licence entitlement and auto-renewal alerts.

#### S22 · 30 Aug – 10 Sep · Logistics and healthcare

- Logistics: lane tenders and spot auctions, rate contracts with fuel indexation, POD as service confirmation, freight audit against lane rates.
- Healthcare: lot/expiry/serial and cold chain at GR, consignment with usage-triggered POs, recall traceability, clinical sign-off in the award.

#### S23 · 13 – 24 Sep · Remaining connectors

- Oracle Fusion/EBS (REST/FBDI), Dynamics 365 (OData/Dataverse), Odoo (JSON-RPC); connector SDK documentation.
- EDI gateway (ORDERS, ORDCHG, ORDRSP, DESADV, INVOIC over AS2/SFTP); e-way bill on ASN.

> **Exit test (Industry packs gate).** Each industry template passes its test sheet in the workbook, including the demo case listed in blueprint Table 23.

### Phase 5 · Hardening & GA (S24–S25 · 27 Sep – 22 Oct 2027)

#### S24 · 27 Sep – 8 Oct · Production readiness

- Load test at 10,000 concurrent users per tenant and 5 M invoices/year volume; spend cube under 3 s on 50 M lines.
- DR drill against RPO 15 min / RTO 4 h; blue/green deployment rehearsal; backward-compatible migration check.
- Third-party penetration test against OWASP ASVS L2; WCAG 2.1 AA audit; DPDP privacy review; runbooks for dead-lettered postings, workflow incidents, MRP failure, model drift.
- Migration rehearsal 3 (full cutover dry-run).

#### S25 · 11 – 22 Oct · Cutover and general availability

- Pilot tenant production cutover following §15; open-invoice freeze window; reconciliation sign-off by finance.
- Two weeks hypercare with daily SLO review (PR approval latency, touchless rate, match rate, posting success).

> **Exit test (GA).** All release gates in §14 green; finance signs off reconciliation; GA announced.

---

## 8. Module specifications

What each module must contain when done. "Screens" maps each blueprint screen to the existing page it replaces; pages marked *new* do not exist yet.

### M01 · Spend & Category Intelligence
*Intelligence squad · S9, S14, S16*

| | |
|---|---|
| Tables | spend_line, taxonomy, taxonomy_node, classification_review, maverick_rule, maverick_hit, category_plan, category_budget; ClickHouse `spend_cube` (Postgres materialised view in MVP) |
| APIs | `GET /v1/spend/cube`, `GET /v1/spend/maverick`, `POST /v1/spend/maverick-hits/{id}/disposition`, `/v1/category-plans` |
| Events | Consumes invoice.posted, purchase_order.released |
| Rules | De-duplicate PO and invoice through lineage before aggregation; classification below 0.80 to steward queue; intercompany excluded from addressable; maverick rules configurable, each hit needs owner and disposition |
| Screens | SPD-01, SPD-06 ← `/spend/cube` · SPD-07 ← `/workbenches` (Kraljic) · SPD-08 ← `/savings` · SPD-02 to SPD-05, SPD-09 *new* |
| Tests | Spend total ties to GL within ±0.5%; cube query under 3 s on 50 M lines |

### M02 · Demand Planning & MRP
*Plan & Request · S15–S16*

| | |
|---|---|
| Tables | material_plan_params, demand_element, forecast, mrp_run, mrp_run_result, planned_order, mrp_exception, quota_arrangement, factory_calendar |
| States | Planned order: Created → Firmed → Converted \| Deleted (by next run if not firmed) |
| APIs | `POST /v1/mrp/runs`, `GET /v1/mrp/runs/{id}/exceptions`, `POST /v1/planned-orders/{id}/firm`, `POST /v1/planned-orders/{id}/convert` |
| Events | mrp.run.completed, planned_order.firmed |
| Rules | Only MRP-active materials planned; firmed orders never changed; simulation creates no documents; conversion inherits material, qty, date, plant, storage location, source |
| Screens | MRP-01 to MRP-03 ← `/mrp/planner-workbench` · MRP-04 *new* |
| Tests | MR-1043 = 9,000; property tests for lot sizing; 50,000 materials under 10 min |

### M03 · Material & Supplier Master Data Governance
*Plan & Request · S5, S7*

| | |
|---|---|
| Tables | material, material_request, duplicate_candidate, steward_task, supplier_master_change, bank_account (field-encrypted) |
| States | Draft → Duplicate Check → In Stewardship → Approved → Synced to ERP \| Rejected \| Merged |
| APIs | `POST /v1/materials/requests`, `POST /v1/materials/requests/{id}/decision`, `POST /v1/requisitions/{id}/lines/{n}/promote-material`, `POST /v1/suppliers/{id}/master-changes` |
| Events | material_request.approved, supplier.master.changed |
| Rules | Duplicate ≥ 0.92 blocks unless a steward overrides with reason; 0.75–0.92 warns; bank change needs two finance approvers, never the requester, plus call-back and cooling-off; ERP sync only after final approval; SOD-02, SOD-06 |
| Screens | MDM-01, MDM-02 ← `/mdm/requests`, `/mdm/studio` · MDM-04 ← bank change in `/mdm/studio` · MDM-03 *new* |
| Tests | Dedup precision/recall on labelled set; bank-change fraud scenarios from the workbook |

### M04 · Requisitioning & Guided Buying
*Plan & Request · S4–S5, S20*

| | |
|---|---|
| Tables | requisition, pr_line, account_assignment, budget, budget_commitment, catalogue, catalogue_item, punchout_session |
| States | Draft → Submitted → In Approval → Approved → Partially Ordered → Ordered → Closed \| Rejected \| Returned \| Cancelled |
| APIs | `POST /v1/requisitions`, `POST /v1/requisitions/{id}/submit`, `/approve`, `/return`, `GET /v1/guided-buying/search` |
| Events | requisition.submitted, requisition.approved |
| Rules | P01–P04, P08; DMN-01; quote policy (< ₹25,000 none; to ₹2 L one quote or catalogue; > ₹2 L three quotes or sourcing event); budget hard/soft stop; re-approval on value, account or supplier change |
| Screens | REQ-01 ← `/p2p` guided buying · REQ-03 ← `/approvals` · REQ-04 ← `/purchase-orders/pending` · REQ-02 *new form* |
| Tests | Search-order enforcement; budget stop variants; DMN-01 band edges (24,999 / 25,000 / 2,00,000 / 10,00,000) |

### M05 · Strategic Sourcing
*Source & Contract · S10–S11*

| | |
|---|---|
| Tables | sourcing_event, event_line, invitee, scoring_model, criterion, bid (ciphertext + key ref), bid_line, clarification, award_scenario, award_decision, conflict_declaration |
| States | Draft → Published → Open → Closed → Under Evaluation → Award Pending → Awarded \| Cancelled |
| APIs | `POST /v1/sourcing/events`, `/publish`, `/bids`, `/scenarios`, `/award` |
| Events | sourcing.event.published, sourcing.bid.submitted, sourcing.event.awarded |
| Rules | Only qualified invitees; sealed until close; weights sum to 100 and lock at publish; non-lowest award needs rationale; above threshold category head + finance; SOD-05 |
| Screens | SRC-01 ← `/sourcing` · SRC-02 ← `/rfqs/create` · SRC-03 ← `/rfqs/compare` · SRC-05 ← `/rfqs/awards` · SRC-04 *new* (logic from `sealed_bid_mip.py`) · supplier side ← `/supplier/rfqs` |
| Tests | RFQ-2231 scenario = 60/40 weighted 400.8; early unseal attempt blocked and audited |

### M06 · Supplier Lifecycle & Performance
*Source & Contract · S7, S13*

| | |
|---|---|
| Tables | supplier, supplier_category_status, qualification, questionnaire_response, certificate, scorecard, scorecard_period, risk_signal, capa, supplier_user |
| States | Per category: Registered → Under Qualification → Qualified \| Conditional → Preferred \| Blocked \| Exited |
| APIs | `/v1/suppliers/*`, `/v1/suppliers/{id}/qualifications`, `/scorecards`, `/risk-signals` |
| Events | supplier.status.changed; consumes goods_receipt.posted, invoice.posted |
| Rules | Only Qualified/Preferred receive POs for the category (one-time vendor policy aside); expired certificate → Conditional; block stops new POs and flags open ones |
| Screens | SLM-01 ← `/suppliers/360`, `/supplier/[id]` · SLM-02 ← `/suppliers/onboarding`, `/assessments`, `/approvals` · SLM-03 ← `/buyer/suppliers/scorecards` · SLM-04 ← `/risk/*` · SLM-05 ← `/supplier/*` (moves to portal app) |
| Tests | Certificate-expiry timer; block-with-open-PO flow; scorecard recompute on events |

### M07 · Contract Lifecycle Management
*Source & Contract · S12*

| | |
|---|---|
| Tables | contract, contract_line, clause, clause_library, playbook_position, template, obligation, price_validity, consumption, signature_envelope |
| States | Draft → In Negotiation → In Approval → Out for Signature → Active → Expiring → Expired \| Terminated \| Renewed |
| APIs | `POST /v1/contracts`, `/activate`, `GET /v1/contracts/{id}/consumption`, `/obligations` |
| Events | contract.activated, contract.consumption.threshold |
| Rules | Only executed contracts referenced by POs; PO price = contract ± tolerance; legal + finance above threshold; indexation creates new validity periods |
| Screens | CLM-01 ← `/contracts`, `/contracts/view` · CLM-02 ← `/workbenches` clause redline · CLM-03 ← `/contracts/pending-renewals` · templates ← `/contracts/templates` · CLM-04 *new* |
| Tests | SA-5520 LME reset creates new validity; consumption 80/90/100% alerts |

### M08 · Operational Purchasing
*Order to Pay · S6*

| | |
|---|---|
| Tables | purchase_order, po_line, po_schedule_line, po_version, po_confirmation, po_change_request, info_record, source_list, transmission |
| States | Draft → In Approval → Released → Transmitted → Confirmed → Partially Received → Received → Invoiced → Closed \| Cancelled; any change after confirmation → new version |
| APIs | `POST /v1/purchase-orders`, `/validate`, `/release`, `/transmit`, `/confirmations`, `/versions` |
| Events | purchase_order.released, .confirmed, .changed |
| Rules | DMN-02 touchless; additive risk score; no release to blocked supplier; split detection escalates; deviation reason when price leaves tolerance; SOD-01, SOD-03, SOD-04 |
| Screens | PO-01 ← `/purchase-orders` · PO-03 ← `/supplier/orders` + confirmations · PO-04 ← `/workbenches` expediting · PO-02 *new* `/purchase-orders/[id]` |
| Tests | PO-77410 risk 18, touchless; illegal transitions return 409; stale update returns 412 |

### M09 · Fulfilment, Goods Receipt & Service Entry
*Order to Pay · S7*

| | |
|---|---|
| Tables | asn, asn_line, goods_receipt, gr_line, inspection_lot, usage_decision, return_delivery, service_entry, ses_line; inventory stock and movements |
| States | GR: Posted → Quality Hold → Accepted \| Partially Rejected \| Rejected → Reversed. SES: Draft → Submitted → Approved \| Rejected → Revoked |
| APIs | `POST /v1/asns`, `POST /v1/goods-receipts`, `/reverse`, `POST /v1/service-entries`, `/approve` |
| Events | asn.received, goods_receipt.posted, quality.usage_decision, service_entry.approved |
| Rules | Over-delivery above tolerance blocked; quality-managed GR to quality stock; SES approver differs from supplier and PO creator; receipt-less expense only below value |
| Screens | RCV-01 ← `/supplier/shipping/asn`, `/buyer/logistics` · RCV-02 ← `/inventory/receipt` · RCV-03 ← `/workbenches` service entries · RCV-04 *new* |
| Tests | GR-90231: 5,400 received, 5,380 accepted, 20 rejected |

### M10 · Invoice Matching & Finance Integration
*Order to Pay + Integration · S8*

| | |
|---|---|
| Tables | invoice, invoice_line, tax_line, match_result, invoice_exception, credit_note, posting, payment, payment_block, grir_accrual, integration_message |
| States | Captured → Duplicate Check → Matching → Exception \| Matched → Approved → Posted → Paid \| Rejected |
| APIs | `POST /v1/invoices`, `/match`, `/exceptions/{eid}/resolve`, `/post` (Idempotency-Key), `/v1/payments` |
| Events | invoice.captured, invoice.exception.raised, invoice.posted, payment.completed |
| Rules | DMN-03; unique + fuzzy duplicate; 3-way needs GR unless ERS; services against SES; posting key tenant + company code + supplier + invoice no.; payment block until exceptions resolved |
| Screens | INV-01 ← `/invoices`, `/finance/invoices` · INV-02 ← `/invoices/3-way-match` · INV-04 ← `/finance/payments`, `/finance/dashboard` · INV-03 *new* · supplier side ← `/supplier/invoices` |
| Tests | INV-TF-8812 → QTY +20 → CN-TF-221 → posted 5100004421; replay returns `"replayed": true` |

### M11 · Savings & Value Realisation
*Source & Contract · S14*

| | |
|---|---|
| Tables | savings_initiative, savings_ledger_entry, baseline |
| States | Identified → Negotiated → Contracted → Realising → Validated \| Lost |
| APIs | `GET /v1/savings`, `POST /v1/savings/initiatives`, `/validate` |
| Events | Consumes sourcing.event.awarded, invoice.posted; emits savings.realised |
| Rules | Realised only from posted invoices; cost avoidance never reduces budget; validator differs from owner (SOD-07) |
| Screens | SAV-01, SAV-02 ← `/savings` |
| Tests | SV-0412: negotiated 0.99 Cr/yr, avoidance 0.32 Cr, realised YTD 0.38 Cr |

### M12 · Predictive Intelligence & Agents
*Intelligence · S17–S19*

| | |
|---|---|
| Tables | agent, agent_version, autonomy_policy, kill_switch, agent_run, recommendation, feedback, model_version, copilot_session, retrieval_chunk (pgvector) |
| APIs | `POST /v1/copilot/ask`, `POST /v1/agents/{agent}/runs`, `PUT /v1/agents/{agent}/autonomy`, `POST /v1/agents/{agent}/kill-switch` |
| Rules | Agents act only with their role's permissions; L3/L4 only in configured categories and values; every action logged; answer contract mandatory; numbers from tools, never generated |
| Screens | AIX-01 ← `/command-centre` · AIX-02 ← `/copilot` · AIX-03 ← `/command-centre/ai-agents` |
| Tests | Autonomy guard denial cases; cross-tenant retrieval leak test; answer-contract completeness ≥ 99% |

### M13 · Platform, Workflow & Administration
*Platform · S0–S3, S20*

| | |
|---|---|
| Tables | Org model, currency, fx_rate, factory_calendar, number_range, role, permission, role_assignment, sod_rule, sod_violation, action_log, rule_set, process_def, audit_event, outbox_event, integration_message, idempotency_record, industry_template |
| APIs | `/v1/admin/*`, `GET /v1/audit/{objectType}/{id}`, `POST /v1/integration/messages/{id}/replay` |
| Rules | Rule and workflow versions are effective-dated; in-flight documents keep their version |
| Screens | ADM-01 ← `/admin/settings` · ADM-02 ← `/admin/governance` · ADM-03 ← `/bpmn-flows` (bpmn-js) · ADM-04 ← `/admin/users` · ADM-06 ← `/admin` · templates ← `/industry-templates` · ADM-05 *new* |
| Tests | RLS suite; audit chain tamper detection; rule version pinning on in-flight documents |

---

## 9. Principle traceability

Where each mandatory principle is enforced, when it lands, and how it is proven.

| ID | Principle | Enforcement point | Sprint | Proof |
|---|---|---|---|---|
| P01 | Traceable purpose | `purpose_code NOT NULL` on PR, PO, contract; submit guard | S4 | API test: submit without purpose → 422 `RULE_VIOLATION` |
| P02 | Two demand origins | Origin enum; trigger rejects updates | S4 | DB test: update origin fails |
| P03 | Reuse before create | Guided-buying search service ordering; agent uses the same service | S5 | E2E: free text offered only after no contract/catalogue/material hit |
| P04 | No master pollution | CHECK constraint; no code path creates material from PR | S4 | Unit + DB constraint test |
| P05 | Governed material creation | F9 with duplicate gateway at 0.92 | S5 | Workflow test with Zeebe test engine |
| P06 | Evidence-based sourcing | Publish guards (approved requirement, qualified invitees, weights 100) | S10 | API tests per guard |
| P07 | Inheritance into PO | PO creation copies references; `deviation_reason` CHECK | S6, S12 | RFQ-2231 → SA-5520 → PO-77410 test |
| P08 | Purchase-type rules | Purchase-type matrix as rule set driving GR, valuation, match | S4–S8 | Parameterised tests across 7 types |
| P09 | Approvals & SoD | Camunda tasks + SoD engine at command time | S2–S3 | SoD suite SOD-01…07 for humans and agents |
| P10 | Complete lineage | `document_link` written on every conversion | S3 onward | Lineage test from PO line to MRP run |
| P11 | Explainable AI | Answer-contract schema validation; run log | S17–S18 | Contract completeness eval |
| P12 | Three kinds of savings | Ledger from invoice.posted only | S14 | SV-0412 test |
| P13 | Exactly-once posting | Outbox + `integration_message` unique key + query-before-retry | S3, S8 | 10,000-invoice soak with fault injection |
| P14 | Configurable everything | Effective-dated rule sets by scope | S3 | Version pinning test; CI check for hardcoded thresholds |

---

## 10. SoD implementation

The current `sod_service.py` uses different rule IDs from the blueprint. In S2 the IDs are re-aligned to this table, which is the default tenant rule set.

| Rule | Action A | Conflicts with action B | Risk | Checked at |
|---|---|---|---|---|
| SOD-01 | Create supplier master | Create PO for same supplier | High | PO create / release |
| SOD-02 | Change supplier bank details | Approve payment / post invoice | Critical | Invoice approve, post, payment run |
| SOD-03 | Create PO | Post GR for same PO | High | GR post |
| SOD-04 | Create PO | Approve invoice exception for same PO | High | Exception resolve |
| SOD-05 | Award sourcing event | Score same event as sole evaluator | Medium | Award approve |
| SOD-06 | Request material | Approve same material as steward | Medium | Steward decision |
| SOD-07 | Initiate savings | Validate same savings | High | Savings validate |

Each check reads `action_log` for the object and its related objects, applies to agents running under a role, and either blocks (409 `SOD_CONFLICT`) or routes to a mitigating approval as the tenant configures. Every outcome is written to `sod_violation` and the audit chain.

---

## 11. Security and privacy

| Control | Implementation | Sprint |
|---|---|---|
| Identity | Keycloak OIDC/SAML federation; MFA for approvers, finance, admins; supplier users by invitation with MFA | S2 |
| Authorisation | RBAC scopes + ABAC (company code, plant, category, value band) per request; CI check that every route declares a scope | S2 |
| Tenant isolation | RLS on every table, non-owner DB role, tenant from token only | S1 |
| Data protection | TLS 1.3; AES-256 at rest; field-level encryption for bank accounts and tax IDs with per-tenant Cloud KMS keys; masked display | S1, S7 |
| Bank-change fraud | Dual finance approval, call-back, cooling-off, alert on change + invoice within 30 days | S7 |
| Audit | Append-only, hash-chained, 10-year configurable retention, nightly verification | S2 |
| Application security | OWASP ASVS L2; Semgrep SAST, ZAP DAST, pip-audit/npm audit, Trivy image scan, SBOM, signed images; secrets only in Secret Manager | S0 onward |
| Privacy (DPDP Act) | Purpose limitation, India residency default, retention and deletion workflows, PII redaction at LLM gateway | S17, S24 |
| Threat modelling | STRIDE review per module before its first sprint; pen test in S24 | Ongoing |

---

## 12. NFRs and operations

| Attribute | Target | How | Verified by |
|---|---|---|---|
| Availability | 99.9% transactional · 99.5% analytics | Regional GKE, HA Cloud SQL, multi-zone broker | SLO dashboards from S9 |
| Performance | P95 < 400 ms · PR form < 2 s | Indexed queries, read models, Redis caching, cursor pagination (max 200) | k6 per release |
| Spend cube | < 3 s on 50 M lines | ClickHouse with CDC refresh < 5 min | ClickHouse benchmark S14, S24 |
| MRP | 50,000 materials < 10 min | Partitioned workers, vectorised netting | S16 benchmark |
| Scale | 10,000 concurrent users/tenant · 5 M invoices/yr | Horizontal API pods, broker partitioning by tenant | S24 load test |
| Recovery | RPO 15 min · RTO 4 h | PITR, cross-region replica, Terraform rebuild | S24 DR drill |
| Accessibility | WCAG 2.1 AA | Design system components, jsx-a11y lint, axe in CI | Audit S24 |

### Observability

- OpenTelemetry traces across web, API, workers, Zeebe and connectors; `traceId` in every error response.
- Golden signals per module; business SLOs for PR approval latency, touchless rate, first-pass match rate and posting success rate.
- Runbooks for dead-lettered postings, workflow incidents, MRP run failure and model drift; on-call rota from S9.
- Blue/green deployments; migrations stay backward-compatible for one release (expand, migrate, contract).

---

## 13. CI/CD and environments

### Pipeline

1. **Pull request:** ruff, mypy (strict on `modules/*/states.py`, `rules.py`), pytest unit and API, eslint, `tsc`, Vitest, OpenAPI breaking-change diff, Avro compatibility, gitleaks, Semgrep, dependency audit.
2. **Merge to main:** build images, Trivy scan, SBOM, cosign signature, deploy to dev, integration tests with Testcontainers and Zeebe, migration upgrade/downgrade check.
3. **Nightly:** RLS and SoD suites, Camunda process tests, ZAP against the test environment, Pact verification.
4. **Release:** Playwright E2E, k6, change approval, blue/green to production.

### Environments

| Env | Purpose |
|---|---|
| local | docker-compose dev stack |
| dev | Auto-deploy from main |
| test | Nightly suites, ERP sandboxes |
| staging | Release candidates, UAT, anonymised pilot data |
| prod | asia-south1, DR asia-south2 |

---

## 14. Testing and release gates

| Layer | Scope | Tooling | Gate |
|---|---|---|---|
| Unit | Netting, match, TCO, risk, rules, state machines | Pytest, Hypothesis, Vitest | 85% coverage on domain logic |
| Contract | Service APIs and event schemas | Pact, schema registry compatibility | Must pass to merge |
| Integration | Workflow + modules + DB with RLS | Testcontainers, Zeebe test engine | Nightly |
| E2E | E2E-01…n through UI | Playwright | Release gate |
| Security | RLS isolation, SoD, authZ, OWASP | Custom suites, ZAP, external pen test | Release gate |
| Performance | NFR targets | k6, ClickHouse benchmarks | Per release |
| AI evaluation | Accuracy, MAPE, answer-contract completeness | Offline eval sets + human review | Before any autonomy increase |

The worked example (Axion Mobility: MR-1043 → REQ-2311 → RFQ-2231 → SA-5520 → PO-77410 → ASN-61208 → GR-90231 → INV-TF-8812 → SV-0412) is implemented as one executable scenario that grows each phase and must stay green on every release.

---

## 15. Data migration and cutover

| Object | Source | Approach | Validation | Rehearsals |
|---|---|---|---|---|
| Suppliers & materials | ERP masters | Initial load + delta sync | Counts, duplicate scan, bank verification sample | S9, S14, S24 |
| Open contracts | ERP, shared drives | Template load; AI clause extraction with review | Value and validity totals | S14, S24 |
| Open POs | ERP | Load with ERP number as external reference | Open value per supplier matches | S9, S24 |
| Spend history | 24–36 months PO + invoice | Bulk load to ClickHouse; classification run | Ties to GL ±0.5% | S14, S24 |
| Open invoices | ERP AP | Read-only references; new invoices through platform | AP ageing matches | S24 |
| Current demo data | Postgres / `capability_twin.db` | One-off script in S1 into new schema; then discarded | Row counts | S1 |

---

## 16. Existing code disposition

What happens to each part of the current codebase.

| Code | Action | Detail |
|---|---|---|
| `services/rules_engine.py` | Refactor | Keep logic; thresholds read from rule sets (S3) |
| `services/sod_service.py` | Refactor | Move to DB, re-align rule IDs, remove seeded fake violations (S2) |
| `services/lineage_service.py` | Refactor | BFS over `document_link` (S3) |
| `services/outbox_service.py` | Replace | Transactional outbox + relay + connector worker (S3) |
| `routers/purchasing_p2p.py` | Rebuild | Logic reused in requisition, order, receiving, payables modules (S4–S8) |
| `routers/procurement.py`, `finance.py`, `actions.py` | Migrate, then retire | Data migrated; frozen in S1; removed once pages use `/v1` (S9) |
| `sourcing_clm_savings.py`, `contracts.py`, `sealed_bid_mip.py` | Rebuild | sourcing, contract, savings modules (S10–S14) |
| `planning_mdm.py`, `mdm_governance.py` | Rebuild | mdm (S5, S7), planning (S15) |
| `unified_approvals.py`, `invoice_exceptions.py` | Rebuild | Camunda task inbox (S3); payables exceptions (S8) |
| `admin.py`, `enterprise_admin.py`, `tenant.py` | Rebuild | admin module on Keycloak and DB (S1–S3) |
| `copilot.py`, `spend_cube_ai_agents.py`, `core/agent_graph.py` | Replace | ai module (S17–S18) |
| `routers/inventory.py` | Keep, harden | Add auth, RLS, money types; feeds MRP on-hand (S7) |
| Supplier profile, onboarding, evidence, scoring, twin, development, DFSC, ESG, network, discovery | Keep in twin context | Persist in-memory stores; expose the §12.3 interface (S13) |
| `iot.py`, `blockchain.py`, `simulation.py`, `analytics.py`, `analytics_hub.py`, geospatial page | Feature-flag off | Not in the blueprint; remove random data; product owner decides scope after GA |
| `app/api/*` (unregistered), `telemetry.py`, `inventory.py.bak`, `core/db.py` | Delete | S0 |
| `test_*.py`, `verify_*.py` | Port | Into pytest suites (S0–S1) |
| Frontend pages | Refactor | Keep layout and flows; move to design system and typed client; replace inline seed arrays; split pages over 600 lines |
| `components/layout/Shell.tsx` | Refactor | Navigation from user scopes, grouped Decide · Plan & Request · Source & Contract · Order to Pay · Reference; lifecycle strip; Copilot in header |

---

## 17. Risks

| Risk | Impact | Mitigation | Owner |
|---|---|---|---|
| Team smaller than six squads | Dates slip up to 2× | Keep phase order; cut industry packs to manufacturing + general first | Delivery manager |
| Camunda 8 licence or learning curve | Workflow delays from S3 | Confirm licence in S0; spike in S1; Camunda SaaS as fallback | Architect |
| Late ERP sandbox access | S8 posting blocked | Request in S0; WireMock contract stubs from SAP API specs | Integration lead |
| Frontend breaks during legacy API retirement | Demo regressions | Freeze legacy API in S1; migrate pages module by module behind feature flags | Order to Pay lead |
| Twin features compete for capacity | Core PIC scope slips | Twin work limited to the §12.3 interface until GA | Product owner |
| Pilot data quality | Migration rework | Three rehearsals; duplicate and bank checks before load | Integration lead |
| LLM accuracy, cost or data leakage | Trust and compliance | Tool-computed numbers, permission-filtered retrieval, eval gates, gateway budgets | Intelligence lead |
| MIP award solve times | Slow SRC-04 | Bound supplier count; CP-SAT time limits; cache scenarios | Source & Contract lead |

---

## 18. Definition of done

- Acceptance criteria and linked workbook test cases pass; the screen matches its blueprint ID and states.
- Every command checks scope and ABAC, runs SoD where a rule applies, writes an audit event and, where relevant, an outbox event in the same transaction.
- State transitions go through the module's state machine; illegal ones return 409; stale writes return 412.
- Thresholds live in rule sets; no hardcoded values (CI check).
- Money in minor units with currency; dates in UTC.
- OpenAPI and Avro schemas updated; idempotency, concurrency and `problem+json` errors handled.
- RLS test added for any new table.
- Frontend uses the typed client and design system; keyboard-complete; axe passes; loading, empty and error states designed.
- Runbook and dashboards updated for any new failure mode.

---

## 19. First ten working days

Sprint 0, 26 October to 6 November 2026.

| Day | Work | Owner |
|---|---|---|
| 1 | Git repository, branch protection, baseline commit of current code | Platform lead |
| 1–2 | Fix requirements, delete dead code, remove backdoor and hardcoded secrets, add settings module | Platform |
| 2–3 | Dev stack compose file with Postgres 16, Redpanda, Keycloak, Camunda, Redis, OTel | DevOps |
| 2–4 | Pytest harness with Testcontainers; port verify scripts | QA leads |
| 3–4 | CI v1 pipeline | DevOps |
| 3–5 | Frontend API URL env var, Providers fix, legacy API freeze list | Order to Pay |
| 4–6 | Interim guards: invoice double-pay, PO state endpoint locked down | Order to Pay |
| 5–7 | ADRs DD-01 to DD-11; Camunda licence; ERP sandbox requests | Architect |
| 6–9 | Design system inventory from existing pages; component specs | UX + Plan & Request |
| 8–10 | S1 backlog groomed: schema baseline, RLS, org model, problem+json, idempotency | Platform lead |
