"""ABAC read scope of the finance module (Technical Document SEC-AZ, Blueprint M10): the company codes and plants in the user's attributes
limit which invoices, payments, registers and accruals they can see, not only which commands they can run (platform/abac.py guards the
commands). A user without the attribute (or with "*") is unrestricted on that dimension, so existing users keep working; an object outside
the scope is "not found" (its existence is not revealed).
"""
import uuid
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.pic.models import Invoice, InvoiceLine, PoLine, PurchaseOrder
from app.pic.platform import abac
from app.pic.platform.errors import not_found


def scope(session: Session) -> dict:
    """{"company_code": list | None, "plant": list | None} for the principal of the session (None: unrestricted)."""
    return abac.read_scope(session)


def plant_filter(allowed: list[str]):
    """Invoice rows whose order (header or any line) is in one of the plants."""
    in_plants = select(PurchaseOrder.id).where(PurchaseOrder.plant.in_(allowed))
    via_lines = (select(InvoiceLine.invoice_id).join(PoLine, PoLine.id == InvoiceLine.po_line_id)
                 .join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(PurchaseOrder.plant.in_(allowed)))
    return or_(Invoice.po_id.in_(in_plants), Invoice.id.in_(via_lines))


def restrict_invoices(query, session: Session, current: Optional[dict] = None):
    current = current if current is not None else scope(session)
    if current["company_code"] is not None:
        query = query.where(Invoice.company_code.in_(current["company_code"]))
    if current["plant"] is not None:
        query = query.where(plant_filter(current["plant"]))
    return query


def companies(session: Session) -> Optional[list[str]]:
    """The company codes the principal may see, None when unrestricted."""
    return scope(session)["company_code"]


def invoice_visible(session: Session, invoice: Invoice) -> bool:
    current = scope(session)
    if current["company_code"] is None and current["plant"] is None:
        return True
    return session.execute(restrict_invoices(select(Invoice.id).where(Invoice.id == invoice.id), session, current)).first() is not None


def guard_invoice_read(session: Session, invoice: Invoice, ref) -> Invoice:
    if not invoice_visible(session, invoice):
        raise not_found("Invoice", ref)
    return invoice


def guard_company(session: Session, company_code: Optional[str]) -> None:
    allowed = companies(session)
    if company_code and allowed is not None and company_code not in allowed:
        raise not_found("Company code", company_code)
