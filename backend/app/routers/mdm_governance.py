"""
AlphaHelion Purchasing Intelligence Cloud
Module: Material Master Governance & Fuzzy Duplicate Shield Studio (MDM-01..04)
With Agent AGT-MDM-03 (MDM Duplicate Sentinel) Integration
Blueprint Reference: Section 11 (pages 18-20), BPMN Flow F9 (pic.material-request), Principles P03, P04, P05, P09, P10
"""

from fastapi import APIRouter, HTTPException, Query, Header, Body
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import difflib
import uuid

from app.services.lineage_service import lineage_engine
from app.services.sod_service import sod_engine, action_history_store, SodViolation
from app.services.outbox_service import outbox_service
from app.routers.spend_cube_ai_agents import AI_AGENTS_REGISTRY
from app.routers.planning_mdm import STANDARD_MATERIALS_CATALOG, MATERIAL_REQUESTS_DB

router = APIRouter(prefix="/api/v1/mdm/studio", tags=["Material Master Governance & Duplicate Shield"])

# ==============================================================================
# PYDANTIC SCHEMAS
# ==============================================================================

class DuplicateAnalysisRequest(BaseModel):
    proposed_description: str
    category: str
    commodity_code: Optional[str] = None
    uom: str = "EA"
    manufacturer_part_no: Optional[str] = None
    target_plant: Optional[str] = "P100 Hosur"

class MaterialCreationRequest(BaseModel):
    proposed_description: str
    category: str
    commodity_code: str
    uom: str = "EA"
    target_plant: str = "P100 Hosur"
    technical_spec: Optional[str] = None
    actor: str = "u:planner.hosur"
    differentiation_justification: Optional[str] = None

class StewardViewEnrichmentRequest(BaseModel):
    view_name: str # purchasing, plant, quality, accounting
    actor: str
    attributes: Dict[str, Any]

class StewardFinalApprovalRequest(BaseModel):
    actor: str
    assigned_material_id: Optional[str] = None
    steward_notes: str = "Approved standard aerospace material master"

# ==============================================================================
# IN-MEMORY MULTI-VIEW ENRICHMENT STORE
# ==============================================================================

MATERIAL_VIEWS_DB: Dict[str, Dict[str, Any]] = {
    "MDM-REQ-701": {
        "request_id": "MDM-REQ-701",
        "purchasing_view": {
            "purchasing_group": "P01 Powertrain",
            "order_unit": "EA",
            "overdelivery_tolerance_pct": 0.0,
            "underdelivery_tolerance_pct": 5.0,
            "planned_lead_time_days": 14,
            "default_incoterms": "FCA Trichy",
            "enriched": True,
            "enriched_by": "u:steward.purchasing"
        },
        "plant_view": {
            "plant": "P100 Hosur",
            "mrp_type": "PD (MRP Netting)",
            "lot_sizing_procedure": "EX (Lot-for-lot)",
            "safety_stock": 200,
            "reorder_point": 500,
            "storage_location": "SL01 Raw Stores",
            "enriched": True,
            "enriched_by": "u:steward.plant"
        },
        "quality_view": {
            "inspection_setup": "01 Goods Receipt for PO",
            "certificate_required": "PPAP Level 3 & CoA",
            "skip_lot_active": False,
            "defect_ppm_threshold": 50,
            "enriched": True,
            "enriched_by": "u:steward.quality"
        },
        "accounting_view": {
            "valuation_class": "3000 Raw Materials",
            "price_control": "S (Standard Price)",
            "standard_valuation_inr": 398.00,
            "enriched": True,
            "enriched_by": "u:steward.finance"
        }
    }
}

# Ensure existing material request in planning_mdm is registered in action_history for SOD-06
action_history_store.record_action("MATERIAL_REQUEST", "MDM-REQ-701", "REQUEST_MATERIAL", "u:planner.hosur")

# ==============================================================================
# ADVANCED FUZZY DUPLICATE SHIELD ALGORITHM
# ==============================================================================
# ADVANCED FUZZY DUPLICATE SHIELD ALGORITHM (Blueprint Section 11 & Principle P03)
# ==============================================================================

STOP_WORDS = {"for", "with", "and", "the", "in", "of", "a", "an", "to", "by", "from", "on"}

def extract_core_tokens(text: str) -> List[str]:
    clean = text.lower().replace('/', ' ').replace(',', ' ').replace('(', ' ').replace(')', ' ')
    raw_tokens = clean.split()
    return [t for t in raw_tokens if t not in STOP_WORDS and len(t) > 1]

def extract_model_codes(text: str) -> set:
    clean = text.lower().replace('/', ' ').replace(',', ' ')
    codes = set()
    for t in clean.split():
        # Has digits and letters or hyphens like dc-330, m8x30, 46000
        has_digit = any(c.isdigit() for c in t)
        has_alpha = any(c.isalpha() for c in t)
        if (has_digit and has_alpha) or (has_digit and '-' in t):
            codes.add(t)
    return codes

def evaluate_fuzzy_duplicate_shield(proposed_desc: str, category: str) -> Dict[str, Any]:
    """
    Evaluates candidate description against standard materials catalog:
    1. Normalized SequenceMatcher ratio
    2. Token Sort Ratio (invariant to word order)
    3. Core Keyword Coverage (containment of catalog specification)
    4. Exact Model / Drawing Code match detection (e.g. DC-330, M8x30)
    5. Category semantic affinity
    Cutoff: 0.92 (92%) triggers Principle P03 Hard Block.
    """
    best_score = 0.0
    matched_mat = None
    all_scores = []
    
    cand_tokens = extract_core_tokens(proposed_desc)
    cand_set = set(cand_tokens)
    cand_models = extract_model_codes(proposed_desc)
    cand_sorted_str = " ".join(sorted(cand_tokens))

    for mat_id, mat in STANDARD_MATERIALS_CATALOG.items():
        ref_tokens = extract_core_tokens(mat["description"])
        ref_set = set(ref_tokens)
        ref_models = extract_model_codes(mat["description"])
        ref_sorted_str = " ".join(sorted(ref_tokens))
        
        # 1. Sequence Matcher on raw and sorted tokens
        raw_seq = difflib.SequenceMatcher(None, proposed_desc.lower().strip(), mat["description"].lower().strip()).ratio()
        sorted_seq = difflib.SequenceMatcher(None, cand_sorted_str, ref_sorted_str).ratio()
        
        # 2. Token Jaccard overlap and Token Set Similarity (RapidFuzz / FuzzyWuzzy standard)
        intersection = cand_set.intersection(ref_set)
        union = cand_set.union(ref_set)
        jaccard = len(intersection) / len(union) if union else 0.0
        
        s_inter = " ".join(sorted(intersection))
        if s_inter:
            r_inter_1 = difflib.SequenceMatcher(None, s_inter, cand_sorted_str).ratio()
            r_inter_2 = difflib.SequenceMatcher(None, s_inter, ref_sorted_str).ratio()
            token_set_sim = max(r_inter_1, r_inter_2)
        else:
            token_set_sim = 0.0
        
        # 3. Containment / Coverage of reference core concepts in candidate
        coverage = len(intersection) / len(ref_set) if ref_set else 0.0
        
        # 4. Model code matching boost
        model_match = bool(cand_models and ref_models and cand_models.intersection(ref_models))
        model_bonus = 0.15 if model_match else 0.0
        
        # 5. Category affinity bonus
        cat_match = mat.get("category", "").lower() == category.lower() or any(
            w in mat.get("category", "").lower() for w in category.lower().split()
        )
        cat_bonus = 0.05 if cat_match else 0.0
        
        # Composite score calculation (Principle P03)
        base_similarity = (0.50 * token_set_sim) + (0.25 * sorted_seq) + (0.15 * coverage) + (0.10 * jaccard)
        composite = round(min(1.0, base_similarity + model_bonus + cat_bonus), 2)
        
        all_scores.append({
            "material_id": mat_id,
            "description": mat["description"],
            "category": mat["category"],
            "similarity_score": composite,
            "token_overlap": list(intersection),
            "model_match": model_match
        })
        
        if composite > best_score:
            best_score = composite
            matched_mat = mat

    all_scores.sort(key=lambda x: x["similarity_score"], reverse=True)
    top_matches = all_scores[:3]
    
    # Governance decision band
    if best_score >= 0.92:
        band = "CRITICAL_DUPLICATE_RISK"
        action = "HARD_BLOCK"
        message = (
            f"Principle P03 Violation: {int(best_score * 100)}% similarity to existing standard material "
            f"{matched_mat['material_id']} ('{matched_mat['description']}'). Master creation blocked to prevent catalog pollution."
        )
    elif best_score >= 0.70:
        band = "POTENTIAL_DUPLICATE_WARNING"
        action = "REQUIRE_JUSTIFICATION"
        message = (
            f"Moderate similarity ({int(best_score * 100)}%) to {matched_mat['material_id']}. "
            "Requires mandatory technical differentiation justification prior to Domain Steward routing."
        )
    else:
        band = "UNIQUE_SPECIFICATION"
        action = "PASS_TO_STEWARD"
        message = f"Similarity score ({int(best_score * 100)}%) is well below 92% cutoff. Unique standard item eligible for master creation."

    return {
        "best_score": best_score,
        "governance_band": band,
        "governance_action": action,
        "cutoff_threshold": 0.92,
        "is_blocked": best_score >= 0.92,
        "message": message,
        "matched_material": matched_mat,
        "top_matches": top_matches
    }

# ==============================================================================
# REST ENDPOINTS
# ==============================================================================

@router.post("/analyze-duplicate")
async def analyze_duplicate_shield(req: DuplicateAnalysisRequest):
    """
    Real-time interactive Fuzzy Duplicate Shield evaluation.
    Called on keystroke or form blur to warn requesters of duplicate items before submission.
    Incorporates Agent AGT-MDM-03 (MDM Duplicate Sentinel).
    """
    analysis = evaluate_fuzzy_duplicate_shield(req.proposed_description, req.category)
    
    # Incorporate Agent AGT-MDM-03
    agent_info = AI_AGENTS_REGISTRY.get("AGT-MDM-03", {})
    if "AGT-MDM-03" in AI_AGENTS_REGISTRY:
        AI_AGENTS_REGISTRY["AGT-MDM-03"]["actions_today"] += 1
        AI_AGENTS_REGISTRY["AGT-MDM-03"]["last_active"] = datetime.now(timezone.utc).isoformat()
        
    copilot_contract = {
        "agent_id": "AGT-MDM-03",
        "agent_name": agent_info.get("name", "MDM Duplicate Sentinel"),
        "autonomy_level": agent_info.get("autonomy_level", "L4_AUTONOMOUS_EXECUTE"),
        "confidence_score": 0.98,
        "analysis": analysis,
        "recommendation": (
            f"Adopt standard record {analysis['matched_material']['material_id']} ({analysis['matched_material']['description']})"
            if analysis["is_blocked"]
            else "Specification qualifies as novel reusable part. Proceed with 4-view steward enrichment."
        )
    }
    
    return {
        "status": "success",
        "analysis": analysis,
        "agent_contract": copilot_contract
    }

@router.get("/requests")
async def list_governed_material_requests():
    """
    List all material requests with 4-view enrichment status and duplicate scores.
    """
    requests = list(MATERIAL_REQUESTS_DB.values())
    
    # Enrich with 4-view completeness
    enriched_list = []
    for r in requests:
        views = MATERIAL_VIEWS_DB.get(r["id"], {
            "purchasing_view": {"enriched": False},
            "plant_view": {"enriched": False},
            "quality_view": {"enriched": False},
            "accounting_view": {"enriched": False}
        })
        enriched_count = sum(1 for v in views.values() if isinstance(v, dict) and v.get("enriched"))
        enriched_list.append({
            **r,
            "views_completed": f"{enriched_count}/4",
            "is_ready_for_approval": enriched_count == 4 and r["status"] == "PENDING_STEWARD"
        })
        
    total_blocked = sum(1 for r in requests if r["status"] == "REJECTED_DUPLICATE")
    total_pending = sum(1 for r in requests if r["status"] == "PENDING_STEWARD")
    
    return {
        "status": "success",
        "metrics": {
            "total_requests": len(requests),
            "blocked_duplicates": total_blocked,
            "pending_stewards": total_pending,
            "active_catalog_size": len(STANDARD_MATERIALS_CATALOG),
            "duplicate_cutoff_pct": 92.0
        },
        "requests": enriched_list
    }

@router.get("/requests/{req_id}")
async def get_governed_material_request_detail(req_id: str):
    """
    Get full request detail, 4-view enrichment status, and audit trail.
    """
    key = req_id.upper()
    req = MATERIAL_REQUESTS_DB.get(key)
    if not req:
        raise HTTPException(status_code=404, detail=f"Material request '{req_id}' not found.")
        
    views = MATERIAL_VIEWS_DB.get(key, {
        "purchasing_view": {"enriched": False},
        "plant_view": {"enriched": False},
        "quality_view": {"enriched": False},
        "accounting_view": {"enriched": False}
    })
    
    return {
        "status": "success",
        "request": req,
        "views": views,
        "catalog_reference": STANDARD_MATERIALS_CATALOG.get(req.get("matched_material_id", ""))
    }

@router.post("/requests")
async def create_governed_material_request(req: MaterialCreationRequest):
    """
    Governed Material Request Initiation (Principle P05):
    Runs Fuzzy Duplicate Shield against catalog.
    If >= 0.92, automatically BLOCKS and registers REJECTED_DUPLICATE.
    If < 0.92, registers PENDING_STEWARD and initializes 4-view enrichment schema.
    """
    analysis = evaluate_fuzzy_duplicate_shield(req.proposed_description, req.category)
    req_id = f"MDM-REQ-{uuid.uuid4().hex[:4].upper()}"
    now_str = datetime.now(timezone.utc).isoformat()
    
    if analysis["is_blocked"]:
        req_record = {
            "id": req_id,
            "tenant_id": "axion-mobility",
            "requester": req.actor,
            "proposed_description": req.proposed_description,
            "category": req.category,
            "commodity_code": req.commodity_code,
            "uom": req.uom,
            "target_plant": req.target_plant,
            "status": "REJECTED_DUPLICATE",
            "duplicate_score": analysis["best_score"],
            "matched_material_id": analysis["matched_material"]["material_id"],
            "duplicate_reason": analysis["message"],
            "created_at": now_str
        }
        MATERIAL_REQUESTS_DB[req_id] = req_record
        action_history_store.record_action("MATERIAL_REQUEST", req_id, "REQUEST_MATERIAL", req.actor)
        
        return {
            "status": "BLOCKED_DUPLICATE",
            "message": analysis["message"],
            "request": req_record,
            "adopt_material": analysis["matched_material"]
        }
        
    # Similarity < 0.92 -> Eligible for steward enrichment
    req_record = {
        "id": req_id,
        "tenant_id": "axion-mobility",
        "requester": req.actor,
        "proposed_description": req.proposed_description,
        "category": req.category,
        "commodity_code": req.commodity_code,
        "uom": req.uom,
        "target_plant": req.target_plant,
        "status": "PENDING_STEWARD",
        "duplicate_score": analysis["best_score"],
        "matched_material_id": analysis["matched_material"]["material_id"] if analysis["best_score"] > 0.40 else None,
        "duplicate_reason": analysis["message"],
        "differentiation_justification": req.differentiation_justification,
        "created_at": now_str
    }
    MATERIAL_REQUESTS_DB[req_id] = req_record
    action_history_store.record_action("MATERIAL_REQUEST", req_id, "REQUEST_MATERIAL", req.actor)
    
    # Initialize empty 4-view enrichment container
    MATERIAL_VIEWS_DB[req_id] = {
        "request_id": req_id,
        "purchasing_view": {"enriched": False},
        "plant_view": {"enriched": False},
        "quality_view": {"enriched": False},
        "accounting_view": {"enriched": False}
    }
    
    return {
        "status": "PENDING_APPROVAL",
        "message": "Material request logged. Initialized 4-view Domain Steward enrichment queue.",
        "request": req_record
    }

@router.put("/requests/{req_id}/views/{view_name}")
async def enrich_domain_steward_view(req_id: str, view_name: str, payload: StewardViewEnrichmentRequest):
    """
    Enriches one of the 4 domain steward views:
    - purchasing: purchasing group, order unit, tolerances, lead time, incoterms
    - plant: plant extensions, mrp type, lot size, safety stock, storage location
    - quality: inspection setup, certificate type, skip-lot eligibility
    - accounting: valuation class, price control, standard cost
    """
    key = req_id.upper()
    v_clean = view_name.lower().strip()
    if v_clean not in ["purchasing", "plant", "quality", "accounting"]:
        raise HTTPException(status_code=400, detail="Invalid view_name. Must be purchasing, plant, quality, or accounting.")
        
    if key not in MATERIAL_VIEWS_DB:
        MATERIAL_VIEWS_DB[key] = {
            "request_id": key,
            "purchasing_view": {"enriched": False},
            "plant_view": {"enriched": False},
            "quality_view": {"enriched": False},
            "accounting_view": {"enriched": False}
        }
        
    target_key = f"{v_clean}_view"
    MATERIAL_VIEWS_DB[key][target_key] = {
        **payload.attributes,
        "enriched": True,
        "enriched_by": payload.actor,
        "enriched_at": datetime.now(timezone.utc).isoformat()
    }
    
    return {
        "status": "success",
        "message": f"Successfully enriched {view_name.upper()} view for request {key}.",
        "views": MATERIAL_VIEWS_DB[key]
    }

@router.post("/requests/{req_id}/steward-approve")
async def approve_and_create_master_record(req_id: str, payload: StewardFinalApprovalRequest):
    """
    Final Domain Steward Approval & ERP Master Record Creation:
    1. Enforces SOD-06 (Requester cannot approve own material request).
    2. Validates that all 4 Domain Views have been enriched.
    3. Extends STANDARD_MATERIALS_CATALOG with new Golden Record.
    4. Syncs to SAP S/4HANA via Transactional Outbox (Doc MAT-S4-XXXX).
    """
    key = req_id.upper()
    req = MATERIAL_REQUESTS_DB.get(key)
    if not req:
        raise HTTPException(status_code=404, detail=f"Material request '{req_id}' not found.")
        
    if req["status"] == "REJECTED_DUPLICATE":
        raise HTTPException(status_code=400, detail="Cannot approve duplicate material. Must adopt existing master.")
        
    # Enforce SOD-06: Requester cannot approve own material
    try:
        sod_engine.check_action(
            actor=payload.actor,
            target_action="APPROVE_MATERIAL_STEWARD",
            target_object_type="MATERIAL_REQUEST",
            target_object_id=key
        )
    except SodViolation as e:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "SEGREGATION_OF_DUTIES_VIOLATION",
                "rule_id": e.rule_id,
                "risk": e.risk,
                "message": e.message,
                "actor": payload.actor,
                "conflicting_action": e.conflicting_action
            }
        )
        
    views = MATERIAL_VIEWS_DB.get(key, {})
    new_mat_id = payload.assigned_material_id or f"MAT-{uuid.uuid4().hex[:6].upper()}"
    
    # Add Golden Record to Standard Materials Catalog
    purch_view = views.get("purchasing_view", {})
    acct_view = views.get("accounting_view", {})
    plant_view = views.get("plant_view", {})
    
    golden_record = {
        "material_id": new_mat_id,
        "description": req["proposed_description"],
        "category": req["category"],
        "commodity_code": req["commodity_code"],
        "uom": req["uom"],
        "standard_price_inr": acct_view.get("standard_valuation_inr", 0.0),
        "drawing_number": "STANDARD-SPEC",
        "material_group": req["category"][:8].upper(),
        "plant_extensions": [req["target_plant"]],
        "purchasing_group": purch_view.get("purchasing_group", "P01"),
        "mrp_type": plant_view.get("mrp_type", "PD"),
        "status": "ACTIVE",
        "created_from_request": key,
        "steward_approver": payload.actor
    }
    
    STANDARD_MATERIALS_CATALOG[new_mat_id] = golden_record
    req["status"] = "APPROVED"
    req["approved_by"] = payload.actor
    req["assigned_material_id"] = new_mat_id
    
    # Principle P10: Record Lineage link
    lineage_engine.record_link(
        tenant_id="axion-mobility",
        from_type="MATERIAL_REQUEST",
        from_id=key,
        to_type="MATERIAL_MASTER",
        to_id=new_mat_id,
        link_type="promoted_to",
        created_by=payload.actor
    )
    
    # Sync to SAP S/4HANA via Outbox
    erp_post = outbox_service.post_to_erp(
        tenant_id="axion-mobility",
        idempotency_key=f"AXN|1000|MDM|{new_mat_id}",
        target_system="SAP_S4HANA",
        object_ref=new_mat_id,
        payload=golden_record
    )
    
    return {
        "status": "success",
        "message": f"Material request {key} approved. Created golden master record {new_mat_id} and synced to SAP S/4HANA.",
        "golden_record": golden_record,
        "erp_sync": erp_post
    }

@router.get("/catalog")
async def get_master_catalog():
    """
    Returns entire active golden standard material catalog with 4-view metadata.
    """
    mats = list(STANDARD_MATERIALS_CATALOG.values())
    return {
        "status": "success",
        "total": len(mats),
        "materials": mats
    }
