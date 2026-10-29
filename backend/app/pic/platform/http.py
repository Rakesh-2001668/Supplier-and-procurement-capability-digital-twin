"""HTTP hardening (§14, §10.1, §15.1): trace context and request ids, structured access logs, security headers, HSTS,
rate limiting per client IP and per user, login brute-force throttling, request body limits, problem+json for every
error (each with a traceId), health and readiness probes and the Prometheus endpoint.

Rate limits are in-memory per API replica (sliding-window counters). The edge (Cloud Armor / ingress) enforces the
global limit; these limits stop one client or one account from starving a replica.
"""
import hmac
import ipaddress
import logging
import math
import threading
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text
from starlette.background import BackgroundTask, BackgroundTasks
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.pic.config import get_settings
from app.pic.db import engine
from app.pic.platform import errors, observability as obs

log = logging.getLogger("pic.http")

LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_ATTEMPTS = 10
_login_attempts: dict[str, deque] = defaultdict(deque)

PROBE_PATHS = {"/healthz", "/readyz", "/metrics", "/health"}
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")
UPLOAD_TYPES = ("multipart/form-data", "text/csv", "application/octet-stream", "application/pdf", "image/")


def _prune(window: deque) -> None:
    now = time.monotonic()
    while window and now - window[0] > LOGIN_WINDOW_SECONDS:
        window.popleft()


def record_login_failure(request: Request) -> None:
    _login_attempts[_client_ip(request)].append(time.monotonic())


def clear_login_failures(request: Request) -> None:
    _login_attempts.pop(_client_ip(request), None)


def _client_ip(request: Request) -> str:
    """Client address. With PIC_TRUSTED_PROXY_HOPS=N the N-th X-Forwarded-For entry from the right (the address the
    outermost trusted proxy saw), so a client cannot choose its own address by sending the header; with 0 the left-most
    entry (original behaviour, suitable only when the API is reachable through the web BFF alone)."""
    forwarded = [part.strip() for part in (request.headers.get("x-forwarded-for") or "").split(",") if part.strip()]
    hops = get_settings().trusted_proxy_hops
    if forwarded:
        if hops <= 0:
            return forwarded[0]
        return forwarded[-hops] if len(forwarded) >= hops else forwarded[0]
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------- sliding-window rate limiter
class SlidingWindowLimiter:
    """Sliding-window counter: the previous fixed window's count weighted by its remaining overlap plus the current
    window's count. O(1) memory per key; stale keys are swept periodically."""

    def __init__(self):
        self._buckets: dict[str, list] = {}  # key -> [window_start, previous_count, current_count]
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def hit(self, key: str, limit: int, window: int, now: Optional[float] = None) -> Optional[int]:
        """Count one request. Returns None when allowed, or the seconds to wait (Retry-After) when over the limit."""
        if limit <= 0:
            return None
        now = time.monotonic() if now is None else now
        start = now - (now % window)
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = self._buckets[key] = [start, 0, 0]
            elif bucket[0] != start:
                previous = bucket[2] if math.isclose(start - bucket[0], window) else 0
                bucket[:] = [start, previous, 0]
            elapsed = now - start
            estimate = bucket[1] * (window - elapsed) / window + bucket[2]
            if estimate + 1 > limit:
                if bucket[2] + 1 > limit:
                    # The current window alone is full: wait for it to end and for its weight to decay enough.
                    wait = (window - elapsed) + window * (1 - (limit - 1) / max(bucket[2], 1))
                else:
                    wait = (window - elapsed) - window * (limit - 1 - bucket[2]) / max(bucket[1], 1)
                return max(1, min(int(math.ceil(wait)), 2 * window))
            bucket[2] += 1
            if now - self._last_sweep > window:
                self._sweep(start, window)
                self._last_sweep = now
            return None

    def _sweep(self, start: float, window: int) -> None:
        for key in [k for k, b in self._buckets.items() if b[0] < start - window]:
            del self._buckets[key]

    def clear(self) -> None:
        with self._lock:
            self._buckets.clear()


limiter = SlidingWindowLimiter()


def _problem(request: Request, status: int, code: str, detail: str, headers: Optional[dict] = None, **extra) -> JSONResponse:
    response = errors._body(request, status, code, detail, extra=extra or None)
    for name, value in (headers or {}).items():
        response.headers[name] = value
    return response


def _bearer_principal(request: Request):
    authorization = request.headers.get("authorization") or ""
    if not authorization.lower().startswith("bearer "):
        return None
    from app.pic.platform.auth import principal_from_token
    try:
        return principal_from_token(authorization.split(" ", 1)[1].strip())
    except Exception:
        return None


# ---------------------------------------------------------------- body size limit (pure ASGI: never reads or alters the body)
class BodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    """Rejects bodies over PIC_MAX_BODY_BYTES (PIC_MAX_UPLOAD_BYTES for multipart/file uploads) with 413. Checks
    Content-Length up front and counts streamed chunks, passing every byte through unchanged (HMAC webhooks keep working)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        settings = get_settings()
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        content_type = headers.get("content-type", "").lower()
        limit = settings.max_upload_bytes if content_type.startswith(UPLOAD_TYPES) else settings.max_body_bytes
        declared = headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            return await self._reject(scope, receive, send, limit)
        seen = 0
        started = False

        async def counting_receive():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise BodyTooLarge()
            return message

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except BodyTooLarge:
            if started:
                raise
            await self._reject(scope, receive, send, limit)

    @staticmethod
    async def _reject(scope, receive, send, limit: int):
        obs.BODY_REJECTED.inc()
        request = Request(scope, receive)
        response = _problem(request, 413, "PAYLOAD_TOO_LARGE", f"The request body is larger than {limit} bytes")
        _security_headers(request, response)
        await response(scope, receive, send)


# ---------------------------------------------------------------- headers
def _https(request: Request) -> bool:
    return request.url.scheme == "https" or (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower() == "https"


def _security_headers(request: Request, response) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers.setdefault("Cache-Control", "no-store")
    if not request.url.path.startswith(DOCS_PATHS):
        # JSON API: nothing may be rendered or framed from a response.
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
    mode = get_settings().hsts.lower()
    if mode == "always" or (mode == "auto" and _https(request)):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or ("probe" if request.url.path in PROBE_PATHS else "unmatched")


# ---------------------------------------------------------------- error handlers: problem+json with traceId everywhere
_HTTP_CODES = {400: "BAD_REQUEST", 401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED",
               406: "NOT_ACCEPTABLE", 409: "CONFLICT", 413: "PAYLOAD_TOO_LARGE", 415: "UNSUPPORTED_MEDIA_TYPE", 429: "TOO_MANY_REQUESTS"}


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail if exc.detail is not None else ""
    response = errors._body(request, exc.status_code, _HTTP_CODES.get(exc.status_code, f"HTTP_{exc.status_code}"),
                            detail if isinstance(detail, str) else "Request failed")
    if not isinstance(detail, str):
        # Legacy prototype routers raise structured details; keep them readable for their screens.
        import json
        body = json.loads(response.body)
        body["detail"] = jsonable_encoder(detail)
        response = JSONResponse(status_code=exc.status_code, content=body, media_type="application/problem+json")
    for name, value in (getattr(exc, "headers", None) or {}).items():
        response.headers[name] = value
    return response


async def validation_handler(request: Request, exc: RequestValidationError):
    problems = jsonable_encoder(exc.errors(), custom_encoder={Exception: str})
    for item in problems:
        item.pop("input", None)  # never echo submitted values (they may be passwords or bank details)
        item.pop("url", None)
    summary = "; ".join(f"{'.'.join(str(p) for p in e.get('loc', []) if p != 'body')}: {e.get('msg')}" for e in problems[:5])
    return errors._body(request, 422, "VALIDATION_FAILED", summary or "The request is not valid", extra={"errors": problems})


async def unhandled_handler(request: Request, exc: Exception):
    log.error("unhandled error", exc_info=exc, extra={"fields": {"path": request.url.path, "method": request.method}})
    response = errors._body(request, 500, "INTERNAL_ERROR", "An unexpected error occurred. Quote the traceId when reporting it.")
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        response.headers["X-Request-ID"] = request_id
    _security_headers(request, response)
    return response


# ---------------------------------------------------------------- readiness
def readiness() -> tuple[int, dict]:
    """(status code, body). Not ready (503): database unreachable or schema behind this release; or, when configured, no live
    worker / outbox lag over the limit. Otherwise ready, with warnings for an absent worker, outbox lag or a schema one ahead."""
    settings = get_settings()
    checks: dict = {}
    warnings: list[str] = []
    try:
        with engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
            version = conn.execute(text("SELECT version_num FROM pic.alembic_version")).scalar()
            head = obs.expected_head()
            if version == head:
                checks["schema"] = {"status": "ok", "revision": version}
            elif version and not obs.known_revision(version):
                # Database migrated ahead of this release (rolling deploy): migrations stay backward-compatible for one release.
                checks["schema"] = {"status": "ahead", "revision": version, "expected": head}
                warnings.append(f"schema {version} is ahead of this release ({head})")
            else:
                checks["schema"] = {"status": "behind", "revision": version, "expected": head}
                return 503, {"status": "not ready", "schema": version, "checks": checks}
            try:
                beats = obs.worker_heartbeats(conn)
            except Exception:
                beats = []
            age = round(time.time() - max(beats), 1) if beats else None
            alive = age is not None and age <= settings.worker_stale_seconds
            checks["worker"] = {"status": "ok" if alive else ("stale" if beats else "absent"), "instances": len(beats), "heartbeatAgeSeconds": age}
            from app.pic.platform import clock
            pending, oldest = obs.outbox_backlog(conn)  # per tenant under RLS: an owner without BYPASSRLS would see no rows
            lag = max((clock.now() - oldest).total_seconds(), 0) if oldest else 0
            checks["outbox"] = {"pending": pending, "lagSeconds": round(lag, 1)}
        failed = []
        if not alive:
            (failed if settings.ready_require_worker else warnings).append(f"worker heartbeat {checks['worker']['status']}")
        if settings.ready_max_outbox_lag_seconds and lag > settings.ready_max_outbox_lag_seconds:
            failed.append(f"outbox lag {lag:.0f}s over {settings.ready_max_outbox_lag_seconds}s")
        body = {"status": "not ready" if failed else "ready", "schema": version, "checks": checks}
        if warnings or failed:
            body["warnings"] = failed + warnings
        return (503 if failed else 200), body
    except Exception as exc:
        checks.setdefault("database", type(exc).__name__)
        return 503, {"status": "not ready", "error": type(exc).__name__, "checks": checks}


def _metrics_allowed(request: Request) -> bool:
    settings = get_settings()
    token = settings.metrics_token
    if token:
        supplied = request.headers.get("authorization") or ""
        expected = f"Bearer {token}"
        return hmac.compare_digest(supplied.encode(), expected.encode())
    if settings.is_production or request.headers.get("x-forwarded-for"):
        return False
    try:
        return request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return request.client is not None and request.client.host in ("testclient", "localhost")


# ---------------------------------------------------------------- serverless worker (Vercel)
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


def _cron_allowed(request: Request) -> bool:
    secret = get_settings().cron_secret
    if not secret:
        return False
    supplied = request.headers.get("authorization") or ""
    return hmac.compare_digest(supplied.encode(), f"Bearer {secret}".encode())


def _drain_after(response, budget_seconds: float, tenant_id=None) -> None:
    """Run the worker after the response has been sent (the client does not wait), so events, ERP messages and timers do
    not have to wait for the next scheduled tick. Only the caller's tenant when known: one tenant's request never runs (or
    waits for) every tenant's work; the scheduled cron drain stays global."""
    from app.pic import worker
    task = BackgroundTask(worker.drain, budget_seconds, tenant_id=tenant_id)
    response.background = task if response.background is None else BackgroundTasks([response.background, task])


# ---------------------------------------------------------------- install
def install(app: FastAPI) -> None:
    settings = get_settings()
    obs.setup_tracing("pic-api", settings.otel_enabled)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_exception_handler(Exception, unhandled_handler)
    # Added before the context middleware, so it runs inside it and its 413 carries the request's traceId.
    app.add_middleware(BodyLimitMiddleware)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        settings = get_settings()
        ctx = obs.context_from_headers(request.headers.get("traceparent"), request.headers.get("x-request-id"))
        request.state.request_id = ctx.request_id
        request.state.trace_id = ctx.trace_id
        token = obs.activate(ctx)
        try:
            path = request.url.path
            if path.startswith("/v1/"):
                if path == "/v1/auth/token" and request.method == "POST":
                    # Brute-force protection: after 10 failed sign-ins from one client IP, block for 5 minutes.
                    window = _login_attempts[_client_ip(request)]
                    _prune(window)
                    if len(window) >= LOGIN_MAX_ATTEMPTS:
                        obs.RATE_LIMITED.inc("login")
                        return _finish(request, _problem(request, 429, "TOO_MANY_ATTEMPTS",
                                                         "Too many sign-in attempts. Wait 5 minutes and try again.",
                                                         headers={"Retry-After": str(LOGIN_WINDOW_SECONDS)}), ctx)
                limited = _rate_limit(request, settings)
                if limited is not None:
                    return _finish(request, limited, ctx)
            started = time.perf_counter()
            obs.HTTP_IN_FLIGHT.inc(amount=1)
            status = 500
            try:
                with obs.span(f"{request.method} {path}", obs.current(), kind="SERVER", **{"http.method": request.method}) as active:
                    response = await call_next(request)
                    status = response.status_code
                    obs.set_span_attributes(**{"http.route": _route_template(request), "http.status_code": status})
                    ctx = active
            finally:
                obs.HTTP_IN_FLIGHT.inc(amount=-1)
                elapsed = time.perf_counter() - started
                route = _route_template(request)
                if path not in PROBE_PATHS:
                    obs.observe_request(request.method, route, status, elapsed)
                if path.startswith("/v1/") or status >= 500:
                    current = obs.current()
                    log.info("%s %s %s", request.method, path, status, extra={"fields": {
                        "event": "http_request", "method": request.method, "path": path, "route": route, "status": status,
                        "ms": round(elapsed * 1000, 1), "tenant": current.tenant if current else None,
                        "user": current.user if current else None}})
            if settings.inline_worker and path.startswith("/v1/") and request.method in WRITE_METHODS and status < 400:
                principal = _bearer_principal(request)
                _drain_after(response, settings.worker_tick_budget_seconds, principal.tenant_id if principal is not None else None)
            return _finish(request, response, ctx)
        finally:
            obs.deactivate(token)

    def _finish(request: Request, response, ctx):
        response.headers["X-Request-ID"] = ctx.request_id or ctx.trace_id
        response.headers["traceparent"] = ctx.traceparent
        _security_headers(request, response)
        return response

    def _rate_limit(request: Request, settings) -> Optional[JSONResponse]:
        window = max(settings.rate_limit_window_seconds, 1)
        principal = _bearer_principal(request)
        if principal is not None:
            obs.bind(tenant=principal.tenant_code or str(principal.tenant_id), user=str(principal.user_id))
        checks = [("ip", f"ip:{_client_ip(request)}", settings.ip_limit)]
        if principal is not None:
            checks.append(("user", f"user:{principal.tenant_id}:{principal.user_id}", settings.user_limit))
        for scope, key, limit in checks:
            retry = limiter.hit(key, limit, window)
            if retry is not None:
                obs.RATE_LIMITED.inc(scope)
                log.warning("rate limited", extra={"fields": {"event": "rate_limited", "scope": scope, "path": request.url.path}})
                return _problem(request, 429, "RATE_LIMITED",
                                f"Too many requests from this {'account' if scope == 'user' else 'address'}: the limit is {limit} per "
                                f"{window} seconds. Retry after {retry} seconds.",
                                headers={"Retry-After": str(retry), "RateLimit-Limit": str(limit), "RateLimit-Policy": f"{limit};w={window}"},
                                limit=limit, windowSeconds=window, scope=scope)
        return None

    @app.api_route("/internal/worker/tick", methods=["GET", "POST"], include_in_schema=False)
    def worker_tick(request: Request):
        """Serverless worker: Vercel Cron (or any scheduler) sends 'Authorization: Bearer <CRON_SECRET>'. Off without CRON_SECRET."""
        if not _cron_allowed(request):
            return errors._body(request, 404, "NOT_FOUND", "Not found")
        from app.pic import worker
        return worker.drain(get_settings().worker_tick_budget_seconds)

    @app.get("/healthz", tags=["Operations"])
    def healthz():
        """Liveness: the process answers. Does not touch the database."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["Operations"])
    def readyz():
        """Readiness: database reachable, schema at this release's migration head (or one ahead), worker heartbeat and
        outbox lag reported (they fail readiness only with PIC_READY_REQUIRE_WORKER / PIC_READY_MAX_OUTBOX_LAG_SECONDS)."""
        code, body = readiness()
        return JSONResponse(status_code=code, content=body)

    @app.get("/metrics", tags=["Operations"], include_in_schema=False)
    def metrics(request: Request):
        if not _metrics_allowed(request):
            return errors._body(request, 401 if get_settings().metrics_token else 403, "METRICS_FORBIDDEN",
                                "Send 'Authorization: Bearer <PIC_METRICS_TOKEN>'" if get_settings().metrics_token
                                else "Metrics need PIC_METRICS_TOKEN; without it only local unproxied callers outside production are served")
        return PlainTextResponse(obs.render_metrics(get_settings().metrics_cache_seconds),
                                 media_type="text/plain; version=0.0.4; charset=utf-8")

