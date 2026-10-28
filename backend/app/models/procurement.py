from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Float, Text, Enum, ForeignKey, DateTime
from sqlalchemy.sql import func
import enum
from .base import TenantBase

class RFQStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"
    QUOTED = "QUOTED"
    NEGOTIATING = "NEGOTIATING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

class POStatus(str, enum.Enum):
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

class OrderRequest(TenantBase):
    __tablename__ = "order_requests"
    
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    description: Mapped[str] = mapped_column(Text)
    target_supplier_id: Mapped[str] = mapped_column(String(50), nullable=True) # Optional direct request
    status: Mapped[RFQStatus] = mapped_column(String(20), default=RFQStatus.REQUESTED)

class Quotation(TenantBase):
    __tablename__ = "quotations"
    
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey('order_requests.id'))
    supplier_tenant_id: Mapped[str] = mapped_column(String(50)) # Identifies which supplier gave the quote
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    terms: Mapped[str] = mapped_column(Text)
    status: Mapped[RFQStatus] = mapped_column(String(20), default=RFQStatus.QUOTED)

class NegotiationMessage(TenantBase):
    __tablename__ = "negotiation_messages"
    
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    quotation_id: Mapped[str] = mapped_column(ForeignKey('quotations.id'), nullable=False)
    sender_tenant_id: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_amount: Mapped[float] = mapped_column(Float, nullable=True)
    
    quotation = relationship("Quotation", backref="messages")

class PurchaseOrder(TenantBase):
    __tablename__ = "purchase_orders"
    
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    po_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True) # Non-repeatable constraint
    quotation_id: Mapped[str] = mapped_column(ForeignKey('quotations.id'), nullable=False)
    supplier_tenant_id: Mapped[str] = mapped_column(String(50), nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[POStatus] = mapped_column(String(20), default=POStatus.ISSUED)
    
class POApproval(TenantBase):
    __tablename__ = "po_approvals"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    po_id: Mapped[str] = mapped_column(ForeignKey("purchase_orders.id"))
    approver_id: Mapped[str] = mapped_column(String(50)) # User ID of the manager
    status: Mapped[str] = mapped_column(String(20), default="PENDING") # PENDING, APPROVED, REJECTED
    comments: Mapped[str] = mapped_column(Text, nullable=True)
    
    po = relationship("PurchaseOrder", backref="approvals")

class ContractStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SENT_FOR_SIGNATURE = "SENT_FOR_SIGNATURE"
    PARTIALLY_SIGNED = "PARTIALLY_SIGNED"
    FULLY_SIGNED = "FULLY_SIGNED"
    EXPIRED = "EXPIRED"

class Contract(TenantBase):
    __tablename__ = "contracts"
    
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    po_id: Mapped[str] = mapped_column(ForeignKey('purchase_orders.id'), nullable=True)
    supplier_tenant_id: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[ContractStatus] = mapped_column(String(30), default=ContractStatus.DRAFT)
    
    # Simple markdown or HTML string representing the legal document
    document_content: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Signatures (can be a base64 string or an IP/Timestamp trail)
    buyer_signature: Mapped[str] = mapped_column(String(255), nullable=True)
    supplier_signature: Mapped[str] = mapped_column(String(255), nullable=True)
    
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
