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


---

# Second analysis, 3 November 2026

Scope and method. A second, independent pass over Blueprint M10 (section 16), the receipt rules of section 15.4, the finance parts of M11, the Technical Document (sections 5, 6, 7.3, 9.4, 10, 11, 12.3, 14) and the India rules (GST, TDS/TCS, MSMED Act, FX). The requirement list below was derived again from the specifications, not copied from section 2; every row was traced to code and to a test that was run. Besides reading, adversarial probes were written (boundary tolerances, hostile numbers and amounts, concurrent commands, scale of 650 open invoices, scoping, replays) and every defect they found was fixed with a regression test in `backend/tests/pic/test_finance_second_pass.py` (names start `test_fin2_`).

Test keys in addition to those of section 2: **F2** = `test_finance_second_pass.py`.
Status legend: **VERIFIED** (a test that was run proves it), **CODE ONLY** (implemented, no automated proof), **PARTIAL** (part of the requirement is met, the rest named), **MISSING** (not built), **WRONG** (built, but found wrong in this pass; the fix is in section 8.3 and the row shows the state after it).

## 8.1 Traceability, second analysis

| # | Requirement (source) | Code path | Proof | Status |
|---|---|---|---|---|
| S01 | Capture by portal, AP clerk, PDF/OCR (BP 16.1) | `payables.capture`, `api/order_pay.py` | J02, J04, J05, F2 | VERIFIED |
| S02 | GST e-invoice IRN and signed QR validated on capture (TD 12.3) | `einvoice.verify` (local hash and QR checks; IRP lookup when configured) | J02, J05, SIG | VERIFIED locally; the live IRP call has no test (no sandbox) |
| S03 | An IRN is on one invoice only | `payables.capture` (DUPLICATE_IRN) | F2 `duplicates_refused_at_capture` | WRONG, fixed (D33) |
| S04 | EDI INVOIC inbound | `edi_invoice` | W1P | VERIFIED |
| S05 | Supplier invoice number: 1 to 40 printable characters, blanks not part of it | `payables.capture` | F2 `overlong_and_blank_invoice_numbers` | WRONG, fixed (D23) |
| S06 | Amounts, quantities, GST rate inside the storable range | `payables.capture` | F2 `zero_negative_and_overflow_amounts` | WRONG, fixed (D24) |
| S07 | Duplicate: exact key, amount +-1 and date +-3 days, OCR / case / blank / leading-zero variants | `_duplicate_check`, `finance_controls.number_variant_of` | J02, J04, R78, F2 (`ocr_and_whitespace_case_variants`) | VERIFIED |
| S08 | Duplicate prevented is counted (BP 16.5 KPI) | `kpi.m10_duplicates`, audit event DUPLICATE_BLOCKED | F2 `duplicates_refused_at_capture` | WRONG, fixed (D32) |
| S09 | 2-way, 3-way, 4-way, SES and ERS match; GR before approval unless ERS (BP 16.4) | `payables.match` | J02, J04, R56, R78, CON, F2 (consignment settlement) | VERIFIED |
| S10 | Price tolerance: lower of percent and amount per line (TD 7.3; TD 9.4 writes it per unit, the Blueprint and 7.3 per line: per line is built) | `payables.match` | J05, R78 | VERIFIED |
| S11 | Quantity tolerance by percent (default 0 %) and by amount (units) | `payables._with_tolerance` (rule DMN-03 `qtyPct`, `qtyAbs`) | F2 `quantity_tolerance_by_absolute_units` | PARTIAL before, now VERIFIED (D34) |
| S12 | Tolerances per company code and supplier group | `rules.resolve("DMN-03", company_code, supplier_group)` | W1P | VERIFIED |
| S13 | Tax exact: rate, HSN/SAC, amount; CBIC rate schedule | `payables.match`, `gst.check` | J05 | VERIFIED |
| S14 | CGST + SGST inside the state, IGST between states (place of supply); wrong tax head is a tax exception | `gst.split_tax / place_of_supply`, `payables.capture / match` | F2 `gst_tax_heads_follow_the_place_of_supply` | MISSING, built (G6) |
| S15 | Reverse charge: supplier charges no GST, buyer self-assesses; ERP payload carries it | `gst.reverse_charge`, rule GST-RCM, `invoice.rcm_tax_minor` | F2 `gst_reverse_charge_supply` | MISSING, built (G6) |
| S16 | Exceptions: price, quantity, missing GR, tax, duplicate, service; resolution rules; buyer decides price variance; dispute keeps the block; reject closes | `resolve_exception`, `_request_price_acceptance`, `reject` | J04, J05, J06, R78, F2 (`rejected_and_disputed`) | VERIFIED |
| S17 | Credit notes (quantity and value), never above the invoice; reverse-charge lines carry no tax | `submit_credit_note` | J04, R78, F2 `credit_note_cannot_exceed_the_invoice` | VERIFIED |
| S18 | Debit notes, retention, GR/IR accrual | `debit_notes`, `retention_by_po`, `payables.grir` | J08, J09, CON, R78 | VERIFIED |
| S19 | State machine: Matched to Posted needs approval, no open exception, posting key, four-eyes | `payables.SM`, `approve`, `post` | J03, J04, R78 | VERIFIED |
| S20 | SoD-04 (PO creator), SoD-08 (capturer cannot approve), SoD-09 (approver cannot pay), also for system-built AP documents | `sod` rules; `release_retention`, `settle_consignment` record the capturer | J04, J12, F2 `capturer_is_recorded_for_retention_releases_and_consignment_settlements` | PARTIAL before, now VERIFIED (D31) |
| S21 | Posting idempotency: key tenant, company code, supplier, number; replay; ERP retry; lost response; concurrent double post posts once | `payables.post`, `integration` | J03, J07, F2 `concurrent_double_post_posts_once` | VERIFIED |
| S22 | Posting key for numbers with spaces or non-ASCII letters (a header cannot carry them) | `payables.post` accepts the percent-encoded key | F2 `invoice_numbers_with_slashes_spaces_unicode` | WRONG, fixed (D22) |
| S23 | Invoice numbers with slashes in every route (supplier numbers are the document number) | `http.EncodedSlashMiddleware`, `common.by_ref` | F2 same test | WRONG, fixed (D21) |
| S24 | ERP reconciliation: invoices, payments, credit and debit memos, returned payments | `payables.reconcile` | J12, R78, OO | VERIFIED |
| S25 | Payment run: selection, supplier and invoice filters, blocks, cooling-off, rejected and disputed never paid | `payables.payment_run / _assess_payment` | J09, J12, F2 `rejected_and_disputed` | VERIFIED |
| S26 | Two payment runs at the same time pay each invoice once and neither fails | `_due_invoices(lock=True)` | F2 `concurrent_payment_runs` | WRONG (second run lost), fixed (D27) |
| S27 | Payment proposal over 600+ open invoices in under 20 s; run and worklists at that size | `payables._PayContext`, `platform/batch.py` | F2 `payment_proposal_over_650_open_invoices`, `worklists_with_filters_stay_fast` | WRONG (35 s), fixed (D28) |
| S28 | Early-payment discount, SCF hooks | `early_payment` | J09, W1P | VERIFIED |
| S29 | Bank file pain.001 / NEFT: one PmtInf per company code, date and currency; foreign beneficiary data validated | `bank_files` | J09, F2 `foreign_payment_realised_fx_swift_data_and_pain001` | WRONG (mixed currencies in one PmtInf), fixed (D31b) |
| S30 | Bank result per payment; statement import camt.053, camt.054, MT940; batch entries; idempotent per statement id | `bank_statement`, `bank_files.record_bank_results` | J20, F2 `camt054_batch_entries_and_repeated_mt940_lines` | PARTIAL before, now VERIFIED (G2) |
| S31 | Approval value limits per user and action (ABAC), at approve, post and payment run | `abac` INVOICE_APPROVE / INVOICE_POST / PAYMENT_RUN | F2 `abac_value_limit_stops_a_large_approval` | VERIFIED |
| S32 | Approval bands as a multi-step chain by invoice value, and delegation of invoice approval | no chain for invoices (single approval plus the value limit); the delegation module serves tasks only | none | PARTIAL: needs the customer's bands (section 8.6) |
| S33 | ABAC company-code and plant scope on every finance read and write | `abac.read_scope`, `finance_scope`, guards in `payables` | F2 `abac_company_scope_covers_finance_reads_and_writes` | WRONG (reads unscoped; capture, resolve, reject, match, retention release, period close unguarded), fixed (D26) |
| S34 | Tenant isolation (RLS) on every finance table, new tables included | row-level security, migration 0020 | J16, migration check | VERIFIED |
| S35 | TDS: section, rate, thresholds, no-PAN rate, catch-up, deduction at payment, debit notes | `finance_controls.compute_tds / payment_tds` | J10, J13, FC, J19 | VERIFIED |
| S36 | s.197 certificate with an amount cap | `payment_tds`, `tds_certificate.max_base_minor` | F2 `certificate_amount_cap` | MISSING, built (G3) |
| S37 | TDS return by the date of payment (quarter and year) | `tds_export`, `tds_register` | F2 `tds_return_follows_the_payment_date` | WRONG (by invoice year), fixed (D25) |
| S38 | TDS on advances, adjusted against the final bill | `advance_taxed_minor` | F2 `tds_already_deducted_on_an_advance` | WRONG (taxed twice), fixed (D30) |
| S39 | TCS flag (off by default), carried to the ERP | `compute_tcs`, rule TDS.tcs | F2 `tcs_flag_is_off_by_default` | MISSING, built (G3) |
| S40 | Form 16A data, challan / BSR records, deducted against deposited per section | `services/tds_returns.py` | F2 `challans_reconcile_deducted_against_deposited_and_form_16a_data` | MISSING, built (G3) |
| S41 | MSME: 45 days from acceptance, 15 days without a written agreement | `finance_controls.due_date`, `supplier.msme_written_agreement` | J10, J13, F2 `msme_fifteen_day_rule` | PARTIAL before, now VERIFIED (G4) |
| S42 | MSME interest recorded when the bank rate is published | `accrue_msme_interest`, table `msme_interest` | F2 same test | PARTIAL before (computed, not recorded), now VERIFIED (G4) |
| S43 | Foreign currency: rate on the invoice date, group amount, USD payment | `fx_for`, `payment_run` | J11, J13 | VERIFIED |
| S44 | Realised exchange gain or loss at payment, in the ERP payload and on the payment | `fx_at_payment` | F2 `foreign_payment_realised_fx_swift_data_and_pain001` | MISSING, built (G5) |
| S45 | Period close and cut-off: last day, first day | `finance_controls` | J11, J21, F2 `closed_period_edges_last_and_first_day` | VERIFIED |
| S46 | ETag / If-Match and Idempotency-Key on every finance command | generic middleware (`platform/idempotency.py`, `preconditions.py`) plus route-level checks | J03, J14, J18, F2 (`replayed_idempotency_key_with_a_different_body`) | VERIFIED |
| S47 | Pagination, filters and cursors at 650 invoices; malformed dates, huge pages | `api/lists.py`, `pagination` | J16, F2 `malformed_filters_and_huge_pages`, `worklists_with_filters_stay_fast` | VERIFIED |
| S48 | Wrong supplier or role reading finance data | `api/*`, `finance_scope` | J16, F2 `a_supplier_user_cannot_read_finance_registers` | VERIFIED |
| S49 | Audit event for every state change; hash chain | `platform/audit.py` | J15 | VERIFIED |
| S50 | Event schemas and catalogue rows for every finance event | `events/schemas`, `docs/PIC_Event_Catalogue.md` | `test_wave1_jobs` (validates every emitted payload) | VERIFIED |
| S51 | KPIs of BP 16.5: first-pass match %, exception cycle time, duplicates prevented, discount capture %, DPO | `kpi.py` M10 | J15, F2 | VERIFIED (DPO now weighted in the company currency, D32) |
| S52 | KPIs asked for besides the Blueprint five: touchless invoice %, MSME compliance, exception ageing | `kpi.m10_touchless / m10_msme_on_time / m10_exception_ageing` | F2 `duplicates_refused_at_capture` (all codes present and computed) | MISSING, built (G7) |
| S53 | Screens INV-01..04 and the finance screens | `frontend/src/app/pic/invoices/*` | tsc, eslint (earlier pass) | CODE ONLY; this pass changed no frontend file, section 8.7 lists the screens it needs |
| S54 | A payment selection that names nothing (empty list of invoices or suppliers) is refused, not read as "pay everything due" | `payables._due_invoices` (EMPTY_SELECTION) | F2 `empty_payment_selection_is_refused` | WRONG (474 paid by one run), fixed (D37) |
| S55 | A payment block that no exception explains (it came with the ERP load) can be lifted: by finance per invoice, and by unblocking the supplier | `payables.release_payment_block`, `POST /v1/invoices/{ref}/payment-block/release`, `supplier.unblock` | F2 `a_payment_block_loaded_from_the_erp_can_be_lifted` | MISSING, built (D38) |
| S56 | The CBIC rate master is not applied to a foreign supplier's invoice (import IGST is paid on the bill of entry; the specifications say nothing on imports) | `payables.match` | F2 `foreign_supplier_invoice_skips_the_indian_rate_master` | WRONG, fixed (D39) |
| S57 | Approval value limits compare in the company currency | `abac._in_company_currency` | F2 same test (USD 2,360.00 against a 10,000.00 INR limit) | WRONG, fixed (D40) |
| S58 | A posting refused because the period is closed leaves evidence | `finance_controls._record_refusal` (audit event POSTING_REFUSED) | F2 `a_refused_posting_into_a_closed_period_leaves_an_audit_event` | MISSING, built (D41) |

Counts: 58 rows. As found: **VERIFIED 27**, **WRONG 15** (found by the probes and by the data-pack work), **PARTIAL 6** (5 closed in this pass, 1 open: row S32), **MISSING 9**, **CODE ONLY 1** (row S53). After this pass: **VERIFIED 56** (the 15 wrong, the 9 missing and the 5 partial rows each have a regression test that passes), **PARTIAL 1** (S32, needs customer policy), **CODE ONLY 1** (S53, the screens). Row S02 is verified at the local level (hash and QR checks); the live IRP call has no sandbox to test against.

## 8.2 What the first analysis marked and this pass re-checked

Rows 1 to 70 of section 2 were not re-proved one by one; the existing tests (`test_finance_journey.py`, `test_finance_controls.py`, `test_review_f7_f8.py`, `test_wave1_p2p.py`, `test_order_ops.py`, `test_signature_case.py`, `test_review_f5_f6.py`, `test_datasets_industry_construction.py`) were run again after the changes (section 8.8). Row 53 of section 2 (realised savings net of a value credit note) now has its test: `test_fin2_gap_a_realised_savings_are_net_of_a_value_credit_note`.

## 8.3 Defects found and fixed (numbering continues section 4)

| # | Finding and evidence | Fix | Test |
|---|---|---|---|
| D21 | A supplier invoice number is the document number and contains slashes (`THT/27-28/0311`); `GET /v1/invoices/THT%2F27-28%2F0311` and every command route answered 404 because servers decode `%2F` before routing. | `platform/http.py` `EncodedSlashMiddleware` keeps the escaped slash for `/v1/invoices/` and `/v1/debit-notes/`, `services/common.by_ref` and `debit_notes.by_ref` restore it | `test_fin2_invoice_numbers_with_slashes_spaces_unicode_work_in_every_route` |
| D22 | An invoice whose number has a space or a non-ASCII letter could never be posted: the posting key (tenant, company code, supplier, number) must be sent as the `Idempotency-Key` header, which carries ASCII without spaces. | `payables.post` accepts the percent-encoded key as well | same test |
| D23 | A 41-character supplier invoice number raised a database error (HTTP 500); a blank or whitespace-only number was accepted; doubled blanks made distinct keys. | `payables.capture` trims, rejects blank, over 40 characters and non-printable characters (422); the API model caps at 120 | `test_fin2_overlong_and_blank_invoice_numbers_are_422_not_500` |
| D24 | Quantity 1e12 at price 1e12 overflowed the BIGINT columns (HTTP 500); negative tax and GST rate above 100 were accepted. | `payables.capture` bounds quantity, unit price, line value, tax and GST rate (422) | `test_fin2_zero_negative_and_overflow_amounts_are_422` |
| D25 | The TDS register and the 26Q/16A export selected payments by the fiscal year of the invoice: an invoice of March paid in April was missing from the return of the quarter in which the tax was deducted. | both select by the payment date; `fiscal_year_range` | `test_fin2_d25_tds_return_follows_the_payment_date_not_the_invoice_year` |
| D26 | ABAC covered only approve, post and the payment run. A user limited to company code 2000 saw every invoice, payment, accrual, TDS row and KPI of company code 1000, and could capture, re-match, resolve, reject, release retention, settle consignment and close periods for it. | `abac.read_scope`, `services/finance_scope.py` (company codes and plants of the user restrict the lists, single reads answer 404, registers and insights are filtered); new actions INVOICE_CAPTURE, INVOICE_RESOLVE, PERIOD_CLOSE (added to every tenant's policy by `policy_for`), INVOICE_POST on retention release | `test_fin2_abac_company_scope_covers_finance_reads_and_writes` |
| D27 | Two payment runs started together: the second failed whole with CONSTRAINT_VIOLATION (the unique index prevented the double payment, but the run and every other invoice in it was lost). | the run locks the invoices it selects (`FOR UPDATE`) and re-reads them, so the second run finds them paid | `test_fin2_concurrent_payment_runs_pay_each_invoice_once_without_a_500` |
| D28 | The payment proposal over 651 open invoices took 35 s (profiled: 9,120 queries, 14 per invoice: rule sets, SoD log, credit and debit notes, bank accounts, periods, users). The run was slower. | `payables._PayContext` prefetches the per-invoice reads once, `platform/batch.py` remembers rule sets, ABAC attributes and SoD history within the call: 18 queries, 2.7 s | `test_fin2_payment_proposal_over_650_open_invoices_is_fast_and_the_run_pays_each_once` |
| D29 | The payment run raised AttributeError (HTTP 500) for an invoice without a process instance (an invoice migrated from the legacy ERP). | the workflow step is written only when the instance exists | same test (the scale fixture has no instances) |
| D30 | An advance paid to a contractor was taxed at payment, and recovered from the running bill whose full value was taxed again. | `finance_controls.advance_taxed_minor` lowers the bill's TDS base by the taxed share of the recovered advance | `test_fin2_gap_c_tds_already_deducted_on_an_advance_is_not_deducted_again_on_the_bill` |
| D31 | SoD-08/09: a retention release (approved and posted by the clerk's command) and a consignment settlement (built by the clerk) recorded no capturer, so the clerk could approve the settlement and pay the release. | both record INVOICE_CAPTURE, the release also INVOICE_APPROVE | `test_fin2_gap_a_capturer_is_recorded_for_retention_releases_and_consignment_settlements` |
| D31b | pain.001 put USD and INR payments of one company code and date into one PmtInf whose debit account currency was that of the first payment; NEFT would have carried a dollar payment. | one PmtInf per company code, date and currency; NEFT refuses foreign-currency and foreign-beneficiary payments (422 NEFT_INR_ONLY) | `test_fin2_gap_e_foreign_payment_realised_fx_swift_data_and_pain001` |
| D32 | KPI DPO added rupee and dollar amounts without converting; the duplicates-prevented KPI counted duplicates released as "not a duplicate" and never counted a duplicate refused with 409. | DPO weighted by the invoice exchange rate; duplicates: held and not released plus refused at capture (audit event DUPLICATE_BLOCKED) | `test_fin2_duplicates_refused_at_capture_leave_evidence_and_count_in_the_kpi` |
| D33 | The same IRN could be on two invoices (checked nowhere). | `payables.capture` refuses with 409 DUPLICATE_IRN and leaves the audit event | same test |
| D34 | The quantity tolerance existed as a percent only (BP: "by amount and %"). | rule DMN-03 `qtyAbs` (units); with `qtyPct` also set the lower of the two applies, like the price tolerance | `test_fin2_quantity_tolerance_by_absolute_units` |
| D35 | The payment list loaded every supplier and every invoice of the tenant on each request. | the codes and numbers of the page only | `test_fin2_worklists_with_filters_stay_fast_at_650_invoices` |
| D36 | The bank-statement matcher could not read a payment number glued to an MT940 `:86:` tag (`/EREF/PAY-2027-0001/REMI/...`). | candidate strings are also tried per slash-separated part | `test_fin2_gap_b_camt054_batch_entries_and_repeated_mt940_lines_match_individual_payments` |
| D37 | `payment_run` with an empty `invoice_numbers` (or `supplier_codes`) list ignored the filter and paid every due invoice (474 in one run, found while building the finance data pack). | an empty list is refused with 422 EMPTY_SELECTION in the run and the proposal; omitting the filter still means everything due (the scheduled job passes `None`) | `test_fin2_empty_payment_selection_is_refused_not_read_as_pay_everything` |
| D38 | Invoices loaded from the ERP with a payment block (and the invoices of a blocked supplier) could not be released: `unblock` lifted only the invoices named in its own BLOCKED audit event, and an active supplier's invoice had no release command at all. | `POST /v1/invoices/{ref}/payment-block/release` (scope `payment:run`, role FINANCE_CONTROLLER, a reason of at least 5 characters, ABAC INVOICE_RESOLVE, refused with open exceptions, duplicate hold or a blocked supplier, audit event PAYMENT_BLOCK_LIFTED with cause FINANCE_RELEASE); `supplier.unblock` also lifts the blocks of posted, unpaid invoices that no audit event lists (cause SUPPLIER_UNBLOCKED_ERP_BLOCK) | `test_fin2_a_payment_block_loaded_from_the_erp_can_be_lifted_by_finance_and_by_unblocking_the_supplier` |
| D39 | The CBIC GST rate master was applied to the invoice of a foreign supplier, whose invoice carries no Indian GST rate (the importer pays IGST and customs duty on the bill of entry). The Blueprint and the Technical Document do not mention imports at all. | the master check is skipped for a supplier whose country is not IN; the keyed tax is still matched exactly. Import duty (BCD), IGST on the bill of entry and the self-assessment are not built: they need the customer's customs process | `test_fin2_foreign_supplier_invoice_skips_the_indian_rate_master_and_the_limit_is_compared_in_rupees` |
| D40 | ABAC approval limits compared the document's minor units whatever its currency (USD 2,360.00 passed a 10,000.00 INR limit). | `abac._in_company_currency` converts at the rate fixed on the document, else the rate valid on its date; without a rate the document's own amount is compared | same test |
| D41 | A posting refused because its period is closed was recorded nowhere (the 409 rolls the request back). | audit event POSTING_REFUSED on the period (who, what, document date), written in its own transaction like an ABAC denial | `test_fin2_a_refused_posting_into_a_closed_period_leaves_an_audit_event` |

## 8.4 Gaps of section 5 closed

| Gap | What was built | Where | Test |
|---|---|---|---|
| a. SOD-08 for system-built AP documents; row 53 | capturer recorded for consignment settlements and retention releases; realised savings from a value credit note proved | `payables.settle_consignment / release_retention` | `test_fin2_gap_a_*` (2 tests) |
| b. Bank statements | CAMT.054 notifications (`Ntfctn`), camt.052 reports; a batch `<Ntry>` with several `<TxDtls>` becomes one result per transaction (own amount, own references, return data), the entry total must equal their sum; an entry that only names several payments is a batch booking when their amounts add up to the entry (each judged on its own, `batch: true`), otherwise AMBIGUOUS with the totals; MT940 repeated `:61:` lines under one bank reference match payment by payment; idempotent per statement id (existing unique key); synthetic fixtures `camt054_notification.xml`, `camt053_batch.xml`, `mt940_batch.sta` | `services/bank_statement.py` | `test_fin2_gap_b_*` |
| c. TDS | s.197 certificate amount cap (`max_base_minor`, consumed and remaining shown on the supplier finance view, the rest of the base at the section rate, blended rate stored); TDS on advances at payment with the bill adjusted (D30); TCS flag (rule TDS.tcs, off by default, `addToPayable` decides whether the supplier is paid it) carried to the ERP payload; Form 16A data per deductee and quarter as JSON or CSV (`GET /v1/finance/tds-certificates/data`, no PDF); challan / BSR records (`POST /v1/finance/tds-challans`, void, list) and the reconciliation of deducted against deposited per company code and section with the difference (`GET /v1/finance/tds-challans/reconciliation`) | `finance_controls.py`, `services/tds_returns.py`, `api/finance.py`; tables `tds_challan`, columns in migration 0020 | `test_fin2_gap_c_*` (4 tests) |
| d. MSME | rule MSME `noAgreementDays` (15) with the supplier flag `msme_written_agreement` (PUT `/v1/suppliers/{code}/finance` field `msmeWrittenAgreement`); interest accrual record per late payment (`msme_interest`, event `msme.interest.accrued`, in the ERP payment payload, `GET /v1/finance/msme-interest`) when `bankRatePct` is published | `finance_controls.py`, `payables.payment_run` | `test_fin2_gap_d_msme_fifteen_day_rule_and_interest_accrual` |
| e. FX | realised gain or loss at payment against the invoice rate (stored on the payment: `fx_rate`, `amount_group_minor`, `fx_gain_loss_minor`, and in the ERP payload; no rate for the payment date skips the payment with the reason); foreign beneficiary bank fields (country, SWIFT/BIC, intermediary BIC, charge bearer, RBI purpose code) through the dual-approved bank change; a file with a foreign beneficiary is pain.001.001.09 with `CdtrAgt/FinInstnId/BICFI`, `IntrmyAgt1`, `ChrgBr`, `Purp/Cd`, validated at the proposal (skipped with the reason) and at file generation (409 PAYMENT_FILE_INCOMPLETE) | `finance_controls.fx_at_payment`, `bank_files.py`, `supplier.request_bank_change`, `api/plan_request.py` | `test_fin2_gap_e_foreign_payment_realised_fx_swift_data_and_pain001` |
| also | GST tax heads and reverse charge (G6); KPIs touchless invoice %, MSME compliance, exception ageing (G7) | `gst.py`, `payables.py`, `kpi.py` | `test_fin2_gst_*`, `test_fin2_duplicates_refused_*` |

## 8.5 Behaviour changes other code can depend on

* `GET /v1/invoices`, `GET /v1/invoices/{ref}` (and every command on an invoice), `/v1/payments`, `/v1/grir`, `/v1/payables/insights`, `/v1/reconciliation/runs`, `/v1/finance/*` now apply the user's company-code and plant attributes. A user without the attributes (or with `*`) sees what they saw before; a user with attributes sees only their scope, other documents answer 404.
* New ABAC actions INVOICE_CAPTURE, INVOICE_RESOLVE, PERIOD_CLOSE (company code check) apply to tenants whose ABAC rule predates them as well.
* The invoice routes keep an escaped slash (`%2F`) in the path parameter; `by_ref` restores it. Plain, unescaped slashes in a number are still not routable (they cannot be told from path segments).
* The posting key header may be the percent-encoded key.
* `payables.insights`, `payables.grir`, `finance_controls.tds_register / tds_export` take an optional list of company codes; `bank_files.pain001` emits pain.001.001.09 only when a foreign beneficiary is in the file (domestic files are byte-for-byte as before except one PmtInf per currency).
* The payment run locks the selected invoices; a payment to a foreign beneficiary or in a currency without a rate for the payment date is skipped with a reason; a supplier with two active bank accounts is skipped with a reason (it was an unhandled error).
* The TDS register and exports select by payment date.
* `settle_consignment` and `release_retention` record SoD actions: the clerk who ran them cannot approve the settlement or pay the release. **The data packs `seed/datasets/purchase_types.py` (line 411) and `seed/datasets/industry_healthcare.py` (line 310) settle a consignment and approve it with the same user (`ap.clerk`), which SOD-08 now refuses (409 SOD_CONFLICT while the pack loads). They need a second approver for the ERS document (in the AXN tenant `finance.controller`); this pass did not edit the `seed/datasets` folder. With a different approver for the ERS document the `purchase_types` pack and its nine tests pass (checked with a test-only wrapper); the `industry_healthcare` pack was not re-checked because its tenant has its own users.**
* The SUPPLIER_INVOICE payload gains `placeOfSupply` and `taxHeads` for invoices captured after migration 0020, `reverseCharge` and `rcmTaxMinor` for reverse-charge invoices, `tcsSection / tcsRatePct / tcsMinor` when TCS is on; the PAYMENT payload gains `tcsMinor`, `msmeInterestMinor`, `fxRate`, `amountGroupMinor`, `fxGainLossMinor` when they apply. Invoices posted before the migration keep their payload.
* `payment_run` / `payment_proposal` refuse an empty `invoice_numbers` or `supplier_codes` list (422 EMPTY_SELECTION); an omitted filter still selects everything due.
* New command `POST /v1/invoices/{ref}/payment-block/release` (finance); `supplier.unblock` additionally lifts the payment blocks of posted, unpaid invoices that came with the ERP load.
* The supplier finance rules (MSME class and Udyam, TDS section, PAN, written agreement) are now `finance_controls.set_supplier_finance(session, supplier, ...)`; the route `PUT /v1/suppliers/{code}/finance` only locks, checks If-Match and calls it (same errors, same audit event). The accrual of MSME interest is created by the real payment run (`msme_interest`, `GET /v1/finance/msme-interest`); a pack need not write a stand-in event.
* The CBIC rate master is not applied to a supplier whose country is not IN; ABAC value limits compare in the company currency (document rate, else the rate on its date); a refused posting into a closed period writes the audit event POSTING_REFUSED.
* KPI registry: three new M10 codes (TOUCHLESS_INVOICE, MSME_ON_TIME, EXCEPTION_AGEING); DPO and DUPLICATES_PREVENTED are computed differently (D32).
* Bank-change request accepts `country`, `swift_bic`, `intermediary_bic`, `charge_bearer`, `purpose_code`; the IFSC is optional for a foreign account; the account number is alphanumeric 5 to 34 (digits 9 to 18 for India, checked).
* Migration `0020_finance_second_pass` (down_revision 0019): additive columns on `invoice`, `invoice_line`, `payment`, `supplier`, `supplier_bank_account`, `tds_certificate` and the tables `tds_challan`, `msme_interest` (grants and forced RLS). The data-pack work in `seed/datasets` can use the new columns after this pass; none of them is required by existing packs (all defaulted or nullable).

## 8.6 What remains, and why

* Approval bands for invoices as a multi-step chain, and delegation of authority for invoice approval: the platform has the per-user value limit (ABAC) at approve, post and pay and the task delegation module, but an invoice is approved by one command, not by a task chain. The bands and approvers are customer policy (section 8.9).
* Partial payment of an invoice: the payment run pays the net payable in full (the unique live payment per invoice is a control). The Blueprint does not ask for part payments; the credit-note and debit-note netting covers adjustments.
* Live IRP lookup, live ERP mapping of the reversal, CBIC rate master loading and the bank host-to-host link need customer credentials or data (unchanged from section 5).
* Form 16A as a PDF and the TRACES certificate number: out of scope by instruction; the data export has `certificateNo: null` to be filled from TRACES.
* TDS on foreign remittances (s.195), the TCS credit/refund handling in the ERP, and the debit-note tax heads (a debit note uses the single tax amount): not built; they need the tax team's rules.
* MSME interest is recorded at payment; interest on invoices still unpaid after the due date is shown by the due ladder, not accrued daily.
* The browser pass of the screens that this pass needs (section 8.7) is the lead's.

## 8.7 Screens that need a change (not done: no frontend file was touched)

Invoice capture dialog (optional CGST/SGST/IGST per line, invoice number limited to 40 characters); invoice detail (place of supply, tax heads, reverse charge, TCS, TDS certificate and cap used); payment proposal and run dialog (TCS, certificate split, foreign-beneficiary and exchange-rate skip reasons); supplier finance card (written agreement switch, certificate amount cap with consumed and remaining); bank change form (country, SWIFT/BIC, intermediary, charge bearer, purpose code); bank statement upload (CAMT.054, batch parts); new screens for TDS challans with the reconciliation, Form 16A data download and the MSME interest register; KPI tiles for the three new M10 KPIs.

## 8.8 How the proof was run

All on the local test Postgres (127.0.0.1:54329), each run on a freshly created database; nothing touched Neon.

* `backend/tests/pic/test_finance_second_pass.py`: 35 tests (own tenant FIN2). Every test in it passes in the final full run below; during development it ran many times, and the failures it showed (missing import in the match path, a wrong event column, a stub that did not know the new query) were fixed.
* `test_finance_journey.py` (21) + `test_finance_controls.py` (30) + the second-pass file (31 at that time): 82 passed on one fresh database. Two existing tests were changed for good reasons: `test_finance_journey.py::test_20` now asks for a pain.001 file for the run that contains a USD payment (NEFT is rupee-only, D31b), `test_finance_controls.py` stub answers the new advance-recovery query, and `test_wave1_erp_ai.py::test_payment_amount_keeps_back_the_withholding_tax` looks for `payment_tds` instead of `at_payment_detail`.
* Finance-related groups, one fresh database each: `test_review_f7_f8`, `test_wave1_p2p`, `test_order_ops`, `test_signature_case`, `test_review_f5_f6`: 101 passed; `test_wave1_jobs`, `test_wave1_spend_kpi`, `test_document_refs_with_slashes`, `test_controls`, `test_datasets_industry_construction`, `test_datasets_purchase_types`: 95 passed, 9 errors (`test_datasets_purchase_types`, see below); `test_review_platform`, `test_platform_ops`, `test_wave1_platform`, `test_admin_enterprise`, `test_admin_journey`, `test_legacy_migration`, `test_inventory_journey`: 151 passed.
* Migration `0020`: upgrade head, downgrade to 0019, upgrade head, `alembic check`: all exit 0 (database pic_mig20).
* The whole `tests/pic` suite, once, on a fresh database after the last code change: **915 passed, 6 failed, 38 errors in 40 minutes 43 seconds.** Every failure and error is in a data-pack test file: `test_datasets_purchase_types` (9 errors) and `test_datasets_industry_healthcare` (8 errors): the packs settle a consignment and approve it with the same clerk, which SOD-08 now refuses; `test_datasets_finance_ops` (21 errors): its foreign-currency invoice S091 of 4.65 crore paise (converted) is approved by a user with a 1 crore limit, which the currency-aware limit (D40) now refuses; `test_datasets_contracts_kac` (4), `test_datasets_industry_manufacturing` (1), `test_datasets_reference_data` (1): count assertions disturbed by the data the aborted finance_ops pack and earlier pack loads leave in the shared database. No test outside the data-pack files fails.


## 8.9 What the product owner must supply (additions)

| Item | Why |
|---|---|
| Deductor TAN and PAN per company code (rule TDS `deductor`) and the deductee PAN where the supplier has no GSTIN | Form 16A / 26Q data lists them as missing until supplied |
| TDS challan data from the bank challans (BSR code, serial, deposit date, amount per section and quarter) | reconciliation of deducted against deposited |
| TCS decision: which transactions, rate, threshold, whether the supplier is paid it with the invoice (rule TDS `tcs`) | TCS is off by default |
| The notified reverse-charge goods and services (HSN/SAC prefixes) and the rule for unregistered suppliers (rule GST-RCM) | reverse charge is applied only where the rule says so |
| Which suppliers have a written payment agreement (MSME) | 45 days with, 15 days without |
| RBI bank rate to publish in rule MSME `bankRatePct` | interest accrual |
| Daily exchange-rate source (`fx_rate`) including the payment date | realised gain or loss; payments are skipped without a rate |
| Foreign suppliers' bank details: SWIFT/BIC, intermediary, charge bearer, RBI purpose code, and the bank's pain.001.001.09 specification | foreign payment files |
| Invoice approval value bands and who approves each band; who may delegate | approval chain and delegation of authority (not built) |
| Sample camt.054 and batch camt.053 / MT940 files from the bank | the shipped fixtures are synthetic |

How to run the second-pass proof: `backendenv\Scripts\python.exe <scratchpad>\mkdb.py pic_test_fin2`, `set TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:54329/pic_test_fin2`, `backendenv\Scripts\python.exe -m pytest tests/pic/test_finance_second_pass.py -q` (about 5 minutes after the schema is seeded). New environment variables: none.


## 8.10 Addendum: findings of the browser pass over the finance screens (3 November 2026)

| # | Finding | Fix | Test |
|---|---|---|---|
| D42 | A credit note or debit note dated into a closed period was accepted: `assert_open` looked at the day of posting only (a credit note dated 2026-08-15 into closed 2026-08 answered 201). | credit note submit, debit note submit and debit note post check both the day of posting and the date the document carries (409 PERIOD_CLOSED, audit event POSTING_REFUSED). Invoices are posted on the posting day and payments by their run date, which were already checked | `test_fin2_credit_and_debit_notes_dated_into_a_closed_period_are_refused` |
| D43 | `GET /v1/kpis?module=M10&trend=true` took about 12 s on 688 invoices: three KPIs each rebuilt the payables insight (677 queries each, one MSME rule lookup per invoice). | the insight is computed once per request (`kpi.read` opens the batch cache) and the MSME class once per supplier: 0.6 s on 700 invoices; no migration needed | `test_fin2_kpi_strip_with_trend_is_fast_over_the_scale_data` |
| D44 | The proposal and the run computed TCS, certificate, certificate base and TDS base but returned only `tdsMinor` and `discountMinor`. | `tcsMinor`, `tdsCertificate`, `tdsCertBaseMinor`, `tdsBaseMinor` on `items[]` of the proposal and `paid[]` of the run | `test_fin2_proposal_and_run_expose_the_tax_parts_they_compute` |
| D45 | The lines of a batch entry of a bank statement could not be told from separate entries, and a mismatch printed raw paise. | every item carries `entry` (the bank's AcctSvcrRef / NtryRef, else its reference); amounts in details read `INR 228,675.97` | `test_fin2_bank_statement_items_name_their_bank_entry_and_amounts_are_in_rupees` |
| D46 | `POSTING_REFUSED` was visible only through the audit trail. | `GET /v1/finance/periods` items carry `refusedAttempts {count, lastActor, lastAt}` | same test as D42 |
| D47 | A GSTIN that the configured `PIC_FIELD_KEY` cannot open was a bare 500 in finance, TDS data, GST and e-invoice code. | `finance_controls.supplier_gstin`: 503 problem+json `FIELD_KEY_MISMATCH` naming `PIC_FIELD_KEY` and the supplier (no ciphertext), audit event `FIELD_KEY_MISMATCH` once per supplier | `test_fin2_an_unreadable_encrypted_gstin_is_a_clear_503_audited_once` |

No migration was needed for this addendum (head stays 0020).
