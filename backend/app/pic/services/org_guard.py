"""ADM-01 organisation records on new documents: a deactivated company code, plant, storage location, cost object, purchasing
organisation or purchasing group is refused on a NEW requisition, purchase order or goods receipt that names it.

Deactivation (services/org_admin.py) keeps history readable and open documents working, so this guard is only called where a
document is created. A code that is not in the organisation master at all is not this guard's concern (some tenants run
without a maintained master): only a record that exists and is deactivated is refused, with one 422 problem+json
``ORG_RECORD_INACTIVE`` that lists every inactive record the document names.
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import CompanyCode, CostObject, Plant, PurchasingGroup, PurchasingOrg, StorageLocation
from app.pic.platform.errors import Problem

RULE = "ADM-01"


def inactive_records(session: Session, *, company_code: Optional[str] = None, plant: Optional[str] = None,
                     storage_location: Optional[str] = None, cost_object: Optional[tuple[str, str]] = None,
                     purchasing_org: Optional[str] = None, purchasing_group: Optional[str] = None) -> list[dict]:
    """The named records that exist and are deactivated. ``cost_object`` is (account assignment type, code)."""
    found: list[dict] = []

    def check(kind: str, code: Optional[str], row) -> None:
        if code and row is not None and not row.active:
            found.append({"kind": kind, "code": code})

    if company_code:
        check("company code", company_code, session.execute(select(CompanyCode).where(CompanyCode.code == company_code)).scalar_one_or_none())
    if plant:
        check("plant", plant, session.execute(select(Plant).where(Plant.code == plant)).scalar_one_or_none())
    if storage_location:
        query = select(StorageLocation).where(StorageLocation.code == storage_location)
        if plant:
            query = query.where(StorageLocation.plant == plant)
        rows = session.execute(query).scalars().all()
        # a location code is unique per plant: refused only when every matching location of the plant is deactivated
        if rows and not any(r.active for r in rows):
            found.append({"kind": "storage location", "code": storage_location})
    if cost_object and cost_object[1]:
        kind, code = cost_object
        query = select(CostObject).where(CostObject.code == code)
        if kind:
            query = query.where(CostObject.type == kind)
        rows = session.execute(query).scalars().all()
        if rows and not any(r.active for r in rows):
            found.append({"kind": "cost object", "code": code})
    if purchasing_org:
        check("purchasing organisation", purchasing_org,
              session.execute(select(PurchasingOrg).where(PurchasingOrg.code == purchasing_org)).scalar_one_or_none())
    if purchasing_group:
        check("purchasing group", purchasing_group,
              session.execute(select(PurchasingGroup).where(PurchasingGroup.code == purchasing_group)).scalar_one_or_none())
    return found


def ensure_active(session: Session, document: str, **named) -> None:
    """Refuse a new ``document`` (e.g. "requisition") that names a deactivated organisation record."""
    found = inactive_records(session, **named)
    if found:
        listed = ", ".join(f"{f['kind']} {f['code']}" for f in found)
        raise Problem(422, "ORG_RECORD_INACTIVE",
                      f"A new {document} cannot name {listed}: deactivated in the organisation master (ADM-01); "
                      "choose an active record or ask the tenant administrator to reactivate it",
                      rule_ref=RULE, inactive=found)
