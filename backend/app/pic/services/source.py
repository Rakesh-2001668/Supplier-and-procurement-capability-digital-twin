"""Source determination (Technical Document §9.2).

Order: 1 active contract line → 2 quota arrangement (split by %, running counters)
→ 3 source list → 4 purchasing info record → 5 none (buyer queue).
Suppliers that are Blocked or not Qualified for the category are excluded.
"""
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import (
    Contract, ContractLine, InfoRecord, Material, PriceValidity, QuotaArrangement, QuotaLine, SourceList, Supplier,
)
from app.pic.services.common import category_status

ELIGIBLE = ("QUALIFIED", "PREFERRED")


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


def _eligible(session: Session, supplier_id: uuid.UUID, category: str, excluded: list) -> bool:
    status = category_status(session, supplier_id, category)
    if status not in ELIGIBLE:
        supplier = session.get(Supplier, supplier_id)
        excluded.append({"supplier": supplier.code, "status": status})
        return False
    return True


def _contract_lines(session: Session, material_id: uuid.UUID, plant: str, on: date):
    return session.execute(
        select(ContractLine, Contract).join(Contract, Contract.id == ContractLine.contract_id).where(
            ContractLine.material_id == material_id, ContractLine.plant == plant, Contract.status.in_(("ACTIVE", "EXPIRING")),
            Contract.valid_from <= on, Contract.valid_to >= on, ContractLine.released_qty < ContractLine.target_qty,
        )
    ).all()


def determine(session: Session, material: Material, plant: str, need_date: date, qty: Decimal,
              reserve: bool = False) -> Determination:
    """Find the source of supply. ``reserve`` updates running quota counters (PO creation only)."""
    excluded: list[dict] = []
    category = material.category

    quota = session.execute(select(QuotaArrangement).where(
        QuotaArrangement.material_id == material.id, QuotaArrangement.plant == plant,
        QuotaArrangement.valid_from <= need_date, QuotaArrangement.valid_to >= need_date)).scalar_one_or_none()
    contract_rows = _contract_lines(session, material.id, plant, need_date)

    # 1. Single active contract line (no quota split).
    if contract_rows and quota is None:
        line, contract = contract_rows[0]
        if _eligible(session, contract.supplier_id, category, excluded):
            validity = contract_price(session, line.id, need_date)
            supplier = session.get(Supplier, contract.supplier_id)
            return Determination("CONTRACT", [Allocation(contract.supplier_id, supplier.code, qty,
                                                         validity.unit_price_minor if validity else None, "CONTRACT",
                                                         contract.id, line.id, validity.id if validity else None)], excluded)

    # 2. Quota arrangement: split by share, prices from each supplier's contract.
    if quota is not None:
        quota_lines = session.execute(select(QuotaLine).where(QuotaLine.quota_id == quota.id)).scalars().all()
        eligible = [q for q in quota_lines if _eligible(session, q.supplier_id, category, excluded)]
        if eligible:
            total_share = sum(q.share for q in eligible)
            allocations, assigned = [], Decimal(0)
            for index, q in enumerate(eligible):
                share = q.share / total_share
                part = (qty - assigned) if index == len(eligible) - 1 else (qty * share).quantize(Decimal("1"))
                assigned += part
                if reserve:
                    q.allocated_qty = (q.allocated_qty or 0) + part
                supplier = session.get(Supplier, q.supplier_id)
                contract_line = next((l for l, c in contract_rows if c.id == q.contract_id), None)
                validity = contract_price(session, contract_line.id, need_date) if contract_line else None
                allocations.append(Allocation(
                    q.supplier_id, supplier.code, part, validity.unit_price_minor if validity else None,
                    "CONTRACT" if validity else "QUOTA", q.contract_id, contract_line.id if contract_line else None,
                    validity.id if validity else None, share=share,
                ))
            return Determination("QUOTA", allocations, excluded)

    # 3. Source list, 4. info record.
    sources = session.execute(select(SourceList).where(
        SourceList.material_id == material.id, SourceList.plant == plant,
        SourceList.valid_from <= need_date, SourceList.valid_to >= need_date).order_by(SourceList.fixed.desc())).scalars().all()
    for source in sources:
        if _eligible(session, source.supplier_id, category, excluded):
            info = session.execute(select(InfoRecord).where(InfoRecord.supplier_id == source.supplier_id,
                                                            InfoRecord.material_id == material.id, InfoRecord.plant == plant)).scalar_one_or_none()
            supplier = session.get(Supplier, source.supplier_id)
            return Determination("SOURCE_LIST", [Allocation(source.supplier_id, supplier.code, qty,
                                                            info.last_price_minor if info else None,
                                                            "INFO_RECORD" if info else "MANUAL",
                                                            lead_time_days=info.lead_time_days if info else None)], excluded)
    infos = session.execute(select(InfoRecord).where(InfoRecord.material_id == material.id, InfoRecord.plant == plant)
                            .order_by(InfoRecord.last_price_minor)).scalars().all()
    for info in infos:
        if _eligible(session, info.supplier_id, category, excluded):
            supplier = session.get(Supplier, info.supplier_id)
            return Determination("INFO_RECORD", [Allocation(info.supplier_id, supplier.code, qty, info.last_price_minor,
                                                            "INFO_RECORD", lead_time_days=info.lead_time_days)], excluded)
    return Determination("NONE", [], excluded)
