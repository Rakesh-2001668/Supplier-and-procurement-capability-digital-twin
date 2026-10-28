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
    material: Optional[str] = None
    description: str
    plant: str = "P100"
    uom: str
    target_qty: Decimal = Field(gt=0)
    unit_price_minor: int = Field(gt=0)


class ContractIn(BaseModel):
    type: str = Field(pattern="^(SCHEDULING_AGREEMENT|QUANTITY_CONTRACT|VALUE_CONTRACT)$")
    title: str
    supplier: str
    company_code: str = "1000"
    valid_from: date
    valid_to: date
    payment_terms: str
    incoterms: Optional[str] = None
    lines: list[ContractLineIn] = Field(min_length=1)
    tolerances: dict = {"over_pct": "0", "under_pct": "0", "price_pct": "0"}
    index_ref: Optional[dict] = None  # e.g. {"index": "LME_AL", "base": "100.00", "band_pct": "3", "reset": "QUARTERLY"}


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
        if body.type == "SCHEDULING_AGREEMENT" and not body.index_ref:
            raise Problem(422, "INDEX_REQUIRED", "A scheduling agreement carries the price-index clause; give index_ref (index, base, band_pct)")
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
                                             incoterms=body.incoterms, lines=lines, owner_id=p.user_id, tolerances=body.tolerances,
                                             index_ref=body.index_ref)
        return guard.store(row(contract), 201)


@router.get("/contract-templates", tags=["F4 Contract"])
def contract_templates(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return contract_svc.templates(s)


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
    from app.pic.platform.auth import ROLE_SCOPES
    return [{"role": role, "scopes": sorted(scopes)} for role, scopes in ROLE_SCOPES.items()]


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
