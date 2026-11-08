"""M04 hosted catalogue maintenance (flow fixes A11): create, change, deactivate and reactivate the items of the CATALOGUE channel.

A hosted catalogue item is a supplier's part with a price valid from ``valid_from`` to ``valid_to`` (open ends allowed), optionally tied to a
material master record and to the contract that fixes its price. The guided-buying search offers only active items valid today, and a
requisition line refuses an item that is not (services/requisition.py). Every change is validated and audited with before / after; the
category of the item is an ABAC dimension (action CATALOGUE_MANAGE), so a category manager maintains only the categories assigned to them.

The same rules serve the API (/v1/catalogue-items) and the CSV loader (tools/load_catalogue.py, ``upsert``).
"""
import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import CatalogueItem, Contract, Material, Supplier
from app.pic.platform import abac, audit
from app.pic.platform.errors import Problem, illegal_transition, not_found, rule_violation
from app.pic.platform.serialize import jsonable, row
from app.pic.services.common import principal, supplier_ref

RULE = "M04-CATALOGUE"
GST_SLABS = {Decimal(x) for x in ("0", "0.1", "0.25", "1.5", "3", "5", "6", "7.5", "12", "18", "28")}
HSN_RE = re.compile(r"^[0-9]{4}(?:[0-9]{2}){0,2}$")
SUPPLIER_REFUSED = ("BLOCKED", "EXITED", "REJECTED", "INACTIVE")
LIVE_CONTRACT = ("ACTIVE", "EXPIRING")
EDITABLE = ("description", "material_group", "category", "uom", "price_minor", "currency", "gst_rate", "hsn_code", "valid_from", "valid_to",
            "lead_time_days", "material", "contract")


def _bad(field: str, why: str) -> Problem:
    return Problem(422, "INVALID_FIELD", f"{field}: {why}", rule_ref=RULE, field=field)


def _text(value: Any, field: str, limit: int, upper: bool = False, required: bool = True) -> Optional[str]:
    text = str(value if value is not None else "").strip()
    if not text:
        if required:
            raise _bad(field, "is required")
        return None
    if len(text) > limit:
        raise _bad(field, f"at most {limit} characters")
    return text.upper() if upper else text


def _date(value: Any, field: str) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        raise _bad(field, "must be an ISO date (YYYY-MM-DD)")


def _normalise(session: Session, data: dict, current: Optional[CatalogueItem] = None) -> dict:
    """Validated, normalised field values (only the keys present in ``data``; on create every required field)."""
    out: dict = {}
    creating = current is None
    if creating or "description" in data:
        out["description"] = _text(data.get("description"), "description", 200)
    if creating or "material_group" in data:
        out["material_group"] = _text(data.get("material_group"), "material_group", 30, upper=True)
    if creating or "category" in data:
        out["category"] = _text(data.get("category") or (out.get("material_group") if creating else None), "category", 40, upper=True)
    if creating or "uom" in data:
        out["uom"] = _text(data.get("uom"), "uom", 5, upper=True)
    if creating or "currency" in data:
        currency = _text(data.get("currency") or "INR", "currency", 3, upper=True)
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise _bad("currency", "must be an ISO 4217 code such as INR")
        out["currency"] = currency
    if creating or "price_minor" in data:
        try:
            price = int(data.get("price_minor"))
        except (TypeError, ValueError):
            raise _bad("price_minor", "must be a whole number of minor units (paise)")
        if price <= 0:
            raise _bad("price_minor", "must be greater than zero")
        out["price_minor"] = price
    if creating or "gst_rate" in data:
        try:
            rate = Decimal(str(data.get("gst_rate") if data.get("gst_rate") is not None else 18))
        except (InvalidOperation, ValueError):
            raise _bad("gst_rate", "must be a number")
        if rate not in GST_SLABS:
            raise _bad("gst_rate", "is not a GST rate slab (0, 0.25, 3, 5, 12, 18, 28 ...)")
        out["gst_rate"] = rate
    if "hsn_code" in data:
        hsn = _text(data.get("hsn_code"), "hsn_code", 10, required=False)
        if hsn and not HSN_RE.match(hsn):
            raise _bad("hsn_code", "HSN/SAC must be 4, 6 or 8 digits")
        out["hsn_code"] = hsn
    if "lead_time_days" in data:
        if data.get("lead_time_days") in (None, ""):
            out["lead_time_days"] = None
        else:
            try:
                days = int(data["lead_time_days"])
            except (TypeError, ValueError):
                raise _bad("lead_time_days", "must be a whole number of days")
            if days < 0 or days > 730:
                raise _bad("lead_time_days", "must be between 0 and 730")
            out["lead_time_days"] = days
    for field in ("valid_from", "valid_to"):
        if field in data:
            out[field] = _date(data.get(field), field)
    start = out.get("valid_from", current.valid_from if current else None)
    end = out.get("valid_to", current.valid_to if current else None)
    if start and end and end < start:
        raise rule_violation("The price validity ends before it starts (valid_to < valid_from)", RULE)
    if "material" in data:
        number = _text(data.get("material"), "material", 30, required=False)
        material = None
        if number:
            material = session.execute(select(Material).where(Material.number == number)).scalar_one_or_none()
            if material is None:
                raise not_found("Material", number)
            if material.status != "ACTIVE":
                raise rule_violation(f"{material.number} is {material.status}; link only active materials", RULE)
        out["material_id"] = material.id if material else None
    return out


def _contract(session: Session, number: Optional[str], supplier_id: uuid.UUID) -> Optional[uuid.UUID]:
    number = (number or "").strip()
    if not number:
        return None
    contract = session.execute(select(Contract).where(Contract.number == number)).scalar_one_or_none()
    if contract is None:
        raise not_found("Contract", number)
    if contract.supplier_id != supplier_id:
        raise rule_violation(f"{contract.number} is with another supplier; a catalogue item is priced only by its own supplier's contract", RULE)
    if contract.status not in LIVE_CONTRACT:
        raise rule_violation(f"{contract.number} is {contract.status}; link only an active contract", RULE)
    return contract.id


def _overlapping(session: Session, supplier_id: uuid.UUID, part: str, start: Optional[date], end: Optional[date],
                 exclude: Optional[uuid.UUID] = None) -> Optional[CatalogueItem]:
    """An active item of the same supplier part whose validity overlaps (one price per part and day)."""
    for item in session.execute(select(CatalogueItem).where(CatalogueItem.supplier_id == supplier_id, CatalogueItem.supplier_part_no == part,
                                                            CatalogueItem.active.is_(True))).scalars():
        if exclude is not None and item.id == exclude:
            continue
        if (item.valid_to is None or start is None or item.valid_to >= start) and (end is None or item.valid_from is None or item.valid_from <= end):
            return item
    return None


def _snapshot(item: CatalogueItem) -> dict:
    return jsonable({k: getattr(item, k) for k in ("supplier_part_no", "description", "material_group", "category", "uom", "price_minor", "currency",
                                                   "gst_rate", "hsn_code", "valid_from", "valid_to", "lead_time_days", "material_id", "contract_id",
                                                   "active")})


def create(session: Session, *, supplier: str, supplier_part_no: str, **data) -> CatalogueItem:
    p = principal(session)
    sup = supplier_ref(session, supplier)
    if sup.status in SUPPLIER_REFUSED:
        raise rule_violation(f"{sup.code} is {sup.status}; it cannot be given catalogue items", RULE)
    part = _text(supplier_part_no, "supplier_part_no", 60)
    values = _normalise(session, data)
    abac.guard(session, "CATALOGUE_MANAGE", None, category=values["category"])
    values["contract_id"] = _contract(session, data.get("contract"), sup.id)
    clash = _overlapping(session, sup.id, part, values.get("valid_from"), values.get("valid_to"))
    if clash is not None:
        raise Problem(409, "CATALOGUE_ITEM_EXISTS", f"{sup.code} part {part} already has an active catalogue price for this period "
                      f"({clash.valid_from or 'open'} to {clash.valid_to or 'open'}); change that item or end its validity first", rule_ref=RULE,
                      item=str(clash.id))
    item = CatalogueItem(tenant_id=current_tenant(session), supplier_id=sup.id, supplier_part_no=part, active=True, created_by=p.user_id,
                         **values)
    session.add(item)
    session.flush()
    audit.record(session, "CATALOGUE_ITEM", item.id, "CREATED", object_ref=f"{sup.code}/{part}", after=_snapshot(item), rule_set_version=RULE)
    return item


def update(session: Session, item: CatalogueItem, changes: dict, reason: str) -> CatalogueItem:
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise rule_violation("Give the reason for the change", RULE)
    unknown = sorted(set(changes) - set(EDITABLE))
    if unknown:
        raise Problem(422, "FIELD_NOT_CHANGEABLE", f"{', '.join(unknown)} cannot be changed (supplier and part number identify the item; "
                      "create a new item instead)", rule_ref=RULE)
    if not changes:
        raise Problem(422, "NO_CHANGES", "Give the fields to change", rule_ref=RULE)
    abac.guard(session, "CATALOGUE_MANAGE", item)
    values = _normalise(session, changes, item)
    if "contract" in changes:
        values["contract_id"] = _contract(session, changes.get("contract"), item.supplier_id)
    if "category" in values:
        abac.guard(session, "CATALOGUE_MANAGE", None, category=values["category"])
    before = _snapshot(item)
    if item.active and ({"valid_from", "valid_to"} & set(values)):
        clash = _overlapping(session, item.supplier_id, item.supplier_part_no, values.get("valid_from", item.valid_from),
                             values.get("valid_to", item.valid_to), exclude=item.id)
        if clash is not None:
            raise Problem(409, "CATALOGUE_ITEM_EXISTS", f"Another active item of part {item.supplier_part_no} is valid in that period", rule_ref=RULE,
                          item=str(clash.id))
    for field, value in values.items():
        setattr(item, field, value)
    after = _snapshot(item)
    changed = {k: after[k] for k in after if after[k] != before[k]}
    if not changed:
        raise Problem(422, "NO_CHANGES", "The values equal the current catalogue item", rule_ref=RULE)
    audit.record(session, "CATALOGUE_ITEM", item.id, "CHANGED", object_ref=_ref(session, item), before={k: before[k] for k in changed},
                 after=changed, reason=reason, rule_set_version=RULE)
    return item


def set_active(session: Session, item: CatalogueItem, active: bool, reason: str) -> CatalogueItem:
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise rule_violation("Give the reason", RULE)
    abac.guard(session, "CATALOGUE_MANAGE", item)
    if item.active == active:
        raise illegal_transition("Catalogue item", _ref(session, item), "ACTIVE" if item.active else "INACTIVE",
                                 "reactivate" if active else "deactivate")
    if active:
        clash = _overlapping(session, item.supplier_id, item.supplier_part_no, item.valid_from, item.valid_to, exclude=item.id)
        if clash is not None:
            raise Problem(409, "CATALOGUE_ITEM_EXISTS", f"Another active item of part {item.supplier_part_no} is valid in that period", rule_ref=RULE)
    item.active = active
    audit.record(session, "CATALOGUE_ITEM", item.id, "REACTIVATED" if active else "DEACTIVATED", object_ref=_ref(session, item),
                 before={"active": not active}, after={"active": active}, reason=reason, rule_set_version=RULE)
    return item


def upsert(session: Session, row_data: dict, reason: str) -> tuple[str, CatalogueItem]:
    """CSV loader: create the item, or change the active one of the same supplier part whose validity starts on the same day."""
    sup = supplier_ref(session, row_data["supplier"])
    part = _text(row_data.get("supplier_part_no"), "supplier_part_no", 60)
    start = _date(row_data.get("valid_from"), "valid_from")
    existing = next((i for i in session.execute(select(CatalogueItem).where(
        CatalogueItem.supplier_id == sup.id, CatalogueItem.supplier_part_no == part, CatalogueItem.active.is_(True))).scalars()
        if i.valid_from == start), None)
    data = {k: v for k, v in row_data.items() if k not in ("supplier", "supplier_part_no")}
    if existing is None:
        return "CREATED", create(session, supplier=sup.code, supplier_part_no=part, **data)
    changes = {k: v for k, v in data.items() if k in EDITABLE}
    current = _snapshot(existing)
    probe = _normalise(session, changes, existing)
    if all(jsonable(v) == current.get(k) for k, v in probe.items()) and "contract" not in changes:
        return "UNCHANGED", existing
    return "CHANGED", update(session, existing, changes, reason)


def get(session: Session, ref: str) -> CatalogueItem:
    try:
        item = session.get(CatalogueItem, uuid.UUID(str(ref)))
    except ValueError:
        item = None
    if item is None:
        raise not_found("Catalogue item", ref)
    return item


def _ref(session: Session, item: CatalogueItem) -> str:
    supplier = session.get(Supplier, item.supplier_id)
    return f"{supplier.code if supplier else item.supplier_id}/{item.supplier_part_no}"


def view(session: Session, item: CatalogueItem, today: Optional[date] = None) -> dict:
    from app.pic.platform import clock

    today = today or clock.today()
    supplier = session.get(Supplier, item.supplier_id)
    material = session.get(Material, item.material_id) if item.material_id else None
    contract = session.get(Contract, item.contract_id) if item.contract_id else None
    valid = item.active and (item.valid_from is None or item.valid_from <= today) and (item.valid_to is None or item.valid_to >= today)
    return row(item, extra={"supplier": supplier.code if supplier else None, "supplierName": supplier.legal_name if supplier else None,
                            "material": material.number if material else None, "contract": contract.number if contract else None,
                            "offeredToday": bool(valid)})


def listing(session: Session, *, supplier: Optional[str] = None, active: Optional[bool] = None, q: Optional[str] = None,
            category: Optional[str] = None, limit: int = 200) -> list[dict]:
    query = select(CatalogueItem).order_by(CatalogueItem.supplier_part_no, CatalogueItem.valid_from)
    if supplier:
        query = query.where(CatalogueItem.supplier_id == supplier_ref(session, supplier).id)
    if active is not None:
        query = query.where(CatalogueItem.active.is_(active))
    if category:
        query = query.where(CatalogueItem.category == category.upper())
    if q:
        like = f"%{q.strip()}%"
        query = query.where(CatalogueItem.description.ilike(like) | CatalogueItem.supplier_part_no.ilike(like))
    return [view(session, i) for i in session.execute(query.limit(limit)).scalars()]
