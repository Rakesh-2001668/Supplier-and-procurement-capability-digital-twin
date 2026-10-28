from sqlalchemy import Column, String, Float, ForeignKey, DateTime, JSON, Boolean
from app.core.db import Base
from datetime import datetime

class ScoringModel(Base):
    __tablename__ = "scoring_models"
    id = Column(String, primary_key=True, index=True)
    name = Column(String, unique=True)
    description = Column(String)

class ScoringModelVersion(Base):
    __tablename__ = "scoring_model_versions"
    id = Column(String, primary_key=True, index=True)
    model_id = Column(String, ForeignKey("scoring_models.id"))
    version_number = Column(String)
    rules_payload = Column(JSON) # The exact rules (gates, caps, discounts)
    is_active = Column(Boolean, default=False)
    published_at = Column(DateTime)

class SupplierScore(Base):
    __tablename__ = "supplier_scores"
    id = Column(String, primary_key=True, index=True)
    supplier_id = Column(String, ForeignKey("suppliers.id"))
    model_version_id = Column(String, ForeignKey("scoring_model_versions.id"))
    computed_at = Column(DateTime, default=datetime.utcnow)
    
    # The 12 Canonical Dimensions
    manufacturing = Column(Float)
    quality = Column(Float)
    engineering = Column(Float)
    capacity = Column(Float)
    technology = Column(Float)
    workforce = Column(Float)
    supply_chain = Column(Float)
    financial_resilience = Column(Float)
    digital_maturity = Column(Float)
    esg = Column(Float)
    industry_readiness = Column(Float)
    future_readiness = Column(Float)
    
    overall_score = Column(Float)
