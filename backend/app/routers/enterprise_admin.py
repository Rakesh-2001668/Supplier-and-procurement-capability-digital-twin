"""
AlphaHelion Purchasing Intelligence Cloud — Enterprise Administration, SoD Matrix & RBAC Router
Covers Module M13: Enterprise Administration (ADM-01..04):
- ADM-01: Visual Segregation of Duties (SoD) Conflict Matrix & Real-time Violation Auditing
- ADM-02: Tenant & Plant Configuration and DMN Parameter Tuning Engine
- ADM-03: Transactional Outbox & Idempotency Monitor for ERP Posting
- ADM-04: Lineage Graph Visualizer & Audit Ledger Engine
"""

from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid

from app.services.sod_service import sod_engine, action_history_store
from app.services.outbox_service import outbox_service
from app.services.lineage_service import lineage_engine

router = APIRouter(prefix="/api/v1/admin/governance", tags=["Enterprise Administration & SoD Matrix"])

# -------------------------------------------------------------
# Module M13: In-Memory Governance Data Store
# -------------------------------------------------------------

SOD_RULES_METADATA = [
    {
        "id": "SOD-01",
        "title": "Create Supplier Master vs Create PO for Same Supplier",
        "risk": "High",
        "description": "An actor who creates or certifies a supplier master record cannot generate purchase orders for that supplier without independent verification.",
        "mitigation": "Vendor management officer cannot hold PO release roles.",
        "enforcement_point": "Command time PO Creation",
        "status": "ENFORCED"
    },
    {
        "id": "SOD-02",
        "title": "Change Supplier Bank Details vs Post Invoice / Approve Payment",
        "risk": "Critical",
        "description": "Modifications to supplier bank account numbers (IFSC/SWIFT) require dual approval from distinct finance authorities and invoke a 14-day invoice posting lockout for the changers.",
        "mitigation": "Dual distinct Finance Controller approval required; cooling-off period active.",
        "enforcement_point": "Command time Invoice Post & Payment Approval",
        "status": "ENFORCED"
    },
    {
        "id": "SOD-03",
        "title": "Create PO vs Post Goods Receipt / Approve SES for Same PO",
        "risk": "High",
        "description": "The buyer who created the Purchase Order cannot acknowledge receipt of goods or sign off on Service Entry Sheets (SES).",
        "mitigation": "Physical warehouse receiving clerk or separate service verifier required.",
        "enforcement_point": "Command time Goods Receipt & SES Post",
        "status": "ENFORCED"
    },
    {
        "id": "SOD-04",
        "title": "Create PO vs Approve Invoice Price/Quantity Exception for Same PO",
        "risk": "High",
        "description": "The PO creator cannot authorize invoice matching exceptions (such as quantity discrepancies or unapproved price variances).",
        "mitigation": "Independent AP supervisor or Cost-Object Owner approval required.",
        "enforcement_point": "Command time Exception Resolution",
        "status": "ENFORCED"
    },
    {
        "id": "SOD-05",
        "title": "Award Sourcing Event vs Score as Sole Evaluator",
        "risk": "Medium",
        "description": "An award decision cannot be authorized by an individual who was the single evaluator of supplier commercial bids.",
        "mitigation": "Multi-stakeholder evaluation team or distinct Finance Approver sign-off required.",
        "enforcement_point": "Command time Sourcing Award",
        "status": "ENFORCED"
    },
    {
        "id": "SOD-06",
        "title": "Request Material Master vs Approve Material as Domain Steward",
        "risk": "Medium",
        "description": "A requisitioner or plant engineer requesting a standard material creation cannot approve their own catalog record.",
        "mitigation": "Independent Domain Steward (Metals/Chemicals/Tooling) review required.",
        "enforcement_point": "Command time Material Request Approval",
        "status": "ENFORCED"
    },
    {
        "id": "SOD-07",
        "title": "Initiate Savings Project vs Validate Savings as Finance Controller",
        "risk": "High",
        "description": "A Category Manager who initiates a strategic savings project cannot self-validate the realized P&L impact into enterprise budgets.",
        "mitigation": "Independent Finance Controller sign-off verified against general ledger posted invoices.",
        "enforcement_point": "Command time Savings Realisation Sign-Off",
        "status": "ENFORCED"
    }
]

# Track historical SoD blocks for audit
SOD_BLOCKED_LOGS: List[Dict[str, Any]] = [
    {
        "id": "LOG-SOD-001",
        "rule_id": "SOD-03",
        "actor": "u:buyer.hosur",
        "attempted_action": "POST_GR",
        "target_object_id": "PO-77410",
        "risk": "High",
        "reason": "Actor 'u:buyer.hosur' created PO-77410 and attempted to post Goods Receipt.",
        "timestamp": "2026-10-21T11:42:00Z",
        "decision": "BLOCKED"
    },
    {
        "id": "LOG-SOD-002",
        "rule_id": "SOD-07",
        "actor": "u:category.mgr.castings",
        "attempted_action": "VALIDATE_SAVINGS",
        "target_object_id": "SV-0412",
        "risk": "High",
        "reason": "Actor 'u:category.mgr.castings' initiated SV-0412 and attempted self-validation.",
        "timestamp": "2026-10-21T14:10:00Z",
        "decision": "BLOCKED"
    },
    {
        "id": "LOG-SOD-003",
        "rule_id": "SOD-02",
        "actor": "u:finance.steward.p100",
        "attempted_action": "SECOND_BANK_APPROVAL",
        "target_object_id": "BCR-8810",
        "risk": "Critical",
        "reason": "Single-user dual approval attempted for Trichy Forge Works bank modification.",
        "timestamp": "2026-10-21T15:02:00Z",
        "decision": "BLOCKED"
    }
]

DMN_CONFIG = {
    "touchless_po_max_risk_score": 20,
    "touchless_po_max_value_inr": 5000000.0,
    "metal_indexation_deadband_pct": 3.0,
    "invoice_qty_tolerance_pct": 0.0,
    "invoice_price_tolerance_pct": 1.0,
    "mdm_duplicate_similarity_block_pct": 92.0,
    "requisition_auto_approval_limit_inr": 500000.0,
    "active_plants": [
        {"code": "P100", "name": "Hosur Powertrain & Motors", "status": "ACTIVE"},
        {"code": "P200", "name": "Chennai Chassis & Body", "status": "ACTIVE"}
    ],
    "last_updated": "2026-10-22T14:00:00Z",
    "updated_by": "u:platform.admin"
}

# Pre-seed signature ERP post message for SAP S/4HANA (Doc 5100004421) if empty
if not outbox_service.messages:
    outbox_service.post_to_erp(
        tenant_id="axion-mobility",
        idempotency_key="POST_INVOICE_INV-TF-8812",
        target_system="SAP_S4HANA_MM",
        object_ref="INV-TF-8812",
        payload={"invoice_id": "INV-TF-8812", "amount": 2141240.0}
    )

# -------------------------------------------------------------
# Request & Response Models
# -------------------------------------------------------------

class DmnConfigUpdateRequest(BaseModel):
    touchless_po_max_risk_score: Optional[int] = None
    touchless_po_max_value_inr: Optional[float] = None
    metal_indexation_deadband_pct: Optional[float] = None
    invoice_qty_tolerance_pct: Optional[float] = None
    invoice_price_tolerance_pct: Optional[float] = None
    mdm_duplicate_similarity_block_pct: Optional[float] = None
    actor: str = "u:platform.admin"

# -------------------------------------------------------------
# ADM-01: SoD Conflict Matrix & Audit Logs
# -------------------------------------------------------------

@router.get("/sod-matrix")
def get_sod_matrix():
    return {
        "status": "success",
        "total_rules": len(SOD_RULES_METADATA),
        "rules": SOD_RULES_METADATA,
        "enforcement_mode": "STRICT_COMMAND_TIME"
    }

@router.get("/sod-violations")
def list_sod_violations():
    return {
        "status": "success",
        "total_violations_blocked": len(SOD_BLOCKED_LOGS),
        "violations": SOD_BLOCKED_LOGS
    }

# -------------------------------------------------------------
# ADM-02: DMN Rule Parameter Editor & Plant Config
# -------------------------------------------------------------

@router.get("/config/dmn-rules")
def get_dmn_rules_configuration():
    return {
        "status": "success",
        "config": DMN_CONFIG
    }

@router.put("/config/dmn-rules")
def update_dmn_rules_configuration(payload: DmnConfigUpdateRequest):
    if payload.touchless_po_max_risk_score is not None:
        DMN_CONFIG["touchless_po_max_risk_score"] = payload.touchless_po_max_risk_score
    if payload.touchless_po_max_value_inr is not None:
        DMN_CONFIG["touchless_po_max_value_inr"] = payload.touchless_po_max_value_inr
    if payload.metal_indexation_deadband_pct is not None:
        DMN_CONFIG["metal_indexation_deadband_pct"] = payload.metal_indexation_deadband_pct
    if payload.invoice_qty_tolerance_pct is not None:
        DMN_CONFIG["invoice_qty_tolerance_pct"] = payload.invoice_qty_tolerance_pct
    if payload.invoice_price_tolerance_pct is not None:
        DMN_CONFIG["invoice_price_tolerance_pct"] = payload.invoice_price_tolerance_pct
    if payload.mdm_duplicate_similarity_block_pct is not None:
        DMN_CONFIG["mdm_duplicate_similarity_block_pct"] = payload.mdm_duplicate_similarity_block_pct

    DMN_CONFIG["last_updated"] = datetime.utcnow().isoformat() + "Z"
    DMN_CONFIG["updated_by"] = payload.actor

    return {
        "status": "success",
        "message": "DMN business rule parameters calibrated successfully.",
        "config": DMN_CONFIG
    }

# -------------------------------------------------------------
# ADM-03: Transactional Outbox & Idempotency Monitor
# -------------------------------------------------------------

@router.get("/outbox")
def get_outbox_telemetry():
    messages = outbox_service.list_recent_messages()
    return {
        "status": "success",
        "total_messages": len(messages),
        "connector_target": "SAP S/4HANA (BAPI_INCOMINGINVOICE_CREATE / MM_PO_CREATE)",
        "messages": messages
    }

@router.post("/outbox/{msg_id}/retry")
def retry_outbox_message(msg_id: str):
    messages = outbox_service.list_recent_messages()
    target_msg = next((m for m in messages if m["msg_id"] == msg_id), None)
    if not target_msg:
        raise HTTPException(status_code=404, detail="Outbox message not found")

    target_msg["retries"] += 1
    target_msg["updated_at"] = datetime.utcnow().isoformat() + "Z"

    return {
        "status": "success",
        "message": f"Message {msg_id} re-enqueued for ERP dispatch.",
        "outbox_record": target_msg
    }

# -------------------------------------------------------------
# ADM-04: Bi-directional Lineage Explorer
# -------------------------------------------------------------

@router.get("/lineage/{doc_id}")
def inspect_document_lineage(doc_id: str):
    """
    Traverses the full demand-to-settlement lineage graph from any starting document node (Principle P10).
    """
    history = lineage_engine.get_lineage_for_document(doc_id)
    return {
        "status": "success",
        "query_doc_id": doc_id,
        "lineage_depth": len(history.get("nodes", [])),
        "lineage_graph": history
    }
