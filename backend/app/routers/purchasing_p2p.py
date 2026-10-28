"""
AlphaHelion Purchasing Intelligence Cloud — Operational P2P Router
Covers Modules:
- M04: Requisitioning & Guided Buying (REQ-01..04)
- M08: Operational Purchasing / POs (PO-01..04)
- M09: Supplier Fulfilment, Goods Receipt & Service Entry (RCV-01..04)
- M10: Invoice Matching & Finance Integration (INV-01..04)
With full integration into:
- Lineage Model (P10)
- SoD Command-Time Validator (SOD-01..07)
- DMN Decision Tables (DMN-01, DMN-02, DMN-03)
- Transactional Outbox & Idempotent ERP posting (P13)
"""

from fastapi import APIRouter, HTTPException, Header, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import uuid

from app.services.lineage_service import lineage_engine
from app.services.sod_service import sod_engine, action_history_store, SodViolation
from app.services.rules_engine import (
    DMN01RequisitionRule,
    DMN02TouchlessPO,
    DMN03InvoiceTolerance,
    PORiskScoreCalculator
)
from app.services.outbox_service import outbox_service

router = APIRouter(prefix="/api/v1/p2p", tags=["Operational P2P"])

# -------------------------------------------------------------
# In-Memory Master Data & Databases
# -------------------------------------------------------------

CATALOGUE_DB = [
    {
        "sku": "MAT-300118",
        "name": "M8 Hex Bolt Zinc Plated 30mm",
        "category": "Fasteners & Hardware",
        "channel": "CATALOGUE",
        "supplier_id": "SUP-FAST-01",
        "supplier_name": "Fastenal Global",
        "contract_ref": "FA-2201",
        "unit_price_inr": 4.00,
        "uom": "PC",
        "lead_time_days": 2
    },
    {
        "sku": "MAT-DC330-HSG",
        "name": "DC-330 Aluminium Die-Cast Housing",
        "category": "Castings & Forgings",
        "channel": "CONTRACT",
        "supplier_id": "TF001",
        "supplier_name": "Trichy Forge Works",
        "contract_ref": "SA-5520",
        "unit_price_inr": 398.00,
        "uom": "EA",
        "lead_time_days": 21
    },
    {
        "sku": "MAT-TOOL-441",
        "name": "Carbide Endmill 12mm 4-Flute",
        "category": "Tooling & Inserts",
        "channel": "MATERIAL_MASTER",
        "supplier_id": "SUP-KENN-05",
        "supplier_name": "Kennametal India",
        "contract_ref": None,
        "unit_price_inr": 1850.00,
        "uom": "PC",
        "lead_time_days": 7
    }
]

REQUISITIONS_DB: Dict[str, Dict[str, Any]] = {
    "REQ-2311": {
        "id": "REQ-2311",
        "tenant_id": "axion-mobility",
        "origin": "MRP",
        "planned_order_ref": "PLO-55821",
        "purpose_code": "DIRECT_PRODUCTION",
        "requester": "u:mrp.planner.hosur",
        "status": "APPROVED",
        "company_code": "1000",
        "plant": "P100 Hosur",
        "created_at": "2026-10-21T08:30:00Z",
        "lines": [
            {
                "line_no": 10,
                "item_type": "STOCK_MATERIAL",
                "material_id": "MAT-DC330-HSG",
                "description": "DC-330 Aluminium Die-Cast Housing",
                "material_group": "CASTING-ALU",
                "qty": 5400,
                "uom": "EA",
                "price_estimate": 398.00,
                "account_assignment": {"type": "INVENTORY", "id": "INV-P100"},
                "need_date": "2026-11-12",
                "contract_ref": "SA-5520",
                "supplier_id": "TF001",
                "supplier_name": "Trichy Forge Works"
            }
        ],
        "approvals": [
            {"role": "MRP Controller", "actor": "u:mrp.planner.hosur", "status": "APPROVED", "timestamp": "2026-10-21T08:31:00Z"}
        ]
    }
}

PURCHASE_ORDERS_DB: Dict[str, Dict[str, Any]] = {
    "PO-77410": {
        "id": "PO-77410",
        "tenant_id": "axion-mobility",
        "version": 1,
        "status": "CONFIRMED",
        "supplier_id": "TF001",
        "supplier_name": "Trichy Forge Works",
        "company_code": "1000",
        "plant": "P100 Hosur",
        "purch_org": "1000",
        "contract_ref": "SA-5520",
        "payment_terms": "N60",
        "incoterms": "FCA Trichy",
        "currency": "INR",
        "total_amount_inr": 2149200.0,  # 5400 * 398
        "risk_score": 18,
        "touchless": True,
        "validation_factors": [
            {"code": "LATE_RISK_MED", "points": 18, "evidence": "AI model eta-v3 predicted late probability 0.22"}
        ],
        "created_at": "2026-10-21T09:15:00Z",
        "created_by": "Touchless PO Agent (L4)",
        "lines": [
            {
                "line_no": 10,
                "material_id": "MAT-DC330-HSG",
                "description": "DC-330 Aluminium Die-Cast Housing",
                "qty": 5400,
                "uom": "EA",
                "unit_price": 398.00,
                "total_price": 2149200.0,
                "delivery_date": "2026-11-12",
                "gr_required": True,
                "ir_required": True,
                "tolerance_profile": {"over_pct": 2.0, "under_pct": 5.0}
            }
        ]
    }
}

# Pre-record lineage for PO-77410
lineage_engine.record_link(
    tenant_id="axion-mobility",
    from_type="PLANNED_ORDER",
    from_id="PLO-55821",
    to_type="REQUISITION",
    to_id="REQ-2311",
    link_type="converted_from",
    created_by="mrp_engine"
)
lineage_engine.record_link(
    tenant_id="axion-mobility",
    from_type="REQUISITION",
    from_id="REQ-2311",
    to_type="PURCHASE_ORDER",
    to_id="PO-77410",
    link_type="ordered_from",
    created_by="Touchless PO Agent (L4)"
)
lineage_engine.record_link(
    tenant_id="axion-mobility",
    from_type="CONTRACT",
    from_id="SA-5520",
    to_type="PURCHASE_ORDER",
    to_id="PO-77410",
    link_type="priced_by_contract",
    created_by="Touchless PO Agent (L4)"
)
action_history_store.record_action("PURCHASE_ORDER", "PO-77410", "CREATE_PO", "Touchless PO Agent (L4)")

ASNS_DB: Dict[str, Dict[str, Any]] = {
    "ASN-61208": {
        "id": "ASN-61208",
        "tenant_id": "axion-mobility",
        "po_id": "PO-77410",
        "supplier_id": "TF001",
        "supplier_name": "Trichy Forge Works",
        "carrier": "VRL Logistics Express",
        "tracking_no": "VRL-TN-88291",
        "shipped_date": "2026-10-21",
        "expected_arrival": "2026-10-22",
        "status": "DELIVERED",
        "lines": [
            {"line_no": 10, "po_line_ref": 10, "qty_shipped": 5400, "batch_number": "BATCH-TF-2026-99", "coc_doc": "COC-TF-4412"}
        ]
    }
}
lineage_engine.record_link(
    tenant_id="axion-mobility",
    from_type="PURCHASE_ORDER",
    from_id="PO-77410",
    to_type="ASN",
    to_id="ASN-61208",
    link_type="shipped_against",
    created_by="u:trichy.dispatch"
)

GOODS_RECEIPTS_DB: Dict[str, Dict[str, Any]] = {
    "GR-90231": {
        "id": "GR-90231",
        "tenant_id": "axion-mobility",
        "po_id": "PO-77410",
        "asn_id": "ASN-61208",
        "receiver": "u:store.keeper.hosur",
        "received_at": "2026-10-22T06:45:00Z",
        "status": "ACCEPTED_WITH_REJECTION",
        "total_received": 5400,
        "total_accepted": 5380,
        "total_rejected": 20,
        "rejection_reason": "Gas porosity detected on internal bore during ultrasonic NDT (Inspection Report #QL-2210)",
        "quality_doc": "QL-2210",
        "lines": [
            {
                "line_no": 10,
                "po_line_ref": 10,
                "material_id": "MAT-DC330-HSG",
                "qty_received": 5400,
                "qty_accepted": 5380,
                "qty_rejected": 20,
                "unit_price": 398.00
            }
        ]
    }
}
lineage_engine.record_link(
    tenant_id="axion-mobility",
    from_type="PURCHASE_ORDER",
    from_id="PO-77410",
    to_type="GOODS_RECEIPT",
    to_id="GR-90231",
    link_type="received_against",
    created_by="u:store.keeper.hosur"
)
action_history_store.record_action("PURCHASE_ORDER", "PO-77410", "POST_GR", "u:store.keeper.hosur")

INVOICES_DB: Dict[str, Dict[str, Any]] = {
    "INV-TF-8812": {
        "id": "INV-TF-8812",
        "tenant_id": "axion-mobility",
        "supplier_id": "TF001",
        "supplier_name": "Trichy Forge Works",
        "supplier_invoice_no": "INV-TF-8812",
        "po_id": "PO-77410",
        "company_code": "1000",
        "fiscal_year": "2026",
        "billed_amount_inr": 2149200.0,  # 5400 units * 398 INR
        "tax_amount_inr": 386856.0,      # 18% GST
        "total_invoiced_inr": 2536056.0,
        "gst_irn": "9a38f72c10b83e47a988d01124f",
        "status": "EXCEPTION",
        "match_type": "3-WAY",
        "match_result": {
            "status": "EXCEPTION",
            "is_matched": False,
            "exceptions": [
                {
                    "type": "QUANTITY_EXCEPTION",
                    "delta": 20.0,
                    "detail": "Billed 5,400 units vs 5,380 accepted goods receipt. 20 units rejected under QL-2210."
                }
            ],
            "suggested_actions": ["Request Credit Note CN-TF-221 for 20 units (₹7,960 + GST)."]
        },
        "credit_note_ref": None,
        "erp_doc_no": None,
        "payment_status": "BLOCKED_ON_EXCEPTION",
        "lines": [
            {
                "line_no": 10,
                "po_line_ref": 10,
                "material_id": "MAT-DC330-HSG",
                "billed_qty": 5400,
                "billed_unit_price": 398.00,
                "line_total": 2149200.0
            }
        ]
    }
}
lineage_engine.record_link(
    tenant_id="axion-mobility",
    from_type="PURCHASE_ORDER",
    from_id="PO-77410",
    to_type="INVOICE",
    to_id="INV-TF-8812",
    link_type="invoiced_against",
    created_by="u:trichy.accounts"
)

# -------------------------------------------------------------
# Pydantic Request Models
# -------------------------------------------------------------

class GuidedSearchRequest(BaseModel):
    query: str
    tenant_id: str = "axion-mobility"

class PRCreateRequest(BaseModel):
    tenant_id: str = "axion-mobility"
    origin: str = "MANUAL"  # "MRP" | "MANUAL" | "PROJECT" | "CATALOGUE"
    planned_order_ref: Optional[str] = None
    purpose_code: str = "DIRECT_PRODUCTION"
    requester: str = "u:buyer.officer"
    company_code: str = "1000"
    plant: str = "P100 Hosur"
    lines: List[Dict[str, Any]]

class POCreateFromPRRequest(BaseModel):
    pr_id: str
    pr_lines: List[int]
    supplier_id: str
    contract_ref: Optional[str] = None
    actor: str = "u:buyer.officer"

class POValidationRequest(BaseModel):
    po_id: str
    late_delivery_prob: float = 0.22
    has_split_pattern: bool = False
    touchless_band_max: float = 5000000.0  # 50 Lakhs INR

class GoodsReceiptPostRequest(BaseModel):
    po_id: str
    asn_id: Optional[str] = None
    receiver: str = "u:store.keeper.hosur"
    received_lines: List[Dict[str, Any]]  # [{po_line_ref, qty_received, qty_accepted, qty_rejected, rejection_reason}]
    quality_doc: Optional[str] = None

class ServiceEntrySheetRequest(BaseModel):
    po_id: str
    po_line_ref: int = 10
    service_description: str
    progress_pct: float
    amount_inr: float
    service_owner: str = "u:plant.engineer"
    actor: str = "u:plant.engineer"

class InvoiceCaptureRequest(BaseModel):
    supplier_id: str
    supplier_name: str
    supplier_invoice_no: str
    po_id: str
    billed_amount_inr: float
    tax_amount_inr: float
    gst_irn: str
    lines: List[Dict[str, Any]]

class InvoiceResolveExceptionRequest(BaseModel):
    resolution_type: str = "CREDIT_NOTE"  # "CREDIT_NOTE" | "ACCEPT_VARIANCE" | "DISPUTE"
    credit_note_number: str
    credit_note_amount_inr: float
    notes: str
    actor: str = "u:ap.clerk.2"

# -------------------------------------------------------------
# Module M04: Requisitioning & Guided Buying Endpoints
# -------------------------------------------------------------

@router.post("/guided-buying/search")
def guided_buying_search(payload: GuidedSearchRequest):
    """
    Enforces Principle P03: Search Order Hierarchy
    Contract Item -> Internal Catalogue -> Material Master -> Free-Text
    """
    q = payload.query.lower().strip()
    results = {"contract_items": [], "catalogue_items": [], "material_master": [], "free_text_allowed": True}

    for item in CATALOGUE_DB:
        if q in item["name"].lower() or q in item["sku"].lower() or q in item["category"].lower():
            if item["channel"] == "CONTRACT":
                results["contract_items"].append(item)
            elif item["channel"] == "CATALOGUE":
                results["catalogue_items"].append(item)
            else:
                results["material_master"].append(item)

    return {
        "status": "success",
        "search_hierarchy": ["CONTRACT_ITEM", "CATALOGUE_ITEM", "MATERIAL_MASTER", "FREE_TEXT"],
        "results": results
    }

@router.post("/requisitions")
def create_requisition(payload: PRCreateRequest):
    """
    Creates a new purchase requisition conforming to Principle P01 (Traceable purpose)
    and evaluates DMN-01 to generate the exact multi-tier approval chain.
    """
    new_id = f"REQ-{len(REQUISITIONS_DB) + 2311}"
    total_val = sum(l.get("qty", 1) * l.get("price_estimate", 0) for l in payload.lines)
    first_line = payload.lines[0] if payload.lines else {}
    acct_type = first_line.get("account_assignment", {}).get("type", "COST_CENTER")
    purch_type = first_line.get("item_type", "STOCK_MATERIAL")

    # Evaluate DMN-01
    approver_chain = DMN01RequisitionRule.evaluate(
        value_inr=total_val,
        account_assignment_type=acct_type,
        purchase_type=purch_type
    )

    pr_record = {
        "id": new_id,
        "tenant_id": payload.tenant_id,
        "origin": payload.origin,
        "planned_order_ref": payload.planned_order_ref,
        "purpose_code": payload.purpose_code,
        "requester": payload.requester,
        "status": "IN_APPROVAL" if "AUTO" not in approver_chain[0] else "APPROVED",
        "company_code": payload.company_code,
        "plant": payload.plant,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "lines": payload.lines,
        "approvals": [{"role": role, "status": "PENDING" if "AUTO" not in role else "APPROVED"} for role in approver_chain]
    }
    REQUISITIONS_DB[new_id] = pr_record

    # Lineage link if from planned order
    if payload.planned_order_ref:
        lineage_engine.record_link(
            tenant_id=payload.tenant_id,
            from_type="PLANNED_ORDER",
            from_id=payload.planned_order_ref,
            to_type="REQUISITION",
            to_id=new_id,
            link_type="converted_from",
            created_by=payload.requester
        )

    return {
        "status": "success",
        "requisition": pr_record,
        "dmn_approval_chain": approver_chain
    }

@router.get("/requisitions/{pr_id}")
def get_requisition(pr_id: str):
    pr = REQUISITIONS_DB.get(pr_id)
    if not pr:
        raise HTTPException(status_code=404, detail=f"Requisition '{pr_id}' not found")
    return {"status": "success", "requisition": pr}

@router.get("/requisitions")
def list_requisitions(status: Optional[str] = None):
    res = list(REQUISITIONS_DB.values())
    if status and status != "All":
        res = [r for r in res if r["status"].lower() == status.lower()]
    return {"status": "success", "total": len(res), "requisitions": res}

@router.post("/requisitions/{pr_id}/lines/{line_no}/promote-material")
def promote_free_text_to_material(pr_id: str, line_no: int, actor: str = "u:buyer.officer"):
    """
    Principle P04 & P05: Reusable new items start a parallel MDM request without polluting master data.
    """
    pr = REQUISITIONS_DB.get(pr_id)
    if not pr:
        raise HTTPException(status_code=404, detail="PR not found")

    mdm_request_id = f"MRQ-{uuid.uuid4().hex[:6].upper()}"
    return {
        "status": "success",
        "message": f"PR line {line_no} initiated parallel MDM request {mdm_request_id}.",
        "mdm_request_id": mdm_request_id,
        "steward_queue": "Domain Stewards (Mechanical/Tooling)"
    }

# -------------------------------------------------------------
# Module M08: Operational Purchasing (Purchase Orders) Endpoints
# -------------------------------------------------------------

@router.post("/purchase-orders/from-requisition")
def create_po_from_pr(payload: POCreateFromPRRequest):
    """
    Converts approved PR into a formal Purchase Order, inheriting pricing, contract,
    and recording complete lineage.
    """
    pr = REQUISITIONS_DB.get(payload.pr_id)
    if not pr:
        raise HTTPException(status_code=404, detail=f"PR '{payload.pr_id}' not found")

    new_po_id = f"PO-{len(PURCHASE_ORDERS_DB) + 77410}"
    lines = []
    total = 0.0

    for l in pr["lines"]:
        qty = l["qty"]
        price = l["price_estimate"]
        line_tot = qty * price
        total += line_tot
        lines.append({
            "line_no": l["line_no"],
            "material_id": l["material_id"],
            "description": l["description"],
            "qty": qty,
            "uom": l["uom"],
            "unit_price": price,
            "total_price": line_tot,
            "delivery_date": l["need_date"],
            "gr_required": True,
            "ir_required": True,
            "tolerance_profile": {"over_pct": 2.0, "under_pct": 5.0}
        })

    po_record = {
        "id": new_po_id,
        "tenant_id": pr["tenant_id"],
        "version": 1,
        "status": "DRAFT",
        "supplier_id": payload.supplier_id,
        "supplier_name": "Trichy Forge Works",
        "company_code": pr["company_code"],
        "plant": pr["plant"],
        "purch_org": "1000",
        "contract_ref": payload.contract_ref,
        "payment_terms": "N60",
        "incoterms": "FCA Trichy",
        "currency": "INR",
        "total_amount_inr": total,
        "risk_score": 0,
        "touchless": False,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "created_by": payload.actor,
        "lines": lines
    }
    PURCHASE_ORDERS_DB[new_po_id] = po_record

    # Record lineage & SoD action
    lineage_engine.record_link(
        tenant_id=pr["tenant_id"],
        from_type="REQUISITION",
        from_id=payload.pr_id,
        to_type="PURCHASE_ORDER",
        to_id=new_po_id,
        link_type="ordered_from",
        created_by=payload.actor
    )
    if payload.contract_ref:
        lineage_engine.record_link(
            tenant_id=pr["tenant_id"],
            from_type="CONTRACT",
            from_id=payload.contract_ref,
            to_type="PURCHASE_ORDER",
            to_id=new_po_id,
            link_type="priced_by_contract",
            created_by=payload.actor
        )
    action_history_store.record_action("PURCHASE_ORDER", new_po_id, "CREATE_PO", payload.actor)

    return {"status": "success", "purchase_order": po_record}

@router.post("/purchase-orders/{po_id}/validate")
def validate_po_and_evaluate_touchless(po_id: str, payload: POValidationRequest):
    """
    Computes explainable additive PO Risk Score (0-100) and evaluates DMN-02 Touchless criteria.
    In signature case PO-77410, risk=18 -> Touchless Auto-Release!
    """
    po = PURCHASE_ORDERS_DB.get(po_id)
    if not po:
        raise HTTPException(status_code=404, detail=f"PO '{po_id}' not found")

    # Calculate additive risk
    risk_eval = PORiskScoreCalculator.calculate(
        late_delivery_prob=payload.late_delivery_prob,
        price_deviation_vs_contract=False,
        supplier_not_qualified=False,
        value_above_band=po["total_amount_inr"] > payload.touchless_band_max,
        split_pattern=payload.has_split_pattern,
        account_assignment_changed=False
    )

    # Evaluate DMN-02 Touchless Decision
    touchless_decision = DMN02TouchlessPO.evaluate(
        price_source="CONTRACT" if po.get("contract_ref") else "NONE",
        supplier_status="QUALIFIED",
        value_inr=po["total_amount_inr"],
        touchless_band_max=payload.touchless_band_max,
        has_split_pattern=payload.has_split_pattern,
        late_risk_prob=payload.late_delivery_prob,
        risk_score=risk_eval["risk_score"]
    )

    po["risk_score"] = risk_eval["risk_score"]
    po["validation_factors"] = risk_eval["factors"]
    po["touchless"] = touchless_decision["touchless_approved"]
    if touchless_decision["touchless_approved"]:
        po["status"] = "RELEASED"

    return {
        "status": "success",
        "po_id": po_id,
        "risk_evaluation": risk_eval,
        "touchless_decision": touchless_decision,
        "po_status": po["status"]
    }

@router.get("/purchase-orders/{po_id}")
def get_purchase_order(po_id: str):
    po = PURCHASE_ORDERS_DB.get(po_id)
    if not po:
        raise HTTPException(status_code=404, detail=f"PO '{po_id}' not found")
    return {"status": "success", "purchase_order": po}

@router.get("/purchase-orders")
def list_purchase_orders(status: Optional[str] = None):
    pos = list(PURCHASE_ORDERS_DB.values())
    if status and status != "All":
        pos = [p for p in pos if p["status"].lower() == status.lower()]
    return {"status": "success", "total": len(pos), "purchase_orders": pos}

# -------------------------------------------------------------
# Module M09: Fulfilment, Goods Receipt & SES Endpoints
# -------------------------------------------------------------

@router.post("/receiving/goods-receipt")
def post_goods_receipt(payload: GoodsReceiptPostRequest):
    """
    Posts Goods Receipt against PO/ASN with quality hold and SoD check (SOD-03: receiver != PO creator).
    In signature case GR-90231: 5,400 received -> 5,380 accepted, 20 rejected (porosity).
    """
    # Enforce SOD-03 at command time
    sod_engine.check_action(
        actor=payload.receiver,
        target_action="POST_GR",
        target_object_type="PURCHASE_ORDER",
        target_object_id=payload.po_id,
        context={"po_id": payload.po_id}
    )

    po = PURCHASE_ORDERS_DB.get(payload.po_id)
    if not po:
        raise HTTPException(status_code=404, detail="PO not found")

    new_gr_id = f"GR-{len(GOODS_RECEIPTS_DB) + 90231}"
    rec_tot = sum(l.get("qty_received", 0) for l in payload.received_lines)
    acc_tot = sum(l.get("qty_accepted", 0) for l in payload.received_lines)
    rej_tot = sum(l.get("qty_rejected", 0) for l in payload.received_lines)

    gr_record = {
        "id": new_gr_id,
        "tenant_id": po["tenant_id"],
        "po_id": payload.po_id,
        "asn_id": payload.asn_id,
        "receiver": payload.receiver,
        "received_at": datetime.utcnow().isoformat() + "Z",
        "status": "ACCEPTED" if rej_tot == 0 else "ACCEPTED_WITH_REJECTION",
        "total_received": rec_tot,
        "total_accepted": acc_tot,
        "total_rejected": rej_tot,
        "quality_doc": payload.quality_doc or "QL-2210",
        "lines": payload.received_lines
    }
    GOODS_RECEIPTS_DB[new_gr_id] = gr_record

    # Record lineage & SoD
    lineage_engine.record_link(
        tenant_id=po["tenant_id"],
        from_type="PURCHASE_ORDER",
        from_id=payload.po_id,
        to_type="GOODS_RECEIPT",
        to_id=new_gr_id,
        link_type="received_against",
        created_by=payload.receiver
    )
    action_history_store.record_action("PURCHASE_ORDER", payload.po_id, "POST_GR", payload.receiver)

    return {"status": "success", "goods_receipt": gr_record}

@router.post("/receiving/service-entry")
def approve_service_entry_sheet(payload: ServiceEntrySheetRequest):
    """
    Submits and approves Service Entry Sheet (SES) with strict SOD-03 check:
    Approver != PO creator != supplier.
    """
    sod_engine.check_action(
        actor=payload.actor,
        target_action="APPROVE_SES",
        target_object_type="PURCHASE_ORDER",
        target_object_id=payload.po_id,
        context={"po_id": payload.po_id}
    )

    ses_id = f"SES-{uuid.uuid4().hex[:6].upper()}"
    return {
        "status": "success",
        "ses_id": ses_id,
        "message": f"Service Entry Sheet {ses_id} approved for {payload.progress_pct}% progress.",
        "amount_inr": payload.amount_inr,
        "approver": payload.actor
    }

# -------------------------------------------------------------
# Module M10: Invoice Matching & Finance Integration Endpoints
# -------------------------------------------------------------

@router.post("/invoices/capture")
def capture_invoice(payload: InvoiceCaptureRequest):
    """
    Captures supplier invoice and runs 3-way match against PO and GR using DMN-03 tolerances.
    In signature case INV-TF-8812: billed 5,400 vs accepted 5,380 -> +20 Quantity Exception!
    """
    po = PURCHASE_ORDERS_DB.get(payload.po_id)
    if not po:
        raise HTTPException(status_code=404, detail="PO not found")

    # Find matching GR
    gr = next((g for g in GOODS_RECEIPTS_DB.values() if g["po_id"] == payload.po_id), None)
    gr_accepted = gr["total_accepted"] if gr else 0

    first_line = payload.lines[0] if payload.lines else {}
    billed_qty = first_line.get("billed_qty", 5400)
    billed_price = first_line.get("billed_unit_price", 398.0)
    po_price = po["lines"][0]["unit_price"] if po["lines"] else billed_price

    # Evaluate DMN-03 Tolerances
    tolerance_eval = DMN03InvoiceTolerance.check_tolerances(
        po_price=po_price,
        invoice_price=billed_price,
        po_qty=po["lines"][0]["qty"],
        gr_accepted_qty=gr_accepted,
        invoiced_qty=billed_qty,
        tax_matches=True,
        is_duplicate=False,
        gr_required=True
    )

    new_inv_id = payload.supplier_invoice_no
    inv_record = {
        "id": new_inv_id,
        "tenant_id": po["tenant_id"],
        "supplier_id": payload.supplier_id,
        "supplier_name": payload.supplier_name,
        "supplier_invoice_no": payload.supplier_invoice_no,
        "po_id": payload.po_id,
        "company_code": po["company_code"],
        "fiscal_year": "2026",
        "billed_amount_inr": payload.billed_amount_inr,
        "tax_amount_inr": payload.tax_amount_inr,
        "total_invoiced_inr": payload.billed_amount_inr + payload.tax_amount_inr,
        "gst_irn": payload.gst_irn,
        "status": tolerance_eval["status"],
        "match_type": "3-WAY",
        "match_result": tolerance_eval,
        "credit_note_ref": None,
        "erp_doc_no": None,
        "payment_status": "BLOCKED_ON_EXCEPTION" if not tolerance_eval["is_matched"] else "READY_FOR_PAYMENT",
        "lines": payload.lines
    }
    INVOICES_DB[new_inv_id] = inv_record

    # Record lineage
    lineage_engine.record_link(
        tenant_id=po["tenant_id"],
        from_type="PURCHASE_ORDER",
        from_id=payload.po_id,
        to_type="INVOICE",
        to_id=new_inv_id,
        link_type="invoiced_against",
        created_by="supplier_portal"
    )

    return {
        "status": "success",
        "invoice": inv_record,
        "match_evaluation": tolerance_eval
    }

@router.post("/invoices/{invoice_id}/resolve-exception")
def resolve_invoice_exception(invoice_id: str, payload: InvoiceResolveExceptionRequest):
    """
    Resolves quantity/price exception by attaching Credit Note (e.g. CN-TF-221 for 20 units).
    Transforms invoice status from EXCEPTION -> MATCHED!
    """
    inv = INVOICES_DB.get(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Enforce SOD-04: PO creator cannot approve invoice exception
    sod_engine.check_action(
        actor=payload.actor,
        target_action="APPROVE_INVOICE_EXCEPTION",
        target_object_type="PURCHASE_ORDER",
        target_object_id=inv["po_id"],
        context={"po_id": inv["po_id"]}
    )

    inv["status"] = "MATCHED"
    inv["credit_note_ref"] = payload.credit_note_number
    inv["payment_status"] = "APPROVED_READY_TO_POST"
    inv["match_result"]["status"] = "RESOLVED_WITH_CREDIT_NOTE"
    inv["match_result"]["resolution_note"] = f"Credit note {payload.credit_note_number} received for ₹{payload.credit_note_amount_inr:,.2f}."

    # Record lineage for credit note
    lineage_engine.record_link(
        tenant_id=inv["tenant_id"],
        from_type="CREDIT_NOTE",
        from_id=payload.credit_note_number,
        to_type="INVOICE",
        to_id=invoice_id,
        link_type="settled_by",
        created_by=payload.actor
    )

    return {
        "status": "success",
        "message": f"Exception resolved with Credit Note {payload.credit_note_number}. Invoice is now MATCHED.",
        "invoice": inv
    }

@router.post("/invoices/{invoice_id}/post")
def post_invoice_to_erp(
    invoice_id: str,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    actor: str = "u:ap.clerk.2"
):
    """
    Idempotent ERP Posting (Principle P13):
    Posts invoice to SAP S/4HANA (Doc #5100004421).
    Replays with same Idempotency-Key return cached response with replayed=True!
    """
    inv = INVOICES_DB.get(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    idem_key = idempotency_key or f"AXN|{inv['company_code']}|{inv['supplier_id']}|{invoice_id}"

    # Principle P13: Check idempotency store first for replay requests
    existing_msg = outbox_service.get_message_by_key(idem_key)
    if existing_msg and existing_msg.get("status") == "POSTED":
        return {
            "status": "POSTED",
            "erpDocument": existing_msg["erp_doc_no"],
            "replayed": True,
            "targetSystem": existing_msg["target_system"],
            "objectRef": existing_msg["object_ref"],
            "postedAt": existing_msg["updated_at"]
        }

    if inv["status"] != "MATCHED":
        raise HTTPException(status_code=400, detail=f"Cannot post invoice with status '{inv['status']}'. Must be MATCHED.")

    # Check SoD-02: bank changer cannot post invoice
    sod_engine.check_action(
        actor=actor,
        target_action="POST_INVOICE",
        target_object_type="INVOICE",
        target_object_id=invoice_id,
        context={"supplier_id": inv["supplier_id"]}
    )

    posting_res = outbox_service.post_to_erp(
        tenant_id=inv["tenant_id"],
        idempotency_key=idem_key,
        target_system="SAP_S4HANA",
        object_ref=invoice_id,
        payload=inv
    )

    inv["status"] = "POSTED"
    inv["erp_doc_no"] = posting_res["erpDocument"]
    inv["payment_status"] = "SCHEDULED_PAYMENT_RUN"

    # Record ERP Doc in lineage
    lineage_engine.record_link(
        tenant_id=inv["tenant_id"],
        from_type="INVOICE",
        from_id=invoice_id,
        to_type="ERP_DOCUMENT",
        to_id=posting_res["erpDocument"],
        link_type="posted_as",
        created_by=actor
    )

    return posting_res

@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: str):
    inv = INVOICES_DB.get(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {"status": "success", "invoice": inv}

@router.get("/invoices")
def list_invoices(status: Optional[str] = None):
    invs = list(INVOICES_DB.values())
    if status and status != "All":
        invs = [i for i in invs if i["status"].lower() == status.lower()]
    return {"status": "success", "total": len(invs), "invoices": invs}

# -------------------------------------------------------------
# Lineage Explorer API Endpoint (P10)
# -------------------------------------------------------------

@router.get("/lineage/{doc_type}/{doc_id}")
def get_full_document_lineage(doc_type: str, doc_id: str, tenant_id: str = "axion-mobility"):
    """
    Returns the complete end-to-end forward and backward lineage graph for any document.
    """
    chain = lineage_engine.get_document_chain(
        tenant_id=tenant_id,
        doc_type=doc_type.upper(),
        doc_id=doc_id
    )
    return {"status": "success", "lineage": chain}
