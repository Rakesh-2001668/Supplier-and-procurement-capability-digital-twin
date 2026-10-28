from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Enum
import enum
from .base import Base, TenantBase
import datetime
from sqlalchemy import DateTime
from sqlalchemy.sql import func

class TenantType(str, enum.Enum):
    BUYER = "BUYER"
    SUPPLIER = "SUPPLIER"

class Tenant(Base):
    __tablename__ = "tenants"
    
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    type: Mapped[TenantType] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=datetime.datetime.utcnow)

class User(TenantBase):
    __tablename__ = "users"
    
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)

from sqlalchemy import Float

class SupplierProfile(Base):
    __tablename__ = "supplier_profiles"
    
    tenant_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    description: Mapped[str] = mapped_column(String(1000), nullable=True)
    # External Data Integrations (Mocked D&B / EcoVadis data)
    financial_risk_score: Mapped[int] = mapped_column(nullable=True) # 0-100
    esg_score: Mapped[int] = mapped_column(nullable=True) # 0-100
    compliance_status: Mapped[str] = mapped_column(String(50), default="UNKNOWN") # COMPLIANT, FLAG, NON_COMPLIANT
    last_audit_date: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=True)
