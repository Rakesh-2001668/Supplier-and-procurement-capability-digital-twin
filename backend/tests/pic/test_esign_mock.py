"""The MOCK e-signature provider (app.pic.tools.esign_mock) against the real adapter path of services.contract.

A contract out for signature -> envelope created by the PIC adapter over HTTP at the mock server (started in a thread on port 8765) ->
the mock signs for each party and sends HMAC-signed webhooks to the PIC endpoint -> both parties signed -> contract ACTIVE. The signatures are
recorded with the provider MOCK and shown as demo signatures (not legally binding). Also: a webhook with a wrong signature is refused, a replayed
webhook is idempotent, a webhook for another document is refused, and the provider MOCK is refused when PIC_ENV is production.
"""
import json
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import AppUser, AuditEvent, Contract, Supplier
from app.pic.platform import clock
from app.pic.platform.auth import hash_password
from app.pic.seed.datasets import _tenant_kit as kit
from app.pic.services import contract as contract_svc
from app.pic.tools import esign_mock

from .conftest import PASSWORD

CODE, DOMAIN = "ESM1", "esm1.example"
SECRET, API_KEY, PORT = "mock-esign-webhook-secret", "mock-esign-api-key", 8765
USERS = [("admin", "Admin Anil", ["TENANT_ADMIN"], {}), ("cm", "Chandra Contracts", ["CONTRACT_MANAGER"], {}),
         ("cm2", "Meena Contracts", ["CONTRACT_MANAGER"], {}), ("cm3", "Mohan Contracts", ["CONTRACT_MANAGER"], {})]
ROLE_USER = {"CONTRACT_MANAGER": ["cm2", "cm3"]}
J: dict = {}


def _h(login, who: str) -> dict:
    return login(f"{who}@{DOMAIN}", CODE)


@pytest.fixture(scope="module")
def env(database):
    sc = kit.setup_tenant(CODE, "E-sign Mock Industries Pvt Ltd", "GENERAL", company=("1000", "E-sign Mock Industries Pvt Ltd", "29AAKCD4821M1Z7"),
                          plants=[("P100", "Main plant", "29")], cost_objects=[("COST_CENTER", "6100", "Test cost centre")], holidays=[], domain=DOMAIN, role_user=ROLE_USER)
    kit.create_users(sc, USERS, PASSWORD)
    kit.rule_version(sc, "MFA", "2026.1-ESM", date(2026, 4, 1), {"enforce": False}, "E-sign mock tenant: no MFA challenge for the API tests")
    with tenant_tx(sc.tenant_id) as s:
        sup = Supplier(tenant_id=sc.tenant_id, code="ESM-SUP", legal_name="Demo Signatory Pvt Ltd", status="QUALIFIED", country="IN", state_code="29", payment_terms="N30")
        s.add(sup)
        s.flush()
        s.add(AppUser(tenant_id=sc.tenant_id, email=f"portal@esm-sup.{DOMAIN}", full_name="Demo Signatory portal", password_hash=hash_password(PASSWORD),
                      roles=["SUPPLIER_USER"], attributes={}, supplier_id=sup.id, mfa_enrolled=True))
    return sc


@pytest.fixture(scope="module")
def mock(client, env):
    """The mock provider as a real HTTP server on 127.0.0.1:8765, delivering its webhooks to the PIC app of this test client."""
    def deliver(raw: bytes, headers: dict):
        response = client.post("/v1/esign/webhook", content=raw, headers=headers)
        return response.status_code, response.text

    provider = esign_mock.MockEsign(secret=SECRET, api_key=API_KEY, deliver=deliver)
    server = esign_mock.MockServer(provider, "127.0.0.1", PORT).start()
    yield provider, server
    server.stop()


@pytest.fixture
def configured(monkeypatch, mock):
    _, server = mock
    for name, value in (("PIC_ENV", "test"), ("PIC_ESIGN_PROVIDER", "MOCK"), ("PIC_ESIGN_URL", server.url), ("PIC_ESIGN_API_KEY", API_KEY),
                        ("PIC_ESIGN_WEBHOOK_SECRET", SECRET)):
        monkeypatch.setenv(name, value)


def _tasks(client, headers, ref):
    return [t for t in client.get("/v1/tasks", headers=headers).json() if t["object_ref"] == ref]


def _out_for_signature(client, login, title: str) -> str:
    today = clock.today()
    body = {"type": "NDA", "title": title, "supplier": "ESM-SUP", "company_code": "1000", "valid_from": today.isoformat(),
            "valid_to": (today + timedelta(days=730)).isoformat(), "payment_terms": "N30", "jurisdiction": "IN-KA"}
    created = client.post("/v1/contracts", json=body, headers=_h(login, "cm"))
    assert created.status_code == 201, created.text
    ref = created.json()["number"]
    assert client.post(f"/v1/contracts/{ref}/review", headers=_h(login, "cm")).status_code == 200
    assert client.post(f"/v1/contracts/{ref}/submit", headers=_h(login, "cm3")).status_code == 200
    task = _tasks(client, _h(login, "cm2"), ref)[0]
    assert client.post(f"/v1/tasks/{task['id']}/complete", json={"decision": "APPROVE", "comment": "ok"}, headers=_h(login, "cm2")).status_code == 200
    assert client.get(f"/v1/contracts/{ref}", headers=_h(login, "cm")).json()["status"] == "OUT_FOR_SIGNATURE"
    return ref


# ---------------------------------------------------------------- the mock server on its own
def test_mock_server_speaks_the_envelope_api_and_signs_webhooks_with_the_shared_secret(mock):
    provider, server = mock
    assert httpx.get(f"{server.url}/health").json() == {"status": "ok", "mock": True}
    banner = httpx.get(server.url + "/").text
    assert "demo only" in banner and "legally binding" in banner
    body = {"reference": "PIC:X:SA-1", "documentName": "x", "documentHash": {"algorithm": "SHA-256", "value": "ab" * 32},
            "signers": [{"party": "BUYER", "name": "B", "email": "b@x", "routingOrder": 1}]}
    assert httpx.post(f"{server.url}/envelopes", json=body).status_code == 401            # the API key is checked
    created = httpx.post(f"{server.url}/envelopes", json=body, headers={"Authorization": f"Bearer {API_KEY}"})
    assert created.status_code == 201 and created.json()["envelopeId"].startswith("MOCK-") and created.json()["signingUrls"]["BUYER"].startswith(server.url)
    assert httpx.post(f"{server.url}/envelopes", json={"reference": "x"}, headers={"Authorization": f"Bearer {API_KEY}"}).status_code == 400
    sent = []
    standalone = esign_mock.MockEsign(secret=SECRET, deliver=lambda raw, headers: sent.append((raw, headers)) or (200, "ok"))
    envelope_id = standalone.create(body)["envelopeId"]
    standalone.complete(envelope_id)
    raw, headers = sent[0]
    config = contract_svc.EsignConfig("MOCK", server.url, API_KEY, SECRET)
    contract_svc.verify_webhook(config, raw, headers[esign_mock.SIGNATURE_HEADER])         # PIC's own verification accepts the mock's signature
    event = json.loads(raw)
    assert event["event"] == "SIGNER_COMPLETED" and event["documentHash"] == "ab" * 32 and len(event["signedDocumentHash"]) == 64
    assert [json.loads(r)["event"] for r, _ in sent] == ["SIGNER_COMPLETED", "ENVELOPE_COMPLETED"]
    with pytest.raises(Exception):
        contract_svc.verify_webhook(contract_svc.EsignConfig("MOCK", "", "", "another-secret"), raw, headers[esign_mock.SIGNATURE_HEADER])


# ---------------------------------------------------------------- the whole flow through the real adapter and webhook endpoint
def test_envelope_to_two_signatures_to_an_active_contract_with_demo_signatures(client, login, env, mock, configured):
    provider, server = mock
    ref = J["ref"] = _out_for_signature(client, login, "Mutual NDA - e-sign mock flow")
    contract = client.get(f"/v1/contracts/{ref}", headers=_h(login, "cm")).json()
    assert contract["signatures"] == [] and contract["demoSignature"] is False
    sent = client.post(f"/v1/contracts/{ref}/signature-envelopes", json={"buyer_signer": f"cm2@{DOMAIN}"}, headers=_h(login, "cm"))
    assert sent.status_code == 201, sent.text
    envelope = J["envelope"] = sent.json()
    assert envelope["provider"] == "MOCK" and envelope["envelopeId"].startswith("MOCK-") and [s["party"] for s in envelope["signers"]] == ["BUYER", "SUPPLIER"]
    assert provider.envelopes[envelope["envelopeId"]]["documentHash"] == envelope["documentHash"] and provider.envelopes[envelope["envelopeId"]]["status"] == "SENT"
    assert client.post(f"/v1/contracts/{ref}/signature-envelopes", json={}, headers=_h(login, "cm")).json()["code"] == "ENVELOPE_PENDING"
    # the buyer signs at the provider: signed webhook -> PIC records the signature as a demo signature
    first = provider.complete(envelope["envelopeId"], "BUYER")
    assert [r["status"] for r in first] == [200] and json.loads(first[0]["response"])["signedBy"] == ["BUYER"]
    view = client.get(f"/v1/contracts/{ref}", headers=_h(login, "cm")).json()
    signature = view["signatures"][0]
    assert signature["party"] == "BUYER" and signature["provider"] == "MOCK" and signature["demoSignature"] is True and signature["envelope_ref"] == envelope["envelopeId"]
    assert "not legally binding" in signature["label"] and view["demoSignature"] is True
    assert client.post(f"/v1/contracts/{ref}/activate", headers=_h(login, "cm")).status_code == 422       # the supplier has not signed yet
    # replay: the same webhook again is idempotent; a wrong signature or another document is refused
    replay = provider.post_raw(provider.raw_log[0])
    assert replay["status"] == 200 and json.loads(replay["response"])["duplicate"] is True
    assert len(client.get(f"/v1/contracts/{ref}", headers=_h(login, "cm")).json()["signatures"]) == 1
    forged = provider.post_raw(provider.raw_log[0], secret="not-the-shared-secret")
    assert forged["status"] == 401 and json.loads(forged["response"])["code"] == "ESIGN_SIGNATURE_INVALID"
    other = json.loads(provider.raw_log[0])
    other.update(party="SUPPLIER", documentHash="0" * 64)
    changed = provider.post_raw(json.dumps(other).encode())
    assert changed["status"] == 409 and json.loads(changed["response"])["code"] == "DOCUMENT_CHANGED"
    assert len(client.get(f"/v1/contracts/{ref}", headers=_h(login, "cm")).json()["signatures"]) == 1
    # the supplier signs: both parties signed, envelope completed, the contract can be activated
    second = provider.complete(envelope["envelopeId"])
    assert [r["event"] for r in second] == ["SIGNER_COMPLETED", "ENVELOPE_COMPLETED"] and [r["status"] for r in second] == [200, 200]
    assert json.loads(second[1]["response"])["status"] == "COMPLETED"
    activated = client.post(f"/v1/contracts/{ref}/activate", headers=_h(login, "cm"))
    assert activated.status_code == 200 and activated.json()["status"] == "ACTIVE"
    done = activated.json()
    assert {s["party"] for s in done["signatures"]} == {"BUYER", "SUPPLIER"} and all(s["provider"] == "MOCK" and s["demoSignature"] for s in done["signatures"])
    assert len({s["documentHash"] for s in done["signatures"]}) == 1 and done["signatures"][0]["documentHash"] == envelope["documentHash"]
    # the audit trail says so too
    with tenant_tx(env.tenant_id) as s:
        c = s.execute(select(Contract).where(Contract.number == ref)).scalar_one()
        signed = s.execute(select(AuditEvent).where(AuditEvent.object_id == c.id, AuditEvent.action == "SIGNED")).scalars().all()
        assert len(signed) == 2 and all(e.after["provider"] == "MOCK" and e.after["demoSignature"] is True and "not legally binding" in e.after["notice"] for e in signed)
        assert {e.action for e in s.execute(select(AuditEvent).where(AuditEvent.object_id == c.id)).scalars()} >= {"ESIGN_ENVELOPE_SENT", "SIGNED"}


def test_declined_envelope_is_recorded_and_signs_nothing(client, login, env, mock, configured):
    provider, _ = mock
    ref = _out_for_signature(client, login, "Mutual NDA - declined envelope")
    envelope = client.post(f"/v1/contracts/{ref}/signature-envelopes", json={"buyer_signer": f"cm2@{DOMAIN}"}, headers=_h(login, "cm")).json()
    result = provider.close(envelope["envelopeId"], "DECLINED", "Terms not acceptable")
    assert result[0]["status"] == 200 and json.loads(result[0]["response"])["status"] == "DECLINED"
    view = client.get(f"/v1/contracts/{ref}", headers=_h(login, "cm")).json()
    assert view["signatures"] == [] and view["demoSignature"] is False and view["status"] == "OUT_FOR_SIGNATURE"


# ---------------------------------------------------------------- never in production
def test_mock_provider_is_refused_when_pic_env_is_production(client, login, env, mock, monkeypatch):
    _, server = mock
    ref = _out_for_signature(client, login, "Mutual NDA - production refusal")
    for name, value in (("PIC_ESIGN_PROVIDER", "MOCK"), ("PIC_ESIGN_URL", server.url), ("PIC_ESIGN_API_KEY", API_KEY), ("PIC_ESIGN_WEBHOOK_SECRET", SECRET)):
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PIC_ENV", "development")
    assert "MOCK" in contract_svc.esign_providers() and contract_svc.esign_config().provider == "MOCK"
    monkeypatch.setenv("PIC_ENV", "production")
    assert "MOCK" not in contract_svc.esign_providers() and contract_svc.ESIGN_PROVIDERS == ("DOCUSIGN", "ADOBE_SIGN", "LEEGALITY", "EMUDHRA")
    with pytest.raises(Exception) as refused:
        contract_svc.esign_config()
    assert refused.value.code == "ESIGN_MOCK_FORBIDDEN" and "PIC_ENV is production" in refused.value.detail
    r = client.post(f"/v1/contracts/{ref}/signature-envelopes", json={}, headers=_h(login, "cm"))
    assert r.status_code == 409 and r.json()["code"] == "ESIGN_MOCK_FORBIDDEN"
    hook = client.post("/v1/esign/webhook", content=b"{}", headers={"X-Esign-Signature": "00"})
    assert hook.status_code == 409 and hook.json()["code"] == "ESIGN_MOCK_FORBIDDEN"
    # a real provider is still accepted in production, and unknown names are still rejected
    monkeypatch.setenv("PIC_ESIGN_PROVIDER", "DOCUSIGN")
    assert contract_svc.esign_config().provider == "DOCUSIGN"
    monkeypatch.setenv("PIC_ESIGN_PROVIDER", "SOMETHING_ELSE")
    assert contract_svc.esign_config() is None
    # the start-up check names the variable, and the mock server itself refuses to run
    from app.pic.config import Settings
    monkeypatch.setenv("PIC_ESIGN_PROVIDER", "MOCK")
    settings = Settings(DATABASE_URL="postgresql://u:p@db.internal/pic?sslmode=require", PIC_JWT_SECRET="x9Qm4vTz7LpR2sWb8KdN5yHc3JfGaEu6", PIC_FIELD_KEY="Zm9yLXRlc3RpbmctYS1sb25nLXJhbmRvbS1rZXkhIQ==", PIC_ENV="production")
    assert any("PIC_ESIGN_PROVIDER=MOCK" in p for p in settings.production_problems())
    assert esign_mock.main(["--secret", "x"]) == 2
