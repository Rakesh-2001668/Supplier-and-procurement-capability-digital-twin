# PIC – Inventory Module Analysis and Completion

Date: 2 November 2026. Written for: the product owner, as the record of what the specification requires of inventory, what was found, what was built and fixed, how it was tested, and what is still open.

## 1. Finding in one paragraph

The Technical Document (TD) and Blueprint (BP) do not define a stand-alone inventory or warehouse module. Stock is a receipt-driven ledger that sits inside the supplier-fulfilment module (BP §15, M09), the special-stock rules (BP §22–23), the MRP supply formula (TD §9.1) and a handful of KPIs. Before this work the ledger was written correctly by goods receipt, quality decisions, consignment and subcontracting, but **nothing could read it and nothing governed changes to it**: there were no stock, movement, summary or alert endpoints, no screens, and no controlled way to post a transfer, block, scrap, count or reservation. The reservation demand type existed in the planning model but nothing created it. The old `/inventory` screens in the web app are a separate prototype with their own mock tables; they were left alone.

## 2. What the specification requires, and the state found

| # | Requirement (source) | State before | State now |
|---|---|---|---|
| 1 | Goods receipt updates stock, GR/IR and scorecard (BP F6) | Built | Unchanged, defects fixed (section 3) |
| 2 | GR for quality-managed materials posts to quality stock until usage decision (BP §15.4) | Built | Built; cut-off check added |
| 3 | Batch, serial, expiry capture where required (BP §15.1) | Built, with a serial-reuse defect and a 500 on bad dates | Fixed |
| 4 | Over-delivery above tolerance blocked at receipt (BP §15.4, TD §5.2) | Built | Unchanged |
| 5 | Consignment and subcontracting stock (BP §15.1, §22) | Built, no plant check | Plant and period checks added |
| 6 | MRP supply uses unrestricted on-hand (TD §9.1) | Built | Unchanged (consignment decision open, section 6) |
| 7 | Reservations are gross demand in MRP (TD §9.1) | Demand type only, nothing created it | Reservations create and release the demand |
| 8 | Stock/requirements list per material (BP MRP-02) | Missing | Material stock card with per-bucket projection |
| 9 | KPIs: stock-outs, days of cover, dock-to-stock, quality rejection (BP) | Built | Stock-out definition corrected; inventory turns, count accuracy, adjustment value added |
| 10 | Expiry write-offs, par levels, cold chain (healthcare template) | Built, expiry sweep wrongly used reversed receipts | Fixed |
| 11 | Org hierarchy plant → storage location, deactivated sites refused (BP §4.1) | Built for receipts | Applied to all stock postings |
| 12 | Segregation of duties, audit, ERP posting, idempotency (TD §3, §10) | Built for receipts | Applied to all new inventory commands |
| 13 | Read access to stock, movements, alerts (implied by every screen that shows stock) | Missing | Built |
| 14 | Governed stock adjustments (transfer, block, scrap, count) | Missing | Built (not named in the specification; added because the old prototype offered adjustments and an enterprise tenant needs them controlled) |

## 3. Defects found and fixed

Each has a regression test in `backend/tests/pic/test_inventory_ledger.py`.

1. **Serial numbers of a reversed receipt could never be received again.** The duplicate-serial check included reversed receipts, so the corrected receipt was refused. It is now one indexed query that ignores reversed receipts.
2. **A malformed expiry date returned HTTP 500.** Expiry and ASN batch dates are now validated and return 422.
3. **Reversing a receipt and taking a usage decision skipped the closed posting period.** Both now apply the cut-off.
4. **Missing indexes and constraints.** Ledger lookups had no supporting index. Added five indexes, a stock-type domain check and a non-negative quantity check (after confirming no seed or ERP-sync path writes a negative balance).
5. **Expiry sweep and value-analysis report used reversed receipts**, which could condemn good stock.
6. **Consignment withdrawal, recall, subcontractor components, expiry write-off, usage decision and receipt reversal had no plant (ABAC) check** and mostly no period check. Added.
7. **Quantities with more than three decimals were silently rounded** by the database; wrong-sign movements were accepted; two first postings of a balance could race. All now refused or serialised.
8. **Opening stock in two seed tenants had no ledger movement**, which would have shown as false drift. The seeds now post an opening movement.
9. **The stock-out KPI counted non-stock materials (services, expense items) and ignored the plant on the demand side.** Corrected in this pass.

## 4. What was built

- **Ledger service** (`stock_ledger.py`): one posting primitive used by receiving and the new code, with row lock, negative-stock guard, value at standard price, reason code and document reference on every movement.
- **Reads** (`stock_reads.py`, `/v1/stock…`): filterable stock list, summary (value, quality hold ageing, blocked, expiring, below safety, stock-outs, days of cover, open reservations and counts), typed alerts (stock-out, below safety, below reorder, expiring, expired, quality hold aged, blocked aged, drift), material stock card with the MRP-02 requirements profile, movement ledger and a capped, hashed, audited CSV export.
- **Stock postings** (`STP-`): transfer, block, unblock, scrap. Draft, submitted, approved, posted, rejected, cancelled. Value-banded approval chain; small transfers, blocks and unblocks post automatically; scrap always needs approval; the maker can never approve (SOD-10, enforced per document). Stock is re-checked under lock at posting.
- **Physical inventory** (`PHI-`): count freeze, blind counting, tolerance-driven recount by a different person, approval by someone who did not count (SOD-11), differences posted as 701/702 relative to the freeze so receipts during counting are not wiped out.
- **Reservations** (`RSV-`): availability check, demand for MRP, partial issue (first-expiry-first-out), cancel, daily expiry job.
- **Rule sets** (effective-dated, editable through the admin rules route): `INVENTORY-POSTING`, `INVENTORY-COUNT`, `INVENTORY-RESERVATION`, `INVENTORY-ALERTS`.
- **Access**: scopes `inventory:post`, `inventory:count`, `inventory:approve`; new built-in role `INVENTORY_CONTROLLER`; Receiver may post and count; Finance Controller may approve.
- **Integration**: ERP message type `STOCK_POSTING`, idempotent per document; 8 event schemas; KPIs `INVENTORY_TURNS`, `STOCK_COUNT_ACCURACY`, `STOCK_ADJUSTMENT_VALUE`.
- **Data**: migration 0018; demo pack `inventory_ops` for the AXN and KAC tenants (KAC also receives an opening position of 20 materials).
- **Screens**: Inventory (stock, alerts, movements, postings, counts, reservations), material stock card, and detail pages for postings, counts and reservations with the usual approvals, documents, lineage and audit tabs; navigation entry; links from receipts and lot trace.
- **Runbook**: `docs/runbooks/inventory_operations.md`.

## 5. Test evidence

- Inventory ledger tests 14, inventory journey 21 steps through the HTTP API, inventory demo pack 5: passing.
- Dataset, industry and module-case tests (62) passed on a fresh database. One apparent failure in the KAC test came from running the inventory pack first in the same database; it passes in the normal order.
- About 765 of 849 backend tests ran in the engineer's full run with no pre-existing test failing; the full suite has **not** been run to completion on the final code.
- Migration 0018: upgrade, downgrade to 0017, upgrade again and model/migration comparison all passed on a scratch database.
- Browser (real flows against a scratch database): every tab and the stock card as controller, receiver and plain reader; a transfer that auto-posts; a scrap that waits for approval, refused for its maker and approved by a second controller; a blind count entered by a receiver, approved and posted by a controller with a loss; a reservation issued in two parts and one cancelled; CSV export; 390 px mobile width; keyboard tab navigation. No console errors or failed calls.
- Frontend `tsc` exit 0; ESLint on the CI scope 0 errors.

## 6. Open items and decisions

1. **Not run in the browser:** block and unblock postings, rejecting a posting, a Finance Controller approving, a controller requesting a recount, and the batch, material-group, expiring and below-safety filters. The shortage highlighting in the material card was not seen because the demo data has no demand inside the 90-day horizon.
2. **Full backend suite** to be run once on the final code before the push.
3. **Decision: consignment stock in MRP supply.** The TD says unrestricted only, so consignment goods are neither open order nor on-hand supply after receipt. Left as specified.
4. **Decision: cancelled or issued reservations** set the demand to zero and keep the row so net-change MRP replans the material; the daily job removes zero rows after seven days.
5. **SOD-10** is enforced per document, not as a role-pair rule, because the new controller role legitimately holds both posting and approval. Consequence: a Receiver cannot also be an Inventory Controller or Finance Controller.
6. **Known, not changed:** the ERP stock sync writes an empty-batch balance that can double-count batch-managed materials; fractional quantities are accepted for each-unit materials (no unit-of-measure rule); demo documents are dated 2027 by the pinned business clock, so new documents sort below them in lists.
7. The old `/inventory` prototype screens still use their own mock tables and are not part of the PIC lint scope.

## 7. What the product owner must supply

- ERP mapping of the `STOCK_POSTING` message (goods-movement BAPI or material-document API) for any live ERP; the SAP simulator works today.
- Standard prices, safety stock, reorder points and batch/expiry flags on materials; opening stock for real tenants (ledger opening movement or ERP stock sync).
- At least two Inventory Controller users per plant, with plant and value-limit attributes.
- Decisions on the rule values: auto-post limit (default ₹25,000), approval bands, count tolerance (2% and ₹5,000), scrap reason codes, reservation grace days (7), alert ageing limits.
- A decision window to apply migration 0018 to production, then the normal Neon setup run (it seeds number ranges, rule sets, SoD rules and the demo pack).
