from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Float, ForeignKey, Text, DateTime
from datetime import datetime, timezone
from .base import TenantBase

class InventoryItem(TenantBase):
    __tablename__ = "inventory_items"
    
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), default='General Components')
    unit: Mapped[str] = mapped_column(String(30), default='pcs')
    quantity_on_hand: Mapped[int] = mapped_column(Integer, default=0)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)
    min_threshold: Mapped[int] = mapped_column(Integer, default=50)
    max_capacity: Mapped[int] = mapped_column(Integer, default=5000)
    location: Mapped[str] = mapped_column(String(100), default='Warehouse A - Bay 01')
    status: Mapped[str] = mapped_column(String(50), default='IN_STOCK')

class StockTransaction(TenantBase):
    __tablename__ = "stock_transactions"
    
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    inventory_item_id: Mapped[str] = mapped_column(ForeignKey('inventory_items.id'), nullable=False)
    change_quantity: Mapped[int] = mapped_column(Integer, nullable=False) # Negative for deduction, Positive for addition
    reference_type: Mapped[str] = mapped_column(String(50), default='GOODS_IN') # 'GOODS_IN', 'GOODS_OUT', 'ADJUSTMENT'
    reference_id: Mapped[str] = mapped_column(String(50), nullable=True) # e.g. PO-2025-00045, WO-2026-9901
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    performed_by: Mapped[str] = mapped_column(String(100), default='Warehouse Logistics')
    balance_after: Mapped[int] = mapped_column(Integer, default=0)

class AdvanceShipNotice(TenantBase):
    __tablename__ = 'advance_ship_notices'
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    po_id: Mapped[str] = mapped_column(ForeignKey('purchase_orders.id'), nullable=False)
    carrier: Mapped[str] = mapped_column(String(100), nullable=True)
    tracking_number: Mapped[str] = mapped_column(String(100), nullable=True)
    expected_date: Mapped[str] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default='SHIPPED')
