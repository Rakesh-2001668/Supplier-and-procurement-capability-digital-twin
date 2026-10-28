from sqlalchemy import Column, String, Boolean
from app.core.db import Base

class Process(Base):
    __tablename__ = "ontology_processes"
    id = Column(String, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    description = Column(String)
    is_active = Column(Boolean, default=True)

class Material(Base):
    __tablename__ = "ontology_materials"
    id = Column(String, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    family = Column(String) # e.g., Aluminum, Steel, Plastic

class CertificationType(Base):
    __tablename__ = "ontology_certifications"
    id = Column(String, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    issuer = Column(String)
