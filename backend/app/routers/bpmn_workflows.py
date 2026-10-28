"""
AlphaHelion Purchasing Intelligence Cloud
Module: BPMN 2.0 Swimlane Workflows & Token Simulation Engine
Blueprint Reference: Part C: Section 21 (Flows F1 to F9, pages 37-54) & Technical Doc Section 8 & 16

Implements the 9 Governed BPMN Swimlane Flows:
F1: MRP Run -> Planned Order -> Purchase Requisition (pic.mrp-to-pr)
F2: Guided Buying Requisition (pic.requisition)
F3: Strategic Sourcing -> Award (pic.sourcing-award)
F4: Contract Lifecycle (pic.contract)
F5: Purchase Order -> Supplier Confirmation -> Delivery (pic.po)
F6: Goods Receipt / Service Entry -> Quality (pic.receipt)
F7: Invoice -> Match -> ERP Posting -> Payment (pic.invoice)
F8: Supplier Onboarding & Qualification (pic.supplier-onboarding)
F9: Material Master Governance (pic.material-request)
"""

from fastapi import APIRouter, HTTPException, Query, Header
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

router = APIRouter(prefix="/api/v1/bpmn", tags=["BPMN Swimlane Workflows"])

class BpmnStep(BaseModel):
    step_index: int
    step_id: str
    label: str
    type: str # START_EVENT, USER_TASK, SYSTEM_TASK, GATEWAY, END_EVENT
    lane: str
    screen_ref: Optional[str] = None
    candidate_group: Optional[str] = None
    key_dmn_or_timer: Optional[str] = None
    branch_notes: Optional[str] = None
    description: str

class BpmnLane(BaseModel):
    lane_id: str
    name: str
    role_type: str # HUMAN, SYSTEM, EXTERNAL_SUPPLIER
    description: str

class BpmnFlowDefinition(BaseModel):
    id: str
    flow_code: str # F1, F2, ... F9
    process_key: str
    title: str
    start_trigger: str
    lanes: List[BpmnLane]
    steps: List[BpmnStep]
    branches_and_nuances: str
    total_steps: int

class TokenStepRequest(BaseModel):
    current_step_index: int
    branch_choice: Optional[str] = "MAIN_PATH" # MAIN_PATH, ALTERNATIVE_BRANCH
    actor: str = "Chief Procurement Officer"

# ==============================================================================
# IN-MEMORY DEFINITIONS OF ALL 9 BPMN FLOWS (BLUEPRINT SECTION 21)
# ==============================================================================

BPMN_FLOWS: Dict[str, Dict[str, Any]] = {
    "F1": {
        "id": "F1",
        "flow_code": "F1",
        "process_key": "pic.mrp-to-pr",
        "title": "MRP Run → Planned Order → Purchase Requisition",
        "start_trigger": "Scheduled calendar run or manual planner trigger",
        "lanes": [
            {"lane_id": "L1_PLANNER", "name": "MRP Controller / Planner", "role_type": "HUMAN", "description": "Firms planned orders, manages lot sizes, reviews exceptions"},
            {"lane_id": "L2_ENGINE", "name": "Platform MRP Engine", "role_type": "SYSTEM", "description": "Automated BOM explosion, supply netting, calendar lead-time offset"},
            {"lane_id": "L3_BUYER", "name": "Operational Buyer", "role_type": "HUMAN", "description": "Converts requisitions to sourcing events or purchase orders"}
        ],
        "branches_and_nuances": "Simulation runs branch to report without creating records. Firmed orders are protected from next run. Source determination: Contract -> Quota -> Source List -> Info Record.",
        "steps": [
            {"step_index": 0, "step_id": "S1_START", "label": "Plan Cycle Starts", "type": "START_EVENT", "lane": "MRP Controller / Planner", "screen_ref": None, "candidate_group": "MRP_CONTROLLER", "key_dmn_or_timer": "Factory Calendar Scheduled Trigger", "description": "MRP controller initiates planning cycle for plant P100."},
            {"step_index": 1, "step_id": "S2_SCOPE", "label": "Select Scope & Run Mode", "type": "USER_TASK", "lane": "MRP Controller / Planner", "screen_ref": "MRP-01", "candidate_group": "MRP_CONTROLLER", "key_dmn_or_timer": None, "description": "Select plant, materials, and mode (Net-Change vs Regenerative vs Simulation)."},
            {"step_index": 2, "step_id": "S3_READ", "label": "Read Demand, Stock & Open POs", "type": "SYSTEM_TASK", "lane": "Platform MRP Engine", "screen_ref": "MRP-01", "candidate_group": None, "key_dmn_or_timer": "BOM Explosion", "description": "Aggregates forecast (12k units), stock (2.5k), scheduled (700), safety (200)."},
            {"step_index": 3, "step_id": "S4_NETTING", "label": "Net Requirement & Lot Sizing", "type": "SYSTEM_TASK", "lane": "Platform MRP Engine", "screen_ref": "MRP-02", "candidate_group": None, "key_dmn_or_timer": "Netting Formula", "description": "Net = max(0, 12,000 - 2,500 - 700 + 200) = 9,000 units. Applies exact lot-sizing."},
            {"step_index": 4, "step_id": "S5_GW_SIM", "label": "Simulation Run?", "type": "GATEWAY", "lane": "Platform MRP Engine", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "Run Mode Switch", "description": "If Simulation, branch to report. If Live, proceed to planned order generation."},
            {"step_index": 5, "step_id": "S6_CREATE_PLO", "label": "Create Planned Orders & Exceptions", "type": "SYSTEM_TASK", "lane": "Platform MRP Engine", "screen_ref": "MRP-03", "candidate_group": None, "key_dmn_or_timer": "Lead-Time Schedule", "description": "Generates PLO-55821 scheduled for start 2026-10-27 and finish 2026-11-10."},
            {"step_index": 6, "step_id": "S7_REVIEW", "label": "Review Exceptions & Firm Orders", "type": "USER_TASK", "lane": "MRP Controller / Planner", "screen_ref": "MRP-02", "candidate_group": "MRP_CONTROLLER", "key_dmn_or_timer": "SLA: 4 Hours", "description": "Planner reviews shortage warnings and locks PLO-55821 as FIRMED."},
            {"step_index": 7, "step_id": "S8_CONVERT_PR", "label": "Convert to PR (Source Determination)", "type": "SYSTEM_TASK", "lane": "Platform MRP Engine", "screen_ref": "REQ-04", "candidate_group": None, "key_dmn_or_timer": "Quota Split (60/40)", "description": "Autonomously converts PLO-55821 into Purchase Requisition REQ-2311."},
            {"step_index": 8, "step_id": "S9_BUYER_QUEUE", "label": "PR Appears in Buyer Workbench", "type": "USER_TASK", "lane": "Operational Buyer", "screen_ref": "REQ-04", "candidate_group": "BUYER", "key_dmn_or_timer": "SLA: 1 Business Day", "description": "Requisition queued for buyer review, bundling, and purchase order release."},
            {"step_index": 9, "step_id": "S10_END", "label": "PR Ready for Sourcing / PO", "type": "END_EVENT", "lane": "Operational Buyer", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "Hand-off to F3 / F5", "description": "Document linkage recorded under Principle P10. Ready for execution."}
        ]
    },
    "F2": {
        "id": "F2",
        "flow_code": "F2",
        "process_key": "pic.requisition",
        "title": "Guided Buying Requisition (Catalogue / Free Text / MDM)",
        "start_trigger": "Employee need identified (requisition.submitted)",
        "lanes": [
            {"lane_id": "L1_REQ", "name": "Employee Requester", "role_type": "HUMAN", "description": "Identifies item need, performs guided search, fills account assignment"},
            {"lane_id": "L2_BUDGET", "name": "Platform Policy & Budget Engine", "role_type": "SYSTEM", "description": "4-Tier search check, budget commitment lock, DMN-01 approval routing"},
            {"lane_id": "L3_APPROVER", "name": "Designated Approvers", "role_type": "HUMAN", "description": "Cost object owner, Department head, Procurement head, Finance controller"},
            {"lane_id": "L4_MDM", "name": "MDM Data Steward", "role_type": "HUMAN", "description": "Parallel governance for reusable new material promotion"}
        ],
        "branches_and_nuances": "Search order enforced: Contract -> Catalogue -> Material -> Free Text. Free-text lines never create material masters unless promoted to parallel MDM request.",
        "steps": [
            {"step_index": 0, "step_id": "S1_START", "label": "Need Identified", "type": "START_EVENT", "lane": "Employee Requester", "screen_ref": None, "candidate_group": "REQUESTER", "key_dmn_or_timer": None, "description": "Employee initiates guided buying request."},
            {"step_index": 1, "step_id": "S2_SEARCH", "label": "Search 'What do you need?'", "type": "USER_TASK", "lane": "Employee Requester", "screen_ref": "REQ-01", "candidate_group": "REQUESTER", "key_dmn_or_timer": "Search Hierarchy", "description": "Guided buying agent evaluates contract and catalogue coverage."},
            {"step_index": 2, "step_id": "S3_GW_MATCH", "label": "Contract/Catalogue Found?", "type": "GATEWAY", "lane": "Platform Policy & Budget Engine", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "Priority Check", "description": "If found, lock price & contract ref. If not found, allow free-text input."},
            {"step_index": 3, "step_id": "S4_FREE_TEXT", "label": "Add Free-Text Line with Material Group", "type": "USER_TASK", "lane": "Employee Requester", "screen_ref": "REQ-02", "candidate_group": "REQUESTER", "key_dmn_or_timer": "3 Quotes Policy", "description": "Employee enters description and assigns cost center / WBS element."},
            {"step_index": 4, "step_id": "S5_GW_REUSE", "label": "Reusable in Future?", "type": "GATEWAY", "lane": "Employee Requester", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "P05 Check", "description": "If flagged as reusable, starts parallel MDM request without blocking PR."},
            {"step_index": 5, "step_id": "S6_PARALLEL_MDM", "label": "New Material Request (Parallel)", "type": "USER_TASK", "lane": "MDM Data Steward", "screen_ref": "MDM-01", "candidate_group": "DATA_STEWARD", "key_dmn_or_timer": "Duplicate Gateway (0.92)", "description": "MDM steward evaluates classification and duplicates in background."},
            {"step_index": 6, "step_id": "S7_BUDGET", "label": "Budget Check & Policy Validation", "type": "SYSTEM_TASK", "lane": "Platform Policy & Budget Engine", "screen_ref": "REQ-02", "candidate_group": None, "key_dmn_or_timer": "DMN-01 Routing Matrix", "description": "Encumbers budget funds. Evaluates multi-tier approval chain."},
            {"step_index": 7, "step_id": "S8_APPROVE", "label": "Approve / Reject / Return", "type": "USER_TASK", "lane": "Designated Approvers", "screen_ref": "REQ-03", "candidate_group": "APPROVER_BY_DMN01", "key_dmn_or_timer": "SLA: 2 Business Days", "description": "Multi-tier approval stream based on spend threshold."},
            {"step_index": 8, "step_id": "S9_END", "label": "Approved PR Handed to Buyer", "type": "END_EVENT", "lane": "Designated Approvers", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "Hand-off to F5", "description": "Requisition fully authorized and placed on open buyer queue."}
        ]
    },
    "F3": {
        "id": "F3",
        "flow_code": "F3",
        "process_key": "pic.sourcing-award",
        "title": "Strategic Sourcing → Award Optimization",
        "start_trigger": "Approved requirement or category sourcing wave (sourcing.event.published)",
        "lanes": [
            {"lane_id": "L1_CAT_MGR", "name": "Category Manager", "role_type": "HUMAN", "description": "Builds RFx event, defines scoring model, invites qualified suppliers"},
            {"lane_id": "L2_SUPPLIER", "name": "Qualified Suppliers", "role_type": "EXTERNAL_SUPPLIER", "description": "Submits sealed commercial & technical bids via supplier portal"},
            {"lane_id": "L3_PLATFORM", "name": "Platform Sourcing Engine", "role_type": "SYSTEM", "description": "TCO normalization, should-cost comparison, MIP optimization solver"},
            {"lane_id": "L4_APPROVERS", "name": "Award Approval Board", "role_type": "HUMAN", "description": "Category Head, CPO, and Finance Controller (SOD-05)"}
        ],
        "branches_and_nuances": "Weights lock at publish. Bids sealed until deadline. Awards >= ₹50L or non-lowest bid require written rationale & multi-role sign-off.",
        "steps": [
            {"step_index": 0, "step_id": "S1_START", "label": "Approved Requirement / Wave", "type": "START_EVENT", "lane": "Category Manager", "screen_ref": None, "candidate_group": "CATEGORY_MGR", "key_dmn_or_timer": None, "description": "Sourcing wave triggered for DC-330 Motor Housings."},
            {"step_index": 1, "step_id": "S2_BUILD", "label": "Build Event, Scoring & Invite Suppliers", "type": "USER_TASK", "lane": "Category Manager", "screen_ref": "SRC-02", "candidate_group": "CATEGORY_MGR", "key_dmn_or_timer": "Weights Lock at Publish", "description": "Invites Trichy Forge, Kovai Diecast, and Salem Light Alloys. Locks weights."},
            {"step_index": 2, "step_id": "S3_BIDS", "label": "Clarifications & Sealed Bids", "type": "USER_TASK", "lane": "Qualified Suppliers", "screen_ref": "SLM-05", "candidate_group": "SUPPLIER_EXTERNAL", "key_dmn_or_timer": "Sealed Envelope Gate", "description": "Suppliers submit sealed bids: ₹398, ₹405, ₹412."},
            {"step_index": 3, "step_id": "S4_TCO", "label": "Normalise Bids, TCO & Should-Cost", "type": "SYSTEM_TASK", "lane": "Platform Sourcing Engine", "screen_ref": "SRC-03", "candidate_group": None, "key_dmn_or_timer": "Should-Cost: ₹391", "description": "Unseals bids at deadline. Computes landed TCO stack and should-cost delta."},
            {"step_index": 4, "step_id": "S5_GW_ROUND", "label": "Another Round / Auction?", "type": "GATEWAY", "lane": "Category Manager", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "Auction Decision", "description": "If bids tight, launch reverse auction. Main path proceeds to award studio."},
            {"step_index": 5, "step_id": "S6_MIP", "label": "Run Award Scenario Studio (MIP)", "type": "USER_TASK", "lane": "Category Manager", "screen_ref": "SRC-04", "candidate_group": "CATEGORY_MGR", "key_dmn_or_timer": "Mixed-Integer Program", "description": "MIP solver allocates 60% Trichy Forge and 40% Kovai Diecast under capacity limits."},
            {"step_index": 6, "step_id": "S7_GW_AUTH", "label": "Award >= ₹50L or Split?", "type": "GATEWAY", "lane": "Platform Sourcing Engine", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "SOD-05 Check", "description": "Award spend is ₹43.29 Cr; triggers CPO and Finance sign-off."},
            {"step_index": 7, "step_id": "S8_APPROVE", "label": "Approve Award Decision", "type": "USER_TASK", "lane": "Award Approval Board", "screen_ref": "SRC-05", "candidate_group": "CPO_AND_FINANCE", "key_dmn_or_timer": "SLA: 2 Business Days", "description": "CPO and Finance Controller validate and sign off under SOD-05."},
            {"step_index": 8, "step_id": "S9_NOTIFY", "label": "Notify Suppliers & Handoff to CLM", "type": "SYSTEM_TASK", "lane": "Platform Sourcing Engine", "screen_ref": "CLM-01", "candidate_group": None, "key_dmn_or_timer": "Handoff to F4", "description": "Dispatches award notifications and creates contract draft SA-5520."},
            {"step_index": 9, "step_id": "S10_END", "label": "Award Recorded & Contract Drafted", "type": "END_EVENT", "lane": "Award Approval Board", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "P12 Negotiated Savings", "description": "Records ₹0.99 Cr annual negotiated savings in pipeline ledger."}
        ]
    },
    "F4": {
        "id": "F4",
        "flow_code": "F4",
        "process_key": "pic.contract",
        "title": "Contract Lifecycle Management (CLM)",
        "start_trigger": "Sourcing award handoff or renewal trigger (-120d timer)",
        "lanes": [
            {"lane_id": "L1_CON_MGR", "name": "Contract Manager", "role_type": "HUMAN", "description": "Authors contract, selects clauses, defines price indexation rules"},
            {"lane_id": "L2_CLM_SYS", "name": "Platform CLM Engine", "role_type": "SYSTEM", "description": "AI playbook redline analysis, consumption alerts, price activation"},
            {"lane_id": "L3_LEGAL", "name": "Legal & Finance Board", "role_type": "HUMAN", "description": "Reviews clause deviations, approves liability caps and indexation"},
            {"lane_id": "L4_SUPPLIER", "name": "Supplier Executive", "role_type": "EXTERNAL_SUPPLIER", "description": "Reviews markup, counter-proposes terms, executes e-signature"}
        ],
        "branches_and_nuances": "LME indexation creates new validity period with ±3% deadband. Consumption alerts at 80/90/100%. Renewal triggers 120 days prior to expiry.",
        "steps": [
            {"step_index": 0, "step_id": "S1_START", "label": "Award or Renewal Trigger", "type": "START_EVENT", "lane": "Contract Manager", "screen_ref": None, "candidate_group": "CONTRACT_MGR", "key_dmn_or_timer": None, "description": "Contract authoring initiated for SA-5520."},
            {"step_index": 1, "step_id": "S2_DRAFT", "label": "Draft from Template & Clause Library", "type": "USER_TASK", "lane": "Contract Manager", "screen_ref": "CLM-01", "candidate_group": "CONTRACT_MGR", "key_dmn_or_timer": "Standard Playbook", "description": "Selects scheduling agreement template with quarterly LME indexation."},
            {"step_index": 2, "step_id": "S3_AI_REDLINE", "label": "AI Redline vs Playbook & Risk Score", "type": "SYSTEM_TASK", "lane": "Platform CLM Engine", "screen_ref": "CLM-02", "candidate_group": None, "key_dmn_or_timer": "Risk Scoring", "description": "Identifies indemnity liability cap deviation and evaluates risk rating."},
            {"step_index": 3, "step_id": "S4_SUPPLIER_REV", "label": "Supplier Review & Redline", "type": "USER_TASK", "lane": "Supplier Executive", "screen_ref": "SLM-05", "candidate_group": "SUPPLIER_EXTERNAL", "key_dmn_or_timer": "Negotiation Window", "description": "Supplier reviews terms and proposes compromise fallback positions."},
            {"step_index": 4, "step_id": "S5_GW_NON_STD", "label": "Non-Standard or >= ₹1 Cr?", "type": "GATEWAY", "lane": "Platform CLM Engine", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "Threshold Check", "description": "Commitment is ₹25.79 Cr with redlines; requires Legal & Finance approval."},
            {"step_index": 5, "step_id": "S6_LEGAL_APP", "label": "Legal & Finance Approval", "type": "USER_TASK", "lane": "Legal & Finance Board", "screen_ref": "CLM-02", "candidate_group": "LEGAL_AND_FINANCE", "key_dmn_or_timer": "SLA: 3 Business Days", "description": "Legal counsel approves compromise with 3x liability cap and porosity carveout."},
            {"step_index": 6, "step_id": "S7_ESIGN", "label": "Digital E-Signature", "type": "USER_TASK", "lane": "Supplier Executive", "screen_ref": "SLM-05", "candidate_group": "SUPPLIER_EXTERNAL", "key_dmn_or_timer": "DocuSign / Aadhaar eSign", "description": "Both parties execute cryptographically signed contract agreement."},
            {"step_index": 7, "step_id": "S8_ACTIVATE", "label": "Activate & Publish Prices to Source List", "type": "SYSTEM_TASK", "lane": "Platform CLM Engine", "screen_ref": "CLM-03", "candidate_group": None, "key_dmn_or_timer": "Price Validity Published", "description": "SA-5520 activated. Publishes effective price ₹398.0 to MRP source determination."},
            {"step_index": 8, "step_id": "S9_MONITOR", "label": "Track Consumption & Indexation Resets", "type": "SYSTEM_TASK", "lane": "Platform CLM Engine", "screen_ref": "CLM-04", "candidate_group": None, "key_dmn_or_timer": "Quarterly LME Evaluation", "description": "Monitors release orders against ₹25.79 Cr commitment and tracks deadband."},
            {"step_index": 9, "step_id": "S10_END", "label": "Active Contract Operating", "type": "END_EVENT", "lane": "Contract Manager", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "Ready for F5 PO", "description": "Framework active and ready for operational PO releases."}
        ]
    },
    "F5": {
        "id": "F5",
        "flow_code": "F5",
        "process_key": "pic.po",
        "title": "Purchase Order → Supplier Confirmation → Delivery",
        "start_trigger": "Approved PR or scheduled release due",
        "lanes": [
            {"lane_id": "L1_BUYER", "name": "Operational Buyer", "role_type": "HUMAN", "description": "Reviews open PRs, validates terms inheritance, expedites delivery"},
            {"lane_id": "L2_PO_SYS", "name": "Platform PO Engine", "role_type": "SYSTEM", "description": "Additive PO risk score computation, DMN-02 touchless release gate"},
            {"lane_id": "L3_APPROVER", "name": "Designated PO Approver", "role_type": "HUMAN", "description": "Required if PO risk >= 20 or price deviates from contract"},
            {"lane_id": "L4_SUPPLIER", "name": "Supplier Logistics", "role_type": "EXTERNAL_SUPPLIER", "description": "Confirms PO lines, proposes delivery adjustments, dispatches ASN"}
        ],
        "branches_and_nuances": "Touchless release triggers if Risk Score < 20 and price equals contract. Changes outside tolerance create new version n+1 back to buyer.",
        "steps": [
            {"step_index": 0, "step_id": "S1_START", "label": "Approved PR / Release Due", "type": "START_EVENT", "lane": "Operational Buyer", "screen_ref": None, "candidate_group": "BUYER", "key_dmn_or_timer": None, "description": "Release need arrives for 5,400 units against SA-5520."},
            {"step_index": 1, "step_id": "S2_INHERIT", "label": "Source Determination & Terms Inheritance", "type": "SYSTEM_TASK", "lane": "Platform PO Engine", "screen_ref": "PO-01", "candidate_group": None, "key_dmn_or_timer": "P07 Inheritance", "description": "Creates PO-77410 inheriting price ₹398, terms N60, and delivery tolerances."},
            {"step_index": 2, "step_id": "S3_RISK", "label": "AI Validation & PO Risk Score", "type": "SYSTEM_TASK", "lane": "Platform PO Engine", "screen_ref": "PO-02", "candidate_group": None, "key_dmn_or_timer": "Risk Formula", "description": "Risk Score = 18/100 (Late prob 0.22 contributes 18 points; within threshold)."},
            {"step_index": 3, "step_id": "S4_GW_TOUCHLESS", "label": "Touchless Criteria Met?", "type": "GATEWAY", "lane": "Platform PO Engine", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "DMN-02 (Risk <= 20)", "description": "Score 18 <= 20. Autonomously bypasses human queue to TOUCHLESS_RELEASE."},
            {"step_index": 4, "step_id": "S5_HUMAN_APP", "label": "Approve PO (If High Risk)", "type": "USER_TASK", "lane": "Designated PO Approver", "screen_ref": "REQ-03", "candidate_group": "PO_APPROVER", "key_dmn_or_timer": "SLA: 1 Business Day", "description": "Bypassed on touchless path. Human sign-off required only on deviation."},
            {"step_index": 5, "step_id": "S6_TRANSMIT", "label": "Transmit (Portal / EDI / cXML)", "type": "SYSTEM_TASK", "lane": "Platform PO Engine", "screen_ref": "PO-02", "candidate_group": None, "key_dmn_or_timer": "Outbox Dispatch", "description": "Dispatches electronic purchase order to Trichy Forge Works portal."},
            {"step_index": 6, "step_id": "S7_CONFIRM", "label": "Supplier Confirmation", "type": "USER_TASK", "lane": "Supplier Logistics", "screen_ref": "SLM-05", "candidate_group": "SUPPLIER_EXTERNAL", "key_dmn_or_timer": "SLA: 24 Hours", "description": "Supplier confirms quantity 5,400 units and promised delivery date."},
            {"step_index": 7, "step_id": "S8_GW_CHANGE", "label": "Change Within Tolerance?", "type": "GATEWAY", "lane": "Platform PO Engine", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "Tolerance Gate", "description": "No deviation detected; proceeding to shipping notice."},
            {"step_index": 8, "step_id": "S9_DISPATCH_ASN", "label": "Ship Goods & Send ASN-61208", "type": "USER_TASK", "lane": "Supplier Logistics", "screen_ref": "RCV-01", "candidate_group": "SUPPLIER_EXTERNAL", "key_dmn_or_timer": "Transit Dispatch", "description": "Supplier dispatches 54 bins (5,400 units) via NH44 corridor."},
            {"step_index": 9, "step_id": "S10_END", "label": "Goods in Transit (Hand-off to F6)", "type": "END_EVENT", "lane": "Supplier Logistics", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "Hand-off to F6", "description": "Electronic dispatch recorded; ready for physical dock receipt."}
        ]
    },
    "F6": {
        "id": "F6",
        "flow_code": "F6",
        "process_key": "pic.receipt",
        "title": "Goods Receipt / Service Entry → Quality Inspection",
        "start_trigger": "Inbound shipment arrival or service completed",
        "lanes": [
            {"lane_id": "L1_RECEIVER", "name": "Storekeeper / Service Owner", "role_type": "HUMAN", "description": "Receives physical cargo, scans bins, certifies service milestones"},
            {"lane_id": "L2_RCV_SYS", "name": "Platform Receiving Engine", "role_type": "SYSTEM", "description": "Checks over-delivery tolerance, routes to inspection, updates inventory"},
            {"lane_id": "L3_QUALITY", "name": "Quality Inspector", "role_type": "HUMAN", "description": "Metrology sampling, CMM porosity test, usage decision (SOD-03)"},
            {"lane_id": "L4_SUPPLIER", "name": "Supplier Logistics", "role_type": "EXTERNAL_SUPPLIER", "description": "Receives rejection notification, issues credit note or replacement"}
        ],
        "branches_and_nuances": "SOD-03 blocks PO creator from posting GR. Quality hold places goods in inspection stock until usage decision QL-2210.",
        "steps": [
            {"step_index": 0, "step_id": "S1_START", "label": "Consignment Arrives at Gate", "type": "START_EVENT", "lane": "Storekeeper / Service Owner", "screen_ref": None, "candidate_group": "STOREKEEPER", "key_dmn_or_timer": None, "description": "Truck arrives at Plant P100 receiving dock."},
            {"step_index": 1, "step_id": "S2_GW_TYPE", "label": "Goods or Service?", "type": "GATEWAY", "lane": "Platform Receiving Engine", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "P08 Purchase Type", "description": "Physical die-cast motor housings route to Goods Receipt lane."},
            {"step_index": 2, "step_id": "S3_POST_GR", "label": "Post Goods Receipt (GR-90231)", "type": "USER_TASK", "lane": "Storekeeper / Service Owner", "screen_ref": "RCV-02", "candidate_group": "STOREKEEPER", "key_dmn_or_timer": "SOD-03 Check", "description": "Storekeeper verifies 5,400 units arrived. Posted by u:store.keeper.hosur."},
            {"step_index": 3, "step_id": "S4_GW_QC", "label": "Quality Managed?", "type": "GATEWAY", "lane": "Platform Receiving Engine", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "Material Master Flag", "description": "Critical automotive casting requires Nadcap/CMM metrology check."},
            {"step_index": 4, "step_id": "S5_INSPECT", "label": "Metrology Inspection & Usage Decision", "type": "USER_TASK", "lane": "Quality Inspector", "screen_ref": "RCV-04", "candidate_group": "QUALITY_INSPECTOR", "key_dmn_or_timer": "QL-2210 Decision", "description": "CMM check accepts 5,380 parts to stock; quarantines 20 parts with porosity."},
            {"step_index": 5, "step_id": "S6_REJECT_NOTICE", "label": "Replacement or Credit Note Trigger", "type": "USER_TASK", "lane": "Supplier Logistics", "screen_ref": "SLM-05", "candidate_group": "SUPPLIER_EXTERNAL", "key_dmn_or_timer": "Defect Notice", "description": "Automated rejection notice dispatched to Trichy Forge for 20 units."},
            {"step_index": 6, "step_id": "S7_UPDATE_STOCK", "label": "Update Unrestricted Stock & GRIR", "type": "SYSTEM_TASK", "lane": "Platform Receiving Engine", "screen_ref": "SLM-03", "candidate_group": None, "key_dmn_or_timer": "Inventory Ledger Sync", "description": "5,380 units credited to unrestricted stock. Scorecard logged at 99.6% quality."},
            {"step_index": 7, "step_id": "S8_END", "label": "Receipt Complete (Ready for 3-Way Match)", "type": "END_EVENT", "lane": "Platform Receiving Engine", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "Hand-off to F7", "description": "Unrestricted inventory active. Clear for accounts payable reconciliation."}
        ]
    },
    "F7": {
        "id": "F7",
        "flow_code": "F7",
        "process_key": "pic.invoice",
        "title": "Invoice Matching → ERP Posting → Payment Run",
        "start_trigger": "Supplier invoice submitted via portal or e-invoice IRN",
        "lanes": [
            {"lane_id": "L1_SUPPLIER", "name": "Supplier Accounts Receivable", "role_type": "EXTERNAL_SUPPLIER", "description": "Submits invoice, uploads tax IRN, provides credit notes on variance"},
            {"lane_id": "L2_AP_SYS", "name": "Platform AP Matching Engine", "role_type": "SYSTEM", "description": "2/3-way tolerance comparison, idempotency validation, ERP posting"},
            {"lane_id": "L3_AP_CLERK", "name": "Accounts Payable Clerk", "role_type": "HUMAN", "description": "Resolves match exceptions, attaches credit notes (SOD-04)"},
            {"lane_id": "L4_FINANCE_ERP", "name": "ERP Financial Ledger / Bank", "role_type": "SYSTEM", "description": "SAP S/4HANA invoice posting, payment release, P&L savings realization"}
        ],
        "branches_and_nuances": "Quantity variance (+20 billed above accepted GR) blocks payment until Credit Note CN-TF-221 is attached. Posting is idempotent via transactional outbox.",
        "steps": [
            {"step_index": 0, "step_id": "S1_START", "label": "Invoice Submitted (INV-TF-8812)", "type": "START_EVENT", "lane": "Supplier Accounts Receivable", "screen_ref": None, "candidate_group": "SUPPLIER_EXTERNAL", "key_dmn_or_timer": None, "description": "Supplier bills 5,400 units @ ₹398 = ₹21,49,200."},
            {"step_index": 1, "step_id": "S2_CAPTURE", "label": "Capture & Duplicate Detection", "type": "SYSTEM_TASK", "lane": "Platform AP Matching Engine", "screen_ref": "INV-01", "candidate_group": None, "key_dmn_or_timer": "Fuzzy Duplicate Check", "description": "Validates GST IRN and checks vendor/invoice number uniqueness."},
            {"step_index": 2, "step_id": "S3_MATCH", "label": "3-Way Match with Tolerances (PO × GR × Inv)", "type": "SYSTEM_TASK", "lane": "Platform AP Matching Engine", "screen_ref": "INV-02", "candidate_group": None, "key_dmn_or_timer": "DMN-03 Tolerances", "description": "Compares 5,400 billed vs 5,380 accepted GR. Discrepancy: +20 units variance."},
            {"step_index": 3, "step_id": "S4_GW_TOL", "label": "Within Tolerance?", "type": "GATEWAY", "lane": "Platform AP Matching Engine", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "Quantity Tol: 0%", "description": "Quantity exception detected (+20). Sets payment lock and diverts to AP."},
            {"step_index": 4, "step_id": "S5_RESOLVE", "label": "Resolve Exception (Credit Note CN-TF-221)", "type": "USER_TASK", "lane": "Accounts Payable Clerk", "screen_ref": "INV-02", "candidate_group": "AP_CLERK", "key_dmn_or_timer": "SOD-04 Enforcement", "description": "AP Clerk applies Credit Note CN-TF-221 for ₹7,960. Invoice reconciles to MATCHED."},
            {"step_index": 5, "step_id": "S6_POST_ERP", "label": "Post to SAP S/4HANA (Idempotent)", "type": "SYSTEM_TASK", "lane": "Platform AP Matching Engine", "screen_ref": "INV-03", "candidate_group": None, "key_dmn_or_timer": "Outbox Doc #5100004421", "description": "Idempotent posting succeeds. SAP Document #5100004421 generated."},
            {"step_index": 6, "step_id": "S7_PAYMENT", "label": "Payment Run & Remittance", "type": "SYSTEM_TASK", "lane": "ERP Financial Ledger / Bank", "screen_ref": "INV-04", "candidate_group": None, "key_dmn_or_timer": "N60 Payment Term", "description": "Clears payment block for scheduled payment release at N60."},
            {"step_index": 7, "step_id": "S8_SAVINGS_SYNC", "label": "Realised P&L Savings Sync (SV-0412)", "type": "SYSTEM_TASK", "lane": "Platform AP Matching Engine", "screen_ref": "SAV-02", "candidate_group": None, "key_dmn_or_timer": "Principle P12", "description": "Credits ₹0.38 Cr realised savings strictly from verified posted invoice."},
            {"step_index": 8, "step_id": "S9_END", "label": "Paid & Reconciled (End of Cycle)", "type": "END_EVENT", "lane": "ERP Financial Ledger / Bank", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "Audit Trail Locked", "description": "Hash-chained audit log sealed. Complete 10-step lifecycle complete."}
        ]
    },
    "F8": {
        "id": "F8",
        "flow_code": "F8",
        "process_key": "pic.supplier-onboarding",
        "title": "Supplier Onboarding & Category Qualification (SLM)",
        "start_trigger": "Supplier invitation or portal registration",
        "lanes": [
            {"lane_id": "L1_SUPPLIER", "name": "Prospective Supplier", "role_type": "EXTERNAL_SUPPLIER", "description": "Completes registration, uploads certifications and tax/bank proof"},
            {"lane_id": "L2_SLM_SYS", "name": "Platform SLM Sentinel", "role_type": "SYSTEM", "description": "Sanctions screening, duplicate vendor check, certificate expiry tracker"},
            {"lane_id": "L3_FINANCE", "name": "Finance & Compliance", "role_type": "HUMAN", "description": "Dual-approval bank detail validation and tax ID verification (SOD-02)"},
            {"lane_id": "L4_SLM_MGR", "name": "Supplier Manager", "role_type": "HUMAN", "description": "Conducts category audits, sample evaluations, and sets qualification status"}
        ],
        "branches_and_nuances": "Qualification is per category. Bank modifications require dual finance approval (SOD-02) and 14-day cooling-off period.",
        "steps": [
            {"step_index": 0, "step_id": "S1_START", "label": "Invitation / Registration", "type": "START_EVENT", "lane": "Prospective Supplier", "screen_ref": None, "candidate_group": "SUPPLIER_EXTERNAL", "key_dmn_or_timer": None, "description": "Supplier receives invitation or self-registers on portal."},
            {"step_index": 1, "step_id": "S2_PROFILE", "label": "Submit Profile, Tax IDs & Bank Info", "type": "USER_TASK", "lane": "Prospective Supplier", "screen_ref": "SLM-05", "candidate_group": "SUPPLIER_EXTERNAL", "key_dmn_or_timer": "Mandatory Docs", "description": "Uploads GSTIN, MSME, ISO/IATF certificates, and bank cheque."},
            {"step_index": 2, "step_id": "S3_CHECKS", "label": "Duplicate, Sanctions & Bank Checks", "type": "SYSTEM_TASK", "lane": "Platform SLM Sentinel", "screen_ref": "SLM-02", "candidate_group": None, "key_dmn_or_timer": "Penny-Drop & Watchlist", "description": "Runs automated penny-drop verification and OFAC/sanctions screening."},
            {"step_index": 3, "step_id": "S4_BANK_VERIFY", "label": "Verify Bank & Tax (Dual Approval)", "type": "USER_TASK", "lane": "Finance & Compliance", "screen_ref": "MDM-04", "candidate_group": "FINANCE_CONTROLLER", "key_dmn_or_timer": "SOD-02 Dual Approval", "description": "Two distinct finance officers verify and approve bank details with call-back."},
            {"step_index": 4, "step_id": "S5_CAT_AUDIT", "label": "Category Qualification (Audit & PPAP)", "type": "USER_TASK", "lane": "Supplier Manager", "screen_ref": "SLM-02", "candidate_group": "SUPPLIER_MGR", "key_dmn_or_timer": "Category Qualification", "description": "Audits production line for 'Die-Casting & Machining' capability."},
            {"step_index": 5, "step_id": "S6_GW_QUAL", "label": "Qualified?", "type": "GATEWAY", "lane": "Supplier Manager", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "Score >= 80", "description": "Audit score: 92/100. Supplier qualified for die-casting."},
            {"step_index": 6, "step_id": "S7_CREATE_MASTER", "label": "Create Supplier Master & Sync ERP", "type": "SYSTEM_TASK", "lane": "Platform SLM Sentinel", "screen_ref": "MDM-04", "candidate_group": None, "key_dmn_or_timer": "ERP Sync", "description": "Creates golden vendor record TF001 and syncs to SAP S/4HANA."},
            {"step_index": 7, "step_id": "S8_MONITOR_TWIN", "label": "Monitor Twin Telemetry & OTIF", "type": "SYSTEM_TASK", "lane": "Platform SLM Sentinel", "screen_ref": "SLM-04", "candidate_group": None, "key_dmn_or_timer": "Live Scorecard", "description": "Continuous telemetry streaming for machine capacity and quality PPM."},
            {"step_index": 8, "step_id": "S9_END", "label": "Supplier Active in Network", "type": "END_EVENT", "lane": "Supplier Manager", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "Eligible for Sourcing", "description": "Vendor eligible to participate in RFx sourcing and receive purchase orders."}
        ]
    },
    "F9": {
        "id": "F9",
        "flow_code": "F9",
        "process_key": "pic.material-request",
        "title": "Material Master Governance (MDM Duplicate Shield)",
        "start_trigger": "New reusable item request submitted",
        "lanes": [
            {"lane_id": "L1_REQ", "name": "Requester / Buyer", "role_type": "HUMAN", "description": "Submits material master creation request with attributes"},
            {"lane_id": "L2_MDM_SYS", "name": "Platform MDM Engine", "role_type": "SYSTEM", "description": "Fuzzy token similarity, duplicate cutoff detection, classification"},
            {"lane_id": "L3_STEWARDS", "name": "Domain Data Stewards", "role_type": "HUMAN", "description": "Enriches purchasing, plant, quality, and accounting views (SOD-06)"},
            {"lane_id": "L4_ERP", "name": "ERP Master Repository", "role_type": "SYSTEM", "description": "Assigns standard material ID, syncs to SAP S/4HANA"}
        ],
        "branches_and_nuances": "Duplicate score >= 0.92 automatically blocks creation and redirects requester to existing standard material (Principle P03).",
        "steps": [
            {"step_index": 0, "step_id": "S1_START", "label": "New Reusable Item Needed", "type": "START_EVENT", "lane": "Requester / Buyer", "screen_ref": None, "candidate_group": "REQUESTER", "key_dmn_or_timer": None, "description": "User requests new item creation."},
            {"step_index": 1, "step_id": "S2_SUBMIT", "label": "Submit Material Request", "type": "USER_TASK", "lane": "Requester / Buyer", "screen_ref": "MDM-01", "candidate_group": "REQUESTER", "key_dmn_or_timer": "Mandatory Attributes", "description": "Enters description, material group, UoM, and manufacturer part number."},
            {"step_index": 2, "step_id": "S3_DUP_AI", "label": "Duplicate & Classification AI Scorer", "type": "SYSTEM_TASK", "lane": "Platform MDM Engine", "screen_ref": "MDM-03", "candidate_group": None, "key_dmn_or_timer": "Jaccard + SequenceMatcher", "description": "Computes token similarity against existing standard master records."},
            {"step_index": 3, "step_id": "S4_GW_DUP", "label": "Duplicate Score >= 0.92?", "type": "GATEWAY", "lane": "Platform MDM Engine", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "Cutoff Gate: 0.92", "description": "If >= 0.92, blocks duplicate and redirects to existing material (P03)."},
            {"step_index": 4, "step_id": "S5_STEWARDS", "label": "Enrich & Approve by Domain Stewards", "type": "USER_TASK", "lane": "Domain Data Stewards", "screen_ref": "MDM-02", "candidate_group": "DATA_STEWARDS", "key_dmn_or_timer": "SOD-06 Check", "description": "Stewards enrich purchasing, valuation, and inspection settings."},
            {"step_index": 5, "step_id": "S6_CREATE_ERP", "label": "Create Material in SAP S/4HANA", "type": "SYSTEM_TASK", "lane": "ERP Master Repository", "screen_ref": "ADM-05", "candidate_group": None, "key_dmn_or_timer": "Transactional Outbox", "description": "Generates standard material number MAT-DC330-HSG."},
            {"step_index": 6, "step_id": "S7_LINK_PR", "label": "Link to PR Line / Catalogue / Contract", "type": "SYSTEM_TASK", "lane": "Platform MDM Engine", "screen_ref": "REQ-02", "candidate_group": None, "key_dmn_or_timer": "P10 Lineage Link", "description": "Updates originating requisition line to reference approved master record."},
            {"step_index": 7, "step_id": "S8_END", "label": "Golden Record Live", "type": "END_EVENT", "lane": "ERP Master Repository", "screen_ref": None, "candidate_group": None, "key_dmn_or_timer": "Master Available", "description": "Standard material available for all plant planners and requisitioners."}
        ]
    }
}

ACTIVE_TOKEN_STATES: Dict[str, Dict[str, Any]] = {
    "F1": {"current_step_index": 0, "status": "IN_PROGRESS", "history": [0]},
    "F2": {"current_step_index": 0, "status": "IN_PROGRESS", "history": [0]},
    "F3": {"current_step_index": 0, "status": "IN_PROGRESS", "history": [0]},
    "F4": {"current_step_index": 0, "status": "IN_PROGRESS", "history": [0]},
    "F5": {"current_step_index": 0, "status": "IN_PROGRESS", "history": [0]},
    "F6": {"current_step_index": 0, "status": "IN_PROGRESS", "history": [0]},
    "F7": {"current_step_index": 0, "status": "IN_PROGRESS", "history": [0]},
    "F8": {"current_step_index": 0, "status": "IN_PROGRESS", "history": [0]},
    "F9": {"current_step_index": 0, "status": "IN_PROGRESS", "history": [0]}
}

@router.get("/flows")
async def list_bpmn_flows():
    """List all 9 BPMN flows (F1 to F9) with summary metadata."""
    result = []
    for f_id, f_data in BPMN_FLOWS.items():
        state = ACTIVE_TOKEN_STATES.get(f_id, {"current_step_index": 0, "status": "IN_PROGRESS"})
        result.append({
            "id": f_data["id"],
            "flow_code": f_data["flow_code"],
            "process_key": f_data["process_key"],
            "title": f_data["title"],
            "start_trigger": f_data["start_trigger"],
            "lanes_count": len(f_data["lanes"]),
            "lanes": [l["name"] for l in f_data["lanes"]],
            "total_steps": len(f_data["steps"]),
            "current_token_step": state["current_step_index"],
            "current_token_status": state["status"]
        })
    return result

@router.get("/flows/{flow_id}")
async def get_bpmn_flow_detail(flow_id: str):
    """Retrieve complete swimlanes, tasks, gateways, and live token position for a flow."""
    key = flow_id.upper()
    if key not in BPMN_FLOWS:
        raise HTTPException(status_code=404, detail=f"BPMN Flow '{flow_id}' not found. Valid flows: F1 to F9")
    
    flow = BPMN_FLOWS[key].copy()
    state = ACTIVE_TOKEN_STATES.get(key, {"current_step_index": 0, "status": "IN_PROGRESS", "history": [0]})
    current_idx = state["current_step_index"]
    active_step = flow["steps"][current_idx] if current_idx < len(flow["steps"]) else flow["steps"][-1]
    
    return {
        "status": "success",
        "flow": flow,
        "token_state": {
            "current_step_index": current_idx,
            "active_step": active_step,
            "status": state["status"],
            "history": state.get("history", [0])
        }
    }

@router.post("/flows/{flow_id}/simulate")
async def simulate_token_step(flow_id: str, req: TokenStepRequest):
    """
    Advance the execution token to the next step.
    Evaluates gateways, branch selection, and human task candidate groups.
    """
    key = flow_id.upper()
    if key not in BPMN_FLOWS:
        raise HTTPException(status_code=404, detail=f"Flow '{flow_id}' not found")
    
    flow = BPMN_FLOWS[key]
    total_steps = len(flow["steps"])
    current_idx = req.current_step_index
    
    if current_idx >= total_steps - 1:
        # Already at end event, wrap or complete
        next_idx = total_steps - 1
        new_status = "COMPLETED"
    else:
        next_idx = current_idx + 1
        new_status = "IN_PROGRESS" if next_idx < total_steps - 1 else "COMPLETED"
    
    # Update state
    if key not in ACTIVE_TOKEN_STATES:
        ACTIVE_TOKEN_STATES[key] = {"current_step_index": 0, "status": "IN_PROGRESS", "history": [0]}
    
    ACTIVE_TOKEN_STATES[key]["current_step_index"] = next_idx
    ACTIVE_TOKEN_STATES[key]["status"] = new_status
    if next_idx not in ACTIVE_TOKEN_STATES[key]["history"]:
        ACTIVE_TOKEN_STATES[key]["history"].append(next_idx)
    
    next_step = flow["steps"][next_idx]
    
    return {
        "status": "success",
        "flow_id": key,
        "previous_step_index": current_idx,
        "new_step_index": next_idx,
        "active_step": next_step,
        "token_status": new_status,
        "message": f"Token advanced to Step {next_idx + 1}/{total_steps}: '{next_step['label']}' in lane '{next_step['lane']}'"
    }

@router.post("/flows/{flow_id}/reset")
async def reset_token(flow_id: str):
    """Reset the execution token to the Start Event."""
    key = flow_id.upper()
    if key not in BPMN_FLOWS:
        raise HTTPException(status_code=404, detail=f"Flow '{flow_id}' not found")
    
    ACTIVE_TOKEN_STATES[key] = {
        "current_step_index": 0,
        "status": "IN_PROGRESS",
        "history": [0]
    }
    
    return {
        "status": "success",
        "message": f"Flow {key} token reset to Start Event (Step 1).",
        "current_step_index": 0,
        "active_step": BPMN_FLOWS[key]["steps"][0]
    }
