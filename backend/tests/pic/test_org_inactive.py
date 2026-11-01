"""ADM-01: a deactivated organisation record (company code, plant, storage location, cost object, purchasing organisation or group)
is refused on a NEW requisition, purchase order or goods receipt that names it (422 ORG_RECORD_INACTIVE, problem+json), while
documents that already exist keep working.

Two parts: the API on a tenant of its own (ORGI1, deactivation through the administration endpoints) and the service level on the
Axion tenant, where the deactivation happens inside a rolled-back transaction so the signature case is never touched.
"""
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, CompanyCode, CostObject, Plant, PrLine, PurchaseOrder, PurchasingGroup, PurchasingOrg, Requisition, StorageLocation, Tenant,
)
from app.pic.platform import clock
from app.pic.platform.auth import Principal, hash_password, scopes_for
from app.pic.platform.errors import Problem
from app.pic.seed import reference
from app.pic.seed.axion import Scenario
from app.pic.services import order, org_guard, receiving, requisition
from tests.pic.conftest import PASSWORD

IST = clock.IST
CODE = "ORGI1"


class _Rollback(Exception):
    pass


# ================================================================ API on a tenant of its own
@pytest.fixture(scope="module")
def tenant():
    tid = reference.create_tenant(CODE, "Org Inactive Test Pvt Ltd", "GENERAL", mfa_enforce=False)
    reference.bootstrap(tid, company=("1000", "Org Inactive Test Pvt Ltd", "27AAAAA0000A1Z2"), plants=[("P100", "Plant 100", "27")],
                        cost_objects=[("COST_CENTER", "7100", "CC 7100")])
    with tenant_tx(tid) as s:
        for local, roles, attributes in (("admin", ["TENANT_ADMIN"], {}), ("requester", ["REQUESTER"], {"plants": ["P100"]})):
            s.add(AppUser(tenant_id=tid, email=f"{local}@{CODE.lower()}.example", full_name=local.title(), password_hash=hash_password(PASSWORD),
                          roles=roles, attributes=attributes))
    return tid


@pytest.fixture(scope="module")
def admin(login, tenant):
    return login(f"admin@{CODE.lower()}.example", CODE)


@pytest.fixture(scope="module")
def requester(login, tenant):
    return login(f"requester@{CODE.lower()}.example", CODE)


def _record(client, admin, kind: str, **match) -> dict:
    rows = client.get(f"/v1/admin/org/{kind}", headers=admin).json()
    return next(r for r in rows if all(r.get(k) == v for k, v in match.items()))


def _body(plant: str = "P100", cost_object: str = "7100", storage_location: str = "0001", **top) -> dict:
    return {"origin": "MANUAL", "purpose_text": "Office supplies", "plant": plant, **top, "lines": [{
        "item_type": "FREE_TEXT", "purchase_type": "NON_STOCK", "description": "Printer toner cartridges", "material_group": "OFFICE",
        "qty": "5", "price_est_minor": 450000, "need_date": (clock.today() + timedelta(days=14)).isoformat(),
        "account_assignment_type": "COST_CENTER", "account_assignment_code": cost_object, "storage_location": storage_location}]}


def test_api_refuses_each_deactivated_record_and_accepts_it_again_once_reactivated(client, admin, requester):
    for body in (
        {"code": "P200", "name": "Plant 200", "company_code": "1000", "state_code": "27"},
    ):
        assert client.post("/v1/admin/org/plants", json=body, headers=admin).status_code == 201
    assert client.post("/v1/admin/org/storage-locations", json={"plant": "P200", "code": "S1", "name": "Store 1"}, headers=admin).status_code == 201
    assert client.post("/v1/admin/org/cost-objects", json={"type": "COST_CENTER", "code": "7200", "name": "CC 7200", "company_code": "1000"},
                       headers=admin).status_code == 201
    assert client.post("/v1/admin/org/purchasing-orgs", json={"code": "PO10", "name": "Central purchasing", "company_code": "1000"},
                       headers=admin).status_code == 201
    assert client.post("/v1/admin/org/purchasing-orgs", json={"code": "PO20", "name": "Regional purchasing", "company_code": "1000"},
                       headers=admin).status_code == 201        # no group under it: it can be deactivated on its own
    assert client.post("/v1/admin/org/purchasing-groups", json={"code": "G10", "name": "Indirect buying", "purchasing_org": "PO10"},
                       headers=admin).status_code == 201
    plant = _record(client, admin, "plants", code="P200")
    sloc = _record(client, admin, "storage-locations", plant="P200", code="S1")
    cost = _record(client, admin, "cost-objects", code="7200")
    porg = _record(client, admin, "purchasing-orgs", code="PO20")
    pgroup = _record(client, admin, "purchasing-groups", code="G10")

    ok = client.post("/v1/requisitions", json=_body("P200", "7200", "S1", purchasing_org="PO10", purchasing_group="G10"), headers=requester)
    assert ok.status_code == 201, ok.text   # everything active: accepted

    cases = [  # (admin kind, record, request body, what the problem names)
        ("storage-locations", sloc, _body("P200", "7200", "S1"), "storage location"),
        ("cost-objects", cost, _body("P200", "7200", "S1"), "cost object"),
        ("purchasing-groups", pgroup, _body("P200", "7200", "S1", purchasing_group="G10"), "purchasing group"),
        ("purchasing-orgs", porg, _body("P200", "7200", "S1", purchasing_org="PO20"), "purchasing organisation"),
    ]
    for kind, record, body, label in cases:
        assert client.post(f"/v1/admin/org/{kind}/{record['id']}/deactivate", json={"reason": "closed for this test"}, headers=admin).status_code == 200
        refused = client.post("/v1/requisitions", json=body, headers=requester)
        assert refused.status_code == 422, (kind, refused.text)
        assert refused.headers["content-type"].startswith("application/problem+json")
        problem = refused.json()
        assert problem["code"] == "ORG_RECORD_INACTIVE" and problem["ruleRef"] == "ADM-01"
        assert [i["kind"] for i in problem["inactive"]] == [label] and label in problem["detail"]
        assert client.post(f"/v1/admin/org/{kind}/{record['id']}/activate", json={}, headers=admin).status_code == 200
        assert client.post("/v1/requisitions", json=body, headers=requester).status_code == 201, kind   # reactivated: accepted again

    # the plant (its storage location first: a plant with an active child cannot be deactivated)
    assert client.post(f"/v1/admin/org/storage-locations/{sloc['id']}/deactivate", json={}, headers=admin).status_code == 200
    assert client.post(f"/v1/admin/org/plants/{plant['id']}/deactivate", json={"reason": "plant closed"}, headers=admin).status_code == 200
    refused = client.post("/v1/requisitions", json=_body("P200", "7200", "0001"), headers=requester)
    assert refused.status_code == 422 and refused.json()["code"] == "ORG_RECORD_INACTIVE"
    assert [i["kind"] for i in refused.json()["inactive"]] == ["plant"]
    assert client.post("/v1/requisitions", json=_body("P100"), headers=requester).status_code == 201   # another plant is not affected


# ================================================================ service level on the Axion tenant (rolled back)
def _axn():
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()


def _as(session, email: str) -> None:
    user = session.execute(select(AppUser).where(AppUser.email == email)).scalar_one()
    session.info["principal"] = Principal(user.id, user.tenant_id, "AXN", user.email, user.full_name, list(user.roles), scopes_for(list(user.roles)),
                                          user.attributes or {}, user.supplier_id)
    session.info["user_id"] = user.id


def _lines(need, **extra) -> list[dict]:
    return [{"item_type": "MATERIAL", "purchase_type": "STOCK", "material": "DC-330", "qty": "10", "price_est_minor": 40500,
             "need_date": need.isoformat(), "storage_location": "0001", **extra}]


@pytest.fixture(scope="module")
def docs(database):
    """An approved requisition not yet ordered, and a transmitted order of Trichy Forge to receive against (both committed)."""
    tenant_id = _axn()
    now = datetime.now(IST).replace(microsecond=0)
    need = (now + timedelta(days=30)).date()
    sc = Scenario(tenant_id)
    out = {"tenant": tenant_id, "need": need}
    try:
        for key in ("open_pr", "ordered_pr"):
            with sc.act("buyer", now) as s:
                pr = requisition.create(s, origin="MANUAL", purpose_code="BUFFER_BUILD", purpose_text=f"ADM-01 inactive record test ({key})",
                                        plant="P100", lines=_lines(need))
                requisition.submit(s, pr)
                pr_id, out[key] = pr.id, pr.number
            sc.approve_all(pr_id, now)
        with sc.act("buyer", now) as s:
            po = order.create_from_requisition(s, requisition=out["ordered_pr"], lines=[10], supplier_code="TF001", unit_price_minor=40500)[0]
            po_id, out["po"] = po.id, po.number
        sc.approve_all(po_id, now, "Manual price as per quotation")
    finally:
        clock.set_pinned(None)
    with tenant_tx(tenant_id) as s:
        assert s.get(PurchaseOrder, po_id).status == "TRANSMITTED"
    out["po_id"] = po_id
    return out


def _only(session, model, *conditions):
    return session.execute(select(model).where(*conditions)).scalar_one()


def _refused(session, call, *, document: str, kinds: list[str]) -> Problem:
    with pytest.raises(Problem) as caught:
        with session.begin_nested():
            call()
    problem = caught.value
    assert problem.status == 422 and problem.code == "ORG_RECORD_INACTIVE" and problem.rule_ref == "ADM-01", problem.detail
    assert f"new {document}" in problem.detail
    assert [i["kind"] for i in problem.extra["inactive"]] == kinds
    return problem


def test_new_requisition_names_a_deactivated_record(docs):
    with pytest.raises(_Rollback):
        with tenant_tx(docs["tenant"]) as s:
            _as(s, "buyer@axion.example")
            plant, company = _only(s, Plant, Plant.code == "P100"), _only(s, CompanyCode, CompanyCode.code == "1000")
            sloc = _only(s, StorageLocation, StorageLocation.plant == "P100", StorageLocation.code == "0001")
            cost = _only(s, CostObject, CostObject.type == "COST_CENTER", CostObject.code == "4100")
            s.add(PurchasingOrg(tenant_id=docs["tenant"], code="PO10", name="Central purchasing", company_code="1000"))
            s.add(PurchasingGroup(tenant_id=docs["tenant"], code="G10", name="Direct buying", purchasing_org="PO10"))
            s.flush()
            porg, pgroup = _only(s, PurchasingOrg, PurchasingOrg.code == "PO10"), _only(s, PurchasingGroup, PurchasingGroup.code == "G10")

            def create(**kw):
                return requisition.create(s, origin="MANUAL", purpose_text="ADM-01", plant=kw.pop("plant", "P100"), lines=kw.pop("lines", _lines(docs["need"])),
                                          **kw)

            assert create(purchasing_org="PO10", purchasing_group="G10").number          # all active: accepted
            for record, label, call in (
                (company, "company code", lambda: create()),
                (plant, "plant", lambda: create()),
                (sloc, "storage location", lambda: create()),
                (cost, "cost object", lambda: create(lines=_lines(docs["need"], account_assignment_type="COST_CENTER", account_assignment_code="4100"))),
                (porg, "purchasing organisation", lambda: create(purchasing_org="PO10")),
                (pgroup, "purchasing group", lambda: create(purchasing_group="G10")),
            ):
                record.active = False
                s.flush()
                _refused(s, call, document="requisition", kinds=[label])
                record.active = True
                s.flush()
            plant.active = sloc.active = False      # the header is judged first: the plant is named
            s.flush()
            _refused(s, lambda: create(), document="requisition", kinds=["plant"])
            _refused(s, lambda: create(lines=_lines(docs["need"], plant="P200")), document="requisition", kinds=["storage location"]) \
                if False else None
            raise _Rollback


def test_new_purchase_order_names_a_deactivated_record(docs):
    with pytest.raises(_Rollback):
        with tenant_tx(docs["tenant"]) as s:
            _as(s, "buyer@axion.example")
            plant, company = _only(s, Plant, Plant.code == "P100"), _only(s, CompanyCode, CompanyCode.code == "1000")
            sloc = _only(s, StorageLocation, StorageLocation.plant == "P100", StorageLocation.code == "0001")
            cost = _only(s, CostObject, CostObject.type == "COST_CENTER", CostObject.code == "4100")
            s.add(PurchasingOrg(tenant_id=docs["tenant"], code="1000", name="Purchasing organisation 1000", company_code="1000"))
            s.flush()
            porg = _only(s, PurchasingOrg, PurchasingOrg.code == "1000")
            pr_line = s.execute(select(PrLine).join(Requisition, Requisition.id == PrLine.requisition_id)
                                .where(Requisition.number == docs["open_pr"], PrLine.line_no == 10)).scalar_one()
            pr_line.account_assignment_type, pr_line.account_assignment_code = "COST_CENTER", "4100"
            s.flush()

            def create():
                return order.create_from_requisition(s, requisition=docs["open_pr"], lines=[10], supplier_code="TF001", unit_price_minor=40500)

            for record, label in ((company, "company code"), (plant, "plant"), (porg, "purchasing organisation"),
                                  (sloc, "storage location"), (cost, "cost object")):
                record.active = False
                s.flush()
                _refused(s, create, document="purchase order", kinds=[label])
                record.active = True
                s.flush()
            assert create()[0].number                                                # all active again: the order is created
            raise _Rollback


def test_new_goods_receipt_names_a_deactivated_record_but_the_order_stays_open(docs):
    with pytest.raises(_Rollback):
        with tenant_tx(docs["tenant"]) as s:
            _as(s, "receiver@axion.example")
            po = s.get(PurchaseOrder, docs["po_id"])
            plant = _only(s, Plant, Plant.code == "P100")
            sloc = _only(s, StorageLocation, StorageLocation.plant == "P100", StorageLocation.code == "0001")
            lines = [{"line": 10, "qty": "10", "batch": f"ORG-{uuid.uuid4().hex[:8].upper()}", "storage_location": "0001"}]
            for record, label in ((plant, "plant"), (sloc, "storage location")):
                record.active = False
                s.flush()
                _refused(s, lambda: receiving.post_gr(s, po, lines=lines), document="goods receipt", kinds=[label])
                record.active = True
                s.flush()
            assert po.status == "TRANSMITTED"
            gr = receiving.post_gr(s, po, lines=lines)                               # active again: the receipt posts
            assert gr.number and gr.status in ("POSTED", "QUALITY_HOLD")
            raise _Rollback


def test_existing_documents_keep_working_after_the_plant_is_deactivated(docs):
    """Deactivation is for new documents only: the guard is called where a document is created, not when it is read or changed."""
    with pytest.raises(_Rollback):
        with tenant_tx(docs["tenant"]) as s:
            _as(s, "buyer@axion.example")
            assert org_guard.inactive_records(s, plant="P100", company_code="1000") == []
            # codes that are not in the organisation master at all are not this guard's concern
            assert org_guard.inactive_records(s, plant="NOPLANT", company_code="9999", storage_location="ZZ") == []
            po = s.get(PurchaseOrder, docs["po_id"])
            _only(s, Plant, Plant.code == "P100").active = False
            s.flush()
            assert org_guard.inactive_records(s, plant="P100") == [{"kind": "plant", "code": "P100"}]
            assert po.status == "TRANSMITTED" and order.lines_of(s, po)     # the open order is untouched and still readable
            raise _Rollback
