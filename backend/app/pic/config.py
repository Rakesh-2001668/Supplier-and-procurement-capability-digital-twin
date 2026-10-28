"""Runtime settings for the Purchasing Intelligence Cloud (PIC) backend.

Values come from environment variables or backend/.env. Secrets have no
defaults so a misconfigured environment fails at start-up instead of
silently using a demo value.
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


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

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url.strip()
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg2://" + url[len("postgresql://"):]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
