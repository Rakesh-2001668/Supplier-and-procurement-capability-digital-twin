"""Inbound pulls from SAP S/4HANA over OData (TD §12.1): masters, stock, open POs, payment status, planned orders.

Every pull returns ``PullResult``: rows shaped like the SAP tables the ERP loader already understands (LFA1, ADRC, LFB1, LFBK,
MARA, MAKT, MARC, MBEW, T001W, CSKS, PRPS) or plain dictionaries for the object kinds that are applied directly. Delta pulls use a
cursor (an ISO date or timestamp string): the next pull asks SAP only for objects changed since then, minus one day of overlap
(change detection by content hash in ``erp_sync`` removes the repeats).

Services and entity sets assumed (released APIs on SAP API Business Hub unless marked custom):
  VENDORS         API_BUSINESS_PARTNER      A_BusinessPartner (LastChangeDate for the delta), A_Supplier $expand=to_SupplierCompany,
                                            A_BusinessPartnerBank, A_BusinessPartnerAddress $expand=to_EmailAddress
  MATERIALS       API_PRODUCT_SRV           A_Product $expand=to_Description,to_Plant,to_Valuation (LastChangeDate for the delta);
                                            the HSN/SAC is ConsumptionTaxCtrlCode of the plant data
  PLANTS          API_PLANT_SRV             A_Plant
  COST_OBJECTS    API_COSTCENTER_SRV        A_CostCenter $expand=to_Text; API_ENTERPRISE_PROJECT_SRV A_EnterpriseProjectElement
  STOCK           API_MATERIAL_STOCK_SRV    A_MatlStkInAcctMod (unrestricted-use stock per plant and storage location)
  OPEN_POS        API_PURCHASEORDER_PROCESS_SRV  A_PurchaseOrder $expand=to_PurchaseOrderItem (LastChangeDateTime for the delta)
  PAYMENT_STATUS  API_OPLACCTGDOCITEMCUBE_SRV    OperationalAcctgDocItem (cleared vendor items: ClearingDate, ClearingAccountingDocument)
  PLANNED_ORDERS  API_PLANNED_ORDERS (customer-enabled)  PlannedOrder  (service name: PIC_ERP_SAP_S4_PLANNED_ORDER_SERVICE)
Payment terms are not read from SAP: ``PIC_ERP_SAP_S4_TERMS_MAP`` maps SAP terms keys to PIC terms, e.g. ``ZN30=30,Z210=30:2``
(days, or days:cash-discount-percent).
"""
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app.pic.platform.sap_odata import ODataClient, SapODataError, literal

KINDS = ("VENDORS", "MATERIALS", "COST_OBJECTS", "PLANTS", "STOCK", "OPEN_POS", "PAYMENT_STATUS", "PLANNED_ORDERS")
SERVICE = {"BP": "API_BUSINESS_PARTNER", "PRODUCT": "API_PRODUCT_SRV", "PLANT": "API_PLANT_SRV", "COST": "API_COSTCENTER_SRV",
           "PROJECT": "API_ENTERPRISE_PROJECT_SRV", "STOCK": "API_MATERIAL_STOCK_SRV", "PO": "API_PURCHASEORDER_PROCESS_SRV",
           "ACCT": "API_OPLACCTGDOCITEMCUBE_SRV"}


@dataclass
class PullResult:
    kind: str
    tables: dict = field(default_factory=dict)      # SAP table name -> rows (masters)
    rows: list = field(default_factory=list)        # plain rows (stock, open POs, payment status, planned orders, plants, cost objects)
    cursor: Optional[str] = None
    pulled: int = 0
    notes: list = field(default_factory=list)


def _date(value) -> str:
    """OData date value (``/Date(ms)/``, ISO or None) as YYYY-MM-DD."""
    if value in (None, ""):
        return ""
    text = str(value)
    if text.startswith("/Date("):
        ms = int(text[6:].split(")")[0].split("+")[0].split("-")[0] or 0)
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()
    return text[:10]


def _flag(value) -> str:
    return "X" if value in (True, "X", "true", "True") else ""


def _since_filter(field_name: str, since: Optional[str], version: int) -> Optional[str]:
    if not since:
        return None
    d = (date.fromisoformat(since[:10]) - timedelta(days=1)).isoformat()
    return f"{field_name} ge datetime'{d}T00:00:00'" if version == 2 else f"{field_name} ge {d}T00:00:00Z"


def terms_map() -> dict:
    out = {}
    for pair in (os.environ.get("PIC_ERP_SAP_S4_TERMS_MAP") or "").split(","):
        if "=" in pair:
            key, value = pair.split("=", 1)
            days, _, discount = value.partition(":")
            out[key.strip()] = (days.strip(), discount.strip() or "0")
    return out


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def pull(client: ODataClient, kind: str, since: Optional[str], company: str, today: date) -> PullResult:
    kind = kind.upper()
    if kind not in KINDS:
        raise ValueError(f"unknown object kind {kind}; known: {', '.join(KINDS)}")
    return globals()[f"_pull_{kind.lower()}"](client, since, company, today)


# ---------------------------------------------------------------- masters
def _pull_vendors(client: ODataClient, since, company, today) -> PullResult:
    svc = SERVICE["BP"]
    flt = _since_filter("LastChangeDate", since, client.version)
    changed = [r["BusinessPartner"] for r in client.query(svc, "A_BusinessPartner", filter=flt, select="BusinessPartner,LastChangeDate")] if flt else None
    suppliers = client.query(svc, "A_Supplier", expand="to_SupplierCompany") if changed is None else []
    if changed is not None:
        # one $batch per 20 partners instead of one request per supplier
        from app.pic.platform.sap_odata import BatchOp
        for group in _chunks(changed, 20):
            results = client.batch(svc, [BatchOp("GET", f"A_Supplier({literal(bp)})?$expand=to_SupplierCompany&$format=json") for bp in group])
            suppliers.extend(r.data for r in results if r.ok and isinstance(r.data, dict))
    codes = [s["Supplier"] for s in suppliers]
    terms = terms_map()
    lfa1, lfb1, lfbk, adrc, t052 = [], [], [], [], []
    for s in suppliers:
        number = s["Supplier"]
        lfa1.append({"LIFNR": number, "NAME1": s.get("SupplierName") or s.get("SupplierFullName") or "", "NAME2": "", "STCD3": s.get("TaxNumber3") or "",
                     "J_1IPANNO": s.get("BusinessPartnerPanNumber") or "", "KTOKK": s.get("SupplierAccountGroup") or "", "SPERR": _flag(s.get("PostingIsBlocked")),
                     "SPERM": _flag(s.get("PurchasingIsBlocked")), "LOEVM": _flag(s.get("DeletionIndicator")), "ADRNR": number,
                     "ERDAT": _date(s.get("CreationDate"))})
        companies = (s.get("to_SupplierCompany") or {})
        companies = companies.get("results", companies) if isinstance(companies, dict) else companies
        for c in companies or []:
            if c.get("CompanyCode") != company:
                continue
            key = c.get("PaymentTerms") or ""
            lfb1.append({"LIFNR": number, "BUKRS": company, "ZTERM": key, "SPERR": "" if not c.get("PaymentBlockingReason") else "X",
                         "LOEVM": _flag(c.get("DeletionIndicator"))})
            if key in terms and not any(t["ZTERM"] == key for t in t052):
                t052.append({"ZTERM": key, "ZTAG1": terms[key][0], "ZPRZ1": terms[key][1]})
    if codes:
        for group in _chunks(codes, 20):
            flt_banks = " or ".join(f"BusinessPartner eq {literal(c)}" for c in group)
            for b in client.query(svc, "A_BusinessPartnerBank", filter=flt_banks):
                lfbk.append({"LIFNR": b["BusinessPartner"], "BANKL": b.get("BankNumber") or "", "BANKN": b.get("BankAccount") or "",
                             "KOINH": b.get("BankAccountHolderName") or ""})
            flt_addr = " or ".join(f"BusinessPartner eq {literal(c)}" for c in group)
            for a in client.query(svc, "A_BusinessPartnerAddress", filter=flt_addr, expand="to_EmailAddress"):
                emails = (a.get("to_EmailAddress") or {})
                emails = emails.get("results", emails) if isinstance(emails, dict) else emails
                adrc.append({"ADDRNUMBER": a["BusinessPartner"], "STREET": a.get("StreetName") or "", "STR_SUPPL1": a.get("StreetPrefixName") or "",
                             "CITY1": a.get("CityName") or "", "POST_CODE1": a.get("PostalCode") or "", "COUNTRY": a.get("Country") or "IN",
                             "SMTP_ADDR": (emails[0].get("EmailAddress") if emails else "") or ""})
    return PullResult("VENDORS", tables={"LFA1": lfa1, "LFB1": lfb1, "LFBK": lfbk, "ADRC": adrc, "T052": t052}, pulled=len(lfa1),
                      cursor=today.isoformat())


def _pull_materials(client: ODataClient, since, company, today) -> PullResult:
    flt = _since_filter("LastChangeDate", since, client.version)
    products = client.query(SERVICE["PRODUCT"], "A_Product", filter=flt, expand="to_Description,to_Plant,to_Valuation")
    mara, makt, marc, mbew = [], [], [], []
    for p in products:
        number = p["Product"]
        mara.append({"MATNR": number, "MTART": p.get("ProductType") or "", "MATKL": p.get("ProductGroup") or "", "MEINS": p.get("BaseUnit") or "",
                     "LVORM": _flag(p.get("IsMarkedForDeletion")), "MFRPN": p.get("ManufacturerPartNmbr") or ""})
        descriptions = p.get("to_Description") or {}
        descriptions = descriptions.get("results", descriptions) if isinstance(descriptions, dict) else descriptions
        for d in descriptions or []:
            makt.append({"MATNR": number, "SPRAS": "E" if d.get("Language") in ("EN", "E") else d.get("Language"), "MAKTX": d.get("ProductDescription") or ""})
        plants = p.get("to_Plant") or {}
        plants = plants.get("results", plants) if isinstance(plants, dict) else plants
        for pl in plants or []:
            marc.append({"MATNR": number, "WERKS": pl.get("Plant"), "STEUC": pl.get("ConsumptionTaxCtrlCode") or "", "DISMM": pl.get("MRPType") or "ND",
                         "DISLS": pl.get("LotSizingProcedure") or "EX", "BSTFE": pl.get("FixedLotSizeQuantity") or "", "BSTMI": pl.get("MinimumLotSizeQuantity") or "",
                         "BSTMA": pl.get("MaximumLotSizeQuantity") or "", "EISBE": pl.get("SafetyStockQuantity") or "", "PLIFZ": pl.get("PlannedDeliveryDurationInDays") or "",
                         "WEBAZ": pl.get("GoodsReceiptDuration") or "", "LVORM": _flag(pl.get("IsMarkedForDeletion"))})
        valuations = p.get("to_Valuation") or {}
        valuations = valuations.get("results", valuations) if isinstance(valuations, dict) else valuations
        for v in valuations or []:
            mbew.append({"MATNR": number, "BWKEY": v.get("ValuationArea"), "VPRSV": v.get("PriceControl") or "S", "STPRS": v.get("StandardPrice") or "",
                         "VERPR": v.get("MovingAveragePrice") or "", "PEINH": v.get("PriceUnitQty") or "1", "BKLAS": v.get("ValuationClass") or ""})
    return PullResult("MATERIALS", tables={"MARA": mara, "MAKT": makt, "MARC": marc, "MBEW": mbew}, pulled=len(mara), cursor=today.isoformat())


# ---------------------------------------------------------------- organisation
def _pull_plants(client: ODataClient, since, company, today) -> PullResult:
    rows = [{"WERKS": p["Plant"], "NAME1": p.get("PlantName") or p["Plant"], "BUKRS": company, "REGIO": p.get("Region") or "",
             "GSTIN": p.get("TaxNumber3") or ""} for p in client.query(SERVICE["PLANT"], "A_Plant")]
    return PullResult("PLANTS", rows=rows, pulled=len(rows), cursor=today.isoformat())


def _pull_cost_objects(client: ODataClient, since, company, today) -> PullResult:
    rows = []
    for c in client.query(SERVICE["COST"], "A_CostCenter", filter=f"CompanyCode eq {literal(company)}", expand="to_Text"):
        texts = c.get("to_Text") or {}
        texts = texts.get("results", texts) if isinstance(texts, dict) else texts
        name = (texts[0].get("CostCenterName") if texts else None) or c.get("CostCenterName") or c["CostCenter"]
        rows.append({"type": "COST_CENTER", "code": c["CostCenter"], "name": name, "validTo": _date(c.get("ValidityEndDate"))})
    for w in client.query(SERVICE["PROJECT"], "A_EnterpriseProjectElement", filter=f"CompanyCode eq {literal(company)}"):
        rows.append({"type": "WBS", "code": w["ProjectElement"], "name": w.get("ProjectElementDescription") or w["ProjectElement"], "validTo": ""})
    return PullResult("COST_OBJECTS", rows=rows, pulled=len(rows), cursor=today.isoformat())


# ---------------------------------------------------------------- transactional
def _pull_stock(client: ODataClient, since, company, today) -> PullResult:
    rows = []
    for s in client.query(SERVICE["STOCK"], "A_MatlStkInAcctMod", filter="InventoryStockType eq '01'"):
        rows.append({"material": s["Material"], "plant": s["Plant"], "storageLocation": s.get("StorageLocation") or "0001",
                     "qty": s.get("MatlWrhsStkQtyInMatBaseUnit") or "0", "uom": s.get("MaterialBaseUnit") or "", "stockType": "UNRESTRICTED"})
    return PullResult("STOCK", rows=rows, pulled=len(rows), cursor=today.isoformat())


def _pull_open_pos(client: ODataClient, since, company, today) -> PullResult:
    flt = _since_filter("LastChangeDateTime", since, client.version)
    flt = f"CompanyCode eq {literal(company)}" + (f" and {flt}" if flt else "")
    rows = []
    for po in client.query(SERVICE["PO"], "A_PurchaseOrder", filter=flt, expand="to_PurchaseOrderItem"):
        items = po.get("to_PurchaseOrderItem") or {}
        items = items.get("results", items) if isinstance(items, dict) else items
        rows.append({"po": po["PurchaseOrder"], "supplier": po.get("Supplier") or "", "deleted": po.get("PurchasingDocumentDeletionCode") == "L",
                     "reference": po.get("CorrespncExternalReference") or "", "currency": po.get("DocumentCurrency") or "INR",
                     "items": [{"item": str(int(i["PurchaseOrderItem"])), "material": i.get("Material") or "", "plant": i.get("Plant") or "",
                                "qty": i.get("OrderQuantity") or "0", "price": i.get("NetPriceAmount") or "0",
                                "deleted": i.get("PurchasingDocumentDeletionCode") == "L", "delivered": bool(i.get("IsCompletelyDelivered")),
                                "invoiced": bool(i.get("IsFinallyInvoiced"))} for i in items or []]})
    return PullResult("OPEN_POS", rows=rows, pulled=len(rows), cursor=today.isoformat())


def _pull_payment_status(client: ODataClient, since, company, today) -> PullResult:
    flt = f"CompanyCode eq {literal(company)} and FinancialAccountType eq 'K' and ClearingDate ne null"
    since_filter = _since_filter("ClearingDate", since, client.version)
    rows = []
    for item in client.query(SERVICE["ACCT"], "OperationalAcctgDocItem", filter=flt + (f" and {since_filter}" if since_filter else "")):
        rows.append({"document": item["AccountingDocument"], "fiscalYear": item.get("FiscalYear") or "", "supplier": item.get("Supplier") or "",
                     "clearingDate": _date(item.get("ClearingDate")), "clearingDocument": item.get("ClearingAccountingDocument") or "",
                     "amount": item.get("AmountInCompanyCodeCurrency") or "0"})
    return PullResult("PAYMENT_STATUS", rows=rows, pulled=len(rows), cursor=today.isoformat())


def _pull_planned_orders(client: ODataClient, since, company, today) -> PullResult:
    service = os.environ.get("PIC_ERP_SAP_S4_PLANNED_ORDER_SERVICE") or "API_PLANNED_ORDERS"
    flt = _since_filter("LastChangeDateTime", since, client.version)
    rows = []
    for o in client.query(service, "PlannedOrder", filter=flt):
        rows.append({"externalRef": o["PlannedOrder"], "material": o.get("Material") or "", "plant": o.get("ProductionPlant") or o.get("Plant") or "",
                     "qty": o.get("TotalQuantity") or o.get("PlannedTotalQtyInBaseUnit") or "0", "needDate": _date(o.get("PlannedOrderEndDate") or o.get("PlndOrderPlannedEndDate")),
                     "releaseDate": _date(o.get("PlannedOrderStartDate") or o.get("PlndOrderPlannedStartDate"))})
    return PullResult("PLANNED_ORDERS", rows=rows, pulled=len(rows), cursor=today.isoformat())


__all__ = ["KINDS", "PullResult", "pull", "SapODataError"]
