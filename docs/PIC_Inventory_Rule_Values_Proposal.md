# PIC Inventory: proposed rule values for Kaveri Auto Components (KAC)

**Status: MOCK proposal - pending client sign-off.** The values below are *not confirmed by the customer*. They are a starting proposal, scaled to the
value range of KAC's own (mock) data, so the demo tenant behaves like a configured one. Each is published in PIC as a new effective-dated version
`2026.2-KAC-MOCK` (effective 1 November 2026) whose description reads "MOCK proposal - pending client sign-off". The customer's finance, plant and stores
teams decide the real values; the sign-off table at the end is theirs to fill. Until it is signed these values must not be described as agreed.

Date: 2 November 2026. Scope: tenant KAC only (AXN keeps the documented defaults, version `2026.1`). Amounts are in rupees, stored in paise.

## 1. What the values are scaled to

KAC's own data (mock SAP extract and the mock opening stock, `backend/data/erp_mock/KAC` and `KAC_INVENTORY`): 1,068 stock materials, 1,554 material-plant
combinations, opening stock of INR 50.2 crore at standard price.

| Measure | Rupees |
|---|---|
| Value of one stock line (quantity x standard price): 25th percentile / median / 75th / 90th / 95th | 42,000 / 97,000 / 2,50,000 / 6,40,000 / 11,00,000 |
| Standard price of one unit: median / 90th percentile | 382 / 4,335 (die sets run to INR 40 lakh each) |
| Monthly usage value of a material at a plant: median / 90th percentile | 49,000 / 4,20,000 |

A stock posting (transfer, block, scrap) normally moves a part of one line, so a posting of INR 3 lakh is already above three quarters of a whole stock line.

## 2. INVENTORY-POSTING (stock postings: transfer, block, unblock, scrap)

| Key | Default | Proposed for KAC | Why |
|---|---|---|---|
| `autoPostBelowMinor` | 25,000 | **50,000** (5,000,000 paise) | About half the median stock line. Below it a transfer, block or unblock posts at once; a scrap never does. Bulk fasteners and consumables move in values far below this. |
| `autoPostTypes` | TRANSFER, BLOCK, UNBLOCK | unchanged | SCRAP always needs an approval (the rule refuses it as an auto-post type). |
| `approvalBands` | up to 2 lakh: controller; to 10 lakh: + finance; above: + CPO | **up to 3,00,000: Inventory Controller; up to 15,00,000: Inventory Controller and Finance Controller; above 15,00,000: Finance Controller and CPO** | 3 lakh is about the 75th percentile of a stock line, 15 lakh about the 95th: the controller decides everyday adjustments, finance joins for the large ones, the CPO only for the exceptional. Above the controller's own limit (section 6) the controller no longer takes part, so the chain cannot stall on an approver whose limit is exceeded. |
| `reasonRequiredFor` | BLOCK, SCRAP | unchanged | A block and a scrap are explained in words. |
| `scrapReasons` | DAMAGED, EXPIRED, OBSOLETE, QUALITY, LOST, OTHER | **CASTING_DEFECT** (porosity, cold shut, blow hole), **MACHINING_REJECT**, **HANDLING_DAMAGE**, **CORROSION**, **SHELF_LIFE_EXPIRED** (rubber, adhesive, chemical, lubricant), **SUPERSEDED_ECN**, **FIRE_OR_SPILL**, OTHER | KAC is an automotive component maker (die casting, forgings, machining, rubber seals); its scrap is casting and machining rejects, rust in storage, aged rubber and chemicals, and parts superseded by an engineering change. |
| `blockReasons` | QUALITY_DOUBT, DAMAGED, RECALL, INVESTIGATION, OTHER | QUALITY_DOUBT, **SUPPLIER_8D**, **CUSTOMER_COMPLAINT**, DAMAGED, RECALL, OTHER | A supplier 8D containment and a customer-complaint trace-back are the two usual reasons to block automotive stock. |
| `crossPlantTransfer` | true | true | **Open question for the customer:** plant 1300 (Bidadi) is in Karnataka and plants 1100 and 1200 in Tamil Nadu. A transfer across the state border is a taxable stock transfer in SAP (delivery challan, e-way bill, GST invoice). PIC's plant-to-plant posting (301) only mirrors the stock movement. If SAP's stock transfer order is the master, set this to false and let PIC read the result. |
| `maxLines` | 100 | 100 | |
| `slaBusinessDays` | 2 | 2 | |

## 3. INVENTORY-COUNT (physical inventory)

| Key | Default | Proposed | Why |
|---|---|---|---|
| `qtyTolerancePct` | 2 | **1** | Automotive suppliers aim for a stock record accuracy of 99 % or better; a line more than 1 % off is recounted by a second person. |
| `valueToleranceMinor` | 5,000 | **10,000** (1,000,000 paise) | About a tenth of the median stock line; either limit (quantity or value) triggers the recount. |
| `recountDifferentCounter` | true | true | |
| `approvalBands` | to 50,000: controller; to 5 lakh: + finance; above: + CPO | **to 50,000: Inventory Controller; to 5,00,000: Inventory Controller and Finance Controller; above: Finance Controller and CPO** | The same shape as the postings; count differences are small, so the first bands stay low. |
| `maxLines`, `slaBusinessDays`, `differenceReasonCode` | 2000, 3, COUNT_DIFF | unchanged | |

## 4. INVENTORY-RESERVATION

| Key | Default | Proposed | Why |
|---|---|---|---|
| `graceDays` | 7 | **3** | Production and maintenance reservations are consumed within the weekly schedule; an unused one should release its demand quickly. |
| `blockWhenUnavailable` | false | false | A reservation of stock that is not there is still demand for MRP (Technical Document 9.1); it is warned about, not refused. |
| `requireCostObject` | true | true | |
| `purposes` | PRODUCTION, MAINTENANCE, PROJECT, SERVICE, OTHER | PRODUCTION, MAINTENANCE, **TOOLING**, **QUALITY_TRIAL**, PROJECT, OTHER | Die and tooling jobs and quality trials are the other reasons to reserve stock in KAC's plants. |
| `maxOpenDays` | 365 | **90** | A need date further out than a quarter is a plan, not a reservation. |

## 5. INVENTORY-ALERTS

| Key | Default | Proposed | Why |
|---|---|---|---|
| `qualityHoldDays` | 7 | **3** | Incoming inspection of castings and forgings should clear within three days; longer holds stop the line. |
| `blockedDays` | 30 | **15** | Blocked stock ties up cash and space; a fortnight is enough for a supplier 8D decision. |
| `expiryWarnDays` | 90 | 90 | Rubber, adhesives and chemicals (minimum shelf life 60 to 180 days at receipt) need a quarter's warning to be used first. |
| `negativeDrift` | true | true | |

## 6. Inventory Controller users and their approval limit

Two mock Inventory Controllers per plant (`inventory.controller.<plant>.1` and `.2`, for 1100, 1200 and 1300), each restricted to their own plant. Each controller's
`approval_limits.INVENTORY_APPROVE` is **INR 15,00,000** (150,000,000 paise), the top of the highest band their role takes part in: a controller approves up to that
value, above it the chain is the Finance Controller and the CPO. The maker of a posting can never approve it (SOD-10); a count's counters can never approve its
differences (SOD-11). Real users, names and limits are the customer's to supply.

## 7. How a value is changed after sign-off

A new version through `POST /v1/admin/rules` (scope `admin:rules`) with a later effective date; versions are never edited. For example, to confirm the auto-post limit
and the bands from 1 December 2026, publish `INVENTORY-POSTING` with version `2026.3` and `effective_from` 2026-12-01 and a description such as "Approved by <name>, <date>";
the labelled `2026.2-KAC-MOCK` version then stops applying from that date. The current effective values are read with `GET /v1/inventory/rules`.

## 8. Sign-off

| Rule set | Decision | Approver (name, role) | Date | Signature |
|---|---|---|---|---|
| INVENTORY-POSTING: auto-post limit, approval bands, scrap and block reasons, cross-plant transfers | accepted / changed to: | | | |
| INVENTORY-COUNT: tolerance, value tolerance, approval bands | accepted / changed to: | | | |
| INVENTORY-RESERVATION: grace days, purposes, maximum open days | accepted / changed to: | | | |
| INVENTORY-ALERTS: quality-hold, blocked and expiry limits | accepted / changed to: | | | |
| Inventory Controller approval limit and the two controllers per plant | accepted / changed to: | | | |

Sign-off table to be completed by the customer. The approver and date columns are intentionally blank.
