"""M13 enterprise administration: organisation masters, user lifecycle, custom roles, template packs, tenant provisioning tool.
Runs in tenants of its own (ADMT1, ADMT2); the AXN signature tenant is not touched."""
import argparse
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, text

from app.pic.db import system_tx, tenant_tx
from app.pic.models import AppUser, AuditEvent, PurchasingOrg, RoleDef, RuleSet, TemplateApplication, UserToken
from app.pic.platform import clock
from app.pic.platform.auth import hash_password
from app.pic.seed import reference
from tests.pic.conftest import PASSWORD

T1, T2 = "ADMT1", "ADMT2"
NEW_PASSWORD = "Gx7#kQm2-Lp9vTz!"


def _tenant(code: str, name: str, template: str = "GENERAL") -> uuid.UUID:
    tid = reference.create_tenant(code, name, template, mfa_enforce=False)
    reference.bootstrap(tid, company=("1000", name, "27AAAAA0000A1Z2"), plants=[("P100", "Plant 100", "27")], cost_objects=[("COST_CENTER", "7100", "CC 7100")])
    with tenant_tx(tid) as s:
        for local, roles in (("admin", ["TENANT_ADMIN"]), ("buyer", ["BUYER"]), ("fc", ["FINANCE_CONTROLLER"]), ("receiver", ["RECEIVER"])):
            s.add(AppUser(tenant_id=tid, email=f"{local}@{code.lower()}.example", full_name=local.upper(), password_hash=hash_password(PASSWORD),
                          roles=roles, attributes={}))
    return tid


@pytest.fixture(scope="module")
def tenants():
    return {T1: _tenant(T1, "Admin Test One Pvt Ltd"), T2: _tenant(T2, "Admin Test Two Pvt Ltd")}


@pytest.fixture(scope="module")
def admin(login, tenants):
    return login(f"admin@{T1.lower()}.example", T1)


def _mail(local: str, tenant: str = T1) -> str:
    return f"{local}@{tenant.lower()}.example"


def _token_of(url: str) -> str:
    return url.split("token=", 1)[1].replace("%2E", ".")


def _new_user(client, admin, local: str, roles, **extra) -> dict:
    r = client.post("/v1/admin/users", json={"email": _mail(local), "name": local.title() + " User", "roles": roles, **extra}, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


def _activate(client, invited: dict, password: str = NEW_PASSWORD) -> None:
    token = _token_of(invited["activationUrl"])
    r = client.post(f"/v1/public/user-tokens/{token}/complete", json={"password": password})
    assert r.status_code == 200, r.text


def _login(client, email: str, tenant: str = T1, password: str = NEW_PASSWORD) -> dict:
    r = client.post("/v1/auth/token", json={"tenant": tenant, "email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------------------------------------------------------------- ADM-01 organisation
def test_organisation_crud_validation_and_audit(client, admin):
    bad = client.post("/v1/admin/org/company-codes", json={"code": "ab c", "name": "x", "gstin": "27AAAAA0000A1Z0"}, headers=admin)
    assert bad.status_code == 422 and bad.json()["code"] == "VALIDATION_FAILED" and len(bad.json()["errors"]) >= 2
    r = client.post("/v1/admin/org/company-codes", json={"code": "2000", "name": "Second Entity Ltd", "gstin": "27AAAAA0000A1Z2", "currency": "INR"},
                    headers=admin, )
    assert r.status_code == 201, r.text
    cc = r.json()
    assert cc["active"] and cc["version"] == 1 and r.headers["ETag"] == '"1"'
    assert client.post("/v1/admin/org/company-codes", json={"code": "2000", "name": "Dup"}, headers=admin).json()["code"] == "CODE_EXISTS"
    # plant: state code, working days, company must exist
    assert client.post("/v1/admin/org/plants", json={"code": "P200", "name": "Plant 200", "company_code": "9999", "state_code": "27"},
                       headers=admin).status_code == 422
    assert client.post("/v1/admin/org/plants", json={"code": "P200", "name": "Plant 200", "company_code": "2000", "state_code": "99"},
                       headers=admin).status_code == 422
    plant = client.post("/v1/admin/org/plants", json={"code": "P200", "name": "Plant 200", "company_code": "2000", "state_code": "27",
                                                      "working_days": [0, 1, 2, 3, 4]}, headers=admin).json()
    sloc = client.post("/v1/admin/org/storage-locations", json={"plant": "P200", "code": "0001", "name": "Main store"}, headers=admin)
    assert sloc.status_code == 201
    co = client.post("/v1/admin/org/cost-objects", json={"type": "WBS", "code": "W-1.1", "company_code": "2000", "name": "Tower"}, headers=admin)
    assert co.status_code == 201 and co.json()["type"] == "WBS"
    assert client.post("/v1/admin/org/cost-objects", json={"type": "BOGUS", "code": "X1", "company_code": "2000", "name": "x"}, headers=admin).status_code == 422
    porg = client.post("/v1/admin/org/purchasing-orgs", json={"code": "PO10", "name": "Central purchasing", "company_code": "2000"}, headers=admin)
    assert porg.status_code == 201
    buyer_id = next(u["id"] for u in client.get("/v1/admin/users", headers=admin).json() if u["email"] == _mail("buyer"))
    grp = client.post("/v1/admin/org/purchasing-groups", json={"code": "G01", "name": "Raw materials", "purchasing_org": "PO10", "plant": "P200",
                                                              "buyer_user_ids": [buyer_id]}, headers=admin)
    assert grp.status_code == 201 and grp.json()["buyerUserIds"] == [buyer_id]
    assert client.post("/v1/admin/org/purchasing-groups", json={"code": "G02", "name": "x1", "purchasing_org": "NOPE"}, headers=admin).status_code == 422
    # holidays: source required, union semantics
    h = client.post(f"/v1/admin/org/plants/{plant['id']}/holidays", json={"dates": ["2027-01-26", "2027-08-15"], "source": "Gazette notification 2027"}, headers=admin)
    assert h.status_code == 200 and h.json()["added"] == ["2027-01-26", "2027-08-15"]
    again = client.post(f"/v1/admin/org/plants/{plant['id']}/holidays", json={"dates": ["2027-01-26"], "source": "Gazette notification 2027"}, headers=admin)
    assert again.json()["added"] == []
    # currencies
    assert client.post("/v1/admin/org/currencies", json={"code": "SGD", "name": "Singapore dollar", "decimals": 2}, headers=admin).status_code == 201
    # update: code is immutable, name changes, audited
    upd = client.put(f"/v1/admin/org/plants/{plant['id']}", json={"name": "Plant 200 Pune", "code": "ZZZ", "reason": "renamed"}, headers=admin)
    assert upd.status_code == 200 and upd.json()["name"] == "Plant 200 Pune" and upd.json()["code"] == "P200"
    listing = client.get("/v1/admin/organisation", headers=admin).json()
    assert {c["code"] for c in listing["companyCodes"]} >= {"1000", "2000"} and listing["purchasingGroups"][0]["code"] == "G01"
    with tenant_tx(system_tenant(T1)) as s:
        actions = {(e.object_type, e.action) for e in s.execute(select(AuditEvent)).scalars()}
    assert {("COMPANY_CODE", "CREATED"), ("PLANT", "CREATED"), ("PLANT", "UPDATED"), ("PLANT", "CALENDAR_UPDATED"), ("COST_OBJECT", "CREATED"),
            ("PURCHASING_ORG", "CREATED"), ("PURCHASING_GROUP", "CREATED"), ("STORAGE_LOCATION", "CREATED"), ("CURRENCY", "CREATED")} <= actions


def system_tenant(code: str) -> uuid.UUID:
    from app.pic.models import Tenant
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == code)).scalar_one()


def test_non_admin_can_read_but_not_write_organisation(client, login, tenants):
    buyer = login(_mail("buyer"), T1)
    assert client.get("/v1/admin/organisation", headers=buyer).status_code == 200
    assert client.get("/v1/admin/org/plants", headers=buyer).status_code == 200
    r = client.post("/v1/admin/org/plants", json={"code": "PX", "name": "x1", "company_code": "1000", "state_code": "27"}, headers=buyer)
    assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN"


def test_deactivate_instead_of_delete_when_referenced(client, admin):
    cc = client.post("/v1/admin/org/company-codes", json={"code": "3000", "name": "Third Entity", "currency": "INR"}, headers=admin).json()
    pl = client.post("/v1/admin/org/plants", json={"code": "P300", "name": "Plant 300", "company_code": "3000", "state_code": "27"}, headers=admin).json()
    # a company code with an active plant is referenced and has active children: refused, not deleted
    blocked = client.delete(f"/v1/admin/org/company-codes/{cc['id']}", headers=admin)
    assert blocked.status_code == 409 and blocked.json()["code"] == "HAS_ACTIVE_CHILDREN"
    # an unreferenced plant is really deleted ...
    spare = client.post("/v1/admin/org/plants", json={"code": "P301", "name": "Plant 301", "company_code": "3000", "state_code": "27"}, headers=admin).json()
    gone = client.delete(f"/v1/admin/org/plants/{spare['id']}", headers=admin).json()
    assert gone["outcome"] == "DELETED"
    # ... a referenced one (a storage location points at it) is deactivated once its children are
    sl = client.post("/v1/admin/org/storage-locations", json={"plant": "P300", "code": "S1", "name": "Store"}, headers=admin).json()
    assert client.delete(f"/v1/admin/org/plants/{pl['id']}", headers=admin).status_code == 409
    assert client.delete(f"/v1/admin/org/storage-locations/{sl['id']}", headers=admin).json()["outcome"] == "DELETED"
    result = client.delete(f"/v1/admin/org/plants/{pl['id']}?reason=closed", headers=admin).json()
    assert result["outcome"] == "DELETED"  # nothing refers to it any more
    # reference by a document-like table: a rule set scoped to the plant keeps it
    pl2 = client.post("/v1/admin/org/plants", json={"code": "P310", "name": "Plant 310", "company_code": "3000", "state_code": "27"}, headers=admin).json()
    with tenant_tx(system_tenant(T1)) as s:
        s.add(RuleSet(tenant_id=system_tenant(T1), key="BUDGET", version="plant-scope", plant="P310", effective_from=clock.today(),
                      body={"hardFor": [], "softFor": []}))
    outcome = client.delete(f"/v1/admin/org/plants/{pl2['id']}", headers=admin).json()
    assert outcome["outcome"] == "DEACTIVATED" and outcome["record"]["active"] is False
    # deactivated masters leave the lookups but stay in the organisation view; reactivation works
    org = client.get("/v1/admin/organisation", headers=admin).json()
    assert next(p for p in org["plants"] if p["code"] == "P310")["active"] is False
    assert client.post(f"/v1/admin/org/plants/{pl2['id']}/activate", json={}, headers=admin).json()["active"] is True
    # now the company code: plants P310 active -> still refused until deactivated
    client.post(f"/v1/admin/org/plants/{pl2['id']}/deactivate", json={"reason": "closing"}, headers=admin)
    final = client.delete(f"/v1/admin/org/company-codes/{cc['id']}", headers=admin).json()
    assert final["outcome"] == "DEACTIVATED"


def test_idempotency_and_etag(client, admin):
    body = {"code": "4000", "name": "Fourth Entity", "currency": "INR"}
    first = client.post("/v1/admin/org/company-codes", json=body, headers={**admin, "Idempotency-Key": "org-4000"})
    second = client.post("/v1/admin/org/company-codes", json=body, headers={**admin, "Idempotency-Key": "org-4000"})
    assert first.status_code == 201 and second.json()["id"] == first.json()["id"] and second.json().get("replayed") is True
    clash = client.post("/v1/admin/org/company-codes", json={**body, "name": "Different"}, headers={**admin, "Idempotency-Key": "org-4000"})
    assert clash.status_code == 422 and clash.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    rid = first.json()["id"]
    ok = client.put(f"/v1/admin/org/company-codes/{rid}", json={"name": "Fourth Entity Ltd"}, headers={**admin, "If-Match": '"1"'})
    assert ok.status_code == 200 and ok.headers["ETag"] == '"2"'
    stale = client.put(f"/v1/admin/org/company-codes/{rid}", json={"name": "Lost update"}, headers={**admin, "If-Match": '"1"'})
    assert stale.status_code == 412 and stale.json()["code"] == "STALE_WRITE"
    now = client.put(f"/v1/admin/org/company-codes/{rid}", json={"name": "Fourth Entity Private Ltd"}, headers={**admin, "If-Match": '"2"'})
    assert now.status_code == 200 and now.headers["ETag"] == '"3"'


# ---------------------------------------------------------------- user lifecycle
def test_invite_activation_token_is_single_use_and_not_stored(client, admin):
    invited = _new_user(client, admin, "asha", ["REQUESTER"], attributes={"plants": ["P100"], "value_limit_minor": 5000000})
    assert invited["status"] == "INVITED" and invited["attributes"]["value_limit_minor"] == 5000000
    token = _token_of(invited["activationUrl"])
    assert token == invited["token"] and token.startswith(f"{T1}.")
    # not signable in before activation
    assert client.post("/v1/auth/token", json={"tenant": T1, "email": _mail("asha"), "password": "anything-Else-1!"}).status_code == 401
    info = client.get(f"/v1/public/user-tokens/{token}")
    assert info.status_code == 200 and info.json()["purpose"] == "ACTIVATION" and info.json()["email"] == _mail("asha")
    weak = client.post(f"/v1/public/user-tokens/{token}/complete", json={"password": "password123"})
    assert weak.status_code == 422 and weak.json()["code"] == "WEAK_PASSWORD"
    done = client.post(f"/v1/public/user-tokens/{token}/complete", json={"password": NEW_PASSWORD})
    assert done.status_code == 200 and done.json()["activated"] is True
    again = client.post(f"/v1/public/user-tokens/{token}/complete", json={"password": "Another#Passw0rd-77"})
    assert again.status_code == 410 and again.json()["code"] == "LINK_USED"
    assert client.get(f"/v1/public/user-tokens/{token}").status_code == 410
    _login(client, _mail("asha"))
    # only the hash is stored; the clear token never reaches the audit trail
    with tenant_tx(system_tenant(T1)) as s:
        rows = s.execute(select(UserToken)).scalars().all()
        assert rows and all(token not in r.token_hash and len(r.token_hash) == 64 for r in rows)
        trail = " ".join(str(e.after) + str(e.before) + str(e.reason) for e in s.execute(select(AuditEvent)).scalars())
        assert token not in trail and token.split(".", 1)[1] not in trail
    # garbage and foreign-tenant tokens give the same answer
    assert client.get("/v1/public/user-tokens/NOPE.garbage").status_code == 404
    assert client.get(f"/v1/public/user-tokens/{T1}.{'a' * 43}").status_code == 404


def test_link_expiry_and_replacement(client, admin):
    invited = _new_user(client, admin, "bela", ["REQUESTER"])
    user_id = invited["id"]
    resent = client.post(f"/v1/admin/users/{user_id}/resend-invitation", headers=admin).json()
    old, new = _token_of(invited["activationUrl"]), _token_of(resent["activationUrl"])
    assert client.get(f"/v1/public/user-tokens/{old}").json()["code"] == "LINK_REVOKED"
    with tenant_tx(system_tenant(T1)) as s:
        row = s.execute(select(UserToken).where(UserToken.user_id == uuid.UUID(user_id), UserToken.revoked_at.is_(None))).scalar_one()
        row.expires_at = clock.now() - timedelta(minutes=1)
    expired = client.post(f"/v1/public/user-tokens/{new}/complete", json={"password": NEW_PASSWORD})
    assert expired.status_code == 410 and expired.json()["code"] == "LINK_EXPIRED"


def test_password_reset_and_session_revocation(client, admin):
    invited = _new_user(client, admin, "chitra", ["REQUESTER"])
    pending = client.post(f"/v1/admin/users/{invited['id']}/password-reset", json={"reason": "forgot password"}, headers=admin)
    assert pending.status_code == 409 and pending.json()["code"] == "ACTIVATION_PENDING"
    _activate(client, invited)
    h = _login(client, _mail("chitra"))
    assert client.get("/v1/me", headers=h).status_code == 200
    reset = client.post(f"/v1/admin/users/{invited['id']}/password-reset", json={"reason": "forgot password, ticket 22"}, headers=admin).json()
    assert reset["resetUrl"].startswith("http") and client.get("/v1/me", headers=h).status_code == 200  # issuing the link keeps the session
    new_password = "Rt5!pWx8-Nc3dLq"
    assert client.post(f"/v1/public/user-tokens/{_token_of(reset['resetUrl'])}/complete", json={"password": new_password}).status_code == 200
    old = client.get("/v1/me", headers=h)
    assert old.status_code == 401 and old.json()["code"] == "SESSION_REVOKED"  # using the link ended the old session
    h2 = _login(client, _mail("chitra"), password=new_password)
    assert client.post("/v1/auth/token", json={"tenant": T1, "email": _mail("chitra"), "password": NEW_PASSWORD}).status_code == 401
    revoked = client.post(f"/v1/admin/users/{invited['id']}/revoke-sessions", json={"reason": "laptop lost"}, headers=admin)
    assert revoked.status_code == 200
    assert client.get("/v1/me", headers=h2).status_code == 401
    _login(client, _mail("chitra"), password=new_password)  # signing in again works
    with tenant_tx(system_tenant(T1)) as s:
        actions = {e.action for e in s.execute(select(AuditEvent).where(AuditEvent.object_type == "APP_USER")).scalars()}
    assert {"USER_INVITED", "USER_ACTIVATED", "PASSWORD_RESET_REQUESTED", "PASSWORD_RESET_COMPLETED", "SESSIONS_REVOKED"} <= actions


def test_invite_refuses_sod_conflicts_and_bad_input(client, admin):
    r = client.post("/v1/admin/users", json={"email": _mail("dup"), "name": "Dup User", "roles": ["BUYER", "RECEIVER"]}, headers=admin)
    assert r.status_code == 409 and r.json()["code"] == "SOD_CONFLICT" and "SOD-03" in r.text  # same answer as role assignment (flow fixes)
    assert client.post("/v1/admin/users", json={"email": "not-an-email", "name": "X", "roles": ["BUYER"]}, headers=admin).status_code == 422
    assert client.post("/v1/admin/users", json={"email": _mail("q"), "name": "Q User", "roles": ["NO_SUCH_ROLE"]}, headers=admin).status_code == 422
    assert client.post("/v1/admin/users", json={"email": _mail("q"), "name": "Q User", "roles": ["BUYER"], "attributes": {"plants": ["ZZZ"]}},
                       headers=admin).status_code == 422
    assert client.post("/v1/admin/users", json={"email": _mail("buyer"), "name": "Again", "roles": ["BUYER"]}, headers=admin).status_code == 422
    assert client.post("/v1/admin/users", json={"email": _mail("s"), "name": "Sup User", "roles": ["SUPPLIER_USER"]}, headers=admin).status_code == 422


def test_bulk_import_dry_run_then_commit(client, admin):
    csv_text = ("email,name,roles,plants,company_codes,value_limit_minor\n"
                f"{_mail('imp1')},Import One,BUYER,P100,1000,1000000\n"
                f"{_mail('imp2')},Import Two,RECEIVER;REQUESTER,P100,,\n"
                f"{_mail('imp1')},Duplicate,BUYER,,,\n"
                "bad-address,Bad Row,BUYER,,,\n"
                f"{_mail('imp3')},Conflict Row,BUYER;RECEIVER,,,\n")
    dry = client.post("/v1/admin/users/import", json={"csv": csv_text, "dry_run": True}, headers=admin).json()
    assert dry["summary"]["rows"] == 5 and dry["summary"]["valid"] == 2 and dry["summary"]["errors"] == 3 and dry["summary"]["created"] == 0
    assert [x["status"] for x in dry["report"]] == ["OK", "OK", "ERROR", "ERROR", "ERROR"]
    refused = client.post("/v1/admin/users/import", json={"csv": csv_text, "dry_run": False}, headers=admin).json()
    assert refused["summary"]["created"] == 0  # all-or-nothing
    good = ("email,name,roles,plants\n" f"{_mail('imp1')},Import One,BUYER,P100\n" f"{_mail('imp2')},Import Two,RECEIVER,P100\n")
    done = client.post("/v1/admin/users/import", json={"csv": good, "dry_run": False}, headers=admin).json()
    assert done["summary"]["created"] == 2 and all(u["activationUrl"] for u in done["users"])
    assert client.post("/v1/admin/users/import", json={"csv": "colA,colB,colC\n1,2,3\n", "dry_run": True}, headers=admin).json()["code"] == "CSV_COLUMNS"


# ---------------------------------------------------------------- custom roles
def test_custom_role_lifecycle_and_effective_scopes(client, admin):
    r = client.post("/v1/admin/roles", json={"code": "PO_DESK", "name": "PO desk", "scopes": ["pic:read", "tasks:work", "po:create"]}, headers=admin)
    assert r.status_code == 201, r.text
    role = r.json()
    assert client.post("/v1/admin/roles", json={"code": "BUYER", "name": "Mine", "scopes": ["pic:read"]}, headers=admin).status_code == 422  # built-in
    platform = client.post("/v1/admin/roles", json={"code": "SUPER", "name": "Super", "scopes": ["pic:read", "admin:rules"]}, headers=admin)
    assert platform.status_code == 422 and platform.json()["code"] == "SCOPE_NOT_ASSIGNABLE"
    assert client.post("/v1/admin/roles", json={"code": "SUPP", "name": "Supp", "scopes": ["supplier:portal"]}, headers=admin).status_code == 422
    matrix = client.get("/v1/admin/roles/matrix", headers=admin).json()
    codes = {x["code"]: x for x in matrix["roles"]}
    assert codes["BUYER"]["kind"] == "BUILT_IN" and codes["PO_DESK"]["kind"] == "CUSTOM" and matrix["sodPairs"]
    assert next(s for s in matrix["scopes"] if s["scope"] == "admin:rules")["assignable"] is False
    # built-in roles are read-only through the API
    assert client.put(f"/v1/admin/roles/{uuid.uuid4()}", json={"name": "x1"}, headers=admin).status_code == 404
    # assign to a new user: the token carries the custom scopes, and only the catalogue ones
    invited = _new_user(client, admin, "dora", ["PO_DESK"])
    _activate(client, invited)
    h = _login(client, _mail("dora"))
    me = client.get("/v1/me", headers=h).json()
    assert "po:create" in me["scopes"] and "admin:rules" not in me["scopes"] and me["roles"] == ["PO_DESK"]
    assert client.get("/v1/admin/users", headers=h).status_code == 403
    # extend the role: holders are signed out so the new scopes apply, and the change is audited
    upd = client.put(f"/v1/admin/roles/{role['id']}", json={"scopes": ["pic:read", "tasks:work", "po:create", "po:release"], "reason": "release rights"},
                     headers={**admin, "If-Match": f'"{role["version"]}"'})
    assert upd.status_code == 200 and "po:release" in upd.json()["scopes"]
    assert client.get("/v1/me", headers=h).status_code == 401
    me2 = client.get("/v1/me", headers=_login(client, _mail("dora"))).json()
    assert "po:release" in me2["scopes"]
    stale = client.put(f"/v1/admin/roles/{role['id']}", json={"name": "PO desk 2"}, headers={**admin, "If-Match": f'"{role["version"]}"'})
    assert stale.status_code == 412
    # a role with holders is deactivated, not deleted; its holders lose its scopes
    out = client.delete(f"/v1/admin/roles/{role['id']}", headers=admin).json()
    assert out["outcome"] == "DEACTIVATED"
    assert "po:create" not in client.get("/v1/me", headers=_login(client, _mail("dora"))).json()["scopes"]
    unused = client.post("/v1/admin/roles", json={"code": "TEMP_ROLE", "name": "Temp", "scopes": ["pic:read"]}, headers=admin).json()
    assert client.delete(f"/v1/admin/roles/{unused['id']}", headers=admin).json()["outcome"] == "DELETED"


def test_custom_role_sod_refusals(client, admin):
    own = client.post("/v1/admin/roles", json={"code": "PO_AND_GR", "name": "Both", "scopes": ["pic:read", "po:create", "gr:post"]}, headers=admin)
    assert own.status_code == 409 and own.json()["code"] == "SOD_CONFLICT" and own.json()["impact"]["ownConflicts"][0]["rule"] == "SOD-03"
    prev = client.post("/v1/admin/roles/preview", json={"code": "BANK_PAY", "scopes": ["supplier:bank", "payment:run"]}, headers=admin).json()
    assert prev["allowed"] is False and prev["ownConflicts"][0]["rule"] == "SOD-02"
    ok = client.post("/v1/admin/roles/preview", json={"code": "BANK_ONLY", "scopes": ["supplier:bank"]}, headers=admin).json()
    assert ok["allowed"] is True and ok["added"] == ["supplier:bank"]
    # a holder-level conflict: the user holds a role with gr:post, the other role must not gain po:create
    recv = client.post("/v1/admin/roles", json={"code": "GR_DESK", "name": "GR desk", "scopes": ["pic:read", "gr:post"]}, headers=admin).json()
    base = client.post("/v1/admin/roles", json={"code": "BASE_USER", "name": "Base", "scopes": ["pic:read", "tasks:work"]}, headers=admin).json()
    inv = _new_user(client, admin, "emil", ["GR_DESK", "BASE_USER"])
    assert inv["roles"] == ["BASE_USER", "GR_DESK"]
    risky = client.put(f"/v1/admin/roles/{base['id']}", json={"scopes": ["pic:read", "po:create"]}, headers=admin)
    assert risky.status_code == 409 and risky.json()["code"] == "SOD_CONFLICT"
    assert "emil" in risky.json()["detail"] and risky.json()["impact"]["affectedUsers"][0]["newConflicts"][0]["rule"] == "SOD-03"
    # assignment: the same pair across a built-in and a custom role is refused too
    po = client.post("/v1/admin/roles", json={"code": "PO_ONLY", "name": "PO", "scopes": ["pic:read", "po:create"]}, headers=admin).json()
    uid = next(u["id"] for u in client.get("/v1/admin/users", headers=admin).json() if u["email"] == _mail("receiver"))
    refused = client.put(f"/v1/admin/users/{uid}/roles", json={"roles": ["RECEIVER", "PO_ONLY"], "reason": "test conflict"}, headers=admin)
    assert refused.status_code == 409 and refused.json()["code"] == "SOD_CONFLICT"
    assert recv["code"] == "GR_DESK" and po["scopes"] == ["pic:read", "po:create"]


# ---------------------------------------------------------------- templates
def test_template_preview_and_idempotent_apply(client, admin):
    cur = client.get("/v1/admin/templates", headers=admin).json()["current"]
    assert cur == "GENERAL"
    prev = client.get("/v1/admin/templates/MANUFACTURING/preview", headers=admin).json()
    assert prev["switchesTemplate"] is True and prev["willAdd"] + prev["willChange"] >= 1
    keys = {c["key"]: c for c in prev["ruleSetChanges"]}
    assert "SELF-BILLING" in keys and keys["SELF-BILLING"]["action"] == "ADD"
    assert next(c for c in prev["ruleSetChanges"] if c["key"] == "PURCHASE-TYPE-MATRIX")["action"] == "REVERT"
    first = client.post("/v1/admin/templates/MANUFACTURING/apply", headers={**admin, "Idempotency-Key": "tpl-1"})
    assert first.status_code == 200 and first.json()["applied"] is True
    keys_applied = {c["key"] for c in first.json()["ruleSetChanges"]}
    assert "SELF-BILLING" in keys_applied
    second = client.post("/v1/admin/templates/MANUFACTURING/apply", headers=admin).json()
    assert second["applied"] is False and second["noop"] is True
    replay = client.post("/v1/admin/templates/MANUFACTURING/apply", headers={**admin, "Idempotency-Key": "tpl-1"}).json()
    assert replay["applied"] is True and replay["replayed"] is True
    with tenant_tx(system_tenant(T1)) as s:
        assert s.execute(select(text("count(*)")).select_from(TemplateApplication)).scalar() == 1
        app_row = s.execute(select(TemplateApplication)).scalar_one()
        assert app_row.template == "MANUFACTURING" and app_row.previous_template == "GENERAL" and app_row.applied_by is not None
        versions = s.execute(select(RuleSet.version).where(RuleSet.key == "PURCHASE-TYPE-MATRIX")).scalars().all()
        assert len(versions) == 2  # the original version is kept; the revert is a new one
    assert client.get("/v1/admin/templates", headers=admin).json()["current"] == "MANUFACTURING"
    assert client.get("/v1/admin/templates/NOPE/preview", headers=admin).status_code == 404


# ---------------------------------------------------------------- isolation and provisioning
def test_row_level_security_isolates_new_tables(client, admin, login, tenants):
    client.post("/v1/admin/org/purchasing-orgs", json={"code": "ISO1", "name": "Isolated org", "company_code": "1000"}, headers=admin)
    other = login(_mail("admin", T2), T2)
    assert [o for o in client.get("/v1/admin/org/purchasing-orgs", headers=other).json() if o["code"] == "ISO1"] == []
    mine = next(o for o in client.get("/v1/admin/org/purchasing-orgs", headers=admin).json() if o["code"] == "ISO1")
    assert client.put(f"/v1/admin/org/purchasing-orgs/{mine['id']}", json={"name": "Hijack"}, headers=other).status_code == 404
    assert client.delete(f"/v1/admin/org/purchasing-orgs/{mine['id']}", headers=other).status_code == 404
    role = client.post("/v1/admin/roles", json={"code": "ISO_ROLE", "name": "Iso role", "scopes": ["pic:read"]}, headers=admin).json()
    assert [r for r in client.get("/v1/admin/roles/matrix", headers=other).json()["roles"] if r["code"] == "ISO_ROLE"] == []
    assert client.put(f"/v1/admin/roles/{role['id']}", json={"name": "Hijack"}, headers=other).status_code == 404
    # at the database level: tenant two sees none of tenant one's rows in any new table
    with tenant_tx(tenants[T2]) as s:
        for model in (PurchasingOrg, RoleDef, UserToken, TemplateApplication):
            assert s.execute(select(model)).scalars().all() == [], model.__name__
    with tenant_tx(tenants[T1]) as s:
        assert len(s.execute(select(PurchasingOrg)).scalars().all()) >= 1


def test_tenant_admin_tool_provisions_a_tenant(client):
    from app.pic.tools import tenant_admin
    args = argparse.Namespace(code="PROV1", name="Provisioned Industries Ltd", template="CONSTRUCTION", admin_email="owner@prov1.example", admin_name="Olga Owner",
                              company_code="5000", company_name=None, gstin="27AAAAA0000A1Z2", plant="P500", plant_name="Site 500", state_code="27")
    result = tenant_admin.create(args)
    assert result["tenant"] == "PROV1" and "token=PROV1." in result["activationUrl"]
    with pytest.raises(tenant_admin.ToolError):
        tenant_admin.create(args)  # nothing is provisioned twice
    tid = system_tenant("PROV1")
    with tenant_tx(tid) as s:
        from app.pic.models import CompanyCode, Plant, Tenant
        assert s.get(Tenant, tid).mfa_enforce is True and s.get(Tenant, tid).industry_template == "CONSTRUCTION"
        assert s.execute(select(CompanyCode.code)).scalars().all() == ["5000"] and s.execute(select(Plant.code)).scalars().all() == ["P500"]
        mfa = s.execute(select(RuleSet).where(RuleSet.key == "MFA")).scalar_one()
        assert mfa.body["enforce"] is True
        assert s.execute(select(RuleSet).where(RuleSet.key == "ADVANCE-PAYMENT")).scalar_one().body["enabled"] is True  # template rule
        admin_row = s.execute(select(AppUser)).scalar_one()
        assert admin_row.roles == ["TENANT_ADMIN"] and admin_row.activation_pending is True
        events = {e.action for e in s.execute(select(AuditEvent)).scalars()}
        assert {"USER_INVITED", "PROVISIONED"} <= events
    token = _token_of(result["activationUrl"])
    assert client.post(f"/v1/public/user-tokens/{token}/complete", json={"password": NEW_PASSWORD}).status_code == 200
    # a not-yet-activated administrator can get a fresh link; an activated one cannot
    with pytest.raises(tenant_admin.ToolError):
        tenant_admin.reissue(argparse.Namespace(code="PROV1", admin_email="owner@prov1.example"))
    # administrators sign in only after MFA enrolment (MFA is on by default)
    denied = client.post("/v1/auth/token", json={"tenant": "PROV1", "email": "owner@prov1.example", "password": NEW_PASSWORD})
    assert denied.status_code == 403 and denied.json()["code"] == "MFA_ENROLMENT_REQUIRED"
    bad = argparse.Namespace(**{**vars(args), "code": "bad code", "template": "NOPE"})
    with pytest.raises(tenant_admin.ToolError):
        tenant_admin.create(bad)
    # the tool is not on the web API
    assert not [r.path for r in client.app.routes if hasattr(r, "path") and r.path.rstrip("/").endswith(("/tenants", "/admin/tenants"))]
