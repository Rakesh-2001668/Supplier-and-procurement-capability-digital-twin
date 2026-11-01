"""ADM-01 organisation management: company codes, plants (state, working days, holidays), storage locations, cost objects,
purchasing organisations and groups, currencies.

One generic create / update / deactivate / delete flow driven by a ``Kind`` description per master. Rules:

* codes are validated and unique per tenant; a code never changes after creation (documents refer to it by value);
* a record that anything refers to (documents, children, rule scopes, ...) is never deleted: ``delete`` deactivates it instead and
  says so; an unreferenced record is deleted. References are found from the ORM metadata (every table with a column of the
  record's name), so a new document table is covered without changing this module;
* a record with active children (a plant under a company code) cannot be deactivated before them;
* every write is audited with before and after; ``version`` (the row version) is the ETag of each record.
"""
import re
import uuid
from datetime import date
from typing import Any, Callable, Optional

from sqlalchemy import func, literal, select, text
from sqlalchemy.orm import Session

from app.pic.db import Base, SCHEMA
from app.pic.models import (
    AppUser, CompanyCode, CostObject, Currency, Plant, PurchasingGroup, PurchasingOrg, StorageLocation,
)
from app.pic.platform import audit
from app.pic.platform.errors import Problem, not_found
from app.pic.services import master_changes
from app.pic.services.common import principal

CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.-]{0,9}$")
COST_TYPES = ("COST_CENTER", "WBS", "ORDER", "ASSET")


def _admin(session: Session) -> None:
    if "TENANT_ADMIN" not in principal(session).roles:
        raise Problem(403, "FORBIDDEN", "Requires the tenant administrator", rule_ref="RBAC")


def _invalid(errors: list[str]) -> None:
    if errors:
        raise Problem(422, "VALIDATION_FAILED", "; ".join(errors), rule_ref="ADM-01", errors=errors)


def _text(body: dict, key: str, label: str, errors: list[str], *, min_len: int = 2, max_len: int = 200, required: bool = True) -> Optional[str]:
    value = body.get(key)
    if value is None or str(value).strip() == "":
        if required:
            errors.append(f"{label} is required")
        return None
    value = str(value).strip()
    if not min_len <= len(value) <= max_len:
        errors.append(f"{label} must be {min_len}-{max_len} characters")
    return value


def _code(body: dict, errors: list[str], label: str, pattern: re.Pattern = CODE_RE, max_len: int = 10) -> Optional[str]:
    code = str(body.get("code") or "").strip().upper()
    if not pattern.match(code):
        errors.append(f"{label} code must be 1-{max_len} characters: capital letters, digits, '.', '_' or '-'")
        return None
    return code


# ---------------------------------------------------------------- references
def _tables_with(*columns: str, exclude: tuple = ()):
    for table in Base.metadata.sorted_tables:
        if table.schema != SCHEMA or table.name in exclude or table.name in ("audit_event", "audit_event_archive", "idempotency_record"):
            continue
        if all(c in table.c for c in columns):
            yield table


def _exists(session: Session, table, *conditions) -> bool:
    return session.execute(select(literal(1)).select_from(table).where(*conditions).limit(1)).first() is not None


def is_referenced(session: Session, kind: str, row) -> bool:
    """Does any other record or document refer to this master record by its code?"""
    if kind == "company-codes":
        pairs = [(t, t.c.company_code == row.code) for t in _tables_with("company_code", exclude=("company_code",))]
    elif kind == "plants":
        pairs = [(t, t.c.plant == row.code) for t in _tables_with("plant", exclude=("plant",))]
    elif kind == "storage-locations":
        pairs = [(t, (t.c.storage_location == row.code) & (t.c.plant == row.plant)) for t in _tables_with("storage_location", "plant",
                                                                                                          exclude=("storage_location",))]
    elif kind == "cost-objects":
        pairs = [(t, (t.c.cost_object_code == row.code) & (t.c.cost_object_type == row.type))
                 for t in _tables_with("cost_object_code", "cost_object_type")]
        pairs += [(t, (t.c.cost_object == row.code) & (t.c.cost_object_type == row.type)) for t in _tables_with("cost_object", "cost_object_type")]
    elif kind == "purchasing-orgs":
        pairs = [(t, t.c.purch_org == row.code) for t in _tables_with("purch_org")]
        pairs += [(t, t.c.purchasing_org == row.code) for t in _tables_with("purchasing_org", exclude=("purchasing_org",))]
    elif kind == "purchasing-groups":
        pairs = [(t, t.c.purchasing_group == row.code) for t in _tables_with("purchasing_group", exclude=("purchasing_group",))]
    elif kind == "currencies":
        pairs = [(t, t.c.currency == row.code) for t in _tables_with("currency", exclude=("currency",))]
        pairs += [(t, t.c.from_ccy == row.code) for t in _tables_with("from_ccy")]
        pairs += [(t, t.c.to_ccy == row.code) for t in _tables_with("to_ccy")]
        if session.execute(text("SELECT 1 FROM pic.tenant WHERE base_currency = :c"), {"c": row.code}).first():
            return True
    else:
        return False
    return any(_exists(session, t, cond) for t, cond in pairs)


def active_children(session: Session, kind: str, row) -> list[str]:
    out = []
    if kind == "company-codes":
        for model, label_, col in ((Plant, "plants", Plant.company_code), (CostObject, "cost objects", CostObject.company_code),
                                   (PurchasingOrg, "purchasing organisations", PurchasingOrg.company_code)):
            n = session.execute(select(func.count()).select_from(model).where(col == row.code, model.active.is_(True))).scalar()
            if n:
                out.append(f"{n} active {label_}")
    elif kind == "plants":
        n = session.execute(select(func.count()).select_from(StorageLocation).where(StorageLocation.plant == row.code,
                                                                                    StorageLocation.active.is_(True))).scalar()
        if n:
            out.append(f"{n} active storage locations")
        n = session.execute(select(func.count()).select_from(PurchasingGroup).where(PurchasingGroup.plant == row.code,
                                                                                    PurchasingGroup.active.is_(True))).scalar()
        if n:
            out.append(f"{n} active purchasing groups")
    elif kind == "purchasing-orgs":
        n = session.execute(select(func.count()).select_from(PurchasingGroup).where(PurchasingGroup.purchasing_org == row.code,
                                                                                    PurchasingGroup.active.is_(True))).scalar()
        if n:
            out.append(f"{n} active purchasing groups")
    return out


# ---------------------------------------------------------------- per-kind validation
def _company(session: Session, code: Optional[str], errors: list[str], label: str = "company code", must_be_active: bool = True):
    if not code:
        errors.append(f"{label} is required")
        return None
    row = session.execute(select(CompanyCode).where(CompanyCode.code == code)).scalar_one_or_none()
    if row is None:
        errors.append(f"{label} {code} does not exist")
    elif must_be_active and not row.active:
        errors.append(f"{label} {code} is deactivated")
    return row


def _validate_company(session: Session, body: dict, row: Optional[CompanyCode]) -> dict:
    errors: list[str] = []
    out: dict[str, Any] = {}
    if row is None:
        out["code"] = _code(body, errors, "company")
    if row is None or "name" in body:
        out["name"] = _text(body, "name", "legal entity name", errors)
    if "gstin" in body or row is None:
        gstin = (body.get("gstin") or "").strip().upper() or None
        if gstin:
            errors += master_changes.gstin_errors(gstin)
        out["gstin"] = gstin
    if row is None or "currency" in body:
        ccy = str(body.get("currency") or "INR").upper()
        known = session.execute(select(Currency).where(Currency.code == ccy)).scalar_one_or_none()
        if known is None or not known.active:
            errors.append(f"currency {ccy} is not an active currency of this tenant")
        elif row is not None and ccy != row.currency and is_referenced(session, "company-codes", row):
            errors.append("the currency of a company code that already has documents cannot change")
        out["currency"] = ccy
    if row is None or "fiscal_year_start_month" in body:
        month = body.get("fiscal_year_start_month", 4)
        if not isinstance(month, int) or isinstance(month, bool) or not 1 <= month <= 12:
            errors.append("fiscal year start month must be 1-12")
        out["fiscal_year_start_month"] = month
    _invalid(errors)
    return {k: v for k, v in out.items() if k != "code" or row is None}


def _validate_plant(session: Session, body: dict, row: Optional[Plant]) -> dict:
    errors: list[str] = []
    out: dict[str, Any] = {}
    if row is None:
        out["code"] = _code(body, errors, "plant")
        _company(session, str(body.get("company_code") or "").strip().upper(), errors)
        out["company_code"] = str(body.get("company_code") or "").strip().upper()
    if row is None or "name" in body:
        out["name"] = _text(body, "name", "plant name", errors)
    if row is None or "state_code" in body:
        state = str(body.get("state_code") or "").strip()
        if state not in master_changes.STATE_CODES:
            errors.append("state code must be a 2-digit GST state code (01-38 or 97)")
        out["state_code"] = state
    if row is None or "working_days" in body:
        days = body.get("working_days", [0, 1, 2, 3, 4, 5])
        if (not isinstance(days, list) or not days or any(not isinstance(d, int) or isinstance(d, bool) or not 0 <= d <= 6 for d in days)
                or len(set(days)) != len(days)):
            errors.append("working days must be a non-empty list of weekdays 0 (Monday) to 6 (Sunday), without repeats")
        out["working_days"] = sorted(set(days)) if isinstance(days, list) else days
    _invalid(errors)
    return {k: v for k, v in out.items() if k != "code" or row is None}


def _validate_sloc(session: Session, body: dict, row: Optional[StorageLocation]) -> dict:
    errors: list[str] = []
    out: dict[str, Any] = {}
    if row is None:
        out["code"] = _code(body, errors, "storage location", max_len=10)
        plant = str(body.get("plant") or "").strip().upper()
        p = session.execute(select(Plant).where(Plant.code == plant)).scalar_one_or_none()
        if p is None:
            errors.append(f"plant {plant or '-'} does not exist")
        elif not p.active:
            errors.append(f"plant {plant} is deactivated")
        out["plant"] = plant
        if out["code"] and session.execute(select(StorageLocation.id).where(StorageLocation.plant == plant,
                                                                           StorageLocation.code == out["code"])).first():
            errors.append(f"storage location {out['code']} already exists in plant {plant}")
    if row is None or "name" in body:
        out["name"] = _text(body, "name", "storage location name", errors, max_len=100)
    _invalid(errors)
    return {k: v for k, v in out.items() if k != "code" or row is None}


def _validate_cost_object(session: Session, body: dict, row: Optional[CostObject]) -> dict:
    errors: list[str] = []
    out: dict[str, Any] = {}
    if row is None:
        type_ = str(body.get("type") or "").strip().upper()
        if type_ not in COST_TYPES:
            errors.append(f"type must be one of {', '.join(COST_TYPES)}")
        out["type"] = type_
        out["code"] = _code(body, errors, "cost object", re.compile(r"^[A-Z0-9][A-Z0-9_.-]{0,29}$"), 30)
        company = str(body.get("company_code") or "").strip().upper()
        _company(session, company, errors)
        out["company_code"] = company
        if out["code"] and session.execute(select(CostObject.id).where(CostObject.type == type_, CostObject.code == out["code"])).first():
            errors.append(f"{type_} {out['code']} already exists")
    if row is None or "name" in body:
        out["name"] = _text(body, "name", "name", errors)
    for key, label_ in (("owner_user_id", "owner"), ("department_head_user_id", "department head")):
        if key in body:
            value = body.get(key)
            if value in (None, ""):
                out[key] = None
                continue
            try:
                uid = uuid.UUID(str(value))
            except ValueError:
                errors.append(f"{label_} must be a user id")
                continue
            user = session.get(AppUser, uid)
            if user is None or not user.active or user.supplier_id is not None:
                errors.append(f"{label_} must be an active internal user")
            out[key] = uid
    _invalid(errors)
    return {k: v for k, v in out.items() if k != "code" or row is None}


def _validate_porg(session: Session, body: dict, row: Optional[PurchasingOrg]) -> dict:
    errors: list[str] = []
    out: dict[str, Any] = {}
    if row is None:
        out["code"] = _code(body, errors, "purchasing organisation")
        company = str(body.get("company_code") or "").strip().upper()
        _company(session, company, errors)
        out["company_code"] = company
    if row is None or "name" in body:
        out["name"] = _text(body, "name", "name", errors)
    _invalid(errors)
    return {k: v for k, v in out.items() if k != "code" or row is None}


def _validate_pgroup(session: Session, body: dict, row: Optional[PurchasingGroup]) -> dict:
    errors: list[str] = []
    out: dict[str, Any] = {}
    if row is None:
        out["code"] = _code(body, errors, "purchasing group")
    if row is None or "name" in body:
        out["name"] = _text(body, "name", "name", errors)
    if row is None or "purchasing_org" in body:
        org = (str(body.get("purchasing_org") or "").strip().upper()) or None
        if org:
            o = session.execute(select(PurchasingOrg).where(PurchasingOrg.code == org)).scalar_one_or_none()
            if o is None or not o.active:
                errors.append(f"purchasing organisation {org} does not exist or is deactivated")
        out["purchasing_org"] = org
    if row is None or "plant" in body:
        plant = (str(body.get("plant") or "").strip().upper()) or None
        if plant:
            p = session.execute(select(Plant).where(Plant.code == plant)).scalar_one_or_none()
            if p is None or not p.active:
                errors.append(f"plant {plant} does not exist or is deactivated")
        out["plant"] = plant
    if row is None or "buyer_user_ids" in body:
        ids: list[uuid.UUID] = []
        for raw in body.get("buyer_user_ids") or []:
            try:
                uid = uuid.UUID(str(raw))
            except ValueError:
                errors.append(f"buyer {raw!r} is not a user id")
                continue
            user = session.get(AppUser, uid)
            if user is None or not user.active or user.supplier_id is not None:
                errors.append(f"buyer {uid} is not an active internal user")
            elif uid not in ids:
                ids.append(uid)
        out["buyer_user_ids"] = ids
    _invalid(errors)
    return {k: v for k, v in out.items() if k != "code" or row is None}


def _validate_currency(session: Session, body: dict, row: Optional[Currency]) -> dict:
    errors: list[str] = []
    out: dict[str, Any] = {}
    if row is None:
        code = str(body.get("code") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", code):
            errors.append("currency code must be a 3-letter ISO 4217 code")
        out["code"] = code
    if row is None or "name" in body:
        out["name"] = _text(body, "name", "currency name", errors, max_len=60)
    if row is None or "decimals" in body:
        decimals = body.get("decimals", 2)
        if not isinstance(decimals, int) or isinstance(decimals, bool) or not 0 <= decimals <= 4:
            errors.append("decimals must be 0-4")
        elif row is not None and decimals != row.decimals and is_referenced(session, "currencies", row):
            errors.append("the decimals of a currency that is already in use cannot change")
        out["decimals"] = decimals
    _invalid(errors)
    return {k: v for k, v in out.items() if k != "code" or row is None}


class Kind:
    def __init__(self, key: str, label_: str, model, validate: Callable, view: Callable, audit_type: str, order: tuple):
        self.key, self.label, self.model, self.validate, self.view, self.audit_type, self.order = key, label_, model, validate, view, audit_type, order


def _base_view(r) -> dict:
    return {"id": str(r.id), "version": r.row_version, "active": r.active}


KINDS: dict[str, Kind] = {
    "company-codes": Kind("company-codes", "Company code", CompanyCode, _validate_company, lambda r: {
        **_base_view(r), "code": r.code, "name": r.name, "gstin": r.gstin, "currency": r.currency,
        "fiscalYearStartMonth": r.fiscal_year_start_month}, "COMPANY_CODE", (CompanyCode.code,)),
    "plants": Kind("plants", "Plant", Plant, _validate_plant, lambda r: {
        **_base_view(r), "code": r.code, "name": r.name, "companyCode": r.company_code, "stateCode": r.state_code,
        "workingDays": r.working_days, "holidays": [h.isoformat() for h in (r.holidays or [])]}, "PLANT", (Plant.code,)),
    "storage-locations": Kind("storage-locations", "Storage location", StorageLocation, _validate_sloc, lambda r: {
        **_base_view(r), "plant": r.plant, "code": r.code, "name": r.name}, "STORAGE_LOCATION", (StorageLocation.plant, StorageLocation.code)),
    "cost-objects": Kind("cost-objects", "Cost object", CostObject, _validate_cost_object, lambda r: {
        **_base_view(r), "type": r.type, "code": r.code, "name": r.name, "companyCode": r.company_code,
        "ownerUserId": str(r.owner_user_id) if r.owner_user_id else None,
        "departmentHeadUserId": str(r.department_head_user_id) if r.department_head_user_id else None}, "COST_OBJECT",
        (CostObject.type, CostObject.code)),
    "purchasing-orgs": Kind("purchasing-orgs", "Purchasing organisation", PurchasingOrg, _validate_porg, lambda r: {
        **_base_view(r), "code": r.code, "name": r.name, "companyCode": r.company_code}, "PURCHASING_ORG", (PurchasingOrg.code,)),
    "purchasing-groups": Kind("purchasing-groups", "Purchasing group", PurchasingGroup, _validate_pgroup, lambda r: {
        **_base_view(r), "code": r.code, "name": r.name, "purchasingOrg": r.purchasing_org, "plant": r.plant,
        "buyerUserIds": [str(u) for u in (r.buyer_user_ids or [])]}, "PURCHASING_GROUP", (PurchasingGroup.code,)),
    "currencies": Kind("currencies", "Currency", Currency, _validate_currency, lambda r: {
        **_base_view(r), "code": r.code, "name": r.name, "decimals": r.decimals}, "CURRENCY", (Currency.code,)),
}


def kind_of(key: str) -> Kind:
    if key not in KINDS:
        raise Problem(404, "UNKNOWN_KIND", f"Unknown master {key}; use one of {', '.join(KINDS)}")
    return KINDS[key]


def ref_of(kind: Kind, r) -> str:
    return getattr(r, "code", str(r.id)) if kind.key != "cost-objects" else f"{r.type}:{r.code}"


def get(session: Session, kind: Kind, record_id: uuid.UUID, lock: bool = False):
    r = session.get(kind.model, record_id, with_for_update=lock)
    if r is None:
        raise not_found(kind.label, record_id)
    return r


def list_all(session: Session, kind: Kind) -> list[dict]:
    return [kind.view(r) for r in session.execute(select(kind.model).order_by(*kind.order)).scalars()]


# ---------------------------------------------------------------- commands
def create(session: Session, kind: Kind, body: dict) -> dict:
    _admin(session)
    values = kind.validate(session, body, None)
    existing = None
    if kind.key not in ("storage-locations", "cost-objects"):
        existing = session.execute(select(kind.model.id).where(kind.model.code == values["code"])).first()
    if existing:
        raise Problem(409, "CODE_EXISTS", f"{kind.label} {values['code']} already exists", rule_ref="ADM-01")
    r = kind.model(tenant_id=principal(session).tenant_id, created_by=principal(session).user_id, **values)
    session.add(r)
    session.flush()
    audit.record(session, kind.audit_type, r.id, "CREATED", object_ref=ref_of(kind, r), after=kind.view(r))
    return kind.view(r)


def update(session: Session, kind: Kind, record_id: uuid.UUID, body: dict, reason: Optional[str]) -> dict:
    _admin(session)
    r = get(session, kind, record_id, lock=True)
    before = kind.view(r)
    values = kind.validate(session, body, r)
    changed = {k: v for k, v in values.items() if getattr(r, k) != v}
    if not changed:
        return before
    for k, v in changed.items():
        setattr(r, k, v)
    session.flush()
    audit.record(session, kind.audit_type, r.id, "UPDATED", object_ref=ref_of(kind, r), before=before, after=kind.view(r), reason=reason)
    return kind.view(r)


def set_active(session: Session, kind: Kind, record_id: uuid.UUID, active: bool, reason: Optional[str]) -> dict:
    _admin(session)
    r = get(session, kind, record_id, lock=True)
    if r.active == active:
        return kind.view(r)
    if not active:
        children = active_children(session, kind.key, r)
        if children:
            raise Problem(409, "HAS_ACTIVE_CHILDREN", f"{kind.label} {ref_of(kind, r)} still has {', '.join(children)}; deactivate those first",
                          rule_ref="ADM-01")
        if kind.key == "currencies":
            tenant_ccy = session.execute(text("SELECT base_currency FROM pic.tenant WHERE id = :t"),
                                         {"t": principal(session).tenant_id}).scalar()
            if tenant_ccy == r.code:
                raise Problem(409, "BASE_CURRENCY", "The tenant's base currency cannot be deactivated", rule_ref="ADM-01")
    else:
        errors: list[str] = []
        if kind.key in ("plants", "cost-objects", "purchasing-orgs"):
            _company(session, r.company_code, errors)
        elif kind.key == "storage-locations":
            p = session.execute(select(Plant).where(Plant.code == r.plant)).scalar_one_or_none()
            if p is None or not p.active:
                errors.append(f"plant {r.plant} is deactivated")
        _invalid(errors)
    r.active = active
    session.flush()
    audit.record(session, kind.audit_type, r.id, "ACTIVATED" if active else "DEACTIVATED", object_ref=ref_of(kind, r),
                 before={"active": not active}, after={"active": active}, reason=reason)
    return kind.view(r)


def delete(session: Session, kind: Kind, record_id: uuid.UUID, reason: Optional[str]) -> dict:
    """Delete an unreferenced record; deactivate a referenced one (history keeps its master data)."""
    _admin(session)
    r = get(session, kind, record_id, lock=True)
    if is_referenced(session, kind.key, r):
        view = set_active(session, kind, record_id, False, reason or "Referenced; deactivated instead of deleted")
        return {"outcome": "DEACTIVATED", "reason": "Other records refer to it, so it was deactivated instead of deleted", "record": view}
    before = kind.view(r)
    ref = ref_of(kind, r)
    rid = r.id
    session.delete(r)
    session.flush()
    audit.record(session, kind.audit_type, rid, "DELETED", object_ref=ref, before=before, reason=reason)
    return {"outcome": "DELETED", "record": before}


def add_holidays(session: Session, record_id: uuid.UUID, holidays: list[date], source: str) -> dict:
    from app.pic.services import admin
    plant = get(session, KINDS["plants"], record_id, lock=True)
    added = admin.add_plant_holidays(session, plant.code, holidays, source)
    session.flush()
    return {**KINDS["plants"].view(plant), "added": [d.isoformat() for d in added]}


def remove_holiday(session: Session, record_id: uuid.UUID, day: date, reason: str) -> dict:
    """Correct a wrongly entered holiday. Planned dates already computed keep their basis; the removal is audited with the reason."""
    _admin(session)
    plant = get(session, KINDS["plants"], record_id, lock=True)
    if day not in (plant.holidays or []):
        raise Problem(404, "HOLIDAY_NOT_FOUND", f"{day} is not a holiday of plant {plant.code}")
    if not reason or len(reason.strip()) < 5:
        raise Problem(422, "REASON_REQUIRED", "Say why the holiday is removed")
    plant.holidays = [h for h in plant.holidays if h != day]
    session.flush()
    audit.record(session, "PLANT", plant.id, "CALENDAR_UPDATED", object_ref=plant.code, before={"holidays": len(plant.holidays) + 1},
                 after={"removed": day.isoformat(), "holidays": len(plant.holidays)}, reason=reason)
    return KINDS["plants"].view(plant)
