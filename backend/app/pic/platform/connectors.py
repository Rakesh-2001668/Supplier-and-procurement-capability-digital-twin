"""ERP connector framework: SAP S/4HANA, Oracle Fusion, Dynamics 365, Tally Prime, Odoo (TD §12.1).

Every connector declares the PIC message types it maps, the configuration it needs, a health check, ``find`` (query-before-retry
by the PIC reference written into the ERP document) and ``post``. ``platform/integration.py`` drives them with the exactly-once
outbox: any ``ConnectorError`` (timeout, not configured, rejected) goes to RETRY with back-off and DEAD_LETTER after 8 attempts.

SAP_S4 is the S/4HANA sandbox simulator (``erp_document`` table) and stays the default target. The other connectors call the
vendor API over HTTPS when configured:
    PIC_ERP_<SYSTEM>_URL            base URL of the ERP / gateway
    PIC_ERP_<SYSTEM>_USER, _PASSWORD  basic credentials (Odoo: login and API key), or
    PIC_ERP_<SYSTEM>_TOKEN          bearer token (e.g. an Entra ID access token for Dynamics 365)
    PIC_ERP_<SYSTEM>_COMPANY_MAP    PIC company code → ERP company, e.g. "1000=USMF,2000=DEMF" (business unit, legal entity, Tally company)
    PIC_ERP_ODOO_DB                 Odoo database name
    PIC_ERP_<SYSTEM>_TIMEOUT        seconds, default 20
Field mappings are the vendors' standard entities; confirm them against the customer's ERP configuration at onboarding.
"""
import base64
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.models import IntegrationMessage
from app.pic.platform import clock, integration, sap_customizing, sap_defaults, sap_mapping, sap_odata, sap_pull
from app.pic.platform.integration import ConnectorError, ConnectorTimeout

MESSAGE_TYPES = ("SUPPLIER_INVOICE", "SUPPLIER_CREDIT_MEMO", "PURCHASE_ORDER", "GOODS_RECEIPT", "SUPPLIER_MASTER", "MATERIAL_MASTER", "PAYMENT")


class ConnectorNotConfigured(ConnectorError):
    pass


class ConnectorRejected(ConnectorError):
    pass


class ConnectorUnsupported(ConnectorError):
    pass


@dataclass
class RemoteDocument:
    doc_no: str


def reference(key: str, length: int = 20) -> str:
    """The PIC idempotency key as it is written into an ERP reference field (shortened with a digest when too long)."""
    return key if len(key) <= length else "PIC" + hashlib.sha256(key.encode()).hexdigest()[: length - 3].upper()


def _http(method: str, url: str, *, headers: Optional[dict] = None, body: Optional[bytes] = None, timeout: float = 20) -> tuple[int, str]:
    """One HTTP call. Network failures are timeouts (retried); HTTP errors are rejections (retried, then dead-lettered)."""
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL from operator configuration
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")[:500]
        raise ConnectorRejected(f"HTTP {exc.code} from {url.split('?')[0]}: {text}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ConnectorTimeout(f"{url.split('?')[0]} not reachable: {exc}")


def _json(text: str, system: str) -> dict:
    """An ERP's JSON answer; an unreadable or non-object answer is a rejection (retried, then dead-lettered), never a crash."""
    try:
        answer = json.loads(text or "{}")
    except ValueError:
        raise ConnectorRejected(f"{system} answered with unreadable JSON: {(text or '')[:200]}")
    if not isinstance(answer, dict):
        raise ConnectorRejected(f"{system} answered with unexpected JSON: {(text or '')[:200]}")
    return answer


def _xml(text: str, system: str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(text)
    except ElementTree.ParseError:
        raise ConnectorRejected(f"{system} answered with unreadable XML: {(text or '')[:200]}")


# ---------------------------------------------------------------- base
class Connector:
    system = ""
    name = ""
    protocol = ""
    message_types: tuple[str, ...] = ()
    credentials = "basic|token"  # basic|token, basic, token or none
    extra_settings: tuple[str, ...] = ()
    needs_company_map = True
    simulator = False

    def env(self, key: str) -> Optional[str]:
        value = os.environ.get(f"PIC_ERP_{self.system}_{key}")
        return value.strip() if value and value.strip() else None

    def requirements(self) -> list[dict]:
        def item(key: str, required: bool = True, secret: bool = False) -> dict:
            return {"name": f"PIC_ERP_{self.system}_{key}", "present": self.env(key) is not None, "required": required, "secret": secret}

        items = [item("URL")]
        if self.credentials in ("basic|token", "basic"):
            alt = self.credentials == "basic|token"
            items += [item("USER", not alt), item("PASSWORD", not alt, secret=True)]
        if self.credentials in ("basic|token", "token"):
            items.append(item("TOKEN", self.credentials == "token", secret=True))
        items += [item(k) for k in self.extra_settings]
        items.append(item("COMPANY_MAP", self.needs_company_map))
        return items

    def missing(self) -> list[str]:
        missing = [r["name"] for r in self.requirements() if r["required"] and not r["present"]]
        if self.credentials == "basic|token" and not self.env("TOKEN") and not (self.env("USER") and self.env("PASSWORD")):
            missing.append(f"PIC_ERP_{self.system}_USER/_PASSWORD or PIC_ERP_{self.system}_TOKEN")
        return missing

    def configured(self) -> bool:
        return not self.missing()

    def company(self, code: Optional[str]) -> str:
        mapping = {}
        for pair in (self.env("COMPANY_MAP") or "").split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                mapping[k.strip()] = v.strip()
        code = code or "1000"
        if code not in mapping and self.needs_company_map:
            raise ConnectorRejected(f"PIC company code {code} has no mapping in PIC_ERP_{self.system}_COMPANY_MAP")
        return mapping.get(code, code)

    def _require(self, message: IntegrationMessage) -> None:
        if not self.configured():
            raise ConnectorNotConfigured(f"{self.system} connector is not configured: set {', '.join(self.missing())}")
        if message.message_type not in self.message_types:
            raise ConnectorUnsupported(f"{self.system} connector does not map {message.message_type}")

    def _headers(self, content_type: str = "application/json") -> dict:
        headers = {"accept": "application/json", "content-type": content_type}
        if self.env("TOKEN"):
            headers["authorization"] = f"Bearer {self.env('TOKEN')}"
        elif self.env("USER"):
            raw = f"{self.env('USER')}:{self.env('PASSWORD') or ''}".encode()
            headers["authorization"] = "Basic " + base64.b64encode(raw).decode()
        return headers

    def _call(self, method: str, path: str, payload=None, content_type: str = "application/json", raw: Optional[bytes] = None) -> tuple[int, str]:
        body = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
        timeout = float(self.env("TIMEOUT") or 20)
        return _http(method, f"{self.env('URL').rstrip('/')}{path}", headers=self._headers(content_type), body=body, timeout=timeout)

    def skip_reason(self, session: Session, message_type: str, payload: dict) -> Optional[str]:
        """Why a document this connector maps is deliberately not sent (e.g. a legal document an ERP has no object for), else None.
        Asked before a message is queued; a skip is not an error."""
        return None

    # interface used by integration.process
    def find(self, session: Session, message: IntegrationMessage) -> Optional[RemoteDocument]:
        return None

    def post(self, session: Session, message: IntegrationMessage) -> str:
        raise NotImplementedError

    def after_post(self) -> None:
        return None

    def pull(self, kind: str, since: Optional[str] = None, company_code: Optional[str] = None):
        """Inbound read (live ERP sync, ``services/erp_sync``): connectors without a read interface say so."""
        raise ConnectorUnsupported(f"{self.system} connector has no inbound read interface; use the file drop (PIC_ERP_SYNC_DROP_DIR)")

    def health(self) -> dict:
        if not self.configured():
            return {"healthy": False, "detail": f"not configured: set {', '.join(self.missing())}"}
        try:
            status, _ = self._call("GET", self.health_path())
            return {"healthy": 200 <= status < 300, "detail": f"HTTP {status}"}
        except ConnectorError as exc:
            return {"healthy": False, "detail": str(exc)}

    def health_path(self) -> str:
        return "/"

    def describe(self) -> dict:
        return {"system": self.system, "name": self.name, "protocol": self.protocol, "simulator": self.simulator,
                "messageTypes": list(self.message_types), "configuration": self.requirements(), "configured": self.configured(),
                "missing": self.missing()}


# ---------------------------------------------------------------- SAP S/4HANA (sandbox simulator)
class SapS4Simulator(Connector):
    """Wraps ``integration.SapS4Connector`` so the simulator, its fault injection and document numbering are unchanged."""
    system = "SAP_S4"
    name = "SAP S/4HANA (sandbox simulator)"
    protocol = "OData v2 (simulated in erp_document)"
    message_types = tuple(integration.DOC_TYPES)
    credentials = "none"
    needs_company_map = False
    simulator = True

    @property
    def inner(self) -> integration.SapS4Connector:
        return integration.CONNECTORS["SAP_S4"]

    def requirements(self) -> list[dict]:
        return []

    def missing(self) -> list[str]:
        return []

    def find(self, session, message):
        return self.inner.lookup(session, message.idempotency_key)

    def lookup(self, session, external_ref):
        return self.inner.lookup(session, external_ref)

    def post(self, session, message):
        if message.message_type not in integration.DOC_TYPES:
            raise ConnectorUnsupported(f"SAP_S4 simulator does not map {message.message_type}")
        return self.inner.post(session, message)

    def after_post(self):
        return self.inner.after_post()

    def health(self) -> dict:
        return {"healthy": True, "detail": "sandbox simulator (erp_document table)"}


# ---------------------------------------------------------------- SAP S/4HANA: sandbox simulator by default, the real connector when configured
REF_LEN = {"PURCHASE_ORDER": 12, "SUPPLIER_INVOICE": 25, "SUPPLIER_CREDIT_MEMO": 25, "SUPPLIER_DEBIT_MEMO": 25, "GOODS_RECEIPT": 25, "STOCK_POSTING": 25, "SUPPLIER_MASTER": 20,
           "PURCHASE_REQUISITION": 40, "MATERIAL_MASTER": 40, "PAYMENT": 25, "OUTLINE_AGREEMENT": 12, "PAYMENT_REVERSAL": 25, "SCF_FINANCING": 25}
# Message types the simulator maps through the live mapping and validates against the mock SAP customizing (platform/sap_customizing.py).
SIMULATOR_VALIDATED = ("OUTLINE_AGREEMENT", "PAYMENT_REVERSAL", "SCF_FINANCING")
# message type -> (mapping key in sap_mapping.SERVICES, entity set, reference field, number field, select)
SAP_FIND = {
    "PURCHASE_REQUISITION": ("A_PurchaseRequisitionHeader", "PurReqnDescription", "PurchaseRequisition"),
    "PURCHASE_ORDER": ("A_PurchaseOrder", "CorrespncExternalReference", "PurchaseOrder"),
    "SUPPLIER_INVOICE": ("A_SupplierInvoice", "DocumentHeaderText", "SupplierInvoice"),
    "SUPPLIER_CREDIT_MEMO": ("A_SupplierInvoice", "DocumentHeaderText", "SupplierInvoice"),
    "SUPPLIER_DEBIT_MEMO": ("A_SupplierInvoice", "DocumentHeaderText", "SupplierInvoice"),
    "GOODS_RECEIPT": ("A_MaterialDocumentHeader", "MaterialDocumentHeaderText", "MaterialDocument"),
    "STOCK_POSTING": ("A_MaterialDocumentHeader", "MaterialDocumentHeaderText", "MaterialDocument"),
    "SUPPLIER_MASTER": ("A_BusinessPartner", "SearchTerm1", "BusinessPartner"),
}


class SapS4(SapS4Simulator):
    """SAP S/4HANA (TD §12.1). Without ``PIC_ERP_SAP_S4_URL`` (or ``..._IDOC_DIR``) this is the sandbox simulator, exactly as
    before. With it, documents are posted to the real system:

        PIC_ERP_SAP_S4_URL            base URL of the SAP Gateway / ICF host, e.g. https://s4.example.com:44300
        PIC_ERP_SAP_S4_USER, _PASSWORD  basic credentials of the technical user, or PIC_ERP_SAP_S4_TOKEN (bearer / OAuth)
        PIC_ERP_SAP_S4_SAP_CLIENT     SAP client (mandant), sent as ``sap-client``
        PIC_ERP_SAP_S4_ODATA_VERSION  2 (default; the released APIs are OData v2) or 4
        PIC_ERP_SAP_S4_TRANSPORT      odata (default) | idoc (IDoc XML over HTTP, /sap/bc/idoc_xml) | idoc-file (XML into a directory)
        PIC_ERP_SAP_S4_IDOC_DIR       directory of the file port (idoc-file); also PIC_ERP_SAP_S4_IDOC_PARTNER / _IDOC_PORT / _IDOC_RECEIVER
        PIC_ERP_SAP_S4_COMPANY_MAP    PIC company code -> SAP company code, "1000=1710" (unmapped codes are sent unchanged)
        PIC_ERP_SAP_S4_PURCH_ORG, _PURCH_GROUP, _PO_TYPE, _TAX_CODE, _GL_ACCOUNT (invoices without PO), _BANK_GL_ACCOUNT (IDoc payment),
        PIC_ERP_SAP_S4_PAYMENT_SERVICE (custom OData service for outgoing payments and their reversal), _BP_GROUPING, _PRODUCT_TYPE
        PIC_ERP_SAP_S4_JOURNAL_SERVICE (custom OData journal entry service of the supply-chain-finance posting; without it IDoc FIDCCP02)
        PIC_ERP_SAP_S4_TERMS_MAP ("N45=Z045,N30=Z030": PIC payment terms -> SAP terms key of outline agreements; unmapped terms are not sent)
        Outline agreements, payment reversals and SCF postings take their SAP values from the rules SAP-OUTLINE-AGREEMENT,
        SAP-PAYMENT-REVERSAL and SAP-SCF-FINANCING (platform/sap_defaults.py), per company code.
        PIC_ERP_SAP_S4_SCRAP_COST_CENTER (cost centre of a scrapping / goods issue whose PIC document names none), _REASON_MAP ("DAMAGED=0001,EXPIRED=0002":
        PIC scrap reason -> SAP goods movement reason), _STOCK_TYPE_MAP ("QUALITY=02,BLOCKED=03": PIC stock type -> SAP stock type code)
        PIC_ERP_SAP_S4_TIMEOUT / _RETRIES   seconds per call (20) and retries (2) on read errors and gateway overload

    The field mappings and the assumed API shapes are documented in ``sap_mapping.py``; the inbound reads in ``sap_pull.py``.
    """
    name = "SAP S/4HANA"
    credentials = "basic|token"
    SETTINGS = ("SAP_CLIENT", "ODATA_VERSION", "TRANSPORT", "IDOC_DIR", "IDOC_PARTNER", "IDOC_PORT", "IDOC_RECEIVER", "PURCH_ORG", "PURCH_GROUP",
                "PO_TYPE", "TAX_CODE", "GL_ACCOUNT", "BANK_GL_ACCOUNT", "PAYMENT_SERVICE", "BP_GROUPING", "PRODUCT_TYPE", "TERMS_MAP", "TIMEOUT", "RETRIES",
                "SCRAP_COST_CENTER", "REASON_MAP", "STOCK_TYPE_MAP", "JOURNAL_SERVICE")

    # ------------------------------------------------------------ mode and configuration
    @property
    def live(self) -> bool:
        return bool(self.env("URL") or self.env("IDOC_DIR"))

    @property
    def simulator(self) -> bool:  # type: ignore[override]
        return not self.live

    @property
    def protocol(self) -> str:  # type: ignore[override]
        if not self.live:
            return "OData v2 (simulated in erp_document)"
        return {"odata": f"OData v{self.env('ODATA_VERSION') or 2} (released APIs) + CSRF + $batch", "idoc": "IDoc XML over HTTP (/sap/bc/idoc_xml)",
                "idoc-file": "IDoc XML file port"}[self.transport()]

    def transport(self) -> str:
        value = (self.env("TRANSPORT") or ("idoc-file" if self.env("IDOC_DIR") and not self.env("URL") else "odata")).lower()
        if value not in ("odata", "idoc", "idoc-file"):
            raise ConnectorRejected(f"PIC_ERP_SAP_S4_TRANSPORT must be odata, idoc or idoc-file (got {value})")
        return value

    def transport_for(self, message_type: str) -> str:
        value = self.transport()
        if message_type == "PAYMENT" and value == "odata":
            return "odata" if self.env("PAYMENT_SERVICE") else "idoc"
        if message_type == "SCF_FINANCING" and value == "odata":
            return "odata" if self.env("JOURNAL_SERVICE") else "idoc"
        return value

    @property
    def message_types(self) -> tuple:  # type: ignore[override]
        if not self.live:
            return tuple(integration.DOC_TYPES)
        if self.transport() != "odata":
            return tuple(sap_mapping.IDOC_TYPES)
        # the reversal of a returned payment needs the customer's payment service (no released API resets and reverses a clearing)
        return sap_mapping.MESSAGE_TYPES + (sap_mapping.ODATA_SERVICE_TYPES if self.env("PAYMENT_SERVICE") else ())

    def requirements(self) -> list[dict]:
        if not self.live:
            return [{"name": f"PIC_ERP_SAP_S4_{k}", "present": self.env(k) is not None, "required": False, "secret": k in ("PASSWORD", "TOKEN")}
                    for k in ("URL", "USER", "PASSWORD", "TOKEN", "COMPANY_MAP", *self.SETTINGS)]
        out = [{"name": "PIC_ERP_SAP_S4_URL", "present": self.env("URL") is not None, "required": self.transport() != "idoc-file", "secret": False}]
        out += [{"name": f"PIC_ERP_SAP_S4_{k}", "present": self.env(k) is not None, "required": False, "secret": k in ("PASSWORD", "TOKEN")}
                for k in ("USER", "PASSWORD", "TOKEN", "COMPANY_MAP", *self.SETTINGS)]
        return out

    def missing(self) -> list[str]:
        if not self.live:
            return []
        transport = self.transport()
        if transport == "idoc-file":
            return [] if self.env("IDOC_DIR") else ["PIC_ERP_SAP_S4_IDOC_DIR"]
        gaps = [] if self.env("URL") else ["PIC_ERP_SAP_S4_URL"]
        if not self.env("TOKEN") and not (self.env("USER") and self.env("PASSWORD")):
            gaps.append("PIC_ERP_SAP_S4_USER/_PASSWORD or PIC_ERP_SAP_S4_TOKEN")
        return gaps

    def maps(self, message_type: str) -> bool:
        return message_type in self.message_types

    # ------------------------------------------------------------ clients
    def client(self) -> "sap_odata.ODataClient":
        return sap_odata.ODataClient(self.env("URL"), user=self.env("USER"), password=self.env("PASSWORD"), token=self.env("TOKEN"),
                                     sap_client=self.env("SAP_CLIENT"), version=int(self.env("ODATA_VERSION") or 2),
                                     timeout=float(self.env("TIMEOUT") or 20), retries=int(self.env("RETRIES") or 2))

    def idoc_transport(self) -> "sap_odata.IdocTransport":
        file_port = self.transport() == "idoc-file"
        return sap_odata.IdocTransport(url=None if file_port else self.env("URL"), directory=self.env("IDOC_DIR") if file_port else None,
                                       user=self.env("USER"), password=self.env("PASSWORD"), token=self.env("TOKEN"), sap_client=self.env("SAP_CLIENT"),
                                       timeout=float(self.env("TIMEOUT") or 20), retries=int(self.env("RETRIES") or 2))

    # ------------------------------------------------------------ database enrichment (the payload carries PIC keys only)
    def _vendor_number(self, session: Session, code: Optional[str]) -> Optional[str]:
        """SAP vendor / business partner number of a PIC supplier: the ERP number recorded when PIC created it, else its code
        (vendors migrated from SAP keep their SAP number as code)."""
        if not code:
            return None
        from app.pic.models import Supplier
        supplier = session.execute(select(Supplier).where(Supplier.code == code)).scalar_one_or_none()
        if supplier is not None and (supplier.twin_ref or "").startswith("ERP-VENDOR-"):
            return supplier.twin_ref[len("ERP-VENDOR-"):]
        return code

    def _ctx(self, session: Session, message: IntegrationMessage) -> dict:
        p = _payload(message)
        return {"version": 4 if int(self.env("ODATA_VERSION") or 2) == 4 else 2, "company": self.company(p.get("companyCode")),
                "vendor": self._vendor_number(session, p.get("supplier")), "reference": reference(message.idempotency_key, REF_LEN.get(message.message_type, 40)),
                "today": clock.today(), "purch_org": self.env("PURCH_ORG"), "purch_group": self.env("PURCH_GROUP"), "po_type": self.env("PO_TYPE"),
                "tax_code": self.env("TAX_CODE"), "bp_grouping": self.env("BP_GROUPING"), "product_type": self.env("PRODUCT_TYPE"),
                "payment_service": self.env("PAYMENT_SERVICE"), "bank_gl_account": self.env("BANK_GL_ACCOUNT"), "idoc_partner": self.env("IDOC_PARTNER"),
                "idoc_port": self.env("IDOC_PORT"), "idoc_receiver": self.env("IDOC_RECEIVER"),
                "stock_cost_center": self.env("SCRAP_COST_CENTER"), "reason_map": _pairs(self.env("REASON_MAP")),
                "stock_type_codes": _pairs(self.env("STOCK_TYPE_MAP")) or None}

    def _po_lines(self, session: Session, p: dict) -> list[dict]:
        from app.pic.models import Material, PoLine, PurchaseOrder
        po = session.execute(select(PurchaseOrder).where(PurchaseOrder.number == p.get("po"))).scalar_one_or_none()
        rows = {}
        if po is not None:
            for line in session.execute(select(PoLine).where(PoLine.po_id == po.id)).scalars():
                material = session.get(Material, line.material_id) if line.material_id else None
                rows[line.line_no] = (line, material.number if material else None)
        out = []
        for line in p.get("lines", []):
            row, material = rows.get(int(line["line"]), (None, None))
            item = {"line": line["line"], "qty": line["qty"], "priceMinor": line["priceMinor"], "material": material}
            if row is not None:
                item.update(uom=row.uom, plant=row.plant, storageLocation=row.storage_location, needDate=row.need_date.isoformat(),
                            description=row.description, materialGroup=row.material_group)
            out.append(item)
        return out

    def _gr_items(self, session: Session, p: dict) -> list[dict]:
        from app.pic.models import Material, PoLine, PurchaseOrder
        items = []
        for line in p.get("lines", []):
            po_line = session.get(PoLine, uuid.UUID(str(line["poLine"])))
            if po_line is None:
                raise ConnectorRejected(f"PO line {line['poLine']} of goods receipt {p.get('gr')} no longer exists")
            po = session.get(PurchaseOrder, po_line.po_id)
            if not po.erp_doc_no:
                raise ConnectorRejected(f"{po.number} has no SAP purchase order number yet: the goods receipt follows once the PO is posted")
            material = session.get(Material, po_line.material_id) if po_line.material_id else None
            if material is None:
                raise ConnectorRejected(f"{po.number} line {po_line.line_no} has no material: a goods movement needs one")
            items.append({"material": material.number, "plant": po_line.plant,
                          "storageLocation": line.get("storageLocation") or po_line.storage_location, "po": po.erp_doc_no,
                          "poItem": po_line.line_no, "qty": line["accepted"], "uom": po_line.uom, "batch": line.get("batch") or None})
        items = [i for i in items if Decimal(str(i["qty"])) > 0]
        if not items and p.get("movement") == "102":
            # Older reversal messages carried no lines: there is nothing a live system could post against (retry dead-letters it, visible).
            raise ConnectorRejected(f"reversal of goods receipt {p.get('gr')} carries no lines: post the 102 in SAP against {p.get('reverses')}")
        try:
            sap_mapping.gr_movement(p)
        except ValueError as exc:
            raise ConnectorRejected(f"goods receipt {p.get('gr')}: {exc}")
        return items

    def _stock_items(self, session: Session, message: IntegrationMessage, ctx: dict) -> list[dict]:
        """Material-document items of an inventory message (stock posting, count differences, reservation issue). The payload carries PIC keys
        only; the unit of measure comes from the material master. What cannot be expressed in SAP is a rejection (retried, then dead-lettered)."""
        from app.pic.models import Material
        p = _payload(message)
        if p.get("reversalOf"):
            raise ConnectorRejected(f"{message.object_ref}: PIC never reverses a posted inventory document and the SAP mapping has no reversal "
                                    "(post the correction as a new document)")
        numbers = {line.get("material") for line in p.get("lines") or [] if line.get("material")}
        uoms = {m.number: m.base_uom for m in session.execute(select(Material).where(Material.number.in_(numbers or {""}))).scalars()}
        try:
            return sap_mapping.stock_items(message.object_type, p, uoms, ctx)
        except ValueError as exc:
            raise ConnectorRejected(f"{message.object_ref}: {exc}")

    def _stock_refs(self, message: IntegrationMessage) -> list[str]:
        """The PIC references of the material documents of an inventory message (one per goods movement code)."""
        codes = sap_mapping.stock_codes(_payload(message))
        base = reference(message.idempotency_key, REF_LEN["STOCK_POSTING"])
        return [sap_mapping.stock_reference(base, code, len(codes)) for code in codes]

    def _post_stock(self, session: Session, client, message: IntegrationMessage, ctx: dict) -> str:
        """OData: one material document per goods movement code. A document already in SAP (an earlier attempt failed after the first of two)
        is reused, never created again."""
        specs = sap_mapping.stock_posting(message.object_type, _payload(message), ctx, self._stock_items(session, message, ctx))
        numbers = []
        for spec in specs:
            rows = client.query(spec.service, spec.entity_set, filter=f"{spec.reference_field} eq {sap_odata.literal(spec.reference)}", select=spec.number_field, top=1)
            number = rows[0].get(spec.number_field) if rows else None
            if not number:
                entity = client.create(spec.service, spec.entity_set, spec.body)
                number = entity.get(spec.number_field)
            if not number:
                raise ConnectorRejected(f"SAP accepted the {message.message_type} but returned no {spec.number_field}")
            numbers.append(str(number))
        return "/".join(numbers)

    def _invoice_items(self, session: Session, message: IntegrationMessage, scale: Optional[Decimal] = None) -> list[dict]:
        from app.pic.models import Invoice, InvoiceLine, PoLine, PurchaseOrder
        invoice = session.get(Invoice, message.object_id)
        if invoice is None:
            raise ConnectorRejected(f"invoice {message.object_ref} not found")
        out = []
        for line in session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id).order_by(InvoiceLine.line_no)).scalars():
            net = int((Decimal(line.net_minor) * scale).to_integral_value()) if scale is not None else line.net_minor
            po_line = session.get(PoLine, line.po_line_id) if line.po_line_id else None
            po = session.get(PurchaseOrder, po_line.po_id) if po_line is not None else None
            if po is not None and po.erp_doc_no:
                out.append({"po": po.erp_doc_no, "poItem": po_line.line_no, "netMinor": net, "qty": line.qty, "uom": po_line.uom})
            elif self.env("GL_ACCOUNT"):
                out.append({"glAccount": self.env("GL_ACCOUNT"), "netMinor": net})
            else:
                raise ConnectorRejected(f"invoice line {line.line_no} has no SAP purchase order reference; set PIC_ERP_SAP_S4_GL_ACCOUNT "
                                        "to post invoices without a PO")
        if not out:
            raise ConnectorRejected(f"invoice {invoice.number} has no lines to post")
        return out

    def _debit_items(self, session: Session, message: IntegrationMessage) -> list[dict]:
        """Items of a supplier debit memo: PRICE lines against the SAP PO item of the invoice line (subsequent debit), CHARGE lines on the
        G/L account for postings without PO items (PIC_ERP_SAP_S4_GL_ACCOUNT)."""
        from app.pic.models import DebitNote, InvoiceLine, PoLine, PurchaseOrder
        note = session.get(DebitNote, message.object_id)
        if note is None:
            raise ConnectorRejected(f"debit note {message.object_ref} not found")
        lines = {l.line_no: l for l in session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == note.invoice_id)).scalars()}
        out = []
        for entry in note.lines or []:
            net = int(entry.get("netMinor") or 0)
            if entry.get("kind") == "PRICE":
                inv_line = lines.get(int(entry.get("invoice_line") or 0))
                po_line = session.get(PoLine, inv_line.po_line_id) if inv_line is not None and inv_line.po_line_id else None
                po = session.get(PurchaseOrder, po_line.po_id) if po_line is not None else None
                if po is None or not po.erp_doc_no:
                    raise ConnectorRejected(f"debit note {note.number} line {entry.get('invoice_line')}: no SAP purchase order item to debit")
                out.append({"po": po.erp_doc_no, "poItem": po_line.line_no, "netMinor": net, "qty": entry.get("qty") or inv_line.qty, "uom": po_line.uom})
            elif self.env("GL_ACCOUNT"):
                out.append({"glAccount": self.env("GL_ACCOUNT"), "netMinor": net, "text": entry.get("description") or entry.get("charge")})
            else:
                raise ConnectorRejected(f"debit note {note.number}: the {entry.get('charge') or 'additional'} charge needs a G/L account; set "
                                        "PIC_ERP_SAP_S4_GL_ACCOUNT")
        if not out:
            raise ConnectorRejected(f"debit note {note.number} has no lines to post")
        return out

    def _supplier_master(self, session: Session, message: IntegrationMessage) -> dict:
        from app.pic.models import Supplier, SupplierBankAccount
        from app.pic.platform import crypto
        from app.pic.db import current_tenant
        supplier = session.get(Supplier, message.object_id)
        if supplier is None:
            raise ConnectorRejected(f"supplier {message.object_ref} not found")
        tid = current_tenant(session)
        gstin = crypto.decrypt(tid, "gstin", supplier.gstin_enc) if supplier.gstin_enc else None
        bank = session.execute(select(SupplierBankAccount).where(SupplierBankAccount.supplier_id == supplier.id)
                               .order_by(SupplierBankAccount.active.desc(), SupplierBankAccount.created_at.desc())).scalars().first()
        out = {"code": supplier.code, "name": supplier.legal_name, "gstin": gstin, "email": supplier.contact_email, "address": supplier.address or {}}
        if bank is not None:
            out["bank"] = {"account": crypto.decrypt(tid, "bank", bank.account_enc), "ifsc": bank.ifsc, "holder": bank.holder_name}
        return out

    # ------------------------------------------------------------ outline agreements, payment reversal, SCF (rules in platform/sap_defaults.py)
    def skip_reason(self, session: Session, message_type: str, payload: dict) -> Optional[str]:
        """OUTLINE_AGREEMENT: a contract type rule SAP-OUTLINE-AGREEMENT does not send (master agreement, NDA), a type without an SAP
        document type, or a close (termination / renewal) the rule switches off. Live and simulator alike."""
        if message_type != "OUTLINE_AGREEMENT":
            return None
        cfg = sap_defaults.resolve(session, sap_defaults.OUTLINE_KEY, payload.get("companyCode"))
        reason = sap_defaults.skip_reason(cfg, payload.get("type"))
        if reason:
            return reason
        if sap_defaults.api_of(cfg, payload.get("type")) is None:
            doc_type = cfg["documentTypes"].get(payload.get("type"))
            return f"SAP document type {doc_type} of {payload.get('type')} is in neither contractTypes nor schedulingAgreementTypes (rule {cfg.ref})"
        if payload.get("action") == "CLOSE":
            flag = "closeOnRenewal" if payload.get("closeReason") == "RENEWED" else "closeOnTermination"
            if not cfg.get(flag):
                return f"rule {cfg.ref} {flag} is off: the SAP agreement keeps its validity end"
        return None

    def _purchasing(self, session: Session, company_code: Optional[str], cfg) -> dict:
        """Purchasing organisation and group of an outline agreement: the rule (per company code), else PIC_ERP_SAP_S4_PURCH_ORG / _PURCH_GROUP,
        else the PIC purchasing-org master when it names exactly one for the company code (one group for the organisation). The simulator
        falls back to the first master entry, the company code and the mock customizing; a live system rejects an undecided value."""
        from app.pic.models import PurchasingGroup, PurchasingOrg
        org = cfg.get("purchasingOrg") or self.env("PURCH_ORG")
        if not org:
            orgs = list(session.execute(select(PurchasingOrg.code).where(PurchasingOrg.company_code == company_code, PurchasingOrg.active.is_(True))
                                        .order_by(PurchasingOrg.code)).scalars())
            org = orgs[0] if len(orgs) == 1 or (orgs and not self.live) else (None if self.live else company_code)
        group = cfg.get("purchasingGroup") or self.env("PURCH_GROUP")
        if not group and org:
            groups = list(session.execute(select(PurchasingGroup.code).where(PurchasingGroup.purchasing_org == org, PurchasingGroup.active.is_(True))
                                          .order_by(PurchasingGroup.code)).scalars())
            group = groups[0] if len(groups) == 1 or (groups and not self.live) else (
                None if self.live else sap_customizing.load().defaults.get("purchasingGroup"))
        if self.live and not (org and group):
            missing = "purchasingOrg" if not org else "purchasingGroup"
            raise ConnectorRejected(f"company code {company_code}: no SAP {missing} for outline agreements; set it in rule {cfg.ref} for the company "
                                    f"code (or PIC_ERP_SAP_S4_PURCH_ORG / _PURCH_GROUP)")
        return {"purch_org": org, "purch_group": group}

    def _outline_number(self, session: Session, message: IntegrationMessage) -> Optional[str]:
        """The SAP number of the agreement a message changes: the latest earlier OUTLINE_AGREEMENT message of the contract that SAP posted,
        else the contract's ERP number (a contract migrated from SAP). An earlier message that is still pending or retrying goes first
        (versions reach SAP in order); none = the message creates the agreement."""
        from app.pic.models import Contract
        p = _payload(message)
        rank = (int(p.get("version") or 0), message.created_at or datetime.max.replace(tzinfo=timezone.utc), str(message.id))
        earlier = [m for m in session.execute(select(IntegrationMessage).where(
            IntegrationMessage.message_type == "OUTLINE_AGREEMENT", IntegrationMessage.target_system == message.target_system,
            IntegrationMessage.object_id == message.object_id, IntegrationMessage.id != message.id)).scalars()
            if (int((m.payload or {}).get("version") or 0), m.created_at, str(m.id)) < rank]
        posted = sorted((m for m in earlier if m.status == "POSTED" and m.erp_doc_no),
                        key=lambda m: (int((m.payload or {}).get("version") or 0), m.posted_at or m.created_at, str(m.id)))
        if posted:
            return posted[-1].erp_doc_no
        waiting = [m for m in earlier if m.status in ("PENDING", "RETRY")]
        if waiting:
            raise ConnectorRejected(f"{p.get('contract')}: the earlier outline agreement message {waiting[0].idempotency_key} has to reach SAP first")
        contract = session.get(Contract, message.object_id) if message.object_id else None
        return contract.erp_doc_no if contract is not None and contract.erp_doc_no else None

    def _existing_items(self, session: Session, plan_api: str, number: str) -> set:
        """Item numbers SAP holds for an agreement: an OData read (live), the items of the documents recorded so far (simulator)."""
        names = sap_mapping.OUTLINE_API[plan_api]
        if self.live:
            rows = self.client().query(names["service"], names["item_set"], filter=f"{names['number']} eq {sap_odata.literal(number)}", select=names["item"])
            return {int(r[names["item"]]) for r in rows if str(r.get(names["item"]) or "").isdigit()}
        from app.pic.models import ErpDocument
        docs = session.execute(select(ErpDocument).where(ErpDocument.system == self.system, ErpDocument.doc_type == integration.DOC_TYPES["OUTLINE_AGREEMENT"][0],
                                                         ErpDocument.doc_no == number)).scalars()
        return {int(line["line"]) for doc in docs for line in (doc.payload or {}).get("lines") or [] if str(line.get("line") or "").isdigit()}

    def _outline_plan(self, session: Session, message: IntegrationMessage, ctx: dict) -> "sap_mapping.OutlinePlan":
        p = _payload(message)
        cfg = sap_defaults.resolve(session, sap_defaults.OUTLINE_KEY, p.get("companyCode"))
        reason = self.skip_reason(session, "OUTLINE_AGREEMENT", p)
        if reason:
            raise ConnectorRejected(f"{p.get('contract')} is not sent to SAP: {reason}")
        api = sap_defaults.api_of(cfg, p.get("type"))
        body = dict(cfg.body)
        if any(not line.get("material") for line in p.get("lines") or []) and not body.get("textItemMaterialGroup"):
            if self.live:
                raise ConnectorRejected(f"{p.get('contract')} has lines without a material: SAP needs a material group for them; set "
                                        f"textItemMaterialGroup in rule {cfg.ref}")
            body["textItemMaterialGroup"] = sap_customizing.load().defaults.get("textItemMaterialGroup")
        octx = {**ctx, "payment_terms": _pairs(self.env("TERMS_MAP")).get(p.get("paymentTerms") or "")}
        if p.get("action") != "CLOSE":
            octx.update(self._purchasing(session, p.get("companyCode"), cfg))
        number = self._outline_number(session, message)
        existing = self._existing_items(session, api, number) if number and p.get("action") != "CLOSE" else None
        try:
            return sap_mapping.outline_agreement(p, octx, body, api, p.get("lines") or [], number=number, existing_items=existing)
        except ValueError as exc:
            raise ConnectorRejected(f"{p.get('contract')}: {exc}")

    def _post_outline(self, client, plan: "sap_mapping.OutlinePlan") -> str:
        if plan.action == "CREATE":
            entity = client.create(plan.service, plan.header_set, plan.ops[0].body)
            number = entity.get(plan.number_field)
            if not number:
                raise ConnectorRejected(f"SAP accepted the outline agreement but returned no {plan.number_field}: {str(entity)[:200]}")
            return str(number)
        for op in plan.ops:            # items first, the header with the new reference last (sap_mapping.OutlinePlan)
            if op.method == "POST":
                client.create(plan.service, op.path, op.body)
            else:
                client.update(plan.service, op.path, op.body)
        return str(plan.number)

    def _reversal(self, session: Session, message: IntegrationMessage, ctx: dict) -> tuple["sap_mapping.Spec", date]:
        """PAYMENT_REVERSAL body and the original posting date: fiscal year from the payment's value date and the company code's fiscal-year
        start, reason and posting date by rule SAP-PAYMENT-REVERSAL (the closed-period reason when PIC closed the payment's period)."""
        from app.pic.models import CompanyCode, Payment, PostingPeriod
        p = _payload(message)
        cfg = sap_defaults.resolve(session, sap_defaults.REVERSAL_KEY, p.get("companyCode"))
        payment = session.execute(select(Payment).where(Payment.number == p.get("payment"))).scalar_one_or_none()
        original = payment.value_date if payment is not None else clock.today()
        returned = payment.bank_confirmed_at.astimezone(clock.IST).date() if payment is not None and payment.bank_confirmed_at else clock.today()
        company = session.execute(select(CompanyCode).where(CompanyCode.code == p.get("companyCode"))).scalar_one_or_none()
        start = company.fiscal_year_start_month if company is not None and company.fiscal_year_start_month else 4
        fiscal_year = original.year if original.month >= start else original.year - 1
        closed = session.execute(select(PostingPeriod.id).where(PostingPeriod.company_code == p.get("companyCode"), PostingPeriod.status == "CLOSED",
                                                                PostingPeriod.period == original.strftime("%Y-%m"))).first() is not None
        reason, posting = sap_mapping.reversal_terms(cfg.body, original, returned, closed)
        try:
            spec = sap_mapping.payment_reversal(p, ctx, cfg.body, {"fiscalYear": str(fiscal_year), "reason": reason, "postingDate": posting})
        except ValueError as exc:
            raise ConnectorRejected(str(exc))
        return spec, original

    def _scf(self, session: Session, message: IntegrationMessage) -> tuple[dict, dict, str]:
        """(rule SAP-SCF-FINANCING body, the financier's entry, currency) of an SCF_FINANCING message. The simulator uses the mock financier
        when the rule names none; a live system rejects the message until the client configures it."""
        from app.pic.models import Invoice
        p = _payload(message)
        cfg = sap_defaults.resolve(session, sap_defaults.SCF_KEY, p.get("companyCode"))
        try:
            financier = sap_mapping.scf_financier(cfg.body, p.get("financier"))
        except ValueError as exc:
            if self.live:
                raise ConnectorRejected(f"{exc} ({cfg.ref}); the SCF posting needs the client's design, see docs/PIC_SAP_Document_Types.md")
            financier = dict(sap_customizing.load().defaults.get("financier") or {})
        invoice = session.get(Invoice, message.object_id) if message.object_type == "INVOICE" and message.object_id else None
        return cfg.body, financier, (getattr(invoice, "currency", None) or "INR")

    def _scf_spec(self, session: Session, message: IntegrationMessage, ctx: dict) -> "sap_mapping.Spec":
        cfg, financier, currency = self._scf(session, message)
        return sap_mapping.scf_journal_entry(_payload(message), {**ctx, "currency": currency, "journal_service": self.env("JOURNAL_SERVICE")}, cfg, financier)

    def _simulate(self, session: Session, message: IntegrationMessage) -> str:
        """Sandbox simulator for the message types it validates: the live mapping builds the request, the mock customizing checks it
        (platform/sap_customizing.py) and the simulator records it; an outline-agreement change or close keeps the agreement's number."""
        t = message.message_type
        ctx = self._ctx(session, message)
        number = None
        if t == "OUTLINE_AGREEMENT":
            plan = self._outline_plan(session, message, ctx)
            problems = sap_customizing.check_outline(plan, _payload(message).get("type"))
            request = {"service": plan.service, "action": plan.action, "documentType": plan.doc_type,
                       "ops": [{"method": op.method, "path": op.path, "body": op.body} for op in plan.ops]}
            number = plan.number
        elif t == "PAYMENT_REVERSAL":
            spec, original = self._reversal(session, message, ctx)
            problems = sap_customizing.check_reversal(spec.body, original)
            request = {"service": spec.service, "entitySet": spec.entity_set, "body": spec.body}
        else:
            spec = self._scf_spec(session, message, ctx)
            problems = sap_customizing.check_journal(spec.body)
            request = {"service": spec.service, "entitySet": spec.entity_set, "body": spec.body}
        if problems:
            raise ConnectorRejected(f"SAP sandbox simulator refused the {t}: " + "; ".join(problems))
        return self.inner.post(session, message, doc_no=number, request=request)

    # ------------------------------------------------------------ interface used by integration.process
    def _spec(self, session: Session, message: IntegrationMessage, ctx: dict) -> "sap_mapping.Spec":
        p, t = _payload(message), message.message_type
        if t == "PURCHASE_REQUISITION":
            return sap_mapping.purchase_requisition(p, ctx)
        if t == "PURCHASE_ORDER":
            return sap_mapping.purchase_order(p, ctx, self._po_lines(session, p))
        if t == "GOODS_RECEIPT":
            return sap_mapping.goods_receipt(p, ctx, self._gr_items(session, p))
        if t == "SUPPLIER_INVOICE":
            return sap_mapping.supplier_invoice(p, ctx, self._invoice_items(session, message))
        if t == "SUPPLIER_CREDIT_MEMO":
            from app.pic.models import Invoice
            invoice = session.get(Invoice, message.object_id)
            scale = Decimal(p.get("grossMinor") or 0) / Decimal(invoice.gross_minor) if invoice is not None and invoice.gross_minor else None
            return sap_mapping.supplier_invoice(p, ctx, self._invoice_items(session, message, scale), credit=True)
        if t == "SUPPLIER_DEBIT_MEMO":
            return sap_mapping.supplier_debit_memo(p, ctx, self._debit_items(session, message))
        if t == "SUPPLIER_MASTER":
            return sap_mapping.business_partner(p, ctx, self._supplier_master(session, message))
        if t == "MATERIAL_MASTER":
            return sap_mapping.product(p, ctx)
        if t == "PAYMENT":
            return sap_mapping.vendor_payment(p, ctx)
        if t == "PAYMENT_REVERSAL":
            return self._reversal(session, message, ctx)[0]
        if t == "SCF_FINANCING":
            return self._scf_spec(session, message, ctx)
        raise ConnectorUnsupported(f"SAP_S4 connector does not map {t}")

    def find(self, session, message):
        """Query-before-retry (TD §12.2 step 3) by the PIC reference written into the SAP document."""
        if not self.live:
            return super().find(session, message)
        if not self.configured() or message.message_type not in self.message_types:
            return None
        t, p = message.message_type, _payload(message)
        transport = self.transport_for(t)
        reference_value = reference(message.idempotency_key, REF_LEN.get(t, 40))
        if transport == "idoc-file":
            if t == "STOCK_POSTING":
                refs = self._stock_refs(message)
                return RemoteDocument("/".join(refs)) if refs and all(self.idoc_transport().exists(r) for r in refs) else None
            return RemoteDocument(reference_value) if self.idoc_transport().exists(reference_value) else None
        if transport == "idoc":
            return None            # the ICF IDoc port has no query by reference; the IDoc ARCKEY carries it for the SAP-side status report
        if t == "MATERIAL_MASTER":
            if p.get("change"):
                return None
            found = self.client().get(sap_mapping.SERVICES[t], f"A_Product({sap_odata.literal(str(p.get('material'))[:40])})", {"$select": "Product"})
            return RemoteDocument(str(found.get("Product"))) if found else None
        if t == "SUPPLIER_MASTER" and p.get("change"):
            return None            # master changes are always applied (PATCH is idempotent)
        if t == "OUTLINE_AGREEMENT":
            # create, change and close all write the message's reference into the header (a change and a close last), so one query covers them
            api = sap_defaults.api_of(sap_defaults.resolve(session, sap_defaults.OUTLINE_KEY, p.get("companyCode")), p.get("type"))
            if api is None:
                return None
            names = sap_mapping.OUTLINE_API[api]
            rows = self.client().query(names["service"], names["header"], filter=f"{sap_mapping.OUTLINE_REFERENCE_FIELD} eq {sap_odata.literal(reference_value)}",
                                       select=names["number"], top=1)
            return RemoteDocument(str(rows[0][names["number"]])) if rows else None
        if t in ("PAYMENT_REVERSAL", "SCF_FINANCING"):
            service, entity, number = ((self.env("PAYMENT_SERVICE"), "A_VendorPaymentReversal", "ReverseDocument") if t == "PAYMENT_REVERSAL"
                                       else (self.env("JOURNAL_SERVICE"), "A_JournalEntry", "AccountingDocument"))
            rows = self.client().query(service, entity, filter=f"DocumentHeaderText eq {sap_odata.literal(reference_value)}", select=number, top=1)
            return RemoteDocument(str(rows[0][number])) if rows else None
        if t == "PAYMENT":
            return None
        if t == "STOCK_POSTING":   # one material document per goods movement code: found only when every one of them is
            entity, field, number = SAP_FIND[t]
            found, refs = [], self._stock_refs(message)
            if not refs:
                return None
            for ref in refs:
                rows = self.client().query(sap_mapping.SERVICES[t], entity, filter=f"{field} eq {sap_odata.literal(ref)}", select=number, top=1)
                if not rows:
                    return None
                found.append(str(rows[0][number]))
            return RemoteDocument("/".join(found))
        entity, field, number = SAP_FIND[t]
        value = str(p.get("supplier")) if t == "SUPPLIER_MASTER" else reference_value
        rows = self.client().query(sap_mapping.SERVICES[t], entity, filter=f"{field} eq {sap_odata.literal(value)}", select=number, top=1)
        return RemoteDocument(str(rows[0][number])) if rows else None

    def lookup(self, session, external_ref, message_type: Optional[str] = None):
        """Find a document by its PIC reference without a message (reconciliation, support). Without ``message_type`` the reference-bearing
        entity sets are searched in turn."""
        if not self.live:
            return super().lookup(session, external_ref)
        types = [message_type] if message_type else list(SAP_FIND)
        for t in types:
            entity, field, number = SAP_FIND[t]
            rows = self.client().query(sap_mapping.SERVICES[t], entity, filter=f"{field} eq {sap_odata.literal(external_ref)}", select=number, top=1)
            if rows:
                return RemoteDocument(str(rows[0][number]))
        return None

    def post(self, session, message):
        if not self.live:
            if message.message_type in SIMULATOR_VALIDATED:
                return self._simulate(session, message)
            return super().post(session, message)
        self._require(message)
        t, p = message.message_type, _payload(message)
        ctx = self._ctx(session, message)
        transport = self.transport_for(t)
        if transport != "odata":
            return self._post_idoc(session, message, ctx)
        client = self.client()
        if t == "STOCK_POSTING":
            return self._post_stock(session, client, message, ctx)
        if t == "OUTLINE_AGREEMENT":
            return self._post_outline(client, self._outline_plan(session, message, ctx))
        if t == "SUPPLIER_MASTER" and p.get("change"):
            return self._change_vendor(session, client, message, ctx)
        if t == "MATERIAL_MASTER" and p.get("change"):
            body = sap_mapping.product(p, ctx).body
            client.update(sap_mapping.SERVICES[t], f"A_Product({sap_odata.literal(str(p.get('material'))[:40])})",
                          {k: v for k, v in body.items() if k not in ("Product", "to_Description")})
            return str(p.get("material"))
        spec = self._spec(session, message, ctx)
        entity = client.create(spec.service, spec.entity_set, spec.body)
        number = entity.get(spec.number_field)
        if not number:
            raise ConnectorRejected(f"SAP accepted the {t} but returned no {spec.number_field}: {str(entity)[:200]}")
        return str(number)

    def _post_idoc(self, session, message, ctx) -> str:
        t, p = message.message_type, _payload(message)
        data: dict = {}
        if t == "PURCHASE_ORDER":
            data["lines"] = self._po_lines(session, p)
        elif t == "GOODS_RECEIPT":
            data["lines"] = self._gr_items(session, p)
        elif t == "SUPPLIER_INVOICE":
            data["items"] = self._invoice_items(session, message)
        elif t == "SUPPLIER_CREDIT_MEMO":
            data["items"] = self._invoice_items(session, message)
        elif t == "SUPPLIER_MASTER":
            data["supplier"] = self._supplier_master(session, message)
        elif t == "STOCK_POSTING":
            return self._post_stock_idoc(session, message, ctx)
        elif t == "SCF_FINANCING":
            data["cfg"], data["financier"], data["currency"] = self._scf(session, message)
        xml = sap_mapping.idoc_xml(t, p, ctx, data)
        return self.idoc_transport().send(ctx["reference"], xml)

    def _post_stock_idoc(self, session, message, ctx) -> str:
        """IDoc MBGMCR03: one IDoc (one E1BP2017_GM_CODE) per goods movement code. The IDoc port returns the IDoc numbers, joined with '/'."""
        p = _payload(message)
        groups = sap_mapping.stock_groups(self._stock_items(session, message, ctx))
        transport, numbers = self.idoc_transport(), []
        for (code, items), ref in zip(groups, self._stock_refs(message)):
            xml = sap_mapping.idoc_xml("STOCK_POSTING", p, {**ctx, "reference": ref}, {"code": code, "items": items, "objectType": message.object_type})
            numbers.append(transport.send(ref, xml))
        return "/".join(numbers)

    def _change_vendor(self, session, client, message, ctx) -> str:
        """Apply an approved MDM-04 change (tax number, address, e-mail) to the business partner found by supplier code."""
        import json as _json
        from app.pic.db import current_tenant
        from app.pic.models import SupplierMasterChange
        from app.pic.platform import crypto
        p = _payload(message)
        service = sap_mapping.SERVICES["SUPPLIER_MASTER"]
        partners = client.query(service, "A_BusinessPartner", filter=f"SearchTerm1 eq {sap_odata.literal(p.get('supplier'))}", select="BusinessPartner", top=1)
        if not partners:
            raise ConnectorRejected(f"business partner for supplier {p.get('supplier')} not found in SAP; create it first")
        bp = partners[0]["BusinessPartner"]
        change = session.execute(select(SupplierMasterChange).where(SupplierMasterChange.number == p.get("change"))).scalar_one_or_none()
        if change is None:
            raise ConnectorRejected(f"master change {p.get('change')} not found")
        values = _json.loads(crypto.decrypt(current_tenant(session), "supplier-master-change", change.after_enc))
        group = (p.get("fieldGroup") or change.field_group or "").upper()
        if group == "TAX":
            if self._has_tax(client, service, bp):
                client.update(service, f"A_BusinessPartnerTaxNumber(BusinessPartner={sap_odata.literal(bp)},BPTaxType='IN3')",
                              {"BPTaxNumber": values["gstin"]})
            else:
                client.create(service, "A_BusinessPartnerTaxNumber", {"BusinessPartner": bp, "BPTaxType": "IN3", "BPTaxNumber": values["gstin"]})
        else:
            addresses = client.query(service, "A_BusinessPartnerAddress", filter=f"BusinessPartner eq {sap_odata.literal(bp)}", select="AddressID", top=1)
            if not addresses:
                raise ConnectorRejected(f"business partner {bp} has no address in SAP to change")
            address_id = addresses[0]["AddressID"]
            if group == "ADDRESS":
                client.update(service, f"A_BusinessPartnerAddress(BusinessPartner={sap_odata.literal(bp)},AddressID={sap_odata.literal(address_id)})",
                              {"StreetName": (values.get("line1") or "")[:60], "CityName": (values.get("city") or "")[:40], "PostalCode": (values.get("pin") or "")[:10]})
            elif values.get("email"):
                client.create(service, "A_AddressEmailAddress", {"AddressID": address_id, "Person": "", "OrdinalNumber": "1", "EmailAddress": values["email"][:241]})
        return str(bp)

    @staticmethod
    def _has_tax(client, service, bp) -> bool:
        return bool(client.query(service, "A_BusinessPartnerTaxNumber", filter=f"BusinessPartner eq {sap_odata.literal(bp)} and BPTaxType eq 'IN3'", top=1))

    def after_post(self):
        return super().after_post() if not self.live else None

    # ------------------------------------------------------------ health, test and inbound pulls
    def health(self) -> dict:
        if not self.live:
            return super().health()
        if not self.configured():
            return {"healthy": False, "detail": f"not configured: set {', '.join(self.missing())}"}
        if self.transport() == "idoc-file":
            import os
            directory = self.env("IDOC_DIR")
            ok = os.path.isdir(directory) and os.access(directory, os.W_OK)
            return {"healthy": ok, "detail": f"file port {directory} " + ("is writable" if ok else "is missing or not writable")}
        try:
            report = self.client().test([sap_mapping.SERVICES[t] for t in ("SUPPLIER_MASTER", "PURCHASE_ORDER", "SUPPLIER_INVOICE", "GOODS_RECEIPT", "MATERIAL_MASTER")])
        except ConnectorError as exc:
            return {"healthy": False, "detail": str(exc)}
        failed = [s for s, r in report["services"].items() if not r["ok"]]
        detail = "all services reachable, CSRF token obtained" if report["ok"] else ("; ".join(f"{s}: {report['services'][s]['detail']}" for s in failed)
                                                                                    or report.get("csrfDetail", "no CSRF token"))
        return {"healthy": report["ok"], "detail": detail[:300], "services": report["services"], "csrf": report["csrf"]}

    def test_connection(self) -> dict:
        return {**self.health(), "system": self.system, "live": self.live, "transport": self.transport() if self.live else "simulator"}

    def pull(self, kind: str, since: Optional[str] = None, company_code: Optional[str] = None):
        if not self.live or self.transport() != "odata":
            raise ConnectorNotConfigured("SAP_S4 inbound pulls need the OData transport: set PIC_ERP_SAP_S4_URL and credentials "
                                         "(the sandbox simulator and IDoc ports have no read interface)")
        if not self.configured():
            raise ConnectorNotConfigured(f"SAP_S4 connector is not configured: set {', '.join(self.missing())}")
        return sap_pull.pull(self.client(), kind, since, self.company(company_code), clock.today())


def _pairs(value: Optional[str]) -> dict:
    """``"A=1,B=2"`` (an environment setting) as a dict; blanks and entries without '=' are ignored."""
    out = {}
    for pair in (value or "").split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            if k.strip() and v.strip():
                out[k.strip()] = v.strip()
    return out


def _payload(message: IntegrationMessage) -> dict:
    """The payload the connector maps: the field-mapped outbound payload when the mapping layer produced one, else the PIC payload."""
    return getattr(message, "outbound_payload", None) or message.payload


# ---------------------------------------------------------------- Oracle Fusion Cloud ERP (REST)
class OracleFusion(Connector):
    system = "ORACLE_FUSION"
    name = "Oracle Fusion Cloud ERP"
    protocol = "REST (fscmRestApi 11.13.18.05)"
    message_types = MESSAGE_TYPES
    BASE = "/fscmRestApi/resources/11.13.18.05"
    # message type → (resource, PIC reference field, document number field)
    RESOURCES = {
        "SUPPLIER_INVOICE": ("invoices", "Description", "InvoiceId"),
        "SUPPLIER_CREDIT_MEMO": ("invoices", "Description", "InvoiceId"),
        "PURCHASE_ORDER": ("draftPurchaseOrders", "Description", "OrderNumber"),
        "GOODS_RECEIPT": ("receivingReceiptRequests", "Comments", "HeaderInterfaceId"),
        "SUPPLIER_MASTER": ("suppliers", "AlternateName", "SupplierId"),
        "MATERIAL_MASTER": ("itemsV2", "ItemNumber", "ItemId"),
        "PAYMENT": ("payablesPayments", "PaymentDescription", "CheckId"),
    }

    def body(self, message: IntegrationMessage) -> dict:
        p, bu, ref = message.payload, self.company(message.payload.get("companyCode")), reference(message.idempotency_key, 240)
        t = message.message_type
        if t == "SUPPLIER_INVOICE":
            return {"InvoiceNumber": p.get("invoice"), "BusinessUnit": bu, "Supplier": p.get("supplier"), "InvoiceCurrency": "INR",
                    "InvoiceAmount": (p.get("grossMinor") or 0) / 100, "InvoiceType": "Standard", "Description": ref}
        if t == "SUPPLIER_CREDIT_MEMO":   # Payables credit memo: type "Credit Memo", negative amount, tied to the invoice by its number
            return {"InvoiceNumber": p.get("creditNote"), "BusinessUnit": bu, "Supplier": p.get("supplier"), "InvoiceCurrency": "INR",
                    "InvoiceAmount": -(p.get("grossMinor") or 0) / 100, "InvoiceType": "Credit Memo", "Description": ref,
                    "InvoiceReference": p.get("invoice")}
        if t == "PURCHASE_ORDER":
            return {"ProcurementBU": bu, "Supplier": p.get("supplier"), "Description": ref, "CurrencyCode": "INR",
                    "lines": [{"LineNumber": l.get("line"), "Quantity": float(l.get("qty") or 0), "Price": (l.get("priceMinor") or 0) / 100}
                              for l in p.get("lines", [])]}
        if t == "GOODS_RECEIPT":
            return {"ReceiptSourceCode": "VENDOR", "BusinessUnit": bu, "Comments": ref, "ReceiptNumber": p.get("gr"),
                    "lines": [{"DocumentNumber": p.get("po"), "Quantity": float(l.get("accepted") or 0), "SourceDocumentCode": "PO",
                               "TransactionType": "RECEIVE"} for l in p.get("lines", [])]}
        if t == "SUPPLIER_MASTER":
            return {"Supplier": p.get("name") or p.get("supplier"), "SupplierNumber": p.get("supplier"), "AlternateName": ref,
                    "BusinessRelationship": "SPEND_AUTHORIZED", "TaxOrganizationType": "CORPORATION"}
        if t == "MATERIAL_MASTER":
            return {"ItemNumber": p.get("material"), "ItemDescription": p.get("description"), "PrimaryUOMValue": p.get("uom"),
                    "OrganizationCode": bu, "ItemClass": "Root Item Class"}
        return {"BusinessUnit": bu, "PaymentAmount": (p.get("amountMinor") or 0) / 100, "PaymentCurrency": "INR",
                "PaymentDescription": ref, "RemitToSupplier": p.get("supplier")}

    def find(self, session, message):
        if not self.configured() or message.message_type not in self.RESOURCES:
            return None
        resource, field, number = self.RESOURCES[message.message_type]
        value = message.payload.get("material") if field == "ItemNumber" else reference(message.idempotency_key, 240)
        query = urllib.parse.quote(f"{field}='{value}'")
        _, text = self._call("GET", f"{self.BASE}/{resource}?q={query}&limit=1&onlyData=true")
        items = _json(text, self.system).get("items") or []
        return RemoteDocument(str(items[0].get(number))) if items else None

    def post(self, session, message):
        self._require(message)
        resource, _, number = self.RESOURCES[message.message_type]
        _, text = self._call("POST", f"{self.BASE}/{resource}", self.body(message))
        return str(_json(text, self.system).get(number) or "")

    def health_path(self) -> str:
        return f"{self.BASE}/invoices?limit=1&onlyData=true&fields=InvoiceId"


# ---------------------------------------------------------------- Microsoft Dynamics 365 Finance & Operations (OData v4)
class Dynamics365(Connector):
    system = "DYNAMICS_365"
    name = "Microsoft Dynamics 365 Finance & Supply Chain"
    protocol = "OData v4 (/data entities)"
    message_types = ("SUPPLIER_INVOICE", "SUPPLIER_CREDIT_MEMO", "PURCHASE_ORDER", "GOODS_RECEIPT", "SUPPLIER_MASTER", "MATERIAL_MASTER", "PAYMENT")
    credentials = "token"
    # PAYMENT needs the vendor payment journal batch to post into: PIC_ERP_DYNAMICS_365_PAYMENT_JOURNAL (the batch number, optional setting).
    ENTITIES = {
        "SUPPLIER_INVOICE": ("VendorInvoiceHeaders", "InvoiceDescription", "HeaderReference"),
        "SUPPLIER_CREDIT_MEMO": ("VendorInvoiceHeaders", "InvoiceDescription", "HeaderReference"),
        "PAYMENT": ("VendorPaymentJournalLines", "PaymentReference", "JournalBatchNumber"),
        "PURCHASE_ORDER": ("PurchaseOrderHeadersV2", "VendorOrderReference", "PurchaseOrderNumber"),
        "GOODS_RECEIPT": ("ProductReceiptHeaders", "ProductReceiptNumber", "ProductReceiptNumber"),
        "SUPPLIER_MASTER": ("VendorsV2", "VendorAccountNumber", "VendorAccountNumber"),
        "MATERIAL_MASTER": ("ReleasedProductsV2", "ItemNumber", "ItemNumber"),
    }

    def body(self, message: IntegrationMessage) -> dict:
        p, area, t = message.payload, self.company(message.payload.get("companyCode")), message.message_type
        if t == "SUPPLIER_INVOICE":
            return {"dataAreaId": area, "InvoiceAccount": p.get("supplier"), "InvoiceNumber": p.get("invoice"),
                    "InvoiceDescription": reference(message.idempotency_key, 60), "Currency": "INR"}
        if t == "PURCHASE_ORDER":
            return {"dataAreaId": area, "OrderVendorAccountNumber": p.get("supplier"), "VendorOrderReference": reference(message.idempotency_key, 20),
                    "PurchaseOrderName": f"PIC {p.get('po')} v{p.get('version')}", "CurrencyCode": "INR"}
        if t == "GOODS_RECEIPT":
            return {"dataAreaId": area, "PurchaseOrderNumber": p.get("po"), "ProductReceiptNumber": p.get("gr")}
        if t == "SUPPLIER_CREDIT_MEMO":   # a vendor invoice with a negative amount is posted as a credit note
            return {"dataAreaId": area, "InvoiceAccount": p.get("supplier"), "InvoiceNumber": p.get("creditNote"),
                    "InvoiceDescription": reference(message.idempotency_key, 60), "Currency": "INR",
                    "InvoiceAmount": -(p.get("grossMinor") or 0) / 100, "OriginalInvoiceNumber": p.get("invoice")}
        if t == "PAYMENT":
            journal = self.env("PAYMENT_JOURNAL")
            if not journal:
                raise ConnectorRejected("set PIC_ERP_DYNAMICS_365_PAYMENT_JOURNAL to the vendor payment journal batch payments are posted into")
            return {"dataAreaId": area, "JournalBatchNumber": journal, "AccountDisplayValue": p.get("supplier"),
                    "DebitAmount": (p.get("amountMinor") or 0) / 100, "CurrencyCode": "INR", "PaymentReference": reference(message.idempotency_key, 20),
                    "Description": f"PIC {p.get('payment')}"}
        if t == "SUPPLIER_MASTER":
            return {"dataAreaId": area, "VendorAccountNumber": p.get("supplier"), "VendorOrganizationName": p.get("name") or p.get("supplier"),
                    "VendorGroupId": "DOM"}
        return {"dataAreaId": area, "ItemNumber": p.get("material"), "ProductName": p.get("description"),
                "InventoryUnitSymbol": p.get("uom"), "PurchaseUnitSymbol": p.get("uom")}

    def _key(self, message) -> str:
        entity, field, _ = self.ENTITIES[message.message_type]
        p = message.payload
        return {"ProductReceiptNumber": p.get("gr"), "VendorAccountNumber": p.get("supplier"), "ItemNumber": p.get("material")}.get(
            field) or reference(message.idempotency_key, 60 if field == "InvoiceDescription" else 20)

    def find(self, session, message):
        if not self.configured() or message.message_type not in self.ENTITIES:
            return None
        entity, field, number = self.ENTITIES[message.message_type]
        if message.message_type in ("SUPPLIER_MASTER", "MATERIAL_MASTER") and message.payload.get("change"):
            return None  # master changes are always applied (PATCH in post)
        area = self.company(message.payload.get("companyCode"))
        flt = urllib.parse.quote(f"{field} eq '{self._key(message)}' and dataAreaId eq '{area}'")
        _, text = self._call("GET", f"/data/{entity}?$filter={flt}&cross-company=true&$top=1")
        items = _json(text, self.system).get("value") or []
        return RemoteDocument(str(items[0].get(number))) if items else None

    def post(self, session, message):
        self._require(message)
        entity, field, number = self.ENTITIES[message.message_type]
        body = self.body(message)
        if message.message_type in ("SUPPLIER_MASTER", "MATERIAL_MASTER") and message.payload.get("change"):
            key = f"dataAreaId='{body['dataAreaId']}',{field}='{self._key(message)}'"
            self._call("PATCH", f"/data/{entity}({urllib.parse.quote(key)})", {k: v for k, v in body.items() if k not in ("dataAreaId", field)})
            return self._key(message)
        _, text = self._call("POST", f"/data/{entity}", body)
        doc_no = str(_json(text, self.system).get(number) or "")
        if message.message_type == "PURCHASE_ORDER":
            for line in message.payload.get("lines", []):
                self._call("POST", "/data/PurchaseOrderLinesV2", {
                    "dataAreaId": body["dataAreaId"], "PurchaseOrderNumber": doc_no, "LineNumber": line.get("line"),
                    "OrderedPurchaseQuantity": float(line.get("qty") or 0), "PurchasePrice": (line.get("priceMinor") or 0) / 100})
        return doc_no

    def health_path(self) -> str:
        return "/data/LegalEntities?$top=1&$select=LegalEntityId"


# ---------------------------------------------------------------- Tally Prime (XML over HTTP gateway)
class TallyPrime(Connector):
    system = "TALLY_PRIME"
    name = "TallyPrime"
    protocol = "XML over HTTP (Tally gateway, port 9000)"
    message_types = MESSAGE_TYPES
    credentials = "none"
    VOUCHERS = {"SUPPLIER_INVOICE": "Purchase", "SUPPLIER_CREDIT_MEMO": "Debit Note", "PURCHASE_ORDER": "Purchase Order",
                "GOODS_RECEIPT": "Receipt Note", "PAYMENT": "Payment"}

    def envelope(self, message: IntegrationMessage) -> str:
        p, t = message.payload, message.message_type
        company = escape(self.company(p.get("companyCode")))
        ref = escape(reference(message.idempotency_key, 50))
        if t == "SUPPLIER_MASTER":
            name = escape(str(p.get("name") or p.get("supplier")))
            data, report = (f'<LEDGER NAME="{name}" ACTION="{"Alter" if p.get("change") else "Create"}"><NAME>{name}</NAME>'
                            f'<PARENT>Sundry Creditors</PARENT><ALIAS>{escape(str(p.get("supplier")))}</ALIAS></LEDGER>'), "All Masters"
        elif t == "MATERIAL_MASTER":
            item = escape(str(p.get("material")))
            data, report = (f'<STOCKITEM NAME="{item}" ACTION="Create"><NAME>{item}</NAME><BASEUNITS>{escape(str(p.get("uom") or "Nos"))}'
                            f'</BASEUNITS><DESCRIPTION>{escape(str(p.get("description") or ""))}</DESCRIPTION></STOCKITEM>'), "All Masters"
        else:
            amount = (p.get("grossMinor") or p.get("amountMinor") or 0) / 100
            party = escape(str(p.get("supplier") or ""))
            data = (f'<VOUCHER VCHTYPE="{self.VOUCHERS[t]}" ACTION="Create"><VOUCHERTYPENAME>{self.VOUCHERS[t]}</VOUCHERTYPENAME>'
                    f'<VOUCHERNUMBER>{ref}</VOUCHERNUMBER><REFERENCE>{escape(str(p.get("invoice") or p.get("po") or p.get("gr") or p.get("payment") or ""))}'
                    f'</REFERENCE><PARTYLEDGERNAME>{party}</PARTYLEDGERNAME><NARRATION>PIC {escape(message.idempotency_key)}</NARRATION>'
                    f'<AMOUNT>{amount:.2f}</AMOUNT></VOUCHER>')
            report = "Vouchers"
        return (f"<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA><REQUESTDESC>"
                f"<REPORTNAME>{report}</REPORTNAME><STATICVARIABLES><SVCURRENTCOMPANY>{company}</SVCURRENTCOMPANY></STATICVARIABLES>"
                f"</REQUESTDESC><REQUESTDATA><TALLYMESSAGE>{data}</TALLYMESSAGE></REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")

    def lookup_envelope(self, message: IntegrationMessage) -> Optional[str]:
        """Export request (TDL collection) for the document a message would create: vouchers by the PIC voucher number written
        by ``envelope``, ledgers / stock items by name. None when there is nothing to look up (master alterations are idempotent)."""
        p, t = message.payload, message.message_type
        if t in ("SUPPLIER_MASTER", "MATERIAL_MASTER") and p.get("change"):
            return None

        def literal(value) -> str:  # a TDL string literal inside XML text
            return escape(str(value or "").replace('"', "").replace("\n", " "))

        if t == "SUPPLIER_MASTER":
            kind, fetch, formula = "Ledger", "Name, MasterId", f'$Name = "{literal(p.get("name") or p.get("supplier"))}"'
        elif t == "MATERIAL_MASTER":
            kind, fetch, formula = "StockItem", "Name, MasterId", f'$Name = "{literal(p.get("material"))}"'
        else:
            kind, fetch = "Voucher", "VoucherNumber, VoucherTypeName, MasterId"
            formula = (f'$VoucherTypeName = "{literal(self.VOUCHERS[t])}" AND '
                       f'$VoucherNumber = "{literal(reference(message.idempotency_key, 50))}"')
        company = escape(self.company(p.get("companyCode")))
        return (f"<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>PICLookup</ID>"
                f"</HEADER><BODY><DESC><STATICVARIABLES><SVCURRENTCOMPANY>{company}</SVCURRENTCOMPANY>"
                f"<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT></STATICVARIABLES><TDL><TDLMESSAGE>"
                f'<COLLECTION NAME="PICLookup" ISMODIFY="No"><TYPE>{kind}</TYPE><FETCH>{fetch}</FETCH><FILTER>PICMatch</FILTER></COLLECTION>'
                f'<SYSTEM TYPE="Formulae" NAME="PICMatch">{formula}</SYSTEM></TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>')

    def find(self, session, message):
        """Query-before-retry (TD §12.2 step 3): ask the Tally gateway whether the voucher / master already exists."""
        if not self.configured() or message.message_type not in self.message_types:
            return None
        request = self.lookup_envelope(message)
        if request is None:
            return None
        _, text = self._call("POST", "/", raw=request.encode(), content_type="text/xml; charset=utf-8")
        root = _xml(text, "Tally")
        if root.findtext(".//LINEERROR"):
            raise ConnectorRejected(f"Tally rejected the lookup: {root.findtext('.//LINEERROR')}")
        for tag in ("VOUCHER", "LEDGER", "STOCKITEM"):
            found = root.find(f".//{tag}")
            if found is not None:
                number = (found.findtext("MASTERID") or found.findtext("VOUCHERNUMBER") or found.get("NAME") or found.findtext("NAME") or "").strip()
                return RemoteDocument(number or reference(message.idempotency_key, 50))
        return None

    def post(self, session, message):
        self._require(message)
        _, text = self._call("POST", "/", raw=self.envelope(message).encode(), content_type="text/xml; charset=utf-8")
        root = _xml(text, "Tally")
        try:
            failed = int(root.findtext(".//ERRORS") or 0) > 0 or int(root.findtext(".//EXCEPTIONS") or 0) > 0
        except ValueError:
            raise ConnectorRejected(f"Tally answered with an unreadable import status: {text[:200]}")
        if failed:
            raise ConnectorRejected(f"Tally rejected the import: {root.findtext('.//LINEERROR') or text[:200]}")
        return root.findtext(".//LASTVCHID") or reference(message.idempotency_key, 50)

    def health(self) -> dict:
        if not self.configured():
            return {"healthy": False, "detail": f"not configured: set {', '.join(self.missing())}"}
        try:
            _, text = self._call("GET", "/", content_type="text/xml")
            return {"healthy": "running" in text.lower(), "detail": text.strip()[:120] or "no answer"}
        except ConnectorError as exc:
            return {"healthy": False, "detail": str(exc)}


# ---------------------------------------------------------------- Odoo (JSON-RPC external API)
class Odoo(Connector):
    system = "ODOO"
    name = "Odoo"
    protocol = "JSON-RPC (/jsonrpc external API)"
    message_types = ("SUPPLIER_INVOICE", "SUPPLIER_CREDIT_MEMO", "PURCHASE_ORDER", "GOODS_RECEIPT", "SUPPLIER_MASTER", "MATERIAL_MASTER", "PAYMENT")
    credentials = "basic"
    extra_settings = ("DB",)
    needs_company_map = False
    MODELS = {"SUPPLIER_INVOICE": ("account.move", "payment_reference"), "SUPPLIER_CREDIT_MEMO": ("account.move", "payment_reference"),
              "GOODS_RECEIPT": ("stock.picking", "origin"), "PURCHASE_ORDER": ("purchase.order", "origin"),
              "SUPPLIER_MASTER": ("res.partner", "ref"), "MATERIAL_MASTER": ("product.product", "default_code"),
              "PAYMENT": ("account.payment", "memo")}

    def _rpc(self, service: str, method: str, *args):
        body = {"jsonrpc": "2.0", "method": "call", "id": uuid.uuid4().hex, "params": {"service": service, "method": method, "args": list(args)}}
        _, text = _http("POST", f"{self.env('URL').rstrip('/')}/jsonrpc", headers={"content-type": "application/json"},
                        body=json.dumps(body).encode(), timeout=float(self.env("TIMEOUT") or 20))
        answer = _json(text, self.system)
        if answer.get("error"):
            raise ConnectorRejected(f"Odoo: {answer['error'].get('data', {}).get('message') or answer['error'].get('message')}")
        return answer.get("result")

    def _execute(self, model: str, method: str, *args):
        uid = self._rpc("common", "login", self.env("DB"), self.env("USER"), self.env("PASSWORD"))
        if not uid:
            raise ConnectorRejected("Odoo rejected the login (check PIC_ERP_ODOO_USER / _PASSWORD)")
        return self._rpc("object", "execute_kw", self.env("DB"), uid, self.env("PASSWORD"), model, method, *args)

    def _value(self, message) -> str:
        p = message.payload
        if message.message_type == "SUPPLIER_MASTER":
            return str(p.get("supplier"))
        if message.message_type == "MATERIAL_MASTER":
            return str(p.get("material"))
        return reference(message.idempotency_key, 60)

    def _partner(self, code: Optional[str]) -> Optional[int]:
        ids = self._execute("res.partner", "search", [[["ref", "=", code]]], {"limit": 1}) if code else []
        return ids[0] if ids else None

    def find(self, session, message):
        if not self.configured() or message.message_type not in self.MODELS:
            return None
        if message.message_type in ("SUPPLIER_MASTER", "MATERIAL_MASTER") and message.payload.get("change"):
            return None
        model, field = self.MODELS[message.message_type]
        ids = self._execute(model, "search", [[[field, "=", self._value(message)]]], {"limit": 1})
        return RemoteDocument(str(ids[0])) if ids else None

    def post(self, session, message):
        self._require(message)
        model, field = self.MODELS[message.message_type]
        p, t = message.payload, message.message_type
        if t == "SUPPLIER_INVOICE":
            vals = {"move_type": "in_invoice", "ref": p.get("invoice"), field: self._value(message), "partner_id": self._partner(p.get("supplier"))}
        elif t == "SUPPLIER_CREDIT_MEMO":   # vendor refund (credit note) against the original bill
            vals = {"move_type": "in_refund", "ref": p.get("creditNote"), field: self._value(message), "partner_id": self._partner(p.get("supplier")),
                    "invoice_origin": p.get("invoice")}
        elif t == "GOODS_RECEIPT":          # incoming picking (receipt) of the PO; validating it books the stock in Odoo
            types = self._execute("stock.picking.type", "search_read", [[["code", "=", "incoming"]]], {"fields": ["default_location_dest_id"], "limit": 1})
            sources = self._execute("stock.location", "search", [[["usage", "=", "supplier"]]], {"limit": 1})
            if not types or not sources:
                raise ConnectorRejected("Odoo has no incoming picking type or supplier location to receive into")
            vals = {"picking_type_id": types[0]["id"], "location_id": sources[0], "location_dest_id": (types[0].get("default_location_dest_id") or [None])[0],
                    "origin": self._value(message), "note": f"PIC goods receipt {p.get('gr')} for {p.get('po')}"}
        elif t == "PURCHASE_ORDER":
            vals = {"partner_id": self._partner(p.get("supplier")), "partner_ref": p.get("po"), field: self._value(message)}
        elif t == "SUPPLIER_MASTER":
            vals = {"name": p.get("name") or p.get("supplier"), field: self._value(message), "supplier_rank": 1, "is_company": True}
            existing = self._execute(model, "search", [[[field, "=", self._value(message)]]], {"limit": 1})
            if existing:
                self._execute(model, "write", [existing, {k: v for k, v in vals.items() if k != field}])
                return str(existing[0])
        elif t == "MATERIAL_MASTER":
            vals = {"name": p.get("description") or p.get("material"), field: self._value(message), "purchase_ok": True}
        else:
            vals = {"payment_type": "outbound", "partner_type": "supplier", "amount": (p.get("amountMinor") or 0) / 100,
                    field: self._value(message), "partner_id": self._partner(p.get("supplier"))}
        vals = {k: v for k, v in vals.items() if v is not None}
        return str(self._execute(model, "create", [vals]))

    def health(self) -> dict:
        if not self.configured():
            return {"healthy": False, "detail": f"not configured: set {', '.join(self.missing())}"}
        try:
            version = self._rpc("common", "version")
            uid = self._rpc("common", "login", self.env("DB"), self.env("USER"), self.env("PASSWORD"))
            return {"healthy": bool(uid), "detail": f"Odoo {(version or {}).get('server_version', '?')}" + ("" if uid else ", login rejected")}
        except ConnectorError as exc:
            return {"healthy": False, "detail": str(exc)}


# ---------------------------------------------------------------- registry
REGISTRY: dict[str, Connector] = {c.system: c for c in (SapS4(), OracleFusion(), Dynamics365(), TallyPrime(), Odoo())}
_health: dict[str, dict] = {}


def get(system: str) -> Connector:
    connector = REGISTRY.get((system or "").upper())
    if connector is None:
        raise ConnectorNotConfigured(f"No connector for target system {system}; known: {', '.join(REGISTRY)}")
    return connector


def maps(system: str, message_type: str) -> bool:
    """Whether the target system's connector maps this PIC message type (SAP_S4: every simulator document type)."""
    connector = REGISTRY.get((system or "").upper())
    if connector is None:
        return False
    return message_type in connector.message_types      # SAP_S4: the simulator's document types, or the live connector's mapping


def skip_reason(system: str, session: Session, message_type: str, payload: dict) -> Optional[str]:
    """Why the target connector deliberately does not send this document (SAP_S4: a contract type its rule does not send), else None."""
    connector = REGISTRY.get((system or "").upper())
    return connector.skip_reason(session, message_type, payload) if connector is not None else None


def require_mapped(system: str, message_type: str) -> None:
    """Refuse to enqueue a message the target connector cannot post: it would only dead-letter after 8 retries while the
    platform reports the business step as done. Raise a clear 422 instead, before anything is written."""
    from app.pic.platform.errors import Problem

    if not maps(system, message_type):
        connector = REGISTRY.get((system or "").upper())
        supported = ", ".join(connector.message_types) if connector is not None else "none (unknown target system)"
        raise Problem(422, "MESSAGE_TYPE_NOT_MAPPED",
                      f"The {system} connector does not map {message_type}; post it in the ERP directly or configure a connector that "
                      f"maps it (supported: {supported})", rule_ref="P13", targetSystem=system, messageType=message_type)


def check_health(system: str) -> dict:
    connector = get(system)
    result = {**connector.health(), "checkedAt": datetime.now(timezone.utc).isoformat()}
    _health[connector.system] = result
    return result


def status(session: Session) -> list[dict]:
    counts: dict[str, dict[str, int]] = {}
    for target, state, n in session.execute(select(IntegrationMessage.target_system, IntegrationMessage.status, func.count())
                                            .group_by(IntegrationMessage.target_system, IntegrationMessage.status)):
        counts.setdefault(target, {})[state] = n
    out = []
    for system, connector in REGISTRY.items():
        last = _health.get(system)
        healthy = True if connector.simulator else (last["healthy"] if last else None)
        out.append({**connector.describe(), "healthy": healthy, "lastCheck": last, "messages": counts.get(system, {}),
                    "total": sum(counts.get(system, {}).values())})
    return out
