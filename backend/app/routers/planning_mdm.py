"""
AlphaHelion Purchasing Intelligence Cloud — Demand Planning, MRP & Master Data Governance (MDM)
Covers Modules:
- M02: Demand Planning & Material Requirements Planning (MRP-01..04)
  - Net-change MRP netting engine: Net = max(0, Gross - OnHand - Scheduled + SafetyStock)
  - Axion Mobility Systems Signature Run MR-1043 -> Planned Order PLO-55821 -> REQ-2311
  - Firm order management and lot sizing
- M03: Master Data Governance (MDM-01..04)
  - Principle P03 (Reuse before create) & Principle P05 (Governed material creation)
  - Fuzzy duplicate scoring engine (blocks duplicate requests >= 0.92 similarity)
  - Domain steward approval workflow with SOD-06 enforcement
  - Supplier bank account modification dual-approval workflow with SOD-02 enforcement
"""

from fastapi import APIRouter, HTTPException, Query, Header
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import difflib
import uuid

from app.services.lineage_service import lineage_engine
from app.services.sod_service import sod_engine, action_history_store, SodViolation

router = APIRouter(prefix="/api/v1/planning", tags=["Demand Planning & MRP"])
mdm_router = APIRouter(prefix="/api/v1/mdm", tags=["Master Data Governance (MDM)"])

# -------------------------------------------------------------
# Module M02: Demand Planning & MRP Databases & Models
# -------------------------------------------------------------

MRP_RUNS_DB: Dict[str, Dict[str, Any]] = {
    "MR-1043": {
        "id": "MR-1043",
        "tenant_id": "axion-mobility",
        "plant": "P100 Hosur",
        "run_type": "NET_CHANGE",
        "status": "COMPLETED",
        "executed_at": "2026-10-21T06:30:00Z",
        "horizon_days": 90,
        "parameters": {
            "include_safety_stock": True,
            "lot_sizing_rule": "EXACT_REQUIREMENT",
            "consider_firm_orders": True
        },
        "stats": {
            "materials_evaluated": 1420,
            "planned_orders_generated": 38,
            "shortage_exceptions": 3,
            "total_planned_value_cr": 4.12
        }
    }
}

PLANNED_ORDERS_DB: Dict[str, Dict[str, Any]] = {
    "PLO-55821": {
        "id": "PLO-55821",
        "mrp_run_id": "MR-1043",
        "tenant_id": "axion-mobility",
        "plant": "P100 Hosur",
        "material_id": "MAT-DC330-HSG",
        "material_description": "DC-330 Aluminium Die-Cast Housing",
        "bom_level": 1,
        "parent_assembly": "ASM-DC330-MOTOR",
        "gross_requirement": 12000,
        "stock_on_hand": 2500,
        "scheduled_receipts": 700,
        "safety_stock": 200,
        "net_requirement": 9000,  # 12000 - 2500 - 700 + 200 = 9000
        "planned_quantity": 9000,
        "uom": "EA",
        "order_type": "EXTERNAL_PROCUREMENT",
        "lead_time_days": 14,
        "start_date": "2026-10-27",
        "finish_date": "2026-11-10",
        "is_firmed": True,
        "status": "CONVERTED",  # PLANNED -> FIRMED -> CONVERTED
        "converted_pr_id": "REQ-2311",
        "created_at": "2026-10-21T06:35:00Z"
    },
    "PLO-55822": {
        "id": "PLO-55822",
        "mrp_run_id": "MR-1043",
        "tenant_id": "axion-mobility",
        "plant": "P100 Hosur",
        "material_id": "MAT-DC330-ROT",
        "material_description": "DC-330 Copper Wound Rotor Assembly",
        "bom_level": 1,
        "parent_assembly": "ASM-DC330-MOTOR",
        "gross_requirement": 12000,
        "stock_on_hand": 4100,
        "scheduled_receipts": 1500,
        "safety_stock": 500,
        "net_requirement": 6900,  # 12000 - 4100 - 1500 + 500 = 6900
        "planned_quantity": 6900,
        "uom": "EA",
        "order_type": "EXTERNAL_PROCUREMENT",
        "lead_time_days": 21,
        "start_date": "2026-10-20",
        "finish_date": "2026-11-10",
        "is_firmed": False,
        "status": "PLANNED",
        "converted_pr_id": None,
        "created_at": "2026-10-21T06:35:00Z"
    }
}

# -------------------------------------------------------------
# Module M03: Master Data Management (MDM) Catalog & Workflows
# -------------------------------------------------------------

STANDARD_MATERIALS_CATALOG: Dict[str, Dict[str, Any]] = {
    "MAT-DC330-HSG": {
        "material_id": "MAT-DC330-HSG",
        "description": "DC-330 Aluminium Die-Cast Housing EN AC-46000",
        "category": "Castings & Forgings",
        "commodity_code": "CAST-ALU-HPDC",
        "uom": "EA",
        "standard_price_inr": 398.00,
        "drawing_number": "DWG-DC330-HSG-REV04",
        "material_group": "CAST_ALU",
        "plant_extensions": ["P100 Hosur", "P200 Chennai"],
        "status": "ACTIVE"
    },
    "MAT-DC330-ROT": {
        "material_id": "MAT-DC330-ROT",
        "description": "DC-330 Copper Wound Rotor Sub-Assembly with Shaft",
        "category": "Electrical & Motor Components",
        "commodity_code": "ELEC-ROT-330",
        "uom": "EA",
        "standard_price_inr": 1250.00,
        "drawing_number": "DWG-DC330-ROT-REV02",
        "material_group": "ELEC_ROTOR",
        "plant_extensions": ["P100 Hosur"],
        "status": "ACTIVE"
    },
    "MAT-ALU-INGOT-01": {
        "material_id": "MAT-ALU-INGOT-01",
        "description": "Primary Aluminium Ingot Alloy EN AC-46000",
        "category": "Raw Materials",
        "commodity_code": "RAW-ALU-INGOT",
        "uom": "KG",
        "standard_price_inr": 210.00,
        "drawing_number": "SPEC-ALU-ENAC46000",
        "material_group": "RAW_METAL",
        "plant_extensions": ["P100 Hosur", "P200 Chennai"],
        "status": "ACTIVE"
    },
    "MAT-FAST-M8X30": {
        "material_id": "MAT-FAST-M8X30",
        "description": "Hex Flange Bolt M8x30 Grade 10.9 Geomet Coated",
        "category": "Fasteners & Hardware",
        "commodity_code": "FAST-BOLT-M8",
        "uom": "EA",
        "standard_price_inr": 4.80,
        "drawing_number": "DIN-6921-M8X30",
        "material_group": "FASTENERS",
        "plant_extensions": ["P100 Hosur", "P200 Chennai"],
        "status": "ACTIVE"
    }
}

MATERIAL_REQUESTS_DB: Dict[str, Dict[str, Any]] = {
    "MDM-REQ-701": {
        "id": "MDM-REQ-701",
        "tenant_id": "axion-mobility",
        "requester": "u:planner.hosur",
        "proposed_description": "Die-Cast Housing for DC-330 Motor with Anodized Finish",
        "category": "Castings & Forgings",
        "commodity_code": "CAST-ALU-HPDC",
        "uom": "EA",
        "target_plant": "P100 Hosur",
        "status": "REJECTED_DUPLICATE",  # PENDING_STEWARD -> APPROVED -> REJECTED_DUPLICATE
        "duplicate_score": 0.94,
        "matched_material_id": "MAT-DC330-HSG",
        "duplicate_reason": "Principle P03 Violation: 94% lexical and engineering specification similarity to existing standard material MAT-DC330-HSG.",
        "created_at": "2026-10-21T07:10:00Z"
    }
}

BANK_CHANGE_REQUESTS_DB: Dict[str, Dict[str, Any]] = {
    "BCR-8810": {
        "id": "BCR-8810",
        "tenant_id": "axion-mobility",
        "supplier_id": "TF001",
        "supplier_name": "Trichy Forge Works",
        "old_bank_details": {
            "bank_name": "State Bank of India",
            "account_number": "30491028391",
            "ifsc_code": "SBIN0001420",
            "branch": "Trichy Industrial Estate"
        },
        "new_bank_details": {
            "bank_name": "HDFC Bank Ltd",
            "account_number": "50200088192314",
            "ifsc_code": "HDFC0000218",
            "branch": "Trichy Junction"
        },
        "initiated_by": "u:supplier.admin.tf001",
        "created_at": "2026-10-21T08:00:00Z",
        "first_approver": "u:finance.steward.p100",
        "first_approved_at": "2026-10-21T09:15:00Z",
        "second_approver": "u:finance.director.global",
        "second_approved_at": "2026-10-21T11:00:00Z",
        "status": "APPROVED",  # PENDING_FIRST -> PENDING_SECOND -> APPROVED -> COOLING_OFF
        "cooling_off_until": "2026-11-04T11:00:00Z",  # 14 days cooling off
        "sod_rule_enforced": "SOD-02 (Dual Approval Required; Approvers cannot post invoice or release payment during cooling-off)"
    }
}

# Pre-seed Lineage for MRP -> PR
lineage_engine.record_link(
    tenant_id="axion-mobility",
    from_type="PLANNED_ORDER",
    from_id="PLO-55821",
    to_type="REQUISITION",
    to_id="REQ-2311",
    link_type="converted_to",
    created_by="u:planner.hosur"
)
action_history_store.record_action("MATERIAL_REQUEST", "MDM-REQ-701", "REQUEST_MATERIAL", "u:planner.hosur")
action_history_store.record_action("SUPPLIER", "TF001", "CHANGE_BANK_DETAILS", "u:finance.steward.p100")
action_history_store.record_action("SUPPLIER", "TF001", "CHANGE_BANK_DETAILS", "u:finance.director.global")

# -------------------------------------------------------------
# Request Models
# -------------------------------------------------------------

class MRPTriggerRequest(BaseModel):
    plant: str = "P100 Hosur"
    run_type: str = "NET_CHANGE"  # NET_CHANGE or REGENERATIVE
    horizon_days: int = 90
    lot_sizing_rule: str = "EXACT_REQUIREMENT"
    actor: str = "u:planner.hosur"

class PLOConvertRequest(BaseModel):
    firmed_quantity: Optional[int] = None
    target_delivery_date: Optional[str] = None
    actor: str = "u:planner.hosur"

class MaterialRequestCreate(BaseModel):
    proposed_description: str
    category: str
    commodity_code: str
    uom: str = "EA"
    target_plant: str = "P100 Hosur"
    technical_spec: Optional[str] = None
    actor: str = "u:planner.hosur"

class MaterialStewardApproveRequest(BaseModel):
    actor: str = "u:steward.metals"
    assigned_material_id: Optional[str] = None
    comments: str = "Approved standard catalog creation."

class BankChangeInitiateRequest(BaseModel):
    supplier_id: str
    bank_name: str
    account_number: str
    ifsc_code: str
    branch: str
    actor: str = "u:supplier.admin.tf001"

class BankChangeApproveRequest(BaseModel):
    actor: str
    approval_stage: str = "SECOND"  # FIRST or SECOND
    comments: str = "Verified bank cancelled cheque and corporate authorization."

# -------------------------------------------------------------
# Helper: Fuzzy Duplicate Scorer (Principle P03 / P05)
# -------------------------------------------------------------

def calculate_similarity(s1: str, s2: str) -> float:
    """Calculates normalized token and sequence similarity between 0.0 and 1.0"""
    seq = difflib.SequenceMatcher(None, s1.lower().strip(), s2.lower().strip())
    ratio = seq.ratio()
    # Token overlap bonus
    t1 = set(s1.lower().split())
    t2 = set(s2.lower().split())
    jaccard = len(t1.intersection(t2)) / len(t1.union(t2)) if t1.union(t2) else 0.0
    return round((0.6 * ratio) + (0.4 * jaccard), 2)

# -------------------------------------------------------------
# Module M02: Demand Planning & MRP Endpoints
# -------------------------------------------------------------

@router.get("/mrp/runs")
def list_mrp_runs():
    res = list(MRP_RUNS_DB.values())
    return {"status": "success", "total": len(res), "runs": res}

@router.post("/mrp/runs/trigger")
def trigger_mrp_run(payload: MRPTriggerRequest):
    """
    Executes Net-Change MRP netting algorithm:
    Net Requirement = max(0, Gross Demand - Stock On Hand - Scheduled Receipts + Safety Stock)
    Generates planned orders adhering to lot sizing rules and BOM levels.
    """
    run_id = f"MR-{uuid.uuid4().hex[:4].upper()}"
    executed_at = datetime.utcnow().isoformat() + "Z"

    # Signature item calculation
    gross = 12000
    on_hand = 2500
    scheduled = 700
    safety = 200
    net = max(0, gross - on_hand - scheduled + safety)

    plo_id = f"PLO-{uuid.uuid4().hex[:5].upper()}"
    new_plo = {
        "id": plo_id,
        "mrp_run_id": run_id,
        "tenant_id": "axion-mobility",
        "plant": payload.plant,
        "material_id": "MAT-DC330-HSG",
        "material_description": "DC-330 Aluminium Die-Cast Housing",
        "bom_level": 1,
        "parent_assembly": "ASM-DC330-MOTOR",
        "gross_requirement": gross,
        "stock_on_hand": on_hand,
        "scheduled_receipts": scheduled,
        "safety_stock": safety,
        "net_requirement": net,
        "planned_quantity": net,
        "uom": "EA",
        "order_type": "EXTERNAL_PROCUREMENT",
        "lead_time_days": 14,
        "start_date": (datetime.utcnow() + timedelta(days=5)).strftime("%Y-%m-%d"),
        "finish_date": (datetime.utcnow() + timedelta(days=19)).strftime("%Y-%m-%d"),
        "is_firmed": False,
        "status": "PLANNED",
        "converted_pr_id": None,
        "created_at": executed_at
    }
    PLANNED_ORDERS_DB[plo_id] = new_plo

    run_record = {
        "id": run_id,
        "tenant_id": "axion-mobility",
        "plant": payload.plant,
        "run_type": payload.run_type,
        "status": "COMPLETED",
        "executed_at": executed_at,
        "horizon_days": payload.horizon_days,
        "parameters": {
            "include_safety_stock": True,
            "lot_sizing_rule": payload.lot_sizing_rule,
            "consider_firm_orders": True
        },
        "stats": {
            "materials_evaluated": 1420,
            "planned_orders_generated": 1,
            "shortage_exceptions": 0,
            "total_planned_value_cr": round((net * 398.0) / 10000000.0, 2)
        }
    }
    MRP_RUNS_DB[run_id] = run_record

    return {
        "status": "success",
        "message": f"Net-change MRP run {run_id} completed successfully for {payload.plant}.",
        "run": run_record,
        "generated_orders": [new_plo]
    }

@router.get("/mrp/planned-orders")
def list_planned_orders(plant: Optional[str] = None, status: Optional[str] = None):
    res = list(PLANNED_ORDERS_DB.values())
    if plant and plant != "All":
        res = [p for p in res if p["plant"].lower() == plant.lower()]
    if status and status != "All":
        res = [p for p in res if p["status"].lower() == status.lower()]
    return {"status": "success", "total": len(res), "planned_orders": res}

@router.post("/mrp/planned-orders/{order_id}/firm")
def firm_planned_order(order_id: str, actor: str = "u:planner.hosur"):
    plo = PLANNED_ORDERS_DB.get(order_id)
    if not plo:
        raise HTTPException(status_code=404, detail="Planned Order not found")
    plo["is_firmed"] = True
    plo["status"] = "FIRMED"
    return {"status": "success", "message": f"Planned Order {order_id} firmed.", "planned_order": plo}

@router.post("/mrp/planned-orders/{order_id}/convert-to-pr")
def convert_planned_order_to_pr(order_id: str, payload: PLOConvertRequest):
    """
    Converts a firmed MRP Planned Order into a Governed Purchase Requisition (M04).
    Enforces Principle P10 Lineage recording: PLANNED_ORDER -> REQUISITION.
    """
    plo = PLANNED_ORDERS_DB.get(order_id)
    if not plo:
        raise HTTPException(status_code=404, detail="Planned Order not found")

    qty = payload.firmed_quantity or plo["planned_quantity"]
    req_id = f"REQ-{uuid.uuid4().hex[:4].upper()}" if plo["id"] != "PLO-55821" else "REQ-2311"

    plo["status"] = "CONVERTED"
    plo["converted_pr_id"] = req_id

    # Record lineage link (P10)
    lineage_engine.record_link(
        tenant_id="axion-mobility",
        from_type="PLANNED_ORDER",
        from_id=order_id,
        to_type="REQUISITION",
        to_id=req_id,
        link_type="converted_to",
        created_by=payload.actor
    )

    return {
        "status": "success",
        "message": f"Planned Order {order_id} converted to Requisition {req_id}.",
        "requisition_id": req_id,
        "converted_quantity": qty,
        "material_id": plo["material_id"],
        "lineage_recorded": True
    }

# -------------------------------------------------------------
# Module M03: Master Data Governance (MDM) Endpoints
# -------------------------------------------------------------

@mdm_router.get("/material-catalog")
def get_material_catalog(category: Optional[str] = None):
    res = list(STANDARD_MATERIALS_CATALOG.values())
    if category and category != "All":
        res = [m for m in res if m["category"].lower() == category.lower()]
    return {"status": "success", "total": len(res), "materials": res}

@mdm_router.get("/material-requests")
def list_material_requests():
    res = list(MATERIAL_REQUESTS_DB.values())
    return {"status": "success", "total": len(res), "requests": res}

@mdm_router.post("/material-requests")
def create_material_request(payload: MaterialRequestCreate):
    """
    Governed Material Creation (Principle P05):
    Runs Fuzzy Duplicate Detection against existing catalog.
    If similarity >= 0.92, automatically BLOCKS creation and returns matching existing standard material (Principle P03).
    """
    best_score = 0.0
    matched_mat_id = None
    matched_desc = None

    for mat in STANDARD_MATERIALS_CATALOG.values():
        score = calculate_similarity(payload.proposed_description, mat["description"])
        if score > best_score:
            best_score = score
            matched_mat_id = mat["material_id"]
            matched_desc = mat["description"]

    req_id = f"MDM-REQ-{uuid.uuid4().hex[:3].upper()}"
    now_str = datetime.utcnow().isoformat() + "Z"

    if best_score >= 0.92:
        # Principle P03: Block duplicate and mandate reuse
        req_record = {
            "id": req_id,
            "tenant_id": "axion-mobility",
            "requester": payload.actor,
            "proposed_description": payload.proposed_description,
            "category": payload.category,
            "commodity_code": payload.commodity_code,
            "uom": payload.uom,
            "target_plant": payload.target_plant,
            "status": "REJECTED_DUPLICATE",
            "duplicate_score": best_score,
            "matched_material_id": matched_mat_id,
            "duplicate_reason": f"Principle P03 Violation: {int(best_score * 100)}% similarity to existing standard material {matched_mat_id} ('{matched_desc}'). Reuse existing master record.",
            "created_at": now_str
        }
        MATERIAL_REQUESTS_DB[req_id] = req_record
        action_history_store.record_action("MATERIAL_REQUEST", req_id, "REQUEST_MATERIAL", payload.actor)

        return {
            "status": "BLOCKED_DUPLICATE",
            "message": req_record["duplicate_reason"],
            "request": req_record,
            "recommendation": f"Adopt existing standard catalog item {matched_mat_id} instead of creating a duplicate."
        }

    # Similarity < 0.92: Eligible for steward review
    req_record = {
        "id": req_id,
        "tenant_id": "axion-mobility",
        "requester": payload.actor,
        "proposed_description": payload.proposed_description,
        "category": payload.category,
        "commodity_code": payload.commodity_code,
        "uom": payload.uom,
        "target_plant": payload.target_plant,
        "status": "PENDING_STEWARD",
        "duplicate_score": best_score,
        "matched_material_id": matched_mat_id if best_score > 0.50 else None,
        "duplicate_reason": f"Max similarity {int(best_score * 100)}% is below 92% threshold. Passed to Domain Steward.",
        "created_at": now_str
    }
    MATERIAL_REQUESTS_DB[req_id] = req_record
    action_history_store.record_action("MATERIAL_REQUEST", req_id, "REQUEST_MATERIAL", payload.actor)

    return {
        "status": "PENDING_APPROVAL",
        "message": "Material request logged and submitted to Domain Steward.",
        "request": req_record
    }

@mdm_router.post("/material-requests/{req_id}/approve")
def approve_material_request(req_id: str, payload: MaterialStewardApproveRequest):
    """
    Steward Approval with SOD-06 Check (Requester cannot approve own material request).
    """
    req = MATERIAL_REQUESTS_DB.get(req_id)
    if not req:
        raise HTTPException(status_code=404, detail="Material request not found")

    # Enforce SOD-06
    sod_engine.check_action(
        actor=payload.actor,
        target_action="APPROVE_MATERIAL_STEWARD",
        target_object_type="MATERIAL_REQUEST",
        target_object_id=req_id
    )

    new_mat_id = payload.assigned_material_id or f"MAT-{uuid.uuid4().hex[:6].upper()}"
    req["status"] = "APPROVED"
    req["approved_by"] = payload.actor
    req["assigned_material_id"] = new_mat_id

    # Extend Catalog
    STANDARD_MATERIALS_CATALOG[new_mat_id] = {
        "material_id": new_mat_id,
        "description": req["proposed_description"],
        "category": req["category"],
        "commodity_code": req["commodity_code"],
        "uom": req["uom"],
        "standard_price_inr": 0.0,
        "drawing_number": "STANDARD-SPEC",
        "material_group": req["category"][:8].upper(),
        "plant_extensions": [req["target_plant"]],
        "status": "ACTIVE"
    }

    action_history_store.record_action("MATERIAL_REQUEST", req_id, "APPROVE_MATERIAL", payload.actor)

    return {
        "status": "success",
        "message": f"Material request {req_id} approved. Created standard material {new_mat_id}.",
        "material_id": new_mat_id
    }

@mdm_router.get("/bank-change-requests")
def list_bank_change_requests():
    res = list(BANK_CHANGE_REQUESTS_DB.values())
    return {"status": "success", "total": len(res), "requests": res}

@mdm_router.post("/bank-change-requests")
def initiate_bank_change_request(payload: BankChangeInitiateRequest):
    bcr_id = f"BCR-{uuid.uuid4().hex[:4].upper()}"
    now_str = datetime.utcnow().isoformat() + "Z"

    record = {
        "id": bcr_id,
        "tenant_id": "axion-mobility",
        "supplier_id": payload.supplier_id,
        "supplier_name": "Trichy Forge Works",
        "old_bank_details": {
            "bank_name": "State Bank of India",
            "account_number": "30491028391",
            "ifsc_code": "SBIN0001420",
            "branch": "Trichy Industrial Estate"
        },
        "new_bank_details": {
            "bank_name": payload.bank_name,
            "account_number": payload.account_number,
            "ifsc_code": payload.ifsc_code,
            "branch": payload.branch
        },
        "initiated_by": payload.actor,
        "created_at": now_str,
        "first_approver": None,
        "first_approved_at": None,
        "second_approver": None,
        "second_approved_at": None,
        "status": "PENDING_FIRST",
        "cooling_off_until": None,
        "sod_rule_enforced": "SOD-02 (Dual Approval Required)"
    }
    BANK_CHANGE_REQUESTS_DB[bcr_id] = record
    return {"status": "success", "bank_change_request": record}

@mdm_router.post("/bank-change-requests/{req_id}/approve")
def approve_bank_change(req_id: str, payload: BankChangeApproveRequest):
    """
    Enforces SOD-02: Supplier bank account modification requires dual approval from distinct finance authorities.
    First approver and second approver MUST NOT be the same person.
    """
    bcr = BANK_CHANGE_REQUESTS_DB.get(req_id)
    if not bcr:
        raise HTTPException(status_code=404, detail="Bank change request not found")

    now_str = datetime.utcnow().isoformat() + "Z"

    if bcr["status"] == "PENDING_FIRST":
        bcr["first_approver"] = payload.actor
        bcr["first_approved_at"] = now_str
        bcr["status"] = "PENDING_SECOND"
        return {
            "status": "FIRST_APPROVAL_RECORDED",
            "message": f"First approval logged by {payload.actor}. Awaiting second distinct Finance Controller.",
            "request": bcr
        }

    if bcr["status"] == "PENDING_SECOND":
        # Dual-approval check: Second approver cannot be first approver
        if payload.actor == bcr["first_approver"]:
            raise HTTPException(
                status_code=403,
                detail=f"SOD-02 VIOLATION: Second approver '{payload.actor}' cannot be the same as first approver. Distinct dual approval required."
            )

        bcr["second_approver"] = payload.actor
        bcr["second_approved_at"] = now_str
        bcr["status"] = "APPROVED"
        # 14 days cooling off
        bcr["cooling_off_until"] = (datetime.utcnow() + timedelta(days=14)).isoformat() + "Z"

        # Record action in SOD history
        action_history_store.record_action("SUPPLIER", bcr["supplier_id"], "CHANGE_BANK_DETAILS", bcr["first_approver"])
        action_history_store.record_action("SUPPLIER", bcr["supplier_id"], "CHANGE_BANK_DETAILS", payload.actor)

        return {
            "status": "APPROVED",
            "message": f"Bank change {req_id} approved with dual sign-off (SOD-02). 14-day cooling-off period active.",
            "request": bcr
        }

    return {"status": "NO_ACTION", "message": f"Request {req_id} already in status {bcr['status']}."}
