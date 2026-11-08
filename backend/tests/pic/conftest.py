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
    # PIC_TEST_KEEP_DB=1 (developer shortcut for iterating on one test file): keep an already seeded schema, only apply new migrations.
    # Never set it for a full run; tests that assume a fresh database (module-scoped tenants) may see their own leftovers.
    with engine.begin() as conn:
        seeded = os.environ.get("PIC_TEST_KEEP_DB") == "1" and bool(
            conn.execute(text("SELECT 1 FROM information_schema.tables WHERE table_schema = 'pic' AND table_name = 'tenant'")).first()
            and conn.execute(text("SELECT 1 FROM pic.tenant WHERE code = 'AXN'")).first())
        if not seeded:
            conn.execute(text("DROP SCHEMA IF EXISTS pic CASCADE"))
    engine.dispose()
    config = Config(str(BACKEND_DIR / "alembic_pic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "pic_migrations"))
    command.upgrade(config, "head")
    import app.pic.services  # noqa: F401
    if not seeded:
        from app.pic.seed import axion
        axion.run(PASSWORD)
    yield


@pytest.fixture(scope="module", autouse=True)
def _business_clock_isolated(database):
    """Every test module starts and ends on the real clock. Scenario.act / approve_all (seed/axion.py) pin the business clock and a
    module that does not unpin leaves it pinned for the next one: the time-based job and agent tests then see a clock that is
    days ahead of the rows they just wrote (idempotency purge counted the fresh row as expired; the acceptance-rate window was
    shifted). Being an autouse fixture of the module scope it runs before the module's own fixtures, so a module that pins the
    clock on purpose in its fixtures still can."""
    from app.pic.platform import clock

    clock.set_pinned(None)
    yield
    clock.set_pinned(None)


@pytest.fixture(scope="session")
def client(database):
    from app.pic.api import install
    app = FastAPI()
    install(app)
    return TestClient(app)


@pytest.fixture(scope="session")
def login(client):
    import time

    tokens: dict = {}
    # Access tokens live 8 hours (wall clock). A full run that is paused (machine asleep) or slow can outlast them, and every
    # later call would answer 401 "Signature has expired": log in again once a cached token is 7 hours old.
    max_age_s = 7 * 3600

    def _login(local: str, tenant: str = "AXN") -> dict:
        key = (tenant, local)
        cached = tokens.get(key)
        if cached is None or time.time() - cached[0] > max_age_s:
            email = local if "@" in local else f"{local}@axion.example"
            r = client.post("/v1/auth/token", json={"tenant": tenant, "email": email, "password": PASSWORD})
            assert r.status_code == 200, r.text
            tokens[key] = (time.time(), {"Authorization": f"Bearer {r.json()['access_token']}"})
        return tokens[key][1]

    return _login


def pytest_collection_modifyitems(config, items):
    """Dataset-pack tests (test_datasets_*.py) add data on top of the signature case: run them after every other test so
    the signature-case assertions always see the base seed."""
    # test_datasets_contracts_kac builds on the KAC pack of test_datasets_erp_client_kac (whose fixture expects to be the one that loads it): last.
    items.sort(key=lambda item: (item.module.__name__.rsplit(".", 1)[-1].startswith("test_datasets_"),
                                 item.module.__name__.rsplit(".", 1)[-1] == "test_datasets_contracts_kac"))
