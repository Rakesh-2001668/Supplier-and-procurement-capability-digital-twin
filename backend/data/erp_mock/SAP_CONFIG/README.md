# SAP_CONFIG: mock SAP S/4HANA customizing (MOCK, fictional)

This folder is a small, fictional extract of SAP customizing for the AXN and KAC demo tenants.
It is not taken from any real SAP system. Replace it with the client's values before go-live.

It is used in three places:

1. The SAP sandbox simulator (`platform/sap_customizing.py`) checks every outline agreement,
   payment reversal and supply-chain-finance posting against these tables, the way SAP would.
2. Dataset pack D21 (`seed/datasets/sap_config.py`) writes `PIC_RULES.json` as tenant rules
   for AXN and KAC, so the values are visible and editable in the rules administration.
3. `samples/` shows the exact requests the live connector sends, built by the mapping code.
   `tests/pic/test_sap_live_mapping.py` fails if a sample no longer matches the code.

## Files

| File | SAP table | What it holds |
|---|---|---|
| `T001.csv` | T001 | Company codes: AXN 1000, 1100; KAC 1000, 2000 (same as the PIC org masters D19). |
| `T024E.csv` | T024E | Purchasing organisations and their company code (same codes as `data/reference/org_masters.csv`). |
| `T024.csv` | T024 | Purchasing groups. `PIC_EKORG` is PIC's assignment to an organisation; SAP itself does not store it. |
| `T161.csv` | T161 | Purchasing document types: PR `NB`; PO `NB`, `FO`, `UB`; contracts `MK`, `WK`; scheduling agreements `LP`, `LPA`. |
| `T041C.csv` | T041C | Reversal reasons. `XABWD = X` means an alternative posting date is allowed. |
| `T003.csv` | T003 | FI document types (`KA` for the SCF posting, `KZ` payment, `SA` G/L). |
| `T042Z.csv` | T042Z | Payment methods for India (N NEFT, R RTGS, I IMPS, T host-to-host, C cheque). |
| `T023.csv` | T023 | Material groups for contract lines without a material (`SERVICES` is the default). |
| `BP_FINANCIER.csv` | BUT000 / LFB1 | The SCF financier business partner per tenant, extended to each company code. |
| `PIC_RULES.json` | (PIC) | The rule versions pack D21 writes: SAP-OUTLINE-AGREEMENT, SAP-PAYMENT-REVERSAL, SAP-SCF-FINANCING. |
| `SIMULATOR_DEFAULTS.json` | (PIC) | Values the simulator uses when a tenant rule leaves one empty. A live connector rejects instead. |
| `samples/` | (PIC) | Request and response bodies for the three message types. |

## Values per tenant

| Tenant | Company code | Purchasing org | Purchasing group | SCF financier BP |
|---|---|---|---|---|
| AXN | 1000 | PO10 | G01 | 9800001 |
| AXN | 1100 | PO30 | G04 | 9800001 |
| KAC | 1000 | PO10 | G03 | 9800011 |
| KAC | 2000 | PO21 | G01 | 9800011 |

## Samples

| File | Message |
|---|---|
| `OUTLINE_AGREEMENT_MK_create.request.json` / `.response.json` | Quantity contract, new (API_PURCHASECONTRACT_PROCESS_SRV). |
| `OUTLINE_AGREEMENT_WK_rate_card_create.request.json` | Rate card as a value contract with a text item. |
| `OUTLINE_AGREEMENT_LP_create.request.json` / `.response.json` | Scheduling agreement, new (API_SCHED_AGRMT_PROCESS_SRV). |
| `OUTLINE_AGREEMENT_MK_change.request.json` | New contract version: item PATCH, new item POST, header PATCH last. |
| `OUTLINE_AGREEMENT_close.request.json` | Termination: the validity end is set. |
| `PAYMENT_REVERSAL.request.json` / `.response.json` | Reversal of a returned payment's clearing document. |
| `SCF_FINANCING.request.json` / `.response.json` | Journal entry moving the payable to the financier (OData). |
| `SCF_FINANCING_FIDCCP02.idoc.xml` | The same posting as an IDoc FIDCCP02. |

The responses are illustrative. The services `ZAPI_VENDOR_PAYMENT_SRV` and `ZAPI_JOURNAL_ENTRY_SRV` are
placeholders for the client's own services (see `docs/PIC_SAP_Document_Types.md`).

To rebuild the samples after a mapping change, run from `backend/`:

```
python -c "from tests.pic.test_sap_live_mapping import write_samples; write_samples()"
```
