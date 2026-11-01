"""SAP Gateway OData client (v2 and v4) and IDoc transports for the S/4HANA connector (Technical Document §12.1).

Transport only; the SAP field mappings are in ``sap_mapping.py`` and the connector in ``connectors.py``.

OData behaviour implemented (as documented by SAP for the released APIs on SAP API Business Hub):
  * Basic or bearer authentication, optional ``sap-client`` query parameter.
  * CSRF protection: a modifying request needs the token returned by a GET with ``x-csrf-token: Fetch`` *in the same HTTP
    session* (the token is bound to the session cookies, so a cookie jar is used). A 403 answered with
    ``x-csrf-token: Required`` makes the client fetch a new token and repeat the request once.
  * JSON payloads. v2 wraps results in ``d`` / ``d.results`` and pages with ``__next``; v4 uses ``value`` and ``@odata.nextLink``.
  * ``$batch`` (multipart/mixed) with optional change sets, parsed back into one result per operation.
  * Retries with exponential back-off for connection errors, 429, 502, 503 and 504 on reads; modifying requests are repeated
    only for 429 and 503 (SAP did not process them). A timeout after a POST is *not* repeated here: the outbox retries and
    ``find`` (query by the PIC reference) decides whether the document already exists.
  * Structured errors: the SAP error code, message, inner error details and whether a retry can help (``SapODataError``).
"""
import base64
import http.cookiejar
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from xml.etree import ElementTree

from app.pic.platform.integration import ConnectorError, ConnectorTimeout

RETRY_STATUS = (429, 502, 503, 504)


class SapODataError(ConnectorError):
    """SAP answered with an error. ``code`` is SAP's message class/number (e.g. ``06/018``), ``retryable`` says whether the same
    request can succeed later (gateway overload) as opposed to a business rejection (missing master data, closed period)."""

    def __init__(self, message: str, *, status: int = 0, code: Optional[str] = None, details: Optional[list] = None, retryable: bool = False,
                 url: Optional[str] = None):
        super().__init__(message)
        self.status, self.code, self.details, self.retryable, self.url = status, code, details or [], retryable, url

    def as_dict(self) -> dict:
        return {"status": self.status, "code": self.code, "message": str(self), "details": self.details, "retryable": self.retryable}


def parse_error(status: int, text: str, content_type: str = "", url: str = "") -> SapODataError:
    """Parse a v2/v4 JSON or an XML OData error body into a structured error."""
    code, message, details = None, (text or "").strip()[:300], []
    body = (text or "").strip()
    try:
        if body.startswith("{"):
            error = (json.loads(body) or {}).get("error") or {}
            code = error.get("code")
            raw = error.get("message")
            message = (raw.get("value") if isinstance(raw, dict) else raw) or message
            inner = (error.get("innererror") or {}).get("errordetails") or error.get("details") or []
            details = [{"code": d.get("code"), "message": d.get("message"), "severity": d.get("severity")} for d in inner if isinstance(d, dict)]
        elif body.startswith("<"):
            root = ElementTree.fromstring(body)
            for el in root.iter():
                tag = el.tag.rsplit("}", 1)[-1]
                if tag == "code" and code is None:
                    code = (el.text or "").strip() or None
                elif tag == "message" and el.text and el.text.strip():
                    message = el.text.strip()
    except (ValueError, ElementTree.ParseError, AttributeError):
        pass
    label = f"SAP {status}" + (f" [{code}]" if code else "")
    return SapODataError(f"{label}: {message}", status=status, code=str(code) if code else None, details=details,
                         retryable=status in RETRY_STATUS or status >= 500, url=url.split("?")[0])


def odata_date(value, version: int = 2) -> Optional[str]:
    """A date for a payload: ``/Date(ms)/`` for v2 JSON (what Gateway accepts for Edm.DateTime), ISO for v4."""
    if value is None:
        return None
    iso = value.isoformat()[:10]
    if version == 4:
        return iso
    from datetime import datetime, timezone
    ms = int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() * 1000)
    return f"/Date({ms})/"


def literal(value: Any) -> str:
    """OData string literal for ``$filter`` (single quotes doubled)."""
    return "'" + str(value).replace("'", "''") + "'"


@dataclass
class BatchOp:
    method: str
    path: str                    # relative to the service root, e.g. "A_PurchaseOrder('4500000001')"
    body: Optional[dict] = None
    changeset: bool = False      # modifying operations of a batch share one change set (all or nothing) when True


@dataclass
class BatchResult:
    status: int
    headers: dict
    data: Any = None
    error: Optional[SapODataError] = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class ODataClient:
    """One SAP Gateway endpoint. Not thread-safe (holds the cookie jar and CSRF token); create one per use."""

    def __init__(self, base_url: str, *, user: Optional[str] = None, password: Optional[str] = None, token: Optional[str] = None,
                 sap_client: Optional[str] = None, version: int = 2, timeout: float = 20, retries: int = 2, backoff: float = 0.5,
                 sleep: Callable[[float], None] = time.sleep):
        self.base_url = base_url.rstrip("/")
        self.user, self.password, self.token = user, password, token
        self.sap_client = sap_client
        self.version = 4 if int(version) == 4 else 2
        self.timeout, self.retries, self.backoff, self.sleep = timeout, retries, backoff, sleep
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf: Optional[str] = None
        self.requests = 0          # HTTP calls made (for tests and metrics)

    # ------------------------------------------------------------ plumbing
    def _headers(self, extra: Optional[dict] = None) -> dict:
        headers = {"accept": "application/json", "x-requested-with": "XMLHttpRequest"}
        if self.token:
            headers["authorization"] = f"Bearer {self.token}"
        elif self.user:
            headers["authorization"] = "Basic " + base64.b64encode(f"{self.user}:{self.password or ''}".encode()).decode()
        if self.version == 4:
            headers["odata-version"] = "4.0"
        headers.update(extra or {})
        return headers

    def _url(self, service: str, path: str, params: Optional[dict] = None) -> str:
        url = f"{self.base_url}/{service.strip('/')}/{path.lstrip('/')}" if path else f"{self.base_url}/{service.strip('/')}/"
        query = dict(params or {})
        if self.sap_client:
            query.setdefault("sap-client", self.sap_client)
        if self.version == 2 and path != "$batch":
            query.setdefault("$format", "json")
        return url + ("?" + urllib.parse.urlencode(query, quote_via=urllib.parse.quote) if query else "")

    def _send(self, method: str, url: str, headers: dict, body: Optional[bytes]) -> tuple[int, dict, str]:
        request = urllib.request.Request(url, data=body, method=method, headers=headers)
        self.requests += 1
        try:
            with self.opener.open(request, timeout=self.timeout) as response:  # noqa: S310 - operator-configured URL
                return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, exc.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ConnectorTimeout(f"{url.split('?')[0]} not reachable: {exc}")

    def fetch_csrf(self, service: str) -> str:
        status, headers, text = self._send("GET", self._url(service, ""), self._headers({"x-csrf-token": "Fetch"}), None)
        token = headers.get("x-csrf-token")
        if status >= 400 or not token or token.lower() == "required":
            raise parse_error(status, text, headers.get("content-type", ""), service) if status >= 400 else SapODataError(
                "SAP did not return an x-csrf-token", status=status, url=service)
        self.csrf = token
        return token

    def request(self, method: str, service: str, path: str = "", *, params: Optional[dict] = None, body: Optional[dict] = None,
                headers: Optional[dict] = None, raw: Optional[bytes] = None, content_type: str = "application/json") -> tuple[int, dict, str]:
        """One OData call with CSRF handling and retries. Returns (status, headers, text) for 2xx; raises ``SapODataError``."""
        method = method.upper()
        modifying = method in ("POST", "PUT", "PATCH", "MERGE", "DELETE")
        url = self._url(service, path, params)
        payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        csrf_retried = False
        attempts = self.retries + 1
        delay = self.backoff
        for attempt in range(1, attempts + 1):
            send_headers = self._headers({"content-type": content_type, **(headers or {})} if modifying or payload else headers)
            if modifying:
                if not self.csrf:
                    self.fetch_csrf(service)
                send_headers["x-csrf-token"] = self.csrf
            try:
                status, response_headers, text = self._send(method, url, send_headers, payload)
            except ConnectorTimeout:
                if modifying or attempt >= attempts:   # a repeated POST could create a second document: the outbox + find decide
                    raise
                self.sleep(delay)
                delay *= 2
                continue
            if modifying and status == 403 and (response_headers.get("x-csrf-token") or "").lower() == "required" and not csrf_retried:
                csrf_retried = True
                self.csrf = None
                continue
            if 200 <= status < 300:
                return status, response_headers, text
            error = parse_error(status, text, response_headers.get("content-type", ""), url)
            retry_ok = status in (429, 503) if modifying else status in RETRY_STATUS
            if retry_ok and attempt < attempts:
                wait = response_headers.get("retry-after")
                self.sleep(min(float(wait), 30) if wait and wait.replace(".", "", 1).isdigit() else delay)
                delay *= 2
                continue
            raise error
        raise SapODataError("SAP request failed after retries", url=url)  # pragma: no cover - the loop always returns or raises

    # ------------------------------------------------------------ JSON helpers
    def _json(self, text: str) -> Any:
        try:
            return json.loads(text) if text and text.strip() else {}
        except ValueError:
            raise SapODataError(f"SAP answered with unreadable JSON: {(text or '')[:200]}", retryable=False)

    def unwrap(self, payload: Any) -> Any:
        """The entity or list of entities of a response, without OData metadata."""
        if isinstance(payload, dict) and "d" in payload:
            payload = payload["d"]
        if isinstance(payload, dict) and isinstance(payload.get("results"), list):
            payload = payload["results"]
        elif isinstance(payload, dict) and isinstance(payload.get("value"), list):
            payload = payload["value"]
        return self._strip(payload)

    def _strip(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self._strip(v) for v in value]
        if isinstance(value, dict):
            return {k: self._strip(v) for k, v in value.items() if k != "__metadata" and not k.startswith("@odata") and k != "__deferred"}
        return value

    @staticmethod
    def _next(payload: Any) -> Optional[str]:
        if isinstance(payload, dict):
            return (payload.get("d") or {}).get("__next") if isinstance(payload.get("d"), dict) else payload.get("@odata.nextLink")
        return None

    # ------------------------------------------------------------ operations
    def query(self, service: str, entity_set: str, *, filter: Optional[str] = None, select: Optional[str] = None, top: Optional[int] = None,
              orderby: Optional[str] = None, expand: Optional[str] = None, max_pages: int = 50, extra: Optional[dict] = None) -> list[dict]:
        """All entities of a set (following server-side paging), as plain dicts."""
        params = {k: v for k, v in {"$filter": filter, "$select": select, "$orderby": orderby, "$expand": expand,
                                    "$top": str(top) if top is not None else None, **(extra or {})}.items() if v}
        out: list[dict] = []
        status, headers, text = self.request("GET", service, entity_set, params=params)
        for _ in range(max_pages):
            payload = self._json(text)
            data = self.unwrap(payload)
            out.extend(data if isinstance(data, list) else [data] if data else [])
            next_link = self._next(payload)
            if not next_link or (top is not None and len(out) >= top):
                break
            url = next_link if next_link.startswith("http") else f"{self.base_url}/{service.strip('/')}/{next_link.lstrip('/')}"
            status, headers, text = self._follow(url)
        return out

    def _follow(self, url: str) -> tuple[int, dict, str]:
        status, headers, text = self._send("GET", url, self._headers(), None)
        if status >= 400:
            raise parse_error(status, text, headers.get("content-type", ""), url)
        return status, headers, text

    def get(self, service: str, path: str, params: Optional[dict] = None) -> Optional[dict]:
        """One entity by key path (``A_Product('X')``); None when SAP answers 404."""
        try:
            _, _, text = self.request("GET", service, path, params=params)
        except SapODataError as exc:
            if exc.status == 404:
                return None
            raise
        data = self.unwrap(self._json(text))
        return data if isinstance(data, dict) else None

    def create(self, service: str, entity_set: str, body: dict) -> dict:
        _, _, text = self.request("POST", service, entity_set, body=body)
        data = self.unwrap(self._json(text))
        return data if isinstance(data, dict) else {}

    def update(self, service: str, path: str, body: dict) -> None:
        method = "PATCH"
        self.request(method, service, path, body=body)

    # ------------------------------------------------------------ $batch
    def batch(self, service: str, operations: list[BatchOp]) -> list[BatchResult]:
        """Send operations in one ``$batch`` request: reads individually, all ``changeset=True`` operations in one change set.
        Returns one result per operation in the order given (a failed change set repeats its error for each member)."""
        batch_id, changeset_id = f"batch_{uuid.uuid4().hex}", f"changeset_{uuid.uuid4().hex}"
        parts: list[str] = []
        changeset_ops = [op for op in operations if op.changeset]
        if changeset_ops and not self.csrf:
            self.fetch_csrf(service)

        def http_part(op: BatchOp, content_id: Optional[int] = None) -> str:
            lines = ["Content-Type: application/http", "Content-Transfer-Encoding: binary"]
            if content_id is not None:
                lines.append(f"Content-ID: {content_id}")
            lines += ["", f"{op.method.upper()} {op.path} HTTP/1.1", "Accept: application/json"]
            if op.body is not None:
                lines += ["Content-Type: application/json", ""]
                return "\r\n".join(lines) + "\r\n" + json.dumps(op.body) + "\r\n"
            return "\r\n".join(lines) + "\r\n\r\n"

        index_of: list[tuple[str, int]] = []
        for op in operations:
            if not op.changeset:
                parts.append(f"--{batch_id}\r\n" + http_part(op))
                index_of.append(("read", 0))
        if changeset_ops:
            inner = "".join(f"--{changeset_id}\r\n" + http_part(op, n) for n, op in enumerate(changeset_ops, start=1))
            parts.append(f"--{batch_id}\r\nContent-Type: multipart/mixed; boundary={changeset_id}\r\n\r\n{inner}--{changeset_id}--\r\n")
        body = ("".join(parts) + f"--{batch_id}--\r\n").encode()
        _, headers, text = self.request("POST", f"{service}", "$batch", raw=body, content_type=f"multipart/mixed; boundary={batch_id}",
                                        headers={"accept": "multipart/mixed"})
        results = self.parse_batch(headers.get("content-type", ""), text)
        # Responses come in request order: reads first, then the change set members (one error response covers a failed set).
        ordered: list[BatchResult] = []
        reads = [r for r in results if r is not None]
        n_reads = sum(1 for op in operations if not op.changeset)
        read_results, set_results = reads[:n_reads], reads[n_reads:]
        if changeset_ops and len(set_results) == 1 and len(changeset_ops) > 1 and not set_results[0].ok:
            set_results = set_results * len(changeset_ops)
        read_iter, set_iter = iter(read_results), iter(set_results)
        for op in operations:
            ordered.append(next(set_iter if op.changeset else read_iter, BatchResult(0, {}, error=SapODataError("missing batch response"))))
        return ordered

    def parse_batch(self, content_type: str, text: str) -> list[BatchResult]:
        match = re.search(r"boundary=\"?([^\";\s]+)\"?", content_type or "")
        if not match:
            raise SapODataError(f"SAP $batch answer has no multipart boundary: {(text or '')[:200]}")
        return self._parse_multipart(match.group(1), text)

    def _parse_multipart(self, boundary: str, text: str) -> list[BatchResult]:
        results: list[BatchResult] = []
        for chunk in text.split(f"--{boundary}"):
            chunk = chunk.lstrip("\r\n")
            if not chunk or chunk.startswith("--"):
                continue
            head, _, rest = chunk.partition("\r\n\r\n") if "\r\n\r\n" in chunk else chunk.partition("\n\n")
            inner = re.search(r"boundary=\"?([^\";\s]+)\"?", head)
            if "multipart/mixed" in head and inner:
                results.extend(self._parse_multipart(inner.group(1), rest))
                continue
            status_line = re.search(r"HTTP/1\.[01]\s+(\d{3})", rest)
            if not status_line:
                continue
            status = int(status_line.group(1))
            after = rest[status_line.end():]
            header_text, _, body = after.lstrip("\r\n").partition("\r\n\r\n") if "\r\n\r\n" in after else after.lstrip("\n").partition("\n\n")
            headers = {k.strip().lower(): v.strip() for k, _, v in (line.partition(":") for line in header_text.splitlines()) if k.strip()}
            body = body.strip()
            if 200 <= status < 300:
                data = None
                if body:
                    try:
                        data = self.unwrap(json.loads(body))
                    except ValueError:
                        data = body
                results.append(BatchResult(status, headers, data))
            else:
                results.append(BatchResult(status, headers, None, parse_error(status, body, headers.get("content-type", ""))))
        return results

    # ------------------------------------------------------------ connection test
    def test(self, services: list[str]) -> dict:
        """Reach every service root, obtain a CSRF token from the first and report per service. Never raises."""
        report = {"services": {}, "csrf": False}
        for index, service in enumerate(services):
            try:
                self.request("GET", service, "", params={})
                report["services"][service] = {"ok": True, "detail": "HTTP 200"}
            except ConnectorError as exc:
                report["services"][service] = {"ok": False, "detail": str(exc)[:200]}
        try:
            if services:
                self.fetch_csrf(services[0])
                report["csrf"] = True
        except ConnectorError as exc:
            report["csrfDetail"] = str(exc)[:200]
        report["ok"] = bool(report["services"]) and all(s["ok"] for s in report["services"].values()) and report["csrf"]
        return report


# ---------------------------------------------------------------- IDoc transports (XML over HTTP, or a file port)
class IdocTransport:
    """Delivery of an IDoc-XML document to SAP: HTTP to the ICF service ``/sap/bc/idoc_xml`` or a directory watched by a file port."""

    def __init__(self, *, url: Optional[str] = None, directory: Optional[str] = None, user: Optional[str] = None, password: Optional[str] = None,
                 token: Optional[str] = None, sap_client: Optional[str] = None, timeout: float = 20, retries: int = 2,
                 sleep: Callable[[float], None] = time.sleep):
        self.url, self.directory, self.user, self.password, self.token = url, directory, user, password, token
        self.sap_client, self.timeout, self.retries, self.sleep = sap_client, timeout, retries, sleep

    def send(self, reference: str, xml: str) -> str:
        """Deliver and return the IDoc number (HTTP, parsed from ``DOCNUM`` or the confirmation text) or the file name."""
        if self.directory:
            import os
            os.makedirs(self.directory, exist_ok=True)
            final = os.path.join(self.directory, f"{safe_name(reference)}.xml")
            tmp = final + ".part"
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(xml)
            os.replace(tmp, final)
            return reference
        if not self.url:
            raise ConnectorError("IDoc transport needs PIC_ERP_SAP_S4_URL or PIC_ERP_SAP_S4_IDOC_DIR")
        headers = {"content-type": "application/xml; charset=utf-8", "accept": "text/xml, application/xml, text/plain"}
        if self.token:
            headers["authorization"] = f"Bearer {self.token}"
        elif self.user:
            headers["authorization"] = "Basic " + base64.b64encode(f"{self.user}:{self.password or ''}".encode()).decode()
        endpoint = f"{self.url.rstrip('/')}/sap/bc/idoc_xml" + (f"?sap-client={self.sap_client}" if self.sap_client else "")
        delay = 0.5
        for attempt in range(1, self.retries + 2):
            request = urllib.request.Request(endpoint, data=xml.encode("utf-8"), method="POST", headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - operator-configured URL
                    text = response.read().decode("utf-8", "replace")
                    return _idoc_number(text) or reference
            except urllib.error.HTTPError as exc:
                text = exc.read().decode("utf-8", "replace")
                if exc.code in (429, 503) and attempt <= self.retries:
                    self.sleep(delay)
                    delay *= 2
                    continue
                raise parse_error(exc.code, text, "", endpoint)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise ConnectorTimeout(f"{endpoint.split('?')[0]} not reachable: {exc}")
        raise ConnectorError("IDoc delivery failed after retries")  # pragma: no cover

    def exists(self, reference: str) -> bool:
        """File port only: the file for this reference was already written (HTTP IDoc ports have no query-by-reference)."""
        if not self.directory:
            return False
        import os
        return os.path.exists(os.path.join(self.directory, f"{safe_name(reference)}.xml"))


def safe_name(reference: str) -> str:
    """A PIC reference as a file name (the idempotency key contains '|' and '/', which file systems refuse)."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", reference)


def _idoc_number(text: str) -> Optional[str]:
    match = re.search(r"<DOCNUM>\s*(\d+)\s*</DOCNUM>", text or "") or re.search(r"\b(\d{16})\b", text or "")
    return match.group(1) if match else None
