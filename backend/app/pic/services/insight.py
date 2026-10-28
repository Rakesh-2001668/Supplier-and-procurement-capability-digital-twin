"""AIX-01 command centre KPIs (blueprint §27) computed from transactions, never stored."""
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.pic.models import (
    AgentRun, AuditEvent, IntegrationMessage, Invoice, InvoiceException, PurchaseOrder, Requisition, SavingsLedgerEntry, SodViolation,
    SpendLine, Supplier, SupplierCategoryStatus, Task,
)
from app.pic.platform import clock, workflow
from app.pic.platform.money import crore


def _pct(num, den) -> str | None:
    return str((Decimal(num) * 100 / Decimal(den)).quantize(Decimal("0.1"))) if den else None


def _counts(session: Session, column) -> dict:
    return {k: v for k, v in session.execute(select(column, func.count()).group_by(column)).all()}


def dashboard(session: Session, principal) -> dict:
    spend_total = session.execute(select(func.coalesce(func.sum(SpendLine.amount_minor), 0))).scalar()
    contracted = session.execute(select(func.coalesce(func.sum(SpendLine.amount_minor), 0)).where(SpendLine.contracted.is_(True))).scalar()
    maverick = session.execute(select(func.coalesce(func.sum(SpendLine.amount_minor), 0)).where(
        func.jsonb_array_length(SpendLine.maverick_flags) > 0)).scalar()
    released = session.execute(select(func.count(), func.sum(case((PurchaseOrder.touchless.is_(True), 1), else_=0))).where(
        PurchaseOrder.released_at.is_not(None))).one()
    matched = session.execute(select(func.count(), func.sum(case((Invoice.first_pass_matched.is_(True), 1), else_=0))).where(
        Invoice.first_pass_matched.is_not(None))).one()
    cycle = session.execute(select(func.avg(func.extract("epoch", Requisition.approved_at - Requisition.submitted_at))).where(
        Requisition.approved_at.is_not(None))).scalar()
    ledger = {k: v for k, v in session.execute(select(SavingsLedgerEntry.type, func.sum(SavingsLedgerEntry.amount_minor))
                                               .group_by(SavingsLedgerEntry.type)).all()}
    integration = _counts(session, IntegrationMessage.status)
    posted = integration.get("POSTED", 0)
    attempted = sum(integration.values())
    categories = _counts(session, SupplierCategoryStatus.status)
    open_tasks = session.execute(select(func.count()).select_from(Task).where(Task.status == "OPEN")).scalar()
    overdue = session.execute(select(func.count()).select_from(Task).where(Task.status == "OPEN", Task.due_at < clock.now())).scalar()
    mine = len(workflow.open_tasks_for(session, principal)) if "tasks:work" in principal.scopes else 0
    activity = [{"ts": e.ts.isoformat(), "objectType": e.object_type, "objectRef": e.object_ref, "action": e.action, "actor": e.actor}
                for e in session.execute(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(15)).scalars()]
    return {
        "asOf": clock.now().isoformat(),
        "spend": {"totalMinor": spend_total, "contractCoveragePct": _pct(contracted, spend_total), "maverickPct": _pct(maverick, spend_total)},
        "purchasing": {"touchlessPct": _pct(released[1] or 0, released[0]), "released": released[0],
                       "byStatus": _counts(session, PurchaseOrder.status)},
        "requisitions": {"byStatus": _counts(session, Requisition.status),
                         "avgApprovalHours": str(Decimal(cycle / 3600).quantize(Decimal("0.1"))) if cycle else None},
        "payables": {"firstPassMatchPct": _pct(matched[1] or 0, matched[0]), "byStatus": _counts(session, Invoice.status),
                     "openExceptions": session.execute(select(func.count()).select_from(InvoiceException).where(InvoiceException.status == "OPEN")).scalar(),
                     "paymentBlocked": session.execute(select(func.count()).select_from(Invoice).where(Invoice.payment_block.is_(True))).scalar()},
        "savings": {"negotiatedCr": str(crore(ledger.get("NEGOTIATED", 0))), "avoidanceCr": str(crore(ledger.get("AVOIDANCE", 0))),
                    "realisedCr": str(crore(ledger.get("REALISED", 0))), "realisedMinor": ledger.get("REALISED", 0)},
        "suppliers": {"total": session.execute(select(func.count()).select_from(Supplier)).scalar(), "categoryStatus": categories,
                      "qualifiedCoveragePct": _pct(categories.get("QUALIFIED", 0) + categories.get("PREFERRED", 0), sum(categories.values()))},
        "integration": {"byStatus": integration, "postingSuccessPct": _pct(posted, attempted)},
        "controls": {"sodViolations": session.execute(select(func.count()).select_from(SodViolation)).scalar(),
                     "agentRuns": session.execute(select(func.count()).select_from(AgentRun)).scalar()},
        "tasks": {"open": open_tasks, "overdue": overdue, "mine": mine},
        "activity": activity,
    }
