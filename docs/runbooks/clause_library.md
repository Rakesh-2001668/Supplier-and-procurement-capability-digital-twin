# Contracts: clause library, e-signature and contract data (mocks and how to replace them)

**ILLUSTRATIVE SAMPLE, NOT LEGAL ADVICE, REPLACE WITH LEGAL-APPROVED TEXT.** The product owner has no legal clause library, no e-signature
provider account and no real contracts for the first tenant yet. Module M07 (Contracts) therefore ships three clearly labelled stand-ins. They run the
real code paths, so each one is replaced by loading real input, with no code change.

| Stand-in | What it is | Replace with | How |
|---|---|---|---|
| Clause library | `backend/app/pic/seed/clause_library.py`: 37 clauses, 8 category overlays (26 more clauses), 7 governing-law variants, 85 pre-approved fallbacks | the client's legal-approved library (CSV or JSON, format below) | `python -m app.pic.tools.clause_library_load --tenant CODE --file clauses.csv` |
| E-signature | `PIC_ESIGN_PROVIDER=MOCK` with `python -m app.pic.tools.esign_mock --port 8765` | DocuSign, Adobe Sign, Leegality or eMudhra | set the four `PIC_ESIGN_*` variables (section 3) |
| Contracts of tenant KAC | `backend/data/erp_mock/KAC_CLM` (60 fictional contracts), dataset pack `contracts_kac` | the client's contract register export in the same layout | `python -m app.pic.tools.contract_load --tenant CODE --dir <folder>` (layout: PIC_ERP_Extract_Spec.md section 10) |

## 1. Clause library

### What it holds

* **Clauses per contract type** (`MASTER_AGREEMENT`, `QUANTITY_CONTRACT`, `VALUE_CONTRACT`, `SCHEDULING_AGREEMENT`, `RATE_CARD`, `SOW`, `NDA`): payment terms with the
  MSME 45-day rule (MSMED Act 2006 s.15, interest s.16), price and taxes, price variation and indexation, rebate, delivery and tolerance, liquidated damages, quality and
  certificate of conformity, PPAP, warranty, service levels, liability cap, indemnity, IP, confidentiality, termination for convenience and for cause, force majeure,
  subcontracting, insurance, assignment, audit rights, personal data (DPDP Act 2023), anti-bribery and sanctions, ESG and code of conduct, GST and tax compliance,
  dispute resolution and arbitration; NDA-specific clauses (definition, use, term, permitted disclosure, return, no licence, remedies).
  Each clause has standard wording, one or two pre-approved **fallback positions**, a **risk weight** (1 low to 10 high) and an **escalation role**.
* **Category overlays** (added to a draft whose `category` is one of the listed codes): castings and forgings, electronics, IT services and software licences, logistics
  freight, construction works, healthcare supplies, professional services, MRO.
* **Governing-law variants** (the `jurisdiction` of a draft): India (`IN-TN` Tamil Nadu, `IN-MH` Maharashtra, `IN-KA` Karnataka, `IN-GJ` Gujarat; the service also
  knows `IN`, `IN-DL`, `IN-WB`, `IN-TG`, `IN-HR`) and foreign suppliers (`GB` England and Wales, `SG` Singapore, `US-DE` Delaware USA).

### How a tenant gets it

The library is part of the `CLM-PLAYBOOK` rule set (keys `clauseLibrary`, `categoryClauses`, `jurisdictions`, `fallbacks`). New tenants get it in the bootstrap. A tenant
bootstrapped earlier gets it from `reference.ensure_extensions` as a new effective-dated rule version (`2026.3`): an existing version is never edited, and the tenant's
own `categoryClauses`, `jurisdictions` and `fallbacks` entries win. The built-in templates stay; where a library clause has the same code as a template clause the
library wins (`clauseLibrary.precedence` = `LIBRARY`; set `TEMPLATE` to reverse it). A draft takes: template, library clauses of its type, category overlay, governing-law variant.
The clause review (CLM-02, `GET /v1/contracts/{ref}/clause-review`) shows for each clause its `riskWeight`, `escalationRole` and `fallbackPositions`.

### File format (CSV or JSON)

Write the sample out as a template: `python -m app.pic.tools.clause_library_load --export-sample clauses.csv` (or `.json`). A checked-in copy is
`backend/data/clause_library/illustrative_clause_library.csv`.

CSV, UTF-8, one row per clause, overlay clause or jurisdiction. Columns:

| Column | Used by | Meaning |
|---|---|---|
| `kind` | all | `CLAUSE`, `OVERLAY` or `JURISDICTION` |
| `code` | all | clause code (A-Z, 0-9, `_`, 2 to 30 characters) or jurisdiction code (`IN-TN`, `GB`) |
| `category` | OVERLAY | the category codes the overlay applies to, separated by `\|` (rows with the same list form one overlay) |
| `title`, `group` | CLAUSE, OVERLAY | clause heading; free grouping label |
| `types` | CLAUSE, OVERLAY | contract types the clause applies to, separated by `\|` |
| `text` | CLAUSE, OVERLAY | standard wording; placeholders `{terms}` `{incoterms}` `{supplier}` `{band}` `{over}` `{under}` only, no other braces |
| `risk_weight` | CLAUSE, OVERLAY | whole number 1 to 10 |
| `escalation_role` | CLAUSE, OVERLAY | `LEGAL`, `FINANCE_CONTROLLER`, `CPO`, `PROCUREMENT_HEAD`, `CATEGORY_MANAGER`, `CONTRACT_MANAGER`, `SUPPLIER_MANAGER` or `DEPT_HEAD` |
| `fallback_1`, `fallback_2` | CLAUSE, OVERLAY | pre-approved fallback, written `label :: wording`; at most two |
| `variants` | CLAUSE, OVERLAY | optional JSON object `{"RATE_CARD": "wording for that type"}` |
| `name`, `law`, `seat`, `forum`, `stamp`, `data`, `note` | JURISDICTION | fill the jurisdiction clauses: governing law, seat of arbitration, courts, stamp duty, data protection law; `note` is for the contract manager |

JSON: `{"version", "source", "clauses": [...], "overlays": [{"name", "categories": [...], "clauses": [...]}], "jurisdictions": {"IN-TN": {...}}}`, each clause
`{"code","title","group","types":[...],"text","riskWeight","escalationRole","fallbacks":[{"label","text"}],"variants":{...}}`.

### Loading the client's file

1. `python -m app.pic.tools.clause_library_load --file clauses.csv --validate-only` lists every problem (codes, types, weights, roles, placeholders, fallbacks).
2. `python -m app.pic.tools.clause_library_load --tenant CODE --file clauses.csv` adds a new `CLM-PLAYBOOK` version (`LIB-<date>`, effective today, audited). The file replaces the
   library, overlays, jurisdictions and fallbacks per key; templates, obligations, position risk and award defaults stay.
3. New drafts use it at once. Contracts already drafted keep their wording (their `standard_text` is the wording they were drafted from).
4. To remove the "illustrative" label the file's `source` is `FILE`; set your own `version` and an empty `disclaimer` in a JSON file.

Not verified: the wording is engineering's, not a lawyer's. Legal must review every clause, every statute reference and every fallback before use.

## 2. If-Match decision

`PIC_REQUIRE_IF_MATCH` is **on in production and off by default only in dev and test**. Verified: `app/pic/config.py` `Settings.if_match_required` returns the variable when set, else
`is_production`; `platform/preconditions.py` then answers 428 `PRECONDITION_REQUIRED` for the document overwrites in `REQUIRED` (including the contract commands submit, activate,
terminate, index-resets and amendments). The web app sends `If-Match` by itself: `frontend/src/lib/pic/api.ts` remembers the ETag of every document GET (`/collection/ref`) and sends it
as `If-Match` on the next write to that document, and the proxy `frontend/src/app/api/pic/[...path]/route.ts` forwards `if-match` and `etag`. A script that calls the API directly must send
the ETag of its last GET. To switch it off in production (not recommended) set `PIC_REQUIRE_IF_MATCH=false`.

## 3. E-signature

| Mode | Variables | Notes |
|---|---|---|
| none | unset | contracts are signed inside PIC (internal signature bound to the document hash) |
| real provider | `PIC_ESIGN_PROVIDER` (`DOCUSIGN`, `ADOBE_SIGN`, `LEEGALITY`, `EMUDHRA`), `PIC_ESIGN_URL`, `PIC_ESIGN_API_KEY`, `PIC_ESIGN_WEBHOOK_SECRET` | the provider's webhook calls `POST /v1/esign/webhook` with `X-Esign-Signature` (HMAC-SHA256 of the raw body); needs the provider account and Legal's sign-off |
| demo | `PIC_ESIGN_PROVIDER=MOCK`, `PIC_ESIGN_URL=http://127.0.0.1:8765`, `PIC_ESIGN_API_KEY`, `PIC_ESIGN_WEBHOOK_SECRET` (any values, the same on both sides) | not in production |

Demo run: start PIC, then `python -m app.pic.tools.esign_mock --port 8765 --webhook-url http://127.0.0.1:8000/v1/esign/webhook --secret <same secret> --api-key <same key> [--delay 5]`.
"Send via e-sign provider" on the contract creates the envelope at the mock; `POST http://127.0.0.1:8765/envelopes/<id>/complete` (or `--delay`) signs for both parties and sends the signed
webhooks; the contract can then be activated.

Rules enforced: `MOCK` is accepted only when `PIC_ENV` is not production (`contract.esign_providers()`); with `PIC_ENV=production` the adapter answers 409 `ESIGN_MOCK_FORBIDDEN`, the
start-up check (`Settings.production_problems`) names `PIC_ESIGN_PROVIDER=MOCK`, and the mock server refuses to start. A MOCK signature is recorded with the envelope id `MOCK-...`, shown as
provider `MOCK` and **"Demo signature - not legally binding"** in the API (`signatures[].provider`, `.demoSignature`, `.label`; `demoSignature` on the contract), on the Signatures tab of the contract
screen, and in the audit trail (`SIGNED` with `provider` and `demoSignature`). Signatures loaded from a contract register show as `MIGRATED`.

## 4. Contract portfolio of the mock client KAC

`python -m app.pic.tools.erp_mock_contracts` writes `backend/data/erp_mock/KAC_CLM` (fixed seed, identical files); the dataset pack `contracts_kac` (after `erp_client_kac`) loads it with
`app.pic.tools.contract_load`. 60 contracts: 14 master agreements with 20 call-offs (6 scheduling, 8 quantity, 6 value), 8 rate cards, 8 statements of work, 10 NDAs; 43 active, 9 expiring
(18 to 117 days), 3 expired, 1 terminated, 2 in negotiation (one with three supplier redlines), 1 out for signature, 1 draft. See the header of `erp_mock_contracts.py`. Vendors, materials,
plants, payment terms and prices come from the SAP mock extract. With a real register: export it in the layout of PIC_ERP_Extract_Spec.md section 10 and run `contract_load`.
