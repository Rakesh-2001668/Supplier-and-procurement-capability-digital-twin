"""MOCK e-signature provider (demo and test only): a local stand-in for DocuSign / Adobe Sign / Leegality / eMudhra.

    python -m app.pic.tools.esign_mock --port 8765 --webhook-url http://127.0.0.1:8000/v1/esign/webhook --delay 5

It speaks the small envelope API the PIC adapter (``services.contract.EsignProvider``) calls and sends the signed completion
webhooks the PIC endpoint (``POST /v1/esign/webhook``, ``services.contract.handle_webhook``) verifies, so the whole real path runs:
envelope -> signers complete -> HMAC-signed webhook -> signature recorded -> contract ACTIVE. Nothing here is a real signature: every
signature it produces is recorded in PIC with the provider MOCK and shown as a *demo signature, not legally binding*. It refuses to
start when PIC_ENV is production, and PIC refuses the provider MOCK in production.

Point PIC at it (names only; the values are yours to choose):
    PIC_ESIGN_PROVIDER=MOCK  PIC_ESIGN_URL=http://127.0.0.1:8765  PIC_ESIGN_API_KEY=<any>  PIC_ESIGN_WEBHOOK_SECRET=<any>
and give this tool the same API key and webhook secret (--api-key / --secret, or the same environment variables).

API
    POST /envelopes                     create an envelope (the adapter's request) -> 201 {envelopeId, status, signingUrls}
    GET  /envelopes/{id}                state of the envelope and its signers
    POST /envelopes/{id}/complete       sign for every pending signer, or for ?party=BUYER|SUPPLIER (on demand)
    POST /envelopes/{id}/decline        decline (webhook ENVELOPE_DECLINED);  /void  voids it (ENVELOPE_VOIDED)
    GET  /sign/{id}/{party}             the demo signing page (a button; nothing real);  POST on it signs
    GET  /                              the banner and the list of envelopes
With --delay N each new envelope is completed by itself N seconds after creation, one signer after the other.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import html
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional
from urllib.parse import parse_qs, urlsplit

import httpx

SIGNATURE_HEADER = "X-Esign-Signature"
ENVELOPE_PREFIX = "MOCK-"
BANNER = "MOCK e-signature provider: demo only. Nothing here is a real or legally binding signature."


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sign_body(secret: str, body: bytes) -> str:
    """HMAC-SHA256 hex digest of the raw webhook body, the scheme PIC verifies."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def http_deliver(url: str) -> Callable[[bytes, dict], tuple]:
    """Default webhook delivery: POST the raw body with its signature header to PIC; returns (status, response text)."""
    def deliver(body: bytes, headers: dict) -> tuple:
        response = httpx.post(url, content=body, headers=headers, timeout=15.0)
        return response.status_code, response.text
    return deliver


class MockEsign:
    """The provider's state and behaviour, independent of HTTP so a test can drive it directly.

    ``deliver(body, headers) -> (status, text)`` sends a webhook to PIC; by default an HTTP POST to ``webhook_url``."""

    def __init__(self, *, secret: str, api_key: str = "", webhook_url: str = "", deliver: Optional[Callable] = None, delay: Optional[float] = None,
                 base_url: str = "http://127.0.0.1:8765"):
        self.secret, self.api_key, self.delay, self.base_url = secret, api_key, delay, base_url.rstrip("/")
        self.deliver = deliver or (http_deliver(webhook_url) if webhook_url else None)
        self.envelopes: dict = {}
        self.deliveries: list = []   # one dict per webhook sent: event, party, status, response
        self.raw_log: list = []      # the raw body of every webhook sent (a test replays one)
        self.lock = threading.RLock()

    # ------------------------------------------------------------------ the provider API
    def create(self, request: dict) -> dict:
        signers = request.get("signers") or []
        if not request.get("reference") or not (request.get("documentHash") or {}).get("value") or not signers:
            raise ValueError("an envelope needs a reference, a documentHash and at least one signer")
        envelope_id = f"{ENVELOPE_PREFIX}{uuid.uuid4().hex[:16].upper()}"
        envelope = {"envelopeId": envelope_id, "reference": request["reference"], "documentName": request.get("documentName", ""),
                    "documentHash": request["documentHash"]["value"], "status": "SENT", "createdAt": _now(),
                    "signers": [{"party": s["party"], "name": s["name"], "email": s["email"], "routingOrder": s.get("routingOrder", i),
                                 "status": "SENT", "signedAt": None} for i, s in enumerate(signers, start=1)]}
        with self.lock:
            self.envelopes[envelope_id] = envelope
        if self.delay is not None:
            threading.Thread(target=self._auto, args=(envelope_id,), daemon=True).start()
        return {"envelopeId": envelope_id, "status": "sent",
                "signingUrls": {s["party"]: f"{self.base_url}/sign/{envelope_id}/{s['party']}" for s in envelope["signers"]}}

    def _auto(self, envelope_id: str) -> None:
        import time
        for _ in range(len(self.envelopes[envelope_id]["signers"])):
            time.sleep(max(float(self.delay or 0), 0.0))
            self.complete(envelope_id)

    def get(self, envelope_id: str) -> Optional[dict]:
        with self.lock:
            envelope = self.envelopes.get(envelope_id)
            return json.loads(json.dumps(envelope)) if envelope else None

    def complete(self, envelope_id: str, party: Optional[str] = None) -> list:
        """Sign for ``party`` (the next pending signer in routing order when None); returns the webhook results."""
        with self.lock:
            envelope = self.envelopes.get(envelope_id)
            if envelope is None:
                raise KeyError(envelope_id)
            if envelope["status"] not in ("SENT", "IN_PROGRESS"):
                raise ValueError(f"envelope {envelope_id} is {envelope['status']}")
            pending = sorted((s for s in envelope["signers"] if s["status"] == "SENT"), key=lambda s: s["routingOrder"])
            signer = next((s for s in pending if party is None or s["party"] == party.upper()), None)
            if signer is None:
                raise ValueError(f"no pending signer{' ' + party if party else ''} in {envelope_id}")
            signer["status"], signer["signedAt"] = "SIGNED", _now()
            results = [self.webhook("SIGNER_COMPLETED", envelope, party=signer["party"], signerName=signer["name"], signedAt=signer["signedAt"])]
            if all(s["status"] == "SIGNED" for s in envelope["signers"]):
                envelope["status"] = "COMPLETED"
                results.append(self.webhook("ENVELOPE_COMPLETED", envelope))
            else:
                envelope["status"] = "IN_PROGRESS"
            return results

    def close(self, envelope_id: str, how: str, reason: str = "") -> list:
        with self.lock:
            envelope = self.envelopes[envelope_id]
            envelope["status"] = how
            return [self.webhook(f"ENVELOPE_{how}", envelope, reason=reason)]

    # ------------------------------------------------------------------ the webhook
    def payload(self, event: str, envelope: dict, **extra) -> dict:
        body = {"event": event, "reference": envelope["reference"], "envelopeId": envelope["envelopeId"], "documentHash": envelope["documentHash"],
                "at": _now(), **extra}
        if event in ("SIGNER_COMPLETED", "ENVELOPE_COMPLETED"):
            # what the provider would hand back as the hash of the signed (sealed) document
            body["signedDocumentHash"] = hashlib.sha256(f"{envelope['documentHash']}|{envelope['envelopeId']}|signed".encode()).hexdigest()
        return body

    def webhook(self, event: str, envelope: dict, **extra) -> dict:
        raw = json.dumps(self.payload(event, envelope, **extra)).encode()
        return self.post_raw(raw, event=event, party=extra.get("party"))

    def post_raw(self, raw: bytes, *, event: str = "RAW", party: Optional[str] = None, secret: Optional[str] = None) -> dict:
        """Send a prepared body to PIC, signed with ``secret`` (default: the configured one). A test uses a wrong secret to check PIC refuses it."""
        self.raw_log.append(raw)
        headers = {SIGNATURE_HEADER: sign_body(self.secret if secret is None else secret, raw), "Content-Type": "application/json"}
        if self.deliver is None:
            result = {"event": event, "party": party, "status": None, "response": "no webhook url configured"}
        else:
            try:
                status, text = self.deliver(raw, headers)
            except Exception as exc:  # the receiver being down must not break the provider
                status, text = None, f"delivery failed: {exc.__class__.__name__}"
            result = {"event": event, "party": party, "status": status, "response": text}
        self.deliveries.append(result)
        return result


# ---------------------------------------------------------------------------------------------------------------------------------
class _Handler(BaseHTTPRequestHandler):
    server_version = "MockEsign/1"
    mock: MockEsign

    def log_message(self, *args) -> None:  # quiet
        return

    def _send(self, status: int, body, content_type: str = "application/json") -> None:
        data = (body if isinstance(body, str) else json.dumps(body)).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Mock-Esign", "demo only, not legally binding")
        self.end_headers()
        self.wfile.write(data)

    def _authorised(self) -> bool:
        key = self.mock.api_key
        return not key or self.headers.get("Authorization", "") == f"Bearer {key}"

    def _read(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def do_GET(self) -> None:
        parts = [p for p in urlsplit(self.path).path.split("/") if p]
        if not parts:
            rows = "".join(f"<li>{html.escape(e['envelopeId'])} {html.escape(e['reference'])}: {e['status']}</li>" for e in self.mock.envelopes.values())
            return self._send(200, f"<h2>{BANNER}</h2><ul>{rows}</ul>", "text/html")
        if parts == ["health"]:
            return self._send(200, {"status": "ok", "mock": True})
        if len(parts) == 2 and parts[0] == "envelopes":
            if not self._authorised():
                return self._send(401, {"error": "unauthorised"})
            envelope = self.mock.get(parts[1])
            return self._send(200, envelope) if envelope else self._send(404, {"error": "unknown envelope"})
        if len(parts) == 3 and parts[0] == "sign" and self.mock.get(parts[1]):
            page = (f"<h2>{BANNER}</h2><p>Envelope {html.escape(parts[1])}, signer {html.escape(parts[2])}.</p>"
                    f"<form method='post'><button>Sign (demo)</button></form>")
            return self._send(200, page, "text/html")
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        url = urlsplit(self.path)
        parts = [p for p in url.path.split("/") if p]
        query = parse_qs(url.query)
        body = self._read()
        try:
            if parts == ["envelopes"]:
                if not self._authorised():
                    return self._send(401, {"error": "unauthorised"})
                try:
                    return self._send(201, self.mock.create(json.loads(body or b"{}")))
                except (ValueError, KeyError) as exc:
                    return self._send(400, {"error": str(exc)})
            if len(parts) == 3 and parts[0] == "envelopes" and parts[2] in ("complete", "decline", "void"):
                if not self._authorised():
                    return self._send(401, {"error": "unauthorised"})
                if parts[2] == "complete":
                    return self._send(200, {"webhooks": self.mock.complete(parts[1], (query.get("party") or [None])[0])})
                return self._send(200, {"webhooks": self.mock.close(parts[1], "DECLINED" if parts[2] == "decline" else "VOIDED")})
            if len(parts) == 3 and parts[0] == "sign":
                return self._send(200, {"webhooks": self.mock.complete(parts[1], parts[2])})
        except KeyError:
            return self._send(404, {"error": "unknown envelope"})
        except ValueError as exc:
            return self._send(409, {"error": str(exc)})
        self._send(404, {"error": "not found"})


class MockServer:
    """The mock over HTTP, in a background thread (used by the tests and by ``main``)."""

    def __init__(self, mock: MockEsign, host: str = "127.0.0.1", port: int = 8765):
        handler = type("Handler", (_Handler,), {"mock": mock})
        self.mock, self.httpd = mock, ThreadingHTTPServer((host, port), handler)
        self.url = f"http://{host}:{self.httpd.server_address[1]}"
        mock.base_url = self.url
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self) -> "MockServer":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="MOCK e-signature provider for PIC (demo and test only; not a real or legally binding signature)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--webhook-url", default=os.environ.get("PIC_ESIGN_WEBHOOK_URL", "http://127.0.0.1:8000/v1/esign/webhook"))
    parser.add_argument("--secret", default=os.environ.get("PIC_ESIGN_WEBHOOK_SECRET", ""), help="HMAC secret (same as PIC_ESIGN_WEBHOOK_SECRET)")
    parser.add_argument("--api-key", default=os.environ.get("PIC_ESIGN_API_KEY", ""), help="bearer key PIC sends (same as PIC_ESIGN_API_KEY); empty accepts any")
    parser.add_argument("--delay", type=float, default=None, help="complete each signer by itself this many seconds after creation (default: on demand)")
    args = parser.parse_args(argv)
    if os.environ.get("PIC_ENV", "").strip().lower() in ("production", "prod"):
        print("Refusing to start: the mock e-signature provider must never run with PIC_ENV=production.")
        return 2
    if not args.secret:
        print("A webhook secret is needed: pass --secret or set PIC_ESIGN_WEBHOOK_SECRET (the same value PIC uses).")
        return 2
    server = MockServer(MockEsign(secret=args.secret, api_key=args.api_key, webhook_url=args.webhook_url, delay=args.delay), args.host, args.port)
    print(f"{BANNER}\nListening on {server.url}; webhooks go to {args.webhook_url}"
          + (f"; signers complete by themselves after {args.delay} s" if args.delay is not None else "; complete envelopes on demand (POST /envelopes/{id}/complete)"))
    try:
        server.httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
