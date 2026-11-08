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
| erp-sync-masters / -stock / -open-pos / -payment-status / -planned-orders / -retry | 01:00 / hourly :20 / 01:40 / hourly :50 / 00:30 / every 4 h | inbound ERP sync per kind (rule ERP-SYNC, off by default) |
| kpi-snapshot-monthly | 1st, 00:15 | stores the previous month's KPI values (kpi_snapshot) |
| ml-drift-check     | daily 04:00     | drift check of the trained M12 models; an alert suspends and falls back (rule AI-RETRAIN) |
| ml-retrain         | Sunday 05:00    | retrains due models into candidates for review (rule AI-RETRAIN autoActivate) |
| supplier-risk-scan | daily 05:00     | Supplier Risk Agent scan of every supplier (services/risk.py) |
| sanctions-rescreen | daily 04:30     | refreshes the licensed sanctions list and re-screens live suppliers; a new match blocks (services/supplier.py) |
| rebate-accrual     | daily 03:15     | accrues every active rebate agreement for its current period (services/rebates.py) |
| bid-offer-expiry   | daily 00:30     | flags bids whose offer validity passed before the award and tells the event owner (services/sourcing.py) |
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
          description="Reconciles the posted invoices, payments and credit memos and the released purchase orders of every company code "
                      "with the ERP documents (count, amount, status, PO version) and notifies finance when there are differences.")
def erp_reconciliation(ctx: jobs.JobContext) -> dict:
    from app.pic.services import payables
    session = ctx.session
    results, errors = [], []
    for company in session.execute(select(CompanyCode).order_by(CompanyCode.code)).scalars().all():
        posted = session.execute(select(func.count()).select_from(Invoice).where(
            Invoice.company_code == company.code, Invoice.posting_key.is_not(None), Invoice.status.in_(("POSTED", "PAID")))).scalar_one()
        from app.pic.models import PurchaseOrder
        from app.pic.services import order as order_svc
        orders = session.execute(select(func.count()).select_from(PurchaseOrder).where(
            PurchaseOrder.company_code == company.code, PurchaseOrder.status.in_(order_svc.PO_IN_ERP + ("CANCELLED",)))).scalar_one()
        if not posted and not orders:
            continue
        system = integration.target_system(session, company.code)
        if ctx.dry_run:
            results.append({"companyCode": company.code, "system": system, "invoices": posted, "purchaseOrders": orders})
            continue
        try:
            with session.begin_nested():
                view = payables.reconcile(session, company.code, system) if posted else {"number": None, "differences": 0, "items": []}
                po_items = order_svc.reconcile_purchase_orders(session, company.code, system)  # flow fixes B9: POs too
                if po_items or view["number"] is None:
                    po_run = order_svc.add_reconciliation_items(session, view["number"], company.code, system, po_items)
                    view = {**view, "number": po_run["run"], "differences": po_run["differences"],
                            "items": list(view.get("items") or []) + [{"kind": i[0]} for i in po_items]}
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


# ================================================================ flow fixes (engineer 3): inbound ERP sync, KPI month-end snapshot, model drift
# and retraining (Audit #12: A14, C6, C7). Each is a registered job with a schedule; what it does is governed by a rule (ERP-SYNC is off by default).
ERP_SYNC_DEFAULTS = {"enabled": False, "system": None,
                     "kinds": {"MASTERS": True, "STOCK": True, "OPEN_POS": True, "PAYMENT_STATUS": True, "PLANNED_ORDERS": False}, "retryFailed": True}
AI_RETRAIN_DEFAULTS = {"driftCheck": True, "retrain": True, "retrainAfterDays": 30, "retrainOnDrift": True, "autoActivate": False,
                       "models": ["demand_forecast", "late_delivery", "invoice_exception_cause"]}
SYNC_GROUPS = {"MASTERS": "sync_masters", "STOCK": "sync_stock", "OPEN_POS": "sync_open_pos", "PAYMENT_STATUS": "sync_payment_status",
               "PLANNED_ORDERS": "sync_planned_orders"}
TRAINABLE = ("demand_forecast", "late_delivery", "invoice_exception_cause", "price_trend")


def validate_rule(key: str, body: dict) -> list[str]:
    """Problems of an ERP-SYNC or AI-RETRAIN rule body (POST /v1/admin/rules)."""
    problems: list[str] = []
    if key == "ERP-SYNC":
        if not isinstance(body.get("enabled", False), bool):
            problems.append("enabled must be true or false")
        kinds = body.get("kinds", {})
        if not isinstance(kinds, dict) or any(k not in SYNC_GROUPS or not isinstance(v, bool) for k, v in kinds.items()):
            problems.append(f"kinds maps {', '.join(SYNC_GROUPS)} to true/false")
        system = body.get("system")
        if system is not None:
            from app.pic.platform import connectors
            if str(system).upper() not in connectors.REGISTRY:
                problems.append(f"system {system} is not a known connector")
    elif key == "AI-RETRAIN":
        for flag in ("driftCheck", "retrain", "retrainOnDrift", "autoActivate"):
            if flag in body and not isinstance(body[flag], bool):
                problems.append(f"{flag} must be true or false")
        days = body.get("retrainAfterDays", 30)
        if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 366:
            problems.append("retrainAfterDays must be 1-366")
        models = body.get("models", [])
        if not isinstance(models, list) or any(m not in TRAINABLE for m in models):
            problems.append(f"models must list some of {', '.join(TRAINABLE)}")
    return problems


def _sync_source(system: str) -> tuple[bool, str]:
    """Is there anything to pull from: a live connector (OData pull), the file drop or SFTP (the source order of services/erp_sync.py)."""
    import os
    from app.pic.platform import connectors
    from app.pic.services import erp_sync
    connector = connectors.get(system)
    if connector.configured() and not connector.simulator:
        return True, f"{system} connector (live pull)"
    if erp_sync.drop_dir() is not None:
        return True, f"file drop {erp_sync.drop_dir()}"
    if os.environ.get("PIC_ERP_SYNC_SFTP_HOST"):
        return True, "SFTP landing folder"
    return False, f"{system} is the sandbox simulator or not configured and no file drop / SFTP is set: nothing to pull"


def _erp_sync(ctx: jobs.JobContext, group: str) -> dict:
    body, rule_ref = ctx.rule("ERP-SYNC", ERP_SYNC_DEFAULTS)
    cfg = {**ERP_SYNC_DEFAULTS, **body, "kinds": {**ERP_SYNC_DEFAULTS["kinds"], **(body.get("kinds") or {})}}
    if not cfg.get("enabled"):
        return {"action": "none", "note": "rule ERP-SYNC is off (enabled=false)", "rule": rule_ref}
    if group != "RETRY" and not cfg["kinds"].get(group):
        return {"action": "none", "note": f"rule ERP-SYNC does not sync {group}", "rule": rule_ref}
    if group == "RETRY" and not cfg.get("retryFailed", True):
        return {"action": "none", "note": "rule ERP-SYNC retryFailed is false", "rule": rule_ref}
    system = str(cfg.get("system") or integration.target_system(ctx.session)).upper()
    available, source = _sync_source(system)
    if not available:
        return {"action": "none", "note": source, "system": system, "rule": rule_ref}
    if ctx.dry_run:
        return {"action": "SYNC", "group": group, "system": system, "source": source, "rule": rule_ref}
    from app.pic.services import erp_sync
    triggered = f"scheduler:{ctx.job_key}" if ctx.trigger == "SCHEDULE" else (ctx.requested_by or "manual")
    if group == "RETRY":
        runs = erp_sync.retry_failed(ctx.tenant_id, triggered_by=triggered)
    else:
        runs = getattr(erp_sync, SYNC_GROUPS[group])(ctx.tenant_id, system=system, mode="SCHEDULED" if ctx.trigger == "SCHEDULE" else "ON_DEMAND",
                                                    triggered_by=triggered)
    errors = [f"{r.get('kind')}: {r.get('error') or r.get('status')}"[:300] for r in runs if r.get("status") in ("FAILED", "SKIPPED")]
    return {"action": "SYNCED", "group": group, "system": system, "source": source, "rule": rule_ref, "errors": errors,
            "runs": [{"run": r.get("number"), "kind": r.get("kind"), "status": r.get("status"), "counts": r.get("counts")} for r in runs]}


_SYNC_HELP = (" Governed by rule ERP-SYNC (enabled=false by default; kinds, system, retryFailed); it pulls from the live connector, the file "
              "drop or SFTP as configured and does nothing when no source is configured. Runs and rejects are in the ERP sync monitor.")


@jobs.job("erp-sync-masters", name="ERP sync: masters", schedule="0 1 * * *", dry_run=True, timeout_seconds=1800,
          description="Inbound sync of plants, cost objects, vendors and materials from the ERP (delta since the cursor; bank and tax-ID differences "
                      "become MDM-04 change requests)." + _SYNC_HELP)
def erp_sync_masters(ctx: jobs.JobContext) -> dict:
    return _erp_sync(ctx, "MASTERS")


@jobs.job("erp-sync-stock", name="ERP sync: stock levels", schedule="20 * * * *", dry_run=True, timeout_seconds=1800,
          description="Inbound sync of stock levels from the ERP, hourly." + _SYNC_HELP)
def erp_sync_stock(ctx: jobs.JobContext) -> dict:
    return _erp_sync(ctx, "STOCK")


@jobs.job("erp-sync-open-pos", name="ERP sync: open purchase orders", schedule="40 1 * * *", dry_run=True, timeout_seconds=1800,
          description="Inbound sync of the ERP's open purchase orders, reconciled against PIC's (differences are findings)." + _SYNC_HELP)
def erp_sync_open_pos(ctx: jobs.JobContext) -> dict:
    return _erp_sync(ctx, "OPEN_POS")


@jobs.job("erp-sync-payment-status", name="ERP sync: payment status", schedule="50 * * * *", dry_run=True, timeout_seconds=1800,
          description="Inbound sync of the payment status (clearing) of posted invoices, hourly." + _SYNC_HELP)
def erp_sync_payment_status(ctx: jobs.JobContext) -> dict:
    return _erp_sync(ctx, "PAYMENT_STATUS")


@jobs.job("erp-sync-planned-orders", name="ERP sync: planned orders", schedule="30 0 * * *", dry_run=True, timeout_seconds=1800,
          description="Inbound sync of the ERP's planned orders (AD-05 import; off in the default rule)." + _SYNC_HELP)
def erp_sync_planned_orders(ctx: jobs.JobContext) -> dict:
    return _erp_sync(ctx, "PLANNED_ORDERS")


@jobs.job("erp-sync-retry", name="ERP sync: retry failed kinds", schedule="10 */4 * * *", dry_run=True, timeout_seconds=1800,
          description="Runs again every object kind whose last sync failed (its cursor did not move, so nothing is skipped)." + _SYNC_HELP)
def erp_sync_retry(ctx: jobs.JobContext) -> dict:
    return _erp_sync(ctx, "RETRY")


@jobs.job("kpi-snapshot-monthly", name="KPI month-end snapshot", schedule="15 0 1 * *", dry_run=True,
          description="Stores the closed month's value of every KPI (kpi_snapshot) for the trend and the KPI explorer, on the 1st for the "
                      "previous month; idempotent (a rerun refreshes the month). Manual runs accept {\"period\": \"YYYY-MM\"}.")
def kpi_snapshot_monthly(ctx: jobs.JobContext) -> dict:
    from app.pic.services import kpi
    period = str(ctx.params.get("period") or previous_period(clock.today()))
    if not (len(period) == 7 and period[4] == "-" and period[:4].isdigit() and period[5:].isdigit() and 1 <= int(period[5:]) <= 12):
        raise Problem(422, "INVALID_PERIOD", "period must be YYYY-MM")
    if ctx.dry_run:
        return {"period": period, "kpis": len(kpi.applicable(ctx.session, include_other_templates=False)), "action": "SNAPSHOT"}
    return {**kpi.snapshot_kpis(ctx.tenant_id, period, session=ctx.session), "action": "SNAPSHOT"}


def _admins(session) -> list:
    return [u for u in notifications.users_with_role(session, "TENANT_ADMIN") if u.supplier_id is None]


@jobs.job("ml-drift-check", name="Model drift check", schedule="0 4 * * *", dry_run=True,
          description="Compares the live data of every trained, active M12 model with its training baseline (PSI on the features, live against "
                      "offline accuracy). An alert suspends the version and re-activates the previous one (ml_registry.check_drift) and notifies "
                      "the administrators. Rule AI-RETRAIN driftCheck switches it off.")
def ml_drift_check(ctx: jobs.JobContext) -> dict:
    from app.pic.services import ml_models, ml_registry
    body, rule_ref = ctx.rule("AI-RETRAIN", AI_RETRAIN_DEFAULTS)
    cfg = {**AI_RETRAIN_DEFAULTS, **body}
    if not cfg.get("driftCheck", True):
        return {"action": "none", "note": "rule AI-RETRAIN driftCheck is false", "rule": rule_ref}
    session = ctx.session
    results, errors = [], []
    for code in ml_registry.BASELINES:
        model = ml_registry.active(session, code)
        if model is None or ml_registry.is_baseline(code, model.version):
            continue
        if ctx.dry_run:
            results.append({"code": code, "version": model.version, "wouldCheck": True})
            continue
        try:
            with session.begin_nested():
                features = ml_models.late_drift_inputs(session)["features"] if code == ml_models.LATE else None
                result = ml_registry.check_drift(session, code, features=features)
            results.append(result)
            if result.get("alerts"):
                notifications.notify(session, _admins(session), kind="MODEL_DRIFT", dedup_key=f"MODEL_DRIFT:{code}:{model.version}:{clock.today()}",
                                     title=f"Model drift: {code}@{model.version}",
                                     body=f"{'; '.join(result['alerts'])}. The version was suspended and the previous one re-activated; retrain "
                                          "and review it in the model registry.", link="/pic/agents", object_type="ML_MODEL",
                                     object_ref=f"{code}@{model.version}")
        except Exception as exc:  # noqa: BLE001 - one model must not stop the others
            errors.append(f"{code}: {type(exc).__name__}: {getattr(exc, 'detail', None) or exc}"[:300])
    return {"checked": results, "alerts": sum(len(r.get("alerts") or []) for r in results), "errors": errors, "rule": rule_ref}


def _retrain_due(session, code: str, cfg: dict, now) -> tuple[bool, str]:
    from app.pic.models import MlDriftEvent
    from app.pic.services import ml_registry
    model = ml_registry.active(session, code)
    if model is None or ml_registry.is_baseline(code, model.version):
        return True, "no trained version is active (built-in baseline in use)"
    if cfg.get("retrainOnDrift", True) and session.execute(select(MlDriftEvent.id).where(
            MlDriftEvent.code == code, MlDriftEvent.version == model.version, MlDriftEvent.status == "ALERT").limit(1)).first():
        return True, "drift alert on the active version"
    trained = model.trained_at or model.activated_at
    if trained is not None and now - trained >= timedelta(days=int(cfg.get("retrainAfterDays", 30))):
        return True, f"trained {(now - trained).days} days ago (rule: every {cfg.get('retrainAfterDays', 30)} days)"
    return False, "trained recently, no drift"


@jobs.job("ml-retrain", name="Model retraining", schedule="0 5 * * 0", dry_run=True, timeout_seconds=1800,
          description="Retrains the M12 models listed in rule AI-RETRAIN that are due (no trained version active, a drift alert, or older than "
                      "retrainAfterDays) from the tenant's own data. A retrained version is registered as a CANDIDATE and the administrators are "
                      "asked to review it, unless autoActivate is true and it passes its evaluation gate. A version that is already active or "
                      "suspended cannot be re-registered under the same label: that case is reported for a new model release.")
def ml_retrain(ctx: jobs.JobContext) -> dict:
    from app.pic.services import ml_models, ml_registry
    from app.pic.tools import ai_train
    body, rule_ref = ctx.rule("AI-RETRAIN", AI_RETRAIN_DEFAULTS)
    cfg = {**AI_RETRAIN_DEFAULTS, **body}
    if not cfg.get("retrain", True):
        return {"action": "none", "note": "rule AI-RETRAIN retrain is false", "rule": rule_ref}
    session, activate = ctx.session, bool(cfg.get("autoActivate"))
    def _demand():
        # No evaluable history (rolling origin needs 8+ periods with actuals): nothing to train, no empty candidate for review.
        if not ml_models.evaluate_demand(ml_models.demand_series(session))["points"]:
            return {"trained": False, "reason": "no demand history with actuals to evaluate against"}
        return ml_models.train_demand(session, activate)

    trainers = {"demand_forecast": _demand,
                "late_delivery": lambda: ml_models.train_late_delivery(session, activate=activate),
                "invoice_exception_cause": lambda: ml_models.train_exception_cause(session, activate),
                "price_trend": lambda: ai_train.train_price_trend(session, activate)}
    if not ctx.dry_run:
        ml_registry.ensure_baselines(session)
    results, errors, candidates = [], [], []
    for code in [m for m in cfg.get("models") or [] if m in trainers]:
        due, why = _retrain_due(session, code, cfg, clock.now())
        if not due:
            results.append({"code": code, "retrain": False, "reason": why})
            continue
        if ctx.dry_run:
            results.append({"code": code, "retrain": True, "reason": why})
            continue
        try:
            with session.begin_nested():
                out = trainers[code]()
            trained = out.get("trained", True) and out.get("model") is not None
            results.append({"code": code, "retrain": True, "reason": why, "trained": trained, "activated": out.get("activated", False),
                            "version": (out.get("model") or {}).get("version"), "note": out.get("reason")})
            if trained and not out.get("activated"):
                candidates.append(f"{code}@{out['model']['version']}")
        except Problem as exc:
            results.append({"code": code, "retrain": True, "reason": why, "trained": False, "note": exc.detail})
            if exc.code == "MODEL_VERSION_EXISTS":
                errors.append(f"{code}: {exc.detail}")
        except Exception as exc:  # noqa: BLE001 - one model must not stop the others
            errors.append(f"{code}: {type(exc).__name__}: {exc}"[:300])
    if candidates and not ctx.dry_run:
        notifications.notify(session, _admins(session), kind="MODEL_RETRAINED", dedup_key=f"MODEL_RETRAINED:{clock.today()}:{','.join(candidates)}",
                             title=f"{len(candidates)} retrained model version(s) to review",
                             body=f"{', '.join(candidates)} were retrained and wait as candidates: review the evaluation and activate them in the "
                                  "model registry.", link="/pic/agents", object_type="ML_MODEL", object_ref=candidates[0])
    return {"models": results, "candidates": candidates, "errors": errors, "autoActivate": activate, "rule": rule_ref}
