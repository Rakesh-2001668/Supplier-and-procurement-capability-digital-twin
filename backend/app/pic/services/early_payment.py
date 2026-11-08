"""Early-payment discount offers and supply-chain-finance hooks on invoices (BP M10 "early-payment discount and supply-chain finance hooks").

DISCOUNT offers (dynamic discounting): a posted, unpaid invoice can be paid before its due date at a discount.
* source TERMS  - the supplier's payment terms carry a discount (``2/10 N45``): taken by accounts payable inside the discount window, accepted at once;
* source BUYER  - accounts payable / finance offers a pay-on date and discount; the supplier accepts or declines in the portal;
* source SUPPLIER - the supplier asks to be paid early at a discount; accounts payable / finance accepts or declines.
Accepting moves the invoice's due date to the pay-on date and sets ``invoice.discount_minor``; the payment run pays the invoice less
the discount (and ``payables.payment_run`` ends the offer as APPLIED). If the run misses the pay-on date the offer lapses and the
original due date is restored.

SCF (kind SCF): the supplier elects to be financed on the invoice by the customer's supply-chain-finance programme. No external provider
is called: the election sets ``invoice.payment_option = SCF``, raises the ``invoice.scf.elected`` event and enqueues the ERP message
``SCF_FINANCING`` (assignment of the payable to the programme); the invoice is still paid at maturity by the normal payment run, flagged
``scf`` in the PAYMENT message. Rule EARLY-PAYMENT holds the limits."""
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import EarlyPaymentOffer, Invoice, Supplier
from app.pic.platform import audit, clock, integration, outbox
from app.pic.platform.errors import Problem, illegal_transition, not_found, rule_violation
from app.pic.platform.money import D, fmt_inr, pct_of
from app.pic.services import p2p_rules
from app.pic.services.common import principal, require_supplier_user

KEY = "EARLY-PAYMENT"
LIVE = ("OFFERED", "ACCEPTED")
BUYER_ROLES = ("AP_CLERK", "FINANCE_CONTROLLER")  # kept for callers; the check below is by permission
BUYER_SCOPES = frozenset({"invoice:post", "payment:run"})


def _is_supplier(session: Session) -> bool:
    return "SUPPLIER_USER" in principal(session).roles


def _require_buyer_side(session: Session) -> None:
    if not principal(session).scopes & BUYER_SCOPES:
        raise Problem(403, "FORBIDDEN", "Early-payment offers are handled by accounts payable or finance (permission invoice:post or payment:run)")


def offers_of(session: Session, invoice: Invoice) -> list[EarlyPaymentOffer]:
    expire_due(session, invoice)
    return session.execute(select(EarlyPaymentOffer).where(EarlyPaymentOffer.invoice_id == invoice.id)
                           .order_by(EarlyPaymentOffer.created_at)).scalars().all()


def live_offer(session: Session, invoice: Invoice) -> Optional[EarlyPaymentOffer]:
    return session.execute(select(EarlyPaymentOffer).where(EarlyPaymentOffer.invoice_id == invoice.id,
                                                           EarlyPaymentOffer.status.in_(LIVE))).scalars().first()


def expire_due(session: Session, invoice: Invoice) -> None:
    for offer in session.execute(select(EarlyPaymentOffer).where(EarlyPaymentOffer.invoice_id == invoice.id,
                                                                 EarlyPaymentOffer.status == "OFFERED",
                                                                 EarlyPaymentOffer.expires_on < clock.today())).scalars():
        offer.status = "EXPIRED"
        audit.record(session, "INVOICE", invoice.id, "EARLY_PAYMENT_OFFER_EXPIRED", object_ref=invoice.number, after={"offer": str(offer.id)})


def payable_base(session: Session, invoice: Invoice) -> int:
    """What would be paid without a discount: gross less credit notes, plus posted debit notes, less retention."""
    from app.pic.models import CreditNote
    from app.pic.services import debit_notes
    credit = sum(n.gross_minor for n in session.execute(select(CreditNote).where(CreditNote.invoice_id == invoice.id)).scalars())
    debit, _ = debit_notes.payable_adjustment(session, invoice)
    return invoice.gross_minor - credit + debit - (invoice.retention_minor or 0)


def _eligible(session: Session, invoice: Invoice, rule) -> None:
    if not rule.body.get("enabled", True):
        raise rule_violation("Early-payment offers are switched off for this tenant", KEY)
    if invoice.status != "POSTED" or invoice.payment_status != "UNPAID":
        raise rule_violation(f"{invoice.number} is {invoice.status.lower()}/{(invoice.payment_status or '').lower()}: an early-payment offer needs a "
                             "posted, unpaid invoice", KEY)
    if invoice.payment_block:
        raise rule_violation(f"{invoice.number} is payment-blocked", KEY)
    if invoice.match_type in ("RETENTION", "ERS"):
        raise rule_violation(f"{invoice.number} is a {invoice.match_type.lower()} document; early payment applies to supplier invoices", KEY)
    if invoice.due_date is None:
        raise rule_violation(f"{invoice.number} has no due date", KEY)
    if live_offer(session, invoice) is not None:
        raise Problem(409, "OFFER_OPEN", f"{invoice.number} already has an open early-payment offer or election", rule_ref=KEY)


def terms_discount(session: Session, invoice: Invoice) -> Optional[tuple[Decimal, date]]:
    """(discount %, last day) of the supplier's terms discount ('2/10 N45' → 2% until invoice date + 10 days)."""
    from app.pic.services import payables
    terms = payables._discount_terms(session.get(Supplier, invoice.supplier_id).payment_terms)
    return (terms[0], invoice.invoice_date + timedelta(days=terms[1])) if terms else None


def options(session: Session, invoice: Invoice) -> dict:
    rule = p2p_rules.rule(session, KEY, company_code=invoice.company_code)
    terms = terms_discount(session, invoice)
    eligible = True
    why = None
    try:
        _eligible(session, invoice, rule)
    except Problem as exc:
        eligible, why = False, exc.detail
    return {"eligible": eligible, "reason": why, "paymentOption": invoice.payment_option, "discountMinor": invoice.discount_minor,
            "dueDate": invoice.due_date.isoformat() if invoice.due_date else None, "payableMinor": payable_base(session, invoice),
            "termsDiscount": ({"pct": str(terms[0]), "until": terms[1].isoformat(), "available": terms[1] >= clock.today()} if terms else None),
            "maxDiscountPct": rule.body.get("maxDiscountPct"), "scfEnabled": bool((rule.body.get("scf") or {}).get("enabled")),
            "scfMinInvoiceMinor": (rule.body.get("scf") or {}).get("minInvoiceMinor"), "rule": rule.ref}


def _annualised(pct: Decimal, days_early: int, basis: int) -> Optional[Decimal]:
    if days_early <= 0 or pct >= 100:
        return None
    return ((pct / (100 - pct)) * Decimal(basis) / Decimal(days_early)).quantize(Decimal("0.01"))


def make_offer(session: Session, invoice: Invoice, *, discount_pct: Optional[Decimal], pay_on: Optional[date], note: Optional[str] = None,
               source: Optional[str] = None) -> EarlyPaymentOffer:
    """A DISCOUNT offer. Buyer side: BUYER offer (or TERMS when ``source`` says so and the terms carry a discount); supplier: SUPPLIER ask."""
    p = principal(session)
    rule = p2p_rules.rule(session, KEY, company_code=invoice.company_code)
    require_supplier_user(session, invoice.supplier_id)
    supplier_side = _is_supplier(session)
    if not supplier_side:
        _require_buyer_side(session)
    _eligible(session, invoice, rule)
    today = clock.today()
    if (source or "").upper() == "TERMS":
        if supplier_side:
            raise Problem(403, "FORBIDDEN", "The terms discount is taken by accounts payable")
        terms = terms_discount(session, invoice)
        if terms is None:
            raise rule_violation(f"The payment terms of {invoice.number}'s supplier carry no early-payment discount", KEY)
        if terms[1] < today:
            raise rule_violation(f"The terms discount window closed on {terms[1].isoformat()}", KEY)
        discount_pct, pay_on, source = terms[0], today, "TERMS"
    else:
        source = "SUPPLIER" if supplier_side else "BUYER"
    if discount_pct is None or pay_on is None:
        raise Problem(422, "VALIDATION_FAILED", "Give the discount percentage and the pay-on date", rule_ref=KEY)
    discount_pct = D(discount_pct)
    if discount_pct <= 0 or discount_pct > D(rule.body.get("maxDiscountPct", 5)):
        raise rule_violation(f"The discount must be above 0 and at most {rule.body.get('maxDiscountPct', 5)}%", KEY)
    if pay_on < today:
        raise rule_violation(f"The pay-on date {pay_on.isoformat()} is in the past", KEY)
    latest = invoice.due_date - timedelta(days=int(rule.body.get("minDaysEarly", 3)))
    if pay_on > latest:
        raise rule_violation(f"The pay-on date must be at least {rule.body.get('minDaysEarly', 3)} days before the due date "
                             f"({invoice.due_date.isoformat()}); latest {latest.isoformat()}", KEY)
    base = payable_base(session, invoice)
    discount = pct_of(base, discount_pct)
    if discount <= 0:
        raise rule_violation("The discount amounts to nothing", KEY)
    expires = min(today + timedelta(days=int(rule.body.get("offerValidDays", 7))), pay_on)
    offer = EarlyPaymentOffer(
        tenant_id=invoice.tenant_id, invoice_id=invoice.id, supplier_id=invoice.supplier_id, kind="DISCOUNT", source=source,
        status="OFFERED", discount_pct=discount_pct, discount_minor=discount, pay_on=pay_on, original_due=invoice.due_date, expires_on=expires,
        annualised_pct=_annualised(discount_pct, (invoice.due_date - pay_on).days, int(rule.body.get("annualisedBasisDays", 365))),
        offered_by=p.user_id, note=(note or "").strip() or None, created_by=p.user_id)
    session.add(offer)
    session.flush()
    audit.record(session, "INVOICE", invoice.id, "EARLY_PAYMENT_OFFERED", object_ref=invoice.number, reason=offer.note, rule_set_version=rule.ref,
                 after={"offer": str(offer.id), "source": source, "discountPct": str(discount_pct), "discountMinor": discount,
                        "payOn": pay_on.isoformat(), "dueDate": invoice.due_date.isoformat(), "annualisedPct": str(offer.annualised_pct)})
    outbox.emit(session, "invoice.early_payment.offered", "INVOICE", invoice.id, invoice.number,
                {"offer": str(offer.id), "source": source, "discountMinor": discount, "payOn": pay_on.isoformat()})
    if source == "TERMS":
        _accept(session, invoice, offer, "terms discount taken by accounts payable")
    return offer


def _accept(session: Session, invoice: Invoice, offer: EarlyPaymentOffer, why: Optional[str]) -> None:
    offer.status = "ACCEPTED"
    offer.decided_by = principal(session).user_id
    invoice.payment_option = "EARLY_DISCOUNT"
    invoice.discount_minor = offer.discount_minor
    invoice.due_date = offer.pay_on
    audit.record(session, "INVOICE", invoice.id, "EARLY_PAYMENT_ACCEPTED", object_ref=invoice.number, reason=why,
                 after={"offer": str(offer.id), "discountMinor": offer.discount_minor, "payOn": offer.pay_on.isoformat(),
                        "originalDue": offer.original_due.isoformat() if offer.original_due else None})
    outbox.emit(session, "invoice.early_payment.accepted", "INVOICE", invoice.id, invoice.number,
                {"offer": str(offer.id), "discountMinor": offer.discount_minor, "payOn": offer.pay_on.isoformat()})


def _get(session: Session, invoice: Invoice, offer_id) -> EarlyPaymentOffer:
    offer = session.get(EarlyPaymentOffer, offer_id)
    if offer is None or offer.invoice_id != invoice.id:
        raise not_found("Early-payment offer", offer_id)
    expire_due(session, invoice)
    return offer


def decide(session: Session, invoice: Invoice, offer_id, accept: bool, note: Optional[str] = None) -> EarlyPaymentOffer:
    """The counterparty decides: the supplier on a BUYER offer, accounts payable / finance on a SUPPLIER ask."""
    offer = _get(session, invoice, offer_id)
    require_supplier_user(session, invoice.supplier_id)
    if offer.kind != "DISCOUNT" or offer.status != "OFFERED":
        raise illegal_transition("Early-payment offer", str(offer.id), offer.status, "accept" if accept else "decline")
    supplier_side = _is_supplier(session)
    if offer.source == "BUYER" and not supplier_side:
        raise Problem(403, "FORBIDDEN", "A buyer offer is accepted or declined by the supplier", rule_ref=KEY)
    if offer.source == "SUPPLIER" and supplier_side:
        raise Problem(403, "FORBIDDEN", "Your request is decided by accounts payable or finance", rule_ref=KEY)
    if not supplier_side:
        _require_buyer_side(session)
    if accept:
        if invoice.status != "POSTED" or invoice.payment_status != "UNPAID":
            raise rule_violation(f"{invoice.number} is no longer open for early payment", KEY)
        if offer.pay_on < clock.today():
            offer.status = "EXPIRED"
            raise rule_violation("The pay-on date has passed", KEY)
        _accept(session, invoice, offer, note)
    else:
        offer.status, offer.decided_by = "DECLINED", principal(session).user_id
        audit.record(session, "INVOICE", invoice.id, "EARLY_PAYMENT_DECLINED", object_ref=invoice.number, reason=note,
                     after={"offer": str(offer.id)})
    return offer


def cancel(session: Session, invoice: Invoice, offer_id, note: Optional[str] = None) -> EarlyPaymentOffer:
    """The party that made an open offer withdraws it."""
    offer = _get(session, invoice, offer_id)
    p = principal(session)
    if offer.status != "OFFERED":
        raise illegal_transition("Early-payment offer", str(offer.id), offer.status, "cancel")
    if offer.offered_by != p.user_id:
        raise Problem(403, "FORBIDDEN", "Only the party that made the offer can withdraw it", rule_ref=KEY)
    offer.status = "CANCELLED"
    audit.record(session, "INVOICE", invoice.id, "EARLY_PAYMENT_CANCELLED", object_ref=invoice.number, reason=note, after={"offer": str(offer.id)})
    return offer


def elect_scf(session: Session, invoice: Invoice, note: Optional[str] = None) -> EarlyPaymentOffer:
    """The supplier (or accounts payable on its behalf) elects supply-chain finance on the invoice: SCF flag, event and ERP message."""
    p = principal(session)
    rule = p2p_rules.rule(session, KEY, company_code=invoice.company_code)
    scf = rule.body.get("scf") or {}
    require_supplier_user(session, invoice.supplier_id)
    if not _is_supplier(session):
        _require_buyer_side(session)
    if not scf.get("enabled"):
        raise rule_violation("Supply-chain finance is not enabled for this tenant", KEY)
    _eligible(session, invoice, rule)
    if invoice.gross_minor < int(scf.get("minInvoiceMinor", 0)):
        raise rule_violation(f"Supply-chain finance needs an invoice of at least {fmt_inr(int(scf.get('minInvoiceMinor', 0)))}", KEY)
    target = integration.target_system(session, invoice.company_code)
    from app.pic.platform import connectors
    connectors.require_mapped(target, "SCF_FINANCING")
    supplier = session.get(Supplier, invoice.supplier_id)
    offer = EarlyPaymentOffer(
        tenant_id=invoice.tenant_id, invoice_id=invoice.id, supplier_id=invoice.supplier_id, kind="SCF",
        source="SUPPLIER" if _is_supplier(session) else "BUYER", status="ACCEPTED", discount_pct=0, discount_minor=0, pay_on=invoice.due_date,
        original_due=invoice.due_date, expires_on=invoice.due_date, offered_by=p.user_id, decided_by=p.user_id,
        note=(note or "").strip() or None, created_by=p.user_id)
    session.add(offer)
    session.flush()
    invoice.payment_option = "SCF"
    message = integration.enqueue(
        session, target_system=target, message_type="SCF_FINANCING", idempotency_key=f"SCF|{invoice.posting_key}", object_type="INVOICE",
        object_id=invoice.id, object_ref=invoice.number,
        payload={"invoice": invoice.supplier_invoice_no, "invoiceErp": invoice.erp_doc_no, "supplier": supplier.code,
                 "companyCode": invoice.company_code, "grossMinor": invoice.gross_minor, "maturity": invoice.due_date.isoformat(),
                 "financier": scf.get("financier", "PROGRAMME"), "offer": str(offer.id)})
    integration.process(session, message)
    offer.erp_doc_no = message.erp_doc_no
    audit.record(session, "INVOICE", invoice.id, "SCF_ELECTED", object_ref=invoice.number, reason=offer.note, rule_set_version=rule.ref,
                 after={"offer": str(offer.id), "maturity": invoice.due_date.isoformat(), "grossMinor": invoice.gross_minor,
                        "erpDocument": message.erp_doc_no, "integrationStatus": message.status})
    outbox.emit(session, "invoice.scf.elected", "INVOICE", invoice.id, invoice.number,
                {"offer": str(offer.id), "maturity": invoice.due_date.isoformat(), "grossMinor": invoice.gross_minor})
    return offer


# ---------------------------------------------------------------- payment run hooks
def lapse_missed(session: Session, run_date: date) -> list[str]:
    """Accepted discount offers whose pay-on date passed before the run: the discount lapses and the original due date returns."""
    lapsed = []
    for offer in session.execute(select(EarlyPaymentOffer).where(EarlyPaymentOffer.kind == "DISCOUNT", EarlyPaymentOffer.status == "ACCEPTED",
                                                                 EarlyPaymentOffer.pay_on < run_date)).scalars().all():
        invoice = session.get(Invoice, offer.invoice_id)
        if invoice.payment_status != "UNPAID" or invoice.status != "POSTED":
            continue
        invoice.payment_option, invoice.discount_minor = "STANDARD", 0
        if offer.original_due:
            invoice.due_date = offer.original_due
        offer.status = "EXPIRED"
        audit.record(session, "INVOICE", invoice.id, "EARLY_PAYMENT_LAPSED", object_ref=invoice.number,
                     reason=f"not paid by {offer.pay_on.isoformat()}", after={"offer": str(offer.id), "dueDate": invoice.due_date.isoformat()})
        lapsed.append(invoice.number)
    return lapsed


def deduction_minor(invoice: Invoice) -> int:
    return int(invoice.discount_minor or 0) if invoice.payment_option == "EARLY_DISCOUNT" else 0


def applied(session: Session, invoice: Invoice) -> None:
    for offer in session.execute(select(EarlyPaymentOffer).where(EarlyPaymentOffer.invoice_id == invoice.id, EarlyPaymentOffer.kind == "DISCOUNT",
                                                                 EarlyPaymentOffer.status == "ACCEPTED")).scalars():
        offer.status = "APPLIED"
        audit.record(session, "INVOICE", invoice.id, "EARLY_PAYMENT_APPLIED", object_ref=invoice.number,
                     after={"offer": str(offer.id), "discountMinor": offer.discount_minor})


def view(offer: EarlyPaymentOffer) -> dict:
    return {"id": str(offer.id), "kind": offer.kind, "source": offer.source, "status": offer.status, "discountPct": str(offer.discount_pct),
            "discountMinor": offer.discount_minor, "payOn": offer.pay_on.isoformat() if offer.pay_on else None,
            "originalDue": offer.original_due.isoformat() if offer.original_due else None, "expiresOn": offer.expires_on.isoformat(),
            "annualisedPct": str(offer.annualised_pct) if offer.annualised_pct is not None else None, "note": offer.note,
            "erpDocument": offer.erp_doc_no, "rowVersion": offer.row_version}
