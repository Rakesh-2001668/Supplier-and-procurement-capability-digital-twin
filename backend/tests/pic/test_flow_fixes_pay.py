"""Flow-audit fixes for receiving, invoice-to-pay, savings, AI and the platform (M09 to M12; docs/PIC_Workflow_Flow_Audit.md §3 #2, #5,
#6, #7, #12, #13, #15, #16 and the Workflow Guide's Appendix A A14, C1 to C8).

Service tests run in one AXN transaction that is rolled back at the end (orders, receipts, invoices and rule versions created inside it), so
the signature case and the KPIs other files check never change. API tests only read, or take paths refused before anything is written,
except the idempotent-replay test, which stores one idempotency record.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuditEvent, Contract, InspectionLot, IntegrationMessage, Invoice, InvoiceException, OutboxEvent, PoLine,
    PurchaseOrder, ReturnDelivery, RoleDef, RuleSet, SavingsInitiative, Supplier, Task, Tenant,
)
from app.pic.platform import clock, connectors, sap_mapping, workflow
from app.pic.platform.auth import Principal, scopes_for
from app.pic.platform.errors import Problem
from app.pic.platform.integration import ConnectorError
from app.pic.seed.axion import CATEGORY, ROLE_USER
from app.pic.services import copilot, delegation, job_handlers, jobs, order, payables, receiving, requisition, savings

BACKEND = Path(__file__).resolve().parents[2]


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
    s.info.pop(delegation_cache_key(), None)
    return user


def delegation_cache_key() -> str:
    from app.pic.platform import delegation as platform_delegation
    return platform_delegation.CACHE_KEY


def _as_roles(s, roles: list, attributes: dict = None, user_id=None) -> Principal:
    """A principal with any roles (built-in or the tenant's own) and, unless given, no user row."""
    uid = user_id or uuid.uuid4()
    p = Principal(uid, _axn(), "AXN", f"{uid.hex[:8]}@axion.example", "Test user", roles, scopes_for(roles, s), attributes or {}, None)
    s.info["principal"], s.info["user_id"] = p, uid
    return p


def _problem(fn, *args, **kwargs) -> Problem:
    with pytest.raises(Problem) as exc:
        fn(*args, **kwargs)
    return exc.value


def _approve(s, object_id, kind: str = None) -> int:
    done = 0
    for _ in range(12):
        query = select(Task).where(Task.object_id == object_id, Task.status == "OPEN")
        if kind:
            query = query.where(Task.kind == kind)
        tasks = s.execute(query.order_by(Task.sequence)).scalars().all()
        if not tasks:
            return done
        for task in tasks:
            who = ROLE_USER[task.candidate_role]
            for local in who if isinstance(who, list) else [who]:
                _as(s, local)
                if workflow.can_work(s.info["principal"], task) is None:
                    workflow.complete(s, task.id, "APPROVE", "Approved")
                    done += 1
                    break
    return done


def _po(s, lines: list[tuple], supplier: str = "TF001") -> PurchaseOrder:
    """(material, qty, price_est_minor) lines: requisition, approval, PO, approval and supplier confirmation inside the transaction."""
    _as(s, "buyer")
    reason = ("Flow-fix test purchase of fasteners from a supplier not yet qualified for FASTENERS: one-time exception"
              if any(m.startswith("FK-") for m, _, _ in lines) else None)
    pr = requisition.create(s, origin="MANUAL", purpose_code="BUFFER_BUILD", purpose_text="Flow fixes M09-M12 test", plant="P100",
                            lines=[{"item_type": "MATERIAL", "purchase_type": "STOCK", "material": m, "qty": str(q), "price_est_minor": p,
                                    "need_date": (clock.today() + timedelta(days=30)).isoformat(), "storage_location": "0001"} for m, q, p in lines])
    requisition.submit(s, pr)
    _approve(s, pr.id)
    _as(s, "buyer")
    po = order.create_from_requisition(s, requisition=pr.number, lines=[10 * (i + 1) for i in range(len(lines))], supplier_code=supplier,
                                       one_time_vendor_reason=reason)[0]
    _approve(s, po.id)
    _as(s, "tf.sales" if supplier == "TF001" else "kd.sales")
    order.confirm(s, po, "CONFIRMED")
    return po


def _service_po(s) -> PurchaseOrder:
    _as(s, "requester")
    pr = requisition.create(s, origin="MANUAL", purpose_code="MAINTENANCE", purpose_text="Flow fixes SES test", plant="P100",
                            lines=[{"item_type": "FREE_TEXT", "purchase_type": "SERVICE", "description": "Die polishing (T&M) - flow fix test",
                                    "material_group": "SVC-TOOLING", "category": "TOOLING-SERVICES", "qty": "10", "uom": "H",
                                    "price_est_minor": 300_000, "account_assignment_type": "COST_CENTER", "account_assignment_code": "4100",
                                    "need_date": (clock.today() + timedelta(days=30)).isoformat(),
                                    "quotes": [{"supplier": "HTS004", "reference": "HTS/Q/FIX3", "date": clock.today().isoformat()}]}])
    requisition.submit(s, pr)
    _approve(s, pr.id)
    _as(s, "buyer")
    po = order.create_from_requisition(s, requisition=pr.number, lines=[10], supplier_code="HTS004", unit_price_minor=300_000)[0]
    _approve(s, po.id)
    _as(s, "hts.service")
    order.confirm(s, po, "CONFIRMED")
    return po


def _lot(s, gr) -> InspectionLot:
    return s.execute(select(InspectionLot).where(InspectionLot.gr_id == gr.id).order_by(InspectionLot.number)).scalars().first()


def _batch(tag: str) -> str:
    return f"FX3-{tag}-{uuid.uuid4().hex[:6].upper()}"


def _invoice(s, po, qty: str, price: str, number: str = None, who: str = "tf.sales", supplier: str = "TF001") -> Invoice:
    _as(s, who)
    return payables.capture(s, supplier=supplier, supplier_invoice_no=number or f"FX3/{uuid.uuid4().hex[:8]}", invoice_date=clock.today(),
                            channel="PORTAL", lines=[{"po": po.number, "po_line": 10, "qty": qty, "unit_price": price, "gst_rate": "18"}])


def _events(s, topic: str, object_id) -> list[OutboxEvent]:
    s.flush()
    return s.execute(select(OutboxEvent).where(OutboxEvent.topic == topic, OutboxEvent.object_id == object_id)).scalars().all()


def _role(s, code: str, scopes: list[str]) -> None:
    s.add(RoleDef(tenant_id=_axn(), code=code, name=code.replace("_", " ").title(), scopes=scopes, active=True))
    s.flush()
    from app.pic.platform import roles as roles_mod
    roles_mod.forget(s)


def _rule(s, key: str, body: dict, company_code: str = None) -> None:
    s.add(RuleSet(tenant_id=_axn(), key=key, version=f"FX3-{uuid.uuid4().hex[:6]}", company_code=company_code,
                  effective_from=clock.today() - timedelta(days=1), body=body, description="flow fix 3 test"))
    s.flush()


# ================================================================ 1. C4: permissions, not built-in role names
def test_flowfix3_custom_role_with_payment_run_releases_a_payment_block(tx):
    s = tx
    invoice = s.execute(select(Invoice).where(Invoice.status == "POSTED", Invoice.payment_status == "UNPAID", Invoice.duplicate_of.is_(None))
                        .order_by(Invoice.number)).scalars().first()
    if invoice is None or payables.supplier_blocked(s, invoice) or s.execute(select(InvoiceException.id).where(
            InvoiceException.invoice_id == invoice.id, InvoiceException.status == "OPEN")).first():
        pytest.skip("no posted, unpaid invoice without exceptions in the signature case")
    invoice.payment_block = True
    s.flush()
    _role(s, "PAY_DESK", ["pic:read", "tasks:work", "payment:run"])
    _as_roles(s, ["AP_CLERK"])  # holds invoice:* but not payment:run
    assert _problem(payables.release_payment_block, s, invoice, "Block from the ERP load cleared").status == 403
    _as_roles(s, ["PAY_DESK"])
    assert payables.release_payment_block(s, invoice, "Block from the ERP load cleared").payment_block is False


def test_flowfix3_custom_role_with_savings_validate_validates_and_sod07_holds(tx):
    s = tx
    _as(s, "category.manager")
    initiative = savings.create_initiative(s, title="FX3 validation", category=CATEGORY, baseline_method="SHOULD_COST",
                                           annual_volume=Decimal(100), material_number="DC-330", baseline_price_minor=45000)
    savings.negotiate(s, initiative, 40000, "TF001", "Renegotiated rate")
    initiative.stage = "REALISING"  # (rolled back) realised from a posted invoice
    s.flush()
    _role(s, "SAV_DESK", ["pic:read", "tasks:work", "savings:validate"])
    _as_roles(s, ["CATEGORY_MANAGER"])
    assert _problem(savings.validate, s, initiative).status == 403
    _as_roles(s, ["SAV_DESK"])
    assert savings.validate(s, initiative).stage == "VALIDATED"


def test_flowfix3_category_team_may_negotiate_within_its_categories_and_sod07(tx):
    s = tx
    _as(s, "category.manager")
    initiative = savings.create_initiative(s, title="FX3 negotiate", category=CATEGORY, baseline_method="SHOULD_COST",
                                           annual_volume=Decimal(100), material_number="DC-330", baseline_price_minor=45000)
    _as_roles(s, ["CATEGORY_MANAGER"], {"categories": ["SOME-OTHER-CATEGORY"]})
    assert _problem(savings.negotiate, s, initiative, 40000, "TF001", "x").status == 403  # ABAC SAVINGS_MANAGE: not his category
    _as_roles(s, ["BUYER"])
    assert _problem(savings.negotiate, s, initiative, 40000, "TF001", "x").status == 403  # no savings:manage
    head = _user(s, "category.head")
    _as_roles(s, ["CATEGORY_MANAGER", "FINANCE_CONTROLLER"], {"categories": ["*"]}, user_id=head.id)
    assert savings.negotiate(s, initiative, 40000, "TF001", "Renegotiated by the category head").stage == "NEGOTIATED"
    initiative.stage = "REALISING"
    s.flush()
    problem = _problem(savings.validate, s, initiative)  # the co-initiator is SOD-07 bound like the owner
    assert problem.status == 409 and problem.code == "SOD_CONFLICT"


def test_flowfix3_ap_scopes_not_role_names_for_retention_and_reconciliation(tx):
    s = tx
    po = s.execute(select(PurchaseOrder).order_by(PurchaseOrder.number)).scalars().first()
    _as_roles(s, ["BUYER"])
    problem = _problem(payables.release_retention, s, po, reference="X", reason="Y")
    assert problem.status == 403 and "invoice:post or payment:run" in problem.detail
    _role(s, "AP_DESK", ["pic:read", "tasks:work", "invoice:post"])
    _as_roles(s, ["AP_DESK"])
    assert _problem(payables.release_retention, s, po, reference="X", reason="Y").status != 403  # past the permission check


# ================================================================ 2. C1: return deliveries close
def test_flowfix3_return_delivery_is_credited_by_the_credit_note(tx):
    s = tx
    po = _po(s, [("DC-330", 10, 40500)])
    _as(s, "receiver")
    gr = receiving.post_gr(s, po, lines=[{"line": 10, "qty": "10", "batch": _batch("C")}])
    _as(s, "quality.inspector")
    result = receiving.usage_decision(s, _lot(s, gr), accepted=Decimal(6), rejected=Decimal(4), defect_code="CRACK", reason="Cracked bosses")
    rd = s.execute(select(ReturnDelivery).where(ReturnDelivery.number == result["returnDelivery"])).scalar_one()
    assert rd.status == "CREATED" and rd.credit_note_expected
    invoice = _invoice(s, po, "10", "405.00")
    _as(s, "tf.sales")
    note = payables.submit_credit_note(s, invoice, supplier_credit_note_no=f"CN-FX3-{uuid.uuid4().hex[:6]}", note_date=clock.today(),
                                       reason="4 cracked parts returned", lines=[{"invoice_line": 10, "qty": "3"}])
    assert rd.status == "CREATED" and rd.settled_qty == 3  # partly covered
    payables.submit_credit_note(s, invoice, supplier_credit_note_no=f"CN-FX3-{uuid.uuid4().hex[:6]}", note_date=clock.today(),
                                reason="last cracked part", lines=[{"invoice_line": 10, "qty": "1"}])
    assert rd.status == "CREDITED" and rd.closed_at is not None and [x["type"] for x in rd.settlements] == ["CREDIT_NOTE", "CREDIT_NOTE"]
    assert note.number in [x["ref"] for x in rd.settlements]
    assert _events(s, "return_delivery.credited", rd.id)
    audit = [a.action for a in s.execute(select(AuditEvent).where(AuditEvent.object_id == rd.id).order_by(AuditEvent.seq)).scalars()]
    assert "PARTIALLY_SETTLED" in audit and "CREDIT" in audit
    assert _problem(receiving.close_return, s, rd, "Nothing more is due from the supplier").code == "ILLEGAL_TRANSITION"


def test_flowfix3_return_delivery_is_replaced_reopened_by_reversal_and_closed_by_hand(tx):
    s = tx
    po = _po(s, [("DC-330", 20, 40500)])
    _as(s, "receiver")
    gr = receiving.post_gr(s, po, lines=[{"line": 10, "qty": "20", "batch": _batch("R")}])
    _as(s, "quality.inspector")
    result = receiving.usage_decision(s, _lot(s, gr), accepted=Decimal(15), rejected=Decimal(5), defect_code="POROSITY", reason="Porosity",
                                      replacement=True)
    rd = s.execute(select(ReturnDelivery).where(ReturnDelivery.number == result["returnDelivery"])).scalar_one()
    assert rd.status == "REPLACEMENT_DUE"
    _as(s, "receiver")
    replacement = receiving.post_gr(s, po, lines=[{"line": 10, "qty": "5", "batch": _batch("R2")}])
    assert rd.status == "REPLACED" and rd.settlements[-1] == {**rd.settlements[-1], "type": "GOODS_RECEIPT", "ref": replacement.number}
    assert _events(s, "return_delivery.replaced", rd.id)
    receiving.reverse_gr(s, replacement, "Replacement posted against the wrong delivery note")
    assert rd.status == "REPLACEMENT_DUE" and rd.settled_qty == 0 and rd.closed_at is None
    _as(s, "quality.inspector")
    assert _problem(receiving.close_return, s, rd, "short").status == 422
    receiving.close_return(s, rd, "Supplier credited the five parts outside PIC (agreed by phone)")
    assert rd.status == "CLOSED" and rd.settlements[-1]["type"] == "MANUAL" and _events(s, "return_delivery.closed", rd.id)
    listing = receiving.list_returns(s, po=po.number)
    assert listing["total"] == 1 and listing["items"][0]["status"] == "CLOSED" and listing["items"][0]["openQty"] == "0"
    assert receiving.list_returns(s, po=po.number, open_only=True)["total"] == 0


def test_flowfix3_return_delivery_routes(client, login):
    r = client.get("/v1/return-deliveries", headers=login("receiver"))
    assert r.status_code == 200 and {"items", "total", "countsByStatus", "openValueMinor"} <= set(r.json())
    assert client.get("/v1/return-deliveries?status=NOPE", headers=login("receiver")).status_code == 422
    supplier = client.get("/v1/return-deliveries", headers=login("kd.sales"))
    assert supplier.status_code == 200 and all(i["supplier"] == "KD002" for i in supplier.json()["items"])
    assert client.get("/v1/return-deliveries/RD-NOPE-1", headers=login("receiver")).status_code == 404
    assert client.post("/v1/return-deliveries/RD-NOPE-1/close", json={"reason": "Nothing more is due here"},
                       headers=login("buyer")).status_code == 403


# ================================================================ 3. service entry sheets: the whole state machine
def test_flowfix3_ses_draft_submit_reject_resubmit_approve_revoke(tx):
    s = tx
    po = _service_po(s)
    _as(s, "hts.service")
    ses = receiving.create_ses(s, po, method="TIME_MATERIAL", period_from=clock.today(), period_to=clock.today(), lines=[{"line": 10, "qty": "4"}])
    assert ses.status == "DRAFT"
    receiving.resubmit_ses(s, ses)
    assert ses.status == "SUBMITTED"
    task = s.execute(select(Task).where(Task.object_id == ses.id, Task.status == "OPEN")).scalar_one()
    _as(s, "service.owner")
    workflow.complete(s, task.id, "REJECT", "Hours do not match the timesheet")
    assert ses.status == "REJECTED"
    _as(s, "hts.service")
    receiving.resubmit_ses(s, ses)
    assert ses.status == "SUBMITTED"
    assert _approve(s, ses.id, "SES_APPROVAL") == 1 and ses.status == "APPROVED"
    line = s.execute(select(PoLine).where(PoLine.po_id == po.id)).scalar_one()
    assert line.ses_approved_minor == ses.total_minor
    _as(s, "hts.service")
    assert _problem(receiving.resubmit_ses, s, ses).code == "ILLEGAL_TRANSITION"
    _as(s, "service.owner")
    assert _problem(receiving.revoke_ses, s, ses, "short").status == 422
    receiving.revoke_ses(s, ses, "Approved against the wrong timesheet week")
    assert ses.status == "REVOKED" and line.ses_approved_minor == 0 and _events(s, "service_entry.revoked", ses.id)


def test_flowfix3_ses_routes_exist(client, login):
    assert client.post("/v1/service-entries/SES-NOPE-1/submit", headers=login("hts.service")).status_code == 404
    assert client.get("/v1/service-entries/SES-NOPE-1", headers=login("service.owner")).status_code == 404
    assert client.post("/v1/service-entries/SES-NOPE-1/revoke", json={"reason": "wrong timesheet week"}, headers=login("service.owner")).status_code == 404
    assert client.post("/v1/service-entries/SES-NOPE-1/reject", json={"reason": "wrong"}, headers=login("buyer")).status_code == 403


# ================================================================ 4. C6: Copilot finds the tenant's own document numbers
def test_flowfix3_copilot_finds_invoice_numbers_of_any_format(tx):
    s = tx
    invoices = s.execute(select(Invoice).where(Invoice.supplier_id == s.execute(select(Supplier.id).where(Supplier.code == "TF001")).scalar_one())
                         .order_by(Invoice.created_at).limit(3)).scalars().all()
    if len(invoices) < 3:
        pytest.skip("signature case has fewer than three TF001 invoices")
    invoices[0].supplier_invoice_no = "SSPL-A-0001"
    invoices[1].number = "KAC/26-27/0311"
    invoices[2].number = "MTW-0001"
    s.flush()
    _as(s, "ap.clerk")
    principal = s.info["principal"]
    for question, expected in (("status of invoice SSPL-A-0001?", invoices[0].number), ("where is KAC/26-27/0311", "KAC/26-27/0311"),
                               ("what about mtw-0001", "MTW-0001"), ("status of PO-77410", "PO-77410")):
        answer = copilot.ask(s, principal, question)
        assert answer["confidence"]["score"] >= 0.9 and answer["evidence"][0]["ref"] == expected, (question, answer)
    assert copilot.ask(s, principal, "status of XYZ-99999")["confidence"]["score"] < 0.5
    assert copilot.ask(s, principal, "status of INV-NOPE-1")["answer"].startswith("INV-NOPE-1 was not found")
    _as(s, "kd.sales")  # another supplier's invoice stays invisible
    assert "not found or is not visible" in copilot.ask(s, s.info["principal"], "status of SSPL-A-0001")["answer"]
    assert copilot.candidate_numbers("spend on 12/11/2026 of 1,200.50") == []


# ================================================================ 5. A14, C6, C7: scheduled jobs
def _ctx(s, key: str, dry_run: bool = False, params: dict = None) -> jobs.JobContext:
    s.info["principal"] = jobs.scheduler_principal(_axn())
    return jobs.JobContext(session=s, tenant_id=_axn(), job_key=key, trigger="MANUAL", dry_run=dry_run, params=params or {}, now=clock.now(),
                           requested_by="test")


def test_flowfix3_jobs_are_registered_with_schedules():
    expected = {"erp-sync-masters": "0 1 * * *", "erp-sync-stock": "20 * * * *", "erp-sync-open-pos": "40 1 * * *",
                "erp-sync-payment-status": "50 * * * *", "erp-sync-planned-orders": "30 0 * * *", "erp-sync-retry": "10 */4 * * *",
                "kpi-snapshot-monthly": "15 0 1 * *", "ml-drift-check": "0 4 * * *", "ml-retrain": "0 5 * * 0"}
    for key, schedule in expected.items():
        assert jobs.REGISTRY[key].schedule == schedule and jobs.REGISTRY[key].dry_run


def test_flowfix3_erp_sync_jobs_follow_rule_and_source(tx, monkeypatch, tmp_path):
    s = tx
    monkeypatch.delenv("PIC_ERP_SYNC_DROP_DIR", raising=False)
    monkeypatch.delenv("PIC_ERP_SYNC_SFTP_HOST", raising=False)
    assert job_handlers.erp_sync_stock(_ctx(s, "erp-sync-stock"))["note"].startswith("rule ERP-SYNC is off")
    _rule(s, "ERP-SYNC", {"enabled": True, "kinds": {"STOCK": True, "PLANNED_ORDERS": False}})
    assert "nothing to pull" in job_handlers.erp_sync_stock(_ctx(s, "erp-sync-stock"))["note"]  # simulator, no file drop
    monkeypatch.setenv("PIC_ERP_SYNC_DROP_DIR", str(tmp_path))
    out = job_handlers.erp_sync_stock(_ctx(s, "erp-sync-stock", dry_run=True))
    assert out["action"] == "SYNC" and "file drop" in out["source"]
    assert job_handlers.erp_sync_planned_orders(_ctx(s, "erp-sync-planned-orders", dry_run=True))["action"] == "none"
    assert job_handlers.validate_rule("ERP-SYNC", {"enabled": "yes", "kinds": {"NOPE": True}}) and not job_handlers.validate_rule(
        "ERP-SYNC", {"enabled": True, "kinds": {"STOCK": False}})


def test_flowfix3_kpi_snapshot_and_model_jobs(tx):
    s = tx
    from app.pic.models import KpiSnapshot
    out = job_handlers.kpi_snapshot_monthly(_ctx(s, "kpi-snapshot-monthly", params={"period": "2026-10"}))
    assert out["period"] == "2026-10" and out["kpis"] > 0
    assert s.execute(select(KpiSnapshot).where(KpiSnapshot.period == "2026-10")).scalars().first() is not None
    with pytest.raises(Problem):
        job_handlers.kpi_snapshot_monthly(_ctx(s, "kpi-snapshot-monthly", params={"period": "2026-13"}))
    drift = job_handlers.ml_drift_check(_ctx(s, "ml-drift-check"))
    assert drift["errors"] == [] and "checked" in drift
    retrain = job_handlers.ml_retrain(_ctx(s, "ml-retrain", dry_run=True))
    assert {m["code"] for m in retrain["models"]} == {"demand_forecast", "late_delivery", "invoice_exception_cause"}
    assert retrain["autoActivate"] is False
    _rule(s, "AI-RETRAIN", {"driftCheck": False, "retrain": False})
    assert job_handlers.ml_drift_check(_ctx(s, "ml-drift-check"))["action"] == "none"
    assert job_handlers.ml_retrain(_ctx(s, "ml-retrain"))["action"] == "none"


# ================================================================ 6. C3: invoice approval chain by value band
def test_flowfix3_invoice_approval_chain_by_value_band_with_delegation_and_sod(tx):
    s = tx
    _rule(s, "INVOICE-APPROVAL", {"bands": [{"fromMinor": 0, "approvers": ["FINANCE_CONTROLLER"]}], "slaBusinessDays": 2}, company_code="1000")
    po = _po(s, [("FK-M8-50", 100, 1250)])
    _as(s, "receiver")
    receiving.post_gr(s, po, lines=[{"line": 10, "qty": "100"}])
    invoice = _invoice(s, po, "100", "12.50")
    assert invoice.status == "MATCHED"
    _as(s, "ap.clerk")
    payables.approve(s, invoice)
    assert invoice.status == "MATCHED"  # waiting for the band's approver
    state = payables.approval_state(s, invoice)
    assert state["status"] == "PENDING" and state["requiredChain"] == ["FINANCE_CONTROLLER"] and state["steps"][0]["role"] == "FINANCE_CONTROLLER"
    assert _problem(payables.approve, s, invoice).code == "APPROVAL_PENDING"
    task = payables.open_approval_tasks(s, invoice)[0]
    # ABAC value limit of the approver applies to the task
    fc2 = _user(s, "finance.controller2")
    fc2.attributes = {**(fc2.attributes or {}), "value_limit_minor": 100}
    s.flush()
    _as(s, "finance.controller2")
    assert _problem(workflow.complete, s, task.id, "APPROVE", "ok").status == 403
    # delegation of authority: the finance controller is away, the procurement head approves for him
    _as(s, "finance.controller")
    delegation.create(s, delegator_id=None, delegate_id=_user(s, "procurement.head").id, valid_from=clock.today(),
                      valid_to=clock.today() + timedelta(days=5), roles=["FINANCE_CONTROLLER"], value_limit_minor=None, reason="Annual leave")
    _as(s, "procurement.head")
    assert task.id in [t.id for t in workflow.open_tasks_for(s, s.info["principal"])]
    workflow.complete(s, task.id, "APPROVE", "Approved for the finance controller")
    assert invoice.status == "APPROVED" and payables.approval_state(s, invoice)["status"] == "APPROVED"
    assert task.evidence.get(workflow.DELEGATED_KEY) == str(_user(s, "finance.controller").id)
    from app.pic.platform import sod
    # SOD-09: everyone who approved (AP and the chain) is recorded and may not release the payment
    for local in ("ap.clerk", "procurement.head"):
        _as(s, local)
        with pytest.raises(Problem) as exc:
            sod.guard(s, "PAYMENT_APPROVE", {"invoice_id": invoice.id})
        assert exc.value.code == "SOD_CONFLICT"


def test_flowfix3_invoice_approval_rejected_returns_to_ap_and_is_clarified(tx):
    s = tx
    _rule(s, "INVOICE-APPROVAL", {"bands": [{"fromMinor": 0, "approvers": ["FINANCE_CONTROLLER"]}]}, company_code="1000")
    po = _po(s, [("FK-M8-50", 50, 1250)])
    _as(s, "receiver")
    receiving.post_gr(s, po, lines=[{"line": 10, "qty": "50"}])
    invoice = _invoice(s, po, "50", "12.50")
    _as(s, "ap.clerk")
    payables.approve(s, invoice)
    task = payables.open_approval_tasks(s, invoice)[0]
    _as(s, "finance.controller")
    workflow.complete(s, task.id, "REJECT", "Cost centre not budgeted this quarter")
    assert invoice.status == "EXCEPTION" and invoice.payment_block
    exc = s.execute(select(InvoiceException).where(InvoiceException.invoice_id == invoice.id, InvoiceException.status == "OPEN")).scalar_one()
    assert exc.type == "APPROVAL" and _events(s, "invoice.exception.raised", invoice.id)
    _as(s, "ap.clerk")
    assert _problem(payables.resolve_exception, s, invoice, exc.id, "GR_POSTED", "x").code == "INVALID_RESOLUTION"
    payables.resolve_exception(s, invoice, exc.id, "CLARIFIED", "Budget moved; finance agreed")
    assert invoice.status == "MATCHED"
    payables.approve(s, invoice)
    assert len(payables.open_approval_tasks(s, invoice)) == 1  # a new chain


def test_flowfix3_no_band_keeps_single_ap_approval_and_rule_validation(tx):
    s = tx
    po = _po(s, [("FK-M8-50", 40, 1250)])
    _as(s, "receiver")
    receiving.post_gr(s, po, lines=[{"line": 10, "qty": "40"}])
    invoice = _invoice(s, po, "40", "12.50")
    _as(s, "ap.clerk")
    assert payables.approve(s, invoice).status == "APPROVED" and not payables.open_approval_tasks(s, invoice)
    assert payables.validate_approval_rule("INVOICE-APPROVAL", {"bands": [{"fromMinor": -1, "approvers": ["X"]}]})
    assert payables.validate_approval_rule("INVOICE-APPROVAL", {"bands": [{"fromMinor": 0, "approvers": ["SUPPLIER_USER"]}]})
    assert not payables.validate_approval_rule("INVOICE-APPROVAL", {"bands": [{"fromMinor": 100, "approvers": ["FINANCE_CONTROLLER", "CPO"]}]})


def test_flowfix3_invoice_view_carries_the_approval_state(client, login):
    r = client.get("/v1/invoices", headers=login("ap.clerk"))
    assert r.status_code == 200
    items = r.json()["items"] if isinstance(r.json(), dict) else r.json()
    one = client.get(f"/v1/invoices/{items[0]['id']}", headers=login("ap.clerk"))
    assert one.status_code == 200 and {"status", "requiredChain", "steps", "myTaskId"} <= set(one.json()["approval"])
    assert client.post(f"/v1/invoices/{items[0]['id']}/approval/decision", json={"decision": "APPROVE"}, headers=login("cpo")).status_code == 403


# ================================================================ 7. C5: volume-shortfall leakage
def test_flowfix3_volume_shortfall_against_the_negotiated_volume(tx):
    s = tx
    _as(s, "category.manager")
    initiative = savings.create_initiative(s, title="FX3 volume", category="TOOLING-SERVICES", baseline_method="SHOULD_COST",
                                           annual_volume=Decimal(1000), material_number="DC-330", baseline_price_minor=45000)
    savings.negotiate(s, initiative, 40000, "HTS004", "Rate agreed")
    start = clock.today()
    out = savings.volume_shortfall(s, initiative, as_of=start + timedelta(days=90))
    line = out["lines"][0]
    assert line["basis"] == "INITIATIVE_VOLUME" and line["invoicedQty"] == "0"
    assert line["expectedToDateQty"] == "249.315" and line["shortfallQty"] == "249.315" and line["unitSavingMinor"] == 5000
    assert line["shortfallMinor"] == 1_246_575 and out["shortfallMinor"] == 1_246_575 and len(line["periods"]) >= 3
    leakage = savings.waterfall(s, initiative)["leakage"]
    assert any(item["kind"] == "VOLUME_SHORTFALL" and item["amountMinor"] > 0 for item in leakage)


def test_flowfix3_volume_shortfall_per_contract_line_of_the_signature_case(tx):
    s = tx
    initiative = s.execute(select(SavingsInitiative).where(SavingsInitiative.source_event_id.is_not(None))
                           .order_by(SavingsInitiative.number)).scalars().first()
    if initiative is None or not s.execute(select(Contract.id).where(Contract.source_event_id == initiative.source_event_id)).first():
        pytest.skip("no award-driven initiative with contracts")
    contract = s.execute(select(Contract).where(Contract.source_event_id == initiative.source_event_id)).scalars().first()
    volume = savings.volume_shortfall(s, initiative, as_of=contract.valid_from + timedelta(days=200))
    assert volume["lines"] and all(l["basis"] == "CONTRACT_LINE" for l in volume["lines"])
    for l in volume["lines"]:
        assert Decimal(l["shortfallQty"]) == max(Decimal(l["expectedToDateQty"]) - Decimal(l["invoicedQty"]), Decimal(0)).quantize(Decimal("0.001"))
    assert "volume" in savings.waterfall(s, initiative)


# ================================================================ 8. Audit #16: SoD 409 on invite, replay header, duplicate-hold event, label
def test_flowfix3_invite_with_sod_pair_answers_409(client, login):
    r = client.post("/v1/admin/users", json={"email": f"fx3.{uuid.uuid4().hex[:6]}@axion.example", "name": "Counter Approver",
                                             "roles": ["RECEIVER", "INVENTORY_CONTROLLER"]}, headers=login("admin"))
    assert r.status_code == 409 and r.json()["code"] == "SOD_CONFLICT" and "SOD-11" in r.text


def test_flowfix3_route_level_replay_sets_the_idempotent_replayed_header(client, login):
    key = f"fx3-replay-{uuid.uuid4().hex}"
    headers = {**login("admin"), "Idempotency-Key": key}
    first = client.post("/v1/ai/models/copilot/drift-check", headers=headers)
    second = client.post("/v1/ai/models/copilot/drift-check", headers=headers)
    assert first.status_code == 200 and first.headers.get("Idempotent-Replayed") is None
    assert second.status_code == 200 and second.headers.get("Idempotent-Replayed") == "true" and second.json().get("replayed") is True


def test_flowfix3_duplicate_hold_emits_invoice_exception_raised(tx):
    s = tx
    po = _po(s, [("FK-M8-50", 60, 1250)])
    _as(s, "receiver")
    receiving.post_gr(s, po, lines=[{"line": 10, "qty": "60"}])
    _invoice(s, po, "30", "12.50")
    held = _invoice(s, po, "30", "12.50")  # same supplier, amount and date: DMN-03 hold
    assert held.status == "EXCEPTION" and held.duplicate_of is not None
    events = _events(s, "invoice.exception.raised", held.id)
    assert events and events[0].payload["exceptions"][0]["type"] == "DUPLICATE"


def test_flowfix3_inventory_screen_has_its_own_screen_id():
    page = (BACKEND.parent / "frontend" / "src" / "app" / "pic" / "inventory" / "page.tsx").read_text(encoding="utf-8")
    assert "INV-01" not in page and "STK-01 · Inventory" in page


# ================================================================ 9. C2: live ERP payloads
CTX = {"version": 2, "today": date(2026, 11, 20), "reference": "GR|GR-90234|102", "company": "1710", "vendor": "17300001", "tax_code": "V1"}


def test_flowfix3_sap_goods_receipt_movement_from_the_document():
    items = [{"material": "DC-330", "plant": "P100", "storageLocation": "0001", "po": "4500000123", "poItem": 10, "qty": "100", "uom": "EA",
              "batch": "B1"}]
    spec = sap_mapping.goods_receipt({"gr": "GR-90234", "movement": "102"}, CTX, items)
    assert spec.body["GoodsMovementCode"] == "01" and spec.body["MaterialDocumentHeaderText"] == "GR|GR-90234|102"
    assert spec.body["to_MaterialDocumentItem"]["results"] == [{
        "Material": "DC-330", "Plant": "P100", "StorageLocation": "0001", "GoodsMovementType": "102", "PurchaseOrder": "4500000123",
        "PurchaseOrderItem": "00010", "QuantityInEntryUnit": "100.000", "EntryUnit": "EA", "GoodsMovementRefDocType": "B", "Batch": "B1"}]
    assert sap_mapping.goods_receipt({"gr": "GR-1"}, CTX, items).body["to_MaterialDocumentItem"]["results"][0]["GoodsMovementType"] == "101"
    xml = sap_mapping.idoc_xml("GOODS_RECEIPT", {"gr": "GR-90234", "movement": "102"}, CTX, {"lines": items})
    assert "<MOVE_TYPE>102</MOVE_TYPE>" in xml and "<BATCH>B1</BATCH>" in xml
    with pytest.raises(ValueError):
        sap_mapping.gr_movement({"movement": "122"})
    with pytest.raises(ConnectorError):
        connectors.get("SAP_S4")._gr_items(None, {"gr": "GR-1", "movement": "102", "reverses": "5000001", "lines": []})


def test_flowfix3_sap_supplier_debit_memo_golden_payload():
    spec = sap_mapping.supplier_debit_memo(
        {"debitNote": "DN-1", "supplierDebitNote": "SSPL-DN-0001", "grossMinor": 59000, "invoiceErp": "5100004422"},
        {**CTX, "reference": "AXN|1000|TF001|SSPL-A-0001|DN|DN-1"},
        [{"po": "4500000123", "poItem": 10, "netMinor": 30000, "qty": "20", "uom": "EA"}, {"glAccount": "510000", "netMinor": 20000, "text": "FREIGHT"}])
    assert spec.service == "API_SUPPLIERINVOICE_PROCESS_SRV" and spec.entity_set == "A_SupplierInvoice" and spec.number_field == "SupplierInvoice"
    body = spec.body
    assert body["SupplierInvoiceIsCreditMemo"] is False and body["InvoiceGrossAmount"] == "590.00" and body["SupplierInvoiceIDByInvcgParty"] == "SSPL-DN-0001"
    assert body["DocumentHeaderText"] == "AXN|1000|TF001|SSPL-A-000" and body["AssignmentReference"] == "5100004422"
    assert body["to_SuplrInvcItemPurOrdRef"]["results"] == [{
        "SupplierInvoiceItem": "1", "PurchaseOrder": "4500000123", "PurchaseOrderItem": "00010", "DocumentCurrency": "INR",
        "SupplierInvoiceItemAmount": "300.00", "QuantityInPurchaseOrderUnit": "20.000", "PurchaseOrderQuantityUnit": "EA",
        "IsSubsequentDebitCredit": "X", "TaxCode": "V1"}]
    assert body["to_SuplrInvcItemAcctAssgmt"]["results"] == [{
        "SupplierInvoiceItem": "2", "CompanyCode": "1710", "GLAccount": "510000", "DocumentCurrency": "INR", "SupplierInvoiceItemAmount": "200.00",
        "DebitCreditCode": "S", "SupplierInvoiceItemText": "FREIGHT", "TaxCode": "V1"}]
    assert "SUPPLIER_DEBIT_MEMO" in sap_mapping.MESSAGE_TYPES and "SUPPLIER_DEBIT_MEMO" not in sap_mapping.IDOC_TYPES
    assert set(sap_mapping.UNMAPPED_LIVE) == {"PAYMENT_REVERSAL", "SCF_FINANCING"}


def test_flowfix3_gr_reversal_message_carries_the_received_lines(tx):
    s = tx
    po = _po(s, [("FK-M8-50", 100, 1250)])
    _as(s, "receiver")
    gr = receiving.post_gr(s, po, lines=[{"line": 10, "qty": "100"}])
    receiving.reverse_gr(s, gr, "Posted against the wrong delivery note")
    s.flush()
    messages = {m.idempotency_key: m for m in s.execute(select(IntegrationMessage).where(IntegrationMessage.object_id == gr.id)).scalars()}
    original, reversal = messages[f"GR|{gr.number}"], messages[f"GR|{gr.number}|102"]
    assert reversal.payload["movement"] == "102" and reversal.payload["lines"] == original.payload["lines"]
    assert reversal.payload["lines"][0]["accepted"] == "100.000" or Decimal(reversal.payload["lines"][0]["accepted"]) == 100


# ================================================================ follow-ups: engineer 2's number ranges and the ABAC-scoped task inbox (B7)
def test_flowfix3_copilot_resolves_the_new_sourcing_and_contract_number_ranges(tx):
    from app.pic.models import SourcingEvent
    s = tx
    event = s.execute(select(SourcingEvent).order_by(SourcingEvent.created_at)).scalars().first()
    contract = s.execute(select(Contract).order_by(Contract.created_at)).scalars().first()
    event.number, contract.number = "RFP-3101", "QC-6103"  # (rolled back) numbers of the new RFP- and QC- ranges
    s.flush()
    _as(s, "category.head")
    principal = s.info["principal"]
    for question, kind in (("status of RFP-3101", "SOURCING_EVENT"), ("where is QC-6103?", "CONTRACT")):
        answer = copilot.ask(s, principal, question)
        assert answer["confidence"]["score"] >= 0.9 and answer["evidence"][0]["type"] == kind, (question, answer)
        assert answer["evidence"][0]["ref"] == question.split()[-1].rstrip("?")


def test_flowfix3_task_inbox_hides_tasks_outside_the_approver_abac_scope(tx):
    from app.pic.models import BankChangeRequest, SupplierBankAccount
    s = tx
    _rule(s, "INVOICE-APPROVAL", {"bands": [{"fromMinor": 0, "approvers": ["FINANCE_CONTROLLER"]}]}, company_code="1000")
    po = _po(s, [("FK-M8-50", 30, 1250)])
    _as(s, "receiver")
    receiving.post_gr(s, po, lines=[{"line": 10, "qty": "30"}])
    invoice = _invoice(s, po, "30", "12.50")
    _as(s, "ap.clerk")
    payables.approve(s, invoice)
    task = payables.open_approval_tasks(s, invoice)[0]
    inbox = lambda: [t.id for t in workflow.open_tasks_for(s, s.info["principal"])]  # noqa: E731
    _as_roles(s, ["FINANCE_CONTROLLER"])
    assert task.id in inbox()
    _as_roles(s, ["FINANCE_CONTROLLER"], {"value_limit_minor": 100})          # value limit below the invoice
    assert task.id not in inbox()
    _as_roles(s, ["FINANCE_CONTROLLER"], {"company_codes": ["9999"]})          # another company code
    assert task.id not in inbox()
    with pytest.raises(Problem) as exc:                                         # and the guard still refuses at completion
        workflow.complete(s, task.id, "APPROVE", "ok")
    assert exc.value.status == 403
    # supplier master governance: a bank change of a supplier outside the approver's categories is not listed
    supplier = s.execute(select(Supplier).where(Supplier.code == "TF001")).scalar_one()
    account = s.execute(select(SupplierBankAccount).where(SupplierBankAccount.supplier_id == supplier.id)).scalars().first()
    change = BankChangeRequest(tenant_id=_axn(), number=f"BCR-FX3-{uuid.uuid4().hex[:6]}", supplier_id=supplier.id, bank_account_id=account.id,
                               status="PENDING_APPROVAL", requested_by=_user(s, "supplier.manager").id)
    s.add(change)
    s.flush()
    bank_task = Task(tenant_id=_axn(), kind="BANK_CHANGE", name="Bank change test", object_type="BANK_CHANGE", object_id=change.id,
                     object_ref=change.number, candidate_role="FINANCE_CONTROLLER", candidate_scope={}, excluded_user_ids=[],
                     group_key=f"BANK_CHANGE:{change.id}", sequence=1, status="OPEN", due_at=clock.now() + timedelta(days=2))
    s.add(bank_task)
    s.flush()
    _as_roles(s, ["FINANCE_CONTROLLER"], {"categories": ["MRO-ONLY"]})
    assert bank_task.id not in inbox()
    _as_roles(s, ["FINANCE_CONTROLLER"], {"categories": ["*"]})
    assert bank_task.id in inbox()
