# PIC ERP Extract Specification — SAP S/4HANA cutover extract

**AlphaHelion Procurement Intelligence Cloud (PIC) · Data migration & cutover (Technical Document §12.4, §12.1; requirements MIG-1..5, D10)**
Audience: the client's SAP basis / functional team and finance team. Version 1 · 2026-10-30.

This document tells your SAP team exactly which data to extract, in which layout, and what PIC does with it. The same layout
is produced by our mock generator (`backend/app/pic/tools/erp_mock.py`, fictional company *Kaveri Auto Components Pvt Ltd*,
files in `backend/data/erp_mock/KAC/`) and loaded by our loader (`backend/app/pic/tools/erp_load.py`). Your real files drop into
the same loader unchanged.

---

## 1. What we need and why

| # | Object (TD §12.4) | SAP source | PIC target | Validation at load |
|---|---|---|---|---|
| 1 | Organisation | T001, T001W (+ J_1BBRANCH GSTIN), CSKS/CSKT, PRPS | `company_code`, `plant`, `storage_location`, `cost_object`, taxonomy | GSTIN of each business place; plants belong to the company code |
| 2 | Suppliers | LFA1, ADRC/ADR6, LFB1, LFBK, T052 | `supplier`, `supplier_bank_account` (encrypted), `supplier_category_status` | GSTIN format/state/check character, PAN = GSTIN chars 3–12, IFSC format, terms key known; duplicate scan (GSTIN, PAN, name, bank account); bank verification sample |
| 3 | Materials | MARA, MAKT, MARC, MBEW, T023T (+ mapping) | `material` | HSN/SAC present and in the CBIC schedule, unit known, material group mapped, plant data present |
| 4 | Sourcing | EINA/EINE, EORD | `info_record`, `source_list` | vendor and material loaded, price > 0, validity |
| 5 | Open contracts | EKKO/EKPO (BSTYP K and L), A016/KONP | `contract`, `contract_line`, `price_validity`, `clause` | validity, conditions present, value and validity totals |
| 6 | Open POs | EKKO/EKPO (BSTYP F), EKKN, EKET, EKBE | `purchase_order` (ERP number in `erp_doc_no`), `po_line`, `po_schedule_line` | open value per supplier matches |
| 7 | Open AP | BSIK (+ RBKP/RSEG, BKPF/BSEG) | `invoice` (status POSTED, awaiting payment), `invoice_line` | AP total and ageing match the vendor reconciliation account |
| 8 | Spend history (24–36 months) | RBKP/RSEG, EKBE, BKPF/BSEG (KR), BSAK | `spend_line` (source ERP_HISTORY), classification, maverick hits | spend ties to GL ±0.5 % per company code and period |
| 9 | GL tie-out | ACDOCA period totals, account balances, reconciling items | tie-out report (stored with the load) | per period: extract vs loaded vs GL |

---

## 2. File format (applies to every file)

| Item | Rule |
|---|---|
| Format | CSV, **UTF-8** (BOM tolerated), comma delimiter, `"` quoting where needed, header row with the **SAP field names** given below, one file per table |
| File name | `<TABLE>.csv` exactly as in the tables below (e.g. `LFA1.csv`, `EINA_EINE.csv`) |
| Dates | ISO `YYYY-MM-DD`; "unlimited" as `9999-12-31` |
| Amounts | Document currency, decimal point `.`, no thousands separator, 2 decimals (e.g. `125000.50`); the currency key column next to it (`WAERS`, `RHCUR`, `KONWA`). Sign: positive amounts with the debit/credit indicator `SHKZG` (S = debit, H = credit); GL totals (`HSL`) are signed (debit +) |
| Quantities | Decimal point `.`, up to 3 decimals |
| Keys | Leading zeros allowed (`0000100023`): the loader applies SAP ALPHA conversion (numeric keys without leading zeros) |
| Units | Commercial/ISO units (`EA`, `KG`, `L`, `M`, `SET`, `AU`, `MON`); SAP internal codes `ST`, `PC`, `LE`, `PAA`, `TO`, `H`, `D` are mapped |
| Texts | English (`SPRAS = E`) |
| Scope | One company code per extract (more: one extract per company code, same key date) |
| History | Invoices posted in the 24 (preferably 36) full months up to the key date |
| Hand-over | `MANIFEST.json` in the same folder (§4) |

---

## 3. Files and columns

`M` = mandatory, `O` = optional (column must exist, value may be empty). Types: `C` char, `N` numeric string, `D` date, `A` amount, `Q` quantity.

### 3.1 Organisation

**T001.csv** — company code (T001; GSTIN/PAN from the registered-office business place J_1BBRANCH)

| Field | Description | Type | M/O | PIC |
|---|---|---|---|---|
| BUKRS | Company code | C4 | M | `company_code.code` |
| BUTXT | Company name | C25+ | M | `company_code.name`, tenant name |
| ORT01 | City | C | O | — |
| LAND1 | Country | C2 | M | must be IN |
| WAERS | Local currency | C3 | M | INR |
| PERIV | Fiscal year variant (V3 = April–March) | C2 | M | period conversion for the GL tie-out |
| KTOPL | Chart of accounts | C4 | O | — |
| PAN | Company PAN | C10 | O | — |
| GSTIN | GSTIN of the registered office | C15 | M | `company_code.gstin` (validated) |

**T001W.csv** — plants (T001W, T001K, J_1BBRANCH)

| Field | Description | Type | M/O | PIC |
|---|---|---|---|---|
| WERKS | Plant | C4 | M | `plant.code` |
| NAME1 | Name | C30 | M | `plant.name` |
| BUKRS | Company code (via T001K) | C4 | M | `plant.company_code` |
| STRAS / ORT01 / PSTLZ | Street / city / PIN | C | O | — |
| REGIO | Region key (T005S) | C3 | O | informational |
| LAND1 | Country | C2 | M | |
| J_1BBRANCH | Business place | C4 | O | |
| GSTIN | GSTIN of the business place | C15 | M | `plant.state_code` = first two digits |

**CSKS.csv** — cost centres (CSKS joined with CSKT, SPRAS = E, valid on the key date)

| Field | Description | Type | M/O | PIC |
|---|---|---|---|---|
| KOKRS | Controlling area | C4 | M | |
| KOSTL | Cost centre | C10 | M | `cost_object` (type COST_CENTER) `.code` |
| DATAB / DATBI | Valid from / to | D | M | only valid on the key date |
| BUKRS | Company code | C4 | M | |
| WERKS | Plant | C4 | O | plant of FI invoices (spend) |
| KOSAR | Category | C1 | O | |
| VERAK | Person responsible | C20 | O | |
| KTEXT / LTEXT | Short / long text (CSKT) | C | M | `cost_object.name` |

**PRPS.csv** — WBS elements (PRPS, PROJ)

| Field | Description | Type | M/O | PIC |
|---|---|---|---|---|
| POSID | WBS element (external key, not PS_PSP_PNR) | C24 | M | `cost_object` (type WBS) `.code` |
| POST1 | Description | C40 | M | `cost_object.name` |
| PSPHI | Project definition (PROJ-PSPID) | C24 | O | |
| PBUKR | Company code | C4 | M | |
| WERKS | Plant | C4 | O | |
| STUFE / BELKZ | Level / account assignment element | N / C1 | O | |

**T052.csv** — payment terms: `ZTERM` (M), `ZTAG1` days (M), `ZPRZ1` discount % (O), `TEXT1` (O) → PIC terms key `N30`, or `2/10 N30` with a discount.

**T007S.csv** — input tax codes: `MWSKZ` (M), `TEXT1`, `RATE` total GST % (M), `GST_TYPE` (CGST_SGST / IGST) → `po_line.gst_rate`, `invoice_line.gst_rate`.

**T023T.csv** (O) — material group texts: `MATKL`, `SPRAS`, `WGBEZ`.

### 3.2 Suppliers

**LFA1.csv** — vendor general data (all vendors with a posting in the history window or an open item; account groups of one-time vendors excluded)

| Field | Description | Type | M/O | PIC / rule |
|---|---|---|---|---|
| LIFNR | Vendor | C10 | M | `supplier.code` (ALPHA) |
| KTOKK | Account group | C4 | M | intercompany group (e.g. ZICO) → segment INTERCOMPANY, spend not addressable |
| NAME1, NAME2 | Name | C40 | M/O | `supplier.legal_name` |
| SORTL | Search term | C10 | O | |
| ADRNR | Address number → ADRC | C10 | M | |
| LAND1 | Country | C2 | M | |
| STCD3 | **GSTIN** | C15 | M | encrypted `gstin_enc`, masked, blind index; reject if missing/invalid |
| J_1IPANNO | PAN | C10 | M | must equal GSTIN chars 3–12 |
| SPERR / SPERM | Central posting / purchasing block | C1 | O | `supplier.status = BLOCKED` |
| LOEVM | Deletion flag | C1 | O | BLOCKED, categories EXITED, bank not loaded (history only) |
| ERDAT | Created on | D | M | `qualified_on`, bank `verified_on` |

**ADRC.csv** — address (ADRC + ADR6 e-mail)

| Field | Description | Type | M/O | PIC |
|---|---|---|---|---|
| ADDRNUMBER | Address number | C10 | M | join to LFA1-ADRNR |
| NAME1 | Name | C40 | O | |
| STREET, STR_SUPPL1 | Street, supplement | C60 | M/O | `supplier.address.line1/line2` |
| CITY1 | City | C40 | M | `address.city` |
| POST_CODE1 | PIN | C10 | M | `address.pin` |
| REGION | Region key | C3 | O | informational — the state comes from the GSTIN |
| COUNTRY | Country | C2 | M | |
| SMTP_ADDR | E-mail (ADR6) | C241 | O | `supplier.contact_email` |
| TEL_NUMBER | Telephone | C30 | O | not loaded |

**LFB1.csv** — vendor company-code data: `LIFNR` (M), `BUKRS` (M), `AKONT` reconciliation account (M), `ZTERM` (M → T052), `ZWELS` payment methods (O), `REPRF` duplicate-invoice check (O), `SPERR` (O), `LOEVM` (O), `ERDAT` (O). A vendor without LFB1 for the company code is rejected (NO_COMPANY_CODE_DATA).

**LFBK.csv** — bank details (first row per vendor is loaded)

| Field | Description | Type | M/O | PIC / rule |
|---|---|---|---|---|
| LIFNR | Vendor | C10 | M | |
| BANKS | Bank country | C3 | M | IN |
| BANKL | Bank key = **IFSC** | C11 | M | 4 letters + `0` + 6 alphanumerics; invalid → bank row rejected, vendor loaded without bank |
| BANKN | Account number | C18 | M | 6–18 digits; stored **encrypted** (`account_enc`, platform field key), masked |
| KOINH | Account holder | C60 | M | `holder_name` |
| BVTYP | Partner bank type | C4 | O | |

### 3.3 Materials

**MARA.csv**: `MATNR` (M → `material.number`), `MTART` (M: ROH/HALB/VERP/ERSA/HIBE/FHMI → STOCK, NLAG/UNBW → NON_STOCK, DIEN → SERVICE), `MATKL` (M → category via PIC_MAP_MATKL), `MEINS` (M → base unit), `MFRPN` (O → mpn), `BRGEW`/`GEWEI` (O), `LVORM` (O: flagged materials are skipped), `ERSDA` (O).

**MAKT.csv**: `MATNR`, `SPRAS` (E), `MAKTX` (M → `material.description`).

**MARC.csv** — plant data (one row per material and plant; PIC holds one MRP view per material: the lowest plant number is used)

| Field | Description | PIC |
|---|---|---|
| MATNR, WERKS | Material, plant | plants list |
| DISMM | MRP type | PD → PD; ND/VB/V1 → ND (reorder-point planning is not run by PIC MRP; warning MRP_TYPE_MAPPED) |
| DISPO | MRP controller | — |
| BESKZ | Procurement type | — |
| PLIFZ / WEBAZ | Planned delivery / GR processing days | `planned_delivery_days` / `gr_processing_days` |
| EISBE | Safety stock | `safety_stock` |
| DISLS, BSTFE, BSTMI, BSTMA | Lot-size procedure, fixed / min / max lot | `lot_size_policy` (FX → FIXED, else EXACT), `lot_size_qty`, `min_lot`, `max_lot` |
| **STEUC** | **HSN/SAC (control code)** | `hsn_code`; GST rate from the CBIC schedule (`data/reference/hsn_gst_rates.csv`) |
| QMATV | Inspection setup active | `quality_managed` |
| LVORM | Deletion flag at plant level | plant row ignored |

**MBEW.csv**: `MATNR`, `BWKEY` (= plant), `BKLAS` valuation class, `VPRSV` (S/V), `STPRS` standard price, `VERPR` moving average price, `PEINH` price unit → `valuation_class`, `standard_price_minor` (price per base unit, paise).

**PIC_MAP_MATKL.csv** (mapping workshop deliverable, not SAP): `MATKL` (M), `PIC_CATEGORY` (M: a PIC taxonomy category or UNCLASSIFIED for "miscellaneous" groups, which then go through the Spend Classification Agent), `NOTE`.
**PIC_MAP_TAXONOMY.csv** (O): categories to add to the PIC taxonomy — `CATEGORY`, `PARENT`, `LEVEL`, `NAME`, `KEYWORDS` (`;`-separated, used by the classifier), `ADDRESSABLE` (X).

### 3.4 Sourcing

**EINA_EINE.csv** — purchasing info records (EINA joined with EINE, standard category `ESOKZ = 0`): `INFNR`, `LIFNR`, `MATNR`, `EKORG`, `WERKS` (M), `ESOKZ`, `NETPR` (M, per `PEINH`), `PEINH`, `WAERS`, `APLFZ` planned delivery days (M), `MINBM`, `LOEKZ`, `DATLB` → `info_record` (supplier, material, plant, last price, lead time).

**EORD.csv** — source list: `MATNR`, `WERKS`, `ZEORD`, `VDATU`, `BDATU`, `LIFNR`, `FLIFN` fixed vendor, `EBELN`/`EBELP` agreement, `AUTET` → `source_list` (only records valid on/after the key date).

### 3.5 Purchasing documents (one EKKO and one EKPO file for contracts, scheduling agreements and POs)

Selection: all outline agreements (BSTYP K, L) valid in the history window or on the key date; all POs (BSTYP F) with a goods
receipt or invoice in the window **plus every PO with an open quantity or open invoice quantity on the key date**.

**EKKO.csv**

| Field | Description | Type | M/O | PIC |
|---|---|---|---|---|
| EBELN | Purchasing document | C10 | M | PO: `erp_doc_no`; agreement: `contract.number` |
| BUKRS | Company code | C4 | M | |
| BSTYP | Category: F PO, K contract, L scheduling agreement | C1 | M | |
| BSART | Type: NB, MK quantity contract, WK value contract, LP | C4 | M | `contract.type` (L → SCHEDULING_AGREEMENT, MK → QUANTITY_CONTRACT, WK → VALUE_CONTRACT) |
| LIFNR | Vendor | C10 | M | `supplier_id` |
| EKORG / EKGRP | Purchasing org / group | C4 / C3 | M / O | `purch_org`, `inherited.purchasingGroup` |
| BEDAT | Document (order) date | D | M | maverick PO_AFTER_INVOICE when after the invoice date |
| KDATB / KDATE | Validity start / end (agreements) | D | M for K/L | `valid_from` / `valid_to`; active = valid on the key date |
| KTWRT | Target value (value contracts) | A | O | `target_value_minor` |
| ZTERM | Payment terms | C4 | M | `payment_terms` |
| INCO1 / INCO2 | Incoterms | C3 / C28 | O | `incoterms` |
| WAERS | Currency | C5 | M | |
| ERNAM | Created by | C12 | O | |
| LOEKZ | Deletion indicator | C1 | O | deleted documents ignored |

**EKPO.csv**

| Field | Description | Type | M/O | PIC |
|---|---|---|---|---|
| EBELN, EBELP | Document, item | C10, N5 | M | `po_line.line_no` / `contract_line.line_no` = EBELP |
| LOEKZ | Deletion indicator | C1 | O | ignored when set |
| MATNR | Material (empty = free text) | C40 | O | `material_id`; unknown material → reject |
| TXZ01 | Short text | C40 | M | description |
| MATKL | Material group | C9 | M | `material_group`, spend category |
| WERKS / LGORT | Plant / storage location | C4 | M / O | |
| MENGE | PO quantity (BSTYP F) | Q | M | `po_line.qty` (> 0) |
| KTMNG | Target quantity (agreements) | Q | M for K/L | `contract_line.target_qty` |
| MEINS | Order unit | C3 | M | `uom` |
| NETPR / PEINH | Net price / price unit | A / N | M | `unit_price_minor` = NETPR ÷ PEINH in paise (> 0) |
| NETWR | Net order value | A | M | `net_minor`, open PO value |
| KNTTP | Account assignment: blank, K cost centre, P project, A asset | C1 | O | purchase type, `account_assignment_*` |
| PSTYP | Item category | C1 | O | |
| MWSKZ | Tax code → T007S | C2 | M | `gst_rate` |
| J_1BNBM | HSN/SAC on the item | C16 | O | `hsn_code` |
| WEPOS / REPOS / WEBRE | GR / IR / GR-based IV | C1 | M | `gr_required`, `ir_required` |
| ELIKZ / EREKZ | Delivery completed / final invoice | C1 | M | open line = not (ELIKZ and EREKZ) |
| KONNR / KTPNR | Outline agreement / item | C10 / N5 | O | `contract_line_id`, spend `contracted` |
| UEBTO / UNTTO | Over- / under-delivery tolerance % | Q | O | PO and contract tolerances |

**A016_KONP.csv** — contract / scheduling agreement price conditions (A016 joined with KONP, condition type PB00/PBXX, one row per validity period)

| Field | Description | Type | M/O | PIC |
|---|---|---|---|---|
| EVRTN / EVRTP | Agreement / item | C10 / N5 | M | |
| KSCHL | Condition type | C4 | M | |
| DATAB / DATBI | Valid from / to | D | M | `price_validity.valid_from / valid_to` |
| KBETR / KPEIN / KMEIN / KONWA | Rate / per / unit / currency | A / N / C / C | M | `price_validity.unit_price_minor` (published) |
| KNUMH | Condition record | C10 | O | |

**EKKN.csv** — account assignment: `EBELN`, `EBELP`, `ZEKKN`, `SAKTO` G/L account, `KOSTL`, `POSID` (WBS external key, converted from PS_PSP_PNR) → `account_assignment_type/code`, spend `cost_object`.

**EKET.csv** — schedule lines of **open** items: `EBELN`, `EBELP`, `ETENR`, `EINDT` delivery date, `MENGE`, `WEMNG` delivered → `po_schedule_line`, `po_line.need_date`.

**EKBE.csv** — PO history (all items in EKPO)

| Field | Description | Type | M/O | PIC |
|---|---|---|---|---|
| EBELN, EBELP | Document, item | C10, N5 | M | |
| VGABE | Transaction: 1 goods receipt, 2 invoice | C1 | M | |
| GJAHR, BELNR, BUZEI | Material / invoice document | N4, C10, N4 | M | |
| BWART | Movement type (101, 102, 122) | C3 | O | |
| BUDAT | Posting date | D | M | |
| MENGE | Quantity | Q | M | `received_qty`, `accepted_qty`, `invoiced_qty` (net of H) |
| DMBTR / WAERS | Amount in local currency / currency | A / C | M | `invoiced_minor`, contract consumption |
| SHKZG | Debit/credit | C1 | M | H reverses |

### 3.6 Invoices, open and cleared items

**RBKP.csv** — logistics invoice headers (RBSTAT 5 = posted; reversed documents with STBLG)

| Field | Description | Type | M/O | PIC |
|---|---|---|---|---|
| BELNR, GJAHR | Invoice document, fiscal year | C10, N4 | M | `invoice.erp_doc_no`, spend key |
| BUKRS | Company code | C4 | M | |
| BLART | Document type (RE) | C2 | M | |
| BLDAT | Invoice (document) date | D | M | `invoice_date`, fiscal year of the duplicate key |
| BUDAT | Posting date | D | M | spend **period** |
| XBLNR | Supplier invoice number | C16 | M | `supplier_invoice_no` |
| LIFNR | Invoicing party | C10 | M | |
| WAERS | Currency | C5 | M | |
| RMWWR / WMWST1 | Gross amount / tax | A | M | `gross_minor`, `tax_minor` |
| ZTERM / ZFBDT | Terms / baseline date | C4 / D | M | |
| XRECH | Invoice (X) or credit memo (blank) | C1 | M | |
| STBLG | Reversal document | C10 | O | |
| RBSTAT | Status | C1 | M | |

**RSEG.csv** — invoice items: `BELNR`, `GJAHR`, `BUZEI` (N6), `EBELN`, `EBELP` (M), `MATNR` (O), `WERKS` (M), `MENGE` (M, ≥ 0), `BSTME`, `WRBTR` net (M), `SHKZG` (M: H = credit memo item → negative spend), `MWSKZ` (M) → one `spend_line` per item; open-AP invoice lines.

**BSEG_KR.csv** — FI vendor invoices without PO (BKPF + BSEG expense lines of document type KR): `BUKRS`, `BELNR`, `GJAHR`, `BUZEI`, `BLART`, `BLDAT`, `BUDAT`, `XBLNR`, `LIFNR`, `HKONT` G/L account, `KOSTL`, `WRBTR` net, `MWSKZ`, `WMWST` tax, `SGTXT` item text (M — it is what the classifier reads), `WAERS` → `spend_line` (category UNCLASSIFIED → Spend Classification Agent).

**BSIK.csv** — open vendor items on the key date (all, incl. blocked)

| Field | Description | Type | M/O | PIC |
|---|---|---|---|---|
| BUKRS, LIFNR, GJAHR, BELNR, BUZEI | Key | | M | `invoice.erp_doc_no` |
| BLART | Document type (RE, KR) | C2 | M | RE → lines from RSEG, KR → lines from BSEG_KR |
| BLDAT / BUDAT | Document / posting date | D | M | `invoice_date` / `posted_at` |
| XBLNR | Supplier invoice number | C16 | M | duplicate key (supplier, XBLNR, fiscal year) |
| WAERS, WRBTR, DMBTR | Currency, amount (doc / local) | A | M | must equal the document gross |
| SHKZG | H = liability | C1 | M | open debit items (S) are rejected |
| ZFBDT, ZTERM, ZBD1T | Baseline date, terms, net days | D, C4, N | M | `due_date` = ZFBDT + ZBD1T |
| ZLSPR | Payment block | C1 | O | `payment_block` |
| EBELN | Purchase order | C10 | O | `po_id` when the PO is loaded open |
| QBSHB | Withholding tax amount | A | M | ≠ 0 → rejected (see §7) |

**BSAK.csv** — cleared vendor items in the window: BSIK columns + `AUGDT` clearing date, `AUGBL` clearing document (used for payment behaviour and completeness, not loaded as documents).

### 3.7 General ledger (for the tie-out)

**ACDOCA_PERIOD_TOTALS.csv** — per company code, fiscal period and G/L account: **the debit total of all vendor-invoice postings (BLART RE, KR, KG) to the offsetting expense / GR-IR / CWIP accounts, excluding tax and vendor reconciliation accounts**. This is the GL view of "spend" the loaded history must tie to.

| Field | Description | Type | M/O |
|---|---|---|---|
| RBUKRS | Company code | C4 | M |
| GJAHR, POPER | Fiscal year, period (V3: 001 = April) | N4, N3 | M |
| RACCT, TXT50 | Account, text | C10, C50 | M / O |
| HSL, RHCUR | Amount (signed, debit +), currency | A, C5 | M |

**GL_BALANCES.csv** — balances on the key date of the vendor reconciliation account(s) (LFB1-AKONT, e.g. 160000): `RBUKRS`, `RACCT`, `TXT50`, `KEYDATE`, `HSL` (credit balance negative), `RHCUR`.

**GL_RECON_ITEMS.csv** (O, prepared by finance) — known reconciling items between GL and the extract (accruals, GR/IR maintenance, manual JVs): `RBUKRS`, `GJAHR`, `POPER`, `RACCT`, `HSL`, `RHCUR`, `REASON`, `BELNR`, `DESCRIPTION`.

---

## 4. Hand-over: MANIFEST.json

```json
{"client": "…", "sourceSystem": "SAP_S4", "system": "<SID>", "release": "S/4HANA 2023", "extractId": "<CLIENT>-<SID>-<YYYYMMDD>-INIT",
 "extractType": "INITIAL | DELTA", "companyCodes": ["1000"], "keyDate": "2026-10-31", "historyFrom": "2024-11-01", "historyTo": "2026-10-31",
 "extractedAt": "2026-11-01T02:00:00+05:30", "encoding": "UTF-8", "currency": "INR",
 "files": {"LFA1.csv": {"rows": 247, "sha256": "…", "controlTotal": {"column": "…", "sum": "…"}}, "…": {}}}
```

Every listed file must exist with exactly that row count and SHA-256; otherwise **nothing is loaded** (ExtractError). Control totals
(sum of the main amount column) are for your own reconciliation of the extraction run.

---

## 5. Load order and behaviour

`python -m app.pic.tools.erp_load --tenant <CODE> --dir <folder> [--validate-only] [--report] [--report-dir <dir>]`

1. **org** — tenant bootstrapped from T001/T001W/CSKS/PRPS if it has no configuration yet; otherwise missing plants/cost objects added; taxonomy extension.
2. **vendors** — supplier masters (status ACTIVE / BLOCKED), GSTIN and bank account **encrypted with the platform field key**, qualified categories from info records, agreements or ≥ 3 history invoice lines; then the F8-03 duplicate and sanctions screening (`services.supplier.screen`: same GSTIN, same PAN, similar name, sanctions list) plus a shared-bank-account check → `screening.outcome = REVIEW` for the MDM duplicate queue.
3. **materials**, info records, source lists.
4. **agreements** — active on the key date → ACTIVE contracts with price validities (published), template clauses (CLM playbook), consumption so far (GRs of scheduling agreements, release-order quantities of contracts), renewal and expiry timers; expired ones are used only to flag the history as contracted.
5. **open POs** — status CONFIRMED / PARTIALLY_RECEIVED / RECEIVED, `erp_doc_no` = EBELN, received and invoiced quantities from EKBE, process F5 waiting at F5-09 (delivery). New receipts and invoices then run through the normal PIC services.
6. **open AP** — invoices in status POSTED with the SAP document number, due date and payment block; process F7 waiting at F7-07 (payment run). On the SAP sandbox simulator the documents are also registered so the nightly reconciliation (TD §12.2) agrees.
7. **spend history** — spend lines (source ERP_HISTORY) with category (material master or material-group mapping), plant, cost object, contracted flag, maverick flags PO_AFTER_INVOICE and OFF_CONTRACT derived from the documents, purchase price variance against the standard price; then the Spend Classification Agent and the maverick rules (`services.spend.refresh`).
8. **tie-out** — §6.

Behaviour: every row is validated; a failing row goes to the **reject report** (`rejects.csv`: object, file, row, key, reason, detail, amount) and the load continues. Everything is **idempotent**: a second run of the same extract writes nothing. Each object type is audited (`MIGRATION` object, action **INITIAL_LOAD** on the first load, **ERP_DELTA** on later extracts, actor **integration:SAP_S4**); every vendor, contract, PO and invoice also gets its own `MIGRATED` audit event. All writes run in tenant transactions (row-level security).

**Delta extracts** (same layout, `extractType: DELTA`): new rows are added; descriptive vendor fields (name, address, e-mail, terms, block flag) and material fields (text, HSN, GST rate, standard price) are updated and audited as ERP_DELTA. **A changed GSTIN or bank account is never applied from the ERP**: it is rejected as SENSITIVE_CHANGE and must go through the PIC MDM-04 change process (call-back, dual approval, cooling-off).

---

## 6. Tie-out (TD §12.4 validations)

| Check | Rule | Report |
|---|---|---|
| Spend vs GL | per company code and period: GL − loaded within **±0.5 %** → BALANCED; otherwise EXPLAINED if the difference equals the documented reconciling items plus the rejected genuine postings, else UNEXPLAINED | `tieout_spend.csv`, summary `tieOut.spend` |
| Open AP | extract total = GL vendor reconciliation balance; loaded + rejected = GL; ageing (not due, 1–30, 31–60, 61–90, > 90 days overdue) extract vs loaded | `tieOut.openAp` |
| Open POs | open value (net value − invoiced) per supplier, extract vs loaded; differences must equal the rejected lines | `tieOut.openPo` |
| Contracts | number active, validity buckets (≤ 3, 4–6, > 6 months), target value | `tieOut.contracts` |
| Masters | counts loaded / existing / rejected / skipped per object; duplicate candidates; **bank verification sample** (10 %, at least 10 accounts) for call-back | summary `objects`, `duplicates`, `bankVerificationSample` |

Reject reasons: GSTIN_MISSING, GSTIN_INVALID, GSTIN_PAN_MISMATCH, NO_COMPANY_CODE_DATA, PAYMENT_TERMS_UNKNOWN, BANK_IFSC_INVALID, BANK_ACCOUNT_INVALID, SENSITIVE_CHANGE, DUPLICATE_KEY, NO_DESCRIPTION, NO_PLANT_DATA, MATERIAL_GROUP_UNMAPPED, UOM_UNKNOWN, HSN_MISSING, HSN_UNKNOWN, VENDOR_NOT_LOADED, MATERIAL_NOT_LOADED, MATERIAL_UNKNOWN, PLANT_UNKNOWN, PRICE_INVALID, QTY_INVALID, QTY_NEGATIVE, VALIDITY_INVALID, CONDITION_MISSING, AGREEMENT_TYPE_UNKNOWN, VENDOR_BLOCKED, PO_UNKNOWN, INVOICE_HEADER_MISSING, DATE_INVALID, DUPLICATE_INVOICE, DEBIT_ITEM, REFERENCE_MISSING, WITHHOLDING_NOT_SUPPORTED, DOCUMENT_NOT_FOUND, PARTIAL_OR_WITHHELD.
Warnings (loaded, flagged): GST_RATE_AMBIGUOUS (e.g. GTA 5 %/18 %: highest used, confirm with tax), MRP_TYPE_MAPPED, PRICE_UNIT_ROUNDED, AGREEMENT_NOT_LOADED, SPEND_MATERIAL_NOT_LOADED.

---

## 7. Known limits (decisions / schema needs)

- **Withholding tax (TDS)**: PIC invoices have no withholding amount; open items with `QBSHB ≠ 0` are rejected so they are never over-paid. Needs `invoice.withholding_minor`.
- **MRP view per plant**: PIC stores one MRP view per material (lowest plant used). Needs a material-plant table.
- **Contract consumption baseline**: migrated consumption is stored on the contract line, but PIC recomputes consumption from platform POs when the next release order is created, so the history part is then dropped. Needs `contract_line.migrated_released_qty/value`.
- **Contracts have no ERP reference column**: the SAP agreement number is used as the PIC contract number. Needs `contract.erp_doc_no`.
- **Clause extraction** from the signed contract PDFs (AI extraction with review) needs the documents; until then clauses come from the PIC template.
- **One-time vendors (CPD)** and **open debit items / down payments** are out of scope of the automatic load (settle in SAP before cutover).

---

## 8. Cutover checklist (TD §12.4)

| Step | When | Who | Action | Evidence |
|---|---|---|---|---|
| 1. Mapping workshop | T − 4 weeks | Client SAP + PIC | material groups → PIC categories (`PIC_MAP_MATKL`), taxonomy extension, tax codes, payment terms, users and roles | signed mapping files |
| 2. Trial extract | T − 3 weeks | Client SAP | full extract into a test tenant; `--validate-only` | reject report, tie-out |
| 3. Data cleansing | T − 3 … T − 1 weeks | Client MDM / AP | fix rejected rows in SAP (GSTIN, HSN, units, duplicates, withholding, debit items); finance prepares GL_RECON_ITEMS | reject count trending to zero |
| 4. Freeze | T − 1 day | Client | purchasing freeze (no new POs/agreements in SAP), MIRO stop after the last posting run, period close of the key-date month | freeze notice |
| 5. Extract | T, night | Client SAP | final extract with key date = freeze date, MANIFEST.json with row counts and SHA-256 | MANIFEST, control totals |
| 6. Load | T + 0 | PIC | `erp_load --tenant <CODE> --dir <folder> --report` | load report, audit INITIAL_LOAD |
| 7. Tie-out | T + 0 | PIC + client finance | spend ±0.5 % per period, AP vs reconciliation account, open PO value per supplier, contracts; bank call-back on the sample | `tieout_spend.csv`, `summary.json` |
| 8. Sign-off | T + 1 | Client CFO / CPO | accept the tie-out and the UNEXPLAINED items (or re-extract) | signed tie-out |
| 9. Go-live | T + 1 | All | new requisitions, POs, receipts and invoices in PIC; SAP postings via the connector (exactly-once) | first postings |
| 10. Delta | T + 1 … T + n | Client SAP | delta extracts (new vendors/materials, master changes) with `extractType: DELTA` until the master-data interface is live | audit ERP_DELTA |

---

## 9. The mock extract (demo)

`backend/data/erp_mock/KAC/` — Kaveri Auto Components Pvt Ltd (fictional): company code 1000, plants 1100 Hosur and 1200 Oragadam
(Tamil Nadu, GST state 33) and 1300 Bidadi (Karnataka, 29); 24 months of history (Nov 2024 – Oct 2026), key date 31.10.2026.
Regenerate with `python -m app.pic.tools.erp_mock` (fixed seed: identical files). The deliberate data-quality cases (duplicates,
invalid GSTINs, missing HSN, negative quantities, a duplicate invoice, three GL variances — two documented, one not) are listed in
the generator's module docstring and asserted by `backend/tests/pic/test_datasets_erp_client_kac.py`. The dataset pack
`erp_client_kac` (key `erp-client-kac`) creates tenant KAC and runs the loader.
