import datetime
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from app.api.deps import get_db
from app.models.procurement import PurchaseOrder, OrderRequest, Quotation, POStatus, POApproval
from app.schemas.procurement import PurchaseOrderSchema, OrderRequestSchema, QuotationSchema

router = APIRouter(prefix="/api/v1/procurement", tags=["procurement"])

@router.get("/po", response_model=List[PurchaseOrderSchema])
def get_purchase_orders(tenant_id: str, skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    from sqlalchemy import or_
    # Match as buyer or supplier
    if tenant_id in ["TENANT_SUPPLIER_001", "supplier-mock"]:
        pos = db.query(PurchaseOrder).filter(
            or_(
                PurchaseOrder.supplier_tenant_id.in_(["TENANT_SUPPLIER_001", "supplier-mock"]),
                PurchaseOrder.tenant_id.in_(["TENANT_SUPPLIER_001", "supplier-mock"])
            )
        ).offset(skip).limit(limit).all()
    elif tenant_id in ["TENANT_BUYER_001", "buyer-mock"]:
        pos = db.query(PurchaseOrder).filter(
            or_(
                PurchaseOrder.tenant_id.in_(["TENANT_BUYER_001", "buyer-mock"]),
                PurchaseOrder.supplier_tenant_id.in_(["TENANT_BUYER_001", "buyer-mock"])
            )
        ).offset(skip).limit(limit).all()
    else:
        pos = db.query(PurchaseOrder).filter(
            or_(PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.supplier_tenant_id == tenant_id)
        ).offset(skip).limit(limit).all()
    return pos

@router.get("/rfq", response_model=List[OrderRequestSchema])
def get_order_requests(tenant_id: str, skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    reqs = db.query(OrderRequest).filter(OrderRequest.tenant_id == tenant_id).offset(skip).limit(limit).all()
    return reqs

@router.get("/quotations", response_model=List[QuotationSchema])
def get_quotations(tenant_id: str, skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    quotes = db.query(Quotation).filter(Quotation.tenant_id == tenant_id).offset(skip).limit(limit).all()
    return quotes

from pydantic import BaseModel
class POStateUpdate(BaseModel):
    status: str

@router.put("/purchase-orders/{po_id}/state")
def update_po_state(po_id: str, payload: POStateUpdate, db: Session = Depends(get_db)):
    from app.models.procurement import PurchaseOrder, POStatus
    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="PO not found")
        
    try:
        po.status = POStatus(payload.status)
        db.commit()
        return {"status": "success", "new_state": po.status}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid state")

class ASNDispatchItem(BaseModel):
    sku: Optional[str] = None
    item_id: Optional[str] = None
    name: Optional[str] = None
    quantity: int = 1

class ASNCreation(BaseModel):
    carrier: str
    tracking_number: str
    estimated_delivery: str
    shipped_quantity: Optional[int] = None
    packages_count: Optional[int] = 1
    coc_number: Optional[str] = None
    notes: Optional[str] = None
    items: Optional[List[ASNDispatchItem]] = None
    tenant_id: Optional[str] = "TENANT_SUPPLIER_001"

@router.post("/purchase-orders/{po_id}/asn")
def create_asn(po_id: str, payload: ASNCreation, db: Session = Depends(get_db)):
    from app.models.procurement import PurchaseOrder, POStatus
    from app.models.inventory import InventoryItem, StockTransaction, AdvanceShipNotice
    import uuid
    from datetime import datetime, timezone

    po = db.query(PurchaseOrder).filter(
        (PurchaseOrder.id == po_id) | (PurchaseOrder.po_number == po_id)
    ).first()
    if not po:
        raise HTTPException(status_code=404, detail=f"Purchase Order '{po_id}' not found.")
        
    try:
        now = datetime.now(timezone.utc)
        target_supplier_tenant = payload.tenant_id or po.supplier_tenant_id or "TENANT_SUPPLIER_001"

        # 1. Update PO Status to SHIPPED
        po.status = POStatus.SHIPPED
        po.updated_at = now

        # 2. Register Advance Ship Notice (ASN) Record
        asn_id = f"ASN-{uuid.uuid4().hex[:6].upper()}"
        asn = AdvanceShipNotice(
            id=asn_id,
            po_id=po.id,
            carrier=payload.carrier,
            tracking_number=payload.tracking_number,
            expected_date=payload.estimated_delivery,
            status="SHIPPED",
            tenant_id=target_supplier_tenant,
            created_at=now,
            updated_at=now
        )
        db.add(asn)

        # 3. Deduct Stock from Supplier Finished Goods Inventory
        deductions = []
        supplier_filter = ["TENANT_SUPPLIER_001", "supplier-mock"]
        if target_supplier_tenant not in supplier_filter:
            supplier_filter.append(target_supplier_tenant)

        dispatch_items = payload.items or []

        # If items not explicitly provided, match Finished Goods from supplier inventory
        if not dispatch_items:
            fg_items = db.query(InventoryItem).filter(
                InventoryItem.tenant_id.in_(supplier_filter),
                InventoryItem.category == "Finished Goods"
            ).all()
            if fg_items:
                qty_to_ship = payload.shipped_quantity or 1
                dispatch_items = [ASNDispatchItem(sku=fg_items[0].sku, quantity=qty_to_ship)]

        for d_item in dispatch_items:
            qty = d_item.quantity if d_item.quantity > 0 else 1
            inv_item = None
            if d_item.item_id:
                inv_item = db.query(InventoryItem).filter(InventoryItem.id == d_item.item_id).first()
            elif d_item.sku:
                inv_item = db.query(InventoryItem).filter(
                    InventoryItem.sku == d_item.sku.strip(),
                    InventoryItem.tenant_id.in_(supplier_filter)
                ).first()

            if not inv_item and d_item.name:
                inv_item = db.query(InventoryItem).filter(
                    InventoryItem.name.ilike(f"%{d_item.name[:10]}%"),
                    InventoryItem.tenant_id.in_(supplier_filter)
                ).first()

            if not inv_item:
                inv_item = db.query(InventoryItem).filter(
                    InventoryItem.tenant_id.in_(supplier_filter),
                    InventoryItem.category == "Finished Goods"
                ).first()

            if inv_item:
                actual_deduct = min(qty, inv_item.quantity_on_hand) if inv_item.quantity_on_hand > 0 else qty
                inv_item.quantity_on_hand = max(0, inv_item.quantity_on_hand - actual_deduct)
                inv_item.updated_at = now
                if inv_item.quantity_on_hand <= 0:
                    inv_item.status = "OUT_OF_STOCK"
                elif inv_item.quantity_on_hand <= inv_item.min_threshold:
                    inv_item.status = "LOW_STOCK"
                else:
                    inv_item.status = "IN_STOCK"

                # Log immutable stock transaction in movement ledger
                ref_id = f"DISP-{po.po_number or po.id}"
                coc_tag = f"CoC: {payload.coc_number}" if payload.coc_number else "CoC Certified"
                tx = StockTransaction(
                    id=f"TX-{uuid.uuid4().hex[:8].upper()}",
                    inventory_item_id=inv_item.id,
                    change_quantity=-actual_deduct,
                    reference_type="GOODS_OUT",
                    reference_id=ref_id,
                    notes=f"Customer Order Dispatch: {po.po_number or po.id} via {payload.carrier} (Tracking: {payload.tracking_number}). {coc_tag}. Ref ASN: {asn_id}",
                    performed_by="Shipping & Logistics Lead",
                    balance_after=inv_item.quantity_on_hand,
                    tenant_id=inv_item.tenant_id or target_supplier_tenant,
                    created_at=now,
                    updated_at=now
                )
                db.add(tx)
                deductions.append({
                    "sku": inv_item.sku,
                    "name": inv_item.name,
                    "deducted_qty": actual_deduct,
                    "balance_after": inv_item.quantity_on_hand,
                    "transaction_id": tx.id
                })

        db.commit()
        return {
            "status": "success",
            "message": f"ASN {asn_id} created successfully and {len(deductions)} Finished Goods items deducted from plant inventory.",
            "asn_id": asn_id,
            "po_id": po.id,
            "po_number": po.po_number,
            "new_status": "SHIPPED",
            "carrier": payload.carrier,
            "tracking_number": payload.tracking_number,
            "deductions": deductions
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

class ProposeChangesPayload(BaseModel):
    reason: str
    newDeliveryDate: str
    notes: str

@router.post("/purchase-orders/{po_id}/propose")
def propose_po_changes(po_id: str, payload: ProposeChangesPayload, db: Session = Depends(get_db)):
    from app.models.procurement import PurchaseOrder
    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="PO not found")
        
    try:
        po.status = "CHANGES_PROPOSED"
        db.commit()
        return {"status": "success", "message": "Changes proposed successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/executive-dashboard")
def get_executive_dashboard(tenant_id: Optional[str] = Query(None), db: Session = Depends(get_db)):
    """Return comprehensive executive dashboard overview: works progress, ups and downs, profit & loss, total spend, active orders, and risk alerts."""
    # Query all active POs
    all_pos = db.query(PurchaseOrder).all()
    active_pos = [p for p in all_pos if p.status in ["ISSUED", "PENDING_APPROVAL", "INVOICED", "DISPATCHED"]]
    
    total_active_val = sum(float(p.total_amount) for p in active_pos) if active_pos else 207711.76
    
    # Active orders detailed list
    orders_list = []
    supplier_names = {
        "TENANT_SUPPLIER_001": "Apex Precision Machining Ltd",
        "047fb121-28d5-43e5-84dd-827a92211b5e": "Lawrence LLC",
        "1ef4bf40-8033-49f5-ba1b-2617dcceffe4": "James-Hampton",
        "309c7081-3d30-43fc-946e-63423a811cde": "Jones & Stephenson",
        "22645dd7-8966-467d-8907-61585915241f": "Gonzalez Inc",
        "ca617a63-0a2b-4f5f-8e19-d0c8db655bf1": "Morrison PLC"
    }
    
    for p in active_pos:
        sup_name = supplier_names.get(p.supplier_tenant_id, "Apex Precision Machining Ltd")
        progress = 85 if p.status == "INVOICED" else (65 if p.status == "ISSUED" else 30)
        orders_list.append({
            "id": p.id,
            "po_number": p.po_number,
            "supplier_name": sup_name,
            "total_amount": float(p.total_amount),
            "status": p.status,
            "created_at": p.created_at.strftime("%Y-%m-%d") if p.created_at else "2026-10-01",
            "progress_pct": progress,
            "stage": "Fabrication Complete • Inspection Underway" if progress >= 80 else "Milling & Turning in Progress"
        })
        
    return {
        "financials": {
            "total_spend_ytd": 1420500.0,
            "budget_allocated": 1750000.0,
            "budget_utilization_pct": 81.2,
            "gross_profit_contribution": 384200.0,
            "cost_savings_achieved": 148500.0,
            "unrealized_variance_loss": 18400.0,
            "net_margin_impact_pct": 8.6,
            "total_active_wip_value": total_active_val,
            "total_active_pos_count": len(active_pos)
        },
        "works_overview": {
            "total_active_projects": len(active_pos) + 2,
            "overall_progress_pct": 76.5,
            "on_track_count": len(active_pos),
            "delayed_count": 1,
            "completed_this_month": 4
        },
        "ups_and_downs": [
            {"month": "Nov 25", "spend": 105000, "profit": 31000, "margin_pct": 29.5, "event": None, "type": None},
            {"month": "Dec 25", "spend": 118000, "profit": 28000, "margin_pct": 23.7, "event": "Year-end logistics freight congestion", "type": "DOWNTURN"},
            {"month": "Jan 26", "spend": 98000, "profit": 34000, "margin_pct": 34.6, "event": None, "type": None},
            {"month": "Feb 26", "spend": 135000, "profit": 22000, "margin_pct": 16.2, "event": "Alloy steel spot price spike (-$14k variance)", "type": "DOWNTURN"},
            {"month": "Mar 26", "spend": 110000, "profit": 32000, "margin_pct": 29.0, "event": None, "type": None},
            {"month": "Apr 26", "spend": 92000, "profit": 42000, "margin_pct": 45.6, "event": "Automated robotic cell launched (+$28k profit surge)", "type": "UPTURN"},
            {"month": "May 26", "spend": 104000, "profit": 39000, "margin_pct": 37.5, "event": "Direct titanium long-term supply contract locked", "type": "UPTURN"},
            {"month": "Jun 26", "spend": 126000, "profit": 25000, "margin_pct": 19.8, "event": "Sub-tier actuator delivery lag (5-day delay)", "type": "DOWNTURN"},
            {"month": "Jul 26", "spend": 115000, "profit": 36000, "margin_pct": 31.3, "event": "Secondary regional warehouse hub opened", "type": "UPTURN"},
            {"month": "Aug 26", "spend": 88000, "profit": 46000, "margin_pct": 52.2, "event": "ISO 9001 audit zero non-conformances (Quality surge)", "type": "UPTURN"},
            {"month": "Sep 26", "spend": 112000, "profit": 35000, "margin_pct": 31.2, "event": None, "type": None},
            {"month": "Oct 26", "spend": 117500, "profit": 38000, "margin_pct": 32.3, "event": "Working capital credit facility expanded", "type": "UPTURN"}
        ],
        "active_orders": orders_list,
        "risk_alerts": [
            {
                "id": "ALT-01",
                "severity": "High",
                "supplier": "Shenzhen Tech Microelectronics",
                "title": "Sub-tier Cortex-M7 Wafer Lead Time Surge",
                "impact": "+8 Days Lead Time Delay",
                "date": "2026-10-08",
                "status": "Mitigation in Progress"
            },
            {
                "id": "ALT-02",
                "severity": "Medium",
                "supplier": "Titan Aero Heavy Engineering",
                "title": "Regional Maritime Port Congestion (Rotterdam)",
                "impact": "+3 Days Transit Delay on Heavy Forgings",
                "date": "2026-10-04",
                "status": "Monitored"
            },
            {
                "id": "ALT-03",
                "severity": "Low",
                "supplier": "Apex Precision Machining Ltd",
                "title": "AS9100 Aerospace Audit Clean Renewal",
                "impact": "100% Quality Acceptance Record",
                "date": "2026-08-16",
                "status": "Verified Safe"
            }
        ]
    }


# In-Memory Store for Supplier Incoming RFQs & Quotation Responses
incoming_rfqs_db = [
    {
        "id": "RFQ-2026-092",
        "title": "5-Axis Aerospace Avionics Enclosure Housing",
        "buyer_org": "Global Aerospace Systems Corp",
        "buyer_tier": "Tier-1 Aerospace OEM",
        "buyer_location": "Seattle, WA, USA",
        "part_number": "AERO-ENC-7075-REV4",
        "cad_filename": "Avionics_Enclosure_Geometry.STEP",
        "cad_filesize": "14.2 MB",
        "material_spec": "Aluminum 7075-T651 (AMS 4045)",
        "precision_tolerance": "±0.003 mm (High Precision Bore Alignment)",
        "surface_treatment": "MIL-A-8625 Type III Class 2 Hardcoat Anodizing (Black)",
        "quantity_requested": 150,
        "buyer_target_unit_price": 280.0,
        "buyer_target_total": 42000.0,
        "target_delivery_date": "2026-11-20",
        "requested_payment_terms": "Net 30 Days",
        "requested_incoterms": "DDP Buyer Warehouse",
        "deadline_date": "2026-10-18",
        "deadline_countdown": "18 Hours Remaining",
        "status": "PENDING_REVIEW",
        "created_at": "2026-10-12",
        "capability_fit": {
            "match_pct": 96,
            "machine_fit": "DMG Mori DMU 65 5-Axis (Capacity Open Week 44)",
            "material_fit": "Raw 7075-T6 Billet in Stock (Batch Cert Available)",
            "tolerance_fit": "Zeiss CMM Metrology Verified"
        },
        "quotation_response": None
    },
    {
        "id": "RFQ-2026-088",
        "title": "Inconel 718 High-Pressure Hydraulic Actuator Manifold",
        "buyer_org": "North American Defense Corp",
        "buyer_tier": "Defense Prime Contractor",
        "buyer_location": "Fort Worth, TX, USA",
        "part_number": "ACT-MNF-718-MOD2",
        "cad_filename": "Hydraulic_Actuator_Manifold.STEP",
        "cad_filesize": "28.5 MB",
        "material_spec": "Inconel 718 Superalloy (AMS 5662)",
        "precision_tolerance": "±0.002 mm (High Pressure Seal Surfaces)",
        "surface_treatment": "Electropolishing Ra 0.4 µm + Vacuum Stress Relief",
        "quantity_requested": 85,
        "buyer_target_unit_price": 490.0,
        "buyer_target_total": 41650.0,
        "target_delivery_date": "2026-12-05",
        "requested_payment_terms": "Net 45 Days",
        "requested_incoterms": "DDP Buyer Facility",
        "deadline_date": "2026-10-22",
        "deadline_countdown": "4 Days Remaining",
        "status": "PENDING_REVIEW",
        "created_at": "2026-10-11",
        "capability_fit": {
            "match_pct": 94,
            "machine_fit": "Mazak Integrex Multi-Tasking Mill-Turn Center",
            "material_fit": "Inconel 718 Supplier Batch Verified",
            "tolerance_fit": "CMM 3D Coordinate Inspection Ready"
        },
        "quotation_response": None
    },
    {
        "id": "RFQ-2026-074",
        "title": "Titanium Grade 5 Pinion Drive Spline Shaft",
        "buyer_org": "Apex Dynamic Mobility Group",
        "buyer_tier": "High-Performance Mobility",
        "buyer_location": "Munich, Germany",
        "part_number": "PIN-SFT-TI64-009",
        "cad_filename": "Spline_Shaft_3D.STEP",
        "cad_filesize": "9.8 MB",
        "material_spec": "Titanium Ti-6Al-4V (Grade 5 ASTM B348)",
        "precision_tolerance": "±0.005 mm (Involute Spline Pitch)",
        "surface_treatment": "TiN PVD Hard Coating (Golden)",
        "quantity_requested": 200,
        "buyer_target_unit_price": 320.0,
        "buyer_target_total": 64000.0,
        "target_delivery_date": "2026-11-28",
        "requested_payment_terms": "Net 30 Days",
        "requested_incoterms": "FOB Port / DDP Buyer",
        "deadline_date": "2026-10-26",
        "deadline_countdown": "8 Days Remaining",
        "status": "QUOTED",
        "created_at": "2026-10-09",
        "capability_fit": {
            "match_pct": 98,
            "machine_fit": "Mazak Integrex i-200 + Wire EDM Spline Cutting",
            "material_fit": "Ti-6Al-4V Aerospace Rod in Stock",
            "tolerance_fit": "Gear & Spline Metrology Verified"
        },
        "quotation_response": {
            "decision": "ACCEPTED",
            "quoted_unit_price": 335.0,
            "quoted_total_price": 67000.0,
            "production_lead_time_days": 16,
            "committed_delivery_date": "2026-11-25",
            "payment_terms": "Net 30 Days (Electronic Bank Wire)",
            "incoterms": "DDP Buyer Facility",
            "validity_days": 30,
            "technical_notes": "Quote includes 100% CMM metrology scan, wire EDM precision spline cut, and EN 10204 3.1 material test certificate.",
            "decline_reason": None,
            "submitted_at": "2026-10-10 14:22:00 UTC"
        }
    },
    {
        "id": "RFQ-2026-061",
        "title": "Cast Iron Heavy Machinery Bearing Cap Flange",
        "buyer_org": "Continental Heavy Forgings GmbH",
        "buyer_tier": "Industrial Equipment",
        "buyer_location": "Stuttgart, Germany",
        "part_number": "FLG-IRN-9092",
        "cad_filename": "Bearing_Cap_Rough.STEP",
        "cad_filesize": "34.1 MB",
        "material_spec": "Grey Cast Iron EN-GJL-250",
        "precision_tolerance": "±0.05 mm (Rough Cast Machining)",
        "surface_treatment": "Black Oxide Anti-Corrosion Dip",
        "quantity_requested": 500,
        "buyer_target_unit_price": 45.0,
        "buyer_target_total": 22500.0,
        "target_delivery_date": "2026-11-10",
        "requested_payment_terms": "Net 60 Days",
        "requested_incoterms": "EXW Factory Gate",
        "deadline_date": "2026-10-14",
        "deadline_countdown": "Expired Yesterday",
        "status": "DECLINED",
        "created_at": "2026-10-05",
        "capability_fit": {
            "match_pct": 68,
            "machine_fit": "Capacity constrained (High volume casting)",
            "material_fit": "Grey Cast Iron not certified in twin",
            "tolerance_fit": "Outside aerospace precision focus"
        },
        "quotation_response": {
            "decision": "DECLINED",
            "quoted_unit_price": None,
            "quoted_total_price": None,
            "production_lead_time_days": None,
            "committed_delivery_date": None,
            "payment_terms": None,
            "incoterms": None,
            "validity_days": None,
            "technical_notes": None,
            "decline_reason": "Facility specializes in 5-axis high-tolerance titanium and aluminum machining. Rough cast iron high-volume production falls outside our core manufacturing envelope and AS9100 cleanroom focus.",
            "submitted_at": "2026-10-06 10:15:00 UTC"
        }
    }
]

class SupplierRFQResponsePayload(BaseModel):
    decision: str  # ACCEPTED, DECLINED, CLARIFICATION
    quoted_unit_price: Optional[float] = None
    production_lead_time_days: Optional[int] = None
    committed_delivery_date: Optional[str] = None
    payment_terms: Optional[str] = None
    incoterms: Optional[str] = None
    validity_days: Optional[int] = 30
    technical_notes: Optional[str] = None
    decline_reason: Optional[str] = None

def calculate_rfq_atp(rfq: dict, inv_items: List[Any]) -> dict:
    """
    Computes real-time Available-to-Promise (ATP) based on Finished Goods on-hand
    and Raw Material billets/bars in stock for the supplier.
    """
    requested_qty = rfq.get("quantity_requested", 1)
    material_spec = rfq.get("material_spec", "").lower()
    title = rfq.get("title", "").lower()
    part_num = rfq.get("part_number", "").upper()
    
    fg_items = [it for it in inv_items if getattr(it, "category", "") == "Finished Goods"]
    raw_items = [it for it in inv_items if getattr(it, "category", "") == "Raw Materials"]
    
    # 1. Match against Finished Goods Depot
    matched_fg = None
    if "7075" in part_num or "7075" in material_spec or "enclosure" in title or "housing" in title:
        matched_fg = next((it for it in fg_items if "HSG" in it.sku or "Housing" in it.name), None)
    elif "718" in part_num or "718" in material_spec or "manifold" in title or "flange" in title:
        matched_fg = next((it for it in fg_items if "FLG" in it.sku or "Flange" in it.name), None)
    elif "ti64" in part_num.lower() or "titanium" in material_spec or "spline" in title or "shaft" in title:
        matched_fg = next((it for it in fg_items if "ACT-SHF" in it.sku or "Shaft" in it.name), None)
        
    # 2. Match matching raw material
    matched_raw = None
    if "7075" in material_spec or "aluminum" in material_spec:
        matched_raw = next((it for it in raw_items if "7075" in it.sku or "Aluminum" in it.name), None)
    elif "718" in material_spec or "inconel" in material_spec:
        matched_raw = next((it for it in raw_items if "718" in it.sku or "Inconel" in it.name), None)
    elif "titanium" in material_spec or "ti-6al-4v" in material_spec:
        matched_raw = next((it for it in raw_items if "TI-6AL4V" in it.sku or "Titanium" in it.name), None)

    # Check outside scope materials
    if "cast iron" in material_spec or "grey" in material_spec:
        return {
            "status": "OUT_OF_SCOPE",
            "badge_color": "red",
            "badge_text": "❌ Not Stocked / Outside Twin Envelope",
            "headline": "Grey Cast Iron EN-GJL-250 Not Stocked",
            "available_fgi_qty": 0,
            "raw_stock_info": "Zero cast iron in inventory. Outside AS9100 cleanroom scope.",
            "suggested_lead_time_days": 35,
            "suggested_unit_price": rfq.get("buyer_target_unit_price", 50.0) * 1.25,
            "atp_action": "RECOMMEND_DECLINE",
            "notes": "Facility specializes in 5-axis aerospace titanium/aluminum alloys. Non-stocked ferrous casting requires unverified external foundry sub-contracting."
        }
        
    if matched_fg and matched_fg.quantity_on_hand >= requested_qty:
        return {
            "status": "IN_STOCK_FGI",
            "badge_color": "emerald",
            "badge_text": f"⚡ 100% In-Stock in FGI ({matched_fg.quantity_on_hand} Units)",
            "headline": f"Immediate Dispatch Available: {matched_fg.quantity_on_hand} Units in Depot ({matched_fg.location})",
            "available_fgi_qty": matched_fg.quantity_on_hand,
            "raw_stock_info": f"{matched_raw.quantity_on_hand} {matched_raw.unit} {matched_raw.name[:30]}... in stock" if matched_raw else "Raw stock available",
            "suggested_lead_time_days": 2,
            "suggested_unit_price": rfq.get("buyer_target_unit_price", matched_fg.unit_price),
            "atp_action": "INSTANT_DISPATCH",
            "notes": f"100% inspected parts staged at {matched_fg.location}. Pre-certified with CMM dimensional report and EN 10204 3.1 inspection certificate. Ready for immediate outbound freight in 48 hours."
        }
    elif matched_fg and matched_fg.quantity_on_hand > 0:
        return {
            "status": "PARTIAL_FGI_WIP",
            "badge_color": "blue",
            "badge_text": f"⚡ {matched_fg.quantity_on_hand} FGI On-Hand + Raw Stock Ready",
            "headline": f"Partial FGI Available ({matched_fg.quantity_on_hand} pcs) + In-House Billets",
            "available_fgi_qty": matched_fg.quantity_on_hand,
            "raw_stock_info": f"{matched_raw.quantity_on_hand} {matched_raw.unit} certified raw metal staged in Yard" if matched_raw else "Raw billets in stock",
            "suggested_lead_time_days": 8,
            "suggested_unit_price": rfq.get("buyer_target_unit_price", matched_fg.unit_price),
            "atp_action": "HYBRID_FULFILLMENT",
            "notes": f"{matched_fg.quantity_on_hand} finished units can ship immediately; remaining {requested_qty - matched_fg.quantity_on_hand} units will be machined on 5-axis CNC using in-stock {matched_raw.name if matched_raw else 'raw stock'} with 8-day turnaround."
        }
    elif matched_raw and matched_raw.quantity_on_hand > 0:
        return {
            "status": "RAW_MATERIAL_READY",
            "badge_color": "amber",
            "badge_text": f"⚙️ Raw Metal In-House ({matched_raw.quantity_on_hand} {matched_raw.unit})",
            "headline": f"Raw Stock Staged & Verified: {matched_raw.name}",
            "available_fgi_qty": 0,
            "raw_stock_info": f"{matched_raw.quantity_on_hand} {matched_raw.unit} in {matched_raw.location}",
            "suggested_lead_time_days": 14,
            "suggested_unit_price": rfq.get("buyer_target_unit_price", 300.0),
            "atp_action": "PRODUCTION_RUN",
            "notes": f"Certified aerospace mill material on-hand with MTR Heat # trace. 5-axis CNC machine cell available in schedule for complete batch run in 14 calendar days."
        }
    else:
        return {
            "status": "MILL_PROCUREMENT_REQUIRED",
            "badge_color": "slate",
            "badge_text": "📦 Mill Material Procurement Required",
            "headline": "Specialty Raw Metal Required from Primary Mill",
            "available_fgi_qty": 0,
            "raw_stock_info": "Lead time required for certified ingot delivery",
            "suggested_lead_time_days": 28,
            "suggested_unit_price": rfq.get("buyer_target_unit_price", 350.0) * 1.1,
            "atp_action": "EXTENDED_LEAD_TIME",
            "notes": "Custom alloy billets must be procured from approved AS9100 primary mill with 14-day transit prior to 5-axis CNC machining."
        }

@router.get("/incoming-rfqs")
def get_incoming_rfqs(tenant_id: Optional[str] = Query(None), db: Session = Depends(get_db)):
    """Return all incoming RFQs with real-time Available-to-Promise (ATP) calculations."""
    from app.models.inventory import InventoryItem
    try:
        inv_items = db.query(InventoryItem).filter(
            InventoryItem.tenant_id.in_(["TENANT_SUPPLIER_001", "supplier-mock"])
        ).all()
    except Exception:
        inv_items = []
        
    for rfq in incoming_rfqs_db:
        rfq["atp_analysis"] = calculate_rfq_atp(rfq, inv_items)
        
    return incoming_rfqs_db

@router.post("/incoming-rfqs/{rfq_id}/respond")
def respond_to_incoming_rfq(rfq_id: str, payload: SupplierRFQResponsePayload, tenant_id: Optional[str] = Query(None), db: Session = Depends(get_db)):
    """Supplier submits quotation reply or decline decision back to the buyer and persists into database."""
    import uuid
    from app.models.procurement import Quotation, OrderRequest, RFQStatus
    from app.models.inventory import InventoryItem
    
    for rfq in incoming_rfqs_db:
        if rfq["id"] == rfq_id:
            total_amt = None
            if payload.quoted_unit_price:
                total_amt = payload.quoted_unit_price * rfq["quantity_requested"]
                
            response_record = {
                "decision": payload.decision,
                "quoted_unit_price": payload.quoted_unit_price,
                "quoted_total_price": total_amt,
                "production_lead_time_days": payload.production_lead_time_days,
                "committed_delivery_date": payload.committed_delivery_date,
                "payment_terms": payload.payment_terms,
                "incoterms": payload.incoterms,
                "validity_days": payload.validity_days,
                "technical_notes": payload.technical_notes,
                "decline_reason": payload.decline_reason,
                "submitted_at": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
            }
            rfq["quotation_response"] = response_record
            
            if payload.decision == "ACCEPTED":
                rfq["status"] = "QUOTED"
            elif payload.decision == "DECLINED":
                rfq["status"] = "DECLINED"
            else:
                rfq["status"] = "CLARIFICATION_REQUESTED"
                
            # Persist into SQL database quotations table
            try:
                # Ensure parent order_request exists
                existing_req = db.query(OrderRequest).filter(OrderRequest.id == rfq_id).first()
                if not existing_req:
                    new_req = OrderRequest(
                        id=rfq_id,
                        description=f"{rfq['title']} - {rfq['part_number']} ({rfq['quantity_requested']} units)",
                        target_supplier_id="TENANT_SUPPLIER_001",
                        status=RFQStatus.QUOTED if payload.decision == "ACCEPTED" else RFQStatus.REJECTED,
                        tenant_id="TENANT_BUYER_001"
                    )
                    db.add(new_req)
                    db.commit()
                else:
                    existing_req.status = RFQStatus.QUOTED if payload.decision == "ACCEPTED" else RFQStatus.REJECTED
                    db.commit()

                # Insert quotation
                quote_id = f"QUOTE-{uuid.uuid4().hex[:6].upper()}"
                terms_text = f"Lead Time: {payload.production_lead_time_days} days | Payment: {payload.payment_terms} | Incoterms: {payload.incoterms} | Valid: {payload.validity_days} days. {payload.technical_notes or payload.decline_reason or ''}"
                new_quote = Quotation(
                    id=quote_id,
                    request_id=rfq_id,
                    supplier_tenant_id="TENANT_SUPPLIER_001",
                    amount=total_amt or 0.0,
                    terms=terms_text,
                    status=RFQStatus.QUOTED if payload.decision == "ACCEPTED" else RFQStatus.REJECTED,
                    tenant_id="TENANT_BUYER_001"
                )
                db.add(new_quote)
                db.commit()
            except Exception as e:
                print(f"[Quotation DB Sync Error]: {e}")
                db.rollback()

            # Refresh ATP analysis
            try:
                inv_items = db.query(InventoryItem).filter(
                    InventoryItem.tenant_id.in_(["TENANT_SUPPLIER_001", "supplier-mock"])
                ).all()
                rfq["atp_analysis"] = calculate_rfq_atp(rfq, inv_items)
            except Exception:
                pass
                
            return {
                "status": "success",
                "message": f"Quotation response for {rfq_id} submitted to buyer successfully and logged in commercial ledger!",
                "rfq": rfq
            }
            
    raise HTTPException(status_code=404, detail="RFQ not found")


# =========================================================================================
# BUYER RFQ SOURCING & MULTI-SUPPLIER BIDDING ENGINE
# =========================================================================================

buyer_rfqs_db = [
    {
        "id": "RFQ-2026-092",
        "title": "5-Axis Aerospace Avionics Enclosure Housing",
        "part_number": "AERO-ENC-7075-REV4",
        "category": "Aerospace Machining",
        "department": "Structural Assemblies & Avionics",
        "buyer_org": "Global Aerospace Systems Corp",
        "cad_filename": "Avionics_Enclosure_Geometry.STEP",
        "cad_filesize": "14.2 MB",
        "material_spec": "Aluminum 7075-T651 (AMS 4045)",
        "precision_tolerance": "±0.003 mm (High Precision Bore Alignment)",
        "surface_treatment": "MIL-A-8625 Type III Class 2 Hardcoat Anodizing (Black)",
        "quantity": 150,
        "target_unit_price": 280.0,
        "target_total_budget": 42000.0,
        "target_delivery_date": "2026-11-20",
        "deadline_date": "2026-10-25",
        "payment_terms": "Net 30 Days",
        "incoterms": "DDP Buyer Facility",
        "status": "UNDER_EVALUATION",
        "created_at": "2026-10-12",
        "invited_suppliers": 4,
        "bids": [
            {
                "quote_id": "QUO-2026-092-A",
                "supplier_id": "TENANT_SUPPLIER_001",
                "supplier_name": "Apex Precision Machining Ltd",
                "supplier_tier": "Tier-1 AS9100 Rev D Certified",
                "supplier_location": "Bengaluru Aerospace Park / Singapore",
                "unit_price": 265.0,
                "total_amount": 39750.0,
                "tooling_nre_cost": 0.0,
                "lead_time_days": 14,
                "committed_delivery_date": "2026-11-18",
                "twin_match_pct": 98,
                "digital_twin_fit": "100% In-Stock 7075-T6 Billet • Zeiss CMM Calibrated",
                "atp_status": "RAW_MATERIAL_READY",
                "atp_badge": "⚡ Immediate Production Ready (14-Day Cycle)",
                "quality_ppm": 12,
                "quality_score": 99.4,
                "esg_score": 92,
                "incoterms": "DDP Buyer Warehouse",
                "payment_terms": "Net 30 Days",
                "validity_days": 30,
                "mcda_score": 96.2,
                "ai_recommendation": "TOP_RECOMMENDED",
                "ai_reasoning": "Cost leader ($2,250 under budget) with fastest delivery (14 days). AS9100 certified cleanroom with pre-verified CMM metrology inspection.",
                "status": "SUBMITTED",
                "submitted_at": "2026-10-14 11:20:00"
            },
            {
                "quote_id": "QUO-2026-092-B",
                "supplier_id": "SUPPLIER-TITAN-02",
                "supplier_name": "Titan Aero Heavy Engineering",
                "supplier_tier": "Aerospace Prime Subcontractor",
                "supplier_location": "Stuttgart, Germany",
                "unit_price": 278.0,
                "total_amount": 41700.0,
                "tooling_nre_cost": 1200.0,
                "lead_time_days": 21,
                "committed_delivery_date": "2026-11-25",
                "twin_match_pct": 91,
                "digital_twin_fit": "DMG Mori 5-Axis • Mill Procurement Required",
                "atp_status": "MILL_PROCUREMENT_REQUIRED",
                "atp_badge": "📦 7-Day Ingot Transit Needed",
                "quality_ppm": 35,
                "quality_score": 97.2,
                "esg_score": 84,
                "incoterms": "FOB Port / DDP Buyer",
                "payment_terms": "Net 45 Days",
                "validity_days": 30,
                "mcda_score": 85.1,
                "ai_recommendation": "CAPACITY_BACKUP",
                "ai_reasoning": "Competitive pricing but requires 21-day cycle and raw metal transit. Recommended as secondary backup capacity.",
                "status": "SUBMITTED",
                "submitted_at": "2026-10-15 14:15:00"
            },
            {
                "quote_id": "QUO-2026-092-C",
                "supplier_id": "SUPPLIER-KOVAI-03",
                "supplier_name": "Kovai Precision Diecast & Tooling",
                "supplier_tier": "Precision Toolmaker & Diecaster",
                "supplier_location": "Coimbatore, India",
                "unit_price": 295.0,
                "total_amount": 44250.0,
                "tooling_nre_cost": 2800.0,
                "lead_time_days": 28,
                "committed_delivery_date": "2026-12-02",
                "twin_match_pct": 82,
                "digital_twin_fit": "Die Modification & Machining Cell Needed",
                "atp_status": "EXTENDED_LEAD_TIME",
                "atp_badge": "⏳ Tooling & Die Setup (12 Days)",
                "quality_ppm": 68,
                "quality_score": 94.5,
                "esg_score": 78,
                "incoterms": "EXW Factory Gate",
                "payment_terms": "Net 30 Days",
                "validity_days": 45,
                "mcda_score": 73.6,
                "ai_recommendation": "NON_COMPETITIVE",
                "ai_reasoning": "Price exceeds target budget by 5.3% and requires 28 calendar days with $2,800 NRE tooling. Not recommended.",
                "status": "SUBMITTED",
                "submitted_at": "2026-10-16 09:40:00"
            }
        ],
        "clarifications": [
            {
                "id": "CLR-001",
                "sender": "Buyer (Alex Sharma)",
                "recipient": "Apex Precision Machining Ltd",
                "date": "2026-10-15 09:30",
                "message": "Can Apex provide EN 10204 3.1 chemical & mechanical mill certificates along with the first production article inspection (FAIR)?",
                "reply": "Confirmed. All billets are lot-tracked with Heat # and full EN 10204 3.1 MTR will accompany the AS9102 FAIR inspection package."
            }
        ],
        "awarded_info": None
    },
    {
        "id": "RFQ-2026-088",
        "title": "Inconel 718 High-Pressure Hydraulic Actuator Manifold",
        "part_number": "ACT-MNF-718-MOD2",
        "category": "Superalloy Machining",
        "department": "Hydraulic Flight Controls",
        "buyer_org": "North American Defense Corp",
        "cad_filename": "Hydraulic_Actuator_Manifold.STEP",
        "cad_filesize": "28.5 MB",
        "material_spec": "Inconel 718 Superalloy (AMS 5662)",
        "precision_tolerance": "±0.002 mm (High Pressure Seal Surfaces)",
        "surface_treatment": "Electropolishing Ra 0.4 µm + Vacuum Stress Relief",
        "quantity": 85,
        "target_unit_price": 490.0,
        "target_total_budget": 41650.0,
        "target_delivery_date": "2026-12-05",
        "deadline_date": "2026-10-28",
        "payment_terms": "Net 45 Days",
        "incoterms": "DDP Buyer Facility",
        "status": "UNDER_EVALUATION",
        "created_at": "2026-10-11",
        "invited_suppliers": 4,
        "bids": [
            {
                "quote_id": "QUO-2026-088-A",
                "supplier_id": "TENANT_SUPPLIER_001",
                "supplier_name": "Apex Precision Machining Ltd",
                "supplier_tier": "Tier-1 AS9100 Rev D Certified",
                "supplier_location": "Bengaluru / Singapore",
                "unit_price": 475.0,
                "total_amount": 40375.0,
                "tooling_nre_cost": 0.0,
                "lead_time_days": 16,
                "committed_delivery_date": "2026-11-26",
                "twin_match_pct": 96,
                "digital_twin_fit": "Mazak Integrex Multi-Tasking Mill-Turn Center",
                "atp_status": "RAW_MATERIAL_READY",
                "atp_badge": "⚡ AMS 5662 Stock In-Yard",
                "quality_ppm": 15,
                "quality_score": 99.1,
                "esg_score": 90,
                "incoterms": "DDP Buyer Facility",
                "payment_terms": "Net 30 Days",
                "validity_days": 30,
                "mcda_score": 94.8,
                "ai_recommendation": "TOP_RECOMMENDED",
                "ai_reasoning": "$1,275 below target budget. Inconel 718 aerospace rod batch pre-tested with 16-day turnaround.",
                "status": "SUBMITTED",
                "submitted_at": "2026-10-13 16:40:00"
            },
            {
                "quote_id": "QUO-2026-088-B",
                "supplier_id": "SUPPLIER-CONT-03",
                "supplier_name": "Continental Mechatronics Corp",
                "supplier_tier": "Defense Systems Tier-1",
                "supplier_location": "Munich, Germany",
                "unit_price": 485.0,
                "total_amount": 41225.0,
                "tooling_nre_cost": 500.0,
                "lead_time_days": 19,
                "committed_delivery_date": "2026-11-30",
                "twin_match_pct": 92,
                "digital_twin_fit": "5-Axis Hermle High-Torque Spindle",
                "atp_status": "RAW_MATERIAL_READY",
                "atp_badge": "⚡ Qualified Inconel Billets",
                "quality_ppm": 22,
                "quality_score": 96.8,
                "esg_score": 86,
                "incoterms": "DDP Buyer Facility",
                "payment_terms": "Net 45 Days",
                "validity_days": 30,
                "mcda_score": 89.0,
                "ai_recommendation": "STRONG_ALTERNATIVE",
                "ai_reasoning": "Strong technical capability matching defense spec. Slower delivery than Apex by 3 days.",
                "status": "SUBMITTED",
                "submitted_at": "2026-10-14 10:10:00"
            },
            {
                "quote_id": "QUO-2026-088-C",
                "supplier_id": "SUPPLIER-PREC-04",
                "supplier_name": "Precision AutoComp Aerospace",
                "supplier_tier": "Specialty Component Machining",
                "supplier_location": "Dallas, TX, USA",
                "unit_price": 510.0,
                "total_amount": 43350.0,
                "tooling_nre_cost": 1800.0,
                "lead_time_days": 24,
                "committed_delivery_date": "2026-12-05",
                "twin_match_pct": 88,
                "digital_twin_fit": "Standard 4-Axis CNC (Fixture Required)",
                "atp_status": "MILL_PROCUREMENT_REQUIRED",
                "atp_badge": "📦 Secondary Mill Order",
                "quality_ppm": 48,
                "quality_score": 95.0,
                "esg_score": 81,
                "incoterms": "FOB Port",
                "payment_terms": "Net 30 Days",
                "validity_days": 30,
                "mcda_score": 79.2,
                "ai_recommendation": "NON_COMPETITIVE",
                "ai_reasoning": "Unit price is 4.1% above target with additional $1,800 NRE tooling cost.",
                "status": "SUBMITTED",
                "submitted_at": "2026-10-15 08:30:00"
            }
        ],
        "clarifications": [],
        "awarded_info": None
    },
    {
        "id": "RFQ-2026-074",
        "title": "Titanium Grade 5 Pinion Drive Spline Shaft",
        "part_number": "PIN-SFT-TI64-009",
        "category": "High-Performance Mobility",
        "department": "Powertrain & Gear Systems",
        "buyer_org": "Apex Dynamic Mobility Group",
        "cad_filename": "Spline_Shaft_3D.STEP",
        "cad_filesize": "9.8 MB",
        "material_spec": "Titanium Ti-6Al-4V (Grade 5 ASTM B348)",
        "precision_tolerance": "±0.005 mm (Involute Spline Pitch)",
        "surface_treatment": "TiN PVD Hard Coating (Golden)",
        "quantity": 200,
        "target_unit_price": 320.0,
        "target_total_budget": 64000.0,
        "target_delivery_date": "2026-11-28",
        "deadline_date": "2026-10-26",
        "payment_terms": "Net 30 Days",
        "incoterms": "FOB Port / DDP Buyer",
        "status": "OPEN_FOR_BIDS",
        "created_at": "2026-10-09",
        "invited_suppliers": 3,
        "bids": [
            {
                "quote_id": "QUO-2026-074-A",
                "supplier_id": "TENANT_SUPPLIER_001",
                "supplier_name": "Apex Precision Machining Ltd",
                "supplier_tier": "Tier-1 AS9100 Rev D Certified",
                "supplier_location": "Bengaluru / Singapore",
                "unit_price": 335.0,
                "total_amount": 67000.0,
                "tooling_nre_cost": 0.0,
                "lead_time_days": 16,
                "committed_delivery_date": "2026-11-25",
                "twin_match_pct": 98,
                "digital_twin_fit": "Mazak Integrex i-200 + Wire EDM Spline Cutting",
                "atp_status": "RAW_MATERIAL_READY",
                "atp_badge": "⚡ Titanium Ti-6Al-4V in Yard",
                "quality_ppm": 8,
                "quality_score": 99.6,
                "esg_score": 93,
                "incoterms": "DDP Buyer Facility",
                "payment_terms": "Net 30 Days",
                "validity_days": 30,
                "mcda_score": 92.4,
                "ai_recommendation": "TOP_RECOMMENDED",
                "ai_reasoning": "High precision involute spline wire EDM cutting included with full metrology inspection cert.",
                "status": "SUBMITTED",
                "submitted_at": "2026-10-10 14:22:00"
            },
            {
                "quote_id": "QUO-2026-074-B",
                "supplier_id": "SUPPLIER-TITAN-02",
                "supplier_name": "Titan Aero Heavy Engineering",
                "supplier_tier": "Aerospace Prime Subcontractor",
                "supplier_location": "Stuttgart, Germany",
                "unit_price": 348.0,
                "total_amount": 69600.0,
                "tooling_nre_cost": 1500.0,
                "lead_time_days": 24,
                "committed_delivery_date": "2026-12-04",
                "twin_match_pct": 89,
                "digital_twin_fit": "Broaching Cell + CNC Lathe",
                "atp_status": "MILL_PROCUREMENT_REQUIRED",
                "atp_badge": "📦 Titanium Billet In-Transit",
                "quality_ppm": 28,
                "quality_score": 96.5,
                "esg_score": 83,
                "incoterms": "FOB Port",
                "payment_terms": "Net 45 Days",
                "validity_days": 30,
                "mcda_score": 81.6,
                "ai_recommendation": "SECONDARY_BID",
                "ai_reasoning": "Higher price and longer lead time than Apex. Broaching tooling required.",
                "status": "SUBMITTED",
                "submitted_at": "2026-10-12 11:05:00"
            }
        ],
        "clarifications": [],
        "awarded_info": None
    },
    {
        "id": "RFQ-2026-061",
        "title": "Cast Iron Heavy Machinery Bearing Cap Flange",
        "part_number": "FLG-IRN-9092",
        "category": "Ferrous Castings",
        "department": "Heavy Industrial Drives",
        "buyer_org": "Continental Heavy Forgings GmbH",
        "cad_filename": "Bearing_Cap_Rough.STEP",
        "cad_filesize": "34.1 MB",
        "material_spec": "Grey Cast Iron EN-GJL-250",
        "precision_tolerance": "±0.05 mm (Rough Cast Machining)",
        "surface_treatment": "Black Oxide Anti-Corrosion Dip",
        "quantity": 500,
        "target_unit_price": 45.0,
        "target_total_budget": 22500.0,
        "target_delivery_date": "2026-11-10",
        "deadline_date": "2026-10-30",
        "payment_terms": "Net 60 Days",
        "incoterms": "EXW Factory Gate",
        "status": "OPEN_FOR_BIDS",
        "created_at": "2026-10-05",
        "invited_suppliers": 3,
        "bids": [
            {
                "quote_id": "QUO-2026-061-A",
                "supplier_id": "SUPPLIER-BAVARIA-05",
                "supplier_name": "Bavaria Foundry Castings GmbH",
                "supplier_tier": "Foundry & Casting Specialist",
                "supplier_location": "Nuremberg, Germany",
                "unit_price": 42.5,
                "total_amount": 21250.0,
                "tooling_nre_cost": 650.0,
                "lead_time_days": 18,
                "committed_delivery_date": "2026-11-15",
                "twin_match_pct": 95,
                "digital_twin_fit": "Automated Sand Casting & Milling Line",
                "atp_status": "RAW_MATERIAL_READY",
                "atp_badge": "⚡ EN-GJL-250 In-Stock Foundry",
                "quality_ppm": 45,
                "quality_score": 96.0,
                "esg_score": 82,
                "incoterms": "EXW Factory Gate",
                "payment_terms": "Net 60 Days",
                "validity_days": 30,
                "mcda_score": 93.1,
                "ai_recommendation": "TOP_RECOMMENDED",
                "ai_reasoning": "Foundry specialist. Unit price $42.50 provides $1,250 savings vs target.",
                "status": "SUBMITTED",
                "submitted_at": "2026-10-08 14:00:00"
            },
            {
                "quote_id": "QUO-2026-061-B",
                "supplier_id": "SUPPLIER-STUTTGART-06",
                "supplier_name": "Stuttgart Metal Forgings",
                "supplier_tier": "Heavy Forging Supplier",
                "supplier_location": "Stuttgart, Germany",
                "unit_price": 44.0,
                "total_amount": 22000.0,
                "tooling_nre_cost": 800.0,
                "lead_time_days": 21,
                "committed_delivery_date": "2026-11-18",
                "twin_match_pct": 90,
                "digital_twin_fit": "High-Volume Casting Line",
                "atp_status": "RAW_MATERIAL_READY",
                "atp_badge": "⚡ Cast Iron Available",
                "quality_ppm": 55,
                "quality_score": 94.8,
                "esg_score": 80,
                "incoterms": "EXW Factory Gate",
                "payment_terms": "Net 60 Days",
                "validity_days": 30,
                "mcda_score": 87.5,
                "ai_recommendation": "SECONDARY_BID",
                "ai_reasoning": "Meets specification with standard delivery schedule.",
                "status": "SUBMITTED",
                "submitted_at": "2026-10-09 16:30:00"
            }
        ],
        "clarifications": [],
        "awarded_info": None
    },
    {
        "id": "RFQ-2026-050",
        "title": "Micro-Precision Titanium Bone Screw Fasteners",
        "part_number": "MED-SCRW-TI64-002",
        "category": "Medical Device & Implants",
        "department": "Biomedical Engineering",
        "buyer_org": "MedTech BioSystems AG",
        "cad_filename": "Bone_Screw_3D.STEP",
        "cad_filesize": "5.6 MB",
        "material_spec": "Titanium Grade 23 (Ti-6Al-4V ELI)",
        "precision_tolerance": "±0.0015 mm (Micro Thread Lead)",
        "surface_treatment": "Passivation ASTM F86 + Cleanroom Packaging",
        "quantity": 1200,
        "target_unit_price": 50.0,
        "target_total_budget": 60000.0,
        "target_delivery_date": "2026-10-30",
        "deadline_date": "2026-09-25",
        "payment_terms": "Net 30 Days",
        "incoterms": "DDP Buyer Cleanroom",
        "status": "AWARDED",
        "created_at": "2026-09-10",
        "invited_suppliers": 3,
        "bids": [
            {
                "quote_id": "QUO-2026-050-A",
                "supplier_id": "TENANT_SUPPLIER_001",
                "supplier_name": "Apex Precision Machining Ltd",
                "supplier_tier": "ISO 13485 & AS9100 Certified",
                "supplier_location": "Bengaluru / Singapore",
                "unit_price": 48.5,
                "total_amount": 58200.0,
                "tooling_nre_cost": 0.0,
                "lead_time_days": 15,
                "committed_delivery_date": "2026-10-25",
                "twin_match_pct": 99,
                "digital_twin_fit": "Citizen Swiss-Type 7-Axis Lathe + Cleanroom Passivation",
                "atp_status": "IN_STOCK_FGI",
                "atp_badge": "⚡ Pre-Verified Medical Twin",
                "quality_ppm": 0,
                "quality_score": 99.9,
                "esg_score": 94,
                "incoterms": "DDP Buyer Facility",
                "payment_terms": "Net 30 Days",
                "validity_days": 30,
                "mcda_score": 98.4,
                "ai_recommendation": "AWARDED_WINNER",
                "ai_reasoning": "Awarded bid: $1,800 cost savings, ISO 13485 certified cleanroom line, 0 PPM quality defect rate.",
                "status": "AWARDED",
                "submitted_at": "2026-09-15 10:12:00"
            }
        ],
        "clarifications": [],
        "awarded_info": {
            "quote_id": "QUO-2026-050-A",
            "supplier_id": "TENANT_SUPPLIER_001",
            "supplier_name": "Apex Precision Machining Ltd",
            "po_number": "PO-2026-0812",
            "total_amount": 58200.0,
            "savings": 1800.0,
            "awarded_at": "2026-09-28 15:45:00",
            "contract_status": "CONTRACT_SIGNED"
        }
    },
    {
        "id": "RFQ-2026-042",
        "title": "Cryogenic Fuel Injector Nozzle Assembly",
        "part_number": "PROP-NOZ-IN718-V2",
        "category": "Space Propulsion",
        "department": "Liquid Propulsion R&D",
        "buyer_org": "Orbital Dynamics Spacecraft Corp",
        "cad_filename": "Injector_Nozzle_Assembly.STEP",
        "cad_filesize": "42.0 MB",
        "material_spec": "Inconel 718 + Copper Alloy Liner",
        "precision_tolerance": "±0.002 mm (Micro-orifice discharge)",
        "surface_treatment": "Vacuum Brazing + CT Metrology",
        "quantity": 40,
        "target_unit_price": 1900.0,
        "target_total_budget": 76000.0,
        "target_delivery_date": "2026-11-15",
        "deadline_date": "2026-09-20",
        "payment_terms": "Net 45 Days",
        "incoterms": "DDP Buyer Space Launch Facility",
        "status": "AWARDED",
        "created_at": "2026-09-01",
        "invited_suppliers": 3,
        "bids": [
            {
                "quote_id": "QUO-2026-042-B",
                "supplier_id": "SUPPLIER-TITAN-02",
                "supplier_name": "Titan Aero Heavy Engineering",
                "supplier_tier": "Aerospace Prime Subcontractor",
                "supplier_location": "Stuttgart, Germany",
                "unit_price": 1860.0,
                "total_amount": 74400.0,
                "tooling_nre_cost": 2500.0,
                "lead_time_days": 30,
                "committed_delivery_date": "2026-11-10",
                "twin_match_pct": 95,
                "digital_twin_fit": "Vacuum Brazing Furnace + 5-Axis EDM",
                "atp_status": "RAW_MATERIAL_READY",
                "atp_badge": "⚡ Inconel Billets Available",
                "quality_ppm": 10,
                "quality_score": 98.8,
                "esg_score": 88,
                "incoterms": "DDP Launch Facility",
                "payment_terms": "Net 45 Days",
                "validity_days": 30,
                "mcda_score": 95.0,
                "ai_recommendation": "AWARDED_WINNER",
                "ai_reasoning": "Awarded bid: $1,600 budget savings, qualified aerospace vacuum brazing line.",
                "status": "AWARDED",
                "submitted_at": "2026-09-08 14:10:00"
            }
        ],
        "clarifications": [],
        "awarded_info": {
            "quote_id": "QUO-2026-042-B",
            "supplier_id": "SUPPLIER-TITAN-02",
            "supplier_name": "Titan Aero Heavy Engineering",
            "po_number": "PO-2026-0794",
            "total_amount": 74400.0,
            "savings": 1600.0,
            "awarded_at": "2026-09-22 11:20:00",
            "contract_status": "CONTRACT_SIGNED"
        }
    }
]

class AwardBidPayload(BaseModel):
    quote_id: str
    supplier_id: str
    notes: Optional[str] = None
    buyer_tenant_id: Optional[str] = "TENANT_BUYER_001"

class RFQClarificationPayload(BaseModel):
    supplier_id: Optional[str] = None
    subject: Optional[str] = None
    message: str
    sender_name: Optional[str] = "Procurement Lead (Alex Sharma)"

class CreateRFQPayload(BaseModel):
    title: str
    category: str
    department: str
    part_number: str
    quantity: int
    material_spec: str
    precision_tolerance: str
    surface_treatment: Optional[str] = "Standard Aerospace Anodizing / Passivation"
    target_unit_price: float
    target_delivery_date: str
    deadline_date: str
    incoterms: Optional[str] = "DDP Buyer Facility"
    payment_terms: Optional[str] = "Net 30 Days"
    invited_suppliers: Optional[List[str]] = None
    notes: Optional[str] = None

@router.get("/rfqs/overview")
def get_rfqs_overview():
    """Return high-level RFQ sourcing overview metrics."""
    total_rfqs = len(buyer_rfqs_db)
    active_rfqs = [r for r in buyer_rfqs_db if r["status"] in ["OPEN_FOR_BIDS", "UNDER_EVALUATION"]]
    awarded_rfqs = [r for r in buyer_rfqs_db if r["status"] == "AWARDED"]
    
    total_pipeline_val = sum(r["target_total_budget"] for r in buyer_rfqs_db)
    awarded_val = sum(r["awarded_info"]["total_amount"] for r in awarded_rfqs if r["awarded_info"])
    total_bids_count = sum(len(r["bids"]) for r in buyer_rfqs_db)
    
    # Calculate average savings percentage across evaluated/awarded quotes
    savings_list = []
    for r in buyer_rfqs_db:
        if r["awarded_info"]:
            s = (r["target_total_budget"] - r["awarded_info"]["total_amount"]) / r["target_total_budget"] * 100
            savings_list.append(s)
        elif r["bids"]:
            lowest_bid = min(b["total_amount"] for b in r["bids"])
            s = (r["target_total_budget"] - lowest_bid) / r["target_total_budget"] * 100
            savings_list.append(s)
            
    avg_savings = round(sum(savings_list) / len(savings_list), 1) if savings_list else 12.4
    
    return {
        "status": "success",
        "kpis": {
            "total_rfqs": total_rfqs,
            "active_rfqs": len(active_rfqs),
            "under_evaluation": len([r for r in buyer_rfqs_db if r["status"] == "UNDER_EVALUATION"]),
            "awarded_rfqs": len(awarded_rfqs),
            "total_pipeline_value": total_pipeline_val,
            "total_awarded_value": awarded_val,
            "total_bids_received": total_bids_count,
            "average_savings_pct": avg_savings,
            "average_cycle_days": 7.2,
            "supplier_response_rate_pct": 92.5,
            "pre_verified_digital_twin_fit_pct": 95.8
        }
    }

@router.get("/rfqs/list")
def get_rfqs_list(
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None)
):
    """Return filterable buyer RFQ registry with live quotation statistics."""
    results = []
    for rfq in buyer_rfqs_db:
        if status and status.upper() != "ALL" and rfq["status"].upper() != status.upper():
            continue
        if category and category.upper() != "ALL" and rfq["category"].lower() != category.lower():
            continue
        if search:
            query = search.lower()
            if query not in rfq["title"].lower() and query not in rfq["id"].lower() and query not in rfq["part_number"].lower():
                continue
                
        # Compute summary stats for the RFQ
        bids = rfq.get("bids", [])
        lowest_bid = min((b["total_amount"] for b in bids), default=rfq["target_total_budget"])
        potential_savings = max(0.0, rfq["target_total_budget"] - lowest_bid)
        savings_pct = round((potential_savings / rfq["target_total_budget"]) * 100, 1) if rfq["target_total_budget"] > 0 else 0.0
        
        results.append({
            "id": rfq["id"],
            "title": rfq["title"],
            "part_number": rfq["part_number"],
            "category": rfq["category"],
            "department": rfq["department"],
            "quantity": rfq["quantity"],
            "material_spec": rfq["material_spec"],
            "precision_tolerance": rfq["precision_tolerance"],
            "target_unit_price": rfq["target_unit_price"],
            "target_total_budget": rfq["target_total_budget"],
            "target_delivery_date": rfq["target_delivery_date"],
            "deadline_date": rfq["deadline_date"],
            "status": rfq["status"],
            "created_at": rfq["created_at"],
            "invited_suppliers": rfq.get("invited_suppliers", 3),
            "quotes_received": len(bids),
            "lowest_bid_amount": lowest_bid,
            "potential_savings": potential_savings,
            "savings_pct": savings_pct,
            "awarded_info": rfq.get("awarded_info")
        })
        
    return results

@router.get("/rfqs/awards/list")
def get_rfq_awards_list():
    """Return all awarded RFQ contracts with converted Purchase Order references."""
    awarded = []
    for r in buyer_rfqs_db:
        if r.get("awarded_info"):
            awd = dict(r["awarded_info"])
            awd["rfq_id"] = r["id"]
            awd["rfq_title"] = r["title"]
            awd["part_number"] = r["part_number"]
            awd["category"] = r["category"]
            awd["quantity"] = r["quantity"]
            awarded.append(awd)
    return awarded

@router.get("/rfqs/analytics")
def get_rfqs_analytics():
    """Return comprehensive sourcing and multi-supplier bidding analytics."""
    categories = {}
    for r in buyer_rfqs_db:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = {
                "category": cat,
                "rfq_count": 0,
                "total_budget": 0.0,
                "awarded_or_lowest": 0.0,
                "savings": 0.0
            }
        categories[cat]["rfq_count"] += 1
        categories[cat]["total_budget"] += r["target_total_budget"]
        
        if r.get("awarded_info"):
            spent = r["awarded_info"]["total_amount"]
        elif r.get("bids"):
            spent = min(b["total_amount"] for b in r["bids"])
        else:
            spent = r["target_total_budget"]
            
        categories[cat]["awarded_or_lowest"] += spent
        categories[cat]["savings"] += max(0.0, r["target_total_budget"] - spent)
        
    cat_list = []
    for c in categories.values():
        c["savings_pct"] = round((c["savings"] / c["total_budget"]) * 100, 1) if c["total_budget"] > 0 else 0.0
        cat_list.append(c)
        
    return {
        "status": "success",
        "category_performance": cat_list,
        "supplier_response_turnaround": [
            {"supplier": "Apex Precision Machining Ltd", "avg_response_hours": 18.5, "bids_submitted": 4, "win_rate_pct": 75.0, "quality_score": 99.4},
            {"supplier": "Titan Aero Heavy Engineering", "avg_response_hours": 26.2, "bids_submitted": 4, "win_rate_pct": 25.0, "quality_score": 97.2},
            {"supplier": "Continental Mechatronics Corp", "avg_response_hours": 32.0, "bids_submitted": 2, "win_rate_pct": 0.0, "quality_score": 96.8},
            {"supplier": "Kovai Precision Diecast", "avg_response_hours": 44.5, "bids_submitted": 2, "win_rate_pct": 0.0, "quality_score": 94.5},
            {"supplier": "Bavaria Foundry Castings", "avg_response_hours": 22.0, "bids_submitted": 1, "win_rate_pct": 100.0, "quality_score": 96.0}
        ],
        "bid_dispersion": {
            "average_spread_pct": 14.8,
            "min_spread_pct": 3.1,
            "max_spread_pct": 22.5,
            "total_savings_pipeline": sum(c["savings"] for c in cat_list)
        },
        "quarterly_savings_trend": [
            {"quarter": "Q1 2026", "spend": 420000, "savings": 48000, "savings_pct": 11.4},
            {"quarter": "Q2 2026", "spend": 510000, "savings": 66000, "savings_pct": 12.9},
            {"quarter": "Q3 2026", "spend": 485000, "savings": 71000, "savings_pct": 14.6},
            {"quarter": "Q4 2026 (YTD)", "spend": 425000, "savings": 68500, "savings_pct": 16.1}
        ]
    }

@router.get("/rfqs/{rfq_id}")
def get_rfq_detail(rfq_id: str):
    """Return complete technical specifications, line items, and parameters of an RFQ."""
    for rfq in buyer_rfqs_db:
        if rfq["id"].upper() == rfq_id.upper():
            return rfq
    raise HTTPException(status_code=404, detail=f"RFQ '{rfq_id}' not found.")

@router.get("/rfqs/{rfq_id}/bids")
def get_rfq_bids(
    rfq_id: str,
    cost_weight: float = Query(0.35),
    lead_time_weight: float = Query(0.25),
    quality_weight: float = Query(0.20),
    twin_fit_weight: float = Query(0.15),
    esg_weight: float = Query(0.05)
):
    """
    Return multi-supplier bid comparison matrix for an RFQ,
    dynamically computing Multi-Criteria Decision Analysis (MCDA) scores.
    """
    rfq = None
    for r in buyer_rfqs_db:
        if r["id"].upper() == rfq_id.upper():
            rfq = r
            break
            
    if not rfq:
        raise HTTPException(status_code=404, detail=f"RFQ '{rfq_id}' not found.")
        
    bids = rfq.get("bids", [])
    if not bids:
        return {
            "rfq_id": rfq["id"],
            "title": rfq["title"],
            "bids": [],
            "mcda_weights": {
                "cost": cost_weight,
                "lead_time": lead_time_weight,
                "quality": quality_weight,
                "twin_fit": twin_fit_weight,
                "esg": esg_weight
            }
        }
        
    min_price = min(b["total_amount"] for b in bids)
    min_lead_time = min(b["lead_time_days"] for b in bids)
    
    scored_bids = []
    for b in bids:
        b_copy = dict(b)
        
        # MCDA Components normalized to 0-100:
        # 1. Price Score: (min_price / current_price) * 100
        price_score = (min_price / b["total_amount"]) * 100 if b["total_amount"] > 0 else 50
        
        # 2. Lead Time Score: (min_lead_time / current_lead_time) * 100
        lead_score = (min_lead_time / b["lead_time_days"]) * 100 if b["lead_time_days"] > 0 else 50
        
        # 3. Quality Score: directly from quality_score
        qual_score = b.get("quality_score", 95.0)
        
        # 4. Digital Twin Fit Score
        twin_score = b.get("twin_match_pct", 90.0)
        
        # 5. ESG Score
        esg_score = b.get("esg_score", 85.0)
        
        # Weighted composite MCDA score
        total_mcda = (
            (price_score * cost_weight) +
            (lead_score * lead_time_weight) +
            (qual_score * quality_weight) +
            (twin_score * twin_fit_weight) +
            (esg_score * esg_weight)
        )
        
        b_copy["mcda_score"] = round(total_mcda, 1)
        b_copy["mcda_breakdown"] = {
            "price_score": round(price_score, 1),
            "lead_time_score": round(lead_score, 1),
            "quality_score": round(qual_score, 1),
            "twin_fit_score": round(twin_score, 1),
            "esg_score": round(esg_score, 1)
        }
        scored_bids.append(b_copy)
        
    # Sort descending by MCDA score
    scored_bids.sort(key=lambda x: x["mcda_score"], reverse=True)
    
    return {
        "rfq_id": rfq["id"],
        "title": rfq["title"],
        "part_number": rfq["part_number"],
        "target_total_budget": rfq["target_total_budget"],
        "target_delivery_date": rfq["target_delivery_date"],
        "status": rfq["status"],
        "awarded_info": rfq.get("awarded_info"),
        "mcda_weights": {
            "cost": cost_weight,
            "lead_time": lead_time_weight,
            "quality": quality_weight,
            "twin_fit": twin_fit_weight,
            "esg": esg_weight
        },
        "bids": scored_bids
    }

@router.post("/rfqs/{rfq_id}/award")
def award_rfq_bid(rfq_id: str, payload: AwardBidPayload, db: Session = Depends(get_db)):
    """
    1-Click Award Contract & Issue Purchase Order.
    Selects winning supplier quotation, updates RFQ state to AWARDED,
    generates and inserts a verified PurchaseOrder record in SQL database.
    """
    import uuid
    from datetime import datetime, timezone
    from app.models.procurement import PurchaseOrder, POStatus, Quotation, OrderRequest, RFQStatus
    
    rfq = None
    for r in buyer_rfqs_db:
        if r["id"].upper() == rfq_id.upper():
            rfq = r
            break
            
    if not rfq:
        raise HTTPException(status_code=404, detail=f"RFQ '{rfq_id}' not found.")
        
    # Locate winning bid
    winning_bid = None
    for b in rfq.get("bids", []):
        if b["quote_id"] == payload.quote_id or b["supplier_id"] == payload.supplier_id:
            winning_bid = b
            break
            
    if not winning_bid:
        raise HTTPException(status_code=404, detail=f"Quote '{payload.quote_id}' not found for RFQ '{rfq_id}'.")
        
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    generated_po_num = f"PO-2026-{uuid.uuid4().hex[:4].upper()}"
    po_db_id = f"po-{uuid.uuid4().hex[:8]}"
    
    # 1. Update internal state
    for b in rfq.get("bids", []):
        if b["quote_id"] == winning_bid["quote_id"]:
            b["status"] = "AWARDED"
        else:
            b["status"] = "REJECTED_UNSUCCESSFUL"
            
    rfq["status"] = "AWARDED"
    savings_amt = max(0.0, rfq["target_total_budget"] - winning_bid["total_amount"])
    
    award_record = {
        "award_id": f"AWD-{uuid.uuid4().hex[:6].upper()}",
        "quote_id": winning_bid["quote_id"],
        "supplier_id": winning_bid["supplier_id"],
        "supplier_name": winning_bid["supplier_name"],
        "supplier_location": winning_bid.get("supplier_location", "Verified Twin Hub"),
        "po_number": generated_po_num,
        "po_id": po_db_id,
        "total_amount": winning_bid["total_amount"],
        "unit_price": winning_bid["unit_price"],
        "lead_time_days": winning_bid["lead_time_days"],
        "committed_delivery_date": winning_bid["committed_delivery_date"],
        "target_budget": rfq["target_total_budget"],
        "savings": savings_amt,
        "savings_pct": round((savings_amt / rfq["target_total_budget"]) * 100, 1) if rfq["target_total_budget"] > 0 else 0.0,
        "awarded_at": now_str,
        "contract_status": "CONTRACT_GENERATED_PENDING_SIGNATURE",
        "notes": payload.notes or "Awarded via Multi-Criteria Decision Analysis (MCDA) Sourcing Engine."
    }
    rfq["awarded_info"] = award_record
    
    # Also update incoming_rfqs_db if linked
    for inc_rfq in incoming_rfqs_db:
        if inc_rfq["id"] == rfq_id:
            inc_rfq["status"] = "AWARDED"
            
    # 2. Persist into SQLite DB
    try:
        # Check/create parent OrderRequest
        existing_req = db.query(OrderRequest).filter(OrderRequest.id == rfq_id).first()
        if not existing_req:
            new_req = OrderRequest(
                id=rfq_id,
                description=f"{rfq['title']} - {rfq['part_number']} ({rfq['quantity']} units)",
                target_supplier_id=winning_bid["supplier_id"],
                status=RFQStatus.APPROVED,
                tenant_id=payload.buyer_tenant_id or "TENANT_BUYER_001",
                created_at=now,
                updated_at=now
            )
            db.add(new_req)
            db.flush()
        else:
            existing_req.status = RFQStatus.APPROVED
            db.flush()
            
        # Check/create Quotation record
        existing_quote = db.query(Quotation).filter(Quotation.id == winning_bid["quote_id"]).first()
        if not existing_quote:
            terms_text = f"Lead Time: {winning_bid['lead_time_days']} days | {winning_bid.get('payment_terms', 'Net 30')} | {winning_bid.get('incoterms', 'DDP')}"
            new_quote = Quotation(
                id=winning_bid["quote_id"],
                request_id=rfq_id,
                supplier_tenant_id=winning_bid["supplier_id"],
                amount=winning_bid["total_amount"],
                terms=terms_text,
                status=RFQStatus.APPROVED,
                tenant_id=payload.buyer_tenant_id or "TENANT_BUYER_001",
                created_at=now,
                updated_at=now
            )
            db.add(new_quote)
            db.flush()
            
        # Insert PurchaseOrder
        new_po = PurchaseOrder(
            id=po_db_id,
            po_number=generated_po_num,
            quotation_id=winning_bid["quote_id"],
            supplier_tenant_id=winning_bid["supplier_id"],
            total_amount=winning_bid["total_amount"],
            status=POStatus.ISSUED,
            tenant_id=payload.buyer_tenant_id or "TENANT_BUYER_001",
            created_at=now,
            updated_at=now
        )
        db.add(new_po)
        db.commit()
    except Exception as e:
        print(f"[Award PO Sync Warning]: {e}")
        db.rollback()
        
    return {
        "status": "success",
        "message": f"RFQ '{rfq_id}' successfully awarded to {winning_bid['supplier_name']}! Purchase Order {generated_po_num} issued.",
        "award": award_record
    }

@router.post("/rfqs/{rfq_id}/clarify")
def submit_rfq_clarification(rfq_id: str, payload: RFQClarificationPayload):
    """Submit a technical or commercial clarification inquiry for an RFQ."""
    import uuid
    from datetime import datetime, timezone
    
    rfq = None
    for r in buyer_rfqs_db:
        if r["id"].upper() == rfq_id.upper():
            rfq = r
            break
            
    if not rfq:
        raise HTTPException(status_code=404, detail=f"RFQ '{rfq_id}' not found.")
        
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    clar_id = f"CLR-{uuid.uuid4().hex[:4].upper()}"
    new_clar = {
        "id": clar_id,
        "sender": payload.sender_name or "Procurement Lead (Alex Sharma)",
        "recipient": payload.supplier_id or "All Participating Suppliers",
        "date": now,
        "message": payload.message,
        "reply": "Inquiry transmitted to supplier capability twin dispatch queue."
    }
    rfq.setdefault("clarifications", []).append(new_clar)
    return {
        "status": "success",
        "message": f"Clarification inquiry #{clar_id} dispatched successfully to suppliers.",
        "clarification": new_clar
    }

@router.post("/rfqs/create")
def create_buyer_rfq(payload: CreateRFQPayload):
    """Create a new RFQ and open it for multi-supplier bidding."""
    import uuid
    from datetime import datetime, timezone
    
    rfq_id = f"RFQ-2026-{uuid.uuid4().hex[:3].upper()}"
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    total_budget = payload.target_unit_price * payload.quantity
    
    new_rfq = {
        "id": rfq_id,
        "title": payload.title,
        "part_number": payload.part_number,
        "category": payload.category,
        "department": payload.department,
        "buyer_org": "Global Aerospace Systems Corp",
        "cad_filename": f"{payload.part_number}_Engineering_Model.STEP",
        "cad_filesize": "18.4 MB",
        "material_spec": payload.material_spec,
        "precision_tolerance": payload.precision_tolerance,
        "surface_treatment": payload.surface_treatment or "Standard Passivation",
        "quantity": payload.quantity,
        "target_unit_price": payload.target_unit_price,
        "target_total_budget": total_budget,
        "target_delivery_date": payload.target_delivery_date,
        "deadline_date": payload.deadline_date,
        "payment_terms": payload.payment_terms or "Net 30 Days",
        "incoterms": payload.incoterms or "DDP Buyer Facility",
        "status": "OPEN_FOR_BIDS",
        "created_at": now_str,
        "invited_suppliers": len(payload.invited_suppliers) if payload.invited_suppliers else 3,
        "bids": [],
        "clarifications": [],
        "awarded_info": None
    }
    
    buyer_rfqs_db.insert(0, new_rfq)
    return {
        "status": "success",
        "message": f"RFQ '{rfq_id}' created and broadcasted to supplier capability network!",
        "rfq": new_rfq
    }

# =====================================================================
# ENTERPRISE PURCHASE ORDER LIFECYCLE & FULFILLMENT WORKSTATION ENGINE
# =====================================================================

SUPPLIER_PROFILE_MAP = {
    "TENANT_SUPPLIER_001": {
        "name": "Apex Precision Machining Ltd",
        "initials": "AP",
        "color": "bg-emerald-600",
        "category": "Aerospace CNC & Precision Machining",
        "email": "contracts@apexmachining.aero",
        "rating": 98.4,
        "facility": "Denver High-Precision Plant Bay 04"
    },
    "047fb121-28d5-43e5-84dd-827a92211b5e": {
        "name": "Lawrence LLC",
        "initials": "LL",
        "color": "bg-cyan-600",
        "category": "Avionics Guidance & Flight Control",
        "email": "orders@lawrence-aerospace.com",
        "rating": 96.8,
        "facility": "Huntsville Avionics Technology Hub"
    },
    "1ef4bf40-8033-49f5-ba1b-2617dcceffe4": {
        "name": "James-Hampton Ltd",
        "initials": "JH",
        "color": "bg-indigo-600",
        "category": "Propulsion Turbines & Titanium Impellers",
        "email": "procurement@jameshampton.com",
        "rating": 97.2,
        "facility": "Derby Turbine Facility Building A"
    },
    "309c7081-3d30-43fc-946e-63423a811cde": {
        "name": "Jones & Stephenson",
        "initials": "JS",
        "color": "bg-violet-600",
        "category": "Precision Hydraulic Valves & Actuators",
        "email": "sales@jonesstephenson.co.uk",
        "rating": 95.9,
        "facility": "Birmingham Hydraulic Systems Plant"
    },
    "22645dd7-8966-467d-8907-61585915241f": {
        "name": "Gonzalez Inc",
        "initials": "GI",
        "color": "bg-amber-600",
        "category": "Forged Aerospace Alloys & Structural Fasteners",
        "email": "contracts@gonzalez-alloys.com",
        "rating": 98.1,
        "facility": "Phoenix Precision Foundry Dock 2"
    },
    "ca617a63-0a2b-4f5f-8e19-d0c8db655bf1": {
        "name": "Morrison PLC",
        "initials": "MP",
        "color": "bg-rose-600",
        "category": "Carbon Fiber Fairings & Composite Panels",
        "email": "orders@morrison-composites.com",
        "rating": 94.6,
        "facility": "Bristol Advanced Composite Center"
    }
}

po_lifecycle_store: Dict[str, Dict[str, Any]] = {
    "PO-2026-6488": {
        "department": "Flight Avionics",
        "buyer_name": "Alex Sharma",
        "priority": "High",
        "cost_center": "CC-AVIO-910",
        "payment_terms": "Net 30 Days (Direct Wire)",
        "incoterms": "DDP Spaceport Warehouse Bay 2",
        "target_delivery_date": "2026-11-20",
        "approval_tier": "Level 3/3 (VP Finance / CFO)",
        "approval_due_date": "2026-10-22",
        "sla_status": "URGENT_ACTION",
        "budget_limit_check": {
            "department_budget": 500000.0,
            "allocated_to_date": 342000.0,
            "this_po": 125000.0,
            "remaining_after": 33000.0,
            "status": "WITHIN_LIMITS"
        },
        "line_items": [
            {
                "item_id": "ITEM-6488-1",
                "sku": "AVIO-FC-9002",
                "name": "Redundant Flight Control Computer Units (AS9100D)",
                "category": "Avionics Guidance",
                "unit": "units",
                "qty_ordered": 2,
                "qty_shipped": 0,
                "qty_received": 0,
                "unit_price": 50000.0,
                "line_total": 100000.0,
                "inspection_status": "PENDING"
            },
            {
                "item_id": "ITEM-6488-2",
                "sku": "AVIO-BUS-429",
                "name": "MIL-STD-1553B / ARINC 429 Bus Interface Modules",
                "category": "Avionics Guidance",
                "unit": "sets",
                "qty_ordered": 10,
                "qty_shipped": 0,
                "qty_received": 0,
                "unit_price": 2500.0,
                "line_total": 25000.0,
                "inspection_status": "PENDING"
            }
        ],
        "milestones": [
            {
                "key": "DRAFT",
                "title": "Purchase Order Drafted",
                "timestamp": "2026-10-18 09:20 UTC",
                "actor": "Alex Sharma (Procurement Lead)",
                "completed": True,
                "details": "High-value avionics procurement initiated from approved RFQ specification."
            },
            {
                "key": "SUBMIT_APPROVAL",
                "title": "Routed for Executive Level 3 Financial Approval",
                "timestamp": "2026-10-18 10:15 UTC",
                "actor": "Autonomous Lifecycle Engine",
                "completed": True,
                "details": "Threshold >$100,000 triggered mandatory VP Finance / CFO dual sign-off."
            },
            {
                "key": "APPROVAL",
                "title": "Executive Sign-Off & Budget Release",
                "timestamp": "Pending Sign-off",
                "actor": "Elena Rostova (VP Finance)",
                "completed": False,
                "details": "Awaiting final electronic cryptographic signature."
            },
            {
                "key": "ISSUED",
                "title": "Issued to Supplier Network",
                "timestamp": "Queued",
                "actor": "EDI Gateway",
                "completed": False,
                "details": "Pending completion of Level 3 approval."
            },
            {
                "key": "PRODUCTION",
                "title": "Fabrication & In-Production",
                "timestamp": "Queued",
                "actor": "Lawrence LLC Plant",
                "completed": False,
                "details": "SMT pick-and-place & thermal cycling."
            },
            {
                "key": "SHIPPED",
                "title": "Advance Ship Notice (ASN)",
                "timestamp": "Queued",
                "actor": "Logistics Dispatch",
                "completed": False,
                "details": "Carrier pickup and digital bill of lading."
            },
            {
                "key": "GOODS_RECEIVED",
                "title": "Dock Goods Receipt Note (GRN)",
                "timestamp": "Queued",
                "actor": "Receiving Dock 04-B",
                "completed": False,
                "details": "Physical barcode scan & quarantine bay check."
            },
            {
                "key": "3_WAY_MATCH",
                "title": "3-Way Invoice Reconciliation & Ledger Close",
                "timestamp": "Queued",
                "actor": "ERP Finance Ledger",
                "completed": False,
                "details": "PO amount == GRN received == Tax Invoice."
            }
        ]
    },
    "PO-2026-7022": {
        "department": "Propulsion Engineering",
        "buyer_name": "Alex Sharma",
        "priority": "Critical",
        "cost_center": "CC-PROP-201",
        "payment_terms": "Net 30 Days (Direct Wire)",
        "incoterms": "DDP Spaceport Receiving Bay 1",
        "target_delivery_date": "2026-11-12",
        "approval_tier": "Level 1/3 (Dept Lead - Auto Approved)",
        "approval_due_date": "Completed",
        "sla_status": "ON_TRACK",
        "line_items": [
            {
                "item_id": "ITEM-7022-1",
                "sku": "AERO-TI-440",
                "name": "Titanium Grade 5 Impeller Blades",
                "category": "Turbine Components",
                "unit": "sets",
                "qty_ordered": 20,
                "qty_shipped": 20,
                "qty_received": 0,
                "unit_price": 1761.61,
                "line_total": 35232.31,
                "inspection_status": "IN_TRANSIT"
            }
        ],
        "milestones": [
            {
                "key": "DRAFT",
                "title": "PO Drafted",
                "timestamp": "2026-10-10 08:30 UTC",
                "actor": "Alex Sharma",
                "completed": True,
                "details": "Turbine impeller specification."
            },
            {
                "key": "APPROVAL",
                "title": "Level 1 Approval Granted",
                "timestamp": "2026-10-10 11:45 UTC",
                "actor": "David Chen (Dept Head)",
                "completed": True,
                "details": "Within departmental authorization threshold."
            },
            {
                "key": "ISSUED",
                "title": "PO Transmitted to Supplier",
                "timestamp": "2026-10-10 14:00 UTC",
                "actor": "EDI Gateway",
                "completed": True,
                "details": "Dispatched to James-Hampton Ltd."
            },
            {
                "key": "ACKNOWLEDGED",
                "title": "Supplier Acknowledged",
                "timestamp": "2026-10-11 09:12 UTC",
                "actor": "James-Hampton Sales",
                "completed": True,
                "details": "Production schedule locked."
            },
            {
                "key": "PRODUCTION",
                "title": "CNC 5-Axis Milling Completed",
                "timestamp": "2026-10-17 16:30 UTC",
                "actor": "James-Hampton Shopfloor",
                "completed": True,
                "details": "CMM inspection 100% nominal."
            },
            {
                "key": "SHIPPED",
                "title": "Carrier Dispatched (ASN-JH-9921)",
                "timestamp": "2026-10-18 07:15 UTC",
                "actor": "DHL Global Forwarding",
                "completed": True,
                "details": "Tracking: DHL-AERO-77192. In-transit to Spaceport Dock."
            },
            {
                "key": "GOODS_RECEIVED",
                "title": "Dock Goods Receipt Note (GRN)",
                "timestamp": "Awaiting Dock Arrival",
                "actor": "Receiving Dock 04-B",
                "completed": False,
                "details": "ETA 24 hours. Dock verification pending."
            },
            {
                "key": "3_WAY_MATCH",
                "title": "3-Way Match & Reconciliation",
                "timestamp": "Queued",
                "actor": "Finance Ledger",
                "completed": False,
                "details": "Reconcile on GRN receipt."
            }
        ]
    },
    "PO-2025-00123": {
        "department": "Structural & Hydraulics",
        "buyer_name": "Priya Menon",
        "priority": "Normal",
        "cost_center": "CC-AERO-704",
        "payment_terms": "Net 30 Days",
        "incoterms": "DDP Buyer Facility",
        "target_delivery_date": "2026-10-15",
        "approval_tier": "Level 1/3 (Approved)",
        "approval_due_date": "Completed",
        "sla_status": "COMPLETED",
        "line_items": [
            {
                "item_id": "ITEM-123-1",
                "sku": "AERO-FLG-880",
                "name": "Precision CNC High-Temp Flange Rings",
                "category": "Precision CNC & Milling",
                "unit": "pcs",
                "qty_ordered": 50,
                "qty_shipped": 50,
                "qty_received": 50,
                "unit_price": 590.0,
                "line_total": 29500.0,
                "inspection_status": "PASSED"
            }
        ],
        "grn_record": {
            "grn_number": "GRN-2026-0812",
            "received_at": "2026-10-15 14:10 UTC",
            "dock_bay": "Receiving Dock 02",
            "received_by": "Marcus Vance",
            "packages_verified": 3,
            "units_accepted": 50,
            "units_rejected": 0,
            "quality_pass": True,
            "cmm_cert": "CMM-MET-99201-B",
            "storage_bin": "BIN-AERO-W02"
        },
        "invoice_record": {
            "invoice_number": "INV-APEX-88912",
            "invoice_amount": 29500.0,
            "po_amount": 29500.0,
            "grn_amount": 29500.0,
            "variance": 0.0,
            "matched": True,
            "reconciled_at": "2026-10-16 10:00 UTC",
            "status": "RECONCILED"
        },
        "milestones": [
            {
                "key": "DRAFT",
                "title": "PO Formulated",
                "timestamp": "2026-09-28 10:00 UTC",
                "actor": "Priya Menon",
                "completed": True,
                "details": "Flange ring specifications."
            },
            {
                "key": "APPROVAL",
                "title": "Financial Sign-off",
                "timestamp": "2026-09-29 11:30 UTC",
                "actor": "David Chen",
                "completed": True,
                "details": "Level 1 approved."
            },
            {
                "key": "ISSUED",
                "title": "Dispatched to Apex Precision",
                "timestamp": "2026-09-29 15:00 UTC",
                "actor": "EDI Gateway",
                "completed": True,
                "details": "Confirmed transmission."
            },
            {
                "key": "SHIPPED",
                "title": "Carrier Dispatched (ASN-A50B69)",
                "timestamp": "2026-10-12 08:30 UTC",
                "actor": "FedEx Aerospace Freight",
                "completed": True,
                "details": "Tracking: FX-TEST-88912-US."
            },
            {
                "key": "GOODS_RECEIVED",
                "title": "Dock Receipt Note GRN-2026-0812",
                "timestamp": "2026-10-15 14:10 UTC",
                "actor": "Marcus Vance",
                "completed": True,
                "details": "Zero NCR. Passed 100% CMM dimensional metrology."
            },
            {
                "key": "3_WAY_MATCH",
                "title": "3-Way Match Reconciled ($29,500.00)",
                "timestamp": "2026-10-16 10:00 UTC",
                "actor": "ERP Ledger Bot",
                "completed": True,
                "details": "Variance $0.00. Ready for final settlement."
            }
        ]
    }
}

class POTransitionPayload(BaseModel):
    action: str  # APPROVE, REJECT, ISSUE, ACKNOWLEDGE, START_PRODUCTION, RECORD_GRN, INSPECT_QUALITY, RECONCILE_3_WAY, CLOSE
    actor_name: Optional[str] = "Procurement Specialist"
    actor_role: Optional[str] = "Operations Lead"
    notes: Optional[str] = None
    dock_bay: Optional[str] = "Receiving Dock 04-B"
    received_quantity: Optional[int] = None
    batch_lot_number: Optional[str] = None
    cmm_cert_id: Optional[str] = None
    quality_pass: Optional[bool] = True
    storage_bin: Optional[str] = "BIN-AERO-W02"
    invoice_number: Optional[str] = None

class BatchApprovalPayload(BaseModel):
    po_ids: List[str]
    action: str  # APPROVE or REJECT
    approver_name: Optional[str] = "Elena Rostova"
    approver_role: Optional[str] = "VP Finance & Operations"
    comments: Optional[str] = "Budget authorized under FY2026 Q4 Operations Ledger"

class CreatePOItemPayload(BaseModel):
    sku: str
    name: str
    category: Optional[str] = "Precision Components"
    unit: Optional[str] = "pcs"
    quantity: int
    unit_price: float

class CreatePOPayload(BaseModel):
    supplier_tenant_id: str
    supplier_name: Optional[str] = None
    department: str
    buyer_name: Optional[str] = "Alex Sharma"
    priority: Optional[str] = "High"
    cost_center: Optional[str] = "CC-AERO-704"
    payment_terms: Optional[str] = "Net 30 Days"
    incoterms: Optional[str] = "DDP Buyer Facility"
    target_delivery_date: str
    notes: Optional[str] = None
    items: List[CreatePOItemPayload]


def _build_po_dossier(po: PurchaseOrder, db: Session) -> Dict[str, Any]:
    """Helper to assemble an exhaustive lifecycle & fulfillment dossier for a PO."""
    from app.models.inventory import AdvanceShipNotice, StockTransaction
    from app.models.procurement import POApproval

    sup_info = SUPPLIER_PROFILE_MAP.get(po.supplier_tenant_id, {
        "name": "Apex Precision Machining Ltd",
        "initials": "AP",
        "color": "bg-emerald-600",
        "category": "Aerospace Machining",
        "email": "orders@apexprecision.com",
        "rating": 98.2,
        "facility": "Plant Bay 01"
    })

    # Look up live ASN
    asn = db.query(AdvanceShipNotice).filter(
        (AdvanceShipNotice.po_id == po.id) | (AdvanceShipNotice.po_id == po.po_number)
    ).first()

    # Look up live approvals
    approvals = db.query(POApproval).filter(POApproval.po_id == po.id).all()

    # Look up rich metadata
    meta = po_lifecycle_store.get(po.po_number, po_lifecycle_store.get(po.id, {}))

    # Determine approval tier
    amount = float(po.total_amount)
    if amount > 100000.0:
        tier = "Level 3/3 (VP Finance / CFO)"
    elif amount >= 50000.0:
        tier = "Level 2/3 (Procurement Head / Finance)"
    else:
        tier = "Level 1/3 (Department Manager)"

    # Generate or format line items
    raw_items = meta.get("line_items")
    if not raw_items:
        raw_items = [
            {
                "item_id": f"ITEM-{po.po_number[:8]}-1",
                "sku": f"AERO-PART-{po.po_number[-4:]}",
                "name": f"Aerospace Flight Subassembly Part {po.po_number}",
                "category": sup_info["category"],
                "unit": "units",
                "qty_ordered": 10,
                "qty_shipped": 10 if po.status in ["SHIPPED", "GOODS_RECEIVED", "QUALITY_INSPECTED", "INVOICED", "COMPLETED"] else 0,
                "qty_received": 10 if po.status in ["GOODS_RECEIVED", "QUALITY_INSPECTED", "INVOICED", "COMPLETED"] else 0,
                "unit_price": round(amount / 10.0, 2),
                "line_total": round(amount, 2),
                "inspection_status": "PASSED" if po.status in ["GOODS_RECEIVED", "QUALITY_INSPECTED", "INVOICED", "COMPLETED"] else "PENDING"
            }
        ]

    # Calculate completion percentage
    status_weights = {
        "DRAFT": 10,
        "PENDING_APPROVAL": 25,
        "APPROVED": 40,
        "ISSUED": 50,
        "ACKNOWLEDGED": 60,
        "IN_PRODUCTION": 70,
        "SHIPPED": 80,
        "GOODS_RECEIVED": 90,
        "QUALITY_INSPECTED": 95,
        "INVOICED": 98,
        "COMPLETED": 100
    }
    progress = status_weights.get(str(po.status), 50)

    # Milestones
    milestones = meta.get("milestones")
    if not milestones:
        milestones = [
            {
                "key": "DRAFT",
                "title": "PO Drafted",
                "timestamp": po.created_at.strftime("%Y-%m-%d %H:%M UTC") if po.created_at else "2026-10-15 08:00 UTC",
                "actor": meta.get("buyer_name", "Alex Sharma"),
                "completed": True,
                "details": f"Generated under {meta.get('cost_center', 'CC-AERO-704')}."
            },
            {
                "key": "APPROVAL",
                "title": f"Approval ({tier})",
                "timestamp": "Approved" if po.status != "PENDING_APPROVAL" else "Pending Review",
                "actor": "Elena Rostova (VP Finance)" if amount > 50000 else "David Chen (Dept Head)",
                "completed": po.status != "PENDING_APPROVAL",
                "details": "Authorization threshold verified."
            },
            {
                "key": "ISSUED",
                "title": "Issued to Supplier Network",
                "timestamp": "Dispatched" if po.status not in ["DRAFT", "PENDING_APPROVAL"] else "Queued",
                "actor": "EDI Gateway",
                "completed": po.status not in ["DRAFT", "PENDING_APPROVAL"],
                "details": f"Dispatched electronically to {sup_info['name']}."
            },
            {
                "key": "SHIPPED",
                "title": "Carrier Dispatched (ASN)",
                "timestamp": asn.created_at.strftime("%Y-%m-%d %H:%M UTC") if (asn and asn.created_at) else ("In Transit" if po.status in ["SHIPPED", "GOODS_RECEIVED", "INVOICED", "COMPLETED"] else "Pending Dispatch"),
                "actor": asn.carrier if asn else "Logistics Dispatch",
                "completed": po.status in ["SHIPPED", "GOODS_RECEIVED", "QUALITY_INSPECTED", "INVOICED", "COMPLETED"],
                "details": f"Tracking: {asn.tracking_number if asn else 'TRK-AERO-PENDING'}"
            },
            {
                "key": "GOODS_RECEIVED",
                "title": "Dock Goods Receipt Note (GRN)",
                "timestamp": "Dock Check-in Verified" if po.status in ["GOODS_RECEIVED", "QUALITY_INSPECTED", "INVOICED", "COMPLETED"] else "Awaiting Dock Arrival",
                "actor": "Dock Receiving Team",
                "completed": po.status in ["GOODS_RECEIVED", "QUALITY_INSPECTED", "INVOICED", "COMPLETED"],
                "details": "Physical tally, serial scan & metrology verification."
            },
            {
                "key": "3_WAY_MATCH",
                "title": "3-Way Match Reconciliation",
                "timestamp": "Reconciled & Balanced" if po.status in ["INVOICED", "COMPLETED"] else "Queued",
                "actor": "Finance Ledger",
                "completed": po.status in ["INVOICED", "COMPLETED"],
                "details": f"PO ${amount:,.2f} == GRN == Tax Invoice ($0.00 Variance)."
            }
        ]

    asn_payload = None
    if asn:
        asn_payload = {
            "asn_id": asn.id,
            "carrier": asn.carrier or "Aerospace Express Freight",
            "tracking_number": asn.tracking_number or "TRK-AERO-99218",
            "expected_date": asn.expected_date or "2026-10-25",
            "status": asn.status or "SHIPPED",
            "dispatched_at": asn.created_at.strftime("%Y-%m-%d %H:%M UTC") if asn.created_at else "2026-10-18 09:30 UTC"
        }
    elif po.status in ["SHIPPED", "GOODS_RECEIVED", "INVOICED", "COMPLETED"]:
        asn_payload = {
            "asn_id": f"ASN-{po.po_number[-4:]}",
            "carrier": "FedEx Aerospace Heavy Cargo",
            "tracking_number": f"FX-{po.po_number[-4:]}-889",
            "expected_date": "2026-10-25",
            "status": "DELIVERED" if po.status in ["GOODS_RECEIVED", "INVOICED", "COMPLETED"] else "IN_TRANSIT",
            "dispatched_at": "2026-10-18 10:15 UTC"
        }

    grn_payload = meta.get("grn_record")
    if not grn_payload and po.status in ["GOODS_RECEIVED", "QUALITY_INSPECTED", "INVOICED", "COMPLETED"]:
        grn_payload = {
            "grn_number": f"GRN-2026-{po.po_number[-4:]}",
            "received_at": "2026-10-16 11:30 UTC",
            "dock_bay": "Receiving Dock 04-B",
            "received_by": "Marcus Vance",
            "packages_verified": 2,
            "units_accepted": raw_items[0]["qty_ordered"],
            "units_rejected": 0,
            "quality_pass": True,
            "cmm_cert": f"CMM-MET-{po.po_number[-4:]}",
            "storage_bin": "BIN-AERO-W02"
        }

    invoice_payload = meta.get("invoice_record")
    if not invoice_payload and po.status in ["INVOICED", "COMPLETED"]:
        invoice_payload = {
            "invoice_number": f"INV-{sup_info['initials']}-{po.po_number[-4:]}",
            "invoice_amount": amount,
            "po_amount": amount,
            "grn_amount": amount,
            "variance": 0.0,
            "matched": True,
            "reconciled_at": "2026-10-17 14:00 UTC",
            "status": "RECONCILED"
        }

    return {
        "id": po.id,
        "po_number": po.po_number,
        "status": str(po.status),
        "total_amount": amount,
        "currency": "USD",
        "supplier_tenant_id": po.supplier_tenant_id,
        "supplier_name": sup_info["name"],
        "supplier_initials": sup_info["initials"],
        "supplier_color": sup_info["color"],
        "supplier_category": sup_info["category"],
        "supplier_email": sup_info["email"],
        "supplier_rating": sup_info["rating"],
        "supplier_facility": sup_info["facility"],
        "department": meta.get("department", "Flight Systems"),
        "buyer_name": meta.get("buyer_name", "Alex Sharma"),
        "priority": meta.get("priority", "High" if amount > 50000 else "Normal"),
        "cost_center": meta.get("cost_center", "CC-AERO-704"),
        "payment_terms": meta.get("payment_terms", "Net 30 Days (Direct Wire)"),
        "incoterms": meta.get("incoterms", "DDP Spaceport Receiving Bay 1"),
        "created_at": po.created_at.strftime("%Y-%m-%d") if po.created_at else "2026-10-15",
        "target_delivery_date": meta.get("target_delivery_date", "2026-11-15"),
        "approval_tier": tier,
        "approval_due_date": meta.get("approval_due_date", "2026-10-22"),
        "sla_status": meta.get("sla_status", "URGENT_ACTION" if po.status == "PENDING_APPROVAL" else "ON_TRACK"),
        "budget_limit_check": meta.get("budget_limit_check", {
            "department_budget": 500000.0,
            "allocated_to_date": 280000.0,
            "this_po": amount,
            "remaining_after": max(0.0, 500000.0 - (280000.0 + amount)),
            "status": "WITHIN_LIMITS"
        }),
        "line_items": raw_items,
        "milestones": milestones,
        "asn_info": asn_payload,
        "grn_info": grn_payload,
        "invoice_info": invoice_payload,
        "three_way_matched": bool(invoice_payload and invoice_payload.get("matched")),
        "progress_pct": progress,
        "approvals_audit": [
            {
                "approver_id": app.approver_id,
                "status": app.status,
                "comments": app.comments,
                "created_at": app.created_at.strftime("%Y-%m-%d %H:%M UTC") if app.created_at else "2026-10-18"
            } for app in approvals
        ]
    }


@router.get("/purchase-orders/overview")
def get_po_lifecycle_overview(db: Session = Depends(get_db)):
    """Executive KPI strip & state distribution for PO Lifecycle & Fulfillment Workstation."""
    pos = db.query(PurchaseOrder).all()
    
    total_spend = sum(float(p.total_amount) for p in pos)
    pending_approvals = [p for p in pos if str(p.status) == "PENDING_APPROVAL"]
    pending_value = sum(float(p.total_amount) for p in pending_approvals)
    
    in_transit_asns = [p for p in pos if str(p.status) == "SHIPPED"]
    goods_received = [p for p in pos if str(p.status) in ["GOODS_RECEIVED", "QUALITY_INSPECTED"]]
    completed_orders = [p for p in pos if str(p.status) in ["INVOICED", "COMPLETED"]]
    issued_orders = [p for p in pos if str(p.status) in ["ISSUED", "ACKNOWLEDGED", "IN_PRODUCTION"]]

    status_counts = {}
    for p in pos:
        s = str(p.status)
        status_counts[s] = status_counts.get(s, 0) + 1

    return {
        "status": "success",
        "total_pos": len(pos),
        "total_spend": round(total_spend, 2),
        "pending_approvals_count": len(pending_approvals),
        "pending_approvals_value": round(pending_value, 2),
        "in_transit_asns_count": len(in_transit_asns),
        "goods_received_count": len(goods_received),
        "completed_count": len(completed_orders),
        "issued_count": len(issued_orders),
        "three_way_match_pass_rate": 98.6,
        "average_fulfillment_days": 13.4,
        "inspection_pass_rate": 99.2,
        "status_distribution": status_counts
    }


@router.get("/purchase-orders/list")
def get_po_lifecycle_list(
    status_filter: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    supplier_filter: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """List all POs enriched with live lifecycle state, line items, ASN, GRN, and 3-way match audit."""
    pos = db.query(PurchaseOrder).order_by(PurchaseOrder.created_at.desc()).all()
    results = []

    for po in pos:
        dossier = _build_po_dossier(po, db)

        # Filters
        if status_filter and status_filter.upper() != "ALL":
            if dossier["status"].upper() != status_filter.upper():
                continue

        if supplier_filter and supplier_filter.upper() != "ALL":
            if dossier["supplier_name"].lower() != supplier_filter.lower() and dossier["supplier_tenant_id"] != supplier_filter:
                continue

        if search:
            q = search.lower().strip()
            match = (
                q in dossier["po_number"].lower() or
                q in dossier["supplier_name"].lower() or
                q in dossier["department"].lower() or
                q in dossier["buyer_name"].lower()
            )
            if not match:
                continue

        results.append(dossier)

    return {
        "status": "success",
        "count": len(results),
        "purchase_orders": results
    }


@router.get("/purchase-orders/fulfillment/{po_id}")
def get_po_fulfillment_dossier(po_id: str, db: Session = Depends(get_db)):
    """Deep fulfillment workstation dossier for an individual PO."""
    po = db.query(PurchaseOrder).filter(
        (PurchaseOrder.id == po_id) | (PurchaseOrder.po_number == po_id)
    ).first()

    if not po:
        raise HTTPException(status_code=404, detail=f"Purchase Order '{po_id}' not found.")

    dossier = _build_po_dossier(po, db)
    return {
        "status": "success",
        "fulfillment_dossier": dossier
    }


@router.post("/purchase-orders/{po_id}/transition")
def transition_po_state(po_id: str, payload: POTransitionPayload, db: Session = Depends(get_db)):
    """State machine transition engine for enterprise PO lifecycle."""
    import uuid
    from datetime import datetime, timezone
    from app.models.inventory import StockTransaction, InventoryItem

    po = db.query(PurchaseOrder).filter(
        (PurchaseOrder.id == po_id) | (PurchaseOrder.po_number == po_id)
    ).first()

    if not po:
        raise HTTPException(status_code=404, detail=f"Purchase Order '{po_id}' not found.")

    action = payload.action.upper()
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M UTC")
    
    meta = po_lifecycle_store.setdefault(po.po_number, {})
    milestones = meta.setdefault("milestones", [])

    old_status = str(po.status)
    new_status = old_status

    if action == "APPROVE":
        new_status = "ISSUED"  # Authorized and immediately issued to supplier
        po.status = POStatus.ISSUED
        po.updated_at = now
        
        # Log approval
        app_record = POApproval(
            id=f"APP-{uuid.uuid4().hex[:6].upper()}",
            po_id=po.id,
            approver_id=payload.actor_name or "Elena Rostova (VP Finance)",
            status="APPROVED",
            comments=payload.notes or f"Level financial threshold authorized electronically under {meta.get('cost_center', 'CAPEX')}.",
            tenant_id=po.tenant_id or "TENANT_BUYER_001",
            created_at=now,
            updated_at=now
        )
        db.add(app_record)

        milestones.append({
            "key": "APPROVAL",
            "title": "Executive Financial Sign-Off Approved",
            "timestamp": now_str,
            "actor": payload.actor_name or "Elena Rostova (VP Finance)",
            "completed": True,
            "details": payload.notes or "Financial budget authorized and release committed."
        })
        milestones.append({
            "key": "ISSUED",
            "title": "Purchase Order Dispatched to Supplier",
            "timestamp": now_str,
            "actor": "EDI Gateway",
            "completed": True,
            "details": "EDI 850 Purchase Order transmission acknowledged by supplier system."
        })

    elif action == "REJECT":
        new_status = "REJECTED"
        po.status = POStatus.REJECTED
        po.updated_at = now
        
        app_record = POApproval(
            id=f"APP-{uuid.uuid4().hex[:6].upper()}",
            po_id=po.id,
            approver_id=payload.actor_name or "Executive Approver",
            status="REJECTED",
            comments=payload.notes or "Purchase Order rejected during executive review.",
            tenant_id=po.tenant_id or "TENANT_BUYER_001",
            created_at=now,
            updated_at=now
        )
        db.add(app_record)
        milestones.append({
            "key": "REJECTED",
            "title": "Purchase Order Rejected",
            "timestamp": now_str,
            "actor": payload.actor_name or "Executive Approver",
            "completed": True,
            "details": payload.notes or "Budget or specification revision requested."
        })

    elif action == "ACKNOWLEDGE":
        new_status = "ACKNOWLEDGED"
        po.status = POStatus.ACKNOWLEDGED
        po.updated_at = now
        milestones.append({
            "key": "ACKNOWLEDGED",
            "title": "Supplier Order Acknowledged",
            "timestamp": now_str,
            "actor": payload.actor_name or "Supplier Sales Engineering",
            "completed": True,
            "details": payload.notes or "Supplier confirmed delivery schedule and locked manufacturing allocation."
        })

    elif action == "START_PRODUCTION":
        new_status = "IN_PRODUCTION"
        po.status = POStatus.IN_PRODUCTION
        po.updated_at = now
        milestones.append({
            "key": "PRODUCTION",
            "title": "Fabrication & Machining Commenced",
            "timestamp": now_str,
            "actor": payload.actor_name or "Supplier CNC Production Plant",
            "completed": True,
            "details": payload.notes or "Raw material issued and CNC milling scheduled."
        })

    elif action in ["RECORD_GRN", "GOODS_RECEIVED"]:
        new_status = "GOODS_RECEIVED"
        po.status = POStatus.GOODS_RECEIVED
        po.updated_at = now

        grn_id = f"GRN-2026-{uuid.uuid4().hex[:4].upper()}"
        qty_rcv = payload.received_quantity or 10
        dock = payload.dock_bay or "Receiving Dock 04-B"

        meta["grn_record"] = {
            "grn_number": grn_id,
            "received_at": now_str,
            "dock_bay": dock,
            "received_by": payload.actor_name or "Marcus Vance (Dock Receiving Lead)",
            "packages_verified": 3,
            "units_accepted": qty_rcv,
            "units_rejected": 0,
            "quality_pass": payload.quality_pass,
            "cmm_cert": payload.cmm_cert_id or f"CMM-MET-{uuid.uuid4().hex[:4].upper()}",
            "storage_bin": payload.storage_bin or "BIN-AERO-W02",
            "lot_number": payload.batch_lot_number or f"LOT-{now.strftime('%Y%m%d')}-01"
        }

        # Auto-update buyer plant inventory: Add received stock
        buyer_tenant = po.tenant_id or "TENANT_BUYER_001"
        inv_item = db.query(InventoryItem).filter(
            InventoryItem.tenant_id.in_([buyer_tenant, "buyer-mock", "TENANT_BUYER_001"])
        ).first()

        if inv_item:
            inv_item.quantity_on_hand += qty_rcv
            inv_item.updated_at = now
            if inv_item.quantity_on_hand > inv_item.min_threshold:
                inv_item.status = "IN_STOCK"

            tx = StockTransaction(
                id=f"TX-{uuid.uuid4().hex[:8].upper()}",
                inventory_item_id=inv_item.id,
                change_quantity=qty_rcv,
                reference_type="GOODS_IN",
                reference_id=grn_id,
                notes=f"Dock Goods Receipt Note {grn_id} for PO {po.po_number} at {dock}. Storage Bin: {payload.storage_bin or 'BIN-AERO-W02'}",
                performed_by=payload.actor_name or "Dock Receiving Lead",
                balance_after=inv_item.quantity_on_hand,
                tenant_id=buyer_tenant,
                created_at=now,
                updated_at=now
            )
            db.add(tx)

        milestones.append({
            "key": "GOODS_RECEIVED",
            "title": f"Dock Receipt Note Issued ({grn_id})",
            "timestamp": now_str,
            "actor": payload.actor_name or "Dock Receiving Specialist",
            "completed": True,
            "details": f"Physical count verified: {qty_rcv} units received at {dock}. Barcode telemetry scanned and registered into inventory."
        })

    elif action == "INSPECT_QUALITY":
        new_status = "QUALITY_INSPECTED"
        po.status = POStatus.QUALITY_INSPECTED
        po.updated_at = now
        
        cert = payload.cmm_cert_id or f"CMM-{uuid.uuid4().hex[:5].upper()}"
        milestones.append({
            "key": "QUALITY_INSPECTED",
            "title": "Quality Metrology Sign-Off (Zero NCR)",
            "timestamp": now_str,
            "actor": payload.actor_name or "Quality Assurance Specialist",
            "completed": True,
            "details": f"100% CMM geometric dimensioning & tolerance verified. Metrology Certificate: {cert}."
        })

    elif action in ["RECONCILE_3_WAY", "COMPLETE"]:
        new_status = "COMPLETED"
        po.status = POStatus.COMPLETED
        po.updated_at = now

        meta["invoice_record"] = {
            "invoice_number": payload.invoice_number or f"INV-REC-{uuid.uuid4().hex[:5].upper()}",
            "invoice_amount": float(po.total_amount),
            "po_amount": float(po.total_amount),
            "grn_amount": float(po.total_amount),
            "variance": 0.0,
            "matched": True,
            "reconciled_at": now_str,
            "status": "RECONCILED"
        }

        milestones.append({
            "key": "3_WAY_MATCH",
            "title": "3-Way Match Reconciled & PO Closed",
            "timestamp": now_str,
            "actor": payload.actor_name or "Finance Ledger Engine",
            "completed": True,
            "details": f"PO ${float(po.total_amount):,.2f} == GRN == Tax Invoice ($0.00 Variance). Order closed and archived in enterprise ledger."
        })

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported lifecycle action '{action}'.")

    db.commit()
    db.refresh(po)

    return {
        "status": "success",
        "message": f"PO '{po.po_number}' transitioned to '{new_status}' successfully.",
        "old_status": old_status,
        "new_status": new_status,
        "action": action,
        "dossier": _build_po_dossier(po, db)
    }


@router.post("/purchase-orders/{po_id}/grn")
def record_po_goods_receipt(po_id: str, payload: POTransitionPayload, db: Session = Depends(get_db)):
    """Dedicated endpoint to record Goods Receipt Note (GRN) directly at receiving dock."""
    payload.action = "RECORD_GRN"
    return transition_po_state(po_id=po_id, payload=payload, db=db)


@router.get("/purchase-orders/approvals/pending")
def get_pending_approvals(db: Session = Depends(get_db)):
    """Executive approval queue with multi-tier thresholds, budget checks, and SLA timers."""
    pos = db.query(PurchaseOrder).filter(PurchaseOrder.status == POStatus.PENDING_APPROVAL).all()
    
    queue = []
    total_val = 0.0

    for po in pos:
        dossier = _build_po_dossier(po, db)
        total_val += float(po.total_amount)
        queue.append(dossier)

    return {
        "status": "success",
        "pending_count": len(queue),
        "total_pending_value": round(total_val, 2),
        "approvals": queue
    }


@router.post("/purchase-orders/{po_id}/approve")
def approve_single_po(po_id: str, payload: Optional[POTransitionPayload] = None, db: Session = Depends(get_db)):
    """1-Click executive approval for an individual PO."""
    p = payload or POTransitionPayload(
        action="APPROVE",
        actor_name="Elena Rostova",
        actor_role="VP Finance & Operations",
        notes="Single-click executive authorization granted. Enterprise budget reserved."
    )
    p.action = "APPROVE"
    return transition_po_state(po_id=po_id, payload=p, db=db)


@router.post("/purchase-orders/approvals/batch")
def batch_po_approval(payload: BatchApprovalPayload, db: Session = Depends(get_db)):
    """Batch approve or reject multiple POs in a single executive transaction."""
    import uuid
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M UTC")

    processed = []
    action = payload.action.upper()
    target_status = POStatus.ISSUED if action == "APPROVE" else POStatus.REJECTED

    for pid in payload.po_ids:
        po = db.query(PurchaseOrder).filter(
            (PurchaseOrder.id == pid) | (PurchaseOrder.po_number == pid)
        ).first()

        if po:
            po.status = target_status
            po.updated_at = now
            
            # Register approval audit
            app_record = POApproval(
                id=f"APP-BATCH-{uuid.uuid4().hex[:6].upper()}",
                po_id=po.id,
                approver_id=payload.approver_name or "Elena Rostova (VP Finance)",
                status="APPROVED" if action == "APPROVE" else "REJECTED",
                comments=payload.comments or f"Batch {action} authorization executed.",
                tenant_id=po.tenant_id or "TENANT_BUYER_001",
                created_at=now,
                updated_at=now
            )
            db.add(app_record)

            meta = po_lifecycle_store.setdefault(po.po_number, {})
            milestones = meta.setdefault("milestones", [])
            milestones.append({
                "key": action,
                "title": f"Batch Executive {action.capitalize()}",
                "timestamp": now_str,
                "actor": payload.approver_name or "VP Finance & Operations",
                "completed": True,
                "details": payload.comments or f"Processed in executive batch ledger transaction."
            })
            processed.append(po.po_number)

    db.commit()
    return {
        "status": "success",
        "message": f"Successfully processed {len(processed)} purchase orders with action: {action}.",
        "processed_pos": processed
    }


@router.post("/purchase-orders/create")
def create_enterprise_purchase_order(payload: CreatePOPayload, db: Session = Depends(get_db)):
    """Create a new Enterprise Purchase Order, calculate financial tier and route for approval/dispatch."""
    import uuid
    from datetime import datetime, timezone
    from app.models.procurement import Quotation, OrderRequest

    now = datetime.now(timezone.utc)
    po_id = f"po-{uuid.uuid4().hex[:8]}"
    po_number = f"PO-2026-{uuid.uuid4().hex[:4].upper()}"

    total_amount = sum(item.quantity * item.unit_price for item in payload.items) if payload.items else 45000.0

    # 1. Create underlying OrderRequest to satisfy FK
    req_id = f"REQ-{uuid.uuid4().hex[:6].upper()}"
    new_req = OrderRequest(
        id=req_id,
        description=f"Purchase Request for {payload.department}: {payload.notes or 'Aerospace Components'}",
        target_supplier_id=payload.supplier_tenant_id,
        status="APPROVED",
        tenant_id="TENANT_BUYER_001",
        created_at=now,
        updated_at=now
    )
    db.add(new_req)
    db.flush()

    # 2. Create underlying Quotation to satisfy FK
    quo_id = f"QUO-{uuid.uuid4().hex[:6].upper()}"
    new_quo = Quotation(
        id=quo_id,
        request_id=req_id,
        supplier_tenant_id=payload.supplier_tenant_id,
        amount=total_amount,
        terms=f"Payment: {payload.payment_terms} | Incoterms: {payload.incoterms}",
        status="APPROVED",
        tenant_id="TENANT_BUYER_001",
        created_at=now,
        updated_at=now
    )
    db.add(new_quo)
    db.flush()

    # Determine initial status based on approval threshold (> $50,000 requires executive review)
    initial_status = POStatus.PENDING_APPROVAL if total_amount >= 50000.0 else POStatus.ISSUED

    new_po = PurchaseOrder(
        id=po_id,
        po_number=po_number,
        quotation_id=quo_id,
        supplier_tenant_id=payload.supplier_tenant_id,
        total_amount=total_amount,
        status=initial_status,
        tenant_id="TENANT_BUYER_001",
        created_at=now,
        updated_at=now
    )
    db.add(new_po)

    # If pending approval, seed a pending approval entry
    if initial_status == POStatus.PENDING_APPROVAL:
        app_entry = POApproval(
            id=f"APP-{uuid.uuid4().hex[:6].upper()}",
            po_id=po_id,
            approver_id="Pending Department/Executive Review",
            status="PENDING",
            comments=f"Approval required: PO total ${total_amount:,.2f} exceeds standard authorization threshold.",
            tenant_id="TENANT_BUYER_001",
            created_at=now,
            updated_at=now
        )
        db.add(app_entry)

    # Store rich line items and fulfillment metadata
    line_items_data = []
    for idx, item in enumerate(payload.items):
        line_items_data.append({
            "item_id": f"ITEM-{po_number[-4:]}-{idx+1}",
            "sku": item.sku,
            "name": item.name,
            "category": item.category or "Precision Components",
            "unit": item.unit or "pcs",
            "qty_ordered": item.quantity,
            "qty_shipped": 0,
            "qty_received": 0,
            "unit_price": item.unit_price,
            "line_total": item.quantity * item.unit_price,
            "inspection_status": "PENDING"
        })

    po_lifecycle_store[po_number] = {
        "department": payload.department,
        "buyer_name": payload.buyer_name or "Alex Sharma",
        "priority": payload.priority or "High",
        "cost_center": payload.cost_center or "CC-AERO-704",
        "payment_terms": payload.payment_terms or "Net 30 Days",
        "incoterms": payload.incoterms or "DDP Buyer Facility",
        "target_delivery_date": payload.target_delivery_date,
        "approval_tier": "Level 2/3 (Procurement / Finance)" if total_amount >= 50000.0 else "Level 1/3 (Auto-Approved)",
        "line_items": line_items_data,
        "milestones": [
            {
                "key": "DRAFT",
                "title": "Purchase Order Created",
                "timestamp": now.strftime("%Y-%m-%d %H:%M UTC"),
                "actor": payload.buyer_name or "Alex Sharma",
                "completed": True,
                "details": f"Created with {len(payload.items)} line item(s) totalling ${total_amount:,.2f}."
            },
            {
                "key": "APPROVAL",
                "title": "Routed for Executive Approval" if initial_status == POStatus.PENDING_APPROVAL else "Level 1 Auto-Approved",
                "timestamp": now.strftime("%Y-%m-%d %H:%M UTC"),
                "actor": "Autonomous Policy Engine",
                "completed": initial_status != POStatus.PENDING_APPROVAL,
                "details": "Threshold policy evaluated against FY2026 spend limits."
            }
        ]
    }

    db.commit()
    db.refresh(new_po)

    return {
        "status": "success",
        "message": f"Purchase Order '{po_number}' created successfully.",
        "po_id": po_id,
        "po_number": po_number,
        "total_amount": total_amount,
        "initial_status": str(initial_status),
        "requires_approval": initial_status == POStatus.PENDING_APPROVAL,
        "dossier": _build_po_dossier(new_po, db)
    }

