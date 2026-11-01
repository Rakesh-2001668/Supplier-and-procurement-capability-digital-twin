"""M07 supplier rebates (pending workflow 26): volume or value tiers per contract or supplier, accrual from posted invoices net of credit
notes, and settlement as a vendor credit memo posted to the ERP exactly once.

An agreement states the basis (purchase VALUE in rupees or VOLUME in quantity), the period (month, Indian fiscal quarter or year), the tier
table and how tiers apply: RETROACTIVE (the rate of the tier reached applies to the whole basis of the period) or SLAB (each tier's rate
applies to the part of the basis inside it). The accrual of a period is recomputed from the facts whenever it is read or an invoice is
posted, so it is always right; settlement fixes the amount, creates the credit memo and closes the period for that agreement.
"""
import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    Contract, ContractLine, CreditNote, Invoice, InvoiceLine, PoLine, RebateAccrual, RebateAgreement, RebateSettlement, Supplier,
)
from app.pic.platform import audit, clock, integration, outbox
from app.pic.platform.core import link, next_number
from app.pic.platform.errors import Problem, illegal_transition, not_found, rule_violation
from app.pic.platform.money import D, fmt_inr
from app.pic.platform.serialize import row
from app.pic.services.common import principal

POSTED_INVOICE = ("POSTED", "PAID")
BASES, PERIODS, TIER_MODES, SCOPES = ("VOLUME", "VALUE"), ("MONTHLY", "QUARTERLY", "ANNUAL"), ("SLAB", "RETROACTIVE"), ("CONTRACT", "SUPPLIER")


# ---------------------------------------------------------------- periods (Indian fiscal year April-March)
def period_of(period: str, on: date) -> tuple[str, date, date]:
    """(label, first day, last day) of the rebate period that contains ``on``."""
    if period == "MONTHLY":
        start = on.replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return start.strftime("%Y-%m"), start, end
    fy = on.year if on.month >= 4 else on.year - 1
    if period == "ANNUAL":
        return f"FY{fy}-{str(fy + 1)[2:]}", date(fy, 4, 1), date(fy + 1, 3, 31)
    quarter = ((on.month - 4) % 12) // 3 + 1
    first_month = 4 + 3 * (quarter - 1)
    start = date(fy + (1 if first_month > 12 else 0), first_month - 12 if first_month > 12 else first_month, 1)
    end = (date(start.year + (start.month + 3 > 12), (start.month + 3 - 1) % 12 + 1, 1)) - timedelta(days=1)
    return f"FY{fy}-{str(fy + 1)[2:]}-Q{quarter}", start, end


def _tiers(raw: list[dict], basis: str) -> list[dict]:
    if not raw:
        raise Problem(422, "TIERS_REQUIRED", "Give at least one tier", rule_ref="CLM-REBATE")
    out, last_from, last_rate = [], None, None
    for entry in raw:
        try:
            start, rate = D(entry["from"]), D(entry["ratePct"])
        except Exception:  # noqa: BLE001
            raise Problem(422, "INVALID_TIERS", "Each tier needs from (a number) and ratePct (a number)", rule_ref="CLM-REBATE")
        if start < 0 or rate <= 0 or rate > 100:
            raise Problem(422, "INVALID_TIERS", "A tier starts at zero or above and has a rate above 0 and at most 100 percent", rule_ref="CLM-REBATE")
        if last_from is not None and start <= last_from:
            raise Problem(422, "INVALID_TIERS", "Tier thresholds must rise", rule_ref="CLM-REBATE")
        if last_rate is not None and rate < last_rate:
            raise Problem(422, "INVALID_TIERS", "A higher tier cannot pay a lower rate than the tier below it", rule_ref="CLM-REBATE")
        last_from, last_rate = start, rate
        out.append({"from": str(start), "ratePct": str(rate)})
    return out


def create_agreement(session: Session, contract: Contract, *, title: str, basis: str, period: str, tiers: list[dict], tier_mode: str = "RETROACTIVE",
                     scope: str = "CONTRACT", valid_from: Optional[date] = None, valid_to: Optional[date] = None) -> RebateAgreement:
    p = principal(session)
    basis, period, tier_mode, scope = basis.upper(), period.upper(), tier_mode.upper(), scope.upper()
    if basis not in BASES or period not in PERIODS or tier_mode not in TIER_MODES or scope not in SCOPES:
        raise Problem(422, "INVALID_REBATE", "basis, period, tier_mode or scope is not valid", rule_ref="CLM-REBATE")
    if contract.status in ("TERMINATED", "EXPIRED", "RENEWED"):
        raise illegal_transition("Contract", contract.number, contract.status, "add a rebate agreement")
    if contract.type == "NDA":
        raise rule_violation("An NDA carries no purchases and no rebate", "CLM-REBATE")
    if scope == "CONTRACT" and contract.type == "MASTER_AGREEMENT":
        raise rule_violation("A master agreement has no lines: its rebate applies to all purchases from the supplier (scope SUPPLIER)", "CLM-REBATE")
    valid_from, valid_to = valid_from or contract.valid_from, valid_to or contract.valid_to
    if valid_to < valid_from or valid_from < contract.valid_from or valid_to > contract.valid_to:
        raise rule_violation(f"The rebate period must lie within the contract's ({contract.valid_from} to {contract.valid_to})", "CLM-REBATE")
    if not (title or "").strip():
        raise Problem(422, "VALIDATION_FAILED", "Give the agreement a title", rule_ref="CLM-REBATE")
    agreement = RebateAgreement(
        tenant_id=current_tenant(session), number=next_number(session, "REBATE_AGREEMENT"), contract_id=contract.id, supplier_id=contract.supplier_id,
        title=title.strip(), basis=basis, period=period, tier_mode=tier_mode, scope=scope, tiers=_tiers(tiers, basis), valid_from=valid_from,
        valid_to=valid_to, status="ACTIVE", currency=contract.currency, company_code=contract.company_code, created_by=p.user_id)
    session.add(agreement)
    session.flush()
    link(session, "CONTRACT", contract.id, contract.number, "REBATE_AGREEMENT", agreement.id, agreement.number, "rebate")
    audit.record(session, "CONTRACT", contract.id, "REBATE_AGREED", object_ref=contract.number,
                 after={"agreement": agreement.number, "basis": basis, "period": period, "mode": tier_mode, "scope": scope, "tiers": agreement.tiers})
    return agreement


def cancel_agreement(session: Session, agreement: RebateAgreement, reason: str) -> RebateAgreement:
    if agreement.status != "ACTIVE":
        raise illegal_transition("Rebate agreement", agreement.number, agreement.status, "cancel")
    if not (reason or "").strip():
        raise Problem(422, "REASON_REQUIRED", "Give the reason for cancelling the rebate agreement", rule_ref="CLM-REBATE")
    open_period = session.execute(select(RebateAccrual).where(RebateAccrual.agreement_id == agreement.id, RebateAccrual.status == "OPEN",
                                                              RebateAccrual.accrued_minor > 0)).first()
    if open_period:
        raise rule_violation("Settle or write off the accrued periods first: an agreement with an unsettled accrual cannot be cancelled",
                             "CLM-REBATE")
    agreement.status = "CANCELLED"
    audit.record(session, "REBATE_AGREEMENT", agreement.id, "CANCELLED", object_ref=agreement.number, reason=reason)
    return agreement


# ---------------------------------------------------------------- basis and accrual
def basis_of(session: Session, agreement: RebateAgreement, start: date, end: date) -> tuple[int, Decimal, dict]:
    """(net value in paise, quantity, detail) bought from the supplier in the period: posted invoice lines net of credit-note lines. Scope
    CONTRACT counts only lines that reference this contract's lines."""
    contract_line_ids = None
    if agreement.scope == "CONTRACT":
        contract_line_ids = set(session.execute(select(ContractLine.id).where(ContractLine.contract_id == agreement.contract_id)).scalars())
    period_start, period_end = max(start, agreement.valid_from), min(end, agreement.valid_to)
    value, qty, invoices, credited = 0, Decimal(0), set(), 0
    if period_end < period_start:
        return 0, Decimal(0), {"invoices": 0, "creditedMinor": 0}
    for invoice in session.execute(select(Invoice).where(
            Invoice.supplier_id == agreement.supplier_id, Invoice.company_code == agreement.company_code, Invoice.status.in_(POSTED_INVOICE),
            Invoice.invoice_date >= period_start, Invoice.invoice_date <= period_end)).scalars():
        lines = session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)).scalars().all()
        in_scope = {}
        for line in lines:
            if contract_line_ids is not None:
                po_line = session.get(PoLine, line.po_line_id) if line.po_line_id else None
                if po_line is None or po_line.contract_line_id not in contract_line_ids:
                    continue
            in_scope[line.line_no] = line
            value += line.net_minor
            qty += line.qty
        if in_scope:
            invoices.add(invoice.number)
        for note in session.execute(select(CreditNote).where(CreditNote.invoice_id == invoice.id)).scalars():
            for entry in note.lines or []:
                line = in_scope.get(int(entry["invoice_line"]))
                if line is None:
                    continue
                unit = int(entry["unitCreditMinor"]) if entry.get("unitCreditMinor") not in (None, "") else line.unit_price_minor
                amount = int((D(entry["qty"]) * unit).quantize(Decimal("1"), ROUND_HALF_UP))
                value -= amount
                credited += amount
                if entry.get("unitCreditMinor") in (None, ""):
                    qty -= D(entry["qty"])
    return max(value, 0), max(qty, Decimal(0)), {"invoices": len(invoices), "invoiceNumbers": sorted(invoices)[:25], "creditedMinor": credited}


def rebate_for(agreement: RebateAgreement, value_minor: int, qty: Decimal) -> tuple[int, Decimal, list]:
    """(rebate in paise, effective rate %, per-tier working) for the period's basis."""
    tiers = [(D(t["from"]), D(t["ratePct"])) for t in agreement.tiers]
    measure = Decimal(value_minor) / 100 if agreement.basis == "VALUE" else qty  # tiers are in rupees (VALUE) or in quantity (VOLUME)
    total = Decimal(value_minor)
    if total <= 0 or measure < tiers[0][0]:
        return 0, Decimal(0), []
    working = []
    if agreement.tier_mode == "RETROACTIVE":
        reached = [t for t in tiers if measure >= t[0]][-1]
        amount = total * reached[1] / 100
        working.append({"tierFrom": str(reached[0]), "ratePct": str(reached[1]), "applied": "whole period"})
    else:
        amount = Decimal(0)
        for index, (low, rate) in enumerate(tiers):
            high = tiers[index + 1][0] if index + 1 < len(tiers) else None
            if measure <= low:
                break
            part = (min(measure, high) if high is not None else measure) - low
            share = part / measure  # the part of the basis inside the tier, as a share of the period's basis
            slice_amount = total * share * rate / 100
            amount += slice_amount
            working.append({"tierFrom": str(low), "ratePct": str(rate), "partOfBasis": str(part), "amountMinor": int(slice_amount.quantize(Decimal("1"), ROUND_HALF_UP))})
    rebate = int(amount.quantize(Decimal("1"), ROUND_HALF_UP))
    return rebate, (Decimal(rebate) * 100 / total).quantize(Decimal("0.001")), working


def accrue(session: Session, agreement: RebateAgreement, on: Optional[date] = None) -> Optional[RebateAccrual]:
    """Recompute the accrual of the period that contains ``on`` (default today). A settled period is left as it is."""
    on = on or clock.today()
    if agreement.status != "ACTIVE" or on < agreement.valid_from or on > agreement.valid_to:
        return None
    label, start, end = period_of(agreement.period, on)
    accrual = session.execute(select(RebateAccrual).where(RebateAccrual.agreement_id == agreement.id, RebateAccrual.period_label == label)
                              .with_for_update()).scalar_one_or_none()
    if accrual is not None and accrual.status == "SETTLED":
        return accrual
    value, qty, detail = basis_of(session, agreement, start, end)
    amount, rate, working = rebate_for(agreement, value, qty)
    before = accrual.accrued_minor if accrual is not None else None
    if accrual is None:
        accrual = RebateAccrual(tenant_id=agreement.tenant_id, agreement_id=agreement.id, period_label=label, period_start=start, period_end=end,
                                status="OPEN", computed_at=clock.now(), created_by=principal(session).user_id if session.info.get("principal") else None)
        session.add(accrual)
    accrual.basis_value_minor, accrual.basis_qty, accrual.rate_pct, accrual.accrued_minor = value, qty, rate, amount
    accrual.detail, accrual.computed_at = {**detail, "tiers": working}, clock.now()
    session.flush()
    if before != amount:
        audit.record(session, "REBATE_AGREEMENT", agreement.id, "ACCRUED", object_ref=agreement.number,
                     before={"accruedMinor": before}, after={"period": label, "basisValueMinor": value, "basisQty": str(qty),
                                                              "ratePct": str(rate), "accruedMinor": amount})
    return accrual


def accrue_all(session: Session, on: Optional[date] = None) -> dict:
    """Accrue every active agreement for the period of ``on`` (the scheduled run; also the catch-up after back-dated postings)."""
    done, total = 0, 0
    for agreement in session.execute(select(RebateAgreement).where(RebateAgreement.status == "ACTIVE")).scalars():
        accrual = accrue(session, agreement, on)
        if accrual is not None:
            done += 1
            total += accrual.accrued_minor
    return {"agreements": done, "accruedMinor": total}


@outbox.consumer("invoice.posted", "rebate-accrual")
def _on_invoice_posted(session: Session, event) -> None:
    invoice = session.get(Invoice, uuid.UUID(event.payload["invoiceId"]))
    if invoice is None:
        return
    for agreement in session.execute(select(RebateAgreement).where(RebateAgreement.supplier_id == invoice.supplier_id,
                                                                   RebateAgreement.company_code == invoice.company_code,
                                                                   RebateAgreement.status == "ACTIVE")).scalars():
        accrue(session, agreement, invoice.invoice_date)


# ---------------------------------------------------------------- settlement (credit memo through payables)
def settle(session: Session, accrual: RebateAccrual) -> RebateSettlement:
    p = principal(session)
    if not set(p.roles) & {"FINANCE_CONTROLLER", "CONTRACT_MANAGER"}:
        raise Problem(403, "FORBIDDEN", "Rebates are settled by finance or the contract manager", rule_ref="CLM-REBATE")
    agreement = session.get(RebateAgreement, accrual.agreement_id, with_for_update=True)
    accrual = session.get(RebateAccrual, accrual.id, with_for_update=True)
    if accrual.status != "OPEN":
        raise illegal_transition("Rebate accrual", f"{agreement.number} {accrual.period_label}", accrual.status, "settle")
    if accrual.period_end >= clock.today():
        raise rule_violation(f"The period {accrual.period_label} ends on {accrual.period_end}: settle after it has ended", "CLM-REBATE")
    accrual = accrue(session, agreement, accrual.period_end)  # final recompute: invoices and credit notes posted late are included
    if accrual.accrued_minor <= 0:
        raise rule_violation(f"No rebate is due for {accrual.period_label}: the tier was not reached", "CLM-REBATE")
    supplier = session.get(Supplier, agreement.supplier_id)
    from app.pic.platform import connectors

    target = integration.target_system(session, agreement.company_code)
    connectors.require_mapped(target, "SUPPLIER_CREDIT_MEMO")
    number = next_number(session, "REBATE_SETTLEMENT")
    key = f"REBATE|{agreement.number}|{accrual.period_label}"
    settlement = RebateSettlement(tenant_id=agreement.tenant_id, number=number, agreement_id=agreement.id, accrual_id=accrual.id,
                                  supplier_id=agreement.supplier_id, amount_minor=accrual.accrued_minor, status="PENDING_ERP", settled_by=p.user_id,
                                  erp_key=key, created_by=p.user_id)
    session.add(settlement)
    accrual.status = "SETTLED"
    session.flush()
    message = integration.enqueue(
        session, target_system=target, message_type="SUPPLIER_CREDIT_MEMO", idempotency_key=key, object_type="REBATE_SETTLEMENT",
        object_id=settlement.id, object_ref=settlement.number,
        payload={"creditNote": number, "supplier": supplier.code, "companyCode": agreement.company_code, "grossMinor": settlement.amount_minor,
                 "rebate": agreement.number, "period": accrual.period_label, "invoice": number, "invoiceErp": None})
    audit.record(session, "REBATE_AGREEMENT", agreement.id, "SETTLED", object_ref=agreement.number,
                 after={"settlement": number, "period": accrual.period_label, "amountMinor": settlement.amount_minor, "erpKey": key})
    outbox.emit(session, "rebate.settled", "REBATE_SETTLEMENT", settlement.id, number,
                {"supplierId": str(supplier.id), "supplier": supplier.code, "agreement": agreement.number, "period": accrual.period_label,
                 "amountMinor": settlement.amount_minor, "companyCode": agreement.company_code, "erpKey": key})
    integration.process(session, message)
    return sync_settlement(session, settlement)


def sync_settlement(session: Session, settlement: RebateSettlement) -> RebateSettlement:
    """The credit memo is posted by the connector worker (retries on failure); the settlement follows the integration message by its key."""
    if settlement.status == "POSTED":
        return settlement
    from app.pic.models import IntegrationMessage

    message = session.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == settlement.erp_key,
                                                               IntegrationMessage.message_type == "SUPPLIER_CREDIT_MEMO")).scalars().first()
    if message is not None and message.status == "POSTED":
        settlement.status, settlement.erp_document, settlement.posted_at = "POSTED", message.erp_doc_no, clock.now()
        audit.record(session, "REBATE_SETTLEMENT", settlement.id, "ERP_CREDIT_MEMO_POSTED", object_ref=settlement.number,
                     after={"erpDocument": message.erp_doc_no, "amountMinor": settlement.amount_minor})
    return settlement


# ---------------------------------------------------------------- read
def agreement_view(session: Session, agreement: RebateAgreement) -> dict:
    contract = session.get(Contract, agreement.contract_id)
    supplier = session.get(Supplier, agreement.supplier_id)
    accruals = session.execute(select(RebateAccrual).where(RebateAccrual.agreement_id == agreement.id)
                               .order_by(RebateAccrual.period_start.desc())).scalars().all()
    settlements = {s.accrual_id: sync_settlement(session, s) for s in session.execute(
        select(RebateSettlement).where(RebateSettlement.agreement_id == agreement.id)).scalars()}
    return row(agreement, extra={
        "contract": contract.number, "supplier": supplier.code,
        "accruals": [row(a, extra={"settlement": row(settlements[a.id]) if a.id in settlements else None,
                                   "settleable": a.status == "OPEN" and a.period_end < clock.today() and a.accrued_minor > 0}) for a in accruals],
        "accruedOpenMinor": sum(a.accrued_minor for a in accruals if a.status == "OPEN"),
        "settledMinor": sum(s.amount_minor for s in settlements.values())})


def list_for_contract(session: Session, contract: Contract) -> list[dict]:
    return [agreement_view(session, a) for a in session.execute(select(RebateAgreement).where(RebateAgreement.contract_id == contract.id)
                                                                .order_by(RebateAgreement.created_at)).scalars()]


def by_number(session: Session, ref: str, lock: bool = False) -> RebateAgreement:
    query = select(RebateAgreement)
    try:
        query = query.where(RebateAgreement.id == uuid.UUID(str(ref)))
    except ValueError:
        query = query.where(RebateAgreement.number == ref)
    found = session.execute(query.with_for_update() if lock else query).scalar_one_or_none()
    if found is None:
        raise not_found("Rebate agreement", ref)
    return found
