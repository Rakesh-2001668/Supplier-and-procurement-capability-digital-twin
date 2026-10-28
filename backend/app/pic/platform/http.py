"""HTTP hardening: request ids, structured access logs, security headers, login throttling, health probes."""
import json
import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.pic.db import engine

log = logging.getLogger("pic.http")

LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_ATTEMPTS = 10
_login_attempts: dict[str, deque] = defaultdict(deque)


def _prune(window: deque) -> None:
    now = time.monotonic()
    while window and now - window[0] > LOGIN_WINDOW_SECONDS:
        window.popleft()


def record_login_failure(request: Request) -> None:
    _login_attempts[_client_ip(request)].append(time.monotonic())


def clear_login_failures(request: Request) -> None:
    _login_attempts.pop(_client_ip(request), None)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    return forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        if request.url.path == "/v1/auth/token" and request.method == "POST":
            # Brute-force protection: after 10 failed sign-ins from one client IP, block for 5 minutes.
            window = _login_attempts[_client_ip(request)]
            _prune(window)
            if len(window) >= LOGIN_MAX_ATTEMPTS:
                return JSONResponse(status_code=429, media_type="application/problem+json", headers={"Retry-After": "300"},
                                    content={"type": "https://errors.alphahelion.io/pic/TOO_MANY_ATTEMPTS", "title": "TOO_MANY_ATTEMPTS",
                                             "status": 429, "code": "TOO_MANY_ATTEMPTS", "traceId": request_id,
                                             "detail": "Too many sign-in attempts. Wait 5 minutes and try again."})
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers.setdefault("Cache-Control", "no-store")
        if request.url.path.startswith("/v1/"):
            log.info(json.dumps({"requestId": request_id, "method": request.method, "path": request.url.path,
                                 "status": response.status_code, "ms": elapsed_ms}))
        return response

    @app.get("/healthz", tags=["Operations"])
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz", tags=["Operations"])
    def readyz():
        try:
            with engine().connect() as conn:
                conn.execute(text("SELECT 1"))
                version = conn.execute(text("SELECT version_num FROM pic.alembic_version")).scalar()
            return {"status": "ready", "schema": version}
        except Exception as exc:
            return JSONResponse(status_code=503, content={"status": "not ready", "error": type(exc).__name__})
