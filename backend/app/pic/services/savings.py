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
from app.pic.services import spend, spend_cube as cube_engine
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
    # An award above the baseline is a cost increase, not a negative saving: the ledger records 0 negotiated and the audit trail the increase.
    booked = max(amount, 0)
    _ledger(session, initiative, "NEGOTIATED", booked, False,
            f"({initiative.baseline_price_minor/100:.2f} − {weighted/100:.2f}) × {volume} /yr" + (" (cost increase: not booked as a saving)" if amount < 0 else "")
            + f" [baseline method {data.get('baselineMethod') or initiative.baseline_method}]", "SOURCING_EVENT", event.object_ref)
    SM.apply(session, initiative, "negotiate", extra_after={"negotiatedMinor": booked, "baselineMethod": data.get("baselineMethod") or initiative.baseline_method,
                                                            **({"costIncreaseMinor": -amount} if amount < 0 else {})})


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
    from app.pic.services import payables
    invoice = session.get(Invoice, uuid.UUID(event.payload["invoiceId"]))
    # Quantity credit notes reduce the quantity realised; a value (price-difference) credit note leaves the quantity and lowers the
    # price actually paid, so the realised saving is measured on the net value (same netting as the match, payables._credited_*).
    credited = payables._credited_qty(session, invoice)
    value_credited = payables._credited_value(session, invoice)
    booked = []
    for line in session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)).scalars():
        po_line = session.get(PoLine, line.po_line_id)
        if po_line.material_id is None:
            continue
        initiative = session.execute(select(SavingsInitiative).where(SavingsInitiative.material_id == po_line.material_id,
                                                                     SavingsInitiative.stage.in_(("NEGOTIATED", "CONTRACTED", "REALISING", "VALIDATED")))
                                     .order_by(SavingsInitiative.created_at).limit(1)).scalar_one_or_none()
        if initiative is None or str(invoice.supplier_id) not in (initiative.supplier_prices or {}):
            continue
        qty = line.qty - credited.get(line.line_no, Decimal(0))
        paid_value = line_amount(qty, line.unit_price_minor) - value_credited.get(line.line_no, 0)
        amount = int((Decimal(initiative.baseline_price_minor) * qty - Decimal(paid_value)).quantize(Decimal("1"), ROUND_HALF_UP))
        entry = _ledger(session, initiative, "REALISED", amount, True,
                        f"({initiative.baseline_price_minor/100:.2f} − {line.unit_price_minor/100:.2f}) × {qty} invoiced", "INVOICE",
                        f"{invoice.number}/{line.line_no}")
        if entry:
            booked.append(entry)
            if initiative.stage in ("NEGOTIATED", "CONTRACTED"):
                SM.apply(session, initiative, "realise", extra_after={"firstRealisedFrom": invoice.number})
            # The ledger entry above is bookkeeping from the posted invoice; the agent's run (its attribution) needs the guard.
            if agents.permit(session, "SAVINGS_VALIDATION", object_type="SAVINGS_INITIATIVE", object_id=initiative.id,
                             object_ref=initiative.number, required_level="L3", sod_action="SAVINGS_VALIDATE",
                             sod_refs={"initiative_id": initiative.id}):
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
# The invoice.posted / credit_note.received / debit_note.posted consumers that write the spend lines live in services/spend_feed.py
# (a credit note is a negative line in the period of the note, a debit note a positive one; see its docstring).


def spend_cube(session: Session, dimensions: list[str]) -> dict:
    """GET /v1/spend/cube?dims=...: the spend cube grouped by the given dimensions (see ``spend_cube.cube`` for filters and measures).
    Served from the cube summary tables, so it stays fast at 50 M spend lines."""
    return cube_engine.cube(session, dimensions)


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


# ---------------------------------------------------------------- SPD-08 pipeline tracker and M11-C4 savings P&L
STAGES = ("IDENTIFIED", "NEGOTIATED", "CONTRACTED", "REALISING", "VALIDATED", "LOST")


def _owner_names(session: Session) -> dict:
    from app.pic.models import AppUser
    return {u.id: u.full_name for u in session.execute(select(AppUser)).scalars()}


def _ledger_totals(session: Session, since=None, until=None) -> dict:
    """initiative id -> {type: amount} (optionally for a posting-date range)."""
    query = select(SavingsLedgerEntry.initiative_id, SavingsLedgerEntry.type, func.sum(SavingsLedgerEntry.amount_minor)).group_by(
        SavingsLedgerEntry.initiative_id, SavingsLedgerEntry.type)
    if since:
        query = query.where(SavingsLedgerEntry.posting_date >= since)
    if until:
        query = query.where(SavingsLedgerEntry.posting_date <= until)
    out: dict = {}
    for initiative_id, type_, amount in session.execute(query):
        out.setdefault(initiative_id, {})[type_] = int(amount)
    return out


def _pct1(num, den) -> Optional[str]:
    return str((Decimal(num) * 100 / den).quantize(Decimal("0.1"))) if den else None


def pipeline(session: Session, *, stage: Optional[str] = None, category: Optional[str] = None, owner: Optional[uuid.UUID] = None,
             created_from=None, created_to=None, min_forecast_minor: int = 0) -> dict:
    """SPD-08: forecast vs realised savings and cost avoidance by initiative and stage, with filters. Forecast is the negotiated
    annual saving once there is one, else the sourcing event's savings target on baseline x annual volume (basis shown)."""
    if stage and stage.upper() not in STAGES:
        raise Problem(422, "INVALID_STAGE", f"Use one of {', '.join(STAGES)}")
    query = select(SavingsInitiative).order_by(SavingsInitiative.number)
    if stage:
        query = query.where(SavingsInitiative.stage == stage.upper())
    if category:
        query = query.where(SavingsInitiative.category == category)
    if owner:
        query = query.where(SavingsInitiative.owner_id == owner)
    if created_from:
        query = query.where(func.date(SavingsInitiative.created_at) >= created_from)
    if created_to:
        query = query.where(func.date(SavingsInitiative.created_at) <= created_to)
    initiatives = session.execute(query).scalars().all()
    ledger = _ledger_totals(session)
    targets = {e.id: e.savings_target_pct for e in session.execute(select(SourcingEvent)).scalars()}
    owners = _owner_names(session)
    items = []
    for i in initiatives:
        t = ledger.get(i.id, {})
        negotiated, avoidance, realised = t.get("NEGOTIATED", 0), t.get("AVOIDANCE", 0), t.get("REALISED", 0)
        target_pct = targets.get(i.source_event_id)
        estimate = int(Decimal(i.baseline_price_minor) * (i.annual_volume or 0) * Decimal(target_pct) / 100) if target_pct and i.annual_volume else 0
        forecast, basis = (negotiated, "NEGOTIATED") if negotiated else ((estimate, "TARGET") if estimate and i.stage != "LOST" else (0, "NONE"))
        if forecast < min_forecast_minor:
            continue
        items.append({"id": str(i.id), "number": i.number, "title": i.title, "category": i.category, "stage": i.stage, "owner": owners.get(i.owner_id),
                      "ownerId": str(i.owner_id), "baselineMethod": i.baseline_method, "forecastMinor": forecast, "forecastBasis": basis,
                      "negotiatedMinor": negotiated, "avoidanceMinor": avoidance, "realisedMinor": realised,
                      "realisationPct": _pct1(realised, negotiated), "gapMinor": max(0, forecast - realised) if i.stage != "LOST" else 0,
                      "validated": i.stage == "VALIDATED", "createdAt": i.created_at.isoformat()})
    stages = []
    for name in STAGES:
        group = [x for x in items if x["stage"] == name]
        negotiated, realised = sum(x["negotiatedMinor"] for x in group), sum(x["realisedMinor"] for x in group)
        stages.append({"stage": name, "count": len(group), "forecastMinor": sum(x["forecastMinor"] for x in group), "negotiatedMinor": negotiated,
                       "avoidanceMinor": sum(x["avoidanceMinor"] for x in group), "realisedMinor": realised, "realisationPct": _pct1(realised, negotiated)})
    live = [x for x in items if x["stage"] != "LOST"]
    reached = {name: sum(1 for x in live if STAGES.index(x["stage"]) >= STAGES.index(name)) for name in STAGES[:-1]}
    totals = {"initiatives": len(items), "forecastMinor": sum(x["forecastMinor"] for x in live), "negotiatedMinor": sum(x["negotiatedMinor"] for x in live),
              "avoidanceMinor": sum(x["avoidanceMinor"] for x in live), "realisedMinor": sum(x["realisedMinor"] for x in live),
              "lostMinor": sum(x["forecastMinor"] for x in items if x["stage"] == "LOST")}
    totals["realisationPct"] = _pct1(totals["realisedMinor"], totals["negotiatedMinor"])
    return {"filters": {k: v for k, v in {"stage": stage, "category": category, "owner": str(owner) if owner else None,
                                          "createdFrom": created_from, "createdTo": created_to}.items() if v},
            "stages": stages, "funnel": reached, "initiatives": items, "totals": totals,
            "categories": sorted({x["category"] for x in items}),
            "owners": [{"id": o[0], "name": o[1]} for o in sorted({(x["ownerId"], x["owner"]) for x in items}, key=lambda o: o[1] or "")]}


def fiscal_year_bounds(fiscal_year: str):
    from datetime import date
    start = int(fiscal_year[:4])
    return date(start, 4, 1), date(start + 1, 3, 31)


def pnl(session: Session, fiscal_year: Optional[str] = None) -> dict:
    """M11-C4: the savings P&L and budget impact for a fiscal year. Only REALISED entries of initiatives that finance has
    VALIDATED reduce the budget; realised-but-unvalidated savings wait in the validation queue; negotiated savings and cost
    avoidance are reported but never counted."""
    from datetime import date
    from app.pic.models import CategoryPlan
    fiscal_year = fiscal_year or clock.fiscal_year(clock.today())
    try:
        start, end = fiscal_year_bounds(fiscal_year)
    except ValueError:
        raise Problem(422, "INVALID_FISCAL_YEAR", "fiscal_year looks like 2026-27")
    initiatives = {i.id: i for i in session.execute(select(SavingsInitiative)).scalars()}
    entries = session.execute(select(SavingsLedgerEntry).where(SavingsLedgerEntry.posting_date >= start, SavingsLedgerEntry.posting_date <= end)
                              .order_by(SavingsLedgerEntry.posting_date)).scalars().all()
    months: dict = {}
    cursor = start
    for _ in range(12):
        months[cursor.strftime("%Y-%m")] = {"period": cursor.strftime("%Y-%m"), "realisedMinor": 0, "validatedMinor": 0, "pendingValidationMinor": 0,
                                           "negotiatedMinor": 0, "avoidanceMinor": 0}
        cursor = date(cursor.year + (cursor.month // 12), cursor.month % 12 + 1, 1)
    categories: dict = {}
    for e in entries:
        i = initiatives.get(e.initiative_id)
        if i is None or i.stage == "LOST":
            continue
        month = months[e.posting_date.strftime("%Y-%m")]
        cat = categories.setdefault(i.category, {"category": i.category, "realisedMinor": 0, "validatedMinor": 0, "pendingValidationMinor": 0,
                                                 "negotiatedMinor": 0, "avoidanceMinor": 0})
        if e.type == "REALISED" and e.counts_toward_budget:
            key = "validatedMinor" if i.stage == "VALIDATED" else "pendingValidationMinor"
            for bucket in (month, cat):
                bucket["realisedMinor"] += e.amount_minor
                bucket[key] += e.amount_minor
        elif e.type == "NEGOTIATED":
            month["negotiatedMinor"] += e.amount_minor
            cat["negotiatedMinor"] += e.amount_minor
        elif e.type == "AVOIDANCE":
            month["avoidanceMinor"] += e.amount_minor
            cat["avoidanceMinor"] += e.amount_minor
    plans = {p.category: p for p in session.execute(select(CategoryPlan).where(CategoryPlan.fiscal_year == fiscal_year)).scalars()}
    for name, cat in categories.items():
        plan = plans.get(name)
        cat["planBudgetMinor"] = plan.budget_minor if plan else None
        cat["planTargetMinor"] = plan.savings_target_minor if plan else None
        cat["attainmentPct"] = _pct1(cat["validatedMinor"], plan.savings_target_minor) if plan else None
    ordered, running = [months[k] for k in sorted(months)], 0
    for m in ordered:
        running += m["validatedMinor"]
        m["cumulativeValidatedMinor"] = running
    ledger = _ledger_totals(session, start, end)
    owners = _owner_names(session)
    me = session.info["principal"].user_id if session.info.get("principal") else None
    queue = [{"id": str(i.id), "number": i.number, "title": i.title, "category": i.category, "stage": i.stage,
              "realisedMinor": ledger.get(i.id, {}).get("REALISED", 0), "owner": owners.get(i.owner_id),
              "canValidate": i.stage == "REALISING" and i.owner_id != me}
             for i in initiatives.values() if i.stage in ("NEGOTIATED", "CONTRACTED", "REALISING") and ledger.get(i.id, {}).get("REALISED", 0) > 0]
    totals = {k: sum(m[k] for m in ordered) for k in ("realisedMinor", "validatedMinor", "pendingValidationMinor", "negotiatedMinor", "avoidanceMinor")}
    target = sum((p.savings_target_minor or 0) for p in plans.values())
    return {"fiscalYear": fiscal_year, "from": start.isoformat(), "to": end.isoformat(), "months": ordered,
            "categories": sorted(categories.values(), key=lambda c: -c["realisedMinor"]),
            "totals": {**totals, "budgetImpactMinor": totals["validatedMinor"], "planTargetMinor": target or None,
                       "attainmentPct": _pct1(totals["validatedMinor"], target)},
            "validationQueue": sorted(queue, key=lambda q: -q["realisedMinor"]),
            "rule": "Budget impact = REALISED savings of VALIDATED initiatives (SOD-07: validated by finance, never by the initiative owner); "
                    "negotiated savings and cost avoidance never count toward budget."}
