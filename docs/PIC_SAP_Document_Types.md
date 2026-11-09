# PIC to SAP S/4HANA: document types and postings

This note covers three PIC messages that now have a live SAP mapping:
contracts (OUTLINE_AGREEMENT), the reversal of a returned payment (PAYMENT_REVERSAL)
and supply-chain finance (SCF_FINANCING).

All values below are defaults. Each one is a tenant rule. A rule can be set per company code
and has an effective date. Change it in Administration, Rules (no code change).

Everything here was tested against a mock SAP only. The client must confirm it in their
SAP sandbox before go-live. Section 6 lists what to confirm.

Code: `backend/app/pic/platform/sap_mapping.py` (request bodies),
`platform/sap_defaults.py` (rules and checks), `platform/connectors.py` (class `SapS4`),
`platform/sap_customizing.py` (the simulator's checks).
Mock SAP data: `backend/data/erp_mock/SAP_CONFIG/`.

## 1. Mapping table

| PIC document | SAP document | SAP document type | SAP API (entity set) | Number SAP returns |
|---|---|---|---|---|
| Purchase requisition | Purchase requisition | NB | API_PURCHASEREQ_PROCESS_SRV (A_PurchaseRequisitionHeader) | PurchaseRequisition |
| Purchase order | Purchase order | NB (FO, UB by setting) | API_PURCHASEORDER_PROCESS_SRV (A_PurchaseOrder) | PurchaseOrder |
| Quantity contract | Quantity contract | MK | API_PURCHASECONTRACT_PROCESS_SRV (A_PurchaseContract) | PurchaseContract |
| Value contract | Value contract | WK | API_PURCHASECONTRACT_PROCESS_SRV (A_PurchaseContract) | PurchaseContract |
| Rate card | Value contract | WK | API_PURCHASECONTRACT_PROCESS_SRV (A_PurchaseContract) | PurchaseContract |
| Statement of work (SOW) | Value contract | WK | API_PURCHASECONTRACT_PROCESS_SRV (A_PurchaseContract) | PurchaseContract |
| Scheduling agreement | Scheduling agreement | LP | API_SCHED_AGRMT_PROCESS_SRV (A_SchAgrmtHeader) | SchedulingAgreement |
| Master agreement | Not sent | - | - | - |
| NDA | Not sent | - | - | - |
| Payment returned by the bank | Reversal of the clearing document | reason 01 | Client's payment service (A_VendorPaymentReversal) | ReverseDocument |
| Supply-chain finance election | Journal entry, supplier to financier | KA | Client's journal service (A_JournalEntry) or IDoc FIDCCP02 | AccountingDocument |

Rate card and SOW: both are sent as WK value contracts. The contract's target value is the
header target value (PurchaseContractTargetAmount). Each PIC line is an item. A line without a
material is a text item with a material group and account assignment category U (unknown), so the
call-off order assigns the cost centre. If the client uses service items, set
`serviceItemCategory` (for example D for lean services or 9 for services with service lines).

Master agreements and NDAs are legal documents. SAP has no object for them. PIC never sends
them. This is not an error: nothing is queued and no retry happens.

## 2. What happens over a contract's life

| PIC event | What PIC sends | SAP call |
|---|---|---|
| Contract activated | Create | POST of the header with its items (deep insert). |
| Amendment, extension or index reset (new version or new prices) | Change | PATCH of each existing item, POST of new items, then PATCH of the header. |
| Termination takes effect | Close | PATCH of the header: validity end = last day in force. |
| Renewal by a successor that starts early | Close of the predecessor | PATCH of the header: validity end = the day before the successor starts. |
| Renewal by a successor | Create of the successor | A new SAP agreement. |
| Contract expires | Nothing | The SAP validity end already ends it. |
| Master agreement or NDA | Nothing | PIC never queues it. A call-off type a rule lists in notSent is recorded as ERP_NOT_SENT in the audit trail. |

PIC writes its reference into the header field CorrespncExternalReference ("Your reference",
12 characters). A change and a close write the new reference in the last call. So if a call
fails half way, PIC does not find the change in SAP and sends it again. Item PATCHes are safe
to repeat. A new item that already reached SAP is PATCHed on the retry, not created twice.

Versions reach SAP in order. A newer version waits while an older one is still retrying.

A contract migrated from SAP keeps its SAP number. Its first change from PIC updates that number.

## 3. Payment reversal

When the bank returns a payment, PIC asks SAP to reverse the payment's clearing document.

Fields sent: CompanyCode, AccountingDocument (the clearing document), FiscalYear,
ReversalReason, PostingDate, ResetClearing, DocumentHeaderText (PIC reference),
PaymentReference, ReversalText.

- Reason 01 (reversal in current period) with the payment's original posting date. This is the default.
- If PIC has closed that posting period, reason 02 (reversal in closed period) with the return date.
- ResetClearing true: the service first resets the cleared items (FBRA), then reverses (FB08).
- Fiscal year: the year the payment's fiscal year starts in (April start: January 2027 is fiscal year 2026).

SAP has no released OData API that resets clearing and reverses in one step.
So the reversal goes to the client's own payment service, the one named in
`PIC_ERP_SAP_S4_PAYMENT_SERVICE` (the same service that posts outgoing payments).
Without that service the reversal is not mapped. PIC then tells treasury to reverse it in SAP by hand.
IDoc transports do not map it either.

## 4. Supply-chain finance (SCF)

SAP has no standard API for this. PIC posts one journal entry:

| Line | Posting key | Account | Debit / credit | Amount |
|---|---|---|---|---|
| 1 | 21 | Supplier (vendor) | Debit | Invoice gross |
| 2 | 31 | Financier business partner (vendor), due on the maturity date | Credit | Invoice gross |
| 2 (alternative) | 50 | Financier G/L account | Credit | Invoice gross |

Document type KA. Reference: invoice number in DocumentReferenceID, the SAP invoice number in
AssignmentReference, PIC reference in DocumentHeaderText.

Transport: the client's journal entry service named in `PIC_ERP_SAP_S4_JOURNAL_SERVICE`
(fields follow the Journal Entry Post API). Without it, PIC sends IDoc FIDCCP02.

This posting needs the client's design. Open points:

- Clearing: the journal entry does not clear the supplier invoice. The client decides how the
  supplier's invoice and the debit line are cleared (automatic clearing by assignment, or a clearing posting).
- Fees and discount charged by the financier are not posted.
- Withholding tax (TDS) is not split. The full gross is moved.
- Whether the financier is a vendor (business partner) or a G/L liability account.

## 5. Rules and defaults

Rules are effective-dated and can be scoped per company code. A version must hold every key it
needs: the most specific version wins on its own and is not merged with the tenant-wide one.
Keys left out take the code default.

### SAP-OUTLINE-AGREEMENT

| Key | Default | Meaning |
|---|---|---|
| documentTypes | QUANTITY_CONTRACT MK, VALUE_CONTRACT WK, SCHEDULING_AGREEMENT LP, RATE_CARD WK, SOW WK | PIC type to SAP document type. |
| contractTypes | MK, WK | Types sent to the purchase contract API (category K). |
| schedulingAgreementTypes | LP, LPA | Types sent to the scheduling agreement API (category L). |
| notSent | MASTER_AGREEMENT, NDA | Never sent. |
| purchasingOrg | empty | Empty: `PIC_ERP_SAP_S4_PURCH_ORG`, else the only active PIC purchasing org of the company code. |
| purchasingGroup | empty | Empty: `PIC_ERP_SAP_S4_PURCH_GROUP`, else the only PIC purchasing group of that org. |
| textItemMaterialGroup | empty | Material group of lines without a material. Required in live mode when such lines exist. |
| textItemAccountAssignment | U | Account assignment category of text items. |
| serviceItemCategory | empty | Item category of text items of the serviceItems types (D, 9 ...). |
| serviceItems | RATE_CARD, SOW | Types whose text items get serviceItemCategory. |
| closeOnTermination | true | Send the validity end when a contract is terminated. |
| closeOnRenewal | true | Send the validity end when a successor starts before the end. |

### SAP-PAYMENT-REVERSAL

| Key | Default | Meaning |
|---|---|---|
| reversalReason | 01 | SAP reversal reason (table T041C). |
| postingDate | ORIGINAL | ORIGINAL (payment posting date) or RETURN_DATE (day the return was recorded). RETURN_DATE needs a reason that allows another date. |
| closedPeriodReason | 02 | Used, with the return date, when PIC has closed the payment's period. Empty = never. |
| resetClearing | true | Reset the cleared items before the reversal. |

### SAP-SCF-FINANCING

| Key | Default | Meaning |
|---|---|---|
| documentType | KA | FI document type. |
| postingKeys | supplierDebit 21, financierCredit 31, glCredit 50 | Posting keys. |
| financiers | empty | Per PIC financier code (rule EARLY-PAYMENT scf.financier, default PROGRAMME): `businessPartner` or `glAccount`, and `paymentMethod`. |

In live mode an SCF election whose financier is not configured is rejected and retried, so the
client sees it in the integration monitor. The simulator uses its mock financier instead.

### Connector settings (environment)

| Setting | Use |
|---|---|
| PIC_ERP_SAP_S4_PAYMENT_SERVICE | Client OData service for payments and their reversal. |
| PIC_ERP_SAP_S4_JOURNAL_SERVICE | Client OData service for the SCF journal entry. |
| PIC_ERP_SAP_S4_TERMS_MAP | PIC payment terms to SAP terms key for contracts, e.g. `N45=Z045`. Unmapped terms are not sent; SAP then uses the vendor master. |
| PIC_ERP_SAP_S4_COMPANY_MAP | PIC company code to SAP company code. |

### Mock values (dataset pack D21)

Pack `sap_config` (D21) writes these rules for AXN and KAC from `SAP_CONFIG/PIC_RULES.json`:
purchasing org and group per company code (AXN 1000 PO10/G01, 1100 PO30/G04; KAC 1000 PO10/G03,
2000 PO21/G01), material group SERVICES for text items, reason 01 / 02, and the mock financier
9800001 (AXN) or 9800011 (KAC). They are MOCK values.

## 6. What the client must confirm in the sandbox

1. Document types: are MK, WK and LP used, or own types (for example ZMK)? Add own types to
   contractTypes or schedulingAgreementTypes and to documentTypes.
2. Rate card and SOW: value contract WK with text items, or service items (item category D or 9)?
3. Field names we could not confirm from public documentation:
   - contract item text `PurchaseContractItemText` and price `ContractNetPriceAmount`;
   - item category `PurchasingDocumentItemCategory` and `AccountAssignmentCategory` on contract items;
   - scheduling agreement header type `PurchasingDocumentType`, item text `PurchasingDocumentItemText`, price `NetPriceAmount`;
   - whether CorrespncExternalReference can be changed by PATCH on both APIs;
   - whether item keys are sent as `'10'` or `'00010'`.
4. Time-dependent prices: PIC sends the current price as the item net price. If the client keeps
   price validity periods as conditions (PB00 with validity), that needs the condition entity of the API.
5. Lines removed in PIC are not deleted in SAP (PIC does not remove contract lines today).
6. Termination: is setting the validity end enough, or should items also get the deletion
   indicator or a block?
7. Purchasing organisation and group per company code.
8. Payment terms map (PIC terms to SAP terms keys).
9. Reversal: the client's payment service must reset clearing and reverse. Confirm reason 01
   (no other posting date allowed) and reason 02 in table T041C.
10. Payment documents over IDoc: the number PIC receives is an IDoc number, not the accounting
    document. A reversal needs the real clearing document number, so use the payment service.
11. SCF: the whole design in section 4 (clearing, fees, tax, vendor or G/L, posting keys,
    document type, the financier's business partner and its company code extension).
12. Services: the names `ZAPI_VENDOR_PAYMENT_SRV` and `ZAPI_JOURNAL_ENTRY_SRV` are placeholders.
    The entity sets and field names we use are in `SAP_CONFIG/samples/`.

## 7. Simulator

Without `PIC_ERP_SAP_S4_URL` the SAP connector is a simulator. For these three messages it runs the
same mapping as the live connector. It then checks the request against the mock customizing:
document type allowed (T161, T003), reversal reason and posting date (T041C), financier and its
company code (BP_FINANCIER), payment method (T042Z), material group (T023), and the mandatory fields.
It refuses what SAP would refuse, and the message goes to retry with the reason.
A contract change or close keeps the agreement's number, as in SAP.
The request sent is kept with the simulated document (`erp_document.payload.sapRequest`).
