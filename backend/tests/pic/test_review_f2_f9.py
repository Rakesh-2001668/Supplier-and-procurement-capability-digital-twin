"""Review fixes F2 (guided buying → requisition) and F9 (material governance).

Service-level checks run in tenant transactions that roll back (own objects only, pinned to 20 Nov 2026 so the FY 2026-27
budgets of the signature case apply). API checks only create DRAFT requisitions of their own, refused requests (422) or
cancel what they created, so the signature case is untouched.
"""
import uuid
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuditEvent, Budget, BudgetCommitment, CatalogueItem, CategoryPlan, Contract, ContractLine, Material, PrLine,
    ProcessInstance, ProcessStep, PunchoutSession, RuleSet, Supplier, Task, Tenant,
)
from app.pic.platform import clock, rules, workflow
from app.pic.platform.auth import Principal, scopes_for
from app.pic.platform.errors import Problem
from app.pic.seed import axion
from app.pic.services import mdm, order, punchout, requisition, source

WHEN = axion.at(date(2026, 11, 20), 11)
L = 100_000 * 100


class _Rollback(Exception):
    pass


def _axn():
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()


def _as(session, local: str) -> None:
    user = session.execute(select(AppUser).where(AppUser.email == f"{local}@axion.example")).scalar_one()
    session.info["principal"] = Principal(user.id, user.tenant_id, "AXN", user.email, user.full_name, list(user.roles),
                                          scopes_for(list(user.roles)), user.attributes or {}, user.supplier_id)
    session.info["user_id"] = user.id


@contextmanager
def _rolled_back(local: str = "requester", when=WHEN):
    clock.set_pinned(when)
    try:
        with tenant_tx(_axn()) as s:
            _as(s, local)
            yield s
            raise _Rollback
    except _Rollback:
        pass
    finally:
        clock.set_pinned(None)


def _user(s, local: str, roles: list[str], attributes: dict) -> None:
    s.add(AppUser(tenant_id=s.info["principal"].tenant_id, email=f"{local}@axion.example", full_name=local.replace(".", " ").title(),
                  password_hash="x", roles=roles, attributes=attributes))
    s.flush()


def _line(**over) -> dict:
    line = {"item_type": "FREE_TEXT", "purchase_type": "NON_STOCK", "description": "Pneumatic clamp kit for fixture rework",
            "material_group": "41-FIXTURE", "category": "TOOLING", "qty": "2", "uom": "EA", "price_est_minor": 900_000,
            "account_assignment_type": "COST_CENTER", "account_assignment_code": "4100", "need_date": "2026-12-15"}
    line.update(over)
    return line


def _pr(s, *lines, purpose="F2F9_REVIEW"):
    return requisition.create(s, origin="MANUAL", purpose_code=purpose, purpose_text="review test", plant="P100", lines=list(lines))


def _problem(fn, *args, **kwargs) -> Problem:
    with pytest.raises(Problem) as exc:
        fn(*args, **kwargs)
    return exc.value


def _open_tasks(s, pr) -> list[Task]:
    return s.execute(select(Task).where(Task.object_id == pr.id, Task.status == "OPEN").order_by(Task.sequence)).scalars().all()


def _approve(s, task: Task, local: str) -> None:
    _as(s, local)
    workflow.complete(s, task.id, "APPROVE", "ok")


def _approve_all(s, pr) -> None:
    for _ in range(6):
        tasks = _open_tasks(s, pr)
        if not tasks:
            return
        for task in tasks:
            local = axion.ROLE_USER[task.candidate_role]
            _approve(s, task, local if isinstance(local, str) else local[0])


QUOTE = {"supplier": "HTS004", "reference": "HTS/Q/26-27/0901", "date": "2026-11-10"}


# ---------------------------------------------------------------- 1 negative quantity / price
def test_negative_quantity_and_price_are_refused_by_api_and_service(client, login):
    h = login("requester")
    base = {"origin": "MANUAL", "purpose_code": "F2F9_REVIEW", "plant": "P100", "lines": [_line(need_date="2026-12-15")]}
    for bad in ({"qty": "-5"}, {"qty": "0"}, {"price_est_minor": -100}):
        r = client.post("/v1/requisitions", json={**base, "lines": [_line(**bad)]}, headers=h)
        assert r.status_code == 422, (bad, r.text)
    assert client.patch("/v1/requisitions/REQ-NONE/lines/10", json={"qty": "-1"}, headers=h).status_code == 422
    assert client.patch("/v1/requisitions/REQ-NONE/lines/10", json={"price_est_minor": -1}, headers=h).status_code == 422
    with _rolled_back() as s:
        assert _problem(_pr, s, _line(qty="-3")).status == 422
        assert _problem(_pr, s, _line(price_est_minor=-1)).status == 422
        pr = _pr(s, _line(), _line(description="Clamp spares", price_est_minor=100_000))
        assert _problem(requisition.change_line, s, pr, 10, {"qty": "-2"}).status == 422
        assert _problem(requisition.change_line, s, pr, 20, {"price_est_minor": -50}).status == 422
        assert pr.total_minor == 2 * 900_000 + 2 * 100_000


# ---------------------------------------------------------------- 15 no lines
def test_requisition_without_lines_is_a_422_not_a_500(client, login):
    r = client.post("/v1/requisitions", json={"origin": "MANUAL", "purpose_code": "X", "plant": "P100", "lines": []}, headers=login("requester"))
    assert r.status_code == 422
    with _rolled_back() as s:
        assert _problem(requisition.create, s, origin="MANUAL", lines=[], plant="P100", purpose_code="X").status == 422
        pr = _pr(s, _line())
        for line in s.execute(select(PrLine).where(PrLine.requisition_id == pr.id)).scalars():
            s.delete(line)
        s.flush()
        problem = _problem(requisition.submit, s, pr)
        assert problem.status == 422 and "at least one line" in problem.detail


# ---------------------------------------------------------------- 2 contract lines
def test_contract_line_is_created_through_the_api_at_the_contract_price(client, login):
    today = clock.today()
    with tenant_tx(_axn()) as s:
        found = s.execute(select(ContractLine, Contract, Material).join(Contract, Contract.id == ContractLine.contract_id)
                          .join(Material, Material.id == ContractLine.material_id)
                          .where(Contract.status.in_(("ACTIVE", "EXPIRING")), Contract.valid_to >= today, ContractLine.plant == "P100")).first()
        assert found, "the signature case has an active contract line"
        cline, contract, material = found
        validity = source.contract_price(s, cline.id, max(today, contract.valid_from))
        cline_id, material_no = str(cline.id), material.number
        expected = validity.unit_price_minor if validity else None
    h = login("requester")
    body = {"origin": "MANUAL", "purpose_code": "F2F9_REVIEW", "plant": "P100", "lines": [
        {"item_type": "CONTRACT", "purchase_type": "STOCK", "material": material_no, "contract_line_id": cline_id, "qty": "10",
         "price_est_minor": 1, "need_date": (today + timedelta(days=20)).isoformat()}]}
    r = client.post("/v1/requisitions", json=body, headers=h)
    assert r.status_code == 201, r.text
    line = r.json()["lines"][0]
    assert line["item_type"] == "CONTRACT" and line["contract_line_id"] == cline_id
    if expected is not None:
        assert line["price_est_minor"] == expected  # the contract price wins over the client's estimate
    number = r.json()["number"]
    # A contract line that does not belong to the material is refused.
    other = {**body, "lines": [{**body["lines"][0], "contract_line_id": str(uuid.uuid4())}]}
    assert client.post("/v1/requisitions", json=other, headers=h).status_code == 422
    cancelled = client.post(f"/v1/requisitions/{number}/cancel", json={"reason": "review test clean-up"}, headers=h)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"


# ---------------------------------------------------------------- 3 STOCK needs a material
def test_stock_purchase_without_material_is_refused_on_submit():
    with _rolled_back() as s:
        pr = _pr(s, _line(purchase_type="STOCK", account_assignment_type=None, account_assignment_code=None, price_est_minor=500_000))
        problem = _problem(requisition.submit, s, pr)
        assert problem.status == 422 and "stock purchases need a material master" in problem.detail


# ---------------------------------------------------------------- 4 quote policy on every unstructured line
def test_quote_policy_applies_to_service_lines_and_needs_quote_references():
    with _rolled_back() as s:
        service = _line(item_type="SERVICE", purchase_type="SERVICE", description="Thermal survey of die cell 2", material_group="SVC-TOOLING",
                        category="TOOLING-SERVICES", qty="1", price_est_minor=5_000_000)
        pr = _pr(s, service)
        problem = _problem(requisition.submit, s, pr)
        assert problem.status == 422 and "1 quote(s)" in problem.detail and "service line" in problem.detail
        instance = workflow.find(s, "REQUISITION", pr.id, requisition.PROCESS)
        steps = {st.step_id: st.outcome for st in s.execute(select(ProcessStep).where(ProcessStep.instance_id == instance.id)).scalars()}
        assert "F2-04" in steps and "service" in steps["F2-04"]
        # A bare count without references is refused at entry.
        assert "quote reference" in _problem(_pr, s, {**service, "quotes_attached": 1}).detail
        # Incomplete references are refused; a future-dated quote too.
        assert _problem(_pr, s, {**service, "quotes": [{"supplier": "HTS004", "reference": "", "date": "2026-11-01"}]}).status == 422
        assert _problem(_pr, s, {**service, "quotes": [{**QUOTE, "date": "2026-12-31"}]}).status == 422
        ok = _pr(s, {**service, "quotes": [QUOTE]})
        assert s.execute(select(PrLine).where(PrLine.requisition_id == ok.id)).scalar_one().quotes_attached == 1
        assert requisition.submit(s, ok)["status"] in ("IN_APPROVAL", "APPROVED")
        # Three quotes means three suppliers: the same supplier three times counts once.
        big = {**service, "price_est_minor": 3 * L, "quotes": [QUOTE, {**QUOTE, "reference": "HTS/Q/2"}, {**QUOTE, "reference": "HTS/Q/3"}]}
        assert "3 quote(s)" in _problem(requisition.submit, s, _pr(s, big)).detail


def test_quote_band_edges_follow_the_blueprint():
    rule = rules.Rule("QUOTE-POLICY", "test", {"noQuoteBelow": 25_000 * 100, "oneQuoteBelow": 2 * L})
    assert requisition.quotes_required(rule, 25_000 * 100 - 1) == 0
    assert requisition.quotes_required(rule, 25_000 * 100) == 1
    assert requisition.quotes_required(rule, 2 * L) == 1          # "25,000 – 2 L one quote"
    assert requisition.quotes_required(rule, 2 * L + 1) == 3      # "> 2 L three quotes or sourcing event"


# ---------------------------------------------------------------- 5 one approval task per cost object
def test_every_cost_object_of_a_multi_cost_object_requisition_approves():
    with _rolled_back() as s:
        _user(s, "coo.4200", ["COST_OBJECT_OWNER"], {"plants": ["P100"], "cost_objects": ["COST_CENTER:4200"]})
        _user(s, "head.4200", ["DEPT_HEAD"], {"plants": ["P100"], "cost_objects": ["COST_CENTER:4200"]})
        _as(s, "requester")
        # ₹3 L in total → band COO + department head, charged to two cost centres.
        pr = _pr(s, _line(qty="1", price_est_minor=int(1.5 * L), quotes=[QUOTE]),
                 _line(qty="1", price_est_minor=int(1.5 * L), account_assignment_code="4200", description="IT cabling for fixture cell",
                       quotes=[{**QUOTE, "supplier": "Hosur Networks"}]))
        assert requisition.submit(s, pr)["chain"] == ["COST_OBJECT_OWNER", "DEPT_HEAD"]
        tasks = _open_tasks(s, pr)
        assert sorted(t.candidate_scope["cost_object"] for t in tasks) == ["COST_CENTER:4100", "COST_CENTER:4200"]
        assert {t.candidate_role for t in tasks} == {"COST_OBJECT_OWNER"}
        mine = next(t for t in tasks if t.candidate_scope["cost_object"] == "COST_CENTER:4100")
        theirs = next(t for t in tasks if t.candidate_scope["cost_object"] == "COST_CENTER:4200")
        _as(s, "plant.controller")
        assert _problem(workflow.complete, s, theirs.id, "APPROVE").status == 403  # not the owner of CC 4200
        _approve(s, mine, "plant.controller")
        assert pr.status == "IN_APPROVAL" and len(_open_tasks(s, pr)) == 1
        _approve(s, theirs, "coo.4200")
        heads = _open_tasks(s, pr)
        assert pr.status == "IN_APPROVAL" and sorted(t.candidate_scope["cost_object"] for t in heads) == ["COST_CENTER:4100", "COST_CENTER:4200"]
        assert {t.candidate_role for t in heads} == {"DEPT_HEAD"}
        _approve(s, next(t for t in heads if t.candidate_scope["cost_object"] == "COST_CENTER:4100"), "ops.head")
        assert pr.status == "IN_APPROVAL"
        _approve(s, next(t for t in heads if t.candidate_scope["cost_object"] == "COST_CENTER:4200"), "head.4200")
        assert pr.status == "APPROVED"


def test_single_cost_object_keeps_the_sequential_chain():
    with _rolled_back() as s:
        pr = _pr(s, _line(qty="1", price_est_minor=3 * L, quotes=[QUOTE, {**QUOTE, "supplier": "B"}, {**QUOTE, "supplier": "C"}]))
        requisition.submit(s, pr)
        tasks = _open_tasks(s, pr)
        assert [t.candidate_role for t in tasks] == ["COST_OBJECT_OWNER"] and tasks[0].candidate_scope == {"cost_object": "COST_CENTER:4100"}
        _approve_all(s, pr)
        assert pr.status == "APPROVED"


# ---------------------------------------------------------------- 6 DMN-01 with the full scope
def test_dmn01_resolves_with_category_and_purchase_type():
    with _rolled_back() as s:
        tenant_id = s.info["principal"].tenant_id
        base = rules.resolve(s, "DMN-01", company_code="1000", plant="P100")
        s.add(RuleSet(tenant_id=tenant_id, key="DMN-01", version="f2f9-cat", company_code="1000", category="REVIEW-CAT", effective_from=date(2026, 11, 1),
                      body={**base.body, "bands": [{"upTo": None, "chain": ["PROCUREMENT_HEAD"]}]}, description="test"))
        s.add(RuleSet(tenant_id=tenant_id, key="DMN-01", version="f2f9-svc", company_code="1000", purchase_type="SERVICE", effective_from=date(2026, 11, 1),
                      body={**base.body, "bands": [{"upTo": None, "chain": ["FINANCE_CONTROLLER"]}]}, description="test"))
        s.flush()
        # Dominant category by value is REVIEW-CAT (₹18,000 vs ₹1,000).
        pr = _pr(s, _line(category="REVIEW-CAT"), _line(description="Spares", price_est_minor=50_000))
        assert requisition.submit(s, pr)["chain"] == ["PROCUREMENT_HEAD"] and "DMN-01@f2f9-cat" in pr.rule_set_version
        service = _pr(s, _line(purchase_type="SERVICE", category="TOOLING-SERVICES", price_est_minor=500_000))
        assert requisition.submit(s, service)["chain"] == ["FINANCE_CONTROLLER"] and "DMN-01@f2f9-svc" in service.rule_set_version


# ---------------------------------------------------------------- 7 re-approval after a change
def test_change_after_approval_reuses_submit_routing_type_change_and_justification():
    with _rolled_back() as s:
        tenant_id = s.info["principal"].tenant_id
        s.add(Budget(tenant_id=tenant_id, cost_object_type="COST_CENTER", cost_object_code="4999", fiscal_year="2026-27", control="SOFT",
                     amount_minor=3 * L))
        s.add(Budget(tenant_id=tenant_id, cost_object_type="ORDER", cost_object_code="4100", fiscal_year="2026-27", control="SOFT",
                     amount_minor=10 * L))
        _user(s, "coo.4999", ["COST_OBJECT_OWNER", "DEPT_HEAD"], {"plants": ["P100"], "cost_objects": ["COST_CENTER:4999", "ORDER:4100"]})
        _as(s, "requester")
        pr = _pr(s, _line(qty="1", price_est_minor=int(1.5 * L), account_assignment_code="4999", quotes=[QUOTE]))
        requisition.submit(s, pr)
        _approve(s, _open_tasks(s, pr)[0], "coo.4999")
        assert pr.status == "APPROVED" and pr.approved_snapshot["10"]["accountType"] == "COST_CENTER"
        _as(s, "requester")
        # ₹4 L on a ₹3 L soft budget: the re-booking needs the change's justification.
        with pytest.raises(Problem) as refused:
            with s.begin_nested():
                requisition.change_line(s, pr, 10, {"price_est_minor": 4 * L})
        s.expire_all()  # reload the rows the savepoint rolled back (row_version is the optimistic-lock column)
        assert refused.value.code == "BUDGET_JUSTIFICATION_REQUIRED" and pr.status == "APPROVED"
        result = requisition.change_line(s, pr, 10, {"price_est_minor": 4 * L, "justification": "Scope adds the second fixture"})
        assert result == {"status": "IN_APPROVAL", "reapproval": True}
        assert pr.approval_chain == ["COST_OBJECT_OWNER", "DEPT_HEAD"]  # whole-requisition DMN-01 band for ₹4 L
        commitment = s.execute(select(BudgetCommitment).where(BudgetCommitment.object_id == pr.id, BudgetCommitment.status == "OPEN")).scalar_one()
        assert commitment.amount_minor == 4 * L and commitment.justification == "Scope adds the second fixture"
        assert pr.budget_result["rebookedOnChange"] is True and "categoryBudget" in pr.budget_result
        _approve_all_as(s, pr, "coo.4999", "coo.4999")
        assert pr.status == "IN_APPROVAL"  # the same person cannot approve twice (four-eyes inside the chain)


def _approve_all_as(s, pr, *who) -> None:
    for local in who:
        tasks = _open_tasks(s, pr)
        if not tasks:
            return
        try:
            _approve(s, tasks[0], local)
        except Problem:
            return


def test_account_type_change_alone_restarts_approval():
    with _rolled_back() as s:
        tenant_id = s.info["principal"].tenant_id
        s.add(Budget(tenant_id=tenant_id, cost_object_type="ORDER", cost_object_code="4100", fiscal_year="2026-27", control="SOFT",
                     amount_minor=10 * L))
        s.flush()
        pr = _pr(s, _line())
        requisition.submit(s, pr)
        _approve_all(s, pr)
        assert pr.status == "APPROVED"
        _as(s, "requester")
        assert requisition.change_line(s, pr, 10, {"account_assignment_type": "ORDER"})["reapproval"] is True


# ---------------------------------------------------------------- 8 who may change a line
def test_only_the_requester_or_a_buyer_after_approval_changes_lines():
    with _rolled_back() as s:
        pr = _pr(s, _line())
        _as(s, "buyer")
        assert _problem(requisition.change_line, s, pr, 10, {"need_date": "2026-12-20"}).status == 403
        _as(s, "requester")
        assert requisition.change_line(s, pr, 10, {"need_date": "2026-12-20"})["reapproval"] is False
        requisition.submit(s, pr)
        _approve_all(s, pr)
        _as(s, "plant.controller")
        assert _problem(requisition.change_line, s, pr, 10, {"need_date": "2026-12-22"}).status == 403
        _as(s, "buyer")
        assert requisition.change_line(s, pr, 10, {"need_date": "2026-12-22"}) == {"status": "APPROVED", "reapproval": False}
        assert _problem(requisition.change_line, s, pr, 90, {"need_date": "2026-12-22"}).status == 404


# ---------------------------------------------------------------- 10 cancel / withdraw
def test_cancel_releases_budget_cancels_tasks_and_ends_the_process():
    with _rolled_back() as s:
        budget = s.execute(select(Budget).where(Budget.cost_object_type == "COST_CENTER", Budget.cost_object_code == "4100",
                                                Budget.fiscal_year == "2026-27")).scalar_one()
        committed = budget.committed_minor
        pr = _pr(s, _line())
        requisition.submit(s, pr)
        assert pr.status == "IN_APPROVAL" and budget.committed_minor == committed + 1_800_000
        task = _open_tasks(s, pr)[0]
        _as(s, "buyer")
        assert _problem(requisition.cancel, s, pr, "not mine").status == 403  # a buyer only cancels APPROVED requisitions
        _as(s, "requester")
        assert _problem(requisition.cancel, s, pr, "  ").status == 422
        requisition.cancel(s, pr, "Fixture rework moved to the next quarter")
        assert pr.status == "CANCELLED" and budget.committed_minor == committed
        assert s.get(Task, task.id).status == "CANCELLED"
        instance = s.execute(select(ProcessInstance).where(ProcessInstance.business_id == pr.id)).scalar_one()
        assert instance.status == "CANCELLED"
        assert _problem(requisition.cancel, s, pr, "again").code == "ILLEGAL_TRANSITION"
        # A buyer cancels an approved requisition.
        approved = _pr(s, _line())
        requisition.submit(s, approved)
        _approve_all(s, approved)
        _as(s, "buyer")
        requisition.cancel(s, approved, "Requirement withdrawn by the plant")
        assert approved.status == "CANCELLED"
        audit = s.execute(select(AuditEvent).where(AuditEvent.object_id == approved.id, AuditEvent.action == "CANCEL")).scalar_one()
        assert audit.reason == "Requirement withdrawn by the plant"


def test_cancel_is_refused_once_purchase_order_lines_exist():
    with _rolled_back() as s:
        pr = _pr(s, _line(purchase_type="SERVICE", description="Die maintenance visit", material_group="SVC-TOOLING",
                          category="TOOLING-SERVICES", qty="1", price_est_minor=1_850_000))
        requisition.submit(s, pr)
        _approve_all(s, pr)
        _as(s, "buyer")
        order.create_from_requisition(s, requisition=pr.number, lines=[10], supplier_code="HTS004", unit_price_minor=1_850_000)
        assert _problem(requisition.cancel, s, pr, "late").status == 409
        pr.status = "APPROVED"  # even if the status were reopened, the open PO line blocks the cancel
        s.flush()
        assert _problem(requisition.cancel, s, pr, "late").code == "REQUISITION_ORDERED"


def test_cancel_route(client, login):
    h = login("requester")
    body = {"origin": "MANUAL", "purpose_code": "F2F9_REVIEW", "plant": "P100", "lines": [_line()]}
    number = client.post("/v1/requisitions", json=body, headers=h).json()["number"]
    assert client.post(f"/v1/requisitions/{number}/cancel", json={"reason": ""}, headers=h).status_code == 422
    assert client.post(f"/v1/requisitions/{number}/cancel", json={"reason": "x"}, headers=login("buyer")).status_code == 403
    assert client.patch(f"/v1/requisitions/{number}/lines/10", json={"need_date": "2026-12-20"}, headers=login("buyer")).status_code == 403
    r = client.post(f"/v1/requisitions/{number}/cancel", json={"reason": "Raised twice"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"


# ---------------------------------------------------------------- 14 category plan rows are locked before reading
def test_category_budget_locks_the_plan_rows():
    with _rolled_back() as s:
        tenant_id = s.info["principal"].tenant_id
        s.add(CategoryPlan(tenant_id=tenant_id, number="CP-F2F9-LOCK", category="F2F9-LOCK", fiscal_year="2026-27", spend_minor=0,
                           profit_impact=Decimal(5), supply_risk=Decimal(5), kraljic="LEVERAGE", budget_minor=10 * L, status="APPROVED",
                           owner_id=s.info["principal"].user_id))
        s.flush()
        statements = []
        bind = s.get_bind()

        def capture(conn, cursor, statement, *args):
            statements.append(statement)

        event.listen(bind, "before_cursor_execute", capture)
        try:
            pr = SimpleNamespace(id=uuid.uuid4(), company_code="1000")
            line = SimpleNamespace(category="F2F9-LOCK", material_group="X", qty=Decimal(1), price_est_minor=L)
            result, _ = requisition.category_budget_check(s, pr, [line], None)
        finally:
            event.remove(bind, "before_cursor_execute", capture)
        assert result["checks"][0]["plan"] == "CP-F2F9-LOCK"
        assert any("category_plan" in st and "FOR UPDATE" in st for st in statements)


# ---------------------------------------------------------------- 13 punch-out
def _cart_session(s, cart) -> PunchoutSession:
    supplier = s.execute(select(Supplier).where(Supplier.code == "HTS004")).scalar_one()
    ps = PunchoutSession(tenant_id=supplier.tenant_id, supplier_id=supplier.id, user_id=s.info["principal"].user_id, protocol="CXML",
                         buyer_cookie=f"AXN.f2f9-{uuid.uuid4().hex[:16]}", cart=cart, status="RETURNED",
                         expires_at=clock.now() + timedelta(minutes=30), created_by=s.info["principal"].user_id)
    s.add(ps)
    s.flush()
    return ps


def test_punchout_unmatched_items_become_free_text_and_prices_are_checked():
    with _rolled_back() as s:
        catalogue = s.execute(select(CatalogueItem).where(CatalogueItem.supplier_part_no == "HTS-PM-STD")).scalar_one()
        matched = {"lineNo": 1, "supplierPartNo": "HTS-PM-STD", "description": "PM visit", "qty": "1", "uom": "EA",
                   "unitPriceMinor": int(catalogue.price_minor * Decimal("1.015")), "currency": "INR"}
        unmatched = {"lineNo": 2, "supplierPartNo": "HTS-XRAY-01", "description": "X-ray inspection of die inserts", "qty": "1", "uom": "EA",
                     "unitPriceMinor": 3_000_000, "currency": "INR", "materialGroup": "SVC-TOOLING"}
        pr = punchout.convert(s, _cart_session(s, [matched, unmatched]), plant="P100", purpose_code="F2F9_REVIEW")
        lines = {l.line_no: l for l in s.execute(select(PrLine).where(PrLine.requisition_id == pr.id)).scalars()}
        assert lines[10].item_type == "CATALOGUE" and lines[10].catalogue_item_id == catalogue.id
        assert lines[20].item_type == "FREE_TEXT" and lines[20].catalogue_item_id is None and lines[20].quotes_attached == 1
        assert lines[20].source_determination["quotes"][0]["supplier"] == "HTS004"
        assert requisition.submit(s, pr)["status"] == "IN_APPROVAL"  # one quote (the cart) for a ₹30,000 free-text line
        too_high = {**matched, "unitPriceMinor": int(catalogue.price_minor * Decimal("1.10"))}
        problem = _problem(punchout.convert, s, _cart_session(s, [too_high]), plant="P100", purpose_code="F2F9_REVIEW")
        assert problem.code == "CART_NOT_CONVERTIBLE" and "above the catalogue price" in problem.detail


# ---------------------------------------------------------------- 9 / 12 material-request merge and in-flight duplicates
DUP = {"description": "Aluminium die-cast housing DC-330", "type": "STOCK", "material_group": axion.CATEGORY, "category": axion.CATEGORY,
       "base_uom": "EA", "mpn": "AXN-DC-330", "attributes": {"alloy": "ADC12", "weight_kg": "1.2", "process": "HPDC"}}


def test_merge_is_restricted_to_requester_or_steward_and_listed_candidates():
    with _rolled_back("buyer") as s:
        request = mdm.create_request(s, **DUP)
        assert request.status == "DUPLICATE_BLOCKED" and request.duplicate_candidates[0]["material"] == "DC-330"
        dc330 = s.execute(select(Material).where(Material.number == "DC-330")).scalar_one()
        listed = {c["material"] for c in request.duplicate_candidates}
        other = s.execute(select(Material).where(Material.status == "ACTIVE", Material.number.notin_(listed))).scalars().first()
        _as(s, "requester")
        assert _problem(mdm.merge_into_existing, s, request, dc330).status == 403  # neither requester nor steward
        _as(s, "buyer")
        assert "not a duplicate candidate" in _problem(mdm.merge_into_existing, s, request, other).detail
        mdm.merge_into_existing(s, request, dc330)
        assert request.status == "MERGED" and request.merged_into_material_id == dc330.id
        assert _problem(mdm.merge_into_existing, s, request, dc330).code == "ILLEGAL_TRANSITION"


def test_in_flight_requests_are_duplicate_candidates_and_stewardship_merge_needs_a_steward():
    with _rolled_back("buyer") as s:
        fields = {"description": "Hydraulic die-spray manifold block 6-way, anodised", "type": "STOCK", "material_group": "41-FIXTURE",
                  "category": "TOOLING", "base_uom": "EA", "mpn": "AXN-SPRAY-6W", "attributes": {"ports": "6", "finish": "anodised"}}
        first = mdm.create_request(s, **fields)
        assert first.status == "IN_STEWARDSHIP"
        _as(s, "requester")
        second = mdm.create_request(s, **fields)
        candidate = second.duplicate_candidates[0]
        assert candidate["kind"] == "MATERIAL_REQUEST" and candidate["materialRequest"] == first.number
        assert second.status == "DUPLICATE_BLOCKED"
        dc330 = s.execute(select(Material).where(Material.number == "DC-330")).scalar_one()
        _as(s, "buyer")  # the requester of the first request; it is in stewardship
        assert _problem(mdm.merge_into_existing, s, first, dc330).status == 403
        _as(s, "mdm.purchasing")
        assert "not a duplicate candidate" in _problem(mdm.merge_into_existing, s, first, dc330).detail


# ---------------------------------------------------------------- 16 override reason, audit, promote guards
def test_override_needs_a_reason(client, login):
    assert client.post("/v1/materials/requests/MRQ-NONE/override", json={"reason": ""}, headers=login("mdm.purchasing")).status_code == 422
    with _rolled_back("buyer") as s:
        request = mdm.create_request(s, **DUP)
        _as(s, "mdm.purchasing")
        assert _problem(mdm.steward_override, s, request, "   ").status == 422


def test_material_request_status_changes_and_golden_record_are_audited():
    with _rolled_back("buyer") as s:
        approved = mdm.create_request(s, description="Ceramic filter foam 50 x 50 x 22 mm, 30 ppi, for aluminium ladle", type="NON_STOCK",
                                      material_group="FOUNDRY-CONS", category="MRO-FOUNDRY", base_uom="EA", mpn="AXN-CF-30PPI")
        rejected = mdm.create_request(s, description="Graphite ladle coating paste 5 kg pail, low sulphur", type="NON_STOCK",
                                      material_group="FOUNDRY-CONS", category="MRO-FOUNDRY", base_uom="KG", mpn="AXN-GLC-5")
        for task in s.execute(select(Task).where(Task.object_id == approved.id, Task.status == "OPEN")).scalars().all():
            local = "mdm." + task.candidate_scope["steward_domain"].lower()
            _as(s, local)
            workflow.complete(s, task.id, "APPROVE", "complete")
        task = s.execute(select(Task).where(Task.object_id == rejected.id, Task.status == "OPEN")).scalars().first()
        _as(s, "mdm." + task.candidate_scope["steward_domain"].lower())
        workflow.complete(s, task.id, "REJECT", "Use the existing coating material")

        def actions(object_id):
            return {a.action for a in s.execute(select(AuditEvent).where(AuditEvent.object_id == object_id)).scalars()}

        assert {"APPROVED"} <= actions(approved.id)
        if approved.status == "SYNCED_TO_ERP":
            assert "SYNCED_TO_ERP" in actions(approved.id)
        assert "CREATED" in actions(approved.material_id)
        assert "REJECTED" in actions(rejected.id) and rejected.status == "REJECTED"


def test_promote_material_guards():
    with _rolled_back() as s:
        pr = _pr(s, _line(), {"item_type": "MATERIAL", "purchase_type": "STOCK", "material": "DC-330", "qty": "10", "price_est_minor": 41_000,
                              "need_date": "2026-12-15"})
        free, material_line = sorted(s.execute(select(PrLine).where(PrLine.requisition_id == pr.id)).scalars(), key=lambda l: l.line_no)
        fields = {"description": "Pneumatic clamp kit for fixture rework, 4-jaw", "type": "NON_STOCK", "material_group": "41-FIXTURE",
                  "category": "TOOLING", "base_uom": "EA"}
        _as(s, "buyer")
        assert _problem(mdm.promote_line, s, pr, free, **fields).status == 403
        _as(s, "requester")
        assert _problem(mdm.promote_line, s, pr, material_line, **fields).status == 422
        request = mdm.promote_line(s, pr, free, **fields)
        assert free.mdm_request_id == request.id
        assert _problem(mdm.promote_line, s, pr, free, **fields).code == "ALREADY_PROMOTED"
        other = _pr(s, _line(description="Clamp spares kit"))
        requisition.cancel(s, other, "not needed")
        line = s.execute(select(PrLine).where(PrLine.requisition_id == other.id)).scalar_one()
        assert _problem(mdm.promote_line, s, other, line, **fields).code == "ILLEGAL_TRANSITION"
