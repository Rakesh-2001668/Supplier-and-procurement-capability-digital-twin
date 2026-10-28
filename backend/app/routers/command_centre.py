"""
Autonomous Operational Command Centre Router
Aggregates live multi-tier supplier digital twin intelligence, 6-axis predictive risk radar,
global facility geospatial operations, AI sentinel intervention streams, and autonomous decision execution.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import uuid

router = APIRouter(prefix="/api/v1/command-centre", tags=["Autonomous Command Centre"])

# -------------------------------------------------------------
# In-Memory Operational State
# -------------------------------------------------------------

DECISION_QUEUE = [
    {
        "id": "DEC-2026-001",
        "title": "Dual-Sourcing Parallel Allocation: PO-2025-00441",
        "category": "LOGISTICS_RESILIENCE",
        "priority": "CRITICAL",
        "threat_description": "Chennai Port container dwell variance exceeding 4.2 days threatens line-side assembly shutdown.",
        "recommended_action": "Split order: Reroute 30% urgent batch via Bangalore Air Cargo; secondary allocation to Precision AutoComp.",
        "financial_impact_usd": 144000.0,
        "sla_impact": "Prevents 4.5-day delivery delay",
        "status": "PENDING",
        "created_at": "2 hours ago"
    },
    {
        "id": "DEC-2026-002",
        "title": "Automated Smart Escrow Milestone Release: Batch #HPDC-8812",
        "category": "FINANCIAL_SETTLEMENT",
        "priority": "HIGH",
        "threat_description": "Zeiss CMM automated coordinate inspection passed with 18 PPM. Pre-funded escrow release ready.",
        "recommended_action": "Disburse 40% Phase-2 milestone ($355,200 USD) to Kovai Diecast Industries escrow account.",
        "financial_impact_usd": 355200.0,
        "sla_impact": "Zero SLA liquidated damages incurred",
        "status": "PENDING",
        "created_at": "3 hours ago"
    },
    {
        "id": "DEC-2026-003",
        "title": "Dodd-Frank 1502 CMRT Smelter Quarantine: CID002918",
        "category": "REGULATORY_COMPLIANCE",
        "priority": "HIGH",
        "threat_description": "Responsible Minerals Initiative flag on Mexican smelter CID002918 for unverified 3TG tin ingress.",
        "recommended_action": "Initiate electronic quarantine on busbar heats Lot #MEX-2024-44; request RMI RMAP re-audit declaration.",
        "financial_impact_usd": 85000.0,
        "sla_impact": "Ensures SEC Dodd-Frank audit compliance",
        "status": "PENDING",
        "created_at": "5 hours ago"
    },
    {
        "id": "DEC-2026-004",
        "title": "SLA Delay Penalty Execution: Copper Busbars (CON-2024-018)",
        "category": "CONTRACT_ENFORCEMENT",
        "priority": "MEDIUM",
        "threat_description": "Consignment delayed 3.2 days past scheduled transit threshold without approved force majeure notice.",
        "recommended_action": "Execute automated 2.5%/day liquidated damages deduction ($4,800 USD) directly from next invoice disbursement.",
        "financial_impact_usd": 4800.0,
        "sla_impact": "Contractual liquidated damages recovered",
        "status": "PENDING",
        "created_at": "7 hours ago"
    },
    {
        "id": "DEC-2026-005",
        "title": "Generative DFSC Radius Relaxation: CAD-ACT-7075",
        "category": "ENGINEERING_OPTIMIZATION",
        "priority": "LOW",
        "threat_description": "Tight internal fillet radius (R2.0mm) bottlenecks CNC milling capacity across Tier-1 machine shops.",
        "recommended_action": "Relax fillet radius from R2.0mm to R4.5mm; activates 130 additional pre-qualified suppliers.",
        "financial_impact_usd": 32000.0,
        "sla_impact": "Reduces unit production lead time from 8 to 3 weeks",
        "status": "PENDING",
        "created_at": "9 hours ago"
    }
]

OPERATIONAL_NODES = [
    {
        "id": "NODE-APEX-DE",
        "name": "Apex Precision Machining Ltd",
        "city": "Munich",
        "country": "Germany",
        "region": "EUROPE",
        "coordinates": {"lat": 48.137, "lng": 11.576},
        "risk_level": "LOW",
        "active_po_value_usd": 1250000.0,
        "capacity_utilization_pct": 88.0,
        "current_otif_pct": 98.4,
        "current_defect_ppm": 12,
        "status": "OPTIMAL",
        "alert": None
    },
    {
        "id": "NODE-KOVAI-IN",
        "name": "Kovai Diecast Industries",
        "city": "Coimbatore",
        "country": "India",
        "region": "ASIA_PACIFIC",
        "coordinates": {"lat": 11.016, "lng": 76.955},
        "risk_level": "ELEVATED",
        "active_po_value_usd": 888000.0,
        "capacity_utilization_pct": 82.0,
        "current_otif_pct": 96.8,
        "current_defect_ppm": 32,
        "status": "CHOKE_POINT_BUFFER_ACTIVE",
        "alert": "Chennai port congestion buffer active (+48h grace window applied)"
    },
    {
        "id": "NODE-PREC-IN",
        "name": "Precision AutoComp Ltd",
        "city": "Chennai",
        "country": "India",
        "region": "ASIA_PACIFIC",
        "coordinates": {"lat": 13.082, "lng": 80.270},
        "risk_level": "MODERATE",
        "active_po_value_usd": 680000.0,
        "capacity_utilization_pct": 91.0,
        "current_otif_pct": 94.2,
        "current_defect_ppm": 68,
        "status": "PPAP_REVISION",
        "alert": "IATF PPAP Level 3 documentation pending re-verification"
    },
    {
        "id": "NODE-COPP-MX",
        "name": "Apex Copper Formings",
        "city": "Monterrey",
        "country": "Mexico",
        "region": "NORTH_AMERICA",
        "coordinates": {"lat": 25.686, "lng": -100.316},
        "risk_level": "CRITICAL",
        "active_po_value_usd": 320000.0,
        "capacity_utilization_pct": 74.0,
        "current_otif_pct": 86.4,
        "current_defect_ppm": 92,
        "status": "EXPIRING_SLA",
        "alert": "Contract expiring in 17 days; CMRT smelter query flagged"
    },
    {
        "id": "NODE-PAC-CA",
        "name": "Pacific Aero Component Tech",
        "city": "Vancouver",
        "country": "Canada",
        "region": "NORTH_AMERICA",
        "coordinates": {"lat": 49.282, "lng": -123.120},
        "risk_level": "LOW",
        "active_po_value_usd": 2100000.0,
        "capacity_utilization_pct": 95.0,
        "current_otif_pct": 99.1,
        "current_defect_ppm": 4,
        "status": "ITAR_ACTIVE",
        "alert": None
    },
    {
        "id": "NODE-SGP-SG",
        "name": "SingaPrecision Micro-Optics",
        "city": "Jurong",
        "country": "Singapore",
        "region": "ASIA_PACIFIC",
        "coordinates": {"lat": 1.352, "lng": 103.819},
        "risk_level": "LOW",
        "active_po_value_usd": 940000.0,
        "capacity_utilization_pct": 89.0,
        "current_otif_pct": 99.4,
        "current_defect_ppm": 8,
        "status": "OPTIMAL",
        "alert": None
    }
]

# -------------------------------------------------------------
# Schemas
# -------------------------------------------------------------

class DecisionExecutionRequest(BaseModel):
    notes: Optional[str] = "Approved via Autonomous Operational Command Centre"
    actor: str = "Chief Procurement Officer"

class ExportBriefingRequest(BaseModel):
    region_filter: str = "GLOBAL"
    horizon_days: int = 90
    include_threat_matrix: bool = True

# -------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------

@router.get("/overview")
def get_command_centre_overview(region: Optional[str] = "GLOBAL"):
    """
    Returns platform-wide live telemetry, KPI ribbon, 6-axis capability health,
    and active AI sentinel interventions.
    """
    filtered_nodes = OPERATIONAL_NODES
    if region and region != "GLOBAL":
        filtered_nodes = [n for n in OPERATIONAL_NODES if n["region"] == region]

    total_exposure = sum(n["active_po_value_usd"] for n in filtered_nodes)
    avg_otif = sum(n["current_otif_pct"] for n in filtered_nodes) / max(1, len(filtered_nodes))
    avg_ppm = sum(n["current_defect_ppm"] for n in filtered_nodes) / max(1, len(filtered_nodes))

    return {
        "status": "success",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "region": region,
        "kpis": {
            "total_suppliers": 2845,
            "verified_digital_twins": 2316,
            "connected_iiot_cells": 1894,
            "at_risk_suppliers": 87,
            "open_rfqs_count": 124,
            "open_rfqs_value_usd": 4850000.0,
            "total_active_po_exposure_usd": round(total_exposure, 2),
            "platform_resilience_index": 92.4,
            "average_otif_pct": round(avg_otif, 1),
            "average_defect_ppm": round(avg_ppm, 1),
            "active_autonomous_interventions": 18,
            "active_choke_points": len([n for n in filtered_nodes if n["risk_level"] in ["ELEVATED", "CRITICAL"]])
        },
        "capability_health": [
            {"dimension": "Manufacturing", "score": 88, "unit": "CNC & HPDC", "status": "OPTIMAL", "color": "emerald"},
            {"dimension": "Quality Assurance", "score": 86, "unit": "32 Avg PPM", "status": "VERIFIED", "color": "emerald"},
            {"dimension": "Engineering & CAD", "score": 82, "unit": "DFSC AP242", "status": "ACTIVE", "color": "blue"},
            {"dimension": "Capacity Headroom", "score": 84, "unit": "18.4% Free", "status": "BALANCED", "color": "blue"},
            {"dimension": "Technology & IIoT", "score": 79, "unit": "Edge Telemetry", "status": "STREAMING", "color": "cyan"},
            {"dimension": "Financial Escrow", "score": 83, "unit": "Smart Escrow", "status": "FUNDED", "color": "purple"},
            {"dimension": "ESG Compliance", "score": 76, "unit": "CBAM & Scope 1-3", "status": "CONFORMANT", "color": "slate"}
        ],
        "threat_radar": {
            "axes": ["Financial", "Operational", "Quality", "Capacity", "Geopolitical", "ESG"],
            "current_scores": [74, 82, 88, 79, 68, 75],
            "predicted_90d_scores": [81, 76, 91, 86, 62, 80],
            "highest_threat_vector": "Geopolitical Transit Choke Points (Suez & Malacca)",
            "highest_resilience_vector": "Quality PPM & Coordinate CMM Verification"
        },
        "ai_sentinel_alerts": [
            {
                "id": "ALT-1",
                "title": "Chennai Port Customs Bottleneck (2.2 Days Delay)",
                "supplier": "Kovai Diecast Industries",
                "severity": "ELEVATED",
                "action_label": "Trigger 48h Escrow Buffer",
                "deep_link": "/contracts"
            },
            {
                "id": "ALT-2",
                "title": "CMRT Conflict Smelter CID002918 Flagged",
                "supplier": "Apex Copper Formings",
                "severity": "CRITICAL",
                "action_label": "Open Evidence Quarantine",
                "deep_link": "/evidence"
            },
            {
                "id": "ALT-3",
                "title": "Machine Headroom Optimization Opportunity (18% Idle)",
                "supplier": "Kovai Diecast Industries",
                "severity": "LOW",
                "action_label": "Allocate SOW-2026 Batch",
                "deep_link": "/negotiation"
            }
        ]
    }

@router.get("/nodes")
def get_operational_nodes(region: Optional[str] = None):
    """
    Returns global operational facility nodes with GPS coordinates, capacity, and live status.
    """
    nodes = OPERATIONAL_NODES
    if region and region != "GLOBAL":
        nodes = [n for n in OPERATIONAL_NODES if n["region"] == region]

    return {
        "status": "success",
        "total_nodes": len(nodes),
        "nodes": nodes
    }

@router.get("/decision-queue")
def get_decision_queue():
    """
    Returns pending autonomous decisions awaiting buyer execution or confirmation.
    """
    return {
        "status": "success",
        "pending_count": len([d for d in DECISION_QUEUE if d["status"] == "PENDING"]),
        "queue": DECISION_QUEUE
    }

@router.post("/decision-queue/{decision_id}/execute")
def execute_decision(decision_id: str, req: DecisionExecutionRequest):
    """
    Executes or approves an autonomous operational intervention in real time.
    """
    decision = next((d for d in DECISION_QUEUE if d["id"] == decision_id), None)
    if not decision:
        raise HTTPException(status_code=404, detail=f"Decision '{decision_id}' not found")

    decision["status"] = "EXECUTED"
    decision["executed_by"] = req.actor
    decision["executed_at"] = datetime.utcnow().isoformat() + "Z"
    decision["notes"] = req.notes

    return {
        "status": "success",
        "message": f"Autonomous decision '{decision_id}' successfully executed.",
        "decision": decision
    }

@router.get("/trends")
def get_performance_trends():
    """
    Returns 6-month historical trends plus 3-month AI predictive forecasting for
    OTIF, Defect PPM, and Quality Scores.
    """
    months = ["May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov (F)", "Dec (F)", "Jan (F)"]
    return {
        "status": "success",
        "months": months,
        "series": {
            "otif_pct": [94.2, 95.1, 95.8, 96.2, 96.8, 97.4, 98.1, 98.4, 98.8],
            "defect_ppm": [58, 52, 44, 38, 32, 28, 24, 20, 18],
            "quality_index": [81.5, 82.8, 84.0, 85.2, 86.8, 88.0, 89.2, 90.1, 91.0]
        }
    }

@router.post("/export")
def export_intelligence_briefing(req: ExportBriefingRequest):
    """
    Generates an executive intelligence briefing snapshot for C-level supply chain operations.
    """
    report_id = f"RPT-CMD-{uuid.uuid4().hex[:6].upper()}"
    return {
        "status": "success",
        "report_id": report_id,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "region_scope": req.region_filter,
        "horizon_days": req.horizon_days,
        "summary": f"Autonomous Command Centre Briefing ({req.region_filter}) covering 2,845 suppliers and $4.85M in active procurement.",
        "download_url": f"/api/v1/command-centre/reports/{report_id}.json"
    }
