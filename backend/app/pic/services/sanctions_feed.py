"""Hardened HTTP access for the licensed sanctions / watch-list provider (F8-03, ``PIC_SANCTIONS_*``).

``supplier.SanctionsProvider`` keeps the request and response contract; this module is the transport it uses:

    PIC_SANCTIONS_TIMEOUT     seconds per attempt (default 10)
    PIC_SANCTIONS_RETRIES     retries on connection errors, 429 and 5xx with exponential back-off (default 2)
    PIC_SANCTIONS_MAX_BYTES   largest accepted answer (default 50 MB: the full list download)
    PIC_SANCTIONS_ALLOW_HTTP  1 allows a plain-HTTP URL for a non-local host (default: HTTPS only; localhost is always allowed)

The original exception of the last attempt is re-raised (callers record ``ConnectError: ...`` in the screening result); an answer
larger than the cap is an error, never a silently truncated list. ``test`` reports reachability for the admin screen.
"""
import os
import time
import urllib.parse
from typing import Optional

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
RETRY_STATUS = (429, 500, 502, 503, 504)


class SanctionsTransportError(Exception):
    pass


def _int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except ValueError:
        return default


def check_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise SanctionsTransportError("PIC_SANCTIONS_URL must be an http(s) URL")
    if parsed.scheme == "http" and parsed.hostname not in LOCAL_HOSTS and os.environ.get("PIC_SANCTIONS_ALLOW_HTTP", "").strip() not in ("1", "true"):
        raise SanctionsTransportError("PIC_SANCTIONS_URL must use HTTPS (set PIC_SANCTIONS_ALLOW_HTTP=1 only for a private network)")


def get(url: str, params: Optional[dict] = None, headers: Optional[dict] = None, sleep=time.sleep):
    """``httpx.get`` with the URL check, timeout, retries with back-off and the size cap. Returns the last response."""
    import httpx
    check_url(url)
    timeout, retries, cap = float(_int("PIC_SANCTIONS_TIMEOUT", 10)), _int("PIC_SANCTIONS_RETRIES", 2), _int("PIC_SANCTIONS_MAX_BYTES", 50_000_000)
    delay = 0.5
    for attempt in range(1, retries + 2):
        try:
            response = httpx.get(url, params=params, headers=headers, timeout=timeout)
        except httpx.TransportError:
            if attempt > retries:
                raise
        else:
            content = getattr(response, "content", None)
            if isinstance(content, (bytes, bytearray)) and len(content) > cap:
                raise SanctionsTransportError(f"the provider answer is larger than PIC_SANCTIONS_MAX_BYTES ({cap})")
            if response.status_code not in RETRY_STATUS or attempt > retries:
                return response
        sleep(delay)
        delay *= 2
    raise SanctionsTransportError("provider unavailable")  # pragma: no cover


def test() -> dict:
    """Reachability of the configured provider (search endpoint with a harmless query)."""
    from app.pic.services import supplier as supplier_svc
    provider = supplier_svc.sanctions_provider()
    if provider is None:
        return {"configured": False, "healthy": False, "detail": "PIC_SANCTIONS_PROVIDER / PIC_SANCTIONS_URL are not set (built-in SAMPLE-LIST in use)"}
    started = time.monotonic()
    try:
        response = provider._get("/search", {"name": "connectivity test", "country": "IN"})
        return {"configured": True, "provider": provider.name, "healthy": response.status_code < 400, "detail": f"HTTP {response.status_code}",
                "latencyMs": int((time.monotonic() - started) * 1000)}
    except Exception as exc:  # noqa: BLE001 - report, never raise
        return {"configured": True, "provider": provider.name, "healthy": False, "detail": f"{type(exc).__name__}: {exc}"[:300]}
