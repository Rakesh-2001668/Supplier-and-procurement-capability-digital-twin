"""Organisation registration (migration 0030, services/registration.py): shared-mailbox rule, named first administrator, optional "authorised
by", e-mail confirmation, screening, the platform operator console (approve provisions the organisation; reject), and the controls around it
(registration closed without e-mail, operators only, MFA for operators, PLATFORM_OPERATOR not assignable by an organisation)."""
import re
import uuid
from datetime import timedelta
from urllib.parse import unquote

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import AppUser, AuditEvent, OrgRegistration, Tenant
from app.pic.platform import clock, mailer
from app.pic.platform.auth import hash_password, token_response
from app.pic.services import registration
from tests.pic.conftest import PASSWORD

OPERATOR = "operator.test@platform.example"
RUN = uuid.uuid4().hex[:6]
CODE = f"AP{RUN.upper()}"  # unique per run: re-running on a kept database never meets its own earlier requests


def _d(name: str) -> str:
    return f"{name}-{RUN}.example"


@pytest.fixture
def outbox(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setenv("PIC_WEB_URL", "https://app.example")
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subject, text, html=None, attachments=None: sent.append(
        {"to": to, "subject": subject, "text": text}) or "SENT")
    # every request of this module comes from the test client's address: the per-network limit is tested on its own
    real_policy = registration.policy
    monkeypatch.setattr(registration, "policy", lambda: {**real_policy(), "maxPerIpPerHour": 1000})
    return sent


def _form(domain: str, **over) -> dict:
    body = {"kind": "BUYER", "companyName": f"{domain.split('.')[0].title()} Industries Pvt Ltd", "country": "IN", "stateCode": "33",
            "industryTemplate": "MANUFACTURING", "organisationEmail": f"purchase@{domain}", "adminName": "Asha Rao",
            "adminEmail": f"asha.rao@{domain}", "adminPhone": "+91 98400 12345", "authorisedByName": "K. Raman",
            "authorisedByDesignation": "Managing Director", "expectedUsers": 40, "acceptTerms": True}
    body.update(over)
    return body


def _link_token(mail: dict, path: str) -> str:
    match = re.search(rf"{re.escape(path)}\?token=(\S+)", mail["text"])
    assert match, mail["text"]
    return unquote(match.group(1))


@pytest.fixture
def operator(client, outbox):
    """A platform operator with a usable session (the account itself is created exactly as by the command-line tool)."""
    platform_id = registration.ensure_platform()
    with tenant_tx(platform_id) as s:
        exists = s.execute(select(AppUser.id).where(AppUser.email == OPERATOR)).first()
    if not exists:
        result = registration.create_operator(OPERATOR, "Test Operator")
        assert result["activationUrl"].startswith("https://app.example/pic/activate?token=")
    with tenant_tx(platform_id) as s:
        user = s.execute(select(AppUser).where(AppUser.email == OPERATOR)).scalar_one()
        user.password_hash, user.activation_pending = hash_password(PASSWORD), False
        s.flush()
        with system_tx() as ts:
            tenant = ts.get(Tenant, platform_id)
            ts.expunge(tenant)
        token = token_response(user, tenant)["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _confirmed(client, outbox, domain: str, **over) -> str:
    r = client.post("/v1/public/registrations", json=_form(domain, **over))
    assert r.status_code == 202, r.text
    token = _link_token([m for m in outbox if m["to"] == f"purchase@{domain}"][-1], "/register/verify")
    v = client.post("/v1/public/registrations/verify", json={"token": token})
    assert v.status_code == 200 and v.json()["status"] == "PENDING_APPROVAL", v.text
    with system_tx() as s:
        return str(s.execute(select(OrgRegistration.id).where(OrgRegistration.org_domain == domain)).scalar_one())


def test_registration_is_closed_until_email_and_web_address_are_set(client, monkeypatch):
    monkeypatch.delenv("PIC_WEB_URL", raising=False)
    monkeypatch.setattr(mailer, "configured", lambda: False)
    assert client.get("/v1/public/registrations/status").json()["enabled"] is False
    r = client.post("/v1/public/registrations", json=_form("closed.example"))
    assert r.status_code == 503 and r.json()["code"] == "REGISTRATION_CLOSED"


@pytest.mark.parametrize("over, fragment", [
    ({"organisationEmail": "asha@rules.example"}, "shared mailbox"),
    ({"organisationEmail": "purchase@gmail.com", "adminEmail": "asha.rao@gmail.com"}, "own domain"),
    ({"adminEmail": "asha.rao@elsewhere.example"}, "company domain rules.example"),
    ({"adminEmail": "accounts@rules.example"}, "not a shared mailbox"),
    ({"authorisedByDesignation": None}, "authorised by"),
    ({"acceptTerms": False}, "terms of use"),
    ({"kind": "SUPPLIER"}, "next release"),
    ({"gstin": "33AAAAA0000A1Z0"}, "GSTIN"),
])
def test_registration_rules(client, outbox, over, fragment):
    r = client.post("/v1/public/registrations", json=_form("rules.example", **over))
    assert r.status_code == 422 and fragment in r.json()["detail"], r.text
    assert outbox == []


def test_confirm_screen_and_the_same_answer_for_a_known_domain(client, outbox, operator):
    first = client.post("/v1/public/registrations", json=_form(_d("confirm")))
    again = client.post("/v1/public/registrations", json=_form(_d("confirm"), adminEmail=f"ravi.k@{_d('confirm')}"))
    assert first.status_code == again.status_code == 202 and first.json() == again.json()
    with system_tx() as s:
        rows = s.execute(select(OrgRegistration).where(OrgRegistration.org_domain == _d("confirm"))).scalars().all()
        assert len(rows) == 1 and rows[0].status == "PENDING_VERIFICATION" and rows[0].verify_token_hash and rows[0].number.startswith("REG-")
        assert rows[0].authorised_by_name == "K. Raman" and rows[0].authorised_by_designation == "Managing Director"
    mail = [m for m in outbox if m["to"] == f"purchase@{_d('confirm')}"]
    assert len(mail) == 1 and f"asha.rao@{_d('confirm')}" in mail[0]["text"]
    token = _link_token(mail[0], "/register/verify")
    with system_tx() as s:
        assert s.execute(select(OrgRegistration.verify_token_hash)).scalars().all().count(token) == 0  # only its hash is stored

    done = client.post("/v1/public/registrations/verify", json={"token": token})
    assert done.status_code == 200 and done.json()["status"] == "PENDING_APPROVAL"
    assert client.post("/v1/public/registrations/verify", json={"token": token}).status_code == 410   # single use
    with system_tx() as s:
        reg = s.execute(select(OrgRegistration).where(OrgRegistration.org_domain == _d("confirm"))).scalar_one()
        assert reg.status == "PENDING_APPROVAL" and reg.verified_at and reg.verify_token_hash is None
        assert reg.screening["outcome"] in ("CLEAR", "REVIEW") and "sanctionsHits" in reg.screening
    assert any(m["to"] == OPERATOR and "to review" in m["subject"] for m in outbox)


def test_requests_from_one_network_are_limited(client, outbox, monkeypatch):
    monkeypatch.setattr(registration, "policy", lambda: {**registration.RULE_DEFAULTS, "maxPerIpPerHour": 2})
    headers = {"x-forwarded-for": f"203.0.113.{uuid.uuid4().int % 250 + 1}"}
    codes = [client.post("/v1/public/registrations", json=_form(_d(f"limit{i}")), headers=headers).status_code for i in range(3)]
    assert codes == [202, 202, 429]


def test_expired_link(client, outbox):
    client.post("/v1/public/registrations", json=_form(_d("expired")))
    token = _link_token(outbox[-1], "/register/verify")
    with system_tx() as s:
        reg = s.execute(select(OrgRegistration).where(OrgRegistration.org_domain == _d("expired"))).scalar_one()
        reg.verify_expires_at = clock.now() - timedelta(minutes=1)
    r = client.post("/v1/public/registrations/verify", json={"token": token})
    assert r.status_code == 410 and r.json()["code"] == "LINK_EXPIRED"


def test_only_platform_operators_see_and_decide(client, login, outbox, operator):
    reg_id = _confirmed(client, outbox, _d("guarded"))
    admin = login("admin")
    assert client.get("/v1/platform/registrations", headers=admin).status_code == 403
    assert client.post(f"/v1/platform/registrations/{reg_id}/reject", json={"reason": "Not allowed to decide"}, headers=admin).status_code == 403
    listed = client.get("/v1/platform/registrations?status=PENDING_APPROVAL", headers=operator)
    assert listed.status_code == 200 and any(r["id"] == reg_id for r in listed.json())


def test_operator_sign_in_requires_two_step_verification(client, operator):
    r = client.post("/v1/auth/token", json={"email": OPERATOR, "password": PASSWORD})
    assert r.status_code == 403 and r.json()["code"] == "MFA_ENROLMENT_REQUIRED"


def test_an_organisation_cannot_make_a_platform_operator(client, login):
    r = client.post("/v1/admin/users", headers=login("admin"),
                    json={"email": "sneaky@axion.example", "name": "Sneaky", "roles": ["PLATFORM_OPERATOR"], "attributes": {}})
    assert r.status_code in (409, 422) and "PLATFORM_OPERATOR" in r.text
    roles = client.get("/v1/admin/roles", headers=login("admin"))
    assert roles.status_code == 200 and roles.json()
    assert all(role["role"] != "PLATFORM_OPERATOR" for role in roles.json())  # not even listed to an organisation


def test_approval_provisions_the_organisation_and_invites_the_administrator(client, outbox, operator):
    reg_id = _confirmed(client, outbox, _d("approve"))
    detail = client.get(f"/v1/platform/registrations/{reg_id}", headers=operator).json()
    assert detail["authorisedByName"] == "K. Raman" and detail["proposedCode"]
    r = client.post(f"/v1/platform/registrations/{reg_id}/approve", json={"organisationCode": CODE, "note": "Known prospect"}, headers=operator)
    assert r.status_code == 200 and r.json() == {"status": "APPROVED", "organisation": CODE, "activationEmail": "SENT"}, r.text
    with system_tx() as s:
        tenant = s.execute(select(Tenant).where(Tenant.code == CODE)).scalar_one()
        assert tenant.kind == "BUYER" and tenant.status == "ACTIVE" and tenant.mfa_enforce is True
        reg = s.get(OrgRegistration, reg_id)
        assert reg.status == "APPROVED" and reg.tenant_id == tenant.id and reg.decided_by == OPERATOR
        tenant_id = tenant.id
    with tenant_tx(tenant_id) as s:
        admin = s.execute(select(AppUser).where(AppUser.email == f"asha.rao@{_d('approve')}")).scalar_one()
        assert admin.roles == ["TENANT_ADMIN"] and admin.activation_pending is True
    assert any(m["to"] == f"asha.rao@{_d('approve')}" and "/pic/activate?token=" in m["text"] for m in outbox)
    assert any(m["to"] == f"purchase@{_d('approve')}" and CODE in m["text"] for m in outbox)
    with tenant_tx(registration.ensure_platform()) as s:
        assert s.execute(select(AuditEvent).where(AuditEvent.object_type == "ORG_REGISTRATION", AuditEvent.action == "APPROVED")).first()
    again = client.post(f"/v1/platform/registrations/{reg_id}/approve", json={}, headers=operator)
    assert again.status_code == 409


def test_rejection_needs_a_reason_and_tells_the_company(client, outbox, operator):
    reg_id = _confirmed(client, outbox, _d("reject"))
    short = client.post(f"/v1/platform/registrations/{reg_id}/reject", json={"reason": "No"}, headers=operator)
    assert short.status_code == 422
    r = client.post(f"/v1/platform/registrations/{reg_id}/reject", json={"reason": "The company could not be verified with the GST portal."},
                    headers=operator)
    assert r.status_code == 200 and r.json()["status"] == "REJECTED"
    assert any(m["to"] == f"purchase@{_d('reject')}" and "could not be verified" in m["text"] for m in outbox)
    with system_tx() as s:
        reg = s.get(OrgRegistration, reg_id)
        assert reg.status == "REJECTED" and reg.tenant_id is None and reg.organisation_code is None
