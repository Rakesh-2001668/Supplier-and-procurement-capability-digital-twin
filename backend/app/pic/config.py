"""Runtime settings for the Purchasing Intelligence Cloud (PIC) backend.

Values come from environment variables or backend/.env. Secrets have no
defaults so a misconfigured environment fails at start-up instead of
silently using a demo value. With PIC_ENV=production, ``get_settings``
refuses to return weak or development settings (see ``production_problems``).
"""
import base64
import binascii
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]

PRODUCTION_NAMES = {"production", "prod"}
DEVELOPMENT_NAMES = {"dev", "development", "local", "test"}
# Values that appear in examples, tests and CI. Never acceptable in production.
PLACEHOLDER_SECRETS = {
    "change-me", "changeme", "secret", "password", "test-secret", "ci-only-secret", "rehearsal-jwt", "dev-secret",
    "test-field-key", "ci-only-field-key", "rehearsal-key", "perf-jwt", "perf-key",
}
PLACEHOLDER_MARKERS = ("change-me", "changeme", "replace-me", "placeholder", "example", "your-")
SSL_MODES_OK = {"require", "verify-ca", "verify-full"}


class InsecureConfiguration(RuntimeError):
    """Raised at start-up when PIC_ENV=production and the configuration is unsafe. Never includes secret values."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Neon / PostgreSQL connection string. postgres:// and postgresql:// are both accepted.
    database_url: str = Field(alias="DATABASE_URL")
    # JWT signing key for the built-in identity endpoint (replace with OIDC/Keycloak in production).
    jwt_secret: str = Field(alias="PIC_JWT_SECRET")
    jwt_ttl_minutes: int = Field(default=480, alias="PIC_JWT_TTL_MINUTES")
    # Master key for field-level encryption (bank accounts, tax IDs, sealed bids).
    # A per-tenant key is derived from it with HKDF. Generate with:
    #   python -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
    field_key: str = Field(alias="PIC_FIELD_KEY")
    # Database role every request runs under (no BYPASSRLS, not the table owner).
    app_role: str = Field(default="pic_app", alias="PIC_APP_ROLE")
    db_schema: str = "pic"
    environment: str = Field(default="dev", alias="PIC_ENV")
    # Comma-separated browser origins allowed to call the API directly (the web app normally calls through its own server).
    cors_origins: str = Field(default="http://localhost:3000", alias="PIC_CORS_ORIGINS")

    # ---------------------------------------------------------------- production surface
    # Old prototype routers (app.routers.*, app.api.*). Unset: off in production, on elsewhere.
    enable_legacy_demo: Optional[bool] = Field(default=None, alias="PIC_ENABLE_LEGACY_DEMO")
    # OpenAPI document and Swagger/ReDoc UIs. Unset: off in production, on elsewhere.
    api_docs: Optional[bool] = Field(default=None, alias="PIC_API_DOCS")

    # ---------------------------------------------------------------- HTTP hardening (platform/http.py)
    # Requests per window per client IP and per signed-in user on /v1. 0 disables. Unset: 600 / 1200 outside dev and test, off in dev.
    rate_limit_per_ip: Optional[int] = Field(default=None, alias="PIC_RATE_LIMIT_PER_IP")
    rate_limit_per_user: Optional[int] = Field(default=None, alias="PIC_RATE_LIMIT_PER_USER")
    rate_limit_window_seconds: int = Field(default=60, alias="PIC_RATE_LIMIT_WINDOW_SECONDS")
    # Proxies in front of the API that append to X-Forwarded-For. 0: the left-most entry (legacy behaviour).
    trusted_proxy_hops: int = Field(default=0, alias="PIC_TRUSTED_PROXY_HOPS")
    # Largest request body accepted; multipart uploads (document capture, CSV import) get the upload limit.
    max_body_bytes: int = Field(default=10 * 1024 * 1024, alias="PIC_MAX_BODY_BYTES")
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, alias="PIC_MAX_UPLOAD_BYTES")
    # Strict-Transport-Security: auto (only when the request arrived over HTTPS), always, off.
    hsts: str = Field(default="auto", alias="PIC_HSTS")

    # ---------------------------------------------------------------- observability (platform/observability.py)
    log_format: Optional[str] = Field(default=None, alias="PIC_LOG_FORMAT")  # json | text; unset: text in dev, json elsewhere
    log_level: str = Field(default="INFO", alias="PIC_LOG_LEVEL")
    # Bearer token for GET /metrics. Unset: /metrics answers only unproxied loopback callers, and never in production.
    metrics_token: Optional[str] = Field(default=None, alias="PIC_METRICS_TOKEN")
    metrics_cache_seconds: int = Field(default=30, alias="PIC_METRICS_CACHE_SECONDS")
    # OpenTelemetry export (needs opentelemetry-sdk + opentelemetry-exporter-otlp-proto-http; OTEL_* variables configure it).
    otel_enabled: bool = Field(default=False, alias="PIC_OTEL_ENABLED")

    # ---------------------------------------------------------------- readiness and worker
    ready_require_worker: bool = Field(default=False, alias="PIC_READY_REQUIRE_WORKER")
    ready_max_outbox_lag_seconds: int = Field(default=0, alias="PIC_READY_MAX_OUTBOX_LAG_SECONDS")  # 0: report only
    worker_heartbeat_file: str = Field(default="/tmp/pic-worker.heartbeat", alias="PIC_WORKER_HEARTBEAT_FILE")
    worker_interval_seconds: float = Field(default=2.0, alias="PIC_WORKER_INTERVAL_SECONDS")
    worker_stale_seconds: int = Field(default=60, alias="PIC_WORKER_STALE_SECONDS")
    # Serverless hosting (Vercel) has no long-running worker process. A scheduler calls GET /internal/worker/tick with
    # "Authorization: Bearer <CRON_SECRET>" (Vercel Cron sends exactly that), and with PIC_INLINE_WORKER every successful
    # write under /v1 drains the outbox, connectors and due timers after its response. Unset CRON_SECRET: the endpoint is off.
    cron_secret: Optional[str] = Field(default=None, alias="CRON_SECRET")
    inline_worker: bool = Field(default=False, alias="PIC_INLINE_WORKER")
    worker_tick_budget_seconds: float = Field(default=50.0, alias="PIC_WORKER_TICK_BUDGET_SECONDS")

    @field_validator("enable_legacy_demo", "api_docs", "rate_limit_per_ip", "rate_limit_per_user", "metrics_token", "log_format",
                     "cron_secret", mode="before")
    @classmethod
    def _blank_is_unset(cls, value):
        # docker compose / env files often pass VAR= ; treat an empty value as "not set" so the defaults apply.
        return None if isinstance(value, str) and value.strip() == "" else value

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url.strip()
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg2://" + url[len("postgresql://"):]
        return url

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in PRODUCTION_NAMES

    @property
    def is_development(self) -> bool:
        return self.environment.strip().lower() in DEVELOPMENT_NAMES

    @property
    def legacy_demo_enabled(self) -> bool:
        return self.enable_legacy_demo if self.enable_legacy_demo is not None else not self.is_production

    @property
    def docs_enabled(self) -> bool:
        return self.api_docs if self.api_docs is not None else not self.is_production

    @property
    def ip_limit(self) -> int:
        return self.rate_limit_per_ip if self.rate_limit_per_ip is not None else (0 if self.is_development else 600)

    @property
    def user_limit(self) -> int:
        return self.rate_limit_per_user if self.rate_limit_per_user is not None else (0 if self.is_development else 1200)

    @property
    def json_logs(self) -> bool:
        fmt = (self.log_format or ("text" if self.is_development else "json")).lower()
        return fmt == "json"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def production_problems(self) -> list[str]:
        """Every reason this configuration is unsafe for production. Messages name variables, never values."""
        problems = []
        secret = self.jwt_secret or ""
        if len(secret) < 32:
            problems.append("PIC_JWT_SECRET must be at least 32 characters (generate: python -c \"import secrets;print(secrets.token_urlsafe(48))\")")
        if secret.lower() in PLACEHOLDER_SECRETS or any(m in secret.lower() for m in PLACEHOLDER_MARKERS) or len(set(secret)) < 8:
            problems.append("PIC_JWT_SECRET is a known placeholder or has too little variety")
        if not valid_field_key(self.field_key):
            problems.append("PIC_FIELD_KEY must be a urlsafe-base64 encoding of exactly 32 random bytes")
        if sslmode(self.database_url) not in SSL_MODES_OK:
            problems.append("DATABASE_URL must use TLS: add sslmode=require (or verify-full)")
        for origin in self.cors_origin_list:
            host = (urlsplit(origin).hostname or origin).lower()
            if origin == "*" or "*" in origin:
                problems.append("PIC_CORS_ORIGINS must not contain '*'")
            elif host in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or host.endswith(".localhost"):
                problems.append("PIC_CORS_ORIGINS must not contain localhost origins")
        if self.metrics_token and len(self.metrics_token) < 24:
            problems.append("PIC_METRICS_TOKEN must be at least 24 characters when set")
        if self.cron_secret and len(self.cron_secret) < 24:
            problems.append("CRON_SECRET must be at least 24 characters when set")
        if self.hsts.lower() not in ("auto", "always", "off"):
            problems.append("PIC_HSTS must be auto, always or off")
        return problems


def valid_field_key(value: Optional[str]) -> bool:
    raw = (value or "").strip()
    if not raw or raw.lower() in PLACEHOLDER_SECRETS:
        return False
    try:
        key = base64.urlsafe_b64decode(raw.encode() + b"=" * (-len(raw) % 4))
    except (binascii.Error, ValueError):
        return False
    # Reject keys that are trivially guessable (all one byte) as well as the wrong length.
    return len(key) == 32 and len(set(key)) > 4 and base64.urlsafe_b64encode(key).decode().rstrip("=") == raw.rstrip("=")


def sslmode(database_url: str) -> Optional[str]:
    try:
        values = parse_qs(urlsplit(database_url.strip()).query).get("sslmode")
    except ValueError:
        return None
    return values[-1].lower() if values else None


def check(settings: Settings) -> Settings:
    if settings.is_production:
        problems = settings.production_problems()
        if problems:
            raise InsecureConfiguration("Refusing to start with PIC_ENV=production:\n  - " + "\n  - ".join(problems))
    return settings


@lru_cache
def get_settings() -> Settings:
    return check(Settings())
