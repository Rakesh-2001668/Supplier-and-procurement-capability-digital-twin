"""Test harness: fresh `pic` schema, migrations, the Axion signature case, and an API client.

Uses TEST_DATABASE_URL (default: local test server on 54329). Never point it at Neon production:
the fixture drops and recreates the pic schema.
"""
import os

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres@127.0.0.1:54329/pic_test")
os.environ.setdefault("PIC_JWT_SECRET", "test-secret")
os.environ.setdefault("PIC_FIELD_KEY", "test-field-key")

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.pic.config import BACKEND_DIR  # noqa: E402

PASSWORD = "Test-Only-Password-1"


@pytest.fixture(scope="session", autouse=True)
def database():
    url = os.environ["DATABASE_URL"]
    assert "neon.tech" not in url, "Refusing to run destructive tests against Neon"
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS pic CASCADE"))
    engine.dispose()
    config = Config(str(BACKEND_DIR / "alembic_pic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "pic_migrations"))
    command.upgrade(config, "head")
    import app.pic.services  # noqa: F401
    from app.pic.seed import axion
    axion.run(PASSWORD)
    yield


@pytest.fixture(scope="session")
def client(database):
    from app.pic.api import install
    app = FastAPI()
    install(app)
    return TestClient(app)


@pytest.fixture(scope="session")
def login(client):
    tokens = {}

    def _login(local: str, tenant: str = "AXN") -> dict:
        key = (tenant, local)
        if key not in tokens:
            email = local if "@" in local else f"{local}@axion.example"
            r = client.post("/v1/auth/token", json={"tenant": tenant, "email": email, "password": PASSWORD})
            assert r.status_code == 200, r.text
            tokens[key] = {"Authorization": f"Bearer {r.json()['access_token']}"}
        return tokens[key]

    return _login
