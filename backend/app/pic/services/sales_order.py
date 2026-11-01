"""Sales-order account assignment on requisition and purchase order lines (BP M04: "account assignment: cost centre, WBS, internal
order, asset, sales order").

A line assigned to a customer order (account type ``SALES_ORDER``, code ``<order>`` or ``<order>/<line>``) is a make-to-order or
project purchase whose cost settles to that order. Rule ``SALES-ORDER-ACCOUNT`` controls the check against the customer order as it
is known to planning (``demand_element`` of type SALES_ORDER, M02):

* the order (and the line, when given) must exist as a sales-order demand element in the plant;
* a material line must be demanded by that order (same material);
* the quantity assigned to the order by all live requisitions must not exceed its demand (plus ``overAssignmentTolerancePct``);
* budget: a budget for ``SALES_ORDER:<order>`` is checked and committed like any cost object (soft stop unless rule BUDGET makes
  it hard); without a budget the cost settles to the order and nothing is committed (``COMMITMENT_IF_BUDGETED``)."""
import re
import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.models import DemandElement, PrLine, Requisition
from app.pic.platform.errors import Problem
from app.pic.platform.money import D
from app.pic.services import p2p_rules

TYPE = "SALES_ORDER"
KEY = "SALES-ORDER-ACCOUNT"
CODE = re.compile(r"^([A-Z0-9][A-Z0-9-]{1,28}?)(?:/(\d{1,6}))?$")
LIVE_STATUSES_EXCLUDED = ("CANCELLED", "REJECTED")


def parse(code: Optional[str]) -> tuple[str, Optional[str]]:
    match = CODE.match((code or "").strip().upper())
    if not match:
        raise Problem(422, "INVALID_SALES_ORDER", f"'{code}' is not a sales order reference; use <order> or <order>/<line> (e.g. SO-88120/10)",
                      rule_ref=KEY)
    return match.group(1), match.group(2)


def demand(session: Session, order: str, line: Optional[str], plant: str, material_id: Optional[uuid.UUID]) -> list[DemandElement]:
    refs = [f"{order}/{line}"] if line else [order]
    query = select(DemandElement).where(DemandElement.type == TYPE, func.upper(DemandElement.reference).in_(refs), DemandElement.plant == plant)
    if material_id is not None:
        query = query.where(DemandElement.material_id == material_id)
    return session.execute(query).scalars().all()


def assigned_qty(session: Session, code: str, material_id: Optional[uuid.UUID], exclude_line_id: Optional[uuid.UUID] = None) -> Decimal:
    query = select(func.coalesce(func.sum(PrLine.qty), 0)).join(Requisition, Requisition.id == PrLine.requisition_id).where(
        PrLine.account_assignment_type == TYPE, func.upper(PrLine.account_assignment_code) == code.strip().upper(),
        Requisition.status.not_in(LIVE_STATUSES_EXCLUDED))
    if material_id is not None:
        query = query.where(PrLine.material_id == material_id)
    if exclude_line_id is not None:
        query = query.where(PrLine.id != exclude_line_id)
    return D(session.execute(query).scalar_one())


def check(session: Session, *, code: Optional[str], plant: str, material_id: Optional[uuid.UUID], qty: Decimal,
          exclude_line_id: Optional[uuid.UUID] = None, company_code: Optional[str] = None) -> dict:
    """Validate a SALES_ORDER assignment; returns the facts (demanded / already assigned / free) or raises 422."""
    rule = p2p_rules.rule(session, KEY, company_code=company_code, plant=plant)
    order, line = parse(code)
    if not rule.body.get("enabled", True):
        return {"order": order, "line": line, "checked": False, "rule": rule.ref}
    material_filter = material_id if rule.body.get("requireMaterialMatch", True) else None
    elements = demand(session, order, line, plant, material_filter)
    if rule.body.get("requireDemandElement", True) and not elements:
        anywhere = demand(session, order, line, plant, None)
        why = (f"{order}{'/' + line if line else ''} has no demand for this material in plant {plant}" if anywhere
               else f"Sales order {order}{'/' + line if line else ''} is not known in plant {plant}")
        raise Problem(422, "SALES_ORDER_NOT_FOUND", f"{why}; account assignment to a sales order needs the customer order in planning",
                      rule_ref=rule.ref, salesOrder=order, salesOrderLine=line)
    demanded = sum((e.qty for e in elements), Decimal(0))
    already = assigned_qty(session, f"{order}/{line}" if line else order, material_filter, exclude_line_id)
    free = demanded - already
    tolerance = D(rule.body.get("overAssignmentTolerancePct", 0))
    if elements and D(qty) > max(free * (1 + tolerance / 100), Decimal(0)):
        raise Problem(422, "SALES_ORDER_OVER_ASSIGNED",
                      f"{order}{'/' + line if line else ''} demands {demanded.normalize():f} and {already.normalize():f} is already assigned to "
                      f"requisitions; {D(qty).normalize():f} more exceeds it", rule_ref=rule.ref, salesOrder=order, demandedQty=str(demanded),
                      assignedQty=str(already), requestedQty=str(qty))
    return {"order": order, "line": line, "checked": True, "demandedQty": str(demanded), "assignedQty": str(already), "freeQty": str(free),
            "rule": rule.ref}
