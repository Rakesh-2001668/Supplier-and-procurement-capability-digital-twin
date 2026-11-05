"""ABAC read scope of the spend module (Technical Document SEC-AZ, BP M01): what a user may SEE in the spend cube.

The command checks in platform/abac.py decide who may release or approve a document; reading spend needs the same attributes on every query.
A user whose attributes restrict ``plants``, ``company_codes`` or ``categories`` (ABAC rule dimensions) or the spend-specific ``cost_centres`` and
``supplier_groups`` (parent supplier codes) sees totals, rows, hits and reviews that are inside that scope, and nothing else: every aggregate is
computed after the restriction, never filtered afterwards, so a total can never carry a figure from outside the scope.

A user without the attribute (or with "*") is not restricted on that dimension; agents, the scheduler and the loaders (no principal, or an agent
principal) are not restricted. An ABAC rule in mode AUDIT or OFF does not restrict reads, like abac.read_scope.
"""
import uuid
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import and_, false, select
from sqlalchemy.orm import Session

from app.pic.platform import abac

DIMENSIONS = ("plants", "company_codes", "categories", "cost_centres", "supplier_groups")


@dataclass
class Scope:
    plants: Optional[list] = None
    company_codes: Optional[list] = None
    categories: Optional[list] = None
    cost_centres: Optional[list] = None
    supplier_groups: Optional[list] = None  # parent supplier codes
    restricted: bool = field(default=False)

    def describe(self) -> dict:
        return {k: getattr(self, k) for k in DIMENSIONS if getattr(self, k) is not None}


def _allowed(attributes: dict, name: str) -> Optional[list]:
    value = attributes.get(name)
    if value is None:
        return None
    values = [value] if isinstance(value, str) else [str(v) for v in value]
    return None if "*" in values else values


def of(session: Session) -> Scope:
    """The read scope of the session's principal (cached per session)."""
    cached = session.info.get("spend_scope")
    principal = session.info.get("principal")
    if cached is not None and cached[0] is principal:
        return cached[1]
    scope = Scope()
    if principal is not None and not principal.is_agent and not principal.attributes.get("mfa_enrolment"):
        policy = abac.policy_for(session)
        if str(policy.get("mode", "ENFORCE")).upper() == "ENFORCE":
            attributes = abac._attributes(session, principal)
            dimensions = policy.get("dimensions") or {}
            scope.plants = _allowed(attributes, dimensions.get("plant", "plants"))
            scope.company_codes = _allowed(attributes, dimensions.get("company_code", "company_codes"))
            scope.categories = _allowed(attributes, dimensions.get("category", "categories"))
            scope.cost_centres = _allowed(attributes, "cost_centres")
            scope.supplier_groups = _allowed(attributes, "supplier_groups")
    scope.restricted = any(getattr(scope, k) is not None for k in DIMENSIONS)
    session.info["spend_scope"] = (principal, scope)
    return scope


def _category_codes(session: Session, codes: list) -> set:
    from app.pic.services import spend_cube
    return spend_cube._descendants(spend_cube._taxonomy(session), codes) | set(codes)


def _supplier_ids(session: Session, parent_codes: list) -> list:
    from app.pic.models import Supplier
    parents = list(session.execute(select(Supplier.id).where(Supplier.code.in_(parent_codes))).scalars())
    if not parents:
        return [uuid.UUID(int=0)]
    members = list(session.execute(select(Supplier.id).where(Supplier.id.in_(parents) | Supplier.parent_supplier_id.in_(parents))).scalars())
    return members or [uuid.UUID(int=0)]


def where(session: Session, model) -> list:
    """SQL conditions that restrict ``model`` (spend_line, spend_cube_summary or spend_commitment_summary) to the user's scope."""
    scope = of(session)
    if not scope.restricted:
        return []
    out = []
    if scope.plants is not None:
        out.append(model.plant.in_(scope.plants) if scope.plants else false())
    if scope.company_codes is not None:
        out.append(model.company_code.in_(scope.company_codes) if scope.company_codes else false())
    if scope.categories is not None:
        out.append(model.category.in_(sorted(_category_codes(session, scope.categories))) if scope.categories else false())
    if scope.cost_centres is not None:
        out.append(and_(model.cost_object_type == "COST_CENTER", model.cost_object.in_(scope.cost_centres)) if scope.cost_centres else false())
    if scope.supplier_groups is not None:
        out.append(model.supplier_id.in_(_supplier_ids(session, scope.supplier_groups)))
    return out


def allows(session: Session, *, plant: Optional[str] = None, company_code: Optional[str] = None, category: Optional[str] = None,
           supplier_id=None, cost_object: Optional[str] = None, cost_object_type: Optional[str] = None) -> bool:
    """The same restriction for one object (a hit, a review, a plan) already loaded."""
    scope = of(session)
    if not scope.restricted:
        return True
    if scope.plants is not None and plant not in scope.plants:
        return False
    if scope.company_codes is not None and company_code not in scope.company_codes:
        return False
    if scope.categories is not None and category not in _category_codes(session, scope.categories):
        return False
    if scope.cost_centres is not None and not (cost_object_type == "COST_CENTER" and cost_object in scope.cost_centres):
        return False
    if scope.supplier_groups is not None and supplier_id not in _supplier_ids(session, scope.supplier_groups):
        return False
    return True


def line_exists(session: Session, line_id_column):
    """EXISTS-subquery that keeps rows of another table (hits, reviews) whose spend line is inside the scope."""
    from app.pic.models import SpendLine
    conditions = where(session, SpendLine)
    if not conditions:
        return None
    return select(SpendLine.id).where(SpendLine.id == line_id_column, *conditions).exists()


def allows_category(session: Session, category: str) -> bool:
    """Category-only check for objects that have no plant or company (a category plan)."""
    scope = of(session)
    return scope.categories is None or category in _category_codes(session, scope.categories)
