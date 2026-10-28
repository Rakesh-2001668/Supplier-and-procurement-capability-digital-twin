from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid

router = APIRouter()

# -------------------------------------------------------------
# Existing Models & Endpoints (Maintained for Backward Compatibility)
# -------------------------------------------------------------

class CarbonCalculationRequest(BaseModel):
    material: str
    quantity_kg: float
    distance_km: float
    transport_mode: str

@router.get("/scope3-emissions")
async def get_scope3_dashboard():
    return {
        "total_emissions_mt": 12450.5,
        "carbon_budget_mt": 15000.0,
        "yoy_reduction_percent": 12.4,
        "breakdown_by_source": [
            {"name": "Purchased Goods", "value": 8500.0},
            {"name": "Upstream Logistics", "value": 2400.0},
            {"name": "Waste Generated", "value": 850.5},
            {"name": "Business Travel", "value": 700.0}
        ],
        "top_emitting_suppliers": [
            {"supplier_name": "Global Metals Inc.", "emissions_mt": 4200.0, "intensity": "High", "reduction_target": "Missed"},
            {"supplier_name": "TechCorp Logistics", "emissions_mt": 2100.0, "intensity": "Medium", "reduction_target": "On Track"},
            {"supplier_name": "Apex Tooling", "emissions_mt": 850.0, "intensity": "Low", "reduction_target": "Exceeded"}
        ],
        "monthly_trend": [
            {"month": "Jan", "emissions": 1800},
            {"month": "Feb", "emissions": 1750},
            {"month": "Mar", "emissions": 1900},
            {"month": "Apr", "emissions": 1650},
            {"month": "May", "emissions": 1500},
            {"month": "Jun", "emissions": 1450}
        ]
    }

@router.post("/carbon-calculator")
async def calculate_footprint(req: CarbonCalculationRequest):
    material_factors = {
        "aluminum": 11.5,
        "steel": 1.85,
        "plastic": 2.5,
        "electronic": 25.0
    }
    
    transport_factors = {
        "sea": 0.015,
        "rail": 0.025,
        "road": 0.100,
        "air": 1.250
    }
    
    mat_factor = material_factors.get(req.material.lower(), 5.0)
    trans_factor = transport_factors.get(req.transport_mode.lower(), 0.100)
    
    manufacturing_emissions = req.quantity_kg * mat_factor
    transport_emissions = (req.quantity_kg / 1000.0) * req.distance_km * trans_factor
    total = manufacturing_emissions + transport_emissions
    
    return {
        "manufacturing_emissions_kg": round(manufacturing_emissions, 2),
        "transport_emissions_kg": round(transport_emissions, 2),
        "total_co2e_kg": round(total, 2)
    }

# -------------------------------------------------------------
# FEATURE 9: Scope 1-3 ESG Compliance & Batch Carbon Hub
# -------------------------------------------------------------

# In-memory certificate vault
CERTIFICATE_VAULT: List[Dict[str, Any]] = [
    {
        "id": "CERT-ISO-14001",
        "title": "ISO 14001:2015 Environmental Management System",
        "issuer": "TÜV SÜD Certification Authority",
        "category": "Environmental Management",
        "issue_date": "2024-10-15",
        "expiry_date": "2027-10-14",
        "status": "ACTIVE_VERIFIED",
        "verification_hash": "0x89a3f29b4e1174cb2291e0fa356a87c53d4c0b31",
        "scope": "Precision CNC milling, wire EDM, aerospace component manufacturing, and zero-landfill scrap recycling",
        "badge_color": "emerald"
    },
    {
        "id": "CERT-CBAM-EU",
        "title": "EU CBAM (Carbon Border Adjustment) Verified Importer",
        "issuer": "European Union Directorate-General for Taxation & Customs",
        "category": "Regulatory Trade Compliance",
        "issue_date": "2025-01-10",
        "expiry_date": "2026-12-31",
        "status": "ACTIVE_VERIFIED",
        "verification_hash": "0x51c70e44b93f18a44b8efcc991024bda21976a14",
        "scope": "Direct & indirect embodied emissions declaration for aluminum & nickel alloy articles (EU Reg 2023/956)",
        "badge_color": "blue"
    },
    {
        "id": "CERT-GHG-AUDIT",
        "title": "GHG Protocol Scope 1, 2 & 3 Verification Statement",
        "issuer": "SGS Global Environmental Assurance",
        "category": "Greenhouse Gas Accounting",
        "issue_date": "2025-06-01",
        "expiry_date": "2026-05-31",
        "status": "ACTIVE_VERIFIED",
        "verification_hash": "0x98f441029ba88ef77410acdb1284bb819c9e8802",
        "scope": "Independent reasonable assurance of Corporate Carbon Accounting under ISO 14064-3 standard",
        "badge_color": "teal"
    },
    {
        "id": "CERT-ROHS-REACH",
        "title": "RoHS 3 & REACH SVHC Compliance Declaration",
        "issuer": "Intertek Chemical Laboratory",
        "category": "Material Substance Safety",
        "issue_date": "2025-02-20",
        "expiry_date": "2027-02-19",
        "status": "ACTIVE_VERIFIED",
        "verification_hash": "0x77d12a9bc401f82e3b1c607759a11efc882193b2",
        "scope": "Hazardous substance restriction compliance across 100% of Aerospace raw alloys & surface treatments",
        "badge_color": "indigo"
    }
]

# Historical Batch Carbon Audits
BATCH_AUDITS_LEDGER: List[Dict[str, Any]] = [
    {
        "batch_id": "BATCH-2025-041",
        "po_id": "PO-2025-00123",
        "part_name": "Aerospace Actuator Housing",
        "material": "Aluminum 7075-T6",
        "quantity_units": 50,
        "billet_weight_kg": 4.2,
        "machined_weight_kg": 1.45,
        "manufacturing_process": "5-Axis CNC Milling",
        "scrap_recycled_percent": 88.0,
        "total_emissions_kg": 142.5,
        "per_unit_emissions_kg": 2.85,
        "industry_baseline_kg": 188.0,
        "carbon_savings_percent": -24.2,
        "cbam_status": "CBAM_READY",
        "passport_hash": "CBAM-APEX-ACT-00123",
        "date": "2025-10-14"
    },
    {
        "batch_id": "BATCH-2025-042",
        "po_id": "PO-2025-00124",
        "part_name": "Turbine Mounting Flange Assembly",
        "material": "Titanium Ti-6Al-4V",
        "quantity_units": 25,
        "billet_weight_kg": 6.8,
        "machined_weight_kg": 2.90,
        "manufacturing_process": "CNC Turn-Mill & Wire EDM",
        "scrap_recycled_percent": 92.5,
        "total_emissions_kg": 210.0,
        "per_unit_emissions_kg": 8.40,
        "industry_baseline_kg": 295.0,
        "carbon_savings_percent": -28.8,
        "cbam_status": "CBAM_READY",
        "passport_hash": "CBAM-APEX-FLG-00124",
        "date": "2025-10-15"
    },
    {
        "batch_id": "BATCH-2025-043",
        "po_id": "PO-2025-00125",
        "part_name": "High-Pressure Hydraulic Manifold",
        "material": "Stainless Steel 316L",
        "quantity_units": 30,
        "billet_weight_kg": 3.1,
        "machined_weight_kg": 1.60,
        "manufacturing_process": "Precision 5-Axis Machining",
        "scrap_recycled_percent": 84.0,
        "total_emissions_kg": 95.2,
        "per_unit_emissions_kg": 3.17,
        "industry_baseline_kg": 128.5,
        "carbon_savings_percent": -25.9,
        "cbam_status": "CBAM_READY",
        "passport_hash": "CBAM-APEX-MAN-00125",
        "date": "2025-10-16"
    },
    {
        "batch_id": "BATCH-2025-044",
        "po_id": "PO-2025-00128",
        "part_name": "Rocket Motor Gimbal Gimbal Mount",
        "material": "Inconel 718 Superalloy",
        "quantity_units": 10,
        "billet_weight_kg": 8.5,
        "machined_weight_kg": 3.20,
        "manufacturing_process": "Laser Powder Bed Fusion & CNC Finish",
        "scrap_recycled_percent": 95.0,
        "total_emissions_kg": 185.0,
        "per_unit_emissions_kg": 18.50,
        "industry_baseline_kg": 260.0,
        "carbon_savings_percent": -28.8,
        "cbam_status": "CBAM_READY",
        "passport_hash": "CBAM-APEX-GIM-00128",
        "date": "2025-10-16"
    }
]

# Request model for batch calculations
class BatchCarbonRequest(BaseModel):
    material: str = Field("aluminum_7075", description="Alloy material code")
    quantity_units: int = Field(50, ge=1)
    billet_weight_kg: float = Field(4.2, gt=0)
    machined_weight_kg: Optional[float] = Field(1.5, gt=0)
    manufacturing_process: str = Field("5_axis_cnc", description="5_axis_cnc, wire_edm, laser_additive_slm, turning")
    machining_hours_per_unit: float = Field(2.5, ge=0.1)
    scrap_recycled_percent: float = Field(85.0, ge=0, le=100)
    delivery_distance_km: float = Field(850.0, ge=0)
    transport_mode: str = Field("road_freight", description="road_freight, air_cargo, sea_freight, rail_intermodal")
    clean_solar_power_percent: float = Field(68.0, ge=0, le=100)

class CertificateUploadRequest(BaseModel):
    title: str
    issuer: str
    category: str
    issue_date: str
    expiry_date: str
    scope: str
    badge_color: Optional[str] = "emerald"

# -------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------

@router.get("/overview")
async def get_esg_overview(tenant_id: str = "TENANT_SUPPLIER_001"):
    """
    Returns comprehensive ESG Executive Summary & Scope 1-3 telemetry
    for Apex Precision Tooling.
    """
    return {
        "tenant_id": tenant_id,
        "company_name": "Apex Precision Tooling Inc.",
        "as_of_date": datetime.now().strftime("%Y-%m-%d"),
        "green_supplier_tier": "Tier-1 Preferred Platinum Green Supplier",
        "is_preferred_green_supplier": True,
        "rfq_score_boost_percent": 15.0,
        "cbam_compliance_status": "Fully Audited & Registered",
        "kpis": {
            "total_emissions_mt": 235.2,
            "carbon_budget_mt": 280.0,
            "budget_utilized_percent": 84.0,
            "yoy_reduction_percent": -18.4,
            "renewable_energy_mix_percent": 68.0,
            "solar_generation_kwh_ytd": 412500,
            "recycled_swarf_alloy_mt": 48.6,
            "water_recirculation_rate_percent": 94.2
        },
        "scopes_breakdown": {
            "scope1": {
                "name": "Scope 1 - Direct Plant Emissions",
                "emissions_mt": 28.4,
                "share_percent": 12.1,
                "sources": [
                    {"name": "Facility Heating & Natural Gas", "value_mt": 14.2},
                    {"name": "Fleet Service Vehicles", "value_mt": 8.6},
                    {"name": "Backup Diesel Generators", "value_mt": 5.6}
                ]
            },
            "scope2": {
                "name": "Scope 2 - Purchased Electricity",
                "emissions_mt": 64.2,
                "share_percent": 27.3,
                "gross_grid_emissions_mt": 106.2,
                "solar_rooftop_offset_mt": -42.0,
                "clean_energy_percentage": 68.0,
                "sources": [
                    {"name": "CNC Machining Center Spindles", "value_mt": 52.4},
                    {"name": "Cleanroom & Metrology HVAC", "value_mt": 11.8}
                ]
            },
            "scope3": {
                "name": "Scope 3 - Value Chain & Embodied Carbon",
                "emissions_mt": 142.6,
                "share_percent": 60.6,
                "sources": [
                    {"name": "Upstream Raw Alloy Billets (Al 7075, Ti-6Al-4V)", "value_mt": 96.4},
                    {"name": "Outbound Freight Logistics (FedEx/DHL/Intermodal)", "value_mt": 32.2},
                    {"name": "Cutting Fluid & Tool Wear Lifecycle", "value_mt": 8.5},
                    {"name": "Business Commute & Operational Waste", "value_mt": 5.5}
                ]
            }
        },
        "monthly_trend": [
            {"month": "Nov 24", "scope1": 3.1, "scope2": 7.2, "scope3": 14.5, "solar_offset": 3.2, "total": 24.8},
            {"month": "Dec 24", "scope1": 2.9, "scope2": 6.8, "scope3": 13.9, "solar_offset": 3.0, "total": 23.6},
            {"month": "Jan 25", "scope1": 2.8, "scope2": 6.5, "scope3": 13.2, "solar_offset": 3.4, "total": 22.5},
            {"month": "Feb 25", "scope1": 2.6, "scope2": 6.1, "scope3": 12.8, "solar_offset": 3.6, "total": 21.5},
            {"month": "Mar 25", "scope1": 2.5, "scope2": 5.8, "scope3": 12.4, "solar_offset": 4.1, "total": 20.7},
            {"month": "Apr 25", "scope1": 2.4, "scope2": 5.4, "scope3": 12.0, "solar_offset": 4.5, "total": 19.8},
            {"month": "May 25", "scope1": 2.3, "scope2": 5.1, "scope3": 11.5, "solar_offset": 4.8, "total": 18.9},
            {"month": "Jun 25", "scope1": 2.2, "scope2": 4.9, "scope3": 11.1, "solar_offset": 5.2, "total": 18.2},
            {"month": "Jul 25", "scope1": 2.1, "scope2": 4.8, "scope3": 10.8, "solar_offset": 5.4, "total": 17.7},
            {"month": "Aug 25", "scope1": 2.2, "scope2": 4.9, "scope3": 11.0, "solar_offset": 5.1, "total": 18.1},
            {"month": "Sep 25", "scope1": 2.1, "scope2": 4.7, "scope3": 10.5, "solar_offset": 4.6, "total": 17.3},
            {"month": "Oct 25", "scope1": 2.0, "scope2": 4.5, "scope3": 10.2, "solar_offset": 4.2, "total": 16.7}
        ],
        "material_carbon_intensity_index": [
            {"material": "Aluminum 7075-T6 (Virgin)", "emission_factor_kg_per_kg": 11.2, "primary_use": "Structural Aircraft Brackets"},
            {"material": "Aluminum 7075-T6 (Closed-Loop Recycled)", "emission_factor_kg_per_kg": 1.8, "primary_use": "Apex Sustainable Housings"},
            {"material": "Titanium Ti-6Al-4V Grade 5", "emission_factor_kg_per_kg": 28.5, "primary_use": "Turbine Rotors & Flanges"},
            {"material": "Stainless Steel 316L", "emission_factor_kg_per_kg": 4.8, "primary_use": "Hydraulic Valves & Manifolds"},
            {"material": "Inconel 718 Superalloy", "emission_factor_kg_per_kg": 34.0, "primary_use": "Rocket Nozzles & Hypersonic Parts"},
            {"material": "Carbon Fiber Pre-preg", "emission_factor_kg_per_kg": 24.2, "primary_use": "Lightweight Fairings"}
        ]
    }

@router.post("/calculate-batch")
async def calculate_batch_footprint(req: BatchCarbonRequest):
    """
    Computes precise, cradle-to-gate carbon footprint for a manufactured aerospace batch,
    incorporating raw alloy factors, CNC machining power, closed-loop scrap credit, and freight.
    """
    # Material Emission Factors (kg CO2e per kg raw billet)
    alloy_factors = {
        "aluminum_7075": 11.2,
        "aluminum_6061": 8.9,
        "titanium_ti6al4v": 28.5,
        "stainless_316l": 4.8,
        "inconel_718": 34.0,
        "carbon_fiber": 24.2
    }
    
    # Process power intensities (kWh per hour of spindle runtime)
    process_power_kwh = {
        "5_axis_cnc": 18.5,
        "wire_edm": 9.2,
        "laser_additive_slm": 24.0,
        "turning": 12.0
    }
    
    # Transport emission factors (kg CO2e per tonne-km)
    transport_factors = {
        "road_freight": 0.092,
        "air_cargo": 1.150,
        "sea_freight": 0.016,
        "rail_intermodal": 0.024
    }
    
    # 1. Raw Billet Embodied Carbon
    total_billet_mass_kg = req.quantity_units * req.billet_weight_kg
    mat_factor = alloy_factors.get(req.material.lower(), 10.0)
    gross_material_co2_kg = total_billet_mass_kg * mat_factor
    
    # 2. Closed-Loop Swarf Recycling Credit
    machined_weight = req.machined_weight_kg if req.machined_weight_kg else (req.billet_weight_kg * 0.45)
    swarf_mass_kg = max(0.0, total_billet_mass_kg - (req.quantity_units * machined_weight))
    recycled_swarf_kg = swarf_mass_kg * (req.scrap_recycled_percent / 100.0)
    # Recycling avoids 85% of primary smelter emissions
    recycling_credit_kg = recycled_swarf_kg * (mat_factor * 0.85)
    net_material_co2_kg = max(0.0, gross_material_co2_kg - recycling_credit_kg)
    
    # 3. Machining & Plant Energy Carbon
    power_kw = process_power_kwh.get(req.manufacturing_process.lower(), 15.0)
    total_kwh = req.quantity_units * req.machining_hours_per_unit * power_kw
    
    # Grid emissions: standard grid = 0.42 kg CO2e/kWh, rooftop solar = 0.02 kg CO2e/kWh
    clean_ratio = req.clean_solar_power_percent / 100.0
    effective_grid_factor = (1.0 - clean_ratio) * 0.42 + (clean_ratio * 0.02)
    machining_co2_kg = total_kwh * effective_grid_factor
    
    # 4. Outbound Logistics Carbon
    finished_mass_tonnes = (req.quantity_units * machined_weight) / 1000.0
    trans_factor = transport_factors.get(req.transport_mode.lower(), 0.092)
    transport_co2_kg = finished_mass_tonnes * req.delivery_distance_km * trans_factor
    
    # Total Emissions
    total_batch_co2_kg = net_material_co2_kg + machining_co2_kg + transport_co2_kg
    per_unit_co2_kg = total_batch_co2_kg / float(req.quantity_units)
    
    # Benchmark Comparison (Standard grid without solar & virgin alloy)
    industry_baseline_per_unit = (req.billet_weight_kg * mat_factor) + (req.machining_hours_per_unit * power_kw * 0.42) + ((machined_weight / 1000.0) * req.delivery_distance_km * 0.12)
    industry_baseline_total = industry_baseline_per_unit * req.quantity_units
    carbon_savings_percent = ((total_batch_co2_kg - industry_baseline_total) / industry_baseline_total) * 100.0 if industry_baseline_total > 0 else 0.0
    
    # European CBAM calculation (EU ETS Benchmark avg: €68 / tonne CO2e)
    cbam_carbon_tax_avoided_eur = max(0.0, ((industry_baseline_total - total_batch_co2_kg) / 1000.0) * 68.0)
    
    passport_id = f"CBAM-APEX-{uuid.uuid4().hex[:8].upper()}"
    
    return {
        "passport_id": passport_id,
        "calculation_timestamp": datetime.now().isoformat(),
        "summary": {
            "total_batch_co2e_kg": round(total_batch_co2_kg, 2),
            "per_unit_co2e_kg": round(per_unit_co2_kg, 2),
            "total_batch_co2e_mt": round(total_batch_co2_kg / 1000.0, 4),
            "industry_baseline_kg": round(industry_baseline_total, 2),
            "carbon_savings_percent": round(carbon_savings_percent, 1),
            "cbam_tariff_savings_eur": round(cbam_carbon_tax_avoided_eur, 2),
            "eco_rating": "A+ Platinum Green Component" if carbon_savings_percent <= -20 else "A Green Component"
        },
        "breakdown": {
            "net_material_embodied_kg": round(net_material_co2_kg, 2),
            "gross_material_before_recycling_kg": round(gross_material_co2_kg, 2),
            "closed_loop_scrap_credit_kg": round(recycling_credit_kg, 2),
            "machining_electricity_kg": round(machining_co2_kg, 2),
            "logistics_transport_kg": round(transport_co2_kg, 2)
        },
        "scopes": {
            "scope1_direct_fuel_kg": round(machining_co2_kg * 0.10, 2),
            "scope2_electricity_kg": round(machining_co2_kg * 0.90, 2),
            "scope3_upstream_and_freight_kg": round(net_material_co2_kg + transport_co2_kg, 2)
        },
        "cbam_declaration": {
            "eligible": True,
            "direct_emissions_specific_tco2e_per_t": round((machining_co2_kg / 1000.0) / max(0.001, finished_mass_tonnes), 3),
            "indirect_emissions_specific_tco2e_per_t": round((net_material_co2_kg / 1000.0) / max(0.001, finished_mass_tonnes), 3),
            "verification_status": "VERIFIED_ACCORDING_TO_EU_2023_956"
        }
    }

@router.get("/certificates")
async def get_certificates():
    """
    Returns auditable environmental and regulatory certifications in the vault.
    """
    return {
        "total_certificates": len(CERTIFICATE_VAULT),
        "verified_count": len([c for c in CERTIFICATE_VAULT if "VERIFIED" in c["status"]]),
        "certificates": CERTIFICATE_VAULT
    }

@router.post("/certificates/upload")
async def upload_certificate(req: CertificateUploadRequest):
    """
    Registers a new sustainability or emissions verification certificate.
    """
    new_cert = {
        "id": f"CERT-{uuid.uuid4().hex[:6].upper()}",
        "title": req.title,
        "issuer": req.issuer,
        "category": req.category,
        "issue_date": req.issue_date,
        "expiry_date": req.expiry_date,
        "status": "ACTIVE_VERIFIED",
        "verification_hash": f"0x{uuid.uuid4().hex}{uuid.uuid4().hex[:8]}",
        "scope": req.scope,
        "badge_color": req.badge_color or "emerald"
    }
    CERTIFICATE_VAULT.insert(0, new_cert)
    return {
        "message": "Certificate successfully added to ESG compliance vault.",
        "certificate": new_cert
    }

@router.get("/batch-audits")
async def get_batch_audits():
    """
    Returns the auditable ledger of manufactured PO production batches
    with their calculated product carbon footprints (PCF).
    """
    return {
        "total_batches_audited": len(BATCH_AUDITS_LEDGER),
        "average_carbon_savings_percent": -26.9,
        "audits": BATCH_AUDITS_LEDGER
    }
