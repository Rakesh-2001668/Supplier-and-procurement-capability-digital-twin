from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Float, Text, Enum, ForeignKey
import enum
from .base import TenantBase

class InvoiceStatus(str, enum.Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    DISPUTED = "DISPUTED"

class MatchStatus(str, enum.Enum):
    PENDING = "PENDING"
    MATCHED = "MATCHED"
    DISCREPANCY = "DISCREPANCY"

class SalesInvoice(TenantBase):
    __tablename__ = "sales_invoices"
    
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    po_id: Mapped[str] = mapped_column(ForeignKey('purchase_orders.id'), nullable=False)
    buyer_tenant_id: Mapped[str] = mapped_column(String(50), nullable=False) # Linked to buyer
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    due_date: Mapped[str] = mapped_column(String(50), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[InvoiceStatus] = mapped_column(String(20), default=InvoiceStatus.PENDING)
    invoiced_quantity: Mapped[float] = mapped_column(Float, nullable=True, default=1.0)
    match_status: Mapped[MatchStatus] = mapped_column(String(20), nullable=True, default=MatchStatus.PENDING)
    dispatch_status: Mapped[str] = mapped_column(String(50), default="PENDING")

class Payment(TenantBase):
    __tablename__ = "payments"
    
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey('sales_invoices.id'))
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    due_date: Mapped[str] = mapped_column(String(50), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="COMPLETED")

class GoodsReceipt(TenantBase):
    __tablename__ = "goods_receipts"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    po_id: Mapped[str] = mapped_column(ForeignKey('purchase_orders.id'), nullable=False)
    received_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    received_amount_value: Mapped[float] = mapped_column(Float, nullable=False) # Value of received goods
    status: Mapped[str] = mapped_column(String(20), default="RECEIVED")
