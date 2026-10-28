from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import uuid

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])

class NotificationItem(BaseModel):
    id: str
    tenant_id: str
    company_name: str
    partner_company: str
    title: str
    message: str
    category: str  # DISPATCH, ORDER, RFQ, INVOICE, PAYMENT, INVENTORY, RISK, TWIN
    priority: str  # CRITICAL, HIGH, NORMAL, INFO
    action_url: str
    action_label: str
    read: bool
    created_at: str
    metadata: Optional[Dict[str, Any]] = None

def get_initial_notifications() -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    
    return [
        # === BUYER NOTIFICATIONS (AlphaHelion Global Buyer) ===
        {
            "id": "notif-b-01",
            "tenant_id": "buyer-mock",
            "company_name": "AlphaHelion Global (Buyer HQ)",
            "partner_company": "Apex Precision Engineering",
            "title": "Goods Dispatched: PO-2026-0042 in Transit",
            "message": "Apex Precision Engineering dispatched 500x CNC Turbine Housings via Express Freight. Ready for Goods-In receiving.",
            "category": "DISPATCH",
            "priority": "HIGH",
            "action_url": "/inventory",
            "action_label": "Receive (Goods In)",
            "read": False,
            "created_at": (now - timedelta(minutes=4)).isoformat(),
            "metadata": {"po_id": "PO-2026-0042", "qty": 500, "sku": "SKU-TURB-09"}
        },
        {
            "id": "notif-b-02",
            "tenant_id": "buyer-mock",
            "company_name": "AlphaHelion Global (Buyer HQ)",
            "partner_company": "TechCast Forgings Ltd.",
            "title": "New Quotation Received for RFQ-AERO-882",
            "message": "TechCast submitted competitive quote of $48,200 for 1,200 Titanium Flanges with 14-day delivery commitment.",
            "category": "RFQ",
            "priority": "NORMAL",
            "action_url": "/rfqs",
            "action_label": "Review Quote",
            "read": False,
            "created_at": (now - timedelta(minutes=22)).isoformat(),
            "metadata": {"rfq_id": "RFQ-AERO-882", "amount": 48200}
        },
        {
            "id": "notif-b-03",
            "tenant_id": "buyer-mock",
            "company_name": "AlphaHelion Global (Buyer HQ)",
            "partner_company": "Apex Precision Tooling",
            "title": "3-Way Match Passed: Invoice INV-2026-104",
            "message": "Invoice #INV-2026-104 ($14,800) successfully auto-verified against PO-2026-0038 and Goods Receipt GRN-892. Ready for payment.",
            "category": "INVOICE",
            "priority": "NORMAL",
            "action_url": "/invoices",
            "action_label": "Approve Payment",
            "read": False,
            "created_at": (now - timedelta(hours=1, minutes=10)).isoformat(),
            "metadata": {"invoice_id": "INV-2026-104", "amount": 14800}
        },
        {
            "id": "notif-b-04",
            "tenant_id": "buyer-mock",
            "company_name": "AlphaHelion Global (Buyer HQ)",
            "partner_company": "Global Logistics Intelligence",
            "title": "Risk Command Alert: Port Congestion Advisory",
            "message": "Port of Rotterdam dock congestion alert flagged. 3 active inbound shipments may experience +48h delivery latency.",
            "category": "RISK",
            "priority": "CRITICAL",
            "action_url": "/risk",
            "action_label": "Inspect Risk Radar",
            "read": False,
            "created_at": (now - timedelta(hours=2, minutes=30)).isoformat(),
            "metadata": {"port": "Rotterdam", "severity": "HIGH"}
        },
        {
            "id": "notif-b-05",
            "tenant_id": "buyer-mock",
            "company_name": "AlphaHelion Global (Buyer HQ)",
            "partner_company": "Internal Warehouse Hub",
            "title": "Low Stock Threshold: Ti-6Al-4V Aerospace Rods",
            "message": "Inventory for Titanium Ti-6Al-4V dropped to 45 units (Safety buffer: 100 units). Restock PO suggested.",
            "category": "INVENTORY",
            "priority": "HIGH",
            "action_url": "/inventory",
            "action_label": "Restock Item",
            "read": True,
            "created_at": (now - timedelta(hours=4)).isoformat(),
            "metadata": {"sku": "RAW-TI-001", "level": 45}
        },
        {
            "id": "notif-b-06",
            "tenant_id": "buyer-mock",
            "company_name": "AlphaHelion Global (Buyer HQ)",
            "partner_company": "Apex Precision Engineering",
            "title": "Digital Twin Telemetry Calibrated",
            "message": "Apex Precision machine telemetry OEE health score upgraded to 91.2% following 5-axis CNC recalibration.",
            "category": "TWIN",
            "priority": "INFO",
            "action_url": "/network",
            "action_label": "View Twin Telemetry",
            "read": True,
            "created_at": (now - timedelta(hours=6)).isoformat(),
            "metadata": {"supplier_id": "sup-apex-01", "oee": 91.2}
        },

        # === SUPPLIER NOTIFICATIONS (Apex Precision Tooling) ===
        {
            "id": "notif-s-01",
            "tenant_id": "supplier-mock",
            "company_name": "Apex Precision Tooling Inc.",
            "partner_company": "AlphaHelion Global (Buyer)",
            "title": "Contract Awarded: RFQ-AERO-442 Approved",
            "message": "AlphaHelion Global selected your quotation for 800 Aerospace Hydraulic Actuators. Total Contract Value: $124,500.",
            "category": "RFQ",
            "priority": "HIGH",
            "action_url": "/supplier/rfqs",
            "action_label": "Accept & Generate PO",
            "read": False,
            "created_at": (now - timedelta(minutes=6)).isoformat(),
            "metadata": {"rfq_id": "RFQ-AERO-442", "contract_value": 124500}
        },
        {
            "id": "notif-s-02",
            "tenant_id": "supplier-mock",
            "company_name": "Apex Precision Tooling Inc.",
            "partner_company": "AlphaHelion Global (Buyer)",
            "title": "New Purchase Order Received: PO-2026-0091",
            "message": "New purchase order issued by AlphaHelion Buyer for 250 Shaft Assemblies ($84,200). Required delivery: 15 business days.",
            "category": "ORDER",
            "priority": "HIGH",
            "action_url": "/supplier/orders",
            "action_label": "Acknowledge Order",
            "read": False,
            "created_at": (now - timedelta(minutes=35)).isoformat(),
            "metadata": {"po_id": "PO-2026-0091", "amount": 84200}
        },
        {
            "id": "notif-s-03",
            "tenant_id": "supplier-mock",
            "company_name": "Apex Precision Tooling Inc.",
            "partner_company": "AlphaHelion Global (Buyer)",
            "title": "Payment Remittance Cleared: $45,200 Deposited",
            "message": "Automated Clearing settlement completed for Invoice INV-2026-098. Wire transfer deposited to Operating Account.",
            "category": "PAYMENT",
            "priority": "NORMAL",
            "action_url": "/supplier/payments",
            "action_label": "View Remittance Advice",
            "read": False,
            "created_at": (now - timedelta(hours=1, minutes=45)).isoformat(),
            "metadata": {"invoice_id": "INV-2026-098", "deposit": 45200}
        },
        {
            "id": "notif-s-04",
            "tenant_id": "supplier-mock",
            "company_name": "Apex Precision Tooling Inc.",
            "partner_company": "AlphaHelion Global (Buyer)",
            "title": "Goods Receipt Confirmed for PO-2026-0038",
            "message": "Buyer warehouse accepted delivery of 300 Rotor Pins. Quality acceptance score: 100%. Invoice milestone unlocked.",
            "category": "DISPATCH",
            "priority": "NORMAL",
            "action_url": "/supplier/invoices",
            "action_label": "Issue Invoice",
            "read": True,
            "created_at": (now - timedelta(hours=3, minutes=20)).isoformat(),
            "metadata": {"po_id": "PO-2026-0038", "status": "DELIVERED"}
        },
        {
            "id": "notif-s-05",
            "tenant_id": "supplier-mock",
            "company_name": "Apex Precision Tooling Inc.",
            "partner_company": "Global Verification Bureau",
            "title": "Digital Twin Audit Score: 98/100 Certified",
            "message": "Annual ISO-9001 and AS9100D supplier digital twin capability verification audited with zero non-conformances.",
            "category": "TWIN",
            "priority": "INFO",
            "action_url": "/supplier/profile",
            "action_label": "View Capability Twin",
            "read": True,
            "created_at": (now - timedelta(hours=8)).isoformat(),
            "metadata": {"audit_score": 98}
        }
    ]

NOTIFICATIONS_DB: List[Dict[str, Any]] = get_initial_notifications()

@router.get("")
def list_notifications(
    tenant_id: Optional[str] = Query("buyer-mock"),
    role: Optional[str] = Query(None),
    unread_only: bool = Query(False),
    category: Optional[str] = Query(None)
):
    active_tenant = "supplier-mock" if (role == "supplier" or tenant_id == "supplier-mock") else "buyer-mock"
    
    results = [n for n in NOTIFICATIONS_DB if n["tenant_id"] == active_tenant]
    
    if unread_only:
        results = [n for n in results if not n["read"]]
    if category and category.upper() != "ALL":
        results = [n for n in results if n["category"].upper() == category.upper()]
        
    unread_count = sum(1 for n in NOTIFICATIONS_DB if n["tenant_id"] == active_tenant and not n["read"])
    
    return {
        "status": "success",
        "tenant_id": active_tenant,
        "company_name": "AlphaHelion Global (Buyer HQ)" if active_tenant == "buyer-mock" else "Apex Precision Tooling Inc.",
        "unread_count": unread_count,
        "total_count": len([n for n in NOTIFICATIONS_DB if n["tenant_id"] == active_tenant]),
        "server_time": datetime.now(timezone.utc).isoformat(),
        "notifications": results
    }

@router.post("/{notification_id}/read")
def mark_read(notification_id: str):
    for n in NOTIFICATIONS_DB:
        if n["id"] == notification_id:
            n["read"] = True
            return {"status": "success", "id": notification_id, "read": True}
    raise HTTPException(status_code=404, detail="Notification not found")

@router.post("/{notification_id}/unread")
def mark_unread(notification_id: str):
    for n in NOTIFICATIONS_DB:
        if n["id"] == notification_id:
            n["read"] = False
            return {"status": "success", "id": notification_id, "read": False}
    raise HTTPException(status_code=404, detail="Notification not found")

@router.post("/mark-all-read")
def mark_all_read(tenant_id: Optional[str] = Query("buyer-mock"), role: Optional[str] = Query(None)):
    active_tenant = "supplier-mock" if (role == "supplier" or tenant_id == "supplier-mock") else "buyer-mock"
    count = 0
    for n in NOTIFICATIONS_DB:
        if n["tenant_id"] == active_tenant and not n["read"]:
            n["read"] = True
            count += 1
    return {"status": "success", "tenant_id": active_tenant, "marked_count": count}

@router.delete("/{notification_id}")
def delete_notification(notification_id: str):
    global NOTIFICATIONS_DB
    before_len = len(NOTIFICATIONS_DB)
    NOTIFICATIONS_DB = [n for n in NOTIFICATIONS_DB if n["id"] != notification_id]
    if len(NOTIFICATIONS_DB) == before_len:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"status": "success", "deleted_id": notification_id}

@router.post("/clear")
def clear_notifications(tenant_id: Optional[str] = Query("buyer-mock"), role: Optional[str] = Query(None)):
    global NOTIFICATIONS_DB
    active_tenant = "supplier-mock" if (role == "supplier" or tenant_id == "supplier-mock") else "buyer-mock"
    NOTIFICATIONS_DB = [n for n in NOTIFICATIONS_DB if n["tenant_id"] != active_tenant]
    return {"status": "success", "tenant_id": active_tenant, "remaining": len(NOTIFICATIONS_DB)}

@router.post("/simulate")
def simulate_workflow_event(
    tenant_id: Optional[str] = Query("buyer-mock"),
    role: Optional[str] = Query(None),
    event_type: Optional[str] = Query("DISPATCH")
):
    active_tenant = "supplier-mock" if (role == "supplier" or tenant_id == "supplier-mock") else "buyer-mock"
    now = datetime.now(timezone.utc)
    new_id = f"notif-live-{str(uuid.uuid4())[:8]}"
    
    if active_tenant == "buyer-mock":
        event_templates = {
            "DISPATCH": {
                "title": "Live Dispatch: PO-2026-0099 Shipped",
                "message": "Apex Precision dispatched 240x Aerospace Valve Bodies via DHL Express. GPS Tracking active.",
                "category": "DISPATCH",
                "priority": "HIGH",
                "action_url": "/inventory",
                "action_label": "Receive (Goods In)",
                "partner_company": "Apex Precision Engineering"
            },
            "INVOICE": {
                "title": "New Invoice Submitted: INV-2026-118",
                "message": "TechCast Forgings submitted invoice for $32,400. 3-way reconciliation in progress.",
                "category": "INVOICE",
                "priority": "NORMAL",
                "action_url": "/invoices",
                "action_label": "Review Invoice",
                "partner_company": "TechCast Forgings Ltd."
            },
            "RFQ": {
                "title": "New Quotation: RFQ-AERO-920",
                "message": "Titanium Forgings submitted proposal with 8% volume discount ($94,100).",
                "category": "RFQ",
                "priority": "HIGH",
                "action_url": "/rfqs",
                "action_label": "Inspect Quote",
                "partner_company": "Titanium Forgings Global"
            }
        }
    else:
        event_templates = {
            "RFQ": {
                "title": "Live RFQ: AlphaHelion RFQ-AERO-990",
                "message": "AlphaHelion Global Buyer invited your shop to bid on 600 Titanium Flanges ($78,000).",
                "category": "RFQ",
                "priority": "HIGH",
                "action_url": "/supplier/rfqs",
                "action_label": "Submit Bid",
                "partner_company": "AlphaHelion Global (Buyer)"
            },
            "PAYMENT": {
                "title": "Wire Transfer Released: $58,900",
                "message": "AlphaHelion Finance Desk released batch payment for INV-2026-092.",
                "category": "PAYMENT",
                "priority": "HIGH",
                "action_url": "/supplier/payments",
                "action_label": "View Payment",
                "partner_company": "AlphaHelion Global (Buyer)"
            },
            "ORDER": {
                "title": "Urgent PO Issued: PO-2026-0112",
                "message": "New urgent production run requested for 150 Engine Brackets ($42,000).",
                "category": "ORDER",
                "priority": "HIGH",
                "action_url": "/supplier/orders",
                "action_label": "Confirm PO",
                "partner_company": "AlphaHelion Global (Buyer)"
            }
        }
        
    tpl = event_templates.get(event_type.upper(), list(event_templates.values())[0])
    
    new_notif = {
        "id": new_id,
        "tenant_id": active_tenant,
        "company_name": "AlphaHelion Global (Buyer HQ)" if active_tenant == "buyer-mock" else "Apex Precision Tooling Inc.",
        "partner_company": tpl["partner_company"],
        "title": tpl["title"],
        "message": tpl["message"],
        "category": tpl["category"],
        "priority": tpl["priority"],
        "action_url": tpl["action_url"],
        "action_label": tpl["action_label"],
        "read": False,
        "created_at": now.isoformat(),
        "metadata": {"simulated": True, "event_type": event_type}
    }
    
    NOTIFICATIONS_DB.insert(0, new_notif)
    return {"status": "success", "notification": new_notif}
