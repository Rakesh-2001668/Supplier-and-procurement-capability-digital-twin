# M01 Spend Cube and Category Intelligence: analysis, defects, build

Second pass, 4 November 2026. Scope: spend cube (SPD-01..09), taxonomy and classification, maverick rules, supplier duplicates, contract compliance, category
strategy, forecast, KPIs, data quality, export, scale. Sources: Blueprint section 7 (M01), 17 (savings baselines), Technical Document 3, 5.1 (lineage P10), 6, 9, 11,
12.4, 13.1, 15; the code in `services/spend*.py`, `api/intelligence.py`, `api/spend_ops.py`, the models and the tests. House style as in
`PIC_Finance_Module_Analysis.md`: every requirement is mapped to code and a proving test and marked VERIFIED, CODE ONLY, PARTIAL, MISSING or WRONG.
Migration `0021_spend_cube_complete` (head after 0020; the sourcing engineer's 0022 chains after it). Runbook: `docs/runbooks/spend_operations.md`. Mock data:
`backend/data/erp_mock/KAC_SPEND/README.md`.

## 1. Result in one table

| | Before this pass | After |
|---|---|---|
| Requirements traced (section 2) | 68 | 68 |
| VERIFIED | 19 | 57 |
| CODE ONLY | 3 | 3 |
| PARTIAL | 15 | 6 |
| MISSING | 20 | 1 (ClickHouse, by decision) |
| WRONG | 11 | 1 (a platform convention the owner must confirm, see 2.3) |
| Defects and control gaps found and fixed (section 3) | | 19: 16 defects of existing behaviour (S1-S11, S15, S16, S19-S21) and 3 control gaps (S12-S14), each with a `test_spend2_*` regression |
| New tests | | 42 in `tests/pic/test_spend_second_pass.py`, 12 in `tests/pic/test_datasets_spend_ops.py` |

The WRONG that remains is the JPY exponent question: the platform stores every currency with two implied decimals; this is a platform convention the owner must confirm, not a spend defect.

## 2. Traceability

Status after the pass; "was" gives the status before when it changed. Tests are in `test_spend_second_pass.py` (`test_spend2_*`) unless named.

### 2.1 Feed and lineage

| # | Requirement (source) | Code | Test | Status |
|---|---|---|---|---|
| 1 | Cube from PO, invoice, contract, consumption (BP 7.1) | `spend_feed` (invoice, credit, debit notes), `spend_cube.commitments` (open POs), `contracted` flag, `consumptionMinor` = contract consumption | s1, test_wave1_spend_kpi commitments | PARTIAL: goods-issue consumption is not a source |
| 2 | spend_line with lineage to the document (TD 3, P10) | `invoice_line_id`, `po_line_id`, `po_ref`, `document_type`, `document_ref`; drill `GET /v1/spend/lines` | w10 | VERIFIED (was PARTIAL: no document type) |
| 3 | Credit notes net the spend, in the right period (BP 7.4) | `spend_feed.feed_credit_note`, event `credit_note.received` | s1, s2 | VERIFIED (was WRONG, S1, S2) |
| 4 | Debit notes add (price correction, charge classified from text) | `feed_debit_note`, `debit_note.posted` | s3, s3b | VERIFIED (was MISSING, S3) |
| 5 | Cancelled / rejected invoices never counted | only `invoice.posted` is consumed | s15 (indirect) | CODE ONLY (no invoice reversal flow exists to test) |
| 6 | PO, GR and invoice never double counted; open orders are commitments | feed design; `spend_commitment_summary` | test_wave1_spend_kpi `commitments_equal_open_po_value` | VERIFIED |
| 7 | Partial invoices and partial credits | quantity basis per line; credit by qty or by price | s1, s2 | VERIFIED |
| 8 | Non-PO invoice line does not break the feed | `feed_invoice` without `po_line` | s15 | VERIFIED (was WRONG, S15) |
| 9 | Notes recorded before the cube knew them | `spend_feed.backfill_notes`, run by the pack | s1 (idempotent), test_datasets_spend_ops | VERIFIED |
| 10 | Intercompany suppliers excluded from addressable (BP 7.4) | `spend.addressable_for` (segment INTERCOMPANY, IC categories) | s5 | VERIFIED (was WRONG, S5) |
| 11 | Spend history ties to the GL within 0.5% (TD 12.4) | `tools/erp_load.py` tie-out | test_datasets_erp_client_kac | CODE ONLY here (owned by the loader) |

### 2.2 Dimensions and measures

| # | Requirement | Code | Test | Status |
|---|---|---|---|---|
| 12 | Category L1-L4 | `category_l1..l4`, taxonomy admin allows commodities (level 4), classification into level 4 | w15 | VERIFIED (was PARTIAL) |
| 13 | Supplier parent / child | `parent_supplier`, roll-up in the summary | test_wave1_spend_kpi | VERIFIED |
| 14 | Plant, company code, cost centre, WBS, material group, period, currency | summary grain | test_wave1_spend_kpi | VERIFIED |
| 15 | Buyer | `buyer` dimension and filter (`spend_line.buyer_id` from the PO) | s17 | VERIFIED (was MISSING) |
| 16 | Contract flag, maverick flag, addressable | summary columns | test_wave1_spend_kpi | VERIFIED |
| 17 | Fiscal year / quarter, calendar year / quarter | `fiscal_year`, `fiscal_quarter`, `year`, `quarter` dimensions; start month from rule `fiscalYearStartMonth` | s1, w9 | VERIFIED (was MISSING) |
| 18 | Spend, PO count, invoice count | measures | test_wave1_spend_kpi | VERIFIED |
| 19 | Invoiced, debit notes, credit notes, committed | `invoicedMinor`, `debitNoteMinor`, `creditNoteMinor`, `commitments` | s1, w9 | VERIFIED (was MISSING) |
| 20 | Price variance (vs contract / standard price, vs last price) | measures; credit lines reduce the variance pro rata | s2, s19 | VERIFIED |
| 21 | Contract coverage %, maverick %, addressable share | shares of ADDRESSABLE spend, one rounding rule | s8 | VERIFIED (was WRONG, S8) |
| 22 | Concentration HHI | `spend.hhi_of`: parent roll-up, net-negative suppliers excluded, 0-10,000 | s9 | VERIFIED (was WRONG, S9) |
| 23 | YoY, QoQ, YTD, run-rate, share of spend | `spend_analytics.comparison` | w9 | VERIFIED (was MISSING) |
| 24 | Pareto / ABC, tail suppliers, suppliers per category | `pareto`, `category_structure` | w9 | VERIFIED (was MISSING) |
| 25 | Spend under management, addressable, coverage | `spend.portfolio` | test_wave1_spend_kpi | VERIFIED |
| 26 | Savings potential by lever | `savings_potential` (indicative, never the ledger) | w9 (shape and sum) | PARTIAL: the lever percentages are assumptions the owner sets (`aggregationSavingPct`, `contractSavingPct`) |
| 27 | Measure set of a fiscal year in one call | `GET /v1/spend/summary` | w9 | VERIFIED |

### 2.3 Currency and period

| # | Requirement | Code | Test | Status |
|---|---|---|---|---|
| 28 | FX at the invoice / posting date, rate and date stored | `rate_for_line`; deferred conversion now uses the line's `document_date` | s7, test_wave1_spend_kpi | VERIFIED (was WRONG, S7) |
| 29 | Missing rate: counted, never guessed | `fx_missing_lines`, DQ check | test_wave1_spend_kpi, w12 | VERIFIED |
| 30 | Rate too old for the document | DQ check `FX_RATE_STALE` (`fxMaxAgeDays`) | s18 | VERIFIED (was MISSING) |
| 31 | JPY and other currencies with other minor-unit exponents | platform stores two implied decimals for all; `currency.decimals` is not used | none | WRONG until the owner decides (section 7) |
| 32 | Rounding half up, one rule | `spend_cube._pct`, `ROUND_HALF_UP` in conversions | s8 | VERIFIED (was WRONG, S8) |
| 33 | Fiscal year boundary 31 March / 1 April | `windows`, `time_label` | s1, w9 | VERIFIED |
| 34 | Prior-year comparison, YTD | `comparison` | w9 | VERIFIED |
| 35 | Data freshness | `freshness`: as-of, dirty periods, `pendingEvents`, `feedBehind` | s17 | VERIFIED (was PARTIAL) |
| 36 | Read-after-write with a new invoice | eventually consistent (outbox relay); the response says what waits | s17 | PARTIAL by design |

### 2.4 Security and controls

| # | Requirement | Code | Test | Status |
|---|---|---|---|---|
| 37 | ABAC on every spend read: plant, company code, category | `spend_scope` applied in `_conditions`, `portfolio`, overview, treemap, suppliers, compliance, forecast, hits, reviews, plans, lines, export | s4, s4b, s4c | VERIFIED (was MISSING, S4) |
| 38 | Cost-centre and supplier-group scope | `cost_centres`, `supplier_groups` attributes | s4b | VERIFIED (was MISSING) |
| 39 | Tenant isolation (RLS) | forced RLS on every table, new tables included | test_wave1_spend_kpi `summaries_are_tenant_isolated` | VERIFIED |
| 40 | Audit of decisions, dispositions, exports, rule versions | `audit.record` on each | w5, w11, test_datasets_spend_ops (chain verifies) | VERIFIED |
| 41 | Filter validation, injection-style input, bounded lists | `CubeFilter.validate` | s10 | VERIFIED (was PARTIAL) |
| 42 | Pagination, cursors, limits | keyset cursor on `/v1/spend/lines`, `limit` 1-5000 | w10, s10 | VERIFIED (was MISSING) |
| 43 | Empty and single-line cubes | all reads | s15 | VERIFIED |
| 44 | Concurrent decisions on one item | row lock before the state check | s16 | VERIFIED (was WRONG, S16) |
| 45 | Export of any slice: hash, row cap, audit | `GET /v1/spend/export` | w11, w16 | VERIFIED (was MISSING) |

### 2.5 Classification, maverick, duplicates, plans

| # | Requirement | Code | Test | Status |
|---|---|---|---|---|
| 46 | Classification below 0.80 goes to the steward queue (BP 7.4), threshold per tenant | `classify_line`, rule `classificationThreshold` | test_intelligence_modules | VERIFIED |
| 47 | Queue with value, ageing, SLA | `review_queue`, `queue_summary` | w3 | VERIFIED (was MISSING) |
| 48 | Four-eyes on a reclassification above a value | `decide_review` (`PENDING_SECOND`) | w1 | VERIFIED (was MISSING) |
| 49 | Bulk reclassify with audit; keyword learning | `bulk_reclassify`, `learn_keyword` | w2 | VERIFIED (was MISSING) |
| 50 | Reclassification re-materialises the cube, credit lines follow | `_set_category`, dirty periods | s12 | VERIFIED |
| 51 | Auto-classified count follows the tenant threshold | summary joins `classification_review` instead of a fixed 0.80 | test_wave1_spend_kpi (KPI) | CODE ONLY |
| 52 | Nine maverick rules, tenant-configurable | `MAVERICK_RULES`, rule set `MAVERICK-RULES` (effective-dated versions), `SPEND-GOVERNANCE` values | w4 | VERIFIED (was PARTIAL) |
| 53 | Live evaluation of the six BP rules, no false hits | `_po_flags` (PO date in the tenant time zone, contract valid on the PO date and plant) | s6, s6b, s6c, s6d | VERIFIED (was WRONG, S6) |
| 54 | NO_GOODS_RECEIPT, PO_NOT_APPROVED, OVER_INVOICED live | `_po_flags` | s6 | VERIFIED (was MISSING: legacy seed only) |
| 55 | SPLIT_PO within 7 days | from the PO risk factor `SPLIT_PATTERN` (rule `splitWindowDays`) at PO creation | s6 (not directly) | PARTIAL: no re-detection on ERP history without dates |
| 56 | Owner, disposition, reason, SLA, escalation, recovery, repeat offenders, savings at risk | `dispose`, `resolve_recovery`, `escalate_overdue`, `repeat_offenders` | s13, w5, w6 | VERIFIED (was PARTIAL) |
| 57 | Duplicate-supplier clusters: PAN, GSTIN, bank, name | `find_clusters` | w7 | VERIFIED (was PARTIAL, S20) |
| 58 | Merge proposal into the MDM path, never automatic | task `SPEND_SUPPLIER_MERGE` approved by a second steward, then the parent link | w7 | PARTIAL: uses the workflow inbox, not the `SupplierMasterChange` request (which has no merge field group) |
| 59 | Plan validations (budget, target vs addressable spend, dated waves, lever catalogue) | `validate_plan` | w8 | VERIFIED (was PARTIAL) |
| 60 | Plan versions, submission, approval chain, owner and submitter cannot approve | `submit_plan`, `revise_plan`, `approve_plan`, task `CATEGORY_PLAN_APPROVAL` | s14, w8 | VERIFIED |
| 61 | Link to the sourcing pipeline by reference | `GET /v1/category-plans/{ref}/pipeline-links` | w8 | VERIFIED (was MISSING) |

### 2.6 Forecast, quality, KPIs, scale

| # | Requirement | Code | Test | Status |
|---|---|---|---|---|
| 62 | Forecast by category / plant with an 80% band, method documented, back-tested | `spend_forecast` (Holt, seasonal naive, Holt-Winters chosen by back-test; band from back-test errors) | w13 | VERIFIED (was PARTIAL) |
| 63 | Forecast error measured over time | snapshots as issued, `accuracy` | w13, test_datasets_spend_ops | VERIFIED (was MISSING) |
| 64 | Data-quality report, score, history | `spend_quality` (14 checks), `spend_quality_run` | w12, test_datasets_spend_ops | VERIFIED (was MISSING) |
| 65 | KPIs of BP 7.5 (5) | `kpi.py` | test_wave1_spend_kpi | VERIFIED; plant scope added (was WRONG: the plant filter was ignored, S18) |
| 66 | More M01 KPIs: tail spend, suppliers per category, forecast error, savings pipeline, queue and hit overdue, data quality | seven KPIs registered | w14 | VERIFIED (was MISSING) |
| 67 | Cube query < 3 s on 50 M lines, near-real-time refresh (TD 15, AD-04) | summary tables, incremental refresh job (5 min) | `tools/volume_gen.py --measure` | PARTIAL: measured at 0.5 M and 2.5 M lines, extrapolated (section 5) |
| 68 | ClickHouse cube (TD AD-04) | Postgres summary tables | | MISSING by decision (the owner's brief: Postgres only) |

## 3. Defects and control gaps found and fixed

Every one has a regression test; none weakens a control. S12-S14 are control gaps (behaviour the specification asks for that did not exist), the others are defects of existing behaviour.

| # | Defect | Evidence | Fix | Test |
|---|---|---|---|---|
| S1 | A credit note submitted after the invoice was posted never reached the cube (the consumer read only the credit notes that existed at posting; `submit_credit_note` emitted no event). On KAC, 20 credit notes were missing. | probe: 0 `CREDIT_NOTE` lines before the backfill | event `credit_note.received`, negative lines in the period of the note, same attributes and FX rate as the invoice line, backfill | s1 |
| S2 | A price (value) credit was netted as a quantity credit: a Rs 100 / unit credit on 10 units removed all 10 units instead of Rs 1,000 | code: `credited[line] += qty` whatever the entry kind | value credit = qty x credit per unit; the invoice keeps its quantity | s2 |
| S3 | Debit notes (`debit_note.posted`) never fed the cube | no consumer | `DEBIT_NOTE` lines; a charge is classified from its text | s3, s3b |
| S4 | No spend read applied the ABAC scope: a user restricted to plant P2 saw all plants in the cube, overview, treemap, suppliers, compliance, forecast, hits, reviews, plans and counts | code; reproduced by the test on plants, categories, cost centres, supplier groups | `spend_scope`, applied before every aggregation | s4, s4b, s4c |
| S5 | Invoices of an intercompany supplier were addressable (only category IC-TRANSFER was excluded) | code | `addressable_for` | s5 |
| S6 | NO_GOODS_RECEIPT, PO_NOT_APPROVED, OVER_INVOICED were defined but only the legacy seed ever set them; PO_AFTER_INVOICE compared the UTC date of the PO with the invoice date; ONE_TIME_VENDOR compared a USD amount in cents with the rupee limit in paise; OFF_CONTRACT used the contract status at processing time, ignoring the PO date and the plant | code | `_po_flags`, group-currency value, tenant calendar day | s6, s6b, s6c, s6d |
| S7 | A late-converted foreign line took the rate of the END of its period, not of its invoice date | code | `document_date` column; conversion by the document date | s7 |
| S8 | The cube divided contracted spend by ALL spend, the overview and the KPIs by addressable spend; the overview rounded half-even, the cube half-up | code | one definition (addressable base), one rounding | s8 |
| S9 | HHI was computed on child records (a group split in two looked unconcentrated) and a supplier with net credits produced shares above 100% | code | parent roll-up, positive net spend only | s9 |
| S10 | `period_from=2026-13` accepted; from > to accepted; unbounded filter lists; cube ties ordered arbitrarily | probe | `CubeFilter.validate`, ordered ties | s10 |
| S11 | The admin refresh and the scheduled catch-up (`dirty_only`) did nothing on a cube that was never built; the job named in the docs (`spend.refresh_spend_views`) was not registered | code, probe | build whole when never built; four jobs registered | s11, w5 |
| S12 | (Design check on the new note lines) credit-note lines must not enter the steward queue and must follow a reclassification | | `_set_category` follows `invoice_line_id` | s12 |
| S13 | A hit could be accepted or dismissed with a comment only (no reason code, no value limit) | | `reason_code` required, limit for accepting large exceptions | s13 |
| S14 | A plan's submitter could approve it; a plan could be approved without validation | | SoD on submitter, `validate_plan` | s14 |
| S15 | An invoice line without a PO line raised an exception in the consumer (the event was retried and finally dead-lettered) | code | fallback plant and category | s15 |
| S16 | Two stewards (or owners) deciding the same item at once both read OPEN; the last write won silently | reproduced with two threads | row lock, second sees 409 | s16 |
| S19 | The compliance leakage added price variances of all currencies as if they were rupees | code | group-currency variance | s19 |
| S20 | Duplicate-supplier clusters joined "Plant 1" and "Plant 2" Engineering (name ratio 0.96 with the old 0.86 threshold; digits ignored) | arithmetic | threshold 0.92, digits must agree, PAN / GSTIN / bank signals | w7 |
| S21 | The M01 KPIs ignored the plant filter | code | `portfolio(plant=)` and PLANT scope | w14 |

Found while testing the new code: filtering the cube by an unknown buyer returned the "no buyer" rows (the nil UUID stands for no buyer); fixed in the same pass (s17). The row lock added for S16 re-read a review before the bulk decision's channel was written, so `channel = BULK` was lost; found by the dataset test, fixed (the channel is written after the decision) and covered in w2. A huge line (10^18 minor units) would have overflowed the BIGINT cube sums and stopped the refresh for the tenant: a check constraint (`abs(amount_minor) <= 10^15`) now refuses it (s20).

### 3.1 Second round (findings of the front-end walk and the full-suite run)

| # | Finding | Fix | Test |
|---|---|---|---|
| T0 | The plan budget (`generate_plans`) took the back-tested forecast; for RUBBER-SEALS on AXN the projection was exactly half of the trailing spend, so the budget of the base-seed plan CP-114 fell from 2,353,333,328 to 1,176,666,664 paise and the module-cases pack (a 2.03 crore requisition against that budget) hit a hard stop | the budget of a plan uses `spend_forecast.plan_projection`, the original Holt projection (alpha 0.4, beta 0.2, 24 months), so a better forecast method does not move the budgets that other controls read | datasets: module_cases |
| T1 | TENANT_ADMIN had no `spend:read`: the maverick tab (work list, rules) and the cube status answered 403 although the admin owns the actions on that tab (rule versions `admin:rules`, escalate and refresh `admin:integration`) | the three read routes accept `spend:read` or `admin:rules` or `admin:integration`. The admin role is NOT given `spend:read`: the analytics, the queue, dispositions, recoveries and plans stay closed to it (the admin cannot decide a hit it can see) | t1 |
| T2 | A read (`GET /v1/spend/duplicates`, any cube read) could answer 412 STALE_WRITE: it started a refresh of dirty periods, loaded the refresh-state row, waited for the refresh lock held by another request and then updated its stale copy | a read takes the refresh lock with `pg_try_advisory_xact_lock` and, when it is not free, serves the data as it is (`freshness.stale` and `dirtyPeriods` say what is pending); a refresh that is asked for waits and reads the state row again under the lock (`populate_existing`) | t2 |
| T3 | `GET /v1/spend/duplicates` took about 6 s idle on KAC (500 suppliers) and 20 s under load: the name comparison ran a full difflib ratio for every neighbour | the length bound and the letter-count bound (both upper bounds of the ratio) skip pairs that cannot reach 0.92; the result is the same, 0.8 s | t3 |
| T3b | `GET /v1/spend/quality` took 166 s once on KAC: not reproducible on an idle machine (1.8 s for 34,000 lines, 38 statements); the likely cause is planner statistics right after a bulk load | the pack runs ANALYZE on the spend tables at its end; no change to the checks | |
| T4 | KPI `Spend forecast error (MAPE)` showed 755.7 % on AXN (a handful of forecasts judged against small actual months) | `spend_forecast.accuracy` returns `status: INSUFFICIENT_DATA` with `reason` and no MAPE / bias / band coverage below `MIN_JUDGED = 12` judged forecast points or `MIN_MONTHS = 3` months; `wapePct` (error as a share of the total actual) is always given. KPI detail: `status`, `reason`, `judged`, `series`, `months`, `minimumJudged`, `minimumMonths`, `wapePct`, `bandCoveragePct` | t4 |
| T5 | CI sorts text by English locale rules, the local database bytewise: a mismatch between SQL ORDER BY and Python `sorted()` hides locally | the pack and the test helper that pick or compare by text order use `COLLATE "C"`; the spend files and the spend pack were run on a database with English collation | |

## 4. What was added

* **Calculations** (`spend_analytics.py`): YTD / prior-year, YoY, QoQ, run-rate, share of spend; Pareto A/B/C (80% / 95%) and the long tail; suppliers per category and
  HHI per category; savings potential by lever (consolidation, contract coverage, price recovery); the measure set of a fiscal year; drill to lines with keyset cursors.
* **Cube** (`spend_cube.py`): document types, buyer, fiscal and calendar roll-ups, invoiced / debit / credit measures, freshness with waiting documents, scope,
  validation, deterministic ties.
* **Checks** (`spend_quality.py`): 14 data-quality checks with a 0-100 score and a stored history.
* **Workflows** (`spend_workflow.py`): steward queue with SLA and four-eyes, bulk decisions, keyword learning, maverick rule versions, hit lifecycle with escalation and recovery,
  repeat offenders, duplicate clusters with a two-person merge, plan validation / edit / submit / reject / revise, four scheduled jobs.
* **Forecast** (`spend_forecast.py`): three methods chosen by back-test, 80% band from the back-test errors, snapshots and measured accuracy.
* **API** (`api/spend_ops.py`, 34 routes; section 8 lists them for the front end).
* **KPIs**: tail spend %, suppliers per category, forecast error, savings pipeline, steward queue past SLA, hits past SLA, data-quality score; the five BP KPIs gained the PLANT scope.
* **Migration 0021** (additive; `spend_line` and `category_plan` unique keys widen, nothing is dropped; the summary is rebuilt on first read; existing reviews, hits and rules get their SLA values).

## 5. Performance

`tools/volume_gen.py --scale S --measure` generates S x 50 M spend lines (S x 5 M invoices a year) by COPY into a scratch database, builds the summary, then times the
eight main queries through the service functions with a category-manager principal (`RUNS` = 5 runs each in the tool; the table below is a quiet re-measure of 7 runs each on the
kept scratch databases, p95 is the slowest of the 7). Local PostgreSQL 16 on a developer laptop, default settings, nothing tuned.

| Scale | Spend lines | Summary rows | Full refresh | Refresh of one period |
|---|---|---|---|---|
| 0.01 | 500,000 | 4,492 | 76 s | 0.24 s (small last period) |
| 0.05 | 2,500,000 | 22,030 | 1,962 s | 26 s for a period of 58,600 lines |
| 0.2 | 10,000,000 | not run | | |

| Query | 0.01: p50 / p95 (s) | 0.05: p50 / p95 (s) |
|---|---|---|
| by category | 0.15 / 0.32 | 0.27 / 0.42 |
| by supplier (child) | 0.16 / 0.33 | 0.33 / 0.45 |
| by category x period | 0.45 / 1.19 | 0.36 / 1.29 |
| by category L1 x plant | 0.14 / 0.22 | 0.15 / 0.21 |
| by fiscal year x parent supplier | 0.53 / 1.84 | 0.86 / 1.03 |
| filtered (category, from 2025-01) by supplier + commitments | 0.10 / 3.40 | 0.08 / 2.35 |
| overview SPD-01 | 0.14 / 0.22 | 0.16 / 0.23 |
| YoY / YTD comparison by category | 0.09 / 0.16 | 0.13 / 0.22 |

(0.01 was measured while two test suites ran on the same machine, so its p95 are noisy.) Seven of eight queries have p95 under 2 s at 2.5 M lines; the 2-3 s
spikes of the filtered query are the commitments summary, which a read rebuilds when it is older than 5 minutes (`ensure_commitments_fresh`; the 5-minute job
normally keeps it fresh, so the spike is the first read after the job was stopped). A fiscal-year roll-up used to return one row per month and take 5-10 s at 2.5 M
lines; the database now rolls the months up (`time_expression`).

What the numbers do and do not say:

* The queries read the summary, whose size depends on the number of distinct combinations (period x category x supplier x plant x ...), not on the number of lines:
  22,030 rows for 2.5 M lines in this generator (100 suppliers). At 50 M lines with 2,000 suppliers the generator's own arithmetic gives 150,000-400,000 summary rows, i.e.
  10-20 times the 0.05 table; the grouped scans scale about linearly with the rows, so the 3 s target at 50 M lines is plausible (p95 about 1-3 s for the heaviest roll-ups) but
  **not demonstrated**. The 0.2 scale was not run: the Python generator needed 2 hours for 2.5 M lines.
* The refresh is dominated by reading the period's lines. The generator writes periods interleaved, so one period's 58,600 lines lie on 39,921 different pages (an index scan
  of random reads, 26-57 s); in a real tenant the lines of a month are appended together. The honest design answer at 50 M lines is declarative partitioning of `spend_line` by period
  (the unit of refresh) or a delta refresh; neither is built. A 5 M invoices-a-year tenant has about 0.8 M lines in a month: an incremental refresh of the current month is
  minutes, not the "< 5 minutes near-real-time" of TD AD-04 on this hardware.
* Both `count(DISTINCT ...)` columns of the refresh were measured and re-written with window functions and with pre-aggregation; neither was faster on this data, so the SQL is unchanged.

## 6. Datasets

Pack `spend_ops` (see `backend/data/erp_mock/KAC_SPEND/README.md`): KAC gains 7,539 lines, 101 suppliers, 212 FX rates, 150 hits, 132 reviews, 8 plans (+1 revision),
1,008 forecast snapshots, about 200 service-driven workflow items, a data-quality run; AXN gains 1,350 lines, 24 suppliers, 36 hits, 21 reviews and about 120 workflow items. Local
run time: KAC 105-175 s, AXN about 40 s. Deliberate defects DQ1-DQ8 are listed in the README and found by the report.

## 7. What remains

* Goods-issue consumption as a spend source; buyer for ERP history lines (purchasing group); SPLIT_PO re-detection from spend lines (needs document dates in the history).
* A delta refresh for the current month at very large volume; a measured run at 10 M and 50 M lines; ClickHouse if the Postgres summary proves too slow at the customer's scale.
* Invoice reversal after posting has no process in the platform; when it exists it must emit credit lines.
* The merge of duplicate suppliers in the ERP stays a manual master-data task; only the parent link is automated.
* The front end for everything in section 8 (a separate pass).
* JPY and other non-two-decimal currencies: decide whether amounts are stored in the currency's own minor unit (then the conversion needs the exponent) or, as today, with two implied decimals.
* Classification learning is keyword-based; an ML retraining loop from the steward decisions is not built (the decisions are stored and exportable for it).

## 8. What the owner must supply

* The tenant's taxonomy (UNSPSC is licensed; the mapping rule `TAXONOMY-UNSPSC` carries titles only) and keyword lists; the group currency and the FX source (FBIL feed or treasury file).
* Rule values (all in rule set `SPEND-GOVERNANCE`, effective-dated): classification threshold, four-eyes value (default Rs 25 lakh), steward SLA days (5), maverick SLAs by severity
  (3 / 5 / 10 / 15), accept-exception limit (Rs 1 crore), OVER_INVOICED tolerance (2%), one-time-vendor limit (Rs 5 lakh), plan savings cap (15% of addressable spend), stale-feed hours (48),
  FX age (10 days), outlier limit, export cap (50,000), consolidation and contract saving percentages (3% / 4%), fiscal-year start month. The defaults are mine; none is the customer's decision.
* Supplier master with parents and the intercompany flag; buyers (purchasing groups) for the ERP history; contract data for coverage; the savings baseline method.
* 24-36 months of PO and invoice history with the GL totals for the 0.5% tie-out.
* Who plays which role in the stewardship (two stewards per tenant at least, a procurement head and a CPO distinct from the category managers).

## 9. Behaviour other code can depend on

* `spend_line` is unique per (invoice line, document type, document reference); consumers that insert spend lines must set nothing new (defaults are INVOICE / ''); `volume_gen` and `erp_load` still work.
* `spend_cube_summary` has `buyer_id` in its grain and three new measure columns; the summary is derived and rebuilt on first read after 0021.
* Cube shares changed meaning (`contractCoveragePct`, `maverickPct` are shares of addressable spend); `overview` keys are unchanged; new keys `scope`, `freshness.pendingEvents`.
* `spend.decide_review` / `dispose` / `approve_plan` keep their signatures (new keyword arguments are optional); a hit disposition of ACCEPTED_EXCEPTION or FALSE_POSITIVE now needs `reason_code`.
* The consumer `spend-cube` moved from `services/savings.py` to `services/spend_feed.py` under the same consumer name (processed events are not replayed); `savings.spend_cube()` remains.
* Event `credit_note.received` added (producer `payables.submit_credit_note`); jobs `spend-cube-refresh`, `spend-sla`, `spend-quality`, `spend-forecast-snapshot` registered.
* `MaverickRule` rows are the baseline; the rule in force for a document is `spend_workflow.effective_rules(session, document_date)`. `tools/erp_load.py` still reads the rows.

## 10. Routes the front end needs

Existing (changed): `GET /v1/spend/analysis` (`buyer`, `fiscal_year` / `fiscal_quarter` / `year` / `quarter` / `buyer` dims, `scope`, measures `invoicedMinor`, `debitNoteMinor`, `creditNoteMinor`,
`contractedAddressableMinor`, `priceVariancePct`, `addressablePct`), `GET /v1/spend/overview` (`scope`), `POST /v1/spend/maverick-hits/{id}/disposition` (`reason_code`),
`POST /v1/spend/classification-reviews/{id}/decision` (`reason`, `learn_keyword`; status `PENDING_SECOND`).

New: `GET /v1/spend/summary`, `/comparison`, `/pareto`, `/category-structure`, `/savings-potential`, `/lines` (cursor), `/export` (CSV), `/quality`, `POST /quality/run`, `/quality/history`,
`/forecast/accuracy`, `POST /forecast/snapshot`, `/classification-queue`, `POST /classification-reviews/bulk`, `GET/POST/PATCH /spend/taxonomy`, `/maverick/worklist`, `/maverick/repeat-offenders`,
`/maverick-rules`, `POST /maverick-rules/{code}/versions`, `POST /maverick-hits/{id}/resolve`, `POST /maverick/escalate`, `/duplicates`, `POST /duplicates/scan`, `/duplicates/{key}/propose-merge`,
`/duplicates/{key}/dismiss`, `GET /v1/category-plans/{ref}`, `PATCH`, `POST /submit`, `/reject`, `/revise`, `GET /pipeline-links`, `POST /v1/admin/spend/reevaluate`.
