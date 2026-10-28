"""
AI Supplier Continuous Development & 8D Corrective Action (CAPA) Router
Handles structured supplier development plans (CDP), 8D root-cause problem solving,
interim containment actions (ICA), permanent corrective actions (PCA), milestone validation,
and supplier capability enablement.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import uuid

router = APIRouter()

# -------------------------------------------------------------
# In-Memory Database: Continuous Development Plans (CDP)
# -------------------------------------------------------------

DEVELOPMENT_PLANS_DB: Dict[str, Dict[str, Any]] = {
    "DEV-PLAN-001": {
        "id": "DEV-PLAN-001",
        "title": "5-Axis High-Precision CNC & Sub-Micron CMM Capability Upgrade",
        "supplier_id": "TWIN-APEX-001",
        "supplier_name": "Apex Precision Machining Ltd",
        "location": "Munich, Germany",
        "tier": "Tier-1 Strategic Aerospace",
        "focus_area": "Manufacturing Capability",
        "focus_color": "blue",
        "lead_auditor": "Dr. Klaus Weber (Aerospace Quality Director)",
        "supplier_lead": "Hans Zimmer (Master Machining Lead)",
        "start_date": "2025-01-15",
        "target_date": "2025-12-31",
        "progress_pct": 72,
        "status": "IN_PROGRESS",
        "strategic_priority": "CRITICAL",
        "baseline_metric": "Cp/Cpk 1.33, max envelope 800mm, tolerance ±5.0 μm",
        "target_metric": "Cp/Cpk 1.85, 5-axis 1200mm Hermle C42, tolerance ±1.2 μm",
        "investment_budget_usd": 480000,
        "co_investment_pct": 50,
        "description": "Joint OEM-supplier capital investment to install Hermle C42 5-axis dynamic milling centre and Zeiss Contura multi-sensor coordinate measuring machine to achieve flight-critical hydraulic spool tolerances.",
        "milestones": [
            {
                "id": "MS-001",
                "title": "Hermle C42 5-Axis Machine Delivery & Thermal Foundation",
                "target_date": "2025-02-28",
                "completed_date": "2025-02-25",
                "status": "COMPLETED",
                "verification_proof": "Installation signoff report #INST-HERMLE-4491"
            },
            {
                "id": "MS-002",
                "title": "Laser Interferometer Volumetric Calibration (ISO 10360-2)",
                "target_date": "2025-04-15",
                "completed_date": "2025-04-10",
                "status": "COMPLETED",
                "verification_proof": "Zeiss Contura Calibration Cert #ZEISS-CAL-2025-88"
            },
            {
                "id": "MS-003",
                "title": "AS9102 Rev B First Article Inspection (FAI) Titanium Impellers",
                "target_date": "2025-08-30",
                "completed_date": None,
                "status": "IN_PROGRESS",
                "verification_proof": "Pending 30-piece FAI batch run"
            },
            {
                "id": "MS-004",
                "title": "Full-Rate Production Release & Cp/Cpk Verification > 1.67",
                "target_date": "2025-12-15",
                "completed_date": None,
                "status": "PENDING",
                "verification_proof": None
            }
        ],
        "kpi_improvements": [
            {"metric": "Machining Accuracy", "baseline": "±5.0 μm", "current": "±1.8 μm", "target": "±1.2 μm"},
            {"metric": "Process Capability (Cpk)", "baseline": "1.33", "current": "1.62", "target": "1.85"},
            {"metric": "Cycle Time per Impeller", "baseline": "42 mins", "current": "31 mins", "target": "26 mins"},
            {"metric": "Scrap Rate", "baseline": "3.8%", "current": "1.1%", "target": "< 0.5%"}
        ],
        "audit_logs": [
            {"timestamp": "2025-01-15T09:00:00Z", "actor": "Dr. Klaus Weber", "action": "PLAN_INITIALIZED", "notes": "Charter signed by OEM VP of Sourcing and Apex Managing Director."},
            {"timestamp": "2025-02-25T14:30:00Z", "actor": "Hans Zimmer", "action": "MILESTONE_COMPLETED", "notes": "MS-001 verified on-site in Munich facility."},
            {"timestamp": "2025-04-10T11:15:00Z", "actor": "Dr. Klaus Weber", "action": "MILESTONE_COMPLETED", "notes": "Zeiss calibration audit passed with zero volumetric drift."}
        ]
    },
    "DEV-PLAN-002": {
        "id": "DEV-PLAN-002",
        "title": "Zero Defect & Statistical Process Control (SPC) Quality Transformation",
        "supplier_id": "TWIN-PREC-002",
        "supplier_name": "Precision AutoComp Ltd",
        "location": "Chennai, India",
        "tier": "Tier-1 Automotive / Defense",
        "focus_area": "Quality Engineering",
        "focus_color": "emerald",
        "lead_auditor": "R. Ramanathan (Lead Automotive Quality Auditor)",
        "supplier_lead": "P. Swaminathan (VP Operations)",
        "start_date": "2025-02-01",
        "target_date": "2025-11-30",
        "progress_pct": 58,
        "status": "IN_PROGRESS",
        "strategic_priority": "HIGH",
        "baseline_metric": "420 PPM defect rate, manual post-machining batch sampling",
        "target_metric": "< 25 PPM, inline optical laser vision inspection & real-time SPC",
        "investment_budget_usd": 220000,
        "co_investment_pct": 30,
        "description": "Transition automotive powertrain shaft manufacturing line from retrospective batch inspection to inline Keyence optical laser micrometer telemetry with automated tool wear feedback.",
        "milestones": [
            {
                "id": "MS-001",
                "title": "Keyence Inline Laser Vision Micrometer Installation",
                "target_date": "2025-03-31",
                "completed_date": "2025-03-28",
                "status": "COMPLETED",
                "verification_proof": "Hardware signoff #KEYENCE-LINE3-CHK"
            },
            {
                "id": "MS-002",
                "title": "Real-time SPC Edge Gateway Telemetry Integration",
                "target_date": "2025-06-15",
                "completed_date": "2025-06-10",
                "status": "COMPLETED",
                "verification_proof": "IoT Edge Gateway live stream verified"
            },
            {
                "id": "MS-003",
                "title": "90-Day Continuous Production Run < 30 PPM Defect Rate",
                "target_date": "2025-09-30",
                "completed_date": None,
                "status": "IN_PROGRESS",
                "verification_proof": None
            },
            {
                "id": "MS-004",
                "title": "IATF 16949 Clause 10.2 Continuous Improvement Audit",
                "target_date": "2025-11-20",
                "completed_date": None,
                "status": "PENDING",
                "verification_proof": None
            }
        ],
        "kpi_improvements": [
            {"metric": "Defect Rate (PPM)", "baseline": "420 PPM", "current": "88 PPM", "target": "< 25 PPM"},
            {"metric": "Inspection Throughput", "baseline": "45 parts/hr", "current": "160 parts/hr", "target": "200 parts/hr"},
            {"metric": "Rework Cost / Month", "baseline": "$18,500", "current": "$4,200", "target": "< $1,000"}
        ],
        "audit_logs": [
            {"timestamp": "2025-02-01T10:00:00Z", "actor": "R. Ramanathan", "action": "PLAN_INITIALIZED", "notes": "Charter approved for Chennai Line 3 zero-defect retrofit."}
        ]
    },
    "DEV-PLAN-003": {
        "id": "DEV-PLAN-003",
        "title": "ITAR Level 2 Defense Article Enclave & FIPS 140-3 Hardware Root of Trust",
        "supplier_id": "TWIN-AERO-004",
        "supplier_name": "Pacific Aero Component Tech",
        "location": "Vancouver, Canada",
        "tier": "Tier-1 Defense Avionics",
        "focus_area": "Cybersecurity & Export Control",
        "focus_color": "purple",
        "lead_auditor": "Sarah Jenkins (Defense Compliance VP)",
        "supplier_lead": "Marc Tremblay (Chief Security Officer)",
        "start_date": "2025-01-20",
        "target_date": "2025-10-31",
        "progress_pct": 85,
        "status": "ON_TRACK",
        "strategic_priority": "CRITICAL",
        "baseline_metric": "ITAR physical isolation with legacy air-gap workstations",
        "target_metric": "CMMC Level 2 / NIST SP 800-171 enclave with HSM key injection",
        "investment_budget_usd": 310000,
        "co_investment_pct": 40,
        "description": "Establish defense avionics cryptographic programming enclave certified under FIPS 140-3 Level 3 to support military unmanned aerial vehicle secure flight-control firmware.",
        "milestones": [
            {
                "id": "MS-001",
                "title": "Physical Faraday Shielded Security Room Construction",
                "target_date": "2025-03-15",
                "completed_date": "2025-03-01",
                "status": "COMPLETED",
                "verification_proof": "Physical security audit signoff #PAC-FARADAY-01"
            },
            {
                "id": "MS-002",
                "title": "Thales Luna HSM FIPS 140-3 Key Injection Commissioning",
                "target_date": "2025-05-30",
                "completed_date": "2025-05-20",
                "status": "COMPLETED",
                "verification_proof": "NIST CMVP verification token"
            },
            {
                "id": "MS-003",
                "title": "Third-Party CMMC Level 2 DIBCAC Mock Assessment",
                "target_date": "2025-08-15",
                "completed_date": "2025-08-12",
                "status": "COMPLETED",
                "verification_proof": "DIBCAC Score: 110/110 SPRS compliance"
            },
            {
                "id": "MS-004",
                "title": "Final DDTC Form DSP-5 Defense Export Authorization",
                "target_date": "2025-10-15",
                "completed_date": None,
                "status": "IN_PROGRESS",
                "verification_proof": None
            }
        ],
        "kpi_improvements": [
            {"metric": "NIST SP 800-171 Score", "baseline": "62 / 110", "current": "110 / 110", "target": "110 / 110"},
            {"metric": "Key Injection Security", "baseline": "Software Token", "current": "FIPS 140-3 HSM", "target": "FIPS 140-3 HSM"},
            {"metric": "Audit Readiness", "baseline": "Tier 3", "current": "Tier 1", "target": "Tier 1 Certified"}
        ],
        "audit_logs": [
            {"timestamp": "2025-01-20T08:00:00Z", "actor": "Sarah Jenkins", "action": "PLAN_INITIALIZED", "notes": "ITAR Enclave plan initiated pursuant to AECA Section 38."}
        ]
    },
    "DEV-PLAN-004": {
        "id": "DEV-PLAN-004",
        "title": "Closed-Loop Green Hydrogen Forging & Superalloy Carbon Abatement",
        "supplier_id": "TWIN-FORGE-031",
        "supplier_name": "Specialty SuperAlloy Forgings",
        "location": "Sheffield, UK",
        "tier": "Tier-2 Superalloy Billet Foundry",
        "focus_area": "ESG & Decarbonization",
        "focus_color": "amber",
        "lead_auditor": "Mark Richardson (DNV Lead Environmental Auditor)",
        "supplier_lead": "Arthur Pendelton (Technical Director)",
        "start_date": "2025-03-01",
        "target_date": "2026-03-01",
        "progress_pct": 35,
        "status": "IN_PROGRESS",
        "strategic_priority": "MEDIUM",
        "baseline_metric": "18.4 kg CO2e / kg forged nickel superalloy disc",
        "target_metric": "< 7.2 kg CO2e / kg via electric induction & green H2 furnace retrofits",
        "investment_budget_usd": 650000,
        "co_investment_pct": 60,
        "description": "Convert Sheffield gas-fired reheat furnaces to clean green hydrogen burner arrays and install waste-heat recovery Rankine cycle to meet OEM Scope 3 aerospace decarbonization mandate.",
        "milestones": [
            {
                "id": "MS-001",
                "title": "Hydrogen Pipeline Feasibility & ATEX Zone 1 Safety Certification",
                "target_date": "2025-05-30",
                "completed_date": "2025-05-18",
                "status": "COMPLETED",
                "verification_proof": "HSE ATEX Safety Cert #UK-H2-SHEFF-2025"
            },
            {
                "id": "MS-002",
                "title": "Electrolyzer & Dual-Fuel Burner Installation in Furnace 4",
                "target_date": "2025-09-30",
                "completed_date": None,
                "status": "IN_PROGRESS",
                "verification_proof": None
            },
            {
                "id": "MS-003",
                "title": "ISO 14064 GHG Third-Party Carbon Footprint Verification",
                "target_date": "2025-12-15",
                "completed_date": None,
                "status": "PENDING",
                "verification_proof": None
            }
        ],
        "kpi_improvements": [
            {"metric": "Emissions Intensity", "baseline": "18.4 kg CO2e/kg", "current": "15.1 kg CO2e/kg", "target": "7.2 kg CO2e/kg"},
            {"metric": "Thermal Efficiency", "baseline": "44%", "current": "56%", "target": "78%"}
        ],
        "audit_logs": [
            {"timestamp": "2025-03-01T12:00:00Z", "actor": "Mark Richardson", "action": "PLAN_INITIALIZED", "notes": "Charter approved for Scope 3 emissions decarbonization."}
        ]
    },
    "DEV-PLAN-005": {
        "id": "DEV-PLAN-005",
        "title": "Nadcap Chemical Processing & Automated Immersion Tank Line",
        "supplier_id": "TWIN-KOVAI-003",
        "supplier_name": "Kovai Diecast & CNC",
        "location": "Coimbatore, India",
        "tier": "Tier-2 Aerospace Special Process",
        "focus_area": "Process Optimization",
        "focus_color": "cyan",
        "lead_auditor": "Aerospace NDT Specialist",
        "supplier_lead": "M. Senthil (Quality Head)",
        "start_date": "2025-02-15",
        "target_date": "2025-12-31",
        "progress_pct": 44,
        "status": "IN_PROGRESS",
        "strategic_priority": "HIGH",
        "baseline_metric": "Manual penetrant dip tanks, visual timing inspection",
        "target_metric": "PLC-controlled automated crane immersion line compliant with AC7108",
        "investment_budget_usd": 180000,
        "co_investment_pct": 25,
        "description": "Automate Coimbatore special process immersion line with automated temperature, pH, and dwell-time monitoring to qualify for Nadcap AC7108 Chemical Processing accreditation.",
        "milestones": [
            {
                "id": "MS-001",
                "title": "SCADA Automated Tank Line Construction",
                "target_date": "2025-05-15",
                "completed_date": "2025-05-10",
                "status": "COMPLETED",
                "verification_proof": "SCADA acceptance report #KOVAI-AC7108"
            },
            {
                "id": "MS-002",
                "title": "Pre-Audit Gap Analysis by Nadcap Specialist",
                "target_date": "2025-08-30",
                "completed_date": None,
                "status": "IN_PROGRESS",
                "verification_proof": None
            },
            {
                "id": "MS-003",
                "title": "Official PRI / Nadcap AC7108 On-Site Audit",
                "target_date": "2025-11-30",
                "completed_date": None,
                "status": "PENDING",
                "verification_proof": None
            }
        ],
        "kpi_improvements": [
            {"metric": "Coating Uniformity", "baseline": "±8.0 μm", "current": "±3.2 μm", "target": "±1.5 μm"},
            {"metric": "First Pass Yield", "baseline": "84.2%", "current": "94.6%", "target": "> 98.5%"}
        ],
        "audit_logs": [
            {"timestamp": "2025-02-15T09:00:00Z", "actor": "M. Senthil", "action": "PLAN_INITIALIZED", "notes": "Nadcap AC7108 automation plan launched."}
        ]
    }
}

# -------------------------------------------------------------
# In-Memory Database: 8D Corrective & Preventive Actions (CAPA)
# -------------------------------------------------------------

CAPA_CASES_DB: Dict[str, Dict[str, Any]] = {
    "CAPA-2025-001": {
        "id": "CAPA-2025-001",
        "title": "Hydraulic Actuator Cylinder Bore Micro-Porosity Non-Conformance",
        "supplier_id": "TWIN-APEX-001",
        "supplier_name": "Apex Precision Machining Ltd",
        "part_number": "ACT-HYD-7075-88A",
        "part_name": "Flight Control Hydraulic Actuator Body",
        "severity": "CRITICAL",
        "current_stage": "D5_PERMANENT_CORRECTIVE_ACTION",
        "status": "PCA_IN_PROGRESS",
        "source": "Incoming Receiving Quality Inspection (PO-9912)",
        "source_doc_id": "DOC-EVID-009",
        "opened_date": "2025-02-10",
        "target_closure_date": "2025-04-15",
        "days_open": 18,
        "champion_name": "Dr. Klaus Weber (Lead Aerospace Quality Auditor)",
        "supplier_rep": "Hans Zimmer (Apex Master Metrologist)",
        "risk_impact": "Flight control hydraulic pressure loss during high-G maneuvers if porosity propagates to micro-cracking.",
        "eight_d": {
            "d1_team": [
                {"name": "Dr. Klaus Weber", "role": "Champion (Lead Auditor)", "organization": "Aerospace OEM QA"},
                {"name": "Hans Zimmer", "role": "Technical Lead", "organization": "Apex Precision Machining Ltd"},
                {"name": "Elena Rostova", "role": "Metallurgical Specialist", "organization": "Materials Engineering Lab"},
                {"name": "Marcus Vance", "role": "Procurement Lead", "organization": "Strategic Sourcing"}
            ],
            "d2_problem_statement": {
                "what": "Micro-porosity clusters > 25 μm detected inside honed internal bore of cylinder.",
                "where": "Cylinder bore surface, Section B-B, Lot #APX-4491.",
                "when": "Detected during 100% ultrasonic C-Scan on receiving inspection on Feb 10, 2025.",
                "magnitude": "3 out of 120 cylinders (2.5% non-conformance rate).",
                "containment_target_hours": 24
            },
            "d3_interim_containment": {
                "actions": [
                    "Immediate quarantine of 117 unmachined billets and 120 finished cylinders at Central Warehouse.",
                    "Issued Stop-Ship Notice #SSN-APX-024 to Apex Precision Machining.",
                    "Implemented 100% Eddy Current and Radiographic X-Ray sorting on all stock in transit.",
                    "Authorized buffer release from qualified secondary supplier Pacific Aero."
                ],
                "effectiveness_pct": 100,
                "verified_by": "Receiving Inspection QA",
                "date_implemented": "2025-02-11"
            },
            "d4_root_cause_analysis": {
                "methodology": "5-Whys & Ishikawa Fishbone Analysis",
                "five_whys": [
                    {"step": "Why 1", "question": "Why did cylinder bore contain micro-porosity?", "answer": "Entrapped hydrogen gas pockets formed during billet solidification."},
                    {"step": "Why 2", "question": "Why was hydrogen gas entrapped in the melt?", "answer": "Degasification cycle in secondary aluminum melting furnace was truncated."},
                    {"step": "Why 3", "question": "Why was the degasification cycle truncated?", "answer": "Furnace operator terminated vacuum cycle prematurely based on false temp readout."},
                    {"step": "Why 4", "question": "Why was the temperature readout false?", "answer": "Thermocouple probe T-04 had suffered resistive thermal drift (+18°C offset)."},
                    {"step": "Why 5 (Root Cause)", "question": "Why was thermocouple drift not detected?", "answer": "Preventive maintenance calibration interval was set to 6 months instead of monthly per AMS 2750F Pyrometry standards."}
                ],
                "root_cause_summary": "Inadequate pyrometry calibration frequency under AMS 2750F allowed thermocouple T-04 to drift undetected, leading to premature termination of vacuum degasification cycle.",
                "contributing_factors": ["Absence of automated PLC interlock preventing premature cycle abort."]
            },
            "d5_permanent_corrective_action": {
                "selected_pca": [
                    "Replaced thermocouple T-04 with dual-redundant optical pyrometer system.",
                    "Programmed PLC hard-interlock preventing furnace pouring until vacuum degasification has run a verified 6.5 minutes.",
                    "Updated Pyrometry Calibration Schedule to bi-weekly verification under AMS 2750F."
                ],
                "estimated_completion": "2025-03-15",
                "status": "APPROVED"
            },
            "d6_implementation_and_validation": {
                "validation_plan": "Produce 3 pilot batches (180 cylinders total) under dual-redundant pyrometry and conduct destructive metallurgical micro-sectioning.",
                "pilot_batch_results": "Batch 1 (60 parts): Zero micro-porosity detected under Class A ultrasonic scan. Density index = 0.998.",
                "validation_status": "IN_PROGRESS"
            },
            "d7_prevention_of_recurrence": {
                "systemic_actions": [
                    "Updated Standard Operating Procedure SOP-MELT-88 Rev D across all 4 foundry lines.",
                    "Revised FMEA Failure Mode #FMEA-APX-81 RPN from 240 down to 24.",
                    "Propagated lesson learned across Supplier Capability Twin network."
                ],
                "institutionalized": True
            },
            "d8_closure_and_recognition": {
                "status": "PENDING_60_DAY_STABILITY_RUN",
                "signoff_auditor": None,
                "closure_date": None
            }
        }
    },
    "CAPA-2025-002": {
        "id": "CAPA-2025-002",
        "title": "Dodd-Frank 1502 Conflict Minerals Smelter CID002918 Audit Lapse",
        "supplier_id": "TWIN-COPP-024",
        "supplier_name": "Apex Copper Formings",
        "part_number": "RAW-COPP-C11000",
        "part_name": "High-Purity Electrolytic Copper Busbars",
        "severity": "CRITICAL",
        "current_stage": "D3_INTERIM_CONTAINMENT",
        "status": "CONTAINMENT_ACTIVE",
        "source": "Regulatory Evidence Vault Discrepancy (CONF-2024-003)",
        "source_doc_id": "DOC-EVID-010",
        "opened_date": "2025-02-14",
        "target_closure_date": "2025-03-30",
        "days_open": 8,
        "champion_name": "Senior ESG & Trade Compliance Auditor",
        "supplier_rep": "Apex Copper ESG Director",
        "risk_impact": "SEC filing reporting violation and defense contract procurement debarment under Dodd-Frank Section 1502.",
        "eight_d": {
            "d1_team": [
                {"name": "Senior ESG Auditor", "role": "Lead Auditor", "organization": "OEM Regulatory Affairs"},
                {"name": "Apex Copper ESG Rep", "role": "Supplier Lead", "organization": "Apex Copper Formings"}
            ],
            "d2_problem_statement": {
                "what": "Smelter #CID002918 in Eastern DRC transit corridor listed as conflict-free despite RMI RMAP audit expiration.",
                "where": "CMRT v6.3 Declaration Table.",
                "when": "Detected during automated AI Evidence Cross-Referencing.",
                "magnitude": "1 smelter out of 14 in copper supply chain.",
                "containment_target_hours": 48
            },
            "d3_interim_containment": {
                "actions": [
                    "Supplier issued formal quarantine on all raw copper cathode batches originating from Smelter #CID002918.",
                    "Diverted high-purity copper procurement to RMI-certified Chilean foundry."
                ],
                "effectiveness_pct": 100,
                "verified_by": "Trade Compliance Lead",
                "date_implemented": "2025-02-15"
            },
            "d4_root_cause_analysis": {
                "methodology": "5-Whys Analysis",
                "five_whys": [
                    {"step": "Why 1", "question": "Why was expired smelter included in declaration?", "answer": "Supplier used an outdated Q1 CMRT spreadsheet template without refreshing RMI RMAP database list."}
                ],
                "root_cause_summary": "Manual spreadsheet management failed to ingest monthly RMI RMAP conformance audit updates.",
                "contributing_factors": ["Lack of automated API sync between supplier ERP and RMI central database."]
            },
            "d5_permanent_corrective_action": {
                "selected_pca": ["Connect supplier procurement system to live RMI RMAP automated verification API."],
                "estimated_completion": "2025-03-15",
                "status": "IN_REVIEW"
            },
            "d6_implementation_and_validation": {"validation_status": "PENDING"},
            "d7_prevention_of_recurrence": {"institutionalized": False},
            "d8_closure_and_recognition": {"status": "OPEN"}
        }
    },
    "CAPA-2025-003": {
        "id": "CAPA-2025-003",
        "title": "Turbine Blade Root Fir-Tree Profile EDM Dimensional Drift",
        "supplier_id": "TWIN-KOVAI-003",
        "supplier_name": "Kovai Diecast & CNC",
        "part_number": "BLD-TURB-718-X9",
        "part_name": "Inconel 718 High-Pressure Turbine Blade",
        "severity": "MAJOR",
        "current_stage": "D4_ROOT_CAUSE_ANALYSIS",
        "status": "ROOT_CAUSE_ANALYSIS",
        "source": "Customer Quality Notification / CMM Laser Scan",
        "source_doc_id": "DOC-EVID-004",
        "opened_date": "2025-02-05",
        "target_closure_date": "2025-04-05",
        "days_open": 15,
        "champion_name": "Aerospace NDT Specialist",
        "supplier_rep": "Kovai Quality Head",
        "risk_impact": "Fir-tree root misalignment in turbine disc slot creates stress concentration and reduced low-cycle fatigue life.",
        "eight_d": {
            "d1_team": [
                {"name": "Aerospace NDT Specialist", "role": "Lead", "organization": "Turbine QA"},
                {"name": "Kovai Quality Head", "role": "Supplier Lead", "organization": "Kovai Diecast & CNC"}
            ],
            "d2_problem_statement": {
                "what": "Wire EDM cutting of Inconel 718 fir-tree root exhibited taper error of 0.015mm on upper serration.",
                "where": "Makino Wire EDM Machine #EDM-04.",
                "when": "Detected during Zeiss CMM contact scan on lot #KVI-8820.",
                "magnitude": "5 blades out of 40 inspected."
            },
            "d3_interim_containment": {
                "actions": [
                    "Halted production on Makino EDM-04.",
                    "100% CMM inspection mandated on all blades prior to packaging."
                ],
                "effectiveness_pct": 100,
                "verified_by": "Quality Lead",
                "date_implemented": "2025-02-06"
            },
            "d4_root_cause_analysis": {
                "methodology": "Fishbone Diagram & Dielectric Conductivity Test",
                "five_whys": [
                    {"step": "Why 1", "question": "Why did EDM wire cut taper erratically?", "answer": "Deionized water dielectric conductivity spiked from 0.5 μS/cm to 14.8 μS/cm."},
                    {"step": "Why 2", "question": "Why did conductivity spike?", "answer": "Resin deionizer bottle was fully depleted."},
                    {"step": "Why 3", "question": "Why was depleted bottle not replaced?", "answer": "Conductivity probe sensor alarm was muted by night shift operator."}
                ],
                "root_cause_summary": "Depleted DI resin combined with muted conductivity alarm caused arc instability in deep fir-tree cuts."
            },
            "d5_permanent_corrective_action": {
                "selected_pca": ["Install automated dual-resin bottle automatic rollover system with non-mutable machine shutoff interlock."],
                "estimated_completion": "2025-03-20",
                "status": "APPROVED"
            },
            "d6_implementation_and_validation": {"validation_status": "PENDING"},
            "d7_prevention_of_recurrence": {"institutionalized": False},
            "d8_closure_and_recognition": {"status": "OPEN"}
        }
    },
    "CAPA-2025-004": {
        "id": "CAPA-2025-004",
        "title": "SCADA Key Injection Firmware Rev 2 Timestamp Desynchronization",
        "supplier_id": "TWIN-SEMI-008",
        "supplier_name": "MicroAvionics Foundry",
        "part_number": "AV-SOC-FIPS-140-3",
        "part_name": "Radiation-Tolerant Cryptographic Flight SoC",
        "severity": "MAJOR",
        "current_stage": "D6_IMPLEMENTATION_VALIDATION",
        "status": "VALIDATION_PENDING",
        "source": "ISO 27001 Security Audit Discrepancy (DOC-EVID-008)",
        "source_doc_id": "DOC-EVID-008",
        "opened_date": "2025-01-25",
        "target_closure_date": "2025-03-25",
        "days_open": 26,
        "champion_name": "Senior Cybersecurity Auditor",
        "supplier_rep": "MicroAvionics Cyber Officer",
        "risk_impact": "Cryptographic certificate validation failure during bootloader challenge-response handshakes.",
        "eight_d": {
            "d1_team": [
                {"name": "Cybersecurity Auditor", "role": "Lead", "organization": "Aerospace Avionics Security"},
                {"name": "MicroAvionics Cyber Lead", "role": "Supplier Lead", "organization": "MicroAvionics Foundry"}
            ],
            "d2_problem_statement": {
                "what": "Hardware security module injected certificates with NTP time offset of -42 seconds.",
                "where": "Fab 4 Cleanroom Secure HSM Enclave.",
                "when": "Detected during X.509 signature timestamp validation."
            },
            "d3_interim_containment": {
                "actions": ["Re-flashed 240 quarantined microchips with corrected UTC timestamp."],
                "effectiveness_pct": 100,
                "verified_by": "Security Auditor",
                "date_implemented": "2025-01-26"
            },
            "d4_root_cause_analysis": {
                "methodology": "Network NTP Trace",
                "root_cause_summary": "Cleanroom air-gapped NTP clock drift due to battery-backed RTC oscillator crystal temperature coefficient in high-ambient cleanroom server rack."
            },
            "d5_permanent_corrective_action": {
                "selected_pca": ["Installed GPS/Galileo roof antenna fiber-optic feed to atomic rubidium reference oscillator."],
                "status": "IMPLEMENTED"
            },
            "d6_implementation_and_validation": {
                "validation_status": "30-day continuous nanosecond drift monitoring in progress (0.002 ms drift observed)."
            },
            "d7_prevention_of_recurrence": {"institutionalized": True},
            "d8_closure_and_recognition": {"status": "READY_FOR_FINAL_AUDIT"}
        }
    },
    "CAPA-2025-005": {
        "id": "CAPA-2025-005",
        "title": "Packaging ESD Moisture Barrier Puncture in Maritime Transit",
        "supplier_id": "TWIN-PREC-002",
        "supplier_name": "Precision AutoComp Ltd",
        "part_number": "SEN-ABS-WHEEL-04",
        "part_name": "Automotive Wheel Speed Sensor Assembly",
        "severity": "MINOR",
        "current_stage": "D8_CLOSED_VERIFIED",
        "status": "CLOSED_VERIFIED",
        "source": "Transit IoT Telemetry Sensor Alert #IOT-SENS-88",
        "source_doc_id": "DOC-EVID-003",
        "opened_date": "2025-01-05",
        "target_closure_date": "2025-02-15",
        "days_open": 40,
        "champion_name": "Packaging & Logistics Quality Lead",
        "supplier_rep": "Precision Packaging Supervisor",
        "risk_impact": "Sensor humidity exposure exceeding 60% RH during ocean freight transit.",
        "eight_d": {
            "d1_team": [{"name": "Logistics Lead", "role": "Lead", "organization": "Global Logistics"}],
            "d2_problem_statement": {"what": "Corner puncture in vacuum foil moisture barrier bag on pallet 4."},
            "d3_interim_containment": {"actions": ["Repacked and re-desiccated all sensors at destination port."], "effectiveness_pct": 100},
            "d4_root_cause_analysis": {"root_cause_summary": "Wooden pallet corner splinters penetrated 4-mil bag under maritime vibration."},
            "d5_permanent_corrective_action": {"selected_pca": ["Upgraded to 7-mil puncture-resistant military foil with plastic corner guards."]},
            "d6_implementation_and_validation": {"validation_status": "5 subsequent ocean shipments verified with 0 RH spikes."},
            "d7_prevention_of_recurrence": {"institutionalized": True},
            "d8_closure_and_recognition": {"status": "CLOSED_VERIFIED", "closure_date": "2025-02-14"}
        }
    }
}

# -------------------------------------------------------------
# In-Memory Database: Training & Enablement Modules
# -------------------------------------------------------------

TRAINING_MODULES_DB: List[Dict[str, Any]] = [
    {
        "id": "TRN-001",
        "title": "AS9100 Rev D & AS9102 First Article Inspection (FAI) Masterclass",
        "category": "Quality & Standards",
        "duration_hours": 16,
        "format": "Interactive Virtual & Shopfloor Lab",
        "enrolled_suppliers": 28,
        "completion_rate_pct": 92.5,
        "certification_issued": "Certified AS9102 FAI Lead Practitioner",
        "description": "Comprehensive aerospace qualification on completing Forms 1, 2, and 3, ballooned drawing ballooning, optical CMM metrology correlation, and non-conformance disposition."
    },
    {
        "id": "TRN-002",
        "title": "8D Root Cause Problem Solving & 5-Whys Fishbone Facilitation",
        "category": "Continuous Improvement",
        "duration_hours": 8,
        "format": "Hands-On Workshop",
        "enrolled_suppliers": 34,
        "completion_rate_pct": 97.0,
        "certification_issued": "Certified 8D Problem Solver",
        "description": "Standardized aerospace & automotive methodology to institute rigorous interim containment actions (ICA) and permanent corrective actions (PCA) preventing systemic recurrence."
    },
    {
        "id": "TRN-003",
        "title": "ITAR / EAR Part 122 Export Control Defense Article Protocol",
        "category": "Defense & Regulatory",
        "duration_hours": 12,
        "format": "Executive Compliance Seminar",
        "enrolled_suppliers": 18,
        "completion_rate_pct": 94.0,
        "certification_issued": "ITAR Defense Compliance Officer",
        "description": "Legal training on Section 38 of the Arms Export Control Act (AECA), technical data handling, visitor control log protocols, and foreign national licensing."
    },
    {
        "id": "TRN-004",
        "title": "Statistical Process Control (SPC) & Sub-Micron CNC Machining",
        "category": "Manufacturing Engineering",
        "duration_hours": 24,
        "format": "Technical Engineering Workshop",
        "enrolled_suppliers": 22,
        "completion_rate_pct": 89.0,
        "certification_issued": "Advanced CNC Process Capability Specialist",
        "description": "Deep dive into real-time tool wear compensation, thermal expansion offsets, X-bar R charts, and achieving Cp/Cpk > 1.67 in Inconel, Titanium, and 7075 aluminum."
    },
    {
        "id": "TRN-005",
        "title": "Digital Twin Machine Telemetry & IoT Edge Gateway Integration",
        "category": "Industry 4.0 & Digitalization",
        "duration_hours": 10,
        "format": "Developer & Systems Lab",
        "enrolled_suppliers": 25,
        "completion_rate_pct": 91.0,
        "certification_issued": "SupplyTwin IoT Edge Integrator",
        "description": "Hands-on guide to connecting MTConnect, OPC-UA, and Modbus TCP machine telemetry streams into the real-time Supplier Capability Twin simulation model."
    }
]

# -------------------------------------------------------------
# Request & Response Schemas
# -------------------------------------------------------------

class PlanCreateRequest(BaseModel):
    title: str
    supplier_id: str
    supplier_name: str
    focus_area: str = "Manufacturing Capability"
    target_date: str
    strategic_priority: str = "HIGH"
    baseline_metric: str
    target_metric: str
    investment_budget_usd: Optional[float] = 100000
    description: Optional[str] = "Continuous capability improvement plan."

class PlanProgressUpdateRequest(BaseModel):
    progress_pct: int = Field(..., ge=0, le=100)
    actor: str = "Lead Quality Auditor"
    notes: Optional[str] = "Progress updated based on milestone verification."

class MilestoneVerifyRequest(BaseModel):
    verification_proof: str
    verifier_name: str = "Lead Aerospace Quality Auditor"
    notes: Optional[str] = "Milestone verified against physical artifact and inspection certificate."

class CapaCreateRequest(BaseModel):
    title: str
    supplier_id: str
    supplier_name: str
    part_number: str
    part_name: str
    severity: str = "MAJOR"  # "CRITICAL" | "MAJOR" | "MINOR"
    source: str = "Receiving Inspection Non-Conformance"
    champion_name: str = "Lead Quality Auditor"
    supplier_rep: str = "Supplier Quality Manager"
    what: str
    where: str
    magnitude: str
    risk_impact: str

class CapaStageTransitionRequest(BaseModel):
    target_stage: str
    actor: str = "Lead Quality Auditor"
    notes: Optional[str] = "Stage advanced based on verification."
    containment_actions: Optional[List[str]] = None
    root_cause_summary: Optional[str] = None
    selected_pca: Optional[List[str]] = None

class CapaActionAddRequest(BaseModel):
    action_type: str = "INTERIM_CONTAINMENT"  # "INTERIM_CONTAINMENT" | "PERMANENT_CORRECTIVE" | "PREVENTIVE"
    action_description: str
    actor: str = "Lead Quality Auditor"

# -------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------

@router.get("/overview")
def get_development_overview():
    """
    Returns platform-wide continuous development metrics, active plan counts,
    8D CAPA severity buckets, average capability improvement rates, and focus areas.
    """
    plans = list(DEVELOPMENT_PLANS_DB.values())
    capas = list(CAPA_CASES_DB.values())

    active_plans = len([p for p in plans if p["status"] == "IN_PROGRESS" or p["status"] == "ON_TRACK"])
    suppliers_count = len(set(p["supplier_id"] for p in plans))
    avg_improvement = round(sum(p["progress_pct"] for p in plans) / len(plans), 1) if plans else 0

    open_capas = len([c for c in capas if c["status"] != "CLOSED_VERIFIED"])
    critical_capas = len([c for c in capas if c["severity"] == "CRITICAL" and c["status"] != "CLOSED_VERIFIED"])
    major_capas = len([c for c in capas if c["severity"] == "MAJOR" and c["status"] != "CLOSED_VERIFIED"])
    closed_capas = len([c for c in capas if c["status"] == "CLOSED_VERIFIED"])

    # Focus area distribution
    focus_distribution = [
        {"area": "Manufacturing Capability & Precision", "count": 14, "pct": 33, "color": "bg-blue-500"},
        {"area": "Zero Defect & Quality Engineering", "count": 10, "pct": 24, "color": "bg-emerald-500"},
        {"area": "Cybersecurity & ITAR Enclave", "count": 7, "pct": 17, "color": "bg-purple-500"},
        {"area": "ESG & Clean Hydrogen Forging", "count": 6, "pct": 14, "color": "bg-amber-500"},
        {"area": "Process Automation & Special Processes", "count": 5, "pct": 12, "color": "bg-cyan-500"}
    ]

    return {
        "status": "success",
        "kpis": {
            "active_development_plans": active_plans + 37,  # Scaled for platform breadth
            "suppliers_in_development": suppliers_count + 21,
            "completed_plans": 16,
            "average_improvement_pct": avg_improvement,
            "open_capa_cases": open_capas,
            "critical_capas": critical_capas,
            "major_capas": major_capas,
            "closed_capas": closed_capas,
            "capa_on_time_closure_rate_pct": 93.8,
            "total_co_investment_usd": 1840000
        },
        "focus_distribution": focus_distribution,
        "recent_plans": plans[:3],
        "active_capas": capas[:3]
    }

# -------------------------------------------------------------
# Development Plans Endpoints
# -------------------------------------------------------------

@router.get("/plans")
def list_development_plans(
    status: Optional[str] = None,
    focus_area: Optional[str] = None,
    supplier_id: Optional[str] = None,
    search: Optional[str] = None
):
    """
    Returns filtered continuous development plans.
    """
    results = list(DEVELOPMENT_PLANS_DB.values())

    if status and status != "All Statuses" and status != "All":
        results = [p for p in results if p["status"].lower() == status.lower()]

    if focus_area and focus_area != "All Areas" and focus_area != "All":
        results = [p for p in results if focus_area.lower() in p["focus_area"].lower()]

    if supplier_id and supplier_id != "All Suppliers" and supplier_id != "All":
        results = [p for p in results if p["supplier_id"] == supplier_id or p["supplier_name"].lower() == supplier_id.lower()]

    if search:
        s = search.lower()
        results = [
            p for p in results
            if s in p["title"].lower()
            or s in p["supplier_name"].lower()
            or s in p["id"].lower()
            or s in p["focus_area"].lower()
        ]

    return {
        "status": "success",
        "total_plans": len(results),
        "plans": results
    }

@router.get("/plans/{plan_id}")
def get_development_plan(plan_id: str):
    """
    Retrieves full details of a Continuous Development Plan including milestones,
    KPI improvement tracks, and audit trail.
    """
    plan = DEVELOPMENT_PLANS_DB.get(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Development Plan '{plan_id}' not found")
    return {
        "status": "success",
        "plan": plan
    }

@router.post("/plans")
def create_development_plan(payload: PlanCreateRequest):
    """
    Creates a new Continuous Development Plan charter for a supplier.
    """
    new_id = f"DEV-PLAN-{len(DEVELOPMENT_PLANS_DB) + 1:03d}"
    new_plan = {
        "id": new_id,
        "title": payload.title,
        "supplier_id": payload.supplier_id,
        "supplier_name": payload.supplier_name,
        "location": "Global Supplier Facility",
        "tier": "Tier-1 Strategic",
        "focus_area": payload.focus_area,
        "focus_color": "blue",
        "lead_auditor": "Chief Supplier Development Officer",
        "supplier_lead": "Supplier Operations VP",
        "start_date": datetime.utcnow().strftime("%Y-%m-%d"),
        "target_date": payload.target_date,
        "progress_pct": 5,
        "status": "IN_PROGRESS",
        "strategic_priority": payload.strategic_priority,
        "baseline_metric": payload.baseline_metric,
        "target_metric": payload.target_metric,
        "investment_budget_usd": payload.investment_budget_usd or 100000,
        "co_investment_pct": 50,
        "description": payload.description or "Joint continuous development initiative.",
        "milestones": [
            {
                "id": "MS-001",
                "title": "Charter Kickoff & Gap Assessment",
                "target_date": datetime.utcnow().strftime("%Y-%m-%d"),
                "completed_date": datetime.utcnow().strftime("%Y-%m-%d"),
                "status": "COMPLETED",
                "verification_proof": "Charter Signed"
            },
            {
                "id": "MS-002",
                "title": "Equipment / Process Upgrade Implementation",
                "target_date": payload.target_date,
                "completed_date": None,
                "status": "IN_PROGRESS",
                "verification_proof": None
            }
        ],
        "kpi_improvements": [
            {"metric": "Primary Capability Metric", "baseline": payload.baseline_metric, "current": payload.baseline_metric, "target": payload.target_metric}
        ],
        "audit_logs": [
            {"timestamp": datetime.utcnow().isoformat() + "Z", "actor": "Chief Sourcing Officer", "action": "PLAN_CHARTER_CREATED", "notes": f"Charter {new_id} established."}
        ]
    }
    DEVELOPMENT_PLANS_DB[new_id] = new_plan
    return {
        "status": "success",
        "message": f"Development Plan '{payload.title}' created successfully.",
        "plan": new_plan
    }

@router.post("/plans/{plan_id}/milestones/{milestone_id}/verify")
def verify_plan_milestone(plan_id: str, milestone_id: str, payload: MilestoneVerifyRequest):
    """
    Auditor verifies and marks a milestone as COMPLETED with proof artifact.
    """
    plan = DEVELOPMENT_PLANS_DB.get(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found")

    milestone = next((m for m in plan.get("milestones", []) if m["id"] == milestone_id), None)
    if not milestone:
        raise HTTPException(status_code=404, detail=f"Milestone '{milestone_id}' not found in plan {plan_id}")

    milestone["status"] = "COMPLETED"
    milestone["completed_date"] = datetime.utcnow().strftime("%Y-%m-%d")
    milestone["verification_proof"] = payload.verification_proof

    # Recalculate progress
    completed_count = len([m for m in plan["milestones"] if m["status"] == "COMPLETED"])
    total_milestones = len(plan["milestones"])
    plan["progress_pct"] = round((completed_count / total_milestones) * 100) if total_milestones > 0 else 100

    if plan["progress_pct"] >= 100:
        plan["status"] = "COMPLETED"

    plan["audit_logs"].append({
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "actor": payload.verifier_name,
        "action": f"MILESTONE_VERIFIED ({milestone_id})",
        "notes": payload.notes or f"Milestone '{milestone['title']}' verified with proof: {payload.verification_proof}"
    })

    return {
        "status": "success",
        "message": f"Milestone '{milestone['title']}' marked as COMPLETED.",
        "plan_progress_pct": plan["progress_pct"],
        "plan": plan
    }

@router.post("/plans/{plan_id}/progress")
def update_plan_progress(plan_id: str, payload: PlanProgressUpdateRequest):
    """
    Updates the overall completion percentage of a development plan.
    """
    plan = DEVELOPMENT_PLANS_DB.get(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found")

    plan["progress_pct"] = payload.progress_pct
    if payload.progress_pct >= 100:
        plan["status"] = "COMPLETED"

    plan["audit_logs"].append({
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "actor": payload.actor,
        "action": "PROGRESS_UPDATED",
        "notes": payload.notes or f"Progress set to {payload.progress_pct}%."
    })

    return {
        "status": "success",
        "message": f"Plan progress updated to {payload.progress_pct}%.",
        "plan": plan
    }

# -------------------------------------------------------------
# 8D Corrective & Preventive Action (CAPA) Endpoints
# -------------------------------------------------------------

@router.get("/capa")
def list_capa_cases(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    supplier_id: Optional[str] = None,
    search: Optional[str] = None
):
    """
    Returns filtered 8D Corrective Action cases.
    """
    results = list(CAPA_CASES_DB.values())

    if status and status != "All Statuses" and status != "All":
        results = [c for c in results if c["status"].lower() == status.lower()]

    if severity and severity != "All Severities" and severity != "All":
        results = [c for c in results if c["severity"].lower() == severity.lower()]

    if supplier_id and supplier_id != "All Suppliers" and supplier_id != "All":
        results = [c for c in results if c["supplier_id"] == supplier_id or c["supplier_name"].lower() == supplier_id.lower()]

    if search:
        s = search.lower()
        results = [
            c for c in results
            if s in c["title"].lower()
            or s in c["id"].lower()
            or s in c["part_number"].lower()
            or s in c["supplier_name"].lower()
            or s in c["source"].lower()
        ]

    return {
        "status": "success",
        "total_capas": len(results),
        "capas": results
    }

@router.get("/capa/{capa_id}")
def get_capa_case(capa_id: str):
    """
    Retrieves complete 8D report structure (D1 through D8) for a CAPA case.
    """
    capa = CAPA_CASES_DB.get(capa_id)
    if not capa:
        raise HTTPException(status_code=404, detail=f"CAPA Case '{capa_id}' not found")
    return {
        "status": "success",
        "capa": capa
    }

@router.post("/capa")
def create_capa_case(payload: CapaCreateRequest):
    """
    Initiates a new 8D Corrective Action case against a supplier.
    """
    new_id = f"CAPA-2025-{len(CAPA_CASES_DB) + 1:03d}"
    new_capa = {
        "id": new_id,
        "title": payload.title,
        "supplier_id": payload.supplier_id,
        "supplier_name": payload.supplier_name,
        "part_number": payload.part_number,
        "part_name": payload.part_name,
        "severity": payload.severity,
        "current_stage": "D2_PROBLEM_STATEMENT",
        "status": "ISSUED",
        "source": payload.source,
        "opened_date": datetime.utcnow().strftime("%Y-%m-%d"),
        "target_closure_date": (datetime.utcnow() + timedelta(days=45)).strftime("%Y-%m-%d"),
        "days_open": 0,
        "champion_name": payload.champion_name,
        "supplier_rep": payload.supplier_rep,
        "risk_impact": payload.risk_impact,
        "eight_d": {
            "d1_team": [
                {"name": payload.champion_name, "role": "Lead Auditor", "organization": "Quality Lead"},
                {"name": payload.supplier_rep, "role": "Supplier Lead", "organization": payload.supplier_name}
            ],
            "d2_problem_statement": {
                "what": payload.what,
                "where": payload.where,
                "when": datetime.utcnow().strftime("%Y-%m-%d"),
                "magnitude": payload.magnitude
            },
            "d3_interim_containment": {"actions": [], "effectiveness_pct": 0},
            "d4_root_cause_analysis": {"methodology": "5-Whys / Fishbone", "five_whys": []},
            "d5_permanent_corrective_action": {"selected_pca": [], "status": "PENDING"},
            "d6_implementation_and_validation": {"validation_status": "PENDING"},
            "d7_prevention_of_recurrence": {"institutionalized": False},
            "d8_closure_and_recognition": {"status": "OPEN"}
        }
    }
    CAPA_CASES_DB[new_id] = new_capa
    return {
        "status": "success",
        "message": f"8D CAPA Case {new_id} issued to {payload.supplier_name}.",
        "capa": new_capa
    }

@router.post("/capa/{capa_id}/transition")
def transition_capa_stage(capa_id: str, payload: CapaStageTransitionRequest):
    """
    Advances 8D stage (e.g. from D3 Containment to D4 Root Cause, D5 PCA, or D8 Closure).
    """
    capa = CAPA_CASES_DB.get(capa_id)
    if not capa:
        raise HTTPException(status_code=404, detail=f"CAPA '{capa_id}' not found")

    capa["current_stage"] = payload.target_stage

    # Update macro status based on stage
    if "D3" in payload.target_stage:
        capa["status"] = "CONTAINMENT_ACTIVE"
        if payload.containment_actions:
            capa["eight_d"]["d3_interim_containment"]["actions"].extend(payload.containment_actions)
            capa["eight_d"]["d3_interim_containment"]["effectiveness_pct"] = 100
    elif "D4" in payload.target_stage:
        capa["status"] = "ROOT_CAUSE_ANALYSIS"
        if payload.root_cause_summary:
            capa["eight_d"]["d4_root_cause_analysis"]["root_cause_summary"] = payload.root_cause_summary
    elif "D5" in payload.target_stage or "D6" in payload.target_stage:
        capa["status"] = "PCA_IN_PROGRESS"
        if payload.selected_pca:
            capa["eight_d"]["d5_permanent_corrective_action"]["selected_pca"].extend(payload.selected_pca)
            capa["eight_d"]["d5_permanent_corrective_action"]["status"] = "IMPLEMENTED"
    elif "D7" in payload.target_stage:
        capa["status"] = "VALIDATION_PENDING"
        capa["eight_d"]["d7_prevention_of_recurrence"]["institutionalized"] = True
    elif "D8" in payload.target_stage or "CLOSED" in payload.target_stage:
        capa["status"] = "CLOSED_VERIFIED"
        capa["eight_d"]["d8_closure_and_recognition"]["status"] = "CLOSED_VERIFIED"
        capa["eight_d"]["d8_closure_and_recognition"]["closure_date"] = datetime.utcnow().strftime("%Y-%m-%d")
        capa["eight_d"]["d8_closure_and_recognition"]["signoff_auditor"] = payload.actor

    return {
        "status": "success",
        "message": f"CAPA {capa_id} transitioned to stage '{payload.target_stage}'.",
        "capa": capa
    }

@router.post("/capa/{capa_id}/action")
def add_capa_action(capa_id: str, payload: CapaActionAddRequest):
    """
    Appends an interim containment action, corrective action, or preventive action to the 8D report.
    """
    capa = CAPA_CASES_DB.get(capa_id)
    if not capa:
        raise HTTPException(status_code=404, detail=f"CAPA '{capa_id}' not found")

    eight_d = capa["eight_d"]
    if payload.action_type == "INTERIM_CONTAINMENT":
        eight_d["d3_interim_containment"]["actions"].append(payload.action_description)
    elif payload.action_type == "PERMANENT_CORRECTIVE":
        if "selected_pca" not in eight_d["d5_permanent_corrective_action"]:
            eight_d["d5_permanent_corrective_action"]["selected_pca"] = []
        eight_d["d5_permanent_corrective_action"]["selected_pca"].append(payload.action_description)
    else:
        if "systemic_actions" not in eight_d["d7_prevention_of_recurrence"]:
            eight_d["d7_prevention_of_recurrence"]["systemic_actions"] = []
        eight_d["d7_prevention_of_recurrence"]["systemic_actions"].append(payload.action_description)

    return {
        "status": "success",
        "message": f"{payload.action_type} action added to 8D CAPA report.",
        "capa": capa
    }

# -------------------------------------------------------------
# Training & Enablement Modules Endpoints
# -------------------------------------------------------------

@router.get("/training")
def list_training_modules():
    """
    Returns available supplier technical capability & quality enablement modules.
    """
    return {
        "status": "success",
        "total_modules": len(TRAINING_MODULES_DB),
        "modules": TRAINING_MODULES_DB
    }

@router.post("/training/{module_id}/enroll")
def enroll_supplier_in_training(module_id: str, supplier_id: str, supplier_name: Optional[str] = "Supplier Partner"):
    """
    Enrolls a supplier team into a continuous capability training course.
    """
    module = next((m for m in TRAINING_MODULES_DB if m["id"] == module_id), None)
    if not module:
        raise HTTPException(status_code=404, detail=f"Module '{module_id}' not found")

    module["enrolled_suppliers"] += 1
    return {
        "status": "success",
        "message": f"Supplier '{supplier_name}' ({supplier_id}) successfully enrolled in '{module['title']}'.",
        "module": module
    }
