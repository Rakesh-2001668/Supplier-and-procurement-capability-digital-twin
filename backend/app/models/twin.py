from sqlalchemy import Column, String, Float, ForeignKey, DateTime, JSON
from app.core.db import Base
from datetime import datetime

class TwinEvent(Base):
    __tablename__ = "twin_events"
    id = Column(String, primary_key=True, index=True)
    supplier_id = Column(String, ForeignKey("suppliers.id"))
    event_type = Column(String) # e.g., 'capability_gained', 'certification_expired'
    timestamp = Column(DateTime, default=datetime.utcnow)
    payload = Column(JSON) # Details of the event

class TwinState(Base):
    __tablename__ = "twin_states"
    id = Column(String, primary_key=True, index=True)
    supplier_id = Column(String, ForeignKey("suppliers.id"))
    state_dimension = Column(String) # Current, Historical, Emerging, Predicted
    computed_at = Column(DateTime, default=datetime.utcnow)
    data = Column(JSON) # The aggregated state data

class TwinSnapshot(Base):
    __tablename__ = "twin_snapshots"
    id = Column(String, primary_key=True, index=True)
    supplier_id = Column(String, ForeignKey("suppliers.id"))
    timestamp = Column(DateTime, default=datetime.utcnow)
    snapshot_data = Column(JSON) # Immutable point-in-time state for simulation
