# PIC Finance: proposed rule values for Kaveri Auto Components (KAC)

**Status: MOCK proposal - pending client sign-off.** Nothing below is confirmed by the customer, its tax advisers or its bank. The values are a starting
proposal, scaled to the value range of KAC's own (mock) SAP extract, so the demo tenant behaves like a configured one. Each rule is published in PIC as a new
effective-dated version `2026.2-KAC-MOCK` (PAYMENT-FILE: `2026.2-CC1000-MOCK-A` / `-B`) whose description reads "MOCK - pending client sign-off". The
customer's finance, tax and treasury owners decide the real values; the sign-off tables at the end are theirs to fill and are intentionally blank. Until they
are signed these values must not be described as agreed, and no number here is legal or tax advice.

Date: 3 November 2026. Scope: tenant KAC (company code 1000, plants 1100 Hosur, 1200 Oragadam, 1300 Bidadi). AXN keeps the documented defaults (version `2026.1`).
Amounts are in rupees, stored in paise. The dataset behind these values is described in `backend/data/erp_mock/KAC_FINANCE/README.md`; the pack is
`app/pic/seed/datasets/finance_ops.py` (key `finance-ops`).

## 1. What the values are scaled to

KAC's own data (mock SAP extract `backend/data/erp_mock/KAC`): 242 suppliers (12 blocked), 587 open supplier invoices loaded from the extract (INR 55.7 crore), 161 open purchase orders,
payment terms N15 (91 suppliers), N30 (95), N45 (31), N60 (25). Median open invoice INR 3.3 lakh, 90th percentile INR 23.6 lakh; the largest single purchase-order line about INR 40 lakh.

## 2. MSME (rule MSME) - payment inside 45 days, interest on delay

| Key | Default | Proposed for KAC | Why |
|---|---|---|---|
| `maxDays` | 45 | **45** | MSMED Act 2006 s.15: never more than 45 days from the day of acceptance, even when the contract says more. |
| `classes` | MICRO, SMALL | unchanged | Medium enterprises are outside s.15-16. |
| `noAgreementDays` | 15 | unchanged | s.15 allows 15 days when there is no written agreement; the supplier flag `msme_written_agreement` decides. |
| `bankRatePct` | empty (no interest computed) | **6.50 (MOCK)** | A placeholder for the RBI bank rate on the payment date; the treasury team must confirm the figure it uses. Without a rate PIC computes no interest at all. |
| `interestMultiple` | 3 | unchanged | s.16: three times the bank rate, compounded monthly. |

The dataset marks 48 of 244 KAC suppliers (about 20 %) as MICRO or SMALL, with a generated Udyam number (`UDYAM-XX-00-0000000`, fictional), including the three
suppliers with the oldest open invoices; two N15 MSME invoices of the dataset are paid 6 and 8 days after their due date on purpose so the interest computation has cases (30 October run).

## 3. TDS (rule TDS) - sections, rates, thresholds

The body is the documented default (illustrative; **the tax team confirms every row**), published as a KAC version so the label is visible:

| Section key | Meaning | Rate % | Single payment threshold | Annual threshold |
|---|---|---|---|---|
| 194C-IND | Contractor, individual / HUF (proprietors, "Enterprises") | 1 | 30,000 | 1,00,000 |
| 194C-OTH | Contractor, other payees (job work, logistics, maintenance, facilities) | 2 | 30,000 | 1,00,000 |
| 194J-TECH | Technical services / IT services | 2 | none | 50,000 |
| 194J-PRO | Professional services | 10 | none | 50,000 |
| 194H | Commission / brokerage | 2 | none | 20,000 |
| 194I-LB | Rent, land and building | 10 | none | 6,00,000 |
| 194I-PM | Rent, plant and machinery | 2 | none | 6,00,000 |
| 194Q | Purchase of goods above the annual limit (on the excess only) | 0.1 | none | 50,00,000 |

`noPanRatePct` 20 (higher rate when the supplier has no PAN; every KAC supplier has a PAN from its GSTIN, so the case does not occur in the data). TCS (`tcs`)
is switched off; the deductor block (`deductor.tan`, `pan`, `name`, `address`) is empty because KAC's TAN is the client's to supply.

Section assignment in the dataset (supplier master, rule-based, replaceable): PROF-SERVICES 194J-PRO; IT-SERVICES and SOFTWARE-LICENCES 194J-TECH; LOGISTICS,
TOOLING-SERVICES, FACILITIES, MACHINING (job work) and MRO 194C-OTH (194C-IND for proprietary names); two FACILITIES suppliers 194I-LB (rent); castings, forgings,
raw materials, fasteners, rubber, electronics and packaging suppliers none; the one supplier with the largest purchases 194Q (its new invoices stay under the
annual limit, so nothing is withheld on it in the data).

Lower-deduction certificates under s.197 (four, numbers `LDC-MOCK-2627-0001..0004`): 1 % valid 1 Apr 2026 - 31 Mar 2027; 1 % **expiring 15 Nov 2026**; 0.5 % with an
**amount cap of INR 25,00,000** (recorded in the certificate's cap field when the service carries it, in its note otherwise); 1 % valid to 31 May 2027.

## 4. PAYMENT-FILE (bank payment file) - debtor account per company code

| Version | Effective | `debtorName` | `debtorAccountRef` | `debtorIfsc` |
|---|---|---|---|---|
| `2026.2-CC1000-MOCK-A` | 1 Sep 2026 | Kaveri Auto Components Pvt Ltd (MOCK debtor account A) | MOCK-CA-0001 | MOCK0000001 |
| `2026.2-CC1000-MOCK-B` | 19 Oct 2026 | Kaveri Auto Components Pvt Ltd (MOCK debtor account B) | MOCK-CA-0002 | MOCK0000002 |

Both are obviously fake (never a real account or IFSC). Account B models a second bank taken into use mid-October (its pain.001 mandate is "not active yet", so the
first October file is rejected and re-sent as a NEFT file). The real account, IFSC, file format (pain.001 or NEFT), cut-off times and whether the bank echoes the
payment number as EndToEndId are the treasury owner's to supply.

## 5. PAYMENT-RUN (scheduled payment proposal)

`horizonDays` **7** (the default 3 would miss a weekly run), `autoRun` false (humans decide; PIC ignores `true`), `approverRole` FINANCE_CONTROLLER,
`slaBusinessDays` 1. The dataset runs payments on 18 September, then 2, 9, 16, 23 and 30 October (and a foreign-currency run on 30 October).

## 6. Invoice approval bands and approvers (user limits, ABAC)

PIC bounds approvers through attributes (`company_codes`, `approval_limits`) enforced by rule ABAC, not through a separate band table. The dataset creates mock users:

| User (local part) | Role | Limits (INR) | Purpose |
|---|---|---|---|
| ap.clerk.1, ap.clerk.2 | AP_CLERK | approve invoice up to 10,00,000; post up to 50,00,000 | capture / approve / post of everyday invoices (four-eyes: SOD-08) |
| fin.controller.1, fin.controller.2 | FINANCE_CONTROLLER | approve and post up to 3,00,00,000; payment run 0 | invoices above the clerks' limit, period close and reopen |
| treasury.1000 | FINANCE_CONTROLLER (function TREASURY) | payment run up to 5,00,00,000 per invoice; approve 0 | releases payments (SOD-09: never the approver of the invoice) |
| tax.manager | FINANCE_CONTROLLER (function TAX) | approve 0, post 0, payment run 0 | s.197 certificates, TDS export; cannot approve or pay |

Rationale: 10 lakh is about three times the median invoice (3.3 lakh) and well below the 90th percentile (23.6 lakh), so clerks clear routine invoices and finance sees the large ones; 3 crore
covers every open order line. PIC has no TREASURY or TAX role: the function is an attribute on a FINANCE_CONTROLLER user (a dedicated role is a service change).
The legacy users `ap.clerk`, `finance.controller` and `finance.controller2` are unrestricted and unchanged.

## 7. Early payment and supply-chain finance (rule EARLY-PAYMENT, unchanged)

Default values are used: `maxDiscountPct` 5, `minDaysEarly` 3, `offerValidDays` 7, SCF enabled for invoices of at least INR 1,00,000. The dataset has 11 dynamic-discounting
offers (1.0 / 1.5 / 2.0 %, offered by AP, accepted by the supplier's accounts-receivable login, applied at the run) and 4 SCF elections. Whether KAC runs such a programme,
the discount ceiling and the financier are commercial decisions of the client.

## 8. Rebates (contract data)

Two supplier-scope rebate agreements on master agreements KAC-MA-0004 (quarterly, 0.5 % from INR 0, 1.0 % from INR 1 crore, retroactive) and KAC-MA-0005 (monthly,
0.3 % / 0.6 % from INR 50 lakh). The contract owners agree the real tiers; the dataset settles the quarter to September 2026 of the first as a vendor credit memo.

## 9. FX reference rates

Daily INR per USD, EUR, GBP, JPY and CNY for 1 April to 30 October 2026 (weekdays) are a **generated** series (`app/pic/tools/finance_mock.py`), anchored on the FBIL
reference rate of 28 October 2026 that the reference-data pack carries (USD 95.2278, EUR 105.8641, GBP 126.4657, JPY 60.3100 per 100; CNY at USD / 7.25 has no
official anchor). The series is smooth (about +-3 % around the anchor) and flat from 29 October so later documents keep the official value. It is **not** RBI or
FBIL history. The client loads its own rate source (`fx_rate`) before go-live.

## 10. Not proposed (stays as shipped, needs the client)

DMN-03 invoice tolerances (1 % or INR 500 price, 0 % quantity), DEBIT-NOTE rule (cap 25 % of invoice net, buyer chain up to INR 1 lakh), posting-period calendar and who may
close (the dataset uses finance controllers), ERP posting profile for TDS / MSME interest / credit memos / payment reversal, the IRP / GSP credentials, the host-to-host bank link.

## 11. How a value is changed after sign-off

Publish a new version of the rule (POST /v1/admin/rules, effective-dated, audited); never edit a version. Users' limits are changed in the user administration (audited).
The mock documents stay as history; they are labelled MOCK in their reasons and notes and in the audit trail (`actor mock-data:finance_ops`).

## 12. Sign-off (to be completed by the customer; approver, date and signature intentionally blank)

| Area | Owner (role) | Values to confirm | Approver | Date | Signature |
|---|---|---|---|---|---|
| Finance (AP policy) | Head of Finance / AP | approval bands and limits (section 6), tolerances, early payment | | | |
| Tax | Tax manager / adviser | TDS sections, rates, thresholds, certificates, TAN, TCS decision (section 3) | | | |
| Treasury | Treasury head | debtor accounts, file format, run schedule, MSME bank rate, payment limits (sections 2, 4, 5, 6) | | | |
| Procurement | Contract owners | rebate tiers (section 8) | | | |
