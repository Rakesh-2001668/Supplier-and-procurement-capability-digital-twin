from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import datetime

router = APIRouter()

# Default Company-Centric Risk Profile for the Enterprise (e.g. XYZ Machinery Ltd)
COMPANY_CENTRIC_DATA = {
    "id": "xyz-machinery-ltd",
    "name": "XYZ Machinery Ltd",
    "legal_entity": "XYZ Machinery & Industrial Equipment Ltd",
    "category": "Heavy Industrial Machinery & Precision Engineering",
    "industry": "Industrial Equipment Manufacturing",
    "headquarters": "Industrial Zone Phase II, Precision Valley",
    "facility_type": "Primary OEM Manufacturing & Assembly Facility",
    "digital_twin_id": "TWIN-XYZ-MACHINERY-001",
    "composite_risk_score": 28,
    "risk_level": "LOW",
    "risk_status": "Optimal Operational Stability",
    "volatility_index": 13.8,  # % Amplitude of performance and risk swings
    "volatility_trend": "STABILIZING",
    "mom_change": -5,  # Risk decreased by 5 points this month (favorable)
    "financial_health": {
        "score": 89,
        "status": "Robust Capitalization",
        "altman_z_score": 3.28,
        "working_capital_ratio": 2.25,
        "dso_days": 34,
        "cash_runway_months": 18.5,
        "debt_to_equity": 0.42,
        "credit_rating": "AA- (Investment Grade)"
    },
    "operational_resilience": {
        "score": 93,
        "status": "High Production Reliability",
        "factory_utilization": 82.5,  # %
        "otif_delivery_rate": 96.2,   # % On-Time In-Full fulfillment
        "equipment_oee": 88.4,        # Overall Equipment Effectiveness %
        "mean_time_between_failures_hrs": 1420,
        "defect_rate_ppm": 85
    },
    "supply_chain_vulnerability": {
        "score": 22,
        "status": "Well-Diversified Supply Base",
        "single_source_dependencies": 2,  # Low single-source critical items
        "raw_material_hedging": "85% Hedged on Steel & Aluminum",
        "logistics_congestion_exposure": "Low (Multi-modal transit)",
        "critical_component_buffer_days": 45
    },
    "esg_compliance": {
        "score": 94,
        "status": "Certified Green Enterprise",
        "carbon_intensity_kg_co2": 16.4,
        "iso_9001_certified": True,
        "iso_14001_certified": True,
        "iso_45001_certified": True,
        "lost_time_injury_rate": 0.0
    },
    "trajectory_12m": [
        {"month": "Nov 25", "score": 36, "financial": 84, "operational": 86, "event": None, "type": None},
        {"month": "Dec 25", "score": 40, "financial": 82, "operational": 83, "event": "Year-end shipping container surge backlog", "type": "DOWNTURN"},
        {"month": "Jan 26", "score": 33, "financial": 86, "operational": 88, "event": None, "type": None},
        {"month": "Feb 26", "score": 49, "financial": 75, "operational": 76, "event": "Alloy steel spot price spike (+24% cost spike)", "type": "DOWNTURN"},
        {"month": "Mar 26", "score": 41, "financial": 80, "operational": 82, "event": None, "type": None},
        {"month": "Apr 26", "score": 30, "financial": 88, "operational": 90, "event": "Commissioning of automated robotic assembly cell", "type": "UPTURN"},
        {"month": "May 26", "score": 26, "financial": 91, "operational": 92, "event": "Long-term direct steel supply contract secured", "type": "UPTURN"},
        {"month": "Jun 26", "score": 45, "financial": 78, "operational": 79, "event": "Sub-tier actuator delivery delay (5-day plant bottleneck)", "type": "DOWNTURN"},
        {"month": "Jul 26", "score": 34, "financial": 85, "operational": 88, "event": "Secondary regional warehouse hub opened in Pune", "type": "UPTURN"},
        {"month": "Aug 26", "score": 25, "financial": 91, "operational": 94, "event": "ISO 9001 & AS9100 recertification passed with zero NRs", "type": "UPTURN"},
        {"month": "Sep 26", "score": 29, "financial": 89, "operational": 92, "event": None, "type": None},
        {"month": "Oct 26", "score": 28, "financial": 89, "operational": 93, "event": "Corporate working capital credit expansion approved", "type": "UPTURN"}
    ],
    "incident_log": [
        {
            "id": "INC-XYZ-104",
            "date": "Aug 16, 2026",
            "type": "UPTURN",
            "impact": "-9 pts Risk",
            "title": "Comprehensive ISO 9001 & AS9100 Quality Audit Clean Pass",
            "category": "Operational & Quality",
            "description": "Passed comprehensive third-party manufacturing audit with zero major findings, improving quality reliability benchmark."
        },
        {
            "id": "INC-XYZ-103",
            "date": "Jun 20, 2026",
            "type": "DOWNTURN",
            "impact": "+16 pts Risk",
            "title": "Tier-2 Actuator Sourcing Delay Bottleneck",
            "category": "Supply Chain Disruption",
            "description": "Component delays from overseas actuator sub-tier created an assembly line backlog, increasing operational delivery risk."
        },
        {
            "id": "INC-XYZ-102",
            "date": "Apr 08, 2026",
            "type": "UPTURN",
            "impact": "-11 pts Risk",
            "title": "Robotic Automation Cell Activated (Capacity +30%)",
            "category": "Manufacturing Innovation",
            "description": "Commissioned 4 robotic welding and assembly workstations, expanding machinery batch throughput by 30% and reducing unit labor hours."
        },
        {
            "id": "INC-XYZ-101",
            "date": "Feb 14, 2026",
            "type": "DOWNTURN",
            "impact": "+15 pts Risk",
            "title": "Alloy Steel Spot Market Price Surge",
            "category": "Financial & Material Cost",
            "description": "Unhedged steel spot market costs jumped 24% over 3 weeks, compressing gross margins before quarterly price indexing kicked in."
        }
    ],
    "predictive_forecast": {
        "forecast_30d": 24,
        "forecast_90d": 22,
        "direction": "STABLE_FAVORABLE",
        "confidence": 95,
        "summary": "AI predictive twin simulation projects stable performance for XYZ Machinery Ltd through Q4 2026 with 97%+ forecasted order fulfillment."
    },
    "internal_contingency_actions": [
        {"id": "ACT-1", "action": "Maintain 45-day safety buffer stock on critical hydraulic components", "priority": "Medium", "status": "Active"},
        {"id": "ACT-2", "action": "Lock in H1 2027 raw material commodity futures forward contracts", "priority": "High", "status": "Recommended"},
        {"id": "ACT-3", "action": "Conduct preventive maintenance audit on high-torque gear cutting cells", "priority": "Low", "status": "Scheduled"}
    ]
}

@router.get("/company")
def get_company_risk(tenant_id: Optional[str] = Query(None)):
    """Return company-centric risk intelligence for the enterprise (XYZ Machinery Ltd)."""
    return COMPANY_CENTRIC_DATA

@router.get("/dashboard")
def get_risk_dashboard():
    return {
        "company_name": COMPANY_CENTRIC_DATA["name"],
        "composite_risk_score": COMPANY_CENTRIC_DATA["composite_risk_score"],
        "volatility_index": COMPANY_CENTRIC_DATA["volatility_index"],
        "financial_score": COMPANY_CENTRIC_DATA["financial_health"]["score"],
        "operational_score": COMPANY_CENTRIC_DATA["operational_resilience"]["score"],
        "supply_chain_score": COMPANY_CENTRIC_DATA["supply_chain_vulnerability"]["score"]
    }

@router.get("/alerts")
def get_risk_alerts():
    return [
        {
            "id": "ALT-001",
            "title": "Tier-2 Actuator Lead Time Extension",
            "severity": "Medium",
            "impact": "+6 pts",
            "date": "2026-10-08",
            "description": "Lead time on precision hydraulic actuators extended from 14 to 22 days."
        },
        {
            "id": "ALT-002",
            "title": "Raw Steel Commodity Market Volatility",
            "severity": "Low",
            "impact": "+3 pts",
            "date": "2026-09-28",
            "description": "Index pricing fluctuated within ±4% bandwidth; within current hedge threshold."
        }
    ]
