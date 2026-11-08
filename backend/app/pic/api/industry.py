"""Industry-template controls (blueprint §23): planning and Kanban, self-billing, advances and bank guarantees, licences, accessorial
charges and index feed, cold chain and par levels, purchasing cards, industry KPIs. Every control answers 409 CONTROL_NOT_ENABLED for
a tenant whose template does not carry its rule set; ``GET /v1/industry/controls`` tells the frontend which ones are on."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Callable, Optional

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.pic import views
from app.pic.api.deps import idempotency_key, idempotent, uow
from app.pic.api.pagination import Page, paginate
from app.pic.db import current_tenant
from app.pic.models import (
    AccessorialCharge, AccessorialRate, AdvancePayment, BankGuarantee, ColdChainReading, ColdChainSpec, Contract, FreightMovement, IndexValue,
    KanbanCard, LicenceEntitlement, Material, MrpRun, PCard, PCardStatement, ParLevel, PlannedOrder, PlanningParameter, PurchaseOrder, Tenant,
)
from app.pic.platform.auth import READ, Principal, require, require_any
from app.pic.platform.core import check_if_match, etag
from app.pic.platform.errors import Problem, not_found
from app.pic.platform.serialize import jsonable, row, rows
from app.pic.services import (
    ind_common, ind_construction, ind_general, ind_healthcare, ind_it, ind_kpis, ind_logistics, ind_manufacturing,
)
from app.pic.services.common import by_ref, material_by_number

router = APIRouter(prefix="/v1")
IfMatch = Header(default=None, alias="If-Match")

# Rule sets that switch the industry controls on (the template carries them).
CONTROLS = {
    "selfBilling": ("SELF-BILLING", "Self-billing (ERS) on scheduling agreements"), "kanban": ("KANBAN", "Kanban replenishment"),
    "advancePayment": ("ADVANCE-PAYMENT", "Advance payment and recovery"), "bankGuarantee": ("PERFORMANCE-GUARANTEE", "Bank guarantee tracking"),
    "licences": ("LICENCE-UTILISATION", "Licence utilisation"), "accessorials": ("FREIGHT-AUDIT", "Freight audit and accessorial charges"),
    "coldChain": ("COLD-CHAIN", "Cold-chain tracking"), "parLevels": ("PAR-LEVEL", "Par-level planning"), "pcards": ("PCARD", "Purchasing cards"),
    "clinicalSignOff": ("AWARD-APPROVAL", "Clinical sign-off on awards"),
}


def _post(p: Principal, scope: str, key: Optional[str], body, fn: Callable, status: int = 201):
    """One tenant transaction, idempotent on the Idempotency-Key (a replay returns the stored response)."""
    with uow(p) as s:
        idem = idempotent(s, scope, key, body)
        if idem.replay:
            return idem.replay
        return idem.store(fn(s), status)


def _tagged(response: Response, doc) -> None:
    response.headers["ETag"] = etag(doc)


@router.get("/industry/controls", tags=["Industry"])
def controls(p: Principal = Depends(require(READ))):
    """Which industry controls are enabled for this tenant (rule set present and not switched off)."""
    with uow(p) as s:
        tenant = s.get(Tenant, current_tenant(s))
        out = {}
        for name, (key, title) in CONTROLS.items():
            rule = ind_common.rule_or_none(s, key)
            enabled = rule is not None and rule.body.get("enabled") is not False
            if name == "clinicalSignOff":
                enabled = rule is not None and bool(rule.body.get("clinicalSignOff"))
            out[name] = {"enabled": enabled, "rule": rule.ref if rule else None, "title": title}
        return {"template": tenant.industry_template, "controls": out}


@router.get("/industry/kpis", tags=["Industry"])
def industry_kpis(period: Optional[str] = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), plant: Optional[str] = None, all: bool = False,
                  p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return ind_kpis.industry_kpis(s, period, plant, include_other_templates=all)


# ---------------------------------------------------------------- MRP detail reads (paged) and planning parameters
@router.get("/mrp/runs/{ref}/planned-orders", tags=["F1 MRP"])
def mrp_planned_orders(ref: str, page: Page = Depends(), status: Optional[str] = None, p: Principal = Depends(require(READ))):
    """Planned orders of a run, newest first, as cursor pages (a 50,000-material run has ~120,000)."""
    from app.pic.services import planning

    with uow(p) as s:
        run = by_ref(s, MrpRun, ref)
        planning.ensure_readable(s, run.plant, "MRP run", ref)  # SEC-AZ: plant scope on planning reads
        query = select(PlannedOrder).where(PlannedOrder.mrp_run_id == run.id)
        if status:
            query = query.where(PlannedOrder.status == status.upper())
        result = paginate(s, query, PlannedOrder, page)
        numbers = dict(s.execute(select(Material.id, Material.number).where(Material.id.in_([uuid.UUID(i["material_id"]) for i in result["items"]]))).all()) \
            if result["items"] else {}
        for item in result["items"]:
            item["material"] = numbers.get(uuid.UUID(item["material_id"]))
        result["run"] = run.number
        return result


@router.get("/mrp/runs/{ref}/results", tags=["F1 MRP"])
def mrp_results(ref: str, offset: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=500), p: Principal = Depends(require(READ))):
    """The per-material netting trace of a run, in pages."""
    from app.pic.services import planning

    with uow(p) as s:
        run = by_ref(s, MrpRun, ref)
        planning.ensure_readable(s, run.plant, "MRP run", ref)
        results = run.results or []
        return {"run": run.number, "total": len(results), "items": results[offset:offset + limit],
                "nextOffset": offset + limit if offset + limit < len(results) else None}


class ParameterIn(BaseModel):
    material: str
    plant: str
    reorderPoint: Decimal = Field(ge=0)
    maxStock: Optional[Decimal] = Field(default=None, ge=0)
    note: Optional[str] = Field(default=None, max_length=300)


@router.put("/planning/parameters", tags=["F1 MRP"])
def put_parameters(body: ParameterIn, p: Principal = Depends(require("mrp:plan")), key: Optional[str] = Depends(idempotency_key)):
    """Reorder point and maximum stock of a reorder-point (VB) material at a plant."""
    def run(s):
        r = ind_manufacturing.set_parameters(s, material=body.material, plant=body.plant, reorder_point=body.reorderPoint, max_stock=body.maxStock, note=body.note)
        return row(r, extra={"material": body.material})
    return _post(p, "PUT /v1/planning/parameters", key, body, run, 200)


@router.get("/planning/parameters", tags=["F1 MRP"])
def list_parameters(plant: Optional[str] = None, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        query = select(PlanningParameter, Material.number).join(Material, Material.id == PlanningParameter.material_id).order_by(Material.number)
        if plant:
            query = query.where(PlanningParameter.plant == plant)
        return [row(r, extra={"material": number}) for r, number in s.execute(query).all()]


class MrpTypeIn(BaseModel):
    mrpType: str = Field(pattern="^(PD|PW|PM|VB|KB|ND)$")
    reason: Optional[str] = Field(default=None, max_length=1000)


@router.put("/materials/{number}/mrp-type", status_code=202, tags=["F1 MRP"])
def put_mrp_type(number: str, body: MrpTypeIn, p: Principal = Depends(require("mrp:plan")), key: Optional[str] = Depends(idempotency_key)):
    """Ask for a planning mode: PD daily MRP, PW weekly buckets, PM monthly buckets, VB reorder point, KB Kanban, ND none. The MRP type is
    master data (M03 governance): the call raises a material change request that the PLANT data steward approves; on approval the
    material gets a new version and the ERP material master is updated. 202 with the change request; ``mrpType`` is the type in force."""
    def run(s):
        request = ind_manufacturing.request_mrp_type(s, number, body.mrpType, body.reason)
        material = s.get(Material, request.material_id)
        return {"material": number, "mrpType": material.mrp_type, "requestedMrpType": body.mrpType, "changeRequest": request.number,
                "status": request.status}
    return _post(p, f"PUT /v1/materials/{number}/mrp-type", key, body, run, 202)


# ---------------------------------------------------------------- 36 Kanban
class CardIn(BaseModel):
    material: str
    plant: str
    binQty: Decimal = Field(gt=0)
    storageLocation: str = Field(default="0001", max_length=10)
    supplier: Optional[str] = None


class NoteIn(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=300)


@router.post("/kanban/cards", status_code=201, tags=["Kanban"])
def create_card(body: CardIn, p: Principal = Depends(require("mrp:plan")), key: Optional[str] = Depends(idempotency_key)):
    return _post(p, "POST /v1/kanban/cards", key, body, lambda s: ind_manufacturing.card_view(s, ind_manufacturing.create_card(
        s, material=body.material, plant=body.plant, bin_qty=body.binQty, storage_location=body.storageLocation, supplier=body.supplier)))


@router.get("/kanban/cards", tags=["Kanban"])
def list_cards(plant: Optional[str] = None, status: Optional[str] = None, material: Optional[str] = None, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        query = select(KanbanCard).order_by(KanbanCard.number)
        if plant:
            query = query.where(KanbanCard.plant == plant)
        if status:
            query = query.where(KanbanCard.status == status.upper())
        if material:
            query = query.where(KanbanCard.material_id == material_by_number(s, material).id)
        return [ind_manufacturing.card_view(s, c) for c in s.execute(query).scalars()]


def _card_action(ref: str, p: Principal, key: Optional[str], if_match: Optional[str], action: str, body, fn: Callable):
    def run(s):
        card = by_ref(s, KanbanCard, ref, lock=True)
        check_if_match(card, if_match)
        fn(s, card)
        return ind_manufacturing.card_view(s, card)
    return _post(p, f"POST /v1/kanban/cards/{ref}/{action}", key, body, run, 200)


@router.post("/kanban/cards/{ref}/signal", tags=["Kanban"])
def signal_card(ref: str, p: Principal = Depends(require("mrp:plan")), key: Optional[str] = Depends(idempotency_key), if_match: Optional[str] = IfMatch):
    """Empty bin: the card signals replenishment and a requisition is raised."""
    return _card_action(ref, p, key, if_match, "signal", {}, lambda s, c: ind_manufacturing.signal_empty(s, c))


@router.post("/kanban/cards/{ref}/replenish", tags=["Kanban"])
def replenish_card(ref: str, p: Principal = Depends(require("mrp:plan")), key: Optional[str] = Depends(idempotency_key),
                   if_match: Optional[str] = IfMatch):
    """Raise the replenishment requisition of an EMPTY card (rule KANBAN autoRequisition false, or a signal nobody replenished)."""
    return _card_action(ref, p, key, if_match, "replenish", {}, lambda s, c: ind_manufacturing.replenish(s, c))


@router.post("/kanban/cards/{ref}/refill", tags=["Kanban"])
def refill_card(ref: str, body: NoteIn, p: Principal = Depends(require("mrp:plan")), key: Optional[str] = Depends(idempotency_key),
                if_match: Optional[str] = IfMatch):
    return _card_action(ref, p, key, if_match, "refill", body, lambda s, c: ind_manufacturing.refill(s, c, body.reason))


@router.post("/kanban/cards/{ref}/suspend", tags=["Kanban"])
def suspend_card(ref: str, body: NoteIn, p: Principal = Depends(require("mrp:plan")), key: Optional[str] = Depends(idempotency_key),
                 if_match: Optional[str] = IfMatch):
    return _card_action(ref, p, key, if_match, "suspend", body, lambda s, c: ind_manufacturing.set_suspended(s, c, True, body.reason or ""))


@router.post("/kanban/cards/{ref}/resume", tags=["Kanban"])
def resume_card(ref: str, body: NoteIn, p: Principal = Depends(require("mrp:plan")), key: Optional[str] = Depends(idempotency_key),
                if_match: Optional[str] = IfMatch):
    return _card_action(ref, p, key, if_match, "resume", body, lambda s, c: ind_manufacturing.set_suspended(s, c, False, body.reason or ""))


# ---------------------------------------------------------------- 35 self-billing
class SettleIn(BaseModel):
    supplier: str
    periodTo: date
    companyCode: str = Field(default="1000", max_length=10)
    reference: Optional[str] = Field(default=None, max_length=60)


@router.get("/self-billing/open", tags=["Self-billing"])
def self_billing_open(supplier: str, periodTo: date, companyCode: str = "1000", p: Principal = Depends(require_any("invoice:post", "payment:run", "invoice:approve"))):
    """Call-off deliveries that a settlement up to the date would bill."""
    with uow(p) as s:
        return ind_manufacturing.preview_self_billing(s, supplier=supplier, period_to=periodTo, company_code=companyCode)


@router.post("/self-billing/settlements", status_code=201, tags=["Self-billing"])
def settle(body: SettleIn, p: Principal = Depends(require_any("invoice:post", "payment:run")), key: Optional[str] = Depends(idempotency_key)):
    """Self-billing (ERS) document for the call-off deliveries of a supplier's scheduling agreements up to the period end."""
    return _post(p, "POST /v1/self-billing/settlements", key, body, lambda s: views.invoice(s, ind_manufacturing.settle_scheduling_agreement(
        s, supplier=body.supplier, period_to=body.periodTo, company_code=body.companyCode, reference=body.reference)))


# ---------------------------------------------------------------- 38 advance payments, 39 bank guarantees
class AdvanceIn(BaseModel):
    netMinor: int = Field(gt=0)
    reference: str = Field(min_length=2, max_length=60)
    reason: Optional[str] = Field(default=None, max_length=500)


@router.post("/purchase-orders/{ref}/advances", status_code=201, tags=["Construction"])
def request_advance(ref: str, body: AdvanceIn, p: Principal = Depends(require_any("contract:manage", "invoice:post")),
                    key: Optional[str] = Depends(idempotency_key)):
    return _post(p, f"POST /v1/purchase-orders/{ref}/advances", key, body, lambda s: ind_construction.advance_view(s, ind_construction.request_advance(
        s, by_ref(s, PurchaseOrder, ref, lock=True), net_minor=body.netMinor, reference=body.reference, reason=body.reason)))


@router.get("/purchase-orders/{ref}/advances", tags=["Construction"])
def po_advances(ref: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        po = by_ref(s, PurchaseOrder, ref)
        return [ind_construction.advance_view(s, a) for a in s.execute(select(AdvancePayment).where(AdvancePayment.po_id == po.id)
                                                                      .order_by(AdvancePayment.created_at)).scalars()]


@router.get("/advances", tags=["Construction"])
def list_advances(status: Optional[str] = None, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        query = select(AdvancePayment).order_by(AdvancePayment.created_at.desc())
        if status:
            query = query.where(AdvancePayment.status == status.upper())
        return [ind_construction.advance_view(s, a) for a in s.execute(query).scalars()]


@router.get("/advances/{ref}", tags=["Construction"])
def get_advance(ref: str, response: Response, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        advance = by_ref(s, AdvancePayment, ref)
        _tagged(response, advance)
        return ind_construction.advance_view(s, advance)


class GuaranteeIn(BaseModel):
    po: str
    kind: str = Field(pattern="^(PERFORMANCE|ADVANCE)$")
    bankName: str = Field(min_length=2, max_length=120)
    bankRef: str = Field(min_length=2, max_length=60)
    amountMinor: int = Field(gt=0)
    issueDate: date
    expiryDate: date


@router.post("/bank-guarantees", status_code=201, tags=["Construction"])
def record_guarantee(body: GuaranteeIn, p: Principal = Depends(require("contract:manage")), key: Optional[str] = Depends(idempotency_key)):
    return _post(p, "POST /v1/bank-guarantees", key, body, lambda s: ind_construction.guarantee_view(s, ind_construction.record_guarantee(
        s, by_ref(s, PurchaseOrder, body.po), kind=body.kind, bank_name=body.bankName, bank_ref=body.bankRef, amount_minor=body.amountMinor,
        issue_date=body.issueDate, expiry_date=body.expiryDate)))


@router.get("/bank-guarantees", tags=["Construction"])
def list_guarantees(status: Optional[str] = None, po: Optional[str] = None, expiringWithinDays: Optional[int] = Query(default=None, ge=0, le=730),
                    p: Principal = Depends(require(READ))):
    with uow(p) as s:
        query = select(BankGuarantee).order_by(BankGuarantee.expiry_date)
        if status:
            query = query.where(BankGuarantee.status == status.upper())
        if po:
            query = query.where(BankGuarantee.po_id == by_ref(s, PurchaseOrder, po).id)
        views_ = [ind_construction.guarantee_view(s, g) for g in s.execute(query).scalars()]
        if expiringWithinDays is not None:
            views_ = [v for v in views_ if v["status"] == "ACTIVE" and v["daysToExpiry"] <= expiringWithinDays]
        return views_


@router.get("/bank-guarantees/{ref}", tags=["Construction"])
def get_guarantee(ref: str, response: Response, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        guarantee = by_ref(s, BankGuarantee, ref)
        _tagged(response, guarantee)
        return ind_construction.guarantee_view(s, guarantee)


@router.post("/bank-guarantees/{ref}/verify", tags=["Construction"])
def verify_guarantee(ref: str, body: NoteIn, p: Principal = Depends(require("payment:run")), key: Optional[str] = Depends(idempotency_key),
                     if_match: Optional[str] = IfMatch):
    def run(s):
        guarantee = by_ref(s, BankGuarantee, ref, lock=True)
        check_if_match(guarantee, if_match)
        return ind_construction.guarantee_view(s, ind_construction.verify_guarantee(s, guarantee, body.reason))
    return _post(p, f"POST /v1/bank-guarantees/{ref}/verify", key, body, run, 200)


class ReleaseIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/bank-guarantees/{ref}/release", tags=["Construction"])
def release_guarantee(ref: str, body: ReleaseIn, p: Principal = Depends(require_any("payment:run", "contract:manage")),
                      key: Optional[str] = Depends(idempotency_key), if_match: Optional[str] = IfMatch):
    def run(s):
        guarantee = by_ref(s, BankGuarantee, ref, lock=True)
        check_if_match(guarantee, if_match)
        return ind_construction.guarantee_view(s, ind_construction.release_guarantee(s, guarantee, body.reason))
    return _post(p, f"POST /v1/bank-guarantees/{ref}/release", key, body, run, 200)


@router.get("/purchase-orders/{ref}/guarantee-status", tags=["Construction"])
def guarantee_status(ref: str, p: Principal = Depends(require(READ))):
    """Whether retention release and final payment of the order are blocked for want of a valid performance guarantee."""
    with uow(p) as s:
        po = by_ref(s, PurchaseOrder, ref)
        return {"po": po.number, "retentionPct": jsonable(po.retention_pct),
                "retentionRelease": ind_construction.guarantee_problem(s, po, "RETENTION_RELEASE"),
                "finalPayment": ind_construction.guarantee_problem(s, po, "FINAL_PAYMENT"),
                "guarantees": [ind_construction.guarantee_view(s, g) for g in s.execute(select(BankGuarantee).where(BankGuarantee.po_id == po.id)
                                                                                      .order_by(BankGuarantee.expiry_date)).scalars()]}


# ---------------------------------------------------------------- 40 licences
class LicenceIn(BaseModel):
    supplier: str
    product: str = Field(min_length=2, max_length=120)
    entitledQty: Decimal = Field(gt=0)
    unitPriceMinor: int = Field(ge=0)
    termStart: date
    termEnd: date
    metric: str = Field(default="USER", max_length=20)
    contract: Optional[str] = None


class UsageRow(BaseModel):
    licence: str
    asOf: date
    usedQty: Decimal = Field(ge=0)


class UsageIn(BaseModel):
    records: list[UsageRow] = Field(min_length=1, max_length=ind_it.MAX_IMPORT_ROWS)
    source: str = Field(default="IMPORT", pattern="^(IMPORT|API|MANUAL)$")


@router.post("/licences", status_code=201, tags=["IT services"])
def create_licence(body: LicenceIn, p: Principal = Depends(require_any("sourcing:manage", "contract:manage")), key: Optional[str] = Depends(idempotency_key)):
    return _post(p, "POST /v1/licences", key, body, lambda s: ind_it.licence_view(s, ind_it.create_entitlement(
        s, supplier=body.supplier, product=body.product, entitled_qty=body.entitledQty, unit_price_minor=body.unitPriceMinor, term_start=body.termStart,
        term_end=body.termEnd, metric=body.metric, contract=body.contract)))


@router.get("/licences", tags=["IT services"])
def list_licences(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return ind_it.summary(s)


@router.get("/licences/{ref}", tags=["IT services"])
def get_licence(ref: str, response: Response, p: Principal = Depends(require(READ))):
    from app.pic.models import LicenceUsage
    with uow(p) as s:
        entitlement = by_ref(s, LicenceEntitlement, ref)
        _tagged(response, entitlement)
        usage = s.execute(select(LicenceUsage).where(LicenceUsage.entitlement_id == entitlement.id).order_by(LicenceUsage.as_of.desc()).limit(24)).scalars().all()
        return {**ind_it.licence_view(s, entitlement), "usage": [{"asOf": u.as_of.isoformat(), "usedQty": jsonable(u.used_qty), "source": u.source} for u in usage]}


@router.post("/licences/usage", tags=["IT services"])
def import_usage(body: UsageIn, p: Principal = Depends(require_any("sourcing:manage", "contract:manage")), key: Optional[str] = Depends(idempotency_key)):
    """Usage records from the licence portal / SSO report; re-importing the same dates replaces them."""
    return _post(p, "POST /v1/licences/usage", key, body, lambda s: ind_it.import_usage(
        s, [{"licence": r.licence, "as_of": r.asOf, "used_qty": r.usedQty} for r in body.records], body.source), 200)


@router.post("/licences/{ref}/end", tags=["IT services"])
def end_licence(ref: str, body: ReleaseIn, p: Principal = Depends(require_any("sourcing:manage", "contract:manage")), key: Optional[str] = Depends(idempotency_key),
                if_match: Optional[str] = IfMatch):
    def run(s):
        entitlement = by_ref(s, LicenceEntitlement, ref, lock=True)
        check_if_match(entitlement, if_match)
        return ind_it.licence_view(s, ind_it.end_entitlement(s, entitlement, body.reason))
    return _post(p, f"POST /v1/licences/{ref}/end", key, body, run, 200)


# ---------------------------------------------------------------- 41 logistics
class RateIn(BaseModel):
    chargeType: str = Field(pattern="^(DETENTION|DEMURRAGE|LOADING|UNLOADING|WAITING)$")
    rateMinor: int = Field(ge=0)
    unit: str = Field(default="HOUR", pattern="^(HOUR|DAY|TRIP)$")
    freeUnits: Decimal = Field(default=Decimal(0), ge=0)
    supplier: Optional[str] = None
    lane: Optional[str] = Field(default=None, max_length=40)
    validFrom: Optional[date] = None
    validTo: Optional[date] = None


@router.post("/accessorial/rates", status_code=201, tags=["Logistics"])
def add_rate(body: RateIn, p: Principal = Depends(require("contract:manage")), key: Optional[str] = Depends(idempotency_key)):
    def run(s):
        rate = ind_logistics.add_rate(s, charge_type=body.chargeType, rate_minor=body.rateMinor, unit=body.unit, free_units=body.freeUnits,
                                      supplier=body.supplier, lane=body.lane, valid_from=body.validFrom, valid_to=body.validTo)
        return row(rate, extra={"supplier": body.supplier})
    return _post(p, "POST /v1/accessorial/rates", key, body, run)


@router.get("/accessorial/rates", tags=["Logistics"])
def list_rates(p: Principal = Depends(require(READ))):
    from app.pic.models import Supplier
    with uow(p) as s:
        codes = dict(s.execute(select(Supplier.id, Supplier.code)).all())
        return [row(r, extra={"supplier": codes.get(r.supplier_id)}) for r in s.execute(select(AccessorialRate).order_by(
            AccessorialRate.charge_type, AccessorialRate.valid_from.desc())).scalars()]


class ChargeIn(BaseModel):
    line: int = Field(gt=0)
    chargeType: str = Field(pattern="^(DETENTION|DEMURRAGE|LOADING|UNLOADING|WAITING)$")
    units: Decimal = Field(gt=0)
    occurredOn: date
    lane: Optional[str] = Field(default=None, max_length=40)
    podServiceEntry: Optional[str] = Field(default=None, max_length=30)
    note: Optional[str] = Field(default=None, max_length=300)


@router.post("/purchase-orders/{ref}/accessorial-charges", status_code=201, tags=["Logistics"])
def claim_charge(ref: str, body: ChargeIn, p: Principal = Depends(require_any("ses:create", "po:change", "contract:manage")),
                 key: Optional[str] = Depends(idempotency_key)):
    """Detention / demurrage / accessorial claim on a freight order's accessorial service line; becomes a service entry when valid."""
    return _post(p, f"POST /v1/purchase-orders/{ref}/accessorial-charges", key, body, lambda s: ind_logistics.charge_view(s, ind_logistics.claim_charge(
        s, by_ref(s, PurchaseOrder, ref), line=body.line, charge_type=body.chargeType, units=body.units, occurred_on=body.occurredOn, lane=body.lane,
        pod_ses=body.podServiceEntry, note=body.note)))


@router.get("/accessorial/charges", tags=["Logistics"])
def list_charges(po: Optional[str] = None, status: Optional[str] = None, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        query = select(AccessorialCharge).order_by(AccessorialCharge.number.desc())
        if po:
            query = query.where(AccessorialCharge.po_id == by_ref(s, PurchaseOrder, po).id)
        charges = [ind_logistics.charge_view(s, c) for c in s.execute(query).scalars()]
        return [c for c in charges if not status or c["status"] == status.upper()]


class MovementIn(BaseModel):
    line: int = Field(gt=0)
    reference: str = Field(min_length=2, max_length=60)
    distanceKm: Decimal = Field(gt=0)
    payloadTonnes: Decimal = Field(gt=0)
    movedOn: date
    lane: Optional[str] = Field(default=None, max_length=40)
    serviceEntry: Optional[str] = Field(default=None, max_length=30)


@router.post("/purchase-orders/{ref}/freight-movements", status_code=201, tags=["Logistics"])
def record_movement(ref: str, body: MovementIn, p: Principal = Depends(require_any("ses:create", "po:change", "contract:manage")),
                    key: Optional[str] = Depends(idempotency_key)):
    def run(s):
        movement = ind_logistics.record_movement(s, by_ref(s, PurchaseOrder, ref), line=body.line, reference=body.reference, distance_km=body.distanceKm,
                                                 payload_tonnes=body.payloadTonnes, moved_on=body.movedOn, lane=body.lane, ses=body.serviceEntry)
        return row(movement, extra={"po": ref})
    return _post(p, f"POST /v1/purchase-orders/{ref}/freight-movements", key, body, run)


class IndexRow(BaseModel):
    asOf: date
    value: Decimal = Field(gt=0)
    unit: Optional[str] = Field(default=None, max_length=20)


class IndexIn(BaseModel):
    values: list[IndexRow] = Field(min_length=1, max_length=ind_logistics.MAX_INDEX_ROWS)
    source: str = Field(default="API", pattern="^(IMPORT|API|MANUAL)$")
    sourceRef: Optional[str] = Field(default=None, max_length=80)


@router.put("/indices/{code}/values", tags=["Logistics"])
def put_index(code: str, body: IndexIn, p: Principal = Depends(require_any("contract:manage", "admin:integration")),
              key: Optional[str] = Depends(idempotency_key)):
    """Feed index values (fuel, aluminium, ...) from a published source; contract index resets read them."""
    return _post(p, f"PUT /v1/indices/{code}/values", key, body, lambda s: ind_logistics.put_index_values(
        s, code, [{"as_of": v.asOf, "value": v.value, "unit": v.unit} for v in body.values], body.source, body.sourceRef), 200)


@router.get("/indices/{code}", tags=["Logistics"])
def get_index(code: str, limit: int = Query(default=60, ge=1, le=500), p: Principal = Depends(require(READ))):
    with uow(p) as s:
        values = s.execute(select(IndexValue).where(IndexValue.index_code == code.upper()).order_by(IndexValue.as_of.desc()).limit(limit)).scalars().all()
        return {"index": code.upper(), "latest": jsonable(values[0].value) if values else None, "values": rows(values)}


class FeedResetIn(BaseModel):
    effectiveFrom: Optional[date] = None


@router.post("/contracts/{ref}/index-resets/from-feed", tags=["Logistics"])
def reset_from_feed(ref: str, body: FeedResetIn, p: Principal = Depends(require("contract:manage")), key: Optional[str] = Depends(idempotency_key)):
    """Index reset with the latest fed value on or before the effective date."""
    return _post(p, f"POST /v1/contracts/{ref}/index-resets/from-feed", key, body, lambda s: ind_logistics.reset_contract_from_feed(
        s, by_ref(s, Contract, ref, lock=True), body.effectiveFrom), 200)


# ---------------------------------------------------------------- 43 cold chain, 44 par levels, expiry
class SpecIn(BaseModel):
    minC: Decimal
    maxC: Decimal
    maxExcursionMinutes: Optional[int] = Field(default=None, ge=0, le=1440)
    label: Optional[str] = Field(default=None, max_length=40)


@router.put("/materials/{number}/cold-chain-spec", tags=["Cold chain"])
def put_spec(number: str, body: SpecIn, p: Principal = Depends(require_any("quality:decide", "mrp:plan")), key: Optional[str] = Depends(idempotency_key)):
    return _post(p, f"PUT /v1/materials/{number}/cold-chain-spec", key, body, lambda s: row(ind_healthcare.set_spec(
        s, material=number, min_c=body.minC, max_c=body.maxC, max_excursion_minutes=body.maxExcursionMinutes, label=body.label), extra={"material": number}), 200)


@router.get("/cold-chain/specs", tags=["Cold chain"])
def list_specs(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return [row(spec, extra={"material": number, "description": description}) for spec, number, description in s.execute(
            select(ColdChainSpec, Material.number, Material.description).join(Material, Material.id == ColdChainSpec.material_id).order_by(Material.number)).all()]


class ReadingPoint(BaseModel):
    at: datetime
    tempC: Decimal


class ReadingIn(BaseModel):
    objectType: str = Field(pattern="^(ASN|GOODS_RECEIPT)$")
    ref: str = Field(min_length=2, max_length=40)
    material: str
    loggerId: str = Field(min_length=2, max_length=40)
    readings: list[ReadingPoint] = Field(min_length=2, max_length=5000)
    batch: Optional[str] = Field(default=None, max_length=30)


@router.post("/cold-chain/readings", status_code=201, tags=["Cold chain"])
def record_readings(body: ReadingIn, p: Principal = Depends(require_any("gr:post", "quality:decide", "asn:create")), key: Optional[str] = Depends(idempotency_key)):
    """Temperature-logger trace for a material on an ASN or goods receipt; an excursion quarantines the stock and opens a quality task."""
    return _post(p, "POST /v1/cold-chain/readings", key, body, lambda s: ind_healthcare.reading_view(s, ind_healthcare.record_readings(
        s, object_type=body.objectType, ref=body.ref, material=body.material, logger_id=body.loggerId, batch=body.batch,
        readings=[{"at": r.at, "temp_c": r.tempC} for r in body.readings])))


@router.get("/cold-chain/readings", tags=["Cold chain"])
def list_readings(status: Optional[str] = None, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        query = select(ColdChainReading).order_by(ColdChainReading.created_at.desc())
        if status:
            query = query.where(ColdChainReading.status == status.upper())
        return [ind_healthcare.reading_view(s, r) for r in s.execute(query).scalars()]


class ParIn(BaseModel):
    plant: str
    storageLocation: str = Field(max_length=10)
    material: str
    parQty: Decimal = Field(gt=0)
    triggerQty: Decimal = Field(ge=0)


@router.put("/par-levels", tags=["Par levels"])
def put_par(body: ParIn, p: Principal = Depends(require("mrp:plan")), key: Optional[str] = Depends(idempotency_key)):
    return _post(p, "PUT /v1/par-levels", key, body, lambda s: row(ind_healthcare.set_par_level(
        s, plant=body.plant, storage_location=body.storageLocation, material=body.material, par_qty=body.parQty, trigger_qty=body.triggerQty),
        extra={"material": body.material}), 200)


@router.get("/par-levels", tags=["Par levels"])
def list_par(plant: Optional[str] = None, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        query = select(ParLevel, Material).join(Material, Material.id == ParLevel.material_id).order_by(ParLevel.plant, ParLevel.storage_location, Material.number)
        if plant:
            query = query.where(ParLevel.plant == plant)
        out = []
        for level, mat in s.execute(query).all():
            on_hand = ind_healthcare._on_hand(s, level)
            out.append(row(level, extra={"material": mat.number, "description": mat.description, "uom": mat.base_uom, "onHand": jsonable(on_hand),
                                          "onOrder": jsonable(ind_healthcare._on_order(s, level)), "belowTrigger": on_hand <= level.trigger_qty}))
        return out


class PlantIn(BaseModel):
    plant: Optional[str] = None


@router.post("/par-levels/sweep", tags=["Par levels"])
def sweep_par(body: PlantIn, p: Principal = Depends(require("mrp:plan")), key: Optional[str] = Depends(idempotency_key)):
    """Check every par level and raise replenishment requisitions up to par."""
    return _post(p, "POST /v1/par-levels/sweep", key, body, lambda s: ind_healthcare.sweep(s, body.plant), 200)


@router.get("/par-levels/vac-report", tags=["Par levels"])
def vac_report(plant: Optional[str] = None, days: int = Query(default=90, ge=7, le=365), p: Principal = Depends(require(READ))):
    """Value-analysis committee report: usage, days of supply, stock-out risk, expiring stock and the par level the usage supports."""
    with uow(p) as s:
        return ind_healthcare.vac_report(s, plant, days)


@router.get("/expiry/stock", tags=["Cold chain"])
def expired_stock(asOf: Optional[date] = None, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return [{"material": i["material"].number, "description": i["material"].description, "plant": i["stock"].plant, "storageLocation": i["stock"].storage_location,
                 "batch": i["stock"].batch, "qty": jsonable(i["stock"].qty), "expiry": i["expiry"].isoformat(), "valueMinor": i["valueMinor"]}
                for i in ind_healthcare.expired_stock(s, asOf)]


class WriteOffIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)
    asOf: Optional[date] = None


@router.post("/expiry/write-off", tags=["Cold chain"])
def write_off(body: WriteOffIn, p: Principal = Depends(require("quality:decide")), key: Optional[str] = Depends(idempotency_key)):
    """Write off own stock of batches that have expired (movement 551); the value feeds the expiry-write-off KPI."""
    return _post(p, "POST /v1/expiry/write-off", key, body, lambda s: ind_healthcare.write_off_expired(s, body.reason, body.asOf), 200)


# ---------------------------------------------------------------- 45 purchasing cards
class CardLimitsIn(BaseModel):
    perTxnLimitMinor: int = Field(gt=0)
    monthlyLimitMinor: int = Field(gt=0)


class PCardIn(CardLimitsIn):
    holderName: str = Field(min_length=2, max_length=120)
    holderEmail: Optional[str] = Field(default=None, max_length=200)
    issuer: str = Field(min_length=2, max_length=60)
    cardLast4: str = Field(pattern=r"^\d{4}$")
    blockedMccs: list[str] = Field(default_factory=list, max_length=100)
    allowedMccs: list[str] = Field(default_factory=list, max_length=100)
    costObject: Optional[str] = Field(default=None, max_length=60)
    validTo: Optional[date] = None


_PCARD_ROLES = ("payment:run", "admin:rules")


@router.post("/pcards", status_code=201, tags=["P-cards"])
def issue_card(body: PCardIn, p: Principal = Depends(require_any(*_PCARD_ROLES)), key: Optional[str] = Depends(idempotency_key)):
    return _post(p, "POST /v1/pcards", key, body, lambda s: ind_general.card_view(s, ind_general.issue_card(
        s, holder_name=body.holderName, issuer=body.issuer, card_last4=body.cardLast4, per_txn_limit_minor=body.perTxnLimitMinor,
        monthly_limit_minor=body.monthlyLimitMinor, holder_email=body.holderEmail, blocked_mccs=body.blockedMccs, allowed_mccs=body.allowedMccs,
        cost_object=body.costObject, valid_to=body.validTo)))


@router.get("/pcards", tags=["P-cards"])
def list_pcards(status: Optional[str] = None, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        query = select(PCard).order_by(PCard.number)
        if status:
            query = query.where(PCard.status == status.upper())
        return [ind_general.card_view(s, c) for c in s.execute(query).scalars()]


@router.get("/pcards/{ref}", tags=["P-cards"])
def get_pcard(ref: str, response: Response, p: Principal = Depends(require(READ))):
    from app.pic.models import PCardTransaction
    with uow(p) as s:
        card = by_ref(s, PCard, ref)
        _tagged(response, card)
        txns = s.execute(select(PCardTransaction).where(PCardTransaction.pcard_id == card.id).order_by(PCardTransaction.txn_date.desc()).limit(100)).scalars().all()
        return {**ind_general.card_view(s, card), "transactions": rows(txns)}


class LimitsChangeIn(CardLimitsIn):
    reason: str = Field(min_length=3, max_length=300)


@router.post("/pcards/{ref}/limits", tags=["P-cards"])
def change_limits(ref: str, body: LimitsChangeIn, p: Principal = Depends(require_any(*_PCARD_ROLES)), key: Optional[str] = Depends(idempotency_key),
                  if_match: Optional[str] = IfMatch):
    def run(s):
        card = by_ref(s, PCard, ref, lock=True)
        check_if_match(card, if_match)
        return ind_general.card_view(s, ind_general.change_limits(s, card, per_txn_limit_minor=body.perTxnLimitMinor, monthly_limit_minor=body.monthlyLimitMinor,
                                                                 reason=body.reason))
    return _post(p, f"POST /v1/pcards/{ref}/limits", key, body, run, 200)


class StatusIn(BaseModel):
    status: str = Field(pattern="^(ACTIVE|SUSPENDED|CLOSED)$")
    reason: str = Field(min_length=3, max_length=300)


@router.post("/pcards/{ref}/status", tags=["P-cards"])
def card_status(ref: str, body: StatusIn, p: Principal = Depends(require_any(*_PCARD_ROLES)), key: Optional[str] = Depends(idempotency_key),
                if_match: Optional[str] = IfMatch):
    def run(s):
        card = by_ref(s, PCard, ref, lock=True)
        check_if_match(card, if_match)
        return ind_general.card_view(s, ind_general.set_status(s, card, body.status, body.reason))
    return _post(p, f"POST /v1/pcards/{ref}/status", key, body, run, 200)


class AuthoriseIn(BaseModel):
    amountMinor: int = Field(gt=0)
    mcc: str = Field(pattern=r"^\d{4}$")
    merchant: Optional[str] = Field(default=None, max_length=120)
    on: Optional[date] = None


@router.post("/pcards/{ref}/authorise", tags=["P-cards"])
def authorise(ref: str, body: AuthoriseIn, p: Principal = Depends(require_any(*_PCARD_ROLES)), key: Optional[str] = Depends(idempotency_key)):
    """Issuer authorisation decision: approved only inside the card state, merchant categories and limits."""
    return _post(p, f"POST /v1/pcards/{ref}/authorise", key, body, lambda s: ind_general.authorise(
        s, by_ref(s, PCard, ref), amount_minor=body.amountMinor, mcc=body.mcc, on=body.on, merchant=body.merchant), 200)


class StatementLine(BaseModel):
    cardLast4: str = Field(pattern=r"^\d{4}$")
    holderName: Optional[str] = Field(default=None, max_length=120)
    txnRef: str = Field(min_length=2, max_length=60)
    txnDate: date
    merchant: str = Field(min_length=1, max_length=120)
    mcc: str = Field(pattern=r"^\d{4}$")
    amountMinor: int = Field(gt=0)
    po: Optional[str] = Field(default=None, max_length=30)


class StatementIn(BaseModel):
    issuer: str = Field(min_length=2, max_length=60)
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    lines: list[StatementLine] = Field(min_length=1, max_length=ind_general.MAX_STATEMENT_LINES)


@router.post("/pcard-statements", status_code=201, tags=["P-cards"])
def import_statement(body: StatementIn, p: Principal = Depends(require_any(*_PCARD_ROLES)), key: Optional[str] = Depends(idempotency_key)):
    """Import a card statement and reconcile its lines to purchase orders; breaches and unmatched lines go to review tasks."""
    return _post(p, "POST /v1/pcard-statements", key, body, lambda s: ind_general.statement_view(s, ind_general.import_statement(
        s, issuer=body.issuer, period=body.period, lines=[{"card_last4": l.cardLast4, "holder_name": l.holderName, "txn_ref": l.txnRef, "txn_date": l.txnDate,
                                                          "merchant": l.merchant, "mcc": l.mcc, "amount_minor": l.amountMinor, "po": l.po} for l in body.lines])))


@router.get("/pcard-statements", tags=["P-cards"])
def list_statements(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return rows(s.execute(select(PCardStatement).order_by(PCardStatement.period.desc(), PCardStatement.issuer)).scalars())


@router.get("/pcard-statements/{ref}", tags=["P-cards"])
def get_statement(ref: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return ind_general.statement_view(s, by_ref(s, PCardStatement, ref))
