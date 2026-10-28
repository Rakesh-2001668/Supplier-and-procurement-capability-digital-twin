from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base

class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    status = Column(String, default="Pending")
    risk_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    on_time_delivery = Column(Float, default=100.0)
    defect_rate = Column(Float, default=0.0)
    invoice_accuracy = Column(Float, default=100.0)
    compliance_score = Column(Float, default=100.0)
    risk_level = Column(String, default="Low")
    spend = Column(Float, default=0.0)


    locations = relationship("SupplierLocation", back_populates="supplier")
    capabilities = relationship("SupplierCapability", back_populates="supplier")

class SupplierLocation(Base):
    __tablename__ = "supplier_locations"

    id = Column(Integer, primary_key=True, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"))
    address = Column(String)
    type = Column(String) # e.g., HQ, Factory

    supplier = relationship("Supplier", back_populates="locations")

class SupplierCapability(Base):
    __tablename__ = "supplier_capabilities"

    id = Column(Integer, primary_key=True, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"))
    category = Column(String)
    description = Column(String)
    certification = Column(String)

    supplier = relationship("Supplier", back_populates="capabilities")
