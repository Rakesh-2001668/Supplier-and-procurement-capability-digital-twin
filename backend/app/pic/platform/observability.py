"""Observability (Technical Document §15.1): W3C trace context, structured JSON logs, Prometheus metrics and business SLOs.

* Trace context: every request gets a W3C ``traceparent`` (accepted from the caller or created here) and returns one.
  The trace id is attached to log lines, problem responses (``traceId``) and outbox events (``outbox_event.trace_id``),
  and the worker opens a trace per tick, so one id follows web → API → services → workflow → connectors.
* OpenTelemetry: optional. With ``PIC_OTEL_ENABLED=true`` and ``opentelemetry-sdk`` +
  ``opentelemetry-exporter-otlp-proto-http`` installed, spans are exported over OTLP (configure with the standard
  ``OTEL_EXPORTER_OTLP_ENDPOINT`` / ``OTEL_SERVICE_NAME`` variables). Without it, propagation and logs still work.
* Logs: one JSON object per line with traceId, spanId, requestId, tenant and user. Secrets, tokens, connection-string
  passwords and bank identifiers are redacted before writing.
* Metrics: ``GET /metrics`` in Prometheus text format — golden signals per route, outbox lag, workflow tasks,
  integration dead letters and business SLOs computed from the database (cached).
"""
import contextvars
import json
import logging
import os
import re
import secrets
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any, Iterator, Optional

log = logging.getLogger("pic.observability")

# ---------------------------------------------------------------- trace context (W3C Trace Context Level 1)
_TRACEPARENT = re.compile(r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})(?:-.*)?$")


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    sampled: bool = True
    request_id: Optional[str] = None
    tenant: Optional[str] = None
    user: Optional[str] = None

    @property
    def traceparent(self) -> str:
        return f"00-{self.trace_id}-{self.span_id}-{'01' if self.sampled else '00'}"


_current: contextvars.ContextVar[Optional[TraceContext]] = contextvars.ContextVar("pic_trace", default=None)


def new_trace_id() -> str:
    return secrets.token_hex(16)


def new_span_id() -> str:
    return secrets.token_hex(8)


def parse_traceparent(value: Optional[str]) -> Optional[tuple[str, str, bool]]:
    """(trace_id, parent_span_id, sampled) from a traceparent header, or None when absent or invalid."""
    match = _TRACEPARENT.match((value or "").strip().lower())
    if not match:
        return None
    version, trace_id, span_id, flags = match.groups()
    if version == "ff" or trace_id == "0" * 32 or span_id == "0" * 16 or (version == "00" and len(value.strip()) != 55):
        return None
    return trace_id, span_id, bool(int(flags, 16) & 1)


def context_from_headers(traceparent: Optional[str], request_id: Optional[str]) -> TraceContext:
    parsed = parse_traceparent(traceparent)
    if parsed:
        trace_id, parent, sampled = parsed
        return TraceContext(trace_id, new_span_id(), parent, sampled, request_id or trace_id)
    trace_id = new_trace_id()
    return TraceContext(trace_id, new_span_id(), None, True, request_id or trace_id)


def current() -> Optional[TraceContext]:
    return _current.get()


def current_trace_id() -> Optional[str]:
    ctx = _current.get()
    return ctx.trace_id if ctx else None


def activate(ctx: TraceContext) -> contextvars.Token:
    return _current.set(ctx)


def deactivate(token: contextvars.Token) -> None:
    _current.reset(token)


def bind(**fields: Optional[str]) -> None:
    """Add tenant / user to the active context (after the bearer token has been read)."""
    ctx = _current.get()
    if ctx is not None:
        _current.set(replace(ctx, **{k: v for k, v in fields.items() if v is not None}))


def outbound_headers() -> dict[str, str]:
    """Headers a connector adds to outbound calls so the receiving system joins the trace."""
    ctx = _current.get()
    return {"traceparent": ctx.traceparent} if ctx else {}


# ---------------------------------------------------------------- optional OpenTelemetry
_tracer = None
_otel_trace = None


def setup_tracing(service_name: str, enabled: bool) -> bool:
    """Configure OTLP export when requested and the SDK is importable. Returns whether OpenTelemetry is active."""
    global _tracer, _otel_trace
    if not enabled or _tracer is not None:
        return _tracer is not None
    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        log.warning("PIC_OTEL_ENABLED is set but opentelemetry-sdk / opentelemetry-exporter-otlp-proto-http are not installed; "
                    "continuing with trace propagation and logs only")
        return False
    provider = TracerProvider(resource=Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", service_name)}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    otel_trace.set_tracer_provider(provider)
    _otel_trace = otel_trace
    _tracer = otel_trace.get_tracer("pic")
    return True


@contextmanager
def span(name: str, ctx: Optional[TraceContext] = None, kind: str = "INTERNAL", **attributes: Any) -> Iterator[TraceContext]:
    """Open a span. ``ctx`` (from ``context_from_headers``) starts a server span under a remote parent; otherwise the span is
    a child of the active context, or the root of a new trace (worker ticks)."""
    parent = _current.get()
    explicit = ctx is not None
    if ctx is None:
        ctx = TraceContext(parent.trace_id, new_span_id(), parent.span_id, parent.sampled, parent.request_id, parent.tenant, parent.user) \
            if parent else TraceContext(new_trace_id(), new_span_id())
    if _tracer is None:
        token = _current.set(ctx)
        try:
            yield ctx
        finally:
            _current.reset(token)
        return
    otel = _otel_trace
    from opentelemetry.trace import NonRecordingSpan, SpanContext, SpanKind, TraceFlags
    parent_context = None
    if ctx.parent_span_id:
        remote = SpanContext(int(ctx.trace_id, 16), int(ctx.parent_span_id, 16), is_remote=explicit,
                             trace_flags=TraceFlags(1 if ctx.sampled else 0))
        parent_context = otel.set_span_in_context(NonRecordingSpan(remote))
    with _tracer.start_as_current_span(name, context=parent_context, kind=getattr(SpanKind, kind, SpanKind.INTERNAL),
                                       attributes={k: v for k, v in attributes.items() if v is not None}) as otel_span:
        sc = otel_span.get_span_context()
        ctx = replace(ctx, trace_id=format(sc.trace_id, "032x"), span_id=format(sc.span_id, "016x"))
        token = _current.set(ctx)
        try:
            yield ctx
        except Exception as exc:
            otel_span.record_exception(exc)
            otel_span.set_status(otel.Status(otel.StatusCode.ERROR))
            raise
        finally:
            _current.reset(token)


def set_span_attributes(**attributes: Any) -> None:
    if _otel_trace is not None:
        _otel_trace.get_current_span().set_attributes({k: v for k, v in attributes.items() if v is not None})


# ---------------------------------------------------------------- structured logs with redaction
_SENSITIVE_KEY = re.compile(r"(?i)(pass(word|wd)?|secret|token|authori[sz]ation|cookie|iban|account_?(no|num|number)|bank_?account|"
                            r"ifsc|swift|otp|totp|field_?key|api_?key|private|database_?url|dsn)")
_REDACTIONS = [
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-_.~+/=]+"), "Bearer [REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]+"), "[REDACTED_JWT]"),
    (re.compile(r"(postgres(?:ql)?(?:\+\w+)?://[^:/@\s]+:)[^@\s]+@"), r"\1[REDACTED]@"),
    (re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization)(\s*[=:]\s*)([^\s&,;\"']+)"), r"\1\2[REDACTED]"),
    (re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"), "[REDACTED_IFSC]"),
]


def redact_text(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def redact(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "…"
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if isinstance(k, str) and _SENSITIVE_KEY.search(k) else redact(v, depth + 1)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, depth + 1) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str = "pic-api"):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        body: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname, "logger": record.name, "service": self.service,
            "msg": redact_text(record.getMessage()),
        }
        ctx = _current.get()
        if ctx is not None:
            body.update({"traceId": ctx.trace_id, "spanId": ctx.span_id, "requestId": ctx.request_id})
            if ctx.tenant:
                body["tenant"] = ctx.tenant
            if ctx.user:
                body["user"] = ctx.user
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            body.update(redact(fields))
        if record.exc_info:
            body["exc"] = redact_text("".join(traceback.format_exception(*record.exc_info)))
        return json.dumps(body, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def __init__(self):
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        line = redact_text(super().format(record))
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            line += " " + json.dumps(redact(fields), default=str)
        ctx = _current.get()
        return f"{line} trace={ctx.trace_id}" if ctx else line


_configured = False


def configure_logging(service: str = "pic-api", json_logs: bool = True, level: str = "INFO") -> None:
    """Install one stdout handler on the root logger (idempotent). Uvicorn's loggers are routed through it."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service) if json_logs else TextFormatter())
    handler.set_name("pic")
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if h.get_name() != "pic"] + [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    # The API writes its own access line with trace ids; uvicorn's would duplicate it without them.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING if json_logs else logging.INFO)
    _configured = True


# ---------------------------------------------------------------- Prometheus metrics (text exposition 0.0.4)
LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.2, 0.4, 0.8, 1.5, 3.0, 6.0, 12.0)


def _labels(names: tuple[str, ...], values: tuple[str, ...]) -> str:
    if not names:
        return ""
    escaped = (str(v).replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n") for v in values)
    return "{" + ",".join(f'{n}="{v}"' for n, v in zip(names, escaped)) + "}"


class Counter:
    def __init__(self, name: str, help_: str, labels: tuple[str, ...] = ()):
        self.name, self.help, self.label_names = name, help_, labels
        self._values: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def inc(self, *labels: str, amount: float = 1.0) -> None:
        with self._lock:
            self._values[labels] = self._values.get(labels, 0.0) + amount

    def value(self, *labels: str) -> float:
        return self._values.get(labels, 0.0)

    def render(self) -> list[str]:
        out = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        with self._lock:
            out += [f"{self.name}{_labels(self.label_names, k)} {v:g}" for k, v in sorted(self._values.items())]
        return out


class Gauge(Counter):
    def set(self, *labels: str, value: float) -> None:
        with self._lock:
            self._values[labels] = value

    def render(self) -> list[str]:
        lines = super().render()
        lines[1] = f"# TYPE {self.name} gauge"
        return lines


class Histogram:
    def __init__(self, name: str, help_: str, labels: tuple[str, ...] = (), buckets: tuple[float, ...] = LATENCY_BUCKETS):
        self.name, self.help, self.label_names, self.buckets = name, help_, labels, buckets
        self._values: dict[tuple, list] = {}  # labels -> [bucket counts..., sum, count]
        self._lock = threading.Lock()

    def observe(self, value: float, *labels: str) -> None:
        with self._lock:
            row = self._values.setdefault(labels, [0] * len(self.buckets) + [0.0, 0])
            for i, bound in enumerate(self.buckets):
                if value <= bound:
                    row[i] += 1
            row[-2] += value
            row[-1] += 1

    def render(self) -> list[str]:
        out = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        names = self.label_names + ("le",)
        with self._lock:
            for labels, row in sorted(self._values.items()):
                for i, bound in enumerate(self.buckets):
                    out.append(f"{self.name}_bucket{_labels(names, labels + (f'{bound:g}',))} {row[i]}")
                out.append(f"{self.name}_bucket{_labels(names, labels + ('+Inf',))} {row[-1]}")
                out.append(f"{self.name}_sum{_labels(self.label_names, labels)} {row[-2]:.6f}")
                out.append(f"{self.name}_count{_labels(self.label_names, labels)} {row[-1]}")
        return out


HTTP_REQUESTS = Counter("pic_http_requests_total", "HTTP requests by method, route template and status code.", ("method", "route", "status"))
HTTP_ERRORS = Counter("pic_http_server_errors_total", "HTTP responses with status >= 500 by route template.", ("method", "route"))
HTTP_LATENCY = Histogram("pic_http_request_duration_seconds", "Time to response headers by method and route template.", ("method", "route"))
HTTP_IN_FLIGHT = Gauge("pic_http_requests_in_flight", "Requests currently being handled.")
RATE_LIMITED = Counter("pic_http_rate_limited_total", "Requests rejected with 429 by limiter scope.", ("scope",))
BODY_REJECTED = Counter("pic_http_body_too_large_total", "Requests rejected with 413.")
WORKER_TICKS = Counter("pic_worker_ticks_total", "Worker ticks by outcome (this process only).", ("outcome",))
_REGISTRY = [HTTP_REQUESTS, HTTP_ERRORS, HTTP_LATENCY, HTTP_IN_FLIGHT, RATE_LIMITED, BODY_REJECTED, WORKER_TICKS]


def observe_request(method: str, route: str, status: int, seconds: float) -> None:
    HTTP_REQUESTS.inc(method, route, str(status))
    HTTP_LATENCY.observe(seconds, method, route)
    if status >= 500:
        HTTP_ERRORS.inc(method, route)


# ---------------------------------------------------------------- database-derived gauges and business SLOs
SLO_WINDOW_DAYS = 30
WORKER_APP_NAME = "pic-worker"


def worker_heartbeats(conn) -> list[float]:
    """Epoch seconds of the last tick of each running worker (application_name 'pic-worker hb=<epoch> ...')."""
    from sqlalchemy import text
    names = conn.execute(text("SELECT application_name FROM pg_stat_activity WHERE application_name LIKE :p AND datname = current_database()"),
                         {"p": f"{WORKER_APP_NAME} hb=%"}).scalars().all()
    beats = []
    for name in names:
        match = re.search(r"hb=(\d+)", name or "")
        if match:
            beats.append(float(match.group(1)))
    return beats


def _db_samples() -> list[tuple[str, str, dict, float]]:
    """(metric, help, labels, value) rows from cheap aggregate queries. Owner connection: sees every tenant."""
    from sqlalchemy import text
    from app.pic.db import engine
    from app.pic.platform import clock
    now = clock.now()
    since = now - timedelta(days=SLO_WINDOW_DAYS)
    samples: list[tuple[str, str, dict, float]] = []

    def query(conn, sql: str, params: Optional[dict] = None):
        try:
            with conn.begin_nested():
                return conn.execute(text(sql), params or {}).all()
        except Exception as exc:  # one failing query must not hide the others
            log.warning("metrics query failed: %s", type(exc).__name__)
            return []

    with engine().connect() as conn:
        with conn.begin():
            tenants = {tid: code for tid, code in query(conn, "SELECT id, code FROM pic.tenant")}

            def code(tid) -> str:
                return tenants.get(tid, str(tid))

            for tid in tenants:  # report zeros explicitly: an absent series is not the same as "no backlog"
                t = {"tenant": code(tid)}
                for name, help_ in (("pic_outbox_pending_events", "Outbox events not yet relayed."),
                                    ("pic_workflow_open_tasks", "Open human tasks."),
                                    ("pic_workflow_overdue_tasks", "Open human tasks past their SLA due time.")):
                    samples.append((name, help_, t, 0))
            for tid, pending, oldest, dead in query(conn, """
                    SELECT tenant_id, count(*) FILTER (WHERE published_at IS NULL),
                           min(occurred_at) FILTER (WHERE published_at IS NULL),
                           count(*) FILTER (WHERE published_at >= :since AND last_error LIKE 'DEAD_LETTER%')
                    FROM pic.outbox_event WHERE published_at IS NULL OR published_at >= :since GROUP BY tenant_id""", {"since": since}):
                t = {"tenant": code(tid)}
                samples.append(("pic_outbox_pending_events", "Outbox events not yet relayed.", t, pending))
                samples.append(("pic_outbox_lag_seconds", "Age of the oldest unrelayed outbox event (business clock).", t,
                                max((now - oldest).total_seconds(), 0) if oldest else 0))
                samples.append(("pic_outbox_dead_letters", f"Outbox events dead-lettered in the last {SLO_WINDOW_DAYS} days.", t, dead))
            for tid, open_, overdue in query(conn, """
                    SELECT tenant_id, count(*), count(*) FILTER (WHERE due_at < :now) FROM pic.task WHERE status = 'OPEN'
                    GROUP BY tenant_id""", {"now": now}):
                t = {"tenant": code(tid)}
                samples.append(("pic_workflow_open_tasks", "Open human tasks.", t, open_))
                samples.append(("pic_workflow_overdue_tasks", "Open human tasks past their SLA due time.", t, overdue))
            for tid, status, n in query(conn, """
                    SELECT tenant_id, status, count(*) FROM pic.integration_message
                    WHERE status IN ('PENDING', 'RETRY', 'DEAD_LETTER') GROUP BY tenant_id, status"""):
                samples.append(("pic_integration_messages", "ERP integration messages not yet posted, by status.",
                                {"tenant": code(tid), "status": status}, n))
            for tid, posted, settled in query(conn, """
                    SELECT tenant_id, count(*) FILTER (WHERE status = 'POSTED'), count(*) FILTER (WHERE status IN ('POSTED', 'DEAD_LETTER'))
                    FROM pic.integration_message WHERE created_at >= :since GROUP BY tenant_id""", {"since": since}):
                if settled:
                    samples.append(("pic_slo_posting_success_ratio", f"ERP postings posted / (posted + dead-lettered), last {SLO_WINDOW_DAYS} days.",
                                    {"tenant": code(tid)}, posted / settled))
            for tid, p50, p95, n in query(conn, """
                    SELECT tenant_id,
                           percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM approved_at - submitted_at)),
                           percentile_cont(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM approved_at - submitted_at)), count(*)
                    FROM pic.requisition WHERE approved_at >= :since AND submitted_at IS NOT NULL GROUP BY tenant_id""", {"since": since}):
                t = {"tenant": code(tid)}
                samples.append(("pic_slo_pr_approval_latency_seconds", f"Requisition submit → approved, last {SLO_WINDOW_DAYS} days.",
                                {**t, "quantile": "0.5"}, float(p50 or 0)))
                samples.append(("pic_slo_pr_approval_latency_seconds", f"Requisition submit → approved, last {SLO_WINDOW_DAYS} days.",
                                {**t, "quantile": "0.95"}, float(p95 or 0)))
                samples.append(("pic_slo_pr_approvals", f"Requisitions approved, last {SLO_WINDOW_DAYS} days.", t, n))
            for tid, yes, n in query(conn, """
                    SELECT tenant_id, count(*) FILTER (WHERE touchless), count(*) FROM pic.purchase_order
                    WHERE touchless IS NOT NULL AND created_at >= :since GROUP BY tenant_id""", {"since": since}):
                if n:
                    samples.append(("pic_slo_touchless_ratio", f"Validated POs that met DMN-02 touchless criteria, last {SLO_WINDOW_DAYS} days.",
                                    {"tenant": code(tid)}, yes / n))
            for tid, yes, n in query(conn, """
                    SELECT tenant_id, count(*) FILTER (WHERE first_pass_matched), count(*) FROM pic.invoice
                    WHERE first_pass_matched IS NOT NULL AND created_at >= :since GROUP BY tenant_id""", {"since": since}):
                if n:
                    samples.append(("pic_slo_first_pass_match_ratio", f"Invoices matched within tolerance at first attempt, last {SLO_WINDOW_DAYS} days.",
                                    {"tenant": code(tid)}, yes / n))
            version = query(conn, "SELECT version_num FROM pic.alembic_version")
            head = expected_head()
            samples.append(("pic_schema_info", "Schema revision applied in the database vs the code's migration head.",
                            {"revision": version[0][0] if version else "none", "expected": head or "unknown"},
                            1.0 if version and version[0][0] == head else 0.0))
            try:
                beats = worker_heartbeats(conn)
            except Exception:
                beats = []
            samples.append(("pic_worker_instances", "Workers holding a heartbeat connection.", {}, len(beats)))
            if beats:
                samples.append(("pic_worker_heartbeat_age_seconds", "Seconds since the most recent worker tick.", {}, max(time.time() - max(beats), 0)))
    return samples


_cache: dict[str, Any] = {"at": 0.0, "lines": [], "error": None}
_cache_lock = threading.Lock()


def _render_samples(samples: list[tuple[str, str, dict, float]]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    latest: dict[tuple, tuple[str, str, dict, float]] = {}
    for sample in samples:  # a later sample for the same series replaces an earlier one (zero defaults)
        latest[(sample[0], tuple(sorted(sample[2].items())))] = sample
    for name, help_, labels, value in latest.values():
        if name not in seen:
            seen.add(name)
            out += [f"# HELP {name} {help_}", f"# TYPE {name} gauge"]
        keys = tuple(sorted(labels))
        out.append(f"{name}{_labels(keys, tuple(labels[k] for k in keys))} {float(value):g}")
    # Group lines of one metric family together (Prometheus requires it).
    families: dict[str, list[str]] = {}
    current_family = None
    for line in out:
        if line.startswith("# HELP "):
            current_family = line.split()[2]
        families.setdefault(current_family, []).append(line)
    return [line for fam in families.values() for line in fam]


def render_metrics(cache_seconds: int = 30) -> str:
    lines: list[str] = []
    for metric in _REGISTRY:
        lines += metric.render()
    with _cache_lock:
        if time.monotonic() - _cache["at"] > cache_seconds:
            started = time.perf_counter()
            try:
                _cache["lines"] = _render_samples(_db_samples())
                _cache["error"] = None
            except Exception as exc:
                _cache["error"] = type(exc).__name__
                log.warning("metrics collection failed: %s", _cache["error"])
            _cache["seconds"] = time.perf_counter() - started
            _cache["at"] = time.monotonic()
        lines += _cache["lines"]
        lines += ["# HELP pic_metrics_collection_seconds Time spent on the database-derived metrics.",
                  "# TYPE pic_metrics_collection_seconds gauge", f"pic_metrics_collection_seconds {_cache.get('seconds', 0):.6f}",
                  "# HELP pic_metrics_collection_up 1 when the database-derived metrics were collected.",
                  "# TYPE pic_metrics_collection_up gauge", f"pic_metrics_collection_up {0 if _cache['error'] else 1}"]
    return "\n".join(lines) + "\n"


def reset_metrics_cache() -> None:
    with _cache_lock:
        _cache["at"] = 0.0


# ---------------------------------------------------------------- migration head
_head: dict[str, Optional[str]] = {}


def expected_head() -> Optional[str]:
    """The migration head this code expects (pic_migrations), computed once by reading the revision files (no imports)."""
    if "head" not in _head:
        from app.pic.config import BACKEND_DIR
        revisions: dict[str, tuple[str, ...]] = {}
        try:
            for path in (BACKEND_DIR / "pic_migrations" / "versions").glob("*.py"):
                source = path.read_text(encoding="utf-8")
                rev = re.search(r"^revision\b[^=\n]*=\s*['\"]([^'\"]+)['\"]", source, re.M)
                down = re.search(r"^down_revision\b[^=\n]*=\s*(.+)$", source, re.M)
                if rev:
                    revisions[rev.group(1)] = tuple(re.findall(r"['\"]([^'\"]+)['\"]", down.group(1))) if down else ()
            parents = {d for downs in revisions.values() for d in downs}
            heads = sorted(r for r in revisions if r not in parents)
            _head["head"] = (heads[0] if len(heads) == 1 else ",".join(heads)) if heads else None
            _head["known"] = ",".join(revisions)
        except OSError as exc:
            log.warning("could not read the migration head: %s", type(exc).__name__)
            _head["head"], _head["known"] = None, ""
    return _head["head"]


def known_revision(revision: str) -> bool:
    expected_head()
    return revision in (_head.get("known") or "").split(",")


# ---------------------------------------------------------------- outbox events carry the trace id
def _install_outbox_trace() -> None:
    from sqlalchemy import event
    from app.pic.models import OutboxEvent

    @event.listens_for(OutboxEvent, "before_insert", propagate=True)
    def _stamp(mapper, connection, target):  # noqa: ARG001
        if not target.trace_id:
            target.trace_id = current_trace_id()


_install_outbox_trace()
