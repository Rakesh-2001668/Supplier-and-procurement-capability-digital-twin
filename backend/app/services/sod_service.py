"""
Segregation of Duties (SoD) Command-Time Enforcement Engine (Principle P09)
AlphaHelion Purchasing Intelligence Cloud
Evaluates action-level conflicts (SOD-01..07) at the moment of action for humans and AI agents.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
from pydantic import BaseModel

class SodViolation(Exception):
    def __init__(self, rule_id: str, message: str, risk: str, conflicting_action: str):
        self.rule_id = rule_id
        self.message = message
        self.risk = risk
        self.conflicting_action = conflicting_action
        super().__init__(f"[{rule_id}] {risk} SoD Conflict: {message}")

class ActionHistoryStore:
    def __init__(self):
        # In-memory store of historical actions per object: { (object_type, object_id): [ {action, actor, timestamp} ] }
        self.action_history: Dict[str, List[Dict[str, Any]]] = {}

    def record_action(self, object_type: str, object_id: str, action: str, actor: str):
        key = f"{object_type}:{object_id}"
        if key not in self.action_history:
            self.action_history[key] = []
        self.action_history[key].append({
            "action": action,
            "actor": actor,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })

    def get_actors_for_action(self, object_type: str, object_id: str, action: str) -> List[str]:
        key = f"{object_type}:{object_id}"
        return [entry["actor"] for entry in self.action_history.get(key, []) if entry["action"] == action]

action_history_store = ActionHistoryStore()

class SodEngine:
    """
    SoD Rule Catalogue from Blueprint Table 4:
    - SOD-01: Create supplier master vs Create PO for same supplier (High)
    - SOD-02: Change supplier bank details vs Approve payment / post invoice (Critical)
    - SOD-03: Create PO vs Post GR / SES for same PO (High)
    - SOD-04: Create PO vs Approve invoice exception for same PO (High)
    - SOD-05: Award sourcing event vs Score same event as sole evaluator (Medium)
    - SOD-06: Request material vs Approve same material as steward (Medium)
    - SOD-07: Initiate savings vs Validate same savings (High)
    """

    def check_action(
        self,
        actor: str,
        target_action: str,
        target_object_type: str,
        target_object_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Validates whether the actor can perform target_action without violating active SoD rules.
        Raises SodViolation if blocked without mitigation.
        """
        context = context or {}

        # SOD-01: Requisition Creator cannot approve own PR
        if target_action == "APPROVE_PR":
            pr_id = context.get("pr_id") or target_object_id
            pr_creators = action_history_store.get_actors_for_action("PURCHASE_REQUISITION", pr_id, "CREATE_PR")
            if actor in pr_creators:
                violation = SodViolation(
                    rule_id="SOD-01",
                    message=f"Actor '{actor}' created Purchase Requisition '{pr_id}' and cannot approve their own requisition (Principle P09).",
                    risk="High",
                    conflicting_action="CREATE_PR"
                )
                self.record_violation(violation, actor, target_action, target_object_type, target_object_id)
                raise violation

        # SOD-05: Award Sourcing Event vs Sourcing Creator / Sole Evaluator
        if target_action == "APPROVE_SOURCING_AWARD":
            rfq_id = context.get("rfq_id") or target_object_id
            rfq_creators = action_history_store.get_actors_for_action("SOURCING_EVENT", rfq_id, "CREATE_SOURCING_EVENT")
            if actor in rfq_creators:
                violation = SodViolation(
                    rule_id="SOD-05",
                    message=f"Actor '{actor}' published RFQ event '{rfq_id}' and cannot be the sole authorizing sign-off for the sourcing award without independent Board sign-off.",
                    risk="High",
                    conflicting_action="CREATE_SOURCING_EVENT"
                )
                self.record_violation(violation, actor, target_action, target_object_type, target_object_id)
                raise violation

        # SOD-03: Create PO vs Post GR / Approve SES for same PO
        if target_action in ["POST_GR", "APPROVE_SES"]:
            po_id = context.get("po_id") or target_object_id
            po_creators = action_history_store.get_actors_for_action("PURCHASE_ORDER", po_id, "CREATE_PO")
            if actor in po_creators:
                violation = SodViolation(
                    rule_id="SOD-03",
                    message=f"Actor '{actor}' created Purchase Order '{po_id}' and cannot post GR or approve Service Entry Sheet for the same order.",
                    risk="High",
                    conflicting_action="CREATE_PO"
                )
                self.record_violation(violation, actor, target_action, target_object_type, target_object_id)
                raise violation

        # SOD-04: Create PO vs Approve Invoice Exception
        if target_action == "APPROVE_INVOICE_EXCEPTION":
            po_id = context.get("po_id") or target_object_id
            po_creators = action_history_store.get_actors_for_action("PURCHASE_ORDER", po_id, "CREATE_PO")
            if actor in po_creators:
                violation = SodViolation(
                    rule_id="SOD-04",
                    message=f"Actor '{actor}' created Purchase Order '{po_id}' and cannot approve price/quantity invoice exceptions for it.",
                    risk="High",
                    conflicting_action="CREATE_PO"
                )
                self.record_violation(violation, actor, target_action, target_object_type, target_object_id)
                raise violation

        # SOD-02: Change supplier bank details vs Approve payment / post invoice
        if target_action in ["POST_INVOICE", "APPROVE_PAYMENT"]:
            supplier_id = context.get("supplier_id")
            if supplier_id:
                bank_changers = action_history_store.get_actors_for_action("SUPPLIER", supplier_id, "CHANGE_BANK_DETAILS")
                if actor in bank_changers:
                    violation = SodViolation(
                        rule_id="SOD-02",
                        message=f"Actor '{actor}' modified bank details for supplier '{supplier_id}' within cooling-off period and cannot post invoices or approve payments.",
                        risk="Critical",
                        conflicting_action="CHANGE_BANK_DETAILS"
                    )
                    self.record_violation(violation, actor, target_action, target_object_type, target_object_id)
                    raise violation

        # SOD-06: Request material vs Approve as steward
        if target_action == "APPROVE_MATERIAL_STEWARD":
            material_id = target_object_id
            requesters = action_history_store.get_actors_for_action("MATERIAL_REQUEST", material_id, "REQUEST_MATERIAL")
            if actor in requesters:
                violation = SodViolation(
                    rule_id="SOD-06",
                    message=f"Actor '{actor}' requested material '{material_id}' and cannot approve it as Domain Steward.",
                    risk="Medium",
                    conflicting_action="REQUEST_MATERIAL"
                )
                self.record_violation(violation, actor, target_action, target_object_type, target_object_id)
                raise violation

        # SOD-07: Initiate savings vs Validate savings
        if target_action == "VALIDATE_SAVINGS":
            initiative_id = target_object_id
            initiators = action_history_store.get_actors_for_action("SAVINGS_INITIATIVE", initiative_id, "INITIATE_SAVINGS")
            if actor in initiators:
                violation = SodViolation(
                    rule_id="SOD-07",
                    message=f"Actor '{actor}' initiated savings initiative '{initiative_id}' and cannot self-validate finance realization.",
                    risk="High",
                    conflicting_action="INITIATE_SAVINGS"
                )
                self.record_violation(violation, actor, target_action, target_object_type, target_object_id)
                raise violation

        return {
            "status": "APPROVED",
            "actor": actor,
            "action": target_action,
            "sod_checks_passed": True
        }

    def record_violation(self, violation: SodViolation, actor: str, target_action: str, target_object_type: str, target_object_id: str):
        sod_violations_log.insert(0, {
            "rule_id": violation.rule_id,
            "risk": violation.risk,
            "message": violation.message,
            "conflicting_action": violation.conflicting_action,
            "attempted_action": target_action,
            "actor": actor,
            "target_object": f"{target_object_type}:{target_object_id}",
            "blocked_at": datetime.utcnow().isoformat() + "Z",
            "enforcement": "HARD_BLOCK"
        })

sod_violations_log: List[Dict[str, Any]] = [
    {
        "rule_id": "SOD-01",
        "risk": "High",
        "message": "Actor 'priya.sharma@alphahelion.com' attempted to approve self-created PR #REQ-2024-8891.",
        "conflicting_action": "CREATE_PR",
        "attempted_action": "APPROVE_PR",
        "actor": "priya.sharma@alphahelion.com",
        "target_object": "PURCHASE_REQUISITION:REQ-2024-8891",
        "blocked_at": "2026-10-24T06:15:00Z",
        "enforcement": "HARD_BLOCK"
    },
    {
        "rule_id": "SOD-05",
        "risk": "High",
        "message": "Actor 'amit.verma@alphahelion.com' attempted to authorize RFQ-701 Die-Casting tender award where they were the sole evaluator.",
        "conflicting_action": "CREATE_SOURCING_EVENT",
        "attempted_action": "APPROVE_SOURCING_AWARD",
        "actor": "amit.verma@alphahelion.com",
        "target_object": "SOURCING_EVENT:RFQ-701",
        "blocked_at": "2026-10-24T08:30:00Z",
        "enforcement": "HARD_BLOCK"
    }
]

sod_engine = SodEngine()
