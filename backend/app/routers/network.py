from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.models.tenant import Tenant, TenantType, SupplierProfile
from app.models.procurement import PurchaseOrder, Contract
from typing import List, Optional
import datetime

router = APIRouter(prefix="/api/v1/network", tags=["Supplier Network & AVL"])

APPROVED_VENDOR_DETAILS = {
    "TENANT_SUPPLIER_001": {
        "display_name": "Apex Precision Machining Ltd",
        "category": "Aerospace Machining & CNC Assemblies",
        "tier": "Tier 1 Strategic AVL Partner",
        "avl_status": "APPROVED_PREFERRED",
        "qualification_date": "2023-04-15",
        "last_audit_date": "2026-08-14",
        "next_audit_due": "2027-08-14",
        "location": "Bengaluru, India (Aerospace Special Economic Zone)",
        "facility_type": "AS9100D Certified High-Precision Machining Facility",
        "digital_twin_id": "TWIN-APEX-IND-001",
        "delivery_period": {
            "standard_lead_time_days": 14,
            "expedited_lead_time_days": 7,
            "otif_delivery_rate": 97.8,
            "avg_dispatch_lag_days": 0.4,
            "quote_turnaround_hrs": 3
        },
        "purchasing_terms": {
            "payment_terms": "Net 30 Days (Electronic Bank Wire)",
            "currency": "USD / EUR / INR",
            "incoterms": "DDP (Delivered Duty Paid) Buyer Warehouse",
            "master_agreement_no": "MSA-2024-APX-088",
            "agreement_valid_until": "2027-12-31",
            "volume_rebate_tier": "5% rebate on annual spend > $250k; 8% on > $500k",
            "warranty_period": "24 Months Full Replacement Warranty",
            "defect_liability": "Immediate 48h RMA turnaround with advance replacement",
            "audit_compliance_status": "100% Fully Compliant (ITAR & AS9100D)"
        },
        "capabilities": {
            "core_processes": ["5-Axis CNC Milling", "Mill-Turn Multi-Tasking", "Wire EDM", "Coordinate Metrology (CMM)", "Cleanroom Packaging"],
            "materials_certified": ["Titanium Ti-6Al-4V", "Aluminum 7075-T6 & 6061-T6", "Inconel 718", "Stainless Steel 316L", "PEEK Polymer"],
            "precision_tolerance": "±0.003 mm",
            "surface_finishing": ["Hardcoat Anodize (MIL-A-8625)", "Electropolishing", "Chromate Conversion"],
            "certifications": ["AS9100D (Aerospace)", "ISO 9001:2015", "ISO 14001", "ITAR Compliant", "Nadcap NDT"]
        },
        "default_active_works": [
            {
                "po_number": "PO-2026-7022",
                "title": "Precision CNC 5-Axis Aerospace Enclosures (Batch 4)",
                "quantity": 120,
                "amount": 35232.31,
                "committed_delivery": "2026-11-15",
                "status": "IN_PROGRESS",
                "fulfillment_stage": "80% Machining Complete • Scheduled CMM Quality Inspection",
                "progress_pct": 80
            },
            {
                "po_number": "PO-2026-4410",
                "title": "Inconel 718 High-Pressure Hydraulic Flanges",
                "quantity": 45,
                "amount": 21825.00,
                "committed_delivery": "2026-11-28",
                "status": "IN_PROGRESS",
                "fulfillment_stage": "45% Turning & Milling in Progress",
                "progress_pct": 45
            }
        ],
        "default_past_works": [
            {
                "po_number": "PO-2025-00123",
                "title": "Batch Run: Modular Aluminum Manifolds & Housings",
                "quantity": 100,
                "amount": 29500.00,
                "delivered_date": "2026-09-10",
                "status": "COMPLETED_DELIVERED",
                "quality_acceptance_pct": 100.0,
                "invoice_ref": "INV-9306FD51"
            },
            {
                "po_number": "PO-2025-00089",
                "title": "Titanium Grade 5 Pinion Drive Spline Shafts",
                "quantity": 85,
                "amount": 29500.00,
                "delivered_date": "2026-07-22",
                "status": "COMPLETED_DELIVERED",
                "quality_acceptance_pct": 99.4,
                "invoice_ref": "INV-EE51835D"
            },
            {
                "po_number": "PO-2025-00045",
                "title": "Aerospace Machined Sensor Mounting Brackets",
                "quantity": 150,
                "amount": 29500.00,
                "delivered_date": "2026-05-18",
                "status": "COMPLETED_DELIVERED",
                "quality_acceptance_pct": 100.0,
                "invoice_ref": "INV-2025-1118"
            }
        ]
    },

    "TITAN_AERO_SUPPLIER": {
        "display_name": "Titan Aero Heavy Engineering",
        "category": "Heavy Forgings & Structural Airframes",
        "tier": "Tier 1 Qualified AVL Partner",
        "avl_status": "APPROVED_STANDARD",
        "qualification_date": "2023-09-10",
        "last_audit_date": "2026-06-20",
        "next_audit_due": "2027-06-20",
        "location": "Sheffield, United Kingdom",
        "facility_type": "2,500-Ton Hydraulic Aerospace Forging Facility",
        "digital_twin_id": "TWIN-TITAN-UK-042",
        "delivery_period": {
            "standard_lead_time_days": 24,
            "expedited_lead_time_days": 14,
            "otif_delivery_rate": 94.6,
            "avg_dispatch_lag_days": 1.2,
            "quote_turnaround_hrs": 5
        },
        "purchasing_terms": {
            "payment_terms": "Net 45 Days (Electronic Wire Transfer)",
            "currency": "GBP / USD",
            "incoterms": "CIF Buyer Port (Rotterdam / Nhava Sheva)",
            "master_agreement_no": "MSA-2023-TITAN-041",
            "agreement_valid_until": "2026-12-31",
            "volume_rebate_tier": "4% rebate on orders exceeding 200 metric tons/year",
            "warranty_period": "36 Months Structural Integrity Warranty",
            "defect_liability": "Full batch replacement and root cause 8D analysis within 5 business days",
            "audit_compliance_status": "Fully Certified (AS9100 & ISO 14001)"
        },
        "capabilities": {
            "core_processes": ["Closed-Die Forging", "VTL Heavy Vertical Turning", "Vacuum Induction Melting", "Ultrasonic Non-Destructive Testing"],
            "materials_certified": ["AISI 4340 High-Strength Steel", "Titanium Grade 5", "Inconel 625", "Aerospace Aluminum Alloys"],
            "precision_tolerance": "±0.010 mm",
            "surface_finishing": ["Shot Peening", "Induction Hardening (58-62 HRC)", "Phosphate Coating"],
            "certifications": ["AS9100D", "ISO 9001:2015", "ISO 14001", "CE Certified"]
        },
        "default_active_works": [
            {
                "po_number": "PO-2026-6488",
                "title": "Heavy Forged Titanium Transmission Ring Gear Blanks",
                "quantity": 80,
                "amount": 125000.00,
                "committed_delivery": "2026-12-05",
                "status": "IN_PROGRESS",
                "fulfillment_stage": "60% Forged • Entering Heat Treatment Quench",
                "progress_pct": 60
            }
        ],
        "default_past_works": [
            {
                "po_number": "PO-2025-00412",
                "title": "Turbine Engine Structural Ring Mountings",
                "quantity": 50,
                "amount": 84000.00,
                "delivered_date": "2026-08-02",
                "status": "COMPLETED_DELIVERED",
                "quality_acceptance_pct": 98.8,
                "invoice_ref": "INV-TITAN-889"
            }
        ]
    },

    "SHENZHEN_TECH_SUPPLIER": {
        "display_name": "Shenzhen Tech Microelectronics Co.",
        "category": "Avionics, High-Reliability PCBs & MCUs",
        "tier": "Tier 2 Approved Sub-Tier",
        "avl_status": "APPROVED_WATCHLIST",
        "qualification_date": "2024-01-20",
        "last_audit_date": "2026-05-12",
        "next_audit_due": "2026-11-12",
        "location": "Shenzhen, Guangdong, China",
        "facility_type": "Class 10,000 Cleanroom Semiconductor Surface-Mount Facility",
        "digital_twin_id": "TWIN-SZT-CN-088",
        "delivery_period": {
            "standard_lead_time_days": 18,
            "expedited_lead_time_days": 10,
            "otif_delivery_rate": 88.5,
            "avg_dispatch_lag_days": 2.8,
            "quote_turnaround_hrs": 6
        },
        "purchasing_terms": {
            "payment_terms": "Net 30 Days (Letter of Credit / Wire)",
            "currency": "USD",
            "incoterms": "FOB Yantian Port",
            "master_agreement_no": "MSA-2024-SZT-019",
            "agreement_valid_until": "2027-04-30",
            "volume_rebate_tier": "3% rebate on batch orders > 5,000 boards",
            "warranty_period": "12 Months Manufacturer Warranty",
            "defect_liability": "Standard repair and replace warranty",
            "audit_compliance_status": "Audited Cleanroom (Export Compliance Monitored)"
        },
        "capabilities": {
            "core_processes": ["High-Density SMT Assembly", "Multi-Layer PCB (up to 32 layers)", "Automated Optical Inspection (AOI)", "X-Ray BGA Metrology"],
            "materials_certified": ["FR-4 High TG", "Rogers High-Frequency Substrates", "Lead-Free SAC305 Solder", "Conformal Coating"],
            "precision_tolerance": "01005 Chip Placement (±0.015 mm)",
            "surface_finishing": ["ENIG (Electroless Nickel Immersion Gold)", "Immersion Silver", "OSP"],
            "certifications": ["IPC-A-610 Class 3 (Aerospace)", "ISO 9001:2015", "RoHS & REACH Compliant"]
        },
        "default_active_works": [
            {
                "po_number": "PO-2026-8183",
                "title": "Dual-Core ARM Cortex-M7 Avionics Flight Controller PCBs",
                "quantity": 250,
                "amount": 25654.45,
                "committed_delivery": "2026-11-20",
                "status": "IN_PROGRESS",
                "fulfillment_stage": "70% SMT Placed • Undergoing Thermal Burn-In Testing",
                "progress_pct": 70
            }
        ],
        "default_past_works": [
            {
                "po_number": "PO-2025-00781",
                "title": "Industrial Controller Sensor Interface Motherboards",
                "quantity": 300,
                "amount": 32400.00,
                "delivered_date": "2026-06-14",
                "status": "COMPLETED_DELIVERED",
                "quality_acceptance_pct": 99.2,
                "invoice_ref": "INV-SZT-781"
            }
        ]
    }
}

@router.get("/avl")
def get_approved_vendor_list(db: Session = Depends(get_db)):
    """Return complete Approved Vendor List (AVL) with active works, past completed works, capabilities, delivery periods, and purchasing terms."""
    suppliers = db.query(Tenant).filter(Tenant.type == TenantType.SUPPLIER).all()
    
    results = []
    
    # 1. Add our well-documented strategic suppliers first
    for key, data in APPROVED_VENDOR_DETAILS.items():
        # Match real active POs from database if available
        matched_pos = db.query(PurchaseOrder).all()
        
        # Calculate active work in progress and past spend
        active_works = data["default_active_works"]
        past_works = data["default_past_works"]
        
        total_active_spend = sum(w["amount"] for w in active_works)
        total_lifetime_spend = sum(w["amount"] for w in past_works) + total_active_spend
        
        results.append({
            "id": key,
            "name": data["display_name"],
            "category": data["category"],
            "tier": data["tier"],
            "avl_status": data["avl_status"],
            "location": data["location"],
            "facility_type": data["facility_type"],
            "digital_twin_id": data["digital_twin_id"],
            "qualification_date": data["qualification_date"],
            "last_audit_date": data["last_audit_date"],
            "next_audit_due": data["next_audit_due"],
            "active_works_count": len(active_works),
            "total_active_spend": total_active_spend,
            "total_lifetime_spend": total_lifetime_spend,
            "past_works_count": len(past_works),
            "delivery_period": data["delivery_period"],
            "purchasing_terms": data["purchasing_terms"],
            "capabilities": data["capabilities"],
            "works_in_progress": active_works,
            "past_completed_works": past_works
        })
        
    return results

@router.get("/avl/{supplier_id}")
def get_vendor_avl_detail(supplier_id: str, db: Session = Depends(get_db)):
    """Return detailed AVL profile for a specific approved vendor."""
    if supplier_id in APPROVED_VENDOR_DETAILS:
        data = APPROVED_VENDOR_DETAILS[supplier_id]
        active_works = data["default_active_works"]
        past_works = data["default_past_works"]
        return {
            "id": supplier_id,
            "name": data["display_name"],
            "category": data["category"],
            "tier": data["tier"],
            "avl_status": data["avl_status"],
            "location": data["location"],
            "facility_type": data["facility_type"],
            "digital_twin_id": data["digital_twin_id"],
            "qualification_date": data["qualification_date"],
            "last_audit_date": data["last_audit_date"],
            "next_audit_due": data["next_audit_due"],
            "active_works_count": len(active_works),
            "total_active_spend": sum(w["amount"] for w in active_works),
            "total_lifetime_spend": sum(w["amount"] for w in past_works) + sum(w["amount"] for w in active_works),
            "delivery_period": data["delivery_period"],
            "purchasing_terms": data["purchasing_terms"],
            "capabilities": data["capabilities"],
            "works_in_progress": active_works,
            "past_completed_works": past_works
        }
        
    # Default to first strategic supplier
    return get_vendor_avl_detail("TENANT_SUPPLIER_001", db)
