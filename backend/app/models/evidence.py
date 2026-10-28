from sqlalchemy import Column, Integer, String, Float, ForeignKey
from app.core.db import Base

class Evidence(Base):
    __tablename__ = "evidence"
    
    id = Column(String, primary_key=True)
    supplier_id = Column(String, ForeignKey("suppliers.id"))
    document_type = Column(String)
    ai_status = Column(String)
    level = Column(String) # L1-L5
