# Partial payments, section 195 TDS and the Form 16A information copy

AlphaHelion PIC, finance module (M10). Status: built on 9 November 2026 (migration 0028).

PIC is not a tax authority. Every rate, threshold and label below is rule data that the client can change without a release. The default values are MOCK values. The client's chartered accountant must confirm them before go-live (see the last section).

## 1. Partial payments

### What it does

- An invoice can be paid in parts across payment runs.
- PIC keeps the cash paid on the invoice (`paid_minor`) and works out the open amount.
- The payment status is `PARTIALLY_PAID` while something is open. The last part makes it `IN_PAYMENT`, and the ERP posting makes it `PAID`.
- Each part is its own payment record, its own PAYMENT message to the ERP and its own line in the bank file.
- Each part has a sequence number (`installment_no`). A returned part keeps its number.

### How to pay a part

- In the payment run screen, enter an amount and a reason on the proposal line. Preview, then run.
- API: `POST /v1/payments/runs` with `partials: [{invoice, amountMinor, reason}]`. The preview is `POST /v1/payments/proposal` with the same body.
- An amount equal to the open amount is the final payment. A run without an amount pays the whole open amount.
- A partial amount is refused (422 `PARTIAL_NOT_ALLOWED`) when:
  - it is more than the open amount,
  - it is below the minimum,
  - the reason is too short,
  - the invoice already has the maximum number of payments,
  - the invoice has an accepted early-payment discount or an SCF election.

### What the open amount is

Open amount = gross − credit notes + debit notes netted − retention − early-payment discount − advance recovery − TDS withheld + TCS paid − cash already paid.

### Rules for TDS, debit notes, early payment and MSME

- **TDS is deducted once.** PIC already deducts TDS at payment (the tax is fixed at posting and taken when the supplier is paid). With parts, the whole TDS of the invoice is deducted with the first part. Later parts deduct nothing. The Form 16A data shows the deduction on the date of the first part.
- If the bank returns the part that carried the TDS, the TDS is deducted again by the next payment.
- Debit notes are netted into the first part only. A debit note posted after that is paid on its own, as for a paid invoice.
- An early-payment discount is earned only by paying the whole invoice. PIC refuses a partial amount on an invoice with an accepted discount or SCF. It also refuses an early-payment offer on a partially paid invoice.
- MSME: a partial payment does not change the due date. The open part stays due on the MSME date (acceptance + 45 days). Interest on a late part is worked out on that part.
- SoD is unchanged: every part goes through the same SoD check (SOD-09: the approver of the invoice cannot release its payment), bank checks and blocks.

### A returned part

- The bank returns one part: that payment is cancelled. Only its cash is reopened.
- The other parts stay paid. The invoice goes back to `PARTIALLY_PAID` (or `UNPAID` if nothing is left).
- The ERP reversal message (`PAYMENT_REVERSAL`) is sent for that part only.
- A Form 15CA used by the returned part is freed for the next remittance.

### Rule PARTIAL-PAYMENT (effective-dated, per company code)

| Field | Default | Meaning |
|---|---|---|
| `enabled` | true | partial payments allowed |
| `minAmountMinor` | 1,00,000 (₹1,000.00) | smallest partial payment, invoice currency minor units |
| `maxInstallments` | 12 | payments per invoice, returned ones included |
| `reasonMinLength` | 10 | length of the reason |

## 2. Section 195: payments to non-residents

### Numbering

PIC uses the section numbers of the Income-tax Act, 1961 as the client asked. The Income-tax Act, 2025 replaced the 1961 Act from 1 April 2026 and renumbers the sections. PIC does not invent the new numbers. The label is rule data (`sectionLabel`, `act`, `noPan.sectionLabel`). The client's tax advisor must confirm the numbering and the rates.

### Tax residency of a supplier

Screen: supplier finance. API: `GET` / `PUT /v1/suppliers/{code}/tax-residency`.

- Resident or non-resident, and the country of residence.
- Payee type: COMPANY (foreign company) or NON_COMPANY.
- PAN, or no PAN.
- Tax identification number in the home country.
- Tax Residency Certificate (TRC): number, valid from / to, document reference.
- Form 10F: acknowledgement, filing date, period it covers.
- No-PE declaration (no permanent establishment in India), with its validity.
- Gross-up (s.195A): the company bears the tax.
- Default payment nature.

PAN, tax ID, TRC number and Form 10F and Form 15CA acknowledgements are encrypted with the tenant field key, like the GSTIN and bank account. Screens and the audit trail show masked values only. Key rotation (`tools/reencrypt.py`) covers the new fields.

### How the rate is chosen

PIC decides the rate on the **payment date**. It uses the documents valid on that day and the exchange rate of that day. Posting fixes a provisional figure for the ERP.

1. **Act rate** of the payment nature (ROYALTY, FTS, INTEREST, OTHER) for the payee type.
2. Add the **surcharge** of the slab, then the **health and education cess** (4%).
3. **Treaty (DTAA) rate**: used when the TRC and Form 10F are valid on the payment date, and the treaty has an article for the nature. Some entries also need the no-PE declaration. The treaty rate is taken as is: no surcharge or cess.
4. The **lower** of the Act rate and the treaty rate applies.
5. **No PAN (s.206AA)**: the higher of 20% and the Act rate. The treaty is not used.
   - Relief: a non-resident who gives the TRC, the tax ID and the address (Rule 37BC) for royalty, FTS or interest is not caught by s.206AA. The normal choice applies.
6. A valid **lower-deduction certificate** (s.197) replaces the rate when it covers the whole payment.
7. **Gross-up (s.195A)**: the income is grossed up to net ÷ (1 − rate). The tax is grossed income − net. The supplier gets the full invoice. The company pays the tax. The surcharge slab is chosen on the grossed-up amount.

The basis is stored on the payment: `DTAA`, `ACT`, `NO_PAN_206AA` or `LOWER_DEDUCTION_CERTIFICATE`. So is the breakdown: Act rate, surcharge, cess, treaty article, FX rate and date.

Where gross-up is set:
- on the invoice (`PUT /v1/invoices/{ref}/withholding-195`),
- else on the contract of the purchase order (`contract.tax_gross_up`),
- else on the supplier.

The invoice can also change the payment nature until the first payment.

### Foreign currency

- The tax is worked out in the invoice currency (it is withheld from the remittance).
- It is also worked out in INR (the 27Q return and the challan carry INR).
- The rate date is in the rule: `fxRateDate` = PAYMENT_DATE (default) or INVOICE_DATE. Rates come from the tenant's FX table.
- The INR tax is rounded to the rupee (`roundInrToMinor`).

### GST on imported services

- A service (SAC chapter 99) bought from a supplier located outside India is an import of services.
- The supplier charges no Indian GST. The company pays IGST itself under reverse charge (IGST Act s.5(3), notification 10/2017-Integrated Tax (Rate)).
- PIC marks such an invoice as reverse charge on its own, without the GST-RCM rule. The invoice tax is 0 and the self-assessed IGST (18 % for the mock services) is in `rcmTaxMinor`, which goes to the ERP with the invoice.
- Imported goods are not reverse charge: their IGST is paid at customs on the bill of entry.
- The s.195 tax is worked out on the invoice amount without this GST.

### Form 15CA / 15CB checkpoint

- A remittance to a non-resident is not released until a Form 15CA acknowledgement covering it is recorded.
- Form 15CB (the CA's certificate) is also needed above the threshold.
- Record them: `POST /v1/invoices/{ref}/form15` (finance only). Fields: part, acknowledgement, filing date, amount covered, and the 15CB number (UDIN), date, CA name and membership number.
- One Form 15CA covers one remittance. A partial payment needs its own 15CA.
- In a run that names the invoice, a missing form refuses the whole run before anything is written: **409** problem+json `FORM_15CA_REQUIRED` or `FORM_15CB_REQUIRED`.
- In a run that only picks up due invoices, the invoice is skipped with the same code. One missing form does not stop the tenant's run.
- An invoice of a non-resident posted before its residency was recorded is skipped (`TDS_195_NOT_DETERMINED`) until its nature is set.

### Returns: 26Q and 27Q

- Payments to non-residents go to **Form 27Q**. Residents stay in **26Q**.
- The challan reconciliation shows the return form per section and the totals per form.
- The Form 16A data shows the return form, the residency, the country and, for 27Q, the basis, treaty article, currency and FX rate.
- Exports: `GET /v1/finance/tds-export?format=26Q|27Q|16A`. 26Q leaves out the non-residents. 27Q lists only them, with the rate breakdown.
- s.195 section keys are `195-ROYALTY`, `195-FTS`, `195-INTEREST`, `195-OTHER`. Challans can be recorded against them.

### Rule TDS-195 (effective-dated, per company code)

| Field | Default (MOCK) |
|---|---|
| `act` / `sectionLabel` / `returnForm` | Income-tax Act, 1961 / 195 / 27Q |
| `natures.ROYALTY.actRatePct` | 20 (company and non-company) |
| `natures.FTS.actRatePct` | 20 |
| `natures.INTEREST.actRatePct` | 20 |
| `natures.OTHER.actRatePct` | 35 company / 30 non-company |
| `surcharge.COMPANY` | 2% above ₹1 crore, 5% above ₹10 crore |
| `surcharge.NON_COMPANY` | 10% above ₹50 lakh, 15% above ₹1 crore, 25% above ₹2 crore, 37% above ₹5 crore |
| `surchargeBasis` | PAYMENT_AMOUNT (INR amount of the payment, after gross-up) |
| `cessPct` | 4 |
| `treatyRateInclusive` | true (no surcharge or cess on a treaty rate) |
| `treatyRequires` | TRC, FORM_10F |
| `dtaa` (MOCK) | US 15/15/15, DE 10/10/10, JP 10/10/10, SG 10/10/15, GB 15/15/15, AE 10/–/12.5 (royalty / FTS / interest); OTHER 0 with a no-PE declaration |
| `noPan` | s.206AA, 20%, treaty not applied; relief for royalty, FTS, interest with TRC, tax ID and address |
| `form15` | 15CA always; 15CB above ₹5 lakh, counted over the fiscal year to the supplier |
| `fxRateDate` | PAYMENT_DATE |
| `roundInrToMinor` | 100 (nearest rupee) |

## 3. Form 16A information copy (PDF)

- PIC prints the Form 16A data of one deductee and one quarter as a PDF.
- Every page has a banner and a watermark: "Information copy — the statutory Form 16A must be downloaded from TRACES".
- The PDF shows: period, deductor (TAN, PAN, address from rule TDS `deductor`), deductee (PAN, residency), section, each payment with the amount, rate, tax and dates, the totals, the challans, and any mandatory data PIC does not hold.
- Screen: Invoices → Tax → Form 16A data → "16A PDF (information copy)".
- API: `GET /v1/finance/tds-certificates/pdf?fiscal_year=2027-28&quarter=Q3&supplier=RVES01`.
  - Finance only (`payment:run`).
  - Limited to the company codes of the user's scope (ABAC).
  - Every download is audited with its hash.
- No new library: the PDF is written by PIC itself (`services/form16a_pdf.py`, PDF 1.4 with the standard Helvetica fonts).

## 4. Mock data (pack D23 `tax_nonresident`, tenant AXN, October 2027)

All names and numbers are fictional.

| Vendor | Case |
|---|---|
| Rheinmark Werkzeugtechnik GmbH (DE) | TRC and 10F valid: treaty 10% instead of 20.8%. Invoice 1 paid with 15CA + 15CB. Invoice 2 blocked: no 15CA. |
| Cascade Ridge Software Inc (US) | Form 10F expired: Act rate 20.8% on a royalty. Refused in the 12 October run (409), released on 19 October after the 15CA. |
| Merlion Process Engineering Pte Ltd (SG) | No PAN, no tax ID: s.206AA. |
| Gulf Crest Technical Consultancy FZE (AE) | No FTS article in the MOCK treaty: Act rate, grossed up. |
| Kaveri Valley Engineering Services Pvt Ltd (resident, MSME) | Invoice paid in three parts, TDS with the first. Second invoice: a part returned by the bank, then paid. |

Challans are deposited on 6 November 2027, so Q3 2027-28 reconciles. The Form 16A copies of every deductee can be printed.

## 5. What the client's chartered accountant must confirm

1. The section numbers and labels under the Income-tax Act, 2025 that replace s.195, s.195A, s.206AA, s.197 and s.194J, and from which date.
2. The Act rates per payment nature and payee type, and whether any special rate (for example interest under a concessional section) applies.
3. The surcharge slabs and their basis. PIC uses the amount of the payment. The law uses the payee's total income.
4. The cess rate.
5. Every treaty rate and article in the DTAA table, the countries needed, and whether a treaty rate is inclusive of surcharge and cess.
6. Which documents the treaty needs (TRC, Form 10F, no-PE declaration, others such as a beneficial-ownership declaration).
7. The no-PAN rule: the 20% floor, whether surcharge and cess are added, whether the treaty can still apply, and the Rule 37BC relief conditions.
8. The Form 15CA / 15CB threshold, its basis (per payment or per fiscal year), and the remittances that need no 15CA.
9. The exchange rate to use. Rule 26 asks for the SBI telegraphic-transfer buying rate. PIC uses the tenant's FX table.
10. The rounding of the tax.
11. Gross-up: which contracts and suppliers carry it, and the accounting of the borne tax.
12. When TDS is deducted on a partially paid invoice. PIC deducts it in full with the first payment. The law asks for the earlier of credit and payment: if the ERP books the credit at posting, the deduction date may have to be the posting date.
13. The deductor's TAN, PAN and address in rule TDS (`deductor`). The mock data carries MOCK values.
14. Whether excess TDS after a later credit note must be refunded or adjusted. PIC does not adjust a deduction already made.
15. The GST rate and reverse-charge treatment of each imported service, and whether the input tax credit on the self-assessed IGST is available.
