"""One platform, one sign-in (migration 0029, services/signin.py): sign-in by e-mail without an organisation code, the organisation choice
for a person in several organisations, switching organisations, organisation status, the sign-in directory kept by the database trigger,
and single sign-on found from the e-mail domain."""
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app.pic.db import system_tx, tenant_tx
from app.pic.models import AppUser, LoginDirectory, Tenant
from app.pic.platform.auth import hash_password
from app.pic.seed import reference
from tests.pic.conftest import PASSWORD

EMAIL = "multi.org@signin.example"
OTHER_PASSWORD = "Another-Password-77"


def _tenant(code: str, name: str, status: str = "ACTIVE") -> uuid.UUID:
    tenant_id = reference.create_tenant(code, name, "MANUFACTURING", mfa_enforce=False)
    reference.bootstrap(tenant_id, company=("4000", name, "29AAACS1234C1Z5"), plants=[("S100", "Hosur", "33")],
                        cost_objects=[("COST_CENTER", "9400", "Admin")])
    with system_tx() as s:
        s.get(Tenant, tenant_id).status = status
    return tenant_id


def _user(tenant_id: uuid.UUID, email: str, password: str, roles=("REQUESTER",)) -> uuid.UUID:
    with tenant_tx(tenant_id) as s:
        user = s.execute(select(AppUser).where(AppUser.email == email)).scalar_one_or_none()
        if user is None:
            user = AppUser(tenant_id=tenant_id, email=email, full_name="Multi Org", password_hash=hash_password(password), roles=list(roles),
                           attributes={})
            s.add(user)
            s.flush()
        return user.id


@pytest.fixture(scope="module")
def organisations():
    with system_tx() as s:
        axn = s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()
    sg1 = _tenant("SGNA", "Signin Alpha Pvt Ltd")
    sg2 = _tenant("SGNB", "Signin Beta Pvt Ltd")
    sg3 = _tenant("SGNC", "Signin Pending Pvt Ltd", status="PENDING_APPROVAL")
    _user(axn, EMAIL, PASSWORD)
    _user(sg1, EMAIL, PASSWORD)
    _user(sg2, EMAIL, OTHER_PASSWORD)   # same e-mail, another password: not proved by PASSWORD
    _user(sg3, EMAIL, PASSWORD)          # organisation not ACTIVE: never offered
    return {"AXN": axn, "SGNA": sg1, "SGNB": sg2, "SGNC": sg3}


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_directory_follows_every_change_of_app_user(organisations):
    tenant_id = organisations["SGNA"]
    user_id = _user(tenant_id, "Directory.Probe@Signin.Example", PASSWORD)
    with system_tx() as s:
        row = s.get(LoginDirectory, (tenant_id, user_id))
        assert row is not None and row.email == "directory.probe@signin.example" and row.active is True
    with tenant_tx(tenant_id) as s:
        user = s.get(AppUser, user_id)
        user.email, user.active = "renamed.probe@signin.example", False
    with system_tx() as s:
        row = s.get(LoginDirectory, (tenant_id, user_id))
        assert row.email == "renamed.probe@signin.example" and row.active is False
    with tenant_tx(tenant_id) as s:
        s.delete(s.get(AppUser, user_id))
    with system_tx() as s:
        assert s.get(LoginDirectory, (tenant_id, user_id)) is None


def test_application_role_cannot_read_the_directory(organisations):
    with pytest.raises(ProgrammingError) as error:
        with tenant_tx(organisations["AXN"]) as s:
            s.execute(text("SELECT count(*) FROM pic.login_directory")).scalar()
    assert "permission denied" in str(error.value).lower()


def test_existing_users_were_backfilled_into_the_directory(organisations):
    with system_tx() as s:
        axn_rows = s.execute(select(LoginDirectory.email).where(LoginDirectory.org_id == organisations["AXN"])).scalars().all()
    assert "buyer@axion.example" in axn_rows and "admin@axion.example" in axn_rows


def test_one_organisation_signs_in_without_a_code(client, organisations):
    _user(organisations["AXN"], "solo@signin.example", PASSWORD)  # own user: no other test registers an authenticator for it
    r = client.post("/v1/auth/token", json={"email": " Solo@Signin.Example ", "password": PASSWORD})
    assert r.status_code == 200, r.text
    assert r.json()["tenant"] == "AXN" and r.json()["access_token"]
    me = client.get("/v1/me", headers=_bearer(r.json()["access_token"])).json()
    assert me["tenant"] == "AXN" and me["tenantName"] and me["tenantKind"] == "BUYER"
    assert [o["code"] for o in me["organisations"]] == ["AXN"] and me["organisations"][0]["current"] is True


def test_unknown_email_and_wrong_password_give_the_same_answer(client, organisations):
    unknown = client.post("/v1/auth/token", json={"email": "nobody@nowhere.example", "password": PASSWORD})
    wrong = client.post("/v1/auth/token", json={"email": EMAIL, "password": "Wrong-Password-1"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["code"] == wrong.json()["code"] == "INVALID_CREDENTIALS"
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_several_organisations_ask_which_one_then_switch(client, organisations):
    r = client.post("/v1/auth/token", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["organisationChoice"] is True and "access_token" not in body
    offered = {o["code"] for o in body["organisations"]}
    assert offered == {"AXN", "SGNA"}            # SGNB: other password; SGNC: not active
    assert all(o["kind"] == "BUYER" and o["name"] for o in body["organisations"])

    bad = client.post("/v1/auth/organisation", json={"challenge": body["challenge"], "organisation": "SGNB"})
    assert bad.status_code == 403 and bad.json()["code"] == "ORGANISATION_NOT_AVAILABLE"
    chosen = client.post("/v1/auth/organisation", json={"challenge": body["challenge"], "organisation": "sgna"})
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["tenant"] == "SGNA"
    token = chosen.json()["access_token"]
    me = client.get("/v1/me", headers=_bearer(token)).json()
    assert me["tenant"] == "SGNA" and {o["code"] for o in me["organisations"]} == {"AXN", "SGNA"}

    switched = client.post("/v1/auth/switch", json={"organisation": "AXN"}, headers=_bearer(token))
    assert switched.status_code == 200, switched.text
    assert client.get("/v1/me", headers=_bearer(switched.json()["access_token"])).json()["tenant"] == "AXN"
    for code in ("SGNB", "SGNC", "ZZZZ"):
        refused = client.post("/v1/auth/switch", json={"organisation": code}, headers=_bearer(token))
        assert refused.status_code == 403 and refused.json()["code"] == "ORGANISATION_NOT_AVAILABLE"


def test_forged_or_expired_choice_is_refused(client, organisations):
    r = client.post("/v1/auth/organisation", json={"challenge": "not-a-challenge", "organisation": "AXN"})
    assert r.status_code == 401 and r.json()["code"] == "ORGANISATION_CHOICE_INVALID"


def test_the_other_password_proves_only_its_own_organisation(client, organisations):
    r = client.post("/v1/auth/token", json={"email": EMAIL, "password": OTHER_PASSWORD})
    assert r.status_code == 200 and r.json()["tenant"] == "SGNB"
    me = client.get("/v1/me", headers=_bearer(r.json()["access_token"])).json()
    assert [o["code"] for o in me["organisations"]] == ["SGNB"]
    refused = client.post("/v1/auth/switch", json={"organisation": "AXN"}, headers=_bearer(r.json()["access_token"]))
    assert refused.status_code == 403


def test_sign_in_with_a_code_is_refused_for_an_organisation_that_is_not_active(client, organisations):
    r = client.post("/v1/auth/token", json={"tenant": "SGNC", "email": EMAIL, "password": PASSWORD})
    assert r.status_code == 401 and r.json()["code"] == "INVALID_CREDENTIALS"
    ok = client.post("/v1/auth/token", json={"tenant": "SGNA", "email": EMAIL, "password": PASSWORD})
    assert ok.status_code == 200
    # a sign-in with an organisation code proves only that organisation: nothing to switch to
    me = client.get("/v1/me", headers=_bearer(ok.json()["access_token"])).json()
    assert [o["code"] for o in me["organisations"]] == ["SGNA"]


def test_single_sign_on_is_found_from_the_email_domain(client, monkeypatch):
    monkeypatch.setenv("PIC_OIDC_AXN_EMAIL_DOMAINS", "axion.example, axion-mobility.example")
    monkeypatch.setenv("PIC_OIDC_AXN_ISSUER", "https://idp.example/realms/axion")
    monkeypatch.setenv("PIC_OIDC_AXN_CLIENT_ID", "pic")
    monkeypatch.setenv("PIC_OIDC_AXN_REDIRECT_URI", "https://pic.example/api/auth/oidc/callback")
    found = client.get("/v1/auth/sso", params={"email": "someone@Axion-Mobility.example"}).json()
    assert found == {"enabled": True, "tenant": "AXN"}
    assert client.get("/v1/auth/sso", params={"email": "someone@elsewhere.example"}).json() == {"enabled": False, "tenant": None}
    assert client.get("/v1/auth/sso", params={"email": "not-an-email"}).json() == {"enabled": False, "tenant": None}
