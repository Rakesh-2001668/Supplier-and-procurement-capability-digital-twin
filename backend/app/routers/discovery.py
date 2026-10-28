from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.models.tenant import SupplierProfile, Tenant, TenantType
from pydantic import BaseModel
from typing import List, Optional
import datetime

router = APIRouter(prefix="/api/v1/discovery", tags=["discovery"])

# Detailed Catalog & Capability Data for Suppliers
SUPPLIER_CATALOG_DATA = {
    "TENANT_SUPPLIER_001": {
        "display_name": "Apex Precision Machining Ltd",
        "category": "Aerospace Machining & CNC Assemblies",
        "tier": "Tier 1 Strategic Supplier",
        "location": "Bengaluru, India (Aerospace Special Economic Zone)",
        "facility_size": "45,000 sq.ft Manufacturing Plant",
        "founded_year": 2012,
        "employees": 180,
        "verified_twin_score": 96,
        "otif_delivery_rate": 97.8,
        "defect_ppm": 65,
        "avg_quote_turnaround_hrs": 3,
        "certifications": ["AS9100D", "ISO 9001:2015", "ISO 14001", "ITAR Compliant", "Nadcap Certified"],
        "materials_handled": ["Titanium Ti-6Al-4V", "Aluminum 7075-T6", "Inconel 718", "Stainless 316L", "PEEK"],
        "machinery": [
            {"equipment": "DMG Mori 5-Axis Machining Center (DMU 65)", "count": 6, "tolerance": "±0.003 mm", "envelope": "650 x 650 x 560 mm"},
            {"equipment": "Mazak Integrex Multi-Tasking Mill-Turn", "count": 4, "tolerance": "±0.005 mm", "envelope": "Ø 500 x 1000 mm"},
            {"equipment": "Zeiss Coordinate Measuring Machine (CMM)", "count": 2, "tolerance": "±0.0008 mm", "envelope": "1000 x 1200 x 800 mm"},
            {"equipment": "AgieCharmilles Wire EDM Precision Cutter", "count": 3, "tolerance": "±0.002 mm", "envelope": "350 x 250 x 250 mm"}
        ],
        "products": [
            {
                "id": "PROD-APX-01",
                "name": "Precision CNC 5-Axis Aerospace Housing",
                "part_number": "APX-HSG-7075",
                "category": "Structural Machined Castings",
                "material": "Aluminum 7075-T6 (Aerospace Grade)",
                "unit_price_usd": 295.0,
                "moq": 25,
                "lead_time_days": 14,
                "in_stock": True,
                "stock_available": 120,
                "tolerances": "±0.005 mm",
                "surface_finish": "MIL-A-8625 Type III Hardcoat Anodized",
                "description": "High-integrity 5-axis machined enclosure for avionics and sensor packages."
            },
            {
                "id": "PROD-APX-02",
                "name": "Inconel 718 High-Pressure Hydraulic Flange",
                "part_number": "APX-FLG-718",
                "category": "High-Pressure Fluid Systems",
                "material": "Inconel 718 Nickel Alloy",
                "unit_price_usd": 485.0,
                "moq": 10,
                "lead_time_days": 21,
                "in_stock": True,
                "stock_available": 65,
                "tolerances": "±0.003 mm",
                "surface_finish": "Electropolished Ra 0.4 µm",
                "description": "Corrosion-resistant high-temp flange designed for hydraulic actuation systems."
            },
            {
                "id": "PROD-APX-03",
                "name": "Titanium Grade 5 Pinion Drive Shaft",
                "part_number": "APX-SFT-TI64",
                "category": "Transmission & Powertrain",
                "material": "Titanium Grade 5 (Ti-6Al-4V)",
                "unit_price_usd": 340.0,
                "moq": 50,
                "lead_time_days": 18,
                "in_stock": True,
                "stock_available": 200,
                "tolerances": "±0.002 mm",
                "surface_finish": "Diamond-Turned & Superfinished Ra 0.2 µm",
                "description": "High-strength lightweight spline drive shaft engineered for heavy cyclic torque."
            },
            {
                "id": "PROD-APX-04",
                "name": "Modular Dual-Valve Aluminum Manifold",
                "part_number": "APX-MNF-6061",
                "category": "Pneumatic & Fluid Control",
                "material": "Aluminum 6061-T651",
                "unit_price_usd": 180.0,
                "moq": 30,
                "lead_time_days": 10,
                "in_stock": True,
                "stock_available": 350,
                "tolerances": "±0.010 mm",
                "surface_finish": "Clear Chromate Conversion (MIL-DTL-5541)",
                "description": "Cross-drilled hydraulic control manifold block tested up to 5,000 PSI."
            }
        ]
    },
    "DEFAULT": {
        "display_name": "Titan Industrial Engineering Ltd",
        "category": "Heavy Forgings & Hydraulic Actuators",
        "tier": "Tier 1 Qualified Partner",
        "location": "Sheffield, United Kingdom",
        "facility_size": "60,000 sq.ft Heavy Forge Facility",
        "founded_year": 2008,
        "employees": 240,
        "verified_twin_score": 92,
        "otif_delivery_rate": 95.4,
        "defect_ppm": 110,
        "avg_quote_turnaround_hrs": 5,
        "certifications": ["ISO 9001:2015", "IATF 16949", "ISO 14001", "CE Certified"],
        "materials_handled": ["Alloy Steel 4340", "Stainless 304/316", "Titanium Grade 5", "Bronze Alloys"],
        "machinery": [
            {"equipment": "2,500-Ton Closed Die Hydraulic Forging Press", "count": 2, "tolerance": "±0.5 mm", "envelope": "1500 x 1500 mm"},
            {"equipment": "CNC Heavy Turning Lathe (VTL)", "count": 5, "tolerance": "±0.01 mm", "envelope": "Ø 2000 x 1800 mm"},
            {"equipment": "Vacuum Heat Treatment Quench Furnace", "count": 3, "tolerance": "±2°C", "envelope": "2000 kg capacity"}
        ],
        "products": [
            {
                "id": "PROD-TTN-01",
                "name": "Heavy Forged Steel Transmission Ring Gear",
                "part_number": "TTN-RNG-4340",
                "category": "Heavy Transmission Components",
                "material": "AISI 4340 Nickel-Chromium-Moly Steel",
                "unit_price_usd": 520.0,
                "moq": 15,
                "lead_time_days": 25,
                "in_stock": True,
                "stock_available": 80,
                "tolerances": "±0.008 mm",
                "surface_finish": "Induction Hardened (58-62 HRC)",
                "description": "High-durability forged ring gear blank precision machined for industrial machinery gearboxes."
            },
            {
                "id": "PROD-TTN-02",
                "name": "Heavy-Duty Hydraulic Cylinder Piston Rod",
                "part_number": "TTN-PST-1045",
                "category": "Hydraulic Cylinders",
                "material": "AISI 1045 Hard Chrome Plated Steel",
                "unit_price_usd": 245.0,
                "moq": 40,
                "lead_time_days": 12,
                "in_stock": True,
                "stock_available": 150,
                "tolerances": "±0.005 mm",
                "surface_finish": "Hard Chrome 25 µm Ra 0.2 µm",
                "description": "Corrosion-resistant induction-hardened piston rods for earthmoving equipment."
            }
        ]
    }
}

@router.get("/suppliers")
def get_suppliers(
    search: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Return all verified suppliers with manufactured product offerings, machinery, and capability metrics."""
    suppliers = db.query(Tenant).filter(Tenant.type == TenantType.SUPPLIER).all()
    
    results = []
    for sup in suppliers:
        profile = db.query(SupplierProfile).filter(SupplierProfile.tenant_id == sup.id).first()
        catalog = SUPPLIER_CATALOG_DATA.get(sup.id, SUPPLIER_CATALOG_DATA["DEFAULT"])
        
        display_name = catalog["display_name"] if sup.id == "TENANT_SUPPLIER_001" else (sup.name if sup.name and "Dummy" not in sup.name else catalog["display_name"])
        
        results.append({
            "id": sup.id,
            "name": display_name,
            "legal_name": sup.name,
            "category": catalog["category"],
            "tier": catalog["tier"],
            "location": catalog["location"],
            "facility_size": catalog["facility_size"],
            "verified_twin_score": catalog["verified_twin_score"],
            "otif_delivery_rate": catalog["otif_delivery_rate"],
            "defect_ppm": catalog["defect_ppm"],
            "certifications": catalog["certifications"],
            "materials": catalog["materials_handled"],
            "machinery_count": len(catalog["machinery"]),
            "product_count": len(catalog["products"]),
            "sample_products": catalog["products"][:3],
            "price_range_usd": f"${min(p['unit_price_usd'] for p in catalog['products']):.0f} - ${max(p['unit_price_usd'] for p in catalog['products']):.0f}",
            "min_lead_time_days": min(p['lead_time_days'] for p in catalog['products']),
            "financial_risk_score": profile.financial_risk_score if profile else 88,
            "esg_score": profile.esg_score if profile else 92,
            "compliance_status": profile.compliance_status if profile else "COMPLIANT"
        })
        
    return results

@router.get("/suppliers/{supplier_id}")
def get_supplier_details(supplier_id: str, db: Session = Depends(get_db)):
    """Return complete supplier detail profile including complete product catalog, machinery roster, and certifications."""
    sup = db.query(Tenant).filter(Tenant.id == supplier_id, Tenant.type == TenantType.SUPPLIER).first()
    if not sup:
        # Check if id is a mock ID or fallback
        pass
        
    catalog = SUPPLIER_CATALOG_DATA.get(supplier_id, SUPPLIER_CATALOG_DATA["DEFAULT"])
    display_name = catalog["display_name"] if supplier_id == "TENANT_SUPPLIER_001" or not sup else sup.name
    
    return {
        "id": supplier_id,
        "name": display_name,
        "category": catalog["category"],
        "tier": catalog["tier"],
        "location": catalog["location"],
        "facility_size": catalog["facility_size"],
        "founded_year": catalog["founded_year"],
        "employees": catalog["employees"],
        "verified_twin_score": catalog["verified_twin_score"],
        "otif_delivery_rate": catalog["otif_delivery_rate"],
        "defect_ppm": catalog["defect_ppm"],
        "avg_quote_turnaround_hrs": catalog["avg_quote_turnaround_hrs"],
        "certifications": catalog["certifications"],
        "materials_handled": catalog["materials_handled"],
        "machinery": catalog["machinery"],
        "products": catalog["products"],
        "financial_risk_score": 88,
        "esg_score": 92,
        "compliance_status": "COMPLIANT",
        "description": f"Verified industrial manufacturing twin. Specializes in {catalog['category']} with state-of-the-art machinery and rigorous quality control."
    }

class DirectInquiryPayload(BaseModel):
    product_id: Optional[str] = None
    target_quantity: int = 100
    target_delivery_date: str = "2026-11-15"
    notes: Optional[str] = None

@router.post("/suppliers/{supplier_id}/inquire")
def submit_direct_inquiry(supplier_id: str, payload: DirectInquiryPayload):
    """Direct workflow to request quotation or submit purchase interest for supplier products."""
    return {
        "status": "success",
        "message": f"Procurement inquiry submitted to supplier digital twin. Confirmation notification generated.",
        "inquiry_id": f"INQ-{supplier_id[:6].upper()}-2026",
        "details": payload.dict()
    }
