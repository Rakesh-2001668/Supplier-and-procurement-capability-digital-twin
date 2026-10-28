"""
AlphaHelion Purchasing Intelligence Cloud
Module: Unified Multi-Tier Approval Inbox & Segregation of Duties (SoD) Sentinel
Blueprint Reference: Section 24 (Multi-Tier Approval Matrix, pages 62-68) & Table 4 (SoD Rules SOD-01..07)
Technical Doc Reference: Section 8 (DMN Decision Tables) & Section 16 (Front-end Workspaces)

Features:
- DMN-01 Multi-Tier Routing:
  * Tier 1 (< ₹1,00,000): Cost Center / Project Lead (SLA: 24h)
  * Tier 2 (₹1,00,000 - ₹10,00,000): Department Head / Category Lead (SLA: 48h)
  * Tier 3 (₹10,00,000 - ₹50,00,000): Chief Procurement Officer / Sourcing Director (SLA: 48h)
  * Tier 4 (> ₹50,00,000): VP / CFO / Sourcing Board (SLA: 72h)
- Command-Time SoD Conflict Checking (SOD-01 through SOD-07)
- Bulk Approval Processing
- Out-of-Office Delegation Registry
- SoD Matrix & Live Violation Sentinel
"""

from fastapi import APIRouter, HTTPException, Query, Header, Body
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import uuid

from app.services.sod_service import sod_engine, action_history_store, sod_violations_log, SodViolation

router = APIRouter(prefix="/api/v1/approvals", tags=["Unified Approvals & SoD Sentinel"])

# ==============================================================================
# PYDANTIC DATA MODELS
# ==============================================================================

class ApprovalActionRequest(BaseModel):
    action: str = Field(..., description="APPROVE, REJECT, RETURN, DELEGATE")
    actor: str = Field(..., description="User email or identity executing action")
    rationale: Optional[str] = Field(None, description="Mandatory for REJECT (min 15 chars), optional for others")
    delegate_to: Optional[str] = Field(None, description="Required when action is DELEGATE")

class BulkApprovalRequest(BaseModel):
    approval_ids: List[str]
    actor: str
    rationale: Optional[str] = "Bulk authorized via Unified Approval Inbox"

class DelegationRuleRequest(BaseModel):
    delegator: str
    delegatee: str
    scope: str = "ALL_DOCUMENTS" # ALL_DOCUMENTS, RFQ_ONLY, REQ_ONLY
    valid_from: str
    valid_until: str
    reason: str

# ==============================================================================
# IN-MEMORY APPROVAL INBOX STORE WITH REAL MULTI-TIER DATA
# ==============================================================================

APPROVAL_ITEMS: Dict[str, Dict[str, Any]] = {
    "APP-RFQ-701": {
        "id": "APP-RFQ-701",
        "document_type": "RFQ_SOURCING_AWARD",
        "document_ref": "RFQ-701",
        "title": "Sourcing Wave #701: Precision Die-Casting & CNC Machining",
        "category": "Direct Materials / Powertrain",
        "currency": "INR",
        "total_amount": 7250000.0,
        "amount_display": "₹72,50,000",
        "tier": "Tier 4 (>₹50L)",
        "tier_level": 4,
        "sla_hours": 72,
        "submitted_at": "2026-10-23T10:00:00Z",
        "expires_at": "2026-10-26T10:00:00Z",
        "creator": "amit.verma@alphahelion.com",
        "creator_role": "Category Manager",
        "current_approvers": ["cpo@alphahelion.com", "cfo@alphahelion.com"],
        "status": "PENDING", # PENDING, APPROVED, REJECTED, RETURNED, DELEGATED
        "sod_rule": "SOD-05",
        "sod_risk": "High",
        "sod_description": "RFQ creator (amit.verma) cannot self-approve sourcing awards >= ₹50L or split awards without independent Board sign-off.",
        "commercial_summary": {
            "awarded_supplier": "Trichy Forge (70%) + Kovai Diecast (30%)",
            "benchmark_should_cost": "₹415/unit",
            "awarded_unit_rate": "₹398/unit (TF) / ₹405/unit (Kovai)",
            "annual_savings": "₹8,45,000 (10.4% negotiated saving)",
            "non_lowest_justification": "Kovai Diecast awarded 30% volume despite +₹7/unit delta to mitigate single-source risk and secure 48h emergency replenishment SLA."
        },
        "approval_chain": [
            {"tier": "Tier 1", "role": "Category Lead", "assignee": "vikram.mehta@alphahelion.com", "status": "APPROVED", "timestamp": "2026-10-23T12:00:00Z"},
            {"tier": "Tier 2", "role": "Head of Sourcing", "assignee": "priya.sharma@alphahelion.com", "status": "APPROVED", "timestamp": "2026-10-23T16:30:00Z"},
            {"tier": "Tier 3", "role": "Chief Procurement Officer", "assignee": "cpo@alphahelion.com", "status": "PENDING", "timestamp": None},
            {"tier": "Tier 4", "role": "Chief Financial Officer", "assignee": "cfo@alphahelion.com", "status": "PENDING", "timestamp": None}
        ]
    },
    "APP-RFQ-704": {
        "id": "APP-RFQ-704",
        "document_type": "RFQ_SOURCING_AWARD",
        "document_ref": "RFQ-704",
        "title": "RFQ #704: High-Tensile Structural Fasteners (M12/M16)",
        "category": "Direct Materials / Hardware",
        "currency": "INR",
        "total_amount": 840000.0,
        "amount_display": "₹8,40,000",
        "tier": "Tier 2 (₹1L-₹10L)",
        "tier_level": 2,
        "sla_hours": 48,
        "submitted_at": "2026-10-24T06:00:00Z",
        "expires_at": "2026-10-26T06:00:00Z",
        "creator": "vikram.mehta@alphahelion.com",
        "creator_role": "Buyer",
        "current_approvers": ["category.lead@alphahelion.com"],
        "status": "PENDING",
        "sod_rule": "SOD-05",
        "sod_risk": "Medium",
        "sod_description": "Buyer cannot authorize award without independent Category Lead sign-off.",
        "commercial_summary": {
            "awarded_supplier": "Salem Fasteners Ltd",
            "benchmark_should_cost": "₹48/unit",
            "awarded_unit_rate": "₹44/unit",
            "annual_savings": "₹96,000 (8.3% saving)",
            "non_lowest_justification": "Lowest compliant bidder with IATF-16949 certification."
        },
        "approval_chain": [
            {"tier": "Tier 1", "role": "Project Manager", "assignee": "project.mgr@alphahelion.com", "status": "APPROVED", "timestamp": "2026-10-24T08:15:00Z"},
            {"tier": "Tier 2", "role": "Category Lead", "assignee": "category.lead@alphahelion.com", "status": "PENDING", "timestamp": None}
        ]
    },
    "APP-REQ-2311": {
        "id": "APP-REQ-2311",
        "document_type": "PURCHASE_REQUISITION",
        "document_ref": "REQ-2311",
        "title": "PR #2311: Replacement Tungsten Carbide Milling Inserts",
        "category": "MRO & Tooling",
        "currency": "INR",
        "total_amount": 485000.0,
        "amount_display": "₹4,85,000",
        "tier": "Tier 2 (₹1L-₹10L)",
        "tier_level": 2,
        "sla_hours": 48,
        "submitted_at": "2026-10-24T07:15:00Z",
        "expires_at": "2026-10-26T07:15:00Z",
        "creator": "priya.sharma@alphahelion.com",
        "creator_role": "Tooling Engineer",
        "current_approvers": ["dept.head.machining@alphahelion.com"],
        "status": "PENDING",
        "sod_rule": "SOD-01",
        "sod_risk": "High",
        "sod_description": "Requester (priya.sharma) cannot approve own PR under DMN-01 / P09.",
        "commercial_summary": {
            "awarded_supplier": "Sandvik Coromant India",
            "benchmark_should_cost": "₹4,950/box",
            "awarded_unit_rate": "₹4,850/box (Contract CTR-2024-88)",
            "annual_savings": "Pre-negotiated framework contract rate",
            "non_lowest_justification": "Standard catalogue purchase with budget encumbrance confirmed."
        },
        "approval_chain": [
            {"tier": "Tier 1", "role": "Shopfloor Supervisor", "assignee": "supervisor.shop4@alphahelion.com", "status": "APPROVED", "timestamp": "2026-10-24T08:00:00Z"},
            {"tier": "Tier 2", "role": "Department Head", "assignee": "dept.head.machining@alphahelion.com", "status": "PENDING", "timestamp": None}
        ]
    },
    "APP-REQ-1043": {
        "id": "APP-REQ-1043",
        "document_type": "PURCHASE_REQUISITION",
        "document_ref": "REQ-1043",
        "title": "PR #1043: Direct Materials Titanium Billets (MRP Netting)",
        "category": "Direct Materials / Raw Stock",
        "currency": "INR",
        "total_amount": 3420000.0,
        "amount_display": "₹34,20,000",
        "tier": "Tier 3 (₹10L-₹50L)",
        "tier_level": 3,
        "sla_hours": 48,
        "submitted_at": "2026-10-24T05:00:00Z",
        "expires_at": "2026-10-26T05:00:00Z",
        "creator": "mrp.controller@alphahelion.com",
        "creator_role": "MRP Controller",
        "current_approvers": ["cpo@alphahelion.com"],
        "status": "PENDING",
        "sod_rule": "SOD-01",
        "sod_risk": "High",
        "sod_description": "MRP Controller conversion to PR requires CPO authorization for Tier 3 value.",
        "commercial_summary": {
            "awarded_supplier": "Midhani Superalloys Ltd",
            "benchmark_should_cost": "₹35,00,000",
            "awarded_unit_rate": "₹34,20,000 total",
            "annual_savings": "₹80,000 spot market index discount",
            "non_lowest_justification": "Critical flight-safety grade material with lot traceability."
        },
        "approval_chain": [
            {"tier": "Tier 1", "role": "Plant Planner", "assignee": "plant.planner@alphahelion.com", "status": "APPROVED", "timestamp": "2026-10-24T05:30:00Z"},
            {"tier": "Tier 2", "role": "Plant Operations Head", "assignee": "ops.head@alphahelion.com", "status": "APPROVED", "timestamp": "2026-10-24T06:45:00Z"},
            {"tier": "Tier 3", "role": "Chief Procurement Officer", "assignee": "cpo@alphahelion.com", "status": "PENDING", "timestamp": None}
        ]
    },
    "APP-PO-77410": {
        "id": "APP-PO-77410",
        "document_type": "PURCHASE_ORDER",
        "document_ref": "PO-77410",
        "title": "PO #77410: Precision CNC Flange Casings (Release Sign-off)",
        "category": "Direct Materials / Machined Components",
        "currency": "INR",
        "total_amount": 1890000.0,
        "amount_display": "₹18,90,000",
        "tier": "Tier 3 (₹10L-₹50L)",
        "tier_level": 3,
        "sla_hours": 48,
        "submitted_at": "2026-10-24T08:00:00Z",
        "expires_at": "2026-10-26T08:00:00Z",
        "creator": "buyer.automotive@alphahelion.com",
        "creator_role": "Buyer",
        "current_approvers": ["procurement.head@alphahelion.com"],
        "status": "PENDING",
        "sod_rule": "SOD-03",
        "sod_risk": "High",
        "sod_description": "Buyer creating PO cannot acknowledge receipt or approve exceptions.",
        "commercial_summary": {
            "awarded_supplier": "Trichy Forge (TF001)",
            "benchmark_should_cost": "₹19,20,000",
            "awarded_unit_rate": "₹18,90,000 (PO line 1-4)",
            "annual_savings": "Derived from Sourcing Wave #701 Award",
            "non_lowest_justification": "Direct contract call-off under MSA #991."
        },
        "approval_chain": [
            {"tier": "Tier 1", "role": "Buyer Sourcing", "assignee": "buyer.automotive@alphahelion.com", "status": "APPROVED", "timestamp": "2026-10-24T08:00:00Z"},
            {"tier": "Tier 2", "role": "Category Lead", "assignee": "category.lead@alphahelion.com", "status": "APPROVED", "timestamp": "2026-10-24T08:30:00Z"},
            {"tier": "Tier 3", "role": "Procurement Head", "assignee": "procurement.head@alphahelion.com", "status": "PENDING", "timestamp": None}
        ]
    },
    "APP-BNK-108": {
        "id": "APP-BNK-108",
        "document_type": "SUPPLIER_BANK_CHANGE",
        "document_ref": "SUP-TF001",
        "title": "Vendor Bank Account Modification: Trichy Forge (TF001)",
        "category": "Vendor Master / Banking",
        "currency": "INR",
        "total_amount": 0.0,
        "amount_display": "Critical Banking Risk",
        "tier": "Dual Finance Sign-off (SOD-02)",
        "tier_level": 3,
        "sla_hours": 24,
        "submitted_at": "2026-10-24T04:00:00Z",
        "expires_at": "2026-10-25T04:00:00Z",
        "creator": "vendor.ops@alphahelion.com",
        "creator_role": "Supplier Admin",
        "current_approvers": ["controller2@alphahelion.com"],
        "status": "PENDING",
        "sod_rule": "SOD-02",
        "sod_risk": "Critical",
        "sod_description": "Modifications to supplier IFSC/Account # require dual distinct Finance sign-offs with 14-day cooling period.",
        "commercial_summary": {
            "awarded_supplier": "Trichy Forge (TF001)",
            "benchmark_should_cost": "N/A",
            "awarded_unit_rate": "New HDFC Bank A/C #50200088123441",
            "annual_savings": "Penny-Drop & Name-Match Verified (98.4%)",
            "non_lowest_justification": "Primary signatory Controller 1 verified cancelled cheque via callback."
        },
        "approval_chain": [
            {"tier": "Finance Signatory 1", "role": "Finance Controller", "assignee": "controller1@alphahelion.com", "status": "APPROVED", "timestamp": "2026-10-24T06:00:00Z"},
            {"tier": "Finance Signatory 2", "role": "Senior Treasury Manager", "assignee": "controller2@alphahelion.com", "status": "PENDING", "timestamp": None}
        ]
    }
}

# Seed action history store so SoD rules immediately detect creators
for app_id, app in APPROVAL_ITEMS.items():
    if app["document_type"] == "RFQ_SOURCING_AWARD":
        action_history_store.record_action("SOURCING_EVENT", app["document_ref"], "CREATE_SOURCING_EVENT", app["creator"])
    elif app["document_type"] == "PURCHASE_REQUISITION":
        action_history_store.record_action("PURCHASE_REQUISITION", app["document_ref"], "CREATE_PR", app["creator"])
    elif app["document_type"] == "PURCHASE_ORDER":
        action_history_store.record_action("PURCHASE_ORDER", app["document_ref"], "CREATE_PO", app["creator"])
    elif app["document_type"] == "SUPPLIER_BANK_CHANGE":
        action_history_store.record_action("SUPPLIER", app["document_ref"], "CHANGE_BANK_DETAILS", app["creator"])

# Delegations Store
DELEGATIONS_STORE: List[Dict[str, Any]] = [
    {
        "id": "DEL-101",
        "delegator": "cpo@alphahelion.com",
        "delegatee": "deputy.cpo@alphahelion.com",
        "scope": "ALL_DOCUMENTS",
        "valid_from": "2026-10-20T00:00:00Z",
        "valid_until": "2026-10-28T23:59:59Z",
        "reason": "Executive Sourcing Summit Attendance (Europe)",
        "active": True
    }
]

# ==============================================================================
# REST API ENDPOINTS
# ==============================================================================

@router.get("/inbox")
async def get_approval_inbox(
    document_type: Optional[str] = Query(None, description="RFQ_SOURCING_AWARD, PURCHASE_REQUISITION, etc."),
    tier: Optional[str] = Query(None, description="Tier 1, Tier 2, Tier 3, Tier 4"),
    status: Optional[str] = Query(None, description="PENDING, APPROVED, REJECTED"),
    actor: Optional[str] = Query(None, description="Filter for current actor pending sign-off")
):
    """
    Unified Multi-Tier Approval Inbox query endpoint.
    Filters by document type, value tier, approval status, and candidate actor.
    """
    items = list(APPROVAL_ITEMS.values())
    
    if document_type and document_type != "ALL":
        items = [i for i in items if i["document_type"] == document_type]
    
    if tier and tier != "ALL":
        items = [i for i in items if tier.lower() in i["tier"].lower()]
        
    if status and status != "ALL":
        items = [i for i in items if i["status"] == status]
        
    if actor:
        items = [i for i in items if actor.lower() in [a.lower() for a in i["current_approvers"]]]
        
    # Calculate summary metrics
    total_pending = sum(1 for i in APPROVAL_ITEMS.values() if i["status"] == "PENDING")
    total_rfq_pending = sum(1 for i in APPROVAL_ITEMS.values() if i["status"] == "PENDING" and i["document_type"] == "RFQ_SOURCING_AWARD")
    total_value_pending = sum(i["total_amount"] for i in APPROVAL_ITEMS.values() if i["status"] == "PENDING")
    
    return {
        "status": "success",
        "metrics": {
            "total_pending_count": total_pending,
            "total_rfq_pending_count": total_rfq_pending,
            "total_pending_value_inr": total_value_pending,
            "active_delegations_count": len([d for d in DELEGATIONS_STORE if d["active"]]),
            "sod_violations_prevented_today": len(sod_violations_log)
        },
        "count": len(items),
        "items": items
    }

@router.get("/inbox/{approval_id}")
async def get_approval_detail(approval_id: str, actor: Optional[str] = None):
    """
    Retrieve single approval document with commercial details, SoD pre-check, and multi-tier chain.
    """
    key = approval_id.upper()
    if key not in APPROVAL_ITEMS:
        raise HTTPException(status_code=404, detail=f"Approval document '{approval_id}' not found.")
    
    item = APPROVAL_ITEMS[key]
    
    # Pre-evaluate SoD check if actor is provided
    sod_precheck = {"can_approve": True, "conflict_reason": None}
    if actor:
        try:
            target_action = "APPROVE_SOURCING_AWARD" if item["document_type"] == "RFQ_SOURCING_AWARD" else "APPROVE_PR"
            target_type = "SOURCING_EVENT" if item["document_type"] == "RFQ_SOURCING_AWARD" else "PURCHASE_REQUISITION"
            sod_engine.check_action(actor, target_action, target_type, item["document_ref"])
        except SodViolation as e:
            sod_precheck = {"can_approve": False, "conflict_reason": e.message, "rule_id": e.rule_id, "risk": e.risk}
            
    return {
        "status": "success",
        "item": item,
        "sod_precheck": sod_precheck
    }

@router.post("/inbox/{approval_id}/action")
async def execute_approval_action(approval_id: str, req: ApprovalActionRequest):
    """
    Execute approval action (APPROVE, REJECT, RETURN, DELEGATE).
    Performs command-time Segregation of Duties (SoD) enforcement.
    Blocks violators with HTTP 403 Forbidden and logs the violation.
    """
    key = approval_id.upper()
    if key not in APPROVAL_ITEMS:
        raise HTTPException(status_code=404, detail=f"Approval document '{approval_id}' not found.")
    
    item = APPROVAL_ITEMS[key]
    
    # 1. SoD Command-Time Check if action is APPROVE
    if req.action == "APPROVE":
        target_action = "APPROVE_SOURCING_AWARD" if item["document_type"] == "RFQ_SOURCING_AWARD" else "APPROVE_PR"
        target_type = "SOURCING_EVENT" if item["document_type"] == "RFQ_SOURCING_AWARD" else "PURCHASE_REQUISITION"
        
        try:
            sod_engine.check_action(
                actor=req.actor,
                target_action=target_action,
                target_object_type=target_type,
                target_object_id=item["document_ref"],
                context={"pr_id": item["document_ref"], "rfq_id": item["document_ref"]}
            )
        except SodViolation as e:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "SEGREGATION_OF_DUTIES_VIOLATION",
                    "rule_id": e.rule_id,
                    "risk": e.risk,
                    "message": e.message,
                    "principle": "P09: Approvals and Segregation of Duties",
                    "actor": req.actor,
                    "conflicting_action": e.conflicting_action
                }
            )

        # Mark current chain step as approved
        for step in item["approval_chain"]:
            if step["status"] == "PENDING":
                step["status"] = "APPROVED"
                step["timestamp"] = datetime.now(timezone.utc).isoformat()
                step["assignee"] = req.actor
                break
                
        # Check if all steps in chain are approved
        all_approved = all(s["status"] == "APPROVED" for s in item["approval_chain"])
        if all_approved:
            item["status"] = "APPROVED"
        
        return {
            "status": "success",
            "message": f"Successfully approved {item['document_ref']} by '{req.actor}'.",
            "approval_status": item["status"],
            "sod_checked": True
        }

    elif req.action == "REJECT":
        if not req.rationale or len(req.rationale.strip()) < 15:
            raise HTTPException(status_code=400, detail="Rejection requires a mandatory written rationale of at least 15 characters.")
        
        item["status"] = "REJECTED"
        for step in item["approval_chain"]:
            if step["status"] == "PENDING":
                step["status"] = "REJECTED"
                step["timestamp"] = datetime.now(timezone.utc).isoformat()
                step["notes"] = req.rationale
                break
                
        return {
            "status": "success",
            "message": f"Document {item['document_ref']} rejected with recorded rationale.",
            "approval_status": "REJECTED"
        }

    elif req.action == "RETURN":
        item["status"] = "RETURNED"
        return {
            "status": "success",
            "message": f"Document {item['document_ref']} returned to creator for clarification/revision.",
            "approval_status": "RETURNED"
        }

    elif req.action == "DELEGATE":
        if not req.delegate_to:
            raise HTTPException(status_code=400, detail="Delegation requires a target delegatee email.")
            
        item["current_approvers"] = [req.delegate_to]
        item["status"] = "DELEGATED"
        return {
            "status": "success",
            "message": f"Document {item['document_ref']} delegated to '{req.delegate_to}'.",
            "approval_status": "DELEGATED"
        }

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported action '{req.action}'.")

@router.post("/inbox/bulk-action")
async def bulk_approve_items(req: BulkApprovalRequest):
    """
    Bulk approves compliant documents.
    Evaluates SoD individually; skips or rejects any item violating SoD rules.
    """
    success_ids = []
    failed_items = []
    
    for app_id in req.approval_ids:
        key = app_id.upper()
        if key not in APPROVAL_ITEMS:
            failed_items.append({"id": app_id, "reason": "Not found"})
            continue
            
        item = APPROVAL_ITEMS[key]
        target_action = "APPROVE_SOURCING_AWARD" if item["document_type"] == "RFQ_SOURCING_AWARD" else "APPROVE_PR"
        target_type = "SOURCING_EVENT" if item["document_type"] == "RFQ_SOURCING_AWARD" else "PURCHASE_REQUISITION"
        
        try:
            sod_engine.check_action(
                actor=req.actor,
                target_action=target_action,
                target_object_type=target_type,
                target_object_id=item["document_ref"]
            )
            item["status"] = "APPROVED"
            success_ids.append(app_id)
        except SodViolation as e:
            failed_items.append({
                "id": app_id,
                "reason": f"SoD Conflict ({e.rule_id}): {e.message}"
            })
            
    return {
        "status": "success",
        "approved_count": len(success_ids),
        "approved_ids": success_ids,
        "blocked_count": len(failed_items),
        "blocked_items": failed_items
    }

@router.get("/sod/matrix")
async def get_sod_conflict_matrix():
    """
    Returns full 7-rule SoD matrix catalog, role conflict grid, and governance configuration.
    """
    from app.routers.enterprise_admin import SOD_RULES_METADATA
    
    # Conflict grid between key procurement roles
    roles = [
        "Requisition Creator",
        "Category Manager / Sourcing Lead",
        "Cost Center Approver",
        "PO Buyer",
        "Receiving Clerk / SES Verifier",
        "Supplier Master Steward",
        "AP Invoice Matcher",
        "Finance Treasury / Payment Signatory"
    ]
    
    role_conflict_grid = [
        {"role_a": "Requisition Creator", "role_b": "Cost Center Approver", "rule": "SOD-01", "conflict": True, "description": "Self-approval prohibited"},
        {"role_a": "Supplier Master Steward", "role_b": "PO Buyer", "rule": "SOD-01", "conflict": True, "description": "Cannot buy from self-created vendor"},
        {"role_a": "Supplier Master Steward", "role_b": "Finance Treasury / Payment Signatory", "rule": "SOD-02", "conflict": True, "description": "Bank modification lockout"},
        {"role_a": "PO Buyer", "role_b": "Receiving Clerk / SES Verifier", "rule": "SOD-03", "conflict": True, "description": "Cannot verify own receipts"},
        {"role_a": "PO Buyer", "role_b": "AP Invoice Matcher", "rule": "SOD-04", "conflict": True, "description": "Cannot resolve own PO price exceptions"},
        {"role_a": "Category Manager / Sourcing Lead", "role_b": "Cost Center Approver", "rule": "SOD-05", "conflict": True, "description": "Sole evaluator cannot authorize award >= ₹50L"},
        {"role_a": "AP Invoice Matcher", "role_b": "Finance Treasury / Payment Signatory", "rule": "SOD-07", "conflict": True, "description": "Matcher cannot trigger payment run"}
    ]
    
    return {
        "status": "success",
        "rules": SOD_RULES_METADATA,
        "roles": roles,
        "conflict_grid": role_conflict_grid,
        "enforcement_mode": "HARD_BLOCK",
        "total_rules": len(SOD_RULES_METADATA)
    }

@router.get("/sod/violations")
async def get_sod_violations_log():
    """
    Returns live ledger of blocked SoD violation attempts.
    """
    return {
        "status": "success",
        "total_violations": len(sod_violations_log),
        "violations": sod_violations_log
    }

@router.get("/delegations")
async def get_delegations():
    """
    Returns active out-of-office delegation rules.
    """
    return {
        "status": "success",
        "delegations": DELEGATIONS_STORE
    }

@router.post("/delegations")
async def create_delegation(req: DelegationRuleRequest):
    """
    Registers an out-of-office delegation rule.
    """
    new_rule = {
        "id": f"DEL-{uuid.uuid4().hex[:6].upper()}",
        "delegator": req.delegator,
        "delegatee": req.delegatee,
        "scope": req.scope,
        "valid_from": req.valid_from,
        "valid_until": req.valid_until,
        "reason": req.reason,
        "active": True
    }
    DELEGATIONS_STORE.insert(0, new_rule)
    return {
        "status": "success",
        "message": f"Delegation from '{req.delegator}' to '{req.delegatee}' active.",
        "delegation": new_rule
    }
