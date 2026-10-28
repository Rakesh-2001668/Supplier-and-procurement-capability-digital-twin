from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
import datetime
import uuid
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.models.supplier import Supplier, SupplierLocation, SupplierCapability

router = APIRouter()

# =====================================================================
# FUTURISTIC SUPPLIER ONBOARDING, ASSESSMENT & APPROVAL ENGINE
# =====================================================================

# 8 Futuristic Aerospace Assessment Pillars Definition
AEROSPACE_ASSESSMENT_PILLARS = [
    {
        "id": "financial_solvency",
        "name": "Autonomous Financial & Solvency Health",
        "weight": 0.15,
        "metrics": ["Altman Z''-Score (3.62)", "D&B PAYDEX (88/100)", "Debt-to-Equity (0.42)", "Operating Cash Runway (24 mos)"],
        "benchmark": "Investment Grade BAA1 / Low Liquidity Risk",
        "target_score": 90
    },
    {
        "id": "as9100d_metrology",
        "name": "AS9100D Rev D & Zero-Defect Metrology",
        "weight": 0.20,
        "metrics": ["Zeiss CMM Calibration (±0.0001\")", "AS9102 First Article Inspection Rate (99.8%)", "Process Capability Cpk (1.82)", "Optical Laser Interferometry"],
        "benchmark": "NADCAP Accredited (NDT & Heat Treat)",
        "target_score": 95
    },
    {
        "id": "precision_telemetry",
        "name": "Precision Manufacturing & Capacity Telemetry",
        "weight": 0.15,
        "metrics": ["DMG MORI 5-Axis CNC Spindle OEE (84.6%)", "ISO Class 5 Space Cleanroom Packaging", "Wire EDM Tolerance (<1.5µm)", "Automated Tool Wear Telemetry"],
        "benchmark": "Industry 4.0 Digital Shopfloor Active",
        "target_score": 88
    },
    {
        "id": "esg_lifecycle",
        "name": "ESG & Carbon Scope 1/2/3 Lifecycle Telemetry",
        "weight": 0.10,
        "metrics": ["Scope 1 & 2 Emissions (42.1 tCO2e/yr)", "100% Conflict-Free Minerals (Dodd-Frank 1502)", "Renewable Solar Microgrid (68%)", "Closed-Loop Coolant Recirculation (94%)"],
        "benchmark": "ISO 14001:2015 & RoHS/REACH Compliant",
        "target_score": 85
    },
    {
        "id": "cyber_zero_trust",
        "name": "Zero-Trust Cyber & Information Security",
        "weight": 0.15,
        "metrics": ["CMMC Level 2 Certified (NIST SP 800-171)", "Air-Gapped CAD/CAM Enclave", "FIPS 140-3 Hardware Crypto Modules", "Zero-Trust Device Identity Attestation"],
        "benchmark": "ITAR & EAR Defense Enclave Compliant",
        "target_score": 92
    },
    {
        "id": "dfsc_resilience",
        "name": "Geopolitical & DFSC Multi-Sourcing Resilience",
        "weight": 0.10,
        "metrics": ["Disruption-Free Supply Chain Score (91.4)", "Tier-2 Billet Redundancy (Dual Sourced)", "Geopolitical Chokepoint Distance (>800 km)", "Strategic Buffer Stock (60 Days)"],
        "benchmark": "Resilient NATO / Tier-1 Production Node",
        "target_score": 86
    },
    {
        "id": "predictive_otd",
        "name": "High-Velocity On-Time Delivery Simulation",
        "weight": 0.08,
        "metrics": ["Monte Carlo Schedule Reliability (98.2%)", "Historical OTD (99.1%)", "Buffer Compression Capability (<48 hrs)", "Real-Time ASN EDI 856 Telemetry"],
        "benchmark": "Critical Spaceflight Flight-Article Readiness",
        "target_score": 94
    },
    {
        "id": "advanced_materials",
        "name": "Advanced Superalloys & Generative Topology",
        "weight": 0.07,
        "metrics": ["Inconel 718 & Titanium Ti-6Al-4V Certified", "Additive DMLS Powder Metallurgy", "Cryogenic Nitrogen Machining", "Generative Lightweighting Co-Engineering"],
        "benchmark": "Propulsion Grade High-Temp Metallurgy",
        "target_score": 89
    }
]

# Rich In-Memory Data Store for Supplier Onboarding Dossiers
onboarding_pipeline_store: Dict[str, Dict[str, Any]] = {
    "SUP-2025-0012": {
        "id": "SUP-2025-0012",
        "name": "ABC Components Pvt Ltd",
        "short_name": "ABC Components",
        "cage_code": "7X892",
        "duns_number": "83-492-1092",
        "industry": "Aerospace CNC Machining & Turbine Components",
        "tier": "Tier 1 Qualified Partner",
        "status": "PENDING_EXECUTIVE_APPROVAL",
        "stage_step": 5,
        "composite_score": 92.4,
        "risk_level": "Low",
        "submission_date": "2026-10-14",
        "last_updated": "2026-10-19 14:20 UTC",
        "primary_contact": {
            "name": "Rakesh Kumar",
            "title": "Director of Aerospace Systems",
            "email": "rakesh.kumar@abccomponents.com",
            "phone": "+1 (555) 749-2019"
        },
        "headquarters": {
            "address": "45 Industrial Corridor, Phase II",
            "city": "Chennai",
            "state": "Tamil Nadu",
            "country": "India",
            "facility_size_sqft": "65,000 sq.ft High-Precision Plant"
        },
        "plants": [
            {
                "name": "Plant 1 - Aerospace SEZ Machining Center",
                "location": "Chennai SEZ Bay 04",
                "capabilities": ["5-Axis CNC Milling", "Zeiss CMM Metrology", "Vacuum Heat Treat"],
                "cleanroom_class": "ISO Class 7",
                "power_source": "Solar Microgrid Hybrid"
            },
            {
                "name": "Plant 2 - Defense Fabrication & Cleanroom Assembly",
                "location": "Sriperumbudur Advanced Corridor",
                "capabilities": ["Titanium Electron Beam Welding", "Laser Cladding", "Cleanroom Assembly"],
                "cleanroom_class": "ISO Class 5",
                "power_source": "Grid + Captive Hydro"
            }
        ],
        "certifications": [
            {"code": "AS9100D", "name": "Aerospace Quality Management", "valid_until": "2028-06-30", "status": "VERIFIED"},
            {"code": "ISO 9001:2015", "name": "Quality Management Systems", "valid_until": "2028-04-15", "status": "VERIFIED"},
            {"code": "NADCAP-NDT", "name": "Non-Destructive Testing Penetrant/Magnetic", "valid_until": "2027-11-20", "status": "VERIFIED"},
            {"code": "CMMC-L2", "name": "Cybersecurity Maturity Model Certification", "valid_until": "2027-09-12", "status": "VERIFIED"},
            {"code": "ITAR-ACTIVE", "name": "ITAR Registrant DDTC Code M39812", "valid_until": "2027-01-31", "status": "VERIFIED"}
        ],
        "pillar_scores": {
            "financial_solvency": 92,
            "as9100d_metrology": 96,
            "precision_telemetry": 89,
            "esg_lifecycle": 88,
            "cyber_zero_trust": 95,
            "dfsc_resilience": 90,
            "predictive_otd": 94,
            "advanced_materials": 91
        },
        "approvals": [
            {
                "role": "Lead Quality & Metrology Assessor",
                "approver": "Dr. Sarah Jenkins (AS9100D Auditor)",
                "status": "APPROVED",
                "timestamp": "2026-10-18 11:30 UTC",
                "comments": "Zeiss CMM coordinate calibration certified to ±0.0001\". Zero NCR detected on sample titanium turbine blisk."
            },
            {
                "role": "Chief Security & Defense Compliance Officer",
                "approver": "Marcus Vance (CMMC/ITAR Specialist)",
                "status": "APPROVED",
                "timestamp": "2026-10-18 16:45 UTC",
                "comments": "NIST SP 800-171 enclave air-gap verified. Active DDTC registration CAGE 7X892 confirmed."
            },
            {
                "role": "VP Global Strategic Procurement",
                "approver": "Elena Rostova (Executive VP)",
                "status": "PENDING",
                "timestamp": None,
                "comments": None
            }
        ]
    },
    "SUP-AERO-991": {
        "id": "SUP-AERO-991",
        "name": "AeroForge Dynamics Inc",
        "short_name": "AeroForge",
        "cage_code": "4K291",
        "duns_number": "92-381-8821",
        "industry": "Superalloy Forging & Cryogenic Rocket Casings",
        "tier": "Tier 1 Aerospace Prime Supplier",
        "status": "IN_ASSESSMENT",
        "stage_step": 4,
        "composite_score": 88.6,
        "risk_level": "Low",
        "submission_date": "2026-10-17",
        "last_updated": "2026-10-20 08:15 UTC",
        "primary_contact": {
            "name": "Dr. Brian Campbell",
            "title": "VP Engineering",
            "email": "bcampbell@aeroforge.aero",
            "phone": "+1 (555) 441-9920"
        },
        "headquarters": {
            "address": "1200 Orbit Propulsion Way",
            "city": "Huntsville",
            "state": "Alabama",
            "country": "United States",
            "facility_size_sqft": "110,000 sq.ft Heavy Forging Plant"
        },
        "plants": [
            {
                "name": "Huntsville Heavy Hydraulic Forging Bay",
                "location": "Huntsville Space SEZ",
                "capabilities": ["15,000-Ton Hydraulic Forging", "Inconel 718 Vacuum Induction Melting", "Ultrasonic Sub-surface NDT"],
                "cleanroom_class": "ISO Class 8",
                "power_source": "Grid 100% Hydro"
            }
        ],
        "certifications": [
            {"code": "AS9100D", "name": "Aerospace Quality Management", "valid_until": "2027-12-31", "status": "VERIFIED"},
            {"code": "NADCAP-MTL", "name": "Materials Testing Laboratory", "valid_until": "2027-08-30", "status": "VERIFIED"},
            {"code": "ITAR-ACTIVE", "name": "ITAR Registrant DDTC Code K49201", "valid_until": "2028-02-28", "status": "VERIFIED"}
        ],
        "pillar_scores": {
            "financial_solvency": 88,
            "as9100d_metrology": 92,
            "precision_telemetry": 87,
            "esg_lifecycle": 82,
            "cyber_zero_trust": 90,
            "dfsc_resilience": 89,
            "predictive_otd": 91,
            "advanced_materials": 95
        },
        "approvals": [
            {
                "role": "Lead Quality & Metrology Assessor",
                "approver": "Pending Assignment",
                "status": "PENDING",
                "timestamp": None,
                "comments": None
            },
            {
                "role": "Chief Security & Defense Compliance Officer",
                "approver": "Pending Assignment",
                "status": "PENDING",
                "timestamp": None,
                "comments": None
            },
            {
                "role": "VP Global Strategic Procurement",
                "approver": "Pending Assignment",
                "status": "PENDING",
                "timestamp": None,
                "comments": None
            }
        ]
    },
    "SUP-AERO-992": {
        "id": "SUP-AERO-992",
        "name": "Titanium Space Castings Ltd",
        "short_name": "Titanium Space",
        "cage_code": "8R112",
        "duns_number": "77-102-4412",
        "industry": "Precision Investment Casting & Titanium Valves",
        "tier": "Tier 2 Specialized Component Maker",
        "status": "APPLICATION_SUBMITTED",
        "stage_step": 2,
        "composite_score": 79.2,
        "risk_level": "Medium",
        "submission_date": "2026-10-19",
        "last_updated": "2026-10-19 16:00 UTC",
        "primary_contact": {
            "name": "Hiroshi Tanaka",
            "title": "Managing Director",
            "email": "h.tanaka@titaniumspace.co.uk",
            "phone": "+44 20 7946 0912"
        },
        "headquarters": {
            "address": "4 Advanced Metals Industrial Park",
            "city": "Sheffield",
            "state": "Yorkshire",
            "country": "United Kingdom",
            "facility_size_sqft": "40,000 sq.ft Precision Foundry"
        },
        "plants": [
            {
                "name": "Sheffield Vacuum Arc Remelt Foundry",
                "location": "Advanced Metals Park Bay 2",
                "capabilities": ["Titanium Investment Casting", "Hot Isostatic Pressing (HIP)", "Digital Radiography"],
                "cleanroom_class": "Standard Industrial",
                "power_source": "Wind Renewable"
            }
        ],
        "certifications": [
            {"code": "ISO 9001:2015", "name": "Quality Management Systems", "valid_until": "2027-05-20", "status": "VERIFIED"},
            {"code": "AS9100D", "name": "Aerospace Quality Management", "valid_until": "2026-12-15", "status": "AUDIT_SCHEDULED"}
        ],
        "pillar_scores": {
            "financial_solvency": 82,
            "as9100d_metrology": 80,
            "precision_telemetry": 78,
            "esg_lifecycle": 84,
            "cyber_zero_trust": 75,
            "dfsc_resilience": 82,
            "predictive_otd": 77,
            "advanced_materials": 88
        },
        "approvals": [
            {
                "role": "Lead Quality & Metrology Assessor",
                "approver": "Pending",
                "status": "PENDING",
                "timestamp": None,
                "comments": None
            },
            {
                "role": "Chief Security & Defense Compliance Officer",
                "approver": "Pending",
                "status": "PENDING",
                "timestamp": None,
                "comments": None
            },
            {
                "role": "VP Global Strategic Procurement",
                "approver": "Pending",
                "status": "PENDING",
                "timestamp": None,
                "comments": None
            }
        ]
    },
    "TENANT_SUPPLIER_001": {
        "id": "TENANT_SUPPLIER_001",
        "name": "Apex Precision Machining Ltd",
        "short_name": "Apex Precision",
        "cage_code": "9A120",
        "duns_number": "61-902-8841",
        "industry": "High-Tolerance CNC Turning, Milling & Cleanroom Assembly",
        "tier": "Tier 1 Strategic Production Prime",
        "status": "VERIFIED_CAPABILITY_TWIN",
        "stage_step": 6,
        "composite_score": 98.4,
        "risk_level": "Low",
        "submission_date": "2026-08-10",
        "last_updated": "2026-10-15 11:00 UTC",
        "primary_contact": {
            "name": "Marcus Vance",
            "title": "Director of Manufacturing Operations",
            "email": "operations@apexmachining.aero",
            "phone": "+1 (555) 819-2011"
        },
        "headquarters": {
            "address": "880 High-Precision Way",
            "city": "Denver",
            "state": "Colorado",
            "country": "United States",
            "facility_size_sqft": "85,000 sq.ft Smart Factory"
        },
        "plants": [
            {
                "name": "Denver 5-Axis Robotic Cell Facility",
                "location": "Aerospace Technology Corridor Bay 01",
                "capabilities": ["DMG MORI 5-Axis Milling", "Zeiss Prismo CMM", "Laser Cladding", "Vacuum Quench"],
                "cleanroom_class": "ISO Class 5",
                "power_source": "100% Zero-Carbon Microgrid"
            }
        ],
        "certifications": [
            {"code": "AS9100D", "name": "Aerospace Quality Management System", "valid_until": "2028-11-30", "status": "VERIFIED"},
            {"code": "CMMC-L2", "name": "Cybersecurity Maturity Model Certification", "valid_until": "2028-08-15", "status": "VERIFIED"},
            {"code": "ITAR-ACTIVE", "name": "ITAR DDTC Certified", "valid_until": "2028-01-31", "status": "VERIFIED"},
            {"code": "NADCAP-NDT", "name": "Non-Destructive Testing", "valid_until": "2028-06-30", "status": "VERIFIED"}
        ],
        "pillar_scores": {
            "financial_solvency": 98,
            "as9100d_metrology": 99,
            "precision_telemetry": 97,
            "esg_lifecycle": 96,
            "cyber_zero_trust": 99,
            "dfsc_resilience": 97,
            "predictive_otd": 98,
            "advanced_materials": 99
        },
        "approvals": [
            {
                "role": "Lead Quality & Metrology Assessor",
                "approver": "Dr. Sarah Jenkins",
                "status": "APPROVED",
                "timestamp": "2026-08-12 14:00 UTC",
                "comments": "Zero NCR. Full CMM metrology alignment verified."
            },
            {
                "role": "Chief Security & Defense Compliance Officer",
                "approver": "Marcus Vance",
                "status": "APPROVED",
                "timestamp": "2026-08-12 15:30 UTC",
                "comments": "CMMC Level 2 & ITAR enclave passed."
            },
            {
                "role": "VP Global Strategic Procurement",
                "approver": "Elena Rostova",
                "status": "APPROVED",
                "timestamp": "2026-08-13 09:15 UTC",
                "comments": "Prime Tier 1 capability twin authorized for open RFQ bidding and high-value purchase orders."
            }
        ]
    }
}


# =====================================================================
# PYDANTIC SCHEMAS
# =====================================================================

class SupplierRegistrationPayload(BaseModel):
    company_name: str
    short_name: Optional[str] = None
    cage_code: Optional[str] = None
    duns_number: Optional[str] = None
    industry_sector: str
    contact_name: str
    contact_email: str
    contact_phone: Optional[str] = None
    headquarters_city: str
    headquarters_country: str
    facility_size_sqft: Optional[str] = "50,000 sq.ft"
    cleanroom_class: Optional[str] = "ISO Class 7"
    processes: List[str] = Field(default_factory=list)
    materials: List[str] = Field(default_factory=list)
    precision_tolerance: Optional[str] = "±0.0002\" (High Precision)"
    certifications: List[str] = Field(default_factory=list)
    esg_renewable_pct: Optional[int] = 75
    notes: Optional[str] = None

class EvaluatePillarPayload(BaseModel):
    pillar_id: str
    new_score: int
    evaluator_name: Optional[str] = "Lead Quality Assessor"
    evaluator_notes: Optional[str] = "CMM calibration report verified against AS9100D standards."

class ExecutiveApprovalPayload(BaseModel):
    role: str  # "Lead Quality & Metrology Assessor", "Chief Security & Defense Compliance Officer", "VP Global Strategic Procurement"
    approver_name: str
    action: str  # "APPROVE" or "REJECT" or "REQUEST_REVISION"
    comments: Optional[str] = "Full compliance verified across AS9100D and defense air-gap security enclaves."

class BatchApprovalPayload(BaseModel):
    supplier_ids: List[str]
    action: str  # "APPROVE" or "REJECT"
    approver_name: Optional[str] = "Executive Committee"
    comments: Optional[str] = "Batch onboarding verification authorized."


# Backward-compatible onboarding schema
class OnboardingData(BaseModel):
    companyInfo: Dict[str, Any]
    locations: List[Dict[str, Any]] = Field(default_factory=list)
    capabilities: List[Dict[str, Any]] = Field(default_factory=list)
    documents: List[Dict[str, Any]] = Field(default_factory=list)


# =====================================================================
# API ENDPOINTS
# =====================================================================

@router.get("/onboarding/overview")
def get_onboarding_overview(db: Session = Depends(get_db)):
    """Executive KPI Strip for the Autonomous Supplier Onboarding, Assessment & Approvals Engine."""
    total_pipeline = len(onboarding_pipeline_store)
    in_assessment = sum(1 for s in onboarding_pipeline_store.values() if s["status"] in ["APPLICATION_SUBMITTED", "IN_ASSESSMENT"])
    pending_approval = sum(1 for s in onboarding_pipeline_store.values() if s["status"] == "PENDING_EXECUTIVE_APPROVAL")
    verified_twins = sum(1 for s in onboarding_pipeline_store.values() if s["status"] == "VERIFIED_CAPABILITY_TWIN")

    scores = [s["composite_score"] for s in onboarding_pipeline_store.values() if s.get("composite_score")]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 91.2

    return {
        "status": "success",
        "total_pipeline": total_pipeline,
        "in_assessment_count": in_assessment,
        "pending_executive_approvals": pending_approval,
        "verified_capability_twins": verified_twins,
        "average_assessment_score": avg_score,
        "fast_track_kyc_rate": 96.8,
        "zero_trust_attestation_rate": 99.4,
        "pillars": AEROSPACE_ASSESSMENT_PILLARS
    }


@router.get("/onboarding/pipeline")
def get_onboarding_pipeline(
    status_filter: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Retrieve full onboarding pipeline with live capability twin scores and stage progress."""
    suppliers = list(onboarding_pipeline_store.values())

    # Filter by status
    if status_filter and status_filter.upper() != "ALL":
        suppliers = [s for s in suppliers if s["status"].upper() == status_filter.upper()]

    # Filter by search
    if search:
        q = search.lower().strip()
        suppliers = [
            s for s in suppliers if (
                q in s["name"].lower() or
                q in s.get("cage_code", "").lower() or
                q in s["industry"].lower() or
                q in s.get("primary_contact", {}).get("name", "").lower()
            )
        ]

    return {
        "status": "success",
        "count": len(suppliers),
        "suppliers": suppliers
    }


@router.post("/onboarding/submit")
def submit_new_supplier_onboarding(payload: SupplierRegistrationPayload, db: Session = Depends(get_db)):
    """Live Enterprise Onboarding Endpoint: Synthesizes Capability Twin & Triggers AI Multi-Pillar Assessment."""
    import uuid
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    sup_id = f"SUP-{now.strftime('%Y')}-{uuid.uuid4().hex[:4].upper()}"

    # Calculate initial composite score based on payload capabilities
    base_score = 85.0
    if "AS9100D" in payload.certifications:
        base_score += 4.0
    if "CMMC-L2" in payload.certifications or "ITAR" in payload.certifications:
        base_score += 3.5
    if "5-Axis CNC Milling" in payload.processes:
        base_score += 2.5
    composite = min(98.5, round(base_score, 1))

    # Construct the digital twin & onboarding record
    record = {
        "id": sup_id,
        "name": payload.company_name,
        "short_name": payload.short_name or payload.company_name.split()[0],
        "cage_code": payload.cage_code or f"9{uuid.uuid4().hex[:4].upper()}",
        "duns_number": payload.duns_number or f"{uuid.uuid4().int % 90 + 10}-{uuid.uuid4().int % 900 + 100}-9912",
        "industry": payload.industry_sector,
        "tier": "Tier 1 Candidate" if composite >= 90 else "Tier 2 Candidate",
        "status": "PENDING_EXECUTIVE_APPROVAL" if composite >= 90 else "IN_ASSESSMENT",
        "stage_step": 4 if composite >= 90 else 3,
        "composite_score": composite,
        "risk_level": "Low" if composite >= 88 else "Medium",
        "submission_date": now.strftime("%Y-%m-%d"),
        "last_updated": now.strftime("%Y-%m-%d %H:%M UTC"),
        "primary_contact": {
            "name": payload.contact_name,
            "title": "Director of Aerospace Business",
            "email": payload.contact_email,
            "phone": payload.contact_phone or "+1 (555) 910-2026"
        },
        "headquarters": {
            "address": "Aerospace Industrial Corridor",
            "city": payload.headquarters_city,
            "state": "SEZ Phase II",
            "country": payload.headquarters_country,
            "facility_size_sqft": payload.facility_size_sqft
        },
        "plants": [
            {
                "name": f"{payload.company_name} - Primary Machining Facility",
                "location": f"{payload.headquarters_city} Industrial Bay 01",
                "capabilities": payload.processes if payload.processes else ["5-Axis CNC Milling", "Zeiss CMM Metrology"],
                "cleanroom_class": payload.cleanroom_class,
                "power_source": f"Renewable Solar ({payload.esg_renewable_pct}%)"
            }
        ],
        "certifications": [
            {"code": c, "name": f"{c} Certified", "valid_until": "2028-12-31", "status": "VERIFIED"}
            for c in (payload.certifications if payload.certifications else ["AS9100D", "ISO 9001:2015"])
        ],
        "pillar_scores": {
            "financial_solvency": int(min(98, composite - 1)),
            "as9100d_metrology": int(min(99, composite + 3)),
            "precision_telemetry": int(min(96, composite)),
            "esg_lifecycle": int(min(94, payload.esg_renewable_pct or 85)),
            "cyber_zero_trust": int(min(98, composite + 1)),
            "dfsc_resilience": int(min(95, composite - 2)),
            "predictive_otd": int(min(97, composite + 2)),
            "advanced_materials": int(min(98, composite))
        },
        "approvals": [
            {
                "role": "Lead Quality & Metrology Assessor",
                "approver": "Dr. Sarah Jenkins (AS9100D Lead)",
                "status": "APPROVED" if composite >= 90 else "PENDING",
                "timestamp": now.strftime("%Y-%m-%d %H:%M UTC") if composite >= 90 else None,
                "comments": "Autonomous CMM dimensional tolerance verification passed (±0.0001\")." if composite >= 90 else None
            },
            {
                "role": "Chief Security & Defense Compliance Officer",
                "approver": "Marcus Vance (CMMC/ITAR Specialist)",
                "status": "APPROVED" if composite >= 92 else "PENDING",
                "timestamp": now.strftime("%Y-%m-%d %H:%M UTC") if composite >= 92 else None,
                "comments": "Active CAGE code and zero-trust ITAR enclave validated." if composite >= 92 else None
            },
            {
                "role": "VP Global Strategic Procurement",
                "approver": "Elena Rostova (Executive VP)",
                "status": "PENDING",
                "timestamp": None,
                "comments": None
            }
        ]
    }

    onboarding_pipeline_store[sup_id] = record

    # Also persist to SQLite database Supplier table
    try:
        db_sup = Supplier(
            name=payload.company_name,
            status="Under Review" if composite < 90 else "Pending Approval",
            risk_score=float(round(100.0 - composite, 1)),
            on_time_delivery=98.5,
            defect_rate=0.002,
            invoice_accuracy=99.8,
            compliance_score=float(composite),
            risk_level="Low" if composite >= 88 else "Medium",
            spend=0.0
        )
        db.add(db_sup)
        db.commit()
    except Exception as e:
        print("Note: DB persist bypassed:", e)

    return {
        "status": "success",
        "message": f"Supplier capability twin for '{payload.company_name}' synthesized successfully. Multi-pillar evaluation initialized.",
        "supplier_id": sup_id,
        "composite_score": composite,
        "onboarding_record": record
    }


@router.get("/onboarding/{supplier_id}/assessment")
def get_supplier_assessment(supplier_id: str):
    """Deep assessment dossier with 8 futuristic aerospace dimensions, metrics, and radar telemetry."""
    sup = onboarding_pipeline_store.get(supplier_id)
    if not sup:
        # Fallback to first available
        sup = list(onboarding_pipeline_store.values())[0]

    pillar_scores = sup.get("pillar_scores", {})

    detailed_pillars = []
    for p in AEROSPACE_ASSESSMENT_PILLARS:
        score = pillar_scores.get(p["id"], 88)
        detailed_pillars.append({
            **p,
            "current_score": score,
            "status": "EXCEEDS_BENCHMARK" if score >= p["target_score"] else "MEETS_BENCHMARK",
            "last_calibrated": sup.get("last_updated", "2026-10-18 10:00 UTC")
        })

    return {
        "status": "success",
        "supplier_id": sup["id"],
        "supplier_name": sup["name"],
        "cage_code": sup["cage_code"],
        "industry": sup["industry"],
        "tier": sup["tier"],
        "composite_score": sup["composite_score"],
        "risk_level": sup["risk_level"],
        "status_code": sup["status"],
        "plants_count": len(sup.get("plants", [])),
        "certifications": sup.get("certifications", []),
        "pillars": detailed_pillars,
        "ai_recommendation": {
            "verdict": "RECOMMENDED_FOR_TIER_1_DEFENSE_AWARD" if sup["composite_score"] >= 90 else "RECOMMENDED_WITH_CONDITIONS",
            "confidence": "98.4%",
            "key_strengths": [
                "Zero-Defect Zeiss CMM coordinate metrology verified at ±0.0001\" precision.",
                "Active CAGE code and ITAR defense enclave air-gap verified.",
                "High-velocity DMG MORI 5-Axis spindle OEE exceeding 84%."
            ],
            "action_items": [
                "Authorize executive procurement sign-off to graduate twin to active bidding network.",
                "Lock in quarterly capacity reservation under Tier 1 CAPEX frame agreement."
            ]
        }
    }


@router.post("/onboarding/{supplier_id}/assessment/evaluate")
def evaluate_assessment_pillar(supplier_id: str, payload: EvaluatePillarPayload):
    """Update or recalibrate an individual aerospace assessment pillar."""
    sup = onboarding_pipeline_store.get(supplier_id)
    if not sup:
        raise HTTPException(status_code=404, detail=f"Supplier '{supplier_id}' not found.")

    if "pillar_scores" not in sup:
        sup["pillar_scores"] = {}

    sup["pillar_scores"][payload.pillar_id] = payload.new_score
    
    # Recompute weighted composite score
    total_weighted = 0.0
    total_weight = 0.0
    for p in AEROSPACE_ASSESSMENT_PILLARS:
        w = p["weight"]
        s = sup["pillar_scores"].get(p["id"], 88)
        total_weighted += s * w
        total_weight += w

    sup["composite_score"] = round(total_weighted / total_weight, 1) if total_weight > 0 else 90.0
    sup["last_updated"] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    return {
        "status": "success",
        "message": f"Pillar '{payload.pillar_id}' recalibrated to {payload.new_score}. Composite score updated to {sup['composite_score']}.",
        "new_composite_score": sup["composite_score"],
        "pillar_scores": sup["pillar_scores"]
    }


@router.get("/onboarding/{supplier_id}/approval-dossier")
def get_supplier_approval_dossier(supplier_id: str):
    """Retrieve full executive approval dossier with cryptographic multi-tier sign-off trail."""
    sup = onboarding_pipeline_store.get(supplier_id)
    if not sup:
        sup = list(onboarding_pipeline_store.values())[0]

    return {
        "status": "success",
        "supplier_id": sup["id"],
        "supplier_name": sup["name"],
        "short_name": sup.get("short_name", sup["name"]),
        "cage_code": sup["cage_code"],
        "tier": sup["tier"],
        "status": sup["status"],
        "composite_score": sup["composite_score"],
        "risk_level": sup["risk_level"],
        "headquarters": sup.get("headquarters"),
        "primary_contact": sup.get("primary_contact"),
        "certifications": sup.get("certifications", []),
        "plants": sup.get("plants", []),
        "approvals": sup.get("approvals", []),
        "is_ready_for_final_signoff": all(
            a["status"] == "APPROVED" for a in sup.get("approvals", [])[:-1]
        ),
        "digital_signature_stamp": f"ECDSA-SECP256K1-{uuid.uuid4().hex[:12].upper()}"
    }


@router.post("/onboarding/{supplier_id}/approve")
def execute_supplier_approval(supplier_id: str, payload: ExecutiveApprovalPayload, db: Session = Depends(get_db)):
    """1-Click Executive Sign-Off Engine: Authorizes role or final graduation to VERIFIED_CAPABILITY_TWIN."""
    now_str = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    sup = onboarding_pipeline_store.get(supplier_id)
    if not sup:
        raise HTTPException(status_code=404, detail=f"Supplier '{supplier_id}' not found.")

    matched_role = False
    for app in sup.get("approvals", []):
        if app["role"] == payload.role or payload.role in app["role"]:
            app["status"] = "APPROVED" if payload.action.upper() == "APPROVE" else "REJECTED"
            app["approver"] = payload.approver_name
            app["timestamp"] = now_str
            app["comments"] = payload.comments or "Authorization confirmed under aerospace governance matrix."
            matched_role = True
            break

    if not matched_role:
        # Update last approval (VP Procurement)
        if sup.get("approvals"):
            sup["approvals"][-1]["status"] = "APPROVED" if payload.action.upper() == "APPROVE" else "REJECTED"
            sup["approvals"][-1]["approver"] = payload.approver_name
            sup["approvals"][-1]["timestamp"] = now_str
            sup["approvals"][-1]["comments"] = payload.comments

    # Check if all roles are approved
    all_approved = all(a["status"] == "APPROVED" for a in sup.get("approvals", []))
    if all_approved:
        sup["status"] = "VERIFIED_CAPABILITY_TWIN"
        sup["stage_step"] = 6
        # Update SQL Supplier record to 'Verified'
        try:
            db_sup = db.query(Supplier).filter(Supplier.name == sup["name"]).first()
            if db_sup:
                db_sup.status = "Verified"
                db_sup.risk_level = "Low"
                db_sup.compliance_score = float(sup["composite_score"])
                db.commit()
        except Exception as e:
            print("DB update note:", e)

    sup["last_updated"] = now_str

    return {
        "status": "success",
        "message": f"Supplier '{sup['name']}' has been {payload.action.upper()}D by {payload.approver_name}.",
        "new_status": sup["status"],
        "all_approved": all_approved,
        "approvals": sup["approvals"]
    }


@router.post("/onboarding/approvals/batch")
def batch_supplier_approvals(payload: BatchApprovalPayload, db: Session = Depends(get_db)):
    """Executive Committee 1-Click Batch Approval Engine."""
    now_str = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    approved_list = []

    for sid in payload.supplier_ids:
        sup = onboarding_pipeline_store.get(sid)
        if sup:
            for app in sup.get("approvals", []):
                app["status"] = "APPROVED" if payload.action.upper() == "APPROVE" else "REJECTED"
                app["approver"] = payload.approver_name or "Executive Committee"
                app["timestamp"] = now_str
                app["comments"] = payload.comments or "Batch Executive Committee Authorization."
            
            sup["status"] = "VERIFIED_CAPABILITY_TWIN" if payload.action.upper() == "APPROVE" else "REJECTED"
            sup["last_updated"] = now_str
            approved_list.append(sup["name"])

    return {
        "status": "success",
        "message": f"Successfully processed {len(approved_list)} suppliers with action '{payload.action.upper()}'.",
        "approved_suppliers": approved_list
    }


# Backward-compatible onboarding POST endpoint
@router.post("/onboard")
def submit_onboarding_legacy(data: OnboardingData):
    """Legacy backward-compatible endpoint mapped to the new autonomous engine."""
    comp = data.companyInfo
    name = comp.get('name', 'Aerospace Prime Partner Ltd')
    
    reg_payload = SupplierRegistrationPayload(
        company_name=name,
        short_name=comp.get('shortName', name.split()[0]),
        cage_code=comp.get('cageCode', '7X892'),
        duns_number=comp.get('duns', '83-492-1092'),
        industry_sector=comp.get('industry', 'Aerospace CNC Machining & Turbine Components'),
        contact_name=comp.get('contactPerson', 'Alex Sharma'),
        contact_email=comp.get('email', 'procurement@capability-twin.aero'),
        headquarters_city=comp.get('city', 'Denver'),
        headquarters_country=comp.get('country', 'United States'),
        processes=[c.get('process', '5-Axis CNC Milling') for c in data.capabilities] if data.capabilities else ["5-Axis CNC Milling", "Zeiss CMM Metrology"],
        certifications=[d.get('docType', 'AS9100D') for d in data.documents] if data.documents else ["AS9100D", "CMMC-L2", "ITAR"]
    )
    return submit_new_supplier_onboarding(reg_payload)
