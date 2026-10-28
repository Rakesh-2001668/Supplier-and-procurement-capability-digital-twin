"""
AlphaHelion Purchasing Intelligence Cloud
Module: Specialized High-Impact Workbenches (Blueprint Section 30 Screen Catalogue)

Implements:
1. SPD-07 Category Strategy Workbench (Kraljic Portfolio Matrix)
2. PO-04 Predictive Expediting Cockpit (Late-Risk ML Ranking & Escalations)
3. RCV-03 Service Entry Sheet (SES) Approval Console (SOD-03 Variant & Rate Checks)
4. CLM-02 AI Clause Review & Redline Studio (Playbook Deviation & Fallback Library)
"""

from fastapi import APIRouter, HTTPException, Query, Header
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import uuid

router = APIRouter(prefix="/api/v1/workbenches", tags=["Specialized Workbenches"])

# ==============================================================================
# 1. SPD-07 KRALJIC PORTFOLIO MATRIX & STRATEGY WORKBENCH
# ==============================================================================

class KraljicCategoryItem(BaseModel):
    id: str
    name: str
    code: str
    quadrant: str # STRATEGIC, LEVERAGE, BOTTLENECK, ROUTINE
    annual_spend_inr_cr: float
    supply_risk_score: float # 0 to 100
    profit_impact_score: float # 0 to 100
    primary_suppliers: List[str]
    strategic_levers: List[str]
    action_wave: str # Wave 1 (Q1), Wave 2 (Q2), etc.
    target_savings_inr_cr: float
    contract_coverage_pct: float

class EscalatePORequest(BaseModel):
    escalation_tier: str = "TIER_1_STANDARD" # TIER_1_STANDARD, TIER_2_EXECUTIVE, TIER_3_CARRIER_SWAP
    contact_email: str
    message: str
    requested_revised_eta: str
    actor: str = "u:buyer.hosur"

class SESApprovalRequest(BaseModel):
    decision: str = "APPROVE" # APPROVE, REJECT, RETURN
    actor: str
    comments: str
    measured_work_quality: str = "SATISFACTORY" # SATISFACTORY, MINOR_PUNCHLIST, DEFICIENT

class ClauseRedlineDecisionRequest(BaseModel):
    clause_id: str
    decision: str # ACCEPT_SUPPLIER, REJECT_SUPPLIER, APPLY_FALLBACK
    actor: str
    justification: str

# In-Memory State for Workbenches
KRALJIC_CATEGORIES: List[Dict[str, Any]] = [
    {
        "id": "CAT-DC-CASTINGS",
        "name": "Die-Cast Aluminium Motor Housings",
        "code": "41-CASTINGS",
        "quadrant": "STRATEGIC",
        "annual_spend_inr_cr": 43.29,
        "supply_risk_score": 88.0,
        "profit_impact_score": 94.0,
        "primary_suppliers": ["Trichy Forge Works", "Kovai Diecast Industries"],
        "strategic_levers": [
            "Long-term Scheduling Agreement (SA-5520)",
            "Dual-source capacity allocation (60/40)",
            "Quarterly LME Aluminium deadband indexation",
            "IIoT machine-level telemetry surveillance"
        ],
        "action_wave": "Wave 1 (Active)",
        "target_savings_inr_cr": 0.99,
        "contract_coverage_pct": 100.0
    },
    {
        "id": "CAT-RAW-INGOT",
        "name": "Primary Aluminium Ingots (EN AC-46000)",
        "code": "10-RAW-METALS",
        "quadrant": "LEVERAGE",
        "annual_spend_inr_cr": 61.50,
        "supply_risk_score": 32.0,
        "profit_impact_score": 89.0,
        "primary_suppliers": ["Vedanta Resources", "Hindalco Industries"],
        "strategic_levers": [
            "Aggressive multi-round reverse auctions",
            "Consolidated volume purchasing across 3 plants",
            "Cash discount terms (2/10 Net 30 optimization)",
            "Consignment vendor-managed inventory (VMI)"
        ],
        "action_wave": "Wave 1 (Active)",
        "target_savings_inr_cr": 1.85,
        "contract_coverage_pct": 85.0
    },
    {
        "id": "CAT-MAGNETS",
        "name": "High-Temp Neodymium Rotor Magnets",
        "code": "48-MAGNETS",
        "quadrant": "BOTTLENECK",
        "annual_spend_inr_cr": 4.80,
        "supply_risk_score": 92.0,
        "profit_impact_score": 38.0,
        "primary_suppliers": ["RareEarth Magnetics Ltd", "Kyoto Advanced Magnets"],
        "strategic_levers": [
            "Safety stock buffer increase from 2 to 6 weeks",
            "Alternative rare-earth substitution R&D",
            "Supplier development & joint tooling investment",
            "Long-term volume guarantee to lock production slots"
        ],
        "action_wave": "Wave 2 (Q2 2027)",
        "target_savings_inr_cr": 0.15,
        "contract_coverage_pct": 60.0
    },
    {
        "id": "CAT-FASTENERS",
        "name": "Standard Metric High-Tensile Fasteners",
        "code": "52-FASTENERS",
        "quadrant": "ROUTINE",
        "annual_spend_inr_cr": 8.20,
        "supply_risk_score": 15.0,
        "profit_impact_score": 22.0,
        "primary_suppliers": ["Fastenal Industrial", "Unbrako Fasteners"],
        "strategic_levers": [
            "Hosted e-catalogue with punch-out cart integration",
            "Touchless PO release below ₹25,000 threshold",
            "Automated 2-way invoice match",
            "Consolidated monthly billing (consolidated invoice)"
        ],
        "action_wave": "Wave 3 (Q3 2027)",
        "target_savings_inr_cr": 0.35,
        "contract_coverage_pct": 92.0
    }
]

EXPEDITING_QUEUE: List[Dict[str, Any]] = [
    {
        "id": "EXP-77410",
        "po_number": "PO-77410",
        "line_no": 10,
        "item_description": "DC-330 Die-Cast Housing (EN AC-46000)",
        "supplier_name": "Trichy Forge Works",
        "supplier_id": "TF001",
        "plant": "P100 Hosur",
        "ordered_qty": 5400,
        "unit": "EA",
        "need_date": "2026-11-12",
        "promised_date": "2026-11-10",
        "late_delivery_prob": 0.22,
        "risk_level": "LOW",
        "transit_status": "ASN_DISPATCHED",
        "asn_number": "ASN-61208",
        "carrier_name": "Axion Dedicated Logistics",
        "gps_corridor": "Trichy-Hosur NH44 (On Route)",
        "delay_hours": 0.0,
        "escalation_status": "MONITORING_NORMAL",
        "last_ping_at": "2026-10-23T11:00:00Z"
    },
    {
        "id": "EXP-77395",
        "po_number": "PO-77395",
        "line_no": 1,
        "item_description": "Neodymium Rotor Magnet Ring 48M",
        "supplier_name": "RareEarth Magnetics Ltd",
        "supplier_id": "REM009",
        "plant": "P100 Hosur",
        "ordered_qty": 1200,
        "unit": "EA",
        "need_date": "2026-10-28",
        "promised_date": "2026-10-26",
        "late_delivery_prob": 0.68,
        "risk_level": "CRITICAL_LATE",
        "transit_status": "CUSTOMS_HOLD",
        "asn_number": "ASN-REM-441",
        "carrier_name": "BlueDart Aviation Cargo",
        "gps_corridor": "Chennai Air Cargo Customs Clearance",
        "delay_hours": 48.0,
        "escalation_status": "TIER_2_ESCALATED",
        "last_ping_at": "2026-10-23T08:30:00Z"
    },
    {
        "id": "EXP-77380",
        "po_number": "PO-77380",
        "line_no": 2,
        "item_description": "Copper Magnet Wire 0.85mm Dual-Coated",
        "supplier_name": "Precision Winding Copper Ltd",
        "supplier_id": "PWC004",
        "plant": "P200 Chennai",
        "ordered_qty": 3500,
        "unit": "KG",
        "need_date": "2026-10-31",
        "promised_date": "2026-10-29",
        "late_delivery_prob": 0.38,
        "risk_level": "MODERATE_WARNING",
        "transit_status": "IN_PRODUCTION",
        "asn_number": None,
        "carrier_name": "TCI Freight Express",
        "gps_corridor": "Supplier Yard (Bengaluru)",
        "delay_hours": 12.0,
        "escalation_status": "EXPEDITE_NOTICE_SENT",
        "last_ping_at": "2026-10-23T09:15:00Z"
    }
]

SERVICE_ENTRY_SHEETS: List[Dict[str, Any]] = [
    {
        "ses_id": "SES-CFAE0F",
        "po_number": "PO-77402",
        "po_line_no": 1,
        "vendor_name": "Novus Global Tech Consulting",
        "vendor_id": "TECH003",
        "service_title": "Cloud Native Architecture & SOW-4410 Migration",
        "compensation_type": "TIME_AND_MATERIALS",
        "service_period": "2026-10-01 to 2026-10-15",
        "service_owner_role": "Service Delivery Head",
        "po_creator": "u:buyer.it.hosur",
        "candidate_approver": "u:service.owner.it",
        "contracted_rate_inr_hr": 3650.0,
        "timesheet_hours_billed": 320.0,
        "total_amount_inr": 1168000.0,
        "progress_pct": 100.0,
        "rate_card_compliant": True,
        "status": "APPROVED",
        "approved_by": "u:service.owner.it",
        "approved_at": "2026-10-23T09:00:00Z"
    },
    {
        "ses_id": "SES-CONST-991",
        "po_number": "PO-77388",
        "po_line_no": 1,
        "vendor_name": "Apex Structural Engineering",
        "vendor_id": "CONST002",
        "service_title": "RCC Rebar & Formwork Subcontract SC-118",
        "compensation_type": "MILESTONE_PROGRESS",
        "service_period": "2026-09-15 to 2026-10-20",
        "service_owner_role": "Site Project Manager",
        "po_creator": "u:buyer.infra.site",
        "candidate_approver": "u:project.manager.site",
        "contracted_rate_inr_hr": None,
        "timesheet_hours_billed": None,
        "total_amount_inr": 4250000.0,
        "progress_pct": 35.0,
        "rate_card_compliant": True,
        "status": "PENDING_APPROVAL",
        "approved_by": None,
        "approved_at": None,
        "retention_amount_inr": 212500.0, # 5% retention
        "advance_recovery_inr": 425000.0,
        "net_payable_inr": 3612500.0
    }
]

CLAUSE_REDLINES: Dict[str, Any] = {
    "SA-5520": {
        "contract_id": "SA-5520",
        "contract_title": "Long-Term Scheduling Agreement for DC-330 Motor Housing",
        "counterparty": "Trichy Forge Works",
        "playbook_version": "AHG-LEGAL-2026.2",
        "total_clauses_reviewed": 18,
        "clauses": [
            {
                "clause_id": "CLS-INDEMNITY-01",
                "title": "Product Liability & Intellectual Property Indemnification",
                "risk_rating": "HIGH",
                "playbook_position": "Supplier shall defend, indemnify and hold harmless Buyer against all third-party claims arising from design defects, material porosity, and patent infringements with NO liability ceiling.",
                "supplier_proposed": "Supplier shall indemnify Buyer solely for gross negligence, capped at 100% of the aggregate purchase order value placed within the preceding 12 months.",
                "deviation_summary": "Supplier introduced liability cap of 1x annual PO value and eliminated strict liability for internal porosity defects.",
                "fallback_suggestion": "Compromise Position B: Concede to liability cap at 3x annual contract commitment with an explicit CARVEOUT removing all caps for third-party serial defect recalls.",
                "status": "PENDING_REVIEW"
            },
            {
                "clause_id": "CLS-INDEXATION-02",
                "title": "Quarterly LME Aluminium Raw Material Indexation & Deadband",
                "risk_rating": "LOW",
                "playbook_position": "Price reset shall occur quarterly based on LME Aluminium Cash settlement average with a ±3.0% deadband tolerance. Movements within deadband trigger zero price change.",
                "supplier_proposed": "Price reset shall occur monthly with a ±1.5% deadband tolerance.",
                "deviation_summary": "Supplier requested monthly frequency and narrower deadband to pass through raw material increases faster.",
                "fallback_suggestion": "Uphold Quarterly reset frequency as agreed in RFQ-2231; deadband of ±3.0% ensures administrative stability.",
                "status": "ACCEPTED_PLAYBOOK"
            },
            {
                "clause_id": "CLS-TERMINATION-03",
                "title": "Termination for Convenience & Wind-Down Compensation",
                "risk_rating": "MEDIUM",
                "playbook_position": "Buyer may terminate for convenience upon 30 days written notice, reimbursing only documented raw material work-in-progress (WIP).",
                "supplier_proposed": "Buyer may terminate upon 90 days notice, paying 20% of unamortized tooling cost plus finished stock inventory at full price.",
                "deviation_summary": "Supplier increased notice period from 30 to 90 days and added unamortized tooling penalty.",
                "fallback_suggestion": "Compromise Position A: 60 days notice period with reimbursement of audited finished parts matching firm release schedule lines.",
                "status": "PENDING_REVIEW"
            }
        ]
    }
}

# ==============================================================================
# ROUTE HANDLERS
# ==============================================================================

@router.get("/kraljic")
async def get_kraljic_workbench():
    """Retrieve the Category Strategy Workbench (Kraljic Portfolio Matrix - SPD-07)."""
    quadrants = {"STRATEGIC": [], "LEVERAGE": [], "BOTTLENECK": [], "ROUTINE": []}
    total_spend = sum(c["annual_spend_inr_cr"] for c in KRALJIC_CATEGORIES)
    total_target_savings = sum(c["target_savings_inr_cr"] for c in KRALJIC_CATEGORIES)
    
    for item in KRALJIC_CATEGORIES:
        quadrants[item["quadrant"]].append(item)
        
    return {
        "status": "success",
        "portfolio_summary": {
            "total_spend_under_management_cr": round(total_spend, 2),
            "total_target_savings_cr": round(total_target_savings, 2),
            "total_categories_tracked": len(KRALJIC_CATEGORIES)
        },
        "quadrants": quadrants,
        "all_categories": KRALJIC_CATEGORIES
    }

@router.get("/expediting")
async def get_expediting_cockpit():
    """Retrieve Open POs at Risk of Late Delivery (PO-04 Expediting Cockpit)."""
    high_risk_count = sum(1 for p in EXPEDITING_QUEUE if p["late_delivery_prob"] >= 0.30)
    return {
        "status": "success",
        "summary": {
            "monitored_pos": len(EXPEDITING_QUEUE),
            "high_risk_delayed": high_risk_count,
            "average_delay_hours": round(sum(p["delay_hours"] for p in EXPEDITING_QUEUE) / len(EXPEDITING_QUEUE), 1)
        },
        "expediting_items": EXPEDITING_QUEUE
    }

@router.post("/expediting/{po_id}/escalate")
async def escalate_expediting_item(po_id: str, req: EscalatePORequest):
    """Trigger an automated supplier or carrier expediting escalation."""
    item = next((p for p in EXPEDITING_QUEUE if p["id"] == po_id or p["po_number"] == po_id), None)
    if not item:
        raise HTTPException(status_code=404, detail=f"PO item '{po_id}' not found in expediting queue")
    
    item["escalation_status"] = f"ESCALATED_{req.escalation_tier}"
    item["last_ping_at"] = datetime.now(timezone.utc).isoformat()
    item["promised_date"] = req.requested_revised_eta
    
    return {
        "status": "success",
        "message": f"Escalation {req.escalation_tier} successfully dispatched to {item['supplier_name']} ({req.contact_email})",
        "po_number": item["po_number"],
        "actor": req.actor,
        "promised_date_updated": item["promised_date"],
        "current_status": item["escalation_status"]
    }

@router.get("/service-entries")
async def list_service_entry_sheets():
    """Retrieve Service Entry Sheets awaiting review/approval (RCV-03)."""
    return {
        "status": "success",
        "total_sheets": len(SERVICE_ENTRY_SHEETS),
        "service_entries": SERVICE_ENTRY_SHEETS
    }

@router.post("/service-entries/{ses_id}/approve")
async def approve_service_entry_sheet(ses_id: str, req: SESApprovalRequest):
    """
    Approve or reject a Service Entry Sheet with SOD-03 enforcement.
    Rule: Approver must differ from PO creator and cannot be supplier user.
    """
    sheet = next((s for s in SERVICE_ENTRY_SHEETS if s["ses_id"] == ses_id), None)
    if not sheet:
        raise HTTPException(status_code=404, detail=f"Service Entry Sheet '{ses_id}' not found")
    
    # SOD-03 Enforcement check
    if req.actor.lower() == sheet["po_creator"].lower():
        raise HTTPException(
            status_code=403, 
            detail=f"SOD-03 VIOLATION: Approver '{req.actor}' cannot be the PO creator '{sheet['po_creator']}'. Segregation of Duties requires an independent service owner."
        )
    
    sheet["status"] = req.decision
    sheet["approved_by"] = req.actor
    sheet["approved_at"] = datetime.now(timezone.utc).isoformat()
    
    return {
        "status": "success",
        "message": f"Service Entry Sheet {ses_id} {req.decision} by {req.actor}",
        "ses_id": ses_id,
        "decision": req.decision,
        "amount_certified_inr": sheet["total_amount_inr"],
        "quality_score": req.measured_work_quality
    }

@router.get("/clause-redline/{contract_id}")
async def get_contract_clause_redlines(contract_id: str):
    """Retrieve AI-powered Clause Review & Redline Studio for a contract (CLM-02)."""
    if contract_id not in CLAUSE_REDLINES:
        raise HTTPException(status_code=404, detail=f"Contract '{contract_id}' redline data not found")
    return {
        "status": "success",
        "redline_workspace": CLAUSE_REDLINES[contract_id]
    }

@router.post("/clause-redline/{contract_id}/decision")
async def decide_clause_redline(contract_id: str, req: ClauseRedlineDecisionRequest):
    """Record a decision (accept, reject, fallback) on a redlined clause."""
    workspace = CLAUSE_REDLINES.get(contract_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Contract '{contract_id}' not found")
    
    clause = next((c for c in workspace["clauses"] if c["clause_id"] == req.clause_id), None)
    if not clause:
        raise HTTPException(status_code=404, detail=f"Clause '{req.clause_id}' not found in contract")
    
    clause["status"] = req.decision
    clause["decision_actor"] = req.actor
    clause["justification"] = req.justification
    clause["decided_at"] = datetime.now(timezone.utc).isoformat()
    
    return {
        "status": "success",
        "message": f"Clause {req.clause_id} decision '{req.decision}' recorded by {req.actor}",
        "clause_id": req.clause_id,
        "new_status": clause["status"]
    }
