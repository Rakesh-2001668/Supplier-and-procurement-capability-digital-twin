"""Helpers shared by the domain services."""
import uuid
from typing import Any, Optional, Type

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import AppUser, Material, Supplier, SupplierCategoryStatus
from app.pic.platform.errors import Problem, not_found


def principal(session: Session):
    return session.info["principal"]


def by_number(session: Session, model: Type, number: str, lock: bool = False):
    query = select(model).where(model.number == number)
    if lock:
        query = query.with_for_update()
    obj = session.execute(query).scalar_one_or_none()
    if obj is None:
        raise not_found(model.__tablename__.replace("_", " ").title(), number)
    return obj


def by_ref(session: Session, model: Type, ref: str, lock: bool = False):
    """Accept either a UUID or a human document number."""
    try:
        obj = session.get(model, uuid.UUID(str(ref)), with_for_update=lock)
        if obj is not None:
            return obj
    except ValueError:
        pass
    return by_number(session, model, ref, lock=lock)


def supplier_by_code(session: Session, code: str) -> Supplier:
    supplier = session.execute(select(Supplier).where(Supplier.code == code)).scalar_one_or_none()
    if supplier is None:
        raise not_found("Supplier", code)
    return supplier


def supplier_ref(session: Session, ref: str) -> Supplier:
    try:
        obj = session.get(Supplier, uuid.UUID(str(ref)))
        if obj:
            return obj
    except ValueError:
        pass
    return supplier_by_code(session, ref)


def material_by_number(session: Session, number: str) -> Material:
    material = session.execute(select(Material).where(Material.number == number)).scalar_one_or_none()
    if material is None:
        raise not_found("Material", number)
    return material


def category_status(session: Session, supplier_id: uuid.UUID, category: str) -> str:
    supplier = session.get(Supplier, supplier_id)
    if supplier is not None and supplier.status == "BLOCKED":
        return "BLOCKED"
    row = session.execute(select(SupplierCategoryStatus).where(
        SupplierCategoryStatus.supplier_id == supplier_id, SupplierCategoryStatus.category == category)).scalar_one_or_none()
    return row.status if row else "NOT_REGISTERED"


def require_supplier_user(session: Session, supplier_id: uuid.UUID) -> None:
    """External users may act only on their own supplier's documents."""
    p = principal(session)
    if "SUPPLIER_USER" in p.roles and p.supplier_id != supplier_id:
        raise Problem(403, "FORBIDDEN", "You can only act on your own company's documents", rule_ref="SUPPLIER_SCOPE")


def user_by_email(session: Session, email: str) -> AppUser:
    user = session.execute(select(AppUser).where(AppUser.email == email)).scalar_one_or_none()
    if user is None:
        raise not_found("User", email)
    return user


def days_from_terms(terms: str) -> int:
    digits = "".join(ch for ch in terms if ch.isdigit())
    return int(digits) if digits else 0
