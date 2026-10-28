from sqlalchemy.orm import declarative_base, Mapped, mapped_column
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
import datetime

Base = declarative_base()

class TenantBase(Base):
    __abstract__ = True
    
    tenant_id: Mapped[str] = mapped_column(String(50), ForeignKey('tenants.id'), nullable=False, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), onupdate=datetime.datetime.utcnow, nullable=True)
