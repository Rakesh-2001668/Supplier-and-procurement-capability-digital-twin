# PIC Finance Module Analysis: M10 Invoice Matching & Finance Integration (flow F7), finance parts of M11

Scope: Blueprint M10 (section 16) and flow F7 (section 21.7), the finance parts of M11 (finance validation, budget impact, SOD-07), and Technical Document payables-svc
(sections 5, 6, 7.3 DMN-03, 9.4, 10, 11, 12.3, 14). Code: `backend/app/pic/services/payables.py` and its neighbours, `frontend/src/app/pic/invoices`.
Method: read the specifications and every code path, ran the existing finance tests (baseline 108 passed), fixed what was broken, completed what was missing, and
proved it with `backend/tests/pic/test_finance_journey.py` (one sequential scenario through the real HTTP API in its own tenant FIN1) and
`backend/tests/pic/test_finance_controls.py` (unit tests of the TDS, duplicate-number and MSME logic).

Status legend: **VERIFIED** = covered by a named test that passes; **CODE ONLY** = implemented and read, no automated test; **MISSING** = not built.
Test keys: **J01..J16** = `test_finance_journey.py`; **FC** = `test_finance_controls.py`; **R78** = `test_review_f7_f8.py`; **W1P** = `test_wave1_p2p.py`;
**OO** = `test_order_ops.py`; **SIG** = `test_signature_case.py`; **R56** = `test_review_f5_f6.py`; **CON** = `test_datasets_industry_construction.py`.

## 1. What the specification requires

| Source | Requirement |
|---|---|
| BP 16.1 | Capture by portal, PDF/OCR, GST e-invoice (IRN), EDI; 2-, 3-, 4-way match, ERS; tolerances by amount, percent, price, quantity per company code; exception workflow (price, quantity, missing GR, tax, duplicate); credit/debit notes and retention; posting to ERP AP with idempotency and reconciliation; payment status, early-payment discount, SCF hooks; GRIR accruals |
| BP 16.2 | Signature case INV-TF-8812: billed 5,400, quantity exception 20, credit note, matched, posted (ERP 5100004421); default tolerances price 1% or 500 (lower), quantity 0%, tax exact; configurable per company code and supplier group |
| BP 16.3 | INV-01 inbox, INV-02 match and exception resolver, INV-03 posting and reconciliation, INV-04 payables insights (due dates, discounts captured, DPO, GRIR ageing) |
| BP 16.4 | Duplicate check supplier + number + amount + date; GR before approval unless ERS; services match approved SES; posting key = tenant + company code + supplier + invoice no.; payment block until all exceptions resolved |
| BP 16.5 | KPIs: first-pass match %, exception cycle time, duplicates prevented, discount capture %, DPO |
| BP 17 (M11) | Realised savings only from posted invoices; cost avoidance never counts towards budget; finance validator differs from the initiative owner |
| F7 (21.7) | Submitted, capture and duplicate check, 2/3/4-way match with tolerances, within tolerance?, resolve exception (credit note / approve / dispute), post to ERP (idempotent), payment run, realised savings and scorecard update, paid and reconciled; retries never double-post |
| TD 5/6 | Invoice states Captured, Duplicate Check, Matching, Exception or Matched, Approved, Posted, Paid, Rejected; guard on Matched to Posted: no open exceptions, posting key reserved |
| TD 7.3 DMN-03 | Price 1% or 500 per line (lower), quantity 0% vs accepted GR, quantity vs SES 0%, tax exact with IRN validated, duplicate same supplier + number or amount +-1 and date +-3 days |
| TD 9.4 | Algorithm: PO line, accepted GR less already invoiced, price band, tax (rate, HSN/SAC, IRN valid), exceptions with suggested action, matched then approve then post (idempotent) |
| TD 10/11 | `POST /v1/invoices`, `/match`, `/post` (Idempotency-Key), ETag/If-Match, problem+json; events invoice.captured, invoice.exception.raised, invoice.posted, payment.completed |
| TD 12.3 | GST e-invoice IRN and signed QR validated on capture |
| TD 14 | SoD engine SOD-01..07 at command time; bank-change fraud controls (callback, dual approval, cooling-off) |
| India | GST, TDS at payment, MSME 45-day payment rule (MSMED Act s.15), retention/withholding |

## 2. Traceability: specification step to code to proof

| # | Spec rule / step | Code | Proof | Status |
|---|---|---|---|---|
| 1 | F7-01 capture via portal / AP clerk / PDF (OCR) | `payables.capture`, `api/order_pay.py:capture_invoice`, `services/ocr.py` | J02, J04, J05, R78, SIG | VERIFIED |
| 2 | F7-01 GST e-invoice IRN + QR validation on capture | `services/einvoice.py:verify`, `payables.capture` | J02 (valid IRN), J05 (invalid IRN raises TAX), SIG | VERIFIED |
| 3 | F7-01 EDI INVOIC inbound | `services/edi_invoice.py` | W1P (inbound INVOIC, AERAK rollback, credit/debit syntax) | VERIFIED |
| 4 | F7-02 hard duplicate (supplier + number + FY) | unique key + `capture` 409 | J02 (409 DUPLICATE_INVOICE, Idempotency-Key replay) | VERIFIED |
| 5 | F7-02 fuzzy duplicate amount +-1, date +-3 d | `payables._duplicate_check` | R78 | VERIFIED |
| 6 | F7-02 OCR / formatting variants of the number | `finance_controls.normalise_invoice_no`, `_duplicate_check` | J04, FC | VERIFIED (new) |
| 7 | F7-03 3-way match vs accepted GR less invoiced, qty 0% | `payables.match` | J02 (clean), J04 (QUANTITY +50), R78, SIG | VERIFIED |
| 8 | partial receipts and several invoices on one PO line | `pending_on_line`, `over_claimed`, row lock | R78 (pendingInvoicedQty), J02/J04 (600 then 400 of 1000) | VERIFIED |
| 9 | 4-way (inspection accepted), 2-way, SES, ERS match | `payables.match` | R56, R78, CON, datasets | VERIFIED (existing) |
| 10 | price tolerance min(1%, 500) per line | `payables.match` | J05 (PRICE, variance 2,000 INR against tolerance 500), R78 | VERIFIED |
| 11 | tax exact (rate, HSN, tax amount, IRN) + CBIC HSN master | `payables.match`, `services/gst.py` | J05 (IRN), existing | VERIFIED |
| 12 | tolerance by company code and supplier group | `rules.resolve("DMN-03", supplier_group=...)` | W1P `test_invoice_tolerance_follows_the_supplier_group_scope` | VERIFIED |
| 13 | missing GR exception then GR posted resolution | `match`, `resolve_exception` | J06 | VERIFIED |
| 14 | quantity exception resolved by credit note (value and quantity credits) | `submit_credit_note`, `resolve_exception` | J04, R78, SIG | VERIFIED |
| 15 | price exception: AP asks, buyer other than PO creator decides, PO re-priced | `_request_price_acceptance`, `_price_variance_decided` | J05 | VERIFIED |
| 16 | dispute keeps the block; reject closes | `resolve_exception(DISPUTE)`, `reject` | J05, J04 | VERIFIED |
| 17 | SOD-04 PO creator cannot resolve exceptions on the PO | `resolve_exception` + `sod.guard` | R78 | VERIFIED |
| 18 | payment block until all exceptions resolved | `match`, `post` | J04, J05, J06, J07 | VERIFIED |
| 19 | credit note netting in payment | `payment_run` | J12 (INV2 pays gross less credit note) | VERIFIED |
| 20 | debit note: match, buyer chain for charges, AP approval, ERP debit memo, nets into payment | `services/debit_notes.py` | J08, J09, W1P | VERIFIED |
| 21 | **four-eyes: capturer cannot approve (SOD-08)** | `payables.approve`, sod rule SOD-08 | J04 | VERIFIED (new) |
| 22 | **payer differs from approver (SOD-09)** | `payables._assess_payment`, sod rule SOD-09 | J12 | VERIFIED (new) |
| 23 | SOD-02/02a bank changer cannot pay / post | `_assess_payment`, `post`, `approve` | R78 (existing) | VERIFIED |
| 24 | F7-06 post to ERP, key tenant + company + supplier + number | `payables.post`, `integration.enqueue` | J03, SIG (ERP 5100004421) | VERIFIED |
| 25 | posting replay returns same ERP document | `api/order_pay.py:post_invoice` | J03 | VERIFIED |
| 26 | ERP failure then retry; lost response then query-before-retry | `integration.process`, `post` | J04 (fail then admin replay), J07 (lost response, one ERP document) | VERIFIED |
| 27 | Idempotency-Key retry sees the final state (not a stale interim answer) | `Idempotent.release`, `post_invoice` | J04 | VERIFIED (defect fixed) |
| 28 | ETag / If-Match on invoice writes | `order_pay._locked_invoice` | J03 (412 on stale), J14 (savings) | VERIFIED (new) |
| 29 | Idempotency-Key on credit note, exception resolve, payment run, file, bank results | `api/order_pay.py`, `api/finance.py` | J04, J09, J11 | VERIFIED |
| 30 | F7-07 due date from payment terms (invoice date + net days) | `_invoice_posted` | J03 (Dec 3 + 30 = Jan 2) | VERIFIED |
| 31 | **MSME 45 days from acceptance** | `finance_controls.due_date`, `acceptance_date` | J10, J13, FC | VERIFIED (new) |
| 32 | MSME interest (3x bank rate, monthly compounding) | `finance_controls.msme_interest_minor` | FC; needs the bank rate from the tenant | VERIFIED formula, rate must be supplied |
| 33 | early-payment discount (terms 2/10 N30), SCF hooks | `services/early_payment.py` | J09, W1P | VERIFIED |
| 34 | payment run with supplier and invoice filters, idempotent | `payables.payment_run`, `api/order_pay.py:payment_run` | J09, J12, J13, R78 | VERIFIED |
| 35 | **payment proposal (dry run, same logic as the run)** | `payables.payment_proposal`, `GET /v1/payments/proposal` | J09, J12, J13 | VERIFIED (new) |
| 36 | blocked supplier: invoices payment-blocked, no new invoices | `supplier.block`, `capture`, `payment_run` | J07, J12 | VERIFIED |
| 37 | bank-change cooling-off holds payment | `_assess_payment` | J12 (skipped with reason) | VERIFIED |
| 38 | **TDS determination (section, rate, thresholds, no-PAN, catch-up) and deduction at payment** | `finance_controls.compute_tds / at_payment`, `_fix_fx_and_tds` | J10, J13, J06, FC | VERIFIED (new) |
| 39 | TDS register (quarterly return source) | `finance_controls.tds_register`, `GET /v1/finance/tds-register` | J13 | VERIFIED (new) |
| 40 | retention withheld and released | `retention_by_po`, `release_retention` | CON | VERIFIED (existing) |
| 41 | advance recovery (construction) | `services/ind_construction.py` | CON | VERIFIED (existing) |
| 42 | **foreign-currency invoice: currency from the PO, rate on the invoice date, group amount, USD payment** | `capture`, `finance_controls.fx_for`, `payment_run` | J11, J13 | VERIFIED (new) |
| 43 | **posting period close and cut-off** | `finance_controls.close_period / assert_open`, `GET/POST /v1/finance/periods` | J11 | VERIFIED (new) |
| 44 | payment file ISO 20022 pain.001 / NEFT, one live file per run, content audited | `services/bank_files.py` | J09, J12, OO | VERIFIED |
| 45 | **bank result per payment: credited with UTR, returned with reason, invoice payable again** | `bank_files.record_bank_results`, `payables.return_payment` | J09, J12 | VERIFIED (new) |
| 46 | **returned payment's ERP clearing document listed until reversed** | `payables._reconcile_payments_and_memos` (PAYMENT_RETURN_OPEN) | J12 | VERIFIED (new) |
| 47 | F7-09 payment completed only when the ERP clears | `_payment_posted`, `payment.completed` | J09, J13 (5 events) | VERIFIED |
| 48 | INV-03 nightly reconciliation (invoices, payments, credit and debit memos) | `payables.reconcile` | J12, R78, OO | VERIFIED |
| 49 | INV-04 insights: due ladder, discount, DPO, first pass, GRIR ageing, MSME, exception ageing, TDS | `payables.insights` | J13 | VERIFIED |
| 50 | GRIR accrual (received not invoiced) | `payables.grir` | R78, cut-off snapshot J11 | VERIFIED |
| 51 | M10 KPIs (5 of the blueprint) | `services/kpi.py` M10 section | J15 | VERIFIED |
| 52 | F7-08 realised savings only from posted invoices; net of credit notes | `savings._realised` | J14 (5,000,000 = 600 + 400 pieces x 50.00) | VERIFIED |
| 53 | **realised savings net of value (price-difference) credit notes** | `savings._realised` | none (defect fixed by reading; quantity-credit path covered by J14) | CODE ONLY |
| 54 | cost avoidance never counts towards budget | `savings.waterfall` | J14 | VERIFIED |
| 55 | finance validation, validator differs from owner (SOD-07) | `savings.validate` | J14 (403 non-finance, 409 SOD-07 for the owner, 412 stale, validated by finance) | VERIFIED |
| 56 | audit trail of every state change, hash chain valid | `platform/audit.py` | J15 | VERIFIED |
| 57 | SoD violations leave evidence | `sod._log_violation` | J15 (SOD-07, 08, 09) | VERIFIED |
| 58 | tenant isolation (RLS) | row-level security | J16 | VERIFIED |
| 59 | event schemas for new events | `events/schemas/*.json` | J15 validates payloads | VERIFIED |
| 60 | INV-01 filters (status, supplier, company, text, dates, payment, block, match, exceptions, MSME, amount) | `api/lists.py:invoices` | J16 | VERIFIED (new) |
| 61 | UI: invoice list filters, payment run dialog with filters and proposal, bank results, period close, MSME/TDS/FX on the invoice | `frontend/src/app/pic/invoices/*` | `tsc --noEmit`, eslint; browser pass is done by the lead | CODE ONLY |
| 62 | **scheduled payment-due trigger: proposal for invoices due (MSME 45-day deadline included) and early-payment discount windows, approval task for the finance approver, never pays by itself** | `job_handlers.payment_due`, `_proposal_detail`, `_discount_windows`, `_proposal_decided` (job `payment-due`, rule PAYMENT-RUN) | J17, `test_wave1_jobs` (proposal, never pays with autoRun) | VERIFIED (new) |
| 63 | **supplier finance maintenance screen: MSME class, Udyam no., PAN, TDS section, s.197 certificates; ETag, audit, role gate, format validation** | `GET/PUT /v1/suppliers/{code}/finance`, `suppliers/[code]/_finance.tsx` | J18 (API: formats, 403, 412, PAN never in the audit trail); screen: tsc, eslint | VERIFIED (API), CODE ONLY (screen) |
| 64 | **ERP reversal message for a returned payment (idempotent PAYREV key, retry, replay); closes PAYMENT_RETURN_OPEN when the ERP confirms** | `payables._request_erp_reversal`, `_payment_reversed`, DOC_TYPES `PAYMENT_REVERSAL` (simulator; live connectors report it unmapped like the debit memo) | J12 (ERP down: item stays open), J20 (replay posts once, item closes) | VERIFIED (new), simulator only |
| 65 | **bank statement import: camt.053 and MT940, dry run then apply, idempotent per statement id, amount / conflict / unsent-file checks** | `services/bank_statement.py`, `POST /v1/bank-statements/import`, fixtures `tests/pic/fixtures/bank` | J20, FC (parsers, refusals) | VERIFIED (new) |
| 66 | **period close blocks credit notes, debit notes and goods receipts (problem+json with the reopen rule); GR/IR snapshot persisted per close** | `finance_controls.assert_open` in `submit_credit_note`, `debit_notes.submit/post`, `receiving.post_gr`; `grir_snapshot` | J21, J11 | VERIFIED (new) |
| 67 | **s.197 lower-deduction certificate per supplier (number, rate, validity, section), applied at payment when valid** | `finance_controls.valid_certificate / at_payment_detail`, `tds_certificate`, `POST /v1/suppliers/{code}/tds-certificates` | J19 (0.5 % on invoice and note, payment keeps the certificate number), FC | VERIFIED (new) |
| 68 | **TDS on debit notes (additional taxable value, thresholds count earlier notes), netted into the payment** | `finance_controls.compute_note_tds`, `debit_notes.post`, `_assess_payment` | J19 (INR 200 at 2 % fixed at posting, INR 50 at the certificate rate), FC | VERIFIED (new) |
| 69 | **Form 26Q / 16A style CSV of TDS deducted per quarter (finance scope, audited with hash, formula-injection safe)** | `finance_controls.tds_export`, `GET /v1/finance/tds-export` | J19, FC (quarters, CSV safety) | VERIFIED (new) |
| 70 | UI: TDS export, bank statement upload, posting periods card | `invoices/_close.tsx`, `invoices/_ops.tsx` | tsc, eslint; browser pass by the lead | CODE ONLY |

Counts: 70 rows; **VERIFIED 67** (22 of them new or fixed in this work; row 63 verified through the API, its screen is code-only), **CODE ONLY 3** (rows 53, 61, 70), **MISSING 0**. (Row 32 counts as verified for the formula only; row 64 is verified against the ERP simulator, live connectors report the message unmapped.)

## 3. What works (unchanged by this pass)

The F7 core was already enterprise grade: the 3/4-way/SES/ERS match with row-locked PO lines and over-claim re-checks, DMN-03 per company code and supplier group, value and
quantity credit notes, the buyer price-variance approval, debit notes, early payment and SCF hooks, retention and advance recovery for construction, EDI INVOIC, the
posting key and `integration_message` uniqueness with query-before-retry, one live payment per invoice (partial unique index), bank-change cooling-off, payment files,
nightly reconciliation, the savings ledger and its SOD-07 check. Baseline before any change: `test_review_f7_f8`, `test_wave1_p2p`, `test_order_ops`,
`test_signature_case`, `test_review_f5_f6`, `test_datasets_industry_construction`: 108 passed.

## 4. Defects found and fixed, gaps completed

| # | Finding | Fix (file) |
|---|---|---|
| D1 | **Retry with the same Idempotency-Key replayed the interim answer "POSTING" for ever** when the first post parked in RETRY (ERP down): the documented retry path never saw the posted state. | `platform/core.py` `Idempotent.release`; `api/order_pay.py` `post_invoice` releases the reservation when the result is not final |
| D2 | AP clerk could capture an invoice and approve it herself (AP_CLERK holds capture, approve and post). | SOD-08 (`INVOICE_CAPTURE` vs `INVOICE_APPROVE`): `payables.capture` records, `approve` guards; migration 0017 inserts the rule for every tenant, `seed/reference.py` for new ones |
| D3 | Nothing stopped the user who approved an invoice from releasing its payment. | SOD-09 (`INVOICE_APPROVE` vs `PAYMENT_APPROVE`): `payables._assess_payment`; the invoice is skipped with the rule in the reason |
| D4 | A debit note with only a CHARGE line could be approved by the creator of the PO it bills (SOD-04 reached price lines only). | `services/debit_notes.py` `match` excludes the creators of every order on the invoice |
| D5 | Invoice currency was hard-coded INR at capture and Payment currency defaulted to INR: a foreign-currency PO produced an INR invoice and an INR bank line; no exchange rate anywhere on the invoice. | `payables.capture` takes the PO currency (422 for mixed currencies), `_fix_fx_and_tds` fixes the rate at first post (409 FX_RATE_MISSING), `payment_run` pays in the invoice currency; insights convert to the company currency |
| D6 | Realised savings treated a value (price-difference) credit note as a quantity credit, understating the saving; the initiative lookup raised `MultipleResultsFound` when two initiatives shared a material. | `services/savings.py` `_realised` uses the match's own credit helpers and takes the oldest initiative |
| D7 | Duplicate detection ignored OCR and formatting variants (INV-0012, inv 12, INVO12). | `finance_controls.normalise_invoice_no` + `payables._duplicate_check` hold the variant (DUPLICATE, `variant: NUMBER_NORMALISED`) |
| D8 | MSME 45-day rule absent. | migration 0017 (supplier.msme_class, udyam_no; invoice.acceptance_date, msme_capped), rule set MSME, `finance_controls.due_date`, payment proposal ordering, insights |
| D9 | TDS was a column filled only by the SAP loader; nothing computed or reported it. | rule set TDS, supplier.tds_section, `finance_controls.compute_tds` at posting (fixed once so retries send the same payload), `at_payment`, `payment.tds_minor`, ERP payload, register, ETag-guarded supplier maintenance route |
| D10 | Bank acknowledgement was file-level only: a payment the bank returned left the invoice PAID for ever; no UTR. | `bank_files.record_bank_results`, `payables.return_payment`, state `PAID` to `POSTED`, payment `bank_status`, reconciliation item for the ERP reversal |
| D11 | No posting-period control or cut-off. | table `posting_period` (RLS), `finance_controls.close_period/reopen_period/assert_open`, checks in `post` and the payment run, GR/IR snapshot, events finance.period.closed / reopened |
| D12 | No payment proposal; the run could only be executed. | `payables.payment_proposal` shares `_assess_payment` with the run |
| D13 | Invoice writes had no ETag / If-Match; credit-note and resolve had no Idempotency-Key; worklist filtered by status only; no payment list. | `api/order_pay.py` (`_locked_invoice`, ETag on GET), `api/lists.py` (12 filters, one grouped query for open exceptions), `api/finance.py` (`GET /v1/payments`) |
| D14 | Skipped list of the run keyed by invoice number only (a debit-note payment and its invoice collide in the UI). | frontend key includes the position |

Second pass (closing the gaps of section 5):

| # | Finding | Fix (file) |
|---|---|---|
| D15 | The `payment-due` job existed but could pay by itself with `autoRun`, and its proposal showed gross totals only (no MSME deadline, TDS, discounts, no discount windows). | `services/job_handlers.py`: autoRun is ignored by policy (reported as `autoRunIgnored`), the task evidence now carries the full proposal (amounts net of credit notes, TDS and discount, MSME flags, skipped reasons) and the invoices whose terms discount closes within the horizon; approving takes the terms discount and runs the normal payment run. `test_wave1_jobs` was changed accordingly (the old test asserted the auto-run). |
| D16 | A returned payment left its ERP clearing document to be reversed by hand. | `PAYMENT_REVERSAL` message (key `PAYREV|<payment>`), `payables._request_erp_reversal`; the ERP confirmation marks the clearing document reversed and closes the reconciliation item. |
| D17 | Bank results were keyed by hand. | `services/bank_statement.py` (camt.053 with a DTD/entity refusal, MT940), analysis states READY / UNCHANGED / CONFLICT / AMOUNT_MISMATCH / FILE_NOT_SENT / UNMATCHED / AMBIGUOUS / NO_REFERENCE, apply through `bank_files.record_bank_results`, table `bank_statement_import` (unique per tenant and statement id). |
| D18 | Credit notes, debit notes and goods receipts could be posted into a closed period; no GR/IR evidence at close. | `finance_controls.assert_open` in the three paths; `PERIOD_CLOSED` problem carries `period`, `companyCode`, `reopenScope` and the reopen rule; table `grir_snapshot` (one row per close, line by line). |
| D19 | No lower-deduction certificate, no TDS on debit notes, no return file. | tables `tds_certificate`; columns `debit_note.tds_*`, `payment.tds_base_minor / tds_rate / tds_certificate`; `finance_controls`; export endpoint. |
| D20 | PAN could not be maintained; Udyam had no format check. | `PUT /v1/suppliers/{code}/finance` accepts `pan` (must be the one inside the GSTIN, stored as hash, only the masked value is audited) and validates `UDYAM-XX-00-0000000`. |

Migration 0017 was extended (it is local only): `debit_note.tds_base_minor / tds_minor`, `payment.tds_base_minor / tds_rate / tds_certificate / reversal_doc`, tables
`grir_snapshot`, `tds_certificate`, `bank_statement_import` (grants and forced RLS). New files: `services/bank_statement.py`, `tests/pic/fixtures/bank/*`,
`frontend/.../invoices/_close.tsx`, `frontend/.../suppliers/[code]/_finance.tsx`.

Shared files changed backward compatibly: `payables.py`, `bank_files.py`, `savings.py`, `debit_notes.py`, `platform/core.py` (new method), `platform/auth.py` (+ scope
`period:close` for FINANCE_CONTROLLER), `platform/roles.py`, `seed/reference.py` (+ SOD-08/09, rule sets MSME and TDS), `events/catalogue.py`. New: migration `0017_finance_complete.py`
(down_revision 0016), `models/finance_close.py`, `services/finance_controls.py`, `platform/finance_defaults.py`, `api/finance.py`, four event schemas.

## 5. What remains

* Live ERP reversal: `PAYMENT_REVERSAL` is mapped for the simulator only (like the debit memo and SCF types); SAP S/4, Dynamics, Tally and Odoo connectors report it unmapped, so with them the treasury clerk still reverses the clearing document and resolves the reconciliation item.
* The payment-due job proposes in the tenant time zone once a day; it does not chase a proposal nobody decides (the task SLA escalation of the workflow engine does).
* TDS: certificates are per supplier, rate and validity (no amount cap of the certificate); no Form 16A PDF, no challan/BSR matching, no TCS, no TDS on advances, no foreign-remittance TDS (s.195). The PAN of the return comes from the GSTIN (a supplier without GSTIN is exported as PANNOTAVBL). The default sections remain illustrative.
* MSME: interest is computed only when the tenant publishes the bank rate; no accrual posting and no 15-day rule for suppliers without a written agreement.
* FX: rate fixed at invoice date, no revaluation or realised gain/loss at payment; foreign payment files carry no SWIFT data.
* Bank statements: camt.053 and a basic MT940 (one :61:/:86: pair per entry, matching by payment number); no CAMT.054, no multi-payment batch entries (reported AMBIGUOUS), no automatic matching of other bank movements.
* SOD-08 is recorded for supplier invoice capture; consignment settlements and retention releases (system-built AP documents) do not record a capturer.
* Realised savings from value credit notes (row 53) has no automated test.
* The browser pass of the new screens (invoice list, payment run, bank results and statement upload, posting periods, TDS export, supplier finance card) is done by the lead.

## 6. What the product owner must supply

| Item | Why |
|---|---|
| Tax team sign-off of TDS sections, rates, thresholds and the section codes of the Act in force from 1 April 2026; publish as rule set TDS (`POST /v1/admin/rules`) | the shipped defaults are illustrative |
| PAN and TDS section per supplier (migration or screen), lower-deduction certificates | determines what is withheld |
| RBI bank rate (rule MSME `bankRatePct`) and the position on suppliers without a written payment agreement | MSME interest |
| Udyam verification source and the list of micro/small suppliers | MSME class |
| Debtor bank account per company code (rule PAYMENT-FILE: debtorName, debtorAccountRef, debtorIfsc), bank file specification, bank acknowledgement / statement format and host-to-host access (`PIC_BANK_SFTP_*`) | payment files, automatic bank results |
| ERP posting profile for TDS, MSME interest, credit memos and payment reversal; SAP (or other) sandbox access | live posting and reversal |
| Exchange-rate source (daily reference rates) loaded into `fx_rate` | foreign-currency invoices |
| Fiscal calendar, who may close and reopen periods, and the cut-off day | period control |
| IRP / GSP credentials (`PIC_IRP_*`) | live e-invoice verification |
| Invoice approval value bands and the finance approvers | approval policy |
| Sample camt.053 and MT940 files from the bank (the shipped fixtures are synthetic) and whether the bank echoes our payment number as EndToEndId / reference | statement matching |
| s.197 certificates of the suppliers (number, rate, validity) and the tax team's rule on certificate amount caps | lower deduction |
| Live ERP message for reversing a payment (SAP reversal BAPI / OData service, Dynamics, Tally, Odoo) | closing returned payments automatically on live systems |
| Time of day and approver role for the payment proposal (rule PAYMENT-RUN: horizonDays, approverRole, slaBusinessDays) | scheduled trigger |

## 7. How to run the proof

```
backend\venv\Scripts\python.exe <scratchpad>\mkdb.py pic_test_fin
set TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:54329/pic_test_fin
backend\venv\Scripts\python.exe -m pytest tests/pic/test_finance_journey.py tests/pic/test_finance_controls.py -q
```
Developers iterating on a seeded database add `PIC_TEST_KEEP_DB=1` and a fresh tenant code (`FIN_TEST_TENANT=FIN2`). New environment variables: none (existing `PIC_REQUIRE_IF_MATCH` now also
applies to invoice and supplier-finance writes).
