# KAC_DELTA: Mock SAP S/4HANA Production Delta Extracts (Tenant KAC)

**Everything in this folder is deterministic mock data.** It provides high-fidelity post-cutover
incremental changes for Kaveri Auto Components Pvt Ltd (tenant KAC) as specified in Technical
Document §12.1 and §12.4.

This mock extract enables 100% offline demonstration, automated CI testing, and end-to-end
validation of the live inbound ERP sync engine (``app.pic.services.erp_sync``) without requiring
active credentials to a live client SAP S/4HANA production instance.

## Extract Summary
* **Extract ID:** ``KAC-S4H-20261102-DELTA``
* **Extract Type:** ``DELTA``
* **Target Company Code:** ``1000`` (Kaveri Auto Components Pvt Ltd)
* **Delta Date:** 2 November 2026 (Day-1 post cutover)

## Contents by Object Kind

| Kind | Files | Business Purpose |
|---|---|---|
| ``VENDORS`` | ``LFA1.csv``, ``ADRC.csv``, ``LFB1.csv``, ``LFBK.csv``, ``T052.csv`` | Updates existing vendor descriptions/terms; onboards 2 new suppliers (``200350``, ``200351``); simulates 1 sensitive bank/tax modification on ``100008`` routing to MDM-04 without cleartext exposure. |
| ``MATERIALS`` | ``MARA.csv``, ``MAKT.csv``, ``MARC.csv``, ``MBEW.csv``, ``PIC_MAP_MATKL.csv`` | Standard price revision on ``11000001`` in ``MBEW``; onboards 2 new direct materials (``11000901`` fasteners, ``11000902`` seals). |
| ``STOCK`` | ``STOCK.csv`` | Incremental physical inventory updates across plants 1100, 1200, 1300, updating ``Stock.qty`` and generating ``StockMovement`` audit records. |
| ``OPEN_POS`` | ``OPEN_POS.json`` | Reconciles purchase orders in SAP against PIC state machines; detects discrepancies and unknown ERP orders. |
| ``PAYMENT_STATUS`` | ``PAYMENT_STATUS.csv`` | Cleared AP documents in SAP (``BSIK`` -> ``BSAK``) flipping PIC posted invoices to ``PAID`` and emitting ``invoice.paid_in_erp`` outbox events. |
| ``PLANNED_ORDERS`` | ``PLANNED_ORDERS.csv`` | Incremental MRP planned orders imported for procurement scheduling. |
| ``PLANTS`` | ``PLANTS.csv`` | Plant name updates (Plant 1100) and new facility onboarding (Plant 1400 Coimbatore). |
| ``COST_OBJECTS`` | ``COST_OBJECTS.csv`` | New cost center (``CC140``) and capital investment WBS element (``W-2026-EXP``). |

## How to Use for Testing or Live Demonstration

```bash
# 1. Regenerate or verify this mock delta folder:
python -m app.pic.tools.erp_delta_mock

# 2. Stage into a fresh drop folder for FILE_DROP ingestion:
python -m app.pic.tools.erp_delta_mock --stage-drop /path/to/drop_dir

# 3. Trigger inbound ERP sync for tenant KAC:
# Inside Python or API:
# erp_sync.run("KAC", "VENDORS", directory=Path("/path/to/drop_dir"))
```
