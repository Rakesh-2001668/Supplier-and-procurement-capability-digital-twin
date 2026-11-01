# PIC Contracts module (M07 Contract Lifecycle Management, flow F4) — analysis against the Blueprint and the Technical Document

Scope: Blueprint section 13 (M07), flow 21.4 (F4), screens CLM-01..CLM-04, signature case SA-5520, KPIs of M07; Technical Document contract-svc
(state machine, data model, source determination 9.2, API, events, clause extraction, contract redline agent).
Code audited: `backend/app/pic/services/contract.py`, `amendments.py`, `rebates.py`, `clause_extract.py`, `api/source_contract.py`,
`api/governance.py` (manual contracts), `api/source_ops.py` (amendments, termination, e-sign envelopes), `api/wave1_c.py` (rebates, extraction),
`models/source_contract.py`, source determination (`services/source.py`, `services/order.py`, `services/requisition.py`), spend flags
(`services/savings.py`, `services/spend.py`), KPIs (`services/kpi.py`), seed rule sets, event schemas, and the contracts screens of the frontend.

Legend: **V** verified by the new end-to-end test `backend/tests/pic/test_contract_journey.py` (steps 01..12); **E** verified by an existing test;
**P** works, only partly covered; **M** missing or not verified.

## 1. What the specification requires

* Seven contract types: master agreement, quantity, value, scheduling agreement, rate card, SOW, NDA.
* Clause library with fallback positions and risk scores; templates by category and jurisdiction; AI redline review against the playbook.
* Approval workflow and e-signature; obligations, milestones; price indexation (new validity period at each reset, never overwritten); rebates.
* Consumption against quantity or value with alerts at 80 / 90 / 100 %; renewal (notice 120 days before expiry), expiry and termination.
* Compliance: off-contract buying and price leakage. Executed contracts are the price source for POs.
* Rules: only executed contracts can be referenced by a PO; a PO line price equals the contract price within tolerance or is flagged
  (Technical Document: `contract_line_id` set means price inside tolerance or `deviation_reason NOT NULL`); a contract of 1 Cr or more, or with a
  non-standard clause, needs legal and finance approval; indexation creates a new price validity period.
* F4 steps 1-10, screens CLM-01 (workspace: header, documents, clauses, lines, obligations), CLM-02 (clause review and redline: deviation from
  playbook, risk score, fallback suggestion), CLM-03 (consumption and compliance: released vs target, leakage, renewals calendar), CLM-04
  (obligation tracker with due dates), KPIs: contract cycle time, contract leakage, expiring in 90 days, obligation on-time %.
* Technical Document: state machine Draft > In Negotiation > In Approval > Out for Signature > Active > Expiring > Expired | Terminated | Renewed;
  events `contract.activated`, `contract.consumption.threshold`; `POST /v1/contracts`, `/activate`, `GET /consumption`; source determination step 1
  "active contract line (validity covers the date, not exhausted)"; SoD, ETag/If-Match, Idempotency-Key, problem+json, RBAC scopes, RLS, audit.

## 2. Traceability (rule or step, code, evidence)

| # | Spec rule / step | Code location | Evidence |
|---|---|---|---|
| 1 | Types master agreement, NDA | `contract.py` FRAMEWORK_TYPES, `api/governance.py` ContractIn | E `test_wave1_sourcing_contracts`; V journey 01 (lines refused with LINES_NOT_ALLOWED) |
| 2 | Types quantity, value, scheduling | `contract.py` create_draft; seed CLM-PLAYBOOK | V 01, 06 |
| 3 | Types rate card and SOW | `contract.py` BUILTIN_TEMPLATES / BUILTIN_OBLIGATIONS (new), API pattern | V 01 (clauses and SOW milestones). Was MISSING: not creatable |
| 4 | Clause library with fallback positions, risk score | CLM-PLAYBOOK `positionRisk`, `fallbacks`; `clause_findings` | V 02 |
| 5 | Templates by jurisdiction | `JURISDICTIONS`, `_library` | E wave1 (IN-TN, IN-GJ); V 01 (IN-MH stamp duty) |
| 6 | Templates by category | CLM-PLAYBOOK `categoryClauses`, `Contract.category`, `_library` (new) | V 01 (ESG overlay). Was MISSING |
| 7 | AI redline review against the playbook, risk score | `ai_review`, `clause_findings` (wording vs library text, `Clause.standard_text`) | V 02; E f3_f4 |
| 8 | Supplier redline always non-standard until reviewed | `redline`, `review_redline` | E f3_f4; V 02 |
| 9 | Fallback suggestion | `clause_findings.fallback / suggestedPosition`, `GET /contracts/{ref}/clause-review` (new) | V 02 |
| 10 | Approval workflow: 1 Cr or more, or non-standard: legal + finance (+CPO) | `approval_route`, `submit`, rule CONTRACT-APPROVAL | V 03 (3 steps, sequential); E f3_f4 |
| 11 | Below threshold: single approval | same | V 06 |
| 12 | SoD: owner and submitter cannot approve | `submit` exclude + initiator; `workflow.guard_task` | V 03, 06 (403 for owner and submitter); E f3_f4 |
| 13 | E-signature of both parties, hash-bound | `sign`, `_document_hash` | V 04 (duplicate signature 409 ALREADY_SIGNED, new) |
| 14 | E-signature provider (DocuSign etc.) | `EsignProvider`, `handle_webhook` | V 06 with a faked provider (HMAC, replay, changed document); live provider NOT VERIFIED |
| 15 | Activate publishes prices to source determination | `activate`, `source.contract_price` | V 04, 05 |
| 16 | Only executed contracts can be referenced by a PO | `order.create_from_requisition`, `source._contract_lines`, `requisition` (new check) | V 05 (draft), 10 (terminated), 11 (expired); requisition line of a draft contract refused (was MISSING) |
| 17 | PO price equals contract price within tolerance, else flagged | `order._create_po`, DB check `deviation_reason` | V 05 (inherited price, inside tolerance, above tolerance refused, flagged with reason); per-line tolerance fixed |
| 18 | PO quantity inside the contract quantity | `order.create_from_requisition` + `contract.committed_qty` (new) | V 05, 07. Was MISSING |
| 19 | Consumption tracking; alerts 80 / 90 / 100 to the owner | `_consume`, notification `notify-contract-consumption` | V 07 (owner and contract managers, once each); E f3_f4 |
| 20 | Compliance: off-contract buying, price leakage | `consumption().compliance`, `savings._spend` flags, KPI M07 leakage | V 07 (numbers add up); invoice-based leakage KPI E `test_wave1_spend_kpi` |
| 21 | Indexation: new validity period, never overwrite | `index_reset` | V 08 (3 periods, absorbed vs adjusted, duplicate and earlier dates 409, idempotent); E f3_f4 |
| 22 | Obligations and milestones | `add_obligation` (new), `complete_obligation`, `Obligation.kind` | V 09 |
| 23 | Rebates | `rebates.py`, `api/wave1_c.py` | E wave1 sourcing contracts (accrual, settlement, ERP credit memo); not re-audited line by line |
| 24 | Renewal triggers 120 days before expiry | timer CONTRACT_RENEWAL at valid_to - `renewalNoticeDays` | V 11 (nothing the day before, EXPIRING with decision task at 09:00 IST on the day) |
| 25 | Renew decision, extension | `_renewal_decided`, `amendments.renewal_draft` | V 11 (extension drafted, approved by another manager, ACTIVE, v2, timers re-armed) |
| 26 | Expire | timer CONTRACT_EXPIRY `_expired` | V 11 (open renewal task is now cancelled; was a defect) |
| 27 | Terminate (direct action) | `contract.terminate`, `POST /contracts/{ref}/terminate` (new), termination amendment | V 10 (notice rule, chain legal + CPO, effective on approval, prices stopped). Was only via amendment |
| 28 | State machine Draft...Terminated | `contract.SM` | V 01-04, 10, 11. `RENEWED` has no caller (see 5) |
| 29 | F4-01 award or renewal trigger | `_from_award`, `_renewal_due` | E f3_f4 / wave1 (award drafts); renewal V 11 |
| 30 | F4-02 draft from template and clause library | `create_draft` | V 01 |
| 31 | F4-03 AI redline and risk score | `ai_review` | V 02 |
| 32 | F4-04 legal and finance review / redline | `redline`, `review_redline` | V 02 |
| 33 | F4-05 gateway non-standard or 1 Cr | `approval_route` | V 02 (route shown), 03, 06 |
| 34 | F4-06 approve | `workflow.start_approval`, `_approved` | V 03, 06 |
| 35 | F4-07 e-signature | `sign`, envelopes | V 04, 06 |
| 36 | F4-08 activate, publish prices | `activate` | V 04 |
| 37 | F4-09 track consumption and obligations | `_consume`, `consumption`, `obligations_tracker` | V 07, 09 |
| 38 | F4-10 renew / expire / terminate | see 24-27 | V 10, 11 |
| 39 | CLM-01 workspace (header, documents, clauses, lines, obligations) | `frontend/.../contracts/[ref]/page.tsx`; Documents tab is the generic object tab | P: no browser test; tsc and eslint clean; generic Documents tab not audited |
| 40 | CLM-02 clause review and redline | `_clauses.tsx` (new), `clause-review` API | V 02 (API); UI not browser tested |
| 41 | CLM-03 consumption and compliance, renewals calendar | `ConsumptionTab`, `obligations/page.tsx` RenewalCalendar, `/contracts-renewals` | V 07, 11 (API); UI not browser tested |
| 42 | CLM-04 obligation tracker | `obligations/page.tsx`, `/obligations` | V 09 |
| 43 | KPI contract cycle time | `kpi.m07_cycle` (activated_at - created_at) | V 12 (computes, no error) |
| 44 | KPI contract leakage | `kpi.m07_leakage` (open maverick hits OFF_CONTRACT*) | E spend_kpi; V 12 (computes). Source is invoice posting, see 5 |
| 45 | KPI expiring in 90 days | `kpi.m07_expiring` | V 11 (value 1 at 60 days before expiry, 0 afterwards) |
| 46 | KPI obligation on-time % | `kpi.m07_obligations` (on-time uses `completed_at`; was "completed = met") | V 09 (equals the tracker's figure) |
| 47 | Event contract.activated | `activate`, schema | V 04 (tick), E schema validation `test_wave1_jobs` |
| 48 | Event contract.consumption.threshold | `_consume`, schema (line, quantities added) | V 07, E schema validation |
| 49 | Idempotency-Key | create, index-resets, obligations, terminate, amendments, envelopes | V 01, 08, 09, 10 |
| 50 | ETag / If-Match | generic preconditions; REQUIRED now includes submit, activate, terminate, index-resets, amendments | E `test_wave1_platform` mechanism; contract routes not exercised with enforcement on |
| 51 | problem+json, validation | typed `ContractIn`, `IndexResetIn`, `ObligationIn`, services | V 01, 08, 09 |
| 52 | RBAC scopes | `contract:manage`, `contract:sign`, `supplier:portal`, READ | V 01-09 (403s) |
| 53 | RLS / tenant isolation | no new tables; new columns on RLS tables | V 12 (by id 404, lists, audit) |
| 54 | Audit trail | `audit.record` on every command | V 12 (full action list, hash chain valid) |
| 55 | Source determination step 1 (active, in validity, not exhausted, deterministic) | `source._contract_lines` | E signature case; ordering of several live contracts unchanged (see 5) |
| 56 | Contract redline agent (LLM with playbook) | `erp_ai_ops.py` redline suggestion; deterministic playbook review in `ai_review` | P: no LLM provider call verified |
| 57 | Clause extraction from existing contracts | `clause_extract.py`, `api/wave1_c.py` | E wave1 sourcing contracts; not re-audited |
| 58 | Contract sees supplier only after negotiation starts | `get_contract`, `/contracts` list | V 01, 03 (new rule: a draft is internal) |

Counts: 58 rows. V (verified by the journey, alone or together with an existing test) 49; E (existing tests only) 5 (rows 23, 29, 50, 55, 57);
P (works, UI or provider side not exercised) 4 (rows 39, 40, 41, 56); NOT VERIFIED / MISSING as a stated rule 0 (the open points are listed in section 5).

## 3. What works (before this change)

State machine and approvals with four-eyes, supplier redline classification, hash-bound signatures, e-sign provider adapter with HMAC webhook,
activation with price publication and quota arrangement, quantity consumption recomputed from live PO lines (idempotent), index reset with
absorption band and savings avoidance, amendments (variation, extension, terms, termination) with notice rules and approvals, renewal and expiry
timers, framework agreements, jurisdiction variants, rebates, clause extraction, the contract screens (workspace, amendments, rebates,
extraction, obligations, renewal calendar). The 55 existing contract tests all passed.

## 4. Defects and gaps found and fixed

| # | Finding | Fix (file:line) |
|---|---|---|
| 1 | RATE_CARD and SOW (Blueprint types) could not be created and had no template | `contract.py:81` BUILTIN_TEMPLATES / BUILTIN_OBLIGATIONS; `governance.py` type pattern; `new/page.tsx` |
| 2 | No templates by category | `contract.py:196` `_library` with CLM-PLAYBOOK.categoryClauses; `Contract.category`; award keeps the event category |
| 3 | `ai_review` could be run on an active contract and rewound its process (F4-04 wait on a running contract) | `contract.py:410` status guard |
| 4 | AI review only mapped position to risk; a reworded clause on STANDARD was invisible; no deviation or fallback view for CLM-02 | `contract.py:381` `clause_findings`, `:433` `clause_review`, `Clause.standard_text`, `GET /contracts/{ref}/clause-review`, `_clauses.tsx` |
| 5 | A party could sign twice (unique-constraint 500) | `contract.py:587` 409 ALREADY_SIGNED, party validated |
| 6 | Activation did not check an ended validity or a blocked supplier, and an illegal state gave a misleading signature message | `contract.py:616` |
| 7 | PO against a contract could exceed the contract quantity; plant ignored; price tolerance of the PO's first contract applied to all lines | `order.py:103-120`, `:238` ; `contract.py:695` `committed_qty` (counts drafts and orders in approval) |
| 8 | Requisition line could reference a contract that is not executed (blueprint rule 1) | `requisition.py:207` |
| 9 | Consumption alerts were de-duplicated per contract: the second line reaching 80 % never alerted | `contract.py:715` per-line `ContractLine.thresholds_hit`; notification key includes the line (`notifications.py`) |
| 10 | No direct terminate action | `contract.py:916` `terminate`, `POST /contracts/{ref}/terminate` (`source_ops.py:62`), approvals unchanged |
| 11 | Expired contract left its renewal decision task open | `contract.py:933` `_expired` cancels it; guard against a stale expiry timer after an extension |
| 12 | Index reset: no validation of date inside validity, duplicates or earlier resets, non-positive index, no Idempotency-Key | `contract.py:797`, `source_contract.py:316` |
| 13 | Obligations: no way to add one or a milestone; completion without evidence/timestamp; double completion; KPI counted a late completion as on time | `contract.py:848/872`, `Obligation.kind/completed_at/completed_by/completion_note`, `kpi.py:328` (fixed UTC+05:30 offset, no tz database needed), API `POST /contracts/{ref}/obligations` |
| 14 | Compliance numbers: consumption view had only off-contract lines, no totals, no flagged contract-priced lines, no validity window end | `contract.py:742` `compliance` block (rate, off-contract value, price leakage, price-deviation lines) |
| 15 | Create contract: untyped tolerances and index (500 on garbage), no length limits, master agreement with lines accepted at API | `governance.py` typed `ToleranceIn`, `IndexRefIn`, limits; `contract.py:181` `check_index_ref` |
| 16 | Supplier could list and open a DRAFT contract | `source_contract.py` get_contract, `lists.py` |
| 17 | Contracts list had no filters | `lists.py` supplier, type, text, expiring |
| 18 | ETag required list did not contain the contract commands | `preconditions.py` REQUIRED |
| 19 | Frontend: list mislabelled CLM-03, no filters; new-contract form could not create RATE_CARD/SOW, hard-coded plant P100 and company 1000, tolerances not bounded, no category/reset; consumption tab had no compliance panel or add-obligation; obligations page lacked on-time %, milestone, late-completion, renewal decision | `contracts/page.tsx`, `new/page.tsx`, `[ref]/page.tsx`, `[ref]/_clauses.tsx`, `obligations/page.tsx` |
| 20 | Two failing jobs tests in the integrated run (`test_idempotency_records_older_than_24_hours_are_purged`, `test_agent_is_suspended_automatically_when_acceptance_drifts_below_70_percent`): not a code defect. `Scenario.act` / `approve_all` pin the business clock and an earlier module (`test_wave1_industry`) left it pinned; the jobs tests then ran with a clock days ahead of the rows they wrote. Reproduced with a pinned clock, both pass on a real clock | `tests/pic/conftest.py` module-scoped autouse fixture resets the clock at the start and end of every module (module fixtures can still pin on purpose). No control weakened |

Schema: migration `0016_contracts_complete.py` (down_revision `0015`): `obligation.kind/completed_at/completed_by/completion_note`, `contract.category`,
`contract_line.thresholds_hit`, `clause.standard_text`, with backfills. Existing tables only, so grants and row-level security already apply.

Developer shortcut added: `PIC_TEST_KEEP_DB=1` keeps an already seeded test schema (never for a full run); `CLM_TEST_TENANT` picks another tenant code for the journey on a kept database.

## 5. What remains

* `RENEWED` is a state with no caller: renewal extends the same contract (extension amendment, back to ACTIVE). Product decision needed whether a renewal
  should create a successor contract and mark the old one RENEWED.
* No cancel/withdraw state for a contract that never reached signature (the Technical Document state machine has none either).
* ACTIVE becomes EXPIRING on the renewal notice date (120 days before expiry; immediately for contracts shorter than 120 days). "Expiring in 90 days"
  counts ACTIVE and EXPIRING contracts. Confirm this reading of "Expiring".
* Contract leakage KPI and the OFF_CONTRACT flags come from posted invoices (spend cube); the contract view computes the same picture from PO lines.
  An off-contract flag does not yet compare supplier or validity window.
* PO quantity is checked at creation (released + drafts + this order), not again at release.
* Several live contracts for one material: source determination takes the first row of an unordered query; define a precedence rule (latest start, lowest price).
* Value contracts consume by quantity at line level (target quantity x price); consumption by free value is not tracked separately.
* The AI review is deterministic against the playbook. The LLM redline suggestion endpoint and clause extraction were not re-audited; no live LLM or e-sign provider was exercised.
* Rebates were verified through existing tests only. Documents tab (generic) not audited.
* UI: type-checked and linted only; no browser test was run (servers are in use by the lead).
* `test_new_tables_are_tenant_isolated` (intelligence modules) needs a second tenant to exist in the database; it passes in a full run and now also when the journey runs before it.

## 6. What the product owner must supply

* Legal-approved clause library per contract type, category and jurisdiction (CLM-PLAYBOOK: templates, categoryClauses, jurisdictions, fallbacks, positionRisk).
* Approval thresholds and chains (CONTRACT-APPROVAL, CONTRACT-AMENDMENT), consumption thresholds and renewal notice days per company code if they differ.
* An e-signature provider account and the settings `PIC_ESIGN_PROVIDER`, `PIC_ESIGN_URL`, `PIC_ESIGN_API_KEY`, `PIC_ESIGN_WEBHOOK_SECRET`; legal sign-off of the signature process.
* Decisions: meaning of EXPIRING/RENEWED, cancel state for unsigned contracts, source-determination precedence for overlapping contracts, whether `PIC_REQUIRE_IF_MATCH` is on in production.
* Real contracts, obligations and rebate agreements for the first tenant (the module is tested on generated data only).

## 7. Stand-ins for the inputs the product owner does not have yet

Each is labelled illustrative, runs the real code path, and is replaced by real input without code changes (details, file formats and commands: `docs/runbooks/clause_library.md`).

| Missing input (section 6) | Stand-in | Replace with |
|---|---|---|
| Legal-approved clause library | `seed/clause_library.py` (ILLUSTRATIVE SAMPLE, NOT LEGAL ADVICE): clauses per contract type with fallbacks, risk weight and escalation role, 8 category overlays, 7 governing-law variants; part of the `CLM-PLAYBOOK` rule set (new version for existing tenants) | CSV or JSON in the documented format, loaded with `tools/clause_library_load.py` |
| E-signature provider account | `PIC_ESIGN_PROVIDER=MOCK` with `tools/esign_mock.py` (port 8765): envelope, HMAC-signed webhooks, both parties signed, contract ACTIVE; shown as "Demo signature - not legally binding"; refused when `PIC_ENV` is production | the four `PIC_ESIGN_*` variables of DocuSign, Adobe Sign, Leegality or eMudhra |
| Real contracts of the first tenant | `data/erp_mock/KAC_CLM` (60 fictional contracts: master agreements with call-offs, NDAs, rate cards, SOWs; obligations, rebates, amendments, renewals, one in negotiation, one terminated) and the dataset pack `contracts_kac` | the client's contract register export in the layout of `PIC_ERP_Extract_Spec.md` section 10, loaded with `tools/contract_load.py` |

Decision recorded: `PIC_REQUIRE_IF_MATCH` is on in production and off by default only in dev and test (`config.py`, `platform/preconditions.py`); the web app sends `If-Match` automatically (`frontend/src/lib/pic/api.ts`).
