"""PIC message → SAP S/4HANA mappings (OData request bodies and IDoc XML) for the real SAP connector.

Assumptions (confirm against the customer's system at onboarding; they are the *released* S/4HANA APIs from SAP API Business Hub):

  PURCHASE_REQUISITION  API_PURCHASEREQ_PROCESS_SRV   A_PurchaseRequisitionHeader, deep insert to_PurchaseReqnItem;
                        reference in PurReqnDescription (40 chars); the number is PurchaseRequisition.
  PURCHASE_ORDER        API_PURCHASEORDER_PROCESS_SRV A_PurchaseOrder, deep insert to_PurchaseOrderItem(+ to_ScheduleLine);
                        reference in CorrespncExternalReference ("Your reference", 12 chars); number = PurchaseOrder.
  SUPPLIER_INVOICE      API_SUPPLIERINVOICE_PROCESS_SRV A_SupplierInvoice with to_SuplrInvcItemPurOrdRef (PO-based items) or
  SUPPLIER_CREDIT_MEMO  to_SuplrInvcItemAcctAssgmt (G/L items, needs PIC_ERP_SAP_S4_GL_ACCOUNT); credit memo =
                        SupplierInvoiceIsCreditMemo true; reference in DocumentHeaderText (25 chars); number = SupplierInvoice.
  GOODS_RECEIPT         API_MATERIAL_DOCUMENT_SRV     A_MaterialDocumentHeader (GoodsMovementCode 01) with
                        to_MaterialDocumentItem (movement type 101 against the PO item); reference in MaterialDocumentHeaderText
                        (25 chars); number = MaterialDocument.
  STOCK_POSTING         API_MATERIAL_DOCUMENT_SRV     A_MaterialDocumentHeader (GoodsMovementCode 03/04/05) with to_MaterialDocumentItem for the
                        inventory documents PIC posts: stock postings (311/301 transfer, 343/344 unblock/block, 551 scrap), physical-inventory
                        differences (701/702) and reservation issues (201); reference in MaterialDocumentHeaderText (25 chars) and
                        ReferenceDocument (the PIC document number, 16 chars); number = MaterialDocument. One material document has one goods
                        movement code, so a document that needs two (a count with gains and losses) is sent as two material documents. VALIDATED
                        AGAINST THE MOCK ONLY: confirm every field of this block in a real SAP sandbox before go-live (docs/runbooks/inventory_operations.md 7).
  SUPPLIER_MASTER       API_BUSINESS_PARTNER          A_BusinessPartner (category 2 = organisation) with roles FLVN00/FLVN01,
                        tax number IN3 (GSTIN), bank, address, e-mail; reference in SearchTerm1 (20 chars); number = BusinessPartner.
                        Changes PATCH the partner (tax number, address, e-mail).
  MATERIAL_MASTER       API_PRODUCT_SRV               A_Product with to_Description; the key is the material number (Product).
  SUPPLIER_DEBIT_MEMO   API_SUPPLIERINVOICE_PROCESS_SRV A_SupplierInvoice (not a credit memo): price corrections as PO items with
                        IsSubsequentDebitCredit "X" (subsequent debit), charges as G/L items (PIC_ERP_SAP_S4_GL_ACCOUNT). OData only (no IDoc
                        mapping); VALIDATE in a sandbox (unplanned delivery costs instead of G/L items for freight is a customer choice).
  GOODS_RECEIPT 102     the reversal of a receipt PIC reverses is a material document with movement type 102 against the same PO items,
                        quantities and batches (GoodsMovementCode 01), its own reference; VALIDATE in a sandbox (cancellation instead).
  PAYMENT_REVERSAL,     NOT MAPPED for a live system (UNMAPPED_LIVE): a returned bank credit is reversed in SAP with FB08 plus resetting the
  SCF_FINANCING         cleared items, and an SCF settlement is booked by the financier's interface; both need the customer's design and a sandbox.
  PAYMENT               no released OData API posts an outgoing payment: the IDoc FIDCCP02 (FI document, message type FIDCCH) is
                        used when an IDoc transport is configured; otherwise a customer service named in
                        PIC_ERP_SAP_S4_PAYMENT_SERVICE with entity set A_VendorPayment (fields as built below).

IDoc basic types: PORDCR105/PORDCR1 (purchase order), MBGMCR03/MBGMCR (goods movement), INVOIC02/INVOIC (logistics invoice
verification), CREMAS05/CREMAS (vendor), MATMAS05/MATMAS (material), FIDCCP02/FIDCCH (payment FI document). Segment field names
follow the standard IDoc definitions; the partner profile, port and process codes are the customer's.
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional
from xml.sax.saxutils import escape

from app.pic.platform.sap_odata import odata_date

SERVICES = {
    "PURCHASE_REQUISITION": "API_PURCHASEREQ_PROCESS_SRV",
    "PURCHASE_ORDER": "API_PURCHASEORDER_PROCESS_SRV",
    "SUPPLIER_INVOICE": "API_SUPPLIERINVOICE_PROCESS_SRV",
    "SUPPLIER_CREDIT_MEMO": "API_SUPPLIERINVOICE_PROCESS_SRV",
    "SUPPLIER_DEBIT_MEMO": "API_SUPPLIERINVOICE_PROCESS_SRV",
    "GOODS_RECEIPT": "API_MATERIAL_DOCUMENT_SRV",
    "STOCK_POSTING": "API_MATERIAL_DOCUMENT_SRV",
    "SUPPLIER_MASTER": "API_BUSINESS_PARTNER",
    "MATERIAL_MASTER": "API_PRODUCT_SRV",
}
MESSAGE_TYPES = ("PURCHASE_REQUISITION", "PURCHASE_ORDER", "GOODS_RECEIPT", "SUPPLIER_INVOICE", "SUPPLIER_CREDIT_MEMO",
                 "SUPPLIER_MASTER", "MATERIAL_MASTER", "PAYMENT", "STOCK_POSTING", "SUPPLIER_DEBIT_MEMO")
# Not mapped for a live SAP system (simulator only; they stay manual steps until confirmed in the customer's sandbox, see the docstring):
# PAYMENT_REVERSAL (returned bank credit: FB08 reversal + reset of the cleared items, no released API) and SCF_FINANCING (the financier's
# settlement is booked by the SCF platform's own ERP interface).
UNMAPPED_LIVE = ("PAYMENT_REVERSAL", "SCF_FINANCING")
# message type -> (IDoc basic type, message type)
IDOC_TYPES = {"PURCHASE_ORDER": ("PORDCR105", "PORDCR1"), "GOODS_RECEIPT": ("MBGMCR03", "MBGMCR"), "STOCK_POSTING": ("MBGMCR03", "MBGMCR"), "SUPPLIER_INVOICE": ("INVOIC02", "INVOIC"),
              "SUPPLIER_CREDIT_MEMO": ("INVOIC02", "INVOIC"), "SUPPLIER_MASTER": ("CREMAS05", "CREMAS"),
              "MATERIAL_MASTER": ("MATMAS05", "MATMAS"), "PAYMENT": ("FIDCCP02", "FIDCCH")}


def amount(minor: Optional[int]) -> str:
    value = int(minor or 0)
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value) // 100}.{abs(value) % 100:02d}"


def quantity(value) -> str:
    return str(Decimal(str(value or 0)).quantize(Decimal("0.001"), ROUND_HALF_UP))


def trim(value, length: int) -> str:
    return str(value if value is not None else "")[:length]


def item_number(line_no) -> str:
    """SAP item numbers are 5 digits with leading zeros in OData keys (PO items 00010)."""
    return f"{int(line_no):05d}"


class Spec:
    """What to create and how to find it again."""

    def __init__(self, service: str, entity_set: str, body: dict, reference_field: Optional[str], reference: str, number_field: str,
                 key_path: Optional[str] = None, select: Optional[str] = None):
        self.service, self.entity_set, self.body = service, entity_set, body
        self.reference_field, self.reference, self.number_field = reference_field, reference, number_field
        self.key_path = key_path      # lookup by key instead of by reference field (e.g. A_Product('X'))
        self.select = select or number_field


# ---------------------------------------------------------------- OData builders
def purchase_requisition(p: dict, ctx: dict) -> Spec:
    v = ctx["version"]
    items = []
    for n, line in enumerate(p.get("lines", []), start=1):
        items.append({"PurchaseRequisitionItem": str(n * 10), "PurchaseRequisitionItemText": trim(line.get("description") or line.get("material"), 40),
                      "Material": line.get("material"), "Plant": line.get("plant"), "RequestedQuantity": quantity(line.get("qty")),
                      "BaseUnit": line.get("uom") or "EA", "PurchaseRequisitionPrice": amount(line.get("priceMinor")),
                      "PurReqnItemCurrency": "INR", "DeliveryDate": odata_date(date.fromisoformat(line["needDate"]), v) if line.get("needDate") else None,
                      "PurchasingGroup": ctx.get("purch_group")})
    body = {"PurchaseRequisitionType": "NB", "PurReqnDescription": trim(ctx["reference"], 40),
            "to_PurchaseReqnItem": [{k: x for k, x in it.items() if x is not None} for it in items]}
    return Spec(SERVICES["PURCHASE_REQUISITION"], "A_PurchaseRequisitionHeader", body, "PurReqnDescription", trim(ctx["reference"], 40), "PurchaseRequisition")


def purchase_order(p: dict, ctx: dict, lines: list[dict]) -> Spec:
    v = ctx["version"]
    items = []
    for line in lines:
        item = {"PurchaseOrderItem": str(int(line["line"])), "PurchaseOrderItemText": trim(line.get("description") or line.get("material"), 40),
                "Material": line.get("material"), "Plant": line.get("plant"), "StorageLocation": line.get("storageLocation"),
                "OrderQuantity": quantity(line.get("qty")), "PurchaseOrderQuantityUnit": line.get("uom") or "EA",
                "NetPriceAmount": amount(line.get("priceMinor")), "NetPriceQuantity": "1", "DocumentCurrency": "INR",
                "TaxCode": ctx.get("tax_code"), "MaterialGroup": line.get("materialGroup")}
        item = {k: x for k, x in item.items() if x not in (None, "")}
        if line.get("needDate"):
            item["to_ScheduleLine"] = [{"ScheduleLine": "1", "ScheduleLineDeliveryDate": odata_date(date.fromisoformat(line["needDate"]), v),
                                        "ScheduledQuantity": quantity(line.get("qty"))}]
        items.append(item)
    body = {"CompanyCode": ctx["company"], "PurchaseOrderType": ctx.get("po_type") or "NB", "Supplier": ctx["vendor"],
            "PurchasingOrganization": ctx.get("purch_org"), "PurchasingGroup": ctx.get("purch_group"), "DocumentCurrency": "INR",
            "PurchaseOrderDate": odata_date(ctx["today"], v), "CorrespncExternalReference": trim(ctx["reference"], 12),
            "PaymentTerms": ctx.get("payment_terms"), "to_PurchaseOrderItem": items}
    body = {k: x for k, x in body.items() if x not in (None, "")}
    return Spec(SERVICES["PURCHASE_ORDER"], "A_PurchaseOrder", body, "CorrespncExternalReference", trim(ctx["reference"], 12), "PurchaseOrder")


def supplier_invoice(p: dict, ctx: dict, items: list[dict], credit: bool = False) -> Spec:
    """items: [{"po": "4500000001", "poItem": 10, "netMinor": 0, "qty": 0, "uom": "EA", "taxCode": "V1"}] for PO-based invoices or
    [{"glAccount": "...", "netMinor": 0, "taxCode": ""}] for invoices without a PO."""
    v = ctx["version"]
    po_items, gl_items = [], []
    for n, it in enumerate(items, start=1):
        if it.get("po"):
            po_items.append({"SupplierInvoiceItem": str(n), "PurchaseOrder": it["po"], "PurchaseOrderItem": item_number(it["poItem"]),
                             "DocumentCurrency": "INR", "SupplierInvoiceItemAmount": amount(it["netMinor"]),
                             "QuantityInPurchaseOrderUnit": quantity(it.get("qty") or 1), "PurchaseOrderQuantityUnit": it.get("uom") or "EA",
                             "TaxCode": it.get("taxCode") or ctx.get("tax_code")})
        else:
            gl_items.append({"SupplierInvoiceItem": str(n), "CompanyCode": ctx["company"], "GLAccount": it["glAccount"], "DocumentCurrency": "INR",
                             "SupplierInvoiceItemAmount": amount(it["netMinor"]), "DebitCreditCode": "S", "TaxCode": it.get("taxCode") or ctx.get("tax_code")})
    number = p.get("creditNote") if credit else p.get("invoice")
    body = {"CompanyCode": ctx["company"], "DocumentDate": odata_date(ctx.get("document_date") or ctx["today"], v), "PostingDate": odata_date(ctx["today"], v),
            "SupplierInvoiceIDByInvcgParty": trim(number, 16), "InvoicingParty": ctx["vendor"], "DocumentCurrency": "INR",
            "InvoiceGrossAmount": amount(p.get("grossMinor")), "DocumentHeaderText": trim(ctx["reference"], 25),
            "SupplierInvoiceIsCreditMemo": bool(credit), "PaymentTerms": ctx.get("payment_terms"),
            "TaxIsCalculatedAutomatically": True}
    if po_items:
        body["to_SuplrInvcItemPurOrdRef"] = {"results": po_items} if v == 2 else po_items
    if gl_items:
        body["to_SuplrInvcItemAcctAssgmt"] = {"results": gl_items} if v == 2 else gl_items
    body = {k: x for k, x in body.items() if x not in (None, "")}
    return Spec(SERVICES["SUPPLIER_INVOICE"], "A_SupplierInvoice", body, "DocumentHeaderText", trim(ctx["reference"], 25), "SupplierInvoice",
                select="SupplierInvoice,FiscalYear")


GR_MOVEMENTS = ("101", "102")  # goods receipt for a PO item / its reversal (both GoodsMovementCode 01 against the PO item)


def gr_movement(p: dict) -> str:
    """Movement type of a GOODS_RECEIPT message: 101, or 102 for the reversal PIC sends after reversing a receipt (payload movement)."""
    movement = str(p.get("movement") or "101")
    if movement not in GR_MOVEMENTS:
        raise ValueError(f"goods receipt movement {movement} is not mapped (101 receipt, 102 reversal)")
    return movement


def supplier_debit_memo(p: dict, ctx: dict, items: list[dict]) -> Spec:
    """Supplier debit note (upward price correction / additional charge) as a logistics invoice of type subsequent debit
    (API_SUPPLIERINVOICE_PROCESS_SRV, SupplierInvoiceIsCreditMemo false): PRICE lines become PO-referenced items flagged
    IsSubsequentDebitCredit = "X" (the quantity stays, only the value is debited); CHARGE lines (freight, packing) become G/L items on
    PIC_ERP_SAP_S4_GL_ACCOUNT. Reference in DocumentHeaderText (25 chars); number = SupplierInvoice. VALIDATE in a SAP sandbox: the
    customer may book charges as unplanned delivery costs (header UnplannedDeliveryCost) instead of G/L items.
    items: [{"po", "poItem", "netMinor", "qty", "uom", "taxCode"}] or [{"glAccount", "netMinor", "taxCode", "text"}]."""
    v = ctx["version"]
    po_items, gl_items = [], []
    for n, it in enumerate(items, start=1):
        if it.get("po"):
            po_items.append({"SupplierInvoiceItem": str(n), "PurchaseOrder": it["po"], "PurchaseOrderItem": item_number(it["poItem"]),
                             "DocumentCurrency": "INR", "SupplierInvoiceItemAmount": amount(it["netMinor"]),
                             "QuantityInPurchaseOrderUnit": quantity(it.get("qty") or 1), "PurchaseOrderQuantityUnit": it.get("uom") or "EA",
                             "IsSubsequentDebitCredit": "X", "TaxCode": it.get("taxCode") or ctx.get("tax_code")})
        else:
            gl_items.append({"SupplierInvoiceItem": str(n), "CompanyCode": ctx["company"], "GLAccount": it["glAccount"], "DocumentCurrency": "INR",
                             "SupplierInvoiceItemAmount": amount(it["netMinor"]), "DebitCreditCode": "S",
                             "SupplierInvoiceItemText": trim(it.get("text"), 50) or None, "TaxCode": it.get("taxCode") or ctx.get("tax_code")})
    body = {"CompanyCode": ctx["company"], "DocumentDate": odata_date(ctx.get("document_date") or ctx["today"], v), "PostingDate": odata_date(ctx["today"], v),
            "SupplierInvoiceIDByInvcgParty": trim(p.get("supplierDebitNote") or p.get("debitNote"), 16), "InvoicingParty": ctx["vendor"],
            "DocumentCurrency": "INR", "InvoiceGrossAmount": amount(p.get("grossMinor")), "DocumentHeaderText": trim(ctx["reference"], 25),
            "SupplierInvoiceIsCreditMemo": False, "AssignmentReference": trim(p.get("invoiceErp"), 18) or None, "TaxIsCalculatedAutomatically": True}
    if po_items:
        clean = [{k: x for k, x in i.items() if x not in (None, "")} for i in po_items]
        body["to_SuplrInvcItemPurOrdRef"] = {"results": clean} if v == 2 else clean
    if gl_items:
        clean = [{k: x for k, x in i.items() if x not in (None, "")} for i in gl_items]
        body["to_SuplrInvcItemAcctAssgmt"] = {"results": clean} if v == 2 else clean
    body = {k: x for k, x in body.items() if x not in (None, "")}
    return Spec(SERVICES["SUPPLIER_DEBIT_MEMO"], "A_SupplierInvoice", body, "DocumentHeaderText", trim(ctx["reference"], 25), "SupplierInvoice",
                select="SupplierInvoice,FiscalYear")


def goods_receipt(p: dict, ctx: dict, items: list[dict]) -> Spec:
    """API_MATERIAL_DOCUMENT_SRV material document for a PO receipt (101) or its reversal (102: same PO items and quantities, GoodsMovementCode
    01, MaterialDocumentHeaderText = the reversal's own reference so query-before-retry finds it). VALIDATE the 102 against a SAP sandbox: some
    customers require the reversal as a cancellation of the original material document instead (MIGO 'Cancellation' / BAPI_GOODSMVT_CANCEL)."""
    v = ctx["version"]
    movement = gr_movement(p)
    rows = []
    for it in items:
        row = {"Material": it["material"], "Plant": it["plant"], "StorageLocation": it.get("storageLocation"), "GoodsMovementType": movement,
               "PurchaseOrder": it["po"], "PurchaseOrderItem": item_number(it["poItem"]), "QuantityInEntryUnit": quantity(it["qty"]),
               "EntryUnit": it.get("uom") or "EA", "GoodsMovementRefDocType": "B", "Batch": it.get("batch") or None}
        rows.append({k: x for k, x in row.items() if x not in (None, "")})
    body = {"PostingDate": odata_date(ctx["today"], v), "DocumentDate": odata_date(ctx["today"], v), "GoodsMovementCode": "01",
            "MaterialDocumentHeaderText": trim(ctx["reference"], 25), "ReferenceDocument": trim(p.get("gr"), 16),
            "to_MaterialDocumentItem": {"results": rows} if v == 2 else rows}
    return Spec(SERVICES["GOODS_RECEIPT"], "A_MaterialDocumentHeader", body, "MaterialDocumentHeaderText", trim(ctx["reference"], 25), "MaterialDocument",
                select="MaterialDocument,MaterialDocumentYear")


# ---------------------------------------------------------------- inventory documents (STOCK_POSTING): material documents
# PIC movement type -> SAP goods movement code of the material document (BAPI_GOODSMVT_CREATE GM_CODE / OData GoodsMovementCode):
# 03 goods issue (MB1A), 04 transfer posting (MB1B), 05 other goods receipt (MB1C). 701/702 are physical-inventory differences: SAP normally posts
# them from a physical-inventory document (MI07 / API_PHYSICALINVENTORYDOC_SRV); posting them as goods movements is an ASSUMPTION to confirm in the
# customer's sandbox (the alternative is a count document in SAP).
STOCK_GM_CODE = {"311": "04", "301": "04", "343": "04", "344": "04", "551": "03", "201": "03", "702": "03", "701": "05"}
STOCK_MOVEMENT_TEXT = {"311": "transfer, storage location to storage location", "301": "transfer, plant to plant", "343": "unblock", "344": "block",
                       "551": "scrapping", "201": "goods issue to cost object", "701": "inventory difference, gain", "702": "inventory difference, loss"}
# PIC stock type -> SAP stock type of the item. Unrestricted is SAP's default and is not sent. The OData codes and the IDoc codes are ASSUMPTIONS to
# confirm (setting PIC_ERP_SAP_S4_STOCK_TYPE_MAP overrides them): OData InventoryStockType 02/03, BAPI STCK_TYPE X/S.
STOCK_TYPE_ODATA = {"QUALITY": "02", "BLOCKED": "03"}
STOCK_TYPE_IDOC = {"QUALITY": "X", "BLOCKED": "S"}
STOCK_OBJECTS = {"STOCK_POSTING": "posting", "PHYSICAL_INVENTORY": "inventory", "STOCK_RESERVATION": "reservation"}


def stock_number(object_type: str, p: dict) -> str:
    """The PIC document number of an inventory message (stock posting, physical inventory or reservation)."""
    return str(p.get(STOCK_OBJECTS.get(object_type, "posting")) or "")


def stock_items(object_type: str, p: dict, uoms: dict, ctx: dict) -> list[dict]:
    """The material-document items of an inventory message, in the order of its lines. ``uoms`` maps material number -> unit of measure.
    Raises ValueError for a line the SAP mapping cannot express (unknown movement, stock type that has no SAP code, a movement that needs
    an account assignment and has none)."""
    number = stock_number(object_type, p)
    reason = p.get("reasonCode")
    items = []
    for line in p.get("lines") or []:
        movement = str(line.get("movement") or "")
        if movement not in STOCK_GM_CODE:
            raise ValueError(f"movement type {movement or '?'} has no SAP goods movement mapping")
        material = line.get("material")
        if material not in uoms:
            raise ValueError(f"material {material} is unknown, so its unit of measure cannot be sent")
        stock_type = line.get("fromStockType") or "UNRESTRICTED"
        if stock_type not in ("UNRESTRICTED", "QUALITY", "BLOCKED"):
            raise ValueError(f"stock type {stock_type} cannot be posted as a goods movement")
        if movement in ("343", "344"):
            stock_type = "UNRESTRICTED"        # the movement type itself says which stock the goods leave; no stock type is sent
        qty = Decimal(str(line.get("qty") or 0))
        item = {"movement": movement, "material": material, "plant": line.get("fromPlant") or p.get("plant"),
                "sloc": line.get("fromStorageLocation") or p.get("storageLocation"), "batch": line.get("batch") or "", "qty": quantity(abs(qty)),
                "uom": uoms[material], "stockType": stock_type, "toPlant": None, "toSloc": None, "toBatch": None, "costCenter": None, "wbs": None,
                "reasonCode": None, "text": trim(" ".join(x for x in (number, reason if movement == "551" else None) if x), 50)}
        if movement in ("311", "301"):
            item.update(toPlant=line.get("toPlant") if movement == "301" else None, toSloc=line.get("toStorageLocation"), toBatch=line.get("batch") or None)
        if movement in ("551", "201"):
            kind, _, code = str(p.get("costObject") or "").partition(":")
            if code and kind.upper() == "WBS":
                item["wbs"] = code
            elif code:
                item["costCenter"] = code
            elif ctx.get("stock_cost_center"):
                item["costCenter"] = ctx["stock_cost_center"]
            else:
                raise ValueError(f"movement {movement} ({STOCK_MOVEMENT_TEXT[movement]}) needs a cost centre: the document names none and "
                                 "PIC_ERP_SAP_S4_SCRAP_COST_CENTER is not set")
            item["reasonCode"] = (ctx.get("reason_map") or {}).get(reason) if movement == "551" else None
        items.append(item)
    if not items:
        raise ValueError("the document has no lines")
    return items


def stock_groups(items: list[dict]) -> list[tuple[str, list[dict]]]:
    """[(goods movement code, items)] in code order: one material document per code (a count with gains and losses is two documents)."""
    groups: dict[str, list[dict]] = {}
    for item in items:
        groups.setdefault(STOCK_GM_CODE[item["movement"]], []).append(item)
    return sorted(groups.items())


def stock_codes(p: dict) -> list[str]:
    """The goods movement codes (one material document each) a message's lines need, from the payload alone (no database)."""
    return sorted({STOCK_GM_CODE.get(str(line.get("movement") or "")) or "00" for line in p.get("lines") or []})


def stock_reference(reference: str, code: str, documents: int) -> str:
    """PIC reference written into the material document (header text, 25 characters): the key itself, with the goods movement code appended
    when the message needs more than one document, so each can be found again."""
    return reference if documents == 1 else f"{reference[:22]}-{code}"


def stock_posting(object_type: str, p: dict, ctx: dict, items: list[dict]) -> list[Spec]:
    """OData bodies of an inventory message: one ``A_MaterialDocumentHeader`` deep insert per goods movement code (``Spec.code``)."""
    v, groups = ctx["version"], stock_groups(items)
    codes = ctx.get("stock_type_codes") or STOCK_TYPE_ODATA
    posted = date.fromisoformat(p["postingDate"]) if p.get("postingDate") else ctx["today"]
    specs = []
    for code, rows in groups:
        out = []
        for it in rows:
            row = {"Material": it["material"], "Plant": it["plant"], "StorageLocation": it["sloc"], "Batch": it["batch"] or None,
                   "GoodsMovementType": it["movement"], "InventoryStockType": codes.get(it["stockType"]), "QuantityInEntryUnit": it["qty"],
                   "EntryUnit": it["uom"], "IssuingOrReceivingPlant": it["toPlant"], "IssuingOrReceivingStorageLoc": it["toSloc"],
                   "IssgOrRcvgBatch": it["toBatch"], "CostCenter": it["costCenter"], "WBSElement": it["wbs"],
                   "GoodsMovementReasonCode": it["reasonCode"], "MaterialDocumentItemText": it["text"]}
            out.append({k: x for k, x in row.items() if x not in (None, "")})
        reference = stock_reference(ctx["reference"], code, len(groups))
        body = {"PostingDate": odata_date(posted, v), "DocumentDate": odata_date(posted, v), "GoodsMovementCode": code,
                "MaterialDocumentHeaderText": trim(reference, 25), "ReferenceDocument": trim(stock_number(object_type, p), 16),
                "to_MaterialDocumentItem": {"results": out} if v == 2 else out}
        spec = Spec(SERVICES["STOCK_POSTING"], "A_MaterialDocumentHeader", body, "MaterialDocumentHeaderText", trim(reference, 25), "MaterialDocument",
                    select="MaterialDocument,MaterialDocumentYear")
        spec.code = code
        specs.append(spec)
    return specs


def business_partner(p: dict, ctx: dict, supplier: dict) -> Spec:
    """supplier: {"code","name","gstin","bank":{"account","ifsc","holder"},"email","address":{...},"terms"} with *plain* values."""
    v = ctx["version"]
    body = {"BusinessPartnerCategory": "2", "BusinessPartnerGrouping": ctx.get("bp_grouping") or "BP02", "OrganizationBPName1": trim(supplier["name"], 35),
            "OrganizationBPName2": trim(supplier["name"][35:], 35) or None, "SearchTerm1": trim(supplier["code"], 20), "Language": "EN",
            "to_BusinessPartnerRole": {"results": [{"BusinessPartnerRole": "FLVN00"}, {"BusinessPartnerRole": "FLVN01"}]} if v == 2
            else [{"BusinessPartnerRole": "FLVN00"}, {"BusinessPartnerRole": "FLVN01"}]}
    if supplier.get("gstin"):
        taxes = [{"BPTaxType": "IN3", "BPTaxNumber": supplier["gstin"]}]
        body["to_BusinessPartnerTax"] = {"results": taxes} if v == 2 else taxes
    if supplier.get("bank"):
        b = supplier["bank"]
        banks = [{"BankIdentification": "0001", "BankCountryKey": "IN", "BankNumber": trim(b["ifsc"], 15), "BankAccount": trim(b["account"], 18),
                  "BankAccountHolderName": trim(b.get("holder"), 60)}]
        body["to_BusinessPartnerBank"] = {"results": banks} if v == 2 else banks
    address = supplier.get("address") or {}
    if address:
        row = {"Country": "IN", "StreetName": trim(address.get("line1") or address.get("street"), 60), "CityName": trim(address.get("city"), 40),
               "PostalCode": trim(address.get("pincode") or address.get("postalCode"), 10), "Region": trim(address.get("state"), 3) or None}
        if supplier.get("email"):
            row["to_EmailAddress"] = {"results": [{"EmailAddress": trim(supplier["email"], 241)}]} if v == 2 else [{"EmailAddress": trim(supplier["email"], 241)}]
        body["to_BusinessPartnerAddress"] = {"results": [{k: x for k, x in row.items() if x}]} if v == 2 else [{k: x for k, x in row.items() if x}]
    body = {k: x for k, x in body.items() if x not in (None, "")}
    return Spec(SERVICES["SUPPLIER_MASTER"], "A_BusinessPartner", body, "SearchTerm1", trim(supplier["code"], 20), "BusinessPartner")


def product(p: dict, ctx: dict) -> Spec:
    v = ctx["version"]
    descriptions = [{"Language": "EN", "ProductDescription": trim(p.get("description") or p.get("material"), 40)}]
    body = {"Product": trim(p.get("material"), 40), "ProductType": ctx.get("product_type") or "ROH", "BaseUnit": p.get("uom") or "EA",
            "ProductGroup": trim(p.get("group"), 9) or None, "to_Description": {"results": descriptions} if v == 2 else descriptions}
    body = {k: x for k, x in body.items() if x not in (None, "")}
    return Spec(SERVICES["MATERIAL_MASTER"], "A_Product", body, None, trim(p.get("material"), 40), "Product",
                key_path=f"A_Product({_q(trim(p.get('material'), 40))})")


def vendor_payment(p: dict, ctx: dict) -> Spec:
    v = ctx["version"]
    body = {"CompanyCode": ctx["company"], "PostingDate": odata_date(ctx["today"], v), "DocumentCurrency": "INR", "PaymentAmount": amount(p.get("amountMinor")),
            "Supplier": ctx["vendor"], "ClearedSupplierInvoice": p.get("invoiceErp"), "DocumentHeaderText": trim(ctx["reference"], 25),
            "PaymentReference": trim(p.get("payment"), 18)}
    body = {k: x for k, x in body.items() if x not in (None, "")}
    return Spec(ctx.get("payment_service") or "ZAPI_VENDOR_PAYMENT_SRV", "A_VendorPayment", body, "DocumentHeaderText", trim(ctx["reference"], 25), "AccountingDocument")


def _q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


# ---------------------------------------------------------------- IDoc builders
def _control(basic: str, message: str, ctx: dict, ref: str) -> str:
    return (f'<EDI_DC40 SEGMENT="1"><TABNAM>EDI_DC40</TABNAM><DIRECT>2</DIRECT><IDOCTYP>{basic}</IDOCTYP><MESTYP>{message}</MESTYP>'
            f'<SNDPOR>{escape(ctx.get("idoc_sender_port") or "PIC")}</SNDPOR><SNDPRT>LS</SNDPRT><SNDPRN>{escape(ctx.get("idoc_partner") or "PICCLOUD")}</SNDPRN>'
            f'<RCVPOR>{escape(ctx.get("idoc_port") or "SAPS4")}</RCVPOR><RCVPRT>LS</RCVPRT><RCVPRN>{escape(ctx.get("idoc_receiver") or "S4HCLNT")}</RCVPRN>'
            f'<ARCKEY>{escape(trim(ref, 70))}</ARCKEY></EDI_DC40>')


def _seg(name: str, fields: dict) -> str:
    inner = "".join(f"<{k}>{escape(str(x))}</{k}>" for k, x in fields.items() if x not in (None, ""))
    return f'<{name} SEGMENT="1">{inner}</{name}>'


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def idoc_xml(message_type: str, p: dict, ctx: dict, data: dict) -> str:
    """IDoc XML for a message. ``data`` carries the enriched details (lines, supplier master); ctx the settings."""
    if message_type not in IDOC_TYPES:
        raise ValueError(f"no IDoc mapping for {message_type}")
    basic, message = IDOC_TYPES[message_type]
    ref, today = ctx["reference"], ctx["today"]
    body = ""
    if message_type == "PURCHASE_ORDER":
        body = _seg("E1BPMEPOHEADER", {"COMP_CODE": ctx["company"], "DOC_TYPE": ctx.get("po_type") or "NB", "VENDOR": ctx["vendor"],
                                       "PURCH_ORG": ctx.get("purch_org"), "PUR_GROUP": ctx.get("purch_group"), "CURRENCY": "INR", "DOC_DATE": _ymd(today),
                                       "REF_1": trim(ref, 12)})
        for line in data.get("lines", []):
            body += _seg("E1BPMEPOITEM", {"PO_ITEM": item_number(line["line"]), "SHORT_TEXT": trim(line.get("description"), 40), "MATERIAL": line.get("material"),
                                          "PLANT": line.get("plant"), "STGE_LOC": line.get("storageLocation"), "QUANTITY": quantity(line.get("qty")),
                                          "PO_UNIT": line.get("uom") or "EA", "NET_PRICE": amount(line.get("priceMinor"))})
    elif message_type == "GOODS_RECEIPT":
        body = _seg("E1BP2017_GM_HEAD_01", {"PSTNG_DATE": _ymd(today), "DOC_DATE": _ymd(today), "REF_DOC_NO": trim(p.get("gr"), 16), "HEADER_TXT": trim(ref, 25)})
        body += _seg("E1BP2017_GM_CODE", {"GM_CODE": "01"})
        for line in data.get("lines", []):
            body += _seg("E1BP2017_GM_ITEM_CREATE", {"MATERIAL": line["material"], "PLANT": line["plant"], "STGE_LOC": line.get("storageLocation"),
                                                     "MOVE_TYPE": gr_movement(p), "ENTRY_QNT": quantity(line["qty"]), "ENTRY_UOM": line.get("uom") or "EA",
                                                     "PO_NUMBER": line["po"], "PO_ITEM": item_number(line["poItem"]), "MVT_IND": "B",
                                                     "BATCH": line.get("batch")})
    elif message_type == "STOCK_POSTING":
        # data: {"code": goods movement code, "items": stock_items(...), "objectType": PIC object type}; ctx["reference"] is this document's reference
        codes = ctx.get("stock_type_codes") or STOCK_TYPE_IDOC
        posted = date.fromisoformat(p["postingDate"]) if p.get("postingDate") else today
        body = _seg("E1BP2017_GM_HEAD_01", {"PSTNG_DATE": _ymd(posted), "DOC_DATE": _ymd(posted),
                                            "REF_DOC_NO": trim(stock_number(data.get("objectType", ""), p), 16), "HEADER_TXT": trim(ref, 25)})
        body += _seg("E1BP2017_GM_CODE", {"GM_CODE": data["code"]})
        for it in data["items"]:
            body += _seg("E1BP2017_GM_ITEM_CREATE", {"MATERIAL": it["material"], "PLANT": it["plant"], "STGE_LOC": it["sloc"], "BATCH": it["batch"],
                                                     "MOVE_TYPE": it["movement"], "STCK_TYPE": codes.get(it["stockType"]), "ENTRY_QNT": it["qty"],
                                                     "ENTRY_UOM": it["uom"], "MOVE_PLANT": it["toPlant"], "MOVE_STLOC": it["toSloc"],
                                                     "MOVE_BATCH": it["toBatch"], "COSTCENTER": it["costCenter"], "WBS_ELEM": it["wbs"],
                                                     "MOVE_REAS": it["reasonCode"], "ITEM_TEXT": it["text"]})
    elif message_type in ("SUPPLIER_INVOICE", "SUPPLIER_CREDIT_MEMO"):
        credit = message_type == "SUPPLIER_CREDIT_MEMO"
        number = p.get("creditNote") if credit else p.get("invoice")
        body = _seg("E1EDK01", {"BELNR": trim(number, 35), "CURCY": "INR", "BSART": "CRME" if credit else "INVO"})
        body += _seg("E1EDKA1", {"PARVW": "RS", "PARTN": ctx["vendor"]}) + _seg("E1EDK03", {"IDDAT": "012", "DATUM": _ymd(today)})
        body += _seg("E1EDS01", {"SUMID": "011", "SUMME": amount(p.get("grossMinor")), "SUNIT": "INR"})
        for n, it in enumerate(data.get("items", []), start=1):
            body += _seg("E1EDP02", {"QUALF": "001", "BELNR": it.get("po"), "ZEILE": item_number(it["poItem"]) if it.get("poItem") else None}) \
                if it.get("po") else _seg("E1EDP19", {"QUALF": "001", "IDTNR": it.get("glAccount")})
        body += _seg("E1EDK02", {"QUALF": "009", "BELNR": trim(ref, 35)})
    elif message_type == "SUPPLIER_MASTER":
        s = data["supplier"]
        body = _seg("E1LFA1M", {"LIFNR": "", "NAME1": trim(s["name"], 35), "SORTL": trim(s["code"], 10), "LAND1": "IN", "ORT01": trim((s.get("address") or {}).get("city"), 35),
                                "PSTLZ": trim((s.get("address") or {}).get("pincode"), 10), "STCD3": s.get("gstin"), "SPRAS": "E"})
        if s.get("bank"):
            body += _seg("E1LFBKM", {"BANKS": "IN", "BANKL": trim(s["bank"]["ifsc"], 15), "BANKN": trim(s["bank"]["account"], 18), "KOINH": trim(s["bank"].get("holder"), 60)})
    elif message_type == "MATERIAL_MASTER":
        body = _seg("E1MARAM", {"MATNR": trim(p.get("material"), 18), "MTART": ctx.get("product_type") or "ROH", "MEINS": p.get("uom") or "EA", "MATKL": trim(p.get("group"), 9)})
        body += _seg("E1MAKTM", {"SPRAS": "E", "MAKTX": trim(p.get("description"), 40)})
    else:  # PAYMENT
        body = _seg("E1FIKPF", {"BUKRS": ctx["company"], "BLART": "KZ", "BLDAT": _ymd(today), "BUDAT": _ymd(today), "WAERS": "INR",
                                "XBLNR": trim(p.get("payment"), 16), "BKTXT": trim(ref, 25)})
        body += _seg("E1FISEG", {"BUZEI": "001", "BSCHL": "25", "KOART": "K", "LIFNR": ctx["vendor"], "WRBTR": amount(p.get("amountMinor")), "ZUONR": trim(p.get("invoiceErp"), 18)})
        body += _seg("E1FISEG", {"BUZEI": "002", "BSCHL": "50", "KOART": "S", "HKONT": ctx.get("bank_gl_account"), "WRBTR": amount(p.get("amountMinor"))})
    return f'<?xml version="1.0" encoding="UTF-8"?><{basic}><IDOC BEGIN="1">{_control(basic, message, ctx, ref)}{body}</IDOC></{basic}>'
