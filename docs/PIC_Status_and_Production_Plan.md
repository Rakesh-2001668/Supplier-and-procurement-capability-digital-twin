# PIC: Status, Pending Work and the Production Plan

AlphaHelion Procurement Intelligence Cloud. Status as of 28 Oct 2026, written after the module build (agents A–E) and the
dataset build (six dataset engineers).

## Contents

1. [Summary](#1-summary)
2. [What is in place](#2-what-is-in-place)
3. [Workflows: implementation status](#3-workflows-implementation-status)
4. [Datasets: status](#4-datasets-status)
5. [Pending work](#5-pending-work)
6. [What "production grade by tomorrow" can and cannot mean](#6-what-production-grade-by-tomorrow-can-and-cannot-mean)
7. [The plan to tomorrow](#7-the-plan-to-tomorrow)
8. [What you must supply or decide](#8-what-you-must-supply-or-decide)
9. [Go / no-go checklist](#9-go--no-go-checklist)

---

## 1. Summary

| Area | State |
|---|---|
| Core workflows F1–F9 | **Implemented**, including every gateway branch, which are now exercised by dataset D1 (cases 9–34) |
| Operations modules (amendments, auctions, EDI, payment files, e-invoice, 4-way match, reconciliation, MDM-04, punch-out, ERP import, notifications, MFA, SSO) | **Implemented**, exercised by dataset `module_cases` |
| Purchase types (expense, capital asset, consignment, subcontracting) | **Implemented in this phase**, exercised by D2 |
| Industry packs (construction, IT services, logistics, healthcare, general) | **Implemented** as five demo tenants, D3–D7 |
| Production readiness (security headers, rate limits, health/readiness, metrics, privacy, CI, container files, K8s/Terraform, runbooks) | **Implemented** (agent E) |
| Datasets | **D1–D9 and D11 done** (each engineer's full suite green: 230–249 tests); D8 generator done, full-scale runs need a production-like environment; D10 needs your ERP extract |
| Code size | 249 backend tests, 244 API routes, 114 tables, 44 screens, migrations 0001–0005 |
| Your decisions (28 Oct) | **Vercel** for now (GCP for the market later); **demo datasets on the production Neon database**; Neon **Singapore** is fine (demo data only) |
| **Biggest risk right now** | **About 140 changed files are not committed or pushed.** Nothing from the module and dataset phases is on GitHub or Neon yet. |

The product is functionally complete against the blueprint for an India-first manufacturing tenant and the five industry
packs. What separates it from a production go-live is:

- **Integration of this phase:** one full test run with every pack, then commit, push and migrate Neon.
- **A short list of code hardening items** (§5.1).
- **External items only you can provide:** hosting, credentials, legal and tax sign-off.

## 2. What is in place

| Layer | Contents |
|---|---|
| Backend | FastAPI modular monolith, schema `pic`, forced row-level security per tenant, append-only hash-chained audit, transactional outbox, workflow engine with timers and SoD, effective-dated rules with scopes, Idempotency-Key, problem+json errors |
| Integration layer | Connector registry with per-company ERP target (rule `ERP-TARGET`). SAP S/4 is a **simulator**; the EDI, SMTP, bank SFTP, GST IRP, OCR, e-sign and sanctions adapters are ready but need credentials |
| Frontend | Next.js workspace with 44 screens, a supplier portal, a BFF proxy with CSP/HSTS, multipart uploads and trace propagation |
| Operations | `/healthz`, `/readyz`, `/metrics` (golden signals, business SLOs, outbox lag), JSON logs with redaction, optional OpenTelemetry, worker heartbeat |
| Security | Rate limits per IP and per user, body-size limits, MFA (TOTP) with admin reset, OIDC SSO, field encryption, privacy export and erasure (DPDP) |
| Delivery | GitHub CI (Python 3.14 tests, migrations, pip-audit gate, npm audit, tsc/eslint, container builds), security scans (gitleaks, CodeQL, ZAP report-only), release to GHCR, Neon deploy workflow, `deploy/k8s` + `deploy/terraform` (GKE Autopilot, asia-south1), 10 runbooks |
| Data | Axion signature case (Oct 2026 – Mar 2027), migrated legacy tenants GMC and DBY, dataset packs on top of them (§4) |

## 3. Workflows: implementation status

### 3.1 Core workflows F1–F9

| Flow | Built | Branches exercised by data | Still open |
|---|---|---|---|
| F1 MRP → planned order → requisition | Yes | Simulation run, PAST_DUE, RESCHEDULE_IN/OUT, CANCEL, firming, quota sourcing, ERP import (accepted/rejected rows) | **Performance**: 50k materials takes 2–4 h against a 10 min target |
| F2 Guided buying → requisition | Yes | Return, reject, resubmit, value change re-approval, budget soft/hard, category budget warning/hard block, punch-out | Maintenance screens for budgets (loaded directly today) |
| F3 Sourcing → award | Yes | RFQ, reverse auction with soft-close, clarification board, rejected strategy recommendation, award without approval | **Sourcing event cancellation**; **award-approval rejection** path |
| F4 Contract lifecycle | Yes | Below-₹1 Cr rejection, redline, 80/90/100% alerts, renewal approved/rejected, expiry, variation, extension, termination, index reset | E-sign needs a provider (internal signatures today) |
| F5 PO → confirmation → delivery | Yes | Supplier rejection, cancellation, confirmation breach, change in/out of tolerance, EDI ORDRSP/ORDCHG, schedules, **cancel/close (new)** | **E-mail/EDI cancellation notice** to the supplier; screen buttons for cancel/close |
| F6 GR / SES → quality | Yes | Wrong-PO reversal, rejected lot → return → CAPA, rejected SES, lot/expiry/serial checks, consignment, subcontracting | **Validation that a GR's ASN belongs to the same PO** |
| F7 Invoice → match → post → pay | Yes | 2/3/4-way, ERS, dispute, IRN mismatch, ERP timeout → dead letter → replay, credit memo, retention, freight audit, payment-file rejection | **Payment-run selection by supplier/invoice** (runs are tenant-wide today); capitalisation in the GR ERP payload |
| F8 Supplier onboarding | Yes | Invitation, self-registration, qualification rejected, certificate expiry → Conditional, bank change rejected, MDM-04 address/contact/tax | Real sanctions feed |
| F9 Material governance | Yes | Steward rejection, duplicate warning band, block + override | **GST rate on a material request** (every new material defaults to 18%) |

### 3.2 Intelligence and governance flows

| Flow | State |
|---|---|
| Spend classification → steward review | Built. D9 result: 0.991 overall; the curated set scores only 0.733 because keywords match inside words ("ecu" in "security"). Fix planned (§5.1 #13) |
| Supplier de-duplication | Built. D9: registration screening precision 0.78 / recall 0.75 (no PAN or "Pvt Ltd" normalisation); spend clusters 0.83 / 1.0 |
| Category plan → budget check | **Done in this phase** (hard and warning rules on requisitions) |
| Demand sensing | Built. D9: MAPE 0.037 at horizon 1 (ERP plan 0.061); spend forecast MAPE 0.035 |
| Copilot | Built. D9: answer-contract completeness 1.0 (gate ≥ 0.99 met) on 40 questions |
| Risk signal → mitigation | Built. Needs a live feed |
| CAPA | Open, respond, verify and close all exercised (D1 case 28) |
| Reconciliation | Difference → resolution → clean rerun (module_cases REC-102/103) |
| Agent autonomy suspension (< 70% acceptance) | Built. Needs ≥ 20 feedback events from live use |
| Approval-matrix simulation (ADM-03) | **Done** (Admin → Approval simulation) |

### 3.3 Module behaviour added or fixed in this phase

The datasets exposed these gaps; each one is fixed and covered by tests.

| Area | Change |
|---|---|
| Payables | Retention withholding and release (construction); freight audit (logistics); ERS settlement for consignment; credit memo to the ERP after posting; dispute keeps the exception open |
| Orders | PO cancel and close; reversed-receipt state; subcontracting bill of materials; catalogue lines take HSN and GST from the catalogue item (they were hard-coded to 18%) |
| Receiving | Consignment stock, component provision and consumption (541/543/544), batch/expiry/serial checks, lot trace and recall, full GR reversal (inspection lot, ASN, ERP 102) |
| Requisitions | Asset lines need an asset or WBS; consignment and subcontracting lines need a material; a value change re-books the budget |
| Contracts | Late extension re-dated; cancelled POs skipped in consumption; index reset from the latest negotiated price |
| Suppliers | **Certificates never expired** (the timer fired on the expiry day itself): fixed |
| Planning | RESCHEDULE_OUT and CANCEL exceptions |
| Templates | General: goods receipt above ₹1 L; Logistics: carriers need insurance and a permit |
| Platform | Per-company ERP target; MFA admin reset; supplier portal company tab; OCR invoice upload; binary uploads through the proxy |
| Tax | New GST check: an invoice whose rate is not a scheduled rate for its HSN/SAC raises a TAX exception (CBIC notifications in force 22.09.2025) |
| Admin | Plant holiday calendars maintained through a service, with source and audit |

## 4. Datasets: status

| # | Dataset | Status | Tenant / window | Content |
|---|---|---|---|---|
| D1 | Branch cases | **Done** (25 tests) | AXN, Apr 2027 | Cases 9–34, every F1–F9 gateway outcome |
| D1b | Operations module cases | **Done** (8 tests) | AXN, May 2027 | Amendments, auction, EDI, e-way bill, 4-way match, reconciliation, payment files, MDM-04, punch-out, ERP import |
| D2 | Purchase types | **Done** (8 tests) | AXN, Jun 2027 | Expense, capital asset with capex committee and WBS hard stop, consignment + ERS, subcontracting |
| D3 | Construction | **Done** | CON | SC-118, WBS C-2207, running-account bills at 35/70/100%, 5% retention, VO-01, release |
| D4 | IT services | **Done** | ITS | SOW-4410, RC-22, 320 h timesheet, licence renewal alert and extension |
| D5 | Logistics | **Done** (with D7: 12 tests) | LOG | Lane CHE→PNQ ₹54/km with a demo fuel index, 15 trips, proof of delivery, freight audit and credit note |
| D6 | Healthcare | **Done** (8 tests) | HLT | KN-77 consignment implants, lot/expiry/serial, usage-triggered replenishment, recall trace |
| D7 | General enterprise | **Done** | GEN | Laptop punch-out ₹78,500 with one approval, catalogue, housekeeping service |
| D8 | Volume | **Generator done** (3 tests) | Local / staging only | 50k materials, invoices, spend lines. The real runs need a production-like environment |
| D9 | AI evaluation sets | **Done** (7 tests) | AXN | 2,568 + 86 labelled spend lines, 18 forecast actuals, 48 duplicate pairs, 40 Copilot questions; evaluator `python -m app.pic.tools.ai_eval` |
| D10 | Real tenant masters | **Needs your ERP extract** | Your tenant | Vendors, materials, contracts, open POs, open AP, 24–36 months of history |
| D11 | Reference data | **Done** (9 tests) | All tenants | 370 HSN/SAC rates from CBIC notifications, 212 holidays (central + 7 states 2026, central + TN 2027), 56 UNSPSC mappings, FBIL FX rates of 28 Oct 2026 |

**Still to do on the datasets:**

- **One combined run:** a full-suite run with every pack loaded in one database. Each engineer ran in their own database.
- **Order-dependent budgets:** next year's (FY 2027-28) AXN budgets are created by three packs with different amounts, so whichever pack runs first wins. They will be defined once.
- **One AXN payment run pays a signature-case invoice** (INV-TF-9031). Fixed by adding supplier selection to payment runs.
- **GSTIN check character:** the Axion company GSTIN `33AAACA4321F1Z9` fails the check. It becomes `33AAACA4321F1ZF` in the code and as an audited correction on Neon.
- **Duplicate helpers:** the GSTIN and tenant helpers exist in four copies across the packs. They will be merged into `_tenant_kit`.
- **Pack order:** reference data runs first, so it doesn't reach the five industry tenants created later. It will run last as well.
- **Invalid seed GSTINs** in the signature case (e.g. `33AABCM7890P1Z4`), and supplier registration doesn't validate the check character. Both are fixed together.

## 5. Pending work

### 5.1 Code: can be done by me, no external input

| # | Item | Why | Size |
|---|---|---|---|
| 1 | Integrate all agent changes, then one full test run on one database | Payables, orders and receiving were edited by several engineers | 2–3 h |
| 2 | Commit and push; CI green on GitHub | Nothing of this phase is saved remotely | 30 min |
| 3 | Payment-run selection by supplier, invoice or due date | Required for real AP; fixes the dataset side effect | 1 h |
| 4 | Single FY 2027-28 budget definition; GSTIN fix; merge the helpers | Data correctness | 1 h |
| 5 | Replace `python-jose` with PyJWT | Critical advisory with no fix released; not exploitable today, but it fails an audit | 1 h |
| 6 | Token revocation (token version per user, migration 0006) | A deactivated or erased user keeps a valid token for up to 8 h | 1.5 h |
| 7 | MRP quick wins: composite indexes (migration 0006), cached source determination, bulk inserts | 50k materials is 2–4 h today; quick wins should bring it to about 20–40 min, but the 10 min target needs a deeper rewrite | 3–4 h |
| 8 | Screens: PO cancel/close, consignment withdrawal and settlement, lot trace and recall, subcontracting components | The APIs exist but have no buttons | 3 h |
| 9 | Hide the "Legacy demo screens" link in production; move `PIC_ESIGN_*` into `config.py` | Production surface | 30 min |
| 10 | GR ASN-to-PO check; EDI/e-mail cancellation notice; sourcing event cancel; award-approval rejection | Spec gaps found by the datasets | 3 h |
| 11 | Docs (gap analysis, remaining-work report, process flows, README, datasets) and PDFs | Keep the documents true | 1.5 h |
| 12 | Apply 0004–0006, the rules and all packs to the production Neon database (your decision); verify | Neon still has only 0001–0003 | 1 h |
| 13 | Classifier word-boundary matching; PAN and suffix normalisation in registration de-duplication | D9 findings | 1.5 h |
| 14 | **Vercel deployment** (§6.1): API entrypoint and `vercel.json`, a worker tick through Vercel Cron plus a drain after each write, Neon pooled connection, web project settings, deployment guide | Your hosting decision | 3 h |

### 5.2 Code that needs a schema decision, later

| Item | Proposal |
|---|---|
| GST rate on a material request | Add `material_request.gst_rate` |
| HSN/SAC on free-text lines | Add the columns to requisition and PO lines |
| Job-work tax code on subcontracting lines | A separate tax code per line (SAC 9988) |
| Retention as its own items | A `retention_item` table instead of release documents as invoices |
| Consumption origin and usage numbers | Add origin `CONSUMPTION` and a usage-document number range |
| Weight on a service entry | For cost per tonne-km |
| Field-encryption key version | Needed to rotate `PIC_FIELD_KEY` |
| Maintenance screens for budgets, catalogue, taxonomy, planning data, demand, order channel | Loaded directly today, with audit |
| Other features | WBS re-check on PO variations, advance recovery, accessorials, capitalisation payload, clinical sign-off on awards |

### 5.3 Cannot be finished in code alone

- **Live integrations:** real ERP posting, GST IRP, e-sign, bank host-to-host, EDI, sanctions, SMTP, OCR and the LLM gateway all need credentials (§8).
- **Performance runs:** k6 latency (P95 < 400 ms), cube < 3 s and the 10,000-user test need a staging environment.
- **Docker:** a local image build needs Docker Desktop repaired. GitHub CI builds the images in any case.
- **Reviews and decisions:** legal retention periods, the tax team's rate confirmations, a penetration test and a ZAP triage.

## 6. What "production grade by tomorrow" can and cannot mean

**Achievable by tomorrow: a production release candidate.**

- All code integrated and tested in one run, committed, CI green, and container images built by CI.
- Neon migrated with reference data, and the hardening items §5.1 #3–#9 done.
- Integrations whose credentials are missing switched off cleanly, rather than half-configured. They surface as "needs configuration" in the admin connector screen.
- That is a system you can put real users on for a **pilot**: requisitions, approvals, sourcing, contracts, POs, receiving, invoice capture and matching, with ERP posting through the simulator or a manual export.

**Not achievable by tomorrow, whoever does the work:**

- Live money and tax flows (bank files to a real bank, IRN from the GST portal, ERP postings) until you provide credentials and the tax team signs off.
- The MRP 10-minute target at 50,000 materials.
- Proven latency and availability SLOs (needs staging and load tests) and an external penetration test.
- India data residency, if required: Neon is in Singapore today.

**Your decision on demo data:** the demo datasets go into the production Neon database, because there are no real customers yet. Before the first real customer is onboarded, plan a split (a Neon branch for demo, or removing the demo tenants).

### 6.1 Deployment on Vercel (now) and GCP (for the market)

| Part | On Vercel | Notes |
|---|---|---|
| Web (Next.js) | Vercel project with root `frontend` | Native. `PIC_API_URL` points at the API project; `PIC_ENV=production` |
| API (FastAPI) | Vercel project with root `backend`, Python **3.14** (supported), entrypoint `app/main.py:app` | Zero-config FastAPI; function region **sin1 (Singapore)**, next to Neon |
| Worker (outbox, timers, connectors) | No long-running process on Vercel. Instead: **Vercel Cron** calls a protected worker-tick endpoint, and each write request drains its own tenant's outbox after the response | **Vercel Pro** allows a tick every minute; **Hobby allows only one cron a day**, so timers (SLA escalations, certificate expiry) would wait until the next request or the daily run |
| Database | Neon, **pooled** host for the API, direct host for migrations | Tenant settings are transaction-local (`SET LOCAL`, `set_config(…, true)`), so they are safe with the pooler |
| Live updates (`/v1/stream`) | Streaming works within the function time limit; the browser reconnects | Acceptable for a demo |
| Rate limits, login lockout | In-memory per instance, so weaker on serverless | Add Vercel Firewall rules; a shared store later on GCP |
| Migrations and datasets | GitHub `neon.yml` (unchanged) | Runs on each push to `main` |

GCP (`deploy/k8s`, `deploy/terraform`, GKE Autopilot asia-south1) stays the target for the market. It runs the worker as a real process and removes the serverless limits above.

## 7. The plan to tomorrow

| When | Work | Done when |
|---|---|---|
| **Tonight, block 1** (≈ 4 h) | Last dataset agent reports → items 1, 3, 4 → full suite on one database with every pack → tsc + eslint → commit + push | Full suite green; CI green on GitHub |
| **Tomorrow morning, block 2** (≈ 4 h) | Items 5, 6, 7 (migration 0006), 9 → full suite again | Security items closed; MRP measured again and the new number reported |
| **Tomorrow midday, block 3** (≈ 3 h) | Items 8, 10, 13 → browser check of every screen on localhost → item 11 docs + PDFs | Screens and docs match the code |
| **Tomorrow afternoon, block 4** (≈ 4 h) | Item 14 Vercel deployment → item 12 Neon (production database, all packs) → `/readyz` and verification report → browser check on the Vercel URL → go/no-go (§9) | Live on Vercel; release tagged |

The plan assumes no new large scope. Anything found in the combined test run is fixed first, ahead of blocks 2–4.

## 8. What you must supply or decide

### Decisions (needed before tomorrow afternoon)

| # | Decision | Default if you don't decide |
|---|---|---|
| D-1 | Hosting | **Decided:** Vercel now, GCP for the market |
| D-1a | **Vercel plan: Pro or Hobby?** | Pro is needed for a worker tick every minute; on Hobby, background work runs only after requests and once a day |
| D-2 | Demo data on production Neon | **Decided:** same database (demo only, no real customers yet) |
| D-3 | Data residency | **Decided:** Neon Singapore for now; Vercel functions in sin1 |
| D-4 | **Identity**: company SSO through OIDC, or built-in passwords + MFA | Built-in passwords + MFA |
| D-5 | **Neon plan**: history retention ≥ 7 days, daily export | Current plan; RPO not guaranteed |

### Supplies

| Item | Needed for |
|---|---|
| Rotate the Neon password (it was shared in chat earlier) and update `backend/.env` and the GitHub secrets | Security, before go-live |
| GitHub secrets: `NEON_DATABASE_URL`, `PIC_SEED_PASSWORD`, `PIC_JWT_SECRET` (≥ 48 chars), `PIC_FIELD_KEY`, `PIC_METRICS_TOKEN`, `GITLEAKS_LICENSE` (organisation repos) | CI, release, Neon deploy |
| Vercel: access to your team (`vercel login` on this machine, or a `VERCEL_TOKEN` + team/org ID as GitHub secrets) and the plan (Pro/Hobby) | Deploying |
| Domain name (optional; Vercel gives `*.vercel.app` with TLS) | Go-live |
| ERP sandbox or extract (SAP S/4 first): vendors, materials, contracts, open POs, open AP, history (D10) | Real data, replacing the simulator |
| Credentials: SMTP, EDI gateway, bank SFTP/host-to-host + the real debtor account, GST IRP/GSP, OCR, e-sign, sanctions feed, OIDC, LLM gateway | Live integrations |
| Tax team: confirm GST for goods transport (SAC 996791 at 18%), KN-77 at 5%, ERS (self-billing) under GST, job-work SAC 9988 | Correct tax |
| Reference: FX history (only 28 Oct 2026 is loaded; the FBIL archive is behind a captcha), 2027 holiday lists for Karnataka, Maharashtra, Telangana, Gujarat, Delhi and Haryana (not published yet), real IFSC codes, a real diesel index feed, the licensed UNSPSC code set if class level is needed | Reference data |
| Legal: retention periods per data category, lawful-basis wording | Privacy |
| Business: FY 2027-28 budgets (the demo copies FY 2026-27), the NPPA ceiling check for implant prices | Demo realism |
| Docker Desktop repair (steps given earlier) | Local image builds only |

## 9. Go / no-go checklist

- [ ] Full backend suite green in one database with every pack; tsc and eslint clean
- [ ] Everything committed and pushed; CI, security and release workflows green
- [ ] Migrations 0001–0006 on Neon; `alembic check` clean; RLS on every table; audit chain verifies
- [ ] `PIC_ENV=production`; legacy demo routers off; API docs off; CORS empty; production secrets set
- [ ] Neon password rotated; no secrets in the repository (gitleaks clean)
- [ ] Integrations without credentials are switched off and shown as "needs configuration"
- [ ] Browser check of every screen as buyer, approver, AP clerk, supplier and admin
- [ ] Decisions D-1 to D-5 recorded
- [ ] Known limits accepted in writing: MRP scale, no load test yet, Singapore residency (if kept), simulator ERP
