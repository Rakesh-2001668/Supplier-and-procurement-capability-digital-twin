"""Partial payments of an invoice (M10, F7-07): an invoice is paid in parts across payment runs.

Rules of the game (rule set PARTIAL-PAYMENT, effective-dated, scope company code):
* ``invoice.paid_minor`` is the cash paid by the live (not cancelled) payments of the invoice; the open amount is what the invoice is worth to
  the supplier in cash (gross - credit notes + debit notes netted - retention - early-payment discount - advance recovery - TDS withheld + TCS
  paid with it) less ``paid_minor``. ``payment_status`` is PARTIALLY_PAID while something is open, IN_PAYMENT / PAID once the last part is paid.
* A partial amount needs a reason (rule ``reasonMinLength``), is at least ``minAmountMinor`` and below the open amount (paying the open amount is
  the final payment); an invoice takes at most ``maxInstallments`` payments, returned ones included.
* TDS (resident sections and section 195) is deducted ONCE, in full, with the first payment of the invoice; the later parts withhold nothing. When
  the payment that carried the TDS is returned by the bank, the next payment deducts it again.
* Debit notes are netted into the first payment only; a note posted after the first part is paid on its own (as for a paid invoice).
* An accepted early-payment discount or an SCF election is earned only by paying the whole invoice: a partial amount is refused for it, and no
  early-payment offer can be made on a partially paid invoice (early_payment requires an unpaid one).
* Every payment, partial or not, is its own payment record, PAYMENT ERP message and bank-file line, under the same SoD and bank checks.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.models import Invoice, Payment
from app.pic.platform import clock, finance_defaults, rules
from app.pic.platform.errors import Problem

KEY = "PARTIAL-PAYMENT"
DEFAULT = finance_defaults.PARTIAL_PAYMENT_DEFAULT
OPEN_STATUSES = ("UNPAID", "PARTIALLY_PAID")


def rule(session: Session, company_code: Optional[str], on: Optional[date] = None) -> tuple[dict, str]:
    try:
        found = rules.resolve(session, KEY, on=on or clock.today(), company_code=company_code)
        return {**DEFAULT, **found.body}, found.ref
    except Problem:
        return DEFAULT, f"{KEY}@default"


def live_payments(session: Session, invoice: Invoice) -> list[Payment]:
    """The invoice's own live payments (debit notes paid on their own excluded), in installment order."""
    return session.execute(select(Payment).where(Payment.invoice_id == invoice.id, Payment.status != "CANCELLED", Payment.debit_note_id.is_(None))
                           .order_by(Payment.installment_no, Payment.created_at)).scalars().all()


def next_installment(session: Session, invoice: Invoice) -> int:
    """Sequence number of the next payment of the invoice (returned payments keep theirs, so numbers are never reused)."""
    return int(session.execute(select(func.coalesce(func.max(Payment.installment_no), 0)).where(
        Payment.invoice_id == invoice.id, Payment.debit_note_id.is_(None))).scalar() or 0) + 1


def check_partial(session: Session, invoice: Invoice, *, amount_minor: int, open_minor: int, reason: Optional[str], installment: int,
                  on: date) -> Optional[str]:
    """None when a partial payment of ``amount_minor`` is allowed, else the reason it is not (the caller raises or skips)."""
    body, ref = rule(session, invoice.company_code, on)
    if not body.get("enabled", True):
        return f"partial payments are switched off ({ref})"
    if invoice.payment_option != "STANDARD" or invoice.discount_minor:
        return (f"{invoice.number} carries an accepted {invoice.payment_option.replace('_', ' ').lower()} option: the discount or financing is earned "
                "only by paying the whole invoice")
    if amount_minor <= 0:
        return "the partial amount must be positive"
    if amount_minor > open_minor:
        return f"the partial amount {amount_minor / 100:,.2f} is more than the open amount {open_minor / 100:,.2f}"
    if amount_minor < int(body.get("minAmountMinor") or 0):
        return f"a partial payment is at least {int(body['minAmountMinor']) / 100:,.2f} ({ref})"
    if installment > int(body.get("maxInstallments") or 12):
        return f"{invoice.number} already has {installment - 1} payments: at most {body.get('maxInstallments')} are allowed ({ref})"
    if len((reason or "").strip()) < int(body.get("reasonMinLength") or 1):
        return f"give the reason for paying part of the invoice (at least {body.get('reasonMinLength')} characters)"
    return None


def position(session: Session, invoice: Invoice) -> dict:
    """Paid / open view of the invoice for screens: the open amount is what the next payment run would pay (``payables.open_amount``)."""
    from app.pic.services import payables
    payments = session.execute(select(Payment).where(Payment.invoice_id == invoice.id, Payment.debit_note_id.is_(None))
                               .order_by(Payment.installment_no, Payment.created_at)).scalars().all()
    open_minor = payables.open_amount(session, invoice) if invoice.status == "POSTED" and invoice.payment_status in OPEN_STATUSES else 0
    body, _ = rule(session, invoice.company_code)
    return {"paidMinor": int(invoice.paid_minor or 0), "openMinor": open_minor, "currency": invoice.currency or "INR",
            "paymentStatus": invoice.payment_status,
            "partialAllowed": bool(body.get("enabled", True)) and invoice.payment_option == "STANDARD" and not invoice.discount_minor,
            "minPartialMinor": int(body.get("minAmountMinor") or 0),
            "installments": [{"payment": p.number, "installment": p.installment_no, "amountMinor": p.amount_minor, "status": p.status,
                              "bankStatus": p.bank_status, "settlesInvoice": p.settles_invoice, "reason": p.partial_reason, "valueDate": p.value_date.isoformat(),
                              "tdsMinor": p.tds_minor, "taxBorneMinor": p.tax_borne_minor, "run": p.run_ref} for p in payments]}
