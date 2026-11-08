"""Flow-audit fixes for sourcing, suppliers, contracts and purchase orders (M05 to M08; docs/PIC_Workflow_Flow_Audit.md §3 #3, #9, #10,
#11, #14 and the Workflow Guide's Appendix A B1 to B9).

Every test that writes runs in one AXN transaction that is rolled back at the end, so the signature case (RFQ-2231, SA-5520/5521, PO-77410)
and the KPIs other files check never change. API tests only take paths that are refused before anything is written, or read.
"""
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuditEvent, BankChangeRequest, Contract, ContractLine, FxRate, IntegrationMessage, Material, Notification, NumberRange, OutboxEvent,
    PlannedOrder, PriceValidity, PurchaseOrder, PurchasingGroup, PurchasingOrg, Requisition, SanctionEntry, SourcingEvent, Supplier,
    SupplierCategoryStatus, SupplierMasterChange, Task, Tenant, Timer,
)
from app.pic.platform import abac, clock, workflow
from app.pic.platform.auth import Principal, scopes_for
from app.pic.platform.errors import Problem
from app.pic.seed.axion import ROLE_USER
from app.pic.services import contract as contract_svc
from app.pic.services import (
    jobs, master_changes, order, rebates, requisition, risk, source, sourcing, sourcing_notify, supplier as supplier_svc,
)

IST = clock.IST
PRICE_ONLY = [{"code": "PRICE_TCO", "name": "Price / TCO", "weight": 100}]
OPEN_SHARES = {"max_suppliers": 2, "max_share": "1", "min_share": "0"}


class _Rollback(Exception):
    pass


def _tid():
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()


@contextmanager
def rolled_back(when: datetime = None):
    if when is not None:
        clock.set_pinned(when)
    try:
        with pytest.raises(_Rollback):
            with tenant_tx(_tid()) as s:
                yield s
                raise _Rollback()
    finally:
        clock.set_pinned(None)


def act(s, who: str) -> AppUser:
    user = s.execute(select(AppUser).where(AppUser.email == f"{who}@axion.example")).scalar_one()
    s.info["principal"] = Principal(user_id=user.id, tenant_id=user.tenant_id, tenant_code="AXN", email=user.email, name=user.full_name,
                                    roles=list(user.roles), scopes=scopes_for(list(user.roles)), attributes=user.attributes or {},
                                    supplier_id=user.supplier_id)
    s.info["user_id"] = user.id
    return user


def act_as(s, roles: list, attributes: dict, name: str = "Scoped user"):
    """A principal without a user row (its attributes come from the token): a user scoped by plant / category / company code."""
    uid = uuid.uuid4()
    s.info["principal"] = Principal(user_id=uid, tenant_id=_tid(), tenant_code="AXN", email=f"{uid.hex[:8]}@axion.example", name=name,
                                    roles=roles, scopes=scopes_for(roles), attributes=attributes, supplier_id=None)
    s.info["user_id"] = uid
    return uid


def problem(fn, *args, **kwargs) -> Problem:
    with pytest.raises(Problem) as exc:
        fn(*args, **kwargs)
    return exc.value


def sup(s, code: str) -> Supplier:
    return s.execute(select(Supplier).where(Supplier.code == code)).scalar_one()


def mat(s, number: str) -> Material:
    return s.execute(select(Material).where(Material.number == number)).scalar_one()


def contract_of(s, number: str) -> Contract:
    return s.execute(select(Contract).where(Contract.number == number)).scalar_one()


def approve_all(s, object_id, comment: str = "Approved") -> int:
    done = 0
    for _ in range(12):
        tasks = s.execute(select(Task).where(Task.object_id == object_id, Task.status == "OPEN").order_by(Task.sequence)).scalars().all()
        if not tasks:
            return done
        progressed = False
        for task in tasks:
            people = ROLE_USER.get(task.candidate_role) or [u.email.split("@")[0] for u in s.execute(
                select(AppUser).where(AppUser.roles.any(task.candidate_role), AppUser.supplier_id.is_(None), AppUser.active.is_(True))
                .order_by(AppUser.email)).scalars()]
            people = people if isinstance(people, list) else [people]
            for who in people:
                act(s, who)
                if workflow.can_work(s.info["principal"], task) is None:
                    workflow.complete(s, task.id, "APPROVE", comment)
                    done += 1
                    progressed = True
                    break
        if not progressed:
            return done
    return done


def live_contract(s, supplier_code: str, material: str, price_minor: int, *, valid_to: date = None, number: str = None, qty: str = "10000") -> Contract:
    """An ACTIVE scheduling agreement with one published price (no quota arrangement)."""
    today = clock.today()
    c = Contract(tenant_id=_tid(), number=number or f"T-{uuid.uuid4().hex[:6]}", type="SCHEDULING_AGREEMENT", title="flow fix test",
                 supplier_id=sup(s, supplier_code).id, company_code="1000", status="ACTIVE", valid_from=today - timedelta(days=10),
                 valid_to=valid_to or today + timedelta(days=300), currency="INR", payment_terms="N60", over_tolerance_pct=Decimal(2),
                 owner_id=s.info["user_id"])
    s.add(c)
    s.flush()
    line = ContractLine(tenant_id=c.tenant_id, contract_id=c.id, line_no=10, material_id=mat(s, material).id, description="test line",
                        plant="P100", uom="EA", target_qty=Decimal(qty))
    s.add(line)
    s.flush()
    s.add(PriceValidity(tenant_id=c.tenant_id, contract_line_id=line.id, valid_from=c.valid_from, valid_to=c.valid_to,
                        unit_price_minor=price_minor, reason="INITIAL", published=True))
    s.flush()
    return c


def approved_pr(s, material: str, qty: str = "50", price: int = 21500) -> Requisition:
    act(s, "requester")
    pr = requisition.create(s, origin="MANUAL", purpose_code="BUFFER_BUILD", purpose_text="flow fix test", plant="P100",
                            lines=[{"item_type": "MATERIAL", "purchase_type": "STOCK", "material": material, "qty": qty, "price_est_minor": price,
                                    "need_date": (clock.today() + timedelta(days=30)).isoformat(), "storage_location": "0001"}])
    requisition.submit(s, pr)
    approve_all(s, pr.id)
    return pr


def manual_po(s, **kw) -> PurchaseOrder:
    act(s, kw.pop("who", "buyer"))
    args = dict(supplier_code="KD002", plant="P100", purpose_code="MAINTENANCE",
                reason="Urgent repair part: the breakdown cannot wait for a requisition", currency=None,
                lines=[{"material": "DC-331", "qty": "10", "unitPriceMinor": 21000, "needDate": (clock.today() + timedelta(days=20)).isoformat()}])
    args.update(kw)
    return order.create_manual(s, **args)


def last_event(s, topic: str, object_id) -> OutboxEvent:
    return s.execute(select(OutboxEvent).where(OutboxEvent.topic == topic, OutboxEvent.object_id == object_id)
                     .order_by(OutboxEvent.occurred_at.desc())).scalars().first()


def notes(s, kind: str, ref: str = None) -> list[Notification]:
    query = select(Notification).where(Notification.kind == kind)
    if ref:
        query = query.where(Notification.object_ref == ref)
    return s.execute(query).scalars().all()


def bank(s, code: str):
    return supplier_svc.request_bank_change(s, sup(s, code), bank_account="123456789012", ifsc="HDFC0001234", holder_name="Test Holder")


# ================================================================ 1 (audit #3) bank-change guards shared with onboarding
def test_flowfix2_bank_change_refused_while_one_is_pending_and_on_blocked_or_exited_supplier():
    with rolled_back() as s:
        act(s, "supplier.manager")
        first = bank(s, "TF001")
        assert first.status == "PENDING_CALLBACK"
        again = problem(bank, s, "TF001")
        assert (again.status, again.code) == (409, "BANK_CHANGE_PENDING") and first.number in again.detail
        blocked = problem(bank, s, "ZAT006")
        assert (blocked.status, blocked.code) == (409, "SUPPLIER_BLOCKED")
        exited = sup(s, "SLA003")
        exited.status = "EXITED"
        s.flush()
        refused = problem(bank, s, "SLA003")
        assert (refused.status, refused.code) == (409, "SUPPLIER_INACTIVE")
        assert s.execute(select(BankChangeRequest).where(BankChangeRequest.supplier_id == exited.id,
                                                         BankChangeRequest.status == "PENDING_CALLBACK")).first() is None


def test_flowfix2_bank_change_route_answers_409_for_a_blocked_supplier(client, login):
    r = client.post("/v1/suppliers/ZAT006/bank-changes", headers=login("supplier.manager"),
                    json={"bank_account": "123456789012", "ifsc": "HDFC0001234", "holder_name": "Zenith Alloy Traders"})
    assert r.status_code == 409 and r.json()["code"] == "SUPPLIER_BLOCKED", r.text


# ================================================================ 2 (audit #9, B4) deterministic source determination
def test_flowfix2_source_determination_takes_the_lowest_valid_price_then_earliest_end():
    with rolled_back() as s:
        act(s, "buyer")
        dearer = live_contract(s, "TF001", "DC-331", 210000, number="T-A")
        cheaper = live_contract(s, "KD002", "DC-331", 199000, number="T-B")
        material = mat(s, "DC-331")
        for _ in range(3):  # always the same answer
            d = source.determine(s, material, "P100", clock.today() + timedelta(days=20), Decimal(10))
            assert d.method == "CONTRACT" and d.allocations[0].contract_id == cheaper.id and d.allocations[0].unit_price_minor == 199000
        assert [c["contract"] for c in d.as_dict()["candidates"]] == ["T-B", "T-A"] and "lowest valid net price" in d.as_dict()["basis"]
        # the PO path uses the same choice
        pr = approved_pr(s, "DC-331")
        act(s, "buyer")
        po = order.create_from_requisition(s, requisition=pr.number, lines=[10])[0]
        assert po.supplier_id == sup(s, "KD002").id and po.contract_id == cheaper.id
        # same price: the contract that ends first; an ineligible supplier is skipped for the next candidate
        dearer.valid_to = clock.today() + timedelta(days=100)
        s.execute(select(PriceValidity).join(ContractLine, ContractLine.id == PriceValidity.contract_line_id)
                  .where(ContractLine.contract_id == dearer.id)).scalar_one().unit_price_minor = 199000
        s.flush()
        d = source.determine(s, material, "P100", clock.today() + timedelta(days=20), Decimal(10))
        assert d.allocations[0].contract_id == dearer.id
        s.execute(select(SupplierCategoryStatus).where(SupplierCategoryStatus.supplier_id == sup(s, "TF001").id)).scalar_one().status = "BLOCKED"
        s.flush()
        d = source.determine(s, material, "P100", clock.today() + timedelta(days=20), Decimal(10))
        assert d.allocations[0].contract_id == cheaper.id and {"supplier": "TF001", "status": "BLOCKED"} in d.excluded


# ================================================================ 3 (audit #10, B2) PO from a contract, a planned order, a manual PO; currency, org
def test_flowfix2_release_order_against_a_contract():
    with rolled_back() as s:
        act(s, "buyer")
        po = order.create_from_contract(s, contract_ref="SA-5520", lines=[{"line": 10, "qty": "20000"}])
        sa = contract_of(s, "SA-5520")
        assert po.origin == "CONTRACT" and po.contract_id == sa.id and po.supplier_id == sa.supplier_id
        assert po.purpose_code == "CONTRACT_RELEASE" and po.payment_terms == sa.payment_terms
        line = order.lines_of(s, po)[0]
        assert line.price_source == "CONTRACT" and line.contract_line_id is not None and line.requisition_id is None
        assert "SA-5520" in order.lineage_refs(s, po)
        too_much = problem(order.create_from_contract, s, contract_ref="SA-5520", lines=[{"line": 10, "qty": "900000"}])
        assert too_much.code == "RULE_VIOLATION" and "exceeds the contract quantity" in too_much.detail
        assert problem(order.create_from_contract, s, contract_ref="SA-5520", lines=[{"line": 99, "qty": "1"}]).code == "RULE_VIOLATION"


def test_flowfix2_manual_po_needs_reason_and_purpose_and_is_approved_by_bands():
    with rolled_back() as s:
        assert problem(manual_po, s, reason="urgent").code == "REASON_REQUIRED"
        assert problem(manual_po, s, purpose_code="").code == "RULE_VIOLATION"
        po = manual_po(s)
        assert po.origin == "MANUAL" and po.reason.startswith("Urgent repair") and po.status == "IN_APPROVAL" and po.touchless is False
        tasks = s.execute(select(Task).where(Task.object_id == po.id, Task.status == "OPEN")).scalars().all()
        assert tasks and all(po.created_by in (t.excluded_user_ids or []) for t in tasks)   # four-eyes: the buyer never approves it
        assert order.lines_of(s, po)[0].price_source == "MANUAL"
        free = problem(manual_po, s, lines=[{"description": "Spare belt", "qty": "2", "unitPriceMinor": 50000}])
        assert free.code == "VALIDATION_FAILED"   # free text needs a material group and an account assignment
        expense = manual_po(s, supplier_code="V-210111", lines=[{"description": "Spare belt", "materialGroup": "MRO", "qty": "2", "unitPriceMinor": 50000,
                                       "accountAssignmentType": "COST_CENTER", "accountAssignmentCode": "4100"}])
        assert order.lines_of(s, expense)[0].purchase_type == "EXPENSE"


def test_flowfix2_po_carries_currency_with_fx_rate_and_purchasing_org_from_org_masters():
    with rolled_back() as s:
        assert problem(manual_po, s, currency="XYZ").code == "UNKNOWN_CURRENCY"
        assert problem(manual_po, s, currency="USD").code == "FX_RATE_MISSING"
        s.add(FxRate(tenant_id=_tid(), from_ccy="USD", to_ccy="INR", rate=Decimal("83.25"), valid_from=clock.today() - timedelta(days=1), source="TEST"))
        s.flush()
        usd = manual_po(s, currency="USD", lines=[{"material": "DC-331", "qty": "10", "unitPriceMinor": 250}])
        assert usd.currency == "USD" and usd.fx_rate == Decimal("83.25") and usd.inherited["totalCompanyMinor"] == round(2500 * 83.25)
        assert order.company_value(usd) == round(2500 * 83.25)
        # no purchasing-organisation master: the company code; with D19 masters: the purchasing group of the plant
        assert usd.purch_org == "1000"
        s.add(PurchasingOrg(tenant_id=_tid(), code="PO10", name="Central purchasing", company_code="1000", active=True))
        s.add(PurchasingOrg(tenant_id=_tid(), code="PO20", name="Plant purchasing", company_code="1000", active=True))
        s.add(PurchasingOrg(tenant_id=_tid(), code="PX99", name="Other company", company_code="9999", active=True))
        s.add(PurchasingGroup(tenant_id=_tid(), code="G10", name="Hosur buyers", purchasing_org="PO20", plant="P100", active=True))
        s.flush()
        assert manual_po(s).purch_org == "PO20"
        assert manual_po(s, purchasing_org="PO10").purch_org == "PO10"
        assert problem(manual_po, s, purchasing_org="PX99").code == "PURCHASING_ORG_COMPANY_MISMATCH"


def test_flowfix2_po_from_a_planned_order_goes_through_its_mrp_requisition():
    with rolled_back() as s:
        template = s.execute(select(PlannedOrder).where(PlannedOrder.number == "PLO-55821")).scalar_one()
        planned = PlannedOrder(tenant_id=_tid(), number="PLO-T9001", mrp_run_id=template.mrp_run_id, material_id=mat(s, "DC-331").id, plant="P100",
                               storage_location=template.storage_location, qty=Decimal(40), need_date=clock.today() + timedelta(days=30),
                               release_date=clock.today() + timedelta(days=5), status="CREATED", source={}, exception_codes=[])
        s.add(planned)
        s.flush()
        act(s, "buyer")
        assert problem(order.create_from_planned_order, s, planned_order="PLO-T9001").code == "FORBIDDEN"   # converting is the MRP controller's
        user = act(s, "mrp.controller")
        s.info["principal"] = Principal(user_id=user.id, tenant_id=user.tenant_id, tenant_code="AXN", email=user.email, name=user.full_name,
                                        roles=["MRP_CONTROLLER", "BUYER"], scopes=scopes_for(["MRP_CONTROLLER", "BUYER"]),
                                        attributes={"plants": ["P100"]}, supplier_id=None)
        out = order.create_from_planned_order(s, planned_order="PLO-T9001")
        pr = s.execute(select(Requisition).where(Requisition.number == out["requisition"])).scalar_one()
        assert pr.origin == "MRP" and planned.status == "CONVERTED" and planned.requisition_id == pr.id
        if out["purchaseOrders"]:
            assert out["purchaseOrders"][0].origin == "REQUISITION"
        else:
            assert out["requisitionStatus"] in ("SUBMITTED", "IN_APPROVAL")


def test_flowfix2_po_create_api_takes_contract_planned_and_manual_sources(client, login):
    h = login("buyer")
    r = client.post("/v1/purchase-orders", headers=h, json={"source": {"type": "MANUAL"}, "supplierId": "KD002", "plant": "P100",
                                                            "purposeCode": "MAINTENANCE", "reason": "short",
                                                            "manualLines": [{"material": "DC-331", "qty": "1", "unitPriceMinor": 100}]})
    assert r.status_code == 422 and r.json()["code"] == "REASON_REQUIRED", r.text
    r = client.post("/v1/purchase-orders", headers=h, json={"source": {"type": "CONTRACT", "id": "SA-5520"},
                                                            "contractLines": [{"line": 10, "qty": "99999999"}]})
    assert r.status_code == 422 and "contract quantity" in r.json()["detail"], r.text
    r = client.post("/v1/purchase-orders", headers=h, json={"source": {"type": "PLANNED_ORDER", "id": "PLO-55821"}})
    assert r.status_code == 403 and "MRP controller" in r.json()["detail"], r.text   # converting is the MRP controller's step
    r = client.post("/v1/purchase-orders", headers=h, json={"source": {"type": "MANUAL"}, "supplierId": "KD002", "plant": "P100",
                                                            "purposeCode": "MAINTENANCE", "reason": "Breakdown spare without a requisition",
                                                            "currency": "XYZ", "manualLines": [{"material": "DC-331", "qty": "1", "unitPriceMinor": 100}]})
    assert r.status_code == 422 and r.json()["code"] == "UNKNOWN_CURRENCY", r.text


# ================================================================ 4 (audit #11, B1, B7) ABAC on PO create / release and supplier governance
def test_flowfix2_abac_po_create_and_release_check_plant():
    with rolled_back() as s:
        act_as(s, ["BUYER"], {"plants": ["P200"]}, "Pune buyer")
        denied = problem(order.create_manual, s, supplier_code="KD002",
                         plant="P100", purpose_code="MAINTENANCE", reason="Breakdown spare without a requisition",
                         lines=[{"material": "DC-331", "qty": "10", "unitPriceMinor": 21000}])
        assert (denied.status, denied.code) == (403, "FORBIDDEN") and denied.extra.get("action") == "PO_CREATE"
        po = manual_po(s)
        assert po.status == "IN_APPROVAL"
        act_as(s, ["BUYER", "PROCUREMENT_HEAD"], {"plants": ["P200"]}, "Pune approver")
        refused = problem(order._release, s, po)
        assert (refused.status, refused.code) == (403, "FORBIDDEN") and refused.extra.get("action") == "PO_RELEASE"
        act_as(s, ["BUYER"], {"plants": ["P100"], "value_limit_minor": 100}, "Low-limit releaser")
        over = problem(order._release, s, po)
        assert over.code == "VALUE_LIMIT_EXCEEDED"


def test_flowfix2_abac_scopes_supplier_master_and_bank_changes_to_the_supplier():
    with rolled_back() as s:
        tf = sup(s, "TF001")  # ALU-DIECAST, orders in company code 1000
        act_as(s, ["SUPPLIER_MANAGER"], {"categories": ["MRO"]}, "MRO-only supplier manager")
        refused = problem(master_changes.request_change, s, tf, field_group="CONTACT", values={"email": "new@tf.example"}, reason="test change")
        assert (refused.status, refused.code) == (403, "FORBIDDEN") and "category" in refused.detail
        assert problem(bank, s, "TF001").status == 403
        # an in-scope request, then an out-of-scope approver of the master change task
        act(s, "procurement.head")
        change = master_changes.request_change(s, tf, field_group="CONTACT", values={"email": "new@tf.example"}, reason="test change")
        task = s.execute(select(Task).where(Task.object_id == change.id, Task.candidate_role == "SUPPLIER_MANAGER")).scalar_one()
        act_as(s, ["SUPPLIER_MANAGER"], {"categories": ["MRO"]}, "MRO-only supplier manager")
        assert problem(workflow.complete, s, task.id, "APPROVE", "ok").code == "FORBIDDEN"
        # bank change approved by a finance controller of another company code: refused; of company code 1000: allowed
        act(s, "procurement.head")
        change = bank(s, "TF001")
        act(s, "supplier.manager")
        supplier_svc.callback_verify(s, change, "called back on the number on record")
        task = s.execute(select(Task).where(Task.object_id == change.id, Task.status == "OPEN")).scalars().first()
        act_as(s, ["FINANCE_CONTROLLER"], {"company_codes": ["9999"]}, "Other company FC")
        assert problem(workflow.complete, s, task.id, "APPROVE", "ok").code == "FORBIDDEN"
        act_as(s, ["FINANCE_CONTROLLER"], {"company_codes": ["1000"]}, "Company 1000 FC")
        workflow.complete(s, task.id, "APPROVE", "ok")
        assert abac.supplier_scope(s, tf) == {"category": ["ALU-DIECAST"], "company_code": ["1000"]}
        # a supplier without any contract or order is scoped to every company code of the tenant: another company's controller is refused
        fresh = Supplier(tenant_id=_tid(), code="T-NEW1", legal_name="Fresh Castings Pvt Ltd", status="ACTIVE", payment_terms="N60")
        s.add(fresh)
        s.flush()
        s.add(SupplierCategoryStatus(tenant_id=_tid(), supplier_id=fresh.id, category="ALU-DIECAST", status="QUALIFIED"))
        s.flush()
        assert abac.supplier_scope(s, fresh) == {"category": ["ALU-DIECAST"], "company_code": ["1000"]}
        act_as(s, ["FINANCE_CONTROLLER"], {"company_codes": ["9999"]}, "Other company FC")
        assert problem(abac.authorize_supplier, s, s.info["principal"], "SUPPLIER_BANK_CHANGE", fresh).code == "FORBIDDEN"


# ================================================================ 5 (audit #14) invited suppliers are notified
def _event(s, type_: str = "RFQ") -> SourcingEvent:
    act(s, "category.head")
    return sourcing.create_event(s, type=type_, title=f"flow fix {type_}", category="ALU-DIECAST",
                                 lines=[{"requisition": "REQ-2312", "line": 10, "annual_qty": "20000", "monthly_qty": "2000"}], criteria=PRICE_ONLY,
                                 invitees=[{"supplier": "TF001"}, {"supplier": "KD002"}], close_at=datetime(2029, 3, 8, 17, tzinfo=IST),
                                 baseline_method="BUDGET", baseline_price_minor=42000, constraints=OPEN_SHARES)


def test_flowfix2_invited_suppliers_notified_at_publish_extension_and_new_round():
    with rolled_back(datetime(2029, 3, 1, 10, tzinfo=IST)) as s:
        event = _event(s)
        sourcing.publish(s, event)
        sourcing_notify._invited(s, last_event(s, "sourcing.event.published", event.id))
        invited = notes(s, "SOURCING_INVITED", event.number)
        emails = {s.get(AppUser, n.user_id).email for n in invited}
        assert {"tf.sales@axion.example", "kd.sales@axion.example"} <= emails and "sla.sales@axion.example" not in emails
        assert all("Bids close" in n.body for n in invited)
        refused = problem(sourcing.extend_deadline, s, event, datetime(2029, 3, 7, 17, tzinfo=IST), "earlier is never allowed")
        assert refused.code == "RULE_VIOLATION"
        sourcing.extend_deadline(s, event, datetime(2029, 3, 12, 17, tzinfo=IST), "Suppliers asked for more time for samples")
        assert event.close_at == datetime(2029, 3, 12, 17, tzinfo=IST)
        assert s.execute(select(Timer).where(Timer.object_id == event.id, Timer.kind == "SOURCING_CLOSE", Timer.due_at == event.close_at)).first()
        sourcing_notify._deadline_extended(s, last_event(s, "sourcing.deadline.extended", event.id))
        assert len(notes(s, "SOURCING_DEADLINE_EXTENDED", event.number)) >= 2
        assert s.execute(select(AuditEvent).where(AuditEvent.object_id == event.id, AuditEvent.action == "DEADLINE_EXTENDED")).first()


# ================================================================ 6 (B3) contract consumption checked again at release
def test_flowfix2_contract_quantity_rechecked_at_release():
    with rolled_back() as s:
        act(s, "buyer")
        po = order.create_from_contract(s, contract_ref="SA-5520", lines=[{"line": 10, "qty": "20000"}])
        assert po.status == "IN_APPROVAL"
        line = s.execute(select(ContractLine).where(ContractLine.contract_id == contract_of(s, "SA-5520").id)).scalar_one()
        released, _ = contract_svc.live_consumption(s, line)
        line.target_qty = released + Decimal(100)   # the contract was used up by other releases meanwhile
        s.flush()
        refused = problem(approve_all, s, po.id)
        assert refused.code == "CONTRACT_EXHAUSTED" and "already released" in refused.detail
        assert po.status == "IN_APPROVAL"


def test_flowfix2_release_refused_when_contract_no_longer_live():
    with rolled_back() as s:
        act(s, "buyer")
        po = order.create_from_contract(s, contract_ref="SA-5520", lines=[{"line": 10, "qty": "20000"}])
        contract_of(s, "SA-5520").status = "TERMINATED"
        s.flush()
        assert problem(approve_all, s, po.id).code == "CONTRACT_NOT_LIVE"


# ================================================================ 7 (B5) RENEWED state, CONTRACT_EXPIRING, ERP outline agreement
def test_flowfix2_successor_renewal_turns_the_predecessor_renewed():
    with rolled_back() as s:
        act(s, "contract.manager")
        old = contract_of(s, "SA-5521")
        successor = contract_svc.renew_as_successor(s, old, reason="Renewal for next year", valid_from=clock.today())
        assert successor.renews_contract_id == old.id and successor.status == "DRAFT" and successor.number.startswith("SA-")
        assert problem(contract_svc.renew_as_successor, s, old, reason="again").code == "SUCCESSOR_EXISTS"
        successor.status = "ACTIVE"
        contract_svc._succeed(s, successor)
        assert old.status == "RENEWED"
        assert last_event(s, "contract.renewed", old.id).payload["successor"] == successor.number
        # a successor that starts later turns its predecessor RENEWED on its start date
        other = contract_of(s, "SA-5520")
        later = contract_svc.renew_as_successor(s, other, reason="Renewal for next year")
        assert later.valid_from == other.valid_to + timedelta(days=1)
        later.status = "ACTIVE"
        contract_svc._succeed(s, later)
        assert other.status == "ACTIVE"
        assert s.execute(select(Timer).where(Timer.kind == "CONTRACT_SUCCESSION", Timer.object_id == later.id)).first()
        contract_svc._succession_due(s, SimpleNamespace(object_id=later.id))
        assert other.status == "RENEWED"


def test_flowfix2_contract_expiring_notification_and_erp_outline_agreement():
    with rolled_back() as s:
        act(s, "contract.manager")
        sa = contract_of(s, "SA-5521")
        contract_svc._renewal_due(s, SimpleNamespace(object_id=sa.id))
        assert sa.status == "EXPIRING"
        contract_svc._notify_expiring(s, last_event(s, "contract.expiring", sa.id))
        emails = {s.get(AppUser, n.user_id).email for n in notes(s, "CONTRACT_EXPIRING", sa.number)}
        assert "contract.manager@axion.example" in emails
        def messages():
            return s.execute(select(IntegrationMessage).where(IntegrationMessage.message_type == "OUTLINE_AGREEMENT",
                                                              IntegrationMessage.object_id == sa.id)).scalars().all()
        result = contract_svc.post_to_erp(s, sa)
        posted = len(messages())
        message = next(m for m in messages() if m.erp_doc_no == result["erpDocument"])
        assert message.idempotency_key.startswith(f"1000|OA|SA-5521|v{sa.version}|") and message.payload["lines"][0]["line"] == 10
        assert result["status"] == "POSTED" and sa.erp_doc_no == message.erp_doc_no
        contract_svc.post_to_erp(s, sa)   # exactly once per content of a version
        assert len(messages()) == posted


# ================================================================ 8 (B6) number ranges per event type and contract type
def test_flowfix2_number_ranges_per_event_type_and_contract_type():
    with rolled_back(datetime(2029, 3, 1, 10, tzinfo=IST)) as s:
        assert _event(s, "RFQ").number.startswith("RFQ-")
        assert _event(s, "RFP").number.startswith("RFP-")
        assert _event(s, "RFI").number.startswith("RFI-")
        act(s, "contract.manager")
        kw = dict(title="numbering", supplier_id=sup(s, "HTS004").id, company_code="1000", valid_from=date(2029, 4, 1), valid_to=date(2030, 3, 31),
                  payment_terms="N45", incoterms=None, owner_id=s.info["user_id"], tolerances={})
        value = contract_svc.create_draft(s, type="VALUE_CONTRACT", lines=[{"description": "Tool polishing", "plant": "P100", "uom": "H",
                                                                            "target_qty": "100", "unit_price_minor": 300000}], **kw)
        nda = contract_svc.create_draft(s, type="NDA", lines=[], **kw)
        assert value.number.startswith("VC-") and nda.number.startswith("NDA-")
        # a tenant whose ranges predate the split keeps numbering from the original range
        s.execute(NumberRange.__table__.delete().where(NumberRange.object_type == "SOURCING_EVENT_RFI"))
        assert _event(s, "RFI").number.startswith("RFQ-")
        assert s.execute(select(SourcingEvent.number).where(SourcingEvent.number == "RFQ-2231")).scalar_one() == "RFQ-2231"


# ================================================================ 9 (B8) portal bank change; legal name and commercial terms changes
def test_flowfix2_supplier_requests_own_bank_change_from_portal(client, login):
    with rolled_back() as s:
        act(s, "tf.sales")
        change = bank(s, "TF001")
        assert change.status == "PENDING_CALLBACK" and change.requested_by == s.info["user_id"]
        assert notes(s, "CHANGE_REQUEST", "TF001")   # the supplier managers are told to call back
        assert problem(bank, s, "KD002").status == 403   # never another supplier's account
        act(s, "supplier.manager")
        supplier_svc.callback_verify(s, change, "called back on the number on record")
        assert change.status == "PENDING_APPROVAL"
        assert len(s.execute(select(Task).where(Task.object_id == change.id, Task.status == "OPEN")).scalars().all()) == 1  # dual approval chain
    assert client.get("/v1/portal/bank-changes", headers=login("tf.sales")).status_code == 200
    assert client.post("/v1/portal/bank-changes", headers=login("buyer"), json={}).status_code == 403


def test_flowfix2_legal_name_and_commercial_terms_change_through_governed_path():
    with rolled_back() as s:
        tf = sup(s, "TF001")
        act(s, "tf.sales")
        assert problem(master_changes.request_change, s, tf, field_group="COMMERCIAL", values={"paymentTerms": "N30"}, reason="shorter").status == 403
        legal = master_changes.request_change(s, tf, field_group="LEGAL_NAME", values={"legalName": "Trichy Forge Private Limited"},
                                              reason="Conversion to a private limited company")
        act(s, "procurement.head")
        assert problem(master_changes.request_change, s, tf, field_group="COMMERCIAL", values={"paymentTerms": "N61X"}, reason="bad").code == "VALIDATION_FAILED"
        terms = master_changes.request_change(s, tf, field_group="COMMERCIAL", values={"paymentTerms": "n45", "incoterms": "fca Trichy"},
                                              reason="Renegotiated terms")
        assert terms.before_masked == {"paymentTerms": tf.payment_terms, "incoterms": tf.incoterms}
        for change in (legal, terms):
            approve_all(s, change.id)
            assert change.status == "APPLIED", change.status
        assert tf.legal_name == "Trichy Forge Private Limited" and tf.payment_terms == "N45" and tf.incoterms == "FCA Trichy"
        keys = set(s.execute(select(IntegrationMessage.idempotency_key).where(IntegrationMessage.message_type == "SUPPLIER_MASTER",
                                                                              IntegrationMessage.object_id == tf.id)).scalars())
        assert {f"TF001|LEGAL_NAME|{legal.number}", f"TF001|COMMERCIAL|{terms.number}"} <= keys
        assert s.execute(select(AuditEvent).where(AuditEvent.object_id == tf.id, AuditEvent.action == "SCREENED")).first()  # legal name re-screened


# ================================================================ 10 (B9) scheduled jobs and PO reconciliation
def test_flowfix2_jobs_registered_for_risk_sanctions_rebates_offer_expiry():
    assert {"supplier-risk-scan", "sanctions-rescreen", "rebate-accrual", "bid-offer-expiry", "erp-reconciliation"} <= set(jobs.REGISTRY)
    with rolled_back() as s:
        act(s, "admin")
        assert "agreements" in rebates.accrue_all(s)
        assert isinstance(risk.scheduled_risk_scan(SimpleNamespace(session=s, dry_run=True))["suppliers"], int)
        s.add(SanctionEntry(tenant_id=_tid(), name=sup(s, "SLA003").legal_name, source="TEST-LIST"))
        s.flush()
        assert "SLA003" in supplier_svc.rescreen_sanctions(s, dry_run=True)["matches"]
        result = supplier_svc.rescreen_sanctions(s, sync=False)
        assert "SLA003" in result["blocked"] and sup(s, "SLA003").status == "BLOCKED"
        assert sup(s, "KD002").status == "ACTIVE" and "rescreenedAt" in sup(s, "KD002").screening


def test_flowfix2_offer_validity_expiry_flags_the_bid_and_tells_the_owner():
    from app.pic.models import Bid
    with rolled_back(datetime(2029, 3, 1, 10, tzinfo=IST)) as s:
        event = _event(s)
        sourcing.publish(s, event)
        act(s, "tf.sales")
        bid = sourcing.submit_bid(s, event, sup(s, "TF001"), [{"line": 10, "unit_price": "400", "payment_terms_days": 60, "lead_time_days": 14,
                                                                "capacity_per_month": "5000"}], valid_until=date(2029, 3, 20))
        clock.set_pinned(datetime(2029, 3, 8, 17, 5, tzinfo=IST))
        act(s, "category.head")
        sourcing.close(s, event)
        if event.unsealed_at is None:   # two-person opening
            act(s, "category.head")
            sourcing.open_bids(s, event)
            act(s, "procurement.head")
            sourcing.open_bids(s, event)
        assert s.get(Bid, bid.id).valid_until == date(2029, 3, 20)
        clock.set_pinned(datetime(2029, 3, 25, 10, tzinfo=IST))
        act(s, "admin")
        result = sourcing.expire_offers(s)
        assert result["count"] >= 1 and any(e["event"] == event.number for e in result["expired"])
        assert notes(s, "SOURCING_OFFER_EXPIRED", event.number)
        sourcing.expire_offers(s)
        assert len(s.execute(select(AuditEvent).where(AuditEvent.object_id == event.id, AuditEvent.action == "OFFER_EXPIRED")).scalars().all()) == 1
        assert s.get(Bid, bid.id) is not None


def test_flowfix2_erp_reconciliation_covers_purchase_orders():
    with rolled_back() as s:
        act(s, "buyer")
        po = order.create_from_contract(s, contract_ref="SA-5520", lines=[{"line": 10, "qty": "100"}])
        if po.status == "IN_APPROVAL":
            approve_all(s, po.id)
        assert po.status in order.PO_IN_ERP + ("TRANSMITTED",)
        items = order.reconcile_purchase_orders(s, "1000", "SAP_S4")
        assert ("PO_MISSING_IN_ERP", po.number) in {(i[0], i[1]) for i in items}
        order._post_po(s, last_event(s, "purchase_order.released", po.id))
        items = order.reconcile_purchase_orders(s, "1000", "SAP_S4")
        assert po.number not in {i[1] for i in items}
        run = order.add_reconciliation_items(s, None, "1000", "SAP_S4", items)
        assert run["purchaseOrderDifferences"] == len(items)
