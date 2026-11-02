"""The whole inventory workflow through the real HTTP API, one sequential scenario in its own tenant (INV1).

goods receipts -> stock visible (list, ledger, value) -> transfer (auto-post under the rule limit, ERP material document) -> block / unblock ->
validation (release from quality, unknown location, not enough stock) -> scrap awaiting approval -> SoD: the maker cannot approve (SOD-10), a user
without the approval scope cannot either -> stale If-Match (412) -> approval by another user -> post (movements, ERP message, idempotent) ->
two-step approval chain through the task inbox -> rejection -> stock moved after approval (re-checked at posting) -> closed period -> plant scope ->
physical inventory: freeze, blind count, recount by another person, a receipt during the count, approval by a different user than every counter
(SOD-11), count-relative posting, count accuracy KPI -> reservations: availability warning, MRP counts them as demand and releases them on cancel,
partial and full issue, rule-blocked reservation, expiry job -> rule sets (validation, effective-dated change) -> audit trail, events, tenant isolation.

Time is moved with the business clock (the API runs in-process); the tests share state on purpose and run in file order."""
import os
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.pic.db import tenant_tx
from app.pic.models import (
    AppUser, DemandElement, ErpDocument, IntegrationMessage, Material, OutboxEvent, PoLine, PurchaseOrder, Stock, StockMovement, StorageLocation, Supplier,
    SupplierCategoryStatus,
)
from app.pic.platform import clock
from app.pic.platform.core import next_number
from app.pic.seed.axion import at
from app.pic.seed.datasets import _tenant_kit as kit
from app.pic.services import jobs

from .conftest import PASSWORD

CODE = os.environ.get("INV_TEST_TENANT", "INV1")   # a developer re-running against a kept database (PIC_TEST_KEEP_DB) picks a fresh tenant code
DOMAIN = f"{CODE.lower()}.example"
GSTIN = "29AAKCD4821M1Z7"
P1, P2 = "P100", "P200"
TODAY = date(2026, 11, 4)
J: dict = {}   # state handed from step to step
M: dict = {}   # material number -> id

USERS = [
    ("admin", "Admin Anil", ["TENANT_ADMIN"], {}),
    ("buyer", "Bala Buyer", ["BUYER"], {"plants": [P1, P2]}),
    ("recv", "Rita Receiver", ["RECEIVER"], {"plants": [P1]}),                  # stores clerk: posts, counts
    ("recv2", "Ravi Receiver", ["RECEIVER"], {"plants": [P1]}),
    ("recv_p200", "Rekha Receiver (P200)", ["RECEIVER"], {"plants": [P2]}),
    ("ic1", "Isha Inventory", ["INVENTORY_CONTROLLER"], {"plants": [P1, P2]}),
    ("ic2", "Imran Inventory", ["INVENTORY_CONTROLLER"], {"plants": [P1, P2]}),
    ("mixed", "Manoj Mixed-Duties", ["RECEIVER", "INVENTORY_CONTROLLER"], {"plants": [P1]}),   # loaded directly: the admin API would refuse the pair (SOD-11)
    ("fin", "Farid Finance", ["FINANCE_CONTROLLER"], {}),
    ("mrp", "Mira MRP", ["MRP_CONTROLLER"], {"plants": [P1]}),
    ("reader", "Rhea Reader", ["REQUESTER"], {"cost_objects": ["COST_CENTER:6100"]}),
]
ROLE_USER = {"FINANCE_CONTROLLER": "fin", "INVENTORY_CONTROLLER": ["ic1", "ic2"], "BUYER": "buyer"}


def _email(local: str) -> str:
    return f"{local}@{DOMAIN}"


def _h(login, local: str) -> dict:
    return login(_email(local), CODE)


def _pin(day: date = TODAY, hour: int = 10) -> None:
    clock.set_pinned(at(day, hour))


def _problem(r, status: int, code: str | None = None) -> dict:
    assert r.status_code == status, r.text
    body = r.json()
    if code:
        assert body["code"] == code, body
    return body


@pytest.fixture(scope="module")
def env(database):
    sc = kit.setup_tenant(CODE, "Inventory Journey Industries Pvt Ltd", "MANUFACTURING", company=("1000", "Inventory Journey Industries Pvt Ltd", GSTIN),
                          plants=[(P1, "Main plant", "29"), (P2, "Second plant", "29")], cost_objects=[("COST_CENTER", "6100", "Test cost centre")],
                          holidays=[], domain=DOMAIN, role_user=ROLE_USER)
    kit.create_users(sc, USERS, PASSWORD)
    kit.rule_version(sc, "MFA", "2026.1-INV", date(2026, 4, 1), {"enforce": False}, "Inventory journey tenant: no MFA challenge for the API tests")
    with tenant_tx(sc.tenant_id) as s:
        for plant in (P1, P2):
            s.add(StorageLocation(tenant_id=sc.tenant_id, plant=plant, code="0002", name="Second location"))
        sup = Supplier(tenant_id=sc.tenant_id, code="INVSUP", legal_name="Journey Supplies Pvt Ltd", status="QUALIFIED", country="IN", state_code="29",
                       payment_terms="N30")
        s.add(sup)
        s.flush()
        s.add(SupplierCategoryStatus(tenant_id=sc.tenant_id, supplier_id=sup.id, category="GENERAL", status="QUALIFIED", qualified_on=date(2026, 1, 1)))
        M["supplier"] = sup.id
        for number, price, extra in (("JM-A", 10_000, {}), ("JM-B", 50_000, {"attributes": {"batchManaged": True, "expiryManaged": True}}),
                                     ("JM-HV", 5_000_000, {}), ("JM-RES", 20_000, {})):
            m = Material(tenant_id=sc.tenant_id, number=number, description=f"Journey material {number}", type="STOCK", material_group="GENERAL",
                         category="GENERAL", base_uom="EA", mrp_type="PD", lot_size_policy="EXACT", safety_stock=Decimal(0), planned_delivery_days=3,
                         gr_processing_days=0, standard_price_minor=price, status="ACTIVE", hsn_code="8708", gst_rate=Decimal(18), **extra)
            s.add(m)
            s.flush()
            M[number] = m.id
    return sc


def _po(sc, lines: list[tuple]) -> str:
    """A confirmed order (inserted directly; the order flow is covered elsewhere): lines (material, qty)."""
    with tenant_tx(sc.tenant_id) as s:
        buyer = s.execute(select(AppUser).where(AppUser.email == _email("buyer"))).scalar_one()
        po = PurchaseOrder(tenant_id=sc.tenant_id, number=next_number(s, "PURCHASE_ORDER"), version=1, company_code="1000", purch_org="1000", plant=P1,
                           supplier_id=M["supplier"], status="CONFIRMED", purpose_code="TEST", currency="INR", total_minor=0, payment_terms="N30",
                           tolerance={"over_pct": 0, "under_pct": 0, "price_pct": 0}, rule_set_version="TEST", created_by=buyer.id)
        s.add(po)
        s.flush()
        for index, (material, qty) in enumerate(lines, start=1):
            price = s.get(Material, M[material]).standard_price_minor
            s.add(PoLine(tenant_id=sc.tenant_id, po_id=po.id, line_no=index * 10, item_type="MATERIAL", purchase_type="STOCK", description="Test line",
                         material_group="GENERAL", uom="EA", gst_rate=Decimal(18), hsn_code="8708", need_date=TODAY + timedelta(days=10), plant=P1,
                         storage_location="0001", gr_required=True, ir_required=True, ses_required=False, ers=False, quality_managed=False,
                         price_source="MANUAL", material_id=M[material], qty=Decimal(qty), unit_price_minor=price, net_minor=int(Decimal(qty) * price),
                         created_by=buyer.id))
        return po.number


def _gr(client, login, lines: list[tuple], who: str = "recv") -> dict:
    """Receive the lines (material, qty, batch, expiry) on one order through the API."""
    po = _po(J["env"], [(m, q) for m, q, *_ in lines])
    body = {"po": po, "posting_date": TODAY.isoformat(),
            "lines": [{"line": (i + 1) * 10, "qty": str(q), "storage_location": "0001", "batch": (rest[0] if rest else ""),
                       **({"expiry": rest[1]} if len(rest) > 1 else {})} for i, (m, q, *rest) in enumerate(lines)]}
    _pin(TODAY, 8)
    r = client.post("/v1/goods-receipts", json=body, headers=_h(login, who))
    assert r.status_code == 201, r.text
    return r.json()


def _on_hand(client, login, material: str, stock_type: str = "UNRESTRICTED", sloc: str = "0001", batch: str = "", who: str = "ic1") -> Decimal:
    rows = client.get(f"/v1/stock?material={material}&plant={P1}&storage_location={sloc}&stock_type={stock_type}&onlyNonZero=false&limit=200", headers=_h(login, who)).json()["items"]
    return sum((Decimal(r["qty"]) for r in rows if r["material"] == material and r["batch"] == batch), Decimal(0))


def _posting(client, login, body: dict, who: str, key: str | None = None, expect: int = 201):
    _pin(TODAY, 9)
    r = client.post("/v1/stock-postings", json=body, headers={**_h(login, who), **({"Idempotency-Key": key} if key else {})})
    assert r.status_code == expect, r.text
    return r.json()


def _line(material: str, qty, sloc: str = "0001", **extra) -> dict:
    return {"material": material, "qty": str(qty), "storageLocation": sloc, **extra}


def _tasks(client, headers, ref: str) -> list[dict]:
    return [t for t in client.get("/v1/tasks", headers=headers).json() if t["object_ref"] == ref]


# ================================================================ 1. goods receipts make stock visible
def test_01_goods_receipts_make_stock_visible_with_value(env, client, login):
    J["env"] = env
    _pin(TODAY, 8)
    J["gr1"] = _gr(client, login, [("JM-A", 100), ("JM-B", 40, "B1", "2027-09-30"), ("JM-HV", 10), ("JM-RES", 60)])
    ic1 = _h(login, "ic1")
    rows = client.get(f"/v1/stock?plant={P1}&limit=200", headers=ic1).json()["items"]
    by = {(r["material"], r["batch"]): r for r in rows}
    assert Decimal(by[("JM-A", "")]["qty"]) == 100 and by[("JM-A", "")]["valueMinor"] == 1_000_000 and by[("JM-B", "B1")]["expiry"] == "2027-09-30"
    assert by[("JM-HV", "")]["valueMinor"] == 50_000_000 and by[("JM-RES", "")]["stockType"] == "UNRESTRICTED"
    ledger = client.get("/v1/stock/movements?movement_type=101&material=JM-A", headers=ic1).json()["items"]
    assert ledger[0]["valueMinor"] == 1_000_000 and ledger[0]["movementText"] == "Goods receipt" and ledger[0]["actor"]["email"] == _email("recv")
    summary = client.get("/v1/stock/summary", headers=ic1).json()
    assert summary["stockValueMinor"] == 1_000_000 + 2_000_000 + 50_000_000 + 1_200_000 and summary["byType"]["UNRESTRICTED"]["rows"] == 4


# ================================================================ 2-4. transfer, block, unblock: auto-post under the rule limit
def test_02_transfer_under_the_limit_posts_at_once_with_an_erp_document(env, client, login):
    r = _posting(client, login, {"type": "TRANSFER", "plant": P1, "lines": [_line("JM-A", 30, toStorageLocation="0002")], "submit": True}, "recv",
                 key="inv-transfer-1")
    J["transfer"], J["transfer_id"] = r["number"], r["id"]
    assert r["status"] == "POSTED" and r["autoPosted"] is True and r["totalValueMinor"] == 300_000 and r["number"].startswith("STP-")
    assert r["lines"][0]["movementType"] == "311" and r["erpDocument"] and r["rule"].startswith("INVENTORY-POSTING@")
    assert [m["qty"] for m in r["movements"]] == ["-30", "30"] and {m["movementType"] for m in r["movements"]} == {"311"}
    assert _on_hand(client, login, "JM-A") == 70 and _on_hand(client, login, "JM-A", sloc="0002") == 30
    # the Idempotency-Key replays the same posting, it does not move stock twice
    again = _posting(client, login, {"type": "TRANSFER", "plant": P1, "lines": [_line("JM-A", 30, toStorageLocation="0002")], "submit": True}, "recv",
                     key="inv-transfer-1")
    assert again["number"] == J["transfer"] and again["replayed"] is True and _on_hand(client, login, "JM-A") == 70
    with tenant_tx(env.tenant_id) as s:
        message = s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == f"STP|{J['transfer']}")).scalar_one()
        assert message.message_type == "STOCK_POSTING" and message.status == "POSTED" and message.erp_doc_no == r["erpDocument"]
        assert s.execute(select(ErpDocument.doc_type).where(ErpDocument.external_ref == f"STP|{J['transfer']}")).scalar_one() == "MB"


def test_03_block_and_unblock(env, client, login):
    draft = _posting(client, login, {"type": "BLOCK", "plant": P1, "reasonCode": "QUALITY_DOUBT", "reason": "Surface rust seen on the top layer",
                                     "lines": [_line("JM-A", 10)]}, "recv")
    assert draft["status"] == "DRAFT" and draft["lines"][0]["toStockType"] == "BLOCKED" and _on_hand(client, login, "JM-A") == 70
    ref = draft["number"]
    submit = client.post(f"/v1/stock-postings/{ref}/submit", headers=_h(login, "recv"))
    assert submit.status_code == 200 and submit.json()["status"] == "POSTED" and submit.json()["lines"][0]["movementType"] == "344"
    assert _on_hand(client, login, "JM-A") == 60 and _on_hand(client, login, "JM-A", "BLOCKED") == 10
    un = _posting(client, login, {"type": "UNBLOCK", "plant": P1, "lines": [_line("JM-A", 4)], "submit": True}, "recv")
    assert un["status"] == "POSTED" and un["lines"][0]["movementType"] == "343"
    assert _on_hand(client, login, "JM-A") == 64 and _on_hand(client, login, "JM-A", "BLOCKED") == 6


def test_04_validation_and_refusals(env, client, login):
    _pin(TODAY, 9)
    h = _h(login, "recv")
    release = _problem(client.post("/v1/stock-postings", json={"type": "RELEASE_QUALITY", "plant": P1, "lines": [_line("JM-A", 1)]}, headers=h), 422, "USE_USAGE_DECISION")
    assert "usage decision" in release["detail"]
    _problem(client.post("/v1/stock-postings", json={"type": "SCRAP", "plant": P1, "lines": [_line("JM-A", 1)]}, headers=h), 422, "REASON_CODE_REQUIRED")
    _problem(client.post("/v1/stock-postings", json={"type": "SCRAP", "plant": P1, "reasonCode": "NOPE", "lines": [_line("JM-A", 1)]}, headers=h), 422, "REASON_CODE_UNKNOWN")
    short = _problem(client.post("/v1/stock-postings", json={"type": "TRANSFER", "plant": P1, "lines": [_line("JM-A", 500, toStorageLocation="0002")]}, headers=h),
                     422, "INSUFFICIENT_STOCK")      # negative stock is refused with what is available
    assert short["availableQty"] == "64" and short["requiredQty"] == "500"
    _problem(client.post("/v1/stock-postings", json={"type": "TRANSFER", "plant": P1, "lines": [_line("JM-A", 1, toStorageLocation="0099")]}, headers=h), 422, "UNKNOWN_STORAGE_LOCATION")
    _problem(client.post("/v1/stock-postings", json={"type": "TRANSFER", "plant": P1, "lines": [_line("JM-A", 1, toStorageLocation="0001")]}, headers=h), 422, "VALIDATION_FAILED")
    _problem(client.post("/v1/stock-postings", json={"type": "TRANSFER", "plant": P1, "lines": [_line("JM-A", 0.0001, toStorageLocation="0002")]}, headers=h), 422)
    _problem(client.post("/v1/stock-postings", json={"type": "TRANSFER", "plant": P1, "lines": [_line("JM-A", 1, toStorageLocation="0002"),
                                                                                                  _line("JM-A", 2, toStorageLocation="0002")]}, headers=h), 422, "DUPLICATE_LINE")
    batch = _problem(client.post("/v1/stock-postings", json={"type": "BLOCK", "plant": P1, "reasonCode": "DAMAGED", "reason": "Damaged pallet",
                                                             "lines": [_line("JM-B", 1)]}, headers=h), 422, "INSUFFICIENT_STOCK")
    assert "batch" in batch["detail"].lower()      # JM-B is in batch B1: the line has to name it
    assert client.post("/v1/stock-postings", json={"type": "BLOCK", "plant": P1, "lines": [_line("JM-A", 1)]}, headers=_h(login, "reader")).status_code == 403   # no inventory:post


# ================================================================ 5-8. scrap: approval, SoD, If-Match, posting
def test_05_scrap_needs_approval_even_below_the_limit(env, client, login):
    r = _posting(client, login, {"type": "SCRAP", "plant": P1, "reasonCode": "DAMAGED", "reason": "Forklift damage to 5 cartons, photographed",
                                 "lines": [_line("JM-B", 5, batch="B1")], "submit": True}, "recv")
    J["scrap_a"] = r["number"]
    assert r["status"] == "SUBMITTED" and r["autoPosted"] is False and r["totalValueMinor"] == 250_000
    assert [a["role"] for a in r["approvals"]] == ["INVENTORY_CONTROLLER"] and r["approvals"][0]["status"] == "OPEN"
    assert _on_hand(client, login, "JM-B", batch="B1") == 40            # nothing moved yet
    assert client.post(f"/v1/stock-postings/{J['scrap_a']}/post", headers=_h(login, "recv")).status_code == 409   # not approved
    assert client.post(f"/v1/stock-postings/{J['scrap_a']}/approve", headers=_h(login, "recv")).status_code == 403     # no approval scope
    assert client.post(f"/v1/stock-postings/{J['scrap_a']}/submit", headers=_h(login, "recv")).status_code == 409      # already submitted
    listing = client.get("/v1/stock-postings?status=SUBMITTED&type=SCRAP", headers=_h(login, "ic1")).json()
    assert [x["number"] for x in listing["items"]] == [J["scrap_a"]] and listing["nextCursor"] is None


def test_06_the_maker_cannot_approve_sod10(env, client, login):
    r = _posting(client, login, {"type": "SCRAP", "plant": P1, "reasonCode": "LOST", "reason": "Two blocked pieces missing at the quarterly check",
                                 "lines": [_line("JM-A", 2, stockType="BLOCKED")], "submit": True}, "ic1")
    J["scrap_b"] = r["number"]
    assert r["status"] == "SUBMITTED"
    refused = _problem(client.post(f"/v1/stock-postings/{J['scrap_b']}/approve", headers=_h(login, "ic1")), 409, "SOD_CONFLICT")
    assert refused["ruleRef"] == "SOD-10"
    with tenant_tx(env.tenant_id) as s:
        from app.pic.models import SodViolation
        assert s.execute(select(func.count()).select_from(SodViolation).where(SodViolation.rule_code == "SOD-10", SodViolation.outcome == "BLOCKED")).scalar_one() >= 1
    # the drafter who is not the submitter is a maker too
    draft = _posting(client, login, {"type": "SCRAP", "plant": P1, "reasonCode": "LOST", "reason": "One blocked piece missing at the check",
                                     "lines": [_line("JM-A", 1, stockType="BLOCKED")]}, "ic2")
    assert client.post(f"/v1/stock-postings/{draft['number']}/submit", headers=_h(login, "recv")).json()["status"] == "SUBMITTED"
    _problem(client.post(f"/v1/stock-postings/{draft['number']}/approve", headers=_h(login, "ic2")), 409, "SOD_CONFLICT")
    J["scrap_draft_b"] = draft["number"]
    # another controller approves scrap B (first If-Match is stale)
    etag = client.get(f"/v1/stock-postings/{J['scrap_b']}", headers=_h(login, "ic2")).headers["ETag"]
    _problem(client.post(f"/v1/stock-postings/{J['scrap_b']}/approve", headers={**_h(login, "ic2"), "If-Match": '"999"'}), 412, "STALE_WRITE")
    ok = client.post(f"/v1/stock-postings/{J['scrap_b']}/approve", headers={**_h(login, "ic2"), "If-Match": etag}, json={"comment": "Checked against the count sheet"})
    assert ok.status_code == 200 and ok.json()["status"] == "APPROVED" and ok.json()["approvedBy"]["email"] == _email("ic2")
    assert ok.headers["ETag"] != etag


def test_07_approve_and_post_scrap(env, client, login):
    ic1 = _h(login, "ic1")
    approved = client.post(f"/v1/stock-postings/{J['scrap_a']}/approve", headers=ic1)
    assert approved.status_code == 200 and approved.json()["status"] == "APPROVED" and approved.json()["approvals"][0]["status"] == "COMPLETED"
    again = client.post(f"/v1/stock-postings/{J['scrap_a']}/approve", headers=ic1)
    _problem(again, 409, "ILLEGAL_TRANSITION")
    posted = client.post(f"/v1/stock-postings/{J['scrap_a']}/post", headers={**_h(login, "recv"), "Idempotency-Key": "inv-post-a"})
    assert posted.status_code == 200 and posted.json()["status"] == "POSTED" and posted.json()["erpDocument"]
    movement = posted.json()["movements"][0]
    assert movement["movementType"] == "551" and movement["qty"] == "-5" and movement["valueMinor"] == -250_000
    replay = client.post(f"/v1/stock-postings/{J['scrap_a']}/post", headers={**_h(login, "recv"), "Idempotency-Key": "inv-post-a"})
    assert replay.json()["replayed"] is True
    assert client.post(f"/v1/stock-postings/{J['scrap_a']}/post", headers=_h(login, "recv")).json()["status"] == "POSTED"     # posting twice moves nothing twice
    assert _on_hand(client, login, "JM-B", batch="B1") == 35
    scrap_b = client.post(f"/v1/stock-postings/{J['scrap_b']}/post", headers=_h(login, "ic1")).json()
    assert scrap_b["status"] == "POSTED" and _on_hand(client, login, "JM-A", "BLOCKED") == 4
    ledger = client.get("/v1/stock/movements?movement_type=551&limit=10", headers=ic1).json()["items"]
    assert {m["reasonCode"] for m in ledger} == {"DAMAGED", "LOST"} and all(m["postingRef"].startswith("STP-") for m in ledger)
    # nobody can cancel what is posted
    _problem(client.post(f"/v1/stock-postings/{J['scrap_a']}/cancel", json={"reason": "Changed my mind"}, headers=_h(login, "recv")), 409, "ILLEGAL_TRANSITION")


def test_08_value_bands_make_a_two_step_chain_worked_through_the_task_inbox(env, client, login):
    r = _posting(client, login, {"type": "SCRAP", "plant": P1, "reasonCode": "OBSOLETE", "reason": "Superseded model, ECN 4471, five units",
                                 "lines": [_line("JM-HV", 5)], "submit": True}, "recv")
    J["scrap_hv"] = r["number"]
    assert r["totalValueMinor"] == 25_000_000 and [a["role"] for a in r["approvals"]] == ["INVENTORY_CONTROLLER"]
    task = _tasks(client, _h(login, "ic2"), J["scrap_hv"])[0]
    assert _tasks(client, _h(login, "recv"), J["scrap_hv"]) == []                         # the maker's inbox does not show it
    step1 = client.post(f"/v1/tasks/{task['id']}/complete", json={"decision": "APPROVE", "comment": "Obsolescence confirmed"}, headers=_h(login, "ic2"))
    assert step1.status_code == 200, step1.text
    mid = client.get(f"/v1/stock-postings/{J['scrap_hv']}", headers=_h(login, "ic1")).json()
    assert mid["status"] == "SUBMITTED" and [a["role"] for a in mid["approvals"]] == ["INVENTORY_CONTROLLER", "FINANCE_CONTROLLER"]
    assert client.post(f"/v1/stock-postings/{J['scrap_hv']}/approve", headers=_h(login, "ic1")).status_code == 403    # the open step is finance's
    done = client.post(f"/v1/stock-postings/{J['scrap_hv']}/approve", headers=_h(login, "fin"), json={"comment": "Write-off booked against the obsolescence provision"})
    assert done.status_code == 200 and done.json()["status"] == "APPROVED"
    assert client.post(f"/v1/stock-postings/{J['scrap_hv']}/post", headers=_h(login, "ic1")).json()["status"] == "POSTED"
    assert _on_hand(client, login, "JM-HV") == 5


def test_09_rejection_and_cancellation(env, client, login):
    r = _posting(client, login, {"type": "SCRAP", "plant": P1, "reasonCode": "OTHER", "reason": "Unspecified shrinkage claim",
                                 "lines": [_line("JM-A", 1)], "submit": True}, "recv")
    no_reason = client.post(f"/v1/stock-postings/{r['number']}/reject", json={"reason": "x"}, headers=_h(login, "ic2"))
    assert no_reason.status_code == 422
    rejected = client.post(f"/v1/stock-postings/{r['number']}/reject", json={"reason": "No evidence of loss attached"}, headers=_h(login, "ic2"))
    assert rejected.status_code == 200 and rejected.json()["status"] == "REJECTED" and rejected.json()["decisionComment"] == "No evidence of loss attached"
    _problem(client.post(f"/v1/stock-postings/{r['number']}/post", headers=_h(login, "ic2")), 409, "ILLEGAL_TRANSITION")
    # the draft left in test 06 is cancelled by its maker; the cancelled posting has no open task
    cancelled = client.post(f"/v1/stock-postings/{J['scrap_draft_b']}/cancel", json={"reason": "Raised twice by mistake"}, headers=_h(login, "recv"))
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"
    assert _tasks(client, _h(login, "ic1"), J["scrap_draft_b"]) == []


def test_10_stock_that_moved_after_approval_is_rechecked_at_posting(env, client, login):
    r = _posting(client, login, {"type": "SCRAP", "plant": P1, "reasonCode": "DAMAGED", "reason": "Water damage to the second location, 25 pieces",
                                 "lines": [_line("JM-A", 25, "0002")], "submit": True}, "recv")
    assert client.post(f"/v1/stock-postings/{r['number']}/approve", headers=_h(login, "ic1")).json()["status"] == "APPROVED"
    away = _posting(client, login, {"type": "TRANSFER", "plant": P1, "lines": [_line("JM-A", 20, "0002", toStorageLocation="0001")], "submit": True}, "recv")
    assert away["status"] == "POSTED" and _on_hand(client, login, "JM-A", sloc="0002") == 10
    short = _problem(client.post(f"/v1/stock-postings/{r['number']}/post", headers=_h(login, "ic1")), 422, "INSUFFICIENT_STOCK")
    assert short["availableQty"] == "10"
    assert client.get(f"/v1/stock-postings/{r['number']}", headers=_h(login, "ic1")).json()["status"] == "APPROVED"      # nothing moved, still postable
    assert client.post(f"/v1/stock-postings/{r['number']}/cancel", json={"reason": "Stock moved, raise a new scrap"}, headers=_h(login, "ic1")).status_code == 200
    assert _on_hand(client, login, "JM-A") == 84 and _on_hand(client, login, "JM-A", sloc="0002") == 10


def test_11_closed_posting_period_and_plant_scope(env, client, login):
    _pin(TODAY, 9)
    fin = _h(login, "fin")
    closed = client.post("/v1/finance/periods/2026-10/close", json={"companyCode": "1000", "reason": "October close for the inventory cut-off test"}, headers=fin)
    assert closed.status_code == 200, closed.text
    body = {"type": "TRANSFER", "plant": P1, "postingDate": "2026-10-15", "lines": [_line("JM-A", 1, toStorageLocation="0002")], "submit": True}
    refused = _problem(client.post("/v1/stock-postings", json=body, headers=_h(login, "recv")), 409, "PERIOD_CLOSED")
    assert refused["ruleRef"] == "CUT-OFF" and refused["period"] == "2026-10"
    reopened = client.post("/v1/finance/periods/2026-10/reopen", json={"companyCode": "1000", "reason": "Reopened after the inventory cut-off test"}, headers=fin)
    assert reopened.status_code == 200
    assert client.post("/v1/stock-postings", json=body, headers=_h(login, "recv")).json()["status"] == "POSTED"   # back in an open period
    assert _problem(client.post("/v1/stock-postings", json={"type": "TRANSFER", "plant": P1, "postingDate": "2026-11-30",
                                                           "lines": [_line("JM-A", 1, toStorageLocation="0002")]}, headers=_h(login, "recv")), 422, "RULE_VIOLATION")   # future date
    # plant scope: the P200 stores clerk cannot touch P100, neither to write nor to read
    outsider = _h(login, "recv_p200")
    _problem(client.post("/v1/stock-postings", json={"type": "BLOCK", "plant": P1, "reasonCode": "DAMAGED", "reason": "x" * 5, "lines": [_line("JM-A", 1)]}, headers=outsider),
             403, "FORBIDDEN")
    assert client.get(f"/v1/stock?plant={P1}", headers=outsider).status_code == 403
    assert client.get(f"/v1/stock-postings/{J['transfer']}", headers=outsider).status_code == 404       # a document of another plant does not exist for them
    assert client.get("/v1/stock-postings?limit=50", headers=outsider).json()["items"] == []


# ================================================================ 12-17. physical inventory
def _count_line(count: dict, material: str, batch: str = "") -> dict:
    return next(l for l in count["lines"] if l["material"] == material and l["batch"] == batch)


def test_12_count_freeze_blind_view_and_recount(env, client, login):
    _pin(TODAY, 9)
    ic1, recv, recv2 = _h(login, "ic1"), _h(login, "recv"), _h(login, "recv2")
    created = client.post("/v1/physical-inventories", json={"plant": P1, "storageLocation": "0001", "description": "November cycle count"}, headers=ic1)
    assert created.status_code == 201, created.text
    count = created.json()
    J["count"] = count["number"]
    assert count["status"] == "PLANNED" and count["lineCount"] == 4 and count["frozenAt"] and count["number"].startswith("PHI-")
    assert _count_line(count, "JM-A")["bookQty"] == "83" and "bookQty" in count["lines"][0]                   # the controller sees the book quantities
    blind = client.get(f"/v1/physical-inventories/{J['count']}", headers=recv).json()
    assert blind["blind"] is True and all("bookQty" not in l and "diffQty" not in l for l in blind["lines"]) and "gainMinor" not in blind
    _problem(client.post("/v1/physical-inventories", json={"plant": P1, "storageLocation": "0001"}, headers=ic1), 409, "COUNT_IN_PROGRESS")
    _problem(client.post("/v1/physical-inventories", json={"plant": P2, "storageLocation": "0001"}, headers=ic1), 422, "NOTHING_TO_COUNT")
    # the counter enters what is on the shelf: two inside the tolerance, one a fifth short, one found stock that is not on the list
    entries = [{"material": "JM-A", "qty": "83"}, {"material": "JM-B", "batch": "B1", "qty": "35"}, {"material": "JM-RES", "qty": "60"},
               {"material": "JM-HV", "qty": "4", "note": "one unit missing"}, {"material": "JM-B", "batch": "B-FOUND", "qty": "3", "note": "not on the list"}]
    r = client.put(f"/v1/physical-inventories/{J['count']}/counts", json={"counts": entries}, headers=recv)
    assert r.status_code == 200, r.text
    after = r.json()
    assert after["status"] == "COUNTING" and after["progress"]["recountRequired"] == 2 and "bookQty" not in after["lines"][0]
    assert _count_line(after, "JM-HV")["countStatus"] == "RECOUNT_REQUIRED" and _count_line(after, "JM-B", "B-FOUND")["unlisted"] is True
    assert _count_line(after, "JM-A")["countStatus"] == "COUNTED"
    _problem(client.put(f"/v1/physical-inventories/{J['count']}/counts", json={"counts": [{"material": "JM-HV", "qty": "5"}]}, headers=recv), 403, "RECOUNT_SAME_COUNTER")
    _problem(client.post(f"/v1/physical-inventories/{J['count']}/submit", headers=recv), 409, "ILLEGAL_TRANSITION")     # not fully counted
    # a receipt is posted while counting: it must not be wiped out by the count
    J["gr2"] = _gr(client, login, [("JM-RES", 20)])
    assert _on_hand(client, login, "JM-RES") == 80
    # recount by two other people (the mixed-duties user is one of them)
    r = client.put(f"/v1/physical-inventories/{J['count']}/counts", json={"counts": [{"material": "JM-B", "batch": "B-FOUND", "qty": "2"}]}, headers=recv2)
    assert r.status_code == 200 and r.json()["status"] == "COUNTING"
    r = client.put(f"/v1/physical-inventories/{J['count']}/counts", json={"counts": [{"material": "JM-HV", "qty": "4"}]}, headers=_h(login, "mixed"))
    assert r.status_code == 200, r.text
    counted = r.json()
    assert counted["status"] == "COUNTED" and counted["progress"]["accepted"] == 5
    assert _count_line(counted, "JM-HV")["countStatus"] == "RECOUNTED" and _count_line(counted, "JM-HV")["recountedBy"]["email"] == _email("mixed")
    assert _problem(client.put(f"/v1/physical-inventories/{J['count']}/counts", json={"counts": [{"material": "JM-A", "qty": "83"}]}, headers=recv2), 403)["code"] == "FORBIDDEN"


def test_13_submit_sod11_approval_and_count_relative_posting(env, client, login):
    recv, ic1, ic2, fin = _h(login, "recv"), _h(login, "ic1"), _h(login, "ic2"), _h(login, "fin")
    submitted = client.post(f"/v1/physical-inventories/{J['count']}/submit", headers=recv)
    assert submitted.status_code == 200 and submitted.json()["status"] == "PENDING_APPROVAL"
    # the controller's view: differences, first-count result, and the approval chain from the value of the differences (5,100,000 > 5,000,000)
    view = client.get(f"/v1/physical-inventories/{J['count']}", headers=ic2).json()
    assert view["blind"] is False and view["gainMinor"] == 100_000 and view["lossMinor"] == 5_000_000 and view["accuracyPct"] == "60.00"
    assert _count_line(view, "JM-HV")["diffQty"] == "-1" and _count_line(view, "JM-HV")["diffValueMinor"] == -5_000_000 and _count_line(view, "JM-HV")["firstCountWithinTolerance"] is False
    assert _count_line(view, "JM-B", "B-FOUND")["bookQty"] == "0" and _count_line(view, "JM-B", "B-FOUND")["diffQty"] == "2"
    assert [a["role"] for a in view["approvals"]] == ["INVENTORY_CONTROLLER"]
    # SOD-11: a user who counted cannot approve, even holding the approval role; neither can the submitter or a user without the scope
    refused = _problem(client.post(f"/v1/physical-inventories/{J['count']}/approve", headers=_h(login, "mixed")), 409, "SOD_CONFLICT")
    assert refused["ruleRef"] == "SOD-11"
    assert client.post(f"/v1/physical-inventories/{J['count']}/approve", headers=recv).status_code == 403
    assert client.post(f"/v1/physical-inventories/{J['count']}/post", headers=ic1).status_code == 409       # not approved yet
    # a controller sees the whole difference list; the counter 'mixed' (who counted) still gets the blind view
    assert client.get(f"/v1/physical-inventories/{J['count']}", headers=_h(login, "mixed")).json()["blind"] is True
    step1 = client.post(f"/v1/physical-inventories/{J['count']}/approve", headers=ic1, json={"comment": "Differences explained by the stores manager"})
    assert step1.status_code == 200 and step1.json()["status"] == "PENDING_APPROVAL" and len(step1.json()["approvals"]) == 2
    step2 = client.post(f"/v1/physical-inventories/{J['count']}/approve", headers=fin)
    assert step2.status_code == 200 and step2.json()["status"] == "APPROVED"
    posted = client.post(f"/v1/physical-inventories/{J['count']}/post", headers={**ic1, "Idempotency-Key": "inv-count-post"})
    assert posted.status_code == 200, posted.text
    body = posted.json()
    assert body["status"] == "POSTED" and body["erpDocument"] and body["gainMinor"] == 100_000 and body["lossMinor"] == 5_000_000
    res = _count_line(body, "JM-RES")
    assert res["driftQty"] == "20" and res["postedQty"] == "0"                         # 20 were received during the count, none posted as a difference
    assert _count_line(body, "JM-HV")["postedQty"] == "-1" and _count_line(body, "JM-B", "B-FOUND")["postedQty"] == "2"
    assert _on_hand(client, login, "JM-RES") == 80                                     # the receipt during the count stands
    assert _on_hand(client, login, "JM-HV") == 4 and _on_hand(client, login, "JM-B", batch="B-FOUND") == 2
    moves = client.get(f"/v1/stock/movements?reference={J['count']}", headers=ic1).json()["items"]
    assert {(m["movementType"], m["qty"]) for m in moves} == {("702", "-1"), ("701", "2")} and all(m["postingRef"] == J["count"] for m in moves)
    assert client.post(f"/v1/physical-inventories/{J['count']}/post", headers=ic1).json()["status"] == "POSTED"
    kpi = {i["code"]: i for i in client.get("/v1/kpis?module=M09&trend=false", headers=ic1).json()["items"]}
    assert kpi["M09.STOCK_COUNT_ACCURACY"]["value"] == "60.0" and kpi["M09.STOCK_COUNT_ACCURACY"]["denominator"] == "5"
    assert Decimal(kpi["M09.STOCK_ADJUSTMENT_VALUE"]["value"]) == 5_100_000 + 250_000 + 25_000_000 + 20_000          # count differences and the three scraps posted
    turns = kpi["M09.INVENTORY_TURNS"]
    assert turns["unit"] == "RATIO" and all("error" not in kpi[c]["detail"] for c in ("M09.INVENTORY_TURNS", "M09.STOCK_COUNT_ACCURACY", "M09.STOCK_ADJUSTMENT_VALUE"))
    assert turns["value"] == "0.0" and turns["detail"]["windowDays"] == 365 and turns["detail"]["issuesMinor"] == 0      # nothing issued yet: the reservations come later
    by_plant = {i["code"]: i for i in client.get(f"/v1/kpis?module=M09&trend=false&plant={P1}", headers=ic1).json()["items"]}
    assert by_plant["M09.STOCK_COUNT_ACCURACY"]["value"] == "60.0"


def test_14_a_rejected_count_goes_back_to_the_counters(env, client, login):
    recv, ic2 = _h(login, "recv"), _h(login, "ic2")
    created = client.post("/v1/physical-inventories", json={"plant": P1, "storageLocation": "0001", "materials": ["JM-A", "JM-RES"]}, headers=recv)
    assert created.status_code == 201 and created.json()["lineCount"] == 2
    number = created.json()["number"]
    client.put(f"/v1/physical-inventories/{number}/counts", json={"counts": [{"material": "JM-A", "qty": "83"}, {"material": "JM-RES", "qty": "80"}]}, headers=recv)
    assert client.post(f"/v1/physical-inventories/{number}/submit", headers=recv).json()["status"] == "PENDING_APPROVAL"
    _problem(client.post(f"/v1/physical-inventories/{number}/reject", json={"reason": "x"}, headers=ic2), 422)
    back = client.post(f"/v1/physical-inventories/{number}/reject", json={"reason": "Count sheet for the second location is missing"}, headers=ic2)
    assert back.status_code == 200 and back.json()["status"] == "COUNTING"
    # an approver orders a recount of a line, which reopens the document
    client.put(f"/v1/physical-inventories/{number}/counts", json={"counts": [{"material": "JM-A", "qty": "83"}]}, headers=recv)
    assert client.get(f"/v1/physical-inventories/{number}", headers=recv).json()["status"] == "COUNTED"
    ordered = client.post(f"/v1/physical-inventories/{number}/recount", json={"materials": ["JM-A"], "reason": "Spot check disagrees"}, headers=ic2)
    assert ordered.status_code == 200 and ordered.json()["status"] == "COUNTING" and _count_line(ordered.json(), "JM-A")["countStatus"] == "RECOUNT_REQUIRED"
    assert client.post(f"/v1/physical-inventories/{number}/cancel", json={"reason": "Replaced by the quarterly count"}, headers=recv).json()["status"] == "CANCELLED"
    assert {c["number"] for c in client.get("/v1/physical-inventories?status=POSTED,CANCELLED", headers=ic2).json()["items"]} == {J["count"], number}


def test_14b_a_loss_larger_than_the_stock_now_on_hand_is_refused_at_posting(env, client, login):
    recv, recv2, ic1 = _h(login, "recv"), _h(login, "recv2"), _h(login, "ic1")
    created = client.post("/v1/physical-inventories", json={"plant": P1, "storageLocation": "0002", "materials": ["JM-A"]}, headers=ic1)
    assert created.status_code == 201 and created.json()["lines"][0]["bookQty"] == "11", created.text
    number = created.json()["number"]
    assert client.put(f"/v1/physical-inventories/{number}/counts", json={"counts": [{"material": "JM-A", "qty": "5"}]}, headers=recv).json()["status"] == "COUNTING"
    assert client.put(f"/v1/physical-inventories/{number}/counts", json={"counts": [{"material": "JM-A", "qty": "5"}]}, headers=recv2).json()["status"] == "COUNTED"
    assert client.post(f"/v1/physical-inventories/{number}/submit", headers=recv).json()["status"] == "PENDING_APPROVAL"
    assert client.post(f"/v1/physical-inventories/{number}/approve", headers=_h(login, "ic2")).json()["status"] == "APPROVED"
    # eight pieces leave the location after the freeze: the loss of six counted against 11 would leave -3 of what is there now
    moved = _posting(client, login, {"type": "TRANSFER", "plant": P1, "lines": [_line("JM-A", 8, "0002", toStorageLocation="0001")], "submit": True}, "recv")
    assert moved["status"] == "POSTED"
    refused = _problem(client.post(f"/v1/physical-inventories/{number}/post", headers=ic1), 422, "NEGATIVE_STOCK")
    assert refused["material"] == "JM-A" and refused["stockNow"] == "3" and refused["bookAtFreeze"] == "11"
    assert client.get(f"/v1/physical-inventories/{number}", headers=ic1).json()["status"] == "APPROVED" and _on_hand(client, login, "JM-A", sloc="0002") == 3
    assert client.post(f"/v1/physical-inventories/{number}/cancel", json={"reason": "Stock moved during the count, count again"}, headers=recv).json()["status"] == "CANCELLED"
    back = _posting(client, login, {"type": "TRANSFER", "plant": P1, "lines": [_line("JM-A", 8, "0001", toStorageLocation="0002")], "submit": True}, "recv")
    assert back["status"] == "POSTED" and _on_hand(client, login, "JM-A", sloc="0002") == 11


# ================================================================ 15-19. reservations and MRP
def _mrp(client, login, mode: str = "SIMULATION") -> dict:
    _pin(TODAY, 11)
    r = client.post("/v1/mrp/runs", json={"plant": P1, "mode": mode, "materials": ["JM-RES"]}, headers=_h(login, "mrp"))
    assert r.status_code == 201, r.text
    row = next(x for x in r.json()["results"] if x["material"] == "JM-RES")
    return {**row, **{k: Decimal(row[k]) for k in ("gross", "on_hand", "net")}}


def test_15_reservation_availability_and_mrp_demand(env, client, login):
    _pin(TODAY, 9)
    recv = _h(login, "recv")
    first = client.post("/v1/reservations", json={"material": "JM-RES", "plant": P1, "storageLocation": "0001", "qty": "50", "needDate": "2026-11-20",
                                                    "costObject": "COST_CENTER:6100", "purpose": "Line 3 changeover kit"}, headers={**recv, "Idempotency-Key": "inv-rsv-1"})
    assert first.status_code == 201, first.text
    J["rsv1"], J["rsv1_id"] = first.json()["number"], first.json()["id"]
    r1 = first.json()
    assert r1["status"] == "OPEN" and r1["availabilityAtCreation"]["available"] == "80" and r1["availabilityAtCreation"]["shortBy"] == "0" and r1["number"].startswith("RSV-")
    replay = client.post("/v1/reservations", json={"material": "JM-RES", "plant": P1, "storageLocation": "0001", "qty": "50", "needDate": "2026-11-20",
                                                    "costObject": "COST_CENTER:6100", "purpose": "Line 3 changeover kit"}, headers={**recv, "Idempotency-Key": "inv-rsv-1"})
    assert replay.json()["number"] == J["rsv1"] and replay.json()["replayed"] is True
    second = client.post("/v1/reservations", json={"material": "JM-RES", "plant": P1, "storageLocation": "0001", "qty": "60", "needDate": "2026-11-25",
                                                     "costObject": "COST_CENTER:6100"}, headers=recv)
    assert second.status_code == 201 and second.json()["availabilityAtCreation"]["shortBy"] == "30"      # warned, still demand: blockWhenUnavailable is off
    J["rsv2"] = second.json()["number"]
    with tenant_tx(env.tenant_id) as s:
        elements = s.execute(select(DemandElement).where(DemandElement.type == "RESERVATION", DemandElement.material_id == M["JM-RES"])).scalars().all()
        assert {e.reference: e.qty for e in elements} == {J["rsv1"]: 50, J["rsv2"]: 60}
    # validation
    for body, code in (({"qty": "1", "needDate": "2026-11-20"}, "COST_OBJECT_REQUIRED"), ({"qty": "1", "needDate": "2026-11-01", "costObject": "COST_CENTER:6100"}, "RULE_VIOLATION"),
                       ({"qty": "1", "needDate": "2026-11-20", "costObject": "COST_CENTER:9999"}, "UNKNOWN_COST_OBJECT")):
        _problem(client.post("/v1/reservations", json={"material": "JM-RES", "plant": P1, "storageLocation": "0001", **body}, headers=recv), 422, code)
    # MRP counts the open reservations as gross demand (TD 9.1) and the stock card shows them
    result = _mrp(client, login)
    assert result["gross"] == 110 and result["on_hand"] == 80 and result["net"] == 30
    card = client.get(f"/v1/stock/materials/JM-RES?plant={P1}", headers=_h(login, "ic1")).json()
    profile = card["requirements"][0]
    assert profile["demand"] == "110" and profile["reserved"] == "110" and {x["type"] for x in profile["requirements"]} == {"RESERVATION"}
    assert {r["number"] for r in card["reservations"]} == {J["rsv1"], J["rsv2"]} and profile["buckets"][-1]["projected"] == "-30"
    live = _mrp(client, login, "NET_CHANGE")           # the first live run plans the shortage
    assert live["net"] == 30


def test_16_cancel_releases_the_demand_and_net_change_replans(env, client, login):
    recv = _h(login, "recv")
    outsider = client.post(f"/v1/reservations/{J['rsv2']}/cancel", json={"reason": "not mine"}, headers=_h(login, "reader"))
    assert outsider.status_code == 403                                                           # neither requester nor a stock poster
    _pin(TODAY, 12)
    cancelled = client.post(f"/v1/reservations/{J['rsv2']}/cancel", json={"reason": "Customer order withdrawn"}, headers=recv)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED" and cancelled.json()["openQty"] == "60"
    _problem(client.post(f"/v1/reservations/{J['rsv2']}/cancel", json={"reason": "again please"}, headers=recv), 409, "ILLEGAL_TRANSITION")
    assert _mrp(client, login)["gross"] == 50
    nc = _mrp(client, login, "NET_CHANGE")             # the cancel changed the demand after the last live run: the material is replanned
    assert nc["gross"] == 50 and nc["net"] == 0
    with tenant_tx(env.tenant_id) as s:
        element = s.execute(select(DemandElement).where(DemandElement.reference == J["rsv2"])).scalar_one()
        assert element.qty == 0 and element.changed_at is not None


def test_17_partial_and_full_issue(env, client, login):
    recv = _h(login, "recv")
    _pin(TODAY, 13)
    part = client.post(f"/v1/reservations/{J['rsv1']}/issue", json={"qty": "20"}, headers=recv)
    assert part.status_code == 200, part.text
    assert part.json()["status"] == "PARTIALLY_ISSUED" and part.json()["issuedQty"] == "20" and part.json()["openQty"] == "30"
    assert _on_hand(client, login, "JM-RES") == 60
    _problem(client.post(f"/v1/reservations/{J['rsv1']}/issue", json={"qty": "40"}, headers=recv), 422, "EXCEEDS_RESERVATION")
    assert _mrp(client, login)["gross"] == 30                                                  # the issued part left the demand with the stock
    done = client.post(f"/v1/reservations/{J['rsv1']}/issue", headers={**recv, "Idempotency-Key": "inv-issue-rest"})
    assert done.status_code == 200 and done.json()["status"] == "ISSUED" and done.json()["openQty"] == "0" and len(done.json()["issues"]) == 2
    assert client.post(f"/v1/reservations/{J['rsv1']}/issue", headers=recv).status_code == 409
    assert _on_hand(client, login, "JM-RES") == 30
    ledger = client.get(f"/v1/stock/movements?reference={J['rsv1']}", headers=_h(login, "ic1")).json()["items"]
    assert [m["movementType"] for m in ledger] == ["201", "201"] and sorted(m["qty"] for m in ledger) == ["-20", "-30"] and sum(m["valueMinor"] for m in ledger) == -1_000_000
    assert _mrp(client, login)["gross"] == 0
    turns = next(i for i in client.get("/v1/kpis?module=M09&trend=false", headers=_h(login, "ic1")).json()["items"] if i["code"] == "M09.INVENTORY_TURNS")
    assert turns["detail"]["issuesMinor"] == 1_000_000 and Decimal(turns["value"]) > 0       # 50 pieces issued at 200.00 over the average own stock value
    with tenant_tx(env.tenant_id) as s:
        assert s.execute(select(IntegrationMessage.status).where(IntegrationMessage.idempotency_key == f"RSV|{J['rsv1']}|50")).scalar_one() == "POSTED"
    # ABC selection of a count: by the value issued in the last 12 months only the reserved-and-issued material is class A
    abc = client.post("/v1/physical-inventories", json={"plant": P1, "storageLocation": "0001", "abc": ["A"]}, headers=_h(login, "ic1"))
    assert abc.status_code == 201 and [l["material"] for l in abc.json()["lines"]] == ["JM-RES"] and abc.json()["scope"]["abc"] == ["A"]
    assert client.post(f"/v1/physical-inventories/{abc.json()['number']}/cancel", json={"reason": "ABC selection check only"}, headers=_h(login, "ic1")).status_code == 200
    _problem(client.post("/v1/physical-inventories", json={"plant": P1, "storageLocation": "0001", "abc": ["Z"]}, headers=_h(login, "ic1")), 422, "VALIDATION_FAILED")
    listing = client.get(f"/v1/reservations?status=ISSUED,CANCELLED&mine=true", headers=recv).json()
    assert {r["number"] for r in listing["items"]} == {J["rsv1"], J["rsv2"]}


def test_18_rule_blocks_unavailable_reservation_and_the_expiry_job(env, client, login):
    admin = _h(login, "admin")
    _pin(TODAY, 9)
    # an effective-dated rule version: an unavailable quantity is refused. A malformed version is not accepted.
    bad = client.post("/v1/admin/rules", json={"key": "INVENTORY-POSTING", "version": "9.bad", "effective_from": TODAY.isoformat(),
                                               "body": {"approvalBands": [{"upTo": 100, "chain": ["INVENTORY_CONTROLLER"]}]}}, headers=admin)
    _problem(bad, 422, "RULE_INVALID")
    ok = client.post("/v1/admin/rules", json={"key": "INVENTORY-RESERVATION", "version": "2026.2-BLOCK", "effective_from": TODAY.isoformat(),
                                              "body": {"blockWhenUnavailable": True, "graceDays": 3}, "description": "Refuse unavailable reservations"}, headers=admin)
    assert ok.status_code == 201, ok.text
    recv = _h(login, "recv")
    refused = _problem(client.post("/v1/reservations", json={"material": "JM-RES", "plant": P1, "storageLocation": "0001", "qty": "500", "needDate": "2026-11-12",
                                                               "costObject": "COST_CENTER:6100"}, headers=recv), 422, "INSUFFICIENT_STOCK")
    assert refused["availableQty"] == "30" and refused["ruleRef"].startswith("INVENTORY-RESERVATION@2026.2-BLOCK")
    kept = client.post("/v1/reservations", json={"material": "JM-RES", "plant": P1, "storageLocation": "0001", "qty": "10", "needDate": "2026-11-10",
                                                   "costObject": "COST_CENTER:6100"}, headers=recv)
    assert kept.status_code == 201
    number = kept.json()["number"]
    # the nightly job expires it once the need date plus the grace (3 days) has passed
    _pin(date(2026, 11, 12), 3)
    early = jobs.run_now(env.tenant_id, "inventory-reservations", requested_by="u:test")      # 12 Nov: the grace runs to 13 Nov
    assert early["status"] == "SUCCESS" and early["result"]["expired"] == []
    assert client.get(f"/v1/reservations/{number}", headers=recv).json()["status"] == "OPEN"
    _pin(date(2026, 11, 15), 3)
    dry = jobs.run_now(env.tenant_id, "inventory-reservations", requested_by="u:test", dry_run=True)
    assert dry["status"] == "SUCCESS" and dry["result"]["expired"] == [number]
    assert client.get(f"/v1/reservations/{number}", headers=recv).json()["status"] == "OPEN"        # a dry run changes nothing
    outcome = jobs.run_now(env.tenant_id, "inventory-reservations", requested_by="u:test")
    assert outcome["status"] == "SUCCESS" and outcome["result"]["expired"] == [number]
    expired = client.get(f"/v1/reservations/{number}", headers=recv).json()
    assert expired["status"] == "EXPIRED" and "Expired" in expired["closedReason"]
    _pin(TODAY, 14)


def test_19_rules_endpoint_and_an_effective_dated_posting_rule(env, client, login):
    ic1, admin = _h(login, "ic1"), _h(login, "admin")
    rules = client.get("/v1/inventory/rules", headers=ic1).json()
    assert rules["posting"]["ref"].startswith("INVENTORY-POSTING@") and rules["posting"]["body"]["autoPostBelowMinor"] == 2_500_000
    assert rules["count"]["body"]["qtyTolerancePct"] == "2" and rules["reservation"]["ref"].startswith("INVENTORY-RESERVATION@2026.2-BLOCK")
    assert "SCRAP" in rules["enums"]["postingTypes"] and rules["enums"]["movementTypes"]["311"] and rules["me"]["canApprove"] is True
    # from tomorrow nothing posts by itself any more
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    ok = client.post("/v1/admin/rules", json={"key": "INVENTORY-POSTING", "version": "2026.2-STRICT", "effective_from": tomorrow,
                                              "body": {"autoPostBelowMinor": 0}, "description": "Every posting is approved"}, headers=admin)
    assert ok.status_code == 201, ok.text
    _pin(TODAY, 15)
    today_post = _posting(client, login, {"type": "BLOCK", "plant": P1, "reasonCode": "DAMAGED", "reason": "Dented drums", "lines": [_line("JM-A", 1)], "submit": True}, "recv")
    assert today_post["status"] == "POSTED"                                    # today's rule version still applies
    _pin(TODAY + timedelta(days=1), 9)
    strict = client.post("/v1/stock-postings", json={"type": "BLOCK", "plant": P1, "reasonCode": "DAMAGED", "reason": "Dented drums",
                                                      "lines": [_line("JM-A", 1)], "submit": True}, headers=_h(login, "recv")).json()
    assert strict["status"] == "SUBMITTED" and strict["rule"] == "INVENTORY-POSTING@2026.2-STRICT"
    assert client.post(f"/v1/stock-postings/{strict['number']}/cancel", json={"reason": "Test only, rule check"}, headers=_h(login, "recv")).status_code == 200
    _pin(TODAY, 16)


# ================================================================ 20. audit, events, ledger consistency, isolation
def test_20_audit_events_ledger_and_isolation(env, client, login):
    ic1 = _h(login, "ic1")
    audit = client.get(f"/v1/audit/STOCK_POSTING/{J['scrap_a']}", headers=ic1).json()
    actions = [e["action"] for e in audit]
    assert actions[:2] == ["CREATED", "SUBMIT"] and {"TASK_CREATED", "APPROVAL_APPROVE", "APPROVE", "POST"} <= set(actions) and audit[-1]["action"] in ("POST", "ERP_POSTED")
    approve = next(e for e in audit if e["action"] == "APPROVE")
    assert approve["before"]["status"] == "SUBMITTED" and approve["after"]["status"] == "APPROVED" and approve["ruleSetVersion"].startswith("INVENTORY-POSTING@")
    count_trail = client.get(f"/v1/audit/PHYSICAL_INVENTORY/{J['count']}", headers=ic1).json()
    count_actions = [e["action"] for e in count_trail]
    assert count_actions[0] == "CREATED" and {"START", "COUNTS_ENTERED", "COMPLETE", "SUBMIT", "APPROVE", "POST"} <= set(count_actions)
    approvals = client.get(f"/v1/documents/STOCK_POSTING/{J['scrap_hv']}/approvals", headers=ic1).json()
    assert approvals and len(approvals) >= 2
    assert client.get(f"/v1/lineage/STOCK_POSTING/{J['transfer']}", headers=ic1).status_code == 200
    assert client.get("/v1/audit/verify", headers=_h(login, "admin")).json()["valid"] is True
    with tenant_tx(env.tenant_id) as s:
        topics = {t for (t,) in s.execute(select(OutboxEvent.topic).distinct())}
        assert {"stock_posting.submitted", "stock_posting.approved", "stock_posting.posted", "stock_posting.rejected", "physical_inventory.posted",
                "stock_reservation.created", "stock_reservation.issued", "stock_reservation.cancelled"} <= topics
    alerts = client.get("/v1/stock/alerts?type=NEGATIVE_DRIFT&limit=50", headers=ic1).json()
    assert alerts["items"] == []                                            # nothing but postings changed stock
    # another tenant sees none of it
    other = login("admin")      # the Axion tenant (its own document numbers may coincide with ours, its ids never do)
    assert client.get(f"/v1/stock-postings/{J['transfer_id']}", headers=other).status_code == 404
    assert client.get(f"/v1/reservations/{J['rsv1_id']}", headers=other).status_code == 404
    assert all(i["id"] != J["transfer_id"] for i in client.get("/v1/stock-postings?limit=200", headers=other).json()["items"])

