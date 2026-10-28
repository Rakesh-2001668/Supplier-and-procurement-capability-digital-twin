from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.tenant import Tenant, TenantType, SupplierProfile
from app.models.procurement import PurchaseOrder, OrderRequest
from app.api.deps import get_db
from typing import Optional, List
import datetime

router = APIRouter(prefix="/api/v1/supplier", tags=["Supplier Dashboard & Operations"])

@router.get("/dashboard-overview")
def get_supplier_dashboard_overview(
    tenant_id: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Company-centric supplier executive dashboard. Returns company-specific RFQs, POs, financials, action queue, and ups & downs."""
    # Find supplier tenant (defaulting to TENANT_SUPPLIER_001)
    target_id = tenant_id or "TENANT_SUPPLIER_001"
    sup = db.query(Tenant).filter(Tenant.id == target_id).first()
    
    # Company Name for the supplier firm
    company_name = "ABC Manufacturing Ltd" if tenant_id and "abc" in tenant_id.lower() else "Apex Precision Machining Ltd"
    
    # Query real POs for this supplier
    pos = db.query(PurchaseOrder).filter(PurchaseOrder.supplier_tenant_id == target_id).all()
    if not pos:
        pos = db.query(PurchaseOrder).all()
        
    active_pos = [p for p in pos if p.status in ["ISSUED", "DISPATCHED", "PENDING_APPROVAL", "INVOICED"]]
    
    # Query real RFQs
    rfqs = db.query(OrderRequest).all()
    pending_rfqs = [r for r in rfqs if r.status in ["REQUESTED", "DRAFT", "OPEN"]]
    
    total_wip_val = sum(float(p.total_amount) for p in active_pos) if active_pos else 88500.0
    
    return {
        "firm_profile": {
            "company_name": company_name,
            "legal_entity": f"{company_name} & Industrial Technologies Ltd",
            "digital_twin_id": "TWIN-ABC-MFG-001" if "ABC" in company_name else "TWIN-APEX-IND-001",
            "tier": "Tier 1 Qualified Production Partner",
            "location": "Precision Industrial Corridor, Phase II",
            "facility_type": "AS9100D Certified 5-Axis Precision Machining Facility",
            "active_status": "OPERATIONAL_ACTIVE",
            "verified_twin_score": 96
        },
        "financials": {
            "revenue_ytd": 485200.0,
            "gross_profit": 162400.0,
            "gross_profit_margin_pct": 33.5,
            "operating_cogs": 322800.0,
            "scrap_and_tooling_loss": 8200.0,
            "active_wip_revenue": total_wip_val,
            "rfq_pipeline_value": 128500.0,
            "on_time_payment_rate": 98.2
        },
        "factory_progress": {
            "active_jobs_count": len(active_pos) if active_pos else 4,
            "overall_batch_progress_pct": 78.4,
            "overall_equipment_effectiveness_oee": 88.4,
            "on_time_delivery_otif": 97.8,
            "defect_ppm": 65,
            "active_cnc_spindles": 12,
            "spindle_utilization_pct": 84.5
        },
        "actions_required": [
            {
                "id": "ACT-RFQ-01",
                "type": "RFQ_RESPONSE",
                "urgency": "High",
                "title": "Submit Quotation: RFQ-2026-092 (Aerospace Avionics Housing)",
                "counterparty": "Global Aerospace Systems Corp",
                "deadline": "Expires in 18 Hours",
                "action_label": "Submit Bid Quote",
                "target_link": "/supplier/rfqs",
                "details": "Batch of 150 pcs • Target Material: Aluminum 7075-T6"
            },
            {
                "id": "ACT-PO-02",
                "type": "PO_DISPATCH",
                "urgency": "High",
                "title": "Confirm Dispatch & Generate ASN: PO-2025-00123",
                "counterparty": "Global Manufacturing Corp",
                "deadline": "Committed Ship Date: Tomorrow",
                "action_label": "Generate ASN & Dispatch",
                "target_link": "/supplier/orders",
                "details": "Batch of 100 Modular Aluminum Manifolds ($29,500.00)"
            },
            {
                "id": "ACT-INV-03",
                "type": "INVOICE_SUBMIT",
                "urgency": "Medium",
                "title": "Generate Final Commercial Invoice: PO-2025-00089",
                "counterparty": "Titan Machinery Enterprise",
                "deadline": "Delivery Accepted • Ready for Billing",
                "action_label": "Create Invoice (PO Flip)",
                "target_link": "/supplier/invoices/create",
                "details": "85 Titanium Drive Shafts Delivered ($29,500.00)"
            },
            {
                "id": "ACT-QC-04",
                "type": "QUALITY_CMM",
                "urgency": "Low",
                "title": "Upload AS9100 CMM Metrology Report: Batch #771",
                "counterparty": "Quality Compliance Vault",
                "deadline": "Audit Due in 3 Days",
                "action_label": "Upload Inspection Data",
                "target_link": "/supplier/profile",
                "details": "Coordinate Metrology report for Inconel Hydraulic Flanges"
            }
        ],
        "ups_and_downs": [
            {"month": "Nov 25", "revenue": 38000, "profit": 12500, "utilization": 74.0, "event": None, "type": None},
            {"month": "Dec 25", "revenue": 34000, "profit": 9800, "utilization": 68.5, "event": "Year-end maintenance shutdown", "type": "DOWNTURN"},
            {"month": "Jan 26", "revenue": 42000, "profit": 14200, "utilization": 79.0, "event": None, "type": None},
            {"month": "Feb 26", "revenue": 31000, "profit": 7100, "utilization": 62.0, "event": "CNC #3 Spindle bearing replacement downtime (-$7k margin)", "type": "DOWNTURN"},
            {"month": "Mar 26", "revenue": 40000, "profit": 13400, "utilization": 78.5, "event": None, "type": None},
            {"month": "Apr 26", "revenue": 56000, "profit": 21800, "utilization": 89.0, "event": "Automated robotic loading cell commissioned (+$22k surge)", "type": "UPTURN"},
            {"month": "May 26", "revenue": 49000, "profit": 17200, "utilization": 82.5, "event": "Long-term direct titanium tooling agreement secured", "type": "UPTURN"},
            {"month": "Jun 26", "revenue": 36000, "profit": 9400, "utilization": 71.0, "event": "Alloy cutting tool supply backlog delay", "type": "DOWNTURN"},
            {"month": "Jul 26", "revenue": 48000, "profit": 16900, "utilization": 83.0, "event": "Secondary shift added on 5-axis cell", "type": "UPTURN"},
            {"month": "Aug 26", "revenue": 61000, "profit": 24500, "utilization": 92.5, "event": "AS9100 recertification audit clean renewal (Zero NRs)", "type": "UPTURN"},
            {"month": "Sep 26", "revenue": 52000, "profit": 18200, "utilization": 85.0, "event": None, "type": None},
            {"month": "Oct 26", "revenue": 54500, "profit": 19400, "utilization": 86.2, "event": "Working capital credit facility expansion approved", "type": "UPTURN"}
        ],
        "active_orders_summary": [
            {
                "po_number": p.po_number,
                "amount": float(p.total_amount),
                "status": p.status,
                "customer": "Global Manufacturing Corp",
                "progress_pct": 80 if p.status == "INVOICED" else (50 if p.status == "ISSUED" else 30),
                "stage": "Fabrication Complete • Inspection Underway" if p.status == "INVOICED" else "5-Axis Milling in Progress"
            }
            for p in active_pos[:5]
        ],
        "pending_rfqs_summary": [
            {
                "rfq_id": f"RFQ-2026-00{i+1}",
                "part_title": "Precision CNC 5-Axis Aerospace Housing",
                "target_quantity": 100 * (i+1),
                "buyer_org": "Global Aerospace Systems",
                "deadline": "2026-10-20",
                "status": "OPEN_FOR_BIDDING"
            }
            for i in range(min(3, len(pending_rfqs) if pending_rfqs else 3))
        ]
    }

@router.get("/{supplier_id}/profile")
def get_profile(supplier_id: str, db: Session = Depends(get_db)):
    return {
        "id": supplier_id,
        "name": "Apex Precision Machining Ltd",
        "location": "Bengaluru, India",
        "tier": "Tier-1 Strategic",
        "state": "Production Active",
        "trust": 96,
        "freshness": "98%"
    }
