from typing import Optional
from pydantic import BaseModel
from .base import TenantBaseSchema
from enum import Enum

class InvoiceStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    DISPUTED = "DISPUTED"

class SalesInvoiceSchema(TenantBaseSchema):
    id: str
    po_id: str
    buyer_tenant_id: str
    amount: float
    due_date: Optional[str] = None
    description: Optional[str] = None
    status: InvoiceStatus
    dispatch_status: str
    match_status: Optional[str] = "PENDING"

class PaymentSchema(TenantBaseSchema):
    id: str
    invoice_id: str
    amount: float
    due_date: Optional[str] = None
    description: Optional[str] = None
    status: str
