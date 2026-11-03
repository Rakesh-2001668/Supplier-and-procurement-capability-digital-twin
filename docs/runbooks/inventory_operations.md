# Inventory operations (M09 stock)

How stock changes, who may change it, and how to configure it. Spec: Blueprint M09 (receiving), section 22/23 (special stocks), MRP-02
(stock/requirements list); Technical Document 5.2, 6, 9.1. Amounts are minor units (paise).

## 1. The ledger

* `stock` holds the balance per **tenant > plant > storage location > stock type > batch**; stock types are `UNRESTRICTED`, `QUALITY`, `BLOCKED`,
  `CONSIGNMENT` (supplier-owned, at our location) and `SUBCONTRACTOR` (our components at the subcontractor).
* `stock_movement` holds one signed line per change: movement type, quantity, **value at the standard price when it was posted** (`value_minor`,
  null when the material has no standard price), the document that caused it (`reference_type` / `reference_ref`), the inventory document
  (`posting_ref`: STP-, PHI-, RSV-), a `reason_code`, who and when.
* One code posts everything: `services/stock_ledger.post_movement`. It locks the balance row, refuses a balance below zero (422 `NEGATIVE_STOCK`),
  keeps quantities to three decimals, and checks the sign of one-sided movement types. The database also refuses a negative balance
  (`ck_stock_qty_not_negative`) and an unknown stock type (`ck_stock_stock_type`). **Never edit `stock.qty` directly**; the alert `NEGATIVE_DRIFT`
  lists any balance its movements do not explain (a direct edit, or stock that came from the ERP sync, which overwrites the ERP's own balance).
* Movement types: 101 receipt, 102 receipt reversal, 122 return to supplier, 201 issue to cost object, 201K consignment withdrawal, 301/311 transfer,
  321 release from quality, 343/344 unblock/block, 350 reject to blocked, 411K consignment to own stock, 541 components to the subcontractor,
  543/544 component consumption (reversal), 551 scrapping, 561 opening balance, 701/702 inventory difference gain/loss, `ERP` sync.

## 2. What may be done, by whom

| Action | Scope (roles that hold it) | Controls |
|---|---|---|
| Read stock, summary, alerts, stock card, movements, CSV export | `pic:read` (everyone internal) | Plant scope: the user's `plants` attribute (absent or `*`: all) |
| Create / submit / post / cancel a stock posting; create a reservation; issue it | `inventory:post` (RECEIVER, INVENTORY_CONTROLLER) | ABAC `INVENTORY_POST` / `INVENTORY_RESERVE` on company code and plant; period cut-off; active plant and location |
| Approve / reject a stock posting or count differences | `inventory:approve` (INVENTORY_CONTROLLER, FINANCE_CONTROLLER) | Never the maker (SOD-10) or a counter (SOD-11); ABAC `INVENTORY_APPROVE` incl. the approver's value limit |
| Enter counts and recounts | `inventory:count` (RECEIVER) | ABAC `INVENTORY_COUNT`; recount by someone other than the first counter |
| Cancel a reservation | its requester, or `inventory:post` | |
| Release stock from quality inspection | `quality:decide` through the **usage decision** of the inspection lot | A stock posting of type `RELEASE_QUALITY` is refused (422 `USE_USAGE_DECISION`) |

Other stock-changing commands (consignment withdrawal, recall, components to a subcontractor, expiry write-off, usage decision, receipt reversal) now
also check the user's plants (ABAC action `STOCK_MOVE` / `GR_POST`) and the posting period.

**Segregation of duties.** SOD-10: whoever created or submitted a stock posting cannot approve it (rule `INVENTORY_POST` vs `INVENTORY_APPROVE` per
posting). SOD-11: whoever counted or recounted cannot approve that count (`INVENTORY_COUNT` vs `INVENTORY_COUNT_APPROVE` per count); at assignment time
the scope pair `inventory:count` / `inventory:approve` cannot be held by one user, so RECEIVER and INVENTORY_CONTROLLER or FINANCE_CONTROLLER cannot be
combined. INVENTORY_CONTROLLER holds both `inventory:post` and `inventory:approve` on purpose (it must stay assignable); the per-document rule keeps
the maker away from the approval. Either rule can be switched to `MITIGATE` for an approved, time-boxed exception (not for Critical risk).

## 3. Stock postings (`/v1/stock-postings`)

`DRAFT -> SUBMITTED -> APPROVED -> POSTED` (or `REJECTED` / `CANCELLED`).

| Type | Movement | From -> to |
|---|---|---|
| TRANSFER | 311 within a plant, 301 plant to plant (same company code) | location -> location, unrestricted or blocked stock |
| BLOCK | 344 | unrestricted -> blocked, same location |
| UNBLOCK | 343 | blocked -> unrestricted |
| SCRAP | 551 | unrestricted or blocked -> out; reason code required (rule INVENTORY-POSTING `scrapReasons`) |

Submitting evaluates rule **INVENTORY-POSTING**: TRANSFER, BLOCK and UNBLOCK below `autoPostBelowMinor` (default 25,000.00) post at once; SCRAP and
everything above go to the approval chain of the value band (`approvalBands`; default up to 2 L: controller; up to 10 L: + finance; above: + CPO).
Posting re-checks the stock under the row locks and the posting period (the state may have changed since the submit): 422 `INSUFFICIENT_STOCK`,
409 `PERIOD_CLOSED`. A posting dated into a closed period is refused at submit.

## 4. Physical inventory (`/v1/physical-inventories`)

`PLANNED -> COUNTING -> COUNTED -> PENDING_APPROVAL -> APPROVED -> POSTED` (or `CANCELLED`; a rejected count returns to `COUNTING`).

1. **Create** for a plant and storage location, optionally limited by material group, named materials or ABC class (by value issued in the last 12
   months). The **book quantity of every line is frozen** (`frozenAt`). One open count per location and material at a time.
2. **Count blind.** The counter's view never carries book quantities or differences; the controller's does. Found stock that is not on the list is
   added as an *unlisted* line.
3. A count outside the tolerance of rule **INVENTORY-COUNT** (`qtyTolerancePct` and `valueToleranceMinor`; either exceeded) must be **recounted by
   another person** (`recountDifferentCounter`). A controller can also order a recount (`POST .../recount`).
4. **Submit**, then the approval chain of the value of the differences (`approvalBands`). Counters never approve (SOD-11).
5. **Post** (`inventory:post`): the difference posted is `counted - book at the freeze` as 701 (gain) / 702 (loss) on unrestricted stock, so a receipt
   posted while counting is **not** wiped out (`driftQty` shows what moved). A loss larger than the stock now on hand is refused.
6. Count accuracy (`M09.STOCK_COUNT_ACCURACY`) is the share of lines whose first count was inside the tolerance.

## 5. Reservations (`/v1/reservations`)

`OPEN -> PARTIALLY_ISSUED -> ISSUED` (or `CANCELLED` / `EXPIRED`). Creating one checks unrestricted stock at the location less other open
reservations; rule **INVENTORY-RESERVATION** `blockWhenUnavailable` (default false) decides between a warning (it is still demand) and a refusal. The
open quantity is a `RESERVATION` row in `demand_element`, so **MRP counts it as gross demand** (TD 9.1) and the stock card shows it. An issue posts 201
(first expiry first out unless a batch is named) and reduces the demand; a cancel or expiry sets the demand to zero (the row stays, with a new
`changed_at`, so a net-change MRP run replans the material). The job `inventory-reservations` (daily 02:45) expires reservations whose need date plus
`graceDays` has passed and removes zero-quantity reservation demand older than a week.

## 6. Rule sets and how to change them

`INVENTORY-POSTING`, `INVENTORY-COUNT`, `INVENTORY-RESERVATION`, `INVENTORY-ALERTS` are seeded for every tenant (migration 0018 for existing ones) and
fall back to the code defaults in `platform/inventory_defaults.py` for a tenant without a version. Read them with `GET /v1/inventory/rules`. A change
is a **new effective-dated version** through `POST /v1/admin/rules` (scope `admin:rules`); versions are never edited. Example:

```json
{"key": "INVENTORY-POSTING", "version": "2027.1", "effective_from": "2027-04-01",
 "body": {"autoPostBelowMinor": 1000000, "approvalBands": [
   {"upTo": 5000000, "chain": ["INVENTORY_CONTROLLER"]}, {"upTo": null, "chain": ["INVENTORY_CONTROLLER", "FINANCE_CONTROLLER"]}]},
 "description": "Plant 1100 pilot: lower auto-post limit"}
```

A version scoped with `plant` or `company_code` overrides the tenant-wide one for that scope. Unknown keys, bands that do not end with `upTo: null`,
and `SCRAP` in `autoPostTypes` are refused (422 `RULE_INVALID`). The approval chain names roles; make sure each role has a user who is not the maker
(two controllers per plant is the minimum).

## 7. ERP messages

Every posted stock posting, count difference and reservation issue enqueues a `STOCK_POSTING` message (idempotency key `STP|<number>`,
`PHI|<number>`, `RSV|<number>|<cumulative issued>`) and processes it like a goods receipt: retried with back-off, dead-lettered after 8 attempts
(see `dead-lettered-postings.md`), the ERP material document number comes back on the document (`erpDocument`). The SAP S/4HANA **simulator** posts every
message (document type MB, numbers from 4900000001). The **SAP connector** (`PIC_ERP_SAP_S4_URL` set) maps it to a material document, below. A connector that
does not map the type (Oracle, Dynamics, Tally, Odoo today) leaves the document posted in PIC and writes an `ERP_NOT_MAPPED` audit event: post such documents in
the ERP by hand.

> **Validated against the mock only.** The SAP mapping below was written from SAP's documentation of API_MATERIAL_DOCUMENT_SRV and BAPI_GOODSMVT_CREATE and is
> tested against the loopback mock (`tests/pic/sap_mock.py`: golden payloads and a round trip that returns a material document number). It has **not** run against a
> real SAP system. It needs a real SAP sandbox (field names, movement types allowed in the customer's configuration, stock-type codes, reason codes, account
> determination) before go-live. Section 7.3 lists what to confirm.

### 7.1 Movement types and what is sent

| PIC document | PIC movement | SAP goods movement code (`GoodsMovementCode` / `GM_CODE`) | SAP movement type | Stock type sent | Account assignment |
|---|---|---|---|---|---|
| Stock posting TRANSFER, same plant | 311 | 04 (MB1B transfer posting) | 311 | of the source stock (blocked: yes, unrestricted: none) | none |
| Stock posting TRANSFER, plant to plant | 301 | 04 | 301 | of the source stock | none |
| Stock posting BLOCK | 344 | 04 | 344 | none (the type says it) | none |
| Stock posting UNBLOCK | 343 | 04 | 343 | none | none |
| Stock posting SCRAP | 551 | 03 (MB1A goods issue) | 551 | of the source stock | cost centre (the document's cost object, else `PIC_ERP_SAP_S4_SCRAP_COST_CENTER`; refused when neither exists) |
| Physical inventory, gain | 701 | 05 (MB1C other goods receipt) | 701 | unrestricted | none |
| Physical inventory, loss | 702 | 03 | 702 | unrestricted | none |
| Reservation issue | 201 | 03 | 201 | unrestricted | cost centre or WBS element of the reservation's cost object (refused when it has none) |

One material document has one goods movement code, so a count with gains **and** losses is sent as two material documents (the header text carries `-03` / `-05`
after the key; `erpDocument` then holds both numbers joined with `/`). Nothing is sent twice: before posting, the connector looks the document up by its PIC
reference (`MaterialDocumentHeaderText`) and reuses one that SAP already holds.

### 7.2 Fields

| PIC | OData `A_MaterialDocumentHeader` / `A_MaterialDocumentItem` | IDoc MBGMCR03 segment field |
|---|---|---|
| posting date (the stock posting's; today for a count and a reservation issue) | `PostingDate`, `DocumentDate` | `E1BP2017_GM_HEAD_01` `PSTNG_DATE`, `DOC_DATE` |
| goods movement code | `GoodsMovementCode` | `E1BP2017_GM_CODE` `GM_CODE` |
| PIC key (`STP|STP-1001`, shortened to 25 characters with a digest) | `MaterialDocumentHeaderText` | `HEADER_TXT`, `EDI_DC40` `ARCKEY` |
| document number (`STP-1001`, `PHI-1001`, `RSV-1001`, 16 characters) | `ReferenceDocument` | `REF_DOC_NO` |
| material | `Material` | `MATERIAL` |
| plant, storage location (the stock leaves) | `Plant`, `StorageLocation` | `PLANT`, `STGE_LOC` |
| batch | `Batch` | `BATCH` |
| movement | `GoodsMovementType` | `MOVE_TYPE` |
| stock type (blocked / quality only) | `InventoryStockType` (`03` blocked, `02` quality) | `STCK_TYPE` (`S`, `X`) |
| quantity and unit (the material's base unit) | `QuantityInEntryUnit` (3 decimals), `EntryUnit` | `ENTRY_QNT`, `ENTRY_UOM` |
| receiving plant / storage location / batch (transfers) | `IssuingOrReceivingPlant`, `IssuingOrReceivingStorageLoc`, `IssgOrRcvgBatch` | `MOVE_PLANT`, `MOVE_STLOC`, `MOVE_BATCH` |
| cost centre / WBS element (551, 201) | `CostCenter`, `WBSElement` | `COSTCENTER`, `WBS_ELEM` |
| scrap reason (mapped by `PIC_ERP_SAP_S4_REASON_MAP`, else only in the text) | `GoodsMovementReasonCode`, `MaterialDocumentItemText` | `MOVE_REAS`, `ITEM_TEXT` |
| material document number answered by SAP | `MaterialDocument` (stored as `erpDocument`) | IDoc number from the port's answer |

Settings (all optional, environment variables of the API and the worker): `PIC_ERP_SAP_S4_SCRAP_COST_CENTER`, `PIC_ERP_SAP_S4_REASON_MAP` (`DAMAGED=0001,CORROSION=0002`),
`PIC_ERP_SAP_S4_STOCK_TYPE_MAP` (`QUALITY=02,BLOCKED=03`), plus the connector's usual URL, credentials, `SAP_CLIENT`, `ODATA_VERSION`, `TRANSPORT` (`odata`, `idoc`,
`idoc-file`) and `COMPANY_MAP`. Material and cost-centre numbers are sent as PIC holds them (the same as the goods receipt): add the SAP alpha conversion in the
field mapping layer (platform/field_mapping.py) if the customer's system needs leading zeros.

**Reversal is not mapped.** PIC never reverses a posted inventory document (a correction is a new document), and the goods receipt mapping has no reversal either; a message
that asks for one (`reversalOf`) is rejected with that reason. The reversal of a goods receipt (102) stays a manual action in SAP.

### 7.3 To confirm in a SAP sandbox before go-live

1. The goods movement code of 701 and 702: SAP normally posts count differences from a physical-inventory document (MI07, API_PHYSICALINVENTORYDOC_SRV), not from a goods
   movement. If the customer's configuration refuses 701/702 in a goods movement, replace this mapping by a physical-inventory document.
2. The stock-type codes (`InventoryStockType` 02 / 03, `STCK_TYPE` X / S) and whether a transfer from blocked stock needs them.
3. Which movement types the customer's plants allow, the reason codes of 551 and the account determination (a cost centre is needed when the scrapping account is a cost element).
4. The field names of the OData service on the customer's release (S/4HANA 2023 or 2024) and the IDoc partner profile, port and process code.
5. Unit codes: PIC sends its own unit (`EA`, `KG`, `L`, `SET`); SAP's external codes may differ (`ST`, `PC`).

## 8. What the tenant must supply

* Organisation: plants, storage locations (every plant has `0001`; add the others), company codes, cost objects for reservations.
* Materials with a **standard price** (value of every movement and the KPIs depend on it), safety stock, reorder points (planning parameters), batch and
  expiry flags (`batchManaged`, `expiryManaged` in material attributes).
* Opening stock: post opening balances through the ledger (movement 561) or load the ERP stock extract (`POST /v1/erp/sync`).
* Users: the INVENTORY_CONTROLLER role for at least two people per plant (approvals), RECEIVER for stores clerks, `plants` attributes, value limits.
* Decisions: the auto-post limit, approval bands, count tolerance, scrap reason codes, reservation grace days, alert limits.
* The client's ERP mapping of `STOCK_POSTING` (section 7).

The demo tenants AXN and KAC carry **mock** values for all of these so they behave like configured tenants (section 11). Mock values are labelled and are replaced, not
extended, by the customer's own.

## 9. Reading and reporting

`GET /v1/stock`, `/v1/stock/summary`, `/v1/stock/alerts`, `/v1/stock/materials/{material}`, `/v1/stock/movements` (+ `/export` CSV, audited with its
hash, 50,000 rows at most). KPIs: `M02.STOCKOUTS`, `M02.DAYS_OF_COVER`, `M09.INVENTORY_TURNS`, `M09.STOCK_COUNT_ACCURACY`,
`M09.STOCK_ADJUSTMENT_VALUE`, `TPL.EXPIRY_WRITE_OFFS` (healthcare). Targets can be overridden in rule `KPI-THRESHOLDS`.

## 10. Opening stock: the loader (the production path)

`python -m app.pic.tools.stock_opening_load --tenant <code> --file <opening_stock.csv> [--dry-run] [--strict] [--report out.json]`

The customer's SAP team exports its stock list (MARD for plant and storage-location stock, MCHB for batch stock, MKOL for consignment at the plant, MSKA/MSLB for special
stocks, the batch master MCH1 for the expiry date, MBEW for the valuation) and maps it to one CSV, UTF-8 with a header row:

| Column | Meaning |
|---|---|
| `material` | PIC material number (the SAP number as loaded by the ERP migration, without leading zeros) |
| `plant`, `storage_location` | must exist and be active in the organisation master (ADM-01); the material must be maintained at the plant |
| `stock_type` | `UNRESTRICTED`, `QUALITY`, `BLOCKED`, `CONSIGNMENT` or `SUBCONTRACTOR` |
| `batch` | required for a batch-managed material, at most 30 characters |
| `qty` | not negative, at most 3 decimals; `0` is a stock-out line (listed, nothing posted) |
| `uom` | must equal the material's base unit; convert quantities first |
| `expiry` | ISO date; required for an expiry-managed material in live stock; written to the batch master (`stock_batch`) so the expiry alerts and first-expiry-first-out see it |
| `valuation` | the value of the line in INR as the ERP stock list shows it, for the reconciliation only |

What it does: validates the **whole** file first and refuses it if any line is wrong (nothing is written; every error names its line and code); then posts every balance
through the ledger primitive as movement **561**, reference type `OPENING_BALANCE`, valued at the material's standard price, in one transaction, with one `INITIAL_LOAD`
audit event (file name, SHA-256, counts, value). Re-running a file is safe: a balance that already has an opening movement is skipped, and a balance that already holds
other postings is skipped with a warning (an opening balance is only posted into an empty balance), so a file can also be extended.

Validation errors: `MISSING_COLUMN`, `EMPTY_FILE`, `NOT_UTF8` (file); `UNKNOWN_MATERIAL`, `NOT_A_STOCK_MATERIAL`, `UNKNOWN_PLANT`, `PLANT_INACTIVE`, `UNKNOWN_LOCATION`,
`LOCATION_INACTIVE`, `MATERIAL_NOT_AT_PLANT`, `BAD_STOCK_TYPE`, `BAD_NUMBER`, `NEGATIVE_QTY`, `TOO_MANY_DECIMALS`, `UOM_MISMATCH`, `BATCH_REQUIRED`, `BATCH_TOO_LONG`,
`EXPIRY_REQUIRED`, `EXPIRY_WITHOUT_BATCH`, `BAD_DATE`, `BATCH_EXPIRY_CONFLICT` (a batch has one expiry per material), `BAD_VALUATION`, `MISSING_VALUE`, `DUPLICATE_KEY`. Exit
code 0 loaded or dry run, 2 refused.

**Reconciliation to the ERP stock list.** The report (and the JSON) gives, in total and per plant, the file's `valuation` total, PIC's value of the same quantities at the standard
price and the difference, and lists the lines that differ by more than INR 1.00. Procedure: (1) run with `--dry-run` and fix the file until there are no errors; (2) compare the
quantity totals per plant and the value totals with the ERP stock list (MB52 / MC.9) signed by the plant; (3) if the ERP values stock at a moving-average price the differences are
expected and are explained to finance (PIC values at standard price); with `--strict` any difference above INR 1.00 refuses the file; (4) load; (5) run a physical inventory of a sample.
After the load the ledger explains every balance (the alert `NEGATIVE_DRIFT` stays empty).

## 11. The mock go-live inputs of the demo tenants (dataset pack `inventory_master`, D14)

Everything is labelled MOCK (names, notes, rule descriptions, audit reasons, `data/erp_mock/KAC_INVENTORY/README.md`) and idempotent (seed-if-missing; a value that is set is never
overwritten). The pack requires `inventory_ops` and runs after it (`python -m app.pic.seed.datasets --only inventory_master`, part of the Neon setup run).

| Input | Mock content | What the customer replaces it with |
|---|---|---|
| ERP mapping of STOCK_POSTING | section 7, tested against the mock only | validation in a real SAP sandbox |
| Prices, safety stock, reorder points, batch / expiry flags | standard price only where missing (from the latest purchase-order line, contract price period or info record; none invented); safety stock = days of average usage by category (7 to 14), or 20 % of a typical lot; reorder point = daily usage x lead time + safety stock; max = reorder point + lot size; one `MASTER_DATA_FILLED` audit event per material; flags on chemicals, lubricants, rubber compounds, raw-material lots, adhesive tapes / labels, never on a material with an open order or batchless stock | the customer's own master data (or the ERP material sync) |
| Opening stock | KAC: 1,624 lines in `opening_stock.csv` through the loader (section 10) | the customer's stock list through the same loader |
| Controllers | two `INVENTORY_CONTROLLER` per plant of AXN and KAC (`inventory.controller.<plant>.1/.2`, that plant only; KAC with an approval limit that matches its bands) and a receiver for each plant that had none, same demo password mechanism and MFA setting as the other demo users | the customer's real users, plants and limits |
| Rule values | KAC only: version `2026.2-KAC-MOCK` of the four rule sets, "MOCK proposal - pending client sign-off", `docs/PIC_Inventory_Rule_Values_Proposal.md` | the signed-off values as later versions |
