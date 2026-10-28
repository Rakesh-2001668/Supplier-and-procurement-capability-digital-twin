from sqlalchemy import Column, String, Float, ForeignKey, Boolean
from app.core.db import Base

class Plant(Base):
    __tablename__ = "graph_plants"
    id = Column(String, primary_key=True, index=True)
    supplier_id = Column(String, ForeignKey("suppliers.id"))
    name = Column(String)
    location = Column(String)
    region = Column(String)

class Machine(Base):
    __tablename__ = "graph_machines"
    id = Column(String, primary_key=True, index=True)
    plant_id = Column(String, ForeignKey("graph_plants.id"))
    name = Column(String)
    manufacturer = Column(String)
    status = Column(String)

class MachineCapability(Base):
    __tablename__ = "graph_machine_capabilities"
    id = Column(String, primary_key=True, index=True)
    machine_id = Column(String, ForeignKey("graph_machines.id"))
    process_id = Column(String, ForeignKey("ontology_processes.id"))
    material_id = Column(String, ForeignKey("ontology_materials.id"))
    max_tolerance = Column(Float)
    annual_capacity = Column(Float)

class SupplierDependency(Base):
    __tablename__ = "graph_supplier_dependencies"
    id = Column(String, primary_key=True, index=True)
    tier1_supplier_id = Column(String, ForeignKey("suppliers.id"))
    tier2_supplier_id = Column(String, ForeignKey("suppliers.id"))
    dependency_type = Column(String) # e.g., Raw Material, Logistics
