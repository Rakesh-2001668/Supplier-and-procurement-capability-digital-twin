"""Construction template controls (BP §23): advance payment and its recovery from running bills (pending workflow 38) and
bank guarantee tracking (39).

Rules carried by the construction template: ``ADVANCE-PAYMENT`` (maximum advance as a share of the order value, guarantee
required, approver), ``PERFORMANCE-GUARANTEE`` (minimum guarantee as a share of the order value, which payments it must be valid
for, expiry alerts, release condition) and the existing ``PROJECT-CONTROLS.advanceRecovery`` switch.

An advance is requested against a purchase order (subcontract), approved by finance (never the requester, and only against a
valid advance bank guarantee when the rule says so), and booked as an AP document (match type ADVANCE) that is posted to the ERP as
a down-payment request and paid by the normal payment run. Every running bill on the order then carries a recovery of the same
share of its value, withheld from the payment and cleared against the advance in the ERP; the final bill recovers what is left.
Hooks in payables.py call ``plan_recovery`` (capture), ``post_payload`` / ``apply_recovery`` (posting), ``payment_deduction_minor``,
``payment_blocker`` and ``payment_payload`` (payment run) and ``require_valid_guarantee`` (retention release)."""
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    AdvancePayment, AdvanceRecovery, BankGuarantee, Invoice, InvoiceLine, PoLine, PurchaseOrder, Supplier, Task, Timer,
)
from app.pic.platform import audit, clock, outbox, workflow
from app.pic.platform.core import link
from app.pic.platform.errors import Problem, illegal_transition, rule_violation
from app.pic.platform.money import D, fmt_inr, pct_of, tax_amount
from app.pic.platform.serialize import jsonable, row
from app.pic.services import ind_common
from app.pic.services.common import principal

ADVANCE = "ADVANCE"          # channel and match type of the AP document that pays an advance
GUARANTEE_ALERT = "GUARANTEE_ALERT"
GUARANTEE_EXPIRY = "GUARANTEE_EXPIRY"
OPEN_PO = ("RELEASED", "TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED", "RECEIVED")


def po_net_total(session: Session, po: PurchaseOrder) -> int:
    return int(session.execute(select(func.coalesce(func.sum(PoLine.net_minor), 0)).where(PoLine.po_id == po.id)).scalar_one())


# ---------------------------------------------------------------- 39 bank guarantees
def guarantee_rule(session: Session, company_code: Optional[str] = None):
    return ind_common.require_rule(session, "PERFORMANCE-GUARANTEE", "Bank guarantee tracking", company_code=company_code)


def record_guarantee(session: Session, po: PurchaseOrder, *, kind: str, bank_name: str, bank_ref: str, amount_minor: int, issue_date: date,
                     expiry_date: date) -> BankGuarantee:
    """A bank guarantee received for an order. It is PENDING_VERIFICATION until a second person confirms it with the issuing bank."""
    p = principal(session)
    rule = guarantee_rule(session, po.company_code)
    kind = (kind or "").upper()
    if kind not in ("PERFORMANCE", "ADVANCE"):
        raise Problem(422, "INVALID_KIND", "kind must be PERFORMANCE or ADVANCE")
    if expiry_date <= issue_date:
        raise rule_violation("The guarantee must expire after its issue date", rule.ref)
    if expiry_date <= clock.today():
        raise rule_violation("The guarantee has already expired", rule.ref)
    if amount_minor <= 0:
        raise Problem(422, "INVALID_AMOUNT", "The guarantee amount must be positive")
    if kind == "PERFORMANCE":
        minimum = pct_of(po_net_total(session, po), rule.body.get("minPct", "0"))
        if amount_minor < minimum:
            raise rule_violation(f"A performance guarantee covers at least {rule.body.get('minPct')}% of the order value "
                                 f"({fmt_inr(minimum)}); {fmt_inr(amount_minor)} offered", rule.ref, minimumMinor=minimum)
    if session.execute(select(BankGuarantee.id).where(BankGuarantee.bank_name == bank_name, BankGuarantee.bank_ref == bank_ref)).first():
        raise Problem(409, "DUPLICATE_GUARANTEE", f"Guarantee {bank_ref} of {bank_name} is already recorded", rule_ref=rule.ref)
    guarantee = BankGuarantee(tenant_id=current_tenant(session), number=ind_common.number(session, "BANK_GUARANTEE", "BG-", 1001, 0), kind=kind,
                              po_id=po.id, supplier_id=po.supplier_id, bank_name=bank_name, bank_ref=bank_ref, amount_minor=amount_minor,
                              issue_date=issue_date, expiry_date=expiry_date, status="PENDING_VERIFICATION", recorded_by=p.user_id,
                              alerts_sent=[], created_by=p.user_id)
    session.add(guarantee)
    session.flush()
    link(session, "PURCHASE_ORDER", po.id, po.number, "BANK_GUARANTEE", guarantee.id, guarantee.number, "secured_by")
    audit.record(session, "BANK_GUARANTEE", guarantee.id, "RECORDED", object_ref=guarantee.number, rule_set_version=rule.ref,
                 after={"po": po.number, "kind": kind, "bank": bank_name, "bankRef": bank_ref, "amountMinor": amount_minor,
                        "expiry": expiry_date.isoformat()})
    return guarantee


def verify_guarantee(session: Session, guarantee: BankGuarantee, note: Optional[str] = None) -> BankGuarantee:
    """Confirmation with the issuing bank by someone other than the person who recorded it; starts the expiry alerts."""
    p = principal(session)
    if "FINANCE_CONTROLLER" not in p.roles:
        raise Problem(403, "FORBIDDEN", "A bank guarantee is verified by finance")
    if guarantee.status != "PENDING_VERIFICATION":
        raise illegal_transition("Bank guarantee", guarantee.number, guarantee.status, "verify")
    if guarantee.recorded_by == p.user_id:
        raise Problem(403, "SOD_CONFLICT", "Segregation of duties: the person who recorded the guarantee cannot verify it", rule_ref="SOD-GUARANTEE")
    if guarantee.expiry_date <= clock.today():
        raise rule_violation(f"{guarantee.number} expired on {guarantee.expiry_date.isoformat()}", "PERFORMANCE-GUARANTEE")
    guarantee.status, guarantee.verified_by, guarantee.verified_at = "ACTIVE", p.user_id, clock.now()
    rule = guarantee_rule(session)
    for days in sorted({int(d) for d in rule.body.get("alertDays") or []}, reverse=True):
        due = clock.at_ist(guarantee.expiry_date - timedelta(days=days), 9)
        workflow.create_timer(session, GUARANTEE_ALERT, "BANK_GUARANTEE", guarantee.id, due, {"daysBefore": days})
    workflow.create_timer(session, GUARANTEE_EXPIRY, "BANK_GUARANTEE", guarantee.id, clock.at_ist(guarantee.expiry_date + timedelta(days=1), 0, 5))
    audit.record(session, "BANK_GUARANTEE", guarantee.id, "VERIFIED", object_ref=guarantee.number, before={"status": "PENDING_VERIFICATION"},
                 after={"status": "ACTIVE", "alertDays": rule.body.get("alertDays")}, reason=note, rule_set_version=rule.ref)
    outbox.emit(session, "guarantee.verified", "BANK_GUARANTEE", guarantee.id, guarantee.number,
                {"po": session.get(PurchaseOrder, guarantee.po_id).number, "kind": guarantee.kind, "expiry": guarantee.expiry_date.isoformat()})
    return guarantee


def release_guarantee(session: Session, guarantee: BankGuarantee, reason: str) -> BankGuarantee:
    """Release (return to the bank) once its purpose is served: an advance guarantee when the advance is fully recovered, a performance
    guarantee when the order's retention is released in full (rule PERFORMANCE-GUARANTEE.releaseAfter)."""
    from app.pic.services import payables

    p = principal(session)
    if not set(p.roles) & {"FINANCE_CONTROLLER", "CONTRACT_MANAGER"}:
        raise Problem(403, "FORBIDDEN", "A guarantee is released by finance or the contract manager")
    if not (reason or "").strip():
        raise Problem(422, "REASON_REQUIRED", "Give the release reason")
    if guarantee.status != "ACTIVE":
        raise illegal_transition("Bank guarantee", guarantee.number, guarantee.status, "release")
    po = session.get(PurchaseOrder, guarantee.po_id)
    if guarantee.kind == "ADVANCE":
        open_advances = session.execute(select(AdvancePayment.number).where(
            AdvancePayment.guarantee_id == guarantee.id, AdvancePayment.status.in_(("REQUESTED", "APPROVED", "PAID")))).scalars().all()
        if open_advances:
            raise rule_violation(f"Advance {', '.join(open_advances)} is not fully recovered yet", "PERFORMANCE-GUARANTEE")
    elif po.retention_pct:
        outstanding = payables.retention_position(session, po)["outstandingMinor"]
        if outstanding > 0:
            raise rule_violation(f"{fmt_inr(outstanding)} retention on {po.number} is still outstanding: release it before the guarantee",
                                 "PERFORMANCE-GUARANTEE")
    guarantee.status, guarantee.released_by, guarantee.released_at, guarantee.release_reason = "RELEASED", p.user_id, clock.now(), reason
    for timer in session.execute(select(Timer).where(Timer.object_id == guarantee.id, Timer.kind.in_((GUARANTEE_ALERT, GUARANTEE_EXPIRY)),
                                                     Timer.fired_at.is_(None))).scalars():
        timer.fired_at, timer.payload = clock.now(), {**(timer.payload or {}), "cancelled": True}
    audit.record(session, "BANK_GUARANTEE", guarantee.id, "RELEASED", object_ref=guarantee.number, before={"status": "ACTIVE"},
                 after={"status": "RELEASED"}, reason=reason, rule_set_version="PERFORMANCE-GUARANTEE")
    return guarantee


def valid_guarantee(session: Session, po: PurchaseOrder, kind: str, on: Optional[date] = None, minimum_minor: int = 0) -> Optional[BankGuarantee]:
    on = on or clock.today()
    return session.execute(select(BankGuarantee).where(
        BankGuarantee.po_id == po.id, BankGuarantee.kind == kind, BankGuarantee.status == "ACTIVE", BankGuarantee.expiry_date >= on,
        BankGuarantee.amount_minor >= minimum_minor).order_by(BankGuarantee.expiry_date.desc())).scalars().first()


def guarantee_problem(session: Session, po: PurchaseOrder, purpose: str, on: Optional[date] = None) -> Optional[str]:
    """Why the order's payment ``purpose`` (RETENTION_RELEASE | FINAL_PAYMENT) is blocked for want of a valid performance guarantee,
    or None (rule absent, purpose not covered, order without retention, or a valid guarantee on file)."""
    rule = ind_common.rule_or_none(session, "PERFORMANCE-GUARANTEE", company_code=po.company_code)
    if rule is None or rule.body.get("enabled") is False or purpose not in (rule.body.get("requiredFor") or []) or not po.retention_pct:
        return None
    minimum = pct_of(po_net_total(session, po), rule.body.get("minPct", "0"))
    if valid_guarantee(session, po, "PERFORMANCE", on, minimum) is not None:
        return None
    latest = session.execute(select(BankGuarantee).where(BankGuarantee.po_id == po.id, BankGuarantee.kind == "PERFORMANCE")
                             .order_by(BankGuarantee.created_at.desc())).scalars().first()
    if latest is None:
        return f"no performance bank guarantee is on file for {po.number} (rule {rule.ref})"
    return f"performance guarantee {latest.number} is {latest.status.lower().replace('_', ' ')}" + (
        f" (expired {latest.expiry_date.isoformat()})" if latest.expiry_date < (on or clock.today()) else "") + f"; rule {rule.ref}"


def require_valid_guarantee(session: Session, po: PurchaseOrder, purpose: str) -> None:
    problem = guarantee_problem(session, po, purpose)
    if problem:
        raise Problem(409, "GUARANTEE_REQUIRED", f"{purpose.replace('_', ' ').capitalize()} is blocked: {problem}", rule_ref="PERFORMANCE-GUARANTEE")


@workflow.on_timer(GUARANTEE_ALERT)
def _alert(session: Session, timer: Timer) -> None:
    guarantee = session.get(BankGuarantee, timer.object_id)
    if guarantee is None or guarantee.status != "ACTIVE":
        return
    po = session.get(PurchaseOrder, guarantee.po_id)
    days_left = (guarantee.expiry_date - clock.today()).days
    guarantee.alerts_sent = list(guarantee.alerts_sent or []) + [{"at": clock.now().isoformat(), "daysBefore": (timer.payload or {}).get("daysBefore"),
                                                                    "daysLeft": days_left}]
    ind_common.open_task(session, "GUARANTEE_EXPIRY", "CONTRACT_MANAGER", object_type="BANK_GUARANTEE", object_id=guarantee.id,
                         object_ref=guarantee.number, evidence={"po": po.number, "kind": guarantee.kind, "expiry": guarantee.expiry_date.isoformat(),
                                                                "daysLeft": days_left, "bank": guarantee.bank_name, "bankRef": guarantee.bank_ref,
                                                                "action": "Ask the contractor to extend or replace the guarantee before it expires"})
    audit.record(session, "BANK_GUARANTEE", guarantee.id, "EXPIRY_ALERT", object_ref=guarantee.number,
                 after={"daysLeft": days_left, "expiry": guarantee.expiry_date.isoformat()}, rule_set_version="PERFORMANCE-GUARANTEE")
    outbox.emit(session, "guarantee.expiring", "BANK_GUARANTEE", guarantee.id, guarantee.number,
                {"po": po.number, "daysLeft": days_left, "expiry": guarantee.expiry_date.isoformat()})


@workflow.on_timer(GUARANTEE_EXPIRY)
def _expired(session: Session, timer: Timer) -> None:
    guarantee = session.get(BankGuarantee, timer.object_id)
    if guarantee is None or guarantee.status != "ACTIVE":
        return
    guarantee.status = "EXPIRED"
    audit.record(session, "BANK_GUARANTEE", guarantee.id, "EXPIRED", object_ref=guarantee.number, before={"status": "ACTIVE"}, after={"status": "EXPIRED"},
                 rule_set_version="PERFORMANCE-GUARANTEE")
    outbox.emit(session, "guarantee.expired", "BANK_GUARANTEE", guarantee.id, guarantee.number,
                {"po": session.get(PurchaseOrder, guarantee.po_id).number, "expiry": guarantee.expiry_date.isoformat()})


# ---------------------------------------------------------------- 38 advance payment
def request_advance(session: Session, po: PurchaseOrder, *, net_minor: int, reference: str, reason: Optional[str] = None) -> AdvancePayment:
    p = principal(session)
    rule = ind_common.require_rule(session, "ADVANCE-PAYMENT", "Advance payment", company_code=po.company_code)
    project = ind_common.rule_or_none(session, "PROJECT-CONTROLS", company_code=po.company_code)
    if project is not None and project.body.get("advanceRecovery") is False:
        raise Problem(409, "CONTROL_NOT_ENABLED", "Advance recovery is switched off (PROJECT-CONTROLS.advanceRecovery)", rule_ref="PROJECT-CONTROLS")
    if po.status not in OPEN_PO:
        raise illegal_transition("Purchase order", po.number, po.status, "advance")
    if net_minor <= 0:
        raise Problem(422, "INVALID_AMOUNT", "The advance must be positive")
    if not (reference or "").strip():
        raise Problem(422, "REFERENCE_REQUIRED", "Give the contractor's advance invoice / proforma number")
    order_value = po_net_total(session, po)
    existing = session.execute(select(AdvancePayment).where(AdvancePayment.po_id == po.id, AdvancePayment.status.notin_(("REJECTED", "CANCELLED")))).scalars().all()
    if any(a.reference == reference for a in existing):
        raise Problem(409, "DUPLICATE_ADVANCE", f"Advance reference {reference} is already requested for {po.number}", rule_ref=rule.ref)
    ceiling = pct_of(order_value, rule.body.get("maxPct", "100"))
    total = sum(a.net_minor for a in existing) + net_minor
    if total > ceiling:
        raise rule_violation(f"Advances on {po.number} would total {fmt_inr(total)}; the limit is {rule.body.get('maxPct')}% of the order value "
                             f"({fmt_inr(ceiling)})", rule.ref, ceilingMinor=ceiling)
    first_line = session.execute(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no)).scalars().first()
    tax = tax_amount(net_minor, first_line.gst_rate if first_line else 0)
    advance = AdvancePayment(tenant_id=current_tenant(session), number=ind_common.number(session, "ADVANCE_PAYMENT", "ADV-", 1001, 0), po_id=po.id,
                             supplier_id=po.supplier_id, net_minor=net_minor, tax_minor=tax, gross_minor=net_minor + tax,
                             recovery_pct=(Decimal(net_minor) * 100 / Decimal(order_value)).quantize(Decimal("0.000001")), recovered_minor=0,
                             status="REQUESTED", reference=reference, reason=reason, requested_by=p.user_id, rule_set_version=rule.ref,
                             created_by=p.user_id)
    session.add(advance)
    session.flush()
    link(session, "PURCHASE_ORDER", po.id, po.number, "ADVANCE_PAYMENT", advance.id, advance.number, "advanced_by")
    audit.record(session, "ADVANCE_PAYMENT", advance.id, "REQUESTED", object_ref=advance.number, rule_set_version=rule.ref, reason=reason,
                 after={"po": po.number, "netMinor": net_minor, "grossMinor": advance.gross_minor, "recoveryPct": str(advance.recovery_pct),
                        "reference": reference})
    workflow.start_approval(session, None, "ADVANCE_APPROVAL", object_type="ADVANCE_PAYMENT", object_id=advance.id, object_ref=advance.number,
                            chain=[rule.body.get("approverRole", "FINANCE_CONTROLLER")], step_id=None, initiator_id=p.user_id, sla_business_days=2,
                            rule_set_version=rule.ref, evidence={"po": po.number, "supplier": session.get(Supplier, po.supplier_id).code,
                                                                   "grossMinor": advance.gross_minor, "recoveryPct": str(advance.recovery_pct),
                                                                   "needsGuarantee": bool(rule.body.get("needsGuarantee"))})
    return advance


def _advance_guarantee(session: Session, advance: AdvancePayment, po: PurchaseOrder) -> Optional[BankGuarantee]:
    return valid_guarantee(session, po, "ADVANCE", None, advance.gross_minor)


@workflow.guard_task("ADVANCE_APPROVAL")
def _advance_guard(session: Session, task: Task, decision: str) -> None:
    if decision != "APPROVE":
        return
    advance = session.get(AdvancePayment, task.object_id)
    po = session.get(PurchaseOrder, advance.po_id)
    rule = ind_common.rule_or_none(session, "ADVANCE-PAYMENT", company_code=po.company_code)
    if principal(session).user_id == advance.requested_by:
        raise Problem(403, "SOD_CONFLICT", "Segregation of duties: the requester cannot approve the advance", rule_ref="SOD-ADVANCE")
    if rule is not None and rule.body.get("needsGuarantee") and _advance_guarantee(session, advance, po) is None:
        raise Problem(409, "GUARANTEE_REQUIRED", f"An active advance bank guarantee of at least {fmt_inr(advance.gross_minor)} valid today must be "
                      f"on file for {po.number} before the advance is approved", rule_ref="ADVANCE-PAYMENT")


@workflow.on_task("ADVANCE_APPROVAL")
def _advance_decided(session: Session, task: Task, outcome: str) -> None:
    advance = session.get(AdvancePayment, task.object_id)
    po = session.get(PurchaseOrder, advance.po_id)
    if outcome != "APPROVED":
        advance.status = "REJECTED"
        audit.record(session, "ADVANCE_PAYMENT", advance.id, "REJECTED", object_ref=advance.number, reason=task.comment)
        return
    from app.pic.services import payables

    supplier = session.get(Supplier, po.supplier_id)
    guarantee = _advance_guarantee(session, advance, po)
    today = clock.today()
    number = f"ADV-{po.number}-{advance.number[-4:]}"[:30]
    invoice = Invoice(tenant_id=advance.tenant_id, number=number, supplier_invoice_no=advance.reference[:40], fiscal_year=clock.fiscal_year(today),
                      company_code=po.company_code, supplier_id=po.supplier_id, po_id=po.id, invoice_date=today, channel=ADVANCE,
                      currency=po.currency or "INR", net_minor=advance.net_minor, tax_minor=advance.tax_minor, gross_minor=advance.gross_minor,
                      retention_minor=0, status="MATCHED", match_type=ADVANCE, first_pass_matched=True, payment_block=False,
                      rule_set_version=advance.rule_set_version, created_by=advance.requested_by)
    session.add(invoice)
    session.flush()
    advance.status, advance.approved_by, advance.invoice_id = "APPROVED", task.completed_by, invoice.id
    advance.guarantee_id = guarantee.id if guarantee else None
    instance = workflow.start(session, payables.PROCESS, "INVOICE", invoice.id, invoice.number, {"advance": advance.number})
    workflow.step(session, instance, "F7-01", outcome=f"advance {advance.number} on {po.number}: {fmt_inr(advance.gross_minor)} (reference {advance.reference})")
    workflow.step(session, instance, "F7-02", outcome="no duplicate: advance document")
    workflow.step(session, instance, "F7-03", outcome=f"ADVANCE: approved by finance ({advance.number})")
    workflow.step(session, instance, "F7-04", outcome="yes: advance approved")
    link(session, "ADVANCE_PAYMENT", advance.id, advance.number, "INVOICE", invoice.id, invoice.number, "paid_by_document")
    link(session, "PURCHASE_ORDER", po.id, po.number, "INVOICE", invoice.id, invoice.number, "advanced_by")
    audit.record(session, "ADVANCE_PAYMENT", advance.id, "APPROVED", object_ref=advance.number, reason=task.comment, rule_set_version=advance.rule_set_version,
                 after={"document": invoice.number, "guarantee": guarantee.number if guarantee else None, "supplier": supplier.code})
    outbox.emit(session, "advance.approved", "ADVANCE_PAYMENT", advance.id, advance.number,
                {"po": po.number, "grossMinor": advance.gross_minor, "document": invoice.number})


@outbox.consumer("payment.completed", "advance-paid")
def _advance_paid(session: Session, event) -> None:
    invoice = session.get(Invoice, event.object_id)
    if invoice is None or invoice.match_type != ADVANCE:
        return
    advance = session.execute(select(AdvancePayment).where(AdvancePayment.invoice_id == invoice.id)).scalar_one_or_none()
    if advance is not None and advance.status == "APPROVED":
        advance.status = "PAID"
        audit.record(session, "ADVANCE_PAYMENT", advance.id, "PAID", object_ref=advance.number, after={"payment": event.payload.get("payment")})


# ---------------------------------------------------------------- 38 recovery from running bills
def _open_balance(session: Session, advance: AdvancePayment, exclude_invoice_id: Optional[uuid.UUID] = None) -> int:
    """Advance not yet recovered or planned for other unposted bills."""
    query = select(func.coalesce(func.sum(AdvanceRecovery.amount_minor), 0)).join(Invoice, Invoice.id == AdvanceRecovery.invoice_id).where(
        AdvanceRecovery.advance_id == advance.id, AdvanceRecovery.status == "PLANNED", Invoice.status != "REJECTED")
    if exclude_invoice_id is not None:
        query = query.where(AdvanceRecovery.invoice_id != exclude_invoice_id)
    planned = int(session.execute(query).scalar_one())
    return advance.gross_minor - advance.recovered_minor - planned


def plan_recovery(session: Session, invoice: Invoice) -> int:
    """Recovery of paid advances from this running bill, per purchase order: the advance's share of the bill's gross value, capped
    at what is left of the advance; the bill that completes the order recovers everything that is left. Stored as PLANNED rows (the
    payment run withholds them) and applied when the bill is posted. Returns the total planned. Not for advance or retention documents."""
    if invoice.match_type in (ADVANCE, "RETENTION") or invoice.channel in (ADVANCE, "RETENTION"):
        return 0
    lines = session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)).scalars().all()
    by_po: dict = {}
    for line in lines:
        po_line = session.get(PoLine, line.po_line_id) if line.po_line_id else None
        if po_line is not None:
            by_po[po_line.po_id] = by_po.get(po_line.po_id, 0) + line.net_minor + line.tax_minor
    total = 0
    for po_id, bill_gross in by_po.items():
        advances = session.execute(select(AdvancePayment).where(AdvancePayment.po_id == po_id, AdvancePayment.status.in_(("PAID", "APPROVED")))
                                   .order_by(AdvancePayment.created_at).with_for_update()).scalars().all()
        for advance in advances:
            if advance.status != "PAID":
                continue
            balance = _open_balance(session, advance, invoice.id)
            amount = min(pct_of(bill_gross, advance.recovery_pct), max(balance, 0))
            if _completes_order(session, po_id, invoice):
                amount = max(balance, 0)
            existing = session.execute(select(AdvanceRecovery).where(AdvanceRecovery.advance_id == advance.id,
                                                                     AdvanceRecovery.invoice_id == invoice.id)).scalar_one_or_none()
            if amount <= 0:
                if existing is not None and existing.status == "PLANNED":
                    existing.status = "CANCELLED"
                continue
            if existing is None:
                session.add(AdvanceRecovery(tenant_id=invoice.tenant_id, advance_id=advance.id, invoice_id=invoice.id, amount_minor=amount,
                                            status="PLANNED", created_by=principal(session).user_id))
            elif existing.status in ("PLANNED", "CANCELLED"):
                existing.amount_minor, existing.status = amount, "PLANNED"
            total += amount
    session.flush()
    return total


def _completes_order(session: Session, po_id: uuid.UUID, invoice: Invoice) -> bool:
    """This bill brings the invoiced value of the order (posted bills plus this one) to the full order value."""
    lines = session.execute(select(PoLine).where(PoLine.po_id == po_id)).scalars().all()
    mine: dict = {}
    for line in session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)).scalars():
        mine[line.po_line_id] = mine.get(line.po_line_id, 0) + line.net_minor
    posted = invoice.status in ("POSTED", "PAID")
    return bool(lines) and all((l.invoiced_minor if posted else l.invoiced_minor + mine.get(l.id, 0)) >= l.net_minor for l in lines if l.ses_required or l.gr_required or l.ir_required)


def recovery_minor(session: Session, invoice: Invoice, statuses=("PLANNED", "APPLIED")) -> int:
    return int(session.execute(select(func.coalesce(func.sum(AdvanceRecovery.amount_minor), 0)).where(
        AdvanceRecovery.invoice_id == invoice.id, AdvanceRecovery.status.in_(list(statuses)))).scalar_one())


def payment_deduction_minor(session: Session, invoice: Invoice) -> int:
    """Advance recovery withheld from the payment of a running bill (0 for tenants without advances)."""
    return recovery_minor(session, invoice)


def post_payload(session: Session, invoice: Invoice) -> dict:
    """Extra ERP fields of the SUPPLIER_INVOICE message: a down-payment request for an advance document, the clearing of the paid
    advances for a running bill."""
    if invoice.match_type == ADVANCE:
        advance = session.execute(select(AdvancePayment).where(AdvancePayment.invoice_id == invoice.id)).scalar_one_or_none()
        return {"downPayment": True, "specialGl": "A", "advance": advance.number if advance else None}
    if invoice.channel == "RETENTION":
        return {}
    plan_recovery(session, invoice)  # recomputed at posting, as retention is
    rows = session.execute(select(AdvanceRecovery, AdvancePayment).join(AdvancePayment, AdvancePayment.id == AdvanceRecovery.advance_id).where(
        AdvanceRecovery.invoice_id == invoice.id, AdvanceRecovery.status == "PLANNED")).all()
    if not rows:
        return {}
    return {"advanceRecoveryMinor": sum(r.amount_minor for r, _ in rows),
            "advances": [{"advance": a.number, "amountMinor": r.amount_minor} for r, a in rows]}


def apply_recovery(session: Session, invoice: Invoice) -> None:
    """The bill is posted: the planned recoveries are applied to the advances (balance tracking) and audited."""
    for recovery in session.execute(select(AdvanceRecovery).where(AdvanceRecovery.invoice_id == invoice.id, AdvanceRecovery.status == "PLANNED")).scalars():
        advance = session.get(AdvancePayment, recovery.advance_id)
        recovery.status = "APPLIED"
        advance.recovered_minor += recovery.amount_minor
        if advance.recovered_minor >= advance.gross_minor:
            advance.status = "RECOVERED"
        audit.record(session, "ADVANCE_PAYMENT", advance.id, "RECOVERED", object_ref=advance.number,
                     after={"invoice": invoice.number, "amountMinor": recovery.amount_minor, "recoveredMinor": advance.recovered_minor,
                            "balanceMinor": advance.gross_minor - advance.recovered_minor, "status": advance.status})
        link(session, "ADVANCE_PAYMENT", advance.id, advance.number, "INVOICE", invoice.id, invoice.number, "recovered_from")


def payment_payload(session: Session, invoice: Invoice) -> dict:
    if invoice.match_type == ADVANCE:
        return {"downPayment": True}
    amount = recovery_minor(session, invoice)
    return {"advanceRecoveryMinor": amount} if amount else {}


def payment_blocker(session: Session, invoice: Invoice) -> Optional[str]:
    """Final payment of an order with retention waits for a valid performance guarantee when the rule says so."""
    if invoice.match_type in (ADVANCE, "RETENTION") or invoice.channel in (ADVANCE, "RETENTION"):
        return None
    po_ids = {session.get(PoLine, l.po_line_id).po_id for l in session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)).scalars()
              if l.po_line_id}
    for po_id in po_ids:
        po = session.get(PurchaseOrder, po_id)
        if not po.retention_pct:
            continue
        lines = session.execute(select(PoLine).where(PoLine.po_id == po_id)).scalars().all()
        if lines and all(l.invoiced_minor >= l.net_minor for l in lines):
            problem = guarantee_problem(session, po, "FINAL_PAYMENT")
            if problem:
                return f"final payment blocked: {problem}"
    return None


# ---------------------------------------------------------------- views
def advance_view(session: Session, advance: AdvancePayment) -> dict:
    po = session.get(PurchaseOrder, advance.po_id)
    invoice = session.get(Invoice, advance.invoice_id) if advance.invoice_id else None
    recoveries = session.execute(select(AdvanceRecovery, Invoice).join(Invoice, Invoice.id == AdvanceRecovery.invoice_id).where(
        AdvanceRecovery.advance_id == advance.id, AdvanceRecovery.status != "CANCELLED").order_by(AdvanceRecovery.created_at)).all()
    guarantee = session.get(BankGuarantee, advance.guarantee_id) if advance.guarantee_id else None
    return row(advance, extra={"po": po.number, "document": invoice.number if invoice else None, "documentStatus": invoice.status if invoice else None,
                               "balanceMinor": advance.gross_minor - advance.recovered_minor,
                               "plannedMinor": sum(r.amount_minor for r, _ in recoveries if r.status == "PLANNED"),
                               "guarantee": guarantee.number if guarantee else None,
                               "recoveries": [{"invoice": i.number, "amountMinor": r.amount_minor, "status": r.status} for r, i in recoveries]})


def guarantee_view(session: Session, guarantee: BankGuarantee) -> dict:
    po = session.get(PurchaseOrder, guarantee.po_id)
    days = (guarantee.expiry_date - clock.today()).days
    return row(guarantee, extra={"po": po.number, "daysToExpiry": days, "version": guarantee.row_version,
                                 "valid": guarantee.status == "ACTIVE" and days >= 0,
                                 "expiringSoon": guarantee.status == "ACTIVE" and 0 <= days <= 60})
