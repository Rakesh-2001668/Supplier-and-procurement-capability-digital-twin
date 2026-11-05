# Spend operations (M01 spend and category intelligence)

How spend gets into the cube, how it is classified, who handles exceptions, how plans are approved, how to keep the data clean, which rules to
change and how to load a new tenant. Spec: Blueprint M01 (section 7), Technical Document 3, 5.1, 11, 13.1, 15; analysis and traceability in
`docs/PIC_Spend_Cube_Analysis.md`. Amounts are minor units (paise); the cube is in the tenant's group currency (`tenant.base_currency`).

## 1. What is in the cube

One document family feeds it: the supplier invoice and the notes that correct it (`services/spend_feed.py`).

| Event | Spend lines |
|---|---|
| `invoice.posted` | one `INVOICE` line per invoice line, in the period of the invoice date, net of GST |
| `credit_note.received` | one negative `CREDIT_NOTE` line per credited invoice line, in the period of the note date, same category / supplier / plant / contract flag / FX rate as the invoice line (the credit nets the invoice exactly). A quantity credit is qty x invoice price; a price credit is qty x credit per unit and does **not** reduce the quantity |
| `debit_note.posted` | one positive `DEBIT_NOTE` line per debit-note line (a price correction follows its invoice line; an additional charge is classified from its text) |

Purchase orders and goods receipts are never spend: open orders are commitments (`GET /v1/spend/commitments`), so an order and its invoice are
never counted twice. ERP history (`source = ERP_HISTORY`) is loaded as signed lines by the cutover loader (`tools/erp_load.py`); a negative history
line counts as a credit note in the cube measures.

Events are relayed by the worker. The cube is as fresh as its last refresh **and** `freshness.pendingEvents = 0` (`GET /v1/spend/cube-status`).
`POST /v1/admin/spend/refresh` (or the `spend-cube-refresh` job every 5 minutes) rebuilds the periods whose lines changed; `{"full": true}`
rebuilds everything (needed after a change of the group currency, or after a migration: 0021 empties the summary on purpose, the first read or
the job rebuilds it). A cube that was never built is built whole.

Credit and debit notes recorded **before** release 0021 are not in the cube until `spend_feed.backfill_notes` runs (the dataset pack `spend_ops`
does it; for a tenant without the pack: `POST /v1/admin/spend/reevaluate` runs the classification and rule pass; call `backfill_notes` from a
maintenance shell once). It is idempotent and skips notes against invoices that are not in the cube.

## 2. Reading the cube safely

* Every spend read is restricted to the reader's ABAC scope before it aggregates: user attributes `plants`, `company_codes`, `categories`
  (rule ABAC dimensions) and `cost_centres`, `supplier_groups` (parent supplier codes). A user without the attribute (or `*`) is unrestricted. A
  total can never contain a figure from outside the scope; the response says which scope applied (`scope`).
* Filters are validated (`period_from` / `period_to` YYYY-MM with month 01-12 and from <= to, at most 200 values of 60 characters each, three-letter
  currencies); values are bound parameters.
* Exports (`GET /v1/spend/export?kind=cube|lines`) are capped at rule `exportMaxRows` (default 50,000), carry a SHA-256 in `X-Content-SHA256`, are
  audited (user, filter, rows, hash, scope) and neutralise spreadsheet formulas.

## 3. Classification stewardship

* The Spend Classification Agent classifies every invoice line that does not come from the material master. Confidence at or above rule
  `classificationThreshold` (default 0.80) is applied; below it the line waits in the steward queue (`GET /v1/spend/classification-queue`) with its
  value, age and due date (`reviewSlaDays`, default 5).
* Work the queue by value (largest first). Accept the proposal or reclassify. A reclassification of a line at or above `fourEyesAboveMinor` (default
  25 lakh) needs two different stewards who choose the same category: the first decision parks the review as `PENDING_SECOND`, the second confirms; a
  different category from the second steward reopens it. Accepting the agent's own proposal is one decision at any value.
* Teach the classifier: `learn_keyword` on a decision (or on a bulk decision) adds one word of 4-40 characters to the chosen category. A word that
  another category already owns is refused (409 `KEYWORD_CONFLICT`). The change is audited on the taxonomy node.
* Bulk: `POST /v1/spend/classification-reviews/bulk` decides every open review matching ids, a description text or a supplier (at most
  `bulkReclassifyMax`, default 500), each as a normal decision with its own result.
* A reclassification moves the credit and debit note lines of the same invoice line and marks the periods dirty, so the cube re-materialises.
* The taxonomy: `GET/POST/PATCH /v1/spend/taxonomy`. Levels: segment (1), family (2), category (3), commodity (4, optional). A node with spend lines cannot
  be retired. The UNSPSC code set is licensed; the tenant maps its own codes (rule TAXONOMY-UNSPSC).

## 4. Maverick spend

Nine rules: PO_AFTER_INVOICE, SPLIT_PO, NON_CATALOGUE, OFF_CONTRACT, OFF_CONTRACT_PRICE, ONE_TIME_VENDOR (BP 7.2) and NO_GOODS_RECEIPT, PO_NOT_APPROVED,
OVER_INVOICED (payment controls). All nine are evaluated when an invoice is fed (document rules read the order, the receipts and the invoice).

| Change | How |
|---|---|
| Switch a rule off, change its severity, owner role, SLA days or escalation role from a date | `POST /v1/spend/maverick-rules/{code}/versions` (tenant administrator): a new effective-dated version of rule set `MAVERICK-RULES`; the version applies to documents dated from its effective date; the `maverick_rule` rows stay the baseline |
| Change a threshold (`oneTimeVendorLimitMinor`, `overInvoicedTolerancePct`, `acceptExceptionLimitMinor`, `requireReasonCode`) | `POST /v1/admin/rules` for rule set `SPEND-GOVERNANCE` (validated; effective-dated) |

Lifecycle: `OPEN` -> `DISPOSED` (disposition `ACCEPTED_EXCEPTION`, `POLICY_BREACH`, `FALSE_POSITIVE`) or `RECOVERY_OPEN` -> `RESOLVED` (recovery booked,
`POST /v1/spend/maverick-hits/{id}/resolve`). `lifecycle` in the worklist reads OPEN / ACCEPTED / RECOVERY / RESOLVED. `ACCEPTED_EXCEPTION` and
`FALSE_POSITIVE` need a reason code (EMERGENCY_BREAKDOWN, SOLE_SOURCE, CONTRACT_NOT_LOADED, SUPPLIER_CHANGE_PENDING, CATALOGUE_GAP, DATA_ERROR, RULE_TOO_BROAD,
RULE_RETIRED, OTHER) and a comment; accepting an exception above `acceptExceptionLimitMinor` (default 1 crore) needs the procurement head or CPO.
Each hit has an owner (category manager of the category's plan, else the first active holder of the rule's owner role), a due date (rule SLA by
severity: Critical 3, High 5, Medium 10, Low 15 days) and savings at risk (price paid above contract / standard price; the excess for OVER_INVOICED).
The job `spend-sla` (hourly) escalates hits past their due date to the rule's escalation role, at most twice; `POST /v1/spend/maverick/escalate`
runs it now. `GET /v1/spend/maverick/repeat-offenders` lists suppliers and categories with repeated hits.

## 5. Supplier duplicates

`GET /v1/spend/duplicates` shows clusters: same PAN or GSTIN (score 1.00), same bank account (0.95), or a name similarity of at least 0.92 on the normalised
token-sorted names with equal digits (Plant 1 and Plant 2 are different suppliers). `POST /v1/spend/duplicates/scan` stores them. A steward or category manager
proposes a merge under a survivor (`propose-merge`); a **second** steward approves it as a task in the inbox (the proposer cannot). Approval records the
corporate-parent link, which the cube uses to roll the records up; **nothing is merged, blocked or deleted**: the ERP merge stays a master-data decision.
`dismiss` records why two records are different entities; a dismissed cluster does not come back while its members stay the same.

## 6. Category plans

`POST /v1/category-plans` drafts a plan per category with addressable spend (Kraljic position from spend and supply risk, levers, a dated wave plan, a budget from
the forecast, a savings target by lever capped at `planMaxSavingsPct` of the addressable spend). Edit a draft (`PATCH`): budget >= 0, target <= budget and <=
the cap, levers from the catalogue, savings by lever adding up to the target, waves with start <= end, at least `planWaveMinDays` days, inside the fiscal
year and the next. `submit` -> `IN_APPROVAL` and a task for the procurement head; the owner and the submitter can neither approve nor reject
(SOD_CONFLICT). Approval supersedes the previous approved version. `revise` makes a new draft version of an approved plan (one open revision at a
time). `GET /v1/category-plans/{ref}/pipeline-links` lists the sourcing events and savings initiatives of the category by reference. The rule
`planRequiresSubmission` (default false) forbids approving a draft that was never submitted.

## 7. Data quality

`GET /v1/spend/quality` runs 14 checks (unclassified spend, category not in taxonomy, unknown supplier, FX rate missing / stale, duplicate lines, zero
or wrongly signed lines, no document lineage, intercompany counted as addressable, future period, outlier amount, feed or cube out of date, months without
spend, cube differs from the lines) and returns a 0-100 score; `POST /v1/spend/quality/run` stores it (history in `GET /v1/spend/quality/history`; the job
`spend-quality` runs daily). Every check names its remedy. Tenant limits: `staleFeedHours`, `fxMaxAgeDays`, `outlierAmountMinor`.

## 8. Forecast

`GET /v1/spend/forecast` picks, per category, the best of Holt, seasonal naive and Holt-Winters by a rolling-origin back-test (last 6 origins, 1-3 months
ahead), reports its MAPE and an 80% band (80th percentile of the back-test errors). `POST /v1/spend/forecast/snapshot` (the job `spend-forecast-snapshot`
monthly) stores the forecast as issued; `GET /v1/spend/forecast/accuracy` compares issued forecasts with the actuals (MAPE per horizon, bias, band coverage).

Accuracy needs history: below 12 judged forecast points over 3 months `GET /v1/spend/forecast/accuracy` and the KPI `M01.SPEND_FORECAST_MAPE` answer
`INSUFFICIENT_DATA` with the counts they have (no percentage). The forecast snapshots of the monthly job build that history; do not read a number into the first months.

The tenant admin sees the maverick work list, the rules and the cube status (to version a rule, escalate, or refresh) but holds no `spend:read`: it cannot
open the analytics or decide, recover or approve anything.

## 9. Loading a new tenant

1. Provision the tenant and organisation (`admin_operations.md`): company codes, plants, cost objects, users with the roles CATEGORY_MANAGER,
   PROCUREMENT_HEAD, CPO, MDM_STEWARD (two), FINANCE_CONTROLLER and the ABAC attributes you need.
2. Set the group currency (`tenant.base_currency`) and load the FX series (daily or weekly per currency to the group currency; the cube converts at the
   rate valid on the document date; a currency without a rate is counted in `fxMissingLines`, never guessed).
3. Load suppliers (with `parent_supplier_id` where a group exists and `segment = INTERCOMPANY` for group companies), materials and categories, then the
   taxonomy (`/v1/spend/taxonomy`) and the keyword lists.
4. Load 24-36 months of PO and invoice history with `tools/erp_load.py` (spend total must tie to the GL within 0.5%: TD 12.4) and run
   `POST /v1/admin/spend/refresh {"full": true}`.
5. Set the rule values you own: `SPEND-GOVERNANCE` (threshold, limits, SLAs, fiscal year start month), maverick rule versions, KPI thresholds.
6. Run `GET /v1/spend/quality` and clear the findings before anyone relies on the numbers.
7. Mock data for demonstrations: `python -m app.pic.seed.datasets spend_ops` (see `backend/data/erp_mock/KAC_SPEND/README.md`; everything is labelled MOCK).

## 10. Jobs

| Key | Schedule | What |
|---|---|---|
| `spend-cube-refresh` | every 5 minutes | rebuild the dirty periods (the whole cube if never built) |
| `spend-sla` | hourly at :15 | escalate maverick hits past their SLA; reports the steward queue ageing |
| `spend-quality` | daily 05:00 | data-quality assessment, stored |
| `spend-forecast-snapshot` | 2nd of the month 05:30 | store the forecast as issued |

## 11. Incidents

* The numbers look stale: `GET /v1/spend/cube-status` (`dirtyPeriods`, `pendingEvents`, `asOf`). Pending events: the worker/outbox (`workflow-incidents.md`). Dirty
  periods: run the refresh job; if it fails, read `job_run`.
* Totals differ from the GL by more than 0.5%: `GET /v1/spend/quality` -> `CUBE_TIE_OUT`, `FX_RATE_MISSING`, `DUPLICATE_LINES`, `NO_LINEAGE`.
* A spend page answers 412 or hangs: reads never wait for the refresh lock (`spendview:<tenant>`); if one does, look for a long refresh in `pg_stat_activity`
  (`GET /v1/spend/cube-status` shows `dirtyPeriods`). A very slow quality report right after a bulk load: `ANALYZE pic.spend_line` (the pack does it).
* A user sees too little or too much: read their `attributes` (`plants`, `company_codes`, `categories`, `cost_centres`, `supplier_groups`) and the ABAC rule mode
  (ENFORCE restricts; AUDIT and OFF do not). The cube response shows the applied `scope`.
