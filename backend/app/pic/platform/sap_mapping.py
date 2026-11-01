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
  SUPPLIER_MASTER       API_BUSINESS_PARTNER          A_BusinessPartner (category 2 = organisation) with roles FLVN00/FLVN01,
                        tax number IN3 (GSTIN), bank, address, e-mail; reference in SearchTerm1 (20 chars); number = BusinessPartner.
                        Changes PATCH the partner (tax number, address, e-mail).
  MATERIAL_MASTER       API_PRODUCT_SRV               A_Product with to_Description; the key is the material number (Product).
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
    "GOODS_RECEIPT": "API_MATERIAL_DOCUMENT_SRV",
    "SUPPLIER_MASTER": "API_BUSINESS_PARTNER",
    "MATERIAL_MASTER": "API_PRODUCT_SRV",
}
MESSAGE_TYPES = ("PURCHASE_REQUISITION", "PURCHASE_ORDER", "GOODS_RECEIPT", "SUPPLIER_INVOICE", "SUPPLIER_CREDIT_MEMO",
                 "SUPPLIER_MASTER", "MATERIAL_MASTER", "PAYMENT")
# message type -> (IDoc basic type, message type)
IDOC_TYPES = {"PURCHASE_ORDER": ("PORDCR105", "PORDCR1"), "GOODS_RECEIPT": ("MBGMCR03", "MBGMCR"), "SUPPLIER_INVOICE": ("INVOIC02", "INVOIC"),
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


def goods_receipt(p: dict, ctx: dict, items: list[dict]) -> Spec:
    v = ctx["version"]
    rows = []
    for it in items:
        row = {"Material": it["material"], "Plant": it["plant"], "StorageLocation": it.get("storageLocation"), "GoodsMovementType": "101",
               "PurchaseOrder": it["po"], "PurchaseOrderItem": item_number(it["poItem"]), "QuantityInEntryUnit": quantity(it["qty"]),
               "EntryUnit": it.get("uom") or "EA", "GoodsMovementRefDocType": "B", "Batch": it.get("batch") or None}
        rows.append({k: x for k, x in row.items() if x not in (None, "")})
    body = {"PostingDate": odata_date(ctx["today"], v), "DocumentDate": odata_date(ctx["today"], v), "GoodsMovementCode": "01",
            "MaterialDocumentHeaderText": trim(ctx["reference"], 25), "ReferenceDocument": trim(p.get("gr"), 16),
            "to_MaterialDocumentItem": {"results": rows} if v == 2 else rows}
    return Spec(SERVICES["GOODS_RECEIPT"], "A_MaterialDocumentHeader", body, "MaterialDocumentHeaderText", trim(ctx["reference"], 25), "MaterialDocument",
                select="MaterialDocument,MaterialDocumentYear")


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
                                                     "MOVE_TYPE": "101", "ENTRY_QNT": quantity(line["qty"]), "ENTRY_UOM": line.get("uom") or "EA",
                                                     "PO_NUMBER": line["po"], "PO_ITEM": item_number(line["poItem"]), "MVT_IND": "B"})
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
