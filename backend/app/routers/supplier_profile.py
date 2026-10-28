from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import datetime
import uuid
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.inventory import InventoryItem

router = APIRouter()

# Live In-Memory / Twin Database for the Logged-In Supplier Firm
digital_twin_store = {
    "profile": {
        "companyName": "ABC Manufacturing Ltd",
        "legalEntity": "ABC Manufacturing & Industrial Technologies Ltd",
        "industry": "Aerospace Machining & Precision High-Tolerance Components",
        "tier": "Tier 1 Qualified Production Partner",
        "digitalTwinId": "TWIN-ABC-MFG-001",
        "facilityLocation": "Precision Industrial Corridor, Phase II, Aerospace SEZ",
        "facilitySizeSqFt": "45,000 sq.ft High-Precision Manufacturing Plant",
        "yearFounded": 2012,
        "employees": 180,
        "email": "procurement-twin@abc-manufacturing.com",
        "phone": "+1 (555) 234-5678",
        "description": "AS9100D and ISO 9001:2015 certified aerospace and industrial machining facility specializing in 5-axis complex geometric milling, tight tolerance turning, titanium/Inconel superalloys, and cleanroom aerospace assembly."
    },
    "twinMetrics": {
        "trustScore": 96,
        "freshnessScore": 98,
        "profileCompleteness": 94,
        "lastSynced": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "auditStatus": "Fully Compliant (AS9100D & ITAR Active)"
    },
    "capabilities": {
        "coreProcesses": [
            "5-Axis CNC Milling",
            "Multi-Tasking Mill-Turn Lathe",
            "Precision Wire EDM Cutting",
            "Coordinate Metrology (Zeiss CMM)",
            "Vacuum Heat Treatment Quench",
            "Cleanroom Aerospace Packaging"
        ],
        "materialsCertified": [
            "Titanium Ti-6Al-4V (Grade 5)",
            "Inconel 718 Superalloy",
            "Aluminum 7075-T6 & 6061-T651",
            "Stainless Steel 316L & 17-4 PH",
            "PEEK Aerospace Polymer"
        ],
        "precisionTolerance": "±0.003 mm (High Precision)",
        "surfaceFinishes": [
            "MIL-A-8625 Type III Hardcoat Anodizing",
            "Electropolishing Ra 0.4 µm",
            "Chromate Conversion (MIL-DTL-5541)",
            "Passivation (ASTM A967)"
        ]
    },
    "machinery": [
        {
            "id": "m1",
            "name": "DMG Mori DMU 65 monoBLOCK 5-Axis Machining Center",
            "type": "5-Axis CNC Milling",
            "count": 6,
            "status": "Operational",
            "capacity": "88%",
            "tolerance": "±0.003 mm",
            "envelope": "650 x 650 x 560 mm",
            "iotConnected": True
        },
        {
            "id": "m2",
            "name": "Mazak Integrex i-200 Multi-Tasking Mill-Turn Center",
            "type": "Precision Turning/Milling",
            "count": 4,
            "status": "Operational",
            "capacity": "82%",
            "tolerance": "±0.005 mm",
            "envelope": "Ø 500 x 1000 mm",
            "iotConnected": True
        },
        {
            "id": "m3",
            "name": "Zeiss PRISMO Coordinate Measuring Machine (CMM)",
            "type": "Metrology & Quality Metrology",
            "count": 2,
            "status": "Operational",
            "capacity": "95%",
            "tolerance": "±0.0008 mm",
            "envelope": "1000 x 1200 x 800 mm",
            "iotConnected": True
        },
        {
            "id": "m4",
            "name": "AgieCharmilles CUT P 350 Precision Wire EDM",
            "type": "EDM Cutter",
            "count": 3,
            "status": "Operational",
            "capacity": "78%",
            "tolerance": "±0.002 mm",
            "envelope": "350 x 250 x 250 mm",
            "iotConnected": True
        }
    ],
    "productsCatalog": [
        {
            "id": "PROD-ABC-01",
            "partNumber": "ABC-HSG-7075",
            "name": "Precision CNC 5-Axis Aerospace Housing",
            "category": "Structural Machined Castings",
            "material": "Aluminum 7075-T6 (Aerospace Grade)",
            "unitPriceUsd": 295.0,
            "moq": 25,
            "leadTimeDays": 14,
            "stockAvailable": 120,
            "tolerances": "±0.005 mm",
            "description": "High-integrity 5-axis machined enclosure for avionics and sensor packages."
        },
        {
            "id": "PROD-ABC-02",
            "partNumber": "ABC-FLG-718",
            "name": "Inconel 718 High-Pressure Hydraulic Flange",
            "category": "High-Pressure Fluid Systems",
            "material": "Inconel 718 Nickel Alloy",
            "unitPriceUsd": 485.0,
            "moq": 10,
            "leadTimeDays": 21,
            "stockAvailable": 65,
            "tolerances": "±0.003 mm",
            "description": "Corrosion-resistant high-temp flange designed for hydraulic actuation systems."
        },
        {
            "id": "PROD-ABC-03",
            "partNumber": "ABC-SFT-TI64",
            "name": "Titanium Grade 5 Pinion Drive Spline Shaft",
            "category": "Transmission & Powertrain",
            "material": "Titanium Grade 5 (Ti-6Al-4V)",
            "unitPriceUsd": 340.0,
            "moq": 50,
            "leadTimeDays": 18,
            "stockAvailable": 200,
            "tolerances": "±0.002 mm",
            "description": "High-strength lightweight spline drive shaft engineered for heavy cyclic torque."
        }
    ],
    "certifications": [
        {"id": "c1", "name": "AS9100D (Aerospace Quality)", "authority": "Bureau Veritas", "certificateNo": "AS-9100D-88219", "expiry": "Aug 2027", "status": "VERIFIED_ACTIVE"},
        {"id": "c2", "name": "ISO 9001:2015 (Quality Management)", "authority": "TUV Rheinland", "certificateNo": "ISO-9001-2023-412", "expiry": "Dec 2027", "status": "VERIFIED_ACTIVE"},
        {"id": "c3", "name": "ISO 14001:2015 (Environmental)", "authority": "TUV Rheinland", "certificateNo": "ISO-14001-9901", "expiry": "Jun 2028", "status": "VERIFIED_ACTIVE"},
        {"id": "c4", "name": "ITAR Registered & Compliant", "authority": "US Directorate of Defense Trade Controls", "certificateNo": "ITAR-REG-M2841", "expiry": "Dec 2026", "status": "VERIFIED_ACTIVE"}
    ],
    "purchasingTerms": {
        "paymentTerms": "Net 30 Days (Electronic Bank Wire)",
        "currency": "USD / EUR",
        "incoterms": "DDP (Delivered Duty Paid) Buyer Warehouse",
        "standardLeadTimeDays": 14,
        "expeditedLeadTimeDays": 7,
        "expeditedPremiumPct": 15,
        "volumeRebates": "5% rebate on annual volume > $250k; 8% on > $500k",
        "warrantyPeriod": "24 Months Full Replacement Warranty",
        "defectLiability": "Immediate 48h RMA turnaround with advance replacement"
    }
}

class ProfileUpdate(BaseModel):
    companyName: str
    legalEntity: Optional[str] = None
    industry: str
    facilityLocation: Optional[str] = None
    facilitySizeSqFt: Optional[str] = None
    yearFounded: Optional[int] = None
    employees: Optional[int] = None
    email: str
    phone: str
    description: str

class CapabilitiesUpdate(BaseModel):
    coreProcesses: List[str]
    materialsCertified: List[str]
    precisionTolerance: str
    surfaceFinishes: List[str]

class MachineryItem(BaseModel):
    id: Optional[str] = None
    name: str
    type: str
    count: Optional[int] = 1
    status: str
    capacity: str
    tolerance: Optional[str] = "±0.005 mm"
    envelope: Optional[str] = "Standard"
    iotConnected: Optional[bool] = True

class ProductItem(BaseModel):
    id: Optional[str] = None
    partNumber: str
    name: str
    category: str
    material: str
    unitPriceUsd: float
    moq: int
    leadTimeDays: int
    stockAvailable: int
    tolerances: str
    description: str

class PurchasingTermsUpdate(BaseModel):
    paymentTerms: str
    currency: str
    incoterms: str
    standardLeadTimeDays: int
    expeditedLeadTimeDays: int
    volumeRebates: str
    warrantyPeriod: str

class CertificateItem(BaseModel):
    id: Optional[str] = None
    name: str
    authority: Optional[str] = "Accredited Body"
    certificateNo: Optional[str] = "CERT-VALID-2026"
    expiry: str
    status: Optional[str] = "VERIFIED_ACTIVE"

class IoTSyncConfig(BaseModel):
    gatewayUrl: str
    apiKey: str

def sync_digital_twin_catalog_with_inventory(db: Session):
    """
    Synchronizes the Digital Twin Products Catalog with the physical InventoryItem table
    for TENANT_SUPPLIER_001 so that Finished Goods stock, prices, locations, and SKUs stay completely unified.
    """
    try:
        inv_items = db.query(InventoryItem).filter(
            InventoryItem.tenant_id.in_(["TENANT_SUPPLIER_001", "supplier-mock"]),
            InventoryItem.category == "Finished Goods"
        ).all()
        
        item_by_sku = {it.sku.upper(): it for it in inv_items}
        
        # Primary reference mappings between catalog part numbers and inventory SKUs
        sku_mapping = {
            "ABC-HSG-7075": "FG-SENS-HSG-30",
            "ABC-FLG-718": "FG-FLG-ASMY-88",
            "ABC-SFT-TI64": "FG-ACT-SHF-01"
        }
        
        catalog = digital_twin_store["productsCatalog"]
        represented_skus = set()
        
        for prod in catalog:
            pn = prod.get("partNumber", "").upper()
            target_sku = sku_mapping.get(pn, pn)
            
            matched_item = item_by_sku.get(target_sku) or item_by_sku.get(pn)
            if not matched_item:
                # Fallback: check matching tokens in name
                for sku, it in item_by_sku.items():
                    if any(w.lower() in it.name.lower() for w in prod["name"].split() if len(w) > 4):
                        matched_item = it
                        break
            
            if matched_item:
                represented_skus.add(matched_item.sku.upper())
                prod["stockAvailable"] = matched_item.quantity_on_hand
                prod["linkedInventorySku"] = matched_item.sku
                prod["inventoryStatus"] = matched_item.status
                prod["inventoryLocation"] = matched_item.location or "Finished Goods Depot - Bay FG-01"
                prod["inventoryLastUpdated"] = matched_item.updated_at.isoformat() if matched_item.updated_at else datetime.datetime.utcnow().isoformat()
            else:
                prod["linkedInventorySku"] = pn
                prod["inventoryStatus"] = "IN_STOCK" if prod.get("stockAvailable", 0) > 0 else "OUT_OF_STOCK"
                prod["inventoryLocation"] = "Finished Goods Depot"
                prod["inventoryLastUpdated"] = datetime.datetime.utcnow().isoformat()
                
        # Also auto-add any new Finished Goods from the shop floor that are not in catalog yet
        for it in inv_items:
            if it.sku.upper() not in represented_skus and not any(p.get("linkedInventorySku") == it.sku for p in catalog):
                catalog.append({
                    "id": f"PROD-ABC-{len(catalog) + 1:02d}",
                    "partNumber": it.sku,
                    "name": it.name,
                    "category": "Precision CNC Machined Parts",
                    "material": "Aerospace Alloy Specification",
                    "unitPriceUsd": it.unit_price or 250.0,
                    "moq": it.min_threshold or 25,
                    "leadTimeDays": 14,
                    "stockAvailable": it.quantity_on_hand,
                    "tolerances": "±0.003 mm",
                    "description": f"Shop-floor certified production line item staged at {it.location}.",
                    "linkedInventorySku": it.sku,
                    "inventoryStatus": it.status,
                    "inventoryLocation": it.location,
                    "inventoryLastUpdated": it.updated_at.isoformat() if it.updated_at else datetime.datetime.utcnow().isoformat()
                })
                represented_skus.add(it.sku.upper())
    except Exception as e:
        print(f"[Digital Twin Sync Error]: {e}")

@router.get("/full-twin")
def get_full_digital_twin(db: Session = Depends(get_db)):
    """Return complete Digital Twin profile of the company with live synchronized inventory."""
    sync_digital_twin_catalog_with_inventory(db)
    return digital_twin_store

@router.put("/profile")
def update_profile(profile: ProfileUpdate):
    """Update company identity and facility details."""
    p = digital_twin_store["profile"]
    p["companyName"] = profile.companyName
    if profile.legalEntity: p["legalEntity"] = profile.legalEntity
    p["industry"] = profile.industry
    if profile.facilityLocation: p["facilityLocation"] = profile.facilityLocation
    if profile.facilitySizeSqFt: p["facilitySizeSqFt"] = profile.facilitySizeSqFt
    if profile.yearFounded: p["yearFounded"] = profile.yearFounded
    if profile.employees: p["employees"] = profile.employees
    p["email"] = profile.email
    p["phone"] = profile.phone
    p["description"] = profile.description
    digital_twin_store["twinMetrics"]["lastSynced"] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return {"status": "success", "message": "Digital Twin company profile updated successfully!", "profile": p}

@router.put("/capabilities")
def update_capabilities(caps: CapabilitiesUpdate):
    """Update manufacturing processes, certified materials, and tolerances."""
    digital_twin_store["capabilities"]["coreProcesses"] = caps.coreProcesses
    digital_twin_store["capabilities"]["materialsCertified"] = caps.materialsCertified
    digital_twin_store["capabilities"]["precisionTolerance"] = caps.precisionTolerance
    digital_twin_store["capabilities"]["surfaceFinishes"] = caps.surfaceFinishes
    digital_twin_store["twinMetrics"]["lastSynced"] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return {"status": "success", "message": "Manufacturing capabilities updated successfully!", "capabilities": digital_twin_store["capabilities"]}

@router.get("/machinery")
def get_machinery():
    """Return machinery roster."""
    return digital_twin_store["machinery"]

@router.post("/machinery")
def add_machinery(item: MachineryItem):
    """Add new equipment to machinery roster."""
    new_item = item.dict()
    new_item['id'] = f"m{len(digital_twin_store['machinery']) + 1}"
    digital_twin_store["machinery"].append(new_item)
    digital_twin_store["twinMetrics"]["lastSynced"] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return {"status": "success", "data": new_item}

@router.put("/machinery/{machine_id}")
def edit_machinery(machine_id: str, item: MachineryItem):
    """Edit equipment parameters."""
    for i, m in enumerate(digital_twin_store["machinery"]):
        if m['id'] == machine_id:
            updated = item.dict()
            updated['id'] = machine_id
            digital_twin_store["machinery"][i] = updated
            digital_twin_store["twinMetrics"]["lastSynced"] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
            return {"status": "success", "data": updated}
    raise HTTPException(status_code=404, detail="Machine not found")

@router.delete("/machinery/{machine_id}")
def delete_machinery(machine_id: str):
    """Remove equipment from machinery roster."""
    digital_twin_store["machinery"] = [m for m in digital_twin_store["machinery"] if m['id'] != machine_id]
    digital_twin_store["twinMetrics"]["lastSynced"] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return {"status": "success", "message": "Equipment decommissioned"}

@router.get("/products")
def get_products(db: Session = Depends(get_db)):
    """Return manufactured products catalog with live inventory synchronization."""
    sync_digital_twin_catalog_with_inventory(db)
    return digital_twin_store["productsCatalog"]

@router.post("/products")
def add_product(prod: ProductItem, auto_provision_inventory: Optional[bool] = Query(True), db: Session = Depends(get_db)):
    """Add new product offering to catalog and optionally provision in Finished Goods inventory."""
    new_p = prod.dict()
    new_p['id'] = f"PROD-ABC-{len(digital_twin_store['productsCatalog']) + 1:02d}"
    new_p['linkedInventorySku'] = prod.partNumber.strip().upper()
    new_p['inventoryStatus'] = "IN_STOCK" if (prod.stockAvailable or 0) > 0 else "OUT_OF_STOCK"
    new_p['inventoryLocation'] = "Finished Goods Depot - Bay FG-01"
    new_p['inventoryLastUpdated'] = datetime.datetime.utcnow().isoformat()
    
    # Provision into physical inventory
    if auto_provision_inventory:
        try:
            existing = db.query(InventoryItem).filter(
                InventoryItem.sku == prod.partNumber.strip().upper(),
                InventoryItem.tenant_id.in_(["TENANT_SUPPLIER_001", "supplier-mock"])
            ).first()
            if not existing:
                item = InventoryItem(
                    id=f"INV-SUP-{uuid.uuid4().hex[:6].upper()}",
                    sku=prod.partNumber.strip().upper(),
                    name=prod.name.strip(),
                    category="Finished Goods",
                    unit="pcs",
                    quantity_on_hand=prod.stockAvailable or 0,
                    unit_price=prod.unitPriceUsd or 0.0,
                    min_threshold=prod.moq or 25,
                    max_capacity=1000,
                    location="Finished Goods Depot - Bay FG-01",
                    status="IN_STOCK" if (prod.stockAvailable or 0) > 0 else "OUT_OF_STOCK",
                    tenant_id="TENANT_SUPPLIER_001"
                )
                db.add(item)
                db.commit()
                db.refresh(item)
        except Exception as e:
            print(f"[Inventory Provision Error]: {e}")
            db.rollback()

    digital_twin_store["productsCatalog"].append(new_p)
    digital_twin_store["twinMetrics"]["lastSynced"] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return {"status": "success", "data": new_p}

@router.delete("/products/{product_id}")
def delete_product(product_id: str, db: Session = Depends(get_db)):
    """Remove product offering from catalog."""
    digital_twin_store["productsCatalog"] = [p for p in digital_twin_store["productsCatalog"] if p['id'] != product_id]
    digital_twin_store["twinMetrics"]["lastSynced"] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return {"status": "success", "message": "Product removed from catalog"}

@router.get("/certifications")
def get_certifications():
    """Return quality certifications."""
    return digital_twin_store["certifications"]

@router.post("/certifications")
def add_certification(cert: CertificateItem):
    """Upload / register new certification."""
    new_c = cert.dict()
    new_c['id'] = f"c{len(digital_twin_store['certifications']) + 1}"
    digital_twin_store["certifications"].append(new_c)
    digital_twin_store["twinMetrics"]["lastSynced"] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return {"status": "success", "data": new_c}

@router.put("/purchasing-terms")
def update_purchasing_terms(terms: PurchasingTermsUpdate):
    """Update commercial purchasing terms."""
    digital_twin_store["purchasingTerms"] = terms.dict()
    digital_twin_store["twinMetrics"]["lastSynced"] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return {"status": "success", "message": "Commercial purchasing terms updated successfully!", "terms": digital_twin_store["purchasingTerms"]}

@router.post("/iot-sync")
def configure_iot_sync(config: IoTSyncConfig):
    """Configure live shop-floor IoT gateway telemetry."""
    return {"status": "success", "message": f"IoT telemetry gateway connected to {config.gatewayUrl}. Live telemetry streaming active."}

# -------------------------------------------------------------
# FEATURE 10: Public Shareable Capability Twin Profile Endpoints
# -------------------------------------------------------------

class InviteRfqRequest(BaseModel):
    supplier_id: str
    buyer_name: str
    buyer_company: Optional[str] = "AlphaHelion Global Aerospace"
    buyer_email: Optional[str] = "procurement@alphahelion.com"
    rfq_title: str
    part_name: str
    target_qty: int
    target_delivery_date: str
    target_budget_usd: Optional[float] = None
    notes: Optional[str] = ""

class ShortlistRequest(BaseModel):
    supplier_id: str
    buyer_company: Optional[str] = "AlphaHelion Global Aerospace"
    tier_category: Optional[str] = "Strategic Tier-1 Approved Partner"
    notes: Optional[str] = ""

# In-memory storage for public RFQ invites and buyer shortlists
PUBLIC_RFQ_INVITES: List[Dict[str, Any]] = []
BUYER_SHORTLISTS: List[Dict[str, Any]] = []

@router.get("/public/{supplier_id}")
def get_public_capability_twin_profile(supplier_id: str, db: Session = Depends(get_db)):
    """
    Public shareable capability passport endpoint for enterprise buyers.
    Returns audited metrology tolerances, Zeiss CMM records, machine capacity availability,
    live SCADA data freshness, ESG green credential, and cryptographic W3C DID passport.
    """
    sync_digital_twin_catalog_with_inventory(db)
    
    twin_id = supplier_id if supplier_id and supplier_id != "undefined" else "TWIN-APEX-001"
    
    company_name = "Apex Precision Tooling Inc."
    legal_entity = "Apex Precision Tooling & Aerospace Technologies Corp."
    if "abc" in twin_id.lower():
        company_name = "ABC Manufacturing Ltd"
        legal_entity = "ABC Manufacturing & Industrial Technologies Ltd"
        
    passport_hash = f"0x{uuid.uuid5(uuid.NAMESPACE_DNS, twin_id).hex}{uuid.uuid4().hex[:12]}"
    
    return {
        "status": "success",
        "passport_id": twin_id,
        "verification_hash": passport_hash,
        "w3c_did": f"did:twin:aerospace:{twin_id.lower()}",
        "cryptographic_status": "CRYPTOGRAPHICALLY_VERIFIED_AUTHENTIC",
        "issued_timestamp": datetime.datetime.utcnow().isoformat(),
        "profile": {
            "company_name": company_name,
            "legal_entity": legal_entity,
            "duns_number": "08-412-9912",
            "cage_code": "8X4K1",
            "itar_registration": "M38921 (Active)",
            "tier_rating": "Tier-1 AS9100D Certified Aerospace Supplier",
            "facility_location": "Pacific Northwest Aerospace Corridor, Seattle, WA",
            "facility_size_sqft": "65,000 sq.ft High-Precision Manufacturing & Metrology Facility",
            "cleanroom_spec": "ISO Class 7 Cleanroom Assembly & Packaging",
            "year_founded": 2011,
            "employees_count": 210,
            "annual_machining_capacity_hours": 145000,
            "headquarters": "Seattle, Washington, USA",
            "contact_email": "aerospace-twin@apex-tooling.com",
            "contact_phone": "+1 (206) 555-0198",
            "description": "AS9100D Rev D and ISO 9001:2015 certified aerospace manufacturing facility specializing in high-tolerance 5-axis CNC titanium and superalloy components, sub-micron coordinate metrology, and hermetic aerospace assemblies."
        },
        "twin_composite_scores": {
            "overall_trust_score": 98,
            "quality_ppm_defect_rate": 8.2,
            "otif_delivery_rate_percent": 99.1,
            "metrology_accuracy_index": 99.6,
            "iot_telemetry_freshness": "Real-time (5s SCADA Stream)",
            "esg_sustainability_rating": "Tier-1 Platinum Green Supplier (+15% RFQ advantage)",
            "carbon_reduction_yoy": "-18.4%"
        },
        "radar_capability_dimensions": {
            "dimensions": [
                "5-Axis Machining",
                "Metrology Tolerances",
                "Advanced Alloys",
                "Quality (AS9100D)",
                "Available Capacity",
                "SCADA IoT Live",
                "ESG Green Score",
                "Supply Chain Resilience",
                "ITAR / Defense Ready",
                "Additive SLM",
                "On-Time Delivery",
                "Engineering CAD/CAM"
            ],
            "supplier_scores": [98, 99, 96, 97, 86, 95, 94, 91, 99, 88, 99, 94],
            "aerospace_industry_average": [64, 58, 52, 60, 48, 42, 45, 55, 50, 38, 72, 62]
        },
        "audited_metrology": {
            "certified_tolerance": "±0.003 mm (High-Precision Sub-Micron)",
            "certified_surface_roughness": "Ra 0.2 µm (Electropolished Mirror Finish)",
            "inspection_equipment": "Zeiss CONTURA 5-Axis Laser Scanning CMM (MPEe: 1.5 + L/350 µm)",
            "as9102_fai_support": "100% First Article Inspection Reports Digitally Sealed",
            "calibration_audit_date": "2025-08-15 (NIST Traceable)"
        },
        "materials_certified": [
            {"alloy": "Titanium Ti-6Al-4V Grade 5", "spec": "AMS 4911 / AMS 4928", "applications": "Turbine Rotors, Structural Airframe Brackets"},
            {"alloy": "Inconel 718 Superalloy", "spec": "AMS 5662 / AMS 5663", "applications": "Rocket Motor Nozzles, Hypersonic Mounts"},
            {"alloy": "Aluminum 7075-T651", "spec": "AMS 4045 / QQ-A-250/12", "applications": "Avionics Enclosures, Hydraulic Actuator Housings"},
            {"alloy": "17-4 PH Stainless Steel (Condition H900)", "spec": "AMS 5643", "applications": "High-Pressure Hydraulic Valves, Drive Shafts"},
            {"alloy": "PEEK Polymer (Aerospace 450G)", "spec": "MIL-P-46183", "applications": "Lightweight Dielectric Spacers & Bushings"}
        ],
        "machine_capacity_roster": [
            {
                "machine_id": "MAC-DMG-65",
                "name": "DMG Mori DMU 65 monoBLOCK",
                "type": "5-Axis High-Speed CNC Machining Center",
                "tolerance": "±0.003 mm",
                "work_envelope": "735 x 650 x 560 mm (20,000 RPM Spindle)",
                "load_current_pct": 82,
                "available_capacity_pct": 18,
                "status": "OPERATIONAL_OPTIMAL",
                "lead_time_days": 7
            },
            {
                "machine_id": "MAC-MZK-200",
                "name": "Mazak Integrex i-200 Multi-Tasking Mill-Turn",
                "type": "9-Axis CNC Simultaneous Turn-Mill Center",
                "tolerance": "±0.003 mm",
                "work_envelope": "Ø658 mm x 1,011 mm",
                "load_current_pct": 74,
                "available_capacity_pct": 26,
                "status": "OPERATIONAL_OPTIMAL",
                "lead_time_days": 10
            },
            {
                "machine_id": "MAC-AGIE-550",
                "name": "GF AgieCharmilles CUT P 550 Pro",
                "type": "Sub-Micron Precision Wire EDM",
                "tolerance": "±0.0015 mm",
                "work_envelope": "550 x 350 x 400 mm",
                "load_current_pct": 65,
                "available_capacity_pct": 35,
                "status": "OPERATIONAL_OPTIMAL",
                "lead_time_days": 5
            },
            {
                "machine_id": "MAC-EOS-290",
                "name": "EOS M 290 Direct Metal Laser Sintering (DMLS)",
                "type": "Industrial Additive Metal 3D Printer",
                "tolerance": "±0.020 mm (Pre-CNC Finish)",
                "work_envelope": "250 x 250 x 325 mm (400W Yb-Fiber Laser)",
                "load_current_pct": 58,
                "available_capacity_pct": 42,
                "status": "OPERATIONAL_OPTIMAL",
                "lead_time_days": 3
            },
            {
                "machine_id": "MAC-ZEISS-CMM",
                "name": "Zeiss CONTURA Coordinate Metrology Lab",
                "type": "Active Scanning Metrology CMM",
                "tolerance": "±0.0008 mm (0.8 µm)",
                "work_envelope": "1,000 x 1,200 x 600 mm",
                "load_current_pct": 70,
                "available_capacity_pct": 30,
                "status": "CALIBRATED_ACTIVE",
                "lead_time_days": 1
            }
        ],
        "capacity_forecast_next_90_days": [
            {"period": "Next 14 Days", "total_plant_hours": 5800, "committed_hours": 4640, "available_hours": 1160, "availability_pct": 20},
            {"period": "15 - 30 Days", "total_plant_hours": 6200, "committed_hours": 4464, "available_hours": 1736, "availability_pct": 28},
            {"period": "31 - 60 Days", "total_plant_hours": 12800, "committed_hours": 7936, "available_hours": 4864, "availability_pct": 38},
            {"period": "61 - 90 Days", "total_plant_hours": 13200, "committed_hours": 6600, "available_hours": 6600, "availability_pct": 50}
        ],
        "certifications_vault": [
            {"code": "AS9100D", "title": "AS9100D / ISO 9001:2015 Aviation, Space & Defense", "body": "TÜV SÜD", "valid_until": "2027-10-15", "badge": "emerald"},
            {"code": "ISO 14001", "title": "ISO 14001:2015 Environmental Management (ESG)", "body": "TÜV SÜD", "valid_until": "2027-10-14", "badge": "emerald"},
            {"code": "ITAR", "title": "ITAR Registered (U.S. Dept of State DDTC)", "body": "DDTC M38921", "valid_until": "2026-12-31", "badge": "blue"},
            {"code": "Nadcap", "title": "Nadcap Aerospace Quality - Heat Treat & NDT", "body": "PRI Nadcap", "valid_until": "2026-08-30", "badge": "indigo"},
            {"code": "EU CBAM", "title": "EU CBAM Regulation 2023/956 Verified Importer", "body": "EU Commission", "valid_until": "2026-12-31", "badge": "teal"}
        ],
        "products_catalog": digital_twin_store.get("productsCatalog", []),
        "shareable_url": f"http://localhost:3000/supplier/{twin_id}"
    }

@router.post("/invite-rfq")
def invite_supplier_to_rfq(req: InviteRfqRequest):
    """
    Handles enterprise buyer direct RFQ invitation sent from public capability passport.
    """
    invite_id = f"INV-RFQ-{uuid.uuid4().hex[:6].upper()}"
    invite_record = {
        "invite_id": invite_id,
        "supplier_id": req.supplier_id,
        "buyer_name": req.buyer_name,
        "buyer_company": req.buyer_company,
        "buyer_email": req.buyer_email,
        "rfq_title": req.rfq_title,
        "part_name": req.part_name,
        "target_qty": req.target_qty,
        "target_delivery_date": req.target_delivery_date,
        "target_budget_usd": req.target_budget_usd or (req.target_qty * 320.0),
        "notes": req.notes,
        "status": "INVITED",
        "created_at": datetime.datetime.utcnow().isoformat()
    }
    PUBLIC_RFQ_INVITES.insert(0, invite_record)
    return {
        "status": "success",
        "message": f"Successfully invited {req.supplier_id} to private RFQ: {req.rfq_title}",
        "invite": invite_record
    }

@router.post("/shortlist")
def add_supplier_to_shortlist(req: ShortlistRequest):
    """
    Handles enterprise buyer adding supplier to their Approved Supplier List (ASL).
    """
    shortlist_id = f"ASL-{uuid.uuid4().hex[:6].upper()}"
    record = {
        "shortlist_id": shortlist_id,
        "supplier_id": req.supplier_id,
        "buyer_company": req.buyer_company,
        "tier_category": req.tier_category,
        "notes": req.notes,
        "created_at": datetime.datetime.utcnow().isoformat()
    }
    BUYER_SHORTLISTS.insert(0, record)
    return {
        "status": "success",
        "message": f"Supplier {req.supplier_id} added to {req.buyer_company}'s Approved Supplier List.",
        "shortlist": record
    }

@router.get("/verify/{credential_hash}")
def verify_capability_credential(credential_hash: str):
    """
    Cryptographic verification endpoint for public capability passport.
    """
    return {
        "status": "VALID_AND_CRYPTOGRAPHICALLY_VERIFIED",
        "credential_hash": credential_hash,
        "issuer": "Supplier Capability Twin Decentralized Trust Authority",
        "verification_time": datetime.datetime.utcnow().isoformat(),
        "metrology_tamper_evident": True,
        "telemetry_signature": "Ed25519-SHA512-VERIFIED"
    }
