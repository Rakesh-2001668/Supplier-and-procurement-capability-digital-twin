"""General enterprise (indirect) template control (BP §23, pending workflow 45): purchasing cards.

Rule ``PCARD`` (carried by the general template): ``maxPerTransactionMinor`` and ``maxMonthlyMinor`` (the ceiling no card may exceed),
``blockedMccs`` (merchant categories no card may be used for, ISO 18245), ``poRequiredAboveMinor`` (a card transaction above this
amount must match a purchase order), ``matchToleranceMinor`` and ``matchWindowDays``. Card holders, per-card limits and merchant
category lists are kept per card; a card statement is reconciled line by line to purchase orders; breaches and unmatched
transactions go to the cost-object owner for review (never the card holder)."""
import re
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import AppUser, PCard, PCardStatement, PCardTransaction, PoLine, PurchaseOrder, Supplier, Task
from app.pic.platform import audit, clock, outbox, workflow
from app.pic.platform.core import link
from app.pic.platform.errors import Problem, illegal_transition, not_found, rule_violation
from app.pic.platform.money import D, fmt_inr, tax_amount
from app.pic.platform.serialize import jsonable, row
from app.pic.services import ind_common
from app.pic.services.common import principal

REVIEW_TASK = "PCARD_REVIEW"
MAX_STATEMENT_LINES = 5000


def _rule(session: Session):
    return ind_common.require_rule(session, "PCARD", "Purchasing cards")


def _require_admin(session: Session) -> None:
    if not set(principal(session).roles) & {"FINANCE_CONTROLLER", "TENANT_ADMIN"}:
        raise Problem(403, "FORBIDDEN", "Purchasing cards are administered by finance")


# ---------------------------------------------------------------- cards and limits
def issue_card(session: Session, *, holder_name: str, issuer: str, card_last4: str, per_txn_limit_minor: int, monthly_limit_minor: int,
               holder_email: Optional[str] = None, blocked_mccs: Optional[list] = None, allowed_mccs: Optional[list] = None,
               cost_object: Optional[str] = None, valid_to: Optional[date] = None) -> PCard:
    p = principal(session)
    rule = _rule(session)
    _require_admin(session)
    if not re.fullmatch(r"\d{4}", card_last4 or ""):
        raise Problem(422, "INVALID_CARD", "card_last4 is the last four digits of the card number (the full number is never stored)")
    holder = None
    if holder_email:
        holder = session.execute(select(AppUser).where(AppUser.email == holder_email)).scalar_one_or_none()
        if holder is None:
            raise not_found("User", holder_email)
        if holder.id == p.user_id:
            raise Problem(403, "SOD_CONFLICT", "Segregation of duties: you cannot issue a card to yourself", rule_ref="SOD-PCARD")
    _check_limits(rule, per_txn_limit_minor, monthly_limit_minor)
    for mcc in list(blocked_mccs or []) + list(allowed_mccs or []):
        if not re.fullmatch(r"\d{4}", str(mcc)):
            raise Problem(422, "INVALID_MCC", f"Merchant category code {mcc} is not four digits (ISO 18245)")
    if cost_object and ":" not in cost_object:
        raise Problem(422, "INVALID_COST_OBJECT", "cost_object is TYPE:CODE, e.g. COST_CENTER:6100")
    ctype, ccode = (cost_object.split(":", 1) if cost_object else (None, None))
    if session.execute(select(PCard.id).where(PCard.issuer == issuer, PCard.card_last4 == card_last4, PCard.holder_name == holder_name)).first():
        raise Problem(409, "DUPLICATE_CARD", f"{holder_name}'s {issuer} card ending {card_last4} is already registered", rule_ref=rule.ref)
    card = PCard(tenant_id=current_tenant(session), number=ind_common.number(session, "PCARD", "PC-", 1001, 0), holder_user_id=holder.id if holder else None,
                 holder_name=holder_name, issuer=issuer, card_last4=card_last4, per_txn_limit_minor=per_txn_limit_minor,
                 monthly_limit_minor=monthly_limit_minor, blocked_mccs=sorted({str(m) for m in blocked_mccs or []}),
                 allowed_mccs=sorted({str(m) for m in allowed_mccs or []}), cost_object_type=ctype, cost_object_code=ccode, status="ACTIVE",
                 valid_to=valid_to, created_by=p.user_id)
    session.add(card)
    session.flush()
    audit.record(session, "PCARD", card.id, "ISSUED", object_ref=card.number, rule_set_version=rule.ref,
                 after={"holder": holder_name, "issuer": issuer, "last4": card_last4, "perTxnLimitMinor": per_txn_limit_minor,
                        "monthlyLimitMinor": monthly_limit_minor, "blockedMccs": card.blocked_mccs, "allowedMccs": card.allowed_mccs,
                        "costObject": cost_object, "validTo": valid_to.isoformat() if valid_to else None})
    return card


def _check_limits(rule, per_txn: int, monthly: int) -> None:
    if per_txn <= 0 or monthly < per_txn:
        raise Problem(422, "INVALID_LIMITS", "The per-transaction limit is positive and the monthly limit at least that", rule_ref=rule.ref)
    if per_txn > int(rule.body.get("maxPerTransactionMinor", per_txn)) or monthly > int(rule.body.get("maxMonthlyMinor", monthly)):
        raise rule_violation(f"Limits above the policy ceiling: per transaction {fmt_inr(int(rule.body.get('maxPerTransactionMinor', 0)))}, "
                             f"per month {fmt_inr(int(rule.body.get('maxMonthlyMinor', 0)))}", rule.ref)


def change_limits(session: Session, card: PCard, *, per_txn_limit_minor: int, monthly_limit_minor: int, reason: str) -> PCard:
    rule = _rule(session)
    _require_admin(session)
    if not (reason or "").strip():
        raise Problem(422, "REASON_REQUIRED", "Give the reason for the limit change")
    if card.holder_user_id == principal(session).user_id:
        raise Problem(403, "SOD_CONFLICT", "Segregation of duties: you cannot change the limits of your own card", rule_ref="SOD-PCARD")
    if card.status != "ACTIVE":
        raise illegal_transition("Purchasing card", card.number, card.status, "change limits")
    _check_limits(rule, per_txn_limit_minor, monthly_limit_minor)
    before = {"perTxnLimitMinor": card.per_txn_limit_minor, "monthlyLimitMinor": card.monthly_limit_minor}
    card.per_txn_limit_minor, card.monthly_limit_minor = per_txn_limit_minor, monthly_limit_minor
    audit.record(session, "PCARD", card.id, "LIMITS_CHANGED", object_ref=card.number, before=before, reason=reason, rule_set_version=rule.ref,
                 after={"perTxnLimitMinor": per_txn_limit_minor, "monthlyLimitMinor": monthly_limit_minor})
    return card


def set_status(session: Session, card: PCard, status: str, reason: str) -> PCard:
    _rule(session)
    _require_admin(session)
    status = status.upper()
    if status not in ("ACTIVE", "SUSPENDED", "CLOSED") or not (reason or "").strip():
        raise Problem(422, "VALIDATION_FAILED", "status is ACTIVE, SUSPENDED or CLOSED, with a reason")
    if card.status == "CLOSED" or card.status == status:
        raise illegal_transition("Purchasing card", card.number, card.status, status.lower())
    before, card.status = card.status, status
    audit.record(session, "PCARD", card.id, status, object_ref=card.number, before={"status": before}, after={"status": status}, reason=reason)
    return card


def month_to_date(session: Session, card: PCard, on: date, exclude_id: Optional[uuid.UUID] = None) -> int:
    start = on.replace(day=1)
    end = (start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1))
    query = select(func.coalesce(func.sum(PCardTransaction.amount_minor), 0)).where(
        PCardTransaction.pcard_id == card.id, PCardTransaction.txn_date >= start, PCardTransaction.txn_date < end)
    if exclude_id is not None:
        query = query.where(PCardTransaction.id != exclude_id)
    return int(session.execute(query).scalar_one())


def check_use(card: PCard, amount_minor: int, mcc: str, on: date, month_spend_minor: int) -> list[dict]:
    """Why a card use is not allowed (empty list: allowed): card state and validity, merchant category, per-transaction and monthly limit."""
    reasons = []
    if card.status != "ACTIVE":
        reasons.append({"code": "CARD_NOT_ACTIVE", "detail": f"card {card.number} is {card.status.lower()}"})
    if card.valid_to and on > card.valid_to:
        reasons.append({"code": "CARD_EXPIRED", "detail": f"card valid to {card.valid_to.isoformat()}"})
    if mcc in (card.blocked_mccs or []):
        reasons.append({"code": "MCC_BLOCKED", "detail": f"merchant category {mcc} is blocked for this card"})
    elif card.allowed_mccs and mcc not in card.allowed_mccs:
        reasons.append({"code": "MCC_NOT_ALLOWED", "detail": f"merchant category {mcc} is not on the card's allowed list"})
    if amount_minor > card.per_txn_limit_minor:
        reasons.append({"code": "OVER_TXN_LIMIT", "detail": f"{fmt_inr(amount_minor)} exceeds the per-transaction limit {fmt_inr(card.per_txn_limit_minor)}"})
    if month_spend_minor + amount_minor > card.monthly_limit_minor:
        reasons.append({"code": "OVER_MONTHLY_LIMIT", "detail": f"month-to-date {fmt_inr(month_spend_minor)} + {fmt_inr(amount_minor)} exceeds the monthly limit "
                                                                f"{fmt_inr(card.monthly_limit_minor)}"})
    return reasons


def authorise(session: Session, card: PCard, *, amount_minor: int, mcc: str, on: Optional[date] = None, merchant: Optional[str] = None) -> dict:
    """Authorisation decision for a card use (the issuer's real-time authorisation hook): approved only inside every limit."""
    rule = _rule(session)
    if amount_minor <= 0 or not re.fullmatch(r"\d{4}", mcc or ""):
        raise Problem(422, "VALIDATION_FAILED", "A positive amount and a four-digit merchant category code are required", rule_ref=rule.ref)
    on = on or clock.today()
    blocked = [m for m in rule.body.get("blockedMccs") or [] if m == mcc]
    reasons = check_use(card, amount_minor, mcc, on, month_to_date(session, card, on))
    if blocked and not any(r["code"] == "MCC_BLOCKED" for r in reasons):
        reasons.append({"code": "MCC_BLOCKED", "detail": f"merchant category {mcc} is blocked by policy"})
    decision = "DECLINED" if reasons else "APPROVED"
    audit.record(session, "PCARD", card.id, f"AUTHORISATION_{decision}", object_ref=card.number, rule_set_version=rule.ref,
                 after={"amountMinor": amount_minor, "mcc": mcc, "merchant": merchant, "reasons": [r["code"] for r in reasons]})
    return {"card": card.number, "decision": decision, "reasons": reasons, "limitRemainingMinor": max(card.monthly_limit_minor - month_to_date(session, card, on), 0)}


# ---------------------------------------------------------------- statements and reconciliation
def _po_value(session: Session, po: PurchaseOrder) -> tuple[int, int]:
    net = gross = 0
    for line in session.execute(select(PoLine).where(PoLine.po_id == po.id)).scalars():
        net += line.net_minor
        gross += line.net_minor + tax_amount(line.net_minor, line.gst_rate)
    return net, gross


def _match_po(session: Session, txn: PCardTransaction, explicit: Optional[str], rule, taken: set) -> Optional[PurchaseOrder]:
    tolerance = int(rule.body.get("matchToleranceMinor", 100))
    if explicit:
        po = session.execute(select(PurchaseOrder).where(PurchaseOrder.number == explicit)).scalar_one_or_none()
        if po is None or po.status in ("CANCELLED", "DRAFT"):
            return None
        net, gross = _po_value(session, po)
        return po if min(abs(txn.amount_minor - net), abs(txn.amount_minor - gross)) <= tolerance else None
    window = int(rule.body.get("matchWindowDays", 45))
    token = re.sub(r"[^A-Za-z0-9 ]", " ", txn.merchant).split()
    if not token:
        return None
    first = token[0].lower()
    candidates = []
    for po, supplier in session.execute(select(PurchaseOrder, Supplier).join(Supplier, Supplier.id == PurchaseOrder.supplier_id).where(
            PurchaseOrder.status.notin_(("CANCELLED", "DRAFT")), PurchaseOrder.created_at >= clock.at_ist(txn.txn_date - timedelta(days=window), 0),
            func.lower(Supplier.legal_name).like(f"{first}%"))).all():
        if po.id in taken:
            continue
        net, gross = _po_value(session, po)
        if min(abs(txn.amount_minor - net), abs(txn.amount_minor - gross)) <= tolerance:
            candidates.append(po)
    return candidates[0] if len(candidates) == 1 else None


def import_statement(session: Session, *, issuer: str, period: str, lines: list[dict]) -> PCardStatement:
    """Card statement lines [{card_last4, holder_name?, txn_ref, txn_date, merchant, mcc, amount_minor, po?}] for a month. Each line is
    checked against its card's limits and merchant categories and matched to a purchase order (explicit reference, else supplier name
    and amount within tolerance); unmatched lines above the PO threshold and every breach go to the cost-object owner for review."""
    p = principal(session)
    rule = _rule(session)
    _require_admin(session)
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period or ""):
        raise Problem(422, "INVALID_PERIOD", "period is YYYY-MM")
    if not lines:
        raise Problem(422, "VALIDATION_FAILED", "A statement has at least one transaction")
    if len(lines) > MAX_STATEMENT_LINES:
        raise Problem(413, "TOO_MANY_ROWS", f"At most {MAX_STATEMENT_LINES} lines per statement")
    if session.execute(select(PCardStatement.id).where(PCardStatement.issuer == issuer, PCardStatement.period == period)).first():
        raise Problem(409, "DUPLICATE_STATEMENT", f"The {issuer} statement for {period} is already imported", rule_ref=rule.ref)
    cards = session.execute(select(PCard).where(PCard.issuer == issuer)).scalars().all()
    resolved = []
    for line in lines:
        options = [c for c in cards if c.card_last4 == line["card_last4"] and (not line.get("holder_name") or c.holder_name == line["holder_name"])]
        if len(options) != 1:
            raise Problem(422, "UNKNOWN_CARD", f"{issuer} card ending {line['card_last4']}" + (f" of {line['holder_name']}" if line.get("holder_name") else "")
                          + (" matches several cards: give holder_name" if options else " is not registered"), rule_ref=rule.ref)
        if int(line["amount_minor"]) <= 0 or not re.fullmatch(r"\d{4}", str(line["mcc"])):
            raise Problem(422, "VALIDATION_FAILED", f"{line['txn_ref']}: a positive amount and a four-digit merchant category code are required")
        resolved.append((options[0], line))
    refs = [(c.id, l["txn_ref"]) for c, l in resolved]
    if len(set(refs)) != len(refs):
        raise Problem(422, "DUPLICATE_TRANSACTION", "A transaction reference appears twice for the same card")
    statement = PCardStatement(tenant_id=current_tenant(session), number=ind_common.number(session, "PCARD_STATEMENT", "PCS-", 1001, 0), issuer=issuer,
                               period=period, status="IMPORTED", line_count=len(lines), total_minor=sum(int(l["amount_minor"]) for _, l in resolved),
                               imported_by=p.user_id, created_by=p.user_id)
    session.add(statement)
    session.flush()
    taken: set = set(session.execute(select(PCardTransaction.po_id).where(PCardTransaction.po_id.isnot(None))).scalars())
    reviews = 0
    for card, line in sorted(resolved, key=lambda item: (item[0].number, item[1]["txn_date"], item[1]["txn_ref"])):
        on = line["txn_date"] if isinstance(line["txn_date"], date) else date.fromisoformat(str(line["txn_date"]))
        amount = int(line["amount_minor"])
        txn = PCardTransaction(tenant_id=current_tenant(session), statement_id=statement.id, pcard_id=card.id, txn_ref=line["txn_ref"], txn_date=on,
                               merchant=line["merchant"], mcc=str(line["mcc"]), amount_minor=amount, status="UNMATCHED", exception_codes=[], created_by=p.user_id)
        session.add(txn)
        session.flush()
        reasons = check_use(card, amount, txn.mcc, on, month_to_date(session, card, on, exclude_id=txn.id))
        if txn.mcc in (rule.body.get("blockedMccs") or []) and not any(r["code"] == "MCC_BLOCKED" for r in reasons):
            reasons.append({"code": "MCC_BLOCKED", "detail": f"merchant category {txn.mcc} is blocked by policy"})
        po = _match_po(session, txn, line.get("po"), rule, taken)
        if po is not None:
            txn.po_id = po.id
            taken.add(po.id)
            link(session, "PCARD_STATEMENT", statement.id, statement.number, "PURCHASE_ORDER", po.id, po.number, "settles")
        elif line.get("po"):
            reasons.append({"code": "PO_MISMATCH", "detail": f"{line['po']} does not exist, is cancelled, or its value differs from {fmt_inr(amount)}"})
        elif amount > int(rule.body.get("poRequiredAboveMinor", 0)):
            reasons.append({"code": "NO_PO", "detail": f"{fmt_inr(amount)} exceeds {fmt_inr(int(rule.body.get('poRequiredAboveMinor', 0)))} and matches no purchase order"})
        txn.exception_codes = [r["code"] for r in reasons]
        if reasons:
            txn.status = "EXCEPTION"
            _open_review(session, card, txn, reasons, rule)
            reviews += 1
        else:
            txn.status = "MATCHED" if po is not None else "CLEARED"
    session.flush()
    audit.record(session, "PCARD_STATEMENT", statement.id, "IMPORTED", object_ref=statement.number, rule_set_version=rule.ref,
                 after={"issuer": issuer, "period": period, "lines": len(lines), "totalMinor": statement.total_minor, "exceptions": reviews})
    _refresh_statement(session, statement)
    return statement


def _open_review(session: Session, card: PCard, txn: PCardTransaction, reasons: list, rule) -> None:
    ind_common.open_task(
        session, REVIEW_TASK, rule.body.get("reviewRole", "COST_OBJECT_OWNER"), object_type="PCARD_TRANSACTION", object_id=txn.id,
        object_ref=f"{card.number}/{txn.txn_ref}", exclude=[card.holder_user_id] if card.holder_user_id else [], rule_set_version=rule.ref,
        scope={"cost_object": f"{card.cost_object_type}:{card.cost_object_code}"} if card.cost_object_type else None,
        evidence={"card": card.number, "holder": card.holder_name, "merchant": txn.merchant, "mcc": txn.mcc, "amountMinor": txn.amount_minor,
                  "date": txn.txn_date.isoformat(), "reasons": reasons})


@workflow.on_task(REVIEW_TASK)
def _review_decided(session: Session, task: Task, outcome: str) -> None:
    txn = session.get(PCardTransaction, task.object_id)
    if txn is None:
        return
    txn.reviewed_by, txn.review_note = task.completed_by, task.comment
    if outcome == "APPROVED":
        txn.status = "CLEARED"
        audit.record(session, "PCARD_TRANSACTION", txn.id, "REVIEW_APPROVED", object_ref=txn.txn_ref, reason=task.comment,
                     after={"exceptions": txn.exception_codes, "amountMinor": txn.amount_minor})
    else:
        audit.record(session, "PCARD_TRANSACTION", txn.id, "REVIEW_REJECTED", object_ref=txn.txn_ref, reason=task.comment,
                     after={"exceptions": txn.exception_codes, "amountMinor": txn.amount_minor})
        outbox.emit(session, "pcard.transaction_disallowed", "PCARD_TRANSACTION", txn.id, txn.txn_ref,
                    {"card": session.get(PCard, txn.pcard_id).number, "amountMinor": txn.amount_minor, "reasons": txn.exception_codes})
    _refresh_statement(session, session.get(PCardStatement, txn.statement_id))


def _refresh_statement(session: Session, statement: PCardStatement) -> None:
    open_items = session.execute(select(func.count()).select_from(PCardTransaction).where(
        PCardTransaction.statement_id == statement.id, PCardTransaction.status.in_(("EXCEPTION", "UNMATCHED")))).scalar_one()
    status = "RECONCILED" if open_items == 0 else "IMPORTED"
    if status != statement.status:
        statement.status = status
        audit.record(session, "PCARD_STATEMENT", statement.id, status, object_ref=statement.number, after={"openItems": open_items})


# ---------------------------------------------------------------- views
def card_view(session: Session, card: PCard) -> dict:
    spend = month_to_date(session, card, clock.today())
    return row(card, extra={"version": card.row_version, "monthToDateMinor": spend, "remainingMinor": max(card.monthly_limit_minor - spend, 0),
                            "utilisationPct": round(spend * 100 / card.monthly_limit_minor, 1) if card.monthly_limit_minor else 0})


def statement_view(session: Session, statement: PCardStatement) -> dict:
    txns = session.execute(select(PCardTransaction, PCard).join(PCard, PCard.id == PCardTransaction.pcard_id).where(
        PCardTransaction.statement_id == statement.id).order_by(PCard.number, PCardTransaction.txn_date, PCardTransaction.txn_ref)).all()
    pos = {po.id: po.number for po in session.execute(select(PurchaseOrder).where(PurchaseOrder.id.in_([t.po_id for t, _ in txns if t.po_id]))).scalars()} if txns else {}
    return row(statement, extra={"transactions": [row(t, extra={"card": c.number, "holder": c.holder_name, "po": pos.get(t.po_id)}) for t, c in txns],
                                 "matched": sum(1 for t, _ in txns if t.status == "MATCHED"), "cleared": sum(1 for t, _ in txns if t.status == "CLEARED"),
                                 "exceptions": sum(1 for t, _ in txns if t.status == "EXCEPTION")})
