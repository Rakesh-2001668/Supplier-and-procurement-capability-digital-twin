from pydantic import BaseModel
from typing import Optional
from .base import TenantBaseSchema
from enum import Enum

class RFQStatus(str, Enum):
    REQUESTED = "REQUESTED"
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

class POStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    ISSUED = "ISSUED"
    REJECTED = "REJECTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PRODUCTION = "IN_PRODUCTION"
    SHIPPED = "SHIPPED"
    GOODS_RECEIVED = "GOODS_RECEIVED"
    QUALITY_INSPECTED = "QUALITY_INSPECTED"
    PARTIAL = "PARTIAL"
    INVOICED = "INVOICED"
    COMPLETED = "COMPLETED"
    CHANGES_PROPOSED = "CHANGES_PROPOSED"

class OrderRequestSchema(TenantBaseSchema):
    id: str
    description: str
    target_supplier_id: Optional[str] = None
    status: RFQStatus

class QuotationSchema(TenantBaseSchema):
    id: str
    request_id: str
    supplier_tenant_id: str
    amount: float
    terms: str
    status: RFQStatus

class PurchaseOrderSchema(TenantBaseSchema):
    id: str
    po_number: str
    quotation_id: str
    supplier_tenant_id: str
    total_amount: float
    status: POStatus
