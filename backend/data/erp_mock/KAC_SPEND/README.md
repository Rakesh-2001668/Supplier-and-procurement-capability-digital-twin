# KAC / AXN spend datasets (MOCK, ILLUSTRATIVE SAMPLE)

Everything in this folder's pack is **mock data**: invented suppliers, amounts, currencies, descriptions and decisions that make the spend cube (M01) show
a working category-intelligence function until the customer's own data is loaded. Nothing here is a statement about a real company or a real price. Every
generated spend line has the invoice reference `MOCK-SP/<family>/<tenant>/<n>`, every supplier a code `MOCKF- / MOCKT- / MOCKH- / MOCKD- / MOCKK-`, every
rate the source `MOCK series (spend_ops)`, every decision the word MOCK in its comment.

* Pack: `app/pic/seed/datasets/spend_ops.py` (key `spend-ops`, requires `finance-ops`, registered right after it in `datasets.PACKS`)
* Generator rules (deterministic, no randomness): `app/pic/tools/spend_mock.py`
* Tests: `tests/pic/test_datasets_spend_ops.py`
* Runbook: `docs/runbooks/spend_operations.md`

## How it loads

Bulk spend lines, hit rows and review rows are written with multi-row inserts (batches of 2,000, one transaction per batch): the pack is meant to run against
a database behind a high-latency link. Everything that is a **workflow** goes through the real services with the business clock pinned to the day of each
step (decisions, dispositions, escalations, duplicate merge, category plans, rule version, forecast and data-quality runs), so state machines, four-eyes, SoD,
audit hash chains and outbox events behave as in production. The pack is loaded once per tenant (`pic.dataset_load`); every insert looks for its own rows first,
so a re-run after a failure does not duplicate anything.

Local run (PostgreSQL 16 on the developer machine, the whole pack, one process): KAC about 105-175 s, AXN about 40 s (the first figure is on a quiet
machine). On Neon the multi-row inserts dominate; the service-driven part is about 200 items for KAC and 120 for AXN.

## What each dataset is

<!-- counts:start -->
| item | KAC | AXN |
|---|---|---|
| periods covered by the pack's lines | April 2025 to October 2026 (19 months, fiscal years 2025-26 and 2026-27) | same |
| spend lines written by the pack | 7,539 (the tenant had 26,528 before: 34,067 in total) | 1,350 (3,952 in total) |
| foreign-currency lines (second ERP systems SAP-EU, SAP-APAC) | 4,676 (USD 1,205, EUR 1,454, JPY 673, CNY 1,344) and the 20 KRW defect lines | 9 foreign suppliers (EUR, USD, CNY) |
| tail lines (60 small suppliers) | 1,154 | 15 suppliers |
| concentrated categories | HEAT-TREATMENT 795 lines, HHI about 6,600; SPECIAL-COATINGS 230 lines, HHI about 8,600 | none |
| ERP credit memos (negative lines) | 120 | 30 |
| maverick cases for the six rules the tenant had none of | 6 x 25 lines, 150 hits | 6 x 6 lines |
| unclassified free-text lines | 140 (132 reviews in the steward queue, 8 applied automatically) | 25 |
| new suppliers | 101 (24 foreign, 60 tail, 5 concentrated, 11 in duplicate groups, 1 Korean) | 24 |
| MOCK FX rates (weekly, 31 March 2025 to 30 March 2026; USD, EUR, JPY, CNY) | 212 | 212 |
<!-- counts:end -->

Formula-derived figures (rewritten by `python -m app.pic.tools.spend_mock --write`):

<!-- gen:start -->
| item | value |
|---|---|
| periods | 2025-04 to 2026-10 (19) |
| foreign lines (formula) | 4,670 |
| HEAT-TREATMENT shares | {'MOCKH-001': 79.7, 'MOCKH-002': 12.9, 'MOCKH-003': 7.4} |
| HEAT-TREATMENT HHI | 6,573 |
<!-- gen:end -->

* **Foreign lines.** 24 MOCK suppliers (DE, IT, SE, US, JP, CN, SG, NL) in 14 categories. A line is quantity x unit price in the supplier's currency (two implied
  decimals for every currency, as the platform stores them) converted at the rate valid on the document date from the finance pack's series (1 April to 31 October 2026)
  or from the pack's weekly MOCK rates before it, which continue the finance pack's curve (`finance_mock.fx_rate`). The rate and its date are stored on the line.
* **Seasonality.** monthly lines x pattern[month] x (1 + 0.6 % per month): AUTO (year-end push in March, festive build in October), FESTIVE (packaging, logistics:
  October 1.25, November 1.18, December 1.08), FLAT (software, professional services). Formulas in `spend_mock.season`.
* **Concentration.** HEAT-TREATMENT: three suppliers (about 80 / 13 / 7 % of the spend, one with risk tier HIGH): HHI about 6,600. SPECIAL-COATINGS: two suppliers
  (90 / 10 % of the lines): HHI about 8,600. Both are above the 2,500 limit; the first is a STRATEGIC item and the second a BOTTLENECK item in the category plans.
* **Duplicate-supplier groups.** MOCKD-101/102 (same PAN and bank account, names "Precision Dies and Tools Pvt Ltd" / "Precision Dies & Tools Private Limited"),
  MOCKD-201/202/203 (Hosur Packaging Industries and two name variants), MOCKD-301/302 (same PAN, different names), MOCKD-401/402 (Madras Industrial Gases / Gasses).
  MOCKD-501/502 (Plant 1 / Plant 2 Engineering Services) are **not** duplicates and must not be clustered. States after the pack: 101/102 merge approved by a second
  steward (the corporate-parent link is set), 201-203 merge proposed (task waiting), 301/302 open, 401/402 dismissed with a reason.
* **Maverick.** Every one of the nine rules has cases. States after the pack (KAC): open, accepted exception (with reason codes), policy breach, false positive,
  recovery open, recovery resolved (with the amount recovered), and hits escalated once and twice after missing their SLA; one rule (NON_CATALOGUE) has an
  effective-dated version (SLA 15 days from 1 October 2026).
* **Steward queue.** 12 proposals accepted, 12 reclassified (and, through one bulk decision on the description with the most open reviews, more with a keyword taught to its category; the pack picks a word no category owns yet), three
  above the four-eyes value: one confirmed by a second steward, one disagreed (back in the queue), one waiting for its second steward (`PENDING_SECOND`).
* **Category plans.** Fiscal year 2026-27 for the top volume categories plus HEAT-TREATMENT, SPECIAL-COATINGS and MRO: three approved (one through the task
  inbox, one by direct approval of the CPO, one that was then revised into version 2), two or three drafts (one edited), one in approval, one rejected. Kraljic
  positions: LEVERAGE, STRATEGIC, BOTTLENECK and NON_CRITICAL.
* **Forecast history.** 1,008 forecasts "as issued" for April to September 2026 (24 categories, six months ahead), computed by the real forecast method on the
  data known at the end of the previous month, so `GET /v1/spend/forecast/accuracy` shows a real error: about 30 % MAPE over all categories, 9-20 % for the large
  ones and above 50 % for the lumpy small ones, with the 80 % band covering about 65 % of the actuals (it under-covers: lumpy series).

## Deliberately wrong data (the data-quality report must find each of these)

| Code | Check | What was planted | KAC count |
|---|---|---|---|
| DQ1 | FX_RATE_MISSING | KRW lines from MOCKK-001 (the tenant has no KRW rate at all) | 20 |
| DQ2 | DUPLICATE_LINES | six foreign lines loaded twice (same invoice, order, period, amount, description) | 6 (+1 in the history) |
| DQ3 | CATEGORY_NOT_IN_TAXONOMY | category typed FASTNERS | 5 |
| DQ4 | NON_POSITIVE_INVOICE_LINES | invoice lines of value 0 | 3 |
| DQ5 | NO_LINEAGE | lines without an order reference (non-PO spend) | 40 |
| DQ6 | AMOUNT_OUTLIER | one line of Rs 60 crore in March 2025 (the tenant limit is Rs 25 crore, rule version `2026.3-MOCK-SPEND`) | 1 |
| DQ7 | INTERCOMPANY_ADDRESSABLE | intercompany supplier lines counted as addressable | 2 |
| DQ8 | SUPPLIER_UNKNOWN | lines whose supplier is not in the master | 2 |

The report also finds the findings that are real in the history the cutover loaded (unclassified spend, non-PO lines, the history's own intercompany lines). The
score after the pack is about 90 (grade A) because the planted defects are few and small; the checks, not the score, are what the tests assert.

## What the pack does not touch

No AXN signature document, number, amount or status; no KAC contract, invoice, payment or stock row (the tests hash them before and after); no scheduled job runs.
The contract coverage and maverick share of the AXN overview stay inside the signature bands (68-74 % and 5-8 %). Totals: KAC 34,067 spend lines (budget 150,000),
AXN 3,952 (budget 20,000).

## How to regenerate and check

```
python -m app.pic.seed.datasets spend_ops          # load (after finance_ops); idempotent
python -m app.pic.tools.spend_mock --check         # the generator's own invariants (24 suppliers, 4 currencies, 19 periods, HHI above 2,500, no collisions)
python -m app.pic.tools.spend_mock --write         # rewrite the counts block above from the generator
pytest tests/pic/test_datasets_spend_ops.py        # the properties of the loaded data
```

## Replacing it with the customer's data

Load the customer's 24-36 months of PO and invoice history with `tools/erp_load.py`, their FX series, supplier master (with parents and the intercompany segment),
taxonomy and keyword lists (runbook section 9). The mock suppliers, lines, rates, plans and decisions can then be removed by invoice reference prefix `MOCK-SP/`
and supplier code prefix `MOCK`; they hold no foreign keys that anything else depends on except the audit trail, which is kept.
