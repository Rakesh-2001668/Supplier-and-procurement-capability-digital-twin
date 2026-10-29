"""M11 savings ledger (P12, Technical Document §9.5) and M01 spend lines."""
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.pic.models import (
    Contract, ContractLine, CreditNote, Invoice, InvoiceLine, Material, PoLine, PriceValidity, PurchaseOrder, SavingsInitiative, SavingsLedgerEntry,
    SourcingEvent,
    SpendLine, Supplier,
)
from app.pic.platform import agents, audit, clock, outbox, sod, workflow
from app.pic.platform.core import StateMachine, link, next_number
from app.pic.platform.errors import Problem, illegal_transition
from app.pic.platform.money import D, crore, fmt_inr, line_amount
from app.pic.services import spend
from app.pic.services.common import principal

SM = StateMachine("SAVINGS_INITIATIVE", {
    ("IDENTIFIED", "negotiate"): "NEGOTIATED",
    ("NEGOTIATED", "contract"): "CONTRACTED",
    ("CONTRACTED", "realise"): "REALISING",
    ("NEGOTIATED", "realise"): "REALISING",
    ("REALISING", "validate"): "VALIDATED",
    ("IDENTIFIED", "lose"): "LOST",
    ("NEGOTIATED", "lose"): "LOST",
}, field="stage")


def _ledger(session: Session, initiative: SavingsInitiative, type_: str, amount: int, counts: bool, formula: str, source_type: str,
            source_ref: str) -> Optional[SavingsLedgerEntry]:
    exists = session.execute(select(SavingsLedgerEntry).where(SavingsLedgerEntry.initiative_id == initiative.id,
                                                              SavingsLedgerEntry.type == type_, SavingsLedgerEntry.source_ref == source_ref)).first()
    if exists:
        return None
    entry = SavingsLedgerEntry(tenant_id=initiative.tenant_id, initiative_id=initiative.id, type=type_, amount_minor=amount,
                               counts_toward_budget=counts, formula=formula, source_type=source_type, source_ref=source_ref,
                               posting_date=clock.today(), created_by=principal(session).user_id)
    session.add(entry)
    session.flush()
    return entry


def _by_event(session: Session, event_id: uuid.UUID) -> Optional[SavingsInitiative]:
    return session.execute(select(SavingsInitiative).where(SavingsInitiative.source_event_id == event_id)).scalar_one_or_none()


@outbox.consumer("sourcing.event.published", "savings-identify")
def _identified(session: Session, event) -> None:
    sourcing_event = session.get(SourcingEvent, event.object_id)
    if _by_event(session, sourcing_event.id) or not sourcing_event.baseline_price_minor:
        return
    line = event.payload["lines"][0]
    initiative = SavingsInitiative(
        tenant_id=sourcing_event.tenant_id, number=next_number(session, "SAVINGS"), title=sourcing_event.title,
        category=sourcing_event.category, material_id=uuid.UUID(line["material"]) if line.get("material") not in (None, "None") else None,
        source_event_id=sourcing_event.id, owner_id=sourcing_event.owner_id, stage="IDENTIFIED",
        baseline_method=sourcing_event.baseline_method or "LAST_PRICE", baseline_price_minor=sourcing_event.baseline_price_minor,
        annual_volume=D(line["annualQty"]), created_by=sourcing_event.owner_id,
    )
    session.add(initiative)
    session.flush()
    # SOD-07: the owner who initiates savings cannot validate them.
    sod.record(session, "SAVINGS_INITIATE", {"initiative_id": initiative.id}, actor_id=initiative.owner_id)
    link(session, "SOURCING_EVENT", sourcing_event.id, sourcing_event.number, "SAVINGS_INITIATIVE", initiative.id, initiative.number, "tracked_by")
    audit.record(session, "SAVINGS_INITIATIVE", initiative.id, "IDENTIFIED", object_ref=initiative.number,
                 after={"baselineMethod": initiative.baseline_method, "baselineMinor": initiative.baseline_price_minor})


@outbox.consumer("sourcing.event.cancelled", "savings-lost")
def _event_cancelled(session: Session, event) -> None:
    """A cancelled event will not deliver the savings it was tracked for."""
    initiative = _by_event(session, event.object_id)
    if initiative is None or not SM.can(initiative.stage, "lose"):
        return
    SM.apply(session, initiative, "lose", reason=f"sourcing event {event.object_ref} cancelled: {event.payload.get('reason')}")


@outbox.consumer("sourcing.event.awarded", "savings-negotiated")
def _negotiated(session: Session, event) -> None:
    initiative = _by_event(session, event.object_id)
    if initiative is None:
        return
    data = event.payload
    weighted = int(data["weightedPriceMinor"])
    volume = D(data["annualQty"])
    amount = int(((Decimal(initiative.baseline_price_minor) - weighted) * volume).quantize(Decimal("1"), ROUND_HALF_UP))
    initiative.new_price_minor = weighted
    initiative.annual_volume = volume
    initiative.supplier_prices = {a["supplierId"]: a["priceMinor"] for a in data["allocations"]}
    _ledger(session, initiative, "NEGOTIATED", amount, False,
            f"({initiative.baseline_price_minor/100:.2f} − {weighted/100:.2f}) × {volume} /yr", "SOURCING_EVENT", event.object_ref)
    SM.apply(session, initiative, "negotiate", extra_after={"negotiatedMinor": amount})


@outbox.consumer("contract.activated", "savings-contracted")
def _contracted(session: Session, event) -> None:
    source_event = event.payload.get("sourceEventId")
    if not source_event:
        return
    initiative = _by_event(session, uuid.UUID(source_event))
    if initiative is None or initiative.stage != "NEGOTIATED":
        return
    contracts = session.execute(select(Contract).where(Contract.source_event_id == initiative.source_event_id)).scalars().all()
    if contracts and all(c.status in ("ACTIVE", "EXPIRING") for c in contracts):
        SM.apply(session, initiative, "contract", extra_after={"contracts": [c.number for c in contracts]})


def record_avoidance(session: Session, *, source_event_id: uuid.UUID, requested_price_minor: int, agreed_price_minor: int, volume: Decimal,
                     reason: str, source_ref: str) -> Optional[SavingsLedgerEntry]:
    initiative = _by_event(session, source_event_id)
    if initiative is None:
        return None
    amount = int(((Decimal(requested_price_minor) - agreed_price_minor) * volume).quantize(Decimal("1"), ROUND_HALF_UP))
    if amount <= 0:
        return None
    # Cost avoidance never counts toward budget reduction.
    return _ledger(session, initiative, "AVOIDANCE", amount, False,
                   f"({requested_price_minor/100:.2f} − {agreed_price_minor/100:.2f}) × {volume}: {reason}", "CONTRACT_INDEX", source_ref)


@outbox.consumer("invoice.posted", "savings-realised")
def _realised(session: Session, event) -> None:
    invoice = session.get(Invoice, uuid.UUID(event.payload["invoiceId"]))
    credited: dict[int, Decimal] = {}
    for note in session.execute(select(CreditNote).where(CreditNote.invoice_id == invoice.id)).scalars():
        for entry in note.lines:
            credited[int(entry["invoice_line"])] = credited.get(int(entry["invoice_line"]), Decimal(0)) + D(entry["qty"])
    booked = []
    for line in session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)).scalars():
        po_line = session.get(PoLine, line.po_line_id)
        if po_line.material_id is None:
            continue
        initiative = session.execute(select(SavingsInitiative).where(SavingsInitiative.material_id == po_line.material_id,
                                                                     SavingsInitiative.stage.in_(("NEGOTIATED", "CONTRACTED", "REALISING", "VALIDATED")))).scalar_one_or_none()
        if initiative is None or str(invoice.supplier_id) not in (initiative.supplier_prices or {}):
            continue
        qty = line.qty - credited.get(line.line_no, Decimal(0))
        amount = int(((Decimal(initiative.baseline_price_minor) - line.unit_price_minor) * qty).quantize(Decimal("1"), ROUND_HALF_UP))
        entry = _ledger(session, initiative, "REALISED", amount, True,
                        f"({initiative.baseline_price_minor/100:.2f} − {line.unit_price_minor/100:.2f}) × {qty} invoiced", "INVOICE",
                        f"{invoice.number}/{line.line_no}")
        if entry:
            booked.append(entry)
            if initiative.stage in ("NEGOTIATED", "CONTRACTED"):
                SM.apply(session, initiative, "realise", extra_after={"firstRealisedFrom": invoice.number})
            agents.log_run(session, "SAVINGS_VALIDATION", object_type="SAVINGS_INITIATIVE", object_id=initiative.id,
                           object_ref=initiative.number, inputs={"invoice": invoice.number, "qty": str(qty)},
                           evidence=[invoice.number, invoice.erp_doc_no], output={"realisedMinor": amount}, confidence=1.0,
                           action_taken="EXECUTED")
            outbox.emit(session, "savings.realised", "SAVINGS_INITIATIVE", initiative.id, initiative.number,
                        {"invoice": invoice.number, "amountMinor": amount})
    from app.pic.services import payables
    instance = workflow.find(session, "INVOICE", invoice.id, payables.PROCESS)
    if instance:
        total = sum(e.amount_minor for e in booked)
        workflow.step(session, instance, "F7-08", outcome=f"realised savings {fmt_inr(total)}; scorecard and spend updated")


def validate(session: Session, initiative: SavingsInitiative) -> SavingsInitiative:
    p = principal(session)
    if "FINANCE_CONTROLLER" not in p.roles:
        raise Problem(403, "FORBIDDEN", "Savings are validated by finance", rule_ref="P12")
    sod.guard(session, "SAVINGS_VALIDATE", {"initiative_id": initiative.id})
    if initiative.owner_id == p.user_id:
        raise Problem(409, "SOD_CONFLICT", "SOD-07: the initiative owner cannot validate it", rule_ref="SOD-07")
    SM.apply(session, initiative, "validate")
    sod.record(session, "SAVINGS_VALIDATE", {"initiative_id": initiative.id})
    initiative.validated_by = p.user_id
    initiative.validated_at = clock.now()
    return initiative


def register(session: Session) -> list[dict]:
    out = []
    for initiative in session.execute(select(SavingsInitiative).order_by(SavingsInitiative.number)).scalars():
        totals = dict(session.execute(select(SavingsLedgerEntry.type, func.sum(SavingsLedgerEntry.amount_minor)).where(
            SavingsLedgerEntry.initiative_id == initiative.id).group_by(SavingsLedgerEntry.type)).all())
        out.append({"id": str(initiative.id), "ownerId": str(initiative.owner_id), "number": initiative.number, "title": initiative.title, "stage": initiative.stage, "category": initiative.category,
                    "baselineMethod": initiative.baseline_method, "baselinePriceMinor": initiative.baseline_price_minor,
                    "newPriceMinor": initiative.new_price_minor, "annualVolume": str(initiative.annual_volume),
                    "negotiatedMinor": totals.get("NEGOTIATED", 0), "avoidanceMinor": totals.get("AVOIDANCE", 0),
                    "realisedMinor": totals.get("REALISED", 0),
                    "negotiatedCr": str(crore(totals.get("NEGOTIATED", 0))), "avoidanceCr": str(crore(totals.get("AVOIDANCE", 0))),
                    "realisedCr": str(crore(totals.get("REALISED", 0))), "validated": initiative.stage == "VALIDATED"})
    return out


def waterfall(session: Session, initiative: SavingsInitiative) -> dict:
    """Negotiated → contracted → realised, with leakage from off-contract and above-contract invoicing."""
    entries = session.execute(select(SavingsLedgerEntry).where(SavingsLedgerEntry.initiative_id == initiative.id)
                              .order_by(SavingsLedgerEntry.created_at)).scalars().all()
    negotiated = sum(e.amount_minor for e in entries if e.type == "NEGOTIATED")
    realised = sum(e.amount_minor for e in entries if e.type == "REALISED")
    avoidance = sum(e.amount_minor for e in entries if e.type == "AVOIDANCE")
    contracted = negotiated if initiative.stage in ("CONTRACTED", "REALISING", "VALIDATED") else 0
    leakage = []
    if initiative.material_id:
        for line, po in session.execute(select(PoLine, PurchaseOrder).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(
                PoLine.material_id == initiative.material_id, PoLine.invoiced_qty > 0)).all():
            agreed = (initiative.supplier_prices or {}).get(str(po.supplier_id))
            if agreed is None:
                leakage.append({"po": po.number, "kind": "OFF_CONTRACT", "amountMinor": line_amount(line.invoiced_qty, line.unit_price_minor - (initiative.new_price_minor or 0))})
            elif line.unit_price_minor > agreed:
                leakage.append({"po": po.number, "kind": "PRICE_DRIFT", "amountMinor": line_amount(line.invoiced_qty, line.unit_price_minor - agreed)})
    return {"initiative": initiative.number, "stage": initiative.stage, "negotiatedMinor": negotiated, "contractedMinor": contracted,
            "realisedMinor": realised, "avoidanceMinor": avoidance, "leakage": leakage,
            "budgetImpactMinor": sum(e.amount_minor for e in entries if e.counts_toward_budget) if initiative.stage == "VALIDATED" else 0,
            "entries": [{"type": e.type, "amountMinor": e.amount_minor, "countsTowardBudget": e.counts_toward_budget,
                         "formula": e.formula, "source": e.source_ref, "date": e.posting_date.isoformat()} for e in entries]}


# ---------------------------------------------------------------- spend (M01)
@outbox.consumer("invoice.posted", "spend-cube")
def _spend(session: Session, event) -> None:
    invoice = session.get(Invoice, uuid.UUID(event.payload["invoiceId"]))
    credited: dict[int, Decimal] = {}
    for note in session.execute(select(CreditNote).where(CreditNote.invoice_id == invoice.id)).scalars():
        for entry in note.lines:
            credited[int(entry["invoice_line"])] = credited.get(int(entry["invoice_line"]), Decimal(0)) + D(entry["qty"])
    for line in session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)).scalars():
        po_line = session.get(PoLine, line.po_line_id)
        po = session.get(PurchaseOrder, po_line.po_id)
        material = session.get(Material, po_line.material_id) if po_line.material_id else None
        flags = []
        if po.created_at.date() > invoice.invoice_date:
            flags.append("PO_AFTER_INVOICE")
        if material and po_line.contract_line_id is None and session.execute(
                select(ContractLine.id).join(Contract, Contract.id == ContractLine.contract_id).where(
                    ContractLine.material_id == material.id, Contract.status.in_(("ACTIVE", "EXPIRING")))).first():
            flags.append("OFF_CONTRACT")
        if any(f.get("code") == "SPLIT_PATTERN" for f in (po.risk_factors or [])):
            flags.append("SPLIT_PO")
        if po_line.price_deviation:
            flags.append("OFF_CONTRACT_PRICE")
        qty = line.qty - credited.get(line.line_no, Decimal(0))
        reference = None
        if po_line.price_validity_id:
            reference = session.get(PriceValidity, po_line.price_validity_id).unit_price_minor
        elif material and material.standard_price_minor:
            reference = material.standard_price_minor
        variance = line_amount(qty, line.unit_price_minor - reference) if reference and line.unit_price_minor > reference else 0
        spend_line = SpendLine(
            tenant_id=invoice.tenant_id, invoice_line_id=line.id, invoice_ref=invoice.number, po_ref=po.number, supplier_id=invoice.supplier_id,
            category=material.category if material else po_line.material_group, material_group=po_line.material_group, plant=po_line.plant,
            company_code=invoice.company_code, cost_object=po_line.account_assignment_code, period=invoice.invoice_date.strftime("%Y-%m"),
            amount_minor=line_amount(qty, line.unit_price_minor), contracted=po_line.contract_line_id is not None, addressable=True,
            maverick_flags=flags, classification_confidence=Decimal("1.000") if material else Decimal("0.000"), created_by=invoice.created_by,
            description=po_line.description, po_line_id=po_line.id, price_variance_minor=variance, source="PLATFORM",
        )
        session.add(spend_line)
        spend.after_spend_line(session, spend_line)


def spend_cube(session: Session, dimensions: list[str]) -> dict:
    allowed = {"category", "supplier", "plant", "company_code", "period", "material_group", "cost_object"}
    unknown = [d for d in dimensions if d and d not in allowed]
    if unknown:
        raise Problem(400, "INVALID_DIMENSION", f"Unknown spend dimension(s): {', '.join(unknown)}. Use {', '.join(sorted(allowed))}")
    dims = [d for d in dimensions if d in allowed] or ["category"]
    columns = [SpendLine.supplier_id if d == "supplier" else getattr(SpendLine, d) for d in dims]
    contracted_amount = func.sum(case((SpendLine.contracted.is_(True), SpendLine.amount_minor), else_=0))
    rows = session.execute(select(*columns, func.sum(SpendLine.amount_minor), func.count(), contracted_amount)
                           .group_by(*columns)).all()
    total = sum(r[len(dims)] for r in rows) or 0
    suppliers = {s.id: s.code for s in session.execute(select(Supplier)).scalars()}
    out = []
    for r in rows:
        key = {d: (suppliers.get(r[i]) if d == "supplier" else r[i]) for i, d in enumerate(dims)}
        amount, count, contracted = r[len(dims)], r[len(dims) + 1], r[len(dims) + 2] or 0
        out.append({**key, "spendMinor": amount, "lines": count,
                    "contractCoveragePct": str((Decimal(contracted) * 100 / amount).quantize(Decimal("0.1"))) if amount else "0"})
    maverick = session.execute(select(func.sum(SpendLine.amount_minor)).where(func.jsonb_array_length(SpendLine.maverick_flags) > 0)).scalar() or 0
    contracted_total = session.execute(select(func.sum(SpendLine.amount_minor)).where(SpendLine.contracted.is_(True))).scalar() or 0
    return {"dimensions": dims, "totalMinor": total, "contractedPct": str((Decimal(contracted_total) * 100 / total).quantize(Decimal("0.1"))) if total else "0",
            "maverickPct": str((Decimal(maverick) * 100 / total).quantize(Decimal("0.1"))) if total else "0", "rows": out}


# ---------------------------------------------------------------- SAV-01 manual initiatives and baseline methods (blueprint §26)
BASELINE_METHODS = ("LAST_PRICE", "WAVG_12M", "STANDARD", "SHOULD_COST")


def baseline_price(session: Session, method: str, material: Optional[Material], given_minor: Optional[int] = None) -> tuple[int, str]:
    """Fixed per initiative at creation. Returns (price, how it was derived)."""
    from datetime import timedelta
    from app.pic.models import InfoRecord
    if method == "SHOULD_COST":
        if not given_minor:
            raise Problem(422, "BASELINE_REQUIRED", "A should-cost baseline needs the should-cost price")
        return given_minor, "should-cost model supplied by the category manager"
    if material is None:
        if given_minor:
            return given_minor, "baseline supplied (no material master)"
        raise Problem(422, "MATERIAL_REQUIRED", f"{method} needs a material or an explicit baseline price")
    if method == "STANDARD":
        if not material.standard_price_minor:
            raise Problem(422, "NO_STANDARD_PRICE", f"{material.number} has no standard price")
        return material.standard_price_minor, f"standard price of {material.number}"
    if method == "LAST_PRICE":
        last = session.execute(select(PoLine.unit_price_minor, PurchaseOrder.number).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id)
                               .where(PoLine.material_id == material.id).order_by(PurchaseOrder.created_at.desc())).first()
        if last:
            return last[0], f"last price paid on {last[1]}"
        info = session.execute(select(InfoRecord).where(InfoRecord.material_id == material.id).order_by(InfoRecord.last_price_minor)).scalars().first()
        if info:
            return info.last_price_minor, "purchasing info record"
        raise Problem(422, "NO_PRICE_HISTORY", f"{material.number} has no purchase history; use STANDARD or SHOULD_COST")
    since = clock.now() - timedelta(days=365)
    rows = session.execute(select(InvoiceLine.qty, InvoiceLine.unit_price_minor).join(PoLine, PoLine.id == InvoiceLine.po_line_id)
                           .where(PoLine.material_id == material.id, InvoiceLine.created_at >= since)).all()
    qty = sum((q for q, _ in rows), Decimal(0))
    if not qty:
        raise Problem(422, "NO_PRICE_HISTORY", f"{material.number} has no invoiced quantity in the last 12 months")
    wavg = int((sum((q * p for q, p in rows), Decimal(0)) / qty).quantize(Decimal("1"), ROUND_HALF_UP))
    return wavg, f"weighted average of {len(rows)} invoice lines in the last 12 months"


def create_initiative(session: Session, *, title: str, category: str, baseline_method: str, annual_volume: Decimal,
                      material_number: Optional[str] = None, baseline_price_minor: Optional[int] = None) -> SavingsInitiative:
    p = principal(session)
    if baseline_method not in BASELINE_METHODS:
        raise Problem(422, "INVALID_BASELINE", f"Use one of {', '.join(BASELINE_METHODS)}")
    material = None
    if material_number:
        material = session.execute(select(Material).where(Material.number == material_number)).scalar_one_or_none()
        if material is None:
            raise Problem(404, "NOT_FOUND", f"Material {material_number} not found")
    price, derivation = baseline_price(session, baseline_method, material, baseline_price_minor)
    initiative = SavingsInitiative(tenant_id=p.tenant_id, number=next_number(session, "SAVINGS"), title=title, category=category,
                                   material_id=material.id if material else None, owner_id=p.user_id, stage="IDENTIFIED",
                                   baseline_method=baseline_method, baseline_price_minor=price, annual_volume=D(annual_volume), created_by=p.user_id)
    session.add(initiative)
    session.flush()
    sod.record(session, "SAVINGS_INITIATE", {"initiative_id": initiative.id})
    audit.record(session, "SAVINGS_INITIATIVE", initiative.id, "IDENTIFIED", object_ref=initiative.number,
                 after={"baselineMethod": baseline_method, "baselineMinor": price, "derivation": derivation, "annualVolume": str(annual_volume)})
    return initiative


def negotiate(session: Session, initiative: SavingsInitiative, new_price_minor: int, supplier_code: str, evidence: str) -> SavingsInitiative:
    """Record a negotiated price outside a sourcing event (e.g. a renegotiation); negotiated savings never count toward budget."""
    if initiative.owner_id != principal(session).user_id:
        raise Problem(403, "FORBIDDEN", "Only the initiative owner records the negotiated price")
    supplier = session.execute(select(Supplier).where(Supplier.code == supplier_code)).scalar_one_or_none()
    if supplier is None:
        raise Problem(404, "NOT_FOUND", f"Supplier {supplier_code} not found")
    amount = int(((Decimal(initiative.baseline_price_minor) - new_price_minor) * initiative.annual_volume).quantize(Decimal("1"), ROUND_HALF_UP))
    initiative.new_price_minor = new_price_minor
    initiative.supplier_prices = {**(initiative.supplier_prices or {}), str(supplier.id): new_price_minor}
    _ledger(session, initiative, "NEGOTIATED", amount, False,
            f"({initiative.baseline_price_minor/100:.2f} − {new_price_minor/100:.2f}) × {initiative.annual_volume} /yr", "NEGOTIATION", evidence[:60])
    SM.apply(session, initiative, "negotiate", extra_after={"negotiatedMinor": amount, "supplier": supplier.code, "evidence": evidence})
    return initiative


def lose(session: Session, initiative: SavingsInitiative, reason: str) -> SavingsInitiative:
    if not reason:
        raise Problem(422, "REASON_REQUIRED", "Say why the initiative was lost")
    SM.apply(session, initiative, "lose", reason=reason)
    return initiative
