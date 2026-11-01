"""M07 manual contracts, obligations and renewals; M08 change requests and expediting; M12 agent console; M13 administration."""
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.pic.api.deps import idempotency_key, idempotent, uow
from app.pic.models import AppUser, Material, PurchaseOrder
from app.pic.platform.auth import READ, Principal, require, require_any
from app.pic.platform.errors import Problem, not_found
from app.pic.platform.money import D
from app.pic.platform.serialize import row
from app.pic.services import admin, contract as contract_svc, order
from app.pic.services.common import by_ref, supplier_ref

router = APIRouter(prefix="/v1")


# ---------------------------------------------------------------- M07 contracts
class ContractLineIn(BaseModel):
    material: Optional[str] = Field(default=None, max_length=40)
    description: str = Field(min_length=1, max_length=200)
    plant: str = Field(default="P100", min_length=1, max_length=10)
    uom: str = Field(min_length=1, max_length=5)
    target_qty: Decimal = Field(gt=0, lt=Decimal("1e12"), decimal_places=3)
    unit_price_minor: int = Field(gt=0, lt=10**13)


class ToleranceIn(BaseModel):
    """Quantity over / under delivery and price tolerance in percent."""
    over_pct: Decimal = Field(default=Decimal(0), ge=0, le=100)
    under_pct: Decimal = Field(default=Decimal(0), ge=0, le=100)
    price_pct: Decimal = Field(default=Decimal(0), ge=0, le=100)


class IndexRefIn(BaseModel):
    index: str = Field(min_length=1, max_length=40)
    base: Decimal = Field(gt=0)
    band_pct: Decimal = Field(ge=0, lt=100)
    reset: Optional[str] = Field(default=None, pattern="^(MONTHLY|QUARTERLY|HALF_YEARLY|ANNUAL)$")


class ContractIn(BaseModel):
    type: str = Field(pattern="^(SCHEDULING_AGREEMENT|QUANTITY_CONTRACT|VALUE_CONTRACT|MASTER_AGREEMENT|RATE_CARD|SOW|NDA)$")
    title: str = Field(min_length=3, max_length=200)
    supplier: str = Field(min_length=1, max_length=40)
    company_code: str = Field(default="1000", min_length=1, max_length=10)
    valid_from: date
    valid_to: date
    payment_terms: str = Field(min_length=1, max_length=10)
    incoterms: Optional[str] = Field(default=None, max_length=40)
    lines: list[ContractLineIn] = Field(default=[], max_length=500)  # at least one for a call-off contract; a master agreement and an NDA have none
    tolerances: ToleranceIn = ToleranceIn()
    index_ref: Optional[IndexRefIn] = None  # e.g. {"index": "LME_AL", "base": "100.00", "band_pct": "3", "reset": "QUARTERLY"}
    framework: Optional[str] = Field(default=None, max_length=30)  # number of the master agreement a call-off contract refers to
    jurisdiction: Optional[str] = Field(default=None, pattern="^[A-Z]{2}(-[A-Z0-9]{1,3})?$")  # governing-law variant of the clause library
    category: Optional[str] = Field(default=None, max_length=40)  # selects the category overlay of the clause library (CLM-PLAYBOOK.categoryClauses)


@router.post("/contracts", status_code=201, tags=["F4 Contract"])
def create_contract(body: ContractIn, p: Principal = Depends(require("contract:manage")), key: Optional[str] = Depends(idempotency_key)):
    if body.valid_to <= body.valid_from:
        raise Problem(422, "INVALID_VALIDITY", "valid_to must be after valid_from")
    with uow(p) as s:
        guard = idempotent(s, "contract.create", key, body)
        if guard.replay:
            return guard.replay
        supplier = supplier_ref(s, body.supplier)
        if supplier.status == "BLOCKED":
            raise Problem(409, "SUPPLIER_BLOCKED", f"{supplier.code} is blocked", rule_ref="SLM")
        if body.type not in contract_svc.FRAMEWORK_TYPES and not body.lines:
            raise Problem(422, "LINES_REQUIRED", "A contract needs at least one line; only a master agreement or an NDA has none")
        if body.type in contract_svc.FRAMEWORK_TYPES and body.lines:
            raise Problem(422, "LINES_NOT_ALLOWED", f"A {body.type.replace('_', ' ').lower()} sets terms, not quantities: it carries no lines",
                          rule_ref="CLM-FRAMEWORK")
        if body.type == "SCHEDULING_AGREEMENT" and not body.index_ref:
            raise Problem(422, "INDEX_REQUIRED", "A scheduling agreement carries the price-index clause; give index_ref (index, base, band_pct)")
        framework = None
        if body.framework:
            framework = s.execute(select(contract_svc.Contract).where(contract_svc.Contract.number == body.framework)).scalar_one_or_none()
            if framework is None:
                raise not_found("Contract", body.framework)
        lines = []
        for line in body.lines:
            material = None
            if line.material:
                material = s.execute(select(Material).where(Material.number == line.material)).scalar_one_or_none()
                if material is None:
                    raise not_found("Material", line.material)
            lines.append({"material_id": material.id if material else None, "description": line.description, "plant": line.plant, "uom": line.uom,
                          "target_qty": line.target_qty, "unit_price_minor": line.unit_price_minor})
        contract = contract_svc.create_draft(s, type=body.type, title=body.title, supplier_id=supplier.id, company_code=body.company_code,
                                             valid_from=body.valid_from, valid_to=body.valid_to, payment_terms=body.payment_terms,
                                             incoterms=body.incoterms, lines=lines, owner_id=p.user_id,
                                             tolerances=body.tolerances.model_dump(mode="json"),
                                             index_ref=body.index_ref.model_dump(mode="json", exclude_none=True) if body.index_ref else None,
                                             framework_contract_id=framework.id if framework else None, jurisdiction=body.jurisdiction,
                                             category=body.category)
        return guard.store(row(contract), 201)


@router.get("/contract-templates", tags=["F4 Contract"])
def contract_templates(jurisdiction: Optional[str] = None, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return contract_svc.templates(s, jurisdiction)


@router.get("/obligations", tags=["F4 Contract"])
def obligations(party: Optional[str] = None, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return contract_svc.obligations_tracker(s, party)


@router.get("/contracts-renewals", tags=["F4 Contract"])
def renewals(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return contract_svc.renewals(s)


# ---------------------------------------------------------------- M08 PO-03 / PO-04
class ChangeRequestIn(BaseModel):
    lines: list[dict] = Field(min_length=1)
    reason: str


@router.post("/purchase-orders/{ref}/change-requests", status_code=201, tags=["F5 Purchase Order"])
def request_change(ref: str, body: ChangeRequestIn, p: Principal = Depends(require_any("po:confirm", "po:change"))):
    with uow(p) as s:
        return row(order.request_change(s, by_ref(s, PurchaseOrder, ref, lock=True), body.lines, body.reason))


@router.get("/po-confirmations", tags=["F5 Purchase Order"])
def po_confirmations(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return order.confirmations_view(s)


@router.get("/expediting", tags=["F5 Purchase Order"])
def expediting(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return order.expediting_view(s)


class ExpediteIn(BaseModel):
    line: int
    message: Optional[str] = None


@router.post("/purchase-orders/{ref}/expedite", tags=["F5 Purchase Order"])
def expedite(ref: str, body: ExpediteIn, p: Principal = Depends(require("po:change"))):
    with uow(p) as s:
        return order.expedite(s, by_ref(s, PurchaseOrder, ref), body.line, body.message)


# ---------------------------------------------------------------- M12 agent console (AIX-03)
class AutonomyIn(BaseModel):
    level: str = Field(pattern="^L[0-4]$")
    value_limit_minor: Optional[int] = None
    categories: Optional[list[str]] = None
    kill_switch: Optional[bool] = None
    reason: str


@router.put("/agents/{code}/autonomy", tags=["Agents"])
def set_autonomy(code: str, body: AutonomyIn, p: Principal = Depends(require("agents:manage"))):
    with uow(p) as s:
        return row(admin.set_autonomy(s, code, level=body.level, value_limit_minor=body.value_limit_minor, categories=body.categories,
                                      kill_switch=body.kill_switch, reason=body.reason))


@router.post("/agents/{code}/runs", tags=["Agents"])
def run_agent(code: str, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return admin.run_agent(s, code)


@router.get("/recommendations", tags=["Agents"])
def recommendations(status: Optional[str] = "OPEN", p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return admin.recommendations(s, status or None)


class FeedbackIn(BaseModel):
    accepted: bool
    comment: Optional[str] = None


@router.post("/recommendations/{rec_id}/feedback", tags=["Agents"])
def recommendation_feedback(rec_id: str, body: FeedbackIn, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return row(admin.decide_recommendation(s, admin.get_recommendation(s, rec_id), body.accepted, body.comment))


# ---------------------------------------------------------------- M13 administration (ADM-01, ADM-04)
@router.get("/admin/organisation", tags=["Admin"])
def organisation(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return admin.organisation(s)


class FxIn(BaseModel):
    from_ccy: str = Field(min_length=3, max_length=3)
    to_ccy: str = Field(min_length=3, max_length=3)
    rate: Decimal = Field(gt=0)
    valid_from: date
    source: str


@router.post("/admin/fx-rates", status_code=201, tags=["Admin"])
def add_fx_rate(body: FxIn, p: Principal = Depends(require("admin:rules"))):
    with uow(p) as s:
        return row(admin.add_fx_rate(s, body.from_ccy.upper(), body.to_ccy.upper(), D(body.rate), body.valid_from, body.source))


@router.get("/admin/roles", tags=["Admin"])
def roles(p: Principal = Depends(require("admin:rules"))):
    """Role catalogue: the built-in roles (read-only) and the tenant's own active roles."""
    from app.pic.services import role_admin
    with uow(p) as s:
        return [{"role": r["code"], "name": r["name"], "kind": r["kind"], "scopes": r["scopes"]} for r in role_admin.list_roles(s) if r["active"]]


@router.get("/admin/users", tags=["Admin"])
def users(p: Principal = Depends(require("admin:rules"))):
    with uow(p) as s:
        return admin.users(s)


class RolesIn(BaseModel):
    roles: list[str] = Field(min_length=1)
    reason: str


def _user(s, user_id: uuid.UUID) -> AppUser:
    user = s.get(AppUser, user_id)
    if user is None:
        raise not_found("User", user_id)
    return user


@router.put("/admin/users/{user_id}/roles", tags=["Admin"])
def assign_roles(user_id: uuid.UUID, body: RolesIn, p: Principal = Depends(require("admin:rules"))):
    with uow(p) as s:
        user = admin.assign_roles(s, _user(s, user_id), body.roles, body.reason)
        return {"id": str(user.id), "email": user.email, "roles": user.roles}


class ActiveIn(BaseModel):
    active: bool
    reason: str


@router.put("/admin/users/{user_id}/active", tags=["Admin"])
def set_active(user_id: uuid.UUID, body: ActiveIn, p: Principal = Depends(require("admin:rules"))):
    with uow(p) as s:
        user = admin.set_active(s, _user(s, user_id), body.active, body.reason)
        return {"id": str(user.id), "email": user.email, "active": user.active}


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/admin/users/{user_id}/mfa/reset", tags=["Admin"])
def reset_mfa(user_id: uuid.UUID, body: ReasonIn, p: Principal = Depends(require("admin:rules"))):
    """Remove a user's authenticator (lost phone). Audited with the reason; the user enrols again at next sign-in if required."""
    from app.pic.platform import mfa

    with uow(p) as s:
        user = _user(s, user_id)
        mfa.admin_reset(s, user, body.reason)
        return {"id": str(user.id), "email": user.email, "mfaEnrolled": user.mfa_enrolled}


@router.get("/admin/templates", tags=["Admin"])
def industry_templates(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return admin.templates(s)
