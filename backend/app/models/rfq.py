from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.db import Base

class RFQ(Base):
    __tablename__ = "rfqs"
    
    id = Column(String, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(String)
    category = Column(String)
    annual_volume = Column(Integer)
    target_price = Column(Float)
    target_award_date = Column(DateTime)
    status = Column(String, default="Draft") # Draft, Evaluating, Awarded, Closed
    priority = Column(String)

class RFQPart(Base):
    __tablename__ = "rfq_parts"
    
    id = Column(String, primary_key=True)
    rfq_id = Column(String, ForeignKey("rfqs.id"))
    part_number = Column(String)
    part_name = Column(String)
    material = Column(String)
    process = Column(String)
    annual_volume = Column(Integer)
    target_price = Column(Float)
