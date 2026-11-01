"""A local HTTP server that mimics the SAP Gateway behaviours the connector depends on (CSRF with session cookie, OData v2 JSON
envelopes, $filter lookups, $batch, SAP-style errors, transient failures) and the IDoc-XML ICF service. Test support only."""
import json
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

NUMBERS = {"A_PurchaseOrder": ("PurchaseOrder", 4500000100), "A_SupplierInvoice": ("SupplierInvoice", 5105600000),
           "A_MaterialDocumentHeader": ("MaterialDocument", 4900000000), "A_BusinessPartner": ("BusinessPartner", 100200),
           "A_PurchaseRequisitionHeader": ("PurchaseRequisition", 10000100)}


class SapMock:
    def __init__(self):
        self.created: list[tuple[str, dict]] = []     # (entity set, body)
        self.requests: list[dict] = []                 # every request: method, path, query, headers, body
        self.failures: list[tuple[int, str, dict]] = []  # queued (status, body, headers) answers for the next requests
        self.get_data: dict[str, object] = {}          # entity set -> list of entities returned by a GET (with or without $filter)
        self.idocs: list[str] = []
        self.token = uuid.uuid4().hex
        self.cookie = uuid.uuid4().hex
        self.counter = {k: v[1] for k, v in NUMBERS.items()}
        self.server = None

    def start(self) -> str:
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _send(self, status, body="", headers=None, content_type="application/json"):
                data = body.encode() if isinstance(body, str) else body
                self.send_response(status)
                self.send_header("content-type", content_type)
                self.send_header("content-length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _handle(self):
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length).decode() if length else ""
                parts = urlsplit(self.path)
                query = {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
                record = {"method": self.command, "path": parts.path, "query": query, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": raw}
                mock.requests.append(record)
                if mock.failures:
                    status, body, headers = mock.failures.pop(0)
                    return self._send(status, body, headers)
                if parts.path.endswith("/sap/bc/idoc_xml"):
                    mock.idocs.append(raw)
                    return self._send(200, f"<IDOC_RESPONSE><DOCNUM>{len(mock.idocs):016d}</DOCNUM></IDOC_RESPONSE>", content_type="text/xml")
                headers = {}
                has_session = mock.cookie in (self.headers.get("cookie") or "")
                if (self.headers.get("x-csrf-token") or "") == "Fetch":
                    headers = {"x-csrf-token": mock.token, "set-cookie": f"sap-session={mock.cookie}; Path=/"}
                if self.command == "GET":
                    return self._get(parts.path, query, headers)
                if self.command in ("POST", "PATCH", "PUT"):
                    if (self.headers.get("x-csrf-token") != mock.token) or not has_session:
                        return self._send(403, json.dumps({"error": {"code": "CSRF", "message": {"value": "CSRF token validation failed"}}}),
                                          {"x-csrf-token": "Required"})
                    if parts.path.endswith("/$batch"):
                        return self._batch(raw)
                    return self._write(parts.path, raw)
                return self._send(405, "")

            def _get(self, path, query, headers):
                entity = path.rstrip("/").rsplit("/", 1)[-1]
                key = re.match(r"(\w+)\('([^']*)'\)", entity)
                if key:
                    for name, body in mock.created:
                        if name == key.group(1) and body.get("Product") == key.group(2):
                            return self._send(200, json.dumps({"d": body}), headers)
                    return self._send(404, json.dumps({"error": {"code": "/IWBEP/CM_MGW_RT/021", "message": {"value": "Resource not found"}}}), headers)
                if not entity or entity.startswith("API_"):
                    return self._send(200, json.dumps({"d": {"EntitySets": []}}), headers)
                flt = unquote(query.get("$filter", ""))
                found = re.match(r"(\w+) eq '([^']*)'", flt)
                if entity in mock.get_data and not found:
                    return self._send(200, json.dumps({"d": {"results": mock.get_data[entity]}}), headers)
                results = []
                if found:
                    field, value = found.groups()
                    results = [dict(body, **{NUMBERS[name][0]: self._number_of(body)}) for name, body in mock.created if name == entity and body.get(field) == value]
                    results = results or [r for r in mock.get_data.get(entity, []) if r.get(field) == value]
                return self._send(200, json.dumps({"d": {"results": results}}), headers)

            def _number_of(self, body):
                return body.get("_number")

            def _write(self, path, raw):
                entity = path.rstrip("/").rsplit("/", 1)[-1]
                body = json.loads(raw or "{}")
                if "(" in entity:
                    return self._send(204, "")
                number_field, _ = NUMBERS.get(entity, (None, None))
                response = dict(body)
                if number_field:
                    mock.counter[entity] += 1
                    body["_number"] = str(mock.counter[entity])
                    response = {number_field: body["_number"], **({"FiscalYear": "2026"} if entity == "A_SupplierInvoice" else {}),
                                **({"MaterialDocumentYear": "2026"} if entity == "A_MaterialDocumentHeader" else {})}
                mock.created.append((entity, body))
                return self._send(201, json.dumps({"d": response}))

            def _batch(self, raw):
                gets = raw.count("GET ")
                boundary = "batch_resp"
                payload = ""
                for i in range(gets):
                    payload += (f"--{boundary}\r\nContent-Type: application/http\r\nContent-Transfer-Encoding: binary\r\n\r\n"
                                f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n" + json.dumps({"d": {"Supplier": f"S{i}"}}) + "\r\n")
                if "changeset" in raw:
                    payload += (f"--{boundary}\r\nContent-Type: multipart/mixed; boundary=cs_resp\r\n\r\n"
                                f"--cs_resp\r\nContent-Type: application/http\r\n\r\nHTTP/1.1 201 Created\r\nContent-Type: application/json\r\n\r\n"
                                + json.dumps({"d": {"PurchaseOrder": "4500000777"}}) + "\r\n--cs_resp--\r\n")
                payload += f"--{boundary}--\r\n"
                self._send(202, payload, content_type=f"multipart/mixed; boundary={boundary}")

            do_GET = do_POST = do_PATCH = do_PUT = lambda self: self._handle()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()


class JsonMock:
    """Minimal programmable JSON endpoint: routes (method, path-prefix) -> callable(record) returning (status, body, headers)."""

    def __init__(self):
        self.routes: dict[tuple[str, str], object] = {}
        self.requests: list[dict] = []
        self.failures: list[tuple[int, str]] = []
        self.server = None

    def start(self) -> str:
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _handle(self):
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length).decode() if length else ""
                parts = urlsplit(self.path)
                record = {"method": self.command, "path": parts.path, "query": parse_qs(parts.query), "headers": {k.lower(): v for k, v in self.headers.items()}, "body": raw}
                mock.requests.append(record)
                if mock.failures:
                    status, body = mock.failures.pop(0)
                    answer = (status, body, {})
                else:
                    handler = next((h for (m, prefix), h in mock.routes.items() if m == self.command and parts.path.startswith(prefix)), None)
                    answer = handler(record) if handler else (404, "{}", {})
                status, body, headers = answer
                data = (body if isinstance(body, str) else json.dumps(body)).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = lambda self: self._handle()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
