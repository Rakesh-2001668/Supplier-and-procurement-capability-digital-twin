"""Security and control gates: RLS, authN/Z, state machines, SoD, idempotency, exactly-once, audit, constraints."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.pic.db import tenant_tx
from app.pic.models import (
    AppUser, ErpDocument, IntegrationMessage, Payment, PlannedOrder, PrLine, PurchaseOrder, Requisition, SodViolation, Tenant,
)
from app.pic.platform import integration, sod
from app.pic.platform.auth import Principal, hash_password, scopes_for
from app.pic.platform.errors import Problem
from app.pic.seed import reference
from tests.pic.conftest import PASSWORD


def _principal(session, email: str) -> Principal:
    user = session.execute(select(AppUser).where(AppUser.email == email)).scalar_one()
    p = Principal(user.id, user.tenant_id, "AXN", user.email, user.full_name, list(user.roles), scopes_for(list(user.roles)),
                  user.attributes or {}, user.supplier_id)
    session.info["principal"], session.info["user_id"] = p, user.id
    return p


def _axn_id():
    from app.pic.db import system_tx
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()


@pytest.fixture(scope="module")
def beta_tenant():
    tenant_id = reference.create_tenant("BETA", "Beta Logistics Pvt Ltd", "LOGISTICS")
    reference.bootstrap(tenant_id, company=("2000", "Beta Logistics Pvt Ltd", "29AAACB1111C1ZJ"), plants=[("B100", "Bengaluru", "29")],
                        cost_objects=[("COST_CENTER", "9100", "Fleet")])
    with tenant_tx(tenant_id) as s:
        if not s.execute(select(AppUser.id)).first():
            s.add(AppUser(tenant_id=tenant_id, email="admin@beta.example", full_name="Beta admin", password_hash=hash_password(PASSWORD),
                          roles=["TENANT_ADMIN", "BUYER"], attributes={}))
    return tenant_id


def test_rls_hides_other_tenant_rows(beta_tenant):
    with tenant_tx(beta_tenant) as s:
        assert s.execute(select(func.count()).select_from(PurchaseOrder)).scalar() == 0
        assert s.execute(select(func.count()).select_from(AppUser)).scalar() == 1


def test_rls_blocks_cross_tenant_writes(beta_tenant):
    axn = _axn_id()
    with pytest.raises(DBAPIError, match="row-level security"):
        with tenant_tx(beta_tenant) as s:
            s.add(AppUser(tenant_id=axn, email="intruder@beta.example", full_name="x", password_hash="x", roles=[], attributes={}))


def test_beta_login_sees_no_axion_data(client, login, beta_tenant):
    headers = login("admin@beta.example", tenant="BETA")
    assert client.get("/v1/purchase-orders", headers=headers).json()["items"] == []
    r = client.get("/v1/purchase-orders/PO-77410", headers=headers)
    assert r.status_code == 404


def test_unauthenticated_requests_get_problem_json(client):
    r = client.get("/v1/tasks")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "UNAUTHENTICATED" and "traceId" in r.json()


def test_scope_enforced(client, login):
    r = client.post("/v1/payments/runs", json={"run_date": "2027-01-31"}, headers=login("buyer"))
    assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN"


def test_illegal_transition_returns_409(client, login):
    r = client.post("/v1/purchase-orders/PO-77410/confirmations", json={"status": "CONFIRMED"}, headers=login("tf.sales"))
    assert r.status_code == 409 and r.json()["code"] == "ILLEGAL_TRANSITION"


def test_supplier_user_cannot_see_other_suppliers_po(client, login):
    r = client.get("/v1/purchase-orders/PO-77410", headers=login("kd.sales"))
    assert r.status_code == 404


def test_sod03_po_creator_cannot_post_gr():
    with tenant_tx(_axn_id()) as s:
        _principal(s, "buyer@axion.example")
        po = s.execute(select(PurchaseOrder).where(PurchaseOrder.number == "PO-77410")).scalar_one()
        with pytest.raises(Problem) as exc:
            sod.guard(s, "GR_POST", {"po_id": po.id})
        assert exc.value.code == "SOD_CONFLICT" and exc.value.rule_ref == "SOD-03"
    with tenant_tx(_axn_id()) as s:
        assert s.execute(select(SodViolation).where(SodViolation.rule_code == "SOD-03")).first() is not None


def test_invoice_post_is_idempotent(client, login):
    headers = {**login("ap.clerk"), "Idempotency-Key": "AXN|1000|TF001|INV-TF-8812"}
    first = client.post("/v1/invoices/INV-TF-8812/post", headers=headers).json()
    second = client.post("/v1/invoices/INV-TF-8812/post", headers=headers).json()
    assert first["erpDocument"] == second["erpDocument"] == "5100004421"
    assert first["replayed"] is False and second["replayed"] is True
    with tenant_tx(_axn_id()) as s:
        assert s.execute(select(func.count()).select_from(ErpDocument).where(
            ErpDocument.external_ref == "AXN|1000|TF001|INV-TF-8812")).scalar() == 1


def test_exactly_once_when_erp_response_is_lost():
    with tenant_tx(_axn_id()) as s:
        _principal(s, "ap.clerk@axion.example")
        message = integration.enqueue(s, target_system="SAP_S4", message_type="PAYMENT", idempotency_key="TEST|LOST-RESPONSE",
                                      object_type="TEST", object_id=uuid.uuid4(), object_ref="TEST-1", payload={"companyCode": "1000"})
        integration.FAULTS["lose_response"] = 1
        integration.process(s, message)
        assert message.status == "POSTED"
        retry = integration.enqueue(s, target_system="SAP_S4", message_type="PAYMENT", idempotency_key="TEST|LOST-RESPONSE",
                                    object_type="TEST", object_id=message.object_id, object_ref="TEST-1", payload={"companyCode": "1000"})
        assert retry.id == message.id
        assert s.execute(select(func.count()).select_from(ErpDocument).where(ErpDocument.external_ref == "TEST|LOST-RESPONSE")).scalar() == 1


def test_failed_posting_retries_then_replays():
    with tenant_tx(_axn_id()) as s:
        _principal(s, "ap.clerk@axion.example")
        message = integration.enqueue(s, target_system="SAP_S4", message_type="PAYMENT", idempotency_key="TEST|TIMEOUT",
                                      object_type="TEST", object_id=uuid.uuid4(), object_ref="TEST-2", payload={"companyCode": "1000"})
        integration.FAULTS["fail"] = 1
        integration.process(s, message)
        assert message.status == "RETRY" and message.attempts == 1
        integration.replay(s, message.id)
        assert message.status == "POSTED"


def test_audit_is_append_only_and_chained(client, login):
    with pytest.raises(DBAPIError, match="permission denied"):
        with tenant_tx(_axn_id()) as s:
            s.execute(text("UPDATE pic.audit_event SET reason = 'tampered'"))
    with tenant_tx(_axn_id()) as s:
        from app.pic.platform.audit import verify_chain
        result = verify_chain(s)
    assert result["valid"] is True and result["checked"] > 100


def test_requisition_origin_is_immutable_p02():
    with pytest.raises(DBAPIError, match="P02"):
        with tenant_tx(_axn_id()) as s:
            s.execute(text("UPDATE pic.requisition SET origin = 'MANUAL' WHERE number = 'REQ-2311'"))


def test_free_text_line_cannot_reference_material_p04():
    with pytest.raises(DBAPIError, match="free_text_no_material"):
        with tenant_tx(_axn_id()) as s:
            line = s.execute(select(PrLine).where(PrLine.item_type == "FREE_TEXT")).scalars().first()
            other = s.execute(select(PrLine).where(PrLine.material_id.is_not(None))).scalars().first()
            line.material_id = other.material_id
            s.flush()


def test_double_payment_is_impossible(client, login):
    r = client.post("/v1/payments/runs", json={"run_date": "2027-03-31", "include_not_due": True}, headers=login("finance.controller"))
    assert r.status_code == 200
    assert all(p["invoice"] not in ("INV-TF-8812", "HTS/1107") for p in r.json()["paid"])
    with tenant_tx(_axn_id()) as s:
        paid_invoices = s.execute(select(Payment.invoice_id)).scalars().all()
        assert len(paid_invoices) == len(set(paid_invoices))  # never two payments for one invoice


def test_mrp_simulation_creates_no_documents(client, login):
    with tenant_tx(_axn_id()) as s:
        before = s.execute(select(func.count()).select_from(PlannedOrder)).scalar()
    r = client.post("/v1/mrp/runs", json={"plant": "P100", "mode": "SIMULATION"}, headers=login("mrp.controller"))
    assert r.status_code == 201 and r.json()["status"] == "SIMULATED"
    with tenant_tx(_axn_id()) as s:
        assert s.execute(select(func.count()).select_from(PlannedOrder)).scalar() == before


def test_sealed_bids_cannot_be_read_before_close(client, login):
    close_at = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    body = {"type": "RFQ", "title": "Fixture build – line 3", "category": "TOOLING-SERVICES",
            "lines": [{"requisition": "REQ-2312", "line": 10, "annual_qty": "2", "monthly_qty": "2"}],
            "criteria": [{"code": "PRICE_TCO", "name": "Price", "weight": 70}, {"code": "TECHNICAL", "name": "Technical", "weight": 30}],
            "invitees": [{"supplier": "HTS004"}], "close_at": close_at, "baseline_method": "BUDGET", "baseline_price_minor": 9_250_000}
    created = client.post("/v1/sourcing/events", json=body, headers=login("category.head"))
    assert created.status_code == 201, created.text
    number = created.json()["number"]
    assert client.post(f"/v1/sourcing/events/{number}/publish", headers=login("category.head")).status_code == 200
    bid = {"lines": [{"line": 10, "unit_price": "88000", "payment_terms_days": 30, "lead_time_days": 21}]}
    assert client.post(f"/v1/sourcing/events/{number}/bids", json=bid, headers=login("hts.service")).status_code == 201
    r = client.get(f"/v1/sourcing/events/{number}/bids", headers=login("category.head"))
    assert r.status_code == 423 and r.json()["code"] == "BIDS_SEALED"
    trail = client.get(f"/v1/audit/SOURCING_EVENT/{number}", headers=login("category.head")).json()
    assert any(e["action"] == "BID_ACCESS_DENIED" for e in trail)


def test_weights_must_sum_to_100(client, login):
    close_at = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    body = {"type": "RFQ", "title": "Bad weights", "category": "TOOLING-SERVICES",
            "lines": [{"requisition": "REQ-2312", "line": 10, "annual_qty": "2", "monthly_qty": "2"}],
            "criteria": [{"code": "PRICE_TCO", "name": "Price", "weight": 60}], "invitees": [{"supplier": "HTS004"}],
            "close_at": close_at, "baseline_price_minor": 9_250_000, "baseline_method": "BUDGET"}
    number = client.post("/v1/sourcing/events", json=body, headers=login("category.head")).json()["number"]
    r = client.post(f"/v1/sourcing/events/{number}/publish", headers=login("category.head"))
    assert r.status_code == 422 and r.json()["ruleRef"] == "SRC-WEIGHTS"


def test_unqualified_supplier_cannot_be_invited(client, login):
    body = {"type": "RFQ", "title": "Invite check", "category": "ALU-DIECAST",
            "lines": [{"requisition": "REQ-2312", "line": 10, "annual_qty": "2", "monthly_qty": "2"}],
            "criteria": [{"code": "PRICE_TCO", "name": "Price", "weight": 100}], "invitees": [{"supplier": "MPC005"}],
            "close_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(), "baseline_price_minor": 1, "baseline_method": "BUDGET"}
    r = client.post("/v1/sourcing/events", json=body, headers=login("category.head"))
    assert r.status_code == 422 and "MPC005" in r.json()["detail"]


def test_four_eyes_requester_cannot_approve_own_requisition(client, login):
    body = {"origin": "MANUAL", "purpose_code": "IT", "plant": "P100", "lines": [
        {"item_type": "FREE_TEXT", "purchase_type": "EXPENSE", "description": "Label printer", "material_group": "IT-HW", "qty": "1",
         "uom": "EA", "price_est_minor": 4_500_000, "account_assignment_type": "COST_CENTER", "account_assignment_code": "4100",
         "need_date": "2027-02-01", "quotes": [{"supplier": "Zebra reseller Chennai", "reference": "ZRC-Q-0928", "date": "2026-09-28"}]}]}
    pr = client.post("/v1/requisitions", json=body, headers=login("requester"))
    assert pr.status_code == 201, pr.text
    number = pr.json()["number"]
    submitted = client.post(f"/v1/requisitions/{number}/submit", json={}, headers=login("requester")).json()
    assert submitted["status"] == "IN_APPROVAL"
    assert client.get("/v1/tasks", headers=login("requester")).json() == []
    tasks = [t for t in client.get("/v1/tasks", headers=login("plant.controller")).json() if t["object_ref"] == number]
    assert len(tasks) == 1
    done = client.post(f"/v1/tasks/{tasks[0]['id']}/complete", json={"decision": "APPROVE"}, headers=login("plant.controller"))
    assert done.status_code == 200
    assert client.get(f"/v1/requisitions/{number}", headers=login("requester")).json()["status"] == "APPROVED"
