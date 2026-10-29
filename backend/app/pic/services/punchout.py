"""M04 punch-out (cXML 1.2 / SAP OCI 4.0) sessions and cart return to requisition lines.

Flow (blueprint M04 "cXML/OCI punch-out; returned carts become catalogue PR lines with supplier part numbers"):

1. ``configure`` stores the supplier's punch-out endpoint: protocol, URL, identity; the shared secret is field-encrypted
   and never returned.
2. ``start`` opens a session with a random BuyerCookie ``<tenantCode>.<random>`` (the tenant code lets the public return
   endpoint open a tenant-scoped transaction under RLS), then
   - cXML: builds a PunchOutSetupRequest (From/To/Sender credentials with the shared secret, BuyerCookie,
     BrowserFormPost URL = our return endpoint), POSTs it to the supplier and reads StartPage/URL from the
     PunchOutSetupResponse;
   - OCI: returns the supplier URL with the HOOK_URL form fields; the browser posts them to the supplier.
3. The supplier posts the cart back through the browser to ``receive`` (cXML PunchOutOrderMessage in ``cxml-urlencoded``
   / ``cxml-base64``, or OCI ``NEW_ITEM-*`` fields). The session must be OPEN and not expired.
4. ``convert`` turns the normalised cart into CATALOGUE requisition lines (supplier part number, preferred supplier,
   returned price) through the requisition service, so policy, budget and DMN-01 apply on submit as usual. A returned price
   more than the tolerance (rule PUNCHOUT ``priceTolerancePct``, default 2%) above the hosted catalogue price is refused;
   items not in the hosted catalogue become FREE_TEXT lines (quote policy; the cart counts as the supplier's quote).

A built-in test supplier (``punchout.url == "builtin"``) answers the setup request in-process, serves a small catalogue
page from the supplier's ``catalogue_item`` rows and posts a real PunchOutOrderMessage / OCI form back, so the whole
flow runs end-to-end without an external catalogue. The stored setup request never contains the shared secret.
"""
import base64
import html
import re
import secrets
import xml.etree.ElementTree as ET
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional
from urllib.parse import parse_qs, quote, urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import CatalogueItem, PunchoutSession, Requisition, Supplier, SupplierCategoryStatus, Tenant
from app.pic.platform import audit, clock, crypto, outbox, rules
from app.pic.platform.core import link, next_number
from app.pic.platform.errors import Problem, not_found
from app.pic.platform.serialize import row
from app.pic.services.common import principal

RULE = "PUNCHOUT"
BUILTIN = "builtin"
CXML_DOCTYPE = '<!DOCTYPE cXML SYSTEM "http://xml.cxml.org/schemas/cXML/1.2.014/cXML.dtd">'
MAX_DOCUMENT = 1_000_000
USER_AGENT = "AlphaHelion PIC punch-out 1.0"
UOM_ALIASES = {"C62": "EA", "H87": "EA", "PCE": "EA", "PC": "EA", "EACH": "EA", "ST": "EA", "NOS": "EA", "NO": "EA"}
MASKED_SECRET = "********"
DEFAULT_PRICE_TOLERANCE_PCT = "2"


# ---------------------------------------------------------------- helpers
def _web_url() -> str:
    from app.pic.services.invitations import web_url
    return web_url()


def return_url() -> str:
    """Browser form-post target for returned carts: the web app's public BFF route, which forwards to POST /v1/punchout/return."""
    return f"{_web_url()}/api/public/punchout/return"


def simulator_url(path: str) -> str:
    return f"{_web_url()}/api/pic/v1/punchout/simulator/{path}"


def tenant_code_of(cookie: str) -> Optional[str]:
    code, sep, rest = (cookie or "").partition(".")
    return code if sep and code and rest and len(cookie) <= 64 else None


def _secret(session: Session, supplier: Supplier) -> str:
    if not supplier.punchout_secret_enc:
        raise Problem(409, "PUNCHOUT_NOT_CONFIGURED", f"{supplier.code} has no punch-out shared secret", rule_ref="M04")
    return crypto.decrypt(current_tenant(session), "punchout", supplier.punchout_secret_enc.encode())


def _number_of(ps: PunchoutSession) -> Optional[str]:
    """The PUN- number travels in the cXML payloadID (or the OCI ~PIC_SESSION field) of the stored setup request."""
    document = ps.setup_request or ""
    if document.lstrip().startswith("<"):
        match = re.search(r'payloadID="([^".@]+)', document)
        return match.group(1) if match else None
    return (parse_qs(document).get("~PIC_SESSION") or [None])[0]


def parse_xml(document: str) -> ET.Element:
    """Parse a partner cXML document. External entities are never resolved; entity declarations are refused outright."""
    if not document or len(document) > MAX_DOCUMENT:
        raise Problem(413 if document else 422, "INVALID_CXML", "cXML document is empty or larger than 1 MB")
    if "<!ENTITY" in document.upper():
        raise Problem(422, "INVALID_CXML", "cXML documents with entity declarations are refused")
    try:
        return ET.fromstring(document.encode() if isinstance(document, str) else document)
    except ET.ParseError as exc:
        raise Problem(422, "INVALID_CXML", f"cXML document is not well-formed: {exc}")


def _text(node: Optional[ET.Element], path: str) -> Optional[str]:
    found = node.find(path) if node is not None else None
    return found.text.strip() if found is not None and found.text else None


def _money_minor(value: Optional[str]) -> int:
    raw = (value or "").strip().replace(" ", "")
    if raw.count(",") and not raw.count("."):
        raw = raw.replace(",", ".")
    raw = raw.replace(",", "")
    try:
        return int((Decimal(raw) * 100).quantize(Decimal("1")))
    except (InvalidOperation, ValueError):
        raise Problem(422, "INVALID_CART", f"price '{value}' is not a number")


def _qty(value: Optional[str]) -> Decimal:
    try:
        qty = Decimal((value or "").strip().replace(",", "."))
    except InvalidOperation:
        raise Problem(422, "INVALID_CART", f"quantity '{value}' is not a number")
    if qty <= 0:
        raise Problem(422, "INVALID_CART", "every returned item needs a positive quantity")
    return qty


def _uom(value: Optional[str]) -> str:
    code = (value or "EA").strip().upper()
    return UOM_ALIASES.get(code, code)[:5] or "EA"


def _timestamp() -> str:
    return clock.now().astimezone(clock.IST).isoformat(timespec="seconds")


def _cxml(payload_id: str) -> ET.Element:
    root = ET.Element("cXML", {"payloadID": payload_id, "timestamp": _timestamp()})
    root.set("xml:lang", "en-US")
    return root


def _serialise(root: ET.Element) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + CXML_DOCTYPE + "\n" + ET.tostring(root, encoding="unicode")


def _credential(parent: ET.Element, tag: str, domain: str, identity: str, secret: Optional[str] = None) -> None:
    node = ET.SubElement(ET.SubElement(parent, tag), "Credential", {"domain": domain})
    ET.SubElement(node, "Identity").text = identity
    if secret is not None:
        ET.SubElement(node, "SharedSecret").text = secret


# ---------------------------------------------------------------- 1. supplier configuration
def configure(session: Session, supplier: Supplier, *, protocol: str, url: str, identity: str, shared_secret: Optional[str]) -> dict:
    rule = rules.resolve(session, RULE)
    protocol = (protocol or "").upper()
    url = (url or "").strip()
    identity = (identity or "").strip()
    errors = []
    if protocol not in rule.body.get("protocols", ["CXML", "OCI"]):
        errors.append(f"protocol must be one of {', '.join(rule.body.get('protocols', ['CXML', 'OCI']))}")
    if url != BUILTIN and not re.match(r"^https?://[^\s/$.?#].[^\s]*$", url):
        errors.append("url must be the supplier's http(s) punch-out address, or 'builtin' for the built-in test catalogue")
    if not identity or len(identity) > 100:
        errors.append("identity (the supplier's network / DUNS id or OCI user) is required")
    if shared_secret is not None and len(shared_secret) < 8:
        errors.append("the shared secret must be at least 8 characters")
    if shared_secret is None and not supplier.punchout_secret_enc:
        errors.append("a shared secret is required the first time punch-out is configured")
    if errors:
        raise Problem(422, "VALIDATION_FAILED", "; ".join(errors), rule_ref=rule.ref, errors=errors)
    before = dict(supplier.punchout or {})
    supplier.punchout = {"protocol": protocol, "url": url, "identity": identity, "configuredAt": clock.now().isoformat(),
                         "configuredBy": principal(session).actor}
    if shared_secret is not None:
        supplier.punchout_secret_enc = crypto.encrypt(current_tenant(session), "punchout", shared_secret).decode()
    audit.record(session, "SUPPLIER", supplier.id, "PUNCHOUT_CONFIGURED", object_ref=supplier.code,
                 before={k: before.get(k) for k in ("protocol", "url", "identity")},
                 after={"protocol": protocol, "url": url, "identity": identity, "secretChanged": shared_secret is not None},
                 rule_set_version=rule.ref)
    return {"supplier": supplier.code, **supplier.punchout, "secretConfigured": bool(supplier.punchout_secret_enc)}


def configured_suppliers(session: Session) -> list[dict]:
    return [{"code": s.code, "name": s.legal_name, "status": s.status, "protocol": s.punchout.get("protocol"),
             "builtin": s.punchout.get("url") == BUILTIN}
            for s in session.execute(select(Supplier).where(Supplier.status != "BLOCKED").order_by(Supplier.code)).scalars()
            if (s.punchout or {}).get("url") and s.punchout_secret_enc]


# ---------------------------------------------------------------- 2. setup
def build_setup_request(*, payload_id: str, buyer_identity: str, supplier_identity: str, secret: str, cookie: str,
                        form_post: str, supplier_url: str, user_email: str, user_name: str) -> str:
    root = _cxml(payload_id)
    header = ET.SubElement(root, "Header")
    _credential(header, "From", "NetworkID", buyer_identity)
    _credential(header, "To", "NetworkID", supplier_identity)
    _credential(header, "Sender", "NetworkID", buyer_identity, secret)
    ET.SubElement(header.find("Sender"), "UserAgent").text = USER_AGENT
    request = ET.SubElement(ET.SubElement(root, "Request", {"deploymentMode": "production"}), "PunchOutSetupRequest",
                            {"operation": "create"})
    ET.SubElement(request, "BuyerCookie").text = cookie
    ET.SubElement(request, "Extrinsic", {"name": "UserEmail"}).text = user_email
    ET.SubElement(request, "Extrinsic", {"name": "UniqueName"}).text = user_email
    ET.SubElement(request, "Extrinsic", {"name": "UserFullName"}).text = user_name
    ET.SubElement(ET.SubElement(request, "BrowserFormPost"), "URL").text = form_post
    ET.SubElement(ET.SubElement(request, "SupplierSetup"), "URL").text = supplier_url
    return _serialise(root)


def parse_setup_response(document: str) -> str:
    root = parse_xml(document)
    status = root.find("./Response/Status")
    code = status.get("code") if status is not None else None
    if code != "200":
        text = (status.get("text") if status is not None else None) or "no status"
        raise Problem(502, "PUNCHOUT_SETUP_FAILED", f"The supplier refused the punch-out setup: {code} {text}", rule_ref="M04")
    url = _text(root, "./Response/PunchOutSetupResponse/StartPage/URL")
    if not url or not re.match(r"^https?://", url):
        raise Problem(502, "PUNCHOUT_SETUP_FAILED", "The supplier's PunchOutSetupResponse has no StartPage URL", rule_ref="M04")
    return url


def _post_setup(url: str, document: str) -> str:
    try:
        response = httpx.post(url, content=document.encode(), headers={"content-type": "text/xml; charset=utf-8",
                                                                     "user-agent": USER_AGENT}, timeout=20)
    except httpx.HTTPError as exc:
        raise Problem(502, "PUNCHOUT_UNREACHABLE", f"The supplier's punch-out endpoint did not answer: {type(exc).__name__}", rule_ref="M04")
    if response.status_code >= 400:
        raise Problem(502, "PUNCHOUT_SETUP_FAILED", f"The supplier's punch-out endpoint returned HTTP {response.status_code}", rule_ref="M04")
    return response.text


def start(session: Session, supplier: Supplier) -> dict:
    p = principal(session)
    if supplier.status == "BLOCKED":
        raise Problem(409, "SUPPLIER_BLOCKED", f"{supplier.code} is blocked", rule_ref="SLM")
    config = supplier.punchout or {}
    if not config.get("url"):
        raise Problem(409, "PUNCHOUT_NOT_CONFIGURED", f"{supplier.code} has no punch-out catalogue configured", rule_ref="M04")
    rule = rules.resolve(session, RULE)
    secret = _secret(session, supplier)
    tenant_code = p.tenant_code or session.execute(select(Tenant.code).where(Tenant.id == current_tenant(session))).scalar()
    cookie = f"{tenant_code}.{secrets.token_urlsafe(24)}"
    number = next_number(session, "PUNCHOUT")
    ps = PunchoutSession(tenant_id=current_tenant(session), supplier_id=supplier.id, user_id=p.user_id, protocol=config["protocol"],
                         buyer_cookie=cookie, status="OPEN", cart=[], created_by=p.user_id,
                         expires_at=clock.now() + timedelta(minutes=int(rule.body.get("sessionMinutes", 30))))
    builtin = config["url"] == BUILTIN
    form: dict = {}
    if config["protocol"] == "CXML":
        payload_id = f"{number}.{clock.now().strftime('%Y%m%d%H%M%S')}@{tenant_code.lower()}.pic"
        args = dict(payload_id=payload_id, buyer_identity=tenant_code, supplier_identity=config["identity"], cookie=cookie,
                    form_post=return_url(), supplier_url=config["url"] if not builtin else simulator_url("setup"),
                    user_email=p.email, user_name=p.name)
        document = build_setup_request(secret=secret, **args)
        ps.setup_request = build_setup_request(secret=MASKED_SECRET, **args)
        session.add(ps)
        session.flush()
        answer = simulator_setup(session, document) if builtin else _post_setup(config["url"], document)
        ps.start_url = parse_setup_response(answer)[:500]
        method = "GET"
    else:
        hook = f"{return_url()}?cookie={quote(cookie, safe='')}"
        form = {"USERNAME": config["identity"], "PASSWORD": secret, "HOOK_URL": hook, "OCI_VERSION": "4.0", "~OkCode": "ADDI",
                "~TARGET": "_top", "~CALLER": "CTLG", "returntarget": "_top"}
        ps.setup_request = urlencode({**form, "PASSWORD": MASKED_SECRET, "~PIC_SESSION": number})
        ps.start_url = (simulator_url("catalogue") if builtin else config["url"])[:500]
        session.add(ps)
        session.flush()
        method = "POST"
    audit.record(session, "PUNCHOUT_SESSION", ps.id, "PUNCHOUT_STARTED", object_ref=number,
                 after={"supplier": supplier.code, "protocol": ps.protocol, "builtin": builtin, "expiresAt": ps.expires_at},
                 rule_set_version=rule.ref)
    return {**view(session, ps, supplier), "startUrl": ps.start_url, "method": method, "formFields": form}


# ---------------------------------------------------------------- 3. return
def _parse_cxml_cart(document: str) -> tuple[Optional[str], list[dict]]:
    root = parse_xml(document)
    message = root.find("./Message/PunchOutOrderMessage")
    if message is None:
        raise Problem(422, "INVALID_CXML", "The document is not a PunchOutOrderMessage")
    cookie = _text(message, "BuyerCookie")
    header_currency = None
    total = message.find("./PunchOutOrderMessageHeader/Total/Money")
    if total is not None:
        header_currency = total.get("currency")
    items = []
    for index, item in enumerate(message.findall("ItemIn"), start=1):
        detail = item.find("ItemDetail")
        money = detail.find("./UnitPrice/Money") if detail is not None else None
        classification = {c.get("domain") or "UNKNOWN": (c.text or "").strip() for c in (detail.findall("Classification") if detail is not None else [])}
        description = detail.find("Description") if detail is not None else None
        desc_text = " ".join("".join(description.itertext()).split()) if description is not None else None
        items.append({
            "lineNo": index, "supplierPartNo": _text(item, "./ItemID/SupplierPartID"),
            "supplierPartAuxId": _text(item, "./ItemID/SupplierPartAuxiliaryID"), "description": desc_text,
            "qty": str(_qty(item.get("quantity"))), "uom": _uom(_text(detail, "UnitOfMeasure")),
            "unitPriceMinor": _money_minor(money.text if money is not None else None),
            "currency": (money.get("currency") if money is not None else None) or header_currency or "INR",
            "classification": classification, "unspsc": classification.get("UNSPSC") or classification.get("unspsc"),
            "manufacturerPartNo": _text(detail, "ManufacturerPartID"), "leadTimeDays": _text(detail, "LeadTime"),
        })
    return cookie, items


def _parse_oci_cart(form: dict) -> list[dict]:
    indexes = sorted({int(m.group(1)) for key in form for m in [re.match(r"^NEW_ITEM-[A-Z_]+\[(\d+)\]$", key)] if m})
    items = []
    for n in indexes:
        get = lambda field: (form.get(f"NEW_ITEM-{field}[{n}]") or "").strip() or None  # noqa: E731
        price_unit = _qty(get("PRICEUNIT") or "1")
        unit_price = (Decimal(_money_minor(get("PRICE"))) / price_unit).quantize(Decimal("1"))
        unspsc = get("EXT_CATEGORY_ID")
        items.append({
            "lineNo": len(items) + 1, "supplierPartNo": get("VENDORMAT") or get("EXT_PRODUCT_ID"), "supplierPartAuxId": get("EXT_PRODUCT_ID"),
            "description": get("DESCRIPTION"), "qty": str(_qty(get("QUANTITY"))), "uom": _uom(get("UNIT")),
            "unitPriceMinor": int(unit_price), "currency": get("CURRENCY") or "INR",
            "classification": {k: v for k, v in (("UNSPSC", unspsc), ("MATGROUP", get("MATGROUP"))) if v}, "unspsc": unspsc,
            "materialGroup": get("MATGROUP"), "manufacturerPartNo": get("MANUFACTMAT"), "leadTimeDays": get("LEADTIME"),
        })
    return items


def decode_return(form: dict, query_cookie: Optional[str]) -> tuple[Optional[str], str, list[dict], str]:
    """Return (cookie, protocol, items, document) from a browser form post (cXML or OCI)."""
    if form.get("cxml-base64"):
        try:
            document = base64.b64decode(form["cxml-base64"]).decode("utf-8")
        except Exception:  # noqa: BLE001
            raise Problem(422, "INVALID_CXML", "cxml-base64 is not valid base64 UTF-8")
    elif form.get("cxml-urlencoded"):
        document = form["cxml-urlencoded"]
        if document.lstrip().startswith("%3C") or document.lstrip().startswith("%3c"):
            from urllib.parse import unquote_plus
            document = unquote_plus(document)
    else:
        document = None
    if document is not None:
        cookie, items = _parse_cxml_cart(document)
        return cookie or query_cookie, "CXML", items, document
    if any(k.startswith("NEW_ITEM-") for k in form):
        items = _parse_oci_cart(form)
        return query_cookie or form.get("cookie") or form.get("BUYER_COOKIE"), "OCI", items, urlencode(sorted(form.items()))
    raise Problem(422, "INVALID_CART", "Expected a cXML PunchOutOrderMessage (cxml-urlencoded / cxml-base64) or OCI NEW_ITEM fields")


def receive(session: Session, cookie: str, protocol: str, items: list[dict], document: str) -> PunchoutSession:
    ps = session.execute(select(PunchoutSession).where(PunchoutSession.buyer_cookie == cookie).with_for_update()).scalar_one_or_none()
    if ps is None:
        raise Problem(404, "PUNCHOUT_SESSION_NOT_FOUND", "No punch-out session matches this BuyerCookie")
    number = _number_of(ps)
    if ps.status == "OPEN" and ps.expires_at <= clock.now():
        ps.status = "EXPIRED"
        audit.record(session, "PUNCHOUT_SESSION", ps.id, "PUNCHOUT_EXPIRED", object_ref=number,
                     reason="cart returned after the session expired", after={"expiredAt": ps.expires_at})
        return ps
    if ps.status != "OPEN":
        raise Problem(409, "PUNCHOUT_SESSION_CLOSED", f"The punch-out session is {ps.status}; start a new one", rule_ref="M04")
    if protocol != ps.protocol:
        raise Problem(422, "PROTOCOL_MISMATCH", f"The session uses {ps.protocol} but an {protocol} cart was returned", rule_ref="M04")
    if not items:
        raise Problem(422, "EMPTY_CART", "The supplier returned an empty cart", rule_ref="M04")
    ps.cart = items
    ps.cart_document = document[:MAX_DOCUMENT]
    ps.status = "RETURNED"
    total = sum(int(Decimal(i["qty"]) * i["unitPriceMinor"]) for i in items)
    supplier = session.get(Supplier, ps.supplier_id)
    audit.record(session, "PUNCHOUT_SESSION", ps.id, "PUNCHOUT_RETURNED", object_ref=number,
                 after={"supplier": supplier.code, "items": len(items), "totalMinor": total,
                        "parts": [i["supplierPartNo"] for i in items][:50]})
    outbox.emit(session, "punchout.cart.returned", "PUNCHOUT_SESSION", ps.id, number or cookie[:20],
                {"supplier": supplier.code, "items": len(items), "totalMinor": total, "protocol": protocol})
    return ps


# ---------------------------------------------------------------- 4. convert to requisition lines
def get(session: Session, cookie: str) -> PunchoutSession:
    ps = session.execute(select(PunchoutSession).where(PunchoutSession.buyer_cookie == cookie)).scalar_one_or_none()
    if ps is None or ps.user_id != principal(session).user_id:
        raise not_found("Punch-out session", cookie[:12] + "…")
    return ps


def view(session: Session, ps: PunchoutSession, supplier: Optional[Supplier] = None) -> dict:
    supplier = supplier or session.get(Supplier, ps.supplier_id)
    requisition = session.get(Requisition, ps.requisition_id) if ps.requisition_id else None
    status = "EXPIRED" if ps.status == "OPEN" and ps.expires_at <= clock.now() else ps.status
    return row(ps, only=("id", "protocol", "buyer_cookie", "start_url", "cart", "status", "expires_at", "created_at"), extra={
        "status": status, "number": _number_of(ps), "supplier": {"code": supplier.code, "name": supplier.legal_name},
        "requisition": requisition.number if requisition else None,
        "totalMinor": sum(int(Decimal(i["qty"]) * i["unitPriceMinor"]) for i in ps.cart or []),
    })


def convert(session: Session, ps: PunchoutSession, *, requisition: Optional[str] = None, plant: Optional[str] = None,
            purpose_code: Optional[str] = None, purpose_text: Optional[str] = None, need_date=None, purchase_type: Optional[str] = None,
            account_assignment_type: Optional[str] = None, account_assignment_code: Optional[str] = None,
            material_group: Optional[str] = None, category: Optional[str] = None) -> Requisition:
    from app.pic.services import requisition as req_svc

    p = principal(session)
    if ps.user_id != p.user_id:
        raise Problem(403, "FORBIDDEN", "Only the user who punched out can convert the cart")
    if ps.status == "CONVERTED":
        raise Problem(409, "PUNCHOUT_ALREADY_CONVERTED", "This cart was already added to a requisition", rule_ref="M04")
    if ps.status != "RETURNED":
        raise Problem(409, "PUNCHOUT_NOT_RETURNED", f"The punch-out session is {ps.status}; no cart to convert", rule_ref="M04")
    supplier = session.get(Supplier, ps.supplier_id)
    if supplier.status == "BLOCKED":
        raise Problem(409, "SUPPLIER_BLOCKED", f"{supplier.code} is blocked", rule_ref="SLM")
    number = _number_of(ps)
    catalogue = {c.supplier_part_no: c for c in session.execute(select(CatalogueItem).where(CatalogueItem.supplier_id == supplier.id)).scalars()}
    supplier_categories = [c.category for c in session.execute(select(SupplierCategoryStatus).where(
        SupplierCategoryStatus.supplier_id == supplier.id, SupplierCategoryStatus.status.in_(("QUALIFIED", "PREFERRED")))).scalars()]
    due = need_date or (clock.today() + timedelta(days=14))
    if account_assignment_type is None and account_assignment_code is None:
        default = next(iter(p.attr("cost_objects") or []), None)
        if default and ":" in default:
            account_assignment_type, account_assignment_code = default.split(":", 1)
    # A matched item's returned price may exceed the hosted catalogue price by at most this tolerance (rule PUNCHOUT
    # priceTolerancePct when the tenant sets it; default 2%, the "price > contract + 2%" deviation band of BP Table 24).
    tolerance = Decimal(str(rules.resolve(session, RULE).body.get("priceTolerancePct", DEFAULT_PRICE_TOLERANCE_PCT)))
    lines, problems = [], []
    for item in ps.cart or []:
        if (item.get("currency") or "INR") != "INR":
            problems.append(f"item {item['lineNo']}: currency {item['currency']} differs from the requisition currency INR")
            continue
        match = catalogue.get(item.get("supplierPartNo") or "")
        if match is not None and match.price_minor is not None:
            ceiling = Decimal(match.price_minor) * (1 + tolerance / 100)
            if Decimal(int(item["unitPriceMinor"])) > ceiling:
                problems.append(f"item {item['lineNo']} ({item.get('supplierPartNo')}): returned price {int(item['unitPriceMinor'])} paise is more "
                                f"than {tolerance}% above the catalogue price {match.price_minor} paise")
                continue
        group = (match.material_group if match else None) or item.get("materialGroup") or \
            (item.get("classification") or {}).get("MaterialGroup") or material_group or \
            (supplier_categories[0] if len(supplier_categories) == 1 else None)
        cat = (match.category if match else None) or category or group
        if not group:
            problems.append(f"item {item['lineNo']} ({item.get('supplierPartNo')}): no material group; give materialGroup")
            continue
        kind = (purchase_type or ("SERVICE" if "SERVICE" in (cat or "") else "NON_STOCK")).upper()
        # An item that is not in the supplier's hosted catalogue has no agreed price: it becomes a free-text line and the
        # quote policy applies on submit; the returned cart itself counts as that supplier's quote.
        unmatched = {} if match else {"quotes": [{"supplier": supplier.code, "reference": f"punch-out {number or ps.protocol}",
                                                  "date": clock.today()}]}
        lines.append({
            **unmatched,
            "item_type": "CATALOGUE" if match else "FREE_TEXT", "purchase_type": kind, "catalogue_item_id": str(match.id) if match else None,
            "description": (item.get("description") or (match.description if match else None) or item.get("supplierPartNo") or "")[:200],
            "material_group": group[:30], "category": (cat or group)[:40], "qty": item["qty"], "uom": item["uom"],
            "price_est_minor": int(item["unitPriceMinor"]), "need_date": due, "preferred_supplier_id": supplier.id,
            "account_assignment_type": account_assignment_type, "account_assignment_code": account_assignment_code,
            "punchout": True,
            "source_determination": {"method": "PUNCHOUT", "supplier": supplier.code, "supplierPartNo": item.get("supplierPartNo"),
                                     "supplierPartAuxId": item.get("supplierPartAuxId"), "unspsc": item.get("unspsc"),
                                     "classification": item.get("classification"), "session": number, "protocol": ps.protocol,
                                     "unitPriceMinor": int(item["unitPriceMinor"]), "currency": item.get("currency") or "INR",
                                     "catalogueMatch": bool(match)},
        })
    if problems:
        raise Problem(422, "CART_NOT_CONVERTIBLE", "; ".join(problems), rule_ref="M04", violations=problems)
    if requisition:
        pr = session.execute(select(Requisition).where(Requisition.number == requisition).with_for_update()).scalar_one_or_none()
        if pr is None:
            raise not_found("Requisition", requisition)
        first = len(req_svc._lines(session, pr))
        req_svc.add_lines(session, pr, lines, source=f"punch-out {number} ({supplier.code})")
        line_numbers = [l.line_no for l in req_svc._lines(session, pr)][first:]
    else:
        plants = [x for x in (p.attr("plants") or []) if x != "*"]
        plant = plant or (plants[0] if plants else None)
        if not plant:
            raise Problem(422, "PLANT_REQUIRED", "Give the plant for the new requisition")
        pr = req_svc.create(session, origin="CATALOGUE", lines=lines, plant=plant, purpose_code=purpose_code, purpose_text=purpose_text,
                            origin_ref=number)
        line_numbers = [l.line_no for l in req_svc._lines(session, pr)]
    ps.status = "CONVERTED"
    ps.requisition_id = pr.id
    for item, line_no in zip(ps.cart or [], line_numbers):
        link(session, "PUNCHOUT_SESSION", ps.id, number or "PUNCHOUT", "REQUISITION", pr.id, pr.number, "PUNCHOUT_CART",
             from_line=item["lineNo"], to_line=line_no)
    audit.record(session, "PUNCHOUT_SESSION", ps.id, "PUNCHOUT_CONVERTED", object_ref=number,
                 after={"requisition": pr.number, "lines": line_numbers})
    return pr


# ---------------------------------------------------------------- built-in test supplier (url == "builtin")
def _builtin_supplier(session: Session, identity: str) -> Supplier:
    for supplier in session.execute(select(Supplier)).scalars():
        config = supplier.punchout or {}
        if config.get("url") == BUILTIN and config.get("identity") == identity:
            return supplier
    raise Problem(404, "UNKNOWN_SUPPLIER", "No built-in punch-out catalogue for this identity")


def _setup_answer(code: str, text: str, start_url: Optional[str] = None) -> str:
    root = _cxml(f"{secrets.token_hex(8)}@builtin-supplier.pic")
    response = ET.SubElement(root, "Response")
    ET.SubElement(response, "Status", {"code": code, "text": text})
    if start_url:
        ET.SubElement(ET.SubElement(ET.SubElement(response, "PunchOutSetupResponse"), "StartPage"), "URL").text = start_url
    return _serialise(root)


def simulator_setup(session: Session, document: str) -> str:
    """The simulated supplier's setup endpoint: authenticate the Sender shared secret, answer with a StartPage."""
    root = parse_xml(document)
    identity = _text(root, "./Header/To/Credential/Identity")
    secret = _text(root, "./Header/Sender/Credential/SharedSecret")
    cookie = _text(root, "./Request/PunchOutSetupRequest/BuyerCookie")
    form_post = _text(root, "./Request/PunchOutSetupRequest/BrowserFormPost/URL")
    if not (identity and cookie and form_post):
        return _setup_answer("400", "Bad Request: To identity, BuyerCookie and BrowserFormPost are required")
    try:
        supplier = _builtin_supplier(session, identity)
    except Problem:
        return _setup_answer("401", "Unauthorized: unknown supplier identity")
    if not secrets.compare_digest((secret or "").encode(), _secret(session, supplier).encode()):
        return _setup_answer("401", "Unauthorized: shared secret does not match")
    return _setup_answer("200", "success", f"{simulator_url('catalogue')}?cookie={quote(cookie, safe='')}")


def _open_session(session: Session, cookie: Optional[str]) -> PunchoutSession:
    ps = session.execute(select(PunchoutSession).where(PunchoutSession.buyer_cookie == (cookie or ""))).scalar_one_or_none()
    if ps is None:
        raise Problem(404, "PUNCHOUT_SESSION_NOT_FOUND", "Unknown punch-out session")
    if ps.status != "OPEN" or ps.expires_at <= clock.now():
        raise Problem(410, "PUNCHOUT_SESSION_EXPIRED", "This punch-out session has ended; start again from the requisition")
    return ps


def _oci_form(ps: PunchoutSession) -> dict:
    return {k: v[0] for k, v in parse_qs(ps.setup_request or "").items()}


def simulator_catalogue(session: Session, cookie: Optional[str], form: dict) -> str:
    """HTML catalogue page of the simulated supplier (cXML: ?cookie=..., OCI: the posted HOOK_URL / USERNAME / PASSWORD)."""
    if not cookie and form.get("HOOK_URL"):
        match = re.search(r"[?&]cookie=([^&]+)", form["HOOK_URL"])
        from urllib.parse import unquote
        cookie = unquote(match.group(1)) if match else None
    ps = _open_session(session, cookie)
    supplier = session.get(Supplier, ps.supplier_id)
    if ps.protocol == "OCI":
        expected = _oci_form(ps)
        if form.get("USERNAME") != supplier.punchout.get("identity") or not secrets.compare_digest(
                (form.get("PASSWORD") or "").encode(), _secret(session, supplier).encode()) or form.get("HOOK_URL") != expected.get("HOOK_URL"):
            raise Problem(401, "UNAUTHORIZED", "OCI user, password or HOOK_URL do not match the punch-out configuration")
    items = session.execute(select(CatalogueItem).where(CatalogueItem.supplier_id == supplier.id, CatalogueItem.active.is_(True))
                            .order_by(CatalogueItem.supplier_part_no)).scalars().all()
    esc = html.escape
    rows_html = "".join(
        f"<tr><td><code>{esc(i.supplier_part_no)}</code></td><td>{esc(i.description)}</td><td>{esc(i.uom)}</td>"
        f"<td style='text-align:right'>&#8377;{i.price_minor / 100:,.2f}</td>"
        f"<td><input type='number' min='0' step='1' name='qty_{i.id}' value='0' aria-label='Quantity of {esc(i.supplier_part_no)}' "
        f"style='width:6em'></td></tr>" for i in items) or "<tr><td colspan='5'>This supplier has no catalogue items.</td></tr>"
    minutes = max(int((ps.expires_at - clock.now()).total_seconds() // 60), 0)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(supplier.legal_name)} – punch-out catalogue (test)</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px;color:#0f172a}}table{{border-collapse:collapse;width:100%;max-width:960px}}
td,th{{border-bottom:1px solid #e2e8f0;padding:8px;text-align:left;font-size:14px}}th{{background:#f8fafc;font-size:12px;text-transform:uppercase;color:#475569}}
button{{background:#1A56DB;color:#fff;border:0;border-radius:8px;padding:8px 16px;font-size:14px;cursor:pointer}}
.note{{background:#fffbeb;border:1px solid #fcd34d;border-radius:8px;padding:8px 12px;font-size:13px;max-width:960px}}</style></head>
<body><h1 style="font-size:20px">{esc(supplier.legal_name)} · online catalogue</h1>
<p class="note">Built-in test supplier for punch-out ({esc(ps.protocol)}). Choose quantities and transfer the cart back to the
purchasing workspace. This session ends in {minutes} minute(s).</p>
<form method="post" action="{esc(simulator_url('checkout'))}">
<input type="hidden" name="cookie" value="{esc(ps.buyer_cookie)}">
<table><thead><tr><th>Part no.</th><th>Description</th><th>Unit</th><th>Price</th><th>Quantity</th></tr></thead><tbody>{rows_html}</tbody></table>
<p><button type="submit">Transfer cart to requisition</button></p></form></body></html>"""


def build_order_message(ps: PunchoutSession, supplier: Supplier, picked: list[tuple[CatalogueItem, Decimal]]) -> str:
    root = _cxml(f"{secrets.token_hex(8)}@builtin-supplier.pic")
    header = ET.SubElement(root, "Header")
    _credential(header, "From", "NetworkID", supplier.punchout.get("identity", supplier.code))
    _credential(header, "To", "NetworkID", tenant_code_of(ps.buyer_cookie) or "BUYER")
    _credential(header, "Sender", "NetworkID", supplier.punchout.get("identity", supplier.code))
    ET.SubElement(header.find("Sender"), "UserAgent").text = "PIC built-in test supplier"
    message = ET.SubElement(ET.SubElement(root, "Message"), "PunchOutOrderMessage")
    ET.SubElement(message, "BuyerCookie").text = ps.buyer_cookie
    total = sum(Decimal(item.price_minor) * qty for item, qty in picked) / 100
    head = ET.SubElement(message, "PunchOutOrderMessageHeader", {"operationAllowed": "edit"})
    ET.SubElement(ET.SubElement(head, "Total"), "Money", {"currency": "INR"}).text = f"{total:.2f}"
    for item, qty in picked:
        node = ET.SubElement(message, "ItemIn", {"quantity": format(qty.normalize(), "f")})
        ids = ET.SubElement(node, "ItemID")
        ET.SubElement(ids, "SupplierPartID").text = item.supplier_part_no
        ET.SubElement(ids, "SupplierPartAuxiliaryID").text = str(item.id)
        detail = ET.SubElement(node, "ItemDetail")
        ET.SubElement(ET.SubElement(detail, "UnitPrice"), "Money", {"currency": item.currency or "INR"}).text = f"{item.price_minor / 100:.2f}"
        description = ET.SubElement(detail, "Description")
        description.set("xml:lang", "en")
        description.text = item.description
        ET.SubElement(detail, "UnitOfMeasure").text = item.uom
        if item.hsn_code:
            ET.SubElement(detail, "Classification", {"domain": "HSN"}).text = item.hsn_code
        ET.SubElement(detail, "Classification", {"domain": "MaterialGroup"}).text = item.material_group
    return _serialise(root)


def simulator_checkout(session: Session, form: dict) -> str:
    """Build the cart from the posted quantities and return an auto-submitting form that posts it to the buyer."""
    ps = _open_session(session, form.get("cookie"))
    supplier = session.get(Supplier, ps.supplier_id)
    items = {str(i.id): i for i in session.execute(select(CatalogueItem).where(CatalogueItem.supplier_id == supplier.id,
                                                                              CatalogueItem.active.is_(True))).scalars()}
    picked = []
    for key, value in form.items():
        if key.startswith("qty_") and key[4:] in items and (value or "").strip():
            try:
                qty = Decimal(value.strip())
            except InvalidOperation:
                continue
            if qty > 0:
                picked.append((items[key[4:]], qty))
    if not picked:
        raise Problem(422, "EMPTY_CART", "Choose a quantity for at least one item")
    esc = html.escape
    if ps.protocol == "CXML":
        root = parse_xml(ps.setup_request)
        target = _text(root, "./Request/PunchOutSetupRequest/BrowserFormPost/URL") or return_url()
        fields = {"cxml-urlencoded": build_order_message(ps, supplier, picked)}
    else:
        target = _oci_form(ps).get("HOOK_URL") or f"{return_url()}?cookie={quote(ps.buyer_cookie, safe='')}"
        fields = {}
        for n, (item, qty) in enumerate(picked, start=1):
            fields.update({f"NEW_ITEM-DESCRIPTION[{n}]": item.description, f"NEW_ITEM-QUANTITY[{n}]": format(qty.normalize(), "f"),
                           f"NEW_ITEM-UNIT[{n}]": item.uom, f"NEW_ITEM-PRICE[{n}]": f"{item.price_minor / 100:.2f}",
                           f"NEW_ITEM-PRICEUNIT[{n}]": "1", f"NEW_ITEM-CURRENCY[{n}]": item.currency or "INR",
                           f"NEW_ITEM-VENDORMAT[{n}]": item.supplier_part_no, f"NEW_ITEM-MATGROUP[{n}]": item.material_group,
                           f"NEW_ITEM-EXT_PRODUCT_ID[{n}]": str(item.id)})
    inputs = "".join(f'<input type="hidden" name="{esc(k)}" value="{esc(v)}">' for k, v in fields.items())
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Returning your cart…</title></head>
<body style="font-family:system-ui,sans-serif;margin:24px"><p>Returning {len(picked)} item(s) to your purchasing workspace…</p>
<form id="cart" method="post" action="{esc(target)}">{inputs}<noscript><button type="submit">Continue</button></noscript></form>
<script>document.getElementById('cart').submit();</script></body></html>"""

