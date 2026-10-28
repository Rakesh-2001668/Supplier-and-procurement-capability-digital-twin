"""
AlphaHelion Purchasing Intelligence Cloud — Spend Cube & Governed AI Agent Runtime
Covers Modules:
- M01: Spend Analytics & Spend Cube (SPD-01..09)
  - 8-dimensional spend aggregation (Supplier, Commodity, Plant, Type, Period, Contract Coverage)
  - Maverick Spend Analysis (Principle P03 violation detection)
  - Tail Spend Pareto 80/20 Classification
  - Sourcing Opportunity Discovery
- M12: Governed AI Agent Runtime & Copilot Answer Contract (AIX-01..03)
  - 14 Governed AI Agents operating across L0..L4 autonomy
  - Agent and Global Emergency Kill Switch
  - Principle P11: 6-Field Explainable Copilot Answer Contract
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid

from app.services.lineage_service import lineage_engine
from app.services.sod_service import sod_engine, action_history_store

router = APIRouter(prefix="/api/v1/spend", tags=["Spend Analytics & Spend Cube"])
agents_router = APIRouter(prefix="/api/v1/agents", tags=["Governed AI Agents & Copilot Runtime"])

# -------------------------------------------------------------
# Module M01: Spend Cube In-Memory Database
# -------------------------------------------------------------

SPEND_CUBE_RECORDS = [
    # Axion Mobility Systems FY26 Invoiced & Committed Spend
    {
        "id": "SP-001",
        "supplier_id": "TF001",
        "supplier_name": "Trichy Forge Works",
        "commodity": "Castings & Forgings",
        "commodity_code": "CAST-ALU-HPDC",
        "material_id": "MAT-DC330-HSG",
        "plant": "P100 Hosur",
        "company_code": "1000",
        "period": "2026-Q3",
        "purchase_type": "SCHEDULING_AGREEMENT",
        "contract_id": "SA-5520",
        "is_on_contract": True,
        "spend_inr": 2141240.0,  # From INV-TF-8812 & PO-77410
        "quantity": 5380,
        "uom": "EA",
        "unit_price_inr": 398.00
    },
    {
        "id": "SP-002",
        "supplier_id": "KD002",
        "supplier_name": "Kovai Diecast Industries",
        "commodity": "Castings & Forgings",
        "commodity_code": "CAST-ALU-HPDC",
        "material_id": "MAT-DC330-HSG",
        "plant": "P100 Hosur",
        "company_code": "1000",
        "period": "2026-Q3",
        "purchase_type": "CONTRACT_PO",
        "contract_id": "SA-5521",
        "is_on_contract": True,
        "spend_inr": 1458000.0,
        "quantity": 3600,
        "uom": "EA",
        "unit_price_inr": 405.00
    },
    {
        "id": "SP-003",
        "supplier_id": "SLA003",
        "supplier_name": "Salem Light Alloys",
        "commodity": "Castings & Forgings",
        "commodity_code": "CAST-ALU-HPDC",
        "material_id": "FREE-TEXT-DIECAST",
        "plant": "P200 Chennai",
        "company_code": "1000",
        "period": "2026-Q3",
        "purchase_type": "FREE_TEXT_SPOT",
        "contract_id": None,
        "is_on_contract": False,  # Maverick spend!
        "spend_inr": 14000000.0,  # ₹1.4 Cr maverick spend
        "quantity": 32900,
        "uom": "EA",
        "unit_price_inr": 425.50
    },
    {
        "id": "SP-004",
        "supplier_id": "PREC004",
        "supplier_name": "Precision AutoComp Ltd",
        "commodity": "Electrical & Motors",
        "commodity_code": "ELEC-ROT-330",
        "material_id": "MAT-DC330-ROT",
        "plant": "P100 Hosur",
        "company_code": "1000",
        "period": "2026-Q3",
        "purchase_type": "STANDARD_PO",
        "contract_id": "CNT-ELEC-401",
        "is_on_contract": True,
        "spend_inr": 8625000.0,
        "quantity": 6900,
        "uom": "EA",
        "unit_price_inr": 1250.00
    },
    {
        "id": "SP-005",
        "supplier_id": "FAST005",
        "supplier_name": "Sundaram Fasteners Ltd",
        "commodity": "Fasteners & Hardware",
        "commodity_code": "FAST-BOLT-M8",
        "material_id": "MAT-FAST-M8X30",
        "plant": "P100 Hosur",
        "company_code": "1000",
        "period": "2026-Q3",
        "purchase_type": "STANDARD_PO",
        "contract_id": "CNT-FAST-109",
        "is_on_contract": True,
        "spend_inr": 432000.0,
        "quantity": 90000,
        "uom": "EA",
        "unit_price_inr": 4.80
    },
    {
        "id": "SP-006",
        "supplier_id": "TAIL-991",
        "supplier_name": "Local Industrial Consumables",
        "commodity": "MRO & Consumables",
        "commodity_code": "MRO-SHOP-01",
        "material_id": "FREE-TEXT-SAFETY-GLOVES",
        "plant": "P100 Hosur",
        "company_code": "1000",
        "period": "2026-Q3",
        "purchase_type": "FREE_TEXT_SPOT",
        "contract_id": None,
        "is_on_contract": False,
        "spend_inr": 185000.0,
        "quantity": 500,
        "uom": "PAIR",
        "unit_price_inr": 370.00
    }
]

# -------------------------------------------------------------
# Module M12: 14 Governed AI Agents Registry
# -------------------------------------------------------------

AI_AGENTS_REGISTRY: Dict[str, Dict[str, Any]] = {
    "AGT-MAVERICK-01": {
        "id": "AGT-MAVERICK-01",
        "name": "Spend Maverick Watchdog",
        "module": "M01 Spend Analytics",
        "autonomy_level": "L2_PROPOSE_DRAFT",
        "description": "Scans purchase requisitions against active contracts (P03) and flags uncontracted purchases above threshold.",
        "status": "ACTIVE",
        "kill_switch_engaged": False,
        "actions_today": 42,
        "last_active": "2026-10-22T14:40:00Z"
    },
    "AGT-MRP-02": {
        "id": "AGT-MRP-02",
        "name": "MRP Netting & Shortage Predictor",
        "module": "M02 Demand Planning",
        "autonomy_level": "L3_SUPERVISED_ACTION",
        "description": "Explodes multi-tier BOMs, net requirements against lead times, and recommends planned order firm dates.",
        "status": "ACTIVE",
        "kill_switch_engaged": False,
        "actions_today": 38,
        "last_active": "2026-10-22T14:42:00Z"
    },
    "AGT-MDM-03": {
        "id": "AGT-MDM-03",
        "name": "MDM Duplicate Sentinel",
        "module": "M03 Master Data",
        "autonomy_level": "L4_AUTONOMOUS_EXECUTE",
        "description": "Calculates fuzzy lexical & token similarity on material requests, autonomously blocking records >= 0.92.",
        "status": "ACTIVE",
        "kill_switch_engaged": False,
        "actions_today": 12,
        "last_active": "2026-10-22T14:35:00Z"
    },
    "AGT-REQUISITION-04": {
        "id": "AGT-REQUISITION-04",
        "name": "Requisition 4-Tier Router",
        "module": "M04 Requisitions",
        "autonomy_level": "L3_SUPERVISED_ACTION",
        "description": "Applies DMN-01 approval matrices and auto-routes contract-backed requisitions.",
        "status": "ACTIVE",
        "kill_switch_engaged": False,
        "actions_today": 65,
        "last_active": "2026-10-22T14:45:00Z"
    },
    "AGT-SHOULD-COST-05": {
        "id": "AGT-SHOULD-COST-05",
        "name": "Sourcing Should-Cost Estimator",
        "module": "M05 Sourcing",
        "autonomy_level": "L1_RECOMMEND",
        "description": "Computes bottom-up raw metal, cycle time, machine hour rate, and margin stacks for RFQs.",
        "status": "ACTIVE",
        "kill_switch_engaged": False,
        "actions_today": 9,
        "last_active": "2026-10-22T14:15:00Z"
    },
    "AGT-MIP-06": {
        "id": "AGT-MIP-06",
        "name": "TCO MIP Award Optimizer",
        "module": "M05 Sourcing",
        "autonomy_level": "L2_PROPOSE_DRAFT",
        "description": "Solves mixed-integer programming capacity-constrained split allocations eliminating single-source risk.",
        "status": "ACTIVE",
        "kill_switch_engaged": False,
        "actions_today": 4,
        "last_active": "2026-10-22T14:20:00Z"
    },
    "AGT-INDEXATION-07": {
        "id": "AGT-INDEXATION-07",
        "name": "LME Metal Indexation Agent",
        "module": "M07 CLM",
        "autonomy_level": "L2_PROPOSE_DRAFT",
        "description": "Monitors LME aluminium cash prices against contract baselines and evaluates +/- 3% deadband resets.",
        "status": "ACTIVE",
        "kill_switch_engaged": False,
        "actions_today": 16,
        "last_active": "2026-10-22T14:30:00Z"
    },
    "AGT-TOUCHLESS-PO-08": {
        "id": "AGT-TOUCHLESS-PO-08",
        "name": "Touchless PO Auto-Release Orchestrator",
        "module": "M08 Purchase Orders",
        "autonomy_level": "L4_AUTONOMOUS_EXECUTE",
        "description": "Evaluates additive risk scores (0-100) and autonomously releases orders with Risk <= 20 & Value <= 50L.",
        "status": "ACTIVE",
        "kill_switch_engaged": False,
        "actions_today": 88,
        "last_active": "2026-10-22T14:48:00Z"
    },
    "AGT-ASN-09": {
        "id": "AGT-ASN-09",
        "name": "ASN Dispatch & Transit Sentinel",
        "module": "M09 Receiving",
        "autonomy_level": "L3_SUPERVISED_ACTION",
        "description": "Validates packaging bar-codes, IoT tamper sensors, and ETA drift before warehouse arrival.",
        "status": "ACTIVE",
        "kill_switch_engaged": False,
        "actions_today": 24,
        "last_active": "2026-10-22T14:22:00Z"
    },
    "AGT-QUALITY-10": {
        "id": "AGT-QUALITY-10",
        "name": "Goods Receiving Quality Auditor",
        "module": "M09 Receiving",
        "autonomy_level": "L3_SUPERVISED_ACTION",
        "description": "Quarantines lots failing CMM/porosity checks (e.g. QL-2210) and posts accepted stock into unrestricted inventory.",
        "status": "ACTIVE",
        "kill_switch_engaged": False,
        "actions_today": 18,
        "last_active": "2026-10-22T14:36:00Z"
    },
    "AGT-INVOICE-11": {
        "id": "AGT-INVOICE-11",
        "name": "3-Way Invoice Matching Resolver",
        "module": "M10 Invoicing",
        "autonomy_level": "L3_SUPERVISED_ACTION",
        "description": "Compares PO, GR, and Invoice with DMN-03 tolerances, blocking quantity over-billing and requesting credit notes.",
        "status": "ACTIVE",
        "kill_switch_engaged": False,
        "actions_today": 31,
        "last_active": "2026-10-22T14:38:00Z"
    },
    "AGT-SAVINGS-12": {
        "id": "AGT-SAVINGS-12",
        "name": "Principle P12 Savings Validator",
        "module": "M11 Savings",
        "autonomy_level": "L2_PROPOSE_DRAFT",
        "description": "Bridges negotiated savings into realized cash-in-bank strictly from posted ERP invoice line items.",
        "status": "ACTIVE",
        "kill_switch_engaged": False,
        "actions_today": 7,
        "last_active": "2026-10-22T14:25:00Z"
    },
    "AGT-SOD-13": {
        "id": "AGT-SOD-13",
        "name": "SoD Command-Time Defender",
        "module": "M13 Governance",
        "autonomy_level": "L4_AUTONOMOUS_EXECUTE",
        "description": "Enforces action-level conflicts (SOD-01..07) at the moment of action across all humans and AI agents.",
        "status": "ACTIVE",
        "kill_switch_engaged": False,
        "actions_today": 142,
        "last_active": "2026-10-22T14:49:00Z"
    },
    "AGT-CAPA-14": {
        "id": "AGT-CAPA-14",
        "name": "Supplier Development & CAPA Sentinel",
        "module": "M06 SLM",
        "autonomy_level": "L2_PROPOSE_DRAFT",
        "description": "Detects recurring quality deviations, generates 8D containment plans, and schedules supplier training programs.",
        "status": "ACTIVE",
        "kill_switch_engaged": False,
        "actions_today": 11,
        "last_active": "2026-10-22T14:18:00Z"
    }
}

GLOBAL_EMERGENCY_STOP_STATUS = False

# -------------------------------------------------------------
# Request & Response Models
# -------------------------------------------------------------

class CopilotQueryRequest(BaseModel):
    query: str
    tenant_id: str = "axion-mobility"
    actor: str = "u:cpo.executive"
    plant: Optional[str] = "P100 Hosur"

class AnswerContractCitation(BaseModel):
    document_id: str
    doc_type: str
    url: str
    snippet: str

class AnswerContractNextAction(BaseModel):
    action_id: str
    title: str
    endpoint: str
    payload: Dict[str, Any]
    requires_approval: bool
    approver_role: str

class CopilotAnswerContractResponse(BaseModel):
    answer_summary: str
    citations: List[AnswerContractCitation]
    confidence_score: float
    assumptions_made: List[str]
    sod_check_result: Dict[str, Any]
    recommended_next_actions: List[AnswerContractNextAction]

# -------------------------------------------------------------
# Module M01: Spend Analytics & Spend Cube Endpoints
# -------------------------------------------------------------

@router.get("/cube")
def get_spend_cube_metrics(
    plant: Optional[str] = None,
    commodity: Optional[str] = None,
    supplier_id: Optional[str] = None
):
    """
    Multidimensional spend aggregation across 8 core dimensions.
    """
    records = SPEND_CUBE_RECORDS
    if plant and plant != "All":
        records = [r for r in records if r["plant"].lower() == plant.lower()]
    if commodity and commodity != "All":
        records = [r for r in records if r["commodity"].lower() == commodity.lower()]
    if supplier_id and supplier_id != "All":
        records = [r for r in records if r["supplier_id"].lower() == supplier_id.lower()]

    total_spend = sum(r["spend_inr"] for r in records)
    on_contract_spend = sum(r["spend_inr"] for r in records if r["is_on_contract"])
    maverick_spend = total_spend - on_contract_spend
    contract_compliance_pct = round((on_contract_spend / total_spend) * 100.0, 1) if total_spend > 0 else 100.0

    # Commodity breakdown
    comm_map = {}
    for r in records:
        c = r["commodity"]
        comm_map[c] = comm_map.get(c, 0.0) + r["spend_inr"]

    # Supplier breakdown
    supp_map = {}
    for r in records:
        s = r["supplier_name"]
        supp_map[s] = supp_map.get(s, 0.0) + r["spend_inr"]

    return {
        "status": "success",
        "total_spend_cr": round(total_spend / 10000000.0, 2),
        "on_contract_spend_cr": round(on_contract_spend / 10000000.0, 2),
        "maverick_spend_cr": round(maverick_spend / 10000000.0, 2),
        "contract_compliance_pct": contract_compliance_pct,
        "record_count": len(records),
        "commodity_breakdown": [
            {"commodity": k, "spend_cr": round(v / 10000000.0, 2)} for k, v in comm_map.items()
        ],
        "top_suppliers": [
            {"supplier_name": k, "spend_cr": round(v / 10000000.0, 2)} for k, v in supp_map.items()
        ]
    }

@router.get("/maverick")
def get_maverick_spend_details():
    """
    Identifies uncontracted rogue purchases violating Principle P03.
    """
    mavericks = [r for r in SPEND_CUBE_RECORDS if not r["is_on_contract"]]
    total_mav = sum(m["spend_inr"] for m in mavericks)

    return {
        "status": "success",
        "maverick_spend_cr": round(total_mav / 10000000.0, 2),
        "records": mavericks,
        "principle_p03_warning": "Detected ₹1.4 Cr off-contract purchases for die-cast parts with Salem Light Alloys when active Scheduling Agreement SA-5520 exists with Trichy Forge Works."
    }

@router.get("/tail")
def get_tail_spend_analysis():
    """
    80/20 Pareto distribution classifier.
    """
    return {
        "status": "success",
        "tail_threshold_pct": 20.0,
        "tail_spend_cr": 0.45,
        "tail_supplier_count": 84,
        "total_suppliers": 105,
        "insight": "80% of vendors represent only 2.1% of annual spend (tail friction). Catalog enablement recommended."
    }

# -------------------------------------------------------------
# Module M12: Governed AI Agent Runtime & Copilot Answer Contract
# -------------------------------------------------------------

@agents_router.get("/registry")
def list_ai_agents():
    return {
        "status": "success",
        "global_emergency_stop": GLOBAL_EMERGENCY_STOP_STATUS,
        "total_agents": len(AI_AGENTS_REGISTRY),
        "agents": list(AI_AGENTS_REGISTRY.values())
    }

@agents_router.post("/{agent_id}/toggle-kill-switch")
def toggle_agent_kill_switch(agent_id: str, actor: str = "u:security.admin"):
    agent = AI_AGENTS_REGISTRY.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent["kill_switch_engaged"] = not agent["kill_switch_engaged"]
    agent["status"] = "SUSPENDED" if agent["kill_switch_engaged"] else "ACTIVE"

    return {
        "status": "success",
        "agent_id": agent_id,
        "kill_switch_engaged": agent["kill_switch_engaged"],
        "agent_status": agent["status"],
        "message": f"Kill switch {'ENGAGED' if agent['kill_switch_engaged'] else 'RELEASED'} by {actor}."
    }

@agents_router.post("/global-emergency-stop")
def toggle_global_emergency_stop(actor: str = "u:cpo.executive"):
    global GLOBAL_EMERGENCY_STOP_STATUS
    GLOBAL_EMERGENCY_STOP_STATUS = not GLOBAL_EMERGENCY_STOP_STATUS
    status_label = "SUSPENDED_ALL" if GLOBAL_EMERGENCY_STOP_STATUS else "ACTIVE"

    for a in AI_AGENTS_REGISTRY.values():
        if GLOBAL_EMERGENCY_STOP_STATUS:
            a["status"] = "EMERGENCY_HALT"
        else:
            a["status"] = "ACTIVE" if not a["kill_switch_engaged"] else "SUSPENDED"

    return {
        "status": "success",
        "global_emergency_stop": GLOBAL_EMERGENCY_STOP_STATUS,
        "message": f"Global Emergency Stop {'ENGAGED' if GLOBAL_EMERGENCY_STOP_STATUS else 'DISENGAGED'} by {actor}. All 14 agents {status_label}."
    }

@agents_router.post("/copilot/query", response_model=CopilotAnswerContractResponse)
def execute_governed_copilot_query(payload: CopilotQueryRequest):
    """
    Executes Governed Procurement Copilot query strictly returning Principle P11 Answer Contract:
    1. answer_summary
    2. citations (with document_link grounded references)
    3. confidence_score
    4. assumptions_made
    5. sod_check_result
    6. recommended_next_actions
    """
    q_lower = payload.query.lower()

    # Query routing logic across golden scenario
    if "housing" in q_lower or "dc-330" in q_lower or "trichy" in q_lower or "savings" in q_lower or "po-77410" in q_lower:
        return CopilotAnswerContractResponse(
            answer_summary=(
                "For DC-330 Aluminium Die-Cast Housings at Plant P100 Hosur, demand of 12,000 units was netted "
                "down to 9,000 EA via MRP Run MR-1043. Sourcing Event RFQ-2231 established a 60/40 capacity-split award "
                "between Trichy Forge Works (₹398) and Kovai Diecast (₹405), delivering ₹0.99 Cr/yr negotiated savings. "
                "Touchless Release PO-77410 (Risk 18) was issued against Scheduling Agreement SA-5520. Goods receipt GR-90231 "
                "identified 20 rejected units under QL-2210; Invoice INV-TF-8812 was reconciled with Credit Note CN-TF-221, "
                "yielding exactly-once SAP S/4HANA posted Document 5100004421 with ₹0.38 Cr realised P&L savings."
            ),
            citations=[
                AnswerContractCitation(
                    document_id="MR-1043",
                    doc_type="MRP_RUN",
                    url="/mrp/planner-workbench",
                    snippet="Net Requirement = max(0, 12000 - 2500 - 700 + 200) = 9000 EA."
                ),
                AnswerContractCitation(
                    document_id="SA-5520",
                    doc_type="CONTRACT",
                    url="/contracts/agreements",
                    snippet="Scheduling Agreement with quarterly LME indexation clause and FCA Trichy terms @ ₹398.00."
                ),
                AnswerContractCitation(
                    document_id="PO-77410",
                    doc_type="PURCHASE_ORDER",
                    url="/p2p",
                    snippet="Auto-released touchless PO (Risk Score 18/100, 5,400 units, INR 2,149,200)."
                ),
                AnswerContractCitation(
                    document_id="INV-TF-8812",
                    doc_type="INVOICE",
                    url="/p2p",
                    snippet="3-way match reconciled via CN-TF-221. Posted to SAP Doc 5100004421."
                ),
                AnswerContractCitation(
                    document_id="SV-0412",
                    doc_type="SAVINGS_INITIATIVE",
                    url="/savings",
                    snippet="Realised P&L savings: ₹0.38 Cr validated by Finance Controller under SOD-07."
                )
            ],
            confidence_score=0.98,
            assumptions_made=[
                "Aluminium LME cash benchmark remains within +/- 3% deadband through Q3.",
                "Quality rejection defect porosity rate remains under 50 PPM for subsequent lots.",
                "SAP S/4HANA MM connector retains exact idempotency key on Doc 5100004421."
            ],
            sod_check_result={
                "rule_id": "SOD-05_07",
                "status": "COMPLIANT",
                "explanation": "Award decision approved by distinct finance approver; savings validated by Finance Controller separate from Category Manager."
            },
            recommended_next_actions=[
                AnswerContractNextAction(
                    action_id="ACT-EXPEDITE-ASN",
                    title="Track ASN-61208 Transit Telemetry",
                    endpoint="/api/v1/p2p/asn/ASN-61208",
                    payload={"asn_id": "ASN-61208"},
                    requires_approval=False,
                    approver_role="LOGISTICS_COORDINATOR"
                ),
                AnswerContractNextAction(
                    action_id="ACT-AUDIT-SAVINGS",
                    title="Audit FY26 Realised Savings Waterfall",
                    endpoint="/api/v1/strategic/savings/waterfall",
                    payload={},
                    requires_approval=True,
                    approver_role="FINANCE_CONTROLLER"
                )
            ]
        )

    # General / Default response
    return CopilotAnswerContractResponse(
        answer_summary=f"Analyzed AlphaHelion Purchasing Intelligence Cloud for query '{payload.query}'. All 14 autonomous agents operating normally under active RBAC policies.",
        citations=[
            AnswerContractCitation(
                document_id="SPEND-CUBE-FY26",
                doc_type="SPEND_CUBE",
                url="/spend/cube",
                snippet="Total spend under management: ₹412.0 Cr across Hosur P100 and Chennai P200."
            )
        ],
        confidence_score=0.91,
        assumptions_made=["Standard ERP synchronization latency < 2 seconds."],
        sod_check_result={
            "rule_id": "SOD-01..07",
            "status": "PASS",
            "explanation": "All command-time validations operational."
        },
        recommended_next_actions=[
            AnswerContractNextAction(
                action_id="VIEW_SPEND_CUBE",
                title="Explore Multidimensional Spend Cube",
                endpoint="/api/v1/spend/cube",
                payload={},
                requires_approval=False,
                approver_role="BUYER"
            )
        ]
    )
