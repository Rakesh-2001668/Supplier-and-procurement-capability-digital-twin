"""Production readiness: legacy surface, start-up refusals, rate limits, body limits, problem traceIds, metrics, readiness,
DPDP privacy requests and the ADM-03 approval-matrix simulation."""
import base64
import secrets
import uuid

import pytest
from sqlalchemy import select

from app.pic import config
from app.pic.config import InsecureConfiguration, Settings

GOOD_FIELD_KEY = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
GOOD_JWT = secrets.token_urlsafe(48)


def production(**overrides) -> Settings:
    values = {"DATABASE_URL": "postgresql://pic:pw@db.example.internal/pic?sslmode=require", "PIC_JWT_SECRET": GOOD_JWT,
              "PIC_FIELD_KEY": GOOD_FIELD_KEY, "PIC_ENV": "production", "PIC_CORS_ORIGINS": ""}
    values.update(overrides)
    return Settings(_env_file=None, **values)


# ---------------------------------------------------------------- legacy surface and docs
def test_legacy_routers_and_docs_off_in_production():
    from app.main import create_app
    prod = create_app(production())
    paths = prod.openapi()["paths"]
    assert not [p for p in paths if p.startswith("/api/")], "legacy prototype routes must not be mounted in production"
    assert "/v1/me" in paths and "/v1/admin/rules/simulate" in paths
    assert prod.docs_url is None and prod.openapi_url is None and prod.redoc_url is None

    dev = create_app(production(PIC_ENV="dev"))
    assert [p for p in dev.openapi()["paths"] if p.startswith("/api/v1/")], "local demo keeps the prototype routes"
    assert dev.docs_url == "/docs"
    explicit = create_app(production(PIC_ENABLE_LEGACY_DEMO="true", PIC_API_DOCS="true"))
    assert [p for p in explicit.openapi()["paths"] if p.startswith("/api/v1/")] and explicit.docs_url == "/docs"


# ---------------------------------------------------------------- start-up refusals
@pytest.mark.parametrize("override, fragment", [
    ({"PIC_JWT_SECRET": "short-secret"}, "PIC_JWT_SECRET must be at least 32"),
    ({"PIC_JWT_SECRET": "change-me-change-me-change-me-change-me"}, "placeholder"),
    ({"PIC_JWT_SECRET": "a" * 40}, "placeholder"),
    ({"PIC_FIELD_KEY": "test-field-key"}, "PIC_FIELD_KEY"),
    ({"PIC_FIELD_KEY": base64.urlsafe_b64encode(secrets.token_bytes(16)).decode()}, "PIC_FIELD_KEY"),
    ({"DATABASE_URL": "postgresql://pic:pw@db.example.internal/pic"}, "sslmode=require"),
    ({"DATABASE_URL": "postgresql://pic:pw@db.example.internal/pic?sslmode=prefer"}, "sslmode=require"),
    ({"PIC_CORS_ORIGINS": "*"}, "'*'"),
    ({"PIC_CORS_ORIGINS": "https://pic.example.com,http://localhost:3000"}, "localhost"),
    ({"PIC_METRICS_TOKEN": "short"}, "PIC_METRICS_TOKEN"),
])
def test_production_refuses_unsafe_configuration(override, fragment):
    settings = production(**override)
    with pytest.raises(InsecureConfiguration) as raised:
        config.check(settings)
    message = str(raised.value)
    assert fragment in message
    # Never echo secret values.
    for name in ("PIC_JWT_SECRET", "PIC_FIELD_KEY", "PIC_METRICS_TOKEN"):
        if name in override and len(override[name]) > 6:
            assert override[name] not in message
    assert "pw@" not in message


def test_production_accepts_a_safe_configuration_and_dev_is_lenient():
    assert config.check(production(PIC_CORS_ORIGINS="https://pic.example.com", PIC_METRICS_TOKEN=secrets.token_urlsafe(32))).is_production
    assert config.check(production(PIC_ENV="dev", PIC_JWT_SECRET="x", PIC_FIELD_KEY="y", DATABASE_URL="postgresql://localhost/x"))
    assert config.valid_field_key(GOOD_FIELD_KEY) and not config.valid_field_key(base64.urlsafe_b64encode(b"\0" * 32).decode())


# ---------------------------------------------------------------- rate limiting, body limit, traceId
@pytest.fixture
def limits(monkeypatch):
    from app.pic.platform import http
    settings = config.get_settings()
    http.limiter.clear()

    def apply(**values):
        for key, value in values.items():
            monkeypatch.setattr(settings, key, value)
    yield apply
    http.limiter.clear()


def test_rate_limit_per_ip_returns_problem_with_retry_after_and_trace_id(client, login, limits):
    limits(rate_limit_per_ip=3, rate_limit_per_user=0, rate_limit_window_seconds=60)
    headers = {**login("buyer"), "X-Forwarded-For": "203.0.113.77"}
    for _ in range(3):
        assert client.get("/v1/me", headers=headers).status_code == 200
    traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    r = client.get("/v1/me", headers={**headers, "traceparent": traceparent})
    assert r.status_code == 429
    assert r.headers["content-type"].startswith("application/problem+json")
    assert 1 <= int(r.headers["Retry-After"]) <= 120
    body = r.json()
    assert body["code"] == "RATE_LIMITED" and body["scope"] == "ip" and body["traceId"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert r.headers["traceparent"].startswith("00-4bf92f3577b34da6a3ce929d0e0e4736-")
    # Another client address is not affected; probes are never limited.
    assert client.get("/v1/me", headers={**login("buyer"), "X-Forwarded-For": "203.0.113.78"}).status_code == 200
    assert client.get("/healthz", headers={"X-Forwarded-For": "203.0.113.77"}).status_code == 200


def test_rate_limit_per_user(client, login, limits):
    limits(rate_limit_per_ip=0, rate_limit_per_user=2)
    for ip in ("198.51.100.1", "198.51.100.2"):
        assert client.get("/v1/me", headers={**login("buyer"), "X-Forwarded-For": ip}).status_code == 200
    r = client.get("/v1/me", headers={**login("buyer"), "X-Forwarded-For": "198.51.100.3"})
    assert r.status_code == 429 and r.json()["scope"] == "user" and r.json()["traceId"]
    assert client.get("/v1/me", headers={**login("requester"), "X-Forwarded-For": "198.51.100.3"}).status_code == 200


def test_sliding_window_limiter_math():
    from app.pic.platform.http import SlidingWindowLimiter
    limiter = SlidingWindowLimiter()
    assert all(limiter.hit("k", 10, 60, now=600.0 + i) is None for i in range(10))
    assert limiter.hit("k", 10, 60, now=615.0) is not None
    # Half-way through the next window, half of the previous window's 10 still count: 5 more are allowed.
    assert all(limiter.hit("k", 10, 60, now=690.0) is None for _ in range(5))
    assert limiter.hit("k", 10, 60, now=690.0) is not None
    assert limiter.hit("k", 10, 60, now=900.0) is None


def test_body_limit_and_problem_trace_ids(client, login, limits):
    limits(max_body_bytes=200)
    r = client.post("/v1/auth/token", content=b'{"tenant":"AXN","email":"x","password":"' + b"p" * 400 + b'"}',
                    headers={"content-type": "application/json", "X-Request-ID": "trace-413"})
    assert r.status_code == 413 and r.json()["code"] == "PAYLOAD_TOO_LARGE" and r.json()["traceId"] == "trace-413"
    # Framework errors are problem+json with a traceId too: unknown route, validation, wrong method.
    missing = client.get("/v1/no-such-route", headers={"X-Request-ID": "trace-404"})
    assert missing.status_code == 404 and missing.json()["traceId"] == "trace-404" and missing.json()["code"] == "NOT_FOUND"
    invalid = client.post("/v1/auth/token", json={"tenant": "AXN"})
    assert invalid.status_code == 422 and invalid.json()["code"] == "VALIDATION_FAILED" and invalid.json()["traceId"]
    assert all("input" not in e for e in invalid.json()["errors"])
    assert client.delete("/v1/me", headers=login("buyer")).json()["traceId"]
    # Every response carries a W3C traceparent and the API's security headers.
    ok = client.get("/v1/me", headers=login("buyer"))
    assert ok.headers["traceparent"].count("-") == 3 and ok.headers["Content-Security-Policy"].startswith("default-src 'none'")
    assert "Strict-Transport-Security" not in ok.headers
    assert "Strict-Transport-Security" in client.get("/healthz", headers={"X-Forwarded-Proto": "https"}).headers


# ---------------------------------------------------------------- metrics and readiness
def test_metrics_require_the_token_and_report_golden_signals_and_slos(client, login, limits):
    from app.pic.platform import observability
    observability.reset_metrics_cache()
    client.get("/v1/me", headers=login("buyer"))
    local = client.get("/metrics")  # unproxied local caller outside production, no token configured
    assert local.status_code == 200
    assert client.get("/metrics", headers={"X-Forwarded-For": "203.0.113.5"}).status_code == 403

    token = secrets.token_urlsafe(32)
    limits(metrics_token=token)
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    observability.reset_metrics_cache()
    r = client.get("/metrics", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain; version=0.0.4")
    text = r.text
    for metric in ("pic_http_requests_total{method=\"GET\",route=\"/v1/me\",status=\"200\"}", "pic_http_request_duration_seconds_bucket",
                   "pic_outbox_pending_events", "pic_outbox_lag_seconds", "pic_workflow_open_tasks", "pic_workflow_overdue_tasks",
                   "pic_schema_info", "pic_metrics_collection_up 1", "pic_slo_first_pass_match_ratio", "pic_slo_touchless_ratio"):
        assert metric in text, metric
    assert 'tenant="AXN"' in text
    # Each metric family is contiguous (Prometheus rejects split families).
    families = [line.split()[2] for line in text.splitlines() if line.startswith("# TYPE ")]
    assert len(families) == len(set(families))


def test_readiness_reports_schema_worker_and_outbox(client):
    from app.pic.platform import observability
    from app.pic.worker import Heartbeat
    r = client.get("/readyz")
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ready"
    assert body["checks"]["schema"] == {"status": "ok", "revision": observability.expected_head()}
    assert "pending" in body["checks"]["outbox"]
    heartbeat = Heartbeat(path=None)
    try:
        heartbeat.beat()
        worker = client.get("/readyz").json()["checks"]["worker"]
        assert worker["status"] == "ok" and worker["instances"] >= 1 and worker["heartbeatAgeSeconds"] <= 5
    finally:
        heartbeat.close()


def test_readiness_can_require_the_worker(client, limits):
    limits(ready_require_worker=True, worker_stale_seconds=60)
    from app.pic.worker import Heartbeat
    heartbeat = Heartbeat()
    heartbeat.beat()
    try:
        assert client.get("/readyz").status_code == 200
    finally:
        heartbeat.close()
    import time
    for _ in range(20):  # the closed session leaves pg_stat_activity asynchronously
        r = client.get("/readyz")
        if r.status_code == 503:
            break
        time.sleep(0.1)
    assert r.status_code == 503 and r.json()["checks"]["worker"]["status"] == "absent"


def test_outbox_events_carry_the_active_trace_id(client, login):
    from app.pic.db import tenant_tx
    from app.pic.models import OutboxEvent
    from app.pic.platform import observability, outbox
    tenant_id = _tenant_id(client, login)
    ctx = observability.context_from_headers(f"00-{uuid.uuid4().hex}-00f067aa0ba902b7-01", None)
    token = observability.activate(ctx)
    try:
        with tenant_tx(tenant_id) as s:
            event_id = outbox.emit(s, "test.trace", "TEST", uuid.uuid4(), "TRACE-1", {}).id
    finally:
        observability.deactivate(token)
    with tenant_tx(tenant_id) as s:
        stored = s.get(OutboxEvent, event_id)
        assert stored.trace_id == ctx.trace_id
        stored.published_at = stored.occurred_at  # no consumer: mark relayed so it does not count as backlog


# ---------------------------------------------------------------- DPDP privacy requests
def _tenant_id(client, login) -> uuid.UUID:
    from app.pic.db import system_tx
    from app.pic.models import Tenant
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()


def _new_user(tenant_id: uuid.UUID, roles: list[str], email: str) -> uuid.UUID:
    from app.pic.db import tenant_tx
    from app.pic.models import AppUser
    from app.pic.platform.auth import hash_password
    from tests.pic.conftest import PASSWORD
    with tenant_tx(tenant_id) as s:
        user = AppUser(tenant_id=tenant_id, email=email, full_name="Priya Test", password_hash=hash_password(PASSWORD), roles=roles,
                       attributes={"phone": "+91 98765 43210", "plants": ["*"]})
        s.add(user)
        s.flush()
        return user.id


def test_privacy_export_and_erase(client, login):
    from app.pic.db import tenant_tx
    from app.pic.models import AppUser, AuditEvent, Notification, Task
    from app.pic.platform import audit
    from tests.pic.conftest import PASSWORD
    tenant_id = _tenant_id(client, login)
    email = f"privacy.{uuid.uuid4().hex[:6]}@axion.example"
    user_id = _new_user(tenant_id, ["PRIVACY_TEST_ROLE"], email)
    with tenant_tx(tenant_id) as s:
        s.add(Notification(tenant_id=tenant_id, user_id=user_id, kind="TASK_ASSIGNED", title="Hello", body="Body"))
        task = Task(tenant_id=tenant_id, kind="TEST", name="Privacy test task", object_type="APP_USER", object_id=user_id,
                    object_ref="PRIV-1", candidate_role="PRIVACY_TEST_ROLE", status="OPEN")
        s.add(task)
        s.flush()
        task_id = task.id
    admin = login("admin")

    # Tenant administrator only.
    assert client.get(f"/v1/admin/privacy/users/{user_id}/export", headers=login("buyer")).status_code == 403
    assert client.post(f"/v1/admin/privacy/users/{user_id}/erase", json={"reason": "DPDP-TEST-1 left company"},
                       headers=login("buyer")).status_code == 403

    export = client.get(f"/v1/admin/privacy/users/{user_id}/export", headers=admin)
    assert export.status_code == 200, export.text
    data = export.json()
    assert data["profile"]["email"] == email and data["profile"]["attributes"]["phone"].startswith("+91")
    assert data["notifications"][0]["title"] == "Hello" and "password_hash" not in str(data)

    # Refused while the user can still work an open task.
    refused = client.post(f"/v1/admin/privacy/users/{user_id}/erase", json={"reason": "DPDP-TEST-1 left company"}, headers=admin)
    assert refused.status_code == 409 and refused.json()["code"] == "OPEN_TASKS" and "PRIV-1" in refused.json()["tasks"]
    with tenant_tx(tenant_id) as s:
        s.get(Task, task_id).status = "CANCELLED"

    with tenant_tx(tenant_id) as s:
        audit_before = s.execute(select(AuditEvent.seq, AuditEvent.hash).order_by(AuditEvent.seq)).all()
    erased = client.post(f"/v1/admin/privacy/users/{user_id}/erase", json={"reason": "DPDP-TEST-1 left company"}, headers=admin)
    assert erased.status_code == 200, erased.text
    assert erased.json()["status"] == "ERASED" and erased.json()["notificationsDeleted"] == 1
    with tenant_tx(tenant_id) as s:
        user = s.get(AppUser, user_id)
        assert user.email.endswith("@erased.invalid") and user.full_name.startswith("Erased user") and not user.active
        assert "phone" not in user.attributes and user.attributes["plants"] == ["*"] and user.attributes["erased"]
        assert not s.execute(select(Notification).where(Notification.user_id == user_id)).scalars().all()
        # Audit integrity: earlier events untouched, the erasure appended, chain still valid, no personal data in the new event.
        after = s.execute(select(AuditEvent.seq, AuditEvent.hash).order_by(AuditEvent.seq)).all()
        assert after[:len(audit_before)] == audit_before
        event = s.execute(select(AuditEvent).where(AuditEvent.object_id == user_id, AuditEvent.action == "PERSONAL_DATA_ERASED")).scalar_one()
        assert email not in str(event.after) and "Priya" not in str(event.after) and event.reason == "DPDP-TEST-1 left company"
        assert audit.verify_chain(s)["valid"]
    # The person can no longer sign in, and a second erasure is refused.
    assert client.post("/v1/auth/token", json={"tenant": "AXN", "email": email, "password": PASSWORD}).status_code in (401, 403)
    assert client.post(f"/v1/admin/privacy/users/{user_id}/erase", json={"reason": "DPDP-TEST-1 again please"},
                       headers=admin).json()["code"] == "ALREADY_ERASED"
    me = client.get("/v1/me", headers=admin).json()
    assert client.post(f"/v1/admin/privacy/users/{me['userId']}/erase", json={"reason": "DPDP-TEST-2 self request"},
                       headers=admin).json()["code"] == "SELF_ERASURE"


def test_privacy_retention_report(client, login):
    assert client.get("/v1/admin/privacy/retention", headers=login("buyer")).status_code == 403
    r = client.get("/v1/admin/privacy/retention", headers=login("admin"))
    assert r.status_code == 200
    body = r.json()
    keys = {c["key"] for c in body["categories"]}
    assert {"user_profile", "notification", "audit_actor", "access_logs"} <= keys
    assert all(c["lawfulBasis"] and c["purpose"] for c in body["categories"])
    assert "dataResidency" in body and body["dataResidency"]["provider"] == "local"


# ---------------------------------------------------------------- ADM-03 simulation
def _simulate(client, login, **body):
    r = client.post("/v1/admin/rules/simulate", json=body, headers=login("admin"))
    assert r.status_code == 200, r.text
    return r.json()


def test_simulation_dmn01_band_edges(client, login):
    first = _simulate(client, login, key="DMN-01", inputs={"valueMinor": 1, "channel": "OTHER"})
    bands = first["resolved"]["body"]["bands"]
    assert first["resolved"]["ref"].startswith("DMN-01@")
    for index, band in enumerate(bands):
        if band["upTo"] is None:
            continue
        below = _simulate(client, login, key="DMN-01", inputs={"valueMinor": band["upTo"] - 1, "channel": "OTHER"})["result"]
        at = _simulate(client, login, key="DMN-01", inputs={"valueMinor": band["upTo"], "channel": "OTHER"})["result"]
        assert below["band"] == index + 1 and below["chain"] == band["chain"]
        assert at["band"] == index + 2 and at["chain"] == bands[index + 1]["chain"], "the band bound is exclusive"
    auto = [b for b in bands if b.get("autoChannels")]
    if auto:
        r = _simulate(client, login, key="DMN-01", inputs={"valueMinor": auto[0]["upTo"] - 1, "channel": auto[0]["autoChannels"][0]})
        assert r["result"]["chain"] == [] and r["result"]["autoApproved"]
    asset = _simulate(client, login, key="DMN-01", inputs={"valueMinor": 1, "channel": "OTHER", "purchaseType": "ASSET"})
    assert set(first["resolved"]["body"].get("assetAdds", [])) <= set(asset["result"]["chain"])
    assert any(c["applies"] for c in first["candidates"])


def test_simulation_po_touchless_and_compare(client, login):
    good = {"valueMinor": 100_000, "supplierStatus": "QUALIFIED", "priceSources": ["CONTRACT"], "lateProb": "0.05"}
    r = _simulate(client, login, key="DMN-02", inputs=good)
    assert r["result"]["touchless"] and r["result"]["decision"] == "TOUCHLESS_RELEASE" and r["result"]["riskRuleSet"].startswith("PO-RISK@")
    band = r["resolved"]["body"]["touchlessBandMinor"]
    over = _simulate(client, login, key="DMN-02", inputs={**good, "valueMinor": band + 1})
    assert not over["result"]["touchless"] and "value above touchless band" in over["result"]["reasons"]
    unqualified = _simulate(client, login, key="DMN-02", inputs={**good, "supplierStatus": "NEW"})
    assert not unqualified["result"]["touchless"] and any(f["code"] == "SUPPLIER_NOT_QUALIFIED" for f in unqualified["result"]["riskFactors"])
    draft = {**over["resolved"]["body"], "touchlessBandMinor": band * 10}
    compared = _simulate(client, login, key="DMN-02", inputs={**good, "valueMinor": band + 1}, draftBody=draft)
    assert compared["compare"]["changed"] and "touchless" in compared["compare"]["changedFields"]
    assert compared["compare"]["draft"]["result"]["touchless"] and compared["compare"]["draft"]["ref"] == "DMN-02@draft"
    po = _simulate(client, login, key="PO-APPROVAL", inputs={"valueMinor": 1, "priceDeviation": True})
    assert po["result"]["chain"][0] == po["resolved"]["body"]["bands"][0]["chain"][0]
    for key, inputs in (("AWARD-APPROVAL", {"annualValueMinor": 10**12}), ("CONTRACT-APPROVAL", {"valueMinor": 10**12}),
                        ("CONTRACT-AMENDMENT", {"kind": "TERMINATION"}), ("DMN-03", {"poUnitPriceMinor": 10000, "invoiceUnitPriceMinor": 10500,
                                                                                      "invoicedQty": "1", "availableQty": "1"})):
        result = _simulate(client, login, key=key, inputs=inputs)["result"]
        assert result.get("chain") or result.get("decision"), key
    assert client.post("/v1/admin/rules/simulate", json={"key": "DMN-01", "inputs": {}}, headers=login("admin")).status_code == 422
    assert client.post("/v1/admin/rules/simulate", json={"key": "DMN-01", "inputs": {"valueMinor": 1}},
                       headers=login("buyer")).status_code == 403
