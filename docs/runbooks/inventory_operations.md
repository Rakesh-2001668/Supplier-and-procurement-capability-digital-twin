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
(see `dead-lettered-postings.md`), the ERP material document number comes back on the document (`erpDocument`). The SAP S/4HANA **simulator** maps
the message type. A live connector that does not map it leaves the document posted in PIC and writes an `ERP_NOT_MAPPED` audit event: map
`STOCK_POSTING` to the client's material-document API (BAPI_GOODSMVT_CREATE / API_MATERIAL_DOCUMENT_SRV: 311/301/343/344/551/701/702/201) before
go-live, or post these documents in the ERP by hand.

## 8. What the tenant must supply

* Organisation: plants, storage locations (every plant has `0001`; add the others), company codes, cost objects for reservations.
* Materials with a **standard price** (value of every movement and the KPIs depend on it), safety stock, reorder points (planning parameters), batch and
  expiry flags (`batchManaged`, `expiryManaged` in material attributes).
* Opening stock: post opening balances through the ledger (movement 561) or load the ERP stock extract (`POST /v1/erp/sync`).
* Users: the INVENTORY_CONTROLLER role for at least two people per plant (approvals), RECEIVER for stores clerks, `plants` attributes, value limits.
* Decisions: the auto-post limit, approval bands, count tolerance, scrap reason codes, reservation grace days, alert limits.
* The client's ERP mapping of `STOCK_POSTING` (section 7).

## 9. Reading and reporting

`GET /v1/stock`, `/v1/stock/summary`, `/v1/stock/alerts`, `/v1/stock/materials/{material}`, `/v1/stock/movements` (+ `/export` CSV, audited with its
hash, 50,000 rows at most). KPIs: `M02.STOCKOUTS`, `M02.DAYS_OF_COVER`, `M09.INVENTORY_TURNS`, `M09.STOCK_COUNT_ACCURACY`,
`M09.STOCK_ADJUSTMENT_VALUE`, `TPL.EXPIRY_WRITE_OFFS` (healthcare). Targets can be overridden in rule `KPI-THRESHOLDS`.
