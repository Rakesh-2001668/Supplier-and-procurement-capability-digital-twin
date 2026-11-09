"""Default decisions (docs/PIC_Default_Decisions.md): invoice value bands with the CFO, the expired-offer award block (D5), category ABAC on PO
create / release (D3), and the PO-from-planned-order (D1) and scoped-inbox (D2) defaults.

Service tests run in one AXN transaction that is rolled back at the end (orders, invoices, events, rule versions and the CFO users created inside it),
so the signature case and the AP-only approval of AXN never change. Tenants created to check the new-tenant default (BNDT*, BNDP1) persist, like the
tenants of test_admin_enterprise.py.
"""
import argparse
import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuditEvent, AwardDecision, Invoice, InvoiceException, Material, OutboxEvent, RuleSet, SourcingEvent, Supplier, Task, Tenant, Timer,
)
from app.pic.platform import abac, clock, p2p_defaults, sourcing_defaults, workflow
from app.pic.platform.auth import ROLE_SCOPES, Principal, scopes_for
from app.pic.platform.errors import Problem
from app.pic.seed import reference
from app.pic.seed.axion import ROLE_USER
from app.pic.services import admin as admin_svc, order, payables, receiving, requisition, sourcing

IST = clock.IST
L = 100_000 * 100           # one lakh rupees in paise
CR = 100 * L                # one crore
BANDS = p2p_defaults.INVOICE_APPROVAL_BANDS
FC, CFO = "FINANCE_CONTROLLER", "CFO"


class _Rollback(Exception):
    pass


def _axn():
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()


@pytest.fixture
def tx(database):
    """One AXN transaction that always rolls back."""
    with pytest.raises(_Rollback):
        with tenant_tx(_axn()) as s:
            yield s
            raise _Rollback
    clock.set_pinned(None)


def _user(s, local: str) -> AppUser:
    return s.execute(select(AppUser).where(AppUser.email == f"{local}@axion.example")).scalar_one()


def _as(s, local: str) -> AppUser:
    user = _user(s, local)
    s.info["principal"] = Principal(user.id, user.tenant_id, "AXN", user.email, user.full_name, list(user.roles), scopes_for(list(user.roles)),
                                    user.attributes or {}, user.supplier_id)
    s.info["user_id"] = user.id
    from app.pic.platform import delegation as platform_delegation
    s.info.pop(platform_delegation.CACHE_KEY, None)
    return user


def _as_roles(s, roles: list, attributes: dict = None) -> Principal:
    uid = uuid.uuid4()
    p = Principal(uid, _axn(), "AXN", f"{uid.hex[:8]}@axion.example", "Scoped user", roles, scopes_for(roles, s), attributes or {}, None)
    s.info["principal"], s.info["user_id"] = p, uid
    return p


def _add_user(s, local: str, roles: list, attributes: dict = None) -> AppUser:
    user = AppUser(tenant_id=_axn(), email=f"{local}@axion.example", full_name=local.replace(".", " ").title(), password_hash="x", roles=roles,
                   attributes=attributes or {}, mfa_enrolled=True)
    s.add(user)
    s.flush()
    return user


def _problem(fn, *args, **kwargs) -> Problem:
    with pytest.raises(Problem) as exc:
        fn(*args, **kwargs)
    return exc.value


def _rule(s, key: str, body: dict, company_code: str = None) -> None:
    s.add(RuleSet(tenant_id=_axn(), key=key, version=f"BND-{uuid.uuid4().hex[:6]}", company_code=company_code,
                  effective_from=clock.today() - timedelta(days=1), body=body, description="approval bands test"))
    s.flush()


def _approve_all(s, object_id) -> None:
    for _ in range(12):
        tasks = s.execute(select(Task).where(Task.object_id == object_id, Task.status == "OPEN").order_by(Task.sequence)).scalars().all()
        if not tasks:
            return
        for task in tasks:
            who = ROLE_USER[task.candidate_role]
            for local in who if isinstance(who, list) else [who]:
                _as(s, local)
                if workflow.can_work(s.info["principal"], task) is None:
                    workflow.complete(s, task.id, "APPROVE", "Approved")
                    break


def _po(s, qty: int = 40):
    """Fasteners from Trichy Forge (one-time-vendor exception), approved, confirmed and received."""
    _as(s, "buyer")
    pr = requisition.create(s, origin="MANUAL", purpose_code="BUFFER_BUILD", purpose_text="Approval bands test", plant="P100",
                            lines=[{"item_type": "MATERIAL", "purchase_type": "STOCK", "material": "FK-M8-50", "qty": str(qty), "price_est_minor": 1250,
                                    "need_date": (clock.today() + timedelta(days=30)).isoformat(), "storage_location": "0001"}])
    requisition.submit(s, pr)
    _approve_all(s, pr.id)
    _as(s, "buyer")
    po = order.create_from_requisition(s, requisition=pr.number, lines=[10], supplier_code="TF001",
                                       one_time_vendor_reason="Approval bands test purchase of fasteners: one-time exception")[0]
    _approve_all(s, po.id)
    _as(s, "tf.sales")
    order.confirm(s, po, "CONFIRMED")
    _as(s, "receiver")
    receiving.post_gr(s, po, lines=[{"line": 10, "qty": str(qty)}])
    return po


def _invoice(s, gross_minor: int, qty: int = 40) -> Invoice:
    """A matched invoice whose gross is set to ``gross_minor`` (the band is chosen by the gross in company currency)."""
    po = _po(s, qty)
    _as(s, "tf.sales")
    invoice = payables.capture(s, supplier="TF001", supplier_invoice_no=f"BND/{uuid.uuid4().hex[:8]}", invoice_date=clock.today(), channel="PORTAL",
                               lines=[{"po": po.number, "po_line": 10, "qty": str(qty), "unit_price": "12.50", "gst_rate": "18"}])
    assert invoice.status == "MATCHED"
    invoice.gross_minor = gross_minor
    s.flush()
    return invoice


def _bands(s) -> None:
    _rule(s, "INVOICE-APPROVAL", BANDS, company_code="1000")


def _cfos(s):
    return _add_user(s, "cfo.one", [CFO]), _add_user(s, "cfo.two", [CFO])


def _open(s, invoice) -> list[Task]:
    return payables.open_approval_tasks(s, invoice)


def _events(s, topic: str, object_id) -> list[OutboxEvent]:
    s.flush()
    return s.execute(select(OutboxEvent).where(OutboxEvent.topic == topic, OutboxEvent.object_id == object_id)).scalars().all()


# ================================================================ defaults: the bands body, the CFO role, new tenants
def test_default_bands_body_and_cfo_role():
    assert BANDS["bands"] == [{"fromMinor": 10 * L, "approvers": [FC]}, {"fromMinor": 1 * CR, "approvers": [FC, CFO]}]
    assert 10 * L == 100_000_000 and 1 * CR == 1_000_000_000
    assert payables.validate_approval_rule("INVOICE-APPROVAL", BANDS) == []
    assert p2p_defaults.BODIES["INVOICE-APPROVAL"][0]["bands"] == []          # existing tenants and the bundled seeds keep AP-only approval
    assert payables.APPROVAL_DEFAULT["bands"] == []
    scopes = ROLE_SCOPES[CFO]
    assert "invoice:approve" in scopes and "tasks:work" in scopes
    assert not scopes & {"invoice:capture", "invoice:post", "invoice:resolve", "payment:run", "supplier:bank", "po:create"}
    assert CFO in admin_svc.SENSITIVE_ROLES
    assert CFO in reference.RULE_SETS["MFA"][0]["requiredRoles"]
    assert workflow.role_title(CFO) == "CFO" and workflow.role_title(FC) == "Finance Controller"


def test_with_invoice_bands_copies_and_never_touches_the_rule_sets():
    rules = {"INVOICE-APPROVAL": ({"bands": [], "slaBusinessDays": 2}, "Invoice approval")}
    assert reference._with_invoice_bands(rules, False) is rules
    out = reference._with_invoice_bands(rules, True)
    assert out["INVOICE-APPROVAL"][0] == BANDS and out["INVOICE-APPROVAL"][0] is not BANDS
    assert "CFO" in out["INVOICE-APPROVAL"][1] and rules["INVOICE-APPROVAL"][0]["bands"] == []
    assert reference._with_invoice_bands({"X": ({}, "x")}, True) == {"X": ({}, "x")}


def _bootstrapped(code: str, **kwargs) -> dict:
    tid = reference.create_tenant(code, f"Bands test {code} Pvt Ltd", "GENERAL", mfa_enforce=False)
    reference.bootstrap(tid, company=("1000", f"Bands test {code}", "27AAAAA0000A1Z2"), plants=[("P100", "Plant 100", "27")],
                        cost_objects=[("COST_CENTER", "7100", "CC 7100")], **kwargs)
    with tenant_tx(tid) as s:
        return s.execute(select(RuleSet).where(RuleSet.key == "INVOICE-APPROVAL")).scalar_one().body


def test_a_new_tenant_starts_with_the_bands_and_the_bundled_seeds_do_not():
    assert _bootstrapped("BNDT1")["bands"] == BANDS["bands"]                 # created outside the bundled seeds: the client-approved default
    assert _bootstrapped("BNDT2", invoice_bands=False)["bands"] == []        # explicit opt-out
    with tenant_tx(_axn()) as s:                                            # the AXN signature tenant keeps AP-only approval
        base = s.execute(select(RuleSet).where(RuleSet.key == "INVOICE-APPROVAL", RuleSet.version == reference.RULES_VERSION)).scalar_one()
        assert base.body["bands"] == []


def test_the_onboarding_tool_provisions_the_bands():
    from app.pic.tools import tenant_admin
    with system_tx() as s:
        exists = s.execute(select(Tenant.id).where(Tenant.code == "BNDP1")).scalar_one_or_none()
    if exists is None:
        tenant_admin.create(argparse.Namespace(code="BNDP1", name="Bands Provisioned Ltd", template="MANUFACTURING", admin_email="owner@bndp1.example",
                                               admin_name="Bina Owner", company_code="6000", company_name=None, gstin="27AAAAA0000A1Z2",
                                               plant="P600", plant_name="Plant 600", state_code="27"))
    with system_tx() as s:
        tid = s.execute(select(Tenant.id).where(Tenant.code == "BNDP1")).scalar_one()
    with tenant_tx(tid) as s:
        assert s.execute(select(RuleSet).where(RuleSet.key == "INVOICE-APPROVAL")).scalar_one().body["bands"] == BANDS["bands"]
        provisioned = s.execute(select(AuditEvent).where(AuditEvent.action == "PROVISIONED")).scalars().first()
        assert provisioned.after["invoiceApprovalBands"] is True


# ================================================================ bands at each boundary
@pytest.mark.parametrize("gross, chain", [
    (99_999_999, []),                      # ₹9,99,999.99: accounts payable alone
    (100_000_000, [FC]),                   # ₹10,00,000.00: AP, then the finance controller
    (999_999_999, [FC]),                   # ₹99,99,999.99
    (1_000_000_000, [FC, CFO]),            # ₹1,00,00,000.00: AP, finance controller, CFO
])
def test_band_boundaries(tx, gross, chain):
    s = tx
    _bands(s)
    invoice = _invoice(s, gross)
    assert payables.approval_chain(s, invoice)[0] == chain
    _as(s, "ap.clerk")
    payables.approve(s, invoice)
    tasks = _open(s, invoice)
    if not chain:
        assert invoice.status == "APPROVED" and not tasks
        state = payables.approval_state(s, invoice)
        assert state["status"] == "APPROVED" and state["requiredChain"] == []
    else:
        assert invoice.status == "MATCHED" and [t.candidate_role for t in tasks] == [FC]
        state = payables.approval_state(s, invoice)
        assert state["status"] == "PENDING" and state["requiredChain"] == chain and state["valueMinor"] == gross
        assert state["band"]["fromMinor"] == (1 * CR if CFO in chain else 10 * L)


def test_an_invoice_approved_before_the_bands_is_not_relabelled(tx):
    s = tx
    invoice = _invoice(s, 5 * CR)
    _as(s, "ap.clerk")
    payables.approve(s, invoice)                       # AXN without bands: AP alone
    assert invoice.status == "APPROVED"
    _bands(s)                                           # the bands arrive later
    state = payables.approval_state(s, invoice)
    assert state["status"] == "APPROVED" and state["requiredChain"] == [] and state["band"] is None


# ================================================================ the CFO step: approve, reject, SoD, inbox, SLA
def test_cfo_band_runs_ap_then_controller_then_cfo(tx):
    s = tx
    _bands(s)
    cfo, _ = _cfos(s)
    invoice = _invoice(s, 1 * CR + 4_50_000_00)
    ap = _as(s, "ap.clerk")
    payables.approve(s, invoice)
    fc_task = _open(s, invoice)[0]
    assert fc_task.candidate_role == FC and ap.id in fc_task.excluded_user_ids
    assert _problem(payables.approve, s, invoice).code == "APPROVAL_PENDING"
    _as(s, "cfo.one")
    assert workflow.can_work(s.info["principal"], fc_task) == f"task requires role {FC}"   # the CFO does not skip the controller
    fc = _as(s, "finance.controller")
    workflow.complete(s, fc_task.id, "APPROVE", "Within the tooling budget")
    cfo_task = _open(s, invoice)[0]
    assert cfo_task.candidate_role == CFO and cfo_task.sequence == 2 and {ap.id, fc.id} <= set(cfo_task.excluded_user_ids)
    assert cfo_task.name.endswith("· CFO") and invoice.status == "MATCHED"
    _as(s, "cfo.one")
    workflow.complete(s, cfo_task.id, "APPROVE", "Approved: die set per capex plan")
    assert invoice.status == "APPROVED" and invoice.approved_by == cfo.id
    state = payables.approval_state(s, invoice)
    assert state["status"] == "APPROVED" and [st["role"] for st in state["steps"]] == [FC, CFO]
    assert [st["decision"] for st in state["steps"]] == ["APPROVE", "APPROVE"] and state["apApprover"] == "ap.clerk@axion.example"
    from app.pic.platform import sod
    for local in ("ap.clerk", "finance.controller", "cfo.one"):    # SOD-09: none of the three may release the payment
        _as(s, local)
        assert _problem(sod.guard, s, "PAYMENT_APPROVE", {"invoice_id": invoice.id}).code == "SOD_CONFLICT"


def test_cfo_rejection_returns_the_invoice_to_ap(tx):
    s = tx
    _bands(s)
    _cfos(s)
    invoice = _invoice(s, 2 * CR)
    _as(s, "ap.clerk")
    payables.approve(s, invoice)
    _as(s, "finance.controller")
    workflow.complete(s, _open(s, invoice)[0].id, "APPROVE", "Checked")
    cfo_task = _open(s, invoice)[0]
    _as(s, "cfo.two")
    assert _problem(workflow.complete, s, cfo_task.id, "REJECT", None).code == "COMMENT_REQUIRED"
    workflow.complete(s, cfo_task.id, "REJECT", "Die price 14% above should-cost: hold for the tooling audit")
    assert invoice.status == "EXCEPTION" and invoice.payment_block
    exc = s.execute(select(InvoiceException).where(InvoiceException.invoice_id == invoice.id, InvoiceException.status == "OPEN")).scalar_one()
    assert exc.type == "APPROVAL" and exc.delta["role"] == CFO and exc.detail.startswith("CFO rejected the invoice: Die price")
    assert _events(s, "invoice.exception.raised", invoice.id)
    state = payables.approval_state(s, invoice)
    assert state["status"] == "REJECTED" and state["steps"][-1]["decision"] == "REJECT" and state["steps"][-1]["role"] == CFO
    _as(s, "ap.clerk")
    payables.resolve_exception(s, invoice, exc.id, "CLARIFIED", "Tooling audit done; supplier agreed the price")
    assert invoice.status == "MATCHED"
    payables.approve(s, invoice)
    assert [t.candidate_role for t in _open(s, invoice)] == [FC]    # a new chain from the controller


def test_cfo_return_also_goes_back_to_ap(tx):
    s = tx
    _bands(s)
    _cfos(s)
    invoice = _invoice(s, 1 * CR)
    _as(s, "ap.clerk")
    payables.approve(s, invoice)
    _as(s, "finance.controller2")
    workflow.complete(s, _open(s, invoice)[0].id, "APPROVE", "Checked")
    _as(s, "cfo.one")
    workflow.complete(s, _open(s, invoice)[0].id, "RETURN", "Attach the tooling acceptance report")
    assert invoice.status == "EXCEPTION"
    assert s.execute(select(InvoiceException).where(InvoiceException.invoice_id == invoice.id)).scalar_one().detail.startswith("CFO returned")


def test_sod_nobody_approves_twice_in_one_chain_or_after_the_ap_approval(tx):
    s = tx
    _bands(s)
    both = _add_user(s, "fc.cfo", [FC, CFO])
    ap_cfo = _add_user(s, "ap.cfo", ["AP_CLERK", CFO])
    _add_user(s, "cfo.only", [CFO])
    invoice = _invoice(s, 3 * CR)
    _as(s, "ap.cfo")                                   # the AP approver also holds CFO
    payables.approve(s, invoice)
    _as(s, "fc.cfo")                                   # holds both chain roles: approves the controller step ...
    workflow.complete(s, _open(s, invoice)[0].id, "APPROVE", "Controller check done")
    cfo_task = _open(s, invoice)[0]
    assert {both.id, ap_cfo.id} <= set(cfo_task.excluded_user_ids)
    for local in ("fc.cfo", "ap.cfo"):                 # ... and neither he nor the AP approver can take the CFO step
        _as(s, local)
        assert "four-eyes" in workflow.can_work(s.info["principal"], cfo_task)
        assert cfo_task.id not in [t.id for t in workflow.open_tasks_for(s, s.info["principal"])]
        assert _problem(workflow.complete, s, cfo_task.id, "APPROVE", "again").code == "NOT_YOUR_TASK"
    _as(s, "cfo.only")
    workflow.complete(s, cfo_task.id, "APPROVE", "Approved")
    assert invoice.status == "APPROVED"


def test_sod_08_the_capturer_never_approves_at_the_cfo_step(tx):
    s = tx
    _bands(s)
    _cfos(s)
    invoice = _invoice(s, 1 * CR)
    _as(s, "ap.clerk")
    payables.approve(s, invoice)
    _as(s, "finance.controller")
    workflow.complete(s, _open(s, invoice)[0].id, "APPROVE", "ok")
    cfo_task = _open(s, invoice)[0]
    # the capturer (here the supplier's portal user) is excluded from every step of the chain
    capturer = invoice.created_by
    assert capturer in cfo_task.excluded_user_ids


def test_inbox_shows_the_cfo_step_only_to_a_cfo_in_scope(tx):
    s = tx
    _bands(s)
    _cfos(s)
    invoice = _invoice(s, 1 * CR + 1)
    _as(s, "ap.clerk")
    payables.approve(s, invoice)
    _as(s, "finance.controller")
    workflow.complete(s, _open(s, invoice)[0].id, "APPROVE", "ok")
    cfo_task = _open(s, invoice)[0]
    inbox = lambda: [t.id for t in workflow.open_tasks_for(s, s.info["principal"])]  # noqa: E731
    _as(s, "cfo.one")
    assert cfo_task.id in inbox()
    _as(s, "finance.controller2")
    assert cfo_task.id not in inbox()
    _as_roles(s, [CFO], {"value_limit_minor": 1 * CR})                 # value limit below the invoice (D2: hidden, and refused)
    assert cfo_task.id not in inbox()
    assert _problem(workflow.complete, s, cfo_task.id, "APPROVE", "ok").status == 403
    _as_roles(s, [CFO], {"approval_limits": {"INVOICE_APPROVE": 5 * CR}})
    assert cfo_task.id in inbox()
    _as_roles(s, [CFO], {"company_codes": ["9999"]})                   # another company code
    assert cfo_task.id not in inbox()
    assert abac.task_allowed(s, s.info["principal"], cfo_task) is False


def test_sla_reminds_and_escalates_the_cfo_step(tx):
    s = tx
    _rule(s, "INVOICE-APPROVAL", {**BANDS, "slaBusinessDays": 3}, company_code="1000")
    _cfos(s)
    invoice = _invoice(s, 1 * CR)
    _as(s, "ap.clerk")
    payables.approve(s, invoice)
    _as(s, "finance.controller")
    approved_at = clock.now()
    workflow.complete(s, _open(s, invoice)[0].id, "APPROVE", "ok")
    cfo_task = _open(s, invoice)[0]
    assert cfo_task.due_at.date() == clock.add_business_days(approved_at, 3).date()      # slaBusinessDays carried to the CFO step
    timer = s.execute(select(Timer).where(Timer.object_id == cfo_task.id, Timer.kind == "TASK_SLA", Timer.fired_at.is_(None))).scalar_one()
    clock.set_pinned(cfo_task.due_at + timedelta(hours=1))
    timer.fired_at = clock.now()
    workflow._task_sla(s, timer)                                          # level 1: reminder to the CFOs
    assert cfo_task.escalation_level == 1
    escalated = _events(s, "task.escalated", cfo_task.id)
    assert escalated and escalated[-1].payload["role"] == CFO and escalated[-1].payload["escalatedTo"] is None
    timer2 = s.execute(select(Timer).where(Timer.object_id == cfo_task.id, Timer.kind == "TASK_SLA", Timer.fired_at.is_(None))).scalar_one()
    timer2.fired_at = clock.now()
    workflow._task_sla(s, timer2)                                         # level 2: no role above CFO in the default rule -> reminder again
    assert cfo_task.escalation_level == 2 and cfo_task.candidate_role == CFO
    trail = s.execute(select(AuditEvent).where(AuditEvent.object_id == invoice.id, AuditEvent.action == "TASK_ESCALATED")).scalars().all()
    assert len(trail) >= 2 and all("reminder" in (a.reason or "") for a in trail[-2:])
    # a tenant that names a manager for the CFO in rule ESCALATION gets the escalation at the next level
    body = s.execute(select(RuleSet).where(RuleSet.key == "ESCALATION").order_by(RuleSet.effective_from.desc())).scalars().first().body
    _rule(s, "ESCALATION", {**body, "managers": {**body["managers"], CFO: "CPO"}, "mode": "ADD"})
    timer3 = s.execute(select(Timer).where(Timer.object_id == cfo_task.id, Timer.kind == "TASK_SLA", Timer.fired_at.is_(None))).scalar_one()
    timer3.fired_at = clock.now()
    workflow._task_sla(s, timer3)
    assert any(e.get("role") == "CPO" for e in cfo_task.candidate_scope.get(workflow.ESCALATION_KEY) or [])


def test_approval_decision_api_for_a_cfo_without_a_task(client, login):
    r = client.get("/v1/invoices", headers=login("ap.clerk"))
    items = r.json()["items"] if isinstance(r.json(), dict) else r.json()
    one = client.get(f"/v1/invoices/{items[0]['id']}", headers=login("ap.clerk")).json()
    assert {"status", "requiredChain", "steps"} <= set(one["approval"])


# ================================================================ D5: award on an expired offer
PRICE_ONLY = [{"code": "PRICE_TCO", "name": "Price / TCO", "weight": 100}]
OPEN_SHARES = {"max_suppliers": 2, "max_share": "1", "min_share": "0"}


def _at(y, m, d, hh=10, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def _evaluated_event(s, owner: str = "category.head", valid_until=(date(2029, 3, 20), date(2029, 4, 30))) -> SourcingEvent:
    """An ALU-DIECAST RFQ: Trichy Forge at 400 (offer valid to 20 March 2029) and Kovai Diecast at 405 (to 30 April), closed on 8 March 2029."""
    clock.set_pinned(_at(2029, 3, 1))
    _as(s, owner)
    event = sourcing.create_event(s, type="RFQ", title="Bands test RFQ", category="ALU-DIECAST",
                                  lines=[{"requisition": "REQ-2312", "line": 10, "annual_qty": "20000", "monthly_qty": "2000"}], criteria=PRICE_ONLY,
                                  invitees=[{"supplier": "TF001"}, {"supplier": "KD002"}], close_at=_at(2029, 3, 8, 17), baseline_method="BUDGET",
                                  baseline_price_minor=42000, constraints=OPEN_SHARES)
    sourcing.publish(s, event)
    for who, price, until in (("tf.sales", "400", valid_until[0]), ("kd.sales", "405", valid_until[1])):
        user = _as(s, who)
        sourcing.submit_bid(s, event, s.get(Supplier, user.supplier_id), [{"line": 10, "unit_price": price, "payment_terms_days": 60,
                                                                          "lead_time_days": 14, "capacity_per_month": "5000"}], valid_until=until)
    clock.set_pinned(_at(2029, 3, 8, 17, 5))
    _as(s, owner)
    sourcing.close(s, event)
    if event.unsealed_at is None:
        sourcing.open_bids(s, event)
    return event


def _lowest(s, event, who: str = "category.head") -> uuid.UUID:
    _as(s, who)
    return uuid.UUID(next(x for x in sourcing.build_scenarios(s, event) if x["kind"] == "LOWEST_COST")["id"])


REASON = "Trichy Forge confirmed the 400 price in writing on 24 March (letter TF/2029/118)"


def test_award_on_an_expired_offer_is_blocked_with_the_bids_and_the_way_out(tx):
    s = tx
    event = _evaluated_event(s)
    scenario = _lowest(s, event)
    clock.set_pinned(_at(2029, 3, 25))
    _as(s, "category.head")
    p = _problem(sourcing.propose_award, s, event, scenario, None, "No conflict")
    assert p.status == 409 and p.code == "BID_OFFER_EXPIRED" and p.rule_ref == "SRC-AWARD"
    assert [b["supplier"] for b in p.extra["expiredBids"]] == ["TF001"]
    bid = p.extra["expiredBids"][0]
    assert bid["validUntil"] == "2029-03-20" and bid["daysExpired"] == 5 and bid["supplierName"] == "Trichy Forge Pvt Ltd"
    assert p.extra["overrideAllowed"] is True and p.extra["overrideRoles"] == ["CATEGORY_MANAGER"] and p.extra["minReasonChars"] == 20
    assert p.extra["extendValidity"]["path"] == f"/v1/sourcing/events/{event.number}/rounds" and "rounds" in p.detail
    assert event.status == "UNDER_EVALUATION" and not s.execute(select(AwardDecision).where(AwardDecision.event_id == event.id)).first()
    # the honest path: a new round, in which the supplier gives a new validity
    sourcing.new_round(s, event, _at(2029, 3, 28, 17), "Offer of TF001 expired: confirm or extend the validity")
    assert event.round == 2


def test_override_needs_the_right_role_and_a_real_reason(tx):
    s = tx
    event = _evaluated_event(s, owner="buyer")
    scenario = _lowest(s, event, "buyer")
    clock.set_pinned(_at(2029, 3, 25))
    _as(s, "buyer")                                                   # the buyer owns the event but may not override
    p = _problem(sourcing.propose_award, s, event, scenario, None, "No conflict")
    assert p.code == "BID_OFFER_EXPIRED" and p.extra["overrideAllowed"] is False
    p = _problem(sourcing.propose_award, s, event, scenario, None, "No conflict", REASON)
    assert p.status == 403 and p.code == "OVERRIDE_NOT_ALLOWED"
    _as_roles(s, ["CATEGORY_MANAGER"], {"categories": ["MRO"]})       # a category manager of another category is not the event's manager
    assert _problem(sourcing.propose_award, s, event, scenario, None, "No conflict", REASON).status == 403
    _as(s, "category.manager")                                        # ALU-DIECAST category manager
    p = _problem(sourcing.propose_award, s, event, scenario, None, "No conflict", "price confirmed")
    assert p.status == 422 and p.code == "REASON_REQUIRED"
    assert sourcing.may_override_expired(s.info["principal"], event, sourcing.policy_of(s, event)) is True


def test_override_is_recorded_audited_emitted_and_approved_by_someone_else(tx):
    from app.pic.events import catalogue
    s = tx
    event = _evaluated_event(s)
    scenario = _lowest(s, event)
    clock.set_pinned(_at(2029, 3, 25))
    _as(s, "category.head")
    decision = sourcing.propose_award(s, event, scenario, None, "No conflict", f"  {REASON}  ")
    assert decision.status == "PENDING" and event.status == "AWARD_PENDING"          # an override always goes to the approvers
    exc = next(e for e in decision.exceptions if e["code"] == "BID_OFFER_EXPIRED")
    assert exc["override"]["reason"] == REASON and exc["override"]["byEmail"] == "category.head@axion.example"
    assert exc["override"]["bids"][0]["supplier"] == "TF001" and "TF001 valid until 2029-03-20" in exc["detail"]
    audit_row = s.execute(select(AuditEvent).where(AuditEvent.object_id == event.id, AuditEvent.action == "AWARD_EXPIRED_OFFER_OVERRIDDEN")).scalar_one()
    assert audit_row.reason == REASON and audit_row.after["decision"] == str(decision.id)
    emitted = _events(s, "sourcing.award.offer_expiry_overridden", event.id)
    assert len(emitted) == 1 and catalogue.validate("sourcing.award.offer_expiry_overridden", emitted[0].payload) == []
    assert emitted[0].payload["bids"] == [{"supplier": "TF001", "validUntil": "2029-03-20", "daysExpired": 5}]
    task = s.execute(select(Task).where(Task.object_id == event.id, Task.kind == "AWARD_APPROVAL", Task.status == "OPEN")).scalar_one()
    _as(s, "category.head")
    assert workflow.can_work(s.info["principal"], task) is not None                    # the overrider never approves his own override
    _as(s, "category.manager")
    workflow.complete(s, task.id, "APPROVE", "Written price confirmation on file")
    _approve_all(s, event.id)                                                          # the rest of the band: CPO, finance controller
    assert s.get(AwardDecision, decision.id).status == "APPROVED" and event.status == "AWARDED"


def test_an_offer_that_expires_during_the_approval_blocks_the_approver(tx):
    s = tx
    event = _evaluated_event(s, valid_until=(date(2029, 3, 20), date(2029, 3, 21)))
    _lowest(s, event)
    _as(s, "category.head")
    clock.set_pinned(_at(2029, 3, 10))
    # a non-lowest award (with its rationale) always goes to the approvers
    custom = sourcing.custom_scenario(s, event, [{"supplier": "KD002", "share_pct": "100"}])
    decision = sourcing.propose_award(s, event, uuid.UUID(custom["id"]), "Kovai Diecast: better delivery record on this part", "No conflict")
    assert decision.status == "PENDING"
    task = s.execute(select(Task).where(Task.object_id == event.id, Task.kind == "AWARD_APPROVAL", Task.status == "OPEN")).scalar_one()
    clock.set_pinned(_at(2029, 3, 25))                                # Kovai's offer ended on 21 March
    _as(s, "category.manager")
    p = _problem(workflow.complete, s, task.id, "APPROVE", "ok")
    assert p.status == 409 and p.code == "BID_OFFER_EXPIRED" and p.extra["expiredBids"][0]["supplier"] == "KD002"
    workflow.complete(s, task.id, "RETURN", "Offer expired: ask Kovai to extend the validity")   # returning is still possible
    assert s.get(AwardDecision, decision.id).status == "REJECTED"


def test_override_policy_is_validated_and_configurable(tx):
    assert sourcing_defaults.validate("SOURCING-POLICY", {"expiredOfferOverride": {"roles": ["CATEGORY_MANAGER", "CPO"], "minReasonChars": 30}}) == []
    assert sourcing_defaults.validate("SOURCING-POLICY", {"expiredOfferOverride": "yes"})
    assert sourcing_defaults.validate("SOURCING-POLICY", {"expiredOfferOverride": {"roles": ["SUPPLIER_USER"]}})
    assert sourcing_defaults.validate("SOURCING-POLICY", {"expiredOfferOverride": {"roles": "CPO"}})
    assert sourcing_defaults.validate("SOURCING-POLICY", {"expiredOfferOverride": {"minReasonChars": 3}})
    assert sourcing_defaults.validate("SOURCING-POLICY", {"expiredOfferOverride": {"requiresApproval": "no"}})
    s = tx
    event = _evaluated_event(s)
    scenario = _lowest(s, event)
    # a tenant that lets nobody override: the block stands
    _rule(s, "SOURCING-POLICY", {**sourcing_defaults.POLICY_DEFAULT, "expiredOfferOverride": {"roles": [], "minReasonChars": 20}})
    clock.set_pinned(_at(2029, 3, 25))
    _as(s, "category.head")
    p = _problem(sourcing.propose_award, s, event, scenario, None, "No conflict", REASON)
    assert p.status == 403 and "(nobody)" in p.detail
    # a tenant that does not require approval of an override (approval then follows the value band only)
    _rule(s, "SOURCING-POLICY", {**sourcing_defaults.POLICY_DEFAULT, "expiredOfferOverride": {"roles": ["CATEGORY_MANAGER"], "requiresApproval": False}})
    assert sourcing.override_policy(sourcing.policy_of(s, event))["minReasonChars"] == 20
    decision = sourcing.propose_award(s, event, scenario, None, "No conflict", REASON)
    assert any(e["code"] == "BID_OFFER_EXPIRED" for e in decision.exceptions)


def test_who_may_override_and_nothing_to_check_without_a_pending_award():
    from types import SimpleNamespace
    event = SimpleNamespace(category="ALU-DIECAST")
    pol = {"expiredOfferOverride": {"roles": ["CATEGORY_MANAGER", "CPO"]}}
    principal_ = lambda roles, cats=None: SimpleNamespace(roles=roles, attr=lambda k, d=None: cats if k == "categories" else d)  # noqa: E731
    assert sourcing.may_override_expired(principal_(["CATEGORY_MANAGER"], ["MRO"]), event, pol) is False      # another category
    assert sourcing.may_override_expired(principal_(["CATEGORY_MANAGER"], ["*"]), event, pol) is True
    assert sourcing.may_override_expired(principal_(["CPO"]), event, pol) is True                              # a role without category scope
    assert sourcing.may_override_expired(principal_(["BUYER"]), event, pol) is False
    assert sourcing.override_policy({"expiredOfferOverride": "bad"}) == sourcing_defaults.POLICY_DEFAULT["expiredOfferOverride"]
    assert sourcing._expired_without_override(None, event, None) == []


def test_award_api_carries_the_override_field():
    from app.pic.api.source_contract import AwardIn
    body = AwardIn(scenario_id=uuid.uuid4(), conflict_declaration="none", expired_offer_override=REASON)
    assert body.expired_offer_override == REASON and AwardIn(scenario_id=uuid.uuid4(), conflict_declaration="none").expired_offer_override is None


# ================================================================ D3: category ABAC on PO create / release, per tenant
def _abac_with_category(s) -> None:
    body = abac.policy_for(s)
    actions = dict(body["actions"])
    for action in ("PO_CREATE", "PO_RELEASE"):
        actions[action] = {**actions[action], "check": sorted(set(actions[action]["check"]) | {"category"})}
    _rule(s, "ABAC", {**body, "actions": actions})


def _approved_fastener_pr(s):
    _as(s, "buyer")
    pr = requisition.create(s, origin="MANUAL", purpose_code="BUFFER_BUILD", purpose_text="D3 test", plant="P100",
                            lines=[{"item_type": "MATERIAL", "purchase_type": "STOCK", "material": "FK-M8-50", "qty": "10", "price_est_minor": 1250,
                                    "need_date": (clock.today() + timedelta(days=30)).isoformat(), "storage_location": "0001"}])
    requisition.submit(s, pr)
    _approve_all(s, pr.id)
    return pr


def _create_po(s, pr):
    return order.create_from_requisition(s, requisition=pr.number, lines=[10], supplier_code="TF001",
                                         one_time_vendor_reason="D3 test purchase of fasteners: one-time exception")[0]


def test_d3_category_check_is_off_by_default(tx):
    s = tx
    policy = abac.policy_for(s)
    assert "category" not in policy["actions"]["PO_CREATE"]["check"] and "category" not in policy["actions"]["PO_RELEASE"]["check"]
    pr = _approved_fastener_pr(s)
    _as_roles(s, ["BUYER"], {"plants": ["P100"], "categories": ["MRO"]})     # categories do not restrict ordering by default
    assert _create_po(s, pr).number


def test_d3_turning_the_switch_on_restricts_create_and_release_to_the_buyer_categories(tx):
    s = tx
    material_category = s.execute(select(Material.category).where(Material.number == "FK-M8-50")).scalar_one()
    pr = _approved_fastener_pr(s)
    _abac_with_category(s)
    _as_roles(s, ["BUYER"], {"plants": ["P100"], "categories": ["MRO"]})
    p = _problem(_create_po, s, pr)
    assert p.status == 403 and p.code == "FORBIDDEN" and p.extra["action"] == "PO_CREATE"
    assert any(v["dimension"] == "category" for v in p.extra["violations"])
    _as_roles(s, ["BUYER"], {"plants": ["P100"], "categories": [material_category]})
    po = _create_po(s, pr)
    assert po.number
    # release: a buyer outside the category may not release it
    from app.pic.services.order import _release
    _as_roles(s, ["BUYER"], {"plants": ["P100"], "categories": ["MRO"]})
    p = _problem(_release, s, po)
    assert p.status == 403 and p.extra["action"] == "PO_RELEASE"
    # the same switch, AUDIT mode: logged, not refused
    body = abac.policy_for(s)
    _rule(s, "ABAC", {**body, "mode": "AUDIT"})
    _as_roles(s, ["BUYER"], {"plants": ["P100"], "categories": ["MRO"]})
    assert abac.guard(s, "PO_CREATE", po, category=material_category)["allowed"] is False


# ================================================================ D1 and D2 defaults
def test_d1_a_planned_order_is_ordered_through_its_requisition():
    import inspect
    from app.pic.services import order as order_svc
    source = inspect.getsource(order_svc.create_from_planned_order)
    assert "planning.convert" in source and "create_from_requisition" in source


def test_d1_only_the_mrp_controller_converts_a_planned_order(tx):
    s = tx
    _as(s, "buyer")
    p = _problem(order.create_from_planned_order, s, planned_order="PLO-00000")
    assert p.status == 403 and p.rule_ref == "P02"


def test_d2_the_inbox_filters_by_abac_scope():
    import inspect
    source = inspect.getsource(workflow.open_tasks_for)
    assert "abac.task_allowed" in source and "can_work" in source
    # (the behaviour is exercised in test_inbox_shows_the_cfo_step_only_to_a_cfo_in_scope)
