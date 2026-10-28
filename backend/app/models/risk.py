from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.db import Base

class RiskAssessment(Base):
    __tablename__ = "risk_assessments"
    
    id = Column(String, primary_key=True, index=True)
    supplier_id = Column(String, ForeignKey("suppliers.id"))
    overall_score = Column(Float)
    financial_risk = Column(Float)
    geopolitical_risk = Column(Float)
    esg_risk = Column(Float)
    cyber_risk = Column(Float)
    operational_risk = Column(Float)
    last_assessed = Column(DateTime)
