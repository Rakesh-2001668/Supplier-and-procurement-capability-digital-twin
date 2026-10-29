"""Source determination (Technical Document §9.2).

Order: 1 active contract line → 2 quota arrangement (split by %, running counters)
→ 3 source list → 4 purchasing info record → 5 none (buyer queue).
Suppliers that are Blocked or not Qualified for the category are excluded.

``determine`` reads through a lookup: by default one query per read (POs, PRs, conversions); an MRP run passes a
``Preloaded`` lookup that bulk-loads the same rows for one plant once, so the run does not query per planned order.
"""
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.orm import Session

from app.pic.models import (
    Contract, ContractLine, InfoRecord, Material, PriceValidity, QuotaArrangement, QuotaLine, SourceList, Supplier,
    SupplierCategoryStatus,
)
from app.pic.services.common import category_status

ELIGIBLE = ("QUALIFIED", "PREFERRED")
IN_CHUNK = 5000  # bind parameters per IN (...) list when bulk-loading


@dataclass
class Allocation:
    supplier_id: uuid.UUID
    supplier_code: str
    qty: Decimal
    unit_price_minor: Optional[int]
    price_source: str
    contract_id: Optional[uuid.UUID] = None
    contract_line_id: Optional[uuid.UUID] = None
    price_validity_id: Optional[uuid.UUID] = None
    lead_time_days: Optional[int] = None
    share: Optional[Decimal] = None

    def as_dict(self) -> dict:
        return {"supplier": self.supplier_code, "qty": str(self.qty), "unitPriceMinor": self.unit_price_minor,
                "priceSource": self.price_source, "contractId": str(self.contract_id) if self.contract_id else None,
                "share": str(self.share) if self.share is not None else None}


@dataclass
class Determination:
    method: str  # CONTRACT | QUOTA | SOURCE_LIST | INFO_RECORD | NONE
    allocations: list[Allocation] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"method": self.method, "allocations": [a.as_dict() for a in self.allocations], "excluded": self.excluded}


def contract_price(session: Session, contract_line_id: uuid.UUID, on: date) -> Optional[PriceValidity]:
    """Latest published validity period that covers the date. Index resets add periods; none are overwritten."""
    return session.execute(
        select(PriceValidity).where(PriceValidity.contract_line_id == contract_line_id, PriceValidity.published.is_(True),
                                    PriceValidity.valid_from <= on, PriceValidity.valid_to >= on)
        .order_by(PriceValidity.valid_from.desc(), PriceValidity.created_at.desc()).limit(1)
    ).scalar_one_or_none()


def _contract_lines(session: Session, material_id: uuid.UUID, plant: str, on: date):
    return session.execute(
        select(ContractLine, Contract).join(Contract, Contract.id == ContractLine.contract_id).where(
            ContractLine.material_id == material_id, ContractLine.plant == plant, Contract.status.in_(("ACTIVE", "EXPIRING")),
            Contract.valid_from <= on, Contract.valid_to >= on, ContractLine.released_qty < ContractLine.target_qty,
        )
    ).all()


# ---------------------------------------------------------------- data access
class Lookup:
    """The reads ``determine`` needs, one query each (the default)."""

    def __init__(self, session: Session):
        self.session = session

    def quota(self, material_id: uuid.UUID, plant: str, on: date) -> Optional[QuotaArrangement]:
        return self.session.execute(select(QuotaArrangement).where(
            QuotaArrangement.material_id == material_id, QuotaArrangement.plant == plant,
            QuotaArrangement.valid_from <= on, QuotaArrangement.valid_to >= on)).scalar_one_or_none()

    def contract_rows(self, material_id: uuid.UUID, plant: str, on: date) -> list:
        return _contract_lines(self.session, material_id, plant, on)

    def price(self, contract_line_id: uuid.UUID, on: date) -> Optional[PriceValidity]:
        return contract_price(self.session, contract_line_id, on)

    def quota_lines(self, quota_id: uuid.UUID) -> list:
        return self.session.execute(select(QuotaLine).where(QuotaLine.quota_id == quota_id)).scalars().all()

    def source_lists(self, material_id: uuid.UUID, plant: str, on: date) -> list:
        return self.session.execute(select(SourceList).where(
            SourceList.material_id == material_id, SourceList.plant == plant,
            SourceList.valid_from <= on, SourceList.valid_to >= on).order_by(SourceList.fixed.desc())).scalars().all()

    def info_record(self, supplier_id: uuid.UUID, material_id: uuid.UUID, plant: str):
        return self.session.execute(select(InfoRecord).where(InfoRecord.supplier_id == supplier_id,
                                                             InfoRecord.material_id == material_id, InfoRecord.plant == plant)).scalar_one_or_none()

    def info_records(self, material_id: uuid.UUID, plant: str) -> list:
        return self.session.execute(select(InfoRecord).where(InfoRecord.material_id == material_id, InfoRecord.plant == plant)
                                    .order_by(InfoRecord.last_price_minor)).scalars().all()

    def supplier(self, supplier_id: uuid.UUID) -> Optional[Supplier]:
        return self.session.get(Supplier, supplier_id)

    def category_status(self, supplier_id: uuid.UUID, category: str) -> str:
        return category_status(self.session, supplier_id, category)


def _chunks(values: list) -> Iterable[list]:
    for start in range(0, len(values), IN_CHUNK):
        yield values[start:start + IN_CHUNK]


class Preloaded(Lookup):
    """The same reads for one plant answered from rows loaded once (MRP runs: one query per table, not ~10 per order).

    ``material_ids`` limits the load to those materials (None: every material of the plant). Rows keep the database
    order of the per-call queries' ORDER BY; date filters are applied in Python with the same predicates. Reads for
    keys outside the loaded scope fall back to the per-call queries.
    """

    def __init__(self, session: Session, plant: str, material_ids: Optional[Iterable[uuid.UUID]] = None):
        super().__init__(session)
        self.plant = plant
        ids = None if material_ids is None else list(material_ids)
        self.scope = None if ids is None else set(ids)

        def scoped(query, column):
            if ids is None:
                yield from session.execute(query)
            else:
                for part in _chunks(ids):
                    yield from session.execute(query.where(column.in_(part)))

        self._quotas: dict = defaultdict(list)
        for q in scoped(select(QuotaArrangement).where(QuotaArrangement.plant == plant), QuotaArrangement.material_id):
            self._quotas[q[0].material_id].append(q[0])
        self._quota_lines: dict = defaultdict(list)
        quota_ids = [q.id for rows in self._quotas.values() for q in rows]
        self._quota_ids = set(quota_ids)
        for part in _chunks(quota_ids):
            for line in session.execute(select(QuotaLine).where(QuotaLine.quota_id.in_(part))).scalars():
                self._quota_lines[line.quota_id].append(line)
        self._contracts: dict = defaultdict(list)
        for row in scoped(select(ContractLine, Contract).join(Contract, Contract.id == ContractLine.contract_id).where(
                ContractLine.plant == plant, Contract.status.in_(("ACTIVE", "EXPIRING")),
                ContractLine.released_qty < ContractLine.target_qty), ContractLine.material_id):
            self._contracts[row[0].material_id].append(row)
        self._prices: dict = {}
        line_ids = [row[0].id for rows in self._contracts.values() for row in rows]
        for line_id in line_ids:
            self._prices[line_id] = []
        for part in _chunks(line_ids):
            for validity in session.execute(select(PriceValidity).where(
                    PriceValidity.contract_line_id.in_(part), PriceValidity.published.is_(True))
                    .order_by(PriceValidity.valid_from.desc(), PriceValidity.created_at.desc())).scalars():
                self._prices[validity.contract_line_id].append(validity)
        self._sources: dict = defaultdict(list)
        for row in scoped(select(SourceList.material_id, SourceList.supplier_id, SourceList.valid_from, SourceList.valid_to)
                          .where(SourceList.plant == plant).order_by(SourceList.fixed.desc()), SourceList.material_id):
            self._sources[row.material_id].append(row)
        self._infos: dict = defaultdict(list)
        self._info_by_supplier: dict = {}
        for row in scoped(select(InfoRecord.material_id, InfoRecord.supplier_id, InfoRecord.last_price_minor,
                                 InfoRecord.lead_time_days).where(InfoRecord.plant == plant)
                          .order_by(InfoRecord.last_price_minor), InfoRecord.material_id):
            self._infos[row.material_id].append(row)
            self._info_by_supplier[(row.supplier_id, row.material_id)] = row  # unique per supplier, material, plant
        supplier_ids = {c.supplier_id for rows in self._contracts.values() for _, c in rows}
        supplier_ids |= {line.supplier_id for rows in self._quota_lines.values() for line in rows}
        supplier_ids |= {row.supplier_id for rows in self._sources.values() for row in rows}
        supplier_ids |= {row.supplier_id for rows in self._infos.values() for row in rows}
        # Strong references: the session's identity map is weak, so session.get would query again per call.
        self._suppliers: dict = {}
        self._statuses: dict = {}
        for part in _chunks(sorted(supplier_ids)):
            for supplier in session.execute(select(Supplier).where(Supplier.id.in_(part))).scalars():
                self._suppliers[supplier.id] = supplier
            for row in session.execute(select(SupplierCategoryStatus.supplier_id, SupplierCategoryStatus.category,
                                              SupplierCategoryStatus.status).where(SupplierCategoryStatus.supplier_id.in_(part))):
                self._statuses[(row.supplier_id, row.category)] = row.status

    def _covers(self, material_id: uuid.UUID, plant: str) -> bool:
        return plant == self.plant and (self.scope is None or material_id in self.scope)

    def quota(self, material_id, plant, on):
        if not self._covers(material_id, plant):
            return super().quota(material_id, plant, on)
        found = [q for q in self._quotas.get(material_id, ()) if q.valid_from <= on and q.valid_to >= on]
        if len(found) > 1:  # as scalar_one_or_none on the per-call query
            raise MultipleResultsFound("Multiple rows were found when one or none was required")
        return found[0] if found else None

    def contract_rows(self, material_id, plant, on):
        if not self._covers(material_id, plant):
            return super().contract_rows(material_id, plant, on)
        return [row for row in self._contracts.get(material_id, ()) if row[1].valid_from <= on and row[1].valid_to >= on]

    def price(self, contract_line_id, on):
        if contract_line_id not in self._prices:
            return super().price(contract_line_id, on)
        return next((v for v in self._prices[contract_line_id] if v.valid_from <= on and v.valid_to >= on), None)

    def quota_lines(self, quota_id):
        if quota_id not in self._quota_ids:
            return super().quota_lines(quota_id)
        return self._quota_lines.get(quota_id, [])

    def source_lists(self, material_id, plant, on):
        if not self._covers(material_id, plant):
            return super().source_lists(material_id, plant, on)
        return [row for row in self._sources.get(material_id, ()) if row.valid_from <= on and row.valid_to >= on]

    def info_record(self, supplier_id, material_id, plant):
        if not self._covers(material_id, plant):
            return super().info_record(supplier_id, material_id, plant)
        return self._info_by_supplier.get((supplier_id, material_id))

    def info_records(self, material_id, plant):
        if not self._covers(material_id, plant):
            return super().info_records(material_id, plant)
        return self._infos.get(material_id, [])

    def supplier(self, supplier_id):
        found = self._suppliers.get(supplier_id)
        return found if found is not None else super().supplier(supplier_id)

    def category_status(self, supplier_id, category):
        if supplier_id not in self._suppliers:
            return super().category_status(supplier_id, category)
        # Same rule as services.common.category_status.
        if self._suppliers[supplier_id].status == "BLOCKED":
            return "BLOCKED"
        return self._statuses.get((supplier_id, category), "NOT_REGISTERED")


def _eligible(lookup: Lookup, supplier_id: uuid.UUID, category: str, excluded: list) -> bool:
    status = lookup.category_status(supplier_id, category)
    if status not in ELIGIBLE:
        supplier = lookup.supplier(supplier_id)
        excluded.append({"supplier": supplier.code, "status": status})
        return False
    return True


def determine(session: Session, material: Material, plant: str, need_date: date, qty: Decimal,
              reserve: bool = False, lookup: Optional[Lookup] = None) -> Determination:
    """Find the source of supply. ``reserve`` updates running quota counters (PO creation only)."""
    lookup = lookup or Lookup(session)
    excluded: list[dict] = []
    category = material.category

    quota = lookup.quota(material.id, plant, need_date)
    contract_rows = lookup.contract_rows(material.id, plant, need_date)

    # 1. Single active contract line (no quota split).
    if contract_rows and quota is None:
        line, contract = contract_rows[0]
        if _eligible(lookup, contract.supplier_id, category, excluded):
            validity = lookup.price(line.id, need_date)
            supplier = lookup.supplier(contract.supplier_id)
            return Determination("CONTRACT", [Allocation(contract.supplier_id, supplier.code, qty,
                                                         validity.unit_price_minor if validity else None, "CONTRACT",
                                                         contract.id, line.id, validity.id if validity else None)], excluded)

    # 2. Quota arrangement: split by share, prices from each supplier's contract.
    if quota is not None:
        quota_lines = lookup.quota_lines(quota.id)
        eligible = [q for q in quota_lines if _eligible(lookup, q.supplier_id, category, excluded)]
        if eligible:
            total_share = sum(q.share for q in eligible)
            allocations, assigned = [], Decimal(0)
            for index, q in enumerate(eligible):
                share = q.share / total_share
                part = (qty - assigned) if index == len(eligible) - 1 else (qty * share).quantize(Decimal("1"))
                assigned += part
                if reserve:
                    q.allocated_qty = (q.allocated_qty or 0) + part
                supplier = lookup.supplier(q.supplier_id)
                contract_line = next((l for l, c in contract_rows if c.id == q.contract_id), None)
                validity = lookup.price(contract_line.id, need_date) if contract_line else None
                allocations.append(Allocation(
                    q.supplier_id, supplier.code, part, validity.unit_price_minor if validity else None,
                    "CONTRACT" if validity else "QUOTA", q.contract_id, contract_line.id if contract_line else None,
                    validity.id if validity else None, share=share,
                ))
            return Determination("QUOTA", allocations, excluded)

    # 3. Source list, 4. info record.
    sources = lookup.source_lists(material.id, plant, need_date)
    for source in sources:
        if _eligible(lookup, source.supplier_id, category, excluded):
            info = lookup.info_record(source.supplier_id, material.id, plant)
            supplier = lookup.supplier(source.supplier_id)
            return Determination("SOURCE_LIST", [Allocation(source.supplier_id, supplier.code, qty,
                                                            info.last_price_minor if info else None,
                                                            "INFO_RECORD" if info else "MANUAL",
                                                            lead_time_days=info.lead_time_days if info else None)], excluded)
    infos = lookup.info_records(material.id, plant)
    for info in infos:
        if _eligible(lookup, info.supplier_id, category, excluded):
            supplier = lookup.supplier(info.supplier_id)
            return Determination("INFO_RECORD", [Allocation(info.supplier_id, supplier.code, qty, info.last_price_minor,
                                                            "INFO_RECORD", lead_time_days=info.lead_time_days)], excluded)
    return Determination("NONE", [], excluded)
