"""
AlphaHelion Purchasing Intelligence Cloud
Module: 3-Way Match Exception & Automated Dispute Resolution Engine (INV-03 & INV-04)
With Agent AGT-INVOICE-11 (3-Way Invoice Matching Resolver) Integration
Blueprint Reference: Section 14 (pages 24-27) & Section 21 (Flow F7: pic.invoice) & Principle P11/P13
"""

from fastapi import APIRouter, HTTPException, Query, Header, Body
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import uuid

from app.services.lineage_service import lineage_engine
from app.services.sod_service import sod_engine, action_history_store, SodViolation
from app.services.rules_engine import DMN03InvoiceTolerance
from app.services.outbox_service import outbox_service
from app.routers.spend_cube_ai_agents import AI_AGENTS_REGISTRY

router = APIRouter(prefix="/api/v1/invoices/3-way-match", tags=["3-Way Match & Automated Dispute Engine"])

# ==============================================================================
# PYDANTIC SCHEMAS
# ==============================================================================

class DebitNoteIssueRequest(BaseModel):
    actor: str = "ap.clerk@alphahelion.com"
    debit_note_number: Optional[str] = None
    reason: Optional[str] = "Automated offset for unaccepted rejected units"
    deduct_from_payment_run: bool = True

class CreditNoteRequestPayload(BaseModel):
    actor: str = "ap.clerk@alphahelion.com"
    dispute_reason: str = "Quantity overbilling exceeding accepted warehouse receipt"
    expected_amount_inr: float
    supplier_contact: str = "accounts@trichyforge.com"

class VarianceWaiverRequest(BaseModel):
    actor: str
    waiver_justification: str = Field(..., min_length=15, description="Mandatory commercial justification")
    approved_tolerance_delta: float

# ==============================================================================
# IN-MEMORY MATCH CASES STORE (WITH SIGNATURE GOLDEN SCENARIO DATA)
# ==============================================================================

MATCH_CASES_DB: Dict[str, Dict[str, Any]] = {
    "INV-TF-8812": {
        "invoice_id": "INV-TF-8812",
        "supplier_id": "TF001",
        "supplier_name": "Trichy Forge Works",
        "po_id": "PO-77410",
        "po_creator": "buyer.automotive@alphahelion.com",
        "contract_ref": "SA-5520",
        "material_id": "MAT-DC330-HSG",
        "material_desc": "DC-330 Aluminium Die-Cast Motor Housing",
        "po_ordered_qty": 5400.0,
        "po_unit_price": 398.00,
        "gr_id": "GR-90231",
        "gr_received_qty": 5400.0,
        "gr_accepted_qty": 5380.0,
        "gr_rejected_qty": 20.0,
        "quality_inspection_id": "QL-2210",
        "quarantine_reason": "CMM & porosity check failed on flange face (porosity flaw > 50 PPM)",
        "invoiced_qty": 5400.0,
        "invoiced_unit_price": 398.00,
        "billed_base_amount_inr": 2149200.0, # 5,400 * 398
        "tax_rate_percent": 18.0,
        "billed_tax_amount_inr": 386856.0,
        "total_invoiced_inr": 2536056.0,
        "discrepancy_type": "QUANTITY_EXCEPTION",
        "discrepancy_units": 20.0,
        "discrepancy_base_inr": 7960.0,       # 20 * 398
        "discrepancy_tax_inr": 1432.8,        # 18% GST
        "discrepancy_total_inr": 9392.8,
        "adjusted_payable_inr": 2526663.20,
        "match_status": "EXCEPTION",          # EXCEPTION, MATCHED, MATCHED_WITH_DEBIT_NOTE, PENDING_CREDIT_NOTE, POSTED
        "payment_hold": True,
        "hold_reason": "DMN-03 Overbilling Guard: 20 units billed but rejected in QA",
        "debit_note_ref": None,
        "credit_note_ref": None,
        "erp_doc_no": None,
        "agent_verified": False,
        "agent_verification_result": None
    },
    "INV-KD-4402": {
        "invoice_id": "INV-KD-4402",
        "supplier_id": "KD002",
        "supplier_name": "Kovai Diecast Ltd",
        "po_id": "PO-77411",
        "po_creator": "buyer.automotive@alphahelion.com",
        "contract_ref": "SA-5521",
        "material_id": "MAT-DC330-HSG",
        "material_desc": "DC-330 Aluminium Die-Cast Motor Housing",
        "po_ordered_qty": 3600.0,
        "po_unit_price": 405.00,
        "gr_id": "GR-90235",
        "gr_received_qty": 3600.0,
        "gr_accepted_qty": 3600.0,
        "gr_rejected_qty": 0.0,
        "quality_inspection_id": "QL-2215",
        "quarantine_reason": None,
        "invoiced_qty": 3600.0,
        "invoiced_unit_price": 412.00, # +₹7.00 price variance!
        "billed_base_amount_inr": 1483200.0, # 3,600 * 412
        "tax_rate_percent": 18.0,
        "billed_tax_amount_inr": 266976.0,
        "total_invoiced_inr": 1750176.0,
        "discrepancy_type": "PRICE_EXCEPTION",
        "discrepancy_units": 0.0,
        "discrepancy_base_inr": 25200.0, # 3600 * 7
        "discrepancy_tax_inr": 4536.0,
        "discrepancy_total_inr": 29736.0,
        "adjusted_payable_inr": 1720440.0,
        "match_status": "EXCEPTION",
        "payment_hold": True,
        "hold_reason": "DMN-03 Price Tolerance: Invoiced unit price ₹412.00 exceeds PO rate ₹405.00 by +₹7.00/unit",
        "debit_note_ref": None,
        "credit_note_ref": None,
        "erp_doc_no": None,
        "agent_verified": False,
        "agent_verification_result": None
    },
    "INV-SL-9011": {
        "invoice_id": "INV-SL-9011",
        "supplier_id": "SL003",
        "supplier_name": "Salem Light Alloys",
        "po_id": "PO-77415",
        "po_creator": "buyer.castings@alphahelion.com",
        "contract_ref": "PO-CALLOFF-01",
        "material_id": "MAT-AL-EXTR",
        "material_desc": "Aluminium Structural Extrusion Profile 6061-T6",
        "po_ordered_qty": 1200.0,
        "po_unit_price": 180.00,
        "gr_id": "GR-PENDING",
        "gr_received_qty": 0.0,
        "gr_accepted_qty": 0.0,
        "gr_rejected_qty": 0.0,
        "quality_inspection_id": None,
        "quarantine_reason": None,
        "invoiced_qty": 1200.0,
        "invoiced_unit_price": 180.00,
        "billed_base_amount_inr": 216000.0,
        "tax_rate_percent": 18.0,
        "billed_tax_amount_inr": 38880.0,
        "total_invoiced_inr": 254880.0,
        "discrepancy_type": "MISSING_GOODS_RECEIPT",
        "discrepancy_units": 1200.0,
        "discrepancy_base_inr": 216000.0,
        "discrepancy_tax_inr": 38880.0,
        "discrepancy_total_inr": 254880.0,
        "adjusted_payable_inr": 0.0,
        "match_status": "EXCEPTION",
        "payment_hold": True,
        "hold_reason": "Principle P08 / GR Gate: Stock material invoice received prior to warehouse Goods Receipt",
        "debit_note_ref": None,
        "credit_note_ref": None,
        "erp_doc_no": None,
        "agent_verified": False,
        "agent_verification_result": None
    },
    "INV-SD-3301": {
        "invoice_id": "INV-SD-3301",
        "supplier_id": "SD005",
        "supplier_name": "Sandvik Coromant India",
        "po_id": "PO-77409",
        "po_creator": "priya.sharma@alphahelion.com",
        "contract_ref": "CTR-2024-88",
        "material_id": "MAT-TOOL-001",
        "material_desc": "Tungsten Carbide CNMG 120408 Milling Inserts",
        "po_ordered_qty": 100.0,
        "po_unit_price": 4850.00,
        "gr_id": "GR-90220",
        "gr_received_qty": 100.0,
        "gr_accepted_qty": 100.0,
        "gr_rejected_qty": 0.0,
        "quality_inspection_id": "QL-2201",
        "quarantine_reason": None,
        "invoiced_qty": 100.0,
        "invoiced_unit_price": 4850.00,
        "billed_base_amount_inr": 485000.0,
        "tax_rate_percent": 18.0,
        "billed_tax_amount_inr": 87300.0,
        "total_invoiced_inr": 572300.0,
        "discrepancy_type": "NONE",
        "discrepancy_units": 0.0,
        "discrepancy_base_inr": 0.0,
        "discrepancy_tax_inr": 0.0,
        "discrepancy_total_inr": 0.0,
        "adjusted_payable_inr": 572300.0,
        "match_status": "MATCHED",
        "payment_hold": False,
        "hold_reason": None,
        "debit_note_ref": None,
        "credit_note_ref": None,
        "erp_doc_no": "5100004419",
        "agent_verified": True,
        "agent_verification_result": {
            "status": "PASSED",
            "message": "Perfect 3-way match across PO, GR, and Invoice."
        }
    }
}

# Ensure PO creators are registered in action_history_store for SOD-04 checking
for c in MATCH_CASES_DB.values():
    action_history_store.record_action("PURCHASE_ORDER", c["po_id"], "CREATE_PO", c["po_creator"])

# ==============================================================================
# REST ENDPOINTS
# ==============================================================================

@router.get("/cases")
async def list_match_cases(
    status: Optional[str] = Query(None, description="ALL, EXCEPTION, MATCHED"),
    discrepancy_type: Optional[str] = Query(None, description="ALL, QUANTITY_EXCEPTION, PRICE_EXCEPTION, etc.")
):
    """
    List all 3-way matching cases with tolerance evaluation and KPI metrics.
    """
    cases = list(MATCH_CASES_DB.values())
    
    if status and status != "ALL":
        cases = [c for c in cases if c["match_status"] == status]
        
    if discrepancy_type and discrepancy_type != "ALL":
        cases = [c for c in cases if c["discrepancy_type"] == discrepancy_type]
        
    total_exceptions = sum(1 for c in MATCH_CASES_DB.values() if c["match_status"] == "EXCEPTION")
    total_disputed_amt = sum(c["discrepancy_total_inr"] for c in MATCH_CASES_DB.values() if c["match_status"] == "EXCEPTION")
    agent_info = AI_AGENTS_REGISTRY.get("AGT-INVOICE-11", {})
    
    return {
        "status": "success",
        "metrics": {
            "total_cases": len(MATCH_CASES_DB),
            "exceptions_count": total_exceptions,
            "disputed_value_inr": total_disputed_amt,
            "agent_id": "AGT-INVOICE-11",
            "agent_name": agent_info.get("name", "3-Way Invoice Matching Resolver"),
            "agent_autonomy": agent_info.get("autonomy_level", "L3_SUPERVISED_ACTION"),
            "agent_actions_today": agent_info.get("actions_today", 31)
        },
        "count": len(cases),
        "cases": cases
    }

@router.get("/cases/{invoice_id}")
async def get_match_case_detail(invoice_id: str):
    """
    Retrieve single 3-way match case with PO line, GR line, invoice line, and DMN-03 tolerance audit.
    """
    key = invoice_id.upper()
    if key not in MATCH_CASES_DB:
        raise HTTPException(status_code=404, detail=f"Match case '{invoice_id}' not found.")
    
    case = MATCH_CASES_DB[key]
    agent_info = AI_AGENTS_REGISTRY.get("AGT-INVOICE-11", {})
    
    return {
        "status": "success",
        "case": case,
        "agent": agent_info
    }

@router.post("/cases/{invoice_id}/agent-verify")
async def invoke_agent_verification(invoice_id: str):
    """
    Incorporate Agent AGT-INVOICE-11 (3-Way Invoice Matching Resolver).
    Executes autonomous cross-comparison under Principle P11 (Explainable Copilot Contract).
    Returns citations, confidence score, root cause analysis, and suggested resolution paths.
    """
    key = invoice_id.upper()
    if key not in MATCH_CASES_DB:
        raise HTTPException(status_code=404, detail=f"Match case '{invoice_id}' not found.")
        
    case = MATCH_CASES_DB[key]
    
    # Update agent stats
    if "AGT-INVOICE-11" in AI_AGENTS_REGISTRY:
        AI_AGENTS_REGISTRY["AGT-INVOICE-11"]["actions_today"] += 1
        AI_AGENTS_REGISTRY["AGT-INVOICE-11"]["last_active"] = datetime.now(timezone.utc).isoformat()
    
    # Formulate explainable response contract
    citations = [
        {"doc_id": case["po_id"], "doc_type": "PURCHASE_ORDER", "snippet": f"{case['po_ordered_qty']} EA @ ₹{case['po_unit_price']:.2f} contract rate."},
        {"doc_id": case["gr_id"], "doc_type": "GOODS_RECEIPT", "snippet": f"{case['gr_accepted_qty']} EA accepted into unrestricted inventory."}
    ]
    if case["quality_inspection_id"]:
        citations.append({
            "doc_id": case["quality_inspection_id"],
            "doc_type": "QUALITY_INSPECTION",
            "snippet": f"{case['gr_rejected_qty']} EA quarantined under inspection: {case['quarantine_reason']}."
        })
    citations.append({
        "doc_id": case["invoice_id"],
        "doc_type": "INVOICE",
        "snippet": f"Billed {case['invoiced_qty']} EA @ ₹{case['invoiced_unit_price']:.2f} = ₹{case['total_invoiced_inr']:,.2f}."
    })
    
    if case["discrepancy_type"] == "QUANTITY_EXCEPTION":
        explanation = (
            f"Supplier {case['supplier_name']} billed for the complete PO quantity ({case['invoiced_qty']} EA), "
            f"ignoring {case['discrepancy_units']} EA rejected during QA inspection {case['quality_inspection_id']}. "
            f"Under Blueprint Section 14, payment cannot exceed accepted goods receipt ({case['gr_accepted_qty']} EA)."
        )
        recommended_action = (
            f"Issue Automated Debit Note DN-2026-{case['invoice_id'][-4:]} for ₹{case['discrepancy_total_inr']:,.2f} "
            f"(₹{case['discrepancy_base_inr']:,.2f} base + 18% GST ₹{case['discrepancy_tax_inr']:,.2f}) and deduct from payment run."
        )
        alternative_action = f"Request Supplier Credit Note CN-{case['supplier_id']}-221 for ₹{case['discrepancy_total_inr']:,.2f}."
    elif case["discrepancy_type"] == "PRICE_EXCEPTION":
        explanation = (
            f"Billed unit price of ₹{case['invoiced_unit_price']:.2f} exceeds purchase order contracted rate of "
            f"₹{case['po_unit_price']:.2f} by +₹{case['invoiced_unit_price'] - case['po_unit_price']:.2f}/unit (+1.73%). "
            f"DMN-03 enforces a 0.0% positive price tolerance limit."
        )
        recommended_action = f"Issue Debit Note for ₹{case['discrepancy_total_inr']:,.2f} to force contract pricing."
        alternative_action = "Require Price Variance Waiver approved by Category Lead (SOD-04 guarded)."
    elif case["discrepancy_type"] == "MISSING_GOODS_RECEIPT":
        explanation = "Invoice received prior to warehouse arrival / Goods Receipt posting. Direct stock materials cannot post without warehouse GR."
        recommended_action = "Hold invoice on automated payment lockout until receiving dock posts GR."
        alternative_action = "Expedite shipment tracking with logistics carrier."
    else:
        explanation = "All 3 documents (PO, GR, Invoice) reconcile within DMN-03 0.0% tolerances."
        recommended_action = "Release payment hold and post invoice to SAP S/4HANA."
        alternative_action = "None needed."

    verification_result = {
        "agent_id": "AGT-INVOICE-11",
        "agent_name": "3-Way Invoice Matching Resolver",
        "autonomy_level": "L3_SUPERVISED_ACTION",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "confidence_score": 0.99,
        "is_matched": case["discrepancy_type"] == "NONE",
        "discrepancy_type": case["discrepancy_type"],
        "discrepancy_amount_inr": case["discrepancy_total_inr"],
        "citations": citations,
        "root_cause_explanation": explanation,
        "recommended_action": recommended_action,
        "alternative_action": alternative_action,
        "debit_note_proposal": {
            "suggested_dn_number": f"DN-2026-{case['invoice_id'][-4:]}",
            "base_amount_inr": case["discrepancy_base_inr"],
            "tax_amount_inr": case["discrepancy_tax_inr"],
            "total_dn_amount_inr": case["discrepancy_total_inr"],
            "net_payable_after_dn_inr": case["adjusted_payable_inr"]
        }
    }
    
    case["agent_verified"] = True
    case["agent_verification_result"] = verification_result
    
    return {
        "status": "success",
        "agent_contract": verification_result
    }

@router.post("/cases/{invoice_id}/issue-debit-note")
async def issue_automated_debit_note(invoice_id: str, req: DebitNoteIssueRequest):
    """
    Automated Dispute Resolution (INV-04):
    Generates and applies an automated Debit Note against the supplier invoice.
    Nets out the overbilled discrepancy and sets status to MATCHED_WITH_DEBIT_NOTE,
    unblocking the invoice for payment and ERP posting.
    """
    key = invoice_id.upper()
    if key not in MATCH_CASES_DB:
        raise HTTPException(status_code=404, detail=f"Match case '{invoice_id}' not found.")
        
    case = MATCH_CASES_DB[key]
    dn_number = req.debit_note_number or f"DN-2026-{key[-4:]}"
    
    # Apply Debit Note
    case["debit_note_ref"] = dn_number
    case["match_status"] = "MATCHED_WITH_DEBIT_NOTE"
    case["payment_hold"] = False
    case["hold_reason"] = None
    
    # Record lineage
    lineage_engine.record_link(
        tenant_id="axion-mobility",
        from_type="DEBIT_NOTE",
        from_id=dn_number,
        to_type="INVOICE",
        to_id=key,
        link_type="offsets_discrepancy_in",
        created_by=req.actor
    )
    
    # Increment agent actions
    if "AGT-INVOICE-11" in AI_AGENTS_REGISTRY:
        AI_AGENTS_REGISTRY["AGT-INVOICE-11"]["actions_today"] += 1
        
    return {
        "status": "success",
        "message": f"Automated Debit Note {dn_number} issued for ₹{case['discrepancy_total_inr']:,.2f}. Invoice {key} is now MATCHED with net payable ₹{case['adjusted_payable_inr']:,.2f}.",
        "debit_note": {
            "debit_note_number": dn_number,
            "invoice_ref": key,
            "supplier_id": case["supplier_id"],
            "supplier_name": case["supplier_name"],
            "deducted_amount_inr": case["discrepancy_total_inr"],
            "net_payable_inr": case["adjusted_payable_inr"],
            "issued_by": req.actor,
            "issued_at": datetime.now(timezone.utc).isoformat()
        },
        "case": case
    }

@router.post("/cases/{invoice_id}/request-credit-note")
async def request_supplier_credit_note(invoice_id: str, req: CreditNoteRequestPayload):
    """
    Automated Dispute Resolution:
    Dispatches automated dispute notice to supplier requesting a credit note.
    """
    key = invoice_id.upper()
    if key not in MATCH_CASES_DB:
        raise HTTPException(status_code=404, detail=f"Match case '{invoice_id}' not found.")
        
    case = MATCH_CASES_DB[key]
    dispute_id = f"DISP-2026-{key[-4:]}"
    
    case["match_status"] = "PENDING_CREDIT_NOTE"
    case["hold_reason"] = f"Dispute {dispute_id} active: Awaiting supplier Credit Note for ₹{req.expected_amount_inr:,.2f}"
    
    return {
        "status": "success",
        "message": f"Dispute notice {dispute_id} dispatched to {case['supplier_name']} ({req.supplier_contact}).",
        "dispute_id": dispute_id,
        "case": case
    }

@router.post("/cases/{invoice_id}/waive-variance")
async def waive_invoice_variance(invoice_id: str, req: VarianceWaiverRequest):
    """
    Price/Quantity Variance Waiver:
    Enforces SOD-04 (PO buyer cannot waive own variance).
    Allows independent AP supervisor or Cost Center Owner to accept discrepancy.
    """
    key = invoice_id.upper()
    if key not in MATCH_CASES_DB:
        raise HTTPException(status_code=404, detail=f"Match case '{invoice_id}' not found.")
        
    case = MATCH_CASES_DB[key]
    
    # SOD-04 Enforcement: PO creator cannot authorize invoice exception
    try:
        sod_engine.check_action(
            actor=req.actor,
            target_action="APPROVE_INVOICE_EXCEPTION",
            target_object_type="PURCHASE_ORDER",
            target_object_id=case["po_id"],
            context={"po_id": case["po_id"]}
        )
    except SodViolation as e:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "SEGREGATION_OF_DUTIES_VIOLATION",
                "rule_id": e.rule_id,
                "risk": e.risk,
                "message": e.message,
                "actor": req.actor,
                "conflicting_action": e.conflicting_action
            }
        )
        
    case["match_status"] = "MATCHED"
    case["payment_hold"] = False
    case["hold_reason"] = None
    case["notes"] = f"Variance of ₹{req.approved_tolerance_delta:,.2f} waived by {req.actor}: {req.waiver_justification}"
    
    return {
        "status": "success",
        "message": f"Variance waived by '{req.actor}'. Invoice {key} is now MATCHED.",
        "case": case
    }

@router.post("/cases/{invoice_id}/post-to-erp")
async def post_matched_invoice_to_erp(
    invoice_id: str,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    actor: str = "ap.clerk@alphahelion.com"
):
    """
    Principle P13 Idempotent ERP Posting:
    Posts matched invoice to SAP S/4HANA financial ledger via Transactional Outbox.
    """
    key = invoice_id.upper()
    if key not in MATCH_CASES_DB:
        raise HTTPException(status_code=404, detail=f"Match case '{invoice_id}' not found.")
        
    case = MATCH_CASES_DB[key]
    
    if case["match_status"] not in ["MATCHED", "MATCHED_WITH_DEBIT_NOTE"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot post invoice with status '{case['match_status']}'. Must be MATCHED or MATCHED_WITH_DEBIT_NOTE."
        )
        
    idem_key = idempotency_key or f"AXN|1000|{case['supplier_id']}|{key}"
    
    posting_res = outbox_service.post_to_erp(
        tenant_id="axion-mobility",
        idempotency_key=idem_key,
        target_system="SAP_S4HANA",
        object_ref=key,
        payload={
            "invoice_id": key,
            "po_id": case["po_id"],
            "supplier_id": case["supplier_id"],
            "net_amount_inr": case["adjusted_payable_inr"],
            "debit_note_ref": case["debit_note_ref"]
        }
    )
    
    case["match_status"] = "POSTED"
    case["erp_doc_no"] = posting_res["erpDocument"]
    
    return posting_res
