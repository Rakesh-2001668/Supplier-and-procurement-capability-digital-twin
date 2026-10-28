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
from datetime import datetime, timezone
from typing import Optional
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.models import IntegrationMessage
from app.pic.platform import integration
from app.pic.platform.integration import ConnectorError, ConnectorTimeout

MESSAGE_TYPES = ("SUPPLIER_INVOICE", "PURCHASE_ORDER", "GOODS_RECEIPT", "SUPPLIER_MASTER", "MATERIAL_MASTER", "PAYMENT")


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

    # interface used by integration.process
    def find(self, session: Session, message: IntegrationMessage) -> Optional[RemoteDocument]:
        return None

    def post(self, session: Session, message: IntegrationMessage) -> str:
        raise NotImplementedError

    def after_post(self) -> None:
        return None

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
class SapS4(Connector):
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
        items = json.loads(text or "{}").get("items") or []
        return RemoteDocument(str(items[0].get(number))) if items else None

    def post(self, session, message):
        self._require(message)
        resource, _, number = self.RESOURCES[message.message_type]
        _, text = self._call("POST", f"{self.BASE}/{resource}", self.body(message))
        return str(json.loads(text or "{}").get(number) or "")

    def health_path(self) -> str:
        return f"{self.BASE}/invoices?limit=1&onlyData=true&fields=InvoiceId"


# ---------------------------------------------------------------- Microsoft Dynamics 365 Finance & Operations (OData v4)
class Dynamics365(Connector):
    system = "DYNAMICS_365"
    name = "Microsoft Dynamics 365 Finance & Supply Chain"
    protocol = "OData v4 (/data entities)"
    message_types = ("SUPPLIER_INVOICE", "PURCHASE_ORDER", "GOODS_RECEIPT", "SUPPLIER_MASTER", "MATERIAL_MASTER")
    credentials = "token"
    ENTITIES = {
        "SUPPLIER_INVOICE": ("VendorInvoiceHeaders", "InvoiceDescription", "HeaderReference"),
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
        items = json.loads(text or "{}").get("value") or []
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
        doc_no = str(json.loads(text or "{}").get(number) or "")
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
    VOUCHERS = {"SUPPLIER_INVOICE": "Purchase", "PURCHASE_ORDER": "Purchase Order", "GOODS_RECEIPT": "Receipt Note", "PAYMENT": "Payment"}

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

    def post(self, session, message):
        self._require(message)
        _, text = self._call("POST", "/", raw=self.envelope(message).encode(), content_type="text/xml; charset=utf-8")
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError:
            raise ConnectorRejected(f"Tally answered with unreadable XML: {text[:200]}")
        if int(root.findtext(".//ERRORS") or 0) > 0 or int(root.findtext(".//EXCEPTIONS") or 0) > 0:
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
    message_types = ("SUPPLIER_INVOICE", "PURCHASE_ORDER", "SUPPLIER_MASTER", "MATERIAL_MASTER", "PAYMENT")
    credentials = "basic"
    extra_settings = ("DB",)
    needs_company_map = False
    MODELS = {"SUPPLIER_INVOICE": ("account.move", "payment_reference"), "PURCHASE_ORDER": ("purchase.order", "origin"),
              "SUPPLIER_MASTER": ("res.partner", "ref"), "MATERIAL_MASTER": ("product.product", "default_code"),
              "PAYMENT": ("account.payment", "memo")}

    def _rpc(self, service: str, method: str, *args):
        body = {"jsonrpc": "2.0", "method": "call", "id": uuid.uuid4().hex, "params": {"service": service, "method": method, "args": list(args)}}
        _, text = _http("POST", f"{self.env('URL').rstrip('/')}/jsonrpc", headers={"content-type": "application/json"},
                        body=json.dumps(body).encode(), timeout=float(self.env("TIMEOUT") or 20))
        answer = json.loads(text or "{}")
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
