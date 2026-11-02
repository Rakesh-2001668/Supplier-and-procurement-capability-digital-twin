"""The scheduled jobs of the platform (registered with ``services.jobs.job``; TD §8 F1/F7, §12.2, §15, BP M06/M13).

| key                | default schedule (tenant time zone) | what it does |
| payment-due        | daily 06:30     | proposes the payment run for invoices falling due or whose discount window closes (rule PAYMENT-RUN); never pays by itself |
| erp-reconciliation | daily 01:30     | reconciles platform postings with the ERP per company code |
| mrp-schedule       | daily 02:00     | runs MRP for the plants listed in rule MRP-SCHEDULE |
| scorecard-monthly  | 1st, 03:00      | recomputes the previous month's supplier scorecards from the source documents |
| retention-purge    | daily 03:30     | applies rule PRIVACY-RETENTION (dry-run until the rule says otherwise) |
| audit-archive      | Sunday 04:00    | moves old audit events to the verified archive (dry-run until the rule says otherwise) |
| idempotency-purge  | hourly :15      | deletes Idempotency-Key records older than 24 hours |
| inventory-reservations | daily 02:45 | expires stock reservations past their need date plus grace (rule INVENTORY-RESERVATION) |
"""
import uuid
from datetime import date, timedelta

from sqlalchemy import delete, func, select

from app.pic.models import CompanyCode, IdempotencyRecord, Invoice, MrpRun, Plant, Supplier, Task
from app.pic.platform import audit, clock, integration, workflow
from app.pic.platform.errors import Problem
from app.pic.services import jobs, notifications, planning, privacy

PROPOSAL_KIND = "PAYMENT_RUN_PROPOSAL"
PROPOSAL_TYPE = "PAYMENT_PROPOSAL"
PROPOSAL_LIST_CAP = 500
IDEMPOTENCY_TTL = timedelta(hours=24)
PAYMENT_RUN_DEFAULTS = {"horizonDays": 3, "autoRun": False, "approverRole": "FINANCE_CONTROLLER", "slaBusinessDays": 1}


# ---------------------------------------------------------------- 1 payment-due trigger (F7-07)
def _proposal_id(tenant_id: uuid.UUID, run_date: date) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"pic-payment-proposal:{tenant_id}:{run_date.isoformat()}")


def _proposal_detail(session, horizon: date) -> dict:
    """What a run would pay (amounts net of credit notes, TDS and discount), MSME invoices and why some are skipped: the same assessment the
    payment run makes (payables.payment_proposal), so the approver sees what will happen. Best effort: the job never fails on it."""
    from app.pic.services import finance_controls, payables
    try:
        proposal = payables.payment_proposal(session, horizon, include_not_due=False)
    except Exception as exc:  # noqa: BLE001 - the detail is advisory, the proposal itself must still be raised
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}
    msme = [i for i in proposal["items"] if i["msme"]]
    return {"items": proposal["items"][:PROPOSAL_LIST_CAP], "skipped": proposal["skipped"][:PROPOSAL_LIST_CAP], "payableMinor": proposal["totalMinor"],
            "msme": {"count": len(msme), "overdue": sum(1 for i in msme if i["overdueDays"] > 0),
                     "capped": sum(1 for i in msme if i["msmeCapped"])}, "maxDays": finance_controls.rule_body(session, "MSME", finance_controls.MSME_DEFAULT).get("maxDays")}


def _discount_windows(session, today: date, horizon_days: int, exclude: set) -> list[dict]:
    """Posted, unpaid invoices that are not yet due but whose terms discount (2/10 N30) closes within the horizon: paying them in time earns
    the discount, so the approver is asked now. Taking the discount is decided by the approver (see ``_proposal_decided``)."""
    from app.pic.platform.money import pct_of
    from app.pic.services import early_payment
    rows = session.execute(select(Invoice).where(
        Invoice.status == "POSTED", Invoice.payment_status == "UNPAID", Invoice.payment_block.is_(False), Invoice.payment_option == "STANDARD",
        Invoice.due_date.is_not(None), Invoice.number.not_in(exclude or {""}))
        .order_by(Invoice.invoice_date, Invoice.number).limit(2000)).scalars().all()
    windows = []
    for invoice in rows:
        terms = early_payment.terms_discount(session, invoice)
        if terms is None or not today <= terms[1] <= today + timedelta(days=horizon_days):
            continue
        windows.append({"invoice": invoice.number, "discountPct": str(terms[0]), "closesOn": terms[1].isoformat(), "dueDate": invoice.due_date.isoformat(),
                        "discountMinor": pct_of(early_payment.payable_base(session, invoice), terms[0])})
    return windows[:PROPOSAL_LIST_CAP]


@jobs.job("payment-due", name="Payment-due trigger", schedule="30 6 * * *", dry_run=True,
          description="Finds posted, unpaid, unblocked invoices that fall due within the horizon (rule PAYMENT-RUN horizonDays; MSME invoices "
                      "fall due 45 days after acceptance) and invoices whose early-payment discount closes within it, and asks the finance "
                      "controller to approve the payment run. It never pays by itself: the rule's autoRun flag is ignored by policy, the "
                      "approver's decision runs the normal payment run (supplier status, bank checks, SoD, blocks).")
def payment_due(ctx: jobs.JobContext) -> dict:
    body, rule_ref = ctx.rule("PAYMENT-RUN", PAYMENT_RUN_DEFAULTS)
    cfg = {**PAYMENT_RUN_DEFAULTS, **body}
    today = clock.today()
    horizon = today + timedelta(days=int(cfg["horizonDays"]))
    session = ctx.session
    due = session.execute(select(Invoice).where(
        Invoice.status == "POSTED", Invoice.payment_status == "UNPAID", Invoice.payment_block.is_(False),
        Invoice.due_date.is_not(None), Invoice.due_date <= horizon).order_by(Invoice.due_date, Invoice.number)).scalars().all()
    windows = _discount_windows(session, today, int(cfg["horizonDays"]), {i.number for i in due})
    summary = {"horizon": horizon.isoformat(), "due": len(due), "totalMinor": sum(i.gross_minor for i in due), "rule": rule_ref,
               "discountWindows": len(windows), **({"autoRunIgnored": True} if cfg.get("autoRun") else {})}
    if not due and not windows:
        return {**summary, "action": "none"}
    if ctx.dry_run:
        return {**summary, "action": "PROPOSE", "invoices": [i.number for i in due[:50]], "windows": [w["invoice"] for w in windows[:50]]}
    proposal_id = _proposal_id(ctx.tenant_id, today)
    existing = session.execute(select(Task).where(Task.kind == PROPOSAL_KIND, Task.object_id == proposal_id)
                               .order_by(Task.created_at.desc())).scalars().first()
    if existing is not None:
        return {**summary, "action": "PROPOSAL_EXISTS", "proposal": existing.object_ref, "taskStatus": existing.status}
    ref = f"PAYPROP-{today.isoformat()}"
    by_supplier: dict[str, int] = {}
    codes = {s.id: s.code for s in session.execute(select(Supplier).where(Supplier.id.in_({i.supplier_id for i in due}))).scalars()}
    for i in due:
        by_supplier[codes.get(i.supplier_id, "?")] = by_supplier.get(codes.get(i.supplier_id, "?"), 0) + i.gross_minor
    detail = _proposal_detail(session, horizon) if due else {}
    workflow.start_approval(
        session, None, PROPOSAL_KIND, object_type=PROPOSAL_TYPE, object_id=proposal_id, object_ref=ref, chain=[cfg["approverRole"]],
        step_id=None, initiator_id=None, sla_business_days=int(cfg["slaBusinessDays"]), rule_set_version=rule_ref,
        evidence={"runDate": today.isoformat(), "horizon": horizon.isoformat(), "count": len(due), "totalMinor": summary["totalMinor"],
                  "invoices": [i.number for i in due[:PROPOSAL_LIST_CAP]], "truncated": len(due) > PROPOSAL_LIST_CAP,
                  "bySupplierMinor": dict(sorted(by_supplier.items(), key=lambda kv: -kv[1])[:20]),
                  "proposal": detail, "discountWindows": windows})
    audit.record(session, PROPOSAL_TYPE, proposal_id, "PAYMENT_RUN_PROPOSED", object_ref=ref, rule_set_version=rule_ref,
                 after={"invoices": len(due), "totalMinor": summary["totalMinor"], "approver": cfg["approverRole"], "discountWindows": len(windows),
                        "msme": (detail.get("msme") or {}).get("count", 0)})
    return {**summary, "action": "PROPOSED", "proposal": ref}


@workflow.on_task(PROPOSAL_KIND)
def _proposal_decided(session, task, outcome: str) -> None:
    """The finance controller decides the proposal: approving runs the payment run for the proposed invoices as that person
    (so the payment SoD, bank and block checks apply to them); rejecting records why nothing is paid."""
    from app.pic.services import payables
    evidence = task.evidence or {}
    if outcome != "APPROVED":
        audit.record(session, PROPOSAL_TYPE, task.object_id, f"PAYMENT_RUN_{outcome}", object_ref=task.object_ref, reason=task.comment)
        return
    p = session.info["principal"]
    if "payment:run" not in p.scopes:
        raise Problem(403, "FORBIDDEN", "Approving a payment-run proposal executes the payment run, which needs the payment:run scope",
                      rule_ref="PAYMENT-RUN")
    run_date = clock.today()
    # Discount windows: the approver takes the terms discount (as accounts payable would); what cannot be taken is reported, not paid early.
    from app.pic.services import early_payment
    numbers = list(evidence.get("invoices") or [])
    taken, not_taken = [], []
    for window in evidence.get("discountWindows") or []:
        invoice = session.execute(select(Invoice).where(Invoice.number == window["invoice"])).scalar_one_or_none()
        if invoice is None or invoice.status != "POSTED" or invoice.payment_status != "UNPAID":
            not_taken.append({"invoice": window["invoice"], "reason": "no longer payable"})
            continue
        try:
            with session.begin_nested():
                early_payment.make_offer(session, invoice, discount_pct=None, pay_on=None, note="Taken with the approved payment-run proposal", source="TERMS")
            taken.append(invoice.number)
        except Problem as exc:
            not_taken.append({"invoice": invoice.number, "reason": exc.detail})
    numbers += taken
    result = payables.payment_run(session, run_date, include_not_due=True, invoice_numbers=numbers or None)
    task.evidence = {**evidence, "result": {"run": result["run"], "paid": len(result["paid"]), "skipped": result["skipped"],
                                            "discountTaken": taken, "discountNotTaken": not_taken}}
    audit.record(session, PROPOSAL_TYPE, task.object_id, "PAYMENT_RUN_EXECUTED", object_ref=task.object_ref,
                 after={"run": result["run"], "paid": len(result["paid"]), "skipped": len(result["skipped"])})


# ---------------------------------------------------------------- 2 nightly ERP reconciliation (TD §12.2 step 5)
@jobs.job("erp-reconciliation", name="Nightly ERP reconciliation", schedule="30 1 * * *", dry_run=True,
          description="Reconciles the posted invoices, payments and credit memos of every company code with the ERP documents (count, "
                      "amount, status) and notifies finance when there are differences.")
def erp_reconciliation(ctx: jobs.JobContext) -> dict:
    from app.pic.services import payables
    session = ctx.session
    results, errors = [], []
    for company in session.execute(select(CompanyCode).order_by(CompanyCode.code)).scalars().all():
        posted = session.execute(select(func.count()).select_from(Invoice).where(
            Invoice.company_code == company.code, Invoice.posting_key.is_not(None), Invoice.status.in_(("POSTED", "PAID")))).scalar_one()
        if not posted:
            continue
        system = integration.target_system(session, company.code)
        if ctx.dry_run:
            results.append({"companyCode": company.code, "system": system, "invoices": posted})
            continue
        try:
            with session.begin_nested():
                view = payables.reconcile(session, company.code, system)
                if view["differences"]:
                    finance = [u for role in ("FINANCE_CONTROLLER", "AP_CLERK") for u in notifications.users_with_role(session, role)
                               if u.supplier_id is None]
                    kinds = sorted({i["kind"] for i in view["items"]})
                    notifications.notify(
                        session, finance, kind="RECONCILIATION_DIFFERENCES", dedup_key=f"RECONCILIATION:{view['number']}",
                        title=f"ERP reconciliation {view['number']}: {view['differences']} difference(s)",
                        body=f"Company code {company.code} against {system}: {view['differences']} difference(s) ({', '.join(kinds)}). "
                             "Review and resolve the items.", link="/pic/invoices", object_type="RECONCILIATION_RUN", object_ref=view["number"])
            results.append({"companyCode": company.code, "system": system, "run": view["number"], "differences": view["differences"]})
        except Exception as exc:  # noqa: BLE001 - one company code must not stop the others
            errors.append(f"{company.code}: {type(exc).__name__}: {getattr(exc, 'detail', None) or exc}"[:300])
    return {"companyCodes": results, "differences": sum(r.get("differences", 0) for r in results), "errors": errors}


# ---------------------------------------------------------------- 3 scheduled MRP per plant (F1)
MRP_DEFAULTS = {"plants": [], "mode": "NET_CHANGE", "overlapMinutes": 120}


@jobs.job("mrp-schedule", name="Scheduled MRP run", schedule="0 2 * * *", dry_run=True,
          description="Runs MRP for each plant listed in rule MRP-SCHEDULE ({\"plants\": [\"1000\"], \"mode\": \"NET_CHANGE\"}); a plant "
                      "whose previous run is still RUNNING is skipped. Does nothing until the rule names plants.")
def mrp_schedule(ctx: jobs.JobContext) -> dict:
    body, rule_ref = ctx.rule("MRP-SCHEDULE", MRP_DEFAULTS)
    cfg = {**MRP_DEFAULTS, **body}
    session = ctx.session
    plants = [p if isinstance(p, dict) else {"plant": p} for p in cfg["plants"]]
    if not plants:
        return {"plants": [], "note": "no plant is listed in rule MRP-SCHEDULE", "rule": rule_ref}
    known = set(session.execute(select(Plant.code)).scalars())
    results, errors = [], []
    for entry in plants:
        plant, mode = entry["plant"], str(entry.get("mode") or cfg["mode"]).upper()
        if plant not in known:
            errors.append(f"{plant}: unknown plant")
            continue
        running = session.execute(select(MrpRun.number).where(
            MrpRun.plant == plant, MrpRun.status == "RUNNING",
            MrpRun.created_at > ctx.now - timedelta(minutes=int(cfg["overlapMinutes"])))).scalars().first()
        if running:
            results.append({"plant": plant, "skipped": f"{running} is still running"})
            continue
        if ctx.dry_run:
            results.append({"plant": plant, "mode": mode, "wouldRun": True})
            continue
        try:
            with session.begin_nested():
                run = planning.run(session, plant=plant, mode=mode, materials=entry.get("materials"))
            results.append({"plant": plant, "mode": mode, "run": run.number, "materials": run.materials_planned,
                            "plannedOrders": run.planned_orders_created, "exceptions": run.exceptions_raised})
        except Exception as exc:  # noqa: BLE001 - one plant must not stop the others
            errors.append(f"{plant}: {type(exc).__name__}: {getattr(exc, 'detail', None) or exc}"[:300])
    return {"plants": results, "errors": errors, "rule": rule_ref}


# ---------------------------------------------------------------- 4 monthly supplier scorecards (M06)
def previous_period(today: date) -> str:
    first = today.replace(day=1)
    last_month = first - timedelta(days=1)
    return last_month.strftime("%Y-%m")


@jobs.job("scorecard-monthly", name="Monthly supplier scorecards", schedule="0 3 1 * *", dry_run=True,
          description="Recomputes the previous month's supplier scorecards (OTIF, PPM, invoice accuracy) from the goods receipts and "
                      "invoices themselves and corrects any drift from the event-driven counters. Idempotent per month. "
                      "Manual runs accept {\"period\": \"YYYY-MM\"}.")
def scorecard_monthly(ctx: jobs.JobContext) -> dict:
    from app.pic.services import supplier
    period = str(ctx.params.get("period") or previous_period(clock.today()))
    return supplier.recalculate_scorecards(ctx.session, period, dry_run=ctx.dry_run)


# ---------------------------------------------------------------- 5 retention purge and audit archive (TD §15, M13)
@jobs.job("retention-purge", name="Data retention purge", schedule="30 3 * * *", dry_run=True,
          description="Applies rule PRIVACY-RETENTION: deletes notifications, delivered events, fired timers and job history past their "
                      "retention, and pseudonymises users deactivated longer than user_profile.days. Dry run until the rule sets "
                      "purge.dryRun=false. Statutory records and the audit trail are never touched here.")
def retention_purge(ctx: jobs.JobContext) -> dict:
    body, rule_ref = ctx.rule("PRIVACY-RETENTION")
    dry = ctx.dry_run or bool((body.get("purge") or {}).get("dryRun", True))
    result = privacy.apply_retention(ctx.session, dry_run=dry, rule_ref=rule_ref)
    return {**result, "dryRun": dry, "rule": rule_ref, "requestedDryRun": ctx.dry_run}


@jobs.job("audit-archive", name="Audit trail archive", schedule="0 4 * * 0", dry_run=True,
          description="Moves audit events older than the hot window (rule PRIVACY-RETENTION audit_archive.hotDays, default 730) to the "
                      "audit archive in verified batches. The hash chain keeps verifying across the archive through the batch "
                      "checkpoint; archived events are dropped only after the statutory retention (audit_actor.days, default 8 years).")
def audit_archive(ctx: jobs.JobContext) -> dict:
    body, rule_ref = ctx.rule("PRIVACY-RETENTION")
    dry = ctx.dry_run or bool((body.get("purge") or {}).get("dryRun", True))
    result = privacy.archive_audit(ctx.session, dry_run=dry, rule_ref=rule_ref)
    return {**result, "dryRun": dry, "rule": rule_ref, "requestedDryRun": ctx.dry_run}


# ---------------------------------------------------------------- 6 idempotency records (TD §10)
@jobs.job("idempotency-purge", name="Expired idempotency records", schedule="15 * * * *", dry_run=True,
          description="Deletes Idempotency-Key records older than 24 hours (the replay window of every POST).")
def idempotency_purge(ctx: jobs.JobContext) -> dict:
    cutoff = ctx.now - IDEMPOTENCY_TTL
    query = IdempotencyRecord.created_at < cutoff
    if ctx.dry_run:
        return {"wouldDelete": ctx.session.execute(select(func.count()).select_from(IdempotencyRecord).where(query)).scalar_one(),
                "cutoff": cutoff.isoformat()}
    deleted = ctx.session.execute(delete(IdempotencyRecord).where(query)).rowcount or 0
    return {"deleted": deleted, "cutoff": cutoff.isoformat()}


# ---------------------------------------------------------------- 7 reservation expiry (inventory)
@jobs.job("inventory-reservations", name="Reservation expiry", schedule="45 2 * * *", dry_run=True,
          description="Expires the open stock reservations whose need date plus the grace of rule INVENTORY-RESERVATION (graceDays) has passed: "
                      "the open quantity is released from the demand MRP sees, the reservation is EXPIRED and audited. Also removes the zero-quantity "
                      "reservation demand that net-change MRP has had a week to see.")
def inventory_reservations(ctx: jobs.JobContext) -> dict:
    from app.pic.services import inventory
    return inventory.expire_due(ctx.session, dry_run=ctx.dry_run)
