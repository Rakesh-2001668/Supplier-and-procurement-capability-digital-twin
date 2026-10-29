# PIC Requirements Traceability Matrix

AlphaHelion Procurement Intelligence Cloud. Specs: Technical Document AHG/PRC/PIC/2026-10/02 (TD) and Product Blueprint AHG/PRC/PIC/2026-10/01 (BP).
Code at commit `5a63ed3` (+1 modified doc), read on 29 Oct 2026.

**How this was built.** Every row was checked against the code (`backend/app/pic/**`, migrations 0001–0007, `backend/tests/pic/**`,
`frontend/src/app/pic/**`, `.github/workflows/*`, `deploy/**`), plus read-only SELECTs on the local full build `pic_neon_build`
(8 tenants, every dataset pack). The project's status documents were used only as pointers. Where they disagree with the code,
the code wins. Example: `PIC_Remaining_Work_Report.md` lists punch-out, EDI, auctions and 4-way match as "not built", but they
are built. The suite was not run. The last recorded full run (`scratchpad/final_suite.log`) shows **387 passed, 2 failed**; the code
review report says those 2 tests were re-run and passed after their expectations changed.

**Status key**
- **DONE**: implemented, and covered by tests or seeded data.
- **PARTIAL**: something is missing; the row says what.
- **NOT DONE**: not built.
- **EXTERNAL**: the code or adapter is ready but needs a credential, a system, data or a decision from you.
- **N/A**: does not apply.

Abbreviations: `svc/` = `backend/app/pic/services/`, `plat/` = `backend/app/pic/platform/`, `api/` = `backend/app/pic/api/`,
`tests/` = `backend/tests/pic/`, `fe/` = `frontend/src/`. DB = `pic_neon_build`.

**Database facts used below:**
- 115 tables. Row-level security is forced on 112 of them; the 3 exceptions are global tables (`tenant`, `process_definition`, `alembic_version`).
- 8 tenants: AXN, GMC and DBY (manufacturing), CON, ITS, LOG, HLT, GEN.
- 18 `dataset_load` rows.
- All 84 F1–F9 steps were executed, and all 13 gateways were taken both ways.
- 490 agent runs and 3,423 audit events.
- 229 integration messages, all POSTED.

---

## Part 1 — Technical Document

### TD §1.1 Engineering conventions

| ID | Requirement | Status | Evidence / gap |
|---|---|---|---|
| TD-1.1a | TypeScript end-to-end (NestJS services, Next.js web); Python for ML | **PARTIAL** | Web: Next.js 16 / TS (`frontend/package.json`). Backend is a **Python 3.14 FastAPI modular monolith** (`backend/app/main.py`), not NestJS services. This is an architecture deviation (project DD-01) that the customer has not signed off. |
| TD-1.1b | UUIDv7 IDs; human-readable numbers per tenant and number range | **DONE** | `uuid.uuid7()` throughout; `plat/core.py:next_number/next_numbers`; `number_range` has 224 rows (DB) |
| TD-1.1c | Money as integer minor units + ISO currency; FX rate and date stored with every converted amount | **PARTIAL** | Integer minor units: `*_minor` columns. `fx_rate` table holds 4 rates per tenant, all for one date (28 Oct 2026). **No document converts currency, and no rate or date is stored on any amount.** PO currency is hard-coded `"INR"` (`svc/order.py:_create_po`). |
| TD-1.1d | UTC storage; tenant time zone; factory calendar | **DONE** | `tenant.timezone`; `plant.working_days/holidays`; `clock.subtract_working_days` used by `svc/planning.py:_Reads.release_date` |
| TD-1.1e | Every write → audit event + outbox event in the same transaction | **DONE** | `plat/audit.py:record`, `plat/outbox.py:emit` (caller's session); `StateMachine.apply` audits every transition |
| TD-1.1f | Configuration over code: thresholds, tolerances, mandatory fields, approval chains as effective-dated rule data | **PARTIAL** | 33 effective-dated, scoped rule keys (`seed/reference.py:RULE_SETS`, `plat/rules.py:resolve`). Mandatory fields are not configurable (no rule key). Hard-coded values remain: `purch_org="1000"`, `currency="INR"`, company code default `"1000"`, GST fallback 18% (7 occurrences in `svc/`). |
| TD-1.1g | AI doctrine: no agent commits spend outside its autonomy level and role | **DONE** | The only spend-committing agent (Touchless PO) is gated by `plat/agents.py:guard(L4, scope po:release, value ≤ ₹25 L)` at `svc/order.py:343`. All other agents recommend or draft. |

### TD §2.1 Technology stack

| ID | Layer / choice | Status | Evidence / gap |
|---|---|---|---|
| TD-2.1a | Web: Next.js, React, TS, AlphaHelion tokens | **DONE** | `fe/app/pic/**` (45 pages); tokens `#0B1020`, `#1A56DB` in `fe/components/pic/*` |
| TD-2.1b | API: NestJS; GraphQL for read models, REST for commands | **PARTIAL** | REST only: 254 routes under `/v1` (FastAPI). **No GraphQL.** |
| TD-2.1c | Workflow: Camunda 8 (BPMN/DMN) | **PARTIAL** | Replaced by a Postgres-native engine (`plat/workflow.py`: human tasks, timers, SLAs, escalation, versioned `process_definition`). No Camunda, no BPMN XML, no DMN files. Needs a decision: accept the replacement or adopt Camunda. |
| TD-2.1d | Data: PostgreSQL 16 (RLS), Redis, OpenSearch, ClickHouse | **PARTIAL** | PG 16 (`ci.yml` `postgres:16`) with forced RLS. **No Redis** (rate limits are in-memory per instance), **no OpenSearch** (SQL search), **no ClickHouse** (spend cube on Postgres). |
| TD-2.1e | Events: Kafka + outbox + schema registry | **PARTIAL** | Outbox with in-process consumers (`plat/outbox.py`). `_publish_external` is a stub that returns None. No Kafka, no Avro registry. |
| TD-2.1f | AI/ML: Python services (FastAPI), feature store, MLflow registry, LiteLLM gateway | **PARTIAL** | Models are in-process heuristics with version strings (`demand-es-v1`, `copilot-rules-v1`). **No feature store, no MLflow, and no LLM call anywhere.** `litellm==1.102.2` is in `requirements.txt` but never imported. |
| TD-2.1g | Integration: SAP (OData/IDoc), Oracle, Dynamics, Tally, Odoo; cXML/OCI; EDI; GST e-invoice | **PARTIAL** | See §12. SAP is a simulator only; the other ERP connectors need credentials. |
| TD-2.1h | Infra: GCP GKE, Cloud SQL/AlloyDB, Pub/Sub, Secret Manager, Cloud Armor; Terraform | **EXTERNAL** | `deploy/terraform` (asia-south1) and `deploy/k8s` exist but are not provisioned. The current target is Vercel + Neon Singapore (`backend/vercel.json`, region `sin1`). **Nothing is deployed** (docs show placeholder URLs). |
| TD-2.1i | Observability: OpenTelemetry, Grafana, structured audit stream | **PARTIAL** | OTel is optional (`PIC_OTEL_ENABLED`, `plat/observability.py`). `/metrics` with a ServiceMonitor. **No Grafana dashboards in the repo.** Audit stream = hash-chained `audit_event`. |

### TD §2.2 Architecture decisions

| ID | Decision | Status | Evidence / gap |
|---|---|---|---|
| AD-01 | Camunda 8 for approvals and long-running flows; process keys are part of the API | **PARTIAL** | Own engine in `plat/workflow.py` with process keys `pic.*` (`plat/process_defs.py`). Process keys are exposed: `GET /v1/process-definitions` and `/v1/documents/{type}/{ref}/process`. Camunda itself is not used. |
| AD-02 | PostgreSQL RLS; every table has tenant_id; connection sets app.tenant_id; RLS tested in CI | **DONE** | Migration `0002_rls_roles_grants.py`. `db.py:100–101` runs `SET LOCAL ROLE pic_app` and `set_config('app.tenant_id')`. Tests: `tests/test_controls.py::test_rls_hides_other_tenant_rows` and `::test_rls_blocks_cross_tenant_writes`. CI runs them on every push. DB: RLS forced on 112/115 tables. |
| AD-03 | Outbox + Kafka; idempotent consumers; versioned schemas in a registry | **PARTIAL** | Outbox plus `processed_event` (idempotent consumers), with retry back-off (`next_attempt_at`, migration 0007). **No Kafka; no registry**; `schema_version` is always 1. |
| AD-04 | ClickHouse spend cube: < 3 s on 50 M lines; < 5 min CDC refresh | **NOT DONE** | The cube is a Postgres GROUP BY (`svc/savings.py:spend_cube`). SPD-01 `svc/spend.py:overview` **loads every spend line of 12 months into Python**, so it cannot meet 3 s at 50 M lines. Never measured: `tools/volume_gen.py --measure` exists but no run is recorded. Refresh runs on `invoice.posted`, which is near real time. |
| AD-05 | MRP optional; in-platform engine or ERP planned-order import | **DONE** | `svc/planning.py:run`; `svc/erp_import.py:import_planned_orders` (JSON and CSV). DB has `MR-1048` in mode `ERP_IMPORT`. |
| AD-06 | LLM access only through the LiteLLM gateway | **NOT DONE** | No gateway client exists. `svc/copilot.py` only mentions `PIC_LLM_GATEWAY_URL` in its docstring and builds answers deterministically. Nothing calls a model vendor, so the constraint is not violated, but the gateway path is unbuilt. |
| AD-07 | Effective-dated rule sets; documents store rule_set_version | **DONE** | `rule_set` (256 rows); `plat/rules.py:resolve` resolves most-specific first, deterministically. `rule_set_version` is stored on requisition, PO, invoice, contract, material_request, award, task and audit_event. |

### TD §3 Service decomposition

| ID | Requirement | Status | Evidence / gap |
|---|---|---|---|
| TD-3a | One service per bounded context, each owning its data; cross-service reads only via events/read models | **PARTIAL** | Modules exist as `svc/*.py` inside one deployable. **Modules read each other's tables directly** (e.g. `svc/order.py` reads Supplier/Contract; `svc/savings.py:_spend` reads PoLine/PO). No import-linter rule enforces boundaries, despite project DD-01. |
| TD-3b | Owned entities per Table 3 | **PARTIAL** | All listed entities have tables, except **legal_entity, purch_org and purch_group** (stored as strings) and **mrp_run_result** (simulation results are kept on `mrp_run`). |
| TD-3c | API surfaces and events per Table 3 | **DONE** | See §10 and §11 |

### TD §4 Multi-tenancy & organisation model

| ID | Requirement | Status | Evidence / gap |
|---|---|---|---|
| TD-4a | Hierarchy tenant → legal entity/company code → plant → storage location; purch org/group; cost objects (CC, internal order, WBS, asset) | **PARTIAL** | Tables `company_code`, `plant`, `storage_location`, `cost_object` (type COST_CENTER, WBS, ORDER or ASSET). **No legal-entity, purchasing-org or purchasing-group master** (`purch_org` is hard-coded `"1000"`). |
| TD-4b | RLS tenant isolation; per-tenant KMS keys for field encryption | **PARTIAL** | RLS is DONE. Field encryption uses per-tenant keys derived by HKDF from one `PIC_FIELD_KEY` (`plat/crypto.py`). **Not KMS**, and there is no key version, so keys cannot be rotated. |
| TD-4c | Rules bind to scope (tenant, company code, plant, category, purchase type); most specific wins | **DONE** | `plat/rules.py:resolve` (specificity rank, then effective date, then created_at); duplicate versions refused |
| TD-4d | Industry template seed bundle at tenant creation, editable afterwards | **DONE** | `seed/templates.py` (6 packs, `merged_rules`), `GET /v1/admin/templates`. Five industry tenants were built from these templates (DB). |

### TD §5 Domain data model

| ID | Requirement | Status | Evidence / gap |
|---|---|---|---|
| TD-5a | Core entities and key attributes (Table 4) | **DONE** | 115 tables. Examples: supplier has `twin_ref`, `segment`, `risk_tier`, encrypted GSTIN; material has lot-size policy, safety stock and lead times; invoice has `irn` and `erp_doc_no`; audit has `on_behalf_of`, `prev_hash` and `hash`. The org gaps are listed under TD-4a. |
| TD-5.1 | Explicit lineage `document_link` with typed link types | **DONE** | `document_link` (492 rows), `plat/core.py:link/link_many`, `GET /v1/lineage/{type}/{ref}`, Lineage tab (`fe/components/pic/object.tsx:LineageView`) |
| TD-5.2a | Free-text PR line ⇒ material_id IS NULL | **DONE** | DB CHECK `ck_pr_line_free_text_no_material` (0001) |
| TD-5.2b | Contract-priced PO line: price within tolerance or deviation_reason NOT NULL | **DONE** | Enforced in the service, not the DB: `svc/order.py:_create_po` and `_review_change` raise P07 |
| TD-5.2c | GR received ≤ PO qty × (1 + over-delivery tolerance) | **DONE** | `svc/receiving.py:149–151, 217` (RCV-TOLERANCE); test `tests/test_operating_cases.py::test_short_shipment_inside_tolerance_completes_receipt` plus review tests |
| TD-5.2d | Invoice unique (tenant, cc, supplier, no., FY); fuzzy duplicate ±₹1 / ±3 days | **DONE** | `uq_invoice_tenant_id_company_code_supplier_id_supplier_invoice_no_fiscal_year`. DMN-03 `dupAmountMinor 100`, `dupDays 3`; `svc/payables.py:_duplicate_check` |
| TD-5.2e | Integration message unique (tenant, target_system, idempotency_key) | **DONE** | `uq_integration_message_tenant_id_target_system_idempotency_key` |

### TD §6 State machines (Table 5) and guards (Table 6)

| ID | Object / transition | Status | Evidence / gap |
|---|---|---|---|
| SM-PR | Requisition Draft→Submitted→In Approval→Approved→Partially Ordered→Ordered→Closed, plus Rejected/Returned/Cancelled | **DONE** | `svc/requisition.py:SM` (also supports re-approval and cancel) |
| SM-PLO | Planned order Created→Firmed→Converted, or Deleted by the next run | **DONE** | `svc/planning.py` (firm l.370, convert l.399, delete l.256–262); DB has CREATED, FIRMED, CONVERTED and DELETED. Guards are written by hand, not with the `StateMachine` class. |
| SM-MR | Material request Draft→Duplicate Check→In Stewardship→Approved→Synced to ERP, or Rejected/Merged | **DONE** | `svc/mdm.py` (adds DUPLICATE_BLOCKED); DB: SYNCED_TO_ERP 18, MERGED 1, REJECTED 1 |
| SM-SRC | Sourcing event Draft→Published→Open→Closed→Under Evaluation→Award Pending→Awarded, or Cancelled | **DONE** | `svc/sourcing.py:SM` (also new_round and reject_award) |
| SM-CON | Contract Draft→In Negotiation→In Approval→Out for Signature→Active→Expiring→Expired, or Terminated/Renewed | **DONE** | `svc/contract.py:SM` (also extend); DB has ACTIVE, EXPIRED, TERMINATED, DRAFT and IN_NEGOTIATION |
| SM-PO | PO Draft→In Approval→Released→Transmitted→Confirmed→Partially Received→Received→Invoiced→Closed, or Cancelled; any change creates a new version | **DONE** | `svc/order.py:SM`, `po_version`; DB CHECK `ck_purchase_order_status` matches TD §19.2 |
| SM-GR | GR Posted→Quality Hold→Accepted/Partially Rejected/Rejected→Reversed | **DONE** | `svc/receiving.py:GR_SM` |
| SM-SES | SES Draft→Submitted→Approved/Rejected→Revoked | **DONE** | `svc/receiving.py:SES_SM` |
| SM-INV | Invoice Captured→Duplicate Check→Matching→Exception/Matched→Approved→Posted→Paid, or Rejected | **DONE** | `svc/payables.py:SM` |
| SM-SUP | Supplier per category Registered→Under Qualification→Qualified/Conditional→Preferred/Blocked/Exited | **DONE** | `svc/supplier.py:_set_category_status`, `supplier_category_status`, `POST /v1/suppliers/{code}/categories/{category}/status`. No PREFERRED rows in the seed. |
| SM-SAV | Savings Identified→Negotiated→Contracted→Realising→Validated, or Lost | **DONE** | `svc/savings.py:SM` |
| SM-409 | Illegal transitions return 409 | **DONE** | `plat/errors.py:illegal_transition`, `tests/test_controls.py` |
| G-1 | Requisition Submitted→In Approval: budget check or soft-stop justification; **mandatory fields per rule set**; purpose code (P01) | **PARTIAL** | Budget (rule BUDGET) and purpose code are enforced. **Configurable mandatory fields do not exist**; there is no rule key for them. |
| G-2 | Sourcing Draft→Published: invitees Qualified or Conditional-with-waiver; weights sum to 100, then locked | **DONE** | `svc/sourcing.py:publish` (l.137–149), `_require_eligible` |
| G-3 | Sourcing Closed→Under Evaluation: close time reached; bids unsealed with audit `bids.unsealed` | **DONE** | `BIDS_UNSEALED` audit (l.331); early access is blocked with 423 and audited as `BID_ACCESS_DENIED` (l.237–244) |
| G-4 | Contract Out for Signature→Active: all signatures; approvals done; price validities published | **DONE** | `svc/contract.py:activate` (l.324–335; signature document hash check) |
| G-5 | PO Draft→Released: supplier not Blocked; approval or touchless; SoD for releaser | **DONE** | `PO_SUPPLIER_BLOCKED` (`svc/order.py:340`); approver chain excludes the creator (`initiator_id=po.created_by`, l.367) |
| G-6 | PO Confirmed→new version: qty/price/date change → v n+1 and re-confirmation | **DONE** | `svc/order.py:change_order`, `po_version`, EDI ORDCHG |
| G-7 | SES Submitted→Approved: approver ≠ PO creator ≠ supplier user | **DONE** | `svc/receiving.py:930–932` |
| G-8 | Invoice Matched→Posted: no open exceptions; posting idempotency key reserved | **DONE** | `svc/payables.py:post`, `posting_key`; `tests/test_controls.py` exactly-once tests |
| G-9 | Supplier Qualified→Conditional automatically when a mandatory certificate expires | **DONE** | `@on_timer("CERTIFICATE_EXPIRY")` in `svc/supplier.py:701–724`; D1 branch case |

### TD §7 Rules & decision tables

| ID | Table | Status | Evidence / gap |
|---|---|---|---|
| DMN-01 | Requisition approval route: < ₹25,000 catalogue/contract auto; ₹25k–2 L cost-object owner; 2–10 L + dept head; > 10 L + procurement head + finance controller; asset + capex committee | **DONE** | `seed/reference.py:RULE_SETS["DMN-01"]` (bands, `autoChannels`, `assetAdds`, `slaBusinessDays 2`). Open decision: band upper bounds are exclusive, so exactly ₹2 L or ₹10 L takes the larger chain (code review §7). |
| DMN-02 | Touchless PO: contract/catalogue price, Qualified/Preferred, value below band, no split, late < 0.30, risk < 30 | **DONE** | `RULE_SETS["DMN-02"]`, `plat/rules.py:touchless`, `svc/order.py:validate`. PO-77410: risk 18, touchless (DB). The "touchless band" value is not given by the spec; the default is **₹25 L** and needs your confirmation. |
| DMN-03 | Invoice tolerance: price ±1% or ₹500 (lower); qty 0% (3-way); SES 0%; tax exact + IRN; duplicate | **DONE** | `RULE_SETS["DMN-03"]`; `svc/payables.py:match` (price cap on line value, tax rate + HSN + IRN l.428–441) |
| PO-RISK | Additive score 18/35/18/40/15/25/12, capped at 100, explainable | **DONE** | `RULE_SETS["PO-RISK"]` weights match the TD; `plat/rules.py:po_risk`; factors stored in `po.risk_factors`. Caveat: the late-delivery probability is read from the seeded twin snapshot, not a model (see §13). |
| DMN-ver | Decision tables versioned per tenant | **DONE** | Each tenant has its own `rule_set` rows (8 per key) |

### TD §8 Workflow implementation (BPMN F1–F9)

DB coverage: every one of the 84 steps was executed. All 13 gateways were taken both ways (`process_step` grouped by step_id and outcome).
Instances by flow: F1 7, F2 56, F3 3, F4 17, F5 62, F6 58, F7 72, F8 32, F9 21.

| ID | Flow / key | Status | Evidence / gap |
|---|---|---|---|
| F1 | `pic.mrp-to-pr`: scheduled/planner start; Review exceptions (MRP_CONTROLLER); lot sizing; conversion with source determination | **DONE** | 10 steps (`plat/process_defs.py`); F1-05 taken as live run, live import and simulation; `svc/planning.py`. Not scheduled: runs are started from the API only (no cron for "scheduled run"). |
| F2 | `pic.requisition`: DMN-01; SLA 2 business days; parallel MDM stewards | **DONE** | 9 steps; F2-03 taken via contract, catalogue, material and free text; F2-05 yes and no |
| F3 | `pic.sourcing-award`: close timer; award approval by value (CATEGORY_MGR, CPO, FINANCE) | **DONE** | `@on_timer("SOURCING_CLOSE")`; AWARD-APPROVAL bands at ₹50 L; F3-07 yes and no |
| F4 | `pic.contract`: award or renewal (−120 d timer); Legal/Finance approval; signature; consumption alerts 80/90/100% | **DONE** | `CONTRACT_RENEWAL` / `CONTRACT_EXPIRY` timers (`svc/contract.py:488,515`); thresholds `[80,90,100]`. Signatures are internal; the e-sign provider is EXTERNAL (§12). |
| F5 | `pic.po`: DMN-02 touchless; confirmation SLA timer | **DONE** | `@on_timer("PO_CONFIRMATION_SLA")` (24 h, PO-APPROVAL); F5-04 and F5-08 taken both ways |
| F6 | `pic.receipt`: quality-managed flag; tolerance | **DONE** | F6-02 goods and service; F6-05 yes and no |
| F7 | `pic.invoice`: DMN-03; resolve exception (AP_CLERK); **payment due timer** | **PARTIAL** | The flow is built (F7-04 taken both ways). **No payment-due timer**: payment runs start only by `POST /v1/payments/runs`. |
| F8 | `pic.supplier-onboarding`: finance bank verify ×2; certificate expiry timers | **DONE** | `bankApprovers 2`; `CERTIFICATE_EXPIRY` timer; F8-06 taken as qualified, conditional and rejected |
| F9 | `pic.material-request`: parallel stewards; duplicate gateway ≥ 0.92 | **DONE** | MDM-DUP `blockAt 0.92`, `warnAt 0.75`, 4 domains; F9-04 taken as blocked, warning and override |
| F-ver | Definitions versioned; running instances finish on their version | **PARTIAL** | `process_instance.process_version` is stored, but only version 1 exists. Definitions are Python code (`plat/process_defs.py`), so a tenant cannot edit or version them. |
| F-audit | Every human-task completion audited with actor, decision, comment and evidence snapshot | **DONE** | `plat/workflow.py:complete` (decision APPROVE/REJECT/RETURN, `evidence`) |
| F-esc | Escalation: SLA breach → reminder → escalate to manager → reassign; configurable | **PARTIAL** | Rule ESCALATION: reminder at level 1, manager role added from level 2 (`@on_timer("TASK_SLA")`). **No reassignment**: the original approvers keep the task (open decision in the code review §7). |

### TD §9 Core algorithms

| ID | Algorithm | Status | Evidence / gap |
|---|---|---|---|
| ALG-9.1 | MRP netting: net = max(0, gross − supply + safety); lot size exact/fixed/EOQ/period/min-max with pack rounding; release = need − (PDT + GR days) on the factory calendar; PAST_DUE, BELOW_SAFETY, RESCHEDULE_IN/OUT; firmed orders never changed; simulation creates no documents; net-change | **PARTIAL** | `svc/planning.py:lot_size, net_material, run`. MR-1043 nets 12,000 − (1,400 + 1,200 + 600 + 0) + 200 = 9,000. CANCEL exception also built. **Buckets are daily only; the TD's "daily/weekly by MRP type" is not built.** Performance: see NFR-MRP. |
| ALG-9.2 | Source determination: contract → quota → source list → info record → buyer queue; exclude Blocked / not Qualified | **DONE** | `svc/source.py:determine` (methods CONTRACT, QUOTA, SOURCE_LIST, INFO_RECORD, NONE; `ELIGIBLE` Qualified/Preferred) |
| ALG-9.3 | TCO; weighted score with locked weights; award MIP with capacity from the twin, min share, max suppliers, **risk constraints** | **PARTIAL** | `svc/sourcing.py:_tco` (price + freight + duty + packaging + carrying + quality − payment-term value). `_optimise` is an exact enumeration, not a MIP solver, with capacity, min/max share and max suppliers. RFQ-2231 60/40 at weighted 400.8 is reproduced. **No risk constraints.** **One item per event** (`_require_one_line`). |
| ALG-9.4 | Three-way match: qty vs accepted GR − invoiced; 2-way otherwise; price ≤ min(pct, abs); tax rate/HSN/IRN; exception with suggested action | **DONE** | `svc/payables.py:match` (also 4-way, SES and ERS). INV-TF-8812: quantity exception → credit note → posted, ERP document 5100004421 (DB). |
| ALG-9.5 | Realised savings only from posted invoices; cost avoidance never in budget; validator ≠ owner (SOD-07) | **DONE** | Consumer `invoice.posted` → `savings-realised`; avoidance ledger entries have `counts=False`; `sod.guard("SAVINGS_VALIDATE")` |

### TD §10 API specification

| ID | Convention / endpoint | Status | Evidence / gap |
|---|---|---|---|
| API-1 | REST commands; GraphQL read models; JSON; OpenAPI 3.1 per service | **PARTIAL** | REST plus one FastAPI-generated OpenAPI 3.1 document (turned off in production by `PIC_API_DOCS`). **No GraphQL.** |
| API-2 | Every POST accepts Idempotency-Key; replays within 24 h return the original response | **PARTIAL** | `plat/core.py:Idempotent` is wired into **26 of 138 POST routes** (`api/*: idempotent(...)`). The other 112 ignore the key, even though the web client sends one on every POST (`fe/lib/pic/api.ts:41`). **Records never expire**: there is no 24 h window and no purge. |
| API-3 | ETag / If-Match; 412 on stale writes | **PARTIAL** | Only on purchase orders (`api/order_pay.py:73,107,122`, `api/order_ops.py:51`). No other document type has an ETag. |
| API-4 | RFC 9457 problem+json with code, ruleRef, traceId | **DONE** | `plat/errors.py`, `plat/http.py`; `tests/test_production.py` |
| API-5 | Cursor pagination, max page 200 | **DONE** | `api/pagination.py` (`MAX_PAGE = 200`, opaque cursor) |
| API-6 | OAuth 2.0 / OIDC bearer; scopes per module; tenant from the token, never the payload | **DONE** | `plat/auth.py` (PyJWT HS256 with scopes from roles), `plat/oidc.py` (OIDC code + PKCE). Tenant comes from token claims. |
| API-7 | Table 8: all 32 core endpoints | **DONE** | All 32 exist, e.g. `POST /v1/mrp/runs`, `/planned-orders/{id}/convert`, `/requisitions/{id}/lines/{n}/promote-material`, `/sourcing/events/{id}/publish`, `/bids`, `/award`, `/contracts/{id}/activate`, `GET /contracts/{id}/consumption`, `/purchase-orders/{id}/validate`, `/confirmations`, `/versions`, `/asns`, `/goods-receipts`, `/service-entries/{id}/approve`, `/invoices/{id}/match`, `/post`, `GET /spend/cube`, `GET /savings`, `/copilot/ask`, `/agents/{agent}/runs`, `GET /audit/{type}/{id}`, `/integration/messages/{id}/replay` |
| API-10.2 | Create PO from requisition returns inherited terms, validation (risk factors), lineage | **DONE** | `POST /v1/purchase-orders` (`api/order_pay.py`), `svc/order.py:validate`, `plat/core.py:upstream_chain` |
| API-10.3 | Invoice post is idempotent; a retry returns `replayed: true` | **DONE** | `POST /v1/invoices/{ref}/post` (`api/order_pay.py:414`), tests in `tests/test_controls.py` |

### TD §11 Event catalogue

| ID | Requirement | Status | Evidence / gap |
|---|---|---|---|
| EV-1 | All 23 catalogue events are emitted | **DONE** | `outbox.emit` covers every catalogue event (mrp.run.completed … savings.realised), plus 22 extra events (contract.amended, purchase_order.cancelled, lot.recalled, …) |
| EV-2 | Envelope: tenantId, eventId, occurredAt, actor, objectRef, version, traceId | **DONE** | `plat/outbox.py:envelope` |
| EV-3 | Kafka topics `pic.<tier>.<event>`; Avro schemas, backward-compatible | **NOT DONE** | `_publish_external` stub; no registry |
| EV-4 | Main consumers as in Table 9 | **PARTIAL** | Only **10 of 23** catalogue events have outbox consumers: contract.activated, contract.consumption.threshold, goods_receipt.posted, invoice.exception.raised, invoice.posted (savings, spend, scorecard), purchase_order.changed, purchase_order.released (ERP posting, consumption), quality.usage_decision, sourcing.event.awarded, sourcing.event.published. **No ai-svc consumer exists at all.** requisition.approved → order/sourcing is a synchronous call (`planning.on_requisition_approved`). supplier.status.changed → order/sourcing is checked synchronously. purchase_order.released → spend-svc/portal is not consumed. audit-svc consumers are replaced by direct audit writes. |

### TD §12 Integration architecture

| ID | Integration | Status | Evidence / gap |
|---|---|---|---|
| INT-SAP | SAP S/4HANA outbound PR/PO/GR/invoice/masters; inbound masters, stock, open POs, planned orders, payment status (OData, IDoc fallback) | **PARTIAL** | Only the **sandbox simulator** exists (`plat/connectors.py:SapS4` writes the `erp_document` table, with fault injection). **There is no real OData or IDoc client.** It must be built and verified against your SAP sandbox (EXTERNAL dependency). |
| INT-ORA | Oracle Fusion/EBS REST/FBDI | **EXTERNAL** | `OracleFusion` connector (6 message types, find-before-retry) is written but tested against mocks only. Needs `PIC_ERP_ORACLE_FUSION_*` credentials and mapping confirmation. |
| INT-D365 | Dynamics 365 OData/Dataverse | **EXTERNAL** | `Dynamics365` connector (5 types), mocks only. Needs `PIC_ERP_DYNAMICS_365_*`. |
| INT-TALLY | Tally Prime XML/ODBC via on-prem agent | **EXTERNAL** | `TallyPrime` (XML import plus lookup), mocks only. Needs the Tally gateway and agent. |
| INT-ODOO | Odoo JSON-RPC | **EXTERNAL** | `Odoo` connector, mocks only. Needs `PIC_ERP_ODOO_*`. |
| INT-IN | Inbound ERP → platform (masters, stock, open POs, payment status) | **PARTIAL** | Planned-order import only (`svc/erp_import.py`, `POST /v1/integration/planned-orders/import[/csv]`). Payment status comes back only from the simulator. **No inbound master, stock or open-PO sync.** |
| INT-12.2 | Exactly-once steps 1–4: message in the same transaction; skip if POSTED; query by external ref before retry; back-off, max 8, DEAD_LETTER, replay | **DONE** | `plat/integration.py` (2^n min back-off, `DEAD_LETTER` after 8 attempts, l.167–225), `POST /v1/integration/messages/{id}/replay`; `tests/test_controls.py`, `test_review_platform.py` (F6) |
| INT-12.2-5 | Nightly reconciliation per company code | **PARTIAL** | `svc/payables.py:reconcile`, `POST /v1/reconciliation/runs`, resolve endpoint; REC-101..103 in DB. **Not scheduled**: no nightly job. The Vercel cron runs only the worker tick, once a day (`backend/vercel.json` `0 3 * * *`). |
| INT-PUNCH | Punch-out cXML PunchOutSetupRequest/OrderMessage and SAP OCI; carts become catalogue PR lines | **EXTERNAL** | `svc/punchout.py` with a simulator; D7 laptop order ₹78,500 runs through it. Real supplier punch-out accounts are needed. |
| INT-EDI | EDI ORDERS/ORDCHG, ORDRSP, DESADV, **INVOIC** via gateway (AS2/SFTP) | **PARTIAL** | ORDERS/ORDCHG out, ORDRSP/DESADV in (`svc/transmission.py`, `POST /v1/edi/inbound`, module case PO-77425). **INVOIC inbound is not built.** Transport needs `PIC_EDI_GATEWAY_URL` (EXTERNAL). |
| INT-GST | GST e-invoice IRN and signed QR validated at capture; e-way bill on ASN | **EXTERNAL** | `svc/einvoice.py`: IRP/GSP adapter, plus local IRN hash and QR payload checks (the NIC signature is not verified locally). E-way bill rule ≥ ₹50,000 with format check (`svc/receiving.py:107`). Needs GSP credentials (`PIC_IRP_*`). |
| INT-RISK | Supplier risk feeds: sanctions, financial-risk, news | **PARTIAL** | Sanctions provider adapter (`PIC_SANCTIONS_*`, `svc/supplier.py:212–229`) with 4 fictitious SAMPLE-LIST names. **Financial and news feeds have only the `svc/risk.py:ingest` entry point; no provider adapter.** |
| INT-TWIN | Supplier Capability Digital Twin: read capability, evidence, free capacity, trust; write back OTIF/PPM/invoice accuracy | **PARTIAL** | Reads the local `twin_snapshot` (4 seeded rows) via `svc/supplier.py:twin`. Writes back to the local `twin_feedback` table (138 rows). **No connector to the actual Twin service** (no `PIC_TWIN_*` adapter). |
| MIG-1 | Suppliers & materials: initial load + delta sync; counts, duplicate scan, bank-verification sample | **PARTIAL** | Legacy migration for GMC/DBY (`seed/legacy.py`, `tools/legacy_extract.py`, `tools/migration_report.py`). **No generic ERP master loader and no delta sync.** Real data is EXTERNAL. |
| MIG-2 | Open contracts: template load + AI clause extraction with review; value/validity totals | **NOT DONE** | No contract loader and no clause extraction |
| MIG-3 | Open POs with ERP doc no. as external ref; open value per supplier matches | **NOT DONE** | No open-PO loader (only legacy POs) |
| MIG-4 | Spend history 24–36 months: bulk load + classification; ties to GL ±0.5% | **PARTIAL** | Classification runs on loaded history (AXN has 2,568 generated lines); `volume_gen` uses COPY. **No customer-file spend loader and no GL tie-out check.** |
| MIG-5 | Open invoices as read-only references; AP ageing matches | **NOT DONE** | No loader |

### TD §13 AI & ML architecture

| ID | Item | Status | Evidence / gap |
|---|---|---|---|
| ML-1 | Spend classification: text classifier + embedding similarity | **PARTIAL** | Keyword/taxonomy rule classifier (`svc/spend.py:classify_text`) with confidence and steward queue below 0.80. **No ML model and no embeddings.** D9: accuracy 0.9936 overall; curated set 0.80; **auto-apply precision 0.857, below the proposed 0.95 gate (FAIL)**. |
| ML-2 | Demand forecast: gradient boosted + seasonal baseline | **PARTIAL** | Exponential smoothing `demand-es-v1` (alpha 0.3, `svc/forecasting.py`). D9 MAPE h1 = 0.037 on 45 points. **No gradient-boosted model.** |
| ML-3 | Material duplicate score: Siamese embedding + rules | **PARTIAL** | difflib plus Jaccard on description, combined with MPN, attribute and classification weights (`svc/mdm.py:32–35`). **No embedding model.** Supplier dedup precision 0.83 < 0.9 gate (FAIL). |
| ML-4 | Should-cost: parametric models by commodity | **PARTIAL** | One parametric model, die-casting only (`svc/sourcing.py:should_cost`) |
| ML-5 | Late-delivery probability classifier | **NOT DONE** | The value is read from `twin_snapshot.late_delivery_prob` (seeded, 4 rows); no model |
| ML-6 | Supplier risk: scorecard + anomaly detection | **PARTIAL** | Threshold rules (SUPPLIER-RISK); **no anomaly detection** |
| ML-7 | Invoice exception cause: rules + classifier | **PARTIAL** | Rules only (`svc/payables.py:match`, suggested actions) |
| ML-8 | Contract redline: LLM with playbook retrieval | **PARTIAL** | Deterministic playbook comparison (CLM-PLAYBOOK positions STANDARD/FALLBACK/NON_STANDARD); **no LLM** |
| AGT-1 | Agent registered with purpose, input events, tools/scopes, default autonomy, value/category limits, run-as role | **DONE** | `plat/agents.py:CATALOGUE` (15 agents × 8 tenants = 120 rows): value limit, categories, run_as_role. "Input events" are not registered. |
| AGT-2 | Before any tool call, the guard checks role permission, **SoD**, autonomy, value limit and kill switch; denied calls become L2 drafts | **PARTIAL** | `agents.guard` checks kill switch, level, role scope, value, category and acceptance rate, **but not SoD** (SoD applies only through the underlying command's `sod.guard`). **It is called at only 2 sites** (Touchless PO, Spend Classification). |
| AGT-3 | Every run stores inputs, evidence IDs, model/prompt version, output, confidence, action, feedback | **DONE** | `agent_run` (490 rows), `agents.log_run`, `POST /v1/recommendations/{id}/feedback` |
| AGT-4 | Kill switch per agent and per tenant; automatic suspension on low acceptance or drift | **PARTIAL** | Per-agent kill switch in each tenant (`PUT /v1/agents/{code}/kill-switch`). Suspension below min acceptance (70%) after ≥ 20 feedback events is built. **No tenant-wide switch and no drift detection** (the runbook `model-drift.md` exists but no code backs it). |
| CP-1 | Copilot answer contract (answer, evidence, confidence, explanation, recommendedAction, permission) | **DONE** | `svc/copilot.py:_contract`; D9 completeness 1.0 on 40 questions (gate 0.99) |
| CP-2 | Retrieval tenant-scoped and permission-filtered before the model sees text | **DONE** | Runs inside an RLS transaction, filtered by scopes; supplier users see only their own documents |
| CP-3 | PII and bank data redacted at the gateway; prompts/responses logged with per-tenant retention | **PARTIAL** | No gateway, so no redaction. Questions are logged as COPILOT agent runs (`api/insight.py:39`), but **no retention policy applies to them**. |
| CP-4 | Numbers computed by tools, not by the model | **DONE** | SQL aggregates; there is no model |

### TD §14 Security & compliance

| ID | Control | Status | Evidence / gap |
|---|---|---|---|
| SEC-ID | SSO via SAML/OIDC; MFA mandatory for approvers, finance and admins; supplier users invited with MFA | **PARTIAL** | OIDC is DONE (`plat/oidc.py`); **SAML is missing**. TOTP MFA is built (`plat/mfa.py`), but **rule MFA has `enforce=false` in all 8 tenants** (DB). Invited supplier users are not required to enrol MFA (`svc/invitations.py`). |
| SEC-AZ | RBAC + ABAC (company code, plant, category, value band) evaluated per request | **PARTIAL** | RBAC: 20 roles with scopes (`plat/auth.py`). ABAC is enforced **only on workflow tasks** (`plat/workflow.py:_can_work_as`: cost object, plant, category, steward domain). `auth.check_value_limit` and `check_attr` are defined but **never called**, so commands are not restricted by company code, plant or value band. |
| SEC-SOD | SoD SOD-01..07 checked at command time for humans and agents; conflicts block or require mitigating approval | **PARTIAL** | 8 rules (SOD-01..07 plus 02a) guarded at command time (`plat/sod.py:guard`). Guarded actions: PO_CREATE, GR_POST, INVOICE_POST, PAYMENT_APPROVE, SOURCING_AWARD, MATERIAL_STEWARD_APPROVE, SAVINGS_VALIDATE, INVOICE_EXCEPTION_APPROVE. **MITIGATION mode just raises 409; there is no mitigating-approval path.** |
| SEC-DP | TLS 1.3; AES-256 at rest; field-level encryption with per-tenant keys; masked display | **PARTIAL** | Fernet plus HKDF per tenant (`plat/crypto.py`); GSTIN and bank data masked. TLS and at-rest encryption come from the host (EXTERNAL). **No KMS and no key versioning or rotation.** |
| SEC-BANK | Bank-change fraud: dual finance approval, call-back, cooling-off before first payment, alert on change + invoice within 30 days | **DONE** | `bankApprovers 2`; `POST /v1/bank-changes/{n}/callback`; `coolingOffHours 72` (`svc/supplier.py:524`, payment run skip `svc/payables.py:961`); `svc/risk.py:88` 30-day alert |
| SEC-AUD | Append-only, hash-chained audit: who/what/when/why, before/after, evidence, rule version, AI ref | **DONE** | `plat/audit.py` (advisory lock, sha256 chain), `REVOKE UPDATE, DELETE` (0002), `GET /v1/audit/verify`; 3,423 events |
| SEC-APP | OWASP ASVS L2; SAST/DAST/SCA in CI; dependency pinning; secrets in Secret Manager | **PARTIAL** | CodeQL, gitleaks, pip-audit gate and npm audit (`security.yml`, `ci.yml`). **ZAP is report-only** (`continue-on-error: true`). ASVS gaps per `PIC_Production_Readiness.md`: no breached-password check, no key rotation, no threat model. Frontend dependencies use `^` ranges (not pinned). Secret Manager via `deploy/k8s/external-secret.yaml` is EXTERNAL. |
| SEC-PRIV | DPDP: purpose limitation, India residency default, retention and deletion workflows | **PARTIAL** | Export, erasure (pseudonymisation) and a retention report (`svc/privacy.py`). **No retention purge job.** Retention periods are proposals that need legal review. Residency is currently Neon Singapore (decision needed). |

### TD §15 Non-functional requirements (target vs measured)

| ID | NFR | Target | Measured | Status | Evidence / gap |
|---|---|---|---|---|---|
| NFR-AV | Availability | 99.9% transactional, 99.5% analytics | — | **EXTERNAL** | Not deployed. K8s manifests have 2+ replicas, PDB and HPA; the real figure depends on the hosting plan. |
| NFR-P95 | Transactional API latency | P95 < 400 ms | not measured | **NOT DONE** | k6 scripts in `tests/load/*.js`; no run recorded (k6 binary downloaded, no results) |
| NFR-PR | PR form load | < 2 s | not measured | **NOT DONE** | No frontend performance test |
| NFR-CUBE | Spend cube on 50 M lines | < 3 s | not measured | **NOT DONE** | Postgres; SPD-01 loads every line into memory (`svc/spend.py:overview`). `volume_gen --measure` was never run at scale. |
| NFR-MRP | Net-change run, 50,000 materials | < 10 min (600 s) | **681 s** best (regenerative, 1 plant, local PG; `scratchpad/after_50k.log`); later reruns 1,105 s and 1,615 s; 5,000 materials in 179 s | **NOT DONE** | Target missed by 13% on the best run, and by 84–169% on reruns. `tools/perf_mrp.py`, migration 0006 indexes, bulk inserts. |
| NFR-SCALE | Concurrency and volume | 10,000 concurrent users per tenant; 5 M invoices/year | not measured | **NOT DONE** | `tools/volume_gen.py` can generate 5 M invoices; no run recorded |
| NFR-SEC | SSO, MFA, RBAC+ABAC, field encryption, ASVS L2 | — | — | **PARTIAL** | See SEC-ID, SEC-AZ, SEC-APP |
| NFR-TEN | Logical isolation with RLS; per-tenant keys | — | RLS forced on 112/115 tables | **DONE** | Per-tenant derived keys (not KMS; see SEC-DP) |
| NFR-AUD | Immutable audit log, 10-year retention configurable | 10 y | default **8 y** | **PARTIAL** | Immutable is DONE. `svc/privacy.py` CATEGORIES default to 8 years; configurable via PRIVACY-RETENTION; **no archival or purge job**. |
| NFR-RES | India region by default; tenant-level residency | India | Neon ap-southeast-1 (Singapore) | **EXTERNAL** | Decision needed. Terraform asia-south1 is ready. **Tenant-level residency (per-tenant DB or region) is not built.** |
| NFR-A11Y | Accessibility | WCAG 2.1 AA | not audited | **NOT DONE** | No axe/Lighthouse checks; only 15 aria/role attributes in the shared components |
| NFR-DR | Recovery | RPO 15 min, RTO 4 h | not tested | **EXTERNAL** | `docs/runbooks/backup-restore-dr.md`; needs Neon PITR plan and a DR drill |
| OBS-1 | OTel traces web → API → services → workflow → connectors; traceId in every error | — | — | **PARTIAL** | traceparent propagated, and traceId is in every problem+json. OTLP export needs a collector (EXTERNAL). Connectors do not add outbound trace headers. |
| OBS-2 | Golden signals per service; business SLOs (PR approval latency, touchless, match, posting) | — | — | **DONE** | `/metrics`, `pic_slo_*` gauges (`plat/observability.py:468–491`); `tests/test_production.py` |
| OBS-3 | Runbooks: dead-lettered postings, workflow incidents, MRP failure, model drift | — | — | **DONE** | `docs/runbooks/` (10 files) |
| OBS-4 | Blue/green deploys; migrations backward-compatible for one release | — | — | **PARTIAL** | K8s `rollingUpdate` (not blue/green); Vercel deploys are atomic. No automated check that migrations are backward-compatible. |

### TD §16 Front-end implementation

| ID | Item | Status | Evidence / gap |
|---|---|---|---|
| FE-1 | App Router workspace routes per module; screen IDs map to route components | **PARTIAL** | `/pic/mrp`, `/requisitions`, `/sourcing`, `/contracts`, `/purchase-orders`, `/receiving`, `/invoices`, `/spend`, `/admin` (45 pages). 57 of 58 screens are present. **SPD-08 Savings & Pipeline Tracker has no screen.** CLM-02 and INV-02 sit inside detail pages without their ID. |
| FE-2 | AlphaHelion tokens; shared status chips and **lifecycle strip** | **PARTIAL** | Tokens and `StatusChip` are present. **No lifecycle strip.** The header shows a hard-coded "Manufacturing template" for every tenant (`fe/components/pic/WorkspaceShell.tsx:183`), which is a bug for CON/ITS/LOG/HLT/GEN. |
| FE-3 | Object page: header, tabs (Lines · Approvals · Documents · Lineage · Audit), action bar; commands carry idempotency keys | **PARTIAL** | `fe/components/pic/object.tsx:ObjectPage` has Lines, Process, Lineage and Audit tabs plus a TaskPanel, used by 12 pages. **No generic Approvals or Documents tabs.** The client sends an Idempotency-Key on every POST. |
| FE-4 | Supplier portal as a separate Next.js app with supplier scopes | **PARTIAL** | Portal is `/pic/portal` **inside the same app**, restricted by the SUPPLIER_USER role (deviation; project DD-09 planned a second app) |
| FE-5 | BPMN viewer (bpmn-js) in the process tab showing the live token | **NOT DONE** | `ProcessPath` renders a step list; `bpmn-js` is not a dependency |

### TD §17 Testing strategy

| ID | Layer | Status | Evidence / gap |
|---|---|---|---|
| TST-U | Unit: 85% coverage on domain logic (Jest/Pytest) | **PARTIAL** | 357 pytest functions (389 cases) in `tests/`. **No coverage measurement or gate** in `ci.yml`. **No frontend unit tests.** |
| TST-C | Contract: Pact, schema registry compatibility, must pass to merge | **NOT DONE** | None |
| TST-I | Integration: workflow + services + DB with RLS (nightly) | **DONE** | pytest against PG 16 with RLS on every push (`ci.yml`). Camunda test N/A. |
| TST-E2E | E2E-01..n through the UI with Playwright (release gate) | **NOT DONE** | No Playwright suite in the repo. The E2E-01 chain is exercised only as backend tests (`tests/test_signature_case.py`). The test workbook /03 has not been supplied. |
| TST-SEC | Security: RLS, SoD, authZ, OWASP/ZAP (release gate) | **PARTIAL** | `test_controls.py` and `test_review_platform.py`. ZAP is report-only. |
| TST-PERF | Performance: k6, cube benchmarks per release | **PARTIAL** | k6 scripts and the `perf_mrp` / `volume_gen` harnesses exist. Only the MRP run is recorded, and it failed. |
| TST-AI | AI evaluation before autonomy increases | **DONE** | `tools/ai_eval.py`, D9 sets, `tests/test_datasets_ai_eval.py`. Two gates fail (see ML-1, ML-3). |

### TD §18 Delivery plan & Definition of Done

| ID | Item | Status | Evidence / gap |
|---|---|---|---|
| PH-0 | Foundation exit: approval flow E2E; RLS suite green | **DONE** | `tests/test_controls.py`, `test_workspace_api.py` |
| PH-1 | MVP P2P exit: E2E-01 manual PR path + idempotency tests, **with SAP/Tally connector** | **PARTIAL** | Backend E2E and idempotency tests pass. The SAP connector is a simulator; Tally is tested on mocks only. |
| PH-2 | Source & Contract exit: RFQ-2231 → SA-5520 → PO inheritance | **DONE** | `tests/test_signature_case.py`; DB PO-77410 with contract SA-5520 |
| PH-3 | Plan & Predict exit: MR-1043 netting; agent autonomy tests | **DONE** | MR-1043 = 9,000; agent guard and kill-switch tests (`test_intelligence_modules.py`) |
| PH-4 | Industry packs exit: industry test sheets green | **PARTIAL** | Five pack test files pass (`test_datasets_industry_*.py`). The customer's industry test sheets (workbook /03) have not been supplied. |
| DOD-1 | Acceptance criteria and linked test cases pass; screen matches blueprint ID and states | **PARTIAL** | No mapping to the test workbook (not supplied); 57/58 screens |
| DOD-2 | Audit and domain events emitted **and documented in the schema registry** | **PARTIAL** | Events are emitted; no registry, no event schema docs |
| DOD-3 | Rules externalised (no hard-coded thresholds); SoD checks covered by tests | **PARTIAL** | Residual hard-codes (TD-1.1f); SoD tests DONE |
| DOD-4 | OpenAPI updated; idempotency and concurrency handled; problem+json | **PARTIAL** | Idempotency on 26/138 POSTs; ETag only on POs |
| DOD-5 | WCAG 2.1 AA check and performance budget met | **NOT DONE** | No accessibility audit; NFRs not measured or failed |
| DOD-6 | Runbook and dashboards updated for each new failure mode | **PARTIAL** | Runbooks DONE; **no dashboards** (only a ServiceMonitor) |

### TD §19 Appendix

| ID | Item | Status | Evidence / gap |
|---|---|---|---|
| APX-1 | PR line payload (itemType FREE_TEXT, materialGroup, priceEstimate, accountAssignment, purchaseType, reusable, mdmRequestId) | **DONE** | `pr_line` columns match; `api/plan_request.py` item_type pattern |
| APX-2 | PO DDL (status CHECK, rule_set_version, risk_score, touchless, total_minor, UNIQUE tenant+number+version) | **DONE** | `ck_purchase_order_status`; `purchase_order` columns |
| APX-3 | Audit event (onBehalfOf, before/after, ruleSetVersion, aiRef, prevHash, hash) | **DONE** | `audit_event` columns |

---

## Part 2 — Product Blueprint

### BP §2.1 Fourteen-stage lifecycle

| ID | Stage | Status | Evidence / gap |
|---|---|---|---|
| LC-1/2 | Demand planning; MRP run | **DONE** | MRP-01..04 (`fe/app/pic/mrp/**`), `svc/forecasting.py`, `svc/planning.py` |
| LC-3/4 | Purchase requisition; guided buying | **DONE** | REQ-01..04, `svc/requisition.py:search` (P03 order) |
| LC-5/6 | Strategic sourcing; supplier selection under capacity and risk | **PARTIAL** | Capacity is DONE; risk constraints are missing (ALG-9.3) |
| LC-7 | Contract management | **DONE** | CLM screens; `svc/contract.py`, `svc/amendments.py` |
| LC-8/9 | Purchase order; supplier fulfilment | **DONE** | PO-01..04, RCV-01 |
| LC-10 | GR / service entry | **DONE** | RCV-02..04 |
| LC-11/12 | Invoice matching; finance integration | **PARTIAL** | Matching is DONE; real ERP posting is simulator-only (INT-SAP) |
| LC-13 | Spend analytics | **PARTIAL** | Built on Postgres; scale not proven (AD-04) |
| LC-14 | Predictive intelligence | **PARTIAL** | Heuristic models (TD §13) |

### BP §3 Core principles P01–P14

| ID | Principle | Status | Evidence / gap |
|---|---|---|---|
| P01 | Traceable purpose: purpose code, requester, cost object, origin on PR/PO/contract; no submit without purpose | **DONE** | `requisition.purpose_code`, `purchase_order.purpose_code`; submit guard in `svc/requisition.py` |
| P02 | Two demand origins, stored and never overwritten | **DONE** | Trigger `pic.protect_requisition_origin` (migration 0002) |
| P03 | Reuse before create: contract → catalogue → material → free text | **DONE** | `svc/requisition.py:search` (l.82–114) channel order; lines need the search result (l.183, 191). The Guided Buying **agent** is not wired (see AG-03). |
| P04 | Free text never auto-creates a material | **DONE** | DB CHECK on pr_line; promotion only via `promote-material` |
| P05 | Governed material creation: request → duplicate check → classification → stewards → ERP sync | **DONE** | F9; `svc/mdm.py` |
| P06 | Evidence-based sourcing: approved requirements, qualified invitees, published criteria, authorised award | **DONE** | `svc/sourcing.py` (G-2, G-3, award approval) |
| P07 | PO inherits PR, sourcing, contract, price, Incoterms, terms, tolerances; overrides flagged and justified | **DONE** | `svc/order.py:_create_po` (`inherited`, `overrides`, P07 rule violations) |
| P08 | Purchase-type rules (7 types) | **DONE** | `PURCHASE-TYPE-MATRIX` rule; D2 cases (see BP §22) |
| P09 | Approvals and SoD on awards, contracts, master data, payments | **PARTIAL** | Approval chains and SoD are DONE. The SoD mitigation path is missing (SEC-SOD). |
| P10 | Complete lineage, including integration history | **DONE** | `document_link`, `integration_message`, Lineage and Audit tabs |
| P11 | Explainable, governed AI: evidence, confidence, model version, permission; AI never commits spend | **DONE** | Answer contract (CP-1); agent runs log model version and evidence |
| P12 | Three kinds of savings; only realised reaches P&L | **DONE** | `savings_ledger_entry` types NEGOTIATED / AVOIDANCE / REALISED with a `counts` flag |
| P13 | Exactly-once ERP posting: idempotency keys, outbox, reconciliation | **PARTIAL** | Keys and outbox are DONE. Reconciliation is manual, not scheduled (INT-12.2-5). Only the simulator has been proven. |
| P14 | Configurable by tenant, company code, plant, category, purchase type | **PARTIAL** | Rule scope is DONE. Configurable mandatory fields and editable workflows are missing (G-1, F-ver). |

### BP §4 Roles and §4.1 SoD

| ID | Item | Status | Evidence / gap |
|---|---|---|---|
| ROLE-1..15 | 15 roles: Requester, Cost-object owner/Approver, MRP controller, Buyer, Category manager, Supplier manager, Contract manager/Legal, Master-data steward, Receiver, Service owner, AP clerk, Finance controller, CPO/Procurement head, Supplier user, Tenant admin | **DONE** | `plat/auth.py:ROLE_SCOPES` has 20 roles covering all 15, plus DEPT_HEAD, LEGAL, QUALITY_INSPECTOR and CAPEX_COMMITTEE. Seeded users in every tenant. |
| ROLE-ASSIGN | SoD also checked at role assignment | **DONE** | `svc/admin.py:21` incompatible role pairs |
| SOD-01 | Create supplier master × create PO for the same supplier (High) | **DONE** | `seed/reference.py:SOD_RULES`; `sod.guard("PO_CREATE")` |
| SOD-02 | Change bank details × approve payment / post invoice (Critical) | **DONE** | SOD-02 and SOD-02a; PAYMENT_APPROVE and INVOICE_POST guards |
| SOD-03 | Create PO × post GR for the same PO (High) | **DONE** | GR_POST guard |
| SOD-04 | Create PO × approve invoice exception for the same PO (High) | **DONE** | INVOICE_EXCEPTION_APPROVE guard |
| SOD-05 | Award event × score the same event as sole evaluator (Medium) | **DONE** | `plat/sod.py:_sole_evaluator` |
| SOD-06 | Request material × approve as steward (Medium) | **DONE** | MATERIAL_STEWARD_APPROVE guard |
| SOD-07 | Initiate savings × validate the same savings (High) | **DONE** | SAVINGS_VALIDATE guard |
| SOD-AGT | An agent inherits the SoD rules of its role | **PARTIAL** | Holds only through the underlying commands; the agent guard has no SoD check (AGT-2) |

### BP §6.1 Screen design conventions

| ID | Convention | Status | Evidence / gap |
|---|---|---|---|
| UX-1 | Left nav grouped by lifecycle; header with tenant, industry template and Copilot; **lifecycle strip in the footer** | **PARTIAL** | Nav groups (Decide, Plan & request, …) in `WorkspaceShell.tsx`. **The template label is hard-coded "Manufacturing".** **No lifecycle strip.** |
| UX-2 | Object pages: header, tabs (Lines · Approvals · Documents · Lineage · Audit), action bar | **PARTIAL** | See FE-3 |
| UX-3 | Worklists: filter chips, saved views, SLA badges, bulk actions, side panel | **PARTIAL** | Lists and task SLA due dates exist. **No saved views, and no bulk actions** were found in `fe/app/pic`. |
| UX-4 | AI surfaces: inline recommendation with "Explain"; accept/reject logged | **DONE** | Recommendations with feedback (`POST /v1/recommendations/{id}/feedback`), agent console |
| UX-5 | State colours green/amber/red/blue | **DONE** | `StatusChip` |
| UX-6 | WCAG 2.1 AA, keyboard-complete, colour never the only signal | **NOT DONE** | No audit (NFR-A11Y) |

### BP §7 M01 Spend & Category Intelligence

| ID | Item | Status | Evidence / gap |
|---|---|---|---|
| M01-C1 | Multi-ERP spend cube (PO, invoice, contract, consumption) | **PARTIAL** | Cube built from posted invoices plus ERP history only (`svc/savings.py:_spend`, `spend_cube`). **No PO commitments, consumption or multi-ERP source tagging.** |
| M01-C2 | Configurable taxonomy (UNSPSC or own) with ML auto-classification and steward review | **PARTIAL** | Taxonomy nodes (25–30 per tenant) and UNSPSC mapping (56); steward queue below 0.80. Classification is rule-based, not ML (ML-1). |
| M01-C3 | Addressable / contracted / non-contracted / unmanaged | **DONE** | `svc/spend.py:overview` (addressable, managed, contracted, maverick) |
| M01-C4 | Duplicate-supplier and fragmented-purchase detection | **DONE** | SPD-03 clusters (`svc/spend.py:433+`); SPLIT_PO maverick rule |
| M01-C5 | Concentration, price variance, off-contract, aggregation opportunities | **PARTIAL** | HHI, off-contract and opportunities exist. **The cube has no price-variance or aggregation measure.** |
| M01-C6 | Category strategy, annual plan, category budgets | **DONE** | `category_plan` (15), `POST /v1/category-plans`, CATEGORY-BUDGET check at requisition |
| M01-C7 | Sourcing pipeline with forecast vs realised savings and cost avoidance | **PARTIAL** | Savings register/waterfall exist; **no SPD-08 pipeline tracker** |
| M01-C8 | Actual vs budget, contract, historical price, benchmark | **PARTIAL** | Budget and contract compliance exist; **no external benchmark** |
| M01-C9 | Spend forecast by category, supplier, plant, period | **DONE** | `GET /v1/spend/forecast` (80% band, MAPE 0.035) |
| M01-D | Cube dimensions (cat L1–L4, supplier parent/child, plant, cc, cost centre, WBS, material group, period, currency doc/group) | **PARTIAL** | Dimensions: category, supplier, plant, company_code, period, material_group, cost_object. **No supplier parent/child, and no document/group currency.** |
| M01-R1 | Spend de-duplicated across PO and invoice via lineage | **DONE** | Spend rows come only from posted invoices, so there is no double count |
| M01-R2 | Classification < 0.80 confidence → steward queue | **DONE** | SPEND-GOVERNANCE `classificationThreshold 0.80`; `classification_review` (67) |
| M01-R3 | Intercompany excluded from addressable spend | **DONE** | `svc/spend.py:_apply_addressable` (IC-TRANSFER) |
| M01-R4 | Maverick rules tenant-configurable; each hit has an owner and disposition | **DONE** | `maverick_rule` (9 codes per tenant, incl. PO_AFTER_INVOICE, SPLIT_PO, NON_CATALOGUE, OFF_CONTRACT_PRICE, ONE_TIME_VENDOR); `POST /v1/spend/maverick-hits/{id}/disposition`; 446 hits |
| M01-S | Screens SPD-01..09 | **PARTIAL** | `fe/app/pic/spend/page.tsx` tabs SPD-01..07 and 09; **SPD-08 missing** |
| M01-K | KPIs: spend under management, contract coverage, maverick %, classification accuracy, realisation rate | **PARTIAL** | The first four are computed (`svc/spend.py`, `svc/insight.py`). **Savings realisation rate % is not computed.** |

### BP §8 M02 Demand Planning & MRP

| ID | Item | Status | Evidence / gap |
|---|---|---|---|
| M02-C1 | Demand inputs: forecast, customer orders, project/WBS, reorder points, consumption | **PARTIAL** | `demand_element.type` FORECAST / SALES_ORDER / RESERVATION / WBS_DEMAND; forecasts from consumption. **No reorder-point (Kanban) planning.** |
| M02-C2/3 | Netting formula; lot sizing incl. pack rounding | **DONE** | ALG-9.1 |
| M02-C4 | Lead-time scheduling with PDT, GR time and calendar | **DONE** | `_Reads.release_date` |
| M02-C5 | Exception messages (reschedule in/out, cancel, past due, below safety) | **DONE** | `svc/planning.py:net_material` |
| M02-C6 | Planner workbench with firming and conversion | **DONE** | `POST /v1/planned-orders/{ref}/firm`, `/convert`; MRP-02 |
| M02-C7 | Simulation before live run; in-platform or ERP MRP | **DONE** | Mode SIMULATION (MR-1044 SIMULATED); ERP import (MR-1048) |
| M02-C8 | Source list and quota applied at conversion | **DONE** | `svc/source.py:determine` |
| M02-D | Run modes net-change (default), regenerative, simulation | **DONE** | `planning.run` validates the mode |
| M02-R1 | Only materials with MRP type active are planned | **DONE** | `Material.mrp_type == "PD"` (`svc/planning.py:282`) |
| M02-R2 | Firmed planned orders not changed by later runs | **DONE** | RESCHEDULE messages instead of changes |
| M02-R3 | Conversion inherits material, qty, date, plant, sloc, source | **DONE** | `svc/planning.py:convert` (l.399+) |
| M02-R4 | Simulation never creates documents | **DONE** | `mode != "SIMULATION"` guards (l.298, 322, 342) |
| M02-S | Screens MRP-01..04 | **DONE** | `fe/app/pic/mrp/page.tsx`, `mrp/[ref]`, `mrp/forecast` |
| M02-K | KPIs: MAPE, exception backlog, PO conversion lead time, stock-outs, days of cover | **PARTIAL** | Only MAPE (`svc/forecasting.py`). **The other four are not computed.** |
| M02-NFR | 50,000 materials < 10 min | **NOT DONE** | NFR-MRP (681 s best) |

### BP §9 M03 Master Data Governance

| ID | Item | Status | Evidence / gap |
|---|---|---|---|
| M03-C1 | New material request with mandatory classification | **DONE** | `svc/mdm.py`, MDM-01 |
| M03-C2 | Duplicate detection: fuzzy description, MPN, attributes | **DONE** | MDM-DUP weights; F9-04 |
| M03-C3 | Steward work queues by domain (purchasing, quality, finance, plant) | **DONE** | 4 parallel domain tasks; MDM-02 |
| M03-C4 | Field-level ownership and approval by material type | **PARTIAL** | Domain-level approval only. **No per-field ownership by material type.** |
| M03-C5 | **Material** change requests with before/after and impact on open POs, contracts, catalogues | **NOT DONE** | Only supplier master changes exist (`svc/master_changes.py`). No change request for an existing material. |
| M03-C6 | Supplier master: registration, bank verification, tax IDs, sanctions, duplicate check | **DONE** | F8; MDM-04 tax/address/contact (`svc/master_changes.py`, two approvers, never the requester) |
| M03-C7 | ERP sync with status and error handling | **PARTIAL** | Status, retry and dead-letter are DONE. The target is the SAP simulator only (INT-SAP). |
| M03-C8 | Golden-record history and audit | **DONE** | Audit trail; F9-08 "golden record live" |
| M03-R1 | Free-text line promotable; PR keeps its line; material linked after approval | **DONE** | `promote-material` route; `pr_line.linked_material_id` |
| M03-R2 | Bank changes: two finance approvers, never the requester | **DONE** | SEC-BANK |
| M03-R3 | Blocked at ≥ 0.92 unless a steward overrides with reason | **DONE** | `POST /v1/materials/requests/{ref}/override` |
| M03-R4 | Sync to ERP only after final approval | **DONE** | `svc/mdm.py:251` (SYNCED_TO_ERP after APPROVED) |
| M03-S | Screens MDM-01..04 | **DONE** | `fe/app/pic/materials/**`, `suppliers/[code]/master-data.tsx` |
| M03-K | KPIs: request cycle time, duplicate rate, first-time-right, bank-fraud attempts blocked | **NOT DONE** | None computed (bank-change alerts exist as risk signals) |

### BP §10 M04 Requisitioning & Guided Buying

| ID | Item | Status | Evidence / gap |
|---|---|---|---|
| M04-C1 | Intake "What do you need?" across contracts, catalogues, materials, policy | **DONE** | `GET /v1/guided-buying/search` |
| M04-C2 | Hosted catalogues and punch-out (cXML/OCI) | **DONE** | `catalogue_item`; punch-out (INT-PUNCH; real suppliers EXTERNAL) |
| M04-C3 | Free-text and service requests **with templates** (services, IT, marketing, facilities) | **PARTIAL** | Free text and SERVICE lines exist; **no request templates** |
| M04-C4 | Account assignment: cost centre, WBS, internal order, asset, **sales order** | **PARTIAL** | COST_CENTER / WBS / ORDER / ASSET (`models/platform.py:63`); **no sales-order account assignment** |
| M04-C5 | Budget check (hard/soft) and commitment | **DONE** | BUDGET rule; `budget_commitment` (33) |
| M04-C6 | Policy guidance: preferred supplier, required quotes by band, channel | **DONE** | QUOTE-POLICY (each quote needs supplier, reference and date); `preferred_supplier_id` |
| M04-C7 | Approval chain by value, category, cost object, risk | **DONE** | DMN-01, one task per cost object |
| M04-C8 | Converted MRP PRs in the same buyer queue | **DONE** | `GET /v1/buyer-workbench` (REQ-04) |
| M04-R1 | Search order enforced | **DONE** | P03 |
| M04-R2 | Free text above the configurable value needs 3 quotes or a sourcing event | **DONE** | QUOTE-POLICY `oneQuoteBelow 2 L` |
| M04-R3 | Budget hard stop on capex; soft stop with justification on opex | **DONE** | BUDGET `hardFor ASSET,WBS`, `softFor COST_CENTER,ORDER` |
| M04-R4 | PR changes after approval restart approval only on value/account/supplier change | **DONE** | `svc/requisition.py` reapprove (code review fix 7) |
| M04-S | Screens REQ-01..04 (approval inbox mobile-friendly) | **DONE** | `fe/app/pic/requisitions/**`, `tasks`, `buyer`. Mobile-friendly only through responsive layout; not tested. |
| M04-K | KPIs: catalogue/contract channel %, PR approval cycle time, free-text %, budget-blocked PRs | **PARTIAL** | Only PR approval cycle (`svc/insight.py` avgApprovalHours) |

### BP §11 M05 Strategic Sourcing

| ID | Item | Status | Evidence / gap |
|---|---|---|---|
| M05-C1 | Event types RFI, RFQ, RFP, reverse auction, multi-round, **lot/item bidding** | **PARTIAL** | RFI/RFQ/RFP/REVERSE_AUCTION types (`api/source_contract.py:44`); rounds and live auction with soft close (`svc/auction.py`). **One item per event, so no lot/item bidding.** RFI/RFP share the RFQ flow (no technical envelope). |
| M05-C2 | Requirement bundling from PRs, MRP demand or category plan | **PARTIAL** | One requisition line per event; **no bundling** |
| M05-C3 | Invitation from qualified list with segment and risk filters | **PARTIAL** | Eligibility is enforced; `svc/sourcing_strategy.py` recommends invitees. **No segment or risk filter UI.** |
| M05-C4 | Weighted scoring: price/TCO, quality, delivery, technical, ESG, risk | **PARTIAL** | Criteria are configurable per event; **no ESG or risk score source** |
| M05-C5 | Should-cost and benchmarks; TCO components | **PARTIAL** | TCO is DONE; should-cost covers one commodity (ML-4) |
| M05-C6 | Award scenarios: lowest cost, best value, split, capacity-constrained | **DONE** | `svc/sourcing.py:build_scenarios` |
| M05-C7 | Award approval and notification; outcome flows to contract or PO | **DONE** | AWARD-APPROVAL; `contract-from-award` consumer; notifications |
| M05-C8 | Sealed bids, clarifications, Q&A log | **DONE** | Sealing (G-3); `sourcing_clarification` with endpoints |
| M05-R1 | Invite only Qualified (or Conditional with waiver) | **DONE** | `_require_eligible` |
| M05-R2 | Bids sealed until close; early access blocked and logged | **DONE** | G-3 |
| M05-R3 | Weights locked at publish | **DONE** | `weights_locked` |
| M05-R4 | Non-lowest award needs written rationale | **DONE** | `svc/sourcing.py:558` |
| M05-R5 | Award above threshold needs category head + finance | **DONE** | AWARD-APPROVAL ≥ ₹50 L: CATEGORY_MANAGER, CPO, FINANCE_CONTROLLER |
| M05-S | Screens SRC-01..05 | **DONE** | `fe/app/pic/sourcing/**` |
| M05-K | KPIs: sourcing cycle time, competitive events %, negotiated savings %, bidders per event | **PARTIAL** | Negotiated savings is computed. The others appear only as list fields (bidders); **no cycle-time KPI**. |

### BP §12 M06 Supplier Lifecycle & Performance

| ID | Item | Status | Evidence / gap |
|---|---|---|---|
| M06-C1 | Self-registration and invitation; duplicate and sanctions screening | **DONE** | `svc/invitations.py`; `/public/invitations/{token}/register`; screening disposition gate |
| M06-C2 | Qualification by category: questionnaires, certificates, audits, sample approval (PPAP) | **DONE** | SUPPLIER-QUAL (`minQuestionnaireScore`, `minAuditScore`, `sampleApprovalRequired`) |
| M06-C3 | Status model per category | **DONE** | SM-SUP |
| M06-C4 | Segmentation (strategic, leverage, bottleneck, routine) and risk tiering | **PARTIAL** | Kraljic lives on the category plan; `supplier.segment` and `risk_tier` are plain fields. **No supplier segmentation logic.** |
| M06-C5 | Scorecards: OTIF, PPM, responsiveness, invoice accuracy, ESG | **PARTIAL** | OTIF, PPM and invoice accuracy (`scorecard`, 40 rows). **No responsiveness, no ESG.** |
| M06-C6 | Risk monitoring: financial, geographic, compliance, single-source, cyber | **PARTIAL** | Financial tier, compliance (sanctions, certificates), delivery and bank-change signals. **No geographic, single-source or cyber signals.** |
| M06-C7 | Corrective action and development plans | **PARTIAL** | CAPA open → respond → verify (`/capas`). **No development plans.** |
| M06-C8 | Supplier portal: profile, documents, RFQs, POs, ASNs, invoices | **DONE** | `fe/app/pic/portal/page.tsx`, `/portal/profile` |
| M06-D | SLM-01 reads twin capability, evidence, free capacity; scorecards write back | **PARTIAL** | INT-TWIN (local table, no Twin connector) |
| M06-R1 | Only Qualified/Preferred receive POs unless one-time-vendor policy | **PARTIAL** | Not-qualified suppliers add risk points and block touchless; one-time vendor is flagged as maverick. **There is no hard block on PO release** to a not-qualified supplier (only Blocked is refused). |
| M06-R2 | Expired mandatory certificate → Conditional automatically | **DONE** | G-9 |
| M06-R3 | Blocking stops new POs; open POs flagged for buyer decision | **DONE** | `svc/supplier.py:block` (`openPosFlagged`, payment block) |
| M06-R4 | Scorecards recompute **monthly** and on every GR/invoice event | **PARTIAL** | Event-driven recompute is DONE (consumers). **No monthly job.** |
| M06-S | Screens SLM-01..05 | **DONE** | `fe/app/pic/suppliers/**`, `portal` |
| M06-K | KPIs: onboarding cycle time, qualified coverage %, OTIF, PPM, high-risk % | **PARTIAL** | Qualified coverage, OTIF, PPM and high-risk are computed; **onboarding cycle time is not** |

### BP §13 M07 Contract Lifecycle Management

| ID | Item | Status | Evidence / gap |
|---|---|---|---|
| M07-C1 | Contract types: master agreement, quantity, value, scheduling agreement, rate card, SOW, NDA | **PARTIAL** | The create API accepts only SCHEDULING_AGREEMENT, QUANTITY_CONTRACT and VALUE_CONTRACT (`api/governance.py:34`). Rate card and SOW are modelled as value-contract lines (ITS). **No master agreement or NDA type.** |
| M07-C2 | Clause library with fallback positions and risk scores | **DONE** | CLM-PLAYBOOK; `clause` (104 rows) |
| M07-C3 | Templates by category and **jurisdiction**; AI redline vs playbook | **PARTIAL** | Templates by type; deterministic redline. **No jurisdiction dimension, and no LLM** (ML-8). |
| M07-C4 | Approval workflow and e-signature | **EXTERNAL** | Approval is DONE. The e-sign provider adapter (`svc/contract.py:576`, `/esign/webhook`) needs `PIC_ESIGN_*`; until then signatures are internal with a document hash. |
| M07-C5 | Obligations, milestones, price indexation, **rebates** | **PARTIAL** | Obligations (34) and index resets are DONE. **No rebates.** |
| M07-C6 | Consumption tracking; alerts at 80/90/100% | **DONE** | `GET /v1/contracts/{ref}/consumption`; thresholds |
| M07-C7 | Renewal, expiry, termination | **DONE** | Timers; amendments (`svc/amendments.py`: variation, extension, termination) |
| M07-C8 | Contract compliance: off-contract buying and price leakage | **DONE** | `GET /v1/spend/compliance`; OFF_CONTRACT and OFF_CONTRACT_PRICE rules |
| M07-D | Indexation creates a new price-validity period each reset | **DONE** | `POST /v1/contracts/{ref}/index-resets`; `price_validity` (35) |
| M07-R1 | Only executed contracts referenced by POs | **DONE** | Source determination uses ACTIVE contracts with published validities |
| M07-R2 | PO price = contract price ± tolerance, or flagged | **DONE** | TD-5.2b |
| M07-R3 | Contract above threshold needs legal + finance | **DONE** | CONTRACT-APPROVAL ≥ ₹1 Cr: LEGAL, FINANCE_CONTROLLER, CPO |
| M07-R4 | Indexation never overwrites | **DONE** | New `price_validity` rows |
| M07-S | Screens CLM-01..04 | **DONE** | `fe/app/pic/contracts/**` (CLM-02 inside `[ref]`) |
| M07-K | KPIs: contract cycle time, leakage, expiring in 90 days, obligation on-time % | **PARTIAL** | Leakage and renewals calendar (`/contracts-renewals`); **no cycle-time or obligation on-time %** |

### BP §14 M08 Operational Purchasing

| ID | Item | Status | Evidence / gap |
|---|---|---|---|
| M08-C1 | Automatic PO from PR with source determination | **DONE** | `svc/order.py:create_from_requisition` + `svc/source.py` |
| M08-C2 | Manual PO, release order against contract, scheduling-agreement schedule lines | **DONE** | `po_schedule_line` (78), `PUT /purchase-orders/{ref}/lines/{n}/schedule` |
| M08-C3 | AI PO validation: price vs contract/history, supplier risk, split detection, risk score | **PARTIAL** | Contract-price deviation, split and risk are DONE. **No price check against history (last price).** |
| M08-C4 | Approval strategy by value, category, risk, deviation | **DONE** | PO-APPROVAL bands + deviation chain + change approval |
| M08-C5 | Transmission (portal, email, EDI/cXML) and confirmation | **EXTERNAL** | Portal is DONE. EDI/e-mail adapters need the gateway and SMTP. **cXML OrderRequest is not built.** |
| M08-C6 | Change orders with versioning and re-confirmation | **DONE** | G-6 |
| M08-C7 | Expediting with late-delivery probability | **PARTIAL** | `/expediting`, EXPEDITING agent. The probability comes from the seeded twin, not a model (ML-5). |
| M08-C8 | Touchless PO for low-risk lines | **DONE** | DMN-02; AXN touchless 9/23 = 39% |
| M08-R1 | PO price defaults from contract; deviation > tolerance needs justification | **DONE** | P07 |
| M08-R2 | Not released to a Blocked supplier | **DONE** | G-5 |
| M08-R3 | Split to dodge a threshold is detected and escalated | **DONE** | `svc/order.py:_split_pattern` (same supplier, material group and cost object within 7 days, below the ₹2 L band) → 25 risk points, not touchless, routed to approval |
| M08-R4 | Qty/price/date change after confirmation → new version and re-confirmation | **DONE** | G-6 |
| M08-S | Screens PO-01..04 | **DONE** | `fe/app/pic/purchase-orders/**` |
| M08-K | KPIs: touchless %, PO cycle time, confirmation within SLA, change rate | **PARTIAL** | Touchless, confirmation SLA and change rate exist; **no PO cycle time** |

### BP §15 M09 Fulfilment, GR & Service Entry

| ID | Item | Status | Evidence / gap |
|---|---|---|---|
| M09-C1 | ASN from portal/EDI with packing and batch data | **DONE** | `POST /v1/asns`, EDI DESADV |
| M09-C2 | GR for stock, non-stock, asset; partial receipts | **DONE** | `svc/receiving.py` |
| M09-C3 | Quality inspection (sampling, usage decision), returns, replacements | **DONE** | ISO 2859-1 sample table; `/inspection-lots/{ref}/usage-decision`; `/return-deliveries/{ref}/replacement` |
| M09-C4 | SES: milestones, T&M, unit-rate, progress % | **DONE** | `svc/receiving.py:create_ses(method=…)`; CON 35% progress; ITS 320 h |
| M09-C5 | Receipt tolerances per material/supplier | **PARTIAL** | Tolerance is per contract or the default RCV-TOLERANCE rule. **No per-material or per-supplier tolerance.** |
| M09-C6 | Consignment and subcontracting receipts | **DONE** | Movements 201K/411K, 541/543 (D2) |
| M09-C7 | Batch, serial, expiry capture | **DONE** | Lot trace and recall (`/lots/{material}/{batch}/trace`, `/recall`; HLT) |
| M09-R1 | SES approved by someone other than supplier and PO creator | **DONE** | G-7 |
| M09-R2 | Over-delivery above tolerance blocked | **DONE** | TD-5.2c |
| M09-R3 | Quality-managed GR posts to quality stock until usage decision | **DONE** | F6-05 "yes: quality stock" |
| M09-R4 | Expense receipt-less only below configured value | **DONE** | `receiptlessBelowMinor` (₹25k default, ₹1 L GEN) |
| M09-S | Screens RCV-01..04 | **DONE** | `fe/app/pic/receiving/**` |
| M09-K | KPIs: receipt-to-PO accuracy, dock-to-stock, SES approval time, quality rejection rate | **NOT DONE** | None computed |

### BP §16 M10 Invoice Matching & Finance Integration

| ID | Item | Status | Evidence / gap |
|---|---|---|---|
| M10-C1 | Capture: portal, PDF/OCR, e-invoice (IRN), EDI | **PARTIAL** | Portal is DONE. OCR adapter (`svc/ocr.py`, needs `PIC_OCR_URL`) and IRN (INT-GST) are EXTERNAL. **No EDI INVOIC.** |
| M10-C2 | 2-, 3-, 4-way match; ERS | **DONE** | ALG-9.4 (ERS for consignment only; **not for scheduling agreements**, which the manufacturing template asks for) |
| M10-C3 | Tolerances by amount and %, price and qty, per company code | **PARTIAL** | DMN-03 resolves per company code. **"Per supplier group" is not a scope dimension.** |
| M10-C4 | Exception workflow: price, quantity, missing GR, tax, duplicate | **DONE** | `invoice_exception` (22); `/exceptions/{id}/resolve` |
| M10-C5 | Credit/debit notes and retention | **DONE** | `/credit-notes`; retention withhold and release (CON) |
| M10-C6 | Posting with idempotency and reconciliation | **PARTIAL** | Idempotency is DONE; reconciliation is manual; simulator only |
| M10-C7 | Payment status, early-payment discount, **supply-chain finance hooks** | **PARTIAL** | Payment runs, ISO 20022 files (`svc/bank_files.py`) and discount capture are DONE. **No SCF hooks.** Bank host-to-host is EXTERNAL. |
| M10-C8 | GRIR accruals | **DONE** | `GET /v1/grir` |
| M10-R1 | Duplicate check supplier + no. + amount + date (± tolerance) | **DONE** | TD-5.2d |
| M10-R2 | Goods invoices need GR before approval (3-way) unless ERS | **DONE** | `svc/payables.py:match` |
| M10-R3 | Service invoices match approved SES | **DONE** | match type SES |
| M10-R4 | Idempotency key = tenant + company code + supplier + invoice no. | **DONE** | `svc/payables.py:posting_key` |
| M10-R5 | Payment block until exceptions resolved | **DONE** | `payment_block`; F7-04 "outside tolerance → payment block" |
| M10-S | Screens INV-01..04 | **DONE** | `fe/app/pic/invoices/**` (INV-02 in `[id]`) |
| M10-K | KPIs: first-pass match, exception cycle time, duplicates prevented, discount capture, DPO | **PARTIAL** | First-pass match, discount capture and DPO (`/payables/insights`); **no exception cycle time or duplicates-prevented count** |

### BP §17 M11 Savings & Value Realisation

| ID | Item | Status | Evidence / gap |
|---|---|---|---|
| M11-C1 | Savings types negotiated / avoidance / realised | **DONE** | Ledger types |
| M11-C2 | Baselines: last price, weighted average, budget, should-cost | **DONE** | `svc/savings.py:BASELINE_METHODS` (LAST_PRICE, WAVG_12M, STANDARD, SHOULD_COST) |
| M11-C3 | Lifecycle Identified → … → Validated | **DONE** | SM-SAV |
| M11-C4 | Finance validation and P&L/budget view | **PARTIAL** | Validation with SOD-07 is DONE. **No P&L/budget impact view.** |
| M11-C5 | Leakage: negotiated not realised (off-contract, volume shortfall, price drift) | **DONE** | Waterfall leakage bars (`/savings/{ref}/waterfall`) |
| M11-D | Signature: negotiated 0.99 Cr; avoidance 0.32 Cr; realised YTD 0.38 Cr | **PARTIAL** | DB SV-0412: negotiated 0.9936 Cr and avoidance 0.318 Cr match. **Realised is 0.0129 Cr (₹1.29 L), not 0.38 Cr**: the seed posts too few invoices against the initiative. |
| M11-R1/2/3 | Realised only from posted invoices; avoidance never counts; validator ≠ owner | **DONE** | ALG-9.5 |
| M11-S | Screens SAV-01/02 | **DONE** | `fe/app/pic/savings/page.tsx` (register + waterfall) |
| M11-K | KPIs: negotiated, realised, realisation rate, leakage | **PARTIAL** | Realisation rate is not computed |

### BP §18 M12 Predictive Intelligence & Agents

| ID | Item | Status | Evidence / gap |
|---|---|---|---|
| M12-C1 | Copilot with answer contract | **DONE** | CP-1..4 (deterministic, no LLM) |
| M12-C2 | Predictions: **price trend**, late delivery, supplier risk, demand, invoice exception | **PARTIAL** | Demand forecast and rule-based risk/exception exist. **No price-trend model; late-delivery is seeded data.** |
| M12-C3 | Should-cost by commodity | **PARTIAL** | ML-4 |
| M12-C4 | Agents L0–L4 with kill switch | **DONE** | `PUT /v1/agents/{code}/autonomy`, `/kill-switch` |
| M12-C5 | Model registry, versioning, drift monitoring, feedback loop | **PARTIAL** | Version strings and feedback exist. **No registry, no drift monitoring.** |
| M12-R1 | Agents act only with their role's permissions | **DONE** | Agent principal is scoped to `run_as_role` |
| M12-R2 | L3/L4 only for configured low-risk categories and values | **PARTIAL** | Value limit (₹25 L) and category list exist. Defaults have **no category restriction** (`categories` empty) for the L3/L4 agents. |
| M12-R3 | Every agent action logged with inputs, model version, outcome | **DONE** | AGT-3 |
| M12-S | Screens AIX-01..03 | **DONE** | `fe/app/pic/page.tsx` (command centre), `copilot`, `agents` |
| M12-K | KPIs: agent-assisted %, recommendation acceptance %, prediction accuracy, hours saved | **PARTIAL** | Acceptance rate per agent (`agents.acceptance_rate`) and eval accuracy (D9). **No agent-assisted % or hours saved.** |

### BP §19 M13 Platform, Workflow & Administration

| ID | Item | Status | Evidence / gap |
|---|---|---|---|
| M13-C1 | Org model | **PARTIAL** | TD-4a (no legal entity or purchasing org/group) |
| M13-C2 | Rule engine for thresholds, mandatory fields, tolerances | **PARTIAL** | Mandatory fields missing (G-1); `POST /v1/admin/rules` |
| M13-C3 | **BPMN workflow designer** and approval matrix | **PARTIAL** | Approval-matrix simulation is DONE (`svc/policy_sim.py`, `POST /v1/admin/rules/simulate`). **No workflow designer**; flows are code. |
| M13-C4 | Roles, permissions, SoD rule set, conflict reports | **DONE** | `/admin/roles`, `/admin/sod`, `sod_violation` |
| M13-C5 | Integration hub: connectors, mappings, monitoring, replay | **PARTIAL** | Monitoring and replay (`/integration/messages`, `/admin/connectors`) are DONE. **Field mappings are fixed in code, not configurable.** |
| M13-C6 | Audit trail explorer and data retention | **PARTIAL** | Audit explorer is DONE; retention is report-only (SEC-PRIV) |
| M13-C7 | Industry template packs | **DONE** | TD-4d |
| M13-R1 | Rule changes versioned and effective-dated; in-flight documents keep their version | **DONE** | AD-07 |
| M13-R2 | Workflow models versioned; running instances complete on their version | **PARTIAL** | F-ver |
| M13-S | Screens ADM-01..06 | **DONE** | `fe/app/pic/admin/page.tsx` tabs, `processes` |
| M13-K | KPIs: integration success %, MTTR of integration errors, SoD conflicts open | **PARTIAL** | Posting success % and SoD violations exist; **no MTTR** |

### BP §20 Signature case (Axion, AXN) — values in pic_neon_build

| ID | Stage | Status | Evidence / gap |
|---|---|---|---|
| SIG-1 | MR-1043 net 9,000 | **DONE** | `mrp_run` MR-1043 NET_CHANGE COMPLETED; netting note in the seed |
| SIG-2 | REQ-2311 origin MRP from PLO-55821 | **DONE** | `tests/test_signature_case.py` |
| SIG-3/4 | RFQ-2231 bids 412/398/405, should-cost 391; award 60/40 | **DONE** | `seed/axion.py:375–407`; award_decision (3) |
| SIG-5 | SA-5520 scheduling agreement, LME quarterly, 60-day terms | **DONE** | CLM-PLAYBOOK awardDefaults (LME_AL ±3%) |
| SIG-6 | PO-77410 risk 18/100 touchless | **DONE** | DB PO-77410 risk 18, touchless true |
| SIG-7 | ASN-61208 confirmed in 6 h with batches and CoC | **DONE** | Seeded ASN |
| SIG-8 | GR-90231: 5,400 received / 5,380 accepted / 20 rejected | **DONE** | DB gr_line sums 5400 / 5380 / 20 |
| SIG-9 | INV-TF-8812 → CN-TF-221 → posted, ERP doc 5100004421 | **DONE** | DB INV-TF-8812 PAID, erp_doc_no 5100004421 |
| SIG-10 | SV-0412 negotiated 0.99 Cr / avoidance 0.32 Cr / realised 0.38 Cr | **PARTIAL** | Realised is only 0.0129 Cr (M11-D) |
| SIG-11 | AIX-01 portfolio: spend 412 Cr, under management 78%, coverage 71%, maverick 6.2%, touchless 41%, first-pass 86%, realised 6.3 Cr | **PARTIAL** | DB AXN, 24 months: spend 803.9 Cr (≈ 402 Cr per year), coverage 69.7%, maverick 6.1%, touchless 39%, **first-pass 72% (13/18)**, realised ≈ ₹1.3 L. The demo storyline numbers are not met. |

### BP §21 BPMN flows (branch nuances beyond TD §8)

| ID | Nuance | Status | Evidence / gap |
|---|---|---|---|
| BF-1 | F1 simulation ends without documents; firmed protected; contract → quota → source list → info record | **DONE** | ALG-9.1/9.2 |
| BF-2 | F2 free text never creates materials; parallel MDM does not block the PR | **DONE** | P04; F2-05/06 |
| BF-3 | F3 weights lock; sealed; non-lowest rationale; savings recorded as negotiated | **DONE** | M05-R*; `savings-negotiated` consumer |
| BF-4 | F4 indexation validity periods; alerts 80/90/100; renewal 120 d | **DONE** | M07 |
| BF-5 | F5 touchless criteria; changes outside tolerance create a new version back to the buyer | **DONE** | F5-08 outcomes in DB |
| BF-6 | F6 SES approver ≠ PO creator; over-delivery blocked; rejections feed scorecard and twin | **DONE** | G-7; `twin_feedback` (local, see INT-TWIN) |
| BF-7 | F7 retries never double-post; realised savings only after posting | **DONE** | INT-12.2; ALG-9.5 |
| BF-8 | F8 per-category qualification; expired certificates downgrade | **DONE** | SM-SUP; G-9 |
| BF-9 | F9 high scores redirect; stewards in parallel | **DONE** | F9-04 "duplicate: requester redirected to DC-330" |

### BP §22 Purchase-type rule matrix (P08)

| ID | Type | Status | Evidence / gap |
|---|---|---|---|
| PT-1 | Stock: material required; GR mandatory, QI if quality-managed; 3-way | **DONE** | Matrix STOCK; STOCK needs a material (code review F2 #3) |
| PT-2 | Non-stock: material optional; cost centre/order/WBS; GR (non-valuated); expensed at GR; 3-way | **DONE** | Matrix NON_STOCK |
| PT-3 | Service: SES approval; 3-way vs SES | **DONE** | Matrix SERVICE (`ses: True`) |
| PT-4 | Expense: GR optional below threshold; 2-way below, else 3-way | **DONE** | `receiptlessBelowMinor`; D2 receipt-less case |
| PT-5 | Capital asset: asset/WBS (capex); GR mandatory; capitalised; capex budget, board limits | **PARTIAL** | Asset or WBS required; capex committee; hard budget stop (D2). **No capitalisation in the ERP GR payload** (status doc open item), and no board-limit band. |
| PT-6 | Consignment: GR to consignment stock; liability at withdrawal; ERS | **DONE** | 201K/411K withdrawals; `settle_consignment` (D2, HLT) |
| PT-7 | Subcontracting: material required plus components; GR of the finished part; component consumption; processing fee | **DONE** | `/purchase-orders/{ref}/components`; 541/543/544 (D2). Job-work tax code SAC 9988 per line still needs a schema decision. |

### BP §23 Industry templates and §23.1 nuances

| ID | Template | Status | Evidence / gap |
|---|---|---|---|
| IND-MFG | Manufacturing: MRP, should-cost RFQ, PPAP, scheduling agreements, quota, QI, 3-way, **ERS for scheduling agreements**, **Kanban/reorder for C-parts**, PPV | **PARTIAL** | AXN covers MRP, PPAP gate, quota and QI. **No ERS on scheduling agreements, no Kanban/reorder-point planning, no PPV against standard cost KPI.** |
| IND-CON | Construction: WBS, BOQ, tender by trade, subcontract + rate contracts, measurement SES, retention, **advance recovery**, variation orders as amendments, **performance bank guarantee** | **PARTIAL** | CON tenant: SC-118, WBS C-2207, SES at 35/70/100%, 5% retention, VO-01 amendment. **Advance recovery is a rule flag nothing reads** (`PROJECT-CONTROLS.advanceRecovery` unused). The bank guarantee exists only as clause text and an approval comment. |
| IND-ITS | IT services: SOW, rate cards, timesheet/milestone SES, licence renewals, InfoSec assessment, **unused-licence flag** | **PARTIAL** | ITS: SOW-4410, RC-22, 320 h SES, renewal alert/extension; InfoSec in the qualification questionnaire. **No licence-utilisation tracking or unused-licence flag.** |
| IND-LOG | Logistics: lane tenders, rate contracts with fuel indexation, POD as service confirmation, freight audit, carrier compliance, **detention/demurrage** | **PARTIAL** | LOG: lane CHE→PNQ ₹54/km, 15 trips, POD, freight audit (FREIGHT-AUDIT `rateTolerancePct 0`), carrier certificates mandatory. **`fuelIndex` and `accessorialsNeedPod` are unused flags; no detention/demurrage rules.** The diesel index is demo data. |
| IND-HLT | Healthcare: par levels, VAC, GPO, consignment, lot/expiry/serial, **cold chain**, usage-triggered replenishment, recall, **clinical sign-off in award**, regulatory approvals | **PARTIAL** | HLT: KN-77 consignment, lot/expiry/serial, recall trace, usage-triggered PO, CDSCO/ISO 13485 mandatory certificates. **`AWARD-APPROVAL.clinicalSignOff` is never read, so clinical sign-off is only a comment. No cold chain, no par-level planning.** |
| IND-GEN | General: guided buying, quick quote/3-quote, catalogue, desktop receipt, receipt-less below threshold, 2-way/3-way, **P-card limits**, budget | **PARTIAL** | GEN: punch-out laptop ₹78,500 with one approval, receipt-less below ₹1 L. **No P-card.** |
| IND-KPI | Template KPIs (PPV, cost to complete, rate compliance, cost per tonne-km, expiry write-offs, catalogue adoption …) | **NOT DONE** | They are listed as labels in `seed/templates.py`; none is computed |

### BP §24 Approval matrix (Table 24) and §24.1 control points

| ID | Band | Status | Evidence / gap |
|---|---|---|---|
| APR-1 | Requisition < ₹25,000: auto (policy-compliant catalogue/contract) | **DONE** | DMN-01 band 1 `autoChannels` |
| APR-2 | Requisition ₹25,000 – 2 L: cost-object owner | **DONE** | DMN-01 |
| APR-3 | Requisition 2 – 10 L: cost-object owner + department head | **DONE** | DMN-01 |
| APR-4 | Requisition > 10 L: + procurement head + finance controller; capex follows asset policy | **DONE** | DMN-01 + `assetAdds CAPEX_COMMITTEE`. Band-edge decision pending (see DMN-01). |
| APR-5 | Sourcing award < 50 L: category manager; rationale if not lowest | **DONE** | AWARD-APPROVAL |
| APR-6 | Sourcing award ≥ 50 L: category manager + CPO + finance; conflict-of-interest declaration | **DONE** | AWARD-APPROVAL; `svc/sourcing.py:553` |
| APR-7 | Contract ≥ 1 Cr or non-standard clauses: Legal + Finance + CPO; fallback deviations scored | **DONE** | CONTRACT-APPROVAL `above`; non-standard redlines route to Legal |
| APR-8 | PO deviation: price > contract + 2% **or > last price + 5%** → buyer lead; justification mandatory | **PARTIAL** | Deviation is measured against the **contract's own price tolerance** (default 0.5%), not a +2% band. **The "last price + 5%" check for non-contract POs is not built.** Buyer lead = a second BUYER (PO-APPROVAL `deviationChain`). |
| APR-9 | Supplier bank change: Finance ×2 with call-back; never the requester | **DONE** | SEC-BANK |
| APR-10 | New reusable material: domain stewards; duplicate score < 0.92 | **DONE** | F9 |
| CTL-1 | Budget check at PR submit (hard capex/WBS, soft opex) | **DONE** | BUDGET rule |
| CTL-2 | Split-PO detection: same supplier + material group + cost object within 7 days above the band | **DONE** | `_split_pattern` |
| CTL-3 | Price above contract tolerance needs justification and buyer-lead approval | **DONE** | P07 + deviation chain |
| CTL-4 | Payment block until exceptions resolved | **DONE** | M10-R5 |
| CTL-5 | Every approval records actor, timestamp, comment, rule version, evidence shown | **DONE** | F-audit; `task.rule_set_version` |

### BP §25 AI agents (Table 25), autonomy levels (Table 26), answer contract

DB `agent_run` counts per agent are shown in brackets.

| ID | Agent (default autonomy) | Status | Evidence / gap |
|---|---|---|---|
| AG-01 | Demand Sensing (L1) | **DONE** | `svc/forecasting.py` (1 run; DC-331 bias recommendation accepted) |
| AG-02 | MRP Exception (L2) | **DONE** | `svc/planning.py` (5) |
| AG-03 | Guided Buying (L2): finds contract/catalogue matches, **fills account assignment** | **PARTIAL** | Registered, but **never invoked (0 runs)**. The search is plain service logic, and account assignment is not auto-filled. |
| AG-04 | Material Dedup (L2) | **DONE** | `svc/mdm.py` (21) |
| AG-05 | Spend Classification (L3 auto below threshold) | **DONE** | `svc/spend.py:182` guard (304) |
| AG-06 | Sourcing Strategy (L1) | **DONE** | `svc/sourcing_strategy.py` (3) |
| AG-07 | Bid Analysis (L2) | **DONE** | `svc/sourcing.py` (4) |
| AG-08 | Contract Review (L2) | **DONE** | `svc/contract.py` (17); deterministic, no LLM |
| AG-09 | PO Validation (L3) | **DONE** | `svc/order.py:validate` (67) |
| AG-10 | Touchless PO (L4 within policy) | **DONE** | `svc/order.py:343` guard (42) |
| AG-11 | Expediting (L2) | **DONE** | `svc/order.py` (2) |
| AG-12 | Invoice Exception (L2) | **DONE** | `svc/payables.py` (9) |
| AG-13 | Supplier Risk (L1) | **DONE** | `svc/risk.py` (8) |
| AG-14 | Savings Validation (L3 auto-compute, finance validates) | **DONE** | `svc/savings.py` (5) |
| AUT-L | Autonomy levels L0–L4 with meanings | **DONE** | `plat/agents.py:LEVELS`; L1 → RECOMMENDED, L2 → DRAFTED (`recommend`) |
| AC-BP | Answer contract fields, deep link never executes, low confidence stated | **DONE** | CP-1; confidence label "low" below 0.5 |
| AG-QUAL | Phase-3 exit "6 agents in production" | **EXTERNAL** | Code is ready; production needs deployment and feedback volume (≥ 20 per agent before suspension logic applies) |

### BP §26 Savings methodology

| ID | Item | Status | Evidence / gap |
|---|---|---|---|
| SAVM-1 | Negotiated = (baseline − new) × forecast volume; never in budget | **DONE** | `svc/savings.py` ledger `counts=False` |
| SAVM-2 | Avoidance = (requested/market − agreed) × volume | **DONE** | AVOIDANCE ledger (SV-0412, 0.318 Cr) |
| SAVM-3 | Realised = (baseline − invoiced) × invoiced qty from posted invoices; counts after finance validation | **DONE** | ALG-9.5 |
| SAVM-4 | Baseline method fixed per initiative at creation | **DONE** | `savings_initiative.baseline_method` |

### BP §27 KPI framework (Table 28)

| ID | Module KPIs | Status | Evidence / gap |
|---|---|---|---|
| KPI-M01..M13 | 55 KPIs across 13 modules | **PARTIAL** | About 26 are computed (AIX-01 `svc/insight.py:dashboard`, `/payables/insights`, `/supplier-performance`, `pic_slo_*`, forecasting MAPE, D9 accuracy). Missing per module: M02 backlog, conversion lead time, stock-outs, days of cover; M03 all; M04 channel %, free-text %, budget-blocked; M05 cycle time, competitive %; M06 onboarding cycle; M07 cycle time, obligation on-time; M08 PO cycle time; M09 all; M10 exception cycle, duplicates prevented; M11 realisation rate; M12 agent-assisted %, hours saved; M13 MTTR. |

### BP §28 Roadmap & MVP definition of success

| ID | Criterion | Status | Evidence / gap |
|---|---|---|---|
| MVP-1 | Touchless PO ≥ 30% for catalogue/contract lines in the pilot plant | **EXTERNAL** | Demo AXN shows 39%; it must be measured on the pilot |
| MVP-2 | First-pass invoice match ≥ 80% | **EXTERNAL** | Demo AXN shows 72% (13/18); must be measured on the pilot |
| MVP-3 | Zero duplicate ERP postings across 10,000 invoices in UAT | **EXTERNAL** | The mechanism is DONE (INT-12.2); never run at 10k volume or against a real ERP |
| MVP-4 | Every PO line traceable to its origin in one click | **DONE** | Lineage tab on the PO page |
| RM-0..4 | Phases 0–4 scope | **PARTIAL** | All phase scopes are built in code. The exits that depend on real ERP/connectors (Phase 1) and the workbook industry sheets (Phase 4) are open. |

### Project design decisions DD-01..11 (`docs/PIC_Delivery_Plan.md` §3; project-internal, not in the Blueprint)

| ID | Decision | Status | Evidence / gap |
|---|---|---|---|
| DD-01 | FastAPI modular monolith; no cross-module table access, enforced by import-linter | **PARTIAL** | Monolith is DONE; **no import-linter**, and cross-module table reads are common (TD-3a) |
| DD-02 | PG 16 + RLS, SQLAlchemy, Alembic | **DONE** | AD-02 |
| DD-03 | Outbox to a Kafka-compatible broker, Avro registry | **NOT DONE** | EV-3 |
| DD-04 | Camunda 8 via pyzeebe | **NOT DONE** | Replaced by the own engine (AD-01) |
| DD-05 | Keycloak broker (OIDC/SAML) | **NOT DONE** | Direct OIDC only; no SAML |
| DD-06 | Postgres materialised views in MVP, ClickHouse from Phase 2 | **NOT DONE** | No materialised views and no ClickHouse (AD-04) |
| DD-07 | LLM only via LiteLLM | **NOT DONE** | AD-06 (dependency present, unused) |
| DD-08 | Rule sets in Postgres, evaluated in Python | **DONE** | AD-07 |
| DD-09 | Supplier portal as a second Next.js app | **NOT DONE** | FE-4 (same app) |
| DD-10 | Twin as a separate bounded context PIC reads from | **PARTIAL** | INT-TWIN |
| DD-11 | GCP asia-south1 + asia-south2 DR, Terraform | **EXTERNAL** | Terraform ready (no DR stack); current hosting decision is Vercel + Neon Singapore |

---

## Part 3 — Datasets D1–D11

Source: `backend/app/pic/seed/datasets/*.py` packs, `pic.dataset_load` in pic_neon_build, and `tests/test_datasets_*.py`.

| # | Dataset | Status | Evidence (pack · DB · tests) / gap |
|---|---|---|---|
| D1 | Branch cases for every unexercised gateway (cases 9–34) | **DONE** | `branches.py` (dataset `axn-branch-cases`). All 84 steps executed and 13/13 gateways taken both ways. 25 tests in `test_datasets_branches.py`. Data gaps: no CANCELLED sourcing event, no LOST savings, no PREFERRED supplier and no RENEWED contract remain in the final data (some are tested in the suite only). |
| D1b | Operations module cases (amendments, auction, EDI, e-way bill, 4-way, reconciliation, payment files, MDM-04, punch-out, ERP import) | **DONE** | `module_cases.py` (`axn-module-cases`: PO-77425, RFQ-2233, IB-101, REC-102/103, PF-1001/1002, REQ-2330); 8 tests. The e-sign leg records "ESIGN_NOT_CONFIGURED". |
| D2 | Purchase types: expense, capital asset, consignment, subcontracting | **DONE** | `purchase_types.py` (`axn-purchase-types`); 9 tests |
| D3 | Construction tenant CON: WBS C-2207, SC-118, SES 35%, 5% retention, VO | **DONE** | `industry_construction.py`. CON: 6 suppliers, 2 POs, 5 invoices, 43 spend lines, 1 contract. 6 tests. Advance recovery and bank guarantee are not modelled (IND-CON). |
| D4 | IT services ITS: SOW-4410, RC-22, 320 h SES, licence renewal | **DONE** | `industry_it.py`. ITS: 6 suppliers, 2 POs, 2 invoices, 40 spend lines, 2 contracts. 5 tests. |
| D5 | Logistics LOG: lane CHE→PNQ ₹54/km + fuel index, POD, freight audit | **DONE** | `industry_logistics.py`. LOG: 16 POs, 16 invoices. 7 tests. Fuel index is demo data. |
| D6 | Healthcare HLT: KN-77 consignment, lot/expiry, usage PO, recall | **DONE** | `industry_healthcare.py`. HLT: 8 POs, 3 invoices plus ERS settlements. 7 tests. |
| D7 | General GEN: laptop punch-out ₹78,500, single approval | **DONE** | `industry_general.py`. GEN: 9 POs, 13 invoices. 5 tests. Punch-out uses the simulator. |
| D8 | Volume: 50k materials, 5 M invoices/yr, 50 M spend lines, 10k users | **PARTIAL** | Generator `tools/volume_gen.py` + `tools/perf_mrp.py`; 3 tests (`test_volume_gen.py`). It is not loaded into pic_neon_build, by design. **Only the 50k-material MRP run was executed (681–1,615 s, FAIL). 5 M invoices and 50 M spend lines were never generated or measured.** The k6 10k-user test was never run. Needs a production-like environment. |
| D9 | AI evaluation sets (2,654 labelled spend lines, 45 forecast points, 48 duplicate pairs, 40 Copilot questions) | **DONE** | `ai_eval.py` + `tools/ai_eval.py` (`ai-evaluation-sets`); 7 tests. Gates: classification 0.9936 PASS, MAPE h1 0.037 PASS, Copilot 1.0 PASS, dedup recall 1.0 PASS. **autoApplyPrecision 0.857 < 0.95 FAIL; dedupPrecision 0.83 < 0.90 FAIL.** The gate targets are "proposed" and need your sign-off. |
| D10 | Real tenant masters from your ERP (vendors with bank/tax, materials, contracts, open POs, open AP, 24–36 months history) | **EXTERNAL** | Only the legacy prototype DB was migrated: GMC (5 suppliers, 0 materials, 5 POs, 2 spend lines) and DBY (1 supplier, 9 materials, 6 POs, 13 spend lines). AXN history (2,568 lines, 20 ERP vendors) is **generated**. Loaders for open contracts, open POs and open AP are not built (MIG-2/3/5). |
| D11 | Reference data: FX, HSN/SAC + GST, holiday calendars, UNSPSC/taxonomy | **PARTIAL** | `reference_data.py` (`reference-data` loaded for all 8 tenants); 9 tests. HSN-GST: 370 CBIC entries. TAXONOMY-UNSPSC: 56 mappings. Holidays: 23–46 per plant, **but the migrated GMC and DBY P100 plants have none**. **FX is a single day (28 Oct 2026; 4 rates per tenant), with no history.** 2027 state holiday lists are incomplete. UNSPSC is a mapping only, not the licensed code set. |

---

## Part 4 — Summary counts

Counted from the Status column of every row above.

| Document | DONE | PARTIAL | NOT DONE | EXTERNAL | N/A | Total |
|---|---:|---:|---:|---:|---:|---:|
| Technical Document (Part 1) | 82 (46%) | 68 (38%) | 17 (10%) | 10 (6%) | 0 | 177 |
| Blueprint (Part 2, incl. 11 project DD rows) | 199 (66%) | 83 (28%) | 12 (4%) | 7 (2%) | 0 | 301 |
| Datasets (Part 3) | 9 | 2 | 0 | 1 | 0 | 12 |
| **All** | **290** | **153** | **29** | **18** | **0** | **490** |

Blueprint without the project DD rows: 197 DONE, 81 PARTIAL, 6 NOT DONE, 6 EXTERNAL (290 rows).

What the numbers say:
- The **business logic of the Blueprint is largely built and tested**. That covers flows F1–F9, state machines, DMN tables, SoD, purchase types, the five industry tenants, the agents and the signature case.
- The **Technical Document's platform choices and NFRs are where the gaps are**: Camunda, Kafka, ClickHouse, the LiteLLM gateway, GraphQL, a separate portal app, bpmn-js, Playwright/Pact, measured performance and accessibility.
- **Real integrations are also open**: a real SAP connector, ERP inbound sync and migration loaders.

---

## Part 5 — What you must supply or decide

De-duplicated. The last column shows the rows each item unblocks.

### 5.1 Decisions (architecture, product, legal, tax)

| # | Decision | Unblocks |
|---|---|---|
| DEC-1 | **Accept or reject the architecture deviations**: FastAPI monolith instead of NestJS services; Postgres workflow engine instead of Camunda 8; in-process outbox instead of Kafka/Avro; Postgres spend cube instead of ClickHouse; REST only (no GraphQL); portal in the same app. Accepting them closes about 15 PARTIAL/NOT DONE rows. Rejecting them is L-size work per item. | TD-1.1a, TD-2.1b–e, AD-01, AD-03, AD-04, TD-3a, EV-3, API-1, FE-4, TST-C, DD-01/03/04/06/09 |
| DEC-2 | **Hosting and residency**: stay on Vercel (Pro or Hobby) + Neon Singapore, or move to GCP asia-south1 (India residency, DD-11). Also decide on tenant-level residency. | TD-2.1h, NFR-RES, NFR-AV, NFR-DR, SEC-PRIV, DD-11 |
| DEC-3 | **Neon plan** (PITR ≥ 7 days, exports) to meet RPO 15 min / RTO 4 h; DR region | NFR-DR |
| DEC-4 | **Identity**: corporate IdP via OIDC, and whether **SAML** is required; switch MFA `enforce=true` per tenant; mandatory MFA for supplier users | SEC-ID, NFR-SEC |
| DEC-5 | **LLM**: provide the LiteLLM gateway (URL, key, model list), or confirm the deterministic Copilot and playbook redline are acceptable | AD-06, CP-3, ML-8, DD-07 |
| DEC-6 | **Rule values the spec leaves open**: touchless value band (default ₹25 L); DMN-01 band edges at exactly ₹2 L / ₹10 L; PO-deviation rule (contract tolerance vs +2%, and last price +5%); escalation (add manager vs reassign); AI-eval gate targets (auto-apply precision ≥ 0.95, dedup precision ≥ 0.90) | DMN-01, DMN-02, APR-8, F-esc, ML-1, ML-3, TST-AI |
| DEC-7 | **Legal**: retention periods per data category (10-year audit vs the current 8-year default), lawful-basis wording | NFR-AUD, SEC-PRIV |
| DEC-8 | **Tax team**: GST on goods transport (SAC 996791), implant rate, ERS self-billing under GST, job-work SAC 9988; GST rate on material requests | PT-7, IND-HLT, IND-LOG, M10-C2 |
| DEC-9 | **Product scope**: multi-item/lot sourcing events (currently one item per event); which industry template and purchase types the pilot uses first | ALG-9.3, M05-C1/C2, IND-* |
| DEC-10 | **ZAP gating**: triage the baseline, then make ZAP blocking | SEC-APP, TST-SEC |

### 5.2 Systems, credentials and access

| # | Supply | Unblocks |
|---|---|---|
| SUP-1 | **SAP S/4HANA sandbox** (OData service URLs, technical user; IDoc if needed), or the target ERP of your pilot (Oracle/D365/Tally gateway/Odoo credentials) | INT-SAP, INT-ORA, INT-D365, INT-TALLY, INT-ODOO, INT-IN, M03-C7, M10-C6, P13, PH-1, MVP-3 |
| SUP-2 | **GST IRP/GSP** credentials (`PIC_IRP_*`) | INT-GST, M10-C1 |
| SUP-3 | **E-signature provider** (`PIC_ESIGN_PROVIDER/URL/API_KEY/WEBHOOK_SECRET`) | M07-C4, F4 |
| SUP-4 | **Bank host-to-host/SFTP** and the real debtor account/IFSC (PAYMENT-FILE rule) | M10-C7 |
| SUP-5 | **EDI gateway** (AS2/SFTP, `PIC_EDI_GATEWAY_URL/TOKEN`) and supplier EDI IDs; **punch-out supplier accounts** | INT-EDI, INT-PUNCH, M08-C5, D7 |
| SUP-6 | **Sanctions feed** licence (`PIC_SANCTIONS_*`), plus financial-risk and news providers if wanted | INT-RISK, M06-C6 |
| SUP-7 | **Supplier Capability Digital Twin** API endpoint and credentials (capability, free capacity, trust, late-delivery) | INT-TWIN, ML-5, M06-D, DD-10 |
| SUP-8 | **SMTP** (`PIC_SMTP_*`) for PO e-mails, invitations and notifications | M08-C5, F8 |
| SUP-9 | **OCR/IDP engine** (`PIC_OCR_URL/TOKEN`) | M10-C1 |
| SUP-10 | **Hosting access**: Vercel team/token and plan, or a GCP project; GitHub secrets (`NEON_DATABASE_URL`, `PIC_JWT_SECRET`, `PIC_FIELD_KEY`, `PIC_METRICS_TOKEN`, `PIC_SEED_PASSWORD`); rotated Neon password; Neon URL (still not provided); KMS key if on GCP | TD-2.1h, SEC-DP, TD-4b |
| SUP-11 | **OTel collector / log sink** (Cloud Logging or Grafana) | OBS-1, DOD-6 |
| SUP-12 | **A staging environment** sized like production, for k6, cube, MRP and 10k-user runs | NFR-P95, NFR-PR, NFR-CUBE, NFR-MRP, NFR-SCALE, D8, TST-PERF |

### 5.3 Data and documents

| # | Supply | Unblocks |
|---|---|---|
| DAT-1 | **ERP extract** (24–36 months PO + invoice history, vendors with bank/tax IDs, materials, open contracts, open POs, open AP, GL totals for tie-out) | D10, MIG-1..5, SIG-11, MVP-1/2 |
| DAT-2 | **FX history** (FBIL archive) and the currency of legacy amounts | D11, TD-1.1c |
| DAT-3 | **Reference data**: 2027 holiday lists for the remaining states; holidays for the migrated P100 plants; real IFSC codes; a real diesel/fuel index feed; licensed UNSPSC (if class level is needed); your spend taxonomy | D11, IND-LOG, M01-C2 |
| DAT-4 | **Test-Case Workbook AHG/PRC/PIC/2026-10/03** (E2E-01..n, industry test sheets) | TST-E2E, PH-4, DOD-1 |
| DAT-5 | **Business data**: FY 2027-28 budgets, NPPA ceiling prices for implants | D1/D2 budgets, IND-HLT |

---

## Part 6 — Top gaps you can build without the customer (ranked)

Size: S ≈ ≤ 1 day, M ≈ 2–5 days, L ≈ 1–3 weeks.

| Rank | Gap | Rows | Size |
|---:|---|---|---|
| 1 | **Apply Idempotency-Key to all 112 unprotected POST routes**; add the 24 h expiry/purge; add ETag/If-Match on all mutable documents (requisition, contract, invoice, sourcing event, supplier) | API-2, API-3, DOD-4 | M |
| 2 | **Enforce ABAC on commands** (company code, plant, category, value band: wire `check_attr`/`check_value_limit` into the services); add the SoD mitigating-approval path; add the SoD check inside the agent guard and call the guard for every acting agent | SEC-AZ, SEC-SOD, AGT-2, SOD-AGT | M |
| 3 | **MRP to < 600 s at 50k materials** (drop the per-order link rows or batch them, summary response, COPY for planned orders); add weekly buckets by MRP type | NFR-MRP, ALG-9.1, M02-NFR | M |
| 4 | **Spend at scale**: rewrite SPD-01 `overview` as SQL aggregates; add materialised views (DD-06) with refresh; add period/filters, price-variance and invoice/PO-count measures to the cube; run `volume_gen --measure` at 50 M rows | AD-04, NFR-CUBE, M01-C1/C5/D | M–L |
| 5 | **Scheduled jobs**: nightly reconciliation per company code, payment-due timer, monthly scorecard recompute, retention purge, idempotency purge, scheduled MRP. Requires Vercel Pro or the GCP worker for minute ticks. | INT-12.2-5, F7, M06-R4, SEC-PRIV, NFR-AUD | S–M |
| 6 | **Test layers**: Playwright E2E for the signature case and the 5 industry packs; a coverage gate (85% domain logic); event JSON-schema contract tests; axe accessibility checks in CI | TST-E2E, TST-U, TST-C, NFR-A11Y, UX-6, DOD-5 | M–L |
| 7 | **KPI completion**: compute the ~29 missing module KPIs (M02 backlog/days of cover, all of M03 and M09, cycle times, realisation rate, agent-assisted %, MTTR) and the template KPIs (PPV, cost to complete, cost per tonne-km, …) | KPI-M01..M13, IND-KPI | M |
| 8 | **Front-end gaps**: SPD-08 pipeline tracker, lifecycle strip, generic Approvals/Documents tabs, a bpmn-js process viewer, saved views and bulk actions; **fix the hard-coded "Manufacturing template" header** (S) | FE-1/2/3/5, UX-1/3, M01-S | M |
| 9 | **Industry and purchase-type controls that are only flags or comments**: clinical sign-off as an award approval step, advance recovery, performance bank guarantee tracking, accessorials/detention, ERS for scheduling agreements, Kanban/reorder point, licence utilisation, P-card; price-history check ("last price + 5%") on PO validation; risk constraints in award optimisation | IND-*, APR-8, M08-C3, ALG-9.3 | M–L |
| 10 | **Master data and the org model**: legal-entity and purchasing-org/group masters (remove `purch_org="1000"` and `currency="INR"` hard-codes), configurable mandatory fields, material change requests with impact analysis, sales-order account assignment, real FX conversion with the rate and date stored on amounts | TD-4a, TD-1.1c/f, G-1, M03-C5, M04-C4 | M–L |
| 11 | Migration loaders (contracts, open POs, open AP, spend history with GL tie-out), ready for when the ERP extract arrives | MIG-1..5 | M |
| 12 | Event consumers per the catalogue (ai-svc consumers that feed agents, supplier.status.changed → open-PO/RFQ flagging); a published event schema document | EV-4, DOD-2 | S–M |
| 13 | Field-encryption key versioning and a re-encryption job; breached-password check; a written threat model | SEC-DP, SEC-APP | M |
| 14 | Data fixes: seed enough posted invoices so SV-0412 realised ≈ 0.38 Cr and first-pass ≈ 86%; add holidays for the GMC/DBY P100 plants | M11-D, SIG-10/11, D11 | S |
