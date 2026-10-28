"""
AlphaHelion Purchasing Intelligence Cloud
Module: Industry Template Packs (Blueprint Section 23, Tables 22 & 23, Technical Doc Section 4)

Provides the 6 Industry Configuration Packs:
1. Manufacturing & Industrial (Axion Mobility Systems)
2. Construction & Projects (Apex Infra & Civil Engineering)
3. IT & Professional Services (Novus Global Tech)
4. Logistics & Transportation (TransBharat Freight)
5. Healthcare & Life Sciences (Aethel Lifesciences)
6. General Enterprise / Indirect (Horizon Enterprises Corp)
"""

from fastapi import APIRouter, HTTPException, Query, Header
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import uuid

router = APIRouter(prefix="/api/v1/industry-templates", tags=["Industry Templates"])

class IndustryTemplateSummary(BaseModel):
    id: str
    name: str
    code: str
    icon: str
    tenant_name: str
    tenant_id: str
    plants_or_locations: List[str]
    demand_source: str
    sourcing_type: str
    contract_form: str
    receipt_method: str
    match_rule: str
    special_controls: List[str]
    nuance_description: str
    demo_case_summary: str
    kpis: Dict[str, str]
    is_active: bool = False

class IndustrySwitchRequest(BaseModel):
    template_id: str
    actor: str = "Chief Procurement Officer"
    notes: Optional[str] = "Industry template switch requested from Executive Control Console"

INDUSTRY_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "MANUFACTURING": {
        "id": "MANUFACTURING",
        "name": "Manufacturing & Industrial",
        "code": "IND-MFG-01",
        "icon": "🏭",
        "tenant_name": "Axion Mobility Systems Pvt Ltd",
        "tenant_id": "tenant-axion-mfg-100",
        "plants_or_locations": ["P100 Hosur (Main Plant)", "P200 Chennai (Foundry & Die-Cast)"],
        "demand_source": "MRP from sales forecast and customer orders; Kanban / reorder for C-parts",
        "sourcing_type": "RFQ with should-cost (die-casting, forging, machining), PPAP/IATF gated, capacity-constrained dual sourcing",
        "contract_form": "Scheduling agreements (SA-5520), quantity contracts, metal-index price clauses",
        "receipt_method": "Goods Receipt with mandatory quality inspection (QL-2210), batch traceability, ASN mandatory",
        "match_rule": "3-way match (PO × GR × Invoice), ERS for scheduling agreements, credit note resolution (CN-TF-221)",
        "special_controls": [
            "PPAP / IATF-16949 automotive qualification gate",
            "Quota arrangements with running quota counters (60/40 split)",
            "Safety stock buffer evaluation in net-change MRP",
            "LME Aluminium quarterly indexation with ±3.0% deadband"
        ],
        "nuance_description": "Planned orders convert to PRs automatically; price variance (PPV) against standard cost is the primary savings lens.",
        "demo_case_summary": "Axion Signature Case: Net-change MRP MR-1043 -> PLO-55821 -> RFQ-2231 -> SA-5520 -> PO-77410 touchless release -> ASN-61208 -> GR-90231 (20 porosity defects quarantined under QL-2210) -> INV-TF-8812 -> Credit Note CN-TF-221 -> Idempotent SAP S/4HANA Doc 5100004421 -> SV-0412 realised savings ₹0.38 Cr.",
        "kpis": {
            "OTIF Delivery": "98.8%",
            "Defect PPM": "18 PPM",
            "Inventory Turns": "14.2x",
            "Purchase Price Variance (PPV)": "₹0.38 Cr favorable"
        },
        "sample_document": {
            "doc_type": "SCHEDULING_AGREEMENT",
            "doc_id": "SA-5520",
            "item": "MAT-DC330-HSG Die-Cast Motor Housing",
            "base_price": 398.0,
            "currency": "INR",
            "index_clause": "LME Aluminium Cash quarterly reset with ±3.0% deadband",
            "lead_time_days": 14
        }
    },
    "CONSTRUCTION": {
        "id": "CONSTRUCTION",
        "name": "Construction & Projects",
        "code": "IND-CONST-02",
        "icon": "🏗️",
        "tenant_name": "Apex Infra & Civil Engineering Ltd",
        "tenant_id": "tenant-apex-infra-200",
        "plants_or_locations": ["Site-BLR Kempegowda Terminal 3", "Site-HYD Metro Corridor Line 2"],
        "demand_source": "Project / WBS plan, BOQ (Bill of Quantities), site engineer material requisitions",
        "sourcing_type": "Tender packages by trade (Civil, Structural Steel, MEP), technical + commercial two-envelope evaluation, retention terms",
        "contract_form": "Subcontract agreements (SC-118), trade rate contracts, framework call-off with variation clauses",
        "receipt_method": "Site GR for bulk materials, measurement-based Service Entry Sheets (SES progress %), equipment hire timesheets",
        "match_rule": "3-way match vs SES with 5% retention deduction and mobilization advance recovery",
        "special_controls": [
            "WBS budget hard stop on submit",
            "Contract variation orders (amendments) required instead of new POs",
            "5.0% performance retention held until defect liability period",
            "Performance bank guarantee (PBG) validation gate"
        ],
        "nuance_description": "Every single line item carries a mandatory WBS element; variations are governed contract amendments, never unbudgeted new POs.",
        "demo_case_summary": "WBS C-2207 'Tower B Structure', Subcontract SC-118 rebar & formwork. Measurement SES submitted at 35% progress: Gross ₹42,50,000, 5% retention ₹2,12,500 withheld, Advance recovery ₹4,25,000, Net certified ₹36,12,500.",
        "kpis": {
            "Cost to Complete": "₹18.4 Cr",
            "Commitments vs Budget": "91.2%",
            "Variation Rate": "3.4%",
            "Retention Value Held": "₹1.45 Cr"
        },
        "sample_document": {
            "doc_type": "SUBCONTRACT_AGREEMENT",
            "doc_id": "SC-118",
            "wbs_element": "WBS-C2207-TOWER-B",
            "trade": "Reinforced Cement Concrete (RCC) & Formwork",
            "contract_value": 12500000.0,
            "retention_pct": 5.0,
            "certified_progress_pct": 35.0
        }
    },
    "IT_SERVICES": {
        "id": "IT_SERVICES",
        "name": "IT & Professional Services",
        "code": "IND-TECH-03",
        "icon": "💻",
        "tenant_name": "Novus Global Tech & Consulting",
        "tenant_id": "tenant-novus-tech-300",
        "plants_or_locations": ["CC-8100 Cloud Platform Engineering", "CC-8200 Enterprise AI Labs"],
        "demand_source": "Project resourcing plans, software license renewal calendars, employee hardware & SaaS requests",
        "sourcing_type": "RFP with technical capability scoring, role rate-card benchmarking, vendor security risk review",
        "contract_form": "Master Services Agreement (MSA) + Statement of Work (SOW), role rate cards (RC-22), license agreements with auto-renewal clauses",
        "receipt_method": "Timesheet- or milestone-based Service Entry Sheets (SES); software license seat entitlement confirmation",
        "match_rule": "3-way match against approved timesheet SES; 2-way match for SaaS subscriptions",
        "special_controls": [
            "InfoSec & Data-Privacy compliance assessment (SOC2 / ISO 27001)",
            "Unused software seat detection 120 days prior to contract renewal",
            "Over-rate card billing blocked at SES submission",
            "IP assignment and non-solicitation clause audit"
        ],
        "nuance_description": "Auto-renewal dates drive proactive sourcing; unused licenses are flagged to downsize commitments before renewal lock-in.",
        "demo_case_summary": "SOW-4410 Cloud Migration T&M under Rate Card RC-22. Cloud Architect (160 hrs @ ₹4,500/hr) + DevOps Lead (160 hrs @ ₹2,800/hr). Bi-weekly timesheet SES 320 hrs (₹11,68,000) matched with zero rate drift.",
        "kpis": {
            "Rate Card Compliance": "99.1%",
            "License Utilization": "82.4%",
            "Auto-Renewal Savings": "₹1.2 Cr",
            "Consultant On-Time Invoicing": "96.5%"
        },
        "sample_document": {
            "doc_type": "STATEMENT_OF_WORK",
            "doc_id": "SOW-4410",
            "rate_card_ref": "RC-22",
            "engagement": "Cloud Native Data Platform Migration",
            "approved_hours": 320,
            "blended_hourly_rate": 3650.0,
            "infosec_approval": "APPROVED_SOC2_TYPE2"
        }
    },
    "LOGISTICS": {
        "id": "LOGISTICS",
        "name": "Logistics & Transportation",
        "code": "IND-LOG-04",
        "icon": "🚚",
        "tenant_name": "TransBharat Freight & Cold Supply",
        "tenant_id": "tenant-transbharat-400",
        "plants_or_locations": ["Hub-BOM Bhiwandi Central", "Hub-DEL Manesar Logistics Park", "Hub-CHE Sriperumbudur Gateway"],
        "demand_source": "Lane volume forecasts, ERP sales shipment orders, emergency spot transport requisitions",
        "sourcing_type": "National lane tenders, mini-bids, electronic spot reverse auctions for sudden volume spikes",
        "contract_form": "Transport rate contracts by origin-destination lane with dynamic fuel surcharge indexation",
        "receipt_method": "Electronic Proof of Delivery (e-POD) with consignee digital signature and GPS transit geofence timestamp",
        "match_rule": "Automated Freight Audit: Contracted Base Rate × Actual Distance/Weight + Verified Fuel Index vs Invoice",
        "special_controls": [
            "Carrier compliance check: motor insurance, valid permits, driver safety rating",
            "Accessorial detention charge verification using GPS dock geofence time",
            "Demurrage validation and unauthorized route toll rejection",
            "Dynamic diesel indexation calculation based on national oil benchmark"
        ],
        "nuance_description": "Invoices are validated against contracted lane rates and verified shipment telematics, not against a static PO quantity.",
        "demo_case_summary": "Lane CHE -> PNQ 32 ft Multi-Axle (1,150 km). Base rate ₹54.00/km (₹62,100) + diesel index adjustment (+₹4,200) = ₹66,300. Automated audit validated e-POD signature and blocked ₹1,800 unsupported detention fee.",
        "kpis": {
            "Cost per Tonne-Km": "₹2.45 / t-km",
            "On-Time Delivery (OTD)": "97.6%",
            "Freight Audit Recoveries": "₹48.2 Lakhs",
            "Detention Dispute Rate": "1.8%"
        },
        "sample_document": {
            "doc_type": "LANE_RATE_CONTRACT",
            "doc_id": "LRC-CHE-PNQ-88",
            "origin": "Chennai (CHE)",
            "destination": "Pune (PNQ)",
            "distance_km": 1150,
            "base_rate_per_km": 54.0,
            "fuel_index_baseline": 91.50,
            "current_fuel_index": 97.20
        }
    },
    "HEALTHCARE": {
        "id": "HEALTHCARE",
        "name": "Healthcare & Life Sciences",
        "code": "IND-HEALTH-05",
        "icon": "🏥",
        "tenant_name": "Aethel Lifesciences & Hospitals Ltd",
        "tenant_id": "tenant-aethel-life-500",
        "plants_or_locations": ["Hosp-DEL Saket Multi-Speciality", "Lab-BLR Electronic City Research"],
        "demand_source": "Hospital par levels, automated consumption signals, clinical surgery schedules, formulary lists",
        "sourcing_type": "Value-Analysis Committee (VAC) review, GPO collective tenders, regulatory bio-equivalence evaluations",
        "contract_form": "GPO price agreements, consignment contracts, cold-chain SLA maintenance agreements",
        "receipt_method": "Goods receipt with batch/lot numbers, expiration date capture, and cold-chain temperature telemetry log",
        "match_rule": "3-way match for consumables; consignment settlement (ERS) triggered strictly upon patient implantation record",
        "special_controls": [
            "Mandatory regulatory validation (CDSCO / USFDA / CE mark)",
            "Lot-level recall traceability from warehouse rack to patient procedure ID",
            "Cold-chain temperature deviation hold (< 2°C or > 8°C auto-quarantine)",
            "Clinical head sign-off required for non-formulary medical items"
        ],
        "nuance_description": "Clinical sign-off is mandatory; consignment stock stays off balance sheet until patient implantation creates self-billed liability.",
        "demo_case_summary": "Consignment Orthopedic Titanium Implant KN-77. Stored in Hosur cath lab. Procedure recorded for Patient #9021; barcode scan auto-triggered replenishment PO for 15 units (₹18,75,000) and Evaluated Receipt Settlement (ERS) self-billing.",
        "kpis": {
            "Formulary Compliance": "96.4%",
            "Expiry Write-Off Rate": "< 0.2%",
            "Stock-Out Incidents": "0 incidents",
            "Cold-Chain Compliance": "99.94%"
        },
        "sample_document": {
            "doc_type": "CONSIGNMENT_AGREEMENT",
            "doc_id": "CSA-KN77-LIFE",
            "device": "KN-77 Orthopedic Knee Implant Kit",
            "unit_price": 125000.0,
            "temp_range_celsius": "2°C - 8°C",
            "regulatory_license": "CDSCO/MD/2026/88412",
            "billing_trigger": "PATIENT_IMPLANTATION"
        }
    },
    "GENERAL_ENTERPRISE": {
        "id": "GENERAL_ENTERPRISE",
        "name": "General Enterprise (Indirect Spend)",
        "code": "IND-GEN-06",
        "icon": "🏢",
        "tenant_name": "Horizon Enterprises Corp",
        "tenant_id": "tenant-horizon-corp-600",
        "plants_or_locations": ["HQ-MUM Nariman Point Mumbai", "RO-GGN Cyber City Gurugram"],
        "demand_source": "Employee self-service requisitions, departmental indirect expense budgets, IT service desk tickets",
        "sourcing_type": "Quick quotes, 3-quote policy for free text > ₹25,000, preferred supplier catalog enablement",
        "contract_form": "Hosted catalog agreements, framework master service agreements, corporate corporate rate cards",
        "receipt_method": "Desktop confirmation by requester; receipt-less auto-clearing for micro-purchases < ₹10,000",
        "match_rule": "2-way match for catalog items < ₹25,000; 3-way match for items exceeding threshold",
        "special_controls": [
            "Corporate purchasing card (P-Card) limit and category controls",
            "Guided buying policy prompts enforcing internal catalog reuse",
            "Single-step manager approval for standard IT equipment",
            "Automated cXML punch-out cart integration (e.g. Dell, OfficeSupplies)"
        ],
        "nuance_description": "Guided buying and policy prompts handle 90% of spend touchlessly; buyers intervene only on exceptions and high-value sourcing.",
        "demo_case_summary": "Employee IT Requisition: Dell Latitude 5440 laptop via cXML Punch-Out (₹78,500). System matched existing corporate price agreement, validated departmental IT budget, and auto-routed for single-click manager approval.",
        "kpis": {
            "Catalog Adoption": "88.6%",
            "PR-to-PO Cycle Time": "4.2 Hours",
            "Maverick Spend": "3.8%",
            "First-Pass Match": "94.2%"
        },
        "sample_document": {
            "doc_type": "CATALOG_PUNCHOUT_CART",
            "doc_id": "PUNCH-DELL-8812",
            "catalog_vendor": "Dell Technologies Corporate Store",
            "item_description": "Dell Latitude 5440 (16GB RAM, 512GB SSD, Intel i7)",
            "negotiated_price": 78500.0,
            "punchout_protocol": "cXML 1.2.042",
            "match_tolerance": "2-WAY_AUTO_CLEAR"
        }
    }
}

ACTIVE_TEMPLATE_SESSION = {
    "current_id": "MANUFACTURING",
    "switched_at": datetime.now(timezone.utc).isoformat(),
    "actor": "Chief Procurement Officer"
}

@router.get("", response_model=List[IndustryTemplateSummary])
async def list_industry_templates():
    """List all 6 industry configuration templates with active status."""
    result = []
    current_active = ACTIVE_TEMPLATE_SESSION["current_id"]
    for t_id, t_data in INDUSTRY_TEMPLATES.items():
        summary = IndustryTemplateSummary(
            id=t_data["id"],
            name=t_data["name"],
            code=t_data["code"],
            icon=t_data["icon"],
            tenant_name=t_data["tenant_name"],
            tenant_id=t_data["tenant_id"],
            plants_or_locations=t_data["plants_or_locations"],
            demand_source=t_data["demand_source"],
            sourcing_type=t_data["sourcing_type"],
            contract_form=t_data["contract_form"],
            receipt_method=t_data["receipt_method"],
            match_rule=t_data["match_rule"],
            special_controls=t_data["special_controls"],
            nuance_description=t_data["nuance_description"],
            demo_case_summary=t_data["demo_case_summary"],
            kpis=t_data["kpis"],
            is_active=(t_id == current_active)
        )
        result.append(summary)
    return result

@router.get("/active")
async def get_active_industry_template():
    """Get the currently active industry template and its live runtime configuration."""
    current_active = ACTIVE_TEMPLATE_SESSION["current_id"]
    template_data = INDUSTRY_TEMPLATES.get(current_active)
    if not template_data:
        raise HTTPException(status_code=404, detail="Active template not found")
    return {
        "status": "success",
        "active_template": template_data,
        "session": ACTIVE_TEMPLATE_SESSION
    }

@router.get("/{template_id}")
async def get_industry_template_detail(template_id: str):
    """Retrieve complete deep-dive details for a specific industry template."""
    key = template_id.upper()
    if key not in INDUSTRY_TEMPLATES:
        raise HTTPException(status_code=404, detail=f"Industry template '{template_id}' not found. Available: {list(INDUSTRY_TEMPLATES.keys())}")
    
    data = INDUSTRY_TEMPLATES[key].copy()
    data["is_active"] = (key == ACTIVE_TEMPLATE_SESSION["current_id"])
    return {
        "status": "success",
        "template": data
    }

@router.post("/switch")
async def switch_industry_template(req: IndustrySwitchRequest):
    """
    Switch active platform industry template.
    Reconfigures tenancy, approval rules, DMN thresholds, and document templates.
    """
    key = req.template_id.upper()
    if key not in INDUSTRY_TEMPLATES:
        raise HTTPException(status_code=400, detail=f"Invalid template ID '{req.template_id}'. Must be one of {list(INDUSTRY_TEMPLATES.keys())}")
    
    ACTIVE_TEMPLATE_SESSION["current_id"] = key
    ACTIVE_TEMPLATE_SESSION["switched_at"] = datetime.now(timezone.utc).isoformat()
    ACTIVE_TEMPLATE_SESSION["actor"] = req.actor
    
    target = INDUSTRY_TEMPLATES[key]
    return {
        "status": "success",
        "message": f"Successfully activated Industry Template: {target['name']} ({target['code']})",
        "active_template_id": key,
        "tenant_name": target["tenant_name"],
        "tenant_id": target["tenant_id"],
        "switched_at": ACTIVE_TEMPLATE_SESSION["switched_at"],
        "reconfigured_modules": [
            "M02 Demand Planning & Reorder Models",
            "M04 Guided Buying & Approval Rules",
            "M05 Strategic Sourcing & Bid Criteria",
            "M07 Contract Lifecycle & Indexation Terms",
            "M09 Receiving, Timesheets & Inspection Rules",
            "M10 Invoicing Match Engine & Retentions"
        ]
    }
